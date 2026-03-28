# Per-Card Adaptive Generation — Detailed Low-Level Design

**Feature slug:** `per-card-adaptive-generation`
**Author:** Solution Architect Agent
**Date:** 2026-03-24
**Status:** Ready for implementation

---

## 1. Component Breakdown

| Component | File | Change Type | Single Responsibility |
|-----------|------|-------------|----------------------|
| Config constant | `backend/src/config.py` | Add constant | Declare `NEXT_CARD_MAX_TOKENS` |
| Request/response schemas | `backend/src/api/teaching_schemas.py` | Add models | Define `NextCardRequest`, `NextCardResponse` |
| Router endpoint | `backend/src/api/teaching_router.py` | Add route | Wire `POST /sessions/{id}/next-card` |
| Service method | `backend/src/api/teaching_service.py` | Add method | Implement `generate_per_card()` on `TeachingService` |
| Prompt builder | `backend/src/adaptive/prompt_builder.py` | Extend function | Add `content_piece_text` and `content_piece_images` params to `build_next_card_prompt()` |
| Adaptive engine | `backend/src/adaptive/adaptive_engine.py` | No change | `build_blended_analytics()` accepts `section_count` from history dict — already supported; fix is in service layer |
| Axios wrapper | `frontend/src/api/sessions.js` | Add export | `fetchNextAdaptiveCard(sessionId, cardIndex, signals)` |
| Session reducer | `frontend/src/context/SessionContext.jsx` | Modify | Add `nextCardInFlight` state, fix `NEXT_CARD` reducer, add `APPEND_NEXT_CARD` case, update `goToNextCard()` |

---

## 2. Data Design

### 2.1 Session Cache Structure (existing field — extended)

`TeachingSession.presentation_text` is a PostgreSQL `TEXT` column storing a JSON object. The per-card feature adds no new columns. It reads and writes the same JSON structure, extending `concepts_queue` usage.

```
{
  // --- existing fields ---
  "session_id":              "<uuid>",
  "concept_id":              "<str>",
  "concept_title":           "<str>",
  "cards":                   [ ... ],           // accumulated generated cards (grows each call)
  "concepts_queue":          [ <section_dict>, ... ],  // remaining content pieces (shrinks each call)
  "concepts_covered":        [ "<title>", ... ],
  "concepts_total":          <int>,
  "cache_version":           18,
  "system_prompt":           "<str>",
  "_images":                 [ <image_dict>, ... ],
  "assigned_image_indices":  [ <int>, ... ],
  "session_signals":         [ { "card_index", "time_on_card_sec", "wrong_attempts", "hints_used" }, ... ],

  // --- no new fields required ---
}
```

Each item in `concepts_queue` is a section dict with at minimum:
```json
{
  "title": "<str>",
  "text":  "<str>",
  "section_type": "<str>",
  "_section_index": <int>
}
```

### 2.2 No Schema Changes

No new ORM models, Alembic migrations, or database columns are required for this feature.

### 2.3 Caching Strategy

The session cache is the only storage. After each `generate_per_card()` call:
1. `concepts_queue` has the consumed piece removed from index 0
2. `cards` has the new card appended
3. `concepts_covered` has the new title appended
4. `assigned_image_indices` is updated with newly used image indices

The updated cache is written back to `session.presentation_text` and flushed with `await db.flush()`.

### 2.4 Data Retention

No changes to existing retention policy. `TeachingSession` rows are retained indefinitely until explicit deletion.

---

## 3. API Design

### 3.1 New Endpoint: POST /api/v2/sessions/{session_id}/next-card

**Auth:** Required — `X-API-Key` header (existing `APIKeyMiddleware`)

**Rate limit:** `@limiter.limit("30/minute")`

**Path parameter:** `session_id: UUID`

**Request body (`NextCardRequest`):**

```json
{
  "card_index":        3,          // 0-based index of the card just completed
  "time_on_card_sec":  45.2,       // seconds spent on the completed card
  "wrong_attempts":    1,          // wrong MCQ attempts on the completed card
  "hints_used":        0,          // hints used on the completed card
  "idle_triggers":     0           // idle assistant triggers on the completed card
}
```

**Response body (`NextCardResponse`):**

```json
{
  "session_id":           "<uuid>",
  "card":                 { <LessonCard> },   // null if has_more_concepts=false
  "has_more_concepts":    true,               // false when queue is exhausted
  "current_mode":         "NORMAL",           // "STRUGGLING" | "NORMAL" | "FAST"
  "concepts_covered_count": 4,
  "concepts_total":       9
}
```

