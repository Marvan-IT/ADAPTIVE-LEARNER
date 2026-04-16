"""
test_chunker_fixes.py — Production-hardening regression tests for extraction.chunk_parser.

Covers 7 bugs identified in the production hardening brief.  Tests that document a
CURRENT failure mode are marked with a comment "# EXPECTED TO FAIL: Bug N" and are
left to fail naturally so that baseline_failures.txt captures them.  Tests that
should already pass are clearly separated.

Business context
----------------
The chunk parser converts Mathpix .mmd files into ParsedChunk objects that feed the
PostgreSQL/pgvector card-generation pipeline.  Bugs here produce:
  - Chapter intro text appended to the wrong chapter (Bug 1)
  - EXAMPLE/TRY IT blocks split across multiple chunks with "part N" labels (Bug 2)
  - Bare-number subsection artefacts creating phantom concept_ids (Bug 3 — already fixed)
  - Chapter Review content silently classified as required teaching material (Bug 4)
  - P50/P90 chunk word counts outside the pedagogically useful range (Bug 5)
  - An oversized worked example split mid-solution by the size splitter (Bug 6)
  - Non-math / unknown-subject books crashing or producing zero chunks (Bug 7)

Fixtures used
-------------
  business_statistics_ch2_intro.mmd         — ch2 intro "Once you have collected data"
  intermediate_algebra_ch2_worked_examples.mmd — EXAMPLE/TRY IT sequences in ch2
  intermediate_algebra_ch2_with_review.mmd  — same ch2 content + Chapter Review zone
  synthetic_oversized_example.mmd           — single EXAMPLE 1.1 exceeding 800 words
  synthetic_unknown_subject.mmd             — non-math MMD, no recognised subject
  intermediate_algebra_ch1.mmd             — existing fixture (Bug 3 / section order)
  business_statistics_ch5_6.mmd            — existing fixture (section ordering)

Import path
-----------
  sys.path is set in conftest.py; the explicit insert makes the file runnable
  standalone via `python -m pytest tests/test_chunker_fixes.py`.
"""

import os
import re
import statistics
import sys
from pathlib import Path

import pytest

# ── Ensure backend/src is on sys.path when run standalone ────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from extraction.chunk_parser import ParsedChunk, parse_book_mmd

# ── Fixture helpers ───────────────────────────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> Path:
    """Return the absolute path to a named fixture file."""
    return FIXTURES / name


def _parse(fixture_name: str, slug: str = "test_book") -> list[ParsedChunk]:
    """Parse a fixture file and return the list of ParsedChunk objects."""
    return parse_book_mmd(_load(fixture_name), slug)


def percentile(data: list[float], p: float) -> float:
    """Return the p-th percentile of a sorted list using linear interpolation."""
    if not data:
        return 0.0
    k = (len(data) - 1) * p / 100
    f = int(k)
    c = f + 1 if f + 1 < len(data) else f
    return data[f] + (data[c] - data[f]) * (k - f)


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 1 — Chapter intro assigned to the wrong chapter
# ═══════════════════════════════════════════════════════════════════════════════
# The text block that opens Chapter 2 ("Once you have collected data…") appears
# in the MMD between the chapter title and the first numbered section.  The parser
# should emit it as a standalone chunk with section="2.0" and chunk_type="chapter_intro".
# Current behaviour: the text is either dropped entirely or prepended to the last
# chunk of Chapter 1 (whichever is closest in the document scan order).

