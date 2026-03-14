# Execution Plan: Adaptive Mode Switching

## Revision History
| Date | Author | Change |
|------|--------|--------|
| 2026-03-14 | solution-architect | Initial execution plan |

---

## 1. Work Breakdown Structure (WBS)

| ID | Task | File | Depends On |
|----|------|------|------------|
| P1-01 | RC-1: `_MODE_DELIVERY` dict in `prompts.py` | `api/prompts.py` | — |
| P1-02 | RC-1b: `_CARD_MODE_DELIVERY` dict in `prompt_builder.py` | `adaptive/prompt_builder.py` | — |
| P1-03 | RC-3: TRY_IT visual hints + TRY_IT_BATCH rule in `prompts.py` | `api/prompts.py` | P1-01 |
| P1-04 | RC-3: Mode header in `build_cards_user_prompt()` | `api/prompts.py` | P1-01 |
| P1-05 | RC-2: `_batch_consecutive_try_its()` + wire into `generate_cards()` | `api/teaching_service.py` | — |
| P1-06 | RC-5: Conservative mode cap after `build_blended_analytics()` | `api/teaching_service.py` | P1-05 |
| P1-07 | RC-7: Image rules in system prompt (L1) + user prompt (L4) | `api/prompts.py` | P1-01 |
| P1-08 | RC-7: Max-1 image enforcement + fallback to all types (L2, L3) | `api/teaching_service.py` | — |
| P1-09 | Cache version bump to 9 | `api/teaching_service.py` | P1-05, P1-06, P1-08 |
| P2-01 | RC-6: `_RECOVERY_STYLE_MODIFIERS` + `_RECOVERY_LANG_MAP` dicts | `adaptive/adaptive_engine.py` | — |
| P2-02 | RC-6: `generate_recovery_card()` function | `adaptive/adaptive_engine.py` | P2-01 |
| P2-03 | RC-6: `from json_repair import repair_json` module-level import | `adaptive/adaptive_engine.py` | P2-02 |
| P2-04 | RC-6: Extend `NextCardRequest` + `NextCardResponse` | `adaptive/schemas.py` | P2-02 |
| P2-05 | RC-6: `asyncio.gather` + `_maybe_recovery()` in router | `adaptive/adaptive_router.py` | P2-02, P2-04 |
| P2-06 | RC-8: `UpdateSessionInterestsRequest` schema | `api/teaching_schemas.py` | — |
| P2-07 | RC-8: `PUT /sessions/{id}/interests` endpoint | `api/teaching_router.py` | P2-06 |
| P3-01 | RC-4/RC-6: `re_explain_card_title` + `difficulty_bias` in `completeCardAndGetNext()` | `frontend/api/sessions.js` | P2-04 |
| P3-02 | RC-8: `updateSessionInterests()` in `sessions.js` | `frontend/api/sessions.js` | P2-07 |
| P3-03 | RC-6: `INSERT_RECOVERY_CARD` reducer + dispatch in `SessionContext.jsx` | `frontend/context/SessionContext.jsx` | P3-01 |
| P3-04 | RC-4: Pass signals on wrong×2 in `CardLearningView.jsx` | `frontend/components/learning/CardLearningView.jsx` | P3-01, P3-03 |
| P3-05 | RC-8: Add import from sessions.js to `LearningPage.jsx` + customize panel | `frontend/pages/LearningPage.jsx` | P3-02 |
| P3-06 | RC-8: Remove interests/style from `StudentForm.jsx` + add i18n note | `frontend/components/welcome/StudentForm.jsx` | — |
| P3-07 | RC-8: Add i18n keys to all 13 locale files | `frontend/src/locales/*.json` | P3-05, P3-06 |
| P4-01 | Tests: RC-1 prompt isolation (3 modes + unknown default) | `backend/tests/test_adaptive_mode_switching.py` | P1-01, P1-02 |
| P4-02 | Tests: RC-2 TRY_IT batching (merge, no-merge, solo) | `backend/tests/test_adaptive_mode_switching.py` | P1-05 |
| P4-03 | Tests: RC-5 conservative cap | `backend/tests/test_adaptive_mode_switching.py` | P1-06 |
| P4-04 | Tests: RC-6 recovery card (success, anti-loop, failure→None) | `backend/tests/test_adaptive_mode_switching.py` | P2-02 |
| P4-05 | Tests: `complete-card` endpoint with wrong×2 | `backend/tests/test_adaptive_mode_switching.py` | P2-05 |
| P4-06 | Tests: Image distribution | `backend/tests/test_adaptive_mode_switching.py` | P1-08 |
| P4-07 | Tests: `PUT /sessions/{id}/interests` endpoint | `backend/tests/test_adaptive_mode_switching.py` | P2-07 |
| P4-08 | Tests: Recovery card personalization (interests, style, language) | `backend/tests/test_adaptive_mode_switching.py` | P2-02 |
| P4-09 | Tests: Cache version == 9 regression guard | `backend/tests/test_adaptive_mode_switching.py` | P1-09 |

