"""Audit service for Admin Undo/Redo.

Provides:
- snapshot helpers (snapshot_chunk, snapshot_section, snapshot_session_progress_for_chunks)
- encode_embedding / decode_embedding (base64 ↔ list[float])
- log_action  — insert an AdminAuditLog row inside the caller's transaction
- stale_check — compare current DB state to audit.new_value; raise 409 on drift
- apply_undo  — dispatch to _undo_<action_type> handler
- apply_redo  — re-apply new_value semantics and create a new audit row
- purge_old_audits_per_admin — retention helper used by the cleanup task
- 11 private _undo_* handlers, one per auditable action_type
"""
from __future__ import annotations

import base64
import json
import logging
import struct
import tempfile
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import OUTPUT_DIR
from api.teaching_service import invalidate_chunk_cache
from db.models import AdminAuditLog, ChunkImage, ConceptChunk, TeachingSession

logger = logging.getLogger(__name__)


# ─── Embedding codec ─────────────────────────────────────────────────────────

def encode_embedding(vec: list[float] | None) -> str | None:
    """Encode a pgvector list[float] to a base64 IEEE 754 float32 string.

    Returns None when ``vec`` is None (un-embedded chunk).
    """
    if vec is None:
        return None
    raw = struct.pack(f"{len(vec)}f", *vec)
    return base64.b64encode(raw).decode()


def decode_embedding(b64: str | None) -> list[float] | None:
    """Decode a base64 float32 string back to list[float].

    Returns None when ``b64`` is None.
    """
    if b64 is None:
        return None
    raw = base64.b64decode(b64)
    count = len(raw) // 4
    return list(struct.unpack(f"{count}f", raw))


# ─── Snapshot helpers ─────────────────────────────────────────────────────────

async def snapshot_chunk(db: AsyncSession, chunk_id: UUID) -> dict:
    """Return a full auditable snapshot of a ConceptChunk row.

    Includes all mutable fields, base64-encoded embedding, and chunk_images.
    Raises HTTP 404 if the chunk does not exist.
    """
    chunk = (
        await db.execute(
            select(ConceptChunk).where(ConceptChunk.id == chunk_id)
        )
    ).scalar_one_or_none()
    if chunk is None:
        raise HTTPException(404, f"Chunk {chunk_id} not found")

    # Load images eagerly (relationship may not be loaded yet)
    images_result = await db.execute(
        select(ChunkImage)
        .where(ChunkImage.chunk_id == chunk_id)
        .order_by(ChunkImage.order_index)
    )
    images = images_result.scalars().all()

    vec = chunk.embedding
    # pgvector returns its own vector type; convert to plain list for JSON
    if vec is not None and not isinstance(vec, list):
        try:
            vec = list(vec)
        except Exception:
            vec = None

    return {
        "id": str(chunk.id),
        "concept_id": chunk.concept_id,
        "book_slug": chunk.book_slug,
        "section": chunk.section,
        "order_index": chunk.order_index,
        "heading": chunk.heading,
        "text": chunk.text,
        "chunk_type": chunk.chunk_type,
        "is_optional": chunk.is_optional,
        "is_hidden": chunk.is_hidden,
        "exam_disabled": chunk.exam_disabled,
        "chunk_type_locked": chunk.chunk_type_locked,
        "admin_section_name": chunk.admin_section_name,
        "latex": list(chunk.latex) if chunk.latex else [],
        "embedding": encode_embedding(vec),
        "images": [
            {
                "id": str(img.id),
                "image_url": img.image_url,
                "caption": img.caption,
                "order_index": img.order_index,
            }
            for img in images
        ],
    }


async def snapshot_section(
    db: AsyncSession, concept_id: str, book_slug: str
) -> list[dict]:
    """Return a lightweight snapshot of all chunks in a section.

    Each entry contains the fields most likely to change in section-level bulk ops.
    """
    chunks = (
        await db.execute(
            select(ConceptChunk)
            .where(
                ConceptChunk.concept_id == concept_id,
                ConceptChunk.book_slug == book_slug,
            )
            .order_by(ConceptChunk.order_index)
        )
    ).scalars().all()

    return [
        {
            "id": str(c.id),
            "concept_id": c.concept_id,
            "section": c.section,
            "order_index": c.order_index,
            "is_hidden": c.is_hidden,
            "chunk_type_locked": c.chunk_type_locked,
            "is_optional": c.is_optional,
            "exam_disabled": c.exam_disabled,
            "admin_section_name": c.admin_section_name,
            "admin_section_name_translations": c.admin_section_name_translations or {},  # extended for i18n undo
        }
        for c in chunks
    ]


