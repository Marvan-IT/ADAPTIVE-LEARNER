# Detailed Low-Level Design — Extraction Quality Fix

**Feature:** extraction-quality-fix
**Date:** 2026-04-13
**Status:** Draft

---

## 1. Component Breakdown

| Component | File | Responsibility | Changes |
|-----------|------|----------------|---------|
| TOC Parser | `backend/src/extraction/ocr_validator.py` | Extract authoritative section list from front matter | Fix 1 (adaptive window), Fix 4 (non-instructional filter) |
| Profile-Driven Parser | `backend/src/extraction/chunk_parser.py` | Convert MMD text to `ParsedChunk` objects using book profile | Fix 2 (whitelist), Fix 3 (body-only recovery), Fix 6 (bypass max cap) |
| Hardcoded Parser | `backend/src/extraction/chunk_parser.py` | Legacy path for known math books | Fix 5 (noise pattern, OCR correction wiring) |

No new modules. No new classes. All changes are targeted modifications to existing functions.

---

## 2. Data Design

No schema changes. No new data models. The existing `TocEntry`, `QualityReport`, and `ParsedChunk` dataclasses are used unchanged. The `BookProfile.toc_sections` field (a `list[dict]` with `section_number` and `title` keys) already exists and is the carrier for the TOC whitelist.

---

## 3. API Design

Not applicable. The extraction pipeline is a CLI tool invoked via `python -m src.pipeline --book <slug>`. No HTTP endpoints are modified.

---

## 4. Sequence Diagrams

### 4.1 Primary Flow — Profile-Driven Path with All 6 Fixes Applied

```
pipeline.py
    │
    ├─► ocr_validator.parse_toc(mmd_text)
    │       │
    │       ├── 1. Compute search_limit (first 20% of doc)
    │       ├── 2. Slide 2000-char window to find densest region (best_start, best_count)
    │       ├── 3. [FIX 1] Expand bidirectionally while density >= 2/500-char
    │       │         Stop when left/right chunk density drops below threshold
    │       ├── 4. Extract all X.Y Title matches from expanded region
    │       ├── 5. [FIX 4] Filter entries whose title matches NON_INSTRUCTIONAL_TITLES
    │       └── 6. Return list[TocEntry]  (e.g. 62 entries for prealgebra 2e)
    │
    ├─► book_profiler.build_profile(mmd_text, toc_entries)
    │       └── Returns BookProfile with toc_sections populated from toc_entries
    │
    └─► chunk_parser.parse_book_mmd(mmd_path, book_slug, profile)
            │
            └─► _parse_book_mmd_with_profile(mmd_text, book_slug, profile)
                    │
                    ├── Step 1: SECTION_PATTERN.finditer → raw section_matches (all regex hits)
                    │
                    ├── [FIX 6] Skip max_section_in_chapter cap when profile.toc_sections exists
                    │
                    ├── Remove backward section numbers → section_matches (forward-only)
                    │
                    ├── word-count filter (min_body_words) → filtered_matches
                    │
                    ├── [FIX 2] TOC WHITELIST (inserted here, before recovery):
                    │       toc_set = {entry["section_number"] for entry in profile.toc_sections}
                    │       section_matches = [s for s in filtered_matches
                    │                          if s["section_number"] in toc_set]
                    │       log dropped count
                    │
                    └── Step 1b: Recovery for TOC sections still missing
                            │
                            ├── [FIX 3] Compute body_start_offset:
                            │       = min(s["start"] for s in section_matches)
                            │         if section_matches else len(mmd_text) // 10
                            │
                            └── Pass body_start_offset to _fuzzy_recover_section()
                                    _fuzzy_recover_section skips any match whose
                                    offset < body_start_offset
```

### 4.2 Error Flow — TOC Parser Finds No TOC

```
parse_toc(mmd_text)
    │
    ├── best_count < 3 after full scan
    │       └── logger.warning("No TOC region detected")
    │           return []
    │
    └── profile.toc_sections is empty / None
            └── Fix 2 whitelist check: skipped (falls back to heuristic-only filters)
                Fix 3 body_start_offset: defaults to len(mmd_text) // 10
                Fix 6 max cap: stays active (profile.max_sections_per_chapter used)
```

---

## 5. Fix Specifications

### Fix 1 — Adaptive TOC Window (`ocr_validator.py:218–242`)

