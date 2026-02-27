"""
Week 2 API endpoints: The Pedagogical Loop.
Teaching sessions, Socratic checks, style switching.
"""

import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.connection import get_db
from db.models import Student, TeachingSession, ConversationMessage, StudentMastery, SpacedReview
from api.teaching_schemas import (
    CreateStudentRequest, StudentResponse,
    StartSessionRequest, SessionResponse,
    PresentationResponse,
    StudentResponseRequest, SocraticResponse,
    SwitchStyleRequest,
    SessionHistoryResponse, MessageResponse,
    CardsResponse, LessonCard, CardQuestion,
    AssistRequest, AssistResponse,
    UpdateLanguageRequest,
)

router = APIRouter(prefix="/api/v2", tags=["teaching"])

# Set during app startup in main.py lifespan
teaching_svc = None


# ═══════════════════════════════════════════════════════════════════
# STUDENTS
# ═══════════════════════════════════════════════════════════════════

@router.post("/students", response_model=StudentResponse)
async def create_student(req: CreateStudentRequest, db: AsyncSession = Depends(get_db)):
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
async def list_students(db: AsyncSession = Depends(get_db)):
    """List all student profiles with their mastery counts."""
    result = await db.execute(
        select(Student).order_by(Student.created_at.desc())
    )
    students = result.scalars().all()
    student_list = []
    for s in students:
        count_result = await db.execute(
            select(func.count()).select_from(StudentMastery).where(
                StudentMastery.student_id == s.id
            )
        )
        student_list.append({
            "id": str(s.id),
            "display_name": s.display_name,
            "interests": s.interests or [],
            "preferred_style": s.preferred_style,
            "preferred_language": s.preferred_language or "en",
            "mastered_count": count_result.scalar() or 0,
        })
    return student_list


@router.get("/students/{student_id}", response_model=StudentResponse)
async def get_student(student_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get student profile."""
    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(404, "Student not found")
    return student


@router.get("/students/{student_id}/mastery")
async def get_student_mastery(student_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get all concepts mastered by a student."""
    result = await db.execute(
        select(StudentMastery).where(StudentMastery.student_id == student_id)
    )
    records = result.scalars().all()
    return {
        "student_id": str(student_id),
        "mastered_concepts": [r.concept_id for r in records],
        "count": len(records),
    }


@router.patch("/students/{student_id}/language", response_model=StudentResponse)
async def update_student_language(
    student_id: UUID, req: UpdateLanguageRequest, db: AsyncSession = Depends(get_db)
):
    """Update a student's preferred language."""
    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(404, "Student not found")
    student.preferred_language = req.language
    await db.flush()
    return student


# ═══════════════════════════════════════════════════════════════════
# TEACHING SESSIONS
# ═══════════════════════════════════════════════════════════════════

@router.post("/sessions", response_model=SessionResponse)
async def start_session(req: StartSessionRequest, db: AsyncSession = Depends(get_db)):
    """Start a new teaching session for a student + concept."""
    student = await db.get(Student, req.student_id)
    if not student:
        raise HTTPException(404, "Student not found")

    session = await teaching_svc.start_session(
        db, req.student_id, req.concept_id, req.style, req.lesson_interests
    )
    return session


@router.post("/sessions/{session_id}/present", response_model=PresentationResponse)
async def get_presentation(session_id: UUID, db: AsyncSession = Depends(get_db)):
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
async def begin_check(session_id: UUID, db: AsyncSession = Depends(get_db)):
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
async def respond_to_check(
    session_id: UUID,
    req: StudentResponseRequest,
    db: AsyncSession = Depends(get_db),
):
    """Submit student response during Socratic check. Returns AI's next question or completion."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.phase != "CHECKING":
        raise HTTPException(
            400, f"Cannot respond: session is in {session.phase} phase"
        )

    result = await teaching_svc.handle_student_response(db, session, req.message)

    # Count student exchanges in the CHECKING phase
    exchange_result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.session_id == session_id)
        .where(ConversationMessage.phase == "CHECKING")
        .where(ConversationMessage.role == "user")
    )
    exchange_count = len(exchange_result.scalars().all())

    return SocraticResponse(
        session_id=session.id,
        response=result["response"],
        phase=result["phase"],
        check_complete=result["check_complete"],
        score=result["score"],
        mastered=result["mastered"],
        exchange_count=exchange_count,
    )


@router.put("/sessions/{session_id}/style")
async def switch_style(
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
async def get_session(session_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get session status."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@router.get("/sessions/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(session_id: UUID, db: AsyncSession = Depends(get_db)):
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
async def get_cards(session_id: UUID, db: AsyncSession = Depends(get_db)):
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

    # Build validated response
    cards = []
    for card_data in result.get("cards", []):
        questions = [
            CardQuestion(**q) for q in card_data.get("questions", [])
        ]
        cards.append(LessonCard(
            index=card_data["index"],
            title=card_data["title"],
            content=card_data["content"],
            questions=questions,
            images=card_data.get("images", []),
        ))

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
async def assist_student(
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
async def complete_cards(
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


# ═══════════════════════════════════════════════════════════════════
# SPACED REVIEW
# ═══════════════════════════════════════════════════════════════════

@router.get("/students/{student_id}/review-due")
async def get_review_due(student_id: UUID, db: AsyncSession = Depends(get_db)):
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
