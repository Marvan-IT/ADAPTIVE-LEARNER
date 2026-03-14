# Execution Plan — Enhanced Adaptive Flashcard System

**Feature slug:** `adaptive-flashcard-system`
**Date:** 2026-03-10
**Author:** solution-architect agent
**Status:** Approved for implementation

---

## 1. Work Breakdown Structure (WBS)

### Phase 0 — Infrastructure (devops-engineer)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| P0-01 | Verify DB models match migration intent | Read `backend/src/db/models.py` to confirm all 11 `students` columns and 3 `card_interactions` columns are present in the ORM model | 0.5d | — | `db/models.py` |
| P0-02 | Write Alembic migration `005_add_adaptive_history_columns` | Generate migration script that adds all 14 new columns with correct PostgreSQL types, defaults, and `ADD COLUMN IF NOT EXISTS` guards for safety | 1.0d | P0-01 | `alembic/versions/005_*.py` |
| P0-03 | Test migration on clone of schema | Run `alembic upgrade head` on a fresh DB and on a DB with data; verify no data loss, column defaults correct | 0.5d | P0-02 | DB infrastructure |
| P0-04 | Add new constants to `config.py` | Add `ADAPTIVE_COLD_START_SECTION_THRESHOLD`, `ADAPTIVE_COLD_START_CURRENT_WEIGHT`, `ADAPTIVE_COLD_START_HISTORY_WEIGHT`, `ADAPTIVE_STATE_EMA_ALPHA`, `BOREDOM_SIGNAL_COOLDOWN_CARDS`, `BOREDOM_AUTOPILOT_WINDOW`, `BOREDOM_AUTOPILOT_SIMILARITY_THRESHOLD` | 0.5d | — | `config.py` |
| P0-05 | Create `pytest` fixtures for new schema columns | Update `backend/tests/conftest.py` to include the 14 new columns in the test student/card-interaction factory helpers | 0.5d | P0-02 | `tests/conftest.py` |

**Phase 0 total estimated effort: 3 days**

---

### Phase A — DB Schema + History Loading (backend-developer)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| A-01 | Extend `load_student_history()` to read new columns | Add queries for `avg_state_score`, `section_count`, `effective_engagement`, `ineffective_engagement`, `boredom_pattern` from the `students` row; use `getattr(..., default)` guards for migration safety | 1.0d | P0-02, P0-04 | `adaptive/adaptive_engine.py` |
| A-02 | Implement cold-start weight selection in `build_blended_analytics()` | Replace the hard-coded `has_history` check with `section_count < ADAPTIVE_COLD_START_SECTION_THRESHOLD`; apply cold-start weights when condition is true | 0.5d | A-01, P0-04 | `adaptive/adaptive_engine.py` |
| A-03 | Add `SectionCompleteRequest` and `SectionCompleteResponse` Pydantic schemas | Write both models per DLD §2.2 spec; include field validators for `blended_state_score` range, `strategy_applied` Literal, `concept_index` ge=0 | 0.5d | P0-04 | `api/teaching_schemas.py` |
| A-04 | Implement `_persist_section_complete()` private method in `TeachingService` | DB update using `SELECT ... FOR UPDATE` + EMA computation + JSONB list append for engagement memory; use `ADAPTIVE_STATE_EMA_ALPHA` constant | 1.5d | A-01, A-03 | `api/teaching_service.py` |
| A-05 | Add `POST /api/v2/sessions/{session_id}/section-complete` route | Wire `SectionCompleteRequest` → `TeachingService._persist_section_complete()` → `SectionCompleteResponse`; include 404 guard on session lookup | 0.5d | A-03, A-04 | `api/teaching_router.py` |
| A-06 | Update `load_student_history()` return dict type hint and docstring | Ensure the return dict is fully documented with the new keys | 0.25d | A-01 | `adaptive/adaptive_engine.py` |

**Phase A total estimated effort: 4.25 days**

---

