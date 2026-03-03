# Full Adaptive Upgrade — Execution Plan

**Feature slug:** `full-adaptive-upgrade`
**Date:** 2026-03-02
**Status:** Ready to execute

---

## 1. Work Breakdown Structure (WBS)

All tasks reference specific files and line-level anchors confirmed by reading the codebase.

### Phase 1 — Config and Constants (Foundation)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P1-1 | Add XP constants to `config.py` | Add `XP_MASTERY=50`, `XP_MASTERY_BONUS=25`, `XP_MASTERY_BONUS_THRESHOLD=90`, `XP_CONSOLATION=10`, `XP_CARD_ADVANCE=5` to `backend/src/config.py` immediately after the `ADAPTIVE_CARD_CEILING` block | 0.25d | — | `config.py` |
| P1-2 | Add `XP_CARD_ADVANCE` to frontend constants | Add `export const XP_CARD_ADVANCE = 5;` to `frontend/src/utils/constants.js` | 0.1d | — | `constants.js` |

### Phase 2 — Backend Prompt Enrichment (Core Logic)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P2-1 | Fix FAST/STRONG wording in `adaptive/prompt_builder.py` | At ~line 213, replace `"- Skip introductory analogies; assume the student grasps concepts quickly.\n"` with `"- ALL content, definitions, and formulas MUST appear — never skip substance. Replace beginner analogies with real-world applications and 'why it works' reasoning.\n"`. Exact old_string documented in DLD section 9.4. | 0.25d | P1-1 | `adaptive/prompt_builder.py` |
| P2-2 | Add `learning_profile` and `history` params to `build_cards_system_prompt()` | Add `learning_profile=None` and `history=None` to function signature. Implement `_build_card_profile_block()` helper (exact text in DLD section 9.1). Append result to existing prompt string after `interests_text` + `style_text`. All mode conditions: STRUGGLING/SLOW → SUPPORT; FAST+STRONG → ACCELERATE; BORED → ENGAGEMENT BOOST; WORSENING trend → CONFIDENCE BUILDING; `is_known_weak_concept` → WEAK CONCEPT. | 1.0d | P1-1 | `prompts.py` |
| P2-3 | Add `wrong_option_pattern` param to `build_cards_user_prompt()` | Add `wrong_option_pattern: int | None = None` to function signature. Implement `_build_misconception_block()` helper (exact text in DLD section 9.2). Append before `"Respond with valid JSON only."` in the return string. | 0.5d | P2-2 | `prompts.py` |
| P2-4 | Add `session_card_stats` param to `build_socratic_system_prompt()` | Add `session_card_stats: dict | None = None` to function signature. Implement `_build_session_stats_block()` helper (exact text in DLD section 9.3). Replace the existing conditional profile blocks at the end of the function (lines ~293–315 in current code) with: keep `is_known_weak_concept` block unchanged; replace the STRUGGLING/STRONG/BORED conditionals with the `_build_session_stats_block()` call that handles both session and global signals. | 1.0d | P2-2 | `prompts.py` |

### Phase 3 — Backend Service Wiring

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P3-1 | Wire adaptive context into `generate_cards()` | In `teaching_service.py`, `generate_cards()` method: (1) Add lazy imports for `load_student_history`, `load_wrong_option_pattern`, `build_learning_profile`, `AnalyticsSummary` at the top of the method body (match pattern at line 174). (2) After the sub-section parsing block (step 2), add `asyncio.gather()` call for both history loads with the full `try/except` fallback per DLD section 8.1. (3) Build `learning_profile` when `total_cards_completed >= 3` per DLD section 2 (Flow A), including the `quiz_score` proxy formula. (4) Pass `learning_profile` and `history` to `build_cards_system_prompt()`; pass `wrong_option_pattern` to `build_cards_user_prompt()`. (5) Add the structured log line per DLD section 7. | 1.5d | P2-2, P2-3 | `teaching_service.py` |
| P3-2 | Wire session card stats into `begin_socratic_check()` | In `teaching_service.py`, `begin_socratic_check()`: (1) Add `CardInteraction` import to the lazy import block at line 174 (already imported in router, needs to be added here or use inline import). (2) Before the existing `load_student_history()` call, add the session stats query per DLD section 2 (Flow B) with `try/except` per DLD section 8.2. (3) Pass `session_card_stats` to `build_socratic_system_prompt()`. (4) Add structured log line per DLD section 7. | 1.0d | P2-4 | `teaching_service.py` |