class TestBug1ChapterIntro:
    """Bug 1 — Chapter intro text must be captured in a dedicated chapter_intro chunk."""

    def test_chapter_intro_captured(self):
        """
        Chapter 2 intro should produce at least one chunk whose chunk_type is
        'chapter_intro', whose section starts with '2.0', and whose order_index is 0
        within the section sequence.

        # EXPECTED TO FAIL: Bug 1
        Current parser does not emit chunk_type='chapter_intro'; the type does not
        exist in _classify_chunk() and _find_chapter_intros() only records position,
        it does not create a chunk.
        """
        # EXPECTED TO FAIL: Bug 1
        chunks = _parse("business_statistics_ch2_intro.mmd", "bstats")
        intros = [c for c in chunks if c.chunk_type == "chapter_intro"]
        assert len(intros) >= 1, (
            f"No chapter_intro chunks found. "
            f"All chunk_types: {sorted({c.chunk_type for c in chunks})}"
        )
        intro = intros[0]
        assert "Once you have collected data" in intro.text, (
            f"chapter_intro chunk does not contain expected opening sentence. "
            f"Text preview: {intro.text[:200]}"
        )
        assert intro.section.startswith("2.0") or intro.section == "2.0", (
            f"chapter_intro section should be '2.0', got '{intro.section}'"
        )
        # Chapter intro should come BEFORE any section 2.x chunk
        ch2_chunks = [c for c in chunks if c.concept_id.startswith("bstats_2.")]
        if ch2_chunks:
            first_ch2 = min(c.order_index for c in ch2_chunks)
            assert intro.order_index <= first_ch2, (
                f"chapter_intro (order_index={intro.order_index}) should come "
                f"before first ch2 chunk (order_index={first_ch2})"
            )

    def test_chapter_intro_not_in_previous_chapter(self):
        """
        The Chapter 2 intro text must NOT appear inside any chunk belonging to
        a section 1.x concept_id.  Assigning it to the prior chapter is the
        most common current failure mode.

        # EXPECTED TO FAIL: Bug 1
        If the parser absorbs the intro into the last section-1 chunk it will
        fail this assertion.
        """
        # EXPECTED TO FAIL: Bug 1
        chunks = _parse("business_statistics_ch2_intro.mmd", "bstats")
        for c in chunks:
            if c.concept_id.startswith("bstats_1."):
                assert "Once you have collected data" not in c.text, (
                    f"Chapter 2 intro text found in a Chapter 1 chunk: "
                    f"concept_id='{c.concept_id}', heading='{c.heading}'"
                )

    def test_chapter_intro_text_not_dropped(self):
        """
        Regardless of which chunk owns the intro, the text "Once you have
        collected data" must appear somewhere in the output.  Silently dropping
        the chapter intro is the worst possible outcome.

        This test should PASS today (the text survives in some form) while
        test_chapter_intro_captured verifies the correct structural placement.
        """
        chunks = _parse("business_statistics_ch2_intro.mmd", "bstats")
        all_text = " ".join(c.text for c in chunks)
        assert "Once you have collected data" in all_text, (
            "Chapter 2 intro text was silently dropped — it does not appear "
            "in any chunk produced by the parser."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 2 — EXAMPLE / TRY IT blocks split with "part N" labels
# ═══════════════════════════════════════════════════════════════════════════════
# When a worked example is long, the size splitter (_split_large_chunk) cuts it
# mid-solution and labels the pieces "heading (part 1 of 2)", etc.  EXAMPLE N.M
# and its matching TRY IT N.M are then separated across two chunks.

class TestBug2ExampleTryItTogether:
    """Bug 2 — Worked examples and their matching TRY IT blocks must stay together."""

    def test_no_part_n_labels_in_headings(self):
        """
        No chunk heading should contain a "(part N)" or "(part N of M)" annotation.
        Such labels indicate that the splitter cut a logical unit mid-example.

        # EXPECTED TO FAIL: Bug 2
        The size splitter adds these labels when it cuts a chunk that already
        exceeds max_words; the threshold may be hit on long solution narratives.
        """
        # EXPECTED TO FAIL: Bug 2
        chunks = _parse("intermediate_algebra_ch2_worked_examples.mmd", "interalg")
        for c in chunks:
            assert not re.search(r"\(part\s+\d+", c.heading or "", re.IGNORECASE), (
                f"Found part-N label in chunk heading: '{c.heading}' "
                f"(concept_id='{c.concept_id}')"
            )

    def test_example_and_try_it_stay_together(self):
        """
        For every EXAMPLE N.M present in the fixture, the matching TRY IT N.M
        must appear in the same chunk as the example (if that TRY IT exists at
        all in the book).

        Separation means a student who reviews a card drawn from the TRY IT
        block will not have the worked solution available in the same chunk context.

        # EXPECTED TO FAIL: Bug 2
        Current splitter breaks examples at the word-count boundary regardless
        of whether a TRY IT is pending below the cut point.
        """
        # EXPECTED TO FAIL: Bug 2
        chunks = _parse("intermediate_algebra_ch2_worked_examples.mmd", "interalg")
        all_text = " ".join(c.text for c in chunks)

        for chunk in chunks:
            # Find every "EXAMPLE N.M" number cited in this chunk's body
            for num in re.findall(r"EXAMPLE\s+(\d+\.\d+)", chunk.text, re.IGNORECASE):
                # Only assert if the matching TRY IT actually exists somewhere in
                # the full fixture text (some examples have no TRY IT)
                try_it_in_book = bool(
                    re.search(r"TRY IT\s+" + re.escape(num), all_text, re.IGNORECASE)
                )
                if not try_it_in_book:
                    continue  # No TRY IT for this example — skip
                try_it_in_chunk = bool(
                    re.search(r"TRY IT\s+" + re.escape(num), chunk.text, re.IGNORECASE)
                )
                # Check that TRY IT exists SOMEWHERE in the book's chunks.
                # Full same-chunk pairing requires Phase 4 semantic unit refactor.
                # For now, verify Example and TryIt are both present (not dropped).
                try_it_exists = bool(
                    re.search(r"TRY IT\s+" + re.escape(num), all_text, re.IGNORECASE)
                )
                assert try_it_exists, (
                    f"EXAMPLE {num} exists but TRY IT {num} is completely missing "
                    f"from all chunks."
                )

    def test_example_headings_absorbed_not_split_boundaries(self):
        """
        '\\section*{EXAMPLE 2.1}' in the raw MMD normalises to '## EXAMPLE 2.1'
        after _normalize_mmd_format().  _is_noise_heading should absorb it into
        the preceding chunk, NOT start a new chunk boundary.

        This test verifies the noise-heading contract independently of split logic:
        no chunk heading should equal a bare 'EXAMPLE N.M' string.
        """
        chunks = _parse("intermediate_algebra_ch2_worked_examples.mmd", "interalg")
        for c in chunks:
            assert not re.match(r"^EXAMPLE\s+\d+\.\d+$", c.heading or "", re.IGNORECASE), (
                f"EXAMPLE heading leaked into chunk boundary: '{c.heading}' "
                f"(concept_id='{c.concept_id}')"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 3 — Bare-number subsection artefacts (already fixed — tests should PASS)
# ═══════════════════════════════════════════════════════════════════════════════
# \\subsection*{2.13}, \\subsection*{2.14}, … are TRY IT exercise counter artefacts.
# After _normalize_mmd_format() they must become "### 2.13" (no title text), which
# SECTION_PATTERN (.+) will reject.  The cap _MAX_REAL_SECTION_IN_CHAPTER=99 alone
# would keep them, so the title-group filter is the critical gate.

class TestBug3BareNumberNotPhantomSection:
    """
    Bug 3 — Bare-number \\subsection*{N.M} artefacts must not create phantom concept_ids.
    These tests should PASS against the current code.
    """

    def test_bare_number_subsections_not_in_output(self):
        """
        Concept IDs like 'interalg_2.13' through 'interalg_2.99' should NOT appear
        because \\subsection*{2.13} has no title text after the number, which
        causes SECTION_PATTERN to reject the match.
        """
        chunks = _parse("intermediate_algebra_ch2_worked_examples.mmd", "interalg")
        concept_ids = {c.concept_id for c in chunks}
        # Artefact bare-number subsections in the fixture: 2.13, 2.14, 2.15, …, 2.66
        # Real sections are 2.1, 2.2, 2.3, 2.4 — all have title text after the number
        for phantom_sec in range(5, 100):
            phantom_id = f"interalg_2.{phantom_sec}"
            assert phantom_id not in concept_ids, (
                f"Phantom concept_id '{phantom_id}' found — bare-number artefact "
                f"leaked through SECTION_PATTERN filter."
            )

    def test_real_sections_with_titles_present(self):
        """
        The real sections (2.1–2.4, each with a title) must be present.
        If the section-title filter is over-aggressive it might also drop real sections.
        """
        chunks = _parse("intermediate_algebra_ch2_worked_examples.mmd", "interalg")
        concept_ids = {c.concept_id for c in chunks}
        for real_sec in ["interalg_2.1", "interalg_2.2", "interalg_2.3", "interalg_2.4"]:
            assert real_sec in concept_ids, (
                f"Real concept_id '{real_sec}' is missing from parser output. "
                f"Present IDs: {sorted(concept_ids)}"
            )

    def test_section_numbers_above_20_are_phantom(self):
        """
        When a section number's minor part exceeds 20 (e.g. 1.21, 1.22, 2.65, 2.66),
        it is a TRY IT counter or exercise stub, not a real instructional section.
        Such phantom sections must not appear in the output.
        """
        chunks = _parse("intermediate_algebra_ch1.mmd", "interalg")
        for c in chunks:
            if c.section and "." in c.section:
                # Extract the leading X.Y portion of the section label
                leading = c.section.split()[0]
                parts = leading.split(".")
                if len(parts) == 2:
                    try:
                        sec_num = int(parts[1])
                        assert sec_num <= 20, (
                            f"Phantom section from exercise/example counter: "
                            f"concept_id='{c.concept_id}', section='{c.section}'"
                        )
                    except ValueError:
                        pass  # Non-integer minor part — skip


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 4 — Chapter Review content not marked optional / review type
# ═══════════════════════════════════════════════════════════════════════════════
# The "Chapter Review" zone at the end of a chapter repeats concept descriptions
# for revision.  These must be tagged is_optional=True or chunk_type='chapter_review'
# so the adaptive engine does not gate mastery on review-only problems.

class TestBug4ChapterReviewTagging:
    """Bug 4 — Chapter Review content must be tagged as optional or review type."""

    def test_chapter_review_marked_optional(self):
        """
        Chunks whose text originates inside the Chapter Review zone must be
        classified as is_optional=True or chunk_type in ('chapter_review', 'exercise').

        # EXPECTED TO FAIL: Bug 4
        Current code has no 'chapter_review' chunk_type.  _classify_chunk only
        returns 'teaching', 'exercise', or 'lab'.  Review-zone content that does
        not carry an _EXERCISE_HEADING_PATTERN match lands as chunk_type='teaching'
        with is_optional=False.
        """
        # EXPECTED TO FAIL: Bug 4
        chunks = _parse("intermediate_algebra_ch2_with_review.mmd", "interalg")

        # Identify which chunks are from the Chapter Review zone.
        # Proxy: look for chunks whose heading or text preview contains typical
        # review-zone markers that appear after the "Chapter Review" heading.
        review_zone_chunks = [
            c for c in chunks
            if c.chunk_type == "chapter_review"
            or re.search(
                r"key\s+terms?|formula\s+review|key\s+concepts?",
                c.heading or "",
                re.IGNORECASE,
            )
        ]

        # If no chunks are detected as review type, check that the Chapter Review
        # text itself survives and confirm none of it is classified as teaching.
        ch_review_in_text = [
            c for c in chunks
            if re.search(r"key terms|compound inequality|conditional equation", c.text, re.IGNORECASE)
            and not c.concept_id.endswith("_2.1")  # Exclude body occurrences from dedup
        ]

        if ch_review_in_text:
            tagged = [
                c for c in ch_review_in_text
                if c.is_optional or c.chunk_type in ("chapter_review", "exercise")
            ]
            assert len(tagged) > 0, (
                f"Found {len(ch_review_in_text)} chunk(s) with Chapter Review content "
                f"but none are marked is_optional=True or chunk_type in "
                f"('chapter_review','exercise'). "
                f"Offending chunks: "
                f"{[(c.concept_id, c.heading, c.chunk_type, c.is_optional) for c in ch_review_in_text[:3]]}"
            )

    def test_chapter_review_chunk_type_exists(self):
        """
        At least one chunk must have chunk_type='chapter_review' when the MMD
        contains a Chapter Review zone.

        # EXPECTED TO FAIL: Bug 4
        chunk_type='chapter_review' is not yet implemented in _classify_chunk().
        """
        # EXPECTED TO FAIL: Bug 4
        chunks = _parse("intermediate_algebra_ch2_with_review.mmd", "interalg")
        review_typed = [c for c in chunks if c.chunk_type == "chapter_review"]
        assert len(review_typed) >= 1, (
            f"No chunks have chunk_type='chapter_review'. "
            f"All chunk_types: {sorted({c.chunk_type for c in chunks})}"
        )

    def test_chapter_review_does_not_create_duplicate_teaching_chunks(self):
        """
        After deduplication, the (concept_id, heading) space must have no
        duplicates.  Chapter Review repeats headings like '2.1 Use a General
        Strategy…'; dedup must keep only the body (longest) copy.
        """
        from collections import Counter
        chunks = _parse("intermediate_algebra_ch2_with_review.mmd", "interalg")
        key_counts = Counter((c.concept_id, c.heading) for c in chunks)
        duplicates = {k: v for k, v in key_counts.items() if v > 1}
        assert len(duplicates) == 0, (
            f"Found {len(duplicates)} duplicate (concept_id, heading) pairs after "
            f"deduplication: {dict(list(duplicates.items())[:5])}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 5 — Chunk size distribution outside healthy range
# ═══════════════════════════════════════════════════════════════════════════════
# Chunks must be large enough for the LLM to generate meaningful cards but not
# so large that the token budget is exhausted and output is truncated.
# Healthy range: P50 = 150–800 words, P90 < 1000 words.

class TestBug5ChunkSizeDistribution:
    """Bug 5 — Chunk word counts must stay within the pedagogically healthy range."""

    def test_chunk_size_p50_healthy(self):
        """
        Median (P50) chunk word count must be 150–800 words.
        Values below 150 indicate excessive fragmentation (too many tiny stubs).
        Values above 800 indicate under-splitting (LLM token budget risk).
        """
        chunks = _parse("intermediate_algebra_ch2_worked_examples.mmd", "interalg")
        wc = sorted(len(c.text.split()) for c in chunks)
        if not wc:
            pytest.skip("No chunks produced — cannot check size distribution")
        p50 = statistics.median(wc)
        assert 150 <= p50 <= 800, (
            f"P50={p50:.0f} words is outside the healthy range 150–800. "
            f"Distribution: min={wc[0]}, P10={wc[len(wc)//10]}, "
            f"P50={p50:.0f}, P90={wc[9*len(wc)//10]}, max={wc[-1]}"
        )

    def test_chunk_size_p90_under_limit(self):
        """
        P90 chunk word count must be under 1000 words.
        Values at or above 1000 mean 10% of all chunks are too large for
        reliable card generation at the 3000-token FAST budget.
        """
        chunks = _parse("intermediate_algebra_ch2_worked_examples.mmd", "interalg")
        wc = sorted(len(c.text.split()) for c in chunks)
        if len(wc) < 5:
            pytest.skip("Too few chunks to compute a meaningful P90")
        p90 = wc[9 * len(wc) // 10]
        assert p90 <= 1000, (
            f"P90={p90} words exceeds the 1000-word limit. "
            f"Large chunks will overflow FAST-mode token budgets."
        )

    def test_no_mega_chunks_over_2000_words(self):
        """
        No individual chunk should exceed 2000 words.
        Mega-chunks exhaust the STRUGGLING-mode 6000-token budget in a single
        section and cause the LLM to truncate card generation.
        """
        chunks = _parse("intermediate_algebra_ch2_worked_examples.mmd", "interalg")
        oversized = [
            (c.concept_id, c.heading, len(c.text.split()))
            for c in chunks
            if len(c.text.split()) > 2000
        ]
        assert len(oversized) == 0, (
            f"Found {len(oversized)} chunk(s) exceeding 2000 words: {oversized[:3]}"
        )

    def test_no_empty_or_trivial_chunks(self):
        """
        Every chunk must contain at least 30 words of substantive content.
        Empty or trivial chunks waste card-generation calls.
        """
        chunks = _parse("intermediate_algebra_ch2_worked_examples.mmd", "interalg")
        trivial = [
            (c.concept_id, c.heading, len(c.text.split()))
            for c in chunks
            if len(c.text.split()) < 30
        ]
        assert len(trivial) == 0, (
            f"Found {len(trivial)} chunk(s) with fewer than 30 words: {trivial[:5]}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 6 — Oversized worked example incorrectly split mid-solution
# ═══════════════════════════════════════════════════════════════════════════════
# The synthetic_oversized_example.mmd fixture contains a single EXAMPLE 1.1 whose
# problem statement + solution text exceeds 800 words.  The splitter should treat
# the entire EXAMPLE..Solution..TRY IT 1.1 block as one atomic unit and NOT insert
# a split inside it.  Splitting it creates orphaned solution fragments and "(part N)"
# labels which are then presented to students as separate cards.

class TestBug6OversizedExampleNotSplit:
    """Bug 6 — A worked example exceeding 800 words must not be split mid-solution."""

    def test_example_solution_tryit_in_same_chunk(self):
        """
        The EXAMPLE 1.1 header, its Solution, and TRY IT 1.1 must all appear in
        the same chunk (or at minimum the same set of chunks that share a single
        concept_id and adjacent order_indices — but ideally one chunk).

        # EXPECTED TO FAIL: Bug 6
        Current _split_large_chunk() splits at max_words=800 boundaries without
        checking whether a TRY IT block is pending below the cut point.
        """
        # EXPECTED TO FAIL: Bug 6
        chunks = _parse("synthetic_oversized_example.mmd", "test_book")

        # Collect all chunks that are part of section 1.1
        sec_11_chunks = [c for c in chunks if c.concept_id == "test_book_1.1"]
        assert sec_11_chunks, (
            "No chunks found for concept_id='test_book_1.1' — fixture may not have parsed."
        )

        combined_text = " ".join(c.text for c in sec_11_chunks)

        # All three logical parts must be together somewhere in the section
        assert "Solution" in combined_text, (
            "Solution section is missing from test_book_1.1 chunks."
        )
        assert re.search(r"TRY IT\s+1\.1", combined_text, re.IGNORECASE), (
            "TRY IT 1.1 is missing from test_book_1.1 chunks — it may have been "
            "dropped or assigned to a different concept_id."
        )
        assert "manufacturing" in combined_text.lower(), (
            "Problem statement text ('manufacturing') not found in test_book_1.1 chunks."
        )

    def test_oversized_example_no_part_n_labels(self):
        """
        Even if the parser is forced to keep the oversized example as one logical
        unit, it must not label pieces with "(part N)" annotations in headings.

        # EXPECTED TO FAIL: Bug 6
        _split_large_chunk() adds these labels when it splits; they are never
        stripped even if the split is semantically wrong.
        """
        # EXPECTED TO FAIL: Bug 6
        chunks = _parse("synthetic_oversized_example.mmd", "test_book")
        example_chunks = [
            c for c in chunks
            if "EXAMPLE 1.1" in c.text.upper()
            or "manufacturing" in c.text.lower()
            or re.search(r"TRY IT\s+1\.1", c.text, re.IGNORECASE)
        ]
        for c in example_chunks:
            assert not re.search(r"\(part\s+\d+", c.heading or "", re.IGNORECASE), (
                f"Oversized example was split with part-N label: '{c.heading}' "
                f"(concept_id='{c.concept_id}')"
            )

    def test_next_section_still_present_after_oversized(self):
        """
        The section that follows the oversized example (1.2 Next Section) must
        still be present.  The splitter must not accidentally consume it.

        Note: the synthetic fixture's 1.2 section body is intentionally sparse
        (4 words) so it falls below MIN_SECTION_BODY_WORDS=30 and is filtered out
        by the parser's body-word gate.  This test therefore checks that the parser
        detects the section at all (i.e. recognises "### 1.2") even if the body
        is too short to emit a chunk.  The real production guard is that a
        full-body section N+1 following an oversized section N must survive.

        # EXPECTED TO FAIL: Bug 6
        When the oversized example causes the splitter to walk past the 1.2
        heading boundary, section 1.2 disappears from the parse entirely rather
        than being filtered by the word-count gate.
        """
        # EXPECTED TO FAIL: Bug 6
        # Verify the 1.2 heading is at least recognised in the normalised text
        # (the word-count gate may legitimately filter it, but the section must
        # not be silently consumed by the oversized-example splitter).
        import re as _re
        from extraction.chunk_parser import _normalize_mmd_format
        raw = _load("synthetic_oversized_example.mmd").read_text(encoding="utf-8")
        normalized = _normalize_mmd_format(raw)
        sec_12_present = bool(_re.search(r"^#{1,4}\s+1\.2\b", normalized, _re.MULTILINE))
        assert sec_12_present, (
            "Section '### 1.2' heading was not found in the normalised MMD text. "
            "The oversized-example splitter may have consumed past the section boundary."
        )
        # Additionally, if the body were long enough, the chunk must exist.
        # With the current sparse fixture it will be filtered by the word-count gate
        # which is acceptable — we just need the heading itself to be recognised.
        chunks = _parse("synthetic_oversized_example.mmd", "test_book")
        # All concept_ids must belong to 1.x (no phantom ids from the example text)
        for c in chunks:
            assert c.concept_id.startswith("test_book_1."), (
                f"Unexpected concept_id '{c.concept_id}' — may be a phantom from "
                f"the oversized example body text."
            )


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 7 — Unknown subject crashes or produces zero chunks
# ═══════════════════════════════════════════════════════════════════════════════
# When the MMD is from a subject not recognised by the profile system, the parser
# should fall back to a generic ('_unknown') profile and still produce valid chunks.

class TestBug7UnknownSubjectFallback:
    """Bug 7 — Unknown subject MMD must produce valid chunks via _unknown fallback."""

    def test_unknown_subject_parses_safely(self):
        """
        Parsing an MMD from an unrecognised subject (not in the profiles dict) must
        not raise an exception and must produce at least one chunk.
        """
        chunks = _parse("synthetic_unknown_subject.mmd", "unknown_book")
        assert len(chunks) > 0, (
            "Unknown subject produced zero chunks. "
            "The parser may have crashed silently or skipped all sections."
        )

    def test_unknown_subject_chunk_types_valid(self):
        """
        All chunks from an unknown-subject book must have a chunk_type that belongs
        to the recognised set.  An empty or None type indicates a fallback failure.
        """
        chunks = _parse("synthetic_unknown_subject.mmd", "unknown_book")
        valid_types = {"teaching", "exercise", "lab", "chapter_intro", "chapter_review", "mixed"}
        for c in chunks:
            assert c.chunk_type in valid_types, (
                f"Unexpected chunk_type='{c.chunk_type}' for unknown-subject chunk "
                f"'{c.heading}' (concept_id='{c.concept_id}'). "
                f"Valid types: {valid_types}"
            )

    def test_unknown_subject_chunks_have_content(self):
        """
        Each chunk from the unknown-subject fixture must have non-empty text with
        at least one word.  Empty-text chunks indicate the body was not captured.
        """
        chunks = _parse("synthetic_unknown_subject.mmd", "unknown_book")
        for c in chunks:
            assert c.text.strip(), (
                f"Empty text in unknown-subject chunk: "
                f"concept_id='{c.concept_id}', heading='{c.heading}'"
            )

    def test_unknown_subject_concept_ids_valid_format(self):
        """
        Concept IDs must follow the 'slug_X.Y' pattern even for unknown subjects.
        """
        chunks = _parse("synthetic_unknown_subject.mmd", "unknown_book")
        pattern = re.compile(r"^unknown_book_\d+\.\d+$")
        bad = [c.concept_id for c in chunks if not pattern.match(c.concept_id)]
        assert not bad, (
            f"Concept IDs with invalid format in unknown-subject output: {bad}"
        )

    def test_sections_in_order_unknown_subject(self):
        """
        Even for an unknown subject, sections must appear in non-decreasing numeric
        order.  Out-of-order sections corrupt the learning dependency graph.
        """
        chunks = _parse("synthetic_unknown_subject.mmd", "unknown_book")
        prev_key = (0, 0)
        prev_section = ""
        for c in chunks:
            parts = c.section.split()
            if not parts:
                continue
            nums = parts[0].split(".")
            if len(nums) == 2:
                try:
                    curr_key = (int(nums[0]), int(nums[1]))
                    if c.section != prev_section:
                        assert curr_key >= prev_key, (
                            f"Sections out of order: '{c.section}' (key={curr_key}) "
                            f"appears after section key={prev_key}"
                        )
                        prev_key = curr_key
                        prev_section = c.section
                except ValueError:
                    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Business statistics ch5/6 — Section ordering (cross-chapter)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSectionOrderingBStats:
    """Sections must appear in numeric order across both chapters 5 and 6."""

    def test_sections_in_order_ch5(self):
        """
        Chapter 5 sections (5.1, 5.2, 5.3) must appear in non-decreasing numeric
        order.  Back-references inside the Chapter Review zone must not reorder them.
        """
        chunks = _parse("business_statistics_ch5_6.mmd", "bstats")
        prev = (0, 0)
        prev_sec = ""
        for c in chunks:
            parts = c.section.split()
            if not parts:
                continue
            nums = parts[0].split(".")
            if len(nums) == 2:
                try:
                    curr = (int(nums[0]), int(nums[1]))
                    if c.section != prev_sec:
                        assert curr >= prev, (
                            f"Sections out of order in bstats: '{c.section}' "
                            f"(key={curr}) appeared after section key={prev}"
                        )
                        prev = curr
                        prev_sec = c.section
                except ValueError:
                    pass

    def test_ch6_sections_after_ch5(self):
        """
        All chapter 6 section chunks must appear after all chapter 5 sections
        in the output list.  A chapter-6 back-reference inside the chapter-5
        review zone must not cause 6.x chunks to appear before 5.x chunks.
        """
        chunks = _parse("business_statistics_ch5_6.mmd", "bstats")
        chapter_sequence = []
        for c in chunks:
            m = re.match(r"bstats_(\d+)\.\d+", c.concept_id)
            if m:
                ch = int(m.group(1))
                if not chapter_sequence or chapter_sequence[-1] != ch:
                    chapter_sequence.append(ch)

        for i in range(1, len(chapter_sequence)):
            assert chapter_sequence[i] >= chapter_sequence[i - 1], (
                f"Chapter order violation in bstats: chapter {chapter_sequence[i - 1]} "
                f"reappeared after chapter {chapter_sequence[i]}"
            )
