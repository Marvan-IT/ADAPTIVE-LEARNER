"""
chunk_builder.py — Persist ParsedChunk objects to PostgreSQL.

Pipeline:
  1. Parse book.mmd → list[ParsedChunk]  (via chunk_parser.parse_book_mmd)
  2. For each chunk:
     a. Download CDN images to local disk (idempotent — skipped if file exists)
     b. Embed chunk text with text-embedding-3-small (1536 dims)
     c. Upsert ConceptChunk row + ChunkImage rows to PostgreSQL

All operations are idempotent: re-running against an existing DB will skip
chunks that already exist (matched on book_slug + concept_id + heading + order_index).
Images are also not re-downloaded if the local file already exists.

Usage (from backend/src/):
    python -m extraction.chunk_builder --book prealgebra

Or called programmatically from pipeline.py via --chunks flag.
"""

import hashlib
import logging
import re
import sys
import os
from pathlib import Path

import requests
from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure src/ is importable when run as __main__
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    IMAGE_BASE_URL,
    OUTPUT_DIR,
    EMBEDDING_MODEL,
)
from db.models import ConceptChunk, ChunkImage
from extraction.chunk_parser import ParsedChunk, parse_book_mmd

logger = logging.getLogger(__name__)

# ── Image download ────────────────────────────────────────────────────────────

def download_image(cdn_url: str, images_dir: Path) -> str | None:
    """
    Download a CDN image to local disk once; return the local filename.

    Uses a SHA-256 hash of the URL as the filename to ensure stable, collision-free
    mapping without depending on the CDN path structure (which contains coordinates).

    Args:
        cdn_url:    Full Mathpix CDN URL.
        images_dir: Directory to save images to; must exist before calling.

    Returns:
        Local filename (e.g. "a3f2b8c1d4e5f6a7.jpg") — NOT the full path.
    """
    url_hash = hashlib.sha256(cdn_url.encode()).hexdigest()[:16]
    local_filename = f"{url_hash}.jpg"
    local_path = images_dir / local_filename

    if local_path.exists():
        logger.debug("Image already cached: %s", local_filename)
        return local_filename

    # Handle local relative paths from book.mmd (e.g. ./images/{uuid}.jpg)
    # Actual image files live in mathpix_extracted/, not images/
    if cdn_url.startswith("./"):
        filename = Path(cdn_url).name
        source = images_dir.parent / "mathpix_extracted" / filename
        if source.exists():
            import shutil
            shutil.copy2(source, local_path)
            logger.debug("Copied local image: %s → %s", filename, local_filename)
        else:
            logger.warning("Local image not found in mathpix_extracted/: %s", filename)
            return None
        return local_filename

    logger.debug("Downloading image: %s → %s", cdn_url[:80], local_filename)
    try:
        r = requests.get(cdn_url, timeout=30)
        r.raise_for_status()
        local_path.write_bytes(r.content)
        logger.debug("Saved %d bytes → %s", len(r.content), local_filename)
    except Exception as exc:
        logger.warning("Failed to download image %s: %s", cdn_url[:80], exc)
        return None
    return local_filename


# ── Embedding ─────────────────────────────────────────────────────────────────

# Strip markdown image tags before embedding — the URL text adds noise, not signal.
_IMG_TAG_RE = re.compile(r"!\[\]\([^)]+\)")
# Strip $$ and $ markers but keep the math content so LaTeX context is preserved.
_LATEX_MARKER_RE = re.compile(r"\$\$?")


def _prepare_embed_text(heading: str, text: str) -> str:
    """Clean text for embedding: remove image tags, strip LaTeX markers, sanitize for JSON."""
    combined = f"{heading}\n\n{text}"
    combined = _IMG_TAG_RE.sub("", combined)
    combined = _LATEX_MARKER_RE.sub("", combined)
    # Remove control characters that break JSON serialization (keep \t, \n, \r)
    combined = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', combined)
    # Remove Unicode surrogates and replacement characters
    combined = combined.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
    combined = combined.replace('\ufffd', '')
    # Collapse excessive whitespace introduced by stripping
    combined = re.sub(r"\n{3,}", "\n\n", combined).strip()
    return combined[:8000]  # safety truncation (text-embedding-3-small limit ~8k tokens)


def embed_text(client: OpenAI, heading: str, text: str) -> list[float]:
    """
    Embed chunk content using text-embedding-3-small (1536 dimensions).

    The embedding input is: heading + "\n\n" + text, with image/LaTeX markers stripped.
    Falls back to embedding just the heading if the full text fails.
    """
    input_text = _prepare_embed_text(heading, text)
    try:
        response = client.embeddings.create(
            input=input_text,
            model=EMBEDDING_MODEL,
        )
        return response.data[0].embedding
    except Exception as e:
        logger.warning("Embedding failed for '%s' (len=%d): %s. Retrying with heading only.", heading[:60], len(input_text), e)
        # Fallback: embed just the heading (always safe, short text)
        fallback = re.sub(r'[\x00-\x1f\x7f\ufffd]', '', heading).strip()[:500]
        response = client.embeddings.create(
            input=fallback or "untitled",
            model=EMBEDDING_MODEL,
        )
        return response.data[0].embedding


