"""
test_sessions_endpoint_translations.py
Integration tests for GET /students/{id}/sessions translation behaviour.

Strategy: build a synthetic FastAPI app with the real teaching_router included,
override get_db with a mock that returns pre-built mapping rows (matching the
LATERAL join result shape), override get_current_user with an admin stub to
bypass ownership checks.  No live PostgreSQL needed.

Tests:
  - Student with preferred_language='ml' → concept_title and book_title in Malayalam
  - Student with preferred_language='en' → both fields revert to English
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
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

import api.teaching_router as teaching_router_module
from api.rate_limiter import limiter
from db.connection import get_db
from auth.dependencies import get_current_user


# ── Constants ─────────────────────────────────────────────────────────────────

_STUDENT_ID = uuid.uuid4()

_EN_CONCEPT_HEADING     = "Data Collection"
_ML_CONCEPT_HEADING     = "ഡാറ്റ ശേഖരണം"
_EN_BOOK_TITLE          = "Business Statistics"
_ML_BOOK_TITLE          = "ബിസിനസ് സ്ഥിതിവിവരക്കണക്ക്"

_HEADING_TRANSLATIONS   = {"ml": _ML_CONCEPT_HEADING}
_BOOK_TITLE_TRANSLATIONS = {"ml": _ML_BOOK_TITLE}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_fake_student(preferred_language: str) -> MagicMock:
    s = MagicMock()
    s.id = _STUDENT_ID
    s.preferred_language = preferred_language
    s.role = "student"
    s.user_id = uuid.uuid4()
    return s


def _make_session_row(concept_id: str = "bs_1.1") -> dict:
    """Return a dict that mirrors the LATERAL join's .mappings() shape."""
    return {
        "id": uuid.uuid4(),
        "concept_id": concept_id,
        "book_slug": "business_statistics",
        "phase": "COMPLETED",
        "check_score": 85,
        "concept_mastered": True,
        "started_at": datetime.now(timezone.utc),
        "completed_at": datetime.now(timezone.utc),
        "chunk_heading": _EN_CONCEPT_HEADING,
        "chunk_heading_tr": _HEADING_TRANSLATIONS,
        "book_title_en": _EN_BOOK_TITLE,
        "book_title_tr": _BOOK_TITLE_TRANSLATIONS,
    }


def _make_mock_db(preferred_language: str) -> AsyncMock:
    """
    Mock DB that:
    - db.get(Student, _STUDENT_ID) → fake student with given language
    - the sessions LATERAL query via execute(sa_text(...)) → mapping rows
    Note: admin user bypasses _validate_student_ownership so no ownership execute() call.
    """
    fake_student = _make_fake_student(preferred_language)
    db = AsyncMock(spec=AsyncSession)

    session_row = _make_session_row()
    sessions_result = MagicMock()
    sessions_result.mappings.return_value.all.return_value = [session_row]

    db.execute = AsyncMock(return_value=sessions_result)
    db.get = AsyncMock(return_value=fake_student)
    return db


def _make_admin_user() -> MagicMock:
    """Admin user bypasses ownership validation."""
    u = MagicMock()
    u.id = uuid.uuid4()
    u.role = "admin"
    return u


def _build_sessions_app(preferred_language: str) -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter

    mock_db = _make_mock_db(preferred_language)
    admin_user = _make_admin_user()

    async def _get_test_db():
        yield mock_db

    async def _get_admin_user():
        return admin_user

    app.dependency_overrides[get_db] = _get_test_db
    app.dependency_overrides[get_current_user] = _get_admin_user

    # Inject minimal stubs so _require_services() doesn't 503
    mock_ksvc = MagicMock()
    mock_svc = MagicMock()
    mock_svc.knowledge_services = {}
    teaching_router_module.chunk_ksvc = mock_ksvc
    teaching_router_module.teaching_svc = mock_svc

    app.include_router(teaching_router_module.router)
    return app


async def _get_sessions(app: FastAPI) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(f"/api/v2/students/{_STUDENT_ID}/sessions")


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSessionsEndpointTranslations:
    """GET /students/{id}/sessions — preferred_language-driven translation."""

    async def test_ml_student_returns_malayalam_titles(self):
        """
        Student with preferred_language='ml' → concept_title and book_title
        are resolved to their Malayalam translations.
        """
        app = _build_sessions_app("ml")
        resp = await _get_sessions(app)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sessions"]) == 1
        session = data["sessions"][0]
        assert session["concept_title"] == _ML_CONCEPT_HEADING
        assert session["book_title"] == _ML_BOOK_TITLE

    async def test_en_student_returns_english_titles(self):
        """
        Student with preferred_language='en' → concept_title and book_title
        revert to English column values.
        """
        app = _build_sessions_app("en")
        resp = await _get_sessions(app)
        assert resp.status_code == 200
        data = resp.json()
        session = data["sessions"][0]
        assert session["concept_title"] == _EN_CONCEPT_HEADING
        assert session["book_title"] == _EN_BOOK_TITLE

    async def test_titles_are_never_empty(self):
        """concept_title and book_title must always be non-empty strings."""
        for lang in ("ml", "en", "hi"):
            app = _build_sessions_app(lang)
            resp = await _get_sessions(app)
            assert resp.status_code == 200, f"lang={lang}"
            for session in resp.json()["sessions"]:
                assert session["concept_title"], f"empty concept_title for lang={lang}"
                assert session["book_title"], f"empty book_title for lang={lang}"
