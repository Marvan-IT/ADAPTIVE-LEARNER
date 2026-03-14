# Detailed Low-Level Design — Hybrid Rolling Adaptive Card Generation

**Feature slug:** `hybrid-adaptive-cards`
**Author:** Solution Architect
**Date:** 2026-03-14
**Status:** Approved for implementation

---

## 1. Component Breakdown

### 1.1 Backend Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `generate_cards_starter_pack()` | `teaching_service.py` | Generates cards for first 2 sub-sections only; stores `concepts_queue` in `presentation_text`; returns `has_more_concepts` |
| `generate_next_section_cards()` | `teaching_service.py` (NEW) | Pops one sub-section from `concepts_queue`; calls `_generate_cards_single()`; updates stored queue; returns cards + `has_more_concepts` |
| `_generate_cards_single()` | `teaching_service.py` | Unchanged core LLM call; accepts `max_tokens` param; receives raised per-section floor constants |
| `_stamp_section_index()` | `teaching_service.py` (NEW, private) | Stamps integer `_section_index` on every card dict after generation |
| `cards` endpoint | `teaching_router.py` | `POST /api/v2/sessions/{id}/cards` — calls `generate_cards_starter_pack()` |
| `next-section-cards` endpoint | `teaching_router.py` (NEW) | `POST /api/v2/sessions/{id}/next-section-cards` — calls `generate_next_section_cards()` |
| `adaptive_router.py` | `adaptive_router.py` | Remove `_ADAPTIVE_CARD_CEILING = 20` |
| `prompts.py` | `prompts.py` | Add `question2` field to card JSON schema in `build_cards_system_prompt()` + dual-MCQ instruction |
| `teaching_schemas.py` | `teaching_schemas.py` | Add `question2: CardMCQ | None` to `LessonCard`; extend `CardsResponse`; add two new schemas |
| `config.py` | `config.py` | Add `STARTER_PACK_INITIAL_SECTIONS = 2`; raise per-section floor constants |

### 1.2 Frontend Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `getNextSectionCards()` | `frontend/src/api/sessions.js` | New Axios wrapper for `POST /next-section-cards` |
| `sessionReducer` | `SessionContext.jsx` | New `APPEND_CARDS` action; remove `MAX_ADAPTIVE_CARDS`; add `hasMoreConcepts` state field |
| `goToNextCard()` | `SessionContext.jsx` | Rewritten with 3-case logic (Case A / Case B / Case D) |
| `CardLearningView.jsx` | `CardLearningView.jsx` | `isLastCard` updated; `question2` swap logic; section progress indicator |
| Locale files | `frontend/src/locales/*.json` (13 files) | Add `conceptsProgress` key |

---

## 2. Data Design

### 2.1 `presentation_text` JSON — Version 11 Format

The `teaching_sessions.presentation_text` TEXT column stores a JSON blob. Version 11 introduces `concepts_queue` and `total_sections`.

```json
{
  "version": 11,
  "presentation": "<full markdown presentation text>",
  "cached_cards": [
    {
      "index": 0,
      "_section_index": 0,
      "card_type": "TEACH",
      "title": "What is a whole number?",
      "content": "...",
      "question": {
        "text": "Which of the following is a whole number?",
        "options": ["1.5", "3", "-2", "2/3"],
        "correct_index": 1,
        "explanation": "3 is a whole number because...",
        "difficulty": "MEDIUM"
      },
      "question2": {
        "text": "Which set contains ONLY whole numbers?",
        "options": ["{0, 1, 2}", "{0, 0.5, 1}", "{-1, 0, 1}", "{1/2, 1, 2}"],
        "correct_index": 0,
        "explanation": "The set {0, 1, 2} contains only whole numbers.",
        "difficulty": "MEDIUM"
      },
      "images": [],
      "difficulty": 3
    }
  ],
  "concepts_queue": ["PREALG.C1.S1.SEC3", "PREALG.C1.S1.SEC4", "PREALG.C1.S1.SEC5"],
  "total_sections": 5,
  "generated_sections": ["PREALG.C1.S1.SEC1", "PREALG.C1.S1.SEC2"]
}
```

**Field semantics:**

| Field | Type | Description |
|-------|------|-------------|
| `version` | int | Must equal 11; lower versions trigger full regeneration |
| `presentation` | str | Full markdown presentation text (unchanged) |
| `cached_cards` | list[dict] | All cards generated so far across all sections |
| `concepts_queue` | list[str] | Sub-section IDs not yet generated; ordered; mutated by each rolling fetch |
| `total_sections` | int | Total sub-section count for the concept (constant after starter pack) |
| `generated_sections` | list[str] | Sub-section IDs already generated (for idempotency check) |

**Version compatibility:**

| Version | Handling |
|---------|---------|
| `< 11` | Cache miss — regenerate starter pack; old `cached_cards` discarded |
| `== 11` | Cache hit — use `cached_cards` and `concepts_queue` as-is |
| `> 11` | Future version — treated as cache hit (forward-compatible) |

### 2.2 `LessonCard` Schema Diff

**Before (current):**
```python
class LessonCard(BaseModel):
    index: int
    card_type: str | None = None
    title: str
    content: str
    image_indices: list[int] = []
    images: list[dict] = []
    question: CardMCQ | None = None
    options: list[str] | None = None
    difficulty: int = 3
```

**After (version 11):**
```python
class LessonCard(BaseModel):
    index: int
    card_type: str | None = None
    title: str
    content: str
    image_indices: list[int] = []
    images: list[dict] = []
    question: CardMCQ | None = None
    question2: CardMCQ | None = Field(
        default=None,
        description="Backup MCQ shown after first wrong answer; same schema as question"
    )
    options: list[str] | None = None   # CHECKIN cards only
    difficulty: int = 3
    _section_index: int = Field(
        default=0,
        description="Section sequence position (0-based); used by frontend for deterministic sort"
    )
```

