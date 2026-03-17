# Pre-Deployment Audit Fixes — Execution Plan

**Feature slug:** `pre-deployment-audit-fixes`
**Date:** 2026-03-17
**Author:** solution-architect
**Status:** Stages 0 and 1 complete; Stages 2–4 pending

---

## 1. Work Breakdown Structure (WBS)

### Stage 0 — Infrastructure (devops-engineer)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| S0-01 | Confirm no migration needed | Verify that none of the audit fixes introduce schema changes; document confirmation in this plan | 0.25 d | — | `db/models.py`, `config.py` |

**Status: Complete.** Confirmed — no schema changes, no Alembic migration required, no new environment variables.

---

### Stage 1 — Design (solution-architect)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| S1-01 | HLD | Executive summary, requirements, context, ADRs, risks | 0.5 d | — | `docs/` |
| S1-02 | DLD | Component breakdown, fix specs, sequence diagrams, testing strategy | 1.0 d | S1-01 | `docs/` |
| S1-03 | Execution plan | WBS, phases, DoD, rollout | 0.5 d | S1-02 | `docs/` |

**Status: Complete** (this document).

---

### Stage 2 — Backend (backend-developer)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| B-01 | Fix 1: Remove FUN/RECAP reorder block | Verify the type-based reorder code is absent; if any residual block exists, delete it; confirm `_section_index` sort is sole authority | 0.25 d | S1-02 | `teaching_service.py` |
| B-02 | Fix 2A: Broaden image filter | Remove `image_type in ("DIAGRAM", "FORMULA")` restriction; confirm checklist-keyword exclusion and `is_educational` check remain | 0.25 d | S1-02 | `teaching_service.py` |
| B-03 | Fix 2B: Image fallback retain filename | When primary and fallback file lookups both fail, keep indexed filename in image dict rather than dropping | 0.5 d | S1-02 | `knowledge_service.py` |
| B-04 | Fix 4A: Expected-time floor | Confirm `expected_time = max(baseline_time, 90.0)` present in `build_blended_analytics()`; add if absent | 0.25 d | S1-02 | `adaptive_engine.py` |
| B-05 | Fix 4B: Conservative cap at 2 | Lower consecutive-signal threshold for mode switching from 5 to 2; extract to named constant in `config.py` | 0.5 d | S1-02 | `adaptive_engine.py`, `config.py` |
| B-06 | Fix 5A: Property batching wire-up | Confirm `_batch_consecutive_properties()` is called in `generate_cards()` before section iteration; add if absent | 0.25 d | S1-02 | `teaching_service.py` |
| B-07 | P1-B: Image extractor warning | Add `logger.warning("Failed to extract image xref=%d from page=%d: %s", xref, page_num, e)` to silent catch at line ~42 | 0.25 d | S1-02 | `image_extractor.py` |
| B-08 | P2: Dead function removal | Grep each of the 5 audit-identified dead functions; confirm zero call sites; delete confirmed dead ones | 0.5 d | S1-02 | `teaching_service.py` |
| B-09 | P2: Dead constant removal | Grep each of the 5 audit-identified dead constants; confirm zero references; delete confirmed dead ones | 0.25 d | S1-02 | `config.py` |
| B-10 | P3: Extract-images log promotion | Change `logger.debug(...)` to `logger.info(...)` at `extract_images.py:159`; add `as e` to exception binding | 0.25 d | S1-02 | `extract_images.py` |

**Stage 2 total estimated effort: 3.25 developer-days**

---

### Stage 3 — Testing (comprehensive-tester)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| T-01 | Review existing test_bug_fixes.py | Read the untracked `backend/tests/test_bug_fixes.py`; identify any gaps in coverage against the DLD fix specs | 0.5 d | B-01 through B-10 | `test_bug_fixes.py` |
| T-02 | TestCardOrdering — 4 tests | Verify 4 test cases cover FUN high-index, RECAP low-index, mixed types, missing index | 0.25 d | T-01 | `test_bug_fixes.py` |
| T-03 | TestImageFilter — 5 tests | Verify PHOTO, TABLE, FIGURE pass; `is_educational=False` excluded; missing description excluded | 0.25 d | T-01 | `test_bug_fixes.py` |
| T-04 | TestImageFallback — 2 tests | Verify indexed filename retained when file not on disk; verify image not silently dropped | 0.25 d | T-01 | `test_bug_fixes.py` |
| T-05 | TestRecoveryCardInsertion — 2 tests | Pure-Python simulation of REPLACE_UPCOMING_CARD + INSERT_RECOVERY_CARD reducer sequence | 0.5 d | T-01 | `test_bug_fixes.py` |
| T-06 | TestFastModeDetection — 2 tests | Fast student (10s avg, 85s completion) → FAST via 90s floor; non-fast student correct | 0.25 d | T-01 | `test_bug_fixes.py` |
| T-07 | TestConservativeCap — 2 tests | Mode switches after 2 consistent signals (not 5) | 0.25 d | T-01 | `test_bug_fixes.py` |
| T-08 | TestPropertyBatching — 2 tests | 3 consecutive PROPERTY sections merge; non-consecutive do not merge | 0.25 d | T-01 | `test_bug_fixes.py` |
| T-09 | Run full test suite; confirm no regressions | `python -m pytest tests/test_bug_fixes.py -v`; zero failures | 0.25 d | T-02 through T-08 | `test_bug_fixes.py` |

