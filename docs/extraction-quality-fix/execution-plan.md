# Execution Plan — Extraction Quality Fix

**Feature:** extraction-quality-fix
**Date:** 2026-04-13
**Target:** Single backend developer, 1–2 days

---

## 1. Work Breakdown Structure (WBS)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| EQ-1 | Adaptive TOC window | Replace fixed ±500-char expansion in `parse_toc()` with bidirectional density-driven expansion (Fix 1) | 0.5d | — | `ocr_validator.py` |
| EQ-2 | Non-instructional filter | Add `_NON_INSTRUCTIONAL_TITLE_WORDS` constant and title-match guard inside `parse_toc()` (Fix 4) | 0.25d | EQ-1 (same function edit) | `ocr_validator.py` |
| EQ-3 | TOC whitelist block | Insert whitelist pass after `min_body_words` filter in `_parse_book_mmd_with_profile()` (Fix 2) | 0.5d | EQ-1, EQ-2 (TOC must be complete before whitelist is meaningful) | `chunk_parser.py` |
| EQ-4 | Body-start offset for recovery | Compute `body_start_offset`, update `_fuzzy_recover_section()` signature, add guard in all 3 strategies (Fix 3) | 0.5d | EQ-3 (must follow whitelist so confirmed section set is final) | `chunk_parser.py` |
| EQ-5 | Bypass `max_sections_per_chapter` cap | Add `and not profile.toc_sections` condition to the cap guard (Fix 6) | 0.25d | EQ-3 | `chunk_parser.py` |
| EQ-6 | Noise pattern + OCR correction wiring | Add readiness quiz pattern to `_NOISE_HEADING_PATTERNS`; add `corrected_headings` param to `parse_book_mmd()` and apply in hardcoded path; update `pipeline.py` caller (Fix 5) | 0.5d | — | `chunk_parser.py`, `pipeline.py` |
| EQ-7 | Unit tests | Write `tests/test_extraction_quality.py` covering all 11 test cases from DLD Section 9 | 1.0d | EQ-1 through EQ-6 | `tests/` |
| EQ-8 | Regression validation | Run simulation tests (12/12); run pipeline on prealgebra 2e and assert 62 sections | 0.5d | EQ-7 | `tests/`, CLI |

**Total estimated effort: 4.0 dev-days**

---

## 2. Phased Delivery Plan

### Phase 1 — Foundation (Day 1 morning)
**Tasks:** EQ-1, EQ-2, EQ-6

These three tasks are independent of each other:
- EQ-1 and EQ-2 are in `ocr_validator.py` (same function, edit sequentially)
- EQ-6 is in `chunk_parser.py` hardcoded path and `pipeline.py` (no overlap with profile path)

**Deliverable:** `parse_toc()` correctly captures all sections from any book. Noise headings in the hardcoded path are suppressed. OCR corrections wired through.

**Acceptance check (manual):** Run `parse_toc()` on the prealgebra 2e MMD directly and log the count. Expect 62 entries, no "Summary" / "Key Terms" entries.

---

### Phase 2 — Core Fixes (Day 1 afternoon)
**Tasks:** EQ-3, EQ-4, EQ-5

Run in order (EQ-3 before EQ-4, EQ-3 and EQ-5 can be done together):

- EQ-3: Whitelist block inserted at the correct position in the profile path
- EQ-5: One-line condition change adjacent to EQ-3's edit area
- EQ-4: Body-start offset computation + `_fuzzy_recover_section()` parameter change

**Deliverable:** Profile-driven parser rejects fake sections, restricts recovery to body text, and respects TOC section counts.

**Acceptance check (manual):** Run `_parse_book_mmd_with_profile()` on a book with known fake sections (e.g., 2.10, 3.12 were false positives). Confirm they are dropped. Confirm the section count matches `len(profile.toc_sections)` after subtracting any sections truly absent from the body.

---

### Phase 3 — Testing and Hardening (Day 2)
**Tasks:** EQ-7, EQ-8

Write the unit test file covering all 11 test cases. Then run the full regression suite.

**Deliverable:** `tests/test_extraction_quality.py` (11 tests, all passing). Simulation tests 12/12. Prealgebra pipeline produces 62 sections.

---

## 3. Dependencies and Critical Path

```
EQ-1 ──► EQ-2
EQ-1 ──────────► EQ-3 ──► EQ-4
                 EQ-3 ──► EQ-5
EQ-6 (independent)
EQ-1…EQ-6 ──► EQ-7 ──► EQ-8
```

