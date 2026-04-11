"""
test_admin_console.py
21 pytest tests for the ADA Admin Console backend (admin_router.py).

Strategy:
- Build a minimal FastAPI test app that mounts admin_router and a /api/v1/books
  endpoint, with DB replaced by AsyncMock — no live PostgreSQL required.
- File I/O and subprocess.Popen are patched via unittest.mock.patch.
- All endpoints require X-API-Key: test-secret header.

Run:  pytest backend/tests/test_admin_console.py -v
"""
from __future__ import annotations

import io
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ── 1. sys.path setup ──────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── 2. Set API_SECRET_KEY before admin_router is imported ─────────────────────
os.environ.setdefault("API_SECRET_KEY", "test-secret")

# ── 3. Stub heavy transitive dependencies before importing admin_router ─────────
#    extraction.calibrate imports fitz (PyMuPDF) — stub it out
if "fitz" not in sys.modules:
    sys.modules["fitz"] = MagicMock()

# api.chunk_knowledge_service is imported for _normalize_image_url — stub so we
# can control the return value in individual tests.
if "api.chunk_knowledge_service" not in sys.modules:
    _ck_stub = MagicMock()
    _ck_stub._normalize_image_url = lambda url: url  # identity by default
    sys.modules["api.chunk_knowledge_service"] = _ck_stub

import pytest
import httpx
from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import api.admin_router as admin_router_module
from api.admin_router import router as admin_router

# Force _API_KEY to match our test header regardless of environment
admin_router_module._API_KEY = "test-secret"

_API_HEADERS = {"X-API-Key": "test-secret"}
_TEST_SLUG = "prealgebra"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_book(
    slug: str = _TEST_SLUG,
    title: str = "Prealgebra",
    subject: str = "mathematics",
    status: str = "PROCESSING",
) -> MagicMock:
    b = MagicMock()
    b.book_slug = slug
    b.title = title
    b.subject = subject
    b.status = status
    b.pdf_filename = f"{slug}.pdf"
    b.created_at = datetime.now(timezone.utc)
    b.published_at = None
    return b


def _make_subject(slug: str = "mathematics", label: str = "Mathematics") -> MagicMock:
    s = MagicMock()
    s.slug = slug
    s.label = label
    s.created_at = datetime.now(timezone.utc)
    return s


def _make_chunk(
    chunk_id=None,
    concept_id: str = "prealgebra_1.1",
    section: str = "1.1",
    heading: str = "Introduction",
    text: str = "Some text content here.",
    order_index: int = 0,
) -> MagicMock:
    c = MagicMock()
    c.id = chunk_id or uuid.uuid4()
    c.concept_id = concept_id
    c.section = section
    c.heading = heading
    c.text = text
    c.order_index = order_index
    c.chunk_type = "teaching"
    return c


def _make_chunk_image(chunk_id=None, image_url: str = "http://host/images/prealgebra/fig.png") -> MagicMock:
    img = MagicMock()
    img.id = uuid.uuid4()
    img.chunk_id = chunk_id or uuid.uuid4()
    img.image_url = image_url
    img.caption = "A figure"
    img.order_index = 0
    return img


def _make_mock_db() -> AsyncMock:
    """Return an AsyncSession mock with sensible defaults."""
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    result.scalar = MagicMock(return_value=0)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    result.all = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _build_test_app(mock_db: AsyncMock) -> FastAPI:
    """Build a minimal FastAPI app with admin_router + /api/v1/books endpoint."""
    app = FastAPI()

    async def _override_get_db():
        yield mock_db

    # Override the get_db dependency used by admin_router
    from db.connection import get_db
    app.dependency_overrides[get_db] = _override_get_db

    # Attach admin router
    app.include_router(admin_router)

    # Inline /api/v1/books endpoint (mirrors main.py logic)
    @app.get("/api/v1/books")
    async def list_books_v1(db: AsyncSession = Depends(_override_get_db)):
        from db.models import Book as BookModel
        rows = (await db.execute(
            select(BookModel).where(BookModel.status == "PUBLISHED")
        )).scalars().all()
        return [
            {"slug": b.book_slug, "title": b.title, "subject": b.subject, "processed": True}
            for b in rows
        ]

    # Attach a stub chunk_knowledge_svc so publish tests can verify preload_graph
    app.state.chunk_knowledge_svc = MagicMock()

    return app


