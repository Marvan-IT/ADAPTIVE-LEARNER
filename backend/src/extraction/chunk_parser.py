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
  Only MEANINGFUL headings cause a split. Noise headings (EXAMPLE, TRY IT,
  Solution, HOW TO, MANIPULATIVE, BE PREPARED, SECTION N.N EXERCISES, etc.) are
  treated as body content of the containing chunk. This keeps related example/solution
  pairs with their parent subsection rather than fragmenting them.

3-copy deduplication (critical):
  Mathpix emits each section ~3 times: TOC entry (~0 words), body (500-2000 words),
  chapter review stub (100-400 words). At the CHUNK level we group by
  (concept_id, heading) and keep whichever occurrence has the most words.

Universal architecture (single parse path):
  Both profile-driven and hardcoded logic flows through the same pipeline:
    _build_parse_config() → _find_sections() → _find_chapter_intros()
    → _build_section_chunks() → _postprocess_chunks()
  A profile object enriches the config dict; absence of a profile uses hardcoded defaults.
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

# Matches ## headings specifically (the default subsection-split level)
SUBHEADING_PATTERN = re.compile(r"^##\s+(.+)$", re.MULTILINE)

# CDN image URLs produced by Mathpix
IMAGE_URL_PATTERN = re.compile(r"!\[\]\((https://cdn\.mathpix\.com/[^)]+)\)")
LOCAL_IMAGE_PATTERN = re.compile(r"!\[\]\((\.\/images\/[^)]+)\)")
# LaTeX \includegraphics images from Mathpix figure environments
LATEX_IMAGE_PATTERN = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")

# Inline ($…$) and block ($$…$$) LaTeX — block must be checked first
LATEX_PATTERN = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.DOTALL)

# Real instructional sections have ≥30 words of intro; exercise stubs have 5–15.
MIN_SECTION_BODY_WORDS = 30

# ── Noise heading filters ─────────────────────────────────────────────────────
# These headings are NOT pedagogical subsection boundaries.
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
    re.compile(r"^\([a-z0-9]\)\s+Solution\b", re.IGNORECASE),  # "(a) Solution"
    re.compile(r"^\(\s*[A-Z]\s*\)?\s+Solution\b"),             # "( J Solution" — Mathpix OCR artifact
    # Headings that are just a single word in CAPS (usually markers)
    re.compile(r"^[A-Z]{2,}$"),
    # Numbered items mistakenly turned into headings
    re.compile(r"^\d+\.\s"),
    # Config-driven exclusions — stays in sync with config.py automatically
    *[re.compile(rf"^{re.escape(m)}\b", re.IGNORECASE) for m in CONTENT_EXCLUDE_MARKERS],
    re.compile(r"^LINK TO LEARNING\b", re.IGNORECASE),
    re.compile(r"^CHAPTER OUTLINE\b", re.IGNORECASE),
    re.compile(r"^INTRODUCTION\b$", re.IGNORECASE),
    re.compile(r"^LEARNING OBJECTIVES?\b", re.IGNORECASE),
    re.compile(r"^Before you get started", re.IGNORECASE),
    re.compile(r"^Problem\b", re.IGNORECASE),
    re.compile(r"^COLLABORATIVE EXERCISE\b", re.IGNORECASE),
    re.compile(r"^References\b", re.IGNORECASE),
    re.compile(r"^Key Terms\b", re.IGNORECASE),
    re.compile(r"^Chapter Review\b", re.IGNORECASE),
    re.compile(r"^Practice\b", re.IGNORECASE),
    re.compile(r"^Bringing It Together\b", re.IGNORECASE),
    re.compile(r"^NOTE\b", re.IGNORECASE),
    re.compile(r"^Activity\b", re.IGNORECASE),
    re.compile(r"^Check Your Understanding\b", re.IGNORECASE),
    re.compile(r"^Building Character\b", re.IGNORECASE),
    re.compile(r"^Sample Solution\b", re.IGNORECASE),
    re.compile(r"^Lesson Summary\b", re.IGNORECASE),
    re.compile(r"^Mini.Lesson\b", re.IGNORECASE),
    re.compile(r"^Lesson Overview\b", re.IGNORECASE),
    re.compile(r"^Additional Resources\b", re.IGNORECASE),
    re.compile(r"^Cool Down\b", re.IGNORECASE),
    re.compile(r"^Warm Up\b", re.IGNORECASE),
    re.compile(r"^Analysis\b", re.IGNORECASE),
    re.compile(r"^Checking In\b", re.IGNORECASE),
    re.compile(r"^MEDIA\b", re.IGNORECASE),
    re.compile(r"^PATIENT CONVERSATIONS\b", re.IGNORECASE),
    re.compile(r"^CLINICAL SAFETY\b", re.IGNORECASE),
    re.compile(r"^Are you ready for more\b", re.IGNORECASE),
    re.compile(r"^Extending Your Thinking\b", re.IGNORECASE),
    re.compile(r"^Verbal\b", re.IGNORECASE),
    re.compile(r"^Algebraic\b", re.IGNORECASE),
    re.compile(r"^Chapter Outline\b", re.IGNORECASE),
    re.compile(r"^Key Concepts\b", re.IGNORECASE),
    re.compile(r"^Formula Review\b", re.IGNORECASE),
    re.compile(r"^Homework\b", re.IGNORECASE),
    re.compile(r"^Solutions\b", re.IGNORECASE),
    re.compile(r"^Writing Exercises\b", re.IGNORECASE),
    re.compile(r"^Everyday Math\b", re.IGNORECASE),
    re.compile(r"^Mixed Practice\b", re.IGNORECASE),
    re.compile(r"^Review Exercises\b", re.IGNORECASE),
    re.compile(r"^Practice Test\b", re.IGNORECASE),
    re.compile(r"^BE PREPARED\b", re.IGNORECASE),
    re.compile(r"^Complete the following questions\b", re.IGNORECASE),
    re.compile(r"^Chapter\s+\d+$", re.IGNORECASE),   # "Chapter N" bare heading
]


