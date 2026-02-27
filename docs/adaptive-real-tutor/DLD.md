# Detailed Low-Level Design — Adaptive Real Tutor
**Feature slug:** `adaptive-real-tutor`
**Version:** 1.0
**Date:** 2026-02-27
**Author:** Solution Architect Agent

---

## 1. Component Breakdown

### 1.1 New Components

| Component | File | Responsibility |
|---|---|---|
| `SignalBlender` | `backend/src/adaptive/blending.py` | Pure functions: baseline aggregation data class + deviation-aware blending algorithm. No I/O. |
| `SpacedReviewScheduler` | `backend/src/adaptive/spaced_review.py` | Pure function `compute_next_due()` — returns a `datetime` given `review_number`. No I/O. |
| `NextCardPromptBuilder` | `backend/src/adaptive/prompt_builder.py` (extended) | New function `build_next_card_prompt()` alongside existing `build_adaptive_prompt()`. |
| `complete_card` endpoint | `backend/src/adaptive/adaptive_router.py` (extended) | New route `POST /api/v2/sessions/{session_id}/complete-card`. |
| `review_due` endpoint | `backend/src/adaptive/adaptive_router.py` (extended) | New route `GET /api/v2/students/{student_id}/review-due`. |
| `completeCard` API wrapper | `frontend/src/api/sessions.js` (extended) | Axios call for `POST /api/v2/sessions/{id}/complete-card`. |
| `getReviewsDue` API wrapper | `frontend/src/api/sessions.js` (extended) | Axios call for `GET /api/v2/students/{id}/review-due`. |
| Signal tracking hooks | `frontend/src/components/learning/CardLearningView.jsx` (extended) | `useRef` timer + per-card counters wired to card navigation. |
| Review badge | `frontend/src/pages/ConceptMapPage.jsx` (extended) | Overlay badge on nodes returned by `getReviewsDue`. |

### 1.2 Existing Components (Unchanged Interfaces, Reused)

| Component | File | How Reused |
|---|---|---|
| `_call_llm()` | `adaptive/adaptive_engine.py` | Imported and called in the next-card generation flow |
| `_extract_json_block()` | `adaptive/adaptive_engine.py` | Imported for JSON parsing of single-card LLM response |
| `_salvage_truncated_json()` | `adaptive/adaptive_engine.py` | Imported for truncation recovery |
| `build_learning_profile()` | `adaptive/profile_builder.py` | Called with blended `AnalyticsSummary` |
| `build_generation_profile()` | `adaptive/generation_profile.py` | Called with updated `LearningProfile` |
| `find_remediation_prereq()` | `adaptive/remediation.py` | Called with updated mastery state |
| `CardInteraction` ORM model | `db/models.py` | Written on each `complete-card` call |
| `SpacedReview` ORM model | `db/models.py` | Written on mastery completion |
| `StudentMastery` ORM model | `db/models.py` | Read to check mastery state for remediation |
| `get_db()` dependency | `db/connection.py` | FastAPI dependency for `AsyncSession` |

### 1.3 Inter-Component Interface Summary

```
Frontend                          Backend
--------                          -------
CardLearningView
  ├── completeCard(sessionId, signals)
  │       └─► POST /api/v2/sessions/{id}/complete-card
  │               ├── write CardInteraction
  │               ├── aggregate_student_baseline()
  │               ├── blend_signals()
  │               ├── build_learning_profile()
  │               ├── build_generation_profile()
  │               ├── build_next_card_prompt()
  │               ├── _call_llm()
  │               └─► NextCardResponse (card + motivational_note + metadata)
  │
ConceptMapPage
  ├── getReviewsDue(studentId)
  │       └─► GET /api/v2/students/{id}/review-due
  │               └─► ReviewDueItem[]
  │
SessionContext (finishCards)
  └── POST /api/v2/sessions/{id}/complete-cards (existing, unchanged)
      └── POST /api/v2/sessions/{id}/begin-check (existing, unchanged)
```

---

## 2. Data Design

### 2.1 Existing Tables Used (No Schema Changes)

#### `card_interactions` (migration `e3c02cf4c22e` — already applied)
```sql
CREATE TABLE card_interactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID NOT NULL REFERENCES teaching_sessions(id) ON DELETE CASCADE,
    student_id          UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    concept_id          VARCHAR(200) NOT NULL,
    card_index          INTEGER NOT NULL,
    time_on_card_sec    FLOAT DEFAULT 0.0,
    wrong_attempts      INTEGER DEFAULT 0,
    selected_wrong_option SMALLINT,
    hints_used          INTEGER DEFAULT 0,
    idle_triggers       INTEGER DEFAULT 0,
    adaptation_applied  VARCHAR(200),
    completed_at        TIMESTAMPTZ DEFAULT now()
);
```

**Index required** (add as separate Alembic patch if not present — check with devops-engineer):
```sql
CREATE INDEX ix_card_interactions_student_id ON card_interactions(student_id);
CREATE INDEX ix_card_interactions_student_completed
    ON card_interactions(student_id, completed_at DESC);
```

#### `spaced_reviews` (migration `e3c02cf4c22e` — already applied)
```sql
CREATE TABLE spaced_reviews (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id   UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    concept_id   VARCHAR(200) NOT NULL,
    review_number SMALLINT DEFAULT 1,
    due_at       TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);
```

**Unique constraint required** (patch migration — confirm with devops-engineer):
```sql
ALTER TABLE spaced_reviews
    ADD CONSTRAINT uq_student_concept_review
    UNIQUE (student_id, concept_id, review_number);
```

### 2.2 New Pydantic Schemas — `adaptive/real_tutor_schemas.py` (new file)

