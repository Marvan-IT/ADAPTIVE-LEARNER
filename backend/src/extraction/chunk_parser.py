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
from pathlib import Path

from config import CONTENT_EXCLUDE_MARKERS

logger = logging.getLogger(__name__)

# ── Compiled patterns ─────────────────────────────────────────────────────────

# Matches any markdown heading that carries an X.Y section number.
# Works on # through #### — whichever level Mathpix happens to use.
SECTION_PATTERN = re.compile(r"^(#{1,4})\s+(\d+)\.(\d+)\s+(.+)", re.MULTILINE)

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
_MAX_REAL_SECTION_IN_CHAPTER = 10
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


def _clean_chunk_text(text: str) -> str:
    """Strip LaTeX figure/table markup from chunk text.

    Images are already extracted to chunk_images via _extract_image_urls().
    The raw LaTeX (\\begin{figure}, \\includegraphics, etc.) is noise — strip it
    so chunks contain clean, readable content for LLM card generation and display.
    """
    # Remove \begin{figure}...\end{figure} blocks (images already extracted)
    text = re.sub(r"\\begin\{figure\}.*?\\end\{figure\}", "", text, flags=re.DOTALL)
    # Remove standalone \includegraphics (outside figure env)
    text = re.sub(r"\\includegraphics(?:\[[^\]]*\])?\{[^}]+\}", "", text)
    # Remove \captionsetup{...}
    text = re.sub(r"\\captionsetup\{[^}]*\}", "", text)
    # \caption{text} → keep the caption text, strip the command
    text = re.sub(r"\\caption\{([^}]*)\}", r"\1", text)
    # Remove table/tabular wrappers but keep content
    text = re.sub(r"\\begin\{table\}", "", text)
    text = re.sub(r"\\end\{table\}", "", text)
    text = re.sub(r"\\begin\{tabular\}\{[^}]*\}", "", text)
    text = re.sub(r"\\end\{tabular\}", "", text)
    # Remove \hline
    text = re.sub(r"\\hline\b", "", text)
    # Remove external URLs (no learning value for card generation)
    text = re.sub(r"https?://\S+", "", text)
    # Remove credit/attribution lines
    text = re.sub(r"\(credit:.*?\)", "", text, flags=re.IGNORECASE)
    # Remove standalone "Figure X.Y" reference lines
    text = re.sub(r"^Figure\s+\d+\.\d+\s*$", "", text, flags=re.MULTILINE)
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _word_count(text: str) -> int:
    return len(text.split())


# ── Public API ────────────────────────────────────────────────────────────────

def parse_book_mmd(mmd_path: Path, book_slug: str) -> list[ParsedChunk]:
    """
    Parse book.mmd into subsection-level chunks with 3-copy deduplication.

    Algorithm:
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
        mmd_path:  Path to the book's book.mmd file.
        book_slug: Short identifier for the book (e.g. "prealgebra").

    Returns:
        List of ParsedChunk objects sorted by original reading order.
        After dedup the count should be ~300-600 for prealgebra (not 900-1500).
    """
    mmd_text = mmd_path.read_text(encoding="utf-8")
    # Normalize LaTeX heading syntax (\subsection*{} / \section*{}) to markdown (### / ##)
    # This is a no-op for prealgebra (already markdown); required for all other books.
    mmd_text = _normalize_mmd_format(mmd_text)
    logger.info("Loaded %s (%d chars)", mmd_path, len(mmd_text))

    # ── Step 1: Find all X.Y section headings ────────────────────────────────
    section_matches: list[dict] = []
    for m in SECTION_PATTERN.finditer(mmd_text):
        chapter_num = int(m.group(2))
        section_in_chapter = int(m.group(3))
        if section_in_chapter > _MAX_REAL_SECTION_IN_CHAPTER:
            # Mathpix emits figure/equation numbers as headings — skip
            continue
        section_title_raw = m.group(4).strip()
        section_number = f"{chapter_num}.{section_in_chapter}"
        section_label = f"{section_number} {section_title_raw}"
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

    # ── Remove backward section numbers (lab/experiment internal numbering) ──
    # Mathpix sometimes emits \subsection*{1.1 Lab Title} inside a lab section
    # like 1.5, reusing the 1.1 numbering for internal steps. After normalization
    # this looks like a real section 1.1 heading, stealing the lab content.
    # Fix: once we've seen section X.Y in chapter X, reject any later occurrence
    # of X.Z where Z < Y (it's internal numbering, not a real section).
    _forward_matches: list[dict] = []
    _chapter_max_sec: dict[int, int] = {}
    for sec in section_matches:
        ch = sec["chapter"]
        s = sec["section_in_chapter"]
        prev_max = _chapter_max_sec.get(ch, 0)
        if s < prev_max:
            logger.debug(
                "Removing backward section %d.%d (max seen was %d.%d) — likely lab internal numbering",
                ch, s, ch, prev_max,
            )
            continue
        _chapter_max_sec[ch] = max(prev_max, s)
        _forward_matches.append(sec)
    section_matches = _forward_matches
    logger.info("Section candidates after backward-number filter: %d", len(section_matches))

    # ── Filter fake sections (exercise numbers with tiny bodies) ─────────────
    filtered_matches: list[dict] = []
    for i, sec in enumerate(section_matches):
        body_start = sec["end"]
        body_end = section_matches[i + 1]["start"] if i + 1 < len(section_matches) else len(mmd_text)
        body_words = _word_count(mmd_text[body_start:body_end])
        if body_words >= MIN_SECTION_BODY_WORDS:
            filtered_matches.append(sec)
        else:
            logger.debug(
                "Skipping short fake section %s.%s (%d words) — likely exercise number",
                sec["chapter"], sec["section_in_chapter"], body_words,
            )
    section_matches = filtered_matches
    logger.info("Section candidates after exercise-number filter: %d", len(section_matches))

    # ── Step 1c: Detect chapter intro boundaries ─────────────────────────────
    # Chapters have intro content (title, images, objectives) BEFORE section X.1.
    # Detect chapter headings (## N | Title — no decimal) to adjust body boundaries.
    _CHAPTER_HEADING = re.compile(r"^#{1,4}\s+(\d+)\s*[|:]\s+", re.MULTILINE)
    _chapter_intro_pos: dict[int, int] = {}  # chapter_num → start position of chapter heading
    for _cm in _CHAPTER_HEADING.finditer(mmd_text):
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
            if not chunk_text:
                continue
            # Determine if this heading is in the exercise zone
            # (exercise headings were tagged with " (Exercises)" in the loop above)
            _in_zone = heading_text.endswith(" (Exercises)")
            _ctype, _opt = _classify_chunk(heading_text, _in_zone, sec["section_label"])
            # Extract images and latex BEFORE cleaning so no refs are lost
            _images = _extract_image_urls(chunk_text)
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
        if (len(_chunk.text.split()) < 50
                and _mi + 1 < len(deduped)
                and deduped[_mi + 1].concept_id == _chunk.concept_id):
            deduped[_mi + 1].text = _chunk.text + "\n\n" + deduped[_mi + 1].text
            logger.debug("Merged tiny chunk '%s' into next chunk", _chunk.heading[:40])
        else:
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
    return deduped


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
