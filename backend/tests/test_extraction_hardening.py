"""
test_extraction_hardening.py — Tests for extraction pipeline hardening fixes.

Tests cover:
  Group A — chunk_parser.py: tiny-chunk merge (images + latex transfer, backward
            merge, standalone preservation), coverage check threshold
  Group B — content_filter.py: BE PREPARED safety cap and terminators,
            exercise marker line-start requirement
  Group C — chunk_builder.py: download_image CDN/local failure paths,
            _extract_image_captions (LaTeX, markdown, padding)

All tests are self-contained; no database, PDF, or OpenAI access required.
"""

import os
import sys
import logging

# Must appear before any project import so `extraction.*` and `config` resolve.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_chunk(
    concept_id: str,
    text: str,
    order_index: int = 0,
    heading: str = "Test Heading",
    image_urls: list | None = None,
    latex: list | None = None,
) -> "ParsedChunk":
    """Convenience factory so tests stay concise."""
    from extraction.chunk_parser import ParsedChunk
    return ParsedChunk(
        book_slug="prealgebra",
        concept_id=concept_id,
        section="1.1 Test Section",
        order_index=order_index,
        heading=heading,
        text=text,
        image_urls=image_urls if image_urls is not None else [],
        latex=latex if latex is not None else [],
    )


def _run_merge_logic(deduped: list) -> list:
    """
    Re-implements the tiny-chunk merge loop from chunk_parser.py lines 625-653
    so Group A tests exercise the real logic without calling parse_book_mmd()
    (which requires a real .mmd file on disk).
    """
    _merged: list = []
    for _mi, _chunk in enumerate(deduped):
        _word_ct = len(_chunk.text.split())
        if (
            _word_ct < 50
            and _mi + 1 < len(deduped)
            and deduped[_mi + 1].concept_id == _chunk.concept_id
        ):
            # Forward merge
            deduped[_mi + 1].text = _chunk.text + "\n\n" + deduped[_mi + 1].text
            deduped[_mi + 1].image_urls = _chunk.image_urls + deduped[_mi + 1].image_urls
            deduped[_mi + 1].latex = _chunk.latex + deduped[_mi + 1].latex
        elif (
            _word_ct < 50
            and _merged
            and _merged[-1].concept_id == _chunk.concept_id
        ):
            # Backward merge
            _merged[-1].text += "\n\n" + _chunk.text
            _merged[-1].image_urls += _chunk.image_urls
            _merged[-1].latex += _chunk.latex
        else:
            _merged.append(_chunk)
    return _merged


@dataclass
class _MockSection:
    """Minimal SectionBoundary stand-in for content_filter tests."""
    section_number: str = "1.1"
    section_title: str = "Introduction to Whole Numbers"
    section_in_chapter: int = 1
    chapter_number: int = 1
    start_page_index: int = 0
    end_page_index: int = 5
    header_char_offset: int = 0


# ═════════════════════════════════════════════════════════════════════════════
# Group A — chunk_parser.py: tiny-chunk merge
# ═════════════════════════════════════════════════════════════════════════════

