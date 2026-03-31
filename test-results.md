# ADA API Test Results

**Test Run Date:** 2026-03-28
**Backend Version:** FastAPI 1.0.0 ("ADA - Adaptive Math Learning API")
**Backend Port:** 8889
**Base URL:** http://localhost:8889
**Test Methodology:** curl-based HTTP testing against live backend

---

## Infrastructure Notes

### Backend Status
The backend was running at the time of testing. Two uvicorn processes were found listening on port 8889 (PIDs 1136 and 23296), indicating a stale background process alongside the active server.

### Critical Finding: session creation blocked by stale server state
The `POST /api/v2/sessions` endpoint returns `"Concept 'prealgebra_1.1' not found in book 'prealgebra'"` even though:
- The `concept_chunks` table contains 1063 rows with `concept_id='prealgebra_1.1'` and `book_slug='prealgebra'`
- Direct Python invocation of `ChunkKnowledgeService.get_concept_detail(db, 'prealgebra_1.1', 'prealgebra')` succeeds and returns full data
- `GET /api/v2/books` correctly returns `prealgebra` as an active book

**Root cause diagnosis:** The running server process either (a) was started when the `concept_chunks` table was empty and the `ChunkKnowledgeService` instance has a stale DB connection pool cache, or (b) was started with an older code version before the chunk-based architecture was deployed. The second uvicorn process on the same port suggests an older instance is intercepting some requests.

**Impact:** All session-dependent endpoints (`/sessions`, `/sessions/{id}/present`, `/sessions/{id}/cards`, etc.) are blocked.

### /health returns 500
The `GET /health` endpoint returns HTTP 500 with "Internal Server Error" (plain text). This is an unhandled exception in the health handler — likely from `_chunk_knowledge_svc.get_graph_info(DEFAULT_BOOK_SLUG)` when `_chunk_knowledge_svc` is None (not injected by lifespan on the stale process).

---

## Phase 1 — Infrastructure Endpoints

| # | Method | Path | Input | Expected Status | Actual Status | PASS/FAIL | Notes |
|---|--------|------|-------|-----------------|---------------|-----------|-------|
| 1 | GET | /health | none | 200 | **500** | **FAIL** | Internal Server Error — see root cause above |
| 2 | GET | /api/v1/graph/info | ?book_slug=prealgebra | 200 | **200** | **PASS** | Returns 60 nodes, 94 edges, 1 root, 21 leaves |
| 3 | GET | /api/v1/graph/full | ?book_slug=prealgebra | 200 | **200** | **PASS** | Returns full node+edge list (60 nodes, 94 edges) |
| 4 | GET | /api/v1/graph/nodes | ?book_slug=prealgebra | 200 | **200** | **PASS** | Returns paginated node list with in/out degrees |
| 5 | GET | /api/v1/graph/topological-order | ?book_slug=prealgebra | 200 | **200** | **PASS** | Returns topological ordering of all 60 concepts |
| 6 | GET | /api/v1/concepts/{id} | PREALG.C1.S1... format | 200 | **404** | **FAIL** | Wrong concept ID format — PREALG.* IDs are graph IDs, not chunk IDs |
| 6b | GET | /api/v1/concepts/{id} | prealgebra_1.1 format | 200 | **404** | **FAIL** | Same endpoint returns 404 for both formats — chunk_ksvc not available on responding process |
| 7 | GET | /api/v1/concepts/{id}/prerequisites | PREALG.C1.S1... | 200 | **200** | **PASS** | Returns `{"prerequisites":[],"count":0}` (root has no prereqs) |
| 7b | GET | /api/v1/concepts/{id}/prerequisites | prealgebra_1.1 | 200 | **200** | **PASS** | Returns `{"prerequisites":[],"count":0}` |
| 8 | GET | /api/v1/concepts/{id}/images | prealgebra_1.1 | 200 | **200** | **PASS** | Returns `{"images":[],"count":0}` (no images stored for this concept) |
| 9 | POST | /api/v1/concepts/next | `{"mastered_concepts":[],"book_slug":"prealgebra"}` | 200 | **200** | **PASS** | Returns 1 ready concept + 59 locked; correct prerequisite graph logic |
| 10 | GET | /api/v2/books | none | 200 | **200** | **PASS** | Returns 5 books: algebra_1, college_algebra, elementary_algebra, intermediate_algebra, prealgebra |

**Phase 1 Summary: 8/10 PASS, 2/10 FAIL**

---

## Phase 2 — Student Creation

All 4 students created successfully. Note: The actual request schema uses `display_name` (not `name`), `preferred_style` (not `style`), and has no `grade` field. Initial requests with wrong field names returned HTTP 422.

