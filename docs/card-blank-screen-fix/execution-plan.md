# Execution Plan — Card Blank Screen Fix

**Feature slug:** `card-blank-screen-fix`
**Date:** 2026-03-09
**Author:** Solution Architect

---

## 1. Work Breakdown Structure (WBS)

| ID | Title | Description | Effort (days) | Dependencies | Component |
|----|-------|-------------|--------------|--------------|-----------|
| T-1 | Fix `NEXT_CARD` reducer clamp | Replace unbounded `currentCardIndex + 1` with `Math.min(idx + 1, Math.max(0, cards.length - 1))` in `NEXT_CARD` case | 0.25 | — | `SessionContext.jsx` |
| T-2 | Fix `ADAPTIVE_CARD_ERROR` underflow | Replace advancing index-on-error with hold-in-place clamp; guard for empty cards array | 0.25 | — | `SessionContext.jsx` |
| T-3 | Fix `goToNextCard` pre-gen boundary | Insert `currentCardIndex < cards.length - 1` guard to skip adaptive API when pre-gen card is available; add `currentCardIndex` to `useCallback` deps | 0.5 | — | `SessionContext.jsx` |
| T-4 | Replace null guard with error UI | Replace `if (!card) return null` with the `noCardsError` component; wire `reset()` + `navigate("/map")` button | 0.5 | T-6 | `CardLearningView.jsx` |
| T-5 | Verify `reset` and `navigate` imports | Confirm `reset` is in the `useSession()` destructure and `useNavigate` is imported or add them | 0.1 | — | `CardLearningView.jsx` |
| T-6 | Add `generatingCards` and `noCardsError` to `en.json` | Insert two new i18n keys with English copy after `learning.generatingCard` | 0.1 | — | `frontend/src/locales/en.json` |
| T-7 | Add i18n keys to all 12 other locales | Copy English values as placeholders into `ar.json`, `de.json`, `es.json`, `fr.json`, `hi.json`, `ja.json`, `ko.json`, `ml.json`, `pt.json`, `si.json`, `ta.json`, `zh.json` | 0.25 | T-6 | `frontend/src/locales/` |
| T-8 | Unit tests — reducer cases | Write pure-function unit tests for all 6 reducer test cases (UT-1 through UT-6 per DLD §9) | 0.5 | T-1, T-2 | `backend/tests/` or `frontend/src/__tests__/` |
| T-9 | Unit tests — `goToNextCard` callback | Write mocked unit tests for UT-7, UT-8, UT-9 (API call guard, ceiling, adaptive path) | 0.5 | T-3 | `frontend/src/__tests__/` |
| T-10 | Component test — null guard UI | Write React Testing Library tests for CT-1, CT-2, CT-3 | 0.25 | T-4 | `frontend/src/__tests__/` |
| T-11 | i18n completeness test | Assert all 13 locale files contain both new keys | 0.1 | T-7 | `frontend/src/__tests__/` |
| T-12 | Integration test — end-to-end card flow | Verify adaptive API called exactly once at last pre-gen card; error path holds index; remediation resets correctly (INT-1, INT-2, INT-3) | 0.5 | T-1, T-2, T-3 | `frontend/src/__tests__/` |
| T-13 | Manual smoke test on dev server | Run frontend dev server, navigate a 3-card lesson, verify progress display, no blank screens, adaptive API call count | 0.25 | T-1 through T-7 | Local dev |
| T-14 | Update `CLAUDE.md` fixes table | Add 2026-03-09 row to the "Completed Security and Stability Fixes" table listing all four bug fixes | 0.1 | T-1 through T-7 | `CLAUDE.md` |

**Total estimated effort: ~3.6 engineer-days**

---

## 2. Phased Delivery Plan

### Phase 1 — Foundation: i18n and imports (Day 1 morning)
Tasks: T-5, T-6, T-7

These are zero-risk setup tasks with no logic. Complete them first so that T-4 can reference the new i18n keys without missing-key warnings during development.

Acceptance: `npm run dev` starts; no i18next missing-key warnings for `learning.noCardsError` or `learning.generatingCards`.

