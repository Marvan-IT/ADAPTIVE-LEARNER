# Detailed Low-Level Design: Universal Section Parsing

**Feature slug:** `universal-section-parsing`
**Date:** 2026-03-24
**Author:** solution-architect

---

## 1. Component Breakdown

Only one component is modified.

| Component | File | Change Type |
|-----------|------|-------------|
| `TeachingService._parse_sub_sections()` | `backend/src/api/teaching_service.py` | Modify — add normalisation pre-pass |

All other components (`_classify_sections`, `_build_textbook_blueprint`, `_group_by_major_topic`, `generate_cards`, `_batch_consecutive_try_its`) are read-only with respect to this fix.

---

## 2. Existing Code Structure (as read from source)

Current implementation at lines 2113–2143:

```python
@staticmethod
def _parse_sub_sections(text: str) -> list[dict]:
    """Split concept text by ## headers into sub-sections."""
    sections = []
    current_title = ""
    current_lines = []

    for line in text.split("\n"):
        if line.startswith("## "):
            # Save previous section
            if current_title or current_lines:
                sections.append({
                    "title": current_title or "Introduction",
                    "text": "\n".join(current_lines).strip(),
                })
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Save last section
    if current_title or current_lines:
        sections.append({
            "title": current_title or "Introduction",
            "text": "\n".join(current_lines).strip(),
        })

    # Filter out empty sections
    sections = [s for s in sections if s["text"]]

    return sections
```

The function is called at line 825:

```python
sub_sections = self._parse_sub_sections(concept_text)
if not sub_sections:
    sub_sections = [{"title": concept_title, "text": concept_text}]
else:
    classified = self._classify_sections(sub_sections)
    blueprint = self._build_textbook_blueprint(classified)
    if len(blueprint) >= 2:
        sub_sections = blueprint
    else:
        sub_sections = self._group_by_major_topic(sub_sections)
```

The caller's fallback behaviour (single-section when the list is empty) is preserved by this fix — when concept text genuinely has no recognisable headers in any format, the normalisation passes are no-ops and the function still returns `[]`.

---

## 3. Detailed Specification for `_parse_sub_sections()`

### 3.1 Module-Level Constants

Define the following constants at module level in `teaching_service.py`, alongside the other module-level regex constants already present. Do not define them inside the function body.

```python
import re  # already imported

# --- Universal section parsing constants ---

# Matches LaTeX section/subsection commands:
#   \section*{Title Text}
#   \section{Title Text}
#   \subsection*{Title Text}
#   \subsection{Title Text}
# Capture group 1: the title text inside braces.
_LATEX_SECTION_RE = re.compile(
    r"^\\(?:sub)?section\*?\{(.+?)\}\s*$",
    re.MULTILINE,
)

# Matches ALLCAPS OpenStax pedagogical section markers, optionally followed
# by a numbering suffix (e.g., "EXAMPLE 1.5", "TRY IT 1.27").
# The keyword must appear at the start of the line and must occupy the
# entire line (possibly with trailing whitespace and/or a number).
# Only whitelisted keywords are matched to avoid false positives on
# uppercase body text.
_ALLCAPS_SECTION_RE = re.compile(
    r"^("
    r"EXAMPLE"
    r"|SOLUTION"
    r"|TRY IT"
    r"|HOW TO"
    r"|MANIPULATIVE MATHEMATICS"
    r"|MEDIA"
    r"|LEARNING OBJECTIVES"
    r"|GLOSSARY"
    r"|KEY CONCEPTS"
    r"|NOTE"
    r"|BE CAREFUL"
    r"|LINK TO LITERACY"
    r"|EVERYDAY MATH"
    r"|WRITING EXERCISES"
    r"|PRACTICE MAKES PERFECT"
    r"|MIXED PRACTICE"
    r"|REVIEW EXERCISES"
    r"|PRACTICE TEST"
    r"|ACCESS ADDITIONAL[^\n]*"
    r")"
    r"(\s+[\d.]+)?"   # optional numbering suffix: " 1.5" or " 1.27"
    r"\s*$",
    re.MULTILINE,
)
```

### 3.2 Normalisation Logic

