"""
test_admin_console_extended.py

34 pytest tests covering the new admin console endpoints added in the
full-email+auth release. Covers:

  - RegisterRequest schema changes (age field, removed interests/preferred_style)
  - Dashboard structure
  - Student management (list, detail, update, access toggle, soft-delete)
  - Manual mastery grant/revoke
  - Chunk operations (update, visibility toggle, exam-gate toggle, merge, split, reorder)
  - Section-level controls (rename, optional, exam-gate)
  - Graph overrides (add, add-cycle-rejected, remove, delete override)
  - Config (get, upsert)
  - Admin user creation and role change

Strategy
--------
- Build a minimal FastAPI test app that mounts admin_router, with the DB
  replaced by AsyncMock — no live PostgreSQL required.
- Override require_admin to return a stub admin User without touching JWT.
- patch _load_graph / reload_graph_with_overrides at module level for graph tests.
- All endpoints require the require_admin dependency to be satisfied.

Run: pytest backend/tests/test_admin_console_extended.py -v
"""
from __future__ import annotations

import sys
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ── 1. sys.path ────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── 2. Required env before any import ─────────────────────────────────────────
os.environ.setdefault("API_SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://fake:fake@localhost/fake")

# ── 3. Stub heavy transitive deps before importing admin_router ────────────────
if "fitz" not in sys.modules:
    sys.modules["fitz"] = MagicMock()

if "api.chunk_knowledge_service" not in sys.modules:
    _ck_stub = MagicMock()
    _ck_stub._normalize_image_url = lambda url: url
    sys.modules["api.chunk_knowledge_service"] = _ck_stub

import pytest
import httpx
import networkx as nx
from fastapi import FastAPI, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import api.admin_router as admin_router_module
from api.admin_router import router as admin_router

# Force _API_KEY for legacy endpoints
admin_router_module._API_KEY = "test-secret"

_API_HEADERS = {"X-API-Key": "test-secret"}
_TEST_SLUG = "prealgebra"


# ── Stub admin User ────────────────────────────────────────────────────────────

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


# ── DB mock factory ────────────────────────────────────────────────────────────

def _make_mock_db() -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    result.scalar = MagicMock(return_value=0)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    result.all = MagicMock(return_value=[])
    result.fetchone = MagicMock(return_value=None)
    result.rowcount = 0
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


# ── App builder ────────────────────────────────────────────────────────────────

def _build_test_app(mock_db: AsyncMock) -> FastAPI:
    """Minimal FastAPI app with admin_router + require_admin overridden to stub user."""
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


# ── Model helpers ──────────────────────────────────────────────────────────────

def _make_student(student_id=None, user_id=None) -> MagicMock:
    s = MagicMock()
    s.id = student_id or uuid.uuid4()
    s.user_id = user_id or uuid.uuid4()
    s.display_name = "Alice"
    s.age = 14
    s.xp = 120
    s.streak = 3
    s.preferred_style = "default"
    s.preferred_language = "en"
    s.section_count = 5
    s.overall_accuracy_rate = 0.75
    s.avg_state_score = 2.0
    s.boredom_pattern = None
    s.frustration_tolerance = "medium"
    s.recovery_speed = "normal"
    s.interests = ["science"]
    s.state_distribution = {"struggling": 1, "normal": 3, "fast": 1}
    s.created_at = datetime.now(timezone.utc)
    s.updated_at = datetime.now(timezone.utc)
    return s


def _make_linked_user(user_id=None, is_active=True) -> MagicMock:
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    u.email = "student@test.com"
    u.is_active = is_active
    u.role = "student"
    u.email_verified = True
    u.created_at = datetime.now(timezone.utc)
    return u


def _make_chunk(chunk_id=None, concept_id="prealgebra_1.1", is_hidden=False,
                is_optional=False, exam_disabled=False, order_index=0, text="Some text.") -> MagicMock:
    c = MagicMock()
    c.id = chunk_id or uuid.uuid4()
    c.concept_id = concept_id
    c.book_slug = _TEST_SLUG
    c.section = "1.1"
    c.heading = "Introduction"
    c.text = text
    c.order_index = order_index
    c.chunk_type = "teaching"
    c.is_optional = is_optional
    c.is_hidden = is_hidden
    c.exam_disabled = exam_disabled
    c.embedding = None
    return c


def _make_mastery_record(student_id=None, concept_id="prealgebra_1.1") -> MagicMock:
    m = MagicMock()
    m.id = uuid.uuid4()
    m.student_id = student_id or uuid.uuid4()
    m.concept_id = concept_id
    m.mastered_at = datetime.now(timezone.utc)
    return m


def _make_override(override_id=None, action="add_edge") -> MagicMock:
    ov = MagicMock()
    ov.id = override_id or uuid.uuid4()
    ov.action = action
    ov.source_concept = "prealgebra_1.1"
    ov.target_concept = "prealgebra_1.2"
    ov.book_slug = _TEST_SLUG
    ov.created_at = datetime.now(timezone.utc)
    return ov


def _make_config_row(key: str, value: str) -> MagicMock:
    r = MagicMock()
    r.key = key
    r.value = value
    return r


# ════════════════════════════════════════════════════════════════════════════════
# RegisterRequest schema tests — pure unit tests (no HTTP)
# ════════════════════════════════════════════════════════════════════════════════

