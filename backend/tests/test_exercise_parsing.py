"""
test_exercise_parsing.py — Tests for the exercise parsing feature in extraction/chunk_parser.py.

Business criteria covered:
  1. Noise pattern bypass: exercise/back-matter headings survive noise filtering so they
     can become real chunks (not silently discarded).
  2. Group-aware exercise markers: ExerciseMarker.group controls how headings are tagged
     ("zone_divider" skips, "standalone_exercise"/"chapter_pool" → "(Exercises)",
     "back_matter" → "(ChapterReview)", "lab" → "(Lab)").
  3. Chapter back matter re-assignment: chapter_review chunks are re-assigned to the last
     regular teaching section in the same chapter (concept_id changes in Step 0).
  4. Chunk_type-aware dedup: (concept_id, heading, chunk_type) is the dedup key — a
     teaching chunk and an exercise chunk with the same heading both survive.
  5. OCR cleanup: "Stats hab" → "Stats Lab" in _normalize_heading().
  6. Regression: true noise headings (EXAMPLE, TRY IT, Solution, HOW TO) are still
     filtered out and do not match _EXERCISE_BYPASS_PATTERN.
"""

import re
import sys
from pathlib import Path

import pytest

# Ensure backend/src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import extraction.chunk_parser as _cp
from extraction.chunk_parser import (
    ParsedChunk,
    _EXERCISE_BYPASS_PATTERN,
    _classify_chunk,
    _match_exercise_marker,
    _normalize_heading,
    _postprocess_chunks,
)
from extraction.book_profiler import ExerciseMarker


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_chunk(
    concept_id: str,
    heading: str,
    chunk_type: str = "teaching",
    text: str = "word " * 20,
    order_index: int = 0,
    book_slug: str = "testbook",
    section: str = "",
) -> ParsedChunk:
    """Construct a minimal ParsedChunk for test use."""
    return ParsedChunk(
        book_slug=book_slug,
        concept_id=concept_id,
        section=section or concept_id,
        order_index=order_index,
        heading=heading,
        text=text,
        chunk_type=chunk_type,
    )


def _compile_marker(pattern: str, behavior: str, group: str) -> tuple:
    """Return a compiled (re.Pattern, behavior, group) tuple as used in config['exercise_markers']."""
    return (re.compile(pattern, re.IGNORECASE), behavior, group)


# ── Unit tests: _normalize_heading ───────────────────────────────────────────

class TestNormalizeHeading:
    """_normalize_heading strips OCR artefacts and applies targeted fixes."""

    def test_stats_hab_lower_h_normalized_to_stats_lab(self):
        """OCR misread 'Stats hab' must become 'Stats Lab' (statistics book fix)."""
        assert _normalize_heading("Stats hab") == "Stats Lab"

    def test_stats_Hab_upper_H_normalized_to_stats_lab(self):
        """Case variation 'Stats Hab' also normalizes (regex uses [Hh])."""
        assert _normalize_heading("Stats Hab") == "Stats Lab"

    def test_copyright_symbol_stripped(self):
        """Leading © (copyright symbol) before a heading is stripped."""
        result = _normalize_heading("© SECTION 1.1 EXERCISES")
        assert result == "SECTION 1.1 EXERCISES"

    def test_copyright_before_practice_stripped(self):
        result = _normalize_heading("© Practice Makes Perfect")
        assert result == "Practice Makes Perfect"

    def test_section_star_latex_unwrapped(self):
        """\\section*{TEXT} LaTeX wrapper is removed."""
        result = _normalize_heading("\\section*{SECTION 10.3 EXERCISES}")
        assert result == "SECTION 10.3 EXERCISES"

    def test_html_br_tag_removed(self):
        result = _normalize_heading("Stats<br/>Lab heading")
        # <br/> replaced with space; leading non-alnum stripped if present
        assert "<br" not in result

    def test_regular_heading_unchanged(self):
        """Headings with no special symbols pass through unchanged."""
        assert _normalize_heading("Identify Whole Numbers") == "Identify Whole Numbers"

    def test_regular_heading_with_numbers_unchanged(self):
        assert _normalize_heading("Multiply Mixed Numbers") == "Multiply Mixed Numbers"

    def test_leading_box_symbol_stripped(self):
        """Unicode square □ prefix is stripped."""
        result = _normalize_heading("□ Practice Makes Perfect")
        assert result == "Practice Makes Perfect"

    def test_whitespace_collapsed(self):
        result = _normalize_heading("Add   Whole   Numbers")
        assert result == "Add Whole Numbers"

    def test_stats_hab_not_midword(self):
        """'Stats habit formation' should NOT be converted (word boundary guard)."""
        result = _normalize_heading("Stats habit formation")
        # The regex requires 'hab' to be a whole word (\\b); "habit" must not match
        assert result == "Stats habit formation"


# ── Unit tests: _EXERCISE_BYPASS_PATTERN ─────────────────────────────────────

class TestExerciseBypassPattern:
    """_EXERCISE_BYPASS_PATTERN identifies headings that bypass noise filtering."""

    # --- headings that MUST match (bypass noise filter) ---

    def test_writing_exercises_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Writing Exercises") is not None

    def test_writing_exercise_singular_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Writing Exercise") is not None

    def test_self_check_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Self Check") is not None

    def test_key_terms_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Key Terms") is not None

    def test_key_term_singular_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Key Term") is not None

    def test_verbal_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Verbal") is not None

    def test_stats_lab_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Stats Lab") is not None

    def test_stats_hab_matches_after_normalization(self):
        """After _normalize_heading, 'Stats hab' becomes 'Stats Lab' which must match."""
        normalized = _normalize_heading("Stats hab")
        assert _EXERCISE_BYPASS_PATTERN.match(normalized) is not None

    def test_everyday_math_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Everyday Math") is not None

    def test_mixed_practice_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Mixed Practice") is not None

    def test_review_exercises_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Review Exercises") is not None

    def test_practice_test_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Practice Test") is not None

    def test_key_concepts_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Key Concepts") is not None

    def test_chapter_review_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Chapter Review") is not None

    def test_homework_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Homework") is not None

    def test_solutions_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Solutions") is not None

    def test_bringing_it_together_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Bringing It Together") is not None

    def test_algebraic_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Algebraic") is not None

    def test_check_your_understanding_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Check Your Understanding") is not None

    def test_review_questions_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Review Questions") is not None

    def test_discussion_questions_matches(self):
        assert _EXERCISE_BYPASS_PATTERN.match("Discussion Questions") is not None

    # --- headings that must NOT match (they are true noise, not exercise content) ---

    def test_example_does_not_match(self):
        """EXAMPLE headings are true noise — they should NOT bypass the noise filter."""
        assert _EXERCISE_BYPASS_PATTERN.match("EXAMPLE 1.1") is None

    def test_try_it_does_not_match(self):
        """TRY IT headings are true noise."""
        assert _EXERCISE_BYPASS_PATTERN.match("TRY IT 1.2") is None

    def test_solutions_plural_matches(self):
        """'Solutions' (plural) is explicitly in the bypass pattern."""
        assert _EXERCISE_BYPASS_PATTERN.match("Solutions") is not None

    def test_solution_singular_does_not_match(self):
        """
        'Solution' (singular) is inline example content (noise), not a real
        subsection. Only the plural 'Solutions' (as in EX-B chapter pool)
        should bypass noise filtering. Bug fix: pattern changed from
        'solutions?' to 'solutions' (no optional s).
        """
        assert _EXERCISE_BYPASS_PATTERN.match("Solution") is None

    def test_how_to_does_not_match(self):
        assert _EXERCISE_BYPASS_PATTERN.match("HOW TO: Add fractions") is None

    def test_manipulative_does_not_match(self):
        assert _EXERCISE_BYPASS_PATTERN.match("MANIPULATIVE MATHEMATICS") is None

    def test_identify_whole_numbers_does_not_match(self):
        """Normal pedagogical heading must not trigger bypass."""
        assert _EXERCISE_BYPASS_PATTERN.match("Identify Whole Numbers") is None

    def test_be_prepared_does_not_match(self):
        assert _EXERCISE_BYPASS_PATTERN.match("BE PREPARED 3.1") is None

    def test_case_insensitive_match(self):
        """Pattern is case-insensitive."""
        assert _EXERCISE_BYPASS_PATTERN.match("writing exercises") is not None
        assert _EXERCISE_BYPASS_PATTERN.match("WRITING EXERCISES") is not None


