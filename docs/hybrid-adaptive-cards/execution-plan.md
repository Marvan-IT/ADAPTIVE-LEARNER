# Hybrid Rolling Adaptive Card Generation — Execution Plan

**Feature slug:** `hybrid-adaptive-cards`
**Author:** Solution Architect
**Date:** 2026-03-14
**Status:** Design complete — approved for implementation

---

## Agentic Workflow Stages

This feature follows the ADA 5-stage agentic workflow:

| Stage | Agent | Trigger |
|-------|-------|---------|
| Stage 1 | `solution-architect` | Design complete (this document) |
| Stage 2 | `backend-developer` | DLD approved |
| Stage 3 | `comprehensive-tester` | Backend implementation complete |
| Stage 4 | `frontend-developer` | Backend tests passing |

No Stage 0 (`devops-engineer`) work is required — this feature introduces no DB schema changes and no new infrastructure.

---

## 1. Work Breakdown Structure (WBS)

### Stage 2 — Backend (`backend-developer`)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| B2-01 | Add `STARTER_PACK_INITIAL_SECTIONS` and `ROLLING_PREFETCH_TRIGGER_DISTANCE` to `config.py` | Add two new integer constants after `STARTER_PACK_MAX_SECTIONS`. Mark `STARTER_PACK_MAX_SECTIONS` as deprecated with a comment. | 0.25d | None | `config.py` |
| B2-02 | Raise per-section floor constants in `config.py` | Change `CARDS_MAX_TOKENS_SLOW_FLOOR` from 8000 → 6000, `CARDS_MAX_TOKENS_NORMAL_FLOOR` from 6000 → 4500, `CARDS_MAX_TOKENS_FAST_FLOOR` from 4000 → 3000. Update inline comments to clarify "per-section" scope. | 0.25d | B2-01 | `config.py` |
| B2-03 | Add `question2` field to `LessonCard` schema | Add `question2: CardMCQ \| None = Field(default=None, description="Backup MCQ shown after first wrong answer")` immediately after the `question` field in `teaching_schemas.py`. | 0.25d | None | `teaching_schemas.py` |
| B2-04 | Extend `CardsResponse` with rolling metadata fields | Add `has_more_concepts: bool = False`, `sections_total: int = 0`, `sections_done: int = 0` to `CardsResponse`. All fields have defaults — backward compatible. | 0.25d | None | `teaching_schemas.py` |
| B2-05 | Add `NextSectionCardsRequest` and `NextSectionCardsResponse` schemas | Add both new Pydantic models to `teaching_schemas.py`. `NextSectionCardsRequest` has no fields (body reserved). `NextSectionCardsResponse` has: `session_id`, `cards`, `has_more_concepts`, `sections_total`, `sections_done`, `section_name`. | 0.25d | B2-03 | `teaching_schemas.py` |
| B2-06 | Add `question2` to card JSON schema in `build_cards_system_prompt()` | In `prompts.py`, append the `question2` block to the card JSON schema example and add the DUAL-MCQ RULE instruction block (same concept, different angle, different `correct_index`, difficulty MEDIUM or HARD). | 0.5d | None | `prompts.py` |
| B2-07 | Add `_compute_per_section_budget()` helper to `teaching_service.py` | Standalone module-level function (not a method) that takes `n_sections: int` and `profile: str` and returns `int`. Uses the updated floor constants from `config.py`. Formula: `min(ceiling, max(floor, n_sections * per_section))`. | 0.25d | B2-02 | `teaching_service.py` |
| B2-08 | Add `_stamp_section_index()` private method to `TeachingService` | Iterates over card dicts; matches each card's `section_title` or `section_id` against the ordered `sections` list; stamps integer `_section_index = base_index + i` on each card dict. Fallback to `base_index` if no match; logs `DEBUG` warning on fallback. | 0.5d | None | `teaching_service.py` |
| B2-09 | Add `_store_concepts_queue()` private method to `TeachingService` | Builds the v11 `presentation_text` JSON blob and writes it to `session.presentation_text`. Fields: `version=11`, `presentation`, `cached_cards`, `concepts_queue`, `generated_sections`, `total_sections`. | 0.5d | None | `teaching_service.py` |
| B2-10 | Refactor `generate_cards()` into `generate_cards_starter_pack()` | Rename the existing `generate_cards()` method. After `_group_by_major_topic()` call, split sections into `starter_sections = grouped[:STARTER_PACK_INITIAL_SECTIONS]` and `queue_sections = grouped[STARTER_PACK_INITIAL_SECTIONS:]`. Generate cards only for `starter_sections`. Call `_stamp_section_index()` on generated cards. Call `_store_concepts_queue()` to persist queue. Return `(cards, bool(queue_sections), len(grouped))`. | 1.0d | B2-07, B2-08, B2-09 | `teaching_service.py` |
| B2-11 | Fix RC4 fuzzy sort with `_section_index` deterministic sort | Replace the existing fuzzy RC4 sort (`cards.sort(key=lambda c: _rc4_sort_key(c))`) with `cards.sort(key=lambda c: c.get("_section_index", 0))`. Remove or deprecate the `_rc4_sort_key()` helper. | 0.25d | B2-08 | `teaching_service.py` |
| B2-12 | Bump cache version to 11 | Update the `CURRENT_CACHE_VERSION = 11` constant (or equivalent) in `teaching_service.py`. Update `_load_cached_cards()` / the cache version check to use `pt.get("version", 0) < 11` as the miss condition. | 0.25d | B2-09 | `teaching_service.py` |
| B2-13 | Implement `generate_next_section_cards()` method | New `async def generate_next_section_cards(self, session_id: UUID, db: AsyncSession) -> tuple[list[dict], bool, int, int, str]`. Steps: `SELECT ... FOR UPDATE` on session row; parse `presentation_text`; idempotency check on `generated_sections`; pop `concepts_queue[0]`; call `_generate_cards_single()` with per-section budget; stamp `_section_index`; append to `cached_cards`; persist updated JSON; return `(new_cards, has_more, sections_total, sections_done, section_name)`. | 1.5d | B2-07, B2-08, B2-09, B2-12 | `teaching_service.py` |
| B2-14 | Update `teaching_router.py` for starter pack response | Update the `POST /sessions/{id}/cards` handler to call renamed `generate_cards_starter_pack()`, unpack 3-tuple return, and populate `has_more_concepts`, `sections_total`, `sections_done` in `CardsResponse`. | 0.5d | B2-04, B2-10 | `teaching_router.py` |
| B2-15 | Add `POST /sessions/{id}/next-section-cards` endpoint to `teaching_router.py` | New route handler: validate session exists and phase is CARDS; call `generate_next_section_cards()`; return `NextSectionCardsResponse`; return `Response(status_code=204)` when queue already empty. Apply `@limiter.limit(RATE_LIMIT_LLM_HEAVY)`. | 0.75d | B2-05, B2-13 | `teaching_router.py` |
| B2-16 | Add `complete-cards` gate in `teaching_router.py` | In the `POST /sessions/{id}/complete-cards` handler, parse `presentation_text`, check `concepts_queue`. If non-empty, return `HTTPException(409, detail="All sections must be delivered before completing cards")`. | 0.25d | B2-09 | `teaching_router.py` |
| B2-17 | Remove `_ADAPTIVE_CARD_CEILING` from `adaptive_router.py` | Delete the `_ADAPTIVE_CARD_CEILING = 20` module-level constant (line 32). Delete the guard block that references it (line 227 and surrounding logic). Recovery cards (Case A) are unlimited. | 0.25d | None | `adaptive_router.py` |
| B2-18 | Add structured log lines for rolling card operations | Add the 8 log entries specified in DLD §7.1 at appropriate locations in `teaching_service.py`. Use `logger.info()` for operational events, `logger.debug()` for trace-level events, `logger.error()` for failures. | 0.25d | B2-13 | `teaching_service.py` |