**Critical path:** EQ-1 → EQ-3 → EQ-4 → EQ-7 → EQ-8

**External dependency:** `pipeline.py` caller update (EQ-6) requires confirming the `QualityReport` is already passed to the `parse_book_mmd()` call site. If not, the pipeline caller needs a one-line addition.

---

## 4. Definition of Done

### Phase 1 DoD
- [ ] `parse_toc()` returns 62 entries for prealgebra 2e (verified by direct function call)
- [ ] "Summary" and "Key Terms" entries absent from returned `TocEntry` list
- [ ] "Before you get started" heading classified as noise (unit smoke test)
- [ ] `corrected_headings` dict applied in hardcoded path (unit smoke test)
- [ ] Code reviewed: no magic numbers; all new constants named and placed at module level

### Phase 2 DoD
- [ ] Sections 2.10, 3.12, 6.10 (known false positives) absent from profile-path output
- [ ] Section count in profile path equals `len(profile.toc_sections)` ± unrecoverable sections
- [ ] Recovery produces no matches from front-matter offsets (verified by adding an intentional front-matter match in a test fixture)
- [ ] `max_section_in_chapter` cap inactive when `profile.toc_sections` is non-empty

### Phase 3 DoD
- [ ] `tests/test_extraction_quality.py` exists with ≥ 11 passing tests
- [ ] `rtk pytest backend/tests/test_extraction_quality.py` exits 0
- [ ] `rtk pytest backend/tests/test_student_simulations.py` exits 0 (12/12)
- [ ] Manual pipeline run on prealgebra 2e produces exactly 62 concept sections
- [ ] No `print()` statements; all logging via `logger.*`
- [ ] No new module-level imports beyond what already exists in each file

---

## 5. Rollout Strategy

### Deployment Approach
This is a pure extraction pipeline fix with no API, no database schema, and no frontend changes. Rollout is:

1. Merge to `main` behind a developer review.
2. Re-run the extraction pipeline for affected books:
   ```bash
   python -m src.pipeline --book <slug> --chunks
   ```
3. Verify section counts in the database against the book's TOC (operator manual check).
4. No server restart required unless the pipeline writes to the same PostgreSQL instance as the live API.

### Rollback Plan
Each fix is a small, self-contained code change. If a regression is detected:
- Revert `ocr_validator.py` to restore the original fixed-window behaviour (disabling Fix 1 and Fix 4)
- Revert `chunk_parser.py` to remove the whitelist block and body-start guard (disabling Fix 2, Fix 3, Fix 5, Fix 6)
- Re-run the pipeline for the affected book

Because pipeline output is stored in PostgreSQL (not in-memory), a rollback followed by re-extraction restores the prior state completely.

### Post-Launch Validation
- Query the `concept_chunks` table for the re-processed book: `SELECT COUNT(DISTINCT concept_id) FROM concept_chunks WHERE book_slug = '<slug>'` — must equal the TOC section count.
- Query for any `concept_id` that has `0` chunks — indicates a section was recovered as a position marker only, never assigned body text. Investigate these manually.
- Spot-check 5 random sections in the Admin Book Content page to confirm chunks have substantive text (not front-matter noise).

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| 1 — Foundation | EQ-1 (adaptive window), EQ-2 (non-instructional filter), EQ-6 (noise + OCR wiring) | 1.25d | 1 backend developer |
| 2 — Core Fixes | EQ-3 (whitelist), EQ-4 (body-only recovery), EQ-5 (bypass max cap) | 1.25d | 1 backend developer |
| 3 — Testing | EQ-7 (unit tests), EQ-8 (regression) | 1.5d | 1 backend developer |
| **Total** | **6 tasks, 11 unit tests** | **4.0d** | **1 backend developer** |

---

## Key Decisions Requiring Stakeholder Input

1. **Which books to re-process after merge?** All books processed before this fix have potentially incorrect section sets. Prioritize by whether any students are actively using them.
2. **Acceptance criteria for nursing/accounting books:** The 62-section prealgebra target is well-defined. What is the expected section count for the nursing and accounting books? This must be confirmed against their TOCs before the pipeline run is declared successful.
3. **`pipeline.py` caller change scope:** EQ-6 Fix 5B adds a `corrected_headings` parameter to `parse_book_mmd()`. Confirm there are no other callers of `parse_book_mmd()` in test harnesses or scripts that will break on the new optional parameter (it defaults to `None`, so existing callers are backward compatible).
