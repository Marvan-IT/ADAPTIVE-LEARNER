"""
test_extraction_quality.py — Tests for 6 extraction pipeline fixes that make TOC
the ground truth for section/subsection detection.

Business criteria:
  Fix 1 + 4: parse_toc() adaptively expands to capture all entries; non-instructional
             entries (Summary, Key Terms, Exercises, etc.) are excluded.
  Fix 2:     TOC whitelist: only sections present in the TOC survive when a profile
             carries toc_sections; graceful fallback when toc_sections is empty.
  Fix 3:     _fuzzy_recover_section() respects body_start_offset — front-matter
             matches are skipped; real body matches still found; default=0 is backward-
             compatible.
  Fix 5:     "Before you get started" is classified as noise by _is_noise_heading();
             parse_book_mmd() applies corrected_headings to fix garbled OCR titles.
  Fix 6:     With a TOC whitelist, sections whose section_in_chapter exceeds
             max_sections_per_chapter are NOT dropped; without a TOC the cap
             still applies.

All tests are unit tests — no database, no LLM, no real book.mmd files required.
Synthetic MMD snippets and mock profile objects are used throughout.
"""

import sys
import re
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile

import pytest

# Ensure backend/src is on the path (mirrors existing test files)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from extraction.ocr_validator import parse_toc, TocEntry
from extraction.chunk_parser import (
    _is_noise_heading,
    _fuzzy_recover_section,
    parse_book_mmd,
    ParsedChunk,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_short_toc_mmd() -> str:
    """3-chapter TOC — fits inside the initial 2 000-char window without expansion."""
    toc_block = (
        "# Prealgebra\n\n"
        "## Table of Contents\n\n"
        "1.1 Introduction to Whole Numbers\n"
        "1.2 Add Whole Numbers\n"
        "1.3 Subtract Whole Numbers\n"
        "2.1 Use the Language of Algebra\n"
        "2.2 Evaluate, Simplify, and Translate Expressions\n"
        "3.1 Introduction to Fractions\n"
        "3.2 Multiply and Divide Fractions\n"
        "3.3 Multiply and Divide Mixed Numbers\n\n"
    )
    # Pad with body text so the front-20% limit still contains the TOC
    body = "\n\n".join(
        [
            f"### {ch}.{sec} Section Title\n\n"
            + " ".join(["word"] * 200)
            for ch in range(1, 4)
            for sec in range(1, 4)
        ]
    )
    return toc_block + body


def _make_long_toc_mmd(n_chapters: int = 13, sections_per_chapter: int = 6) -> str:
    """
    Build a synthetic MMD whose TOC spans many chapters and exceeds the 2 000-char
    initial window.  Triggers the adaptive expansion path (Fix 1).
    """
    lines = ["# Big Textbook\n\n## Table of Contents\n\n"]
    for ch in range(1, n_chapters + 1):
        for sec in range(1, sections_per_chapter + 1):
            lines.append(f"{ch}.{sec} Section {ch} Dot {sec}\n")
    toc_block = "".join(lines) + "\n\n"
    # Body text (real sections)
    body_parts = []
    for ch in range(1, n_chapters + 1):
        for sec in range(1, sections_per_chapter + 1):
            body_parts.append(
                f"### {ch}.{sec} Section {ch} Dot {sec}\n\n"
                + " ".join(["word"] * 300)
            )
    return toc_block + "\n\n".join(body_parts)


def _make_toc_with_non_instructional() -> str:
    """TOC that contains Summary, Key Terms, and Exercises alongside real sections."""
    return (
        "# College Algebra\n\n## Table of Contents\n\n"
        "1.1 Real Numbers\n"
        "1.2 Exponents and Scientific Notation\n"
        "1.1 Summary\n"            # non-instructional — same number, different title
        "1.2 Key Terms\n"
        "2.1 Exercises\n"
        "2.2 Linear Equations\n"
        "2.3 Quadratic Equations\n"
        "3.1 References\n"
        "3.2 Answer Key\n"
        "3.3 Polynomial Functions\n\n"
        + " ".join(["word"] * 3000)   # padding so 20% limit includes the whole TOC
    )


@dataclass
class _BookProfile:
    """Minimal stub of BookProfile — only the fields that chunk_parser reads."""
    book_slug: str = "testbook"
    subject: str = "mathematics"
    toc_sections: list = field(default_factory=list)
    subsection_signals: list = field(default_factory=list)
    feature_box_patterns: list = field(default_factory=list)
    noise_patterns: list = field(default_factory=list)
    exercise_markers: list = field(default_factory=list)
    min_chunk_words: int = 5
    max_chunk_words: int = 5000
    max_sections_per_chapter: int = 10
    back_matter_markers: list = field(default_factory=list)
    boilerplate_patterns: list = field(default_factory=list)
    corrected_headings: dict = field(default_factory=dict)


def _toc_entry(section_number: str, title: str = "Section Title", chapter: int = 1) -> dict:
    """Dict form of a TOC entry as stored in BookProfile.toc_sections."""
    return {"section_number": section_number, "title": title, "chapter": chapter}


# ---------------------------------------------------------------------------
# Fix 1 + Fix 4: TOC Parsing
# ---------------------------------------------------------------------------

class TestParseTocShort:
    """parse_toc() captures all entries from a short, compact TOC."""

    def test_returns_list_of_toc_entries(self):
        mmd = _make_short_toc_mmd()
        entries = parse_toc(mmd)
        assert isinstance(entries, list)
        assert all(isinstance(e, TocEntry) for e in entries)

    def test_all_instructional_sections_captured(self):
        mmd = _make_short_toc_mmd()
        entries = parse_toc(mmd)
        numbers = {e.section_number for e in entries}
        expected = {"1.1", "1.2", "1.3", "2.1", "2.2", "3.1", "3.2", "3.3"}
        assert expected.issubset(numbers), (
            f"Missing sections: {expected - numbers}"
        )

    def test_section_titles_are_populated(self):
        mmd = _make_short_toc_mmd()
        entries = parse_toc(mmd)
        for entry in entries:
            assert entry.title, f"Empty title for section {entry.section_number}"

    def test_chapter_field_matches_section_number(self):
        mmd = _make_short_toc_mmd()
        entries = parse_toc(mmd)
        for entry in entries:
            chapter_from_number = int(entry.section_number.split(".")[0])
            assert entry.chapter == chapter_from_number


class TestParseTocLong:
    """parse_toc() adaptively expands to capture large TOCs (Fix 1)."""

    def test_all_chapters_captured_in_long_toc(self):
        n_chapters = 13
        sections_per = 5
        mmd = _make_long_toc_mmd(n_chapters=n_chapters, sections_per_chapter=sections_per)
        entries = parse_toc(mmd)
        numbers = {e.section_number for e in entries}
        # Verify first and last chapter's first section are both present
        assert "1.1" in numbers, "First section of chapter 1 missing"
        assert f"{n_chapters}.1" in numbers, f"First section of chapter {n_chapters} missing"

    def test_total_count_matches_toc_size(self):
        n_chapters = 11
        sections_per = 6
        mmd = _make_long_toc_mmd(n_chapters=n_chapters, sections_per_chapter=sections_per)
        entries = parse_toc(mmd)
        # Each (chapter, section) pair should appear exactly once
        expected_count = n_chapters * sections_per
        assert len(entries) >= expected_count * 0.9, (
            f"Only {len(entries)} entries, expected ~{expected_count}"
        )

    def test_no_duplicate_section_numbers(self):
        mmd = _make_long_toc_mmd()
        entries = parse_toc(mmd)
        numbers = [e.section_number for e in entries]
        assert len(numbers) == len(set(numbers)), "Duplicate section numbers in parsed TOC"


class TestParseTocNonInstructional:
    """Non-instructional TOC entries (Summary, Key Terms, Exercises, etc.) are excluded (Fix 4)."""

    def test_summary_entry_is_excluded(self):
        mmd = _make_toc_with_non_instructional()
        entries = parse_toc(mmd)
        titles = {e.title.lower() for e in entries}
        assert "summary" not in titles

    def test_key_terms_entry_is_excluded(self):
        mmd = _make_toc_with_non_instructional()
        entries = parse_toc(mmd)
        titles = {e.title.lower() for e in entries}
        assert "key terms" not in titles

    def test_exercises_entry_is_excluded(self):
        mmd = _make_toc_with_non_instructional()
        entries = parse_toc(mmd)
        titles = {e.title.lower() for e in entries}
        assert "exercises" not in titles

    def test_references_entry_is_excluded(self):
        mmd = _make_toc_with_non_instructional()
        entries = parse_toc(mmd)
        titles = {e.title.lower() for e in entries}
        assert "references" not in titles

    def test_answer_key_entry_is_excluded(self):
        mmd = _make_toc_with_non_instructional()
        entries = parse_toc(mmd)
        titles = {e.title.lower() for e in entries}
        assert "answer key" not in titles

    def test_real_sections_still_present_after_filtering(self):
        mmd = _make_toc_with_non_instructional()
        entries = parse_toc(mmd)
        numbers = {e.section_number for e in entries}
        assert "1.1" in numbers
        assert "2.2" in numbers
        assert "3.3" in numbers

    def test_empty_input_returns_empty_list(self):
        assert parse_toc("") == []

    def test_none_equivalent_short_text_returns_empty_list(self):
        # Text too short to contain a real TOC
        assert parse_toc("Hello world") == []


# ---------------------------------------------------------------------------
# Fix 2: TOC Whitelist
# ---------------------------------------------------------------------------

def _build_mmd_with_fake_sections() -> str:
    """
    MMD whose regex would match both real sections (1.1, 1.2) and fake sections
    (2.10 — exercise number) that should be rejected by the TOC whitelist.
    """
    real_body = (
        "### 1.1 Real Section One\n\n"
        + " ".join(["word"] * 200) + "\n\n"
        "## Identify Whole Numbers\n\n"
        + " ".join(["word"] * 200) + "\n\n"
        "### 1.2 Real Section Two\n\n"
        + " ".join(["word"] * 200) + "\n\n"
        "## Add Numbers\n\n"
        + " ".join(["word"] * 200) + "\n\n"
        # Fake section — exercise number, NOT in TOC
        "### 2.10 Write each expression in standard form\n\n"
        + " ".join(["word"] * 200) + "\n\n"
        "### 2.1 Real Section of Chapter Two\n\n"
        + " ".join(["word"] * 200) + "\n\n"
    )
    return real_body


class TestTocWhitelist:
    """With a TOC, only TOC sections survive; without a TOC all sections pass (Fix 2)."""

    def _run_parse_with_profile(self, mmd_text: str, profile: _BookProfile) -> list[ParsedChunk]:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".mmd", delete=False, encoding="utf-8"
        ) as f:
            f.write(mmd_text)
            tmp_path = Path(f.name)
        try:
            return parse_book_mmd(tmp_path, profile.book_slug, profile=profile)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_fake_section_dropped_when_toc_present(self):
        mmd = _build_mmd_with_fake_sections()
        profile = _BookProfile(
            book_slug="testbook",
            toc_sections=[
                _toc_entry("1.1", "Real Section One", chapter=1),
                _toc_entry("1.2", "Real Section Two", chapter=1),
                _toc_entry("2.1", "Real Section of Chapter Two", chapter=2),
            ],
            max_sections_per_chapter=15,  # deliberately high to prove TOC, not cap, is the filter
        )
        chunks = self._run_parse_with_profile(mmd, profile)
        concept_ids = {c.concept_id for c in chunks}
        # The fake section 2.10 must NOT appear
        assert "testbook_2.10" not in concept_ids, (
            "Fake section 2.10 survived the TOC whitelist — it should have been dropped"
        )

    def test_real_toc_sections_are_kept_when_toc_present(self):
        mmd = _build_mmd_with_fake_sections()
        profile = _BookProfile(
            book_slug="testbook",
            toc_sections=[
                _toc_entry("1.1", "Real Section One", chapter=1),
                _toc_entry("1.2", "Real Section Two", chapter=1),
                _toc_entry("2.1", "Real Section of Chapter Two", chapter=2),
            ],
            max_sections_per_chapter=15,
        )
        chunks = self._run_parse_with_profile(mmd, profile)
        concept_ids = {c.concept_id for c in chunks}
        assert "testbook_1.1" in concept_ids
        assert "testbook_1.2" in concept_ids

    def test_all_sections_pass_when_no_toc(self):
        """Without a TOC, the whitelist is not applied — sections are not rejected."""
        mmd = _build_mmd_with_fake_sections()
        # max_sections_per_chapter=15 so the cap won't drop 2.10 either
        profile = _BookProfile(
            book_slug="testbook",
            toc_sections=[],   # empty → no whitelist
            max_sections_per_chapter=15,
        )
        chunks = self._run_parse_with_profile(mmd, profile)
        concept_ids = {c.concept_id for c in chunks}
        # All regex-matched sections should survive
        assert "testbook_1.1" in concept_ids
        assert "testbook_1.2" in concept_ids