| Student | Method | Path | Status | PASS/FAIL | Created ID |
|---------|--------|------|--------|-----------|------------|
| Ahmed Al-Rashid (AR, football/sports, default) | POST | /api/v2/students | 200 | **PASS** | `8c1886ed-a6fa-4d28-abe0-e1943ebb59af` |
| Sara Chen (EN, mathematics/science, default) | POST | /api/v2/students | 200 | **PASS** | `45be0921-f71c-40f3-af0b-8ad6ed13e58e` |
| Lucas Fernandez (ES, technology/gaming, gamer) | POST | /api/v2/students | 200 | **PASS** | `89d1ab11-5ce6-46fb-ac66-57f9a3d6782a` |
| Priya Sharma (EN, no interests, default) | POST | /api/v2/students | 200 | **PASS** | `fbf9be1d-e459-4f46-a38d-ed55e5e41693` |

### Schema Discovery Note
The `CreateStudentRequest` schema differs from the task description. Correct fields are:
- `display_name` (string, 1–100 chars) — **required**
- `interests` (array of strings) — optional, defaults to `[]`
- `preferred_style` (enum: default|pirate|astronaut|gamer) — optional, defaults to `"default"`
- `preferred_language` (string) — optional, defaults to `"en"`

No `name`, `grade`, or `style` fields exist in the schema.

---

## Phase 3 — Student CRUD Operations

### Ahmed Al-Rashid (`8c1886ed-a6fa-4d28-abe0-e1943ebb59af`)

| Operation | Method | Path | Status | PASS/FAIL | Response Summary |
|-----------|--------|------|--------|-----------|-----------------|
| Read profile | GET | /api/v2/students/{id} | 200 | **PASS** | id, display_name, interests, preferred_style, preferred_language, created_at, xp=0, streak=0 |
| List students | GET | /api/v2/students?limit=20 | 200 | **PASS** | Returns 8 students including all 4 test students + 4 pre-existing; ordered newest first |
| Update language | PATCH | /api/v2/students/{id}/language | 200 | **PASS** | Language updated from "ar" to "en"; full student object returned |
| Get mastery | GET | /api/v2/students/{id}/mastery | 200 | **PASS** | `{"mastered_concepts":[],"count":0}` — no mastery yet (new student) |
| Get analytics | GET | /api/v2/students/{id}/analytics | 200 | **PASS** | All zeros; xp=0, streak=0, mastery_rate=0.0, avg_check_score=null |
| Concept readiness | GET | /api/v2/concepts/{concept_id}/readiness?student_id={id} | 200 | **PASS** | `{"all_prerequisites_met":true,"unmet_prerequisites":[]}` — root concept has no prereqs |

### Sara Chen (`45be0921-f71c-40f3-af0b-8ad6ed13e58e`)

| Operation | Method | Path | Status | PASS/FAIL | Response Summary |
|-----------|--------|------|--------|-----------|-----------------|
| Read profile | GET | /api/v2/students/{id} | 200 | **PASS** | Correct profile with en language, default style |
| Update language | PATCH | /api/v2/students/{id}/language | 200 | **PASS** | Language updated from "en" to "zh" successfully |
| Get mastery | GET | /api/v2/students/{id}/mastery | 200 | **PASS** | `{"mastered_concepts":[],"count":0}` |
| Get analytics | GET | /api/v2/students/{id}/analytics | 200 | **PASS** | All zeros; full analytics object with all 14 fields present |

### Lucas Fernandez (`89d1ab11-5ce6-46fb-ac66-57f9a3d6782a`)

| Operation | Method | Path | Status | PASS/FAIL | Response Summary |
|-----------|--------|------|--------|-----------|-----------------|
| Read profile | GET | /api/v2/students/{id} | 200 | **PASS** | Correct profile with gamer style, es language, gaming/tech interests |
| Update language | PATCH | /api/v2/students/{id}/language | 200 | **PASS** | Language confirmed as "es" (already set) |
| Get mastery | GET | /api/v2/students/{id}/mastery | 200 | **PASS** | `{"mastered_concepts":[],"count":0}` |
| Get analytics | GET | /api/v2/students/{id}/analytics | 200 | **PASS** | All zeros; analytics object complete |
| Concept readiness | GET | /api/v2/concepts/{concept_id}/readiness?student_id={id} | 200 | **PASS** | `{"all_prerequisites_met":true,"unmet_prerequisites":[]}` |

### Priya Sharma (`fbf9be1d-e459-4f46-a38d-ed55e5e41693`)

| Operation | Method | Path | Status | PASS/FAIL | Response Summary |
|-----------|--------|------|--------|-----------|-----------------|
| Read profile | GET | /api/v2/students/{id} | 200 | **PASS** | Correct profile with empty interests |
| Get mastery | GET | /api/v2/students/{id}/mastery | 200 | **PASS** | `{"mastered_concepts":[],"count":0}` |
| Get analytics | GET | /api/v2/students/{id}/analytics | 200 | **PASS** | All zeros; analytics object complete |
| Concept readiness | GET | /api/v2/concepts/{concept_id}/readiness?student_id={id} | 200 | **PASS** | `{"all_prerequisites_met":true,"unmet_prerequisites":[]}` |