# ── DB persistence ─────────────────────────────────────────────────────────────

async def save_chunk(
    db: AsyncSession,
    chunk: ParsedChunk,
    embedding: list[float],
    images_dir: Path,
    image_base_url: str,
    book_slug: str,
) -> ConceptChunk | None:
    """
    Upsert a single ConceptChunk and its ChunkImage children to the DB.

    Idempotent: returns None (without inserting) if a matching row already exists.
    Matched on (book_slug, concept_id, heading, order_index).

    Args:
        db:             Open async SQLAlchemy session.
        chunk:          Parsed subsection chunk.
        embedding:      1536-dim float vector from text-embedding-3-small.
        images_dir:     Local directory where CDN images are downloaded.
        image_base_url: Base URL for serving images (from config IMAGE_BASE_URL).
        book_slug:      e.g. "prealgebra".

    Returns:
        The newly inserted ConceptChunk ORM object, or None if it already existed.
    """
    # Idempotency check — keyed on (book_slug, concept_id, heading) only.
    # order_index and text are updated if they differ so re-runs stay consistent.
    result = await db.execute(
        select(ConceptChunk).where(
            ConceptChunk.book_slug == book_slug,
            ConceptChunk.concept_id == chunk.concept_id,
            ConceptChunk.heading == chunk.heading,
        )
    )
    rows = result.scalars().all()
    # If duplicates exist (from old order_index-keyed runs), delete extras and keep one
    if len(rows) > 1:
        for dup in rows[1:]:
            await db.delete(dup)
        await db.flush()
    existing = rows[0] if rows else None
    if existing is not None:
        # Update fields that may have changed on re-run
        if existing.order_index != chunk.order_index:
            existing.order_index = chunk.order_index
        if existing.text != chunk.text:
            existing.text = chunk.text
        if existing.latex != chunk.latex:
            existing.latex = chunk.latex
        if not existing.chunk_type_locked:
            existing.chunk_type = chunk.chunk_type
        existing.is_optional = chunk.is_optional
        logger.debug("Chunk already exists, updated: %s / %s", chunk.concept_id, chunk.heading)
        return None

    db_chunk = ConceptChunk(
        book_slug=chunk.book_slug,
        concept_id=chunk.concept_id,
        section=chunk.section,
        order_index=chunk.order_index,
        heading=chunk.heading,
        text=chunk.text,
        latex=chunk.latex,
        chunk_type=chunk.chunk_type,
        is_optional=chunk.is_optional,
        embedding=embedding,
    )
    db.add(db_chunk)
    # flush to get the auto-generated UUID before inserting child ChunkImage rows
    await db.flush()

    _img_order = 0
    for i, cdn_url in enumerate(chunk.image_urls):
        local_filename = download_image(cdn_url, images_dir)
        if local_filename is None:
            logger.warning("Skipping ChunkImage for failed download: %s", cdn_url[:80])
            continue
        if not (images_dir / local_filename).exists():
            logger.warning("Image file missing after download: %s", local_filename)
            continue
        image_url = f"/images/{book_slug}/images_downloaded/{local_filename}"
        _caption = chunk.image_captions[i] if i < len(chunk.image_captions) else None
        db_image = ChunkImage(
            chunk_id=db_chunk.id,
            image_url=image_url,
            caption=_caption,
            order_index=_img_order,
        )
        db.add(db_image)
        _img_order += 1

    return db_chunk


# ── Main entry point ──────────────────────────────────────────────────────────