# ---------------------------------------------------------------------------
# Fix 3: Body-Only Recovery
# ---------------------------------------------------------------------------

class TestFuzzyRecoverSection:
    """_fuzzy_recover_section respects body_start_offset to skip front matter (Fix 3)."""

    # Shared synthetic MMD:
    # Front matter contains "1.1" at offset ~0 (e.g. in the TOC)
    # Body contains the real "1.1" section heading well past offset 500
    _FRONT_MATTER_MARKER = "1.1 Introduction to Whole Numbers"
    _BODY_MARKER = "### 1.1 Introduction to Whole Numbers"

    def _build_mmd_with_front_matter_match(self) -> tuple[str, int]:
        """
        Returns (mmd_text, body_start) where body_start is the char offset where
        the real body begins.  The same section number appears in the front matter
        (at offset < body_start) and in the body.
        """
        front_matter = (
            "# Prealgebra\n\n"
            "## Table of Contents\n\n"
            + self._FRONT_MATTER_MARKER + "\n"  # TOC listing — must be skipped
            + "1.2 Add Whole Numbers\n\n"
            + "## Preface\n\n"
            + "Some preface text about the book.\n\n"
        )
        body_marker_text = (
            self._BODY_MARKER + "\n\n"
            + " ".join(["word"] * 300) + "\n\n"
        )
        body_start = len(front_matter)
        return front_matter + body_marker_text, body_start

    def test_front_matter_match_is_skipped_with_offset(self):
        mmd, body_start = self._build_mmd_with_front_matter_match()
        # Supply a body_start_offset that excludes the TOC listing in front matter
        result = _fuzzy_recover_section(
            "1.1",
            "Introduction to Whole Numbers",
            mmd,
            chapter_boundaries={1: body_start},
            body_start_offset=body_start,
        )
        # Should find the body heading, not the TOC entry
        assert result is not None
        assert result["start"] >= body_start, (
            f"Recovery returned offset {result['start']}, which is inside front matter "
            f"(body starts at {body_start})"
        )

    def test_recovery_finds_section_after_body_start(self):
        mmd, body_start = self._build_mmd_with_front_matter_match()
        result = _fuzzy_recover_section(
            "1.1",
            "Introduction to Whole Numbers",
            mmd,
            chapter_boundaries={1: body_start},
            body_start_offset=body_start,
        )
        assert result is not None, "Should recover the real body section"
        assert result["section_number"] == "1.1"
        assert result["section_title"] == "Introduction to Whole Numbers"

    def test_default_offset_zero_does_not_skip_anything(self):
        """body_start_offset=0 is the default — preserves backward compatibility."""
        mmd, body_start = self._build_mmd_with_front_matter_match()
        result = _fuzzy_recover_section(
            "1.1",
            "Introduction to Whole Numbers",
            mmd,
            chapter_boundaries={1: body_start},
            # No body_start_offset — defaults to 0
        )
        # With offset=0 the first match (TOC line) is accepted
        assert result is not None, "Default offset=0 must still find a match"
        # The match position should be in the front matter (before body_start)
        # because the bare number "1.1" appears there first
        assert result["start"] < body_start, (
            "Expected the TOC (front matter) match to be returned when offset=0"
        )

    def test_no_match_returns_none(self):
        mmd = "# Book\n\n## Chapter 1\n\nSome text with no section numbers.\n"
        result = _fuzzy_recover_section(
            "5.5",
            "Nonexistent Section",
            mmd,
            chapter_boundaries={},
        )
        assert result is None

    def test_recovery_via_fuzzy_title_after_offset(self):
        """Strategy 2 (fuzzy title match) also respects body_start_offset."""
        front = "# Book\n\n" + "x" * 400 + "\n\n"
        body = "## Intrduction to Whole Numbers\n\n" + " ".join(["word"] * 100)
        body_start = len(front)
        mmd = front + body
        result = _fuzzy_recover_section(
            "1.1",
            "Introduction to Whole Numbers",
            mmd,
            chapter_boundaries={1: body_start},
            body_start_offset=body_start,
        )
        # The fuzzy title should match "Intrduction to Whole Numbers"
        assert result is not None
        assert result["start"] >= body_start