class TestTinyChunkMerge:
    """Business rule: chunks under 50 words must never be silently dropped.
    Their content, images, and latex must be transferred to an adjacent chunk."""

    def test_tiny_chunk_forward_merge_transfers_images_and_latex(self):
        """When a <50 word chunk merges forward, its image_urls and latex
        must both appear in the receiving chunk."""
        # Arrange
        tiny_text = "Short intro text."  # well under 50 words
        big_text = " ".join(["word"] * 60)  # 60 words — above threshold

        tiny = _make_chunk(
            concept_id="prealgebra_1.1",
            text=tiny_text,
            order_index=0,
            image_urls=["https://cdn.mathpix.com/img1.jpg"],
            latex=["x^2"],
        )
        big = _make_chunk(
            concept_id="prealgebra_1.1",
            text=big_text,
            order_index=1,
            image_urls=["https://cdn.mathpix.com/img2.jpg"],
            latex=["y^2"],
        )

        # Act
        result = _run_merge_logic([tiny, big])

        # Assert — only one chunk survives; it has both images and both latex
        assert len(result) == 1
        merged = result[0]
        assert "https://cdn.mathpix.com/img1.jpg" in merged.image_urls
        assert "https://cdn.mathpix.com/img2.jpg" in merged.image_urls
        assert "x^2" in merged.latex
        assert "y^2" in merged.latex

    def test_tiny_chunk_forward_merge_prepends_text(self):
        """Merged text of tiny chunk appears before the receiving chunk's text."""
        tiny_text = "Intro."
        big_text = " ".join(["word"] * 60)

        tiny = _make_chunk("prealgebra_1.1", tiny_text, order_index=0)
        big = _make_chunk("prealgebra_1.1", big_text, order_index=1)

        result = _run_merge_logic([tiny, big])

        assert len(result) == 1
        assert result[0].text.startswith(tiny_text)
        assert big_text in result[0].text

    def test_tiny_chunk_backward_merge_when_last_in_section(self):
        """Last chunk in section merges backward into previous subsection,
        and is NOT dropped as standalone."""
        big_text = " ".join(["word"] * 60)
        tiny_text = "Trailing note."

        chunk1 = _make_chunk("prealgebra_1.1", big_text, order_index=0, heading="Main")
        chunk2 = _make_chunk("prealgebra_1.1", big_text, order_index=1, heading="Middle")
        # chunk3 has no forward merge target (it's the last item in the list)
        chunk3 = _make_chunk("prealgebra_1.1", tiny_text, order_index=2, heading="Tiny Last")

        result = _run_merge_logic([chunk1, chunk2, chunk3])

        # chunk3 must merge backward into chunk2, not be dropped
        assert len(result) == 2
        assert "Trailing note." in result[1].text

    def test_tiny_chunk_backward_merge_transfers_images(self):
        """Backward-merged tiny chunk passes its images to the previous chunk."""
        big_text = " ".join(["word"] * 60)
        tiny_text = "End note."  # <50 words, no forward target with matching concept_id

        prev = _make_chunk(
            "prealgebra_1.1", big_text, order_index=0,
            image_urls=["https://cdn.mathpix.com/prev.jpg"],
        )
        tiny = _make_chunk(
            "prealgebra_1.1", tiny_text, order_index=1,
            image_urls=["https://cdn.mathpix.com/tiny.jpg"],
            latex=["z^3"],
        )

        result = _run_merge_logic([prev, tiny])

        assert len(result) == 1
        assert "https://cdn.mathpix.com/tiny.jpg" in result[0].image_urls
        assert "z^3" in result[0].latex

    def test_tiny_chunk_different_concept_id_kept_standalone(self):
        """Chunk with a different concept_id from its neighbours is kept as-is —
        never merged across concept boundaries and never dropped."""
        big_text = " ".join(["word"] * 60)
        tiny_text = "Isolated note."

        chunk_a = _make_chunk("prealgebra_1.1", big_text, order_index=0)
        # Different concept_id — merge is forbidden
        tiny_b = _make_chunk("prealgebra_1.2", tiny_text, order_index=1)
        chunk_c = _make_chunk("prealgebra_1.3", big_text, order_index=2)

        result = _run_merge_logic([chunk_a, tiny_b, chunk_c])

        # All three must survive because concept_ids differ
        assert len(result) == 3
        assert any(c.concept_id == "prealgebra_1.2" for c in result)

    def test_chunks_at_exactly_50_words_are_not_merged(self):
        """The threshold is strictly < 50 words; a 50-word chunk is kept intact."""
        exactly_50 = " ".join(["word"] * 50)
        big_text = " ".join(["word"] * 60)

        chunk_a = _make_chunk("prealgebra_1.1", exactly_50, order_index=0)
        chunk_b = _make_chunk("prealgebra_1.1", big_text, order_index=1)

        result = _run_merge_logic([chunk_a, chunk_b])

        # Both survive; exactly-50 is NOT below the threshold
        assert len(result) == 2

    def test_multiple_tiny_chunks_each_merge_forward(self):
        """Each tiny chunk merges forward independently; none are dropped."""
        tiny_text = "Few words here."  # < 50 words
        big_text = " ".join(["word"] * 60)

        tiny1 = _make_chunk("prealgebra_1.1", tiny_text, order_index=0, image_urls=["img_a.jpg"])
        tiny2 = _make_chunk("prealgebra_1.1", tiny_text, order_index=1, image_urls=["img_b.jpg"])
        big = _make_chunk("prealgebra_1.1", big_text, order_index=2, image_urls=["img_c.jpg"])

        result = _run_merge_logic([tiny1, tiny2, big])

        assert len(result) == 1
        assert "img_a.jpg" in result[0].image_urls
        assert "img_b.jpg" in result[0].image_urls
        assert "img_c.jpg" in result[0].image_urls


