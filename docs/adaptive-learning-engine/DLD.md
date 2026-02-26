# Detailed Low-Level Design: Adaptive Learning Generation Engine

**Feature slug:** `adaptive-learning-engine`
**Version:** 1.0.0
**Date:** 2026-02-25
**Author:** Solution Architect Agent

---

## 1. Component Breakdown

All new files live under `backend/src/adaptive/`. Existing files that must be modified are called out explicitly.

### 1.1 `backend/src/adaptive/__init__.py`
Empty init file. Marks the directory as a Python package. No content required.

---

### 1.2 `backend/src/adaptive/schemas.py`
**Responsibility:** Defines all Pydantic v2 models for request, intermediate, and response objects.

**Exports:**
- `AnalyticsSummary` — raw behavioral signals from the client
- `LearningProfile` — deterministic classification result
- `GenerationProfile` — LLM generation control parameters
- `LessonCard` — a single micro-card in the adaptive lesson
- `LessonBody` — explanation + card list
- `RemediationInfo` — metadata about injected remediation
- `AdaptiveLesson` — the top-level API response
- `AdaptiveLessonRequest` — the API request body

---

### 1.3 `backend/src/adaptive/profile_builder.py`
**Responsibility:** Pure-function classification of `AnalyticsSummary` → `LearningProfile`.

**Function signatures:**
```python
def classify_speed(
    time_spent_sec: int,
    expected_time_sec: int,
    attempts: int,
) -> str:
    """Returns 'SLOW' | 'NORMAL' | 'FAST'."""

def classify_comprehension(
    error_rate: float,
    quiz_score: float,
    hints_used: int,
) -> str:
    """Returns 'STRUGGLING' | 'OK' | 'STRONG'."""

def classify_engagement(
    skip_rate: float,
    hints_used: int,
    revisits: int,
) -> str:
    """Returns 'BORED' | 'ENGAGED' | 'OVERWHELMED'."""

def compute_confidence_score(
    quiz_score: float,
    error_rate: float,
    hints_used: int,
) -> float:
    """Returns float in [0.0, 1.0]."""

def determine_next_step(
    comprehension: str,
    engagement: str,
    speed: str,
) -> str:
    """Returns 'CONTINUE' | 'REMEDIATE_PREREQ' | 'ADD_PRACTICE' | 'CHALLENGE'."""

def build_learning_profile(summary: AnalyticsSummary) -> LearningProfile:
    """Orchestrates all sub-classifiers and returns a LearningProfile."""
```

No I/O. No side effects. All functions are pure and synchronous.

---

### 1.4 `backend/src/adaptive/generation_profile.py`
**Responsibility:** Pure-function mapping of `LearningProfile` → `GenerationProfile`.

**Function signatures:**
```python
def build_generation_profile(profile: LearningProfile) -> GenerationProfile:
    """
    Derives all LLM generation parameters from the learning profile.
    Pure function — no I/O, no side effects.
    """
```

Internally uses a lookup table of `(speed, comprehension)` base settings, then applies engagement modifier adjustments.

---

### 1.5 `backend/src/adaptive/remediation.py`
**Responsibility:** Determines whether remediation cards should be prepended and which prerequisite concept to use. Performs one DB read and one graph traversal.

**Function signatures:**
```python
async def resolve_remediation(
    student_id: uuid.UUID,
    concept_id: str,
    comprehension: str,
    graph: nx.DiGraph,
    db: AsyncSession,
) -> RemediationCandidate:
    """
    If comprehension == 'STRUGGLING', finds the first direct prerequisite
    that is not mastered by the student, by checking student_mastery table.
    Returns RemediationCandidate with prereq_concept_id or None.
    """

async def build_remediation_cards(
    prereq_concept_id: str,
    knowledge_svc: KnowledgeService,
) -> list[LessonCard]:
    """
    Retrieves the prerequisite concept text from KnowledgeService
    and returns 3 [Review] LessonCard objects (difficulty 1-2).
    These are built without an LLM call (template-based for v1).
    """
```

`RemediationCandidate` is a simple dataclass (not a Pydantic model since it is internal):
```python
@dataclass
class RemediationCandidate:
    should_remediate: bool
    prereq_concept_id: str | None
    prereq_title: str | None
```

---

### 1.6 `backend/src/adaptive/prompt_builder.py`
**Responsibility:** Assembles the system prompt and user prompt for the adaptive lesson LLM call.

**Function signatures:**
```python
def build_adaptive_system_prompt(
    generation_profile: GenerationProfile,
    language: str,
) -> str:
    """
    Returns the system prompt string encoding all GenerationProfile parameters.
    Uses the language code to instruct the LLM on output language.
    """

def build_adaptive_user_prompt(
    concept_title: str,
    concept_text: str,
    generation_profile: GenerationProfile,
    remediation_prereq_title: str | None,
) -> str:
    """
    Returns the user prompt string with concept content and generation instructions.
    Truncates concept_text to ADAPTIVE_MAX_CONCEPT_TEXT_CHARS if needed.
    """
```

Both functions are pure (no I/O, no side effects). They are kept separate from `api/prompts.py` to avoid coupling the adaptive module to the teaching module's prompt conventions.

---

### 1.7 `backend/src/adaptive/adaptive_engine.py`
**Responsibility:** Orchestrates the full adaptive lesson generation pipeline.

**Class and function signatures:**
```python
class AdaptiveEngine:
    def __init__(
        self,
        knowledge_svc: KnowledgeService,
        openai_client: AsyncOpenAI,
        model: str,
    ):
        ...

    async def generate_lesson(
        self,
        request: AdaptiveLessonRequest,
        db: AsyncSession,
    ) -> AdaptiveLesson:
        """
        Orchestration steps (a through h):
        a. Build LearningProfile from request.analytics_summary.
        b. Build GenerationProfile from LearningProfile.
        c. Fetch concept detail from KnowledgeService.
        d. Fetch student's preferred_language from DB.
        e. Resolve remediation (DB + graph) if STRUGGLING.
        f. Build remediation cards (template-based, no LLM).
        g. Build system + user prompt from GenerationProfile + concept.
        h. Call OpenAI (with retry) → parse → validate against AdaptiveLesson schema.
        i. Prepend remediation cards to lesson.cards if applicable.
        j. Return validated AdaptiveLesson.
        """

    async def _call_llm_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        max_retries: int = 3,
    ) -> dict:
        """
        Calls OpenAI and returns parsed JSON dict.
        Applies exponential back-off (2s, 4s) and JSON salvage on failure.
        Raises ValueError after max_retries exhausted.
        """
```

