# Detailed Low-Level Design: Adaptive Transparency

**Feature slug:** `adaptive-transparency`
**Date:** 2026-02-28
**Author:** Solution Architect
**Status:** Draft — pending stakeholder review

---

## 1. Component Breakdown

### Group A — Premium Frontend Redesign

All component specifications for Group A reside in `docs/risk-hardening-redesign/DLD.md`. The frontend-developer must read that document in full. This section provides a reference table only.

| Component | File | Spec Location |
|-----------|------|--------------|
| CSS design tokens (`--shadow-*`, `--radius-*`, `--motion-*`, `--shimmer-*`) | `frontend/src/index.css` | `docs/risk-hardening-redesign/DLD.md §2.3` |
| New `@keyframes` (shake, confetti, shimmer, slide-in, ring-fill) | `frontend/src/index.css` | `docs/risk-hardening-redesign/DLD.md §9.1` |
| `Skeleton.jsx` | `frontend/src/components/ui/Skeleton.jsx` | `docs/risk-hardening-redesign/DLD.md §9.2` |
| `ProgressRing.jsx` | `frontend/src/components/ui/ProgressRing.jsx` | `docs/risk-hardening-redesign/DLD.md §9.3` |
| `Card.jsx` | `frontend/src/components/ui/Card.jsx` | `docs/risk-hardening-redesign/DLD.md §1 (Stream C table)` |
| `Toast.jsx` | `frontend/src/components/ui/Toast.jsx` | `docs/risk-hardening-redesign/DLD.md §1 (Stream C table)` |
| `ui/index.js` barrel | `frontend/src/components/ui/index.js` | `docs/risk-hardening-redesign/DLD.md §5.3` |
| `CardLearningView.jsx` (pill MCQ, ProgressDots, focus mode) | `frontend/src/components/learning/CardLearningView.jsx` | `docs/risk-hardening-redesign/DLD.md §9.5` |
| `AssistantPanel` slide-in behaviour | `frontend/src/components/learning/CardLearningView.jsx` | `docs/risk-hardening-redesign/DLD.md §9.5` |
| `CompletionView.jsx` (ProgressRing, confetti, score bands) | `frontend/src/components/learning/CompletionView.jsx` | `docs/risk-hardening-redesign/DLD.md §9.7` |
| `SocraticChat.jsx` (flex column, fixed input bar) | `frontend/src/components/learning/SocraticChat.jsx` | `docs/risk-hardening-redesign/DLD.md §9.6` |
| `AppShell.jsx` (student name dropdown popover) | `frontend/src/components/layout/AppShell.jsx` | `docs/risk-hardening-redesign/DLD.md §9.8` |
| `WelcomePage.jsx` (hero improvement) | `frontend/src/pages/WelcomePage.jsx` | `docs/risk-hardening-redesign/DLD.md §1 (Stream C table)` |
| `ConceptMapPage.jsx` (3-column flex layout) | `frontend/src/pages/ConceptMapPage.jsx` | `docs/risk-hardening-redesign/DLD.md §9.4` |
| `ConceptPanel.jsx` (slide-in panel) | `frontend/src/components/conceptmap/ConceptPanel.jsx` | `docs/risk-hardening-redesign/DLD.md §9.4` |

**Implementation instruction:** Complete all Group A components before beginning Group B components that modify `CardLearningView.jsx`. Group B inserts `AdaptiveSignalTracker` and difficulty controls into the frame that Group A establishes.

---

### Group B — Adaptive Transparency (new)

| Component | File | Responsibility |
|-----------|------|---------------|
| `GET /api/v2/students/{id}/card-history` handler | `backend/src/api/teaching_router.py` | New endpoint: query CardInteraction for a student, return paginated list |
| `CardHistoryResponse` Pydantic schema | `backend/src/api/teaching_schemas.py` | Response model for the history endpoint |
| `CardBehaviorSignals` (modified) | `backend/src/adaptive/schemas.py` | Add `difficulty_bias: Literal["TOO_EASY", "TOO_HARD"] | None = None` |
| Wrong-option pattern query | `backend/src/adaptive/adaptive_engine.py` | New async function `load_wrong_option_pattern()` |
| `generate_next_card()` (modified) | `backend/src/adaptive/adaptive_engine.py` | Apply difficulty_bias override; pass pattern to prompt builder |
| `build_next_card_prompt()` (modified) | `backend/src/adaptive/prompt_builder.py` | Accept and inject `wrong_option_pattern` and `difficulty_bias` into prompt |
| `AdaptiveSignalTracker.jsx` | `frontend/src/components/learning/AdaptiveSignalTracker.jsx` | New component: live signal display + learning profile + readiness bar |
| `StudentHistoryPage.jsx` | `frontend/src/pages/StudentHistoryPage.jsx` | New page at `/history`: table of card interactions + session arc sparklines |
| `getCardHistory()` API wrapper | `frontend/src/api/students.js` | New Axios wrapper for the history endpoint |
| `SessionContext` (modified) | `frontend/src/context/SessionContext.jsx` | Add `learningProfileSummary`, `adaptationApplied`, `difficultyBias` to state |
| App routing (modified) | `frontend/src/App.jsx` | Register `/history` route pointing to `StudentHistoryPage` |

---

## 2. Data Design

### 2.1 Existing Data Model — No ORM Changes

All Group B features read from `CardInteraction`. The ORM model is unchanged. The relevant columns are:

```
card_interactions:
  id                  UUID PK
  session_id          UUID FK → teaching_sessions.id
  student_id          UUID FK → students.id
  concept_id          VARCHAR(200)
  card_index          INTEGER
  time_on_card_sec    FLOAT
  wrong_attempts      INTEGER
  selected_wrong_option SMALLINT | NULL
  hints_used          INTEGER
  idle_triggers       INTEGER
  adaptation_applied  VARCHAR(200) | NULL
  completed_at        DATETIME(tz)
```

No Alembic migration is needed for Group B.

### 2.2 Pydantic Schema Changes

**`backend/src/adaptive/schemas.py` — `CardBehaviorSignals` addition:**

