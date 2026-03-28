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
    book_slug: str = Field(
        default="prealgebra",
        description="Book slug matching the processed output directory, e.g. 'prealgebra', 'elementary_algebra'",
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
    engagement_signal: str | None = None
    strategy_applied: str | None = None


class SwitchStyleRequest(BaseModel):
    style: str = Field(..., pattern="^(default|pirate|astronaut|gamer)$")


# ── Response Schemas ──────────────────────────────────────────────

class UpdateLanguageRequest(BaseModel):
    language: str = Field(
        ...,
        pattern=r"^(en|ar|de|es|fr|hi|ja|ko|ml|pt|si|ta|zh)$",
        description="Supported language code (ISO 639-1)",
    )


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
    xp_awarded: int | None = None       # Populated only when check_complete=True
    remediation_needed: bool = False    # True when session moves to REMEDIATING phase
    attempt: int = 0                    # socratic_attempt_count at time of response
    locked: bool = False                # True would mean permanently locked (not used currently)
    best_score: int | None = None       # Best score across all attempts
    image: dict | None = None           # Exact card image if AI referenced one; None otherwise


class RemediationCardsResponse(BaseModel):
    cards: list[dict]
    session_phase: str


class RecheckResponse(BaseModel):
    response: str
    phase: str
    attempt: int


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

class CardMCQ(BaseModel):
    """Unified MCQ question — one per card in the new card schema."""
    text: str
    options: list[str] = Field(..., min_length=4, max_length=4)
    correct_index: int = Field(..., ge=0, le=3)
    explanation: str = ""
    difficulty: str = Field(default="MEDIUM", description="EASY | MEDIUM | HARD")


class LessonCard(BaseModel):
    """
    Unified card schema for the chunk-based architecture.
    question=None → content card; question set → MCQ card.
    chunk_id links this card back to its source ConceptChunk row.
    is_recovery=True indicates a re-explain card generated after wrong×2.
    """
    index:       int
    title:       str
    content:     str = Field(..., description="Markdown content for this card")
    image_url:   str | None = None
    caption:     str | None = None
    question:    CardMCQ | None = Field(default=None, description="MCQ question; None for content cards")
    chunk_id:    str = ""
    is_recovery: bool = False


class CardsResponse(BaseModel):
    session_id: UUID
    concept_id: str
    concept_title: str
    style: str
    phase: str
    cards: list[LessonCard]
    total_questions: int = 0  # Retained for backward compat; no longer a meaningful count
    has_more_concepts: bool = False           # True when concepts_queue is non-empty
    concepts_total: int = 0                   # Total sub-sections in this concept
    concepts_covered_count: int = 0           # How many covered so far (including this batch)
    cache_version: int = 0                    # Internal generation version for staleness detection


class NextSectionCardsRequest(BaseModel):
    """Live signals from the current session — used for real-time mode blending."""
    card_index: int = 0
    time_on_card_sec: float = 0.0
    wrong_attempts: int = 0
    hints_used: int = 0
    idle_triggers: int = 0


class NextSectionCardsResponse(BaseModel):
    session_id: UUID
    cards: list[LessonCard]
    has_more_concepts: bool
    concepts_total: int
    concepts_covered_count: int
    current_mode: str    # "SLOW" | "NORMAL" | "FAST"
    learning_profile_summary: dict | None = None


class UpdateSessionInterestsRequest(BaseModel):
    interests: list[str] = Field(
        default_factory=list,
        description="Per-session interest override (empty = use student profile interests)"
    )


class RegenerateMCQRequest(BaseModel):
    """Request body for generating a replacement MCQ after a wrong answer."""
    card_content: str = Field(..., description="The card's markdown content (context for LLM)")
    card_title: str
    concept_id: str
    previous_question: str = Field(..., description="The question text just answered wrong — must not reuse")
    language: str = "en"


class RegenerateMCQResponse(BaseModel):
    question: CardMCQ


class CompleteCardRequest(BaseModel):
    card_index: int
    time_on_card_sec: float = 0.0
    wrong_attempts: int = 0
    selected_wrong_option: int | None = None
    hints_used: int = 0
    idle_triggers: int = 0
    difficulty_bias: str | None = None
    re_explain_card_title: str | None = None  # set by frontend when wrong_attempts >= 2
    wrong_question: str | None = None        # The MCQ question text the student got wrong
    wrong_answer_text: str | None = None     # The exact text of the wrong answer chosen


class CompleteCardResponse(BaseModel):
    recovery_card: LessonCard | None = None
    learning_profile_summary: dict | None = None
    motivational_note: str | None = None
    adaptation_applied: str | None = None


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


# ── Analytics Schemas ─────────────────────────────────────────────────────────

class MasteryEvent(BaseModel):
    concept_id: str
    mastered_at: str


class StudentAnalyticsResponse(BaseModel):
    student_id: str
    display_name: str
    xp: int
    streak: int
    total_concepts_mastered: int
    total_concepts_attempted: int
    mastery_rate: float
    mastery_timeline: list[MasteryEvent]
    avg_check_score: float | None
    total_socratic_sessions: int
    avg_wrong_attempts_per_card: float
    avg_hints_per_card: float
    avg_time_on_card_sec: float
    reviews_due_now: int
    reviews_upcoming_7d: int
    hardest_concept_id: str | None
    hardest_concept_wrong_attempts: int


# ── Concept Readiness Schemas ─────────────────────────────────────────────────

class UnmetPrerequisite(BaseModel):
    concept_id: str
    concept_title: str


class ConceptReadinessResponse(BaseModel):
    concept_id: str
    all_prerequisites_met: bool
    unmet_prerequisites: list[UnmetPrerequisite]


# ── Section Completion Schemas ─────────────────────────────────────────────────

class SectionCompleteRequest(BaseModel):
    concept_id: str
    state_score: float = 2.0  # numeric state score for this section (1.0-3.0)


class SectionCompleteResponse(BaseModel):
    section_count: int
    avg_state_score: float
    state_distribution: dict


# ── Per-Card Adaptive Generation Schemas ──────────────────────────────────────

class NextCardRequest(BaseModel):
    """Live signals from the card the student just completed — used to adapt the next card."""
    card_index: int = Field(default=0, ge=0, description="0-based index of the card just completed")
    time_on_card_sec: float = Field(default=0.0, ge=0.0, description="Seconds spent on the completed card")
    wrong_attempts: int = Field(default=0, ge=0, description="Wrong MCQ attempts on the completed card")
    hints_used: int = Field(default=0, ge=0, description="Hints used on the completed card")
    idle_triggers: int = Field(default=0, ge=0, description="Idle assistant triggers on the completed card")


class NextCardResponse(BaseModel):
    """Response from POST /sessions/{id}/next-card — single per-card adaptive generation."""
    session_id: UUID
    card: LessonCard | None = None       # None when has_more_concepts=False
    has_more_concepts: bool
    current_mode: str                    # "STRUGGLING" | "NORMAL" | "FAST"
    concepts_covered_count: int
    concepts_total: int


# ── Chunk-Based Card Generation Schemas ───────────────────────────────────────

class ChunkCardsRequest(BaseModel):
    chunk_id: str  # UUID of the ConceptChunk to generate cards for


class ChunkCardsResponse(BaseModel):
    cards: list[LessonCard]
    chunk_id: str
    chunk_index: int
    total_chunks: int
    is_last_chunk: bool


class RecoveryCardRequest(BaseModel):
    chunk_id: str
    card_index: int = 0         # the card that triggered recovery
    wrong_answers: list[str] = []  # what the student answered incorrectly


class SocraticExamStartRequest(BaseModel):
    session_id: str   # UUID


class SocraticExamAnswer(BaseModel):
    question_index: int
    answer: str


class SocraticExamResult(BaseModel):
    score: float          # 0.0 – 1.0
    passed: bool
    total_questions: int
    correct_count: int
    failed_chunk_ids: list[str]
    attempt: int
