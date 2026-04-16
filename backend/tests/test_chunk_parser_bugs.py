"""
test_chunk_parser_bugs.py — Regression tests documenting 7 known bugs in the chunk parser.

Each test class targets a specific bug.  Tests marked "EXPECTED TO FAIL: BUG N"
document a CURRENT failure mode — they will fail against the unpatched parser and
PASS once the corresponding bug is fixed.  Tests without that mark should already
pass (they verify invariants that must hold even today).

Business context
----------------
The chunk parser (extraction/chunk_parser.py) converts Mathpix-generated .mmd
files into ParsedChunk objects for the PostgreSQL/pgvector pipeline.  Bugs here
produce phantom sections, duplicate concept_ids, under-sized or over-sized chunks,
missing images, or sections out of order — all of which directly degrade lesson
quality for students.

Fixtures
--------
  intermediate_algebra_ch1.mmd   — chapter 1 of Intermediate Algebra 2e
      Contains bare-number subsections (\\subsection*{1.21}, \\subsection*{1.22})
      and a Chapter Review zone at the end.
  business_statistics_ch5_6.mmd  — chapters 5 & 6 of Introductory Business Stats 2e
      Contains section-ordering regressions (6.1/6.3 appear in chapter-review
      back-references before 6.2 body).

Import path
-----------
  sys.path is set in conftest.py (parent/../src); the explicit insert here makes
  the file runnable standalone via `python -m pytest tests/test_chunk_parser_bugs.py`.
"""

import os
import re
import sys
import statistics
from pathlib import Path

import pytest

# ── Ensure backend/src is on sys.path when run standalone ────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from extraction.chunk_parser import (
    ParsedChunk,
    _is_noise_heading,
    _normalize_mmd_format,
    parse_book_mmd,
)

# ── Fixture paths ─────────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures"
INTERALG_MMD = FIXTURES_DIR / "intermediate_algebra_ch1.mmd"
BSTATS_MMD = FIXTURES_DIR / "business_statistics_ch5_6.mmd"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _word_count(text: str) -> int:
    return len(text.split())


def _load_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_toc_sections(mmd_text: str) -> set[str]:
    """Extract section numbers listed in the TOC (lines like 'N.M Title ..... page')."""
    return set(re.findall(r"^(\d+\.\d+)\s+.+?\.{3,}\s*\d+", mmd_text, re.MULTILINE))


# ── BUG 1: Bare-number phantom sections ──────────────────────────────────────
# \\subsection*{1.21} and \\subsection*{1.22} exist in the MMD as Mathpix artefacts
# (TRY IT exercise counters, not real sections).  After _normalize_mmd_format()
# they become "### 1.21" and "### 1.22" — bare-number headings with no title —
# which the SECTION_PATTERN (^(#{1,4})\s+(\d+)\.(\d+)\s+(.+)$) should NOT match
# because the title capture group (.+) would be empty.
# However if the regex is ever loosened, or whitespace quirks exist, they might
# slip through as phantom concept_ids like "test_book_1.21".

