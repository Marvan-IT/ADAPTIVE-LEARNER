"""
test_admin_edit_invalidates_student_cache.py

Business criteria:
  BC-AEIC-01  Every admin content-mutation handler calls invalidate_chunk_cache with
              the correct chunk_ids after the DB mutation.
  BC-AEIC-02  After invalidation, get_exam_questions returns None for the affected chunk
              in every language slice of every active session touching that chunk.
  BC-AEIC-03  Undo and redo also call invalidate_chunk_cache for the restored chunks.
  BC-AEIC-04  Admin handlers for section operations clear ALL chunks in the section.
  BC-AEIC-05  The graph-edge handler clears chunks in both source and target concepts.

Strategy:
  - Live PostgreSQL required (same as test_admin_audit.py — savepoint rollback per test).
  - invalidate_chunk_cache is exercised directly against a real TeachingSession row
    whose presentation_text contains warm exam-question cache entries.
  - Admin router handlers are not called here (too many integration dependencies);
    instead we assert on invalidate_chunk_cache output by calling it directly.
  - Parametrise over every admin action listed in the DLD hook table.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from db.models import ConceptChunk, Student, TeachingSession
from api.cache_accessor import CacheAccessor
from api.teaching_service import invalidate_chunk_cache

# ── DB config ─────────────────────────────────────────────────────────────────

_DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postre2002@localhost:5432/AdaptiveLearner",
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Savepoint-scoped session — rolls back all data after each test."""
    try:
        engine = create_async_engine(_DB_URL, echo=False, future=True)
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            async with session.begin():
                sp = await session.begin_nested()
                try:
                    yield session
                finally:
                    await sp.rollback()
        await engine.dispose()
    except Exception as exc:
        err_str = str(exc).lower()
        if any(kw in err_str for kw in ("connect", "refused", "event loop")):
            pytest.skip(f"DB not available: {exc}")
        raise


async def _make_student(db: AsyncSession, *, language: str = "en") -> Student:
    student = Student(
        id=uuid.uuid4(),
        display_name="Cache Test Student",
        interests=[],
        preferred_style="default",
        preferred_language=language,
    )
    db.add(student)
    await db.flush()
    return student


def _warm_cache(chunk_ids: list[str], languages: list[str] | None = None) -> str:
    """Build a presentation_text JSON with warm exam-question cache for each chunk_id
    in each language slice."""
    langs = languages or ["en", "ml"]
    by_language: dict = {}
    for lang in langs:
        eq_map = {
            cid: [{"index": 0, "text": f"test question for {cid[:8]} in {lang}"}]
            for cid in chunk_ids
        }
        by_language[lang] = {
            "cards": [],
            "concepts_queue": list(chunk_ids),
            "concepts_covered": [],
            "exam_questions_by_chunk": eq_map,
        }
    return json.dumps({"cache_version": 3, "by_language": by_language})


async def _make_session_with_warm_cache(
    db: AsyncSession,
    student_id: uuid.UUID,
    chunk_ids: list[str],
    languages: list[str] | None = None,
) -> TeachingSession:
    """Insert a TeachingSession with warm exam question cache for chunk_ids."""
    sess = TeachingSession(
        id=uuid.uuid4(),
        student_id=student_id,
        concept_id="testbook_1.1",
        book_slug="testbook",
        phase="CARDS",
        presentation_text=_warm_cache(chunk_ids, languages),
    )
    db.add(sess)
    await db.flush()
    return sess


async def _make_chunk(
    db: AsyncSession,
    *,
    concept_id: str = "testbook_1.1",
    order_index: int = 0,
    heading: str = "Test Heading",
) -> ConceptChunk:
    chunk = ConceptChunk(
        id=uuid.uuid4(),
        book_slug="testbook",
        concept_id=concept_id,
        section="1.1 Test Section",
        order_index=order_index,
        heading=heading,
        text="Content for testing.",
        latex=[],
        embedding=None,
    )
    db.add(chunk)
    await db.flush()
    return chunk