---

### 1.8 `backend/src/adaptive/adaptive_router.py`
**Responsibility:** FastAPI router that wires the HTTP endpoint to `AdaptiveEngine.generate_lesson()`.

**Exports:**
- `router: APIRouter` — registered with prefix `/api/v3`

**Endpoint:**
```
POST /api/v3/adaptive/lesson
```

The router receives the `AdaptiveEngine` instance via module-level assignment at startup (same pattern as `teaching_router_module.teaching_svc`).

---

### 1.9 Modifications to Existing Files

#### `backend/src/api/main.py`
- Import `adaptive_router` from `adaptive.adaptive_router`.
- Import `AdaptiveEngine` from `adaptive.adaptive_engine`.
- In the `lifespan()` context manager, instantiate `AdaptiveEngine` after `KnowledgeService` and `TeachingService` are initialized.
- Register the adaptive router: `app.include_router(adaptive_router_module.router)`.
- Store the engine reference on the router module: `adaptive_router_module.adaptive_engine = AdaptiveEngine(knowledge_svc, openai_client, OPENAI_MODEL)`.

#### `backend/src/config.py`
Add two constants (no other changes):
```python
# ── Adaptive Learning Engine ───────────────────────────────────────
ADAPTIVE_MAX_CONCEPT_TEXT_CHARS: int = 1200
ADAPTIVE_LLM_MAX_TOKENS: int = 2800
```

#### `backend/requirements.txt`
Add if not already present:
```
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

---

## 2. Data Design

### 2.1 Pydantic Schema Definitions

```python
# backend/src/adaptive/schemas.py

from __future__ import annotations
from enum import Enum
from typing import Optional
import uuid
from pydantic import BaseModel, Field, field_validator


# ── Enums ─────────────────────────────────────────────────────────

class SpeedLabel(str, Enum):
    SLOW = "SLOW"
    NORMAL = "NORMAL"
    FAST = "FAST"

class ComprehensionLabel(str, Enum):
    STRUGGLING = "STRUGGLING"
    OK = "OK"
    STRONG = "STRONG"

class EngagementLabel(str, Enum):
    BORED = "BORED"
    ENGAGED = "ENGAGED"
    OVERWHELMED = "OVERWHELMED"

class NextStepLabel(str, Enum):
    CONTINUE = "CONTINUE"
    REMEDIATE_PREREQ = "REMEDIATE_PREREQ"
    ADD_PRACTICE = "ADD_PRACTICE"
    CHALLENGE = "CHALLENGE"

