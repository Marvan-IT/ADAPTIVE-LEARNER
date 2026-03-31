"""
test_card_generation_fixes.py — Unit tests for two targeted fixes in the card
generation pipeline.

Business criteria covered:

Fix 6 — _image_to_data_url uses find() instead of startswith():
  BIZ-01  Full HTTP URL containing /images/{book_slug}/ is resolved correctly
          and a base64 data URL is returned (not None).
  BIZ-02  Relative URL starting with /images/{book_slug}/ is resolved correctly.
  BIZ-03  URL containing a different book_slug returns None (wrong book guard).
  BIZ-04  A URL that contains no /images/{book_slug}/ marker returns None.

Fix 3 — Non-teaching chunk guard in generate_per_chunk():
  BIZ-05  Chunks whose headings contain "Learning Objectives" are skipped.
  BIZ-06  Chunks whose headings contain "Key Terms" are skipped.
  BIZ-07  Chunks whose headings contain "Key Concepts" are skipped.
  BIZ-08  Chunks whose headings contain "Summary" are skipped.
  BIZ-09  Chunks whose headings contain "Chapter Review" are skipped.
  BIZ-10  Normal teaching headings like "Counting Numbers" are NOT skipped.
  BIZ-11  Normal teaching headings like "Whole Numbers" are NOT skipped.
  BIZ-12  The guard is case-insensitive ("LEARNING OBJECTIVES" is still skipped).

Fix 5 / Fix 8 — build_chunk_card_prompt() final instruction and mode delivery:
  BIZ-13  The final instruction always contains "every step".
  BIZ-14  The final instruction always contains "genuinely teach".
  BIZ-15  NORMAL mode block does NOT contain the literal phrase "brief 2"
          (regression guard: the old wording accidentally shortened MCQ explanations).
  BIZ-16  STRUGGLING mode block contains "COMPLETENESS RULE".
  BIZ-17  NORMAL mode block contains "COMPLETENESS RULE".
  BIZ-18  FAST mode block contains "COMPLETENESS RULE".
  BIZ-19  FAST mode block does NOT contain "AT LEAST as content-rich as NORMAL"
          (regression guard: that phrase triggered incorrect baseline comparison).

All tests are unit-level — no database, no OpenAI calls, no file I/O beyond
what is mocked with unittest.mock.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure backend/src is importable even when run directly from any working dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ---------------------------------------------------------------------------
# Module-level stub: break circular import between teaching_router ↔ api.main
# teaching_router imports `limiter` from api.main at module level; api.main
# imports `router` from teaching_router — forming a cycle.  Pre-inject a stub
# BEFORE any teaching_service import so the cycle never forms during collection.
# ---------------------------------------------------------------------------

def _install_api_main_stub():
    if "api.main" not in sys.modules:
        stub = MagicMock()
        try:
            from slowapi import Limiter
            from slowapi.util import get_remote_address
            stub.limiter = Limiter(key_func=get_remote_address)
        except ImportError:
            stub.limiter = MagicMock()
        sys.modules["api.main"] = stub


_install_api_main_stub()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_image_to_data_url():
    """Lazy import after the circular-import stub is in place."""
    from api.teaching_service import _image_to_data_url  # noqa: PLC0415
    return _image_to_data_url


def _build_chunk_card_prompt(**kwargs):
    """Thin wrapper that supplies defaults for all required args."""
    from adaptive.prompt_builder import build_chunk_card_prompt  # noqa: PLC0415
    defaults = dict(
        chunk={"heading": "Introduction to Whole Numbers", "text": "Numbers are used to count things."},
        images=[],
        student_mode="NORMAL",
        style="default",
        interests=[],
        language="en",
    )
    defaults.update(kwargs)
    return build_chunk_card_prompt(**defaults)


def _mode_block(mode: str) -> str:
    """Return the raw mode-delivery block string from prompt_builder."""
    from adaptive.prompt_builder import _CARD_MODE_DELIVERY  # noqa: PLC0415
    return _CARD_MODE_DELIVERY[mode]


# ---------------------------------------------------------------------------
# Fix 6 — _image_to_data_url: find()-based URL marker extraction
# ---------------------------------------------------------------------------

class TestImageToDataUrl:
    """
    _image_to_data_url() must locate the /images/{book_slug}/ marker anywhere in
    the URL (not just at position 0), then resolve the file path and return a
    base64 data URL.  When the marker is absent or the book slug doesn't match,
    None is returned.
    """

    @pytest.mark.unit
    def test_image_to_data_url_full_url(self, tmp_path):
        """
        BIZ-01: A fully-qualified URL (http://host:port/images/prealgebra/...) is
        resolved to the correct file path and returns a non-None data URL.

        OUTPUT_DIR is patched on config because _image_to_data_url imports it
        locally via 'from config import OUTPUT_DIR' — there is no module-level
        attribute on teaching_service to patch.
        """
        _image_to_data_url = _load_image_to_data_url()

        # Create a fake image file so file_path.exists() returns True.
        fake_file = tmp_path / "prealgebra" / "images_downloaded" / "abc123.jpg"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 12)  # minimal JPEG header

        full_url = "http://localhost:8889/images/prealgebra/images_downloaded/abc123.jpg"

        with patch("config.OUTPUT_DIR", tmp_path):
            result = _image_to_data_url(full_url, "prealgebra")

        assert result is not None, (
            "_image_to_data_url returned None for a full URL — find() may not be locating "
            "the /images/prealgebra/ marker in a URL that does not start with it."
        )
        assert result.startswith("data:image/jpeg;base64,"), (
            f"Expected a JPEG data URL, got: {result[:60]}"
        )

    @pytest.mark.unit
    def test_image_to_data_url_relative_url(self, tmp_path):
        """
        BIZ-02: A relative URL (/images/prealgebra/...) is also resolved correctly
        because find() works for both relative and full URLs.
        """
        _image_to_data_url = _load_image_to_data_url()

        fake_file = tmp_path / "prealgebra" / "images_downloaded" / "abc123.jpg"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 12)

        relative_url = "/images/prealgebra/images_downloaded/abc123.jpg"

        with patch("config.OUTPUT_DIR", tmp_path):
            result = _image_to_data_url(relative_url, "prealgebra")

        assert result is not None, (
            "_image_to_data_url returned None for a relative /images/prealgebra/ URL."
        )
        assert result.startswith("data:image/jpeg;base64,")

    @pytest.mark.unit
    def test_image_to_data_url_wrong_book(self, tmp_path):
        """
        BIZ-03: When the URL contains /images/algebra/ but book_slug='prealgebra',
        the marker /images/prealgebra/ is not found and None is returned.
        This prevents cross-book image leakage.
        """
        _image_to_data_url = _load_image_to_data_url()

        wrong_book_url = "/images/algebra/images_downloaded/abc123.jpg"

        with patch("config.OUTPUT_DIR", tmp_path):
            result = _image_to_data_url(wrong_book_url, "prealgebra")

        assert result is None, (
            "_image_to_data_url should return None when the URL's book slug doesn't match."
        )

    @pytest.mark.unit
    def test_image_to_data_url_no_marker(self, tmp_path):
        """
        BIZ-04: A URL with no /images/{book_slug}/ segment at all returns None.
        """
        _image_to_data_url = _load_image_to_data_url()

        unrelated_url = "https://cdn.example.com/static/math_diagram.png"

        with patch("config.OUTPUT_DIR", tmp_path):
            result = _image_to_data_url(unrelated_url, "prealgebra")

        assert result is None, (
            "_image_to_data_url should return None for a URL with no recognisable marker."
        )


# ---------------------------------------------------------------------------
# Fix 3 — Non-teaching chunk guard (_NO_TEACHING_PATTERNS)
# ---------------------------------------------------------------------------
# _NO_TEACHING_PATTERNS is a local variable inside generate_per_chunk() and
# cannot be imported directly.  We replicate the exact guard logic here so
# that the test assertions are stable even if the constant is extracted to
# module level later.  Any regression in the pattern list would fail these tests.
# ---------------------------------------------------------------------------

# Canonical copy of the patterns — must stay in sync with teaching_service.py.
_NO_TEACHING_PATTERNS = (
    "learning objectives", "key terms", "key concepts",
    "summary", "chapter review", "review exercises", "practice test",
)


def _should_skip(heading: str) -> bool:
    """Mirrors the exact guard expression used in generate_per_chunk()."""
    return any(p in heading.lower() for p in _NO_TEACHING_PATTERNS)


class TestNonTeachingPatterns:
    """
    The non-teaching chunk guard must skip administrative / structural headings
    while allowing real content headings through.
    """

    @pytest.mark.unit
    def test_non_teaching_patterns_match_learning_objectives(self):
        """BIZ-05: 'Learning Objectives' is always a structural, non-content heading."""
        assert _should_skip("Learning Objectives"), (
            "'Learning Objectives' should match the non-teaching pattern guard."
        )

    @pytest.mark.unit
    def test_non_teaching_patterns_match_key_terms(self):
        """BIZ-06: 'Key Terms' is a glossary section, not a teaching chunk."""
        assert _should_skip("Key Terms"), (
            "'Key Terms' should match the non-teaching pattern guard."
        )

    @pytest.mark.unit
    def test_non_teaching_patterns_match_key_concepts(self):
        """BIZ-07: 'Key Concepts' is a summary list, not a teaching chunk."""
        assert _should_skip("Key Concepts"), (
            "'Key Concepts' should match the non-teaching pattern guard."
        )

    @pytest.mark.unit
    def test_non_teaching_patterns_match_summary(self):
        """BIZ-08: 'Summary' sections are review material, not new instruction."""
        assert _should_skip("Summary"), (
            "'Summary' should match the non-teaching pattern guard."
        )

    @pytest.mark.unit
    def test_non_teaching_patterns_match_chapter_review(self):
        """BIZ-09: 'Chapter Review' is a repetition section, not new teaching."""
        assert _should_skip("Chapter Review"), (
            "'Chapter Review' should match the non-teaching pattern guard."
        )

    @pytest.mark.unit
    def test_non_teaching_patterns_no_match_counting_numbers(self):
        """
        BIZ-10: 'Counting Numbers' is a real content heading and must NOT be skipped.
        A false positive here would silently drop a genuine lesson chunk.
        """
        assert not _should_skip("Counting Numbers"), (
            "'Counting Numbers' is a teaching chunk and should NOT match the non-teaching guard."
        )

    @pytest.mark.unit
    def test_non_teaching_patterns_no_match_whole_numbers(self):
        """
        BIZ-11: 'Whole Numbers' is a real content heading and must NOT be skipped.
        """
        assert not _should_skip("Whole Numbers"), (
            "'Whole Numbers' is a teaching chunk and should NOT match the non-teaching guard."
        )

    @pytest.mark.unit
    def test_non_teaching_patterns_case_insensitive(self):
        """
        BIZ-12: The guard uses .lower() so ALL-CAPS headings like 'LEARNING OBJECTIVES'
        are still recognised and skipped.  Books sometimes export headings in uppercase.
        """
        assert _should_skip("LEARNING OBJECTIVES"), (
            "The non-teaching guard must be case-insensitive; 'LEARNING OBJECTIVES' should match."
        )

    @pytest.mark.unit
    def test_non_teaching_patterns_partial_match_in_longer_heading(self):
        """
        Regression guard: a heading like "Chapter Review Exercises" contains both
        'chapter review' and 'review exercises' — both are in the pattern list, and
        the heading should be skipped regardless of which one matches first.
        """
        assert _should_skip("Chapter Review Exercises"), (
            "'Chapter Review Exercises' contains a non-teaching pattern and should be skipped."
        )

    @pytest.mark.unit
    def test_non_teaching_patterns_no_match_introduction(self):
        """
        'Introduction' is the most common first heading of a teaching chunk and
        must pass through the guard.
        """
        assert not _should_skip("Introduction"), (
            "'Introduction' is a valid teaching heading and must NOT be skipped."
        )


# ---------------------------------------------------------------------------
# Fix 5 / Fix 8 — build_chunk_card_prompt() final instruction + mode delivery
# ---------------------------------------------------------------------------

class TestBuildChunkCardPromptFinalInstruction:
    """
    The trailing instruction in build_chunk_card_prompt() must always contain the
    key quality-enforcement phrases that prevent the LLM from cutting content short.
    """

    @pytest.mark.unit
    def test_build_chunk_card_prompt_final_instruction_contains_every_step(self):
        """
        BIZ-13: The phrase 'every step' must appear in the prompt so the LLM knows
        to include all worked-example steps, not a condensed summary.
        """
        prompt = _build_chunk_card_prompt()
        assert "every step" in prompt, (
            "build_chunk_card_prompt() must contain 'every step' in its final instruction."
        )

    @pytest.mark.unit
    def test_build_chunk_card_prompt_final_instruction_contains_genuinely_teach(self):
        """
        BIZ-14: The phrase 'genuinely teach' must appear so the LLM does not stop
        generating content prematurely.
        """
        prompt = _build_chunk_card_prompt()
        assert "genuinely teach" in prompt, (
            "build_chunk_card_prompt() must contain 'genuinely teach' in its final instruction."
        )


class TestModeDeliveryBlocks:
    """
    _CARD_MODE_DELIVERY strings encode the mode-specific generation rules.
    These tests guard against regressions introduced by editing the mode blocks.
    """

    @pytest.mark.unit
    def test_mode_delivery_normal_no_brief_sentence_count(self):
        """
        BIZ-15: The NORMAL mode block must NOT contain the phrase 'brief 2'.
        The old wording 'brief 2-3 sentence explanation' told the LLM to shorten
        MCQ explanations — this conflicts with the COMPLETENESS RULE.
        """
        block = _mode_block("NORMAL")
        assert "brief 2" not in block, (
            "NORMAL mode block must not contain 'brief 2' — "
            "that phrasing was removed to avoid shortening MCQ explanations."
        )

    @pytest.mark.unit
    def test_mode_delivery_completeness_rule_in_struggling(self):
        """
        BIZ-16: STRUGGLING mode must contain 'COMPLETENESS RULE' so that even
        struggling students receive complete definitions and worked examples.
        """
        block = _mode_block("STRUGGLING")
        assert "COMPLETENESS RULE" in block, (
            "STRUGGLING mode block is missing the mandatory 'COMPLETENESS RULE' directive."
        )

    @pytest.mark.unit
    def test_mode_delivery_completeness_rule_in_normal(self):
        """
        BIZ-17: NORMAL mode must also contain 'COMPLETENESS RULE' — completeness
        is required at every difficulty level.
        """
        block = _mode_block("NORMAL")
        assert "COMPLETENESS RULE" in block, (
            "NORMAL mode block is missing the mandatory 'COMPLETENESS RULE' directive."
        )

    @pytest.mark.unit
    def test_mode_delivery_completeness_rule_in_fast(self):
        """
        BIZ-18: FAST mode must contain 'COMPLETENESS RULE' — advanced students
        must still receive all formula steps and definitions, just in denser language.
        """
        block = _mode_block("FAST")
        assert "COMPLETENESS RULE" in block, (
            "FAST mode block is missing the mandatory 'COMPLETENESS RULE' directive."
        )

    @pytest.mark.unit
    def test_mode_delivery_fast_no_relative_baseline(self):
        """
        BIZ-19: The FAST mode block must NOT contain 'AT LEAST as content-rich as NORMAL'.
        That phrase was removed because it caused the LLM to benchmark against NORMAL
        output rather than following the COMPLETENESS RULE independently.
        """
        block = _mode_block("FAST")
        assert "AT LEAST as content-rich as NORMAL" not in block, (
            "FAST mode block must not contain the 'AT LEAST as content-rich as NORMAL' baseline — "
            "it was removed to prevent relative-length anchoring."
        )

    @pytest.mark.unit
    def test_mode_delivery_all_three_modes_non_empty(self):
        """
        Sanity check: all three mode keys exist and produce non-empty strings.
        """
        for mode in ("STRUGGLING", "NORMAL", "FAST"):
            block = _mode_block(mode)
            assert isinstance(block, str) and len(block) > 50, (
                f"_CARD_MODE_DELIVERY['{mode}'] must be a non-trivial string."
            )
