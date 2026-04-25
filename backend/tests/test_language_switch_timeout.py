"""
test_language_switch_timeout.py
Coverage for F5 (DLD §15 closeout delta): PATCH /api/v2/students/{id}/language
must return HTTP 503 — not 200 — when the inner DB query for translated chunk
headings exceeds the 3-second timeout.

Behaviour under test (teaching_router.py:587-624):
  1. student.preferred_language is updated in-memory (line 582).
  2. The active-session block starts an asyncio.timeout(3.0) guard.
  3. _get_translated_headings_from_db() is called inside the guarded block.
  4. On asyncio.TimeoutError the handler calls db.rollback() and raises
     HTTPException(503, "Language update temporarily unavailable").
  5. db.commit() is NEVER called (exception exits the handler before line 627).
     The in-memory language mutation is therefore NOT persisted to the DB.

Design choice documented here:
  The language update is NOT saved on timeout.  db.rollback() is called
  explicitly (line 622) before the 503 is raised, and the commit that would
  flush student.preferred_language (line 627) is never reached.  This matches
  the DLD §14.5 table note: "DB timeout → 503, language not changed".
  Partial updates (language changed but cache not busted) would leave the
  session in an inconsistent state; rolling back is the correct choice.
"""

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_fake_student(preferred_language: str = "en") -> MagicMock:
    """Return an ORM-like student mock whose preferred_language is settable."""
    s = MagicMock()
    s.id = _STUDENT_ID
    s.preferred_language = preferred_language
    s.display_name = "Test Student"
    s.age = 16
    s.interests = []
    s.custom_interests = []
    s.preferred_style = "default"
    s.created_at = datetime.now(timezone.utc)
    s.role = "student"
    s.user_id = uuid.uuid4()
    return s


def _make_fake_session() -> MagicMock:
    """Return an ORM-like TeachingSession mock with an active (uncompleted) session."""
    sess = MagicMock()
    sess.id = uuid.uuid4()
    sess.student_id = _STUDENT_ID
    sess.book_slug = "prealgebra"
    sess.concept_id = "prealgebra_1.1"
    sess.completed_at = None
    sess.presentation_text = None
    sess.started_at = datetime.now(timezone.utc)
    return sess


def _make_mock_db(fake_student: MagicMock, fake_session: MagicMock) -> AsyncMock:
    """
    Build an AsyncSession mock that returns the given student and active session.

    Call order expected by update_student_language():
      1. _validate_student_ownership: db.execute(select Student.id) → student id scalar
         (admin user skips this entirely)
      2. db.get(Student, student_id) → fake_student
      3. db.execute(select TeachingSession ...) → active_session scalar
      4. [inside timeout block] db.execute(select ConceptChunk ...) — hangs (patched out)
      5. db.rollback() — called by the timeout handler
      [db.commit() is NOT called on 503]
    """
    db = AsyncMock(spec=AsyncSession)

    # db.get returns the student
    db.get = AsyncMock(return_value=fake_student)

    # First execute() → active session query
    session_scalar = MagicMock()
    session_scalar.scalar_one_or_none.return_value = fake_session
    db.execute = AsyncMock(return_value=session_scalar)

    # rollback / commit are void coroutines
    db.rollback = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    return db


def _make_admin_user() -> MagicMock:
    """Admin bypasses _validate_student_ownership."""
    u = MagicMock()
    u.id = uuid.uuid4()
    u.role = "admin"
    return u


def _build_language_app(fake_student: MagicMock, fake_session: MagicMock) -> FastAPI:
    """
    Lightweight FastAPI app that includes the real teaching_router.
    The DB is mocked; teaching_svc / chunk_ksvc stubs are injected so that
    _require_services() does not 503 on startup.
    """
    app = FastAPI()
    app.state.limiter = limiter

    mock_db = _make_mock_db(fake_student, fake_session)
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


