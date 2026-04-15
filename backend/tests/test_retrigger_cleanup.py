"""
test_retrigger_cleanup.py

Tests for the retrigger book cleanup logic in admin_router.py and
the invalidate_graph_cache() utility in chunk_knowledge_service.py.

Business criteria covered:
  1. invalidate_graph_cache() removes the targeted book from _graph_cache.
  2. invalidate_graph_cache() does NOT evict other books present in the cache.
  3. invalidate_graph_cache() is safe to call when the book is absent from cache.
  4. POST /api/admin/books/{slug}/retrigger deletes rows from concept_chunks.
  5. POST /api/admin/books/{slug}/retrigger deletes rows from admin_graph_overrides.
  6. POST /api/admin/books/{slug}/retrigger calls invalidate_graph_cache(slug).
  7. POST /api/admin/books/{slug}/retrigger returns HTTP 404 when book row missing.
  8. POST /api/admin/retrigger-book/{slug} (legacy) deletes concept_chunks rows.
  9. POST /api/admin/retrigger-book/{slug} (legacy) deletes admin_graph_overrides rows.
  10. POST /api/admin/retrigger-book/{slug} (legacy) calls invalidate_graph_cache(slug).

Strategy
--------
- Unit tests for invalidate_graph_cache() manipulate the real module-level
  _graph_cache dict directly — no mocking needed for those 3 cases.
- Integration tests for the HTTP endpoints build a lightweight FastAPI test app
  with AsyncMock DB and dependency overrides — no live PostgreSQL required.
- subprocess.Popen, DATA_DIR, OUTPUT_DIR, and derive_slug are all patched so the
  endpoint can run to completion without touching the filesystem or spawning
  processes.

Run: pytest backend/tests/test_retrigger_cleanup.py -v
"""
from __future__ import annotations

import sys
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

# ── 1. sys.path ────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── 2. Required env before any import ─────────────────────────────────────────
os.environ.setdefault("API_SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://fake:fake@localhost/fake")

# ── 3. Stub heavy transitive deps before importing admin_router ────────────────
if "fitz" not in sys.modules:
    sys.modules["fitz"] = MagicMock()

# api.chunk_knowledge_service is imported by admin_router at module level.
# We do NOT stub it here so that we can import the REAL invalidate_graph_cache
# function and assert it is called correctly from the endpoint tests.
# The real module is imported below after sys.path is set.

import pytest
import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

# Import the real cache module so unit tests can manipulate _graph_cache directly.
import api.chunk_knowledge_service as ck_svc

import api.admin_router as admin_router_module
from api.admin_router import router as admin_router

# Force legacy API key to match our test header.
admin_router_module._API_KEY = "test-secret"

_API_HEADERS = {"X-API-Key": "test-secret"}
_TEST_SLUG = "prealgebra"
_OTHER_SLUG = "algebra"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_admin_user() -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.email = "admin@test.com"
    u.role = "admin"
    u.is_active = True
    u.email_verified = True
    u.created_at = datetime.now(timezone.utc)
    return u


_STUB_ADMIN = _make_admin_user()


def _make_book(slug: str = _TEST_SLUG, status: str = "PUBLISHED") -> MagicMock:
    b = MagicMock()
    b.book_slug = slug
    b.title = "Prealgebra"
    b.subject = "mathematics"
    b.status = status
    b.pdf_filename = f"{slug}.pdf"
    b.created_at = datetime.now(timezone.utc)
    b.published_at = datetime.now(timezone.utc)
    return b


def _make_mock_db(book: MagicMock | None = None) -> AsyncMock:
    """AsyncSession mock; execute() returns a result whose scalar_one_or_none gives `book`."""
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=book)
    result.scalar = MagicMock(return_value=0)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    result.all = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _build_test_app(mock_db: AsyncMock) -> FastAPI:
    """Minimal FastAPI app with admin_router; DB and auth overridden."""
    app = FastAPI()

    async def _override_get_db():
        yield mock_db

    async def _override_require_admin():
        return _STUB_ADMIN

    from db.connection import get_db
    from auth.dependencies import require_admin
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[require_admin] = _override_require_admin
    app.include_router(admin_router)
    app.state.chunk_knowledge_svc = MagicMock()
    return app


def _fake_graph() -> MagicMock:
    """Lightweight stand-in for a networkx.DiGraph stored in the cache."""
    return MagicMock(name="DiGraph")