### Phase 4 — Backend Schema and Router XP Award

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P4-1 | Add `xp_awarded` to `SocraticResponse` | In `teaching_schemas.py`, add `xp_awarded: int | None = None` to `SocraticResponse` Pydantic model after `exchange_count`. | 0.1d | — | `teaching_schemas.py` |
| P4-2 | Implement XP award in `respond_to_check` router handler | In `teaching_router.py`: (1) Import `XP_MASTERY`, `XP_MASTERY_BONUS`, `XP_MASTERY_BONUS_THRESHOLD`, `XP_CONSOLATION` from `config`. (2) Add `_award_xp()` private async function per DLD section 5.2 (inline pattern, not background task). (3) In the `respond_to_check` handler, after `result = await teaching_svc.handle_student_response(...)`, add XP computation and `await _award_xp(...)` when `result["check_complete"]` is `True`. (4) Set `xp_awarded` on the `SocraticResponse`. The DB `student` object is needed for `new_streak`; retrieve it inline with `await db.get(Student, session.student_id)`. | 1.0d | P1-1, P4-1 | `teaching_router.py` |

### Phase 5 — Frontend Wiring

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P5-1 | Mount `XPBurst` in `AppShell.jsx` | Import `XPBurst` from `../game/XPBurst`. Mount at root `<div>` level (outside the nav, at the top of the return tree) so it overlays the full page. `XPBurst` reads `lastXpGain` from `useAdaptiveStore` internally — no props needed. | 0.25d | — | `AppShell.jsx` |
| P5-2 | Wire `updateMode` in `SessionContext.jsx` after `ADAPTIVE_CARD_LOADED` | In the `goToNextCard` callback, after `dispatch({ type: "ADAPTIVE_CARD_LOADED", payload: res.data })`, add `useAdaptiveStore.getState().updateMode(res.data.learning_profile_summary)`. Guard: only call if `res.data.learning_profile_summary` is truthy. | 0.25d | — | `SessionContext.jsx` |
| P5-3 | Wire `awardXP(XP_CARD_ADVANCE)` in `SessionContext.jsx` after card advance | In the same location as P5-2, after the `updateMode` call, add `useAdaptiveStore.getState().awardXP(XP_CARD_ADVANCE)`. Import `XP_CARD_ADVANCE` from `../utils/constants`. | 0.25d | P1-2, P5-2 | `SessionContext.jsx` |
| P5-4 | Wire mastery XP + streak in `SessionContext.jsx` after check completion | In the `sendAnswer` callback, inside the `if (res.data.check_complete)` block: (1) If `res.data.xp_awarded` is truthy, call `useAdaptiveStore.getState().awardXP(res.data.xp_awarded)`. (2) If `res.data.mastered`, call `useAdaptiveStore.getState().recordAnswer(true)` to drive the streak display (the DB streak is updated by the backend; this updates the Zustand streak counter for immediate UI feedback). | 0.5d | P5-2, P4-2 | `SessionContext.jsx` |
| P5-5 | Add lesson interests panel to `LearningPage.jsx` | Add a collapsible "Customize this lesson" section visible only when `phase === "IDLE"` (before `startLesson` is called). The panel contains a text input where the user can enter comma-separated interests. Store value in local `useState`. Pass as the `lessonInterests` array argument to `startLesson()`. The panel should be collapsed by default (show a chevron toggle). Use the existing card-style surface (`var(--color-surface)`, `var(--color-border)`). i18n key: `learning.customizePanel`. | 0.75d | — | `LearningPage.jsx` |
| P5-6 | Make interests field visually optional in `StudentForm.jsx` | Locate the interests input field in `frontend/src/components/` (Glob for `StudentForm`). Change the field label from a prominent heading or required-looking label to a subtle `<p>` or `placeholder` that reads "Optional: add interests (e.g., soccer, coding) to personalise examples". Remove any required marker or asterisk if present. | 0.25d | — | `StudentForm.jsx` |
| P5-7 | Verify `recordAnswer(false)` on wrong MCQ in `CardLearningView.jsx` | Read the `handleMcqAnswer` handler in `CardLearningView.jsx` (lines ~185–). Confirm that `recordAnswer(false)` is called when the answer is wrong. Current code already calls `awardXP(10)` and `recordAnswer(true)` on correct; the wrong path should call `recordAnswer(false)`. If missing, add it. Also verify the TF answer handler (`handleTfAnswer`) has the same pattern. | 0.25d | — | `CardLearningView.jsx` |

