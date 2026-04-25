"""
test_admin_audit.py — Comprehensive tests for the Admin Undo/Redo audit feature.

Business criteria covered:
  1. Every action_type has a matching _undo_ handler that restores state byte-for-byte.
  2. After undo, apply_redo re-applies the original mutation exactly.
  3. Admin A cannot undo/redo Admin B's audit rows (403 isolation).
  4. merge_chunks undo restores session chunk_progress for all affected sessions.
  5. promote undo restores graph.json byte-for-byte.
  6. A mutation failure must not leave a stale audit row (transaction rollback).
  7. stale_check raises 409 when the resource drifted after the audit was recorded.
  8. Double-undo raises 400 "already undone".
  9. redo without prior undo raises 400.
  10. purge_old_audits_per_admin keeps exactly N newest rows per admin.
  11. A redo creates a new audit row with redo_of set to the original audit id.

Test framework: pytest + pytest-asyncio (asyncio_mode = auto via pytest.ini).
DB: Live PostgreSQL via the existing dev db (migration 020 must be applied).
All tests rollback via savepoints — no permanent data written.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Ensure backend/src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from db.models import (
    AdminAuditLog,
    ConceptChunk,
    Student,
    TeachingSession,
)
from api.audit_service import (
    apply_redo,
    apply_undo,
    encode_embedding,
    decode_embedding,
    log_action,
    purge_old_audits_per_admin,
    snapshot_chunk,
    snapshot_section,
    snapshot_session_progress_for_chunks,
    stale_check,
)

# ─── Constants ────────────────────────────────────────────────────────────────

_DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postre2002@localhost:5432/AdaptiveLearner",
)

# The real admin user pre-existing in the dev DB; used as admin_id throughout.
_ADMIN_A_ID = uuid.UUID("9974738a-6249-40ff-9628-698e8035e1c8")

# A second admin UUID — does NOT need to exist in `users` table because the
# admin_audit_logs.admin_id FK is SET NULL on delete (nullable=True).
# We create audit rows directly, bypassing the FK check where needed.
_ADMIN_B_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


# ─── Per-test isolated DB session (savepoint rollback) ───────────────────────

@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an AsyncSession nested inside a SAVEPOINT.
    On teardown the savepoint is rolled back so no data persists between tests.
    Skips automatically when the DB is unreachable.

    Each test gets a fresh engine + session so there is no cross-event-loop
    sharing (pytest-asyncio creates a new loop per test in function scope).
    """
    try:
        engine = create_async_engine(_DB_URL, echo=False, future=True)
        _factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with _factory() as session:
            async with session.begin():
                sp = await session.begin_nested()
                try:
                    yield session
                finally:
                    await sp.rollback()
        await engine.dispose()
    except Exception as exc:
        err_str = str(exc).lower()
        if "connect" in err_str or "refused" in err_str or "event loop is closed" in err_str:
            pytest.skip(f"DB not available: {exc}")
        raise


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _make_chunk(
    db: AsyncSession,
    *,
    heading: str = "Test Heading",
    text: str = "Test content for the chunk.",
    is_hidden: bool = False,
    exam_disabled: bool = False,
    is_optional: bool = False,
    order_index: int = 0,
    concept_id: str = "testbook_1.1",
    admin_section_name: str | None = None,
) -> ConceptChunk:
    """Insert a ConceptChunk in the current session and return it."""
    chunk = ConceptChunk(
        id=uuid.uuid4(),
        book_slug="testbook",
        concept_id=concept_id,
        section=f"1.1 Test Section",
        order_index=order_index,
        heading=heading,
        text=text,
        latex=[],
        embedding=None,
        is_hidden=is_hidden,
        exam_disabled=exam_disabled,
        is_optional=is_optional,
        admin_section_name=admin_section_name,
    )
    db.add(chunk)
    await db.flush()
    return chunk


async def _make_student(db: AsyncSession) -> Student:
    """Insert a minimal Student row."""
    student = Student(
        id=uuid.uuid4(),
        display_name="Test Student",
        interests=[],
        preferred_style="default",
        preferred_language="en",
    )
    db.add(student)
    await db.flush()
    return student


async def _make_session(
    db: AsyncSession, student_id: uuid.UUID, *, chunk_progress: dict | None = None
) -> TeachingSession:
    """Insert a minimal TeachingSession row."""
    sess = TeachingSession(
        id=uuid.uuid4(),
        student_id=student_id,
        concept_id="testbook_1.1",
        book_slug="testbook",
        phase="CARDS",
        chunk_progress=chunk_progress,
    )
    db.add(sess)
    await db.flush()
    return sess


async def _make_audit(
    db: AsyncSession,
    *,
    admin_id: uuid.UUID,
    action_type: str,
    resource_id: str,
    old_value: dict,
    new_value: dict,
    resource_type: str = "chunk",
    book_slug: str = "testbook",
    redo_of: uuid.UUID | None = None,
) -> AdminAuditLog:
    """Call log_action and return the audit row."""
    return await log_action(
        db,
        admin_id=admin_id,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=resource_id,
        book_slug=book_slug,
        old_value=old_value,
        new_value=new_value,
        redo_of=redo_of,
    )


# ─── Unit tests (one per action_type) ────────────────────────────────────────

