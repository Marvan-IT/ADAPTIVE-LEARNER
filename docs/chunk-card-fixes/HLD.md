# HLD — Chunk Card Fixes

**Feature slug:** `chunk-card-fixes`
**Date:** 2026-03-28
**Author:** solution-architect

---

## 1. Executive Summary

### Feature name and purpose
Chunk Card Fixes corrects 7 confirmed defects in the chunk-based card generation flow introduced by the chunk architecture. Together these defects cause blank screens on chunk transitions, LLM-generated content that does not come from the textbook, mode adaptation that never activates, recovery cards that use the wrong API endpoint, exercise chunks that produce generic rather than targeted quiz cards, missing i18n translations that display raw key strings, and a combined-card contract that the LLM ignores.

### Business problem being solved
Real students navigating the chunk teaching flow encounter a blank screen when advancing to a new section (Bug 1), receive generic AI-invented math rather than the actual textbook lesson (Bug 2/3), never experience adaptive difficulty changes no matter how well or poorly they perform (Bugs 3/4), get stuck on a single MCQ with no recovery path (Bug 5), see raw i18n key strings instead of localised error messages (Bug 6), and encounter exercise sections that behave identically to teaching sections (Bug 8). These defects make the chunk teaching flow non-functional for actual classroom use.

### Key stakeholders
- Students: directly affected by all 7 defects
- Backend developer: owns `teaching_service.py` and `prompt_builder.py`
- Frontend developer: owns `SessionContext.jsx` and all 13 locale files
- Comprehensive tester: owns 4 new regression tests for the backend fixes

### Scope

**Included:**
- Fix 1: raise `ValueError` on empty card output from `generate_per_chunk`
- Fix 2: rewrite chunk card system prompt (source constraint, merge rules, combined cards, mode delivery injection)
- Fix 3: wire `build_blended_analytics` call and persist mode to session cache inside `generate_per_chunk`
- Fix 4: rewrite `goToNextChunk` as async with on-demand fallback; guard `CHUNK_ADVANCE` reducer
- Fix 5: change recovery card trigger from `wrongAttempts >= 2` to `wrongAttempts >= 1`; switch endpoint from `/complete-card` to `/chunk-recovery-card`; add local RECAP card on second failure
- Fix 6: add `learning.noCardsError` key to all 13 locale files
- Fix 8: detect exercise chunks by heading pattern; generate 2 MCQ cards per preceding teaching subsection using a dedicated exercise system prompt
- Two additive improvements to `_CARD_MODE_DELIVERY` blocks in `prompt_builder.py`: per-mode MCQ explanation length and style/interests integration instruction

**Excluded:**
- No database schema changes — all fixes are in service layer, prompt strings, and frontend logic
- No new API endpoints — `/chunk-recovery-card` and `/chunk-cards` already exist
- No changes to exam flow, spaced review, or the old per-card adaptive path
- No changes to ChromaDB, NetworkX, or the extraction pipeline
- `completeSection` and `regenerateMCQ` imports in `sessions.js` are intentionally left untouched

---

## 2. Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | Advancing to the next chunk never displays a blank "Could not load cards" screen | P0 |
| FR-2 | Every card's content is extracted exclusively from the textbook chunk text; LLM may not invent definitions, examples, or formulas | P0 |
| FR-3 | Every card contains both a content explanation AND an MCQ question in a single card object | P0 |
| FR-4 | Mode (STRUGGLING / NORMAL / FAST) is computed from live student history before each chunk and written back to session cache | P1 |
| FR-5 | Mode-delivery rules (`_CARD_MODE_DELIVERY` blocks) are injected into the chunk card system prompt | P1 |
| FR-6 | First MCQ failure on a chunk card triggers a recovery card via the `/chunk-recovery-card` endpoint | P1 |
| FR-7 | Second MCQ failure triggers a locally-generated RECAP card and automatic advance to the next chunk | P1 |
| FR-8 | Exercise chunks ("Section Exercises", "Let's Practice") generate exactly 2 MCQ cards per preceding teaching subsection | P1 |
| FR-9 | `learning.noCardsError` renders a localised string in all 13 supported languages | P2 |
| FR-10 | MCQ wrong-answer explanation length adapts per mode: full walkthrough (STRUGGLING), 2–3 sentences (NORMAL), one-line (FAST) | P2 |

---

## 3. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Latency — chunk card generation | p95 ≤ 12 s for NORMAL mode (unchanged from current; token budget is the binding constraint) |
| Latency — `goToNextChunk` happy path | < 50 ms (pre-fetched cards already in state; reducer-only operation) |
| Latency — `goToNextChunk` fallback path | p95 ≤ 12 s (on-demand LLM fetch; matches chunk generation latency) |
| Correctness | 100 % of chunks with valid LLM output produce ≥ 1 card; 0 % silent empty responses |
| Mode adaptation | Mode correct for ≥ 95 % of chunk requests after at least 3 prior card interactions exist |
| i18n coverage | `learning.noCardsError` present and non-empty in all 13 locale files |
| Backward compatibility | No regressions to exam flow, per-card adaptive path, or old Socratic teaching loop |
| Restart required | None — `uvicorn --reload` and Vite HMR handle all file changes automatically |

