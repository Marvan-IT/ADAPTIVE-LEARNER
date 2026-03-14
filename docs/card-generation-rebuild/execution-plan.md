# Execution Plan: Card Generation Rebuild

**Feature slug:** `card-generation-rebuild`
**Date:** 2026-03-09
**Author:** Solution Architect

---

## 1. Work Breakdown Structure (WBS)

| ID | Title | Description | Est. (days) | Depends On | Component |
|----|-------|-------------|-------------|------------|-----------|
| P1-1 | Add token-budget constants to `config.py` | Add `CARDS_MAX_TOKENS_SLOW`, `CARDS_MAX_TOKENS_SLOW_FLOOR`, `CARDS_MAX_TOKENS_SLOW_PER_SECTION`, and equivalent constants for NORMAL and FAST tiers. Total: 9 new constants. | 0.25 | — | `config.py` |
| P1-2 | Fix A1 — wire `_group_by_major_topic()` into `generate_cards()` | Replace the direct use of `_parse_sub_sections()` result with a two-step: capture raw sections, then group. Add INFO log line. | 0.25 | — | `teaching_service.py` |
| P1-3 | Fix A2 — fix fallback dict key `"content"` → `"text"` | One-character change in the `if not sub_sections:` fallback. | 0.1 | P1-2 (same block) | `teaching_service.py` |
| P1-4 | Fix C — add `max_tokens` param to `_generate_cards_single()` | Change signature, change internal `_chat()` call from `max_tokens=8000` to `max_tokens=max_tokens`, set default to `12_000`. | 0.25 | P1-1 | `teaching_service.py` |
| P1-5 | Fix B — compute adaptive `max_tokens` in `generate_cards()` | Insert the profile-tier formula block before the `_generate_cards_single()` call. Import new constants from `config.py`. Update the call site to pass `max_tokens=adaptive_max_tokens`. | 0.5 | P1-1, P1-4 | `teaching_service.py` |
| P2-1 | Fix D — add CARD DENSITY block to `_build_card_profile_block()` | Append density instruction to SUPPORT and ACCELERATE `parts.append()` calls. Do not add for NORMAL profile. | 0.25 | — | `prompts.py` |
| P2-2 | Fix F — strengthen COMPLETE COVERAGE line in system prompt | Replace the existing soft "COMPLETE COVERAGE" line with the NON-NEGOTIABLE version that cross-references the checklist. | 0.1 | — | `prompts.py` |
| P2-3 | Fix E — add COMPLETENESS REQUIREMENT checklist to user prompt | Insert the dynamic checklist-building block immediately before `return prompt` in `build_cards_user_prompt()`. | 0.25 | — | `prompts.py` |
| P3-1 | Unit tests: Fix A (`_group_by_major_topic` and fallback key) | Tests UT-A1, UT-A2, UT-A3 as specified in DLD §9. | 0.5 | P1-2, P1-3 | `tests/test_card_generation.py` |
| P3-2 | Unit tests: Fix B+C (token budget formula and param) | Tests UT-B1–B4, UT-C1, UT-C2. Use `unittest.mock.patch` on `_chat()`. | 0.5 | P1-4, P1-5 | `tests/test_card_generation.py` |
| P3-3 | Unit tests: Fix D+E+F (prompts) | Tests UT-D1–D3, UT-E1, UT-E2, UT-F1. Call prompt functions directly with known inputs; assert on output substrings. | 0.5 | P2-1, P2-2, P2-3 | `tests/test_card_generation.py` |
| P3-4 | Integration test: full `generate_cards()` with mocked LLM | Tests INT-1 and INT-2. Mock `_chat()` to return a valid card JSON. Assert on `_chat()` call args (max_tokens) and prompt content. | 0.5 | P1-2 through P2-3 | `tests/test_card_generation.py` |
| P3-5 | Regression: confirm existing card schema tests still pass | Run the full `tests/test_adaptive_tutor.py` and `tests/test_adaptive_upgrade.py` suites. Fix any test that assumed `max_tokens=8000`. | 0.25 | P1-4 | `tests/` |
| P4-1 | Manual smoke test on a real concept | Run `generate_cards()` against the live dev DB for concept "whole-numbers" (or equivalent prealgebra concept with 50+ raw sections). Inspect logs for `raw=57 grouped=9`. Inspect card deck for completeness. | 0.5 | All P1, P2 tasks | Dev environment |
| P4-2 | Monitor first 10 production sessions post-deploy | Watch logs for `cards token_budget` and `cards section_grouping` lines. Confirm grouped count is < raw count. Confirm SLOW profiles receive `max_tokens >= 8000`. | 0.25 | Deploy | Logs / observability |

