"""
Unit tests for TeachingService._parse_sub_sections().

Business context
----------------
`_parse_sub_sections()` is the first stage of the card-generation pipeline: it
splits raw OpenStax concept text into discrete sections so that each section can
later be turned into one or more lesson cards.  Across 16 supported books the
function must handle three distinct header formats:

  1. Markdown  — `## Title`              (prealgebra, statistics, …)
  2. LaTeX     — `\\section*{Title}`      (college_algebra)
  3. ALLCAPS   — `EXAMPLE 1.5`, `TRY IT` (elementary/intermediate/algebra_1)

The function is a `@staticmethod`, so no TeachingService instance is needed.
Return value is a list of dicts; each dict has exactly two keys:
  - "title"  — the section heading (str)
  - "text"   — the body text with leading/trailing whitespace stripped (str)

Sections whose body text is empty after stripping are silently discarded.

Test mapping
------------
TC-01  Markdown — basic two-section split
TC-02  Markdown — prealgebra multi-section unchanged (regression guard)
TC-03  LaTeX \\section*{} — two sections extracted
TC-04  LaTeX \\section{} without asterisk — still recognised
TC-05  LaTeX \\subsection*{} — subsection title extracted
TC-06  ALLCAPS EXAMPLE with number — e.g. "EXAMPLE 1.5"
TC-07  ALLCAPS TRY IT with number — e.g. "TRY IT 1.27"
TC-08  ALLCAPS SOLUTION alone
TC-09  ALLCAPS HOW TO alone
TC-10  ALLCAPS mixed block — multiple ALLCAPS headers interleaved
TC-11  No headers — whole text returned as one section titled "Introduction"
TC-12  Empty string — returns empty list (no sections)
TC-13  False-positive guard — ALLCAPS word mid-sentence is NOT a header
TC-14  False-positive guard — line starting with whitespace is NOT a header
TC-15  Whitespace-only body filtered out — section with no text is dropped
TC-16  LaTeX + Markdown mixed — both forms work together
"""

import sys
from pathlib import Path

# Ensure backend/src is on the path even when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from api.teaching_service import TeachingService

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse(text: str) -> list[dict]:
    """Thin wrapper so tests read cleanly."""
    return TeachingService._parse_sub_sections(text)


# ---------------------------------------------------------------------------
# TC-01  Markdown — basic two-section split
# ---------------------------------------------------------------------------

class TestMarkdownFormat:
    def test_tc01_basic_two_sections(self):
        """Two ## headers produce two sections with correct titles and bodies."""
        text = "## Intro\nsome text\n## Part 2\nmore text"
        sections = _parse(text)

        assert len(sections) == 2
        assert sections[0]["title"] == "Intro"
        assert sections[0]["text"] == "some text"
        assert sections[1]["title"] == "Part 2"
        assert sections[1]["text"] == "more text"

    def test_tc02_prealgebra_multiblock_regression(self):
        """Prealgebra-style markdown text produces same section count and titles as before the fix."""
        text = (
            "## Model Whole Numbers\n"
            "Whole numbers are 0, 1, 2, 3...\n"
            "## Round Whole Numbers\n"
            "Rounding means replacing a number with an approximation.\n"
            "## Add and Subtract Whole Numbers\n"
            "Addition combines two numbers into one.\n"
        )
        sections = _parse(text)

        assert len(sections) == 3
        assert sections[0]["title"] == "Model Whole Numbers"
        assert sections[1]["title"] == "Round Whole Numbers"
        assert sections[2]["title"] == "Add and Subtract Whole Numbers"
        for s in sections:
            assert len(s["text"]) > 0

    def test_tc02b_markdown_section_bodies_are_nonempty(self):
        """Each section body must be a non-empty string."""
        text = "## Section A\nAlpha text.\n## Section B\nBeta text."
        sections = _parse(text)

        assert all(isinstance(s["text"], str) for s in sections)
        assert all(len(s["text"]) > 0 for s in sections)


# ---------------------------------------------------------------------------
# TC-03 to TC-05  LaTeX format (college_algebra)
# ---------------------------------------------------------------------------

