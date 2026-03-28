# High-Level Design: Universal Section Parsing

**Feature slug:** `universal-section-parsing`
**Date:** 2026-03-24
**Author:** solution-architect

---

## 1. Executive Summary

### Feature Name and Purpose
Universal Section Parsing — normalise all textbook header formats into the single format already understood by `_parse_sub_sections()` before that function runs its split logic.

### Business Problem Being Solved
ADA supports 16 OpenStax textbooks, but the card-generation pipeline currently produces 2–3 cards per concept instead of the expected 10–20 cards for 4 out of 5 books that have been tested. The root cause is that `_parse_sub_sections()` recognises only `## ` (Markdown) headers. Textbooks whose ChromaDB concept text uses ALLCAPS section markers (`EXAMPLE 1.5`, `TRY IT 1.27`, `SOLUTION`) or LaTeX section commands (`\section*{Title}`) are returned to the caller as a single monolithic blob. The grouping, blueprint, and adaptive card-budget logic that follows never has a chance to execute, so the LLM receives one enormous section and generates far fewer cards.

### Key Stakeholders
- Product: students on elementary_algebra, intermediate_algebra, algebra_1, college_algebra receive materially fewer learning cards per concept.
- Backend developer: owns `teaching_service.py`.
- Comprehensive tester: must cover all four new format branches.
- Solution architect: produces this documentation.

### Scope

**Included:**
- A pre-processing normalisation step inside `_parse_sub_sections()` that rewrites LaTeX section commands and ALLCAPS section markers to `## ` headers before the existing line-by-line split logic runs.
- Regression protection: Markdown-format books must be entirely unaffected.

**Excluded:**
- Changes to any other function in `teaching_service.py`.
- Changes to any other file (no schema changes, no config changes, no frontend changes, no new endpoints).
- Changes to the extraction pipeline that produced the ChromaDB data.
- Any alteration to `_group_by_major_topic()`, `_classify_sections()`, or `_build_textbook_blueprint()`.

---

## 2. Functional Requirements

| ID | Priority | Requirement |
|----|----------|-------------|
| FR-1 | P0 | `_parse_sub_sections()` must correctly split concept text from prealgebra (Markdown headers) into multiple sections — existing behaviour preserved. |
| FR-2 | P0 | `_parse_sub_sections()` must correctly split concept text from elementary_algebra and algebra_1 (ALLCAPS markers such as `EXAMPLE 1.5`, `TRY IT 1.27`, `SOLUTION`) into multiple sections. |
| FR-3 | P0 | `_parse_sub_sections()` must correctly split concept text from intermediate_algebra (ALLCAPS markers `EXAMPLE`, `SOLUTION` without numbering) into multiple sections. |
| FR-4 | P0 | `_parse_sub_sections()` must correctly split concept text from college_algebra (LaTeX `\section*{Title}` commands) into multiple sections. |
| FR-5 | P1 | When concept text contains no recognisable headers in any format, the function must return an empty list so the caller's existing fallback (`[{"title": concept_title, "text": concept_text}]`) handles it. |
| FR-6 | P1 | The normalised text must be used only inside `_parse_sub_sections()`; the original `text` argument must never be mutated or returned. |

---

## 3. Non-Functional Requirements

| Attribute | Target |
|-----------|--------|
| Performance | Normalisation must add < 5 ms per call; concept texts are at most ~31 KB. |
| Correctness | Zero regression on prealgebra (Markdown format) — verified by test suite. |
| Maintainability | All regex patterns are defined as named module-level constants, not inline strings. |
| Test coverage | 100% branch coverage on the three normalisation paths (LaTeX, ALLCAPS, no-op). |
| Scope containment | Diff is confined to `_parse_sub_sections()` in `teaching_service.py`; one function, zero other files. |

---

## 4. System Context

```
ChromaDB concept text
  (one of three raw formats)
        │
        ▼
┌──────────────────────────────────────────────────────────┐
│  TeachingService.generate_cards()                        │
│                                                          │
│  concept_text = concept["text"]          (unchanged)     │
│                                                          │
│  sub_sections = _parse_sub_sections(concept_text)        │
│       │                                                  │
│       │  ◄──── THIS FUNCTION IS THE SCOPE OF THE FIX ─► │
│       │                                                  │
│       ▼                                                  │
│  if not sub_sections:                                    │
│      sub_sections = [single-section fallback]            │
│  else:                                                   │
│      classified = _classify_sections(sub_sections)       │
│      blueprint  = _build_textbook_blueprint(classified)  │
│      ...                                                 │
└──────────────────────────────────────────────────────────┘
        │
        ▼
  LLM card generation
  (10–20 cards instead of 2–3)
```

External systems: none. The fix is entirely within a single static method. No network calls, no database reads, no configuration lookups.

---

## 5. Header Format Taxonomy

| Format | Books Affected | Example Raw Line | Normalised Output |
|--------|---------------|-----------------|-------------------|
| Markdown `## ` | prealgebra | `## Whole Numbers` | `## Whole Numbers` (no change) |
| LaTeX `\section*{}` | college_algebra | `\section*{Polynomial Functions}` | `## Polynomial Functions` |
| ALLCAPS numbered | elementary_algebra, algebra_1 | `EXAMPLE 1.5`, `TRY IT 1.27` | `## Example 1.5`, `## Try it 1.27` |
| ALLCAPS bare | intermediate_algebra | `EXAMPLE`, `SOLUTION` | `## Example`, `## Solution` |

