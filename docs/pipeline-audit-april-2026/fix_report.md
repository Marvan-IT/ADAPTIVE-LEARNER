# Fix Report: TOC-Aware Filters (word-count + parse_toc density scan)

## Problem 1: Word-count filter drops TOC sections
21 sections missing from statistics book. Root cause: `_find_sections()` dropped sections with <30 body words BEFORE checking the TOC whitelist. Lab/experiment sections have short bodies.

**Fix:** Build TOC section set BEFORE the word-count filter. Sections in the TOC are kept regardless of body word count. Uses the simple dotted-line regex (`N.M Title ..... PageNum`) instead of `parse_toc()` which fails on some books.

## Problem 2: parse_toc() density scan picks body content over actual TOC
`parse_toc()` in `ocr_validator.py` returned 0 entries for business_statistics because the density scan (`_SECTION_NUMBER_RE`) matched body content (Figure 1.1, Table 2.3, etc.) with higher density than the actual TOC.

**Fix:** Added `_TOC_DOTTED_RE` (matches `N.M Title ..... PageNum` specifically) as the primary density pattern. Falls back to generic `_SECTION_NUMBER_RE` only if dotted-line pattern finds nothing.

## Problem 3: Pipe separators in section titles
Sections like `## 3.6 | Probability Topics` had the pipe in the title: `| Probability Topics`.

**Fix:** Strip leading `|`, `:`, `—`, `–`, `-`, `·` from section titles in both chunk_parser and parse_toc.

## Per-Book Impact

| Book | parse_toc before | parse_toc after | Missing sections |
|------|-----------------|-----------------|-----------------|
| **business_statistics** | **0** | **61** | **0** (was broken) |
| **statistics** | 79 | 79 | **0** (was 21 missing) |
| algebra_1 | 90 | 90 | 38 (Format B — separate task) |
| clinical_nursing_skills | 107 | 107 | 4 (nursing format) |
| college_algebra | 59 | 59 | 0 |
| elementary_algebra | 71→70 | 70 | 0 |
| intermediate_algebra | 70 | 70 | 0 |
| prealgebra | 60 | 60 | 3 (formatting gaps) |
| prealgebra2e | 60→58 | 58 | 0 |

## Other filters audited (no bugs found)

| Filter | Location | Verdict |
|--------|----------|---------|
| `section_in_chapter > 99` | parse_toc line 342 | Correct — exercise numbers |
| `not title` (empty after cleaning) | parse_toc line 350 | Correct — garbled lines |
| `_NON_INSTRUCTIONAL_TITLE_WORDS` | parse_toc line 356 | **Not triggered for any book** — safe |
| TOC region matches skip | chunk_parser line 542 | Correct — prevents TOC stubs |
| TOC whitelist filter | chunk_parser line 568/583 | Correct — runs after dedup |
| Fuzzy recovery | chunk_parser line 611 | Correct — recovers missing sections |

## No Regressions
- 97 tests pass, 0 failures
- No sections lost in any book
- business_statistics and statistics both at 0 missing
