"""
MMD Parser — splits a Mathpix Markdown (MMD) document into per-section blocks.

Mathpix /v3/pdf returns one large Markdown document for the entire book.
Section headings are detected in TWO formats depending on the book:
  - Markdown: "## 1.1 Introduction to Whole Numbers"  (e.g. Prealgebra)
  - LaTeX:    "\\subsection*{1.1 Introduction to Whole Numbers}"  (e.g. Elementary Algebra)

The book config's section_pattern (e.g. r"^(\\d+)\\.(\\d+)\\s+(.+)") is applied
to the heading TEXT extracted from whichever format is present.

Key behaviour:
- Content for each section spans from the section heading to the START of the
  NEXT section heading (not just the next sub-heading). Sub-headings like
  "## Identify Rational Numbers" are part of the section body and included.
- R4 (TOC/review dedup): section_number is used as dict key; the occurrence
  with the MOST words wins. OpenStax Mathpix md has three occurrences of each
  section heading: (1) TOC entry with ~0 words, (2) full body with 500-2000
  words, (3) chapter review stub with 100-400 words. Max-words wins = body.
- section_in_chapter > 20 is filtered — those are figure/equation numbers
  (e.g. "## 1.52", "## 7.87") that Mathpix emits as headings, not real sections.
- Exercise content is truncated using exercise_marker_pattern.
- Image filenames are extracted from ![]() references for later annotation.
"""

import re
from dataclasses import dataclass, field


@dataclass
class MmdSection:
    chapter_number: int
    section_in_chapter: int
    section_number: str        # e.g. "1.1"
    section_title: str
    content_mmd: str           # Full MMD content with inline ![]() image refs
    image_filenames: list[str] = field(default_factory=list)


@dataclass
class _HeadingSpan:
    """Unified heading from either Markdown (## Title) or LaTeX (\\subsection*{Title})."""
    pos_start: int
    pos_end: int
    text: str

    def start(self) -> int:
        return self.pos_start

    def end(self) -> int:
        return self.pos_end


def _find_all_headings(mmd_text: str) -> list[_HeadingSpan]:
    """Find all headings from both Markdown and LaTeX formats, sorted by position.

    Handles:
      - Markdown: ## Title, ### Title  (used by Prealgebra and similar books)
      - LaTeX: \\subsection*{Title}, \\subsection{Title}  (used by Elementary Algebra+)
    """
    spans: list[_HeadingSpan] = []
    # Markdown headings: # through ####
    for m in re.finditer(r'^#{1,4}\s+(.+)$', mmd_text, re.MULTILINE):
        spans.append(_HeadingSpan(m.start(), m.end(), m.group(1).strip()))
    # LaTeX subsection headings: \subsection*{Title} or \subsection{Title}
    for m in re.finditer(r'^\\subsection\*?\{(.+?)\}', mmd_text, re.MULTILINE):
        spans.append(_HeadingSpan(m.start(), m.end(), m.group(1).strip()))
    return sorted(spans, key=lambda s: s.pos_start)


def parse_mmd(
    mmd_text: str,
    section_pattern: str,
    exercise_marker_pattern: str,
) -> list[MmdSection]:
    """
    Parse a Mathpix MMD document into a list of instructional MmdSection objects.

    Args:
        mmd_text: Full text of the Mathpix-generated MMD file.
        section_pattern: Regex matching section headings, e.g. r"^(\\d+)\\.(\\d+)\\s+(.+)"
                         Groups: (chapter_number, section_in_chapter, title)
        exercise_marker_pattern: Regex to detect the start of exercise content,
                                 e.g. r"Section\\s+\\d+\\.\\d+\\s+Exercises"

    Returns:
        List of MmdSection objects sorted by (chapter_number, section_in_chapter).
        Each section contains only the instructional content (exercises stripped).
    """
    _SECTION_RE = re.compile(section_pattern)
    _EXERCISE_RE = re.compile(exercise_marker_pattern, re.IGNORECASE)
    # Additional OpenStax exercise section markers not covered by book-config pattern
    _EXTRA_EXERCISE_RE = re.compile(
        r'(?:^|\n)(?:Practice Makes Perfect|In the following exercises|Everyday Math|Writing Exercises|Self Check)\b',
        re.IGNORECASE | re.MULTILINE,
    )
    _IMG_RE = re.compile(r'!\[.*?\]\(([^)]+)\)')

    # Find all headings — Markdown (## Title) and LaTeX (\subsection*{Title})
    all_headings = _find_all_headings(mmd_text)

    # Build a separate list of SECTION headings only (matching section_pattern,
    # section_in_chapter <= 20). These define the content boundaries.
    section_headings = []
    for m in all_headings:
        heading_text = m.text
        sm = _SECTION_RE.match(heading_text)
        if not sm:
            continue
        chapter_num = int(sm.group(1))
        section_in_chapter = int(sm.group(2))
        if section_in_chapter > 20:
            continue  # figure/equation numbers (1.52, 7.87, 10.134) — not real sections
        section_headings.append((m, chapter_num, section_in_chapter, sm.group(3).strip()))

    # R4: use dict keyed by section_number; max-words occurrence wins
    seen: dict[str, MmdSection] = {}

    for i, (m, chapter_num, section_in_chapter, section_title) in enumerate(section_headings):
        section_number = f"{chapter_num}.{section_in_chapter}"

        # Content spans from end of this section heading to the start of the
        # NEXT section heading (not just the next sub-heading).
        content_start = m.end()
        if i + 1 < len(section_headings):
            content_end = section_headings[i + 1][0].start()
        else:
            content_end = len(mmd_text)
        content = mmd_text[content_start:content_end].strip()

        # Strip exercise content — keep only instructional material
        ex_match = _EXERCISE_RE.search(content)
        if ex_match:
            content = content[:ex_match.start()].strip()
        # Also strip at additional OpenStax exercise markers (Everyday Math, etc.)
        extra_match = _EXTRA_EXERCISE_RE.search(content)
        if extra_match:
            content = content[:extra_match.start()].strip()

        # Skip empty sections (TOC entries have no real content)
        if not content:
            continue

        # Extract referenced image filenames for later vision annotation
        image_filenames = _IMG_RE.findall(content)

        # R4: keep the occurrence with the most words (body, not TOC or review stub)
        existing = seen.get(section_number)
        if existing is None or len(content.split()) > len(existing.content_mmd.split()):
            seen[section_number] = MmdSection(
                chapter_number=chapter_num,
                section_in_chapter=section_in_chapter,
                section_number=section_number,
                section_title=section_title,
                content_mmd=content,
                image_filenames=image_filenames,
            )

    # Return sections in reading order
    return sorted(seen.values(), key=lambda s: (s.chapter_number, s.section_in_chapter))