### Phase B — Numeric State Blending (backend-developer)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| B-01 | Implement `compute_numeric_state_score(speed, comprehension) -> float` | Pure function with `_NUMERIC_STATE_MAP` dict per DLD §2.4; add module-level docstring | 0.25d | P0-04 | `adaptive/adaptive_engine.py` |
| B-02 | Implement `blended_score_to_generate_as(blended_score) -> str` | Pure function with threshold chain per DLD §2.4 | 0.25d | B-01 | `adaptive/adaptive_engine.py` |
| B-03 | Refactor `build_blended_analytics()` to return `tuple[AnalyticsSummary, float, str]` | Call `compute_numeric_state_score()` for current signals and for history baseline; apply weights; call `blended_score_to_generate_as()`; return extended tuple | 1.0d | A-02, B-01, B-02 | `adaptive/adaptive_engine.py` |
| B-04 | Thread `blended_state_context` through `generate_next_card()` | Destructure the new tuple; assemble `blended_state_context` dict and pass to `build_next_card_prompt()` | 0.5d | B-03 | `adaptive/adaptive_engine.py` |
| B-05 | Inject `STUDENT STATE` block in `_build_system_prompt()` | Add optional `blended_state_context: dict | None` parameter; when present, append `STUDENT STATE` section with numeric score, generate_as label, history average, and blend weights | 0.75d | B-04 | `adaptive/prompt_builder.py` |
| B-06 | Inject `COVERAGE CONTEXT` block in `_build_user_prompt()` | Add optional `coverage_context: dict | None` parameter; when present, append `COVERAGE CONTEXT` block with concept_index, concepts_remaining, images_used; format as numbered checklist | 0.75d | B-04 | `adaptive/prompt_builder.py` |
| B-07 | Update `build_adaptive_prompt()` and `build_next_card_prompt()` signatures | Thread the two new optional dict parameters through the public API functions | 0.25d | B-05, B-06 | `adaptive/prompt_builder.py` |

**Phase B total estimated effort: 3.75 days**

---

### Phase C — Concept Tracking (backend-developer)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| C-01 | Track `concept_index` and `images_used_this_section` in `teaching_service.py` | Add a session-scoped counter dict keyed by `session_id` (or pass as params); update `concept_index` on each card generation call within a section | 1.0d | B-06 | `api/teaching_service.py` |
| C-02 | Compute `concepts_remaining` from session metadata | Use `total_concepts` from `SectionCompleteRequest` and `concept_index`; pass to `build_next_card_prompt()` coverage_context | 0.5d | C-01, A-05 | `api/teaching_service.py` |
| C-03 | Populate `images_used_this_section` from image resolution log | Count image hits from `get_concept_images()` responses during this section; thread the count into the coverage context | 0.5d | C-01 | `api/knowledge_service.py`, `api/teaching_service.py` |

**Phase C total estimated effort: 2 days**

---

### Phase D — Boredom Detection (backend-developer + frontend-developer)

#### Backend sub-phase

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| D-01 | Create `backend/src/adaptive/boredom_detector.py` | Implement `detect_boredom_signal()`, `detect_autopilot_pattern()`, and `select_engagement_strategy()` per DLD §1.1 and §2.5 spec; use Python stdlib `re` and `difflib.SequenceMatcher` | 1.5d | P0-04 | `adaptive/boredom_detector.py` (NEW) |
| D-02 | Add `engagement_signal: str | None` to `NextCardRequest` | Optional field with `max_length=50` validator | 0.25d | A-03 | `api/teaching_schemas.py` |
| D-03 | Wire boredom strategy into `generate_next_card()` | After building analytics, check `signals.engagement_signal`; call `select_engagement_strategy()`; pass result to `build_next_card_prompt()`; wrap in try/except per DLD §8.1 | 0.75d | D-01, D-02, B-07 | `adaptive/adaptive_engine.py` |
| D-04 | Inject engagement strategy block in `build_next_card_prompt()` | Add optional `engagement_strategy: str | None` parameter; when not None, append named strategy block (e.g., `GAMIFY MODE: introduce a point-scoring element or beat-your-score challenge`) | 0.75d | D-01 | `adaptive/prompt_builder.py` |
| D-05 | Define 4 strategy prompt blocks as constants in `prompt_builder.py` | One block per strategy: GAMIFY (game mechanic), CHALLENGE (harder variant), STORY (narrative wrapper), BREAK_SUGGESTION (gentle suggestion text) | 0.5d | D-04 | `adaptive/prompt_builder.py` |

#### Frontend sub-phase

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| D-06 | Add keyword boredom detection in `SocraticChat.jsx` | After `handleSend()`, check user message against keyword list (`boring`, `already know`, `skip`, `too easy`, `going too slow`); set `boredomDetected` state | 0.5d | — | `SocraticChat.jsx` |
| D-07 | Add `pendingEngagementSignal` to `SessionContext.jsx` state | New state field; set to `"BORED_TEXT"` when `SocraticChat` reports boredom; cleared after `completeCard()` sends it | 0.5d | D-06 | `context/SessionContext.jsx` |
| D-08 | Pass `engagement_signal` in `completeCard()` API call | Read `state.pendingEngagementSignal` before calling `sessions.completeCard()`; include in request body if non-null | 0.5d | D-07 | `context/SessionContext.jsx` |
| D-09 | Add `sectionComplete()` function to `sessions.js` | Axios POST wrapper for `/api/v2/sessions/${sessionId}/section-complete` | 0.25d | A-05 | `api/sessions.js` |
| D-10 | Add `SECTION_COMPLETE` action and dispatch in `SessionContext.jsx` | Dispatch when `currentCardIndex === cards.length - 1` and user advances; guard with `sectionCompleteSentRef`; call `sessions.sectionComplete()` | 1.0d | D-07, D-09, A-05 | `context/SessionContext.jsx` |
| D-11 | Add i18n strings for boredom-related UI copy | Add `"boredom.breakSuggestion"`, `"boredom.challengePrompt"` keys to all 13 locale files | 0.5d | D-06 | `locales/*.json` (13 files) |

