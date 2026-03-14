# Detailed Low-Level Design — Enhanced Adaptive Flashcard System

**Feature slug:** `adaptive-flashcard-system`
**Date:** 2026-03-10
**Author:** solution-architect agent
**Status:** Approved for implementation

---

## 1. Component Breakdown

### 1.1 New Module: `backend/src/adaptive/boredom_detector.py`

**Single responsibility:** Scan a plain-text Socratic chat message for boredom signals and autopilot patterns. Returns structured results that the caller converts into LLM prompt injections and `engagement_signal` field values.

**Public interface:**
```python
def detect_boredom_signal(message: str) -> str | None
def detect_autopilot_pattern(recent_messages: list[str]) -> bool
def select_engagement_strategy(
    effective_engagement: list[str],
    ineffective_engagement: list[str],
    engagement_signal: str,
) -> str
```

**Dependencies:** Python stdlib `re` only. No I/O.

---

### 1.2 Modified: `backend/src/adaptive/adaptive_engine.py`

**Changes:**
- `load_student_history()` extended to query new columns: `avg_state_score`, `section_count`, `effective_engagement`, `ineffective_engagement`, `boredom_pattern` from the `students` row.
- `build_blended_analytics()` refactored to call `compute_numeric_state_score()` and use cold-start weights.
- New function `compute_numeric_state_score(speed, comprehension) -> float` added.
- New function `blended_score_to_generate_as(blended_score) -> str` added.
- New function `build_blended_analytics()` signature extended to return `tuple[AnalyticsSummary, float, str]`.

---

### 1.3 Modified: `backend/src/adaptive/prompt_builder.py`

**Changes:**
- `_build_system_prompt()` gains a new optional `blended_state_context: dict | None` parameter. When present, injects a `STUDENT STATE` block.
- `_build_user_prompt()` gains a new optional `coverage_context: dict | None` parameter. When present, injects a `COVERAGE CONTEXT` block.
- `build_adaptive_prompt()` and `build_next_card_prompt()` signatures extended accordingly.

---

### 1.4 Modified: `backend/src/api/teaching_service.py`

**Changes:**
- New private method `_persist_section_complete()` writes `avg_state_score`, `section_count`, `effective_engagement`, `ineffective_engagement` updates to the `students` row.
- Concept tracking state (`concept_index`, `images_used_this_section`) threaded through the card-generation call when the section-complete endpoint provides it.

---

### 1.5 Modified: `backend/src/api/teaching_schemas.py`

**New schemas:**
```
SectionCompleteRequest
SectionCompleteResponse
```

**Modified schemas:**
- `NextCardRequest` gains `engagement_signal: str | None`.

---

### 1.6 Modified: `backend/src/api/teaching_router.py`

**New endpoint:**
```
POST /api/v2/sessions/{session_id}/section-complete
```

---

### 1.7 Modified: `backend/src/config.py`

**New constants:**
```python
ADAPTIVE_COLD_START_SECTION_THRESHOLD: int = 3
ADAPTIVE_COLD_START_CURRENT_WEIGHT: float = 0.8
ADAPTIVE_COLD_START_HISTORY_WEIGHT: float = 0.2
ADAPTIVE_STATE_EMA_ALPHA: float = 0.3
BOREDOM_SIGNAL_COOLDOWN_CARDS: int = 5
BOREDOM_AUTOPILOT_WINDOW: int = 4
BOREDOM_AUTOPILOT_SIMILARITY_THRESHOLD: float = 0.85
```

---

### 1.8 Modified: `frontend/src/components/learning/SocraticChat.jsx`

**Changes:**
- After every user message submission, run a lightweight client-side keyword check.
- If boredom keywords detected (`boring`, `already know`, `skip`, `too easy`, `going too slow`), set a React state flag `boredomDetected = true`.
- Pass `engagement_signal: "BORED_TEXT"` in the next `complete-card` API call via SessionContext.

---

### 1.9 Modified: `frontend/src/context/SessionContext.jsx`

**Changes:**
- New action type `SECTION_COMPLETE` triggers call to `sessions.sectionComplete()`.
- `goToNextCard()` checks if `currentCardIndex === cards.length - 1` and dispatches `SECTION_COMPLETE` when appropriate.
- New state field `pendingEngagementSignal: string | null` cleared after each `complete-card` call.

---

### 1.10 Modified: `frontend/src/api/sessions.js`

**New function:**
```javascript
export const sectionComplete = (sessionId, payload) =>
  apiClient.post(`/api/v2/sessions/${sessionId}/section-complete`, payload);
```

**Modified function:**
- `completeCard()` accepts optional `engagement_signal` in its payload.

---

## 2. Data Design

### 2.1 Database Schema Changes

