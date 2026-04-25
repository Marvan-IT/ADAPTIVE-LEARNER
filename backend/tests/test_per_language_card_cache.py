"""
test_per_language_card_cache.py
Integration tests for per-language card cache behaviour as used by the teaching router.

Strategy:
- No live DB, no LLM, no network.
- Tests exercise CacheAccessor directly via the same call-sites that the router uses:
    1. Reading legacy presentation_text (adapter path).
    2. PATCH /students/{id}/language call pattern (mark_stale + write-back).
    3. Translated headings from DB are included in the response without LLM.
- One test wires the real PATCH /students/{id}/language endpoint via httpx + a mock DB
  to verify end-to-end: legacy cache reads without exception, mark_stale fires, and
  translated headings are returned from seeded rows.

Business criteria:
- Legacy sessions (flat-shape presentation_text) continue to work transparently.
- Language change busts only the NEW language's slice; prior language slices are preserved.
- translated_headings come from DB rows (heading_translations), not from an LLM call.
- session_cache_cleared is True when an active session existed.
"""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── Pre-inject api.main stub to break circular import ─────────────────────────
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
from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.cache_accessor import CacheAccessor
from api.teaching_schemas import UpdateLanguageRequest, StudentLanguageResponse
import api.teaching_router as teaching_router_module
from api.rate_limiter import limiter
from db.connection import get_db
from auth.dependencies import get_current_user
from auth.models import User


# ─── Helpers ───────────────────────────────────────────────────────────────────

_STUDENT_ID = uuid.uuid4()
_SESSION_ID = uuid.uuid4()
_CONCEPT_ID = "prealgebra_1.1"
_BOOK_SLUG = "prealgebra"


def _make_legacy_presentation(cache_version: int = 3, cards: list | None = None) -> str:
    """Return a flat (legacy) presentation_text JSON string."""
    return json.dumps({
        "cache_version": cache_version,
        "cards": cards if cards is not None else [{"id": 1, "title": "Whole Numbers"}],
        "concepts_queue": ["prealgebra_1.2"],
        "concepts_covered": [],
    })


def _make_fake_user(role: str = "admin") -> User:
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = role
    u.is_active = True
    return u


def _make_fake_student(lang: str = "en") -> MagicMock:
    s = MagicMock()
    s.id = _STUDENT_ID
    s.display_name = "Test Student"
    s.interests = []
    s.custom_interests = []
    s.preferred_style = "default"
    s.preferred_language = lang
    s.age = None
    s.created_at = datetime.now(timezone.utc)
    s.updated_at = datetime.now(timezone.utc)
    s.xp = 0
    s.streak = 0
    return s


def _make_fake_session(presentation_text: str | None = None) -> MagicMock:
    sess = MagicMock()
    sess.id = _SESSION_ID
    sess.student_id = _STUDENT_ID
    sess.concept_id = _CONCEPT_ID
    sess.book_slug = _BOOK_SLUG
    sess.phase = "CARDS"
    sess.style = "default"
    sess.started_at = datetime.now(timezone.utc)
    sess.completed_at = None
    sess.presentation_text = presentation_text
    return sess


class _FakeRow:
    """Minimal row stub for heading query results."""
    def __init__(self, heading: str, translations: dict | None = None):
        self.heading = heading
        self.heading_translations = translations or {}


def _make_mock_db(
    student_lang: str = "en",
    presentation_text: str | None = None,
    heading_rows: list | None = None,
) -> AsyncMock:
    """
    Build an AsyncMock DB session that:
    - Returns a fake Student on db.get(Student, _STUDENT_ID)
    - Returns a fake TeachingSession (with active session = no completed_at) on the
      scalar_one_or_none() of the session query.
    - Returns heading rows for the chunk heading query.
    """
    from db.models import Student, TeachingSession

    db = AsyncMock(spec=AsyncSession)
    fake_student = _make_fake_student(lang=student_lang)
    fake_session = _make_fake_session(presentation_text=presentation_text)

    async def _db_get(cls, pk):
        if cls == Student and pk == _STUDENT_ID:
            return fake_student
        if cls == TeachingSession and pk == _SESSION_ID:
            return fake_session
        return None

    db.get = _db_get

    # The router calls db.execute() in two places:
    #   1. _validate_student_ownership: select(Student.id).where(Student.user_id == user.id)
    #      → returns scalar_one_or_none() = _STUDENT_ID (admin bypass; this is never reached)
    #   2. Session lookup (scalar_one_or_none → fake_session)
    #   3. _get_translated_headings_from_db (heading/translations rows → .all())
    _rows = heading_rows if heading_rows is not None else []

    call_count = {"n": 0}

    async def _execute(stmt, *args, **kwargs):
        call_count["n"] += 1
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=fake_session)
        result.scalar = MagicMock(return_value=_STUDENT_ID)
        result.all = MagicMock(return_value=_rows)
        return result

    db.execute = _execute
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db, fake_student, fake_session


