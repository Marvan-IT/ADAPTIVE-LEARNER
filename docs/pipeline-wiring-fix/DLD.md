# Pipeline Wiring Fix — Detailed Low-Level Design

**Date:** 2026-04-13
**Files modified:** `backend/src/extraction/book_profiler.py`, `backend/src/extraction/chunk_parser.py`

---

## 1. Component Breakdown

### book_profiler.py — changes

| Change | Location | Description |
|--------|----------|-------------|
| Add field | `BookProfile` (line ~97) | `corrected_headings: dict[str, str] = {}` |
| Populate on cache miss | `_llm_dict_to_profile()` → caller `profile_book()` | Pass `quality_report.corrected_headings` after building profile |
| Populate on cache hit | `load_or_create_profile()` | After loading cached profile, set `profile.corrected_headings = quality_report.corrected_headings` and re-save |

### chunk_parser.py — changes

| Change | Location | Description |
|--------|----------|-------------|
| Fix regex anchor | `SECTION_PATTERN` (line 40) | Add `$` end anchor |
| Apply heading corrections | `_parse_book_mmd_with_profile()` step 1 | Look up `section_title_raw` in `profile.corrected_headings` |
| Fuzzy section recovery | `_parse_book_mmd_with_profile()` after step 1 | For each `missing_section` from TOC, run 3-strategy search |
| Coverage log | `_parse_book_mmd_with_profile()` end of step 1 | Log found vs. expected counts |
| New helper | `_fuzzy_recover_section()` | Pure function, no I/O |

---

## 2. Data Design

### `BookProfile` field addition

```python
class BookProfile(BaseModel):
    # ... existing fields unchanged ...
    corrected_headings: dict[str, str] = {}
    # Key:   garbled heading text as it appears in MMD body (after Mathpix OCR)
    # Value: corrected title from TOC cross-reference
    # Example: {"The Mothated Leernes": "The Motivated Learner"}
    # Source: quality_report.corrected_headings (populated by ocr_validator)
    # Persistence: serialized in book_profile.json via model_dump_json()
```

**Pydantic v2 behavior:** `default={}` means existing cached JSON files without this key deserialize to `{}` safely — no migration needed.

**Size:** Typically 0–50 entries per book (one per OCR-garbled section heading). Negligible JSON overhead.

---

## 3. Function Signatures and Implementation

### 3.1 `book_profiler._llm_dict_to_profile()` — no signature change

The function already receives `toc_entries`. `corrected_headings` is not derived from LLM output — it comes from `quality_report`. The field is populated by the **caller** (`profile_book()`), not inside `_llm_dict_to_profile()`.

### 3.2 `book_profiler.profile_book()` — add one line

```python
async def profile_book(
    mmd_text: str,
    book_slug: str,
    quality_report,  # ocr_validator.QualityReport
) -> BookProfile:
    # ... existing steps 1–4 unchanged ...

    # Step 4: merge and return
    profile = _llm_dict_to_profile(llm_data, book_slug, toc_entries)

    # NEW: wire corrected_headings from quality_report into profile
    profile.corrected_headings = quality_report.corrected_headings
    logger.info(
        "[profiler] Wired %d corrected headings into profile for '%s'",
        len(profile.corrected_headings),
        book_slug,
    )

    return profile
```

### 3.3 `book_profiler.load_or_create_profile()` — refresh on cache hit

```python
async def load_or_create_profile(
    mmd_text: str,
    book_slug: str,
    quality_report,  # ocr_validator.QualityReport
) -> BookProfile:
    cached = load_profile(book_slug)
    if cached is not None:
        # NEW: always refresh corrected_headings from live quality_report,
        # even on cache hit — ensures corrections stay current without full re-profile
        cached.corrected_headings = quality_report.corrected_headings
        save_profile(cached, book_slug)  # persist refreshed corrections
        logger.info(
            "[profiler] Cache hit for '%s'; refreshed %d corrected headings",
            book_slug,
            len(cached.corrected_headings),
        )
        return cached

    # ... existing cold-path unchanged ...
    logger.info("No cached profile for '%s' — invoking LLM profiler", book_slug)
    profile = await profile_book(mmd_text, book_slug, quality_report)
    save_profile(profile, book_slug)
    return profile
```