#### `students` table — 11 new columns

All 11 columns are already present in `backend/src/db/models.py` (added in a prior session). The Alembic migration `005_add_adaptive_history_columns` is needed to add them to the live database.

```sql
-- Migration: 005_add_adaptive_history_columns
ALTER TABLE students
  ADD COLUMN IF NOT EXISTS section_count          INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS overall_accuracy_rate  FLOAT   NOT NULL DEFAULT 0.5,
  ADD COLUMN IF NOT EXISTS preferred_analogy_style VARCHAR(50),
  ADD COLUMN IF NOT EXISTS boredom_pattern        VARCHAR(20),
  ADD COLUMN IF NOT EXISTS frustration_tolerance  VARCHAR(20) DEFAULT 'medium',
  ADD COLUMN IF NOT EXISTS recovery_speed         VARCHAR(20) DEFAULT 'normal',
  ADD COLUMN IF NOT EXISTS avg_state_score        FLOAT   NOT NULL DEFAULT 2.0,
  ADD COLUMN IF NOT EXISTS effective_analogies    JSONB   NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS effective_engagement   JSONB   NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS ineffective_engagement JSONB   NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS state_distribution     JSONB   NOT NULL
    DEFAULT '{"struggling": 0, "normal": 0, "fast": 0}'::jsonb;
```

**Column semantics:**

| Column | Type | Purpose |
|--------|------|---------|
| `section_count` | INTEGER | Count of fully completed sections; used for cold-start weight selection |
| `overall_accuracy_rate` | FLOAT | Rolling accuracy across all completed cards; `correct_cards / total_cards` |
| `preferred_analogy_style` | VARCHAR(50) | Most effective analogy type ("sports", "cooking", "engineering") — populated after 3+ effective uses |
| `boredom_pattern` | VARCHAR(20) | Whether student tends to signal boredom: "FREQUENT", "OCCASIONAL", "RARE", NULL |
| `frustration_tolerance` | VARCHAR(20) | "low", "medium", "high" — derived from recovery speed after STRUGGLING episodes |
| `recovery_speed` | VARCHAR(20) | "fast", "normal", "slow" — how quickly student exits STRUGGLING after support |
| `avg_state_score` | FLOAT | Exponential moving average of numeric state scores; updated per section-complete; used in cold-start blend |
| `effective_analogies` | JSONB | Array of analogy type strings that correlated with score improvement |
| `effective_engagement` | JSONB | Array of strategy strings (GAMIFY, CHALLENGE, STORY) that reduced boredom signal recurrence |
| `ineffective_engagement` | JSONB | Array of strategy strings that did NOT reduce boredom signal; selector avoids these |
| `state_distribution` | JSONB | Object tracking `{struggling: N, normal: N, fast: N}` count of section outcomes |

---

#### `card_interactions` table — 3 new columns

```sql
ALTER TABLE card_interactions
  ADD COLUMN IF NOT EXISTS engagement_signal  VARCHAR(50),
  ADD COLUMN IF NOT EXISTS strategy_applied   VARCHAR(50),
  ADD COLUMN IF NOT EXISTS strategy_effective BOOLEAN;
```

| Column | Type | Purpose |
|--------|------|---------|
| `engagement_signal` | VARCHAR(50) | Signal that triggered engagement intervention: "BORED_TIME", "BORED_TEXT", "AUTOPILOT", NULL |
| `strategy_applied` | VARCHAR(50) | Which strategy was injected: "GAMIFY", "CHALLENGE", "STORY", "BREAK_SUGGESTION", NULL |
| `strategy_effective` | BOOLEAN | True if next card's `engagement_signal` was NULL after strategy applied; set by section-complete call |

---

### 2.2 Data Models (Python / Pydantic)

```python
# backend/src/api/teaching_schemas.py (additions)

class SectionCompleteRequest(BaseModel):
    """
    Payload sent by the frontend when the student completes the last card
    in a section (i.e., the pre-generated starter-pack section).

    Fields:
        blended_state_label:  The generate-as label computed by the backend
                              on the last complete-card call, echoed by frontend.
        blended_state_score:  The numeric blended score (0.0–4.0), echoed by frontend.
        concept_index:        Zero-based index of this section within the current session.
        total_concepts:       Total number of sections in this session.
        images_used:          Count of images shown to the student in this section.
        engagement_signal:    Boredom signal detected during this section, if any.
        strategy_applied:     Engagement strategy that was injected, if any.
        strategy_effective:   True if student did not re-signal boredom after strategy.
        correct_card_count:   Number of MCQs answered correctly in this section.
        total_card_count:     Total cards seen in this section.
    """
    blended_state_label: str
    blended_state_score: float
    concept_index: int = Field(ge=0)
    total_concepts: int = Field(ge=1)
    images_used: int = Field(ge=0, default=0)
    engagement_signal: str | None = None
    strategy_applied: str | None = None
    strategy_effective: bool | None = None
    correct_card_count: int = Field(ge=0, default=0)
    total_card_count: int = Field(ge=1, default=1)


class SectionCompleteResponse(BaseModel):
    """
    Response after persisting section-complete data.

    Fields:
        updated_avg_state_score: New EMA value after this section.
        updated_section_count:   New section count after increment.
        cold_start_active:       True if student is still in cold-start regime.
        next_weights:            The (current_weight, history_weight) pair that
                                 will be used on the NEXT section.
    """
    updated_avg_state_score: float
    updated_section_count: int
    cold_start_active: bool
    next_weights: tuple[float, float]
```

