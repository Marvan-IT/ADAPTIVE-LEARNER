"""
chunk_parser.py — Parse book.mmd into subsection-level ParsedChunk objects.

Heading hierarchy in Mathpix-generated prealgebra book.mmd:
  #     — document-level (title page, front matter)
  ##    — two roles: (a) pedagogical subsection headings like "Identify Whole Numbers"
          and (b) noise headings from Mathpix: EXAMPLE 1.1, TRY IT, Solution, HOW TO, ...
  ###   — section headings with X.Y number pattern (e.g. "### 1.1 Introduction to Whole Numbers")
  ####  — sub-sub-headings (rare, treated as body content)

Section detection is PATTERN-BASED (X.Y number format), NOT level-based, so this
parser works correctly across all 16 OpenStax books regardless of which heading
level Mathpix chose for section markers.

Subsection boundaries (chunk splits):
  Only MEANINGFUL `##` headings cause a split. Noise headings (EXAMPLE, TRY IT,
  Solution, HOW TO, MANIPULATIVE, BE PREPARED, SECTION N.N EXERCISES, etc.) are
  treated as body content of the containing chunk. This keeps related example/solution
  pairs with their parent subsection rather than fragmenting them.

3-copy deduplication (critical):
  Mathpix emits each section ~3 times: TOC entry (~0 words), body (500-2000 words),
  chapter review stub (100-400 words). At the CHUNK level we group by
  (concept_id, heading) and keep whichever occurrence has the most words.
"""

import re
import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from config import CONTENT_EXCLUDE_MARKERS

logger = logging.getLogger(__name__)

# ── Compiled patterns ─────────────────────────────────────────────────────────

# Matches any markdown heading that carries an X.Y section number.
# Works on # through #### — whichever level Mathpix happens to use.
SECTION_PATTERN = re.compile(r"^(#{1,4})\s+(\d+)\.(\d+)\s+(.+)$", re.MULTILINE)

# Matches ## headings specifically (the subsection-split level)
SUBHEADING_PATTERN = re.compile(r"^##\s+(.+)$", re.MULTILINE)

# CDN image URLs produced by Mathpix
IMAGE_URL_PATTERN = re.compile(r"!\[\]\((https://cdn\.mathpix\.com/[^)]+)\)")
LOCAL_IMAGE_PATTERN = re.compile(r"!\[\]\((\.\/images\/[^)]+)\)")
# LaTeX \includegraphics images from Mathpix figure environments
LATEX_IMAGE_PATTERN = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")

# Inline ($…$) and block ($$…$$) LaTeX — block must be checked first
LATEX_PATTERN = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.DOTALL)

# Section-number figure headings Mathpix emits as fake sections (e.g. "### 1.52", "### 2.11").
# Across all 16 OpenStax textbooks, real instructional sections stay at most 10 per chapter.
# Values 11+ are always exercise-set identifiers or figure references, not real sections.
_MAX_REAL_SECTION_IN_CHAPTER = 99  # Effectively no cap; body-word filter + TOC whitelist catch fakes
MIN_SECTION_BODY_WORDS = 30  # real sections have ≥30 words of intro; exercise stubs have 5–15

# ── Noise heading filters ─────────────────────────────────────────────────────
# These ## headings are NOT pedagogical subsection boundaries.
# They are examples, exercises, solutions, or navigational boilerplate.
# We keep them as body content of their containing chunk.
_NOISE_HEADING_PATTERNS: list[re.Pattern] = [
    re.compile(r"^EXAMPLE\b", re.IGNORECASE),
    re.compile(r"^TRY IT\b", re.IGNORECASE),
    re.compile(r"^Solution\b", re.IGNORECASE),
    re.compile(r"^HOW TO\b", re.IGNORECASE),
    re.compile(r"^MANIPULATIVE\b", re.IGNORECASE),
    re.compile(r"^Self Check\b", re.IGNORECASE),
    re.compile(r"^In the following exercises\b", re.IGNORECASE),
    re.compile(r"^Access for free\b", re.IGNORECASE),
    re.compile(r"^\([a-z0-9]\)\s+Solution\b", re.IGNORECASE),  # "(a) Solution", "(r) Solution"
    re.compile(r"^\(\s*[A-Z]\s*\)?\s+Solution\b"),             # "( J Solution", "(A) Solution" — Mathpix OCR artifact ⊙
    # Headings that are just a single word with no spaces (usually CAPS markers)
    re.compile(r"^[A-Z]{2,}$"),
    # Numbered items that are headings by mistake (e.g. "207. Seventy-five more than...")
    re.compile(r"^\d+\.\s"),
    # Config-driven exclusions — stays in sync with config.py automatically
    *[re.compile(rf"^{re.escape(m)}\b", re.IGNORECASE) for m in CONTENT_EXCLUDE_MARKERS],
    re.compile(r"^LINK TO LEARNING\b", re.IGNORECASE),
    re.compile(r"^CHAPTER OUTLINE\b", re.IGNORECASE),
    re.compile(r"^INTRODUCTION\b$", re.IGNORECASE),
    re.compile(r"^LEARNING OBJECTIVES?\b", re.IGNORECASE),
    # Readiness-quiz preamble found in nursing/allied-health books
    re.compile(r"^Before you get started", re.IGNORECASE),
    # Common textbook noise headings — keeps content together with parent section
    re.compile(r"^Problem\b", re.IGNORECASE),
    re.compile(r"^COLLABORATIVE EXERCISE\b", re.IGNORECASE),
    re.compile(r"^References\b", re.IGNORECASE),
    re.compile(r"^Key Terms\b", re.IGNORECASE),
    re.compile(r"^Chapter Review\b", re.IGNORECASE),
    re.compile(r"^Practice\b", re.IGNORECASE),
    re.compile(r"^Bringing It Together\b", re.IGNORECASE),
]

def _is_noise_heading(heading_text: str) -> bool:
    """Return True if this heading is a noise marker, not a pedagogical subsection."""
    return any(p.match(heading_text) for p in _NOISE_HEADING_PATTERNS)


def _normalize_heading(heading: str) -> str:
    """
    Strip Unicode symbol prefixes, LaTeX \\section*{} wrappers, and HTML tags
    that Mathpix sometimes emits before the meaningful heading text.

    Examples:
      "□ <br> \\section*{SECTION 10.3 EXERCISES}" → "SECTION 10.3 EXERCISES"
      "© Practice Makes Perfect"                  → "Practice Makes Perfect"
      "SECTION 1.1 Exercises"                     → "SECTION 1.1 Exercises"
    """
    h = heading
    # Unwrap \\section*{...} LaTeX
    m = re.search(r"\\section\*\{(.+?)\}", h)
    if m:
        h = m.group(1)
    # Remove <br> tags
    h = re.sub(r"<br\s*/?>", " ", h, flags=re.IGNORECASE)
    # Strip leading non-alphanumeric/non-paren characters (Unicode symbols, dashes, bullets)
    h = re.sub(r"^[^\w(]+", "", h)
    # Collapse whitespace
    h = re.sub(r"\s+", " ", h).strip()
    return h


# Patterns that mark start of the exercise zone for a section.
# Once triggered, all subsequent meaningful ## headings within this section
# are classified as exercise chunks.
_EXERCISE_ZONE_PATTERN = re.compile(
    r"^(?:section\s+\d+\.\d+"      # SECTION 1.1 [EXERCISES]
    r"|review exercises?"           # Review Exercises
    r"|chapter\s+review"            # Chapter Review
    r"|practice\s+test"             # Practice Test
    r"|chapter\s+test"              # Chapter Test
    r")",
    re.IGNORECASE,
)

