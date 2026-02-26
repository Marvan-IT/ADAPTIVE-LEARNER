"""
PDF Reader — extracts raw text, font metadata, and image references page-by-page.
Uses PyMuPDF (fitz) for all PDF operations.
"""

import fitz  # PyMuPDF
from pathlib import Path

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models import PageText, FontSpan


def extract_all_pages(pdf_path: Path) -> list[PageText]:
    """
    Open a PDF and extract text + font metadata + image refs from every page.
    Returns a list of PageText objects, one per page.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    pages = []
    doc = fitz.open(str(pdf_path))

    for page_index in range(len(doc)):
        page = doc[page_index]

        # Raw text extraction
        raw_text = page.get_text("text") or ""

        # Font span extraction from dict blocks
        font_spans = _extract_font_spans(page)

        # Image xref extraction
        image_xrefs = _extract_image_xrefs(page)

        pages.append(PageText(
            page_index=page_index,
            page_number=page_index + 1,
            raw_text=raw_text,
            font_spans=font_spans,
            image_xrefs=image_xrefs,
        ))

    doc.close()
    return pages


def _extract_font_spans(page: fitz.Page) -> list[FontSpan]:
    """
    Extract all text spans with font name, size, content, and bounding box.
    Uses page.get_text('dict') which returns structured block/line/span data.
    """
    spans = []
    try:
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    except Exception:
        return spans

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:  # type 0 = text block
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                font = span.get("font", "")
                size = span.get("size", 0.0)
                text = span.get("text", "").strip()
                bbox = span.get("bbox", (0, 0, 0, 0))
                if text:
                    spans.append(FontSpan(
                        font=font,
                        size=round(size, 1),
                        text=text,
                        bbox=tuple(bbox),
                    ))
    return spans


def _extract_image_xrefs(page: fitz.Page) -> list[int]:
    """
    Return list of image xref IDs found on this page.
    """
    xrefs = []
    try:
        images = page.get_images(full=True)
        for img in images:
            xrefs.append(img[0])  # xref is the first element
    except Exception:
        pass
    return xrefs


def render_page_to_image(doc: fitz.Document, page_index: int, dpi: int = 200) -> bytes:
    """
    Render a PDF page as a JPEG image and return the bytes.
    Uses JPEG compression to keep size reasonable for Mathpix API.
    """
    page = doc[page_index]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    image_bytes = pix.tobytes("jpeg", jpg_quality=85)
    pix = None
    return image_bytes


def get_page_count(pdf_path: Path) -> int:
    """Return the total number of pages in a PDF."""
    doc = fitz.open(str(pdf_path))
    count = len(doc)
    doc.close()
    return count