class ExplanationDepth(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

class ReadingLevel(str, Enum):
    KID_SIMPLE = "KID_SIMPLE"
    SIMPLE = "SIMPLE"
    STANDARD = "STANDARD"

class EmojiPolicy(str, Enum):
    NONE = "NONE"
    SPARING = "SPARING"

class CardType(str, Enum):
    EXPLAIN = "explain"
    EXAMPLE = "example"
    MCQ = "mcq"
    SHORT_ANSWER = "short_answer"
    PRACTICE = "practice"
    CHECKPOINT = "checkpoint"


# ── Input ─────────────────────────────────────────────────────────

class AnalyticsSummary(BaseModel):
    student_id: str                        # UUID string (validated in engine)
    concept_id: str
    time_spent_sec: int = Field(ge=0)
    expected_time_sec: int = Field(ge=1)
    attempts: int = Field(ge=0)
    wrong_attempts: int = Field(ge=0)
    hints_used: int = Field(ge=0)
    revisits: int = Field(ge=0)
    recent_dropoffs: int = Field(ge=0)
    skip_rate: float = Field(ge=0.0, le=1.0)
    quiz_score: float = Field(ge=0.0, le=1.0)
    last_7d_sessions: int = Field(ge=0)

    @field_validator("wrong_attempts")
    @classmethod
    def wrong_le_attempts(cls, v: int, info) -> int:
        attempts = info.data.get("attempts", 0)
        if v > attempts:
            raise ValueError("wrong_attempts cannot exceed attempts")
        return v


class AdaptiveLessonRequest(BaseModel):
    student_id: str
    concept_id: str
    analytics_summary: AnalyticsSummary


# ── Intermediate ───────────────────────────────────────────────────

class LearningProfile(BaseModel):
    speed: SpeedLabel
    comprehension: ComprehensionLabel
    engagement: EngagementLabel
    confidence_score: float = Field(ge=0.0, le=1.0)
    recommended_next_step: NextStepLabel
    # Derived fields for transparency
    error_rate: float = Field(ge=0.0, le=1.0)


class GenerationProfile(BaseModel):
    explanation_depth: ExplanationDepth
    reading_level: ReadingLevel
    step_by_step: bool
    analogy_level: float = Field(ge=0.0, le=1.0)
    fun_level: float = Field(ge=0.0, le=1.0)
    card_count: int = Field(ge=7, le=14)
    practice_count: int = Field(ge=3, le=8)
    checkpoint_frequency: int = Field(ge=2, le=5)
    max_paragraph_lines: int = Field(ge=2, le=5)
    emoji_policy: EmojiPolicy


# ── Output ────────────────────────────────────────────────────────

class LessonCard(BaseModel):
    type: CardType
    title: str
    content: str                           # Markdown
    answer: Optional[str] = None
    hints: list[str] = Field(default_factory=list)
    difficulty: int = Field(ge=1, le=5)
    fun_element: Optional[str] = None     # Only present when fun_level > 0.5


class LessonBody(BaseModel):
    concept_explanation: str               # Markdown
    cards: list[LessonCard]


class RemediationInfo(BaseModel):
    included: bool
    prereq_concept_id: Optional[str] = None
    prereq_title: Optional[str] = None


class AdaptiveLesson(BaseModel):
    student_id: str
    concept_id: str
    learning_profile: LearningProfile
    generation_profile: GenerationProfile
    lesson: LessonBody
    remediation: RemediationInfo
```

### 2.2 Database Access

No new tables are required. The engine reads from the existing `student_mastery` table using the existing `StudentMastery` ORM model.

**Query pattern in `remediation.py`:**
```python
from sqlalchemy import select
from db.models import StudentMastery

result = await db.execute(
    select(StudentMastery.concept_id)
    .where(StudentMastery.student_id == student_id)
    .where(StudentMastery.concept_id.in_(direct_prereq_ids))
)
mastered_prereq_ids = {row[0] for row in result.all()}
```

**Query pattern for student language in `adaptive_engine.py`:**
```python
from db.models import Student

student = await db.get(Student, student_id_as_uuid)
if student is None:
    raise HTTPException(status_code=404, detail=f"Student not found: {student_id}")
language = student.preferred_language or "en"
```

### 2.3 Data Flow Diagram

```
AdaptiveLessonRequest
       │
       ▼
[1] AnalyticsSummary ──────────────────────────────────────────────▶ LearningProfile
                                                                          │
                                                                          ▼
                                                                    GenerationProfile
                                                                          │
       │                                                                  │
       ▼                                                                  │
[2] DB: Student.preferred_language ──────────────────────────────────────▶ language: str
       │
       ▼
[3] DB: student_mastery WHERE student_id AND concept_id IN (prereqs)
       │                   ───────────────────────────────────────────▶ mastered_prereq_ids: set
       │
       ▼
[4] NetworkX: graph.predecessors(concept_id)
       │                   ───────────────────────────────────────────▶ direct_prereq_ids: list
       │
       ▼
[5] KnowledgeService.get_concept_detail(concept_id)
       │                   ───────────────────────────────────────────▶ concept_text: str
       │
       ▼
[6] prompt_builder (GenerationProfile + concept_text + language)
       │                   ───────────────────────────────────────────▶ system_prompt, user_prompt
       │
       ▼
[7] OpenAI gpt-4o (system_prompt + user_prompt)
       │                   ───────────────────────────────────────────▶ raw_json: str
       │
       ▼
[8] JSON parse + Pydantic validation
       │                   ───────────────────────────────────────────▶ LessonBody
       │
       ▼
[9] Prepend remediation cards (if STRUGGLING + unmastered prereq)
       │
       ▼
AdaptiveLesson (returned to caller)
```

### 2.4 Caching Strategy

No application-level caching in v1. The OpenAI client handles HTTP-level keep-alive connection pooling. The `KnowledgeService` (ChromaDB + graph) is loaded once at startup and held in process memory — this is the primary performance optimization.

### 2.5 Data Retention

Generated `AdaptiveLesson` responses are transient (not stored). No new retention policy is required. The existing `student_mastery` table retention policy applies unchanged.

---

## 3. LearningProfile Classification Algorithm

### 3.1 Derived Metrics

```python
error_rate: float = wrong_attempts / attempts  if attempts > 0  else 0.0
hint_penalty: float = min(hints_used * 0.05, 0.3)   # cap at 0.30
```

### 3.2 Speed Classification

Evaluated in this order:

```
IF time_spent_sec > expected_time_sec * 1.5:
    speed = SLOW
ELIF time_spent_sec < expected_time_sec * 0.7 AND attempts <= 1:
    speed = FAST
ELSE:
    speed = NORMAL
```

**Brute-force guard:** `attempts <= 1` in the FAST branch prevents classifying a student as FAST if they made multiple attempts (e.g., guessing rapidly). A student who spent 300s on a 450s concept but took 4 attempts is NORMAL, not FAST.

### 3.3 Comprehension Classification

Evaluated in this order:

```
IF error_rate >= 0.5 OR quiz_score < 0.5:
    comprehension = STRUGGLING
ELIF quiz_score >= 0.8 AND error_rate <= 0.2 AND hints_used <= 2:
    comprehension = STRONG
ELSE:
    comprehension = OK
```

**Note:** The STRUGGLING check runs first. A student with quiz_score=0.85 but error_rate=0.6 is STRUGGLING (high errors override good quiz score).

### 3.4 Engagement Classification

Evaluated in this order:

```
IF skip_rate > 0.35:
    engagement = BORED
ELIF hints_used >= 5 AND revisits >= 2:
    engagement = OVERWHELMED
ELSE:
    engagement = ENGAGED
```

**Note:** BORED is checked first. A student who skips frequently and also uses many hints is classified as BORED (they may be bored and skipping to find the answer), not OVERWHELMED.

### 3.5 Confidence Score

```python
confidence_score = max(
    0.0,
    min(
        1.0,
        quiz_score * 0.6
        + (1.0 - error_rate) * 0.3
        - hint_penalty * 0.1
    )
)
```

Weights: quiz performance dominates (60%), error-free attempts contribute (30%), hints subtract minimally (10% of hint_penalty). The result is clamped to [0.0, 1.0].

### 3.6 Recommended Next Step

```
IF comprehension == STRUGGLING AND engagement == OVERWHELMED:
    next_step = REMEDIATE_PREREQ
ELIF comprehension == STRONG AND speed == FAST:
    next_step = CHALLENGE
ELIF comprehension == OK AND engagement == BORED:
    next_step = ADD_PRACTICE
ELSE:
    next_step = CONTINUE
```

---

## 4. GenerationProfile Mapping Table

### 4.1 Base Mapping (Speed × Comprehension)

| Speed  | Comprehension | depth | reading_level | step_by_step | analogy_level | fun_level | card_count | practice_count | checkpoint_freq | max_para_lines | emoji_policy |
|--------|---------------|-------|---------------|-------------|---------------|-----------|------------|----------------|-----------------|----------------|--------------|
| SLOW   | STRUGGLING    | HIGH  | KID_SIMPLE    | True        | 0.8           | 0.4       | 12         | 7              | 2               | 2              | SPARING      |
| SLOW   | OK            | HIGH  | SIMPLE        | True        | 0.6           | 0.3       | 11         | 6              | 2               | 3              | NONE         |
| SLOW   | STRONG        | MEDIUM| SIMPLE        | True        | 0.5           | 0.3       | 10         | 5              | 3               | 3              | NONE         |
| NORMAL | STRUGGLING    | HIGH  | SIMPLE        | True        | 0.7           | 0.3       | 11         | 6              | 2               | 3              | SPARING      |
| NORMAL | OK            | MEDIUM| STANDARD      | False       | 0.5           | 0.2       | 9          | 4              | 3               | 4              | NONE         |
| NORMAL | STRONG        | LOW   | STANDARD      | False       | 0.3           | 0.2       | 8          | 3              | 4               | 4              | NONE         |
| FAST   | STRUGGLING    | HIGH  | SIMPLE        | True        | 0.6           | 0.3       | 10         | 6              | 2               | 3              | NONE         |
| FAST   | OK            | LOW   | STANDARD      | False       | 0.3           | 0.2       | 8          | 3              | 4               | 5              | NONE         |
| FAST   | STRONG        | LOW   | STANDARD      | False       | 0.2           | 0.2       | 7          | 3              | 5               | 5              | NONE         |

### 4.2 Engagement Modifiers (applied after base mapping)

These modifiers are additive/overriding adjustments:

| Engagement  | Modification |
|-------------|-------------|
| BORED       | `fun_level += 0.3` (capped at 1.0); `emoji_policy = SPARING`; `card_count -= 1` (min 7) |
| OVERWHELMED | `card_count -= 3` (min 7); `practice_count -= 1` (min 3); `step_by_step = True`; `analogy_level += 0.2` (capped at 1.0) |
| ENGAGED     | No modification |

**Application order:** Start with base mapping values, then apply engagement modifier.

### 4.3 Python Implementation Pattern

```python
# generation_profile.py

BASE_PROFILES: dict[tuple[str, str], dict] = {
    ("SLOW", "STRUGGLING"): {
        "explanation_depth": "HIGH",
        "reading_level": "KID_SIMPLE",
        "step_by_step": True,
        "analogy_level": 0.8,
        "fun_level": 0.4,
        "card_count": 12,
        "practice_count": 7,
        "checkpoint_frequency": 2,
        "max_paragraph_lines": 2,
        "emoji_policy": "SPARING",
    },
    # ... all 9 combinations ...
}

def build_generation_profile(profile: LearningProfile) -> GenerationProfile:
    base = dict(BASE_PROFILES[(profile.speed.value, profile.comprehension.value)])
    # Apply engagement modifiers
    if profile.engagement == EngagementLabel.BORED:
        base["fun_level"] = min(1.0, base["fun_level"] + 0.3)
        base["emoji_policy"] = "SPARING"
        base["card_count"] = max(7, base["card_count"] - 1)
    elif profile.engagement == EngagementLabel.OVERWHELMED:
        base["card_count"] = max(7, base["card_count"] - 3)
        base["practice_count"] = max(3, base["practice_count"] - 1)
        base["step_by_step"] = True
        base["analogy_level"] = min(1.0, base["analogy_level"] + 0.2)
    return GenerationProfile(**base)
```

---

## 5. Remediation Selection Algorithm

```
FUNCTION resolve_remediation(student_id, concept_id, comprehension, graph, db):
    IF comprehension != "STRUGGLING":
        RETURN RemediationCandidate(should_remediate=False, ...)

    # Get direct prerequisites (only immediate parents, not transitive)
    direct_prereqs = list(graph.predecessors(concept_id))
    IF len(direct_prereqs) == 0:
        RETURN RemediationCandidate(should_remediate=False, ...)

    # Check which prereqs are mastered in DB
    mastered_ids = query student_mastery WHERE student_id AND concept_id IN direct_prereqs

    # Find first unmastered prereq (preserves graph insertion order for determinism)
    FOR prereq_id IN direct_prereqs:
        IF prereq_id NOT IN mastered_ids:
            prereq_title = graph.nodes[prereq_id].get("title", prereq_id)
            RETURN RemediationCandidate(
                should_remediate=True,
                prereq_concept_id=prereq_id,
                prereq_title=prereq_title
            )

    # All prereqs mastered → no remediation needed despite STRUGGLING status
    RETURN RemediationCandidate(should_remediate=False, ...)
```

### Remediation Card Template

When remediation is triggered, `build_remediation_cards()` constructs exactly 3 `LessonCard` objects without an LLM call:

```
Card 1 (type=explain, difficulty=1):
  title: "[Review] Understanding {prereq_title}"
  content: "{prereq concept_text truncated to 400 chars}..."
  hints: []

Card 2 (type=example, difficulty=1):
  title: "[Review] Quick Example: {prereq_title}"
  content: "Before we continue, here is a key example from {prereq_title}:
            {first 200 chars of prereq concept_text example section if found, else generic text}"
  hints: ["Think about the core idea of {prereq_title}"]

Card 3 (type=checkpoint, difficulty=2):
  title: "[Review] Check: {prereq_title}"
  content: "Quick check: Can you recall the main idea from {prereq_title}?
            Write a one-sentence summary in your own words."
  answer: None
  hints: ["Focus on the definition, not formulas"]
```

---

## 6. API Design

### 6.1 Endpoint Specification

```
POST /api/v3/adaptive/lesson
```

**Authentication:** None for v1 (same as all existing `/api/v1` and `/api/v2` endpoints). Student identity is validated by UUID existence in DB.

**Request Content-Type:** `application/json`

**Request Body:**
```json
{
  "student_id": "550e8400-e29b-41d4-a716-446655440000",
  "concept_id": "PREALG.C4.S2.MULTIPLY_AND_DIVIDE_FRACTIONS",
  "analytics_summary": {
    "student_id": "550e8400-e29b-41d4-a716-446655440000",
    "concept_id": "PREALG.C4.S2.MULTIPLY_AND_DIVIDE_FRACTIONS",
    "time_spent_sec": 820,
    "expected_time_sec": 450,
    "attempts": 6,
    "wrong_attempts": 4,
    "hints_used": 7,
    "revisits": 3,
    "recent_dropoffs": 1,
    "skip_rate": 0.05,
    "quiz_score": 0.4,
    "last_7d_sessions": 2
  }
}
```

**Successful Response — HTTP 200:**
```json
{
  "student_id": "550e8400-e29b-41d4-a716-446655440000",
  "concept_id": "PREALG.C4.S2.MULTIPLY_AND_DIVIDE_FRACTIONS",
  "learning_profile": {
    "speed": "SLOW",
    "comprehension": "STRUGGLING",
    "engagement": "OVERWHELMED",
    "confidence_score": 0.26,
    "recommended_next_step": "REMEDIATE_PREREQ",
    "error_rate": 0.67
  },
  "generation_profile": {
    "explanation_depth": "HIGH",
    "reading_level": "KID_SIMPLE",
    "step_by_step": true,
    "analogy_level": 1.0,
    "fun_level": 0.4,
    "card_count": 9,
    "practice_count": 6,
    "checkpoint_frequency": 2,
    "max_paragraph_lines": 2,
    "emoji_policy": "SPARING"
  },
  "lesson": {
    "concept_explanation": "## Multiplying and Dividing Fractions\n\n...",
    "cards": [
      {
        "type": "explain",
        "title": "[Review] Understanding Fractions as Parts",
        "content": "...",
        "answer": null,
        "hints": [],
        "difficulty": 1,
        "fun_element": null
      },
      ...
    ]
  },
  "remediation": {
    "included": true,
    "prereq_concept_id": "PREALG.C3.S1.FRACTIONS_AS_PARTS",
    "prereq_title": "Fractions as Parts"
  }
}
```

**Error Responses:**

| HTTP Status | Condition | Response Body |
|-------------|-----------|---------------|
| 422 Unprocessable Entity | Pydantic validation failure (e.g., `wrong_attempts > attempts`) | Standard FastAPI validation error |
| 404 Not Found | `student_id` UUID not found in `students` table | `{"detail": "Student not found: <uuid>"}` |
| 404 Not Found | `concept_id` not found in KnowledgeService | `{"detail": "Concept not found: <concept_id>"}` |
| 502 Bad Gateway | LLM failed after 3 retries | `{"detail": "Lesson generation failed after 3 retries: <last_error>"}` |
| 500 Internal Server Error | Unexpected exception | `{"detail": "Internal server error"}` |

### 6.2 Versioning Strategy

The endpoint is under `/api/v3`. No versioning within the endpoint itself (field additions are backward-compatible; field removals require a new version prefix).

### 6.3 Error Handling Conventions

Consistent with the existing API: FastAPI `HTTPException` for 4xx errors. Unhandled exceptions propagate to FastAPI's default 500 handler. Structured logging at ERROR level before raising 502.

---

## 7. Sequence Diagrams

### 7.1 Happy Path — STRUGGLING Student with Unmastered Prerequisite

```
Frontend          adaptive_router       AdaptiveEngine       DB (AsyncSession)    KnowledgeService    OpenAI
    │                    │                     │                      │                   │              │
    │──POST /api/v3/──▶  │                     │                      │                   │              │
    │  adaptive/lesson   │                     │                      │                   │              │
    │                    │──generate_lesson()─▶│                      │                   │              │
    │                    │                     │──build_learning_profile()                │              │
    │                    │                     │  (pure, synchronous) │                   │              │
    │                    │                     │──build_generation_profile()              │              │
    │                    │                     │  (pure, synchronous) │                   │              │
    │                    │                     │──db.get(Student)────▶│                   │              │
    │                    │                     │◀─student.language────│                   │              │
    │                    │                     │──get_concept_detail()────────────────────▶              │
    │                    │                     │◀─concept text/title──────────────────────│              │
    │                    │                     │──resolve_remediation()                   │              │
    │                    │                     │  graph.predecessors()│                   │              │
    │                    │                     │──SELECT mastery──────▶│                  │              │
    │                    │                     │◀─mastered_ids─────────│                  │              │
    │                    │                     │  → first unmastered prereq found         │              │
    │                    │                     │──build_remediation_cards()               │              │
    │                    │                     │  get_concept_detail(prereq_id)──────────▶              │
    │                    │                     │◀─prereq text─────────────────────────────│              │
    │                    │                     │──build_adaptive_system_prompt()          │              │
    │                    │                     │──build_adaptive_user_prompt()            │              │
    │                    │                     │──chat.completions.create()───────────────────────────▶  │
    │                    │                     │◀─raw_json────────────────────────────────────────────── │
    │                    │                     │──json.loads() + Pydantic validate        │              │
    │                    │                     │──prepend 3 remediation cards             │              │
    │                    │                     │──return AdaptiveLesson                   │              │
    │                    │◀─AdaptiveLesson──── │                      │                   │              │
    │◀─HTTP 200 JSON─────│                     │                      │                   │              │
```

### 7.2 Error Path — LLM Returns Malformed JSON (Retry)

```
AdaptiveEngine                    OpenAI
    │                               │
    │──_call_llm_with_retry()       │
    │──chat.completions.create()───▶│
    │◀─truncated_json───────────────│
    │──json.loads() → JSONDecodeError
    │──_salvage_truncated_json()
    │  → salvage failed
    │──asyncio.sleep(2s)
    │──chat.completions.create()───▶│  [attempt 2]
    │◀─valid_json───────────────────│
    │──json.loads() → success
    │──return parsed dict
```

### 7.3 Error Path — Student Not Found

```
Frontend          adaptive_router       AdaptiveEngine       DB
    │                    │                     │              │
    │──POST /api/v3/──▶  │                     │              │
    │                    │──generate_lesson()─▶│              │
    │                    │                     │──db.get(Student)──▶│
    │                    │                     │◀─None──────────────│
    │                    │                     │──raise HTTPException(404)
    │                    │◀─HTTPException ─────│
    │◀─HTTP 404 ─────────│
```

---

## 8. Prompt Structure Specification

### 8.1 System Prompt Template

The system prompt encodes all `GenerationProfile` parameters as explicit behavioral instructions. It is assembled by `build_adaptive_system_prompt()`.

```
You are an expert math tutor generating an adaptive lesson for a student.

**Your generation parameters (MUST be followed exactly):**
- Explanation depth: {depth}         (LOW=concise; MEDIUM=moderate; HIGH=thorough with all sub-steps)
- Reading level: {reading_level}     (KID_SIMPLE=age 10 vocabulary; SIMPLE=middle-school; STANDARD=high-school)
- Step-by-step required: {step_by_step}
- Analogy density: {analogy_level}   (0.0=no analogies; 1.0=analogy for every concept)
- Fun level: {fun_level}             (0.0=purely academic; 1.0=maximize real-world fun hooks)
- Cards to generate: {card_count}    (generate EXACTLY this many cards total)
- Practice card count: {practice_count}  (include EXACTLY this many practice-type cards)
- Checkpoint every {checkpoint_frequency} cards (insert a checkpoint card at this interval)
- Max paragraph lines: {max_paragraph_lines} (no explanation paragraph may exceed this line count)
- Emoji policy: {emoji_policy}       (NONE=no emojis anywhere; SPARING=at most 1 per card, in fun_element only)

**Output language:** {language_name} (ALL lesson content must be in this language)

**Output format:** Respond with ONLY valid JSON matching this exact schema (no markdown, no prose):
{
  "concept_explanation": "<markdown string>",
  "cards": [
    {
      "type": "<explain|example|mcq|short_answer|practice|checkpoint>",
      "title": "<string>",
      "content": "<markdown>",
      "answer": "<string or null>",
      "hints": ["<string>", ...],
      "difficulty": <1-5>,
      "fun_element": "<string or null>"
    }
  ]
}
```

### 8.2 User Prompt Template

```
**Concept to teach:** {concept_title}

**Source material (use as the factual basis for your explanation and cards):**
{concept_text_truncated_to_1200_chars}

{remediation_context_block if prereq_title is not None else ""}

Generate the adaptive lesson now. Remember: EXACTLY {card_count} cards total,
{practice_count} of type "practice", checkpoint every {checkpoint_frequency} cards.
```

**Remediation context block (injected only when prereq_title is not None):**
```
**Prerequisite context:** The student has not yet mastered "{prereq_title}".
The first {card_count - 3} content cards should gently reinforce foundational ideas
before building to the full concept.
```

---

## 9. Engine Orchestration Steps (adaptive_engine.py)

```python
async def generate_lesson(self, request: AdaptiveLessonRequest, db: AsyncSession) -> AdaptiveLesson:
    # Step a: Build LearningProfile (pure, synchronous)
    learning_profile = build_learning_profile(request.analytics_summary)

    # Step b: Build GenerationProfile (pure, synchronous)
    generation_profile = build_generation_profile(learning_profile)

    # Step c: Validate student exists and fetch language preference
    try:
        student_uuid = uuid.UUID(request.student_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="student_id must be a valid UUID")
    student = await db.get(Student, student_uuid)
    if student is None:
        raise HTTPException(status_code=404, detail=f"Student not found: {request.student_id}")
    language = student.preferred_language or "en"

    # Step d: Retrieve concept knowledge from KnowledgeService
    concept = self.knowledge_svc.get_concept_detail(request.concept_id)
    if concept is None:
        raise HTTPException(status_code=404, detail=f"Concept not found: {request.concept_id}")

    # Step e: Resolve remediation (DB + graph traversal)
    remediation_candidate = await resolve_remediation(
        student_id=student_uuid,
        concept_id=request.concept_id,
        comprehension=learning_profile.comprehension.value,
        graph=self.knowledge_svc.graph,
        db=db,
    )

    # Step f: Build remediation cards (template-based, no LLM call)
    remediation_cards: list[LessonCard] = []
    if remediation_candidate.should_remediate:
        remediation_cards = await build_remediation_cards(
            prereq_concept_id=remediation_candidate.prereq_concept_id,
            knowledge_svc=self.knowledge_svc,
        )

    # Step g: Build LLM prompts
    system_prompt = build_adaptive_system_prompt(generation_profile, language)
    user_prompt = build_adaptive_user_prompt(
        concept_title=concept["concept_title"],
        concept_text=concept["text"],
        generation_profile=generation_profile,
        remediation_prereq_title=remediation_candidate.prereq_title,
    )

    # Step h: Call LLM with retry, parse, validate
    raw_lesson_dict = await self._call_llm_with_retry(system_prompt, user_prompt)
    lesson_body = LessonBody(**raw_lesson_dict)   # Pydantic validation

    # Step i: Prepend remediation cards
    all_cards = remediation_cards + lesson_body.cards

    # Step j: Assemble and return AdaptiveLesson
    return AdaptiveLesson(
        student_id=request.student_id,
        concept_id=request.concept_id,
        learning_profile=learning_profile,
        generation_profile=generation_profile,
        lesson=LessonBody(
            concept_explanation=lesson_body.concept_explanation,
            cards=all_cards,
        ),
        remediation=RemediationInfo(
            included=remediation_candidate.should_remediate,
            prereq_concept_id=remediation_candidate.prereq_concept_id,
            prereq_title=remediation_candidate.prereq_title,
        ),
    )
```

---

## 10. Integration Design

### 10.1 KnowledgeService Integration
- The `AdaptiveEngine` receives a `KnowledgeService` reference in its constructor.
- It calls `knowledge_svc.get_concept_detail(concept_id)` (sync method, returns `dict | None`).
- It accesses `knowledge_svc.graph` (NetworkX `DiGraph`) directly for `graph.predecessors(concept_id)`.
- No modifications to `KnowledgeService` are required.

### 10.2 Database Integration
- The `AdaptiveEngine.generate_lesson()` receives a `db: AsyncSession` from the FastAPI dependency injector (`get_db()`).
- Two queries are made: `db.get(Student, uuid)` and a `SELECT` on `student_mastery`.
- Both are read-only (no writes from the adaptive engine).
- The session is managed by the router's dependency injection; the engine does not commit or close it.

### 10.3 OpenAI Integration
- Uses `AsyncOpenAI` client (same as `TeachingService`).
- Model: `OPENAI_MODEL` (gpt-4o) from `config.py`.
- Parameters: `temperature=0.7`, `max_tokens=ADAPTIVE_LLM_MAX_TOKENS` (2800).
- Response format: plain text JSON (not `response_format={"type": "json_object"}` to avoid OpenAI JSON mode limitations with long outputs).
- Retry: 3 attempts, `asyncio.sleep(2 * attempt)` back-off.

### 10.4 FastAPI Router Wiring (`main.py`)

```python
# Add to imports
from adaptive.adaptive_router import router as adaptive_router
import adaptive.adaptive_router as adaptive_router_module
from adaptive.adaptive_engine import AdaptiveEngine

# Add to lifespan(), after knowledge_svc is initialized:
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
adaptive_engine_instance = AdaptiveEngine(knowledge_svc, openai_client, OPENAI_MODEL)
adaptive_router_module.adaptive_engine = adaptive_engine_instance

# Add after existing include_router calls:
app.include_router(adaptive_router)
```

**Router definition in `adaptive_router.py`:**
```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from db.connection import get_db
from adaptive.schemas import AdaptiveLessonRequest, AdaptiveLesson
from adaptive.adaptive_engine import AdaptiveEngine

router = APIRouter(prefix="/api/v3", tags=["adaptive"])
adaptive_engine: AdaptiveEngine = None  # set at startup by main.py

@router.post("/adaptive/lesson", response_model=AdaptiveLesson)
async def generate_adaptive_lesson(
    request: AdaptiveLessonRequest,
    db: AsyncSession = Depends(get_db),
) -> AdaptiveLesson:
    return await adaptive_engine.generate_lesson(request, db)
```

---

## 11. Security Design

### Authentication and Authorization
- v1: No token-based authentication (matches existing API pattern). The endpoint is network-accessible to the same origin as the frontend.
- The `student_id` UUID is validated: (1) syntactically as a valid UUID, (2) existentially against the `students` table. An invalid or non-existent `student_id` returns HTTP 404 before any LLM call.

### Input Validation and Sanitization
- All inputs are validated by Pydantic v2 with explicit field constraints (`ge`, `le`, `field_validator`).
- The `wrong_attempts > attempts` cross-field validator prevents logically inconsistent inputs.
- `concept_text` retrieved from `KnowledgeService` is truncated to `ADAPTIVE_MAX_CONCEPT_TEXT_CHARS` before being inserted into the prompt (prevents prompt injection via database content).
- No user-supplied free text is ever inserted raw into an LLM prompt (the `analytics_summary` contains only numeric fields and IDs, not free text).

### Data Encryption
- In transit: HTTPS enforced at the reverse proxy layer (existing infrastructure).
- At rest: PostgreSQL data-at-rest encryption is an infrastructure concern handled by the devops-engineer.

### Secrets Management
- `OPENAI_API_KEY` is loaded from environment variables via `config.py` (existing pattern). The adaptive module does not introduce any new secrets.

---

## 12. Observability Design

### Logging

All log calls use `import logging; logger = logging.getLogger(__name__)`.

```python
# In adaptive_engine.py

# At INFO — emitted for every successful lesson generation:
logger.info(
    "adaptive_lesson_generated",
    extra={
        "student_id": str(request.student_id),
        "concept_id": request.concept_id,
        "speed": learning_profile.speed.value,
        "comprehension": learning_profile.comprehension.value,
        "engagement": learning_profile.engagement.value,
        "card_count": len(all_cards),
        "remediation_included": remediation_candidate.should_remediate,
        "duration_ms": round((time.monotonic() - start_ts) * 1000),
    }
)

# At WARNING — LLM retry triggered:
logger.warning(
    "adaptive_llm_retry",
    extra={"attempt": attempt, "error": str(exc), "concept_id": request.concept_id}
)

# At ERROR — all retries exhausted:
logger.error(
    "adaptive_llm_failed",
    extra={"concept_id": request.concept_id, "last_error": str(last_exc)}
)
```

### Key Metrics (to be instrumented by devops-engineer)
- `adaptive_lesson_latency_ms` — histogram of end-to-end lesson generation time
- `adaptive_llm_retry_count` — counter of LLM retries (alert if rate > 5% of requests)
- `adaptive_llm_failure_count` — counter of full LLM failures (alert if > 0 in 5-minute window)
- `adaptive_lesson_card_count` — histogram of cards per lesson (validates profile mapping)
- `adaptive_remediation_rate` — percentage of lessons with remediation (validates STRUGGLING detection)

### Distributed Tracing
- The existing `AsyncOpenAI` client propagates OpenAI request IDs in response headers. Log `response.id` alongside the `adaptive_lesson_generated` event for LLM call traceability.

---

## 13. Error Handling and Resilience

### Retry Policy
```python
async def _call_llm_with_retry(self, system_prompt, user_prompt, max_retries=3):
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            response = await self.openai_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=ADAPTIVE_LLM_MAX_TOKENS,
            )
            raw = (response.choices[0].message.content or "").strip()
            raw = _extract_json_block(raw)   # strip markdown fences if present
            parsed = json.loads(raw)
            return parsed
        except json.JSONDecodeError as exc:
            last_exc = exc
            salvaged = _salvage_truncated_json(raw)
            if salvaged:
                return salvaged
            logger.warning("adaptive_llm_retry", extra={"attempt": attempt, ...})
        except Exception as exc:
            last_exc = exc
            logger.warning("adaptive_llm_retry", extra={"attempt": attempt, ...})
        if attempt < max_retries:
            await asyncio.sleep(2 * attempt)  # 2s, 4s
    logger.error("adaptive_llm_failed", ...)
    raise HTTPException(status_code=502, detail=f"Lesson generation failed: {last_exc}")
