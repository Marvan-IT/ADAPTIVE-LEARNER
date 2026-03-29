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
    # Headings that are just a single word with no spaces (usually CAPS markers)
    re.compile(r"^[A-Z]{2,}$"),
    # Numbered items that are headings by mistake (e.g. "207. Seventy-five more than...")
    re.compile(r"^\d+\.\s"),
    # Config-driven exclusions — stays in sync with config.py automatically
    *[re.compile(rf"^{re.escape(m)}\b", re.IGNORECASE) for m in CONTENT_EXCLUDE_MARKERS],
]

def _is_noise_heading(heading_text: str) -> bool:
    """Return True if this heading is a noise marker, not a pedagogical subsection."""
    return any(p.match(heading_text) for p in _NOISE_HEADING_PATTERNS)


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
    """Return all CDN image URLs found in text, in order of appearance."""
    return IMAGE_URL_PATTERN.findall(text)


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
      3. Orphan text before the first meaningful ## heading becomes an extra chunk
         with the section title as heading.
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

    # ── Step 2: Split each section's body into subsection chunks ─────────────
    raw_chunks: list[ParsedChunk] = []
    global_order = 0  # monotone counter; reset after dedup

    for i, sec in enumerate(section_matches):
        # Body spans from end of section heading to start of next section heading
        body_start = sec["end"]
        body_end = section_matches[i + 1]["start"] if i + 1 < len(section_matches) else len(mmd_text)
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

        # Tag headings inside the exercises zone with "(Exercises)" suffix so:
        # (a) dedup keys are unique (prevents teaching/exercise heading collision)
        # (b) chunk_type classification works correctly in the API layer
        in_exercises_zone = False
        tagged_subs: list[tuple[int, int, str]] = []
        for (sh_start, sh_end, heading_text) in meaningful_subs:
            if re.match(r"^SECTION\s+\d+\.\d+", heading_text, re.IGNORECASE):
                in_exercises_zone = True
                tagged_subs.append((sh_start, sh_end, heading_text))  # keep as-is
            elif in_exercises_zone:
                tagged_subs.append((sh_start, sh_end, heading_text + " (Exercises)"))
            else:
                tagged_subs.append((sh_start, sh_end, heading_text))
        meaningful_subs = tagged_subs

        if not meaningful_subs:
            # Case 3: no meaningful sub-headings → whole body is one chunk
            text = body.strip()
            if text:
                raw_chunks.append(ParsedChunk(
                    book_slug=book_slug,
                    concept_id=sec["concept_id"],
                    section=sec["section_label"],
                    order_index=global_order,
                    heading=sec["section_label"],
                    text=text,
                    latex=_extract_latex(text),
                    image_urls=_extract_image_urls(text),
                ))
                global_order += 1
            continue

        # Case 2: orphan text before the first meaningful sub-heading
        first_sub_start = meaningful_subs[0][0]
        orphan_text = body[:first_sub_start].strip()
        if orphan_text:
            raw_chunks.append(ParsedChunk(
                book_slug=book_slug,
                concept_id=sec["concept_id"],
                section=sec["section_label"],
                order_index=global_order,
                heading=sec["section_label"],
                text=orphan_text,
                latex=_extract_latex(orphan_text),
                image_urls=_extract_image_urls(orphan_text),
            ))
            global_order += 1

        # Case 1: each meaningful sub-heading → one chunk
        # The chunk text spans from the ## heading line through all body content until
        # the next meaningful ## heading (or end of section). Noise headings inside
        # are naturally included in the text because we skip them as boundaries.
        for j, (sh_start, sh_end, heading_text) in enumerate(meaningful_subs):
            content_end = meaningful_subs[j + 1][0] if j + 1 < len(meaningful_subs) else len(body)
            chunk_text = body[sh_start:content_end].strip()
            if not chunk_text:
                continue
            raw_chunks.append(ParsedChunk(
                book_slug=book_slug,
                concept_id=sec["concept_id"],
                section=sec["section_label"],
                order_index=global_order,
                heading=heading_text,
                text=chunk_text,
                latex=_extract_latex(chunk_text),
                image_urls=_extract_image_urls(chunk_text),
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
        print(f"\nSample chunk with image:")
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