---

## 2. Phased Delivery

### Phase 1 — Backend Prompt + Service Fixes (no API surface changes)
Tasks: P1-01 through P1-09
**Deliverable:** LLM receives single mode block; TRY_IT merging works; conservative cap; image max-1; cache v9.

### Phase 2 — Core Backend Features (schemas + endpoints + engine)
Tasks: P2-01 through P2-07
**Deliverable:** Recovery card generation; extended schemas; interests endpoint.

### Phase 3 — Frontend Integration
Tasks: P3-01 through P3-07
**Deliverable:** Wrong×2 triggers adaptive call; recovery card injected; per-section customize panel; StudentForm simplified.

### Phase 4 — Tests
Tasks: P4-01 through P4-09
**Deliverable:** Full test coverage of all 9 fix paths.

---

## 3. Definition of Done

### Backend (Phases 1 + 2)
- [ ] `build_cards_system_prompt(generate_as="STRUGGLING")` output does NOT contain "DELIVERY MODE: NORMAL" or "DELIVERY MODE: FAST"
- [ ] `_batch_consecutive_try_its([TRY_IT_A, TRY_IT_B, EXAMPLE_C])` returns `[TRY_IT_BATCH_AB, EXAMPLE_C]`
- [ ] Solo TRY_IT passes through unchanged (no batching of single items)
- [ ] New student (0 interactions) → `[mode-cap]` log → NORMAL mode cards
- [ ] `generate_recovery_card()` returns card with `is_recovery=True` and title starting "Let's Try Again — "
- [ ] `generate_recovery_card()` returns `None` when title starts with "Let's Try Again" (anti-loop)
- [ ] `generate_recovery_card()` returns `None` on LLM exception (non-fatal)
- [ ] `_CARDS_CACHE_VERSION = 9` inside `generate_cards()`
- [ ] `PUT /sessions/{id}/interests` → 200 with updated `lesson_interests`
- [ ] Backend starts without import errors

### Frontend (Phase 3)
- [ ] Wrong×2 POST body contains `wrong_attempts: 2` and `re_explain_card_title` (non-null for non-recovery cards)
- [ ] Recovery card appears at `currentCardIndex + 1` in React DevTools cards array
- [ ] All card indices are sequential after recovery card insertion (no drift)
- [ ] Customize panel renders in LearningPage with style selector + interests input
- [ ] StudentForm has no interests input or style selector fields

### Tests (Phase 4)
- [ ] `pytest tests/test_adaptive_mode_switching.py -v` → all pass, no errors

---

## 4. Rollout Strategy

**Deployment:** Standard uvicorn `--reload`. No feature flag required (all changes are bug fixes or additive).

**Backward compatibility:**
- `NextCardRequest`: `re_explain_card_title` is optional (`None` default) — existing clients unchanged.
- `NextCardResponse`: `recovery_card` is optional (`None`) — existing frontend code ignores unknown fields.
- `PUT /sessions/{id}/interests`: new endpoint — no breakage to existing clients.

**Rollback:**
- RC-1/RC-1b: Revert dict to triple-block append (single function revert).
- RC-6: Remove `asyncio.gather` branch; revert to single `generate_next_card()` call.
- Cache version: Revert `_CARDS_CACHE_VERSION = 9` → `7` to re-enable cached decks.

---

## 5. Agent Assignments

| Agent | Tasks |
|-------|-------|
| `devops-engineer` | Verify pytest infra (Stage 0) — DONE |
| `solution-architect` | HLD + DLD + execution-plan (Stage 1) — DONE |
| `backend-developer` | P1-01 through P2-07 (Stage 2) |
| `comprehensive-tester` | P4-01 through P4-09 (Stage 3) |
| `frontend-developer` | P3-01 through P3-07 (Stage 4) |