**Phase D total estimated effort: 7 days (5d backend, 3.25d frontend, with overlap)**

---

### Phase E — Tests (comprehensive-tester)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| E-01 | Write `test_adaptive_numeric_scoring.py` | 6 unit tests for `compute_numeric_state_score()` and `blended_score_to_generate_as()` per DLD §9.1 | 1.0d | B-01, B-02 | `tests/test_adaptive_numeric_scoring.py` (NEW) |
| E-02 | Write `test_boredom_detector.py` | 11 unit tests for all three `boredom_detector.py` functions per DLD §9.1 | 1.5d | D-01 | `tests/test_boredom_detector.py` (NEW) |
| E-03 | Write `test_section_complete_endpoint.py` | 7 integration tests for the section-complete endpoint per DLD §9.2 | 2.0d | A-05, P0-05 | `tests/test_section_complete_endpoint.py` (NEW) |
| E-04 | Extend `test_build_blended_analytics.py` (if it exists) or write new | Cover cold-start weight selection, numeric blending math, and generate_as label generation | 1.0d | A-02, B-03 | `tests/test_adaptive_engine.py` |
| E-05 | Extend prompt builder tests for new blocks | Verify STUDENT STATE block is present in system prompt when `blended_state_context` is provided; verify COVERAGE CONTEXT block format in user prompt | 1.0d | B-05, B-06 | `tests/test_prompt_builder.py` |
| E-06 | Run full regression suite and fix any failures | Run all 93+ tests; investigate and fix any failures caused by the new code | 1.5d | All above | All test files |
| E-07 | Performance benchmark for section-complete endpoint | Use `httpx` async client to fire 10 concurrent section-complete requests; verify p95 < 200 ms | 0.5d | E-03 | `tests/test_performance.py` |

**Phase E total estimated effort: 8.5 days**

---

## 2. Phased Delivery Plan

### Phase 0 — Infrastructure (devops-engineer)
**Goal:** Database schema is ready and test infrastructure extended before any business logic is written.

**Deliverables:**
- `alembic/versions/005_add_adaptive_history_columns.py` — migration script
- `config.py` — 7 new constants added
- `tests/conftest.py` — fixtures updated

**Acceptance criteria:**
- `alembic upgrade head` runs without errors on a clean DB
- `alembic downgrade -1` rolls back all new columns cleanly
- `pytest backend/tests/` passes all 93 existing tests with the updated conftest

---

### Phase A — DB Schema + History (backend-developer)
**Goal:** The existing `load_student_history()` reads the new columns; the section-complete endpoint exists and persists data correctly.

**Deliverables:**
- `adaptive/adaptive_engine.py` — extended `load_student_history()` + `build_blended_analytics()` cold-start logic
- `api/teaching_schemas.py` — `SectionCompleteRequest`, `SectionCompleteResponse`
- `api/teaching_service.py` — `_persist_section_complete()`
- `api/teaching_router.py` — `POST /sessions/{id}/section-complete`

**Acceptance criteria:**
- `GET /api/v2/students/{id}` still works (no regression in student endpoint)
- `POST /section-complete` with a valid session returns 200 with correct `updated_section_count`
- Calling `section-complete` twice does not double-increment `section_count` (optimistic lock test)
- All Phase 0 tests still green

---

### Phase B — Numeric State Blending (backend-developer)
**Goal:** The blending pipeline produces numeric scores and the LLM receives STUDENT STATE and COVERAGE CONTEXT blocks.

**Deliverables:**
- `adaptive/adaptive_engine.py` — `compute_numeric_state_score()`, `blended_score_to_generate_as()`, refactored `build_blended_analytics()`
- `adaptive/prompt_builder.py` — extended `_build_system_prompt()` and `_build_user_prompt()`

**Acceptance criteria:**
- `compute_numeric_state_score("NORMAL", "OK")` returns `2.0` (smoke test)
- A card generation call with known inputs produces a system prompt containing `STUDENT STATE:` block
- A card generation call with coverage context set produces a user prompt containing `COVERAGE CONTEXT:` block
- No change in the `NextCardResponse` schema — existing clients unaffected