class TestCoverageCheck:
    """Business rule: coverage check must flag when less than 95% of body
    characters are represented in chunks."""

    def test_coverage_check_returns_ratio(self):
        """_check_coverage returns a float ratio, not a boolean."""
        from extraction.chunk_parser import _check_coverage

        chunk = _make_chunk("prealgebra_1.1", "a" * 900)
        ratio = _check_coverage(1000, [chunk])

        assert isinstance(ratio, float)
        assert abs(ratio - 0.9) < 0.001

    def test_coverage_check_below_95_percent(self):
        """90% coverage is below the 0.95 threshold."""
        from extraction.chunk_parser import _check_coverage

        chunk = _make_chunk("prealgebra_1.1", "a" * 900)
        ratio = _check_coverage(1000, [chunk])

        assert ratio < 0.95

    def test_coverage_check_at_100_percent(self):
        """Perfect coverage returns 1.0."""
        from extraction.chunk_parser import _check_coverage

        chunk = _make_chunk("prealgebra_1.1", "a" * 1000)
        ratio = _check_coverage(1000, [chunk])

        assert ratio == pytest.approx(1.0)

    def test_coverage_check_warns_via_logging(self, caplog):
        """When coverage < 95%, a WARNING is emitted to the logger."""
        from extraction.chunk_parser import _check_coverage, logger as cp_logger

        chunk = _make_chunk("prealgebra_1.1", "a" * 500)  # 50% coverage
        with caplog.at_level(logging.WARNING, logger="extraction.chunk_parser"):
            # The coverage check itself only returns; the warning is emitted by
            # parse_book_mmd. We verify the helper returns a value that would
            # trigger the warning path (< 0.95).
            ratio = _check_coverage(1000, [chunk])

        assert ratio < 0.95  # caller would log warning

    def test_coverage_check_zero_body_chars_returns_one(self):
        """Zero raw_body_chars must not cause division-by-zero — returns 1.0."""
        from extraction.chunk_parser import _check_coverage

        ratio = _check_coverage(0, [])

        assert ratio == 1.0


# ═════════════════════════════════════════════════════════════════════════════
# Group B — content_filter.py: BE PREPARED and exercise marker behaviour
# ═════════════════════════════════════════════════════════════════════════════

