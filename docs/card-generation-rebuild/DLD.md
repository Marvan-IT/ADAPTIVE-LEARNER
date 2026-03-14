# Detailed Low-Level Design: Card Generation Rebuild

**Feature slug:** `card-generation-rebuild`
**Date:** 2026-03-09
**Author:** Solution Architect

---

## 1. Component Breakdown

| Component | File | Single Responsibility |
|-----------|------|-----------------------|
| `TeachingService.generate_cards()` | `backend/src/api/teaching_service.py` | Orchestrates card generation: retrieve concept, parse sections, build prompts, call LLM, post-process. Receives Fixes A, B. |
| `TeachingService._generate_cards_single()` | `backend/src/api/teaching_service.py` | Executes single LLM call with retry logic. Receives Fix C. |
| `TeachingService._group_by_major_topic()` | `backend/src/api/teaching_service.py` | Static method — semantic grouper that absorbs EXAMPLE/Solution/TRY IT into parent topic. Already implemented; Fix A wires it into the call path. |
| `prompts._build_card_profile_block()` | `backend/src/api/prompts.py` | Builds adaptive profile instruction block appended to system prompt. Receives Fix D. |
| `prompts.build_cards_system_prompt()` | `backend/src/api/prompts.py` | Builds the full system prompt for card generation. Receives Fix F. |
| `prompts.build_cards_user_prompt()` | `backend/src/api/prompts.py` | Builds the per-request user prompt with section content. Receives Fix E. |
| `config.py` | `backend/src/config.py` | Single source for all tunable constants. Receives three new token-budget constants. |

---

## 2. Data Design

### No schema changes

No new database tables, columns, or ChromaDB fields are introduced. All changes are in-memory, within the request/response lifecycle of `generate_cards()`.

### New constants in `config.py`

```python
# Card generation token budgets (adaptive, profile-driven)
# SLOW/STRUGGLING learners need 2-3 cards/section with richer explanations
CARDS_MAX_TOKENS_SLOW: int = 16_000      # ceiling for SLOW or STRUGGLING profile
CARDS_MAX_TOKENS_SLOW_FLOOR: int = 8_000 # minimum even for short concepts
CARDS_MAX_TOKENS_SLOW_PER_SECTION: int = 1_800

# NORMAL learners
CARDS_MAX_TOKENS_NORMAL: int = 12_000
CARDS_MAX_TOKENS_NORMAL_FLOOR: int = 6_000
CARDS_MAX_TOKENS_NORMAL_PER_SECTION: int = 1_200

# FAST/STRONG learners need fewer, denser cards
CARDS_MAX_TOKENS_FAST: int = 8_000
CARDS_MAX_TOKENS_FAST_FLOOR: int = 4_000
CARDS_MAX_TOKENS_FAST_PER_SECTION: int = 900
```

### Data flow (unchanged overall shape, grouping step added)

```
ChromaDB concept text
        │
_parse_sub_sections()          → list[{"title": str, "text": str}]  (57 micro-sections)
        │
[FIX A] _group_by_major_topic() → list[{"title": str, "text": str}]  (8–10 topic blocks)
        │
build_cards_user_prompt()      → str (prompt with section content + completeness checklist)
build_cards_system_prompt()    → str (profile instructions + density block + coverage rule)
        │
[FIX B] max_tokens computed    → int (profile-adaptive)
        │
_generate_cards_single(system_prompt, user_prompt, max_tokens)
        │
OpenAI API                     → {"cards": [...]}
        │
post-processing                → normalised card list (unchanged schema)
```

---

## 3. Fix Specifications

Each fix is described with exact file, line range, the change required, and the rationale.

---

### Fix A — Wire `_group_by_major_topic()` into `generate_cards()`

**File:** `backend/src/api/teaching_service.py`

**Location:** Lines 549–553 (the `_parse_sub_sections` call and fallback block).

**Current code:**
```python
sub_sections = self._parse_sub_sections(concept_text)
if not sub_sections:
    sub_sections = [{"title": concept_title, "content": concept_text}]
```