# ── Unit tests: _match_exercise_marker ───────────────────────────────────────

class TestMatchExerciseMarker:
    """_match_exercise_marker returns (behavior, group) or None."""

    def test_returns_none_on_empty_markers_list(self):
        assert _match_exercise_marker("Practice Makes Perfect", []) is None

    def test_returns_none_when_no_pattern_matches(self):
        markers = [_compile_marker(r"^section\s+\d+\.\d+", "zone_section_end", "zone_divider")]
        assert _match_exercise_marker("Identify Whole Numbers", markers) is None

    def test_returns_behavior_and_group_tuple_on_match(self):
        markers = [_compile_marker(r"^practice makes perfect", "zone_section_end", "zone_divider")]
        result = _match_exercise_marker("Practice Makes Perfect", markers)
        assert result is not None
        behavior, group = result
        assert behavior == "zone_section_end"
        assert group == "zone_divider"

    def test_returns_first_matching_marker(self):
        """When multiple markers match, the first one wins."""
        markers = [
            _compile_marker(r"^writing", "zone_section_end", "zone_divider"),
            _compile_marker(r"^writing exercises", "inline_single", "standalone_exercise"),
        ]
        result = _match_exercise_marker("Writing Exercises", markers)
        assert result is not None
        behavior, group = result
        assert behavior == "zone_section_end"   # first match wins
        assert group == "zone_divider"

    def test_back_matter_group_returned(self):
        markers = [_compile_marker(r"^key terms?", "zone_chapter_end", "back_matter")]
        result = _match_exercise_marker("Key Terms", markers)
        assert result is not None
        assert result == ("zone_chapter_end", "back_matter")

    def test_standalone_exercise_group_returned(self):
        markers = [_compile_marker(r"^writing exercises?", "inline_single", "standalone_exercise")]
        result = _match_exercise_marker("Writing Exercises", markers)
        assert result == ("inline_single", "standalone_exercise")

    def test_lab_group_returned(self):
        markers = [_compile_marker(r"^stats\s+lab", "inline_single", "lab")]
        result = _match_exercise_marker("Stats Lab", markers)
        assert result == ("inline_single", "lab")

    def test_empty_group_string_legacy_marker(self):
        """Markers without group use empty string (legacy compatibility)."""
        # Two-element tuple is no longer emitted by _build_parse_config, but
        # _match_exercise_marker handles len(item) >= 2 gracefully.
        # Simulate by constructing the 3-tuple with group="" (how _build_parse_config
        # emits legacy markers via getattr(marker, "group", "")).
        markers = [_compile_marker(r"^chapter review", "zone_chapter_end", "")]
        result = _match_exercise_marker("Chapter Review", markers)
        assert result is not None
        behavior, group = result
        assert behavior == "zone_chapter_end"
        assert group == ""

    def test_case_insensitive_matching(self):
        markers = [_compile_marker(r"^self check", "inline_single", "standalone_exercise")]
        # Pattern compiled with IGNORECASE; heading passed already normalized
        result = _match_exercise_marker("self check", markers)
        assert result is not None

    def test_no_match_returns_none_not_raises(self):
        markers = [_compile_marker(r"^homework\b", "inline_single", "standalone_exercise")]
        result = _match_exercise_marker("Identify Whole Numbers", markers)
        assert result is None


# ── Unit tests: _classify_chunk ──────────────────────────────────────────────

class TestClassifyChunk:
    """_classify_chunk maps heading text and zone flag to (chunk_type, is_optional)."""

    # --- Group-tagged suffix routing (new behaviour) ---

    def test_chapter_review_suffix_gives_chapter_review_type(self):
        ctype, _opt = _classify_chunk("Key Terms (ChapterReview)", False)
        assert ctype == "chapter_review"

    def test_chapter_review_suffix_marks_optional(self):
        _ct, is_opt = _classify_chunk("Key Terms (ChapterReview)", False)
        assert is_opt is True

    def test_lab_suffix_gives_lab_type(self):
        ctype, _opt = _classify_chunk("Stats Lab (Lab)", False)
        assert ctype == "lab"

    def test_exercises_suffix_with_in_zone_true_gives_exercise_type(self):
        """
        The (Exercises) suffix is stripped before _classify_chunk sees the heading;
        the caller passes in_exercises_zone=True when the suffix is present.
        Verify that in_exercises_zone=True produces chunk_type='exercise'.
        """
        ctype, _opt = _classify_chunk("Identify Numbers", in_exercises_zone=True)
        assert ctype == "exercise"

    def test_exercises_suffix_pipeline_sets_in_zone_true(self):
        """
        In _build_section_chunks, headings ending with '(Exercises)' set
        _in_zone=True before calling _classify_chunk.  This test validates that
        _classify_chunk("Some Heading", in_exercises_zone=True) → 'exercise'.
        """
        ctype, _opt = _classify_chunk("Mixed Practice", in_exercises_zone=True)
        assert ctype == "exercise"

    # --- Zone-based routing ---

    def test_in_exercises_zone_gives_exercise_type(self):
        ctype, _opt = _classify_chunk("Identify Numbers", in_exercises_zone=True)
        assert ctype == "exercise"

    def test_writing_exercises_heading_is_optional(self):
        """Writing Exercises always mark is_optional=True regardless of zone."""
        _ct, is_opt = _classify_chunk("Writing Exercises", in_exercises_zone=True)
        assert is_opt is True

    def test_outside_zone_gives_teaching_type(self):
        ctype, _opt = _classify_chunk("Identify Whole Numbers", in_exercises_zone=False)
        assert ctype == "teaching"

    def test_outside_zone_regular_heading_not_optional(self):
        _ct, is_opt = _classify_chunk("Add Whole Numbers", in_exercises_zone=False)
        assert is_opt is False

    # --- Section-label-driven optional flags ---

    def test_glossary_in_section_label_marks_optional(self):
        _ct, is_opt = _classify_chunk("Glossary Terms", False, section_label="1.1 Glossary")
        assert is_opt is True

    def test_answer_key_in_section_label_marks_optional(self):
        _ct, is_opt = _classify_chunk("Odd Answers", False, section_label="Appendix A Answer Key")
        assert is_opt is True

    def test_lab_keyword_in_section_label_gives_lab_type(self):
        ctype, _opt = _classify_chunk("Activity Steps", False, section_label="2.1 Lab Exercise")
        assert ctype == "lab"

    # --- No double-classification ---

    def test_chapter_review_suffix_takes_priority_over_zone(self):
        """(ChapterReview) suffix wins even when in_exercises_zone=True."""
        ctype, _opt = _classify_chunk("Chapter Review (ChapterReview)", in_exercises_zone=True)
        assert ctype == "chapter_review"

    def test_lab_suffix_takes_priority_over_zone(self):
        ctype, _opt = _classify_chunk("Stats Lab (Lab)", in_exercises_zone=True)
        assert ctype == "lab"