def _is_noise_heading(heading_text: str) -> bool:
    """Return True if this heading is a noise marker, not a pedagogical subsection."""
    return any(p.match(heading_text) for p in _NOISE_HEADING_PATTERNS)


def _is_noise_heading_profile(heading_text: str, compiled_noise: list[re.Pattern]) -> bool:
    """Return True if heading matches any profile-driven noise pattern."""
    return any(p.search(heading_text) for p in compiled_noise)


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


# ── Section exercise zone patterns ───────────────────────────────────────────

# Patterns that mark the start of the exercise zone for a section.
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
    r"|in this section,?\s+you will"
    r"|by the end of this"
    r")",
    re.IGNORECASE,
)

# Detects section titles that ARE themselves exercise sections
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


def _check_coverage(raw_body_chars: int, chunks: list[ParsedChunk]) -> float:
    """Return fraction of body chars covered by chunks (informational only)."""
    covered = sum(len(c.text) for c in chunks)
    ratio = covered / raw_body_chars if raw_body_chars > 0 else 1.0
    return ratio


def _normalize_mmd_format(mmd_text: str) -> str:
    """
    Convert LaTeX-style headings to markdown-style headings for uniform parsing.

    Books like elementary_algebra, intermediate_algebra, college_algebra, and algebra_1
    use LaTeX heading syntax produced by Mathpix:
      \\subsection*{1.1 Title}     →  ### 1.1 Title   (section boundary, X.Y pattern)
      \\section*{Subsection Name}  →  ## Subsection Name   (pedagogical subsection)

    Markdown books (prealgebra) already use ### and ## — transformation is a no-op.
    Uses re.escape() to avoid \\s being misinterpreted as whitespace class.

    BUG 1 fix: bare-number subsections like \\subsection*{1.21} (exercise/example numbers)
    are converted to inline bold markers, NOT ### headings. Only subsections with
    a title after the number become ### headings.
    """
    _bs = re.escape("\\subsection*{")
    _be = re.escape("}")
    # Pattern A: real section heading — N.M followed by title text (space + letter/symbol)
    _SUBSEC_TITLED = re.compile("^" + _bs + r"(\d+\.\d+\s+\S.+?)" + _be, re.MULTILINE)
    # Pattern B: bare exercise/example number — N.M or N.MM alone (no title)
    _SUBSEC_BARE = re.compile("^" + _bs + r"(\d+\.\d+)" + _be + r"\s*$", re.MULTILINE)
    # Pattern C: non-numeric subsection — \subsection*{Title Text}
    _SUBSEC_OTHER = re.compile("^" + _bs + r"([^}]+?)" + _be, re.MULTILINE)

    # Order matters: match bare numbers FIRST (convert to inline marker, not heading)
    text = _SUBSEC_BARE.sub(r"**[EX \1]**", mmd_text)
    # Then convert titled sections to ### headings
    text = _SUBSEC_TITLED.sub(r"### \1", text)
    # Then convert remaining non-numeric subsections to ### headings
    text = _SUBSEC_OTHER.sub(r"### \1", text)

    # \section*{N.M} bare number → inline marker (same fix as subsection)
    _SEC_BARE = re.compile("^" + re.escape("\\section*{") + r"(\d+\.\d+)" + re.escape("}") + r"\s*$", re.MULTILINE)
    text = _SEC_BARE.sub(r"**[EX \1]**", text)
    # \section*{Title} → ## Title (all remaining section types)
    _SEC = re.compile("^" + re.escape("\\section*{") + r"(.+?)" + re.escape("}"), re.MULTILINE)
    text = _SEC.sub(r"## \1", text)
    return text


