"""
Week 2 API endpoints: The Pedagogical Loop.
Teaching sessions, Socratic checks, style switching.
"""

import re
from datetime import datetime, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_, update
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import logging

import asyncio
import json

from config import (
    CARD_HISTORY_DEFAULT_LIMIT,
    CARD_HISTORY_MAX_LIMIT,
    XP_MASTERY,
    XP_MASTERY_BONUS,
    XP_MASTERY_BONUS_THRESHOLD,
    XP_CONSOLATION,
    DEFAULT_BOOK_SLUG,
    CHUNK_EXAM_PASS_RATE,
    CHUNK_EXAM_QUESTIONS_PER_CHUNK,
    CHUNK_MAX_TOKENS_EXAM_Q,
    CHUNK_MAX_TOKENS_EXAM_EVAL,
    OPENAI_MODEL_MINI,
)
from adaptive.adaptive_engine import build_blended_analytics, load_student_history
from adaptive.schemas import CardBehaviorSignals
from db.connection import get_db
from db.models import Student, TeachingSession, ConversationMessage, StudentMastery, SpacedReview, CardInteraction
from db.models import ConceptChunk, ChunkImage
from api.teaching_schemas import (
    CreateStudentRequest, StudentResponse,
    StartSessionRequest, SessionResponse,
    PresentationResponse,
    StudentResponseRequest, SocraticResponse,
    SwitchStyleRequest,
    SessionHistoryResponse, MessageResponse,
    CardsResponse, LessonCard,
    AssistRequest, AssistResponse,
    UpdateLanguageRequest,
    RemediationCardsResponse,
    RecheckResponse,
    StudentAnalyticsResponse,
    ConceptReadinessResponse,
    RegenerateMCQRequest, RegenerateMCQResponse,
    SectionCompleteRequest, SectionCompleteResponse,
    UpdateSessionInterestsRequest,
    NextSectionCardsRequest, NextSectionCardsResponse,
    CompleteCardRequest, CompleteCardResponse,
    NextCardRequest, NextCardResponse,
    ChunkCardsRequest, ChunkCardsResponse,
    RecoveryCardRequest,
    CompleteChunkRequest, CompleteChunkResponse,
    ChunkSummary, ChunkListResponse,
    ExamStartRequest, ExamStartResponse, ExamQuestion,
    ExamSubmitRequest, ExamSubmitResponse, PerChunkScore,
    ExamRetryRequest, ExamRetryResponse,
)
from api.rate_limiter import limiter

logger = logging.getLogger(__name__)


def _get_chunk_type(heading: str) -> str:
    """Classify a chunk heading for SubsectionNav display and exam logic."""
    h = heading.lower()
    # "SECTION X.X EXERCISES" must be checked BEFORE the "(exercises)" suffix check
    if re.match(r"^section\s+\d+\.\d+", h):
        return "exercise_gate"
    if "(exercises)" not in h:
        return "teaching"
    if "everyday math" in h or "writing exercises" in h:
        return "practice"
    if "practice makes perfect" in h:
        return "exercise_gate"
    return "exam_question_source"


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
async def create_student(request: Request, req: CreateStudentRequest, db: AsyncSession = Depends(get_db)):
    """Create a new student profile."""
    student = Student(
        display_name=req.display_name,
        interests=req.interests,
        preferred_style=req.preferred_style,
        preferred_language=req.preferred_language,
    )
    db.add(student)
    await db.flush()
    return student


@router.get("/students", summary="List all students")
@limiter.limit("120/minute")
async def list_students(
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    """List student profiles with their mastery counts (paginated)."""
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
async def get_student(request: Request, student_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get student profile including xp and streak."""
    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(404, "Student not found")
    return {
        "id": str(student.id),
        "display_name": student.display_name,
        "interests": student.interests or [],
        "preferred_style": student.preferred_style,
        "preferred_language": student.preferred_language or "en",
        "created_at": student.created_at.isoformat(),
        "xp": student.xp,
        "streak": student.streak,
    }


@router.get("/students/{student_id}/mastery")
@limiter.limit("30/minute")
async def get_student_mastery(request: Request, student_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get all concepts mastered by a student."""
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
    db: AsyncSession = Depends(get_db),
):
    """Aggregate learning analytics for a student across all four interaction tables."""
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
        ).where(CardInteraction.student_id == student_id)
    )
    agg_row = card_agg.one()
    total_cards = int(agg_row.total or 0)
    avg_wrong_attempts_per_card = round(float(agg_row.avg_wrong), 3)
    avg_hints_per_card = round(float(agg_row.avg_hints), 3)
    avg_time_on_card_sec = round(float(agg_row.avg_time), 3)

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
    db: AsyncSession = Depends(get_db),
):
    """Check whether all prerequisites for a concept are mastered by the student."""
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

    book_slug = DEFAULT_BOOK_SLUG
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


