# Pipeline Wiring Fix — Execution Plan

**Date:** 2026-04-13
**Estimated total effort:** 3.5 dev-days
**Team needed:** 1 backend developer + 1 tester (can overlap)

---

## 1. Work Breakdown Structure

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| P1-1 | Add `corrected_headings` field to `BookProfile` | Add `corrected_headings: dict[str, str] = {}` to `BookProfile` Pydantic model in `book_profiler.py` | 0.25d | — | book_profiler.py |
| P1-2 | Wire corrections in `profile_book()` | After `_llm_dict_to_profile()` call, set `profile.corrected_headings = quality_report.corrected_headings` with INFO log | 0.25d | P1-1 | book_profiler.py |
| P1-3 | Refresh corrections on cache hit in `load_or_create_profile()` | On cache hit: overwrite `corrected_headings`, call `save_profile()`, log | 0.25d | P1-1 | book_profiler.py |
| P2-1 | Fix `SECTION_PATTERN` regex anchor | Change `(.+)` to `(.+)$` in the compiled regex | 0.1d | — | chunk_parser.py |
| P2-2 | Apply heading correction in section scan loop | Add `corrected_headings.get(section_title_raw, section_title_raw)` lookup; log each correction; store both `section_title_raw` and `section_title` in section_matches dict | 0.5d | P1-1 | chunk_parser.py |
| P2-3 | Implement `_fuzzy_recover_section()` helper | New module-level pure function: Strategy 1 (bare number), Strategy 2 (fuzzy title), Strategy 3 (bold/caps). Returns `dict | None`. | 0.75d | — | chunk_parser.py |
| P2-4 | Integrate recovery pass into `_parse_book_mmd_with_profile()` | After regex scan, iterate `profile.toc_sections` for missing entries; call `_fuzzy_recover_section()`; insert results; re-sort; log coverage | 0.5d | P2-3, P1-1 | chunk_parser.py |
| P3-1 | Unit tests — book_profiler changes | Tests: field exists, refresh on cache hit, wire on cold path, JSON round-trip (4 tests) | 0.5d | P1-1–P1-3 | tests/ |
| P3-2 | Unit tests — chunk_parser changes | Tests: regex anchor, correction applied, 3 recovery strategies, None fallback, profile=None untouched (8 tests) | 0.75d | P2-1–P2-4 | tests/ |
| P3-3 | End-to-end integration test | Synthetic 50-line MMD with one garbled heading + one bare-number-only missing section; verify corrected title + recovery in output chunks | 0.5d | P3-1, P3-2 | tests/ |
| P3-4 | Regression run | Execute existing `test_student_simulations.py` (12 tests) to confirm no existing book regresses | 0.1d | P3-3 | tests/ |

---

## 2. Phased Delivery Plan

### Phase 2a — `BookProfile` field addition (P1-1) — Day 1 morning

Single-line Pydantic field addition. Validates that existing cached JSONs still load (regression-free by Pydantic default). Unblocks all downstream work.

**DoD:** `BookProfile(book_slug="x", subject="math").corrected_headings` returns `{}`. Existing `book_profile.json` files for all 16 books load without error.

### Phase 2b — Profiler wiring (P1-2, P1-3) — Day 1 afternoon

Connect `quality_report.corrected_headings` into the profile on both the cold (LLM call) and warm (cache hit) paths. Re-save updated cache on warm path.

**DoD:** Running `load_or_create_profile()` with a mock quality_report containing 3 corrections returns a profile with those 3 corrections in `corrected_headings`, and the on-disk JSON reflects them.

### Phase 2c — Chunk parser fixes (P2-1 through P2-4) — Day 2

Apply regex fix, heading correction lookup, fuzzy recovery helper, and recovery integration. This is the highest-complexity phase.

**DoD:**
- `SECTION_PATTERN` compiled with `$` anchor.
- A section titled "The Mothated Leernes" in MMD, with `corrected_headings = {"The Mothated Leernes": "The Motivated Learner"}` in profile, produces a chunk with `section_label` containing "The Motivated Learner".
- A section whose number "2.1" appears only as bare text (no `###` prefix) is present in the output chunks after recovery.

### Phase 2d — Tests and regression (P3-1 through P3-4) — Day 3

All unit tests passing. E2E integration test passing. Existing 12 simulation tests still pass.

**DoD:** `pytest backend/tests/test_pipeline_wiring_fix.py -v` — all 12+ tests green. `pytest backend/tests/test_student_simulations.py -v` — all 12 tests green.

---

## 3. Dependencies and Critical Path

