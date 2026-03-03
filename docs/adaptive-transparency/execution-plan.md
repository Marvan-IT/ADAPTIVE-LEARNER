# Execution Plan: Adaptive Transparency

**Feature slug:** `adaptive-transparency`
**Date:** 2026-02-28
**Author:** Solution Architect
**Status:** Draft — pending stakeholder review

---

## 1. Work Breakdown Structure (WBS)

### Phase 1 — Design (this document)

| Task ID | Title | Description | Effort | Dependencies | Component |
|---------|-------|-------------|--------|-------------|-----------|
| P1-1 | HLD authored | High-Level Design written to disk | 0.5d | — | `docs/adaptive-transparency/HLD.md` |
| P1-2 | DLD authored | Detailed Low-Level Design written to disk | 1d | P1-1 | `docs/adaptive-transparency/DLD.md` |
| P1-3 | Execution plan authored | This document | 0.5d | P1-2 | `docs/adaptive-transparency/execution-plan.md` |

**Phase 1 status: COMPLETE**

---

### Phase 2 — Backend Changes

| Task ID | Title | Description | Effort | Dependencies | Component |
|---------|-------|-------------|--------|-------------|-----------|
| P2-1 | Add config constants | Add `WRONG_OPTION_PATTERN_THRESHOLD`, `CARD_HISTORY_DEFAULT_LIMIT`, `CARD_HISTORY_MAX_LIMIT` to `backend/src/config.py` | 0.25d | P1-3 | `config.py` |
| P2-2 | Extend `CardBehaviorSignals` | Add `difficulty_bias: Literal["TOO_EASY", "TOO_HARD"] | None = None` to `CardBehaviorSignals` in `backend/src/adaptive/schemas.py` | 0.25d | P1-3 | `adaptive/schemas.py` |
| P2-3 | Add `CardInteractionRecord` and `CardHistoryResponse` schemas | Add two new Pydantic models to `backend/src/api/teaching_schemas.py` per DLD §2.2 | 0.25d | P1-3 | `api/teaching_schemas.py` |
| P2-4 | Implement `load_wrong_option_pattern()` | New async function in `adaptive_engine.py` per DLD §5.1.1 | 0.5d | P2-1, P2-2 | `adaptive/adaptive_engine.py` |
| P2-5 | Modify `generate_next_card()` | Add `db` param, call `load_wrong_option_pattern()`, apply difficulty bias override, forward `difficulty` field, update return tuple to 5 elements per DLD §5.1.2 | 1d | P2-4 | `adaptive/adaptive_engine.py` |
| P2-6 | Modify `build_next_card_prompt()` | Accept `wrong_option_pattern` and `difficulty_bias` params; inject MISCONCEPTION PATTERN and DIFFICULTY ADJUSTMENT blocks per DLD §5.2 | 0.5d | P2-5 | `adaptive/prompt_builder.py` |
| P2-7 | Update adaptive router — unpack 5-tuple | Find all call sites of `generate_next_card()` in `adaptive_router.py`; unpack 5 return values; pass `db` argument; include `adaptation_applied` label in response | 0.5d | P2-5 | `adaptive/adaptive_router.py` |
| P2-8 | Implement `GET /api/v2/students/{id}/card-history` | New endpoint in `teaching_router.py` per DLD §3.1; uses `CardHistoryResponse`; enforces `CARD_HISTORY_MAX_LIMIT` | 0.5d | P2-1, P2-3 | `api/teaching_router.py` |
| P2-9 | Import `CARD_HISTORY_MAX_LIMIT` in router | Add import of new config constants to `teaching_router.py`; import `CardHistoryResponse`, `CardInteractionRecord` from `teaching_schemas` | 0.1d | P2-1, P2-3, P2-8 | `api/teaching_router.py` |

**Phase 2 total estimated effort: 3.85 days**

**Critical path in Phase 2:** P2-1 → P2-2 → P2-4 → P2-5 → P2-6 → P2-7

---

### Phase 3 — Tests