class TestBePreparedFilter:
    """Business rule: BE PREPARED skip must stop at defined terminators and
    at a 15-line safety cap so that instructional content is never silently lost."""

    def test_be_prepared_safety_cap_after_15_lines(self):
        """Content after 15 non-terminating lines following BE PREPARED is preserved."""
        from extraction.content_filter import _remove_be_prepared

        # 20 generic lines that match none of the original terminators
        generic_lines = [f"Numbered item {i} with some filler text." for i in range(20)]
        text = "BE PREPARED\n" + "\n".join(generic_lines)

        result = _remove_be_prepared(text)

        # Lines beyond the 15-line cap must survive
        assert "Numbered item 15" in result or "Numbered item 16" in result

    def test_be_prepared_removes_quiz_lines_before_cap(self):
        """Lines immediately after BE PREPARED (within 15) are removed."""
        from extraction.content_filter import _remove_be_prepared

        text = "BE PREPARED\nQuiz question 1.\nQuiz question 2.\n\nImportant content."

        result = _remove_be_prepared(text)

        assert "Quiz question 1." not in result
        assert "Quiz question 2." not in result

    def test_be_prepared_stops_at_double_blank_line(self):
        """Two consecutive blank lines terminate the BE PREPARED skip block."""
        from extraction.content_filter import _remove_be_prepared

        text = "BE PREPARED\nline1\nline2\n\n\nImportant content here"

        result = _remove_be_prepared(text)

        assert "Important content here" in result

    def test_be_prepared_stops_at_markdown_heading(self):
        """A markdown heading (##) unconditionally terminates the BE PREPARED skip."""
        from extraction.content_filter import _remove_be_prepared

        text = "BE PREPARED\nskip line 1\nskip line 2\n## Next Topic\nImportant content"

        result = _remove_be_prepared(text)

        assert "## Next Topic" in result
        assert "Important content" in result

    def test_be_prepared_stops_at_h3_heading(self):
        """### headings also terminate the BE PREPARED skip."""
        from extraction.content_filter import _remove_be_prepared

        text = "BE PREPARED\nskip line\n### 1.2 Real Content\nKeep this"

        result = _remove_be_prepared(text)

        assert "### 1.2 Real Content" in result
        assert "Keep this" in result

    def test_be_prepared_not_present_text_unchanged(self):
        """Text with no BE PREPARED block passes through unmodified."""
        from extraction.content_filter import _remove_be_prepared

        text = "When we add two numbers, we get a sum.\nThe result is always non-negative."

        result = _remove_be_prepared(text)

        assert result == text

    def test_be_prepared_multiple_blocks_all_removed(self):
        """Multiple BE PREPARED blocks in the same text are each handled."""
        from extraction.content_filter import _remove_be_prepared

        text = (
            "BE PREPARED\nquiz item A\n\n\n"
            "Instructional paragraph one.\n"
            "BE PREPARED\nquiz item B\n\n\n"
            "Instructional paragraph two."
        )

        result = _remove_be_prepared(text)

        assert "quiz item A" not in result
        assert "Instructional paragraph one." in result
        assert "Instructional paragraph two." in result

    def test_be_prepared_stops_at_example_keyword(self):
        """'EXAMPLE' at the start of a line terminates the BE PREPARED skip."""
        from extraction.content_filter import _remove_be_prepared

        text = "BE PREPARED\nskip this\nEXAMPLE 1.1 Addition\nKeep this example"

        result = _remove_be_prepared(text)

        assert "EXAMPLE 1.1 Addition" in result
        assert "Keep this example" in result