**Stage 2 total: 7.75 dev-days**

---

### Stage 3 — Testing (`comprehensive-tester`)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| B3-01 | Unit test: `generate_cards_starter_pack()` returns only first 2 sections | Mock `_generate_cards_single()` to return dummy cards tagged by section. Assert response contains cards only for `starter_sections[0]` and `[1]`. Assert `has_more=True`. | 0.5d | B2-10 | `tests/test_hybrid_cards.py` |
| B3-02 | Unit test: `generate_cards_starter_pack()` stores `concepts_queue` correctly | After call, read `session.presentation_text`; parse JSON; assert `concepts_queue` equals `queue_section_ids`; assert `version == 11`. | 0.5d | B2-09, B2-10 | `tests/test_hybrid_cards.py` |
| B3-03 | Unit test: `generate_next_section_cards()` pops one section per call | Three-section concept. Call twice. Assert `concepts_queue` shrinks from 1 to 0 on second call. Assert `has_more_concepts` returns `False` on second call. | 0.75d | B2-13 | `tests/test_hybrid_cards.py` |
| B3-04 | Unit test: idempotency — second call for same section hits cache | Force `generated_sections` to already contain `next_section_id`. Call `generate_next_section_cards()`. Assert `_generate_cards_single()` is NOT called (mock call count = 0). | 0.5d | B2-13 | `tests/test_hybrid_cards.py` |
| B3-05 | Unit test: `_stamp_section_index()` assigns correct integers | 3 sections, 2 cards each. Assert cards from section 0 have `_section_index=0`, section 1 have `_section_index=1`, section 2 have `_section_index=2`. | 0.5d | B2-08 | `tests/test_hybrid_cards.py` |
| B3-06 | Unit test: `_stamp_section_index()` fallback on no match | Card with no `section_title` and no `section_id`. Assert `_section_index == base_index` (does not raise, does not crash). | 0.25d | B2-08 | `tests/test_hybrid_cards.py` |
| B3-07 | Unit test: token budget `_compute_per_section_budget()` uses raised floors | SLOW profile, 1 section. Assert return value >= 6000. NORMAL, 1 section. Assert >= 4500. FAST, 1 section. Assert >= 3000. | 0.25d | B2-07 | `tests/test_hybrid_cards.py` |
| B3-08 | Unit test: cache version mismatch triggers regeneration | Set `presentation_text = '{"version": 10, ...}'`. Call `generate_cards_starter_pack()`. Assert `_generate_cards_single()` called (cache miss path). Assert output `presentation_text.version == 11`. | 0.5d | B2-12 | `tests/test_hybrid_cards.py` |
| B3-09 | Unit test: `LessonCard` schema accepts `question2` field | Construct `LessonCard` with a `question2: CardMCQ` value. Assert no `ValidationError`. Construct without `question2`. Assert defaults to `None`. | 0.25d | B2-03 | `tests/test_schemas.py` |
| B3-10 | Unit test: `CardsResponse` includes new metadata fields | Construct `CardsResponse` with `has_more_concepts=True`, `sections_total=5`, `sections_done=2`. Assert serialized JSON includes all three fields. | 0.25d | B2-04 | `tests/test_schemas.py` |
| B3-11 | Unit test: `NextSectionCardsResponse` schema validation | Construct with all required fields. Assert no `ValidationError`. Assert `section_name` defaults to `""`. | 0.25d | B2-05 | `tests/test_schemas.py` |
| B3-12 | Integration test: full starter pack → rolling fetch flow | Start session; `POST /cards`; assert `has_more_concepts=True`, `sections_done=2`. Call `POST /next-section-cards` until `has_more_concepts=False`. Assert `sections_done == sections_total` at completion. Assert all sub-sections present in accumulated `cached_cards`. | 1.0d | B2-14, B2-15 | `tests/test_hybrid_integration.py` |
| B3-13 | Integration test: concurrent rolling fetch safety | Two simultaneous `POST /next-section-cards` for same session. Assert exactly one LLM call made. Assert no duplicate section in `cached_cards`. Assert no race condition in `concepts_queue`. | 0.75d | B2-13, B2-15 | `tests/test_hybrid_integration.py` |
| B3-14 | Integration test: `complete-cards` gate blocks early exit | Session with non-empty `concepts_queue`. Call `POST /sessions/{id}/complete-cards`. Assert HTTP 409 returned. Assert error detail mentions "all sections". | 0.5d | B2-16 | `tests/test_hybrid_integration.py` |
| B3-15 | Integration test: `adaptive_router` ceiling removed | Start session; generate starter pack; exhaust 20 recovery cards via `POST /complete-card`. Assert no 409 `{"ceiling": true}` response is returned after card 20. | 0.5d | B2-17 | `tests/test_hybrid_integration.py` |
| B3-16 | Unit test: RC4 sort replaced by `_section_index` sort | Generate 6 cards with `_section_index` values [2, 0, 1, 2, 1, 0]. Sort. Assert resulting order is [0, 0, 1, 1, 2, 2]. | 0.25d | B2-11 | `tests/test_hybrid_cards.py` |
| B3-17 | Unit test: `build_cards_system_prompt()` includes `question2` schema | Assert that `build_cards_system_prompt()` output contains the string `"question2"`. Assert it contains `"DUAL-MCQ RULE"`. | 0.25d | B2-06 | `tests/test_hybrid_cards.py` |
| B3-18 | Performance test: `POST /next-section-cards` P95 latency | Run k6 at 50 concurrent sessions, each calling `next-section-cards` once with a mocked LLM response. Assert P95 < 3000ms for server processing overhead. Document LLM latency separately. | 0.5d | B2-15 | `tests/test_perf.py` |