---

## 4. System Context

```
Student browser
    │
    │ HTTPS / Axios
    ▼
React SPA (SessionContext.jsx)
    │  goToNextCard ──────────────────────────────────────────────┐
    │  goToNextChunk (Fix 4: async + fallback)                    │
    │                                                             │
    │  CHUNK_ADVANCE reducer (Fix 4: safety guard)                │
    │  Recovery threshold change (Fix 5)                          │
    │  RECAP card local generation (Fix 5)                        │
    │                                                             ▼
FastAPI teaching_router.py
    │  POST /api/v2/sessions/{id}/chunk-cards
    │  POST /api/v2/sessions/{id}/chunk-recovery-card
    ▼
TeachingService.generate_per_chunk()
    │  Fix 3: build_blended_analytics() → _generate_as → write to session cache
    │  Fix 2: new system prompt (source rule + merge rules + combined cards + mode delivery)
    │  Fix 1: raise ValueError on empty cards list
    │  Fix 8: exercise chunk detection → dedicated exercise system prompt
    ▼
OpenAI API (gpt-4o-mini)
    │
    ▼
_normalise_per_card() → List[LessonCard]

prompt_builder.py (Fix 2B additions)
    ├── _CARD_MODE_DELIVERY["STRUGGLING"] — adds MCQ explanation length + style/interests rule
    ├── _CARD_MODE_DELIVERY["NORMAL"]     — adds MCQ explanation length + style/interests rule
    └── _CARD_MODE_DELIVERY["FAST"]       — adds MCQ explanation length + style/interests rule

Locale files (Fix 6)
    └── learning.noCardsError → 13 translations
```

---

## 5. How the Fixes Interact

The fixes form two dependency chains:

**Chain A — empty-card pipeline:**
Fix 1 (raise on empty) → router's `except Exception` handler returns HTTP 500 → frontend pre-fetch `.catch()` stores error flag in state → Fix 4's `goToNextChunk` fallback branch detects null/empty `nextChunkCards` and performs an on-demand re-fetch with user-visible error if that also fails.

Without Fix 1, the router returns HTTP 200 with `cards: []` and Fix 4 has no error signal to act on. Fix 4 alone (null guard) would silently do nothing.

**Chain B — mode and prompt quality:**
Fix 3 (wire `build_blended_analytics`) computes the correct `_generate_as` value from live student history. Fix 2 consumes that value by injecting `_CARD_MODE_DELIVERY[_generate_as]` into the system prompt. The additions to `_CARD_MODE_DELIVERY` blocks (Fix 2B) ensure the injected block contains MCQ explanation length rules and style/interests integration.

Without Fix 3, `_generate_as` is always "NORMAL" (read from empty session cache), so Fix 2's mode injection always produces the NORMAL block regardless of actual student performance.

**Fix 5 dependencies:**
Fix 5 changes the recovery trigger threshold and endpoint. It depends on `generateChunkRecoveryCard` already being defined in `sessions.js` (confirmed: line 131) and the `/chunk-recovery-card` endpoint being live in `teaching_router.py` (confirmed: line 894). No new backend code is needed for Fix 5 beyond the frontend change.

**Fix 8 independence:**
Fix 8 is self-contained within `generate_per_chunk`. It adds exercise detection before the system prompt is built, and branches into a completely separate prompt path. It does not interact with Fixes 1–5.

**Fix 6 independence:**
Fix 6 is purely additive — adding missing i18n keys to locale JSON files. No logic changes.

---

## 6. Architectural Style and Patterns

This is a pure **bug-fix release** — no new architectural patterns are introduced. All changes follow the established conventions:

- **System prompt as configuration:** Mode delivery rules live in `_CARD_MODE_DELIVERY` dict in `prompt_builder.py` (established pattern from `build_adaptive_prompt` and `build_next_card_prompt`). Fix 2 extends this pattern to the chunk card path, which previously bypassed it.
- **Session cache as lightweight state:** `session.presentation_text` is used as a JSON dict cache for current mode and other session state (established pattern). Fix 3 writes `current_mode` using this same mechanism.
- **Raise-don't-swallow errors:** The existing router has a broad `except Exception` handler that converts exceptions to HTTP 500 responses. Fix 1 relies on this — raising `ValueError` is the correct signal mechanism.
- **On-demand fallback:** Fix 4 follows the same pattern used by `goToNextCard` (which has its own fallback logic when adaptive cards fail): try the optimistic path, fall back with a user-visible error on failure.
- **Local card generation (RECAP):** Fix 5's RECAP card is assembled from the failed MCQ's `explanation` field without an LLM call, matching the template-based remediation pattern used in `remediation.py`.

---

## 7. Technology Stack