---

### Phase C — Concept Tracking (backend-developer)
**Goal:** The per-section concept_index and images_used counters are threaded through correctly.

**Deliverables:**
- `api/teaching_service.py` — concept tracking state
- `api/knowledge_service.py` — image count plumbing

**Acceptance criteria:**
- A two-section lesson produces `concept_index=0` on first section, `concept_index=1` on second
- `images_used_this_section` resets to 0 at the start of each new section
- `concepts_remaining` decreases correctly as sections are completed

---

### Phase D — Boredom Detection (backend-developer + frontend-developer)
**Goal:** The full boredom detection and engagement strategy pipeline is operational end-to-end.

**Deliverables:**
- `adaptive/boredom_detector.py` (NEW)
- `adaptive/prompt_builder.py` — 4 strategy blocks, `engagement_strategy` parameter
- `adaptive/adaptive_engine.py` — strategy injection with error isolation
- `api/teaching_schemas.py` — `NextCardRequest.engagement_signal`
- `frontend/src/components/learning/SocraticChat.jsx` — keyword detection
- `frontend/src/context/SessionContext.jsx` — `pendingEngagementSignal`, `SECTION_COMPLETE`
- `frontend/src/api/sessions.js` — `sectionComplete()` function
- `frontend/src/locales/*.json` — 2 new keys in 13 files

**Acceptance criteria:**
- Typing "this is boring" in Socratic chat causes the next card request to include `engagement_signal: "BORED_TEXT"`
- The next card's system prompt contains the GAMIFY or CHALLENGE strategy block
- If `select_engagement_strategy()` throws, card generation continues normally (no 500 error)
- `SECTION_COMPLETE` is dispatched exactly once per section boundary (not on card-by-card advance)
- `sectionComplete()` is not called when `sectionCompleteSentRef` is already true

---

### Phase E — Tests and Hardening (comprehensive-tester)
**Goal:** Full test coverage for all new code; all 93 existing tests green; performance benchmark passing.

**Deliverables:**
- `tests/test_adaptive_numeric_scoring.py` (NEW)
- `tests/test_boredom_detector.py` (NEW)
- `tests/test_section_complete_endpoint.py` (NEW)
- Extended `tests/test_adaptive_engine.py`
- Extended `tests/test_prompt_builder.py`
- Performance benchmark results

**Acceptance criteria:**
- `pytest backend/tests/` — 0 failures, 0 errors
- All 11 `test_boredom_detector.py` tests pass without mocking
- p95 latency for section-complete endpoint < 200 ms at 10 concurrent requests
- Zero test modifications to pre-existing test assertions

---

## 3. Dependencies and Critical Path

```
P0-01 ──► P0-02 ──► P0-03
P0-04 ──────────────────────────────────────────────────────────────►  A-01
P0-02 ──► P0-05 ─────────────────────────────────────────────────────► E-03

P0-04 ──► A-01 ──► A-02 ──► B-03 ──► B-04 ──► B-05 ──► B-07 ──► D-04
P0-02 ──► A-03 ──► A-04 ──► A-05
B-01 ──► B-02 ──► B-03
B-03 ──► B-04 ──► D-03
B-05 ──► B-06 ──► B-07

D-01 ──► D-03 ──► (generate_next_card complete)
D-01 ──► D-02 ──► D-03
D-01 ──► D-04 ──► D-05

D-06 ──► D-07 ──► D-08 ──► D-10
D-09 ──► D-10
A-05 ──► D-09

B-01 ──► E-01
D-01 ──► E-02
A-05 ──► E-03
B-03 ──► E-04
B-05 ──► B-06 ──► E-05
E-01..E-05 ──► E-06 ──► E-07
```

**Critical path (longest dependency chain):**
```
P0-04 → A-01 → A-02 → B-03 → B-04 → B-05/B-06 → B-07 → D-04/D-05 → E-05 → E-06
```

Estimated critical path duration: **~10 working days** (assuming 1 developer on critical path tasks sequentially).

**Blocking dependencies on external teams:**
- `P0-02` (Alembic migration) blocks all backend phases. devops-engineer must complete this before backend-developer can write code that queries new columns.
- `A-05` (section-complete endpoint) blocks `D-09` and `D-10` on the frontend side. Frontend cannot implement the `SECTION_COMPLETE` action until the backend route exists.
- `D-06` through `D-10` (frontend boredom) can be developed in parallel with backend Phase B and C, as long as the `sessions.js` and `SessionContext` changes use the final schema from `A-03`.

---

## 4. Definition of Done (DoD)

