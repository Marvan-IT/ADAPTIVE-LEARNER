## Revision History

### Rev 3 — 2026-03-17: 11 Root-Cause Fixes (Card Lag, Blank Cards, Recovery Cards, Multi-Book Graph, MCQ Quality)

**Changes from Rev 2:**

This revision documents 11 additional confirmed root causes and their fixes identified after deeper codebase inspection. These bugs were producing blank cards, wrong images, stale cached cards, SLOW students receiving NORMAL cards, only one book visible in the concept map, and MCQs with two correct answers.

#### Root Cause and Fix Table

| # | Bug | Root Cause | Fix | Files |
|---|-----|------------|-----|-------|
| 1 | First card generation lag | `STARTER_PACK_INITIAL_SECTIONS = 3` — only 3 sections loaded before rolling begins; LLM generates too few cards, causing visible loading pause on first card | Bump to 5 | `config.py` |
| 2, 8 | Card order wrong after cache | `_CARDS_CACHE_VERSION = 14` not bumped after `_sort_cards()` removal — stale pre-sorted cards served from DB cache bypass the corrected sort | Bump cache version to 15 | `teaching_service.py` |
| 3, 7 | Images wrong or missing per card | LLM assigns `image_indices` freely; VISUAL cards with no matching images render blank; VISUAL card type puts image first — empty when none available | VISUAL no-image fallback: render as TEACH layout; blank card filter strips cards with no renderable content | `CardLearningView.jsx`, `teaching_service.py` |
| 4, 6 | Blank card after adaptive API call | `REPLACE_UPCOMING_CARD` reducer spreads `res.data.card` — but `CompleteCardResponse` has no `.card` field; spreads `undefined`, producing a blank card object at `cards[currentIndex + 1]` | Guard: `if (res.data?.card)` before executing `REPLACE_UPCOMING_CARD` | `SessionContext.jsx` |
| 5 | Recovery card same for all wrong answers | `generate_recovery_card()` never receives the wrong MCQ question text or the student's chosen wrong answer — generates generic remediation regardless of which concept was misunderstood | Add `wrong_question` and `wrong_answer_text` to `RecoveryCardRequest` schema, engine function signature, and frontend call site | `teaching_schemas.py`, `adaptive_engine.py`, `CardLearningView.jsx`, `sessions.js` |
| 9 | FAST mode cards too short | FAST mode prompt block had no MANDATORY content enforcement rules; LLM interpreted "connected prose" as license to write less rather than write more concisely | Add `MANDATORY: minimum 3 content points` and `MANDATORY: include worked example` rules to all 3 mode blocks (STRUGGLING / NORMAL / FAST) in both prompt files | `prompts.py`, `prompt_builder.py` |
| 10 | Only prealgebra visible in concept map | All 6 v1 graph endpoints use the hardcoded `knowledge_svc` instance with no `book_slug` routing; concept map always shows prealgebra regardless of which book the student is studying | Add `book_slug` query param to all 6 `/api/v1/` endpoints; add `/api/v1/books` list endpoint; wire `book_slug` through `useConceptMap` hook and `ConceptMapPage` | `main.py`, `ConceptMapPage.jsx`, `useConceptMap.js`, `concepts.js` |
| 11 | MCQ has two correct answers | MCQ RULES section lacked an explicit "exactly one correct answer" constraint; LLM occasionally generated two defensible correct options | Add MCQ unambiguity rules: "exactly one option is unambiguously correct", "the other three options must be clearly incorrect" | `prompts.py`, `prompt_builder.py` |
| B9 | SLOW students receive NORMAL cards | Rolling card generation maps `profile.speed` to `generate_as` via `_CARD_MODE_DELIVERY` dict; dict has no `"SLOW"` key — falls back to `"NORMAL"`; SLOW students never get scaffolded content | Map `"SLOW"` → `"STRUGGLING"` before the `_CARD_MODE_DELIVERY` lookup | `teaching_service.py` |

#### Detailed Fix Specifications for Rev 3

**Fix R1 — Starter Pack Section Count**

File: `backend/src/config.py`

```python
# Before:
STARTER_PACK_INITIAL_SECTIONS = 3

# After:
STARTER_PACK_INITIAL_SECTIONS = 5
```

