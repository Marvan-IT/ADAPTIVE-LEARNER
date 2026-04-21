"""
test_stage2_admin_actions.py
Admin write-operation tests with full cleanup/reversal.

Tests all admin mutation endpoints and cross-verifies effects with student
endpoints where applicable.

Run with:
    PYTHONIOENCODING=utf-8 python backend/tests/test_stage2_admin_actions.py
or:
    cd backend && python tests/test_stage2_admin_actions.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE = "http://localhost:8889"
API_KEY = os.environ.get(
    "ADA_API_KEY",
    "e36e77ba81581c1b6c1a00c44112db727fc1d00a8b073c5ea54be454ae778c22",
)
ADMIN_EMAIL = "muhammed.marvan@hightekers.com"
ADMIN_PASSWORD = "Admin@1234"
STUDENT_EMAIL = "manujaleel007@gmail.com"
STUDENT_PASSWORD = "Marvan@1234"
BOOK_SLUG = "business_statistics"
CONCEPT_1_1 = "business_statistics_1.1"
CONCEPT_1_2 = "business_statistics_1.2"
PREREQ_SOURCE = "business_statistics_1.0"
PREREQ_TARGET = "business_statistics_1.4"

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------
PASS_COUNT = 0
FAIL_COUNT = 0
TEST_NUM = 0


def _result(passed: bool, label: str, detail: str = "") -> None:
    global PASS_COUNT, FAIL_COUNT, TEST_NUM
    TEST_NUM += 1
    tag = "[PASS]" if passed else "[FAIL]"
    suffix = f" -- {detail}" if detail else ""
    print(f"  {tag} #{TEST_NUM:02d} {label}{suffix}")
    if passed:
        PASS_COUNT += 1
    else:
        FAIL_COUNT += 1


def check(
    r: "httpx.Response | None",
    label: str,
    expected: "int | tuple[int, ...]" = 200,
    detail: str = "",
) -> bool:
    if r is None:
        _result(False, label, detail or "connection error")
        return False
    expected_set = (expected,) if isinstance(expected, int) else expected
    passed = r.status_code in expected_set
    extra = detail or (f"HTTP {r.status_code}" if not passed else "")
    _result(passed, label, extra)
    return passed


async def req(
    c: httpx.AsyncClient,
    method: str,
    url: str,
    label: str,
    expected: "int | tuple[int, ...]" = 200,
    detail: str = "",
    _retry: bool = True,
    **kwargs,
) -> "httpx.Response | None":
    """Send HTTP request, record PASS/FAIL, never raise."""
    try:
        r = await c.request(method, url, **kwargs)
        check(r, label, expected=expected, detail=detail)
        return r
    except httpx.ReadError:
        if _retry:
            await asyncio.sleep(1.5)
            return await req(
                c, method, url, label, expected=expected,
                detail=detail, _retry=False, **kwargs,
            )
        _result(False, label, detail="ReadError (server dropped connection)")
        return None
    except Exception as exc:
        _result(False, label, detail=f"{type(exc).__name__}: {str(exc)[:80]}")
        return None


def _skip(label: str, reason: str = "dependency failed") -> None:
    _result(False, label, detail=f"SKIPPED -- {reason}")


# ---------------------------------------------------------------------------
# Login helpers
# ---------------------------------------------------------------------------
async def _login_admin(c: httpx.AsyncClient) -> "str | None":
    r = await c.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    if r.status_code == 200:
        return r.json()["access_token"]
    return None


async def _login_student(c: httpx.AsyncClient) -> "dict | None":
    r = await c.post(
        "/api/v1/auth/login",
        json={"email": STUDENT_EMAIL, "password": STUDENT_PASSWORD},
    )
    if r.status_code == 200:
        data = r.json()
        return {
            "token": data["access_token"],
            "student_id": data["user"]["student_id"],
            "display_name": data["user"].get("display_name", ""),
        }
    return None


# ===========================================================================
# A1: Subject CRUD
# ===========================================================================
async def test_a1_subject_crud(
    c: httpx.AsyncClient, admin_h: dict
) -> None:
    print("\n=== A1: Subject CRUD ===")
    subject_slug: "str | None" = None

    try:
        # Create subject
        r = await req(
            c, "POST", "/api/admin/subjects",
            "A1.1 POST /api/admin/subjects (create)",
            expected=200,
            json={"label": "Test Subject"},
            headers=admin_h,
        )
        if r and r.status_code == 200:
            subject_slug = r.json().get("slug")
            print(f"         slug={subject_slug}")
        else:
            _skip("A1.2 PUT rename subject", "create failed")
            _skip("A1.3 PATCH subject visibility", "create failed")
            return

        # Rename subject
        r2 = await req(
            c, "PUT", f"/api/admin/subjects/{subject_slug}",
            "A1.2 PUT /api/admin/subjects/{slug} (rename)",
            expected=200,
            json={"label": "Renamed Subject"},
            headers=admin_h,
        )
        if r2 and r2.status_code == 200:
            assert r2.json().get("label") == "Renamed Subject", "label mismatch"

        # Hide subject
        await req(
            c, "PATCH", f"/api/admin/subjects/{subject_slug}/visibility",
            "A1.3 PATCH /api/admin/subjects/{slug}/visibility (hide)",
            expected=200,
            json={"is_hidden": True},
            headers=admin_h,
        )

    finally:
        # Always clean up: delete the subject
        if subject_slug:
            await req(
                c, "DELETE", f"/api/admin/subjects/{subject_slug}",
                "A1.4 DELETE /api/admin/subjects/{slug} (cleanup)",
                expected=(204, 404),
                headers=admin_h,
            )


# ===========================================================================
# A2: Book Visibility
# ===========================================================================
async def test_a2_book_visibility(
    c: httpx.AsyncClient, admin_h: dict
) -> None:
    print("\n=== A2: Book Visibility ===")

    try:
        # Hide book
        await req(
            c, "PATCH", f"/api/admin/books/{BOOK_SLUG}/visibility",
            f"A2.1 PATCH /api/admin/books/{BOOK_SLUG}/visibility (hide)",
            expected=200,
            json={"is_hidden": True},
            headers=admin_h,
        )

        # Student should NOT see this book
        r = await c.get("/api/v1/books", headers={"X-API-Key": API_KEY})
        if r.status_code == 200:
            slugs = [b["slug"] for b in r.json()]
            hidden_ok = BOOK_SLUG not in slugs
            _result(
                hidden_ok,
                f"A2.2 GET /api/v1/books -> {BOOK_SLUG} NOT visible",
                "" if hidden_ok else f"book still visible in list: {slugs[:5]}",
            )
        else:
            _skip("A2.2 GET /api/v1/books student verify", f"HTTP {r.status_code}")

    finally:
        # Unhide book (always reverse)
        await req(
            c, "PATCH", f"/api/admin/books/{BOOK_SLUG}/visibility",
            f"A2.3 PATCH /api/admin/books/{BOOK_SLUG}/visibility (unhide/reverse)",
            expected=200,
            json={"is_hidden": False},
            headers=admin_h,
        )


# ===========================================================================
# A3: Student Disable/Enable
# ===========================================================================
async def test_a3_student_access(
    c: httpx.AsyncClient, admin_h: dict, student_id: str
) -> None:
    print("\n=== A3: Student Disable/Enable ===")

    try:
        # Disable student
        await req(
            c, "PATCH", f"/api/admin/students/{student_id}/access",
            "A3.1 PATCH /api/admin/students/{sid}/access (disable)",
            expected=200,
            json={"is_active": False},
            headers=admin_h,
        )

        # Student login should fail
        r = await c.post(
            "/api/v1/auth/login",
            json={"email": STUDENT_EMAIL, "password": STUDENT_PASSWORD},
        )
        login_blocked = r.status_code in (401, 403)
        _result(
            login_blocked,
            "A3.2 POST /api/v1/auth/login (student) -> should fail while disabled",
            "" if login_blocked else f"unexpected HTTP {r.status_code}",
        )

    finally:
        # Always re-enable so subsequent tests can still login as student
        await req(
            c, "PATCH", f"/api/admin/students/{student_id}/access",
            "A3.3 PATCH /api/admin/students/{sid}/access (re-enable/reverse)",
            expected=200,
            json={"is_active": True},
            headers=admin_h,
        )

        # Student login should succeed again
        r2 = await c.post(
            "/api/v1/auth/login",
            json={"email": STUDENT_EMAIL, "password": STUDENT_PASSWORD},
        )
        _result(
            r2.status_code == 200,
            "A3.4 POST /api/v1/auth/login (student) -> should succeed after re-enable",
            "" if r2.status_code == 200 else f"HTTP {r2.status_code}",
        )


# ===========================================================================
# A4: Mastery Grant/Revoke
# ===========================================================================
async def test_a4_mastery(
    c: httpx.AsyncClient, admin_h: dict, student_h: dict, student_id: str
) -> None:
    print("\n=== A4: Mastery Grant/Revoke ===")

    try:
        # Grant mastery for 1.1 (prerequisite for 1.2)
        await req(
            c, "POST", f"/api/admin/students/{student_id}/mastery/{CONCEPT_1_1}",
            f"A4.1 POST /api/admin/students/{{sid}}/mastery/{CONCEPT_1_1} (grant)",
            expected=200,
            headers=admin_h,
        )

        # Student readiness for 1.2 should show prereqs met
        r = await c.get(
            f"/api/v2/concepts/{CONCEPT_1_2}/readiness",
            params={"student_id": student_id, "book_slug": BOOK_SLUG},
            headers=student_h,
        )
        if r.status_code == 200:
            prereqs_met = r.json().get("all_prerequisites_met")
            _result(
                prereqs_met is True,
                f"A4.2 GET /api/v2/concepts/{CONCEPT_1_2}/readiness -> all_prerequisites_met=true",
                "" if prereqs_met else f"got all_prerequisites_met={prereqs_met}",
            )
        else:
            _skip(
                f"A4.2 GET /api/v2/concepts/{CONCEPT_1_2}/readiness",
                f"HTTP {r.status_code}",
            )

    finally:
        # Revoke mastery
        await req(
            c, "DELETE", f"/api/admin/students/{student_id}/mastery/{CONCEPT_1_1}",
            f"A4.3 DELETE /api/admin/students/{{sid}}/mastery/{CONCEPT_1_1} (revoke)",
            expected=(200, 204),
            headers=admin_h,
        )

        # Readiness should now show prereqs NOT met
        r2 = await c.get(
            f"/api/v2/concepts/{CONCEPT_1_2}/readiness",
            params={"student_id": student_id, "book_slug": BOOK_SLUG},
            headers=student_h,
        )
        if r2.status_code == 200:
            prereqs_met = r2.json().get("all_prerequisites_met")
            _result(
                prereqs_met is False,
                f"A4.4 GET /api/v2/concepts/{CONCEPT_1_2}/readiness -> all_prerequisites_met=false (after revoke)",
                "" if prereqs_met is False else f"got all_prerequisites_met={prereqs_met}",
            )
        else:
            _skip(
                f"A4.4 readiness after revoke",
                f"HTTP {r2.status_code}",
            )


# ===========================================================================
# A5: Chunk Hide + Student Verify
# ===========================================================================
async def test_a5_chunk_hide(
    c: httpx.AsyncClient, admin_h: dict, student_h: dict, student_id: str
) -> None:
    print("\n=== A5: Chunk Hide + Student Verify ===")

    # Get chunks for 1.1
    r = await c.get(
        f"/api/admin/books/{BOOK_SLUG}/chunks/{CONCEPT_1_1}",
        headers=admin_h,
    )
    if not r or r.status_code != 200 or not r.json():
        _skip("A5.1 PATCH chunk visibility (hide)", "could not fetch chunks")
        _skip("A5.2 student session chunks verify", "could not fetch chunks")
        _skip("A5.3 PATCH chunk visibility (unhide/reverse)", "could not fetch chunks")
        _skip("A5.4 (no extra test)", "could not fetch chunks")
        return

    chunks = r.json()
    # Pick the first visible chunk
    first_chunk = next((ch for ch in chunks if not ch.get("is_hidden")), None)
    if not first_chunk:
        _skip("A5.1 PATCH chunk visibility (hide)", "no visible chunk found")
        _skip("A5.2 student session chunks verify", "no visible chunk found")
        _skip("A5.3 PATCH chunk visibility (unhide/reverse)", "no visible chunk found")
        _skip("A5.4 (no extra test)", "no visible chunk found")
        return

    chunk_id = first_chunk["id"]
    print(f"         chunk_id={chunk_id[:8]}...")

    try:
        # Hide the chunk
        r_hide = await req(
            c, "PATCH", f"/api/admin/chunks/{chunk_id}/visibility",
            "A5.1 PATCH /api/admin/chunks/{id}/visibility (hide)",
            expected=200,
            headers=admin_h,
        )
        if not (r_hide and r_hide.status_code == 200):
            _skip("A5.2 student session chunks verify", "hide failed")
            return

        assert r_hide.json().get("is_hidden") is True, "is_hidden should be True after toggle"

        # Create a session for 1.1 to get student chunk list
        r_sess = await c.post(
            "/api/v2/sessions",
            json={
                "student_id": student_id,
                "concept_id": CONCEPT_1_1,
                "book_slug": BOOK_SLUG,
                "style": "default",
                "lesson_interests": [],
            },
            headers=student_h,
        )
        session_id = None
        if r_sess.status_code == 200:
            session_id = r_sess.json().get("id") or r_sess.json().get("session_id")
        else:
            # Try to find an existing session
            r_existing = await c.get(
                f"/api/v2/students/{student_id}/sessions",
                headers=student_h,
            )
            if r_existing.status_code == 200:
                body = r_existing.json()
                sessions_list = body if isinstance(body, list) else body.get("sessions", [])
                for s in sessions_list:
                    if s.get("concept_id") == CONCEPT_1_1:
                        session_id = s.get("id") or s.get("session_id")
                        break

        if session_id:
            r_chunks = await c.get(
                f"/api/v2/sessions/{session_id}/chunks",
                headers=student_h,
            )
            if r_chunks.status_code == 200:
                visible_ids = [
                    ch.get("id") for ch in r_chunks.json().get("chunks", [])
                ]
                hidden_absent = chunk_id not in visible_ids
                _result(
                    hidden_absent,
                    "A5.2 student GET /sessions/{id}/chunks -> hidden chunk NOT in list",
                    "" if hidden_absent else "hidden chunk still visible to student",
                )
            else:
                _skip("A5.2 student GET /sessions/{id}/chunks", f"HTTP {r_chunks.status_code}")
        else:
            _skip("A5.2 student GET /sessions/{id}/chunks", "could not get/create session")

    finally:
        # Unhide chunk (reverse)
        r_unhide = await req(
            c, "PATCH", f"/api/admin/chunks/{chunk_id}/visibility",
            "A5.3 PATCH /api/admin/chunks/{id}/visibility (unhide/reverse)",
            expected=200,
            headers=admin_h,
        )
        # Validate it was unhidden
        if r_unhide and r_unhide.status_code == 200:
            _result(
                r_unhide.json().get("is_hidden") is False,
                "A5.4 chunk is_hidden=False confirmed after unhide",
                "",
            )
        else:
            _skip("A5.4 chunk is_hidden=False confirmed after unhide", "unhide call failed")


# ===========================================================================
# A6: Chunk Exam Disable + Student Verify
# ===========================================================================
async def test_a6_chunk_exam_gate(
    c: httpx.AsyncClient, admin_h: dict, student_h: dict, student_id: str
) -> None:
    print("\n=== A6: Chunk Exam Disable + Student Verify ===")

    # Get a visible, non-hidden chunk for 1.1
    r = await c.get(
        f"/api/admin/books/{BOOK_SLUG}/chunks/{CONCEPT_1_1}",
        headers=admin_h,
    )
    if not r or r.status_code != 200 or not r.json():
        for i in range(1, 5):
            _skip(f"A6.{i}", "could not fetch chunks")
        return

    chunks = r.json()
    target_chunk = next(
        (ch for ch in chunks if not ch.get("is_hidden") and not ch.get("exam_disabled")),
        None,
    )
    if not target_chunk:
        for i in range(1, 5):
            _skip(f"A6.{i}", "no suitable chunk found")
        return

    chunk_id = target_chunk["id"]
    print(f"         chunk_id={chunk_id[:8]}...")

    # We need a session for this concept
    r_sess = await c.post(
        "/api/v2/sessions",
        json={
            "student_id": student_id,
            "concept_id": CONCEPT_1_1,
            "book_slug": BOOK_SLUG,
            "style": "default",
            "lesson_interests": [],
        },
        headers=student_h,
    )
    session_id = None
    if r_sess.status_code == 200:
        session_id = r_sess.json().get("id") or r_sess.json().get("session_id")
    else:
        r_existing = await c.get(
            f"/api/v2/students/{student_id}/sessions",
            headers=student_h,
        )
        if r_existing.status_code == 200:
            body = r_existing.json()
            sessions_list = body if isinstance(body, list) else body.get("sessions", [])
            for s in sessions_list:
                if s.get("concept_id") == CONCEPT_1_1:
                    session_id = s.get("id") or s.get("session_id")
                    break

    if not session_id:
        for i in range(1, 5):
            _skip(f"A6.{i}", "could not create/find session for chunk-cards")
        return

    try:
        # Disable exam gate
        r_disable = await req(
            c, "PATCH", f"/api/admin/chunks/{chunk_id}/exam-gate",
            "A6.1 PATCH /api/admin/chunks/{id}/exam-gate (disable exam)",
            expected=200,
            headers=admin_h,
        )
        if not (r_disable and r_disable.status_code == 200):
            _skip("A6.2 student POST chunk-cards -> questions empty", "exam-gate disable failed")
            return

        # Student: generate chunk-cards — questions should be empty []
        r_cards = await c.post(
            f"/api/v2/sessions/{session_id}/chunk-cards",
            json={"chunk_id": chunk_id},
            headers=student_h,
            timeout=30.0,
        )
        if r_cards.status_code == 200:
            questions = r_cards.json().get("questions", [])
            _result(
                len(questions) == 0,
                "A6.2 student POST chunk-cards -> questions=[] (exam disabled)",
                "" if len(questions) == 0 else f"got {len(questions)} questions, expected 0",
            )
        else:
            _skip("A6.2 student POST chunk-cards", f"HTTP {r_cards.status_code}")

    finally:
        # Re-enable exam gate (reverse)
        await req(
            c, "PATCH", f"/api/admin/chunks/{chunk_id}/exam-gate",
            "A6.3 PATCH /api/admin/chunks/{id}/exam-gate (re-enable/reverse)",
            expected=200,
            headers=admin_h,
        )

        # Student: generate chunk-cards again — questions should now have items
        # Use 120s timeout since LLM generation can be slow
        r_cards2 = await c.post(
            f"/api/v2/sessions/{session_id}/chunk-cards",
            json={"chunk_id": chunk_id},
            headers=student_h,
            timeout=120.0,
        )
        if r_cards2.status_code == 200:
            questions2 = r_cards2.json().get("questions", [])
            _result(
                len(questions2) > 0,
                "A6.4 student POST chunk-cards -> questions non-empty (exam re-enabled, LLM 120s)",
                "" if len(questions2) > 0 else "questions still empty after re-enable",
            )
        else:
            _skip("A6.4 student POST chunk-cards after re-enable", f"HTTP {r_cards2.status_code}")


# ===========================================================================
# A7: Chunk Optional Toggle
# ===========================================================================
async def test_a7_chunk_optional(
    c: httpx.AsyncClient, admin_h: dict
) -> None:
    print("\n=== A7: Chunk Optional Toggle ===")

    r = await c.get(
        f"/api/admin/books/{BOOK_SLUG}/chunks/{CONCEPT_1_1}",
        headers=admin_h,
    )
    if not r or r.status_code != 200 or not r.json():
        _skip("A7.1 PATCH chunk is_optional=true", "could not fetch chunks")
        _skip("A7.2 PATCH chunk is_optional=false", "could not fetch chunks")
        return

    chunk_id = r.json()[0]["id"]
    print(f"         chunk_id={chunk_id[:8]}...")

    try:
        # Mark optional
        r1 = await req(
            c, "PATCH", f"/api/admin/chunks/{chunk_id}",
            "A7.1 PATCH /api/admin/chunks/{id} (is_optional=true)",
            expected=200,
            json={"is_optional": True},
            headers=admin_h,
        )
        if r1 and r1.status_code == 200:
            assert r1.json().get("is_optional") is True, "expected is_optional=true"
    finally:
        # Reverse
        await req(
            c, "PATCH", f"/api/admin/chunks/{chunk_id}",
            "A7.2 PATCH /api/admin/chunks/{id} (is_optional=false/reverse)",
            expected=200,
            json={"is_optional": False},
            headers=admin_h,
        )


# ===========================================================================
# A8: Chunk Type Change
# ===========================================================================
async def test_a8_chunk_type(
    c: httpx.AsyncClient, admin_h: dict
) -> None:
    print("\n=== A8: Chunk Type Change ===")

    r = await c.get(
        f"/api/admin/books/{BOOK_SLUG}/chunks/{CONCEPT_1_1}",
        headers=admin_h,
    )
    if not r or r.status_code != 200 or not r.json():
        _skip("A8.1 PATCH chunk chunk_type=exercise", "could not fetch chunks")
        _skip("A8.2 PATCH chunk chunk_type=teaching (reverse)", "could not fetch chunks")
        return

    chunk = r.json()[0]
    chunk_id = chunk["id"]
    original_type = chunk.get("chunk_type") or "teaching"
    print(f"         chunk_id={chunk_id[:8]}... original_type={original_type}")

    try:
        r1 = await req(
            c, "PATCH", f"/api/admin/chunks/{chunk_id}",
            "A8.1 PATCH /api/admin/chunks/{id} (chunk_type=exercise)",
            expected=200,
            json={"chunk_type": "exercise"},
            headers=admin_h,
        )
        if r1 and r1.status_code == 200:
            assert r1.json().get("chunk_type") == "exercise", "type mismatch"
    finally:
        await req(
            c, "PATCH", f"/api/admin/chunks/{chunk_id}",
            "A8.2 PATCH /api/admin/chunks/{id} (chunk_type=teaching/reverse)",
            expected=200,
            json={"chunk_type": original_type},
            headers=admin_h,
        )


# ===========================================================================
# A9: Section-Level Controls
# ===========================================================================
async def test_a9_section_controls(
    c: httpx.AsyncClient, admin_h: dict
) -> None:
    print("\n=== A9: Section-Level Controls ===")
    payload_base = {"book_slug": BOOK_SLUG}

    # --- visibility ---
    try:
        await req(
            c, "PATCH", f"/api/admin/sections/{CONCEPT_1_1}/visibility",
            "A9.1 PATCH /api/admin/sections/{concept}/visibility (is_hidden=true)",
            expected=200,
            json={**payload_base, "is_hidden": True},
            headers=admin_h,
        )
    finally:
        await req(
            c, "PATCH", f"/api/admin/sections/{CONCEPT_1_1}/visibility",
            "A9.2 PATCH /api/admin/sections/{concept}/visibility (is_hidden=false/reverse)",
            expected=200,
            json={**payload_base, "is_hidden": False},
            headers=admin_h,
        )

    # --- optional ---
    try:
        await req(
            c, "PATCH", f"/api/admin/sections/{CONCEPT_1_1}/optional",
            "A9.3 PATCH /api/admin/sections/{concept}/optional (is_optional=true)",
            expected=200,
            json={**payload_base, "is_optional": True},
            headers=admin_h,
        )
    finally:
        await req(
            c, "PATCH", f"/api/admin/sections/{CONCEPT_1_1}/optional",
            "A9.4 PATCH /api/admin/sections/{concept}/optional (is_optional=false/reverse)",
            expected=200,
            json={**payload_base, "is_optional": False},
            headers=admin_h,
        )

    # --- exam gate ---
    try:
        await req(
            c, "PATCH", f"/api/admin/sections/{CONCEPT_1_1}/exam-gate",
            "A9.5 PATCH /api/admin/sections/{concept}/exam-gate (disabled=true)",
            expected=200,
            json={**payload_base, "disabled": True},
            headers=admin_h,
        )
    finally:
        await req(
            c, "PATCH", f"/api/admin/sections/{CONCEPT_1_1}/exam-gate",
            "A9.6 PATCH /api/admin/sections/{concept}/exam-gate (disabled=false/reverse)",
            expected=200,
            json={**payload_base, "disabled": False},
            headers=admin_h,
        )


# ===========================================================================
# A10: Graph Edge Add/Remove
# ===========================================================================
async def test_a10_graph_edge(
    c: httpx.AsyncClient, admin_h: dict
) -> None:
    print("\n=== A10: Graph Edge Add/Remove ===")
    override_id: "str | None" = None

    try:
        # Add edge
        r = await req(
            c, "POST", f"/api/admin/graph/{BOOK_SLUG}/edges",
            "A10.1 POST /api/admin/graph/{slug}/edges (add_edge)",
            expected=(200, 400),  # 400 if cycle or already exists
            json={
                "action": "add_edge",
                "source": PREREQ_SOURCE,
                "target": PREREQ_TARGET,
            },
            headers=admin_h,
        )
        if not (r and r.status_code == 200):
            _skip("A10.2 GET /api/admin/graph/{slug}/overrides verify", "add_edge failed or would create cycle")
            return

        # Verify override in list
        r2 = await req(
            c, "GET", f"/api/admin/graph/{BOOK_SLUG}/overrides",
            "A10.2 GET /api/admin/graph/{slug}/overrides (verify override exists)",
            expected=200,
            headers=admin_h,
        )
        if r2 and r2.status_code == 200:
            overrides = r2.json()
            for ov in overrides:
                if (
                    ov.get("action") == "add_edge"
                    and ov.get("source") == PREREQ_SOURCE
                    and ov.get("target") == PREREQ_TARGET
                ):
                    override_id = ov["id"]
                    break
            if not override_id:
                print("         WARNING: override not found in list (may have been deduplicated)")

    finally:
        if override_id:
            await req(
                c, "DELETE", f"/api/admin/graph/{BOOK_SLUG}/overrides/{override_id}",
                "A10.3 DELETE /api/admin/graph/{slug}/overrides/{id} (remove override)",
                expected=(200, 404),
                headers=admin_h,
            )
        else:
            _skip("A10.3 DELETE /api/admin/graph/{slug}/overrides/{id}", "override_id not captured")


# ===========================================================================
# A11: Config Change
# ===========================================================================
async def test_a11_config(
    c: httpx.AsyncClient, admin_h: dict
) -> None:
    print("\n=== A11: Config Change ===")
    config_key = "CHUNK_EXAM_PASS_RATE"
    original_value: "str | None" = None

    # Get current config
    r = await req(
        c, "GET", "/api/admin/config",
        "A11.1 GET /api/admin/config (read current)",
        expected=200,
        headers=admin_h,
    )
    if r and r.status_code == 200:
        original_value = r.json().get(config_key)
        print(f"         current {config_key}={original_value!r}")
    else:
        _skip("A11.2 PATCH /api/admin/config (update)", "GET config failed")
        _skip("A11.3 PATCH /api/admin/config (revert)", "GET config failed")
        return

    try:
        # Change config
        await req(
            c, "PATCH", "/api/admin/config",
            "A11.2 PATCH /api/admin/config (set CHUNK_EXAM_PASS_RATE=0.60)",
            expected=200,
            json={config_key: "0.60"},
            headers=admin_h,
        )
    finally:
        # Revert to original (or delete key if it didn't exist before)
        revert_value = original_value if original_value is not None else "0.50"
        await req(
            c, "PATCH", "/api/admin/config",
            "A11.3 PATCH /api/admin/config (revert to original value)",
            expected=200,
            json={config_key: revert_value},
            headers=admin_h,
        )


# ===========================================================================
# A12: Admin User Management
# ===========================================================================
async def test_a12_admin_user(
    c: httpx.AsyncClient, admin_h: dict
) -> None:
    print("\n=== A12: Admin User Management ===")
    new_user_id: "str | None" = None
    test_email = "testadmin_stage2@test.com"

    try:
        # Create admin user
        r = await req(
            c, "POST", "/api/admin/users/create-admin",
            "A12.1 POST /api/admin/users/create-admin",
            expected=(200, 409),  # 409 if email already exists from prior run
            json={
                "email": test_email,
                "password": "TestAdmin@1234",
                "display_name": "Test Admin Stage2",
            },
            headers=admin_h,
        )
        if r and r.status_code == 200:
            new_user_id = r.json().get("id")
            print(f"         new_user_id={new_user_id[:8] if new_user_id else '?'}...")
        elif r and r.status_code == 409:
            # Email already exists from a prior run — find the user in the list
            r_list = await c.get("/api/admin/users", headers=admin_h)
            if r_list.status_code == 200:
                for u in r_list.json().get("users", []):
                    if u.get("email") == test_email:
                        new_user_id = u["id"]
                        break

        # Verify new admin appears in user list
        r2 = await req(
            c, "GET", "/api/admin/users",
            "A12.2 GET /api/admin/users (verify new admin in list)",
            expected=200,
            headers=admin_h,
        )
        if r2 and r2.status_code == 200:
            emails = [u.get("email") for u in r2.json().get("users", [])]
            # The default list may be paginated; check whether email appears
            found = test_email in emails
            if not found:
                # Try fetching more pages
                r2b = await c.get(
                    "/api/admin/users",
                    params={"limit": 200},
                    headers=admin_h,
                )
                if r2b.status_code == 200:
                    emails2 = [u.get("email") for u in r2b.json().get("users", [])]
                    found = test_email in emails2
            _result(
                found,
                f"A12.2 new admin email '{test_email}' found in /api/admin/users",
                "" if found else "not found in user list",
            )

    finally:
        # Demote to student (soft cleanup — avoids hard-delete, reverses admin grant)
        if new_user_id:
            await req(
                c, "PATCH", f"/api/admin/users/{new_user_id}/role",
                "A12.3 PATCH /api/admin/users/{id}/role (demote to student, soft cleanup)",
                expected=200,
                json={"role": "student"},
                headers=admin_h,
            )
        else:
            _skip("A12.3 PATCH /api/admin/users/{id}/role (demote)", "new_user_id not captured")


# ===========================================================================
# A13: Student Name Update
# ===========================================================================
async def test_a13_student_name(
    c: httpx.AsyncClient, admin_h: dict, student_id: str
) -> None:
    print("\n=== A13: Student Name Update ===")

    # Fetch original name
    r = await c.get(f"/api/admin/students/{student_id}", headers=admin_h)
    original_name = "Manu"  # fallback
    if r.status_code == 200:
        original_name = r.json().get("profile", {}).get("display_name", original_name)
    print(f"         original_name={original_name!r}")

    try:
        r1 = await req(
            c, "PATCH", f"/api/admin/students/{student_id}",
            "A13.1 PATCH /api/admin/students/{sid} (display_name=Test Renamed)",
            expected=200,
            json={"display_name": "Test Renamed"},
            headers=admin_h,
        )
        if r1 and r1.status_code == 200:
            assert r1.json().get("display_name") == "Test Renamed", "name mismatch"
    finally:
        await req(
            c, "PATCH", f"/api/admin/students/{student_id}",
            "A13.2 PATCH /api/admin/students/{sid} (restore original name/reverse)",
            expected=200,
            json={"display_name": original_name},
            headers=admin_h,
        )


# ===========================================================================
# A14: Section Rename
# ===========================================================================
async def test_a14_section_rename(
    c: httpx.AsyncClient, admin_h: dict
) -> None:
    print("\n=== A14: Section Rename ===")

    # Fetch current admin_section_name for 1.1 chunks
    r = await c.get(
        f"/api/admin/books/{BOOK_SLUG}/sections",
        headers=admin_h,
    )
    original_name: "str | None" = None
    if r.status_code == 200:
        for chapter in r.json().get("chapters", []):
            for sec in chapter.get("sections", []):
                if sec.get("concept_id") == CONCEPT_1_1:
                    original_name = sec.get("display_name") or sec.get("section")
                    break
    if original_name is None:
        original_name = "1.1"  # fallback
    print(f"         original_name={original_name!r}")

    try:
        r1 = await req(
            c, "PATCH", f"/api/admin/sections/{CONCEPT_1_1}/rename",
            "A14.1 PATCH /api/admin/sections/{concept}/rename (name=Test Rename)",
            expected=200,
            json={"name": "Test Rename", "book_slug": BOOK_SLUG},
            headers=admin_h,
        )
        if r1 and r1.status_code == 200:
            assert r1.json().get("admin_section_name") == "Test Rename", "name mismatch"
    finally:
        await req(
            c, "PATCH", f"/api/admin/sections/{CONCEPT_1_1}/rename",
            "A14.2 PATCH /api/admin/sections/{concept}/rename (restore original/reverse)",
            expected=200,
            json={"name": original_name, "book_slug": BOOK_SLUG},
            headers=admin_h,
        )


# ===========================================================================
# Main runner
# ===========================================================================
async def run_tests() -> None:
    async with httpx.AsyncClient(
        base_url=BASE,
        timeout=60.0,
        headers={"X-API-Key": API_KEY},
    ) as c:
        # ----------------------------------------------------------------
        # Bootstrap: login both actors
        # ----------------------------------------------------------------
        print("\n=== Bootstrap: Login ===")

        admin_token = await _login_admin(c)
        if not admin_token:
            print("\n  [FATAL] Admin login failed. Aborting all tests.")
            return
        admin_h = {"Authorization": f"Bearer {admin_token}"}
        print("  Admin login OK")

        student_data = await _login_student(c)
        if not student_data:
            print("\n  [FATAL] Student login failed. Aborting all tests.")
            return
        student_token = student_data["token"]
        student_id = student_data["student_id"]
        student_h = {"Authorization": f"Bearer {student_token}"}
        print(f"  Student login OK -- student_id={student_id[:8]}...")

        # ----------------------------------------------------------------
        # Run each test group
        # ----------------------------------------------------------------
        await test_a1_subject_crud(c, admin_h)
        await test_a2_book_visibility(c, admin_h)
        await test_a3_student_access(c, admin_h, student_id)

        # Refresh student token after A3 (access was re-enabled, token still valid)
        student_data2 = await _login_student(c)
        if student_data2:
            student_token = student_data2["token"]
            student_h = {"Authorization": f"Bearer {student_token}"}

        await test_a4_mastery(c, admin_h, student_h, student_id)
        await test_a5_chunk_hide(c, admin_h, student_h, student_id)
        await test_a6_chunk_exam_gate(c, admin_h, student_h, student_id)
        await test_a7_chunk_optional(c, admin_h)
        await test_a8_chunk_type(c, admin_h)
        await test_a9_section_controls(c, admin_h)
        await test_a10_graph_edge(c, admin_h)
        await test_a11_config(c, admin_h)
        await test_a12_admin_user(c, admin_h)
        await test_a13_student_name(c, admin_h, student_id)
        await test_a14_section_rename(c, admin_h)

    _print_summary()


def _print_summary() -> None:
    total = PASS_COUNT + FAIL_COUNT
    print("\n" + "=" * 60)
    print(f"  RESULTS: {PASS_COUNT} PASS, {FAIL_COUNT} FAIL out of {total} tests")
    print("=" * 60)


async def _safe_run() -> None:
    try:
        await run_tests()
    except Exception as exc:
        print(f"\n  [FATAL] Unhandled exception: {type(exc).__name__}: {exc}")
        _print_summary()


if __name__ == "__main__":
    asyncio.run(_safe_run())