```
P1-1 (field)
  ├──► P1-2 (cold wire) ──────────────────────────────────► P3-1 (profiler tests)
  ├──► P1-3 (cache refresh) ──────────────────────────────► P3-1
  └──► P2-2 (correction lookup) ──────────────────────────► P3-2 (parser tests)

P2-1 (regex fix) ──────────────────────────────────────────► P3-2
P2-3 (fuzzy helper) ──► P2-4 (recovery integration) ───────► P3-2

P3-1 + P3-2 ──► P3-3 (E2E) ──► P3-4 (regression)
```

**Critical path:** P1-1 → P2-2 → P2-4 → P3-2 → P3-3 → P3-4

**No external blocking dependencies.** Both files are standalone modules with no cross-team contracts.

---

## 4. Definition of Done

### Per-phase acceptance criteria

| Phase | Acceptance Criteria |
|-------|---------------------|
| 2a | `BookProfile.corrected_headings` field exists; all 16 existing `book_profile.json` files deserialize without error |
| 2b | `load_or_create_profile()` returns profile with `corrected_headings` populated from `quality_report` on both cold and warm paths; JSON on disk updated |
| 2c | `SECTION_PATTERN` has `$` anchor; chunk parser applies corrections to section titles; fuzzy recovery inserts previously-missing sections; coverage logged |
| 2d | All new unit tests pass; 12 existing simulation tests pass; no `print()` or debug logs left in committed code |

### General DoD (all phases)

- Code reviewed by at least one other engineer
- No bare `except Exception` added
- All new log calls use `logger.*`, not `print()`
- No hardcoded strings — thresholds (`_FUZZY_TITLE_THRESHOLD`, `_BARE_SECTION_NUMBER_RE`) defined as module constants with comments
- `test_pipeline_wiring_fix.py` added to `backend/tests/`

---

## 5. Rollout Strategy

### Deployment approach

This is an **offline data pipeline fix** — not a live API change. No feature flag needed. No blue/green or canary required.

**Steps:**
1. Merge PR to `main`.
2. For books that have already been processed: re-run `python -m src.pipeline --book <slug> --rebuild` to apply corrections. The `--rebuild` flag forces `build_chunks()` with `rebuild=True`, clearing stale DB chunks and re-inserting corrected ones.
3. Verify via `SELECT concept_id, heading FROM concept_chunks WHERE book_slug='<slug>' LIMIT 50` that titles are corrected.

### Rollback plan

If corrections introduce unexpected behaviour (e.g., false-positive fuzzy matches):

1. Delete the offending `book_profile.json` (or remove the `corrected_headings` key from it manually).
2. Re-run pipeline without `--rebuild` — chunk_parser will use `{}` for corrections and the legacy path for missing sections.
3. The profile=None path in chunk_parser is completely untouched, so reverting book_profiler.py to the previous version restores the pre-fix state exactly.

### Post-launch validation

- Check `[correction]` log lines: confirm correction count matches `quality_report.corrected_headings` size.
- Check `[coverage]` log lines: confirm "unrecoverable" count is 0 or minimal for a test book.
- Query DB: `SELECT COUNT(*) FROM concept_chunks WHERE heading LIKE '%Moth%'` (or other known-garbled pattern) — should return 0.

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members |
|-------|-----------|-----------------|--------------|
| 2a — Field addition | P1-1 | 0.25d | Backend developer |
| 2b — Profiler wiring | P1-2, P1-3 | 0.5d | Backend developer |
| 2c — Chunk parser fixes | P2-1, P2-2, P2-3, P2-4 | 1.85d | Backend developer |
| 2d — Tests + regression | P3-1, P3-2, P3-3, P3-4 | 1.85d | Tester (can overlap with 2c) |
| **Total** | | **~3.5 dev-days** | **1 backend + 1 tester** |

With one engineer doing everything sequentially: 3.5 days.
With backend dev (2a–2c) and tester starting P3-1/P3-2 in parallel from Day 2: ~2.5 calendar days.

---

## Key Decisions Requiring Stakeholder Input

1. **Rebuild existing books?** The fix only applies going forward (or when `--rebuild` is explicitly passed). Decide whether a one-time rebuild of all 16 processed books is warranted, and schedule downtime accordingly — each book rebuild takes ~5–15 minutes.
2. **Fuzzy threshold 0.75:** If a book has highly abbreviated TOC titles (e.g., "Integers" vs. "Introduction to the Study of Integers"), 0.75 may miss valid matches. Consider running the recovery dry-run (`_fuzzy_recover_section` without inserting) on a known-problematic book to calibrate before shipping.