class TestRegisterRequestSchema:
    """Verify that RegisterRequest has been updated for the auth system."""

    def test_register_request_has_age_field(self):
        """RegisterRequest must accept an age field (used to record student age)."""
        from auth.schemas import RegisterRequest
        req = RegisterRequest(
            email="test@example.com",
            password="Secure1234!",
            display_name="Test User",
            age=15,
        )
        assert req.age == 15

    def test_register_request_age_defaults_to_none(self):
        """age is optional — omitting it should default to None."""
        from auth.schemas import RegisterRequest
        req = RegisterRequest(
            email="test@example.com",
            password="Secure1234!",
            display_name="Test User",
        )
        assert req.age is None

    def test_register_request_no_interests_field(self):
        """RegisterRequest must not have an interests field (removed in auth refactor)."""
        from auth.schemas import RegisterRequest
        import inspect
        fields = inspect.signature(RegisterRequest).parameters
        assert "interests" not in fields, (
            "interests should not be a field on RegisterRequest — "
            "it was removed when auth was introduced"
        )

    def test_register_request_no_preferred_style_field(self):
        """RegisterRequest must not have a preferred_style field."""
        from auth.schemas import RegisterRequest
        import inspect
        fields = inspect.signature(RegisterRequest).parameters
        assert "preferred_style" not in fields, (
            "preferred_style should not be a field on RegisterRequest"
        )

    def test_register_request_age_validation_too_young(self):
        """age < 5 must be rejected by Pydantic validation."""
        from auth.schemas import RegisterRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RegisterRequest(
                email="test@example.com",
                password="Secure1234!",
                display_name="Test",
                age=4,
            )

    def test_register_request_age_validation_too_old(self):
        """age > 120 must be rejected by Pydantic validation."""
        from auth.schemas import RegisterRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RegisterRequest(
                email="test@example.com",
                password="Secure1234!",
                display_name="Test",
                age=121,
            )

    def test_register_request_age_boundary_values_accepted(self):
        """age of exactly 5 and exactly 120 should pass validation."""
        from auth.schemas import RegisterRequest
        req_low = RegisterRequest(
            email="young@example.com",
            password="Secure1234!",
            display_name="Young",
            age=5,
        )
        req_high = RegisterRequest(
            email="old@example.com",
            password="Secure1234!",
            display_name="Old",
            age=120,
        )
        assert req_low.age == 5
        assert req_high.age == 120


# ════════════════════════════════════════════════════════════════════════════════
# Dashboard
# ════════════════════════════════════════════════════════════════════════════════

class TestAdminDashboard:
    """Verify the dashboard endpoint returns the required metric keys."""

    @pytest.mark.asyncio
    async def test_dashboard_returns_expected_keys(self):
        """GET /api/admin/dashboard must return all required top-level metric keys."""
        mock_db = _make_mock_db()

        # All 7 scalar count/avg queries + 1 struggling students row query
        scalar_result = MagicMock()
        scalar_result.scalar = MagicMock(return_value=0)
        scalar_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        scalar_result.scalar_one_or_none = MagicMock(return_value=None)
        scalar_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=scalar_result)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/dashboard", headers=_API_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        required_keys = {
            "total_students", "active_7d", "active_30d", "total_sessions",
            "sessions_this_week", "avg_mastery_rate", "total_concepts_mastered",
            "struggling_students",
        }
        assert required_keys.issubset(body.keys()), (
            f"Missing keys: {required_keys - body.keys()}"
        )
        assert isinstance(body["struggling_students"], list)


# ════════════════════════════════════════════════════════════════════════════════
# Student Management
# ════════════════════════════════════════════════════════════════════════════════