| Task ID | Title | Description | Effort | Dependencies | Component |
|---------|-------|-------------|--------|-------------|-----------|
| P3-1 | Unit test: `CardBehaviorSignals` bias field | Validate `difficulty_bias` accepts `"TOO_EASY"`, `"TOO_HARD"`, `null`; rejects invalid values | 0.25d | P2-2 | `tests/test_adaptive_schemas.py` |
| P3-2 | Unit test: `load_wrong_option_pattern()` — below threshold | Seed 2 rows for option 1; assert returns `None` | 0.25d | P2-4 | `tests/test_adaptive_engine.py` |
| P3-3 | Unit test: `load_wrong_option_pattern()` — at threshold | Seed 3 rows for option 2; assert returns `2` | 0.25d | P2-4 | `tests/test_adaptive_engine.py` |
| P3-4 | Unit test: `load_wrong_option_pattern()` — multiple options | Seed option 1 ×2, option 3 ×4; assert returns `3` (most frequent above threshold) | 0.25d | P2-4 | `tests/test_adaptive_engine.py` |
| P3-5 | Unit test: bias override in `generate_next_card()` — TOO_EASY | Mock `_call_llm`; assert `build_next_card_prompt` called with profile having `recommended_next_step="CHALLENGE"` | 0.5d | P2-5 | `tests/test_adaptive_engine.py` |
| P3-6 | Unit test: bias override in `generate_next_card()` — TOO_HARD | Mock `_call_llm`; assert profile has `recommended_next_step="REMEDIATE_PREREQ"` | 0.5d | P2-5 | `tests/test_adaptive_engine.py` |
| P3-7 | Unit test: `build_next_card_prompt()` — misconception block present | Call with `wrong_option_pattern=1`; assert user prompt contains "MISCONCEPTION PATTERN" and "option B" | 0.25d | P2-6 | `tests/test_prompt_builder.py` |
| P3-8 | Unit test: `build_next_card_prompt()` — misconception block absent | Call with `wrong_option_pattern=None`; assert user prompt does NOT contain "MISCONCEPTION PATTERN" | 0.25d | P2-6 | `tests/test_prompt_builder.py` |
| P3-9 | Unit test: `build_next_card_prompt()` — difficulty block TOO_EASY | Call with `difficulty_bias="TOO_EASY"`; assert prompt contains "DIFFICULTY ADJUSTMENT" | 0.25d | P2-6 | `tests/test_prompt_builder.py` |
| P3-10 | Unit test: `build_next_card_prompt()` — difficulty block TOO_HARD | Call with `difficulty_bias="TOO_HARD"`; assert prompt contains "too hard" | 0.25d | P2-6 | `tests/test_prompt_builder.py` |
| P3-11 | Unit test: `difficulty` forwarded in card dict | Mock LLM returns `{"difficulty": 4, ...}`; assert returned card dict has `"difficulty": 4` | 0.25d | P2-5 | `tests/test_adaptive_engine.py` |
| P3-12 | Integration test: `GET /card-history` — happy path | Seed 5 `CardInteraction` rows; assert 200 + `total_returned: 5` + correct fields | 0.5d | P2-8 | `tests/integration/test_teaching_router.py` |
| P3-13 | Integration test: `GET /card-history` — student isolation | Seed rows for student A and student B; query student A; assert student B rows absent | 0.5d | P2-8 | `tests/integration/test_teaching_router.py` |
| P3-14 | Integration test: `GET /card-history?limit=2` | Seed 5 rows; query with `limit=2`; assert `total_returned: 2` | 0.25d | P2-8 | `tests/integration/test_teaching_router.py` |
| P3-15 | Integration test: `GET /card-history` — empty result | New student with no interactions; assert `total_returned: 0, interactions: []` | 0.25d | P2-8 | `tests/integration/test_teaching_router.py` |
| P3-16 | Integration test: `GET /card-history` — 404 unknown student | Unknown UUID; assert 404 | 0.25d | P2-8 | `tests/integration/test_teaching_router.py` |
| P3-17 | Integration test: `complete-card` accepts `difficulty_bias` | POST with `difficulty_bias="TOO_HARD"` (mock LLM); assert 200 | 0.5d | P2-7 | `tests/integration/test_adaptive_router.py` |
| P3-18 | Integration test: `complete-card` bias null by default | POST without `difficulty_bias`; assert 200 | 0.25d | P2-7 | `tests/integration/test_adaptive_router.py` |

