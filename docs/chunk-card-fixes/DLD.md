# DLD — Chunk Card Fixes

**Feature slug:** `chunk-card-fixes`
**Date:** 2026-03-28
**Author:** solution-architect

---

## 1. Component Breakdown

| Component | File | Responsibility in this feature |
|-----------|------|-------------------------------|
| `TeachingService.generate_per_chunk` | `backend/src/api/teaching_service.py` ~line 1369 | Generates all cards for one chunk; target of Fixes 1, 2, 3, 8 |
| `_CARD_MODE_DELIVERY` dict | `backend/src/adaptive/prompt_builder.py` line 36 | Per-mode LLM instruction blocks; extended by Fix 2B |
| `goToNextChunk` callback | `frontend/src/context/SessionContext.jsx` ~line 720 | Advances to next chunk; rewritten by Fix 4 |
| `CHUNK_ADVANCE` reducer case | `frontend/src/context/SessionContext.jsx` ~line 273 | Applies pre-fetched cards; guarded by Fix 4 |
| Recovery card wiring in `goToNextCard` | `frontend/src/context/SessionContext.jsx` ~line 516 | Triggers recovery/RECAP on MCQ failure; modified by Fix 5 |
| Locale files | `frontend/src/locales/*.json` (13 files) | i18n strings; extended by Fix 6 |

---

## 2. Data Design

### No schema changes
All fixes are in service layer logic and prompt strings. No new DB columns, no new Alembic migration, no new ChromaDB fields.

### Session cache format (existing, extended by Fix 3)
`session.presentation_text` is a JSON string dict. Fix 3 ensures `current_mode` is written on every chunk generation call.

```json
{
  "current_mode": "STRUGGLING",
  "section_count": 4,
  "total_cards_completed": 12,
  "...other existing fields..."
}
```

`current_mode` is one of `"STRUGGLING"`, `"NORMAL"`, `"FAST"`. Absent or invalid values default to `"NORMAL"`.

---

## 3. Fix 1 — Raise ValueError on 0 cards

**File:** `backend/src/api/teaching_service.py`
**Location:** After the normalization loop, approximately line 1483.

### Current code (broken)
```python
if not cards_data:
    logger.error(
        "[per-chunk] JSON parse failed: session_id=%s chunk_id=%s raw=%s",
        session.id, chunk_id, raw[:300],
    )
    cards_data = []

# Normalise each card
cards = []
for i, parsed_card in enumerate(cards_data):
    ...

logger.info(
    "[per-chunk] generated: session_id=%s chunk_id=%s cards=%d mode=%s",
    session.id, chunk_id, len(cards), _generate_as,
)
return cards
```

### Change
Replace the silent `cards_data = []` fallback at the parse-failure branch AND add a post-normalization guard after the loop:

```python
if not cards_data:
    logger.error(
        "[per-chunk] JSON parse failed: session_id=%s chunk_id=%s raw=%s",
        session.id, chunk_id, raw[:300],
    )
    raise ValueError(
        f"LLM returned unparseable JSON for chunk {chunk_id}. "
        f"raw_len={len(raw)}, first 300 chars: {raw[:300]!r}"
    )

# Normalise each card
cards = []
for i, parsed_card in enumerate(cards_data):
    if not isinstance(parsed_card, dict):
        continue
    parsed_card["index"] = i
    card = _normalise_per_card(parsed_card, chunk_id)
    cards.append(card)

if not cards:
    raise ValueError(
        f"LLM returned 0 usable cards for chunk {chunk_id}. "
        f"raw_len={len(raw)}, cards_data_len={len(cards_data)}."
    )

logger.info(
    "[per-chunk] generated: session_id=%s chunk_id=%s cards=%d mode=%s",
    session.id, chunk_id, len(cards), _generate_as,
)
return cards
```

### Effect
The router's existing `except Exception` handler converts the `ValueError` to HTTP 500 with a JSON `detail` field. The frontend pre-fetch `.catch()` stores the error signal. Fix 4's fallback branch then handles the retry with user-visible feedback.

---

## 4. Fix 2A — System prompt rewrite