async def snapshot_session_progress_for_chunks(
    db: AsyncSession, chunk_ids: list[UUID]
) -> list[dict]:
    """Return chunk_progress snapshots for active sessions referencing any of chunk_ids.

    Used by merge/split/promote undo to restore session state.
    """
    if not chunk_ids:
        return []

    chunk_id_strs = [str(c) for c in chunk_ids]

    # Fetch all non-COMPLETED sessions that have a non-null chunk_progress
    sessions = (
        await db.execute(
            select(TeachingSession).where(
                TeachingSession.phase != "COMPLETED",
                TeachingSession.chunk_progress.isnot(None),
            )
        )
    ).scalars().all()

    result = []
    for session in sessions:
        progress = session.chunk_progress or {}
        if any(cid in progress for cid in chunk_id_strs):
            result.append(
                {
                    "session_id": str(session.id),
                    "chunk_progress_before": dict(progress),
                }
            )
    return result


# ─── Core audit operations ────────────────────────────────────────────────────

async def log_action(
    db: AsyncSession,
    *,
    admin_id: UUID,
    action_type: str,
    resource_type: str,
    resource_id: str,
    book_slug: str,
    old_value: dict,
    new_value: dict,
    affected_count: int = 1,
    redo_of: UUID | None = None,
) -> AdminAuditLog:
    """Insert an AdminAuditLog row within the caller's open transaction.

    The caller is responsible for calling ``db.commit()`` after this function
    returns — this function intentionally does NOT commit.
    """
    audit = AdminAuditLog(
        admin_id=admin_id,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=resource_id,
        book_slug=book_slug,
        old_value=old_value,
        new_value=new_value,
        affected_count=affected_count,
        redo_of=redo_of,
    )
    db.add(audit)
    await db.flush()  # populate audit.id without committing
    logger.info(
        "[admin] Action '%s' on '%s' by admin %s → audit_id=%s",
        action_type, resource_id, admin_id, audit.id,
    )
    return audit