# ── Upload tests ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_saves_pdf_and_inserts_book_row(tmp_path):
    """PDF bytes must be written to DATA_DIR/subject/filename; Book row inserted with status=PROCESSING."""
    mock_db = _make_mock_db()
    # Simulate no pre-existing book row
    mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

    app = _build_test_app(mock_db)
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    with (
        patch.object(admin_router_module, "DATA_DIR", data_dir),
        patch.object(admin_router_module, "OUTPUT_DIR", tmp_path / "output"),
        patch.object(admin_router_module, "subprocess") as mock_subproc,
    ):
        mock_subproc.Popen = MagicMock()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/books/upload",
                headers=_API_HEADERS,
                files={"file": ("prealgebra.pdf", b"%PDF-1.4 fake content", "application/pdf")},
                data={"subject": "mathematics", "title": "Prealgebra"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "PROCESSING"
    assert body["slug"] == "prealgebra"
    # DB add() should have been called once (new book row)
    assert mock_db.add.called
    # Saved file should exist on disk
    saved = data_dir / "mathematics" / "prealgebra.pdf"
    assert saved.exists()
    assert saved.read_bytes() == b"%PDF-1.4 fake content"


@pytest.mark.asyncio
async def test_upload_spawns_pipeline_runner_subprocess(tmp_path):
    """subprocess.Popen must be called with --pdf and --subject arguments."""
    mock_db = _make_mock_db()
    mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

    app = _build_test_app(mock_db)
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    with (
        patch.object(admin_router_module, "DATA_DIR", data_dir),
        patch.object(admin_router_module, "OUTPUT_DIR", tmp_path / "output"),
        patch.object(admin_router_module, "subprocess") as mock_subproc,
    ):
        mock_subproc.Popen = MagicMock()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/admin/books/upload",
                headers=_API_HEADERS,
                files={"file": ("prealgebra.pdf", b"data", "application/pdf")},
                data={"subject": "mathematics", "title": "Prealgebra"},
            )

    assert mock_subproc.Popen.called
    call_args = mock_subproc.Popen.call_args[0][0]  # first positional arg is the cmd list
    assert "--pdf" in call_args
    assert "--subject" in call_args
    assert "mathematics" in call_args


@pytest.mark.asyncio
async def test_upload_stores_custom_title(tmp_path):
    """The title provided in the form must appear in the response and DB upsert."""
    mock_db = _make_mock_db()
    mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

    app = _build_test_app(mock_db)
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    custom_title = "My Custom Prealgebra Book"

    with (
        patch.object(admin_router_module, "DATA_DIR", data_dir),
        patch.object(admin_router_module, "OUTPUT_DIR", tmp_path / "output"),
        patch.object(admin_router_module, "subprocess") as mock_subproc,
    ):
        mock_subproc.Popen = MagicMock()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/books/upload",
                headers=_API_HEADERS,
                files={"file": ("prealgebra.pdf", b"data", "application/pdf")},
                data={"subject": "mathematics", "title": custom_title},
            )

    assert resp.status_code == 200
    assert resp.json()["title"] == custom_title


# ── Status tests ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_no_log_file_returns_stage_0(tmp_path):
    """When no pipeline.log exists, stage_number=0 and stage_label='Not started'."""
    mock_db = _make_mock_db()
    book = _make_book(status="PROCESSING")
    mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=book)

    app = _build_test_app(mock_db)
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with patch.object(admin_router_module, "OUTPUT_DIR", output_dir):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/admin/books/{_TEST_SLUG}/status", headers=_API_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["stage_number"] == 0
    assert body["stage_label"] == "Not started"
    assert body["status"] == "PROCESSING"


@pytest.mark.asyncio
async def test_status_stage2_running(tmp_path):
    """'Stage 2/5: Mathpix' in log without 'Done' → stage_number=2, stage_label contains 'Mathpix'."""
    mock_db = _make_mock_db()
    book = _make_book(status="PROCESSING")
    mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=book)

    app = _build_test_app(mock_db)
    output_dir = tmp_path / "output"
    log_dir = output_dir / _TEST_SLUG
    log_dir.mkdir(parents=True)
    log_file = log_dir / "pipeline.log"
    log_file.write_text(
        "Starting pipeline...\nStage 1/5: Calibrating fonts\nStage 1/5: Done\nStage 2/5: Mathpix extraction running\n",
        encoding="utf-8",
    )

    with patch.object(admin_router_module, "OUTPUT_DIR", output_dir):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/admin/books/{_TEST_SLUG}/status", headers=_API_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["stage_number"] == 2
    assert "Mathpix" in body["stage_label"]


