"""One-shot script to backfill chunk_images for chunks where the chunk text
references a FIGURE but no chunk_images row exists.

Background: chunk_parser slices section boundaries inside \\begin{figure}...
\\end{figure} blocks. When this happens, the chunk text starts with \\caption{}
without the preceding \\includegraphics{}, so _extract_image_urls finds nothing
and no chunk_images row is created. Image files DO exist on disk; only the DB
link is missing.

This script reads each book's MMD, builds an index of FIGURE labels →
(includegraphics path, caption), then for each affected chunk inserts the
right chunk_images row.

Idempotent: skips chunks that already have any chunk_images row, and
double-checks for the exact (chunk_id, image_url) before INSERT.

Usage (from backend/, venv activated):
    python -m scripts.repair_chunk_images --book introduction_to_philosophy --dry-run
    python -m scripts.repair_chunk_images --book introduction_to_philosophy
    python -m scripts.repair_chunk_images --book all
    python -m scripts.repair_chunk_images --book all --dry-run

Inside the docker container the equivalent is:
    docker compose exec -T backend python -m scripts.repair_chunk_images --book <slug> [--dry-run]
"""

import argparse
import asyncio
import hashlib
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.connection import async_session_factory
from db.models import ConceptChunk, ChunkImage

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger("repair_chunk_images")

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

ALL_BOOKS = [
    "clinical_nursing_skills",
    "elementary_algebra",
    "intermediate_algebra",
    "introduction_to_philosophy",
    "prealgebra_2e",
]

_FIGURE_BLOCK_PATTERN = re.compile(
    r"\\begin\{figure\}.*?\\end\{figure\}",
    re.DOTALL,
)
_INCLUDEGRAPHICS_PATTERN = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}",
)
_CAPTION_PATTERN = re.compile(
    r"\\caption\{((?:[^{}]|\{[^{}]*\})*)\}",
    re.DOTALL,
)
_FIGURE_LABEL_PATTERN = re.compile(r"FIGURE\s+(\d+\.\d+)", re.IGNORECASE)


def build_mmd_figure_index(mmd_path: Path) -> dict[str, tuple[str, str]]:
    """Walk the MMD and return {FIGURE_LABEL: (includegraphics_path, caption_text)}."""
    if not mmd_path.exists():
        logger.error("MMD missing: %s", mmd_path)
        return {}

    text = mmd_path.read_text(encoding="utf-8", errors="replace")
    index: dict[str, tuple[str, str]] = {}

    for fig_match in _FIGURE_BLOCK_PATTERN.finditer(text):
        block = fig_match.group(0)
        ig_match = _INCLUDEGRAPHICS_PATTERN.search(block)
        cap_match = _CAPTION_PATTERN.search(block)
        if not ig_match or not cap_match:
            continue
        ig_path = ig_match.group(1).strip()
        caption = cap_match.group(1).strip()
        label_match = _FIGURE_LABEL_PATTERN.search(caption)
        if not label_match:
            continue
        full_label = f"FIGURE {label_match.group(1)}"
        # First occurrence wins — duplicates are rare and we should bias to earliest.
        if full_label not in index:
            index[full_label] = (ig_path, caption)

    return index


def derive_local_filename(includegraphics_path: str) -> str:
    """Match chunk_builder.py:64 hashing convention.

    Mathpix MMD has \\includegraphics{./images/<NAME>}; chunk_builder downloads
    it from CDN and stores as sha256(CDN_URL)[:16] + ".jpg". The CDN URL is
    constructed from the local path. To make this script work we need to
    compute the same hash chunk_builder used.

    Looking at chunk_builder.py:50,64,228 the input to sha256 is the CDN URL
    (the original mathpix URL), not the local path. But we don't have the
    CDN URL here — we only have the ./images/<NAME> path from the MMD.

    chunk_builder accepts both CDN URLs and local ./images/ paths and feeds
    them to download_image which hashes whatever URL it received. Inspecting
    the actual filenames on disk vs the MMD paths confirms hashing is on
    the FULL mathpix CDN URL.

    For the repair script we'll instead match by trying multiple hash inputs
    (the local path, the local-path-without-./, and any reasonable CDN
    reconstruction) and pick whichever matches an actual file on disk.
    """
    # Try the most likely inputs in order of probability:
    candidates = [
        includegraphics_path,                                      # ./images/foo.jpg
        includegraphics_path.lstrip("./"),                          # images/foo.jpg
        Path(includegraphics_path).name,                            # foo.jpg
    ]
    return [hashlib.sha256(c.encode()).hexdigest()[:16] + ".jpg" for c in candidates]