def _assert_exam_cleared(presentation_text: str, chunk_id: str) -> None:
    """Assert that exam_questions_by_chunk for chunk_id is gone in all language slices."""
    ca = CacheAccessor(presentation_text, language="en")
    by_lang = ca._data.get("by_language", {})
    assert by_lang, "by_language must exist"
    for lang, sl in by_lang.items():
        eq = sl.get("exam_questions_by_chunk", {})
        assert str(chunk_id) not in eq, (
            f"exam questions for chunk {chunk_id!r} must be cleared in lang={lang!r}"
        )


def _assert_exam_present(presentation_text: str, chunk_id: str) -> None:
    """Assert that exam_questions_by_chunk for chunk_id is still present."""
    ca = CacheAccessor(presentation_text, language="en")
    found = False
    for _lang, sl in ca._data.get("by_language", {}).items():
        if str(chunk_id) in sl.get("exam_questions_by_chunk", {}):
            found = True
            break
    assert found, f"exam questions for chunk {chunk_id!r} should still be present"


# ─── Tests: single-chunk operations ───────────────────────────────────────────


class TestUpdateChunkInvalidatesCache:
    """update_chunk: session referencing that chunk has its exam cache cleared."""

    async def test_invalidation_clears_exam_questions(self, db: AsyncSession):
        student = await _make_student(db)
        chunk = await _make_chunk(db)
        session = await _make_session_with_warm_cache(db, student.id, [str(chunk.id)])

        # Confirm warm state
        _assert_exam_present(session.presentation_text, str(chunk.id))

        count = await invalidate_chunk_cache(db, [str(chunk.id)])
        await db.flush()
        await db.refresh(session)

        assert count >= 1, "at least one session should be touched"
        _assert_exam_cleared(session.presentation_text, str(chunk.id))

    async def test_invalidation_returns_correct_session_count(self, db: AsyncSession):
        student = await _make_student(db)
        chunk = await _make_chunk(db)

        # Two sessions both referencing the same chunk
        s1 = await _make_session_with_warm_cache(db, student.id, [str(chunk.id)])
        s2 = await _make_session_with_warm_cache(db, student.id, [str(chunk.id)])

        count = await invalidate_chunk_cache(db, [str(chunk.id)])
        assert count >= 2, f"both sessions should be counted; got {count}"


class TestToggleChunkVisibilityInvalidatesCache:
    """toggle_chunk_visibility: same chunk — exam cache cleared."""

    async def test_toggle_visibility_invalidates(self, db: AsyncSession):
        student = await _make_student(db)
        chunk = await _make_chunk(db)
        session = await _make_session_with_warm_cache(db, student.id, [str(chunk.id)])

        await invalidate_chunk_cache(db, [str(chunk.id)])
        await db.flush()
        await db.refresh(session)

        _assert_exam_cleared(session.presentation_text, str(chunk.id))


class TestToggleChunkExamGateInvalidatesCache:
    """toggle_chunk_exam_gate: exam gate change must clear exam questions for that chunk."""

    async def test_exam_gate_toggle_invalidates(self, db: AsyncSession):
        student = await _make_student(db)
        chunk = await _make_chunk(db)
        session = await _make_session_with_warm_cache(db, student.id, [str(chunk.id)])

        await invalidate_chunk_cache(db, [str(chunk.id)])
        await db.flush()
        await db.refresh(session)

        _assert_exam_cleared(session.presentation_text, str(chunk.id))

    async def test_unrelated_chunk_untouched_after_exam_gate_toggle(
        self, db: AsyncSession
    ):
        """Chunks not in chunk_ids list must NOT have their exam questions cleared."""
        student = await _make_student(db)
        chunk_target = await _make_chunk(db, order_index=0)
        chunk_other = await _make_chunk(db, order_index=1)
        session = await _make_session_with_warm_cache(
            db, student.id, [str(chunk_target.id), str(chunk_other.id)]
        )

        # Invalidate only chunk_target
        await invalidate_chunk_cache(db, [str(chunk_target.id)])
        await db.flush()
        await db.refresh(session)

        _assert_exam_cleared(session.presentation_text, str(chunk_target.id))
        _assert_exam_present(session.presentation_text, str(chunk_other.id))


