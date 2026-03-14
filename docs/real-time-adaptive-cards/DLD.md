# Detailed Low-Level Design — Real-Time Adaptive Cards

**Feature slug:** `real-time-adaptive-cards`
**Date:** 2026-03-10
**Author:** Solution Architect

---

## 1. Component Breakdown

### 1.1 `teaching_service.py` — `generate_cards()`

**Responsibility:** Produce the session's initial starter-pack cards from the first `STARTER_PACK_MAX_SECTIONS` (= 2) topic sections of the concept text.

**Key changes in this feature:**

| Change | Location | Purpose |
|--------|----------|---------|
| Cache version guard | lines 576–589 | Discard sessions cached at `cache_version < 3` |
| Starter pack slice | lines 613–619 | Limit initial generation to 2 sections |
| Per-section parallel generation | `_generate_cards_per_section()` | Parallel `asyncio.gather` — one LLM call per section |
| Text-driven token budget | lines 1103–1110 | `max(budget//2, min(budget, text_len//3))` per section |
| Gap-fill sort | lines 820–830 | `_section_order_key` restores curriculum order after extend |
| VISUAL image fallback | lines 969–999 | Keyword-scoring assigns image to image-less VISUAL cards |

**Interface contract (unchanged):**
```
Input:  db: AsyncSession, session: TeachingSession, student: Student
Output: dict  {
  "session_id": str,
  "concept_id": str,
  "concept_title": str,
  "cards": list[dict],
  "cache_version": int,
  ...
}
```

### 1.2 `adaptive_router.py` — `complete_card()`

**Responsibility:** Accept the student's card-completion signals, record them, generate an adaptive next card, append it to the session cache preserving the JSON envelope, and return the card with metadata.

**Key changes in this feature:**

| Change | Location | Purpose |
|--------|----------|---------|
| Envelope-preserving cache write | lines 280–291 | Keep `cache_version`, `concept_title`, etc. intact |
| `_ADAPTIVE_CARD_CEILING = 20` | line 31 | Module-level constant replacing old `config.py` constant |
| Dual-format cache read | lines 217–224 | Handles both `list` (legacy) and `dict` (envelope) formats |

**Interface contract:**
```
POST /api/v2/sessions/{session_id}/complete-card
Rate limit: 60/minute

Request body: NextCardRequest
  card_index:         int
  time_on_card_sec:   float
  wrong_attempts:     int
  selected_wrong_option: str | None
  hints_used:         int
  idle_triggers:      int
  difficulty_bias:    "TOO_EASY" | "TOO_HARD" | None

Response: NextCardResponse (200)
  session_id:               UUID
  card:                     dict
  card_index:               int
  adaptation_applied:       str | None
  learning_profile_summary: { speed, comprehension, engagement, confidence_score }
  motivational_note:        str | None
  performance_vs_baseline:  "FASTER" | "SLOWER" | "ON_TRACK" | None

409 — ceiling reached:    { "ceiling": true }
400 — wrong phase
404 — session not found
502 — LLM failed
```

### 1.3 `SessionContext.jsx` — Rolling Adaptive Replace

**Responsibility:** Advance the student immediately on card answer, fire a background adaptive call, and silently replace the upcoming card slot with the personalised result.

**Key state fields:**

| Field | Type | Purpose |
|-------|------|---------|
| `cards` | `Card[]` | Full card array — starter pack + adaptive replacements |
| `currentCardIndex` | `number` | Zero-based index of the displayed card |
| `adaptiveCallInFlight` | `boolean` | Dedup guard — only one `complete-card` call at a time |
| `adaptiveCardLoading` | `boolean` | Spinner shown only when student has consumed all prepared cards |

**Key reducer actions:**

| Action | Behaviour |
|--------|-----------|
| `NEXT_CARD` | Clamps increment to `cards.length - 1` |
| `ADAPTIVE_CALL_STARTED` | Sets `adaptiveCallInFlight = true` |
| `REPLACE_UPCOMING_CARD` | Targets `currentCardIndex + 1`; replace or append |
| `ADAPTIVE_CALL_DONE` | Clears `adaptiveCallInFlight` flag (always in `finally`) |
| `ADAPTIVE_CARD_ERROR` | Clears loading; clamps index; no crash |