Note: `_section_index` uses underscore prefix by convention to signal it is a system-stamped field, not LLM-generated content. In Pydantic v2, private fields with underscore prefix must be declared as `model_fields` with an alias or as a plain dict field in the serialized output — implementation note for the backend developer: stamp `_section_index` as a plain dict key after Pydantic model construction, before serialization.

### 2.3 `CardsResponse` Schema Diff

**Before:**
```python
class CardsResponse(BaseModel):
    session_id: UUID
    concept_id: str
    concept_title: str
    style: str
    phase: str
    cards: list[LessonCard]
    total_questions: int = 0
```

**After:**
```python
class CardsResponse(BaseModel):
    session_id: UUID
    concept_id: str
    concept_title: str
    style: str
    phase: str
    cards: list[LessonCard]
    total_questions: int = 0           # retained for backward compat
    has_more_concepts: bool = False    # True when concepts_queue is non-empty
    sections_total: int = 0            # total sub-section count for progress display
    sections_done: int = 0             # sub-sections delivered so far
```

### 2.4 New Schemas

```python
class NextSectionCardsRequest(BaseModel):
    """Request body for POST /sessions/{id}/next-section-cards."""
    pass  # Session ID comes from path; no body fields needed for v1
    # Reserved for future: student_state_score, difficulty_bias


class NextSectionCardsResponse(BaseModel):
    """Response for POST /sessions/{id}/next-section-cards."""
    session_id: UUID
    cards: list[LessonCard]
    has_more_concepts: bool
    sections_total: int
    sections_done: int
    section_name: str = ""   # human-readable name of the section just generated
```

### 2.5 Data Flow Diagram

```
POST /sessions/{id}/cards (starter pack)
  │
  ├─ Load session from DB
  ├─ Check presentation_text.version
  │    ├─ version == 11 AND concepts_queue IS empty → all already generated
  │    ├─ version == 11 AND cached_cards exist → return cached_cards[section 0..1]
  │    └─ version < 11 → full regeneration path
  │
  ├─ Call KnowledgeService.get_concept_blocks() for sub-sections 0..N-1
  ├─ Split: sections[0..STARTER_PACK_INITIAL_SECTIONS-1] → starter
  │         sections[STARTER_PACK_INITIAL_SECTIONS..] → queue
  │
  ├─ _generate_cards_single(starter sections, max_tokens=per_section_floor × n_starter)
  │    └─ Returns cards with question + question2 + _section_index stamped
  │
  ├─ Persist to presentation_text:
  │    { version: 11, cached_cards: [starter cards],
  │      concepts_queue: ["sec2_id", "sec3_id", ...],
  │      generated_sections: ["sec0_id", "sec1_id"],
  │      total_sections: N }
  │
  └─ Return CardsResponse(cards=starter_cards, has_more_concepts=(queue non-empty),
                          sections_total=N, sections_done=n_starter)


POST /sessions/{id}/next-section-cards (rolling fetch)
  │
  ├─ Load session from DB (SELECT ... FOR UPDATE to prevent concurrent pops)
  ├─ Load presentation_text JSON
  ├─ Idempotency check: if concepts_queue is empty → return has_more_concepts=false, cards=[]
  │
  ├─ Pop next_section_id = concepts_queue.pop(0)
  ├─ Check generated_sections: if next_section_id already in generated_sections
  │    └─ Return cached cards for that section (already in cached_cards)
  │
  ├─ Call KnowledgeService.get_concept_blocks(next_section_id)
  ├─ _generate_cards_single([next_section], max_tokens=per_section_floor)
  │    └─ Returns cards with question + question2 + _section_index stamped
  │
  ├─ Append new cards to cached_cards
  ├─ Append next_section_id to generated_sections
  ├─ Persist updated presentation_text to DB
  │
  └─ Return NextSectionCardsResponse(
         cards=new_cards,
         has_more_concepts=(concepts_queue non-empty after pop),
         sections_total=total_sections,
         sections_done=len(generated_sections))
```

---

## 3. API Design

### 3.1 Existing Endpoint — Modified

**`POST /api/v2/sessions/{session_id}/cards`**

Response schema extended (backward compatible — new fields have defaults):

```json
{
  "session_id": "uuid",
  "concept_id": "PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS",
  "concept_title": "Introduction to Whole Numbers",
  "style": "default",
  "phase": "CARDS",
  "cards": [ /* starter pack: first 2 sub-sections */ ],
  "total_questions": 0,
  "has_more_concepts": true,
  "sections_total": 5,
  "sections_done": 2
}
```

**Status codes:**
- `200 OK` — starter pack generated or retrieved from cache
- `404 Not Found` — session_id does not exist
- `409 Conflict` — session not in PRESENTING phase

### 3.2 New Endpoint

**`POST /api/v2/sessions/{session_id}/next-section-cards`**

```
Method:  POST
Path:    /api/v2/sessions/{session_id}/next-section-cards
Auth:    X-API-Key header (existing APIKeyMiddleware)
Rate:    10/minute per IP (RATE_LIMIT_LLM_HEAVY — LLM call)
```

**Request:**
```json
{}
```
(Empty body; session_id in path is sufficient. Body reserved for future use.)

**Response `200 OK`:**
```json
{
  "session_id": "uuid",
  "cards": [
    {
      "index": 6,
      "_section_index": 2,
      "card_type": "TEACH",
      "title": "...",
      "content": "...",
      "question": { "text": "...", "options": [...], "correct_index": 1, "explanation": "...", "difficulty": "MEDIUM" },
      "question2": { "text": "...", "options": [...], "correct_index": 2, "explanation": "...", "difficulty": "HARD" },
      "images": [],
      "difficulty": 3
    }
  ],
  "has_more_concepts": false,
  "sections_total": 5,
  "sections_done": 5,
  "section_name": "Multiplication of Whole Numbers"
}
```

**Response `204 No Content`:**
Returned when `concepts_queue` is already empty (all sections delivered; idempotent re-call).

**Response `404 Not Found`:**
```json
{ "detail": "Session not found" }
```

