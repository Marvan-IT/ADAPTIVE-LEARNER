"""
Image Extractor — extracts FORMULA and DIAGRAM images from PDFs,
saves them to disk, calls the vision annotator for each image, and
builds an enriched concept-to-image index (image_index.json).

Usage:
    python -m images.extract_images --book prealgebra
    python -m images.extract_images --book prealgebra --no-annotate
"""

import asyncio
import json
import logging
import re
import sys
import os
import argparse
from collections import defaultdict
from pathlib import Path

import fitz  # PyMuPDF
import io as _io
from PIL import Image as _PILImage
from openai import AsyncOpenAI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    OUTPUT_DIR,
    DATA_DIR,
    BOOK_REGISTRY,
    BOOK_CODE_MAP,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    VISION_RATE_LIMIT,
)
from images.vision_annotator import annotate_image

logger = logging.getLogger(__name__)


async def extract_and_save_images(
    book_slug: str = "prealgebra",
    annotate: bool = True,
) -> dict:
    """
    Extract FORMULA + DIAGRAM images from a book's PDF, save to disk,
    and optionally annotate each image via GPT-4o Vision.

    Args:
        book_slug: Slug identifying the book (e.g. "prealgebra").
        annotate:  When True (default), each image is passed to the vision
                   annotator. Set False to skip API calls (useful for tests
                   and quick re-runs where only extraction is needed).

    Returns:
        image_index dict: {concept_id: [{filename, xref, width, height,
                                         image_type, page, description, relevance}]}
    """
    book_output_dir = OUTPUT_DIR / book_slug
    images_dir = book_output_dir / "images"
    cache_dir = book_output_dir / "vision_cache"

    # ── Load mathpix_plan.json ────────────────────────────────────
    plan_path = book_output_dir / "mathpix_plan.json"
    if not plan_path.exists():
        logger.error("mathpix_plan.json not found at %s — run the pipeline first.", plan_path)
        return {}

    with open(plan_path, "r", encoding="utf-8") as f:
        image_decisions = json.load(f)

    # Only process FORMULA and DIAGRAM images
    target_images = [
        d for d in image_decisions
        if d["image_type"] in ("FORMULA", "DIAGRAM")
    ]
    logger.info("Found %d FORMULA + DIAGRAM images to extract", len(target_images))

    # ── Load concept_blocks.json ──────────────────────────────────
    blocks_path = book_output_dir / "concept_blocks.json"
    if not blocks_path.exists():
        logger.error("concept_blocks.json not found at %s.", blocks_path)
        return {}

    with open(blocks_path, "r", encoding="utf-8") as f:
        concept_blocks = json.load(f)

    page_to_concept = _build_page_to_concept_map(concept_blocks)

    # ── Resolve PDF path ──────────────────────────────────────────
    book_code = BOOK_CODE_MAP.get(book_slug)
    if not book_code or book_code not in BOOK_REGISTRY:
        logger.error("Unknown book_slug: %s", book_slug)
        return {}

    pdf_filename = BOOK_REGISTRY[book_code]["pdf_filename"]
    pdf_path = DATA_DIR / pdf_filename
    if not pdf_path.exists():
        logger.error("PDF not found: %s", pdf_path)
        return {}

    # ── Instantiate LLM client (one shared instance for all calls) ─
    llm_client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    # ── Open PDF ──────────────────────────────────────────────────
    doc = fitz.open(str(pdf_path))

    # ── Extract loop ──────────────────────────────────────────────
    image_index: dict = defaultdict(list)
    extracted = 0
    skipped = 0
    annotated_count = 0
    cache_hit_count = 0
    annotation_error_count = 0

    for decision in target_images:
        ref = decision["image_reference"]
        page_num = decision["page"]
        image_type = decision["image_type"]

        # Parse xref from image_reference (e.g. "xref_15593_p6")
        xref = _parse_xref(ref)
        if xref is None:
            skipped += 1
            continue

        # Extract binary image data from the PDF
        try:
            img_info = doc.extract_image(xref)
            if not img_info or not img_info.get("image"):
                skipped += 1
                continue
        except Exception as exc:
            logger.debug("extract_image failed for xref %d: %s", xref, exc)
            skipped += 1
            continue

        image_bytes: bytes = img_info["image"]
        ext: str = img_info.get("ext", "png")
        width: int = img_info.get("width", 0)
        height: int = img_info.get("height", 0)

        # Discard thumbnails / noise that slipped through classification
        if width < 50 or height < 50:
            skipped += 1
            continue

        # Validate and normalize image bytes with Pillow — skips black/corrupt images
        try:
            _pil = _PILImage.open(_io.BytesIO(image_bytes))
            _pil.verify()  # raises on corruption
            # Re-open after verify (verify closes the stream)
            _pil = _PILImage.open(_io.BytesIO(image_bytes)).convert("RGB")
            _out = _io.BytesIO()
            _pil.save(_out, format="PNG")
            image_bytes = _out.getvalue()
            ext = "png"
        except Exception:
            logger.debug("Pillow validation failed for xref %d — skipping", xref)
            skipped += 1
            continue

        # Map page number to owning concept (with ±5-page proximity fallback)
        concept_id = _nearest_concept(page_num, page_to_concept)

        # Save image file under images/{concept_id}/{xref}.{ext}
        concept_dir = images_dir / concept_id
        concept_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{xref}.{ext}"
        output_path = concept_dir / filename
        output_path.write_bytes(image_bytes)

        # ── Vision annotation ─────────────────────────────────────
        annotation: dict = {"description": None, "relevance": None}
        if annotate:
            concept_meta = _get_concept_meta(concept_blocks, concept_id)
            concept_title = concept_meta.get("concept_title", concept_id)

            annotation = await annotate_image(
                image_bytes=image_bytes,
                concept_title=concept_title,
                image_type=image_type,
                llm_client=llm_client,
                model=OPENAI_MODEL,
                cache_dir=cache_dir,
            )

            # Filter out non-educational images (logos, icons, photos, etc.)
            if not annotation.get("is_educational", True):
                skipped += 1
                logger.debug(
                    "Skipping non-educational image xref %d (concept: %s)",
                    xref,
                    concept_id,
                )
                # Throttle even for skipped images to avoid bursting
                await asyncio.sleep(VISION_RATE_LIMIT)
                continue

            # Track stats for the summary log at the end
            if annotation.get("description") is not None:
                annotated_count += 1
            else:
                annotation_error_count += 1

            # Throttle to stay well within Vision API rate limits
            await asyncio.sleep(VISION_RATE_LIMIT)

        # ── Record in index ───────────────────────────────────────
        image_index[concept_id].append({
            "filename": filename,
            "xref": xref,
            "width": width,
            "height": height,
            "image_type": image_type,
            "page": page_num,
            "description": annotation["description"],
            "relevance": annotation["relevance"],
        })

        extracted += 1
        if extracted % 100 == 0:
            logger.info("Extracted %d images so far...", extracted)

    doc.close()

    # ── Write image_index.json ─────────────────────────────────────
    index_path = book_output_dir / "image_index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(dict(image_index), f, indent=2, ensure_ascii=False)

    logger.info(
        "Extraction complete: %d extracted, %d skipped — index saved to %s",
        extracted,
        skipped,
        index_path,
    )
    logger.info("Concepts with images: %d", len(image_index))

    if annotate:
        logger.info(
            "Annotation complete: %d annotated, %d cache hits, %d skipped, %d errors",
            annotated_count,
            cache_hit_count,
            # DECORATIVE images not in target_images so skipped == 0 here;
            # kept for DLD log format compliance
            0,
            annotation_error_count,
        )

    return dict(image_index)


