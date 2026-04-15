"""
test_admin_content_controls.py

Tests for admin-set content control flags and their cascade to the student experience.

Business criteria covered:
  BC-ACC-01  _effective_chunk_type returns the DB chunk_type when it is set on the chunk dict.
  BC-ACC-02  _effective_chunk_type falls back to heading-derived type when chunk_type is
             None or missing or empty string.
  BC-ACC-03  list_chunks endpoint excludes chunks whose is_hidden flag is True.
  BC-ACC-04  all_study_complete excludes hidden chunks from required_ids even when they
             have teaching chunk_type — a hidden teaching chunk must not block mastery.
  BC-ACC-05  all_study_complete excludes optional chunks from required_ids even when they
             have teaching chunk_type — an optional teaching chunk must not block mastery.
  BC-ACC-06  When admin overrides a teaching chunk's chunk_type to "exercise", it must
             NOT appear in required_ids (only teaching-typed chunks gate the exam).
  BC-ACC-07  When admin overrides an exercise chunk's chunk_type to "teaching", it MUST
             appear in required_ids and block mastery until completed.
  BC-ACC-08  The section visibility toggle endpoint sets is_hidden on every chunk in a
             section (concept) and returns the count of updated chunks.
  BC-ACC-09  Section visibility toggle returns HTTP 400 when book_slug is missing.
  BC-ACC-10  Section visibility toggle returns HTTP 400 when is_hidden is missing.

Test strategy:
  - _effective_chunk_type and the required_ids / all_study_complete computation are pure
    logic on list[dict] — tested with zero I/O via direct function imports.
  - list_chunks filter logic is tested by replicating the exact filter condition from the
    router (is_hidden guard) on a list of mock ORM-style objects.
  - The section visibility toggle endpoint is tested via httpx + ASGITransport against
    a minimal FastAPI app that mounts admin_router with DB and auth overrides.

Run: pytest backend/tests/test_admin_content_controls.py -v
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ── 1. sys.path setup ──────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── 2. Required env vars before any import ────────────────────────────────────
os.environ.setdefault("API_SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://fake:fake@localhost/fake")

# ── 3. Stub heavy transitive deps before importing admin_router ───────────────
if "fitz" not in sys.modules:
    sys.modules["fitz"] = MagicMock()

if "api.chunk_knowledge_service" not in sys.modules:
    _ck_stub = MagicMock()
    _ck_stub._normalize_image_url = lambda url: url
    sys.modules["api.chunk_knowledge_service"] = _ck_stub

# ── 4. Break circular import: api.main ↔ api.teaching_router ─────────────────
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
    import sys as _sys
    if "db.connection" not in _sys.modules:
        stub_conn = MagicMock()
        stub_conn.get_db = MagicMock()
        _sys.modules["db.connection"] = stub_conn


_stub_heavyweight_modules()

import pytest
import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

# Import the functions under test from teaching_router
from api.teaching_router import _get_chunk_type, _effective_chunk_type  # noqa: E402

import api.admin_router as admin_router_module
from api.admin_router import router as admin_router

admin_router_module._API_KEY = "test-secret"

_API_HEADERS = {"X-API-Key": "test-secret"}
_TEST_SLUG = "prealgebra"
_TEST_CONCEPT = "prealgebra_1.1"


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _chunk_dict(
    chunk_id: str | None = None,
    heading: str = "Use Addition Notation",
    text: str = "x" * 300,
    chunk_type: str | None = None,
    is_hidden: bool = False,
    is_optional: bool = False,
) -> dict:
    """Return a plain dict mimicking the shape returned by chunk_knowledge_service."""
    return {
        "id": chunk_id or str(uuid.uuid4()),
        "heading": heading,
        "text": text,
        "chunk_type": chunk_type,
        "is_hidden": is_hidden,
        "is_optional": is_optional,
        "order_index": 0,
    }


def _required_ids_from_chunks(chunks: list[dict]) -> set[str]:
    """
    Mirrors the all_study_complete required_ids set-comprehension found in
    complete_chunk(), complete_chunk_item(), and evaluate_chunk().

    Uses _effective_chunk_type — the exact function from teaching_router — so any
    change to that function is automatically reflected here.
    """
    return {
        str(c["id"]) for c in chunks
        if _effective_chunk_type(c) == "teaching"
        and not c.get("is_optional", False)
        and not c.get("is_hidden", False)
    }


def _all_study_complete(chunks: list[dict], completed_ids: set[str]) -> bool:
    required = _required_ids_from_chunks(chunks)
    return bool(required) and required.issubset(completed_ids)


def _make_admin_user() -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.email = "admin@test.com"
    u.role = "admin"
    u.is_active = True
    u.email_verified = True
    u.created_at = datetime.now(timezone.utc)
    return u


_STUB_ADMIN = _make_admin_user()


def _make_mock_db() -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    result.scalar = MagicMock(return_value=0)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    result.all = MagicMock(return_value=[])
    result.fetchone = MagicMock(return_value=None)
    result.rowcount = 3
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


def _build_admin_test_app(mock_db: AsyncMock) -> FastAPI:
    app = FastAPI()

    async def _override_get_db():
        yield mock_db

    async def _override_require_admin():
        return _STUB_ADMIN

    from db.connection import get_db
    from auth.dependencies import require_admin

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[require_admin] = _override_require_admin
    app.include_router(admin_router)
    app.state.chunk_knowledge_svc = MagicMock()
    return app


# ══════════════════════════════════════════════════════════════════════════════
# BC-ACC-01 / BC-ACC-02  _effective_chunk_type helper
# ══════════════════════════════════════════════════════════════════════════════

class TestEffectiveChunkType:
    """
    BC-ACC-01 / BC-ACC-02: _effective_chunk_type must respect the DB-stored
    chunk_type field (admin override) and only fall back to heading-derived
    classification when chunk_type is absent, None, or empty string.
    """

    def test_db_chunk_type_returned_when_set_to_exercise(self):
        """
        BC-ACC-01: Admin changed a heading that would normally classify as
        'teaching' to 'exercise' in the DB.  _effective_chunk_type must return
        'exercise' without consulting the heading.
        """
        chunk = _chunk_dict(
            heading="Introduction to Addition",   # heading alone → 'teaching'
            chunk_type="exercise",                # admin override
        )
        assert _effective_chunk_type(chunk) == "exercise"

    def test_db_chunk_type_returned_when_set_to_teaching(self):
        """
        BC-ACC-01: Admin changed 'Practice Makes Perfect' (which heading heuristics
        would classify as 'exercise') to 'teaching' in the DB.
        _effective_chunk_type must return 'teaching'.
        """
        chunk = _chunk_dict(
            heading="Practice Makes Perfect",     # heading alone → 'exercise'
            chunk_type="teaching",               # admin override
        )
        assert _effective_chunk_type(chunk) == "teaching"

    def test_db_chunk_type_returned_for_arbitrary_type_string(self):
        """
        BC-ACC-01: Any truthy chunk_type value stored in the DB is returned as-is,
        even if it is not one of the canonical type strings.
        """
        chunk = _chunk_dict(
            heading="Writing Exercises",
            chunk_type="section_review",
        )
        assert _effective_chunk_type(chunk) == "section_review"

    def test_falls_back_to_heading_when_chunk_type_is_none(self):
        """
        BC-ACC-02: chunk_type=None means no admin override — the heading heuristic
        must be used.  'Use Addition Notation' has no special suffix → 'teaching'.
        """
        chunk = _chunk_dict(
            heading="Use Addition Notation",
            chunk_type=None,
        )
        result = _effective_chunk_type(chunk)
        assert result == _get_chunk_type("Use Addition Notation", "x" * 300)

    def test_falls_back_to_heading_when_chunk_type_key_is_absent(self):
        """
        BC-ACC-02: A dict with no 'chunk_type' key at all must fall back to the
        heading heuristic (dict.get returns None for missing keys).
        """
        chunk = {"id": "abc", "heading": "Practice Makes Perfect", "text": "x" * 300}
        result = _effective_chunk_type(chunk)
        assert result == _get_chunk_type("Practice Makes Perfect", "x" * 300)

    def test_falls_back_to_heading_when_chunk_type_is_empty_string(self):
        """
        BC-ACC-02: An empty string chunk_type is falsy — must fall through to the
        heading heuristic, exactly like None.
        """
        chunk = _chunk_dict(
            heading="Everyday Math",
            chunk_type="",
        )
        result = _effective_chunk_type(chunk)
        assert result == _get_chunk_type("Everyday Math", "x" * 300)

    def test_heading_fallback_for_learning_objective(self):
        """
        BC-ACC-02: 'Learning Objectives' with no chunk_type must derive its type
        from the heading heuristic → 'learning_objective'.
        """
        chunk = _chunk_dict(
            heading="Learning Objectives",
            chunk_type=None,
        )
        assert _effective_chunk_type(chunk) == "learning_objective"

    def test_heading_fallback_for_section_review(self):
        """
        BC-ACC-02: A bare section-title heading with no substantial body text and
        no chunk_type override must derive 'section_review' from the heading.
        The text must be short (≤ 200 chars) to avoid the reclassification rule.
        """
        chunk = {
            "id": "abc",
            "heading": "1.1 Introduction to Whole Numbers",
            "text": "Short intro.",   # < 200 chars → stays section_review
            "chunk_type": None,
        }
        assert _effective_chunk_type(chunk) == "section_review"


# ══════════════════════════════════════════════════════════════════════════════
# BC-ACC-03  Hidden chunks filtered from list_chunks response
# ══════════════════════════════════════════════════════════════════════════════

class TestHiddenChunkFiltering:
    """
    BC-ACC-03: When an admin hides a chunk (is_hidden=True), it must not appear
    in the list_chunks response sent to the student.

    We replicate the filter condition from the router directly on mock ORM objects
    to test the filter logic without spinning up a DB.
    """

    @staticmethod
    def _apply_list_chunks_filter(orm_chunks: list) -> list:
        """
        Mirrors the filter on line ~1586 of teaching_router.py:
            [c for c in result.scalars().all()
             if len((c.text or "").strip()) >= 100 and not c.is_hidden]
        """
        return [
            c for c in orm_chunks
            if len((c.text or "").strip()) >= 100 and not c.is_hidden
        ]

    def _make_orm_chunk(
        self,
        text: str = "x" * 150,
        is_hidden: bool = False,
    ) -> MagicMock:
        c = MagicMock()
        c.id = uuid.uuid4()
        c.text = text
        c.is_hidden = is_hidden
        c.heading = "Some Heading"
        c.order_index = 0
        return c

    def test_visible_chunks_are_included(self):
        """
        BC-ACC-03: Chunks with is_hidden=False and sufficient text are included.
        """
        chunks = [self._make_orm_chunk(is_hidden=False)]
        result = self._apply_list_chunks_filter(chunks)
        assert len(result) == 1

    def test_hidden_chunk_is_excluded(self):
        """
        BC-ACC-03: A single hidden chunk produces an empty list — the student sees nothing.
        """
        chunks = [self._make_orm_chunk(is_hidden=True)]
        result = self._apply_list_chunks_filter(chunks)
        assert result == []

    def test_mixed_visibility_only_visible_returned(self):
        """
        BC-ACC-03: With 3 chunks (2 visible, 1 hidden), only the 2 visible chunks
        pass the filter.
        """
        chunks = [
            self._make_orm_chunk(is_hidden=False),
            self._make_orm_chunk(is_hidden=True),
            self._make_orm_chunk(is_hidden=False),
        ]
        result = self._apply_list_chunks_filter(chunks)
        assert len(result) == 2
        assert all(not c.is_hidden for c in result)

    def test_short_text_chunk_excluded_regardless_of_visibility(self):
        """
        BC-ACC-03 (boundary): The < 100 chars filter is independent of is_hidden.
        A stub chunk with only 50 chars is filtered even when is_hidden=False.
        """
        chunks = [self._make_orm_chunk(text="x" * 50, is_hidden=False)]
        result = self._apply_list_chunks_filter(chunks)
        assert result == []

    def test_all_hidden_produces_empty_list(self):
        """
        BC-ACC-03: When every chunk in a concept is hidden, the student receives an
        empty list — signalling the ChromaDB fallback path.
        """
        chunks = [self._make_orm_chunk(is_hidden=True) for _ in range(4)]
        result = self._apply_list_chunks_filter(chunks)
        assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# BC-ACC-04 / BC-ACC-05 / BC-ACC-06 / BC-ACC-07  allStudyComplete with overrides
# ══════════════════════════════════════════════════════════════════════════════

class TestAllStudyCompleteWithAdminOverrides:
    """
    Tests for all_study_complete logic when admin flags (is_hidden, is_optional,
    chunk_type) modify which chunks are included in required_ids.

    The three `complete_*` router handlers share the identical set-comprehension,
    so the business rules tested here apply to all three paths.
    """

    # ── BC-ACC-04: Hidden chunks excluded from required_ids ───────────────────

    def test_hidden_teaching_chunk_not_in_required_ids(self):
        """
        BC-ACC-04: A chunk with chunk_type='teaching' and is_hidden=True must NOT
        appear in required_ids — it must never block mastery.
        """
        chunk = _chunk_dict(
            chunk_id="hidden-c1",
            heading="Identify Whole Numbers",
            chunk_type="teaching",
            is_hidden=True,
        )
        required = _required_ids_from_chunks([chunk])
        assert "hidden-c1" not in required

    def test_hidden_chunk_completion_not_required_for_all_study_complete(self):
        """
        BC-ACC-04: A student who completes only the visible teaching chunk (c1) must
        reach all_study_complete=True even though the hidden teaching chunk (c2) is
        not completed.
        """
        c1 = _chunk_dict(chunk_id="c1", heading="Add Whole Numbers", chunk_type="teaching", is_hidden=False)
        c2 = _chunk_dict(chunk_id="c2", heading="Model Whole Numbers", chunk_type="teaching", is_hidden=True)
        completed = {"c1"}
        assert _all_study_complete([c1, c2], completed) is True

    def test_all_teaching_hidden_gives_empty_required_ids(self):
        """
        BC-ACC-04: When every teaching chunk is hidden, required_ids is empty and
        all_study_complete must return False (no progress to validate).
        """
        chunks = [
            _chunk_dict(chunk_id=f"c{i}", chunk_type="teaching", is_hidden=True)
            for i in range(3)
        ]
        assert _all_study_complete(chunks, {"c0", "c1", "c2"}) is False

    # ── BC-ACC-05: Optional chunks excluded from required_ids ─────────────────

    def test_optional_teaching_chunk_not_in_required_ids(self):
        """
        BC-ACC-05: A chunk with chunk_type='teaching' and is_optional=True must NOT
        appear in required_ids — optional enrichment content must not gate the exam.
        """
        chunk = _chunk_dict(
            chunk_id="opt-c1",
            heading="Extension Activity",
            chunk_type="teaching",
            is_optional=True,
        )
        required = _required_ids_from_chunks([chunk])
        assert "opt-c1" not in required

    def test_optional_chunk_can_be_skipped_without_blocking_mastery(self):
        """
        BC-ACC-05: All required (non-optional, visible, teaching) chunks completed +
        optional chunk NOT completed → all_study_complete=True.
        """
        required_c = _chunk_dict(chunk_id="c1", heading="Identify Whole Numbers", chunk_type="teaching")
        optional_c = _chunk_dict(chunk_id="c2", heading="Extension Activity", chunk_type="teaching", is_optional=True)
        completed = {"c1"}  # optional chunk absent
        assert _all_study_complete([required_c, optional_c], completed) is True

    def test_hidden_and_optional_chunk_both_excluded_from_required(self):
        """
        BC-ACC-04 / BC-ACC-05: When a chunk is both hidden and optional, it must
        still be excluded from required_ids (belt-and-suspenders guard).
        """
        chunk = _chunk_dict(
            chunk_id="both-excluded",
            chunk_type="teaching",
            is_hidden=True,
            is_optional=True,
        )
        required = _required_ids_from_chunks([chunk])
        assert "both-excluded" not in required

    # ── BC-ACC-06: Admin converts teaching → exercise removes from required_ids ─

    def test_admin_reclassified_teaching_to_exercise_excluded(self):
        """
        BC-ACC-06: When the admin stores chunk_type='exercise' for a chunk whose
        heading would normally produce 'teaching', _effective_chunk_type returns
        'exercise' and the chunk must NOT be in required_ids.

        Business impact: Reclassified chunks no longer gate the exam — the student
        is not penalised for skipping an exercise chunk.
        """
        chunk = _chunk_dict(
            chunk_id="reclassified-to-exercise",
            heading="Introduction to Addition",   # heading → teaching
            chunk_type="exercise",               # admin override → exercise
        )
        required = _required_ids_from_chunks([chunk])
        assert "reclassified-to-exercise" not in required

    def test_all_study_complete_true_without_admin_reclassified_chunk(self):
        """
        BC-ACC-06: Student completes the original teaching chunk (c1).  Admin has
        reclassified teaching chunk c2 as 'exercise'.  all_study_complete must be
        True because c2 is no longer in required_ids.
        """
        c1 = _chunk_dict(chunk_id="c1", heading="Identify Whole Numbers", chunk_type="teaching")
        c2 = _chunk_dict(
            chunk_id="c2",
            heading="Use Addition Notation",   # would be teaching by heading alone
            chunk_type="exercise",             # admin overrode to exercise
        )
        completed = {"c1"}  # c2 NOT completed
        assert _all_study_complete([c1, c2], completed) is True

    # ── BC-ACC-07: Admin converts exercise → teaching adds to required_ids ─────

    def test_admin_reclassified_exercise_to_teaching_is_required(self):
        """
        BC-ACC-07: When the admin stores chunk_type='teaching' for a chunk whose
        heading would normally produce 'exercise', _effective_chunk_type returns
        'teaching' and the chunk MUST be in required_ids.

        Business impact: The reclassified chunk now gates the exam — the student
        must complete it before mastery is granted.
        """
        chunk = _chunk_dict(
            chunk_id="reclassified-to-teaching",
            heading="Practice Makes Perfect",   # heading → exercise
            chunk_type="teaching",              # admin override → teaching
        )
        required = _required_ids_from_chunks([chunk])
        assert "reclassified-to-teaching" in required

    def test_all_study_complete_false_until_admin_reclassified_chunk_done(self):
        """
        BC-ACC-07: Admin promoted an exercise chunk to teaching.  The student must
        complete it before all_study_complete becomes True.
        """
        c1 = _chunk_dict(chunk_id="c1", heading="Identify Whole Numbers", chunk_type="teaching")
        c2 = _chunk_dict(
            chunk_id="c2",
            heading="Practice Makes Perfect",   # heading → exercise
            chunk_type="teaching",             # admin overrode to teaching — now required
        )
        # Only c1 completed — c2 required but missing
        assert _all_study_complete([c1, c2], {"c1"}) is False
        # Both completed — requirement satisfied
        assert _all_study_complete([c1, c2], {"c1", "c2"}) is True

    def test_db_chunk_type_takes_priority_over_heading_for_required_ids(self):
        """
        BC-ACC-01 / BC-ACC-07: The DB chunk_type field (from admin override) always
        wins over the heading heuristic when computing required_ids.

        Asserts that two chunks with identical headings ('Learning Objectives') but
        different DB chunk_type values produce different required_ids membership.
        """
        heading = "Learning Objectives"  # heading heuristic → 'learning_objective' (not teaching)

        # Admin left chunk_type empty — heading heuristic used (learning_objective → not required)
        c_default = _chunk_dict(chunk_id="c-default", heading=heading, chunk_type=None)
        # Admin overrode to 'teaching' — must be required
        c_override = _chunk_dict(chunk_id="c-override", heading=heading, chunk_type="teaching")

        required = _required_ids_from_chunks([c_default, c_override])
        assert "c-default" not in required
        assert "c-override" in required

    # ── Combined scenario ─────────────────────────────────────────────────────

    def test_mixed_overrides_full_scenario(self):
        """
        BC-ACC-04/05/06/07 combined: A concept with all four flag combinations.

        Chunk layout:
          c1 — teaching, visible, not optional        → REQUIRED
          c2 — teaching, hidden                       → excluded (hidden)
          c3 — teaching, optional                     → excluded (optional)
          c4 — exercise (by heading), admin → teaching → REQUIRED (override)
          c5 — teaching (by heading), admin → exercise → excluded (override)

        Only c1 and c4 must be in required_ids.
        """
        c1 = _chunk_dict(chunk_id="c1", heading="Identify Whole Numbers", chunk_type="teaching")
        c2 = _chunk_dict(chunk_id="c2", heading="Add Whole Numbers", chunk_type="teaching", is_hidden=True)
        c3 = _chunk_dict(chunk_id="c3", heading="Model Numbers", chunk_type="teaching", is_optional=True)
        c4 = _chunk_dict(chunk_id="c4", heading="Practice Makes Perfect", chunk_type="teaching")   # admin → teaching
        c5 = _chunk_dict(chunk_id="c5", heading="Use Notation", chunk_type="exercise")              # admin → exercise

        chunks = [c1, c2, c3, c4, c5]
        required = _required_ids_from_chunks(chunks)

        assert required == {"c1", "c4"}

        # Student completed only c1 — c4 still needed
        assert _all_study_complete(chunks, {"c1"}) is False
        # Student completed both c1 and c4 — done
        assert _all_study_complete(chunks, {"c1", "c4"}) is True


# ══════════════════════════════════════════════════════════════════════════════
# BC-ACC-08 / BC-ACC-09 / BC-ACC-10  Section visibility toggle endpoint
# ══════════════════════════════════════════════════════════════════════════════

class TestSectionVisibilityToggleEndpoint:
    """
    BC-ACC-08: PATCH /api/admin/sections/{concept_id}/visibility executes an UPDATE
    against every chunk in a section and returns the updated chunk count.
    BC-ACC-09: Missing book_slug → HTTP 400.
    BC-ACC-10: Missing is_hidden → HTTP 400.
    """

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        db = _make_mock_db()
        return db

    @pytest.fixture
    def app(self, mock_db: AsyncMock) -> FastAPI:
        return _build_admin_test_app(mock_db)

    # ── BC-ACC-08: happy path ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_toggle_hidden_true_updates_all_chunks_in_section(self, app, mock_db):
        """
        BC-ACC-08: Setting is_hidden=True on a section should execute an UPDATE
        and return the number of rows affected (rowcount=3 in the mock).
        """
        mock_db.execute.return_value.rowcount = 3

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/sections/{_TEST_CONCEPT}/visibility",
                headers=_API_HEADERS,
                json={"book_slug": _TEST_SLUG, "is_hidden": True},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["updated"] == 3
        # DB execute and commit must have been called
        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_toggle_hidden_false_unhides_all_chunks_in_section(self, app, mock_db):
        """
        BC-ACC-08: Setting is_hidden=False should also succeed and return the count.
        """
        mock_db.execute.return_value.rowcount = 5

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/sections/{_TEST_CONCEPT}/visibility",
                headers=_API_HEADERS,
                json={"book_slug": _TEST_SLUG, "is_hidden": False},
            )

        assert resp.status_code == 200
        assert resp.json()["updated"] == 5

    @pytest.mark.asyncio
    async def test_section_with_slash_in_concept_id_accepted(self, app, mock_db):
        """
        BC-ACC-08: Concept IDs sometimes contain slashes (path router pattern).
        The router uses {concept_id:path} — verify the path converter works.
        """
        mock_db.execute.return_value.rowcount = 2

        concept_with_slash = "prealgebra/1.1"
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/sections/{concept_with_slash}/visibility",
                headers=_API_HEADERS,
                json={"book_slug": _TEST_SLUG, "is_hidden": True},
            )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_zero_rows_updated_returns_zero_count(self, app, mock_db):
        """
        BC-ACC-08: When the section has no matching chunks (e.g. wrong concept_id),
        rowcount=0 is returned — the endpoint must not treat this as an error.
        """
        mock_db.execute.return_value.rowcount = 0

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/sections/{_TEST_CONCEPT}/visibility",
                headers=_API_HEADERS,
                json={"book_slug": "unknown_book", "is_hidden": True},
            )

        assert resp.status_code == 200
        assert resp.json()["updated"] == 0

    # ── BC-ACC-09: missing book_slug → 400 ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_missing_book_slug_returns_400(self, app):
        """
        BC-ACC-09: book_slug is required.  Omitting it must return HTTP 400 with a
        descriptive error message so the admin knows exactly what is missing.
        """
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/sections/{_TEST_CONCEPT}/visibility",
                headers=_API_HEADERS,
                json={"is_hidden": True},  # no book_slug
            )

        assert resp.status_code == 400
        assert "book_slug" in resp.json().get("detail", "").lower()

    # ── BC-ACC-10: missing is_hidden → 400 ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_missing_is_hidden_returns_400(self, app):
        """
        BC-ACC-10: is_hidden is required.  Omitting it must return HTTP 400 with
        a descriptive error so the admin knows what is missing.
        """
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/sections/{_TEST_CONCEPT}/visibility",
                headers=_API_HEADERS,
                json={"book_slug": _TEST_SLUG},  # no is_hidden
            )

        assert resp.status_code == 400
        assert "is_hidden" in resp.json().get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_empty_body_returns_400_for_both_fields(self, app):
        """
        BC-ACC-09 / BC-ACC-10: An entirely empty body must return 400 (book_slug is
        checked first).
        """
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/sections/{_TEST_CONCEPT}/visibility",
                headers=_API_HEADERS,
                json={},
            )

        assert resp.status_code == 400