**File:** `backend/src/api/teaching_service.py`
**Location:** The `system_prompt = (...)` assignment, approximately line 1424.

### Required import addition
In the existing import block at the top of `generate_per_chunk` (line 1380):
```python
from adaptive.prompt_builder import build_chunk_card_prompt, build_next_card_prompt, _CARD_MODE_DELIVERY
```
(Add `_CARD_MODE_DELIVERY` to the existing `from adaptive.prompt_builder import ...` line.)

### New system_prompt string

Replace the current 9-line system prompt with:

```python
system_prompt = (
    "You are ADA, an adaptive math tutor.\n\n"
    "CRITICAL SOURCE RULE: ALL card content MUST be extracted ONLY from the CHUNK CONTENT "
    "provided in the user message. Do NOT invent definitions, examples, formulas, or steps "
    "that are not in CHUNK CONTENT. Do NOT draw on general math knowledge not present in the chunk.\n\n"
    "CRITICAL COVERAGE RULE: Every concept in CHUNK CONTENT MUST appear on at least one card. "
    "NEVER skip, drop, or summarise a definition, worked example, formula, rule, or procedure.\n\n"
    "MERGE RULES — apply deterministically before generating any card:\n"
    "NEVER merge a paragraph that: (a) contains a formula or LaTeX expression, "
    "(b) is a worked example, (c) contains numbered steps, "
    "(d) introduces a new named concept or definition, "
    "(e) has a heading or label: 'Be Careful', 'Try It', or 'Practice'.\n"
    "MAY merge ONLY when ALL THREE of these are true: "
    "paragraph is 2 sentences or fewer AND it directly continues the previous paragraph "
    "AND it introduces no new concept.\n"
    "STRUGGLING mode: NEVER merge — every paragraph gets its own card.\n"
    "NORMAL mode: merge only when all three MAY conditions are met.\n"
    "FAST mode: merge when paragraphs are conceptually related and both are short — "
    "write as unified technical prose.\n\n"
    "MODE RULE: The student mode changes HOW you write each card (vocabulary, analogies, "
    "steps, MCQ difficulty). Mode NEVER reduces coverage or causes you to drop content.\n\n"
    "STRICT RULES:\n"
    "1. COMBINED CARDS: Every card MUST have BOTH a content field (the paragraph explanation) "
    "AND a question field (an MCQ testing that paragraph). "
    "Do NOT create content-only cards with question=null, and do NOT create MCQ-only cards. "
    "Each card is always content + MCQ together. The student reads the explanation, "
    "then answers the question.\n"
    "2. Every card's question field MUST have: options = exactly 4 non-empty strings; "
    "correct_index in [0, 1, 2, 3]; explanation is non-empty.\n"
    "3. MCQ questions test understanding of the content in the SAME card. "
    "NEVER copy verbatim text from card content into the MCQ question.\n"
    "4. Card count is driven by content structure; only merge low-value short snippets "
    "as per the MERGE RULES above. Minimum 2 cards per chunk.\n"
    "5. Return ONLY a JSON array. No markdown fences. No commentary before or after.\n\n"
    "OUTPUT SCHEMA — each element of the array must match exactly:\n"
    '{"index": 0, "title": "...", "content": "...", '
    '"image_url": null, "caption": null, '
    '"question": {"text": "...", "options": ["A", "B", "C", "D"], '
    '"correct_index": 0, "explanation": "...", "difficulty": "MEDIUM"}, '
    '"is_recovery": false}\n'
    "chunk_id is NOT included in the schema — the backend stamps it after parsing.\n\n"
    f"STUDENT MODE — controls writing style only:\n"
    f"{_CARD_MODE_DELIVERY.get(_generate_as, _CARD_MODE_DELIVERY['NORMAL'])}\n"
)
```

### Key differences from the current prompt

| Aspect | Before | After |
|--------|--------|-------|
| Source constraint | Absent — LLM invents content | "CRITICAL SOURCE RULE: extract ONLY from CHUNK CONTENT" |
| Coverage rule | Absent | "Every concept MUST appear on at least one card" |
| Merge rules | Absent | Deterministic per-mode merge rules with explicit ban on merging definitions, formulas, worked examples |
| Combined cards | Weakly stated via "alternate" rule in user prompt | Strict Rule 1: every card has BOTH content AND question fields |
| Mode delivery | Absent (only "STUDENT MODE: NORMAL" string in user prompt) | `_CARD_MODE_DELIVERY[_generate_as]` block appended |
| Minimum card count | Absent | Minimum 2 cards per chunk |