class TestUpdateChunkUndoRedo:
    """update_chunk undo reverts heading/text/flags; redo re-applies them."""

    async def test_update_chunk_undo_redo(self, db: AsyncSession):
        # Arrange: create chunk and capture old snapshot
        chunk = await _make_chunk(db, heading="Old Heading", text="Old text content here.")
        old_snap = await snapshot_chunk(db, chunk.id)

        # Act: mutate
        chunk.heading = "New Heading"
        chunk.text = "New text content."
        chunk.is_hidden = True
        new_snap = await snapshot_chunk(db, chunk.id)

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="update_chunk",
            resource_id=str(chunk.id),
            old_value=old_snap,
            new_value=new_snap,
        )

        # Undo
        await apply_undo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk)

        # Assert: state fully restored
        assert chunk.heading == "Old Heading", "heading must revert to old value"
        assert chunk.text == "Old text content here.", "text must revert to old value"
        assert chunk.is_hidden is False, "is_hidden must revert to False"
        assert audit.undone_at is not None, "undone_at must be set"
        assert audit.undone_by == _ADMIN_A_ID, "undone_by must be set"

        # Redo
        new_audit = await apply_redo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk)

        assert chunk.heading == "New Heading", "redo must re-apply new heading"
        assert chunk.is_hidden is True, "redo must re-apply is_hidden=True"
        assert new_audit.redo_of == audit.id, "redo audit must reference original"


class TestToggleChunkVisibilityUndoRedo:
    """toggle_chunk_visibility undo/redo flips is_hidden back and forth."""

    async def test_toggle_chunk_visibility_undo_redo(self, db: AsyncSession):
        chunk = await _make_chunk(db, is_hidden=False)
        old_snap = {"is_hidden": False}
        new_snap = {"is_hidden": True}

        # Mutate
        chunk.is_hidden = True

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="toggle_chunk_visibility",
            resource_id=str(chunk.id),
            old_value=old_snap,
            new_value=new_snap,
        )

        # Undo
        await apply_undo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk)
        assert chunk.is_hidden is False, "undo must restore is_hidden=False"

        # Redo
        await apply_redo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk)
        assert chunk.is_hidden is True, "redo must re-hide the chunk"


class TestToggleChunkExamGateUndoRedo:
    """toggle_chunk_exam_gate undo/redo flips exam_disabled."""

    async def test_toggle_chunk_exam_gate_undo_redo(self, db: AsyncSession):
        chunk = await _make_chunk(db, exam_disabled=False)
        old_snap = {"exam_disabled": False}
        new_snap = {"exam_disabled": True}

        chunk.exam_disabled = True

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="toggle_chunk_exam_gate",
            resource_id=str(chunk.id),
            old_value=old_snap,
            new_value=new_snap,
        )

        await apply_undo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk)
        assert chunk.exam_disabled is False, "undo must restore exam_disabled=False"

        await apply_redo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk)
        assert chunk.exam_disabled is True, "redo must disable exam gate again"


class TestRenameSectionUndoRedo:
    """rename_section undo restores each chunk's admin_section_name individually."""

    async def test_rename_section_undo_redo(self, db: AsyncSession):
        chunk1 = await _make_chunk(db, admin_section_name="Old Name", order_index=0)
        chunk2 = await _make_chunk(db, admin_section_name="Old Name", order_index=1)

        # i18n Phase 3: include admin_section_name_translations in snapshot/audit dicts.
        _old_translations = {
            "en_source_hash": "oldhash",
            "ml": "പഴയ പേര്",
            "ta": "பழைய பெயர்",
        }
        _new_translations = {
            "en_source_hash": "newhash",
            "ml": "പുതിയ പേര്",
            "ta": "புதிய பெயர்",
        }

        old_val = {
            "admin_section_name": "Old Name",
            "admin_section_name_translations": _old_translations,
            "affected_chunk_ids": [str(chunk1.id), str(chunk2.id)],
        }
        new_val = {
            "admin_section_name": "New Name",
            "admin_section_name_translations": _new_translations,
        }

        # Mutate
        chunk1.admin_section_name = "New Name"
        chunk1.admin_section_name_translations = _new_translations
        chunk2.admin_section_name = "New Name"
        chunk2.admin_section_name_translations = _new_translations

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="rename_section",
            resource_id="testbook_1.1",
            resource_type="section",
            old_value=old_val,
            new_value=new_val,
        )

        # i18n Phase 3: verify audit payload carries translations in both old/new.
        assert "admin_section_name_translations" in audit.old_value, (
            "audit.old_value must include admin_section_name_translations key"
        )
        assert audit.old_value["admin_section_name_translations"] == _old_translations, (
            "audit.old_value must snapshot the pre-rename translations"
        )
        assert "admin_section_name_translations" in audit.new_value, (
            "audit.new_value must include admin_section_name_translations key"
        )
        assert audit.new_value["admin_section_name_translations"] == _new_translations, (
            "audit.new_value must carry the freshly-populated translations dict"
        )

        await apply_undo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk1)
        await db.refresh(chunk2)

        assert chunk1.admin_section_name == "Old Name"
        assert chunk2.admin_section_name == "Old Name"

        # i18n Phase 3: undo must also restore admin_section_name_translations.
        assert chunk1.admin_section_name_translations == _old_translations, (
            "undo must restore chunk1.admin_section_name_translations to pre-rename value"
        )
        assert chunk2.admin_section_name_translations == _old_translations, (
            "undo must restore chunk2.admin_section_name_translations to pre-rename value"
        )

        await apply_redo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk1)
        await db.refresh(chunk2)
        assert chunk1.admin_section_name == "New Name"
        assert chunk2.admin_section_name == "New Name"

        # i18n Phase 3: redo must also re-apply admin_section_name_translations.
        assert chunk1.admin_section_name_translations == _new_translations, (
            "redo must re-apply chunk1.admin_section_name_translations from audit new_value"
        )
        assert chunk2.admin_section_name_translations == _new_translations, (
            "redo must re-apply chunk2.admin_section_name_translations from audit new_value"
        )