---

## 2. Data Design

### 2.1 Session Cache (`teaching_sessions.presentation_text`)

The `presentation_text` column stores the full card set as a JSON string. Two historical formats exist; the router handles both.

**Format A (legacy — raw list, created before this feature):**
```json
[
  { "index": 0, "title": "...", "content": "...", ... },
  { "index": 1, ... }
]
```

**Format B (envelope — created by `generate_cards()` after this feature):**
```json
{
  "cache_version": 3,
  "session_id": "...",
  "concept_id": "...",
  "concept_title": "...",
  "total_questions": 4,
  "cards": [
    { "index": 0, "title": "...", "card_type": "CONCEPT", ... },
    { "index": 1, ... }
  ]
}
```

The `cache_version` key is the authoritative indicator. Any value below 3 triggers discard and regeneration.

**Cache busting logic (pseudocode):**
```
if session.presentation_text is not None:
    cached = JSON.parse(presentation_text)
    if "cards" in cached:
        if cached.cache_version < 3:
            raise ValueError("stale cache version")  → regenerate
        if has_new_schema AND not is_stale:
            return cached  → cache hit
```

### 2.2 `card_interactions` Table (unchanged schema)

Each call to `complete_card()` persists one row immediately — before any LLM call — to guarantee signal persistence even if the LLM times out.

| Column | Type | Set by |
|--------|------|--------|
| `session_id` | UUID FK | `complete_card()` |
| `student_id` | UUID FK | copied from session |
| `concept_id` | str | copied from session |
| `card_index` | int | `req.card_index` |
| `time_on_card_sec` | float | `req.time_on_card_sec` |
| `wrong_attempts` | int | `req.wrong_attempts` |
| `selected_wrong_option` | str | `req.selected_wrong_option` |
| `hints_used` | int | `req.hints_used` |
| `idle_triggers` | int | `req.idle_triggers` |
| `adaptation_applied` | str | written after LLM returns |

### 2.3 Caching Strategy

- **Read path:** `generate_cards()` returns cached envelope if `cache_version >= 3` and schema is valid.
- **Write path — initial generation:** full envelope stored in `presentation_text`.
- **Write path — adaptive card append:** `complete_card()` reads envelope, mutates `cards` list in-place, writes envelope back. This preserves `cache_version` so subsequent page reloads continue to hit the cache.
- **Invalidation:** Only manual DB clear, or cache version bump in code.

---

## 3. API Design

See component contracts in Section 1. No new endpoints introduced by this feature — it wires existing endpoints together differently.

### Versioning
Both endpoints are under `/api/v2` as established. The adaptive lesson batch generation remains at `/api/v3/adaptive/lesson`.

### Error Handling Conventions

| HTTP code | Meaning | Frontend handling |
|-----------|---------|-------------------|
| 200 | Card generated | `REPLACE_UPCOMING_CARD` dispatch |
| 400 | Session in wrong phase | `ADAPTIVE_CARD_ERROR` dispatch; existing card shown |
| 404 | Session not found | `ADAPTIVE_CARD_ERROR` dispatch |
| 409 | Ceiling reached | `NEXT_CARD` dispatch only; no more LLM calls |
| 502 | LLM failure | `ADAPTIVE_CARD_ERROR` dispatch |

---

## 4. Sequence Diagrams

### 4.1 Session Start — Starter Pack

