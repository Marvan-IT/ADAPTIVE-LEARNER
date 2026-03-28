# Execution Plan: Universal Section Parsing

**Feature slug:** `universal-section-parsing`
**Date:** 2026-03-24
**Author:** solution-architect

---

## 1. Work Breakdown Structure (WBS)

### Stage 0 — Infrastructure (devops-engineer)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| S0-1 | Verify test infrastructure exists | Confirm `backend/tests/` directory and `conftest.py` are present (they were deleted in the 2026-03-16 production cleanup). Re-create `backend/tests/__init__.py` and a minimal `conftest.py` with async DB fixture stubs if absent. Also verify `pytest` and `pytest-asyncio` are in `requirements.txt`. | 0.5 d | None | `backend/tests/`, `requirements.txt` |
| S0-2 | Create test file stub | Create `backend/tests/test_universal_section_parsing.py` with the file header, imports, and empty test class skeletons so the backend developer and tester can work in parallel without merge conflicts on the file. | 0.25 d | S0-1 | `backend/tests/test_universal_section_parsing.py` |

**Stage 0 total: 0.75 days**

---

### Stage 1 — Design (solution-architect)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| S1-1 | HLD | High-Level Design document covering problem statement, format taxonomy, scope, risks, and ADRs. | 0.5 d | None | `docs/universal-section-parsing/HLD.md` |
| S1-2 | DLD | Detailed Low-Level Design specifying regex constants, normalisation order, complete updated function, all edge cases, and `_classify_sections()` compatibility analysis. | 0.75 d | S1-1 | `docs/universal-section-parsing/DLD.md` |
| S1-3 | Execution plan | This document. | 0.25 d | S1-1, S1-2 | `docs/universal-section-parsing/execution-plan.md` |

**Stage 1 total: 1.5 days**

---

### Stage 2 — Backend Implementation (backend-developer)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| S2-1 | Add module-level regex constants | Add `_LATEX_SECTION_RE` and `_ALLCAPS_SECTION_RE` as compiled `re.compile()` constants at module level in `teaching_service.py`, alongside existing module-level constants. Follow naming convention already established in the file. | 0.25 d | S1-2 | `backend/src/api/teaching_service.py` |
| S2-2 | Update `_parse_sub_sections()` | Add the normalisation pre-pass (Pass 1: LaTeX, Pass 2: ALLCAPS) at the entry point of the function, operating on a local `normalised` copy of `text`. Replace the iteration over `text.split("\n")` with iteration over `normalised.split("\n")`. Add the `logger.warning()` call for zero/one sections on long text. The rest of the function body is unchanged. | 0.5 d | S2-1 | `backend/src/api/teaching_service.py` |
| S2-3 | Manual smoke test — prealgebra | Start the backend locally, trigger card generation for one prealgebra concept, confirm section count is unchanged from baseline. Log output should show `[blueprint]` or `[group]` lines with `raw=N blueprint=M` where N, M > 1. | 0.25 d | S2-2 | Local dev environment |
| S2-4 | Manual smoke test — ALLCAPS book | Trigger card generation for one elementary_algebra concept. Confirm that `_parse_sub_sections` now returns > 1 section (visible in `[blueprint]` log line) and that the LLM generates > 5 cards. | 0.25 d | S2-2 | Local dev environment |
| S2-5 | Manual smoke test — college_algebra | Trigger card generation for one college_algebra concept. Confirm same as S2-4 for LaTeX format. | 0.25 d | S2-2 | Local dev environment |

**Stage 2 total: 1.5 days**

---

