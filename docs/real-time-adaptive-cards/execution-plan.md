# Execution Plan — Real-Time Adaptive Cards

**Feature slug:** `real-time-adaptive-cards`
**Date:** 2026-03-10
**Author:** Solution Architect

---

## 1. Work Breakdown Structure (WBS)

### Phase 1 — Root Cause Analysis (parallel exploration)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P1-1 | Audit card generation pipeline | Explore `teaching_service.py` end-to-end: `generate_cards()`, `_generate_cards_per_section()`, `_generate_cards_single()`, token budget constants. Identify: (a) where sub-sections are built, (b) whether `_generate_cards_per_section()` existed, (c) `max_tokens` values hardcoded. | 0.5 d | — | Backend |
| P1-2 | Audit adaptive router and cache | Explore `adaptive_router.py` `complete_card()` and `config.py`. Identify: (a) where `json.dumps(existing_cards)` was written without envelope, (b) `_ADAPTIVE_CARD_CEILING` value, (c) whether rate limits were in place. | 0.5 d | — | Backend |
| P1-3 | Audit frontend session context | Explore `SessionContext.jsx`. Identify: (a) whether `REPLACE_UPCOMING_CARD` reducer existed, (b) how `goToNextCard` fired adaptive call, (c) whether `adaptiveCallInFlight` guard existed, (d) whether stale closure on `currentCardIndex` was present. | 0.5 d | — | Frontend |

All three P1 tasks run in parallel (separate Explore subagents).

---

### Phase 2 — Planning

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P2-1 | Design rolling adaptive replace architecture | Produce implementation design: exact code changes per file, reducer shape, envelope format, section-order sort algorithm, keyword scoring algorithm, token budget formula. Write to plan file before touching code. | 0.5 d | P1-1, P1-2, P1-3 | Architecture |

---

### Phase 3 — Backend Fixes (Stage 2)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P3-1 | Add `STARTER_PACK_MAX_SECTIONS` constant and starter pack slice | Add `STARTER_PACK_MAX_SECTIONS: int = 2` to `config.py`. Wire slice in `generate_cards()` after `_group_by_major_topic()`. Add `logger.info` for the limiting event. | 0.25 d | P2-1 | `config.py`, `teaching_service.py` |
| P3-2 | Implement per-section parallel generation with text-driven budget | Implement `_generate_cards_per_section()` as `asyncio.gather` over per-section LLM calls. Compute `text_driven_budget = max(budget//2, min(budget, text_len//3))` per section. Accept `max_tokens_per_section` parameter. | 0.5 d | P2-1 | `teaching_service.py` |
| P3-3 | Implement gap-fill sort via `_section_order_key` | After `all_raw_cards.extend(gap_cards)`, build `sec_order` dict and `_section_order_key()` function. Call `all_raw_cards.sort(key=_section_order_key)`. | 0.25 d | P3-2 | `teaching_service.py` |
| P3-4 | Implement VISUAL card keyword-scoring image fallback | After primary image-assignment pass, iterate VISUAL cards with no images. Score candidates by word overlap. Assign best match from unassigned pool; fall back to all-images pool if unassigned is empty. Log each assignment. | 0.5 d | P3-2 | `teaching_service.py` |
| P3-5 | Fix envelope preservation in `complete_card()` and bump cache version | In `complete_card()`, replace raw `json.dumps(existing_cards)` write with envelope-preserving logic. Add dual-format read for legacy sessions. Bump `_CARDS_CACHE_VERSION = 3` in `generate_cards()`. | 0.25 d | P3-1 | `adaptive_router.py`, `teaching_service.py` |

---

### Phase 4 — Testing (Stage 3)