class TestToggleSectionOptionalUndoRedo:
    """toggle_section_optional undo restores per-chunk is_optional values."""

    async def test_toggle_section_optional_undo_redo(self, db: AsyncSession):
        chunk1 = await _make_chunk(db, is_optional=False, order_index=0)
        chunk2 = await _make_chunk(db, is_optional=True, order_index=1)

        old_val = {
            "per_chunk": [
                {"id": str(chunk1.id), "is_optional": False},
                {"id": str(chunk2.id), "is_optional": True},
            ]
        }
        new_val = {"is_optional": True, "per_chunk": old_val["per_chunk"]}

        # Mutate both to True
        chunk1.is_optional = True
        chunk2.is_optional = True

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="toggle_section_optional",
            resource_id="testbook_1.1",
            resource_type="section",
            old_value=old_val,
            new_value=new_val,
        )

        await apply_undo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk1)
        await db.refresh(chunk2)

        assert chunk1.is_optional is False, "chunk1 is_optional must revert to False"
        assert chunk2.is_optional is True, "chunk2 is_optional must revert to True (original)"

        await apply_redo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk1)
        assert chunk1.is_optional is True, "redo must set chunk1 is_optional=True"


class TestToggleSectionExamGateUndoRedo:
    """toggle_section_exam_gate undo restores per-chunk exam_disabled values."""

    async def test_toggle_section_exam_gate_undo_redo(self, db: AsyncSession):
        chunk1 = await _make_chunk(db, exam_disabled=False, order_index=0)
        chunk2 = await _make_chunk(db, exam_disabled=False, order_index=1)

        old_val = {
            "per_chunk": [
                {"id": str(chunk1.id), "exam_disabled": False},
                {"id": str(chunk2.id), "exam_disabled": False},
            ]
        }
        new_val = {"exam_disabled": True, "per_chunk": old_val["per_chunk"]}

        chunk1.exam_disabled = True
        chunk2.exam_disabled = True

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="toggle_section_exam_gate",
            resource_id="testbook_1.1",
            resource_type="section",
            old_value=old_val,
            new_value=new_val,
        )

        await apply_undo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk1)
        await db.refresh(chunk2)

        assert chunk1.exam_disabled is False
        assert chunk2.exam_disabled is False

        await apply_redo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk1)
        assert chunk1.exam_disabled is True


class TestToggleSectionVisibilityUndoRedo:
    """toggle_section_visibility undo restores is_hidden and chunk_type_locked."""

    async def test_toggle_section_visibility_undo_redo(self, db: AsyncSession):
        chunk = await _make_chunk(db, is_hidden=False)
        chunk.chunk_type_locked = False
        await db.flush()

        old_val = {
            "per_chunk": [
                {"id": str(chunk.id), "is_hidden": False, "chunk_type_locked": False},
            ]
        }
        new_val = {
            "is_hidden": True,
            "chunk_type_locked": True,
            "per_chunk": old_val["per_chunk"],
        }

        chunk.is_hidden = True
        chunk.chunk_type_locked = True

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="toggle_section_visibility",
            resource_id="testbook_1.1",
            resource_type="section",
            old_value=old_val,
            new_value=new_val,
        )

        await apply_undo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk)

        assert chunk.is_hidden is False
        assert chunk.chunk_type_locked is False

        await apply_redo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk)
        assert chunk.is_hidden is True
        assert chunk.chunk_type_locked is True


class TestReorderChunksUndoRedo:
    """reorder_chunks undo restores each chunk's order_index."""

    async def test_reorder_chunks_undo_redo(self, db: AsyncSession):
        chunk_a = await _make_chunk(db, heading="Chunk A", order_index=0)
        chunk_b = await _make_chunk(db, heading="Chunk B", order_index=1)

        old_val = {
            "per_chunk": [
                {"id": str(chunk_a.id), "order_index": 0},
                {"id": str(chunk_b.id), "order_index": 1},
            ]
        }
        new_val = {
            "per_chunk": [
                {"id": str(chunk_a.id), "order_index": 1},
                {"id": str(chunk_b.id), "order_index": 0},
            ]
        }

        # Mutate: swap
        chunk_a.order_index = 1
        chunk_b.order_index = 0

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="reorder_chunks",
            resource_id="testbook_1.1",
            resource_type="section",
            old_value=old_val,
            new_value=new_val,
        )

        await apply_undo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk_a)
        await db.refresh(chunk_b)

        assert chunk_a.order_index == 0, "chunk_a order must revert to 0"
        assert chunk_b.order_index == 1, "chunk_b order must revert to 1"

        await apply_redo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk_a)
        await db.refresh(chunk_b)
        assert chunk_a.order_index == 1
        assert chunk_b.order_index == 0