# ── Unit tests: invalidate_graph_cache() ──────────────────────────────────────

class TestInvalidateGraphCache:
    """
    Pure unit tests for invalidate_graph_cache().  These manipulate the real
    module-level _graph_cache dict and verify the function's postconditions.
    Each test restores the dict to its original state via teardown.
    """

    def setup_method(self):
        # Snapshot the cache state so we can restore it after each test.
        self._original = dict(ck_svc._graph_cache)

    def teardown_method(self):
        ck_svc._graph_cache.clear()
        ck_svc._graph_cache.update(self._original)

    # ── Test 1 ────────────────────────────────────────────────────────────────

    def test_invalidate_removes_target_book_from_cache(self):
        """
        invalidate_graph_cache(slug) should evict the given book so subsequent
        calls to _load_graph() will re-read from disk.
        """
        # Arrange — seed the cache with the book we want evicted.
        ck_svc._graph_cache[_TEST_SLUG] = _fake_graph()
        assert _TEST_SLUG in ck_svc._graph_cache

        # Act
        ck_svc.invalidate_graph_cache(_TEST_SLUG)

        # Assert
        assert _TEST_SLUG not in ck_svc._graph_cache

    # ── Test 2 ────────────────────────────────────────────────────────────────

    def test_invalidate_does_not_evict_other_books(self):
        """
        Evicting one book must leave unrelated books intact in the cache so
        their consumers do not incur an unnecessary disk read.
        """
        # Arrange — seed two books; we will only evict the first.
        target_graph = _fake_graph()
        other_graph = _fake_graph()
        ck_svc._graph_cache[_TEST_SLUG] = target_graph
        ck_svc._graph_cache[_OTHER_SLUG] = other_graph

        # Act
        ck_svc.invalidate_graph_cache(_TEST_SLUG)

        # Assert — other book is still cached and is the *same* object (not re-loaded).
        assert _OTHER_SLUG in ck_svc._graph_cache
        assert ck_svc._graph_cache[_OTHER_SLUG] is other_graph

    # ── Test 3 ────────────────────────────────────────────────────────────────

    def test_invalidate_is_safe_when_book_not_in_cache(self):
        """
        Calling invalidate_graph_cache() for a book that was never loaded must
        not raise any exception — idempotent no-op.
        """
        # Arrange — ensure the slug is absent.
        ck_svc._graph_cache.pop(_TEST_SLUG, None)
        assert _TEST_SLUG not in ck_svc._graph_cache

        # Act + Assert — no exception raised.
        ck_svc.invalidate_graph_cache(_TEST_SLUG)

        # Cache is still empty for that key.
        assert _TEST_SLUG not in ck_svc._graph_cache


# ── Integration tests: POST /api/admin/books/{slug}/retrigger ─────────────────

