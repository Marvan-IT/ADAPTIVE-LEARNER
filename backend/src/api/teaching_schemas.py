"""
Pydantic schemas for the Week 2 Teaching endpoints.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


# ── Request Schemas ───────────────────────────────────────────────

class CreateStudentRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)
    interests: list[str] = Field(
        default_factory=list,
        description="Student's interests for metaphor personalization",
    )
    preferred_style: str = Field(
        default="default",
        pattern="^(default|pirate|astronaut|gamer)$",
    )
    preferred_language: str = Field(default="en")


class StartSessionRequest(BaseModel):
    student_id: UUID
    concept_id: str = Field(
        ..., description="e.g., PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS"
    )
    style: str = Field(
        default="default",
        pattern="^(default|pirate|astronaut|gamer)$",
    )
    lesson_interests: list[str] = Field(
        default_factory=list,
        description="Per-lesson interest override (empty = use student profile interests)",
    )


class StudentResponseRequest(BaseModel):
    message: str = Field(
        ..., min_length=1, max_length=2000, description="Student's response text"
    )


class SwitchStyleRequest(BaseModel):
    style: str = Field(..., pattern="^(default|pirate|astronaut|gamer)$")


# ── Response Schemas ──────────────────────────────────────────────

class UpdateLanguageRequest(BaseModel):
    language: str = Field(..., min_length=2, max_length=10)


class StudentResponse(BaseModel):
    id: UUID
    display_name: str
    interests: list[str]
    preferred_style: str
    preferred_language: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionResponse(BaseModel):
    id: UUID
    student_id: UUID
    concept_id: str
    book_slug: str
    phase: str
    style: str
    started_at: datetime
    completed_at: datetime | None = None
    check_score: int | None = None
    concept_mastered: bool

    model_config = {"from_attributes": True}


class PresentationResponse(BaseModel):
    session_id: UUID
    concept_id: str
    concept_title: str
    presentation: str
    style: str
    phase: str
    images: list[dict] = Field(default_factory=list, description="Extracted textbook images")
    latex_expressions: list[str] = Field(default_factory=list, description="Key LaTeX formulas")


class SocraticResponse(BaseModel):
    session_id: UUID
    response: str
    phase: str
    check_complete: bool
    score: int | None = None
    mastered: bool | None = None
    exchange_count: int
    xp_awarded: int | None = None   # Populated only when check_complete=True


class MessageResponse(BaseModel):
    role: str
    content: str
    phase: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionHistoryResponse(BaseModel):
    session: SessionResponse
    messages: list[MessageResponse]


# ── Card-Based Learning Schemas ──────────────────────────────

class CardQuestion(BaseModel):
    id: str = Field(..., description="e.g., c0_q0")
    type: str = Field(..., pattern="^(mcq|true_false|fill_blank)$")
    question: str
    options: list[str] | None = Field(default=None, description="MCQ choices")
    correct_index: int | None = Field(default=None, description="MCQ correct option index")
    correct_answer: str | None = Field(default=None, description="true_false/fill_blank answer")
    explanation: str = ""


class LessonCard(BaseModel):
    index: int
    title: str
    content: str = Field(..., description="AI-generated markdown explanation")
    questions: list[CardQuestion]
    images: list[dict] = Field(default_factory=list)


class CardsResponse(BaseModel):
    session_id: UUID
    concept_id: str
    concept_title: str
    style: str
    phase: str
    cards: list[LessonCard]
    total_questions: int


class AssistRequest(BaseModel):
    card_index: int
    message: str | None = Field(default=None, description="Student message or null for idle trigger")
    trigger: str = Field(default="user", pattern="^(user|idle)$")


class AssistResponse(BaseModel):
    session_id: UUID
    response: str
    card_index: int


# CompleteCardsRequest removed — cards are gateways only, no scores sent


# ── Adaptive Transparency Schemas ────────────────────────────────────────────

class CardInteractionRecord(BaseModel):
    """A single card interaction row for the history endpoint."""

    id: str                          # UUID as string
    session_id: str                  # UUID as string
    concept_id: str
    card_index: int
    time_on_card_sec: float
    wrong_attempts: int
    hints_used: int
    idle_triggers: int
    adaptation_applied: str | None
    completed_at: str                # ISO 8601 string

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _coerce_uuids_and_datetime(cls, data):
        """Convert UUID fields to strings and datetime to ISO 8601 when loading from ORM."""
        # Support both ORM objects (via from_attributes) and plain dicts
        if hasattr(data, "__dict__"):
            return {
                "id": str(data.id),
                "session_id": str(data.session_id),
                "concept_id": data.concept_id,
                "card_index": data.card_index,
                "time_on_card_sec": data.time_on_card_sec,
                "wrong_attempts": data.wrong_attempts,
                "hints_used": data.hints_used,
                "idle_triggers": data.idle_triggers,
                "adaptation_applied": data.adaptation_applied,
                "completed_at": data.completed_at.isoformat() if isinstance(data.completed_at, datetime) else str(data.completed_at),
            }
        # Plain dict path — coerce UUID values to strings if needed
        result = dict(data)
        for field in ("id", "session_id"):
            if field in result and not isinstance(result[field], str):
                result[field] = str(result[field])
        if "completed_at" in result and isinstance(result["completed_at"], datetime):
            result["completed_at"] = result["completed_at"].isoformat()
        return result


class CardHistoryResponse(BaseModel):
    """Response for GET /api/v2/students/{student_id}/card-history."""

    student_id: str
    total_returned: int
    interactions: list[CardInteractionRecord]