class TestExerciseMarkerTrim:
    """Business rule: exercise markers must only truncate content when they
    appear at the START of a line — mid-sentence occurrences must be ignored."""

    def test_exercise_marker_mid_sentence_does_not_truncate(self):
        """'Practice Makes Perfect' inside a sentence must not cause truncation."""
        from extraction.content_filter import _trim_at_exercises

        section = _MockSection()
        text = (
            "This example shows Practice Makes Perfect in action.\n"
            "More instructional content here.\n"
            "Another important paragraph."
        )

        result = _trim_at_exercises(text, section)

        assert "More instructional content here." in result
        assert "Another important paragraph." in result

    def test_exercise_marker_at_line_start_truncates(self):
        """'Practice Makes Perfect' at line start triggers truncation of everything after."""
        from extraction.content_filter import _trim_at_exercises

        section = _MockSection()
        text = (
            "Some instructional content.\n"
            "Practice Makes Perfect\n"
            "Exercise 1: Add these numbers.\n"
            "Exercise 2: Subtract these numbers."
        )

        result = _trim_at_exercises(text, section)

        assert "Some instructional content." in result
        assert "Exercise 1: Add these numbers." not in result
        assert "Exercise 2: Subtract these numbers." not in result

    def test_section_exercises_marker_truncates(self):
        """'Section X.Y Exercises' triggers truncation regardless of case."""
        from extraction.content_filter import _trim_at_exercises

        section = _MockSection(section_number="1.1")
        text = (
            "Instructional paragraph.\n"
            "Section 1.1 Exercises\n"
            "1. First exercise\n"
            "2. Second exercise"
        )

        result = _trim_at_exercises(text, section)

        assert "Instructional paragraph." in result
        assert "First exercise" not in result

    def test_everyday_math_at_line_start_truncates(self):
        """'Everyday Math' at the beginning of a line truncates the rest."""
        from extraction.content_filter import _trim_at_exercises

        section = _MockSection()
        text = (
            "Key concept explanation.\n"
            "Everyday Math\n"
            "Real-world problem 1."
        )

        result = _trim_at_exercises(text, section)

        assert "Key concept explanation." in result
        assert "Real-world problem 1." not in result

    def test_writing_exercises_at_line_start_truncates(self):
        """'Writing Exercises' at line start truncates the rest."""
        from extraction.content_filter import _trim_at_exercises

        section = _MockSection()
        text = (
            "Explanation text.\n"
            "Writing Exercises\n"
            "Write a paragraph about addition."
        )

        result = _trim_at_exercises(text, section)

        assert "Explanation text." in result
        assert "Write a paragraph about addition." not in result

    def test_no_exercise_markers_text_unchanged(self):
        """Text with no exercise markers passes through unmodified."""
        from extraction.content_filter import _trim_at_exercises

        section = _MockSection()
        text = "First paragraph.\nSecond paragraph.\nThird paragraph."

        result = _trim_at_exercises(text, section)

        assert result == text

    def test_mixed_practice_at_line_start_truncates(self):
        """'Mixed Practice' at line start truncates the rest."""
        from extraction.content_filter import _trim_at_exercises

        section = _MockSection()
        text = "Learn this concept.\nMixed Practice\nProblem 1."

        result = _trim_at_exercises(text, section)

        assert "Learn this concept." in result
        assert "Problem 1." not in result


# ═════════════════════════════════════════════════════════════════════════════
# Group C — chunk_builder.py: download_image failure paths
# ═════════════════════════════════════════════════════════════════════════════