```python
class CardBehaviorSignals(BaseModel):
    """Behavioral signals captured for a single card interaction by the frontend."""

    card_index: int
    time_on_card_sec: float = 0.0
    wrong_attempts: int = 0
    selected_wrong_option: int | None = None
    hints_used: int = 0
    idle_triggers: int = 0
    # NEW — explicit difficulty bias from student (one-shot per card advance)
    difficulty_bias: Literal["TOO_EASY", "TOO_HARD"] | None = None
```

`NextCardRequest` inherits from `CardBehaviorSignals` without change — the new field is automatically included.

**`backend/src/api/teaching_schemas.py` — new schemas:**

```python
class CardInteractionRecord(BaseModel):
    """A single card interaction row for the history endpoint."""
    id: str                          # UUID as string
    session_id: str                  # UUID as string
    concept_id: str
    card_index: int
    time_on_card_sec: float
    wrong_attempts: int
    selected_wrong_option: int | None
    hints_used: int
    idle_triggers: int
    adaptation_applied: str | None
    completed_at: str                # ISO 8601 string


class CardHistoryResponse(BaseModel):
    """Response for GET /api/v2/students/{student_id}/card-history."""
    student_id: str
    total_returned: int
    interactions: list[CardInteractionRecord]
```

### 2.3 Config Constants Added

The following constants are added to `backend/src/config.py`:

```python
# ── Adaptive Transparency ─────────────────────────────────────────────────────
WRONG_OPTION_PATTERN_THRESHOLD: int = 3  # Times a wrong option must be chosen to trigger pattern injection
CARD_HISTORY_DEFAULT_LIMIT: int = 50     # Default row limit for GET /card-history
CARD_HISTORY_MAX_LIMIT: int = 200        # Hard cap — prevents runaway queries
```

### 2.4 Wrong-Option Pattern Query

The wrong-option pattern query is a targeted read against `card_interactions`. It returns the most-frequently-chosen wrong option for a given `(student_id, concept_id)` pair if that count exceeds `WRONG_OPTION_PATTERN_THRESHOLD`.

```python
# Pseudocode for load_wrong_option_pattern()
SELECT selected_wrong_option, COUNT(*) as freq
FROM card_interactions
WHERE student_id = $student_id
  AND concept_id = $concept_id
  AND selected_wrong_option IS NOT NULL
GROUP BY selected_wrong_option
HAVING COUNT(*) >= WRONG_OPTION_PATTERN_THRESHOLD
ORDER BY freq DESC
LIMIT 1
```

Returns: `int | None` — the option index (0-based) that the student most persistently selects incorrectly, or `None` if no pattern exists.

### 2.5 SessionContext State Shape (extended)

```javascript
// New fields added to initialState in SessionContext.jsx:
{
  // ... existing fields ...
  learningProfileSummary: null,  // dict: {speed, comprehension, engagement, confidence_score}
  adaptationApplied: null,       // string: last adaptation label
  difficultyBias: null,          // "TOO_EASY" | "TOO_HARD" | null
}
```

### 2.6 Data Flow Diagram

```
Browser                         FastAPI                    PostgreSQL
  │                               │                            │
  │  ── User clicks "Too Hard" ──>│                            │
  │  (sets difficultyBias="TOO_HARD" in SessionContext)        │
  │                               │                            │
  │  POST /sessions/{id}/         │                            │
  │  complete-card                │                            │
  │  { card_index, time, wrong,   │                            │
  │    hints, idle_triggers,      │                            │
  │    difficulty_bias: "TOO_HARD"}                            │
  │──────────────────────────────>│                            │
  │                               │ load_student_history()     │
  │                               │────────────────────────────>
  │                               │<──── history dict ─────────│
  │                               │                            │
  │                               │ load_wrong_option_pattern()│
  │                               │────────────────────────────>
  │                               │<──── pattern: int|None ────│
  │                               │                            │
  │                               │ build_blended_analytics()  │
  │                               │ build_learning_profile()   │
  │                               │ --- difficulty_bias override:
  │                               │   profile.recommended_next_step
  │                               │   = "REMEDIATE_PREREQ"     │
  │                               │ build_next_card_prompt(    │
  │                               │   wrong_option_pattern=2,  │
  │                               │   difficulty_bias="TOO_HARD"
  │                               │ )                          │
  │                               │ _call_llm(ADAPTIVE_CARD_MODEL)
  │                               │────── OpenAI API ─────────>│ (not shown)
  │                               │<──── card JSON ────────────│
  │                               │                            │
  │                               │ INSERT card_interactions   │
  │                               │────────────────────────────>
  │<── NextCardResponse ──────────│                            │
  │  { card, learning_profile_    │                            │
  │    summary, adaptation_       │                            │
  │    applied, ... }             │                            │
  │                               │                            │
  │ ADAPTIVE_CARD_LOADED dispatch:│                            │
  │  learningProfileSummary = ... │                            │
  │  adaptationApplied = ...      │                            │
  │  difficultyBias = null        │  (cleared — one-shot)      │
```

---

## 3. API Design

### 3.1 New Endpoint: Card History

**`GET /api/v2/students/{student_id}/card-history`**

| Attribute | Value |
|-----------|-------|
| Method | GET |
| Path | `/api/v2/students/{student_id}/card-history` |
| Auth | None (session-cookie pattern unchanged) |
| Rate limit | None (local dev scope) |

**Path parameter:**
- `student_id` (UUID, required) — the student whose history to retrieve

**Query parameters:**

| Parameter | Type | Default | Max | Description |
|-----------|------|---------|-----|-------------|
| `limit` | int | 50 | 200 | Maximum rows to return; hard-capped at `CARD_HISTORY_MAX_LIMIT` |
| `session_id` | UUID | — | — | Optional: filter to interactions from a single session |

**Success response — 200 OK:**

```json
{
  "student_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "total_returned": 47,
  "interactions": [
    {
      "id": "a1b2c3d4-...",
      "session_id": "e5f6a7b8-...",
      "concept_id": "prealgebra_1_2_fractions",
      "card_index": 3,
      "time_on_card_sec": 42.5,
      "wrong_attempts": 1,
      "selected_wrong_option": 2,
      "hints_used": 0,
      "idle_triggers": 0,
      "adaptation_applied": "NORMAL_VARIANCE",
      "completed_at": "2026-02-28T10:45:22Z"
    }
  ]
}
```