Rationale: With 3 sections the initial pack often generates only 3–5 cards, causing a visible loading pause when the student reaches card 4 while the next rolling batch is still generating. 5 sections yields 8–12 cards, providing enough buffer for the rolling generator to catch up without user-visible lag.

**Fix R2/R8 — Cache Version Bump**

File: `backend/src/api/teaching_service.py`

```python
# Before:
_CARDS_CACHE_VERSION = 14

# After:
_CARDS_CACHE_VERSION = 15
# Comment: v15 — invalidate stale pre-sorted cards after _sort_cards() removal (Rev 3)
```

Rationale: Rev 2 removed `_sort_cards()` from the generation path, but any cards already cached at version 14 were sorted by the old FUN/RECAP type-based logic. Those stale cache entries must be invalidated so the corrected `_section_index`-only sort is applied on the next generation.

**Fix R3/R7 — VISUAL Card No-Image Fallback**

File: `frontend/src/components/learning/CardLearningView.jsx`

The VISUAL card renderer must apply a layout fallback when the resolved image list is empty:

```javascript
// Current (broken): renders image-first layout even when images = []
// After: fall through to TEACH layout when images.length === 0

const effectiveCardType = (card.card_type === "VISUAL" && (!card.images || card.images.length === 0))
    ? "TEACH"
    : card.card_type;
```

File: `backend/src/api/teaching_service.py`

Add a blank-card filter as the final step in `generate_cards()` before caching:

```python
# Filter cards that have no renderable content (no presentation text AND no images)
cards = [
    c for c in all_raw_cards
    if c.get("presentation") or c.get("images")
]
```

**Fix R4/R6 — `REPLACE_UPCOMING_CARD` Guard**

File: `frontend/src/context/SessionContext.jsx`

```javascript
// Before — always executes, spreads undefined:
case "REPLACE_UPCOMING_CARD": {
    const newCards = [...state.cards];
    newCards[state.currentCardIndex + 1] = { ...newCards[state.currentCardIndex + 1], ...action.payload.card };
    return { ...state, cards: newCards };
}

// After — guard prevents execution when .card is absent:
case "REPLACE_UPCOMING_CARD": {
    if (!action.payload?.card) return state;
    const newCards = [...state.cards];
    newCards[state.currentCardIndex + 1] = { ...newCards[state.currentCardIndex + 1], ...action.payload.card };
    return { ...state, cards: newCards };
}
```

**Fix R5 — Recovery Card Context**

Schema change (`backend/src/api/teaching_schemas.py`):

```python
class RecoveryCardRequest(BaseModel):
    session_id: UUID
    concept_id: str
    wrong_question: str | None = None      # NEW: the MCQ question that was answered wrong
    wrong_answer_text: str | None = None   # NEW: the option text the student chose
```

Engine change (`backend/src/adaptive/adaptive_engine.py`), `generate_recovery_card()` signature:

```python
async def generate_recovery_card(
    self,
    session: TeachingSession,
    concept_detail: dict,
    wrong_question: str | None = None,    # NEW
    wrong_answer_text: str | None = None, # NEW
) -> dict:
    ...
    # Pass to LLM prompt: "The student answered [wrong_question] incorrectly,
    # choosing [wrong_answer_text]. Target that exact misconception."
```

Frontend call site (`frontend/src/components/learning/CardLearningView.jsx`):

```javascript
// Before: requestRecoveryCard(sessionId, conceptId)
// After:
requestRecoveryCard(sessionId, conceptId, {
    wrong_question: card.mcq?.question ?? null,
    wrong_answer_text: selectedOptionText ?? null,
});
```

API client (`frontend/src/api/sessions.js`):

```javascript
export const requestRecoveryCard = (sessionId, conceptId, context = {}) =>
    apiClient.post(`/api/v2/sessions/${sessionId}/recovery-card`, {
        concept_id: conceptId,
        wrong_question: context.wrong_question ?? null,
        wrong_answer_text: context.wrong_answer_text ?? null,
    });
```

**Fix R9 — FAST Mode Mandatory Content Rules**

File: `backend/src/api/prompts.py` — inside the FAST mode block of the card generation system prompt:

```
FAST MODE — MANDATORY RULES:
- MANDATORY: Each card MUST contain at least 3 distinct content points or steps.
- MANDATORY: Each card MUST include a worked example or concrete application.
- "Connected prose" means concise and dense, NOT shorter. Aim for 200–350 words per card.
- Do NOT reduce the number of cards in the section to save tokens.
```