**Why re-save on cache hit?** `quality_report.corrected_headings` may improve between pipeline runs as the OCR validator is tuned. Persisting the refresh means a subsequent pipeline run that loads from cache still has the latest corrections.

### 3.4 `SECTION_PATTERN` regex fix

```python
# BEFORE (line 40):
SECTION_PATTERN = re.compile(r"^(#{1,4})\s+(\d+)\.(\d+)\s+(.+)", re.MULTILINE)
#                                                                  ^^^^
#                                               No $ — matches trailing garbage

# AFTER:
SECTION_PATTERN = re.compile(r"^(#{1,4})\s+(\d+)\.(\d+)\s+(.+)$", re.MULTILINE)
#                                                                  ^^
#                                               $ anchors to end of line
```

`ocr_validator._SECTION_HEADING_RE` already has `$` (line 123). This brings the two patterns into alignment.

**Risk:** Lines with trailing spaces or CRLF `\r` will no longer match. `re.MULTILINE` with `$` matches before `\n` but not before `\r\n` on some Python versions. Add `.strip()` in the calling loop if needed (already done — `section_title_raw = m.group(4).strip()`).

### 3.5 Heading correction in `_parse_book_mmd_with_profile()` — Step 1 patch

```python
# Inside the for-loop over SECTION_PATTERN.finditer(mmd_text), after line 721:
section_title_raw = m.group(4).strip()

# NEW: apply OCR correction if available
corrected_headings = getattr(profile, "corrected_headings", {}) or {}
section_title = corrected_headings.get(section_title_raw, section_title_raw)
if section_title != section_title_raw:
    logger.info(
        "[correction] Section %s.%s: '%s' → '%s'",
        m.group(2), m.group(3), section_title_raw, section_title,
    )

section_label = f"{section_number} {section_title}"
concept_id = f"{book_slug}_{section_number}"
section_matches.append({
    # ... other fields unchanged ...
    "section_label": section_label,
    "concept_id": concept_id,
    # store both for traceability
    "section_title_raw": section_title_raw,
    "section_title": section_title,
})
```

### 3.6 Fuzzy section recovery — new helper function

Add `_fuzzy_recover_section()` as a module-level pure function in `chunk_parser.py`:

```python
from difflib import SequenceMatcher

# Minimum ratio for fuzzy title match (SequenceMatcher.ratio())
_FUZZY_TITLE_THRESHOLD = 0.75

# Matches a bare "X.Y" section number anywhere on a line (no # prefix required)
_BARE_SECTION_NUMBER_RE = re.compile(r"(?:^|\s)(\d+)\.(\d+)(?:\s|$)", re.MULTILINE)


def _fuzzy_recover_section(
    section_number: str,          # e.g. "2.1"
    expected_title: str,          # from toc_sections
    mmd_text: str,
    chapter_boundaries: dict[int, int],  # chapter_num → char offset (from profile if available)
) -> dict | None:
    """
    Attempt to locate a section whose heading was garbled by Mathpix OCR.

    Three strategies applied in order; first match wins.

    Strategy 1 — Bare number scan:
        Search for "X.Y" number pattern anywhere on a line (even without # prefix).
        The garbled heading may still carry the correct section number.

    Strategy 2 — Fuzzy title match:
        For each markdown heading line in the body, compute SequenceMatcher.ratio()
        against expected_title. Match if ratio >= _FUZZY_TITLE_THRESHOLD.

    Strategy 3 — Chapter-bounded bold/caps scan:
        Within the character range for the expected chapter, search for ALL-CAPS or
        **bold** text that starts with the same word as expected_title.

    Returns:
        dict with keys {start, end, section_number, section_title, recovered_by}
        or None if no strategy found a match.
    """
    chapter_num, section_in_chapter = (int(x) for x in section_number.split("."))

    # ── Strategy 1: bare section number on any line ──────────────────────────
    for m in _BARE_SECTION_NUMBER_RE.finditer(mmd_text):
        if int(m.group(1)) == chapter_num and int(m.group(2)) == section_in_chapter:
            # Find the line start to determine the heading text
            line_start = mmd_text.rfind("\n", 0, m.start()) + 1
            line_end = mmd_text.find("\n", m.end())
            if line_end == -1:
                line_end = len(mmd_text)
            line_text = mmd_text[line_start:line_end].strip()
            logger.info(
                "[recovery:S1] Recovered section %s at offset %d via bare number: '%s'",
                section_number, line_start, line_text[:80],
            )
            return {
                "start": line_start,
                "end": line_end,
                "section_number": section_number,
                "section_title": expected_title,  # use TOC title (authoritative)
                "recovered_by": "bare_number",
            }

    # ── Strategy 2: fuzzy title match against heading lines ─────────────────
    for m in re.finditer(r"^(#{1,4})\s+(.+)$", mmd_text, re.MULTILINE):
        heading_text = m.group(2).strip()
        ratio = SequenceMatcher(None, heading_text.lower(), expected_title.lower()).ratio()
        if ratio >= _FUZZY_TITLE_THRESHOLD:
            logger.info(
                "[recovery:S2] Recovered section %s via fuzzy title match (ratio=%.2f): '%s'",
                section_number, ratio, heading_text[:80],
            )
            return {
                "start": m.start(),
                "end": m.end(),
                "section_number": section_number,
                "section_title": expected_title,
                "recovered_by": f"fuzzy_title:{ratio:.2f}",
            }

    # ── Strategy 3: chapter-bounded bold/caps text ───────────────────────────
    chapter_start = chapter_boundaries.get(chapter_num, 0)
    chapter_end = chapter_boundaries.get(chapter_num + 1, len(mmd_text))
    chapter_body = mmd_text[chapter_start:chapter_end]
    first_word = expected_title.split()[0].lower() if expected_title.split() else ""

    for m in re.finditer(r"^\*\*(.+)\*\*$|^([A-Z][A-Z\s]{2,})$", chapter_body, re.MULTILINE):
        candidate = (m.group(1) or m.group(2) or "").strip()
        if candidate.lower().startswith(first_word):
            abs_start = chapter_start + m.start()
            abs_end = chapter_start + m.end()
            logger.info(
                "[recovery:S3] Recovered section %s via bold/caps in chapter %d: '%s'",
                section_number, chapter_num, candidate[:80],
            )
            return {
                "start": abs_start,
                "end": abs_end,
                "section_number": section_number,
                "section_title": expected_title,
                "recovered_by": "caps_bold",
            }

    logger.warning(
        "[recovery:FAIL] Could not recover section %s ('%s') — skipped",
        section_number, expected_title,
    )
    return None
```

### 3.7 Fuzzy recovery invocation in `_parse_book_mmd_with_profile()` — after Step 1