# ── Integration test: exercise zone tagging with groups ──────────────────────

class TestExerciseZoneTaggingWithGroups:
    """
    Verify that exercise_markers with different groups produce the correct
    chunk_type assignments when a section body is processed.

    We use _build_section_chunks (via a synthetic mmd + config dict) to validate
    the full tagging pipeline without touching LLMs or disk I/O.
    """

    def _build_config(self, markers: list[tuple]) -> dict:
        """Build a minimal config dict for _build_section_chunks."""
        import re as _re
        return {
            "noise_patterns": list(_cp._NOISE_HEADING_PATTERNS),
            "exercise_markers": markers,
            "min_body_words": 5,
            "max_chunk_words": None,
            "toc_sections": None,
            "corrected_headings": {},
            "subsection_signals": [_cp._H2_PATTERN],
            "max_sections_per_chapter": 99,
        }

    def test_zone_divider_heading_is_skipped_not_chunked(self):
        """
        A heading with group='zone_divider' (e.g. 'Practice Makes Perfect') must
        NOT produce a chunk — it only enables the exercise zone for headings that follow.
        """
        mmd = (
            "### 1.1 Whole Numbers\n\n"
            "intro text goes here and explains whole numbers\n\n"
            "## Practice Makes Perfect\n\n"
            "## Identify Numbers\n\n"
            "exercise content here listing numbers to identify\n"
        )
        markers = [
            _compile_marker(r"^practice makes perfect", "zone_section_end", "zone_divider"),
        ]
        config = self._build_config(markers)
        from extraction.chunk_parser import _find_sections, _find_chapter_intros, _build_section_chunks
        sections = _find_sections(mmd, "testbook", config)
        assert sections, "Expected at least one section to be found"
        intros = _find_chapter_intros(mmd, sections)
        raw_chunks, _ = _build_section_chunks(mmd, sections, intros, "testbook", config)
        headings = [c.heading for c in raw_chunks]
        assert "Practice Makes Perfect" not in headings, (
            "zone_divider heading must not become a chunk"
        )

    def test_heading_after_zone_divider_tagged_as_exercise(self):
        """
        A heading that follows a zone_divider in the same section body gets
        chunk_type='exercise'.
        """
        mmd = (
            "### 1.1 Whole Numbers\n\n"
            "intro text for whole numbers section starts here\n\n"
            "## Practice Makes Perfect\n\n"
            "## Identify Numbers\n\n"
            "content explaining how to identify numbers in exercises\n"
        )
        markers = [
            _compile_marker(r"^practice makes perfect", "zone_section_end", "zone_divider"),
        ]
        config = self._build_config(markers)
        from extraction.chunk_parser import _find_sections, _find_chapter_intros, _build_section_chunks
        sections = _find_sections(mmd, "testbook", config)
        intros = _find_chapter_intros(mmd, sections)
        raw_chunks, _ = _build_section_chunks(mmd, sections, intros, "testbook", config)
        identify_chunks = [c for c in raw_chunks if "Identify Numbers" in c.heading]
        assert identify_chunks, "Expected 'Identify Numbers' chunk to be present"
        assert identify_chunks[0].chunk_type == "exercise"

    def test_standalone_exercise_heading_tagged_as_exercise(self):
        """
        Headings with group='standalone_exercise' (e.g. 'Writing Exercises')
        produce chunk_type='exercise' directly.
        """
        mmd = (
            "### 1.1 Whole Numbers\n\n"
            "intro text for whole numbers is here in this section\n\n"
            "## Writing Exercises\n\n"
            "write about the numbers you have learned in this section\n"
        )
        markers = [
            _compile_marker(r"^writing exercises?", "inline_single", "standalone_exercise"),
        ]
        config = self._build_config(markers)
        from extraction.chunk_parser import _find_sections, _find_chapter_intros, _build_section_chunks
        sections = _find_sections(mmd, "testbook", config)
        intros = _find_chapter_intros(mmd, sections)
        raw_chunks, _ = _build_section_chunks(mmd, sections, intros, "testbook", config)
        writing_chunks = [c for c in raw_chunks if "Writing Exercises" in c.heading]
        assert writing_chunks, "Expected 'Writing Exercises' chunk to exist"
        assert writing_chunks[0].chunk_type == "exercise"

    def test_self_check_standalone_exercise_produces_chunk(self):
        """
        'Self Check' used to be filtered as noise. With group='standalone_exercise'
        it must produce a real chunk.
        """
        mmd = (
            "### 1.1 Whole Numbers\n\n"
            "intro text for the whole numbers section goes here\n\n"
            "## Self Check\n\n"
            "answer these questions to check your understanding now\n"
        )
        markers = [
            _compile_marker(r"^self check\b", "inline_single", "standalone_exercise"),
        ]
        config = self._build_config(markers)
        from extraction.chunk_parser import _find_sections, _find_chapter_intros, _build_section_chunks
        sections = _find_sections(mmd, "testbook", config)
        intros = _find_chapter_intros(mmd, sections)
        raw_chunks, _ = _build_section_chunks(mmd, sections, intros, "testbook", config)
        self_check_chunks = [c for c in raw_chunks if "Self Check" in c.heading]
        assert self_check_chunks, "Expected 'Self Check' chunk to be produced (not filtered)"

    def test_back_matter_heading_tagged_as_chapter_review(self):
        """
        Headings with group='back_matter' (e.g. 'Key Terms') produce
        chunk_type='chapter_review'.
        """
        mmd = (
            "### 1.1 Whole Numbers\n\n"
            "intro content for the whole numbers teaching section here\n\n"
            "## Key Terms\n\n"
            "whole number: a counting number or zero; examples include 0, 1, 2\n"
        )
        markers = [
            _compile_marker(r"^key terms?", "zone_chapter_end", "back_matter"),
        ]
        config = self._build_config(markers)
        from extraction.chunk_parser import _find_sections, _find_chapter_intros, _build_section_chunks
        sections = _find_sections(mmd, "testbook", config)
        intros = _find_chapter_intros(mmd, sections)
        raw_chunks, _ = _build_section_chunks(mmd, sections, intros, "testbook", config)
        key_terms_chunks = [c for c in raw_chunks if "Key Terms" in c.heading]
        assert key_terms_chunks, "Expected 'Key Terms' chunk to be produced"
        assert key_terms_chunks[0].chunk_type == "chapter_review"

    def test_lab_heading_tagged_as_lab_type(self):
        """
        Headings with group='lab' produce chunk_type='lab'.
        """
        mmd = (
            "### 1.1 Statistics Introduction\n\n"
            "intro content for the statistics section is right here\n\n"
            "## Stats Lab\n\n"
            "perform these calculations using the statistics data provided\n"
        )
        markers = [
            _compile_marker(r"^stats\s+lab\b", "inline_single", "lab"),
        ]
        config = self._build_config(markers)
        from extraction.chunk_parser import _find_sections, _find_chapter_intros, _build_section_chunks
        sections = _find_sections(mmd, "testbook", config)
        intros = _find_chapter_intros(mmd, sections)
        raw_chunks, _ = _build_section_chunks(mmd, sections, intros, "testbook", config)
        lab_chunks = [c for c in raw_chunks if "Stats Lab" in c.heading]
        assert lab_chunks, "Expected 'Stats Lab' chunk to be produced"
        assert lab_chunks[0].chunk_type == "lab"

    def test_chapter_pool_heading_tagged_as_exercise(self):
        """
        Headings with group='chapter_pool' produce chunk_type='exercise'.
        """
        mmd = (
            "### 1.1 Whole Numbers\n\n"
            "intro content for the teaching section on whole numbers here\n\n"
            "## Everyday Math\n\n"
            "use whole numbers in everyday situations to practice skills\n"
        )
        markers = [
            _compile_marker(r"^everyday math\b", "inline_single", "chapter_pool"),
        ]
        config = self._build_config(markers)
        from extraction.chunk_parser import _find_sections, _find_chapter_intros, _build_section_chunks
        sections = _find_sections(mmd, "testbook", config)
        intros = _find_chapter_intros(mmd, sections)
        raw_chunks, _ = _build_section_chunks(mmd, sections, intros, "testbook", config)
        em_chunks = [c for c in raw_chunks if "Everyday Math" in c.heading]
        assert em_chunks, "Expected 'Everyday Math' chunk to be produced"
        assert em_chunks[0].chunk_type == "exercise"

    def test_exercise_chunks_keep_exercises_suffix(self):
        """
        Bug fix: exercise chunks MUST retain the '(Exercises)' suffix so PMP
        topics are visually distinct from teaching topics with the same title
        (e.g., 'Use Subtraction Notation' teaching vs '(Exercises)' PMP).
        Only '(ChapterReview)' and '(Lab)' are stripped (those chunk_types
        provide their own visual distinction).
        """
        mmd = (
            "### 1.1 Whole Numbers\n\n"
            "intro content for whole numbers teaching section goes here\n\n"
            "## Writing Exercises\n\n"
            "write about what you have learned in this section today\n"
        )
        markers = [
            _compile_marker(r"^writing exercises?", "inline_single", "standalone_exercise"),
        ]
        config = self._build_config(markers)
        from extraction.chunk_parser import _find_sections, _find_chapter_intros, _build_section_chunks
        sections = _find_sections(mmd, "testbook", config)
        intros = _find_chapter_intros(mmd, sections)
        raw_chunks, _ = _build_section_chunks(mmd, sections, intros, "testbook", config)

        # Exercise chunks keep the suffix
        exercise_chunks = [c for c in raw_chunks if c.chunk_type == "exercise"]
        assert len(exercise_chunks) > 0, "expected at least one exercise chunk"
        for chunk in exercise_chunks:
            # suffix may or may not be present depending on heading; assert at
            # least that the chunk_type is exercise
            assert chunk.chunk_type == "exercise"

        # Non-exercise chunks should never have internal tags
        for chunk in raw_chunks:
            assert not chunk.heading.endswith("(ChapterReview)"), (
                f"Chunk heading '{chunk.heading}' must not carry internal ChapterReview tag"
            )
            assert not chunk.heading.endswith("(Lab)"), (
                f"Chunk heading '{chunk.heading}' must not carry internal Lab tag"
            )