**Current behaviour:** Fixed 2000-char seed window + static ±500-char expansion = ~3000-char ceiling.

**New behaviour:** After finding `best_start`/`best_end` (densest 2000-char window), expand left and right in 500-char steps. Continue expansion while the new 500-char chunk contains at least 2 `_SECTION_NUMBER_RE` matches. Stop when the chunk is below threshold or the document boundary is reached.

```python
# After the existing sliding-window loop that finds best_start, best_end, best_count:

_DENSITY_THRESHOLD = 2          # matches per 500-char expansion chunk
_EXPANSION_STEP = 500

# Expand LEFT
expand_left = best_start
while expand_left > 0:
    step_start = max(0, expand_left - _EXPANSION_STEP)
    chunk = candidate_region[step_start:expand_left]
    if len(_SECTION_NUMBER_RE.findall(chunk)) >= _DENSITY_THRESHOLD:
        expand_left = step_start
    else:
        break

# Expand RIGHT
expand_right = best_end
while expand_right < len(candidate_region):
    step_end = min(len(candidate_region), expand_right + _EXPANSION_STEP)
    chunk = candidate_region[expand_right:step_end]
    if len(_SECTION_NUMBER_RE.findall(chunk)) >= _DENSITY_THRESHOLD:
        expand_right = step_end
    else:
        break

toc_start = expand_left
toc_end = expand_right
toc_region = candidate_region[toc_start:toc_end]
```

The existing `toc_start = max(0, best_start - 500)` / `toc_end = min(..., best_end + 500)` lines are **replaced** by the above.

---

### Fix 4 — Non-Instructional Filter (`ocr_validator.py`, inside `parse_toc()`)

**Current behaviour:** All extracted X.Y entries are returned, including "Summary", "Key Terms", etc.

**New behaviour:** After extracting entries and cleaning titles, skip entries whose normalized title matches any word in `_NON_INSTRUCTIONAL_TITLE_WORDS`.

Add constant near top of `ocr_validator.py` (after imports):

```python
# Titles that appear in TOC but are not instructional sections.
# Applied after title cleaning to prevent them from entering the whitelist.
_NON_INSTRUCTIONAL_TITLE_WORDS: frozenset[str] = frozenset({
    "summary",
    "key terms",
    "assessments",
    "references",
    "chapter review",
    "exercises",
    "practice test",
    "chapter test",
    "review exercises",
    "cumulative review",
    "answer key",
    "further reading",
    "bibliography",
})
```

Apply in `parse_toc()` immediately after `title = re.sub(r"[\s.]+\d+\s*$", "", title).strip()`:

```python
# Filter non-instructional TOC entries
if _normalize_text_key(title) in _NON_INSTRUCTIONAL_TITLE_WORDS:
    logger.debug("TOC: skipping non-instructional entry %s %r", section_number, title)
    continue
```

---

### Fix 2 — TOC Whitelist (`chunk_parser.py`, after line 887)

**Current behaviour:** `profile.toc_sections` is only used for recovery (adding missing sections), never for rejection.

**New behaviour:** After the `min_body_words` filter, insert a whitelist pass that drops any section not in the TOC.

Insert this block immediately after `section_matches = filtered_matches` (line ~887) and **before** the recovery block (line ~890):

```python
# ── TOC Whitelist: drop regex matches not in TOC ─────────────────────────
# When the TOC is available, it is the sole authority. Any section_number
# produced by the regex that does not appear in the TOC is noise (exercise
# numbers, figure references, etc.) and must be rejected before recovery.
if profile.toc_sections:
    toc_set: set[str] = {
        str(entry.get("section_number", ""))
        for entry in profile.toc_sections
    }
    pre_whitelist_count = len(section_matches)
    section_matches = [
        sec for sec in section_matches
        if sec["section_number"] in toc_set
    ]
    dropped = pre_whitelist_count - len(section_matches)
    if dropped > 0:
        logger.info(
            "[whitelist] %s: dropped %d fake sections not in TOC (kept %d)",
            book_slug, dropped, len(section_matches),
        )
```

---

### Fix 3 — Body-Only Recovery (`chunk_parser.py:890–946`)

**Current behaviour:** `_fuzzy_recover_section()` searches the entire `mmd_text` string (offset 0 to end).

