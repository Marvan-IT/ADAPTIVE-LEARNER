# Execution Plan — Chunk Classification & Language Feature

**Feature slug:** `chunk-classification-language`
**Date:** 2026-04-01

---

## 1. Work Breakdown Structure (WBS)

### Stage 2a — Socratic Removal (backend-developer + frontend-developer, parallel)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| S2a-01 | Remove Socratic backend routes | Delete `POST /sessions/{id}/check` and `POST /sessions/{id}/respond` handlers from `teaching_router.py`. Remove `StudentResponseRequest`, `SocraticResponse`, `RecheckResponse` schemas from `teaching_schemas.py`. | 0.5 d | none | `teaching_router.py`, `teaching_schemas.py` |
| S2a-02 | Remove Socratic frontend API wrappers | Remove `beginCheck` and `sendResponse` exports from `sessions.js`. Remove their imports from any calling component. | 0.25 d | none | `sessions.js` |
| S2a-03 | Delete SocraticChat.jsx | Delete `frontend/src/components/learning/SocraticChat.jsx`. Remove all imports and usages in `LearningPage.jsx`, `CardLearningView.jsx`, and any other component. Verify no other file imports it. | 0.5 d | S2a-02 | `SocraticChat.jsx`, `LearningPage.jsx` |
| S2a-04 | Remove Socratic state from SessionContext | Remove `messages`, `checkLoading`, `socraticAttempt`, `remediationNeeded`, `checkScore`, `checkPassed`, `bestScore` state fields and their reducer cases. Remove the `CHECK_STARTED`, `SOCRATIC_RESPONSE`, `RECHECK_*` action types. | 0.5 d | S2a-03 | `SessionContext.jsx` |
| S2a-05 | Add Complete button to CardLearningView | Render a "Complete" button on the last card of each chunk. Wire to `completeChunkItem()`. Add `learning.completeChunk` i18n key to all 13 locale files. | 0.5 d | S2a-04 | `CardLearningView.jsx`, `locales/*.json` |

**Stage 2a total: ~2.25 dev-days**

---

### Stage 2b — Backend Main (backend-developer)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| B-01 | Overhaul `_get_chunk_type()` | Replace current 3-type implementation with 6-type priority-order matcher. Add `_is_optional_chunk()` companion function. Add docstring with priority table. | 0.5 d | none | `teaching_router.py` |
| B-02 | Fix exam gate deduplication | Replace unconditional gate injection with `already_has_gate` guard in `list_chunks()`. Use `max(order_index) + 1` for gate position. | 0.25 d | B-01 | `teaching_router.py` |
| B-03 | Update `ChunkSummary` schema | Add `is_optional: bool = False` field. Update the `list_chunks()` handler to call `_is_optional_chunk()` when building each `ChunkSummary`. | 0.25 d | B-01 | `teaching_schemas.py`, `teaching_router.py` |
| B-04 | Update `all_study_complete` logic | Modify `teaching_ids` set in both `complete_chunk()` and new `complete_chunk_item()` to include `exercise` type chunks but exclude `is_optional=True` chunks. | 0.25 d | B-01, B-03 | `teaching_router.py` |
| B-05 | Add `POST /chunks/{id}/complete` endpoint | Implement `complete_chunk_item()` handler. Read `chunk_progress` JSONB, add chunk key with timestamp, recalculate `all_study_complete`, commit, return `CompleteChunkItemResponse`. Add `CompleteChunkItemRequest` / `CompleteChunkItemResponse` to `teaching_schemas.py`. Make idempotent. | 0.5 d | B-04 | `teaching_router.py`, `teaching_schemas.py` |
| B-06 | Extend `NextCardRequest` schema | Add optional `failed_exercise_question: str | None` and `student_wrong_answer: str | None` fields with `max_length=500`. | 0.25 d | none | `teaching_schemas.py` |
| B-07 | Implement `_translate_summaries_headings()` | Single `gpt-4o-mini` call with all headings as JSON array. 10 s timeout. Catch all exceptions and return original list. Parse response as JSON array of strings with length validation. | 0.75 d | none | `teaching_router.py` |
| B-08 | Extend language-change handler | In `update_student_language()`: find active session, call `_translate_summaries_headings()`, bust cache (`cache_version: -1`, clear `cards`), reset exam state in `presentation_text` JSONB. Return `translated_headings` and `session_cache_cleared` in response. Add `UpdateLanguageResponse` schema. | 0.75 d | B-07 | `teaching_router.py`, `teaching_schemas.py` |
| B-09 | Exercise card system prompts | Add `build_exercise_card_system_prompt(language)` and `build_exercise_recovery_prompt(failed_question, wrong_answer, chunk_heading, chunk_text, language)` to `prompts.py`. | 0.5 d | none | `prompts.py` |
| B-10 | Exercise card prompt builder | Add `build_exercise_card_prompt(chunk, student_profile, language)` to `prompt_builder.py`. Pure function. 2000-char text truncation. Card count instruction based on problem count heuristic. | 0.5 d | B-09 | `prompt_builder.py` |
| B-11 | Exercise recovery card engine | Add `generate_exercise_recovery_card()` to `adaptive_engine.py`. 3-retry back-off, `gpt-4o`, `max_tokens=1200`, `timeout=30`. Parse into `LessonCard` with `is_recovery=True`. | 0.75 d | B-09, B-10 | `adaptive_engine.py` |
| B-12 | Wire two-path branch in `next_card()` | In `next_card()` handler: detect chunk type, branch to exercise or teaching path. Branch to recovery when `wrong_attempts >= 2` and `failed_exercise_question` is set. | 0.5 d | B-06, B-10, B-11 | `teaching_router.py` |
| B-13 | Wire exercise path in `chunk-cards` endpoint | In `generate_chunk_cards()` handler: detect chunk type via `_get_chunk_type()`; route exercise chunks to `build_exercise_card_prompt()` instead of the teaching card path. | 0.5 d | B-10 | `teaching_router.py` |

