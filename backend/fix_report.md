# Fix Report: TOC-Aware Word-Count Filter

## Problem
21 sections missing from statistics book (3.6, 1.5, 8.5, etc.) because `_find_sections()` dropped sections with <30 body words BEFORE checking the TOC whitelist. Lab/experiment sections have very short bodies (3-16 words) but are real sections listed in the TOC.

## Fix
Moved TOC section set construction BEFORE the word-count filter. Sections listed in the TOC are now kept regardless of body word count. Also stripped pipe separators (`|`, `:`, `—`) from section titles.

## Per-Book Impact

| Book | Before | After | Change |
|------|--------|-------|--------|
| **statistics** | **21 missing** | **0 missing** | **+21 sections recovered** |
| business_statistics | 0 missing | 0 missing | No change |
| college_algebra | 0 missing | 0 missing | No change |
| elementary_algebra | 0 missing | 0 missing | No change |
| intermediate_algebra | 0 missing | 0 missing | No change |
| prealgebra2e | 0 missing | 0 missing | No change |
| prealgebra | 3 missing | 3 missing | No change (different root cause) |
| clinical_nursing_skills | 4 missing | 4 missing | No change (nursing format) |
| algebra_1 | 50 missing | 50 missing | No change (Format B — future task) |

## Sections Recovered in statistics

All 21 previously missing sections now have chunks:
1.5, 1.6, 2.8, 3.6, 4.8, 5.4, 6.3, 6.4, 7.4, 7.5, 8.4, 8.5, 8.6, 9.6, 10.5, 11.7, 11.8, 12.6, 12.7, 12.8, 13.5

These are all lab/experiment sections with pipe-separated titles (e.g., `## 3.6 | Probability Topics`).

## No Regressions
- 97 tests pass, 0 failures
- No sections lost in any book
- No chunk count decreases