**Response `409 Conflict`:**
```json
{ "detail": "Session is not in CARDS phase" }
```

**Response `503 Service Unavailable`:**
```json
{ "detail": "Card generation failed after 3 attempts" }
```

### 3.3 Versioning Strategy

Both endpoints are under `/api/v2` (Teaching Loop resource). The new endpoint follows the established pattern of adding to v2 for session-scoped resources.

### 3.4 Authentication and Authorization

All endpoints use the existing `APIKeyMiddleware` (`X-API-Key` header). No per-student authorization change is in scope.

### 3.5 Error Handling Conventions

All errors follow the existing FastAPI `HTTPException` pattern with `detail` string. The `503` case for LLM failure uses `HTTPException(status_code=503, detail=...)` (not `JSONResponse`) to be consistent with existing error patterns.

---

## 4. Sequence Diagrams

### 4.1 Happy Path — Session Start (Starter Pack)

```
Student         Frontend            Backend             OpenAI
   │                │                   │                  │
   │  Click Learn   │                   │                  │
   │───────────────►│                   │                  │
   │                │  POST /cards      │                  │
   │                │──────────────────►│                  │
   │                │                   │ load_session()   │
   │                │                   │ check version    │
   │                │                   │ split sections   │
   │                │                   │──────────────────►
   │                │                   │  LLM call        │
   │                │                   │  (sections 0-1)  │
   │                │                   │◄──────────────────
   │                │                   │ stamp _section_index
   │                │                   │ store queue to DB
   │                │  200 cards[]      │                  │
   │                │  has_more=true    │                  │
   │                │◄──────────────────│                  │
   │  Card 0 shown  │                   │                  │
   │◄───────────────│                   │                  │
```

### 4.2 Happy Path — Rolling Pre-Fetch

```
Student         Frontend            Backend             OpenAI
   │                │                   │                  │
   │  Card N-2      │                   │                  │
   │  (2 from end)  │                   │                  │
   │                │ POST /next-section│                  │
   │                │──────────────────►│                  │
   │                │  (background)     │ SELECT FOR UPDATE│
   │                │                   │ pop queue[0]     │
   │                │                   │──────────────────►
   │                │                   │  LLM call        │
   │                │                   │  (section N)     │
   │                │                   │◄──────────────────
   │                │                   │ append to cache  │
   │                │  200 cards[]      │                  │
   │                │  has_more=false   │                  │
   │                │◄──────────────────│                  │
   │                │ APPEND_CARDS      │                  │
   │  Cards appear  │                   │                  │
   │  seamlessly    │                   │                  │
```

### 4.3 Happy Path — `question2` Swap After Wrong Answer

```
Student         Frontend
   │                │
   │  Answers MCQ   │
   │  (wrong)       │
   │───────────────►│
   │                │  recordCardInteraction() fired
   │                │  state.cardAnswers[N].wrong_attempts++
   │                │
   │                │  if wrong_attempts == 1:
   │                │    swap question display → card.question2
   │                │    (NO API call)
   │                │
   │  question2     │
   │  shown instantly│
   │◄───────────────│
```

### 4.4 Case A — Recovery Card (Both MCQs Wrong)

```
Student         Frontend            Backend
   │                │                   │
   │  Answers q2    │                   │
   │  (also wrong)  │                   │
   │───────────────►│                   │
   │                │ POST /complete-card│
   │                │  (recovery mode)  │
   │                │──────────────────►│
   │                │                   │ INSERT_RECOVERY_CARD
   │                │  recovery card    │
   │                │◄──────────────────│
   │  Recovery card │                   │
   │  shown         │                   │
```

### 4.5 Error Path — Rolling Fetch Fails

```
Student         Frontend            Backend
   │                │                   │
   │  Card N-2      │                   │
   │  (2 from end)  │                   │
   │                │ POST /next-section│
   │                │──────────────────►│
   │                │                   │ LLM error (3 attempts)
   │                │  503              │
   │                │◄──────────────────│
   │                │ log error         │
   │                │ state unchanged   │
   │  Existing      │                   │
   │  cards remain  │                   │
   │  (no blank)    │                   │
```

### 4.6 Session Phase Transitions

```
IDLE
  │  POST /sessions (start session)
  ▼
PRESENTING
  │  POST /sessions/{id}/cards (starter pack generated)
  ▼
CARDS  ←──── POST /sessions/{id}/next-section-cards (rolling, stays in CARDS)
  │
  │  [has_more_concepts === false AND student on last card]
  │  POST /sessions/{id}/complete-cards
  ▼
CARDS_DONE
  │  POST /sessions/{id}/check (Socratic begins)
  ▼
CHECKING
  │  [score >= MASTERY_THRESHOLD]
  ▼                              │ [score < MASTERY_THRESHOLD]
COMPLETED                        ▼
                             REMEDIATING
                                 │  POST /sessions/{id}/recheck
                                 ▼
                             RECHECKING
                                 │  [score >= MASTERY_THRESHOLD]
                                 ▼                │ [still failing]
                             COMPLETED            ▼
                                             REMEDIATING_2
                                                  │
                                             RECHECKING_2
                                                  │
                                             COMPLETED (or ATTEMPTS_EXHAUSTED)
```

---

## 5. Integration Design

### 5.1 Internal Service Communication

All communication is synchronous HTTP within the same FastAPI process:

| From | To | Protocol | Notes |
|------|----|----------|-------|
| `teaching_router.py` | `teaching_service.py` | Direct function call (async) | No change from existing pattern |
| `teaching_service.py` | `knowledge_service.py` | Direct method call (async) | `get_concept_blocks(section_id)` — existing method |
| `teaching_service.py` | OpenAI API | HTTPS via `AsyncOpenAI` client | Existing client; timeout=30.0; 3 retries with exponential back-off |
| `teaching_router.py` | PostgreSQL | SQLAlchemy async | `SELECT ... FOR UPDATE` on session row during queue pop |

### 5.2 `SELECT ... FOR UPDATE` Scope