### Phase 6 — Tests

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P6-1 | Unit tests for prompt block functions | Write all 12 unit tests from DLD section 10 covering `build_cards_system_prompt()` profile injection, `build_cards_user_prompt()` misconception block, `build_socratic_system_prompt()` session stats block, and the adaptive prompt builder FAST/STRONG wording. Use `assert ... in prompt` pattern — no LLM calls needed. | 1.0d | P2-1 through P2-4 | `tests/test_prompts.py` |
| P6-2 | Unit tests for XP award logic | Write 4 unit tests from DLD section 10 for XP computation logic. Can be tested as pure function tests by extracting the computation into a helper `_compute_xp_award(mastered, score)` in the router or a separate utility. | 0.5d | P4-1, P4-2 | `tests/test_teaching_router.py` |
| P6-3 | Integration tests for adaptive card generation | Using FastAPI `TestClient` with a test DB: seed `CardInteraction` rows for a student; call `POST /sessions/{id}/cards`; assert 200 and cards returned. Use `unittest.mock.patch` to intercept the LLM call and return a canned JSON response. Assert that `build_cards_system_prompt` was called with a non-None `learning_profile` when enough history exists. | 1.0d | P3-1 | `tests/test_teaching_router.py` |
| P6-4 | Integration tests for XP award endpoint | Seed a session in CHECKING phase; drive it to completion with a mock Socratic response (or force ASSESSMENT marker); assert `students.xp` incremented correctly in DB and `xp_awarded` in response JSON. | 0.75d | P4-2 | `tests/test_teaching_router.py` |

---

## 2. Phased Delivery Plan

### Phase 1 — Foundation (Day 1 morning)
**Goal:** Config constants in place so all other phases can import them.

- P1-1: Add XP constants to `config.py`
- P1-2: Add `XP_CARD_ADVANCE` to `frontend/src/utils/constants.js`

**Acceptance:** `from config import XP_MASTERY` imports without error. `constants.js` exports `XP_CARD_ADVANCE`.

---

### Phase 2 — Prompt Enrichment (Day 1 afternoon to Day 2 morning)
**Goal:** All prompt builder functions accept and respond to the new parameters. This phase is independently testable with unit tests — no LLM calls required.

- P2-1: Fix FAST/STRONG wording in `adaptive/prompt_builder.py`
- P2-2: Add profile injection to `build_cards_system_prompt()`
- P2-3: Add misconception block to `build_cards_user_prompt()`
- P2-4: Add session stats block to `build_socratic_system_prompt()`

**Acceptance:** Unit tests P6-1 all pass with `pytest backend/tests/test_prompts.py`.

---

### Phase 3 — Service Wiring (Day 2)
**Goal:** Live backend calls use adaptive context. Can be tested end-to-end with the running server + real DB.

- P3-1: Wire `generate_cards()`
- P3-2: Wire `begin_socratic_check()`

**Acceptance:**
- `POST /sessions/{id}/cards` succeeds for a new student (no history)
- `POST /sessions/{id}/cards` succeeds for a returning student (history present) and log line `[cards-adaptive]` appears
- `POST /sessions/{id}/check` succeeds and log line `[socratic-adaptive]` appears (even with empty session interactions)

