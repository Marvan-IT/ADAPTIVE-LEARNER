"""
Week 2 API endpoints: The Pedagogical Loop.
Teaching sessions, Socratic checks, style switching.
"""

import re
from datetime import datetime, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_, update
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import logging

import asyncio
import json

from auth.dependencies import get_current_user, require_admin
from auth.models import User
from config import (
    BOOK_REGISTRY,
    CARD_HISTORY_DEFAULT_LIMIT,
    CARD_HISTORY_MAX_LIMIT,
    CHUNK_EXAM_PASS_RATE,
    CUSTOM_INTERESTS_MAX,
    OPENAI_MODEL_MINI,
    PREDEFINED_INTEREST_IDS,
)

def _get_book_title(book_slug: str) -> str:
    """Look up human-readable book title from BOOK_REGISTRY by slug."""
    for entry in BOOK_REGISTRY.values():
        if isinstance(entry, dict) and entry.get("book_slug") == book_slug:
            return entry.get("title", book_slug)
    return book_slug
from adaptive.adaptive_engine import build_blended_analytics, load_student_history
from adaptive.schemas import CardBehaviorSignals
from db.connection import get_db
from db.models import Student, TeachingSession, StudentMastery, SpacedReview, CardInteraction
from db.models import ConceptChunk, ChunkImage
from api.teaching_schemas import (
    CreateStudentRequest, StudentResponse,
    StartSessionRequest, SessionResponse,
    PresentationResponse,
    SessionHistoryResponse, MessageResponse,
    CardsResponse, LessonCard,
    AssistRequest, AssistResponse,
    UpdateLanguageRequest,
    StudentAnalyticsResponse,
    ConceptReadinessResponse,
    RegenerateMCQRequest, RegenerateMCQResponse,
    CompleteCardRequest, CompleteCardResponse,
    ChunkCardsRequest, ChunkCardsResponse,
    ChunkExamQuestion,
    ChunkEvaluateRequest,
    ChunkEvaluateResponse,
    ChunkEvaluateFeedback,
    RecoveryCardRequest,
    CompleteChunkRequest, CompleteChunkResponse,
    CompleteChunkItemResponse,
    ChunkSummary, ChunkListResponse,
    StudentLanguageResponse,
    ChunkPreviewItem, ChunkPreviewResponse,
    ValidateCustomInterestRequest, ValidateCustomInterestResponse,
)
from api.cache_accessor import CacheAccessor
from api.rate_limiter import limiter
from api.prompts import _language_instruction

logger = logging.getLogger(__name__)


def _get_chunk_type(heading: str, text: str = "") -> str:
    """Classify a chunk heading into one of five canonical types.
    Priority order (first match wins):
      1. section_review  — matches ^\\d+\\.\\d+\\s+  (e.g. "1.2 Add Whole Numbers")
      2. learning_objective — contains 'learning objectives', 'be prepared', 'key terms', 'key concepts', 'summary'
      3. exercise (optional) — contains 'writing exercises'
      4. exercise — contains 'practice makes perfect', 'everyday math', 'mixed practice'
      5. section_review (exam source) — matches ^section \\d+ or contains '(exercises)'
      6. teaching — everything else
    Note: 'exercise_gate' is never returned here; it is only injected by list_chunks().
    Returns: 'learning_objective' | 'section_review' | 'teaching' | 'exercise'
    """
    raw = re.sub(r"^[-–—•\s]+", "", heading).strip()
    h = raw.lower()

    # 1. Section title heading (e.g. "1.2 Add Whole Numbers") — classified as section_review
    if (re.match(r"^\d+\.\d+\s+\w", h)
            and not h.rstrip().endswith(":")
            and "exercises" not in h):
        chunk_type = "section_review"

    # 2. Info/objective panels — non-interactive, non-required
    elif any(p in h for p in ("learning objectives", "be prepared", "key terms", "key concepts", "summary")):
        chunk_type = "learning_objective"

    # 3. Optional writing exercise chunks (singular and plural)
    elif "writing exercise" in h:
        chunk_type = "exercise"

    # 4. Required exercise chunks (practice, everyday math, mixed practice)
    elif any(p in h for p in ("practice makes perfect", "everyday math", "mixed practice")):
        chunk_type = "exercise"

    # 5. Review/exam-source chunks
    elif "(exercises)" in h:
        chunk_type = "exercise"
    elif re.match(r"^section\s+\d+\.\d+", h) and "exercises" in h:
        chunk_type = "exercise"
    elif "review exercises" in h or "practice test" in h:
        chunk_type = "exercise"

    # 6. Default: teaching chunk
    else:
        chunk_type = "teaching"

    # section_review (bare section-title headings) with real content → reclassify as teaching
    # learning_objective is NEVER reclassified — long LO blocks are still info cards
    if chunk_type == "section_review" and len((text or "").strip()) > 200:
        return "teaching"
    return chunk_type


def _effective_chunk_type(c: dict) -> str:
    return c.get("chunk_type") or _get_chunk_type(c.get("heading", ""), c.get("text", ""))


router = APIRouter(prefix="/api/v2", tags=["teaching"])


# ── Request / response schemas for new endpoints ──────────────────────────────

class ProgressUpdate(BaseModel):
    xp_delta: int = Field(default=0, ge=0, description="XP to add (non-negative)")
    streak: int = Field(default=0, ge=0, description="Absolute new streak value")


class RecordInteractionRequest(BaseModel):
    card_index: int = Field(..., ge=0)
    time_on_card_sec: float = Field(default=0.0, ge=0)
    wrong_attempts: int = Field(default=0, ge=0)
    hints_used: int = Field(default=0, ge=0)
    idle_triggers: int = Field(default=0, ge=0)
    adaptation_applied: str | None = None
    engagement_signal: str | None = None
    strategy_applied: str | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5, description="Card difficulty 1-5 from LLM")
    is_correct: bool = Field(default=False, description="Whether the student answered correctly")

async def _award_xp(
    student_id: UUID,
    xp_delta: int,
    new_streak: int,
    mastered: bool,
    score: int | None,
    db: AsyncSession,
) -> None:
    """Atomically update a student's XP and streak after a session completes."""
    try:
        await db.execute(
            update(Student)
            .where(Student.id == student_id)
            .values(xp=Student.xp + xp_delta, streak=new_streak)
        )
        await db.commit()
        logger.info(
            "[xp-awarded] student_id=%s xp_delta=%d new_streak=%d mastered=%s score=%s",
            student_id, xp_delta, new_streak, mastered, score,
        )
    except Exception as exc:
        logger.warning(
            "[xp-award-failed] student_id=%s xp_delta=%d error=%s",
            student_id, xp_delta, exc,
        )


# Set during app startup in main.py lifespan
teaching_svc = None
chunk_ksvc = None  # ChunkKnowledgeService — injected by main.py lifespan


async def _validate_student_ownership(user: User, student_id: UUID, db: AsyncSession) -> None:
    """Ensure the authenticated user owns the student profile.

    Admins bypass the check and can access any student's data.
    For student-role users, the JWT's user_id must be linked to the requested
    student_id via Student.user_id.  Raises HTTP 403 if ownership cannot be
    confirmed.
    """
    if user.role == "admin":
        return  # Admins can access any student
    result = await db.execute(select(Student.id).where(Student.user_id == user.id))
    owned_id = result.scalar_one_or_none()
    if not owned_id or owned_id != student_id:
        raise HTTPException(status_code=403, detail="Access denied")


def _require_services():
    """Raise 503 if the backend services were not yet injected by lifespan.

    Prevents AttributeError crashes ('NoneType' has no attribute ...) when
    stale uvicorn processes or a mid-restart request reaches an endpoint before
    main.py lifespan has finished initialising teaching_svc / chunk_ksvc.
    """
    if not chunk_ksvc or not teaching_svc:
        raise HTTPException(
            status_code=503,
            detail="Service not ready — backend is still starting up, please retry in a moment",
        )


# ═══════════════════════════════════════════════════════════════════
# STUDENTS
# ═══════════════════════════════════════════════════════════════════