def _build_lang_test_app(
    student_lang: str = "en",
    presentation_text: str | None = None,
    heading_rows: list | None = None,
) -> tuple[FastAPI, MagicMock, MagicMock]:
    """Return (app, fake_student, fake_session) wired with the real PATCH route."""
    app = FastAPI()
    app.state.limiter = limiter

    mock_db, fake_student, fake_session = _make_mock_db(
        student_lang=student_lang,
        presentation_text=presentation_text,
        heading_rows=heading_rows,
    )

    async def _get_test_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_test_db

    # Override auth: return an admin user so ownership check is bypassed
    fake_user = _make_fake_user(role="admin")

    async def _fake_auth():
        return fake_user

    app.dependency_overrides[get_current_user] = _fake_auth

    app.include_router(teaching_router_module.router)
    return app, fake_student, fake_session


# ─── Unit-level integration: CacheAccessor in the router's call pattern ────────

class TestLegacyPresentationTextAdapter:
    """CacheAccessor transparently handles legacy flat-shape presentation_text."""

    def test_legacy_input_does_not_raise(self):
        """Creating CacheAccessor from legacy text never raises."""
        raw = _make_legacy_presentation(cache_version=3)
        ca = CacheAccessor(raw, language="en")
        sl = ca.get_slice("en")
        assert isinstance(sl, dict)
        assert sl["cards"][0]["id"] == 1

    def test_legacy_slice_available_for_student_language(self):
        """The student's preferred language's slice is immediately available after init."""
        raw = _make_legacy_presentation(cache_version=5, cards=[{"id": 7}])
        ca = CacheAccessor(raw, language="ml")
        sl = ca.get_slice("ml")
        assert sl["cards"] == [{"id": 7}]

    def test_cache_version_preserved_from_legacy(self):
        """cache_version from the legacy flat shape is preserved, not reset."""
        ca = CacheAccessor(_make_legacy_presentation(cache_version=21), language="en")
        assert ca.cache_version == 21


class TestMarkStaleRouterPattern:
    """
    The PATCH /language route calls:
        ca = CacheAccessor(session.presentation_text, language=new_lang)
        ca.mark_stale(new_lang)
        session.presentation_text = ca.to_json()

    Verify that the old language's slice survives while the new language's is cleared.
    """

    def test_old_language_slice_preserved_after_mark_stale(self):
        """Prior language slice is intact after mark_stale(new_lang)."""
        # Simulate a session that already has an "en" slice (written by an earlier request)
        modern = json.dumps({
            "cache_version": 3,
            "by_language": {
                "en": {"cards": [{"id": 10}], "concepts_queue": [], "concepts_covered": []},
            },
        })
        # Student switches to "ml"
        ca = CacheAccessor(modern, language="ml")
        ca.mark_stale("ml")
        updated_json = ca.to_json()

        # Re-read as if the DB row was persisted
        ca2 = CacheAccessor(updated_json, language="en")
        assert ca2.get_slice("en")["cards"] == [{"id": 10}]

    def test_new_language_slice_is_absent_after_mark_stale(self):
        """The new language's slice is removed so cards regenerate in that language."""
        modern = json.dumps({
            "cache_version": 3,
            "by_language": {
                "en": {"cards": [{"id": 10}], "concepts_queue": [], "concepts_covered": []},
                "ml": {"cards": [{"id": 20}], "concepts_queue": [], "concepts_covered": []},
            },
        })
        ca = CacheAccessor(modern, language="ml")
        ca.mark_stale("ml")
        updated_json = ca.to_json()

        ca2 = CacheAccessor(updated_json, language="ml")
        # After mark_stale + round-trip "ml" key is gone; get_slice returns empty dict
        parsed = json.loads(updated_json)
        assert "ml" not in parsed["by_language"]

    def test_mark_stale_on_legacy_session_clears_target_language(self):
        """Legacy presentation_text is wrapped first, then mark_stale behaves correctly."""
        raw = _make_legacy_presentation(cache_version=3, cards=[{"id": 5}])
        # Session was created under "en"; student switches to "ml"
        ca = CacheAccessor(raw, language="en")  # wraps legacy into en
        ca.mark_stale("ml")   # ml was never present — should be a no-op
        ca2 = CacheAccessor(ca.to_json(), language="en")
        assert ca2.get_slice("en")["cards"] == [{"id": 5}]

    def test_session_cache_cleared_flag_meaning(self):
        """Verify the flag logic: mark_stale is called when an active session exists."""
        raw = _make_legacy_presentation()
        ca = CacheAccessor(raw, language="ml")
        # Simulate the router: mark_stale the new language
        ca.mark_stale("ml")
        out = ca.to_json()
        # session_cache_cleared should logically be True (mark_stale ran)
        # We verify by checking the written json has no "ml" key
        parsed = json.loads(out)
        assert "ml" not in parsed["by_language"]


