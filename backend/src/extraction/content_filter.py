"""
Content Filter — extracts ONLY instructional content from cleaned section text.

Removes:
  - Content before the section header on the first page
  - Learning Objectives block (extracted separately)
  - BE PREPARED readiness quizzes
  - MEDIA / ACCESS ADDITIONAL ONLINE RESOURCES blocks
  - SECTION X.Y EXERCISES and everything after
  - Self Check blocks
  - Exercise blocks (Practice Makes Perfect, Everyday Math, Writing Exercises)
"""

import re
from typing import Optional

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from extraction.domain_models import SectionBoundary
from config import EXERCISE_SECTION_MARKERS, CONTENT_EXCLUDE_MARKERS


def filter_section_content(
    full_text: str,
    section: SectionBoundary,
) -> dict:
    """
    From the full combined text of a section's pages, extract only
    the instructional content.

    Returns:
      {
        "instructional_text": str,
        "learning_objectives": list[str],
        "latex_expressions": list[str],
      }
    """
    # Step 1: Remove content before the section header
    text = _trim_before_header(full_text, section)

    # Step 1b: Remove chapter outline / introduction blurb if this is the first section
    text = _remove_chapter_intro(text, section)

    # Step 2: Extract and remove learning objectives
    learning_objectives, text = _extract_learning_objectives(text)

    # Step 3: Remove BE PREPARED blocks
    text = _remove_be_prepared(text)

    # Step 4: Remove everything from exercise markers onward
    text = _trim_at_exercises(text, section)

    # Step 5: Remove MEDIA / ACCESS ADDITIONAL ONLINE RESOURCES
    text = _remove_media_blocks(text)

    # Step 6: Remove Self Check blocks
    text = _remove_self_check(text)

    # Step 7: Extract LaTeX-like expressions
    latex_expressions = _extract_latex_expressions(text)

    # Step 8: Final cleanup
    text = _final_cleanup(text)

    return {
        "instructional_text": text,
        "learning_objectives": learning_objectives,
        "latex_expressions": latex_expressions,
    }


def _trim_before_header(text: str, section: SectionBoundary) -> str:
    """
    Remove everything before the section header on the first page.
    The section header looks like "1.1 Introduction to Whole Numbers".
    Also handles chapter outline text that appears before first section of a chapter.
    """
    title_prefix = section.section_title[:20] if len(section.section_title) >= 20 else section.section_title

    # Try to find the section header line (e.g., "1.1 Introduction to Whole Numbers")
    # The header may appear TWICE: once in the chapter outline, once as the actual section start.
    # We need to find the LAST occurrence that's the actual section heading.
    pattern = re.compile(
        re.escape(section.section_number) + r"\s+" + re.escape(title_prefix),
        re.IGNORECASE,
    )

    # Find all matches and use the last one (which is the actual section start, not the outline)
    matches = list(pattern.finditer(text))
    if matches:
        # Use the last match (skips chapter outline references)
        last_match = matches[-1]
        return text[last_match.start():]

    # Fallback: find just the section number at start of a line
    pattern2 = re.compile(
        r"(?:^|\n)" + re.escape(section.section_number) + r"\s+[A-Z]",
        re.MULTILINE,
    )
    matches2 = list(pattern2.finditer(text))
    if matches2:
        last_match = matches2[-1]
        return text[last_match.start():].lstrip("\n")

    return text


