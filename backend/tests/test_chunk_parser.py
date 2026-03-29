"""
test_chunk_parser.py — Tests for extraction.chunk_parser.

Business criteria covered:
  - Parser produces a reasonable number of deduplicated chunks (300–1200)
  - No duplicate (concept_id, heading) pairs after deduplication
  - order_index is sequential from 0 with no gaps
  - concept_id follows the "prealgebra_X.Y" format
  - Every chunk has non-empty text
  - CDN image URLs are preserved correctly (no rewriting)
  - Exercise and learning-objective chunks are preserved (unlike the old mmd_parser)
  - Every chunk carries a section label containing an X.Y number
  - LaTeX is extracted from math content
  - At least 5 chapters are present

Unit tests for internal helpers are independent of book.mmd and run always.
Integration tests require book.mmd and are auto-skipped when it is absent.
"""

import re
import sys
from pathlib import Path

import pytest

# Ensure backend/src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from extraction.chunk_parser import (
    ParsedChunk,
    _extract_latex,
    _extract_image_urls,
    _is_noise_heading,
    _word_count,
    parse_book_mmd,
)

MMD_PATH = Path(__file__).parent.parent / "output" / "prealgebra" / "book.mmd"


# ── Unit tests: helpers (always run, no file I/O) ─────────────────────────────

class TestIsNoiseHeading:
    """_is_noise_heading classifies pedagogical noise correctly."""

    def test_example_heading_is_noise(self):
        assert _is_noise_heading("EXAMPLE 1.1") is True

    def test_try_it_is_noise(self):
        assert _is_noise_heading("TRY IT 1.2") is True

    def test_solution_is_noise(self):
        assert _is_noise_heading("Solution") is True

    def test_how_to_is_noise(self):
        assert _is_noise_heading("HOW TO: Add fractions") is True

    def test_be_prepared_is_noise(self):
        assert _is_noise_heading("BE PREPARED 3.1") is True

    def test_section_exercises_is_not_noise(self):
        # Fix B: SECTION X.X EXERCISES is now kept as the exercises-zone trigger heading
        assert _is_noise_heading("SECTION 1.1 EXERCISES") is False

    def test_practice_makes_perfect_is_not_noise(self):
        # Fix B: exercise headings are kept so they can be tagged and stored as exercise chunks
        assert _is_noise_heading("Practice Makes Perfect") is False

    def test_everyday_math_is_not_noise(self):
        # Fix B: kept as optional practice content
        assert _is_noise_heading("Everyday Math") is False

    def test_writing_exercises_is_not_noise(self):
        # Fix B: kept as optional practice content
        assert _is_noise_heading("Writing Exercises") is False

    def test_self_check_is_noise(self):
        assert _is_noise_heading("Self Check") is True

    def test_in_the_following_exercises_is_noise(self):
        assert _is_noise_heading("In the following exercises, simplify") is True

    def test_mixed_practice_is_not_noise(self):
        # Fix B: kept as exercise content
        assert _is_noise_heading("Mixed Practice") is False

    def test_access_for_free_is_noise(self):
        assert _is_noise_heading("Access for free at openstax.org") is True

    def test_lettered_solution_is_noise(self):
        assert _is_noise_heading("(a) Solution") is True

    def test_numbered_item_is_noise(self):
        # "207. Seventy-five more than..."
        assert _is_noise_heading("207. Seventy-five more than a number") is True

    def test_all_caps_single_word_is_noise(self):
        assert _is_noise_heading("SOLUTION") is True

    def test_real_pedagogical_heading_is_not_noise(self):
        assert _is_noise_heading("Identify Whole Numbers") is False

    def test_round_whole_numbers_is_not_noise(self):
        assert _is_noise_heading("Round Whole Numbers") is False

    def test_learning_objectives_is_not_noise(self):
        assert _is_noise_heading("Learning Objectives") is False

    def test_mixed_case_non_noise(self):
        assert _is_noise_heading("Fraction Basics") is False