All tests added to `backend/tests/test_card_generation.py` (Groups 13–18), building on existing 74 tests to reach 93 total.

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P4-1 | Group 13: Cache version busting (4 tests) | `test_cache_hit_v3`, `test_cache_bust_v1`, `test_cache_bust_v2`, `test_cache_bust_missing_key`. Mock `session.presentation_text`. Assert regeneration vs. return. | 0.25 d | P3-5 | Tests |
| P4-2 | Group 14: Starter pack slicing (3 tests) | `test_starter_pack_2_sections_of_5`, `test_starter_pack_no_limit_for_short_concept`, `test_starter_pack_log_event`. Assert slice length; assert no slice when sections <= 2; assert log output. | 0.25 d | P3-1 | Tests |
| P4-3 | Group 15: Text-driven token budget (4 tests) | `test_budget_short_section_uses_floor`, `test_budget_long_section_uses_ceiling`, `test_budget_normal_section_uses_text_heuristic`, `test_budget_profile_slow_higher_ceiling`. Parametrised over section text lengths. | 0.25 d | P3-2 | Tests |
| P4-4 | Group 16: Gap-fill sort (3 tests) | `test_gap_fill_no_sort_needed`, `test_gap_fill_out_of_order_sorted`, `test_gap_fill_unknown_section_sent_to_end`. Build mock `all_raw_cards` with and without section-title matches; assert sort result. | 0.25 d | P3-3 | Tests |
| P4-5 | Group 17: VISUAL image fallback (3 tests) | `test_visual_fallback_assigns_best_keyword_match`, `test_visual_fallback_pool_exhaustion_shares`, `test_non_visual_card_not_affected`. Build mock image pools and VISUAL/non-VISUAL cards. | 0.25 d | P3-4 | Tests |
| P4-6 | Group 18: Envelope preservation (2 tests) | `test_envelope_preserved_after_adaptive_append`, `test_legacy_list_read_and_written_correctly`. Mock `session.presentation_text` in both formats; call `complete_card()` endpoint handler; assert written JSON retains or lacks envelope. | 0.25 d | P3-5 | Tests |

---

### Phase 5 — Frontend (Stage 4)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P5-1 | Add `adaptiveCallInFlight` state field | Add `adaptiveCallInFlight: false` to `initialState`. Add `ADAPTIVE_CALL_STARTED` and `ADAPTIVE_CALL_DONE` reducer cases. | 0.1 d | P2-1 | `SessionContext.jsx` |
| P5-2 | Implement `REPLACE_UPCOMING_CARD` reducer | Add reducer case: target `currentCardIndex + 1`; replace if slot exists, append otherwise. Re-stamp `index` field. Clear `adaptiveCardLoading`, `adaptiveCallInFlight`, `motivationalNote`, `learningProfileSummary`, `adaptationApplied`. | 0.25 d | P5-1 | `SessionContext.jsx` |
| P5-3 | Rewrite `goToNextCard` with concurrency guard and replace dispatch | Dispatch `NEXT_CARD` first (immediate). Show loading only if `currentCardIndex >= cards.length - 1`. Check `adaptiveCallInFlight`; if set, record interaction only. Otherwise dispatch `ADAPTIVE_CALL_STARTED`, call `completeCardAndGetNext`, dispatch `REPLACE_UPCOMING_CARD`. Always dispatch `ADAPTIVE_CALL_DONE` in `finally`. Fix `useCallback` deps to include `currentCardIndex` and `adaptiveCallInFlight`. | 0.5 d | P5-2 | `SessionContext.jsx` |

---

### Phase 6 — Infrastructure Verification (Stage 0)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P6-1 | Verify rate limiter on `complete-card` | Confirm `@limiter.limit("60/minute")` is applied to the `complete_card` function. Confirm `@limiter.limit("10/minute")` is on `generate_lesson`. If missing, add them. | 0.1 d | P3-5 | `adaptive_router.py` |
| P6-2 | Verify test infrastructure | Confirm `pytest`, `pytest-asyncio`, and `httpx` are in `requirements.txt`. Confirm `conftest.py` provides async DB session fixture. If missing, add entries. | 0.1 d | — | `requirements.txt`, `conftest.py` |

---

## 2. Phased Delivery Plan

### Phase 1 — Root Cause Analysis (Day 1, morning)
Run three parallel Explore subagents to audit the codebase. Each agent reads its assigned files and produces a written findings summary. No code changes.

**Acceptance:** Findings confirm or revise the assumptions in the DLD. Any discrepancy must update the DLD before implementation begins.

---

### Phase 2 — Planning (Day 1, afternoon)
Single Plan agent produces the detailed implementation list. Writes it to a `.plan` file. No code changes until this is approved.

**Acceptance:** Plan reviewed and approved by the lead engineer.

---

### Phase 3 — Backend Fixes (Day 2)
Backend Developer agent implements P3-1 through P3-5 in sequence (each depends on the prior). Each change is isolated and testable individually.