def _remove_chapter_intro(text: str, section: SectionBoundary) -> str:
    """
    Remove chapter introduction/outline text that sometimes appears
    before the first section of a chapter.
    Patterns: 'Chapter Outline', 'Introduction\n...', list of section numbers.
    """
    # Remove "Chapter Outline" block and associated section listing
    text = re.sub(
        r"Chapter\s+Outline\s*\n.*?(?=\d+\.\d+\s+[A-Z])",
        "",
        text,
        count=1,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Remove "Introduction\n..." paragraph that precedes the actual section header
    # This only appears before the first section of a chapter
    if section.section_in_chapter == 1:
        intro_pattern = re.compile(
            r"^Introduction\s*\n.*?(?=" + re.escape(section.section_number) + r"\s+" + re.escape(section.section_title[:10]) + r")",
            re.DOTALL | re.IGNORECASE | re.MULTILINE,
        )
        text = intro_pattern.sub("", text)

    return text


def _extract_learning_objectives(text: str) -> tuple[list[str], str]:
    """
    Extract the Learning Objectives block and return (objectives, remaining_text).
    Pattern: "Learning Objectives" header followed by bullet items, ending at
    the next block or double newline.
    """
    objectives = []

    # Find the learning objectives block
    lo_pattern = re.compile(
        r"Learning Objectives.*?(?:By the end of this section,.*?:)?\s*\n((?:.*?\n)*?)\n(?=[A-Z]|\n)",
        re.IGNORECASE | re.DOTALL,
    )
    match = lo_pattern.search(text)
    if match:
        obj_text = match.group(1)
        # Extract individual objectives (lines that look like bullet points)
        for line in obj_text.split("\n"):
            line = line.strip()
            # Remove bullet markers
            line = re.sub(r"^[\u2022\-\*]\s*", "", line)
            if line and len(line) > 10:
                objectives.append(line)
        # Remove the entire LO block from text
        text = text[:match.start()] + "\n" + text[match.end():]

    # Also try a simpler pattern
    if not objectives:
        simple_pattern = re.compile(
            r"By the end of this section,\s*you will be able to:\s*\n((?:.*\n)*?)(?=\n[A-Z]|\nBE PREPARED)",
            re.IGNORECASE,
        )
        match = simple_pattern.search(text)
        if match:
            obj_text = match.group(1)
            for line in obj_text.split("\n"):
                line = line.strip()
                line = re.sub(r"^[\u2022\-\*]\s*", "", line)
                if line and len(line) > 10:
                    objectives.append(line)
            text = text[:match.start()] + "\n" + text[match.end():]

    return objectives, text


def _remove_be_prepared(text: str) -> str:
    """
    Remove BE PREPARED readiness quiz blocks.
    These appear after Learning Objectives and before instructional content.
    Also removes "If you missed this problem, review Example X.Y" lines.
    """
    # Remove "If you missed this problem" lines (leftover from BE PREPARED)
    text = re.sub(
        r"If you missed this problem,\s*review.*?\.\s*\n?",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Remove "Before you get started, take this readiness quiz" lines
    text = re.sub(
        r"Before you get started,?\s*take this readiness quiz\.?\s*\n?",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Remove BE PREPARED blocks using a robust line-by-line approach
    lines = text.split("\n")
    filtered = []
    skip = False
    for line in lines:
        stripped = line.strip()
        if "BE PREPARED" in stripped.upper():
            skip = True
            continue
        if skip:
            # End of BE PREPARED block: next meaningful content heading
            if stripped and (
                re.match(r"^(EXAMPLE|HOW TO)\s", stripped) or
                re.match(r"^(Use |Find |Add |Subtract |Multiply |Divide |Simplify |Evaluate |Solve |Translate |Model |Identify |Round |Name |Locate |Convert |Determine |Apply )", stripped) or
                re.match(r"^(MANIPULATIVE|Counting|The |A |An |In |We |When |To |Our |Now |Let |Did )", stripped)
            ):
                skip = False
                filtered.append(line)
            # Stay in skip mode
            continue
        filtered.append(line)
    text = "\n".join(filtered)

    return text


def _trim_at_exercises(text: str, section: SectionBoundary) -> str:
    """
    Remove everything from the exercise markers onward.
    """
    # Pattern: "Section X.Y Exercises" (case-insensitive)
    exercise_pattern = re.compile(
        r"Section\s+" + re.escape(section.section_number) + r"\s+Exercises",
        re.IGNORECASE,
    )
    match = exercise_pattern.search(text)
    if match:
        text = text[:match.start()]

    # Also trim at generic exercise markers
    for marker in EXERCISE_SECTION_MARKERS:
        pattern = re.compile(re.escape(marker), re.IGNORECASE)
        match = pattern.search(text)
        if match:
            text = text[:match.start()]

    return text


def _remove_media_blocks(text: str) -> str:
    """Remove MEDIA and ACCESS ADDITIONAL ONLINE RESOURCES blocks."""
    # Remove MEDIA blocks
    text = re.sub(
        r"MEDIA\s*\n.*?(?=\n\n|\Z)",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Remove ACCESS ADDITIONAL blocks
    text = re.sub(
        r"ACCESS ADDITIONAL ONLINE RESOURCES\s*\n.*?(?=\n\n|\Z)",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return text


def _remove_self_check(text: str) -> str:
    """Remove Self Check blocks at the end of sections."""
    pattern = re.compile(r"Self Check\s*\n.*", re.DOTALL | re.IGNORECASE)
    match = pattern.search(text)
    if match:
        text = text[:match.start()]
    return text


def _extract_latex_expressions(text: str) -> list[str]:
    """
    Extract LaTeX math expressions from Mathpix-formatted text.

    Looks for:
      - Display math: $$...$$
      - Inline math: $...$
    Returns the expressions WITHOUT delimiters, deduplicated.
    """
    latex = []

    # Extract display math first: $$...$$
    for match in re.finditer(r"\$\$(.+?)\$\$", text, re.DOTALL):
        expr = match.group(1).strip()
        if expr and len(expr) > 1:
            latex.append(expr)

    # Extract inline math: $...$ (but not $$)
    # Use negative lookbehind/lookahead to avoid matching $$ delimiters
    for match in re.finditer(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", text):
        expr = match.group(1).strip()
        if expr and len(expr) > 1:
            latex.append(expr)

    return list(set(latex))  # deduplicate


def _final_cleanup(text: str) -> str:
    """Final whitespace and formatting cleanup."""
    # Remove figure/image reference placeholders
    text = re.sub(r"Figure\s+\d+\.\d+", "", text)

    # Remove orphan numbered items from BE PREPARED quizzes (e.g., "1.", "2.", "3.")
    text = re.sub(r"(?m)^\d+\.\s*$", "", text)

    # Remove "Write the number..." quiz prompts that leak from BE PREPARED
    text = re.sub(
        r"Write the number .+? using digits\??\s*\n?",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Remove MANIPULATIVE MATHEMATICS blocks (non-instructional activity references)
    text = re.sub(
        r"MANIPULATIVE MATHEMATICS\s*\n.*?(?=\n\n|\Z)",
        "",
        text,
        flags=re.DOTALL,
    )

    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove trailing/leading whitespace per line
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    # Remove leading/trailing whitespace
    text = text.strip()

    # Remove very short orphan lines (< 3 chars) that are just artifacts
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if len(stripped) < 3 and not re.match(r"\d", stripped):
            continue
        # Remove standalone single-digit numbered lines (quiz remnants like "2.")
        if re.match(r"^\d\.$", stripped):
            continue
        cleaned.append(line)
    text = "\n".join(cleaned)

    return text.strip()