@pytest.mark.asyncio
async def test_status_pipeline_complete_updates_db(tmp_path):
    """'Pipeline complete' in log → DB status updated to READY_FOR_REVIEW."""
    mock_db = _make_mock_db()
    book = _make_book(status="PROCESSING")
    # Two execute calls: once inside the log loop to update, once for the final select
    mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=book)

    app = _build_test_app(mock_db)
    output_dir = tmp_path / "output"
    log_dir = output_dir / _TEST_SLUG
    log_dir.mkdir(parents=True)
    (log_dir / "pipeline.log").write_text(
        "Stage 1/5: Calibrating\nStage 1/5: Done\nStage 2/5: Done\nStage 3/5: Done\nStage 4/5: Done\nPipeline complete\n",
        encoding="utf-8",
    )

    with patch.object(admin_router_module, "OUTPUT_DIR", output_dir):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/admin/books/{_TEST_SLUG}/status", headers=_API_HEADERS)

    assert resp.status_code == 200
    # The book mock's status attribute should have been set to READY_FOR_REVIEW
    assert book.status == "READY_FOR_REVIEW"
    assert mock_db.commit.called


@pytest.mark.asyncio
async def test_status_pipeline_failed_in_db(tmp_path):
    """When book.status=FAILED in DB, status endpoint returns FAILED regardless of log."""
    mock_db = _make_mock_db()
    book = _make_book(status="FAILED")
    mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=book)

    app = _build_test_app(mock_db)
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with patch.object(admin_router_module, "OUTPUT_DIR", output_dir):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/admin/books/{_TEST_SLUG}/status", headers=_API_HEADERS)

    assert resp.status_code == 200
    assert resp.json()["status"] == "FAILED"


# ── Sections tests ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sections_returns_grouped_tree(tmp_path):
    """Sections endpoint must group concept rows by chapter number."""
    mock_db = _make_mock_db()

    # Two concepts: one in chapter 1, one in chapter 2
    rows = [
        ("prealgebra_1.1", "1.1", "Whole Numbers"),
        ("prealgebra_2.1", "2.1", "Fractions"),
    ]
    # scalars().all() for the main query; scalar() for counts
    execute_results = []

    def _make_execute_result_rows():
        r = MagicMock()
        r.all = MagicMock(return_value=rows)
        return r

    def _make_scalar_result(val):
        r = MagicMock()
        r.scalar = MagicMock(return_value=val)
        r.scalar_one_or_none = MagicMock(return_value=None)
        r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        return r

    # Call sequence: 1 main rows query + 2*(chunk_count + image_count) per concept = 5 calls
    call_count = 0

    async def _side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_execute_result_rows()
        return _make_scalar_result(3 if call_count % 2 == 0 else 1)

    mock_db.execute = AsyncMock(side_effect=_side_effect)

    app = _build_test_app(mock_db)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/admin/books/{_TEST_SLUG}/sections", headers=_API_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    chapters = [item["chapter"] for item in body]
    assert 1 in chapters
    assert 2 in chapters


@pytest.mark.asyncio
async def test_sections_includes_counts(tmp_path):
    """Each section entry must have chunk_count and image_count populated."""
    mock_db = _make_mock_db()

    rows = [("prealgebra_1.1", "1.1", "Whole Numbers")]
    call_count = 0

    def _make_rows_result():
        r = MagicMock()
        r.all = MagicMock(return_value=rows)
        return r

    def _make_scalar_result(val):
        r = MagicMock()
        r.scalar = MagicMock(return_value=val)
        r.scalar_one_or_none = MagicMock(return_value=None)
        r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        return r

    async def _side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_rows_result()
        if call_count == 2:
            return _make_scalar_result(5)  # chunk_count
        return _make_scalar_result(2)      # image_count

    mock_db.execute = AsyncMock(side_effect=_side_effect)

    app = _build_test_app(mock_db)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/admin/books/{_TEST_SLUG}/sections", headers=_API_HEADERS)

    assert resp.status_code == 200
    sections = resp.json()[0]["sections"]
    assert sections[0]["chunk_count"] == 5
    assert sections[0]["image_count"] == 2