**Error responses:**

| Status | Condition |
|--------|-----------|
| 404 | `student_id` not found in `students` table |
| 422 | `limit` is non-integer or `session_id` is not a valid UUID |

**SQLAlchemy query pattern:**

```python
@router.get("/students/{student_id}/card-history", response_model=CardHistoryResponse)
async def get_card_history(
    student_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    session_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(404, "Student not found")

    q = (
        select(CardInteraction)
        .where(CardInteraction.student_id == student_id)
        .order_by(CardInteraction.completed_at.desc())
        .limit(min(limit, CARD_HISTORY_MAX_LIMIT))
    )
    if session_id is not None:
        q = q.where(CardInteraction.session_id == session_id)

    result = await db.execute(q)
    rows = result.scalars().all()

    return CardHistoryResponse(
        student_id=str(student_id),
        total_returned=len(rows),
        interactions=[CardInteractionRecord.model_validate(r, from_attributes=True) for r in rows],
    )
```

### 3.2 Modified Endpoint: Complete Card and Get Next

**`POST /api/v2/sessions/{session_id}/complete-card`** — this endpoint already exists. Its request body schema (`NextCardRequest`) gains the `difficulty_bias` field via inheritance from the modified `CardBehaviorSignals`.

**Modified request body schema:**

```json
{
  "card_index": 3,
  "time_on_card_sec": 45.2,
  "wrong_attempts": 2,
  "selected_wrong_option": 1,
  "hints_used": 1,
  "idle_triggers": 0,
  "difficulty_bias": "TOO_HARD"
}
```

`difficulty_bias` is `null` when not provided (backward compatible — existing clients continue to work without change).

**Response schema — unchanged.** `NextCardResponse` is unchanged; `adaptation_applied` will now include bias labels where applicable (e.g., `"REMEDIATE_PREREQ (student: TOO_HARD)"`).

### 3.3 Versioning Strategy

Both endpoints remain under `/api/v2`. The `difficulty_bias` field addition is backward compatible. No version bump is required.

### 3.4 Error Handling Conventions

- All errors follow existing FastAPI `HTTPException` pattern with `detail` string
- Pydantic validation errors (e.g., invalid `difficulty_bias` value) return 422 automatically
- The wrong-option pattern query failure is caught and logged; `pattern = None` is used as fallback

---

## 4. Sequence Diagrams

### 4.1 Student Clicks "Too Hard" — Full Flow

```
Student               Browser (CardLearningView)    SessionContext     FastAPI
  │                         │                           │                │
  │ clicks "Too Hard"        │                           │                │
  │────────────────────────>│                           │                │
  │                         │ setDifficultyBias("TOO_HARD")              │
  │                         │──────────────────────────>│                │
  │                         │ (state.difficultyBias = "TOO_HARD")        │
  │                         │                           │                │
  │ completes card / clicks │                           │                │
  │ "Next Card"              │                           │                │
  │────────────────────────>│                           │                │
  │                         │ goToNextCard({            │                │
  │                         │   ...signals,             │                │
  │                         │   difficulty_bias:        │                │
  │                         │   state.difficultyBias    │                │
  │                         │ })                        │                │
  │                         │──────────────────────────>│                │
  │                         │                           │ completeCardAndGetNext()
  │                         │                           │────────────────>│
  │                         │                           │ { ..., difficulty_bias: "TOO_HARD" }
  │                         │                           │                │
  │                         │                           │  adaptive_engine:
  │                         │                           │  load_student_history()
  │                         │                           │  load_wrong_option_pattern()
  │                         │                           │  build_blended_analytics()
  │                         │                           │  build_learning_profile()
  │                         │                           │  override: recommended_next_step = REMEDIATE_PREREQ
  │                         │                           │  build_next_card_prompt(difficulty_bias="TOO_HARD")
  │                         │                           │  _call_llm()
  │                         │                           │<── NextCardResponse ──│
  │                         │                           │                │
  │                         │ ADAPTIVE_CARD_LOADED:     │                │
  │                         │   learningProfileSummary  │                │
  │                         │   adaptationApplied       │                │
  │                         │   difficultyBias = null   │ (cleared)      │
  │                         │<──────────────────────────│                │
  │ new card renders        │                           │                │
  │<───────────────────────-│                           │                │
```

### 4.2 Wrong-Option Pattern Detection and Injection

```
adaptive_engine.py                        PostgreSQL
  │                                           │
  │ load_wrong_option_pattern(               │
  │   student_id, concept_id, db             │
  │ )                                         │
  │──────────────────────────────────────────>│
  │  SELECT selected_wrong_option, COUNT(*)   │
  │  FROM card_interactions                   │
  │  WHERE student_id = $1                    │
  │    AND concept_id = $2                    │
  │    AND selected_wrong_option IS NOT NULL  │
  │  GROUP BY selected_wrong_option           │
  │  HAVING COUNT(*) >= 3                     │
  │  ORDER BY freq DESC LIMIT 1              │
  │<──── row: {selected_wrong_option: 2, freq: 4} or ()
  │                                           │
  │ pattern = 2  (option C, 0-indexed)        │
  │                                           │
  │ build_next_card_prompt(                   │
  │   ...,                                   │
  │   wrong_option_pattern=2,                │
  │   difficulty_bias=None,                  │
  │ )                                         │
  │                                           │
  │ [PROMPT SECTION injected]:               │
  │   MISCONCEPTION PATTERN:                 │
  │     The student has repeatedly selected  │
  │     option C (index 2) incorrectly       │
  │     on this concept (4 times).           │
  │     Design the question so that          │
  │     option C is a deliberate distractor  │
  │     with an explicit explanation in the  │
  │     explanation field for why it is      │
  │     wrong.                               │
```

### 4.3 Student History Page Load