async def stale_check(db: AsyncSession, audit: AdminAuditLog) -> None:
    """Compare current DB state to audit.new_value; raise HTTP 409 on drift.

    Each action_type has its own comparison logic.  A 409 means another admin
    (or the same admin via a different action) has modified the resource since
    this audit entry was recorded, making an automatic undo unsafe.
    """
    action = audit.action_type
    new_val = audit.new_value

    if action == "update_chunk":
        chunk = await db.get(ConceptChunk, UUID(audit.resource_id))
        if chunk is None:
            raise HTTPException(409, "Resource no longer exists")
        for field in (
            "heading", "text", "chunk_type", "is_optional",
            "is_hidden", "exam_disabled", "chunk_type_locked",
        ):
            if field not in new_val:
                continue
            current = getattr(chunk, field)
            expected = new_val[field]
            if current != expected:
                raise HTTPException(
                    409,
                    f"Cannot undo — resource was modified since this audit was recorded. "
                    f"Field '{field}' expected {expected!r} but found {current!r}. "
                    "Refresh and retry.",
                )

    elif action == "toggle_chunk_visibility":
        chunk = await db.get(ConceptChunk, UUID(audit.resource_id))
        if chunk is None:
            raise HTTPException(409, "Resource no longer exists")
        expected = new_val.get("is_hidden")
        if chunk.is_hidden != expected:
            raise HTTPException(
                409,
                f"Field 'is_hidden' has been modified since this audit. Refresh and retry.",
            )

    elif action == "toggle_chunk_exam_gate":
        chunk = await db.get(ConceptChunk, UUID(audit.resource_id))
        if chunk is None:
            raise HTTPException(409, "Resource no longer exists")
        expected = new_val.get("exam_disabled")
        if chunk.exam_disabled != expected:
            raise HTTPException(
                409,
                f"Field 'exam_disabled' has been modified since this audit. Refresh and retry.",
            )

    elif action == "rename_section":
        # new_value has a single admin_section_name; check representative chunk
        expected_name = new_val.get("admin_section_name")
        chunk_ids = new_val.get("affected_chunk_ids", [])
        if chunk_ids:
            chunk = await db.get(ConceptChunk, UUID(chunk_ids[0]))
            if chunk is None:
                raise HTTPException(409, "Resource no longer exists")
            if chunk.admin_section_name != expected_name:
                raise HTTPException(
                    409,
                    "Section name has been changed since this audit. Refresh and retry.",
                )

    elif action == "toggle_section_optional":
        expected_val = new_val.get("is_optional")
        for entry in new_val.get("per_chunk", []):
            chunk = await db.get(ConceptChunk, UUID(entry["id"]))
            if chunk is None:
                continue
            if chunk.is_optional != expected_val:
                raise HTTPException(
                    409,
                    f"Chunk {entry['id']} is_optional has been changed. Refresh and retry.",
                )

    elif action == "toggle_section_exam_gate":
        expected_val = new_val.get("exam_disabled")
        for entry in new_val.get("per_chunk", []):
            chunk = await db.get(ConceptChunk, UUID(entry["id"]))
            if chunk is None:
                continue
            if chunk.exam_disabled != expected_val:
                raise HTTPException(
                    409,
                    f"Chunk {entry['id']} exam_disabled has been changed. Refresh and retry.",
                )

    elif action == "toggle_section_visibility":
        expected_hidden = new_val.get("is_hidden")
        expected_locked = new_val.get("chunk_type_locked")
        for entry in new_val.get("per_chunk", []):
            chunk = await db.get(ConceptChunk, UUID(entry["id"]))
            if chunk is None:
                continue
            if chunk.is_hidden != expected_hidden:
                raise HTTPException(
                    409,
                    f"Chunk {entry['id']} is_hidden has been changed. Refresh and retry.",
                )
            if expected_locked is not None and chunk.chunk_type_locked != expected_locked:
                raise HTTPException(
                    409,
                    f"Chunk {entry['id']} chunk_type_locked has been changed. Refresh and retry.",
                )

    elif action == "reorder_chunks":
        for entry in new_val.get("per_chunk", []):
            chunk = await db.get(ConceptChunk, UUID(entry["id"]))
            if chunk is None:
                continue
            if chunk.order_index != entry["order_index"]:
                raise HTTPException(
                    409,
                    f"Chunk {entry['id']} order has changed. Refresh and retry.",
                )

    elif action == "merge_chunks":
        surviving = await db.get(ConceptChunk, UUID(new_val["surviving_chunk_id"]))
        if surviving is None:
            raise HTTPException(409, "Merged chunk no longer exists. Cannot safely undo.")
        # Compare text to detect post-merge edits
        if surviving.text != new_val.get("new_text"):
            raise HTTPException(
                409,
                "Merged chunk has been further edited. Cannot safely undo.",
            )

    elif action == "split_chunk":
        created = await db.get(ConceptChunk, UUID(new_val["created_chunk_id"]))
        if created is None:
            raise HTTPException(409, "Split chunk no longer exists. Cannot undo.")

    elif action == "promote":
        new_concept_id = new_val.get("new_concept_id")
        for chunk_id_str in new_val.get("affected_chunk_ids", []):
            chunk = await db.get(ConceptChunk, UUID(chunk_id_str))
            if chunk is None:
                continue
            if chunk.concept_id != new_concept_id:
                raise HTTPException(
                    409,
                    "Promoted chunks have been modified since this audit. Cannot safely undo.",
                )


# ─── Undo handlers (one per action_type) ─────────────────────────────────────

async def _undo_update_chunk(db: AsyncSession, audit: AdminAuditLog) -> None:
    old = audit.old_value
    chunk = await db.get(ConceptChunk, UUID(audit.resource_id))
    if chunk is None:
        raise HTTPException(404, "Chunk no longer exists — cannot undo")
    for field in (
        "heading", "text", "chunk_type", "is_optional",
        "is_hidden", "exam_disabled", "chunk_type_locked",
    ):
        if field in old:
            setattr(chunk, field, old[field])
    # Restore embedding if present
    if "embedding" in old:
        chunk.embedding = decode_embedding(old["embedding"])
    await invalidate_chunk_cache(db, [audit.resource_id])
    await db.flush()


async def _undo_toggle_chunk_visibility(db: AsyncSession, audit: AdminAuditLog) -> None:
    old = audit.old_value
    chunk = await db.get(ConceptChunk, UUID(audit.resource_id))
    if chunk is None:
        raise HTTPException(404, "Chunk no longer exists — cannot undo")
    chunk.is_hidden = old["is_hidden"]
    await invalidate_chunk_cache(db, [audit.resource_id])
    await db.flush()