**Total estimated effort: 4.65 engineer-days**

---

## 2. Phased Delivery Plan

### Phase 1 — Service Layer Fixes (Days 1–2)

Implement all `teaching_service.py` changes. These are the highest-priority fixes because Fix A (dead code) and Fix A2 (KeyError) can cause silent data loss or runtime errors today.

Tasks: P1-1, P1-2, P1-3, P1-4, P1-5

Exit criterion: `generate_cards()` can be called locally with a real or mocked concept and produce a grouped section list with an adaptive `max_tokens`. Manual log inspection confirms the two new INFO lines appear.

### Phase 2 — Prompt Layer Fixes (Day 2, parallel with Phase 1 tail)

Implement all `prompts.py` changes. These can be developed independently of Phase 1 (different file, no shared state).

Tasks: P2-1, P2-2, P2-3

Exit criterion: Calling `build_cards_system_prompt()` with a SLOW profile returns a string containing "CARD DENSITY" and "2–3 cards". Calling `build_cards_user_prompt()` with 5 sections returns a string containing "COMPLETENESS REQUIREMENT" and all 5 section titles.

### Phase 3 — Tests (Days 2–3)

Write the full unit and integration test suite for all six fixes. Tests are written against the new behaviour; no test should assume `max_tokens=8000` anymore.

Tasks: P3-1, P3-2, P3-3, P3-4, P3-5

Exit criterion: All new tests pass. All pre-existing tests pass. `pytest backend/tests/test_card_generation.py -v` exits 0.

### Phase 4 — Hardening and Validation (Day 3)

Manual smoke test on the real dev environment. Deploy to staging, monitor first 10 sessions, confirm logs are healthy.

Tasks: P4-1, P4-2

Exit criterion: Log evidence that grouping and token budget are both working for at least one slow-learner session and one fast-learner session.

---

## 3. Dependencies and Critical Path

```
P1-1 (constants)
  ├─► P1-4 (Fix C: param) ─► P1-5 (Fix B: budget) ─► P3-2 (tests B/C) ─► P3-4 (integration) ─► P4-1
  │
P1-2 (Fix A1: grouper wire)
  └─► P1-3 (Fix A2: key fix) ─► P3-1 (tests A) ─► P3-4 (integration) ─► P4-1

P2-1 (Fix D: density) ─► P3-3 (tests D/E/F)
P2-2 (Fix F: coverage) ─┘
P2-3 (Fix E: checklist) ─┘

P3-5 (regression) — can run in parallel with P3-1 through P3-4
```

**Critical path:** P1-1 → P1-4 → P1-5 → P3-2 → P3-4 → P4-1 → P4-2

**Blocking external dependencies:** None. All changes are internal to two Python files and `config.py`. No migrations required. No frontend deployment required.

**Parallelisation opportunity:** Phase 1 (service layer) and Phase 2 (prompt layer) can be developed in parallel by two engineers on separate branches, then merged before Phase 3 integration tests.

---

## 4. Definition of Done

### Phase 1 DoD
- [ ] `_group_by_major_topic()` is called in `generate_cards()` after `_parse_sub_sections()`.
- [ ] Fallback `sub_sections` dict uses key `"text"`, not `"content"`.
- [ ] `_generate_cards_single()` signature includes `max_tokens: int = 12_000`.
- [ ] Internal `_chat()` call inside `_generate_cards_single()` uses the parameter, not the literal `8000`.
- [ ] `generate_cards()` computes `adaptive_max_tokens` from section count and profile tier.
- [ ] `generate_cards()` passes `adaptive_max_tokens` to `_generate_cards_single()`.
- [ ] All 9 new constants are in `config.py` with descriptive comments.
- [ ] Two new INFO log lines are present (section_grouping, token_budget).
- [ ] No `print()` statements introduced.
- [ ] Code reviewed by one other engineer.

### Phase 2 DoD
- [ ] `_build_card_profile_block()` SUPPORT branch includes "CARD DENSITY: Generate 2–3 cards per section."
- [ ] `_build_card_profile_block()` ACCELERATE branch includes "CARD DENSITY: Generate 1–2 cards per section."
- [ ] NORMAL profile receives no CARD DENSITY instruction.
- [ ] `build_cards_system_prompt()` COMPLETE COVERAGE line contains "NON-NEGOTIABLE".
- [ ] `build_cards_user_prompt()` appends a numbered COMPLETENESS REQUIREMENT checklist using actual section titles.
- [ ] Checklist is appended after all other `prompt +=` blocks (last instruction before return).
- [ ] Code reviewed.