```

### Graceful Degradation
- **DB mastery query failure:** Catch `SQLAlchemyError`; log at WARNING; treat all prerequisites as unmastered. This triggers remediation for more students than necessary (conservative, not dangerous).
- **KnowledgeService concept not found:** Return HTTP 404 (no graceful degradation — the caller must supply a valid concept_id).
- **Graph node missing:** `graph.predecessors(concept_id)` returns an empty iterator for unknown nodes; handled gracefully (no remediation, no crash).

### Timeouts
- No explicit timeout on the OpenAI call in the engine itself (Uvicorn's `--timeout-keep-alive` and OpenAI client's default 600s timeout apply). The retry back-off (2s + 4s + LLM latency) means the worst case is ~16s before returning 502.
- The product team should configure a gateway-level timeout (e.g., 15s via nginx) to ensure a deterministic client experience.

---

## 14. Testing Strategy

### Unit Tests (`backend/tests/test_adaptive_engine.py`)

All classification and mapping functions are pure functions testable without any mocking.

**Required test cases for `profile_builder.py`:**

```python
# Speed classification
def test_classify_speed_slow():
    assert classify_speed(820, 450, 6) == "SLOW"   # 820 > 450*1.5 = 675

def test_classify_speed_fast():
    assert classify_speed(200, 450, 1) == "FAST"   # 200 < 450*0.7 = 315, attempts=1