---

### Phase 4 — Schema and XP Award (Day 3 morning)
**Goal:** Mastery awards XP visibly in the response; DB is updated atomically.

- P4-1: Add `xp_awarded` to `SocraticResponse`
- P4-2: Implement XP award in router

**Acceptance:** Unit tests P6-2 pass. Integration test P6-4 passes.

---

### Phase 5 — Frontend Wiring (Day 3 afternoon to Day 4)
**Goal:** Frontend game HUD responds to adaptive signals and mastery events.

- P5-1: Mount `XPBurst` in `AppShell`
- P5-2: Wire `updateMode` after card advance
- P5-3: Wire `awardXP(XP_CARD_ADVANCE)` after card advance
- P5-4: Wire mastery XP + streak
- P5-5: Add lesson interests panel to `LearningPage`
- P5-6: Make interests optional in `StudentForm`
- P5-7: Verify `recordAnswer(false)` for wrong answers

**Acceptance:** Manual walkthrough: start lesson → advance card → confirm XP burst and streak counter update. Complete Socratic check → confirm mastery XP burst.

---

### Phase 6 — Tests and Hardening (Day 4 to Day 5)
**Goal:** All specified tests passing; no regressions.

- P6-1 through P6-4: Write and run all tests

**Acceptance:** All tests pass. No new test failures in `test_adaptive_engine.py` or `test_adaptive_tutor.py`.

---

## 3. Dependencies and Critical Path

```
P1-1 (Config) ──────────────────────────────────────────────────────────────┐
                                                                             │
P2-1 (Prompt Builder fix) ──depends on── P1-1 ──────────────────────────────┤
                                                                             │
P2-2 (cards_system_prompt) ──depends on── P1-1 ─────────────────────────────┤
    │                                                                        │
    └──► P2-3 (cards_user_prompt) ──► P3-1 (generate_cards wiring) ─────────┤
    │                                                                        │
    └──► P2-4 (socratic_prompt) ──► P3-2 (begin_socratic_check wiring) ─────┤
                                                                             │
P4-1 (Schema xp_awarded) ───────────────────────────────────────────────────┤
    │                                                                        │
    └──► P4-2 (Router XP award) ─────────────────────────────────────────────┤
                                                                             │
P1-2 (Frontend constants) ──► P5-3 (awardXP) ───────────────────────────────┤
                                                                             │
P5-2 (updateMode) ──► P5-3 (awardXP) ──► P5-4 (mastery XP) ────────────────┤
                                                                             │
[All P2-P4] ──► P6-1, P6-2, P6-3, P6-4 (Tests) ─────────────────────────────┘
```

**Critical path:** P1-1 → P2-2 → P3-1 → P6-3 (backend adaptive cards test)

**Parallel work opportunities:**
- P5-1 through P5-7 (frontend) can run entirely in parallel with P2-P4 (backend)
- P6-1 can begin as soon as P2-4 is complete (unit tests only)
- P4-1 and P4-2 can begin as soon as P1-1 is done (independent of prompt changes)

**External blocking dependencies:**
- None. All required functions (`load_student_history`, `load_wrong_option_pattern`, `build_learning_profile`, `awardXP`, `updateMode`, `recordAnswer`, game components) are already implemented and in the codebase.

---

## 4. Definition of Done

### Phase 1 DoD
- [ ] `from config import XP_MASTERY, XP_MASTERY_BONUS, XP_MASTERY_BONUS_THRESHOLD, XP_CONSOLATION, XP_CARD_ADVANCE` imports without error
- [ ] `from src.utils.constants import XP_CARD_ADVANCE` works in frontend
- [ ] Constants match values specified in DLD (50, 25, 90, 10, 5)

