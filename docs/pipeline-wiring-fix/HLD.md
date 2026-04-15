# Pipeline Wiring Fix — High-Level Design

**Date:** 2026-04-13
**Scope:** `backend/src/extraction/book_profiler.py`, `backend/src/extraction/chunk_parser.py`

---

## 1. Executive Summary

**Problem:** The 7-stage universal PDF extraction pipeline computes OCR quality corrections in Stage 3 (`ocr_validator`) but silently drops them before Stage 5 (`chunk_parser`). The result is that garbled Mathpix headings are stored permanently in the database and entire sections (where the section number was garbled) are silently omitted for every future book.

**Fix:** Add a `corrected_headings` field to `BookProfile` (the natural carrier object between stages), populate it in `load_or_create_profile()`, and consume it in `chunk_parser._parse_book_mmd_with_profile()`. Add fuzzy section recovery for missing sections using `profile.toc_sections`. Fix one regex anchor defect (`SECTION_PATTERN` lacks `$`).

**Files changed:** 2 (`book_profiler.py`, `chunk_parser.py`). No API, schema, or migration changes.

**Stakeholders:** Platform engineering, content quality, any team processing a new OpenStax book.

---

## 2. Data Flow — Before and After

### Before (broken)

```
Stage 3 — ocr_validator.validate_and_analyze()
  └─► quality_report
        ├─ corrected_headings: {"The Mothated Leernes": "The Motivated Learner", ...}
        └─ missing_sections:   ["2.1", "2.2", "2.3"]
             │
             │  quality_report passed to Stage 4 only for toc_entries/signal_stats
             ▼
Stage 4 — book_profiler.load_or_create_profile(mmd_text, slug, quality_report)
  └─► profile (BookProfile)
        └─ toc_sections: [...]   ← populated
        └─ corrected_headings    ← FIELD DOES NOT EXIST
             │
             │  quality_report is discarded after Stage 4
             ▼
Stage 5 — chunk_parser.build_chunks(slug, mmd_path, db, profile=profile)
  └─► _parse_book_mmd_with_profile()
        ├─ SECTION_PATTERN regex finds "### X.Y Title" headings
        │    └─ section_title_raw stored as-is (garbled) → DB poisoned
        └─ Garbled "X.Y" numbers not found by regex → section silently dropped
```

### After (fixed)

```
Stage 3 — ocr_validator.validate_and_analyze()
  └─► quality_report (unchanged)

Stage 4 — book_profiler.load_or_create_profile(mmd_text, slug, quality_report)
  └─► profile (BookProfile)
        ├─ toc_sections: [...]
        └─ corrected_headings: {"garbled": "corrected", ...}  ← NEW FIELD
             │  populated from quality_report.corrected_headings
             │  persisted in book_profile.json (auto-refreshed each run)
             ▼
Stage 5 — chunk_parser.build_chunks(slug, mmd_path, db, profile=profile)
  └─► _parse_book_mmd_with_profile()
        ├─ Regex finds clean "### X.Y Title" headings
        │    └─ section_title_raw looked up in profile.corrected_headings → corrected title stored
        ├─ profile.toc_sections drives fuzzy recovery of missing sections
        │    └─ 3-strategy search: "X.Y" bare number → title fuzzy match → chapter bold/caps
        └─ Coverage check logged: expected N sections, found M
```

---

## 3. Component Interactions

```
ocr_validator.py          book_profiler.py           chunk_parser.py
     │                          │                          │
     │  QualityReport           │                          │
     │─────────────────────────►│                          │
     │                          │  BookProfile             │
     │                          │  (+ corrected_headings) ─►│
     │                          │                          │
     │                          │  book_profile.json       │
     │                          │◄────────────────────────►│ (cache read/write)
```

`pipeline_runner.py` orchestrates stages and is not modified — it already passes `quality_report` to Stage 4 and `profile` to Stage 5. The fix only changes what data `profile` carries.

---