# Headings classified as exercise type (within exercise zone OR standalone)
_EXERCISE_HEADING_PATTERN = re.compile(
    r"^(?:practice makes perfect?"  # includes typo "Practice Makes Pefect"
    r"|mixed practice"
    r"|everyday math"
    r"|writing exercises?"
    r")",
    re.IGNORECASE,
)

# Info/objective panels — always learning_objective regardless of text length
_INFO_HEADING_PATTERN = re.compile(
    r"^(?:learning objectives?"
    r"|section objectives?"
    r"|chapter objectives?"
    r"|section outcomes?"
    r"|learning outcomes?"
    r"|key terms?"
    r"|key concepts?"
    r"|summary"
    r"|in this section,?\s+you will"   # college_algebra: "In this section, you will:"
    r"|by the end of this"             # common variant across books
    r")",
    re.IGNORECASE,
)


def _normalize_mmd_format(mmd_text: str) -> str:
    """
    Convert LaTeX-style headings to markdown-style headings for uniform parsing.

    Books like elementary_algebra, intermediate_algebra, college_algebra, and algebra_1
    use LaTeX heading syntax produced by Mathpix:
      \\subsection*{1.1 Title}     →  ### 1.1 Title   (section boundary, X.Y pattern)
      \\section*{Subsection Name}  →  ## Subsection Name   (pedagogical subsection)

    Markdown books (prealgebra) already use ### and ## — transformation is a no-op.
    """
    # \subsection*{1.1 Title} → ### 1.1 Title
    text = re.sub(r"^\\subsection\*\{(.+?)\}", r"### \1", mmd_text, flags=re.MULTILINE)
    # \section*{Title} → ## Title
    text = re.sub(r"^\\section\*\{(.+?)\}", r"## \1", text, flags=re.MULTILINE)
    return text


# Detects section titles that ARE themselves exercise sections (e.g. college_algebra
# "1.1 SECTION EXERCISES") — in these cases the entire body is exercise content.
_SECTION_IS_EXERCISE_PATTERN = re.compile(
    r"section\s+exercises?|chapter\s+review|review\s+exercises?|practice\s+test|chapter\s+test",
    re.IGNORECASE,
)


def _classify_chunk(raw_heading: str, in_exercises_zone: bool, section_label: str = "") -> tuple[str, bool]:
    """Return (chunk_type, is_optional) for a chunk heading."""
    h = _normalize_heading(raw_heading)
    sl = section_label.lower()
    is_opt = bool(re.search(r'\(optional\)', sl, re.IGNORECASE))
    is_lab = bool(re.search(r'\blab\b|\bexperiment\b', sl, re.IGNORECASE))

    # Mark universally obvious metadata as optional
    _OPTIONAL_PATTERNS = [
        r'\bpreface\b', r'\babout the author', r'\bcontributing author',
        r'\breviewers?\b', r'\backnowledgment', r'\bdedication\b',
        r'\bindex\b', r'\banswer key\b', r'\bglossary\b',
    ]
    if any(re.search(p, sl, re.IGNORECASE) or re.search(p, h, re.IGNORECASE) for p in _OPTIONAL_PATTERNS):
        is_opt = True

    if in_exercises_zone or _EXERCISE_HEADING_PATTERN.match(h):
        is_writing = bool(re.match(r"^writing exercises?", h, re.IGNORECASE))
        return "exercise", is_opt or is_writing
    if is_lab:
        return "lab", is_opt
    return "teaching", is_opt


@dataclass
class ParsedChunk:
    """One subsection-level content block extracted from book.mmd."""

    book_slug: str
    concept_id: str        # e.g. "prealgebra_1.1"
    section: str           # e.g. "1.1 Introduction to Whole Numbers"
    order_index: int       # global sequential position (0-based, monotone)
    heading: str           # subsection heading text
    text: str              # full markdown text including image tags and LaTeX
    latex: list[str] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)
    image_captions: list[str | None] = field(default_factory=list)
    chunk_type:  str  = "teaching"
    is_optional: bool = False


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_latex(text: str) -> list[str]:
    """Return all LaTeX expressions found in text (block $$…$$ and inline $…$)."""
    results: list[str] = []
    for m in LATEX_PATTERN.finditer(text):
        expr = (m.group(1) or m.group(2) or "").strip()
        if expr:
            results.append(expr)
    return results


def _extract_image_urls(text: str) -> list[str]:
    """Return all image refs found in text — CDN URLs, local ./images/ paths, or LaTeX \\includegraphics."""
    return IMAGE_URL_PATTERN.findall(text) + LOCAL_IMAGE_PATTERN.findall(text) + LATEX_IMAGE_PATTERN.findall(text)


# Caption patterns — LaTeX \caption{text} and markdown "Figure X.Y: description"
_LATEX_CAPTION_PATTERN = re.compile(r"\\caption\{([^}]*)\}")
_FIGURE_CAPTION_PATTERN = re.compile(r"Figure\s+\d+\.\d+[:\s]+(.+?)(?:\n|$)")


def _extract_image_captions(text: str, image_count: int) -> list[str | None]:
    """Extract captions from LaTeX \\caption{} and Figure X.Y: patterns.

    Returns a list parallel to image_urls (same length), with None for
    images where no caption was found.
    """
    captions: list[str] = []
    for m in _LATEX_CAPTION_PATTERN.finditer(text):
        cap = m.group(1).strip()
        if cap:
            captions.append(cap)
    for m in _FIGURE_CAPTION_PATTERN.finditer(text):
        cap = m.group(1).strip()
        if cap and cap not in captions:
            captions.append(cap)
    # Pad or truncate to match image_count
    result: list[str | None] = []
    for i in range(image_count):
        result.append(captions[i] if i < len(captions) else None)
    return result


def _clean_chunk_text(text: str) -> str:
    """Minimal cleanup — preserve all content for LLM card generation.

    Images are already extracted to image_urls via _extract_image_urls().
    Captions extracted via _extract_image_captions().
    LaTeX extracted via _extract_latex().
    We keep ALL readable content (URLs, Figure refs, credits, LaTeX markup)
    so the LLM sees full context when generating cards.
    """
    # Only collapse excessive blank lines — keep everything else
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _word_count(text: str) -> int:
    return len(text.split())


def _dedup_section_matches(
    section_matches: list[dict],
    mmd_text: str,
) -> list[dict]:
    """Group by section_number, keep the occurrence with the longest body.

    Replaces the old backward-number filter. When Mathpix emits 3 copies
    of each section (TOC stub, body, review), this keeps the body copy
    (highest word count) and discards the rest.

    Returns deduped list sorted by document position (reading order).
    """
    seen: dict[str, tuple[dict, int]] = {}  # section_number -> (sec_dict, body_words)
    for idx, sec in enumerate(section_matches):
        key = sec["section_number"]
        body_start = sec["end"]
        body_end = (
            section_matches[idx + 1]["start"]
            if idx + 1 < len(section_matches)
            else len(mmd_text)
        )
        body_words = _word_count(mmd_text[body_start:body_end])
        prev = seen.get(key)
        if prev is None or body_words > prev[1]:
            seen[key] = (sec, body_words)
    result = [entry[0] for entry in seen.values()]
    result.sort(key=lambda s: s["start"])
    logger.info(
        "Section-level dedup: %d occurrences → %d unique sections",
        len(section_matches), len(result),
    )
    return result


# ── Public API ────────────────────────────────────────────────────────────────