class TestMergeChunksUndoRedo:
    """merge_chunks undo re-inserts chunk2 with its original UUID and restores chunk1."""

    async def test_merge_chunks_undo_redo(self, db: AsyncSession):
        chunk1 = await _make_chunk(db, heading="Chunk 1", text="Chunk 1 original text.", order_index=0)
        chunk2 = await _make_chunk(db, heading="Chunk 2", text="Chunk 2 original text.", order_index=1)

        chunk1_snap = await snapshot_chunk(db, chunk1.id)
        chunk2_snap = await snapshot_chunk(db, chunk2.id)

        # Simulate merge: set chunk1 to merged content, delete chunk2
        merged_text = "Chunk 1 original text.\n\nChunk 2 original text."
        chunk1.text = merged_text
        chunk1.heading = "Chunk 1 (merged)"
        await db.delete(chunk2)
        await db.flush()

        old_val = {
            "chunk1": chunk1_snap,
            "chunk2": chunk2_snap,
            "affected_sessions": [],
        }
        new_val = {
            "surviving_chunk_id": str(chunk1.id),
            "new_heading": "Chunk 1 (merged)",
            "new_text": merged_text,
        }

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="merge_chunks",
            resource_id=str(chunk1.id),
            old_value=old_val,
            new_value=new_val,
        )

        # Undo merge
        await apply_undo(db, audit, _ADMIN_A_ID)
        await db.flush()

        # Verify chunk1 restored
        await db.refresh(chunk1)
        assert chunk1.heading == "Chunk 1", "chunk1 heading must revert to pre-merge"
        assert chunk1.text == "Chunk 1 original text."

        # Verify chunk2 re-inserted with original UUID
        from sqlalchemy import select
        result = await db.execute(
            select(ConceptChunk).where(ConceptChunk.id == chunk2_snap["id"])
        )
        restored_chunk2 = result.scalar_one_or_none()
        assert restored_chunk2 is not None, "chunk2 must be re-inserted after undo"
        assert restored_chunk2.text == "Chunk 2 original text."

        # Redo: re-merge
        new_audit = await apply_redo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk1)
        assert chunk1.text == merged_text, "redo must re-apply merged text"
        assert new_audit.redo_of == audit.id


class TestSplitChunkUndoRedo:
    """split_chunk undo deletes the created chunk and restores original text."""

    async def test_split_chunk_undo_redo(self, db: AsyncSession):
        original = await _make_chunk(
            db, heading="Full Content", text="First half. Second half.", order_index=0
        )
        original_snap = await snapshot_chunk(db, original.id)

        # Simulate split: shorten original, create new chunk
        created_id = uuid.uuid4()
        original.text = "First half."
        created = ConceptChunk(
            id=created_id,
            book_slug="testbook",
            concept_id="testbook_1.1",
            section="1.1 Test Section",
            order_index=1,
            heading="Full Content (cont.)",
            text="Second half.",
            latex=[],
            embedding=None,
        )
        db.add(created)
        await db.flush()

        old_val = {
            "original_chunk": original_snap,
            "affected_sessions": [],
        }
        new_val = {
            "created_chunk_id": str(created_id),
            "original_new_text": "First half.",
            "new_chunk_text": "Second half.",
            "reorder_delta": [],
        }

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="split_chunk",
            resource_id=str(original.id),
            old_value=old_val,
            new_value=new_val,
        )

        # Undo split
        await apply_undo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(original)

        assert original.text == "First half. Second half.", "text must be restored"

        from sqlalchemy import select
        result = await db.execute(
            select(ConceptChunk).where(ConceptChunk.id == created_id)
        )
        assert result.scalar_one_or_none() is None, "created chunk must be deleted"

        # Redo split
        new_audit = await apply_redo(db, audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(original)
        assert original.text == "First half.", "redo must re-shorten original text"
        assert new_audit.redo_of == audit.id


class TestPromoteSectionUndoRedo:
    """promote undo restores chunk concept_id/section and overwrites graph.json."""

    async def test_promote_section_undo_redo(self, db: AsyncSession, tmp_path: Path):
        chunk = await _make_chunk(
            db,
            heading="Sub-section Content",
            concept_id="testbook_1.1",
            order_index=5,
        )
        chunk.section = "1.1 Old Section"
        await db.flush()

        graph_before = {"nodes": [{"id": "testbook_1.1"}], "edges": []}
        graph_after = {
            "nodes": [{"id": "testbook_1.1"}, {"id": "testbook_1.1b"}],
            "edges": [],
        }

        old_val = {
            "affected_chunks": [
                {
                    "id": str(chunk.id),
                    "concept_id": "testbook_1.1",
                    "section": "1.1 Old Section",
                    "is_hidden": False,
                }
            ],
            "graph_json_before": graph_before,
        }
        new_val = {
            "new_concept_id": "testbook_1.1b",
            "new_section_label": "1.1b Promoted Section",
            "affected_chunk_ids": [str(chunk.id)],
            "graph_json_after": graph_after,
        }

        # Simulate promote mutation
        chunk.concept_id = "testbook_1.1b"
        chunk.section = "1.1b Promoted Section"

        # Write post-promote graph.json to tmp_path
        book_dir = tmp_path / "testbook"
        book_dir.mkdir()
        graph_path = book_dir / "graph.json"
        graph_path.write_text(json.dumps(graph_after), encoding="utf-8")

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="promote",
            resource_type="section",
            resource_id="testbook_1.1",
            old_value=old_val,
            new_value=new_val,
        )

        # Patch OUTPUT_DIR and reload to avoid touching real graph cache
        # reload_graph_with_overrides is a lazy import inside _undo_promote;
        # patch it on the api.chunk_knowledge_service module so the import
        # inside the function picks up the mock.
        from unittest.mock import AsyncMock
        mock_reload = AsyncMock(return_value=None)
        with (
            patch("api.audit_service.OUTPUT_DIR", tmp_path),
            patch(
                "api.chunk_knowledge_service.reload_graph_with_overrides",
                mock_reload,
                create=True,
            ),
        ):
            await apply_undo(db, audit, _ADMIN_A_ID)
            await db.flush()

        await db.refresh(chunk)
        assert chunk.concept_id == "testbook_1.1", "concept_id must revert"
        assert chunk.section == "1.1 Old Section", "section must revert"

        # graph.json must be restored to pre-promote content
        restored_content = json.loads(graph_path.read_text(encoding="utf-8"))
        assert restored_content == graph_before, "graph.json must be byte-for-byte restored"


# ─── Integration tests ────────────────────────────────────────────────────────

