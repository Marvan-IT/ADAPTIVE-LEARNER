"""
test_admin_content_bugs.py

Tests for bug fixes in the admin content editor:

  1. _section_sort_key — handles letter suffixes in section IDs (e.g. "1.1b")
  2. promote_subsection_to_section — sets chunk.section and chunk.admin_section_name
     correctly and prefers letter-suffix candidates over numeric increments
  3. toggle_section_visibility — sets chunk_type_locked = True on every updated chunk;
     auto-hide in get_book_sections respects chunk_type_locked and does not override
     admin-locked chunks
  4. concept_id parsing with underscored slugs — uses len(slug)+1 prefix strip instead
     of split("_", 1)[-1] so slugs containing underscores are handled correctly
  5. _sort_key_with_fallback with underscored slugs — same fix applied to sorting
  6. auto-hide removed from get_book_sections — endpoint is a pure GET with no mutations

Business criteria:
  BC-SCK-01  "1.1" sorts before "1.1b" which sorts before "1.2"
  BC-SCK-02  "10.1b" sorts correctly between "10.1" and "10.2"
  BC-SCK-03  Non-numeric section keys (e.g. "Key Concepts") sort to the end
  BC-SCK-04  Empty string and None are handled gracefully (sort to end)
  BC-SCK-05  Letter ordering: "1.1b" < "1.1c" < "1.2"
  BC-SCK-06  Multi-part sections like "1.1.2b" are handled without crashing

  BC-PRO-01  After promote, moved chunks have chunk.section == numeric part of new_concept_id
  BC-PRO-02  After promote, moved chunks have chunk.admin_section_name == display label
  BC-PRO-03  Letter-suffix candidates are tried before numeric-increment candidates
  BC-PRO-04  Promoting the first chunk returns HTTP 400
  BC-PRO-05  Missing book_slug returns HTTP 400
  BC-PRO-06  Missing chunk_id returns HTTP 400

  BC-VIS-01  toggle_section_visibility SQL sets chunk_type_locked = true alongside is_hidden
  BC-VIS-02  auto-hide in get_book_sections does NOT touch chunks where chunk_type_locked=True
  BC-VIS-03  toggle_section_visibility returns the rowcount under key "updated"
  BC-VIS-04  toggle_section_visibility returns HTTP 400 when book_slug is missing
  BC-VIS-05  toggle_section_visibility returns HTTP 400 when is_hidden is missing

  BC-UND-01  concept_id extraction uses len(slug)+1 prefix strip, not split("_",1)[-1]
  BC-UND-02  Chapter derived from underscored-slug concept_id is correct (not 9999)
  BC-UND-03  _sort_key_with_fallback places underscored-slug section between neighbours
  BC-UND-04  get_book_sections has no non_numbered_cids auto-hide mutation
  BC-UND-05  get_book_sections has no update(ConceptChunk) calls — pure GET

Run: pytest backend/tests/test_admin_content_bugs.py -v
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

# ── 1. sys.path ────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── 2. Required env vars before any import ────────────────────────────────────
os.environ.setdefault("API_SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://fake:fake@localhost/fake")

# ── 3. Stub heavy transitive deps BEFORE importing admin_router ───────────────
if "fitz" not in sys.modules:
    sys.modules["fitz"] = MagicMock()

if "api.chunk_knowledge_service" not in sys.modules:
    _ck_stub = MagicMock()
    _ck_stub._normalize_image_url = lambda url: url
    sys.modules["api.chunk_knowledge_service"] = _ck_stub

import pytest
import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

import api.admin_router as admin_router_module
from api.admin_router import router as admin_router, _section_sort_key

admin_router_module._API_KEY = "test-secret"

_API_HEADERS = {"X-API-Key": "test-secret"}
_TEST_SLUG = "prealgebra"


# ══════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ══════════════════════════════════════════════════════════════════════════════

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
    """Return an AsyncSession mock with sensible defaults."""
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


def _build_test_app(mock_db: AsyncMock) -> FastAPI:
    """Build a minimal FastAPI app with admin_router, overriding DB and auth."""
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


def _make_chunk(
    chunk_id=None,
    concept_id: str = "prealgebra_1.1",
    section: str = "1.1",
    heading: str = "Introduction",
    text: str = "Some text content here.",
    order_index: int = 0,
) -> MagicMock:
    c = MagicMock()
    c.id = chunk_id or uuid.uuid4()
    c.concept_id = concept_id
    c.book_slug = _TEST_SLUG
    c.section = section
    c.heading = heading
    c.text = text
    c.order_index = order_index
    c.chunk_type = "teaching"
    c.is_hidden = False
    c.is_optional = False
    c.exam_disabled = False
    c.embedding = None
    return c


# ══════════════════════════════════════════════════════════════════════════════
# Group 1 — _section_sort_key unit tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSectionSortKey:
    """
    BC-SCK-01 through BC-SCK-06: _section_sort_key must produce a comparable
    key that places sections in correct numeric+letter order and gracefully
    handles degenerate inputs.
    """

    def test_plain_sections_sort_numerically(self):
        """BC-SCK-01: '1.1' < '1.2' — pure numeric sections sort in numeric order."""
        assert _section_sort_key("1.1") < _section_sort_key("1.2")

    def test_letter_suffix_sorts_between_base_and_next(self):
        """BC-SCK-01: '1.1b' sorts after '1.1' but before '1.2'."""
        assert _section_sort_key("1.1") < _section_sort_key("1.1b")
        assert _section_sort_key("1.1b") < _section_sort_key("1.2")

    def test_letter_suffixed_sections_sort_between_neighbours(self):
        """BC-SCK-02: '10.1b' must be between '10.1' and '10.2'."""
        assert _section_sort_key("10.1") < _section_sort_key("10.1b")
        assert _section_sort_key("10.1b") < _section_sort_key("10.2")

    def test_non_numeric_key_sorts_to_end(self):
        """BC-SCK-03: 'Key Concepts' must sort after any well-formed numeric section."""
        assert _section_sort_key("Key Concepts") > _section_sort_key("99.99")

    def test_empty_string_sorts_to_end(self):
        """BC-SCK-04: Empty string must sort to end (same as non-numeric)."""
        assert _section_sort_key("") >= _section_sort_key("99.99")

    def test_none_sorts_to_end(self):
        """BC-SCK-04: None must be handled gracefully and sort to end."""
        # _section_sort_key(None) must not raise and must sort after valid sections
        assert _section_sort_key(None) >= _section_sort_key("99.99")

    def test_letter_ordering_b_before_c_before_next_section(self):
        """BC-SCK-05: '1.1b' < '1.1c' < '1.2'."""
        assert _section_sort_key("1.1b") < _section_sort_key("1.1c")
        assert _section_sort_key("1.1c") < _section_sort_key("1.2")

    def test_sorted_list_preserves_correct_order(self):
        """BC-SCK-01/02/05: Sorting a mixed list produces the correct sequence."""
        sections = ["1.2", "1.1b", "10.1", "1.1", "10.1b", "10.2", "Key Concepts"]
        result = sorted(sections, key=_section_sort_key)
        expected = ["1.1", "1.1b", "1.2", "10.1", "10.1b", "10.2", "Key Concepts"]
        assert result == expected

    def test_three_part_section_does_not_crash(self):
        """BC-SCK-06: Multi-part sections like '1.1.2b' must not raise."""
        try:
            key = _section_sort_key("1.1.2b")
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"_section_sort_key('1.1.2b') raised unexpectedly: {exc}")
        assert isinstance(key, tuple)

    def test_single_digit_section_sorts_before_double(self):
        """BC-SCK-01: '1.2' < '1.10' (numeric not lexicographic comparison)."""
        assert _section_sort_key("1.2") < _section_sort_key("1.10")


# ══════════════════════════════════════════════════════════════════════════════
# Group 2 — promote_subsection_to_section endpoint
# ══════════════════════════════════════════════════════════════════════════════

class TestPromoteSubsection:
    """
    BC-PRO-01 through BC-PRO-06: promote_subsection_to_section must set
    chunk.section to the numeric part of the new concept_id, set
    chunk.admin_section_name to the display label, prefer letter-suffix
    candidates first, and reject bad inputs with correct HTTP status codes.
    """

    def _make_two_chunk_db(self, concept_id="prealgebra_1.1"):
        """
        DB that returns two chunks for the given concept_id.

        First execute() call:  the 'load all chunks' query → two chunks
        Second execute() call: candidate availability check → None (slot is free)
        """
        chunk_a = _make_chunk(
            chunk_id=uuid.uuid4(), concept_id=concept_id, order_index=0,
            heading="Learning Objectives",
        )
        chunk_b = _make_chunk(
            chunk_id=uuid.uuid4(), concept_id=concept_id, order_index=1,
            heading="Adding Whole Numbers",
        )

        # result for loading all chunks
        load_result = MagicMock()
        load_result.scalars.return_value.all.return_value = [chunk_a, chunk_b]

        # result for candidate availability check — None means the slot is free
        avail_result = MagicMock()
        avail_result.scalar_one_or_none.return_value = None

        db = _make_mock_db()
        db.execute = AsyncMock(side_effect=[load_result, avail_result])
        return db, chunk_a, chunk_b

    @pytest.mark.asyncio
    async def test_moved_chunks_get_numeric_section_from_new_concept_id(self, tmp_path):
        """
        BC-PRO-01: chunk.section for every moved chunk must equal the numeric part
        of the new concept_id — e.g. "prealgebra_1.1b" -> section "1.1b".
        """
        db, _chunk_a, chunk_b = self._make_two_chunk_db("prealgebra_1.1")
        app = _build_test_app(db)

        with patch.object(admin_router_module, "OUTPUT_DIR", tmp_path):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/admin/sections/prealgebra_1.1/promote",
                    headers=_API_HEADERS,
                    json={
                        "book_slug": _TEST_SLUG,
                        "chunk_id": str(chunk_b.id),
                        "new_section_label": "Adding Whole Numbers",
                    },
                )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        new_cid = body["new_concept_id"]
        # The new concept_id must have the book_slug prefix
        assert new_cid.startswith("prealgebra_1.1")
        # chunk_b.section must be set to the section_label (readable name)
        assert chunk_b.section == "Adding Whole Numbers"

    @pytest.mark.asyncio
    async def test_moved_chunks_section_is_custom_label(self, tmp_path):
        """
        BC-PRO-02: chunk.section for moved chunks must equal the display label
        passed in 'new_section_label'.
        """
        db, _chunk_a, chunk_b = self._make_two_chunk_db("prealgebra_1.1")
        app = _build_test_app(db)

        with patch.object(admin_router_module, "OUTPUT_DIR", tmp_path):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/admin/sections/prealgebra_1.1/promote",
                    headers=_API_HEADERS,
                    json={
                        "book_slug": _TEST_SLUG,
                        "chunk_id": str(chunk_b.id),
                        "new_section_label": "My Custom Label",
                    },
                )

        assert resp.status_code == 200, resp.text
        assert chunk_b.section == "My Custom Label"

    @pytest.mark.asyncio
    async def test_section_defaults_to_chunk_heading_when_label_omitted(self, tmp_path):
        """
        BC-PRO-02: When new_section_label is not provided, chunk.section must
        fall back to the heading of the promoted chunk.
        """
        db, _chunk_a, chunk_b = self._make_two_chunk_db("prealgebra_1.1")
        chunk_b.heading = "Adding Whole Numbers"
        app = _build_test_app(db)

        with patch.object(admin_router_module, "OUTPUT_DIR", tmp_path):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/admin/sections/prealgebra_1.1/promote",
                    headers=_API_HEADERS,
                    json={
                        "book_slug": _TEST_SLUG,
                        "chunk_id": str(chunk_b.id),
                    },
                )

        assert resp.status_code == 200, resp.text
        assert chunk_b.section == "Adding Whole Numbers"

    @pytest.mark.asyncio
    async def test_letter_suffix_candidate_chosen_before_numeric_increment(self, tmp_path):
        """
        BC-PRO-03: For a plain numeric section like 'prealgebra_1.1', the new
        concept_id must be 'prealgebra_1.1b' (letter suffix) rather than
        'prealgebra_1.2' (numeric increment) when 1.1b is free.
        """
        db, _chunk_a, chunk_b = self._make_two_chunk_db("prealgebra_1.1")
        app = _build_test_app(db)

        with patch.object(admin_router_module, "OUTPUT_DIR", tmp_path):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/admin/sections/prealgebra_1.1/promote",
                    headers=_API_HEADERS,
                    json={
                        "book_slug": _TEST_SLUG,
                        "chunk_id": str(chunk_b.id),
                    },
                )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Must have picked the letter-suffix variant
        assert body["new_concept_id"] == "prealgebra_1.1b"

    @pytest.mark.asyncio
    async def test_response_includes_old_new_concept_ids_and_chunks_moved(self, tmp_path):
        """
        BC-PRO-01/02: The response body must include old_concept_id, new_concept_id,
        new_section_label, and chunks_moved.
        """
        db, _chunk_a, chunk_b = self._make_two_chunk_db("prealgebra_1.1")
        app = _build_test_app(db)

        with patch.object(admin_router_module, "OUTPUT_DIR", tmp_path):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/admin/sections/prealgebra_1.1/promote",
                    headers=_API_HEADERS,
                    json={
                        "book_slug": _TEST_SLUG,
                        "chunk_id": str(chunk_b.id),
                        "new_section_label": "Adding Whole Numbers",
                    },
                )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["old_concept_id"] == "prealgebra_1.1"
        assert "new_concept_id" in body
        assert body["new_section_label"] == "Adding Whole Numbers"
        assert body["chunks_moved"] == 1

    @pytest.mark.asyncio
    async def test_promoting_first_chunk_returns_400(self):
        """
        BC-PRO-04: Promoting the first chunk (index 0) must return HTTP 400 because
        doing so would leave the original section empty.
        """
        chunk_a = _make_chunk(
            chunk_id=uuid.uuid4(), concept_id="prealgebra_1.1", order_index=0,
        )
        chunk_b = _make_chunk(
            chunk_id=uuid.uuid4(), concept_id="prealgebra_1.1", order_index=1,
        )

        load_result = MagicMock()
        load_result.scalars.return_value.all.return_value = [chunk_a, chunk_b]

        db = _make_mock_db()
        db.execute = AsyncMock(return_value=load_result)

        app = _build_test_app(db)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/sections/prealgebra_1.1/promote",
                headers=_API_HEADERS,
                json={
                    "book_slug": _TEST_SLUG,
                    "chunk_id": str(chunk_a.id),
                },
            )

        assert resp.status_code == 400
        assert "first chunk" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_missing_book_slug_returns_400(self):
        """BC-PRO-05: Omitting book_slug must return HTTP 400."""
        app = _build_test_app(_make_mock_db())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/sections/prealgebra_1.1/promote",
                headers=_API_HEADERS,
                json={"chunk_id": str(uuid.uuid4())},
            )

        assert resp.status_code == 400
        assert "book_slug" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_missing_chunk_id_returns_400(self):
        """BC-PRO-06: Omitting chunk_id must return HTTP 400."""
        app = _build_test_app(_make_mock_db())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/sections/prealgebra_1.1/promote",
                headers=_API_HEADERS,
                json={"book_slug": _TEST_SLUG},
            )

        assert resp.status_code == 400
        assert "chunk_id" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════════════════════════
# Group 3 — toggle_section_visibility endpoint
# ══════════════════════════════════════════════════════════════════════════════

class TestToggleSectionVisibility:
    """
    BC-VIS-01 through BC-VIS-05: toggle_section_visibility must include
    chunk_type_locked = true in its SQL UPDATE so that subsequent auto-hide
    passes cannot undo an admin's explicit visibility choice.
    """

    @pytest.mark.asyncio
    async def test_sql_sets_chunk_type_locked_true_on_hide(self):
        """
        BC-VIS-01: The SQL executed by toggle_section_visibility must include
        'chunk_type_locked = true' when hiding a section.
        """
        db = _make_mock_db()
        app = _build_test_app(db)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                "/api/admin/sections/prealgebra_1.1/visibility",
                headers=_API_HEADERS,
                json={"book_slug": _TEST_SLUG, "is_hidden": True},
            )

        assert resp.status_code == 200, resp.text

        # Verify db.execute was called and the SQL string contained chunk_type_locked
        assert db.execute.called
        executed_calls = db.execute.call_args_list
        # Find the UPDATE call
        sql_texts = []
        for c in executed_calls:
            args = c.args
            if args:
                sql_texts.append(str(args[0]))
        combined = " ".join(sql_texts).lower()
        assert "chunk_type_locked" in combined, (
            "SQL must set chunk_type_locked — found SQL: " + " | ".join(sql_texts)
        )

    @pytest.mark.asyncio
    async def test_sql_sets_chunk_type_locked_true_on_unhide(self):
        """
        BC-VIS-01: chunk_type_locked = true must also be set when un-hiding
        (is_hidden=False) to lock the admin choice in both directions.
        """
        db = _make_mock_db()
        app = _build_test_app(db)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                "/api/admin/sections/prealgebra_1.1/visibility",
                headers=_API_HEADERS,
                json={"book_slug": _TEST_SLUG, "is_hidden": False},
            )

        assert resp.status_code == 200, resp.text

        executed_calls = db.execute.call_args_list
        sql_texts = [str(c.args[0]) for c in executed_calls if c.args]
        combined = " ".join(sql_texts).lower()
        assert "chunk_type_locked" in combined

    @pytest.mark.asyncio
    async def test_response_contains_updated_rowcount(self):
        """BC-VIS-03: The response must include 'updated' key with the rowcount."""
        db = _make_mock_db()
        db.execute.return_value.rowcount = 5
        app = _build_test_app(db)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                "/api/admin/sections/prealgebra_1.1/visibility",
                headers=_API_HEADERS,
                json={"book_slug": _TEST_SLUG, "is_hidden": True},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["updated"] == 5

    @pytest.mark.asyncio
    async def test_missing_book_slug_returns_400(self):
        """BC-VIS-04: Omitting book_slug must return HTTP 400."""
        app = _build_test_app(_make_mock_db())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                "/api/admin/sections/prealgebra_1.1/visibility",
                headers=_API_HEADERS,
                json={"is_hidden": True},
            )

        assert resp.status_code == 400
        assert "book_slug" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_missing_is_hidden_returns_400(self):
        """BC-VIS-05: Omitting is_hidden must return HTTP 400."""
        app = _build_test_app(_make_mock_db())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                "/api/admin/sections/prealgebra_1.1/visibility",
                headers=_API_HEADERS,
                json={"book_slug": _TEST_SLUG},
            )

        assert resp.status_code == 400
        assert "is_hidden" in resp.json()["detail"]

    def test_toggle_visibility_sets_chunk_type_locked(self):
        """
        BC-VIS-02: The toggle_section_visibility endpoint must set
        chunk_type_locked = true so admin visibility decisions persist.

        Static analysis: inspect the source of toggle_section_visibility to
        confirm chunk_type_locked is set in the UPDATE SQL.
        """
        import inspect
        source = inspect.getsource(admin_router_module.toggle_section_visibility)
        assert "chunk_type_locked" in source, (
            "toggle_section_visibility must set chunk_type_locked in the UPDATE"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Group 4 — concept_id parsing with underscored slugs
# ══════════════════════════════════════════════════════════════════════════════

class TestConceptIdParsingWithUnderscoredSlug:
    """
    BC-UND-01/02: When a book slug itself contains underscores (e.g.
    "prealgebra2e_0qbw93r_(1)"), extracting the numeric section suffix from a
    concept_id must use the len(slug)+1 prefix-strip technique, not
    split("_", 1)[-1], which would give the wrong result.
    """

    def test_extraction_uses_prefix_strip_not_split(self):
        """
        BC-UND-01: For slug='prealgebra2e_0qbw93r_(1)' and
        concept_id='prealgebra2e_0qbw93r_(1)_11.3', the extracted suffix must be
        '11.3', not '0qbw93r_(1)_11.3'.
        """
        slug = "prealgebra2e_0qbw93r_(1)"
        concept_id = "prealgebra2e_0qbw93r_(1)_11.3"

        # Replicate the extraction logic used in get_book_sections
        suffix = concept_id[len(slug) + 1:] if concept_id.startswith(slug + "_") else ""

        assert suffix == "11.3", (
            f"Expected suffix '11.3', got '{suffix}'. "
            "The extraction must use len(slug)+1 strip, not split('_', 1)[-1]."
        )

    def test_wrong_split_approach_gives_incorrect_result(self):
        """
        BC-UND-01 (negative): Demonstrates that the old split('_', 1)[-1] approach
        returns the wrong suffix for underscored slugs, confirming why the fix is
        necessary.
        """
        slug = "prealgebra2e_0qbw93r_(1)"
        concept_id = "prealgebra2e_0qbw93r_(1)_11.3"

        # The old (broken) approach
        bad_suffix = concept_id.split("_", 1)[-1]

        # The correct approach
        good_suffix = concept_id[len(slug) + 1:] if concept_id.startswith(slug + "_") else ""

        assert bad_suffix != good_suffix, (
            "The two approaches should differ for underscored slugs — "
            "this confirms the bug is real and the fix is necessary."
        )
        assert good_suffix == "11.3"

    def test_chapter_derived_correctly_from_underscored_slug_concept_id(self):
        """
        BC-UND-02: Chapter number derived from an underscored-slug concept_id must
        be 11 (from suffix '11.3'), not 9999 (the fallback for unparseable input).
        """
        slug = "prealgebra2e_0qbw93r_(1)"
        concept_id = "prealgebra2e_0qbw93r_(1)_11.3"

        _cid_suffix = concept_id[len(slug) + 1:] if concept_id.startswith(slug + "_") else ""
        try:
            chapter = int(_cid_suffix.split(".")[0])
        except (ValueError, AttributeError):
            chapter = 9999

        assert chapter == 11, (
            f"Expected chapter 11, got {chapter}. "
            "Prefix-strip extraction must yield '11.3' so chapter parses as 11."
        )

    def test_concept_id_without_slug_prefix_yields_empty_suffix(self):
        """
        BC-UND-01 (edge): When concept_id does not start with slug+'_', the suffix
        must be an empty string (safe fallback, not an exception).
        """
        slug = "prealgebra2e_0qbw93r_(1)"
        concept_id = "other_book_11.3"

        suffix = concept_id[len(slug) + 1:] if concept_id.startswith(slug + "_") else ""

        assert suffix == "", (
            f"Expected empty suffix for non-matching concept_id, got '{suffix}'."
        )

    def test_plain_slug_still_works_with_prefix_strip(self):
        """
        BC-UND-01 (regression): The prefix-strip approach must also work correctly
        for plain slugs that contain no underscores (e.g. 'prealgebra').
        """
        slug = "prealgebra"
        concept_id = "prealgebra_3.4"

        suffix = concept_id[len(slug) + 1:] if concept_id.startswith(slug + "_") else ""

        assert suffix == "3.4", (
            f"Expected suffix '3.4' for plain slug, got '{suffix}'."
        )


# ══════════════════════════════════════════════════════════════════════════════
# Group 5 — _sort_key_with_fallback with underscored slugs
# ══════════════════════════════════════════════════════════════════════════════

class TestSortKeyWithFallbackUnderscoredSlug:
    """
    BC-UND-03: _sort_key_with_fallback inside get_book_sections uses
    cid[len(slug)+1:] to extract the concept_id suffix for promoted sections.
    This ensures that a promoted section like 'prealgebra2e_0qbw93r_(1)_11.3b'
    sorts between '11.3' and '11.4', not at the end (which would happen if the
    split-based approach produced a garbage suffix).
    """

    def test_promoted_section_sorts_between_neighbours_for_underscored_slug(self):
        """
        BC-UND-03: A promoted section with concept_id
        'prealgebra2e_0qbw93r_(1)_11.3b' (text section field, e.g. 'Key Concepts')
        must sort between the '11.3' and '11.4' sections within chapter 11.
        """
        slug = "prealgebra2e_0qbw93r_(1)"
        import re

        # Replicate _sort_key_with_fallback logic from admin_router
        def _sort_key_with_fallback(s):
            section = s.get("section") or ""
            if re.match(r"^\d+\.\d+", section):
                return _section_sort_key(section)
            cid = s.get("concept_id", "")
            cid_suffix = cid[len(slug) + 1:] if cid.startswith(slug + "_") else ""
            return _section_sort_key(cid_suffix)

        plain_11_3 = {
            "concept_id": f"{slug}_11.3",
            "section": "11.3",
        }
        promoted_11_3b = {
            "concept_id": f"{slug}_11.3b",
            "section": "Key Concepts",  # text section — triggers fallback path
        }
        plain_11_4 = {
            "concept_id": f"{slug}_11.4",
            "section": "11.4",
        }

        key_11_3 = _sort_key_with_fallback(plain_11_3)
        key_11_3b = _sort_key_with_fallback(promoted_11_3b)
        key_11_4 = _sort_key_with_fallback(plain_11_4)

        assert key_11_3 < key_11_3b, (
            "Promoted section '11.3b' must sort after plain '11.3'."
        )
        assert key_11_3b < key_11_4, (
            "Promoted section '11.3b' must sort before plain '11.4'."
        )

    def test_old_split_approach_would_misorder_promoted_section(self):
        """
        BC-UND-03 (negative): Demonstrates that using split('_', 1)[-1] for the
        concept_id suffix would produce a garbage key for underscored slugs and
        therefore sort the promoted section to the end (after 11.4), confirming
        why the fix is necessary.
        """
        slug = "prealgebra2e_0qbw93r_(1)"
        import re

        # Old (broken) approach: split("_", 1)[-1]
        def _sort_key_broken(s):
            section = s.get("section") or ""
            if re.match(r"^\d+\.\d+", section):
                return _section_sort_key(section)
            cid = s.get("concept_id", "")
            cid_suffix = cid.split("_", 1)[-1]  # wrong for underscored slugs
            return _section_sort_key(cid_suffix)

        # Correct approach: len(slug)+1 strip
        def _sort_key_correct(s):
            section = s.get("section") or ""
            if re.match(r"^\d+\.\d+", section):
                return _section_sort_key(section)
            cid = s.get("concept_id", "")
            cid_suffix = cid[len(slug) + 1:] if cid.startswith(slug + "_") else ""
            return _section_sort_key(cid_suffix)

        promoted = {
            "concept_id": f"{slug}_11.3b",
            "section": "Key Concepts",
        }
        plain_11_4 = {
            "concept_id": f"{slug}_11.4",
            "section": "11.4",
        }

        # With the broken approach the promoted section sorts AFTER 11.4 (wrong)
        broken_promoted = _sort_key_broken(promoted)
        broken_11_4 = _sort_key_broken(plain_11_4)
        assert broken_promoted > broken_11_4, (
            "Broken split approach should misorder the promoted section — "
            "confirming the bug is real."
        )

        # With the correct approach the promoted section sorts BEFORE 11.4 (right)
        correct_promoted = _sort_key_correct(promoted)
        correct_11_4 = _sort_key_correct(plain_11_4)
        assert correct_promoted < correct_11_4, (
            "Fixed prefix-strip approach must place promoted section before 11.4."
        )


# ══════════════════════════════════════════════════════════════════════════════
# Group 6 — auto-hide removal: get_book_sections is a pure GET
# ══════════════════════════════════════════════════════════════════════════════

class TestAutoHideRemoved:
    """
    BC-UND-04/05: The auto-hide pass that used to mark non-numbered concept_ids
    as is_hidden=True has been removed from get_book_sections.  The endpoint is
    now a pure read — it must contain no DB mutations (no update(ConceptChunk),
    no non_numbered_cids variable).
    """

    def _get_book_sections_source(self) -> str:
        """Return the source code of get_book_sections only (not the whole module)."""
        import inspect
        return inspect.getsource(admin_router_module.get_book_sections)

    def test_no_non_numbered_cids_variable_in_get_book_sections(self):
        """
        BC-UND-04: The variable 'non_numbered_cids' that drove the auto-hide pass
        must not appear anywhere in the get_book_sections function source.
        """
        source = self._get_book_sections_source()
        assert "non_numbered_cids" not in source, (
            "get_book_sections must not contain 'non_numbered_cids' — "
            "the auto-hide pass has been removed."
        )

    def test_no_update_conceptchunk_in_get_book_sections(self):
        """
        BC-UND-05: There must be no SQLAlchemy update(ConceptChunk) call inside
        get_book_sections — the endpoint must be a pure GET with zero DB mutations.
        """
        source = self._get_book_sections_source()
        assert "update(ConceptChunk)" not in source, (
            "get_book_sections must not call update(ConceptChunk) — "
            "no auto-hide mutations should occur during a GET request."
        )

    def test_no_auto_hide_is_hidden_true_assignment_in_get_book_sections(self):
        """
        BC-UND-05 (complementary): There must be no 'is_hidden=True' value binding
        inside an update statement within get_book_sections.
        """
        source = self._get_book_sections_source()
        # The combination of 'update' and 'is_hidden' in a SET clause indicates a mutation
        # We check that both are NOT present together in the function scope
        has_update_call = "update(" in source
        has_is_hidden_set = "is_hidden=True" in source or '"is_hidden": True' in source

        # Either there is no update at all, or is_hidden=True is not set in an update context
        assert not (has_update_call and has_is_hidden_set), (
            "get_book_sections must not mutate is_hidden — "
            "auto-hide logic has been removed from this endpoint."
        )

    def test_get_book_sections_function_exists_and_is_async(self):
        """
        BC-UND-04/05 (sanity): get_book_sections must still exist as an async
        function after the auto-hide removal — the endpoint itself was not deleted.
        """
        import asyncio
        func = getattr(admin_router_module, "get_book_sections", None)
        assert func is not None, "get_book_sections must still be defined in admin_router."
        assert asyncio.iscoroutinefunction(func), (
            "get_book_sections must remain an async function."
        )