The row lock is scoped to the session row only during the queue pop operation in `generate_next_section_cards()`. Lock duration: from start of queue pop to DB write of updated `presentation_text`. Estimated < 500ms. Uses `with_for_update()` on the SQLAlchemy query.

### 5.3 Retry Policy (inherited from existing `TeachingService` pattern)

```python
for attempt in range(1, 4):
    try:
        response = await client.chat.completions.create(...)
        break
    except Exception as e:
        if attempt == 3:
            raise ValueError(f"LLM call failed after 3 attempts: {e}")
        await asyncio.sleep(2 * attempt)
```

### 5.4 Frontend API Wrapper

New function in `frontend/src/api/sessions.js`:

```javascript
/**
 * Fetch cards for the next queued sub-section.
 * Called by goToNextCard() Case B when student is 2 cards from end.
 * @param {string} sessionId
 * @returns {Promise<NextSectionCardsResponse>}
 */
export async function getNextSectionCards(sessionId) {
  const { data } = await api.post(`/api/v2/sessions/${sessionId}/next-section-cards`);
  return data;
}
```

---

## 6. Security Design

### 6.1 Authentication and Authorization

- All endpoints protected by `APIKeyMiddleware` (`X-API-Key` header) — existing, unchanged
- No per-student authorization in scope (see Technical Debt in CLAUDE.md)

### 6.2 Input Validation

- `session_id` (path param): UUID type enforced by FastAPI path converter; invalid UUIDs return `422`
- `NextSectionCardsRequest` body: empty; no validation needed
- `concepts_queue` popped from server-side `presentation_text` — never supplied by client; immune to queue injection attacks

### 6.3 Data Encryption

- In transit: HTTPS enforced in production (existing)
- At rest: `presentation_text` column is not encrypted (existing behavior); `concepts_queue` contains only concept IDs (no PII)

### 6.4 Rate Limiting

- `POST /next-section-cards` uses `RATE_LIMIT_LLM_HEAVY` = 10/minute (existing constant)
- Applied via `@limiter.limit(...)` decorator (existing `slowapi` pattern)

### 6.5 Secrets Management

No new secrets introduced. OpenAI API key already in `backend/.env` via `OPENAI_API_KEY`.

---

## 7. Observability Design

### 7.1 Logging

All log lines use the existing `logger = logging.getLogger(__name__)` pattern with structured format.

| Event | Level | Format |
|-------|-------|--------|
| Starter pack generated | INFO | `cards starter_pack session=%s sections=%d cards=%d has_more=%s` |
| Rolling fetch triggered | INFO | `cards rolling_fetch session=%s section=%s cards=%d has_more=%s` |
| Rolling fetch cache hit | INFO | `cards rolling_cache_hit session=%s section=%s` |
| Queue empty (idempotent call) | INFO | `cards queue_empty session=%s` |
| LLM call attempt N | DEBUG | `cards llm_attempt=%d session=%s section=%s max_tokens=%d` |
| LLM call exhausted | ERROR | `cards llm_exhausted session=%s section=%s attempts=3` |
| Cache version mismatch | INFO | `cards cache_miss session=%s version_found=%d version_expected=11` |
| `_section_index` stamped | DEBUG | `cards section_index_stamped cards=%d section_index=%d` |

### 7.2 Key Metrics (add to existing dashboard)

| Metric | Type | Description |
|--------|------|-------------|
| `cards_starter_latency_ms` | Histogram | Time to return starter pack (P50, P95, P99) |
| `cards_rolling_latency_ms` | Histogram | Time to return each rolling fetch |
| `cards_rolling_fetch_count` | Counter | Total rolling fetches per session (baseline: N-2 per concept) |
| `cards_cache_hit_rate` | Gauge | Ratio of requests served from cache vs LLM calls |
| `cards_queue_depth` | Histogram | `len(concepts_queue)` at starter pack time |

### 7.3 Alerting Thresholds

| Alert | Threshold |
|-------|-----------|
| `cards_rolling_latency_ms P95 > 5000ms` | Warning — students hitting wait on rolling fetch |
| `cards_llm_exhausted rate > 5/minute` | Critical — OpenAI errors affecting card delivery |
| `cards_starter_latency_ms P95 > 8000ms` | Warning — starter pack slower than expected |

---

## 8. Error Handling and Resilience

### 8.1 Backend Error Scenarios

| Scenario | Handling |
|----------|---------|
| `concepts_queue` is empty when `next-section-cards` is called | Return `204 No Content` (idempotent, not an error) |
| LLM fails after 3 attempts | Raise `HTTPException(503)`; log `ERROR cards_llm_exhausted` |
| Session not found | `HTTPException(404)` |
| Session not in CARDS phase | `HTTPException(409)` |
| Concurrent rolling fetch (double-tap) | `SELECT ... FOR UPDATE` ensures only one fetch proceeds; second caller gets cached result |
| `presentation_text` JSON parse error | Log `ERROR`; treat as cache miss; regenerate starter pack |
| `_section_index` stamp fails (empty card list) | Log `WARNING`; return cards without stamp; frontend falls back to array order |

### 8.2 Frontend Error Scenarios

| Scenario | Handling |
|----------|---------|
| `POST /next-section-cards` returns 503 | Log error; no state mutation; student remains on current card; existing cards still navigable |
| `POST /next-section-cards` returns 204 (already empty) | Dispatch `SET_HAS_MORE_CONCEPTS(false)`; show "Finish Cards" button |
| Rolling fetch in-flight when student reaches last card | Show existing `adaptiveCardLoading` spinner; wait for response |
| `question2` is `null` on a card | Fall back to existing `regenerate-mcq` endpoint (existing behavior; should not occur after this feature is deployed) |

### 8.3 Graceful Degradation

If the rolling fetch fails consistently (e.g., OpenAI outage), the student can still:
1. Complete cards for the starter pack (first 2 sections)
2. Manually retry by clicking "Next" again (triggers another rolling fetch attempt)
3. If `has_more_concepts` never becomes false, the "Finish Cards" button remains hidden — the student cannot proceed to Socratic check; this is intentional (no partial coverage)