```
Student                   Frontend                    Backend
  |                          |                           |
  | clicks "Start Lesson"    |                           |
  |─────────────────────────►|                           |
  |                          | POST /sessions            |
  |                          |──────────────────────────►|
  |                          |  ← session_id             |
  |                          |                           |
  |                          | GET /sessions/{id}/cards  |
  |                          |──────────────────────────►|
  |                          |            generate_cards() begins
  |                          |            parse_sub_sections()
  |                          |            group_by_major_topic()
  |                          |            slice to [:STARTER_PACK_MAX_SECTIONS=2]
  |                          |            _generate_cards_per_section() [parallel]
  |                          |              section 0 → LLM (text_driven_budget)
  |                          |              section 1 → LLM (text_driven_budget)
  |                          |            gap-fill check → sort by _section_order_key
  |                          |            VISUAL fallback → keyword scoring
  |                          |            return envelope {cache_version:3, cards:[...]}
  |                          |  ← {cards: [c0, c1, ...], cache_version:3}
  |                          |                           |
  |                          | CARDS_LOADED dispatch      |
  |  ← card 0 displayed      |                           |
```

### 4.2 Student Answers Card — Rolling Replace Loop

```
Student                   Frontend (SessionContext)       Backend
  |                          |                               |
  | answers MCQ on card N    |                               |
  |─────────────────────────►|                               |
  |                          | dispatch NEXT_CARD (sync)     |
  |  ← card N+1 shown        |   (uses pre-generated card)   |
  |    immediately           |                               |
  |                          | adaptiveCallInFlight?          |
  |                          |   yes → recordCardInteraction only
  |                          |   no  → dispatch ADAPTIVE_CALL_STARTED
  |                          |         completeCardAndGetNext(session.id, signals)
  |                          |──────────────────────────────►|
  |                          |           POST /api/v2/sessions/{id}/complete-card
  |                          |           1. Save CardInteraction (flush+commit)
  |                          |           2. Check ceiling (20)
  |                          |           3. load_student_history()
  |                          |           4. load_mastery_store()
  |                          |           5. generate_next_card() [LLM]
  |                          |           6. compute performance_vs_baseline
  |                          |           7. envelope-preserving cache write
  |                          |  ← NextCardResponse {card, learning_profile_summary, ...}
  |                          |                               |
  |                          | dispatch REPLACE_UPCOMING_CARD|
  |                          |   targetIndex = N+2           |
  |                          |   if slot exists: replace     |
  |                          |   else: append                |
  |                          | dispatch ADAPTIVE_CALL_DONE   |
  |                          |                               |
  |  card N+2 is now         |                               |
  |  personalised when       |                               |
  |  student arrives         |                               |
```

### 4.3 LLM Failure During Adaptive Call

```
Frontend                    Backend
  |                            |
  | completeCardAndGetNext()   |
  |───────────────────────────►|
  |                            | generate_next_card() raises Exception
  |                            | HTTP 502 returned
  |  ← 502                     |
  |                            |
  | dispatch ADAPTIVE_CARD_ERROR
  |   adaptiveCardLoading = false
  |   adaptiveCallInFlight = false (in finally)
  |   currentCardIndex clamped to cards.length-1
  |                            |
  | Student continues on existing
  | pre-generated card — no crash
```

---

## 5. Integration Design

### 5.1 Starter Pack → Adaptive Loop Handoff

The starter pack and adaptive loop share `session.presentation_text` as their coordination medium. The starter pack writes the envelope with `cache_version: 3`. The adaptive loop reads the envelope, extracts the `cards` list, appends to it, and writes the full envelope back. Neither path knows about the other's internal logic — they coordinate only through the shared DB column.

### 5.2 Frontend → Backend Signal Flow

`goToNextCard(signals)` in `SessionContext.jsx` is the single integration point. It:
1. Dispatches `NEXT_CARD` synchronously (non-blocking).
2. Fires `completeCardAndGetNext(session.id, signals)` asynchronously.
3. On success, dispatches `REPLACE_UPCOMING_CARD`.
4. Always dispatches `ADAPTIVE_CALL_DONE` in `finally`.

The `signals` object maps directly to `NextCardRequest` fields. No transformation occurs at the API layer.

### 5.3 Retry and Timeout

`complete_card()` relies on `generate_next_card()` in `adaptive_engine.py`, which uses the LLM retry pattern established across the codebase: 3 attempts, `asyncio.sleep(2 * attempt)` back-off, `ValueError` raised after exhaustion, which is caught in `complete_card()` and re-raised as HTTP 502.