**Required change:**
```python
sub_sections = self._parse_sub_sections(concept_text)
if not sub_sections:
    sub_sections = [{"title": concept_title, "text": concept_text}]   # Fix A2: key "content" → "text"
else:
    sub_sections = self._group_by_major_topic(sub_sections)            # Fix A1: wire grouper
```

**Two sub-parts:**
- **Fix A1:** Call `_group_by_major_topic(sub_sections)` on the parsed result before the sections are used anywhere downstream. `_group_by_major_topic()` already handles the edge case where its input is empty (returns `sections` unchanged), so no guard is needed.
- **Fix A2:** Change `"content"` to `"text"` in the fallback dict. `_parse_sub_sections()` produces dicts with key `"text"`. The fallback dict must use the same key or `build_cards_user_prompt()` will raise `KeyError` at `sec["text"]` (line 861 of `prompts.py`).

**Log line to add after the grouping call (for observability):**
```python
logger.info(
    "cards section_grouping: concept=%s raw_sections=%d grouped_sections=%d",
    session.concept_id, len(self._parse_sub_sections(concept_text)), len(sub_sections),
)
```

Note: avoid calling `_parse_sub_sections` twice for the log. Capture the raw count before grouping:

```python
raw_sections = self._parse_sub_sections(concept_text)
if not raw_sections:
    sub_sections = [{"title": concept_title, "text": concept_text}]
    logger.info("cards section_grouping: concept=%s no_headers_found — using single block", session.concept_id)
else:
    sub_sections = self._group_by_major_topic(raw_sections)
    logger.info(
        "cards section_grouping: concept=%s raw=%d grouped=%d",
        session.concept_id, len(raw_sections), len(sub_sections),
    )
```

---

### Fix B — Compute adaptive `max_tokens` in `generate_cards()`

**File:** `backend/src/api/teaching_service.py`

**Location:** After the profile is built (line ~625) and before the LLM call (line ~663). Insert immediately before `cards_data = await self._generate_cards_single(...)`.

**New code block to insert:**
```python
# Compute profile-adaptive token budget. Token need scales with section count and
# learner profile. SLOW/STRUGGLING learners get 2-3 cards/section with richer explanations;
# FAST/STRONG learners get 1-2 denser cards/section.
n_sections = len(sub_sections)
if card_profile.speed == "SLOW" or card_profile.comprehension == "STRUGGLING":
    adaptive_max_tokens = min(
        CARDS_MAX_TOKENS_SLOW,
        max(CARDS_MAX_TOKENS_SLOW_FLOOR, n_sections * CARDS_MAX_TOKENS_SLOW_PER_SECTION),
    )
elif card_profile.speed == "FAST" and card_profile.comprehension == "STRONG":
    adaptive_max_tokens = min(
        CARDS_MAX_TOKENS_FAST,
        max(CARDS_MAX_TOKENS_FAST_FLOOR, n_sections * CARDS_MAX_TOKENS_FAST_PER_SECTION),
    )
else:
    adaptive_max_tokens = min(
        CARDS_MAX_TOKENS_NORMAL,
        max(CARDS_MAX_TOKENS_NORMAL_FLOOR, n_sections * CARDS_MAX_TOKENS_NORMAL_PER_SECTION),
    )
logger.info(
    "cards token_budget: concept=%s n_sections=%d profile=%s/%s max_tokens=%d",
    session.concept_id, n_sections, card_profile.speed, card_profile.comprehension, adaptive_max_tokens,
)
```

**Required import addition at top of the function (or module level):**
```python
from config import (
    CARDS_MAX_TOKENS_SLOW, CARDS_MAX_TOKENS_SLOW_FLOOR, CARDS_MAX_TOKENS_SLOW_PER_SECTION,
    CARDS_MAX_TOKENS_NORMAL, CARDS_MAX_TOKENS_NORMAL_FLOOR, CARDS_MAX_TOKENS_NORMAL_PER_SECTION,
    CARDS_MAX_TOKENS_FAST, CARDS_MAX_TOKENS_FAST_FLOOR, CARDS_MAX_TOKENS_FAST_PER_SECTION,
)
```

In practice, `config.py` is already imported as a wildcard import or individual constants in this module — check the existing import block and extend it rather than adding a duplicate import.

