"""
test_untranslated_book_graceful.py
Safety-net tests: when Book and ConceptChunk have no translation data at all
(title_translations={}, heading_translations={}), every translated field must
fall back to the English column value — never empty, never null, never a slug.

Endpoints covered:
  - GET /api/v1/books
  - GET /api/v1/graph/full
  - GET /students/{id}/sessions
"""

import sys
import uuid
from datetime import datetime, timezone
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

import api.teaching_router as teaching_router_module
from api.rate_limiter import limiter
from db.connection import get_db
from auth.dependencies import get_current_user


_STUDENT_ID      = uuid.uuid4()
_EN_TITLE        = "English Only Book"
_EN_HEADING      = "English Only Heading"
_BOOK_SLUG       = "untranslated_test_book"


# ── Books app (no translations) ───────────────────────────────────────────────

def _build_books_app_no_translations() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter

    book = MagicMock()
    book.id = uuid.uuid4()
    book.book_slug = _BOOK_SLUG
    book.title = _EN_TITLE
    book.subject = "mathematics"
    book.status = "PUBLISHED"
    book.is_hidden = False
    book.title_translations = {}
    book.subject_translations = {}

    hidden_result = MagicMock()
    hidden_result.scalars.return_value.all.return_value = []
    books_result = MagicMock()
    books_result.scalars.return_value.all.return_value = [book]

    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=[hidden_result, books_result])

    async def _get_test_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_test_db

    @app.get("/api/v1/books")
    async def list_books_v1(request: Request, db: AsyncSession = Depends(get_db)):
        from db.models import Book as BookModel, Subject
        from api.dependencies import get_request_language, resolve_translation
        lang = await get_request_language(request, student=None)
        hidden_subj_rows = (await db.execute(
            select(Subject.slug).where(Subject.is_hidden == True)
        )).scalars().all()
        hidden_subjects = set(hidden_subj_rows)
        query = select(BookModel).where(
            BookModel.status == "PUBLISHED", BookModel.is_hidden == False
        )
        rows = (await db.execute(
            query.order_by(BookModel.subject, BookModel.title)
        )).scalars().all()
        return [
            {
                "slug": b.book_slug,
                "title": resolve_translation(b.title, b.title_translations or {}, lang),
                "subject": resolve_translation(b.subject, b.subject_translations or {}, lang),
                "has_translations": bool((b.title_translations or {}).get(lang)),
            }
            for b in rows
        ]

    return app


# ── Graph app (no translations) ───────────────────────────────────────────────

def _build_graph_app_no_translations() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter

    fake_book = MagicMock()
    fake_book.is_hidden = False
    fake_book.subject = "mathematics"
    book_result = MagicMock()
    book_result.scalar_one_or_none.return_value = fake_book
    subj_result = MagicMock()
    subj_result.scalar_one_or_none.return_value = None

    chunk_row = MagicMock()
    chunk_row.concept_id = f"{_BOOK_SLUG}_1.1"
    chunk_row.heading = _EN_HEADING
    chunk_row.heading_translations = {}
    chunk_result = MagicMock()
    chunk_result.all.return_value = [chunk_row]

    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=[book_result, subj_result, chunk_result])

    async def _get_test_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_test_db

    mock_ksvc = MagicMock()
    mock_ksvc.get_all_nodes.return_value = [
        {"concept_id": f"{_BOOK_SLUG}_1.1", "title": _EN_HEADING}
    ]
    mock_ksvc.get_all_edges.return_value = []

    @app.get("/api/v1/graph/full")
    async def graph_full(
        request: Request,
        book_slug: str = Query(_BOOK_SLUG),
        db: AsyncSession = Depends(get_db),
    ):
        from db.models import Book as BookModel, Subject, ConceptChunk as CC
        from api.dependencies import get_request_language, resolve_translation
        book = (await db.execute(
            select(BookModel).where(BookModel.book_slug == book_slug)
        )).scalar_one_or_none()
        if book.subject:
            (await db.execute(
                select(Subject).where(Subject.slug == book.subject)
            )).scalar_one_or_none()
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
            nodes = []
            for node in base_nodes:
                cid = node["concept_id"]
                if cid in heading_map:
                    en_heading, translations = heading_map[cid]
                    node = {**node, "title": resolve_translation(en_heading, translations, lang)}
                nodes.append(node)
        else:
            nodes = base_nodes
        return {"nodes": nodes, "edges": mock_ksvc.get_all_edges(book_slug)}

    return app


# ── Sessions app (no translations) ────────────────────────────────────────────

def _build_sessions_app_no_translations() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter

    fake_student = MagicMock()
    fake_student.id = _STUDENT_ID
    fake_student.preferred_language = "ml"
    fake_student.role = "student"
    fake_student.user_id = uuid.uuid4()

    session_row = {
        "id": uuid.uuid4(),
        "concept_id": f"{_BOOK_SLUG}_1.1",
        "book_slug": _BOOK_SLUG,
        "phase": "COMPLETED",
        "check_score": 90,
        "concept_mastered": True,
        "started_at": datetime.now(timezone.utc),
        "completed_at": datetime.now(timezone.utc),
        "chunk_heading": _EN_HEADING,
        "chunk_heading_tr": {},         # no translations
        "book_title_en": _EN_TITLE,
        "book_title_tr": {},            # no translations
    }

    sessions_result = MagicMock()
    sessions_result.mappings.return_value.all.return_value = [session_row]

    mock_db = AsyncMock(spec=AsyncSession)
    # Admin user bypasses _validate_student_ownership, so only the sessions query fires.
    mock_db.execute = AsyncMock(return_value=sessions_result)
    mock_db.get = AsyncMock(return_value=fake_student)

    async def _get_test_db():
        yield mock_db

    admin_user = MagicMock()
    admin_user.id = uuid.uuid4()
    admin_user.role = "admin"

    async def _get_admin_user():
        return admin_user

    app.dependency_overrides[get_db] = _get_test_db
    app.dependency_overrides[get_current_user] = _get_admin_user

    mock_chunk_ksvc = MagicMock()
    mock_svc = MagicMock()
    mock_svc.knowledge_services = {}
    teaching_router_module.chunk_ksvc = mock_chunk_ksvc
    teaching_router_module.teaching_svc = mock_svc

    app.include_router(teaching_router_module.router)
    return app


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestUntranslatedBookGraceful:
    """All three endpoints must never return empty/null/slug when translations={}."""

    async def test_books_endpoint_falls_back_to_english_title(self):
        """GET /api/v1/books with Accept-Language: ml → English title (no translations)."""
        app = _build_books_app_no_translations()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/books", headers={"Accept-Language": "ml"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == _EN_TITLE
        assert data[0]["title"] != ""
        assert data[0]["title"] is not None

    async def test_graph_endpoint_falls_back_to_english_heading(self):
        """GET /api/v1/graph/full with Accept-Language: ml → English heading (no translations)."""
        app = _build_graph_app_no_translations()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/graph/full",
                params={"book_slug": _BOOK_SLUG},
                headers={"Accept-Language": "ml"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["title"] == _EN_HEADING
        assert data["nodes"][0]["title"] != ""

    async def test_sessions_endpoint_falls_back_to_english_titles(self):
        """GET /students/{id}/sessions student lang=ml, no translations → English values."""
        app = _build_sessions_app_no_translations()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v2/students/{_STUDENT_ID}/sessions")
        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["concept_title"] == _EN_HEADING
        assert sessions[0]["book_title"] == _EN_TITLE
        assert sessions[0]["concept_title"] != ""
        assert sessions[0]["book_title"] != ""
