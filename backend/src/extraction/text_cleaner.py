"""
Text Cleaner — removes headers, footers, page numbers, and boilerplate
from raw PDF text. Does NOT modify actual teaching content.
"""

import re

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import BOILERPLATE_PATTERNS


def clean_page_text(raw_text: str) -> str:
    """
    Clean a single page's raw text by removing:
      1. Boilerplate lines (openstax.org references, etc.)
      2. Standalone page numbers
      3. Common footer/header patterns
      4. Chapter-level footer patterns (e.g., "1 • Whole Numbers")
      5. Section-level footer patterns (e.g., "1.1 • Introduction to Whole Numbers")
      6. Excessive whitespace
    """
    lines = raw_text.split("\n")
    cleaned_lines = []

    for line in lines:
        stripped = line.strip()

        # Skip empty lines (will normalize later)
        if not stripped:
            continue

        # Skip standalone page numbers (just digits)
        if re.match(r"^\d{1,4}$", stripped):
            continue

        # Skip boilerplate patterns
        if _is_boilerplate(stripped):
            continue

        # Skip chapter footer: "1 • Whole Numbers" or "1 . Whole Numbers"
        if re.match(r"^\d+\s*[\u2022\.\u00b7•]\s+[A-Z][\w\s]+$", stripped):
            continue

        # Skip section footer: "1.1 • Introduction to Whole Numbers"
        if re.match(r"^\d+\.\d+\s*[\u2022\.\u00b7•]\s+[A-Z][\w\s]+$", stripped):
            continue

        # Skip footer-style lines: "22  1 . Whole Numbers"
        if re.match(r"^\d+\s+\d+\s*[\.\u2022]\s+.+$", stripped):
            continue

        # Skip footer-style lines: "1.1 . Introduction to Whole Numbers  23"
        if re.match(r"^\d+\.\d+\s*[\.\u2022]\s+.+\s+\d+$", stripped):
            continue

        # Skip standalone "..." ellipsis artifacts
        if stripped == "..." or stripped == "\u2026":
            continue

        cleaned_lines.append(stripped)

    # Rejoin and normalize whitespace
    text = "\n".join(cleaned_lines)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_boilerplate(line: str) -> bool:
    """Check if a line matches any boilerplate pattern."""
    for pattern in BOILERPLATE_PATTERNS:
        if re.search(pattern, line, re.IGNORECASE):
            return True
    return False


def clean_section_text(pages_text: list[str]) -> str:
    """
    Join multiple pages of cleaned text into a single section text.
    Handles page-break artifacts (words split across pages).
    """
    if not pages_text:
        return ""

    parts = []
    for text in pages_text:
        cleaned = clean_page_text(text)
        if cleaned:
            parts.append(cleaned)

    return "\n\n".join(parts)
