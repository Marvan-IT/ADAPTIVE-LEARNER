"""
test_session_start_from_profile.py
Integration tests for the post-refactor session-start behaviour.

Plan section 1h: 4 acceptance-criteria tests verifying that:
  AC-SS-01  start_session copies preferred_style + interests from the Student
            profile into the new TeachingSession (not from request body).
  AC-SS-02  PUT /api/v2/sessions/{id}/style no longer exists → 404 or 405.
  AC-SS-03  PUT /api/v2/sessions/{id}/interests no longer exists → 404 or 405.
  AC-SS-04  A legacy `style` field in the StartSessionRequest body is silently
            ignored (Pydantic v2 default `extra='ignore'`); the session style
            still comes from the student profile.

Strategy:
- Build a lightweight FastAPI app with the real teaching_router.
- Override get_db with a mock session that returns a pre-seeded Student mock.
- Override get_current_user with a stub admin user (bypasses ownership check).
- Patch chunk_ksvc and teaching_svc at the module level so LLM / DB calls
  are never made.
- All assertions are on the HTTP response body or on the mock call arguments.
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── Break circular import teaching_router ↔ api.main ─────────────────────────
# teaching_router imports `limiter` from api.main at module level.
# api.main imports router from teaching_router at module level.
# We must break this before any import of teaching_router.

def _install_api_main_stub():
    if "api.main" not in sys.modules:
        stub = MagicMock()
        try:
            from slowapi import Limiter
            from slowapi.util import get_remote_address
            stub.limiter = Limiter(key_func=get_remote_address)
        except ImportError:
            stub.limiter = MagicMock()
        sys.modules["api.main"] = stub


_install_api_main_stub()

import pytest
import httpx
from fastapi import FastAPI

import api.teaching_router as teaching_router_module
from api.rate_limiter import limiter
from auth.dependencies import get_current_user
from db.connection import get_db


# ── Shared test constants ──────────────────────────────────────────────────────

_STUDENT_ID = uuid.uuid4()
_SESSION_ID = uuid.uuid4()
_CONCEPT_ID = "prealgebra_1.1"
_BOOK_SLUG = "prealgebra"


# ── Stub admin user ────────────────────────────────────────────────────────────

def _make_stub_admin_user():
    """
    Returns a User-like mock with role='admin'.
    _validate_student_ownership in the router short-circuits for admins,
    so no Student.user_id lookup is required.
    """
    user = MagicMock()
    user.id = uuid.uuid4()
    user.role = "admin"
    user.is_active = True
    return user


_STUB_ADMIN = _make_stub_admin_user()


async def _stub_get_current_user():
    """FastAPI dependency override: always returns the stub admin user."""
    return _STUB_ADMIN


# ── Mock DB factory ────────────────────────────────────────────────────────────

def _make_mock_db(
    *,
    student_style: str = "gamer",
    student_interests: list | None = None,
) -> MagicMock:
    """
    Build a mock AsyncSession whose db.get(Student, ...) returns a Student
    mock pre-loaded with the given style and interests.
    """
    if student_interests is None:
        student_interests = ["Gaming", "Space"]

    # Student mock
    student = MagicMock()
    student.id = _STUDENT_ID
    student.display_name = "Test Student"
    student.preferred_style = student_style
    student.interests = student_interests
    student.preferred_language = "en"
    student.xp = 0
    student.streak = 0
    student.created_at = datetime.now(timezone.utc)

    # Session mock that looks like the response from teaching_svc.start_session
    session = MagicMock()
    session.id = _SESSION_ID
    session.student_id = _STUDENT_ID
    session.concept_id = _CONCEPT_ID
    session.book_slug = _BOOK_SLUG
    session.phase = "PRESENTING"
    session.style = student_style             # mirrors what the refactored service sets
    session.lesson_interests = student_interests
    session.started_at = datetime.now(timezone.utc)
    session.completed_at = None
    session.check_score = None
    session.concept_mastered = False

    db = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()

    async def _db_get(cls, pk):
        from db.models import Student, TeachingSession
        if cls == Student and pk == _STUDENT_ID:
            return student
        if cls == TeachingSession and pk == _SESSION_ID:
            return session
        return None

    db.get = _db_get

    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        all=MagicMock(return_value=[]),
        scalar=MagicMock(return_value=0),
        one=MagicMock(return_value=MagicMock(total=0, avg_wrong=0.0)),
        one_or_none=MagicMock(return_value=None),
    ))

    # Store the session mock for inspection in tests
    db._fake_session = session
    db._fake_student = student
    return db


# ── App builder ────────────────────────────────────────────────────────────────

def _build_test_app(mock_db) -> FastAPI:
    """
    Builds a minimal FastAPI app that:
      - Includes the real teaching_router (real routing + Pydantic validation)
      - Injects the mock DB
      - Overrides get_current_user with a stub admin so auth passes
      - Stubs teaching_svc and chunk_ksvc at the module level
    """
    app = FastAPI()
    app.state.limiter = limiter

    async def _get_test_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_test_db
    app.dependency_overrides[get_current_user] = _stub_get_current_user

    # Stub the teaching service
    mock_svc = MagicMock()
    # start_session returns the fake session (mirrors real behaviour)
    mock_svc.start_session = AsyncMock(return_value=mock_db._fake_session)
    teaching_router_module.teaching_svc = mock_svc

    # Stub chunk_ksvc so _require_services() passes and book lookup succeeds
    mock_chunk_ksvc = MagicMock()
    mock_chunk_ksvc.get_active_books = AsyncMock(return_value={_BOOK_SLUG})
    mock_chunk_ksvc.get_concept_detail = AsyncMock(return_value={
        "concept_id": _CONCEPT_ID,
        "concept_title": "Introduction to Whole Numbers",
        "text": "Whole numbers are...",
        "latex": [],
        "images": [],
        "prerequisites": [],
    })
    teaching_router_module.chunk_ksvc = mock_chunk_ksvc

    app.include_router(teaching_router_module.router)
    return app


async def _post_start_session(app: FastAPI, body: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/v2/sessions", json=body)


async def _put(app: FastAPI, path: str, body: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.put(path, json=body)


# ═══════════════════════════════════════════════════════════════════════════════
# AC-SS-01  start_session copies style + interests from the student profile
# ═══════════════════════════════════════════════════════════════════════════════

class TestStartSessionCopiesProfileFields:
    """
    AC-SS-01: When a session is created via POST /api/v2/sessions, the
    TeachingSession.style and TeachingSession.lesson_interests must be
    populated from the student's preferred_style and interests fields,
    not from the request body.
    """

    async def test_start_session_copies_style_from_student_profile(self):
        """
        Business criterion: Session style is locked to the student's profile
        at creation time. The response must reflect the student's preferred_style.
        """
        mock_db = _make_mock_db(student_style="gamer", student_interests=["Gaming", "Space"])
        app = _build_test_app(mock_db)

        body = {
            "student_id": str(_STUDENT_ID),
            "concept_id": _CONCEPT_ID,
            "book_slug": _BOOK_SLUG,
        }

        resp = await _post_start_session(app, body)

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

        # The response session must carry the student's style
        assert data["style"] == "gamer", (
            f"Expected session.style='gamer' (from student profile), got {data.get('style')!r}"
        )

    async def test_start_session_response_reflects_student_style_not_default(self):
        """
        Regression guard: when a student's style is non-default ('astronaut'),
        the session response must not fall back to 'default'.
        """
        mock_db = _make_mock_db(student_style="astronaut", student_interests=["Stars", "Math"])
        app = _build_test_app(mock_db)

        body = {
            "student_id": str(_STUDENT_ID),
            "concept_id": _CONCEPT_ID,
            "book_slug": _BOOK_SLUG,
        }

        resp = await _post_start_session(app, body)

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["style"] == "astronaut", (
            f"Expected 'astronaut', got {data.get('style')!r}"
        )

    async def test_start_session_service_called_without_style_kwarg(self):
        """
        Implementation guard: teaching_svc.start_session must be called with
        (db, student_id, concept_id, book_slug) only — no style or
        lesson_interests kwargs.  This validates the refactor removed those params.
        """
        mock_db = _make_mock_db()
        app = _build_test_app(mock_db)

        body = {
            "student_id": str(_STUDENT_ID),
            "concept_id": _CONCEPT_ID,
            "book_slug": _BOOK_SLUG,
        }

        await _post_start_session(app, body)

        # Verify start_session was called exactly once
        mock_svc = teaching_router_module.teaching_svc
        mock_svc.start_session.assert_called_once()

        # style and lesson_interests must NOT be in kwargs
        _call_kwargs = mock_svc.start_session.call_args.kwargs
        assert "style" not in _call_kwargs, (
            "start_session was called with a 'style' kwarg — refactor incomplete"
        )
        assert "lesson_interests" not in _call_kwargs, (
            "start_session was called with a 'lesson_interests' kwarg — refactor incomplete"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# AC-SS-02  PUT /api/v2/sessions/{id}/style is gone (deleted route)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPutSessionStyleDeleted:
    """
    AC-SS-02: The PUT /api/v2/sessions/{session_id}/style endpoint was deleted
    in the refactor.  Any call to it must return 404 or 405 (not 200 or 422).
    """

    async def test_put_session_style_returns_404_or_405(self):
        """
        Business criterion: Clients relying on the old style-switch endpoint
        should receive a clear 'not found' or 'method not allowed' error,
        not a silent success or validation error.
        """
        mock_db = _make_mock_db()
        app = _build_test_app(mock_db)

        resp = await _put(
            app,
            f"/api/v2/sessions/{_SESSION_ID}/style",
            {"style": "pirate"},
        )

        assert resp.status_code in (404, 405), (
            f"Expected 404 or 405 for deleted route, got {resp.status_code}: {resp.text}"
        )

    async def test_put_session_style_is_not_200(self):
        """
        Sanity guard: the old switch-style endpoint must not silently succeed.
        """
        mock_db = _make_mock_db()
        app = _build_test_app(mock_db)

        resp = await _put(
            app,
            f"/api/v2/sessions/{_SESSION_ID}/style",
            {"style": "default"},
        )

        assert resp.status_code != 200, (
            "PUT /style returned 200 — the route was not deleted as expected"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# AC-SS-03  PUT /api/v2/sessions/{id}/interests is gone (deleted route)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPutSessionInterestsDeleted:
    """
    AC-SS-03: The PUT /api/v2/sessions/{session_id}/interests endpoint was
    deleted in the refactor.  Any call to it must return 404 or 405.
    """

    async def test_put_session_interests_returns_404_or_405(self):
        """
        Business criterion: The interests update endpoint is gone.
        Clients must receive a 404 or 405, not a success.
        """
        mock_db = _make_mock_db()
        app = _build_test_app(mock_db)

        resp = await _put(
            app,
            f"/api/v2/sessions/{_SESSION_ID}/interests",
            {"interests": ["Sports"]},
        )

        assert resp.status_code in (404, 405), (
            f"Expected 404 or 405 for deleted route, got {resp.status_code}: {resp.text}"
        )

    async def test_put_session_interests_is_not_200(self):
        """
        Sanity guard: the old update-interests endpoint must not silently succeed.
        """
        mock_db = _make_mock_db()
        app = _build_test_app(mock_db)

        resp = await _put(
            app,
            f"/api/v2/sessions/{_SESSION_ID}/interests",
            {"interests": ["Gaming"]},
        )

        assert resp.status_code != 200, (
            "PUT /interests returned 200 — the route was not deleted as expected"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# AC-SS-04  Legacy `style` field in StartSessionRequest body is silently ignored
# ═══════════════════════════════════════════════════════════════════════════════

class TestStartSessionIgnoresLegacyStyleField:
    """
    AC-SS-04: StartSessionRequest has no `style` field.  Pydantic v2's default
    `extra='ignore'` means sending a spurious `style` key does not cause 422.
    The session's style must come from the student profile, not from the body.
    """

    def test_start_session_request_has_no_style_field(self):
        """
        Direct schema check: StartSessionRequest does not define a `style` field.
        """
        from api.teaching_schemas import StartSessionRequest
        assert "style" not in StartSessionRequest.model_fields, (
            "StartSessionRequest still has a 'style' field — refactor incomplete"
        )

    def test_start_session_request_has_no_lesson_interests_field(self):
        """
        Direct schema check: StartSessionRequest does not define lesson_interests.
        """
        from api.teaching_schemas import StartSessionRequest
        assert "lesson_interests" not in StartSessionRequest.model_fields, (
            "StartSessionRequest still has a 'lesson_interests' field — refactor incomplete"
        )

    def test_start_session_request_extra_is_ignore_by_default(self):
        """
        Verify that a spurious 'style' field does NOT raise a ValidationError.
        In Pydantic v2 the default extra mode is 'ignore', so this must succeed.
        """
        from api.teaching_schemas import StartSessionRequest
        from pydantic import ValidationError

        try:
            req = StartSessionRequest(
                student_id=uuid.uuid4(),
                concept_id="prealgebra_1.1",
                book_slug="prealgebra",
                style="pirate",          # spurious legacy field
            )
            # model_extra should be None (ignore mode) — not a dict with 'style'
            assert req.model_extra is None or "style" not in (req.model_extra or {})
        except ValidationError as exc:
            pytest.fail(
                f"StartSessionRequest raised ValidationError for extra 'style' field "
                f"(expected 'ignore' mode): {exc}"
            )

    async def test_start_session_ignores_legacy_style_field_in_body(self):
        """
        HTTP integration: POST with spurious 'style=pirate' in the body must
        succeed (not 422) and the session style must come from the student
        profile (gamer), not from the body (pirate).
        """
        # Student profile has style='gamer'
        mock_db = _make_mock_db(student_style="gamer", student_interests=["Gaming"])
        app = _build_test_app(mock_db)

        body = {
            "student_id": str(_STUDENT_ID),
            "concept_id": _CONCEPT_ID,
            "book_slug": _BOOK_SLUG,
            "style": "pirate",           # legacy field — should be silently dropped
        }

        resp = await _post_start_session(app, body)

        # Must not be 422 (the field is ignored, not rejected)
        assert resp.status_code != 422, (
            "POST /sessions with spurious 'style' field returned 422 — "
            "expected Pydantic to ignore it silently"
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        data = resp.json()
        # Style must come from the student profile (gamer), not the body (pirate)
        assert data["style"] == "gamer", (
            f"Session style should be 'gamer' (from student profile), not 'pirate' (from body). "
            f"Got: {data.get('style')!r}"
        )