### Phase 2 DoD
- [ ] `build_cards_system_prompt(style="default", interests=None, language="en")` (existing signature, no new args) returns identical output to pre-upgrade — no regression
- [ ] `build_cards_system_prompt(..., learning_profile=<STRUGGLING_PROFILE>, history={...})` returns prompt containing "age-8" or "age 8" and "SUPPORT" mode text
- [ ] `build_cards_system_prompt(..., learning_profile=<FAST_STRONG_PROFILE>, history={...})` returns prompt containing "ALL content" and NOT containing "Skip introductory"
- [ ] `build_cards_user_prompt(..., wrong_option_pattern=2)` returns prompt containing "option index 2"
- [ ] `build_cards_user_prompt(..., wrong_option_pattern=None)` returns prompt NOT containing "MISCONCEPTION"
- [ ] `build_socratic_system_prompt(..., session_card_stats={"total_cards": 5, "total_wrong": 3, "total_hints": 2, "error_rate": 0.6})` returns prompt containing "at least 5 questions"
- [ ] `adaptive/prompt_builder.py` FAST/STRONG block contains "ALL content, definitions, and formulas MUST appear"
- [ ] All P6-1 unit tests pass

### Phase 3 DoD
- [ ] `POST /sessions/{id}/cards` returns 200 for a student with zero card history
- [ ] `POST /sessions/{id}/cards` for a student with >= 3 card interactions produces a structured log line `[cards-adaptive]` with correct profile fields
- [ ] `POST /sessions/{id}/check` produces a structured log line `[socratic-adaptive]` with session stats
- [ ] No regression on `POST /sessions/{id}/cards` cache invalidation (session with existing `presentation_text` returns cached result, no re-generation)
- [ ] All P6-3 integration tests pass

### Phase 4 DoD
- [ ] `SocraticResponse` Pydantic model has `xp_awarded` field with default `None`
- [ ] `POST /sessions/{id}/respond` with a mocked response that triggers `check_complete=True, mastered=True, score=85` returns `xp_awarded=50`
- [ ] Same with `score=92` returns `xp_awarded=75`
- [ ] Same with `mastered=False` returns `xp_awarded=10`
- [ ] `students.xp` incremented correctly in DB after mastery
- [ ] All P6-2 and P6-4 tests pass

### Phase 5 DoD
- [ ] `XPBurst` animation fires visibly when any XP is awarded (card advance, correct MCQ, mastery)
- [ ] `StreakMeter` in `AppShell` updates after correct MCQ
- [ ] `AdaptiveModeIndicator` changes after first card advance when `learning_profile_summary` is present
- [ ] "Customize this lesson" panel collapses/expands correctly; entered interests passed to `startLesson()`
- [ ] `StudentForm` interests field has hint/optional visual treatment — no asterisk or "Required" label
- [ ] Wrong MCQ answer calls `recordAnswer(false)` (streak resets to 0 in Zustand store)
- [ ] Manual walkthrough FE-01 through FE-06 from DLD section 10 all pass

### Phase 6 DoD
- [ ] `pytest backend/tests/` passes with 0 failures, 0 errors
- [ ] Tests `test_adaptive_engine.py` and `test_adaptive_tutor.py` still pass (no regression)
- [ ] Code reviewed by at least one other engineer before merge
- [ ] Structured log lines verified in local server output during a test session
- [ ] No `print()` statements added in any backend file

---

## 5. Rollout Strategy

### Deployment Approach
**Direct deploy** (no feature flag needed). All changes are quality improvements to existing functionality:
- Prompt enrichment is transparent to the client — same response schema
- `xp_awarded` is a new nullable field — backward compatible with clients that ignore it
- Frontend changes are cosmetic additions (XPBurst mount, interest panel) and Zustand store wiring

If the team wants extra caution, wrap the history-load enrichment with the existing `ADAPTIVE_CARDS_ENABLED` feature flag from `config.py` while rolling out, then remove the flag once stable.