@router.patch("/students/{student_id}/language", response_model=StudentResponse)
@limiter.limit("30/minute")
async def update_student_language(
    request: Request, student_id: UUID, req: UpdateLanguageRequest, db: AsyncSession = Depends(get_db)
):
    """Update a student's preferred language."""
    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(404, "Student not found")
    student.preferred_language = req.language
    await db.flush()
    return student


@router.patch("/students/{student_id}/progress", summary="Update XP and streak")
@limiter.limit("30/minute")
async def update_student_progress(
    request: Request,
    student_id: UUID,
    body: ProgressUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Atomically increment a student's XP and set their streak."""
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
async def start_session(request: Request, req: StartSessionRequest, db: AsyncSession = Depends(get_db)):
    """Start a new teaching session for a student + concept."""
    try:
        _require_services()
        student = await db.get(Student, req.student_id)
        if not student:
            raise HTTPException(404, "Student not found")
        active_books = await chunk_ksvc.get_active_books(db)
        if req.book_slug not in active_books:
            raise HTTPException(400, f"Book '{req.book_slug}' not loaded. Available: {sorted(active_books)}")
        concept_detail = await chunk_ksvc.get_concept_detail(db, req.concept_id, req.book_slug)
        if not concept_detail:
            raise HTTPException(
                status_code=400,
                detail=f"Concept '{req.concept_id}' not found in book '{req.book_slug}'"
            )
        session = await teaching_svc.start_session(
            db, req.student_id, req.concept_id, req.book_slug, req.style, req.lesson_interests
        )
        return session
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[sessions] session creation failed: student_id=%s concept_id=%s", req.student_id, req.concept_id)
        raise HTTPException(status_code=500, detail=f"Session creation failed: {exc}")


@router.post("/sessions/{session_id}/present", response_model=PresentationResponse)
@limiter.limit("10/minute")
async def get_presentation(request: Request, session_id: UUID, db: AsyncSession = Depends(get_db)):
    """Generate the metaphor-based explanation for the session's concept."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.phase != "PRESENTING":
        raise HTTPException(
            400, f"Session is in {session.phase} phase, not PRESENTING"
        )

    student = await db.get(Student, session.student_id)
    presentation = await teaching_svc.generate_presentation(db, session, student)

    concept = await chunk_ksvc.get_concept_detail(db, session.concept_id, session.book_slug or DEFAULT_BOOK_SLUG)

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
        presentation=clean_presentation,
        style=session.style,
        phase=session.phase,
        images=useful_images,
        latex_expressions=[],
    )


@router.post("/sessions/{session_id}/check", response_model=SocraticResponse)
@limiter.limit("10/minute")
async def begin_check(request: Request, session_id: UUID, db: AsyncSession = Depends(get_db)):
    """Transition from Presentation to Socratic Check. Returns first question."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.phase not in ("PRESENTING", "CARDS_DONE"):
        raise HTTPException(
            400, f"Cannot begin check: session is in {session.phase} phase"
        )

    student = await db.get(Student, session.student_id)
    first_question, first_image = await teaching_svc.begin_socratic_check(db, session, student)

    return SocraticResponse(
        session_id=session.id,
        response=first_question,
        phase=session.phase,
        check_complete=False,
        exchange_count=1,
        image=first_image,
    )


@router.post("/sessions/{session_id}/respond", response_model=SocraticResponse)
@limiter.limit("10/minute")
async def respond_to_check(
    request: Request,
    session_id: UUID,
    req: StudentResponseRequest,
    db: AsyncSession = Depends(get_db),
):
    """Submit student response during Socratic check. Returns AI's next question or completion."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.phase not in ("CHECKING", "RECHECKING", "RECHECKING_2"):
        raise HTTPException(
            400, f"Cannot respond: session is in {session.phase} phase"
        )

    result = await teaching_svc.handle_student_response(db, session, req.message)

    # Count student exchanges across all check phases (CHECKING, RECHECKING, RECHECKING_2)
    exchange_result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.session_id == session_id)
        .where(ConversationMessage.phase.in_(["CHECKING", "RECHECKING", "RECHECKING_2"]))
        .where(ConversationMessage.role == "user")
    )
    exchange_count = len(exchange_result.scalars().all())

    # Award XP only when the session truly completes (phase == COMPLETED).
    # When remediation_needed=True the session moves to REMEDIATING, not COMPLETED,
    # so no XP is awarded yet — it will be awarded on the final successful (or exhausted) check.
    xp_awarded = None
    if result.get("check_complete") and result.get("phase") == "COMPLETED":
        mastered = result.get("mastered") or False
        score = result.get("score") or 0

        xp_delta = (
            XP_MASTERY + (XP_MASTERY_BONUS if score >= XP_MASTERY_BONUS_THRESHOLD else 0)
            if mastered
            else XP_CONSOLATION
        )

        # Fetch the student to get the current streak for the update
        student_for_xp = await db.get(Student, session.student_id)
        if student_for_xp is not None:
            current_streak = student_for_xp.streak or 0
            new_streak = (current_streak + 1) if mastered else current_streak
            await _award_xp(
                student_id=session.student_id,
                xp_delta=xp_delta,
                new_streak=new_streak,
                mastered=mastered,
                score=score,
                db=db,
            )
        xp_awarded = xp_delta

    return SocraticResponse(
        session_id=session.id,
        response=result["response"],
        phase=result["phase"],
        check_complete=result["check_complete"],
        score=result["score"],
        mastered=result["mastered"],
        exchange_count=exchange_count,
        xp_awarded=xp_awarded,
        remediation_needed=result.get("remediation_needed", False),
        attempt=result.get("attempt", 0),
        locked=result.get("locked", False),
        best_score=result.get("best_score"),
        image=result.get("image"),
    )


@router.put("/sessions/{session_id}/style")
@limiter.limit("30/minute")
async def switch_style(
    request: Request,
    session_id: UUID,
    req: SwitchStyleRequest,
    db: AsyncSession = Depends(get_db),
):
    """Switch teaching style mid-session."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.phase == "COMPLETED":
        raise HTTPException(400, "Cannot switch style on a completed session")

    student = await db.get(Student, session.student_id)
    result = await teaching_svc.switch_style(db, session, req.style, student)

    return {"session_id": str(session.id), "new_style": req.style, "result": result}


@router.put("/sessions/{session_id}/interests")
@limiter.limit("30/minute")
async def update_session_interests(
    request: Request,
    session_id: UUID,
    req: UpdateSessionInterestsRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update per-session interest override. Used by in-section customize panel."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    session.lesson_interests = [i[:50] for i in req.interests[:10]]
    await db.commit()
    logger.info("session=%s interests updated count=%d", session_id, len(session.lesson_interests))
    return {"session_id": str(session_id), "lesson_interests": session.lesson_interests}


@router.get("/sessions/resume", response_model=SessionResponse)
@limiter.limit("30/minute")
async def resume_session(
    request: Request,
    student_id: UUID,
    concept_id: str,
    book_slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Find the most recent non-DONE session for student+concept. Returns 404 if none."""
    result = await db.execute(
        select(TeachingSession)
        .where(
            TeachingSession.student_id == student_id,
            TeachingSession.concept_id == concept_id,
            TeachingSession.book_slug == book_slug,
            TeachingSession.phase != "DONE",
        )
        .order_by(TeachingSession.created_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="No active session found")
    return session


@router.get("/sessions/{session_id}", response_model=SessionResponse)
@limiter.limit("30/minute")
async def get_session(request: Request, session_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get session status."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@router.get("/sessions/{session_id}/history", response_model=SessionHistoryResponse)
@limiter.limit("30/minute")
async def get_session_history(request: Request, session_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get full session history with all messages."""
    session = await db.get(
        TeachingSession, session_id,
        options=[selectinload(TeachingSession.messages)],
    )
    if not session:
        raise HTTPException(404, "Session not found")

    return SessionHistoryResponse(
        session=SessionResponse.model_validate(session),
        messages=[MessageResponse.model_validate(m) for m in session.messages],
    )


# ═══════════════════════════════════════════════════════════════════
# CARD-BASED LEARNING
# ═══════════════════════════════════════════════════════════════════

@router.post("/sessions/{session_id}/cards", response_model=CardsResponse)
@limiter.limit("10/minute")
async def get_cards(request: Request, session_id: UUID, db: AsyncSession = Depends(get_db)):
    """Generate card-based lesson with sub-content cards and quiz questions."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
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
    db: AsyncSession = Depends(get_db),
):
    """AI assistant responds to student during card-based learning."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
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
    db: AsyncSession = Depends(get_db),
):
    """Transition from CARDS to CARDS_DONE phase (gateway only, no mastery)."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.phase == "COMPLETED":
        raise HTTPException(400, "Session is already completed")

    result = await teaching_svc.complete_cards(db, session)
    return result


@router.post(
    "/sessions/{session_id}/next-section-cards",
    response_model=NextSectionCardsResponse,
    summary="Generate cards for the next sub-section (rolling adaptive)",
)
@limiter.limit("30/minute")
async def next_section_cards(
    request: Request,
    session_id: UUID,
    req: NextSectionCardsRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate cards for the next sub-section using live session signals (rolling adaptive).

    Pops one section from the session's concepts_queue, generates cards with mode determined
    by blended live signals + student history, appends to session cache, and returns the new cards
    along with rolling progress metadata.

    Returns 400 when no more sections are queued (caller should use complete-cards instead).
    """
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.phase not in ("PRESENTING", "CARDS"):
        raise HTTPException(400, f"Session not in card phase (phase={session.phase})")

    student = await db.get(Student, session.student_id)
    result = await teaching_svc.generate_next_section_cards(
        db, session, student, signals=req
    )
    await db.commit()
    return NextSectionCardsResponse(**result, session_id=session_id)


@router.post(
    "/sessions/{session_id}/next-card",
    response_model=NextCardResponse,
    summary="Generate the next card on demand (per-card adaptive generation)",
)
@limiter.limit("30/minute")
async def get_next_adaptive_card(
    request: Request,
    session_id: UUID,
    req: NextCardRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate exactly one card for the next content piece in the session queue.

    Uses live signals from the card just completed to determine presentation mode
    (STRUGGLING / NORMAL / FAST) for the new card. Returns has_more_concepts=False
    with card=null when all content pieces have been covered — the frontend should
    then transition to the Socratic check phase.

    Returns 409 when session.phase is not CARDS.
    """
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.phase not in ("CARDS", "PRESENTING"):
        raise HTTPException(
            409,
            f"Cannot generate next card: session is in {session.phase} phase (expected CARDS or PRESENTING)",
        )

    student = await db.get(Student, session.student_id)
    if not student:
        raise HTTPException(404, "Student not found")

    try:
        result = await teaching_svc.generate_per_card(db, session, student, req)
    except ValueError as exc:
        logger.exception(
            "[next-card] generation_failed: session_id=%s error=%s",
            session_id, exc,
        )
        raise HTTPException(500, f"Card generation failed: {exc}")

    await db.commit()

    return NextCardResponse(
        session_id=session.id,
        card=LessonCard(**result["card"]) if result.get("card") else None,
        has_more_concepts=result["has_more_concepts"],
        current_mode=result["current_mode"],
        concepts_covered_count=result["concepts_covered_count"],
        concepts_total=result["concepts_total"],
    )


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

    try:
        cards_dicts = await teaching_svc.generate_per_chunk(session, db, req.chunk_id)
        cards = []
        for _c in cards_dicts:
            try:
                cards.append(LessonCard(**_c))
            except Exception as _val_err:
                logger.warning("[chunk-cards] skipping invalid card dict: %s", _val_err)
        _chunks = await chunk_ksvc.get_chunks_for_concept(db, session.book_slug or DEFAULT_BOOK_SLUG, session.concept_id)
        chunk_index = next((i for i, c in enumerate(_chunks) if c["id"] == req.chunk_id), 0)
        await db.commit()
        return ChunkCardsResponse(
            cards=cards,
            chunk_id=req.chunk_id,
            chunk_index=chunk_index,
            total_chunks=len(_chunks),
            is_last_chunk=chunk_index == len(_chunks) - 1,
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
    response_model=LessonCard,
    summary="Generate a recovery card when student fails an MCQ twice",
)
@limiter.limit("20/minute")
async def generate_chunk_recovery_card(
    request: Request,
    session_id: UUID,
    req: RecoveryCardRequest,
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

    chunk = await chunk_ksvc.get_chunk(db, req.chunk_id)
    if not chunk:
        raise HTTPException(404, f"Chunk not found: {req.chunk_id}")

    images = await chunk_ksvc.get_chunk_images(db, req.chunk_id)

    recovery = await teaching_svc.generate_recovery_card_for_chunk(
        session=session,
        chunk=chunk,
        chunk_images=images,
        card_index=req.card_index,
        wrong_answers=req.wrong_answers,
    )

    if not recovery:
        raise HTTPException(500, "Recovery card generation failed")

    await db.commit()
    return LessonCard(**recovery)


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
    db: AsyncSession = Depends(get_db),
):
    """Record completion of a study chunk and determine mode for the next chunk."""
    from api.teaching_service import EXERCISE_HEADING_PATTERNS
    from datetime import datetime

    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    score = round((req.correct / req.total) * 100) if req.total > 0 else 0

    # Record progress — full dict reassignment required for JSONB change detection
    existing_progress = dict(session.chunk_progress or {})
    existing_progress[req.chunk_id] = {
        "mode": req.mode_used,
        "score": score,
        "correct": req.correct,
        "total": req.total,
        "completed_at": datetime.utcnow().isoformat(),
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

    # Update presentation_text cache with next mode
    if session.presentation_text:
        try:
            cache = json.loads(session.presentation_text)
            cache["current_mode"] = next_mode
            session.presentation_text = json.dumps(cache)
        except Exception:
            pass

    # Get all chunks for this concept
    all_chunks = await chunk_ksvc.get_chunks_for_concept(
        db, session.book_slug, session.concept_id
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
         and _get_chunk_type(c.get("heading", "")) == "teaching"),
        None,
    )

    # all_study_complete: all teaching chunks are in chunk_progress
    completed_ids = set(existing_progress.keys())
    teaching_ids = {
        str(c["id"]) for c in all_sorted
        if _get_chunk_type(c.get("heading", "")) == "teaching"
    }
    all_study_complete = bool(teaching_ids) and teaching_ids.issubset(completed_ids)

    await db.commit()
    return CompleteChunkResponse(
        chunk_id=req.chunk_id,
        score=score,
        next_mode=next_mode,
        next_chunk_id=str(next_teaching["id"]) if next_teaching else None,
        all_study_complete=all_study_complete,
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


@router.get(
    "/sessions/{session_id}/chunks",
    response_model=ChunkListResponse,
    summary="List ordered chunks for the session's concept",
)
@limiter.limit("60/minute")
async def list_chunks(
    request: Request,
    session_id: UUID,
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

        book_slug = session.book_slug or DEFAULT_BOOK_SLUG
        concept_id = session.concept_id

        # Fetch all chunks in textbook order
        result = await db.execute(
            select(ConceptChunk)
            .where(ConceptChunk.book_slug == book_slug, ConceptChunk.concept_id == concept_id)
            .order_by(ConceptChunk.order_index)
        )
        chunks = [c for c in result.scalars().all() if (c.text or "").strip()]

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
                chunk_type=_get_chunk_type(c.heading or ""),
                completed=str(c.id) in progress,
                score=progress.get(str(c.id), {}).get("score"),
                mode_used=progress.get(str(c.id), {}).get("mode"),
            )
            for c in chunks
        ]

        section_title = chunks[0].section if chunks else ""

        # Inject synthetic exam gate if the section has no exercise_gate chunk
        visible_for_exam = [s for s in summaries if s.chunk_type != "exam_question_source"]
        has_exercise_gate = any(s.chunk_type == "exercise_gate" for s in summaries)
        if visible_for_exam and not has_exercise_gate:
            from uuid import uuid5, NAMESPACE_DNS
            synthetic_id = str(uuid5(NAMESPACE_DNS, f"exam_gate:{concept_id}"))
            summaries.append(ChunkSummary(
                chunk_id=synthetic_id,
                order_index=(summaries[-1].order_index + 1) if summaries else 0,
                heading="Section Exam",
                has_images=False,
                has_mcq=False,
                chunk_type="exercise_gate",
                completed=False,
                score=None,
                mode_used=None,
            ))

        logger.info(
            "[chunks] session_id=%s concept_id=%s total=%d current_index=%d",
            session_id, concept_id, len(summaries), session.chunk_index or 0,
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


@router.post(
    "/sessions/{session_id}/exam/start",
    response_model=ExamStartResponse,
    summary="Generate typed-answer exam questions for all chunks",
)
@limiter.limit("10/minute")
async def start_exam(
    request: Request,
    session_id: UUID,
    req: ExamStartRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate one open-ended question per teaching chunk.

    Questions are stored in session.exam_scores JSONB so submit can evaluate
    them without re-generating. Sets exam_phase = 'exam'.
    """
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    book_slug = session.book_slug or DEFAULT_BOOK_SLUG
    chunks = await chunk_ksvc.get_chunks_for_concept(db, book_slug, req.concept_id)

    if not chunks:
        raise HTTPException(404, f"No chunks found for concept '{req.concept_id}'")

    # Filter to teaching and practice chunks as exam source material
    exam_source_chunks = [
        c for c in chunks
        if _get_chunk_type(c["heading"]) in ("teaching", "practice")
    ]

    if not exam_source_chunks:
        raise HTTPException(409, "No exam source chunks available for exam")

    llm = teaching_svc.openai

    q_system = (
        "You are an educational assessor. Generate one open-ended question that tests "
        "deep understanding of the subsection below. The question must require a "
        "sentence answer (not a single word or number). "
        'Return JSON only: {"question": "..."}'
    )

    questions_data: list[dict] = []
    exam_questions: list[ExamQuestion] = []
    global_idx = 0

    for chunk in exam_source_chunks:
        for _ in range(CHUNK_EXAM_QUESTIONS_PER_CHUNK):
            user_prompt = f"Heading: {chunk['heading']}\n\n{chunk['text'][:500]}"
            try:
                parsed = await _call_llm_json(llm, q_system, user_prompt, CHUNK_MAX_TOKENS_EXAM_Q)
                question_text = parsed.get("question", "").strip()
                if not question_text:
                    raise ValueError("empty question returned")
            except Exception as exc:
                logger.error(
                    "[exam-start] question_gen_failed: session_id=%s chunk_id=%s error=%s",
                    session_id, chunk["id"], exc,
                )
                raise HTTPException(500, f"Question generation failed for chunk '{chunk['heading']}'")

            questions_data.append({
                "question_index": global_idx,
                "chunk_id": chunk["id"],
                "chunk_heading": chunk["heading"],
                "question_text": question_text,
            })
            exam_questions.append(ExamQuestion(
                question_index=global_idx,
                chunk_id=chunk["id"],
                chunk_heading=chunk["heading"],
                question_text=question_text,
            ))
            global_idx += 1

    # Persist questions in session; answers will be filled on submit
    session.exam_phase = "exam"
    session.exam_scores = {"questions": questions_data, "answers": {}}
    await db.commit()

    logger.info(
        "[exam-start] session_id=%s total_questions=%d",
        session_id, len(questions_data),
    )

    return ExamStartResponse(
        exam_id=str(session_id),
        questions=exam_questions,
        total_questions=len(exam_questions),
        pass_threshold=CHUNK_EXAM_PASS_RATE,
    )


@router.post(
    "/sessions/{session_id}/exam/submit",
    response_model=ExamSubmitResponse,
    summary="Submit typed answers for LLM evaluation",
)
@limiter.limit("10/minute")
async def submit_exam(
    request: Request,
    session_id: UUID,
    req: ExamSubmitRequest,
    db: AsyncSession = Depends(get_db),
):
    """Evaluate student answers via LLM; compute per-chunk and overall scores.

    On pass: inserts StudentMastery row (with race-condition guard).
    Increments exam_attempt; stores failed_chunk_ids for retry routing.
    """
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    stored = session.exam_scores or {}
    questions_data: list[dict] = stored.get("questions", [])

    if not questions_data:
        raise HTTPException(400, "No exam questions found — call exam/start first")
    if len(req.answers) != len(questions_data):
        raise HTTPException(
            400,
            f"Expected {len(questions_data)} answers, received {len(req.answers)}",
        )

    llm = teaching_svc.openai

    eval_system = (
        "You are a math educator evaluating a student answer. "
        "Mark it correct if it demonstrates understanding of the key concept — "
        "exact wording is not required. "
        'Return JSON only: {"correct": true or false, "feedback": "one sentence"}'
    )

    # Build answer lookup by question_index
    answer_map: dict[int, str] = {a.question_index: a.answer_text for a in req.answers}

    # Per-chunk bookkeeping: each teaching chunk has exactly one question
    chunk_correct: dict[str, int] = {}   # chunk_id -> 1 (correct) or 0 (wrong)
    chunk_headings: dict[str, str] = {}  # chunk_id -> heading

    for qdata in questions_data:
        qidx = qdata["question_index"]
        chunk_id = qdata["chunk_id"]
        chunk_heading = qdata["chunk_heading"]
        chunk_headings[chunk_id] = chunk_heading

        answer_text = answer_map.get(qidx, "").strip()

        user_prompt = (
            f"Question: {qdata['question_text']}\n"
            f"Student answer: {answer_text}\n"
            "Correct if the answer demonstrates understanding of the key concept."
        )
        try:
            parsed = await _call_llm_json(
                llm, eval_system, user_prompt, CHUNK_MAX_TOKENS_EXAM_EVAL
            )
            is_correct = bool(parsed.get("correct", False))
        except Exception as exc:
            logger.error(
                "[exam-submit] eval_failed: session_id=%s q_index=%d error=%s",
                session_id, qidx, exc,
            )
            # Treat evaluation failure as incorrect to avoid inflating scores
            is_correct = False

        chunk_correct[chunk_id] = 1 if is_correct else 0

    total_questions = len(questions_data)
    total_correct = sum(chunk_correct.values())
    score = total_correct / total_questions if total_questions else 0.0
    passed = score >= CHUNK_EXAM_PASS_RATE

    # Per-chunk score fractions (one question per chunk → binary 0.0 or 1.0)
    per_chunk_scores: dict[str, float] = {
        cid: float(correct) for cid, correct in chunk_correct.items()
    }

    failed_chunks = [
        PerChunkScore(
            chunk_id=cid,
            heading=chunk_headings.get(cid, ""),
            score=per_chunk_scores[cid],
        )
        for cid, sc in per_chunk_scores.items()
        if sc < 1.0
    ]

    failed_chunk_id_list = [fc.chunk_id for fc in failed_chunks]

    # Update session
    new_attempt = (session.exam_attempt or 0) + 1
    session.exam_attempt = new_attempt
    session.failed_chunk_ids = failed_chunk_id_list

    # Merge answers into stored state for audit
    updated_scores = dict(stored)
    updated_scores["answers"] = answer_map
    updated_scores["per_chunk_scores"] = per_chunk_scores
    session.exam_scores = updated_scores

    if passed:
        session.exam_phase = None
        session.concept_mastered = True
        session.phase = "COMPLETED"
        session.completed_at = datetime.now(timezone.utc)

        # Insert StudentMastery with race-condition guard
        existing = await db.execute(
            select(StudentMastery).where(
                StudentMastery.student_id == session.student_id,
                StudentMastery.concept_id == session.concept_id,
            )
        )
        existing_mastery = existing.scalar_one_or_none()
        if existing_mastery:
            existing_mastery.session_id = session.id
            existing_mastery.mastered_at = datetime.now(timezone.utc)
        else:
            db.add(StudentMastery(
                student_id=session.student_id,
                concept_id=session.concept_id,
                session_id=session.id,
            ))
        logger.info(
            "[exam-submit] PASSED: session_id=%s score=%.2f attempt=%d",
            session_id, score, new_attempt,
        )
    else:
        logger.info(
            "[exam-submit] FAILED: session_id=%s score=%.2f attempt=%d failed_chunks=%d",
            session_id, score, new_attempt, len(failed_chunks),
        )

    await db.commit()

    # retry_options: targeted is only available if attempt < 3
    retry_options = ["targeted", "full_redo"] if new_attempt < 3 else ["full_redo"]

    return ExamSubmitResponse(
        score=round(score, 4),
        passed=passed,
        total_correct=total_correct,
        total_questions=total_questions,
        per_chunk_scores=per_chunk_scores,
        failed_chunks=failed_chunks,
        exam_attempt=new_attempt,
        retry_options=retry_options,
    )


@router.post(
    "/sessions/{session_id}/exam/retry",
    response_model=ExamRetryResponse,
    summary="Initiate targeted or full-redo retry after a failed exam",
)
@limiter.limit("10/minute")
async def retry_exam(
    request: Request,
    session_id: UUID,
    req: ExamRetryRequest,
    db: AsyncSession = Depends(get_db),
):
    """Set exam_phase to 'retry_study' and return the chunks to re-study.

    targeted: returns only the chunks where the student scored 0.
    full_redo: returns all chunks for the concept.
    Targeted retry is blocked after 3 attempts (HTTP 409).
    """
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    if req.retry_type not in ("targeted", "full_redo"):
        raise HTTPException(400, "retry_type must be 'targeted' or 'full_redo'")

    current_attempt = session.exam_attempt or 0

    if req.retry_type == "targeted" and current_attempt >= 3:
        raise HTTPException(
            409, "Targeted retry not available after 3 attempts — use full_redo"
        )

    book_slug = session.book_slug or DEFAULT_BOOK_SLUG
    all_chunks = await chunk_ksvc.get_chunks_for_concept(db, book_slug, session.concept_id)

    if req.retry_type == "targeted":
        # Return only the failed chunks identified in the last submit
        failed_ids: set[str] = set(req.failed_chunk_ids or session.failed_chunk_ids or [])
        retry_raw = [c for c in all_chunks if c["id"] in failed_ids]
    else:
        retry_raw = all_chunks

    # Check image existence for returned chunks
    if retry_raw:
        retry_ids = [UUID(c["id"]) for c in retry_raw]
        img_result = await db.execute(
            select(ChunkImage.chunk_id)
            .where(ChunkImage.chunk_id.in_(retry_ids))
            .distinct()
        )
        chunks_with_images: set = {row[0] for row in img_result.fetchall()}
    else:
        chunks_with_images = set()

    retry_summaries = [
        ChunkSummary(
            chunk_id=c["id"],
            order_index=c["order_index"],
            heading=c["heading"],
            has_images=UUID(c["id"]) in chunks_with_images,
            has_mcq=_heading_has_mcq(c["heading"]),
        )
        for c in retry_raw
    ]

    session.exam_phase = "retry_study"
    await db.commit()

    logger.info(
        "[exam-retry] session_id=%s retry_type=%s retry_chunks=%d attempt=%d",
        session_id, req.retry_type, len(retry_summaries), current_attempt,
    )

    return ExamRetryResponse(
        retry_chunks=retry_summaries,
        exam_phase="retry_study",
        exam_attempt=current_attempt,
    )


@router.post(
    "/sessions/{session_id}/remediation-cards",
    response_model=RemediationCardsResponse,
    summary="Generate targeted re-teaching cards for failed topics",
)
@limiter.limit("10/minute")
async def get_remediation_cards(
    request: Request,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate remediation cards after a failed Socratic check.
    Session must be in REMEDIATING or REMEDIATING_2 phase.
    Returns TEACH + EXAMPLE + RECAP cards focused on the failed topics.
    """
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.phase not in ("REMEDIATING", "REMEDIATING_2"):
        raise HTTPException(
            400,
            f"Cannot generate remediation cards: session is in {session.phase} phase "
            "(expected REMEDIATING or REMEDIATING_2)"
        )

    cards = await teaching_svc.generate_remediation_cards(session_id, db)
    return RemediationCardsResponse(cards=cards, session_phase=session.phase)


@router.post(
    "/sessions/{session_id}/recheck",
    response_model=RecheckResponse,
    summary="Begin a new Socratic check focused on previously failed topics",
)
@limiter.limit("10/minute")
async def begin_recheck(
    request: Request,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Start a re-check Socratic session after remediation cards have been studied.
    Session must be in REMEDIATING or REMEDIATING_2 phase.
    Transitions session to RECHECKING or RECHECKING_2 and returns the opening question.
    """
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.phase not in ("REMEDIATING", "REMEDIATING_2"):
        raise HTTPException(
            400,
            f"Cannot begin recheck: session is in {session.phase} phase "
            "(expected REMEDIATING or REMEDIATING_2)"
        )

    result = await teaching_svc.begin_recheck(session_id, db)
    return RecheckResponse(
        response=result["response"],
        phase=result["phase"],
        attempt=result["attempt"],
    )


@router.post("/sessions/{session_id}/record-interaction")
@limiter.limit("30/minute")
async def record_card_interaction(
    request: Request,
    session_id: UUID,
    req: RecordInteractionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Save the final card interaction when the student clicks Finish Cards."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
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
    )
    db.add(interaction)
    await db.commit()

    # Update student's engagement effectiveness history if a strategy was applied
    if req.strategy_applied and strategy_effective is not None:
        from api.teaching_service import _update_strategy_effectiveness
        await _update_strategy_effectiveness(
            db, session.student_id, req.strategy_applied, strategy_effective
        )

    return {"saved": True}


@router.post("/sessions/{session_id}/complete-card")
@limiter.limit("30/minute")
async def complete_card(
    request: Request,
    session_id: UUID,
    req: CompleteCardRequest,
    db: AsyncSession = Depends(get_db),
):
    """Record card interaction; optionally generate recovery card; return updated learning profile."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
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
async def get_review_due(request: Request, student_id: UUID, db: AsyncSession = Depends(get_db)):
    """Return concepts due for spaced review for this student."""
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
    request: Request, review_id: UUID, db: AsyncSession = Depends(get_db)
):
    """Mark a spaced review as completed."""
    review = await db.get(SpacedReview, review_id)
    if not review:
        raise HTTPException(404, "Review not found")
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
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent card interactions for a student. Used for adaptive engine verification."""
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
    db: AsyncSession = Depends(get_db),
):
    """List all meaningful teaching sessions for a student (any phase past PRESENTING)."""
    result = await db.execute(
        select(TeachingSession)
        .where(TeachingSession.student_id == student_id)
        .where(TeachingSession.phase.in_(["CARDS", "CARDS_DONE", "CHECKING", "COMPLETED"]))
        .order_by(TeachingSession.started_at.desc())
        .limit(50)
    )
    sessions = result.scalars().all()
    return {
        "student_id": str(student_id),
        "sessions": [
            {
                "id": str(s.id),
                "concept_id": s.concept_id,
                "phase": s.phase,
                "check_score": s.check_score,
                "mastered": s.concept_mastered,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
            }
            for s in sessions
        ],
    }


@router.post("/sessions/{session_id}/regenerate-mcq", response_model=RegenerateMCQResponse)
@limiter.limit("30/minute")
async def regenerate_mcq_endpoint(
    request: Request,
    session_id: UUID,
    body: RegenerateMCQRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate a replacement MCQ after a wrong answer — same concept, different scenario."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    new_mcq = await teaching_svc.regenerate_mcq(body)
    return RegenerateMCQResponse(question=new_mcq)


@router.post("/sessions/{session_id}/section-complete", response_model=SectionCompleteResponse)
@limiter.limit("60/minute")
async def complete_section(
    request: Request,
    session_id: UUID,
    body: SectionCompleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Called when student completes all cards in a section.
    Increments section_count, recalculates avg_state_score, updates state_distribution.
    """
    # 1. Load session to get student_id
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2. Load student
    student = await db.get(Student, session.student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # 3. Increment section_count
    student.section_count = (student.section_count or 0) + 1

    # 4. Update avg_state_score as rolling average
    n = student.section_count
    old_avg = student.avg_state_score or 2.0
    student.avg_state_score = ((old_avg * (n - 1)) + body.state_score) / n

    # 5. Update state_distribution
    dist = dict(student.state_distribution or {"struggling": 0, "normal": 0, "fast": 0})
    if body.state_score < 1.5:
        dist["struggling"] = dist.get("struggling", 0) + 1
    elif body.state_score >= 2.5:
        dist["fast"] = dist.get("fast", 0) + 1
    else:
        dist["normal"] = dist.get("normal", 0) + 1
    student.state_distribution = dist

    await db.commit()
    await db.refresh(student)

    logger.info(
        "[section-complete] session_id=%s student_id=%s section_count=%d "
        "avg_state_score=%.2f state_score=%.2f",
        session_id, session.student_id, student.section_count,
        student.avg_state_score, body.state_score,
    )

    return SectionCompleteResponse(
        section_count=student.section_count,
        avg_state_score=student.avg_state_score,
        state_distribution=student.state_distribution,
    )


@router.get("/sessions/{session_id}/card-interactions")
@limiter.limit("120/minute")
async def get_session_card_interactions(
    request: Request,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return all card interactions for a specific session, ordered by card index."""
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


@router.get("/books", response_model=list[dict])
async def list_available_books(db: AsyncSession = Depends(get_db)):
    """Return all processed books available for study."""
    try:
        from config import BOOK_REGISTRY
        # Build slug → title lookup from the registry (each entry has "book_slug" and "title")
        slug_to_title = {
            entry["book_slug"]: entry["title"]
            for entry in BOOK_REGISTRY.values()
            if isinstance(entry, dict) and "book_slug" in entry and "title" in entry
        }
    except (ImportError, AttributeError):
        slug_to_title = {}

    active_books: set[str] = set()
    try:
        active_books = await chunk_ksvc.get_active_books(db)
    except Exception as exc:
        logger.warning("[list_available_books] get_active_books failed: %s", exc)

    return [
        {
            "slug": slug,
            "title": slug_to_title.get(slug, slug.replace("_", " ").title()),
        }
        for slug in sorted(active_books)
    ]
