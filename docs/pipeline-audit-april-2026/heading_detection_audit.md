# Heading Detection Audit — Phase 0

## Every regex testing for heading patterns in the codebase

### chunk_parser.py (PRIMARY — all heading detection flows through here)

| Line | Pattern | Purpose | Format assumed |
|------|---------|---------|----------------|
| 47 | `^(#{1,4})\s+(\d+)\.(\d+)\s+(.+)$` | SECTION_PATTERN — find X.Y sections | Space or any separator (`.+` captures pipe too) |
| 50 | `^##\s+(.+)$` | SUBHEADING_PATTERN — subsection split boundaries | Any `##` heading |
| 68-130 | 60+ patterns | _NOISE_HEADING_PATTERNS — headings to NOT split on | Various |
| 170-178 | Exercise zone trigger | _EXERCISE_ZONE_PATTERN | Section/Chapter/Review keywords |
| 181-193 | Section-is-exercise | _SECTION_IS_EXERCISE_PATTERN | Same keywords in section labels |
| 195-207 | Exercise headings | _EXERCISE_HEADING_PATTERN | Practice/Writing/Everyday |
| 209-215 | Info headings | _INFO_HEADING_PATTERN | Learning Objectives/Summary |
| 337-358 | Normalization | _normalize_mmd_format() | LaTeX \subsection*{} and \section*{} |
| 383-386 | Chapter headings | _CHAPTER_HEADING_PATTERNS | ## N, ## N |, \section*{N} |
| 497 | Section detection | _find_sections() uses SECTION_PATTERN | Via SECTION_PATTERN |
| 757 | Section leak check | `re.match(r"^\d+\.\d+\s", heading_text)` | Inline check |
| 797 | Review zone detect | `_REVIEW_ZONE_RE` | Chapter Review/Key Terms heading |
| 882 | Exercise zone fallback | `_EXERCISE_ZONE_PATTERN.match()` | Inline check |

### ocr_validator.py (SECONDARY — used for TOC parsing)

| Line | Pattern | Purpose | Format assumed |
|------|---------|---------|----------------|
| 160-161 | Comment only | Documents LaTeX heading formats | N/A |
| ~530 | Signal detection | Detects heading types in MMD | Various |

### mmd_parser.py (LEGACY — not called by current pipeline)

| Line | Pattern | Purpose | Format assumed |
|------|---------|---------|----------------|
| 65 | `\subsection*{Title}` | LaTeX heading detection | Legacy format |
| 99 | Combined markdown+LaTeX | Heading finder | Legacy format |

### book_profiler.py (LEGACY — not called by current pipeline)

| Line | Pattern | Purpose | Format assumed |
|------|---------|---------|----------------|
| 703-748 | References only | Documents noise pattern names | N/A |

---

## ROOT CAUSE of missing sections

**Section 3.6, 1.5, 8.5, etc. in statistics book:** These ARE detected by SECTION_PATTERN (matches exist). But `_find_sections()` filters them out because `body_words < MIN_SECTION_BODY_WORDS (30)`. These are lab/experiment sections with very short bodies (3-16 words) because their content is structured as experiment subsections (`## Procedure`, `## Organize the Data`, etc.) not inline prose.

**The 30-word threshold is correct for exercise stubs** but wrong for lab sections. The fix: either lower the threshold for pipe-separated sections, or handle lab/experiment sections specially.

---

## Inconsistencies between heading detection points

1. **SECTION_PATTERN** (line 47) matches pipe separator as part of title: `3.6 | Probability Topics` → title = `| Probability Topics` (includes pipe)
2. **_CHAPTER_HEADING_PATTERNS** (line 384) explicitly handles pipe: `(?:[|:<]|\s+[A-Z]|\s+\\)` 
3. **Normalization** (lines 337-358) handles bare numbers but NOT pipe separators — pipe stays in title
4. **No title normalization** — the pipe character is never stripped from section titles

---

## Chunk types currently emitted

| chunk_type | Source |
|------------|--------|
| `teaching` | Default for pedagogical content |
| `exercise` | Sections/chunks in exercise zone |
| `lab` | Lab/experiment sections |
| `chapter_intro` | Chapter N.0 introduction |
| `chapter_review` | Content in Chapter Review zones |
| `learning_objective` | Learning Objectives sections |

---

## concept_id / section format

| Field | Format | Example |
|-------|--------|---------|
| concept_id | `{book_slug}_{chapter}.{section}` | `statistics_3.6` |
| section | `{chapter}.{section} {title}` | `3.6 \| Probability Topics` |
| section (chapter intro) | `{chapter}.0 Chapter {N} Introduction` | `3.0 Chapter 3 Introduction` |

---

## Recommendation

The immediate fix for missing lab sections: **don't filter sections with <30 body words if they exist in the TOC**. The TOC is the authority — if a section is in the TOC, it should never be filtered regardless of body word count. The `_find_sections()` function already has TOC whitelist logic but it runs AFTER the word-count filter, so short sections are already gone.

**Fix:** Move the word-count filter AFTER the TOC whitelist, and only apply it to sections NOT in the TOC.