The normalisation is applied once at the entry point of `_parse_sub_sections()` before the existing line iterator. It operates on a **local copy** of `text` — the original argument is never mutated.

**Pass 1 — LaTeX to Markdown:**

```python
normalised = _LATEX_SECTION_RE.sub(lambda m: f"## {m.group(1).strip()}", text)
```

This replaces every `\section*{Polynomial Functions}` (and variants) with `## Polynomial Functions` on the same line. All other lines are untouched.

**Pass 2 — ALLCAPS to Markdown:**

```python
def _allcaps_to_md(m: re.Match) -> str:
    keyword = m.group(1).strip()          # e.g., "EXAMPLE"
    suffix  = (m.group(2) or "").strip()  # e.g., "1.5" (may be empty)
    title   = keyword.capitalize()
    if suffix:
        title = f"{title} {suffix}"
    return f"## {title}"

normalised = _ALLCAPS_SECTION_RE.sub(_allcaps_to_md, normalised)
```

This converts `EXAMPLE 1.5` → `## Example 1.5` and `SOLUTION` → `## Solution`. The `.capitalize()` call lower-cases all characters after the first, which matches the title casing already produced by Markdown-format books.

**Note on `TRY IT`:** The keyword `TRY IT` is two words. After `.capitalize()` it becomes `Try it`, which is consistent with how `_classify_sections()` and `_group_by_major_topic()` already recognise it via case-insensitive regex (`try it\b`).

### 3.3 Complete Updated Function

```python
@staticmethod
def _parse_sub_sections(text: str) -> list[dict]:
    """
    Split concept text by ## headers into sub-sections.

    Normalises all three known header formats to ## before splitting:
      - LaTeX:   \\section*{Title}  →  ## Title
      - ALLCAPS: EXAMPLE 1.5        →  ## Example 1.5
      - Markdown ## Title            →  unchanged (pass-through)
    """
    # --- Normalisation pre-pass (local copy only) ---
    def _allcaps_to_md(m: re.Match) -> str:
        keyword = m.group(1).strip()
        suffix  = (m.group(2) or "").strip()
        title   = keyword.capitalize()
        return f"## {title} {suffix}".rstrip() if suffix else f"## {title}"

    normalised = _LATEX_SECTION_RE.sub(
        lambda m: f"## {m.group(1).strip()}", text
    )
    normalised = _ALLCAPS_SECTION_RE.sub(_allcaps_to_md, normalised)

    # --- Existing split logic (unchanged) ---
    sections = []
    current_title = ""
    current_lines = []

    for line in normalised.split("\n"):
        if line.startswith("## "):
            if current_title or current_lines:
                sections.append({
                    "title": current_title or "Introduction",
                    "text": "\n".join(current_lines).strip(),
                })
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_title or current_lines:
        sections.append({
            "title": current_title or "Introduction",
            "text": "\n".join(current_lines).strip(),
        })

    sections = [s for s in sections if s["text"]]

    if len(sections) <= 1 and len(text) > 2048:
        logger.warning(
            "_parse_sub_sections: returned %d section(s) for %d-char text "
            "(no recognised headers found)",
            len(sections), len(text),
        )

    return sections
```

---

## 4. Edge Cases