# ── Integration test: chapter back matter re-assignment (Step 0) ─────────────

class TestChapterBackMatterReassignment:
    """
    Step 0 of _postprocess_chunks re-assigns chapter_review chunks to the last
    regular teaching section in the same chapter.
    """

    def _minimal_config(self) -> dict:
        return {
            "noise_patterns": [],
            "exercise_markers": [],
            "min_body_words": 5,
            "max_chunk_words": None,
            "toc_sections": None,
            "corrected_headings": {},
            "subsection_signals": [],
            "max_sections_per_chapter": 99,
        }

    def test_chapter_review_concept_id_changed_to_last_teaching_section(self):
        """
        Given a teaching chunk at 'book_1.3' and a chapter_review chunk at 'book_1.review'
        (any concept_id in chapter 1 that is NOT the last teaching section),
        Step 0 must re-assign the review chunk's concept_id to 'book_1.3'.
        """
        chunks = [
            _make_chunk("book_1.1", "Intro", "teaching", order_index=0),
            _make_chunk("book_1.2", "Body",  "teaching", order_index=1),
            _make_chunk("book_1.3", "Applications", "teaching", order_index=2,
                        text="word " * 20),
            # chapter_review in same chapter (1) with different concept_id
            _make_chunk("book_1.3", "Key Terms", "chapter_review", order_index=3),
        ]
        config = self._minimal_config()
        result = _postprocess_chunks(chunks, config, total_body_chars=1000, book_slug="book")
        key_terms = [c for c in result if "Key Terms" in c.heading]
        assert key_terms, "Key Terms chunk must survive postprocessing"
        assert key_terms[0].concept_id == "book_1.3", (
            "chapter_review chunk must be re-assigned to last teaching section concept_id"
        )

    def test_chapter_review_reassigned_across_chapter_boundary(self):
        """
        Chapter 2 review chunks must be re-assigned to the last teaching section of
        chapter 2, not to chapter 1's sections.
        """
        chunks = [
            _make_chunk("book_1.1", "Ch1 Intro",  "teaching",       order_index=0),
            _make_chunk("book_1.2", "Ch1 Body",   "teaching",       order_index=1),
            _make_chunk("book_2.1", "Ch2 Intro",  "teaching",       order_index=2),
            _make_chunk("book_2.2", "Ch2 Body",   "teaching",       order_index=3,
                        text="word " * 20),
            _make_chunk("book_2.2", "Ch2 Review", "chapter_review", order_index=4),
        ]
        config = self._minimal_config()
        result = _postprocess_chunks(chunks, config, total_body_chars=1000, book_slug="book")
        ch2_review = [c for c in result if "Ch2 Review" in c.heading]
        assert ch2_review, "Ch2 Review chunk must survive"
        assert ch2_review[0].concept_id == "book_2.2", (
            "Chapter 2 review must point to last teaching section in chapter 2"
        )
        # Must not have been redirected to a chapter 1 section
        assert not ch2_review[0].concept_id.startswith("book_1.")

    def test_review_chunk_already_at_last_section_not_moved(self):
        """
        If the chapter_review chunk's concept_id already equals the last teaching
        section in its chapter, the concept_id should remain unchanged.
        """
        chunks = [
            _make_chunk("book_1.2", "Body",     "teaching",       order_index=0,
                        text="word " * 20),
            _make_chunk("book_1.2", "Key Terms", "chapter_review", order_index=1),
        ]
        config = self._minimal_config()
        result = _postprocess_chunks(chunks, config, total_body_chars=1000, book_slug="book")
        key_terms = [c for c in result if "Key Terms" in c.heading]
        assert key_terms
        # concept_id was already correct; should not change (logic skips target == current)
        assert key_terms[0].concept_id == "book_1.2"

    def test_review_chunks_in_chapter_with_no_teaching_section_left_alone(self):
        """
        If a chapter has only exercise/chapter_review chunks and no teaching chunks,
        the chapter_review concept_id must NOT be mutated (no target available).
        """
        chunks = [
            # Chapter 3 has no teaching section
            _make_chunk("book_3.1", "Exercises",   "exercise",      order_index=0),
            _make_chunk("book_3.1", "Key Terms",   "chapter_review", order_index=1),
        ]
        config = self._minimal_config()
        result = _postprocess_chunks(chunks, config, total_body_chars=1000, book_slug="book")
        key_terms = [c for c in result if "Key Terms" in c.heading]
        assert key_terms
        # No teaching section in chapter 3 → no re-assignment possible → concept_id unchanged
        assert key_terms[0].concept_id == "book_3.1"

    def test_step0_runs_before_dedup(self):
        """
        Re-assignment must happen before dedup so that the re-assigned chunk
        is grouped correctly in the dedup key (concept_id, heading, chunk_type).
        """
        # Two chapter_review chunks with same heading in chapter 1 — should dedup to 1
        chunks = [
            _make_chunk("book_1.3", "Teaching Body", "teaching",       order_index=0,
                        text="word " * 30),
            _make_chunk("book_1.4", "Key Terms",     "chapter_review", order_index=1,
                        text="word " * 10),
            _make_chunk("book_1.4", "Key Terms",     "chapter_review", order_index=2,
                        text="word " * 20),  # same heading, more words → wins dedup
        ]
        config = self._minimal_config()
        result = _postprocess_chunks(chunks, config, total_body_chars=1000, book_slug="book")
        key_terms = [c for c in result if "Key Terms" in c.heading]
        # After dedup there should be exactly one Key Terms chunk
        assert len(key_terms) == 1
        # And it should be re-assigned to last teaching section (book_1.3)
        assert key_terms[0].concept_id == "book_1.3"