### Phase 3 DoD
- [ ] All 15 unit tests (UT-A1 through UT-F1) pass.
- [ ] Integration tests INT-1 and INT-2 pass.
- [ ] Regression tests REG-1 and REG-2 pass (all pre-existing card/session tests green).
- [ ] `pytest backend/tests/ -v` exits 0 with no warnings about deprecated `max_tokens=8000`.
- [ ] Test file added: `backend/tests/test_card_generation.py`.

### Phase 4 DoD
- [ ] Dev environment smoke test: concept with 40+ raw sections produces a `grouped` count of 8–15 in logs.
- [ ] Dev environment smoke test: SLOW learner session shows `max_tokens >= 8000` in logs.
- [ ] Dev environment smoke test: FAST/STRONG learner session shows `max_tokens <= 8000` in logs.
- [ ] First 10 post-deploy production sessions show no `KeyError` or JSON truncation errors in logs.
- [ ] No increase in `_salvage_truncated_json` log events compared to pre-fix baseline (truncation fixed, not masked).

---

## 5. Rollout Strategy

### Deployment approach
Standard direct deployment (no feature flag required). All fixes are internal to the card generation path; they do not change the API contract, the DB schema, or the frontend. A feature flag would add complexity without risk reduction.

### Rollback plan
All changes are confined to two Python files (`teaching_service.py`, `prompts.py`) and `config.py`. Git revert of the three files restores the previous behaviour instantly. No DB migration to reverse.

**Rollback trigger conditions:**
- Log evidence that `_group_by_major_topic()` is absorbing major topic headings (confirmed by `grouped << raw` with `grouped < 3` on a concept known to have many sections).
- Increase in LLM timeout errors (would indicate `max_tokens` ceiling is too high for the timeout setting — revert or lower `CARDS_MAX_TOKENS_SLOW`).
- Increase in JSON parse failures not salvaged by `_salvage_truncated_json()`.

### Post-launch validation checklist
- [ ] Within 1 hour of deploy: check logs for at least one `cards section_grouping` event with `raw > grouped`.
- [ ] Within 1 hour of deploy: check logs for at least one `cards token_budget` event.
- [ ] Within 24 hours: confirm no increase in `KeyError` or `ValueError` in card generation path.
- [ ] Within 24 hours: manually inspect one slow-learner card deck in the admin view and confirm all major topics have cards.
- [ ] Within 48 hours: confirm OpenAI usage dashboard shows expected cost increase for slow-learner sessions (2x is expected and accepted per HLD §8).

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|-------------------|
| Phase 1 — Service Layer | P1-1 through P1-5 (Fix A, B, C in `teaching_service.py` + constants) | 1.35 days | 1 backend developer |
| Phase 2 — Prompt Layer | P2-1 through P2-3 (Fix D, E, F in `prompts.py`) | 0.6 days | 1 backend developer (parallelisable with Phase 1) |
| Phase 3 — Tests | P3-1 through P3-5 (15 unit tests + integration + regression) | 2.25 days | 1 backend developer or 1 tester |
| Phase 4 — Hardening | P4-1, P4-2 (smoke test + monitoring) | 0.75 days | 1 backend developer + access to dev logs |
| **Total** | **14 tasks** | **4.65 engineer-days** | **1–2 engineers; ~2.5 calendar days with 2 engineers** |

---

## Key Decisions Requiring Stakeholder Input

1. **Cost acceptance for slow-learner sessions** — Increasing `max_tokens` from 8,000 to up to 16,000 for SLOW/STRUGGLING profiles approximately doubles the OpenAI API cost per card-generation call for those students. Product and finance should confirm this is acceptable before Phase 1 is merged to main.

2. **Smoke-test concept selection** — Phase 4 manual smoke test requires a specific concept ID known to have 40+ raw sections (e.g., a full chapter concept from the prealgebra book). The backend developer should confirm the concept ID with the data team before starting P4-1.

3. **Parallelisation decision** — If two engineers are available, Phases 1 and 2 can run in parallel (different files, no conflicts), compressing the calendar timeline to approximately 1.5 days before testing begins. If only one engineer is available, sequential execution is the safer path.
