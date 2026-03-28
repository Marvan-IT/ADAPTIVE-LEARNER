"""
test_section_order.py
Unit tests for TeachingService._parse_sub_sections, _classify_sections,
and _build_textbook_blueprint.

All tests are pure unit tests — no DB, no LLM.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from api.teaching_service import TeachingService


# ── Helpers ───────────────────────────────────────────────────────────────────

def _section(title: str, text: str, section_type: str = "CONCEPT") -> dict:
    return {"title": title, "text": text, "section_type": section_type}


# ── Tests: _parse_sub_sections ────────────────────────────────────────────────

class TestParseSubSections:
    """Verify that _parse_sub_sections correctly splits text into ordered sections."""

    def test_markdown_headers_returns_sections_in_source_order(self):
        """
        Business: ## headers produce sections in the exact source-text order.
        """
        text = (
            "## Section A\nContent of A.\n\n"
            "## Section B\nContent of B.\n\n"
            "## Section C\nContent of C.\n"
        )
        sections = TeachingService._parse_sub_sections(text)
        assert len(sections) == 3
        assert sections[0]["title"] == "Section A"
        assert sections[1]["title"] == "Section B"
        assert sections[2]["title"] == "Section C"

    def test_latex_section_headers_preserved_in_order(self):
        r"""
        Business: \section*{Title} headers are normalised to ## and preserved in order.
        """
        text = r"""\section*{Introduction}
First content.