class TestRetriggerEndpoint:
    """
    Integration tests for the new-style retrigger endpoint.
    DB interactions are replaced by AsyncMock; subprocess, DATA_DIR, and
    OUTPUT_DIR are patched so the test never touches the filesystem.
    """

    def _make_pdf_path(self, tmp_path: Path) -> Path:
        """Create a dummy PDF file that derive_slug maps back to _TEST_SLUG."""
        pdf = tmp_path / "data" / "mathematics" / f"{_TEST_SLUG}.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"%PDF-1.4 fake")
        return pdf

    @pytest.mark.asyncio
    async def test_retrigger_deletes_concept_chunks(self, tmp_path):
        """
        POST /api/admin/books/{slug}/retrigger must issue a DELETE against
        concept_chunks WHERE book_slug = slug before returning 200.
        """
        mock_db = _make_mock_db(book=_make_book())
        app = _build_test_app(mock_db)
        pdf_path = self._make_pdf_path(tmp_path)

        with (
            patch.object(admin_router_module, "DATA_DIR", pdf_path.parent.parent),
            patch.object(admin_router_module, "OUTPUT_DIR", tmp_path / "output"),
            patch.object(admin_router_module, "derive_slug", return_value=_TEST_SLUG),
            patch.object(admin_router_module, "subprocess") as mock_sub,
            patch.object(admin_router_module, "invalidate_graph_cache"),
        ):
            mock_sub.Popen = MagicMock()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/admin/books/{_TEST_SLUG}/retrigger",
                    headers=_API_HEADERS,
                )

        assert resp.status_code == 200

        # Collect all SQL strings passed to db.execute()
        executed_sqls = [
            str(call_args.args[0]) if call_args.args else ""
            for call_args in mock_db.execute.call_args_list
        ]
        assert any("concept_chunks" in sql for sql in executed_sqls), (
            "Expected a DELETE on concept_chunks but it was not found in executed statements"
        )

    @pytest.mark.asyncio
    async def test_retrigger_deletes_admin_graph_overrides(self, tmp_path):
        """
        POST /api/admin/books/{slug}/retrigger must also issue a DELETE against
        admin_graph_overrides WHERE book_slug = slug so stale edge overrides do
        not contaminate the freshly-built graph.
        """
        mock_db = _make_mock_db(book=_make_book())
        app = _build_test_app(mock_db)
        pdf_path = self._make_pdf_path(tmp_path)

        with (
            patch.object(admin_router_module, "DATA_DIR", pdf_path.parent.parent),
            patch.object(admin_router_module, "OUTPUT_DIR", tmp_path / "output"),
            patch.object(admin_router_module, "derive_slug", return_value=_TEST_SLUG),
            patch.object(admin_router_module, "subprocess") as mock_sub,
            patch.object(admin_router_module, "invalidate_graph_cache"),
        ):
            mock_sub.Popen = MagicMock()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/admin/books/{_TEST_SLUG}/retrigger",
                    headers=_API_HEADERS,
                )

        assert resp.status_code == 200

        executed_sqls = [
            str(call_args.args[0]) if call_args.args else ""
            for call_args in mock_db.execute.call_args_list
        ]
        assert any("admin_graph_overrides" in sql for sql in executed_sqls), (
            "Expected a DELETE on admin_graph_overrides but it was not found in executed statements"
        )

    @pytest.mark.asyncio
    async def test_retrigger_calls_invalidate_graph_cache(self, tmp_path):
        """
        POST /api/admin/books/{slug}/retrigger must call invalidate_graph_cache()
        with the correct slug so the in-memory graph is not served stale after
        the pipeline re-runs.
        """
        mock_db = _make_mock_db(book=_make_book())
        app = _build_test_app(mock_db)
        pdf_path = self._make_pdf_path(tmp_path)

        with (
            patch.object(admin_router_module, "DATA_DIR", pdf_path.parent.parent),
            patch.object(admin_router_module, "OUTPUT_DIR", tmp_path / "output"),
            patch.object(admin_router_module, "derive_slug", return_value=_TEST_SLUG),
            patch.object(admin_router_module, "subprocess") as mock_sub,
            patch.object(
                admin_router_module, "invalidate_graph_cache"
            ) as mock_invalidate,
        ):
            mock_sub.Popen = MagicMock()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/admin/books/{_TEST_SLUG}/retrigger",
                    headers=_API_HEADERS,
                )

        assert resp.status_code == 200
        mock_invalidate.assert_called_once_with(_TEST_SLUG)

    @pytest.mark.asyncio
    async def test_retrigger_returns_404_when_book_row_missing(self, tmp_path):
        """
        POST /api/admin/books/{slug}/retrigger must return HTTP 404 when the
        Book row does not exist in the database.
        """
        # scalar_one_or_none returns None → book not found
        mock_db = _make_mock_db(book=None)
        app = _build_test_app(mock_db)
        pdf_path = self._make_pdf_path(tmp_path)

        with (
            patch.object(admin_router_module, "DATA_DIR", pdf_path.parent.parent),
            patch.object(admin_router_module, "OUTPUT_DIR", tmp_path / "output"),
            patch.object(admin_router_module, "derive_slug", return_value=_TEST_SLUG),
            patch.object(admin_router_module, "subprocess") as mock_sub,
            patch.object(admin_router_module, "invalidate_graph_cache"),
        ):
            mock_sub.Popen = MagicMock()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/admin/books/{_TEST_SLUG}/retrigger",
                    headers=_API_HEADERS,
                )

        assert resp.status_code == 404


# ── Integration tests: POST /api/admin/retrigger-book/{slug} (legacy) ─────────