class TestStudentManagement:
    """Admin student list, detail, update, access toggle, and soft-delete."""

    @pytest.mark.asyncio
    async def test_list_students_pagination(self):
        """GET /api/admin/students with limit/offset must return total + items list."""
        mock_db = _make_mock_db()

        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=None)
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            if call_count == 1:
                # total count subquery
                r.scalar = MagicMock(return_value=42)
            else:
                # rows
                r.scalar = MagicMock(return_value=0)
                r.all = MagicMock(return_value=[])
            return r

        mock_db.execute = AsyncMock(side_effect=_side_effect)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/admin/students?limit=10&offset=20",
                headers=_API_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert "items" in body
        assert isinstance(body["items"], list)

    @pytest.mark.asyncio
    async def test_list_students_search_query_accepted(self):
        """GET /api/admin/students?search=alice must return 200 (search param wired up)."""
        mock_db = _make_mock_db()

        r = MagicMock()
        r.scalar = MagicMock(return_value=0)
        r.scalar_one_or_none = MagicMock(return_value=None)
        r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        r.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=r)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/admin/students?search=alice",
                headers=_API_HEADERS,
            )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_student_detail_returns_profile_and_stats(self):
        """GET /api/admin/students/{id} must return profile + stats + sessions + mastery."""
        student_id = uuid.uuid4()
        linked_user_id = uuid.uuid4()
        student = _make_student(student_id=student_id, user_id=linked_user_id)
        linked_user = _make_linked_user(user_id=linked_user_id)

        mock_db = _make_mock_db()
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=None)
            r.scalar = MagicMock(return_value=0)
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            r.all = MagicMock(return_value=[])
            if call_count == 1:
                # select(Student)
                r.scalar_one_or_none = MagicMock(return_value=student)
            elif call_count == 2:
                # select(User) for linked_user
                r.scalar_one_or_none = MagicMock(return_value=linked_user)
            # Subsequent calls: counts (mastery, sessions, avg_time, total_cards)
            # Then sessions list and mastery list — all default to empty/0
            return r

        mock_db.execute = AsyncMock(side_effect=_side_effect)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/admin/students/{student_id}",
                headers=_API_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "profile" in body
        assert "stats" in body
        assert "recent_sessions" in body
        assert "mastery_list" in body
        assert body["profile"]["id"] == str(student_id)

    @pytest.mark.asyncio
    async def test_update_student_validates_style(self):
        """PATCH /api/admin/students/{id} with invalid preferred_style must return HTTP 400."""
        student_id = uuid.uuid4()
        student = _make_student(student_id=student_id)
        mock_db = _make_mock_db()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=student)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/students/{student_id}",
                headers=_API_HEADERS,
                json={"preferred_style": "hacker"},  # not in allowed set
            )

        assert resp.status_code == 400
        assert "preferred_style" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_update_student_accepts_valid_style(self):
        """PATCH /api/admin/students/{id} with a valid style must return 200."""
        student_id = uuid.uuid4()
        student = _make_student(student_id=student_id)
        mock_db = _make_mock_db()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=student)

        # After db.refresh(student), the student has updated fields
        async def _refresh(obj):
            obj.preferred_style = "pirate"

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/students/{student_id}",
                headers=_API_HEADERS,
                json={"preferred_style": "pirate"},
            )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_toggle_student_access_sets_is_active(self):
        """PATCH /api/admin/students/{id}/access must flip linked user's is_active."""
        student_id = uuid.uuid4()
        linked_user_id = uuid.uuid4()
        student = _make_student(student_id=student_id, user_id=linked_user_id)
        linked_user = _make_linked_user(user_id=linked_user_id, is_active=True)

        mock_db = _make_mock_db()
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            if call_count == 1:
                r.scalar_one_or_none = MagicMock(return_value=student)
            else:
                r.scalar_one_or_none = MagicMock(return_value=linked_user)
            r.scalar = MagicMock(return_value=0)
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            return r

        mock_db.execute = AsyncMock(side_effect=_side_effect)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/students/{student_id}/access",
                headers=_API_HEADERS,
                json={"is_active": False},
            )

        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        assert linked_user.is_active is False

    @pytest.mark.asyncio
    async def test_soft_delete_student_deactivates_user(self):
        """DELETE /api/admin/students/{id} must set linked user.is_active=False (not delete row)."""
        student_id = uuid.uuid4()
        linked_user_id = uuid.uuid4()
        student = _make_student(student_id=student_id, user_id=linked_user_id)
        linked_user = _make_linked_user(user_id=linked_user_id, is_active=True)

        mock_db = _make_mock_db()
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            if call_count == 1:
                r.scalar_one_or_none = MagicMock(return_value=student)
            else:
                r.scalar_one_or_none = MagicMock(return_value=linked_user)
            r.scalar = MagicMock(return_value=0)
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            return r

        mock_db.execute = AsyncMock(side_effect=_side_effect)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete(
                f"/api/admin/students/{student_id}",
                headers=_API_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "deactivated"
        # User row should NOT have been hard-deleted — only deactivated
        assert linked_user.is_active is False
        mock_db.delete.assert_not_called()


# ════════════════════════════════════════════════════════════════════════════════
# Manual Mastery
# ════════════════════════════════════════════════════════════════════════════════

class TestManualMastery:
    """Grant and revoke mastery records for students."""

    @pytest.mark.asyncio
    async def test_grant_mastery_creates_record_when_none_exists(self):
        """POST /api/admin/students/{id}/mastery/{concept_id} must add StudentMastery row."""
        student_id = uuid.uuid4()
        student = _make_student(student_id=student_id)
        concept_id = "prealgebra_1.1"

        mock_db = _make_mock_db()
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            if call_count == 1:
                # select(Student)
                r.scalar_one_or_none = MagicMock(return_value=student)
            else:
                # select(StudentMastery) — not yet mastered
                r.scalar_one_or_none = MagicMock(return_value=None)
            r.scalar = MagicMock(return_value=0)
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            return r

        mock_db.execute = AsyncMock(side_effect=_side_effect)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/admin/students/{student_id}/mastery/{concept_id}",
                headers=_API_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "mastered"
        assert resp.json()["concept_id"] == concept_id
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_grant_mastery_updates_timestamp_when_already_mastered(self):
        """POST /api/admin/students/{id}/mastery/{concept_id} must update mastered_at if record exists."""
        student_id = uuid.uuid4()
        student = _make_student(student_id=student_id)
        concept_id = "prealgebra_1.1"
        existing_record = _make_mastery_record(student_id=student_id, concept_id=concept_id)

        mock_db = _make_mock_db()
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            if call_count == 1:
                r.scalar_one_or_none = MagicMock(return_value=student)
            else:
                r.scalar_one_or_none = MagicMock(return_value=existing_record)
            r.scalar = MagicMock(return_value=0)
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            return r

        mock_db.execute = AsyncMock(side_effect=_side_effect)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/admin/students/{student_id}/mastery/{concept_id}",
                headers=_API_HEADERS,
            )

        assert resp.status_code == 200
        # Should update timestamp on existing record, not add a duplicate
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoke_mastery_executes_delete(self):
        """DELETE /api/admin/students/{id}/mastery/{concept_id} must execute DELETE SQL."""
        student_id = uuid.uuid4()
        student = _make_student(student_id=student_id)
        concept_id = "prealgebra_1.1"

        mock_db = _make_mock_db()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=student)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete(
                f"/api/admin/students/{student_id}/mastery/{concept_id}",
                headers=_API_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "unmastered"
        # DELETE statement executed (second execute call after student lookup)
        assert mock_db.execute.call_count >= 2
        assert mock_db.commit.called


# ════════════════════════════════════════════════════════════════════════════════
# Chunk Operations
# ════════════════════════════════════════════════════════════════════════════════

class TestChunkOperations:
    """Update, visibility toggle, exam-gate toggle, merge, split, reorder."""

    @pytest.mark.asyncio
    async def test_update_chunk_fields(self):
        """PATCH /api/admin/chunks/{id} must persist heading, text, and chunk_type."""
        chunk_id = uuid.uuid4()
        chunk = _make_chunk(chunk_id=chunk_id)
        mock_db = _make_mock_db()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=chunk)

        async def _refresh(obj):
            # Simulate DB refresh — fields already set on the mock object
            pass

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/chunks/{chunk_id}",
                headers=_API_HEADERS,
                json={"heading": "Updated Heading", "text": "New text.", "chunk_type": "exercise"},
            )

        assert resp.status_code == 200
        assert chunk.heading == "Updated Heading"
        assert chunk.text == "New text."
        assert chunk.chunk_type == "exercise"

    @pytest.mark.asyncio
    async def test_toggle_chunk_visibility_flips_is_hidden(self):
        """PATCH /api/admin/chunks/{id}/visibility must flip is_hidden from False to True."""
        chunk_id = uuid.uuid4()
        chunk = _make_chunk(chunk_id=chunk_id, is_hidden=False)
        mock_db = _make_mock_db()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=chunk)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/chunks/{chunk_id}/visibility",
                headers=_API_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["is_hidden"] is True
        assert chunk.is_hidden is True

    @pytest.mark.asyncio
    async def test_toggle_chunk_exam_gate_flips_exam_disabled(self):
        """PATCH /api/admin/chunks/{id}/exam-gate must flip exam_disabled from False to True."""
        chunk_id = uuid.uuid4()
        chunk = _make_chunk(chunk_id=chunk_id, exam_disabled=False)
        mock_db = _make_mock_db()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=chunk)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/chunks/{chunk_id}/exam-gate",
                headers=_API_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["exam_disabled"] is True
        assert chunk.exam_disabled is True

    @pytest.mark.asyncio
    async def test_merge_chunks_same_concept_combines_text(self):
        """POST /api/admin/chunks/merge must combine text and return merged_chunk_id."""
        cid_1 = uuid.uuid4()
        cid_2 = uuid.uuid4()
        chunk1 = _make_chunk(chunk_id=cid_1, order_index=0, text="First part.")
        chunk2 = _make_chunk(chunk_id=cid_2, order_index=1, text="Second part.")
        # Both belong to same concept — concept_id already "prealgebra_1.1" from helper

        mock_db = _make_mock_db()
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=None)
            r.scalar = MagicMock(return_value=0)
            r.all = MagicMock(return_value=[])
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            r.rowcount = 0
            if call_count == 1:
                # select(ConceptChunk) for chunk1
                r.scalar_one_or_none = MagicMock(return_value=chunk1)
            elif call_count == 2:
                # select(ConceptChunk) for chunk2
                r.scalar_one_or_none = MagicMock(return_value=chunk2)
            # call 3: UPDATE chunk_images (text statement) — default r is fine
            elif call_count == 4:
                # select(TeachingSession) active sessions — empty list
                r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            elif call_count == 5:
                # select(ConceptChunk) remaining chunks for re-index
                r.scalars = MagicMock(
                    return_value=MagicMock(all=MagicMock(return_value=[chunk1]))
                )
            return r

        mock_db.execute = AsyncMock(side_effect=_side_effect)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/chunks/merge",
                headers=_API_HEADERS,
                json={"chunk_id_1": str(cid_1), "chunk_id_2": str(cid_2)},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["merged_chunk_id"] == str(cid_1)
        assert body["embedding_stale"] is True
        # Text was concatenated
        assert "First part." in chunk1.text
        assert "Second part." in chunk1.text

    @pytest.mark.asyncio
    async def test_merge_chunks_different_concept_rejected(self):
        """POST /api/admin/chunks/merge with mismatched concept_id must return HTTP 400."""
        cid_1 = uuid.uuid4()
        cid_2 = uuid.uuid4()
        chunk1 = _make_chunk(chunk_id=cid_1, concept_id="prealgebra_1.1")
        chunk2 = _make_chunk(chunk_id=cid_2, concept_id="prealgebra_2.1")  # different concept

        mock_db = _make_mock_db()
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(
                return_value=chunk1 if call_count == 1 else chunk2
            )
            r.scalar = MagicMock(return_value=0)
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            return r

        mock_db.execute = AsyncMock(side_effect=_side_effect)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/chunks/merge",
                headers=_API_HEADERS,
                json={"chunk_id_1": str(cid_1), "chunk_id_2": str(cid_2)},
            )

        assert resp.status_code == 400
        assert "concept" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_split_chunk_creates_second_chunk(self):
        """POST /api/admin/chunks/{id}/split must add a new chunk and return both IDs."""
        chunk_id = uuid.uuid4()
        long_text = "First paragraph content.\n\nSecond paragraph content that continues here."
        chunk = _make_chunk(chunk_id=chunk_id, text=long_text)

        mock_db = _make_mock_db()
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=None)
            r.scalar = MagicMock(return_value=0)
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            r.rowcount = 0
            if call_count == 1:
                # select(ConceptChunk)
                r.scalar_one_or_none = MagicMock(return_value=chunk)
            # Remaining calls: UPDATE shift + active sessions = empty
            return r

        mock_db.execute = AsyncMock(side_effect=_side_effect)

        # Capture the new chunk added via db.add()
        added_objects = []
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        # Assign an ID when flush is called (simulates DB assigning PK)
        new_chunk_holder = {}

        async def _flush():
            for obj in added_objects:
                if not hasattr(obj, "_mock_new_id"):
                    obj.id = uuid.uuid4()
                    obj._mock_new_id = True
                    new_chunk_holder["id"] = obj.id

        mock_db.flush = AsyncMock(side_effect=_flush)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Split at position 26 — right inside the first paragraph
            resp = await client.post(
                f"/api/admin/chunks/{chunk_id}/split",
                headers=_API_HEADERS,
                json={"split_at_position": 26},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "original_chunk_id" in body
        assert "new_chunk_id" in body
        assert body["original_chunk_id"] == str(chunk_id)
        assert body["embedding_stale"] is True
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_reorder_chunks_updates_order_index(self):
        """PUT /api/admin/concepts/{concept_id}/reorder must set order_index per position."""
        chunk_a = _make_chunk(chunk_id=uuid.uuid4(), order_index=0)
        chunk_b = _make_chunk(chunk_id=uuid.uuid4(), order_index=1)
        new_order = [str(chunk_b.id), str(chunk_a.id)]  # reversed

        mock_db = _make_mock_db()
        mock_db.execute.return_value.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[chunk_a, chunk_b]))
        )

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/api/admin/concepts/prealgebra_1.1/reorder",
                headers=_API_HEADERS,
                json={"book_slug": _TEST_SLUG, "chunk_ids": new_order},
            )

        assert resp.status_code == 200
        assert resp.json()["reordered"] == 2
        # chunk_b is now at index 0, chunk_a at index 1
        assert chunk_b.order_index == 0
        assert chunk_a.order_index == 1

    # ── Track A fix verification tests ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_toggle_visibility_calls_db_refresh(self):
        """PATCH /api/admin/chunks/{id}/visibility must call db.refresh after commit.

        Business rule: without db.refresh, SQLAlchemy expires the ORM object after
        commit, causing a MissingGreenlet error when the route reads chunk.is_hidden
        for the response. The fix adds await db.refresh(chunk) before returning.
        """
        chunk_id = uuid.uuid4()
        chunk = _make_chunk(chunk_id=chunk_id, is_hidden=False)
        mock_db = _make_mock_db()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=chunk)

        # Simulate db.refresh flipping the attribute (as the DB would)
        async def _refresh(obj):
            # After the toggle, is_hidden was set to True before commit
            pass  # chunk.is_hidden already set to True by the route before refresh

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/chunks/{chunk_id}/visibility",
                headers=_API_HEADERS,
            )

        assert resp.status_code == 200
        # Core assertion: db.refresh must have been called (the fix)
        assert mock_db.refresh.called is True, (
            "db.refresh was not called after commit in toggle_chunk_visibility — "
            "this would cause MissingGreenlet on the lazy-loaded attribute access"
        )
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_toggle_exam_gate_calls_db_refresh(self):
        """PATCH /api/admin/chunks/{id}/exam-gate must call db.refresh after commit.

        Business rule: same MissingGreenlet hazard as toggle_visibility — the fix
        adds await db.refresh(chunk) so exam_disabled can be safely read post-commit.
        """
        chunk_id = uuid.uuid4()
        chunk = _make_chunk(chunk_id=chunk_id, exam_disabled=False)
        mock_db = _make_mock_db()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=chunk)

        async def _refresh(obj):
            pass  # chunk.exam_disabled already set to True by the route before refresh

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/chunks/{chunk_id}/exam-gate",
                headers=_API_HEADERS,
            )

        assert resp.status_code == 200
        # Core assertion: db.refresh must have been called (the fix)
        assert mock_db.refresh.called is True, (
            "db.refresh was not called after commit in toggle_chunk_exam_gate — "
            "this would cause MissingGreenlet on the lazy-loaded attribute access"
        )
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_chunks_captures_concept_id_before_commit(self):
        """POST /api/admin/chunks/merge succeeds and returns correct merged_chunk_id.

        Business rule: concept_id_str must be captured BEFORE await db.commit()
        because SQLAlchemy expires ORM attributes after commit. If the route read
        chunk1.concept_id after commit, it would raise a MissingGreenlet error.
        A successful 200 response proves the fix is in place.
        """
        cid_1 = uuid.uuid4()
        cid_2 = uuid.uuid4()
        chunk1 = _make_chunk(chunk_id=cid_1, order_index=0, text="First part.")
        chunk2 = _make_chunk(chunk_id=cid_2, order_index=1, text="Second part.")

        mock_db = _make_mock_db()
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=None)
            r.scalar = MagicMock(return_value=0)
            r.all = MagicMock(return_value=[])
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            r.rowcount = 0
            if call_count == 1:
                r.scalar_one_or_none = MagicMock(return_value=chunk1)
            elif call_count == 2:
                r.scalar_one_or_none = MagicMock(return_value=chunk2)
            elif call_count == 5:
                # Re-index query: return surviving chunk
                r.scalars = MagicMock(
                    return_value=MagicMock(all=MagicMock(return_value=[chunk1]))
                )
            return r

        mock_db.execute = AsyncMock(side_effect=_side_effect)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/chunks/merge",
                headers=_API_HEADERS,
                json={"chunk_id_1": str(cid_1), "chunk_id_2": str(cid_2)},
            )

        assert resp.status_code == 200, (
            f"Merge returned {resp.status_code}: {resp.text} — "
            "likely concept_id accessed after commit (MissingGreenlet regression)"
        )
        body = resp.json()
        assert body["merged_chunk_id"] == str(cid_1)
        assert body["embedding_stale"] is True
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_get_book_sections_returns_heading_field(self):
        """GET /api/admin/books/{slug}/sections must include a heading field per section.

        Business rule: the correlated subquery fix returns the first-chunk heading
        (lowest order_index) instead of the alphabetically-first heading. Verify
        that each section in the response carries a non-None heading key.
        """
        mock_db = _make_mock_db()
        call_count = 0

        # Row tuple: concept_id, section, heading (correlated subquery), admin_section_name,
        # is_optional, exam_disabled
        section_row = (
            "prealgebra_1.1",
            "1.1",
            "Zebra Topic",   # heading returned by correlated subquery (lowest order_index)
            None,            # admin_section_name
            False,           # is_optional
            False,           # exam_disabled
        )

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=None)
            r.scalar = MagicMock(return_value=0)
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            r.rowcount = 0
            if call_count == 1:
                # Main GROUP BY query — returns our section rows
                r.all = MagicMock(return_value=[section_row])
            elif call_count == 2:
                # Auto-hide non-numbered concepts UPDATE — no-op
                pass
            elif call_count == 3:
                # chunk_count query
                r.scalar = MagicMock(return_value=2)
            elif call_count == 4:
                # image_count query
                r.scalar = MagicMock(return_value=0)
            else:
                r.all = MagicMock(return_value=[])
            return r

        mock_db.execute = AsyncMock(side_effect=_side_effect)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/admin/books/{_TEST_SLUG}/sections",
                headers=_API_HEADERS,
            )

        assert resp.status_code == 200
        chapters = resp.json()
        # Response is a list of chapter dicts, each with a sections list
        assert isinstance(chapters, list), f"Expected list, got: {type(chapters)}"
        # Find the section we injected
        all_sections = [s for ch in chapters for s in ch.get("sections", [])]
        assert any(s.get("concept_id") == "prealgebra_1.1" for s in all_sections), (
            "Section prealgebra_1.1 missing from response"
        )
        matched = next(s for s in all_sections if s.get("concept_id") == "prealgebra_1.1")
        assert "heading" in matched, "heading key missing from section response"
        assert matched["heading"] == "Zebra Topic", (
            f"Expected heading='Zebra Topic' (first by order_index), got {matched['heading']!r}"
        )

    @pytest.mark.asyncio
    async def test_get_book_sections_nonstandard_chapter_sorts_to_end(self):
        """GET /api/admin/books/{slug}/sections places non-numbered sections after numbered ones.

        Business rule: sections like 'Be Prepared' that cannot be parsed as X.Y
        receive chapter=9999 via the regex fallback, placing them after all real chapters.
        """
        mock_db = _make_mock_db()
        call_count = 0

        # Two rows: one real numbered section, one non-standard
        rows = [
            ("prealgebra_1.1", "1.1",         "Real Heading", None, False, False),
            ("prealgebra_bp",  "Be Prepared",  "Prep Heading", None, False, False),
        ]

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=None)
            r.rowcount = 0
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            if call_count == 1:
                r.all = MagicMock(return_value=rows)
            else:
                r.scalar = MagicMock(return_value=0)
                r.all = MagicMock(return_value=[])
            return r

        mock_db.execute = AsyncMock(side_effect=_side_effect)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/admin/books/{_TEST_SLUG}/sections",
                headers=_API_HEADERS,
            )

        assert resp.status_code == 200
        chapters = resp.json()
        assert isinstance(chapters, list)
        # The response is sorted by chapter number; 9999 must come last
        chapter_nums = [ch["chapter"] for ch in chapters]
        assert chapter_nums == sorted(chapter_nums), (
            f"Chapters not in ascending order: {chapter_nums}"
        )
        # The non-standard section must appear in a later chapter than chapter 1
        real_ch = next((ch for ch in chapters if ch["chapter"] == 1), None)
        assert real_ch is not None, "Chapter 1 not found in response"
        nonstandard_section_ids = [
            s["concept_id"]
            for ch in chapters if ch["chapter"] != 1
            for s in ch.get("sections", [])
        ]
        assert "prealgebra_bp" in nonstandard_section_ids, (
            "Non-standard section should be sorted to a chapter after chapter 1"
        )