| Case | Input | Expected Output | Rationale |
|------|-------|----------------|-----------|
| Empty string | `""` | `[]` | No sections, caller fallback applies |
| Whitespace only | `"   \n\n  "` | `[]` | No non-empty body text |
| Markdown only (prealgebra) | `"## Introduction\ntext\n## Section 2\nmore"` | Two sections, titles `Introduction` and `Section 2` | No-op normalisation; existing behaviour unchanged |
| LaTeX only (college_algebra) | `"\\section*{Polynomials}\ntext\n\\section*{Rational}"` | Two sections, titles `Polynomial` and `Rational` | Pass 1 converts to `##`; Pass 2 is no-op |
| ALLCAPS numbered (elementary_algebra) | `"EXAMPLE 1.5\ntext\nSOLUTION\nmore"` | Two sections, titles `Example 1.5` and `Solution` | Pass 1 is no-op; Pass 2 converts both |
| ALLCAPS bare (intermediate_algebra) | `"EXAMPLE\ntext\nSOLUTION\nmore"` | Two sections, titles `Example` and `Solution` | Pass 1 is no-op; Pass 2 converts both |
| Mixed Markdown + ALLCAPS | `"## Intro\ntext\nEXAMPLE 1.5\nbody"` | Two sections | Markdown header survives unchanged; ALLCAPS line is normalised |
| ALLCAPS word in body text (false positive risk) | `"Some NOTE inside a paragraph"` | One section — the NOTE is NOT split | `_ALLCAPS_SECTION_RE` requires the keyword at `^` (line start) with nothing else on the line except an optional number suffix; mid-sentence occurrences are not matched |
| LaTeX body math `$\section$` | `"The $\\section$ symbol"` | One section (no split) | The pattern requires `^\\section` at line start; `$\section$` is mid-line inline math, no match |
| Concept text with only body text, no headers | `"Just prose content."` | `[]` | Neither pass matches; existing fallback in caller applies |
| `\section` without star | `"\\section{Title}\ntext"` | One section, title `Title` | Pattern covers both `\section*{}` and `\section{}` via `\*?` |
| `\subsection*{Title}` | `"\\subsection*{Sub}\ntext"` | One section, title `Sub` | Pattern covers `(?:sub)?section` |
| Last section has no trailing newline | `"## A\ntext"` | One section | Existing "Save last section" guard handles this correctly |
| All sections empty after strip | `"## A\n\n## B\n\n"` | `[]` | Existing empty-filter `[s for s in sections if s["text"]]` still applies |

---

## 5. Compatibility with `_classify_sections()`

`_classify_sections()` (lines 2180–2191) receives the `list[dict]` returned by `_parse_sub_sections()`. It classifies each section's `title` field using a pre-compiled `_SECTION_CLASSIFIER` list of `(pattern, type)` tuples. All patterns in `_SECTION_CLASSIFIER` are case-insensitive (`re.IGNORECASE` or `.lower()` is applied to `title`).

The normalised section titles produced by this fix are compatible with the existing classifier because:

- `Example 1.5` → matches `example\b` (EXAMPLE type) — correct.
- `Solution` → matches `solution\b` (SOLUTION type) — correct.
- `Try it 1.27` → matches `try it\b` (TRY_IT type) — correct.
- `Polynomial Functions` (from LaTeX) → no support-heading match → classified as CONCEPT — correct.

No changes to `_classify_sections()`, `_build_textbook_blueprint()`, or `_group_by_major_topic()` are required.

---

## 6. Data Design

No database changes. No schema changes. No configuration changes. The fix operates entirely on the in-memory string returned from ChromaDB via `concept["text"]`.

---

## 7. API Design

Not applicable. This fix is internal to a static method; it is not exposed via any API endpoint. No request/response schema changes.

---

## 8. Sequence Diagram

### Happy Path — ALLCAPS format (elementary_algebra)

```
generate_cards()
    │
    ├─ concept_text = concept["text"]
    │       (raw: "EXAMPLE 1.5\nbody\nSOLUTION\nanswer\nTRY IT 1.27\nexercise")
    │
    ├─ sub_sections = _parse_sub_sections(concept_text)
    │       │
    │       ├─ Pass 1 (LaTeX): no match → normalised unchanged
    │       ├─ Pass 2 (ALLCAPS):
    │       │       "EXAMPLE 1.5\n..."  →  "## Example 1.5\n..."
    │       │       "SOLUTION\n..."     →  "## Solution\n..."
    │       │       "TRY IT 1.27\n..." →  "## Try it 1.27\n..."
    │       │
    │       ├─ Line iterator: finds 3 "## " headers
    │       └─ returns [
    │               {"title": "Example 1.5",  "text": "body"},
    │               {"title": "Solution",     "text": "answer"},
    │               {"title": "Try it 1.27",  "text": "exercise"},
    │          ]
    │
    ├─ classified = _classify_sections(sub_sections)
    │       → EXAMPLE, SOLUTION, TRY_IT (all matched correctly)
    │
    ├─ blueprint = _build_textbook_blueprint(classified)
    │       → SOLUTION merged into preceding EXAMPLE
    │       → returns [
    │               {"title": "Example 1.5", "text": "body\n\n**Solution:**\nanswer"},
    │               {"title": "Try it 1.27", "text": "exercise"},
    │          ]
    │
    └─ card generation with 2 blueprint items (was 1 monolithic blob)
```

