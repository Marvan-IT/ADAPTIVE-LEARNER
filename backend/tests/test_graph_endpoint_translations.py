"""
test_graph_endpoint_translations.py
Integration tests for GET /api/v1/graph/full translation overlay.

Strategy: replicate the real endpoint in a lightweight FastAPI app; inject
a mock DB and a mock ChunkKnowledgeService.  No live PostgreSQL needed.

Tests:
  - Accept-Language: ml → node with ml translation shows Malayalam title
  - Accept-Language: hi (untranslated) → node shows English title
  - Nodes with no chunk entry keep their English title unchanged
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

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
from fastapi import FastAPI, Request, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.connection import get_db
from api.rate_limiter import limiter


# ── Fake chunk row ────────────────────────────────────────────────────────────

def _make_chunk_row(concept_id: str, heading: str, heading_translations: dict) -> MagicMock:
    row = MagicMock()
    row.concept_id = concept_id
    row.heading = heading
    row.heading_translations = heading_translations
    return row


# ── Build test app ────────────────────────────────────────────────────────────

def _build_graph_app(
    chunk_rows: list,
    nodes: list[dict],
    edges: list[dict],
    book_slug_to_test: str = "testbook",
) -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter

    # Mock DB: first execute = _require_visible_book book query,
    #          second execute = heading_translations SELECT
    fake_book = MagicMock()
    fake_book.is_hidden = False
    fake_book.subject = "mathematics"

    book_result = MagicMock()
    book_result.scalar_one_or_none.return_value = fake_book

    subj_result = MagicMock()
    subj_result.scalar_one_or_none.return_value = None  # subject not hidden

    chunk_result = MagicMock()
    chunk_result.all.return_value = chunk_rows

    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=[book_result, subj_result, chunk_result])

    async def _get_test_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_test_db

    # Mock ChunkKnowledgeService
    mock_ksvc = MagicMock()
    mock_ksvc.get_all_nodes.return_value = nodes
    mock_ksvc.get_all_edges.return_value = edges

    @app.get("/api/v1/graph/full")
    async def graph_full(
        request: Request,
        book_slug: str = Query(book_slug_to_test),
        db: AsyncSession = Depends(get_db),
    ):
        from db.models import Book as BookModel, Subject, ConceptChunk as CC
        from api.dependencies import get_request_language, resolve_translation

        # _require_visible_book logic
        book = (await db.execute(
            select(BookModel).where(BookModel.book_slug == book_slug)
        )).scalar_one_or_none()
        if not book or book.is_hidden:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Book not found")
        if book.subject:
            subj = (await db.execute(
                select(Subject).where(Subject.slug == book.subject)
            )).scalar_one_or_none()
            if subj and subj.is_hidden:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Book not found")

        lang = await get_request_language(request, student=None)

        rows = (await db.execute(
            select(CC.concept_id, CC.heading, CC.heading_translations)
            .where(CC.book_slug == book_slug)
        )).all()
        heading_map = {
            row.concept_id: (row.heading, row.heading_translations or {})
            for row in rows
        }

        base_nodes = mock_ksvc.get_all_nodes(book_slug)
        if lang != "en":
            translated_nodes = []
            for node in base_nodes:
                cid = node["concept_id"]
                if cid in heading_map:
                    en_heading, translations = heading_map[cid]
                    node = {**node, "title": resolve_translation(en_heading, translations, lang)}
                translated_nodes.append(node)
        else:
            translated_nodes = base_nodes

        return {"nodes": translated_nodes, "edges": mock_ksvc.get_all_edges(book_slug)}

    return app


async def _get_graph(app: FastAPI, headers: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(
            "/api/v1/graph/full",
            params={"book_slug": "testbook"},
            headers=headers or {},
        )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestGraphEndpointTranslations:
    """GET /api/v1/graph/full — heading translation overlay tests."""

    async def test_ml_header_returns_malayalam_node_title(self):
        """
        Accept-Language: ml → node for a concept with ml translation
        returns Malayalam title.
        """
        chunk_row = _make_chunk_row(
            "testbook_1.1", "Introduction", {"ml": "പരിചയം"}
        )
        nodes = [{"concept_id": "testbook_1.1", "title": "Introduction"}]
        app = _build_graph_app([chunk_row], nodes, [])
        resp = await _get_graph(app, headers={"Accept-Language": "ml"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["title"] == "പരിചയം"

    async def test_hi_header_returns_english_when_untranslated(self):
        """
        Accept-Language: hi when no hi translation exists → English heading.
        """
        chunk_row = _make_chunk_row(
            "testbook_1.1", "Introduction", {"ml": "പരിചയം"}
        )
        nodes = [{"concept_id": "testbook_1.1", "title": "Introduction"}]
        app = _build_graph_app([chunk_row], nodes, [])
        resp = await _get_graph(app, headers={"Accept-Language": "hi"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"][0]["title"] == "Introduction"

    async def test_nodes_without_chunk_entry_keep_english_title(self):
        """
        A node whose concept_id has no matching chunk row retains its English title.
        """
        # Only chunk for concept _1.1; node _1.2 has no matching chunk
        chunk_row = _make_chunk_row("testbook_1.1", "Intro", {"ml": "ആമുഖം"})
        nodes = [
            {"concept_id": "testbook_1.1", "title": "Intro"},
            {"concept_id": "testbook_1.2", "title": "Variables"},
        ]
        app = _build_graph_app([chunk_row], nodes, [])
        resp = await _get_graph(app, headers={"Accept-Language": "ml"})
        assert resp.status_code == 200
        data = resp.json()
        titles = {n["concept_id"]: n["title"] for n in data["nodes"]}
        assert titles["testbook_1.1"] == "ആമുഖം"
        assert titles["testbook_1.2"] == "Variables"

    async def test_en_header_skips_translation_overlay(self):
        """Accept-Language: en → original English nodes returned without modification."""
        chunk_row = _make_chunk_row("testbook_1.1", "Introduction", {"ml": "പരിചയം"})
        nodes = [{"concept_id": "testbook_1.1", "title": "Introduction"}]
        app = _build_graph_app([chunk_row], nodes, [])
        resp = await _get_graph(app, headers={"Accept-Language": "en"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"][0]["title"] == "Introduction"
