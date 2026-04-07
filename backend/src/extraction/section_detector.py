"""
Section Detector — identifies instructional section boundaries in a PDF.

Strategy:
  1. Find section headers by matching font name + size + regex pattern
  2. Find exercise markers (e.g., "Section 1.1 Exercises") in plain text
  3. Pair each header with its exercise marker to get exact page ranges
  4. Filter out TOC/front-matter/back-matter false positives
"""

import re
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from extraction.domain_models import PageText, SectionBoundary


def detect_sections(pages: list[PageText], book_config: dict) -> list[SectionBoundary]:
    """
    Main entry point. Returns ordered list of SectionBoundary objects.

    Algorithm:
      1. Skip pages before front_matter_end_page
      2. Find all font-matched section headers
      3. Find all exercise markers
      4. Find back matter start
      5. For each header, pair with its exercise marker or next header
      6. Return ordered list
    """
    front_matter_end = book_config.get("front_matter_end_page", 0)
    back_matter_start = _find_back_matter_start(pages)

    # Step 1: Find section headers via font matching
    raw_headers = _find_section_headers(pages, book_config, front_matter_end, back_matter_start)

    # Step 2: Find exercise boundary markers
    exercise_pages = _find_exercise_boundaries(pages, book_config)

    # Step 3: Pair headers with boundaries
    sections = _pair_headers_with_boundaries(raw_headers, exercise_pages, pages, back_matter_start)

    return sections


def _find_section_headers(
    pages: list[PageText],
    book_config: dict,
    front_matter_end: int,
    back_matter_start: int,
) -> list[dict]:
    """
    Scan font spans for section headers matching the configured font/size/pattern.
    Returns list of dicts: {chapter, section_in_chapter, section_number, title, page_index}
    """
    target_font = book_config["section_header_font"]
    size_min = book_config["section_header_size_min"]
    size_max = book_config["section_header_size_max"]
    pattern = re.compile(book_config["section_pattern"])

    headers = []
    seen_sections = set()  # avoid duplicates from TOC

    for page in pages:
        if page.page_index < front_matter_end:
            continue
        if back_matter_start and page.page_index >= back_matter_start:
            continue

        for span in page.font_spans:
            if span.font != target_font:
                continue
            if not (size_min <= span.size <= size_max):
                continue

            match = pattern.match(span.text.strip())
            if not match:
                continue

            chapter = int(match.group(1))
            section_in_chapter = int(match.group(2))
            title = match.group(3).strip()
            section_number = f"{chapter}.{section_in_chapter}"

            # Skip duplicates (same section found on multiple pages = TOC reference)
            key = section_number
            if key in seen_sections:
                continue
            seen_sections.add(key)

            headers.append({
                "chapter": chapter,
                "section_in_chapter": section_in_chapter,
                "section_number": section_number,
                "title": title,
                "page_index": page.page_index,
            })

    # Sort by page index to ensure ordering
    headers.sort(key=lambda h: h["page_index"])
    return headers


def _find_exercise_boundaries(pages: list[PageText], book_config: dict) -> dict:
    """
    Scan raw text for exercise markers like 'Section 1.1 Exercises'.
    Returns dict mapping section_number -> page_index.
    """
    book_config.get("exercise_marker_pattern", r"Section\s+\d+\.\d+\s+Exercises")
    # Build a more specific regex that captures the section number
    exercise_re = re.compile(r"Section\s+(\d+\.\d+)\s+Exercises", re.IGNORECASE)

    result = {}
    for page in pages:
        for match in exercise_re.finditer(page.raw_text):
            section_num = match.group(1)
            if section_num not in result:
                result[section_num] = page.page_index

    return result


def _find_back_matter_start(pages: list[PageText]) -> Optional[int]:
    """
    Find the page where back matter begins by looking for known markers.
    Searches from the end of the book backwards for efficiency.
    """
    from config import BACK_MATTER_MARKERS

    # Search last 20% of pages
    start_search = max(0, len(pages) - len(pages) // 5)

    for page in pages[start_search:]:
        text_upper = page.raw_text.upper()
        for marker in BACK_MATTER_MARKERS:
            if marker.upper() in text_upper:
                return page.page_index

    return None


def _pair_headers_with_boundaries(
    headers: list[dict],
    exercise_pages: dict,
    pages: list[PageText],
    back_matter_start: Optional[int],
) -> list[SectionBoundary]:
    """
    For each section header, determine its end page.

    Priority:
      1. Use the exercise marker page for this section
      2. Use the page before the next section header
      3. Use the back matter start page
      4. Use the last content page
    """
    sections = []

    for i, header in enumerate(headers):
        section_num = header["section_number"]
        start_idx = header["page_index"]

        # Determine end page
        if section_num in exercise_pages:
            # Include the exercise page since instructional content (examples)
            # may continue on the same page before the exercise marker.
            # The content filter / LLM will strip exercise content.
            end_idx = exercise_pages[section_num] + 1
        elif i + 1 < len(headers):
            # End at the page before next section header
            end_idx = headers[i + 1]["page_index"]
        elif back_matter_start:
            end_idx = back_matter_start
        else:
            end_idx = len(pages) - 1

        # Find the character offset of the header text on the start page
        header_offset = _find_header_offset(
            pages[start_idx].raw_text,
            section_num,
            header["title"]
        )

        sections.append(SectionBoundary(
            chapter_number=header["chapter"],
            section_in_chapter=header["section_in_chapter"],
            section_number=section_num,
            section_title=header["title"],
            start_page_index=start_idx,
            end_page_index=end_idx,
            header_char_offset=header_offset,
        ))

    return sections


def _find_header_offset(page_text: str, section_number: str, title: str) -> int:
    """
    Find the character offset of the section header in the page's raw text.
    This is used to skip content from the previous section that appears
    before the header on the same page.
    """
    # Try to find the exact section number + title
    pattern = re.compile(
        re.escape(section_number) + r"\s+" + re.escape(title[:20]),
        re.IGNORECASE
    )
    match = pattern.search(page_text)
    if match:
        return match.start()

    # Fallback: just find the section number
    simple_pattern = re.compile(
        r"(?:^|\n)" + re.escape(section_number) + r"\s",
        re.MULTILINE
    )
    match = simple_pattern.search(page_text)
    if match:
        return match.start()

    return 0