async def _undo_toggle_chunk_exam_gate(db: AsyncSession, audit: AdminAuditLog) -> None:
    old = audit.old_value
    chunk = await db.get(ConceptChunk, UUID(audit.resource_id))
    if chunk is None:
        raise HTTPException(404, "Chunk no longer exists — cannot undo")
    chunk.exam_disabled = old["exam_disabled"]
    await invalidate_chunk_cache(db, [audit.resource_id])
    await db.flush()


async def _undo_rename_section(db: AsyncSession, audit: AdminAuditLog) -> None:
    old = audit.old_value
    # old_value has per-chunk original names stored directly; the new_value
    # has a single uniform name applied to all chunks.  On undo we restore
    # the original name to each chunk individually.
    original_name = old.get("admin_section_name")
    original_translations = old.get("admin_section_name_translations", {})
    chunk_ids = old.get("affected_chunk_ids", [])
    for chunk_id_str in chunk_ids:
        chunk = await db.get(ConceptChunk, UUID(chunk_id_str))
        if chunk is None:
            continue
        chunk.admin_section_name = original_name
        chunk.admin_section_name_translations = original_translations
    await invalidate_chunk_cache(db, chunk_ids)
    await db.flush()


async def _undo_toggle_section_optional(db: AsyncSession, audit: AdminAuditLog) -> None:
    old = audit.old_value
    _chunk_ids = [entry["id"] for entry in old.get("per_chunk", [])]
    for entry in old.get("per_chunk", []):
        chunk = await db.get(ConceptChunk, UUID(entry["id"]))
        if chunk is None:
            continue
        chunk.is_optional = entry["is_optional"]
    await invalidate_chunk_cache(db, _chunk_ids)
    await db.flush()


async def _undo_toggle_section_exam_gate(db: AsyncSession, audit: AdminAuditLog) -> None:
    old = audit.old_value
    _exam_chunk_ids = [entry["id"] for entry in old.get("per_chunk", [])]
    for entry in old.get("per_chunk", []):
        chunk = await db.get(ConceptChunk, UUID(entry["id"]))
        if chunk is None:
            continue
        chunk.exam_disabled = entry["exam_disabled"]
    await invalidate_chunk_cache(db, _exam_chunk_ids)
    await db.flush()


async def _undo_toggle_section_visibility(db: AsyncSession, audit: AdminAuditLog) -> None:
    old = audit.old_value
    _vis_chunk_ids = [entry["id"] for entry in old.get("per_chunk", [])]
    for entry in old.get("per_chunk", []):
        chunk = await db.get(ConceptChunk, UUID(entry["id"]))
        if chunk is None:
            continue
        chunk.is_hidden = entry["is_hidden"]
        chunk.chunk_type_locked = entry["chunk_type_locked"]
    await invalidate_chunk_cache(db, _vis_chunk_ids)
    await db.flush()


async def _undo_reorder_chunks(db: AsyncSession, audit: AdminAuditLog) -> None:
    old = audit.old_value
    for entry in old.get("per_chunk", []):
        chunk = await db.get(ConceptChunk, UUID(entry["id"]))
        if chunk is None:
            continue
        chunk.order_index = entry["order_index"]
    await db.flush()


