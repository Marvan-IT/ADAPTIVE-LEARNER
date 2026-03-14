# Master Card Generation Engine — Detailed Low-Level Design

**Feature name:** Master Card Generation Engine
**Date:** 2026-03-11
**Status:** Design complete — awaiting stakeholder approval

---

## 1. Component Breakdown

### 1.1 Section Classifier (`_SECTION_CLASSIFIER`)

**Responsibility:** Map each `##` sub-section heading to a `SectionType` enum via ordered regex matching.

**Location:** `backend/src/api/teaching_service.py` — module-level constant.

**Interface:**
```python
from enum import StrEnum

class SectionType(StrEnum):
    LEARNING_OBJECTIVES = "LEARNING_OBJECTIVES"
    EXAMPLE             = "EXAMPLE"
    TRY_IT              = "TRY_IT"
    SOLUTION            = "SOLUTION"
    HOW_TO              = "HOW_TO"
    PREREQ_CHECK        = "PREREQ_CHECK"
    TIP                 = "TIP"
    END_MATTER          = "END_MATTER"
    SUPPLEMENTARY       = "SUPPLEMENTARY"  # default / unrecognised

# Ordered list: first match wins
_SECTION_CLASSIFIER: list[tuple[re.Pattern, SectionType]] = [
    (re.compile(r"^learning objectives?\b",   re.I), SectionType.LEARNING_OBJECTIVES),
    (re.compile(r"^example\s+\d+\.\d+",       re.I), SectionType.EXAMPLE),
    (re.compile(r"^try\s+it\s+\d+\.\d+",      re.I), SectionType.TRY_IT),
    (re.compile(r"^solution\b",                re.I), SectionType.SOLUTION),
    (re.compile(r"^how\s+to\b",               re.I), SectionType.HOW_TO),
    (re.compile(r"^be\s+prepared\b",          re.I), SectionType.PREREQ_CHECK),
    (re.compile(r"^(tip|note|media)\b",       re.I), SectionType.TIP),
    (re.compile(r"^(key\s+(concepts?|terms?)|section\s+exercises?|practice\s+makes\s+perfect|everyday\s+math|writing\s+exercises?|self\s+check)", re.I), SectionType.END_MATTER),
]

def _classify_section(heading: str) -> SectionType:
    heading = heading.strip().lstrip("#").strip()
    for pattern, section_type in _SECTION_CLASSIFIER:
        if pattern.match(heading):
            return section_type
    return SectionType.SUPPLEMENTARY
```

---

### 1.2 Blueprint Builder (`_build_textbook_blueprint`)

**Responsibility:** Convert a list of raw sub-sections (heading + text) into an ordered, pedagogically-structured blueprint. Merges SOLUTION into preceding EXAMPLE. Merges TIP into preceding item. Skips PREREQ_CHECK, END_MATTER. Emits WARNING if result is empty.

**Location:** `backend/src/api/teaching_service.py` — private module function.

**Interface:**
```python
@dataclass
class BlueprintItem:
    section_type: SectionType
    heading:      str
    text:         str          # merged: item text + optional solution + optional tip
    index:        int          # position in source section list (for ordering)

def _build_textbook_blueprint(
    sub_sections: list[dict],  # [{"heading": str, "text": str}]
) -> list[BlueprintItem]:
    """
    Returns ordered list of BlueprintItems.
    Skipped types: PREREQ_CHECK, END_MATTER, LEARNING_OBJECTIVES.
    Falls back to flat SUPPLEMENTARY list if result is empty.
    """
```

**Algorithm:**
1. Iterate sub-sections, classify each heading.
2. Skip PREREQ_CHECK, END_MATTER, LEARNING_OBJECTIVES.
3. On SOLUTION: append solution text to the most recent EXAMPLE or TRY_IT item. If no preceding item, treat as SUPPLEMENTARY.
4. On TIP: append as "Pro tip: {text}" to the most recent non-skipped item.
5. On HOW_TO: emit as-is (generates TEACH card with numbered steps).
6. If output list is empty: log `WARNING blueprint empty for concept — falling back to flat sections`; return all sub-sections as SUPPLEMENTARY items.

---