### Edge Case — No Headers Found

```
generate_cards()
    │
    ├─ concept_text = "Plain prose with no headers at all."
    │
    ├─ sub_sections = _parse_sub_sections(concept_text)
    │       │
    │       ├─ Pass 1 (LaTeX): no match
    │       ├─ Pass 2 (ALLCAPS): no match
    │       ├─ Line iterator: no "## " headers found
    │       └─ returns []
    │
    ├─ if not sub_sections:  ← caller fallback
    │       sub_sections = [{"title": concept_title, "text": concept_text}]
    │
    └─ (proceeds with single-section generation, same as before)
```

---

## 9. Integration Design

Not applicable. No external services, message queues, or third-party APIs are involved. The function operates on a local string.

---

## 10. Security Design

Not applicable. The input is internal ChromaDB-stored text from the extraction pipeline, not user-supplied input. No injection risk exists in this context. The `re.sub()` calls operate in linear time on the input string and do not expose catastrophic backtracking (the patterns are anchored and use no nested quantifiers).

---

## 11. Observability Design

One `logger.warning()` call is added (see Section 3.3) when the function returns 0–1 sections from a text longer than 2048 characters. This surfaces any future books whose header format is not covered by the two normalisation passes.

Log format:
```
_parse_sub_sections: returned 0 section(s) for 8432-char text (no recognised headers found)
```

This uses the existing `logger` instance in `teaching_service.py` and requires no new logging configuration.

---

## 12. Error Handling and Resilience

- The normalisation is a pure string transformation. It cannot raise an exception unless the compiled regex is invalid — which is caught at module import time, not at runtime.
- If both normalisation passes produce no `##` headers (e.g., a future unknown format), the function returns `[]` and the caller's existing fallback (`[single-section]`) applies. The student still receives cards; they are just generated from the monolithic blob as before. No degradation beyond the current baseline.
- The added `logger.warning()` provides operational visibility without affecting the happy path.

---

## 13. Testing Strategy

See `execution-plan.md` Stage 3 for the full test task list. Summary:

| Test Class | Coverage Target |
|------------|----------------|
| `TestLaTeXNormalisation` | `\section*{}`, `\section{}`, `\subsection*{}`, body-math false-positive rejection |
| `TestAllcapsNormalisation` | `EXAMPLE N.N`, `SOLUTION`, `TRY IT N.N`, `HOW TO`, bare `NOTE`, `ACCESS ADDITIONAL RESOURCES` (long suffix) |
| `TestMarkdownPassthrough` | Existing `## ` format; confirm zero change to output |
| `TestMixedFormats` | Markdown + ALLCAPS in same text |
| `TestEdgeCases` | Empty string, whitespace-only, no headers, single-section, last section no trailing newline |
| `TestClassifierCompatibility` | Normalised titles are correctly classified by `_classify_sections()` |

All tests are pure unit tests targeting `TeachingService._parse_sub_sections()` directly. No database, no LLM, no HTTP calls.

---

## Key Decisions Requiring Stakeholder Input

1. **`\subsection*{}` inclusion:** The LaTeX pattern covers `\subsection*{}` based on the assumption it appears in college_algebra data. If it does not, the pattern is still harmless (no match, no change). Confirm with the backend developer after sampling college_algebra ChromaDB entries.
2. **Warning threshold (2048 chars):** This value was chosen to avoid noise on genuinely short concepts (< 2 KB). Adjust in `config.py` as `PARSE_SECTIONS_WARN_THRESHOLD = 2048` if the team prefers a configurable constant rather than an inline literal.
3. **`capitalize()` vs `title()`:** `keyword.capitalize()` produces `Try it` from `TRY IT`. Using `str.title()` would produce `Try It`. The existing `_group_by_major_topic` pattern `try it\b` matches both (case-insensitive). Confirm preferred casing with the backend developer for consistency with card titles shown to students.