### Stage 3 — Testing (comprehensive-tester)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| S3-1 | `TestMarkdownPassthrough` — regression suite | Tests confirming zero behavioural change for Markdown-format input. Cases: single `##` header, multiple `##` headers, no headers in short text. Assert that the output dicts are byte-for-byte identical to what the pre-fix function would have returned. | 0.5 d | S0-2, S2-2 | `backend/tests/test_universal_section_parsing.py` |
| S3-2 | `TestLaTeXNormalisation` | Tests for LaTeX format. Cases: `\section*{Title}`, `\section{Title}`, `\subsection*{Sub}`, multiple sections, LaTeX in body text (must NOT split), `$\section$` inline math (must NOT split). Assert title values, section count, and body text content. | 0.5 d | S0-2, S2-2 | `backend/tests/test_universal_section_parsing.py` |
| S3-3 | `TestAllcapsNormalisation` | Tests for ALLCAPS format. Cases: `EXAMPLE 1.5`, `EXAMPLE` bare, `SOLUTION`, `TRY IT 1.27`, `HOW TO`, `NOTE`, `ACCESS ADDITIONAL RESOURCES` (long keyword), multiple sections in sequence, ALLCAPS word mid-sentence (false-positive rejection). Assert title values and casing. | 0.75 d | S0-2, S2-2 | `backend/tests/test_universal_section_parsing.py` |
| S3-4 | `TestMixedFormats` | Tests for concept text containing both Markdown `##` headers and ALLCAPS markers in the same string (edge case for mixed-format books). Assert all sections are correctly split and titled. | 0.25 d | S0-2, S2-2 | `backend/tests/test_universal_section_parsing.py` |
| S3-5 | `TestEdgeCases` | Empty string → `[]`. Whitespace-only → `[]`. No headers, short text (< 2048 chars) → `[]`, no warning logged. No headers, long text (> 2048 chars) → `[]`, warning logged. Single section → `[one item]`. Last section with no trailing newline → correct body text. All sections empty after strip → `[]`. | 0.5 d | S0-2, S2-2 | `backend/tests/test_universal_section_parsing.py` |
| S3-6 | `TestClassifierCompatibility` | Integration tests calling `_classify_sections()` on the output of `_parse_sub_sections()` for ALLCAPS input. Assert that `Example 1.5` → EXAMPLE, `Solution` → SOLUTION, `Try it 1.27` → TRY_IT, a plain concept title → CONCEPT. No mocking required — both are pure static methods. | 0.5 d | S3-3 | `backend/tests/test_universal_section_parsing.py` |
| S3-7 | Run full test suite and confirm no regressions | `pytest backend/tests/ -v`. All existing tests must pass. New tests must achieve 100% branch coverage on `_parse_sub_sections()`. | 0.25 d | S3-1 through S3-6 | CI / local dev |

**Stage 3 total: 3.25 days**

---

### Stage 4 — Frontend (N/A)

This fix is confined to the backend service layer. There are no frontend changes, no new API contracts, no schema changes, and no i18n string additions. Stage 4 is explicitly out of scope.

---

### Stage 5 — Release

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| S5-1 | Code review | Backend developer reviews S2-1 and S2-2 diff. Reviewer confirms: (a) no mutation of the original `text` argument, (b) LaTeX pass runs before ALLCAPS pass, (c) `logger.warning` uses existing `logger` instance, (d) constants are at module level. | 0.25 d | S3-7 | PR review |
| S5-2 | Deploy to staging and validate all 5 books | Trigger card generation for at least one concept from each of the five books. Record section counts from logs. Expected: prealgebra unchanged; all four ALLCAPS/LaTeX books now produce > 1 section. | 0.5 d | S5-1 | Staging environment |
| S5-3 | Deploy to production | Standard deployment (uvicorn reload or container restart). No migration, no env-var changes, no downtime required. | 0.25 d | S5-2 | Production |
| S5-4 | Post-deploy validation | Monitor logs for 30 minutes after deploy. Confirm absence of new `ERROR` lines. Confirm `_parse_sub_sections: returned 0 section(s)` warnings are only appearing for genuinely short concepts. | 0.25 d | S5-3 | Production logs |

**Stage 5 total: 1.25 days**

---

## 2. Phased Delivery Plan