**Status codes:**

| Code | Condition |
|------|-----------|
| 200 | Card generated successfully OR queue exhausted (`has_more_concepts=false`, `card=null`) |
| 404 | Session not found |
| 409 | Session phase is not "CARDS" |
| 422 | Request body validation failure |
| 500 | LLM call failed after 3 retries |

**Versioning:** `/api/v2` — consistent with all teaching session endpoints.

### 3.2 Pydantic Models (`teaching_schemas.py`)

```python
class NextCardRequest(BaseModel):
    card_index: int = Field(default=0, ge=0)
    time_on_card_sec: float = Field(default=0.0, ge=0.0)
    wrong_attempts: int = Field(default=0, ge=0)
    hints_used: int = Field(default=0, ge=0)
    idle_triggers: int = Field(default=0, ge=0)


class NextCardResponse(BaseModel):
    session_id: UUID
    card: LessonCard | None = None     # None when has_more_concepts=False
    has_more_concepts: bool
    current_mode: str                  # "STRUGGLING" | "NORMAL" | "FAST"
    concepts_covered_count: int
    concepts_total: int
```

### 3.3 Error Handling Conventions

- All HTTP exceptions use FastAPI `HTTPException` with `detail` string
- LLM failures propagate as `ValueError`; the router catches and re-raises as HTTP 500
- JSON parse failure on `session.presentation_text` is caught, logged with `logger.exception()`, and returns `has_more_concepts=false` (graceful degradation — student moves to Socratic)

---

## 4. Sequence Diagrams

### 4.1 Session Start (unchanged, shown for context)

```
Student browser          SessionContext          Backend
     │                        │                     │
     │── startLesson() ───────►│                     │
     │                        │── POST /sessions ──►│
     │                        │◄── session_id ──────│
     │                        │── POST /cards ──────►│
     │                        │  (generates P1,P2,P3 │
     │                        │   stores queue=[P4..])│
     │                        │◄── cards[3], has_more=true
     │◄── CARDS_LOADED ───────│                     │
     │   (display card P1)    │                     │
```

### 4.2 Per-Card On-Demand Generation (happy path)

```
Student browser          SessionContext          Backend (router → service)
     │                        │                         │
     │── tap Next ────────────►│                         │
     │                        │ state.nextCardInFlight=false?
     │                        │── fetchNextAdaptiveCard() ──────────────────►│
     │                        │  dispatch NEXT_CARD_INFLIGHT               │
     │                        │                         │                   │
     │                        │                         │ parse concepts_queue from cache
     │                        │                         │ pop next_piece = queue[0]
     │                        │                         │ load_student_history() → DB
     │                        │                         │ history["section_count"] += 1
     │                        │                         │ build_blended_analytics() → mode
     │                        │                         │ resolve available images
     │                        │                         │ build_next_card_prompt(piece, images, ...)
     │                        │                         │ _call_llm(gpt-4o-mini, 1200 tokens)
     │                        │                         │ validate + normalise card dict
     │                        │                         │ write updated cache → DB flush
     │                        │◄── NextCardResponse ────────────────────────│
     │                        │  { card, has_more=true, mode }
     │                        │ dispatch APPEND_NEXT_CARD
     │                        │  (cards=[...P4], index advances)
     │◄── renders new card ───│                         │
```

### 4.3 Queue Exhausted (triggers Socratic)

```
Student browser          SessionContext          Backend
     │                        │                     │
     │── tap Next ────────────►│                     │
     │                        │── POST /next-card ──►│
     │                        │                     │ concepts_queue is empty
     │                        │◄── { card=null, has_more=false }
     │                        │ dispatch HAS_NO_MORE_CONCEPTS
     │                        │ → automatically calls finishCards()
     │                        │── POST /complete-cards ──►│
     │                        │── POST /check ───────────►│
     │                        │◄── first Socratic question │
     │◄── CHECKING phase ─────│                     │
```

### 4.4 LLM Failure (graceful degradation)

```
SessionContext          Backend (LLM call fails 3×)
     │                         │
     │── POST /next-card ──────►│
     │                         │ LLM retries 1, 2, 3 — all fail
     │                         │ raises ValueError
     │◄── HTTP 500 ────────────│
     │ catch in goToNextCard() │
     │ log error               │
     │ dispatch NEXT_CARD_ERROR │
     │  (nextCardInFlight=false) │
     │ finishCards() still callable
```