---

## 9. Per-File Change Specification

### 9.1 `backend/src/config.py`

Add after `STARTER_PACK_MAX_SECTIONS`:

```python
STARTER_PACK_INITIAL_SECTIONS: int = 2    # Sub-sections in the starter pack (rolling: rest fetched on demand)
ROLLING_PREFETCH_TRIGGER_DISTANCE: int = 2  # Frontend fires pre-fetch when this many cards remain
```

Raise per-section floor constants:

```python
# Before:
CARDS_MAX_TOKENS_SLOW_FLOOR: int = 8_000
CARDS_MAX_TOKENS_NORMAL_FLOOR: int = 6_000
CARDS_MAX_TOKENS_FAST_FLOOR: int = 4_000

# After (rolling: per-section, not per-concept):
CARDS_MAX_TOKENS_SLOW_FLOOR: int = 6_000
CARDS_MAX_TOKENS_NORMAL_FLOOR: int = 4_500
CARDS_MAX_TOKENS_FAST_FLOOR: int = 3_000
```

Note: The ceiling constants (`CARDS_MAX_TOKENS_SLOW`, `CARDS_MAX_TOKENS_NORMAL`, `CARDS_MAX_TOKENS_FAST`) are unchanged. Only the floors are raised because each call now covers one sub-section instead of N sub-sections.

### 9.2 `backend/src/api/teaching_schemas.py`

Add `question2` to `LessonCard`:

```python
class LessonCard(BaseModel):
    # ... existing fields ...
    question: CardMCQ | None = Field(default=None, ...)
    question2: CardMCQ | None = Field(
        default=None,
        description="Backup MCQ shown after first wrong answer — same schema as question"
    )
    # ... existing fields ...
```

Extend `CardsResponse`:

```python
class CardsResponse(BaseModel):
    # ... existing fields ...
    has_more_concepts: bool = Field(default=False, description="True when more sub-sections remain in queue")
    sections_total: int = Field(default=0, description="Total sub-section count for this concept")
    sections_done: int = Field(default=0, description="Sub-sections delivered so far")
```

Add new schemas:

```python
class NextSectionCardsRequest(BaseModel):
    """Request body reserved for future use. Currently empty."""
    pass


class NextSectionCardsResponse(BaseModel):
    """Response for POST /sessions/{id}/next-section-cards."""
    session_id: UUID
    cards: list[LessonCard]
    has_more_concepts: bool
    sections_total: int
    sections_done: int
    section_name: str = ""
```

### 9.3 `backend/src/api/teaching_service.py`

Seven changes:

**Change 1 — Import new constants:**
```python
from config import (
    ...,
    STARTER_PACK_INITIAL_SECTIONS,
)
```

**Change 2 — Rename and scope `generate_cards()` to starter pack:**

Rename `generate_cards()` to `generate_cards_starter_pack()`. Inside, after parsing all sub-sections, split:

```python
all_sections = self._parse_sub_sections(presentation_text)
grouped = self._group_by_major_topic(all_sections)

starter_sections = grouped[:STARTER_PACK_INITIAL_SECTIONS]
queue_sections = grouped[STARTER_PACK_INITIAL_SECTIONS:]
queue_section_ids = [s["id"] for s in queue_sections]

# Generate cards for starter only
cards = await self._generate_cards_single(starter_sections, max_tokens=...)
cards = self._stamp_section_index(cards, starter_sections)

# Persist queue
await self._store_concepts_queue(session_id, db, cached_cards=cards,
                                  queue=queue_section_ids,
                                  generated_ids=[s["id"] for s in starter_sections],
                                  total=len(grouped))
return cards, bool(queue_sections)
```

**Change 3 — New `generate_next_section_cards()` method:**

```python
async def generate_next_section_cards(
    self,
    session_id: UUID,
    db: AsyncSession,
) -> tuple[list[dict], bool, int, int, str]:
    """
    Generate cards for the next queued sub-section.

    Returns:
        (cards, has_more_concepts, sections_total, sections_done, section_name)
    """
    async with db.begin():
        session = await db.get(TeachingSession, session_id, with_for_update=True)
        if not session or not session.presentation_text:
            raise ValueError(f"Session {session_id} not found or missing presentation_text")

        pt = json.loads(session.presentation_text)
        concepts_queue = pt.get("concepts_queue", [])
        generated_ids = pt.get("generated_sections", [])
        cached_cards = pt.get("cached_cards", [])
        total_sections = pt.get("total_sections", 0)

        if not concepts_queue:
            return [], False, total_sections, len(generated_ids), ""

        next_section_id = concepts_queue[0]

        # Idempotency: already generated?
        if next_section_id in generated_ids:
            section_cards = [c for c in cached_cards
                             if c.get("_section_index") == generated_ids.index(next_section_id)]
            remaining_queue = concepts_queue[1:]
            return (section_cards, bool(remaining_queue),
                    total_sections, len(generated_ids), next_section_id)

        # Generate
        section_blocks = await self.knowledge_svc.get_concept_blocks(next_section_id)
        new_cards = await self._generate_cards_single([section_blocks],
                                                       max_tokens=_compute_per_section_budget(1, profile))
        new_cards = self._stamp_section_index(new_cards, [section_blocks],
                                               base_index=len(generated_ids))

        # Update state
        updated_queue = concepts_queue[1:]
        updated_generated = generated_ids + [next_section_id]
        updated_cached = cached_cards + new_cards

        pt["concepts_queue"] = updated_queue
        pt["generated_sections"] = updated_generated
        pt["cached_cards"] = updated_cached

        session.presentation_text = json.dumps(pt)
        # (commit happens on context manager exit)

    return (new_cards, bool(updated_queue),
            total_sections, len(updated_generated),
            section_blocks.get("title", next_section_id))
```

**Change 4 — Token budget fix:**

The per-section budget is now computed per single section (not per concept):

