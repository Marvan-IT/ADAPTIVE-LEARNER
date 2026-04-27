"""
Pydantic schemas for the Week 2 Teaching endpoints.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


# ── Request Schemas ───────────────────────────────────────────────

class CreateStudentRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)
    age: int | None = Field(default=None, ge=5, le=120)
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


class StudentResponseRequest(BaseModel):
    message: str = Field(
        ..., min_length=1, max_length=2000, description="Student's response text"
    )
    engagement_signal: str | None = None
    strategy_applied: str | None = None


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
    age: int | None = None
    interests: list[str]
    custom_interests: list[str] = []
    preferred_style: str
    preferred_language: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ValidateCustomInterestRequest(BaseModel):
    text: str
    language: str | None = None


class ValidateCustomInterestResponse(BaseModel):
    ok: bool
    reason: str | None = None
    normalized: str


class StudentLanguageResponse(StudentResponse):
    """Extended response from PATCH /students/{id}/language — includes translation side-effects."""
    translated_headings: list[str] = Field(default_factory=list)
    session_cache_cleared: bool = False


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
    book_title: str = ""
    presentation: str
    style: str
    phase: str
    images: list[dict] = Field(default_factory=list, description="Extracted textbook images")
    latex_expressions: list[str] = Field(default_factory=list, description="Key LaTeX formulas")


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
    book_title: str = ""
    style: str
    phase: str
    cards: list[LessonCard]
    total_questions: int = 0  # Retained for backward compat; no longer a meaningful count
    has_more_concepts: bool = False           # True when concepts_queue is non-empty
    concepts_total: int = 0                   # Total sub-sections in this concept
    concepts_covered_count: int = 0           # How many covered so far (including this batch)
    cache_version: int = 0                    # Internal generation version for staleness detection


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
    new_badges: list = Field(default_factory=list)
    xp_awarded: dict | None = None


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
    total_study_time_sec: float
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


# ── Chunk-Based Card Generation Schemas ───────────────────────────────────────

class ChunkCardsRequest(BaseModel):
    chunk_id: str  # UUID of the ConceptChunk to generate cards for


class ChunkExamQuestion(BaseModel):
    index: int
    text: str
    chunk_id: str


class ChunkCardsResponse(BaseModel):
    cards: list[LessonCard]
    chunk_id: str
    chunk_index: int
    total_chunks: int
    is_last_chunk: bool
    questions: list["ChunkExamQuestion"] = []


class ChunkAnswerItem(BaseModel):
    index: int
    answer_text: str


class ChunkEvaluateRequest(BaseModel):
    questions: list[dict]
    answers: list[ChunkAnswerItem]
    mode_used: str = "NORMAL"
    mcq_correct: int = 0   # MCQ correct count from card phase
    mcq_total: int = 0     # total MCQs attempted during cards


class ChunkEvaluateFeedback(BaseModel):
    index: int
    correct: bool
    feedback: str


class ChunkEvaluateResponse(BaseModel):
    passed: bool
    score: float
    all_study_complete: bool
    chunk_progress: dict
    feedback: list[ChunkEvaluateFeedback]
    next_mode: str = "NORMAL"
    new_badges: list = Field(default_factory=list)
    xp_awarded: dict | None = None


class CompleteChunkRequest(BaseModel):
    chunk_id:  str  # UUID of completed study chunk (NOT exam/exercise_gate chunks)
    correct:   int  # MCQs answered correctly on this chunk
    total:     int  # Total MCQs attempted on this chunk
    mode_used: str  # STRUGGLING / NORMAL / FAST


class CompleteChunkResponse(BaseModel):
    chunk_id:           str
    score:              int        # 0–100 percentage
    next_mode:          str        # mode for next chunk generation
    next_chunk_id:      str | None # UUID of next teaching chunk; None if all done
    all_study_complete: bool       # True when all teaching chunks completed → unlock EXAM
    passed:             bool | None = None  # whether this chunk is considered passed


class RecoveryCardRequest(BaseModel):
    chunk_id: str
    card_index: int = 0         # the card that triggered recovery
    wrong_answers: list[str] = []  # what the student answered incorrectly
    is_exercise: bool = False


# ── Chunk List Schemas ─────────────────────────────────────────────────────────

class ChunkSummary(BaseModel):
    """Summary of a single ConceptChunk for the chunk progress indicator."""
    chunk_id:    str         # UUID string
    order_index: int         # absolute textbook position (sort key)
    heading:     str         # e.g. "Use Addition Notation"
    has_images:  bool        # True if at least one chunk_images row exists
    has_mcq:     bool        # determined by heading rule (no MCQ for Learning Objectives etc.)
    chunk_type:  str = "teaching"  # "teaching"|"exercise"|"chapter_review"|"learning_objective"
    is_optional:   bool = False       # True only for "Writing Exercises"
    exam_disabled: bool = False       # True when admin has disabled exam questions for this chunk
    completed:     bool = False
    score:       int | None = None
    mode_used:   str | None = None
    passed:      bool | None = None  # None = not yet attempted; True/False after completion


class ChunkListResponse(BaseModel):
    """
    Response for GET /sessions/{id}/chunks.
    Empty chunks list signals ChromaDB-path session — frontend falls back to legacy card flow.
    """
    concept_id:          str
    section_title:       str
    chunks:              list[ChunkSummary]
    current_chunk_index: int   # value of teaching_sessions.chunk_index
    translated:          bool = False  # True when headings were just translated on language change


class CompleteChunkItemResponse(BaseModel):
    chunk_id:           str
    next_chunk_id:      str | None  # None if this was the last study chunk
    all_study_complete: bool        # True → unlock exam gate


# ── Chunks Preview Schemas ─────────────────────────────────────────────────────

class ChunkPreviewItem(BaseModel):
    heading: str
    chunk_type: str = "teaching"
    has_images: bool = False
    has_mcq: bool = True
    is_optional: bool = False
    exam_disabled: bool = False
    order_index: int


class ChunkPreviewResponse(BaseModel):
    concept_id: str
    chunks: list[ChunkPreviewItem]