def parse_book_mmd(
    mmd_path: Path,
    book_slug: str,
    profile=None,
    corrected_headings: dict | None = None,
) -> list[ParsedChunk]:
    """
    Parse book.mmd into subsection-level chunks with 3-copy deduplication.

    When profile=None (default), uses the hardcoded OpenStax math logic exactly
    as before — zero regression for all 16 existing math books.

    When a BookProfile is supplied, delegates to _parse_book_mmd_with_profile()
    which uses multi-signal boundary detection driven by the profile object.

    Algorithm (profile=None path):
      1. Locate all X.Y section headings (e.g. "### 1.1 Introduction to Whole Numbers")
         to determine section content boundaries.
      2. For each section's body, split on `##` headings that represent MEANINGFUL
         pedagogical subsections (filtering out noise: EXAMPLE, TRY IT, Solution, etc.).
      3. Orphan text before the first meaningful ## heading is prepended to the
         first subsection chunk (not emitted as a separate chunk).
      4. Sections with zero meaningful ## headings → entire body = one chunk.
      5. Deduplicate: group by (concept_id, heading), keep highest word-count.
         This removes the 3 Mathpix copies of each section (TOC stub, body, review stub).
      6. Re-number order_index in reading order.

    Args:
        mmd_path:            Path to the book's book.mmd file.
        book_slug:           Short identifier for the book (e.g. "prealgebra").
        profile:             Optional BookProfile for non-math books. When provided the
                             profile's signals, noise patterns, and exercise markers drive
                             boundary detection instead of hardcoded patterns.
        corrected_headings:  Optional dict mapping garbled section title strings (as
                             Mathpix emitted them) to the corrected titles from the TOC.
                             Applied only in the hardcoded path (profile=None). When
                             profile is provided, corrections are stored in the profile
                             object itself and applied inside _parse_book_mmd_with_profile.

    Returns:
        List of ParsedChunk objects sorted by original reading order.
        After dedup the count should be ~300-600 for prealgebra (not 900-1500).
    """
    mmd_text = mmd_path.read_text(encoding="utf-8")
    # Normalize LaTeX heading syntax (\subsection*{} / \section*{}) to markdown (### / ##)
    # This is a no-op for prealgebra (already markdown); required for all other books.
    mmd_text = _normalize_mmd_format(mmd_text)
    logger.info("Loaded %s (%d chars)", mmd_path, len(mmd_text))

    # ── Profile-driven path (non-math books) ─────────────────────────────────
    if profile is not None:
        return _parse_book_mmd_with_profile(mmd_text, book_slug, profile)

    # ── Step 1: Find all X.Y section headings ────────────────────────────────
    section_matches: list[dict] = []
    for m in SECTION_PATTERN.finditer(mmd_text):
        chapter_num = int(m.group(2))
        section_in_chapter = int(m.group(3))
        if section_in_chapter > _MAX_REAL_SECTION_IN_CHAPTER:
            # Mathpix emits figure/equation numbers as headings — skip
            continue
        section_title_raw = m.group(4).strip()
        # Apply OCR corrections from caller if provided (Fix 5B).
        # Allows the pipeline to pass quality_report.corrected_headings so that
        # garbled Mathpix headings are corrected before chunk labels are set.
        _corrections = corrected_headings or {}
        section_title = _corrections.get(section_title_raw, section_title_raw)
        if section_title != section_title_raw:
            logger.info(
                "[correction] Hardcoded path %s %s: '%s' → '%s'",
                book_slug, f"{chapter_num}.{section_in_chapter}",
                section_title_raw, section_title,
            )
        section_number = f"{chapter_num}.{section_in_chapter}"
        section_label = f"{section_number} {section_title}"
        concept_id = f"{book_slug}_{section_number}"
        section_matches.append({
            "start": m.start(),
            "end": m.end(),
            "chapter": chapter_num,
            "section_in_chapter": section_in_chapter,
            "section_number": section_number,
            "section_label": section_label,
            "concept_id": concept_id,
        })

    logger.info("Found %d section heading occurrences (before section-level dedup)", len(section_matches))

    # ── Quick TOC whitelist (hardcoded path only) ─────────────────────────
    # When no profile is supplied, do a lightweight TOC parse to filter
    # fake sections. This makes --parse-only correct for any book.
    from extraction.ocr_validator import parse_toc as _parse_toc
    _toc_entries = _parse_toc(mmd_text)
    if _toc_entries:
        _toc_set = {e.section_number for e in _toc_entries}
        _pre = len(section_matches)
        section_matches = [s for s in section_matches if s["section_number"] in _toc_set]
        _dropped = _pre - len(section_matches)
        if _dropped > 0:
            logger.info("[hardcoded] TOC whitelist: dropped %d fake sections (kept %d)", _dropped, len(section_matches))

    # ── Section-level dedup (replaces old backward-number filter) ─────────────
    # Group by section_number, keep the occurrence with the longest body.
    # This correctly handles Mathpix 3-copy duplication (TOC, body, review)
    # by always selecting the body copy (most words).
    section_matches = _dedup_section_matches(section_matches, mmd_text)

    # ── Filter fake sections (exercise numbers with tiny bodies) ─────────────
    filtered_matches: list[dict] = []
    for i, sec in enumerate(section_matches):
        body_start = sec["end"]
        body_end = section_matches[i + 1]["start"] if i + 1 < len(section_matches) else len(mmd_text)
        body_words = _word_count(mmd_text[body_start:body_end])
        if body_words >= MIN_SECTION_BODY_WORDS:
            filtered_matches.append(sec)
        else:
            logger.info(
                "Skipping short fake section %s.%s (%d words) — likely exercise number",
                sec["chapter"], sec["section_in_chapter"], body_words,
            )
    section_matches = filtered_matches
    logger.info("Section candidates after exercise-number filter: %d", len(section_matches))

    # ── Step 1c: Detect chapter intro boundaries ─────────────────────────────
    # Chapters have intro content (title, images, objectives) BEFORE section X.1.
    # Detect chapter headings in ALL formats Mathpix produces:
    #   Markdown: "## N | TITLE", "## N <br> TITLE", "## N: TITLE", "## N TITLE"
    #   LaTeX:    "\section*{N | TITLE}", "\section*{N}", "\section*{N TITLE}"
    _CHAPTER_HEADING_PATTERNS = [
        re.compile(r"^#{1,4}\s+(\d+)\s*(?:[|:<]|\s+[A-Z])", re.MULTILINE),  # ## N | Title, ## N <br>, ## N Title
        re.compile(r"^#{1,4}\s+(\d+)\s*$", re.MULTILINE),                   # ## N (bare number, end of line)
        re.compile(r"^\\\\section\*\{(\d+)(?:\s*[|]|\s*\})", re.MULTILINE),  # \section*{N} or \section*{N | Title}
    ]
    _chapter_intro_pos: dict[int, int] = {}  # chapter_num → start position of chapter heading
    for _pat in _CHAPTER_HEADING_PATTERNS:
        for _cm in _pat.finditer(mmd_text):
            _ch = int(_cm.group(1))
            if _ch not in _chapter_intro_pos:
                _chapter_intro_pos[_ch] = _cm.start()

    _first_section_idx: dict[int, int] = {}  # chapter_num → index in section_matches
    for _si, _sec in enumerate(section_matches):
        if _sec["chapter"] not in _first_section_idx:
            _first_section_idx[_sec["chapter"]] = _si

    # ── Step 2: Split each section's body into subsection chunks ─────────────
    raw_chunks: list[ParsedChunk] = []
    global_order = 0  # monotone counter; reset after dedup
    total_body_chars = 0  # coverage tracking

    for i, sec in enumerate(section_matches):
        # Body spans from end of section heading to start of next section heading
        body_start = sec["end"]
        body_end = section_matches[i + 1]["start"] if i + 1 < len(section_matches) else len(mmd_text)

        # First section of chapter → extend backward to include chapter intro
        if _first_section_idx.get(sec["chapter"]) == i:
            ch_intro = _chapter_intro_pos.get(sec["chapter"])
            if ch_intro is not None and ch_intro < sec["start"]:
                body_start = ch_intro

        # Last section before chapter change → trim at next chapter heading
        if i + 1 < len(section_matches):
            next_ch = section_matches[i + 1]["chapter"]
            if next_ch != sec["chapter"] and next_ch in _chapter_intro_pos:
                body_end = min(body_end, _chapter_intro_pos[next_ch])

        total_body_chars += len(mmd_text[body_start:body_end])

        body = mmd_text[body_start:body_end]

        # Find MEANINGFUL ## subsection headings within the body
        # (noise headings are skipped — they become body content of the surrounding chunk)
        meaningful_subs: list[tuple[int, int, str]] = []  # (match_start, match_end, heading_text)
        for hm in SUBHEADING_PATTERN.finditer(body):
            heading_text = hm.group(1).strip()
            # Skip if this is a section-level heading (X.Y) — shouldn't appear in body
            if re.match(r"^\d+\.\d+\s", heading_text):
                continue
            # Skip noise headings
            if _is_noise_heading(heading_text):
                continue
            meaningful_subs.append((hm.start(), hm.end(), heading_text))

        # Tag headings inside the exercises zone with "(Exercises)" suffix.
        # Zone trigger headings (e.g. "SECTION 1.1 EXERCISES", "Chapter Review") set
        # the flag but are NOT added to tagged_subs — they create no chunk because
        # they contain zero instructional content (pure organizational dividers).
        #
        # Some books (e.g. college_algebra) place exercises as a separate top-level
        # section titled "1.1 SECTION EXERCISES" — seed the zone from the section title.
        in_exercises_zone = bool(_SECTION_IS_EXERCISE_PATTERN.search(sec["section_label"]))
        tagged_subs: list[tuple[int, int, str]] = []
        for (sh_start, sh_end, heading_text) in meaningful_subs:
            _norm = _normalize_heading(heading_text)
            if _EXERCISE_ZONE_PATTERN.match(_norm):
                # Set zone flag; do NOT create a chunk for this organizational marker
                in_exercises_zone = True
            elif in_exercises_zone:
                tagged_subs.append((sh_start, sh_end, heading_text + " (Exercises)"))
            else:
                tagged_subs.append((sh_start, sh_end, heading_text))
        meaningful_subs = tagged_subs

        if not meaningful_subs:
            # Case 3: no meaningful sub-headings → whole body is one chunk
            text = body.strip()
            if text:
                _ctype, _opt = _classify_chunk(sec["section_label"], in_exercises_zone, sec["section_label"])
                # Extract images and latex BEFORE cleaning so no refs are lost
                _images = _extract_image_urls(text)
                _captions = _extract_image_captions(text, len(_images))
                _latex = _extract_latex(text)
                raw_chunks.append(ParsedChunk(
                    book_slug=book_slug,
                    concept_id=sec["concept_id"],
                    section=sec["section_label"],
                    order_index=global_order,
                    heading=sec["section_label"],
                    text=_clean_chunk_text(text),
                    latex=_latex,
                    image_urls=_images,
                    image_captions=_captions,
                    chunk_type=_ctype,
                    is_optional=_opt,
                ))
                global_order += 1
            continue

        # Capture orphan text (section intro before first subheading) — will be prepended to first chunk
        first_sub_start = meaningful_subs[0][0]
        orphan_text = body[:first_sub_start].strip()

        # Case 1: each meaningful sub-heading → one chunk
        # The chunk text spans from the ## heading line through all body content until
        # the next meaningful ## heading (or end of section). Noise headings inside
        # are naturally included in the text because we skip them as boundaries.
        for j, (sh_start, sh_end, heading_text) in enumerate(meaningful_subs):
            content_end = meaningful_subs[j + 1][0] if j + 1 < len(meaningful_subs) else len(body)
            chunk_text = body[sh_start:content_end].strip()
            # Prepend section intro to the first subsection chunk
            if j == 0 and orphan_text:
                chunk_text = orphan_text + "\n\n" + chunk_text
                logger.info(
                    "Prepending %d chars of section intro to first subsection '%s'",
                    len(orphan_text), heading_text[:40],
                )
            if not chunk_text:
                continue
            # Determine if this heading is in the exercise zone
            # (exercise headings were tagged with " (Exercises)" in the loop above)
            _in_zone = heading_text.endswith(" (Exercises)")
            _ctype, _opt = _classify_chunk(heading_text, _in_zone, sec["section_label"])
            # Extract images and latex BEFORE cleaning so no refs are lost
            _images = _extract_image_urls(chunk_text)
            _captions = _extract_image_captions(chunk_text, len(_images))
            _latex = _extract_latex(chunk_text)
            raw_chunks.append(ParsedChunk(
                book_slug=book_slug,
                concept_id=sec["concept_id"],
                section=sec["section_label"],
                order_index=global_order,
                heading=heading_text,
                text=_clean_chunk_text(chunk_text),
                latex=_latex,
                image_urls=_images,
                image_captions=_captions,
                chunk_type=_ctype,
                is_optional=_opt,
            ))
            global_order += 1

    logger.info("Raw chunks before dedup: %d", len(raw_chunks))

    # ── Step 3: 3-copy deduplication ─────────────────────────────────────────
    # Key = (concept_id, heading); keep the occurrence with the most words.
    # This mirrors the strategy in mmd_parser.py (seen dict, max-words wins).
    seen: dict[tuple[str, str], ParsedChunk] = {}
    for chunk in raw_chunks:
        key = (chunk.concept_id, chunk.heading)
        existing = seen.get(key)
        if existing is None or _word_count(chunk.text) > _word_count(existing.text):
            seen[key] = chunk

    deduped = list(seen.values())

    # ── Step 3b: Merge tiny chunks into adjacent chunks ──────────────────────
    # Chunks with < 20 words (e.g. "Introduction", "Chapter Objectives") have
    # no teaching value on their own. Merge them into the next chunk in the same section.
    _merged: list[ParsedChunk] = []
    for _mi, _chunk in enumerate(deduped):
        _word_ct = len(_chunk.text.split())
        if (_word_ct < 50
                and _mi + 1 < len(deduped)
                and deduped[_mi + 1].concept_id == _chunk.concept_id):
            # Forward merge into next subsection within same section
            deduped[_mi + 1].text = _chunk.text + "\n\n" + deduped[_mi + 1].text
            deduped[_mi + 1].image_urls = _chunk.image_urls + deduped[_mi + 1].image_urls
            deduped[_mi + 1].latex = _chunk.latex + deduped[_mi + 1].latex
            logger.info(
                "Merged tiny chunk '%s' (%d words, %d images) forward into next subsection",
                _chunk.heading[:40], _word_ct, len(_chunk.image_urls),
            )
        elif (_word_ct < 50
              and _merged
              and _merged[-1].concept_id == _chunk.concept_id):
            # Backward merge into previous subsection within same section
            _merged[-1].text += "\n\n" + _chunk.text
            _merged[-1].image_urls += _chunk.image_urls
            _merged[-1].latex += _chunk.latex
            logger.info(
                "Merged tiny chunk '%s' (%d words, %d images) backward into previous subsection",
                _chunk.heading[:40], _word_ct, len(_chunk.image_urls),
            )
        else:
            # Keep as standalone — NEVER drop content
            _merged.append(_chunk)
    deduped = _merged

    # ── Step 4: Re-sort by original reading order and re-number ──────────────
    # The winner of each dedup group retains its order_index from the body-copy
    # (which has the most words — the canonical body occurrence).
    deduped.sort(key=lambda c: c.order_index)
    for new_idx, chunk in enumerate(deduped):
        chunk.order_index = new_idx

    logger.info(
        "Chunks after dedup: %d (removed %d duplicates)",
        len(deduped), len(raw_chunks) - len(deduped),
    )

    # ── Coverage check (same as profile-driven path) ─────────────────────────
    if total_body_chars > 0:
        coverage = _check_coverage(total_body_chars, deduped)
        logger.info("Coverage check: %.1f%% of body chars assigned to chunks", coverage * 100)
        if coverage < 0.95:
            logger.warning(
                "Coverage below 95%% for book %s (%.1f%%) — some body text may be unassigned",
                book_slug, coverage * 100,
            )

    return deduped