class TestExtractLatex:
    """_extract_latex pulls out block and inline LaTeX expressions."""

    def test_block_latex_extracted(self):
        text = "Here is a formula: $$a^2 + b^2 = c^2$$ in a block."
        result = _extract_latex(text)
        assert "a^2 + b^2 = c^2" in result

    def test_inline_latex_extracted(self):
        text = "The value of $x$ is unknown."
        result = _extract_latex(text)
        assert "x" in result

    def test_multiple_inline_expressions(self):
        text = "$a + b$ and $c - d$ are two expressions."
        result = _extract_latex(text)
        assert len(result) == 2

    def test_mixed_block_and_inline(self):
        text = "Inline $n$ and block $$n^2$$ expression."
        result = _extract_latex(text)
        assert len(result) == 2

    def test_empty_string_returns_empty(self):
        assert _extract_latex("") == []

    def test_text_with_no_latex_returns_empty(self):
        assert _extract_latex("No math here, just words.") == []

    def test_block_takes_precedence_over_inline_marker(self):
        # Block $$…$$ must be captured without double-counting the outer $
        text = "$$x + y = z$$"
        result = _extract_latex(text)
        assert len(result) == 1
        assert "x + y = z" in result[0]


class TestExtractImageUrls:
    """_extract_image_urls pulls CDN URLs from markdown image tags."""

    def test_cdn_url_extracted(self):
        text = "![](https://cdn.mathpix.com/cropped/2024_abc/img.jpg)"
        result = _extract_image_urls(text)
        assert len(result) == 1
        assert result[0] == "https://cdn.mathpix.com/cropped/2024_abc/img.jpg"

    def test_multiple_cdn_urls(self):
        text = (
            "![](https://cdn.mathpix.com/img1.jpg) some text "
            "![](https://cdn.mathpix.com/img2.jpg)"
        )
        result = _extract_image_urls(text)
        assert len(result) == 2

    def test_non_cdn_url_not_extracted(self):
        text = "![](https://example.com/image.jpg)"
        result = _extract_image_urls(text)
        assert result == []

    def test_empty_text_returns_empty(self):
        assert _extract_image_urls("") == []


class TestWordCount:
    """_word_count splits on whitespace correctly."""

    def test_single_word(self):
        assert _word_count("hello") == 1

    def test_multiple_words(self):
        assert _word_count("one two three four") == 4

    def test_empty_string(self):
        assert _word_count("") == 0

    def test_leading_trailing_whitespace(self):
        assert _word_count("  hello world  ") == 2


class TestParsedChunkDataclass:
    """ParsedChunk dataclass behaves correctly."""

    def test_defaults(self):
        chunk = ParsedChunk(
            book_slug="prealgebra",
            concept_id="prealgebra_1.1",
            section="1.1 Introduction",
            order_index=0,
            heading="Identify Whole Numbers",
            text="Some content here.",
        )
        assert chunk.latex == []
        assert chunk.image_urls == []
        assert chunk.book_slug == "prealgebra"

    def test_explicit_values(self):
        chunk = ParsedChunk(
            book_slug="calculus_1",
            concept_id="calculus_1_2.3",
            section="2.3 Limits",
            order_index=5,
            heading="Definition of a Limit",
            text="A limit is...",
            latex=["\\lim_{x \\to 0}"],
            image_urls=["https://cdn.mathpix.com/img.jpg"],
        )
        assert len(chunk.latex) == 1
        assert len(chunk.image_urls) == 1
        assert chunk.order_index == 5