def test_classify_speed_fast_brute_force_guard():
    # Many attempts prevents FAST even if time is short
    assert classify_speed(200, 450, 5) == "NORMAL"

def test_classify_speed_normal():
    assert classify_speed(450, 450, 3) == "NORMAL"

# Comprehension classification
def test_classify_comprehension_struggling_by_error_rate():
    assert classify_comprehension(error_rate=0.6, quiz_score=0.9, hints_used=1) == "STRUGGLING"

def test_classify_comprehension_struggling_by_quiz():
    assert classify_comprehension(error_rate=0.1, quiz_score=0.4, hints_used=0) == "STRUGGLING"

def test_classify_comprehension_strong():
    assert classify_comprehension(error_rate=0.1, quiz_score=0.85, hints_used=1) == "STRONG"

def test_classify_comprehension_ok():
    assert classify_comprehension(error_rate=0.3, quiz_score=0.65, hints_used=3) == "OK"

# Engagement classification
def test_classify_engagement_bored_checked_first():
    # skip_rate > 0.35 overrides hints+revisits → BORED, not OVERWHELMED
    assert classify_engagement(skip_rate=0.4, hints_used=6, revisits=3) == "BORED"

def test_classify_engagement_overwhelmed():
    assert classify_engagement(skip_rate=0.1, hints_used=5, revisits=2) == "OVERWHELMED"