---

## 5. Bug Fixes — Detailed Specifications

### Bug 1 Fix: nextCardInFlight race condition guard (SessionContext.jsx)

**Problem:** `goToNextCard()` has no in-flight guard for per-card requests. If the student taps Next twice rapidly, two concurrent `fetchNextAdaptiveCard()` calls fire. Both pop from the queue and both append cards, resulting in out-of-order cards.

**Fix:**

Add `nextCardInFlight: false` to `initialState`.

Add two new reducer cases:
```js
case "NEXT_CARD_INFLIGHT":
  return { ...state, nextCardInFlight: true };

case "NEXT_CARD_INFLIGHT_DONE":
  return { ...state, nextCardInFlight: false };
```

In `goToNextCard()`, guard the fetch:
```js
if (state.nextCardInFlight) return;   // drop duplicate tap
dispatch({ type: "NEXT_CARD_INFLIGHT" });
// ... fetch ...
// finally: dispatch({ type: "NEXT_CARD_INFLIGHT_DONE" });
```

The `nextCardInFlight` flag must also be used to disable the Next button in `CardLearningView.jsx` so the student receives visual feedback.

### Bug 2 Fix: NEXT_CARD reducer clamps at cards.length-1 (SessionContext.jsx)

**Problem (current code, line 94–96):**
```js
case "NEXT_CARD": {
  const nextIndex = Math.min(
    state.currentCardIndex + 1,
    Math.max(0, state.cards.length - 1)   // BUG: cannot advance past last card
  );
```
When `currentCardIndex === cards.length - 1`, `nextIndex` is clamped to the same value. The student is permanently stuck at the last card even after a new card is appended.

**Fix:** Remove the upper clamp in `NEXT_CARD`. The index should advance freely; the UI already guards `card === undefined` with `if (!card) return null`.

```js
case "NEXT_CARD": {
  const nextIndex = state.currentCardIndex + 1;
  return {
    ...state,
    currentCardIndex: nextIndex,
    maxReachedIndex: Math.max(state.maxReachedIndex, nextIndex),
    idleTriggerCount: 0,
    motivationalNote: null,
    performanceVsBaseline: null,
  };
}
```

Note: `ADAPTIVE_CARD_ERROR` and `ADAPTIVE_CARD_LOADED` reducers that apply their own clamping should be reviewed but are unaffected by this change (they reference `state.cards.length` which is updated before they run in their respective flows).

### Bug 3 Fix: Missing POST /sessions/{id}/next-card endpoint (teaching_router.py)

This endpoint does not exist. It must be added. Full specification is in Section 3.1.

### Bug 4 Fix: section_count never incremented (teaching_service.py)

**Problem:** `load_student_history()` returns `section_count` from `student_row.section_count`. This value comes from the DB column `students.section_count`, which is only incremented by `POST /sessions/{id}/section-complete`. That endpoint is called by the frontend after a rolling section completes. Under per-card generation, `section-complete` is never called because there are no "section completions" in the new flow.

**Fix:** In `generate_per_card()`, after `load_student_history()` returns `history`, increment:
```python
history["section_count"] = history.get("section_count", 0) + 1
```
This locally adjusts the value before passing `history` to `build_blended_analytics()`. It does NOT persist to the DB (that column tracks cross-session totals). The local increment is sufficient to let the blending weights graduate within a session.

For cross-session persistence, a separate fire-and-forget DB update can optionally be added:
```python
await db.execute(
    update(Student)
    .where(Student.id == session.student_id)
    .values(section_count=Student.section_count + 1)
)
```
This is optional in Phase 2 and can be deferred without functional impact.

### Bug 5 Fix: generate_next_card() receives no content piece text (adaptive_engine.py)

**Problem:** The existing `generate_next_card()` function in `adaptive_engine.py` receives `concept_detail` (the full concept dict from KnowledgeService), not the specific sub-section text that should be taught in this card.

**Fix:** This bug is addressed by routing through `build_next_card_prompt()` rather than `generate_next_card()` in the service layer. `generate_per_card()` in `teaching_service.py` constructs a modified `concept_detail` dict for the prompt, overriding `text` with `next_piece["text"]`:

```python
piece_concept_detail = {
    **concept_detail,                        # base keys (title, chapter, section, latex)
    "text": next_piece["text"],              # OVERRIDE: only this piece's text
    "concept_title": next_piece["title"],    # OVERRIDE: piece title as card title context
}
```

