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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import logging

from config import (
    CARD_HISTORY_DEFAULT_LIMIT,
    CARD_HISTORY_MAX_LIMIT,
    XP_MASTERY,
    XP_MASTERY_BONUS,
    XP_MASTERY_BONUS_THRESHOLD,
    XP_CONSOLATION,
)
from db.connection import get_db
from db.models import Student, TeachingSession, ConversationMessage, StudentMastery, SpacedReview, CardInteraction
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
)
from api.rate_limiter import limiter

logger = logging.getLogger(__name__)

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

    # ── Query 3: CardInteraction ──────────────────────────────────────────────
    cards_result = await db.execute(
        select(CardInteraction)
        .where(CardInteraction.student_id == student_id)
        .limit(10000)
    )
    card_rows = cards_result.scalars().all()
    total_cards = len(card_rows)

    if total_cards > 0:
        avg_wrong_attempts_per_card = round(
            sum(c.wrong_attempts or 0 for c in card_rows) / total_cards, 3
        )
        avg_hints_per_card = round(
            sum(c.hints_used or 0 for c in card_rows) / total_cards, 3
        )
        avg_time_on_card_sec = round(
            sum(c.time_on_card_sec or 0.0 for c in card_rows) / total_cards, 3
        )
    else:
        avg_wrong_attempts_per_card = 0.0
        avg_hints_per_card = 0.0
        avg_time_on_card_sec = 0.0

    # Hardest concept: concept_id with highest total wrong_attempts
    hardest_concept_id: str | None = None
    hardest_concept_wrong_attempts: int = 0
    if card_rows:
        wrong_by_concept: dict[str, int] = {}
        for c in card_rows:
            wrong_by_concept[c.concept_id] = (
                wrong_by_concept.get(c.concept_id, 0) + (c.wrong_attempts or 0)
            )
        hardest_concept_id = max(wrong_by_concept, key=lambda k: wrong_by_concept[k])
        hardest_concept_wrong_attempts = wrong_by_concept[hardest_concept_id]

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

    graph = teaching_svc.knowledge_svc.graph

    if concept_id not in graph:
        return ConceptReadinessResponse(
            concept_id=concept_id,
            all_prerequisites_met=True,
            unmet_prerequisites=[],
        )

    unmet = []
    for prereq_id in graph.predecessors(concept_id):
        if prereq_id not in mastered_ids:
            title = graph.nodes[prereq_id].get("title", prereq_id)
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
    student = await db.get(Student, req.student_id)
    if not student:
        raise HTTPException(404, "Student not found")

    session = await teaching_svc.start_session(
        db, req.student_id, req.concept_id, req.style, req.lesson_interests
    )
    return session


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

    concept = teaching_svc.knowledge_svc.get_concept_detail(session.concept_id)

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
    first_question = await teaching_svc.begin_socratic_check(db, session, student)

    return SocraticResponse(
        session_id=session.id,
        response=first_question,
        phase=session.phase,
        check_complete=False,
        exchange_count=1,
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
    )
    db.add(interaction)
    await db.commit()
    return {"saved": True}


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