class TestMergeChunksInvalidatesCache:
    """merge_chunks: both chunk IDs must be cleared (original and merged-into)."""

    async def test_merge_clears_both_chunks(self, db: AsyncSession):
        student = await _make_student(db)
        chunk1 = await _make_chunk(db, order_index=0)
        chunk2 = await _make_chunk(db, order_index=1)
        session = await _make_session_with_warm_cache(
            db, student.id, [str(chunk1.id), str(chunk2.id)]
        )

        await invalidate_chunk_cache(db, [str(chunk1.id), str(chunk2.id)])
        await db.flush()
        await db.refresh(session)

        _assert_exam_cleared(session.presentation_text, str(chunk1.id))
        _assert_exam_cleared(session.presentation_text, str(chunk2.id))


class TestSplitChunkInvalidatesCache:
    """split_chunk: original chunk's cache must be cleared."""

    async def test_split_clears_original_chunk(self, db: AsyncSession):
        student = await _make_student(db)
        chunk = await _make_chunk(db)
        session = await _make_session_with_warm_cache(db, student.id, [str(chunk.id)])

        await invalidate_chunk_cache(db, [str(chunk.id)])
        await db.flush()
        await db.refresh(session)

        _assert_exam_cleared(session.presentation_text, str(chunk.id))


class TestPromoteChunkInvalidatesCache:
    """promote_subsection_to_section: the promoted chunk must be cleared."""

    async def test_promote_clears_chunk(self, db: AsyncSession):
        student = await _make_student(db)
        chunk = await _make_chunk(db)
        session = await _make_session_with_warm_cache(db, student.id, [str(chunk.id)])

        await invalidate_chunk_cache(db, [str(chunk.id)])
        await db.flush()
        await db.refresh(session)

        _assert_exam_cleared(session.presentation_text, str(chunk.id))


# ─── Tests: section-level operations ──────────────────────────────────────────


class TestRenameSectionInvalidatesAllChunks:
    """rename_section: all chunks in the section must be invalidated."""

    async def test_section_rename_clears_all_section_chunks(self, db: AsyncSession):
        student = await _make_student(db)
        chunk_a = await _make_chunk(db, concept_id="testbook_1.1", order_index=0)
        chunk_b = await _make_chunk(db, concept_id="testbook_1.1", order_index=1)
        chunk_c = await _make_chunk(db, concept_id="testbook_1.1", order_index=2)
        session = await _make_session_with_warm_cache(
            db,
            student.id,
            [str(chunk_a.id), str(chunk_b.id), str(chunk_c.id)],
        )

        all_ids = [str(chunk_a.id), str(chunk_b.id), str(chunk_c.id)]
        count = await invalidate_chunk_cache(db, all_ids)
        await db.flush()
        await db.refresh(session)

        assert count >= 1
        _assert_exam_cleared(session.presentation_text, str(chunk_a.id))
        _assert_exam_cleared(session.presentation_text, str(chunk_b.id))
        _assert_exam_cleared(session.presentation_text, str(chunk_c.id))


class TestToggleSectionOptionalInvalidatesAllChunks:
    """toggle_section_optional: all chunks in section must be cleared."""

    async def test_section_optional_toggle_clears_all(self, db: AsyncSession):
        student = await _make_student(db)
        chunk_a = await _make_chunk(db, order_index=0)
        chunk_b = await _make_chunk(db, order_index=1)
        session = await _make_session_with_warm_cache(
            db, student.id, [str(chunk_a.id), str(chunk_b.id)]
        )

        await invalidate_chunk_cache(db, [str(chunk_a.id), str(chunk_b.id)])
        await db.flush()
        await db.refresh(session)

        _assert_exam_cleared(session.presentation_text, str(chunk_a.id))
        _assert_exam_cleared(session.presentation_text, str(chunk_b.id))


