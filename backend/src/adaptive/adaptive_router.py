"""
FastAPI router for the Adaptive Learning Generation Engine.
Registered at prefix /api/v3 in main.py.

Injection pattern: module-level globals (adaptive_knowledge_svc,
adaptive_llm_client) are set by main.py's lifespan context manager,
identical to the pattern used in api/teaching_router.py.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uuid import UUID

from adaptive.schemas import AdaptiveLessonRequest, AdaptiveLesson, NextCardRequest, NextCardResponse
from adaptive.adaptive_engine import generate_adaptive_lesson
from db.connection import get_db
from db.models import Student, StudentMastery
from config import ADAPTIVE_CARD_CEILING, ADAPTIVE_CARD_MODEL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3", tags=["adaptive"])

# Secondary router for card-completion endpoints mounted under /api/v2
# (cards endpoint must live at /api/v2/sessions/{id}/complete-card, not /api/v3)
cards_router = APIRouter(tags=["adaptive-cards"])

# ── Service references — injected by main.py lifespan ─────────────────────────
# Set to None here; main.py assigns real instances after startup.
adaptive_knowledge_svc = None          # KnowledgeService
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
async def generate_lesson(
    req: AdaptiveLessonRequest,
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
    try:
        lesson = await generate_adaptive_lesson(
            student_id=str(req.student_id),
            concept_id=req.concept_id,
            analytics_summary=req.analytics_summary,
            knowledge_svc=adaptive_knowledge_svc,
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
        "next card via the LLM, and returns it with motivational context. "
        "Returns 409 when the 8-card ceiling is reached."
    ),
)
async def complete_card(
    session_id: UUID,
    req: NextCardRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    POST /api/v2/sessions/{session_id}/complete-card

    Steps:
      1. Load and validate the session.
      2. Save the CardInteraction row immediately.
      3. Check the 8-card ceiling — return 409 if reached.
      4. Load the student's full interaction history for blending.
      5. Load the student's mastery store (bulk SELECT, no N+1).
      6. Call generate_next_card() from the adaptive engine.
      7. Compute performance_vs_baseline comparison string.
      8. Append the new card to session.presentation_text cache.
      9. Commit and return NextCardResponse.

    Error responses:
      400 — Session not in PRESENTING or CARDS phase
      404 — Session not found
      409 — Card ceiling (8 cards) reached
      502 — LLM failed after all retries
    """
    import json as json_mod
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

    # 4. Check ceiling — parse existing cards from the session cache
    existing_cards: list = []
    if session.presentation_text:
        try:
            parsed = json_mod.loads(session.presentation_text)
            if isinstance(parsed, list):
                existing_cards = parsed
            elif isinstance(parsed, dict) and "cards" in parsed:
                # teaching_service stores dict format on first generation; extract the list
                existing_cards = parsed["cards"]
        except Exception:
            existing_cards = []

    if len(existing_cards) >= ADAPTIVE_CARD_CEILING:
        await db.commit()
        raise HTTPException(status_code=409, detail={"ceiling": True})

    # 5. Load student history
    history = await load_student_history(str(session.student_id), session.concept_id, db)

    # 6. Load mastery store (bulk SELECT — no N+1)
    mastery_result = await db.execute(
        select(StudentMastery.concept_id)
        .where(StudentMastery.student_id == session.student_id)
    )
    mastery_store = {cid: True for cid in mastery_result.scalars().all()}

    # 7. Generate next card
    try:
        card_dict, profile, gen_profile, motivational_note, adaptation_label = await generate_next_card(
            student_id=str(session.student_id),
            concept_id=session.concept_id,
            signals=req,
            card_index=len(existing_cards),
            history=history,
            knowledge_svc=adaptive_knowledge_svc,
            mastery_store=mastery_store,
            llm_client=adaptive_llm_client,
            model=ADAPTIVE_CARD_MODEL,
            language=language,
        )
    except Exception as exc:
        logger.error("generate_next_card failed: %s", exc)
        await db.commit()
        raise HTTPException(status_code=502, detail="Adaptive card generation failed")

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
    session.presentation_text = json_mod.dumps(existing_cards)
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
    )