---

### 2.3 Data Flow Diagrams

#### Card generation with numeric blending

```
Frontend CardBehaviorSignals
  │  (time_on_card_sec, wrong_attempts, hints_used, idle_triggers,
  │   difficulty_bias, engagement_signal)
  ▼
teaching_router.py  →  complete_card()
  │
  ├── load_student_history(student_id, concept_id, db)
  │     Reads: students.avg_state_score, students.section_count,
  │            students.effective_engagement, students.ineffective_engagement
  │     Returns: history dict (existing fields + 5 new fields)
  │
  ├── build_blended_analytics(current_signals, history, concept_id, student_id)
  │     NEW:  compute_numeric_state_score(speed, comprehension) → float
  │     NEW:  select cold-start vs normal weights via section_count
  │     NEW:  blend numeric scores: blended = curr_score * cw + hist_avg * hw
  │     NEW:  blended_score_to_generate_as(blended) → label string
  │     Returns: (AnalyticsSummary, blended_score: float, generate_as: str)
  │
  ├── build_learning_profile(analytics, has_unmet_prereq)
  │     UNCHANGED — still classifies to string labels
  │
  ├── If engagement_signal present:
  │     select_engagement_strategy(effective, ineffective, signal) → strategy
  │
  ├── build_next_card_prompt(
  │     ...,
  │     blended_state_context={score, generate_as, hist_avg, cw, hw},
  │     coverage_context={concept_index, concepts_remaining, images_used},
  │     engagement_strategy=strategy
  │   )
  │
  └── _call_llm() → card dict
```

#### Section-complete persistence

```
Frontend SessionContext (SECTION_COMPLETE action)
  │  (SectionCompleteRequest payload)
  ▼
teaching_router.py  →  section_complete()
  │
  ├── Fetch students row (SELECT ... FOR UPDATE)
  ├── Compute new avg_state_score:
  │     new_avg = alpha * section_score + (1 - alpha) * old_avg
  │     where alpha = ADAPTIVE_STATE_EMA_ALPHA (0.3)
  ├── Increment section_count
  ├── Update state_distribution: {struggling, normal, fast} counter
  ├── If strategy_effective=True: append strategy to effective_engagement
  ├── If strategy_effective=False: append strategy to ineffective_engagement
  ├── Overall_accuracy_rate: rolling average of correct_card_count / total_card_count
  └── Commit, return SectionCompleteResponse
```

---

### 2.4 Numeric State Score Scale

The scale maps the 9 (speed × comprehension) cells to a float in [0.0, 4.0]:

```
compute_numeric_state_score(speed, comprehension) -> float

Mapping table:
  SLOW   × STRUGGLING → 0.0   (most scaffolding needed)
  SLOW   × OK         → 0.5
  SLOW   × STRONG     → 1.0
  NORMAL × STRUGGLING → 1.0
  NORMAL × OK         → 2.0   (baseline / average student)
  NORMAL × STRONG     → 2.5
  FAST   × STRUGGLING → 2.0
  FAST   × OK         → 3.0
  FAST   × STRONG     → 4.0   (least scaffolding needed)

Implementation note:
  FAST × STRUGGLING = 2.0 (same as NORMAL × OK) because a fast but struggling
  student is overconfident; they need normal scaffolding.
```