## 4. Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | `BookProfile` carries `corrected_headings: dict[str, str]` (default `{}`) |
| FR-2 | `load_or_create_profile()` populates `corrected_headings` from `quality_report` on every run (cache hit or miss) |
| FR-3 | `chunk_parser` applies `corrected_headings` to every parsed section title before storing |
| FR-4 | `chunk_parser` attempts fuzzy recovery of TOC sections absent from regex scan |
| FR-5 | `SECTION_PATTERN` regex gains `$` anchor to match `ocr_validator`'s strict pattern |
| FR-6 | Coverage check: log warning when recovered+found sections differ materially from TOC count |
| FR-7 | Profile `=None` path in `chunk_parser` is completely untouched |
| FR-8 | Existing 16 books with cached profiles load and run without regression |

---

## 5. Non-Functional Requirements

| NFR | Target |
|-----|--------|
| Correctness | Zero garbled section titles written to DB after fix |
| Backward compatibility | Cached `book_profile.json` files without `corrected_headings` deserialize safely (Pydantic default `{}`) |
| Performance | Fuzzy recovery adds < 100 ms per book run (difflib on heading strings, not large corpora) |
| Observability | Every correction and recovery logged at `INFO`; missed sections logged at `WARNING` |
| Zero-migration | No DB schema changes; no Alembic migration required |

---

## 6. Architectural Style

**In-process data enrichment via carrier object pattern.** `BookProfile` is already the canonical data carrier from Stage 4 to Stage 5. Extending it with `corrected_headings` is the lowest-friction, highest-coherence option — it avoids new function parameters, new files, and new persistence mechanisms.

Alternatives considered:

| Option | Verdict |
|--------|---------|
| Pass `quality_report` directly to `build_chunks()` | Rejected — breaks the established interface; `quality_report` is a Stage 3 artifact that `chunk_parser` should not depend on directly |
| Separate correction file on disk | Rejected — adds another I/O artifact; `book_profile.json` already serves this role |
| Re-run Stage 3 inside chunk_parser | Rejected — violates stage separation; expensive |

---

## 7. Key Architectural Decisions

### ADR-1: `corrected_headings` on `BookProfile`, not a new parameter

**Decision:** Add field to `BookProfile`; populate in `load_or_create_profile()`.

**Rationale:** `build_chunks()` and `parse_book_mmd()` signatures unchanged. Cache persistence is free (Pydantic `model_dump_json` already serializes the field). On cache hit, `load_or_create_profile()` refreshes `corrected_headings` from the live `quality_report` before returning — ensuring corrections stay current even without a full re-profile.

### ADR-2: Fuzzy recovery uses `profile.toc_sections`, not a new data source

**Decision:** Recovery candidates come from `profile.toc_sections` (already populated from `quality_report.toc_entries`).

**Rationale:** No new data needed. `toc_sections` contains `{section_number, title, chapter}` for every instructional section. The fuzzy match is against heading-like lines in the MMD body.

### ADR-3: Three-strategy fuzzy recovery, fail-safe

**Decision:** Strategies applied in order; first match wins. If no strategy recovers the section, it is logged as unrecoverable and skipped (not an error).

**Rationale:** Missing sections should not crash the pipeline. A warning log is sufficient for operator awareness.

---

## 8. Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Fuzzy match produces false positive (wrong section injected) | Low | `SequenceMatcher` threshold ≥ 0.75; Strategy 1 (exact number scan) is tried first |
| `corrected_headings` cache stale between pipeline re-runs | None | `load_or_create_profile()` always overwrites `corrected_headings` from fresh `quality_report`, even on cache hit |
| `$` anchor on `SECTION_PATTERN` breaks an existing match | Very low | Regex now requires no trailing characters after title — previously matched lines with trailing spaces or control chars that should not have been matched |
| Old `book_profile.json` files lack the field | No risk | Pydantic `default={}` makes deserialization safe |

---

## Key Decisions Requiring Stakeholder Input

1. **Fuzzy match threshold:** 0.75 is proposed. If books have highly abbreviated TOC titles vs. body headings, a lower threshold (0.65) may be needed — verify against a problematic book before shipping.
2. **Re-run required for existing books:** The fix only applies to newly processed books or books whose chunks are rebuilt with `rebuild=True`. Existing DB data for already-processed books is not retroactively corrected. Decide whether a one-time rebuild pass is needed for books already in production.