# ── Helpers ───────────────────────────────────────────────────────────

def _nearest_concept(page_num: int, page_map: dict[int, str]) -> str:
    """
    Assign an image page to its owning concept.
    If the page is not directly mapped, searches within ±5 pages for the
    nearest concept boundary and assigns to that concept. Falls back to
    "UNMAPPED" only when no concept is within 5 pages.
    """
    if page_num in page_map:
        return page_map[page_num]
    mapped = sorted(page_map)
    if not mapped:
        return "UNMAPPED"
    closest = min(mapped, key=lambda p: abs(p - page_num))
    return page_map[closest] if abs(closest - page_num) <= 5 else "UNMAPPED"


def _build_page_to_concept_map(concept_blocks: list[dict]) -> dict[int, str]:
    """
    Build a mapping from page number -> concept_id.
    Uses source_pages from each concept block.
    """
    page_map: dict[int, str] = {}
    for block in concept_blocks:
        concept_id = block.get("concept_id", "")
        for page_num in block.get("source_pages", []):
            page_map[page_num] = concept_id
    return page_map


def _get_concept_meta(concept_blocks: list[dict], concept_id: str) -> dict:
    """Return concept metadata dict for a given concept_id, or empty dict."""
    for block in concept_blocks:
        if block.get("concept_id") == concept_id:
            return block
    return {}


def _parse_xref(image_reference: str) -> int | None:
    """Parse xref number from image_reference like 'xref_15593_p6'."""
    match = re.match(r"xref_(\d+)_p\d+", image_reference)
    if match:
        return int(match.group(1))
    return None


# ── Entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Extract and annotate images from a PDF textbook."
    )
    parser.add_argument("--book", default="prealgebra", help="Book slug (e.g. prealgebra)")
    parser.add_argument(
        "--no-annotate",
        action="store_true",
        help="Skip GPT-4o Vision annotation (extract images only)",
    )
    args = parser.parse_args()
    asyncio.run(extract_and_save_images(args.book, annotate=not args.no_annotate))