---

## 5. Fix 2B — Additions to _CARD_MODE_DELIVERY blocks

**File:** `backend/src/adaptive/prompt_builder.py`
**Location:** `_CARD_MODE_DELIVERY` dict, lines 36–64.

Append the following lines to each mode block. These must be added INSIDE each mode's string value (before the closing triple-quote), not as separate dict entries.

### STRUGGLING block — append these two lines
```
MCQ wrong-answer explanation: full step-by-step numbered walkthrough — show exactly what went wrong and the correct path, one numbered step per line.
Apply the student's STYLE and INTERESTS from the user prompt when writing analogies and real-world hooks. STYLE=gamer → gaming language and metaphors. STYLE=pirate → pirate language. STYLE=astronaut → space/science language. INTERESTS — use them for all analogies and real-world examples.
```

### NORMAL block — append these two lines
```
MCQ wrong-answer explanation: brief 2–3 sentence explanation of the correct approach — enough for the student to self-correct.
Apply the student's STYLE and INTERESTS from the user prompt when writing analogies and real-world hooks. STYLE=gamer → gaming language and metaphors. STYLE=pirate → pirate language. STYLE=astronaut → space/science language. INTERESTS — use them for all analogies and real-world examples.
```

### FAST block — append these two lines
```
MCQ wrong-answer explanation: one-line correction only in the form "Correct: [answer] because [brief reason]." No step-by-step.
Apply the student's STYLE and INTERESTS from the user prompt when writing analogies and real-world hooks. STYLE=gamer → gaming language and metaphors. STYLE=pirate → pirate language. STYLE=astronaut → space/science language. INTERESTS — use them for all analogies and real-world examples.
```

### Why these additions are safe
`_CARD_MODE_DELIVERY` is also consumed by `build_adaptive_prompt` (line 172) and `build_next_card_prompt` (line 482) in the same file. The two new lines are additive and consistent with the intent of those paths — they make MCQ feedback more precisely calibrated and ensure style/interests are applied uniformly. There is no conflict with the existing content.

---

## 6. Fix 3 — Wire build_blended_analytics in generate_per_chunk

**File:** `backend/src/api/teaching_service.py`
**Location:** Inside `generate_per_chunk`, after reading `_cached` and before computing `token_budgets` (approximately line 1396).

### Current code (broken)
```python
_generate_as = _cached.get("current_mode", "NORMAL")
if _generate_as not in ("STRUGGLING", "NORMAL", "FAST"):
    _generate_as = "NORMAL"

token_budgets = { ... }
```

`build_blended_analytics` is imported at line 1379 but never called.

### Change
Replace the two-line mode read with:

```python
# Compute live mode from student history via blended analytics
try:
    analytics = await build_blended_analytics(db, session, student)
    _generate_as = analytics.get("current_mode", "NORMAL")
    if _generate_as not in ("STRUGGLING", "NORMAL", "FAST"):
        _generate_as = "NORMAL"
except Exception:
    logger.warning(
        "[per-chunk] build_blended_analytics failed for session %s — defaulting to NORMAL",
        session.id,
    )
    _generate_as = _cached.get("current_mode", "NORMAL")
    if _generate_as not in ("STRUGGLING", "NORMAL", "FAST"):
        _generate_as = "NORMAL"

# Persist updated mode to session cache so next chunk inherits it
_cache_update = dict(_cached)
_cache_update["current_mode"] = _generate_as
session.presentation_text = json.dumps(_cache_update)
# (db.add + commit happen in the router after this call returns)
```

Note: `student` is already fetched on line 1408. Because `build_blended_analytics` is called before the token budget block (which comes before the LLM call), `student` must be fetched earlier. Move the `student = await db.get(Student, session.student_id)` fetch to immediately before the `build_blended_analytics` call.