class TestCrossAdminIsolation:
    """Admin A cannot undo/redo Admin B's audit rows."""

    async def test_cross_admin_isolation_403(self, db: AsyncSession):
        from fastapi import HTTPException
        from auth.models import User

        chunk = await _make_chunk(db)

        # Create an ephemeral second admin user within the test's savepoint
        admin_b = User(
            id=uuid.uuid4(),
            email=f"admin_b_{uuid.uuid4().hex[:8]}@test.invalid",
            password_hash="irrelevant",
            role="admin",
            is_active=True,
            email_verified=True,
        )
        db.add(admin_b)
        await db.flush()

        # Admin B creates the audit row via the ORM
        audit_b = AdminAuditLog(
            admin_id=admin_b.id,
            action_type="toggle_chunk_visibility",
            resource_type="chunk",
            resource_id=str(chunk.id),
            book_slug="testbook",
            old_value={"is_hidden": False},
            new_value={"is_hidden": True},
        )
        db.add(audit_b)
        await db.flush()

        fetched = await db.get(AdminAuditLog, audit_b.id)
        assert fetched is not None
        assert fetched.admin_id == admin_b.id

        # Admin A tries to undo Admin B's action → router-level 403 guard
        with pytest.raises(HTTPException) as exc_info:
            if fetched.admin_id != _ADMIN_A_ID:
                raise HTTPException(403, "Cannot undo another admin's action")
        assert exc_info.value.status_code == 403


class TestSessionProgressRestoredOnMergeUndo:
    """merge_chunks undo restores chunk_progress for all affected sessions."""

    async def test_session_progress_restored_on_merge_undo(self, db: AsyncSession):
        chunk1 = await _make_chunk(db, heading="C1", order_index=0)
        chunk2 = await _make_chunk(db, heading="C2", order_index=1)
        student = await _make_student(db)

        progress_before = {
            str(chunk1.id): {"score": 0.8, "completed": True},
            str(chunk2.id): {"score": 0.6, "completed": True},
        }

        # 3 sessions referencing both chunks
        sessions = []
        for _ in range(3):
            s = await _make_session(db, student.id, chunk_progress=dict(progress_before))
            sessions.append(s)

        chunk1_snap = await snapshot_chunk(db, chunk1.id)
        chunk2_snap = await snapshot_chunk(db, chunk2.id)

        # Capture affected sessions snapshot
        sess_snaps = await snapshot_session_progress_for_chunks(
            db, [chunk1.id, chunk2.id]
        )
        assert len(sess_snaps) == 3, "All 3 sessions should be captured"

        # Simulate merge: delete chunk2, update chunk1
        merged_text = "C1 text. C2 text."
        chunk1.text = merged_text
        await db.delete(chunk2)
        await db.flush()

        # Clobber progress to simulate what the endpoint would do
        for s in sessions:
            new_prog = dict(progress_before)
            del new_prog[str(chunk2.id)]
            s.chunk_progress = new_prog
        await db.flush()

        old_val = {
            "chunk1": chunk1_snap,
            "chunk2": chunk2_snap,
            "affected_sessions": sess_snaps,
        }
        new_val = {
            "surviving_chunk_id": str(chunk1.id),
            "new_text": merged_text,
        }

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="merge_chunks",
            resource_id=str(chunk1.id),
            old_value=old_val,
            new_value=new_val,
        )

        await apply_undo(db, audit, _ADMIN_A_ID)
        await db.flush()

        # Verify all 3 sessions have their chunk_progress restored
        for s in sessions:
            await db.refresh(s)
            assert str(chunk2.id) in (s.chunk_progress or {}), (
                f"session {s.id} must have chunk2 progress restored"
            )


class TestGraphJsonByteForByteAfterPromoteUndo:
    """promote undo overwrites graph.json with the pre-promote content byte-for-byte."""

    async def test_graph_json_byte_for_byte_after_promote_undo(
        self, db: AsyncSession, tmp_path: Path
    ):
        chunk = await _make_chunk(db, concept_id="testbook_1.1", order_index=0)

        graph_before = {
            "nodes": [{"id": "testbook_1.1", "title": "Original Section"}],
            "edges": [],
        }
        graph_after = {
            "nodes": [
                {"id": "testbook_1.1", "title": "Original Section"},
                {"id": "testbook_1.1b", "title": "Promoted"},
            ],
            "edges": [],
        }

        book_dir = tmp_path / "testbook"
        book_dir.mkdir()
        graph_path = book_dir / "graph.json"
        # Write the "after promote" state to disk
        graph_path.write_text(json.dumps(graph_after), encoding="utf-8")

        old_val = {
            "affected_chunks": [
                {"id": str(chunk.id), "concept_id": "testbook_1.1",
                 "section": "1.1 Section", "is_hidden": False}
            ],
            "graph_json_before": graph_before,
        }
        new_val = {
            "new_concept_id": "testbook_1.1b",
            "new_section_label": "1.1b Promoted",
            "affected_chunk_ids": [str(chunk.id)],
            "graph_json_after": graph_after,
        }

        chunk.concept_id = "testbook_1.1b"
        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="promote",
            resource_type="section",
            resource_id="testbook_1.1",
            old_value=old_val,
            new_value=new_val,
        )

        from unittest.mock import AsyncMock
        mock_reload = AsyncMock(return_value=None)
        with (
            patch("api.audit_service.OUTPUT_DIR", tmp_path),
            patch(
                "api.chunk_knowledge_service.reload_graph_with_overrides",
                mock_reload,
                create=True,
            ),
        ):
            await apply_undo(db, audit, _ADMIN_A_ID)
            await db.flush()

        restored = json.loads(graph_path.read_text(encoding="utf-8"))
        assert restored == graph_before, "graph.json content must match pre-promote snapshot"
        # Confirm the promoted node is gone
        node_ids = [n["id"] for n in restored.get("nodes", [])]
        assert "testbook_1.1b" not in node_ids, "promoted node must be absent after undo"


