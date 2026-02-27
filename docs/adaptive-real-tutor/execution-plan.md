# Execution Plan — Adaptive Real Tutor
**Feature slug:** `adaptive-real-tutor`
**Version:** 1.0
**Date:** 2026-02-27
**Author:** Solution Architect Agent

---

## 1. Work Breakdown Structure (WBS)

### Phase 1 — Foundation (DB models — COMPLETE)

| Task ID | Title | Description | Effort | Dependencies | Component |
|---|---|---|---|---|---|
| P1-T01 | Alembic migration `e3c02cf4c22e` | `card_interactions` and `spaced_reviews` tables added. Alembic initialised at `backend/alembic/`. | DONE | — | DB / DevOps |
| P1-T02 | ORM models added | `CardInteraction` and `SpacedReview` mapped in `backend/src/db/models.py`. Relationships wired to `Student` and `TeachingSession`. | DONE | P1-T01 | DB / DevOps |
| P1-T03 | Verify indexes (patch if needed) | Confirm composite index `(student_id, completed_at DESC)` on `card_interactions` exists. If not, create patch migration. | 0.5 days | P1-T01 | DevOps |
| P1-T04 | Verify unique constraint on `spaced_reviews` | Confirm or add `UNIQUE (student_id, concept_id, review_number)` on `spaced_reviews` via patch migration. | 0.5 days | P1-T01 | DevOps |
| P1-T05 | Add `ADAPTIVE_CARDS_ENABLED`, `ADAPTIVE_CARD_MODEL`, `ADAPTIVE_CARD_CEILING`, blending constants to `config.py` | New constants: `ADAPTIVE_CARDS_ENABLED = True`, `ADAPTIVE_CARD_MODEL = "gpt-4o-mini"`, `ADAPTIVE_CARD_CEILING = 8`, `MIN_HISTORY_CARDS = 5`, `BLEND_W_CURR_STEADY = 0.6`, `BLEND_W_HIST_STEADY = 0.4`, `BLEND_W_CURR_ACUTE = 0.9`, `BLEND_W_HIST_ACUTE = 0.1`, `ACUTE_TIME_RATIO_HIGH = 2.0`, `ACUTE_TIME_RATIO_LOW = 0.4`, `ACUTE_WRONG_RATIO = 3.0`, `BASELINE_TIME_FLOOR = 30.0`, `SR_INTERVALS_DAYS = [1, 3, 7, 14, 30]` | 0.5 days | — | Backend |

---

### Phase 2 — Backend: History Aggregation and Blending

| Task ID | Title | Description | Effort | Dependencies | Component |
|---|---|---|---|---|---|
| P2-T01 | Create `adaptive/blending.py` | Implement `StudentBaseline` dataclass, `BlendedSignals` dataclass, and `blend_signals()` pure function per DLD Appendix A. Import all constants from `config.py`. | 1 day | P1-T05 | Backend |
| P2-T02 | Create `adaptive/spaced_review.py` | Implement `compute_next_due(review_number, now)` pure function per DLD Appendix B. Import `SR_INTERVALS_DAYS` from `config.py`. | 0.5 days | P1-T05 | Backend |
| P2-T03 | Create `adaptive/real_tutor_schemas.py` | Implement all Pydantic v2 schemas: `CompleteCardRequest`, `CompleteCardResponse`, `NextCard`, `LearningProfileSummary`, `ReviewDueItem`, `StudentBaseline`, `BlendedSignals`, `NextCardLLMOutput`, `McqQuestion`, `TrueFalseQuestion`. Include `field_validator` for `motivational_note` fallback. | 1 day | — | Backend |
| P2-T04 | Create `aggregate_student_baseline()` async function | In `adaptive/blending.py` (or a new `adaptive/history.py`): `async def aggregate_student_baseline(db: AsyncSession, student_id: uuid.UUID) -> StudentBaseline`. Execute `SELECT AVG(time_on_card_sec), AVG(wrong_attempts), AVG(hints_used), COUNT(*) FROM card_interactions WHERE student_id = ?`. Return `StudentBaseline`. Log query duration at DEBUG. | 1 day | P2-T01, P1-T02 | Backend |
| P2-T05 | Unit tests for `blending.py` | Write `backend/tests/test_blending.py` — 13 test cases covering all branches of `blend_signals()` and `compute_next_due()`. No mocks needed (pure functions). | 1 day | P2-T01, P2-T02 | Testing |
| P2-T06 | Unit tests for `real_tutor_schemas.py` | Write `backend/tests/test_real_tutor_schemas.py` — Pydantic validation tests for all schemas, including boundary conditions and the `motivational_note` fallback. | 0.5 days | P2-T03 | Testing |