---

### Phase 2 — Core Fixes: Reducer and callback corrections (Day 1)
Tasks: T-1, T-2, T-3

These are the three logic fixes in `SessionContext.jsx`. They are independent of each other and can be made in one commit.

Acceptance:
- `sessionReducer` exported and callable as a pure function from a test harness.
- `NEXT_CARD` with `cards = [c0, c1]` and `currentCardIndex = 1` returns `currentCardIndex = 1` (clamped).
- `ADAPTIVE_CARD_ERROR` with `cards = []` returns `currentCardIndex = 0`.
- `ADAPTIVE_CARD_ERROR` with `cards = [c0]` and `currentCardIndex = 0` returns `currentCardIndex = 0` (held).

---

### Phase 3 — Core Fix: Null guard UI (Day 1 afternoon)
Tasks: T-4

Depends on Phase 1 (i18n keys) and T-5 (imports).

Acceptance:
- Rendering `CardLearningView` with `cards = []` and `adaptiveCardLoading = false` shows `learning.noCardsError` text and a "Back to Map" button.
- No blank white area visible.
- Clicking "Back to Map" invokes `reset()` and navigates to `/map`.

---

### Phase 4 — Hardening: Tests (Day 2)
Tasks: T-8, T-9, T-10, T-11, T-12

Write all automated tests per DLD §9.

Acceptance: All tests pass. Zero regressions in existing test suite.

---

### Phase 5 — Release: Smoke test and documentation (Day 2 afternoon)
Tasks: T-13, T-14

Manual end-to-end verification on local dev server. Update `CLAUDE.md`.

Acceptance: Dev server smoke test passes. `CLAUDE.md` table updated.

---

## 3. Dependencies and Critical Path

```
T-6 (en.json)
  └── T-7 (other locales)
        └── T-4 (null guard UI — needs noCardsError key)
              └── T-10 (component test)

T-5 (imports check)
  └── T-4 (null guard UI)

T-1 (NEXT_CARD clamp)
  ├── T-8 (reducer unit tests)
  └── T-12 (integration test)

T-2 (ADAPTIVE_CARD_ERROR fix)
  ├── T-8 (reducer unit tests)
  └── T-12 (integration test)

T-3 (goToNextCard boundary)
  ├── T-9 (callback unit tests)
  └── T-12 (integration test)

[T-1 + T-2 + T-3 + T-4 + T-5 + T-6 + T-7] → T-13 (smoke test)
T-13 → T-14 (CLAUDE.md update)
```

**Critical path:** T-6 → T-7 → T-4 → T-13 → T-14 (longest dependency chain)

**Blocking dependencies on external teams:** None. All changes are frontend-only. Backend team sign-off is not required; backend is unchanged.

**Parallel opportunities:**
- T-1, T-2, T-3 are independent of each other and can be committed in a single pass.
- T-8 and T-9 can be written in parallel with T-10 once their respective source fixes are in place.

---

## 4. Definition of Done (DoD)

### Phase 1 DoD
- [ ] `en.json` contains `learning.generatingCards` and `learning.noCardsError` keys
- [ ] All 12 other locale files contain both keys (English placeholder values acceptable)
- [ ] `npm run dev` starts without i18next missing-key console warnings for these keys

### Phase 2 DoD
- [ ] `NEXT_CARD` reducer: `currentCardIndex` never exceeds `cards.length - 1`
- [ ] `NEXT_CARD` reducer: empty `cards` array → `currentCardIndex` = 0
- [ ] `ADAPTIVE_CARD_ERROR` reducer: `currentCardIndex` unchanged (held in place)
- [ ] `ADAPTIVE_CARD_ERROR` reducer: empty `cards` array → `currentCardIndex` = 0 (no underflow)
- [ ] `goToNextCard`: `completeCardAndGetNext` NOT called when `currentCardIndex < cards.length - 1`
- [ ] `goToNextCard`: `state.currentCardIndex` added to `useCallback` dependency array
- [ ] No TypeScript / ESLint errors introduced

