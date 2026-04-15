# High-Level Design — Extraction Quality Fix

**Feature:** extraction-quality-fix
**Date:** 2026-04-13
**Status:** Draft

---

## 1. Executive Summary

### Feature Purpose
The ADA pipeline converts OpenStax PDF textbooks into structured `ParsedChunk` objects used by the adaptive learning engine. For books outside the original math corpus (nursing, accounting, and any future subject), the pipeline produces incorrect section sets: it misses real sections from the TOC, manufactures fake sections from example/exercise numbers, and corrupts recovered sections by matching against front-matter rather than the book body. This fix makes the TOC the sole authoritative source of truth for what constitutes a real section.

### Business Problem
Newly processed books (clinical nursing, financial accounting, etc.) have degraded learning experiences because the chunk graph either drops instructional content or includes noise as pedagogical sections. Students encounter cards with no substantive body text, or skip entire instructional topics that exist in the textbook.

### Scope

**In scope:**
- 6 targeted bug fixes across `ocr_validator.py` and `chunk_parser.py`
- Profile-driven parsing path only (all new books use `--chunks` pipeline)
- Hardcoded path receives one minor fix (noise pattern + OCR correction wiring)

**Out of scope:**
- Hardcoded path architectural changes
- Graph builder or chunk builder changes
- Frontend or database schema changes
- Re-processing already-published books (operational decision, not in-scope here)

---

## 2. Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | TOC parser captures all sections from any book regardless of TOC length | Critical |
| FR-2 | Section detection accepts only sections present in the TOC whitelist | Critical |
| FR-3 | Recovery search is restricted to the book body (after first confirmed section heading) | Critical |
| FR-4 | Non-instructional TOC entries (Summary, Key Terms, etc.) are excluded from the whitelist | High |
| FR-5 | "Before you get started, take this readiness quiz" headings are classified as noise | Medium |
| FR-6 | OCR corrections from `corrected_headings` are applied in the hardcoded parser path | Medium |
| FR-7 | `max_sections_per_chapter` cap is bypassed when TOC whitelist is available | High |

---

## 3. Non-Functional Requirements

| Concern | Target |
|---------|--------|
| Correctness | All TOC sections captured for a 62-section book (Prealgebra 2e test case) |
| No regressions | Existing simulation tests (12/12) continue to pass post-fix |
| Performance | No LLM calls added; all fixes are pure Python regex/string ops — zero cost increase |
| Purity | All changed functions remain pure (no I/O, no DB, no API calls) |
| Observability | Each fix emits a `logger.info` or `logger.warning` line for traceability |

---

## 4. System Context

```
PDF
 │
 ▼
Mathpix OCR ──► book.mmd (raw)
                    │
                    ▼
            ocr_validator.py
            ┌──────────────────────────────┐
            │  parse_toc()          [FIX 1, FIX 4]  │
            │  find_chapter_boundaries()   │
            │  extract_boundary_candidates()│
            └──────────────────────────────┘
                    │  QualityReport (toc_entries, corrected_headings, ...)
                    ▼
            book_profiler.py (LLM)
                    │  BookProfile (toc_sections, noise_patterns, ...)
                    ▼
            chunk_parser.py
            ┌──────────────────────────────┐
            │  _parse_book_mmd_with_profile()       │
            │    Step 1: section detection [FIX 6]  │
            │    Step 1a: TOC whitelist    [FIX 2]  │
            │    Step 1b: body-only recovery[FIX 3] │
            │  parse_book_mmd() hardcoded  [FIX 5]  │
            └──────────────────────────────┘
                    │  list[ParsedChunk]
                    ▼
            chunk_builder.py ──► PostgreSQL + graph.json
```

---

## 5. Architectural Style

**Style: Pure-function, single-pass text processing pipeline.**

All six fixes maintain the existing architectural contract: every function is stateless and pure. No new modules, no new classes, no new I/O. The changes are:
- Two targeted modifications to `ocr_validator.py::parse_toc()`
- Four targeted modifications to `chunk_parser.py::_parse_book_mmd_with_profile()` and `parse_book_mmd()`