```
StudentHistoryPage           SessionContext         FastAPI
  │                               │                    │
  │ mount                         │                    │
  │ student = useStudent()        │                    │
  │ (student.id from context)     │                    │
  │                               │                    │
  │ getCardHistory(student.id, {limit: 50})            │
  │──────────────────────────────────────────────────>│
  │                               │ SELECT * FROM card_interactions
  │                               │ WHERE student_id = $1
  │                               │ ORDER BY completed_at DESC
  │                               │ LIMIT 50
  │<── CardHistoryResponse ───────────────────────────│
  │                               │                    │
  │ Group rows by session_id      │                    │
  │ For each session group:       │                    │
  │   Sort by card_index          │                    │
  │   Extract [time_on_card_sec]  │                    │
  │   Render <SessionArcSparkline │                    │
  │     times={[42.5, 18.1, ...]} │                    │
  │   />                          │                    │
  │                               │                    │
  │ Render <InteractionTable      │                    │
  │   interactions={rows}         │                    │
  │ />                            │                    │
```

### 4.4 Live Signal Tracker 1-Second Refresh

```
Browser clock          AdaptiveSignalTracker     CardLearningView (refs)
  │                          │                          │
  │ useEffect mount           │                          │
  │──────────────────────────>│                          │
  │                          │ setInterval(1000):        │
  │  1s tick                 │                           │
  │──────────────────────────>│                          │
  │                          │ read cardStartTimeRef ───>│
  │                          │ read wrongAttemptsRef ───>│
  │                          │ read hintsUsedRef ────── >│
  │                          │ read idleTriggersRef ────>│
  │                          │<── current values ────────│
  │                          │                           │
  │                          │ setDisplayState({         │
  │                          │   timeOnCard: elapsed,    │
  │                          │   wrongAttempts: n,       │
  │                          │   ...                     │
  │                          │ })                        │
  │                          │                           │
  │ DOM re-renders            │                          │
  │<──────────────────────────│                          │
```

---

## 5. Integration Design

### 5.1 Backend: `adaptive_engine.py` Changes

#### 5.1.1 New function: `load_wrong_option_pattern()`

Add the following async function to `backend/src/adaptive/adaptive_engine.py`:

```python
async def load_wrong_option_pattern(
    student_id: str,
    concept_id: str,
    db,
) -> int | None:
    """
    Query the most persistently selected wrong option for a student on a concept.
    Returns the option index (0-based) if it has been selected >= WRONG_OPTION_PATTERN_THRESHOLD
    times, else None.
    """
    from sqlalchemy import select, func
    from db.models import CardInteraction
    import uuid as _uuid
    from config import WRONG_OPTION_PATTERN_THRESHOLD

    sid = _uuid.UUID(student_id) if isinstance(student_id, str) else student_id

    result = await db.execute(
        select(
            CardInteraction.selected_wrong_option,
            func.count(CardInteraction.id).label("freq"),
        )
        .where(CardInteraction.student_id == sid)
        .where(CardInteraction.concept_id == concept_id)
        .where(CardInteraction.selected_wrong_option.is_not(None))
        .group_by(CardInteraction.selected_wrong_option)
        .having(func.count(CardInteraction.id) >= WRONG_OPTION_PATTERN_THRESHOLD)
        .order_by(func.count(CardInteraction.id).desc())
        .limit(1)
    )
    row = result.first()
    if row is None:
        return None

    pattern = row.selected_wrong_option
    logger.info(
        "wrong_option_pattern: student_id=%s concept_id=%s option=%s freq=%d",
        student_id, concept_id, pattern, row.freq,
    )
    return int(pattern)
```

#### 5.1.2 Modified function: `generate_next_card()`

The function signature gains a `db` parameter and calls `load_wrong_option_pattern()`. The difficulty bias override is applied after `build_learning_profile()`:

```python
async def generate_next_card(
    student_id: str,
    concept_id: str,
    signals: "CardBehaviorSignals",
    card_index: int,
    history: dict,
    knowledge_svc,
    mastery_store: dict[str, bool],
    llm_client: AsyncOpenAI,
    model: str,
    language: str = "en",
    db = None,  # NEW — optional for backward compat; required for pattern detection
) -> tuple[dict, "LearningProfile", "GenerationProfile", str | None]:
    from adaptive.prompt_builder import build_next_card_prompt

    analytics = build_blended_analytics(signals, history, concept_id, student_id)
    has_prereq = find_remediation_prereq(concept_id, knowledge_svc, mastery_store) is not None
    profile = build_learning_profile(analytics, has_unmet_prereq=has_prereq)
    gen_profile = build_generation_profile(profile)

    # ── Difficulty bias override ───────────────────────────────────────────
    bias = signals.difficulty_bias  # "TOO_EASY" | "TOO_HARD" | None
    if bias == "TOO_EASY":
        profile = profile.model_copy(
            update={"recommended_next_step": "CHALLENGE"}
        )
        logger.info(
            "difficulty_bias_override: student_id=%s bias=TOO_EASY recommended=CHALLENGE",
            student_id,
        )
    elif bias == "TOO_HARD":
        profile = profile.model_copy(
            update={"recommended_next_step": "REMEDIATE_PREREQ"}
        )
        logger.info(
            "difficulty_bias_override: student_id=%s bias=TOO_HARD recommended=REMEDIATE_PREREQ",
            student_id,
        )

    # ── Wrong-option pattern detection ────────────────────────────────────
    wrong_option_pattern: int | None = None
    if db is not None:
        try:
            wrong_option_pattern = await load_wrong_option_pattern(
                student_id, concept_id, db
            )
        except Exception as exc:
            logger.warning(
                "wrong_option_pattern_query_failed: error=%s (skipping)", exc
            )

    concept_detail = knowledge_svc.get_concept_detail(concept_id)
    if concept_detail is None:
        raise ValueError(f"Concept not found: {concept_id}")

    sys_p, usr_p = build_next_card_prompt(
        concept_detail=concept_detail,
        learning_profile=profile,
        gen_profile=gen_profile,
        card_index=card_index,
        history=history,
        language=language,
        wrong_option_pattern=wrong_option_pattern,   # NEW
        difficulty_bias=bias,                        # NEW
    )

    messages = [
        {"role": "system", "content": sys_p},
        {"role": "user", "content": usr_p},
    ]
    raw = await _call_llm(llm_client, ADAPTIVE_CARD_MODEL, messages, max_tokens=2200)
    cleaned = _extract_json_block(raw)

    parsed: dict | None = None
    for attempt_raw in (cleaned, _salvage_truncated_json(cleaned)):
        try:
            parsed = json.loads(attempt_raw)
            break
        except json.JSONDecodeError:
            pass

    if parsed is None:
        raise ValueError(f"LLM output could not be parsed. Raw (first 300): {raw[:300]}")

    motivational_note = parsed.pop("motivational_note", None)

    # ── Difficulty forwarding ─────────────────────────────────────────────
    # The LLM returns "difficulty" for the initial lesson (AdaptiveLessonCard schema).
    # For next-card generation we must forward it to the card dict.
    card = {
        "index": card_index,
        "title": parsed.get("title", f"Card {card_index + 1}"),
        "content": parsed.get("content", ""),
        "images": [],
        "questions": parsed.get("questions", []),
        "difficulty": parsed.get("difficulty", 3),  # NEW — forward to frontend
    }

    for i, q in enumerate(card["questions"]):
        q_type = q.get("type", "mcq")
        q["id"] = f"c{card_index}_{q_type}_{i}"

    # ── Adaptation label ──────────────────────────────────────────────────
    base_label = profile.recommended_next_step
    adaptation_label = (
        f"{base_label} (student: {bias})" if bias else base_label
    )

    return card, profile, gen_profile, motivational_note, adaptation_label
```