```python
# Pure function — no I/O
_NUMERIC_STATE_MAP: dict[tuple[str, str], float] = {
    ("SLOW",   "STRUGGLING"): 0.0,
    ("SLOW",   "OK"):         0.5,
    ("SLOW",   "STRONG"):     1.0,
    ("NORMAL", "STRUGGLING"): 1.0,
    ("NORMAL", "OK"):         2.0,
    ("NORMAL", "STRONG"):     2.5,
    ("FAST",   "STRUGGLING"): 2.0,
    ("FAST",   "OK"):         3.0,
    ("FAST",   "STRONG"):     4.0,
}

def compute_numeric_state_score(speed: str, comprehension: str) -> float:
    """
    Map (speed, comprehension) label pair to a numeric state score in [0.0, 4.0].

    The scale is designed so that 2.0 = an average NORMAL/OK student.
    Values below 2.0 indicate increasing scaffolding need; above 2.0 indicate
    capacity for reduced scaffolding.

    Args:
        speed:         One of "SLOW", "NORMAL", "FAST"
        comprehension: One of "STRUGGLING", "OK", "STRONG"

    Returns:
        Float in [0.0, 4.0].

    Raises:
        KeyError: If (speed, comprehension) is not in the lookup table.
                  This is intentional — callers must validate inputs before calling.
    """
    return _NUMERIC_STATE_MAP[(speed, comprehension)]
```

```python
def blended_score_to_generate_as(blended_score: float) -> str:
    """
    Map a blended numeric score back to a generate-as label for prompt injection.

    Thresholds (mid-points of the 5-cell range):
      score < 1.25  → "SLOW_STRUGGLING"
      score < 1.75  → "SLOW_OK"
      score < 2.25  → "NORMAL_OK"  (baseline)
      score < 2.75  → "NORMAL_STRONG"
      score >= 2.75 → "FAST_STRONG"

    These labels are ONLY used in the STUDENT STATE prompt block.
    They do NOT replace the string labels used in GenerationProfile lookup.

    Args:
        blended_score: Float in [0.0, 4.0] from build_blended_analytics().

    Returns:
        A human-readable label string for LLM prompt injection.
    """
    if blended_score < 1.25:
        return "SLOW_STRUGGLING"
    if blended_score < 1.75:
        return "SLOW_OK"
    if blended_score < 2.25:
        return "NORMAL_OK"
    if blended_score < 2.75:
        return "NORMAL_STRONG"
    return "FAST_STRONG"
```

---

### 2.5 Caching Strategy

No caching layer changes. The `students` row is fetched fresh on every `complete-card` call inside `load_student_history()`. This is acceptable because:
- The call is already making 5 DB queries for history aggregation
- The `students` row fetch adds one cheap primary-key lookup
- The section_count / avg_state_score values must be current to avoid stale cold-start decisions

---

### 2.6 Data Retention

No changes to existing retention policy. The `card_interactions` rows have no TTL. The three new columns (`engagement_signal`, `strategy_applied`, `strategy_effective`) are nullable and do not affect existing row lifecycle.

---

## 3. API Design

### 3.1 New Endpoint: `POST /api/v2/sessions/{session_id}/section-complete`

**Purpose:** Persist section-level outcomes and update student adaptive history.

**Auth:** `X-API-Key` header (same `verify_api_key` dependency as all v2 endpoints).

**Request:**
```
POST /api/v2/sessions/{session_id}/section-complete
Content-Type: application/json
X-API-Key: {VITE_API_SECRET_KEY}

{
  "blended_state_label": "NORMAL_OK",
  "blended_state_score": 2.1,
  "concept_index": 0,
  "total_concepts": 3,
  "images_used": 2,
  "engagement_signal": "BORED_TEXT",
  "strategy_applied": "GAMIFY",
  "strategy_effective": true,
  "correct_card_count": 7,
  "total_card_count": 9
}
```

**Response (200 OK):**
```json
{
  "updated_avg_state_score": 2.13,
  "updated_section_count": 4,
  "cold_start_active": false,
  "next_weights": [0.6, 0.4]
}
```

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid X-API-Key |
| 404 | `session_id` not found in `teaching_sessions` |
| 422 | Request body fails Pydantic validation |
| 500 | DB error during update; logged with `logger.exception()` |

**Idempotency:** The endpoint is NOT fully idempotent (calling it twice increments `section_count` twice). The frontend must ensure it is called exactly once per section boundary. A guard in `SessionContext.jsx` prevents double-dispatch using a `sectionCompleteSent` boolean ref.

---

### 3.2 Modified Endpoint: `POST /api/v2/sessions/{session_id}/complete-card`

**Change:** `engagement_signal` added as an optional field in the request body.

**New request field:**
```json
{
  "card_index": 3,
  "time_on_card_sec": 45.0,
  "wrong_attempts": 1,
  "hints_used": 0,
  "idle_triggers": 0,
  "engagement_signal": "BORED_TEXT"
}
```

**Response unchanged** — `NextCardResponse` schema is unmodified.

---

### 3.3 Versioning Strategy

All new endpoints follow the existing `/api/v2/` prefix convention. No version bump is required for the `complete-card` change because the new `engagement_signal` field is optional and defaults to `None`. Existing frontend clients that do not send it receive unchanged behavior.