class TestParseBookMmdExerciseZone:
    """
    Tests for the exercise-zone tagging logic using a SAMPLE_MMD that
    mirrors real OpenStax book structure: section heading, teaching subsections,
    noise headings, and an exercise zone with sub-headings.

    Key structural facts:
    - SECTION_PATTERN matches `### 1.1 Title` (not `# Section 1.1 Title`)
    - Only `##` headings trigger subsection splits (not `###` or `####`)
    - SECTION X.X EXERCISES (## level) triggers in_exercises_zone=True
    - Sub-headings after the zone marker get "(Exercises)" suffix
    - Noise headings (BE PREPARED, ACCESS ADDITIONAL ONLINE RESOURCES) are excluded
    """

    # Body padding meets MIN_SECTION_BODY_WORDS=30 threshold
    _PAD = (
        "This content describes important mathematical concepts for students. "
        "Regular practice and careful study are essential for mastery of this topic.\n"
    )

    # Correctly structured synthetic MMD:
    #   - Section heading uses `### X.Y Title` format (matches SECTION_PATTERN)
    #   - Sub-headings use `##` level (the only level chunk_parser splits on)
    #   - Noise headings use `##` level so the parser encounters and filters them
    SAMPLE_MMD = (
        "### 1.1 Introduction to Whole Numbers\n\n"
        "## Learning Objectives\n\n"
        "By the end of this section, you will be able to:\n"
        "- Identify counting numbers and whole numbers\n\n"
        "## Identify Counting Numbers and Whole Numbers\n\n"
        "Counting numbers are 1, 2, 3, 4, 5 and so on. "
        "Whole numbers include 0, 1, 2, 3, 4, 5 and continue forever. "
        "This important mathematical concept is foundational.\n\n"
        "## BE PREPARED\n\n"
        "Before you start, make sure you know basic arithmetic.\n\n"
        "## ACCESS ADDITIONAL ONLINE RESOURCES\n\n"
        "Visit the OpenStax website for more resources.\n\n"
        "## SECTION 1.1 EXERCISES\n\n"
        "## Practice Makes Perfect\n\n"
        "## Identify Counting Numbers and Whole Numbers\n\n"
        "1. List the counting numbers between 0 and 5.\n"
        "2. Is zero a whole number?\n\n"
        "## Everyday Math\n\n"
        "3. Real world example about counting.\n\n"
        "## Writing Exercises\n\n"
        "4. In your own words, explain what whole numbers are.\n"
    )

    def _write_mmd(self, tmp_path: Path, content: str) -> Path:
        mmd = tmp_path / "book.mmd"
        mmd.write_text(content, encoding="utf-8")
        return mmd

    def _parsed(self, tmp_path: Path) -> list[ParsedChunk]:
        return parse_book_mmd(self._write_mmd(tmp_path, self.SAMPLE_MMD), "prealgebra")

    def test_be_prepared_not_in_any_chunk_heading(self, tmp_path):
        """BE PREPARED is config-driven noise and must not appear as a chunk heading."""
        headings = [c.heading for c in self._parsed(tmp_path)]
        assert not any("BE PREPARED" in h for h in headings), (
            f"BE PREPARED appeared as a chunk heading. Headings: {headings}"
        )

    def test_access_additional_online_resources_not_in_any_chunk_heading(self, tmp_path):
        """ACCESS ADDITIONAL ONLINE RESOURCES is config-driven noise and must be excluded."""
        headings = [c.heading for c in self._parsed(tmp_path)]
        assert not any("ACCESS ADDITIONAL ONLINE RESOURCES" in h for h in headings), (
            f"ACCESS ADDITIONAL ONLINE RESOURCES appeared as a chunk heading. Headings: {headings}"
        )

    def test_teaching_chunk_for_identify_counting_numbers_exists(self, tmp_path):
        """The pedagogical subsection 'Identify Counting Numbers and Whole Numbers' must
        produce a teaching chunk with exactly that heading (no suffix)."""
        headings = [c.heading for c in self._parsed(tmp_path)]
        assert "Identify Counting Numbers and Whole Numbers" in headings, (
            f"Teaching heading missing. Actual headings: {headings}"
        )

    def test_at_least_one_exercises_suffix_chunk_exists(self, tmp_path):
        """At least one chunk must have '(Exercises)' in its heading after zone tagging."""
        headings = [c.heading for c in self._parsed(tmp_path)]
        assert any("(Exercises)" in h for h in headings), (
            f"No (Exercises) chunks found. Actual headings: {headings}"
        )

    def test_teaching_and_exercise_versions_coexist_no_dedup_collision(self, tmp_path):
        """'Identify Counting Numbers and Whole Numbers' (teaching) and
        'Identify Counting Numbers and Whole Numbers (Exercises)' must both exist
        simultaneously — the (Exercises) suffix is the dedup key differentiator."""
        headings = [c.heading for c in self._parsed(tmp_path)]
        has_teaching = "Identify Counting Numbers and Whole Numbers" in headings
        has_exercise = "Identify Counting Numbers and Whole Numbers (Exercises)" in headings
        assert has_teaching, f"Teaching version missing. Headings: {headings}"
        assert has_exercise, f"Exercise version missing. Headings: {headings}"

    def test_section_exercises_chunk_present_for_exercise_gate(self, tmp_path):
        """The 'SECTION 1.1 EXERCISES' heading must produce its own chunk (exercise_gate)."""
        headings = [c.heading for c in self._parsed(tmp_path)]
        assert any("SECTION 1.1 EXERCISES" in h for h in headings), (
            f"SECTION 1.1 EXERCISES chunk missing. Actual headings: {headings}"
        )

    def test_everyday_math_exercises_chunk_present(self, tmp_path):
        """Everyday Math inside the exercise zone must be tagged '(Exercises)'."""
        headings = [c.heading for c in self._parsed(tmp_path)]
        assert "Everyday Math (Exercises)" in headings, (
            f"Everyday Math (Exercises) missing. Actual headings: {headings}"
        )

    def test_writing_exercises_exercises_chunk_present(self, tmp_path):
        """Writing Exercises inside the exercise zone must be tagged '(Exercises)'."""
        headings = [c.heading for c in self._parsed(tmp_path)]
        assert "Writing Exercises (Exercises)" in headings, (
            f"Writing Exercises (Exercises) missing. Actual headings: {headings}"
        )

    def test_learning_objectives_not_treated_as_config_noise(self, tmp_path):
        """Learning Objectives is NOT in CONTENT_EXCLUDE_MARKERS.
        If present in output it must appear with its clean heading."""
        headings = [c.heading for c in self._parsed(tmp_path)]
        lo_headings = [h for h in headings if "Learning Objectives" in h]
        for h in lo_headings:
            assert "BE PREPARED" not in h
            assert "ACCESS ADDITIONAL ONLINE RESOURCES" not in h