**Phase 3 total estimated effort: 5.5 days**

**Note:** Phase 3 can begin as soon as individual Phase 2 tasks are complete (task-level parallelism is possible). The comprehensive-tester should begin with unit tests (P3-1 through P3-11) while integration tests await Phase 2 completion.

---

### Phase 4 — Frontend Group A (Premium Redesign)

This phase is fully specified in `docs/risk-hardening-redesign/DLD.md §9.1–§9.8`. Task decomposition below is a summary for scheduling purposes; the frontend-developer must use the DLD as the authoritative spec.

| Task ID | Title | Description | Effort | Dependencies | Component |
|---------|-------|-------------|--------|-------------|-----------|
| P4-1 | CSS tokens + keyframes | Add all `--shadow-*`, `--radius-*`, `--motion-*`, `--shimmer-*` tokens and 5 `@keyframes` to `index.css` | 0.5d | — | `frontend/src/index.css` |
| P4-2 | `Card.jsx` primitive | Surface container with optional header slot per DLD | 0.5d | P4-1 | `frontend/src/components/ui/Card.jsx` |
| P4-3 | `Toast.jsx` + `ToastContext.jsx` | Toast notification with 3s auto-dismiss per DLD | 1d | P4-1 | `frontend/src/components/ui/Toast.jsx` |
| P4-4 | `ui/index.js` barrel | Export all ui primitives (Button, Card, Badge, Skeleton, ProgressRing, Toast) | 0.25d | P4-2, P4-3 | `frontend/src/components/ui/index.js` |
| P4-5 | `CardLearningView` pill MCQ + ProgressDots | Replace buttons, implement segmented dots, shake animation per DLD §9.5 | 1.5d | P4-1 | `frontend/src/components/learning/CardLearningView.jsx` |
| P4-6 | `CardLearningView` focus mode + AssistantPanel | Panel hidden until first answer; slide-in behaviour per DLD §9.5 | 1d | P4-5 | `frontend/src/components/learning/CardLearningView.jsx` |
| P4-7 | `CompletionView` ProgressRing + confetti + score bands | SVG ring animation, CSS confetti, 60-threshold bands per DLD §9.7 | 1d | P4-1, P4-4 | `frontend/src/components/learning/CompletionView.jsx` |
| P4-8 | `SocraticChat` flex column + fixed input | Flex layout, fixed bar, typing indicator, Enter key, auto-scroll per DLD §9.6 | 1d | P4-1 | `frontend/src/components/learning/SocraticChat.jsx` |
| P4-9 | `AppShell` student dropdown | Popover with profile info and Switch Student per DLD §9.8 | 0.75d | P4-1 | `frontend/src/components/layout/AppShell.jsx` |
| P4-10 | `WelcomePage` hero | Hero layout improvement per DLD | 0.5d | P4-1 | `frontend/src/pages/WelcomePage.jsx` |
| P4-11 | `ConceptMapPage` + `ConceptPanel` | 3-column flex layout, slide-in ConceptPanel per DLD §9.4 | 1.5d | P4-1 | `frontend/src/pages/ConceptMapPage.jsx`, `frontend/src/components/conceptmap/ConceptPanel.jsx` |

**Phase 4 total estimated effort: 9.5 days**

**Critical path in Phase 4:** P4-1 → P4-5 → P4-6 (CardLearningView must be stable before Phase 5 inserts Group B components into it)

---

### Phase 5 — Frontend Group B (Adaptive Transparency)

**Dependencies on Phase 4:** P5 begins only after P4-5 and P4-6 are complete (CardLearningView frame established). P5-6 (`StudentHistoryPage`) can begin in parallel with Phase 4 as it is an independent page.

