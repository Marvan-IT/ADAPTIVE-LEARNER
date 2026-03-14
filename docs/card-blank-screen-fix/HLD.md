# HLD — Card Blank Screen Fix

**Feature slug:** `card-blank-screen-fix`
**Date:** 2026-03-09
**Author:** Solution Architect

---

## 1. Executive Summary

### Feature / System Name
Card Blank Screen Fix — four targeted defect corrections in the ADA adaptive learning frontend card flow.

### Business Problem Being Solved
When students navigate through lesson cards, a combination of four bugs causes the card learning screen to silently render a blank white area with no feedback, display corrupted progress numbers such as "(5/1)", or issue unnecessary backend API calls that conflict with the pre-generated card set. These failures break the learning loop and erode student trust in the product.

All four bugs are confined to the React frontend. The backend is not affected; all 428 backend tests pass.

### Key Stakeholders
- Students (end users experiencing the blank screen)
- Frontend Developer (implementer)
- Comprehensive Tester (verification)
- Product / Learning Experience team (acceptance)

### Scope

**In scope:**
- Bug 1: Replace `if (!card) return null` with a proper error/loading UI in `CardLearningView.jsx`
- Bug 2: Add upper-bound clamp to `NEXT_CARD` reducer in `SessionContext.jsx`
- Bug 3: Fix math underflow in `ADAPTIVE_CARD_ERROR` reducer in `SessionContext.jsx`
- Bug 4: Skip adaptive API call when pre-generated cards are still available in `goToNextCard()` in `SessionContext.jsx`
- Two new i18n keys (`generatingCards`, `noCardsError`) added to `frontend/src/locales/en.json` and all 12 other locale files
- One row added to the `CLAUDE.md` deployment fixes table

**Out of scope:**
- Backend changes (none required)
- New features or behavioral changes beyond the four stated bug fixes
- Changes to any other component not listed above
- Database migrations

---

## 2. Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | When `cards[currentCardIndex]` is undefined (cards array empty or index out of range) and the session is in CARDS phase, the component must render a visible loading or error state rather than a blank screen. | P0 |
| FR-2 | Dispatching `NEXT_CARD` must never set `currentCardIndex` to a value greater than `cards.length - 1`. | P0 |
| FR-3 | Dispatching `ADAPTIVE_CARD_ERROR` must never set `currentCardIndex` to `-1` (underflow when `cards` is empty). The index must not advance on error. | P0 |
| FR-4 | `goToNextCard()` must not call `completeCardAndGetNext()` when a pre-generated card exists at `currentCardIndex + 1`. The adaptive API is called only when the student has reached the last pre-generated card. | P0 |
| FR-5 | Two i18n keys (`learning.generatingCards` and `learning.noCardsError`) must be present in all 13 locale files. English values are provided; other locales may use English as a fallback until translation is complete. | P1 |

---

## 3. Non-Functional Requirements

| Category | Requirement |
|----------|-------------|
| Performance | No additional render cycles introduced. Clamp operations are O(1). |
| Correctness | `currentCardIndex` must always satisfy `0 <= index <= max(0, cards.length - 1)` after any reducer transition. |
| Reliability | Removing the redundant adaptive API call reduces network errors and backend load during normal pre-generated card navigation. |
| Observability | The `noCardsError` UI state must be visible and translatable; it must not silently fail. |
| Backwards compatibility | All changes are internal to reducer logic and one component guard. No API contract changes. |
| Test coverage | Each corrected reducer case must have a corresponding unit test asserting the new boundary behaviour. |

---

## 4. System Context Diagram

```
Student browser
  └── React SPA (frontend/)
        ├── CardLearningView.jsx          [Bug 1 fix — null guard replaced]
        │     reads: cards[], currentCardIndex, adaptiveCardLoading
        └── SessionContext.jsx             [Bug 2, 3, 4 fixes]
              ├── sessionReducer()
              │     ├── NEXT_CARD        [Bug 2 — clamp added]
              │     └── ADAPTIVE_CARD_ERROR [Bug 3 — underflow fixed]
              └── goToNextCard()          [Bug 4 — pre-gen card skip]
                    └── completeCardAndGetNext()  [backend API — called ONLY at last pre-gen card]

Backend (unchanged)
  └── POST /api/v2/sessions/{id}/complete-card  [called less frequently — only at boundary]
```

The fix reduces calls to the adaptive card endpoint from "every Next click" to "only when exhausting pre-generated cards." No new endpoints. No new services.

---

## 5. Architectural Style and Patterns

**Style:** Local defect correction within an existing React Context + Reducer architecture.

The codebase already uses React's `useReducer` pattern (`SessionContext.jsx`) with a discriminated-union action type. All four fixes follow the existing conventions:

- Reducer cases remain pure functions (no side effects, no async).
- `goToNextCard()` remains an async `useCallback` that dispatches to the reducer.
- Guard clauses in `CardLearningView.jsx` follow the existing early-return pattern already established for `adaptiveCardLoading`.