Note: The return tuple now includes `adaptation_label` as a fifth element. The adaptive router must be updated to unpack five values.

### 5.2 Backend: `prompt_builder.py` Changes

**Modified signature of `build_next_card_prompt()`:**

```python
def build_next_card_prompt(
    concept_detail: dict,
    learning_profile: LearningProfile,
    gen_profile: GenerationProfile,
    card_index: int,
    history: dict,
    language: str = "en",
    wrong_option_pattern: int | None = None,    # NEW
    difficulty_bias: str | None = None,          # NEW
) -> tuple[str, str]:
```

**Addition to user prompt — MISCONCEPTION PATTERN block (appended when `wrong_option_pattern is not None`):**

```python
if wrong_option_pattern is not None:
    option_letter = chr(65 + wrong_option_pattern)  # 0→A, 1→B, 2→C, 3→D
    parts += [
        "",
        "MISCONCEPTION PATTERN (critical — follow exactly):",
        f"  The student has repeatedly selected option {option_letter} (index {wrong_option_pattern})",
        f"  incorrectly on this concept at least {WRONG_OPTION_PATTERN_THRESHOLD} times.",
        "  Requirements for this card's MCQ question:",
        f"  - Include option {option_letter} as a deliberate distractor",
        f"  - Set the 'explanation' field to explicitly address why option {option_letter} is wrong",
        "  - Do NOT make option {option_letter} the correct answer",
    ]
```

**Addition to user prompt — DIFFICULTY BIAS block (appended when `difficulty_bias is not None`):**

```python
if difficulty_bias == "TOO_EASY":
    parts += [
        "",
        "DIFFICULTY ADJUSTMENT (student feedback):",
        "  The student indicated this content is too easy.",
        "  Generate a card at the highest end of the difficulty range for this card_index.",
        "  Prefer a 'practice' or 'challenge' card type if appropriate.",
        "  Include a fun_element that raises the stakes or introduces an extension.",
    ]
elif difficulty_bias == "TOO_HARD":
    parts += [
        "",
        "DIFFICULTY ADJUSTMENT (student feedback):",
        "  The student indicated this content is too hard.",
        "  Generate a card at the lowest appropriate difficulty for this card_index.",
        "  Prefer an 'explain' or 'example' card type.",
        "  Use a concrete analogy and step-by-step breakdown.",
        "  Add at least 2 hints.",
    ]
```

### 5.3 Frontend: `sessions.js` Changes

The `completeCardAndGetNext()` function in `frontend/src/api/sessions.js` must forward `difficulty_bias`:

```javascript
export const completeCardAndGetNext = (sessionId, signals) =>
  api.post(
    `/api/v2/sessions/${sessionId}/complete-card`,
    {
      card_index:            signals.cardIndex,
      time_on_card_sec:      signals.timeOnCardSec,
      wrong_attempts:        signals.wrongAttempts,
      selected_wrong_option: signals.selectedWrongOption ?? null,
      hints_used:            signals.hintsUsed,
      idle_triggers:         signals.idleTriggers,
      difficulty_bias:       signals.difficultyBias ?? null,  // NEW
    },
    { timeout: COMPLETE_CARD_TIMEOUT }
  );
```

### 5.4 Frontend: `students.js` Changes

New function added to `frontend/src/api/students.js`:

```javascript
export const getCardHistory = (studentId, { limit = 50, sessionId = null } = {}) => {
  const params = { limit };
  if (sessionId) params.session_id = sessionId;
  return api.get(`/api/v2/students/${studentId}/card-history`, { params });
};
```

### 5.5 Frontend: `SessionContext.jsx` Changes

**`initialState` additions:**

```javascript
const initialState = {
  // ... existing fields ...
  learningProfileSummary: null,   // NEW: {speed, comprehension, engagement, confidence_score}
  adaptationApplied: null,        // NEW: string label from adaptation_applied
  difficultyBias: null,           // NEW: "TOO_EASY" | "TOO_HARD" | null
};
```

**New reducer cases:**

```javascript
case "SET_DIFFICULTY_BIAS":
  return { ...state, difficultyBias: action.payload };

case "ADAPTIVE_CARD_LOADED":
  return {
    ...state,
    cards: [...state.cards, action.payload.card],
    currentCardIndex: state.currentCardIndex + 1,
    adaptiveCardLoading: false,
    idleTriggerCount: 0,
    motivationalNote: action.payload.motivational_note ?? null,
    performanceVsBaseline: action.payload.performance_vs_baseline ?? null,
    learningProfileSummary: action.payload.learning_profile_summary ?? null,  // NEW
    adaptationApplied: action.payload.adaptation_applied ?? null,             // NEW
    difficultyBias: null,  // NEW — clear after one-shot use
  };
```

**New exported action in `SessionProvider`:**

```javascript
const setDifficultyBias = useCallback((bias) => {
  dispatch({ type: "SET_DIFFICULTY_BIAS", payload: bias });
}, []);
```

**`goToNextCard` modification — pass `difficultyBias` in signals:**