### 1.3 Domain Classifier (`_classify_domain`)

**Responsibility:** Assign a domain TYPE (A–G) to each `BlueprintItem.text` using keyword matching. Domain type informs MCQ distractor strategy in the prompt.

**Location:** `backend/src/api/teaching_service.py` — private module function.

**Interface:**
```python
class DomainType(StrEnum):
    TYPE_A = "TYPE_A"  # Arithmetic
    TYPE_B = "TYPE_B"  # Equations
    TYPE_C = "TYPE_C"  # Fractions
    TYPE_D = "TYPE_D"  # Geometry
    TYPE_E = "TYPE_E"  # Definitions / Properties
    TYPE_F = "TYPE_F"  # Percents / Proportions
    TYPE_G = "TYPE_G"  # Exponents / Polynomials

_DOMAIN_KEYWORDS: dict[DomainType, list[str]] = {
    DomainType.TYPE_A: ["add", "subtract", "multiply", "divide", "whole number", "arithmetic"],
    DomainType.TYPE_B: ["solve", "equation", "equality", "inequality", "variable", "expression"],
    DomainType.TYPE_C: ["fraction", "numerator", "denominator", "mixed number", "improper"],
    DomainType.TYPE_D: ["geometry", "area", "perimeter", "volume", "angle", "triangle", "circle"],
    DomainType.TYPE_E: ["define", "definition", "property", "language of algebra", "term", "coefficient"],
    DomainType.TYPE_F: ["percent", "proportion", "ratio", "rate", "unit rate"],
    DomainType.TYPE_G: ["exponent", "polynomial", "monomial", "binomial", "degree", "power"],
}

def _classify_domain(text: str) -> DomainType:
    """Keyword frequency vote; TYPE_E is default if no domain wins."""
```

**Algorithm:** Lowercase text; count keyword matches per domain type; return winner. Tie-break: TYPE_E (definitions). Minimum 1 keyword match required; otherwise TYPE_E.

---

### 1.4 Prompt Builder — Delivery Mode Block (`build_cards_system_prompt`)

**Responsibility:** Compose the full system prompt by injecting a delivery-mode-specific block and a domain-type-specific MCQ distractor block.

**Location:** `backend/src/api/prompts.py`.

**Delivery mode derivation (from existing `LearningProfile`):**

| LearnerProfile condition | Delivery Mode |
|--------------------------|---------------|
| speed == SLOW or comprehension == STRUGGLING | STRUGGLING |
| speed == FAST and comprehension in {OK, STRONG} | FAST |
| default | NORMAL |

**Delivery mode prompt blocks:**

```
STRUGGLING mode additions:
  - Begin every EXAMPLE card with a plain-English analogy before any math.
  - Use step-by-step narration: label each step "Step 1:", "Step 2:", etc.
  - For APPLICATION cards, always apply this 6-step scaffold:
      Step 1: Read the problem — what are we asked to find?
      Step 2: Identify what we know.
      Step 3: Translate words to math.
      Step 4: Solve.
      Step 5: Check your answer.
      Step 6: Write the answer as a sentence.
  - MCQ difficulty: EASY. Use one obviously wrong distractor; avoid near-miss options.

NORMAL mode additions:
  - Balance explanation depth with brevity.
  - MCQ difficulty: MEDIUM. Include one plausible near-miss distractor.

FAST mode additions:
  - Use compact mathematical notation; skip prose narration of steps.
  - Merge consecutive TRY_IT items into a single multi-part QUESTION card.
  - MCQ difficulty: HARD. All distractors are plausible near-misses or common errors.
```

**Domain-type MCQ distractor blocks (injected after delivery mode block):**

| Domain | Distractor strategy injected into prompt |
|--------|------------------------------------------|
| TYPE_A | "Distractors must be the results of common arithmetic errors: off-by-one, wrong operation, digit reversal." |
| TYPE_B | "Distractors must be the results of common equation errors: wrong sign flip, failure to distribute, incorrect isolation step." |
| TYPE_C | "Distractors must use numerator/denominator confusion or failure to find a common denominator." |
| TYPE_D | "Distractors must confuse area with perimeter, or use the wrong dimension formula." |
| TYPE_E | "Distractors must use near-synonym terms or mix definitions from adjacent sections." |
| TYPE_F | "Distractors must result from percent/decimal conversion errors or proportion setup errors." |
| TYPE_G | "Distractors must result from incorrect exponent rules: adding exponents instead of multiplying, or wrong sign." |