### Effect
- Each chunk generation computes the correct mode from the student's actual card interaction history.
- The computed mode is written back to `session.presentation_text` so the following chunk starts with the updated mode even if `build_blended_analytics` is slow on the next call.
- Cold-start students (no prior interactions) receive NORMAL from `build_blended_analytics`'s default logic, which is the correct pedagogical default.

---

## 7. Fix 4 — Robust goToNextChunk with on-demand fallback

**File:** `frontend/src/context/SessionContext.jsx`

### Part A — CHUNK_ADVANCE reducer guard (~line 273)

Replace:
```javascript
case "CHUNK_ADVANCE":
  return {
    ...state,
    cards: state.nextChunkCards?.cards ?? [],
    chunkIndex: state.chunkIndex + 1,
    currentCardIndex: 0,
    maxReachedIndex: 0,
    nextChunkCards: null,
    nextChunkInFlight: false,
    hasMoreConcepts: (state.chunkIndex + 1) < state.chunkList.length - 1,
  };
```

With:
```javascript
case "CHUNK_ADVANCE":
  if (!(state.nextChunkCards?.cards?.length > 0)) return state; // safety guard
  return {
    ...state,
    cards: state.nextChunkCards.cards,
    chunkIndex: state.chunkIndex + 1,
    currentCardIndex: 0,
    maxReachedIndex: 0,
    nextChunkCards: null,
    nextChunkInFlight: false,
    hasMoreConcepts: (state.chunkIndex + 1) < state.chunkList.length - 1,
  };
```

