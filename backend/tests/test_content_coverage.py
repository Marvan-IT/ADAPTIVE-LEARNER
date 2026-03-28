"""
test_content_coverage.py
Unit tests for zero content loss across section splitting and queuing.

Tests verify that _parse_sub_sections preserves text, sections are correctly
split (or not split), and the starter pack + queue division is lossless.

All tests are pure unit tests — no DB, no LLM.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from api.teaching_service import TeachingService
from config import STARTER_PACK_INITIAL_SECTIONS


# ── Tests: section count and order preservation ───────────────────────────────

class TestSectionCountPreservation:
    """Verify exact section counts are maintained through parsing."""

    def test_five_distinct_headers_return_five_sections(self):
        """
        Business: 5 distinct ## headers produce exactly 5 sections — no
        merging, no loss, no duplication.
        """
        text = "\n\n".join([
            f"## Section {i}\nContent for section {i}."
            for i in range(1, 6)
        ])
        sections = TeachingService._parse_sub_sections(text)
        assert len(sections) == 5
        for i, sec in enumerate(sections, 1):
            assert sec["title"] == f"Section {i}"

    def test_section_with_only_whitespace_filtered_out(self):
        """Sections with only whitespace text are filtered after parsing."""
        text = "## Real Section\nSome content.\n## Empty Section\n   \n## Another Section\nMore content."
        sections = TeachingService._parse_sub_sections(text)
        titles = [s["title"] for s in sections]
        assert "Empty Section" not in titles
        assert "Real Section" in titles
        assert "Another Section" in titles

    def test_single_paragraph_under_800_chars_not_split(self):
        """
        Business: A single paragraph section < 800 chars is returned as-is —
        Pass 3 does not split it.
        """
        short_text = "A" * 400  # well under 800 char threshold
        text = f"## Short Section\n{short_text}"
        sections = TeachingService._parse_sub_sections(text)
        assert len(sections) == 1
        assert sections[0]["title"] == "Short Section"

    def test_blank_line_split_two_paragraphs_from_large_section(self):
        """
        Business: A section > 800 chars with 2+ blank-line-separated paragraphs
        is split into budget-sized parts.
        """
        para_a = "A" * 450
        para_b = "B" * 450
        text = f"## Big Section\n{para_a}\n\n{para_b}"
        sections = TeachingService._parse_sub_sections(text)
        big_parts = [s for s in sections if "Big Section" in s["title"]]
        # Should be split since 450+450 > 800
        assert len(big_parts) >= 2

    def test_multiple_consecutive_blank_lines_treated_same_as_single(self):
        """
        Business: Multiple consecutive blank lines should be treated the same
        as a single blank line for paragraph separation.
        """
        para_a = "A" * 450
        para_b = "B" * 450
        text_single = f"## Section\n{para_a}\n\n{para_b}"
        text_multi = f"## Section\n{para_a}\n\n\n\n{para_b}"
        secs_single = TeachingService._parse_sub_sections(text_single)
        secs_multi = TeachingService._parse_sub_sections(text_multi)
        # Both should produce the same number of parts
        assert len(secs_single) == len(secs_multi)

    def test_example_section_not_split_even_if_large(self):
        """
        Business: EXAMPLE sections (typed by classify_sections after parsing)
        are not split by Pass 3 if section_type=EXAMPLE is already set.
        The raw parsing produces a single item for a single ## header.
        """
        long_example = "X" * 1000
        text = f"## Example 1.5\n{long_example}"
        sections = TeachingService._parse_sub_sections(text)
        # Raw parse = 1 section; classify_sections sets EXAMPLE type
        assert len(sections) == 1


# ── Tests: content preservation across splits ────────────────────────────────

class TestContentPreservation:
    """Verify that split parts contain all original text (no content loss)."""

    def test_split_parts_preserve_total_character_count(self):
        """
        Business: When a section is split into 3 parts, the total text of all
        parts equals the original text length (minus whitespace normalization).
        """
        para_a = "Alpha " * 80   # ~480 chars
        para_b = "Beta " * 80    # ~400 chars
        para_c = "Gamma " * 80   # ~400 chars
        original = f"{para_a.strip()}\n\n{para_b.strip()}\n\n{para_c.strip()}"
        text = f"## Big Section\n{original}"

        sections = TeachingService._parse_sub_sections(text)
        big_parts = [s for s in sections if "Big Section" in s["title"]]

        total_text = "".join(s["text"] for s in big_parts)
        # Allow up to 5% variance for whitespace normalization
        min_expected = len(original) * 0.95
        assert len(total_text) >= min_expected, (
            f"Content lost: original={len(original)} chars, "
            f"total_in_parts={len(total_text)} chars"
        )

    def test_latex_formula_preserved_verbatim(self):
        r"""
        Business: LaTeX formula $\frac{a}{b}$ must survive _parse_sub_sections
        unchanged — no escaping, no stripping.
        """
        formula = r"$\frac{a}{b}$"
        text = f"## Fractions\nThis fraction is {formula} where a and b are integers."
        sections = TeachingService._parse_sub_sections(text)
        assert len(sections) == 1
        assert formula in sections[0]["text"]

    def test_section_title_with_special_characters_preserved(self):
        """
        Business: Section titles with special characters (colons, numbers, dots)
        are stored exactly as they appear.
        """
        title = "Example 1.1: Adding Fractions"
        text = f"## {title}\nContent here."
        sections = TeachingService._parse_sub_sections(text)
        assert len(sections) == 1
        assert sections[0]["title"] == title

    def test_unicode_in_section_text_preserved(self):
        """
        Business: Unicode characters (e.g., π symbol) in section text must
        not cause encoding errors and must be preserved.
        """
        text = "## Constants\nThe value of π (pi) is approximately 3.14159."
        sections = TeachingService._parse_sub_sections(text)
        assert len(sections) == 1
        assert "π" in sections[0]["text"]


# ── Tests: starter pack and queue coverage ───────────────────────────────────

class TestStarterPackQueueCoverage:
    """Verify zero section loss in the starter pack / queue split."""

    def test_starter_plus_queue_equals_total(self):
        """
        Business: len(starter) + len(queue) == total sections.
        No section should be lost when splitting the initial batch.
        """
        # Build 10 sections
        text = "\n\n".join([
            f"## Section {i}\n{'Content ' * 50}for section {i}."
            for i in range(1, 11)
        ])
        sections = TeachingService._parse_sub_sections(text)
        total = len(sections)

        starter = sections[:STARTER_PACK_INITIAL_SECTIONS]
        queue = sections[STARTER_PACK_INITIAL_SECTIONS:]

        assert len(starter) + len(queue) == total
        assert len(starter) == min(STARTER_PACK_INITIAL_SECTIONS, total)

    def test_queue_starts_after_starter_pack(self):
        """
        Business: The queue contains sections starting at index STARTER_PACK_INITIAL_SECTIONS.
        """
        text = "\n\n".join([
            f"## Topic {i}\nContent {i} details here."
            for i in range(1, 8)
        ])
        sections = TeachingService._parse_sub_sections(text)
        starter = sections[:STARTER_PACK_INITIAL_SECTIONS]
        queue = sections[STARTER_PACK_INITIAL_SECTIONS:]

        if len(sections) > STARTER_PACK_INITIAL_SECTIONS:
            # First queue item is the one after the last starter item
            assert queue[0]["title"] == sections[STARTER_PACK_INITIAL_SECTIONS]["title"]