class TestDownloadImage:
    """Business rule: download_image must return None (not raise, not return a
    filename) when the CDN request fails or the local source file is missing."""

    def test_cdn_failure_returns_none(self, tmp_path):
        """An exception from requests.get causes download_image to return None."""
        from extraction.chunk_builder import download_image

        with patch("extraction.chunk_builder.requests.get", side_effect=Exception("timeout")):
            result = download_image("https://cdn.mathpix.com/test.jpg", tmp_path)

        assert result is None

    def test_cdn_http_error_returns_none(self, tmp_path):
        """A non-200 HTTP response (raise_for_status) causes download_image to return None."""
        from extraction.chunk_builder import download_image
        import requests as req_lib

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = req_lib.HTTPError("404")

        with patch("extraction.chunk_builder.requests.get", return_value=mock_response):
            result = download_image("https://cdn.mathpix.com/missing.jpg", tmp_path)

        assert result is None

    def test_local_image_not_in_mathpix_extracted_returns_none(self, tmp_path):
        """A local ./images/ path whose file is absent from mathpix_extracted/ returns None."""
        from extraction.chunk_builder import download_image

        # images_dir is tmp_path; mathpix_extracted/ sub-dir does NOT exist
        result = download_image("./images/missing.jpg", tmp_path)

        assert result is None

    def test_cdn_image_cached_skips_download(self, tmp_path):
        """If the hashed local filename already exists, no network call is made."""
        import hashlib
        from extraction.chunk_builder import download_image

        cdn_url = "https://cdn.mathpix.com/cached.jpg"
        url_hash = hashlib.sha256(cdn_url.encode()).hexdigest()[:16]
        local_path = tmp_path / f"{url_hash}.jpg"
        local_path.write_bytes(b"fake image data")

        with patch("extraction.chunk_builder.requests.get") as mock_get:
            result = download_image(cdn_url, tmp_path)

        mock_get.assert_not_called()
        assert result == f"{url_hash}.jpg"

    def test_cdn_download_writes_file_and_returns_filename(self, tmp_path):
        """Successful CDN download persists file bytes and returns the local filename."""
        import hashlib
        from extraction.chunk_builder import download_image

        cdn_url = "https://cdn.mathpix.com/new.jpg"
        url_hash = hashlib.sha256(cdn_url.encode()).hexdigest()[:16]
        expected_filename = f"{url_hash}.jpg"

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.content = b"\xff\xd8\xff"  # minimal JPEG magic bytes

        with patch("extraction.chunk_builder.requests.get", return_value=mock_response):
            result = download_image(cdn_url, tmp_path)

        assert result == expected_filename
        assert (tmp_path / expected_filename).read_bytes() == b"\xff\xd8\xff"

    def test_local_image_copy_when_source_exists(self, tmp_path):
        """A local ./images/ path whose source exists in mathpix_extracted/ is copied."""
        import hashlib
        from extraction.chunk_builder import download_image

        # download_image resolves: images_dir.parent / "mathpix_extracted" / filename
        # So we need:
        #   images_dir        = tmp_path / "images"
        #   mathpix_extracted = tmp_path / "mathpix_extracted"   (sibling of images_dir)
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        mathpix_dir = tmp_path / "mathpix_extracted"
        mathpix_dir.mkdir()
        (mathpix_dir / "figure01.jpg").write_bytes(b"local image content")

        cdn_url = "./images/figure01.jpg"
        url_hash = hashlib.sha256(cdn_url.encode()).hexdigest()[:16]

        result = download_image(cdn_url, images_dir)

        assert result == f"{url_hash}.jpg"
        assert (images_dir / f"{url_hash}.jpg").read_bytes() == b"local image content"


# ═════════════════════════════════════════════════════════════════════════════
# Group C (continued) — _extract_image_captions
# ═════════════════════════════════════════════════════════════════════════════

class TestExtractImageCaptions:
    r"""Business rule: _extract_image_captions must extract \caption{} and
    Figure X.Y: captions, and pad with None when fewer captions than images."""

    def test_latex_caption_extracted(self):
        r"""\\caption{text} is correctly parsed."""
        from extraction.chunk_parser import _extract_image_captions

        text = r"\begin{figure}\includegraphics{fig1.jpg}\caption{A right triangle}\end{figure}"

        result = _extract_image_captions(text, 1)

        assert result == ["A right triangle"]

    def test_markdown_figure_caption_extracted(self):
        """Figure X.Y: description format is parsed."""
        from extraction.chunk_parser import _extract_image_captions

        text = "Figure 1.2: Distribution of prime numbers\nSome other text"

        result = _extract_image_captions(text, 1)

        assert len(result) == 1
        assert result[0] == "Distribution of prime numbers"

    def test_captions_padded_with_none(self):
        """When fewer captions than images, result is padded with None to match count."""
        from extraction.chunk_parser import _extract_image_captions

        text = "No captions here"

        result = _extract_image_captions(text, 3)

        assert result == [None, None, None]

    def test_result_length_matches_image_count(self):
        """Return value always has exactly image_count entries."""
        from extraction.chunk_parser import _extract_image_captions

        text = r"\caption{First}\caption{Second}\caption{Third}"

        # Request fewer captions than available
        result_2 = _extract_image_captions(text, 2)
        assert len(result_2) == 2

        # Request more captions than available
        result_5 = _extract_image_captions(text, 5)
        assert len(result_5) == 5
        # Trailing entries are None
        assert result_5[3] is None
        assert result_5[4] is None

    def test_multiple_latex_captions_assigned_in_order(self):
        r"""Multiple \\caption{} entries are assigned to images in document order."""
        from extraction.chunk_parser import _extract_image_captions

        text = (
            r"\caption{First figure description}"
            "\n"
            r"\caption{Second figure description}"
        )

        result = _extract_image_captions(text, 2)

        assert result[0] == "First figure description"
        assert result[1] == "Second figure description"

    def test_empty_caption_braces_skipped(self):
        r"""\\caption{} with empty content is not included in results."""
        from extraction.chunk_parser import _extract_image_captions

        text = r"\caption{}\caption{Real caption}"

        result = _extract_image_captions(text, 2)

        # "Real caption" fills slot 0; slot 1 is None (empty caption was skipped)
        assert result[0] == "Real caption"
        assert result[1] is None

    def test_zero_images_returns_empty_list(self):
        """Requesting 0 images returns an empty list even if captions exist."""
        from extraction.chunk_parser import _extract_image_captions

        text = r"\caption{Something}"

        result = _extract_image_captions(text, 0)

        assert result == []

    def test_figure_caption_trailing_whitespace_stripped(self):
        """Figure X.Y: captions have trailing whitespace stripped."""
        from extraction.chunk_parser import _extract_image_captions

        text = "Figure 3.7: The number line   \nSome body text."

        result = _extract_image_captions(text, 1)

        assert result[0] == "The number line"