The guard prevents the reducer from setting `cards: []` when `nextChunkCards` is null (pre-fetch failed) or has an empty array (Fix 1's error signal).

### Part B — goToNextChunk callback rewrite (~line 720)

Replace:
```javascript
const goToNextChunk = useCallback(() => {
  if (state.nextChunkCards) {
    dispatch({ type: "CHUNK_ADVANCE" });
  }
  // If still loading — UI shows spinner; button re-enables when NEXT_CHUNK_CARDS_READY fires
}, [state.nextChunkCards]);
```

With:
```javascript
const goToNextChunk = useCallback(async () => {
  // Happy path: pre-fetch succeeded with non-empty cards
  if (state.nextChunkCards?.cards?.length > 0) {
    dispatch({ type: "CHUNK_ADVANCE" });
    return;
  }
  // Fallback: pre-fetch failed or returned empty — fetch on demand
  if (state.nextChunkInFlight) return;  // already fetching — wait
  const nextIdx = state.chunkIndex + 1;
  if (nextIdx >= state.chunkList.length) return;  // no more chunks
  const nextChunkId = state.chunkList[nextIdx]?.chunk_id;
  if (!nextChunkId || !state.session?.id) return;
  dispatch({ type: "NEXT_CHUNK_FETCH_STARTED" });
  try {
    const data = await generateChunkCards(state.session.id, nextChunkId);
    if (data?.cards?.length > 0) {
      dispatch({ type: "NEXT_CHUNK_CARDS_READY", payload: data });
      dispatch({ type: "CHUNK_ADVANCE" });
    } else {
      dispatch({ type: "NEXT_CHUNK_FETCH_DONE" });
      dispatch({ type: "ERROR", payload: t("learning.noCardsError") });
    }
  } catch (err) {
    dispatch({ type: "NEXT_CHUNK_FETCH_DONE" });
    dispatch({ type: "ERROR", payload: friendlyError(err) });
  }
}, [
  state.nextChunkCards,
  state.nextChunkInFlight,
  state.chunkIndex,
  state.chunkList,
  state.session,
  t,
]);
```

`generateChunkCards` is already imported in `SessionContext.jsx` (used by `loadChunkCards` at line 713). `t` is available from `useTranslation()` which is already used in the context file.

### Sequence diagram — goToNextChunk (happy path)

```
User clicks "Next Section"
  → goToNextChunk()
    → state.nextChunkCards.cards.length > 0 ✓
    → dispatch(CHUNK_ADVANCE)
      → reducer: safety guard passes (cards present)
      → state.cards = nextChunkCards.cards
      → state.chunkIndex += 1
      → state.nextChunkCards = null
  → CardLearningView renders new cards immediately (< 50 ms)
```

### Sequence diagram — goToNextChunk (fallback path)

```
User clicks "Next Section"
  → goToNextChunk()
    → state.nextChunkCards null or empty (pre-fetch failed)
    → dispatch(NEXT_CHUNK_FETCH_STARTED) → spinner shown
    → await generateChunkCards(session.id, nextChunkId)
      → POST /api/v2/sessions/{id}/chunk-cards
        → generate_per_chunk() → LLM → cards
      → HTTP 200, cards.length > 0
    → dispatch(NEXT_CHUNK_CARDS_READY, data)
    → dispatch(CHUNK_ADVANCE) → reducer: guard passes → advance
  → CardLearningView renders cards (~p95 12 s)
```

---

## 8. Fix 5 — Recovery card: correct trigger, correct endpoint, RECAP on second fail

**File:** `frontend/src/context/SessionContext.jsx`
**Location:** `goToNextCard` callback, approximately line 516.

### Required import
Add `generateChunkRecoveryCard` to the existing import line from `../api/sessions` at the top of `SessionContext.jsx`.

### Current code (broken)
```javascript
// CASE A: both MCQs wrong → recovery card via completeCardAndGetNext
if (signals?.wrongAttempts >= 2 && signals?.reExplainCardTitle) {
  dispatch({ type: "ADAPTIVE_CALL_STARTED" });
  try {
    const res = await completeCardAndGetNext(state.session.id, signals);
    if (res.data?.card) {
      dispatch({ type: "REPLACE_UPCOMING_CARD", payload: res.data });
    }
    if (res.data?.recovery_card) {
      dispatch({ type: "INSERT_RECOVERY_CARD", payload: res.data.recovery_card });
    }
    dispatch({ type: "NEXT_CARD" });
    useAdaptiveStore.getState().updateMode(res.data.learning_profile_summary);
    useAdaptiveStore.getState().awardXP(5);
  } catch (err) {
    console.error("[SessionContext] adaptive card fetch failed:", err);
    dispatch({ type: "ADAPTIVE_CARD_ERROR" });
    dispatch({ type: "NEXT_CARD" });
  } finally {
    dispatch({ type: "ADAPTIVE_CALL_DONE" });
  }
  return;
}
```

### Change

The chunk flow needs its own branch that:
1. Fires on first failure (`wrongAttempts >= 1`) using the `/chunk-recovery-card` endpoint.
2. On second failure (`wrongAttempts >= 2`) generates a RECAP card locally and advances.

The existing CASE A block handles the old per-card adaptive path (non-chunk sessions). It must be preserved for that path.

Add a new chunk-specific branch **before** CASE A:

```javascript
// CASE A-CHUNK: chunk flow recovery card
const isChunkFlow = state.chunkList?.length > 0;
const currentCard = state.cards[state.currentCardIndex];

if (isChunkFlow && signals?.wrongAttempts >= 2 && currentCard) {
  // Second fail: generate RECAP card locally from the failed MCQ's explanation
  const recapCard = {
    index: state.currentCardIndex + 1,
    title: `Key Rule: ${currentCard.title ?? "Review"}`,
    content: currentCard.question?.explanation
      ? `**Key point to remember:** ${currentCard.question.explanation}`
      : "Review the key rule from this card before moving on.",
    image_url: null,
    caption: null,
    question: null,
    is_recovery: true,
    chunk_id: currentCard.chunk_id,
  };
  dispatch({ type: "INSERT_RECOVERY_CARD", payload: recapCard });
  dispatch({ type: "NEXT_CARD" });
  return;
}

if (isChunkFlow && signals?.wrongAttempts >= 1 && currentCard?.chunk_id) {
  dispatch({ type: "ADAPTIVE_CALL_STARTED" });
  try {
    const wrongAnswers = signals.wrongAnswerText ? [signals.wrongAnswerText] : [];
    const recoveryCard = await generateChunkRecoveryCard(
      state.session.id,
      currentCard.chunk_id,
      state.currentCardIndex,
      wrongAnswers,
    );
    if (recoveryCard) {
      dispatch({ type: "INSERT_RECOVERY_CARD", payload: recoveryCard });
    }
    dispatch({ type: "NEXT_CARD" });
  } catch (err) {
    console.error("[SessionContext] chunk recovery card fetch failed:", err);
    dispatch({ type: "ADAPTIVE_CARD_ERROR" });
    dispatch({ type: "NEXT_CARD" });
  } finally {
    dispatch({ type: "ADAPTIVE_CALL_DONE" });
  }
  return;
}

// CASE A: non-chunk adaptive path (existing code — do not modify)
if (signals?.wrongAttempts >= 2 && signals?.reExplainCardTitle) {
  ...existing CASE A code...
}
```

### Sequence diagram — first MCQ failure (chunk flow)

```
Student selects wrong answer
  → goToNextCard(signals) called with wrongAttempts = 1
  → isChunkFlow = true, wrongAttempts >= 1 check passes
  → dispatch(ADAPTIVE_CALL_STARTED)
  → await generateChunkRecoveryCard(session.id, chunk_id, cardIndex, wrongAnswers)
    → POST /api/v2/sessions/{id}/chunk-recovery-card
      → generate_recovery_card_for_chunk() → LLM → recovery card
    → HTTP 200, recoveryCard object
  → dispatch(INSERT_RECOVERY_CARD, recoveryCard)
  → dispatch(NEXT_CARD) → student sees recovery card
```

### Sequence diagram — second MCQ failure (chunk flow)

```
Student selects wrong answer on recovery card MCQ
  → goToNextCard(signals) called with wrongAttempts = 2
  → isChunkFlow = true, wrongAttempts >= 2 check passes
  → recapCard assembled locally from currentCard.question.explanation
  → dispatch(INSERT_RECOVERY_CARD, recapCard)
  → dispatch(NEXT_CARD) → student sees RECAP card
  → Student clicks Next on RECAP card (question = null)
    → goToNextCard dispatches NEXT_CARD → advances normally
```

---

## 9. Fix 8 — Exercise chunk detection and dedicated system prompt

**File:** `backend/src/api/teaching_service.py`
**Location:** Inside `generate_per_chunk`, before the system prompt assignment.

### Detection

Add after reading `_generate_as`:

```python
EXERCISE_HEADING_PATTERNS = ("exercises", "practice test", "review exercises")
is_exercise_chunk = any(
    p in (chunk.get("heading") or "").lower()
    for p in EXERCISE_HEADING_PATTERNS
)
```

### Fetching preceding teaching subsection headings

If `is_exercise_chunk` is True, fetch all chunks for the same concept with a lower `order_index`, excluding non-teaching sections:

```python
NON_TEACHING_PATTERNS = ("learning objectives", "key terms", "key concepts", "summary", "review")

if is_exercise_chunk:
    all_chunks = await self._chunk_ksvc.get_chunks_for_concept(db, session.concept_id)
    current_order = chunk.get("order_index", 0)
    teaching_chunks = [
        c for c in all_chunks
        if c.get("order_index", 0) < current_order
        and not any(p in (c.get("heading") or "").lower() for p in NON_TEACHING_PATTERNS)
    ]
    teaching_headings = [c["heading"] for c in teaching_chunks]
```

### Exercise system prompt

```python
if is_exercise_chunk:
    n_subsections = len(teaching_headings)
    total_cards = max(n_subsections * 2, 2)
    subsection_list = "\n".join(
        f"{i + 1}. {h}" for i, h in enumerate(teaching_headings)
    ) or "1. (teaching section)"

    system_prompt = (
        "You are ADA, an adaptive math tutor.\n\n"
        "EXERCISE CHUNK MODE: You are generating review MCQ cards for a section exercise.\n\n"
        "CRITICAL SOURCE RULE: Questions MUST come from the EXERCISE TEXT in the user message. "
        "Do NOT invent problems not present in the exercise text.\n\n"
        f"Generate EXACTLY {total_cards} MCQ cards: 2 cards per teaching subsection listed below.\n"
        "Cards must be in order: 2 cards for subsection 1, then 2 for subsection 2, etc.\n\n"
        "TEACHING SUBSECTIONS COVERED:\n"
        f"{subsection_list}\n\n"
        "RULES:\n"
        "1. Every card MUST have question field with: options = exactly 4 non-empty strings; "
        "correct_index in [0, 1, 2, 3]; explanation non-empty.\n"
        "2. MCQ difficulty: REAL TEXTBOOK DIFFICULTY for all modes — exercise questions do not "
        "adapt difficulty for mode. Every student gets the same difficulty.\n"
        "3. Wrong-answer explanation adapts to mode:\n"
        f"   {_CARD_MODE_DELIVERY.get(_generate_as, _CARD_MODE_DELIVERY['NORMAL'])}\n"
        "   (Apply only the wrong-answer explanation length rule from the mode block above; "
        "   ignore vocabulary/analogy rules for exercise cards.)\n"
        "4. content field = brief context statement for what this card is testing "
        "(1 sentence, e.g. 'Testing: rounding whole numbers'). Not the full explanation.\n"
        "5. Return ONLY a JSON array. No markdown fences. No commentary.\n\n"
        "OUTPUT SCHEMA — each element:\n"
        '{"index": 0, "title": "...", "content": "...", '
        '"image_url": null, "caption": null, '
        '"question": {"text": "...", "options": ["A", "B", "C", "D"], '
        '"correct_index": 0, "explanation": "...", "difficulty": "HARD"}, '
        '"is_recovery": false}\n'
    )
else:
    system_prompt = (
        ... # Fix 2A system prompt string (see Fix 2A above)
    )
```

### Method dependency

The exercise detection requires `self._chunk_ksvc.get_chunks_for_concept(db, concept_id)`. Verify this method exists on `ChunkKnowledgeService` (file `backend/src/api/chunk_knowledge_service.py`). If not present, the backend developer must add it — it returns all `ConceptChunk` rows for a given `concept_id` ordered by `order_index`.

---

## 10. Fix 6 — noCardsError i18n key

**Files:** `frontend/src/locales/*.json` (13 files)
**Key path:** `learning.noCardsError` (nested under the existing `learning` object)

Add the following entry to the `"learning"` object in each locale file:

| Locale file | Value |
|-------------|-------|
| `en.json` | `"Could not load cards. Please try again."` |
| `ar.json` | `"تعذّر تحميل البطاقات. يرجى المحاولة مرة أخرى."` |
| `de.json` | `"Karten konnten nicht geladen werden. Bitte versuche es erneut."` |
| `es.json` | `"No se pudieron cargar las tarjetas. Inténtalo de nuevo."` |
| `fr.json` | `"Impossible de charger les cartes. Veuillez réessayer."` |
| `hi.json` | `"कार्ड लोड नहीं हो सके। कृपया पुनः प्रयास करें।"` |
| `ja.json` | `"カードを読み込めませんでした。もう一度お試しください。"` |
| `ko.json` | `"카드를 불러올 수 없습니다. 다시 시도해 주세요."` |
| `ml.json` | `"കാർഡുകൾ ലോഡ് ചെയ്യാൻ കഴിഞ്ഞില്ല. വീണ്ടും ശ്രമിക്കൂ."` |
| `pt.json` | `"Não foi possível carregar os cartões. Por favor, tente novamente."` |
| `si.json` | `"කාඩ්පත් පූරණය කළ නොහැකි විය. කරුණාකර නැවත උත්සාහ කරන්න."` |
| `ta.json` | `"அட்டைகளை ஏற்ற முடியவில்லை. மீண்டும் முயற்சிக்கவும்."` |
| `zh.json` | `"无法加载卡片，请重试。"` |

---

## 11. Security Design

No new attack surface is introduced. All fixes are within existing code paths. Existing input validation (`_normalise_per_card`, Pydantic schemas) is unchanged. The `ValueError` message in Fix 1 includes `raw[:300]` of LLM output — this is logged at ERROR level, not returned to the client (the router converts it to a generic `{"detail": "..."}` HTTP 500 response).

---

## 12. Observability Design

### Existing log lines (unchanged)
```
[per-chunk] generated: session_id=... chunk_id=... cards=N mode=STRUGGLING/NORMAL/FAST
[per-chunk] JSON parse failed: session_id=... chunk_id=... raw=...
```

### New log line (Fix 3)
```python
logger.info(
    "[per-chunk] mode adapted: session_id=%s chunk_id=%s mode=%s",
    session.id, chunk_id, _generate_as,
)
```

### New log line (Fix 3 fallback)
```python
logger.warning(
    "[per-chunk] build_blended_analytics failed for session %s — defaulting to NORMAL",
    session.id,
)
```

### New log line (Fix 8)
```python
logger.info(
    "[per-chunk] exercise chunk detected: session_id=%s chunk_id=%s subsections=%d total_cards=%d",
    session.id, chunk_id, n_subsections, total_cards,
)
```

---

## 13. Error Handling and Resilience

| Scenario | Handling |
|----------|----------|
| LLM returns invalid JSON → Fix 1 raises ValueError | Router `except Exception` → HTTP 500 → frontend fallback fetch |
| LLM returns valid JSON but 0 usable cards → Fix 1 raises ValueError | Same as above |
| `build_blended_analytics` raises (Fix 3) | Wrapped in try/except → falls back to cached mode or NORMAL; warning logged |
| `goToNextChunk` fallback fetch also fails | `dispatch(ERROR, friendlyError(err))` → error banner shown to student |
| `generateChunkRecoveryCard` fails (Fix 5) | `console.error` + `ADAPTIVE_CARD_ERROR` + `NEXT_CARD` → student advances without recovery card |
| `get_chunks_for_concept` raises (Fix 8) | Can be caught in exercise detection block → fall back to teaching prompt with empty subsection list |
| `CHUNK_ADVANCE` dispatched with null nextChunkCards | Reducer guard returns `state` unchanged → no blank screen |

---

## 14. Testing Strategy

### Unit tests (backend — new file `backend/tests/test_generate_per_chunk.py`)

| Test | Assertion |
|------|-----------|
| `test_generate_per_chunk_raises_on_empty_llm_output` | Mock `_chat` to return `"[]"` → `generate_per_chunk` raises `ValueError` |
| `test_generate_per_chunk_raises_on_unparseable_json` | Mock `_chat` to return `"not json"` → `generate_per_chunk` raises `ValueError` |
| `test_generate_per_chunk_system_prompt_has_source_rule` | Capture the `messages[0]["content"]` passed to `_chat` → assert `"CRITICAL SOURCE RULE"` in string |
| `test_generate_per_chunk_injects_mode_delivery_block` | Set `build_blended_analytics` mock to return `{"current_mode": "STRUGGLING"}` → assert `"DELIVERY MODE: STRUGGLING"` in system prompt |
| `test_generate_per_chunk_updates_session_mode` | After successful call with mocked LLM → assert `json.loads(session.presentation_text)["current_mode"] == "STRUGGLING"` |
| `test_generate_per_chunk_exercise_chunk_detection` | Chunk heading = "Section 1.1 Exercises" → assert system prompt contains `"EXERCISE CHUNK MODE"` |

### Frontend tests
No new frontend unit test framework is in place (known technical debt). Fix 4 and Fix 5 changes should be verified via the manual verification checklist in the plan document.

---

## Key Decisions Requiring Stakeholder Input

1. **`get_chunks_for_concept` method** — Fix 8 requires this method on `ChunkKnowledgeService`. The backend developer must confirm it exists or add it before implementing Fix 8. If the method requires a new DB query, the devops-engineer should review query performance (indexed by `concept_id`).
2. **RECAP card content source** — The RECAP card uses `currentCard.question?.explanation` as its body text. If the explanation field is null or very short (some LLM outputs), the RECAP card will be thin. An alternative is to use `currentCard.content` instead. Confirm which field is more reliable.
3. **`wrongAnswerText` signal availability** — Fix 5 passes `signals.wrongAnswerText` to `generateChunkRecoveryCard`. Confirm that `CardLearningView.jsx` populates `wrongAnswerText` in the signals object it passes to `goToNextCard`. If not, the recovery endpoint receives an empty `wrong_answers` array, which is acceptable but reduces recovery card quality.