### Phase 0 DoD
- [ ] `alembic upgrade head` on fresh DB: 0 errors
- [ ] `alembic downgrade -1` on populated DB: 0 errors, no data loss
- [ ] `config.py` contains all 7 new constants with comments
- [ ] `conftest.py` updated and all existing tests still pass
- [ ] Migration reviewed by solution-architect for correct PostgreSQL types and defaults

### Phase A DoD
- [ ] `load_student_history()` returns `avg_state_score`, `section_count`, `effective_engagement`, `ineffective_engagement` keys
- [ ] `POST /section-complete` returns 200 for valid input, 404 for missing session, 401 for missing auth key
- [ ] EMA computation in `_persist_section_complete()` verified with a manual calculation in test
- [ ] Engagement memory arrays populated correctly for both `strategy_effective=True` and `False`
- [ ] No changes to existing `/complete-card` response format
- [ ] All 93 pre-existing tests green

### Phase B DoD
- [ ] `compute_numeric_state_score()` passes the 9-cell unit test table
- [ ] `blended_score_to_generate_as()` passes all boundary tests
- [ ] `build_blended_analytics()` returns a 3-tuple (not the previous single AnalyticsSummary)
- [ ] System prompt contains `STUDENT STATE:` block when `blended_state_context` dict provided
- [ ] User prompt contains `COVERAGE CONTEXT:` block when `coverage_context` dict provided
- [ ] Callers of the old single-return `build_blended_analytics()` updated (no `TypeError` at runtime)
- [ ] All 93 pre-existing tests green

### Phase C DoD
- [ ] `concept_index` increments correctly across multi-section sessions
- [ ] `images_used_this_section` resets to 0 at section start
- [ ] `concepts_remaining` is never negative
- [ ] Integration test confirms correct values in LLM prompt

### Phase D DoD
- [ ] `boredom_detector.py` has no imports outside Python stdlib
- [ ] All 11 unit tests in `test_boredom_detector.py` pass
- [ ] End-to-end manual test: type "this is boring" → next card prompt contains strategy block
- [ ] `SocraticChat.jsx` keyword list confirmed with product team (list is configurable via constants)
- [ ] `SECTION_COMPLETE` action fires at most once per section (logged and confirmed)
- [ ] All 13 locale files contain new i18n keys
- [ ] Frontend builds without TypeScript/lint errors (`npm run build` clean)
- [ ] All 93 pre-existing tests green

### Phase E DoD
- [ ] `pytest backend/tests/ -v` — 0 failures, 0 errors
- [ ] Test count increased from 93 to at least 115 (22+ new tests)
- [ ] No test uses `# noqa` or skips to work around new behavior
- [ ] Performance benchmark: section-complete p95 < 200 ms at 10 concurrency
- [ ] Code review completed by at least one other agent (backend-developer reviews test logic)

---

## 5. Rollout Strategy

### Deployment Approach

**Feature flag:** Wrap the numeric blending logic behind a config flag `ADAPTIVE_NUMERIC_BLENDING_ENABLED: bool = True` in `config.py`. Setting it to `False` restores the pre-feature behavior (purely label-based, current weights). This allows a same-binary rollback without a code deployment.

```python
# In build_blended_analytics():
if ADAPTIVE_NUMERIC_BLENDING_ENABLED:
    current_score = compute_numeric_state_score(speed, comprehension)
    # ... numeric blending path
else:
    # ... legacy label-based path (existing code)
```

**Deployment order:**
1. devops-engineer runs `alembic upgrade head` on production DB (adds columns with safe defaults)
2. Backend service deployed (new code, numeric blending enabled)
3. Frontend deployed (new `sectionComplete()` call, boredom detection)
4. Monitor for 24 hours; check error rate on `/section-complete`

**No blue/green required** because all DB changes are additive (new nullable columns) and the feature flag provides instant rollback.

---

### Rollback Plan

| Scenario | Rollback Action |
|----------|----------------|
| Numeric blending produces incorrect profiles | Set `ADAPTIVE_NUMERIC_BLENDING_ENABLED=False` in `.env`; restart uvicorn (no redeploy) |
| Section-complete endpoint 500-errors | Frontend `SessionContext` already silently catches failures; backend errors logged only; no user impact |
| Boredom detection false-positives impacting quality | Remove `engagement_signal` from `completeCard()` payload in `sessions.js` (single-line change) |
| Alembic migration breaks production DB | Run `alembic downgrade -1`; all new columns dropped cleanly (IF NOT EXISTS guards prevent partial-apply issues) |

---

### Monitoring and Alerting for Launch

