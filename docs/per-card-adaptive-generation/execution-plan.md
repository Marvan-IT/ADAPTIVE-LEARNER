# Per-Card Adaptive Generation — Execution Plan

**Feature slug:** `per-card-adaptive-generation`
**Author:** Solution Architect Agent
**Date:** 2026-03-24
**Status:** Ready for implementation

---

## 1. Work Breakdown Structure (WBS)

### Phase 1 — Foundation: Config, Schemas, Endpoint Skeleton

| ID | Title | Description | Effort (days) | Dependencies | Component |
|----|-------|-------------|---------------|--------------|-----------|
| P1-1 | Add `NEXT_CARD_MAX_TOKENS` constant | Add `NEXT_CARD_MAX_TOKENS: int = 1200` to `config.py`. Add import in `teaching_service.py`. | 0.25 | None | `config.py` |
| P1-2 | Add `NextCardRequest` schema | Add `NextCardRequest` Pydantic model to `teaching_schemas.py` (5 fields: `card_index`, `time_on_card_sec`, `wrong_attempts`, `hints_used`, `idle_triggers`) | 0.25 | P1-1 | `teaching_schemas.py` |
| P1-3 | Add `NextCardResponse` schema | Add `NextCardResponse` Pydantic model to `teaching_schemas.py` (`session_id`, `card`, `has_more_concepts`, `current_mode`, `concepts_covered_count`, `concepts_total`) | 0.25 | P1-2 | `teaching_schemas.py` |
| P1-4 | Add endpoint skeleton | Add `POST /sessions/{id}/next-card` route to `teaching_router.py`. Stub: returns 501 Not Implemented. Registers schemas in import block. | 0.5 | P1-3 | `teaching_router.py` |
| P1-5 | Add `fetchNextAdaptiveCard` wrapper | Add `fetchNextAdaptiveCard(sessionId, signals)` export to `sessions.js` with `NEXT_CARD_TIMEOUT = 30_000`. | 0.25 | P1-3 | `sessions.js` |

**Phase 1 total:** 1.5 dev-days

### Phase 2 — Backend Service: generate_per_card() + Bug Fixes

| ID | Title | Description | Effort (days) | Dependencies | Component |
|----|-------|-------------|---------------|--------------|-----------|
| P2-1 | Implement `generate_per_card()` — queue read | Add method to `TeachingService`. Step 1–3 from DLD: parse cache, guard empty queue, pop next piece. Return early if empty. | 0.5 | P1-4 | `teaching_service.py` |
| P2-2 | Implement `generate_per_card()` — blending | Steps 4–6 from DLD: load history, increment section_count locally (Bug 4 fix), build blended analytics, build learning profile. | 0.75 | P2-1 | `teaching_service.py`, `adaptive_engine.py` |
| P2-3 | Implement `generate_per_card()` — LLM call | Steps 7–12: resolve images, build piece_concept_detail, call `build_next_card_prompt()`, call `_chat()`, parse JSON response. | 0.75 | P2-2 | `teaching_service.py` |
| P2-4 | Implement `generate_per_card()` — cache write | Steps 13–16: update cache (pop queue, append card, update assigned images), flush to DB, return result dict. | 0.5 | P2-3 | `teaching_service.py` |
| P2-5 | Wire endpoint to service | Replace 501 stub in router with real `generate_per_card()` call. Add error handling (ValueError → HTTP 500). | 0.25 | P2-4 | `teaching_router.py` |
| P2-6 | Fix Bug 7: card_index=0 in generate_cards() | Change `card_index=0` to `card_index=history.get("total_cards_completed", 0)` in initial blended analytics call. | 0.25 | None | `teaching_service.py` |

**Phase 2 total:** 3.0 dev-days

### Phase 3 — Prompt Builder: Image Injection

| ID | Title | Description | Effort (days) | Dependencies | Component |
|----|-------|-------------|---------------|--------------|-----------|
| P3-1 | Extend `build_next_card_prompt()` signature | Add `content_piece_images: list[dict] | None = None` parameter. Update docstring. | 0.25 | None | `prompt_builder.py` |
| P3-2 | Inject image block into user prompt | Add the `RELEVANT IMAGES FOR THIS CARD` block (cap 3 images) in the user prompt assembly section when `content_piece_images` is provided. | 0.5 | P3-1 | `prompt_builder.py` |
| P3-3 | Pass `content_piece_images` from service | Update the `build_next_card_prompt()` call in `generate_per_card()` to pass `content_piece_images`. | 0.25 | P2-3, P3-2 | `teaching_service.py` |