**Updated call site:**
```python
cards_data = await self._generate_cards_single(
    system_prompt, user_prompt, max_tokens=adaptive_max_tokens,
)
```

---

### Fix C — Add `max_tokens` parameter to `_generate_cards_single()`

**File:** `backend/src/api/teaching_service.py`

**Location:** Line 833 — the `_generate_cards_single` method signature.

**Current signature:**
```python
async def _generate_cards_single(self, system_prompt: str, user_prompt: str) -> dict:
```

**Required change:**
```python
async def _generate_cards_single(
    self, system_prompt: str, user_prompt: str, max_tokens: int = 12_000
) -> dict:
```

**Internal usage (line ~843):**

Current:
```python
raw_json = await self._chat(messages=messages, max_tokens=8000)
```

Required:
```python
raw_json = await self._chat(messages=messages, max_tokens=max_tokens)
```

**Notes:**
- The default `max_tokens=12_000` matches `CARDS_MAX_TOKENS_NORMAL` so that any caller that does not pass a budget gets a reasonable value rather than the too-small legacy 8000.
- The `_chat()` method already accepts `max_tokens` as a keyword argument — no changes to `_chat()` needed.
- No other callers of `_generate_cards_single()` exist in the codebase (confirmed by grep). This is a non-breaking change regardless.

---

### Fix D — Add CARD DENSITY block to `_build_card_profile_block()`

**File:** `backend/src/api/prompts.py`

**Location:** `_build_card_profile_block()` function. The SUPPORT block starts at approximately line 580; the ACCELERATE block starts at approximately line 597. Insert the CARD DENSITY instruction inside each profile branch.

**SUPPORT branch** (inside `if learning_profile.comprehension == "STRUGGLING" or learning_profile.speed == "SLOW":`):

Append to the existing string passed to `parts.append(...)`:
```
"\nCARD DENSITY: Generate 2–3 cards per section. More cards means more opportunities to "
"practise each idea at a gentle pace. Never collapse two distinct ideas into one card."
```

Full updated `parts.append()` call for the SUPPORT branch:
```python
parts.append(
    "\nMODE: SUPPORT\n"
    "- Use vocabulary a child aged 8-10 would understand. No jargon without a plain-English definition first.\n"
    "- Open every card explanation with a concrete real-world example BEFORE introducing any formula or rule.\n"
    "- Use analogies that connect to everyday life (cooking, sports, money, building blocks).\n"
    "- Make every MCQ option plausible in plain language — avoid obviously silly distractors.\n"
    "- Tone: warm, patient, never rushed. Short sentences. No more than 4 sentences before a bullet point.\n"
    "- CARD DENSITY: Generate 2–3 cards per section. More cards means more practice opportunities at a gentle pace. "
    "Never collapse two distinct ideas into one card."
)
```

**ACCELERATE branch** (inside `elif learning_profile.speed == "FAST" and learning_profile.comprehension == "STRONG":`):
```python
parts.append(
    "\nMODE: ACCELERATE\n"
    "- ALL content, definitions, and formulas MUST appear — never skip substance because the student is fast.\n"
    "- Replace beginner analogies with real-world applications: show WHERE this concept is used in engineering, finance, coding, or science.\n"
    "- Add 'why it works' reasoning: after each rule or formula, explain the mathematical intuition behind it.\n"
    "- Include at least one challenging application example per card (edge case, non-obvious use, or extension).\n"
    "- Questions may use academic vocabulary. Distractors should represent common mathematical misconceptions, not guesses.\n"
    "- CARD DENSITY: Generate 1–2 cards per section. Combine closely related sub-ideas into a single card to maintain momentum. "
    "Omit no content — density means consolidation, not omission."
)
```

**Default branch** (no mode detected — the `else` / no matching profile block): No density block is inserted for NORMAL profiles. The LLM defaults to 1–2 cards per section via the system prompt's existing CARD SEQUENCE ORDER rules. This is intentional — avoid over-specification for the average case.

---

### Fix E — Add COMPLETENESS REQUIREMENT checklist to `build_cards_user_prompt()`

**File:** `backend/src/api/prompts.py`