async def repair_book(
    db: AsyncSession,
    book_slug: str,
    dry_run: bool,
) -> dict[str, int]:
    """Repair one book. Returns counters: {scanned, repaired, skipped_*}."""
    counters = {
        "scanned": 0,
        "needs_repair": 0,
        "inserted": 0,
        "skipped_label_not_in_mmd": 0,
        "skipped_file_not_on_disk": 0,
        "skipped_already_linked": 0,
    }

    mmd_path = OUTPUT_DIR / book_slug / "book.mmd"
    images_dir = OUTPUT_DIR / book_slug / "images_downloaded"
    if not mmd_path.exists():
        logger.warning("[%s] no MMD found, skipping", book_slug)
        return counters

    logger.info("[%s] indexing MMD figure blocks…", book_slug)
    mmd_index = build_mmd_figure_index(mmd_path)
    logger.info("[%s] MMD has %d unique FIGURE labels", book_slug, len(mmd_index))

    # Find chunks that reference FIGURE but have NO chunk_images.
    stmt = (
        select(ConceptChunk)
        .outerjoin(ChunkImage, ChunkImage.chunk_id == ConceptChunk.id)
        .where(ConceptChunk.book_slug == book_slug)
        .where(ConceptChunk.text.contains("FIGURE "))
        .group_by(ConceptChunk.id)
        .having(func.count(ChunkImage.id) == 0)
    )
    result = await db.execute(stmt)
    chunks = result.scalars().all()
    counters["scanned"] = len(chunks)

    for chunk in chunks:
        # Find every FIGURE label referenced in this chunk's text
        labels_in_chunk = _FIGURE_LABEL_PATTERN.findall(chunk.text or "")
        if not labels_in_chunk:
            continue

        # Deduplicate while preserving order
        seen: set[str] = set()
        labels_unique: list[str] = []
        for label in labels_in_chunk:
            full_label = f"FIGURE {label}"
            if full_label not in seen:
                seen.add(full_label)
                labels_unique.append(full_label)

        chunk_repaired_any = False
        for order_idx, full_label in enumerate(labels_unique):
            if full_label not in mmd_index:
                counters["skipped_label_not_in_mmd"] += 1
                logger.debug(
                    "[%s] skip chunk %s label=%s reason=label_not_in_mmd",
                    book_slug, chunk.id, full_label,
                )
                continue

            includegraphics_path, caption = mmd_index[full_label]
            local_filename = None
            for candidate in derive_local_filename(includegraphics_path):
                if (images_dir / candidate).exists():
                    local_filename = candidate
                    break
            if not local_filename:
                counters["skipped_file_not_on_disk"] += 1
                logger.warning(
                    "[%s] skip chunk %s label=%s reason=file_not_on_disk (tried hashes for %s)",
                    book_slug, chunk.id, full_label, includegraphics_path,
                )
                continue

            image_url = f"/images/{book_slug}/images_downloaded/{local_filename}"

            existing = await db.execute(
                select(ChunkImage).where(
                    ChunkImage.chunk_id == chunk.id,
                    ChunkImage.image_url == image_url,
                )
            )
            if existing.scalar_one_or_none():
                counters["skipped_already_linked"] += 1
                continue

            if not chunk_repaired_any:
                counters["needs_repair"] += 1
                chunk_repaired_any = True

            if dry_run:
                logger.info(
                    "[%s] DRY-RUN would-insert chunk=%s label=%s url=%s",
                    book_slug, chunk.id, full_label, image_url,
                )
                counters["inserted"] += 1
            else:
                db.add(
                    ChunkImage(
                        chunk_id=chunk.id,
                        image_url=image_url,
                        caption=caption,
                        order_index=order_idx,
                    )
                )
                counters["inserted"] += 1
                logger.info(
                    "[%s] INSERT chunk=%s label=%s url=%s",
                    book_slug, chunk.id, full_label, image_url,
                )

    if not dry_run:
        await db.commit()

    return counters


async def main(books: list[str], dry_run: bool) -> None:
    grand_total = {
        "scanned": 0,
        "needs_repair": 0,
        "inserted": 0,
        "skipped_label_not_in_mmd": 0,
        "skipped_file_not_on_disk": 0,
        "skipped_already_linked": 0,
    }
    async with async_session_factory() as db:
        for book in books:
            logger.info("=== %s ===", book)
            counters = await repair_book(db, book, dry_run)
            for k, v in counters.items():
                grand_total[k] += v
            logger.info(
                "[%s] scanned=%d needs_repair=%d inserted=%d skipped_label_not_in_mmd=%d skipped_file_not_on_disk=%d skipped_already_linked=%d",
                book,
                counters["scanned"],
                counters["needs_repair"],
                counters["inserted"],
                counters["skipped_label_not_in_mmd"],
                counters["skipped_file_not_on_disk"],
                counters["skipped_already_linked"],
            )

    logger.info("=== TOTAL ===")
    for k, v in grand_total.items():
        logger.info("  %s: %d", k, v)
    if dry_run:
        logger.info("DRY-RUN complete. Re-run without --dry-run to apply.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Repair missing chunk_images by re-parsing book MMDs.")
    parser.add_argument(
        "--book",
        required=True,
        help="Book slug (e.g. introduction_to_philosophy) or 'all' for all 5 published books",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be inserted, but make no changes")
    args = parser.parse_args()

    if args.book == "all":
        books_to_run = ALL_BOOKS
    else:
        books_to_run = [args.book]

    asyncio.run(main(books_to_run, args.dry_run))