async def _undo_merge_chunks(db: AsyncSession, audit: AdminAuditLog) -> None:
    """Undo a merge by:
    1. Re-inserting chunk2 with its original UUID and all original fields.
    2. Re-inserting chunk2's original chunk_images.
    3. Restoring chunk1 heading/text/embedding to pre-merge values.
    4. Restoring each affected session's chunk_progress.
    """
    old = audit.old_value
    chunk1_snap = old["chunk1"]
    chunk2_snap = old["chunk2"]

    # 1. Restore chunk1 (the surviving chunk) to pre-merge state
    chunk1 = await db.get(ConceptChunk, UUID(chunk1_snap["id"]))
    if chunk1 is None:
        raise HTTPException(404, "Surviving chunk no longer exists — cannot undo merge")
    chunk1.heading = chunk1_snap["heading"]
    chunk1.text = chunk1_snap["text"]
    chunk1.embedding = decode_embedding(chunk1_snap.get("embedding"))

    # 2. Re-INSERT chunk2 with original UUID
    chunk2_id = UUID(chunk2_snap["id"])
    existing_c2 = await db.get(ConceptChunk, chunk2_id)
    if existing_c2 is None:
        # Only re-insert if the row was actually deleted (normal case)
        new_chunk2 = ConceptChunk(
            id=chunk2_id,
            book_slug=chunk2_snap["book_slug"],
            concept_id=chunk2_snap["concept_id"],
            section=chunk2_snap["section"],
            order_index=chunk2_snap["order_index"],
            heading=chunk2_snap["heading"],
            text=chunk2_snap["text"],
            chunk_type=chunk2_snap.get("chunk_type", "teaching"),
            is_optional=chunk2_snap.get("is_optional", False),
            is_hidden=chunk2_snap.get("is_hidden", False),
            exam_disabled=chunk2_snap.get("exam_disabled", False),
            chunk_type_locked=chunk2_snap.get("chunk_type_locked", False),
            admin_section_name=chunk2_snap.get("admin_section_name"),
            latex=chunk2_snap.get("latex", []),
            embedding=decode_embedding(chunk2_snap.get("embedding")),
        )
        db.add(new_chunk2)
        await db.flush()  # ensure chunk2_id exists before inserting images

    # 3. Re-INSERT chunk2 images
    for img_snap in chunk2_snap.get("images", []):
        img_id = UUID(img_snap["id"]) if img_snap.get("id") else None
        img = ChunkImage(
            id=img_id,
            chunk_id=chunk2_id,
            image_url=img_snap["image_url"],
            caption=img_snap.get("caption"),
            order_index=img_snap.get("order_index", 0),
        )
        db.add(img)

    # 4. Restore session chunk_progress
    for sess_snap in old.get("affected_sessions", []):
        session = await db.get(TeachingSession, UUID(sess_snap["session_id"]))
        if session is None:
            continue
        session.chunk_progress = sess_snap["chunk_progress_before"]

    # Invalidate cache for both chunks (the surviving chunk and the restored chunk2)
    _merge_chunk_ids = [chunk1_snap["id"], chunk2_snap["id"]]
    await invalidate_chunk_cache(db, _merge_chunk_ids)
    await db.flush()


async def _undo_split_chunk(db: AsyncSession, audit: AdminAuditLog) -> None:
    """Undo a split by:
    1. Deleting the created (second) chunk.
    2. Restoring the original chunk's text + embedding.
    3. Restoring order_index values for shifted chunks.
    4. Restoring session chunk_progress.
    """
    old = audit.old_value
    new_val = audit.new_value
    original_snap = old["original_chunk"]

    # 1. Delete the created chunk (cascade deletes its chunk_images)
    created_chunk_id = UUID(new_val["created_chunk_id"])
    created = await db.get(ConceptChunk, created_chunk_id)
    if created is not None:
        await db.delete(created)
        await db.flush()

    # 2. Restore original chunk
    original_chunk = await db.get(ConceptChunk, UUID(original_snap["id"]))
    if original_chunk is None:
        raise HTTPException(404, "Original chunk no longer exists — cannot undo split")
    original_chunk.text = original_snap["text"]
    original_chunk.embedding = decode_embedding(original_snap.get("embedding"))

    # 3. Restore order_index values for chunks that were shifted
    for delta in new_val.get("reorder_delta", []):
        chunk = await db.get(ConceptChunk, UUID(delta["id"]))
        if chunk is None:
            continue
        chunk.order_index = delta["old_order"]

    # 4. Restore session chunk_progress
    for sess_snap in old.get("affected_sessions", []):
        session = await db.get(TeachingSession, UUID(sess_snap["session_id"]))
        if session is None:
            continue
        session.chunk_progress = sess_snap["chunk_progress_before"]

    # Invalidate cache for the original chunk (the created chunk was deleted above)
    await invalidate_chunk_cache(db, [original_snap["id"]])
    await db.flush()