# ── Multi-signal patterns (profile-driven path only) ─────────────────────────
# These are only referenced by _parse_book_mmd_with_profile; the existing
# hardcoded path above uses SUBHEADING_PATTERN exclusively.

_H1_PATTERN = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_H2_PATTERN = re.compile(r"^##\s+(.+)$", re.MULTILINE)   # same as SUBHEADING_PATTERN
_H3_PATTERN = re.compile(r"^###\s+(.+)$", re.MULTILINE)
_H4_PATTERN = re.compile(r"^####\s+(.+)$", re.MULTILINE)
_BOLD_LINE_PATTERN = re.compile(r"^\*\*([^*\n]{3,80})\*\*\s*$", re.MULTILINE)
_CAPS_LINE_PATTERN = re.compile(r"^([A-Z][A-Z\s]{2,79})$", re.MULTILINE)
_NUMBERED_ITEM_PATTERN = re.compile(r"^([A-Z]\.\s+\S.{0,60})$", re.MULTILINE)  # "A. Title" style

# Maps signal_type string → compiled pattern
_SIGNAL_PATTERN_MAP: dict[str, re.Pattern] = {
    "heading_h2": _H2_PATTERN,
    "heading_h3": _H3_PATTERN,
    "heading_h4": _H4_PATTERN,
    "bold_line":  _BOLD_LINE_PATTERN,
    "caps_line":  _CAPS_LINE_PATTERN,
    "numbered":   _NUMBERED_ITEM_PATTERN,
}