**Stage 2b total: ~6.25 dev-days**

---

### Stage 3 — Tests (comprehensive-tester)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| T-01 | Unit: chunk classifier | Test all six types + priority edge cases (section number beats exercise keyword, section number beats learning objective keyword). ~12 test cases. | 0.5 d | B-01 | `test_chunk_classification.py` |
| T-02 | Unit: `_is_optional_chunk` | True/false cases for all exercise heading variants. ~6 test cases. | 0.25 d | B-01 | `test_chunk_classification.py` |
| T-03 | Unit: exam gate deduplication | No existing gate → 1 gate appended. Existing gate → 0 gates appended. Empty chunk list → 0 gates appended. | 0.5 d | B-02 | `test_exam_gate.py` |
| T-04 | Unit: language propagation | `_translate_summaries_headings` success path (mock OpenAI). Timeout/error path returns original list. Cache bust logic sets `cache_version: -1`. | 0.5 d | B-07, B-08 | `test_language_propagation.py` |
| T-05 | Unit: exercise prompt builders | `build_exercise_card_system_prompt` contains language name. `build_exercise_recovery_prompt` user prompt contains wrong answer. Text truncated at 2000/1500 chars. | 0.5 d | B-09, B-10 | `test_exercise_prompts.py` |
| T-06 | Unit: `all_study_complete` exclusion | Optional chunks not in `teaching_ids`. Teaching + required exercise chunks in `teaching_ids`. | 0.25 d | B-04 | `test_chunk_completion.py` |
| T-07 | Integration: exercise chunk happy path | POST `/chunk-cards` for exercise chunk → response has 2 cards with `question` field set, `is_recovery=False`. | 0.75 d | B-13 | `test_exercise_flow.py` |
| T-08 | Integration: exercise recovery path | POST `/next-card` with `wrong_attempts=2` + `failed_exercise_question` → response card has `is_recovery=True`, `question.difficulty="EASY"`. | 0.75 d | B-12 | `test_exercise_flow.py` |
| T-09 | Integration: complete chunk item | POST `/chunks/{id}/complete` → `chunk_progress` updated. Second call → idempotent 200. Last chunk → `all_study_complete=true`. | 0.5 d | B-05 | `test_chunk_completion.py` |
| T-10 | Integration: Socratic endpoints removed | POST `/check` → 404/405. POST `/respond` → 404/405. | 0.25 d | S2a-01 | `test_socratic_removed.py` |
| T-11 | Integration: language change | PATCH `/language` → `translated_headings` list length matches chunk count. `session.presentation_text` has `cache_version: -1`. | 0.5 d | B-08 | `test_language_propagation.py` |