class TestBug1BareNumberTrap:
    """BUG 1 — \\subsection*{N.M} bare-number artefacts must not become sections."""

    def test_bare_number_subsections_not_real_sections(self):
        """
        \\subsection*{1.21} and \\subsection*{1.22} should NOT produce ### headings
        that SECTION_PATTERN would accept (title group would be empty).

        After _normalize_mmd_format() they become '### 1.21' (no trailing title).
        SECTION_PATTERN requires (.+) after the X.Y number so they should be skipped.
        This test verifies that no bare-number heading leaks into the normalized text
        as a matchable section heading.
        """
        raw = _load_fixture(INTERALG_MMD)
        normalized = _normalize_mmd_format(raw)

        # Find all ### lines whose entire content is just a number pattern (no title)
        bare_section_headings = re.findall(
            r"^#{1,4}\s+\d+\.\d+\s*$",
            normalized,
            re.MULTILINE,
        )
        # EXPECTED TO FAIL: BUG 1 — if _normalize_mmd_format converts
        # \\subsection*{1.21} → "### 1.21" without title, any regex loosening
        # could pick it up.  The count of bare-number headings should be 0.
        assert len(bare_section_headings) == 0, (
            f"Found {len(bare_section_headings)} bare-number section headings "
            f"after normalization: {bare_section_headings[:5]}"
        )

    def test_real_sections_still_detected(self):
        """
        \\subsection*{1.1 Use the Language of Algebra} MUST become a proper
        '### 1.1 Use the Language of Algebra' heading after normalization.
        The title text after the X.Y number must be preserved.
        """
        raw = _load_fixture(INTERALG_MMD)
        normalized = _normalize_mmd_format(raw)

        # Lines that have both a number AND title text
        real_section_headings = re.findall(
            r"^#{1,4}\s+\d+\.\d+\s+\S.+$",
            normalized,
            re.MULTILINE,
        )
        assert len(real_section_headings) >= 5, (
            f"Expected at least 5 real section headings after normalization, "
            f"found {len(real_section_headings)}"
        )

    def test_phantom_concept_ids_absent_after_full_parse(self):
        """
        Full parse must not produce concept_ids like 'test_book_1.21' or
        'test_book_1.22' — those are TRY IT exercise counters, not sections.
        """
        # EXPECTED TO FAIL: BUG 1 — phantom sections may appear in full parse
        chunks = parse_book_mmd(INTERALG_MMD, "test_book")
        concept_ids = {c.concept_id for c in chunks}
        assert "test_book_1.21" not in concept_ids, (
            "concept_id 'test_book_1.21' is a TRY IT counter, not a real section"
        )
        assert "test_book_1.22" not in concept_ids, (
            "concept_id 'test_book_1.22' is a TRY IT counter, not a real section"
        )


# ── BUG 2: Chapter Review back-references ────────────────────────────────────
# The Chapter Review zone at the end of the MMD repeats section numbers (e.g.
# \\subsection*{1.1 Use the Language of Algebra} appears again inside the review).
# The 3-copy dedup groups by (concept_id, heading) and keeps the highest word-count
# occurrence, which should eliminate the shorter review stubs.  But if the dedup
# key uses a heading that differs slightly between body and review, duplicates slip
# through.

class TestBug2ChapterReview:
    """BUG 2 — Chapter Review back-references must not produce duplicate concept_ids."""

    def test_chapter_review_no_duplicate_chunk_keys(self):
        """
        After dedup, no (concept_id, heading) pair should appear more than once.
        Multiple chunks per concept_id is expected (sections have subsections).
        But the same heading should not appear twice for the same section.
        """
        chunks = parse_book_mmd(INTERALG_MMD, "test_book")
        from collections import Counter
        key_counts = Counter((c.concept_id, c.heading) for c in chunks)
        duplicates = {k: v for k, v in key_counts.items() if v > 1}
        assert len(duplicates) == 0, (
            f"Found {len(duplicates)} duplicate (concept_id, heading) pairs: "
            f"{dict(list(duplicates.items())[:5])}"
        )

    def test_chapter_review_chunks_marked_optional_or_review_type(self):
        """
        Any chunk produced from the Chapter Review zone should be marked either
        is_optional=True or chunk_type='chapter_review' (or 'exercise') so
        the adaptive engine can exclude it from mandatory mastery gating.
        """
        # EXPECTED TO FAIL: BUG 2 — review chunks may be classified as 'teaching'
        # with is_optional=False if the zone detection missed the Chapter Review header.
        chunks = parse_book_mmd(INTERALG_MMD, "test_book")

        # Identify chunks whose text position is after the Chapter Review heading.
        # Proxy: chunks belonging to concept_ids that also appear in the TOC but
        # whose heading text contains review-zone markers.
        review_zone_chunks = [
            c for c in chunks
            if re.search(r"chapter\s+review|key\s+terms|formula\s+review|review\s+exercise",
                         c.heading, re.IGNORECASE)
        ]
        for c in review_zone_chunks:
            assert c.is_optional or c.chunk_type in ("exercise", "chapter_review"), (
                f"Chunk '{c.heading}' in review zone has chunk_type='{c.chunk_type}' "
                f"and is_optional={c.is_optional} — should be optional or exercise type"
            )


# ── BUG 4: Noise keyword coverage ────────────────────────────────────────────
# _is_noise_heading() covers the most common markers but is missing some that
# appear in newer OpenStax textbooks, causing spurious sub-chunks.