Apply the same three mandatory rules to the STRUGGLING and NORMAL mode blocks as a floor baseline. File: `backend/src/adaptive/prompt_builder.py` — apply matching rules to the `build_next_card_prompt()` FAST block.

**Fix R10 — Multi-Book Concept Map**

File: `backend/src/api/main.py` — add `book_slug: str = Query(default="prealgebra")` parameter to all 6 `/api/v1/` route handlers and route to the appropriate `KnowledgeService` instance from `knowledge_services` dict:

```python
@app.get("/api/v1/concepts/{concept_id}")
async def get_concept(concept_id: str, book_slug: str = Query(default="prealgebra")):
    svc = knowledge_services.get(book_slug)
    if not svc:
        raise HTTPException(status_code=404, detail=f"Book '{book_slug}' not found")
    return await svc.get_concept(concept_id)
```

New endpoint:

```python
@app.get("/api/v1/books")
async def list_books():
    return {"books": list(knowledge_services.keys())}
```

File: `frontend/src/pages/ConceptMapPage.jsx` — read `bookSlug` from student context or URL param, pass to `useConceptMap(bookSlug)`.

File: `frontend/src/hooks/useConceptMap.js` — accept `bookSlug` arg; append `?book_slug={bookSlug}` to all concept map API calls.

File: `frontend/src/api/concepts.js` — update all 6 request functions to accept and forward `bookSlug` query param.

**Fix R11 — MCQ Unambiguity Rules**

File: `backend/src/api/prompts.py` — append to MCQ RULES section:

```
MCQ UNAMBIGUITY RULES:
- Exactly ONE option must be unambiguously correct. A student who understands the concept
  must be able to identify it with certainty — not by elimination.
- The other THREE options must be clearly incorrect. They may exploit common misconceptions
  but must not be defensible as partially correct.
- Do NOT write options that are "technically correct in some interpretations."
- Do NOT write trick questions. Test understanding, not reading comprehension.
```

File: `backend/src/adaptive/prompt_builder.py` — apply identical rules to `build_next_card_prompt()` MCQ block.

**Fix RB9 — SLOW → STRUGGLING Mapping**

File: `backend/src/api/teaching_service.py`, rolling card generation function:

```python
# Before — SLOW falls through to default "NORMAL":
generate_as = _CARD_MODE_DELIVERY.get(profile.speed, "NORMAL")

# After — explicit SLOW → STRUGGLING remap before lookup:
speed_key = profile.speed if profile.speed != "SLOW" else "STRUGGLING"
generate_as = _CARD_MODE_DELIVERY.get(speed_key, "NORMAL")
```

Rationale: `LearningProfile.speed` can be `"SLOW"`, `"NORMAL"`, or `"FAST"`. The `_CARD_MODE_DELIVERY` dict maps `"NORMAL"` and `"FAST"` explicitly; `"SLOW"` was never added as a key, silently falling back to `"NORMAL"`. SLOW students need scaffolded STRUGGLING-mode cards, not NORMAL-mode cards.

#### API Changes in Rev 3

`RecoveryCardRequest` gains two optional fields (`wrong_question`, `wrong_answer_text`). These are backward-compatible additions — existing callers that omit them receive generic recovery cards as before. No version bump required.

`GET /api/v1/books` is a new endpoint with no breaking effect on existing clients.

All 6 `/api/v1/` endpoints gain an optional `book_slug` query param defaulting to `"prealgebra"` — fully backward compatible.

**No DB schema changes. No Alembic migration required.**

---

### Rev 2 — 2026-03-17: Card Order and Adaptive Mode Propagation Fixes

**Changes from Rev 1:**

1. **Remove `_sort_cards()` function** (`teaching_service.py`, `adaptive_engine.py`)
   - Root cause: Function was added as a safety-net for FUN/RECAP ordering, but `_CARDS_CACHE_VERSION = 14` comment explicitly states `_section_index` sort is authoritative. `_sort_cards()` contradicts this by moving cards from later sections before earlier sections.
   - Fix: Remove all 5 call sites and 2 function definitions. `_section_index` sort remains as the sole ordering mechanism.
   - Locations removed: `teaching_service.py` lines ~99–105 (definition), ~1142 (call), ~1540 (call); `adaptive_engine.py` lines ~75–81 (definition), ~342–349 (call block).

