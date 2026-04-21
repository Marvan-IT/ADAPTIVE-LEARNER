"""Exhaustive API test script — tests every endpoint, admin action, and student flow."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import httpx

PASS = 0
FAIL = 0
BASE = "http://localhost:8889"
# API key for local dev (from backend/.env)
API_KEY = "e36e77ba81581c1b6c1a00c44112db727fc1d00a8b073c5ea54be454ae778c22"


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def fail(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


async def run_tests():
    global PASS, FAIL

    async with httpx.AsyncClient(base_url=BASE, timeout=30, headers={"X-API-Key": API_KEY}) as c:
        # ═══════════════════════════════════════════════════
        print("\n=== SECTION 1: Health & Public Endpoints ===")
        # ═══════════════════════════════════════════════════
        r = await c.get("/health")
        ok("GET /health") if r.status_code == 200 else fail(f"GET /health {r.status_code}")

        r = await c.get("/api/v1/books")
        ok(f"GET /v1/books ({len(r.json())} books)") if r.status_code == 200 else fail(f"GET /v1/books {r.status_code}")

        r = await c.get("/api/v2/books")
        ok(f"GET /v2/books ({len(r.json())} books)") if r.status_code == 200 else fail(f"GET /v2/books {r.status_code}")

        r = await c.get("/api/v2/features")
        ok("GET /features") if r.status_code == 200 else fail(f"GET /features {r.status_code}")

        r = await c.get("/api/v1/graph/full", params={"book_slug": "business_statistics"})
        ok(f"GET /graph/full ({len(r.json().get('nodes', []))} nodes)") if r.status_code == 200 else fail("GET /graph/full")

        r = await c.get("/api/v1/graph/info", params={"book_slug": "business_statistics"})
        ok("GET /graph/info") if r.status_code == 200 else fail("GET /graph/info")

        r = await c.get("/api/v1/graph/nodes", params={"book_slug": "business_statistics"})
        ok("GET /graph/nodes") if r.status_code == 200 else fail("GET /graph/nodes")

        r = await c.get("/api/v1/graph/topological-order", params={"book_slug": "business_statistics"})
        ok("GET /graph/topo") if r.status_code == 200 else fail("GET /graph/topo")

        r = await c.get("/api/v1/concepts/business_statistics_1.0")
        ok("GET /concepts/1.0") if r.status_code == 200 else fail("GET /concepts/1.0")

        r = await c.get("/api/v1/concepts/business_statistics_1.0/prerequisites")
        ok("GET /prereqs") if r.status_code == 200 else fail("GET /prereqs")

        r = await c.get("/api/v1/concepts/business_statistics_1.0/images")
        ok("GET /images") if r.status_code == 200 else fail("GET /images")

        # ═══════════════════════════════════════════════════
        print("\n=== SECTION 2: Auth ===")
        # ═══════════════════════════════════════════════════
        r = await c.post("/api/v1/auth/login", json={"email": "muhammed.marvan@hightekers.com", "password": "Admin@1234"})
        if r.status_code != 200:
            fail(f"Login admin {r.status_code}: {r.text[:100]}")
            return
        ok("Login admin")
        admin_h = {"Authorization": f"Bearer {r.json()['access_token']}"}

        r = await c.post("/api/v1/auth/login", json={"email": "manujaleel007@gmail.com", "password": "Marvan@1234"})
        if r.status_code != 200:
            fail(f"Login student {r.status_code}: {r.text[:100]}")
            return
        ok("Login student")
        st = r.json()
        student_h = {"Authorization": f"Bearer {st['access_token']}"}
        sid = st["user"]["student_id"]

        r = await c.get("/api/v1/auth/me", headers=student_h)
        ok("GET /auth/me") if r.status_code == 200 else fail("GET /auth/me")

        r = await c.post("/api/v1/auth/refresh", json={"refresh_token": st["refresh_token"]})
        if r.status_code == 200:
            ok("POST /auth/refresh")
            student_h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        else:
            fail(f"POST /auth/refresh {r.status_code}")

        # ═══════════════════════════════════════════════════
        print("\n=== SECTION 3: Student Profile ===")
        # ═══════════════════════════════════════════════════
        r = await c.get(f"/api/v2/students/{sid}", headers=student_h)
        ok("GET /student") if r.status_code == 200 else fail("GET /student")

        r = await c.get(f"/api/v2/students/{sid}/mastery", headers=student_h)
        ok(f"GET /mastery ({len(r.json())} mastered)") if r.status_code == 200 else fail("GET /mastery")

        r = await c.get(f"/api/v2/students/{sid}/analytics", headers=student_h)
        ok("GET /analytics") if r.status_code == 200 else fail("GET /analytics")

        r = await c.get(f"/api/v2/students/{sid}/sessions", headers=student_h)
        ok("GET /sessions") if r.status_code == 200 else fail("GET /sessions")

        r = await c.get(f"/api/v2/students/{sid}/badges", headers=student_h)
        ok("GET /badges") if r.status_code == 200 else fail("GET /badges")

        r = await c.get(f"/api/v2/students/{sid}/card-history", headers=student_h)
        ok("GET /card-history") if r.status_code == 200 else fail("GET /card-history")

        r = await c.get(f"/api/v2/students/{sid}/review-due", headers=student_h)
        ok("GET /review-due") if r.status_code == 200 else fail("GET /review-due")

        r = await c.get("/api/v2/leaderboard", headers=student_h)
        ok("GET /leaderboard") if r.status_code == 200 else fail("GET /leaderboard")

        r = await c.get("/api/v2/concepts/business_statistics_1.0/readiness",
                        params={"student_id": sid, "book_slug": "business_statistics"}, headers=student_h)
        ok(f"GET /readiness (met={r.json().get('all_prerequisites_met')})") if r.status_code == 200 else fail("GET /readiness")

        # ═══════════════════════════════════════════════════
        print("\n=== SECTION 4: Admin Dashboard & Management ===")
        # ═══════════════════════════════════════════════════
        r = await c.get("/api/admin/dashboard", headers=admin_h)
        ok("GET /admin/dashboard") if r.status_code == 200 else fail(f"GET /dashboard {r.status_code}")

        r = await c.get("/api/admin/students", headers=admin_h)
        ok("GET /admin/students") if r.status_code == 200 else fail("GET /admin/students")

        r = await c.get(f"/api/admin/students/{sid}", headers=admin_h)
        ok("GET /admin/students/id") if r.status_code == 200 else fail("GET /admin/students/id")

        r = await c.get("/api/admin/sessions", headers=admin_h)
        ok("GET /admin/sessions") if r.status_code == 200 else fail(f"GET /admin/sessions {r.status_code}")

        r = await c.get("/api/admin/analytics", headers=admin_h)
        ok("GET /admin/analytics") if r.status_code == 200 else fail(f"GET /admin/analytics {r.status_code}")

        r = await c.get("/api/admin/users", headers=admin_h)
        ok("GET /admin/users") if r.status_code == 200 else fail("GET /admin/users")

        r = await c.get("/api/admin/config", headers=admin_h)
        ok("GET /admin/config") if r.status_code == 200 else fail("GET /admin/config")

        r = await c.get("/api/admin/subjects", headers=admin_h)
        ok("GET /admin/subjects") if r.status_code == 200 else fail("GET /admin/subjects")

        r = await c.get("/api/admin/books", headers=admin_h)
        ok("GET /admin/books") if r.status_code == 200 else fail("GET /admin/books")

        r = await c.get("/api/admin/books/business_statistics/sections", headers=admin_h)
        ok("GET /admin/sections") if r.status_code == 200 else fail(f"GET /sections {r.status_code}")

        r = await c.get("/api/admin/books/business_statistics/chunks/business_statistics_1.0", headers=admin_h)
        ok("GET /admin/chunks/1.0") if r.status_code == 200 else fail(f"GET /chunks {r.status_code}")

        r = await c.get("/api/admin/books/business_statistics/graph", headers=admin_h)
        ok("GET /admin/graph") if r.status_code == 200 else fail(f"GET /graph {r.status_code}")

        r = await c.get("/api/admin/graph/business_statistics/edges", headers=admin_h)
        ok("GET /admin/graph/edges") if r.status_code == 200 else fail(f"GET /edges {r.status_code}")

        r = await c.get("/api/admin/graph/business_statistics/overrides", headers=admin_h)
        ok("GET /admin/graph/overrides") if r.status_code == 200 else fail(f"GET /overrides {r.status_code}")

        # ═══════════════════════════════════════════════════
        print("\n=== SECTION 5: Complete Chapter 1.0 (mastery fix test) ===")
        # ═══════════════════════════════════════════════════
        # Clear previous mastery
        await c.delete(f"/api/admin/students/{sid}/mastery/business_statistics_1.0", headers=admin_h)

        r = await c.post("/api/v2/sessions", json={
            "student_id": sid, "concept_id": "business_statistics_1.0",
            "book_slug": "business_statistics", "style": "default", "lesson_interests": []
        }, headers=student_h)
        if r.status_code != 200:
            fail(f"POST /sessions {r.status_code}: {r.text[:150]}")
        else:
            session_id = r.json()["id"]
            ok(f"POST /sessions (id={session_id[:8]})")

            r = await c.get(f"/api/v2/sessions/{session_id}/chunks", headers=student_h)
            chunks = r.json().get("chunks", [])
            ok(f"GET /chunks ({len(chunks)} chunks)") if r.status_code == 200 else fail("GET /chunks")

            if chunks:
                chunk_id = chunks[0]["chunk_id"]
                r = await c.post(f"/api/v2/sessions/{session_id}/chunk-cards",
                                 json={"chunk_id": chunk_id}, headers=student_h, timeout=120)
                if r.status_code == 200:
                    cards = r.json().get("cards", [])
                    questions = r.json().get("questions", [])
                    ok(f"POST /chunk-cards ({len(cards)} cards, {len(questions)} Qs)")
                else:
                    fail(f"POST /chunk-cards {r.status_code}")

                r = await c.post(f"/api/v2/sessions/{session_id}/complete-chunk", json={
                    "chunk_id": chunk_id, "correct": 1, "total": 1, "mode_used": "NORMAL"
                }, headers=student_h)
                if r.status_code == 200:
                    data = r.json()
                    ok(f"POST /complete-chunk (score={data.get('score')}, all_complete={data.get('all_study_complete')})")
                    if data.get("all_study_complete"):
                        ok("all_study_complete=True")
                    else:
                        fail("all_study_complete=False (expected True)")
                else:
                    fail(f"POST /complete-chunk {r.status_code}: {r.text[:150]}")

                # Verify mastery
                r = await c.get(f"/api/v2/students/{sid}/mastery", headers=student_h)
                mastery_data = r.json()
                mastered = mastery_data if isinstance(mastery_data, list) else mastery_data.get("mastered", [])
                mastered = [m.get("concept_id") if isinstance(m, dict) else m for m in mastered]
                if "business_statistics_1.0" in mastered:
                    ok("StudentMastery CREATED for 1.0")
                else:
                    fail(f"StudentMastery NOT found (mastered: {mastered})")

                # Verify 1.1 unlocked
                r = await c.get("/api/v2/concepts/business_statistics_1.1/readiness",
                                params={"student_id": sid, "book_slug": "business_statistics"}, headers=student_h)
                if r.status_code == 200 and r.json().get("all_prerequisites_met"):
                    ok("Concept 1.1 UNLOCKED")
                else:
                    fail("Concept 1.1 still locked")

        # ═══════════════════════════════════════════════════
        print("\n=== SECTION 6: Admin Content Controls ===")
        # ═══════════════════════════════════════════════════
        r = await c.get("/api/admin/books/business_statistics/chunks/business_statistics_1.1", headers=admin_h)
        if r.status_code == 200:
            admin_chunks = r.json() if isinstance(r.json(), list) else r.json().get("chunks", [])
            if admin_chunks:
                tc_id = str(admin_chunks[0].get("id", ""))
                ok(f"Got test chunk: {tc_id[:8]}")

                # Hide
                r = await c.patch(f"/api/admin/chunks/{tc_id}/visibility", json={"is_hidden": True}, headers=admin_h)
                ok("Hide chunk") if r.status_code == 200 else fail(f"Hide chunk {r.status_code}: {r.text[:100]}")

                # Unhide
                r = await c.patch(f"/api/admin/chunks/{tc_id}/visibility", json={"is_hidden": False}, headers=admin_h)
                ok("Unhide chunk (reversed)") if r.status_code == 200 else fail(f"Unhide {r.status_code}")

                # Exam disable
                r = await c.patch(f"/api/admin/chunks/{tc_id}/exam-gate", json={"exam_disabled": True}, headers=admin_h)
                ok("Disable exam") if r.status_code == 200 else fail(f"Disable exam {r.status_code}")

                r = await c.patch(f"/api/admin/chunks/{tc_id}/exam-gate", json={"exam_disabled": False}, headers=admin_h)
                ok("Enable exam (reversed)") if r.status_code == 200 else fail(f"Enable exam {r.status_code}")

                # Optional
                r = await c.patch(f"/api/admin/chunks/{tc_id}", json={"is_optional": True}, headers=admin_h)
                ok("Set optional") if r.status_code == 200 else fail(f"Set optional {r.status_code}")

                r = await c.patch(f"/api/admin/chunks/{tc_id}", json={"is_optional": False}, headers=admin_h)
                ok("Unset optional (reversed)") if r.status_code == 200 else fail(f"Unset optional {r.status_code}")
            else:
                fail("No chunks for 1.1")
        else:
            fail(f"GET admin chunks {r.status_code}")

        # Section-level
        concept = "business_statistics_1.1"
        bs = "business_statistics"

        r = await c.patch(f"/api/admin/sections/{concept}/visibility", json={"is_hidden": True, "book_slug": bs}, headers=admin_h)
        ok("Section hide") if r.status_code == 200 else fail(f"Section hide {r.status_code}: {r.text[:100]}")

        r = await c.patch(f"/api/admin/sections/{concept}/visibility", json={"is_hidden": False, "book_slug": bs}, headers=admin_h)
        ok("Section unhide (reversed)") if r.status_code == 200 else fail(f"Section unhide {r.status_code}")

        r = await c.patch(f"/api/admin/sections/{concept}/optional", json={"is_optional": True, "book_slug": bs}, headers=admin_h)
        ok("Section optional") if r.status_code == 200 else fail(f"Section optional {r.status_code}: {r.text[:100]}")

        r = await c.patch(f"/api/admin/sections/{concept}/optional", json={"is_optional": False, "book_slug": bs}, headers=admin_h)
        ok("Section not-optional (reversed)") if r.status_code == 200 else fail(f"Section unoptional {r.status_code}")

        r = await c.patch(f"/api/admin/sections/{concept}/exam-gate", json={"disabled": True, "book_slug": bs}, headers=admin_h)
        ok("Section exam disable") if r.status_code == 200 else fail(f"Section exam {r.status_code}: {r.text[:100]}")

        r = await c.patch(f"/api/admin/sections/{concept}/exam-gate", json={"disabled": False, "book_slug": bs}, headers=admin_h)
        ok("Section exam enable (reversed)") if r.status_code == 200 else fail(f"Section exam reverse {r.status_code}")

        # ═══════════════════════════════════════════════════
        print("\n=== SECTION 7: Admin Mastery Grant/Revoke ===")
        # ═══════════════════════════════════════════════════
        r = await c.post(f"/api/admin/students/{sid}/mastery/business_statistics_1.1", headers=admin_h)
        ok("Grant mastery 1.1") if r.status_code in [200, 201] else fail(f"Grant mastery {r.status_code}: {r.text[:100]}")

        r = await c.get("/api/v2/concepts/business_statistics_1.2/readiness",
                        params={"student_id": sid, "book_slug": "business_statistics"}, headers=student_h)
        if r.status_code == 200 and r.json().get("all_prerequisites_met"):
            ok("1.2 unlocked after granting 1.1")
        else:
            fail("1.2 not unlocked")

        r = await c.delete(f"/api/admin/students/{sid}/mastery/business_statistics_1.1", headers=admin_h)
        ok("Revoke mastery 1.1") if r.status_code in [200, 204] else fail(f"Revoke {r.status_code}: {r.text[:100]}")

        r = await c.get("/api/v2/concepts/business_statistics_1.2/readiness",
                        params={"student_id": sid, "book_slug": "business_statistics"}, headers=student_h)
        if r.status_code == 200 and not r.json().get("all_prerequisites_met"):
            ok("1.2 locked again after revoking 1.1")
        else:
            fail("1.2 still unlocked after revoke")

        # ═══════════════════════════════════════════════════
        print("\n=== SECTION 8: Edge Cases ===")
        # ═══════════════════════════════════════════════════
        # Graph unchanged after hiding
        r_before = await c.get("/api/v1/graph/full", params={"book_slug": "business_statistics"})
        nodes_before = len(r_before.json().get("nodes", []))

        await c.patch(f"/api/admin/sections/business_statistics_1.1/visibility",
                      json={"is_hidden": True, "book_slug": bs}, headers=admin_h)
        r_after = await c.get("/api/v1/graph/full", params={"book_slug": "business_statistics"})
        nodes_after = len(r_after.json().get("nodes", []))

        if nodes_before == nodes_after:
            ok(f"Graph unchanged after hiding ({nodes_before} nodes)")
        else:
            fail(f"Graph changed: {nodes_before} -> {nodes_after}")

        # Unhide
        await c.patch(f"/api/admin/sections/business_statistics_1.1/visibility",
                      json={"is_hidden": False, "book_slug": bs}, headers=admin_h)

        # Book visibility
        r = await c.patch("/api/admin/books/business_statistics/visibility", json={"is_hidden": True}, headers=admin_h)
        ok("Hide book") if r.status_code == 200 else fail(f"Hide book {r.status_code}: {r.text[:100]}")

        r = await c.get("/api/v1/books")
        slugs = [b["slug"] for b in r.json()]
        if "business_statistics" not in slugs:
            ok("Hidden book not in student list")
        else:
            fail("Hidden book still visible")

        r = await c.patch("/api/admin/books/business_statistics/visibility", json={"is_hidden": False}, headers=admin_h)
        ok("Unhide book (reversed)") if r.status_code == 200 else fail(f"Unhide book {r.status_code}")

    # ═══════════════════════════════════════════════════
    print(f"\n{'=' * 50}")
    print(f"FINAL RESULTS: {PASS} PASS, {FAIL} FAIL")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(run_tests())