**Acceptance criteria:**
- `generate_cards()` called on a 6-section concept returns cards from exactly 2 sections.
- `generate_cards()` called on a cached v1 session regenerates (does not return stale).
- `complete_card()` called after `generate_cards()` writes a JSON string whose `cache_version` is still 3.
- VISUAL card in the response has at least one image.
- Gap-fill cards appear in section order.

---

### Phase 4 — Testing (Day 3)
Comprehensive Tester agent writes all 19 new tests (Groups 13–18). Tests must pass against the Phase 3 implementation. No new code changes — test failures must be fixed in Phase 3 code.

**Acceptance criteria:**
- All 93 tests pass (`pytest backend/tests/test_card_generation.py`).
- No `xfail` markers used for new tests.
- Coverage on `teaching_service.py` new code paths >= 90%.

---

### Phase 5 — Frontend (Day 3, parallel with Phase 4)
Frontend Developer agent implements P5-1 through P5-3. Can run in parallel with Phase 4 since they target different files.

**Acceptance criteria:**
- Clicking "Next" on a card advances immediately; no blocking wait.
- After advancing, the adaptive card arrives and replaces the next slot silently.
- If the student clicks "Next" twice before the first adaptive call returns, only one LLM call is made; the second click only records the interaction.
- `ADAPTIVE_CARD_ERROR` on LLM failure does not crash the session.

---

### Phase 6 — Infrastructure Verification (Day 1, parallel with Phase 1)
Devops Engineer agent confirms test infra and rate limiters are in place.

**Acceptance criteria:**
- `pytest` and `pytest-asyncio` present in `requirements.txt`.
- Rate limit decorators confirmed on both endpoints.

---

## 3. Dependencies and Critical Path

```
P1-1 ─┐
P1-2 ─┼─► P2-1 ─► P3-1 ─► P3-2 ─► P3-3 ─► P3-4 ─► P3-5 ─► P4-1..P4-6
P1-3 ─┘                                                       P5-1 ─► P5-2 ─► P5-3

P6-1, P6-2 run in parallel with Phase 1 (no dependencies)
Phase 4 and Phase 5 run in parallel (different files)
```

**Critical path:** P1-x → P2-1 → P3-1 → P3-2 → P3-3 → P3-4 → P3-5

The backend fix chain is the critical path. Frontend changes (P5) can be developed in parallel from Day 2 once the API contract is confirmed, since the `REPLACE_UPCOMING_CARD` reducer and `goToNextCard` changes do not depend on backend test results.

**External blockers:**
- None. All changes are within the existing codebase; no new external dependencies.

---

## 4. Definition of Done

### Phase-level DoD

**Phase 3 (Backend) — Complete when:**
- [ ] `STARTER_PACK_MAX_SECTIONS` constant exists in `config.py`
- [ ] `generate_cards()` slices sub-sections to `[:STARTER_PACK_MAX_SECTIONS]` after `_group_by_major_topic()`
- [ ] `_generate_cards_per_section()` uses `asyncio.gather` for parallel LLM calls
- [ ] Token budget uses `max(budget//2, min(budget, text_len//3))` per section
- [ ] Gap-fill cards are re-sorted by `_section_order_key` before returning
- [ ] VISUAL fallback assigns best keyword match from unassigned pool
- [ ] `_CARDS_CACHE_VERSION = 3` in `generate_cards()`
- [ ] `complete_card()` writes the envelope back with `cache_version` intact
- [ ] All existing tests still pass

**Phase 4 (Tests) — Complete when:**
- [ ] 19 new tests written in Groups 13–18
- [ ] All 93 tests pass without `xfail`
- [ ] No new `print()` statements in test code

**Phase 5 (Frontend) — Complete when:**
- [ ] `adaptiveCallInFlight` field in `initialState`
- [ ] `ADAPTIVE_CALL_STARTED` and `ADAPTIVE_CALL_DONE` reducer cases present
- [ ] `REPLACE_UPCOMING_CARD` reducer case present with replace-or-append logic
- [ ] `goToNextCard` dispatches `NEXT_CARD` before awaiting LLM call
- [ ] `goToNextCard` `useCallback` deps include `currentCardIndex` and `adaptiveCallInFlight`
- [ ] `ADAPTIVE_CALL_DONE` dispatched in `finally` block
- [ ] Manual test: rapid double-click "Next" produces exactly one adaptive API call