# ── Multi-signal patterns ─────────────────────────────────────────────────────

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

# Chapter heading patterns — universal, used by _find_chapter_intros()
_CHAPTER_HEADING_PATTERNS = [
    re.compile(r"^#{1,4}\s+(\d+)\s*(?:[|:<]|\s+[A-Z])", re.MULTILINE),
    re.compile(r"^#{1,4}\s+(\d+)\s*$", re.MULTILINE),
    re.compile("^" + re.escape("\\section*{") + r"(\d+)(?:\s*[|]|\s*\})", re.MULTILINE),
]


# ── Parse config builder ──────────────────────────────────────────────────────

def _build_parse_config(profile, corrected_headings: dict | None) -> dict:
    """
    Merge profile settings with hardcoded defaults into one config dict.

    When profile is None, all values fall back to the hardcoded defaults
    that have been used for the 16 OpenStax math books.

    Returns a dict with keys:
      noise_patterns        — list of compiled re.Pattern for heading noise
      exercise_markers      — list of (compiled Pattern, behavior_str) tuples
      min_body_words        — int: minimum body words for a valid section
      max_chunk_words       — int | None: split threshold for large chunks
      toc_sections          — list of TOC entry dicts | None
      corrected_headings    — dict: raw title → corrected title
      subsection_signals    — list of compiled re.Pattern for chunk split boundaries
      max_sections_per_chapter — int cap (bypassed when toc_sections present)
    """
    base_noise = list(_NOISE_HEADING_PATTERNS)  # copy so we can extend
    compiled_exercise_markers: list[tuple[re.Pattern, str]] = []
    subsection_signals: list[re.Pattern] = [_H2_PATTERN]  # default: ## headings only
    min_body_words = MIN_SECTION_BODY_WORDS
    max_chunk_words = None
    toc_sections = None
    corrections = dict(corrected_headings or {})
    max_sections_per_chapter = 99  # no effective cap by default

    if profile is not None:
        # Compile profile noise patterns
        for pat_str in profile.noise_patterns:
            try:
                base_noise.append(re.compile(pat_str, re.IGNORECASE))
            except re.error as exc:
                logger.warning("Invalid noise_pattern %r in profile: %s", pat_str, exc)
        for pat_str in profile.feature_box_patterns:
            try:
                base_noise.append(re.compile(pat_str, re.IGNORECASE))
            except re.error as exc:
                logger.warning("Invalid feature_box_pattern %r in profile: %s", pat_str, exc)

        # Compile exercise markers
        for marker in profile.exercise_markers:
            try:
                compiled_exercise_markers.append(
                    (re.compile(marker.pattern, re.IGNORECASE), marker.behavior)
                )
            except re.error as exc:
                logger.warning("Invalid exercise_marker pattern %r in profile: %s", marker.pattern, exc)

        # Build boundary signal patterns from profile
        active: list[re.Pattern] = []
        for signal in profile.subsection_signals:
            if not signal.is_boundary:
                continue
            pat = _SIGNAL_PATTERN_MAP.get(signal.signal_type)
            if pat is None:
                logger.warning("Unknown signal_type %r in profile — skipping", signal.signal_type)
                continue
            active.append(pat)
        if active:
            subsection_signals = active
        else:
            logger.warning("Profile has no is_boundary=True signals — using ## headings as default")

        min_body_words = profile.min_chunk_words
        max_chunk_words = profile.max_chunk_words
        toc_sections = profile.toc_sections or None
        max_sections_per_chapter = profile.max_sections_per_chapter

        # Profile-level heading corrections override caller-supplied corrections
        profile_corrections = getattr(profile, "corrected_headings", {}) or {}
        corrections = {**corrections, **profile_corrections}

    return {
        "noise_patterns": base_noise,
        "exercise_markers": compiled_exercise_markers,
        "min_body_words": min_body_words,
        "max_chunk_words": max_chunk_words,
        "toc_sections": toc_sections,
        "corrected_headings": corrections,
        "subsection_signals": subsection_signals,
        "max_sections_per_chapter": max_sections_per_chapter,
    }