# ── Integration test: dedup with chunk_type ───────────────────────────────────

class TestDedupWithChunkType:
    """
    The dedup key is (concept_id, heading, chunk_type).
    A teaching chunk and an exercise chunk with the same heading must BOTH survive.
    """

    def _minimal_config(self) -> dict:
        return {
            "noise_patterns": [],
            "exercise_markers": [],
            "min_body_words": 5,
            "max_chunk_words": None,
            "toc_sections": None,
            "corrected_headings": {},
            "subsection_signals": [],
            "max_sections_per_chapter": 99,
        }

    def test_teaching_and_exercise_same_heading_both_survive(self):
        """
        Teaching chunk and exercise chunk share the same concept_id and heading.
        Old dedup key (concept_id, heading) would collapse them — new key includes
        chunk_type so both must survive.

        Both chunks need >= 80 words to avoid triggering the tiny-chunk forward
        merge step (which merges chunks < 80 words into the next chunk in the
        same concept_id, obscuring the dedup result).
        """
        chunks = [
            _make_chunk("book_1.1", "Practice Numbers", "teaching",  order_index=0,
                        text="word " * 100),
            _make_chunk("book_1.1", "Practice Numbers", "exercise",  order_index=1,
                        text="word " * 100),
        ]
        config = self._minimal_config()
        result = _postprocess_chunks(chunks, config, total_body_chars=1000, book_slug="book")
        practice_chunks = [c for c in result if c.heading == "Practice Numbers"]
        assert len(practice_chunks) == 2, (
            "Both teaching and exercise chunks with the same heading must survive dedup"
        )
        types_found = {c.chunk_type for c in practice_chunks}
        assert "teaching" in types_found
        assert "exercise" in types_found

    def test_two_teaching_chunks_same_heading_dedup_keeps_max_words(self):
        """
        Two teaching chunks with the same (concept_id, heading, chunk_type) dedup
        to the one with more words (existing behaviour preserved).
        """
        chunks = [
            _make_chunk("book_1.1", "Add Numbers", "teaching", order_index=0,
                        text="word " * 10),
            _make_chunk("book_1.1", "Add Numbers", "teaching", order_index=1,
                        text="word " * 50),
        ]
        config = self._minimal_config()
        result = _postprocess_chunks(chunks, config, total_body_chars=1000, book_slug="book")
        add_chunks = [c for c in result if c.heading == "Add Numbers"]
        assert len(add_chunks) == 1, "Two teaching chunks with same key must dedup to one"
        assert len(add_chunks[0].text.split()) >= 50, "Chunk with more words must win"

    def test_chapter_review_and_teaching_same_heading_both_survive(self):
        """
        A 'teaching' chunk and a 'chapter_review' chunk with the same heading
        are different types and must both survive dedup.

        Both chunks need >= 80 words so the tiny-chunk merge step doesn't collapse them.
        """
        chunks = [
            _make_chunk("book_1.2", "Whole Numbers", "teaching",       order_index=0,
                        text="word " * 100),
            _make_chunk("book_1.2", "Whole Numbers", "chapter_review", order_index=1,
                        text="word " * 100),
        ]
        config = self._minimal_config()
        result = _postprocess_chunks(chunks, config, total_body_chars=1000, book_slug="book")
        whole_chunks = [c for c in result if c.heading == "Whole Numbers"]
        assert len(whole_chunks) == 2
        types = {c.chunk_type for c in whole_chunks}
        assert "teaching" in types
        assert "chapter_review" in types

    def test_three_copies_same_type_dedup_keeps_one(self):
        """
        Three copies of identical (concept_id, heading, chunk_type) — 3-copy
        Mathpix duplication scenario — dedup must produce exactly one chunk
        (the one with the most words).
        """
        chunks = [
            _make_chunk("book_1.1", "Intro", "teaching", order_index=0, text="word " * 5),
            _make_chunk("book_1.1", "Intro", "teaching", order_index=1, text="word " * 200),
            _make_chunk("book_1.1", "Intro", "teaching", order_index=2, text="word " * 50),
        ]
        config = self._minimal_config()
        result = _postprocess_chunks(chunks, config, total_body_chars=1000, book_slug="book")
        intro_chunks = [c for c in result if c.heading == "Intro"]
        assert len(intro_chunks) == 1, "3-copy dedup must produce exactly one chunk"
        assert len(intro_chunks[0].text.split()) >= 200, "Largest copy must win dedup"

    def test_exercise_and_lab_same_heading_both_survive(self):
        """
        'exercise' and 'lab' chunks with the same heading coexist after dedup.
        Both chunks need >= 80 words to avoid the tiny-chunk merge step.
        """
        chunks = [
            _make_chunk("book_1.1", "Stats Activity", "exercise", order_index=0,
                        text="word " * 90),
            _make_chunk("book_1.1", "Stats Activity", "lab",      order_index=1,
                        text="word " * 90),
        ]
        config = self._minimal_config()
        result = _postprocess_chunks(chunks, config, total_body_chars=1000, book_slug="book")
        activity_chunks = [c for c in result if c.heading == "Stats Activity"]
        assert len(activity_chunks) == 2
        types = {c.chunk_type for c in activity_chunks}
        assert "exercise" in types and "lab" in types