---

### 1.5 Card Type Taxonomy

**9 card types and their prompt generation rules:**

| Card Type | Source Section Type | MCQ Rule | Delivery notes |
|-----------|--------------------|-----------|---------------------------------|
| TEACH | SUPPLEMENTARY / HOW_TO / LEARNING_OBJECTIVES | Tests definition or concept label | HOW_TO → numbered steps |
| EXAMPLE | EXAMPLE | Uses different numbers from the worked example | Must show worked solution in `answer` |
| APPLICATION | (injected by LLM for word-problem contexts) | Tests operation identification, not numeric result | STRUGGLING: 6-step scaffold |
| QUESTION | TRY_IT | "One more quick one" — similar to the Try It | FAST: consecutive TRY_ITs merged |
| EXERCISE | END_MATTER (if not skipped) | Practice problem — no scaffold | Only generated in NORMAL/FAST modes |
| VISUAL | Any section containing an image reference | Tests what the diagram illustrates | Requires `[IMAGE:N]` marker |
| RECAP | Last item in blueprint | Summarises the 3 most important points | No MCQ required (optional) |
| FUN | Injected by service (1 per concept max) | None | Interest-personalized hook |
| CHECKIN | Injected by service (every N cards) | Mood/engagement prompt | No MCQ |

**Note:** EXERCISE cards are only emitted if the END_MATTER contains numbered problems. END_MATTER is not fully skipped when it contains numbered practice problems — only `key concepts`, `writing exercises`, `everyday math` sub-types are skipped.

---

### 1.6 Updated `CardMCQ` Schema

**Location:** `backend/src/api/teaching_schemas.py`

```python
from typing import Literal

class CardMCQ(BaseModel):
    question:      str
    options:       list[str] = Field(..., min_length=4, max_length=4)
    correct_index: int       = Field(..., ge=0, le=3)
    explanation:   str
    difficulty:    Literal["EASY", "MEDIUM", "HARD"] = "MEDIUM"
```

**Migration note:** `difficulty` has a default value of `"MEDIUM"` — fully backward compatible with existing card cache entries that lack the field.

---

### 1.7 Updated `LessonCard` Schema

**Location:** `backend/src/api/teaching_schemas.py`

```python
from typing import Literal

CARD_TYPES = Literal[
    "TEACH", "EXAMPLE", "APPLICATION", "QUESTION",
    "EXERCISE", "VISUAL", "RECAP", "FUN", "CHECKIN"
]

class LessonCard(BaseModel):
    card_type:     CARD_TYPES = "TEACH"
    section_id:    str | None = None
    title:         str
    content:       str
    answer:        str | None = None
    question:      CardMCQ | None = None
    image_indices: list[int] = Field(default_factory=list)
    difficulty:    Literal["EASY", "MEDIUM", "HARD"] | None = None
    domain_type:   str | None = None   # TYPE_A through TYPE_G — informational
```

---

## 2. Data Design

### 2.1 Blueprint Item (in-memory only)

No database changes in Phase 1. Blueprint items are transient; they exist only during the `generate_cards()` call.

```
BlueprintItem
  section_type : SectionType
  heading      : str
  text         : str         (merged: base + optional solution + optional tip)
  index        : int
  domain_type  : DomainType  (populated after _classify_domain())
```

### 2.2 Updated Card Fields in PostgreSQL

The `card_interactions` table stores `card_type` and `difficulty` for analytics. These columns already exist from the adaptive-real-tutor design. No new migrations required in Phase 1.

Verify that `card_interactions.card_type` is `VARCHAR(32)` and accepts the new card type values (EXAMPLE, APPLICATION, QUESTION, EXERCISE). This is a data verification step, not a schema change.

### 2.3 Caching Strategy (Phase 1)

No change to existing `cache_version` mechanism. Card sets generated by the new blueprint pipeline are cached identically to current output. Cache key: `(concept_id, student_id, profile_label)`.

