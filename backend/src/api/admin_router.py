"""
Admin API endpoints for the Adaptive Learner Admin Console.

All endpoints require X-API-Key header matching API_SECRET_KEY.
Provides book management, subject management, pipeline status, and publishing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, Form, File
from api.rate_limiter import limiter
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import require_admin
from auth.models import User
from config import OUTPUT_DIR, DATA_DIR, BACKEND_DIR
from db.connection import get_db
import openai
import networkx as nx
from uuid import UUID

from db.models import Book, Subject, ConceptChunk, ChunkImage, AdminGraphOverride, TeachingSession, AdminAuditLog
from extraction.calibrate import derive_slug
from extraction.graph_builder import insert_section_node
from api.chunk_knowledge_service import _normalize_image_url, _load_graph, reload_graph_with_overrides, invalidate_graph_cache
import api.audit_service as audit_service
from api.audit_schemas import AuditLogEntryResponse, UndoResponse, RedoResponse
from api.teaching_service import invalidate_chunk_cache

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

@limiter.limit("30/minute")
@router.get("/api/admin/subjects")
async def list_subjects(
    request: Request,
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
            "is_hidden": s.is_hidden,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })
    return result


@limiter.limit("30/minute")
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
    if not re.match(r'^[a-z0-9_-]+$', slug):
        raise HTTPException(400, "Invalid slug: label must produce a slug containing only lowercase letters, digits, underscores, or hyphens")
    existing = (await db.execute(select(Subject).where(Subject.slug == slug))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Subject '{slug}' already exists")
    subj = Subject(slug=slug, label=label)
    db.add(subj)
    await db.flush()

    # ── Auto-translate the new subject label into all 12 non-English locales ──
    try:
        from api.translation_helper import translate_one_string
        async with asyncio.timeout(10.0):
            translations = await translate_one_string(label)
        if translations:
            subj.label_translations = translations
            logger.info(
                "[admin] subject.label_translations populated for slug=%s (%d langs)",
                slug, max(len(translations) - 1, 0),
            )
    except Exception:
        logger.warning(
            "[admin] subject label translation failed for slug=%s — English-only", slug,
        )
    # ── End translation block ────────────────────────────────────────────────

    await db.commit()
    await db.refresh(subj)
    return {"slug": subj.slug, "label": subj.label}


@limiter.limit("30/minute")
@router.put("/api/admin/subjects/{slug}")
async def update_subject(
    slug: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a subject's display label. The slug is immutable."""
    body = await request.json()
    label = body.get("label", "").strip()
    if not label:
        raise HTTPException(400, "label is required")
    subj = (await db.execute(select(Subject).where(Subject.slug == slug))).scalar_one_or_none()
    if not subj:
        raise HTTPException(404, f"Subject '{slug}' not found")
    old_label = subj.label
    subj.label = label
    db.add(subj)
    await db.flush()

    # ── Auto-translate the updated subject label into all 12 non-English locales ──
    if label != old_label:
        try:
            from api.translation_helper import translate_one_string
            async with asyncio.timeout(10.0):
                translations = await translate_one_string(label)
            if translations:
                subj.label_translations = translations
                logger.info(
                    "[admin] subject.label_translations updated for slug=%s (%d langs)",
                    slug, max(len(translations) - 1, 0),
                )
        except Exception:
            logger.warning(
                "[admin] subject label translation failed for slug=%s — English-only", slug,
            )
    # ── End translation block ────────────────────────────────────────────────

    await db.commit()
    await db.refresh(subj)
    logger.info("[admin] Subject updated: slug=%s new_label=%s by admin=%s", slug, label, str(_user.id))
    return {"slug": subj.slug, "label": subj.label}


@limiter.limit("30/minute")
@router.delete("/api/admin/subjects/{slug}", status_code=204)
async def delete_subject(
    request: Request,
    slug: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a subject. Returns 409 if any books are associated with it."""
    subj = (await db.execute(select(Subject).where(Subject.slug == slug))).scalar_one_or_none()
    if not subj:
        raise HTTPException(404, f"Subject '{slug}' not found")
    book_count = (
        await db.execute(select(func.count()).select_from(Book).where(Book.subject == slug))
    ).scalar() or 0
    if book_count > 0:
        raise HTTPException(
            409,
            f"Cannot delete subject '{slug}': {book_count} book(s) are associated with it. "
            "Remove or reassign those books first.",
        )
    from sqlalchemy import delete as sa_delete
    await db.execute(sa_delete(Subject).where(Subject.slug == slug))
    await db.commit()
    logger.info("[admin] Subject deleted: slug=%s by admin=%s", slug, str(_user.id))


@limiter.limit("30/minute")
@router.patch("/api/admin/subjects/{slug}/visibility")
async def toggle_subject_visibility(
    slug: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Hide or unhide a subject from students."""
    body = await request.json()
    is_hidden = body.get("is_hidden")
    if is_hidden is None:
        raise HTTPException(400, "is_hidden is required")
    subj = (await db.execute(select(Subject).where(Subject.slug == slug))).scalar_one_or_none()
    if not subj:
        raise HTTPException(404, f"Subject '{slug}' not found")
    subj.is_hidden = bool(is_hidden)
    await db.commit()
    logger.info("[admin] Subject visibility: slug=%s is_hidden=%s by admin=%s", slug, is_hidden, str(_user.id))
    return {"slug": subj.slug, "is_hidden": subj.is_hidden}


# ── Books ──────────────────────────────────────────────────────────────────────

@limiter.limit("10/minute")
@router.post("/api/admin/books/upload")
async def upload_book(
    request: Request,
    file: UploadFile = File(...),
    subject: str = Form(...),
    title: str = Form(...),
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Sanitize inputs to prevent path traversal
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', subject):
        raise HTTPException(400, "Invalid subject name — alphanumeric, hyphens, underscores only")
    safe_filename = Path(file.filename).name
    if not safe_filename or safe_filename.startswith('.') or '/' in file.filename or '\\' in file.filename:
        raise HTTPException(400, "Invalid filename")
    # Derive slug from user-given title (not PDF filename)
    slug = derive_slug(title)
    if not slug:
        raise HTTPException(400, "Title must contain at least one alphanumeric character")
    # Ensure slug uniqueness — append _2, _3, … if taken by a different book
    base_slug = slug
    counter = 1
    while True:
        dup = (await db.execute(select(Book).where(Book.book_slug == slug))).scalar_one_or_none()
        if dup is None or dup.title == title:
            break
        counter += 1
        slug = f"{base_slug}_{counter}"
    dest_dir = DATA_DIR / subject
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_filename
    try:
        dest_path.resolve().relative_to(DATA_DIR.resolve())
    except ValueError:
        raise HTTPException(400, "Invalid upload destination")
    content = await file.read()
    # Validate file size (max 200MB — nginx allows 500MB but we cap lower since
    # the whole file is loaded into RAM here; a 500MB upload would use ~12% of
    # available memory which is too risky on the 8GB server).
    if len(content) > 200_000_000:
        raise HTTPException(status_code=413, detail="File too large (max 200MB)")
    # Validate file is a PDF (magic bytes)
    if content[:4] != b"%PDF":
        raise HTTPException(status_code=400, detail="File must be a PDF")
    # Write to a temp file first, then rename — avoids OSError if the
    # destination is locked by a running pipeline from a previous upload.
    tmp_path = dest_path.with_suffix(".pdf.tmp")
    try:
        tmp_path.write_bytes(content)
        tmp_path.replace(dest_path)
    except OSError:
        # Fallback: if rename fails (cross-device, lock), write directly
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
        "--slug", slug,
    ], cwd=str(BACKEND_DIR))
    logger.info("[upload] Spawned pipeline for '%s' (subject=%s)", slug, subject)
    return {"slug": slug, "title": title, "subject": subject, "status": "PROCESSING"}


@limiter.limit("30/minute")
@router.get("/api/admin/books")
async def list_admin_books(
    request: Request,
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
            "is_hidden": b.is_hidden,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "published_at": b.published_at.isoformat() if b.published_at else None,
        }
        for b in books
    ]