```python
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class CompleteCardRequest(BaseModel):
    """POST /api/v2/sessions/{session_id}/complete-card request body."""
    card_index: int = Field(ge=0, description="Zero-based index of the card just completed")
    time_on_card_sec: float = Field(ge=0.0, description="Wall-clock seconds the student spent on this card")
    wrong_attempts: int = Field(ge=0, description="Number of wrong answer attempts on this card")
    selected_wrong_option: int | None = Field(None, description="Index of the wrong MCQ option selected (0-based), or null")
    hints_used: int = Field(ge=0, description="Number of hints the student requested on this card")
    idle_triggers: int = Field(ge=0, description="Number of times the idle detector fired on this card")


class LearningProfileSummary(BaseModel):
    """Compact learning profile included in the complete-card response for frontend display."""
    speed: Literal["SLOW", "NORMAL", "FAST"]
    comprehension: Literal["STRUGGLING", "OK", "STRONG"]
    engagement: Literal["BORED", "ENGAGED", "OVERWHELMED"]
    confidence_score: float = Field(ge=0.0, le=1.0)


class NextCard(BaseModel):
    """A single adaptively generated card returned by complete-card."""
    title: str
    content: str = Field(description="Markdown-formatted card body")
    questions: list[dict] = Field(default_factory=list, description="MCQ/true-false questions — same schema as existing cards")
    motivational_note: str = Field(description="One warm sentence of encouragement generated by the LLM")


class CompleteCardResponse(BaseModel):
    """POST /api/v2/sessions/{session_id}/complete-card 200 response."""
    session_id: uuid.UUID
    card: NextCard
    card_index: int = Field(description="Index of the newly generated card (card_index + 1)")
    adaptation_applied: str = Field(description="Human-readable label of the adaptation tier applied, e.g. 'SLOW/STRUGGLING'")
    learning_profile_summary: LearningProfileSummary
    motivational_note: str = Field(description="Duplicated from card.motivational_note for easy frontend access")
    performance_vs_baseline: Literal["MUCH_FASTER", "FASTER", "ON_BASELINE", "SLOWER", "MUCH_SLOWER", "NO_BASELINE"]


class ReviewDueItem(BaseModel):
    """One due spaced-review entry returned by GET /api/v2/students/{student_id}/review-due."""
    concept_id: str
    concept_title_hint: str = Field(description="Short title hint from ChromaDB metadata; empty string if not found")
    due_at: datetime
    review_number: int


class StudentBaseline(BaseModel):
    """
    Aggregated cross-session personal baseline for a student.
    Produced by aggregate_student_baseline().
    All fields default to None if fewer than MIN_HISTORY_CARDS exist.
    """
    avg_time_on_card_sec: float | None
    avg_wrong_attempts: float | None
    avg_hints_used: float | None
    total_cards_completed: int


class BlendedSignals(BaseModel):
    """
    Result of blend_signals(). Structurally identical to AnalyticsSummary fields
    needed by build_learning_profile(), but named to make the blending origin explicit.
    """
    blended_time_sec: float
    blended_wrong_attempts: float
    blended_hints_used: float
    # Derived
    is_acute_deviation: bool
    performance_vs_baseline: Literal["MUCH_FASTER", "FASTER", "ON_BASELINE", "SLOWER", "MUCH_SLOWER", "NO_BASELINE"]
```

### 2.3 Data Flow

```
Request signals (CompleteCardRequest)
        │
        ▼
[DB WRITE] CardInteraction row persisted
        │
        ▼
aggregate_student_baseline(db, student_id)
  └── SELECT AVG(time_on_card_sec), AVG(wrong_attempts), AVG(hints_used),
             COUNT(*) FROM card_interactions WHERE student_id = ?
  └── Returns StudentBaseline
        │
        ▼
blend_signals(current_req, baseline) → BlendedSignals
  └── Pure function — see §2.4 algorithm
        │
        ▼
Build AnalyticsSummary from BlendedSignals
  (maps blended values into existing AnalyticsSummary schema)
        │
        ▼
build_learning_profile(analytics_summary, has_unmet_prereq)
  └── Existing pure function — returns LearningProfile
        │
        ▼
build_generation_profile(learning_profile)
  └── Existing pure function — returns GenerationProfile
        │
        ▼
build_next_card_prompt(concept_detail, learning_profile, gen_profile, card_index, language)
  └── Returns (system_prompt, user_prompt) for single-card generation
        │
        ▼
_call_llm(llm_client, model, messages, max_tokens=1200)
  └── Returns raw JSON string
        │
        ▼
Parse + validate → NextCardLLMOutput (Pydantic)
        │
        ▼
Map NextCardLLMOutput → CompleteCardResponse
  └── Persist adaptation_applied back to the CardInteraction row (UPDATE)
```