**Phase 3 total:** 1.0 dev-day

### Phase 4 — Frontend: State, Reducer, Callback

| ID | Title | Description | Effort (days) | Dependencies | Component |
|----|-------|-------------|---------------|--------------|-----------|
| P4-1 | Fix Bug 2: NEXT_CARD reducer boundary | Remove `Math.min` clamp from `NEXT_CARD` reducer case. Index advances freely. | 0.25 | None | `SessionContext.jsx` |
| P4-2 | Add `nextCardInFlight` to initialState | Add `nextCardInFlight: false` to `initialState`. | 0.25 | None | `SessionContext.jsx` |
| P4-3 | Add NEXT_CARD_INFLIGHT reducer cases | Add `NEXT_CARD_INFLIGHT` and `NEXT_CARD_INFLIGHT_DONE` cases to `sessionReducer`. | 0.25 | P4-2 | `SessionContext.jsx` |
| P4-4 | Add APPEND_NEXT_CARD reducer case | Add `APPEND_NEXT_CARD` case: appends card to array, advances index, updates `hasMoreConcepts`, clears inflight. | 0.5 | P4-3 | `SessionContext.jsx` |
| P4-5 | Add HAS_NO_MORE_CONCEPTS reducer case | Add `HAS_NO_MORE_CONCEPTS` case: sets `hasMoreConcepts=false`, clears inflight. | 0.25 | P4-3 | `SessionContext.jsx` |
| P4-6 | Import `fetchNextAdaptiveCard` in SessionContext | Add import at top of `SessionContext.jsx`. | 0.1 | P1-5 | `SessionContext.jsx` |
| P4-7 | Rewrite per-card branch in goToNextCard() | Replace old CASE B (rolling section prefetch) with new CASE B (per-card generation). Guard with `nextCardInFlight`. Handle `has_more_concepts=false` path (call finishCards). Add `state.nextCardInFlight` to useCallback deps. | 1.0 | P4-4, P4-5, P4-6, P2-5 | `SessionContext.jsx` |
| P4-8 | Disable Next button when inflight | In `CardLearningView.jsx`, disable Next button when `nextCardInFlight=true`. Show loading indicator. | 0.5 | P4-2 | `CardLearningView.jsx` |

**Phase 4 total:** 3.1 dev-days

### Phase 5 — Hardening: Tests + Observability

| ID | Title | Description | Effort (days) | Dependencies | Component |
|----|-------|-------------|---------------|--------------|-----------|
| P5-1 | Backend unit tests — service | Write pytest tests for `generate_per_card()`: happy path, empty queue, section_count increment, image injection, queue depletion. | 1.0 | P2-5 | `backend/tests/` |
| P5-2 | Backend unit tests — prompt builder | Write pytest tests for `build_next_card_prompt()` with and without `content_piece_images`. | 0.5 | P3-2 | `backend/tests/` |
| P5-3 | Backend integration tests — endpoint | Write pytest integration tests for `/next-card`: happy path, wrong phase, not found, queue depletion. Requires test DB session with seeded `presentation_text`. | 1.0 | P2-5 | `backend/tests/` |
| P5-4 | Frontend unit tests — reducer | Write vitest tests for `NEXT_CARD` (boundary fix), `APPEND_NEXT_CARD`, `HAS_NO_MORE_CONCEPTS`, `NEXT_CARD_INFLIGHT`. | 0.75 | P4-4 | `frontend/src/` |
| P5-5 | Structured logging in generate_per_card() | Add `logger.info` with timing and adaptation metadata at end of method. Add `logger.info` on empty queue return. | 0.25 | P2-5 | `teaching_service.py` |
| P5-6 | PostHog event in goToNextCard() | Add `trackEvent("per_card_generated", {...})` after successful fetch. | 0.25 | P4-7 | `SessionContext.jsx` |

**Phase 5 total:** 3.75 dev-days

---

## 2. Phased Delivery Plan

### Phase 1 — Foundation (Day 1)
**Goal:** Config, schemas, and endpoint registered with 501 stub. Axios wrapper exists.
**Deliverables:** `config.py`, `teaching_schemas.py` (2 new models), `teaching_router.py` (stub endpoint), `sessions.js` (new export).
**Team:** Backend developer (P1-1 to P1-4), Frontend developer (P1-5).
**Can proceed to Phase 2 immediately.** Phases 2 and 3 can begin in parallel after Phase 1.