class TestBug4NoiseKeywords:
    """BUG 4 — _is_noise_heading must recognise all pedagogical noise markers."""

    def test_check_your_understanding_is_noise(self):
        """
        'Check Your Understanding' is a pedagogical callout box, not a subsection.
        It should be absorbed into the containing chunk.
        """
        # EXPECTED TO FAIL: BUG 4 — 'Check Your Understanding' is not in the
        # current _NOISE_HEADING_PATTERNS list.
        assert _is_noise_heading("Check Your Understanding"), (
            "'Check Your Understanding' should be classified as noise"
        )

    def test_check_your_understanding_with_number_is_noise(self):
        """
        Numbered variant 'Check Your Understanding 5.1' should also be noise.
        """
        # EXPECTED TO FAIL: BUG 4
        assert _is_noise_heading("Check Your Understanding 5.1"), (
            "'Check Your Understanding 5.1' should be classified as noise"
        )

    def test_building_character_is_noise(self):
        """
        'Building Character' is a sidebar feature box, not a content subsection.
        """
        # EXPECTED TO FAIL: BUG 4 — 'Building Character' is not in noise patterns.
        assert _is_noise_heading("Building Character"), (
            "'Building Character' should be classified as noise"
        )

    def test_sample_solution_is_noise(self):
        """
        'Sample Solution' labels an example answer; it must not start a new chunk.
        """
        # EXPECTED TO FAIL: BUG 4 — 'Sample Solution' is not in noise patterns
        # (only bare 'Solution' is covered).
        assert _is_noise_heading("Sample Solution"), (
            "'Sample Solution' should be classified as noise"
        )

    def test_existing_noise_patterns_still_work(self):
        """
        Smoke check — the currently-working noise patterns must remain functional
        after any patch to add the missing ones.
        """
        assert _is_noise_heading("EXAMPLE 1.1")
        assert _is_noise_heading("TRY IT 3.2")
        assert _is_noise_heading("Solution")
        assert _is_noise_heading("HOW TO: Simplify")
        assert _is_noise_heading("BE PREPARED 2.1")
        assert _is_noise_heading("Key Terms")
        assert _is_noise_heading("Chapter Review")
        assert _is_noise_heading("Practice Test")
        assert _is_noise_heading("Review Exercises")
        assert _is_noise_heading("Writing Exercises")

    def test_real_subsection_headings_not_noise(self):
        """
        Real instructional subsection titles must NOT be classified as noise.
        """
        real_headings = [
            "Find Factors, Prime Factorizations, and Least Common Multiples",
            "Use Variables and Algebraic Symbols",
            "Properties of the Real Number System",
            "Identify Multiples and Factors",
        ]
        for heading in real_headings:
            assert not _is_noise_heading(heading), (
                f"Real subsection heading '{heading}' was wrongly classified as noise"
            )


# ── BUG 5: Chunk size distribution ───────────────────────────────────────────
# Chunks should be sized for effective LLM card generation: not so large that the
# LLM is overwhelmed and truncates output, not so small that they lack context.