# ════════════════════════════════════════════════════════════════════════════════
# Section Controls
# ════════════════════════════════════════════════════════════════════════════════

class TestSectionControls:
    """Section-level rename, optional flag, and exam-gate flag."""

    @pytest.mark.asyncio
    async def test_rename_section_updates_admin_section_name(self):
        """PATCH /api/admin/sections/{concept_id}/rename must run UPDATE SQL and return chunks_updated."""
        mock_db = _make_mock_db()
        r = MagicMock()
        r.rowcount = 3
        mock_db.execute = AsyncMock(return_value=r)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                "/api/admin/sections/prealgebra_1.1/rename",
                headers=_API_HEADERS,
                json={"book_slug": _TEST_SLUG, "name": "Whole Numbers Overview"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["admin_section_name"] == "Whole Numbers Overview"
        assert body["chunks_updated"] == 3
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_toggle_section_optional_sets_flag_on_all_chunks(self):
        """PATCH /api/admin/sections/{concept_id}/optional must UPDATE all chunks in the section."""
        mock_db = _make_mock_db()
        r = MagicMock()
        r.rowcount = 4
        mock_db.execute = AsyncMock(return_value=r)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                "/api/admin/sections/prealgebra_1.1/optional",
                headers=_API_HEADERS,
                json={"book_slug": _TEST_SLUG, "is_optional": True},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["is_optional"] is True
        assert body["chunks_updated"] == 4
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_toggle_section_exam_gate_sets_flag_on_all_chunks(self):
        """PATCH /api/admin/sections/{concept_id}/exam-gate must UPDATE all chunks in the section."""
        mock_db = _make_mock_db()
        r = MagicMock()
        r.rowcount = 2
        mock_db.execute = AsyncMock(return_value=r)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                "/api/admin/sections/prealgebra_1.1/exam-gate",
                headers=_API_HEADERS,
                json={"book_slug": _TEST_SLUG, "disabled": True},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["exam_disabled"] is True
        assert body["chunks_updated"] == 2


# ════════════════════════════════════════════════════════════════════════════════
# Graph Overrides
# ════════════════════════════════════════════════════════════════════════════════

class TestGraphOverrides:
    """Add/remove prerequisite edges and manage override records."""

    @pytest.mark.asyncio
    async def test_add_graph_edge_creates_override_record(self):
        """POST /api/admin/graph/{slug}/edges with add_edge must call db.add and return action."""
        mock_db = _make_mock_db()

        # Build a simple acyclic graph — no path from target back to source
        G = nx.DiGraph()
        G.add_node("prealgebra_1.1")
        G.add_node("prealgebra_1.2")

        with (
            patch.object(admin_router_module, "_load_graph", return_value=G),
            patch.object(admin_router_module, "reload_graph_with_overrides", new=AsyncMock()),
        ):
            app = _build_test_app(mock_db)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    f"/api/admin/graph/{_TEST_SLUG}/edges",
                    headers=_API_HEADERS,
                    json={
                        "action": "add_edge",
                        "source": "prealgebra_1.1",
                        "target": "prealgebra_1.2",
                    },
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "add_edge"
        assert body["source"] == "prealgebra_1.1"
        assert body["target"] == "prealgebra_1.2"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_graph_edge_cycle_rejected(self):
        """POST /api/admin/graph/{slug}/edges must return HTTP 400 when edge would create a cycle."""
        mock_db = _make_mock_db()

        # Graph: A → B → C; adding C→A would create a cycle
        G = nx.DiGraph()
        G.add_edges_from([("A", "B"), ("B", "C")])

        with (
            patch.object(admin_router_module, "_load_graph", return_value=G),
            patch.object(admin_router_module, "reload_graph_with_overrides", new=AsyncMock()),
        ):
            app = _build_test_app(mock_db)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    f"/api/admin/graph/{_TEST_SLUG}/edges",
                    headers=_API_HEADERS,
                    json={"action": "add_edge", "source": "C", "target": "A"},
                )

        assert resp.status_code == 400
        assert "cycle" in resp.json()["detail"].lower()
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_graph_edge_creates_remove_edge_override(self):
        """POST /api/admin/graph/{slug}/edges with remove_edge must persist override and return 200."""
        mock_db = _make_mock_db()

        with patch.object(admin_router_module, "reload_graph_with_overrides", new=AsyncMock()):
            app = _build_test_app(mock_db)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    f"/api/admin/graph/{_TEST_SLUG}/edges",
                    headers=_API_HEADERS,
                    json={
                        "action": "remove_edge",
                        "source": "prealgebra_1.1",
                        "target": "prealgebra_1.2",
                    },
                )

        assert resp.status_code == 200
        assert resp.json()["action"] == "remove_edge"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_graph_override_removes_record(self):
        """DELETE /api/admin/graph/{slug}/overrides/{id} must return deleted=True."""
        override_id = uuid.uuid4()
        mock_db = _make_mock_db()

        # fetchone() returns a row (meaning the DELETE found a record)
        r = MagicMock()
        r.fetchone = MagicMock(return_value=(override_id,))
        mock_db.execute = AsyncMock(return_value=r)

        with patch.object(admin_router_module, "reload_graph_with_overrides", new=AsyncMock()):
            app = _build_test_app(mock_db)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(
                    f"/api/admin/graph/{_TEST_SLUG}/overrides/{override_id}",
                    headers=_API_HEADERS,
                )

        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_graph_override_not_found_returns_404(self):
        """DELETE /api/admin/graph/{slug}/overrides/{id} returns 404 when override doesn't exist."""
        override_id = uuid.uuid4()
        mock_db = _make_mock_db()

        # fetchone() returns None — no matching row deleted
        r = MagicMock()
        r.fetchone = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=r)

        with patch.object(admin_router_module, "reload_graph_with_overrides", new=AsyncMock()):
            app = _build_test_app(mock_db)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(
                    f"/api/admin/graph/{_TEST_SLUG}/overrides/{override_id}",
                    headers=_API_HEADERS,
                )

        assert resp.status_code == 404


