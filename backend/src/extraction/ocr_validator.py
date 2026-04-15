"""
ocr_validator.py — TOC parser, heading corrector, boundary candidate extractor,
and frequency+position analyzer for the Universal PDF Extraction Pipeline.

This module runs BEFORE chunk_parser and the book profiler, providing them with:
  1. Corrected section headings (fixes garbled OCR text vs. TOC ground truth)
  2. Chapter boundary character positions
  3. All potential subsection boundary candidates with frequency and position data

All functions are PURE — no DB, no LLM, no API calls. $0 local computation.

Heading formats handled (Mathpix output varies by book):
  Markdown  :  #, ##, ###, ####  — used by prealgebra and similar books
  LaTeX     :  \\subsection*{}, \\section*{} — used by elementary/intermediate/college algebra

The normalization step (_normalize_mmd) converts LaTeX to Markdown first, so all
downstream logic works on a single unified format.
"""

import re
import math
import logging
import difflib
from collections import defaultdict

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TocEntry(BaseModel):
    """One entry from the Table of Contents."""

    section_number: str   # e.g. "1.1"
    title: str            # e.g. "Principles of Nursing Practice"
    chapter: int          # e.g. 1


class BoundaryCandidate(BaseModel):
    """A potential subsection boundary found in the MMD body."""

    position: int              # character offset in the (normalized) MMD
    signal_type: str           # one of the _SIGNAL_TYPES values
    text: str                  # heading/line text (cleaned)
    section_id: str            # TOC section_number this candidate falls within ("unknown" if outside all)
    body_words_after: int      # words between this candidate and the next one
    position_in_section: float  # 0.0 = start of section, 1.0 = end


class SignalStats(BaseModel):
    """Frequency and position statistics for a recurring heading text."""

    text: str
    count: int
    avg_position: float        # average position_in_section across all occurrences
    std_position: float        # standard deviation of position_in_section
    signal_types: list[str]    # which signal types this text appears as (deduplicated)


class QualityReport(BaseModel):
    """Aggregated output of the structure analyzer for one book."""

    book_slug: str
    toc_entries: list[TocEntry]
    corrected_headings: dict[str, str]   # garbled_body_heading → corrected_toc_title
    chapter_boundaries: dict[int, int]  # chapter_number → char offset in normalized MMD
    boundary_candidates: list[BoundaryCandidate]
    signal_stats: list[SignalStats]      # sorted by count descending
    missing_sections: list[str]          # section_numbers in TOC but not found in body
    quality_score: float                 # matched_sections / total_toc_sections (0.0–1.0)


# ---------------------------------------------------------------------------
# Signal type constants
# ---------------------------------------------------------------------------

_SIGNAL_HEADING_H1 = "heading_h1"
_SIGNAL_HEADING_H2 = "heading_h2"
_SIGNAL_HEADING_H3 = "heading_h3"
_SIGNAL_HEADING_H4 = "heading_h4"
_SIGNAL_BOLD_LINE = "bold_line"
_SIGNAL_CAPS_LINE = "caps_line"
_SIGNAL_NUMBERED = "numbered"
_SIGNAL_LATEX_SECTION = "latex_section"
_SIGNAL_LATEX_SUBSECTION = "latex_subsection"

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Matches X.Y section numbers — used to detect TOC density and body headings
_SECTION_NUMBER_RE = re.compile(r"(\d+)\.(\d+)\s+\w")

# Matches any markdown heading at any level, capturing level and text
_MD_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)

# LaTeX heading patterns (pre-normalization detection for boundary scanning)
_LATEX_SECTION_RE = re.compile(r"^\\section\*\{(.+?)\}", re.MULTILINE)
_LATEX_SUBSECTION_RE = re.compile(r"^\\subsection\*\{(.+?)\}", re.MULTILINE)

# Bold-only lines: **text** or __text__ on their own line
_BOLD_LINE_RE = re.compile(r"^\*\*(.+)\*\*$|^__(.+)__$", re.MULTILINE)

# ALL-CAPS lines (3+ characters, zero lowercase letters, no digits-only lines)
_CAPS_LINE_RE = re.compile(r"^([A-Z][A-Z\s\-/&]{2,})$", re.MULTILINE)

