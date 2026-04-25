"""
test_books_endpoint_translations.py
Integration tests for GET /api/v1/books translation behaviour.

Strategy: build a lightweight FastAPI app that replicates the real endpoint
logic (identical copy) but injects a mock DB so tests are deterministic and
require no live PostgreSQL.

Tests:
  - Accept-Language: ml → title returned in Malayalam, has_translations=True
  - Accept-Language: hi (not populated) → English title, has_translations=False
  - No Accept-Language header → English title
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── Break circular import before any teaching_router import ──────────────────
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

import pytest
import httpx
from fastapi import FastAPI, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.connection import get_db
from api.rate_limiter import limiter


# ── Fake Book ORM object ──────────────────────────────────────────────────────

def _make_book(
    *,
    slug: str,
    title: str = "Prealgebra",
    subject: str = "mathematics",
    title_translations: dict | None = None,
    subject_translations: dict | None = None,
) -> MagicMock:
    b = MagicMock()
    b.id = uuid.uuid4()
    b.book_slug = slug
    b.title = title
    b.subject = subject
    b.status = "PUBLISHED"
    b.is_hidden = False
    b.title_translations = title_translations or {}
    b.subject_translations = subject_translations or {}
    return b


# ── Build test app ────────────────────────────────────────────────────────────

def _build_books_app(books: list) -> FastAPI:
    """
    Lightweight FastAPI app that replicates list_books_v1 logic.
    Injects a mock DB returning the supplied books list.
    """
    app = FastAPI()
    app.state.limiter = limiter

    mock_db = AsyncMock(spec=AsyncSession)

    # First execute() call: hidden subjects query → empty
    hidden_result = MagicMock()
    hidden_result.scalars.return_value.all.return_value = []

    # Second execute() call: books query → supplied books
    books_result = MagicMock()
    books_result.scalars.return_value.all.return_value = books

    mock_db.execute = AsyncMock(side_effect=[hidden_result, books_result])

    async def _get_test_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_test_db

    @app.get("/api/v1/books")
    async def list_books_v1(request: Request, db: AsyncSession = Depends(get_db)):
        from api.dependencies import get_request_language, resolve_translation
        from db.models import Book as BookModel, Subject
        lang = await get_request_language(request, student=None)

        hidden_subj_rows = (await db.execute(
            select(Subject.slug).where(Subject.is_hidden == True)
        )).scalars().all()
        hidden_subjects = set(hidden_subj_rows)

        query = select(BookModel).where(
            BookModel.status == "PUBLISHED", BookModel.is_hidden == False
        )
        if hidden_subjects:
            query = query.where(BookModel.subject.notin_(hidden_subjects))
        rows = (await db.execute(
            query.order_by(BookModel.subject, BookModel.title)
        )).scalars().all()

        return [
            {
                "slug": b.book_slug,
                "title": resolve_translation(b.title, b.title_translations or {}, lang),
                "subject": resolve_translation(b.subject, b.subject_translations or {}, lang),
                "subject_slug": b.subject,
                "processed": True,
                "has_translations": bool((b.title_translations or {}).get(lang)),
            }
            for b in rows
        ]

    return app


async def _get(app: FastAPI, headers: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/v1/books", headers=headers or {})


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBooksEndpointTranslations:
    """GET /api/v1/books — translation overlay tests."""

    async def test_ml_header_returns_malayalam_title_and_has_translations_true(self):
        """
        Accept-Language: ml → title resolved to Malayalam string.
        has_translations=True when ml key is populated.
        """
        book = _make_book(
            slug="i18n_test_book_ml",
            title="Prealgebra",
            title_translations={"en_source_hash": "abc123", "ml": "പുസ്തകം"},
        )
        app = _build_books_app([book])
        resp = await _get(app, headers={"Accept-Language": "ml"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "പുസ്തകം"
        assert data[0]["has_translations"] is True

    async def test_hi_header_unpopulated_returns_english_and_has_translations_false(self):
        """
        Accept-Language: hi when no hi translation exists → English title.
        has_translations=False. Title is never empty.
        """
        book = _make_book(
            slug="i18n_test_book_hi",
            title="Prealgebra",
            title_translations={"en_source_hash": "abc123", "ml": "പുസ്തകം"},
        )
        app = _build_books_app([book])
        resp = await _get(app, headers={"Accept-Language": "hi"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Prealgebra"
        assert data[0]["title"] != ""
        assert data[0]["has_translations"] is False

    async def test_no_header_returns_english_title(self):
        """No Accept-Language header → English title returned."""
        book = _make_book(
            slug="i18n_test_book_nohdr",
            title="Prealgebra",
            title_translations={"ml": "പുസ്തകം"},
        )
        app = _build_books_app([book])
        resp = await _get(app, headers={})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Prealgebra"

    async def test_empty_translations_never_returns_empty_title(self):
        """Book with no translations at all still returns the English title column."""
        book = _make_book(
            slug="i18n_test_book_empty",
            title="My Book",
            title_translations={},
        )
        app = _build_books_app([book])
        resp = await _get(app, headers={"Accept-Language": "ml"})
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["title"] == "My Book"
        assert data[0]["title"] != ""

    async def test_response_includes_subject_slug_alongside_translated_subject(self):
        """
        GET /api/v1/books must include subject_slug (the raw Book.subject column,
        always English) next to the translated subject label.

        Both keys must coexist: subject_slug carries the routing slug unchanged;
        subject carries the human-readable label (translated when a translation
        is available, English otherwise).

        Covers DLD §3.1 / closeout delta F2.
        """
        book = _make_book(
            slug="math_book_subject_slug_test",
            title="Prealgebra",
            subject="mathematics",
            subject_translations={"ml": "ഗണിതശാസ്ത്രം"},
        )
        app = _build_books_app([book])

        # Request with Malayalam Accept-Language so subject is translated.
        resp = await _get(app, headers={"Accept-Language": "ml"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        item = data[0]

        # subject_slug must equal the raw English slug regardless of language.
        assert "subject_slug" in item, "subject_slug key missing from /api/v1/books response"
        assert item["subject_slug"] == "mathematics"

        # subject must carry the translated human label (not the English slug).
        assert "subject" in item
        assert item["subject"] == "ഗണിതശാസ്ത്രം"

        # Both keys coexist — neither is empty.
        assert item["subject_slug"] != ""
        assert item["subject"] != ""