### Phase 2 — Backend Service (Days 1–3)
**Goal:** `generate_per_card()` is fully implemented and wired. Endpoint returns real cards.
**Deliverables:** `teaching_service.py` (new method), `teaching_router.py` (endpoint wired).
**Team:** Backend developer.
**Dependency:** P1-4 must be done before P2-5.

### Phase 3 — Prompt Builder Image Injection (Days 2–3, parallel with Phase 2)
**Goal:** `build_next_card_prompt()` accepts and injects image context.
**Deliverables:** `prompt_builder.py` (extended function), `teaching_service.py` (pass images).
**Team:** Backend developer (can be same developer — small change).
**Dependency:** P3-3 depends on P2-3 being done.

### Phase 4 — Frontend (Days 3–5)
**Goal:** Frontend state, reducer, and `goToNextCard()` logic complete. Next button disabled while generating.
**Deliverables:** `SessionContext.jsx` (all reducer + callback changes), `CardLearningView.jsx` (loading state).
**Team:** Frontend developer.
**Dependency:** P4-7 requires P2-5 (endpoint must return real data for E2E testing).
**P4-1 and P4-2 to P4-6 are independent of backend and can begin immediately after Phase 1.**

### Phase 5 — Hardening (Days 5–7)
**Goal:** Tests written and passing. Observability in place. Ready for production.
**Deliverables:** Test files (backend + frontend), structured logs, PostHog event.
**Team:** Comprehensive tester (P5-1 to P5-4), Backend developer (P5-5), Frontend developer (P5-6).
**Dependency:** All Phase 2, 3, 4 tasks must be done.

---

## 3. Dependencies and Critical Path

```
P1-1 → P1-2 → P1-3 → P1-4
                        │
               P1-5     │
               (parallel)│
                        ▼
P2-1 → P2-2 → P2-3 → P2-4 → P2-5   ← CRITICAL PATH (backend)
                 │
                 └──── P3-1 → P3-2 → P3-3   ← parallel with P2-3, P2-4
                                 │
P4-1 (independent)               │
P4-2 → P4-3 → P4-4               │
         └─── P4-5                │
P4-6 (independent)                │
                                  ▼
P4-7 (requires P2-5 + P4-4 + P4-5 + P4-6) → P4-8

P5-1 to P5-6 (all require Phase 2–4 complete)
```

**Critical path items:**
- P1-4 (endpoint skeleton) — blocks P2-5
- P2-3 (LLM call implementation) — longest single task; blocks P2-4 and P3-3
- P4-7 (goToNextCard rewrite) — most complex frontend task; requires P2-5 for E2E validation
- P5-3 (integration tests) — requires full backend stack running

**External blocking dependencies:**
- None. This feature is entirely internal to the ADA codebase.
- The backend developer should confirm that `build_blended_analytics()` correctly uses `section_count` from the `history` dict before starting P2-2. A quick unit test of the existing function with `section_count=1, 2, 3` will confirm.

---

## 4. Definition of Done

### Phase 1 DoD
- [ ] `NEXT_CARD_MAX_TOKENS = 1200` present in `config.py`
- [ ] `NextCardRequest` and `NextCardResponse` defined in `teaching_schemas.py` with correct field types
- [ ] `POST /api/v2/sessions/{id}/next-card` route registered in router; returns HTTP 501 with descriptive message
- [ ] `fetchNextAdaptiveCard` exported from `sessions.js` with 30 s timeout

### Phase 2 DoD
- [ ] `generate_per_card()` method exists on `TeachingService`
- [ ] Calling endpoint with a session that has `concepts_queue=[P4, P5]` returns a card for P4; cache has `concepts_queue=[P5]`
- [ ] Calling endpoint a second time returns P5; `has_more_concepts=false`
- [ ] Calling endpoint a third time returns `has_more_concepts=false`, `card=null`, no LLM call made
- [ ] `history["section_count"]` is incremented by 1 relative to the DB value at the start of each call
- [ ] Bug 7 fix: `card_index` in initial `generate_cards()` call uses `total_cards_completed` not hardcoded 0
- [ ] Structured log entry emitted on each call with the required fields
- [ ] Endpoint returns HTTP 409 when `session.phase != "CARDS"`

### Phase 3 DoD
- [ ] `build_next_card_prompt()` accepts `content_piece_images` parameter without breaking existing call sites (default `None`)
- [ ] When `content_piece_images` contains 2 images, the user prompt contains a `RELEVANT IMAGES FOR THIS CARD:` block with both descriptions
- [ ] When `content_piece_images=None`, the user prompt does not contain the image block