class TestLegacyRetriggerEndpoint:
    """
    Integration tests for the legacy retrigger endpoint.
    It uses X-API-Key auth (not JWT), and calls get_db() internally via its
    own async generator — so we patch get_db at the module level instead of
    using dependency_overrides.
    """

    def _make_pdf_path(self, tmp_path: Path) -> Path:
        pdf = tmp_path / "data" / "mathematics" / f"{_TEST_SLUG}.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"%PDF-1.4 fake")
        return pdf

    def _make_db_gen(self, mock_db: AsyncMock):
        """Async generator that yields mock_db once, mimicking get_db()."""
        async def _gen():
            yield mock_db
        return _gen

    @pytest.mark.asyncio
    async def test_legacy_retrigger_deletes_concept_chunks(self, tmp_path):
        """
        POST /api/admin/retrigger-book/{slug} must issue a DELETE against
        concept_chunks for the given book slug.
        """
        mock_db = _make_mock_db()
        app = _build_test_app(mock_db)  # needed only for routing; auth patched below
        pdf_path = self._make_pdf_path(tmp_path)

        with (
            patch.object(admin_router_module, "DATA_DIR", pdf_path.parent.parent),
            patch.object(admin_router_module, "OUTPUT_DIR", tmp_path / "output"),
            patch.object(admin_router_module, "derive_slug", return_value=_TEST_SLUG),
            patch.object(admin_router_module, "subprocess") as mock_sub,
            patch.object(admin_router_module, "invalidate_graph_cache"),
            patch("db.connection.get_db", self._make_db_gen(mock_db)),
        ):
            mock_sub.Popen = MagicMock()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/admin/retrigger-book/{_TEST_SLUG}",
                    headers=_API_HEADERS,
                )

        assert resp.status_code == 200

        executed_sqls = [
            str(call_args.args[0]) if call_args.args else ""
            for call_args in mock_db.execute.call_args_list
        ]
        assert any("concept_chunks" in sql for sql in executed_sqls), (
            "Expected a DELETE on concept_chunks in legacy endpoint"
        )

    @pytest.mark.asyncio
    async def test_legacy_retrigger_deletes_admin_graph_overrides(self, tmp_path):
        """
        POST /api/admin/retrigger-book/{slug} must also DELETE admin_graph_overrides
        so the legacy path is consistent with the new endpoint.
        """
        mock_db = _make_mock_db()
        app = _build_test_app(mock_db)
        pdf_path = self._make_pdf_path(tmp_path)

        with (
            patch.object(admin_router_module, "DATA_DIR", pdf_path.parent.parent),
            patch.object(admin_router_module, "OUTPUT_DIR", tmp_path / "output"),
            patch.object(admin_router_module, "derive_slug", return_value=_TEST_SLUG),
            patch.object(admin_router_module, "subprocess") as mock_sub,
            patch.object(admin_router_module, "invalidate_graph_cache"),
            patch("db.connection.get_db", self._make_db_gen(mock_db)),
        ):
            mock_sub.Popen = MagicMock()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/admin/retrigger-book/{_TEST_SLUG}",
                    headers=_API_HEADERS,
                )

        assert resp.status_code == 200

        executed_sqls = [
            str(call_args.args[0]) if call_args.args else ""
            for call_args in mock_db.execute.call_args_list
        ]
        assert any("admin_graph_overrides" in sql for sql in executed_sqls), (
            "Expected a DELETE on admin_graph_overrides in legacy endpoint"
        )

    @pytest.mark.asyncio
    async def test_legacy_retrigger_calls_invalidate_graph_cache(self, tmp_path):
        """
        POST /api/admin/retrigger-book/{slug} must call invalidate_graph_cache()
        so the stale cached graph is evicted before the pipeline re-populates it.
        """
        mock_db = _make_mock_db()
        app = _build_test_app(mock_db)
        pdf_path = self._make_pdf_path(tmp_path)

        with (
            patch.object(admin_router_module, "DATA_DIR", pdf_path.parent.parent),
            patch.object(admin_router_module, "OUTPUT_DIR", tmp_path / "output"),
            patch.object(admin_router_module, "derive_slug", return_value=_TEST_SLUG),
            patch.object(admin_router_module, "subprocess") as mock_sub,
            patch.object(
                admin_router_module, "invalidate_graph_cache"
            ) as mock_invalidate,
            patch("db.connection.get_db", self._make_db_gen(mock_db)),
        ):
            mock_sub.Popen = MagicMock()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/admin/retrigger-book/{_TEST_SLUG}",
                    headers=_API_HEADERS,
                )

        assert resp.status_code == 200
        mock_invalidate.assert_called_once_with(_TEST_SLUG)