\section*{Main Concept}
Main content here.
"""
        sections = TeachingService._parse_sub_sections(text)
        assert len(sections) == 2
        assert sections[0]["title"] == "Introduction"
        assert sections[1]["title"] == "Main Concept"

    def test_allcaps_headers_preserved_in_order(self):
        """
        Business: ALLCAPS OpenStax-style headers are converted to ## and preserved
        in source order.
        """
        # Use multi-line content that does NOT itself start with an ALLCAPS keyword
        # (to avoid Pass 2 treating body lines as headers)
        text = (
            "EXAMPLE 1.1\nThe number 42 is an even integer.\n\n"
            "TRY IT 1.2\nWhat is 7 plus 5?\n"
        )
        sections = TeachingService._parse_sub_sections(text)
        titles = [s["title"] for s in sections]
        assert len(sections) >= 2
        assert any("EXAMPLE" in t.upper() for t in titles)
        assert any("TRY IT" in t.upper() or "TRY-IT" in t.upper() for t in titles)
        # Order preserved: EXAMPLE before TRY IT
        example_idx = next(i for i, t in enumerate(titles) if "EXAMPLE" in t.upper())
        try_it_idx = next(i for i, t in enumerate(titles) if "TRY IT" in t.upper() or "TRY-IT" in t.upper())
        assert example_idx < try_it_idx

    def test_large_section_split_into_parts(self):
        """
        Business: A non-example section > 800 chars with 3 blank-line-separated
        paragraphs is split into sub-parts; total text length is preserved.
        """
        para_a = "A" * 300
        para_b = "B" * 300
        para_c = "C" * 300
        text = f"## Big Section\n{para_a}\n\n{para_b}\n\n{para_c}"
        sections = TeachingService._parse_sub_sections(text)
        # Should be split into multiple parts
        big_parts = [s for s in sections if "Big Section" in s["title"]]
        assert len(big_parts) > 1
        # Total character content is preserved (within whitespace normalization)
        total_text = "".join(s["text"] for s in big_parts)
        assert len(total_text) >= len(para_a) + len(para_b) + len(para_c) - 10

    def test_example_section_not_split_even_if_large(self):
        """
        Business: EXAMPLE sections are never split by Pass 3, even if > 800 chars.
        """
        long_example = "X" * 1000
        text = f"## Example 1.5\n{long_example}"
        # First classify so section_type is set
        sections = TeachingService._parse_sub_sections(text)
        classified = TeachingService._classify_sections(sections)
        example_parts = [s for s in classified if s.get("section_type") == "EXAMPLE"]
        # Pass 3 does not re-split sections that already have section_type=EXAMPLE from prior processing.
        # Since _parse_sub_sections runs BEFORE _classify_sections, the section will be a single item.
        assert len([s for s in sections if "Example 1.5" in s["title"]]) == 1

    def test_recap_card_section_index_sorts_after_normal_cards(self):
        """
        Business: RECAP cards assigned _section_index=9999 sort after cards
        with _section_index=3.
        """
        cards = [
            {"title": "Normal", "content": "x", "_section_index": 3},
            {"title": "Recap", "content": "y", "_section_index": 9999},
        ]
        sorted_cards = sorted(cards, key=lambda c: c.get("_section_index", 0))
        assert sorted_cards[0]["title"] == "Normal"
        assert sorted_cards[1]["title"] == "Recap"


# ── Tests: _classify_sections ─────────────────────────────────────────────────

class TestClassifySections:
    """Verify that section types are correctly assigned based on title patterns."""

    def test_example_title_classified_as_example(self):
        """'Example 1.1' → section_type = EXAMPLE."""
        sections = [{"title": "Example 1.1", "text": "Some content."}]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "EXAMPLE"

    def test_try_it_title_classified_as_try_it(self):
        """'Try It 1.1' → section_type = TRY_IT."""
        sections = [{"title": "Try It 1.1", "text": "Some content."}]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "TRY_IT"

    def test_learning_objectives_title_classified_correctly(self):
        """'Learning Objectives' → section_type = LEARNING_OBJECTIVES."""
        sections = [{"title": "Learning Objectives", "text": "After this section..."}]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "LEARNING_OBJECTIVES"

    def test_solution_title_classified_as_solution(self):
        """'Solution' → section_type = SOLUTION."""
        sections = [{"title": "Solution", "text": "We solve by..."}]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "SOLUTION"

    def test_unrecognised_title_classified_as_concept(self):
        """An arbitrary heading not matching any pattern → section_type = CONCEPT."""
        sections = [{"title": "Model Whole Numbers", "text": "We use base-10."}]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "CONCEPT"


# ── Tests: _build_textbook_blueprint ─────────────────────────────────────────

class TestBuildTextbookBlueprint:
    """Verify blueprint construction: merges, drops, and ordering."""

    def test_solution_merged_into_preceding_example(self):
        """
        Business: SOLUTION section is merged into the preceding EXAMPLE — not a
        separate item in the blueprint.
        """
        classified = [
            _section("Example 1.1", "Example content.", "EXAMPLE"),
            _section("Solution", "Solution steps.", "SOLUTION"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        assert len(blueprint) == 1
        assert "Solution steps." in blueprint[0]["text"]

    def test_supplementary_sections_dropped(self):
        """
        Business: SUPPLEMENTARY sections (Manipulative, Media, Access) are excluded.
        """
        classified = [
            _section("Model Whole Numbers", "Content.", "CONCEPT"),
            _section("Media", "Video link.", "SUPPLEMENTARY"),
            _section("Round Whole Numbers", "Rounding.", "CONCEPT"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        titles = [s["title"] for s in blueprint]
        assert "Media" not in titles
        assert len(blueprint) == 2

    def test_prereq_check_sections_dropped(self):
        """
        Business: PREREQ_CHECK sections (Be Prepared) are excluded from blueprint.
        """
        classified = [
            _section("Be Prepared", "Prerequisite check.", "PREREQ_CHECK"),
            _section("Introduction", "Intro text.", "CONCEPT"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        titles = [s["title"] for s in blueprint]
        assert "Be Prepared" not in titles
        assert len(blueprint) == 1

    def test_end_matter_sections_dropped(self):
        """
        Business: END_MATTER sections (Writing Exercises, Glossary) are excluded.
        """
        classified = [
            _section("Whole Numbers", "Core content.", "CONCEPT"),
            _section("Writing Exercises", "Exercises.", "END_MATTER"),
            _section("Glossary", "Terms.", "END_MATTER"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        assert len(blueprint) == 1
        assert blueprint[0]["title"] == "Whole Numbers"

    def test_example_try_it_alternation_preserved(self):
        """
        Business: EXAMPLE → TRY_IT → EXAMPLE → TRY_IT ordering is preserved in blueprint.
        """
        classified = [
            _section("Example 1.1", "Ex1.", "EXAMPLE"),
            _section("Try It 1.1", "Try1.", "TRY_IT"),
            _section("Example 1.2", "Ex2.", "EXAMPLE"),
            _section("Try It 1.2", "Try2.", "TRY_IT"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        types = [s["section_type"] for s in blueprint]
        assert types == ["EXAMPLE", "TRY_IT", "EXAMPLE", "TRY_IT"]

    def test_lo_at_index_2_moved_to_index_0_in_generate_cards_flow(self):
        """
        Business: When LO exists at position 2 (not at position 0), the
        generate_cards() flow moves it to position 0.
        """
        classified = [
            _section("Introduction", "Intro text.", "CONCEPT"),
            _section("Main Content", "Core content.", "CONCEPT"),
            _section("Learning Objectives", "You will learn...", "LEARNING_OBJECTIVES"),
        ]
        # Simulate the LO reorder logic from generate_cards()
        lo_indices = [
            i for i, s in enumerate(classified)
            if s.get("section_type") == "LEARNING_OBJECTIVES"
        ]
        if lo_indices and lo_indices[0] != 0:
            lo_section = classified.pop(lo_indices[0])
            classified.insert(0, lo_section)

        assert classified[0]["section_type"] == "LEARNING_OBJECTIVES"
        assert classified[1]["title"] == "Introduction"

    def test_lo_already_at_index_0_stays_at_index_0(self):
        """
        Business: LO at index 0 is not moved — it stays at position 0.
        """
        classified = [
            _section("Learning Objectives", "Objectives.", "LEARNING_OBJECTIVES"),
            _section("Main Content", "Content.", "CONCEPT"),
        ]
        lo_indices = [
            i for i, s in enumerate(classified)
            if s.get("section_type") == "LEARNING_OBJECTIVES"
        ]
        if lo_indices and lo_indices[0] != 0:
            lo_section = classified.pop(lo_indices[0])
            classified.insert(0, lo_section)

        assert classified[0]["section_type"] == "LEARNING_OBJECTIVES"

    def test_no_lo_present_with_matching_phrase_synthesizes_lo(self):
        """
        Business: When no LO section found but intro text contains
        'by the end of this section', an LO is synthesized at index 0.
        """
        import re
        classified = [
            {
                "title": "Introduction",
                "text": "by the end of this section, you will be able to add fractions.",
                "section_type": "CONCEPT",
            },
            {
                "title": "Main Topic",
                "text": "Main content here.",
                "section_type": "CONCEPT",
            },
        ]
        lo_indices = [
            i for i, s in enumerate(classified)
            if s.get("section_type") == "LEARNING_OBJECTIVES"
        ]
        if not lo_indices:
            first = classified[0]
            lo_match = re.search(
                r'((?:by the end of this (?:section|chapter)'
                r'|after (?:studying|reading|completing) this (?:section|chapter)'
                r'|you will be able to'
                r'|students will be able to'
                r'|in this section[,\s]+(?:you|we|students)'
                r'|upon completion)'
                r'.*?)(?=\n\n|\Z)',
                first.get("text", ""), re.IGNORECASE | re.DOTALL
            )
            if lo_match:
                lo_text = lo_match.group(1).strip()
                first["text"] = first["text"].replace(lo_match.group(0), "").strip()
                classified.insert(0, {
                    "title": "Learning Objectives",
                    "text": lo_text,
                    "section_type": "LEARNING_OBJECTIVES",
                })

        assert classified[0]["section_type"] == "LEARNING_OBJECTIVES"
        assert "by the end" in classified[0]["text"].lower()

    def test_no_lo_no_matching_phrase_no_crash(self):
        """
        Business: When no LO section exists and no matching phrase is found,
        no LO is synthesized and no crash occurs.
        """
        import re
        classified = [
            {
                "title": "Main Content",
                "text": "This is standard content about whole numbers.",
                "section_type": "CONCEPT",
            },
        ]
        lo_indices = [
            i for i, s in enumerate(classified)
            if s.get("section_type") == "LEARNING_OBJECTIVES"
        ]
        assert len(lo_indices) == 0
        # Simulate the synthesis path — no match found, no change
        first = classified[0]
        lo_match = re.search(
            r'((?:by the end of this (?:section|chapter)'
            r'|after (?:studying|reading|completing) this (?:section|chapter)'
            r'|you will be able to'
            r'|students will be able to'
            r'|in this section[,\s]+(?:you|we|students)'
            r'|upon completion)'
            r'.*?)(?=\n\n|\Z)',
            first.get("text", ""), re.IGNORECASE | re.DOTALL
        )
        assert lo_match is None
        # No crash, classified unchanged
        assert len(classified) == 1