def test_classify_engagement_engaged():
    assert classify_engagement(skip_rate=0.1, hints_used=2, revisits=1) == "ENGAGED"
```

**Required test cases for `generation_profile.py`:**

```python
def test_slow_struggling_base_profile():
    profile = LearningProfile(speed="SLOW", comprehension="STRUGGLING", engagement="ENGAGED", ...)
    gen = build_generation_profile(profile)
    assert gen.explanation_depth == "HIGH"
    assert gen.reading_level == "KID_SIMPLE"
    assert gen.card_count == 12
    assert gen.practice_count == 7

def test_overwhelmed_reduces_card_count():
    profile = LearningProfile(speed="SLOW", comprehension="STRUGGLING", engagement="OVERWHELMED", ...)
    gen = build_generation_profile(profile)
    assert gen.card_count == 9   # 12 - 3

def test_bored_increases_fun_level():
    profile = LearningProfile(speed="NORMAL", comprehension="OK", engagement="BORED", ...)
    gen = build_generation_profile(profile)
    assert gen.fun_level == pytest.approx(0.5, abs=0.01)   # 0.2 + 0.3
    assert gen.emoji_policy == "SPARING"

def test_fast_strong_minimal_content():
    profile = LearningProfile(speed="FAST", comprehension="STRONG", engagement="ENGAGED", ...)
    gen = build_generation_profile(profile)
    assert gen.card_count == 7
    assert gen.practice_count == 3
    assert gen.explanation_depth == "LOW"