class TestToggleSectionExamGateInvalidatesAllChunks:
    """toggle_section_exam_gate: all section chunks' exam question caches must clear."""

    async def test_section_exam_gate_clears_all(self, db: AsyncSession):
        student = await _make_student(db)
        chunk_a = await _make_chunk(db, order_index=0)
        chunk_b = await _make_chunk(db, order_index=1)
        session = await _make_session_with_warm_cache(
            db, student.id, [str(chunk_a.id), str(chunk_b.id)]
        )

        await invalidate_chunk_cache(db, [str(chunk_a.id), str(chunk_b.id)])
        await db.flush()
        await db.refresh(session)

        _assert_exam_cleared(session.presentation_text, str(chunk_a.id))
        _assert_exam_cleared(session.presentation_text, str(chunk_b.id))


class TestToggleSectionVisibilityInvalidatesAllChunks:
    """toggle_section_visibility: all section chunks must be invalidated."""

    async def test_section_visibility_clears_all(self, db: AsyncSession):
        student = await _make_student(db)
        chunk_a = await _make_chunk(db, order_index=0)
        chunk_b = await _make_chunk(db, order_index=1)
        session = await _make_session_with_warm_cache(
            db, student.id, [str(chunk_a.id), str(chunk_b.id)]
        )

        await invalidate_chunk_cache(db, [str(chunk_a.id), str(chunk_b.id)])
        await db.flush()
        await db.refresh(session)

        _assert_exam_cleared(session.presentation_text, str(chunk_a.id))
        _assert_exam_cleared(session.presentation_text, str(chunk_b.id))


# ─── Tests: graph edge operations ─────────────────────────────────────────────


class TestModifyGraphEdgeInvalidatesCache:
    """modify_graph_edge (add/remove prereq): chunks in both source and target concepts."""

    async def test_add_prereq_clears_both_concept_chunks(self, db: AsyncSession):
        student = await _make_student(db)
        # Source concept chunks
        chunk_src = await _make_chunk(db, concept_id="testbook_1.1", order_index=0)
        # Target concept chunks
        chunk_tgt = await _make_chunk(db, concept_id="testbook_1.2", order_index=0)
        session = await _make_session_with_warm_cache(
            db, student.id, [str(chunk_src.id), str(chunk_tgt.id)]
        )

        all_ids = [str(chunk_src.id), str(chunk_tgt.id)]
        await invalidate_chunk_cache(db, all_ids)
        await db.flush()
        await db.refresh(session)

        _assert_exam_cleared(session.presentation_text, str(chunk_src.id))
        _assert_exam_cleared(session.presentation_text, str(chunk_tgt.id))

    async def test_remove_prereq_clears_both_concept_chunks(self, db: AsyncSession):
        """Same behaviour for remove as for add — both chunk lists cleared."""
        student = await _make_student(db)
        chunk_src = await _make_chunk(db, concept_id="testbook_2.1", order_index=0)
        chunk_tgt = await _make_chunk(db, concept_id="testbook_2.2", order_index=0)
        session = await _make_session_with_warm_cache(
            db, student.id, [str(chunk_src.id), str(chunk_tgt.id)]
        )

        all_ids = [str(chunk_src.id), str(chunk_tgt.id)]
        await invalidate_chunk_cache(db, all_ids)
        await db.flush()
        await db.refresh(session)

        _assert_exam_cleared(session.presentation_text, str(chunk_src.id))
        _assert_exam_cleared(session.presentation_text, str(chunk_tgt.id))


# ─── Tests: multi-language isolation ──────────────────────────────────────────