**Stage 3 total: ~5.25 dev-days**

---

### Stage 4 — Frontend (frontend-developer)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| F-01 | Add `completeChunkItem` API wrapper | Add `completeChunkItem(sessionId, chunkId)` to `sessions.js`. Remove `beginCheck` and `sendResponse` (if not already done in S2a-02). | 0.25 d | S2a-02 | `sessions.js` |
| F-02 | Add `LANGUAGE_CHANGED` reducer | Add `LANGUAGE_CHANGED` case to `SessionContext` reducer: update heading strings by index, clear `cards`, reset `currentCardIndex`. Add `CHUNK_ITEM_COMPLETE` reducer case. | 0.5 d | S2a-04 | `SessionContext.jsx` |
| F-03 | Wire language dispatch in StudentContext | Add `updateLanguage()` function: calls API, gets `translated_headings`, calls `i18n.changeLanguage()`, dispatches `LANGUAGE_CHANGED`. Wire `sessionDispatch` via prop. | 0.5 d | F-02 | `StudentContext.jsx` |
| F-04 | Update LearningPage chunk rendering | Render `learning_objective` and `section_review` as non-interactive panels (no click handler). Render `exercise` with "Practice" or "Optional" badge based on `is_optional`. | 0.75 d | none | `LearningPage.jsx` |
| F-05 | Add i18n keys for new UI strings | Add `learning.completeChunk`, `chunkType.learning_objective`, `chunkType.section_review`, `chunkType.exercise`, `chunkType.practice`, `chunkType.optional` to all 13 locale files. | 0.5 d | none | `locales/*.json` |
| F-06 | Complete button wiring in CardLearningView | Show "Complete" button on last card. On click: call `completeChunkItem()`, dispatch `CHUNK_ITEM_COMPLETE`, advance to next chunk. Disable button while in-flight. | 0.5 d | F-01, F-02, S2a-05 | `CardLearningView.jsx` |
| F-07 | Remove dead Socratic UI | Verify `SocraticChat.jsx` deleted. Verify no import of `beginCheck`/`sendResponse` anywhere. Remove any Socratic phase rendering from `LearningPage.jsx`. | 0.5 d | S2a-03, S2a-04 | `LearningPage.jsx`, `CardLearningView.jsx` |
| F-08 | Smoke test all 13 locales | Manually verify new i18n keys render correctly in at least en, ar (RTL), zh, hi. Automated: check all 13 locale files contain all new keys. | 0.25 d | F-05 | all locale files |

**Stage 4 total: ~3.75 dev-days**

---

## 2. Phased Delivery Plan

```
Stage 2a (Socratic Removal)     Stage 2b (Backend Main)
────────────────────────────    ──────────────────────────────────────
S2a-01  Remove backend routes   B-01  _get_chunk_type() overhaul
S2a-02  Remove frontend wrappers B-02  Exam gate dedup
S2a-03  Delete SocraticChat.jsx B-03  ChunkSummary.is_optional
S2a-04  Clean SessionContext     B-04  all_study_complete fix
S2a-05  Complete button UI       B-05  /chunks/{id}/complete endpoint
                                 B-06  NextCardRequest extension
        [parallel with 2b]       B-07  _translate_summaries_headings
                                 B-08  Language handler extension
                                 B-09  Exercise prompts.py
                                 B-10  Exercise prompt_builder.py
                                 B-11  generate_exercise_recovery_card
                                 B-12  next_card two-path branch
                                 B-13  chunk-cards exercise branch

Stage 3 (Tests)                  Stage 4 (Frontend)
────────────────────────────     ────────────────────────────────────
After 2a + 2b complete           After 2a complete (can start F-04/F-05
T-01 through T-11                in parallel with 2b)
```

### Phase timeline (2 engineers: 1 backend, 1 frontend)