**Location:** `build_cards_user_prompt()` function, at the return point. The `prompt` variable is assembled and returned at line ~928. Append the checklist before the return, after the `wrong_option_pattern` and profile blocks.

**New code block to insert after all other `prompt +=` statements, immediately before `return prompt`:**
```python
# COMPLETENESS REQUIREMENT — generated dynamically from the actual section titles
checklist_lines = []
for i, sec in enumerate(sub_sections, 1):
    checklist_lines.append(f"  {i}. {sec['title']}")
checklist_block = (
    "\n\nCOMPLETENESS REQUIREMENT — before closing your JSON, verify that your cards "
    "collectively cover ALL of the following sections. Every section MUST produce at least one card. "
    "Do not end the JSON until you have addressed every item on this list:\n"
    + "\n".join(checklist_lines)
    + "\n\nIf any section has no card yet, add a TEACH card for it now."
)
prompt += checklist_block
```

**Why at the end?** The LLM processes the user prompt end-to-end before generating a response. Placing the checklist last makes it the most recently seen instruction — it acts as a final reminder immediately before the LLM begins generating JSON output.

**Bounded size concern:** After `_group_by_major_topic()` runs, `sub_sections` will contain at most 10–12 items. Each line is approximately 10–40 characters. The checklist adds at most ~600 tokens — negligible.

---

### Fix F — Strengthen "COMPLETE COVERAGE" line in `build_cards_system_prompt()`

**File:** `backend/src/api/prompts.py`

**Location:** Line 739 — the COMPLETE COVERAGE line inside `build_cards_system_prompt()`.

**Current text:**
```
- COMPLETE COVERAGE: if a sub-section covers multiple topics, your cards MUST address every one.
```

**Required replacement:**
```
- COMPLETE COVERAGE — NON-NEGOTIABLE: Every section listed in the user prompt MUST produce at least
  one card. Omitting a section is a critical error. The completeness checklist at the end of the
  user prompt enumerates every required section — do not close your JSON until all are covered.
```

This change elevates the instruction from advisory ("MUST address") to explicitly error-framed, and creates a forward reference to the checklist added by Fix E, reinforcing both instructions.

---

## 4. Sequence Diagrams

### Happy path — slow learner, 10 grouped sections

```
generate_cards() called
        │
        ▼
KnowledgeService.get_concept_detail(concept_id)
        │  returns concept_text (57 raw sections after ## split)
        ▼
_parse_sub_sections(concept_text)
        │  returns 57 micro-section dicts [{"title": ..., "text": ...}]
        ▼
[FIX A] _group_by_major_topic(raw_sections)
        │  absorbs EXAMPLE/Solution/TRY IT into parents
        │  returns 10 grouped sections
        ▼
asyncio.gather(load_student_history(), load_wrong_option_pattern())
        │  returns history dict + None (no wrong pattern)
        ▼
build_learning_profile(mini)
        │  returns LearningProfile(speed="SLOW", comprehension="STRUGGLING")
        ▼
build_cards_system_prompt(...)    [FIX D: density block "2-3 cards/section"]
build_cards_user_prompt(...)      [FIX E: 10-item completeness checklist appended]
[FIX F: "COMPLETE COVERAGE - NON-NEGOTIABLE" in system prompt]
        ▼
[FIX B] n_sections=10, profile=SLOW → adaptive_max_tokens = min(16000, max(8000, 10*1800)) = 16000
        ▼
[FIX C] _generate_cards_single(system_prompt, user_prompt, max_tokens=16000)
        │  attempt 1: OpenAI gpt-4o, max_tokens=16000
        │  returns 22 cards (2–3 per section), complete JSON
        ▼
post-processing: validate schema, normalise question, assign images
        ▼
result cached in session.presentation_text
        ▼
JSON response: {"cards": [...22 cards...], "concept_title": ...}
```

### Error path — `_group_by_major_topic()` returns empty list (edge case)

```
_parse_sub_sections()  → 5 sections
_group_by_major_topic()
        │  all 5 sections match _SUPPORT_HEADING, groups = []
        │  fallback: returns sections (original 5, unchanged)
        ▼
continues normally with 5 sections
```