### Rollback Plan
Each phase is independently reversible:
- **Phase 2 (prompt changes):** Revert the function signatures to remove new parameters. All callers pass no new args → defaults to `None` → existing behaviour.
- **Phase 3 (service wiring):** Revert the `asyncio.gather()` and profile-build blocks. `generate_cards()` and `begin_socratic_check()` return to original behaviour.
- **Phase 4 (XP award):** Revert `_award_xp()` call in router. `SocraticResponse.xp_awarded` remains in schema with `None` default — no client breakage.
- **Phase 5 (frontend):** Each frontend task is isolated to a single component. Revert individually.

### Monitoring Post-Launch
1. Watch for new `WARNING` log lines from history load fallbacks — would indicate a DB issue
2. Monitor card generation latency for any increase > 100 ms (two additional DB queries)
3. Watch for `[xp-awarded]` log density — should match lesson completion rate
4. Check for Pydantic validation errors in response logs (would indicate `SocraticResponse` schema mismatch)

### Post-Launch Validation Steps
1. Run a complete session as a new student: verify generic (no-profile) cards are generated correctly
2. Run a complete session as a returning student (>=3 prior card interactions): verify `[cards-adaptive]` log line shows correct profile
3. Complete a session with mastery: verify `xp_awarded` in response, verify DB `students.xp` updated, verify XPBurst fires
4. Complete a session without mastery: verify `xp_awarded=10` consolation
5. Run the full test suite: `pytest backend/tests/`

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Phase 1 — Foundation | Config + frontend constants | 0.35d | 1 backend dev (P1-1) + 1 frontend dev (P1-2) in parallel |
| Phase 2 — Prompt Enrichment | Profile block, misconception block, session stats block, FAST/STRONG fix | 2.75d | 1 backend dev |
| Phase 3 — Service Wiring | `generate_cards()` + `begin_socratic_check()` adaptive context | 2.5d | 1 backend dev |
| Phase 4 — Schema + XP Award | `SocraticResponse` schema + router XP handler | 1.1d | 1 backend dev |
| Phase 5 — Frontend Wiring | XPBurst, SessionContext wiring, interests panel, StudentForm | 2.25d | 1 frontend dev |
| Phase 6 — Tests | 4 test modules, ~16 test cases | 3.25d | 1 tester (can start P6-1 on Day 2) |
| **Total** | **16 tasks** | **~12.2d total work** | **2 engineers (backend + frontend) + 1 tester** |

**Calendar estimate with 2 engineers + 1 tester working in parallel:**
- Backend (Phase 1–4): ~5 calendar days
- Frontend (Phase 5, parallel): ~3 calendar days
- Tests (Phase 6, overlapping Days 2–5): adds ~1 calendar day buffer
- **Estimated delivery: 5–6 calendar days**

---

## Notes for Implementation

### Import Patterns to Follow
`begin_socratic_check()` already demonstrates the correct lazy import pattern (lines 174–176 in `teaching_service.py`):
```python
from adaptive.adaptive_engine import load_student_history
from adaptive.profile_builder import build_learning_profile
from adaptive.schemas import AnalyticsSummary
```
`generate_cards()` must follow the same pattern. Do not add these as module-level imports — lazy imports are used here to avoid circular import risk.

### `asyncio.gather()` Usage
`asyncio.gather()` is already imported in `teaching_service.py` (line 8: `import asyncio`). Use it directly.

### `CardInteraction` Import in `begin_socratic_check()`
`CardInteraction` is imported at the module level in `teaching_router.py` but not in `teaching_service.py`. Add it as a lazy import inside the method:
```python
from db.models import CardInteraction
```
Or add it to the module-level imports at the top of `teaching_service.py` alongside the existing `from db.models import TeachingSession, ConversationMessage, StudentMastery, Student, SpacedReview`.

### Do Not Modify These Files (Reused Unchanged)
- `backend/src/adaptive/adaptive_engine.py` (except the logic is called — file not modified)
- `backend/src/adaptive/profile_builder.py`
- `backend/src/adaptive/schemas.py`
- `frontend/src/store/adaptiveStore.js`
- Any file in `frontend/src/components/game/`
- `backend/src/adaptive/adaptive_router.py`
