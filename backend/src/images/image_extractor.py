"""
Image Extractor — extracts images from PDF pages and associates them with sections.
Uses PyMuPDF for extraction. Images are NOT stored in concept blocks or vector DB.
"""

import fitz
import logging
from pathlib import Path
from typing import Optional

import sys, os

logger = logging.getLogger(__name__)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models import PageText, SectionBoundary, ImageDecision


def extract_image_decisions(
    pdf_path: Path,
    pages: list[PageText],
    sections: list[SectionBoundary],
) -> list[ImageDecision]:
    """
    Extract all images from the PDF, classify them, and produce
    ImageDecision objects for the Mathpix plan.

    Images are NOT embedded into concept text.
    This only produces a plan for which images need Mathpix processing.
    """
    doc = fitz.open(str(pdf_path))
    decisions = []
    seen_xrefs = set()

    for page in pages:
        for xref in page.image_xrefs:
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            # Get image info
            try:
                img_info = doc.extract_image(xref)
                if not img_info:
                    continue
            except Exception as e:
                logger.warning("Failed to extract image xref %d: %s", xref, e)
                continue

            width = img_info.get("width", 0)
            height = img_info.get("height", 0)
            colorspace_name = img_info.get("cs-name", "")

            # Classify the image
            image_type, action, reason = _classify_image(
                width, height, colorspace_name, page.raw_text
            )

            # Find which section this image belongs to
            section_id = _find_section_for_page(page.page_index, sections)

            decisions.append(ImageDecision(
                image_reference=f"xref_{xref}_p{page.page_number}",
                page=page.page_number,
                image_type=image_type,
                action=action,
                reason=reason,
            ))

    doc.close()
    return decisions


def _classify_image(
    width: int,
    height: int,
    colorspace: str,
    page_text: str,
) -> tuple[str, str, str]:
    """
    Classify an image and decide whether to send it to Mathpix.

    Returns (image_type, action, reason)
    """
    # Very small images are likely icons or decorative
    if width < 50 or height < 50:
        return "DECORATIVE", "SKIP", "Image too small to contain meaningful content"

    # Very small inline images might be formula fragments
    if width < 200 and height < 80:
        return "FORMULA", "SEND_TO_MATHPIX", "Small inline image likely contains a math expression"

    # Wide and short -> likely number line or horizontal diagram
    aspect_ratio = width / max(height, 1)
    if aspect_ratio > 5:
        return "DIAGRAM", "SKIP", "Wide aspect ratio suggests number line or ruler diagram"

    # Large colorful images -> likely photos or decorative
    if width > 500 and height > 500 and colorspace in ("DeviceRGB", "DeviceCMYK"):
        return "DECORATIVE", "SKIP", "Large color image likely decorative or photographic"

    # Medium-sized images in math context -> could be formulas or diagrams
    if width < 400 and height < 300:
        return "FORMULA", "SEND_TO_MATHPIX", "Medium image in math context may contain expressions"

    # Default: diagrams (charts, figures, etc.)
    return "DIAGRAM", "SKIP", "Standard-sized image classified as diagram or figure"


def _find_section_for_page(
    page_index: int,
    sections: list[SectionBoundary],
) -> Optional[str]:
    """Find which section a page belongs to."""
    for section in sections:
        if section.start_page_index <= page_index < section.end_page_index:
            return section.section_number
    return None