### Phase 4 DoD
- [ ] `NEXT_CARD` reducer: `currentCardIndex` advances from 3 to 4 when `cards.length=4` (not stuck at 3)
- [ ] `nextCardInFlight: false` in `initialState`; set to `true` on dispatch of `NEXT_CARD_INFLIGHT`; cleared on `NEXT_CARD_INFLIGHT_DONE`, `APPEND_NEXT_CARD`, `HAS_NO_MORE_CONCEPTS`
- [ ] Second call to `goToNextCard()` while `nextCardInFlight=true` returns without firing a second API request
- [ ] When `fetchNextAdaptiveCard` returns `has_more_concepts=false`, the session transitions to Socratic phase
- [ ] Next button in `CardLearningView.jsx` is disabled / shows spinner when `nextCardInFlight=true`
- [ ] `fetchNextAdaptiveCard` is imported and used in `SessionContext.jsx`

### Phase 5 DoD
- [ ] All unit tests listed in DLD Section 14 pass
- [ ] All integration tests listed in DLD Section 14 pass
- [ ] All frontend reducer tests pass
- [ ] No `console.log()` statements added; all logging via `logger.info/warning/exception`
- [ ] `trackEvent("per_card_generated", {...})` fires after each successful per-card fetch
- [ ] p50 latency for `/next-card` measured at < 4 s in staging (manual spot-check with timing logs)

---

## 5. Rollout Strategy

### Deployment Approach
Standard rolling deploy — no feature flag required for this feature. The new endpoint is additive and does not break any existing endpoints. The frontend change affects `goToNextCard()` behaviour, which is the only user-visible change.

If a feature flag is desired for caution, add `NEXT_CARD_PER_PIECE_ENABLED: bool = True` to `config.py` and wrap the new `goToNextCard()` branch in a check:
```js
if (import.meta.env.VITE_NEXT_CARD_PER_PIECE_ENABLED !== "false") { ... }
```
This is optional and adds maintenance overhead.

### Rollback Plan
1. Revert the `goToNextCard()` change in `SessionContext.jsx` to restore the rolling-section prefetch (CASE B in old code). This is a single function rollback.
2. Leave the new endpoint in place (additive, not called by old frontend code).
3. No DB changes to roll back.

### Monitoring at Launch
1. Watch for HTTP 500 rate on `/api/v2/sessions/*/next-card` in logs for first 30 minutes after deploy.
2. Watch for `[per-card] generated` log messages — confirm they are appearing at expected volume.
3. Watch for `nextCardInFlight` getting stuck (no `NEXT_CARD_INFLIGHT_DONE` following a `NEXT_CARD_INFLIGHT`) via PostHog session recordings on first 20 student sessions.
4. Confirm `has_more_concepts=false` path leads to Socratic start (not blank screen) via PostHog funnel.

### Post-Launch Validation
- [ ] At least 10 students complete a full lesson end-to-end without getting stuck on a card
- [ ] At least 5 students who started a lesson in NORMAL mode switched to STRUGGLING or FAST mid-lesson (confirms adaptation is working)
- [ ] No increase in HTTP 500 rate vs. baseline (check over 24 hours)
- [ ] Average lesson completion rate unchanged or improved vs. pre-deploy baseline

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Phase 1 — Foundation | Config constant, 2 schemas, endpoint stub, Axios wrapper | 1.5 dev-days | 1 backend + 1 frontend (can split P1-5) |
| Phase 2 — Backend Service | `generate_per_card()`, endpoint wired, Bug 4 + 7 fixes | 3.0 dev-days | 1 backend developer |
| Phase 3 — Prompt Builder | Image injection in `build_next_card_prompt()` | 1.0 dev-day | 1 backend developer (parallel with Phase 2) |
| Phase 4 — Frontend | Reducer fixes (Bug 1 + 2), `goToNextCard()` rewrite, loading UI | 3.1 dev-days | 1 frontend developer |
| Phase 5 — Hardening | Unit + integration tests, logs, PostHog | 3.75 dev-days | 1 tester + backend + frontend |
| **Total** | | **12.35 dev-days** | **3 engineers** |

**Calendar estimate:** With 3 engineers working in parallel (backend, frontend, tester), deliverable in **5–6 calendar days** assuming no blocking issues.

**Critical path calendar duration:** P1-1 → P2-3 (longest backend chain) = ~3.5 days; P4-7 starts Day 3 = complete by Day 5; P5-3 integration tests on Day 5–6.
