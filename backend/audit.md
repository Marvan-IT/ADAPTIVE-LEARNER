# Pipeline Audit — Bug Locations & Planned Fixes

## BUG 1: `\subsection*{N.M}` bare-number trap
**File:** `chunk_parser.py` lines 327-328 (`_normalize_mmd_format()`)
**Current:** `re.escape("\\subsection*{") + r"(.+?)" + re.escape("}")` blindly converts ALL `\subsection*{...}` to `### ...`
**Impact:** 3 books affected NOW:
  - elementary_algebra: 106 bare-number phantom sections
  - intermediate_algebra: 108 bare-number phantom sections
  - prealgebra2e: 159 bare-number phantom sections
**Fix:** Split regex into two: real sections (`\subsection*{N.M Title}` → `### N.M Title`) and bare numbers (`\subsection*{N.M}` → `**[EX N.M]**`)

## BUG 2: Chapter Review back-references create duplicate sections
**File:** `chunk_parser.py` lines 94, 167, 201-203, 715, 736-741
**Current:** "Chapter Review" is both a noise heading AND an exercise zone trigger. `### N.M Title` inside Chapter Review becomes "(Exercises)" tagged chunk with the SAME concept_id as the main section — creating duplicate concept_ids.
**Impact:** 8 of 9 books have Chapter Review zones (10-13 per book). Each re-lists section headings → duplicate concept_ids.
**Fix:** Detect Chapter Review zones. Tag chunks inside as `chunk_type='chapter_review'`, `is_optional=True`. Don't create new section boundaries inside review zones.

## BUG 3: Format B (Unit-Lesson-Activity) books
**File:** `chunk_parser.py` line 46 (`SECTION_PATTERN`)
**Current:** Regex `(\d+)\.(\d+)` only captures two-level. Three-level `N.M.K` headings are missed.
**Impact:** 0 of 9 current books affected. Latent — will activate with new OpenStax 2025 format.
**Fix:** Add format detector + three-level regex. Lowest priority.

## BUG 4: Incomplete noise keyword list
**File:** `chunk_parser.py` lines 68-124 (`_NOISE_HEADING_PATTERNS`)
**Current:** 56 patterns. Missing: "Check Your Understanding", "Building Character", "Sample Solution", "[Show/Hide Solution]"
**Impact:** LOW — 2-3 missing patterns may cause 5-15 unwanted chunk splits in non-math books
**Fix:** Add missing patterns. Move to config file for per-format overrides.

## BUG 5: Chunk size variance
**File:** `chunk_parser.py` lines 385, 855-876, 885-889
**Current:** No TARGET_CHUNK_WORDS. Tiny merge at 50 words (hardcoded). No default max_chunk_words — chunks can be 5000+ words.
**Impact:** MEDIUM — some sections produce micro-chunks (<30 words) that embed poorly, and mega-chunks (>2000 words) that dilute retrieval.
**Fix:** Add MIN_CHUNK_WORDS=150, TARGET=400, MAX=800. Implement semantic chunking with merge/split.

## BUG 6: Image ownership
**File:** `chunk_parser.py` lines 752-753, 802-803
**Current:** Images extracted greedily within chunk text boundaries. No proximity rule. No cross-boundary checks.
**Impact:** MEDIUM-HIGH — images between headings may be attributed to wrong chunk. No orphan detection.
**Fix:** Line-by-line walk with proximity rule. Validation step: count(mmd_images) == count(chunk_images).

## BUG 7: No automated validation between pipeline stages
**File:** `pipeline_runner.py` lines 127-132 (between Stage 3 and Stage 4)
**Current:** Coverage check exists (warns <95%) but doesn't block. No phantom section detection, no image accounting, no chunk order validation.
**Impact:** HIGH — silent failures reach Postgres. Students see broken content.
**Fix:** Add `post_parse_validator.py` between Stage 3 and Stage 4. Fail pipeline loudly on errors. Block DB writes.

## Priority Order
1. BUG 1 (bare-number trap) — CRITICAL, affects 3 books now
2. BUG 4 (noise keywords) — easy fix, low risk
3. BUG 2 (Chapter Review) — MEDIUM, affects 8 books
4. BUG 5 (chunk size) — MEDIUM, affects quality
5. BUG 6 (image ownership) — MEDIUM-HIGH, affects accuracy
6. BUG 7 (validation) — HIGH, depends on other fixes
7. BUG 3 (Format B) — LOW, latent, future-proofing