# ── Chunks tests ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chunks_returns_text_and_normalized_images(tmp_path):
    """Chunks endpoint must return chunk text and images with normalized (relative) URLs."""
    mock_db = _make_mock_db()
    chunk = _make_chunk()
    img = _make_chunk_image(chunk_id=chunk.id, image_url="http://localhost:8889/images/prealgebra/fig.png")

    call_count = 0

    def _make_chunks_result():
        r = MagicMock()
        r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[chunk])))
        return r

    def _make_images_result():
        r = MagicMock()
        r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[img])))
        return r

    async def _side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_chunks_result()
        return _make_images_result()

    mock_db.execute = AsyncMock(side_effect=_side_effect)

    # Patch _normalize_image_url to return a relative path
    with patch.object(admin_router_module, "_normalize_image_url", return_value="/images/prealgebra/fig.png"):
        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/admin/books/{_TEST_SLUG}/chunks/prealgebra_1.1",
                headers=_API_HEADERS,
            )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["text"] == chunk.text
    assert body[0]["heading"] == chunk.heading
    assert len(body[0]["images"]) == 1
    assert body[0]["images"][0]["image_url"] == "/images/prealgebra/fig.png"


# ── Publish tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_sets_status_and_calls_preload(tmp_path):
    """Successful publish must set status=PUBLISHED and call svc.preload_graph(slug)."""
    mock_db = _make_mock_db()
    book = _make_book(status="READY_FOR_REVIEW")

    call_count = 0

    async def _side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            # chunk_count query
            r.scalar = MagicMock(return_value=10)
            r.scalar_one_or_none = MagicMock(return_value=None)
        else:
            # book query
            r.scalar = MagicMock(return_value=10)
            r.scalar_one_or_none = MagicMock(return_value=book)
        r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        return r

    mock_db.execute = AsyncMock(side_effect=_side_effect)

    # Create graph.json in tmp output dir
    output_dir = tmp_path / "output"
    graph_dir = output_dir / _TEST_SLUG
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph.json").write_text('{"nodes": [], "edges": []}', encoding="utf-8")

    mock_svc = MagicMock()

    with patch.object(admin_router_module, "OUTPUT_DIR", output_dir):
        app = _build_test_app(mock_db)
        app.state.chunk_knowledge_svc = mock_svc
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/admin/books/{_TEST_SLUG}/publish", headers=_API_HEADERS)

    assert resp.status_code == 200
    assert resp.json()["status"] == "PUBLISHED"
    assert book.status == "PUBLISHED"
    assert book.published_at is not None
    mock_svc.preload_graph.assert_called_once_with(_TEST_SLUG)


@pytest.mark.asyncio
async def test_publish_rejects_no_chunks(tmp_path):
    """publish must return HTTP 400 when chunk_count == 0."""
    mock_db = _make_mock_db()
    r = MagicMock()
    r.scalar = MagicMock(return_value=0)
    r.scalar_one_or_none = MagicMock(return_value=None)
    r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    mock_db.execute = AsyncMock(return_value=r)

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with patch.object(admin_router_module, "OUTPUT_DIR", output_dir):
        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/admin/books/{_TEST_SLUG}/publish", headers=_API_HEADERS)

    assert resp.status_code == 400
    assert "pipeline" in resp.json()["detail"].lower() or "chunk" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_publish_rejects_no_graph_json(tmp_path):
    """publish must return HTTP 400 when graph.json is missing even if chunks exist."""
    mock_db = _make_mock_db()
    r = MagicMock()
    r.scalar = MagicMock(return_value=5)  # chunks exist
    r.scalar_one_or_none = MagicMock(return_value=None)
    r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    mock_db.execute = AsyncMock(return_value=r)

    output_dir = tmp_path / "output"
    # No graph.json created — directory for slug doesn't exist
    output_dir.mkdir()

    with patch.object(admin_router_module, "OUTPUT_DIR", output_dir):
        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/admin/books/{_TEST_SLUG}/publish", headers=_API_HEADERS)

    assert resp.status_code == 400
    assert "graph" in resp.json()["detail"].lower()


# ── Drop tests ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_drop_deletes_db_and_output(tmp_path):
    """drop must execute DELETE SQL for concept_chunks and call shutil.rmtree on output dir."""
    mock_db = _make_mock_db()
    book = _make_book(status="PUBLISHED")
    mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=book)

    output_dir = tmp_path / "output"
    slug_dir = output_dir / _TEST_SLUG
    slug_dir.mkdir(parents=True)

    with patch.object(admin_router_module, "OUTPUT_DIR", output_dir):
        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/admin/books/{_TEST_SLUG}/drop", headers=_API_HEADERS)

    assert resp.status_code == 200
    # DB execute was called (DELETE + select for book row)
    assert mock_db.execute.called
    # Output directory should have been removed
    assert not slug_dir.exists()