### 2.4 Phase 2 — Concept-Level Shared Card Cache (out of scope, described for continuity)

New table: `concept_card_cache`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| concept_id | VARCHAR(200) | Unique per delivery mode |
| delivery_mode | VARCHAR(16) | STRUGGLING / NORMAL / FAST |
| cards_json | JSONB | Serialised `list[LessonCard]` |
| generated_at | TIMESTAMPTZ | |
| cache_version | INTEGER | Invalidated on concept re-index |
| book_slug | VARCHAR(50) | For partitioning |

Requires Alembic migration `006_concept_card_cache`. Estimated 80–95% LLM cost reduction at scale (one generation per concept per mode, shared by all students).

---

## 3. API Design

No new API endpoints in Phase 1. The existing `POST /api/v2/sessions/{id}/cards` endpoint is unchanged externally. The response schema gains the `difficulty` and `domain_type` fields on `LessonCard` (additive, backward compatible).

### Existing endpoint — response change

```
POST /api/v2/sessions/{id}/cards
Response 200: { "cards": LessonCard[] }

LessonCard additions (non-breaking):
  + difficulty:   "EASY" | "MEDIUM" | "HARD" | null
  + domain_type:  "TYPE_A" | ... | "TYPE_G" | null
  + card_type now includes: "EXAMPLE" | "APPLICATION" | "QUESTION" | "EXERCISE"
```

### Versioning strategy

No version bump required. Additive fields with defaults are backward compatible under the current v2 contract.

---

## 4. Sequence Diagrams

### 4.1 Happy Path — Card Generation with Blueprint Pipeline

```
Frontend          TeachingRouter       TeachingService        OpenAI
   │                    │                    │                   │
   │ POST /cards        │                    │                   │
   │───────────────────▶│                    │                   │
   │                    │ generate_cards()   │                   │
   │                    │───────────────────▶│                   │
   │                    │                    │                   │
   │                    │                    │ _parse_sub_sections()
   │                    │                    │ (existing)
   │                    │                    │                   │
   │                    │                    │ _build_textbook_blueprint()
   │                    │                    │ [classify → merge → filter]
   │                    │                    │                   │
   │                    │                    │ _classify_domain() per item
   │                    │                    │                   │
   │                    │                    │ build_cards_system_prompt(
   │                    │                    │   delivery_mode, domain_types)
   │                    │                    │                   │
   │                    │                    │ build_cards_user_prompt(
   │                    │                    │   blueprint_items)
   │                    │                    │                   │
   │                    │                    │ chat.completions.create()
   │                    │                    │──────────────────▶│
   │                    │                    │    cards JSON     │
   │                    │                    │◀──────────────────│
   │                    │                    │                   │
   │                    │                    │ validate_and_repair_cards()
   │                    │                    │                   │
   │                    │ [cards]            │                   │
   │◀───────────────────│◀───────────────────│                   │
```

### 4.2 Blueprint Empty Fallback

```
TeachingService
   │
   │ _build_textbook_blueprint(sub_sections)
   │
   │ [all classified as skipped]
   │
   │ len(result) == 0
   │
   │ logger.warning("blueprint empty for concept X — fallback to flat sections")
   │
   │ return [BlueprintItem(SUPPLEMENTARY, s["heading"], s["text"], i)
   │         for i, s in enumerate(sub_sections)]
   │
   │ [continues to prompt build with SUPPLEMENTARY items]
```

### 4.3 Frontend — MCQ Wrong × 2 Auto-Advance

```
CardLearningView        SessionContext
      │                       │
      │ handleMCQAnswer(wrong) │
      │───────────────────────▶│
      │                        │ cardStates[idx].wrongCount += 1
      │                        │ if wrongCount == 1 → triggerMCQRegen()
      │◀───────────────────────│ ADAPTIVE_CARD_LOADED (replacementMcq set)
      │
      │ handleMCQAnswer(wrong again)
      │───────────────────────▶│
      │                        │ !!cardStates[idx].replacementMcq === true
      │                        │ → dispatch NEXT_CARD
      │◀───────────────────────│
      │ [auto-advances, no hang]
```