async def _undo_promote(db: AsyncSession, audit: AdminAuditLog) -> None:
    """Undo a promote (subsection → section) by:
    1. Moving affected chunks back to the original concept_id/section/is_hidden.
    2. Overwriting graph.json with the pre-promote snapshot.
    3. Reloading the in-process graph cache.
    """
    old = audit.old_value
    book_slug = audit.book_slug

    # 1. Restore chunk concept_id, section, is_hidden
    _promote_chunk_ids = []
    for chunk_snap in old.get("affected_chunks", []):
        chunk = await db.get(ConceptChunk, UUID(chunk_snap["id"]))
        if chunk is None:
            continue
        chunk.concept_id = chunk_snap["concept_id"]
        chunk.section = chunk_snap["section"]
        chunk.is_hidden = chunk_snap.get("is_hidden", False)
        _promote_chunk_ids.append(chunk_snap["id"])

    await invalidate_chunk_cache(db, _promote_chunk_ids)
    await db.flush()

    # 2. Restore graph.json atomically (write temp → rename)
    graph_json_before = old.get("graph_json_before")
    if graph_json_before is None:
        logger.error(
            "[audit_undo] graph_json_before is missing in promote audit %s — "
            "graph.json NOT restored; manual recovery required",
            audit.id,
        )
        raise HTTPException(
            500,
            "graph.json snapshot missing from audit record — manual recovery required",
        )

    graph_path = OUTPUT_DIR / book_slug / "graph.json"
    if not graph_path.parent.exists():
        logger.error(
            "[audit_undo] graph.json parent dir %s does not exist — cannot restore",
            graph_path.parent,
        )
        raise HTTPException(
            500,
            "graph.json not found — manual recovery required",
        )

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(graph_path.parent), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(graph_json_before, f, ensure_ascii=False)
        os.replace(tmp_path, str(graph_path))
        logger.info(
            "[audit_undo] Restored graph.json for book=%s (promote undo audit=%s)",
            book_slug, audit.id,
        )
    except Exception:
        # Clean up temp file on failure before re-raising
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    # 3. Reload in-memory graph cache
    try:
        from api.chunk_knowledge_service import reload_graph_with_overrides
        await reload_graph_with_overrides(book_slug, db)
    except Exception:
        logger.exception(
            "[audit_undo] Graph cache reload failed after promote undo (book=%s). "
            "graph.json was restored on disk but cache may be stale.",
            book_slug,
        )


# ─── Dispatch table ───────────────────────────────────────────────────────────

_UNDO_HANDLERS: dict[str, Callable] = {
    "update_chunk":              _undo_update_chunk,
    "toggle_chunk_visibility":   _undo_toggle_chunk_visibility,
    "toggle_chunk_exam_gate":    _undo_toggle_chunk_exam_gate,
    "rename_section":            _undo_rename_section,
    "toggle_section_optional":   _undo_toggle_section_optional,
    "toggle_section_exam_gate":  _undo_toggle_section_exam_gate,
    "toggle_section_visibility": _undo_toggle_section_visibility,
    "reorder_chunks":            _undo_reorder_chunks,
    "merge_chunks":              _undo_merge_chunks,
    "split_chunk":               _undo_split_chunk,
    "promote":                   _undo_promote,
}


async def apply_undo(
    db: AsyncSession, audit: AdminAuditLog, current_admin_id: UUID
) -> None:
    """Dispatch to the matching _undo_<action_type> handler.

    Sets audit.undone_at and audit.undone_by on the audit row.
    Caller must commit after this returns.
    """
    handler = _UNDO_HANDLERS.get(audit.action_type)
    if handler is None:
        raise HTTPException(
            400, f"No undo handler registered for action_type={audit.action_type!r}"
        )
    await handler(db, audit)
    audit.undone_at = datetime.now(timezone.utc)
    audit.undone_by = current_admin_id
    logger.info(
        "[admin] Undone action '%s' (audit_id=%s) by admin %s",
        audit.action_type, audit.id, current_admin_id,
    )