**Stage 3 total estimated effort: 2.5 developer-days**

---

### Stage 4 — Frontend (frontend-developer)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| F-01 | P1-A: Remove `passed` from reducer | Remove `passed` from destructure in `SOCRATIC_RESPONSE` reducer case; change `if (passed \|\| mastered)` to `if (mastered)` | 0.25 d | S1-02 | `SessionContext.jsx` |
| F-02 | P1-A: Remove `passed` from analytics | Change `if (res.data.mastered \|\| res.data.passed)` to `if (res.data.mastered)` in PostHog call | 0.25 d | F-01 | `SessionContext.jsx` |
| F-03 | Fix 3: Verify recovery card dispatch | Read `goToNextCard()` recovery path; confirm REPLACE_UPCOMING_CARD → INSERT_RECOVERY_CARD → NEXT_CARD order; fix if not present | 0.5 d | S1-02 | `SessionContext.jsx` |

**Stage 4 total estimated effort: 1.0 developer-days**

---

## 2. Phased Delivery Plan

### Phase 1 — Foundation (Stage 0 + Stage 1)

**Goal:** Confirm no infrastructure requirements; produce design artifacts.

**Tasks:** S0-01, S1-01, S1-02, S1-03

**Acceptance:** Design documents written to `docs/pre-deployment-audit-fixes/`. No migration created (confirmed not needed). Backend developer has DLD in hand before writing any code.

**Status: Complete.**

---

### Phase 2 — Backend Fixes (Stage 2)

**Goal:** All 10 backend fix tasks implemented and peer-reviewed.

**Tasks:** B-01 through B-10

**Execution order:**
- B-01, B-02, B-06 can run in parallel (all in `teaching_service.py` but non-overlapping lines)
- B-03 is independent (`knowledge_service.py`)
- B-04, B-05 can run in parallel (both in `adaptive_engine.py`)
- B-07, B-10 can run in parallel (separate files)
- B-08, B-09 should run after B-01/B-02/B-06 are complete (to avoid removing a function that a simultaneous edit still references)

**Acceptance:**
- `python -m uvicorn src.api.main:app --reload --port 8889` starts cleanly with no ImportError
- No `grep` hits for deleted function/constant names across `backend/src/`
- `logger.warning` appears in image extractor logs during a pipeline test extraction

---

### Phase 3 — Test Suite Completion (Stage 3)

**Goal:** `test_bug_fixes.py` covers all 5 fix classes with passing tests; no regressions in other test files.

**Tasks:** T-01 through T-09

**Acceptance:**
- `python -m pytest tests/test_bug_fixes.py -v` → 0 failures, 0 errors
- All test class names match the fix IDs in the DLD (TestCardOrdering, TestImageFilter, etc.)
- Test descriptions clearly state the business criterion being verified

---

### Phase 4 — Frontend Fixes (Stage 4)

**Goal:** `passed` field removed from all consumption sites; recovery card dispatch verified.

**Tasks:** F-01, F-02, F-03

**Execution order:** F-01 then F-02 (F-02 depends on confirming the correct condition after F-01); F-03 is independent.

**Acceptance:**
- `grep -n "passed" frontend/src/context/SessionContext.jsx` returns zero results outside of comments
- Manual test: complete a Socratic session to mastery (score >= 70) → completion UI appears
- Manual test: answer both MCQs wrong on a card → recovery card appears as next card

---

### Phase 5 — Release (Hardening + Rollout)

**Goal:** Deploy to production with confidence.

**Tasks:** Code review for all changes; final smoke test against production database.

See Rollout Strategy section below.

---

## 3. Dependencies and Critical Path

```
S0-01 (confirmed complete)
    │
S1-01 → S1-02 → S1-03
    │
    ├──────────────────────────────────────────────────┐
    │                                                   │
    ▼                                                   ▼
B-01, B-02, B-03, B-04,                           F-01, F-02, F-03
B-05, B-06, B-07, B-08,
B-09, B-10
    │
    ▼
T-01 → T-02, T-03, T-04, T-05, T-06, T-07, T-08 (parallel)
    │
    ▼
T-09 (full suite run)
    │
    ▼
RELEASE
```

**Critical path:** S1-02 → B-08/B-09 (dead code removal requires grep verification) → T-09 (full suite) → Release

**Blocking items:**
- B-08 is blocked on confirming the call-site status of `_find_missing_sections` and `_get_checking_messages` (see DLD Section 9, P2 specification). If call sites are confirmed live, these two functions are removed from the deletion list — reducing scope to 3 dead functions.
- T-05 (TestRecoveryCardInsertion) requires the reducer logic to be expressed as pure Python functions for unit testing; if the current frontend logic is tightly coupled to React, the tester will need to extract a pure state-transition function.

**External dependencies:** None. No dependency on external teams or systems.

---