**Why not a more architectural fix?**
The bugs are isolated, low-risk, and do not signal a structural problem with the context/reducer design. Larger architectural changes (e.g., moving to Zustand for card state) are out of scope and would introduce unnecessary risk.

---

## 6. Technology Stack

All fixes use the existing stack. No new dependencies.

| Layer | Technology | Version |
|-------|-----------|---------|
| UI | React 19 | existing |
| State | React `useReducer` | existing |
| i18n | i18next 25 | existing |
| Icons / UI | Lucide React | existing |
| HTTP | Axios via `completeCardAndGetNext()` | existing |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-1: Replace `return null` with explicit error UI rather than a redirect

**Options considered:**
1. `return null` — status quo, renders blank screen.
2. Redirect to map page on null card — abrupt, loses lesson context, poor UX.
3. Render an explicit `noCardsError` message with a "Back to Map" CTA — clear, actionable, no data loss.

**Decision:** Option 3.

**Rationale:** Students deserve feedback. An empty UI is worse than an error message. Redirect loses session context. The error UI is consistent with the existing `adaptiveCardLoading` skeleton pattern directly above the null guard in the same file.

---

### ADR-2: Clamp `NEXT_CARD` to `cards.length - 1` rather than ignore the dispatch

**Options considered:**
1. Ignore the dispatch if already at last card.
2. Clamp index to `Math.min(next, Math.max(0, cards.length - 1))`.
3. Assert in development, silently clamp in production.

**Decision:** Option 2 (clamp, always).

**Rationale:** Option 1 suppresses the dispatch entirely, which may cause the UI flow (finish button visibility) to diverge if the caller relies on state having changed. Option 2 is idempotent and safe. `Math.max(0, cards.length - 1)` handles the empty-array edge case without a separate guard.

---

### ADR-3: Do NOT advance index on `ADAPTIVE_CARD_ERROR`

**Options considered:**
1. Keep existing behaviour: advance index (even on error).
2. Reset index to 0.
3. Keep current index, clamp only for safety.

**Decision:** Option 3.

**Rationale:** Advancing on error puts the student at an undefined card slot, producing a blank screen. Resetting to 0 is disorienting mid-lesson. Holding position is the safest UX: the student sees the same card they were on, can retry or request help.

---

### ADR-4: Pre-gen card check in `goToNextCard()` is a boundary guard, not a mode switch

**Options considered:**
1. Remove `completeCardAndGetNext()` entirely (no adaptive extension).
2. Add a boolean `adaptiveMode` flag to `SessionContext` state.
3. Inline check: `currentCardIndex < cards.length - 1` → skip API, dispatch `NEXT_CARD` directly.

**Decision:** Option 3.

**Rationale:** Option 1 removes a planned feature. Option 2 adds unnecessary state complexity. Option 3 is the minimal correct fix: the pre-generated cards are already in `state.cards`; the adaptive API is an extension mechanism for when they are exhausted. The inline boundary check makes this intent explicit without new abstractions.

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| `noCardsError` UI is shown transiently during a LOADING phase race condition | Low | Low | Guard is placed after the `adaptiveCardLoading` early return, which is already in place. The `LOADING` phase renders a different UI upstream in `LearningPage.jsx`. |
| Clamp in `NEXT_CARD` masks a caller bug where `goToNextCard` is invoked past the last card | Low | Medium | The Bug 4 fix in `goToNextCard()` ensures the caller never dispatches `NEXT_CARD` past the pre-gen boundary; adaptive extension uses `ADAPTIVE_CARD_LOADED` instead, which appends to `cards[]` before advancing. |
| i18n keys missing in non-English locales | High (translation lag) | Low | Fallback to `en.json` values via i18next `fallbackLng` already configured. Locales get English text until translators update them. |
| `goToNextCard` refactor breaks remediation card flow | Low | High | Remediation cards are loaded via `REMEDIATION_CARDS_LOADED` which resets `currentCardIndex` to 0. The `goToNextCard` boundary check uses `cards.length - 1` which is always correct after remediation load. Covered by integration test. |

---

## Key Decisions Requiring Stakeholder Input

1. **Error UI copy:** The `noCardsError` string "No cards could be loaded for this lesson. Please go back and try again." is a draft. The learning experience team should confirm the student-friendly wording before the translation round.

2. **Error UI action:** Should the "Back to Map" button in the `noCardsError` state call `reset()` before navigating, or rely on the existing map-page load to re-initialize state? The design assumes `reset()` is called.

3. **Adaptive extension boundary:** Bug 4 fix assumes the adaptive API is ONLY called when the student reaches the last pre-generated card. Confirm this is the intended product behaviour with the product owner. If adaptive cards should interleave with pre-generated cards in the future, this fix will need revisiting.