---

### 3.4 Error Handling Conventions

Following the existing codebase pattern:
- All endpoint handlers use `try/except Exception` with `logger.exception()` before re-raising as `HTTPException(500)`.
- Pydantic validation errors return 422 automatically via FastAPI.
- DB constraint violations (e.g., duplicate section-complete calls) are caught by the optimistic `section_count` check and logged as warnings, not 500s.

---

## 4. Sequence Diagrams

### 4.1 Happy Path: Card Completion with Boredom Signal

```
Frontend (SocraticChat.jsx)           Backend (teaching_router.py)
        │                                      │
        │ 1. User types "this is boring"       │
        │    boredomDetected = true            │
        │    pendingEngagementSignal =         │
        │      "BORED_TEXT"                    │
        │                                      │
        │ 2. POST /complete-card               │
        │    {card_index: 3,                   │
        │     engagement_signal: "BORED_TEXT"} │
        │─────────────────────────────────────►│
        │                                      │ 3. load_student_history()
        │                                      │    reads avg_state_score=2.1,
        │                                      │    section_count=4,
        │                                      │    effective_engagement=[],
        │                                      │    ineffective_engagement=[]
        │                                      │
        │                                      │ 4. compute_numeric_state_score(
        │                                      │      "NORMAL", "OK") → 2.0
        │                                      │
        │                                      │ 5. cold_start? section_count >= 3
        │                                      │    cw=0.6, hw=0.4
        │                                      │
        │                                      │ 6. blended = 2.0*0.6 + 2.1*0.4
        │                                      │           = 2.04
        │                                      │    generate_as = "NORMAL_OK"
        │                                      │
        │                                      │ 7. select_engagement_strategy(
        │                                      │      [], [], "BORED_TEXT")
        │                                      │    → "GAMIFY"
        │                                      │
        │                                      │ 8. build_next_card_prompt(
        │                                      │      blended_state_context={
        │                                      │        score: 2.04,
        │                                      │        generate_as: "NORMAL_OK",
        │                                      │        hist_avg: 2.1,
        │                                      │        cw: 0.6, hw: 0.4
        │                                      │      },
        │                                      │      engagement_strategy="GAMIFY"
        │                                      │    )
        │                                      │
        │                                      │ 9. LLM call → card dict
        │                                      │
        │◄─────────────────────────────────────│ 10. NextCardResponse
        │    {card: {...},                     │
        │     adaptation_applied: "CONTINUE    │
        │       [engagement: GAMIFY]"}         │

```

### 4.2 Happy Path: Section Complete

```
Frontend (SessionContext.jsx)         Backend (teaching_router.py)
        │                                      │
        │ 1. currentCardIndex === cards.length-1│
        │    and user clicks Next              │
        │                                      │
        │ 2. Dispatch SECTION_COMPLETE         │
        │    → sessions.sectionComplete()      │
        │                                      │
        │ 3. POST /section-complete            │
        │    {blended_state_score: 2.04,       │
        │     blended_state_label: "NORMAL_OK",│
        │     concept_index: 0,                │
        │     total_concepts: 3,               │
        │     images_used: 2,                  │
        │     engagement_signal: "BORED_TEXT", │
        │     strategy_applied: "GAMIFY",      │
        │     strategy_effective: true,        │
        │     correct_card_count: 7,           │
        │     total_card_count: 9}             │
        │─────────────────────────────────────►│
        │                                      │ 4. SELECT students WHERE id = :sid
        │                                      │    FOR UPDATE
        │                                      │
        │                                      │ 5. new_avg = 0.3 * 2.04 +
        │                                      │              0.7 * 2.1 = 2.082
        │                                      │
        │                                      │ 6. section_count += 1 → 5
        │                                      │
        │                                      │ 7. state_distribution.normal += 1
        │                                      │
        │                                      │ 8. strategy_effective=True →
        │                                      │    effective_engagement.append(
        │                                      │      "GAMIFY")
        │                                      │
        │                                      │ 9. overall_accuracy_rate =
        │                                      │    rolling_avg(7/9=0.778)
        │                                      │
        │                                      │ 10. UPDATE students SET
        │                                      │     avg_state_score=2.082,
        │                                      │     section_count=5,
        │                                      │     ...
        │                                      │
        │◄─────────────────────────────────────│ 11. SectionCompleteResponse
        │    {updated_avg_state_score: 2.082,  │
        │     updated_section_count: 5,        │
        │     cold_start_active: false,        │
        │     next_weights: [0.6, 0.4]}        │

```

### 4.3 Cold-Start Student: First Section Complete