| Signal | Expected behavior | Alert if |
|--------|-------------------|----------|
| `/section-complete` error rate | < 0.5% of calls | > 1% in any 5-minute window |
| `avg_state_score` distribution | Centered around 2.0 for new students | Mean below 1.5 or above 3.5 after 100+ students |
| `boredom_detected` rate | 5–15% of Socratic messages | > 30% (indicates false-positive spike) |
| `strategy_effective` ratio | > 50% of applied strategies | < 30% sustained for 24 hours |
| Card generation latency p95 | Unchanged from pre-feature (< 3s) | p95 > 5s |

---

### Post-Launch Validation Steps

1. **Day 1:** Verify `section_count` is incrementing in the `students` table for active users.
2. **Day 1:** Confirm `avg_state_score` values are non-zero and within [0.0, 4.0] bounds.
3. **Day 3:** Check that `effective_engagement` and `ineffective_engagement` arrays are populating for students who have triggered boredom detection.
4. **Week 1:** Compare mastery rates between students who went through the cold-start regime (section_count < 3) and those who graduated; flag if cold-start students show lower mastery rates (may indicate over-scaffolding from 80/20 weighting).
5. **Week 2:** Run A/B analysis if feasible: numeric-blended groups vs pre-feature students (cohort comparison using `created_at` on `students` table).

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Phase 0 — Infrastructure | Alembic migration 005, config.py constants, conftest fixtures | 3 days | devops-engineer (1) |
| Phase A — DB Schema + History | load_student_history() extension, section-complete endpoint, EMA persistence | 4.25 days | backend-developer (1) |
| Phase B — Numeric Blending | compute_numeric_state_score, blended_score_to_generate_as, prompt builder STUDENT STATE + COVERAGE CONTEXT | 3.75 days | backend-developer (1) |
| Phase C — Concept Tracking | concept_index/images_used threading in teaching_service | 2 days | backend-developer (1) |
| Phase D — Boredom Detection | boredom_detector.py (new), strategy prompt blocks, frontend keyword detection, SessionContext SECTION_COMPLETE, i18n | 7 days | backend-developer (1) + frontend-developer (1), parallel work |
| Phase E — Tests | 22+ new tests, regression suite, performance benchmark | 8.5 days | comprehensive-tester (1) |
| **Total** | | **~28.5 dev-days** | 4 agents (some parallel) |

**Parallel execution estimate (calendar days):**
- P0 (3d) + A (4.25d) runs sequentially: 7.25 days
- B (3.75d) + C (2d) + D-backend (5d) can overlap significantly with A on separate tasks: adds ~6 days
- D-frontend (3.25d) runs in parallel with D-backend: no additional calendar days if resources allow
- E (8.5d) begins after all implementation phases: 8.5 days

**Estimated calendar time with 4 parallel agents: ~17 working days (3.5 weeks)**

---

## Key Decisions Requiring Stakeholder Input

1. **Feature flag default:** Should `ADAPTIVE_NUMERIC_BLENDING_ENABLED` default to `True` (immediately active) or `False` (opt-in) at first deployment? Defaulting to `False` is safer but means the feature is never active unless someone changes the env var.

2. **Phase ordering:** Phases A, B, C, D-backend could all be developed by a single backend developer sequentially. Should this be assigned to one person for continuity, or split between two backend developers (A+C for developer 1, B+D for developer 2)?

3. **i18n scope for D-11:** Adding 2 keys to 13 locale files requires translations in Arabic, Tamil, Sinhala, Malayalam, Hindi, French, Spanish, Chinese, Japanese, German, Korean, and Portuguese. Should placeholder English strings be used initially with proper translations added in a follow-up sprint?

4. **Cold-start section threshold tuning:** The design uses `section_count >= 3`. After the first 200 students, analyze whether 3 is too low (insufficient calibration) or too high (cold-start weights applied too long). Plan a config update sprint for 4 weeks post-launch.

---

## Phase F — Output Quality & Runtime Enforcement (2026-03-10)

### Motivation

Real student testing revealed cards are still missing content and arriving out of order despite Phase E prompt rules. Root causes identified:

1. **Stale cache** — existing sessions are served cards generated under older prompt versions (cache version 4 and below), bypassing all new prompt rules.
2. **LLM non-compliance** — the LLM occasionally skips sections or reorders cards despite explicit instructions. No post-generation validation existed to catch and repair these violations.
3. **Vague STUDENT STATE instructions** — the STUDENT STATE prompt block described general tendencies but provided no concrete branching rules, resulting in near-identical card content across different learner profiles.
4. **OVERWHELMED bug** — `select_engagement_strategy()` did not accept an `engagement` parameter, meaning the function could not distinguish an OVERWHELMED student from a merely bored one and incorrectly applied `challenge_bump` strategies.
5. **Strategy effectiveness feedback gap** — the `effective_engagement` and `ineffective_engagement` Student columns were defined in the schema but were never written to after a strategy was applied.