```javascript
const goToNextCard = useCallback(
  async (signals) => {
    if (!state.session || !signals || state.cards.length >= MAX_ADAPTIVE_CARDS) {
      dispatch({ type: "NEXT_CARD" });
      return;
    }
    dispatch({ type: "ADAPTIVE_CARD_LOADING" });
    try {
      const res = await completeCardAndGetNext(state.session.id, {
        ...signals,
        difficultyBias: state.difficultyBias,  // NEW
      });
      // ... tracking and dispatch unchanged ...
    } catch (err) {
      dispatch({ type: "ADAPTIVE_CARD_ERROR" });
    }
  },
  [state.session, state.cards.length, state.difficultyBias]  // difficultyBias added to deps
);
```

---

## 6. Security Design

### Authentication and Authorization

No change to existing auth model. The new `/card-history` endpoint uses `student_id` from the URL path. The WHERE clause `CardInteraction.student_id == student_id` ensures students cannot access each other's data.

### Input Validation

| Input | Validation |
|-------|-----------|
| `difficulty_bias` | `Literal["TOO_EASY", "TOO_HARD"] | None` — Pydantic rejects any other string |
| `limit` query param | `int, ge=1, le=200` via FastAPI `Query()` |
| `session_id` query param | UUID validation via FastAPI path conversion |
| `wrong_option_pattern` from DB | Cast to `int` in `load_wrong_option_pattern()`; source is a database SmallInteger |

### Data Encryption

No change. At-rest and in-transit encryption is unchanged.

### Secrets Management

`WRONG_OPTION_PATTERN_THRESHOLD`, `CARD_HISTORY_DEFAULT_LIMIT`, and `CARD_HISTORY_MAX_LIMIT` are code-level constants, not secrets.

---

## 7. Observability Design

### Logging

All new backend log entries follow the established `key=value` pattern:

```python
# load_wrong_option_pattern() — on detection:
logger.info(
    "wrong_option_pattern: student_id=%s concept_id=%s option=%s freq=%d",
    student_id, concept_id, pattern, row.freq,
)

# load_wrong_option_pattern() — on query failure:
logger.warning(
    "wrong_option_pattern_query_failed: error=%s (skipping)", exc
)

# generate_next_card() — on bias override:
logger.info(
    "difficulty_bias_override: student_id=%s bias=%s recommended=%s",
    student_id, bias, profile.recommended_next_step,
)

# teaching_router — on history request:
logger.info(
    "card_history_requested: student_id=%s limit=%d total_returned=%d",
    student_id, limit, len(rows),
)
```

### Metrics

No new dashboards. The existing `adaptive_card_loaded` PostHog event is extended (in the frontend) to include:

```javascript
trackEvent("adaptive_card_loaded", {
  // ... existing fields ...
  difficulty_bias: signals.difficultyBias ?? null,     // NEW
  has_wrong_pattern: res.data.has_wrong_pattern ?? false, // NEW (optional backend field)
});
```

### Alerting

No new alerting thresholds required for local dev scope.

---

## 8. Error Handling and Resilience

### Wrong-Option Pattern Query Failure

The query in `load_wrong_option_pattern()` is wrapped in a try/except in `generate_next_card()`. On failure, `wrong_option_pattern = None` is used and a warning is logged. The card generation continues without pattern injection. This is the correct graceful degradation — pattern injection is a best-effort enhancement.

### Difficulty Bias Applied to Invalid State

If `difficulty_bias = "TOO_EASY"` is received but the student has no history (new student), the override is still applied — it sets `recommended_next_step = "CHALLENGE"`. The `build_learning_profile()` function will produce a profile consistent with the student's signals, and the `CHALLENGE` override ensures the LLM generates a harder card. This is the correct behavior (the student has explicitly requested a challenge).

### Card History Endpoint — Empty Result

If a student has no `CardInteraction` records, the query returns 0 rows. The response is:

```json
{
  "student_id": "...",
  "total_returned": 0,
  "interactions": []
}
```

The frontend history page renders an empty state message: "No card interactions recorded yet."

### Retry Policies

The `load_wrong_option_pattern()` DB query does not retry (single read, low cost). All LLM retries remain on the existing 3-attempt / exponential back-off policy in `_call_llm()`.

### `generate_next_card()` Return Tuple Arity Change

The return tuple changes from 4 to 5 elements (adding `adaptation_label`). The adaptive router must be updated to unpack 5 values. The comprehensive tester must verify this change does not break the existing complete-card endpoint.

---

## 9. Component Specifications: Group B

### 9.1 `AdaptiveSignalTracker.jsx`

**File:** `frontend/src/components/learning/AdaptiveSignalTracker.jsx`

**Purpose:** Displays live behavioral signals, learning profile summary, mastery readiness bar, and difficulty bias controls inside the card learning view.

**Props:**

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `cardStartTimeRef` | `React.RefObject` | Yes | `useRef` holding `performance.now()` at card start |
| `wrongAttemptsRef` | `React.RefObject` | Yes | `useRef` holding current card wrong attempts count |
| `hintsUsedRef` | `React.RefObject` | Yes | `useRef` holding current card hints used count |
| `idleTriggersRef` | `React.RefObject` | Yes | `useRef` holding session idle trigger count |
| `learningProfileSummary` | `object | null` | No | From `SessionContext.learningProfileSummary`; `{speed, comprehension, engagement, confidence_score}` |
| `adaptationApplied` | `string | null` | No | From `SessionContext.adaptationApplied` |
| `onDifficultyBias` | `function` | Yes | Callback: `(bias: "TOO_EASY" | "TOO_HARD" | null) => void` |
| `difficultyBias` | `string | null` | No | Current bias from `SessionContext.difficultyBias` |

**Internal state:**

```javascript
const [display, setDisplay] = useState({
  timeOnCard: 0,
  wrongAttempts: 0,
  hintsUsed: 0,
  idleTriggers: 0,
});
```

**Effect — 1-second polling:**