---

### Phase 3 — Backend: Next-Card Prompt and Generator

| Task ID | Title | Description | Effort | Dependencies | Component |
|---|---|---|---|---|---|
| P3-T01 | Extend `adaptive/prompt_builder.py` with `build_next_card_prompt()` | Implement per DLD Appendix D. Sections: identity (single-card), JSON schema (NextCardLLMOutput), generation controls (reuse existing `_build_system_prompt()` logic), performance tone modifier, card position context, motivational note requirement. Add `_NEXT_CARD_JSON_SCHEMA` string constant. User prompt: concept text, student profile, performance label, instruction. | 1.5 days | P2-T03 | Backend |
| P3-T02 | Implement `generate_next_card()` async function | In `adaptive/adaptive_engine.py` (or new `adaptive/real_tutor_engine.py`). Signature: `async def generate_next_card(student_id, session_id, concept_id, card_index, blended_signals, knowledge_svc, mastery_store, llm_client, model, language) -> tuple[NextCardLLMOutput, str]`. Steps: (a) fetch concept_detail, (b) build LearningProfile from blended AnalyticsSummary, (c) build GenerationProfile, (d) call build_next_card_prompt(), (e) call _call_llm(max_tokens=1200), (f) parse + validate via _extract_json_block() + _salvage_truncated_json() + NextCardLLMOutput.model_validate(), (g) return (output, adaptation_label). Raise ValueError on LLM failure. Return 502 from router layer. | 2 days | P3-T01, P2-T01, P2-T03 | Backend |
| P3-T03 | Unit tests for `build_next_card_prompt()` | Write `backend/tests/test_prompt_builder_next_card.py`. Test: (a) system prompt contains JSON schema string, (b) MUCH_SLOWER modifier present when performance_vs_baseline="MUCH_SLOWER", (c) card_index is correctly embedded, (d) language name injected correctly for all 13 language codes. 4–6 test cases. | 1 day | P3-T01 | Testing |
| P3-T04 | Integration test for `generate_next_card()` with mocked LLM | Mock `_call_llm()` to return a valid `NextCardLLMOutput` JSON string. Assert returned `NextCardLLMOutput` matches expected fields. | 0.5 days | P3-T02 | Testing |

---

### Phase 4 — Backend: Endpoints and Spaced Review