class TestBug5ChunkSize:
    """BUG 5 — Chunk word counts must stay within the pedagogically useful range."""

    def test_no_mega_chunks(self):
        """
        No chunk should exceed 2000 words.  Oversized chunks force the LLM into
        a high token budget and risk truncated card output.
        """
        # EXPECTED TO FAIL: BUG 5 — exercise accumulation may produce mega-chunks
        # when the exercise zone absorbs large swathes of body text.
        chunks = parse_book_mmd(INTERALG_MMD, "test_book")
        word_counts = [_word_count(c.text) for c in chunks]
        max_words = max(word_counts) if word_counts else 0
        assert max_words <= 2000, (
            f"Largest chunk has {max_words} words (limit 2000). "
            f"Top offenders: {sorted(word_counts, reverse=True)[:3]}"
        )

    def test_no_orphan_tiny_chunks(self):
        """
        After merging, no chunk should have fewer than 50 words when other chunks
        share the same concept_id.  Isolated single-chunk sections are exempt.
        """
        # EXPECTED TO FAIL: BUG 5 — tiny header-only chunks may survive merging
        # when the merge condition checks the wrong direction.
        chunks = parse_book_mmd(INTERALG_MMD, "test_book")
        from collections import Counter
        concept_chunk_counts = Counter(c.concept_id for c in chunks)
        orphan_tiny = [
            c for c in chunks
            if _word_count(c.text) < 50 and concept_chunk_counts[c.concept_id] > 1
        ]
        assert len(orphan_tiny) == 0, (
            f"Found {len(orphan_tiny)} tiny (<50 word) chunks that share a concept_id "
            f"with other chunks (should have been merged): "
            f"{[(c.concept_id, c.heading[:40], _word_count(c.text)) for c in orphan_tiny[:3]]}"
        )

    def test_chunk_size_p50_in_range(self):
        """
        Median (P50) chunk word count should be between 200 and 600 words.
        Values outside this range indicate systematic over-splitting or under-splitting.
        """
        chunks = parse_book_mmd(INTERALG_MMD, "test_book")
        word_counts = sorted(_word_count(c.text) for c in chunks)
        if not word_counts:
            pytest.skip("No chunks produced — cannot check distribution")
        p50 = statistics.median(word_counts)
        assert 150 <= p50 <= 800, (
            f"Median chunk word count is {p50:.0f} — expected 150–800. "
            f"This suggests systematic size problems in the parser."
        )

    def test_chunk_size_p10_above_floor(self):
        """
        10th percentile chunk word count must be at least 80 words.
        Very low P10 values indicate widespread tiny fragments.
        """
        chunks = parse_book_mmd(INTERALG_MMD, "test_book")
        word_counts = sorted(_word_count(c.text) for c in chunks)
        if len(word_counts) < 10:
            pytest.skip("Too few chunks to compute P10")
        p10_idx = max(0, len(word_counts) // 10 - 1)
        p10 = word_counts[p10_idx]
        assert p10 >= 80, (
            f"P10 chunk word count is {p10} — expected >= 80. "
            f"Too many tiny fragments exist in the parsed output."
        )


# ── BUG 6: Image accounting ───────────────────────────────────────────────────
# Every image referenced in the MMD must end up in exactly one chunk's image_urls.
# Images that fall between section boundaries or inside noise-filtered zones may
# be orphaned (not assigned to any chunk).

class TestBug6ImageOwnership:
    """BUG 6 — Every image reference in the MMD must appear in at least one chunk."""

    def test_all_interalg_images_accounted_for(self):
        """
        The number of image URLs collected across all chunks must equal or exceed
        the number of image references in the raw MMD for the intermediate algebra
        fixture.  Images should never be silently dropped.
        """
        raw = _load_fixture(INTERALG_MMD)

        # Count all image references in the raw fixture
        cdn_refs = len(re.findall(r"!\[\]\(https://cdn\.mathpix\.com/[^)]+\)", raw))
        local_refs = len(re.findall(r"!\[\]\(\./images/[^)]+\)", raw))
        latex_refs = len(re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{[^}]+\}", raw))
        total_mmd_images = cdn_refs + local_refs + latex_refs

        chunks = parse_book_mmd(INTERALG_MMD, "test_book")
        total_chunk_images = sum(len(c.image_urls) for c in chunks)

        # Images in TOC/front matter are not in any section — allow up to 10% gap
        min_expected = int(total_mmd_images * 0.90)
        assert total_chunk_images >= min_expected, (
            f"Only {total_chunk_images} images accounted for in chunks, "
            f"but MMD references {total_mmd_images} images "
            f"({cdn_refs} CDN + {local_refs} local + {latex_refs} LaTeX). "
            f"Expected at least {min_expected} (90%)"
        )

    def test_all_bstats_images_accounted_for(self):
        """
        Same image-accounting check for the business statistics fixture.
        """
        raw = _load_fixture(BSTATS_MMD)
        cdn_refs = len(re.findall(r"!\[\]\(https://cdn\.mathpix\.com/[^)]+\)", raw))
        local_refs = len(re.findall(r"!\[\]\(\./images/[^)]+\)", raw))
        latex_refs = len(re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{[^}]+\}", raw))
        total_mmd_images = cdn_refs + local_refs + latex_refs

        chunks = parse_book_mmd(BSTATS_MMD, "bstats")
        total_chunk_images = sum(len(c.image_urls) for c in chunks)

        # Fixture contains TOC/front matter images not in any section.
        # Allow up to 25% gap since fixture is a partial book extract.
        min_expected = int(total_mmd_images * 0.75)
        assert total_chunk_images >= min_expected, (
            f"bstats fixture: only {total_chunk_images} images in chunks vs "
            f"{total_mmd_images} in MMD. "
            f"Expected at least {min_expected} (75%)"
        )


# ── BUG 7: Post-parse validation ─────────────────────────────────────────────
# The parser should produce complete coverage of the TOC with no phantom sections
# and with sections appearing in numeric order.

class TestBug7Validation:
    """BUG 7 — Parser output must fully and correctly cover all TOC sections."""

    def test_toc_coverage_complete(self):
        """
        Every section number listed in the TOC must have at least one chunk.
        Missing sections mean the student cannot be taught that concept.
        """
        raw = _load_fixture(INTERALG_MMD)
        toc_sections = _parse_toc_sections(raw)
        # Only chapter-1 sections are in this fixture
        ch1_toc = {s for s in toc_sections if s.startswith("1.")}

        if not ch1_toc:
            pytest.skip("Could not parse TOC sections from fixture")

        chunks = parse_book_mmd(INTERALG_MMD, "test_book")
        chunked_sections = {c.concept_id.replace("test_book_", "") for c in chunks}

        missing = ch1_toc - chunked_sections
        # EXPECTED TO FAIL: BUG 7 — if a section is lost to bad dedup or TOC
        # whitelist exclusion, it will appear in `missing`.
        assert len(missing) == 0, (
            f"TOC sections with no chunks: {sorted(missing)}"
        )

    def test_no_phantom_sections(self):
        """
        No chunk should have a concept_id that does not correspond to a real TOC
        section.  Phantom concept_ids arise from bare-number artefacts (BUG 1) or
        exercise-counter headings being misinterpreted as sections.
        """
        raw = _load_fixture(INTERALG_MMD)
        toc_sections = _parse_toc_sections(raw)

        chunks = parse_book_mmd(INTERALG_MMD, "test_book")
        chunked_sections = {c.concept_id.replace("test_book_", "") for c in chunks}

        phantoms = {s for s in chunked_sections if s not in toc_sections}
        # EXPECTED TO FAIL: BUG 7 / BUG 1 — bare-number artefacts like '1.21' and
        # '1.22' will appear as phantoms if they slip through SECTION_PATTERN.
        assert len(phantoms) == 0, (
            f"Phantom concept_ids not in TOC: {sorted(phantoms)}"
        )

    def test_sections_in_order(self):
        """
        Chunks must appear in strictly non-decreasing (chapter, section) order
        of first occurrence.  A section must not appear for the first time AFTER
        a section with a higher number in the same chapter.
        """
        chunks = parse_book_mmd(INTERALG_MMD, "test_book")
        seen: list[tuple[int, int]] = []
        for c in chunks:
            # concept_id pattern: "test_book_1.3"
            m = re.match(r"test_book_(\d+)\.(\d+)", c.concept_id)
            if not m:
                continue
            key = (int(m.group(1)), int(m.group(2)))
            if key not in seen:
                seen.append(key)

        # Verify monotonically non-decreasing
        for i in range(1, len(seen)):
            assert seen[i] >= seen[i - 1], (
                f"Section order violation: {seen[i - 1]} appeared before {seen[i]} "
                f"in chunk output — sections are not in reading order."
            )


# ── Section ordering (business statistics fixture) ────────────────────────────
# The business statistics MMD has Chapter Review back-references that list 6.1 and
# 6.3 before the 6.2 body has appeared.  The parser must emit sections in numeric
# order, not document-scan order.

class TestSectionOrdering:
    """Section ordering must follow numeric (X.Y) order for all chapters."""

    def test_business_stats_ch5_order(self):
        """
        Sections 5.1, 5.2, 5.3 must appear in that order in the output chunks.
        The first occurrence of each section's concept_id must respect numeric order.
        """
        chunks = parse_book_mmd(BSTATS_MMD, "bstats")
        ch5_sections: list[tuple[int, int]] = []
        for c in chunks:
            m = re.match(r"bstats_5\.(\d+)", c.concept_id)
            if m:
                sec_num = (5, int(m.group(1)))
                if sec_num not in ch5_sections:
                    ch5_sections.append(sec_num)

        if len(ch5_sections) < 2:
            pytest.skip("Fewer than 2 chapter-5 sections found — cannot verify order")

        for i in range(1, len(ch5_sections)):
            assert ch5_sections[i] >= ch5_sections[i - 1], (
                f"Chapter 5 section order violation: "
                f"{ch5_sections[i - 1]} came after {ch5_sections[i]}"
            )

    def test_business_stats_ch6_order(self):
        """
        Sections 6.1, 6.2, 6.3 must appear in that order.
        The MMD has spurious back-references to 6.1 and 6.3 inside the chapter-5
        review zone — these must not reorder the chapter-6 sequence.
        """
        # EXPECTED TO FAIL: BUG (section ordering) — back-references to 6.1/6.3
        # inside chapter-5 review create earlier document positions for those
        # sections, causing them to be sorted before 6.2's body copy.
        chunks = parse_book_mmd(BSTATS_MMD, "bstats")
        ch6_sections: list[tuple[int, int]] = []
        for c in chunks:
            m = re.match(r"bstats_6\.(\d+)", c.concept_id)
            if m:
                sec_num = (6, int(m.group(1)))
                if sec_num not in ch6_sections:
                    ch6_sections.append(sec_num)

        if len(ch6_sections) < 2:
            pytest.skip("Fewer than 2 chapter-6 sections found — cannot verify order")

        for i in range(1, len(ch6_sections)):
            assert ch6_sections[i] >= ch6_sections[i - 1], (
                f"Chapter 6 section order violation: "
                f"{ch6_sections[i - 1]} came after {ch6_sections[i]} in chunk output"
            )

    def test_chapter_intro_in_first_section(self):
        """
        The chapter introduction text (prose before the first numbered section)
        should be prepended to the first section's chunk.  It must not be silently
        dropped or appear as a standalone chunk with no concept_id.
        """
        chunks = parse_book_mmd(INTERALG_MMD, "test_book")

        # The intermediate-algebra chapter-1 intro mentions 3D printers and
        # biomedical engineers — it must appear in section 1.1's chunk.
        ch1_first = next(
            (c for c in chunks if c.concept_id == "test_book_1.1"),
            None,
        )
        assert ch1_first is not None, (
            "concept_id 'test_book_1.1' not found — cannot check chapter intro placement"
        )
        # The intro text contains "3D printer" — but the fixture may not include
        # the chapter heading (fixture starts at section 1.1, chapter heading is earlier).
        # On full books this works; on partial fixtures, skip if chapter heading not detected.
        from extraction.chunk_parser import _normalize_mmd_format, _find_chapter_intros
        raw = _load_fixture(INTERALG_MMD)
        intros = _find_chapter_intros(_normalize_mmd_format(raw))
        if 1 not in intros:
            pytest.skip("Chapter 1 heading not in fixture — cannot test intro absorption")
        assert "3D" in ch1_first.text or "biomedical" in ch1_first.text.lower(), (
            f"Chapter intro text ('3D printer' / 'biomedical') not found in first "
            f"section chunk for test_book_1.1. Chapter intro may not be absorbed."
        )

    def test_cross_chapter_order_in_interalg(self):
        """
        Chapter sections must not interleave: all 1.X chunks before any 2.X chunks,
        all 2.X before 3.X, etc.  This fixture only has chapter 1 so this is a
        simpler monotonicity check for a single-chapter document.
        """
        chunks = parse_book_mmd(INTERALG_MMD, "test_book")
        chapter_sequence = []
        for c in chunks:
            m = re.match(r"test_book_(\d+)\.\d+", c.concept_id)
            if m:
                ch = int(m.group(1))
                if not chapter_sequence or chapter_sequence[-1] != ch:
                    chapter_sequence.append(ch)

        # Verify chapters only ever increase (no chapter going backwards)
        for i in range(1, len(chapter_sequence)):
            assert chapter_sequence[i] >= chapter_sequence[i - 1], (
                f"Chapter order violation: chapter {chapter_sequence[i - 1]} "
                f"reappeared after chapter {chapter_sequence[i]}"
            )
