"""
Auto-detect PDF typography config for a new book using PyMuPDF.
Returns a complete BOOK_REGISTRY-compatible entry dict.
"""
from __future__ import annotations
import logging
import re
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

_SECTION_RE = re.compile(r"^\d+\.\d+\s+\S")
_SUFFIX_RE = re.compile(
    r"[-_]OP_[A-Za-z0-9]+"
    r"|[-_]WEB"
    r"|[-_]2[eE]"
    r"|[-_]v\d+"
    r"|[-_]\d{4}",
    re.IGNORECASE,
)
_CAMEL_RE = re.compile(r"([a-z])([A-Z])")

_MATH_DEFAULTS = {
    "section_header_font": "RobotoSlab-Bold",
    "section_header_size_min": 14.0,
    "section_header_size_max": 14.6,
    "chapter_header_font": "RobotoSlab-Bold",
    "chapter_header_size_min": 17.0,
    "chapter_header_size_max": 17.5,
    "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
    "front_matter_end_page": 16,
    "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
}


def derive_slug(filename: str) -> str:
    """Convert a messy PDF filename to a clean snake_case slug.

    Examples:
        FinancialAccounting-OP_YioY6nY.pdf  ->  financial_accounting
        Clinical-Nursing-Skills-WEB.pdf     ->  clinical_nursing_skills
        prealgebra.pdf                      ->  prealgebra
    """
    stem = Path(filename).stem
    stem = _SUFFIX_RE.sub("", stem)
    stem = _CAMEL_RE.sub(r"\1_\2", stem)
    stem = re.sub(r"[-\s]+", "_", stem)
    stem = re.sub(r"_+", "_", stem).strip("_").lower()
    return stem


def derive_code(slug: str) -> str:
    """Derive a short book code (<=10 chars, uppercase) from a slug.

    Examples:
        financial_accounting  ->  FINACC
        prealgebra            ->  PREALG
        clinical_nursing_skills -> CNS
    """
    words = [w for w in slug.split("_") if w]
    initials = "".join(w[0] for w in words).upper()
    if len(initials) < 4:
        # Pad with more chars from the first word
        pad = slug.replace("_", "").upper()
        initials = pad[:max(6, len(initials))]
    return initials[:10]


def calibrate_book(pdf_path: Path, slug: str, subject: str) -> dict:
    """Scan a PDF with PyMuPDF and return a complete BOOK_REGISTRY entry.

    Falls back to math-book defaults for any field that cannot be auto-detected.
    """
    code = derive_code(slug)
    entry: dict = {
        "book_code": code,
        "book_slug": slug,
        "pdf_filename": f"{subject}/{pdf_path.name}",
        "title": slug.replace("_", " ").title(),
        "subject": subject,
        "section_pattern": _MATH_DEFAULTS["section_pattern"],
        "toc_section_pattern": None,
    }

    try:
        doc = fitz.open(str(pdf_path))
        total = len(doc)
        scan_start = min(10, total)
        scan_end = min(60, total)

        font_stats: dict[tuple[str, float], list[str]] = {}
        first_section_page: int | None = None

        for page_num in range(scan_start, scan_end):
            page = doc[page_num]
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if len(text) < 3:
                            continue
                        font = span.get("font", "")
                        size = round(float(span.get("size", 0)), 1)
                        key = (font, size)
                        font_stats.setdefault(key, [])
                        if len(font_stats[key]) < 5:
                            font_stats[key].append(text[:80])
                        if first_section_page is None and _SECTION_RE.match(text):
                            first_section_page = page_num

        # Section header: bold, 12–16 pt, text matches X.Y pattern
        section_hits = [
            (font, size, samples)
            for (font, size), samples in font_stats.items()
            if 12.0 <= size <= 16.0
            and ("Bold" in font or "bold" in font)
            and any(_SECTION_RE.match(s) for s in samples)
        ]
        if section_hits:
            font, size, _ = max(section_hits, key=lambda x: len(x[2]))
            entry.update(
                section_header_font=font,
                section_header_size_min=round(size - 0.3, 1),
                section_header_size_max=round(size + 0.3, 1),
            )
        else:
            logger.warning(
                "calibrate_book: no section header detected for '%s' — using defaults", slug
            )
            entry.update(
                section_header_font=_MATH_DEFAULTS["section_header_font"],
                section_header_size_min=_MATH_DEFAULTS["section_header_size_min"],
                section_header_size_max=_MATH_DEFAULTS["section_header_size_max"],
            )

        # Chapter header: bold, 16–20 pt
        chapter_hits = [
            (font, size)
            for (font, size) in font_stats
            if 16.0 <= size <= 20.0 and ("Bold" in font or "bold" in font)
        ]
        if chapter_hits:
            font, size = max(chapter_hits, key=lambda x: x[1])
            entry.update(
                chapter_header_font=font,
                chapter_header_size_min=round(size - 0.3, 1),
                chapter_header_size_max=round(size + 0.3, 1),
            )
        else:
            logger.warning(
                "calibrate_book: no chapter header detected for '%s' — using defaults", slug
            )
            entry.update(
                chapter_header_font=_MATH_DEFAULTS["chapter_header_font"],
                chapter_header_size_min=_MATH_DEFAULTS["chapter_header_size_min"],
                chapter_header_size_max=_MATH_DEFAULTS["chapter_header_size_max"],
            )

        entry["front_matter_end_page"] = (
            first_section_page if first_section_page is not None
            else _MATH_DEFAULTS["front_matter_end_page"]
        )
        entry["exercise_marker_pattern"] = (
            _detect_exercise_pattern(doc) or _MATH_DEFAULTS["exercise_marker_pattern"]
        )
        doc.close()

    except Exception:
        logger.exception(
            "calibrate_book: unexpected error for '%s' — falling back to defaults", slug
        )
        for k, v in _MATH_DEFAULTS.items():
            entry.setdefault(k, v)

    # Ensure every required key is present
    for k, v in _MATH_DEFAULTS.items():
        entry.setdefault(k, v)

    logger.info(
        "calibrate_book [%s]: section_font=%s %.1f-%.1f | chapter_font=%s %.1f-%.1f | front_matter_end=%d",
        slug,
        entry.get("section_header_font"),
        entry.get("section_header_size_min") or 0.0,
        entry.get("section_header_size_max") or 0.0,
        entry.get("chapter_header_font"),
        entry.get("chapter_header_size_min") or 0.0,
        entry.get("chapter_header_size_max") or 0.0,
        entry.get("front_matter_end_page", 0),
    )
    return entry


def _detect_exercise_pattern(doc: fitz.Document) -> str | None:
    markers = ["Exercises", "Problems", "Problem Set", "Practice Problems"]
    for page in doc:
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    for marker in markers:
                        if marker in text and re.search(r"\d+\.\d+", text):
                            return rf"Section\s+\d+\.\d+\s+{re.escape(marker)}"
    return None


if __name__ == "__main__":
    import argparse
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    _ap = argparse.ArgumentParser(description="Preview font calibration for a PDF")
    _ap.add_argument("pdf", type=Path, help="Path to PDF file")
    _ap.add_argument("--slug", required=True, help="Book slug (e.g. financial_accounting)")
    _ap.add_argument("--subject", required=True, help="Subject folder name (e.g. business)")
    _args = _ap.parse_args()
    _result = calibrate_book(_args.pdf, _args.slug, _args.subject)
    print(json.dumps(_result, indent=2))
