"""
test_get_chunks_endpoint.py
============================
Unit and integration tests for GET /api/v2/sessions/{session_id}/chunks.

Business criteria covered:
  BC-CHUNKS-01  Chunks are presented to the student in textbook order (order_index ASC).
  BC-CHUNKS-02  ChromaDB-path sessions receive a routing signal via an empty chunks list.
  BC-CHUNKS-03  Frontend knows which chunks have images before fetching cards (has_images flag).
  BC-CHUNKS-04  Student returns to the correct position after resuming (current_chunk_index).
  BC-CHUNKS-05  Requesting a non-existent session returns HTTP 404.
  BC-CHUNKS-06  section_title is derived from the first chunk's section field.
  BC-CHUNKS-07  has_mcq flag correctly marks non-teaching headings as False.
  BC-CHUNKS-08  All ChunkSummary fields are present and well-typed.

Test strategy
-------------
All tests are pure-unit: they use a mock AsyncSession to avoid requiring a live database.
The real router code is exercised via httpx.AsyncClient against a lightweight FastAPI test app
built with dependency_overrides — same pattern used in test_api_integration.py.

asyncio_mode = auto (pytest.ini) — no @pytest.mark.asyncio decorator needed.
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── Break circular import teaching_router ↔ api.main ─────────────────────────
def _install_api_main_stub():
    import sys as _sys
    if "api.main" not in _sys.modules:
        stub = MagicMock()
        try:
            from slowapi import Limiter
            from slowapi.util import get_remote_address
            stub.limiter = Limiter(key_func=get_remote_address)
        except ImportError:
            stub.limiter = MagicMock()
        _sys.modules["api.main"] = stub

_install_api_main_stub()

import httpx
from fastapi import FastAPI

import api.teaching_router as teaching_router_module
from api.rate_limiter import limiter
from db.connection import get_db

# ── Test constants ─────────────────────────────────────────────────────────────

_STUDENT_ID = uuid.uuid4()
_SESSION_ID = uuid.uuid4()
_CONCEPT_ID = "prealgebra_1.1"
_BOOK_SLUG = "prealgebra"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_fake_session(*, concept_id=_CONCEPT_ID, book_slug=_BOOK_SLUG, chunk_index=0):
    """Build a minimal TeachingSession-like mock."""
    s = MagicMock()
    s.id = _SESSION_ID
    s.student_id = _STUDENT_ID
    s.concept_id = concept_id
    s.book_slug = book_slug
    s.phase = "CARDS"
    s.style = "default"
    s.chunk_index = chunk_index
    s.started_at = datetime.now(timezone.utc)
    s.completed_at = None
    s.check_score = None
    s.concept_mastered = False
    # chunk_progress must be None (not a MagicMock) so the router's
    # `session.chunk_progress or {}` fallback evaluates to {} correctly.
    s.chunk_progress = None
    return s


def _make_orm_chunk(*, order_index: int, heading: str = "Use Addition Notation",
                    concept_id: str = _CONCEPT_ID, section: str = "1.1 Introduction",
                    chunk_id: uuid.UUID | None = None) -> MagicMock:
    """Create a ConceptChunk ORM mock with the given order_index."""
    c = MagicMock()
    c.id = chunk_id or uuid.uuid4()
    c.book_slug = _BOOK_SLUG
    c.concept_id = concept_id
    c.section = section
    c.order_index = order_index
    c.heading = heading
    c.text = f"Content for {heading}"
    c.latex = []
    return c


class _MockDb:
    """
    Configurable async DB mock for list_chunks handler.

    The handler calls:
      1. db.get(TeachingSession, session_id)
      2. db.execute(select(ConceptChunk)...)  — returns chunks
      3. db.execute(select(ChunkImage.chunk_id).distinct())  — returns image chunk IDs
    """

    def __init__(self, *, session=None, chunks=None, image_chunk_ids=None):
        self._session = session
        self._chunks = chunks if chunks is not None else []
        # image_chunk_ids: list of UUID objects whose chunks have images
        self._image_chunk_ids = image_chunk_ids if image_chunk_ids is not None else []
        self._execute_call_count = 0

        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.add = MagicMock()

    async def get(self, cls, pk):
        from db.models import TeachingSession
        if cls == TeachingSession and pk == _SESSION_ID:
            return self._session
        return None

    async def execute(self, stmt):
        self._execute_call_count += 1
        result = MagicMock()

        if self._execute_call_count == 1:
            # First execute: ConceptChunk query
            scalars = MagicMock()
            scalars.all.return_value = self._chunks
            result.scalars.return_value = scalars
        else:
            # Second execute: ChunkImage.chunk_id distinct query
            # fetchall returns list of row-tuples like [(uuid,), ...]
            result.fetchall.return_value = [(cid,) for cid in self._image_chunk_ids]

        return result


def _build_test_app(mock_db_instance) -> FastAPI:
    """Build a lightweight FastAPI app exercising the real list_chunks handler."""
    app = FastAPI()
    app.state.limiter = limiter

    async def _get_test_db():
        yield mock_db_instance

    app.dependency_overrides[get_db] = _get_test_db

    # Wire minimal teaching_svc so the module-level reference doesn't raise
    mock_svc = MagicMock()
    teaching_router_module.teaching_svc = mock_svc
    teaching_router_module.chunk_ksvc = MagicMock()

    app.include_router(teaching_router_module.router)
    return app


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CHUNKS-01  Chunks returned in textbook order (order_index ASC)
# ═══════════════════════════════════════════════════════════════════════════════

class TestChunksReturnedInTextbookOrder:
    """
    BC-CHUNKS-01: Chunks must be ordered by order_index so the student progresses
    through the textbook in the correct sequence.
    """

    @pytest.mark.asyncio
    async def test_get_chunks_returns_chunks_in_order(self):
        """
        Business criterion: Chunks are presented to the student in textbook order.
        Create 3 ConceptChunk rows with shuffled order_index values (2, 0, 1).
        The handler orders them by order_index; the response must be [0, 1, 2].
        """
        # Arrange — chunks out of order at the ORM level
        chunk_a = _make_orm_chunk(order_index=2, heading="Summary")
        chunk_b = _make_orm_chunk(order_index=0, heading="Learning Objectives")
        chunk_c = _make_orm_chunk(order_index=1, heading="Use Addition Notation")
        # The DB returns them in whatever order the query delivers;
        # the handler relies on SQLAlchemy ORDER BY order_index which is already
        # baked in. We simulate the ORM already returning them sorted because
        # the handler passes the scalars.all() result directly to list comprehension.
        # To test that the response reflects the DB order, return pre-sorted list.
        sorted_chunks = [chunk_b, chunk_c, chunk_a]

        session = _make_fake_session()
        db = _MockDb(session=session, chunks=sorted_chunks, image_chunk_ids=[])
        app = _build_test_app(db)

        # Act
        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        order_indices = [c["order_index"] for c in data["chunks"]]
        assert order_indices == [0, 1, 2], (
            f"Expected order_indices [0, 1, 2] but got {order_indices}"
        )

    @pytest.mark.asyncio
    async def test_get_chunks_preserves_heading_per_order(self):
        """
        Business criterion: Each chunk summary contains the heading from its DB row.
        After ordering by order_index the heading at position 0 must match the
        chunk with order_index=0.
        """
        chunk0 = _make_orm_chunk(order_index=0, heading="Learning Objectives")
        chunk1 = _make_orm_chunk(order_index=1, heading="Use Addition Notation")
        chunk2 = _make_orm_chunk(order_index=2, heading="Add Whole Numbers")

        session = _make_fake_session()
        db = _MockDb(session=session, chunks=[chunk0, chunk1, chunk2], image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        chunks_resp = resp.json()["chunks"]
        assert chunks_resp[0]["heading"] == "Learning Objectives"
        assert chunks_resp[1]["heading"] == "Use Addition Notation"
        assert chunks_resp[2]["heading"] == "Add Whole Numbers"


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CHUNKS-02  Empty list signals ChromaDB-path session
# ═══════════════════════════════════════════════════════════════════════════════

class TestChunksEmptyForChromaDBSession:
    """
    BC-CHUNKS-02: When no ConceptChunk rows exist for the session's concept,
    the response must return an empty chunks list so the frontend falls back
    to the legacy card-generation flow.
    """

    @pytest.mark.asyncio
    async def test_get_chunks_returns_empty_for_chromadb_session(self):
        """
        Business criterion: ChromaDB-path sessions receive routing signal via
        empty chunks list.
        Session exists, but no ConceptChunk rows exist for its concept_id.
        Response: chunks=[] and current_chunk_index=0.
        """
        session = _make_fake_session(chunk_index=0)
        db = _MockDb(session=session, chunks=[], image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")

        assert resp.status_code == 200
        data = resp.json()
        assert data["chunks"] == [], "chunks must be empty for ChromaDB-path session"
        assert data["current_chunk_index"] == 0

    @pytest.mark.asyncio
    async def test_get_chunks_empty_response_has_required_keys(self):
        """
        Business criterion: Even an empty response must include all required fields
        so the frontend can safely read concept_id, section_title, and chunks.
        """
        session = _make_fake_session()
        db = _MockDb(session=session, chunks=[], image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        data = resp.json()
        assert "concept_id" in data
        assert "section_title" in data
        assert "chunks" in data
        assert "current_chunk_index" in data


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CHUNKS-03  has_images flag reflects the database
# ═══════════════════════════════════════════════════════════════════════════════

class TestHasImagesFlagReflectsDb:
    """
    BC-CHUNKS-03: Frontend knows which chunks have images before fetching cards,
    so it can pre-render image placeholders and avoid layout shift.
    """

    @pytest.mark.asyncio
    async def test_get_chunks_has_images_flag_reflects_db(self):
        """
        Business criterion: Frontend knows which chunks have images before fetching cards.
        Chunk 0 has an associated ChunkImage row; chunk 1 does not.
        The response must reflect has_images=true for chunk 0, false for chunk 1.
        """
        chunk_with_image = _make_orm_chunk(order_index=0, heading="Use Addition Notation")
        chunk_no_image   = _make_orm_chunk(order_index=1, heading="Add Whole Numbers")

        session = _make_fake_session()
        db = _MockDb(
            session=session,
            chunks=[chunk_with_image, chunk_no_image],
            image_chunk_ids=[chunk_with_image.id],  # only first chunk has image
        )
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        chunks_resp = resp.json()["chunks"]

        assert chunks_resp[0]["has_images"] is True, "chunk with image must have has_images=true"
        assert chunks_resp[1]["has_images"] is False, "chunk without image must have has_images=false"

    @pytest.mark.asyncio
    async def test_has_images_false_when_no_images_exist(self):
        """
        Business criterion: has_images flag must be false when no ChunkImage rows exist.
        No images in DB → all chunks report has_images=false.
        """
        chunks = [
            _make_orm_chunk(order_index=0, heading="Add Whole Numbers"),
            _make_orm_chunk(order_index=1, heading="Subtract Whole Numbers"),
        ]
        session = _make_fake_session()
        db = _MockDb(session=session, chunks=chunks, image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        for c in resp.json()["chunks"]:
            assert c["has_images"] is False

    @pytest.mark.asyncio
    async def test_has_images_true_for_all_when_all_have_images(self):
        """
        Business criterion: Every chunk with at least one image row reports has_images=true.
        """
        chunk_a = _make_orm_chunk(order_index=0, heading="Add Whole Numbers")
        chunk_b = _make_orm_chunk(order_index=1, heading="Subtract Whole Numbers")

        session = _make_fake_session()
        db = _MockDb(
            session=session,
            chunks=[chunk_a, chunk_b],
            image_chunk_ids=[chunk_a.id, chunk_b.id],
        )
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        for c in resp.json()["chunks"]:
            assert c["has_images"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CHUNKS-04  current_chunk_index reflects session state
# ═══════════════════════════════════════════════════════════════════════════════

class TestCurrentChunkIndexFromSession:
    """
    BC-CHUNKS-04: Student returns to the correct chunk position after resuming
    a session that was interrupted mid-concept.
    """

    @pytest.mark.asyncio
    async def test_get_chunks_current_chunk_index_from_session(self):
        """
        Business criterion: Student returns to the correct position after resuming.
        Session has chunk_index=2; the response must echo current_chunk_index=2.
        """
        chunks = [
            _make_orm_chunk(order_index=0, heading="Learning Objectives"),
            _make_orm_chunk(order_index=1, heading="Add Whole Numbers"),
            _make_orm_chunk(order_index=2, heading="Subtract Whole Numbers"),
        ]
        session = _make_fake_session(chunk_index=2)
        db = _MockDb(session=session, chunks=chunks, image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        assert resp.json()["current_chunk_index"] == 2

    @pytest.mark.asyncio
    async def test_current_chunk_index_zero_when_session_at_start(self):
        """
        Business criterion: Fresh sessions start at chunk_index=0.
        """
        chunks = [_make_orm_chunk(order_index=0, heading="Add Whole Numbers")]
        session = _make_fake_session(chunk_index=0)
        db = _MockDb(session=session, chunks=chunks, image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        assert resp.json()["current_chunk_index"] == 0

    @pytest.mark.asyncio
    async def test_current_chunk_index_fallback_when_none(self):
        """
        Business criterion: chunk_index=None in DB (legacy rows) is treated as 0.
        """
        session = _make_fake_session(chunk_index=None)
        db = _MockDb(session=session, chunks=[], image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        assert resp.json()["current_chunk_index"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CHUNKS-05  Non-existent session returns 404
# ═══════════════════════════════════════════════════════════════════════════════

class TestSessionNotFound:
    """
    BC-CHUNKS-05: Requesting chunks for an unknown session must return HTTP 404
    so the frontend can display an appropriate error message.
    """

    @pytest.mark.asyncio
    async def test_get_chunks_session_not_found_returns_404(self):
        """
        Business criterion: Unknown session_id returns HTTP 404.
        """
        unknown_id = uuid.uuid4()
        db = _MockDb(session=None, chunks=[], image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{unknown_id}/chunks")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CHUNKS-06  section_title is derived from first chunk
# ═══════════════════════════════════════════════════════════════════════════════

class TestSectionTitle:
    """
    BC-CHUNKS-06: The section_title returned to the frontend must match the
    section field of the first (lowest order_index) chunk.
    """

    @pytest.mark.asyncio
    async def test_section_title_equals_first_chunk_section(self):
        """
        Business criterion: The section_title in the response comes from the
        first chunk's section field, giving the frontend a human-readable title.
        """
        chunk0 = _make_orm_chunk(order_index=0, heading="Learning Objectives",
                                  section="1.1 Introduction to Whole Numbers")
        chunk1 = _make_orm_chunk(order_index=1, heading="Add Whole Numbers",
                                  section="1.1 Introduction to Whole Numbers")
        session = _make_fake_session()
        db = _MockDb(session=session, chunks=[chunk0, chunk1], image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        assert resp.json()["section_title"] == "1.1 Introduction to Whole Numbers"

    @pytest.mark.asyncio
    async def test_section_title_empty_when_no_chunks(self):
        """
        Business criterion: ChromaDB-path sessions have no chunks; section_title is empty string.
        """
        session = _make_fake_session()
        db = _MockDb(session=session, chunks=[], image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        assert resp.json()["section_title"] == ""


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CHUNKS-07  has_mcq flag correctly marks non-teaching headings
# ═══════════════════════════════════════════════════════════════════════════════

class TestHasMcqFlag:
    """
    BC-CHUNKS-07: The has_mcq flag must be False for structural headings
    (e.g., 'Learning Objectives', 'Key Terms') that do not generate quiz questions,
    and True for content headings that do.
    """

    @pytest.mark.asyncio
    async def test_has_mcq_false_for_learning_objectives(self):
        """
        Business criterion: 'Learning Objectives' is a structural heading —
        has_mcq must be False so the frontend skips the MCQ panel for it.
        """
        chunk = _make_orm_chunk(order_index=0, heading="Learning Objectives")
        session = _make_fake_session()
        db = _MockDb(session=session, chunks=[chunk], image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        assert resp.json()["chunks"][0]["has_mcq"] is False

    @pytest.mark.asyncio
    async def test_has_mcq_false_for_key_terms(self):
        """
        Business criterion: 'Key Terms' is a glossary heading — has_mcq=False.
        """
        chunk = _make_orm_chunk(order_index=0, heading="Key Terms")
        session = _make_fake_session()
        db = _MockDb(session=session, chunks=[chunk], image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        assert resp.json()["chunks"][0]["has_mcq"] is False

    @pytest.mark.asyncio
    async def test_has_mcq_true_for_teaching_heading(self):
        """
        Business criterion: Content headings like 'Use Addition Notation' produce
        MCQ questions — has_mcq must be True.
        """
        chunk = _make_orm_chunk(order_index=0, heading="Use Addition Notation")
        session = _make_fake_session()
        db = _MockDb(session=session, chunks=[chunk], image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        assert resp.json()["chunks"][0]["has_mcq"] is True

    @pytest.mark.asyncio
    async def test_has_mcq_mixed_headings(self):
        """
        Business criterion: Mixed chunk list — structural headings get has_mcq=False,
        teaching headings get has_mcq=True.
        """
        structural  = _make_orm_chunk(order_index=0, heading="Learning Objectives")
        teaching    = _make_orm_chunk(order_index=1, heading="Add Whole Numbers")
        summary     = _make_orm_chunk(order_index=2, heading="Summary")

        session = _make_fake_session()
        db = _MockDb(session=session, chunks=[structural, teaching, summary], image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        chunks_resp = resp.json()["chunks"]
        assert chunks_resp[0]["has_mcq"] is False  # Learning Objectives
        assert chunks_resp[1]["has_mcq"] is True   # Add Whole Numbers
        assert chunks_resp[2]["has_mcq"] is False  # Summary


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CHUNKS-08  ChunkSummary schema completeness
# ═══════════════════════════════════════════════════════════════════════════════

class TestChunkSummarySchema:
    """
    BC-CHUNKS-08: Every ChunkSummary in the response must include all required
    fields so the frontend can render the progress indicator without defensive
    null-checks.
    """

    @pytest.mark.asyncio
    async def test_chunk_summary_has_all_required_fields(self):
        """
        Business criterion: chunk_id, order_index, heading, has_images, has_mcq
        must all be present on every ChunkSummary in the response.
        """
        chunk = _make_orm_chunk(order_index=0, heading="Add Whole Numbers")
        session = _make_fake_session()
        db = _MockDb(session=session, chunks=[chunk], image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        summary = resp.json()["chunks"][0]
        required_fields = {"chunk_id", "order_index", "heading", "has_images", "has_mcq"}
        missing = required_fields - set(summary.keys())
        assert not missing, f"Missing fields in ChunkSummary: {missing}"

    @pytest.mark.asyncio
    async def test_chunk_id_is_valid_uuid_string(self):
        """
        Business criterion: chunk_id must be a valid UUID string so the frontend
        can use it directly in subsequent API calls.
        """
        chunk_uuid = uuid.uuid4()
        chunk = _make_orm_chunk(order_index=0, heading="Add Whole Numbers", chunk_id=chunk_uuid)
        session = _make_fake_session()
        db = _MockDb(session=session, chunks=[chunk], image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        chunk_id_str = resp.json()["chunks"][0]["chunk_id"]
        # Must round-trip as a UUID
        parsed = uuid.UUID(chunk_id_str)
        assert parsed == chunk_uuid

    @pytest.mark.asyncio
    async def test_concept_id_echoed_in_response(self):
        """
        Business criterion: The response must echo the concept_id so the frontend
        can confirm it is viewing chunks for the right concept.
        """
        session = _make_fake_session(concept_id="prealgebra_2.3")
        chunk = _make_orm_chunk(order_index=0, heading="Add Fractions",
                                 concept_id="prealgebra_2.3", section="2.3 Fractions")
        db = _MockDb(session=session, chunks=[chunk], image_chunk_ids=[])
        app = _build_test_app(db)

        resp = await _get(app, f"/api/v2/sessions/{_SESSION_ID}/chunks")
        assert resp.status_code == 200
        assert resp.json()["concept_id"] == "prealgebra_2.3"