| Phase | Description | Tasks | Entry Criteria | Exit Criteria |
|-------|-------------|-------|---------------|--------------|
| Phase 0 — Foundation | Test infrastructure restored | S0-1, S0-2 | `backend/tests/` absent or incomplete | `pytest` runs cleanly; stub test file exists |
| Phase 1 — Design | Architecture documents complete | S1-1, S1-2, S1-3 | Problem statement approved by stakeholders | All three docs written to `docs/universal-section-parsing/` |
| Phase 2 — Implementation | Bug fix coded | S2-1, S2-2, S2-3, S2-4, S2-5 | Phase 1 complete; test stub exists | All three smoke tests pass locally; no regression on prealgebra |
| Phase 3 — Testing | Full test coverage | S3-1 through S3-7 | Phase 2 complete | 100% branch coverage on `_parse_sub_sections()`; all tests green |
| Phase 4 — N/A | Frontend not applicable | — | — | — |
| Phase 5 — Release | Staged rollout | S5-1 through S5-4 | Phase 3 complete | All 5 books validated in staging; production deploy confirmed |

---

## 3. Dependencies and Critical Path

```
S0-1 → S0-2 ─────────────────────────────────────────────────────────────┐
                                                                          │
S1-1 → S1-2 → S1-3 ──────────────────────────────────────────────────────┤
                │                                                         │
                └─► S2-1 → S2-2 → S2-3 → S2-4 → S2-5 ──────────────────┤
                              │                                           │
                              └─► S3-1 → S3-2 → S3-3 → S3-4             │
                                    └─► S3-5 → S3-6 → S3-7 ─────────────┤
                                                                          │
                                                              S5-1 → S5-2 → S5-3 → S5-4
```

**Critical path:** S1-2 → S2-1 → S2-2 → S3-3 → S3-6 → S3-7 → S5-1 → S5-2 → S5-3

**Blocking dependencies on external teams:**
- None. This fix is self-contained within the backend. No external team dependencies.
- The only coordination required is between the backend-developer (S2) and the comprehensive-tester (S3), which can overlap after S2-2 is complete.

**Parallelism opportunity:** S3-1 through S3-5 can be written in parallel once S2-2 is complete. The tester does not need to wait for S2-3 through S2-5 (the smoke tests).

---

## 4. Definition of Done

### Phase 0 (Infrastructure)
- [ ] `backend/tests/` directory exists with `__init__.py` and `conftest.py`.
- [ ] `pytest` and `pytest-asyncio` are in `requirements.txt`.
- [ ] `backend/tests/test_universal_section_parsing.py` stub file exists with correct imports and empty test class shells.
- [ ] `pytest backend/tests/test_universal_section_parsing.py` runs (0 tests collected, 0 failures — stub only).

### Phase 1 (Design)
- [ ] `docs/universal-section-parsing/HLD.md` written to disk.
- [ ] `docs/universal-section-parsing/DLD.md` written to disk.
- [ ] `docs/universal-section-parsing/execution-plan.md` written to disk.
- [ ] All three open stakeholder questions in HLD and DLD reviewed and answered before Phase 2 begins.

### Phase 2 (Implementation)
- [ ] `_LATEX_SECTION_RE` and `_ALLCAPS_SECTION_RE` defined at module level as compiled regex constants.
- [ ] `_parse_sub_sections()` normalisation pre-pass implemented; local copy (`normalised`) used for iteration; `text` argument not mutated.
- [ ] LaTeX pass runs before ALLCAPS pass.
- [ ] `logger.warning()` added for 0–1 sections on text > 2048 chars.
- [ ] Existing function body (line iterator, section accumulation, empty filter) is unchanged.
- [ ] Prealgebra smoke test: section count matches pre-fix baseline (no regression).
- [ ] elementary_algebra smoke test: `_parse_sub_sections` returns > 1 section for a concept that previously returned 1.
- [ ] college_algebra smoke test: `_parse_sub_sections` returns > 1 section for a concept that previously returned 1.
- [ ] No new `import` statements added (only `re` and `logger` are used, both already present).

### Phase 3 (Testing)
- [ ] `TestMarkdownPassthrough`: all prealgebra-format cases pass.
- [ ] `TestLaTeXNormalisation`: all LaTeX-format cases pass; false-positive body-text case confirmed rejected.
- [ ] `TestAllcapsNormalisation`: all ALLCAPS-format cases pass; mid-sentence false-positive confirmed rejected.
- [ ] `TestMixedFormats`: mixed input splits correctly.
- [ ] `TestEdgeCases`: empty, whitespace, no-headers, long-text-warning cases all pass.
- [ ] `TestClassifierCompatibility`: normalised titles classified correctly by `_classify_sections()`.
- [ ] 100% branch coverage on `_parse_sub_sections()` reported by `pytest --cov`.
- [ ] `pytest backend/tests/ -v` exits with 0 failures.