```python
def _compute_per_section_budget(n_sections: int, profile: str) -> int:
    if profile in ("SLOW", "STRUGGLING"):
        floor = CARDS_MAX_TOKENS_SLOW_FLOOR
        per_section = CARDS_MAX_TOKENS_SLOW_PER_SECTION
        ceiling = CARDS_MAX_TOKENS_SLOW
    elif profile in ("FAST", "STRONG"):
        floor = CARDS_MAX_TOKENS_FAST_FLOOR
        per_section = CARDS_MAX_TOKENS_FAST_PER_SECTION
        ceiling = CARDS_MAX_TOKENS_FAST
    else:
        floor = CARDS_MAX_TOKENS_NORMAL_FLOOR
        per_section = CARDS_MAX_TOKENS_NORMAL_PER_SECTION
        ceiling = CARDS_MAX_TOKENS_NORMAL
    return min(ceiling, max(floor, n_sections * per_section))
```

**Change 5 — `_stamp_section_index()` private method:**

```python
def _stamp_section_index(
    self,
    cards: list[dict],
    sections: list[dict],
    base_index: int = 0,
) -> list[dict]:
    """Stamp _section_index on each card based on which section it belongs to."""
    for card in cards:
        section_title = card.get("section_title", "")
        for i, section in enumerate(sections):
            if section.get("title", "") == section_title or section.get("id") == card.get("section_id"):
                card["_section_index"] = base_index + i
                break
        else:
            card["_section_index"] = base_index
    return cards
```

**Change 6 — RC4 sort fix:**

Replace the existing fuzzy RC4 sort with deterministic `_section_index` sort in the card assembly function:

```python
# Before:
cards.sort(key=lambda c: _rc4_sort_key(c))

# After:
cards.sort(key=lambda c: c.get("_section_index", 0))
```

**Change 7 — Cache version bump to 11:**

```python
# In _store_presentation_text() / wherever version is written:
pt["version"] = 11

# In _load_cached_cards() / cache version check:
CURRENT_CACHE_VERSION = 11
```

### 9.4 `backend/src/api/teaching_router.py`

Add import of new schemas:

```python
from api.teaching_schemas import (
    ...,
    NextSectionCardsRequest,
    NextSectionCardsResponse,
)
```

Add new endpoint:

```python
@router.post("/sessions/{session_id}/next-section-cards",
             response_model=NextSectionCardsResponse)
@limiter.limit(RATE_LIMIT_LLM_HEAVY)
async def next_section_cards(
    request: Request,
    session_id: UUID,
    body: NextSectionCardsRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate and return cards for the next queued sub-section (rolling fetch)."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.phase not in ("CARDS", "PRESENTING"):
        raise HTTPException(status_code=409, detail="Session is not in CARDS phase")

    try:
        cards, has_more, sections_total, sections_done, section_name = \
            await teaching_svc.generate_next_section_cards(session_id, db)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not cards and not has_more:
        # All sections already delivered — idempotent call
        from fastapi.responses import Response
        return Response(status_code=204)

    return NextSectionCardsResponse(
        session_id=session_id,
        cards=[LessonCard(**c) for c in cards],
        has_more_concepts=has_more,
        sections_total=sections_total,
        sections_done=sections_done,
        section_name=section_name,
    )
```

### 9.5 `backend/src/adaptive/adaptive_router.py`

Remove the ceiling constant entirely:

```python
# DELETE this line:
_ADAPTIVE_CARD_CEILING = 20
```

Remove all references to `_ADAPTIVE_CARD_CEILING` in the ceiling check block. Recovery cards (Case A) are unlimited.

### 9.6 `backend/src/api/prompts.py`

In `build_cards_system_prompt()`, add `question2` to the card JSON schema instruction:

```
Before:
  "question": {
    "text": "<MCQ question text>",
    "options": ["A", "B", "C", "D"],
    "correct_index": 0,
    "explanation": "<why this answer is correct>",
    "difficulty": "EASY|MEDIUM|HARD"
  }

After (add question2 block):
  "question": {
    "text": "<MCQ question text — must NOT be answerable from the lesson text verbatim>",
    "options": ["A", "B", "C", "D"],
    "correct_index": 0,
    "explanation": "<why this answer is correct>",
    "difficulty": "EASY|MEDIUM|HARD"
  },
  "question2": {
    "text": "<SECOND MCQ — tests the same concept from a different angle; different wording and different correct answer position>",
    "options": ["A", "B", "C", "D"],
    "correct_index": 1,
    "explanation": "<why this answer is correct>",
    "difficulty": "MEDIUM|HARD"
  }

DUAL-MCQ RULE: question2 must:
  1. Test the same concept as question but from a different angle
  2. Not share the same correct answer position (correct_index must differ from question.correct_index)
  3. Not reuse question wording verbatim
  4. Have difficulty MEDIUM or HARD (never EASY — it is the fallback after a wrong answer)
```

### 9.7 `frontend/src/api/sessions.js`

Add after existing exports:

```javascript
/**
 * Fetch cards for the next queued sub-section (rolling generation).
 * @param {string} sessionId
 * @returns {Promise<import('../types').NextSectionCardsResponse>}
 */
export async function getNextSectionCards(sessionId) {
  const { data } = await api.post(`/api/v2/sessions/${sessionId}/next-section-cards`, {});
  return data;
}
```

### 9.8 `frontend/src/context/SessionContext.jsx`

**Remove:** `const MAX_ADAPTIVE_CARDS = ...` constant (if present).

**Add to `initialState`:**
```javascript
hasMoreConcepts: true,      // true until server confirms all sections delivered
sectionsTotal: 0,
sectionsDone: 0,
```

**Add `APPEND_CARDS` reducer case:**
```javascript
case "APPEND_CARDS": {
  const startIdx = state.cards.length;
  const newCards = action.payload.cards.map((c, i) => ({
    ...c,
    index: startIdx + i,
  }));
  return {
    ...state,
    cards: [...state.cards, ...newCards],
    hasMoreConcepts: action.payload.has_more_concepts,
    sectionsTotal: action.payload.sections_total ?? state.sectionsTotal,
    sectionsDone: action.payload.sections_done ?? state.sectionsDone,
  };
}
```