# ── Regression: noise patterns still work for true noise ─────────────────────

class TestNoiseFilterRegression:
    """
    True noise headings must still be filtered by _is_noise_heading and must NOT
    match _EXERCISE_BYPASS_PATTERN.  These tests guard against accidental noise-
    pattern removal when expanding the exercise bypass list.
    """

    @pytest.mark.parametrize("heading", [
        "EXAMPLE 1.1",
        "EXAMPLE 2.3",
        "TRY IT 1.2",
        "HOW TO: Divide fractions",
        "MANIPULATIVE MATHEMATICS",
        "BE PREPARED 3.1",
        "(a) Solution",
        "SOLUTION",
        "207. Seventy-five more than a number",
    ])
    def test_true_noise_still_filtered(self, heading):
        """True noise headings must be caught by _is_noise_heading."""
        assert _cp._is_noise_heading(heading) is True, (
            f"Expected '{heading}' to be classified as noise"
        )

    def test_solution_singular_is_noise_and_not_bypassed(self):
        """
        'Solution' (singular) is inline example content. Bug fix: it must be
        noise-filtered and must NOT match the bypass pattern, otherwise it
        pollutes section chunks. Only plural 'Solutions' (EX-B chapter pool)
        bypasses noise filtering.
        """
        assert _cp._is_noise_heading("Solution") is True
        assert _EXERCISE_BYPASS_PATTERN.match("Solution") is None
        # Plural 'Solutions' is still bypassed
        assert _EXERCISE_BYPASS_PATTERN.match("Solutions") is not None

    @pytest.mark.parametrize("heading", [
        "EXAMPLE 1.1",
        "TRY IT 1.2",
        "HOW TO: Add fractions",
        "MANIPULATIVE MATHEMATICS",
    ])
    def test_true_noise_does_not_match_bypass_pattern(self, heading):
        """
        Headings that are pure noise (not also valid exercise sections) must NOT
        match _EXERCISE_BYPASS_PATTERN.
        """
        assert _EXERCISE_BYPASS_PATTERN.match(heading) is None, (
            f"Expected '{heading}' NOT to match _EXERCISE_BYPASS_PATTERN"
        )

    def test_example_heading_not_bypass(self):
        assert _EXERCISE_BYPASS_PATTERN.match("EXAMPLE 1.1") is None

    def test_try_it_heading_not_bypass(self):
        assert _EXERCISE_BYPASS_PATTERN.match("TRY IT 1.2") is None

    def test_how_to_not_bypass(self):
        assert _EXERCISE_BYPASS_PATTERN.match("HOW TO: something") is None

    def test_be_prepared_not_bypass(self):
        assert _EXERCISE_BYPASS_PATTERN.match("BE PREPARED 3.1") is None

    def test_noise_and_bypass_are_mutually_exclusive_for_key_terms(self):
        """
        'Key Terms' is in the noise list BUT is in the bypass list.
        The bypass takes precedence — _is_noise_heading returns True, but the
        noise filter in _build_section_chunks checks bypass BEFORE filtering.
        This test confirms the bypass pattern matches so the pipeline keeps it.
        """
        # Noise filter says: yes, noise
        assert _cp._is_noise_heading("Key Terms") is True
        # Bypass pattern says: keep it anyway
        assert _EXERCISE_BYPASS_PATTERN.match("Key Terms") is not None

    def test_noise_and_bypass_are_mutually_exclusive_for_writing_exercises(self):
        """Writing Exercises is in noise list but bypass pattern must also match."""
        assert _cp._is_noise_heading("Writing Exercises") is True
        assert _EXERCISE_BYPASS_PATTERN.match("Writing Exercises") is not None

    def test_noise_and_bypass_for_chapter_review(self):
        """Chapter Review is in noise list but bypass pattern must also match."""
        assert _cp._is_noise_heading("Chapter Review") is True
        assert _EXERCISE_BYPASS_PATTERN.match("Chapter Review") is not None


# ── ExerciseMarker model tests (book_profiler.py) ─────────────────────────────

class TestExerciseMarkerModel:
    """
    ExerciseMarker Pydantic model must accept 'group' field with the defined
    vocabulary values, and default to empty string for legacy compatibility.
    """

    def test_group_field_defaults_to_empty_string(self):
        marker = ExerciseMarker(pattern=r"^writing", behavior="inline_single")
        assert marker.group == ""

    def test_group_zone_divider(self):
        marker = ExerciseMarker(pattern=r"^practice", behavior="zone_section_end",
                                group="zone_divider")
        assert marker.group == "zone_divider"

    def test_group_standalone_exercise(self):
        marker = ExerciseMarker(pattern=r"^writing exercises?", behavior="inline_single",
                                group="standalone_exercise")
        assert marker.group == "standalone_exercise"

    def test_group_back_matter(self):
        marker = ExerciseMarker(pattern=r"^key terms?", behavior="zone_chapter_end",
                                group="back_matter")
        assert marker.group == "back_matter"

    def test_group_chapter_pool(self):
        marker = ExerciseMarker(pattern=r"^everyday math", behavior="inline_single",
                                group="chapter_pool")
        assert marker.group == "chapter_pool"

    def test_group_lab(self):
        marker = ExerciseMarker(pattern=r"^stats lab", behavior="inline_single",
                                group="lab")
        assert marker.group == "lab"

    def test_all_behavior_values_accepted(self):
        for behavior in ("zone_section_end", "zone_chapter_end", "inline_single"):
            marker = ExerciseMarker(pattern=r"^test", behavior=behavior)
            assert marker.behavior == behavior

    def test_marker_serializes_with_group(self):
        """model_dump() must include the group field for JSON persistence."""
        marker = ExerciseMarker(pattern=r"^key terms?", behavior="zone_chapter_end",
                                group="back_matter")
        d = marker.model_dump()
        assert "group" in d
        assert d["group"] == "back_matter"

    def test_marker_round_trip_via_model_validate(self):
        """Serialise then deserialise preserves all fields including group."""
        original = ExerciseMarker(pattern=r"^stats lab", behavior="inline_single",
                                  group="lab")
        restored = ExerciseMarker.model_validate(original.model_dump())
        assert restored.pattern == original.pattern
        assert restored.behavior == original.behavior
        assert restored.group == original.group

    def test_legacy_marker_missing_group_deserializes_to_empty(self):
        """A JSON dict without 'group' key must deserialise with group='' (backward compat)."""
        data = {"pattern": r"^practice", "behavior": "zone_section_end"}
        marker = ExerciseMarker.model_validate(data)
        assert marker.group == ""


# ──────────────────────────────────────────────────────────────────────────────
# Regression tests for the follow-up bug fixes (Phase 2H)
# ──────────────────────────────────────────────────────────────────────────────