**New behaviour:**
1. Compute `body_start_offset` before the recovery loop.
2. Pass it to `_fuzzy_recover_section()`.
3. Inside `_fuzzy_recover_section()`, skip any match whose character offset is below `body_start_offset`.

**In `_parse_book_mmd_with_profile()`, before the recovery loop:**

```python
# Compute body start offset to prevent recovery from matching front matter.
# Use the earliest confirmed section heading. If none confirmed yet, default
# to 10% of document length as a conservative front-matter boundary.
if section_matches:
    body_start_offset = min(s["start"] for s in section_matches)
else:
    body_start_offset = len(mmd_text) // 10
    logger.warning(
        "[recovery] %s: no confirmed sections for body_start_offset; "
        "defaulting to %d chars",
        book_slug, body_start_offset,
    )
```

**Pass to recovery call:**

```python
result = _fuzzy_recover_section(
    sn, title, mmd_text, chapter_boundaries,
    body_start_offset=body_start_offset,   # NEW parameter
)
```

**Update `_fuzzy_recover_section()` signature and each strategy:**

```python
def _fuzzy_recover_section(
    section_number: str,
    expected_title: str,
    mmd_text: str,
    chapter_boundaries: dict,
    body_start_offset: int = 0,          # NEW — front-matter guard
) -> dict | None:
```

In Strategy 1 (bare number scan), Strategy 2 (fuzzy title), and Strategy 3 (chapter-bounded bold/caps), add a guard after finding a candidate offset `m.start()`:

```python
if m.start() < body_start_offset:
    continue   # skip front-matter hits
```

---

### Fix 6 — Skip `max_sections_per_chapter` Cap When TOC Available (`chunk_parser.py:828`)

**Current behaviour:** `if section_in_chapter > max_section_in_chapter: continue` unconditionally applied.

**New behaviour:** Skip this guard when `profile.toc_sections` is populated.

Replace the existing guard in `_parse_book_mmd_with_profile()` Step 1:

```python
# Before (line ~828):
if section_in_chapter > max_section_in_chapter:
    continue

# After:
if section_in_chapter > max_section_in_chapter and not profile.toc_sections:
    # Only apply the arbitrary cap when we have no TOC whitelist.
    # With a TOC, the whitelist (Fix 2) is the authority — not this cap.
    continue
```

---

### Fix 5 — Noise Pattern + OCR Correction Wiring (hardcoded path, `chunk_parser.py`)

**Part A — Add noise pattern:**

Add to `_NOISE_HEADING_PATTERNS` list (near line 65):

```python
re.compile(r"^Before you get started", re.IGNORECASE),
```

**Part B — Wire OCR corrections in hardcoded path:**

In `parse_book_mmd()` hardcoded path (after `profile is None` branch, around line 322), the function currently reads `section_title_raw = m.group(4).strip()` with no correction step. Add:

```python
# Add parameter to parse_book_mmd signature:
def parse_book_mmd(
    mmd_path: Path,
    book_slug: str,
    profile=None,
    corrected_headings: dict | None = None,   # NEW
) -> list[ParsedChunk]:

# In hardcoded path, after section_title_raw = m.group(4).strip():
_corrections = corrected_headings or {}
section_title = _corrections.get(section_title_raw, section_title_raw)
if section_title != section_title_raw:
    logger.info(
        "[correction] Hardcoded path %s %s: '%s' → '%s'",
        book_slug, section_number, section_title_raw, section_title,
    )
section_label = f"{section_number} {section_title}"
```

The `corrected_headings` dict is already available in `QualityReport.corrected_headings`; the pipeline caller at `pipeline.py` must pass it through.

---

## 6. Security Design

Not applicable. The extraction pipeline is an offline CLI tool with no authentication, no user input, and no network exposure. All inputs are local files read from `backend/output/`.

---

## 7. Observability Design

Each fix emits structured log messages at the appropriate level:

| Fix | Log Level | Message Pattern |
|-----|-----------|----------------|
| Fix 1 | INFO | `"TOC adaptive expansion: %d → %d chars (covers %d–%d)"` |
| Fix 4 | DEBUG | `"TOC: skipping non-instructional entry %s %r"` |
| Fix 2 | INFO | `"[whitelist] %s: dropped %d fake sections not in TOC (kept %d)"` |
| Fix 3 (default) | WARNING | `"[recovery] %s: no confirmed sections for body_start_offset; defaulting to %d chars"` |
| Fix 3 (skip) | DEBUG | `"[recovery] skipping front-matter match at offset %d for section %s"` |
| Fix 6 | DEBUG | `"[profile] TOC whitelist active — skipping max_section_in_chapter cap for %d.%d"` |
| Fix 5A | DEBUG | (via existing `_is_noise_heading` call path) |
| Fix 5B | INFO | `"[correction] Hardcoded path %s %s: '%s' → '%s'"` |

The existing `[coverage]` log at the end of the recovery block remains unchanged and provides the final section count summary.

---

## 8. Error Handling and Resilience

| Scenario | Handling |
|----------|---------|
| Adaptive expansion produces no TOC entries | Falls through to `best_count < 3` check → returns `[]`; book profiler handles empty TOC gracefully |
| `profile.toc_sections` is `None` or `[]` | Whitelist block is skipped entirely (existing heuristic filters apply as-is) |
| `body_start_offset` defaults to 0 because `section_matches` is empty | Conservative: recovery is not restricted, same as current behaviour; WARNING logged |
| `corrected_headings` is `None` in new signature | Defaults to `{}` — no corrections applied, identical to current hardcoded path behaviour |
| Non-instructional filter removes all TOC entries for a chapter | Recovery block will log the missed sections; operator must review the filter set |

All changes degrade gracefully to current behaviour when new inputs are absent or empty.

---

## 9. Testing Strategy

### Unit Tests (pure functions, no I/O)

| Test | File | Covers |
|------|------|--------|
| `test_parse_toc_large_book` | `tests/test_extraction_quality.py` | Fix 1: synthetic 80-section MMD — assert all 80 entries returned |
| `test_parse_toc_small_book` | `tests/test_extraction_quality.py` | Fix 1 regression: 10-section book — no behaviour change |
| `test_parse_toc_filters_non_instructional` | `tests/test_extraction_quality.py` | Fix 4: TOC with "Summary", "Key Terms" — assert excluded from output |
| `test_whitelist_drops_fake_sections` | `tests/test_extraction_quality.py` | Fix 2: fake section 2.10, 3.12 not in TOC — dropped |
| `test_whitelist_noop_when_no_toc` | `tests/test_extraction_quality.py` | Fix 2 regression: empty `toc_sections` → no drops |
| `test_recovery_skips_front_matter` | `tests/test_extraction_quality.py` | Fix 3: match at offset < body_start_offset is skipped |
| `test_recovery_accepts_body_match` | `tests/test_extraction_quality.py` | Fix 3: match at offset >= body_start_offset is accepted |
| `test_max_cap_bypassed_with_toc` | `tests/test_extraction_quality.py` | Fix 6: section 1.15 in TOC is not dropped |
| `test_max_cap_active_without_toc` | `tests/test_extraction_quality.py` | Fix 6 regression: section 1.15 dropped without TOC |
| `test_noise_readiness_quiz` | `tests/test_extraction_quality.py` | Fix 5A: "Before you get started" is noise |
| `test_hardcoded_path_ocr_correction` | `tests/test_extraction_quality.py` | Fix 5B: `corrected_headings` applied in hardcoded path |

### Integration / Regression Tests

- All 12 student simulation tests (`test_student_simulations.py`) must pass unchanged.
- Re-run `python -m src.pipeline --book prealgebra` on the prealgebra 2e MMD and assert the section count equals 62 (the full TOC count).
- Re-run on a nursing or accounting book MMD and manually verify section count matches TOC.

### Performance
No performance tests required. All fixes are O(n) string operations on a single file read once.

---

## Key Decisions Requiring Stakeholder Input

1. **`_DENSITY_THRESHOLD` value:** The constant `2` (matches per 500-char chunk) was chosen conservatively. For books with very sparse TOC formatting, this may need to be `1`. Confirm after testing against the nursing/accounting MMD files.
2. **`_NON_INSTRUCTIONAL_TITLE_WORDS` completeness:** The set was derived from observed OpenStax structure. Verify it covers all subject types before declaring the fix complete.
3. **`corrected_headings` caller wiring:** Fix 5B adds a parameter to `parse_book_mmd()`. The caller in `pipeline.py` must be updated to pass `quality_report.corrected_headings`. Confirm the pipeline team is aware of this call-site change.