| Task ID | Title | Description | Effort | Dependencies | Component |
|---------|-------|-------------|--------|-------------|-----------|
| P5-1 | `SessionContext` state additions | Add `learningProfileSummary`, `adaptationApplied`, `difficultyBias` to initialState + reducer per DLD §5.5 | 0.5d | — | `frontend/src/context/SessionContext.jsx` |
| P5-2 | `SET_DIFFICULTY_BIAS` action + `setDifficultyBias` callback | New reducer case + exported callback per DLD §5.5 | 0.25d | P5-1 | `frontend/src/context/SessionContext.jsx` |
| P5-3 | `goToNextCard` — forward `difficultyBias` | Modify `goToNextCard` to include `state.difficultyBias` in signals; update deps array per DLD §5.5 | 0.25d | P5-1, P5-2 | `frontend/src/context/SessionContext.jsx` |
| P5-4 | `completeCardAndGetNext` — add `difficulty_bias` field | Modify `sessions.js` to forward `difficultyBias` per DLD §5.3 | 0.25d | P5-3 | `frontend/src/api/sessions.js` |
| P5-5 | `getCardHistory` API wrapper | Add to `students.js` per DLD §5.4 | 0.25d | — | `frontend/src/api/students.js` |
| P5-6 | `StudentHistoryPage.jsx` | Full implementation: data fetch, table, session grouping, sparkline SVG per DLD §9.3 | 2d | P5-5 | `frontend/src/pages/StudentHistoryPage.jsx` |
| P5-7 | Register `/history` route | Add route to `App.jsx`; add "View History" link in `AppShell` dropdown per DLD §9.3 | 0.25d | P5-6, P4-9 | `frontend/src/App.jsx`, `frontend/src/components/layout/AppShell.jsx` |
| P5-8 | `AdaptiveSignalTracker.jsx` | Full component: live signal polling, profile display, readiness bar, bias buttons per DLD §9.1 | 1.5d | P5-1, P5-2, P4-6 | `frontend/src/components/learning/AdaptiveSignalTracker.jsx` |
| P5-9 | Slot `AdaptiveSignalTracker` into `CardLearningView` | Import and render inside `AssistantPanel`; pass correct ref props and callbacks | 0.5d | P5-8, P4-6 | `frontend/src/components/learning/CardLearningView.jsx` |
| P5-10 | Difficulty badge in card header | Inline star rendering in `CardLearningView` card header per DLD §9.2 | 0.5d | P4-5 | `frontend/src/components/learning/CardLearningView.jsx` |

**Phase 5 total estimated effort: 6.25 days**

---

## 2. Phased Delivery Plan

### Phase 1 — Design (COMPLETE)
**Goal:** Produce all three design artifacts before any code is written.
**Deliverables:** `HLD.md`, `DLD.md`, `execution-plan.md` in `docs/adaptive-transparency/`
**Duration:** 2 days (complete as of 2026-02-28)

---

### Phase 2 — Backend Changes
**Goal:** Deliver working backend endpoints and adaptive engine changes. No frontend work begins until backend code is reviewable.
**Agent:** `backend-developer`
**Duration:** 4 days
**Milestone:** `GET /api/v2/students/{id}/card-history` returns data; `complete-card` accepts `difficulty_bias`; `generate_next_card()` applies bias override and pattern injection.

**Phase 2 Definition of Done:**
- [ ] `WRONG_OPTION_PATTERN_THRESHOLD`, `CARD_HISTORY_DEFAULT_LIMIT`, `CARD_HISTORY_MAX_LIMIT` exported from `config.py`
- [ ] `CardBehaviorSignals.difficulty_bias` field accepted without error by the Pydantic model
- [ ] `NextCardRequest` inherits `difficulty_bias` transparently
- [ ] `load_wrong_option_pattern()` queries `card_interactions` correctly (manually verified with psql)
- [ ] `generate_next_card()` returns a 5-tuple; all callers in `adaptive_router.py` updated
- [ ] Card dict returned by `generate_next_card()` contains `"difficulty"` key
- [ ] `GET /api/v2/students/{id}/card-history` returns 200 with correct schema when queried manually (curl)
- [ ] `GET /api/v2/students/{id}/card-history?limit=2` returns at most 2 rows
- [ ] `GET /api/v2/students/{unknown-uuid}/card-history` returns 404
- [ ] No existing tests broken (if test suite exists)
- [ ] All new backend code has structured log entries
- [ ] No `print()` debug statements in committed code