---

## 5. Integration Design

### 5.1 LLM Integration — Blueprint-aware Prompt

The user prompt changes from a flat list of sub-section texts to a structured blueprint list. Each blueprint item is labelled with its `section_type` and `domain_type` to give the LLM explicit pedagogical context:

```
[BLUEPRINT ITEM 1 — type: EXAMPLE — domain: TYPE_A]
Example 1.3: Adding Whole Numbers
Jake has 14 apples and buys 7 more...
Solution: 14 + 7 = 21

[BLUEPRINT ITEM 2 — type: TRY_IT — domain: TYPE_A]
Try It 1.4
Sandra has 23 stamps. She buys 15 more. How many does she have?
```

### 5.2 Frontend Integration

**`CardLearningView.jsx` changes:**

1. Card type badge rendering:
```jsx
const CARD_TYPE_BADGE = {
  APPLICATION: { label: "Real World", color: "#e67e22" },
  EXERCISE:    { label: "Practice",   color: "#8e44ad" },
  EXAMPLE:     { label: "Example",    color: "#2980b9" },
  QUESTION:    { label: "Try It",     color: "#27ae60" },
  // TEACH, RECAP, FUN, VISUAL, CHECKIN — no badge (existing behavior)
};
```

2. MCQ wrong × 2 auto-advance:
```jsx
// Inside handleMCQAnswer when answer is wrong:
const hasReplacementMcq = !!cardStates[currentCardIndex]?.replacementMcq;
if (hasReplacementMcq) {
  // Second wrong answer — auto-advance
  dispatch({ type: "NEXT_CARD" });
  return;
}
// First wrong answer — existing regen flow
triggerMCQRegen();
```

---

## 6. Security Design

No new attack surface introduced. The blueprint pipeline operates entirely on text already retrieved from ChromaDB (trusted internal store). No user input flows into the classifier or domain lookup.

Existing controls apply:
- Input validation: `StudentResponseRequest.message` max 2000 chars
- LLM output sanitisation: `skipHtml={true}` on all `react-markdown` instances
- Auth: `APIKeyMiddleware` on all `/api/v2/` routes
- Rate limiting: `RATE_LIMIT_LLM_HEAVY = 10/minute` on card generation endpoints

---

## 7. Observability Design

### 7.1 New Log Lines (structured, `logging` module)

| Event | Level | Message format |
|-------|-------|----------------|
| Blueprint constructed | INFO | `blueprint: concept=%s items=%d skipped=%d fallback=%s` |
| Domain classification | DEBUG | `domain_classify: concept=%s type=%s keyword_hits=%d` |
| Delivery mode selected | INFO | `delivery_mode: student=%s mode=%s speed=%s comprehension=%s` |
| Empty blueprint fallback | WARNING | `blueprint empty for concept %s — falling back to flat sections` |
| MCQ difficulty assigned | DEBUG | `mcq_difficulty: card_type=%s difficulty=%s profile=%s` |

### 7.2 Metrics (existing PostHog)

New events to add:
- `card_generated` — properties: `card_type`, `difficulty`, `domain_type`, `delivery_mode`
- `mcq_wrong_autoadvance` — properties: `card_index`, `concept_id`, `difficulty`

### 7.3 Alerting

No new alerting thresholds. Existing OpenAI error rate and card generation latency alerts cover this feature. Monitor `blueprint empty fallback` log count — spike indicates OpenStax format deviation in a new book.

---

## 8. Error Handling and Resilience

| Scenario | Handling |
|----------|----------|
| `_classify_section` receives empty heading | Returns `SectionType.SUPPLEMENTARY` — treated as TEACH content |
| `_build_textbook_blueprint` returns empty list | Falls back to flat SUPPLEMENTARY items with WARNING log |
| LLM returns card with unknown `card_type` | `validate_and_repair_cards()` defaults it to `"TEACH"` |
| LLM returns card missing `difficulty` field | `CardMCQ` schema default `"MEDIUM"` is applied by Pydantic |
| LLM returns MCQ with `correct_index` out of range | Schema validator raises `ValidationError`; card is dropped from output |
| Domain classifier finds no keyword matches | Returns `DomainType.TYPE_E` (definitions — safest default) |
| FAST mode multi-part QUESTION merge produces card > token budget | `max_tokens` ceiling enforced at LLM call; truncated output caught by `_salvage_truncated_json()` |