# ---------------------------------------------------------------------------
# Fix 5: Noise Pattern + OCR Corrections
# ---------------------------------------------------------------------------

class TestBeforeYouGetStartedNoise:
    """'Before you get started' is classified as noise (Fix 5A)."""

    def test_exact_phrase_is_noise(self):
        assert _is_noise_heading("Before you get started, take this readiness quiz") is True

    def test_case_insensitive_match(self):
        assert _is_noise_heading("BEFORE YOU GET STARTED") is True
        assert _is_noise_heading("before you get started") is True

    def test_partial_match_at_start_is_noise(self):
        # The pattern uses re.IGNORECASE and anchors to start, but not end
        assert _is_noise_heading("Before you get started with this chapter") is True

    def test_phrase_not_at_start_is_not_noise(self):
        # "Before" must appear at the beginning of the heading
        assert _is_noise_heading("Review: Before you get started") is False

    def test_unrelated_heading_is_not_noise(self):
        assert _is_noise_heading("Identify Whole Numbers") is False
        assert _is_noise_heading("Use Place Value with Whole Numbers") is False


class TestOcrCorrectedHeadings:
    """parse_book_mmd() applies corrected_headings to fix garbled OCR titles (Fix 5B)."""

    def _run_parse_no_profile(
        self,
        mmd_text: str,
        book_slug: str = "testbook",
        corrected_headings: dict | None = None,
    ) -> list[ParsedChunk]:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".mmd", delete=False, encoding="utf-8"
        ) as f:
            f.write(mmd_text)
            tmp_path = Path(f.name)
        try:
            return parse_book_mmd(tmp_path, book_slug, corrected_headings=corrected_headings)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _make_garbled_mmd(self) -> str:
        """MMD with a garbled section title 'Lanquage of Algebra'."""
        return (
            "### 1.1 Introduction to Algebra\n\n"
            + " ".join(["word"] * 100) + "\n\n"
            "## Identify Variables\n\n"
            + " ".join(["word"] * 100) + "\n\n"
            "### 2.1 Lanquage of Algebra\n\n"   # garbled: Lanquage instead of Language
            + " ".join(["word"] * 100) + "\n\n"
            "## Evaluate Expressions\n\n"
            + " ".join(["word"] * 100) + "\n\n"
        )

    def test_garbled_title_corrected_in_chunk_section_label(self):
        mmd = self._make_garbled_mmd()
        corrections = {"Lanquage of Algebra": "Language of Algebra"}
        chunks = self._run_parse_no_profile(mmd, corrected_headings=corrections)
        section_labels = [c.section for c in chunks]
        # The section label for 2.1 must use the corrected title
        assert any("Language of Algebra" in lbl for lbl in section_labels), (
            f"Corrected title not found in section labels: {section_labels}"
        )

    def test_garbled_title_absent_without_correction(self):
        mmd = self._make_garbled_mmd()
        chunks = self._run_parse_no_profile(mmd, corrected_headings=None)
        section_labels = [c.section for c in chunks]
        # Without correction, the garbled title remains
        assert any("Lanquage" in lbl for lbl in section_labels), (
            "Expected garbled 'Lanquage' to appear when no correction provided"
        )

    def test_uncorrected_sections_unaffected(self):
        mmd = self._make_garbled_mmd()
        corrections = {"Lanquage of Algebra": "Language of Algebra"}
        chunks = self._run_parse_no_profile(mmd, corrected_headings=corrections)
        section_labels = [c.section for c in chunks]
        # Section 1.1 should be unchanged
        assert any("Introduction to Algebra" in lbl for lbl in section_labels)

    def test_empty_corrections_dict_is_safe(self):
        mmd = self._make_garbled_mmd()
        # Must not raise; empty dict = no corrections applied
        chunks = self._run_parse_no_profile(mmd, corrected_headings={})
        assert len(chunks) > 0