---

### Phase 3 — Tests
**Goal:** All unit and integration tests written and passing.
**Agent:** `comprehensive-tester`
**Duration:** 5.5 days (can overlap with Phase 4 and 5)
**Note:** Phase 3 runs in parallel with Phases 4 and 5. Unit tests (P3-1 through P3-11) can begin immediately after Phase 2 tasks are complete. Integration tests (P3-12 through P3-18) require a running test database.

**Phase 3 Definition of Done:**
- [ ] All 18 test tasks (P3-1 through P3-18) implemented and green
- [ ] Each test name maps to a business criterion (naming convention: `test_<entity>_<condition>_<expected_result>`)
- [ ] No test uses hardcoded UUIDs that conflict with other test data
- [ ] Integration tests use an isolated test database (not the dev database)
- [ ] Test file `tests/test_adaptive_schemas.py` created if not existing
- [ ] Test file `tests/test_prompt_builder.py` created if not existing

---

### Phase 4 — Frontend Group A (Premium Redesign)
**Goal:** All premium redesign components from `docs/risk-hardening-redesign/DLD.md §9.1–§9.8` implemented and manually verified.
**Agent:** `frontend-developer`
**Duration:** 9.5 days
**Note:** Phase 4 can begin independently of Phase 2 and 3. The only prerequisite is the completed design documents.

**Phase 4 Definition of Done:**
- [ ] CSS tokens and all 5 keyframes in `index.css`; dark mode overrides verified
- [ ] `Card.jsx` and `Toast.jsx` implemented per spec; `ui/index.js` barrel exports all 6 primitives
- [ ] `CardLearningView`: pill MCQ buttons render; shake animation fires on wrong answer; ProgressDots are segmented; AssistantPanel starts hidden and slides in after first answer
- [ ] `CompletionView`: ProgressRing animates on mount; confetti appears on `mastered=true`; score bands use 60-threshold colors
- [ ] `SocraticChat`: input bar is fixed at bottom; Enter sends; Shift+Enter newline; typing indicator shows during API call; auto-scroll reliable
- [ ] `AppShell`: student name is a button; popover shows profile details and "Switch Student"; closes on outside click
- [ ] `WelcomePage`: hero section visually improved
- [ ] `ConceptMapPage`: 3-column flex layout; `ConceptPanel` slides in on node click; no absolute-positioned tooltip
- [ ] All components work across 4 themes (default, pirate, astronaut, gamer) — verified manually
- [ ] All components work at 375px (mobile), 768px (tablet), 1440px (desktop) viewports
- [ ] No `console.log` debug statements in committed code

---

### Phase 5 — Frontend Group B (Adaptive Transparency)
**Goal:** All six Group B transparency features implemented and integrated.
**Agent:** `frontend-developer`
**Duration:** 6.25 days
**Prerequisites:** P4-5 and P4-6 complete (CardLearningView frame), Phase 2 complete (backend endpoints available)

**Phase 5 Definition of Done:**
- [ ] `SessionContext` has `learningProfileSummary`, `adaptationApplied`, `difficultyBias` in state
- [ ] `ADAPTIVE_CARD_LOADED` reducer clears `difficultyBias` to `null`
- [ ] `goToNextCard` sends `difficultyBias` in signal payload to API
- [ ] `completeCardAndGetNext()` in `sessions.js` includes `difficulty_bias` field
- [ ] `getCardHistory()` in `students.js` implemented
- [ ] `StudentHistoryPage` at `/history` loads data for current student; redirects to `/` if no student in context
- [ ] History table columns match DLD §9.3 specification
- [ ] Session arc sparkline SVG renders for sessions with 2+ cards; `null` for single-card sessions
- [ ] `/history` route registered in `App.jsx`
- [ ] "View History" link in `AppShell` dropdown navigates to `/history`
- [ ] `AdaptiveSignalTracker` updates live time every 1 second
- [ ] "Too Easy" / "Too Hard" buttons toggle; clicking active button clears bias; bias clears after `ADAPTIVE_CARD_LOADED`
- [ ] Difficulty badge renders correct star count for `difficulty` 1–5
- [ ] Mastery readiness bar reflects `confidence_score` from `learningProfileSummary`
- [ ] All components handle null/loading state without crashing
- [ ] No `console.log` debug statements in committed code