| Task ID | Title | Description | Effort | Dependencies | Component |
|---|---|---|---|---|---|
| P4-T01 | Add `complete_card` route to `adaptive_router.py` | `POST /api/v2/sessions/{session_id}/complete-card`. Steps: (1) validate session_id → 404 if not found, (2) check `ADAPTIVE_CARDS_ENABLED` feature flag, (3) check `card_index >= ADAPTIVE_CARD_CEILING` → `JSONResponse(409, {"ceiling": True})`, (4) INSERT CardInteraction row, (5) `aggregate_student_baseline()`, (6) `blend_signals()`, (7) bulk-load mastery_store, (8) `generate_next_card()`, (9) UPDATE CardInteraction.adaptation_applied, (10) return `CompleteCardResponse`. Handle ValueError → 404 or 502. Handle Exception → 500. Emit structured log. | 2 days | P3-T02, P2-T04, P2-T03 | Backend |
| P4-T02 | Add `schedule_spaced_review()` call to existing complete-cards endpoint | In `teaching_router.py` (or wherever `POST /api/v2/sessions/{id}/complete-cards` is handled): after the session phase transitions to `CARDS_DONE`, call `schedule_spaced_review(db, student_id, concept_id)`. Use `on_conflict_do_nothing()` on the INSERT. | 1 day | P2-T02, P1-T04 | Backend |
| P4-T03 | Add `review_due` route to `adaptive_router.py` | `GET /api/v2/students/{student_id}/review-due`. SELECT from `spaced_reviews WHERE student_id=? AND due_at <= now() AND completed_at IS NULL ORDER BY due_at ASC`. For each row, call `knowledge_svc.get_concept_detail(concept_id)` to resolve `concept_title_hint`. Return `list[ReviewDueItem]`. 404 if student_id not found. | 1 day | P2-T03, P1-T02 | Backend |
| P4-T04 | Feature flag shortcut in `complete_card` route | When `ADAPTIVE_CARDS_ENABLED = False`: skip blending and LLM call; return 204 No Content or a static "feature disabled" 200 with empty card payload. (Exact fallback behavior TBD with product — document as open question.) | 0.5 days | P4-T01 | Backend |
| P4-T05 | Integration tests for `complete_card` endpoint | 7 integration test cases (see DLD §9.2): session not found 404, ceiling 409, LLM failure 502, CardInteraction row written, adaptation_applied updated, valid 200 response structure. Use FastAPI TestClient + test DB. | 2 days | P4-T01 | Testing |
| P4-T06 | Integration tests for `review_due` endpoint | 3 test cases: empty array, overdue item returned, completed item excluded. | 0.5 days | P4-T03 | Testing |
| P4-T07 | Integration test for spaced review scheduling | Verify SpacedReview row inserted after `complete-cards` call on mastered concept. Verify no duplicate on retry. | 0.5 days | P4-T02 | Testing |

---

### Phase 5 — Frontend: Signal Tracking and Dynamic Card Replacement

| Task ID | Title | Description | Effort | Dependencies | Component |
|---|---|---|---|---|---|
| P5-T01 | Add `completeCard()` Axios wrapper to `frontend/src/api/sessions.js` | `export const completeCard = (sessionId, signals) => api.post(\`/api/v2/sessions/${sessionId}/complete-card\`, signals)`. Add `getReviewsDue = (studentId) => api.get(\`/api/v2/students/${studentId}/review-due\`)`. | 0.5 days | — | Frontend |
| P5-T02 | Add card-level signal tracking to `CardLearningView.jsx` | (a) `cardStartRef = useRef(performance.now())` — reset on card change. (b) `wrongAttemptsRef = useRef(0)` — increment on wrong answer, reset on card change. (c) `hintsUsedRef = useRef(0)` — increment on hint request, reset. (d) `idleTriggersRef = useRef(0)` — increment when idle detector fires (if implemented), reset. (e) `selectedWrongOptionRef = useRef(null)` — capture last wrong MCQ index. All refs, not state — zero re-renders. | 1 day | P5-T01 | Frontend |
| P5-T03 | Extend `SessionContext` with `CARD_COMPLETED` action and `completeCardAndFetch()` callback | Add reducer case `CARD_REPLACED`: update `cards[currentCardIndex + 1]` with the new card from the API response; increment `currentCardIndex`. Add `completingCard: false` flag (loading state during API call). Add `motivationalNote: null` field. Implement `completeCardAndFetch(sessionId, signals)` callback: (a) dispatch `COMPLETING_CARD` (loading), (b) call `completeCard()`, (c) on 200: dispatch `CARD_REPLACED` with new card, dispatch motivational note, track PostHog event, (d) on 409: dispatch `CEILING_REACHED`, call `finishCards()`, (e) on 502: dispatch `CARD_FETCH_FAILED` (silent — keep current card), (f) on 500/network: same as 502. | 1.5 days | P5-T01, P5-T02 | Frontend |
| P5-T04 | Wire `completeCardAndFetch()` to "Next Card" button in `CardLearningView.jsx` | Replace direct `goToNextCard()` call with `completeCardAndFetch()`. Disable the "Next Card" button while `state.completingCard === true`. Show spinner icon on button during loading. After response: re-enable button. On failure: show no error to student (silent fallback). | 1 day | P5-T03 | Frontend |
| P5-T05 | Render `motivational_note` in `CardLearningView.jsx` | Display `state.motivationalNote` as an italicised, lightly styled sentence below the card content area. Only visible when `motivationalNote` is non-null. Hide on card change (clear from state). Use `useTranslation` for the fallback key `card.motivationalFallback` (rendered only when LLM fallback is used). | 0.5 days | P5-T03 | Frontend |
| P5-T06 | Add idle detector to `CardLearningView.jsx` | `useEffect` on card change: `const idleTimer = setInterval(() => idleTriggersRef.current++, 60000)`. Clear on card change or unmount. Threshold: 60 seconds of no interaction (no click, no keypress). | 0.5 days | P5-T02 | Frontend |
| P5-T07 | Add i18n strings for motivational feedback and review prompts | Add keys to all 13 locale files (`frontend/src/locales/*.json`): `card.motivationalFallback`, `card.adaptingNote`, `review.badgeTooltip`, `review.dueToday`. English values: `"Keep going — every card brings you closer!"`, `"Adapting to your pace..."`, `"Due for review today"`, `"Review due today"`. | 0.5 days | — | Frontend |