def _is_noise_heading_profile(heading_text: str, compiled_noise: list[re.Pattern]) -> bool:
    """Return True if heading matches any profile-driven noise pattern."""
    return any(p.search(heading_text) for p in compiled_noise)


def _check_coverage(raw_body_chars: int, chunks: list[ParsedChunk]) -> float:
    """Return fraction of body chars covered by chunks (informational only)."""
    covered = sum(len(c.text) for c in chunks)
    ratio = covered / raw_body_chars if raw_body_chars > 0 else 1.0
    return ratio


def _split_large_chunk(chunk: ParsedChunk, max_words: int, book_slug: str) -> list[ParsedChunk]:
    """Split a chunk exceeding max_words at natural paragraph boundaries.

    Returns a single-element list when no split is needed.  Sub-chunks inherit
    the parent's concept_id, section, chunk_type, and is_optional; the heading
    of chunks after the first gets a "(part N)" suffix.  order_index values are
    left unchanged — the caller re-numbers after all splits are applied.
    """
    words = chunk.text.split()
    if len(words) <= max_words:
        return [chunk]

    # Split at double-newline paragraph boundaries
    paragraphs = re.split(r"\n\n+", chunk.text)
    parts: list[str] = []
    current_part: list[str] = []
    current_words = 0

    for para in paragraphs:
        para_words = len(para.split())
        if current_words + para_words > max_words and current_part:
            parts.append("\n\n".join(current_part))
            current_part = [para]
            current_words = para_words
        else:
            current_part.append(para)
            current_words += para_words

    if current_part:
        parts.append("\n\n".join(current_part))

    if len(parts) <= 1:
        return [chunk]

    result: list[ParsedChunk] = []
    for sub_idx, part_text in enumerate(parts):
        if not part_text.strip():
            continue
        sub_chunk = ParsedChunk(
            book_slug=chunk.book_slug,
            concept_id=chunk.concept_id,
            section=chunk.section,
            order_index=chunk.order_index,  # re-numbered by caller
            heading=chunk.heading if sub_idx == 0 else f"{chunk.heading} (part {sub_idx + 1})",
            text=part_text.strip(),
            latex=_extract_latex(part_text),
            image_urls=_extract_image_urls(part_text),
            chunk_type=chunk.chunk_type,
            is_optional=chunk.is_optional,
        )
        result.append(sub_chunk)
    return result


# ── Fuzzy section recovery (profile-driven path only) ────────────────────────

# Minimum SequenceMatcher ratio for a fuzzy title match to be accepted.
_FUZZY_TITLE_THRESHOLD = 0.75

# Matches a bare "X.Y" section number anywhere on a line (no # prefix required).
# Used by Strategy 1 of _fuzzy_recover_section().
_BARE_SECTION_NUMBER_RE = re.compile(r"(?:^|\s)(\d+)\.(\d+)(?:\s|$)", re.MULTILINE)


def _fuzzy_recover_section(
    section_number: str,
    expected_title: str,
    mmd_text: str,
    chapter_boundaries: dict,
    body_start_offset: int = 0,
) -> dict | None:
    """
    Attempt to locate a section whose heading was garbled or missing in the MMD.

    Three strategies applied in order; first match wins.

    Strategy 1 — Bare number scan:
        Search for the "X.Y" number pattern anywhere on a line (even without a #
        prefix). The garbled heading may still carry the correct section number.

    Strategy 2 — Fuzzy title match:
        For each markdown heading line in the body, compute SequenceMatcher.ratio()
        against expected_title. Match if ratio >= _FUZZY_TITLE_THRESHOLD.

    Strategy 3 — Chapter-bounded bold/caps scan:
        Within the character range for the expected chapter, search for **bold** or
        ALL-CAPS text that starts with the same first word as expected_title.

    Args:
        section_number:     "X.Y" string for the section to recover.
        expected_title:     Title from the TOC (authoritative).
        mmd_text:           Full normalized MMD text.
        chapter_boundaries: Dict of chapter_num → char offset of first known section.
        body_start_offset:  Minimum character offset for a valid match. Any candidate
                            found before this offset is in front matter (TOC listings,
                            preface, etc.) and should be skipped.

    Returns:
        dict with keys {start, end, section_number, section_title, recovered_by}
        or None if no strategy found a match.
    """
    chapter_num, section_in_chapter = (int(x) for x in section_number.split("."))

    # ── Strategy 1: bare section number on any line ──────────────────────────
    for m in _BARE_SECTION_NUMBER_RE.finditer(mmd_text):
        if int(m.group(1)) == chapter_num and int(m.group(2)) == section_in_chapter:
            line_start = mmd_text.rfind("\n", 0, m.start()) + 1
            if line_start < body_start_offset:
                logger.debug(
                    "[recovery] skipping front-matter match at offset %d for section %s",
                    line_start, section_number,
                )
                continue
            line_end = mmd_text.find("\n", m.end())
            if line_end == -1:
                line_end = len(mmd_text)
            line_text = mmd_text[line_start:line_end].strip()
            logger.info(
                "[recovery:S1] Recovered section %s at offset %d via bare number: '%s'",
                section_number, line_start, line_text[:80],
            )
            return {
                "start": line_start,
                "end": line_end,
                "section_number": section_number,
                "section_title": expected_title,  # use TOC title (authoritative)
                "recovered_by": "bare_number",
            }

    # ── Strategy 2: fuzzy title match against heading lines ─────────────────
    for m in re.finditer(r"^(#{1,4})\s+(.+)$", mmd_text, re.MULTILINE):
        if m.start() < body_start_offset:
            logger.debug(
                "[recovery] skipping front-matter match at offset %d for section %s",
                m.start(), section_number,
            )
            continue
        heading_text = m.group(2).strip()
        ratio = SequenceMatcher(None, heading_text.lower(), expected_title.lower()).ratio()
        if ratio >= _FUZZY_TITLE_THRESHOLD:
            logger.info(
                "[recovery:S2] Recovered section %s via fuzzy title match (ratio=%.2f): '%s'",
                section_number, ratio, heading_text[:80],
            )
            return {
                "start": m.start(),
                "end": m.end(),
                "section_number": section_number,
                "section_title": expected_title,
                "recovered_by": f"fuzzy_title:{ratio:.2f}",
            }

    # ── Strategy 3: chapter-bounded bold/caps text ───────────────────────────
    chapter_start = max(chapter_boundaries.get(chapter_num, 0), body_start_offset)
    chapter_end = chapter_boundaries.get(chapter_num + 1, len(mmd_text))
    chapter_body = mmd_text[chapter_start:chapter_end]
    first_word = expected_title.split()[0].lower() if expected_title.split() else ""

    if first_word:
        for m in re.finditer(r"^\*\*(.+)\*\*$|^([A-Z][A-Z\s]{2,})$", chapter_body, re.MULTILINE):
            candidate = (m.group(1) or m.group(2) or "").strip()
            if candidate.lower().startswith(first_word):
                abs_start = chapter_start + m.start()
                abs_end = chapter_start + m.end()
                logger.info(
                    "[recovery:S3] Recovered section %s via bold/caps in chapter %d: '%s'",
                    section_number, chapter_num, candidate[:80],
                )
                return {
                    "start": abs_start,
                    "end": abs_end,
                    "section_number": section_number,
                    "section_title": expected_title,
                    "recovered_by": "caps_bold",
                }

    logger.warning(
        "[recovery:FAIL] Could not recover section %s ('%s') — skipped",
        section_number, expected_title,
    )
    return None