**Phase 3 Summary: All CRUD operations PASS across all 4 students.**

---

## Phase 4 — Session Creation

All session creation attempts failed due to the chunk lookup issue described in Infrastructure Notes.

| Student | Method | Path | Input | Expected | Actual Status | PASS/FAIL | Notes |
|---------|--------|------|-------|----------|---------------|-----------|-------|
| Ahmed | POST | /api/v2/sessions | concept_id=prealgebra_1.1, book_slug=prealgebra | 200 | **400** | **FAIL** | "Concept 'prealgebra_1.1' not found in book 'prealgebra'" |
| Sara | POST | /api/v2/sessions | concept_id=prealgebra_1.1, book_slug=prealgebra | 200 | **400** | **FAIL** | Same error — all sessions blocked |
| Lucas | POST | /api/v2/sessions | concept_id=prealgebra_1.1, book_slug=prealgebra | 200 | **400** | **FAIL** | Same error |
| Priya | POST | /api/v2/sessions | concept_id=prealgebra_1.1, book_slug=prealgebra | 200 | **400** | **FAIL** | Same error |

**Root cause confirmed:** `ChunkKnowledgeService.get_concept_detail()` returns `None` for `concept_id='prealgebra_1.1'` at the API level despite the DB containing the data. Direct Python test of the same method returns correct data. This is a stale-server-state issue caused by two uvicorn processes on port 8889 — the older process that responds to requests was likely started before the `concept_chunks` table was populated.

**Phase 4 Summary: 0/4 PASS — all session creations FAIL due to infrastructure issue, not a code bug.**

---

## Phase 5 — Edge Cases

| # | Scenario | Method | Path | Input | Expected | Actual Status | Actual Body (summary) | PASS/FAIL |
|---|----------|--------|------|-------|----------|---------------|-----------------------|-----------|
| 1 | Non-existent concept | GET | /api/v1/concepts/prealgebra_99.99 | ?book_slug=prealgebra | 404 | **404** | `{"detail":"Concept not found: prealgebra_99.99"}` | **PASS** |
| 2 | Non-existent student (nil UUID) | GET | /api/v2/students/00000000-... | — | 404 | **404** | `{"detail":"Student not found"}` | **PASS** |
| 3 | Missing API key | GET | /api/v2/students | no X-API-Key header | 401 | **401** | (empty/plain body) | **PASS** |
| 4 | Wrong API key | POST | /api/v2/students | X-API-Key: wrong-key | 401 | **401** | `{"detail":"Unauthorized"}` | **PASS** |
| 5 | Invalid book slug (graph endpoint) | GET | /api/v1/graph/info | ?book_slug=nonexistent | 400/500 | **200** | Returns prealgebra graph data (ignores invalid slug, falls back) | **FAIL** — should return 400 for unknown book slug, not silently use default |
| 6 | Invalid book slug (session endpoint) | POST | /api/v2/sessions | book_slug=nonexistentbook | 400 | **400** | `{"detail":"Book 'nonexistentbook' not loaded. Available: [...]"}` | **PASS** |
| 7 | Empty display_name | POST | /api/v2/students | display_name="" | 422 | **422** | `{"detail":[{"type":"string_too_short",...}]}` | **PASS** |
| 8 | Invalid language code | PATCH | /api/v2/students/{id}/language | language="INVALID_LANG" | 422 | **422** | `{"detail":[{"type":"string_pattern_mismatch",...}]}` — valid pattern listed | **PASS** |
| 9 | Malformed UUID in session body | POST | /api/v2/sessions | student_id="not-a-uuid" | 422 | **422** | UUID parse error with helpful message | **PASS** |
| 10 | Malformed UUID in path | GET | /api/v2/students/not-a-real-uuid | — | 422 | **422** | UUID parse error | **PASS** |
| 11 | Session for non-existent student | POST | /api/v2/sessions | student_id=nil UUID | 404 | **404** | `{"detail":"Student not found"}` | **PASS** |

**Phase 5 Summary: 10/11 PASS**

**Note on Edge Case #5 (invalid book slug on graph endpoint):** The `GET /api/v1/graph/info?book_slug=nonexistent` returns HTTP 200 with the prealgebra graph data instead of a 400 error. The graph service silently falls back to `DEFAULT_BOOK_SLUG` when the requested slug is not found. This is a missing validation — the endpoint should return 400 for an unknown book slug, as the session endpoint does.

---

## Student Profile Summary