---

## 3. Dependencies and Critical Path

### Dependency Graph

```
P1-1 (HLD)
  └── P1-2 (DLD)
        └── P1-3 (Execution Plan)
              ├── P2-1 (config constants)
              │     ├── P2-4 (load_wrong_option_pattern)
              │     │     └── P2-5 (generate_next_card modify)
              │     │           ├── P2-6 (prompt_builder modify)
              │     │           └── P2-7 (router update)
              │     └── P2-8 (card-history endpoint)
              ├── P2-2 (CardBehaviorSignals extend)
              │     └── P2-5 (generate_next_card)
              └── P2-3 (Pydantic schemas)
                    └── P2-8 (card-history endpoint)

P2-4 done → P3-2, P3-3, P3-4 (unit tests for pattern fn)
P2-5 done → P3-5, P3-6, P3-11 (unit tests for bias override + difficulty)
P2-6 done → P3-7, P3-8, P3-9, P3-10 (unit tests for prompt)
P2-2 done → P3-1 (schema unit test)
P2-7 done → P3-17, P3-18 (integration tests for complete-card)
P2-8 done → P3-12, P3-13, P3-14, P3-15, P3-16 (integration tests for history)

P4-1 (CSS tokens) — independent start
  └── P4-2, P4-3, P4-5, P4-7, P4-8, P4-9, P4-10, P4-11 (all depend on tokens)
        └── P4-4 (barrel after all ui components)
        └── P4-6 (focus mode — after P4-5)

P4-5, P4-6 done ────────────────────┐
P5-1 (context additions)            │
  └── P5-2 (bias action)            │
        └── P5-3 (goToNextCard)     │
              └── P5-4 (sessions.js)│
                                    ↓
                            P5-8 (AdaptiveSignalTracker)
                              └── P5-9 (slot into CardLearningView) ← requires P4-6

P5-5 (getCardHistory) → P5-6 (StudentHistoryPage) → P5-7 (routing + nav link)
P4-5 done → P5-10 (difficulty badge)
```

### Critical Path

The longest dependency chain that controls the overall release timeline:

**P1-1 → P1-2 → P1-3 → P2-1 → P2-4 → P2-5 → P2-7 → [tests pass] → P5-1 → P5-2 → P5-3 → P5-8 → P5-9**

This chain spans backend and frontend and requires sequential completion. All other tasks can be parallelised around it.

### External Blocking Dependencies

| Dependency | Blocked Tasks | Owner |
|------------|-------------|-------|
| Test infrastructure (`conftest.py`, test DB) must exist | P3-12 through P3-18 | devops-engineer (pre-existing debt) |
| `get_db()` FastAPI dependency must be implemented in `db/connection.py` | All integration tests, P2-8 | devops-engineer (pre-existing debt) |

---

## 4. Definition of Done — Combined Release

A release of `adaptive-transparency` is complete when **all five phases** satisfy their individual DoD sections above. In addition:

**Cross-cutting requirements:**
- [ ] `docs/adaptive-transparency/HLD.md`, `DLD.md`, and `execution-plan.md` are up to date with any implementation deviations discovered during coding
- [ ] All new backend functions have docstrings following the project convention
- [ ] No Python `print()` statements; no JavaScript `console.log` statements in any committed file
- [ ] All tests are green with no skipped tests
- [ ] A manual end-to-end smoke test has been performed: start lesson → complete 3 cards (clicking "Too Hard" on card 2) → verify card 3 is noticeably simpler → open `/history` → verify card 2 appears in table with `adaptation_applied` showing bias label

---

## 5. Rollout Strategy

### Deployment Approach

**Local development only** — no production deployment changes required for this release. The backend serves on `localhost:8000` and the frontend on `localhost:5173` (Vite dev server).

### Feature Flag

No feature flag is required for Group A (visual redesign is always-on).