### Phase 3 DoD
- [ ] `CardLearningView` renders `learning.noCardsError` message when `cards = []` and not loading
- [ ] Error UI includes a "Back to Map" button that calls `reset()` and navigates to `/map`
- [ ] `AssistantPanel` still renders in the error state layout (or explicitly excluded — confirm with UX)
- [ ] No `return null` remains in the component for the null card case

### Phase 4 DoD
- [ ] UT-1 through UT-6 pass (reducer unit tests)
- [ ] UT-7 through UT-9 pass (goToNextCard unit tests)
- [ ] CT-1 through CT-3 pass (component tests)
- [ ] IT-1 and IT-2 pass (i18n completeness)
- [ ] INT-1 through INT-3 pass (integration tests)
- [ ] No pre-existing tests broken

### Phase 5 DoD
- [ ] Manual smoke test: 3-card lesson navigated without blank screen
- [ ] Manual smoke test: progress counter reads "Card 1", "Card 2", "Card 3" — no "(5/1)" corruption
- [ ] Manual smoke test: network tab shows `complete-card` called once (on click from card 3), not on clicks from card 1 or 2
- [ ] `CLAUDE.md` "Completed Security and Stability Fixes" table updated with 4 new rows (one per bug)

---

## 5. Rollout Strategy

### Deployment approach
This is a pure frontend fix. No backend deployment, no migration, no feature flag.

The fix ships as a standard frontend build update: `npm run build` → static assets deployed.

**No feature flag required.** The bugs are unconditionally harmful; the fixes are unconditionally correct. A feature flag would add complexity with no benefit.

### Rollback plan
The fix is in three files and fourteen lines of code. If a regression is discovered post-deployment:

1. Revert the single commit containing all frontend changes (`git revert <commit-hash>`).
2. Redeploy the previous build artifact.
3. The pre-fix blank screen bug returns, but no data loss occurs (session state is in-memory only).

### Monitoring and alerting for launch
- Watch PostHog for `lesson_error` event frequency in the 24 hours post-deploy. A spike indicates the null guard is being hit at unexpected frequency.
- Watch for a drop in `adaptive_card_loaded` events per session (expected: should decrease from "fired on every Next" to "fired once at session end"). This confirms Bug 4 fix is live.

### Post-launch validation steps
1. Confirm `adaptive_card_loaded` events: count per session should now equal 1 (not N where N = number of pre-gen cards).
2. Confirm `lesson_error` event rate is stable or decreasing.
3. QA team runs the manual smoke test from Phase 5 DoD on the production environment.
4. Confirm no blank screen reports in user feedback channels for 48 hours post-deploy.

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| 1 — Foundation | T-5, T-6, T-7 (i18n + imports) | 0.45 days | 1 frontend developer |
| 2 — Core Fixes (Context) | T-1, T-2, T-3 (reducer + callback) | 1.0 days | 1 frontend developer |
| 3 — Core Fix (Component) | T-4 (null guard UI) | 0.5 days | 1 frontend developer |
| 4 — Hardening | T-8 through T-12 (all tests) | 1.35 days | 1 frontend developer + 1 tester |
| 5 — Release | T-13, T-14 (smoke test + docs) | 0.35 days | 1 frontend developer |
| **Total** | **14 tasks** | **~3.6 engineer-days** | **1 frontend developer, 1 tester** |

With one frontend developer and one tester working in parallel on phases 4 and 5, calendar time is approximately **1.5–2 days**.

---

## Key Decisions Requiring Stakeholder Input

1. **`AssistantPanel` in error state:** The DLD specifies `AssistantPanel` is rendered alongside the error message (matching the skeleton layout). Confirm with UX whether this is desired or whether the panel should be hidden when there is no active card to assist with.

2. **Error message copy:** The `noCardsError` English string is a technical placeholder. The learning experience or copy team should provide student-friendly wording before the translation round is triggered.

3. **PostHog validation threshold:** What delta in `adaptive_card_loaded` events per session constitutes a rollback trigger? The analytics team should set a specific numeric threshold (e.g., if median events per session does not drop by at least 50% within 24 hours, investigate).