```
Backend load_student_history() result:
  section_count = 0           ← new student
  avg_state_score = 2.0       ← server default

build_blended_analytics():
  section_count < ADAPTIVE_COLD_START_SECTION_THRESHOLD (3)
  → cw = 0.8, hw = 0.2        ← cold-start weights
  current_score = compute_numeric_state_score("SLOW", "STRUGGLING") = 0.0
  blended = 0.0 * 0.8 + 2.0 * 0.2 = 0.4
  generate_as = "SLOW_STRUGGLING"

After section-complete with correct_card_count=3, total_card_count=9:
  new_avg = 0.3 * 0.4 + 0.7 * 2.0 = 1.52
  section_count = 1
  cold_start_active = True (1 < 3)
  next_weights = [0.8, 0.2]
```

### 4.4 Error Path: Boredom Detector Exception

```
Backend generate_next_card():
  │
  ├── engagement_signal = "BORED_TEXT" received from request
  │
  ├── try:
  │     strategy = select_engagement_strategy(
  │       effective_engagement, ineffective_engagement, "BORED_TEXT"
  │     )
  │   except Exception as exc:
  │     logger.warning("boredom_strategy_select_failed: %s (defaulting to None)", exc)
  │     strategy = None
  │
  └── build_next_card_prompt(..., engagement_strategy=strategy)
      → If strategy is None, no engagement block injected into prompt
      → Card generated normally
```

---

## 5. Integration Design

### 5.1 Backend Internal Integration

All adaptive module functions follow the existing call chain. No new async boundaries or message queues are introduced.

```
teaching_router.py
  └─► adaptive_engine.generate_next_card()
        ├─► adaptive_engine.load_student_history()   [DB async]
        ├─► adaptive_engine.compute_numeric_state_score()  [pure]
        ├─► adaptive_engine.build_blended_analytics()      [pure]
        ├─► profile_builder.build_learning_profile()       [pure]
        ├─► boredom_detector.select_engagement_strategy()  [pure]
        └─► prompt_builder.build_next_card_prompt()        [pure]
              └─► _call_llm()  [OpenAI async]
```

### 5.2 Frontend-Backend Contract

The frontend's `SessionContext.jsx` is the state machine for section boundaries. It owns:
- `currentCardIndex` (integer)
- `cards` (array)
- `boredomDetected` (boolean, local to session)
- `sectionCompleteSent` (boolean ref, prevents double-send)

The contract is: when `currentCardIndex === cards.length - 1` and the user advances, `SessionContext` dispatches `SECTION_COMPLETE`. The handler calls `sessions.sectionComplete()` exactly once, then resets `sectionCompleteSent = false` for the next section.

### 5.3 Retry Logic

The section-complete endpoint uses the same retry posture as all existing DB write endpoints: no retry on the client side. If the call fails (network error), `SessionContext` logs the error via `console.error` (per the existing `empty .catch()` fix in CLAUDE.md) and continues. The `avg_state_score` is not critical-path; a missed section-complete degrades personalization for the next section but does not block learning.

---

## 6. Security Design

### 6.1 Authentication and Authorization

No changes to auth model. The new `POST /section-complete` endpoint uses the same `verify_api_key` FastAPI dependency as all `/api/v2/` endpoints. The `session_id` in the path is validated against the `teaching_sessions` table; requests for sessions belonging to other students are rejected at the DB query level (the query joins on `student_id` from the session).

### 6.2 Input Validation

- `SectionCompleteRequest` is a Pydantic v2 model. All fields have explicit types, `ge`/`le` validators, and defaults.
- `engagement_signal` is `str | None`; if provided, it is length-capped at 50 characters by the DB column constraint (`VARCHAR(50)`). FastAPI will reject values longer than 50 with a 422 before they reach the DB.
- `blended_state_score` is validated as a float in `[0.0, 4.0]` via a `ge=0.0, le=4.0` field validator.
- `strategy_applied` values are checked against the four valid strings via a `Literal` type in the Pydantic schema.

### 6.3 Data Encryption

No changes. All data in transit uses HTTPS (reverse proxy termination) and all data at rest uses PostgreSQL default storage encryption where configured at the infrastructure level.

### 6.4 Secrets Management

No new secrets introduced. The existing `OPENAI_API_KEY` and `API_SECRET_KEY` environment variables are unchanged.

### 6.5 Prompt Injection Guard

The boredom detector receives raw user-typed text. It uses `re.search()` with literal keyword patterns, not dynamic pattern construction, so user input cannot alter the detection logic. The detected signal string (`"BORED_TEXT"`, `"AUTOPILOT"`, `"BORED_TIME"`) is a server-defined enum value, never the raw user text, so it cannot be injected into the LLM prompt as user content.

---

## 7. Observability Design

### 7.1 Structured Logging

