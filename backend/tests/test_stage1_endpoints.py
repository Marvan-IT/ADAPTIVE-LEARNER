"""
test_stage1_endpoints.py
Read-only endpoint smoke tests for the ADA backend.

Tests all 50 read-only (and minimal write) endpoints in numbered order.
Run with:
    PYTHONIOENCODING=utf-8 python backend/tests/test_stage1_endpoints.py
or:
    cd backend && python tests/test_stage1_endpoints.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Ensure src/ is importable when run directly
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
CONCEPT_ID = "business_statistics_1.0"

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
    r: httpx.Response | None,
    label: str,
    expected: int | tuple[int, ...] = 200,
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
    expected: int | tuple[int, ...] = 200,
    detail: str = "",
    _retry: bool = True,
    **kwargs,
) -> httpx.Response | None:
    """Send an HTTP request, record PASS/FAIL, and never raise.

    ``expected`` may be a single int or a tuple of acceptable status codes.
    On a ReadError (server-side crash dropping the connection) one retry is
    attempted after a short pause so that the uvicorn worker can recover.
    """
    try:
        r = await c.request(method, url, **kwargs)
        check(r, label, expected=expected, detail=detail)
        return r
    except httpx.ReadError:
        if _retry:
            await asyncio.sleep(1.5)
            return await req(c, method, url, label, expected=expected,
                             detail=detail, _retry=False, **kwargs)
        _result(False, label, detail="ReadError (server dropped connection)")
        return None
    except Exception as exc:
        _result(False, label, detail=f"{type(exc).__name__}: {str(exc)[:80]}")
        return None


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------
async def run_tests() -> None:
    async with httpx.AsyncClient(
        base_url=BASE,
        timeout=30,
        headers={"X-API-Key": API_KEY},
    ) as c:

        # ===================================================================
        print("\n=== SECTION 1: Public endpoints (API key only) ===")
        # ===================================================================

        # 1. GET /health
        await req(c, "GET", "/health", "GET /health")

        # 2. GET /api/v1/books
        r = await req(c, "GET", "/api/v1/books", "GET /api/v1/books")
        books_v1 = r.json() if r and r.status_code == 200 else []
        if r and r.status_code == 200:
            print(f"         {len(books_v1)} books")

        # 3. GET /api/v2/books
        r = await req(c, "GET", "/api/v2/books", "GET /api/v2/books")
        if r and r.status_code == 200:
            print(f"         {len(r.json())} books")

        # 4. GET /api/v2/features
        await req(c, "GET", "/api/v2/features", "GET /api/v2/features")

        # 5. GET /api/v1/graph/full
        r = await req(c, "GET", "/api/v1/graph/full", "GET /api/v1/graph/full",
                      params={"book_slug": BOOK_SLUG})
        if r and r.status_code == 200:
            print(f"         {len(r.json().get('nodes', []))} nodes")

        # 6. GET /api/v1/graph/info
        await req(c, "GET", "/api/v1/graph/info", "GET /api/v1/graph/info",
                  params={"book_slug": BOOK_SLUG})

        # 7. GET /api/v1/graph/nodes
        await req(c, "GET", "/api/v1/graph/nodes", "GET /api/v1/graph/nodes",
                  params={"book_slug": BOOK_SLUG})

        # 8. GET /api/v1/graph/topological-order
        await req(c, "GET", "/api/v1/graph/topological-order",
                  "GET /api/v1/graph/topological-order", params={"book_slug": BOOK_SLUG})

        # 9. GET /api/v1/concepts/{concept_id}
        await req(c, "GET", f"/api/v1/concepts/{CONCEPT_ID}",
                  f"GET /api/v1/concepts/{CONCEPT_ID}", params={"book_slug": BOOK_SLUG})

        # 10. GET /api/v1/concepts/{concept_id}/prerequisites
        await req(c, "GET", f"/api/v1/concepts/{CONCEPT_ID}/prerequisites",
                  f"GET /api/v1/concepts/{CONCEPT_ID}/prerequisites",
                  params={"book_slug": BOOK_SLUG})

        # 11. GET /api/v1/concepts/{concept_id}/images
        await req(c, "GET", f"/api/v1/concepts/{CONCEPT_ID}/images",
                  f"GET /api/v1/concepts/{CONCEPT_ID}/images", params={"book_slug": BOOK_SLUG})

        # 12. POST /api/v1/concepts/query
        await req(c, "POST", "/api/v1/concepts/query", "POST /api/v1/concepts/query",
                  json={"query": "statistics", "n_results": 3, "book_slug": BOOK_SLUG})

        # 13. POST /api/v1/graph/learning-path
        # Correct schema: field is target_concept_id; book_slug is a query param (not in body)
        # NOTE: backend has a known serialization bug (path items are strings, not LearningPathStep
        # dicts) — this will return 500 until fixed. Test records truthfully.
        await req(c, "POST", "/api/v1/graph/learning-path",
                  "POST /api/v1/graph/learning-path",
                  params={"book_slug": BOOK_SLUG},
                  json={"target_concept_id": "business_statistics_1.3", "mastered_concepts": []})

        # 14. POST /api/v2/concepts/translate-titles
        await req(c, "POST", "/api/v2/concepts/translate-titles",
                  "POST /api/v2/concepts/translate-titles",
                  json={"titles": {CONCEPT_ID: "Chapter 1 Introduction"}, "language": "ml"})

        # ===================================================================
        print("\n=== SECTION 2: Auth endpoints ===")
        # ===================================================================

        # 15. POST /api/v1/auth/login (admin)
        r = await req(c, "POST", "/api/v1/auth/login",
                      "POST /api/v1/auth/login (admin)",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        if not r or r.status_code != 200:
            print("\n  [FATAL] Admin login failed. Aborting.")
            return
        admin_token = r.json()["access_token"]
        admin_h = {"Authorization": f"Bearer {admin_token}"}

        # 16. POST /api/v1/auth/login (student)
        r = await req(c, "POST", "/api/v1/auth/login",
                      "POST /api/v1/auth/login (student)",
                      json={"email": STUDENT_EMAIL, "password": STUDENT_PASSWORD})
        if not r or r.status_code != 200:
            print("\n  [FATAL] Student login failed. Aborting.")
            return
        login_data = r.json()
        student_token = login_data["access_token"]
        student_refresh = login_data["refresh_token"]
        sid = login_data["user"]["student_id"]
        student_h = {"Authorization": f"Bearer {student_token}"}
        print(f"         student_id = {sid}")

        # 17. GET /api/v1/auth/me
        await req(c, "GET", "/api/v1/auth/me", "GET /api/v1/auth/me (student)",
                  headers=student_h)

        # 18. POST /api/v1/auth/refresh
        # Refresh rotates the token — capture the new access + refresh tokens immediately.
        r = await req(c, "POST", "/api/v1/auth/refresh", "POST /api/v1/auth/refresh",
                      json={"refresh_token": student_refresh})
        if r and r.status_code == 200:
            refresh_data = r.json()
            student_token = refresh_data["access_token"]
            student_refresh = refresh_data.get("refresh_token", student_refresh)
            student_h = {"Authorization": f"Bearer {student_token}"}

        # ===================================================================
        print("\n=== SECTION 3: Student profile endpoints (student token) ===")
        # ===================================================================

        # 19. GET /api/v2/students/{sid}
        await req(c, "GET", f"/api/v2/students/{sid}",
                  f"GET /api/v2/students/{sid[:8]}...", headers=student_h)

        # 20. GET /api/v2/students/{sid}/mastery
        r = await req(c, "GET", f"/api/v2/students/{sid}/mastery",
                      f"GET /api/v2/students/{sid[:8]}.../mastery", headers=student_h)
        if r and r.status_code == 200:
            body = r.json()
            count = len(body) if isinstance(body, list) else "?"
            print(f"         {count} mastered")

        # 21. GET /api/v2/students/{sid}/analytics
        await req(c, "GET", f"/api/v2/students/{sid}/analytics",
                  f"GET /api/v2/students/{sid[:8]}.../analytics", headers=student_h)

        # 22. GET /api/v2/students/{sid}/sessions
        await req(c, "GET", f"/api/v2/students/{sid}/sessions",
                  f"GET /api/v2/students/{sid[:8]}.../sessions", headers=student_h)

        # 23. GET /api/v2/students/{sid}/badges
        await req(c, "GET", f"/api/v2/students/{sid}/badges",
                  f"GET /api/v2/students/{sid[:8]}.../badges", headers=student_h)

        # 24. GET /api/v2/students/{sid}/card-history
        await req(c, "GET", f"/api/v2/students/{sid}/card-history",
                  f"GET /api/v2/students/{sid[:8]}.../card-history", headers=student_h)

        # 25. GET /api/v2/students/{sid}/review-due
        await req(c, "GET", f"/api/v2/students/{sid}/review-due",
                  f"GET /api/v2/students/{sid[:8]}.../review-due", headers=student_h)

        # 26. GET /api/v2/leaderboard
        await req(c, "GET", "/api/v2/leaderboard", "GET /api/v2/leaderboard",
                  headers=student_h)

        # 27. GET /api/v2/concepts/{concept_id}/readiness
        r = await req(c, "GET", f"/api/v2/concepts/{CONCEPT_ID}/readiness",
                      f"GET /api/v2/concepts/{CONCEPT_ID}/readiness",
                      params={"student_id": sid, "book_slug": BOOK_SLUG},
                      headers=student_h)
        if r and r.status_code == 200:
            print(f"         prereqs_met={r.json().get('all_prerequisites_met')}")

        # ===================================================================
        print("\n=== SECTION 4: Admin GET endpoints (admin token) ===")
        # ===================================================================

        # 28. GET /api/admin/dashboard
        await req(c, "GET", "/api/admin/dashboard", "GET /api/admin/dashboard",
                  headers=admin_h)

        # 29. GET /api/admin/students
        await req(c, "GET", "/api/admin/students", "GET /api/admin/students",
                  headers=admin_h)

        # 30. GET /api/admin/students/{sid}
        await req(c, "GET", f"/api/admin/students/{sid}",
                  f"GET /api/admin/students/{sid[:8]}...", headers=admin_h)

        # 31. GET /api/admin/students/{sid}/progress-report
        await req(c, "GET", f"/api/admin/students/{sid}/progress-report",
                  f"GET /api/admin/students/{sid[:8]}.../progress-report", headers=admin_h)

        # 32. GET /api/admin/sessions
        await req(c, "GET", "/api/admin/sessions", "GET /api/admin/sessions",
                  headers=admin_h)

        # 33. GET /api/admin/analytics
        await req(c, "GET", "/api/admin/analytics", "GET /api/admin/analytics",
                  headers=admin_h)

        # 34. GET /api/admin/users
        await req(c, "GET", "/api/admin/users", "GET /api/admin/users", headers=admin_h)

        # 35. GET /api/admin/config
        await req(c, "GET", "/api/admin/config", "GET /api/admin/config", headers=admin_h)

        # 36. GET /api/admin/subjects
        await req(c, "GET", "/api/admin/subjects", "GET /api/admin/subjects",
                  headers=admin_h)

        # 37. GET /api/admin/books
        await req(c, "GET", "/api/admin/books", "GET /api/admin/books", headers=admin_h)

        # 38. GET /api/admin/books/{slug}/status
        await req(c, "GET", f"/api/admin/books/{BOOK_SLUG}/status",
                  f"GET /api/admin/books/{BOOK_SLUG}/status", headers=admin_h)

        # 39. GET /api/admin/books/{slug}/sections
        await req(c, "GET", f"/api/admin/books/{BOOK_SLUG}/sections",
                  f"GET /api/admin/books/{BOOK_SLUG}/sections", headers=admin_h)

        # 40. GET /api/admin/books/{slug}/chunks/{concept_id}
        r = await req(c, "GET", f"/api/admin/books/{BOOK_SLUG}/chunks/{CONCEPT_ID}",
                      f"GET /api/admin/books/{BOOK_SLUG}/chunks/{CONCEPT_ID}",
                      headers=admin_h)
        if r and r.status_code == 200:
            body = r.json()
            count = len(body) if isinstance(body, list) else "?"
            print(f"         {count} chunks")

        # 41. GET /api/admin/books/{slug}/graph
        await req(c, "GET", f"/api/admin/books/{BOOK_SLUG}/graph",
                  f"GET /api/admin/books/{BOOK_SLUG}/graph", headers=admin_h)

        # 42. GET /api/admin/graph/{slug}/edges
        await req(c, "GET", f"/api/admin/graph/{BOOK_SLUG}/edges",
                  f"GET /api/admin/graph/{BOOK_SLUG}/edges", headers=admin_h)

        # 43. GET /api/admin/graph/{slug}/overrides
        await req(c, "GET", f"/api/admin/graph/{BOOK_SLUG}/overrides",
                  f"GET /api/admin/graph/{BOOK_SLUG}/overrides", headers=admin_h)

        # ===================================================================
        print("\n=== SECTION 5: Session endpoints (create + read) ===")
        # ===================================================================

        # 44. POST /api/v2/sessions — create a new session
        session_id: str | None = None
        r = await req(c, "POST", "/api/v2/sessions", "POST /api/v2/sessions",
                      json={
                          "student_id": sid,
                          "concept_id": CONCEPT_ID,
                          "book_slug": BOOK_SLUG,
                          "style": "default",
                          "lesson_interests": [],
                      },
                      headers=student_h)
        if r and r.status_code == 200:
            session_id = r.json().get("id") or r.json().get("session_id")
            print(f"         session_id = {session_id[:8]}...")
        else:
            # Fall back to an existing session so read tests can still run
            r2 = await c.get(f"/api/v2/students/{sid}/sessions", headers=student_h)
            if r2 and r2.status_code == 200:
                body = r2.json()
                sessions_list = body if isinstance(body, list) else body.get("sessions", [])
                if sessions_list:
                    session_id = sessions_list[0].get("id") or sessions_list[0].get("session_id")
            if session_id:
                print(f"         Using existing session: {session_id[:8]}...")
            else:
                print("         No session available -- skipping session read tests.")
                _record_skipped(5)

        if session_id:
            # 45. GET /api/v2/sessions/{session_id}
            await req(c, "GET", f"/api/v2/sessions/{session_id}",
                      f"GET /api/v2/sessions/{session_id[:8]}...", headers=student_h)

            # 46. GET /api/v2/sessions/{session_id}/chunks
            r = await req(c, "GET", f"/api/v2/sessions/{session_id}/chunks",
                          f"GET /api/v2/sessions/{session_id[:8]}.../chunks",
                          headers=student_h)
            if r and r.status_code == 200:
                print(f"         {len(r.json().get('chunks', []))} chunks")

            # 47. GET /api/v2/sessions/{session_id}/history
            await req(c, "GET", f"/api/v2/sessions/{session_id}/history",
                      f"GET /api/v2/sessions/{session_id[:8]}.../history",
                      headers=student_h)

            # 48. GET /api/v2/sessions/{session_id}/card-interactions
            await req(c, "GET", f"/api/v2/sessions/{session_id}/card-interactions",
                      f"GET /api/v2/sessions/{session_id[:8]}.../card-interactions",
                      headers=student_h)

            # 49. GET /api/v2/sessions/resume
            # 200 = active session found and returned.
            # 404 = no resumable session exists — also valid.
            # 500 = backend serialization bug; recorded truthfully as FAIL.
            await req(c, "GET", "/api/v2/sessions/resume",
                      "GET /api/v2/sessions/resume",
                      expected=(200, 404),
                      params={
                          "student_id": sid,
                          "concept_id": CONCEPT_ID,
                          "book_slug": BOOK_SLUG,
                      },
                      headers=student_h)

        # ===================================================================
        print("\n=== SECTION 6: Logout (invalidates token -- last test) ===")
        # ===================================================================

        # 50. POST /api/v1/auth/logout
        await req(c, "POST", "/api/v1/auth/logout", "POST /api/v1/auth/logout",
                  json={"refresh_token": student_refresh}, headers=student_h)

    _print_summary()


def _record_skipped(count: int) -> None:
    """Mark tests as FAIL when they are skipped due to a dependency failure."""
    global FAIL_COUNT, TEST_NUM
    for _ in range(count):
        TEST_NUM += 1
        FAIL_COUNT += 1
        print(f"  [FAIL] #{TEST_NUM:02d} (skipped — dependency failed)")


def _print_summary() -> None:
    total = PASS_COUNT + FAIL_COUNT
    print("\n" + "=" * 55)
    print(f"  RESULTS: {PASS_COUNT} PASS, {FAIL_COUNT} FAIL out of {total} tests")
    print("=" * 55)


async def _safe_run() -> None:
    try:
        await run_tests()
    except Exception as exc:
        print(f"\n  [FATAL] Unhandled exception: {type(exc).__name__}: {exc}")
        _print_summary()


if __name__ == "__main__":
    asyncio.run(_safe_run())
