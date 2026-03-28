---
name: Universal Card Generation Tests
description: Patterns and facts for test_universal_cards.py covering section parsing, LO reorder, RECAP sort, missed-image cleanup
type: project
---

### Test File
`backend/tests/test_universal_cards.py` — 40 tests across 6 groups (all passing).

### Key Implementation Facts (verified 2026-03-25)

**`_parse_sub_sections()` — Pass 3 (paragraph split)**
- Threshold: 800 chars. Sections SHORTER than this are left intact.
- `_NO_SPLIT_TYPES = {"EXAMPLE", "SOLUTION", "TRY_IT"}` — only applies when `sec.get("section_type")` is already set on the dict.
- `section_type` is NOT set by `_parse_sub_sections` itself — it is set by `_classify_sections`. So the no-split guard only activates when a caller pre-classifies before passing to the expansion loop.
- Testing the no-split guard: construct a dict with `section_type="EXAMPLE"` and run the expansion loop logic directly (not via `_parse_sub_sections`).
- Zero char loss test: reconstruct the original body with `"\n\n".join(p.strip() for p in paragraphs)`, then compare to `"\n\n".join(s["text"] for s in sections)` after whitespace-normalisation.

**`_classify_sections()` — Learning Objectives patterns**
- All these titles classify to `LEARNING_OBJECTIVES` (tested): "Learning Outcomes", "Section Objectives", "Chapter Objectives", "After studying this section…", "By the end of this chapter…", "Students will be able to…"
- Classification uses `re.search(pattern, title_lower)` — so prefix match is sufficient.

**`_ALLCAPS_SECTION_RE`**
- Module-level compiled regex (imported directly from `api.teaching_service`).
- Matches: "LEARNING OUTCOMES", "LEARNING OBJECTIVES", "SECTION OBJECTIVES", "CHAPTER OBJECTIVES", "SECTION OUTCOMES", "EXAMPLE 1.5", "TRY IT 1.27"
- Does NOT match full sentences (fullmatch only covers exact strings).

**LO reorder block (inside `generate_cards()`)**
- Mirrors with `lo_indices = [i for i, s in enumerate(classified) if s.get("section_type") == "LEARNING_OBJECTIVES"]`
- Tests call `_classify_sections()` and then apply the reorder slice-and-insert directly (no mocking needed — pure list manipulation).

**RECAP `_section_index = 9999`**
- Any card whose `card_type == "RECAP"` gets `_section_index = 9999` immediately after the section stamp loop.
- Sort key: `lambda c: c.get("_section_index", 999)` — RECAP always last.

**Missed-image cleanup block**
- Exact logic mirrored in `TestMissedImageCleanup._run_cleanup()`.
- Guard: `_best_score > 0` — zero-overlap images are NEVER force-attached.
- Guard: image already in `_assigned_fnames` (by `filename` or `file` key) is skipped.
- Guard: image with no `description` is skipped.
- Word overlap is `len(desc_words & content_words)` — case-insensitive.

**`_CARDS_CACHE_VERSION` constant**
- Defined as a LOCAL constant inside `generate_cards()`, not at module level.
- Current value: 21 (as of 2026-03-24 per-card adaptive generation update).
- Tested via `inspect.getsource()` + `textwrap.dedent()` + `ast.parse()` AST walk.
- `textwrap.dedent()` is REQUIRED before `ast.parse()` — method source has leading indent that causes `IndentationError` otherwise.