```python
# After section_matches is finalized (after all filters), before Step 2:

if profile is not None and profile.toc_sections:
    found_numbers = {sec["section_number"] for sec in section_matches}
    chapter_boundaries = {}  # build from section_matches as proxy if not in profile
    for sec in section_matches:
        ch = sec["chapter"]
        if ch not in chapter_boundaries:
            chapter_boundaries[ch] = sec["start"]

    recovered_count = 0
    for toc_entry in profile.toc_sections:
        sn = toc_entry.get("section_number", "")
        title = toc_entry.get("title", "")
        if sn not in found_numbers:
            result = _fuzzy_recover_section(sn, title, mmd_text, chapter_boundaries)
            if result is not None:
                # Insert the recovered section into section_matches at the right position
                section_matches.append({
                    "start": result["start"],
                    "end": result["end"],
                    "chapter": int(sn.split(".")[0]),
                    "section_in_chapter": int(sn.split(".")[1]),
                    "section_number": sn,
                    "section_label": f"{sn} {result['section_title']}",
                    "concept_id": f"{book_slug}_{sn}",
                    "section_title_raw": result["section_title"],
                    "section_title": result["section_title"],
                })
                found_numbers.add(sn)
                recovered_count += 1

    # Re-sort by position in document after insertions
    section_matches.sort(key=lambda s: s["start"])

    logger.info(
        "[coverage] %s: TOC has %d sections; regex found %d; recovered %d; total %d",
        book_slug,
        len(profile.toc_sections),
        len(found_numbers) - recovered_count,
        recovered_count,
        len(section_matches),
    )

    missed = len(profile.toc_sections) - len(section_matches)
    if missed > 0:
        logger.warning(
            "[coverage] %s: %d TOC sections still unrecoverable after fuzzy search",
            book_slug, missed,
        )
```

---

## 4. Sequence Diagrams

### 4.1 Happy path — cache hit, corrections applied

```
pipeline_runner.py
  │
  │  Stage 3
  ├──► ocr_validator.validate_and_analyze(mmd_text, slug)
  │         └─► quality_report
  │                 ├─ corrected_headings: {"Gahrbled Tittle": "Correct Title"}
  │                 └─ toc_entries: [...]
  │
  │  Stage 4
  ├──► book_profiler.load_or_create_profile(mmd_text, slug, quality_report)
  │         ├─ load_profile(slug) → cached profile (cache hit)
  │         ├─ profile.corrected_headings = quality_report.corrected_headings  ← NEW
  │         ├─ save_profile(profile, slug)  ← NEW (re-persist with refreshed corrections)
  │         └─► profile
  │
  │  Stage 5
  └──► chunk_parser.build_chunks(slug, mmd_path, db, profile=profile)
            └─► _parse_book_mmd_with_profile(mmd_text, slug, profile)
                     ├─ SECTION_PATTERN.finditer() — finds "### X.Y GarbledTitle"
                     ├─ lookup "GarbledTitle" in profile.corrected_headings
                     │       → "Correct Title"
                     ├─ section_matches built with corrected titles
                     ├─ fuzzy recovery for missing sections
                     └─► raw_chunks (correct titles, no missing sections)
```

### 4.2 Error path — fuzzy recovery exhausted

```
_parse_book_mmd_with_profile()
  ├─ SECTION_PATTERN finds 0 occurrences of section "2.1"
  ├─ _fuzzy_recover_section("2.1", "Introduction to Integers", mmd_text, boundaries)
  │       ├─ Strategy 1: no bare "2.1" on any line → skip
  │       ├─ Strategy 2: no heading with ratio >= 0.75 → skip
  │       ├─ Strategy 3: no bold/caps starting with "introduction" → skip
  │       └─► None
  └─ WARNING logged: "Could not recover section 2.1 ('Introduction to Integers') — skipped"
     Section omitted from output (same behaviour as before fix, but now explicitly logged)
```

---

## 5. Integration Design

No external integrations. All changes are intra-process, within the extraction pipeline.

`pipeline_runner.py` is not modified. It already passes `quality_report` to Stage 4 and the returned `profile` to Stage 5. The wiring fix lives entirely inside the two extraction modules.

---

## 6. Security Design

Not applicable. This is an offline data processing pipeline with no user-facing endpoints, no authentication surface, and no network calls added.

---

## 7. Observability Design

### Logging additions