All new functions emit structured key=value log lines following the existing convention in `adaptive_engine.py`.

| Event | Level | Message format |
|-------|-------|---------------|
| Numeric score computed | INFO | `numeric_state_score: speed=%s comprehension=%s score=%.2f` |
| Blending weights selected | INFO | `blend_weights: section_count=%d cold_start=%s cw=%.2f hw=%.2f` |
| Blended score result | INFO | `blended_score: score=%.2f generate_as=%s hist_avg=%.2f` |
| Boredom signal detected | INFO | `boredom_detected: signal=%s message_len=%d` |
| Autopilot pattern detected | INFO | `autopilot_detected: window=%d similarity=%.2f` |
| Strategy selected | INFO | `engagement_strategy_selected: signal=%s strategy=%s avoided=%s` |
| Strategy failed | WARNING | `boredom_strategy_select_failed: error=%s (defaulting to None)` |
| Section complete persisted | INFO | `section_complete: student_id=%s session_id=%s new_avg=%.2f section_count=%d` |
| Section complete DB error | ERROR | `section_complete_db_error: student_id=%s session_id=%s` (+ `logger.exception`) |

### 7.2 Key Metrics (for future dashboard)

| Metric | Derivation |
|--------|-----------|
| Cold-start graduation rate | `section_count` crossing 3; count of students per day |
| Boredom signal frequency | `COUNT(card_interactions WHERE engagement_signal IS NOT NULL) / day` |
| Strategy effectiveness rate | `COUNT(strategy_effective=True) / COUNT(strategy_effective IS NOT NULL)` |
| avg_state_score distribution | Histogram of `students.avg_state_score` at time of query |
| Coverage context utilization | Log line count for `COVERAGE CONTEXT injected` vs total card generation calls |

### 7.3 Alerting

No new alerts are required beyond the existing patterns. The section-complete endpoint failure path logs at ERROR level, which is captured by the existing log aggregation setup. If error rate on `/section-complete` exceeds 1% of calls in a 5-minute window, this should surface via the existing log-based alerting.

---

## 8. Error Handling and Resilience

### 8.1 Boredom Detector Isolation

```python
# In adaptive_engine.generate_next_card()

engagement_strategy: str | None = None
if engagement_signal:
    try:
        engagement_strategy = select_engagement_strategy(
            history.get("effective_engagement", []),
            history.get("ineffective_engagement", []),
            engagement_signal,
        )
    except Exception as exc:
        logger.warning(
            "boredom_strategy_select_failed: error=%s (defaulting to None)", exc
        )
        # engagement_strategy stays None — prompt builder skips the block
```

### 8.2 Section-Complete Double-Call Protection

Frontend side:
```javascript
// SessionContext.jsx
const sectionCompleteSentRef = useRef(false);

const dispatchSectionComplete = useCallback(async (payload) => {
  if (sectionCompleteSentRef.current) return; // guard
  sectionCompleteSentRef.current = true;
  try {
    await sessions.sectionComplete(state.sessionId, payload);
  } catch (err) {
    console.error('section_complete_failed:', err);
  }
  // Note: do NOT reset sectionCompleteSentRef until next section loads
}, [state.sessionId]);
```

Backend side: The `_persist_section_complete()` function fetches the student row with `SELECT ... FOR UPDATE` inside the same transaction as the UPDATE, ensuring atomicity under concurrent requests.

### 8.3 load_student_history() Missing Columns

During the migration window (old DB schema + new code deployed), `load_student_history()` may encounter rows without the new columns. The function uses `.get()` with safe defaults on all new columns:

```python
history["avg_state_score"] = getattr(student_row, "avg_state_score", 2.0)
history["section_count"] = getattr(student_row, "section_count", 0)
history["effective_engagement"] = getattr(student_row, "effective_engagement", []) or []
history["ineffective_engagement"] = getattr(student_row, "ineffective_engagement", []) or []
```

This ensures zero-downtime deployment: the new code works correctly before and after the migration runs.

### 8.4 Retry Policy

No new retry policies. The `_call_llm()` function already retries 3 times with exponential back-off. The section-complete endpoint is a DB write with no retry — if it fails, the adaptive history is slightly stale for one section but no data is corrupted.

---

## 9. Testing Strategy

### 9.1 Unit Tests (Pure Functions — No Mocks)

All new pure functions must have 100% branch coverage.

**File:** `backend/tests/test_adaptive_numeric_scoring.py`