| Day | Backend | Frontend |
|-----|---------|----------|
| 1 | B-01, B-02, B-03, B-04 | S2a-02, S2a-03, S2a-04 |
| 2 | B-05, B-06, B-07 | S2a-01 (collab with BE), F-04, F-05 |
| 3 | B-08, B-09 | F-01, F-02, F-03 |
| 4 | B-10, B-11 | F-06, F-07 |
| 5 | B-12, B-13, S2a-05 | F-08, begin integration review |
| 6 | T-01 through T-06 (unit tests) | Integration review, locale check |
| 7 | T-07 through T-11 (integration tests) | Bug fixes from test failures |
| 8 | Final review, bug fixes | Final review, bug fixes |

**Estimated total calendar time: ~8 days (2 engineers, parallel)**
**Total dev-days: 2.25 + 6.25 + 5.25 + 3.75 = 17.5 dev-days**

---

## 3. Dependencies and Critical Path

```
Critical path:
B-01 (_get_chunk_type) ──► B-02 (gate dedup) ──► T-03
     │                ──► B-03 (schema) ──► B-04 ──► B-05 ──► T-09
     │                ──► B-13 (chunk-cards branch)

B-09 (prompts) ──► B-10 (prompt_builder) ──► B-11 (recovery engine) ──► B-12 (next_card branch)
                                                                       ──► T-08

B-07 (translator) ──► B-08 (language handler) ──► T-11 ──► F-03

S2a-01 ──► T-10
S2a-03 ──► S2a-04 ──► F-02 ──► F-06
                   ──► F-03

Non-critical (parallelisable):
  F-04, F-05 can start Day 1 in parallel with all backend work
  T-01, T-02, T-06 can start as soon as B-01 is done
  T-04, T-05 can start as soon as B-07/B-09 are done
```

**Blocking external dependencies:** None. All work is within the existing codebase. No Alembic migration required. No new npm packages required.

**Risk item on critical path:** B-12 (two-path branch in `next_card`) depends on B-11 (recovery engine) which depends on B-09 and B-10. If LLM prompt tuning for exercise recovery cards requires multiple iterations, this extends the critical path by 1–2 days.

---

## 4. Definition of Done

### Stage 2a — Socratic Removal

- [ ] `POST /sessions/{id}/check` returns HTTP 404 (route deleted)
- [ ] `POST /sessions/{id}/respond` returns HTTP 404 (route deleted)
- [ ] `SocraticChat.jsx` file does not exist on disk
- [ ] No import of `SocraticChat` anywhere in the frontend codebase (`grep` passes)
- [ ] No import of `beginCheck` or `sendResponse` anywhere in the frontend codebase
- [ ] `SessionContext.jsx` contains no `CHECK_*` or `SOCRATIC_*` action types
- [ ] "Complete" button renders on the last card and triggers `completeChunkItem` API call
- [ ] `learning.completeChunk` i18n key present in all 13 locale files

### Stage 2b — Backend Main

- [ ] `_get_chunk_type("1.1 Introduction")` → `"section_review"`
- [ ] `_get_chunk_type("Learning Objectives")` → `"learning_objective"`
- [ ] `_get_chunk_type("Practice Makes Perfect")` → `"exercise"`
- [ ] `_get_chunk_type("Writing Exercises")` → `"exercise"` with `_is_optional_chunk("Writing Exercises")` → `True`
- [ ] `_get_chunk_type("Use Addition Notation")` → `"teaching"`
- [ ] `GET /sessions/{id}/chunks` returns exactly one `exercise_gate` row, always last
- [ ] `GET /sessions/{id}/chunks` returns `is_optional=True` for Writing Exercises chunks
- [ ] `POST /sessions/{id}/chunks/{id}/complete` is idempotent (second call returns 200 with same state)
- [ ] `PATCH /students/{id}/language` returns `translated_headings` list when an active session exists
- [ ] `PATCH /students/{id}/language` sets `cache_version: -1` in `presentation_text` JSONB
- [ ] `POST /sessions/{id}/next-card` with `failed_exercise_question` + `wrong_attempts=2` returns a card with `is_recovery=True`
- [ ] `POST /sessions/{id}/chunk-cards` for an exercise chunk returns cards with `question` field set
- [ ] All new code passes `flake8` / `mypy` (match existing project standards)
- [ ] No `print()` statements; all logging via `logger`

### Stage 3 — Tests

- [ ] All T-01 through T-11 pass
- [ ] No pre-existing tests broken
- [ ] Test file names follow existing `test_*.py` convention
- [ ] Integration tests use real DB (not mocks) per project convention