### Changes

| Fix | Description | File(s) |
|-----|-------------|---------|
| G | Bump `_CARDS_CACHE_VERSION` to `5` — forces fresh card generation for all existing sessions, invalidating cards produced under all previous prompt versions | `teaching_service.py` |
| E | Add `validate_and_repair_cards()` — post-generation runtime enforcement of coverage (all sections present), ordering (section_id sort), and deduplication (fingerprint-based); repairs or logs violations rather than raising | `teaching_service.py` |
| F | Audit all card-serving code paths: batch generation, adaptive single-card, cache retrieval, and frontend queue ordering; apply `validate_and_repair_cards()` consistently at the single output point | `teaching_service.py`, `SessionContext.jsx` |
| A | Expand STUDENT STATE block in `build_cards_system_prompt()` — replace vague tendency descriptions with concrete per-profile branching rules; add PROFILE MODIFIERS block listing exact adjustments (pacing, scaffolding depth, example density) | `prompts.py` |
| B | Expand STUDENT STATE block in `build_next_card_prompt()` — same concrete branching rules; preserve existing SLOW/FAST/BORED mode blocks; ensure STUDENT STATE takes priority when contradictions arise | `prompt_builder.py` |
| C | Fix OVERWHELMED bug — add `engagement: str \| None` parameter to `select_engagement_strategy()`; guard `challenge_bump` strategy selection to never fire when `engagement == "OVERWHELMED"`; default to `micro_break` strategy for overwhelmed state | `boredom_detector.py`, `adaptive_engine.py` |
| D | Wire strategy effectiveness feedback — implement `_update_strategy_effectiveness()` private method in `TeachingService`; call after each `completeCard()` when `strategy_applied` is set; write to `effective_engagement` and `ineffective_engagement` Student columns using list-append DB update | `teaching_service.py`, `teaching_router.py` |

### WBS — Phase F Tasks

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| F-01 | Bump cache version to 5 | Change `_CARDS_CACHE_VERSION = 4` to `5` in `teaching_service.py`; verify all cache-check branches reference the constant (not a hardcoded literal) | 0.25d | — | `api/teaching_service.py` |
| F-02 | Implement `validate_and_repair_cards()` | Pure function: accepts list of card dicts + expected section list; checks coverage (flags missing sections), sorts by `section_id`, deduplicates by `(section_id, card_type, question_text[:60])` fingerprint; returns repaired list + repair log | 1.5d | F-01 | `api/teaching_service.py` |
| F-03 | Apply validation at all output points | Identify every code path that returns cards to the caller (batch return, cache hit, single-card append); wrap each with `validate_and_repair_cards()`; add structured log line `cards.validation: repaired=%d, missing=%d, dupes=%d` | 1.0d | F-02 | `api/teaching_service.py`, `context/SessionContext.jsx` |
| F-04 | Expand STUDENT STATE in `build_cards_system_prompt()` | Replace the 2-sentence tendency block with 6-line concrete rules per profile: SLOW_STRUGGLING (max 1 card per section, heavy scaffolding, worked example every card), SLOW_OK (1–2 cards, moderate scaffolding), NORMAL_OK (2–3 cards, standard), NORMAL_STRONG (2–3 cards, minimal scaffolding), FAST_STRONG (1–2 cards, challenge variant); add PROFILE MODIFIERS block | 1.0d | — | `api/prompts.py` |
| F-05 | Expand STUDENT STATE in `build_next_card_prompt()` | Mirror F-04 rules in the single-card prompt; ensure STUDENT STATE section appears before COVERAGE CONTEXT and BOREDOM STRATEGY blocks so the model processes it first | 0.75d | F-04 | `adaptive/prompt_builder.py` |
| F-06 | Fix `select_engagement_strategy()` OVERWHELMED bug | Add `engagement: str \| None = None` parameter; add guard at top of function: `if engagement == "OVERWHELMED": return "BREAK_SUGGESTION"`; update all call sites in `adaptive_engine.py` to pass the student engagement field | 0.5d | — | `adaptive/boredom_detector.py`, `adaptive/adaptive_engine.py` |
| F-07 | Implement `_update_strategy_effectiveness()` | Private async method in `TeachingService`; called from `complete_card()` route handler when `strategy_applied` field is present in the card interaction; appends to `effective_engagement` (JSONB array) if `was_effective=True`, else `ineffective_engagement`; uses `SELECT ... FOR UPDATE` to prevent concurrent list corruption | 1.5d | — | `api/teaching_service.py`, `api/teaching_router.py` |

**Phase F total estimated effort: 6.5 days**