| Logger call | Level | Trigger |
|-------------|-------|---------|
| `"Wired %d corrected headings into profile for '%s'"` | INFO | `profile_book()` — always |
| `"Cache hit for '%s'; refreshed %d corrected headings"` | INFO | `load_or_create_profile()` cache hit |
| `"[correction] Section X.Y: 'garbled' → 'corrected'"` | INFO | Each heading correction applied in chunk_parser |
| `"[recovery:S1] Recovered section X.Y at offset %d"` | INFO | Strategy 1 success |
| `"[recovery:S2] Recovered section X.Y via fuzzy title match (ratio=N)"` | INFO | Strategy 2 success |
| `"[recovery:S3] Recovered section X.Y via bold/caps"` | INFO | Strategy 3 success |
| `"[recovery:FAIL] Could not recover section X.Y"` | WARNING | All 3 strategies failed |
| `"[coverage] %s: TOC has %d sections; regex found %d; recovered %d; total %d"` | INFO | After recovery pass |
| `"[coverage] %s: %d TOC sections still unrecoverable"` | WARNING | Any sections still missing |

All existing log calls in both files are unchanged.

---

## 8. Error Handling and Resilience

| Scenario | Handling |
|----------|----------|
| `profile.corrected_headings` is `{}` (no corrections needed) | Lookup returns `section_title_raw` unchanged — zero-cost no-op |
| `profile` is `None` (legacy path) | `getattr(profile, "corrected_headings", {})` returns `{}` — existing behaviour unchanged |
| `profile.toc_sections` is empty | Recovery loop skipped entirely — no error |
| `_fuzzy_recover_section` returns `None` | Section logged as unrecoverable, skipped — no exception |
| `quality_report.corrected_headings` is `{}` | Profile field set to `{}` — no corrections applied |
| Cached `book_profile.json` lacks `corrected_headings` key | Pydantic `default={}` — deserializes cleanly |
| `SequenceMatcher` raises on non-string input | Guarded by `expected_title.split()` check; worst case returns `None` |

---

## 9. Testing Strategy

### Unit tests (add to `backend/tests/test_pipeline_wiring_fix.py`)

| Test | Description |
|------|-------------|
| `test_book_profile_has_corrected_headings_field` | Assert `BookProfile(book_slug="x", subject="math").corrected_headings == {}` |
| `test_load_or_create_profile_refreshes_corrections_on_cache_hit` | Mock `load_profile` returning cached profile without corrections; assert returned profile has corrections from mock quality_report |
| `test_profile_book_wires_corrected_headings` | Mock `_call_llm_profiler`, assert `profile.corrected_headings` matches quality_report |
| `test_section_pattern_anchored` | Assert `SECTION_PATTERN` does not match `"### 1.1 Title trailing garbage extra"` when trailing chars are not part of title (verify `$` works) |
| `test_heading_correction_applied` | Build minimal MMD with garbled heading; build profile with corrected_headings; assert `_parse_book_mmd_with_profile()` produces chunk with corrected title |
| `test_fuzzy_recover_strategy1_bare_number` | MMD has "2.1 Introduction" without `###`; assert recovery finds it |
| `test_fuzzy_recover_strategy2_fuzzy_title` | MMD has `### Introducction to Integers` (typo); assert ratio >= 0.75 recovers it |
| `test_fuzzy_recover_strategy3_caps` | MMD has `**INTRODUCTION TO INTEGERS**` in chapter range; assert recovery finds it |
| `test_fuzzy_recover_returns_none_when_all_fail` | MMD has no recognizable heading for "2.1"; assert `None` returned |
| `test_profile_none_path_untouched` | Call `_parse_book_mmd_with_profile(mmd, slug, profile=None)` with a garbled heading; assert no exception; garbled title preserved (legacy behaviour) |
| `test_corrected_headings_persisted_in_json` | Call `save_profile()` on profile with corrections; load back; assert corrections round-trip |

### Integration test

| Test | Description |
|------|-------------|
| `test_full_pipeline_wiring_fix_e2e` | Use a 50-line synthetic MMD with one garbled section heading and one missing section (bare number only). Run `load_or_create_profile()` + `build_chunks()`. Assert: (1) corrected title in output chunks, (2) missing section recovered, (3) no exception. |

### Regression guard

Run the existing `test_student_simulations.py` suite (12/12 tests) after the fix to confirm no regression in live book paths.