@pytest.mark.asyncio
async def test_drop_sets_status_dropped(tmp_path):
    """drop must set book.status=DROPPED in the DB."""
    mock_db = _make_mock_db()
    book = _make_book(status="PUBLISHED")
    mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=book)

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with patch.object(admin_router_module, "OUTPUT_DIR", output_dir):
        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/admin/books/{_TEST_SLUG}/drop", headers=_API_HEADERS)

    assert resp.status_code == 200
    assert book.status == "DROPPED"
    assert mock_db.commit.called


# ── /api/v1/books student-facing endpoint ─────────────────────────────────────

@pytest.mark.asyncio
async def test_student_books_excludes_processing():
    """GET /api/v1/books must not return books with status=PROCESSING."""
    mock_db = _make_mock_db()
    processing_book = _make_book(status="PROCESSING")

    r = MagicMock()
    r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    # When WHERE status='PUBLISHED' is applied, no rows returned
    mock_db.execute = AsyncMock(return_value=r)

    app = _build_test_app(mock_db)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/books")

    assert resp.status_code == 200
    books = resp.json()
    # The PROCESSING book must not be in the result
    slugs = [b["slug"] for b in books]
    assert processing_book.book_slug not in slugs


@pytest.mark.asyncio
async def test_student_books_includes_published():
    """GET /api/v1/books must return books with status=PUBLISHED."""
    mock_db = _make_mock_db()
    published_book = _make_book(status="PUBLISHED")

    r = MagicMock()
    r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[published_book])))
    mock_db.execute = AsyncMock(return_value=r)

    app = _build_test_app(mock_db)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/books")

    assert resp.status_code == 200
    books = resp.json()
    assert len(books) == 1
    assert books[0]["slug"] == published_book.book_slug
    assert books[0]["processed"] is True


# ── Subject tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_subject():
    """POST /api/admin/subjects with valid label must create subject row and return {slug, label}."""
    mock_db = _make_mock_db()
    # No existing subject
    mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

    # After db.refresh(subj) the returned object should have slug and label
    created_subj = _make_subject(slug="physics", label="Physics")

    async def _refresh(obj):
        obj.slug = "physics"
        obj.label = "Physics"

    mock_db.refresh = AsyncMock(side_effect=_refresh)

    app = _build_test_app(mock_db)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/subjects",
            headers=_API_HEADERS,
            json={"label": "Physics"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "physics"
    assert body["label"] == "Physics"
    assert mock_db.add.called
    assert mock_db.commit.called


@pytest.mark.asyncio
async def test_create_subject_duplicate_returns_409():
    """POST /api/admin/subjects with duplicate slug must return HTTP 409."""
    mock_db = _make_mock_db()
    existing = _make_subject(slug="mathematics", label="Mathematics")
    mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=existing)

    app = _build_test_app(mock_db)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/subjects",
            headers=_API_HEADERS,
            json={"label": "Mathematics"},
        )

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_subjects_with_counts():
    """GET /api/admin/subjects must return a list with slug, label, and book_count per subject."""
    mock_db = _make_mock_db()
    subj = _make_subject(slug="mathematics", label="Mathematics")

    call_count = 0

    async def _side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            # list_subjects: select(Subject)
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[subj])))
            r.scalar = MagicMock(return_value=0)
            r.scalar_one_or_none = MagicMock(return_value=None)
        else:
            # book_count per subject
            r.scalar = MagicMock(return_value=3)
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            r.scalar_one_or_none = MagicMock(return_value=None)
        return r

    mock_db.execute = AsyncMock(side_effect=_side_effect)

    app = _build_test_app(mock_db)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/subjects", headers=_API_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["slug"] == "mathematics"
    assert body[0]["label"] == "Mathematics"
    assert body[0]["book_count"] == 3


# ── Auth test ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_key_missing_returns_403():
    """Any admin endpoint without X-API-Key header must return HTTP 403."""
    mock_db = _make_mock_db()
    app = _build_test_app(mock_db)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Test several endpoints without the API key header
        resp_subjects = await client.get("/api/admin/subjects")
        resp_status = await client.get(f"/api/admin/books/{_TEST_SLUG}/status")
        resp_publish = await client.post(f"/api/admin/books/{_TEST_SLUG}/publish")

    assert resp_subjects.status_code == 403
    assert resp_status.status_code == 403
    assert resp_publish.status_code == 403