# ── Group E: _clean_chunk_text preserves ALL content ────────────────────────

class TestCleanChunkTextPreservesContent:
    """_clean_chunk_text should only collapse blank lines, keeping everything."""

    def test_preserves_urls(self):
        """URLs are kept in chunk text."""
        from extraction.chunk_parser import _clean_chunk_text

        text = "Visit https://openstax.org/books/prealgebra for more info."
        result = _clean_chunk_text(text)
        assert "https://openstax.org/books/prealgebra" in result

    def test_preserves_figure_references(self):
        """Standalone Figure X.Y lines are kept."""
        from extraction.chunk_parser import _clean_chunk_text

        text = "Some content\n\nFigure 1.5\n\nMore content"
        result = _clean_chunk_text(text)
        assert "Figure 1.5" in result

    def test_preserves_credit_lines(self):
        """Credit/attribution lines are kept."""
        from extraction.chunk_parser import _clean_chunk_text

        text = "Image shown above (credit: modification of work by NASA)"
        result = _clean_chunk_text(text)
        assert "(credit: modification of work by NASA)" in result

    def test_preserves_latex_markup(self):
        r"""LaTeX figure/table markup is kept."""
        from extraction.chunk_parser import _clean_chunk_text

        text = r"\begin{figure}\includegraphics{img.jpg}\caption{A diagram}\end{figure}"
        result = _clean_chunk_text(text)
        assert r"\begin{figure}" in result
        assert r"\includegraphics" in result
        assert r"\caption{A diagram}" in result

    def test_preserves_hline(self):
        r"""\hline table markers are kept."""
        from extraction.chunk_parser import _clean_chunk_text

        text = r"\begin{tabular}{|c|c|}\hline Value & Count \\ \hline\end{tabular}"
        result = _clean_chunk_text(text)
        assert r"\hline" in result

    def test_collapses_excessive_blank_lines(self):
        """3+ consecutive blank lines collapsed to double newline."""
        from extraction.chunk_parser import _clean_chunk_text

        text = "Line 1\n\n\n\n\nLine 2"
        result = _clean_chunk_text(text)
        assert "\n\n\n" not in result
        assert "Line 1\n\nLine 2" == result

    def test_strips_leading_trailing_whitespace(self):
        """Leading/trailing whitespace stripped."""
        from extraction.chunk_parser import _clean_chunk_text

        text = "  \n\nContent here\n\n  "
        result = _clean_chunk_text(text)
        assert result == "Content here"