async def build_chunks(
    book_slug: str,
    mmd_path: Path,
    db: AsyncSession,
    rebuild: bool = False,
    profile=None,
) -> None:
    """
    Full chunk pipeline: parse → download images → embed → save to DB.

    Commits every 10 chunks so progress is preserved if the run is interrupted.
    Safe to re-run: when rebuild=False, existing chunks are updated (idempotent).
    When rebuild=True, all existing chunks for the book are deleted first (clean rebuild).

    Args:
        book_slug: e.g. "prealgebra".
        mmd_path:  Path to the book.mmd file.
        db:        Open async SQLAlchemy session (caller manages lifetime).
        rebuild:   If True, delete all existing chunks for the book before re-inserting.
        profile:   Optional BookProfile from book_profiler. When None, uses legacy
                   hardcoded patterns (backward compat for 16 OpenStax math books).
    """
    if rebuild:
        from sqlalchemy import delete as _sa_delete
        await db.execute(_sa_delete(ConceptChunk).where(ConceptChunk.book_slug == book_slug))
        await db.commit()
        logger.info("[rebuild] Cleared all existing chunks for book_slug=%s", book_slug)

    chunks = parse_book_mmd(mmd_path, book_slug, profile=profile)
    logger.info("Parsed %d chunks from %s", len(chunks), mmd_path)

    images_dir = mmd_path.parent / "images_downloaded"
    images_dir.mkdir(exist_ok=True)
    logger.info("Images directory: %s", images_dir)

    openai_client = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL or None,
    )

    saved = 0
    skipped = 0

    for i, chunk in enumerate(chunks):
        embedding = embed_text(openai_client, chunk.heading, chunk.text)
        result = await save_chunk(
            db=db,
            chunk=chunk,
            embedding=embedding,
            images_dir=images_dir,
            image_base_url=IMAGE_BASE_URL,
            book_slug=book_slug,
        )
        if result is not None:
            saved += 1
        else:
            skipped += 1

        if (i + 1) % 10 == 0:
            await db.commit()
            logger.info(
                "Progress: %d/%d chunks processed (%d saved, %d skipped)",
                i + 1, len(chunks), saved, skipped,
            )

    await db.commit()
    logger.info(
        "Done. %d/%d chunks saved for %s (%d already existed)",
        saved, len(chunks), book_slug, skipped,
    )

    # Post-pipeline image validation — warn about orphan records
    orphan_count = await validate_and_clean_images(book_slug, db)
    if orphan_count > 0:
        logger.warning(
            "Image validation: removed %d orphan ChunkImage records (missing files on disk) for %s",
            orphan_count, book_slug,
        )
    else:
        logger.info("Image validation: all ChunkImage records have matching files on disk")


async def _download_image_with_retry(url: str, dest: Path, max_retries: int = 3) -> bool:
    """Download an image with exponential backoff retry. Returns True on success."""
    import asyncio as _asyncio
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(resp.content)
                return True
            logger.warning("Image HTTP %d for %s (attempt %d/%d)", resp.status_code, url, attempt + 1, max_retries)
        except Exception as exc:
            logger.warning("Image download error %s (attempt %d/%d): %s", url, attempt + 1, max_retries, exc)
        if attempt < max_retries - 1:
            await _asyncio.sleep(2 ** (attempt + 1))
    return False


async def validate_and_clean_images(book_slug: str, db: AsyncSession) -> int:
    """Remove chunk_images rows where the local image file does not exist.

    Returns the count of deleted rows.
    """
    from sqlalchemy import select, delete as _delete
    from db.models import ChunkImage, ConceptChunk

    result = await db.execute(
        select(ChunkImage.id, ChunkImage.image_url)
        .join(ConceptChunk, ChunkImage.chunk_id == ConceptChunk.id)
        .where(ConceptChunk.book_slug == book_slug)
    )
    rows = result.all()

    missing_ids = []
    for row_id, image_url in rows:
        filename = image_url.rstrip("/").split("/")[-1]
        local_path = OUTPUT_DIR / book_slug / "images_downloaded" / filename
        if not local_path.exists():
            missing_ids.append(row_id)

    if missing_ids:
        await db.execute(_delete(ChunkImage).where(ChunkImage.id.in_(missing_ids)))
        await db.commit()
        logger.info(
            "validate_and_clean_images: removed %d orphan rows for book '%s'",
            len(missing_ids), book_slug,
        )

    return len(missing_ids)


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import argparse

    from db.connection import async_session_factory

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    ap = argparse.ArgumentParser(description="Build ConceptChunk rows from book.mmd")
    ap.add_argument("--book", required=True, help="Book slug (e.g. prealgebra)")
    ap.add_argument("--parse-only", action="store_true", help="Parse only — no DB writes or embeddings")
    args = ap.parse_args()

    mmd_path = OUTPUT_DIR / args.book / "book.mmd"
    if not mmd_path.exists():
        print(f"ERROR: {mmd_path} not found. Run Mathpix whole-PDF pipeline first.")
        sys.exit(1)

    if args.parse_only:
        from extraction.chunk_parser import _word_count
        chunks = parse_book_mmd(mmd_path, args.book)
        print(f"Total chunks: {len(chunks)}")
        for c in chunks[:5]:
            print(f"  [{c.order_index:03d}] {c.concept_id:20s} '{c.heading[:50]}' ({_word_count(c.text)} words)")
        sys.exit(0)

    async def _run():
        async with async_session_factory() as session:
            await build_chunks(args.book, mmd_path, session)

    asyncio.run(_run())