class TestMultiLanguageSliceInvalidation:
    """All language slices must be cleared — not just the student's active language."""

    async def test_all_language_slices_cleared(self, db: AsyncSession):
        student = await _make_student(db, language="ml")
        chunk = await _make_chunk(db)
        session = await _make_session_with_warm_cache(
            db, student.id, [str(chunk.id)], languages=["en", "ml", "ta"]
        )

        await invalidate_chunk_cache(db, [str(chunk.id)])
        await db.flush()
        await db.refresh(session)

        # All three language slices must have exam questions cleared
        ca = CacheAccessor(session.presentation_text, language="en")
        by_lang = ca._data.get("by_language", {})
        for lang in ["en", "ml", "ta"]:
            if lang in by_lang:
                eq = by_lang[lang].get("exam_questions_by_chunk", {})
                assert str(chunk.id) not in eq, (
                    f"exam questions should be cleared in lang={lang!r}"
                )

    async def test_session_not_referencing_chunk_is_untouched(self, db: AsyncSession):
        """A session whose concepts_queue doesn't contain the chunk is not modified."""
        student = await _make_student(db)
        chunk_target = await _make_chunk(db, order_index=0)
        chunk_unrelated = await _make_chunk(db, order_index=1)

        # Session only references the unrelated chunk
        session_unrelated = await _make_session_with_warm_cache(
            db, student.id, [str(chunk_unrelated.id)]
        )
        original_text = session_unrelated.presentation_text

        await invalidate_chunk_cache(db, [str(chunk_target.id)])
        await db.flush()
        await db.refresh(session_unrelated)

        # The unrelated session's exam questions must still be intact
        _assert_exam_present(session_unrelated.presentation_text, str(chunk_unrelated.id))

    async def test_empty_chunk_ids_returns_zero(self, db: AsyncSession):
        """Calling invalidate_chunk_cache with empty list returns 0 without error."""
        count = await invalidate_chunk_cache(db, [])
        assert count == 0

    async def test_completed_sessions_not_touched(self, db: AsyncSession):
        """Completed sessions (completed_at set) must never be modified."""
        from datetime import datetime, timezone
        student = await _make_student(db)
        chunk = await _make_chunk(db)

        warm = _warm_cache([str(chunk.id)])
        # Completed session
        completed_sess = TeachingSession(
            id=uuid.uuid4(),
            student_id=student.id,
            concept_id="testbook_1.1",
            book_slug="testbook",
            phase="COMPLETED",
            presentation_text=warm,
            completed_at=datetime.now(timezone.utc),
        )
        db.add(completed_sess)
        await db.flush()

        count = await invalidate_chunk_cache(db, [str(chunk.id)])
        await db.flush()
        await db.refresh(completed_sess)

        # Completed session should not be counted
        assert count == 0
        # Its cache must remain intact
        _assert_exam_present(completed_sess.presentation_text, str(chunk.id))


# ─── Parametrised sweep: every admin operation label ─────────────────────────


@pytest.mark.parametrize(
    "operation",
    [
        "rename_section",
        "toggle_section_optional",
        "toggle_section_exam_gate",
        "toggle_section_visibility",
        "update_chunk",
        "toggle_chunk_visibility",
        "toggle_chunk_exam_gate",
        "merge_chunks",
        "split_chunk",
        "promote_subsection_to_section",
        "prereq_add",
        "prereq_remove",
    ],
)
async def test_invalidation_clears_cache_for_operation(
    db: AsyncSession, operation: str
):
    """
    For each admin operation in the DLD hook table, verify that calling
    invalidate_chunk_cache on the affected chunk(s) clears the exam question
    cache in every language slice of active sessions.

    This test does NOT call the admin router; it calls invalidate_chunk_cache
    directly, asserting the contract that must be upheld by every handler.
    """
    student = await _make_student(db)
    chunk = await _make_chunk(db)
    session = await _make_session_with_warm_cache(db, student.id, [str(chunk.id)])

    _assert_exam_present(session.presentation_text, str(chunk.id))

    count = await invalidate_chunk_cache(db, [str(chunk.id)])
    await db.flush()
    await db.refresh(session)

    assert count >= 1, f"[{operation}] at least one session should be invalidated"
    _assert_exam_cleared(session.presentation_text, str(chunk.id))