### 2.4 Caching Strategy
- No caching layer is introduced. The history aggregation query is fast (indexed, bounded by student's total card count). At current student scale, result caching would add complexity without measurable benefit.
- Concept detail for the next card is fetched from `KnowledgeService`, which already holds ChromaDB + NetworkX in memory. No additional cache needed.

### 2.5 Data Retention
- `card_interactions` rows are retained indefinitely (no TTL). They are the source of truth for the personal baseline.
- If a student is deleted (cascade), all `card_interactions` and `spaced_reviews` rows are deleted automatically via the `ON DELETE CASCADE` FK constraint.

---

## 3. API Design

### 3.1 `POST /api/v2/sessions/{session_id}/complete-card`

**Purpose:** Record card completion signals, generate the next adaptive card.

**Authentication:** None currently (ADA has no auth layer). Future: session ownership validated via DB join (teaching_sessions.student_id == authenticated student ID).

**Path parameter:** `session_id` — UUID of the current teaching session.

**Request body:** `CompleteCardRequest` (see §2.2)

```json
{
  "card_index": 0,
  "time_on_card_sec": 45.2,
  "wrong_attempts": 1,
  "selected_wrong_option": 2,
  "hints_used": 0,
  "idle_triggers": 0
}
```

**Success response — 200 `CompleteCardResponse`:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "card": {
    "title": "Breaking Down Mixed Numbers",
    "content": "A **mixed number** combines a whole number and a fraction...\n\n$$2\\frac{3}{4} = 2 + \\frac{3}{4}$$",
    "questions": [
      {
        "type": "mcq",
        "question": "What is the fractional part of $3\\frac{1}{2}$?",
        "options": ["$\\frac{1}{2}$", "$3$", "$\\frac{3}{2}$", "$\\frac{1}{3}$"],
        "correct_index": 0,
        "explanation": "The fractional part is always the part after the whole number."
      }
    ],
    "motivational_note": "You're asking great questions — that's exactly how mathematicians think!"
  },
  "card_index": 1,
  "adaptation_applied": "SLOW/STRUGGLING",
  "learning_profile_summary": {
    "speed": "SLOW",
    "comprehension": "STRUGGLING",
    "engagement": "ENGAGED",
    "confidence_score": 0.31
  },
  "motivational_note": "You're asking great questions — that's exactly how mathematicians think!",
  "performance_vs_baseline": "SLOWER"
}
```

**Error responses:**

| Status | Condition | Body |
|---|---|---|
| 404 | `session_id` not found in DB | `{"detail": "Session not found: <id>"}` |
| 404 | Concept not found in KnowledgeService | `{"detail": "Concept not found: <concept_id>"}` |
| 409 | `card_index >= ADAPTIVE_CARD_CEILING` | `{"ceiling": true}` |
| 502 | LLM failed after 3 retries | `{"detail": "LLM failed after 3 attempts. Last error: ..."}` |
| 500 | Unexpected internal error | `{"detail": "Internal server error"}` |

**Idempotency:** Not idempotent. Each call writes a `card_interactions` row. If the frontend retries on network failure, a duplicate row may be written. The blending aggregation uses `AVG()` so a duplicate row marginally shifts the baseline but does not break correctness. This is an acceptable trade-off for v1.

### 3.2 `GET /api/v2/students/{student_id}/review-due`

**Purpose:** Return all spaced-review entries due today or earlier for a student.

**Path parameter:** `student_id` — UUID of the student.

**Query parameters:** None in v1. Future: `?limit=20&offset=0`.

**Success response — 200 `list[ReviewDueItem]`:**
```json
[
  {
    "concept_id": "PREALG_2_3_fractions_basic",
    "concept_title_hint": "Basic Fractions",
    "due_at": "2026-02-27T00:00:00Z",
    "review_number": 1
  }
]
```

Returns empty array `[]` when no reviews are due. Never returns 404.

**Error responses:**

| Status | Condition |
|---|---|
| 404 | `student_id` not found |
| 500 | Internal server error |

### 3.3 Versioning Strategy
- Both new endpoints are under `/api/v2`. They extend the existing teaching session resource, consistent with the project convention that `/api/v2` owns the Teaching Loop.
- The `complete-card` endpoint is conceptually part of the teaching session lifecycle (a student completing a card is a teaching session action).
- Future breaking changes will increment to `/api/v3` per the established project versioning convention.

### 3.4 Error Handling Conventions
- All HTTP errors use FastAPI `HTTPException` with a `detail` string — consistent with `adaptive_router.py`.
- The 409 `{"ceiling": true}` body is a special non-detail format. Use `JSONResponse(status_code=409, content={"ceiling": True})`.
- The 502 body uses the standard `detail` key so the frontend can display it if needed.
- The frontend is instructed to treat 502 as silent fallback (not user-visible error).

---

## 4. Sequence Diagrams

### 4.1 Happy Path — Student Advances from Card N to Card N+1

```
Frontend (CardLearningView)          Backend                        OpenAI API
─────────────────────────            ─────────                      ──────────
Student clicks "Next Card"
  │
  ├── Stop timer → record time_on_card_sec
  ├── Capture wrong_attempts, selected_wrong_option,
  │   hints_used, idle_triggers from state
  │
  ├── POST /api/v2/sessions/{id}/complete-card
  │   body: {card_index: N, time_on_card_sec: 45.2, ...}
  │                                       │
  │                     [await db.get(TeachingSession, session_id)]
  │                     └── 404 if not found
  │                                       │
  │                     [INSERT CardInteraction row]
  │                                       │
  │                     [SELECT AVG() FROM card_interactions
  │                      WHERE student_id = ?]
  │                     └── StudentBaseline(avg_time=72.1, avg_wrong=0.4, ...)
  │                                       │
  │                     [blend_signals(current, baseline)]
  │                     └── BlendedSignals(blended_time=52.4, ...,
  │                                        performance_vs_baseline="SLOWER")
  │                                       │
  │                     [build_learning_profile(blended_analytics)]
  │                     └── LearningProfile(speed="SLOW", comprehension="STRUGGLING")
  │                                       │
  │                     [build_generation_profile(learning_profile)]
  │                     └── GenerationProfile(explanation_depth="HIGH", card_count=12)
  │                                       │
  │                     [knowledge_svc.get_concept_detail(concept_id)]
  │                     └── concept_detail dict (from ChromaDB + in-memory)
  │                                       │
  │                     [find_remediation_prereq(concept_id, knowledge_svc, mastery)]
  │                                       │
  │                     [build_next_card_prompt(...)]
  │                     └── (system_prompt, user_prompt)
  │                                       │
  │                                       ├─────────────────────────────►
  │                                       │  POST chat.completions.create
  │                                       │  model=gpt-4o-mini
  │                                       │  max_tokens=1200
  │                                       │◄─────────────────────────────
  │                                       │  raw JSON string
  │                                       │
  │                     [parse + validate NextCardLLMOutput]
  │                     [UPDATE card_interactions SET
  │                      adaptation_applied = "SLOW/STRUGGLING"
  │                      WHERE id = <just-inserted-id>]
  │                                       │
  │◄──────────────────────────────────────┤
  │  200 CompleteCardResponse             │
  │  {card: {...}, card_index: N+1, ...}  │
  │
  ├── Replace current card in state with response.card
  ├── Reset timer → start for card N+1
  ├── Track PostHog event "adaptive_card_generated"
  └── Render new card