```javascript
useEffect(() => {
  const id = setInterval(() => {
    const elapsed = Math.floor(
      (performance.now() - (cardStartTimeRef.current ?? performance.now())) / 1000
    );
    setDisplay({
      timeOnCard: elapsed,
      wrongAttempts: wrongAttemptsRef.current ?? 0,
      hintsUsed: hintsUsedRef.current ?? 0,
      idleTriggers: idleTriggersRef.current ?? 0,
    });
  }, 1000);
  return () => clearInterval(id);
}, [cardStartTimeRef, wrongAttemptsRef, hintsUsedRef, idleTriggersRef]);
```

**Engagement emoji map (derived from `learningProfileSummary.engagement`):**

| Value | Emoji | Label |
|-------|-------|-------|
| `"BORED"` | `😴` | Bored |
| `"ENGAGED"` | `😊` | Engaged |
| `"OVERWHELMED"` | `😰` | Overwhelmed |
| `null` / unknown | `🤔` | Thinking |

**Layout (compact vertical stack, max-width 280px, placed in AssistantPanel or sidebar slot):**

```
┌─────────────────────────────────────────────┐
│  Live Signals                                │
│  ─────────────────────────────────────────  │
│  Time on card:     42s                       │
│  Wrong attempts:   1                         │
│  Hints used:       0                         │
│  Idle triggers:    0                         │
│  ─────────────────────────────────────────  │
│  Profile: NORMAL · OK · 😊 ENGAGED          │
│  Adaptation: NORMAL_VARIANCE                 │
│  ─────────────────────────────────────────  │
│  Readiness for quiz                          │
│  [████████░░░░░░░░] 68%                      │
│  ─────────────────────────────────────────  │
│  [Too Easy] [Too Hard]                       │
└─────────────────────────────────────────────┘
```

**Readiness bar implementation:**

```jsx
const confidence = learningProfileSummary?.confidence_score ?? 0;
const pct = Math.round(confidence * 100);

<div className="readiness-bar-track">
  <div
    className="readiness-bar-fill"
    style={{ width: `${pct}%` }}
  />
</div>
<span>{pct}% ready for quiz</span>
```

Track: `height: 8px`, `border-radius: var(--radius-full)`, `background: var(--color-border)`
Fill: `background: var(--color-primary)`, transitions via `transition: width var(--motion-normal)`

**Difficulty bias buttons:**

```jsx
<button
  className={`bias-btn ${difficultyBias === "TOO_EASY" ? "active" : ""}`}
  onClick={() => onDifficultyBias(difficultyBias === "TOO_EASY" ? null : "TOO_EASY")}
>
  Too Easy
</button>
<button
  className={`bias-btn ${difficultyBias === "TOO_HARD" ? "active" : ""}`}
  onClick={() => onDifficultyBias(difficultyBias === "TOO_HARD" ? null : "TOO_HARD")}
>
  Too Hard
</button>
```

Active state: `background: var(--color-primary)`, `color: white`. Second click on same button clears the bias (toggle behavior).

### 9.2 Difficulty Badge

The `difficulty` field is already present in `AdaptiveLessonCard` (from the initial lesson batch). For adaptive next-cards, it is now forwarded in the normalised card dict (see §5.1.2). The frontend renders it in `CardLearningView` card header.

**Implementation (inside `CardLearningView`, card header row):**

```jsx
const difficulty = currentCard?.difficulty ?? null;

{difficulty !== null && (
  <div className="difficulty-badge" aria-label={`Difficulty ${difficulty} out of 5`}>
    {Array.from({ length: 5 }, (_, i) => (
      <span
        key={i}
        className={`star ${i < difficulty ? "filled" : "empty"}`}
      >
        ★
      </span>
    ))}
  </div>
)}
```

Filled star: `color: var(--color-primary)`. Empty star: `color: var(--color-border)`. Component is inline (no separate file needed).

### 9.3 `StudentHistoryPage.jsx`

**File:** `frontend/src/pages/StudentHistoryPage.jsx`

**Route:** `/history` (registered in `frontend/src/App.jsx`)

**Data fetching:**

```javascript
const { student } = useStudent();
const [interactions, setInteractions] = useState([]);
const [loading, setLoading] = useState(true);
const [error, setError] = useState(null);

useEffect(() => {
  if (!student) { navigate("/"); return; }
  getCardHistory(student.id, { limit: 50 })
    .then(res => {
      setInteractions(res.data.interactions);
    })
    .catch(err => setError(err.message))
    .finally(() => setLoading(false));
}, [student]);
```

**Table columns:**

| Column | Source field | Notes |
|--------|-------------|-------|
| Date | `completed_at` | Formatted as `MMM D, YYYY h:mm a` |
| Concept | `concept_id` | Pass through `formatConceptTitle(concept_id)` |
| Card # | `card_index` | 1-indexed display (`card_index + 1`) |
| Time | `time_on_card_sec` | Formatted as `Xs` or `Xm Ys` |
| Wrong | `wrong_attempts` | Plain integer |
| Hints | `hints_used` | Plain integer |
| Adaptation | `adaptation_applied` | Truncated badge (`<Badge>`) |

**Session Arc Sparkline — `SessionArcSparkline` subcomponent:**

Groups `interactions` by `session_id`. For each unique session, renders an inline SVG showing `time_on_card_sec` per card in order of `card_index`.

```javascript
function SessionArcSparkline({ times, width = 120, height = 32 }) {
  if (!times || times.length < 2) return null;
  const max = Math.max(...times, 1);
  const pts = times.map((t, i) => {
    const x = (i / (times.length - 1)) * width;
    const y = height - (t / max) * height;
    return `${x},${y}`;
  });
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-label="Session time-per-card arc"
      role="img"
    >
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke="var(--color-primary)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
```

The sparkline is rendered in a column on the right of each session group row in the history table. The table groups rows by session: the first row of each session group shows the sparkline spanning all cards in that session.

**Layout:**

```
┌────────────────────────────────────────────────────────────────────────┐
│  Your Learning History                                                   │
│  [← Back to Map]                                                         │
├──────────┬────────────────────┬──────┬──────┬───────┬───────┬──────────┤
│ Date     │ Concept            │ Card │ Time │ Wrong │ Hints │ Arc      │
├──────────┼────────────────────┼──────┼──────┼───────┼───────┼──────────┤
│ Feb 28   │ Fractions          │  1   │  42s │   1   │   0   │ ╌╌╌╌╌╌   │
│ (same)   │ Fractions          │  2   │  18s │   0   │   0   │          │
│ (same)   │ Fractions          │  3   │  65s │   2   │   1   │          │
├──────────┼────────────────────┼──────┼──────┼───────┼───────┼──────────┤
│ Feb 27   │ Mixed Numbers      │  1   │  30s │   0   │   0   │ ╌╌╌╌╌    │
└──────────┴────────────────────┴──────┴──────┴───────┴───────┴──────────┘
```