All changes are within the existing stack. No new dependencies are introduced.

| Layer | Technology | Change |
|-------|------------|--------|
| Backend service | Python / FastAPI / `teaching_service.py` | Fixes 1, 2, 3, 8 |
| Backend prompts | `adaptive/prompt_builder.py` | Fix 2B additions to `_CARD_MODE_DELIVERY` |
| Frontend state | React 19 / `SessionContext.jsx` | Fix 4, Fix 5 |
| Frontend i18n | i18next / `locales/*.json` (13 files) | Fix 6 |

---

## 8. Key Architectural Decisions (ADRs)

### ADR-1: Raise ValueError on empty cards rather than returning []
**Options:** (a) Return empty list and let router send HTTP 200 `cards: []`. (b) Raise `ValueError` to trigger HTTP 500.
**Chosen:** (b) Raise.
**Rationale:** HTTP 200 with `cards: []` is indistinguishable from a legitimately empty chunk. The router's existing `except Exception` handler already converts exceptions to structured HTTP 500 responses. Frontend can detect 500 and handle it explicitly; it cannot distinguish HTTP 200 `cards: []` from a successful but empty response.

### ADR-2: Inject _CARD_MODE_DELIVERY into system prompt, not user prompt
**Options:** (a) Append mode block to user prompt. (b) Embed in system prompt.
**Chosen:** (b) System prompt.
**Rationale:** LLMs treat system prompt rules as higher-priority instructions than user prompt content. Mode delivery rules are behavioural constraints (not input data), so they belong in the system prompt. This matches the pattern used by `build_adaptive_prompt` and `build_next_card_prompt`.

### ADR-3: Write updated mode to session.presentation_text before the db commit in the router
**Options:** (a) Write mode update in `generate_per_chunk` and let the router commit. (b) Return mode from function and write in router.
**Chosen:** (a) Write in `generate_per_chunk`.
**Rationale:** The router already owns the db commit after the service call. Writing to `session.presentation_text` in the service function means the mutation is co-located with the mode computation, reducing the risk of the router forgetting to write it.

### ADR-4: RECAP card generated locally on frontend rather than via LLM
**Options:** (a) New backend endpoint returns RECAP card. (b) Frontend assembles RECAP from failed card's `explanation` field.
**Chosen:** (b) Local generation.
**Rationale:** The failed MCQ's `explanation` field already contains the correct answer explanation written by the LLM at card generation time. Reusing it for the RECAP avoids an extra LLM round-trip, reduces latency, and requires no new backend endpoint. This matches the template-based remediation pattern.

### ADR-5: Exercise chunk system prompt is separate, not a conditional block in the existing prompt
**Options:** (a) Add `if is_exercise` blocks inside the existing system prompt string. (b) Build a completely separate system prompt for exercise chunks.
**Chosen:** (b) Separate prompt.
**Rationale:** Exercise chunks have fundamentally different output requirements (MCQ-only, fixed count = 2 × subsection count, real textbook difficulty regardless of mode). Mixing these rules into the teaching prompt creates a prompt that is difficult to maintain and increases the risk of the LLM misapplying rules. A clean branch in `generate_per_chunk` makes the two paths independently testable.

---

## 9. Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `build_blended_analytics` raises an exception for a student with no prior card history, blocking chunk generation | Medium | Wrap call in try/except; fall back to "NORMAL" mode on failure; log a warning |
| Exercise chunk heading detection misclassifies a teaching chunk with "practice" in its title | Low | Pattern-match list is conservative: `("exercises", "practice test", "review exercises")`; individual "practice problem" wording within a teaching chunk heading will not match |
| `session.presentation_text` write in `generate_per_chunk` is not committed because router errors out | Low | Router commits after the service call returns; if the service raises, the session cache write is not committed — acceptable: mode reverts to NORMAL on next chunk, no data corruption |
| On-demand fallback in `goToNextChunk` fires while a pre-fetch is already in flight | Low | `state.nextChunkInFlight` guard prevents double-dispatch; `generateChunkCards` in fallback path uses the same idempotent endpoint |
| 13 locale translations contain errors (auto-translated) | Low | Translations are provided verbatim in the approved plan; backend developer / reviewer should flag any obvious errors during code review |

---

## Key Decisions Requiring Stakeholder Input

1. **Exercise chunk heading patterns** — the detection list `("exercises", "practice test", "review exercises")` was derived from prealgebra chapter headings. If other books use different exercise section naming conventions, patterns need expanding before Fix 8 is deployed.
2. **RECAP card advance behaviour** — Fix 5 specifies that after a RECAP card the student advances to the next chunk automatically on clicking Next. Confirm this is the desired UX — an alternative is to require the student to click an explicit "Move On" button.
3. **Mode adaptation cold-start** — Fix 3 calls `build_blended_analytics` for every chunk. For a brand-new student with zero card interactions, the function may return NORMAL regardless of session-level signals. Confirm that NORMAL as the cold-start mode is acceptable, or whether a different default is preferred.