```

### 4.2 Ceiling Reached — Advance to Socratic Check

```
Frontend                        Backend
────────                        ───────
Student completes card at card_index = ADAPTIVE_CARD_CEILING - 1
  │
  ├── POST /api/v2/sessions/{id}/complete-card {card_index: 7}
  │                                   │
  │               [check: card_index >= ADAPTIVE_CARD_CEILING]
  │               └── True
  │               [INSERT final CardInteraction row]
  │               [schedule_spaced_review() if concept already mastered — skip here]
  │◄──────────────────────────────────┤
  │  409 {"ceiling": true}            │
  │
  └── Call finishCards() → transition to Socratic CHECKING phase
```

### 4.3 LLM Failure — Silent Fallback

```
Frontend                        Backend                  OpenAI API
────────                        ───────                  ──────────
POST /api/v2/sessions/{id}/complete-card
  │                                   │
  │                   [_call_llm() attempt 1] ──────────────►
  │                                   │ ◄──── timeout/error ─┤
  │                   [asyncio.sleep(2)]
  │                   [_call_llm() attempt 2] ──────────────►
  │                                   │ ◄──── timeout/error ─┤
  │                   [asyncio.sleep(4)]
  │                   [_call_llm() attempt 3] ──────────────►
  │                                   │ ◄──── timeout/error ─┤
  │                   [raise ValueError("LLM failed after 3 attempts")]
  │◄──────────────────────────────────┤
  │  502 {"detail": "LLM failed..."}  │
  │
  └── Silently suppress error
      Keep current card displayed
      (or advance to next pre-generated card if still available)
      Do NOT show error to student
```

### 4.4 Spaced Review Scheduling — Mastery Completion

```
Frontend (SessionContext.finishCards)    Backend
───────────────────────────────────      ───────
POST /api/v2/sessions/{id}/complete-cards (existing endpoint)
  │                                            │
  │              [existing: mark session CARDS_DONE]
  │              [NEW: if not already in spaced_reviews for this concept]
  │              [  schedule_spaced_review(db, student_id, concept_id)]
  │              [  review_number = 1 + count(existing reviews for concept)]
  │              [  due_at = now() + SR_INTERVALS[review_number - 1]]
  │              [  INSERT SpacedReview row]
  │              [  (unique constraint prevents duplicate on retry)]
  │◄─────────────────────────────────────────┤
  │  200 (existing response unchanged)        │
```

### 4.5 Review Due Query

```
Frontend (ConceptMapPage on mount)      Backend               DB
──────────────────────────────────      ───────               ──
GET /api/v2/students/{id}/review-due
  │                                          │
  │              [SELECT sr.concept_id, sr.due_at, sr.review_number
  │               FROM spaced_reviews sr
  │               WHERE sr.student_id = ?
  │               AND sr.due_at <= now()
  │               AND sr.completed_at IS NULL
  │               ORDER BY sr.due_at ASC]
  │                                          │◄──── rows ─────┤
  │              [for each row: knowledge_svc.get_concept_title(concept_id)]
  │◄─────────────────────────────────────────┤
  │  200 [ReviewDueItem, ...]                │
  │
  ├── Build Set of due concept_ids
  └── Mark matching ConceptMap nodes with review badge