### Deployment Order

Execute fixes in this sequence to minimize risk:

1. **Fix G (F-01 cache v5)** — deploy first, standalone. Invalidates all stale cached cards immediately. No logic change; zero risk.
2. **Fix E + F (F-02 + F-03 validation + path audit)** — deploy as a unit. Provides the runtime safety net before prompt changes go out. Cards are now validated at every exit point regardless of which code path produced them.
3. **Fix A + B (F-04 + F-05 expanded STUDENT STATE)** — deploy after validation is live. LLM instruction quality improvement. If the LLM still violates rules, the validator catches it.
4. **Fix C + D (F-06 + F-07 OVERWHELMED + strategy feedback)** — deploy last. Behavioral correctness fix with DB writes; can be rolled back independently via the feature flag.

### Test Coverage Added

| Group | Test Count | Coverage |
|-------|-----------|---------|
| Group 25 | 6 | 6-persona blended score to `generate_as` label mapping — full coverage of all threshold boundaries |
| Group 26 | 4 | OVERWHELMED protection: assert `select_engagement_strategy(engagement="OVERWHELMED")` always returns `"BREAK_SUGGESTION"` regardless of other signals |
| Group 27 | 5 | Strategy effectiveness feedback loop: after `strategy_applied=True` card completion, assert `effective_engagement` list gains an entry; after `False`, assert `ineffective_engagement` gains an entry |
| Group 28 | 8 | `validate_and_repair_cards()` unit tests: empty input, missing section, out-of-order sections, duplicate cards, all-valid input, partial-duplicate input, missing `section_id` field (inference fallback), single-card input |
| Group 29 | 6 | Code path coverage: batch path, cache-hit path, single-card adaptive path, and frontend ordering all produce validated output; section sort is stable for equal `section_id` values |

**Total new tests: 29 across 5 groups.** Combined with the 22+ tests from Phase E, the test suite grows from 93 to at least 144 tests.

### Definition of Done — Phase F

- [ ] `_CARDS_CACHE_VERSION` is `5` in `teaching_service.py` and confirmed as the only cache-version constant (no duplicate)
- [ ] `validate_and_repair_cards()` is called at every code path that returns cards; confirmed via log line `cards.validation:` appearing in uvicorn logs for all card-serving endpoints
- [ ] STUDENT STATE block in `build_cards_system_prompt()` contains at least 5 distinct profile branches with concrete numeric guidance (card count per section, scaffolding level)
- [ ] STUDENT STATE block in `build_next_card_prompt()` mirrors the same rules
- [ ] `select_engagement_strategy(engagement="OVERWHELMED")` returns `"BREAK_SUGGESTION"` — unit test passes without mocking
- [ ] `_update_strategy_effectiveness()` writes to both `effective_engagement` and `ineffective_engagement` columns — confirmed via DB inspection after test run
- [ ] All 29 new Group 25–29 tests pass
- [ ] Full regression: `pytest backend/tests/ -v` — 0 failures, test count >= 144
- [ ] Real 5-section topic manual test: all 5 sections present in the card list, in correct order, with no duplicate cards
- [ ] OVERWHELMED students never receive `challenge_bump` in any end-to-end flow
- [ ] Cache version = 5 forces fresh generation: confirmed by clearing one student session and observing a new LLM call (not cache hit) in the uvicorn log

### Updated Effort Summary

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Phase 0 — Infrastructure | Alembic migration 005, config.py constants, conftest fixtures | 3 days | devops-engineer (1) |
| Phase A — DB Schema + History | load_student_history() extension, section-complete endpoint, EMA persistence | 4.25 days | backend-developer (1) |
| Phase B — Numeric Blending | compute_numeric_state_score, blended_score_to_generate_as, prompt builder STUDENT STATE + COVERAGE CONTEXT | 3.75 days | backend-developer (1) |
| Phase C — Concept Tracking | concept_index/images_used threading in teaching_service | 2 days | backend-developer (1) |
| Phase D — Boredom Detection | boredom_detector.py (new), strategy prompt blocks, frontend keyword detection, SessionContext SECTION_COMPLETE, i18n | 7 days | backend-developer (1) + frontend-developer (1), parallel work |
| Phase E — Tests | 22+ new tests, regression suite, performance benchmark | 8.5 days | comprehensive-tester (1) |
| Phase F — Output Quality | Cache invalidation, validate_and_repair_cards(), STUDENT STATE expansion, OVERWHELMED fix, strategy effectiveness feedback | 6.5 days | backend-developer (1) + comprehensive-tester (1), parallel on F-06/F-07 vs test groups |
| **Total** | | **~35 dev-days** | 4 agents (some parallel) |