**Stage 3 total: 8.25 dev-days**

---

### Stage 4 — Frontend (`frontend-developer`)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| B4-01 | Add `getNextSectionCards()` API wrapper to `sessions.js` | New `export async function getNextSectionCards(sessionId)` that calls `api.post('/api/v2/sessions/${sessionId}/next-section-cards', {})`. Configure `validateStatus: (s) => s < 500` to handle 204 without Axios throwing. Return `{ cards: [], has_more_concepts: false }` on 204. | 0.25d | B2-15 | `frontend/src/api/sessions.js` |
| B4-02 | Add `hasMoreConcepts`, `sectionsTotal`, `sectionsDone` to `SessionContext` initial state | Add three fields to `initialState` in `SessionContext.jsx`. `hasMoreConcepts: true` (optimistic default). `sectionsTotal: 0`. `sectionsDone: 0`. | 0.25d | None | `SessionContext.jsx` |
| B4-03 | Add `APPEND_CARDS` reducer case | New `case "APPEND_CARDS"` in `sessionReducer`. Re-stamp `index` on incoming cards (`startIdx + i`). Merge into `state.cards`. Update `hasMoreConcepts`, `sectionsTotal`, `sectionsDone`. | 0.5d | B4-02 | `SessionContext.jsx` |
| B4-04 | Add `SET_HAS_MORE_CONCEPTS` reducer case | Single-field state update: `case "SET_HAS_MORE_CONCEPTS": return { ...state, hasMoreConcepts: action.payload }`. | 0.25d | B4-02 | `SessionContext.jsx` |
| B4-05 | Update `CARDS_LOADED` reducer case to extract rolling metadata | When processing the starter pack response, extract `has_more_concepts`, `sections_total`, `sections_done` from payload and set in state. | 0.25d | B4-02 | `SessionContext.jsx` |
| B4-06 | Remove `MAX_ADAPTIVE_CARDS` constant from `SessionContext.jsx` | Search for `MAX_ADAPTIVE_CARDS` (and any import or reference to it). Delete the constant and any conditional logic that uses it. | 0.25d | None | `SessionContext.jsx` |
| B4-07 | Rewrite `goToNextCard()` with 3-case logic | Replace existing `goToNextCard()` implementation with the three-case pseudocode from DLD §9.8: Case A (both MCQs wrong → POST /complete-card), Case B (near end + has_more → background rolling fetch), Case D (mid-batch → recordCardInteraction + NEXT_CARD). Case B is non-blocking: fire-and-forget then advance card. | 1.5d | B4-01, B4-03, B4-04, B4-06 | `SessionContext.jsx` |
| B4-08 | Update `isLastCard` in `CardLearningView.jsx` | Change from `currentCardIndex >= cards.length - 1` to `currentCardIndex >= cards.length - 1 && !hasMoreConcepts`. Destructure `hasMoreConcepts` from context. | 0.25d | B4-02 | `CardLearningView.jsx` |
| B4-09 | Add `question2` swap logic in `CardLearningView.jsx` | Derive `activeQuestion`: if `wrongAttempts >= 1 && card.question2`, use `card.question2`, else use `card.question`. Replace all references to `card.question` in the MCQ render block with `activeQuestion`. | 0.5d | B4-02 | `CardLearningView.jsx` |
| B4-10 | Add section progress indicator to `CardLearningView.jsx` | Add a small `<span>` that renders `t("learning.conceptsProgress", { current: sectionsDone, total: sectionsTotal })` when `sectionsTotal > 0`. Position below the card progress bar. | 0.25d | B4-02 | `CardLearningView.jsx` |
| B4-11 | Update "Finish Cards" button visibility condition | Change the button's visibility guard to `isLastCard && !hasMoreConcepts` (where `isLastCard` is already updated by B4-08). This is the combined condition. | 0.25d | B4-08 | `CardLearningView.jsx` |
| B4-12 | Add `conceptsProgress` key to all 13 locale files | Add `"conceptsProgress": "Section {{current}} of {{total}}"` (and the per-locale translations from DLD §9.10) to each `frontend/src/locales/{lang}.json`. Locales: en, ar, de, es, fr, hi, ja, ko, ml, pt, si, ta, zh. | 0.5d | None | `frontend/src/locales/*.json` (13 files) |