async def apply_redo(
    db: AsyncSession, audit: AdminAuditLog, current_admin_id: UUID
) -> AdminAuditLog:
    """Re-apply the original action by swapping old/new_value semantics.

    Creates and returns a new AdminAuditLog row with ``redo_of=audit.id``.
    The new row records old_value=audit.new_value (current state that was
    restored by undo) and new_value=audit.old_value (target pre-undo state,
    which is the desired post-redo state).

    For promote, additionally re-writes graph.json and reloads the cache.
    Caller must commit after this returns.
    """
    action = audit.action_type
    book_slug = audit.book_slug

    # Apply the inverse: re-apply new_value to the resource
    if action == "update_chunk":
        new_val = audit.new_value
        chunk = await db.get(ConceptChunk, UUID(audit.resource_id))
        if chunk is None:
            raise HTTPException(404, "Chunk no longer exists — cannot redo")
        for field in (
            "heading", "text", "chunk_type", "is_optional",
            "is_hidden", "exam_disabled", "chunk_type_locked",
        ):
            if field in new_val:
                setattr(chunk, field, new_val[field])
        if "embedding" in new_val:
            chunk.embedding = decode_embedding(new_val["embedding"])

    elif action == "toggle_chunk_visibility":
        chunk = await db.get(ConceptChunk, UUID(audit.resource_id))
        if chunk is None:
            raise HTTPException(404, "Chunk no longer exists — cannot redo")
        chunk.is_hidden = audit.new_value["is_hidden"]

    elif action == "toggle_chunk_exam_gate":
        chunk = await db.get(ConceptChunk, UUID(audit.resource_id))
        if chunk is None:
            raise HTTPException(404, "Chunk no longer exists — cannot redo")
        chunk.exam_disabled = audit.new_value["exam_disabled"]

    elif action == "rename_section":
        new_name = audit.new_value.get("admin_section_name")
        new_translations = audit.new_value.get("admin_section_name_translations", {})
        for chunk_id_str in audit.old_value.get("affected_chunk_ids", []):
            chunk = await db.get(ConceptChunk, UUID(chunk_id_str))
            if chunk is None:
                continue
            chunk.admin_section_name = new_name
            chunk.admin_section_name_translations = new_translations

    elif action == "toggle_section_optional":
        new_val = audit.new_value.get("is_optional")
        for entry in audit.old_value.get("per_chunk", []):
            chunk = await db.get(ConceptChunk, UUID(entry["id"]))
            if chunk is None:
                continue
            chunk.is_optional = new_val

    elif action == "toggle_section_exam_gate":
        new_val = audit.new_value.get("exam_disabled")
        for entry in audit.old_value.get("per_chunk", []):
            chunk = await db.get(ConceptChunk, UUID(entry["id"]))
            if chunk is None:
                continue
            chunk.exam_disabled = new_val

    elif action == "toggle_section_visibility":
        new_hidden = audit.new_value.get("is_hidden")
        new_locked = audit.new_value.get("chunk_type_locked")
        for entry in audit.old_value.get("per_chunk", []):
            chunk = await db.get(ConceptChunk, UUID(entry["id"]))
            if chunk is None:
                continue
            chunk.is_hidden = new_hidden
            if new_locked is not None:
                chunk.chunk_type_locked = new_locked

    elif action == "reorder_chunks":
        for entry in audit.new_value.get("per_chunk", []):
            chunk = await db.get(ConceptChunk, UUID(entry["id"]))
            if chunk is None:
                continue
            chunk.order_index = entry["order_index"]

    elif action == "merge_chunks":
        # Re-apply merge: delete chunk2 again, re-merge chunk1 text/heading/embedding
        new_val = audit.new_value
        old_val = audit.old_value
        chunk1_snap = old_val["chunk1"]
        chunk2_snap = old_val["chunk2"]

        chunk1 = await db.get(ConceptChunk, UUID(chunk1_snap["id"]))
        if chunk1 is None:
            raise HTTPException(404, "Chunk 1 no longer exists — cannot redo merge")
        chunk2 = await db.get(ConceptChunk, UUID(chunk2_snap["id"]))
        if chunk2 is None:
            raise HTTPException(404, "Chunk 2 no longer exists — cannot redo merge (was it re-created?)")

        chunk1.heading = new_val.get("new_heading", chunk1.heading)
        chunk1.text = new_val.get("new_text", chunk1.text)
        chunk1.embedding = None  # stale
        # Transfer images from chunk2 to chunk1 again
        await db.execute(
            text("UPDATE chunk_images SET chunk_id = :c1 WHERE chunk_id = :c2"),
            {"c1": chunk1.id, "c2": chunk2.id},
        )
        await db.delete(chunk2)

    elif action == "split_chunk":
        # Re-apply split: re-create the second chunk and shift order_indexes
        new_val = audit.new_value
        old_val = audit.old_value
        original_snap = old_val["original_chunk"]

        original_chunk = await db.get(ConceptChunk, UUID(original_snap["id"]))
        if original_chunk is None:
            raise HTTPException(404, "Original chunk no longer exists — cannot redo split")

        original_chunk.text = new_val.get("original_new_text", original_chunk.text)
        original_chunk.embedding = None  # stale

        for delta in new_val.get("reorder_delta", []):
            chunk = await db.get(ConceptChunk, UUID(delta["id"]))
            if chunk is None:
                continue
            chunk.order_index = delta["new_order"]

        created_chunk_id = UUID(new_val["created_chunk_id"])
        existing = await db.get(ConceptChunk, created_chunk_id)
        if existing is None:
            new_c = ConceptChunk(
                id=created_chunk_id,
                book_slug=original_chunk.book_slug,
                concept_id=original_chunk.concept_id,
                section=original_chunk.section,
                order_index=original_chunk.order_index + 1,
                heading=original_chunk.heading + " (cont.)",
                text=new_val.get("new_chunk_text", ""),
                chunk_type=original_chunk.chunk_type,
                is_optional=original_chunk.is_optional,
                exam_disabled=original_chunk.exam_disabled,
                is_hidden=original_chunk.is_hidden,
                embedding=None,
            )
            db.add(new_c)

    elif action == "promote":
        # Re-apply promote: move chunks to new_concept_id and restore graph.json after
        new_val = audit.new_value
        new_concept_id = new_val["new_concept_id"]
        new_section_label = new_val.get("new_section_label", new_concept_id)
        for chunk_id_str in new_val.get("affected_chunk_ids", []):
            chunk = await db.get(ConceptChunk, UUID(chunk_id_str))
            if chunk is None:
                continue
            chunk.concept_id = new_concept_id
            chunk.section = new_section_label
            chunk.is_hidden = False

        # Restore post-promote graph.json
        graph_json_after = new_val.get("graph_json_after")
        if graph_json_after is not None:
            graph_path = OUTPUT_DIR / book_slug / "graph.json"
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=str(graph_path.parent), suffix=".tmp"
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(graph_json_after, f, ensure_ascii=False)
                os.replace(tmp_path, str(graph_path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            try:
                from api.chunk_knowledge_service import reload_graph_with_overrides
                await reload_graph_with_overrides(book_slug, db)
            except Exception:
                logger.exception(
                    "[audit_redo] Graph cache reload failed after promote redo (book=%s)",
                    book_slug,
                )

    # Invalidate cache for the chunks affected by this redo operation.
    # Derive the affected chunk IDs from the audit record using the same logic as the undo handlers.
    _redo_chunk_ids: list[str] = []
    if action in ("update_chunk", "toggle_chunk_visibility", "toggle_chunk_exam_gate"):
        _redo_chunk_ids = [audit.resource_id]
    elif action == "rename_section":
        _redo_chunk_ids = audit.old_value.get("affected_chunk_ids", [])
    elif action in ("toggle_section_optional", "toggle_section_exam_gate", "toggle_section_visibility"):
        _redo_chunk_ids = [e["id"] for e in audit.old_value.get("per_chunk", [])]
    elif action == "merge_chunks":
        old_val = audit.old_value
        _redo_chunk_ids = [old_val["chunk1"]["id"], old_val["chunk2"]["id"]]
    elif action == "split_chunk":
        _redo_chunk_ids = [audit.old_value["original_chunk"]["id"], audit.new_value.get("created_chunk_id", "")]
    elif action == "promote":
        _redo_chunk_ids = audit.new_value.get("affected_chunk_ids", [])
    if _redo_chunk_ids:
        try:
            await invalidate_chunk_cache(db, [cid for cid in _redo_chunk_ids if cid])
        except Exception:
            logger.warning("[audit_redo] cache invalidation failed for action=%s", action, exc_info=True)

    await db.flush()

    # Record the redo as a new audit row (old/new swapped relative to original)
    new_audit = await log_action(
        db,
        admin_id=current_admin_id,
        action_type=action,
        resource_type=audit.resource_type,
        resource_id=audit.resource_id,
        book_slug=book_slug,
        old_value=audit.new_value,  # "before redo" state = the post-undo state
        new_value=audit.old_value,  # "after redo" state = the original pre-undo state
        affected_count=audit.affected_count,
        redo_of=audit.id,
    )
    logger.info(
        "[admin] Redo action '%s' (audit_id=%s) → new audit_id=%s by admin %s",
        action, audit.id, new_audit.id, current_admin_id,
    )
    return new_audit


# ─── Retention ────────────────────────────────────────────────────────────────

async def purge_old_audits_per_admin(
    db: AsyncSession, keep_per_admin: int = 50
) -> int:
    """Delete audit rows older than the N newest per admin_id.

    Uses a window function (ROW_NUMBER PARTITION BY admin_id ORDER BY
    created_at DESC) to identify rows beyond the keep threshold.
    Returns the number of rows deleted.
    """
    result = await db.execute(
        text("""
            DELETE FROM admin_audit_logs
            WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY admin_id
                               ORDER BY created_at DESC
                           ) AS rn
                    FROM admin_audit_logs
                ) ranked
                WHERE rn > :keep
            )
        """),
        {"keep": keep_per_admin},
    )
    deleted = result.rowcount
    logger.info(
        "[audit_cleanup] Purged %d old audit rows (keep_per_admin=%d)",
        deleted, keep_per_admin,
    )
    return deleted