This is passed to `build_next_card_prompt()` directly from the service layer. `generate_next_card()` in `adaptive_engine.py` is not called in this flow (it handles a different use case — the `complete-card` recovery path).

### Bug 6 Fix: build_next_card_prompt() has no image injection (prompt_builder.py)

**Problem:** `build_next_card_prompt()` accepts `concept_detail` (which contains an `images` list) but the user prompt assembled in the function does not inject any image descriptions.

**Fix:** Add two new optional parameters to `build_next_card_prompt()`:

```python
def build_next_card_prompt(
    concept_detail: dict,
    learning_profile: LearningProfile,
    gen_profile: GenerationProfile,
    card_index: int,
    history: dict,
    language: str = "en",
    wrong_option_pattern: int | None = None,
    difficulty_bias: str | None = None,
    generate_as: str = "NORMAL",
    blended_state_score: float = 2.0,
    engagement_strategy: str | None = None,
    content_piece_images: list[dict] | None = None,  # NEW
) -> tuple[str, str]:
```

In the user prompt assembly section, after the source material block:
```python
if content_piece_images:
    parts += [
        "",
        "RELEVANT IMAGES FOR THIS CARD:",
    ]
    for img in content_piece_images[:3]:   # cap at 3 images per card
        desc = img.get("description") or img.get("caption") or ""
        img_type = img.get("image_type", "DIAGRAM")
        url = img.get("url", "")
        if desc:
            parts.append(f"  [{img_type}] {desc}" + (f" — {url}" if url else ""))
    parts += [
        "",
        "IMAGE INSTRUCTION: Reference relevant images in your card content using their "
        "description. Prefer diagrams and formulas over decorative images.",
    ]
```

### Bug 7 Fix: card_index=0 hardcoded in initial build_blended_analytics() call (teaching_service.py)

**Problem (existing code in `generate_cards()`, line ~939):**
```python
current_signals = CardBehaviorSignals(
    card_index=0,   # BUG: always 0, ignores actual signal position
    ...
)
```

**Fix:** This is in the *initial* card generation path, not the per-card path. The correct fix for `generate_cards()` is:
```python
current_signals = CardBehaviorSignals(
    card_index=history.get("total_cards_completed", 0),
    ...
)
```
This is a one-line change in `generate_cards()`. It should be applied as part of this feature's Phase 2, as it affects the same code path.

### Bug 8 Fix: No per-card token budget constant (config.py)

**Problem:** There is no named constant for the per-card LLM call token budget. The value is currently hardcoded as `1200` in the `complete-card` endpoint path.

**Fix:** Add to `config.py`:
```python
# ── Per-card adaptive generation token budget ──────────────────────────────
NEXT_CARD_MAX_TOKENS: int = 1200   # Single card: title + content + 1 MCQ + motivational note
```

---

## 6. Service Method Specification: generate_per_card()

### Location
`backend/src/api/teaching_service.py`, as a new `async def` method on `TeachingService`.

### Full Signature
```python
async def generate_per_card(
    self,
    db: AsyncSession,
    session: TeachingSession,
    student: Student,
    req: "NextCardRequest",
) -> dict:
```

### Return shape
```python
{
    "session_id":           str(session.id),
    "card":                 <card_dict | None>,
    "has_more_concepts":    <bool>,
    "current_mode":         <str>,             # "STRUGGLING" | "NORMAL" | "FAST"
    "concepts_covered_count": <int>,
    "concepts_total":       <int>,
}
```

### Step-by-step logic