**Stage 4 total: 5.0 dev-days**

---

## 2. Phased Delivery Plan

### Phase 1: Foundation — Configuration and Schemas (Day 1)

**Goal:** All constants, schema changes, and prompt additions are in place with no behavioral change to existing sessions.

Tasks: B2-01, B2-02, B2-03, B2-04, B2-05, B2-06

**Outcome:** `config.py` has new constants. `teaching_schemas.py` accepts `question2`, `has_more_concepts`, `sections_total`, `sections_done`, and the two new response schemas. `prompts.py` generates `question2` in LLM output.

---

### Phase 2: Core Backend Rolling Pipeline (Days 2–4)

**Goal:** `generate_cards_starter_pack()` and `generate_next_section_cards()` are implemented and unit-tested. Cache version 11 is live.

Tasks: B2-07, B2-08, B2-09, B2-10, B2-11, B2-12, B2-13, B2-17, B2-18

**Outcome:** The starter pack generates cards for 2 sub-sections only. The rolling fetch generates one sub-section per call. `_section_index` sort replaces RC4 fuzzy sort. `_ADAPTIVE_CARD_CEILING` is removed.

---

### Phase 3: Router Wiring and Gate (Days 4–5)

**Goal:** New `POST /next-section-cards` endpoint is live. Existing `/cards` endpoint returns rolling metadata. `complete-cards` gate prevents early Socratic transition.