@router.post("/students", response_model=StudentResponse)
@limiter.limit("30/minute")
async def create_student(
    request: Request,
    req: CreateStudentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new student profile."""
    student = Student(
        display_name=req.display_name,
        interests=req.interests,
        preferred_style=req.preferred_style,
        preferred_language=req.preferred_language,
    )
    db.add(student)
    await db.flush()
    await db.commit()
    return student


@router.get("/students", summary="List all students")
@limiter.limit("120/minute")
async def list_students(
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = Query(0, ge=0),
    _user: User = Depends(require_admin),
):
    """List student profiles with their mastery counts (paginated). Admin only."""
    limit = min(max(1, limit), 200)
    result = await db.execute(
        select(
            Student,
            func.count(StudentMastery.id).label("mastered_count"),
        )
        .outerjoin(StudentMastery, StudentMastery.student_id == Student.id)
        .group_by(Student.id)
        .order_by(Student.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.all()
    return [
        {
            "id": str(s.id),
            "display_name": s.display_name,
            "interests": s.interests or [],
            "preferred_style": s.preferred_style,
            "preferred_language": s.preferred_language or "en",
            "mastered_count": count or 0,
        }
        for s, count in rows
    ]


@router.get("/students/{student_id}")
@limiter.limit("120/minute")
async def get_student(
    request: Request,
    student_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get student profile including xp and streak."""
    await _validate_student_ownership(user, student_id, db)
    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(404, "Student not found")
    return {
        "id": str(student.id),
        "display_name": student.display_name,
        "age": student.age,
        "interests": student.interests or [],
        "custom_interests": student.custom_interests or [],
        "preferred_style": student.preferred_style,
        "preferred_language": student.preferred_language or "en",
        "created_at": student.created_at.isoformat(),
        "xp": student.xp,
        "streak": student.streak,
        "daily_streak": student.daily_streak or 0,
        "daily_streak_best": student.daily_streak_best or 0,
        "last_active_date": student.last_active_date.isoformat() if student.last_active_date else None,
    }


@router.post(
    "/students/{student_id}/custom-interests/validate",
    response_model=ValidateCustomInterestResponse,
    summary="Validate a custom interest text (format + LLM semantic check)",
)
@limiter.limit("30/minute")
async def validate_custom_interest_endpoint(
    request: Request,
    student_id: UUID,
    body: ValidateCustomInterestRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Validate a single custom interest text before persisting it.

    Always returns HTTP 200. The `ok` field indicates whether the text is acceptable.
    When `ok=False`, `reason` contains a stable error code that the frontend maps to
    a localised message (e.g. "too_short", "too_long", "invalid_chars", "duplicate_predefined",
    "duplicate_custom", "limit_reached", "unrecognized", "validator_unavailable").
    """
    from api.interest_validator import validate_custom_interest as _validate

    await _validate_student_ownership(user, student_id, db)
    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(404, "Student not found")

    language = body.language or student.preferred_language or "en"

    result = await _validate(
        text=body.text,
        language=language,
        existing_custom=list(student.custom_interests or []),
        predefined_ids=PREDEFINED_INTEREST_IDS,
    )
    return ValidateCustomInterestResponse(
        ok=result.ok,
        reason=result.reason,
        normalized=result.normalized,
    )


@router.get("/students/{student_id}/mastery")
@limiter.limit("30/minute")
async def get_student_mastery(
    request: Request,
    student_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all concepts mastered by a student."""
    await _validate_student_ownership(user, student_id, db)
    result = await db.execute(
        select(StudentMastery)
        .where(StudentMastery.student_id == student_id)
        .limit(2000)
    )
    records = result.scalars().all()
    return {
        "student_id": str(student_id),
        "mastered_concepts": [r.concept_id for r in records],
        "count": len(records),
    }


@router.get("/students/{student_id}/analytics", response_model=StudentAnalyticsResponse)
@limiter.limit("60/minute")
async def get_student_analytics(
    request: Request,
    student_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate learning analytics for a student across all four interaction tables."""
    await _validate_student_ownership(user, student_id, db)
    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(404, "Student not found")

    now = datetime.now(timezone.utc)

    # ── Query 1: StudentMastery ───────────────────────────────────────────────
    mastery_result = await db.execute(
        select(StudentMastery)
        .where(StudentMastery.student_id == student_id)
        .order_by(StudentMastery.mastered_at.asc())
        .limit(2000)
    )
    mastery_rows = mastery_result.scalars().all()
    total_concepts_mastered = len(mastery_rows)
    mastery_timeline = [
        {"concept_id": r.concept_id, "mastered_at": r.mastered_at.isoformat()}
        for r in mastery_rows
    ]

    # ── Query 2: TeachingSession ──────────────────────────────────────────────
    sessions_result = await db.execute(
        select(TeachingSession)
        .where(TeachingSession.student_id == student_id)
        .limit(2000)
    )
    all_sessions = sessions_result.scalars().all()

    attempted_concept_ids = {s.concept_id for s in all_sessions if s.completed_at is not None}
    total_concepts_attempted = len(attempted_concept_ids)

    if total_concepts_attempted > 0:
        mastery_rate = round(total_concepts_mastered / total_concepts_attempted, 3)
    else:
        mastery_rate = 0.0

    socratic_phases = {"CHECKING", "REMEDIATING", "RECHECKING", "COMPLETED", "ATTEMPTS_EXHAUSTED"}
    check_scores = [s.check_score for s in all_sessions if s.check_score is not None]
    avg_check_score = round(sum(check_scores) / len(check_scores), 3) if check_scores else None
    total_socratic_sessions = sum(1 for s in all_sessions if s.phase in socratic_phases)

    # ── Query 3: CardInteraction (SQL aggregation — no full-table fetch) ─────
    card_agg = await db.execute(
        select(
            func.count(CardInteraction.id).label("total"),
            func.coalesce(func.avg(CardInteraction.wrong_attempts), 0).label("avg_wrong"),
            func.coalesce(func.avg(CardInteraction.hints_used), 0).label("avg_hints"),
            func.coalesce(func.avg(CardInteraction.time_on_card_sec), 0).label("avg_time"),
            func.coalesce(func.sum(CardInteraction.time_on_card_sec), 0).label("total_time"),
        ).where(CardInteraction.student_id == student_id)
    )
    agg_row = card_agg.one()
    total_cards = int(agg_row.total or 0)
    avg_wrong_attempts_per_card = round(float(agg_row.avg_wrong), 3)
    avg_hints_per_card = round(float(agg_row.avg_hints), 3)
    avg_time_on_card_sec = round(float(agg_row.avg_time), 3)
    total_study_time_sec = round(float(agg_row.total_time), 1)

    # Hardest concept: concept_id with highest total wrong_attempts
    hardest_result = await db.execute(
        select(
            CardInteraction.concept_id,
            func.sum(CardInteraction.wrong_attempts).label("total_wrong"),
        )
        .where(CardInteraction.student_id == student_id)
        .group_by(CardInteraction.concept_id)
        .order_by(func.sum(CardInteraction.wrong_attempts).desc())
        .limit(1)
    )
    hardest_row = hardest_result.one_or_none()
    hardest_concept_id: str | None = hardest_row.concept_id if hardest_row else None
    hardest_concept_wrong_attempts: int = int(hardest_row.total_wrong) if hardest_row else 0

    # ── Query 4: SpacedReview ─────────────────────────────────────────────────
    reviews_result = await db.execute(
        select(SpacedReview).where(
            and_(
                SpacedReview.student_id == student_id,
                SpacedReview.completed_at.is_(None),
            )
        )
    )
    pending_reviews = reviews_result.scalars().all()

    reviews_due_now = sum(1 for r in pending_reviews if r.due_at <= now)
    window_end = now + timedelta(days=7)
    reviews_upcoming_7d = sum(
        1 for r in pending_reviews if now < r.due_at <= window_end
    )

    logger.info(
        "[analytics] student_id=%s mastered=%d attempted=%d cards=%d",
        student_id, total_concepts_mastered, total_concepts_attempted, total_cards,
    )

    return StudentAnalyticsResponse(
        student_id=str(student_id),
        display_name=student.display_name,
        xp=student.xp or 0,
        streak=student.streak or 0,
        total_concepts_mastered=total_concepts_mastered,
        total_concepts_attempted=total_concepts_attempted,
        mastery_rate=mastery_rate,
        mastery_timeline=mastery_timeline,
        avg_check_score=avg_check_score,
        total_socratic_sessions=total_socratic_sessions,
        avg_wrong_attempts_per_card=avg_wrong_attempts_per_card,
        avg_hints_per_card=avg_hints_per_card,
        avg_time_on_card_sec=avg_time_on_card_sec,
        total_study_time_sec=total_study_time_sec,
        reviews_due_now=reviews_due_now,
        reviews_upcoming_7d=reviews_upcoming_7d,
        hardest_concept_id=hardest_concept_id,
        hardest_concept_wrong_attempts=hardest_concept_wrong_attempts,
    )


@router.get("/concepts/{concept_id}/readiness", response_model=ConceptReadinessResponse)
@limiter.limit("60/minute")
async def get_concept_readiness(
    request: Request,
    concept_id: str,
    student_id: UUID,
    book_slug: str = "prealgebra",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check whether all prerequisites for a concept are mastered by the student."""
    await _validate_student_ownership(user, student_id, db)
    # Fetch all mastered concept IDs for this student
    mastery_result = await db.execute(
        select(StudentMastery.concept_id).where(StudentMastery.student_id == student_id)
    )
    mastered_ids = {row for row in mastery_result.scalars().all()}

    if not chunk_ksvc:
        return ConceptReadinessResponse(
            concept_id=concept_id,
            all_prerequisites_met=True,
            unmet_prerequisites=[],
        )

    direct_prereqs = chunk_ksvc.get_predecessors(book_slug, concept_id)

    unmet = []
    for prereq_id in direct_prereqs:
        if prereq_id not in mastered_ids:
            node = chunk_ksvc.get_concept_node(book_slug, prereq_id)
            title = node["title"] if node else prereq_id
            unmet.append({"concept_id": prereq_id, "concept_title": title})

    logger.info(
        "[readiness] concept_id=%s student_id=%s unmet=%d",
        concept_id, student_id, len(unmet),
    )

    return ConceptReadinessResponse(
        concept_id=concept_id,
        all_prerequisites_met=len(unmet) == 0,
        unmet_prerequisites=unmet,
    )


async def _get_translated_headings_from_db(
    db: AsyncSession,
    book_slug: str,
    concept_id: str,
    language: str,
) -> list[str]:
    """Return ordered chunk headings for a concept, resolved to the target language via DB."""
    from api.dependencies import resolve_translation
    rows = (await db.execute(
        select(ConceptChunk.heading, ConceptChunk.heading_translations)
        .where(ConceptChunk.book_slug == book_slug, ConceptChunk.concept_id == concept_id)
        .order_by(ConceptChunk.order_index)
    )).all()
    return [
        resolve_translation(row.heading, row.heading_translations or {}, language)
        for row in rows
    ]


@router.patch("/students/{student_id}/language", response_model=StudentLanguageResponse)
@limiter.limit("30/minute")
async def update_student_language(
    request: Request,
    student_id: UUID,
    req: UpdateLanguageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a student's preferred language.
    Also translates chunk headings for any active session and busts the card cache.
    """
    await _validate_student_ownership(user, student_id, db)
    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(404, "Student not found")
    student.preferred_language = req.language

    translated_headings: list[str] = []
    session_cache_cleared = False

    # Find the most recent active session for this student
    session_result = await db.execute(
        select(TeachingSession)
        .where(
            TeachingSession.student_id == student_id,
            TeachingSession.completed_at.is_(None),
        )
        .order_by(TeachingSession.started_at.desc())
        .limit(1)
    )
    active_session = session_result.scalar_one_or_none()

    if active_session:
        try:
            async with asyncio.timeout(3.0):
                book_slug = active_session.book_slug or "prealgebra"
                translated_headings = await _get_translated_headings_from_db(
                    db, book_slug, active_session.concept_id, req.language
                )
                logger.info(
                    "[lang-translate] db headings resolved: session_id=%s lang=%s count=%d",
                    active_session.id, req.language, len(translated_headings),
                )
                # Bust the card generation cache so cards regenerate in the new language.
                # mark_stale() clears only the new language's slice; other language slices
                # are preserved so switching back is instant.
                _lang_ca = CacheAccessor(active_session.presentation_text, language=req.language)
                _lang_ca.mark_stale(req.language)
                # Explicitly clear exam questions for the new language slice.
                # mark_stale already deleted the slice, so this is a safeguard
                # against schema drift where exam questions might survive elsewhere.
                _lang_ca.clear_exam_questions(None)
                active_session.presentation_text = _lang_ca.to_json()
                session_cache_cleared = True
                logger.info(
                    "[lang-translate] cache busted: session_id=%s student_id=%s new_lang=%s",
                    active_session.id, student_id, req.language,
                )
        except asyncio.TimeoutError:
            await db.rollback()
            raise HTTPException(503, "Language update temporarily unavailable")
        except Exception as exc:
            logger.warning("[lang-translate] session update failed: %s", exc)

    await db.commit()
    await db.refresh(student)

    return StudentLanguageResponse(
        id=student.id,
        display_name=student.display_name,
        interests=student.interests or [],
        preferred_style=student.preferred_style,
        preferred_language=student.preferred_language,
        created_at=student.created_at,
        translated_headings=translated_headings,
        session_cache_cleared=session_cache_cleared,
    )


@router.patch("/students/{student_id}/progress", summary="Update XP and streak")
@limiter.limit("30/minute")
async def update_student_progress(
    request: Request,
    student_id: UUID,
    body: ProgressUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Atomically increment a student's XP and set their streak."""
    await _validate_student_ownership(user, student_id, db)
    result = await db.execute(
        select(Student).where(Student.id == student_id)
    )
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Student not found")

    await db.execute(
        update(Student)
        .where(Student.id == student_id)
        .values(xp=Student.xp + body.xp_delta, streak=body.streak)
    )
    await db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════
# TEACHING SESSIONS
# ═══════════════════════════════════════════════════════════════════

@router.post("/sessions", response_model=SessionResponse)
@limiter.limit("30/minute")
async def start_session(
    request: Request,
    req: StartSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a new teaching session for a student + concept."""
    await _validate_student_ownership(user, req.student_id, db)
    try:
        _require_services()
        student = await db.get(Student, req.student_id)
        if not student:
            raise HTTPException(404, "Student not found")
        active_books = await chunk_ksvc.get_active_books(db)
        if req.book_slug not in active_books:
            raise HTTPException(400, f"Book '{req.book_slug}' not loaded. Available: {sorted(active_books)}")
        concept_detail = await chunk_ksvc.get_concept_detail(db, req.concept_id, req.book_slug, lang="en")
        if not concept_detail:
            raise HTTPException(
                status_code=400,
                detail=f"Concept '{req.concept_id}' not found in book '{req.book_slug}'"
            )
        session = await teaching_svc.start_session(
            db, req.student_id, req.concept_id, req.book_slug
        )
        return session
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[sessions] session creation failed: student_id=%s concept_id=%s", req.student_id, req.concept_id)
        raise HTTPException(status_code=500, detail="Session creation failed. Please try again.")


@router.post("/sessions/{session_id}/present", response_model=PresentationResponse)
@limiter.limit("10/minute")
async def get_presentation(
    request: Request,
    session_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate the metaphor-based explanation for the session's concept."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    await _validate_student_ownership(user, session.student_id, db)
    if session.phase != "PRESENTING":
        raise HTTPException(
            400, f"Session is in {session.phase} phase, not PRESENTING"
        )

    student = await db.get(Student, session.student_id)
    presentation = await teaching_svc.generate_presentation(db, session, student)

    concept = await chunk_ksvc.get_concept_detail(db, session.concept_id, session.book_slug or "prealgebra", lang=student.preferred_language or "en")

    # Filter images: only DIAGRAM-type with reasonable dimensions
    raw_images = concept.get("images", []) if concept else []
    useful_images = [
        img for img in raw_images
        if img.get("image_type", "").upper() == "DIAGRAM"
        and img.get("width", 0) >= 200
        and img.get("height", 0) >= 80
    ]

    # Parse AI-generated diagram captions from the presentation text
    captions = {}
    for match in re.finditer(r'\[CAPTION_(\d+):\s*(.+?)\]', presentation):
        captions[int(match.group(1))] = match.group(2).strip()

    # Strip caption markers from the displayed lesson
    clean_presentation = re.sub(r'\[CAPTION_\d+:[^\]]*\]', '', presentation).rstrip()

    # Attach captions to images
    for i, img in enumerate(useful_images):
        img["caption"] = captions.get(i + 1, "")

    return PresentationResponse(
        session_id=session.id,
        concept_id=session.concept_id,
        concept_title=concept["concept_title"] if concept else session.concept_id,
        book_title=_get_book_title(session.book_slug),
        presentation=clean_presentation,
        style=session.style,
        phase=session.phase,
        images=useful_images,
        latex_expressions=[],
    )


@router.get("/sessions/resume", response_model=SessionResponse)
@limiter.limit("30/minute")
async def resume_session(
    request: Request,
    student_id: UUID,
    concept_id: str,
    book_slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Find the most recent non-DONE session for student+concept. Returns 404 if none."""
    await _validate_student_ownership(user, student_id, db)
    result = await db.execute(
        select(TeachingSession)
        .where(
            TeachingSession.student_id == student_id,
            TeachingSession.concept_id == concept_id,
            TeachingSession.book_slug == book_slug,
            TeachingSession.phase != "DONE",
        )
        .order_by(TeachingSession.started_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="No active session found")
    return SessionResponse.model_validate(session)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
@limiter.limit("30/minute")
async def get_session(
    request: Request,
    session_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get session status."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    await _validate_student_ownership(user, session.student_id, db)
    return session


@router.get("/sessions/{session_id}/history", response_model=SessionHistoryResponse)
@limiter.limit("30/minute")
async def get_session_history(
    request: Request,
    session_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full session history with all messages."""
    session = await db.get(
        TeachingSession, session_id,
        options=[selectinload(TeachingSession.messages)],
    )
    if not session:
        raise HTTPException(404, "Session not found")
    await _validate_student_ownership(user, session.student_id, db)

    return SessionHistoryResponse(
        session=SessionResponse.model_validate(session),
        messages=[MessageResponse.model_validate(m) for m in session.messages],
    )


# ═══════════════════════════════════════════════════════════════════
# CARD-BASED LEARNING
# ═══════════════════════════════════════════════════════════════════

@router.post("/sessions/{session_id}/cards", response_model=CardsResponse)
@limiter.limit("10/minute")
async def get_cards(
    request: Request,
    session_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate card-based lesson with sub-content cards and quiz questions."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    await _validate_student_ownership(user, session.student_id, db)
    if session.phase != "PRESENTING":
        raise HTTPException(
            400, f"Session is in {session.phase} phase, not PRESENTING"
        )

    student = await db.get(Student, session.student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    result = await teaching_svc.generate_cards(db, session, student)

    # Build validated response — Pydantic coerces card dicts to LessonCard
    cards = [LessonCard(**card_data) for card_data in result.get("cards", [])]

    return CardsResponse(
        session_id=session.id,
        concept_id=session.concept_id,
        concept_title=result.get("concept_title", session.concept_id),
        book_title=_get_book_title(session.book_slug),
        style=session.style,
        phase=session.phase,
        cards=cards,
        total_questions=result.get("total_questions", 0),
        has_more_concepts=bool(result.get("concepts_queue", [])),
        concepts_total=result.get("concepts_total", 0),
        concepts_covered_count=len(result.get("concepts_covered", [])),
        cache_version=result.get("cache_version", 0),
    )


@router.post("/sessions/{session_id}/assist", response_model=AssistResponse)
@limiter.limit("10/minute")
async def assist_student(
    request: Request,
    session_id: UUID,
    req: AssistRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AI assistant responds to student during card-based learning."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    await _validate_student_ownership(user, session.student_id, db)
    if session.phase == "COMPLETED":
        raise HTTPException(400, "Session is already completed")

    response_text = await teaching_svc.handle_assist(
        db, session, req.card_index, req.message, req.trigger
    )

    return AssistResponse(
        session_id=session.id,
        response=response_text,
        card_index=req.card_index,
    )


@router.post("/sessions/{session_id}/complete-cards")
@limiter.limit("30/minute")
async def complete_cards(
    request: Request,
    session_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Transition from CARDS to CARDS_DONE phase (gateway only, no mastery)."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    await _validate_student_ownership(user, session.student_id, db)
    if session.phase == "COMPLETED":
        raise HTTPException(400, "Session is already completed")

    result = await teaching_svc.complete_cards(db, session)
    return result


# ═══════════════════════════════════════════════════════════════════
# CHUNK-BASED CARD GENERATION (Phase 3)
# ═══════════════════════════════════════════════════════════════════

@router.post(
    "/sessions/{session_id}/chunk-cards",
    response_model=ChunkCardsResponse,
    summary="Generate all cards for a single ConceptChunk",
)
@limiter.limit("20/minute")
async def generate_chunk_cards(
    request: Request,
    session_id: UUID,
    req: ChunkCardsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate all cards for a single chunk. Called when student enters a new chunk.

    Returns interleaved content+MCQ cards for the given chunk_id, along with
    position metadata (chunk_index, total_chunks, is_last_chunk).
    """
    _require_services()
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    await _validate_student_ownership(user, session.student_id, db)

    try:
        cards_dicts = await teaching_svc.generate_per_chunk(session, db, req.chunk_id)
        cards = []
        for _c in cards_dicts:
            try:
                cards.append(LessonCard(**_c))
            except Exception as _val_err:
                logger.warning("[chunk-cards] skipping invalid card dict: %s", _val_err)
        _cc_student = await db.get(Student, session.student_id)
        _cc_lang = (_cc_student.preferred_language or "en") if _cc_student else "en"
        _chunks = await chunk_ksvc.get_chunks_for_concept(db, session.book_slug or "prealgebra", session.concept_id, lang=_cc_lang)
        chunk_index = next((i for i, c in enumerate(_chunks) if c["id"] == req.chunk_id), 0)

        # Fetch the chunk object to determine type and get text for question generation
        chunk = await chunk_ksvc.get_chunk(db, req.chunk_id)

        # Generate 2-3 exam questions for teaching chunks
        chunk_heading = chunk.get("heading", "") if chunk else ""
        chunk_text = chunk.get("text", "") if chunk else ""
        chunk_type = chunk.get("chunk_type") or _get_chunk_type(chunk_heading, chunk_text)
        # exam_disabled may be a bool on an ORM object or a dict value
        _exam_disabled = (
            chunk.get("exam_disabled", False)
            if isinstance(chunk, dict)
            else getattr(chunk, "exam_disabled", False)
        ) if chunk else False
        questions: list[ChunkExamQuestion] = []
        if _exam_disabled:
            # Admin has disabled exam questions for this chunk — auto-advance in frontend
            logger.info(
                "[chunk-cards] exam_disabled=True for chunk_id=%s — skipping question generation",
                req.chunk_id,
            )
        elif chunk_type == "teaching" and chunk and chunk_text.strip():
            # ── Exam question cache read ──────────────────────────────────────
            _exam_student = await db.get(Student, session.student_id)
            _exam_lang = getattr(_exam_student, "preferred_language", "en") or "en"
            _ca = CacheAccessor(session.presentation_text, language=_exam_lang)
            _cached_q = _ca.get_exam_questions(str(req.chunk_id))
            if _cached_q is not None:
                # Cache hit — reconstruct question objects from stored dicts
                logger.info(
                    "[exam-cache] hit chunk_id=%s lang=%s count=%d",
                    req.chunk_id, _exam_lang, len(_cached_q),
                )
                for _q_dict in _cached_q:
                    questions.append(ChunkExamQuestion(
                        index=_q_dict.get("index", 0),
                        text=_q_dict.get("text", ""),
                        chunk_id=str(req.chunk_id),
                    ))
            else:
                # Cache miss — generate via LLM then store result
                logger.info(
                    "[exam-cache] miss chunk_id=%s lang=%s — generating",
                    req.chunk_id, _exam_lang,
                )
                # Dynamic question count based on chunk text length
                _text_len = len(chunk_text.strip()) if chunk_text else 0
                _target_q = 1 if _text_len < 400 else (2 if _text_len < 1200 else 3)
                _q_system = (
                    "You are a friendly quiz writer for math students. "
                    "Based ONLY on the content provided, generate exactly "
                    f"{_target_q} short, direct question{'s' if _target_q > 1 else ''}.\n"
                    "RULES:\n"
                    "- Ask DIRECT questions with ONE clear correct answer.\n"
                    "- GOOD forms: 'Does X include zero — yes or no?', "
                    "'True or false: [simple statement].', "
                    "'What is the name for numbers that start at 1, 2, 3?'\n"
                    "- NEVER use 'explain', 'discuss', 'describe', 'how does X help', "
                    "'what is the significance of' — too abstract.\n"
                    "- Simple vocabulary (age 10–14). One sentence per question.\n"
                    "Return ONLY valid JSON with no markdown: "
                    '{"questions": [{"index": 0, "text": "..."}, ...]}'
                ) + _language_instruction(_exam_lang)
                _q_user = f"Section: {chunk_heading}\n\n{chunk_text[:900]}"
                try:
                    _q_result = await _call_llm_json(
                        teaching_svc.openai,
                        _q_system,
                        _q_user,
                        max_tokens=400,
                    )
                    for _qi, _q in enumerate((_q_result.get("questions") or [])[:_target_q]):
                        _qtext = (_q.get("text") or "").strip()
                        if _qtext:
                            questions.append(ChunkExamQuestion(
                                index=_qi,
                                text=_qtext,
                                chunk_id=str(req.chunk_id),
                            ))
                except Exception:
                    logger.exception("[chunk-cards] question generation failed on first try — retrying")
                    try:
                        _q_result2 = await _call_llm_json(
                            teaching_svc.openai,
                            _q_system,
                            _q_user,
                            max_tokens=400,
                        )
                        for _qi, _q in enumerate((_q_result2.get("questions") or [])[:_target_q]):
                            _qtext = (_q.get("text") or "").strip()
                            if _qtext:
                                questions.append(ChunkExamQuestion(
                                    index=_qi,
                                    text=_qtext,
                                    chunk_id=str(req.chunk_id),
                                ))
                    except Exception:
                        logger.exception("[chunk-cards] question generation failed after retry — skipping exam")
                        questions = []

                # ── Exam question cache write (only on successful generation) ─
                if questions:
                    _ca.set_exam_questions(
                        str(req.chunk_id),
                        [{"index": q.index, "text": q.text} for q in questions],
                    )
                    session.presentation_text = _ca.to_json()

        await db.commit()
        return ChunkCardsResponse(
            cards=cards,
            chunk_id=req.chunk_id,
            chunk_index=chunk_index,
            total_chunks=len(_chunks),
            is_last_chunk=chunk_index == len(_chunks) - 1,
            questions=questions,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "[chunk-cards] unhandled error: session_id=%s chunk_id=%s",
            session_id, req.chunk_id,
        )
        raise HTTPException(500, f"Chunk card generation failed: {exc}")


@router.post(
    "/sessions/{session_id}/chunk-recovery-card",
    summary="Generate a recovery card when student fails an MCQ twice",
)
@limiter.limit("20/minute")
async def generate_chunk_recovery_card(
    request: Request,
    session_id: UUID,
    req: RecoveryCardRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a recovery TEACH card re-explaining the chunk in STRUGGLING mode.

    Called when student fails the same MCQ twice in a row.
    Returns a single LessonCard with is_recovery=True.
    """
    _require_services()
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    await _validate_student_ownership(user, session.student_id, db)

    chunk = await chunk_ksvc.get_chunk(db, req.chunk_id)
    if not chunk:
        raise HTTPException(404, f"Chunk not found: {req.chunk_id}")

    images = await chunk_ksvc.get_chunk_images(db, req.chunk_id)

    _rec_student = await db.get(Student, session.student_id)
    _rec_lang = getattr(_rec_student, "preferred_language", "en") or "en"
    recovery = await teaching_svc.generate_recovery_card_for_chunk(
        session=session,
        chunk=chunk,
        chunk_images=images,
        card_index=req.card_index,
        wrong_answers=req.wrong_answers,
        is_exercise=req.is_exercise,
        language=_rec_lang,
    )

    if not recovery:
        raise HTTPException(500, "Recovery card generation failed")

    from gamification.xp_engine import award_recovery_xp
    xp_result = await award_recovery_xp(db, session.student_id, session.id)

    await db.commit()
    card_data = LessonCard(**recovery).model_dump()
    card_data["xp_awarded"] = {"base_xp": xp_result["base_xp"], "final_xp": xp_result["final_xp"]}
    return card_data


@router.post(
    "/sessions/{session_id}/complete-chunk",
    response_model=CompleteChunkResponse,
    summary="Record completion of a study chunk and determine mode for the next chunk",
)
@limiter.limit("60/minute")
async def complete_chunk(
    request: Request,
    session_id: UUID,
    req: CompleteChunkRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record completion of a study chunk and determine mode for the next chunk."""
    from datetime import datetime

    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await _validate_student_ownership(user, session.student_id, db)

    score = round((req.correct / req.total) * 100) if req.total > 0 else 0

    # Record progress — full dict reassignment required for JSONB change detection
    existing_progress = dict(session.chunk_progress or {})
    existing_progress[req.chunk_id] = {
        "mode": req.mode_used,
        "score": score,
        "correct": req.correct,
        "total": req.total,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    session.chunk_progress = existing_progress

    # Determine mode for next chunk using adaptive blending
    try:
        history = await load_student_history(str(session.student_id), session.concept_id, db)
        history["section_count"] = history.get("section_count", 0) + 1

        signals = CardBehaviorSignals(
            card_index=max(req.total - 1, 0),
            wrong_attempts=req.total - req.correct,
            hints_used=0,
            time_on_card_sec=history.get("avg_time_per_card") or 0.0,
            idle_triggers=0,
        )

        _, _, next_mode = build_blended_analytics(
            signals, history, session.concept_id, str(session.student_id)
        )

        # Persist section_count increment to Student profile
        await db.execute(
            sa_update(Student)
            .where(Student.id == session.student_id)
            .values(section_count=Student.section_count + 1)
        )
    except Exception:
        logger.exception("[complete_chunk] adaptive blending failed, falling back to threshold")
        from api.teaching_service import _mode_from_chunk_score
        next_mode = _mode_from_chunk_score(score)

    # Resolve student language up-front so it's available even when
    # presentation_text is NULL (e.g. after a cache bust).
    _cm_student = await db.get(Student, session.student_id)
    _cm_lang = (
        (getattr(_cm_student, "preferred_language", "en") or "en")
        if _cm_student else "en"
    )

    # Update presentation_text cache with next mode
    if session.presentation_text:
        try:
            _cm_ca = CacheAccessor(session.presentation_text, language=_cm_lang)
            _cm_slice = _cm_ca.get_slice()
            _cm_slice["current_mode"] = next_mode
            _cm_ca.set_slice(_cm_slice)
            session.presentation_text = _cm_ca.to_json()
        except Exception:
            pass

    # Get all chunks for this concept
    all_chunks = await chunk_ksvc.get_chunks_for_concept(
        db, session.book_slug, session.concept_id, lang=_cm_lang
    )
    all_sorted = sorted(all_chunks, key=lambda c: c["order_index"])

    # Find current chunk position
    current_chunk = next(
        (c for c in all_sorted if str(c["id"]) == req.chunk_id), None
    )
    current_order = current_chunk["order_index"] if current_chunk else 0

    # Next teaching chunk after current
    next_teaching = next(
        (c for c in all_sorted
         if c["order_index"] > current_order
         and _effective_chunk_type(c) == "teaching"),
        None,
    )

    # all_study_complete: all visible, required teaching chunks completed
    # Hidden and optional chunks are excluded — they must not block mastery
    completed_ids = set(existing_progress.keys())
    required_ids = {
        str(c["id"]) for c in all_sorted
        if _effective_chunk_type(c) == "teaching"
        and not c.get("is_optional", False)
        and not c.get("is_hidden", False)
    }
    all_study_complete = required_ids.issubset(completed_ids)

    # Record mastery when all required chunks are complete (mirrors evaluate_chunk_answers logic)
    if all_study_complete:
        from datetime import datetime, timezone as _tz
        session.concept_mastered = True
        session.phase = "COMPLETED"
        session.completed_at = datetime.now(_tz.utc)
        _existing_result = await db.execute(
            select(StudentMastery).where(
                StudentMastery.student_id == session.student_id,
                StudentMastery.concept_id == session.concept_id,
            )
        )
        _existing_mastery = _existing_result.scalar_one_or_none()
        if _existing_mastery:
            _existing_mastery.session_id = session.id
            _existing_mastery.mastered_at = datetime.now(_tz.utc)
        else:
            db.add(StudentMastery(
                student_id=session.student_id,
                concept_id=session.concept_id,
                session_id=session.id,
            ))
        logger.info(
            "[complete-chunk] concept MASTERED: session_id=%s concept_id=%s score=%s",
            session_id, session.concept_id, score,
        )
        await db.flush()
        try:
            from gamification.xp_engine import award_mastery_xp
            await award_mastery_xp(db=db, student_id=session.student_id, session_id=session.id, score=score)
        except Exception:
            logger.exception("[complete-chunk] mastery XP award failed")

    await db.commit()
    return CompleteChunkResponse(
        chunk_id=req.chunk_id,
        score=score,
        next_mode=next_mode,
        next_chunk_id=str(next_teaching["id"]) if next_teaching else None,
        all_study_complete=all_study_complete,
    )


@router.post(
    "/sessions/{session_id}/chunks/{chunk_id}/complete",
    response_model=CompleteChunkItemResponse,
    summary="Mark a chunk complete without requiring a score (exercise/teaching completion bookmark)",
)
@limiter.limit("60/minute")
async def complete_chunk_item(
    request: Request,
    session_id: UUID,
    chunk_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bookmark a chunk as completed without recording a score.

    Used when the student taps the Complete button on the last card of a chunk.
    Idempotent — calling twice returns 200 with current state.
    """
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    await _validate_student_ownership(user, session.student_id, db)

    # Verify chunk belongs to this session's concept
    all_chunks = await chunk_ksvc.get_chunks_for_concept(
        db, session.book_slug or "prealgebra", session.concept_id, lang="en"
    )
    all_sorted = sorted(all_chunks, key=lambda c: c.get("order_index", 0))
    chunk_ids_in_concept = {str(c["id"]) for c in all_sorted}

    if chunk_id not in chunk_ids_in_concept:
        raise HTTPException(404, "Chunk not found in this session's concept")

    # Record completion — idempotent
    existing_progress = dict(session.chunk_progress or {})
    if chunk_id not in existing_progress:
        existing_progress[chunk_id] = {
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        session.chunk_progress = existing_progress

    # Determine next study chunk
    current_chunk = next((c for c in all_sorted if str(c["id"]) == chunk_id), None)
    current_order = current_chunk.get("order_index", 0) if current_chunk else 0
    next_chunk = next(
        (c for c in all_sorted
         if c.get("order_index", 0) > current_order
         and _effective_chunk_type(c) in ("teaching", "exercise", "section_review")),
        None,
    )

    # Check all_study_complete — visible, required teaching chunks only
    # Hidden and optional chunks are excluded — they must not block mastery
    completed_ids = set(existing_progress.keys())
    required_ids = {
        str(c["id"]) for c in all_sorted
        if _effective_chunk_type(c) == "teaching"
        and not c.get("is_optional", False)
        and not c.get("is_hidden", False)
    }
    all_study_complete = required_ids.issubset(completed_ids)

    session.phase = "SELECTING_CHUNK"
    await db.commit()

    logger.info(
        "[complete_chunk_item] session_id=%s chunk_id=%s all_study_complete=%s",
        session_id, chunk_id, all_study_complete,
    )

    return CompleteChunkItemResponse(
        chunk_id=chunk_id,
        next_chunk_id=str(next_chunk["id"]) if next_chunk else None,
        all_study_complete=all_study_complete,
    )


@router.post(
    "/sessions/{session_id}/chunks/{chunk_id}/evaluate",
    response_model=ChunkEvaluateResponse,
    summary="Evaluate student answers for chunk exam gate and record completion if passed",
)
@limiter.limit("20/minute")
async def evaluate_chunk_answers(
    request: Request,
    session_id: UUID,
    chunk_id: str,
    req: ChunkEvaluateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Grade student open-ended answers for a chunk's exam gate using LLM.

    If passed (>=70%), records chunk completion in session.chunk_progress and
    computes all_study_complete. Returns per-question feedback.
    """
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await _validate_student_ownership(user, session.student_id, db)

    if not req.questions or not req.answers:
        raise HTTPException(status_code=400, detail="questions and answers are required")

    # Read student language for grading feedback
    _grade_student = await db.get(Student, session.student_id)
    _grade_lang = getattr(_grade_student, "preferred_language", "en") or "en"

    # Build grading prompt
    qa_pairs = []
    ans_by_index = {a.index: a.answer_text for a in req.answers}
    for q in req.questions:
        idx = q.get("index", 0) if isinstance(q, dict) else q.index
        text = q.get("text", "") if isinstance(q, dict) else q.text
        answer = ans_by_index.get(idx, "").strip()
        qa_pairs.append(f"Q{idx + 1}: {text}\nStudent answer: {answer or '(no answer)'}")

    grading_system = (
        "You are a supportive math tutor grading a quick recall check. "
        "Mark an answer CORRECT if it shows the student remembers the key idea — "
        "even if the wording is imprecise, incomplete, or informal. "
        "Only mark WRONG if the answer is completely blank, unrelated, or factually opposite. "
        "Give short, encouraging feedback (1 sentence). "
        "Return ONLY valid JSON: "
        '{"results": [{"index": 0, "correct": true/false, "feedback": "..."}]}'
    ) + _language_instruction(_grade_lang)
    grading_user = "\n\n".join(qa_pairs)

    try:
        grade_result = await _call_llm_json(
            teaching_svc.openai,
            grading_system,
            grading_user,
            max_tokens=600,
        )
        results = grade_result.get("results") or []
    except Exception as _ge:
        logger.exception("[evaluate-chunk] LLM grading failed for chunk %s", chunk_id)
        raise HTTPException(500, f"Grading failed: {_ge}")

    # Calculate score
    correct_count = sum(1 for r in results if r.get("correct"))
    total = len(req.questions)
    score_frac = correct_count / total if total > 0 else 0.0
    passed = score_frac >= CHUNK_EXAM_PASS_RATE

    # Build feedback list
    feedback: list[ChunkEvaluateFeedback] = [
        ChunkEvaluateFeedback(
            index=r.get("index", i),
            correct=bool(r.get("correct")),
            feedback=r.get("feedback", ""),
        )
        for i, r in enumerate(results)
    ]

    chunk_progress_update: dict = {}
    all_study_complete = False
    next_mode = "NORMAL"
    chunk_badges: list = []
    mastery_xp_data: dict | None = None

    if passed:
        # Evaluate chunk_complete badges (e.g. perfect_chunk)
        score_pct_for_badges = round(score_frac * 100)
        try:
            from gamification.badge_engine import evaluate_badges
            chunk_badges = await evaluate_badges(
                db, session.student_id, "chunk_complete",
                {"chunk_perfect": score_pct_for_badges >= 100},
            )
        except Exception:
            logger.exception("[evaluate-chunk] chunk_complete badge evaluation failed")

        # Part 1 — Mode computation using MCQ behavioral signals
        try:
            history = await load_student_history(str(session.student_id), session.concept_id, db)
            history["section_count"] = history.get("section_count", 0) + 1
            signals = CardBehaviorSignals(
                card_index=max(req.mcq_total - 1, 0),
                wrong_attempts=max(req.mcq_total - req.mcq_correct, 0),
                hints_used=0,
                time_on_card_sec=history.get("avg_time_per_card") or 0.0,
                idle_triggers=0,
            )
            _, _, next_mode = build_blended_analytics(
                signals, history, session.concept_id, str(session.student_id)
            )
            await db.execute(
                sa_update(Student)
                .where(Student.id == session.student_id)
                .values(section_count=Student.section_count + 1)
            )
        except Exception:
            logger.exception("[evaluate-chunk] adaptive blending failed, using MCQ score fallback")
            from api.teaching_service import _mode_from_chunk_score
            mcq_pct = round((req.mcq_correct / req.mcq_total) * 100) if req.mcq_total > 0 else 50
            next_mode = _mode_from_chunk_score(mcq_pct)

        # Record chunk progress
        existing_progress = dict(session.chunk_progress or {})
        score_pct = round(score_frac * 100)
        existing_progress[chunk_id] = {
            "mode": req.mode_used,
            "score": score_pct,
            "correct": correct_count,
            "total": total,
        }
        session.chunk_progress = existing_progress
        chunk_progress_update = {chunk_id: {"score": score_pct, "mode_used": req.mode_used}}

        # Compute all_study_complete — visible, required teaching chunks only
        # Hidden and optional chunks are excluded — they must not block mastery
        try:
            all_chunks = await chunk_ksvc.get_chunks_for_concept(
                db, session.book_slug or "prealgebra", session.concept_id, lang="en"
            )
            all_sorted = sorted(all_chunks, key=lambda c: c["order_index"])
            required_ids = {
                str(c["id"]) for c in all_sorted
                if _effective_chunk_type(c) == "teaching"
                and not c.get("is_optional", False)
                and not c.get("is_hidden", False)
            }
            completed_ids = set(existing_progress.keys())
            all_study_complete = required_ids.issubset(completed_ids)
        except Exception:
            logger.exception("[evaluate-chunk] all_study_complete check failed")

        # Part 2 — StudentMastery insertion when all study complete
        if all_study_complete:
            from datetime import datetime, timezone as _tz
            session.concept_mastered = True
            session.phase = "COMPLETED"
            session.completed_at = datetime.now(_tz.utc)
            _existing_result = await db.execute(
                select(StudentMastery).where(
                    StudentMastery.student_id == session.student_id,
                    StudentMastery.concept_id == session.concept_id,
                )
            )
            _existing_mastery = _existing_result.scalar_one_or_none()
            if _existing_mastery:
                _existing_mastery.session_id = session.id
                _existing_mastery.mastered_at = datetime.now(_tz.utc)
            else:
                db.add(StudentMastery(
                    student_id=session.student_id,
                    concept_id=session.concept_id,
                    session_id=session.id,
                ))
            logger.info(
                "[evaluate-chunk] concept MASTERED via KC: session_id=%s concept_id=%s",
                session_id, session.concept_id,
            )

            # Award mastery XP (flush so the mastery row is visible to badge queries)
            await db.flush()
            from gamification.xp_engine import award_mastery_xp
            mastery_xp_result = await award_mastery_xp(
                db=db,
                student_id=session.student_id,
                session_id=session.id,
                score=int(round(score_frac * 100)) if score_frac is not None else None,
            )
            mastery_xp_data = mastery_xp_result
            chunk_badges = chunk_badges + mastery_xp_result.get("new_badges", [])

    await db.commit()

    return ChunkEvaluateResponse(
        passed=passed,
        score=score_frac,
        all_study_complete=all_study_complete,
        chunk_progress=chunk_progress_update,
        feedback=feedback,
        next_mode=next_mode,
        new_badges=chunk_badges,
        xp_awarded=(
            {"base_xp": mastery_xp_data["base_xp"], "final_xp": mastery_xp_data["final_xp"]}
            if mastery_xp_data else None
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# CHUNK LIST (B1)
# ═══════════════════════════════════════════════════════════════════

# Heading patterns that never produce an MCQ card (Appendix C of DLD).
_NO_MCQ_HEADING_PATTERNS = (
    "learning objectives",
    "key terms",
    "key concepts",
    "summary",
    "chapter review",
    "review exercises",
    "practice test",
)


def _heading_has_mcq(heading: str) -> bool:
    """Return False for non-teaching headings that the DLD marks as MCQ-free."""
    lower = heading.lower()
    return not any(pattern in lower for pattern in _NO_MCQ_HEADING_PATTERNS)


_OPTIONAL_HEADING_PATTERNS = ("writing exercises", "writing exercise")

def _heading_is_optional(heading: str) -> bool:
    h = heading.lower()
    return any(p in h for p in _OPTIONAL_HEADING_PATTERNS)


def _chunk_has_meaningful_content(text: str, chunk_type: str) -> bool:
    """Return False for chunks that are bare headings or numbered-problem-list stubs.

    Teaching chunks are always shown (may be short but contain real explanation).
    All other types must contain at least 2 prose sentences (≥5 words, not a
    numbered/lettered exercise item like '1. Find the value...').
    """
    stripped = (text or "").strip()
    if len(stripped) < 60:
        return False
    if chunk_type == "teaching":
        return True
    sentences = re.split(r"[.!?]", stripped)
    prose_sentences = [
        s for s in sentences
        if len(s.split()) >= 5 and not re.match(r"^\s*\d+[\.\)]\s", s)
    ]
    return len(prose_sentences) >= 2


@router.get(
    "/sessions/{session_id}/chunks",
    response_model=ChunkListResponse,
    summary="List ordered chunks for the session's concept",
)
@limiter.limit("60/minute")
async def list_chunks(
    request: Request,
    session_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return ordered ConceptChunk summaries for the concept in this session.

    An empty chunks list signals a ChromaDB-path session — the frontend must
    fall back to the legacy POST /sessions/{id}/cards flow.
    """
    try:
        _require_services()
        session = await db.get(TeachingSession, session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        await _validate_student_ownership(user, session.student_id, db)

        book_slug = session.book_slug or "prealgebra"
        concept_id = session.concept_id

        # Fetch all chunks in textbook order
        result = await db.execute(
            select(ConceptChunk)
            .where(ConceptChunk.book_slug == book_slug, ConceptChunk.concept_id == concept_id)
            .order_by(ConceptChunk.order_index)
        )
        # Exclude heading-only stubs (< 100 chars) — same rule as get_chunks_for_concept()
        # in chunk_knowledge_service.py. Applies to all books and all sections.
        chunks = [c for c in result.scalars().all() if len((c.text or "").strip()) >= 100 and not c.is_hidden]

        if not chunks:
            # ChromaDB-path signal: return empty list
            logger.info(
                "[chunks] no chunks found — ChromaDB path: session_id=%s concept_id=%s",
                session_id, concept_id,
            )
            return ChunkListResponse(
                concept_id=concept_id,
                section_title="",
                chunks=[],
                current_chunk_index=session.chunk_index or 0,
            )

        # Check image existence per chunk in a single batch query
        chunk_ids = [c.id for c in chunks]
        img_result = await db.execute(
            select(ChunkImage.chunk_id)
            .where(ChunkImage.chunk_id.in_(chunk_ids))
            .distinct()
        )
        chunks_with_images: set = {row[0] for row in img_result.fetchall()}

        # chunk_progress is JSONB — guard against non-dict values (e.g. from DB corruption)
        raw_progress = session.chunk_progress
        progress: dict = raw_progress if isinstance(raw_progress, dict) else {}

        summaries = [
            ChunkSummary(
                chunk_id=str(c.id),
                order_index=c.order_index,
                heading=c.heading or "",
                has_images=c.id in chunks_with_images,
                has_mcq=_heading_has_mcq(c.heading or ""),
                chunk_type=c.chunk_type or _get_chunk_type(c.heading or ""),
                is_optional=c.is_optional,
                exam_disabled=bool(c.exam_disabled),
                completed=str(c.id) in progress,
                score=progress.get(str(c.id), {}).get("score"),
                mode_used=progress.get(str(c.id), {}).get("mode"),
            )
            for c in chunks
        ]

        # Prefer admin-supplied section name over the raw DB section field
        section_title = chunks[0].admin_section_name or chunks[0].section if chunks else ""

        # Resolve headings + section_title from DB translations
        student = await db.get(Student, session.student_id)
        lang = getattr(student, "preferred_language", "en") or "en"
        if lang != "en":
            from api.dependencies import resolve_translation
            for i, (s, c) in enumerate(zip(summaries, chunks)):
                s.heading = resolve_translation(c.heading or "", c.heading_translations or {}, lang)
            if section_title and chunks:
                # Use admin-set translations if available; fall back to heading_translations.
                trans = (
                    chunks[0].admin_section_name_translations or {}
                    if chunks[0].admin_section_name
                    else chunks[0].heading_translations or {}
                )
                section_title = resolve_translation(
                    chunks[0].admin_section_name or chunks[0].section or "",
                    trans,
                    lang,
                )

        logger.info(
            "[chunks] session_id=%s concept_id=%s total=%d current_index=%d lang=%s",
            session_id, concept_id, len(summaries), session.chunk_index or 0, lang,
        )

        return ChunkListResponse(
            concept_id=concept_id,
            section_title=section_title,
            chunks=summaries,
            current_chunk_index=session.chunk_index or 0,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[chunks] unhandled error: session_id=%s", session_id)
        raise HTTPException(500, f"Failed to load chunks: {exc}")


# ═══════════════════════════════════════════════════════════════════
# SOCRATIC EXAM (B2)
# ═══════════════════════════════════════════════════════════════════

async def _call_llm_json(
    client,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
) -> dict:
    """Call LLM with a JSON-output system prompt; parse and return the dict.

    Retries up to 3 times with exponential back-off. Raises ValueError on
    persistent failure or invalid JSON.
    """
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            resp = await client.chat.completions.create(
                model=OPENAI_MODEL_MINI,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.3,
                timeout=30.0,
            )
            raw = (resp.choices[0].message.content or "").strip()
            # Strip optional markdown code fences
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
            return json.loads(raw)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "[exam-llm] attempt=%d failed: %s", attempt, exc
            )
        if attempt < 3:
            await asyncio.sleep(2 * attempt)
    raise ValueError(f"LLM call failed after 3 attempts: {last_exc}")


@router.post("/sessions/{session_id}/record-interaction")
@limiter.limit("30/minute")
async def record_card_interaction(
    request: Request,
    session_id: UUID,
    req: RecordInteractionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save the final card interaction when the student clicks Finish Cards."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    await _validate_student_ownership(user, session.student_id, db)
    # Determine strategy effectiveness before saving the interaction row
    strategy_effective: bool | None = None
    if req.strategy_applied:
        # No boredom/disengagement signal after a strategy was applied → effective;
        # a boredom signal still present → ineffective.
        strategy_effective = req.engagement_signal is None

    interaction = CardInteraction(
        session_id=session.id,
        student_id=session.student_id,
        concept_id=session.concept_id,
        card_index=req.card_index,
        time_on_card_sec=req.time_on_card_sec,
        wrong_attempts=req.wrong_attempts,
        hints_used=req.hints_used,
        idle_triggers=req.idle_triggers,
        adaptation_applied=req.adaptation_applied,
        engagement_signal=req.engagement_signal,
        strategy_applied=req.strategy_applied,
        strategy_effective=strategy_effective,
        difficulty=req.difficulty,
    )
    db.add(interaction)
    # Flush first so the interaction gets its PK — the XP event FK needs it
    await db.flush()

    # Update student's engagement effectiveness history if a strategy was applied
    if req.strategy_applied and strategy_effective is not None:
        from api.teaching_service import _update_strategy_effectiveness
        await _update_strategy_effectiveness(
            db, session.student_id, req.strategy_applied, strategy_effective
        )

    # Award XP for correct answers (default difficulty=3 when LLM omits it)
    xp_result: dict = {"base_xp": 0, "multiplier": 1.0, "final_xp": 0, "new_badges": []}
    effective_difficulty = req.difficulty if req.difficulty is not None else 3
    if req.is_correct:
        from gamification.xp_engine import compute_and_award_xp
        xp_result = await compute_and_award_xp(
            db=db,
            student_id=session.student_id,
            session_id=session.id,
            interaction_id=interaction.id,
            difficulty=effective_difficulty,
            wrong_attempts=req.wrong_attempts,
            hints_used=req.hints_used,
            is_correct=True,
            time_on_card_sec=req.time_on_card_sec,
            answer_streak=0,  # Frontend will pass this in a future update
        )

    await db.commit()

    return {
        "saved": True,
        "xp_awarded": {
            "base_xp": xp_result["base_xp"],
            "multiplier": xp_result["multiplier"],
            "final_xp": xp_result["final_xp"],
            "streak_info": xp_result.get("streak_info"),
        },
        "new_badges": xp_result.get("new_badges", []),
    }


@router.post("/sessions/{session_id}/complete-card")
@limiter.limit("30/minute")
async def complete_card(
    request: Request,
    session_id: UUID,
    req: CompleteCardRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record card interaction; optionally generate recovery card; return updated learning profile."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await _validate_student_ownership(user, session.student_id, db)
    student = await db.get(Student, session.student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    result = await teaching_svc.complete_card_interaction(db, session, student, req)
    return CompleteCardResponse(**result)


# ═══════════════════════════════════════════════════════════════════
# SPACED REVIEW
# ═══════════════════════════════════════════════════════════════════

@router.get("/students/{student_id}/review-due")
@limiter.limit("30/minute")
async def get_review_due(
    request: Request,
    student_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return concepts due for spaced review for this student."""
    await _validate_student_ownership(user, student_id, db)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(SpacedReview)
        .where(
            and_(
                SpacedReview.student_id == student_id,
                SpacedReview.due_at <= now,
                SpacedReview.completed_at.is_(None),
            )
        )
        .order_by(SpacedReview.due_at)
    )
    reviews = result.scalars().all()

    return [
        {
            "concept_id": r.concept_id,
            "due_at": r.due_at.isoformat(),
            "review_number": r.review_number,
            "review_id": str(r.id),
        }
        for r in reviews
    ]


@router.post("/spaced-reviews/{review_id}/complete")
@limiter.limit("30/minute")
async def complete_spaced_review(
    request: Request,
    review_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a spaced review as completed."""
    review = await db.get(SpacedReview, review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    await _validate_student_ownership(user, review.student_id, db)
    if review.completed_at is not None:
        return {
            "ok": True,
            "already_completed": True,
            "completed_at": review.completed_at.isoformat(),
        }
    review.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return {
        "ok": True,
        "already_completed": False,
        "completed_at": review.completed_at.isoformat(),
    }


@router.get("/students/{student_id}/card-history")
@limiter.limit("120/minute")
async def get_student_card_history(
    request: Request,
    student_id: UUID,
    limit: int = CARD_HISTORY_DEFAULT_LIMIT,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent card interactions for a student. Used for adaptive engine verification."""
    await _validate_student_ownership(user, student_id, db)
    capped_limit = min(limit, CARD_HISTORY_MAX_LIMIT)

    result = await db.execute(
        select(CardInteraction)
        .where(CardInteraction.student_id == student_id)
        .order_by(CardInteraction.completed_at.desc())
        .limit(capped_limit)
    )
    interactions = result.scalars().all()

    return {
        "student_id": str(student_id),
        "total": len(interactions),
        "interactions": [
            {
                "id": str(ci.id),
                "session_id": str(ci.session_id),
                "concept_id": ci.concept_id,
                "card_index": ci.card_index,
                "time_on_card_sec": ci.time_on_card_sec,
                "wrong_attempts": ci.wrong_attempts,
                "hints_used": ci.hints_used,
                "idle_triggers": ci.idle_triggers,
                "adaptation_applied": ci.adaptation_applied,
                "completed_at": ci.completed_at.isoformat(),
            }
            for ci in interactions
        ],
    }


@router.get("/students/{student_id}/sessions")
@limiter.limit("120/minute")
async def get_student_sessions(
    request: Request,
    student_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all meaningful teaching sessions for a student (any phase past PRESENTING)."""
    from sqlalchemy import text as sa_text
    from api.dependencies import resolve_translation
    await _validate_student_ownership(user, student_id, db)
    student = await db.get(Student, student_id)
    lang = (student.preferred_language or "en") if student else "en"

    # Single query with LATERAL join to fetch chunk heading and book title translations.
    rows = (await db.execute(
        sa_text("""
            SELECT
                ts.id,
                ts.concept_id,
                ts.book_slug,
                ts.phase,
                ts.check_score,
                ts.concept_mastered,
                ts.started_at,
                ts.completed_at,
                cc.heading          AS chunk_heading,
                cc.heading_translations AS chunk_heading_tr,
                b.title             AS book_title_en,
                b.title_translations AS book_title_tr
            FROM teaching_sessions ts
            LEFT JOIN LATERAL (
                SELECT heading, heading_translations
                FROM concept_chunks
                WHERE book_slug = ts.book_slug
                  AND concept_id = ts.concept_id
                ORDER BY order_index ASC
                LIMIT 1
            ) cc ON true
            LEFT JOIN books b ON b.book_slug = ts.book_slug
            WHERE ts.student_id = :student_id
              AND ts.phase IN ('PRESENTING','CARDS','CARDS_DONE','SELECTING_CHUNK','CHECKING','COMPLETED')
            ORDER BY ts.started_at DESC
            LIMIT 50
        """),
        {"student_id": str(student_id)},
    )).mappings().all()

    return {
        "student_id": str(student_id),
        "sessions": [
            {
                "id": str(row["id"]),
                "concept_id": row["concept_id"],
                "book_slug": row["book_slug"],
                "phase": row["phase"],
                "check_score": row["check_score"],
                "mastered": row["concept_mastered"],
                "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                "concept_title": resolve_translation(
                    row["chunk_heading"] or row["concept_id"] or "",
                    row["chunk_heading_tr"] or {},
                    lang,
                ),
                "book_title": resolve_translation(
                    row["book_title_en"] or row["book_slug"] or "",
                    row["book_title_tr"] or {},
                    lang,
                ),
            }
            for row in rows
        ],
    }


@router.post("/sessions/{session_id}/regenerate-mcq", response_model=RegenerateMCQResponse)
@limiter.limit("30/minute")
async def regenerate_mcq_endpoint(
    request: Request,
    session_id: UUID,
    body: RegenerateMCQRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a replacement MCQ after a wrong answer — same concept, different scenario."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await _validate_student_ownership(user, session.student_id, db)
    new_mcq = await teaching_svc.regenerate_mcq(body)
    return RegenerateMCQResponse(question=new_mcq)


@router.get("/sessions/{session_id}/card-interactions")
@limiter.limit("120/minute")
async def get_session_card_interactions(
    request: Request,
    session_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all card interactions for a specific session, ordered by card index."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    await _validate_student_ownership(user, session.student_id, db)
    result = await db.execute(
        select(CardInteraction)
        .where(CardInteraction.session_id == session_id)
        .order_by(CardInteraction.card_index)
        .limit(CARD_HISTORY_MAX_LIMIT)
    )
    interactions = result.scalars().all()
    return {
        "session_id": str(session_id),
        "interactions": [
            {
                "card_index": ci.card_index,
                "time_on_card_sec": ci.time_on_card_sec,
                "wrong_attempts": ci.wrong_attempts,
                "hints_used": ci.hints_used,
                "idle_triggers": ci.idle_triggers,
                "adaptation_applied": ci.adaptation_applied,
                "completed_at": ci.completed_at.isoformat(),
            }
            for ci in interactions
        ],
    }


# ═══════════════════════════════════════════════════════════════════
# GAMIFICATION — BADGES, LEADERBOARD, FEATURE FLAGS
# ═══════════════════════════════════════════════════════════════════

@router.get("/students/{student_id}/badges")
@limiter.limit("30/minute")
async def get_student_badges(
    request: Request,
    student_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all badges earned by a student, ordered newest first.

    Runs a catch-up evaluation for all badge triggers so that any
    badges the student qualified for but were missed are awarded retroactively.
    """
    await _validate_student_ownership(user, student_id, db)

    # Retroactive catch-up: evaluate all triggers to award any missed badges
    try:
        from gamification.badge_engine import sync_student_badges
        await sync_student_badges(db, student_id)
        await db.commit()
    except Exception:
        logger.exception("[badges-catchup] failed for student %s", student_id)
        await db.rollback()

    from db.models import StudentBadge
    result = await db.execute(
        select(StudentBadge)
        .where(StudentBadge.student_id == student_id)
        .order_by(StudentBadge.awarded_at.desc())
    )
    badges = result.scalars().all()
    return [
        {
            "badge_key": b.badge_key,
            "awarded_at": b.awarded_at.isoformat(),
            "metadata": b.metadata_,
        }
        for b in badges
    ]


@router.get("/leaderboard")
@limiter.limit("10/minute")
async def get_leaderboard(
    request: Request,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get XP leaderboard.  Returns 403 if disabled by admin."""
    from db.models import StudentBadge, AdminConfig
    from sqlalchemy import func as sa_func

    # Check feature flag
    config_result = await db.execute(
        select(AdminConfig.value).where(AdminConfig.key == "LEADERBOARD_ENABLED")
    )
    enabled = config_result.scalar_one_or_none()
    if enabled != "true":
        raise HTTPException(403, "Leaderboard is disabled")

    limit = max(5, min(100, limit))

    # Ranked students by XP
    result = await db.execute(
        select(Student.id, Student.display_name, Student.xp)
        .where(Student.xp > 0)
        .order_by(Student.xp.desc())
        .limit(limit)
    )
    rows = result.all()

    # Badge counts in a single query
    badge_counts_result = await db.execute(
        select(StudentBadge.student_id, sa_func.count(StudentBadge.id))
        .group_by(StudentBadge.student_id)
    )
    badge_counts: dict = dict(badge_counts_result.all())

    leaderboard = []
    for rank, (sid, name, xp) in enumerate(rows, 1):
        level = (xp // 100) + 1
        leaderboard.append({
            "rank": rank,
            "display_name": name,
            "xp": xp,
            "level": level,
            "badge_count": badge_counts.get(sid, 0),
        })

    # Find the authenticated user's own rank
    student_result = await db.execute(
        select(Student).where(Student.user_id == user.id)
    )
    my_student = student_result.scalar_one_or_none()
    your_rank = None
    if my_student and my_student.xp > 0:
        count_result = await db.execute(
            select(func.count(Student.id)).where(Student.xp > my_student.xp)
        )
        your_rank = (count_result.scalar() or 0) + 1

    return {
        "leaderboard": leaderboard,
        "your_rank": your_rank,
        "your_xp": my_student.xp if my_student else 0,
    }


@router.get("/features")
@limiter.limit("60/minute")
async def get_feature_flags(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Return gamification feature flags as booleans for the frontend."""
    from db.models import AdminConfig
    flag_keys = [
        "GAMIFICATION_ENABLED",
        "LEADERBOARD_ENABLED",
        "BADGES_ENABLED",
        "STREAK_MULTIPLIER_ENABLED",
        "DIFFICULTY_WEIGHTED_XP_ENABLED",
    ]
    defaults = {
        "GAMIFICATION_ENABLED": "true",
        "LEADERBOARD_ENABLED": "false",
        "BADGES_ENABLED": "true",
        "STREAK_MULTIPLIER_ENABLED": "true",
        "DIFFICULTY_WEIGHTED_XP_ENABLED": "true",
    }
    result = await db.execute(
        select(AdminConfig.key, AdminConfig.value)
        .where(AdminConfig.key.in_(flag_keys))
    )
    config: dict = dict(result.all())
    return {
        k.lower(): (config.get(k, defaults[k]) == "true")
        for k in flag_keys
    }


@router.get("/books", response_model=list[dict])
async def list_available_books(db: AsyncSession = Depends(get_db)):
    """Return all processed books available for study (excluding hidden books/subjects)."""
    from db.models import Book, Subject

    try:
        from config import BOOK_REGISTRY
        slug_to_title = {
            entry["book_slug"]: entry["title"]
            for entry in BOOK_REGISTRY.values()
            if isinstance(entry, dict) and "book_slug" in entry and "title" in entry
        }
    except (ImportError, AttributeError):
        slug_to_title = {}

    # Only show books that are PUBLISHED in the books table, not hidden,
    # and whose subject is not hidden. Old books without a books table entry are excluded.
    try:
        query = select(Book.book_slug, Book.title, Book.subject).where(
            Book.status == "PUBLISHED",
            Book.is_hidden == False,
        )
        rows = (await db.execute(query)).all()
    except Exception as exc:
        logger.warning("[list_available_books] DB query failed: %s", exc)
        rows = []

    # Filter out books whose subject is hidden
    hidden_subjects: set[str] = set()
    try:
        hs_rows = (await db.execute(
            select(Subject.slug).where(Subject.is_hidden == True)
        )).scalars().all()
        hidden_subjects = set(hs_rows)
    except Exception:
        pass

    # Also check that books have concept_chunks (actually processed)
    active_books: set[str] = set()
    try:
        active_books = await chunk_ksvc.get_active_books(db)
    except Exception:
        pass

    return [
        {
            "slug": r[0],
            "title": r[1] or slug_to_title.get(r[0], r[0].replace("_", " ").title()),
            "subject": r[2],
        }
        for r in rows
        if r[2] not in hidden_subjects and r[0] in active_books
    ]


# ═══════════════════════════════════════════════════════════════════
# CHUNKS PREVIEW (no session required)
# ═══════════════════════════════════════════════════════════════════

@router.get(
    "/concepts/{book_slug}/{concept_id}/chunks-preview",
    response_model=ChunkPreviewResponse,
    summary="Preview chunk list for a concept without creating a session",
)
@limiter.limit("60/minute")
async def get_chunks_preview(
    request: Request,
    book_slug: str,
    concept_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Return a lightweight list of chunk summaries for a concept.

    Does NOT create or require a teaching session — intended for the concept
    map and lesson selection UI to display what content a concept contains
    before the student commits to starting a session.

    Excludes hidden chunks and chunks shorter than 100 characters (typically
    placeholder or stub entries).
    """
    # Fetch all visible, substantive chunks for this concept ordered by position
    result = await db.execute(
        select(ConceptChunk)
        .where(
            ConceptChunk.book_slug == book_slug,
            ConceptChunk.concept_id == concept_id,
            ConceptChunk.is_hidden.is_(False),
            func.length(ConceptChunk.text) >= 100,
        )
        .order_by(ConceptChunk.order_index)
    )
    chunks = result.scalars().all()

    if not chunks:
        logger.info(
            "[chunks-preview] no visible chunks for book_slug=%s concept_id=%s",
            book_slug, concept_id,
        )
        return ChunkPreviewResponse(concept_id=concept_id, chunks=[])

    # Bulk-check which chunks have associated images (one query, not N)
    chunk_ids = [c.id for c in chunks]
    img_result = await db.execute(
        select(ChunkImage.chunk_id)
        .where(ChunkImage.chunk_id.in_(chunk_ids))
        .distinct()
    )
    chunks_with_images: set = {row[0] for row in img_result.fetchall()}

    items = [
        ChunkPreviewItem(
            heading=c.heading or "",
            chunk_type=c.chunk_type or _get_chunk_type(c.heading or "", c.text or ""),
            has_images=c.id in chunks_with_images,
            has_mcq=_heading_has_mcq(c.heading or ""),
            is_optional=bool(c.is_optional),
            exam_disabled=bool(c.exam_disabled),
            order_index=c.order_index,
        )
        for c in chunks
    ]

    logger.info(
        "[chunks-preview] book_slug=%s concept_id=%s chunks=%d",
        book_slug, concept_id, len(items),
    )
    return ChunkPreviewResponse(concept_id=concept_id, chunks=items)


# ── Student self-profile update ──────────────────────────────────────────


@router.patch("/students/{student_id}/profile", summary="Update student profile")
@limiter.limit("30/minute")
async def update_student_profile(
    request: Request,
    student_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update editable student profile fields (display_name, age, preferred_style, interests)."""
    await _validate_student_ownership(user, student_id, db)
    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(404, "Student not found")

    body = await request.json()
    allowed_styles = {"default", "pirate", "astronaut", "gamer"}

    if "display_name" in body:
        val = str(body["display_name"]).strip()
        if not val:
            raise HTTPException(400, "display_name cannot be empty")
        if len(val) > 100:
            raise HTTPException(400, "display_name must be 100 characters or fewer")
        student.display_name = val

    if "age" in body:
        if body["age"] is None:
            student.age = None
        else:
            age_val = int(body["age"])
            if age_val < 5 or age_val > 120:
                raise HTTPException(400, "age must be between 5 and 120")
            student.age = age_val

    if "preferred_style" in body:
        style = str(body["preferred_style"])
        if style not in allowed_styles:
            raise HTTPException(400, f"preferred_style must be one of: {sorted(allowed_styles)}")
        student.preferred_style = style

    if "interests" in body:
        interests = body["interests"]
        if not isinstance(interests, list):
            raise HTTPException(400, "interests must be a list")
        student.interests = [str(i).strip() for i in interests if str(i).strip()][:20]

    if "custom_interests" in body:
        from api.interest_validator import validate_custom_interest
        incoming = body["custom_interests"]
        if not isinstance(incoming, list):
            raise HTTPException(400, "custom_interests must be a list")

        existing_custom = list(student.custom_interests or [])
        cleaned: list[str] = []

        for raw_item in incoming:
            item = str(raw_item).strip()
            if not item:
                continue
            # Items already persisted in this student's custom_interests are trusted —
            # skip LLM re-validation (defence in depth without re-billing).
            if any(ec.lower() == item.lower() for ec in existing_custom):
                cleaned.append(item)
                continue
            # New item — run full validation (format + LLM).
            result = await validate_custom_interest(
                text=item,
                language=student.preferred_language or "en",
                existing_custom=cleaned,  # growing list prevents intra-request dupes
                predefined_ids=PREDEFINED_INTEREST_IDS,
            )
            if not result.ok:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "field": "custom_interests",
                        "item": item,
                        "reason": result.reason,
                    },
                )
            cleaned.append(result.normalized)

        # Dedupe case-insensitively, preserve first occurrence, cap at max.
        seen_lower: set[str] = set()
        deduped: list[str] = []
        for c in cleaned:
            if c.lower() not in seen_lower:
                seen_lower.add(c.lower())
                deduped.append(c)
        student.custom_interests = deduped[:CUSTOM_INTERESTS_MAX]

    await db.commit()
    await db.refresh(student)
    logger.info("[profile] Student %s updated own profile", student_id)
    return {
        "id": str(student.id),
        "display_name": student.display_name,
        "age": student.age,
        "preferred_style": student.preferred_style,
        "interests": student.interests or [],
        "custom_interests": student.custom_interests or [],
    }