**Update `CARDS_LOADED` reducer case** to set `hasMoreConcepts`, `sectionsTotal`, `sectionsDone` from the starter pack response.

**Rewrite `goToNextCard()`:**

```javascript
const goToNextCard = useCallback(async () => {
  const { session, cards, currentCardIndex, hasMoreConcepts, adaptiveCallInFlight } = state;
  if (!session) return;

  const card = cards[currentCardIndex];
  const wrongAttempts = state.cardAnswers[currentCardIndex]?.wrongAttempts ?? 0;
  const isLastCard = currentCardIndex >= cards.length - 1;
  const cardsFromEnd = cards.length - 1 - currentCardIndex;

  // ── Case A: Both MCQs wrong → recovery card ──────────────────────────
  if (wrongAttempts >= 2) {
    dispatch({ type: "ADAPTIVE_CARD_LOADING" });
    try {
      const data = await completeCardAndGetNext(session.id, {
        card_index: currentCardIndex,
        time_on_card_sec: timeOnCardRef.current,
        wrong_attempts: wrongAttempts,
        // ... other signals
      });
      dispatch({ type: "INSERT_RECOVERY_CARD", payload: data.card });
      dispatch({ type: "NEXT_CARD" });
    } catch (err) {
      console.error("[SessionContext] recovery card failed", err);
      dispatch({ type: "ADAPTIVE_CARD_ERROR" });
    }
    return;
  }

  // ── Case B: Near end of batch + has_more_concepts → rolling pre-fetch ─
  if (cardsFromEnd <= ROLLING_PREFETCH_TRIGGER_DISTANCE && hasMoreConcepts && !adaptiveCallInFlight) {
    dispatch({ type: "ADAPTIVE_CALL_STARTED" });
    getNextSectionCards(session.id)
      .then((data) => {
        if (data && data.cards && data.cards.length > 0) {
          dispatch({ type: "APPEND_CARDS", payload: data });
        } else {
          dispatch({ type: "SET_HAS_MORE_CONCEPTS", payload: false });
        }
        dispatch({ type: "ADAPTIVE_CALL_DONE" });
      })
      .catch((err) => {
        console.error("[SessionContext] rolling fetch failed", err);
        dispatch({ type: "ADAPTIVE_CALL_DONE" });
      });
    // Do NOT await — let it run in background; advance card immediately
  }

  // ── Case D: Mid-batch → record interaction + advance ─────────────────
  recordCardInteraction(session.id, {
    card_index: currentCardIndex,
    time_on_card_sec: timeOnCardRef.current,
    wrong_attempts: wrongAttempts,
  }).catch((err) => console.error("[SessionContext] recordCardInteraction failed", err));

  dispatch({ type: "NEXT_CARD" });
}, [state, timeOnCardRef]);
```

**Add `SET_HAS_MORE_CONCEPTS` reducer case:**
```javascript
case "SET_HAS_MORE_CONCEPTS":
  return { ...state, hasMoreConcepts: action.payload };
```

### 9.9 `frontend/src/components/learning/CardLearningView.jsx`

**Update `isLastCard` condition:**

```javascript
// Before:
const isLastCard = currentCardIndex >= cards.length - 1;

// After:
const isLastCard = currentCardIndex >= cards.length - 1 && !hasMoreConcepts;
```

**Add `question2` swap logic:**

```javascript
// Derive active question from card state
const wrongAttempts = cardAnswers[currentCardIndex]?.wrongAttempts ?? 0;
const activeQuestion = wrongAttempts >= 1 && card.question2
  ? card.question2
  : card.question;
```

Use `activeQuestion` wherever the card's MCQ is rendered.

**Add section progress indicator:**

```javascript
{sectionsTotal > 0 && (
  <span className="text-xs text-gray-400">
    {t("learning.conceptsProgress", {
      current: sectionsDone,
      total: sectionsTotal,
    })}
  </span>
)}
```

**Update "Finish Cards" button visibility:**

```javascript
// Show only when all sections delivered AND on last card
{isLastCard && !hasMoreConcepts && (
  <Button onClick={handleFinishCards}>
    {t("learning.finishCards")}
  </Button>
)}
```

### 9.10 Locale Files (all 13)

Add to each `frontend/src/locales/{lang}.json`:

```json
"conceptsProgress": "Section {{current}} of {{total}}"
```

Translations per locale:

| Locale | Key value |
|--------|-----------|
| en | `"Section {{current}} of {{total}}"` |
| ar | `"القسم {{current}} من {{total}}"` |
| de | `"Abschnitt {{current}} von {{total}}"` |
| es | `"Sección {{current}} de {{total}}"` |
| fr | `"Section {{current}} sur {{total}}"` |
| hi | `"अनुभाग {{current}} / {{total}}"` |
| ja | `"セクション {{current}} / {{total}}"` |
| ko | `"섹션 {{current}} / {{total}}"` |
| ml | `"വിഭാഗം {{current}} / {{total}}"` |
| pt | `"Seção {{current}} de {{total}}"` |
| si | `"කොටස {{current}} / {{total}}"` |
| ta | `"பிரிவு {{current}} / {{total}}"` |
| zh | `"章节 {{current}} / {{total}}"` |

---

## 10. Risk and Conflict Registry