# ── Section discovery ─────────────────────────────────────────────────────────

def _find_sections(mmd_text: str, book_slug: str, config: dict) -> list[dict]:
    """
    Find, dedup, and filter all X.Y section headings in mmd_text.

    Linear-walk dedup: iterate all SECTION_PATTERN matches; for each
    section_number keep the FIRST occurrence that has body_words >= min_body_words
    (the body copy always appears before the chapter-review stub in document order).
    After dedup, apply TOC whitelist, fuzzy recovery, and numeric sort.

    Returns list of section dicts sorted by (chapter, section_in_chapter).
    """
    corrections = config["corrected_headings"]
    min_body_words = config["min_body_words"]
    toc_sections = config["toc_sections"]
    max_section_in_chapter = config["max_sections_per_chapter"]
    has_toc = bool(toc_sections)

    # ── Collect all raw matches ───────────────────────────────────────────────
    all_matches: list[dict] = []
    for m in SECTION_PATTERN.finditer(mmd_text):
        chapter_num = int(m.group(2))
        section_in_chapter = int(m.group(3))
        if section_in_chapter > max_section_in_chapter and not has_toc:
            continue  # heuristic cap — only applies when no TOC whitelist
        section_title_raw = m.group(4).strip()
        section_title = corrections.get(section_title_raw, section_title_raw)
        if section_title != section_title_raw:
            logger.info(
                "[correction] %s %d.%d: '%s' → '%s'",
                book_slug, chapter_num, section_in_chapter,
                section_title_raw, section_title,
            )
        section_number = f"{chapter_num}.{section_in_chapter}"
        section_label = f"{section_number} {section_title}"
        concept_id = f"{book_slug}_{section_number}"
        all_matches.append({
            "start": m.start(),
            "end": m.end(),
            "chapter": chapter_num,
            "section_in_chapter": section_in_chapter,
            "section_number": section_number,
            "section_label": section_label,
            "concept_id": concept_id,
        })

    logger.info("Found %d section heading occurrences (before dedup)", len(all_matches))

    # ── Detect TOC region end ────────────────────────────────────────────────
    # The Table of Contents lists sections as "X.Y Title ..... PageNum".
    # Everything before the TOC end is TOC stubs — skip them.
    _toc_end = 0
    for _tm in re.finditer(r"^\d+\.\d+\s+.+?\.{3,}\s*\d+\s*$", mmd_text, re.MULTILINE):
        _toc_end = max(_toc_end, _tm.end())
    if _toc_end > 0:
        logger.info("TOC region detected, ends at char %d (%.1f%%)", _toc_end, _toc_end / len(mmd_text) * 100)

    # ── TOC-first dedup: for each section, find FIRST match AFTER the TOC ────
    # The body content always appears after the TOC. By starting from _toc_end,
    # we skip TOC stubs entirely and find the real teaching body for each section.
    seen: dict[str, dict] = {}
    for idx, sec in enumerate(all_matches):
        key = sec["section_number"]
        if key in seen:
            continue  # already found the first body occurrence
        if sec["start"] < _toc_end:
            continue  # skip TOC region matches
        body_start = sec["end"]
        body_end = all_matches[idx + 1]["start"] if idx + 1 < len(all_matches) else len(mmd_text)
        body_words = _word_count(mmd_text[body_start:body_end])
        if body_words >= min_body_words:
            seen[key] = sec
        else:
            logger.info(
                "Skipping short section %s (%d words) — likely exercise stub",
                key, body_words,
            )

    section_matches = list(seen.values())
    logger.info(
        "Section-level dedup: %d occurrences → %d unique sections",
        len(all_matches), len(section_matches),
    )

    # ── Quick TOC whitelist (hardcoded path: parse TOC from body) ─────────────
    if not has_toc:
        from extraction.ocr_validator import parse_toc as _parse_toc
        _toc_entries = _parse_toc(mmd_text)
        if _toc_entries:
            _toc_set = {e.section_number for e in _toc_entries}
            _pre = len(section_matches)
            section_matches = [s for s in section_matches if s["section_number"] in _toc_set]
            _dropped = _pre - len(section_matches)
            if _dropped > 0:
                logger.info(
                    "TOC whitelist: dropped %d fake sections (kept %d)",
                    _dropped, len(section_matches),
                )

    # ── Profile TOC whitelist ─────────────────────────────────────────────────
    if has_toc:
        toc_set: set[str] = {
            str(entry.get("section_number", ""))
            for entry in toc_sections
        }
        pre = len(section_matches)
        section_matches = [s for s in section_matches if s["section_number"] in toc_set]
        dropped = pre - len(section_matches)
        if dropped > 0:
            logger.info(
                "[whitelist] %s: dropped %d sections not in TOC (kept %d)",
                book_slug, dropped, len(section_matches),
            )

        # ── Fuzzy recovery for missing TOC sections ───────────────────────────
        found_numbers = {sec["section_number"] for sec in section_matches}
        chapter_boundaries: dict[int, int] = {}
        for sec in section_matches:
            ch = sec["chapter"]
            if ch not in chapter_boundaries:
                chapter_boundaries[ch] = sec["start"]

        body_start_offset = (
            min(s["start"] for s in section_matches)
            if section_matches
            else len(mmd_text) // 10
        )

        recovered_count = 0
        for toc_entry in toc_sections:
            sn = toc_entry.get("section_number", "")
            title = toc_entry.get("title", "")
            if not sn or sn in found_numbers or not title:
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

        if recovered_count > 0:
            section_matches.sort(key=lambda s: s["start"])

        logger.info(
            "[coverage] %s: TOC has %d sections; regex found %d; recovered %d; total %d",
            book_slug,
            len(toc_sections),
            len(found_numbers) - recovered_count,
            recovered_count,
            len(section_matches),
        )
        missed = len(toc_sections) - len(section_matches)
        if missed > 0:
            logger.warning(
                "[coverage] %s: %d TOC sections still unrecoverable after fuzzy search",
                book_slug, missed,
            )

    # ── Sort by numeric position (chapter, section_in_chapter) ───────────────
    section_matches.sort(key=lambda s: (s["chapter"], s["section_in_chapter"]))
    logger.info("Section candidates after all filters: %d", len(section_matches))
    return section_matches