---

### Phase 6 — Frontend: ConceptMap Review Badges and Completion Polish

| Task ID | Title | Description | Effort | Dependencies | Component |
|---|---|---|---|---|---|
| P6-T01 | Fetch review-due data in `ConceptMapPage.jsx` on mount | `useEffect(() => { getReviewsDue(student.id).then(res => setReviewDue(res.data)) }, [student.id])`. Store as `Set<string>` of `concept_id` values in local state. | 0.5 days | P5-T01 | Frontend |
| P6-T02 | Render review-due badge on ConceptMap nodes | In the Sigma node rendering pass: if `node.concept_id` is in the `reviewDue` set, add a red dot badge overlay (SVG circle or Sigma node attribute `color = "#ef4444"` with `borderColor = "#b91c1c"`). Show tooltip `review.badgeTooltip` on hover via Sigma tooltip plugin or custom. | 1 day | P6-T01 | Frontend |
| P6-T03 | Mark review complete when student starts lesson on due concept | When `startLesson(conceptId)` is called and `conceptId` is in the `reviewDue` set: after session completion, call `PATCH /api/v2/spaced-reviews/{concept_id}/complete` (new endpoint — see note). Alternatively (simpler v1): query `review-due` again after lesson completion and refresh badges. | 0.5 days | P6-T01 | Backend + Frontend |
| P6-T04 | Display `adaptation_applied` and `performance_vs_baseline` in dev overlay (optional, dev-only) | Render a dismissable pill at the bottom of `CardLearningView.jsx` showing `adaptation_applied` (e.g., "SLOW/STRUGGLING") and `performance_vs_baseline` when `import.meta.env.DEV === true`. Helps QA validate adaptation is working. | 0.5 days | P5-T04 | Frontend |
| P6-T05 | End-to-end tests | 3 E2E test scenarios per DLD §9.3: full card sequence adaptation, ceiling triggers Socratic check, spaced review lifecycle. | 2 days | P4-T01, P5-T04 | Testing |

---

## 2. Phased Delivery Plan

### Phase 1 — Foundation (COMPLETE)
**Deliverables:**
- `card_interactions` and `spaced_reviews` tables live in PostgreSQL via Alembic
- ORM models in `db/models.py`
- New constants in `config.py` (P1-T05 is the only remaining task)

**Estimated remaining effort:** 1 day (P1-T03 index verification + P1-T04 unique constraint + P1-T05 config constants)

---

### Phase 2 — Backend: History Aggregation and Blending
**Goal:** All pure business logic exists and is unit-tested before any HTTP endpoint is touched.

**Deliverables:**
- `adaptive/blending.py` — `blend_signals()` + `aggregate_student_baseline()`
- `adaptive/spaced_review.py` — `compute_next_due()`
- `adaptive/real_tutor_schemas.py` — all Pydantic schemas
- `backend/tests/test_blending.py` — 13 test cases all passing
- `backend/tests/test_real_tutor_schemas.py` — validation tests passing

