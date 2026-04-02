"""
Tests for POST /sessions/{session_id}/chunks/{chunk_id}/complete.

Business criteria:
  BC-CC-01  Marking a chunk complete stores a timestamped record in chunk_progress
            and returns {"status": "ok", "chunk_id": "<id>"}.
  BC-CC-02  The endpoint is idempotent — calling it a second time for the same
            chunk_id returns 200 and does not corrupt the progress dict.
  BC-CC-03  Requesting completion for a session that does not exist returns HTTP 404.
  BC-CC-04  Completing a second chunk merges into chunk_progress without overwriting
            the first chunk's record.

Test strategy:
  Pure-unit tests using a mock AsyncSession and httpx.AsyncClient against a
  lightweight FastAPI test app built with dependency_overrides.
  No live database, no OpenAI calls.
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ── Break circular import teaching_router ↔ api.main ─────────────────────────

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
    # db.models, teaching_service — importable without DB; no stub needed


_stub_heavyweight_modules()

import httpx
from fastapi import FastAPI

import api.teaching_router as teaching_router_module
from api.rate_limiter import limiter
from db.connection import get_db


# ── Test constants ─────────────────────────────────────────────────────────────

_STUDENT_ID = uuid.uuid4()
_SESSION_ID = uuid.uuid4()
_CONCEPT_ID = "prealgebra_1.1"
_BOOK_SLUG = "prealgebra"
_CHUNK_ID = str(uuid.uuid4())
_CHUNK_ID_2 = str(uuid.uuid4())


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_fake_session(*, chunk_progress=None):
    """Build a minimal TeachingSession-like mock."""
    s = MagicMock()
    s.id = _SESSION_ID
    s.student_id = _STUDENT_ID
    s.concept_id = _CONCEPT_ID
    s.book_slug = _BOOK_SLUG
    s.phase = "CARDS"
    s.style = "default"
    s.chunk_index = 0
    s.started_at = datetime.now(timezone.utc)
    s.completed_at = None
    s.check_score = None
    s.concept_mastered = False
    # chunk_progress must be a real dict (or None) — not MagicMock — so that
    # `dict(session.chunk_progress or {})` evaluates correctly in the handler.
    s.chunk_progress = chunk_progress
    return s


class _MockDb:
    """
    Mock AsyncSession for the mark_chunk_complete handler.

    The handler calls:
      1. db.get(TeachingSession, session_id) — returns session or None
      2. flag_modified(session, "chunk_progress")  — no-op on mock
      3. db.commit()
    """

    def __init__(self, *, session=None):
        self._session = session
        self.commit = AsyncMock()
        self.flush = AsyncMock()
        self.add = MagicMock()
        # Track mutations so we can inspect them after the request
        self.last_saved_progress = None

    async def get(self, cls, pk):
        from db.models import TeachingSession
        if cls == TeachingSession and pk == _SESSION_ID:
            # Intercept chunk_progress assignment to capture the updated value
            if self._session is not None:
                original_setter = type(self._session).__setattr__

                def _track_setter(obj, name, value):
                    if name == "chunk_progress":
                        self.last_saved_progress = value
                    original_setter(obj, name, value)

                type(self._session).__setattr__ = _track_setter
            return self._session
        return None

    async def execute(self, stmt):
        # mark_chunk_complete does not call execute — return a no-op mock just in case
        return MagicMock()


def _build_test_app(mock_db_instance) -> FastAPI:
    """Build a lightweight FastAPI app using the real mark_chunk_complete handler."""
    app = FastAPI()
    app.state.limiter = limiter

    async def _get_test_db():
        yield mock_db_instance

    app.dependency_overrides[get_db] = _get_test_db

    mock_svc = MagicMock()
    teaching_router_module.teaching_svc = mock_svc
    teaching_router_module.chunk_ksvc = MagicMock()

    app.include_router(teaching_router_module.router)
    return app


async def _post(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path)


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CC-01  Successful chunk completion
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompleteChunkSuccess:
    """
    BC-CC-01: POST to the endpoint must return HTTP 200 with status="ok" and
    the chunk_id echoed back, confirming the progress record was saved.
    """

    async def test_complete_chunk_returns_200_with_ok_status(self):
        """
        Business criterion: Marking a chunk complete returns {status: "ok", chunk_id: <id>}.
        """
        session = _make_fake_session(chunk_progress=None)
        db = _MockDb(session=session)
        app = _build_test_app(db)

        resp = await _post(app, f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/complete")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["chunk_id"] == _CHUNK_ID

    async def test_complete_chunk_db_commit_is_called(self):
        """
        Business criterion: The session must be committed after marking a chunk complete
        so progress is persisted across restarts.
        """
        session = _make_fake_session(chunk_progress=None)
        db = _MockDb(session=session)
        app = _build_test_app(db)

        await _post(app, f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/complete")

        db.commit.assert_called_once()

    async def test_complete_chunk_writes_completed_true_to_progress(self):
        """
        Business criterion: chunk_progress must contain a record with completed=True
        for the given chunk_id after the call.
        """
        session = _make_fake_session(chunk_progress=None)
        db = _MockDb(session=session)
        app = _build_test_app(db)

        await _post(app, f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/complete")

        # After the handler runs, chunk_progress on the session object must be set
        # with completed=True for our chunk_id
        assert session.chunk_progress is not None
        assert _CHUNK_ID in session.chunk_progress
        assert session.chunk_progress[_CHUNK_ID]["completed"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CC-02  Idempotency — calling twice does not corrupt progress
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompleteChunkIdempotent:
    """
    BC-CC-02: Calling the endpoint twice for the same chunk_id must return 200
    on both calls and leave the progress dict in a valid state (not duplicated
    or overwritten with garbage).
    """

    async def test_second_call_returns_200(self):
        """
        Business criterion: The endpoint is idempotent — second call also succeeds.
        """
        session = _make_fake_session(chunk_progress=None)
        db = _MockDb(session=session)
        app = _build_test_app(db)

        resp1 = await _post(app, f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/complete")
        # After first call, chunk_progress is set on session — simulate persistence
        # by keeping the session as-is for the second call (same db mock)
        resp2 = await _post(app, f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/complete")

        assert resp1.status_code == 200
        assert resp2.status_code == 200

    async def test_second_call_does_not_add_duplicate_keys(self):
        """
        Business criterion: After two calls for the same chunk, chunk_progress
        must have exactly one entry for that chunk_id (no duplicate keys).
        """
        session = _make_fake_session(chunk_progress=None)
        db = _MockDb(session=session)
        app = _build_test_app(db)

        await _post(app, f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/complete")
        # Second call sees existing chunk_progress already set on session
        await _post(app, f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/complete")

        assert isinstance(session.chunk_progress, dict)
        # A dict can only have one entry per key — confirm key exists exactly once
        assert list(session.chunk_progress.keys()).count(_CHUNK_ID) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CC-03  Session not found → HTTP 404
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompleteChunkNotFound:
    """
    BC-CC-03: Attempting to mark a chunk complete on a non-existent session must
    return HTTP 404 so the frontend can handle orphaned state gracefully.
    """

    async def test_complete_chunk_unknown_session_returns_404(self):
        """
        Business criterion: Unknown session_id → HTTP 404.
        db.get() returns None when the session does not exist.
        """
        unknown_session_id = uuid.uuid4()
        db = _MockDb(session=None)
        app = _build_test_app(db)

        resp = await _post(
            app, f"/api/v2/sessions/{unknown_session_id}/chunks/{_CHUNK_ID}/complete"
        )

        assert resp.status_code == 404

    async def test_complete_chunk_not_found_response_has_detail(self):
        """
        Business criterion: 404 response must include a detail message so the
        frontend can surface a meaningful error.
        """
        unknown_session_id = uuid.uuid4()
        db = _MockDb(session=None)
        app = _build_test_app(db)

        resp = await _post(
            app, f"/api/v2/sessions/{unknown_session_id}/chunks/{_CHUNK_ID}/complete"
        )

        assert resp.status_code == 404
        assert "detail" in resp.json()


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CC-04  Merges new chunk into existing progress without overwriting
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompleteChunkMergesExisting:
    """
    BC-CC-04: When chunk_progress already contains a record for a previous chunk,
    completing a new chunk must add the new entry without removing the old one.
    """

    async def test_second_chunk_added_without_overwriting_first(self):
        """
        Business criterion: Completing chunk B must not erase chunk A's record.
        Session already has chunk A in chunk_progress; after completing chunk B,
        both A and B must be present in chunk_progress.
        """
        # Arrange — pre-populate progress with chunk A already completed
        existing_progress = {
            _CHUNK_ID: {
                "completed": True,
                "completed_at": datetime.utcnow().isoformat(),
            }
        }
        session = _make_fake_session(chunk_progress=existing_progress)
        db = _MockDb(session=session)
        app = _build_test_app(db)

        # Act — complete a different chunk (chunk B)
        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID_2}/complete"
        )

        # Assert
        assert resp.status_code == 200
        progress = session.chunk_progress
        assert _CHUNK_ID in progress, "Original chunk A record must still be present"
        assert _CHUNK_ID_2 in progress, "Newly completed chunk B must be present"
        assert progress[_CHUNK_ID]["completed"] is True, "Chunk A's completed flag must not be overwritten"

    async def test_both_chunks_have_completed_true_after_sequential_calls(self):
        """
        Business criterion: Both chunk records in progress must have completed=True.
        """
        # Complete first chunk
        session = _make_fake_session(chunk_progress=None)
        db = _MockDb(session=session)
        app = _build_test_app(db)

        await _post(app, f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/complete")
        await _post(app, f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID_2}/complete")

        progress = session.chunk_progress
        assert progress[_CHUNK_ID]["completed"] is True
        assert progress[_CHUNK_ID_2]["completed"] is True