For Group B, `ADAPTIVE_CARDS_ENABLED` (already in `config.py`) gates the adaptive card loop. All Group B features are additive within the adaptive card loop — if `ADAPTIVE_CARDS_ENABLED=false`, none of the Group B backend changes are exercised. This provides implicit rollback at the config level.

### Rollback Plan

**Backend:** Git revert of the adaptive engine and router changes is sufficient. The `card_interactions` table is unchanged, so no data migration is needed.

**Frontend:** Git revert of the modified context and component files. The `SessionContext` change is backward compatible — components that do not read `learningProfileSummary`, `adaptationApplied`, or `difficultyBias` are unaffected.

### Post-Launch Validation Steps

1. Manually create a student and start a lesson. Verify the difficulty badge appears on card 1.
2. Answer the first card incorrectly 3+ times on the same wrong option. Advance to card 2. Inspect the LLM prompt (via debug log) to confirm the MISCONCEPTION PATTERN block is present.
3. Click "Too Easy" before advancing to card 3. Inspect the LLM prompt to confirm DIFFICULTY ADJUSTMENT block is present and `recommended_next_step=CHALLENGE` is logged.
4. Navigate to `/history`. Verify the history table populates with the 3 interactions from the session.
5. Verify the session arc sparkline renders as a line across 3 data points.

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Phase 1 — Design | HLD, DLD, Execution Plan | 2 days | 1 × solution-architect |
| Phase 2 — Backend | Config constants, `CardBehaviorSignals` extension, wrong-option query, `generate_next_card` modification, prompt builder extension, adaptive router update, card-history endpoint | 3.85 days | 1 × backend-developer |
| Phase 3 — Tests | 11 unit tests, 7 integration tests across schemas, engine, prompt builder, teaching router, adaptive router | 5.5 days | 1 × comprehensive-tester |
| Phase 4 — Frontend Group A | 11 component tasks: CSS tokens, keyframes, Card, Toast, barrel, CardLearningView, CompletionView, SocraticChat, AppShell, WelcomePage, ConceptMapPage + ConceptPanel | 9.5 days | 1 × frontend-developer |
| Phase 5 — Frontend Group B | 10 component tasks: SessionContext additions, API wrappers, StudentHistoryPage, sparkline, AdaptiveSignalTracker, difficulty badge, routing | 6.25 days | 1 × frontend-developer |
| **Total** | **All phases** | **27.1 days** | **4 agents (Phases 3–5 parallel)** |

**Parallelism opportunity:** Phases 3, 4, and 5 can overlap once Phase 2 is complete. If run fully in parallel after Phase 2:
- Phase 3 (tests): 5.5 days
- Phase 4 (Group A): 9.5 days
- Phase 5 (Group B, after P4-5/P4-6): 6.25 days — starts ~3 days into Phase 4

**Effective wall-clock duration (with parallelism):** Phase 1 (2d) + Phase 2 (4d) + Phase 4 (9.5d, gating Phase 5) = **~15.5 days** with two frontend developers or sequential execution of Group A then Group B.

---

## Key Decisions Requiring Stakeholder Input

1. **Implementation order for frontend:** Group A must be complete on `CardLearningView` before Group B components are slotted in. Should the frontend-developer deliver Group A first as a reviewable PR, then start Group B? Or should they work in a single branch?

2. **Phase 3 test infrastructure prerequisite:** Integration tests require `conftest.py` and a test database. If the devops-engineer has not yet delivered this infrastructure (known technical debt), Phase 3 integration tests (P3-12 through P3-18) cannot run. Confirm whether devops infrastructure will be delivered before this sprint's Phase 3 or whether integration tests should be written but marked `pytest.mark.skip` until infrastructure is ready.

3. **`generate_next_card()` 5-tuple arity:** This is a breaking change to the function signature. If any other caller exists outside `adaptive_router.py` (e.g., in tests or scripts), it will fail silently at unpack. Request that the backend-developer grep for all call sites before committing this change.

4. **Sparkline for single-card sessions:** See HLD Key Decisions §5. Confirm whether a dot or `null` is correct for 1-card sessions.

5. **Manual testing scope for Group A:** The DoD requires manual verification across 4 themes and 3 viewports. Confirm whether this is the frontend-developer's responsibility or the tester's responsibility for this release.