**Estimated effort:** 4 days (backend: 2.5 days, testing: 1.5 days)
**Dependency:** P1-T05 (config constants)

---

### Phase 3 — Backend: Next-Card Prompt and Generator
**Goal:** The `generate_next_card()` function produces a valid `NextCardLLMOutput` given real inputs.

**Deliverables:**
- `adaptive/prompt_builder.py` extended with `build_next_card_prompt()`
- `generate_next_card()` function in `adaptive/adaptive_engine.py` or new file
- Unit tests for prompt builder (4–6 cases)
- Integration test for generator with mocked LLM

**Estimated effort:** 5 days (backend: 3.5 days, testing: 1.5 days)
**Dependency:** Phase 2 complete

---

### Phase 4 — Backend: Endpoints and Spaced Review
**Goal:** Both new endpoints are live, tested, and production-ready.

**Deliverables:**
- `POST /api/v2/sessions/{id}/complete-card` route in `adaptive_router.py`
- `GET /api/v2/students/{id}/review-due` route in `adaptive_router.py`
- Spaced review scheduling wired into `complete-cards` endpoint
- Feature flag shortcut implemented
- 10+ integration tests passing

**Estimated effort:** 7 days (backend: 4.5 days, testing: 2.5 days)
**Dependency:** Phase 3 complete

---

### Phase 5 — Frontend: Signal Tracking and Dynamic Card Replacement
**Goal:** Frontend collects signals, calls the endpoint, and replaces cards dynamically. Motivational note is displayed.

**Deliverables:**
- `sessions.js` extended with `completeCard()` and `getReviewsDue()`
- `CardLearningView.jsx` wired with signal refs and `completeCardAndFetch()`
- `SessionContext` extended with new reducer actions and callback
- Motivational note UI component
- Idle detector
- i18n strings in all 13 locale files
- PostHog event `adaptive_card_generated` firing

**Estimated effort:** 5 days (frontend: 5 days; can start in parallel with Phase 3 once Phase 2 API schemas are finalised)
**Dependency:** P5-T01 requires Phase 4 `complete-card` endpoint to be available (can mock with MSW during development)

---

### Phase 6 — Frontend: ConceptMap Review Badges and Hardening
**Goal:** Review-due badges visible on ConceptMap; dev overlay for QA; E2E tests green.

**Deliverables:**
- ConceptMap review badges with tooltip
- Review-complete marking
- Dev-only adaptation overlay
- 3 E2E tests passing
- PostHog event `review_due_badge_shown` firing

**Estimated effort:** 4 days (frontend: 2 days, testing: 2 days)
**Dependency:** Phase 4 (review-due endpoint) + Phase 5 (session context)

---

## 3. Dependencies and Critical Path

```
P1-T05 (config.py constants)
    │
    ├──► P2-T01 (blending.py)
    │        │
    │        ├──► P2-T04 (aggregate_student_baseline)
    │        │        │
    │        │        └──► P4-T01 (complete-card endpoint)  ◄─ CRITICAL PATH
    │        │                  │
    │        │                  └──► P4-T05 (endpoint integration tests)
    │        │
    │        └──► P2-T05 (blending unit tests)
    │
    ├──► P2-T02 (spaced_review.py)
    │        │
    │        └──► P4-T02 (schedule_spaced_review call)
    │
    └──► P2-T03 (real_tutor_schemas.py)
             │
             └──► P3-T01 (build_next_card_prompt)
                      │
                      └──► P3-T02 (generate_next_card)  ◄─ CRITICAL PATH
                               │
                               └──► P4-T01 (complete-card endpoint)

P4-T01 complete
    │
    └──► P5-T01 (Axios wrappers)
             │
             └──► P5-T02 (signal tracking refs)
                      │
                      └──► P5-T03 (SessionContext extension)  ◄─ CRITICAL PATH
                               │
                               └──► P5-T04 (wire to button)
                                        │
                                        ├──► P5-T05 (motivational note UI)
                                        └──► P6-T05 (E2E tests)

P4-T03 (review-due endpoint)
    │
    └──► P6-T01 (fetch in ConceptMapPage)
             │
             └──► P6-T02 (badges)  ◄─ CRITICAL PATH (ConceptMap feature)
```