def _find_chapter_intros(mmd_text: str) -> dict[int, int]:
    """
    Universal chapter heading detection.

    Returns dict mapping chapter_num → char_position of first chapter heading.
    Handles all heading formats Mathpix produces across all 16 books:
      Markdown: "## N | TITLE", "## N <br> TITLE", "## N: TITLE", "## N TITLE"
      LaTeX:    "\\section*{N | TITLE}", "\\section*{N}"
    """
    chapter_intro_pos: dict[int, int] = {}
    for _pat in _CHAPTER_HEADING_PATTERNS:
        for _cm in _pat.finditer(mmd_text):
            _ch = int(_cm.group(1))
            if _ch not in chapter_intro_pos:
                chapter_intro_pos[_ch] = _cm.start()
    return chapter_intro_pos


# ── Section body → chunks ─────────────────────────────────────────────────────

def _build_section_chunks(
    mmd_text: str,
    sections: list[dict],
    chapter_intros: dict[int, int],
    book_slug: str,
    config: dict,
) -> tuple[list[ParsedChunk], int]:
    """
    For each section in sections, extract its body text and split it into
    subsection chunks using the boundary signals in config.

    Returns (raw_chunks, total_body_chars).
    """
    subsection_signals: list[re.Pattern] = config["subsection_signals"]
    noise_patterns: list[re.Pattern] = config["noise_patterns"]
    exercise_markers: list[tuple[re.Pattern, str]] = config["exercise_markers"]
    corrections: dict = config["corrected_headings"]

    # First section index per chapter (for backward extension to chapter intro)
    first_section_idx: dict[int, int] = {}
    for si, sec in enumerate(sections):
        if sec["chapter"] not in first_section_idx:
            first_section_idx[sec["chapter"]] = si

    raw_chunks: list[ParsedChunk] = []
    global_order = 0
    total_body_chars = 0

    for i, sec in enumerate(sections):
        body_start = sec["end"]
        body_end = sections[i + 1]["start"] if i + 1 < len(sections) else len(mmd_text)

        # First section of chapter → extend backward to include chapter intro
        if first_section_idx.get(sec["chapter"]) == i:
            ch_intro = chapter_intros.get(sec["chapter"])
            if ch_intro is not None and ch_intro < sec["start"]:
                body_start = ch_intro

        # Last section before a chapter change → trim at next chapter heading
        if i + 1 < len(sections):
            next_ch = sections[i + 1]["chapter"]
            if next_ch != sec["chapter"] and next_ch in chapter_intros:
                body_end = min(body_end, chapter_intros[next_ch])

        body = mmd_text[body_start:body_end]
        total_body_chars += len(body)

        # ── Collect candidates from all active boundary signal patterns ───────
        all_candidates: list[tuple[int, int, str]] = []
        for pat in subsection_signals:
            for hm in pat.finditer(body):
                heading_text = hm.group(1).strip()
                all_candidates.append((hm.start(), hm.end(), heading_text))

        # Sort by position (different patterns may interleave)
        all_candidates.sort(key=lambda t: t[0])

        # ── Noise filtering ───────────────────────────────────────────────────
        meaningful_subs: list[tuple[int, int, str]] = []
        for (sh_start, sh_end, heading_text) in all_candidates:
            if re.match(r"^\d+\.\d+\s", heading_text):
                continue  # section headings leaked into body — skip
            if _is_noise_heading(heading_text):
                continue
            if noise_patterns and _is_noise_heading_profile(heading_text, noise_patterns):
                continue
            meaningful_subs.append((sh_start, sh_end, heading_text))

        # ── Exercise zone tagging ─────────────────────────────────────────────
        in_exercises_zone = bool(_SECTION_IS_EXERCISE_PATTERN.search(sec["section_label"]))
        # Also check profile exercise markers against section label
        if exercise_markers:
            _norm_label = _normalize_heading(sec["section_label"])
            beh = _match_exercise_marker(_norm_label, exercise_markers)
            if beh in ("zone_section_end", "zone_chapter_end"):
                in_exercises_zone = True

        tagged_subs: list[tuple[int, int, str]] = []
        for (sh_start, sh_end, heading_text) in meaningful_subs:
            _norm = _normalize_heading(heading_text)

            if exercise_markers:
                ex_behavior = _match_exercise_marker(_norm, exercise_markers)
                if ex_behavior in ("zone_section_end", "zone_chapter_end"):
                    in_exercises_zone = True
                    continue  # organizational divider — no chunk
                elif ex_behavior == "inline_single":
                    tagged_subs.append((sh_start, sh_end, heading_text + " (Exercises)"))
                    continue
            # Fallback: hardcoded exercise zone pattern
            if _EXERCISE_ZONE_PATTERN.match(_norm):
                in_exercises_zone = True
                continue  # organizational divider — no chunk

            if in_exercises_zone:
                tagged_subs.append((sh_start, sh_end, heading_text + " (Exercises)"))
            else:
                tagged_subs.append((sh_start, sh_end, heading_text))

        meaningful_subs = tagged_subs

        if not meaningful_subs:
            # No meaningful sub-headings → whole body is one chunk
            text = body.strip()
            if text:
                _ctype, _opt = _classify_chunk(sec["section_label"], in_exercises_zone, sec["section_label"])
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

        # ── Orphan intro text before first boundary ───────────────────────────
        first_sub_start = meaningful_subs[0][0]
        orphan_text = body[:first_sub_start].strip()

        for j, (sh_start, sh_end, heading_text) in enumerate(meaningful_subs):
            content_end = meaningful_subs[j + 1][0] if j + 1 < len(meaningful_subs) else len(body)
            chunk_text = body[sh_start:content_end].strip()

            # Prepend section intro to first subsection chunk
            if j == 0 and orphan_text:
                chunk_text = orphan_text + "\n\n" + chunk_text
                logger.info(
                    "Prepending %d chars of section intro to first subsection '%s'",
                    len(orphan_text), heading_text[:40],
                )

            if not chunk_text:
                continue

            # Apply OCR correction to subsection heading
            _exercises_suffix = ""
            if heading_text.endswith(" (Exercises)"):
                _exercises_suffix = " (Exercises)"
                _bare_heading = heading_text[: -len(" (Exercises)")]
            else:
                _bare_heading = heading_text
            _corrected_bare = corrections.get(_bare_heading, _bare_heading)
            heading_text = _corrected_bare + _exercises_suffix

            _in_zone = heading_text.endswith(" (Exercises)")
            _ctype, _opt = _classify_chunk(heading_text, _in_zone, sec["section_label"])
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
    return raw_chunks, total_body_chars