# Numbered sub-items: "A. Word..." or "1. Capital..." but NOT section numbers "1.1 Title"
# Section numbers have a dot between two digit groups (X.Y); these use ". " separator
_NUMBERED_ITEM_RE = re.compile(r"^(?:[A-Z]\.\s+[A-Z]\w+|\d+\.\s+[A-Z][a-z]\w+)", re.MULTILINE)

# Chapter/unit/part boundary detection — case-insensitive
_CHAPTER_BOUNDARY_RE = re.compile(
    r"(?:chapter|unit|part)\s+(\d+)",
    re.IGNORECASE,
)

# Heading patterns that carry an X.Y section number
# Works across # / ## / ### / #### — whichever level Mathpix chose
_SECTION_HEADING_RE = re.compile(r"^(#{1,4})\s+(\d+)\.(\d+)\s+(.+)$", re.MULTILINE)

# Titles that appear in TOC but are not instructional sections.
# Applied after title cleaning to prevent them from entering the whitelist.
# Any TOC entry whose normalized title exactly matches one of these strings
# is a navigational/review artifact, not a pedagogical section.
_NON_INSTRUCTIONAL_TITLE_WORDS: frozenset[str] = frozenset({
    "summary",
    "key terms",
    "assessments",
    "references",
    "chapter review",
    "exercises",
    "practice test",
    "chapter test",
    "review exercises",
    "cumulative review",
    "answer key",
    "further reading",
    "bibliography",
})

# Adaptive TOC expansion constants
_DENSITY_THRESHOLD = 2   # minimum _SECTION_NUMBER_RE matches per 500-char expansion chunk
_EXPANSION_STEP = 500    # characters per expansion step

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_mmd(mmd_text: str) -> str:
    """
    Convert LaTeX-style headings to Markdown headings for uniform downstream parsing.

    Books like elementary_algebra, intermediate_algebra, and college_algebra use
    LaTeX heading syntax emitted by Mathpix:
      \\subsection*{1.1 Title}     →  ### 1.1 Title   (section heading, X.Y pattern)
      \\section*{Subsection Name}  →  ## Subsection Name   (pedagogical subsection)

    Markdown books (prealgebra) already use ### and ## — transformation is a no-op.
    This is intentionally identical to chunk_parser._normalize_mmd_format() so that
    both modules operate on the same normalized view.
    """
    text = re.sub(r"^\\subsection\*\{(.+?)\}", r"### \1", mmd_text, flags=re.MULTILINE)
    text = re.sub(r"^\\section\*\{(.+?)\}", r"## \1", text, flags=re.MULTILINE)
    return text


def _clean_heading_text(text: str) -> str:
    """
    Strip Unicode symbol prefixes, HTML tags, and extra whitespace from a
    heading string, returning clean human-readable text.

    Examples:
      "□ <br> SECTION 10.3 EXERCISES"  →  "SECTION 10.3 EXERCISES"
      "© Practice Makes Perfect"        →  "Practice Makes Perfect"
    """
    # Remove HTML <br> tags
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    # Strip leading non-alphanumeric / non-paren characters (symbols, bullets, etc.)
    text = re.sub(r"^[^\w(]+", "", text)
    # Collapse internal whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _word_count(text: str) -> int:
    """Count whitespace-delimited words in text."""
    return len(text.split())


def _normalize_text_key(text: str) -> str:
    """Produce a normalized key for grouping: lower-case, collapsed whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _compute_std(values: list[float]) -> float:
    """Population standard deviation. Returns 0.0 for lists shorter than 2."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


# ---------------------------------------------------------------------------
# 1. parse_toc
# ---------------------------------------------------------------------------