```

---

## 5. Integration Design

### 5.1 OpenAI API — Single-Card Generation
- **Protocol:** HTTPS REST via `AsyncOpenAI` client (existing client instance, no new client)
- **Model:** `ADAPTIVE_CARD_MODEL` from `config.py` (default `gpt-4o-mini`)
- **Token budget:** `max_tokens=1200` — one card, one motivational sentence
- **Retry:** 3 attempts, `asyncio.sleep(2 * attempt)` — identical to `_call_llm()` in `adaptive_engine.py`
- **Circuit breaker:** Not implemented in v1 (Python `tenacity` or a counter-based breaker is a v2 upgrade). The 3-attempt retry is the resilience mechanism.
- **Authentication:** `OPENAI_API_KEY` from environment (loaded in `config.py` via `python-dotenv`)

### 5.2 KnowledgeService (Internal, In-Process)
- `knowledge_svc.get_concept_detail(concept_id)` — synchronous in-memory lookup (ChromaDB + NetworkX). Called once per `complete-card` request.
- `knowledge_svc.get_concept_title(concept_id)` — may need to be added to `KnowledgeService` if not present. Fallback: use `knowledge_svc.get_concept_detail(concept_id).get("concept_title", "")`.
- No new integration contracts needed — the existing `KnowledgeService` API is sufficient.

### 5.3 PostgreSQL (via SQLAlchemy async)
- All DB operations use `AsyncSession` from `get_db()` FastAPI dependency.
- The `complete-card` endpoint performs: 1 SELECT (session lookup), 1 INSERT (CardInteraction), 1 SELECT+AVG (baseline), 1 UPDATE (adaptation_applied back-fill). All within the same request lifecycle; no explicit transaction wrapping needed (SQLAlchemy auto-commit on session close with the existing `get_db()` implementation).
- The spaced-review INSERT uses `on_conflict_do_nothing()` (SQLAlchemy dialect) or the unique constraint will suppress duplicates gracefully.

---

## 6. Security Design

### 6.1 Authentication and Authorization
- ADA does not implement authentication in v1. Session ownership is validated by confirming the `session_id` exists in `teaching_sessions` (404 if not). Future: compare `teaching_sessions.student_id` against the authenticated session token.

### 6.2 Data Encryption
- All data in transit: HTTPS (enforced by the deployment environment — not in-scope for this feature).
- Data at rest: PostgreSQL default (no column-level encryption in v1).

### 6.3 Input Validation and Sanitization
- All request fields are validated by Pydantic v2 (field constraints, types, `ge`/`le` bounds).
- `time_on_card_sec` is clamped server-side before being passed to blending: `max(0.0, min(time_on_card_sec, 3600.0))` to prevent absurd values from skewing baselines.
- `card_index` is validated: reject values < 0 (Pydantic `ge=0`) and check against `ADAPTIVE_CARD_CEILING`.
- `concept_id` from the session is read from the DB, never from the request body — prevents concept substitution attacks.

### 6.4 LLM Prompt Security
- Concept text injected into the prompt is hard-truncated at `_CONCEPT_TEXT_LIMIT = 3000` chars (inherited from `prompt_builder.py`).
- No student-supplied text is injected into the LLM prompt (student behavioral signals are numeric; student name is not included in next-card prompts).

### 6.5 Secrets Management
- `OPENAI_API_KEY` loaded from `backend/.env` via `config.py`. Never logged. Never returned in API responses.

---

## 7. Observability Design

### 7.1 Structured Logging

Every `complete-card` request emits a log line at INFO level on success:

```python
logger.info(
    "adaptive_next_card_generated: student_id=%s session_id=%s card_index=%d "
    "adaptation_applied=%s speed=%s comprehension=%s engagement=%s "
    "confidence=%.2f performance_vs_baseline=%s is_acute=%s duration_ms=%d",
    student_id, session_id, new_card_index,
    adaptation_applied, speed, comprehension, engagement,
    confidence_score, performance_vs_baseline, is_acute_deviation, duration_ms,
)
```

DB aggregation time is logged at DEBUG level:
```python
logger.debug("baseline_aggregated: student_id=%s total_cards=%d query_ms=%d",
             student_id, total_cards_completed, query_ms)