def _parse_book_mmd_with_profile(mmd_text: str, book_slug: str, profile) -> list[ParsedChunk]:
    """
    Profile-driven parser for non-math books.

    Behaviour differences from the hardcoded path:
    - Boundary signals: driven by profile.subsection_signals (may include h3/h4/bold/caps)
    - Noise filtering: driven by profile.noise_patterns + profile.feature_box_patterns
    - Exercise detection: driven by profile.exercise_markers
    - max_sections_per_chapter: from profile.max_sections_per_chapter
    - min body words threshold: from profile.min_chunk_words
    - Post-processing: large chunks split at profile.max_chunk_words
    - Coverage check: warns if < 95% of instructional body text is assigned
    """
    # ── Compile profile noise patterns once ──────────────────────────────────
    # noise_patterns: headings to skip entirely
    # feature_box_patterns: recurring box headings — keep inline, never split
    compiled_noise: list[re.Pattern] = []
    for pat_str in profile.noise_patterns:
        try:
            compiled_noise.append(re.compile(pat_str, re.IGNORECASE))
        except re.error as exc:
            logger.warning("Invalid noise_pattern %r in profile %s: %s", pat_str, book_slug, exc)
    for pat_str in profile.feature_box_patterns:
        try:
            compiled_noise.append(re.compile(pat_str, re.IGNORECASE))
        except re.error as exc:
            logger.warning("Invalid feature_box_pattern %r in profile %s: %s", pat_str, book_slug, exc)

    # ── Compile exercise markers ──────────────────────────────────────────────
    compiled_exercise_markers: list[tuple[re.Pattern, str]] = []
    for marker in profile.exercise_markers:
        try:
            compiled_exercise_markers.append(
                (re.compile(marker.pattern, re.IGNORECASE), marker.behavior)
            )
        except re.error as exc:
            logger.warning(
                "Invalid exercise_marker pattern %r in profile %s: %s",
                marker.pattern, book_slug, exc,
            )

    # ── Build active boundary patterns from profile signals ───────────────────
    # Only signals with is_boundary=True are treated as chunk split points.
    active_signal_patterns: list[re.Pattern] = []
    for signal in profile.subsection_signals:
        if not signal.is_boundary:
            continue
        pat = _SIGNAL_PATTERN_MAP.get(signal.signal_type)
        if pat is None:
            logger.warning(
                "Unknown signal_type %r in profile %s — skipping",
                signal.signal_type, book_slug,
            )
            continue
        active_signal_patterns.append(pat)

    # If the profile declares no boundary signals, fall back to ## headings.
    if not active_signal_patterns:
        logger.warning(
            "Profile %s has no is_boundary=True signals — using ## headings as default",
            book_slug,
        )
        active_signal_patterns = [_H2_PATTERN]

    max_section_in_chapter: int = profile.max_sections_per_chapter
    min_body_words: int = profile.min_chunk_words
    max_chunk_words: int = profile.max_chunk_words

    # ── Step 1: Find all X.Y section headings ────────────────────────────────
    section_matches: list[dict] = []
    corrected_headings = getattr(profile, "corrected_headings", {}) or {}
    # When a TOC whitelist is available, the TOC is the authority for which
    # sections are real — the arbitrary max_sections_per_chapter cap must not
    # drop legitimate high-numbered sections (e.g. section 1.12 in nursing books).
    has_toc = bool(profile.toc_sections)

    for m in SECTION_PATTERN.finditer(mmd_text):
        chapter_num = int(m.group(2))
        section_in_chapter = int(m.group(3))
        if section_in_chapter > max_section_in_chapter:
            if has_toc:
                # TOC whitelist is the authority — bypass the arbitrary cap.
                # Fix 2 will reject any section not present in the TOC.
                logger.debug(
                    "[profile] TOC whitelist active — skipping max_section_in_chapter cap for %d.%d",
                    chapter_num, section_in_chapter,
                )
            else:
                # No TOC: apply the heuristic cap to reject fake sections.
                continue
        section_title_raw = m.group(4).strip()
        # Apply OCR heading correction if profile provides corrections
        section_title = corrected_headings.get(section_title_raw, section_title_raw)
        if section_title != section_title_raw:
            logger.info(
                "[correction] Section %s.%s: '%s' → '%s'",
                chapter_num, section_in_chapter, section_title_raw, section_title,
            )
        section_number = f"{chapter_num}.{section_in_chapter}"
        section_label = f"{section_number} {section_title}"
        concept_id = f"{book_slug}_{section_number}"
        section_matches.append({
            "start": m.start(),
            "end": m.end(),
            "chapter": chapter_num,
            "section_in_chapter": section_in_chapter,
            "section_number": section_number,
            "section_label": section_label,
            "concept_id": concept_id,
        })

    logger.info(
        "[profile] Found %d section heading occurrences (before dedup)", len(section_matches)
    )

    # ── Section-level dedup (replaces old backward-number filter) ─────────────
    section_matches = _dedup_section_matches(section_matches, mmd_text)

    # ── Filter fake sections (exercise numbers with tiny bodies) ─────────────
    filtered_matches: list[dict] = []
    for i, sec in enumerate(section_matches):
        body_start = sec["end"]
        body_end = (
            section_matches[i + 1]["start"] if i + 1 < len(section_matches) else len(mmd_text)
        )
        body_words = _word_count(mmd_text[body_start:body_end])
        if body_words >= min_body_words:
            filtered_matches.append(sec)
        else:
            logger.debug(
                "[profile] Skipping short fake section %s.%s (%d words)",
                sec["chapter"], sec["section_in_chapter"], body_words,
            )
    section_matches = filtered_matches
    logger.info("[profile] Section candidates after filters: %d", len(section_matches))

    # ── TOC Whitelist: drop regex matches not in TOC ──────────────────────────
    # When the TOC is available, it is the sole authority for which section
    # numbers are real instructional sections. Any section_number produced by
    # the regex that does not appear in the TOC is noise (exercise numbers,
    # figure references, etc.) and must be rejected before recovery.
    if profile.toc_sections:
        toc_set: set[str] = {
            str(entry.get("section_number", ""))
            for entry in profile.toc_sections
        }
        pre_whitelist_count = len(section_matches)
        section_matches = [
            sec for sec in section_matches
            if sec["section_number"] in toc_set
        ]
        dropped = pre_whitelist_count - len(section_matches)
        if dropped > 0:
            logger.info(
                "[whitelist] %s: dropped %d fake sections not in TOC (kept %d)",
                book_slug, dropped, len(section_matches),
            )

    # ── Step 1b: Recover missing sections via TOC fuzzy search ───────────────
    # For each TOC section absent from the regex scan, try three fallback strategies
    # to locate the section's position in the MMD body.
    if profile.toc_sections:
        found_numbers = {sec["section_number"] for sec in section_matches}

        # Build chapter_boundaries from found sections as a position proxy.
        # Maps chapter_num → char offset of first known section in that chapter.
        chapter_boundaries: dict[int, int] = {}
        for sec in section_matches:
            ch = sec["chapter"]
            if ch not in chapter_boundaries:
                chapter_boundaries[ch] = sec["start"]

        # Compute body_start_offset to prevent recovery from matching front matter
        # (TOC page listings, preface, dedication, etc. that precede the body).
        # Use the earliest confirmed section heading position. If no confirmed
        # sections exist yet, fall back to a conservative fraction of the document.
        if section_matches:
            body_start_offset = min(s["start"] for s in section_matches)
        else:
            body_start_offset = len(mmd_text) // 10
            logger.warning(
                "[recovery] %s: no confirmed sections for body_start_offset; "
                "defaulting to %d chars",
                book_slug, body_start_offset,
            )

        recovered_count = 0
        for toc_entry in profile.toc_sections:
            sn = toc_entry.get("section_number", "")
            title = toc_entry.get("title", "")
            if not sn or sn in found_numbers:
                continue
            if not title:
                continue

            result = _fuzzy_recover_section(
                sn, title, mmd_text, chapter_boundaries,
                body_start_offset=body_start_offset,
            )
            if result is not None:
                ch = int(sn.split(".")[0])
                sec_in_ch = int(sn.split(".")[1])
                section_matches.append({
                    "start": result["start"],
                    "end": result["end"],
                    "chapter": ch,
                    "section_in_chapter": sec_in_ch,
                    "section_number": sn,
                    "section_label": f"{sn} {result['section_title']}",
                    "concept_id": f"{book_slug}_{sn}",
                })
                found_numbers.add(sn)
                recovered_count += 1

        # Re-sort by document position after inserting recovered sections
        if recovered_count > 0:
            section_matches.sort(key=lambda s: s["start"])

        logger.info(
            "[coverage] %s: TOC has %d sections; regex found %d; recovered %d; total %d",
            book_slug,
            len(profile.toc_sections),
            len(found_numbers) - recovered_count,
            recovered_count,
            len(section_matches),
        )
        missed = len(profile.toc_sections) - len(section_matches)
        if missed > 0:
            logger.warning(
                "[coverage] %s: %d TOC sections still unrecoverable after fuzzy search",
                book_slug, missed,
            )

    # ── Detect chapter intro positions ───────────────────────────────────────
    # Universal detection: Markdown + LaTeX chapter heading formats
    _CHAPTER_HEADING_PATTERNS = [
        re.compile(r"^#{1,4}\s+(\d+)\s*(?:[|:<]|\s+[A-Z])", re.MULTILINE),
        re.compile(r"^#{1,4}\s+(\d+)\s*$", re.MULTILINE),
        re.compile(r"^\\\\section\*\{(\d+)(?:\s*[|]|\s*\})", re.MULTILINE),
    ]
    _chapter_intro_pos: dict[int, int] = {}
    for _pat in _CHAPTER_HEADING_PATTERNS:
        for _cm in _pat.finditer(mmd_text):
            _ch = int(_cm.group(1))
            if _ch not in _chapter_intro_pos:
                _chapter_intro_pos[_ch] = _cm.start()

    _first_section_idx: dict[int, int] = {}
    for _si, _sec in enumerate(section_matches):
        if _sec["chapter"] not in _first_section_idx:
            _first_section_idx[_sec["chapter"]] = _si

    # Track total instructional body chars for coverage check
    total_body_chars = 0

    # ── Step 2: Split each section's body into subsection chunks ─────────────
    raw_chunks: list[ParsedChunk] = []
    global_order = 0

    for i, sec in enumerate(section_matches):
        body_start = sec["end"]
        body_end = (
            section_matches[i + 1]["start"] if i + 1 < len(section_matches) else len(mmd_text)
        )

        # Extend backward to include chapter intro for the first section
        if _first_section_idx.get(sec["chapter"]) == i:
            ch_intro = _chapter_intro_pos.get(sec["chapter"])
            if ch_intro is not None and ch_intro < sec["start"]:
                body_start = ch_intro

        # Trim at next chapter heading when chapter changes
        if i + 1 < len(section_matches):
            next_ch = section_matches[i + 1]["chapter"]
            if next_ch != sec["chapter"] and next_ch in _chapter_intro_pos:
                body_end = min(body_end, _chapter_intro_pos[next_ch])

        body = mmd_text[body_start:body_end]
        total_body_chars += len(body)

        # ── Multi-signal boundary collection ─────────────────────────────────
        # Gather ALL matches from all active signal patterns, tagged with position.
        # Each entry: (match_start_in_body, match_end_in_body, heading_text)
        all_candidates: list[tuple[int, int, str]] = []
        for pat in active_signal_patterns:
            for hm in pat.finditer(body):
                # group(1) is the captured heading text for all patterns
                heading_text = hm.group(1).strip()
                all_candidates.append((hm.start(), hm.end(), heading_text))

        # Sort by position so splits happen in reading order
        all_candidates.sort(key=lambda t: t[0])

        # ── Noise filtering ───────────────────────────────────────────────────
        meaningful_subs: list[tuple[int, int, str]] = []
        for (sh_start, sh_end, heading_text) in all_candidates:
            # Skip X.Y section headings that leaked into the body
            if re.match(r"^\d+\.\d+\s", heading_text):
                continue
            # Skip profile-defined noise / feature-box headings AND universal noise patterns
            if _is_noise_heading_profile(heading_text, compiled_noise) or _is_noise_heading(heading_text):
                continue
            meaningful_subs.append((sh_start, sh_end, heading_text))

        # ── Exercise zone tagging (profile-driven) ────────────────────────────
        # Seed from the section label itself (same as hardcoded path)
        in_exercises_zone = _check_is_exercise_section_profile(
            sec["section_label"], compiled_exercise_markers
        )
        tagged_subs: list[tuple[int, int, str]] = []
        for (sh_start, sh_end, heading_text) in meaningful_subs:
            _norm = _normalize_heading(heading_text)
            ex_behavior = _match_exercise_marker(_norm, compiled_exercise_markers)
            if ex_behavior in ("zone_section_end", "zone_chapter_end"):
                # Organizational divider — set zone flag, no chunk
                in_exercises_zone = True
            elif ex_behavior == "inline_single":
                # Single exercise heading — becomes exercise chunk, does not set zone
                tagged_subs.append((sh_start, sh_end, heading_text + " (Exercises)"))
            elif in_exercises_zone:
                tagged_subs.append((sh_start, sh_end, heading_text + " (Exercises)"))
            else:
                tagged_subs.append((sh_start, sh_end, heading_text))
        meaningful_subs = tagged_subs

        if not meaningful_subs:
            # No meaningful sub-headings → whole body is one chunk
            text = body.strip()
            if text:
                _ctype, _opt = _classify_chunk(
                    sec["section_label"], in_exercises_zone, sec["section_label"]
                )
                _images = _extract_image_urls(text)
                _latex = _extract_latex(text)
                raw_chunks.append(
                    ParsedChunk(
                        book_slug=book_slug,
                        concept_id=sec["concept_id"],
                        section=sec["section_label"],
                        order_index=global_order,
                        heading=sec["section_label"],
                        text=_clean_chunk_text(text),
                        latex=_latex,
                        image_urls=_images,
                        chunk_type=_ctype,
                        is_optional=_opt,
                    )
                )
                global_order += 1
            continue

        # Capture orphan intro text before the first boundary
        first_sub_start = meaningful_subs[0][0]
        orphan_text = body[:first_sub_start].strip()

        for j, (sh_start, sh_end, heading_text) in enumerate(meaningful_subs):
            content_end = (
                meaningful_subs[j + 1][0] if j + 1 < len(meaningful_subs) else len(body)
            )
            chunk_text = body[sh_start:content_end].strip()
            if j == 0 and orphan_text:
                chunk_text = orphan_text + "\n\n" + chunk_text
            if not chunk_text:
                continue
            # Apply OCR correction to subsection heading if available
            _exercises_suffix = ""
            if heading_text.endswith(" (Exercises)"):
                _exercises_suffix = " (Exercises)"
                _bare_heading = heading_text[: -len(" (Exercises)")]
            else:
                _bare_heading = heading_text
            _corrected_bare = corrected_headings.get(_bare_heading, _bare_heading)
            heading_text = _corrected_bare + _exercises_suffix
            _in_zone = heading_text.endswith(" (Exercises)")
            _ctype, _opt = _classify_chunk(heading_text, _in_zone, sec["section_label"])
            _images = _extract_image_urls(chunk_text)
            _latex = _extract_latex(chunk_text)
            raw_chunks.append(
                ParsedChunk(
                    book_slug=book_slug,
                    concept_id=sec["concept_id"],
                    section=sec["section_label"],
                    order_index=global_order,
                    heading=heading_text,
                    text=_clean_chunk_text(chunk_text),
                    latex=_latex,
                    image_urls=_images,
                    chunk_type=_ctype,
                    is_optional=_opt,
                )
            )
            global_order += 1

    logger.info("[profile] Raw chunks before dedup: %d", len(raw_chunks))

    # ── Step 3: 3-copy deduplication ─────────────────────────────────────────
    seen: dict[tuple[str, str], ParsedChunk] = {}
    for chunk in raw_chunks:
        key = (chunk.concept_id, chunk.heading)
        existing = seen.get(key)
        if existing is None or _word_count(chunk.text) > _word_count(existing.text):
            seen[key] = chunk

    deduped = list(seen.values())

    # ── Step 3b: Merge tiny chunks ────────────────────────────────────────────
    _merged: list[ParsedChunk] = []
    for _mi, _chunk in enumerate(deduped):
        if (
            len(_chunk.text.split()) < 50
            and _mi + 1 < len(deduped)
            and deduped[_mi + 1].concept_id == _chunk.concept_id
        ):
            deduped[_mi + 1].text = _chunk.text + "\n\n" + deduped[_mi + 1].text
            logger.debug("[profile] Merged tiny chunk '%s' into next chunk", _chunk.heading[:40])
        else:
            _merged.append(_chunk)
    deduped = _merged

    # ── Step 4: Re-sort by reading order ─────────────────────────────────────
    deduped.sort(key=lambda c: c.order_index)

    # ── Step 5: Split large chunks (profile-driven) ───────────────────────────
    # Any chunk exceeding profile.max_chunk_words is split at paragraph boundaries.
    split_result: list[ParsedChunk] = []
    for chunk in deduped:
        split_result.extend(_split_large_chunk(chunk, max_chunk_words, book_slug))

    # Re-number after potential splits
    for new_idx, chunk in enumerate(split_result):
        chunk.order_index = new_idx

    logger.info(
        "[profile] Chunks after dedup + split: %d (removed %d duplicates, split %d large)",
        len(split_result),
        len(raw_chunks) - len(seen),
        len(split_result) - len(deduped),
    )

    # ── Step 6: Coverage check ────────────────────────────────────────────────
    coverage = _check_coverage(total_body_chars, split_result)
    logger.info(
        "[profile] Coverage check: %.1f%% of body chars assigned to chunks",
        coverage * 100,
    )
    if coverage < 0.95:
        logger.warning(
            "[profile] Coverage below 95%% for book %s (%.1f%%) — some body text may be unassigned",
            book_slug, coverage * 100,
        )

    # ── TOC section coverage check ────────────────────────────────────────────
    if profile.toc_sections:
        chunked_concepts = {c.concept_id for c in split_result}
        expected_concepts = {f"{book_slug}_{s['section_number']}" for s in profile.toc_sections}
        missing = expected_concepts - chunked_concepts
        if missing:
            logger.warning(
                "[profile] %d TOC sections produced no chunks: %s",
                len(missing), sorted(missing)[:10],
            )
        else:
            logger.info(
                "[profile] TOC coverage: 100%% — all %d sections have chunks",
                len(expected_concepts),
            )

    return split_result