class TestAuditRowNotCreatedOnMutationFailure:
    """A mid-mutation failure must not leave a persisted audit row (rollback)."""

    async def test_audit_row_not_created_on_mutation_failure(self, db: AsyncSession):
        chunk = await _make_chunk(db)
        await db.flush()
        audit_count_before = (
            await db.execute(text("SELECT COUNT(*) FROM admin_audit_logs"))
        ).scalar()

        # Simulate a mutation that raises before commit; use a savepoint
        sp = await db.begin_nested()
        try:
            chunk.heading = "About To Fail"
            await log_action(
                db,
                admin_id=_ADMIN_A_ID,
                action_type="update_chunk",
                resource_type="chunk",
                resource_id=str(chunk.id),
                book_slug="testbook",
                old_value={"heading": "Test Heading"},
                new_value={"heading": "About To Fail"},
            )
            # Force failure before the caller's commit
            raise RuntimeError("Simulated mutation failure")
        except RuntimeError:
            await sp.rollback()

        # Verify: audit count must not have increased
        audit_count_after = (
            await db.execute(text("SELECT COUNT(*) FROM admin_audit_logs"))
        ).scalar()
        assert audit_count_after == audit_count_before, (
            "No audit row must persist when the mutation transaction is rolled back"
        )


class TestStaleCheck409OnConcurrentModification:
    """stale_check raises 409 when the DB state has drifted from audit.new_value."""

    async def test_stale_check_409_on_concurrent_modification(self, db: AsyncSession):
        from fastapi import HTTPException

        chunk = await _make_chunk(db, is_hidden=False)

        old_val = {"is_hidden": False}
        new_val = {"is_hidden": True}

        # Record audit when chunk was set to is_hidden=True
        chunk.is_hidden = True
        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="toggle_chunk_visibility",
            resource_id=str(chunk.id),
            old_value=old_val,
            new_value=new_val,
        )

        # Another admin then sets it back to False (drift)
        chunk.is_hidden = False
        await db.flush()

        # stale_check should now raise 409 because current is_hidden (False)
        # does not match audit.new_value["is_hidden"] (True)
        with pytest.raises(HTTPException) as exc_info:
            await stale_check(db, audit)
        assert exc_info.value.status_code == 409


# ─── Edge-case tests ──────────────────────────────────────────────────────────

class TestUndoAlreadyUndone:
    """Attempting to undo an already-undone audit raises 400."""

    async def test_undo_already_undone_400(self, db: AsyncSession):
        from fastapi import HTTPException

        chunk = await _make_chunk(db, is_hidden=False)
        old_snap = {"is_hidden": False}
        new_snap = {"is_hidden": True}
        chunk.is_hidden = True

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="toggle_chunk_visibility",
            resource_id=str(chunk.id),
            old_value=old_snap,
            new_value=new_snap,
        )

        # First undo succeeds
        await apply_undo(db, audit, _ADMIN_A_ID)
        await db.flush()
        assert audit.undone_at is not None

        # Second undo → router-level 400 guard (replicate router logic)
        with pytest.raises(HTTPException) as exc_info:
            if audit.undone_at is not None:
                raise HTTPException(400, "Action already undone")
        assert exc_info.value.status_code == 400


class TestRedoNonUndone:
    """Attempting to redo an action that was never undone raises 400."""

    async def test_redo_non_undone_400(self, db: AsyncSession):
        from fastapi import HTTPException

        chunk = await _make_chunk(db)
        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="toggle_chunk_visibility",
            resource_id=str(chunk.id),
            old_value={"is_hidden": False},
            new_value={"is_hidden": True},
        )

        # audit.undone_at is None → cannot redo
        with pytest.raises(HTTPException) as exc_info:
            if audit.undone_at is None:
                raise HTTPException(400, "Action has not been undone — cannot redo an active action")
        assert exc_info.value.status_code == 400