# ---------------------------------------------------------------------------
# Fix 6: Skip max_sections with TOC
# ---------------------------------------------------------------------------

class TestMaxSectionsCapWithToc:
    """
    With a TOC, sections whose section_in_chapter > max_sections_per_chapter are NOT
    dropped. Without a TOC, the cap still applies (Fix 6).
    """

    def _run_parse_with_profile(self, mmd_text: str, profile: _BookProfile) -> list[ParsedChunk]:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".mmd", delete=False, encoding="utf-8"
        ) as f:
            f.write(mmd_text)
            tmp_path = Path(f.name)
        try:
            return parse_book_mmd(tmp_path, profile.book_slug, profile=profile)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _make_high_numbered_section_mmd(self) -> str:
        """MMD with section 1.12 — above the typical cap of 10."""
        return (
            "### 1.1 First Section\n\n"
            + " ".join(["word"] * 200) + "\n\n"
            "## Subsection A\n\n"
            + " ".join(["word"] * 200) + "\n\n"
            "### 1.12 Twelfth Section\n\n"  # would be capped without TOC
            + " ".join(["word"] * 200) + "\n\n"
            "## Subsection B\n\n"
            + " ".join(["word"] * 200) + "\n\n"
        )

    def test_high_numbered_section_kept_when_in_toc(self):
        mmd = self._make_high_numbered_section_mmd()
        profile = _BookProfile(
            book_slug="nursing",
            toc_sections=[
                _toc_entry("1.1", "First Section", chapter=1),
                _toc_entry("1.12", "Twelfth Section", chapter=1),
            ],
            max_sections_per_chapter=10,  # cap would normally reject 1.12
        )
        chunks = self._run_parse_with_profile(mmd, profile)
        concept_ids = {c.concept_id for c in chunks}
        assert "nursing_1.12" in concept_ids, (
            "Section 1.12 should be kept when it is listed in the TOC, "
            "even if it exceeds max_sections_per_chapter"
        )

    def test_high_numbered_section_dropped_without_toc(self):
        mmd = self._make_high_numbered_section_mmd()
        profile = _BookProfile(
            book_slug="nursing",
            toc_sections=[],   # no TOC → cap applies
            max_sections_per_chapter=10,
        )
        chunks = self._run_parse_with_profile(mmd, profile)
        concept_ids = {c.concept_id for c in chunks}
        assert "nursing_1.12" not in concept_ids, (
            "Section 1.12 should be dropped when no TOC is present and "
            "it exceeds max_sections_per_chapter"
        )

    def test_low_numbered_section_kept_in_both_cases(self):
        """Section 1.1 (well within cap) must be present regardless of TOC."""
        mmd = self._make_high_numbered_section_mmd()
        # With TOC
        profile_with = _BookProfile(
            book_slug="nursing",
            toc_sections=[_toc_entry("1.1", "First Section", chapter=1)],
            max_sections_per_chapter=10,
        )
        chunks_with = self._run_parse_with_profile(mmd, profile_with)
        assert any(c.concept_id == "nursing_1.1" for c in chunks_with)

        # Without TOC
        profile_without = _BookProfile(
            book_slug="nursing",
            toc_sections=[],
            max_sections_per_chapter=10,
        )
        chunks_without = self._run_parse_with_profile(mmd, profile_without)
        assert any(c.concept_id == "nursing_1.1" for c in chunks_without)

    def test_section_at_exact_cap_boundary_kept_without_toc(self):
        """Section 1.10 (== max 10) must be kept even without a TOC."""
        mmd = (
            "### 1.1 First Section\n\n"
            + " ".join(["word"] * 200) + "\n\n"
            "### 1.10 Tenth Section\n\n"
            + " ".join(["word"] * 200) + "\n\n"
        )
        profile = _BookProfile(
            book_slug="testbook",
            toc_sections=[],
            max_sections_per_chapter=10,
        )
        chunks = self._run_parse_with_profile(mmd, profile)
        concept_ids = {c.concept_id for c in chunks}
        # _MAX_REAL_SECTION_IN_CHAPTER = 10 means > 10 is fake, so 10 itself is kept
        # The profile path uses profile.max_sections_per_chapter which defaults to 10;
        # section_in_chapter > 10 triggers the cap, so 1.10 (== 10) must survive.
        assert "testbook_1.10" in concept_ids, (
            "Section 1.10 should not be dropped by a cap of 10 (strict >)"
        )