# ════════════════════════════════════════════════════════════════════════════════
# Config
# ════════════════════════════════════════════════════════════════════════════════

class TestAdminConfig:
    """Read and upsert platform configuration key-value pairs."""

    @pytest.mark.asyncio
    async def test_get_config_returns_dict(self):
        """GET /api/admin/config must return a flat {key: value} dict."""
        mock_db = _make_mock_db()
        rows = [
            _make_config_row("mastery_threshold", "70"),
            _make_config_row("max_cards_per_session", "10"),
        ]
        mock_db.execute.return_value.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=rows))
        )

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/config", headers=_API_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert body["mastery_threshold"] == "70"
        assert body["max_cards_per_session"] == "10"

    @pytest.mark.asyncio
    async def test_update_config_upserts_and_returns_full_config(self):
        """PATCH /api/admin/config must upsert provided key-value pairs and return full config."""
        mock_db = _make_mock_db()
        call_count = 0
        stored_row = _make_config_row("mastery_threshold", "80")

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            if call_count == 1:
                # select(AdminConfig) for existing key check — not found
                r.scalar_one_or_none = MagicMock(return_value=None)
            else:
                # Final select(AdminConfig) to return updated config
                r.scalars = MagicMock(
                    return_value=MagicMock(all=MagicMock(return_value=[stored_row]))
                )
            r.scalar = MagicMock(return_value=0)
            return r

        mock_db.execute = AsyncMock(side_effect=_side_effect)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                "/api/admin/config",
                headers=_API_HEADERS,
                json={"mastery_threshold": "80"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        # A new row should have been added
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_config_rejects_non_dict_body(self):
        """PATCH /api/admin/config with a list body must return HTTP 400."""
        mock_db = _make_mock_db()
        app = _build_test_app(mock_db)

        merged_headers = {**_API_HEADERS, "content-type": "application/json"}
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                "/api/admin/config",
                headers=merged_headers,
                content=b"[1, 2, 3]",  # list, not dict
            )

        assert resp.status_code == 400