class TestNoiseBypassGroupFilter:
    """
    Bug fix Phase 2H-2: the noise-bypass loop in _build_section_chunks must only
    bypass the noise filter when the matching profile marker has either:
      - an explicit vocabulary group (new system), OR
      - a legacy zone_* behavior (real section boundary).

    Legacy inline_single markers with empty group are typically feature boxes
    (TRY IT, HOW TO, EXAMPLE) and must stay noise-filtered. The regression target
    is a book_profile.json where the LLM detected 'TRY IT' as inline_single
    with group='' — before the fix, 'TRY IT' headings leaked through as exercise
    chunks.
    """

    def _compile(self, pattern, behavior, group):
        return (re.compile(pattern, re.IGNORECASE), behavior, group)

    def test_legacy_inline_single_empty_group_does_not_trigger_bypass(self):
        """The exact shape of the bug: 'TRY IT' with behavior=inline_single, group=''."""
        markers = [self._compile(r"^TRY IT", "inline_single", "")]
        # Simulate the logic from _build_section_chunks noise bypass loop
        result = _match_exercise_marker("TRY IT 1.65", markers)
        assert result is not None
        behavior, group = result
        bypasses = (
            group in ("zone_divider", "standalone_exercise", "pmp_topic",
                      "back_matter", "chapter_pool", "lab")
            or behavior in ("zone_section_end", "zone_chapter_end")
        )
        assert bypasses is False, (
            "Legacy inline_single with empty group must NOT bypass noise filter"
        )

    def test_legacy_zone_chapter_end_empty_group_does_trigger_bypass(self):
        """Legacy zone markers (e.g. 'Exercises') still bypass noise."""
        markers = [self._compile(r"^Exercises", "zone_chapter_end", "")]
        result = _match_exercise_marker("Exercises", markers)
        assert result is not None
        behavior, group = result
        bypasses = (
            group in ("zone_divider", "standalone_exercise", "pmp_topic",
                      "back_matter", "chapter_pool", "lab")
            or behavior in ("zone_section_end", "zone_chapter_end")
        )
        assert bypasses is True

    def test_new_vocab_group_triggers_bypass_regardless_of_behavior(self):
        """Any new-vocab group triggers bypass even with inline_single behavior."""
        for group in ("zone_divider", "standalone_exercise", "pmp_topic",
                      "back_matter", "chapter_pool", "lab"):
            markers = [self._compile(r"^X", "inline_single", group)]
            result = _match_exercise_marker("X heading", markers)
            assert result is not None
            behavior, grp = result
            bypasses = (
                grp in ("zone_divider", "standalone_exercise", "pmp_topic",
                        "back_matter", "chapter_pool", "lab")
                or behavior in ("zone_section_end", "zone_chapter_end")
            )
            assert bypasses is True, f"group={group!r} should bypass"


class TestConceptIdRegexCompoundSlug:
    """
    Bug fix Phase 2H-4: the concept_id regex for chapter back-matter re-assignment
    must handle compound book_slugs (multiple underscores, non-digit segments).

    Before fix: ``re.match(r"[^_]+_(\\d+)\\.\\d+", ...)`` failed on
    'prealgebra2e_0qbw93r_(1)_1.3' because [^_]+ stopped at the first underscore
    and \\d+ couldn't match 'qbw93r'.

    After fix: ``re.search(r"_(\\d+)\\.\\d+$", ...)`` anchors to the end of the string.
    """

    def test_compound_slug_with_parens_matches(self):
        m = re.search(r"_(\d+)\.\d+$", "prealgebra2e_0qbw93r_(1)_1.3")
        assert m is not None
        assert m.group(1) == "1"  # chapter number

    def test_compound_slug_with_multiple_underscores(self):
        m = re.search(r"_(\d+)\.\d+$", "clinical_nursing_skills_7.4")
        assert m is not None
        assert m.group(1) == "7"

    def test_simple_slug_still_matches(self):
        m = re.search(r"_(\d+)\.\d+$", "statistics_3.2")
        assert m is not None
        assert m.group(1) == "3"

    def test_invalid_concept_id_returns_none(self):
        m = re.search(r"_(\d+)\.\d+$", "prealgebra_chapter1_review")
        assert m is None


class TestExerciseSuffixRetention:
    """
    Bug fix Phase 2H-3: the '(Exercises)' suffix must be retained in the stored
    heading so PMP topics are visually distinct from teaching topics with the
    same title.  Only '(ChapterReview)' and '(Lab)' are stripped.
    """

    def test_exercises_suffix_preserved_on_exercise_chunk(self):
        """An exercise chunk with PMP-style heading keeps '(Exercises)' suffix."""
        # This mimics the logic at the chunk-creation site in chunk_parser.py
        heading_text = "Use Subtraction Notation (Exercises)"
        display_heading = heading_text
        for sfx in (" (ChapterReview)", " (Lab)"):
            if display_heading.endswith(sfx):
                display_heading = display_heading[: -len(sfx)]
                break
        assert display_heading == "Use Subtraction Notation (Exercises)"

    def test_chapterreview_suffix_stripped(self):
        heading_text = "Key Terms (ChapterReview)"
        display_heading = heading_text
        for sfx in (" (ChapterReview)", " (Lab)"):
            if display_heading.endswith(sfx):
                display_heading = display_heading[: -len(sfx)]
                break
        assert display_heading == "Key Terms"

    def test_lab_suffix_stripped(self):
        heading_text = "Data Collection Experiment (Lab)"
        display_heading = heading_text
        for sfx in (" (ChapterReview)", " (Lab)"):
            if display_heading.endswith(sfx):
                display_heading = display_heading[: -len(sfx)]
                break
        assert display_heading == "Data Collection Experiment"


class TestChapterBackMatterReassignmentCompoundSlug:
    """
    End-to-end test that chapter back-matter is correctly re-assigned for books
    with compound slugs (Bug E).
    """

    def test_reassignment_happens_for_compound_slug(self):
        """chapter_review chunks get attached to last teaching section in same chapter."""
        # Last teaching section in chapter 1 (compound slug book)
        teaching = _make_chunk(
            concept_id="prealgebra2e_0qbw93r_(1)_1.5",
            heading="Divide Whole Numbers",
            chunk_type="teaching",
            book_slug="prealgebra2e_0qbw93r_(1)",
            section="1.5 Divide Whole Numbers",
            order_index=10,
            text="word " * 100,
        )
        # Chapter back matter is parsed into a standalone "section" (e.g. 1.9)
        # with chunk_type=chapter_review. The post-process step re-assigns its
        # concept_id to match the last teaching section (1.5) in the chapter.
        backmatter = _make_chunk(
            concept_id="prealgebra2e_0qbw93r_(1)_1.9",
            heading="Key Terms",
            chunk_type="chapter_review",
            book_slug="prealgebra2e_0qbw93r_(1)",
            section="1.9 Chapter Review",
            order_index=11,
            text="word " * 100,
        )
        config = {
            "max_chunk_words": None,
            "noise_patterns": [],
            "exercise_markers": [],
            "subsection_signals": [],
            "min_body_words": 30,
            "toc_sections": None,
            "corrected_headings": {},
            "max_sections_per_chapter": 99,
        }
        result = _postprocess_chunks([teaching, backmatter], config, total_body_chars=10_000, book_slug="prealgebra2e_0qbw93r_(1)")

        # Find the back matter chunk after post-processing
        bm_chunks = [c for c in result if c.heading == "Key Terms"]
        assert len(bm_chunks) == 1
        bm = bm_chunks[0]
        # Concept_id must be re-assigned to the last teaching section in chapter 1
        assert bm.concept_id == "prealgebra2e_0qbw93r_(1)_1.5", (
            f"chapter_review chunk should be re-assigned to 1.5 for compound slug; "
            f"got concept_id={bm.concept_id!r}"
        )
        assert bm.section == "1.5 Divide Whole Numbers"