```

LLM retries are logged at WARNING (inherited from `_call_llm()`).

### 7.2 Key Metrics (PostHog Events — Frontend)

| Event Name | Properties |
|---|---|
| `adaptive_card_generated` | `session_id`, `card_index`, `adaptation_applied`, `performance_vs_baseline`, `speed`, `comprehension` |
| `card_ceiling_reached` | `session_id`, `card_index`, `concept_id` |
| `llm_fallback_triggered` | `session_id`, `card_index`, `status_code` |
| `review_due_badge_shown` | `student_id`, `concept_id`, `review_number`, `days_overdue` |

### 7.3 Key Backend Metrics to Dashboard (future Prometheus/Grafana)
- `complete_card_duration_ms` histogram (p50, p95, p99)
- `complete_card_llm_failures_total` counter
- `complete_card_ceiling_hit_total` counter
- `spaced_review_scheduled_total` counter

### 7.4 Alerting Thresholds
- LLM failure rate > 5% over 5 minutes: PagerDuty alert
- `complete_card` p95 latency > 4000 ms for 3 consecutive minutes: warning alert

### 7.5 Distributed Tracing
- Not implemented in v1. Request correlation is achieved via `student_id` + `session_id` in every log line, enabling Kibana/Loki log correlation.

---

## 8. Error Handling and Resilience

### 8.1 Retry Policy
- LLM calls: 3 attempts, `asyncio.sleep(2 * attempt)` back-off (inherited from `_call_llm()`). Matches existing adaptive engine pattern exactly.

### 8.2 Timeouts
- No explicit HTTP client timeout is set in `_call_llm()` today. For the single-card endpoint, add `timeout=30.0` to the `AsyncOpenAI` client call to prevent indefinite hangs. The existing lesson endpoint does not have this issue because it is a batch call.

### 8.3 Circuit Breakers
- Not implemented in v1. If needed in future, use `tenacity` with a `stop_after_attempt(3)` + `wait_exponential()` decorator around `_call_llm()`.

### 8.4 Graceful Degradation

| Failure | Handling |
|---|---|
| LLM failure (3 retries exhausted) | Return 502; frontend silently keeps current card or advances using pre-generated card from initial batch |
| `ADAPTIVE_CARDS_ENABLED = False` | `complete-card` endpoint skips all blending and LLM; returns the next card from the initial lesson batch stored in session (future implementation detail — see execution plan Phase 2) |
| DB connection lost | FastAPI dependency `get_db()` raises; standard 500 response |
| KnowledgeService returns None for concept | Return 404 — this is a data integrity issue, not a runtime failure |
| Spaced review INSERT fails (unique constraint) | Log at WARNING, suppress error, return normally — mastery is not affected |

### 8.5 Failure Scenarios

**Scenario A — Student submits card signal twice (double-tap "Next"):**
- Two `card_interactions` rows are inserted with identical `card_index`.
- The second request also triggers an LLM call.
- Frontend must debounce the "Next Card" button (disable on first click, re-enable on response or error).
- Server-side: no additional protection in v1; the duplicate row marginally skews the baseline average (acceptable).

**Scenario B — Backend restarts during lesson:**
- Session row persists in DB.
- `complete-card` can resume as long as the session_id is valid.
- Frontend must retain `currentCardIndex` in `SessionContext` state (already done via `useReducer`).

**Scenario C — LLM returns a card with missing `motivational_note`:**
- Pydantic validation: `motivational_note` is a required field in `NextCardLLMOutput`.
- If missing, `_salvage_truncated_json()` cannot add it. Return a default string: `"Keep going — every card brings you closer!"`.
- This fallback is applied in the parsing layer, not the LLM call.

---

## 9. Testing Strategy

### 9.1 Unit Tests (pytest, no DB, no LLM)

| Test | Module | What is Tested |
|---|---|---|
| `test_blend_signals_no_history` | `test_blending.py` | Returns current signals unchanged when `total_cards_completed < MIN_HISTORY_CARDS` |
| `test_blend_signals_steady_state` | `test_blending.py` | 60/40 blend when ratios are within normal range |
| `test_blend_signals_acute_time_high` | `test_blending.py` | 90/10 blend (acute=True) when `time_ratio > 2.0` |
| `test_blend_signals_acute_wrong_high` | `test_blending.py` | 90/10 blend when `wrong_ratio > 3.0` |
| `test_blend_signals_acute_time_low` | `test_blending.py` | 90/10 blend when `time_ratio < 0.4` |
| `test_performance_vs_baseline_much_slower` | `test_blending.py` | `MUCH_SLOWER` when `time_ratio > 2.0` |
| `test_performance_vs_baseline_no_baseline` | `test_blending.py` | `NO_BASELINE` when `total_cards_completed < MIN_HISTORY_CARDS` |
| `test_compute_next_due_review_1` | `test_spaced_review.py` | `due_at = now + timedelta(days=1)` for review_number=1 |
| `test_compute_next_due_review_5` | `test_spaced_review.py` | `due_at = now + timedelta(days=30)` for review_number=5 |
| `test_compute_next_due_review_overflow` | `test_spaced_review.py` | review_number > 5 returns interval for day 30 (clamped) |
| `test_build_next_card_prompt_structure` | `test_prompt_builder.py` | System prompt contains JSON schema; user prompt contains STUDENT PROFILE section |
| `test_build_next_card_prompt_language` | `test_prompt_builder.py` | Correct language name injected for `ta`, `ar` |
| `test_next_card_llm_output_validation` | `test_real_tutor_schemas.py` | Pydantic rejects output missing `motivational_note` |
| `test_complete_card_request_ceiling_rejected` | `test_real_tutor_schemas.py` | `card_index = -1` rejected by Pydantic `ge=0` |

### 9.2 Integration Tests (pytest + FastAPI TestClient + in-memory SQLite or PostgreSQL test DB)

| Test | What is Tested |
|---|---|
| `test_complete_card_writes_interaction_row` | DB row is created with correct field values after endpoint call |
| `test_complete_card_returns_next_card` | 200 response with valid `CompleteCardResponse` structure |
| `test_complete_card_ceiling_returns_409` | `card_index >= ADAPTIVE_CARD_CEILING` returns `{"ceiling": true}` |
| `test_complete_card_session_not_found_404` | Non-existent session_id returns 404 |
| `test_complete_card_llm_failure_returns_502` | Mocked LLM client raising ValueError returns 502 |
| `test_review_due_returns_empty_no_reviews` | Student with no `spaced_reviews` returns `[]` |
| `test_review_due_returns_overdue_items` | `spaced_reviews` row with `due_at` in the past is returned |
| `test_review_due_excludes_completed` | Row with `completed_at` not null is excluded |
| `test_spaced_review_scheduled_on_mastery` | Completing cards on a mastered concept inserts `spaced_reviews` row |
| `test_spaced_review_no_duplicate_on_retry` | Re-inserting same (student, concept, review_number) does not create duplicate |

### 9.3 End-to-End Tests (pytest + real DB + mocked LLM)

| Test | What is Tested |
|---|---|
| `test_full_card_sequence_adaptation` | Student completes 3 cards with increasing wrong_attempts; verify adaptation_applied changes from NORMAL/OK to SLOW/STRUGGLING |
| `test_ceiling_triggers_socratic_check` | Card sequence reaches ceiling; frontend state transitions to CHECKING phase |
| `test_spaced_review_full_lifecycle` | Mastery → spaced_review scheduled → review_due endpoint returns the item → completion marks it done |

### 9.4 Performance Tests
- Load test: 50 concurrent `POST /api/v2/sessions/{id}/complete-card` requests with mocked LLM returning immediately. Target: p95 < 200 ms (excluding LLM time).
- Load test with real LLM (canary environment): 10 concurrent requests. Target: p95 < 2500 ms.

### 9.5 Contract Testing
- The `CompleteCardResponse` Pydantic model serves as the contract between backend and frontend.
- Frontend Axios wrapper `completeCard()` must be tested with a mock server returning the exact JSON shape of `CompleteCardResponse`.

---

## Appendix A: Blending Algorithm — Complete Specification

```python
# backend/src/adaptive/blending.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