class TestTranslatedHeadingsFromDB:
    """Translated headings come from DB heading_translations, not from LLM."""

    def test_heading_translations_returned_without_llm(self):
        """resolve_translation returns the correct ML translation from seeded row data."""
        from api.dependencies import resolve_translation

        rows = [
            _FakeRow("Introduction", {"ml": "ആമുഖം", "ta": "அறிமுகம்"}),
            _FakeRow("Place Value", {"ml": "സ്ഥാനമൂല്യം"}),
            _FakeRow("Rounding", {}),  # no translation for ml → falls back to English
        ]

        results = [
            resolve_translation(r.heading, r.heading_translations or {}, "ml")
            for r in rows
        ]
        assert results == ["ആമുഖം", "സ്ഥാനമൂല്യം", "Rounding"]

    def test_missing_translation_falls_back_to_english(self):
        """When heading_translations has no entry for the language, English is returned."""
        from api.dependencies import resolve_translation
        result = resolve_translation("Place Value", {"ta": "இடமதிப்பு"}, "ml")
        assert result == "Place Value"

    def test_empty_translations_dict_falls_back(self):
        from api.dependencies import resolve_translation
        result = resolve_translation("Rounding", {}, "hi")
        assert result == "Rounding"


# ─── HTTP-level integration: PATCH /students/{id}/language ────────────────────

class TestPatchLanguageEndpoint:
    """Wire the real PATCH endpoint with mock DB to verify end-to-end behaviour."""

    async def test_legacy_session_no_exception_slice_available(self):
        """PATCH language on a session with legacy presentation_text returns 200."""
        import httpx
        raw = _make_legacy_presentation(cache_version=3)
        app, _, fake_session = _build_lang_test_app(
            student_lang="en",
            presentation_text=raw,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/v2/students/{_STUDENT_ID}/language",
                json={"language": "ml"},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["preferred_language"] == "ml"

    async def test_language_change_sets_session_cache_cleared(self):
        """session_cache_cleared is True when an active session is found."""
        import httpx
        raw = _make_legacy_presentation(cache_version=3)
        app, _, _ = _build_lang_test_app(
            student_lang="en",
            presentation_text=raw,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/v2/students/{_STUDENT_ID}/language",
                json={"language": "ta"},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        assert resp.json()["session_cache_cleared"] is True

    async def test_translated_headings_returned_from_db_rows(self):
        """translated_headings are resolved from seeded heading_translations rows."""
        import httpx
        heading_rows = [
            _FakeRow("Introduction", {"ml": "ആമുഖം"}),
            _FakeRow("Place Value", {"ml": "സ്ഥാനമൂല്യം"}),
        ]
        app, _, _ = _build_lang_test_app(
            student_lang="en",
            presentation_text=_make_legacy_presentation(),
            heading_rows=heading_rows,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/v2/students/{_STUDENT_ID}/language",
                json={"language": "ml"},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "ആമുഖം" in body["translated_headings"]
        assert "സ്ഥാനമൂല്യം" in body["translated_headings"]

    async def test_prior_language_slice_preserved_in_written_json(self):
        """After PATCH, the written presentation_text still has the prior language slice."""
        import httpx

        # Start with a modern-shape cache that already has "en" data
        modern_raw = json.dumps({
            "cache_version": 3,
            "by_language": {
                "en": {"cards": [{"id": 99}], "concepts_queue": [], "concepts_covered": []},
            },
        })
        app, _, fake_session = _build_lang_test_app(
            student_lang="en",
            presentation_text=modern_raw,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/v2/students/{_STUDENT_ID}/language",
                json={"language": "ml"},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200

        # Inspect the written-back presentation_text on the fake session object
        written = fake_session.presentation_text
        assert written is not None
        parsed = json.loads(written)
        # "en" slice must still be intact
        assert "en" in parsed["by_language"]
        assert parsed["by_language"]["en"]["cards"] == [{"id": 99}]
        # "ml" slice must have been cleared by mark_stale
        assert "ml" not in parsed["by_language"]

    async def test_no_active_session_returns_empty_headings_and_false_flag(self):
        """When there is no active session, translated_headings=[] and cache_cleared=False."""
        import httpx

        db, fake_student, _ = _make_mock_db(student_lang="en", presentation_text=None)

        # Override so the session query returns None (no active session)
        async def _execute_no_session(stmt, *args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=None)
            result.scalar = MagicMock(return_value=_STUDENT_ID)
            result.all = MagicMock(return_value=[])
            return result

        db.execute = _execute_no_session

        app = FastAPI()
        app.state.limiter = limiter

        async def _get_test_db():
            yield db

        fake_user = _make_fake_user(role="admin")

        async def _fake_auth():
            return fake_user

        app.dependency_overrides[get_db] = _get_test_db
        app.dependency_overrides[get_current_user] = _fake_auth
        app.include_router(teaching_router_module.router)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/v2/students/{_STUDENT_ID}/language",
                json={"language": "fr"},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["translated_headings"] == []
        assert body["session_cache_cleared"] is False