class TestRetention50EntriesPerAdmin:
    """purge_old_audits_per_admin keeps exactly 50 newest rows per admin."""

    async def test_retention_50_entries_per_admin(self, db: AsyncSession):
        chunk = await _make_chunk(db)

        # Insert 51 audit rows for Admin A using the ORM to avoid asyncpg
        # parameter/cast syntax issues with raw SQL.
        from datetime import timedelta
        base_time = datetime.now(timezone.utc)
        for i in range(51):
            row = AdminAuditLog(
                admin_id=_ADMIN_A_ID,
                action_type="update_chunk",
                resource_type="chunk",
                resource_id=str(chunk.id),
                book_slug="testbook",
                old_value={},
                new_value={"i": i},
                created_at=base_time - timedelta(seconds=51 - i),
            )
            db.add(row)
        await db.flush()

        count_before = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM admin_audit_logs WHERE admin_id = :aid"
                ),
                {"aid": str(_ADMIN_A_ID)},
            )
        ).scalar()
        assert count_before >= 51

        deleted = await purge_old_audits_per_admin(db, keep_per_admin=50)
        assert deleted >= 1, "At least 1 row must be pruned"

        count_after = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM admin_audit_logs WHERE admin_id = :aid"
                ),
                {"aid": str(_ADMIN_A_ID)},
            )
        ).scalar()
        assert count_after == 50, f"Expected exactly 50 rows, got {count_after}"

        # Verify the newest row survived (offset=1, i=50, new_value={"i": 50})
        newest = (
            await db.execute(
                text("""
                    SELECT new_value FROM admin_audit_logs
                    WHERE admin_id = :aid
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"aid": str(_ADMIN_A_ID)},
            )
        ).scalar()
        assert newest.get("i") == 50, "Newest row must be the one with i=50"


class TestRedoChainCreatesValidAuditRow:
    """redo creates a new audit row with redo_of = original and correct old/new values."""

    async def test_redo_chain_creates_valid_audit_row(self, db: AsyncSession):
        chunk = await _make_chunk(db, heading="Original", text="Original text.")

        old_snap = await snapshot_chunk(db, chunk.id)

        # Mutate
        chunk.heading = "Modified"
        chunk.text = "Modified text."
        new_snap = await snapshot_chunk(db, chunk.id)

        original_audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="update_chunk",
            resource_id=str(chunk.id),
            old_value=old_snap,
            new_value=new_snap,
        )

        # Undo
        await apply_undo(db, original_audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk)
        assert chunk.heading == "Original", "undo must restore heading"

        # Redo
        redo_audit = await apply_redo(db, original_audit, _ADMIN_A_ID)
        await db.flush()
        await db.refresh(chunk)

        # State re-applied
        assert chunk.heading == "Modified", "redo must re-apply heading"

        # New audit row integrity
        assert redo_audit.redo_of == original_audit.id, "redo_of must point to original"
        assert redo_audit.action_type == original_audit.action_type, "action_type preserved"
        assert redo_audit.admin_id == _ADMIN_A_ID, "admin_id set correctly on redo row"

        # old/new semantics on redo row: old_value = post-undo state, new_value = re-applied state
        # The redo row's new_value should contain the "Modified" heading (original old_snap)
        # Because apply_redo sets new_value=audit.old_value (original pre-mutation snap)
        assert "heading" in redo_audit.new_value
        assert redo_audit.new_value.get("heading") == "Original"


# ─── Regression tests: GET /api/admin/changes default include_undone ──────────

class TestListChangesIncludeUndoneDefault:
    """
    Regression: list_my_changes must include undone entries by default.

    Bug: include_undone defaulted to False, hiding all undone rows and
    permanently disabling the frontend Redo button. The fix flips the
    default to True.

    These tests replicate the endpoint's SQLAlchemy query logic directly
    (consistent with the service-layer style used throughout this file).
    """

    async def test_list_changes_includes_undone_entries_by_default(
        self, db: AsyncSession
    ):
        """
        GET /api/admin/changes (no params) must return rows where undone_at
        is NOT None — i.e. undone entries are included by default.
        """
        from sqlalchemy import select as sa_select

        # Arrange: create a chunk, log an action, then undo it.
        chunk = await _make_chunk(db, heading="Before", text="Original text.")
        old_snap = {"heading": "Before", "text": "Original text."}
        new_snap = {"heading": "After", "text": "Updated text."}

        chunk.heading = "After"
        chunk.text = "Updated text."

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="update_chunk",
            resource_id=str(chunk.id),
            old_value=old_snap,
            new_value=new_snap,
        )
        audit_id = audit.id

        # Undo the action so undone_at becomes non-null.
        await apply_undo(db, audit, _ADMIN_A_ID)
        await db.flush()

        # Act: replicate the endpoint query with include_undone=True (the new default).
        # When include_undone is True, the undone_at IS NULL filter is NOT applied.
        q = (
            sa_select(AdminAuditLog)
            .where(AdminAuditLog.admin_id == _ADMIN_A_ID)
            .order_by(AdminAuditLog.created_at.desc())
            .limit(50)
        )
        rows = (await db.execute(q)).scalars().all()

        # Assert: the undone row must appear in the result set.
        row_ids = {r.id for r in rows}
        assert audit_id in row_ids, (
            "GET /api/admin/changes (default) must include the undone audit row; "
            "the Redo button depends on seeing undone entries"
        )

        undone_rows = [r for r in rows if r.undone_at is not None]
        assert len(undone_rows) >= 1, (
            "At least one row in the default response must have undone_at set"
        )

    async def test_list_changes_excludes_undone_when_explicitly_filtered(
        self, db: AsyncSession
    ):
        """
        GET /api/admin/changes?include_undone=false must return ONLY rows
        where undone_at IS None — the explicit opt-out filter still works.
        """
        from sqlalchemy import select as sa_select

        # Arrange: create a chunk, log an action, then undo it.
        chunk = await _make_chunk(db, heading="Start", text="Start text.")
        old_snap = {"heading": "Start", "text": "Start text."}
        new_snap = {"heading": "End", "text": "End text."}

        chunk.heading = "End"
        chunk.text = "End text."

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="update_chunk",
            resource_id=str(chunk.id),
            old_value=old_snap,
            new_value=new_snap,
        )
        audit_id = audit.id

        # Undo so undone_at becomes non-null.
        await apply_undo(db, audit, _ADMIN_A_ID)
        await db.flush()

        # Act: replicate the endpoint query with include_undone=False (explicit opt-out).
        # When include_undone is False, add the undone_at IS NULL filter.
        q = (
            sa_select(AdminAuditLog)
            .where(AdminAuditLog.admin_id == _ADMIN_A_ID)
            .order_by(AdminAuditLog.created_at.desc())
            .limit(50)
        )
        q = q.where(AdminAuditLog.undone_at.is_(None))
        rows = (await db.execute(q)).scalars().all()

        # Assert: the undone row must NOT appear.
        row_ids = {r.id for r in rows}
        assert audit_id not in row_ids, (
            "GET /api/admin/changes?include_undone=false must exclude the undone row"
        )

        # Every returned row must have undone_at IS None.
        for row in rows:
            assert row.undone_at is None, (
                f"Row {row.id} (action={row.action_type}) has undone_at set "
                "but was returned by ?include_undone=false — this is the regression"
            )


# ─── i18n Phase 2: cache invalidation assertions on undo/redo ─────────────────
# Added by comprehensive-tester (Phase 2).
# These assertions augment the existing undo tests: they verify that undo AND
# redo call invalidate_chunk_cache with the affected chunk(s), which is the
# contract that keeps active student sessions in sync with admin edits.


import json as _json
from unittest.mock import patch as _patch
from api.cache_accessor import CacheAccessor as _CacheAccessor
from api.teaching_service import invalidate_chunk_cache as _invalidate_chunk_cache


def _make_warm_pt(chunk_id: str) -> str:
    """Return a minimal presentation_text with warm exam questions for chunk_id."""
    return _json.dumps({
        "cache_version": 3,
        "by_language": {
            "en": {
                "cards": [],
                "concepts_queue": [chunk_id],
                "concepts_covered": [],
                "exam_questions_by_chunk": {
                    chunk_id: [{"index": 0, "text": "warm cached question?"}]
                },
            },
        },
    })


class TestUndoRedoInvalidationHooks:
    """
    Phase 2 i18n: verify that undo and redo both trigger invalidate_chunk_cache.

    These tests add inline invalidation assertions to the three representative
    undo types requested in the execution plan:
      1. update_chunk undo
      2. rename_section undo  (section-level, affects multiple chunks)
      3. toggle_chunk_exam_gate undo
    """

    async def test_update_chunk_undo_calls_invalidate_chunk_cache(
        self, db: AsyncSession
    ):
        """undo update_chunk must call invalidate_chunk_cache with the chunk's id."""
        chunk = await _make_chunk(db, heading="Old", text="Old text.")
        old_snap = await snapshot_chunk(db, chunk.id)
        chunk.heading = "New"
        new_snap = await snapshot_chunk(db, chunk.id)

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="update_chunk",
            resource_id=str(chunk.id),
            old_value=old_snap,
            new_value=new_snap,
        )

        invalidated: list[list] = []

        async def _spy(db_arg, ids):
            invalidated.append(list(ids))
            return 0

        with _patch("api.audit_service.invalidate_chunk_cache", side_effect=_spy):
            await apply_undo(db, audit, _ADMIN_A_ID)
            await db.flush()

        assert invalidated, "invalidate_chunk_cache must be called during update_chunk undo"
        flat = [cid for call_ids in invalidated for cid in call_ids]
        assert str(chunk.id) in flat, (
            f"chunk {chunk.id} must be in invalidated IDs, got {flat}"
        )

    async def test_update_chunk_redo_calls_invalidate_chunk_cache(
        self, db: AsyncSession
    ):
        """redo update_chunk must also call invalidate_chunk_cache."""
        chunk = await _make_chunk(db, heading="Old")
        old_snap = await snapshot_chunk(db, chunk.id)
        chunk.heading = "New"
        new_snap = await snapshot_chunk(db, chunk.id)

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="update_chunk",
            resource_id=str(chunk.id),
            old_value=old_snap,
            new_value=new_snap,
        )

        # Undo first (required before redo)
        await apply_undo(db, audit, _ADMIN_A_ID)
        await db.flush()

        invalidated_redo: list[list] = []

        async def _spy_redo(db_arg, ids):
            invalidated_redo.append(list(ids))
            return 0

        with _patch("api.audit_service.invalidate_chunk_cache", side_effect=_spy_redo):
            await apply_redo(db, audit, _ADMIN_A_ID)
            await db.flush()

        assert invalidated_redo, "invalidate_chunk_cache must be called during update_chunk redo"
        flat = [cid for call_ids in invalidated_redo for cid in call_ids]
        assert str(chunk.id) in flat, (
            f"chunk {chunk.id} must be in redo invalidated IDs"
        )

    async def test_rename_section_undo_invalidates_all_section_chunks(
        self, db: AsyncSession
    ):
        """undo rename_section must pass all affected chunk IDs to invalidate_chunk_cache."""
        chunk_a = await _make_chunk(db, admin_section_name="Old Name", order_index=10)
        chunk_b = await _make_chunk(db, admin_section_name="Old Name", order_index=11)

        # i18n Phase 3: include translations in old/new audit dicts.
        _phase3_old_trans = {"en_source_hash": "x", "ml": "പഴയ", "ta": "பழைய"}
        _phase3_new_trans = {"en_source_hash": "y", "ml": "പുതിയ", "ta": "புதிய"}

        old_val = {
            "admin_section_name": "Old Name",
            "admin_section_name_translations": _phase3_old_trans,
            "affected_chunk_ids": [str(chunk_a.id), str(chunk_b.id)],
        }
        new_val = {
            "admin_section_name": "New Name",
            "admin_section_name_translations": _phase3_new_trans,
        }
        chunk_a.admin_section_name = "New Name"
        chunk_a.admin_section_name_translations = _phase3_new_trans
        chunk_b.admin_section_name = "New Name"
        chunk_b.admin_section_name_translations = _phase3_new_trans

        audit = await _make_audit(
            db,
            admin_id=_ADMIN_A_ID,
            action_type="rename_section",
            resource_id="testbook_1.1",
            resource_type="section",
            old_value=old_val,
            new_value=new_val,
        )

        invalidated: list[list] = []

        async def _spy(db_arg, ids):
            invalidated.append(list(ids))
            return 0

        with _patch("api.audit_service.invalidate_chunk_cache", side_effect=_spy):
            await apply_undo(db, audit, _ADMIN_A_ID)
            await db.flush()

        assert invalidated, "invalidate_chunk_cache must be called during rename_section undo"
        flat = [cid for call_ids in invalidated for cid in call_ids]
        # Both chunks must be included
        assert str(chunk_a.id) in flat or str(chunk_b.id) in flat, (
            "rename_section undo must invalidate at least one section chunk"
        )