2. **Fix `generate_as` not passed to adaptive prompt builder** (`adaptive_engine.py`)
   - Root cause: `generate_adaptive_lesson()` called `build_adaptive_prompt()` without `generate_as`, which defaulted to `"NORMAL"`. All adaptive lessons were generated in NORMAL mode regardless of student profile.
   - Fix: Derive `generate_as` from `analytics_summary.speed` and `analytics_summary.comprehension_score` immediately after building `learning_profile`. Pass to `build_adaptive_prompt()`.
   - Logic: SLOW speed OR comprehension < 0.45 → STRUGGLING; FAST speed AND comprehension ≥ 0.65 → FAST; otherwise → NORMAL.

**No API contract changes. No schema changes. No frontend changes.**

---

# Pre-Deployment Audit Fixes — Detailed Low-Level Design

**Feature slug:** `pre-deployment-audit-fixes`
**Date:** 2026-03-17
**Author:** solution-architect
**Status:** Design complete — implementation pending

---

## 1. Component Breakdown

| Component | File | Fix(es) | Responsibility |
|-----------|------|---------|---------------|
| Card generation service | `backend/src/api/teaching_service.py` | Fix 1, 2A, 2B, 5A, P2 | Ordering, image filtering, property batching, dead code removal |
| Adaptive profiling engine | `backend/src/adaptive/adaptive_engine.py` | Fix 4A, 4B | FAST-mode floor, conservative cap |
| Image extraction pipeline | `backend/src/images/image_extractor.py` | P1-B, P3 | Silent-catch promotion |
| Platform constants | `backend/src/config.py` | P2 | Unused constant removal |
| Session state reducer | `frontend/src/context/SessionContext.jsx` | P1-A, Fix 3 | `passed` field removal, recovery card dispatch |
| Unit test suite | `backend/tests/test_bug_fixes.py` | All | Regression coverage for all five fix classes |

All inter-component interfaces (API contracts, event shapes, DB schema) are unchanged.

---

## 2. Data Design

### No schema changes

All fixes are contained within service-layer and presentation-layer logic. No new database columns, no new Pydantic fields exposed to callers, and no ChromaDB metadata fields are added or removed.

### Affected in-memory data structures

**Fix 1 — Card sort key**

Cards carry a `_section_index: int` field stamped during generation. This field already exists (introduced in cache version 13). The only change is that the post-generation sort uses this field exclusively:

```python
# Before (removed):
fun_cards  = [c for c in cards if c.get("card_type") == "FUN"]
recap_cards = [c for c in cards if c.get("card_type") == "RECAP"]
middle = [c for c in cards if c not in fun_cards and c not in recap_cards]
middle.sort(key=lambda c: c.get("difficulty", 3))
cards = fun_cards + middle + recap_cards

# After (current state — confirmed in teaching_service.py):
all_raw_cards.sort(key=lambda c: c.get("_section_index", len(sub_sections)))
```

**Fix 2A — Image filter predicate**

```python
# Before (removed type restriction):
useful_images = [
    img for img in images
    if img.get("image_type") in ("DIAGRAM", "FORMULA")
    and img.get("is_educational") is not False
    and img.get("description")
]

# After (current state — confirmed in teaching_service.py):
useful_images = [
    img for img in images
    if img.get("is_educational") is not False
    and img.get("description")
    and not any(
        kw in (img.get("description") or "").lower()
        for kw in _CHECKLIST_KEYWORDS
    )
]
```

`_CHECKLIST_KEYWORDS` tuple:
```python
_CHECKLIST_KEYWORDS = (
    "checklist", "self-assessment", "i can", "confidently",
    "with some help", "rubric", "evaluate my understanding", "learning target",
)
```

**Fix 4A — Expected-time floor**

In `adaptive_engine.py`, function `build_blended_analytics()`:

```python
# Before:
expected_time = baseline_time  # could be as low as student's own 10s average

# After (current state — confirmed in adaptive_engine.py line 625):
expected_time = max(baseline_time, 90.0)
# Normative 90s floor: fast students compare against 90s, not their own 10s average
```

**Fix P1-A — `passed` field removal**

In `SessionContext.jsx`, the `SOCRATIC_RESPONSE` reducer case:

```javascript
// Before:
const { passed, mastered, remediation_needed, score, attempt, locked, best_score } = action.payload;
if (passed || mastered) { ... }

// After:
const { mastered, remediation_needed, score, attempt, locked, best_score } = action.payload;
if (mastered) { ... }
```

Note: The PostHog analytics call on line ~546 still reads `res.data.mastered || res.data.passed` — this is outside the reducer and is a separate site that should also be cleaned up:

```javascript
// Before (line ~546):
if (res.data.mastered || res.data.passed) {

// After:
if (res.data.mastered) {
```

---

## 3. API Design

No new endpoints. No changes to existing request/response schemas.

The following confirms the schema alignment after P1-A:

**`SocraticResponse` (backend, `teaching_schemas.py`)** — unchanged:
```python
class SocraticResponse(BaseModel):
    session_id: UUID
    response: str
    phase: str
    check_complete: bool
    score: int | None = None
    mastered: bool | None = None
    remediation_needed: bool | None = None
    attempt: int | None = None
    locked: bool | None = None
    best_score: int | None = None
    image: dict | None = None
    # No `passed` field — never existed
```

**Frontend consumer (`SessionContext.jsx`)** — after P1-A fix:
```javascript
// Destructure only fields that exist in SocraticResponse
const { mastered, remediation_needed, score, attempt, locked, best_score } = action.payload;
```

---

## 4. Sequence Diagrams

### Fix 1 — Card Sort (Happy Path)

```
generate_cards()
    │
    ├─ _parse_sub_sections() → sub_sections[]
    ├─ _batch_consecutive_properties() → sub_sections[] (Fix 5A: may merge PROPERTY sections)
    ├─ For each section:
    │     generate_for_section() → section_cards[]
    │     card["_section_index"] = actual_pos  ← stamp integer
    │     all_raw_cards.extend(section_cards)
    │
    ├─ validate_and_repair_cards(all_raw_cards) → repaired, still_missing
    │
    └─ all_raw_cards.sort(key=lambda c: c.get("_section_index", MAX))
          └─ FUN/RECAP cards stay at their section position ✓
```

### Fix P1-A — Socratic Mastery Check (Happy Path)

```
Student submits final Socratic answer
    │
    ▼
POST /api/v2/sessions/{id}/check
    │
    ▼
Backend returns SocraticResponse { mastered: true, score: 78, ... }
    │
    ▼
SessionContext dispatch("SOCRATIC_RESPONSE", payload)
    │
    ▼
reducer:
    const { mastered, score, ... } = action.payload  ← no `passed`
    if (mastered) {
        // show completion UI
    }
```

### Fix P1-A — Mastery Check (Error Path: mastered = null)

```
Backend returns SocraticResponse { mastered: null, score: 65, ... }
    │
    ▼
reducer:
    const { mastered, ... } = action.payload  → mastered = null
    if (mastered) { ... }  → falsy, correctly skips completion
    // Continues Socratic loop
```

### Fix 3 — Recovery Card Insertion (Happy Path)

```
Student answers both MCQs incorrectly (wrongAttempts >= 2)
    │
    ▼
goToNextCard() dispatch("ADAPTIVE_CALL_STARTED")
    │
    ▼
POST /api/v2/sessions/{id}/complete-card  { signals: { wrongAttempts: 2, reExplainCardTitle: "..." } }
    │
    ▼
Backend returns { card: nextCard, recovery_card: recoveryCard, ... }
    │
    ▼
dispatch("REPLACE_UPCOMING_CARD", payload)          ← replaces cards[currentIndex + 1]
dispatch("INSERT_RECOVERY_CARD", payload.recovery_card)  ← inserts recovery before upcoming
dispatch("NEXT_CARD")                               ← advances to recovery card
```

---

## 5. Integration Design

No third-party integration changes. The image extraction pipeline (`image_extractor.py`) calls PyMuPDF's `doc.extract_image(xref)` — Fix P1-B only adds error logging to the existing exception handler; the call site and retry behaviour are unchanged.

---

## 6. Security Design

No security-relevant changes. The fixes do not introduce new input surfaces, change authentication logic, or alter data persistence behaviour.

The `passed` field removal (P1-A) eliminates a data-trust assumption — the frontend no longer acts on a field that the backend never sends, reducing the surface for unexpected state transitions from future accidental payload injections.

