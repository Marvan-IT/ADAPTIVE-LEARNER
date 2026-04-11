"""
test_chunk_knowledge_service.py — Integration tests for ChunkKnowledgeService.

Business criteria covered:
  - get_active_books() returns a set (possibly empty) — never crashes on empty DB
  - get_chunk_count() returns a non-negative integer
  - get_chunk() returns None for a nonexistent UUID
  - get_chunk() returns None for a malformed UUID string (not a valid UUID)
  - get_chunks_for_concept() returns an empty list for an unknown concept
  - get_chunk_images() returns an empty list for an unknown chunk UUID
  - get_chunk_images() returns an empty list for a malformed UUID
  - _chunk_to_dict() always includes the 'images' key (populated separately)

Unit tests for _chunk_to_dict and UUID validation use a mock ORM object and run always.
DB-dependent tests are auto-skipped when the database is unavailable.
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from typing import AsyncIterator

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from api.chunk_knowledge_service import ChunkKnowledgeService


# ── Unit tests: _chunk_to_dict and UUID guard (always run) ────────────────────

class TestChunkToDictUnit:
    """_chunk_to_dict converts an ORM model to a well-formed dict."""

    def _make_orm_chunk(self, **overrides) -> MagicMock:
        chunk = MagicMock()
        chunk.id = uuid.uuid4()
        chunk.book_slug = "prealgebra"
        chunk.concept_id = "prealgebra_1.1"
        chunk.section = "1.1 Introduction to Whole Numbers"
        chunk.order_index = 0
        chunk.heading = "Identify Whole Numbers"
        chunk.text = "Whole numbers are 0, 1, 2, 3..."
        chunk.latex = ["0, 1, 2, 3"]
        for k, v in overrides.items():
            setattr(chunk, k, v)
        return chunk

    def test_dict_has_expected_keys(self):
        svc = ChunkKnowledgeService()
        orm = self._make_orm_chunk()
        d = svc._chunk_to_dict(orm)
        expected_keys = {"id", "book_slug", "concept_id", "section", "order_index", "heading", "text", "latex", "images"}
        assert expected_keys.issubset(d.keys())

    def test_id_is_string(self):
        svc = ChunkKnowledgeService()
        orm = self._make_orm_chunk()
        d = svc._chunk_to_dict(orm)
        assert isinstance(d["id"], str)

    def test_images_is_always_empty_list(self):
        # images are populated separately via get_chunk_images(); _chunk_to_dict always returns []
        svc = ChunkKnowledgeService()
        orm = self._make_orm_chunk()
        d = svc._chunk_to_dict(orm)
        assert d["images"] == []

    def test_latex_none_becomes_empty_list(self):
        svc = ChunkKnowledgeService()
        orm = self._make_orm_chunk(latex=None)
        d = svc._chunk_to_dict(orm)
        assert d["latex"] == []

    def test_latex_list_is_preserved(self):
        svc = ChunkKnowledgeService()
        orm = self._make_orm_chunk(latex=["a^2", "b^2"])
        d = svc._chunk_to_dict(orm)
        assert d["latex"] == ["a^2", "b^2"]

    def test_all_fields_match_orm(self):
        svc = ChunkKnowledgeService()
        chunk_id = uuid.uuid4()
        orm = self._make_orm_chunk(
            id=chunk_id,
            book_slug="calculus_1",
            concept_id="calculus_1_2.3",
            section="2.3 Limits",
            order_index=42,
            heading="Definition of a Limit",
            text="A limit is the value a function approaches.",
        )
        d = svc._chunk_to_dict(orm)
        assert d["id"] == str(chunk_id)
        assert d["book_slug"] == "calculus_1"
        assert d["concept_id"] == "calculus_1_2.3"
        assert d["section"] == "2.3 Limits"
        assert d["order_index"] == 42
        assert d["heading"] == "Definition of a Limit"
        assert d["text"] == "A limit is the value a function approaches."


class TestGetChunkUUIDValidationUnit:
    """get_chunk() and get_chunk_images() handle malformed UUIDs gracefully."""

    @pytest.mark.asyncio
    async def test_get_chunk_with_invalid_uuid_returns_none(self):
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()
        result = await svc.get_chunk(mock_db, "not-a-valid-uuid")
        assert result is None
        # DB must not be queried for an invalid UUID
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_chunk_images_with_invalid_uuid_returns_empty(self):
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()
        result = await svc.get_chunk_images(mock_db, "definitely-not-a-uuid")
        assert result == []
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_chunk_images_with_empty_string_returns_empty(self):
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()
        result = await svc.get_chunk_images(mock_db, "")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_chunk_with_valid_uuid_format_queries_db(self):
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()
        # Simulate scalar_one_or_none returning None (not found)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await svc.get_chunk(mock_db, "00000000-0000-0000-0000-000000000000")
        assert result is None
        mock_db.execute.assert_called_once()


class TestGetChunkImagesUnit:
    """get_chunk_images() returns correct structure from ORM rows."""

    @pytest.mark.asyncio
    async def test_returns_list_of_dicts_with_image_url_and_caption(self):
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()

        img1 = MagicMock()
        img1.image_url = "/images/prealgebra/images_downloaded/abc.jpg"
        img1.caption = "Figure 1.1"
        img1.order_index = 0

        img2 = MagicMock()
        img2.image_url = "/images/prealgebra/images_downloaded/def.jpg"
        img2.caption = None
        img2.order_index = 1

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [img1, img2]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        chunk_id = str(uuid.uuid4())
        result = await svc.get_chunk_images(mock_db, chunk_id)

        assert len(result) == 2
        assert result[0]["image_url"] == img1.image_url
        assert result[0]["caption"] == "Figure 1.1"
        assert result[1]["caption"] is None

    @pytest.mark.asyncio
    async def test_returns_empty_for_chunk_with_no_images(self):
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        chunk_id = str(uuid.uuid4())
        result = await svc.get_chunk_images(mock_db, chunk_id)
        assert result == []


class TestGetChunksForConceptUnit:
    """get_chunks_for_concept() returns ordered list of chunk dicts."""

    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown_concept(self):
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_chunks_for_concept(mock_db, "prealgebra", "prealgebra_99.99")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_chunks_in_order_index_sequence(self):
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()

        def _make_chunk(order, heading):
            c = MagicMock()
            c.id = uuid.uuid4()
            c.book_slug = "prealgebra"
            c.concept_id = "prealgebra_1.1"
            c.section = "1.1 Introduction"
            c.order_index = order
            c.heading = heading
            c.text = f"Content for {heading}"
            c.latex = []
            return c

        orm_chunks = [_make_chunk(0, "Intro"), _make_chunk(1, "Details"), _make_chunk(2, "Summary")]

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = orm_chunks
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_chunks_for_concept(mock_db, "prealgebra", "prealgebra_1.1")
        assert len(result) == 3
        assert result[0]["order_index"] == 0
        assert result[1]["order_index"] == 1
        assert result[2]["order_index"] == 2

    @pytest.mark.asyncio
    async def test_get_chunks_for_concept_returns_order_index_asc(self):
        """
        Business criterion: Chunks are always served in textbook order.
        Insert chunks with shuffled order_index values (2, 0, 1).
        get_chunks_for_concept relies on the DB ORDER BY clause; the service
        must pass those results through in the same sequence.
        Here we simulate the DB already returning them in ASC order (as the
        ORDER BY order_index clause guarantees), and verify the service
        preserves that order without re-sorting or reversing.
        """
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()

        def _make_chunk(order, heading):
            c = MagicMock()
            c.id = uuid.uuid4()
            c.book_slug = "prealgebra"
            c.concept_id = "prealgebra_1.1"
            c.section = "1.1 Introduction"
            c.order_index = order
            c.heading = heading
            c.text = f"Content for {heading}"
            c.latex = []
            return c

        # DB returns rows already sorted ascending by order_index (SQLAlchemy ORDER BY)
        # Simulating shuffled creation but sorted retrieval (order_index 0, 1, 2)
        db_sorted_chunks = [
            _make_chunk(0, "Learning Objectives"),
            _make_chunk(1, "Use Addition Notation"),
            _make_chunk(2, "Add Whole Numbers"),
        ]

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = db_sorted_chunks
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_chunks_for_concept(mock_db, "prealgebra", "prealgebra_1.1")

        # Criterion: order_index values must be ascending in the returned list
        order_indices = [c["order_index"] for c in result]
        assert order_indices == sorted(order_indices), (
            f"Chunks not in ascending order: {order_indices}"
        )
        assert order_indices == [0, 1, 2]


class TestGetActiveBooksUnit:
    """get_active_books() returns a set of distinct book slugs."""

    @pytest.mark.asyncio
    async def test_returns_set_type(self):
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("prealgebra",), ("calculus_1",)]
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_active_books(mock_db)
        assert isinstance(result, set)

    @pytest.mark.asyncio
    async def test_returns_expected_slugs(self):
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("prealgebra",), ("elementary_algebra",)]
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_active_books(mock_db)
        assert result == {"prealgebra", "elementary_algebra"}

    @pytest.mark.asyncio
    async def test_returns_empty_set_when_no_chunks(self):
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_active_books(mock_db)
        assert result == set()


class TestGetChunkCountUnit:
    """get_chunk_count() returns a non-negative integer."""

    @pytest.mark.asyncio
    async def test_returns_integer(self):
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 150
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_chunk_count(mock_db)
        assert isinstance(result, int)
        assert result == 150

    @pytest.mark.asyncio
    async def test_returns_zero_when_db_null(self):
        # scalar() returns None → should return 0
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_chunk_count(mock_db)
        assert result == 0

    @pytest.mark.asyncio
    async def test_filtered_by_book_slug(self):
        """When book_slug is passed, the query must be filtered (DB called once)."""
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 42
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_chunk_count(mock_db, book_slug="prealgebra")
        assert result == 42
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_unfiltered_call_no_book_slug(self):
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1000
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_chunk_count(mock_db)
        assert result == 1000


# ── DB integration tests (require live PostgreSQL) ────────────────────────────

try:
    import asyncpg  # noqa: F401
    _ASYNCPG_AVAILABLE = True
except ImportError:
    _ASYNCPG_AVAILABLE = False


@pytest.mark.integration
@pytest.mark.skipif(not _ASYNCPG_AVAILABLE, reason="asyncpg not installed")
class TestChunkKnowledgeServiceIntegration:
    """
    Integration tests that hit a real PostgreSQL database.

    Requires DATABASE_URL env var and the concept_chunks table to exist.
    Skip individually if the DB is not available at test time.
    """

    @pytest.mark.asyncio
    async def test_get_active_books_empty_or_set(self, db_session):
        svc = ChunkKnowledgeService()
        books = await svc.get_active_books(db_session)
        assert isinstance(books, set)

    @pytest.mark.asyncio
    async def test_get_chunk_count_non_negative(self, db_session):
        svc = ChunkKnowledgeService()
        count = await svc.get_chunk_count(db_session)
        assert isinstance(count, int)
        assert count >= 0

    @pytest.mark.asyncio
    async def test_get_chunk_nonexistent(self, db_session):
        svc = ChunkKnowledgeService()
        result = await svc.get_chunk(db_session, "00000000-0000-0000-0000-000000000000")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_chunks_for_empty_concept(self, db_session):
        svc = ChunkKnowledgeService()
        result = await svc.get_chunks_for_concept(db_session, "prealgebra", "prealgebra_99.99")
        assert result == []
