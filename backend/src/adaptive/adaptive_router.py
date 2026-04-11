"""
FastAPI router for the Adaptive Learning Generation Engine.
Registered at prefix /api/v3 in main.py.

Injection pattern: module-level globals (adaptive_knowledge_svc,
adaptive_llm_client) are set by main.py's lifespan context manager,
identical to the pattern used in api/teaching_router.py.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import APIRouter, Depends, HTTPException, Request
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uuid import UUID

from auth.dependencies import get_current_user
from auth.models import User
from adaptive.schemas import AdaptiveLessonRequest, AdaptiveLesson, NextCardRequest, NextCardResponse
from adaptive.adaptive_engine import generate_adaptive_lesson, generate_recovery_card
from api.rate_limiter import limiter
from db.connection import get_db
from db.models import Student, StudentMastery
from config import ADAPTIVE_CARD_MODEL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3", tags=["adaptive"])

# Secondary router for card-completion endpoints mounted under /api/v2
# (cards endpoint must live at /api/v2/sessions/{id}/complete-card, not /api/v3)
cards_router = APIRouter(tags=["adaptive-cards"])

# ── Service references — injected by main.py lifespan ─────────────────────────
# Set to None here; main.py assigns real instances after startup.
adaptive_chunk_ksvc = None               # ChunkKnowledgeService (injected by main.py)
adaptive_llm_client: AsyncOpenAI | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/adaptive/lesson",
    response_model=AdaptiveLesson,
    summary="Generate an adaptive lesson",
    description=(
        "Analyse a student's analytics signals, classify their learning profile, "
        "derive generation parameters, optionally insert prerequisite remediation "
        "cards, and call the LLM to produce a fully personalised lesson."
    ),
)
@limiter.limit("10/minute")
async def generate_lesson(
    request: Request,
    req: AdaptiveLessonRequest,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdaptiveLesson:
    """
    POST /api/v3/adaptive/lesson

    Steps:
      1. Verify the student exists in the DB (returns 404 if not).
      2. Load the student's mastery state in a single bulk SELECT (no N+1).
      3. Call generate_adaptive_lesson() from the engine module.

    Error responses:
      404 — student_id not found in the students table
      404 — concept_id not found in KnowledgeService (raised by engine as ValueError)
      502 — LLM failed after all retries (raised by engine as ValueError)
      500 — unexpected internal error
    """
    # 1. Verify student exists
    student = await db.get(Student, req.student_id)
    if student is None:
        raise HTTPException(
            status_code=404,
            detail=f"Student not found: {req.student_id}",
        )

    # Resolve student's preferred language for LLM output
    language: str = getattr(student, "preferred_language", None) or "en"

    # 2. Bulk-load mastery state — one SELECT for all mastered concepts
    result = await db.execute(
        select(StudentMastery.concept_id).where(
            StudentMastery.student_id == req.student_id
        )
    )
    mastery_store: dict[str, bool] = {
        cid: True for cid in result.scalars().all()
    }
    logger.info(
        "Student %s has %d mastered concepts",
        req.student_id,
        len(mastery_store),
    )

    # 3. Delegate to the engine
    book_slug = getattr(req, "book_slug", None) or "prealgebra"
    try:
        lesson = await generate_adaptive_lesson(
            student_id=str(req.student_id),
            concept_id=req.concept_id,
            analytics_summary=req.analytics_summary,
            chunk_ksvc=adaptive_chunk_ksvc,
            book_slug=book_slug,
            db=db,
            mastery_store=mastery_store,
            llm_client=adaptive_llm_client,
            language=language,
        )
    except ValueError as exc:
        error_msg = str(exc)
        # Concept-not-found errors should be surfaced as 404
        if "Concept not found" in error_msg:
            logger.warning("Concept lookup failed: %s", error_msg)
            raise HTTPException(status_code=404, detail=error_msg)
        # LLM failures → 502
        logger.error("Adaptive engine error: %s", error_msg)
        raise HTTPException(status_code=502, detail=error_msg)
    except Exception as exc:
        logger.exception("Unexpected error in adaptive engine: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return lesson


# ── Card-completion adaptive endpoint ─────────────────────────────────────────

@cards_router.post(
    "/api/v2/sessions/{session_id}/complete-card",
    response_model=NextCardResponse,
    summary="Record card completion and generate the next adaptive card",
    description=(
        "Persists the student's card interaction signals, loads their history, "
        "blends current signals with historical baselines, generates an adaptive "
        "next card via the LLM, and returns it with motivational context."
    ),
)
@limiter.limit("60/minute")
async def complete_card(
    request: Request,
    session_id: UUID,
    req: NextCardRequest,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /api/v2/sessions/{session_id}/complete-card

    Steps:
      1. Load and validate the session.
      2. Save the CardInteraction row immediately.
      3. Parse existing cards from the session cache (for index tracking).
      4. Load the student's full interaction history for blending.
      5. Load the student's mastery store (bulk SELECT, no N+1).
      6. Call generate_next_card() from the adaptive engine.
      7. Compute performance_vs_baseline comparison string.
      8. Append the new card to session.presentation_text cache.
      9. Commit and return NextCardResponse.

    Error responses:
      400 — Session not in PRESENTING or CARDS phase
      404 — Session not found
      502 — LLM failed after all retries
    """
    from sqlalchemy import select
    from db.models import CardInteraction, Student, TeachingSession, StudentMastery
    from adaptive.adaptive_engine import load_student_history, generate_next_card

    # 1. Load session
    session_result = await db.execute(
        select(TeachingSession).where(TeachingSession.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.phase not in ("PRESENTING", "CARDS"):
        raise HTTPException(
            status_code=400,
            detail=f"Session phase '{session.phase}' does not accept card signals",
        )

    # 2. Load student language preference
    student_result = await db.execute(
        select(Student).where(Student.id == session.student_id)
    )
    student = student_result.scalar_one_or_none()
    language = student.preferred_language if student else "en"

    # 3. Save CardInteraction immediately
    interaction = CardInteraction(
        session_id=session_id,
        student_id=session.student_id,
        concept_id=session.concept_id,
        card_index=req.card_index,
        time_on_card_sec=req.time_on_card_sec,
        wrong_attempts=req.wrong_attempts,
        selected_wrong_option=req.selected_wrong_option,
        hints_used=req.hints_used,
        idle_triggers=req.idle_triggers,
    )
    db.add(interaction)
    await db.flush()
    await db.commit()   # Persist immediately — before any code that can fail or time out

    # 4. Parse existing cards from the session cache (for index tracking)
    existing_cards: list = []
    if session.presentation_text:
        try:
            parsed = json.loads(session.presentation_text)
            if isinstance(parsed, list):
                existing_cards = parsed
            elif isinstance(parsed, dict) and "cards" in parsed:
                # teaching_service stores dict format on first generation; extract the list
                existing_cards = parsed["cards"]
        except Exception:
            existing_cards = []

    # 5. Load student history
    history = await load_student_history(str(session.student_id), session.concept_id, db)

    # 6. Load mastery store (bulk SELECT — no N+1)
    mastery_result = await db.execute(
        select(StudentMastery.concept_id)
        .where(StudentMastery.student_id == session.student_id)
    )
    mastery_store = {cid: True for cid in mastery_result.scalars().all()}

    # 7. Generate next card (and optional recovery card in parallel)
    need_recovery = (
        req.wrong_attempts >= 2
        and bool(req.re_explain_card_title)
        and not (req.re_explain_card_title or "").startswith("Let's Try Again")
    )

    # Use session-level overrides first, then fall back to student profile
    effective_interests = (
        getattr(session, "lesson_interests", None) or
        getattr(student, "interests", []) or []
    )
    effective_style = (
        getattr(session, "style", None) or
        getattr(student, "preferred_style", "default") or "default"
    )

    # Resolve book_slug for this session
    session_book_slug = getattr(session, "book_slug", None) or "prealgebra"

    async def _maybe_recovery():
        if need_recovery:
            return await generate_recovery_card(
                topic_title=req.re_explain_card_title,
                concept_id=session.concept_id,
                chunk_ksvc=adaptive_chunk_ksvc,
                book_slug=session_book_slug,
                db=db,
                llm_client=adaptive_llm_client,
                language=language,
                interests=effective_interests,
                style=effective_style,
            )
        return None

    try:
        gather_results = await asyncio.gather(
            generate_next_card(
                student_id=str(session.student_id),
                concept_id=session.concept_id,
                signals=req,
                card_index=len(existing_cards),
                history=history,
                chunk_ksvc=adaptive_chunk_ksvc,
                book_slug=session_book_slug,
                mastery_store=mastery_store,
                llm_client=adaptive_llm_client,
                model=ADAPTIVE_CARD_MODEL,
                language=language,
                db=db,
            ),
            _maybe_recovery(),
            return_exceptions=True,
        )
    except Exception as exc:
        logger.error("generate_next_card gather failed: %s", exc)
        await db.commit()
        raise HTTPException(status_code=502, detail="Adaptive card generation failed")

    next_card_result = gather_results[0]
    recovery_result  = gather_results[1]

    if isinstance(next_card_result, Exception):
        logger.error("generate_next_card failed: %s", next_card_result)
        await db.commit()
        raise HTTPException(status_code=502, detail="Adaptive card generation failed")

    card_dict, profile, gen_profile, motivational_note, adaptation_label = next_card_result

    recovery_card = None
    if need_recovery:
        if isinstance(recovery_result, Exception):
            logger.warning("generate_recovery_card failed (non-fatal): %s", recovery_result)
        elif isinstance(recovery_result, dict):
            recovery_card = recovery_result
            logger.info("[recovery] session=%s topic=%r generated", session_id, req.re_explain_card_title)

    # 7b. Apply section_id inference on the single new card (sort is a no-op for one card,
    # but section_id inference is useful if the LLM omitted it).
    try:
        from api.teaching_service import validate_and_repair_cards
        section_order = [c.get("section_id", "") for c in existing_cards if c.get("section_id")]
        repaired_single, _ = validate_and_repair_cards([card_dict], section_order or ["unknown"])
        if repaired_single:
            card_dict = repaired_single[0]
    except Exception as _vrc_exc:
        logger.warning("validate_and_repair_cards on adaptive card failed (non-fatal): %s", _vrc_exc)

    # 8. Compute performance_vs_baseline
    avg_time = history.get("avg_time_per_card")
    if avg_time and avg_time > 0:
        if req.time_on_card_sec < avg_time * 0.75 and req.wrong_attempts == 0:
            perf = "FASTER"
        elif req.time_on_card_sec > avg_time * 1.5:
            perf = "SLOWER"
        else:
            perf = "ON_TRACK"
    else:
        perf = None

    # 9. Update adaptation_applied on the interaction row
    adaptation_str = adaptation_label
    interaction.adaptation_applied = adaptation_str

    # 10. Append new card to the session's presentation cache and set phase
    existing_cards.append(card_dict)
    # RC3-B: Preserve the JSON envelope (cache_version, concept_title, etc.) when
    # appending adaptive cards. Without this, a page refresh would re-trigger
    # full generation because the cache_version key disappears.
    if session.presentation_text:
        try:
            envelope = json.loads(session.presentation_text)
            if isinstance(envelope, dict) and "cards" in envelope:
                envelope["cards"] = existing_cards
                session.presentation_text = json.dumps(envelope)
            else:
                session.presentation_text = json.dumps(existing_cards)
        except Exception:
            session.presentation_text = json.dumps(existing_cards)
    else:
        session.presentation_text = json.dumps(existing_cards)
    session.phase = "CARDS"

    await db.commit()

    return NextCardResponse(
        session_id=session_id,
        card=card_dict,
        card_index=card_dict["index"],
        adaptation_applied=adaptation_str,
        learning_profile_summary={
            "speed": profile.speed,
            "comprehension": profile.comprehension,
            "engagement": profile.engagement,
            "confidence_score": profile.confidence_score,
        },
        motivational_note=motivational_note,
        performance_vs_baseline=perf,
        recovery_card=recovery_card,
    )