---

## 7. Observability Design

### Fix P1-B — Image Extractor Silent Catch

**File:** `backend/src/images/image_extractor.py`, line ~42

**Before:**
```python
except Exception:
    continue
```

**After:**
```python
except Exception as e:
    logger.warning(
        "Failed to extract image xref=%d from page=%d: %s",
        xref, page_num, e,
    )
    continue
```

Log fields:
- `xref` — PDF cross-reference number (integer), searchable for specific corrupt objects
- `page_num` — page number where the failure occurred
- Error message — exception type and message

Log level: `WARNING` — alerts on-call without triggering an alert at INFO level during normal pipeline runs.

### Fix P3 — Extract Images Debug Promotion

**File:** `backend/src/images/extract_images.py`, line ~159

**Before:**
```python
except Exception:
    logger.debug("Pillow validation failed for xref %d — skipping", xref)
```

**After:**
```python
except Exception as e:
    logger.info(
        "Pillow validation skipped xref=%d: %s",
        xref, e,
    )
    skipped += 1
    continue
```

Level rationale: `INFO` is appropriate because this path is expected during normal pipeline runs (PDFs occasionally contain non-image xrefs); `WARNING` would create noise. The promotion from `DEBUG` makes pipeline skip counts visible in default production log levels.

### Existing Observability (Unchanged)

- Card generation logs: `[card-validate]`, `[fast-batch]`, `cards section_grouping`, `cards token_budget`
- Adaptive engine logs: `[blend_signals]`, `[learning_profile]`
- No new metrics or dashboards required for these fixes

---

## 8. Error Handling and Resilience

### Fix 2B — Image Fallback (File Not Found)

**File:** `backend/src/api/knowledge_service.py`, `get_concept_images()`

Current behaviour (from CLAUDE.md and codebase): `get_concept_images()` tries the indexed filename first, then falls back to a PDF page-number derived name. Fix 2B ensures that when neither file exists on disk, the card retains the indexed filename in the `images` array rather than dropping the image entirely.

This means the frontend may attempt to load an image URL that returns 404. The frontend already handles this gracefully via `onError` handlers on `<img>` elements (established pattern). No change to frontend error handling is needed.

### Fix 4B — Conservative Mode-Switch Cap

**File:** `backend/src/adaptive/adaptive_engine.py`

The conservative cap constant controls how many consecutive interactions confirming a new profile are required before the mode actually switches. Lowering from 5 to 2 means the system is more responsive. If this causes instability (oscillating mode switches), the constant can be raised back to 3 in `config.py` without a redeploy.

**Constant name:** `ADAPTIVE_CONSERVATIVE_CAP` in `config.py` — confirm exact name at implementation time; update this document if different.

---

## 9. Detailed Fix Specifications

### Fix 1 — Card Ordering

**File:** `backend/src/api/teaching_service.py`

**Change:** Remove any remaining code blocks that reorder cards by `card_type` (FUN to front, RECAP to back). The sole sort must be:

```python
all_raw_cards.sort(key=lambda c: c.get("_section_index", len(sub_sections)))
```

**Verification:** `TestCardOrdering` in `test_bug_fixes.py` — 4 test cases covering:
1. FUN card with high `_section_index` stays after earlier TEACH cards
2. RECAP card with low `_section_index` stays before later cards
3. Mixed types sorted strictly by `_section_index`
4. Cards missing `_section_index` default to end

**Cache version:** Already at 14 (comment: "Remove FUN/RECAP reorder block"). No cache version bump needed.

---

### Fix 2A — Image Filter

**File:** `backend/src/api/teaching_service.py`

**Change:** Remove `image_type in ("DIAGRAM", "FORMULA")` from the `useful_images` filter predicate. The filter as confirmed in the codebase is already the correct post-fix version. Verify no other filter call sites apply the type restriction.

**Grep check before commit:**
```
grep -rn "image_type.*DIAGRAM\|image_type.*FORMULA" backend/src/
```

**Verification:** `TestImageFilter` in `test_bug_fixes.py` — 5 test cases covering PHOTO, TABLE, FIGURE, all-four-types pass, `is_educational=False` exclusion, missing description exclusion.

---

### Fix 2B — Image Fallback