def test_card_count_floor_at_7():
    # SLOW+STRUGGLING+OVERWHELMED: 12 - 3 = 9 (not below 7)
    profile = LearningProfile(speed="SLOW", comprehension="STRUGGLING", engagement="OVERWHELMED", ...)
    gen = build_generation_profile(profile)
    assert gen.card_count >= 7
```

**Required test cases for `remediation.py`:**

```python
@pytest.mark.asyncio
async def test_no_remediation_when_not_struggling(mock_db, mock_graph):
    candidate = await resolve_remediation("uuid", "C1", "OK", mock_graph, mock_db)
    assert candidate.should_remediate is False

@pytest.mark.asyncio
async def test_no_remediation_when_all_prereqs_mastered(mock_db, mock_graph):
    # graph has prereqs, DB shows all mastered
    candidate = await resolve_remediation("uuid", "C1", "STRUGGLING", mock_graph_with_prereqs, mock_db_all_mastered)
    assert candidate.should_remediate is False

@pytest.mark.asyncio
async def test_remediation_selects_first_unmastered_prereq(mock_db, mock_graph):
    # graph: C1 has prereqs [P1, P2]; P1 mastered, P2 not
    candidate = await resolve_remediation("uuid", "C1", "STRUGGLING", mock_graph, mock_db)
    assert candidate.should_remediate is True
    assert candidate.prereq_concept_id == "P2"
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_generate_lesson_end_to_end(test_db, mock_knowledge_svc, mock_openai):
    """Full engine pipeline with a mocked OpenAI response."""
    engine = AdaptiveEngine(mock_knowledge_svc, mock_openai_client, "gpt-4o")
    request = AdaptiveLessonRequest(
        student_id=str(test_student_uuid),
        concept_id="PREALG.C4.S2.MULTIPLY_AND_DIVIDE_FRACTIONS",
        analytics_summary=AnalyticsSummary(...),
    )
    lesson = await engine.generate_lesson(request, test_db)
    assert isinstance(lesson, AdaptiveLesson)
    assert len(lesson.lesson.cards) >= 7