| ID | Conflict / Risk | Affected Files | Resolution |
|----|-----------------|----------------|------------|
| C1 | `generate_cards()` called from 2 places: `cards` endpoint and remediation | `teaching_router.py` | Rename to `generate_cards_starter_pack()`; update both call sites |
| C2 | `CardsResponse` extended — frontend must handle new optional fields | `SessionContext.jsx` | New fields have defaults; `CARDS_LOADED` reducer updated to extract them |
| C3 | `LessonCard` extended — old cached cards in DB lack `question2` | `teaching_service.py` | Cache version bump to 11 forces full regeneration; no backward compat needed |
| C4 | `_ADAPTIVE_CARD_CEILING` removal — any code that references it breaks at import | `adaptive_router.py`, tests | Grep all references before PR; update tests |
| C5 | `SELECT ... FOR UPDATE` in `generate_next_section_cards()` — must not be called inside an already-open transaction | `teaching_router.py` | Ensure the router endpoint does not wrap in a transaction before calling service |
| C6 | `APPEND_CARDS` reducer — card `index` fields must be re-stamped to match array position | `SessionContext.jsx` | Implemented in reducer: `index: startIdx + i` |
| C7 | `goToNextCard()` Case B fires rolling fetch AND advances card — if fetch is slow, `isLastCard` may be true before new cards arrive | `SessionContext.jsx`, `CardLearningView.jsx` | `adaptiveCardLoading` spinner blocks "Finish Cards" button visibility |
| C8 | `question2` in prompts — LLM may omit it for CHECKIN cards (backend-generated, no LLM) | `prompts.py` | Instruction explicitly states: "CHECKIN cards do not need question2" |
| C9 | Token budget floor constants renamed — any hardcoded reference breaks | `teaching_service.py` | Use symbolic constants from `config.py` only; search for raw ints (8000, 6000, 4000) |
| C10 | `_stamp_section_index()` — if card has no `section_title` and no `section_id`, stamp falls to `base_index` | `teaching_service.py` | Acceptable fallback; log `DEBUG` warning |
| C11 | `nextSectionCards` 204 response — Axios throws on 204 by default | `sessions.js` | Add `validateStatus: (s) => s < 500` to the request config; handle 204 → `{ cards: [], has_more_concepts: false }` |
| C12 | Socratic chat `complete-cards` gate — must check `has_more_concepts` not just `isLastCard` | `teaching_router.py` (complete-cards handler) | Add guard: if `concepts_queue` non-empty in `presentation_text`, return 409 |
| C13 | `STARTER_PACK_MAX_SECTIONS = 50` still in config — now superseded by `STARTER_PACK_INITIAL_SECTIONS = 2` | `config.py` | Remove `STARTER_PACK_MAX_SECTIONS` or add comment that it is deprecated; grep all usages |
| C14 | Cache version check must handle missing `version` key (null / undefined in old JSON) | `teaching_service.py` | `pt.get("version", 0) < 11` — default 0 always triggers regeneration |

---

## 11. Testing Strategy

### 11.1 Unit Tests (pytest)

| Test | File | Covers |
|------|------|--------|
| `test_generate_cards_starter_pack_returns_2_sections` | `tests/test_hybrid_cards.py` | FR-01: starter pack contains only first 2 sections |
| `test_generate_cards_starter_pack_sets_queue` | `tests/test_hybrid_cards.py` | FR-01: `concepts_queue` stored in `presentation_text` |
| `test_generate_next_section_cards_pops_queue` | `tests/test_hybrid_cards.py` | FR-02: queue shrinks by 1 per call |
| `test_generate_next_section_cards_idempotent` | `tests/test_hybrid_cards.py` | R3: second call for same section returns cached cards without LLM call |
| `test_stamp_section_index_assigns_correct_integers` | `tests/test_hybrid_cards.py` | FR-06 / ADR-04 |
| `test_token_budget_per_section_raises_floor` | `tests/test_hybrid_cards.py` | FR-07 |
| `test_cache_version_mismatch_triggers_regeneration` | `tests/test_hybrid_cards.py` | FR-08 |
| `test_question2_present_on_all_llm_cards` | `tests/test_hybrid_cards.py` | FR-03 |
| `test_lesson_card_schema_question2_field` | `tests/test_schemas.py` | Schema diff correctness |
| `test_cards_response_has_more_concepts_field` | `tests/test_schemas.py` | Schema diff correctness |

### 11.2 Integration Tests

| Test | Description |
|------|-------------|
| Full starter pack → rolling fetch flow | POST /cards → verify `has_more_concepts=true`; POST /next-section-cards until `has_more_concepts=false`; verify all sections covered |
| Concurrent rolling fetch safety | Two simultaneous `POST /next-section-cards` calls; verify exactly one LLM call made; no duplicate section |
| `complete-cards` gate | Verify 409 returned when `concepts_queue` non-empty |
| Cache version bump | Session with `version=10` in `presentation_text`; POST /cards; verify regeneration |

### 11.3 Frontend Tests

| Test | Description |
|------|-------------|
| `APPEND_CARDS` reducer | Verify card indices are re-stamped correctly |
| `goToNextCard` Case B fires at 2 cards from end | Mock `getNextSectionCards`; verify fired at correct threshold |
| `isLastCard` only true when `!hasMoreConcepts` | Verify "Finish Cards" hidden when `hasMoreConcepts=true` |
| `question2` swap | Card with `wrongAttempts=1`; verify `activeQuestion === card.question2` |

### 11.4 Performance Test

Target: `POST /next-section-cards` P95 < 3000ms for a single sub-section with 4 cards. Run with k6 at 50 concurrent sessions.

---

## Key Decisions Requiring Stakeholder Input

1. **`NextSectionCardsRequest` body:** Currently empty. Should `difficulty_bias` or `state_score` be sent in v1 to allow server-side adaptation per rolling fetch?
2. **204 vs 200 for empty queue:** Is `204 No Content` acceptable for the idempotent empty-queue case, or should it be `200` with `{ cards: [], has_more_concepts: false }`? (204 is cleaner but requires Axios `validateStatus` configuration.)
3. **`STARTER_PACK_MAX_SECTIONS` removal:** Confirm that removing this constant will not break any existing integration that references it externally.
4. **`_section_index` on CHECKIN cards:** CHECKIN cards are inserted by the backend at fixed intervals (every 12 cards). Should they carry `_section_index = -1` to sort them after all content cards, or should they carry the index of the preceding content card?