---

## 6. Security Design

### 6.1 Rate Limiting

| Endpoint | Limit | Rationale |
|----------|-------|-----------|
| `POST /complete-card` | 60/minute | Prevents rapid-fire card spam inflating LLM costs |
| `POST /api/v3/adaptive/lesson` | 10/minute | Heavy endpoint; full lesson generation |

Rate limits are enforced by `slowapi` via `@limiter.limit(...)` decorator in `adaptive_router.py`. The `limiter` instance is imported from `api.rate_limiter`.

### 6.2 Input Validation

All request fields are validated by Pydantic (`NextCardRequest`). The `card_index` must be a non-negative integer. `time_on_card_sec` must be a float. Unknown fields are rejected by Pydantic v2 strict mode by default.

### 6.3 Session Ownership

`complete_card()` loads the session by `session_id` from the DB and verifies the phase (`PRESENTING` or `CARDS`) before proceeding. No ownership check against `student_id` is performed at this layer — this is documented as a known technical debt in the platform hardening audit (C1 per-student authorisation deferred).

---

## 7. Observability Design

### 7.1 Log Events

All log statements use `logger = logging.getLogger(__name__)` with structured key=value pairs in the message string (ADA convention).

| Event | Level | Fields | Trigger |
|-------|-------|--------|---------|
| Starter pack limit applied | INFO | `concept_id`, `total_sections`, `starter_sections`, `remaining_via_adaptive` | Any concept with > 2 sections |
| Token budget computed | INFO | `concept_id`, `n_sections`, `profile_speed`, `profile_comprehension`, `max_tokens` | Every card generation call |
| Section grouping stats | INFO | `raw_sections`, `grouped_sections` | After `_group_by_major_topic()` |
| Gap-fill needed | WARNING | `n_missing`, `missing_titles[]` | When sections produce no card |
| VISUAL image fallback | INFO | `card_title`, `image_index`, `keyword_score` | Per VISUAL card without LLM-assigned image |
| Stale cache discarded | implicit via ValueError | — | cache_version < 3 |
| Adaptive card generated | INFO | `session_id`, `concept_id`, `card_index`, `adaptation_applied` | Every complete-card call |

### 7.2 Metrics (existing PostHog)

The `goToNextCard` function in SessionContext fires `adaptiveStore.awardXP(5)` on every successful adaptive card, which feeds the Zustand `adaptiveStore` for the gamification layer. No new custom metrics are required for this feature specifically.

### 7.3 Error Tracing

Adaptive LLM failures are logged at ERROR level in `complete_card()` before raising HTTP 502:
```python
logger.error("generate_next_card failed: %s", exc)
```
Frontend catches HTTP 502 in the `goToNextCard` catch block and dispatches `ADAPTIVE_CARD_ERROR`.

---

## 8. Key Implementation Details

### 8.1 `_CARDS_CACHE_VERSION = 3`

Defined as a local constant inside `generate_cards()` at line 576. Bumping this value to 4 in a future change will automatically force all existing sessions to regenerate their card sets the next time a student opens the session — no DB migration required, just a code change and deploy.

The check that reads `cached.get("cache_version", 0) < _CARDS_CACHE_VERSION` treats absent `cache_version` as version 0, which means any legacy session without this key is automatically treated as stale.

### 8.2 Starter Pack — `STARTER_PACK_MAX_SECTIONS = 2`

Defined in `config.py` at line 54. Applied in `generate_cards()`:

```python
if len(sub_sections) > STARTER_PACK_MAX_SECTIONS:
    sub_sections = sub_sections[:STARTER_PACK_MAX_SECTIONS]
```

The remaining sections are not tracked or queued. The adaptive loop's per-card LLM call generates content for the next section on demand, driven by the student's live signals — not by a pre-determined section list.

### 8.3 Text-Driven Token Budget

Each section in `_generate_cards_per_section()` computes its own token ceiling:

```python
text_len = len(sec.get("text", ""))
text_driven_budget = max(
    max_tokens_per_section // 2,       # floor: never below half the profile budget
    min(max_tokens_per_section,        # ceiling: never above profile budget
        text_len // 3),                # heuristic: 1 output token per 3 chars input
)
```

The `max_tokens_per_section` itself is profile-adaptive:
- SLOW or STRUGGLING: `min(16000, max(8000, n × 1800))`
- NORMAL: `min(12000, max(6000, n × 1200))`
- FAST + STRONG: `min(8000, max(4000, n × 900))`

This two-level budget (profile ceiling + text-driven per-section) prevents over-spending tokens on short sections while still providing enough budget for dense sections.

### 8.4 `REPLACE_UPCOMING_CARD` Reducer

```javascript
case "REPLACE_UPCOMING_CARD": {
  const targetIndex = state.currentCardIndex + 1;
  const newCards = [...state.cards];
  if (targetIndex < newCards.length) {
    // Replace the pre-generated placeholder at that slot
    newCards[targetIndex] = { ...action.payload.card, index: targetIndex };
  } else {
    // Append if no slot exists yet (student is at the last prepared card)
    newCards.push({ ...action.payload.card, index: newCards.length });
  }
  return {
    ...state,
    cards: newCards,
    adaptiveCardLoading: false,
    adaptiveCallInFlight: false,
    motivationalNote: action.payload.motivational_note ?? null,
    learningProfileSummary: action.payload.learning_profile_summary ?? null,
    adaptationApplied: action.payload.adaptation_applied ?? null,
  };
}
```

The `index` field is re-stamped to `targetIndex` so that the card's self-reported position matches its array position after replacement.

### 8.5 `adaptiveCallInFlight` Concurrency Guard

In `goToNextCard()`:

```javascript
if (state.adaptiveCallInFlight) {
  // Only record the interaction — no second LLM call
  recordCardInteraction(state.session.id, signals).catch(...)
  return;
}
dispatch({ type: "ADAPTIVE_CALL_STARTED" });
try {
  const res = await completeCardAndGetNext(...)
  dispatch({ type: "REPLACE_UPCOMING_CARD", payload: res.data });
} catch (err) {
  dispatch({ type: "ADAPTIVE_CARD_ERROR" });
} finally {
  dispatch({ type: "ADAPTIVE_CALL_DONE" });
}
```

The `finally` block guarantees the flag is always cleared, even on LLM failure, preventing the guard from permanently locking out future adaptive calls.

The `useCallback` dependency array includes `state.adaptiveCallInFlight` and `state.currentCardIndex` to prevent stale-closure bugs where the guard check reads an outdated flag value.

### 8.6 Envelope Preservation

Before this fix, `complete_card()` wrote `session.presentation_text = json.dumps(existing_cards)` — a raw list. This destroyed the `cache_version`, `concept_title`, and other fields from the envelope that `generate_cards()` had written.

The fix reads the existing JSON, detects whether it is an envelope dict or a raw list, and writes back accordingly:

```python
if session.presentation_text:
    envelope = json_mod.loads(session.presentation_text)
    if isinstance(envelope, dict) and "cards" in envelope:
        envelope["cards"] = existing_cards
        session.presentation_text = json_mod.dumps(envelope)
    else:
        session.presentation_text = json_mod.dumps(existing_cards)
```

The dual-format read earlier in the function handles sessions that were created before the envelope format existed:

```python
if isinstance(parsed, list):
    existing_cards = parsed              # legacy format
elif isinstance(parsed, dict) and "cards" in parsed:
    existing_cards = parsed["cards"]     # envelope format
```

### 8.7 Gap-Fill Sort — `_section_order_key`

After `_generate_cards_per_section()` returns, a second pass checks for sections that produced no card (`_find_missing_sections`). Gap-fill cards are generated and appended to the list. To restore curriculum order, the list is sorted using:

```python
sec_order = {sec["title"].lower(): i for i, sec in enumerate(sub_sections)}

def _section_order_key(card: dict) -> int:
    card_text = (card.get("title", "") + " " + card.get("content", "")).lower()
    for title_lower, order in sec_order.items():
        if title_lower in card_text:
            return order
    return len(sub_sections)  # unknown section → sort to end
```

This is a substring match against the card's full text, not just its title — more robust to LLM paraphrasing. Cards whose section cannot be identified are sorted to the end rather than removed.

### 8.8 VISUAL Image Fallback — Keyword Scoring

For any VISUAL-typed card that the LLM did not assign images to, a fallback runs after the primary image-assignment pass:

1. Build `unassigned` pool: images not yet claimed by any card.
2. For each image-less VISUAL card:
   - If `unassigned` is non-empty, use it as the pool.
   - If `unassigned` is empty, fall back to sharing any already-assigned image (pool = all images).
   - Score each candidate: count words in the card text (length > 3) that appear in the image's vision description.
   - Assign the highest-scoring candidate.
3. Remove the assigned image from `unassigned` to prevent duplicate assignment from the unassigned pool.

This ensures every VISUAL card has an illustration. In the worst case (no unassigned images, very low keyword overlap) the card receives the image with the best available match score, which may be low but is still better than no image.

---

## 9. Testing Strategy

### 9.1 Unit Tests

| Test | Covers |
|------|--------|
| `test_starter_pack_limit` | Verify `generate_cards()` slices to 2 sections when concept has 5+ sections |
| `test_cache_version_bust_v1` | Stale v1 cache is discarded; fresh cards returned |
| `test_cache_version_bust_v2` | Stale v2 cache is discarded |
| `test_cache_hit_v3` | Valid v3 cache is returned without LLM call |
| `test_text_driven_budget_short_section` | Short text (< budget//2 × 3 chars) uses floor |
| `test_text_driven_budget_long_section` | Long text (> budget × 3 chars) uses ceiling |
| `test_gap_fill_sort` | Cards returned out-of-order are re-sorted to curriculum position |
| `test_visual_fallback_assigned` | VISUAL card without image_indices receives best keyword match |
| `test_visual_fallback_pool_exhausted` | When all images are assigned, sharing fallback applies |
| `test_envelope_preserve_on_append` | `complete_card()` preserves `cache_version` after appending |
| `test_envelope_legacy_list` | Legacy list format is read correctly |
| `test_replace_upcoming_card_replace` | Reducer replaces slot at currentIndex+1 |
| `test_replace_upcoming_card_append` | Reducer appends when slot does not exist |
| `test_adaptive_call_inflight_guard` | Second rapid call records interaction but does not fire LLM |
| `test_adaptive_card_error_clamps_index` | `ADAPTIVE_CARD_ERROR` does not push index past cards.length |

### 9.2 Integration Tests

- `test_complete_card_e2e`: Full HTTP call — creates session, generates starter pack, calls complete-card, verifies response shape and DB state.
- `test_complete_card_ceiling`: After 20 adaptive completions, endpoint returns HTTP 409.
- `test_complete_card_wrong_phase`: Session in COMPLETED phase returns HTTP 400.

### 9.3 Performance Baseline

Per-card LLM latency target: < 5 s (p95) on `gpt-4o-mini`. If exceeded, the frontend loading spinner should appear for no more than the excess duration. No load test is required at this stage; latency is monitored via existing OpenAI API response time logs.

---

## Key Decisions Requiring Stakeholder Input

1. **`_ADAPTIVE_CARD_CEILING = 20`** is defined as a module-level constant in `adaptive_router.py`, not in `config.py`. If product wants this to be operator-configurable, it should be moved to `config.py`.
2. **Starter pack does not queue remaining sections.** The adaptive loop drives section coverage entirely reactively. If a student finishes all starter pack cards and then navigates away, subsequent concepts sections are never covered. Confirm this is acceptable for the product.
3. **No ownership verification in `complete_card()`** — any valid session_id can have cards completed by any authenticated caller. Per-student authorisation is deferred (platform hardening scope).
