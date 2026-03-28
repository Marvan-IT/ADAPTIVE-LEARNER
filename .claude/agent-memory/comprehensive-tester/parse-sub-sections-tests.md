---
name: _parse_sub_sections test notes
description: Behavioral edge cases discovered while writing tests for TeachingService._parse_sub_sections()
type: feedback
---

## Test file
`backend/tests/test_parse_sub_sections.py` — 22 tests across 7 classes (all passing).

## Return value shape
Dict keys are `"title"` and `"text"` (NOT `"content"`, NOT `"section_type"`).
Empty-text sections are filtered before return — do not assert their existence.

## LaTeX normalisation guard
Pass 1 fires only when `r'\section'` (the 8-char substring `\section`) is present.
`r'\subsection'` does NOT contain `r'\section'` as a substring in Python string
containment (the characters are `\subsection`, and `\section` ≠ `\subsection`).

**Why:** `r'\subsection*{Title}'` in Python is the string `\subsection*{Title}`.
The guard `r'\section' in text` looks for the literal bytes `\`, `s`, `e`, `c`,
`t`, `i`, `o`, `n` consecutively — and in `\subsection` those bytes are prefixed
by `\sub`, so the match fails.

**Implication:** a text block containing ONLY `\subsection` headers (no `\section`)
will skip Pass 1 and the LaTeX headers will NOT be normalised.  In practice this
does not matter for real books because chapters always mix `\section` and
`\subsection` lines, so the guard always fires.

**How to apply:** TC-05 must use a mixed `\section` + `\subsection` text to exercise
subsection normalisation — do not test `\subsection` alone expecting normalisation.

## ALLCAPS header detection strips leading whitespace
The ALLCAPS check does `stripped = line.strip()` before `_ALLCAPS_SECTION_RE.fullmatch(stripped)`.
So `    EXAMPLE 3.1` (leading spaces) IS treated as a header, same as `EXAMPLE 3.1`.

**Side effect:** if the promoted line was the only body line of a preceding `## Title`
section, that section ends up with empty text and is filtered out.
Example: `## Intro\n    EXAMPLE 3.1\nBody` → result is 1 section (EXAMPLE 3.1), not 2.

## False-positive guard scope
The regex uses `fullmatch` on the stripped line, so it does NOT match:
- `EXAMPLE of substitution` (extra words after the keyword that are not a decimal number)
- `The EXAMPLE of this...` (whole sentence — fullmatch fails because it includes "The")

Words mid-sentence are safe because fullmatch requires the entire stripped line to
match — not just a substring.