| Test | Function | Scenario |
|------|----------|----------|
| `test_numeric_score_all_9_cells` | `compute_numeric_state_score` | All 9 (speed, comprehension) pairs produce expected floats |
| `test_numeric_score_invalid_key` | `compute_numeric_state_score` | `("INVALID", "OK")` raises `KeyError` |
| `test_blended_score_boundaries` | `blended_score_to_generate_as` | Scores 0.0, 1.24, 1.25, 1.74, 1.75, 2.24, 2.25, 2.74, 2.75, 4.0 map to correct labels |
| `test_cold_start_weights` | `build_blended_analytics` | section_count=0 → cw=0.8; section_count=3 → cw=0.6 |
| `test_normal_weights` | `build_blended_analytics` | section_count>=3 → cw=0.6, hw=0.4 |
| `test_blended_math` | `build_blended_analytics` | Verify actual blended score arithmetic |

**File:** `backend/tests/test_boredom_detector.py`

| Test | Function | Scenario |
|------|----------|----------|
| `test_detect_bored_explicit` | `detect_boredom_signal` | "this is boring" → `"BORED_TEXT"` |
| `test_detect_already_know` | `detect_boredom_signal` | "I already know this" → `"BORED_TEXT"` |
| `test_detect_too_easy` | `detect_boredom_signal` | "too easy for me" → `"BORED_TEXT"` |
| `test_detect_no_signal` | `detect_boredom_signal` | "what is the answer?" → `None` |
| `test_detect_case_insensitive` | `detect_boredom_signal` | "THIS IS BORING" → `"BORED_TEXT"` |
| `test_autopilot_4_similar` | `detect_autopilot_pattern` | 4 identical one-word answers → `True` |
| `test_autopilot_varied` | `detect_autopilot_pattern` | 4 varied answers → `False` |
| `test_autopilot_too_few` | `detect_autopilot_pattern` | fewer than 4 messages → `False` |
| `test_strategy_avoids_ineffective` | `select_engagement_strategy` | ineffective=["GAMIFY"] → does not return "GAMIFY" |
| `test_strategy_all_ineffective` | `select_engagement_strategy` | all 4 strategies in ineffective → returns "BREAK_SUGGESTION" as fallback |
| `test_strategy_prefers_effective` | `select_engagement_strategy` | effective=["CHALLENGE"] → returns "CHALLENGE" first |

### 9.2 Integration Tests (DB-Touching Functions)

**File:** `backend/tests/test_section_complete_endpoint.py`

Uses the existing `AsyncSession` fixture pattern from `conftest.py`.

| Test | Scenario |
|------|----------|
| `test_section_complete_first_call` | POST section-complete for student with section_count=0; verify avg_state_score and section_count updated correctly |
| `test_section_complete_graduates_cold_start` | After 3 calls, `cold_start_active` flips to False |
| `test_section_complete_strategy_effective_true` | `strategy_effective=True` → GAMIFY appended to `effective_engagement` |
| `test_section_complete_strategy_effective_false` | `strategy_effective=False` → GAMIFY appended to `ineffective_engagement` |
| `test_section_complete_invalid_session` | Non-existent session_id → 404 |
| `test_section_complete_missing_auth` | No X-API-Key → 401 |
| `test_load_student_history_new_columns` | After migration, new columns are returned with correct defaults |

### 9.3 Regression Tests

Run the full existing test suite after each phase:
```bash
pytest backend/tests/ -v --tb=short
```
Target: all 93 pre-existing tests green. No test may be deleted or have its assertion relaxed to accommodate new behavior.

### 9.4 Contract Tests

The `SectionCompleteRequest` Pydantic model acts as the contract for the frontend-backend interface. The `test_section_complete_endpoint.py` integration tests serve as contract tests by sending valid and invalid payloads directly to the endpoint.

### 9.5 Performance Tests

The section-complete endpoint must complete in < 200 ms p95 under 10 concurrent requests. This is verified with a locust or httpx-async benchmark in the CI pipeline (setup by devops-engineer).

---

## Key Decisions Requiring Stakeholder Input

1. **`blended_score_to_generate_as()` threshold boundaries:** The midpoints (1.25, 1.75, 2.25, 2.75) are architectural estimates. Should these be tuned based on actual student data distributions after launch? If so, a config constant per threshold is needed.

2. **Autopilot similarity metric:** The current design compares recent messages using `SequenceMatcher.ratio()` from Python's `difflib`. Should a more robust approach (e.g., character n-gram similarity) be used, at the cost of adding a dependency?

3. **EMA alpha (0.3):** The exponential moving average weight for `avg_state_score` is set to 0.3 (30% current, 70% history). This gives slow adaptation. A higher value (0.5) reacts faster but is more volatile. The product team should validate this with pilot data.

4. **Section-complete timing:** Should `section-complete` be called immediately when the last card is completed, or after the student navigates to the next section view? The current design fires on card completion. If the student closes the browser before navigating, the call is never made.