All four formats converge to the same `## Title` structure before the existing line-by-line iterator processes them.

---

## 6. Architectural Style and Patterns

**Style:** Pure function mutation (pre-processing pass).

The fix introduces a text normalisation step at the entry point of an already-static method. This is the simplest possible intervention:

- No new classes, no new methods on the class, no state.
- The normalisation runs once over the raw string using `re.sub()` before the existing character-by-character line iterator begins.
- All downstream logic (`_classify_sections`, `_build_textbook_blueprint`, `_group_by_major_topic`) is untouched and already handles the section titles produced by normalisation.

**Alternative considered — detection in the caller (`generate_cards`):** Rejected. The caller already delegates all text-splitting concerns to `_parse_sub_sections`. Splitting that responsibility across two functions would increase coupling and make unit testing harder.

**Alternative considered — per-book preprocessing in KnowledgeService:** Rejected. KnowledgeService returns raw ChromaDB content; applying format transformation there would couple the retrieval layer to the pedagogical parsing layer. The fix belongs where the parsing happens.

---

## 7. Technology Stack

No new dependencies. The fix uses only Python standard library `re`, which is already imported throughout `teaching_service.py`.

---

## 8. Key Architectural Decisions (ADRs)

### ADR-1: Normalise in `_parse_sub_sections`, not in the caller

- **Decision:** Add the normalisation as the first operation inside `_parse_sub_sections()`.
- **Options considered:**
  1. Pre-process in `generate_cards()` before calling `_parse_sub_sections()`.
  2. Pre-process inside `_parse_sub_sections()`.
  3. Detect format in `_parse_sub_sections()` and branch to different split strategies.
- **Chosen:** Option 2.
- **Rationale:** `_parse_sub_sections()` is a static method with a single responsibility — split text into sections. Normalising the input as the first step keeps that responsibility cohesive and makes the function independently testable against all four formats without needing to reach the caller.

### ADR-2: LaTeX normalisation runs before ALLCAPS normalisation

- **Decision:** The two `re.sub()` passes run in a fixed order: LaTeX first, ALLCAPS second.
- **Rationale:** LaTeX `\section*{...}` commands never overlap with ALLCAPS markers. Running LaTeX first prevents the ALLCAPS pattern from accidentally matching the `{TITLE}` brace content in a not-yet-normalised LaTeX line. Markdown headers are never touched by either pass.

### ADR-3: ALLCAPS detection uses a whitelist of known pedagogical keywords

- **Decision:** The ALLCAPS pattern matches a closed set of known OpenStax section keywords (EXAMPLE, SOLUTION, TRY IT, HOW TO, MANIPULATIVE MATHEMATICS, MEDIA, LEARNING OBJECTIVES, GLOSSARY, KEY CONCEPTS, NOTE, BE CAREFUL, LINK TO LITERACY, EVERYDAY MATH, WRITING EXERCISES, PRACTICE MAKES PERFECT, MIXED PRACTICE, REVIEW EXERCISES, PRACTICE TEST, ACCESS ADDITIONAL) optionally followed by a numbering suffix.
- **Rationale:** An open ALLCAPS regex (`^[A-Z][A-Z\s]+$`) would match legitimate uppercase proper nouns or acronyms within body text. A whitelist constrains matches to lines that are structurally section markers. This avoids false-positive splits that would fragment body text.

---

## 9. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| ALLCAPS whitelist misses a keyword used in a book not yet tested | Medium | Low — falls through to single-section fallback | Whitelist is extensible; add keywords as new books are onboarded |
| ALLCAPS regex matches uppercase body text (false positive) | Low | Medium — spurious section split, wrong card grouping | Whitelist anchors to line start (`^`) and requires the keyword to occupy the whole line or be followed only by a numbering suffix |
| LaTeX pattern misses variant commands (e.g., `\subsection*{}`) | Low | Low — subsections are rare in tested college_algebra data | Pattern can be extended to cover `\subsection*{}` with a one-line change |
| Normalisation changes prealgebra output (regression) | Low | High — prealgebra is the only fully functional book today | Neither `re.sub()` pattern matches `## ` headers; confirmed by test suite |
| Concept text from future books uses a fourth unknown format | Low | Medium — monolithic blob, 2–3 cards | Log a warning when `_parse_sub_sections` returns 0 or 1 sections from text > 2 KB so the problem surfaces immediately |

---

## Key Decisions Requiring Stakeholder Input

1. **Whitelist completeness:** The ALLCAPS keyword whitelist was derived from the five books in the problem statement. If additional books are onboarded before this fix ships, the backend developer should sample their ChromaDB concept text to verify all section markers are covered.
2. **`\subsection*{}` handling:** college_algebra may use `\subsection*{}` in some concepts. Confirm whether this command appears in the actual ChromaDB data before implementation to decide whether to include it in the LaTeX pattern.
3. **Logging threshold:** The recommended warning threshold (text > 2 KB with 0–1 sections returned) should be validated against production data to avoid log noise for genuinely short concepts.