**File:** `backend/src/api/knowledge_service.py`, `get_concept_images()`

**Change:** When the primary filename lookup fails (file not on disk), retain the indexed filename in the returned image dict rather than omitting the image from the list.

```python
# Current fallback pattern (from CLAUDE.md):
# tries indexed name → tries PDF page-number derived name → ??? (fix: keep indexed name)

# After fix: if neither file variant exists, return the image dict with the indexed filename
# so the frontend gets a URL that will 404 gracefully rather than no image at all.
```

**Verification:** `TestImageFallback` in `test_bug_fixes.py` — confirm test class name at implementation.

---

### Fix 3 — Recovery Card Insertion

**File:** `frontend/src/context/SessionContext.jsx`

**Change:** The `REPLACE_UPCOMING_CARD` and `INSERT_RECOVERY_CARD` dispatch sequence in `goToNextCard()` is confirmed correct in the current codebase (lines ~177 and ~408). This fix is primarily a test-coverage exercise — no code change expected. If the test reveals a gap, the fix is to ensure the dispatch order is:

```javascript
dispatch({ type: "REPLACE_UPCOMING_CARD", payload: res.data });
if (res.data?.recovery_card) {
    dispatch({ type: "INSERT_RECOVERY_CARD", payload: res.data.recovery_card });
}
dispatch({ type: "NEXT_CARD" });
```

**Verification:** `TestRecoveryCardInsertion` in `test_bug_fixes.py` — pure Python simulation of the reducer logic.

---

### Fix 4A — FAST-Mode Detection Floor

**File:** `backend/src/adaptive/adaptive_engine.py`, `build_blended_analytics()`

**Change:** The floor is confirmed present at line 625:
```python
expected_time = max(baseline_time, 90.0)
```

Verify no other call sites compute `expected_time` without the floor.

**Grep check:**
```
grep -n "expected_time" backend/src/adaptive/adaptive_engine.py
```

**Verification:** `TestFastModeDetection` in `test_bug_fixes.py` — at least 2 test cases:
- Student with 10 s average completing in 85 s → `expected_time = 90.0`, ratio < 1.0 → FAST
- Student with 200 s average completing in 85 s → `expected_time = 200.0`, ratio > 1.0 → NOT FAST

---

### Fix 4B — Conservative Cap

**File:** `backend/src/adaptive/adaptive_engine.py` (or `config.py` if extracted as a constant)

**Change:** The consecutive-signal threshold for mode switching from 5 → 2.

**Verification:** `TestConservativeCap` in `test_bug_fixes.py` — test that after 2 (not 5) consistent signals the mode switches.

---

### Fix 5A — Property Batching

**File:** `backend/src/api/teaching_service.py`, `generate_cards()` call to `_batch_consecutive_properties()`

**Current state (confirmed at line 1042):**
```python
sub_sections = self._batch_consecutive_properties(sub_sections)
```

The function `_batch_consecutive_properties` (line 2219) merges consecutive PROPERTY-type sections up to `max_batch=5`. This is already wired. Verify the call site is present and the function signature matches.

**Verification:** `TestPropertyBatching` in `test_bug_fixes.py` — at least 2 test cases:
- 3 consecutive PROPERTY sections → merged into 1 PROPERTY_BATCH
- Non-consecutive PROPERTY sections → not merged

---

### P1-A — `passed` Field Removal

**File:** `frontend/src/context/SessionContext.jsx`

**Change 1 — Reducer (line ~269):**
```javascript
// Remove `passed` from destructure
const { mastered, remediation_needed, score, attempt, locked, best_score } = action.payload;

// Remove `passed` from condition
if (mastered) {
    // completion logic
}
```

**Change 2 — PostHog analytics call (line ~546):**
```javascript
// Before:
if (res.data.mastered || res.data.passed) {

// After:
if (res.data.mastered) {
```

**Grep check to find all `passed` references:**
```
grep -n "passed" frontend/src/context/SessionContext.jsx
```

---

### P2 — Dead Code Removal

#### Dead Functions — `backend/src/api/teaching_service.py`

Confirm each function has no call sites before deletion:

| Line (approx) | Function | Confirmation command |
|---------------|----------|----------------------|
| 1555 | `_find_missing_sections` | Currently has a call site at line 1084 — verify whether this should be kept or whether the call site should also be removed |
| 1929 | `_split_into_n_chunks` | Grep for `_split_into_n_chunks` across repo |
| 1946 | `_group_sub_sections` | Grep for `_group_sub_sections` across repo |
| 2116 | `_extract_inline_image_filenames` | Grep for `_extract_inline_image_filenames` across repo |
| 2216 | `_get_checking_messages` | Has a call site at line 2391 — verify before deletion |

**Important:** The audit report states `_find_missing_sections` (line 1555) and `_get_checking_messages` (line 2216) have no call sites. However, the live grep above found call sites at lines 1084 and 2391 respectively. **The backend developer must re-verify these two functions before removal.** If call sites exist, keep the function and remove only the three confirmed dead ones (`_split_into_n_chunks`, `_group_sub_sections`, `_extract_inline_image_filenames`).

#### Dead Constants — `backend/src/config.py`

| Constant | Grep before delete |
|----------|--------------------|
| `EMBEDDING_DIMENSIONS` | `grep -rn "EMBEDDING_DIMENSIONS" backend/src/` |
| `XP_CARD_ADVANCE` | `grep -rn "XP_CARD_ADVANCE" backend/src/ frontend/src/` |
| `ADAPTIVE_NUMERIC_STATE_STRUGGLING_MAX` | `grep -rn "ADAPTIVE_NUMERIC_STATE_STRUGGLING_MAX" backend/src/` |
| `ADAPTIVE_NUMERIC_STATE_FAST_MIN` | `grep -rn "ADAPTIVE_NUMERIC_STATE_FAST_MIN" backend/src/` |
| `BOOK_ORDER` | `grep -rn "BOOK_ORDER" backend/src/` |

Delete only constants confirmed to have zero references.

---

## 10. Testing Strategy

### Unit Tests — `backend/tests/test_bug_fixes.py`

All tests are pure unit tests with zero I/O, zero LLM calls, and zero database connections. The test file already exists at `backend/tests/test_bug_fixes.py` as an untracked file.

| Test Class | Fix Covered | Test Count |
|------------|-------------|-----------|
| `TestCardOrdering` | Fix 1 | 4 |
| `TestImageFilter` | Fix 2A | 5+ |
| `TestImageFallback` | Fix 2B | 2+ |
| `TestRecoveryCardInsertion` | Fix 3 | 2+ |
| `TestFastModeDetection` | Fix 4A | 2+ |
| `TestConservativeCap` | Fix 4B | 2+ |
| `TestPropertyBatching` | Fix 5A | 2+ |

**Run command:**
```bash
cd backend
python -m pytest tests/test_bug_fixes.py -v
```

### Manual Verification Checklist

After backend changes:
- [ ] Start backend: `python -m uvicorn src.api.main:app --reload --port 8889`
- [ ] Confirm no import errors (dead function/constant removal)
- [ ] Generate a lesson for a Prealgebra concept; confirm cards appear in section order
- [ ] Confirm images of type PHOTO and TABLE appear in generated cards (Fix 2A)
- [ ] Check backend logs for `logger.warning` output during pipeline re-run (P1-B)

After frontend changes:
- [ ] Complete a Socratic session to mastery; confirm completion UI appears (P1-A)
- [ ] Answer both MCQs wrong on a card; confirm recovery card appears next (Fix 3)

### Regression: No New Failures

Running the full `pytest` suite must produce zero new failures. Baseline: all tests in `test_bug_fixes.py` pass; no regressions in any other test file.

---

## Key Decisions Requiring Stakeholder Input

1. **`_find_missing_sections` and `_get_checking_messages` dead-code status:** The audit report identifies these as dead, but live grep found call sites. The backend developer must inspect the call sites to determine whether they represent dead call paths (wrapped in unreachable conditions) or live paths. Only delete if confirmed dead after code-path analysis.

2. **Fix 4B constant name:** The implementation plan refers to `ADAPTIVE_CONSERVATIVE_CAP`. If this constant does not yet exist in `config.py` and the value is currently hardcoded in `adaptive_engine.py`, the backend developer should extract it to `config.py` as part of Fix 4B for future tunability.

3. **Fix 2B fallback behaviour:** The specification says "retain indexed filename." If the frontend's `onError` handler on image elements produces a visible broken image icon rather than silently hiding the element, UX team should confirm this is acceptable before deploying Fix 2B.