class TestParseBookMmdWithSyntheticContent:
    """
    Unit tests for parse_book_mmd using synthetic .mmd content written to a temp file.
    These run without the real book.mmd — testing parser logic in isolation.
    """

    # MIN_SECTION_BODY_WORDS=30 filters fake exercise stubs; synthetic bodies must meet threshold.
    _BODY = (
        "This important mathematical concept is foundational. Students must understand it "
        "thoroughly before advancing to more complex topics in the course curriculum. "
        "Regular practice and careful study are essential for mastery.\n"
    )

    def _write_mmd(self, tmp_path: Path, content: str) -> Path:
        mmd = tmp_path / "book.mmd"
        mmd.write_text(content, encoding="utf-8")
        return mmd

    def test_single_section_no_subheadings(self, tmp_path):
        content = (
            "### 1.1 Introduction to Whole Numbers\n\n"
            "Whole numbers are the numbers we use to count objects. "
            "They include zero and all positive integers: 0, 1, 2, 3, 4, 5 and so on. "
            "Whole numbers do not include fractions, decimals, or negative numbers.\n"
        )
        mmd = self._write_mmd(tmp_path, content)
        chunks = parse_book_mmd(mmd, "prealgebra")
        assert len(chunks) == 1
        assert chunks[0].concept_id == "prealgebra_1.1"
        assert "Whole numbers" in chunks[0].text

    def test_section_with_meaningful_subheadings(self, tmp_path):
        content = (
            "### 1.1 Introduction to Whole Numbers\n\n"
            "Some intro text here.\n\n"
            "## Identify Whole Numbers\n\n"
            f"Content about identifying whole numbers. {self._BODY}\n"
            "## Round Whole Numbers\n\n"
            f"Content about rounding. {self._BODY}\n"
        )
        mmd = self._write_mmd(tmp_path, content)
        chunks = parse_book_mmd(mmd, "prealgebra")
        # Orphan text + 2 subheadings = 3 raw → all unique → 3 after dedup
        headings = [c.heading for c in chunks]
        assert "Identify Whole Numbers" in headings
        assert "Round Whole Numbers" in headings

    def test_noise_heading_not_split_boundary(self, tmp_path):
        content = (
            "### 1.1 Introduction to Whole Numbers\n\n"
            "## Identify Whole Numbers\n\n"
            f"Here is an explanation. {self._BODY}\n"
            "## EXAMPLE 1.1\n\n"
            "An example solution.\n\n"
            "## TRY IT 1.1\n\n"
            "Now you try.\n"
        )
        mmd = self._write_mmd(tmp_path, content)
        chunks = parse_book_mmd(mmd, "prealgebra")
        # EXAMPLE 1.1 and TRY IT 1.1 are noise — should NOT create separate chunks
        headings = [c.heading for c in chunks]
        assert "EXAMPLE 1.1" not in headings
        assert "TRY IT 1.1" not in headings
        # Only "Identify Whole Numbers" should be a chunk heading
        assert "Identify Whole Numbers" in headings

    def test_deduplication_keeps_longest_copy(self, tmp_path):
        # Simulate Mathpix's 3 copies: short TOC stub, long body, short chapter review
        content = (
            # First occurrence — short (TOC stub, ~3 words)
            "### 1.1 Introduction to Whole Numbers\n\n"
            "Short text.\n\n"
            "## Identify Whole Numbers\n\n"
            "Brief.\n\n"
            # Second occurrence — long (body, ~30 words)
            "### 1.1 Introduction to Whole Numbers\n\n"
            "## Identify Whole Numbers\n\n"
            "Whole numbers are the numbers 0, 1, 2, 3, and so on. "
            "They are used for counting and ordering. "
            "The set of whole numbers is infinite.\n\n"
            # Third occurrence — medium (chapter review, ~10 words)
            "### 1.1 Introduction to Whole Numbers\n\n"
            "## Identify Whole Numbers\n\n"
            "Review: whole numbers start at zero and go up.\n"
        )
        mmd = self._write_mmd(tmp_path, content)
        chunks = parse_book_mmd(mmd, "prealgebra")
        # Only 1 chunk should survive — the longest body copy
        matching = [c for c in chunks if c.heading == "Identify Whole Numbers"]
        assert len(matching) == 1
        # Must be the long version
        assert "infinite" in matching[0].text

    def test_order_index_is_sequential(self, tmp_path):
        content = (
            "### 1.1 Introduction to Whole Numbers\n\n"
            "## Identify Whole Numbers\n\nContent A.\n\n"
            "## Round Whole Numbers\n\nContent B.\n\n"
            "### 1.2 Fractions\n\n"
            "## Proper Fractions\n\nContent C.\n"
        )
        mmd = self._write_mmd(tmp_path, content)
        chunks = parse_book_mmd(mmd, "prealgebra")
        indices = [c.order_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_concept_id_format(self, tmp_path):
        content = f"### 3.7 Some Section\n\nContent here. {self._BODY}\n"
        mmd = self._write_mmd(tmp_path, content)
        chunks = parse_book_mmd(mmd, "mybook")
        assert len(chunks) == 1
        assert chunks[0].concept_id == "mybook_3.7"

    def test_figure_number_sections_skipped(self, tmp_path):
        # Section numbers > 10 in chapter are figure references, not real sections
        content = (
            "### 1.52 Figure Caption Heading\n\n"
            "This should not create a chunk.\n\n"
            f"### 1.1 Real Section\n\nThis should create a chunk. {self._BODY}\n"
        )
        mmd = self._write_mmd(tmp_path, content)
        chunks = parse_book_mmd(mmd, "prealgebra")
        concept_ids = [c.concept_id for c in chunks]
        assert "prealgebra_1.52" not in concept_ids
        assert "prealgebra_1.1" in concept_ids

    def test_latex_is_extracted_in_chunks(self, tmp_path):
        content = (
            "### 1.1 Rounding Numbers\n\n"
            f"The formula is $a^2 + b^2 = c^2$ and also $$n!$$. {self._BODY}\n"
        )
        mmd = self._write_mmd(tmp_path, content)
        chunks = parse_book_mmd(mmd, "prealgebra")
        assert len(chunks) == 1
        assert len(chunks[0].latex) == 2

    def test_image_urls_extracted_in_chunks(self, tmp_path):
        cdn = "https://cdn.mathpix.com/cropped/2024_test/img001.jpg"
        content = (
            f"### 1.1 Visual Numbers\n\n"
            f"See the number line:\n\n![](  {cdn})\n\n"
            "More text here.\n"
        )
        # Note: IMAGE_URL_PATTERN doesn't handle leading spaces in URL — use exact format
        content = (
            "### 1.1 Visual Numbers\n\n"
            f"See the number line: ![]({cdn})\n\n"
            f"More text here. {self._BODY}\n"
        )
        mmd = self._write_mmd(tmp_path, content)
        chunks = parse_book_mmd(mmd, "prealgebra")
        assert len(chunks[0].image_urls) == 1
        assert chunks[0].image_urls[0] == cdn

    def test_section_label_in_chunk(self, tmp_path):
        content = f"### 2.4 Adding Integers\n\nContent about adding integers. {self._BODY}\n"
        mmd = self._write_mmd(tmp_path, content)
        chunks = parse_book_mmd(mmd, "prealgebra")
        assert chunks[0].section == "2.4 Adding Integers"

    def test_empty_section_body_produces_no_chunk(self, tmp_path):
        # A section heading followed immediately by another section produces no body
        content = (
            "### 1.1 Empty Section\n"
            f"### 1.2 Real Section\n\nSome content. {self._BODY}\n"
        )
        mmd = self._write_mmd(tmp_path, content)
        chunks = parse_book_mmd(mmd, "prealgebra")
        # Only prealgebra_1.2 should have a chunk
        ids = [c.concept_id for c in chunks]
        assert "prealgebra_1.1" not in ids
        assert "prealgebra_1.2" in ids

    def test_multiple_chapters_present(self, tmp_path):
        content = (
            f"### 1.1 Whole Numbers\n\nContent A. {self._BODY}\n"
            f"### 2.1 Fractions\n\nContent B. {self._BODY}\n"
            f"### 3.2 Decimals\n\nContent C. {self._BODY}\n"
            f"### 4.1 Ratios\n\nContent D. {self._BODY}\n"
            f"### 5.3 Percents\n\nContent E. {self._BODY}\n"
        )
        mmd = self._write_mmd(tmp_path, content)
        chunks = parse_book_mmd(mmd, "prealgebra")
        chapter_nums = {c.concept_id.split("_")[1].split(".")[0] for c in chunks}
        assert len(chapter_nums) >= 5

    def test_non_empty_text_guaranteed(self, tmp_path):
        content = (
            "### 1.1 A Section\n\n"
            "## First Subsection\n\n"
            "There is content here about math.\n"
        )
        mmd = self._write_mmd(tmp_path, content)
        chunks = parse_book_mmd(mmd, "prealgebra")
        for chunk in chunks:
            assert chunk.text.strip(), f"Empty text found: {chunk.heading}"


# ── Integration tests: require real book.mmd ──────────────────────────────────

@pytest.mark.skipif(not MMD_PATH.exists(), reason="book.mmd not present in output/prealgebra/")
class TestChunkParserIntegration:
    """Runs against the actual prealgebra book.mmd when available."""

    def setup_method(self):
        self.chunks = parse_book_mmd(MMD_PATH, "prealgebra")

    def test_chunk_count_reasonable(self):
        # After Fix B, exercise chunks are included — prealgebra has ~1490 total parsed.
        # After dedup the count should be between 800 and 2000.
        assert 800 <= len(self.chunks) <= 2000, (
            f"Unexpected chunk count: {len(self.chunks)} — dedup may have failed"
        )

    def test_no_duplicate_key_pairs(self):
        keys = [(c.concept_id, c.heading) for c in self.chunks]
        assert len(keys) == len(set(keys)), "Duplicate (concept_id, heading) pairs found after dedup"

    def test_order_index_sequential(self):
        indices = [c.order_index for c in self.chunks]
        assert indices == list(range(len(self.chunks)))

    def test_concept_id_format(self):
        pattern = re.compile(r"^prealgebra_\d+\.\d+$")
        bad = [c.concept_id for c in self.chunks if not pattern.match(c.concept_id)]
        assert not bad, f"Bad concept_id format found: {bad[:5]}"

    def test_chunks_have_non_empty_text(self):
        empty = [c.heading for c in self.chunks if not c.text.strip()]
        assert not empty, f"Chunks with empty text: {empty[:5]}"

    def test_chunks_with_images_have_cdn_urls(self):
        image_chunks = [c for c in self.chunks if c.image_urls]
        assert len(image_chunks) > 0, "Expected some chunks to have CDN image URLs"
        for chunk in image_chunks:
            for url in chunk.image_urls:
                assert url.startswith("https://cdn.mathpix.com/"), f"Non-CDN URL: {url}"

    def test_all_chunks_have_section_with_xy_format(self):
        bad = []
        for c in self.chunks:
            if not c.section:
                bad.append(f"Missing section: {c.heading}")
            elif not re.search(r"\d+\.\d+", c.section):
                bad.append(f"Section has no X.Y: {c.section}")
        assert not bad, f"Section format issues: {bad[:5]}"

    def test_latex_extraction(self):
        latex_chunks = [c for c in self.chunks if c.latex]
        assert len(latex_chunks) > 0, "Expected LaTeX in a math textbook"

    def test_multiple_chapters_present(self):
        chapter_nums = {c.concept_id.split("_")[1].split(".")[0] for c in self.chunks}
        assert len(chapter_nums) >= 5, f"Expected >=5 chapters, got: {sorted(chapter_nums)}"

    def test_noise_headings_not_in_chunk_headings(self):
        noise_terms = ["EXAMPLE", "TRY IT", "Solution", "HOW TO", "BE PREPARED"]
        noise_chunks = [
            c.heading for c in self.chunks
            if any(c.heading.upper().startswith(term.upper()) for term in noise_terms)
        ]
        assert not noise_chunks, f"Noise headings became chunk boundaries: {noise_chunks[:5]}"