@limiter.limit("30/minute")
@router.patch("/api/admin/books/{slug}/visibility")
async def toggle_book_visibility(
    slug: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Hide or unhide a published book from students."""
    body = await request.json()
    is_hidden = body.get("is_hidden")
    if is_hidden is None:
        raise HTTPException(400, "is_hidden is required")
    book = (await db.execute(select(Book).where(Book.book_slug == slug))).scalar_one_or_none()
    if not book:
        raise HTTPException(404, f"Book '{slug}' not found")
    book.is_hidden = bool(is_hidden)
    await db.commit()
    logger.info("[admin] Book visibility: slug=%s is_hidden=%s by admin=%s", slug, is_hidden, str(_user.id))
    return {"slug": book.book_slug, "is_hidden": book.is_hidden}


@limiter.limit("30/minute")
@router.patch("/api/admin/books/{slug}/rename")
async def rename_book(
    slug: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Rename a book's display title."""
    body = await request.json()
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(400, "title is required")
    book = (await db.execute(select(Book).where(Book.book_slug == slug))).scalar_one_or_none()
    if not book:
        raise HTTPException(404, f"Book '{slug}' not found")
    old_title = book.title
    book.title = title
    await db.flush()

    # ── Auto-translate the new title into all 12 non-English locales ───────
    if title != old_title:
        try:
            from api.translation_helper import translate_one_string
            async with asyncio.timeout(10.0):
                translations = await translate_one_string(title)
            if translations:
                book.title_translations = translations
                logger.info(
                    "[admin] book.title_translations populated for slug=%s (%d langs)",
                    slug, max(len(translations) - 1, 0),
                )
        except Exception:
            logger.warning(
                "[admin] book title translation failed for slug=%s — English-only", slug,
            )
    # ── End translation block ────────────────────────────────────────────────

    await db.commit()
    logger.info("[admin] Book renamed: slug=%s title=%s by admin=%s", slug, title, str(_user.id))
    return {"slug": book.book_slug, "title": book.title}


@limiter.limit("30/minute")
@router.get("/api/admin/books/{slug}/status")
async def get_book_status(
    request: Request,
    slug: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    log_path = OUTPUT_DIR / slug / "pipeline.log"
    stage_number = 0
    stage_label = "Not started"
    log_tail: list[str] = []
    lines: list[str] = []

    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        log_tail = lines[-20:] if len(lines) >= 20 else lines

        # Pre-stage detection: log file has content → pipeline process is running
        if lines:
            stage_number, stage_label = -1, "Initializing"

        for line in lines:
            # Pre-stage messages (overwritten once Stage markers appear)
            if "Waiting for file to stabilise" in line and stage_number < 1:
                stage_number, stage_label = -1, "Stabilizing upload"
            elif "File stable" in line and stage_number < 1:
                stage_number, stage_label = -1, "Starting pipeline"
            elif "Pipeline started" in line and stage_number < 1:
                stage_number, stage_label = -1, "Pipeline started"

            # Stage 1–6 markers (6-stage pipeline)
            if "Stage 1/6" in line and "Done" not in line:
                stage_number, stage_label = 1, "Registering book metadata"
            elif "Stage 1/6" in line and "Done" in line:
                stage_number, stage_label = 1, "Book registered \u2713"
            elif "Stage 2/6" in line and "Done" not in line:
                stage_number, stage_label = 2, "Mathpix PDF extraction"
            elif "Stage 2/6" in line and "Done" in line:
                stage_number, stage_label = 2, "Mathpix extraction \u2713"
            elif "Stage 3/6" in line and "Done" not in line:
                stage_number, stage_label = 3, "Building chunks & embeddings"
            elif "Stage 3/6" in line and "Done" in line:
                stage_number, stage_label = 3, "Chunks built \u2713"
            elif "Stage 4/6" in line and "Validat" in line and "FAILED" not in line and "passed" not in line:
                stage_number, stage_label = 4, "Validating parsed chunks"
            elif "Stage 4/6" in line and "passed" in line:
                stage_number, stage_label = 4, "Validation passed \u2713"
            elif "Stage 5/6" in line and "Done" not in line:
                stage_number, stage_label = 5, "Building dependency graph"
            elif "Stage 5/6" in line and "Done" in line:
                stage_number, stage_label = 5, "Graph built \u2713"
            elif "Stage 6/6" in line and "Done" not in line:
                stage_number, stage_label = 6, "Hot-loading into server"
            elif "Hot-load successful" in line:
                stage_number, stage_label = 6, "Hot-load complete ✓"
            elif "Stage 7/7" in line and "Auto-translating" in line:
                stage_number, stage_label = 7, "Translating to all languages"
            elif "Stage 7/7" in line and "Translated" in line:
                stage_number, stage_label = 7, "Translation complete ✓"
            elif "Stage 7/7" in line and "Skipped" in line:
                stage_number, stage_label = 7, "Translation skipped"
            elif "Pipeline complete" in line:
                stage_number, stage_label = 7, "Ready for review"
                # Update DB status when pipeline completes
                book = (await db.execute(
                    select(Book).where(Book.book_slug == slug)
                )).scalar_one_or_none()
                if book and book.status == "PROCESSING":
                    book.status = "READY_FOR_REVIEW"
                    await db.commit()

    # Filtered stage-marker lines for clear progression view
    stage_lines = [
        line for line in lines
        if ("Stage " in line and ("/6" in line or "/7" in line))
        or "Pipeline started" in line
        or "Pipeline complete" in line
        or "Pipeline FAILED" in line
    ][-10:]

    book = (await db.execute(select(Book).where(Book.book_slug == slug))).scalar_one_or_none()
    status = book.status if book else "UNKNOWN"
    return {
        "status": status,
        "stage_number": stage_number,
        "stage_label": stage_label,
        "log_tail": log_tail,
        "stage_lines": stage_lines,
    }


def _section_sort_key(section_str: str):
    """Parse 'X.Y[a]' or 'X.Y.Z' into a numeric tuple for correct section ordering.
    Handles letter suffixes: '1.1b' sorts between '1.1' and '1.2'.
    Strips trailing title text: '3.0 Chapter 3 Introduction' uses just '3.0'.
    """
    s = section_str or ""
    # Extract leading section number (multi-level + optional letter suffix).
    # Without this, '3.0 Chapter 3 Introduction' parses '0 Chapter 3 Introduction'
    # as inf, making (3, 0, inf, 0) sort AFTER promoted '3.1b' (3, 0, 1, 2).
    # Pattern handles: '3.1', '3.1b', '3.1.5', '3.1.5b' (multi-level supported).
    m_lead = re.match(r"^(\d+(?:\.\d+)+[a-z]?)", s)
    if m_lead:
        s = m_lead.group(1)

    parts = []
    for p in s.split("."):
        try:
            parts.extend([int(p), 0])
            continue
        except (ValueError, AttributeError):
            pass
        m = re.match(r'^(\d+)([a-z])$', p or '')
        if m:
            parts.extend([int(m.group(1)), ord(m.group(2)) - ord('a') + 1])
            continue
        parts.extend([float("inf"), 0])
    return tuple(parts) if parts else (float("inf"), 0)


@limiter.limit("30/minute")
@router.get("/api/admin/books/{slug}/sections")
async def get_book_sections(
    request: Request,
    slug: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import aliased

    book = (await db.execute(select(Book).where(Book.book_slug == slug))).scalar_one_or_none()
    book_title = book.title if book else slug.replace("_", " ")

    _cc2 = aliased(ConceptChunk, flat=True)
    first_heading_sq = (
        select(_cc2.heading)
        .where(_cc2.concept_id == ConceptChunk.concept_id,
               _cc2.book_slug == ConceptChunk.book_slug)
        .order_by(_cc2.order_index.asc(), _cc2.id.asc())
        .limit(1)
        .correlate(ConceptChunk)
        .scalar_subquery()
    )

    rows = (await db.execute(
        select(
            ConceptChunk.concept_id,
            func.min(ConceptChunk.section),
            first_heading_sq.label("heading"),
            func.min(ConceptChunk.admin_section_name),
            # Aggregate booleans: section is optional/exam-disabled if ALL chunks are
            func.bool_and(ConceptChunk.is_optional),
            func.bool_and(ConceptChunk.exam_disabled),
            func.bool_and(ConceptChunk.is_hidden),
            # Per-flag counts for mixed-state detection
            func.count().label("chunk_count"),
            func.count().filter(ConceptChunk.is_hidden == True).label("hidden_count"),
            func.count().filter(ConceptChunk.is_optional == True).label("optional_count"),
            func.count().filter(ConceptChunk.exam_disabled == True).label("exam_disabled_count"),
        )
        .where(ConceptChunk.book_slug == slug)
        .group_by(ConceptChunk.concept_id, ConceptChunk.book_slug)
        # Order by MMD position (order_index) not text section. `order_index` is
        # globally sequential, so min() per concept_id reflects the section's
        # earliest position in the book — matching MMD order. Using text
        # ordering on `section` caused promoted sections with empty/text labels
        # to sort to the top.
        .order_by(func.min(ConceptChunk.order_index))
    )).all()

    chapters: dict = {}
    for (concept_id, section, heading, admin_name, is_optional, exam_disabled, is_hidden,
         chunk_count_agg, hidden_count, optional_count, exam_disabled_count) in rows:
        chunk_count = chunk_count_agg or 0
        # Count images via JOIN
        image_count = (await db.execute(
            select(func.count()).select_from(ChunkImage)
            .join(ConceptChunk, ChunkImage.chunk_id == ConceptChunk.id)
            .where(ConceptChunk.book_slug == slug, ConceptChunk.concept_id == concept_id)
        )).scalar() or 0
        # Parse chapter from section string like "1.2"; fall back to concept_id
        # for promoted sections whose section is a text name (e.g. "Key Concepts")
        try:
            chapter = int(section.split(".")[0])
        except (ValueError, AttributeError):
            # Try deriving chapter from concept_id (e.g. "prealgebra_1.6" → 1)
            _cid_suffix = concept_id[len(slug) + 1:] if concept_id.startswith(slug + "_") else ""
            try:
                chapter = int(_cid_suffix.split(".")[0])
            except (ValueError, AttributeError):
                _m = re.search(r'(\d+)', section or "")
                chapter = int(_m.group(1)) if _m else 9999
        if chapter not in chapters:
            chapters[chapter] = []
        chapters[chapter].append({
            "concept_id": concept_id,
            "section": section,
            "display_name": admin_name or section,  # prefer admin override
            "heading": heading,
            "chunk_count": chunk_count,
            "image_count": image_count,
            "is_optional": bool(is_optional),
            "exam_disabled": bool(exam_disabled),
            "is_hidden": bool(is_hidden),
            "hidden_count": hidden_count or 0,
            "optional_count": optional_count or 0,
            "exam_disabled_count": exam_disabled_count or 0,
        })

    # Sort sections within each chapter numerically (e.g. 1.2 before 1.10).
    # For promoted sections with text names, fall back to concept_id for ordering.
    def _sort_key_with_fallback(s):
        section = s["section"] or ""
        if re.match(r"^\d+\.\d+", section):
            return _section_sort_key(section)
        cid = s.get("concept_id", "")
        cid_suffix = cid[len(slug) + 1:] if cid.startswith(slug + "_") else ""
        return _section_sort_key(cid_suffix)

    for ch_secs in chapters.values():
        ch_secs.sort(key=_sort_key_with_fallback)

    return {"title": book_title, "chapters": [{"chapter": ch, "sections": secs} for ch, secs in sorted(chapters.items())]}


@limiter.limit("30/minute")
@router.get("/api/admin/books/{slug}/chunks/{concept_id:path}")
async def get_book_chunks(
    request: Request,
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
    for i, chunk in enumerate(chunks):
        images_rows = (await db.execute(
            select(ChunkImage)
            .where(ChunkImage.chunk_id == chunk.id)
            .order_by(ChunkImage.order_index)
        )).scalars().all()
        images = [
            {"image_url": _normalize_image_url(img.image_url), "caption": img.caption}
            for img in images_rows
        ]
        next_chunk = chunks[i + 1] if i + 1 < len(chunks) else None
        result.append({
            "id": str(chunk.id),
            "heading": chunk.heading,
            "text": chunk.text,
            "order_index": chunk.order_index,
            "chunk_type": chunk.chunk_type,
            "is_optional": chunk.is_optional,
            "is_hidden": chunk.is_hidden,
            "exam_disabled": chunk.exam_disabled,
            "has_embedding": chunk.embedding is not None,
            "next_chunk_id": str(next_chunk.id) if next_chunk else None,
            "images": images,
        })
    return result


@limiter.limit("30/minute")
@router.get("/api/admin/books/{slug}/graph")
async def get_book_graph(
    request: Request,
    slug: str,
    _user: User = Depends(require_admin),
):
    graph_path = OUTPUT_DIR / slug / "graph.json"
    if not graph_path.exists():
        raise HTTPException(404, "Graph not yet built")
    return json.loads(graph_path.read_text(encoding="utf-8"))


@limiter.limit("30/minute")
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


@limiter.limit("10/minute")
@router.post("/api/admin/books/{slug}/drop")
async def drop_book(
    request: Request,
    slug: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Drop a book's content (reset to empty state, keep the Book row)."""
    prefix = f"{slug}_%"
    await db.execute(text("DELETE FROM student_mastery WHERE concept_id LIKE :prefix"), {"prefix": prefix})
    await db.execute(text("DELETE FROM spaced_reviews WHERE concept_id LIKE :prefix"), {"prefix": prefix})
    await db.execute(text("DELETE FROM teaching_sessions WHERE book_slug = :slug"), {"slug": slug})
    await db.execute(text("DELETE FROM concept_chunks WHERE book_slug = :slug"), {"slug": slug})
    await db.execute(text("DELETE FROM admin_graph_overrides WHERE book_slug = :slug"), {"slug": slug})
    book = (await db.execute(select(Book).where(Book.book_slug == slug))).scalar_one_or_none()
    if book:
        book.status = "DROPPED"
    await db.commit()
    invalidate_graph_cache(slug)
    out_dir = OUTPUT_DIR / slug
    _clean_output_dir(out_dir)
    logger.info("[drop] Book dropped: %s (all related data cleaned)", slug)
    return {"status": "DROPPED", "book_slug": slug}


@limiter.limit("10/minute")
@router.delete("/api/admin/books/{slug}", status_code=204)
async def delete_book(
    request: Request,
    slug: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a book and ALL related data (sessions, mastery, chunks, overrides)."""
    book = (await db.execute(select(Book).where(Book.book_slug == slug))).scalar_one_or_none()
    if not book:
        raise HTTPException(404, f"Book '{slug}' not found")

    prefix = f"{slug}_%"
    # Order matters: respect FK constraints
    await db.execute(text("DELETE FROM student_mastery WHERE concept_id LIKE :prefix"), {"prefix": prefix})
    await db.execute(text("DELETE FROM spaced_reviews WHERE concept_id LIKE :prefix"), {"prefix": prefix})
    await db.execute(text("DELETE FROM teaching_sessions WHERE book_slug = :slug"), {"slug": slug})
    await db.execute(text("DELETE FROM concept_chunks WHERE book_slug = :slug"), {"slug": slug})
    await db.execute(text("DELETE FROM admin_graph_overrides WHERE book_slug = :slug"), {"slug": slug})
    await db.execute(text("DELETE FROM books WHERE book_slug = :slug"), {"slug": slug})
    await db.commit()

    # Post-commit cleanup
    invalidate_graph_cache(slug)
    out_dir = OUTPUT_DIR / slug
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)

    logger.info("[delete] Book permanently deleted: %s by admin=%s", slug, str(_user.id))


@limiter.limit("10/minute")
@router.post("/api/admin/books/{slug}/retrigger")
async def retrigger_book(
    request: Request,
    slug: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        text("DELETE FROM concept_chunks WHERE book_slug = :slug"), {"slug": slug}
    )
    await db.execute(
        text("DELETE FROM admin_graph_overrides WHERE book_slug = :slug"), {"slug": slug}
    )
    await db.commit()
    invalidate_graph_cache(slug)
    out_dir = OUTPUT_DIR / slug
    _clean_output_dir(out_dir)
    book = (await db.execute(select(Book).where(Book.book_slug == slug))).scalar_one_or_none()
    if not book:
        raise HTTPException(404, f"Book '{slug}' not found in admin console")
    book.status = "PROCESSING"
    book.published_at = None
    await db.commit()
    # Find the PDF using the stored filename from the Book table
    pdf_matches = list(DATA_DIR.rglob("*.pdf"))
    matched = [p for p in pdf_matches if p.name == book.pdf_filename] if book.pdf_filename else []
    if not matched:
        # Fallback 1: try legacy slug-based lookup
        matched = [p for p in pdf_matches if derive_slug(p.name) == slug]
    if not matched:
        # Fallback 2: fuzzy match by book title keywords
        title_words = [w.lower() for w in (book.title or "").split() if len(w) > 2]
        if title_words:
            matched = [p for p in pdf_matches if all(w in p.stem.lower() for w in title_words)]
    if not matched:
        raise HTTPException(404, f"No PDF found for slug '{slug}' in data/")
    pdf_path = matched[0]
    # Self-healing: update stored filename if found via fallback
    if pdf_path.name != book.pdf_filename:
        book.pdf_filename = pdf_path.name
        await db.commit()
    subject = pdf_path.parent.name.lower()
    if subject == "maths":
        subject = "mathematics"
    subprocess.Popen([
        sys.executable, "-m", "src.watcher.pipeline_runner",
        "--pdf", str(pdf_path),
        "--subject", subject,
        "--slug", slug,
    ], cwd=str(BACKEND_DIR))
    logger.info("[retrigger] Re-queued '%s' (subject=%s)", slug, subject)
    return {"status": "retriggered", "book_slug": slug, "pdf": pdf_path.name}


# ── Legacy endpoints (moved from main.py, kept for pipeline_runner compatibility) ─────

@router.post("/api/admin/load-book/{book_slug}")
async def admin_load_book(
    book_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Hot-load a newly processed book into the running server without restart.
    Called automatically by the pipeline_runner after pipeline completes.
    Accepts EITHER an admin JWT (Bearer token) OR X-API-Key header.
    This dual-auth supports both the Admin UI and the automated pipeline_runner.
    """
    from auth.jwt import decode_access_token as _decode
    from auth.models import User as _AuthUser
    from sqlalchemy import select as _select

    authed = False
    # Try Bearer JWT admin auth first (used by Admin UI)
    raw_creds = request.headers.get("authorization", "")
    if raw_creds.lower().startswith("bearer "):
        token = raw_creds.split(" ", 1)[1]
        try:
            payload = _decode(token)
            user_id = payload.get("sub")
            if user_id:
                result = await db.execute(_select(_AuthUser).where(_AuthUser.id == user_id))
                user = result.scalar_one_or_none()
                if user and user.is_active and user.role == "admin":
                    authed = True
        except Exception:
            pass  # Fall through to API key check

    # Fall back to API key auth (used by pipeline_runner)
    if not authed:
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
                async for _graph_db in _get_db_r():
                    await _bgfn(_graph_db, book_slug, graph_path)
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
        await db.execute(
            text("DELETE FROM admin_graph_overrides WHERE book_slug = :slug"),
            {"slug": book_slug},
        )
        await db.commit()
        break
    invalidate_graph_cache(book_slug)
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


# ── Dashboard ──────────────────────────────────────────────────────────────────

@limiter.limit("30/minute")
@router.get("/api/admin/dashboard")
async def admin_dashboard(
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return platform-wide summary metrics for the admin dashboard."""
    from db.models import Student, TeachingSession, StudentMastery

    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)

    total_students = (
        await db.execute(select(func.count()).select_from(Student))
    ).scalar() or 0

    active_7d = (
        await db.execute(
            select(func.count(func.distinct(TeachingSession.student_id)))
            .where(TeachingSession.started_at >= seven_days_ago)
        )
    ).scalar() or 0

    active_30d = (
        await db.execute(
            select(func.count(func.distinct(TeachingSession.student_id)))
            .where(TeachingSession.started_at >= thirty_days_ago)
        )
    ).scalar() or 0

    total_sessions = (
        await db.execute(select(func.count()).select_from(TeachingSession))
    ).scalar() or 0

    sessions_this_week = (
        await db.execute(
            select(func.count()).select_from(TeachingSession)
            .where(TeachingSession.started_at >= seven_days_ago)
        )
    ).scalar() or 0

    avg_mastery_rate = (
        await db.execute(select(func.avg(Student.overall_accuracy_rate)))
    ).scalar() or 0.0

    total_concepts_mastered = (
        await db.execute(select(func.count()).select_from(StudentMastery))
    ).scalar() or 0

    struggling_rows = (
        await db.execute(
            select(Student.id, Student.display_name, Student.overall_accuracy_rate)
            .where(Student.overall_accuracy_rate < 0.3, Student.section_count > 3)
            .order_by(Student.overall_accuracy_rate.asc())
            .limit(10)
        )
    ).all()
    struggling_students = [
        {"id": str(r.id), "display_name": r.display_name, "accuracy": r.overall_accuracy_rate}
        for r in struggling_rows
    ]

    return {
        "total_students": total_students,
        "active_7d": active_7d,
        "active_30d": active_30d,
        "total_sessions": total_sessions,
        "sessions_this_week": sessions_this_week,
        "avg_mastery_rate": round(float(avg_mastery_rate), 4),
        "total_concepts_mastered": total_concepts_mastered,
        "struggling_students": struggling_students,
    }


# ── Student Management ─────────────────────────────────────────────────────────

@limiter.limit("30/minute")
@router.get("/api/admin/students")
async def admin_list_students(
    request: Request,
    search: str = None,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List students with optional search, pagination, and sorting."""
    from db.models import Student
    from sqlalchemy import asc, desc

    limit = min(limit, 200)
    offset = min(offset, 10_000)

    # Allowed sort columns mapped to ORM attributes
    _sortable = {
        "created_at": Student.created_at,
        "display_name": Student.display_name,
        "xp": Student.xp,
        "section_count": Student.section_count,
        "overall_accuracy_rate": Student.overall_accuracy_rate,
    }
    sort_col = _sortable.get(sort_by, Student.created_at)
    order_fn = desc if sort_dir == "desc" else asc

    base_q = (
        select(Student, User)
        .outerjoin(User, User.id == Student.user_id)
    )
    if search:
        pattern = f"%{search}%"
        base_q = base_q.where(
            Student.display_name.ilike(pattern) | User.email.ilike(pattern)
        )

    total = (
        await db.execute(
            select(func.count()).select_from(base_q.subquery())
        )
    ).scalar() or 0

    rows = (
        await db.execute(
            base_q.order_by(order_fn(sort_col)).offset(offset).limit(limit)
        )
    ).all()

    items = []
    for student, user in rows:
        items.append({
            "id": str(student.id),
            "display_name": student.display_name,
            "email": user.email if user else None,
            "age": student.age,
            "xp": student.xp,
            "streak": student.streak,
            "preferred_style": student.preferred_style,
            "preferred_language": student.preferred_language,
            "section_count": student.section_count,
            "overall_accuracy_rate": student.overall_accuracy_rate,
            "created_at": student.created_at.isoformat() if student.created_at else None,
            "is_active": user.is_active if user else None,
        })

    return {"total": total, "items": items}


@limiter.limit("30/minute")
@router.get("/api/admin/students/{student_id}")
async def admin_get_student(
    request: Request,
    student_id: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return full student detail including stats, recent sessions, and mastery list."""
    from db.models import Student, TeachingSession, StudentMastery, CardInteraction

    student = (
        await db.execute(select(Student).where(Student.id == student_id))
    ).scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Student not found")

    linked_user = None
    if student.user_id:
        linked_user = (
            await db.execute(select(User).where(User.id == student.user_id))
        ).scalar_one_or_none()

    # Stats
    mastery_count = (
        await db.execute(
            select(func.count()).select_from(StudentMastery)
            .where(StudentMastery.student_id == student.id)
        )
    ).scalar() or 0

    total_sessions = (
        await db.execute(
            select(func.count()).select_from(TeachingSession)
            .where(TeachingSession.student_id == student.id)
        )
    ).scalar() or 0

    avg_time_row = (
        await db.execute(
            select(func.avg(CardInteraction.time_on_card_sec))
            .where(CardInteraction.student_id == student.id)
        )
    ).scalar()
    avg_time_per_card = round(float(avg_time_row), 2) if avg_time_row else 0.0

    total_cards_completed = (
        await db.execute(
            select(func.count()).select_from(CardInteraction)
            .where(CardInteraction.student_id == student.id)
        )
    ).scalar() or 0

    # Recent sessions (last 20)
    session_rows = (
        await db.execute(
            select(TeachingSession)
            .where(TeachingSession.student_id == student.id)
            .order_by(TeachingSession.started_at.desc())
            .limit(20)
        )
    ).scalars().all()
    recent_sessions = [
        {
            "id": str(s.id),
            "concept_id": s.concept_id,
            "book_slug": s.book_slug,
            "phase": s.phase,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "completed_at": s.completed_at.isoformat() if s.completed_at else None,
            "check_score": s.check_score,
            "concept_mastered": s.concept_mastered,
        }
        for s in session_rows
    ]

    # Full mastery list
    mastery_rows = (
        await db.execute(
            select(StudentMastery).where(StudentMastery.student_id == student.id)
        )
    ).scalars().all()
    mastery_list = [
        {
            "concept_id": m.concept_id,
            "mastered_at": m.mastered_at.isoformat() if m.mastered_at else None,
        }
        for m in mastery_rows
    ]

    return {
        "profile": {
            "id": str(student.id),
            "display_name": student.display_name,
            "email": linked_user.email if linked_user else None,
            "is_active": linked_user.is_active if linked_user else None,
            "age": student.age,
            "xp": student.xp,
            "streak": student.streak,
            "preferred_style": student.preferred_style,
            "preferred_language": student.preferred_language,
            "section_count": student.section_count,
            "overall_accuracy_rate": student.overall_accuracy_rate,
            "avg_state_score": student.avg_state_score,
            "boredom_pattern": student.boredom_pattern,
            "frustration_tolerance": student.frustration_tolerance,
            "recovery_speed": student.recovery_speed,
            "interests": student.interests,
            "state_distribution": student.state_distribution,
            "created_at": student.created_at.isoformat() if student.created_at else None,
            "updated_at": student.updated_at.isoformat() if student.updated_at else None,
        },
        "stats": {
            "mastery_count": mastery_count,
            "total_sessions": total_sessions,
            "avg_time_per_card": avg_time_per_card,
            "total_cards_completed": total_cards_completed,
        },
        "recent_sessions": recent_sessions,
        "mastery_list": mastery_list,
    }


@limiter.limit("30/minute")
@router.patch("/api/admin/students/{student_id}")
async def admin_update_student(
    student_id: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update editable student profile fields."""
    from db.models import Student

    student = (
        await db.execute(select(Student).where(Student.id == student_id))
    ).scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Student not found")

    body = await request.json()
    allowed_styles = {"default", "pirate", "astronaut", "gamer"}

    if "display_name" in body:
        val = str(body["display_name"]).strip()
        if not val:
            raise HTTPException(400, "display_name cannot be empty")
        student.display_name = val

    if "age" in body:
        student.age = int(body["age"]) if body["age"] is not None else None

    if "preferred_style" in body:
        style = str(body["preferred_style"])
        if style not in allowed_styles:
            raise HTTPException(400, f"preferred_style must be one of: {sorted(allowed_styles)}")
        student.preferred_style = style

    if "preferred_language" in body:
        student.preferred_language = str(body["preferred_language"])

    student.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(student)
    logger.info("[admin] Student %s updated by admin %s", student_id, str(_user.id))
    return {"id": str(student.id), "display_name": student.display_name}


@limiter.limit("30/minute")
@router.patch("/api/admin/students/{student_id}/access")
async def admin_set_student_access(
    student_id: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Enable or disable the student's linked user account."""
    from db.models import Student

    body = await request.json()
    if "is_active" not in body:
        raise HTTPException(400, "is_active is required")

    student = (
        await db.execute(select(Student).where(Student.id == student_id))
    ).scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Student not found")

    if not student.user_id:
        raise HTTPException(404, "Student has no linked user account")

    linked_user = (
        await db.execute(select(User).where(User.id == student.user_id))
    ).scalar_one_or_none()
    if not linked_user:
        raise HTTPException(404, "Linked user not found")

    linked_user.is_active = bool(body["is_active"])
    await db.commit()
    logger.info(
        "[admin] Student %s access set to is_active=%s by admin %s",
        student_id, linked_user.is_active, str(_user.id),
    )
    return {"is_active": linked_user.is_active}


@limiter.limit("10/minute")
@router.delete("/api/admin/students/{student_id}")
async def admin_delete_student(
    request: Request,
    student_id: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a student by deactivating their linked user account."""
    from db.models import Student

    student = (
        await db.execute(select(Student).where(Student.id == student_id))
    ).scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Student not found")

    if not student.user_id:
        raise HTTPException(404, "Student has no linked user account to deactivate")

    linked_user = (
        await db.execute(select(User).where(User.id == student.user_id))
    ).scalar_one_or_none()
    if not linked_user:
        raise HTTPException(404, "Linked user not found")

    linked_user.is_active = False
    await db.commit()
    logger.info("[admin] Student %s soft-deleted by admin %s", student_id, str(_user.id))
    return {"status": "deactivated"}


@limiter.limit("30/minute")
@router.post("/api/admin/students/{student_id}/reset-password")
async def admin_reset_student_password(
    request: Request,
    student_id: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send a password-reset OTP to the student's registered email."""
    from db.models import Student
    from auth.service import _generate_and_send_otp

    student = (
        await db.execute(select(Student).where(Student.id == student_id))
    ).scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Student not found")

    if not student.user_id:
        raise HTTPException(404, "Student has no linked user account")

    linked_user = (
        await db.execute(select(User).where(User.id == student.user_id))
    ).scalar_one_or_none()
    if not linked_user:
        raise HTTPException(404, "Linked user not found")

    await _generate_and_send_otp(db, linked_user, "password_reset")
    await db.commit()
    logger.info("[admin] Password reset OTP sent for student %s", student_id)
    return {"message": "Password reset email sent"}


# ── Manual Mastery ─────────────────────────────────────────────────────────────

@limiter.limit("30/minute")
@router.post("/api/admin/students/{student_id}/mastery/{concept_id:path}")
async def admin_grant_mastery(
    request: Request,
    student_id: str,
    concept_id: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually mark a concept as mastered for a student (upsert)."""
    from db.models import Student, StudentMastery

    student = (
        await db.execute(select(Student).where(Student.id == student_id))
    ).scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Student not found")

    existing = (
        await db.execute(
            select(StudentMastery).where(
                StudentMastery.student_id == student.id,
                StudentMastery.concept_id == concept_id,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.mastered_at = datetime.now(timezone.utc)
    else:
        db.add(StudentMastery(
            student_id=student.id,
            concept_id=concept_id,
            mastered_at=datetime.now(timezone.utc),
        ))

    await db.commit()
    logger.info("[admin] Mastery granted: student=%s concept=%s by admin=%s", student_id, concept_id, str(_user.id))
    return {"status": "mastered", "concept_id": concept_id}


@limiter.limit("30/minute")
@router.delete("/api/admin/students/{student_id}/mastery/{concept_id:path}")
async def admin_revoke_mastery(
    request: Request,
    student_id: str,
    concept_id: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Remove a mastery record for a student."""
    from db.models import Student, StudentMastery
    from sqlalchemy import delete as sa_delete

    student = (
        await db.execute(select(Student).where(Student.id == student_id))
    ).scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Student not found")

    await db.execute(
        sa_delete(StudentMastery).where(
            StudentMastery.student_id == student.id,
            StudentMastery.concept_id == concept_id,
        )
    )
    await db.commit()
    logger.info("[admin] Mastery revoked: student=%s concept=%s by admin=%s", student_id, concept_id, str(_user.id))
    return {"status": "unmastered", "concept_id": concept_id}


# ── Sessions ───────────────────────────────────────────────────────────────────

@limiter.limit("30/minute")
@router.get("/api/admin/sessions")
async def admin_list_sessions(
    request: Request,
    phase: str = None,
    book_slug: str = None,
    limit: int = 50,
    offset: int = 0,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List teaching sessions with optional filters, joined with student name."""
    from db.models import Student, TeachingSession

    limit = min(limit, 200)
    offset = min(offset, 10_000)

    base_q = (
        select(TeachingSession, Student.display_name)
        .join(Student, Student.id == TeachingSession.student_id)
    )
    if phase:
        base_q = base_q.where(TeachingSession.phase == phase)
    if book_slug:
        base_q = base_q.where(TeachingSession.book_slug == book_slug)

    total = (
        await db.execute(
            select(func.count()).select_from(base_q.subquery())
        )
    ).scalar() or 0

    rows = (
        await db.execute(
            base_q.order_by(TeachingSession.started_at.desc()).offset(offset).limit(limit)
        )
    ).all()

    items = [
        {
            "id": str(s.id),
            "student_id": str(s.student_id),
            "student_name": display_name,
            "concept_id": s.concept_id,
            "book_slug": s.book_slug,
            "phase": s.phase,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "completed_at": s.completed_at.isoformat() if s.completed_at else None,
            "check_score": s.check_score,
            "concept_mastered": s.concept_mastered,
        }
        for s, display_name in rows
    ]

    return {"total": total, "items": items}


# ── Analytics ──────────────────────────────────────────────────────────────────

@limiter.limit("30/minute")
@router.get("/api/admin/analytics")
async def admin_analytics(
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return platform-wide learning analytics."""
    from db.models import Student, TeachingSession, StudentMastery, CardInteraction

    # Top 20 hardest concepts by average wrong attempts
    difficulty_rows = (
        await db.execute(
            select(
                CardInteraction.concept_id,
                func.avg(CardInteraction.wrong_attempts).label("avg_wrong"),
                func.count(CardInteraction.id).label("attempt_count"),
            )
            .group_by(CardInteraction.concept_id)
            .order_by(func.avg(CardInteraction.wrong_attempts).desc())
            .limit(20)
        )
    ).all()
    concept_difficulty = [
        {
            "concept_id": r.concept_id,
            "avg_wrong_attempts": round(float(r.avg_wrong), 3),
            "attempt_count": r.attempt_count,
        }
        for r in difficulty_rows
    ]

    # Top 20 concepts by mastery rate (mastered / students who attempted)
    mastered_counts = (
        await db.execute(
            select(
                StudentMastery.concept_id,
                func.count(StudentMastery.id).label("mastered_count"),
            )
            .group_by(StudentMastery.concept_id)
        )
    ).all()
    mastered_map = {r.concept_id: r.mastered_count for r in mastered_counts}

    attempted_counts = (
        await db.execute(
            select(
                TeachingSession.concept_id,
                func.count(func.distinct(TeachingSession.student_id)).label("attempted_count"),
            )
            .group_by(TeachingSession.concept_id)
        )
    ).all()
    attempted_map = {r.concept_id: r.attempted_count for r in attempted_counts}

    concept_ids = set(mastered_map) | set(attempted_map)
    mastery_rates_raw = []
    for cid in concept_ids:
        mc = mastered_map.get(cid, 0)
        ac = attempted_map.get(cid, 0)
        rate = mc / ac if ac > 0 else 0.0
        mastery_rates_raw.append({
            "concept_id": cid,
            "mastered_count": mc,
            "attempted_count": ac,
            "rate": round(rate, 4),
        })
    mastery_rates = sorted(mastery_rates_raw, key=lambda x: x["rate"], reverse=True)[:20]

    # Student mode distribution based on avg_state_score
    # avg_state_score scale: 0–1 = STRUGGLING, 1–3 = NORMAL, 3+ = FAST
    struggling_count = (
        await db.execute(
            select(func.count()).select_from(Student)
            .where(Student.avg_state_score < 1.0)
        )
    ).scalar() or 0

    normal_count = (
        await db.execute(
            select(func.count()).select_from(Student)
            .where(Student.avg_state_score >= 1.0, Student.avg_state_score < 3.0)
        )
    ).scalar() or 0

    fast_count = (
        await db.execute(
            select(func.count()).select_from(Student)
            .where(Student.avg_state_score >= 3.0)
        )
    ).scalar() or 0

    return {
        "concept_difficulty": concept_difficulty,
        "mastery_rates": mastery_rates,
        "student_distribution": {
            "struggling": struggling_count,
            "normal": normal_count,
            "fast": fast_count,
        },
    }


# ── Admin Users ────────────────────────────────────────────────────────────────

@limiter.limit("5/minute")
@router.post("/api/admin/users/create-admin")
async def admin_create_admin_user(
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new admin user account (no Student record created)."""
    from auth.service import pwd_context, validate_password

    body = await request.json()
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    display_name = body.get("display_name", "").strip()

    if not email:
        raise HTTPException(400, "email is required")
    if not password:
        raise HTTPException(400, "password is required")
    if not display_name:
        raise HTTPException(400, "display_name is required")

    try:
        validate_password(password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "Email already registered")

    new_admin = User(
        email=email,
        password_hash=pwd_context.hash(password),
        role="admin",
        email_verified=True,
        is_active=True,
    )
    db.add(new_admin)
    await db.commit()
    await db.refresh(new_admin)
    logger.info("[admin] Admin user created: %s by admin %s", email, str(_user.id))
    return {
        "id": str(new_admin.id),
        "email": new_admin.email,
        "role": new_admin.role,
        "is_active": new_admin.is_active,
        "email_verified": new_admin.email_verified,
        "created_at": new_admin.created_at.isoformat() if new_admin.created_at else None,
    }


@limiter.limit("30/minute")
@router.patch("/api/admin/users/{user_id}/role")
async def admin_set_user_role(
    user_id: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Promote or demote a user's role between admin and student."""
    from db.models import Student

    body = await request.json()
    new_role = body.get("role", "")
    if new_role not in ("admin", "student"):
        raise HTTPException(400, "role must be 'admin' or 'student'")

    target_user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not target_user:
        raise HTTPException(404, "User not found")

    target_user.role = new_role

    # If demoting to student and no Student record exists, create a minimal one
    if new_role == "student":
        existing_student = (
            await db.execute(select(Student).where(Student.user_id == target_user.id))
        ).scalar_one_or_none()
        if not existing_student:
            email_prefix = target_user.email.split("@")[0]
            db.add(Student(
                display_name=email_prefix,
                user_id=target_user.id,
            ))

    await db.commit()
    await db.refresh(target_user)
    logger.info(
        "[admin] User %s role changed to %s by admin %s",
        user_id, new_role, str(_user.id),
    )
    return {"role": target_user.role}


@limiter.limit("30/minute")
@router.get("/api/admin/users")
async def admin_list_users(
    request: Request,
    role: str = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List users with pagination, optionally filtered by role."""
    base = select(User)
    if role:
        base = base.where(User.role == role)

    # Total count
    from sqlalchemy import func as _fn
    total = (await db.execute(base.with_only_columns(_fn.count(User.id)))).scalar() or 0

    # Paginated results
    q = base.order_by(User.created_at.desc()).limit(limit).offset(offset)
    users = (await db.execute(q)).scalars().all()

    return {
        "users": [
            {
                "id": str(u.id),
                "email": u.email,
                "role": u.role,
                "is_active": u.is_active,
                "email_verified": u.email_verified,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
        "total": total,
    }


# ── Config ─────────────────────────────────────────────────────────────────────

@limiter.limit("30/minute")
@router.get("/api/admin/config")
async def admin_get_config(
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all admin config key/value pairs as a dict."""
    from db.models import AdminConfig

    rows = (await db.execute(select(AdminConfig))).scalars().all()
    return {r.key: r.value for r in rows}


@limiter.limit("30/minute")
@router.patch("/api/admin/config")
async def admin_update_config(
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Upsert admin config key/value pairs."""
    from db.models import AdminConfig

    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Request body must be a JSON object of {key: value} pairs")

    now = datetime.now(timezone.utc)
    for key, value in body.items():
        key = str(key).strip()
        if not key:
            continue
        value_str = str(value)
        existing = (
            await db.execute(select(AdminConfig).where(AdminConfig.key == key))
        ).scalar_one_or_none()
        if existing:
            existing.value = value_str
            existing.updated_by = _user.id
            existing.updated_at = now
        else:
            db.add(AdminConfig(
                key=key,
                value=value_str,
                updated_by=_user.id,
                updated_at=now,
            ))

    await db.commit()
    logger.info("[admin] Config updated by admin %s: keys=%s", str(_user.id), list(body.keys()))

    # Return the full updated config
    rows = (await db.execute(select(AdminConfig))).scalars().all()
    return {r.key: r.value for r in rows}


# ── Chunk Edit ──────────────────────────────────────────────────────────────────

@limiter.limit("30/minute")
@router.patch("/api/admin/chunks/{chunk_id}")
async def update_chunk(
    chunk_id: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update editable fields on a single chunk."""
    try:
        chunk_uuid = UUID(chunk_id)
    except ValueError:
        raise HTTPException(400, "Invalid chunk ID format")
    chunk = (
        await db.execute(select(ConceptChunk).where(ConceptChunk.id == chunk_uuid))
    ).scalar_one_or_none()
    if not chunk:
        raise HTTPException(404, "Chunk not found")

    # Capture pre-mutation snapshot for audit
    old_snapshot = await audit_service.snapshot_chunk(db, chunk_uuid)
    book_slug_for_audit = chunk.book_slug
    old_heading = chunk.heading

    body = await request.json()
    if "chunk_type" in body and body["chunk_type"] not in ("teaching", "exercise"):
        raise HTTPException(
            status_code=400,
            detail="chunk_type must be 'teaching' or 'exercise'",
        )
    _allowed = {"heading", "text", "chunk_type", "is_optional", "is_hidden", "exam_disabled", "chunk_type_locked"}
    for field in _allowed:
        if field not in body:
            continue
        val = body[field]
        if field in ("is_optional", "is_hidden", "exam_disabled", "chunk_type_locked"):
            val = bool(val)
        setattr(chunk, field, val)

    await db.flush()
    new_snapshot = await audit_service.snapshot_chunk(db, chunk_uuid)

    # ── Auto-translate updated heading into all 12 non-English locales ─────
    new_heading = chunk.heading
    if "heading" in body and new_heading and new_heading != old_heading:
        try:
            from api.translation_helper import translate_one_string
            async with asyncio.timeout(10.0):
                translations = await translate_one_string(str(new_heading))
            if translations:
                await db.execute(
                    text("UPDATE concept_chunks SET heading_translations = :t WHERE id = :id"),
                    {"t": json.dumps(translations), "id": chunk_uuid},
                )
                logger.info(
                    "[admin] heading_translations populated for chunk=%s (%d langs)",
                    chunk_id, max(len(translations) - 1, 0),
                )
        except Exception:
            logger.warning(
                "[admin] heading translation failed for chunk %s — English-only until re-trigger",
                chunk_id,
            )
    # ── End translation block ────────────────────────────────────────────────

    try:
        await audit_service.log_action(
            db,
            admin_id=_user.id,
            action_type="update_chunk",
            resource_type="chunk",
            resource_id=str(chunk_uuid),
            book_slug=book_slug_for_audit,
            old_value=old_snapshot,
            new_value=new_snapshot,
        )
    except Exception:
        logger.warning(
            "[admin] Audit log failed for update_chunk %s — proceeding", chunk_id
        )

    try:
        await invalidate_chunk_cache(db, [str(chunk_uuid)])
    except Exception:
        logger.warning("[admin-invalidate] action=update_chunk chunks=[%s] — invalidation failed", chunk_id)
    await db.commit()
    await db.refresh(chunk)
    logger.info("[admin] Chunk %s updated by admin %s (audit_logged)", chunk_id, str(_user.id))
    logger.info("[admin-invalidate] action=update_chunk chunks=[%s]", chunk_id)
    return {
        "id": str(chunk.id),
        "heading": chunk.heading,
        "text": chunk.text,
        "chunk_type": chunk.chunk_type,
        "is_optional": chunk.is_optional,
        "is_hidden": chunk.is_hidden,
        "exam_disabled": chunk.exam_disabled,
        "order_index": chunk.order_index,
        "concept_id": chunk.concept_id,
        "book_slug": chunk.book_slug,
    }


@limiter.limit("30/minute")
@router.patch("/api/admin/chunks/{chunk_id}/visibility")
async def toggle_chunk_visibility(
    request: Request,
    chunk_id: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Toggle is_hidden on a chunk."""
    try:
        chunk_uuid = UUID(chunk_id)
    except ValueError:
        raise HTTPException(400, "Invalid chunk ID format")
    chunk = (
        await db.execute(select(ConceptChunk).where(ConceptChunk.id == chunk_uuid))
    ).scalar_one_or_none()
    if not chunk:
        raise HTTPException(404, "Chunk not found")

    old_is_hidden = chunk.is_hidden
    book_slug_for_audit = chunk.book_slug

    chunk.is_hidden = not chunk.is_hidden
    await db.flush()

    try:
        await audit_service.log_action(
            db,
            admin_id=_user.id,
            action_type="toggle_chunk_visibility",
            resource_type="chunk",
            resource_id=str(chunk_uuid),
            book_slug=book_slug_for_audit,
            old_value={"is_hidden": old_is_hidden},
            new_value={"is_hidden": chunk.is_hidden},
        )
    except Exception:
        logger.warning(
            "[admin] Audit log failed for toggle_chunk_visibility %s — proceeding", chunk_id
        )

    try:
        await invalidate_chunk_cache(db, [str(chunk_uuid)])
    except Exception:
        logger.warning("[admin-invalidate] action=toggle_chunk_visibility chunks=[%s] — invalidation failed", chunk_id)
    await db.commit()
    await db.refresh(chunk)
    logger.info("[admin] Chunk %s is_hidden=%s toggled by admin %s (audit_logged)", chunk_id, chunk.is_hidden, str(_user.id))
    logger.info("[admin-invalidate] action=toggle_chunk_visibility chunks=[%s]", chunk_id)
    return {"id": chunk_id, "is_hidden": chunk.is_hidden}


@limiter.limit("30/minute")
@router.patch("/api/admin/chunks/{chunk_id}/exam-gate")
async def toggle_chunk_exam_gate(
    request: Request,
    chunk_id: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Toggle exam_disabled on a chunk."""
    try:
        chunk_uuid = UUID(chunk_id)
    except ValueError:
        raise HTTPException(400, "Invalid chunk ID format")
    chunk = (
        await db.execute(select(ConceptChunk).where(ConceptChunk.id == chunk_uuid))
    ).scalar_one_or_none()
    if not chunk:
        raise HTTPException(404, "Chunk not found")

    old_exam_disabled = chunk.exam_disabled
    book_slug_for_audit = chunk.book_slug

    chunk.exam_disabled = not chunk.exam_disabled
    await db.flush()

    try:
        await audit_service.log_action(
            db,
            admin_id=_user.id,
            action_type="toggle_chunk_exam_gate",
            resource_type="chunk",
            resource_id=str(chunk_uuid),
            book_slug=book_slug_for_audit,
            old_value={"exam_disabled": old_exam_disabled},
            new_value={"exam_disabled": chunk.exam_disabled},
        )
    except Exception:
        logger.warning(
            "[admin] Audit log failed for toggle_chunk_exam_gate %s — proceeding", chunk_id
        )

    try:
        await invalidate_chunk_cache(db, [str(chunk_uuid)])
    except Exception:
        logger.warning("[admin-invalidate] action=toggle_chunk_exam_gate chunks=[%s] — invalidation failed", chunk_id)
    await db.commit()
    await db.refresh(chunk)
    logger.info("[admin] Chunk %s exam_disabled=%s toggled by admin %s (audit_logged)", chunk_id, chunk.exam_disabled, str(_user.id))
    logger.info("[admin-invalidate] action=toggle_chunk_exam_gate chunks=[%s]", chunk_id)
    return {"id": chunk_id, "exam_disabled": chunk.exam_disabled}


# ── Merge / Split / Reorder ────────────────────────────────────────────────────

@limiter.limit("30/minute")
@router.post("/api/admin/chunks/merge")
async def merge_chunks(
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Merge two chunks within the same concept into one.

    The chunk with the lower order_index absorbs the other.
    Active (non-COMPLETED) sessions that reference the deleted chunk have their
    chunk_progress migrated to the surviving chunk.
    """
    body = await request.json()
    chunk_id_1 = body.get("chunk_id_1")
    chunk_id_2 = body.get("chunk_id_2")
    if not chunk_id_1 or not chunk_id_2:
        raise HTTPException(400, "chunk_id_1 and chunk_id_2 are required")

    try:
        chunk_uuid_1 = UUID(chunk_id_1)
    except ValueError:
        raise HTTPException(400, "Invalid chunk_id_1 format")
    try:
        chunk_uuid_2 = UUID(chunk_id_2)
    except ValueError:
        raise HTTPException(400, "Invalid chunk_id_2 format")

    chunk1 = (
        await db.execute(select(ConceptChunk).where(ConceptChunk.id == chunk_uuid_1))
    ).scalar_one_or_none()
    chunk2 = (
        await db.execute(select(ConceptChunk).where(ConceptChunk.id == chunk_uuid_2))
    ).scalar_one_or_none()

    if not chunk1:
        raise HTTPException(404, f"Chunk {chunk_id_1} not found")
    if not chunk2:
        raise HTTPException(404, f"Chunk {chunk_id_2} not found")

    if chunk1.concept_id != chunk2.concept_id:
        raise HTTPException(400, "Both chunks must belong to the same concept_id")

    # Ensure chunk1 is always the earlier one
    if chunk1.order_index > chunk2.order_index:
        chunk1, chunk2 = chunk2, chunk1

    surviving_id = str(chunk1.id)
    deleted_id = str(chunk2.id)
    concept_id_str = str(chunk1.concept_id)  # capture before commit expires ORM attrs
    book_slug_for_audit = chunk1.book_slug

    # Capture pre-mutation snapshots for audit
    chunk1_snapshot = await audit_service.snapshot_chunk(db, chunk1.id)
    chunk2_snapshot = await audit_service.snapshot_chunk(db, chunk2.id)
    affected_sessions_snap = await audit_service.snapshot_session_progress_for_chunks(
        db, [chunk1.id, chunk2.id]
    )

    # Concatenate text and merge headings
    new_heading = chunk1.heading + " / " + chunk2.heading
    new_text = chunk1.text + "\n\n" + chunk2.text
    chunk1.text = new_text
    chunk1.heading = new_heading
    chunk1.embedding = None  # stale — needs regeneration

    # Transfer images from chunk2 to chunk1
    await db.execute(
        text("UPDATE chunk_images SET chunk_id = :c1 WHERE chunk_id = :c2"),
        {"c1": chunk1.id, "c2": chunk2.id},
    )

    # Migrate active session chunk_progress: replace chunk2 key with chunk1 key
    active_sessions = (
        await db.execute(
            select(TeachingSession).where(
                TeachingSession.concept_id == chunk1.concept_id,
                TeachingSession.phase != "COMPLETED",
                TeachingSession.chunk_progress.isnot(None),
            )
        )
    ).scalars().all()

    affected_count = 0
    for session in active_sessions:
        progress = session.chunk_progress or {}
        if deleted_id not in progress:
            continue
        # Merge deleted chunk's entry into surviving chunk's entry
        deleted_entry = progress.pop(deleted_id)
        if surviving_id in progress:
            # Combine totals
            existing = progress[surviving_id]
            existing["total"] = existing.get("total", 0) + deleted_entry.get("total", 0)
            existing["correct"] = existing.get("correct", 0) + deleted_entry.get("correct", 0)
        else:
            progress[surviving_id] = deleted_entry
        session.chunk_progress = progress
        affected_count += 1

    # Delete chunk2
    await db.delete(chunk2)
    await db.flush()

    # ── Auto-translate the merged heading into all 12 non-English locales ───
    try:
        from api.translation_helper import translate_one_string
        async with asyncio.timeout(10.0):
            translations = await translate_one_string(str(new_heading))
        if translations:
            await db.execute(
                text("UPDATE concept_chunks SET heading_translations = :t WHERE id = :id"),
                {"t": json.dumps(translations), "id": chunk1.id},
            )
            logger.info(
                "[admin] heading_translations populated post-merge chunk=%s (%d langs)",
                surviving_id, max(len(translations) - 1, 0),
            )
    except Exception:
        logger.warning(
            "[admin] heading translation failed post-merge for chunk %s — English-only",
            surviving_id,
        )
    # ── End translation block ────────────────────────────────────────────────

    # Re-index remaining chunks for this concept so order_index is sequential
    remaining = (
        await db.execute(
            select(ConceptChunk)
            .where(
                ConceptChunk.concept_id == chunk1.concept_id,
                ConceptChunk.book_slug == chunk1.book_slug,
            )
            .order_by(ConceptChunk.order_index)
        )
    ).scalars().all()
    for idx, ch in enumerate(remaining):
        ch.order_index = idx

    try:
        await audit_service.log_action(
            db,
            admin_id=_user.id,
            action_type="merge_chunks",
            resource_type="chunk",
            resource_id=surviving_id,
            book_slug=book_slug_for_audit,
            old_value={
                "chunk1": chunk1_snapshot,
                "chunk2": chunk2_snapshot,
                "affected_sessions": affected_sessions_snap,
            },
            new_value={
                "surviving_chunk_id": surviving_id,
                "deleted_chunk_id": deleted_id,
                "new_heading": new_heading,
                "new_text": new_text,
            },
            affected_count=affected_count,
        )
    except Exception:
        logger.warning("[admin] Audit log failed for merge_chunks — proceeding")

    try:
        await invalidate_chunk_cache(db, [surviving_id, deleted_id])
    except Exception:
        logger.warning("[admin-invalidate] action=merge_chunks chunks=[%s,%s] — invalidation failed", surviving_id, deleted_id)
    await db.commit()
    logger.info(
        "[admin] Merged chunk %s into %s (concept=%s) by admin %s; %d sessions affected (audit_logged)",
        deleted_id, surviving_id, concept_id_str, str(_user.id), affected_count,
    )
    logger.info("[admin-invalidate] action=merge_chunks chunks=[%s,%s]", surviving_id, deleted_id)
    return {
        "merged_chunk_id": surviving_id,
        "embedding_stale": True,
        "active_sessions_affected": affected_count,
    }


@limiter.limit("30/minute")
@router.post("/api/admin/chunks/{chunk_id}/split")
async def split_chunk(
    chunk_id: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Split a chunk into two at or near split_at_position.

    Searches for the nearest paragraph break (\\n\\n) within 200 characters of
    the requested position. Falls back to splitting at the exact position if no
    paragraph break is found nearby.
    """
    try:
        chunk_uuid = UUID(chunk_id)
    except ValueError:
        raise HTTPException(400, "Invalid chunk ID format")

    body = await request.json()
    split_at = body.get("split_at_position")
    if split_at is None:
        raise HTTPException(400, "split_at_position is required")
    split_at = int(split_at)

    chunk = (
        await db.execute(select(ConceptChunk).where(ConceptChunk.id == chunk_uuid))
    ).scalar_one_or_none()
    if not chunk:
        raise HTTPException(404, "Chunk not found")

    text_len = len(chunk.text)
    if split_at <= 0 or split_at >= text_len:
        raise HTTPException(400, f"split_at_position must be between 1 and {text_len - 1}")

    # Find nearest paragraph break within ±200 chars
    search_start = max(0, split_at - 200)
    search_end = min(text_len, split_at + 200)
    search_region = chunk.text[search_start:search_end]

    # Look for \n\n closest to split_at inside the search region
    relative_split = split_at - search_start
    best_pos = None
    best_dist = 999999
    offset_in_region = 0
    while True:
        idx = search_region.find("\n\n", offset_in_region)
        if idx == -1:
            break
        dist = abs(idx - relative_split)
        if dist < best_dist:
            best_dist = dist
            best_pos = search_start + idx + 2  # position after the \n\n separator
        offset_in_region = idx + 1

    split_pos = best_pos if best_pos is not None else split_at

    first_half = chunk.text[:split_pos]
    second_half = chunk.text[split_pos:].lstrip("\n")

    original_order = chunk.order_index
    original_concept = chunk.concept_id
    original_book = chunk.book_slug

    # Capture pre-mutation state for audit
    original_chunk_snapshot = await audit_service.snapshot_chunk(db, chunk_uuid)
    affected_sessions_snap = await audit_service.snapshot_session_progress_for_chunks(
        db, [chunk_uuid]
    )
    # Capture chunks that will be shifted (order_index > original_order)
    chunks_to_shift = (
        await db.execute(
            select(ConceptChunk).where(
                ConceptChunk.concept_id == original_concept,
                ConceptChunk.book_slug == original_book,
                ConceptChunk.order_index > original_order,
            )
        )
    ).scalars().all()
    pre_shift_order = [
        {"id": str(c.id), "old_order": c.order_index, "new_order": c.order_index + 1}
        for c in chunks_to_shift
    ]

    # Update original chunk
    chunk.text = first_half
    chunk.embedding = None

    # Shift all subsequent chunks in the same concept up by 1
    await db.execute(
        text(
            "UPDATE concept_chunks SET order_index = order_index + 1 "
            "WHERE concept_id = :cid AND book_slug = :slug AND order_index > :oi"
        ),
        {"cid": original_concept, "slug": original_book, "oi": original_order},
    )

    # Create the new second chunk
    new_chunk = ConceptChunk(
        book_slug=original_book,
        concept_id=original_concept,
        section=chunk.section,
        order_index=original_order + 1,
        heading=chunk.heading + " (cont.)",
        text=second_half,
        chunk_type=chunk.chunk_type,
        is_optional=chunk.is_optional,
        exam_disabled=chunk.exam_disabled,
        is_hidden=chunk.is_hidden,
        embedding=None,
    )
    db.add(new_chunk)
    await db.flush()  # assign new_chunk.id before session migration

    new_chunk_id = str(new_chunk.id)
    original_chunk_id = str(chunk.id)

    # ── Auto-translate the new "(cont.)" heading into all 12 non-English locales ──
    try:
        from api.translation_helper import translate_one_string
        async with asyncio.timeout(10.0):
            translations = await translate_one_string(str(new_chunk.heading))
        if translations:
            await db.execute(
                text("UPDATE concept_chunks SET heading_translations = :t WHERE id = :id"),
                {"t": json.dumps(translations), "id": new_chunk.id},
            )
            logger.info(
                "[admin] heading_translations populated post-split chunk=%s (%d langs)",
                new_chunk_id, max(len(translations) - 1, 0),
            )
    except Exception:
        logger.warning(
            "[admin] heading translation failed post-split for chunk %s — English-only",
            new_chunk_id,
        )
    # ── End translation block ────────────────────────────────────────────────

    # Migrate active session chunk_progress: copy original chunk entry to new chunk
    active_sessions = (
        await db.execute(
            select(TeachingSession).where(
                TeachingSession.concept_id == original_concept,
                TeachingSession.phase != "COMPLETED",
                TeachingSession.chunk_progress.isnot(None),
            )
        )
    ).scalars().all()

    affected_count = 0
    for session in active_sessions:
        progress = session.chunk_progress or {}
        if original_chunk_id not in progress:
            continue
        # Copy the original chunk's progress entry to the new chunk too
        if new_chunk_id not in progress:
            progress[new_chunk_id] = dict(progress[original_chunk_id])
        session.chunk_progress = progress
        affected_count += 1

    try:
        await audit_service.log_action(
            db,
            admin_id=_user.id,
            action_type="split_chunk",
            resource_type="chunk",
            resource_id=original_chunk_id,
            book_slug=original_book,
            old_value={
                "original_chunk": original_chunk_snapshot,
                "split_position": split_pos,
                "affected_sessions": affected_sessions_snap,
            },
            new_value={
                "original_chunk_id": original_chunk_id,
                "created_chunk_id": new_chunk_id,
                "original_new_text": first_half,
                "new_chunk_text": second_half,
                "reorder_delta": pre_shift_order,
            },
            affected_count=affected_count,
        )
    except Exception:
        logger.warning("[admin] Audit log failed for split_chunk — proceeding")

    try:
        await invalidate_chunk_cache(db, [original_chunk_id, new_chunk_id])
    except Exception:
        logger.warning("[admin-invalidate] action=split_chunk chunks=[%s,%s] — invalidation failed", original_chunk_id, new_chunk_id)
    await db.commit()
    logger.info(
        "[admin] Split chunk %s → new chunk %s at pos %d (concept=%s) by admin %s; %d sessions affected (audit_logged)",
        original_chunk_id, new_chunk_id, split_pos, original_concept, str(_user.id), affected_count,
    )
    logger.info("[admin-invalidate] action=split_chunk chunks=[%s,%s]", original_chunk_id, new_chunk_id)
    return {
        "original_chunk_id": original_chunk_id,
        "new_chunk_id": new_chunk_id,
        "embedding_stale": True,
        "active_sessions_affected": affected_count,
    }


@limiter.limit("30/minute")
@router.put("/api/admin/concepts/{concept_id:path}/reorder")
async def reorder_chunks(
    concept_id: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set explicit ordering for all chunks in a concept.

    Body: {"book_slug": str, "chunk_ids": ["uuid1", "uuid2", ...]}
    All chunk_ids must belong to this concept_id.
    """
    body = await request.json()
    book_slug = body.get("book_slug")
    chunk_ids = body.get("chunk_ids", [])
    if not book_slug:
        raise HTTPException(400, "book_slug is required")
    if not chunk_ids:
        raise HTTPException(400, "chunk_ids is required and must not be empty")

    # Fetch all chunks for this concept and validate ownership
    existing_chunks = (
        await db.execute(
            select(ConceptChunk).where(
                ConceptChunk.concept_id == concept_id,
                ConceptChunk.book_slug == book_slug,
            )
        )
    ).scalars().all()
    existing_ids = {str(c.id) for c in existing_chunks}

    for cid in chunk_ids:
        if cid not in existing_ids:
            raise HTTPException(400, f"chunk {cid} does not belong to concept {concept_id}")

    chunk_map = {str(c.id): c for c in existing_chunks}

    # Capture old order for audit
    old_per_chunk = [
        {"id": str(c.id), "order_index": c.order_index} for c in existing_chunks
    ]

    for position, cid in enumerate(chunk_ids):
        chunk_map[cid].order_index = position

    await db.flush()

    # Capture new order for audit
    new_per_chunk = [
        {"id": cid, "order_index": pos} for pos, cid in enumerate(chunk_ids)
    ]

    try:
        await audit_service.log_action(
            db,
            admin_id=_user.id,
            action_type="reorder_chunks",
            resource_type="section",
            resource_id=concept_id,
            book_slug=book_slug,
            old_value={"per_chunk": old_per_chunk},
            new_value={"per_chunk": new_per_chunk},
            affected_count=len(chunk_ids),
        )
    except Exception:
        logger.warning("[admin] Audit log failed for reorder_chunks — proceeding")

    await db.commit()
    logger.info("[admin] Reordered %d chunks for concept %s by admin %s (audit_logged)", len(chunk_ids), concept_id, str(_user.id))
    return {"reordered": len(chunk_ids)}


# ── Embedding Regeneration ─────────────────────────────────────────────────────

@limiter.limit("30/minute")
@router.post("/api/admin/chunks/{chunk_id}/regenerate-embedding")
async def regenerate_chunk_embedding(
    request: Request,
    chunk_id: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate the pgvector embedding for a single chunk using OpenAI."""
    try:
        chunk_uuid = UUID(chunk_id)
    except ValueError:
        raise HTTPException(400, "Invalid chunk ID format")
    chunk = (
        await db.execute(select(ConceptChunk).where(ConceptChunk.id == chunk_uuid))
    ).scalar_one_or_none()
    if not chunk:
        raise HTTPException(404, "Chunk not found")

    client = openai.AsyncOpenAI()  # uses OPENAI_API_KEY from env
    response = await client.embeddings.create(
        input=chunk.text[:8000],
        model="text-embedding-3-small",
    )
    chunk.embedding = response.data[0].embedding
    await db.commit()
    logger.info("[admin] Regenerated embedding for chunk %s by admin %s", chunk_id, str(_user.id))
    return {"id": chunk_id, "embedding_regenerated": True}


@limiter.limit("30/minute")
@router.post("/api/admin/concepts/{concept_id:path}/regenerate-embeddings")
async def regenerate_concept_embeddings(
    concept_id: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate embeddings for all NULL-embedding chunks in a concept.

    Body: {"book_slug": str}
    Only processes chunks where embedding IS NULL (stale after edit/merge/split).
    """
    body = await request.json()
    book_slug = body.get("book_slug")
    if not book_slug:
        raise HTTPException(400, "book_slug is required")

    stale_chunks = (
        await db.execute(
            select(ConceptChunk).where(
                ConceptChunk.concept_id == concept_id,
                ConceptChunk.book_slug == book_slug,
                ConceptChunk.embedding.is_(None),
            )
        )
    ).scalars().all()

    if not stale_chunks:
        return {"regenerated": 0}

    client = openai.AsyncOpenAI()
    count = 0
    for chunk in stale_chunks:
        response = await client.embeddings.create(
            input=chunk.text[:8000],
            model="text-embedding-3-small",
        )
        chunk.embedding = response.data[0].embedding
        count += 1

    await db.commit()
    logger.info(
        "[admin] Regenerated %d embeddings for concept %s (book=%s) by admin %s",
        count, concept_id, book_slug, str(_user.id),
    )
    return {"regenerated": count}


# ── Section-Level Controls ─────────────────────────────────────────────────────

@limiter.limit("30/minute")
@router.patch("/api/admin/sections/{concept_id:path}/rename")
async def rename_section(
    concept_id: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set a custom display name for a concept section (stored in admin_section_name)."""
    body = await request.json()
    book_slug = body.get("book_slug")
    name = body.get("name")
    if not book_slug:
        raise HTTPException(400, "book_slug is required")
    if name is None:
        raise HTTPException(400, "name is required")

    # Capture pre-mutation state for audit
    section_snap = await audit_service.snapshot_section(db, concept_id, book_slug)
    old_name = section_snap[0]["admin_section_name"] if section_snap else None
    affected_chunk_ids = [entry["id"] for entry in section_snap]

    result = await db.execute(
        text(
            "UPDATE concept_chunks SET admin_section_name = :name "
            "WHERE concept_id = :cid AND book_slug = :slug"
        ),
        {"name": str(name), "cid": concept_id, "slug": book_slug},
    )
    chunks_updated = result.rowcount

    # ── Translate the new section name into all 12 non-English locales ──────
    translations: dict = {}
    try:
        from api.translation_helper import translate_one_string
        async with asyncio.timeout(10.0):
            translations = await translate_one_string(str(name))
        if translations:
            await db.execute(
                text(
                    "UPDATE concept_chunks "
                    "SET admin_section_name_translations = :t "
                    "WHERE concept_id = :cid AND book_slug = :slug"
                ),
                {"t": json.dumps(translations), "cid": concept_id, "slug": book_slug},
            )
            logger.info(
                "[admin] admin_section_name_translations populated for concept=%s (%d langs)",
                concept_id, len(translations) - 1,  # minus en_source_hash
            )
    except Exception:
        logger.warning(
            "[admin] admin_section_name translation failed — English name will be shown "
            "until a manual re-trigger. concept=%s",
            concept_id,
        )
    # ── End translation block ────────────────────────────────────────────────

    try:
        await audit_service.log_action(
            db,
            admin_id=_user.id,
            action_type="rename_section",
            resource_type="section",
            resource_id=concept_id,
            book_slug=book_slug,
            old_value={
                "admin_section_name": old_name,
                "admin_section_name_translations": section_snap[0].get(
                    "admin_section_name_translations", {}
                ) if section_snap else {},
                "affected_chunk_ids": affected_chunk_ids,
            },
            new_value={
                "admin_section_name": str(name),
                "admin_section_name_translations": translations,
            },
            affected_count=chunks_updated,
        )
    except Exception:
        logger.warning("[admin] Audit log failed for rename_section — proceeding")

    try:
        await invalidate_chunk_cache(db, affected_chunk_ids)
    except Exception:
        logger.warning("[admin-invalidate] action=rename_section concept=%s — invalidation failed", concept_id)
    await db.commit()
    logger.info(
        "[admin] Renamed section concept=%s book=%s to '%s' by admin %s (%d chunks, audit_logged)",
        concept_id, book_slug, name, str(_user.id), chunks_updated,
    )
    logger.info("[admin-invalidate] action=rename_section concept=%s chunks=%d", concept_id, len(affected_chunk_ids))
    return {"concept_id": concept_id, "admin_section_name": name, "chunks_updated": chunks_updated}


@limiter.limit("30/minute")
@router.patch("/api/admin/sections/{concept_id:path}/optional")
async def toggle_section_optional(
    concept_id: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set is_optional on all chunks in a concept section."""
    body = await request.json()
    book_slug = body.get("book_slug")
    is_optional = body.get("is_optional")
    if not book_slug:
        raise HTTPException(400, "book_slug is required")
    if is_optional is None:
        raise HTTPException(400, "is_optional is required")

    # Capture per-chunk old state for audit
    section_snap = await audit_service.snapshot_section(db, concept_id, book_slug)
    old_per_chunk = [
        {"id": entry["id"], "is_optional": entry["is_optional"]}
        for entry in section_snap
    ]

    result = await db.execute(
        text(
            "UPDATE concept_chunks SET is_optional = :val "
            "WHERE concept_id = :cid AND book_slug = :slug"
        ),
        {"val": bool(is_optional), "cid": concept_id, "slug": book_slug},
    )
    chunks_updated = result.rowcount

    try:
        await audit_service.log_action(
            db,
            admin_id=_user.id,
            action_type="toggle_section_optional",
            resource_type="section",
            resource_id=concept_id,
            book_slug=book_slug,
            old_value={"per_chunk": old_per_chunk},
            new_value={"is_optional": bool(is_optional)},
            affected_count=chunks_updated,
        )
    except Exception:
        logger.warning("[admin] Audit log failed for toggle_section_optional — proceeding")

    _section_chunk_ids = [entry["id"] for entry in section_snap]
    try:
        await invalidate_chunk_cache(db, _section_chunk_ids)
    except Exception:
        logger.warning("[admin-invalidate] action=toggle_section_optional concept=%s — invalidation failed", concept_id)
    await db.commit()
    logger.info(
        "[admin] Section concept=%s book=%s is_optional=%s set by admin %s (%d chunks, audit_logged)",
        concept_id, book_slug, is_optional, str(_user.id), chunks_updated,
    )
    logger.info("[admin-invalidate] action=toggle_section_optional concept=%s chunks=%d", concept_id, len(_section_chunk_ids))
    return {"concept_id": concept_id, "is_optional": bool(is_optional), "chunks_updated": chunks_updated}


@limiter.limit("30/minute")
@router.patch("/api/admin/sections/{concept_id:path}/exam-gate")
async def toggle_section_exam_gate(
    concept_id: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set exam_disabled on all chunks in a concept section."""
    body = await request.json()
    book_slug = body.get("book_slug")
    disabled = body.get("disabled")
    if not book_slug:
        raise HTTPException(400, "book_slug is required")
    if disabled is None:
        raise HTTPException(400, "disabled is required")

    # Capture per-chunk old state for audit
    section_snap = await audit_service.snapshot_section(db, concept_id, book_slug)
    old_per_chunk = [
        {"id": entry["id"], "exam_disabled": entry["exam_disabled"]}
        for entry in section_snap
    ]

    result = await db.execute(
        text(
            "UPDATE concept_chunks SET exam_disabled = :val "
            "WHERE concept_id = :cid AND book_slug = :slug"
        ),
        {"val": bool(disabled), "cid": concept_id, "slug": book_slug},
    )
    chunks_updated = result.rowcount

    try:
        await audit_service.log_action(
            db,
            admin_id=_user.id,
            action_type="toggle_section_exam_gate",
            resource_type="section",
            resource_id=concept_id,
            book_slug=book_slug,
            old_value={"per_chunk": old_per_chunk},
            new_value={"exam_disabled": bool(disabled)},
            affected_count=chunks_updated,
        )
    except Exception:
        logger.warning("[admin] Audit log failed for toggle_section_exam_gate — proceeding")

    _section_exam_chunk_ids = [entry["id"] for entry in section_snap]
    try:
        await invalidate_chunk_cache(db, _section_exam_chunk_ids)
    except Exception:
        logger.warning("[admin-invalidate] action=toggle_section_exam_gate concept=%s — invalidation failed", concept_id)
    await db.commit()
    logger.info(
        "[admin] Section concept=%s book=%s exam_disabled=%s set by admin %s (%d chunks, audit_logged)",
        concept_id, book_slug, disabled, str(_user.id), chunks_updated,
    )
    logger.info("[admin-invalidate] action=toggle_section_exam_gate concept=%s chunks=%d", concept_id, len(_section_exam_chunk_ids))
    return {"concept_id": concept_id, "exam_disabled": bool(disabled), "chunks_updated": chunks_updated}


@limiter.limit("30/minute")
@router.patch("/api/admin/sections/{concept_id:path}/visibility")
async def toggle_section_visibility(
    concept_id: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    book_slug = body.get("book_slug")
    is_hidden = body.get("is_hidden")
    if not book_slug:
        raise HTTPException(400, "book_slug is required")
    if is_hidden is None:
        raise HTTPException(400, "is_hidden is required")

    # Capture per-chunk old state for audit (is_hidden + chunk_type_locked both may change)
    section_snap = await audit_service.snapshot_section(db, concept_id, book_slug)
    old_per_chunk = [
        {"id": entry["id"], "is_hidden": entry["is_hidden"], "chunk_type_locked": entry["chunk_type_locked"]}
        for entry in section_snap
    ]

    result = await db.execute(
        text(
            "UPDATE concept_chunks SET is_hidden = :val, "
            "chunk_type_locked = CASE WHEN :val THEN true ELSE chunk_type_locked END "
            "WHERE concept_id = :cid AND book_slug = :slug"
        ),
        {"val": bool(is_hidden), "cid": concept_id, "slug": book_slug},
    )
    chunks_updated = result.rowcount
    if chunks_updated == 0:
        logger.warning(
            "[admin] Section visibility toggle matched 0 chunks: concept=%s book=%s is_hidden=%s admin=%s",
            concept_id, book_slug, is_hidden, str(_user.id),
        )

    try:
        await audit_service.log_action(
            db,
            admin_id=_user.id,
            action_type="toggle_section_visibility",
            resource_type="section",
            resource_id=concept_id,
            book_slug=book_slug,
            old_value={"per_chunk": old_per_chunk},
            new_value={"is_hidden": bool(is_hidden), "chunk_type_locked": bool(is_hidden)},
            affected_count=chunks_updated,
        )
    except Exception:
        logger.warning("[admin] Audit log failed for toggle_section_visibility — proceeding")

    _section_vis_chunk_ids = [entry["id"] for entry in section_snap]
    try:
        await invalidate_chunk_cache(db, _section_vis_chunk_ids)
    except Exception:
        logger.warning("[admin-invalidate] action=toggle_section_visibility concept=%s — invalidation failed", concept_id)
    await db.commit()
    logger.info(
        "[admin] Section concept=%s book=%s is_hidden=%s set by admin %s (%d chunks, audit_logged)",
        concept_id, book_slug, is_hidden, str(_user.id), chunks_updated,
    )
    logger.info("[admin-invalidate] action=toggle_section_visibility concept=%s chunks=%d", concept_id, len(_section_vis_chunk_ids))
    return {"updated": chunks_updated, "is_hidden": bool(is_hidden)}


@limiter.limit("30/minute")
@router.post("/api/admin/sections/{concept_id:path}/promote")
async def promote_subsection_to_section(
    concept_id: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Split a section at a chunk boundary, promoting a chunk (and all chunks after it)
    into a brand-new section node.

    The split inserts the new node immediately after the original section in the
    prerequisite graph, rewiring all downstream successors to the new node so the
    linear learning chain remains intact.

    Request body:
        book_slug (str):           Book the section belongs to.
        chunk_id (str):            UUID of the chunk that becomes the first chunk of
                                   the new section.  Must NOT be the first chunk of the
                                   current section (that would leave an empty section).
        new_section_label (str, optional): Display name for the new section.  Defaults
                                   to the heading of the promoted chunk.

    Returns:
        {
            "old_concept_id": str,
            "new_concept_id": str,
            "new_section_label": str,
            "chunks_moved": int,
        }
    """
    body = await request.json()
    book_slug = body.get("book_slug")
    chunk_id_raw = body.get("chunk_id")
    new_section_label: str | None = body.get("new_section_label") or None

    if not book_slug:
        raise HTTPException(400, "book_slug is required")
    if not chunk_id_raw:
        raise HTTPException(400, "chunk_id is required")

    try:
        chunk_uuid = UUID(str(chunk_id_raw))
    except ValueError:
        raise HTTPException(400, f"chunk_id is not a valid UUID: {chunk_id_raw!r}")

    # ── 1. Load all chunks for this concept in order ───────────────────────────
    result = await db.execute(
        select(ConceptChunk)
        .where(
            ConceptChunk.concept_id == concept_id,
            ConceptChunk.book_slug == book_slug,
        )
        .order_by(ConceptChunk.order_index)
    )
    chunks = result.scalars().all()

    if not chunks:
        raise HTTPException(
            404,
            f"No chunks found for concept_id='{concept_id}' book_slug='{book_slug}'",
        )

    # ── 2. Locate the target chunk ────────────────────────────────────────────
    target_chunk = next((c for c in chunks if c.id == chunk_uuid), None)
    if target_chunk is None:
        raise HTTPException(
            404,
            f"chunk_id '{chunk_uuid}' not found under concept_id='{concept_id}'",
        )

    # Guard: cannot promote the first chunk — would leave the original section empty
    first_chunk = chunks[0]
    if target_chunk.id == first_chunk.id:
        raise HTTPException(
            400,
            "Cannot promote the first chunk — that would create an empty original section.",
        )

    # ── 3. Determine the new concept_id ──────────────────────────────────────
    # Parse the numeric section suffix from the current concept_id.
    # Format: "{book_slug}_{chapter}.{section}"  e.g. "prealgebra_11.3"
    after_slug_part = concept_id[len(book_slug) + 1:] if concept_id.startswith(book_slug + "_") else concept_id.split("_", 1)[-1]  # e.g. "11.3"
    dot_pos = after_slug_part.rfind(".")
    if dot_pos == -1:
        raise HTTPException(
            422,
            f"Cannot parse section number from concept_id='{concept_id}'. "
            "Expected format: <book_slug>_<chapter>.<section>",
        )

    chapter_part = after_slug_part[:dot_pos]   # e.g. "11"
    section_part = after_slug_part[dot_pos + 1:]  # e.g. "3"
    slug_prefix = concept_id[: len(concept_id) - len(after_slug_part)]  # e.g. "prealgebra_"

    # Find next available section number: try incrementing the section digit.
    # If the section number is not purely numeric, fall back to a letter suffix.
    new_concept_id: str | None = None
    if section_part.isdigit():
        section_num = int(section_part)
        # Letter suffixes FIRST to keep adjacent ordering: 1.1 -> 1.1b
        candidates: list[str] = [
            f"{slug_prefix}{chapter_part}.{section_part}{letter}"
            for letter in "bcdefghij"
        ] + [
            f"{slug_prefix}{chapter_part}.{section_num + i}"
            for i in range(1, 10)
        ]
    else:
        # Section already has a letter suffix (e.g. "3b") — append further letters
        candidates = [
            f"{slug_prefix}{chapter_part}.{section_part}{letter}"
            for letter in "bcdefghij"
        ]

    for candidate in candidates:
        existing = await db.execute(
            select(ConceptChunk.id)
            .where(
                ConceptChunk.concept_id == candidate,
                ConceptChunk.book_slug == book_slug,
            )
            .limit(1)
        )
        if existing.scalar_one_or_none() is None:
            new_concept_id = candidate
            break

    if new_concept_id is None:
        raise HTTPException(
            409,
            f"Could not find an available concept_id for the new section after '{concept_id}'. "
            "All candidate IDs are already in use.",
        )

    # ── 4. Determine section label ────────────────────────────────────────────
    section_label = new_section_label or target_chunk.heading or new_concept_id

    # ── 5. Identify chunks to move (order_index >= target's order_index) ──────
    target_order = target_chunk.order_index
    chunks_to_move = [c for c in chunks if c.order_index >= target_order]
    chunks_to_keep = [c for c in chunks if c.order_index < target_order]

    # ── 5b. Capture pre-promote state for audit ───────────────────────────────
    affected_chunk_snapshots = [
        {
            "id": str(c.id),
            "concept_id": c.concept_id,
            "section": c.section,
            "is_hidden": c.is_hidden,
        }
        for c in chunks_to_move
    ]
    affected_chunk_ids = [str(c.id) for c in chunks_to_move]

    # Read graph.json before mutation so we can restore it on undo
    graph_path = OUTPUT_DIR / book_slug / "graph.json"
    graph_json_before: dict | None = None
    if graph_path.exists():
        try:
            import json as _json
            with open(graph_path, "r", encoding="utf-8") as _f:
                graph_json_before = _json.load(_f)
        except Exception:
            logger.warning(
                "[admin] promote_subsection: could not read graph.json for audit snapshot"
            )

    # ── 6. Persist the move in a single transaction ──────────────────────────
    # IMPORTANT: do NOT reset order_index. It is globally sequential across the
    # entire book and reflects MMD position. Admin listing orders sections by
    # min(order_index) per concept_id, so preserving the original values keeps
    # the promoted section in its correct MMD position within the chapter.
    for chunk in chunks_to_keep:
        chunk.concept_id = concept_id       # unchanged, but explicit for clarity

    for chunk in chunks_to_move:
        chunk.concept_id = new_concept_id
        chunk.section = section_label
        chunk.is_hidden = False

    await db.flush()

    # ── 7. Update graph.json on disk ─────────────────────────────────────────
    graph_json_after: dict | None = None
    if not graph_path.exists():
        # Graph file missing — log a warning but don't abort; chunks are already moved.
        logger.warning(
            "[admin] promote_subsection: graph.json not found at %s. "
            "Graph was NOT updated; run graph_builder manually.",
            graph_path,
        )
    else:
        try:
            insert_section_node(
                graph_path=graph_path,
                new_concept_id=new_concept_id,
                label=section_label,
                after_concept_id=concept_id,
            )
            # Reload in-process graph cache so subsequent requests see the change
            await reload_graph_with_overrides(book_slug, db)
            # Capture post-promote graph.json for redo
            try:
                import json as _json2
                with open(graph_path, "r", encoding="utf-8") as _f2:
                    graph_json_after = _json2.load(_f2)
            except Exception:
                pass
        except Exception as exc:
            # Chunks are already flushed — log the graph error but don't roll back.
            logger.error(
                "[admin] promote_subsection: graph update failed for book=%s "
                "old=%s new=%s: %s",
                book_slug, concept_id, new_concept_id, exc,
            )

    try:
        await audit_service.log_action(
            db,
            admin_id=_user.id,
            action_type="promote",
            resource_type="section",
            resource_id=concept_id,
            book_slug=book_slug,
            old_value={
                "old_concept_id": concept_id,
                "affected_chunks": affected_chunk_snapshots,
                "graph_json_before": graph_json_before,
            },
            new_value={
                "new_concept_id": new_concept_id,
                "new_section_label": section_label,
                "affected_chunk_ids": affected_chunk_ids,
                "graph_json_after": graph_json_after,
            },
            affected_count=len(chunks_to_move),
        )
    except Exception:
        logger.warning("[admin] Audit log failed for promote — proceeding")

    try:
        await invalidate_chunk_cache(db, affected_chunk_ids)
    except Exception:
        logger.warning("[admin-invalidate] action=promote concept=%s — invalidation failed", concept_id)
    await db.commit()

    logger.info(
        "[admin] Promoted subsection: book=%s old=%s new=%s label=%r "
        "chunks_moved=%d admin=%s (audit_logged)",
        book_slug, concept_id, new_concept_id, section_label,
        len(chunks_to_move), str(_user.id),
    )
    logger.info("[admin-invalidate] action=promote concept=%s chunks=%d", concept_id, len(affected_chunk_ids))

    return {
        "old_concept_id": concept_id,
        "new_concept_id": new_concept_id,
        "new_section_label": section_label,
        "chunks_moved": len(chunks_to_move),
    }


# ── Graph Edge Operations ──────────────────────────────────────────────────────

@limiter.limit("30/minute")
@router.get("/api/admin/graph/{book_slug}/edges")
async def list_graph_edges(
    request: Request,
    book_slug: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all edges in the (override-applied) graph for a book."""
    try:
        G = await reload_graph_with_overrides(book_slug, db)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return [{"source": src, "target": tgt} for src, tgt in G.edges()]


@limiter.limit("30/minute")
@router.get("/api/admin/graph/{book_slug}/overrides")
async def list_graph_overrides(
    request: Request,
    book_slug: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all admin graph overrides (add/remove edge records) for a book."""
    overrides = (
        await db.execute(
            select(AdminGraphOverride)
            .where(AdminGraphOverride.book_slug == book_slug)
            .order_by(AdminGraphOverride.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": str(ov.id),
            "action": ov.action,
            "source": ov.source_concept,
            "target": ov.target_concept,
            "created_at": ov.created_at.isoformat() if ov.created_at else None,
        }
        for ov in overrides
    ]


@limiter.limit("30/minute")
@router.post("/api/admin/graph/{book_slug}/edges")
async def modify_graph_edge(
    book_slug: str,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Add or remove a prerequisite edge in the dependency graph.

    Body: {"action": "add_edge" | "remove_edge", "source": str, "target": str}

    For add_edge, validates that the new edge would not create a cycle.
    Persists the override and refreshes the in-memory graph cache.
    """
    body = await request.json()
    action = body.get("action")
    source = body.get("source")
    target = body.get("target")

    if action not in ("add_edge", "remove_edge"):
        raise HTTPException(400, "action must be 'add_edge' or 'remove_edge'")
    if not source or not target:
        raise HTTPException(400, "source and target are required")

    if action == "add_edge":
        try:
            G = _load_graph(book_slug)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        # Check if adding source→target would create a cycle
        # (i.e., there is already a path from target back to source)
        if G.has_node(source) and G.has_node(target) and nx.has_path(G, target, source):
            raise HTTPException(400, "Would create a cycle in the prerequisite graph")

    # Collect chunk IDs for both source and target concepts so we can invalidate
    # active sessions whose card cache references either concept's chunks.
    _graph_chunk_rows = (
        await db.execute(
            select(ConceptChunk.id).where(
                ConceptChunk.book_slug == book_slug,
                ConceptChunk.concept_id.in_([source, target]),
            )
        )
    ).scalars().all()
    _graph_chunk_ids = [str(r) for r in _graph_chunk_rows]

    override = AdminGraphOverride(
        book_slug=book_slug,
        action=action,
        source_concept=source,
        target_concept=target,
        created_by=_user.id,
    )
    db.add(override)
    try:
        await invalidate_chunk_cache(db, _graph_chunk_ids)
    except Exception:
        logger.warning(
            "[admin-invalidate] action=modify_graph_edge %s→%s — invalidation failed", source, target
        )
    await db.commit()

    # Refresh in-memory graph cache with the new override applied
    await reload_graph_with_overrides(book_slug, db)

    logger.info(
        "[admin] Graph override %s %s→%s (book=%s) by admin %s",
        action, source, target, book_slug, str(_user.id),
    )
    logger.info("[admin-invalidate] action=modify_graph_edge %s→%s chunks=%d", source, target, len(_graph_chunk_ids))
    return {"action": action, "source": source, "target": target}


@limiter.limit("30/minute")
@router.delete("/api/admin/graph/{book_slug}/overrides/{override_id}")
async def delete_graph_override(
    request: Request,
    book_slug: str,
    override_id: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete an admin graph override and refresh the graph cache."""
    from sqlalchemy import delete as sa_delete

    result = await db.execute(
        sa_delete(AdminGraphOverride).where(
            AdminGraphOverride.id == override_id,
            AdminGraphOverride.book_slug == book_slug,
        ).returning(AdminGraphOverride.id)
    )
    deleted_row = result.fetchone()
    if not deleted_row:
        raise HTTPException(404, "Override not found")

    await db.commit()

    # Refresh in-memory graph cache without this override
    await reload_graph_with_overrides(book_slug, db)

    logger.info(
        "[admin] Graph override %s deleted (book=%s) by admin %s",
        override_id, book_slug, str(_user.id),
    )
    return {"deleted": True}


# ═══════════════════════════════════════════════════════════════════
# GAMIFICATION — ADMIN PROGRESS REPORT
# ═══════════════════════════════════════════════════════════════════

@limiter.limit("30/minute")
@router.get("/api/admin/students/{student_id}/progress-report")
async def get_progress_report(
    request: Request,
    student_id: UUID,
    period: str = "week",
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get XP progress report for a student over a configurable time period.

    period: 'day' | 'week' | 'month' | 'all'
    Returns XP totals, daily breakdown, accuracy, mastery count, and badges
    earned within the period.
    """
    from datetime import timedelta
    from sqlalchemy import func as sa_func, cast, Date as SADate
    from db.models import Student, StudentMastery, CardInteraction, XpEvent, StudentBadge

    if period not in ("day", "week", "month", "all"):
        raise HTTPException(400, "period must be one of: day, week, month, all")

    now = datetime.now(timezone.utc)
    if period == "day":
        start = now - timedelta(days=1)
    elif period == "week":
        start = now - timedelta(weeks=1)
    elif period == "month":
        start = now - timedelta(days=30)
    else:
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)

    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(404, "Student not found")

    # Total XP earned in period
    xp_total_result = await db.execute(
        select(sa_func.coalesce(sa_func.sum(XpEvent.final_xp), 0))
        .where(XpEvent.student_id == student_id)
        .where(XpEvent.created_at >= start)
    )
    total_xp = xp_total_result.scalar() or 0

    # Daily XP breakdown — grouped by UTC date
    daily_xp_result = await db.execute(
        select(
            cast(XpEvent.created_at, SADate).label("date"),
            sa_func.sum(XpEvent.final_xp).label("xp"),
        )
        .where(XpEvent.student_id == student_id)
        .where(XpEvent.created_at >= start)
        .group_by(cast(XpEvent.created_at, SADate))
        .order_by(cast(XpEvent.created_at, SADate))
    )
    daily_xp = [{"date": str(r.date), "xp": int(r.xp)} for r in daily_xp_result.all()]

    # XP by event type
    type_result = await db.execute(
        select(XpEvent.event_type, sa_func.sum(XpEvent.final_xp))
        .where(XpEvent.student_id == student_id)
        .where(XpEvent.created_at >= start)
        .group_by(XpEvent.event_type)
    )
    xp_by_type = {event_type: int(xp) for event_type, xp in type_result.all()}

    # Concepts mastered in period
    mastery_result = await db.execute(
        select(sa_func.count(StudentMastery.id))
        .where(StudentMastery.student_id == student_id)
        .where(StudentMastery.mastered_at >= start)
    )
    concepts_mastered = mastery_result.scalar() or 0

    # Accuracy in period (wrong_attempts == 0 → first-attempt correct)
    correct_result = await db.execute(
        select(sa_func.count(CardInteraction.id))
        .where(CardInteraction.student_id == student_id)
        .where(CardInteraction.completed_at >= start)
        .where(CardInteraction.wrong_attempts == 0)
    )
    total_interactions_result = await db.execute(
        select(sa_func.count(CardInteraction.id))
        .where(CardInteraction.student_id == student_id)
        .where(CardInteraction.completed_at >= start)
    )
    correct_count = correct_result.scalar() or 0
    total_int = total_interactions_result.scalar() or 0
    accuracy = round(correct_count / total_int, 2) if total_int > 0 else 0.0

    # Badges earned in period
    badges_result = await db.execute(
        select(StudentBadge)
        .where(StudentBadge.student_id == student_id)
        .where(StudentBadge.awarded_at >= start)
        .order_by(StudentBadge.awarded_at)
    )
    badges_earned = [
        {"badge_key": b.badge_key, "awarded_at": b.awarded_at.isoformat()}
        for b in badges_result.scalars().all()
    ]

    logger.info(
        "[admin] progress-report student_id=%s period=%s total_xp=%d mastered=%d",
        student_id, period, total_xp, concepts_mastered,
    )

    return {
        "student_name": student.display_name,
        "period": period,
        "period_start": start.isoformat(),
        "period_end": now.isoformat(),
        "total_xp": int(total_xp),
        "concepts_mastered": concepts_mastered,
        "accuracy_rate": accuracy,
        "daily_xp": daily_xp,
        "xp_by_type": xp_by_type,
        "badges_earned": badges_earned,
        "daily_streak": student.daily_streak or 0,
        "daily_streak_best": student.daily_streak_best or 0,
    }


# ── Admin Undo/Redo Audit Log Endpoints ───────────────────────────────────────

@limiter.limit("30/minute")
@router.get("/api/admin/changes")
async def list_my_changes(
    request: Request,
    book_slug: str | None = Query(None),
    include_undone: bool = Query(True),
    limit: int = Query(50, ge=1, le=50),
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AuditLogEntryResponse]:
    """Return the calling admin's audit log entries (newest first).

    Query parameters:
    - book_slug: filter to a specific book (optional)
    - include_undone: if true (default), include entries where undone_at IS NOT NULL; pass false to exclude undone entries
    - limit: max entries to return (capped at 50)
    """
    q = (
        select(AdminAuditLog)
        .where(AdminAuditLog.admin_id == _user.id)
        .order_by(AdminAuditLog.created_at.desc())
        .limit(limit)
    )
    if book_slug is not None:
        q = q.where(AdminAuditLog.book_slug == book_slug)
    if not include_undone:
        q = q.where(AdminAuditLog.undone_at.is_(None))

    rows = (await db.execute(q)).scalars().all()
    return [AuditLogEntryResponse.model_validate(row) for row in rows]


@limiter.limit("10/minute")
@router.post("/api/admin/changes/{audit_id}/undo")
async def undo_action(
    audit_id: UUID,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UndoResponse:
    """Undo an admin action identified by audit_id.

    Rules:
    - 404 if the audit entry does not exist
    - 403 if the entry belongs to a different admin
    - 400 if the entry has already been undone
    - 409 if the current resource state does not match the recorded post-mutation state
    """
    audit = await db.get(AdminAuditLog, audit_id)
    if audit is None:
        raise HTTPException(404, "Audit entry not found")
    if audit.admin_id != _user.id:
        raise HTTPException(403, "Cannot undo another admin's action")
    if audit.undone_at is not None:
        raise HTTPException(400, "Action already undone")

    # Stale-check raises 409 if resource drifted since this audit was recorded
    await audit_service.stale_check(db, audit)
    await audit_service.apply_undo(db, audit, _user.id)
    await db.commit()

    logger.info(
        "[admin] Undone action '%s' (audit_id=%s) by admin %s",
        audit.action_type, audit_id, str(_user.id),
    )
    return UndoResponse(
        success=True,
        message=f"Undone: {audit.action_type} on {audit.resource_id}",
        audit_id=audit_id,
        action_type=audit.action_type,
    )


@limiter.limit("10/minute")
@router.post("/api/admin/changes/{audit_id}/redo")
async def redo_action(
    audit_id: UUID,
    request: Request,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedoResponse:
    """Redo a previously undone admin action.

    Rules:
    - 404 if the audit entry does not exist
    - 403 if the entry belongs to a different admin
    - 400 if the entry has NOT been undone (can only redo undone actions)
    - 409 if the current resource state does not match what was expected after the undo
    """
    audit = await db.get(AdminAuditLog, audit_id)
    if audit is None:
        raise HTTPException(404, "Audit entry not found")
    if audit.admin_id != _user.id:
        raise HTTPException(403, "Cannot redo another admin's action")
    if audit.undone_at is None:
        raise HTTPException(400, "Action has not been undone — cannot redo an active action")

    # Stale-check for redo: current state should match old_value (post-undo state)
    # We temporarily swap new_value into a transient check against old_value semantics.
    # apply_redo handles its own stale detection implicitly via DB operations;
    # for safety run a quick existence check via stale_check on a synthetic audit object.
    new_audit = await audit_service.apply_redo(db, audit, _user.id)
    await db.commit()

    logger.info(
        "[admin] Redo action '%s' (audit_id=%s) → new audit_id=%s by admin %s",
        audit.action_type, audit_id, new_audit.id, str(_user.id),
    )
    return RedoResponse(
        success=True,
        message=f"Redone: {audit.action_type} on {audit.resource_id}",
        original_audit_id=audit_id,
        new_audit_id=new_audit.id,
        action_type=audit.action_type,
    )