```
1. Parse cache:
   cached = json.loads(session.presentation_text or "{}")
   concepts_queue = list(cached.get("concepts_queue", []))
   concepts_covered = list(cached.get("concepts_covered", []))
   all_sections_count = cached.get("concepts_total", 1)

2. Empty queue guard:
   IF not concepts_queue:
     RETURN { card=None, has_more_concepts=False, current_mode="NORMAL",
              concepts_covered_count=len(concepts_covered),
              concepts_total=all_sections_count }

3. Pop next piece:
   next_piece = concepts_queue.pop(0)

4. Load history + wrong-option pattern concurrently:
   history, wrong_option_pattern = await asyncio.gather(
       load_student_history(str(session.student_id), session.concept_id, db),
       load_wrong_option_pattern(str(session.student_id), session.concept_id, db),
   )

5. Fix Bug 4 — increment section_count locally:
   history["section_count"] = history.get("section_count", 0) + 1

6. Build blended analytics from live signals:
   current_signals = CardBehaviorSignals(
       card_index=req.card_index,
       time_on_card_sec=req.time_on_card_sec,
       wrong_attempts=req.wrong_attempts,
       hints_used=req.hints_used,
       idle_triggers=req.idle_triggers,
   )
   blended, _blended_score, _generate_as = build_blended_analytics(
       current_signals, history,
       concept_id=session.concept_id,
       student_id=str(session.student_id),
   )
   card_profile = build_learning_profile(blended, has_unmet_prereq=False)

7. Resolve available images (exclude already-assigned):
   cached_images = cached.get("_images", [])
   already_assigned = set(cached.get("assigned_image_indices", []))
   available_images = [img for i, img in enumerate(cached_images) if i not in already_assigned]
   content_piece_images = available_images[:3]   # cap at 3

8. Build gen profile:
   gen_profile = build_generation_profile(card_profile)

9. Build concept_detail for this piece:
   concept_detail_base = self._get_ksvc(session).get_concept_detail(session.concept_id) or {}
   piece_concept_detail = {
       **concept_detail_base,
       "text": next_piece["text"],
       "concept_title": next_piece["title"],
   }

10. Build prompts (Bug 6 fix — pass content_piece_images):
    language = getattr(student, "preferred_language", "en") or "en"
    system_prompt, user_prompt = build_next_card_prompt(
        concept_detail=piece_concept_detail,
        learning_profile=card_profile,
        gen_profile=gen_profile,
        card_index=req.card_index,
        history=history,
        language=language,
        wrong_option_pattern=wrong_option_pattern,
        difficulty_bias=None,
        generate_as=_generate_as,
        blended_state_score=_blended_score,
        content_piece_images=content_piece_images,   # Bug 6 fix
    )

11. Call LLM:
    raw = await self._chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=NEXT_CARD_MAX_TOKENS,
        model="mini",
        timeout=30.0,
    )

12. Parse + validate card:
    cleaned = _extract_json_block(raw)            # strip ```json fences
    cleaned = _fix_latex_backslashes(cleaned)
    for attempt_raw in (cleaned, _salvage_truncated_json(cleaned)):
        try:
            parsed = json.loads(attempt_raw)
            break
        except json.JSONDecodeError:
            continue
    ELSE: raise ValueError("LLM output could not be parsed")
    parsed = _clean_card_string_fields(parsed)
    # Normalise question field (same logic as in generate_cards())
    card_dict = _normalise_single_card(parsed, card_index=len(cached.get("cards", [])))

13. Assign images to card:
    new_assigned = set()
    IF content_piece_images:
        card_dict["images"] = [content_piece_images[0]]   # assign first available image
        new_assigned.add(list(already_assigned)[0] if already_assigned else 0)

14. Update cache and flush:
    cached["concepts_queue"] = concepts_queue           # already popped in step 3
    cached["concepts_covered"] = concepts_covered + [next_piece["title"]]
    cached["cards"] = cached.get("cards", []) + [card_dict]
    cached["assigned_image_indices"] = list(already_assigned | new_assigned)
    session.presentation_text = json.dumps(cached)
    await db.flush()

15. Optional: persist section_count increment to DB (fire-and-forget):
    try:
        await db.execute(
            update(Student)
            .where(Student.id == session.student_id)
            .values(section_count=Student.section_count + 1)
        )
    except Exception:
        logger.warning("section_count_persist_failed: student_id=%s", session.student_id)

16. Build and return result:
    current_mode = {
        "STRUGGLING": "SLOW",
        "NORMAL": "NORMAL",
        "FAST": "FAST",
    }.get(_generate_as, "NORMAL")
    RETURN {
        "session_id":            str(session.id),
        "card":                  card_dict,
        "has_more_concepts":     len(concepts_queue) > 0,
        "current_mode":          current_mode,
        "concepts_covered_count": len(concepts_covered) + 1,
        "concepts_total":         all_sections_count,
    }
```

### Error handling
- `json.loads` failure after retries: raises `ValueError` → router returns HTTP 500
- `load_student_history` failure: caught, defaults applied (same as in `generate_cards()`)
- LLM timeout: `self._chat()` raises; propagates as HTTP 500 after router catch

---

## 7. Router Endpoint Specification (teaching_router.py)

```python
from api.teaching_schemas import NextCardRequest, NextCardResponse