**Critical path items (must not be delayed):**
- P1-T05 — config constants (blocks all backend work)
- P3-T02 — `generate_next_card()` (blocks the endpoint)
- P4-T01 — `complete-card` endpoint (blocks all frontend wiring)
- P5-T03 — `SessionContext` extension (blocks card replacement UI)

**External blocking dependencies:**
- Devops-engineer: confirm or create patch migration for `card_interactions` indexes and `spaced_reviews` unique constraint before Phase 4 goes to staging
- Product: confirm `ADAPTIVE_CARD_MODEL`, `ADAPTIVE_CARD_CEILING`, `MIN_HISTORY_CARDS` values before Phase 3 begins

---

## 4. Definition of Done

### Phase 1 — Foundation
- [x] `card_interactions` table exists with all columns per `db/models.py`
- [x] `spaced_reviews` table exists with all columns per `db/models.py`
- [ ] Composite index `(student_id, completed_at DESC)` exists on `card_interactions`
- [ ] Unique constraint `(student_id, concept_id, review_number)` exists on `spaced_reviews`
- [ ] All new constants added to `config.py` with correct types and defaults
- [ ] `Alembic upgrade head` runs successfully on a fresh DB

### Phase 2 — Backend: History Aggregation and Blending
- [ ] `blend_signals()` passes all 13 unit tests with 100% branch coverage
- [ ] `compute_next_due()` passes all 3 unit tests
- [ ] `aggregate_student_baseline()` executes against test DB and returns correct `StudentBaseline`
- [ ] All Pydantic schemas in `real_tutor_schemas.py` pass validation tests
- [ ] `motivational_note` fallback validator returns default string on empty input
- [ ] No `print()` statements; all logging uses `logging` module

### Phase 3 — Backend: Next-Card Prompt and Generator
- [ ] `build_next_card_prompt()` unit tests pass (4+ cases)
- [ ] `generate_next_card()` with mocked LLM returns valid `NextCardLLMOutput`
- [ ] JSON salvage (`_salvage_truncated_json`) handles a truncated single-card response in unit test
- [ ] LLM failure after 3 retries raises `ValueError` (integration test with mocked client)
- [ ] `max_tokens=1200` is used (not the full-lesson 8000)
- [ ] Structured log line emitted with `student_id`, `session_id`, `card_index`, `adaptation_applied`, `duration_ms`

### Phase 4 — Backend: Endpoints and Spaced Review
- [ ] `POST /api/v2/sessions/{id}/complete-card` returns 200 with valid `CompleteCardResponse` (integration test)
- [ ] Endpoint returns 404 for unknown `session_id` (integration test)
- [ ] Endpoint returns 409 `{"ceiling": true}` when `card_index >= ADAPTIVE_CARD_CEILING` (integration test)
- [ ] Endpoint returns 502 when LLM client mock raises ValueError (integration test)
- [ ] `CardInteraction` row is written to DB on every 200 response (integration test asserts DB state)
- [ ] `adaptation_applied` field is updated on the `CardInteraction` row after LLM call (integration test)
- [ ] `GET /api/v2/students/{id}/review-due` returns overdue items and excludes completed items (integration tests)
- [ ] `SpacedReview` row is inserted after `complete-cards` call on mastered concept (integration test)
- [ ] Duplicate `SpacedReview` insert does not raise error (unique constraint + `on_conflict_do_nothing`)
- [ ] `ADAPTIVE_CARDS_ENABLED = False` does not call LLM (unit test on router with feature flag patched)
- [ ] All routes registered in `main.py` and accessible via FastAPI OpenAPI docs at `/docs`
- [ ] No breaking changes to existing `/api/v3/adaptive/lesson` or `/api/v2/sessions/{id}/begin-check` endpoints

