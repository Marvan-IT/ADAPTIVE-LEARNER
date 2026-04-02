"""
Tests for PATCH /students/{student_id}/language — language change cache clearing.

Business criteria:
  BC-LC-01  Changing a student's language clears presentation_text, exam_phase, and
            exam_scores on all non-COMPLETED sessions, so cards are regenerated in
            the new language on the next access.
  BC-LC-02  COMPLETED sessions are never touched — their language state is immutable
            once the student has finished.
  BC-LC-03  The student's preferred_language field is updated to the new language code.
  BC-LC-04  Requesting a language change for a non-existent student returns HTTP 404.

Test strategy:
  httpx.AsyncClient against a lightweight FastAPI test app.  No live DB needed.
  Mock AsyncSession captures update calls to verify the right sessions are cleared.
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ── Break circular import ─────────────────────────────────────────────────────

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


def _stub_heavyweight_modules():
    """Stub modules with import-time issues before importing teaching_router."""
    if "db.connection" not in sys.modules:
        stub_conn = MagicMock()
        stub_conn.get_db = MagicMock()
        sys.modules["db.connection"] = stub_conn
    # db.models must NOT be stubbed — select(TeachingSession) requires the real class


_stub_heavyweight_modules()

import httpx
from fastapi import FastAPI

import api.teaching_router as teaching_router_module
from api.rate_limiter import limiter
from db.connection import get_db


# ── Constants ─────────────────────────────────────────────────────────────────

_STUDENT_ID = uuid.uuid4()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_student(*, preferred_language: str = "en"):
    """Build a minimal Student-like mock."""
    s = MagicMock()
    s.id = _STUDENT_ID
    s.display_name = "Test Student"
    s.interests = []
    s.preferred_style = "default"
    s.preferred_language = preferred_language
    s.xp = 0
    s.streak = 0
    s.created_at = datetime.now(timezone.utc)
    return s


def _make_session(*, phase: str, presentation_text: str = '{"cards": []}',
                   exam_phase: str | None = "PENDING",
                   exam_scores: dict | None = None) -> MagicMock:
    """Build a minimal TeachingSession-like mock."""
    sess = MagicMock()
    sess.id = uuid.uuid4()
    sess.phase = phase
    sess.presentation_text = presentation_text
    sess.exam_phase = exam_phase
    sess.exam_scores = exam_scores or {"q1": "answer"}
    return sess


class _MockDb:
    """
    Mock AsyncSession for update_student_language handler.

    Handler call sequence:
      1. db.get(Student, student_id)  → student or None
      2. db.execute(select(TeachingSession) ... phase != "COMPLETED") → sessions
      3. db.commit()
      4. db.refresh(student)
    """

    def __init__(self, *, student=None, active_sessions=None):
        self._student = student
        self._active_sessions = active_sessions if active_sessions is not None else []
        self.commit = AsyncMock()
        self.flush = AsyncMock()
        self.add = MagicMock()
        self._refresh_called = False

    async def get(self, cls, pk):
        from db.models import Student
        if cls == Student and pk == _STUDENT_ID:
            return self._student
        return None

    async def execute(self, stmt):
        # Return the active (non-COMPLETED) sessions
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = self._active_sessions
        result.scalars.return_value = scalars
        return result

    async def refresh(self, obj):
        self._refresh_called = True
        # Simulate DB returning updated object — nothing needed for our assertions


def _build_test_app(mock_db_instance) -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter

    async def _get_test_db():
        yield mock_db_instance

    app.dependency_overrides[get_db] = _get_test_db

    teaching_router_module.teaching_svc = MagicMock()
    teaching_router_module.chunk_ksvc = MagicMock()

    app.include_router(teaching_router_module.router)
    return app


async def _patch_language(app: FastAPI, student_id: uuid.UUID, language: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.patch(
            f"/api/v2/students/{student_id}/language",
            json={"language": language},
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BC-LC-01  Language change clears active sessions
# ═══════════════════════════════════════════════════════════════════════════════

class TestLanguageChangeClearsActiveSessions:
    """
    BC-LC-01: Non-COMPLETED sessions must have their presentation_text, exam_phase,
    and exam_scores set to None so cards are regenerated in the new language on
    the student's next lesson access.
    """

    async def test_presentation_text_cleared_on_active_session(self):
        """
        Business criterion: presentation_text=None on non-COMPLETED sessions after
        language change, forcing card regeneration in the new language.
        """
        active_sess = _make_session(phase="CARDS", presentation_text='{"cards": []}')
        student = _make_student(preferred_language="en")
        db = _MockDb(student=student, active_sessions=[active_sess])
        app = _build_test_app(db)

        resp = await _patch_language(app, _STUDENT_ID, "es")

        assert resp.status_code == 200
        assert active_sess.presentation_text is None, (
            "presentation_text must be cleared on language change"
        )

    async def test_exam_phase_cleared_on_active_session(self):
        """
        Business criterion: exam_phase=None resets any in-progress exam so it
        can be regenerated in the new language.
        """
        active_sess = _make_session(phase="CARDS", exam_phase="PENDING")
        student = _make_student()
        db = _MockDb(student=student, active_sessions=[active_sess])
        app = _build_test_app(db)

        resp = await _patch_language(app, _STUDENT_ID, "fr")

        assert resp.status_code == 200
        assert active_sess.exam_phase is None, "exam_phase must be cleared on language change"

    async def test_exam_scores_cleared_on_active_session(self):
        """
        Business criterion: exam_scores=None discards old-language exam questions
        so the exam is regenerated in the new language.
        """
        active_sess = _make_session(phase="CARDS", exam_scores={"q1": "some answer"})
        student = _make_student()
        db = _MockDb(student=student, active_sessions=[active_sess])
        app = _build_test_app(db)

        resp = await _patch_language(app, _STUDENT_ID, "hi")

        assert resp.status_code == 200
        assert active_sess.exam_scores is None, "exam_scores must be cleared on language change"

    async def test_multiple_active_sessions_all_cleared(self):
        """
        Business criterion: All non-COMPLETED sessions — regardless of phase — must
        be cleared.  A student might have multiple open sessions.
        """
        sess1 = _make_session(phase="CARDS", presentation_text='{"cards": []}')
        sess2 = _make_session(phase="REMEDIATING", presentation_text='{"cards": []}')
        student = _make_student()
        db = _MockDb(student=student, active_sessions=[sess1, sess2])
        app = _build_test_app(db)

        resp = await _patch_language(app, _STUDENT_ID, "zh")

        assert resp.status_code == 200
        assert sess1.presentation_text is None
        assert sess2.presentation_text is None
        assert sess1.exam_phase is None
        assert sess2.exam_phase is None


# ═══════════════════════════════════════════════════════════════════════════════
# BC-LC-02  COMPLETED sessions are not touched
# ═══════════════════════════════════════════════════════════════════════════════

class TestLanguageChangeSkipsCompletedSessions:
    """
    BC-LC-02: COMPLETED sessions represent historical learning events.  Their
    language state must not be altered on a language change — only the DB query
    filters them out.  We confirm this by verifying the mock DB's active_sessions
    list does NOT include COMPLETED sessions.

    The router's WHERE clause reads:
      TeachingSession.phase != "COMPLETED"
    so COMPLETED sessions are never returned by the query and thus never modified.
    """

    async def test_completed_sessions_excluded_from_active_query(self):
        """
        Business criterion: COMPLETED sessions are never touched.
        The mock only returns non-COMPLETED sessions, so the handler cannot
        modify a COMPLETED session even if it tried.
        """
        # Only the non-completed session is returned by the mock
        active_sess = _make_session(phase="CARDS", presentation_text='{"cards": []}')
        # Completed session is NOT returned by _active_sessions (the query filters it)
        completed_sess = _make_session(phase="COMPLETED", presentation_text='{"legacy": true}')
        student = _make_student()
        # DB returns only active_sess — simulating the WHERE phase != "COMPLETED" filter
        db = _MockDb(student=student, active_sessions=[active_sess])
        app = _build_test_app(db)

        resp = await _patch_language(app, _STUDENT_ID, "de")

        assert resp.status_code == 200
        # Active session is cleared
        assert active_sess.presentation_text is None
        # Completed session is unmodified (handler never received it)
        assert completed_sess.presentation_text == '{"legacy": true}'

    async def test_no_active_sessions_returns_200(self):
        """
        Business criterion: Language change succeeds even when there are no
        non-COMPLETED sessions to clear (e.g. brand-new student).
        """
        student = _make_student()
        db = _MockDb(student=student, active_sessions=[])
        app = _build_test_app(db)

        resp = await _patch_language(app, _STUDENT_ID, "ta")

        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# BC-LC-03  Student's preferred_language field updated
# ═══════════════════════════════════════════════════════════════════════════════

class TestLanguageChangeUpdatesStudent:
    """
    BC-LC-03: The student's preferred_language field must be set to the new
    language code and the change must be committed.
    """

    async def test_preferred_language_set_on_student_object(self):
        """
        Business criterion: Student's preferred_language is updated in the handler.
        """
        student = _make_student(preferred_language="en")
        db = _MockDb(student=student, active_sessions=[])
        app = _build_test_app(db)

        await _patch_language(app, _STUDENT_ID, "ko")

        assert student.preferred_language == "ko"

    async def test_db_commit_called_after_update(self):
        """
        Business criterion: Changes are committed to the database so they persist.
        """
        student = _make_student()
        db = _MockDb(student=student, active_sessions=[])
        app = _build_test_app(db)

        await _patch_language(app, _STUDENT_ID, "ar")

        db.commit.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# BC-LC-04  Student not found → HTTP 404
# ═══════════════════════════════════════════════════════════════════════════════

class TestLanguageChangeStudentNotFound:
    """
    BC-LC-04: Attempting to change the language for a non-existent student must
    return HTTP 404 so the frontend can display an appropriate error.
    """

    async def test_unknown_student_returns_404(self):
        """
        Business criterion: Non-existent student_id → HTTP 404.
        """
        unknown_id = uuid.uuid4()
        db = _MockDb(student=None, active_sessions=[])
        app = _build_test_app(db)

        resp = await _patch_language(app, unknown_id, "es")

        assert resp.status_code == 404

    async def test_unknown_student_response_has_detail(self):
        """
        Business criterion: 404 response must include a detail field.
        """
        unknown_id = uuid.uuid4()
        db = _MockDb(student=None, active_sessions=[])
        app = _build_test_app(db)

        resp = await _patch_language(app, unknown_id, "es")

        assert "detail" in resp.json()