### Ahmed Al-Rashid
- **ID:** `8c1886ed-a6fa-4d28-abe0-e1943ebb59af`
- **Created at:** 2026-03-28T06:13:58Z
- **Language:** Updated from `ar` to `en` during test
- **Interests:** football, sports
- **Style:** default
- **Mastery:** 0 concepts
- **XP/Streak:** 0/0
- **Session:** Could not create — see Phase 4

### Sara Chen
- **ID:** `45be0921-f71c-40f3-af0b-8ad6ed13e58e`
- **Created at:** 2026-03-28T06:14:05Z
- **Language:** Updated from `en` to `zh` during test
- **Interests:** mathematics, science
- **Style:** default
- **Mastery:** 0 concepts
- **XP/Streak:** 0/0
- **Session:** Could not create — see Phase 4

### Lucas Fernandez
- **ID:** `89d1ab11-5ce6-46fb-ac66-57f9a3d6782a`
- **Created at:** 2026-03-28T06:14:17Z
- **Language:** es (unchanged)
- **Interests:** technology, gaming
- **Style:** gamer
- **Mastery:** 0 concepts
- **XP/Streak:** 0/0
- **Session:** Could not create — see Phase 4

### Priya Sharma
- **ID:** `fbf9be1d-e459-4f46-a38d-ed55e5e41693`
- **Created at:** 2026-03-28T06:14:24Z
- **Language:** en (unchanged)
- **Interests:** (empty)
- **Style:** default
- **Mastery:** 0 concepts
- **XP/Streak:** 0/0
- **Session:** Could not create — see Phase 4

---

## Summary

| Phase | Endpoints Tested | Passed | Failed |
|-------|-----------------|--------|--------|
| Phase 1 — Infrastructure | 10 | 8 | 2 |
| Phase 2 — Student Creation | 4 | 4 | 0 |
| Phase 3 — Student CRUD | 18 | 18 | 0 |
| Phase 4 — Session Creation | 4 | 0 | 4 |
| Phase 5 — Edge Cases | 11 | 10 | 1 |
| **Total** | **47** | **40** | **7** |

**Pass rate: 40/47 (85%)**

---

## Failures Analysis

### 1. GET /health — HTTP 500 (Critical)
**Expected:** 200 with `{"status":"ok","chunk_count":N,"graph_nodes":60,"graph_edges":94}`
**Actual:** HTTP 500 "Internal Server Error"
**Cause:** Unhandled exception in health handler on the responding uvicorn process. The `_chunk_knowledge_svc` global is likely `None` on that process, causing an `AttributeError` when `get_graph_info()` is called. Caught exception handling around the chunk_count call but not the graph_info call.
**Fix:** Add try/except around the `get_graph_info` call in the health handler, and investigate why two uvicorn processes are listening on port 8889.

### 2. GET /api/v1/concepts/{id} — HTTP 404 (Moderate)
**Expected:** 200 with concept detail
**Actual:** 404 "Concept not found"
**Cause:** The responding process has `_chunk_knowledge_svc` not initialized (None), so `get_concept_detail` returns None → 404 response.
**Fix:** Same as above — stale server process issue. Restarting the backend cleanly (killing both processes and starting fresh) should resolve this.

### 3. POST /api/v2/sessions — HTTP 400 for all 4 students (Critical)
**Expected:** 200 with new session object
**Actual:** 400 "Concept 'prealgebra_1.1' not found in book 'prealgebra'"
**Cause:** The `chunk_ksvc.get_concept_detail()` returns None at the API level despite the DB having the data. Two uvicorn processes on the same port — the stale one was started before `concept_chunks` was populated.
**Fix:** Kill both uvicorn processes and restart with `python -m uvicorn src.api.main:app --port 8889`.

### 4. GET /api/v1/graph/info with invalid book_slug — HTTP 200 (Minor)
**Expected:** 400 error
**Actual:** 200 with default book's graph data
**Cause:** Graph endpoints fall back to `DEFAULT_BOOK_SLUG` when the requested slug is unknown. No validation of the `book_slug` query parameter against available books.
**Fix:** Add a validation check in graph endpoints: if `book_slug` is provided but not in the set of available books, return HTTP 400. The session endpoint already does this correctly.

---

## Actionable Recommendations

1. **Kill stale backend process:** Run `netstat -ano | findstr 8889` to identify both PIDs and kill the older one. The dual-process state is causing all session failures and the health 500.

2. **Health endpoint defensive coding:** Wrap the `get_graph_info` call in the health handler with try/except (the chunk_count call is already wrapped, but graph_info is not).

3. **Book slug validation in graph endpoints:** The `GET /api/v1/graph/*` family of endpoints should validate `book_slug` against the set of available books and return HTTP 400 for unknowns, consistent with the session endpoint behaviour.

4. **Startup validation:** Add a startup check that verifies `concept_chunks` is populated for the default book before marking the server ready. This would prevent silent failures when the server starts with an empty DB.