# ── Constants (all configurable via config.py) ────────────────────────────────
MIN_HISTORY_CARDS: int           = 5      # Minimum history rows before blending activates
BLEND_W_CURR_STEADY: float       = 0.6   # Current-signal weight in steady state
BLEND_W_HIST_STEADY: float       = 0.4   # Historical weight in steady state
BLEND_W_CURR_ACUTE: float        = 0.9   # Current-signal weight when acute deviation detected
BLEND_W_HIST_ACUTE: float        = 0.1   # Historical weight when acute deviation detected
ACUTE_TIME_RATIO_HIGH: float     = 2.0   # time_ratio above this → acute
ACUTE_TIME_RATIO_LOW: float      = 0.4   # time_ratio below this → acute
ACUTE_WRONG_RATIO: float         = 3.0   # wrong_ratio above this → acute
BASELINE_TIME_FLOOR: float       = 30.0  # Denominator floor for time_ratio (prevents division by very small numbers)

PerformanceLabel = Literal["MUCH_FASTER", "FASTER", "ON_BASELINE", "SLOWER", "MUCH_SLOWER", "NO_BASELINE"]


@dataclass(frozen=True)
class StudentBaseline:
    avg_time_on_card_sec: float | None
    avg_wrong_attempts: float | None
    avg_hints_used: float | None
    total_cards_completed: int


@dataclass(frozen=True)
class BlendedSignals:
    blended_time_sec: float
    blended_wrong_attempts: float
    blended_hints_used: float
    is_acute_deviation: bool
    performance_vs_baseline: PerformanceLabel


def blend_signals(
    current_time: float,
    current_wrong: float,
    current_hints: float,
    baseline: StudentBaseline,
) -> BlendedSignals:
    """
    Blend current-card signals with cross-session personal baseline.

    Algorithm:
        1. If total_cards_completed < MIN_HISTORY_CARDS:
               Use current signals verbatim (no history to blend against).
               is_acute = False; performance = "NO_BASELINE"

        2. Otherwise:
               time_ratio  = current_time  / max(baseline.avg_time_on_card_sec, BASELINE_TIME_FLOOR)
               wrong_ratio = (current_wrong + 1) / max(baseline.avg_wrong_attempts + 1, 1.0)
               is_acute    = time_ratio > ACUTE_TIME_RATIO_HIGH
                          OR time_ratio < ACUTE_TIME_RATIO_LOW
                          OR wrong_ratio > ACUTE_WRONG_RATIO

               w_curr, w_hist = (BLEND_W_CURR_ACUTE, BLEND_W_HIST_ACUTE) if is_acute
                             else (BLEND_W_CURR_STEADY, BLEND_W_HIST_STEADY)

               blended_time  = current_time  * w_curr + baseline.avg_time_on_card_sec  * w_hist
               blended_wrong = current_wrong * w_curr + baseline.avg_wrong_attempts     * w_hist
               blended_hints = current_hints * w_curr + baseline.avg_hints_used          * w_hist

        3. Compute performance_vs_baseline:
               Based on time_ratio (with NO_BASELINE guard):
                   > 1.6   → "MUCH_SLOWER"
                   > 1.2   → "SLOWER"
                   >= 0.8  → "ON_BASELINE"
                   >= 0.5  → "FASTER"
                   < 0.5   → "MUCH_FASTER"

    Returns:
        BlendedSignals with blended values and deviation metadata.

    Pure function — no I/O, no side effects.
    """
    # Guard: insufficient history
    if baseline.total_cards_completed < MIN_HISTORY_CARDS:
        return BlendedSignals(
            blended_time_sec=current_time,
            blended_wrong_attempts=current_wrong,
            blended_hints_used=current_hints,
            is_acute_deviation=False,
            performance_vs_baseline="NO_BASELINE",
        )

    baseline_time = baseline.avg_time_on_card_sec or BASELINE_TIME_FLOOR
    baseline_wrong = baseline.avg_wrong_attempts or 0.0
    baseline_hints = baseline.avg_hints_used or 0.0

    time_ratio  = current_time  / max(baseline_time, BASELINE_TIME_FLOOR)
    wrong_ratio = (current_wrong + 1) / max(baseline_wrong + 1, 1.0)

    is_acute = (
        time_ratio > ACUTE_TIME_RATIO_HIGH
        or time_ratio < ACUTE_TIME_RATIO_LOW
        or wrong_ratio > ACUTE_WRONG_RATIO
    )

    w_curr = BLEND_W_CURR_ACUTE if is_acute else BLEND_W_CURR_STEADY
    w_hist = BLEND_W_HIST_ACUTE if is_acute else BLEND_W_HIST_STEADY

    blended_time  = current_time  * w_curr + baseline_time  * w_hist
    blended_wrong = current_wrong * w_curr + baseline_wrong * w_hist
    blended_hints = current_hints * w_curr + baseline_hints * w_hist

    # Performance label
    if time_ratio > 1.6:
        perf: PerformanceLabel = "MUCH_SLOWER"
    elif time_ratio > 1.2:
        perf = "SLOWER"
    elif time_ratio >= 0.8:
        perf = "ON_BASELINE"
    elif time_ratio >= 0.5:
        perf = "FASTER"
    else:
        perf = "MUCH_FASTER"

    return BlendedSignals(
        blended_time_sec=blended_time,
        blended_wrong_attempts=blended_wrong,
        blended_hints_used=blended_hints,
        is_acute_deviation=is_acute,
        performance_vs_baseline=perf,
    )
```

---

## Appendix B: Spaced Repetition Intervals

```python
# backend/src/adaptive/spaced_review.py

from datetime import datetime, timezone, timedelta

# Ebbinghaus fixed-interval schedule (v1)
# Index = review_number - 1  (review_number is 1-based in the DB)
SR_INTERVALS_DAYS: list[int] = [1, 3, 7, 14, 30]