Tasks: B2-14, B2-15, B2-16

**Outcome:** All three backend endpoints are functional end-to-end. The phase state machine enforces correct transitions.

---

### Phase 4: Backend Testing (Days 5–7)

**Goal:** All 18 backend unit and integration tests pass. Performance target confirmed.

Tasks: B3-01 through B3-18 (parallel where independent)

**Outcome:** Full pytest suite green. No regressions on existing tests. `POST /next-section-cards` P95 documented.

---

### Phase 5: Frontend Integration (Days 7–9)

**Goal:** All frontend changes deployed. `question2` swap works without an API call. "Finish Cards" and Socratic chat gated by `has_more_concepts`. Section progress indicator visible.

Tasks: B4-01 through B4-12

**Outcome:** Zero blank-screen scenarios on card navigation. Rolling fetch fires at 2 cards from end. All 13 locales updated. `MAX_ADAPTIVE_CARDS` removed.

---

## 3. Dependencies and Critical Path

```
B2-01 (config constants)
  └─► B2-02 (floor constants)
        └─► B2-07 (_compute_per_section_budget)
              └─► B2-10 (generate_cards_starter_pack)   ←── B2-08 (_stamp_section_index)
              │         └─► B2-14 (router: /cards)            └─► B2-09 (_store_concepts_queue)
              └─► B2-13 (generate_next_section_cards)   ←────── B2-12 (cache version 11)
                        └─► B2-15 (router: /next-section-cards)
                                  └─► B2-16 (complete-cards gate)
                                        └─► [Stage 3 integration tests]
                                                └─► [Stage 4 frontend]
```