### Feature-level DoD
- [ ] A student session with a 6-section concept returns a starter pack of 2 sections at load time
- [ ] Each card advance triggers a background adaptive call that personalises the next card
- [ ] Page refresh on an in-progress session returns the cached cards including previously generated adaptive cards (no `cache_version` dropped)
- [ ] VISUAL cards in the response always include an image
- [ ] Gap-fill cards appear in curriculum section order
- [ ] No blank screen on card index out of bounds
- [ ] All 93 backend tests pass
- [ ] No regressions on existing Socratic, mastery, or remediation flows

---

## 5. Rollout Strategy

### Deployment Approach
Standard deploy — no feature flag required. The cache version bump (`_CARDS_CACHE_VERSION = 3`) is the rollout mechanism: existing sessions regenerate on first access, new sessions generate correctly from the start.

### Cache Version Impact
Any session stored with `cache_version < 3` (or no `cache_version` key) will be regenerated on the student's next visit. This triggers one additional LLM call per affected session. At current usage scale this is acceptable. Monitor the `[starter-pack] concept=X limiting` log lines in the first hour post-deploy to confirm regeneration volume is within expected bounds.

### Rollback Plan
If a critical regression is detected post-deploy:
1. Revert `_CARDS_CACHE_VERSION` to 2 in `generate_cards()` — this restores cache hits for v2 sessions without a full deploy rollback.
2. If deeper rollback is needed, revert the commit and redeploy. Sessions regenerate again (one more LLM call per session).

There is no DB migration in this feature. Rollback does not require any schema reversal.

### Post-Launch Validation

| Check | How | Target |
|-------|-----|--------|
| Starter pack logs appearing | Search `[starter-pack]` in backend logs | Within 5 minutes of first student session |
| Adaptive cards replacing slots | Search `REPLACE_UPCOMING_CARD` dispatches in browser console (dev) | Per-card on every Next click |
| No stale-cache regeneration loops | Confirm `[cards-generated]` log fires once per session, not on every page load | Zero repeat generations for same session |
| VISUAL fallback rate | Count `[image-fallback]` log lines as % of VISUAL cards | Should be < 30% if LLM consistently sets `image_indices` |
| Envelope preservation | Verify `cache_version: 3` present in `presentation_text` after an adaptive append | All sessions |

### LLM Cost Increase
This feature increases LLM usage from 1 call per session start to 1 call per session start + 1 call per card advance. For a 10-card session this means up to 10 additional `gpt-4o-mini` calls. At current pricing this is negligible, but should be monitored in the first week post-launch.

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Phase 1 — Root Cause Analysis | 3 parallel Explore audits | 0.5 d (parallel) | 1 Backend Dev, 1 Frontend Dev (or 1 with both skills) |
| Phase 2 — Planning | Architecture and implementation plan | 0.5 d | 1 Solution Architect |
| Phase 3 — Backend Fixes | 5 targeted fixes across 3 files | 1.75 d | 1 Backend Developer |
| Phase 4 — Testing | 19 new pytest tests, Groups 13–18 | 1.5 d | 1 Tester |
| Phase 5 — Frontend | `SessionContext.jsx` rolling replace | 0.85 d | 1 Frontend Developer |
| Phase 6 — Infra Verification | Rate limits, test infra check | 0.2 d | 1 DevOps / Backend Dev |
| **Total** | | **~5.3 engineer-days** | **2 engineers (back + front) + 1 tester** |

With 2 engineers (one backend, one frontend) running Phases 3 and 5 in parallel, and testing overlapping with Day 3 afternoon:

**Estimated calendar time: 3 working days.**

---

## Key Decisions Requiring Stakeholder Input

1. **Starter pack size**: Should `STARTER_PACK_MAX_SECTIONS` be raised to 3 for longer concepts (e.g., pre-algebra chapters with 8+ sections)? Currently set to 2.
2. **Adaptive ceiling**: `_ADAPTIVE_CARD_CEILING = 20` lives in `adaptive_router.py` as a module constant. Should it be promoted to `config.py` to make it operator-configurable without code changes?
3. **Cost monitoring**: No automated LLM cost alert exists. Confirm whether a spend threshold alert should be set up as part of this rollout (devops-engineer scope).
4. **VISUAL fallback quality**: Keyword overlap scoring is a best-effort heuristic. If product decides that an image-less VISUAL card is preferable to a topically mismatched image, the fallback can be disabled by removing the `RC5` block in `teaching_service.py`.