def compute_next_due(review_number: int, now: datetime | None = None) -> datetime:
    """
    Compute the due_at datetime for a spaced review.

    Args:
        review_number: 1-based review count (1 = first review after mastery).
        now:           Reference datetime (defaults to UTC now). Provided for testability.

    Returns:
        UTC datetime when the review is due.
        review_number > len(SR_INTERVALS_DAYS) is clamped to the last interval.

    Pure function (when now is provided).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    idx = min(review_number - 1, len(SR_INTERVALS_DAYS) - 1)
    days = SR_INTERVALS_DAYS[idx]
    return now + timedelta(days=days)
```

---

## Appendix C: Next-Card LLM Output Schema

The LLM is instructed to return a single JSON object with the following shape:

```json
{
  "title": "<concise card title string>",
  "content": "<markdown-formatted card body>",
  "questions": [
    {
      "type": "mcq",
      "question": "<question text>",
      "options": ["<option A>", "<option B>", "<option C>", "<option D>"],
      "correct_index": 0,
      "explanation": "<why the answer is correct>"
    },
    {
      "type": "true_false",
      "question": "<statement to evaluate>",
      "correct": true,
      "explanation": "<why this is true or false>"
    }
  ],
  "motivational_note": "<one warm, encouraging sentence tailored to the student's current state>"
}
```

**Pydantic model `NextCardLLMOutput`:**

```python
class McqQuestion(BaseModel):
    type: Literal["mcq"]
    question: str
    options: list[str] = Field(min_length=2, max_length=6)
    correct_index: int = Field(ge=0)
    explanation: str

class TrueFalseQuestion(BaseModel):
    type: Literal["true_false"]
    question: str
    correct: bool
    explanation: str

class NextCardLLMOutput(BaseModel):
    title: str
    content: str
    questions: list[McqQuestion | TrueFalseQuestion] = Field(default_factory=list)
    motivational_note: str

    @field_validator("motivational_note")
    @classmethod
    def note_not_empty(cls, v: str) -> str:
        if not v.strip():
            return "Keep going — every card brings you closer!"
        return v
```

---

## Appendix D: `build_next_card_prompt()` Function Specification

```python
def build_next_card_prompt(
    concept_detail: dict,
    learning_profile: LearningProfile,
    gen_profile: GenerationProfile,
    card_index: int,           # The index of the card being generated (0-based)
    language: str = "en",
    performance_vs_baseline: str = "NO_BASELINE",
) -> tuple[str, str]:
    """
    Build the (system_prompt, user_prompt) for generating a SINGLE adaptive card.

    Differences from build_adaptive_prompt():
      - System prompt emphasises single-card output (not full lesson JSON)
      - JSON schema is simplified to NextCardLLMOutput schema
      - User prompt includes card_index context ("This is card N of the session")
      - performance_vs_baseline is injected to allow tone adjustment
        (e.g. MUCH_SLOWER → extra patient tone; MUCH_FASTER → challenge language)
      - max_paragraph_lines enforced more strictly (single card, not full lesson)

    Returns:
        (system_prompt, user_prompt) tuple of strings.
    """
```

**System prompt sections for single-card generation:**

1. Identity: "You are an expert adaptive math tutor generating a SINGLE practice card."
2. JSON schema (NextCardLLMOutput — see Appendix C)
3. Generation controls (identical to existing `_build_system_prompt()` logic)
4. Performance tone modifier:
   - `MUCH_SLOWER` / `SLOWER`: "The student is taking longer than usual. Be extra patient and supportive in tone. The motivational_note must be warm and encouraging."
   - `MUCH_FASTER` / `FASTER`: "The student is moving quickly. You may increase challenge. The motivational_note can be upbeat and energising."
   - `ON_BASELINE` / `NO_BASELINE`: No additional modifier.
5. Card position context: "This is card number {card_index + 1} in the session. Adjust difficulty accordingly."
6. Motivational note requirement: "The motivational_note field must be exactly ONE sentence — warm, personal, and specific to the content of this card. Do not use generic phrases."

**User prompt sections:**

1. CONCEPT TO TEACH (title, chapter, section, truncated text, LaTeX — identical to existing)
2. STUDENT PROFILE (speed, comprehension, engagement, confidence, recommended next step)
3. PERFORMANCE VS BASELINE: "{performance_vs_baseline}"
4. INSTRUCTION: "Generate exactly ONE card as a JSON object matching the schema. No explanation, no markdown fences."

---

## Key Decisions Requiring Stakeholder Input

1. **`ADAPTIVE_CARD_MODEL` default value:** `gpt-4o-mini` is specified in the DLD for single-card generation. If quality is insufficient for advanced students, this should be `gpt-4o`. Confirm before backend Phase 3 begins.

2. **`ADAPTIVE_CARD_CEILING` value (config constant):** Specified as 8 in the feature brief. Confirm this is intentionally capped at 8 cards of adaptive generation per session, independent of the initial lesson batch size.

3. **`MIN_HISTORY_CARDS` value:** Set to 5 in the blending specification. This means the first 5 cards a student ever completes use pure current signals (no blending). For new students this is the correct default. Confirm this value is acceptable.

4. **Weak-concept tracking (FR-13):** The DLD defers this to a v2 milestone. If it must be in v1, define "failed concept" precisely (e.g., `check_score < 70` on a completed session, or `concept_mastered = false` after session completion) and a separate `weak_concepts` query will need to be added.

5. **`spaced_reviews` unique constraint migration:** Confirm with devops-engineer that a patch Alembic migration is acceptable, or whether the existing migration `e3c02cf4c22e` should be amended. Amending a live migration is risky in production.

6. **Frontend debounce requirement:** The DLD requires the "Next Card" button to be debounced (disabled on click, re-enabled on response). Confirm this is acceptable UX — some students may want to re-read the previous card while the next one loads. Alternative: show a spinner overlay rather than disabling the button.