### Phase 5 — Frontend: Signal Tracking and Dynamic Card Replacement
- [ ] `completeCard()` and `getReviewsDue()` Axios wrappers exist in `sessions.js`
- [ ] `useRef` timer resets on card change; `time_on_card_sec` captured accurately (manual QA)
- [ ] Wrong attempt counter increments correctly and resets on card advance (manual QA)
- [ ] "Next Card" button is disabled during API call; spinner shown
- [ ] On 200 response: card in `SessionContext.cards[nextIndex]` replaced with new card
- [ ] On 409 response: `finishCards()` is called automatically (Socratic check begins)
- [ ] On 502 response: no error shown to student; previous card or static fallback shown
- [ ] `motivationalNote` displayed below card content in italics
- [ ] `motivationalNote` cleared on card advance
- [ ] PostHog event `adaptive_card_generated` fires with correct properties on 200 response
- [ ] PostHog event `card_ceiling_reached` fires on 409
- [ ] PostHog event `llm_fallback_triggered` fires on 502
- [ ] All user-visible strings use `useTranslation()` — verified in all 13 locale files
- [ ] RTL layout (Arabic) not broken by new UI elements (manual QA with `ar` locale)
- [ ] Idle detector triggers `idleTriggersRef.current++` after 60 seconds of inactivity (manual QA)

### Phase 6 — Frontend: ConceptMap Review Badges
- [ ] `getReviewsDue()` called on `ConceptMapPage` mount; response stored in state
- [ ] Concepts with due reviews show a red badge on the ConceptMap node (visual QA)
- [ ] Hovering a badge node shows tooltip `review.badgeTooltip`
- [ ] Completing a lesson on a due-review concept removes badge from map (after page refresh or live update)
- [ ] Dev overlay (`import.meta.env.DEV`) shows `adaptation_applied` and `performance_vs_baseline`
- [ ] 3 E2E tests pass (full card sequence, ceiling → Socratic, spaced review lifecycle)
- [ ] No console errors or warnings in production build (`npm run build` clean)
- [ ] WCAG 2.1 AA: review badge has sufficient colour contrast; tooltip accessible via keyboard

---

## 5. Rollout Strategy

### 5.1 Feature Flag
The feature is gated by `ADAPTIVE_CARDS_ENABLED` in `config.py`.

```python
# backend/src/config.py
ADAPTIVE_CARDS_ENABLED: bool = bool(os.getenv("ADAPTIVE_CARDS_ENABLED", "true").lower() == "true")
```

- `ADAPTIVE_CARDS_ENABLED = False`: `complete-card` endpoint is live but does not call the LLM. Returns 204 (or falls back to the pre-generated card batch). All signal collection still runs — baseline data is still populated. This allows pre-population of `card_interactions` history before adaptive generation is enabled.
- `ADAPTIVE_CARDS_ENABLED = True` (default after Phase 4 is deployed): full adaptive generation active.

### 5.2 Deployment Approach
- **Deployment model:** Standard deploy (not blue/green in v1 — ADA does not yet have Docker or CI/CD).
- **Deploy order:**
  1. Deploy backend Phase 4 with `ADAPTIVE_CARDS_ENABLED = False` in `.env`.
  2. Smoke test: verify new endpoints appear in `/docs`.
  3. Run integration test suite against staging DB.
  4. Set `ADAPTIVE_CARDS_ENABLED = True` in `.env`. Restart uvicorn.
  5. Deploy frontend Phase 5–6.
  6. Verify PostHog events firing in PostHog dashboard.

### 5.3 Rollback Plan
| Step | Action |
|---|---|
| LLM quality is poor | Set `ADAPTIVE_CARD_MODEL = "gpt-4o"` in `.env`; restart. No code change needed. |
| Adaptive generation causes errors | Set `ADAPTIVE_CARDS_ENABLED = False` in `.env`; restart. Frontend silently falls back. |
| Blending constants wrong | Adjust `MIN_HISTORY_CARDS`, blend weights in `.env` (once env-var override added to config); restart. |
| DB issue (index missing, constraint error) | Run patch Alembic migration; no downtime for the main app. |
| Full rollback required | `git revert` the backend Phase 4 commit; deploy; new endpoints disappear; existing endpoints unchanged. |