### Phase 5 (Release)
- [ ] Code review approved by at least one reviewer.
- [ ] All five books validated in staging environment (section counts > 1 for the four previously-broken books).
- [ ] Production deploy completed with no downtime.
- [ ] No new ERROR-level log lines appear in the 30-minute post-deploy monitoring window.
- [ ] `_parse_sub_sections: returned 0 section(s)` warnings, if any, are confirmed to correspond to genuinely short or header-free concepts.

---

## 5. Rollout Strategy

### Deployment Approach
Standard hot reload. Because `uvicorn` is run with `--reload`, the updated `teaching_service.py` is picked up automatically on save in development. In production, a container restart (or uvicorn process restart) is sufficient.

No feature flag is required. The fix is a correctness improvement with a safe fallback path: if no headers are recognised after normalisation, the function returns `[]` and the existing single-section fallback applies. There is no new failure mode.

No migration, no new environment variables, no config changes.

### Rollback Plan
If the fix introduces an unexpected regression:
1. Revert the single commit that modifies `_parse_sub_sections()`.
2. Restart the uvicorn process.
3. The DB card cache (`cache_version`) will serve previously-generated cards until the next regeneration.

The rollback is a one-commit revert with no data migration required.

### Monitoring and Alerting for Launch
- Watch the application logs for `[blueprint]` and `[group]` lines during the first card generation requests after deploy.
- For each of the four previously-broken books, confirm that `raw=N blueprint=M` shows N > 1.
- Watch for any unexpected `_parse_sub_sections: returned 0 section(s)` warnings on texts known to have headers — this would indicate a pattern miss.

### Post-Launch Validation Steps
1. Trigger card generation for one concept per book (five total) immediately after production deploy.
2. Compare card counts before and after: elementary_algebra, intermediate_algebra, algebra_1, college_algebra should all show significantly more cards (target: 8–20 cards vs 2–3).
3. Confirm prealgebra card counts and section structure are unchanged.
4. Monitor error rate for 30 minutes on the card generation endpoint.

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Phase 0 — Foundation | Restore test infra, create stub file | 0.75 days | 1 × devops-engineer |
| Phase 1 — Design | HLD, DLD, execution plan | 1.5 days | 1 × solution-architect |
| Phase 2 — Implementation | Add regex constants, update function, 3 smoke tests | 1.5 days | 1 × backend-developer |
| Phase 3 — Testing | 6 test classes, 20+ test cases, coverage report | 3.25 days | 1 × comprehensive-tester |
| Phase 4 — Frontend | N/A | 0 days | — |
| Phase 5 — Release | Code review, staging validation, production deploy | 1.25 days | 1 × backend-developer + 1 × devops-engineer |
| **Total** | | **8.25 days** | **3 roles (can overlap)** |

With Phase 2 and Phase 3 running in parallel after S2-2 is complete, the wall-clock calendar time is approximately **3 calendar days**.

---

## Key Decisions Requiring Stakeholder Input

1. **Test infrastructure status:** The 2026-03-16 production cleanup deleted `backend/tests/`. Confirm with the devops-engineer whether test infrastructure has been re-established since then, or whether S0-1 and S0-2 are genuinely needed. If tests already exist, S0 reduces to zero effort.
2. **Staging environment availability:** The rollout plan assumes a staging environment separate from production. If no staging exists, the smoke tests in S2-3 through S2-5 serve as the validation gate, and S5-2 must be performed in production with careful log monitoring.
3. **Cache invalidation:** Existing cached cards for elementary_algebra, intermediate_algebra, algebra_1, and college_algebra were generated from the monolithic blob and will have 2–3 cards. After the fix ships, these cards will remain cached until the cache version check triggers regeneration. Confirm with the product team whether a manual cache bust (increment `cache_version` in config.py) should accompany this fix so students immediately benefit, or whether natural expiry is acceptable.