# ── Post-processing ───────────────────────────────────────────────────────────

def _postprocess_chunks(
    raw_chunks: list[ParsedChunk],
    config: dict,
    total_body_chars: int,
    book_slug: str,
) -> list[ParsedChunk]:
    """
    1. Chunk-level dedup: group by (concept_id, heading), keep max words.
    2. Merge tiny chunks (<50 words): forward merge, backward fallback.
    3. Split large chunks at paragraph boundaries if max_chunk_words set.
    4. Re-sort by order_index, re-number.
    5. Coverage check: warn if <95%.
    """
    max_chunk_words = config["max_chunk_words"]

    # ── Step 1: 3-copy deduplication ─────────────────────────────────────────
    seen: dict[tuple[str, str], ParsedChunk] = {}
    for chunk in raw_chunks:
        key = (chunk.concept_id, chunk.heading)
        existing = seen.get(key)
        if existing is None or _word_count(chunk.text) > _word_count(existing.text):
            seen[key] = chunk

    deduped = list(seen.values())

    # ── Step 2: Merge tiny chunks ─────────────────────────────────────────────
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
            _merged.append(_chunk)
    deduped = _merged

    # ── Step 3: Re-sort by original reading order ─────────────────────────────
    deduped.sort(key=lambda c: c.order_index)

    # ── Step 4: Split large chunks (profile-driven) ───────────────────────────
    if max_chunk_words:
        split_result: list[ParsedChunk] = []
        for chunk in deduped:
            split_result.extend(_split_large_chunk(chunk, max_chunk_words, book_slug))
        deduped = split_result

    # ── Step 5: Re-number in reading order ───────────────────────────────────
    for new_idx, chunk in enumerate(deduped):
        chunk.order_index = new_idx

    logger.info(
        "Chunks after dedup: %d (removed %d duplicates)",
        len(deduped), len(raw_chunks) - len(deduped),
    )

    # ── Step 6: Coverage check ────────────────────────────────────────────────
    if total_body_chars > 0:
        coverage = _check_coverage(total_body_chars, deduped)
        logger.info("Coverage check: %.1f%% of body chars assigned to chunks", coverage * 100)
        if coverage < 0.95:
            logger.warning(
                "Coverage below 95%% for book %s (%.1f%%) — some body text may be unassigned",
                book_slug, coverage * 100,
            )

    # ── Step 7: TOC section coverage check (profile only) ────────────────────
    toc_sections = config.get("toc_sections")
    if toc_sections:
        chunked_concepts = {c.concept_id for c in deduped}
        expected_concepts = {f"{book_slug}_{s['section_number']}" for s in toc_sections}
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

    return deduped