**Critical path:** B2-07 → B2-10 → B2-13 → B2-15 → B3-12 → B4-07

**Items that can proceed in parallel:**
- B2-03 + B2-04 + B2-05 (schema changes) — independent of service changes
- B2-06 (prompts) — independent of service changes
- B2-17 (remove ceiling) — independent of rolling pipeline
- B2-11 (sort fix) — independent of rolling pipeline
- B3-09, B3-10, B3-11 (schema unit tests) — can start as soon as schemas are done
- B4-12 (locale files) — fully independent, can be done any time in Stage 4

**External blocking dependencies:** None — no new infrastructure, no Alembic migration, no DevOps involvement.

---

## 4. Definition of Done

### Phase 1 DoD (Foundation)
- [ ] `STARTER_PACK_INITIAL_SECTIONS = 2` and `ROLLING_PREFETCH_TRIGGER_DISTANCE = 2` present in `config.py`
- [ ] `CARDS_MAX_TOKENS_SLOW_FLOOR = 6000`, `CARDS_MAX_TOKENS_NORMAL_FLOOR = 4500`, `CARDS_MAX_TOKENS_FAST_FLOOR = 3000` in `config.py`
- [ ] `LessonCard.question2: CardMCQ | None = None` present in `teaching_schemas.py`
- [ ] `CardsResponse` has `has_more_concepts`, `sections_total`, `sections_done` fields (all with defaults)
- [ ] `NextSectionCardsRequest` and `NextSectionCardsResponse` defined in `teaching_schemas.py`
- [ ] `build_cards_system_prompt()` output contains `"question2"` and `"DUAL-MCQ RULE"`

### Phase 2 DoD (Core Backend Pipeline)
- [ ] `generate_cards_starter_pack()` returns cards for exactly `STARTER_PACK_INITIAL_SECTIONS` sections
- [ ] `_store_concepts_queue()` writes valid v11 JSON to `session.presentation_text`
- [ ] `_stamp_section_index()` stamps correct integer values on all card dicts
- [ ] `generate_next_section_cards()` pops one section from queue per call
- [ ] `generate_next_section_cards()` is idempotent (second call for same section returns cached cards without LLM call)
- [ ] `SELECT ... FOR UPDATE` is used during queue pop to prevent race conditions
- [ ] RC4 fuzzy sort removed; cards sort by `_section_index` integer
- [ ] `CURRENT_CACHE_VERSION == 11`; sessions with `version < 11` trigger regeneration
- [ ] `_ADAPTIVE_CARD_CEILING = 20` and its guard block removed from `adaptive_router.py`
- [ ] All 8 structured log events emit at correct levels

### Phase 3 DoD (Router Wiring)
- [ ] `POST /api/v2/sessions/{id}/cards` returns `has_more_concepts`, `sections_total`, `sections_done`
- [ ] `POST /api/v2/sessions/{id}/next-section-cards` is registered and reachable
- [ ] Returns `200` with `NextSectionCardsResponse` when queue has items
- [ ] Returns `204 No Content` when queue is already empty
- [ ] Returns `409` when session is not in CARDS phase
- [ ] Returns `503` when LLM fails after 3 attempts
- [ ] `POST /sessions/{id}/complete-cards` returns `409` when `concepts_queue` is non-empty

### Phase 4 DoD (Testing)
- [ ] All 18 test cases (B3-01 through B3-18) pass with `pytest -v`
- [ ] Zero regressions on existing `test_card_generation.py` and `test_blueprint_pipeline.py`
- [ ] `POST /next-section-cards` P95 processing time documented
- [ ] Concurrent rolling fetch test confirms no duplicate sections