async def _patch_language(app: FastAPI, language: str = "ml") -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.patch(
            f"/api/v2/students/{_STUDENT_ID}/language",
            json={"language": language},
        )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestLanguageSwitchTimeout:
    """PATCH /students/{id}/language — DB timeout → HTTP 503."""

    async def test_db_timeout_returns_503(self):
        """
        When _get_translated_headings_from_db hangs beyond the 3-second guard,
        the endpoint must return HTTP 503, not 200.

        The hang is simulated by monkey-patching the module-level function with
        a coroutine that awaits asyncio.sleep(5) — longer than the 3-second
        timeout wired in the handler.
        """
        fake_student = _make_fake_student(preferred_language="en")
        fake_session = _make_fake_session()
        app = _build_language_app(fake_student, fake_session)

        async def _hang(*args, **kwargs):
            await asyncio.sleep(5)  # exceeds the 3-second timeout
            return []

        with patch.object(teaching_router_module, "_get_translated_headings_from_db", _hang):
            resp = await _patch_language(app, language="ml")

        assert resp.status_code == 503, (
            f"Expected 503 on DB timeout, got {resp.status_code}: {resp.text}"
        )

    async def test_db_timeout_response_body_contains_expected_detail(self):
        """
        The 503 response body must contain a detail string that matches
        'Language update temporarily unavailable' so the frontend can surface a
        meaningful error message.
        """
        fake_student = _make_fake_student(preferred_language="en")
        fake_session = _make_fake_session()
        app = _build_language_app(fake_student, fake_session)

        async def _hang(*args, **kwargs):
            await asyncio.sleep(5)
            return []

        with patch.object(teaching_router_module, "_get_translated_headings_from_db", _hang):
            resp = await _patch_language(app, language="ml")

        body = resp.json()
        assert "detail" in body, "503 response must have a 'detail' key"
        assert "Language update temporarily unavailable" in body["detail"], (
            f"Unexpected detail string: {body['detail']!r}"
        )

    async def test_db_timeout_does_not_persist_language_change(self):
        """
        On timeout, db.rollback() is called before db.commit().
        The in-memory preferred_language mutation (line 582 of teaching_router.py)
        is therefore never flushed to the DB.

        We assert:
          - db.rollback() was called exactly once
          - db.commit() was NOT called (the 503 exception exits the handler before
            the commit at line 627)

        This verifies that a partial update (language stored, headings/cache not
        refreshed) cannot persist — the entire transaction is aborted.
        """
        fake_student = _make_fake_student(preferred_language="en")
        fake_session = _make_fake_session()
        app = _build_language_app(fake_student, fake_session)

        # Grab a reference to the mock_db that the app's dependency creates.
        # We patch get_db after the fact via the override closure.
        captured_db: list[AsyncMock] = []

        original_override = app.dependency_overrides[get_db]

        async def _capturing_db():
            async for db in original_override():
                captured_db.append(db)
                yield db

        app.dependency_overrides[get_db] = _capturing_db

        async def _hang(*args, **kwargs):
            await asyncio.sleep(5)
            return []

        with patch.object(teaching_router_module, "_get_translated_headings_from_db", _hang):
            resp = await _patch_language(app, language="ml")

        assert resp.status_code == 503
        assert len(captured_db) == 1
        db_mock = captured_db[0]
        db_mock.rollback.assert_awaited_once()
        db_mock.commit.assert_not_awaited()

    async def test_no_active_session_returns_200_with_empty_headings(self):
        """
        Baseline / regression: when the student has no active session the
        timeout-protected block is never entered, and the endpoint must succeed
        with HTTP 200 and translated_headings=[].

        This confirms the 503 path is conditional on active_session being present.
        """
        fake_student = _make_fake_student(preferred_language="en")
        app = _build_language_app(fake_student, fake_session=None)

        # Rebuild the mock_db so scalar_one_or_none() → None (no active session)
        db = AsyncMock(spec=AsyncSession)
        db.get = AsyncMock(return_value=fake_student)
        session_scalar = MagicMock()
        session_scalar.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=session_scalar)
        db.rollback = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        admin_user = _make_admin_user()

        async def _get_test_db():
            yield db

        async def _get_admin_user():
            return admin_user

        app.dependency_overrides[get_db] = _get_test_db
        app.dependency_overrides[get_current_user] = _get_admin_user

        resp = await _patch_language(app, language="ml")

        assert resp.status_code == 200, (
            f"No-active-session language switch must succeed with 200, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body.get("translated_headings") == [], (
            f"Expected empty translated_headings list, got: {body.get('translated_headings')}"
        )
        assert body.get("session_cache_cleared") is False