**Retry policy:** Unchanged from existing pattern — 3 attempts with `asyncio.sleep(2 * attempt)` exponential back-off. Blueprint pipeline runs before first LLM call; it does not introduce additional retry surface.

---

## 9. Testing Strategy

### 9.1 Unit Tests (comprehensive-tester agent)

| Test | Location | Coverage target |
|------|----------|----------------|
| `test_classify_section_known_types` | `tests/test_blueprint.py` | All 8 named SectionType values + SUPPLEMENTARY default |
| `test_classify_section_case_insensitive` | `tests/test_blueprint.py` | "Example 1.3" / "EXAMPLE 1.3" / "example 1.3" |
| `test_build_blueprint_merges_solution` | `tests/test_blueprint.py` | SOLUTION appended to preceding EXAMPLE |
| `test_build_blueprint_merges_tip` | `tests/test_blueprint.py` | TIP appended as "Pro tip:" suffix |
| `test_build_blueprint_skips_prereq_check` | `tests/test_blueprint.py` | PREREQ_CHECK absent from output |
| `test_build_blueprint_empty_fallback` | `tests/test_blueprint.py` | All-skipped input → SUPPLEMENTARY fallback + WARNING log |
| `test_classify_domain_type_a` | `tests/test_blueprint.py` | "add whole numbers" → TYPE_A |
| `test_classify_domain_tie_defaults_to_type_e` | `tests/test_blueprint.py` | Equal keyword counts → TYPE_E |
| `test_card_mcq_difficulty_default` | `tests/test_schemas.py` | Missing `difficulty` → "MEDIUM" |
| `test_card_mcq_difficulty_invalid` | `tests/test_schemas.py` | "EXTREME" raises `ValidationError` |
| `test_delivery_mode_struggling_rule` | `tests/test_prompt_builder.py` | SLOW speed → STRUGGLING block present in prompt |
| `test_delivery_mode_fast_rule` | `tests/test_prompt_builder.py` | FAST speed + STRONG comprehension → FAST block |
| `test_mcq_wrong_autoadvance_logic` | `tests/test_session_context.js` (Jest) | `replacementMcq` present → NEXT_CARD dispatched |

### 9.2 Integration Tests

| Test | Description |
|------|-------------|
| `test_generate_cards_blueprint_pipeline` | Calls `generate_cards()` with a real concept fixture; asserts `card_type` distribution includes EXAMPLE cards |
| `test_generate_cards_mcq_difficulty_mapped` | STRUGGLING profile → all MCQ difficulty == "EASY" |
| `test_generate_cards_domain_type_in_response` | Response includes `domain_type` field on each card |
| `test_generate_cards_empty_concept_fallback` | Concept with no EXAMPLE/TRY_IT sections still produces non-empty card set |

### 9.3 Performance Tests

Run against `PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS` (10 sub-sections, mixed types):
- STRUGGLING profile: P95 < 18s
- NORMAL profile: P95 < 12s
- FAST profile: P95 < 8s

### 9.4 Contract Tests

Verify that the existing `sessions.js` Axios wrapper parses responses that include new `difficulty` and `domain_type` fields without error (additive fields must not break destructuring).

---

## Key Decisions Requiring Stakeholder Input

1. **EXERCISE card generation from END_MATTER** — Should numbered practice problems from end-of-section be included (currently in-scope) or deferred to Phase 2? The END_MATTER skip rule in `_SECTION_CLASSIFIER` only partially excludes them.
2. **`domain_type` field visibility to student** — Should `domain_type` be surfaced in the frontend (e.g., a "Geometry" section label) or remain internal/analytics-only?
3. **APPLICATION card injection policy** — Should APPLICATION cards be LLM-injected freely wherever appropriate, or restricted to one per concept to avoid over-scaffolding?
4. **FAST mode TRY_IT merging threshold** — How many consecutive TRY_IT items must appear before they are merged into a multi-part QUESTION? Current proposal: 2 or more consecutive items.