### Phase 5 DoD (Frontend)
- [ ] `getNextSectionCards()` wrapper handles 204 without throwing
- [ ] `APPEND_CARDS` reducer correctly re-stamps `index` and updates `hasMoreConcepts`
- [ ] `goToNextCard()` Case A fires `POST /complete-card` when `wrongAttempts >= 2`
- [ ] `goToNextCard()` Case B fires rolling fetch at 2 cards from end (non-blocking)
- [ ] `goToNextCard()` Case D records interaction and advances index for all other cases
- [ ] `MAX_ADAPTIVE_CARDS` reference removed from `SessionContext.jsx`
- [ ] "Finish Cards" button hidden when `hasMoreConcepts === true`
- [ ] Socratic chat unreachable until `has_more_concepts === false`
- [ ] `question2` shown after first wrong answer without any API call
- [ ] Section progress indicator shows `"Section X of Y"` in all 13 locales
- [ ] `conceptsProgress` key present in all 13 locale JSON files

---

## 5. Rollout Strategy

### Deployment Approach

No infrastructure changes are required. The rollout is a standard backend + frontend code deploy.

**Backend deploy first:** The new endpoint and schema changes are deployed. The modified `CardsResponse` is backward-compatible (new fields have defaults). Old frontend code receiving the new response will ignore the extra fields without error.

**Frontend deploy second:** Once backend is confirmed healthy (`GET /health` → 200, new endpoint reachable), deploy the frontend bundle.

### Cache Version 11 — Rollout Effect

Bumping `cache_version` to 11 means:

- Any student who has a cached session from before this deploy will have their starter pack regenerated on next visit (one-time cost: ~3-4s, transparent to the student)
- Sessions that already have `version == 11` are served from cache with no change
- There is no data loss — `presentation_text` is regenerated from ChromaDB content

This is an intentional, clean cut-over. No gradual rollout or feature flag is required.

### Rollback Plan

If a critical regression is discovered post-deploy:

1. **Backend rollback:** Redeploy the previous backend image. Old `generate_cards()` is restored. Sessions with `version == 11` in `presentation_text` will be treated as cache miss (version check `< 11` fails); they regenerate with the old bulk-generation path. No data corruption.
2. **Frontend rollback:** Redeploy the previous frontend bundle. Old `SessionContext.jsx` without `hasMoreConcepts` state will not call `next-section-cards`. Silently ignores extra fields in `CardsResponse`.
3. **`_ADAPTIVE_CARD_CEILING` rollback:** If the ceiling removal causes issues, restore the constant in `adaptive_router.py` without touching any other file.

### Monitoring During Rollout

Watch the following immediately after deploy:

| Signal | Tool | Threshold |
|--------|------|-----------|
| `POST /cards` HTTP 5xx rate | Backend logs / metrics | > 1% → investigate |
| `POST /next-section-cards` HTTP 5xx rate | Backend logs | > 2% → consider rollback |
| `cards_starter_latency_ms P95` | Metrics dashboard | > 8000ms → investigate |
| `cards_rolling_latency_ms P95` | Metrics dashboard | > 5000ms → investigate |
| `cards_llm_exhausted` log count | Backend error logs | > 5/minute → escalate |
| Frontend console errors containing "APPEND_CARDS" | Browser error tracking | Any → investigate |

### Post-Launch Validation

Execute the following manual validation checklist within 30 minutes of deploy:

1. **Starter pack timing:** Start a new session on `PREALG.C1.S1`. Confirm cards appear within 4 seconds.
2. **Rolling fetch:** Advance to the second-to-last card in the starter pack. Confirm new cards appear without page reload within 3 seconds.
3. **"Finish Cards" gating:** Confirm "Finish Cards" button is hidden while `sectionsTotal > sectionsDone`. Confirm it appears only after all sections are delivered.
4. **`question2` swap:** Answer a card's MCQ incorrectly. Confirm a different question appears immediately with no loading spinner.
5. **Both MCQs wrong (Case A recovery):** Answer both MCQs incorrectly. Confirm a recovery card is inserted and no 409 `{"ceiling": true}` is returned.
6. **Socratic chat gate:** Confirm the chat phase cannot be reached while `hasMoreConcepts === true`.
7. **Section progress indicator:** Confirm "Section X of Y" text is visible and updates as sections are delivered.
8. **Old session regeneration:** Open a session from before the deploy. Confirm it silently regenerates the starter pack.

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Phase 1: Foundation | Config constants, schema changes, prompt `question2` | 1.75 dev-days | 1 backend developer |
| Phase 2: Core Backend Pipeline | Starter pack split, rolling fetch, `_section_index` sort, cache version, ceiling removal | 4.0 dev-days | 1 backend developer |
| Phase 3: Router Wiring | New endpoint, starter pack response update, `complete-cards` gate | 1.5 dev-days | 1 backend developer |
| Phase 4: Backend Testing | 18 unit and integration tests, perf test | 8.25 dev-days | 1 tester (can run parallel with Stage 4) |
| Phase 5: Frontend | API wrapper, reducer, `goToNextCard()`, `question2` swap, locales | 5.0 dev-days | 1 frontend developer |
| **Total** | **28 tasks across 6 files + 13 locales** | **~20.5 dev-days** | **2–3 engineers** |