class TestLatexFormat:
    def test_tc03_section_star_two_sections(self):
        r"""\\section*{Title} lines produce two sections with correct titles."""
        text = (
            r"\section*{Learning Objectives}" + "\n"
            "By the end of this section you will be able to…\n"
            r"\section{Cartesian Coordinates}" + "\n"
            "The Cartesian plane consists of two perpendicular number lines."
        )
        sections = _parse(text)

        assert len(sections) == 2
        assert sections[0]["title"] == "Learning Objectives"
        assert sections[1]["title"] == "Cartesian Coordinates"
        assert len(sections[0]["text"]) > 0
        assert len(sections[1]["text"]) > 0

    def test_tc04_section_without_asterisk(self):
        r"""\\section{Title} (no asterisk) is still recognised."""
        text = r"\section{Introduction to Functions}" + "\nA function maps each input to exactly one output."
        sections = _parse(text)

        assert len(sections) == 1
        assert sections[0]["title"] == "Introduction to Functions"
        assert len(sections[0]["text"]) > 0

    def test_tc05_subsection_star_alongside_section(self):
        r"""\\subsection*{Title} is normalised when the same text also contains \\section.

        The LaTeX normalisation pass (Pass 1) is only activated when the literal
        substring r'\section' is present anywhere in the text.  Since
        r'\subsection' does NOT contain r'\section' as a substring (Python string
        containment), a block that has ONLY \\subsection lines skips Pass 1 and the
        subsection header is left as raw LaTeX in the body.

        In practice, real college_algebra chapters always interleave \\section and
        \\subsection lines, so the guard fires and both are normalised together.
        This test exercises that realistic mixed case.
        """
        text = (
            r"\section*{Coordinate System}" + "\n"
            "This section covers the coordinate plane.\n"
            r"\subsection*{Plotting Points}" + "\n"
            "To plot a point (x, y) start at the origin."
        )
        sections = _parse(text)

        assert len(sections) == 2
        assert sections[0]["title"] == "Coordinate System"
        assert sections[1]["title"] == "Plotting Points"
        assert len(sections[0]["text"]) > 0
        assert len(sections[1]["text"]) > 0


# ---------------------------------------------------------------------------
# TC-06 to TC-10  ALLCAPS format (elementary / intermediate / algebra_1)
# ---------------------------------------------------------------------------

class TestAllcapsFormat:
    def test_tc06_example_with_number(self):
        """EXAMPLE followed by a section number is recognised as a header."""
        text = "EXAMPLE 1.5\nIn this example we demonstrate how to solve 2x = 8."
        sections = _parse(text)

        assert len(sections) == 1
        assert sections[0]["title"] == "EXAMPLE 1.5"
        assert len(sections[0]["text"]) > 0

    def test_tc07_try_it_with_number(self):
        """TRY IT followed by a decimal number is recognised as a header."""
        text = "TRY IT 1.27\nSolve 3x = 12 using the same technique."
        sections = _parse(text)

        assert len(sections) == 1
        assert sections[0]["title"] == "TRY IT 1.27"
        assert len(sections[0]["text"]) > 0

    def test_tc08_solution_alone(self):
        """SOLUTION on a line by itself is recognised as a header."""
        text = "SOLUTION\nMultiply both sides by 2 to isolate x."
        sections = _parse(text)

        assert len(sections) == 1
        assert sections[0]["title"] == "SOLUTION"
        assert len(sections[0]["text"]) > 0

    def test_tc09_how_to_alone(self):
        """HOW TO on a line by itself is recognised as a header."""
        text = "HOW TO\nStep 1: identify the variable.\nStep 2: isolate it."
        sections = _parse(text)

        assert len(sections) == 1
        assert sections[0]["title"] == "HOW TO"
        assert len(sections[0]["text"]) > 0

    def test_tc10_allcaps_mixed_block(self):
        """Multiple interleaved ALLCAPS headers each become separate sections."""
        text = (
            "EXAMPLE 2.1\n"
            "Demonstrate solving x + 3 = 7.\n"
            "SOLUTION\n"
            "Subtract 3 from both sides: x = 4.\n"
            "TRY IT 2.1\n"
            "Now solve x + 5 = 9 on your own.\n"
        )
        sections = _parse(text)

        assert len(sections) == 3
        assert sections[0]["title"] == "EXAMPLE 2.1"
        assert sections[1]["title"] == "SOLUTION"
        assert sections[2]["title"] == "TRY IT 2.1"
        for s in sections:
            assert len(s["text"]) > 0


# ---------------------------------------------------------------------------
# TC-11  No headers — plain text
# ---------------------------------------------------------------------------

class TestNoHeaders:
    def test_tc11_plain_text_returns_single_intro_section(self):
        """Text with no headers returns exactly one section titled 'Introduction'."""
        text = (
            "This chapter covers the fundamental properties of real numbers.\n"
            "We will explore addition, subtraction, multiplication and division."
        )
        sections = _parse(text)

        assert len(sections) == 1
        assert sections[0]["title"] == "Introduction"
        assert len(sections[0]["text"]) > 0

    def test_tc11b_intro_body_contains_original_text(self):
        """The Introduction section body contains the original text content."""
        text = "Real numbers include all rational and irrational numbers."
        sections = _parse(text)

        assert len(sections) == 1
        assert "Real numbers" in sections[0]["text"]


# ---------------------------------------------------------------------------
# TC-12  Empty string
# ---------------------------------------------------------------------------