### Stage 4 — Frontend

- [ ] Chunk list shows non-interactive panel for `learning_objective` and `section_review` types (no click handler)
- [ ] Exercise chunks show "Practice" badge; Writing Exercises chunks show "Optional" badge
- [ ] Language change updates chunk headings in the UI without page reload
- [ ] Language change clears current card view and reloads cards in new language
- [ ] All 13 locale files contain all new i18n keys (automated check in T-11 or a separate locale completeness test)
- [ ] No hardcoded English strings in new JSX code (use `t()`)
- [ ] No `console.log` statements in committed code

---

## 5. Rollout Strategy

### Deployment approach
Feature flags are not used for this change set — the changes are structural (removing dead code and fixing classification bugs) rather than additive features that need gradual exposure.

**Deploy order:**
1. Deploy backend first (Stage 2a + 2b combined)
2. Verify `GET /sessions/{id}/chunks` returns correct types on a sample concept
3. Verify `PATCH /students/{id}/language` returns `translated_headings`
4. Deploy frontend (Stages S2a + 4)
5. Verify chunk list renders non-interactive panels correctly
6. Verify Complete button appears on last card

### Pre-deploy verification (DB check)
Before removing Socratic routes, run:
```sql
SELECT COUNT(*) FROM teaching_sessions WHERE phase = 'SOCRATIC' AND completed_at IS NULL;
```
If count > 0, those sessions will be stranded. Options: force-complete them via a one-time UPDATE, or deploy the frontend first (which no longer shows Socratic UI) and give students time to complete or abandon those sessions naturally before removing the backend routes.

### Rollback plan
- Backend rollback: `git revert` the router changes; Socratic routes can be re-added from git history within minutes
- Frontend rollback: `git revert` the frontend PR; `SocraticChat.jsx` can be restored from git history
- No DB migration to roll back (no schema changes)

### Post-launch validation
- [ ] Monitor `GET /sessions/{id}/chunks` response — verify `exercise_gate` count is exactly 1 per response
- [ ] Monitor error rate on `POST /sessions/{id}/chunks/{id}/complete` — should be < 0.1%
- [ ] Monitor `_translate_summaries_headings` warning logs — if > 5% of language-change calls fail translation, investigate OpenAI timeout configuration
- [ ] Verify `SocraticChat` component is not referenced in any browser network requests or error logs

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|-------------------|
| Stage 2a — Socratic Removal | Remove check/respond routes; delete SocraticChat.jsx; clean SessionContext; add Complete button | 2.25 dev-days | 1 backend + 1 frontend (parallel) |
| Stage 2b — Backend Main | Chunk classifier overhaul; exam gate fix; language propagation; exercise card generation; recovery cards | 6.25 dev-days | 1 backend |
| Stage 3 — Tests | 11 test functions across unit + integration | 5.25 dev-days | 1 tester (can overlap with Stage 4) |
| Stage 4 — Frontend | API wrappers; reducer; language dispatch; chunk list rendering; locale keys | 3.75 dev-days | 1 frontend |
| **Total** | | **17.5 dev-days** | **2 engineers (8 calendar days)** |

---

## Key Decisions Requiring Stakeholder Input

1. **Socratic endpoint removal vs 410 deprecation:** This plan removes the routes immediately. If any external clients (e.g. automated test scripts, demo scripts) still call `/check` or `/respond`, they will break silently. Recommend: search all test and script files for these endpoint strings before merge.

2. **Pre-deploy session cleanup:** If active Socratic sessions exist at deploy time, they must be handled (force-complete or allow natural expiry). Confirm with product whether a one-time DB update is acceptable.

3. **Exercise chunk exam gating:** This plan requires students to complete all non-optional exercise chunks before the exam gate unlocks. If this is too strict for the first release, the `all_study_complete` logic can be limited to `teaching` chunks only (reverting exercise chunks to non-gating) by a single-line config change in the `teaching_ids` set comprehension.

4. **i18n translation quality:** Machine translation of chunk headings via `gpt-4o-mini` may produce inconsistent terminology (e.g. different Spanish translations for "Practice Makes Perfect" across sessions). If consistency is critical, consider a fixed translation dictionary for known heading patterns instead of LLM translation.