def parse_toc(mmd_text: str) -> list[TocEntry]:
    """
    Parse the Table of Contents from the MMD document.

    Strategy:
      - Divide the file into overlapping windows and measure density of
        section-number patterns (X.Y word) in each window.
      - The window with the highest density is the TOC region.
      - Extract all X.Y Title lines from that region.

    The TOC is typically in the first 5–10 % of the file. We search the
    first 20 % to handle unusually long front-matter.

    Args:
        mmd_text: Full raw MMD text (before or after normalization — the
                  section-number pattern works on both).

    Returns:
        List of TocEntry objects in document order, deduplicated by section_number.
        Empty list if no TOC is found.
    """
    if not mmd_text:
        return []

    # Limit search to the first 20 % of the document
    search_limit = max(5000, len(mmd_text) // 5)
    candidate_region = mmd_text[:search_limit]

    # Slide a 2000-char window through the candidate region, count X.Y matches
    window_size = 2000
    step = 500
    best_count = 0
    best_start = 0
    best_end = min(window_size, len(candidate_region))

    for start in range(0, max(1, len(candidate_region) - window_size + 1), step):
        end = min(start + window_size, len(candidate_region))
        window = candidate_region[start:end]
        count = len(_SECTION_NUMBER_RE.findall(window))
        if count > best_count:
            best_count = count
            best_start = start
            best_end = end

    if best_count < 3:
        # Not enough section numbers to be a TOC
        logger.warning("No TOC region detected (best density: %d section numbers)", best_count)
        return []

    # Adaptively expand the detected TOC window in both directions.
    # Continue expanding in _EXPANSION_STEP increments while each new chunk
    # contains at least _DENSITY_THRESHOLD section-number matches. This handles
    # books with 60+ sections whose TOC exceeds the initial 2000-char window.
    expand_left = best_start
    while expand_left > 0:
        step_start = max(0, expand_left - _EXPANSION_STEP)
        chunk = candidate_region[step_start:expand_left]
        if len(_SECTION_NUMBER_RE.findall(chunk)) >= _DENSITY_THRESHOLD:
            expand_left = step_start
        else:
            break

    expand_right = best_end
    while expand_right < len(candidate_region):
        step_end = min(len(candidate_region), expand_right + _EXPANSION_STEP)
        chunk = candidate_region[expand_right:step_end]
        if len(_SECTION_NUMBER_RE.findall(chunk)) >= _DENSITY_THRESHOLD:
            expand_right = step_end
        else:
            break

    # Final peek: catch last-of-chapter sections stranded behind boilerplate
    # (e.g. "Chapter Review", "Exercises" lines that drop density below threshold).
    # Look ahead 2 expansion steps for any remaining X.Y section-number matches.
    peek_end = min(len(candidate_region), expand_right + _EXPANSION_STEP * 2)
    if peek_end > expand_right:
        peek_chunk = candidate_region[expand_right:peek_end]
        if len(_SECTION_NUMBER_RE.findall(peek_chunk)) >= 1:
            expand_right = peek_end

    toc_start = expand_left
    toc_end = expand_right
    toc_region = candidate_region[toc_start:toc_end]

    logger.info(
        "TOC adaptive expansion: %d → %d chars (covers %d–%d); core window had %d matches",
        best_end - best_start, toc_end - toc_start, toc_start, toc_end, best_count,
    )

    # Extract X.Y entries from the TOC region.
    # Patterns seen in OpenStax MMD:
    #   "1.1 Introduction to Whole Numbers"
    #   "## 1.1 Introduction to Whole Numbers"   (after Mathpix heading markup)
    #   "1.1\tIntroduction to Whole Numbers"
    _TOC_LINE_RE = re.compile(
        r"^(?:#{1,4}\s+)?(\d+)\.(\d+)\s+([^\n]+)",
        re.MULTILINE,
    )

    seen_numbers: set[str] = set()
    entries: list[TocEntry] = []

    for m in _TOC_LINE_RE.finditer(toc_region):
        chapter_num = int(m.group(1))
        section_in_chapter = int(m.group(2))
        title_raw = m.group(3).strip()

        # Skip implausibly high section numbers (figure/equation numbers)
        if section_in_chapter > 99:
            continue

        # Clean the title
        title = _clean_heading_text(title_raw)
        # Strip trailing page numbers (common in TOC lines: "1.1 Intro ...... 12")
        title = re.sub(r"[\s.]+\d+\s*$", "", title).strip()

        if not title:
            continue

        # Filter non-instructional TOC entries (Summary, Key Terms, Exercises, etc.).
        # These are navigational/review artifacts, not pedagogical sections.
        # They should not appear in the TOC whitelist used by chunk_parser.
        if _normalize_text_key(title) in _NON_INSTRUCTIONAL_TITLE_WORDS:
            logger.debug(
                "TOC: skipping non-instructional entry %s %r",
                f"{chapter_num}.{section_in_chapter}", title,
            )
            continue

        section_number = f"{chapter_num}.{section_in_chapter}"
        if section_number in seen_numbers:
            continue  # Keep first occurrence only (body copy sometimes bleeds in)

        seen_numbers.add(section_number)
        entries.append(TocEntry(
            section_number=section_number,
            title=title,
            chapter=chapter_num,
        ))

    logger.info("Parsed %d TOC entries", len(entries))
    return entries


# ---------------------------------------------------------------------------
# 2. find_chapter_boundaries
# ---------------------------------------------------------------------------


def find_chapter_boundaries(mmd_text: str, toc: list[TocEntry]) -> dict[int, int]:
    """
    Find where each chapter starts in the normalized MMD body.

    Searches for headings containing "Chapter N", "CHAPTER N", "Unit N",
    "Part N" in any of the formats Mathpix emits:
      - ``## Chapter 13: Title``
      - ``CHAPTER 13 \\ Title``
      - ``# 13 | Title``
      - ``\\subsection*{Chapter 13}``

    Args:
        mmd_text:  Normalized MMD text (LaTeX headings already converted).
        toc:       Parsed TOC entries; used to build the expected chapter set.

    Returns:
        Dict mapping chapter_number → char offset of the chapter heading in mmd_text.
        Only chapters present in the TOC are included. Chapters without a detectable
        heading are omitted (callers must handle this gracefully).
    """
    if not mmd_text:
        return {}

    expected_chapters: set[int] = {e.chapter for e in toc} if toc else set()

    # Pattern 1: "## Chapter 13", "### UNIT 2", etc. inside markdown headings
    _HEADING_CHAPTER_RE = re.compile(
        r"^#{1,4}\s+.*?(?:chapter|unit|part)\s+(\d+)",
        re.IGNORECASE | re.MULTILINE,
    )

    # Pattern 2: Bare "CHAPTER 13" lines (Mathpix sometimes emits these unnested)
    _BARE_CHAPTER_RE = re.compile(
        r"^(?:chapter|unit|part)\s+(\d+)\b",
        re.IGNORECASE | re.MULTILINE,
    )

    # Pattern 3: "# 13 | Title" — chapter number with pipe/colon separator, no keyword
    _NUM_PIPE_RE = re.compile(
        r"^#{1,4}\s+(\d+)\s*[|:]\s+\S",
        re.MULTILINE,
    )

    boundaries: dict[int, int] = {}

    def _record(chapter_num: int, pos: int) -> None:
        """Record the earliest occurrence of a chapter boundary."""
        if chapter_num in boundaries:
            if pos < boundaries[chapter_num]:
                boundaries[chapter_num] = pos
        else:
            boundaries[chapter_num] = pos

    for pattern in (_HEADING_CHAPTER_RE, _BARE_CHAPTER_RE):
        for m in pattern.finditer(mmd_text):
            chapter_num = int(m.group(1))
            if expected_chapters and chapter_num not in expected_chapters:
                continue
            _record(chapter_num, m.start())

    for m in _NUM_PIPE_RE.finditer(mmd_text):
        chapter_num = int(m.group(1))
        if expected_chapters and chapter_num not in expected_chapters:
            continue
        _record(chapter_num, m.start())

    found = sorted(boundaries.keys())
    logger.info(
        "Chapter boundaries found: %d chapters — %s",
        len(boundaries),
        found[:10],
    )
    if expected_chapters:
        missing = sorted(expected_chapters - set(boundaries.keys()))
        if missing:
            logger.warning("Chapter boundaries NOT found for chapters: %s", missing)

    return boundaries


# ---------------------------------------------------------------------------
# 3. correct_headings
# ---------------------------------------------------------------------------


def correct_headings(mmd_text: str, toc: list[TocEntry]) -> dict[str, str]:
    """
    Find garbled body headings and correct them using TOC entries as ground truth.

    Algorithm:
      1. Extract all X.Y section headings from the body (both markdown and
         normalized-LaTeX forms, already converted by _normalize_mmd).
      2. For each body heading, locate the matching TOC entry by section number.
      3. If the heading title diverges from the TOC title
         (SequenceMatcher ratio < 0.8), record a correction mapping.

    Args:
        mmd_text: Normalized MMD text.
        toc:      Parsed TOC entries (ground truth titles).

    Returns:
        Dict mapping garbled_body_title → corrected_toc_title.
        Only entries where a divergence is detected are included.
    """
    if not mmd_text or not toc:
        return {}

    toc_index: dict[str, TocEntry] = {e.section_number: e for e in toc}
    corrections: dict[str, str] = {}

    for m in _SECTION_HEADING_RE.finditer(mmd_text):
        chapter_num = int(m.group(2))
        section_in_chapter = int(m.group(3))

        if section_in_chapter > 20:
            continue  # figure/equation numbers

        section_number = f"{chapter_num}.{section_in_chapter}"
        body_title_raw = m.group(4).strip()
        body_title = _clean_heading_text(body_title_raw)

        toc_entry = toc_index.get(section_number)
        if toc_entry is None:
            # Section in body but not in TOC — cannot correct
            continue

        toc_title = toc_entry.title

        ratio = difflib.SequenceMatcher(
            None, body_title.lower(), toc_title.lower()
        ).ratio()

        if ratio < 0.80:
            logger.debug(
                "Heading mismatch %s: body=%r toc=%r (ratio=%.2f)",
                section_number, body_title, toc_title, ratio,
            )
            # Use body_title as the key (the garbled form) — do NOT overwrite
            # if we have already seen a higher-quality correction (first wins)
            if body_title not in corrections:
                corrections[body_title] = toc_title

    logger.info(
        "Heading corrections found: %d / %d body headings diverge from TOC",
        len(corrections), len(toc),
    )
    return corrections


# ---------------------------------------------------------------------------
# 4. extract_boundary_candidates
# ---------------------------------------------------------------------------


def extract_boundary_candidates(
    mmd_text: str,
    toc: list[TocEntry],
    chapter_boundaries: dict[int, int],
) -> list[BoundaryCandidate]:
    """
    Scan the entire normalized MMD and collect every potential subsection boundary.

    Five signal types are detected:
      heading_h1/h2/h3/h4 : Markdown ``#`` through ``####`` headings
      bold_line            : Lines that are entirely bold (**text** or __text__)
      caps_line            : Lines that are 3+ chars, all uppercase, no lowercase
      numbered             : Lines matching ``A. Word`` or ``1. CapitalWord``
      latex_section        : ``\\section*{...}`` (in raw, pre-normalized text)
      latex_subsection     : ``\\subsection*{...}`` (in raw, pre-normalized text)

    Note: latex_section/latex_subsection are detected on the ORIGINAL mmd_text
    before normalization, because _normalize_mmd already converts them to ## / ###.
    However, since this function receives the already-normalized text, those signal
    types will only appear if the caller passes the raw text.  When passed normalized
    text the LaTeX signals will be zero — this is acceptable; the markdown equivalents
    capture the same boundaries.

    For each candidate:
      - Determine which TOC section it falls within (by character position).
      - Compute body_words_after (words until next candidate).
      - Compute position_in_section (0.0–1.0).

    Args:
        mmd_text:           Normalized MMD text.
        toc:                Parsed TOC entries.
        chapter_boundaries: Chapter number → char offset mapping.

    Returns:
        List of BoundaryCandidate sorted by position ascending.
    """
    if not mmd_text:
        return []

    # ── Build section ranges from _SECTION_HEADING_RE matches ────────────────
    # Each range: (section_number, range_start, range_end)
    section_ranges: list[tuple[str, int, int]] = []

    section_matches: list[tuple[int, int, str]] = []  # (start, end, section_number)
    for m in _SECTION_HEADING_RE.finditer(mmd_text):
        chapter_num = int(m.group(2))
        section_in_chapter = int(m.group(3))
        if section_in_chapter > 20:
            continue
        section_number = f"{chapter_num}.{section_in_chapter}"
        section_matches.append((m.start(), m.end(), section_number))

    for i, (start, end, sec_num) in enumerate(section_matches):
        range_end = section_matches[i + 1][0] if i + 1 < len(section_matches) else len(mmd_text)
        section_ranges.append((sec_num, start, range_end))

    def _find_section_id(pos: int) -> str:
        """Return the section_number whose range contains pos, or 'unknown'."""
        for (sec_num, sec_start, sec_end) in section_ranges:
            if sec_start <= pos < sec_end:
                return sec_num
        return "unknown"

    def _position_in_section(pos: int) -> float:
        """Return normalized position 0.0–1.0 within the containing section."""
        for (sec_num, sec_start, sec_end) in section_ranges:
            if sec_start <= pos < sec_end:
                span = sec_end - sec_start
                if span <= 0:
                    return 0.0
                return min(1.0, max(0.0, (pos - sec_start) / span))
        return 0.0

    # ── Collect raw candidates: (position, signal_type, cleaned_text) ─────────
    raw: list[tuple[int, str, str]] = []

    # Markdown headings (h1–h4)
    _level_signal = {
        1: _SIGNAL_HEADING_H1,
        2: _SIGNAL_HEADING_H2,
        3: _SIGNAL_HEADING_H3,
        4: _SIGNAL_HEADING_H4,
    }
    for m in _MD_HEADING_RE.finditer(mmd_text):
        level = len(m.group(1))
        signal = _level_signal.get(level, _SIGNAL_HEADING_H4)
        text = _clean_heading_text(m.group(2))
        if text:
            raw.append((m.start(), signal, text))

    # LaTeX section commands (if present in pre-normalized text passed by caller)
    for m in _LATEX_SECTION_RE.finditer(mmd_text):
        text = _clean_heading_text(m.group(1))
        if text:
            raw.append((m.start(), _SIGNAL_LATEX_SECTION, text))

    for m in _LATEX_SUBSECTION_RE.finditer(mmd_text):
        text = _clean_heading_text(m.group(1))
        if text:
            raw.append((m.start(), _SIGNAL_LATEX_SUBSECTION, text))

    # Bold-only lines
    for m in _BOLD_LINE_RE.finditer(mmd_text):
        text = _clean_heading_text(m.group(1) or m.group(2) or "")
        if text and len(text) >= 3:
            raw.append((m.start(), _SIGNAL_BOLD_LINE, text))

    # ALL-CAPS lines (must have at least one letter, exclude pure numbers/punctuation)
    for m in _CAPS_LINE_RE.finditer(mmd_text):
        text = m.group(1).strip()
        # Ensure it has at least one alphabetic character
        if text and len(text) >= 3 and re.search(r"[A-Z]", text):
            raw.append((m.start(), _SIGNAL_CAPS_LINE, text))

    # Numbered sub-items
    for m in _NUMBERED_ITEM_RE.finditer(mmd_text):
        text = _clean_heading_text(m.group(0))
        if text:
            raw.append((m.start(), _SIGNAL_NUMBERED, text))

    # Sort by position, deduplicate exact (pos, text) pairs
    raw.sort(key=lambda x: x[0])
    seen_positions: set[int] = set()
    unique_raw: list[tuple[int, str, str]] = []
    for pos, sig, text in raw:
        if pos not in seen_positions:
            seen_positions.add(pos)
            unique_raw.append((pos, sig, text))

    logger.info("Raw boundary candidates collected: %d", len(unique_raw))

    # ── Compute body_words_after for each candidate ───────────────────────────
    candidates: list[BoundaryCandidate] = []

    for i, (pos, signal_type, text) in enumerate(unique_raw):
        # Words between this candidate and the next (or end of document)
        if i + 1 < len(unique_raw):
            next_pos = unique_raw[i + 1][0]
        else:
            next_pos = len(mmd_text)
        body_text_between = mmd_text[pos:next_pos]
        words_after = _word_count(body_text_between)

        section_id = _find_section_id(pos)
        pos_in_section = _position_in_section(pos)

        candidates.append(BoundaryCandidate(
            position=pos,
            signal_type=signal_type,
            text=text,
            section_id=section_id,
            body_words_after=words_after,
            position_in_section=pos_in_section,
        ))

    logger.info("Boundary candidates after dedup: %d", len(candidates))
    return candidates


# ---------------------------------------------------------------------------
# 5. compute_signal_stats
# ---------------------------------------------------------------------------


def compute_signal_stats(
    candidates: list[BoundaryCandidate],
    threshold: int = 5,
) -> list[SignalStats]:
    """
    Group boundary candidates by normalized text, compute frequency and position stats.

    Only headings that appear more than ``threshold`` times are considered
    "recurring" (feature boxes, exercise markers, navigational boilerplate).
    All headings are grouped and stats are computed regardless; the threshold
    controls which ones appear in the returned list.

    Args:
        candidates: Output of extract_boundary_candidates().
        threshold:  Minimum count to include in results. Default 5.
                    Matches DEFAULT_RECURRING_HEADING_THRESHOLD in config.py.

    Returns:
        List of SignalStats sorted by count descending.
    """
    if not candidates:
        return []

    # Group by normalized text
    groups: dict[str, list[BoundaryCandidate]] = defaultdict(list)
    for cand in candidates:
        key = _normalize_text_key(cand.text)
        groups[key].append(cand)

    results: list[SignalStats] = []
    for key, group in groups.items():
        if len(group) <= threshold:
            continue

        positions = [c.position_in_section for c in group]
        avg_pos = sum(positions) / len(positions)
        std_pos = _compute_std(positions)

        # Collect unique signal types in order of first appearance
        seen_types: list[str] = []
        for c in group:
            if c.signal_type not in seen_types:
                seen_types.append(c.signal_type)

        # Use the representative text from the most-common raw form
        representative_text = group[0].text  # sorted by position; first occurrence

        results.append(SignalStats(
            text=representative_text,
            count=len(group),
            avg_position=round(avg_pos, 4),
            std_position=round(std_pos, 4),
            signal_types=seen_types,
        ))

    results.sort(key=lambda s: s.count, reverse=True)
    logger.info(
        "Recurring headings (count > %d): %d unique texts",
        threshold, len(results),
    )
    return results


# ---------------------------------------------------------------------------
# 6. validate_and_analyze  (main entry point)
# ---------------------------------------------------------------------------


def validate_and_analyze(mmd_text: str, book_slug: str) -> QualityReport:
    """
    Run the full OCR validation pipeline and return a QualityReport.

    Pipeline:
      1. Normalize LaTeX headings → Markdown (no-op for markdown books).
      2. Parse the Table of Contents.
      3. Find chapter boundary positions.
      4. Correct garbled section headings using TOC ground truth.
      5. Extract all boundary candidates with frequency/position signals.
      6. Compute signal statistics for recurring headings.
      7. Identify missing sections (in TOC but body heading not found).
      8. Compute quality_score = matched_sections / total_toc_sections.

    Args:
        mmd_text:  Raw MMD text as produced by Mathpix (may contain LaTeX headings).
        book_slug: Short book identifier (e.g. "prealgebra", "college_algebra").

    Returns:
        QualityReport with all analysis results.
    """
    if not mmd_text:
        logger.warning("validate_and_analyze called with empty MMD text for book '%s'", book_slug)
        return QualityReport(
            book_slug=book_slug,
            toc_entries=[],
            corrected_headings={},
            chapter_boundaries={},
            boundary_candidates=[],
            signal_stats=[],
            missing_sections=[],
            quality_score=0.0,
        )

    logger.info("Starting OCR validation for book '%s' (%d chars)", book_slug, len(mmd_text))

    # ── Step 1: Normalize ──────────────────────────────────────────────────────
    normalized = _normalize_mmd(mmd_text)

    # ── Step 2: Parse TOC ──────────────────────────────────────────────────────
    toc = parse_toc(mmd_text)  # Use raw text — TOC often precedes LaTeX sections

    # ── Step 3: Chapter boundaries ─────────────────────────────────────────────
    chapter_boundaries = find_chapter_boundaries(normalized, toc)

    # ── Step 4: Correct headings ───────────────────────────────────────────────
    corrected_headings = correct_headings(normalized, toc)

    # ── Step 5: Extract boundary candidates ───────────────────────────────────
    boundary_candidates = extract_boundary_candidates(normalized, toc, chapter_boundaries)

    # ── Step 6: Signal statistics ──────────────────────────────────────────────
    # Import threshold from config; fall back to module default if unavailable
    try:
        import sys
        from pathlib import Path
        # Ensure the backend/src directory is on sys.path for config import
        _src_dir = Path(__file__).resolve().parent.parent
        if str(_src_dir) not in sys.path:
            sys.path.insert(0, str(_src_dir))
        from config import DEFAULT_RECURRING_HEADING_THRESHOLD
        threshold = DEFAULT_RECURRING_HEADING_THRESHOLD
    except ImportError:
        threshold = 5
        logger.debug("config.py not importable; using default threshold=%d", threshold)

    signal_stats = compute_signal_stats(boundary_candidates, threshold=threshold)

    # ── Step 7: Missing sections ───────────────────────────────────────────────
    # Find which TOC section numbers are absent from the body
    body_section_numbers: set[str] = set()
    for m in _SECTION_HEADING_RE.finditer(normalized):
        chapter_num = int(m.group(2))
        section_in_chapter = int(m.group(3))
        if section_in_chapter <= 20:
            body_section_numbers.add(f"{chapter_num}.{section_in_chapter}")

    toc_section_numbers: list[str] = [e.section_number for e in toc]
    missing_sections: list[str] = [
        sn for sn in toc_section_numbers if sn not in body_section_numbers
    ]

    if missing_sections:
        logger.warning(
            "Missing sections (in TOC but body heading not found): %s",
            missing_sections[:20],
        )

    # ── Step 8: Quality score ──────────────────────────────────────────────────
    total = len(toc_section_numbers)
    matched = total - len(missing_sections)
    quality_score = round(matched / total, 4) if total > 0 else 0.0

    logger.info(
        "OCR validation complete: toc_entries=%d, corrected=%d, candidates=%d, "
        "recurring=%d, missing=%d, quality=%.3f",
        len(toc),
        len(corrected_headings),
        len(boundary_candidates),
        len(signal_stats),
        len(missing_sections),
        quality_score,
    )

    return QualityReport(
        book_slug=book_slug,
        toc_entries=toc,
        corrected_headings=corrected_headings,
        chapter_boundaries=chapter_boundaries,
        boundary_candidates=boundary_candidates,
        signal_stats=signal_stats,
        missing_sections=missing_sections,
        quality_score=quality_score,
    )


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import json
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    try:
        from config import OUTPUT_DIR
    except ImportError:
        print("ERROR: could not import config.OUTPUT_DIR — run from backend/src/")
        sys.exit(1)

    book_slug = sys.argv[1] if len(sys.argv) > 1 else "prealgebra"
    mmd_path = OUTPUT_DIR / book_slug / "book.mmd"

    if not mmd_path.exists():
        print(f"ERROR: {mmd_path} not found")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    mmd_text = mmd_path.read_text(encoding="utf-8")
    report = validate_and_analyze(mmd_text, book_slug)

    print(f"\n{'='*60}")
    print(f"Book: {report.book_slug}")
    print(f"TOC entries: {len(report.toc_entries)}")
    print(f"Chapter boundaries: {sorted(report.chapter_boundaries.keys())}")
    print(f"Corrected headings: {len(report.corrected_headings)}")
    print(f"Boundary candidates: {len(report.boundary_candidates)}")
    print(f"Recurring headings (signal_stats): {len(report.signal_stats)}")
    print(f"Missing sections: {report.missing_sections[:10]}")
    print(f"Quality score: {report.quality_score:.3f}")

    if report.toc_entries:
        print("\nFirst 5 TOC entries:")
        for e in report.toc_entries[:5]:
            print(f"  {e.section_number:6s}  {e.title}")

    if report.signal_stats:
        print("\nTop 5 recurring headings:")
        for s in report.signal_stats[:5]:
            print(f"  count={s.count:3d}  avg_pos={s.avg_position:.2f}  std={s.std_position:.2f}  '{s.text[:50]}'")

    if report.corrected_headings:
        print("\nSample corrections (garbled → toc):")
        for garbled, corrected in list(report.corrected_headings.items())[:5]:
            print(f"  {garbled!r:40s} → {corrected!r}")