`_group_by_major_topic()` already handles this: `return groups if groups else sections`.

### Error path — `_parse_sub_sections()` returns empty (no `##` headers in concept text)

```
_parse_sub_sections()  → []
        ▼
[FIX A2] fallback: sub_sections = [{"title": concept_title, "text": concept_text}]
        │  key is "text" (not "content") — no KeyError
        ▼
build_cards_user_prompt() accesses sec["text"] → succeeds
        ▼
LLM receives 1 section; generates cards from full concept text
```

---

## 5. Integration Design

No external integrations added or changed. The OpenAI `_chat()` call already accepts `max_tokens` as a keyword argument. The only integration surface change is that `max_tokens` passed to OpenAI will now vary between 4,000 and 16,000 depending on profile and section count.

**Implication for the OpenAI `timeout` setting:** The existing `timeout=30.0` on `AsyncOpenAI` (confirmed hardened in `teaching_service.py` per the 2026-03-08 deployment readiness fixes) may be insufficient for a 16,000-token response. Estimated generation time for 16,000 tokens at OpenAI's typical throughput (~2,000 tokens/sec for `gpt-4o`) is approximately 8 seconds. The 30-second timeout provides comfortable headroom. No change required.

---

## 6. Security Design

No new attack surfaces. The fixes do not introduce new API endpoints, new inputs from external callers, or new data stored in the database. The only new user-controlled input touching this code path is the learner profile, which is derived from existing `student_id` and `session_id` — both already validated by the router.

---

## 7. Observability Design

### New log lines

| Fix | Log Location | Log Message Pattern | Level |
|-----|-------------|--------------------|----|
| A | `generate_cards()` after grouping | `"cards section_grouping: concept=%s raw=%d grouped=%d"` | INFO |
| B | `generate_cards()` after budget compute | `"cards token_budget: concept=%s n_sections=%d profile=%s/%s max_tokens=%d"` | INFO |

These two log lines allow post-deploy monitoring to confirm:
1. Grouping is working: `raw` should be ~57, `grouped` should be 8–12 for a typical concept.
2. Budget is adaptive: `max_tokens` should vary by profile (4000–16000 range).

### Existing log lines unchanged

The existing `"Card adaptive profile for student=%s concept=%s: speed=%s comp=%s eng=%s"` log at line 621 already provides the profile values — the new token_budget log is complementary, not redundant.

### Metrics and alerts

No new Prometheus metrics or dashboards needed for this fix. The two new INFO log lines are sufficient for initial validation. If OpenAI cost monitoring is already set up, the increase in average `max_tokens` for slow-learner sessions will surface automatically.

---

## 8. Error Handling and Resilience

### Fix A — grouping failure
`_group_by_major_topic()` is a pure static method with no I/O. It cannot raise an exception in normal operation. Its edge case (all sections are "supporting") is already handled by the `return groups if groups else sections` fallback. No additional error handling required.

### Fix B — profile attribute missing
If `card_profile.speed` or `card_profile.comprehension` is missing (unexpected `LearningProfile` shape), the `elif` and `else` branches will still match, defaulting to NORMAL tier. This is safe because `LearningProfile` is a Pydantic model with explicit field defaults.

### Fix C — `max_tokens` argument to `_chat()`
If `max_tokens` exceeds the model's context window minus the prompt token count, OpenAI returns a 400 error. The existing retry loop in `_generate_cards_single()` will log and retry. After 3 failures it raises `ValueError`, which propagates to the router and returns a 500. This is the existing behaviour and is not made worse by this fix.

### Fix E — empty `sub_sections` list
If `sub_sections` is empty at the point where the checklist is built, `checklist_lines` will be an empty list and the checklist block will produce a grammatically correct but empty list. This is not a regression — if `sub_sections` is empty, card generation would already produce an empty deck.

---

## 9. Testing Strategy

### Unit tests (pytest, no I/O)