### 5.4 Monitoring and Alerting Setup for Launch
- [ ] Confirm PostHog dashboard has `adaptive_card_generated` funnel before launch
- [ ] Set up log alert on `adaptive_llm_failed` appearing more than 10 times per hour (Loki/CloudWatch)
- [ ] Manually test the ceiling path (send 9 `complete-card` requests on a single session)
- [ ] Verify `spaced_reviews` rows are being created after test mastery completions

### 5.5 Post-Launch Validation Steps (first 48 hours)
- [ ] Check `card_interactions` table growth rate — expected: proportional to active sessions
- [ ] Check `spaced_reviews` table — entries appearing for newly mastered concepts
- [ ] Check PostHog `adaptation_applied` distribution — expect mix of NORMAL/OK and SLOW/STRUGGLING (not all same tier)
- [ ] Check `performance_vs_baseline` distribution — expect most to be `NO_BASELINE` in first 48 hours (students building history)
- [ ] Monitor `complete_card` p95 latency in logs — alert threshold: 4000 ms
- [ ] Survey 3–5 students for subjective "did the cards feel personalized?" feedback

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|---|---|---|---|
| Phase 1 — Foundation (partial remaining) | Indexes, unique constraint, config.py constants | 1 day | DevOps Engineer (0.5 day), Backend Developer (0.5 day) |
| Phase 2 — Backend: Aggregation + Blending | `blending.py`, `spaced_review.py`, schemas, unit tests | 4 days | Backend Developer (2.5 days), Tester (1.5 days) |
| Phase 3 — Backend: Prompt + Generator | `build_next_card_prompt()`, `generate_next_card()`, tests | 5 days | Backend Developer (3.5 days), Tester (1.5 days) |
| Phase 4 — Backend: Endpoints + SR | 2 new routes, spaced review scheduling, 10 integration tests | 7 days | Backend Developer (4.5 days), Tester (2.5 days) |
| Phase 5 — Frontend: Signal Tracking | Signal refs, SessionContext, card replacement, i18n | 5 days | Frontend Developer (5 days) |
| Phase 6 — Frontend: Badges + Hardening | ConceptMap badges, dev overlay, 3 E2E tests | 4 days | Frontend Developer (2 days), Tester (2 days) |
| **Total** | | **26 days** | Backend Dev, Frontend Dev, Tester, DevOps (part-time) |

**Parallelism opportunity:** Phase 5 (frontend) can begin as soon as Phase 2 schemas (`real_tutor_schemas.py`) are finalised (day 5 of the overall plan), using Mock Service Worker (MSW) to mock the backend. This reduces the critical path to approximately **18 elapsed calendar days** with 2 developers working in parallel.

---

## Key Decisions Requiring Stakeholder Input

1. **`ADAPTIVE_CARD_MODEL` value before Phase 3:** The DLD defaults to `gpt-4o-mini` for single-card generation. If product requires `gpt-4o` quality, this must be decided before Phase 3 (backend developer needs to set the default in `config.py`). Latency difference: ~800 ms vs ~1800 ms p50.

2. **Phase 4 rollout `ADAPTIVE_CARDS_ENABLED = False` period:** How long should data be collected with signals active but LLM disabled? Recommended: 1 week of real student usage to build baseline history before enabling full adaptation. Confirm with product.

3. **P6-T03 review-complete marking approach:** Simpler v1 approach (re-poll `review-due` after lesson completion) vs adding a `PATCH /api/v2/spaced-reviews/{concept_id}/complete` endpoint. The PATCH approach is more correct but adds 1 day of backend work. Confirm scope.

4. **Idle detector threshold (60 seconds):** This is the proposed default. If 60 seconds is too sensitive (students re-reading card content), increase to 90 or 120 seconds. This is a `config.py` constant `IDLE_DETECTOR_THRESHOLD_SEC` — no code change needed to adjust.

5. **`ADAPTIVE_CARDS_ENABLED = False` response format:** When the feature flag is off, should `complete-card` return 204 No Content (frontend re-uses existing card) or return the next pre-generated card from the initial batch? Confirm the preferred degraded experience.