**Alternatives considered:**
- Re-engineering the parser as a multi-pass system (rejected: over-engineering for 6 targeted bugs)
- Moving TOC whitelist logic into the book profiler LLM prompt (rejected: adds LLM call cost and non-determinism)

---

## 6. Technology Stack

No changes to the tech stack. All fixes are pure Python 3.11+ using `re`, `difflib`, and standard library only. This matches the existing module contracts.

---

## 7. Key Architectural Decisions

### ADR-1: TOC is the Sole Authority for Section Identity
**Decision:** When `profile.toc_sections` is populated, the whitelist is applied before recovery, and the `max_sections_per_chapter` cap is disabled.
**Rationale:** The book author defined the TOC. Any section not in the TOC is either noise, an exercise number, or a duplicate. No heuristic should override this.
**Trade-off:** If the TOC parser itself misses entries (Bug 1), those entries will be absent from the whitelist. Fix 1 must be correct before Fix 2 can be correct. This creates a sequential dependency.

### ADR-2: Adaptive Window Expansion, Not Fixed Size
**Decision:** TOC window starts from the densest 2000-char seed and expands bidirectionally while section-number density remains above 2 matches per 500 chars.
**Rationale:** A fixed 3000-char window fails for books with 60+ sections. Adaptive expansion stops naturally at the TOC boundary, handling books of any size without a new hard-coded constant.
**Trade-off:** Slightly more computation; negligible at extraction time (run once per book).

### ADR-3: Body-Start Offset Guards Recovery
**Decision:** Recovery search is restricted to offsets >= `body_start_offset` (position of first confirmed section heading in the regex scan).
**Rationale:** Front matter (College Success preface, page-number TOC listings) appears before the body. Matches in this region are always false positives.
**Trade-off:** If a book has no confirmed regex sections at all (100% TOC-only recovery scenario), `body_start_offset` defaults to a conservative fraction of the document length.

### ADR-4: Non-Instructional Filter Uses a Fixed Allowlist-Exclusion Set
**Decision:** Exclude sections whose normalized title matches a fixed set of non-instructional labels.
**Rationale:** "Summary", "Key Terms", "References", "Assessments" appear consistently across nursing, accounting, and sciences. They are administrative, not pedagogical. An LLM classification would be more general but adds cost and latency.
**Trade-off:** Future books with unusual section names may need additions to the filter set. The filter set is a named constant in `ocr_validator.py` for easy maintenance.

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Adaptive window over-expands and captures body content as TOC | Low | Medium | Density threshold check — expansion stops when density drops below 2/500-char; regression test with prealgebra |
| TOC whitelist rejects a legitimately numbered exercise section that has instructional value | Low | Low | `min_body_words` filter still applies as a backstop before whitelist check; reviewed manually per book |
| Body-start offset defaults incorrectly for zero-regex-match books | Very Low | Medium | Conservative fallback: 10% of document length; logged at WARNING level for operator review |
| Non-instructional filter accidentally matches instructional sections | Low | Medium | Exact title-word matching only (not substring); filter set reviewed against 16 known OpenStax books |
| OCR correction wiring change breaks hardcoded path for existing books | Low | High | Unit test specifically covering hardcoded path with `corrected_headings`; simulation tests are the regression gate |

---

## Key Decisions Requiring Stakeholder Input

1. **Re-processing policy:** Should already-published books be re-run through the pipeline after these fixes? This could disrupt live student sessions if chunk IDs change.
2. **Non-instructional filter set:** Is the current set (Summary, Key Terms, Assessments, References, Chapter Review, Exercises, Practice Test, Chapter Test, Review Exercises, Cumulative Review, Answer Key) sufficient, or should it be runtime-configurable via `admin_config`?
3. **TOC fallback behaviour:** If Fix 1 still misses sections after adaptive expansion (e.g., a book with an unusually structured TOC), should Fix 2 fall back to heuristic filtering, or fail hard and require operator intervention?