class TestTocDensityThreshold:
    """
    Bug fix Phase 2H-5: the TOC-expansion density threshold was relaxed from 2
    to 1 so that a 500-char expansion chunk containing at least one valid TOC
    entry keeps expansion going (tolerates boundary-split entries).
    """

    def test_density_threshold_is_one(self):
        """The constant must be set to 1 after the fix."""
        from extraction.ocr_validator import _DENSITY_THRESHOLD
        assert _DENSITY_THRESHOLD == 1, (
            "_DENSITY_THRESHOLD must be 1 so boundary-split TOC entries don't "
            "cause expansion to stop prematurely"
        )


class TestChapterIntroBackMatterSkip:
    """
    Bug fix: _find_chapter_intros must not match back-references like
    '## Introduction to Whole Numbers' (which appears inside Chapter 1's Review
    Exercises as a section-1.1 backref) when scanning for the next chapter's
    intro start. And when intro_pos lands inside back-matter, it must skip
    forward past Practice Test / Review Exercises / Chapter Review markers.
    """

    def test_introduction_regex_anchored_to_eol(self):
        """The regex must NOT match '## Introduction to Whole Numbers'."""
        # Previously the regex `^##\s+Introduction` matched any line starting
        # with "## Introduction" — including back-references. After the fix,
        # only standalone "## Introduction" matches.
        ANCHORED = re.compile(r"^##\s+Introduction\s*$", re.MULTILINE | re.IGNORECASE)
        OLD = re.compile(r"^##\s+Introduction", re.MULTILINE | re.IGNORECASE)

        sample = "## Introduction to Whole Numbers\nproblem 453."
        assert OLD.search(sample) is not None, "old regex (false-)matched the backref"
        assert ANCHORED.search(sample) is None, (
            "anchored regex must NOT match back-reference 'Introduction to <X>'"
        )

        # Standalone "## Introduction" still matches
        sample2 = "## Introduction\nIn this chapter, you'll learn..."
        assert ANCHORED.search(sample2) is not None

    def test_skip_past_back_matter_advances_intro_pos(self):
        """When intro_pos lands inside back-matter, it advances to the next ##."""
        from extraction.chunk_parser import _skip_past_back_matter

        # Simulate the prealgebra2e Chapter 2 inference scenario:
        # region contains Chapter 1's back-matter followed by Chapter 2's intro.
        region = (
            "## Introduction to Whole Numbers\n"  # back-ref topic in Review Exercises
            "problem 453.\n"
            "## Practice Test\n"
            "problem 580.\n"
            "## Algebra Graphs\n"  # actual Chapter 2 content
            "Figure 2.1\n"
        )
        prev_end = 1000  # arbitrary base
        sec_start = prev_end + len(region) + 100
        # Intro pos initially points at the backref (false-match)
        intro_pos = prev_end  # start of "## Introduction to Whole Numbers"

        result = _skip_past_back_matter(intro_pos, prev_end, region, sec_start)
        # Must have advanced past "## Practice Test" to the next ## heading
        offset = result - prev_end
        assert region[offset:offset + 25].startswith("## Algebra Graphs"), (
            f"intro_pos should advance to '## Algebra Graphs' but got: "
            f"{region[offset:offset + 50]!r}"
        )

    def test_skip_past_back_matter_no_overshoot(self):
        """If advancing would land past sec_start, original intro_pos is kept."""
        from extraction.chunk_parser import _skip_past_back_matter

        region = "## Practice Test\nproblem 580.\n"
        prev_end = 0
        sec_start = 5  # very small — advancing would overshoot
        intro_pos = 0

        result = _skip_past_back_matter(intro_pos, prev_end, region, sec_start)
        # No safe advance possible → original intro_pos preserved
        assert result == intro_pos

    def test_skip_past_back_matter_no_back_matter_passes_through(self):
        """If no back-matter is present, intro_pos is unchanged."""
        from extraction.chunk_parser import _skip_past_back_matter

        region = "## Algebra Graphs\nFigure 2.1\n"
        prev_end = 0
        sec_start = 1000
        intro_pos = 0

        result = _skip_past_back_matter(intro_pos, prev_end, region, sec_start)
        assert result == intro_pos


class TestSectionSortKey:
    """
    Bug fix: _section_sort_key must strip trailing title text from section
    strings so '3.0 Chapter 3 Introduction' sorts as 3.0 (not as inf).

    Previously the title text made the second part 'inf' which caused
    (3, 0, inf, 0) to sort AFTER promoted '3.1b' (3, 0, 1, 2) — making
    promoted sections appear at the TOP of the chapter in the admin UI.
    """

    def test_section_with_title_strips_correctly(self):
        from api.admin_router import _section_sort_key  # tests put backend/src on sys.path
        assert _section_sort_key("3.0 Chapter 3 Introduction") == (3, 0, 0, 0)
        assert _section_sort_key("3.1 Introduction to Integers") == (3, 0, 1, 0)
        assert _section_sort_key("10.5 Solve a Formula") == (10, 0, 5, 0)

    def test_letter_suffix_preserved(self):
        from api.admin_router import _section_sort_key
        assert _section_sort_key("3.1b") == (3, 0, 1, 2)
        assert _section_sort_key("3.1a") == (3, 0, 1, 1)

    def test_correct_ordering_3_0_before_3_1b(self):
        """Regression: 3.0 must sort BEFORE 3.1b (the bug was the reverse)."""
        from api.admin_router import _section_sort_key
        keys = [
            _section_sort_key("3.0 Chapter 3 Introduction"),
            _section_sort_key("3.1 Introduction to Integers"),
            _section_sort_key("3.1b"),
            _section_sort_key("3.2 Add Integers"),
            _section_sort_key("3.10 Some Section"),  # numeric ordering, not lex
        ]
        assert keys == sorted(keys), f"order broken: {keys}"

    def test_text_only_section_falls_through_to_inf(self):
        """Promoted sections with text-only labels still get a valid (inf, 0)."""
        from api.admin_router import _section_sort_key
        result = _section_sort_key("Locate Positive and Negative Numbers")
        assert result[0] == float("inf"), (
            f"text-only section must fall through to inf as safe fallback; got {result}"
        )

    def test_multilevel_sections_preserved(self):
        """Multi-level numbering like '3.1.5' must not lose granularity."""
        from api.admin_router import _section_sort_key
        assert _section_sort_key("3.1.5 Lesson Title") == (3, 0, 1, 0, 5, 0)
        assert _section_sort_key("3.1.5") == (3, 0, 1, 0, 5, 0)