# ── Profile exercise-detection helpers ───────────────────────────────────────

def _match_exercise_marker(
    normalized_heading: str,
    compiled_markers: list[tuple[re.Pattern, str]],
) -> str | None:
    """Return the behavior string of the first matching exercise marker, or None."""
    for pat, behavior in compiled_markers:
        if pat.search(normalized_heading):
            return behavior
    return None


def _check_is_exercise_section_profile(
    section_label: str,
    compiled_markers: list[tuple[re.Pattern, str]],
) -> bool:
    """Return True if the section label itself signals an exercise section."""
    _norm = _normalize_heading(section_label)
    behavior = _match_exercise_marker(_norm, compiled_markers)
    return behavior in ("zone_section_end", "zone_chapter_end")


# ── CLI test runner ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    from config import OUTPUT_DIR

    mmd_path = OUTPUT_DIR / "prealgebra" / "book.mmd"
    if not mmd_path.exists():
        print(f"ERROR: {mmd_path} not found")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    chunks = parse_book_mmd(mmd_path, "prealgebra")

    print(f"\n{'='*60}")
    print(f"Total chunks: {len(chunks)}")
    print(f"{'='*60}")

    print("\nFirst 5 chunks:")
    for c in chunks[:5]:
        print(f"  [{c.order_index:03d}] {c.concept_id:20s}  '{c.heading[:50]}'  ({_word_count(c.text)} words)")

    # Find first chunk with an image URL
    image_chunk = next((c for c in chunks if c.image_urls), None)
    if image_chunk:
        print("\nSample chunk with image:")
        print(f"  concept_id  : {image_chunk.concept_id}")
        print(f"  heading     : {image_chunk.heading}")
        print(f"  image_urls  : {image_chunk.image_urls[:2]}")
        print(f"  latex count : {len(image_chunk.latex)}")
    else:
        print("\nNo chunks with image URLs found.")

    # Concept coverage
    unique_concepts = len({c.concept_id for c in chunks})
    print(f"\nUnique concept_ids: {unique_concepts}")
    print(f"Average chunks per concept: {len(chunks) / unique_concepts:.1f}")

    # Sample 10 chunks from chapter 1 to verify quality
    ch1_chunks = [c for c in chunks if c.concept_id.startswith("prealgebra_1.")]
    print(f"\nChapter 1 chunks ({len(ch1_chunks)} total):")
    for c in ch1_chunks[:15]:
        print(f"  [{c.order_index:03d}] {c.concept_id:20s}  '{c.heading[:55]}'  ({_word_count(c.text)}w, {len(c.image_urls)} imgs)")