**Calendar estimate with 3 engineers (backend + tester + frontend in parallel from Phase 4):** approximately 6–7 working days.

---

## 7. Verification Checklist (15 Items)

This checklist maps to the approved plan. All 15 items must be checked before marking the feature as complete.

| # | Check | Who | When |
|---|-------|-----|------|
| V-01 | `POST /cards` returns `has_more_concepts: true` for a concept with > 2 sub-sections | Tester | Phase 3 complete |
| V-02 | `POST /cards` returns `sections_done: 2` and `sections_total: N` | Tester | Phase 3 complete |
| V-03 | `POST /next-section-cards` decrements `concepts_queue` by 1 per call | Tester | Phase 3 complete |
| V-04 | `POST /next-section-cards` returns `204` when called after all sections delivered | Tester | Phase 3 complete |
| V-05 | `POST /sessions/{id}/complete-cards` returns `409` when queue non-empty | Tester | Phase 3 complete |
| V-06 | Every LLM-generated card in `POST /cards` response has a non-null `question2` | Tester | Phase 2 + Phase 4 complete |
| V-07 | Cards in response are sorted by `_section_index` integer (not fuzzy match) | Tester | Phase 2 complete |
| V-08 | Old session (`presentation_text.version < 11`) regenerates on next `POST /cards` | Tester | Phase 2 complete |
| V-09 | `_ADAPTIVE_CARD_CEILING` constant does not exist in `adaptive_router.py` | Tester | Phase 2 complete |
| V-10 | `MAX_ADAPTIVE_CARDS` constant does not exist in `SessionContext.jsx` | Tester | Phase 5 complete |
| V-11 | "Finish Cards" button invisible while `hasMoreConcepts === true` in browser | Frontend developer | Phase 5 complete |
| V-12 | `question2` displayed after first wrong answer with zero API calls fired | Frontend developer | Phase 5 complete |
| V-13 | Rolling fetch fires at 2nd-to-last card (network tab shows `next-section-cards` request) | Frontend developer | Phase 5 complete |
| V-14 | Section progress indicator shows correct `"Section X of Y"` and increments | Frontend developer | Phase 5 complete |
| V-15 | All 13 locale files contain `conceptsProgress` key with correct `{{current}}` and `{{total}}` placeholders | Frontend developer | Phase 5 complete |

---

## Key Decisions Requiring Stakeholder Input

1. **`STARTER_PACK_INITIAL_SECTIONS` default (2):** For books with very dense concepts (e.g., Calculus sections average 3x longer text than Prealgebra), should this be configurable per book slug in `BOOK_REGISTRY`?
2. **`ROLLING_PREFETCH_TRIGGER_DISTANCE` default (2):** Should this be exposed as a config constant (recommended) or hardcoded? Configuring it allows A/B testing of 1-card vs 2-card lookahead without redeploy.
3. **204 vs 200 for empty queue:** The DLD specifies `204 No Content` for the idempotent case. Confirm this is acceptable to the frontend team — it requires `validateStatus` configuration in Axios (noted in conflict C11).
4. **`STARTER_PACK_MAX_SECTIONS = 50` deprecation:** This constant is currently referenced in `teaching_service.py` line 776. Confirm it should be removed entirely (not just deprecated) before the backend developer deletes it.
5. **Stale session UX notification:** Students with sessions started before this deploy will silently see their starter pack regenerate. Should the frontend show a brief "Your lesson has been updated" banner on regeneration, or should the experience remain silent?