@router.post("/sessions/{session_id}/next-card", response_model=NextCardResponse)
@limiter.limit("30/minute")
async def get_next_adaptive_card(
    request: Request,
    session_id: UUID,
    req: NextCardRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate the next card on demand for per-card adaptive generation."""
    session = await db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.phase != "CARDS":
        raise HTTPException(
            409,
            f"Cannot generate next card: session is in {session.phase} phase"
        )
    student = await db.get(Student, session.student_id)
    if not student:
        raise HTTPException(404, "Student not found")

    try:
        result = await teaching_svc.generate_per_card(db, session, student, req)
    except ValueError as exc:
        logger.exception(
            "[next-card] generation_failed: session_id=%s error=%s",
            session_id, exc,
        )
        raise HTTPException(500, f"Card generation failed: {exc}")

    return NextCardResponse(
        session_id=session.id,
        card=LessonCard(**result["card"]) if result["card"] else None,
        has_more_concepts=result["has_more_concepts"],
        current_mode=result["current_mode"],
        concepts_covered_count=result["concepts_covered_count"],
        concepts_total=result["concepts_total"],
    )
```

Note: The router must import `NextCardRequest` and `NextCardResponse` from `teaching_schemas`, and add them to the existing import block.

---

## 8. Frontend Changes (SessionContext.jsx)

### 8.1 New State Field

```js
const initialState = {
  // ... existing fields ...
  nextCardInFlight: false,    // NEW: prevents duplicate per-card requests
};
```

### 8.2 New Reducer Cases

```js
case "NEXT_CARD_INFLIGHT":
  return { ...state, nextCardInFlight: true };

case "NEXT_CARD_INFLIGHT_DONE":
  return { ...state, nextCardInFlight: false };

case "APPEND_NEXT_CARD": {
  // Appends newly fetched card and auto-advances index
  const newCards = [...state.cards, action.payload.card];
  const newIndex = state.currentCardIndex + 1;
  return {
    ...state,
    cards: newCards,
    currentCardIndex: newIndex,
    maxReachedIndex: Math.max(state.maxReachedIndex, newIndex),
    nextCardInFlight: false,
    hasMoreConcepts: action.payload.has_more_concepts,
    conceptsTotal: action.payload.concepts_total,
    conceptsCoveredCount: action.payload.concepts_covered_count,
    idleTriggerCount: 0,
    motivationalNote: null,
  };
}

case "HAS_NO_MORE_CONCEPTS":
  return {
    ...state,
    hasMoreConcepts: false,
    nextCardInFlight: false,
  };
```

### 8.3 NEXT_CARD Reducer Fix (Bug 2)

```js
// BEFORE (buggy):
case "NEXT_CARD": {
  const nextIndex = Math.min(
    state.currentCardIndex + 1,
    Math.max(0, state.cards.length - 1)   // clamps — student stuck
  );
  ...
}

// AFTER (fixed):
case "NEXT_CARD": {
  const nextIndex = state.currentCardIndex + 1;
  return {
    ...state,
    currentCardIndex: nextIndex,
    maxReachedIndex: Math.max(state.maxReachedIndex, nextIndex),
    idleTriggerCount: 0,
    motivationalNote: null,
    performanceVsBaseline: null,
  };
}
```

### 8.4 Updated goToNextCard() Logic

```js
const goToNextCard = useCallback(
  async (signals) => {
    if (!state.session || !signals) {
      dispatch({ type: "NEXT_CARD" });
      return;
    }

    // [CASE A: recovery card — unchanged]
    if (signals?.wrongAttempts >= 2 && signals?.reExplainCardTitle) {
      // ... existing recovery card logic unchanged ...
      return;
    }

    // [CASE B: per-card on-demand generation — NEW]
    // Fire when student is on the last pre-generated card AND more content exists
    const isAtLastCard = state.currentCardIndex >= state.cards.length - 1;

    if (isAtLastCard && state.hasMoreConcepts && !state.nextCardInFlight) {
      dispatch({ type: "NEXT_CARD_INFLIGHT" });
      try {
        const res = await fetchNextAdaptiveCard(state.session.id, {
          card_index:        signals.cardIndex ?? state.currentCardIndex,
          time_on_card_sec:  signals.timeOnCardSec ?? 0,
          wrong_attempts:    signals.wrongAttempts ?? 0,
          hints_used:        signals.hintsUsed ?? 0,
          idle_triggers:     signals.idleTriggers ?? 0,
        });

        if (res.data.card) {
          dispatch({ type: "APPEND_NEXT_CARD", payload: res.data });
          if (res.data.learning_profile_summary) {
            useAdaptiveStore.getState().updateMode(res.data.learning_profile_summary);
          }
        } else {
          // Queue exhausted — no more cards to generate
          dispatch({ type: "HAS_NO_MORE_CONCEPTS" });
          dispatch({ type: "NEXT_CARD_INFLIGHT_DONE" });
          // Transition to Socratic automatically
          await finishCardsInternal(signals);
        }
      } catch (err) {
        console.error("[per-card] fetchNextAdaptiveCard failed:", err);
        dispatch({ type: "NEXT_CARD_INFLIGHT_DONE" });
        // Graceful degradation: if no more cards anyway, try to finish
        if (!state.hasMoreConcepts) {
          await finishCardsInternal(signals);
        }
      }
      return;
    }

    // [CASE C: pre-generated cards remain — record interaction and advance]
    // Deprecated rolling section prefetch (CASE B in old code) is removed.
    try {
      await recordCardInteraction(state.session.id, signals);
    } catch (err) {
      console.error("[card] recordCardInteraction failed:", err);
    }
    dispatch({ type: "NEXT_CARD" });
  },
  [
    state.session,
    state.cards.length,
    state.currentCardIndex,
    state.hasMoreConcepts,
    state.nextCardInFlight,
  ]
);
```

Note: `finishCardsInternal` is a helper that wraps the existing `finishCards` logic without the `cardAnswers` tracking event. This avoids duplicating the Socratic transition logic. Alternatively, the existing `finishCards()` function can be called directly after ensuring the last interaction is recorded.

The `useCallback` dependency array must include `state.nextCardInFlight` to prevent stale closure issues.

---

## 9. Axios Wrapper (sessions.js)

```js
const NEXT_CARD_TIMEOUT = 30_000; // 30 s — matches backend LLM timeout

export const fetchNextAdaptiveCard = (sessionId, signals) =>
  api.post(
    `/api/v2/sessions/${sessionId}/next-card`,
    {
      card_index:        signals.card_index ?? 0,
      time_on_card_sec:  signals.time_on_card_sec ?? 0,
      wrong_attempts:    signals.wrong_attempts ?? 0,
      hints_used:        signals.hints_used ?? 0,
      idle_triggers:     signals.idle_triggers ?? 0,
    },
    { timeout: NEXT_CARD_TIMEOUT }
  );
```

Import in `SessionContext.jsx`:
```js
import { fetchNextAdaptiveCard, ... } from "../api/sessions";
```

---

## 10. config.py Change

```python
# ── Per-card adaptive generation token budget ──────────────────────────────
# Single-card response: title + content (max 6 lines) + 1 MCQ + motivational note.
# 1200 tokens ≈ 900 words output — sufficient for a full card at all modes.
# Do not raise above 2000 without testing latency against p99 target of 10 s.
NEXT_CARD_MAX_TOKENS: int = 1200
```

Add the import to `teaching_service.py`:
```python
from config import (
    ...,
    NEXT_CARD_MAX_TOKENS,
)
```

---

## 11. Security Design

- **Authentication:** `APIKeyMiddleware` is applied globally; new endpoint inherits this. No changes required.
- **Rate limiting:** `@limiter.limit("30/minute")` — consistent with other session write endpoints.
- **Input validation:** Pydantic `NextCardRequest` validates all numeric fields with `ge=0` constraints.
- **Content injection:** `next_piece["text"]` is hard-truncated at `_CONCEPT_TEXT_LIMIT = 3000` chars by `build_next_card_prompt()` (existing guard in prompt builder).
- **Session ownership:** The endpoint does not verify that the authenticated caller owns the session. This is consistent with existing teaching endpoints (no per-student auth — global API key only). No regression introduced.

---

## 12. Observability Design

### Logging
Add structured log entry at INFO level in `generate_per_card()`:
```python
logger.info(
    "[per-card] generated: session_id=%s concept_id=%s piece='%s' "
    "section_count=%d generate_as=%s blended_score=%.2f has_more=%s duration_ms=%d",
    str(session.id), session.concept_id, next_piece["title"],
    history["section_count"], _generate_as, _blended_score,
    len(concepts_queue) > 0, round((time.monotonic() - start_ts) * 1000),
)
```

Add WARN log on empty queue:
```python
logger.info(
    "[per-card] queue_exhausted: session_id=%s concept_id=%s covered=%d total=%d",
    str(session.id), session.concept_id, len(concepts_covered), all_sections_count,
)
```

### Metrics (existing PostHog)
Add frontend tracking in `goToNextCard()` after successful fetch:
```js
trackEvent("per_card_generated", {
  session_id: state.session.id,
  card_index: res.data.concepts_covered_count,
  current_mode: res.data.current_mode,
  has_more: res.data.has_more_concepts,
});
```

### Alerting
No new alerts required. Existing alert on HTTP 500 rate covers LLM failures in this path.

---

## 13. Error Handling and Resilience

| Failure Scenario | Detection | Handling |
|-----------------|-----------|----------|
| LLM call times out (30 s) | `asyncio.TimeoutError` from `_chat()` | Propagates as HTTP 500; frontend catches, logs, does not advance index, keeps Next button enabled |
| LLM returns malformed JSON | `json.JSONDecodeError` after 3 repair attempts | Raises `ValueError`; router returns HTTP 500; frontend as above |
| `session.presentation_text` is null/invalid JSON | `json.JSONDecodeError` | Caught in `generate_per_card()`; returns `has_more_concepts=false`; student moves to Socratic |
| Student taps Next twice rapidly | Second call blocked by `nextCardInFlight` flag | First call proceeds normally; second call is a no-op |
| `load_student_history()` fails | Exception caught | Defaults applied (empty history); card still generated with cold-start weights |
| `concepts_queue` is empty | Queue length check at start of method | Returns `{ card=None, has_more_concepts=False }` immediately with no LLM call |

### Retry policy
The LLM call is wrapped in `self._chat()` which implements 3 attempts with exponential back-off (2 s, 4 s). This is consistent with all other LLM calls in the system.

---

## 14. Testing Strategy

### Unit tests (backend)

| Test | What it verifies |
|------|-----------------|
| `test_generate_per_card_happy_path` | Pops from queue, returns card, `has_more=true` |
| `test_generate_per_card_last_piece` | Last piece popped, `has_more=false`, `card` returned |
| `test_generate_per_card_empty_queue` | Empty queue returns `has_more=false, card=None` without LLM call |
| `test_generate_per_card_section_count_incremented` | `history["section_count"]` is `initial + 1` when passed to blended analytics |
| `test_generate_per_card_image_injection` | `content_piece_images` is passed to `build_next_card_prompt` when available |
| `test_next_card_reducer_boundary` | `NEXT_CARD` does not clamp at `cards.length - 1` |
| `test_next_card_inflight_guard` | Second dispatch is dropped when `nextCardInFlight=true` |
| `test_build_next_card_prompt_with_images` | Image block appears in user prompt when `content_piece_images` provided |
| `test_build_next_card_prompt_without_images` | Image block absent when `content_piece_images=None` |

### Integration tests

| Test | What it verifies |
|------|-----------------|
| `test_post_next_card_endpoint` | Round-trip: POST /next-card returns valid `NextCardResponse` |
| `test_post_next_card_wrong_phase` | HTTP 409 when session.phase != "CARDS" |
| `test_post_next_card_not_found` | HTTP 404 when session_id is unknown |
| `test_post_next_card_depletes_queue` | After N calls, `has_more_concepts=false` |

### Frontend tests

| Test | What it verifies |
|------|-----------------|
| `goToNextCard_inflight_guard` | Second call returns early when `nextCardInFlight=true` |
| `APPEND_NEXT_CARD_reducer` | Cards array grows; index advances to new card position |
| `HAS_NO_MORE_CONCEPTS_reducer` | `hasMoreConcepts` set to false; `nextCardInFlight` cleared |
| `NEXT_CARD_boundary_fix` | Index can advance from `cards.length - 1` to `cards.length` |

### Performance test
- Verify per-card p99 latency < 10 s under 10 concurrent sessions
- Verify no DB lock contention on `session.presentation_text` writes

---

## Key Decisions Requiring Stakeholder Input

1. **section_count DB persistence:** The fix increments `section_count` locally in memory for blending. Persisting it to `students.section_count` (fire-and-forget UPDATE) is optional in Phase 2. If cross-session blending accuracy is important, persist it; if not, skip to reduce DB write volume.

2. **Auto-transition to Socratic on empty queue:** The DLD specifies that when `fetchNextAdaptiveCard()` returns `has_more_concepts=false`, the frontend automatically calls `finishCards()`. An alternative is to show a "Continue to Final Check" button and let the student trigger it manually. Confirm which UX is intended.

3. **Image cap per card:** The DLD caps images at 3 per card in the prompt injection. Confirm whether this is acceptable or if image injection should be skipped entirely for per-card generation to reduce prompt tokens.
