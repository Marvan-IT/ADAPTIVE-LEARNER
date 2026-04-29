# Splitter Audit — Phase 0

## Bug 1 — Chapter intros orphaned at end of previous chapter
**File:** `chunk_parser.py` lines 707-716 (chapter intro extension), 808-813 (orphan text prepend)
**Root cause:** Chapter intro content is prepended to the first subsection's chunk, but when the section body extends from section X.Y to section X+1.1, the chapter boundary content (title, Figure, Introduction text) gets absorbed into the LAST section of the previous chapter. Business Statistics: Chapter 2 intro lands in section 1.4 heading "2 \\ DESCRIPTIVE STATISTICS (part 10)".
**No `section="N.0"` or `chunk_type="chapter_intro"` concept exists.**
**Fix:** Add CHAPTER_OPENER state. Emit chapter intro as its own chunk with `section="N.0"`, `chunk_type="chapter_intro"`, `order_index=0`.

## Bug 2 — Mechanical splitting produces "part N of M" labels
**File:** `chunk_parser.py` lines 1001-1051 (`_split_large_chunk()`)
**Root cause:** `_split_large_chunk()` at line 1043 creates "(part N)" suffix headings. Threshold is 800 words (line 413). Splits at paragraph boundaries without awareness of semantic units — examples get separated from solutions, figure captions from figures.
**Impact:** 1,333 "part N" chunks across all 9 books (136 in algebra_1, 270 in statistics, 256 in business_statistics).
**Fix:** Replace `_split_large_chunk()` with semantic unit detector + greedy packer. Never split semantic units.

## Bug 3 — Bare-number exercise labels become phantom sections
**File:** `chunk_parser.py` lines 321-359 (`_normalize_mmd_format()`)
**Status: ALREADY FIXED.** Pattern `_SUBSEC_BARE` (line 342) converts bare `\subsection*{N.M}` to `**[EX N.M]**` (inline marker). Pattern `_SUBSEC_TITLED` (line 340) only converts sections with title text to `###` headings.
**Verified:** No phantom sections from bare numbers in current output.
**No further action needed.**

## Bug 4 — Chapter Review repeats create duplicate section attribution
**File:** `chunk_parser.py` lines 94 (noise pattern), 170-178 (exercise zone), 208 (section-is-exercise)
**Root cause:** Chapter Review is tagged as exercise zone. `### N.M Title` lines inside it become exercise-tagged chunks pointing to the original concept_id. This is partially correct (no duplicate sections), but content is not tagged as `chunk_type='chapter_review'` or `is_optional=True`. Chapter Review content gets mixed into regular exercise chunks.
**Impact:** 8 of 9 books have Chapter Review zones (10-13 per book).
**Fix:** Detect Chapter Review zone explicitly. Tag chunks inside as `chunk_type='chapter_review'`, `is_optional=True`.

## Bug 5 — Format B (Unit-Lesson-Activity) silently fails
**File:** `chunk_parser.py` line 47 (`SECTION_PATTERN`)
**Root cause:** Regex `(\d+)\.(\d+)` only captures two-level X.Y sections. No `detect_format()` function exists. No three-level X.Y.K pattern support.
**Impact:** 0 of 9 current books affected (all are Format A). Will affect new OpenStax 2025 books.
**Fix:** Add format detector. For Format B: use `N.M.K` section pattern, lesson-level grouping.

## Bug 6 — Incomplete noise heading vocabulary
**File:** `chunk_parser.py` lines 68-130 (`_NOISE_HEADING_PATTERNS`)
**Root cause:** 61 hardcoded patterns + 2 from `CONTENT_EXCLUDE_MARKERS`. No YAML config. No subject-specific vocabulary.
**Fix:** Create `config/semantic_patterns/` with `_base.yaml`, `mathematics.yaml`, `_unknown.yaml`. Load at startup from `books.yaml` subject field.

## Bug 7 — Post-parse validation
**File:** `validators/post_parse_validator.py` lines 22-171
**Status: ALREADY PARTIALLY IMPLEMENTED.** 6 checks exist (TOC coverage, chunk count, size distribution, section ordering, image accounting, word retention). Pipeline blocks on errors (>50% TOC missing, <10 chunks, out-of-order sections).
**Missing checks:** No chapter_intro validation, no "part N" detection, no Example/TryIt pairing, no figure accounting (only approximation), no contiguity check.
**Fix:** Add missing validators per Phase 8 spec.

---

## Current State of books.yaml
- **subject field:** YES — all 18 entries have `subject:` (17 mathematics, 1 nursing)
- **format field:** NO — no `format:` field. Auto-detection needed.
- **Other fields:** book_code, book_slug, pdf_filename, title, section_header_font, section_header_size_min/max, chapter_header_font, chapter_header_size_min/max, section_pattern, front_matter_end_page, exercise_marker_pattern, toc_section_pattern

## Current State of config/
- **No `config/` directory exists** under `backend/`
- **No `config/semantic_patterns/` directory**
- All patterns hardcoded in `chunk_parser.py` line 68-130

---

## Unexpected Findings

1. **Bug 3 is already fixed** — the bare-number disambiguation was implemented in the current session. No further action needed.
2. **Bug 2 is massive** — 1,333 "part N" chunks across all 9 books. The `_split_large_chunk()` function at line 1001 actively creates these. The max_chunk_words=800 threshold is correct, but splitting at paragraph boundaries without semantic awareness causes the problem.
3. **Bug 1 is confirmed exactly as described** — Business Statistics Chapter 2 intro ("Once you have collected data") is in section 1.4, heading "2 \\ DESCRIPTIVE STATISTICS (part 10)". The chapter boundary detection exists but the content allocation is wrong.
4. **Bug 7 validator exists but is incomplete** — it was added in this session. Needs additional checks per Phase 8.

---

## Priority Order (recommended)

1. Phase 7 (config infrastructure) — create YAML loader, subject dispatch
2. Phase 1 (chapter opener) — fix Bug 1
3. Phase 2 (bare-number) — already fixed, verify only
4. Phase 3 (Chapter Review) — fix Bug 4
5. Phase 4+5 (semantic units + packer) — fix Bug 2 (the big one)
6. Phase 6 (Format B) — fix Bug 5
7. Phase 8 (validators) — enhance Bug 7
