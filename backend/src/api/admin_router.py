"""
Admin API endpoints for the ADA Admin Console.

All endpoints require X-API-Key header matching API_SECRET_KEY.
Provides book management, subject management, pipeline status, and publishing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, Form, File
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import require_admin
from auth.models import User
from config import OUTPUT_DIR, DATA_DIR
from db.connection import get_db
from db.models import Book, Subject, ConceptChunk, ChunkImage
from extraction.calibrate import derive_slug
from api.chunk_knowledge_service import _normalize_image_url

router = APIRouter()
logger = logging.getLogger(__name__)
_API_KEY = os.getenv("API_SECRET_KEY", "")


def _clean_output_dir(out_dir: Path) -> None:
    """Remove pipeline artifacts, preserving expensive Mathpix data (book.mmd + mathpix_extracted/)."""
    if not out_dir.exists():
        return
    _preserve = {"book.mmd", "mathpix_extracted"}
    for item in out_dir.iterdir():
        if item.name in _preserve:
            continue
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)
    logger.info("[clean] Cleaned output dir %s (preserved Mathpix data)", out_dir)


def _check_api_key(request: Request) -> None:
    if request.headers.get("X-API-Key") != _API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Subjects ───────────────────────────────────────────────────────────────────

@router.get("/api/admin/subjects")
async def list_subjects(
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    subjects = (await db.execute(select(Subject).order_by(Subject.label))).scalars().all()
    result = []
    for s in subjects:
        count = (await db.execute(
            select(func.count()).select_from(Book).where(Book.subject == s.slug)
        )).scalar() or 0
        result.append({
            "slug": s.slug,
            "label": s.label,
            "book_count": count,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })
    return result


@router.post("/api/admin/subjects")
async def create_subject(
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    label = body.get("label", "").strip()
    if not label:
        raise HTTPException(400, "label is required")
    slug = label.lower().replace(" ", "_")
    existing = (await db.execute(select(Subject).where(Subject.slug == slug))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Subject '{slug}' already exists")
    subj = Subject(slug=slug, label=label)
    db.add(subj)
    await db.commit()
    await db.refresh(subj)
    return {"slug": subj.slug, "label": subj.label}


# ── Books ──────────────────────────────────────────────────────────────────────

@router.post("/api/admin/books/upload")
async def upload_book(
    request: Request,
    file: UploadFile = File(...),
    subject: str = Form(...),
    title: str = Form(...),
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    slug = derive_slug(file.filename)
    dest_dir = DATA_DIR / subject
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / file.filename
    content = await file.read()
    dest_path.write_bytes(content)
    logger.info("[upload] Saved PDF: %s (slug=%s)", dest_path, slug)

    # Upsert book row
    existing = (await db.execute(select(Book).where(Book.book_slug == slug))).scalar_one_or_none()
    if existing:
        existing.title = title
        existing.subject = subject
        existing.status = "PROCESSING"
        existing.pdf_filename = file.filename
        existing.published_at = None
    else:
        book = Book(
            book_slug=slug,
            title=title,
            subject=subject,
            status="PROCESSING",
            pdf_filename=file.filename,
        )
        db.add(book)
    await db.commit()

    subprocess.Popen([
        sys.executable, "-m", "src.watcher.pipeline_runner",
        "--pdf", str(dest_path),
        "--subject", subject,
    ])
    logger.info("[upload] Spawned pipeline for '%s' (subject=%s)", slug, subject)
    return {"slug": slug, "title": title, "subject": subject, "status": "PROCESSING"}


@router.get("/api/admin/books")
async def list_admin_books(
    subject: str = None,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    q = select(Book).order_by(Book.created_at.desc())
    if subject:
        q = q.where(Book.subject == subject)
    books = (await db.execute(q)).scalars().all()
    return [
        {
            "slug": b.book_slug,
            "title": b.title,
            "subject": b.subject,
            "status": b.status,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "published_at": b.published_at.isoformat() if b.published_at else None,
        }
        for b in books
    ]


@router.get("/api/admin/books/{slug}/status")
async def get_book_status(
    slug: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    log_path = OUTPUT_DIR / slug / "pipeline.log"
    stage_number = 0
    stage_label = "Not started"
    log_tail: list[str] = []

    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        log_tail = lines[-3:] if len(lines) >= 3 else lines
        for line in lines:
            if "Stage 1/5" in line and "Calibrating" in line:
                stage_number, stage_label = 1, "Font calibration"
            elif "Stage 1/5" in line and "Done" in line:
                stage_number, stage_label = 1, "Font calibration \u2713"
            elif "Stage 2/5" in line and "Done" not in line:
                stage_number, stage_label = 2, "Mathpix extraction"
            elif "Stage 2/5" in line and "Done" in line:
                stage_number, stage_label = 2, "Mathpix extraction \u2713"
            elif "Stage 3/5" in line and "Done" not in line:
                stage_number, stage_label = 3, "Building chunks & embeddings"
            elif "Stage 3/5" in line and "Done" in line:
                stage_number, stage_label = 3, "Chunks built \u2713"
            elif "Stage 4/5" in line and "Done" not in line:
                stage_number, stage_label = 4, "Building dependency graph"
            elif "Stage 4/5" in line and "Done" in line:
                stage_number, stage_label = 4, "Graph built \u2713"
            elif "Stage 5/5" in line and "Done" not in line:
                stage_number, stage_label = 5, "Hot-loading into server"
            elif "Pipeline complete" in line:
                stage_number, stage_label = 5, "Ready for review"
                # Update DB status when pipeline completes
                book = (await db.execute(
                    select(Book).where(Book.book_slug == slug)
                )).scalar_one_or_none()
                if book and book.status == "PROCESSING":
                    book.status = "READY_FOR_REVIEW"
                    await db.commit()

    book = (await db.execute(select(Book).where(Book.book_slug == slug))).scalar_one_or_none()
    status = book.status if book else "UNKNOWN"
    return {
        "status": status,
        "stage_number": stage_number,
        "stage_label": stage_label,
        "log_tail": log_tail,
    }


@router.get("/api/admin/books/{slug}/sections")
async def get_book_sections(
    slug: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(ConceptChunk.concept_id, func.min(ConceptChunk.section), func.min(ConceptChunk.heading))
        .where(ConceptChunk.book_slug == slug)
        .group_by(ConceptChunk.concept_id)
        .order_by(func.min(ConceptChunk.section))
    )).all()

    chapters: dict = {}
    for concept_id, section, heading in rows:
        # Count chunks for this concept
        chunk_count = (await db.execute(
            select(func.count()).select_from(ConceptChunk)
            .where(ConceptChunk.book_slug == slug, ConceptChunk.concept_id == concept_id)
        )).scalar() or 0
        # Count images via JOIN
        image_count = (await db.execute(
            select(func.count()).select_from(ChunkImage)
            .join(ConceptChunk, ChunkImage.chunk_id == ConceptChunk.id)
            .where(ConceptChunk.book_slug == slug, ConceptChunk.concept_id == concept_id)
        )).scalar() or 0
        # Parse chapter from section string like "1.2"
        try:
            chapter = int(section.split(".")[0])
        except Exception:
            chapter = 0
        if chapter not in chapters:
            chapters[chapter] = []
        chapters[chapter].append({
            "concept_id": concept_id,
            "section": section,
            "heading": heading,
            "chunk_count": chunk_count,
            "image_count": image_count,
        })

    return [{"chapter": ch, "sections": secs} for ch, secs in sorted(chapters.items())]


@router.get("/api/admin/books/{slug}/chunks/{concept_id:path}")
async def get_book_chunks(
    slug: str,
    concept_id: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    chunks = (await db.execute(
        select(ConceptChunk)
        .where(ConceptChunk.book_slug == slug, ConceptChunk.concept_id == concept_id)
        .order_by(ConceptChunk.order_index)
    )).scalars().all()

    result = []
    for chunk in chunks:
        images_rows = (await db.execute(
            select(ChunkImage)
            .where(ChunkImage.chunk_id == chunk.id)
            .order_by(ChunkImage.order_index)
        )).scalars().all()
        images = [
            {"image_url": _normalize_image_url(img.image_url), "caption": img.caption}
            for img in images_rows
        ]
        result.append({
            "id": str(chunk.id),
            "heading": chunk.heading,
            "text": chunk.text,
            "order_index": chunk.order_index,
            "chunk_type": chunk.chunk_type,
            "images": images,
        })
    return result


@router.get("/api/admin/books/{slug}/graph")
async def get_book_graph(
    slug: str,
    _user: User = Depends(require_admin),
):
    graph_path = OUTPUT_DIR / slug / "graph.json"
    if not graph_path.exists():
        raise HTTPException(404, "Graph not yet built")
    return json.loads(graph_path.read_text(encoding="utf-8"))


@router.post("/api/admin/books/{slug}/publish")
async def publish_book(
    slug: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    chunk_count = (await db.execute(
        select(func.count()).select_from(ConceptChunk).where(ConceptChunk.book_slug == slug)
    )).scalar() or 0
    if chunk_count == 0:
        raise HTTPException(
            400,
            f"No chunks found for '{slug}' — pipeline may not have completed",
        )
    graph_path = OUTPUT_DIR / slug / "graph.json"
    if not graph_path.exists():
        raise HTTPException(
            400,
            f"graph.json not found for '{slug}' — pipeline may not have completed",
        )

    book = (await db.execute(select(Book).where(Book.book_slug == slug))).scalar_one_or_none()
    if not book:
        raise HTTPException(404, f"Book '{slug}' not found")
    book.status = "PUBLISHED"
    book.published_at = datetime.now(timezone.utc)
    await db.commit()

    # Hot-load graph into the running knowledge service
    svc = getattr(request.app.state, "chunk_knowledge_svc", None)
    if svc:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, svc.preload_graph, slug)
            logger.info("[publish] Graph preloaded for '%s'", slug)
        except Exception:
            logger.exception("[publish] preload_graph failed for '%s'", slug)

    # Mount images static dir
    book_out_dir = OUTPUT_DIR / slug
    if book_out_dir.exists():
        try:
            request.app.mount(
                f"/images/{slug}",
                StaticFiles(directory=str(book_out_dir)),
                name=f"images_{slug}",
            )
            logger.info("[publish] Mounted /images/%s", slug)
        except Exception:
            pass  # Already mounted — not an error

    logger.info("[publish] Book published: %s", slug)
    return {"status": "PUBLISHED", "book_slug": slug}


@router.post("/api/admin/books/{slug}/drop")
async def drop_book(
    slug: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        text("DELETE FROM concept_chunks WHERE book_slug = :slug"), {"slug": slug}
    )
    await db.commit()
    out_dir = OUTPUT_DIR / slug
    _clean_output_dir(out_dir)
    book = (await db.execute(select(Book).where(Book.book_slug == slug))).scalar_one_or_none()
    if book:
        book.status = "DROPPED"
        await db.commit()
    logger.info("[drop] Book dropped: %s", slug)
    return {"status": "DROPPED", "book_slug": slug}


@router.post("/api/admin/books/{slug}/retrigger")
async def retrigger_book(
    slug: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        text("DELETE FROM concept_chunks WHERE book_slug = :slug"), {"slug": slug}
    )
    await db.commit()
    out_dir = OUTPUT_DIR / slug
    _clean_output_dir(out_dir)
    book = (await db.execute(select(Book).where(Book.book_slug == slug))).scalar_one_or_none()
    if not book:
        raise HTTPException(404, f"Book '{slug}' not found in admin console")
    book.status = "PROCESSING"
    book.published_at = None
    await db.commit()
    pdf_matches = list(DATA_DIR.rglob("*.pdf"))
    matched = [p for p in pdf_matches if derive_slug(p.name) == slug]
    if not matched:
        raise HTTPException(404, f"No PDF found for slug '{slug}' in data/")
    pdf_path = matched[0]
    subject = pdf_path.parent.name.lower()
    if subject == "maths":
        subject = "mathematics"
    subprocess.Popen([
        sys.executable, "-m", "src.watcher.pipeline_runner",
        "--pdf", str(pdf_path),
        "--subject", subject,
    ])
    logger.info("[retrigger] Re-queued '%s' (subject=%s)", slug, subject)
    return {"status": "retriggered", "book_slug": slug, "pdf": pdf_path.name}


# ── Legacy endpoints (moved from main.py, kept for pipeline_runner compatibility) ─────

@router.post("/api/admin/load-book/{book_slug}")
async def admin_load_book(book_slug: str, request: Request):
    """
    Hot-load a newly processed book into the running server without restart.
    Called automatically by the pipeline_runner after pipeline completes.
    Secured by X-API-Key header (must match API_SECRET_KEY).
    """
    _check_api_key(request)

    from db.connection import get_db as _get_db_r
    from extraction.graph_builder import build_graph as _bgfn

    global _reload_lock
    if _reload_lock is None:
        _reload_lock = asyncio.Lock()

    async with _reload_lock:
        graph_path = OUTPUT_DIR / book_slug / "graph.json"
        if not graph_path.exists():
            logger.info("[load-book] Building graph.json for %s", book_slug)
            try:
                async for db in _get_db_r():
                    await _bgfn(db, book_slug, graph_path)
                    break
            except Exception:
                logger.exception("[load-book] Failed to build graph.json for %s", book_slug)
                raise HTTPException(500, f"Failed to build graph.json for {book_slug}")

        svc = getattr(request.app.state, "chunk_knowledge_svc", None)
        if svc:
            loop = asyncio.get_event_loop()
            try:
                await loop.run_in_executor(None, svc.preload_graph, book_slug)
                logger.info("[load-book] Graph preloaded: %s", book_slug)
            except Exception:
                logger.exception("[load-book] Failed to preload graph for %s", book_slug)

        book_out_dir = OUTPUT_DIR / book_slug
        if book_out_dir.exists():
            try:
                request.app.mount(
                    f"/images/{book_slug}",
                    StaticFiles(directory=str(book_out_dir)),
                    name=f"images_{book_slug}",
                )
                logger.info("[load-book] Mounted /images/%s", book_slug)
            except Exception:
                pass  # Already mounted — not an error

    logger.info("[load-book] Book loaded: %s", book_slug)
    return {"status": "loaded", "book_slug": book_slug}


@router.post("/api/admin/retrigger-book/{book_slug}")
async def admin_retrigger_book_legacy(book_slug: str, request: Request):
    """Legacy retrigger endpoint — kept for backward compatibility."""
    _check_api_key(request)

    from db.connection import get_db as _get_db_r

    async for db in _get_db_r():
        await db.execute(
            text("DELETE FROM concept_chunks WHERE book_slug = :slug"),
            {"slug": book_slug},
        )
        await db.commit()
        break
    logger.info("[retrigger] Deleted chunks for '%s'", book_slug)

    out_dir = OUTPUT_DIR / book_slug
    _clean_output_dir(out_dir)

    pdf_matches = list(DATA_DIR.rglob("*.pdf"))
    matched = [p for p in pdf_matches if derive_slug(p.name) == book_slug]
    if not matched:
        raise HTTPException(
            status_code=404,
            detail=f"No PDF found for slug '{book_slug}' under data/.",
        )

    pdf_path = matched[0]
    subject = pdf_path.parent.name.lower()
    if subject == "maths":
        subject = "mathematics"

    subprocess.Popen([
        sys.executable, "-m", "src.watcher.pipeline_runner",
        "--pdf", str(pdf_path),
        "--subject", subject,
    ])
    logger.info("[retrigger] Spawned pipeline for '%s' (subject=%s)", book_slug, subject)

    return {
        "status": "retriggered",
        "book_slug": book_slug,
        "pdf": pdf_path.name,
        "subject": subject,
    }


# Module-level lock shared between load-book calls
_reload_lock: asyncio.Lock | None = None