| Test ID | Method Under Test | Scenario | Assertion |
|---------|------------------|----------|-----------|
| UT-A1 | `_group_by_major_topic()` | Input: 57 sections including "EXAMPLE 1.39", "Solution", "TRY IT" | Output: 8–12 groups; no section with title matching `_SUPPORT_HEADING` appears as a top-level group |
| UT-A2 | `_group_by_major_topic()` | Input: all sections are "EXAMPLE ..." | Output: returned list equals input (fallback) |
| UT-A3 | `generate_cards()` mock | Fallback path: `_parse_sub_sections()` returns `[]` | `sub_sections[0]["text"]` exists (not `"content"`) |
| UT-B1 | Token budget formula | `n_sections=10, profile=SLOW` | `adaptive_max_tokens == 16000` |
| UT-B2 | Token budget formula | `n_sections=3, profile=SLOW` | `adaptive_max_tokens == 8000` (floor) |
| UT-B3 | Token budget formula | `n_sections=5, profile=FAST/STRONG` | `adaptive_max_tokens == min(8000, max(4000, 5*900)) == 4500` |
| UT-B4 | Token budget formula | `n_sections=10, profile=NORMAL` | `adaptive_max_tokens == 12000` |
| UT-C1 | `_generate_cards_single()` | Called with `max_tokens=16000` | `_chat()` mock receives `max_tokens=16000` |
| UT-C2 | `_generate_cards_single()` | Called with no `max_tokens` (default) | `_chat()` mock receives `max_tokens=12000` |
| UT-D1 | `_build_card_profile_block()` | `profile.speed="SLOW"` | Output string contains "CARD DENSITY" and "2–3 cards" |
| UT-D2 | `_build_card_profile_block()` | `profile.speed="FAST", profile.comprehension="STRONG"` | Output string contains "CARD DENSITY" and "1–2 cards" |
| UT-D3 | `_build_card_profile_block()` | NORMAL profile | Output string does NOT contain "CARD DENSITY" |
| UT-E1 | `build_cards_user_prompt()` | 10 sections passed in | Output contains "COMPLETENESS REQUIREMENT" and all 10 section titles |
| UT-E2 | `build_cards_user_prompt()` | 1 section (fallback path) | Output contains "COMPLETENESS REQUIREMENT" and that 1 title |
| UT-F1 | `build_cards_system_prompt()` | Any call | Output contains "NON-NEGOTIABLE" adjacent to "COMPLETE COVERAGE" |

### Integration test

| Test ID | Scenario | Setup | Assertion |
|---------|----------|-------|-----------|
| INT-1 | Full `generate_cards()` with mocked LLM | Mock `_chat()` to return a valid 10-card JSON. Real `_parse_sub_sections()` and `_group_by_major_topic()` run. | `_chat()` mock receives `max_tokens >= 8000`; user prompt contains section checklist; system prompt contains density block. |
| INT-2 | Fallback key fix | Mock `_parse_sub_sections()` to return `[]`. Mock `_chat()` to return valid JSON. | No `KeyError`; cards returned successfully. |

### Regression tests

| Test ID | Scenario | Assertion |
|---------|----------|-----------|
| REG-1 | Existing test `test_generate_cards_returns_unified_schema` (if present) | Still passes with no schema changes |
| REG-2 | Any existing test calling `_generate_cards_single()` without `max_tokens` | Default value `12000` applied; test not broken |

---

## Key Decisions Requiring Stakeholder Input

1. **Token budget constants** — `CARDS_MAX_TOKENS_SLOW = 16_000` and associated floor/per-section values are proposed defaults. If the OpenAI account has per-request token limits set below 16,000 (e.g., organisational policy), these constants must be lowered. Confirm with the infrastructure team.

2. **NORMAL profile density** — Fix D deliberately omits a CARD DENSITY instruction for NORMAL profiles. If curriculum QA determines that NORMAL learners are also receiving too few or too many cards, a NORMAL density block (e.g., "1–2 cards per section") should be added in a follow-up.

3. **`_group_by_major_topic()` regex coverage** — The `_SUPPORT_HEADING` regex in the existing method was written for OpenStax Prealgebra. If other books (e.g., Calculus III) use different section heading conventions (e.g., "Proof:", "Remark:"), the regex may need extension. This is a known limitation and should be reviewed when the pipeline is run on additional books.