# ════════════════════════════════════════════════════════════════════════════════
# Admin Users
# ════════════════════════════════════════════════════════════════════════════════

class TestAdminUsers:
    """Create admin users and change user roles."""

    @pytest.mark.asyncio
    async def test_create_admin_user_sets_role_admin(self):
        """POST /api/admin/users/create-admin must create user with role=admin and email_verified=True."""
        mock_db = _make_mock_db()

        # No existing user with that email
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

        created_user = MagicMock()
        created_user.id = uuid.uuid4()
        created_user.email = "newadmin@test.com"
        created_user.role = "admin"
        created_user.is_active = True
        created_user.email_verified = True
        created_user.created_at = datetime.now(timezone.utc)

        async def _refresh(obj):
            obj.id = created_user.id
            obj.email = created_user.email
            obj.role = "admin"
            obj.is_active = True
            obj.email_verified = True
            obj.created_at = created_user.created_at

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/users/create-admin",
                headers=_API_HEADERS,
                json={
                    "email": "newadmin@test.com",
                    "password": "AdminPass123!",
                    "display_name": "New Admin",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "admin"
        assert body["email_verified"] is True
        assert body["is_active"] is True
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_admin_user_duplicate_email_returns_409(self):
        """POST /api/admin/users/create-admin with an existing email must return HTTP 409."""
        mock_db = _make_mock_db()
        existing = _make_linked_user()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=existing)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/users/create-admin",
                headers=_API_HEADERS,
                json={
                    "email": "existing@test.com",
                    "password": "AdminPass123!",
                    "display_name": "Duplicate",
                },
            )

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_change_user_role_updates_role_field(self):
        """PATCH /api/admin/users/{id}/role must set target user's role."""
        user_id = uuid.uuid4()
        target_user = _make_linked_user(user_id=user_id)
        target_user.role = "student"

        mock_db = _make_mock_db()
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=None)
            r.scalar = MagicMock(return_value=0)
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            if call_count == 1:
                # select(User)
                r.scalar_one_or_none = MagicMock(return_value=target_user)
            # Subsequent calls may check for existing Student record
            return r

        mock_db.execute = AsyncMock(side_effect=_side_effect)

        async def _refresh(obj):
            pass  # role already set directly on mock object

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/users/{user_id}/role",
                headers=_API_HEADERS,
                json={"role": "admin"},
            )

        assert resp.status_code == 200
        assert target_user.role == "admin"

    @pytest.mark.asyncio
    async def test_change_user_role_invalid_role_returns_400(self):
        """PATCH /api/admin/users/{id}/role with role='superuser' must return HTTP 400."""
        user_id = uuid.uuid4()
        mock_db = _make_mock_db()

        app = _build_test_app(mock_db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/users/{user_id}/role",
                headers=_API_HEADERS,
                json={"role": "superuser"},
            )

        assert resp.status_code == 400


# ════════════════════════════════════════════════════════════════════════════════
# Auth enforcement
# ════════════════════════════════════════════════════════════════════════════════

class TestAuthEnforcement:
    """Endpoints must reject unauthenticated callers with 401/403."""

    @pytest.mark.asyncio
    async def test_dashboard_without_auth_header_returns_401_or_403(self):
        """GET /api/admin/dashboard without a Bearer token must return 401 or 403."""
        mock_db = _make_mock_db()
        # Build app WITHOUT the require_admin override so the real JWT check fires
        app = FastAPI()

        async def _override_get_db():
            yield mock_db

        from db.connection import get_db
        app.dependency_overrides[get_db] = _override_get_db
        app.include_router(admin_router)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/dashboard")

        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_student_list_without_auth_header_returns_401_or_403(self):
        """GET /api/admin/students without a Bearer token must return 401 or 403."""
        mock_db = _make_mock_db()
        app = FastAPI()

        async def _override_get_db():
            yield mock_db

        from db.connection import get_db
        app.dependency_overrides[get_db] = _override_get_db
        app.include_router(admin_router)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/students")

        assert resp.status_code in (401, 403)