# ── Public API ────────────────────────────────────────────────────────────────

def parse_book_mmd(
    mmd_path: Path,
    book_slug: str,
    profile=None,
    corrected_headings: dict | None = None,
) -> list[ParsedChunk]:
    """
    Parse book.mmd into subsection-level chunks with 3-copy deduplication.

    Single universal parse path — profile=None uses hardcoded OpenStax math
    defaults; a BookProfile enriches the config for non-math books. Both cases
    flow through the same pipeline:
      _build_parse_config → _find_sections → _find_chapter_intros
      → _build_section_chunks → _postprocess_chunks

    Args:
        mmd_path:            Path to the book's book.mmd file.
        book_slug:           Short identifier for the book (e.g. "prealgebra").
        profile:             Optional BookProfile for non-math books.
        corrected_headings:  Optional dict mapping garbled section title strings
                             to corrected titles from the TOC.

    Returns:
        List of ParsedChunk objects sorted by original reading order.
    """
    mmd_text = mmd_path.read_text(encoding="utf-8")
    mmd_text = _normalize_mmd_format(mmd_text)
    logger.info("Loaded %s (%d chars)", mmd_path, len(mmd_text))

    config = _build_parse_config(profile, corrected_headings)
    section_matches = _find_sections(mmd_text, book_slug, config)
    chapter_intros = _find_chapter_intros(mmd_text)
    raw_chunks, total_body_chars = _build_section_chunks(
        mmd_text, section_matches, chapter_intros, book_slug, config
    )
    chunks = _postprocess_chunks(raw_chunks, config, total_body_chars, book_slug)
    return chunks