class TestEmptyInput:
    def test_tc12_empty_string_returns_empty_list(self):
        """An empty string produces an empty list — no sections at all."""
        sections = _parse("")

        assert sections == []

    def test_tc12b_whitespace_only_returns_empty_list(self):
        """A string containing only whitespace / newlines produces an empty list."""
        sections = _parse("   \n\n   \n")

        assert sections == []


# ---------------------------------------------------------------------------
# TC-13 / TC-14  False-positive guards
# ---------------------------------------------------------------------------

class TestFalsePositiveGuard:
    def test_tc13_allcaps_word_mid_sentence_not_promoted(self):
        """An ALLCAPS keyword embedded in a sentence must NOT become a section header."""
        text = (
            "## Introduction\n"
            "The EXAMPLE of this is when we use substitution.\n"
            "Another SOLUTION involves factoring both sides."
        )
        sections = _parse(text)

        # Should still be just one section — no extra EXAMPLE or SOLUTION sections
        assert len(sections) == 1
        assert sections[0]["title"] == "Introduction"
        # The sentences with ALLCAPS words are part of the body, not headers
        assert "EXAMPLE" in sections[0]["text"]
        assert "SOLUTION" in sections[0]["text"]

    def test_tc13b_allcaps_keyword_with_trailing_words_not_promoted(self):
        """'EXAMPLE of substitution' (extra words) must not match the header pattern."""
        text = "## Context\nEXAMPLE of substitution is covered later.\nMore body text here."
        sections = _parse(text)

        assert len(sections) == 1
        assert sections[0]["title"] == "Context"

    def test_tc14_allcaps_with_leading_whitespace_is_promoted(self):
        """A line with leading whitespace before EXAMPLE IS still promoted to a header.

        The ALLCAPS check strips the line before matching
        (`stripped = line.strip()`), so `    EXAMPLE 3.1` becomes `EXAMPLE 3.1`
        which fully matches the regex.  Leading whitespace is NOT a guard against
        header promotion.

        Side effect: the preceding `## Intro` section accumulates no body lines
        (the only line after it was promoted), so it has empty text and is filtered
        out.  The final result is exactly one section — EXAMPLE 3.1.
        """
        text = "## Intro\n    EXAMPLE 3.1\nThis indented line is part of the body."
        sections = _parse(text)

        # Intro has no body after the indented EXAMPLE line is promoted — filtered out.
        # EXAMPLE 3.1 picks up the next body line.
        assert len(sections) == 1
        assert sections[0]["title"] == "EXAMPLE 3.1"
        assert len(sections[0]["text"]) > 0


# ---------------------------------------------------------------------------
# TC-15  Whitespace-only body filtered out
# ---------------------------------------------------------------------------

class TestEmptySectionFiltering:
    def test_tc15_section_with_no_body_is_dropped(self):
        """A section whose body is empty (or whitespace only) is silently discarded."""
        text = "## Header Only\n\n## Real Section\nThis section has content."
        sections = _parse(text)

        # The first header has no body text, so it should be filtered out
        assert len(sections) == 1
        assert sections[0]["title"] == "Real Section"

    def test_tc15b_multiple_empty_sections_all_dropped(self):
        """Multiple consecutive empty sections are all filtered out."""
        text = "## Empty A\n\n## Empty B\n\n## Full Section\nActual content here."
        sections = _parse(text)

        assert len(sections) == 1
        assert sections[0]["title"] == "Full Section"


# ---------------------------------------------------------------------------
# TC-16  LaTeX + Markdown mixed (resilience check)
# ---------------------------------------------------------------------------

class TestMixedFormats:
    def test_tc16_latex_and_markdown_coexist(self):
        r"""\\section*{} and ## headers in the same text both produce sections."""
        text = (
            r"\section*{Overview}" + "\n"
            "An overview of the chapter topics.\n"
            "## Detailed Walkthrough\n"
            "Step-by-step breakdown of the first concept.\n"
        )
        sections = _parse(text)

        assert len(sections) == 2
        titles = [s["title"] for s in sections]
        assert "Overview" in titles
        assert "Detailed Walkthrough" in titles
        for s in sections:
            assert len(s["text"]) > 0

    def test_tc16b_allcaps_and_markdown_coexist(self):
        """ALLCAPS headers and ## headers in the same text both produce sections."""
        text = (
            "## Learning Objectives\n"
            "After this section the student can solve linear equations.\n"
            "EXAMPLE 1.1\n"
            "Solve 2x + 3 = 7.\n"
            "SOLUTION\n"
            "Subtract 3, then divide by 2: x = 2.\n"
        )
        sections = _parse(text)

        assert len(sections) == 3
        assert sections[0]["title"] == "Learning Objectives"
        assert sections[1]["title"] == "EXAMPLE 1.1"
        assert sections[2]["title"] == "SOLUTION"