@pytest.mark.asyncio
async def test_generate_lesson_returns_404_for_unknown_student(test_db, mock_knowledge_svc):
    engine = AdaptiveEngine(mock_knowledge_svc, mock_openai_client, "gpt-4o")
    request = AdaptiveLessonRequest(student_id=str(uuid.uuid4()), ...)
    with pytest.raises(HTTPException) as exc_info:
        await engine.generate_lesson(request, test_db)
    assert exc_info.value.status_code == 404
```

### E2E Tests

```python
@pytest.mark.asyncio
async def test_adaptive_lesson_api_endpoint(async_client, seeded_student):
    """Full HTTP round-trip through the FastAPI test client."""
    response = await async_client.post(
        "/api/v3/adaptive/lesson",
        json={
            "student_id": str(seeded_student.id),
            "concept_id": "PREALG.C4.S2.MULTIPLY_AND_DIVIDE_FRACTIONS",
            "analytics_summary": {...},
        }
    )
    assert response.status_code == 200
    body = response.json()
    assert "learning_profile" in body
    assert "generation_profile" in body
    assert "lesson" in body
    assert len(body["lesson"]["cards"]) >= 7
```

### Performance Testing
- Target: ≤ 8s P95 response time under 10 concurrent requests (baseline before production load testing).
- Tool: `locust` or `pytest-benchmark` (devops-engineer to set up).
- Mocked LLM response for load testing (to isolate application-layer performance from OpenAI latency variability).

### Contract Testing
- The `AdaptiveLesson` Pydantic schema serves as the API contract. The frontend Axios wrapper should validate the response shape in development mode.
- Any schema changes must bump the API version or be backward-compatible (additive fields only).

---

## Key Decisions Requiring Stakeholder Input

1. **Remediation card quality:** The v1 remediation cards are template-generated (no LLM call). This keeps latency and cost down but produces lower-quality review content. Should remediation cards also be LLM-generated in v1, or is template quality acceptable for the initial rollout?

2. **`get_db()` dependency:** The existing `teaching_router.py` uses a `get_db` dependency from `db/connection.py`. Confirm that this dependency is already implemented (or that the devops-engineer will provide it before Phase 3 begins).

3. **Error rate calculation when `attempts == 0`:** The spec says `error_rate = wrong_attempts / attempts`. If a student never attempted (attempts=0), error_rate defaults to 0.0. Should it default to 0.5 (unknown) to push toward STRUGGLING rather than STRONG?

4. **Prompt language:** The existing `prompts.py` uses `LANGUAGE_NAMES` dict and a specific language-instruction block. Should `build_adaptive_system_prompt()` import and reuse `LANGUAGE_NAMES` from `api/prompts.py`, or maintain its own mapping to avoid cross-module coupling?

5. **`LessonCard.answer` nullability for MCQ:** For `type=mcq` cards, `answer` should always be non-null (it is the correct option string). Should the schema enforce `answer: str` for MCQ type specifically, or is `Optional[str]` acceptable for v1 simplicity?