# ── Large-chunk splitter ──────────────────────────────────────────────────────

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


# ── Fuzzy section recovery ────────────────────────────────────────────────────

_FUZZY_TITLE_THRESHOLD = 0.75

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
        body_start_offset:  Minimum character offset for a valid match.

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
                "section_title": expected_title,
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

    image_chunk = next((c for c in chunks if c.image_urls), None)
    if image_chunk:
        print("\nSample chunk with image:")
        print(f"  concept_id  : {image_chunk.concept_id}")
        print(f"  heading     : {image_chunk.heading}")
        print(f"  image_urls  : {image_chunk.image_urls[:2]}")
        print(f"  latex count : {len(image_chunk.latex)}")
    else:
        print("\nNo chunks with image URLs found.")

    unique_concepts = len({c.concept_id for c in chunks})
    print(f"\nUnique concept_ids: {unique_concepts}")
    print(f"Average chunks per concept: {len(chunks) / unique_concepts:.1f}")

    ch1_chunks = [c for c in chunks if c.concept_id.startswith("prealgebra_1.")]
    print(f"\nChapter 1 chunks ({len(ch1_chunks)} total):")
    for c in ch1_chunks[:15]:
        print(f"  [{c.order_index:03d}] {c.concept_id:20s}  '{c.heading[:55]}'  ({_word_count(c.text)}w, {len(c.image_urls)} imgs)")