The sparkline SVG is displayed only in the first row of each session group (rowspan-equivalent using CSS Grid or a group header row).

**Routing addition to `frontend/src/App.jsx`:**

```jsx
import StudentHistoryPage from "./pages/StudentHistoryPage";

// Inside <Routes>:
<Route path="/history" element={<StudentHistoryPage />} />
```

Navigation link added to `AppShell.jsx` student dropdown popover (under the existing "Switch Student" button):

```jsx
<Link to="/history">View History</Link>
```

---

## 10. Testing Strategy

Testing coverage requirements are specified in the execution plan. This section notes the key test surface areas.

### Unit Tests

| Test | Target | Assertion |
|------|--------|-----------|
| `test_card_behavior_signals_accepts_difficulty_bias` | `CardBehaviorSignals` Pydantic model | `difficulty_bias="TOO_EASY"` parses; `difficulty_bias="INVALID"` raises `ValidationError` |
| `test_card_behavior_signals_bias_defaults_to_none` | `CardBehaviorSignals` | `difficulty_bias` defaults to `None` when not supplied |
| `test_difficulty_bias_overrides_recommended_next_step_challenge` | `generate_next_card()` (mock LLM) | `bias="TOO_EASY"` → profile passed to prompt builder has `recommended_next_step="CHALLENGE"` |
| `test_difficulty_bias_overrides_recommended_next_step_remediate` | `generate_next_card()` (mock LLM) | `bias="TOO_HARD"` → profile has `recommended_next_step="REMEDIATE_PREREQ"` |
| `test_wrong_option_pattern_returns_none_when_below_threshold` | `load_wrong_option_pattern()` | With 2 rows for option 1, returns `None` |
| `test_wrong_option_pattern_returns_option_at_threshold` | `load_wrong_option_pattern()` | With 3 rows for option 2, returns `2` |
| `test_prompt_contains_misconception_block_when_pattern_set` | `build_next_card_prompt()` | With `wrong_option_pattern=2`, user prompt contains "MISCONCEPTION PATTERN" |
| `test_prompt_contains_difficulty_block_too_easy` | `build_next_card_prompt()` | With `difficulty_bias="TOO_EASY"`, prompt contains "DIFFICULTY ADJUSTMENT" and "too easy" |
| `test_prompt_contains_difficulty_block_too_hard` | `build_next_card_prompt()` | With `difficulty_bias="TOO_HARD"`, prompt contains "too hard" |
| `test_card_difficulty_forwarded_in_next_card_dict` | `generate_next_card()` | Returned card dict contains `"difficulty"` key with integer value |

### Integration Tests

| Test | Target | Assertion |
|------|--------|-----------|
| `test_card_history_endpoint_returns_200` | `GET /api/v2/students/{id}/card-history` | Returns 200 with valid `CardHistoryResponse` |
| `test_card_history_scoped_to_student` | `GET /api/v2/students/{id}/card-history` | Does not return rows belonging to a different student |
| `test_card_history_respects_limit` | `GET /api/v2/students/{id}/card-history?limit=2` | Returns exactly 2 rows when 5 exist |
| `test_card_history_empty_for_new_student` | `GET /api/v2/students/{id}/card-history` | Returns `total_returned: 0, interactions: []` |
| `test_card_history_404_unknown_student` | `GET /api/v2/students/{unknown}/card-history` | Returns 404 |
| `test_complete_card_accepts_difficulty_bias` | `POST /sessions/{id}/complete-card` | Request with `difficulty_bias="TOO_HARD"` returns 200 (mock LLM) |
| `test_complete_card_bias_null_by_default` | `POST /sessions/{id}/complete-card` | Request without `difficulty_bias` field returns 200 |

### Frontend Tests

Manual verification checklist (no vitest suite yet per technical debt note):

- `AdaptiveSignalTracker`: signal rows update every ~1 second; "Too Easy" button highlights on click; second click clears highlight
- `StudentHistoryPage`: renders table with mocked data; empty state shown when no interactions; sparkline SVG present for sessions with 2+ cards
- Difficulty badge: 3 filled + 2 empty stars when `difficulty=3`; all 5 filled when `difficulty=5`
- `difficultyBias` in `SessionContext`: dispatch `SET_DIFFICULTY_BIAS("TOO_EASY")` → state has `"TOO_EASY"`; dispatch `ADAPTIVE_CARD_LOADED` → `difficultyBias` resets to `null`

---

## Key Decisions Requiring Stakeholder Input

1. **`generate_next_card()` return tuple arity change:** The function now returns 5 values instead of 4. All callers in the adaptive router must be updated. The tester must verify no caller is missed. Is this breaking change acceptable in the current sprint, or should `adaptation_label` be returned as a field inside the existing 4-tuple's `LearningProfile` object?

2. **Wrong-option pattern injection is backend-only (invisible to student):** The DLD specifies the pattern is injected silently into the LLM prompt. Should the API response include a `has_wrong_pattern: bool` field so the frontend can optionally display a message? (e.g., "The AI noticed a pattern in your answers and tailored this card.")

3. **History page session grouping:** The DLD groups interactions by `session_id` and shows the sparkline per session. If a student has 50 interactions spanning 10 sessions, the grouping results in 10 session blocks in a limit-50 list. Should the history endpoint instead accept a `group_by=session` mode that returns sessions with nested cards, or is client-side grouping acceptable?

4. **`AdaptiveSignalTracker` placement:** The spec places the tracker inside the `AssistantPanel` (the slide-in right panel). An alternative is a compact top-bar overlay inside the card frame. Which placement is preferred?

5. **Sparkline for single-card sessions:** `SessionArcSparkline` renders `null` when `times.length < 2`. Should single-card sessions show a dot rather than nothing?