## 4. Definition of Done

### Stage 0 — Infrastructure
- [x] Confirmed: no Alembic migration required
- [x] Confirmed: no new environment variables required
- [x] Confirmed: no new Python dependencies required

### Stage 1 — Design
- [x] `docs/pre-deployment-audit-fixes/HLD.md` written to disk
- [x] `docs/pre-deployment-audit-fixes/DLD.md` written to disk with exact function-level specs
- [x] `docs/pre-deployment-audit-fixes/execution-plan.md` written to disk
- [x] All open questions documented in "Key Decisions Requiring Stakeholder Input" sections

### Stage 2 — Backend
- [ ] All 10 backend tasks implemented
- [ ] No import errors on server start
- [ ] `grep` confirms no call sites for deleted functions and constants
- [ ] Code reviewed by a second developer
- [ ] `git diff` shows net reduction in line count (dead code removed, no compensation bloat)

### Stage 3 — Testing
- [ ] `python -m pytest tests/test_bug_fixes.py -v` passes with 0 failures
- [ ] Test count >= 19 (sum of minimums across all test classes)
- [ ] Each test method has a docstring stating the business criterion
- [ ] No mocking of production database or LLM in any test (all tests are pure unit tests)

### Stage 4 — Frontend
- [ ] Zero `passed` references in `SessionContext.jsx` (excluding code comments)
- [ ] `if (mastered)` is the sole mastery completion gate
- [ ] Recovery card dispatch sequence verified by test or manual walkthrough
- [ ] No new ESLint warnings introduced

### Overall Release DoD
- [ ] All stage-level DoD items checked
- [ ] Smoke test: generate a lesson, answer Socratic questions to mastery, confirm completion screen
- [ ] Smoke test: generate a lesson, answer both MCQs wrong, confirm recovery card appears
- [ ] Image extraction pipeline run on one book confirms `logger.warning` appears for xref errors (or no xref errors, confirming clean data)
- [ ] Backend starts cleanly in production environment

---

## 5. Rollout Strategy

### Deployment Approach

**Method:** Standard rolling deploy. No feature flags required — all fixes are correctness and observability improvements with no user-facing behaviour changes visible in isolation.

**No schema migration:** The deploy does not require `alembic upgrade head`. The database schema is unchanged.

**Cache version:** Already at 14 (set during the FUN/RECAP reorder removal that is already in the codebase). No cache version bump needed for this deploy.

### Rollback Plan

If any fix causes a production regression:

1. **Immediate:** Revert the commit containing the affected fix via `git revert`; redeploy.
2. **Fix-specific rollback knobs:**
   - Fix 4A/4B: Change `expected_time` floor and conservative cap constants in `config.py` and redeploy (no code change needed — just constant updates).
   - P2 dead code removal: If a deleted function turns out to be called (import error), restore from git history and redeploy within minutes.
   - P1-A: If `mastered` condition causes completion UI regression, restore `passed` destructure temporarily; this is a two-line change.

### Monitoring Setup for Launch

**Existing dashboards apply.** No new metrics are introduced. Watch for:

- `logger.warning` entries containing `"Failed to extract image xref"` — indicates PDF corruption in the pipeline; not a regression, but now observable.
- `logger.info` entries containing `"Pillow validation skipped"` — expected during pipeline runs; elevated count may indicate data quality issue.
- Card generation logs for `[card-validate]` errors — confirm no increase vs pre-deploy baseline.

### Post-Launch Validation Steps

1. Generate cards for 3 different concepts across 2 books; confirm card order follows curriculum section sequence.
2. Generate cards for a concept with known PHOTO/TABLE images; confirm images appear in cards.
3. Complete a Socratic session to mastery; confirm `if (mastered)` gate correctly triggers completion UI.
4. Answer both MCQs on a card incorrectly; confirm recovery card is inserted as the next card.
5. Observe adaptive mode for a simulated fast student (consecutive fast completions); confirm FAST mode triggers after 2 interactions.

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Phase 1 — Foundation | S0-01, S1-01 through S1-03 | 2.25 d | solution-architect (1) |
| Phase 2 — Backend Fixes | B-01 through B-10 | 3.25 d | backend-developer (1) |
| Phase 3 — Testing | T-01 through T-09 | 2.5 d | comprehensive-tester (1) |
| Phase 4 — Frontend Fixes | F-01 through F-03 | 1.0 d | frontend-developer (1) |
| Phase 5 — Release | Code review, smoke tests, deploy | 0.5 d | All agents (brief) |
| **Total** | | **9.5 d** | **4 agents** |

**Parallelism available:** Phases 2, 3, and 4 can overlap partially once the DLD is in hand. Realistic calendar time with parallel execution:

| Calendar Day | Activity |
|-------------|----------|
| Day 1 | B-01 through B-07 (backend developer); F-01, F-02, F-03 (frontend developer) |
| Day 2 | B-08, B-09, B-10 (backend developer); T-01 through T-08 (tester begins after backend complete) |
| Day 3 | T-09 full suite run; code review; smoke tests; deploy |

**Minimum calendar time with 4 parallel agents: 3 days.**
