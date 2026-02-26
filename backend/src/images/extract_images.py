"""
Image Extractor — extracts FORMULA and DIAGRAM images from PDFs,
saves them to disk, and builds a concept-to-image index.

Usage:
    python -m images.extract_images --book prealgebra
"""

import json
import re
import sys
import os
import argparse
from pathlib import Path
from collections import defaultdict

import fitz  # PyMuPDF

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import OUTPUT_DIR, DATA_DIR, BOOK_REGISTRY, BOOK_CODE_MAP


def extract_and_save_images(book_slug: str = "prealgebra") -> dict:
    """
    Extract FORMULA + DIAGRAM images from a book's PDF and save to disk.

    Returns the image index: {concept_id: [{filename, width, height, image_type, page, xref}]}
    """
    book_output_dir = OUTPUT_DIR / book_slug
    images_dir = book_output_dir / "images"

    # Load mathpix_plan.json for image classifications
    plan_path = book_output_dir / "mathpix_plan.json"
    if not plan_path.exists():
        print(f"ERROR: {plan_path} not found. Run the pipeline first.")
        return {}

    with open(plan_path, "r", encoding="utf-8") as f:
        image_decisions = json.load(f)

    # Filter to FORMULA + DIAGRAM only
    target_images = [
        d for d in image_decisions
        if d["image_type"] in ("FORMULA", "DIAGRAM")
    ]
    print(f"Found {len(target_images)} FORMULA + DIAGRAM images to extract")

    # Load concept_blocks.json to build page -> concept_id mapping
    blocks_path = book_output_dir / "concept_blocks.json"
    if not blocks_path.exists():
        print(f"ERROR: {blocks_path} not found.")
        return {}

    with open(blocks_path, "r", encoding="utf-8") as f:
        concept_blocks = json.load(f)

    page_to_concept = _build_page_to_concept_map(concept_blocks)

    # Find the PDF
    book_code = BOOK_CODE_MAP.get(book_slug)
    if not book_code or book_code not in BOOK_REGISTRY:
        print(f"ERROR: Unknown book_slug: {book_slug}")
        return {}

    pdf_filename = BOOK_REGISTRY[book_code]["pdf_filename"]
    pdf_path = DATA_DIR / pdf_filename
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        return {}

    # Open PDF
    doc = fitz.open(str(pdf_path))

    # Extract images
    image_index = defaultdict(list)
    extracted = 0
    skipped = 0

    for decision in target_images:
        ref = decision["image_reference"]
        page_num = decision["page"]
        image_type = decision["image_type"]

        # Parse xref from image_reference (e.g., "xref_15593_p6")
        xref = _parse_xref(ref)
        if xref is None:
            skipped += 1
            continue

        # Extract binary image data from PDF
        try:
            img_info = doc.extract_image(xref)
            if not img_info or not img_info.get("image"):
                skipped += 1
                continue
        except Exception:
            skipped += 1
            continue

        image_bytes = img_info["image"]
        ext = img_info.get("ext", "png")
        width = img_info.get("width", 0)
        height = img_info.get("height", 0)

        # Skip very tiny images that slipped through
        if width < 10 or height < 10:
            skipped += 1
            continue

        # Map page to concept
        concept_id = page_to_concept.get(page_num, "UNMAPPED")

        # Create output directory
        concept_dir = images_dir / concept_id
        concept_dir.mkdir(parents=True, exist_ok=True)

        # Save image file
        filename = f"{xref}.{ext}"
        output_path = concept_dir / filename
        output_path.write_bytes(image_bytes)

        # Add to index
        image_index[concept_id].append({
            "filename": filename,
            "xref": xref,
            "width": width,
            "height": height,
            "image_type": image_type,
            "page": page_num,
        })

        extracted += 1
        if extracted % 100 == 0:
            print(f"  Extracted {extracted} images...")

    doc.close()

    # Save image index
    index_path = book_output_dir / "image_index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(dict(image_index), f, indent=2, ensure_ascii=False)

    print(f"\nDone: {extracted} images extracted, {skipped} skipped")
    print(f"  Images saved to: {images_dir}")
    print(f"  Index saved to: {index_path}")
    print(f"  Concepts with images: {len(image_index)}")

    return dict(image_index)


def _build_page_to_concept_map(concept_blocks: list[dict]) -> dict[int, str]:
    """
    Build a mapping from page number -> concept_id.
    Uses source_pages from each concept block.
    """
    page_map = {}
    for block in concept_blocks:
        concept_id = block.get("concept_id", "")
        for page_num in block.get("source_pages", []):
            page_map[page_num] = concept_id
    return page_map


def _parse_xref(image_reference: str) -> int | None:
    """Parse xref number from image_reference like 'xref_15593_p6'."""
    match = re.match(r"xref_(\d+)_p\d+", image_reference)
    if match:
        return int(match.group(1))
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract images from PDF")
    parser.add_argument("--book", default="prealgebra", help="Book slug")
    args = parser.parse_args()

    extract_and_save_images(args.book)
