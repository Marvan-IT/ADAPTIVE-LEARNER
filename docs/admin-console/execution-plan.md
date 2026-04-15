# Execution Plan — Admin Console + Simplified Registration

**Feature slug:** `admin-console`
**Date:** 2026-04-13
**Status:** Approved for implementation

---

## 1. Work Breakdown Structure (WBS)

### Stage 0 — Infrastructure (`devops-engineer`)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P0-01 | Migration 011: age column | `011_add_age_to_students.py` — add nullable `age INTEGER` to `students` | 0.25d | None | `alembic/versions/` |
| P0-02 | Migration 012: content controls | `012_add_content_control_columns.py` — `is_hidden`, `exam_disabled`, `admin_section_name` on `concept_chunks`; `admin_graph_overrides` table; `admin_config` table; `is_active` on `students` | 0.5d | P0-01 | `alembic/versions/` |
| P0-03 | ORM models: age + is_active | Add `age`, `is_active` mapped columns to `Student` in `models.py` | 0.25d | P0-01 | `db/models.py` |
| P0-04 | ORM models: chunk control + admin tables | Add `is_hidden`, `exam_disabled`, `admin_section_name` to `ConceptChunk`; add `AdminGraphOverride`, `AdminConfig` classes | 0.5d | P0-02 | `db/models.py` |
| P0-05 | Test fixtures | Add `admin_user`, `test_student_with_session`, `test_chunks` fixtures to `conftest.py` | 0.5d | P0-03, P0-04 | `tests/conftest.py` |
| P0-06 | Verify migrations | Run `alembic upgrade head` against a fresh DB; verify all columns and tables created correctly | 0.25d | P0-02 | `alembic/` |

**Stage 0 total: ~2.25 dev-days**

---

### Stage 1 — Design (`solution-architect`) ✅ COMPLETE

This document is the output of Stage 1.

---

### Stage 2 — Backend (`backend-developer`)

#### 2a. Simplify Registration

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P2a-01 | Remove interests/style from RegisterRequest | `auth/schemas.py` — remove `interests` + `preferred_style` from `RegisterRequest`; add optional `age: int \| None` | 0.25d | P0-03 | `auth/schemas.py` |
| P2a-02 | Update Student constructor | `auth/service.py` line ~87-93 — pass `age=body.age`, keep `interests=[]`, `preferred_style="default"` defaults | 0.25d | P2a-01 | `auth/service.py` |
| P2a-03 | Add age to StudentResponse | `teaching_schemas.py` — add `age: int \| None` field to `StudentResponse` | 0.25d | P0-03 | `teaching_schemas.py` |

**2a total: ~0.75 dev-days**

#### 2b. Graph Cache Thread Safety

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P2b-01 | Add threading.Lock | `chunk_knowledge_service.py` — add `_graph_lock = threading.Lock()`; wrap `_graph_cache` reads/writes in `_load_graph()` | 0.5d | None | `chunk_knowledge_service.py` |
| P2b-02 | Add reload_graph_with_overrides() | New async function: loads `graph.json`, applies DB overrides, replaces cache atomically under Lock | 0.5d | P0-04, P2b-01 | `chunk_knowledge_service.py` |
| P2b-03 | Add _apply_overrides() | Pure helper function (no I/O) that applies override list to a DiGraph copy | 0.25d | P2b-02 | `chunk_knowledge_service.py` |

**2b total: ~1.25 dev-days**

#### 2c. Admin Dashboard, Students, Sessions, Analytics

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P2c-01 | GET /api/admin/dashboard | Platform stats: total students, active sessions, mastery completions today, avg accuracy, books published | 0.5d | P0-03 | `admin_router.py` |
| P2c-02 | GET /api/admin/students (list) | Search (ILIKE), sort, paginate, is_active filter; JOIN to users table for email | 0.75d | P0-03 | `admin_router.py` |
| P2c-03 | GET /api/admin/students/{id} (detail) | Full profile, mastery list, recent sessions, adaptive stats | 0.5d | P0-03 | `admin_router.py` |
| P2c-04 | PATCH /api/admin/students/{id} | Update display_name, preferred_language, preferred_style, age | 0.25d | P0-03 | `admin_router.py` |
| P2c-05 | PATCH /api/admin/students/{id}/access | Toggle is_active | 0.25d | P0-02 | `admin_router.py` |
| P2c-06 | DELETE /api/admin/students/{id} | Soft-delete (set is_active=false) | 0.25d | P0-02 | `admin_router.py` |
| P2c-07 | POST /api/admin/students/{id}/reset-password | Write bcrypt hash to users.hashed_password | 0.25d | None | `admin_router.py` |
| P2c-08 | POST /api/admin/students/{id}/mastery/{concept_id} | Insert StudentMastery row (manual); 409 guard | 0.25d | None | `admin_router.py` |
| P2c-09 | DELETE /api/admin/students/{id}/mastery/{concept_id} | Delete StudentMastery row | 0.25d | None | `admin_router.py` |
| P2c-10 | GET /api/admin/sessions | List with filter by student/book/phase/date range; paginated | 0.5d | None | `admin_router.py` |
| P2c-11 | GET /api/admin/analytics | Concept difficulty, mastery rates, student accuracy bands, daily mastery (last 30d) | 1.0d | None | `admin_router.py` |

**2c total: ~4.75 dev-days**

#### 2d. Admin User Management and Config

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P2d-01 | GET /api/admin/users | List users filtered by role | 0.25d | None | `admin_router.py` |
| P2d-02 | POST /api/admin/users/create-admin | Create user with role=admin; hash password; 409 guard | 0.5d | None | `admin_router.py` |
| P2d-03 | PATCH /api/admin/users/{id}/role | Promote/demote; guard against demoting last admin | 0.5d | None | `admin_router.py` |
| P2d-04 | GET /api/admin/config | Return all admin_config rows | 0.25d | P0-04 | `admin_router.py` |
| P2d-05 | PATCH /api/admin/config | Upsert config keys; validate against ALLOWED_CONFIG_KEYS | 0.5d | P0-04 | `admin_router.py`, `config.py` |

**2d total: ~2.0 dev-days**

#### 2e. Chunk Operations

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P2e-01 | PATCH /api/admin/chunks/{id} | Full chunk edit; null embedding when text changes; return embedding_stale | 0.5d | P0-04 | `admin_router.py` |
| P2e-02 | PATCH /api/admin/chunks/{id}/visibility | Toggle is_hidden | 0.25d | P0-04 | `admin_router.py` |
| P2e-03 | PATCH /api/admin/chunks/{id}/exam-gate | Toggle exam_disabled | 0.25d | P0-04 | `admin_router.py` |
| P2e-04 | POST /api/admin/chunks/merge | Merge algorithm + chunk_progress migration + image transfer; atomic transaction | 1.5d | P0-04 | `admin_router.py` |
| P2e-05 | POST /api/admin/chunks/{id}/split | Split algorithm + chunk_progress copy + re-sequence; atomic transaction | 1.5d | P0-04 | `admin_router.py` |
| P2e-06 | PUT /api/admin/concepts/{id}/reorder | Validate full chunk ID set; bulk update order_index | 0.5d | None | `admin_router.py` |
| P2e-07 | POST /api/admin/chunks/{id}/regenerate-embedding | Single chunk: OpenAI call → UPDATE embedding | 0.5d | None | `admin_router.py` |
| P2e-08 | POST /api/admin/concepts/{id}/regenerate-embeddings | Batch: stale-only; sequential with 100ms delay; 3 retries per chunk | 0.75d | P2e-07 | `admin_router.py` |

**2e total: ~5.75 dev-days**

#### 2f. Section Controls

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P2f-01 | PATCH /api/admin/sections/{concept_id}/rename | Bulk UPDATE admin_section_name for section | 0.25d | P0-04 | `admin_router.py` |
| P2f-02 | PATCH /api/admin/sections/{concept_id}/optional | Bulk toggle is_optional for section | 0.25d | P0-04 | `admin_router.py` |
| P2f-03 | PATCH /api/admin/sections/{concept_id}/exam-gate | Bulk toggle exam_disabled for section | 0.25d | P0-04 | `admin_router.py` |

**2f total: ~0.75 dev-days**

#### 2g. Prerequisite Graph Editing

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P2g-01 | GET /api/admin/graph/{slug}/edges | Return all edges with override flag | 0.25d | P2b-01 | `admin_router.py` |
| P2g-02 | GET /api/admin/graph/{slug}/overrides | Return admin_graph_overrides rows | 0.25d | P0-04 | `admin_router.py` |
| P2g-03 | POST /api/admin/graph/{slug}/edges | Add/remove edge; cycle detection; INSERT override; reload graph | 0.75d | P2b-02, P0-04 | `admin_router.py` |
| P2g-04 | DELETE /api/admin/graph/{slug}/overrides/{id} | DELETE override; reload graph | 0.5d | P2b-02 | `admin_router.py` |

**2g total: ~1.75 dev-days**

#### 2h. Teaching Flow Modifications

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P2h-01 | get_chunks_for_concept() — is_hidden filter | Add `include_hidden=False` parameter; add `.where(is_hidden == False)` for student queries | 0.5d | P0-04 | `chunk_knowledge_service.py` |
| P2h-02 | _chunk_to_dict() — new fields | Add `is_hidden`, `exam_disabled`, `admin_section_name`, `embedding_stale` to returned dict | 0.25d | P0-04 | `chunk_knowledge_service.py` |
| P2h-03 | all_study_complete — exclude hidden + optional | Update completion check to only require study_required_chunks | 0.5d | P2h-01, P2h-02 | `teaching_router.py` |
| P2h-04 | Exam gate — skip exam_disabled chunks | Filter chunks for exam question generation; auto-pass if all chunks exam_disabled | 0.75d | P2h-01, P2h-02 | `teaching_router.py` |
| P2h-05 | admin_section_name coalescing in get_book_sections() | Return `admin_section_name` when set, else original `section` value | 0.25d | P0-04 | `admin_router.py` |

**2h total: ~2.25 dev-days**

#### 2i. Merge/Split Conflict Handling (part of 2e — highlighted separately)

The merge and split algorithms (P2e-04, P2e-05) include conflict handling as specified in M1 and M8. No separate tasks needed — they are integral to the implementation of those endpoints.

---

**Stage 2 total: ~19.25 dev-days**

---

### Stage 3 — Testing (`comprehensive-tester`)

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P3-01 | test_admin_registration.py | RegisterRequest schema; age field; no interests/style | 0.5d | P2a-01, P2a-02 |
| P3-02 | test_admin_students.py | CRUD, search, sort, paginate, access toggle | 1.0d | P2c-01–P2c-07 |
| P3-03 | test_admin_mastery.py | Manual mark/unmark; 409 duplicate guard | 0.5d | P2c-08, P2c-09 |
| P3-04 | test_admin_sessions.py | List + filter combinations | 0.5d | P2c-10 |
| P3-05 | test_admin_analytics.py | Dashboard stats correctness; accuracy bands | 0.75d | P2c-01, P2c-11 |
| P3-06 | test_admin_user_mgmt.py | Create admin; promote/demote; last-admin guard | 0.5d | P2d-01–P2d-03 |
| P3-07 | test_admin_config.py | Read; write allowlisted keys; reject unknown key | 0.5d | P2d-04, P2d-05 |
| P3-08 | test_admin_chunks.py | Edit; visibility; exam gate; reorder | 0.75d | P2e-01–P2e-03, P2e-06 |
| P3-09 | test_admin_merge_split.py | Merge validation; M8 guard; split index bounds; chunk_progress migration; active_sessions count | 1.5d | P2e-04, P2e-05 |
| P3-10 | test_admin_embedding_regen.py | Single chunk; batch stale-only; OpenAI mock | 0.75d | P2e-07, P2e-08 |
| P3-11 | test_admin_sections.py | Rename; optional toggle; exam gate toggle; all-chunks-updated | 0.5d | P2f-01–P2f-03 |
| P3-12 | test_admin_graph.py | Add edge; remove edge; cycle rejection; override persistence; reload | 1.0d | P2g-01–P2g-04 |
| P3-13 | test_admin_thread_safety.py | Concurrent graph reload via threading; no cache corruption | 0.5d | P2b-01–P2b-03 |
| P3-14 | test_admin_teaching_integration.py | Hidden chunks absent from student query; exam_disabled auto-pass; all_study_complete logic | 1.0d | P2h-01–P2h-04 |

**Stage 3 total: ~10.25 dev-days**

---

### Stage 4 — Frontend (`frontend-developer`)

#### 4a. Simplify Registration

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P4a-01 | RegisterPage.jsx — remove fields | Remove interests tag input + preferred_style buttons | 0.25d | P2a-01 |
| P4a-02 | RegisterPage.jsx — add age | Add optional age number input; i18n key `register.age` | 0.25d | P4a-01 |

**4a total: ~0.5 dev-days**

#### 4b. API Client

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P4b-01 | admin.js — all new wrappers | Add ~28 new Axios wrapper functions per DLD section 11 | 1.0d | Stage 2 complete |

**4b total: ~1.0 dev-days**

#### 4c. Enhanced Admin Dashboard

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P4c-01 | AdminPage.jsx — stat cards | Add 6 stat cards at top using `getAdminDashboard()` | 0.5d | P4b-01, P2c-01 |
| P4c-02 | AdminPage.jsx — nav grid | Navigation tiles: Students, Sessions, Analytics, Content, Settings | 0.25d | P4c-01 |

**4c total: ~0.75 dev-days**

#### 4d. New Admin Pages

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P4d-01 | AdminStudentsPage.jsx | Search input, sort controls, paginated table, is_active filter badge; links to detail page | 1.0d | P4b-01, P2c-02 |
| P4d-02 | AdminStudentDetailPage.jsx | Editable profile form, access toggle, mastery table with mark/unmark, session history list, engagement JSON viewer | 1.5d | P4d-01, P2c-03–P2c-09 |
| P4d-03 | AdminSessionsPage.jsx | Session table, phase/book/date filters, pagination | 0.75d | P4b-01, P2c-10 |
| P4d-04 | AdminAnalyticsPage.jsx | Concept difficulty table (sortable), student accuracy band chart (CSS bars), daily mastery sparkline | 1.0d | P4b-01, P2c-11 |
| P4d-05 | AdminSettingsPage.jsx | Config form — one input per allowed key; save on submit; display last updated_by | 0.75d | P4b-01, P2d-04, P2d-05 |

**4d total: ~5.0 dev-days**

#### 4e. Enhanced AdminReviewPage (pre-publish)

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P4e-01 | Section controls in left panel | Pencil icon → rename modal; optional toggle; exam gate toggle | 0.75d | P4b-01, P2f-01–P2f-03 |
| P4e-02 | Chunk controls in center panel | Edit modal (heading + text); hide toggle; exam gate toggle; merge button (selects adjacent); split button (paragraph picker); reorder up/down arrows | 1.5d | P4b-01, P2e-01–P2e-06 |
| P4e-03 | Embedding stale indicator | Orange badge "Embedding stale" on chunk; "Regenerate" button | 0.5d | P4b-01, P2e-07 |
| P4e-04 | Graph editor in right panel | Edge table with delete button; add edge form (source/target selects); cycle warning message | 1.0d | P4b-01, P2g-01–P2g-04 |

**4e total: ~3.75 dev-days**

#### 4f. AdminBookContentPage (post-publish)

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P4f-01 | AdminBookContentPage.jsx | Same three-panel layout as enhanced ReviewPage; fetches published book chunks; includes "Regenerate All Stale" button | 1.25d | P4e-01–P4e-04, P2e-08 |

**4f total: ~1.25 dev-days**

#### 4g. Routing

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P4g-01 | App.jsx — 6 new routes | `/admin/students`, `/admin/students/:studentId`, `/admin/sessions`, `/admin/analytics`, `/admin/settings`, `/admin/books/:slug/content` | 0.25d | All 4d, 4f |

**4g total: ~0.25 dev-days**

#### 4h. i18n

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P4h-01 | en.json — admin namespace keys | Add all admin UI strings (nav labels, table headers, form labels, button text, confirmation messages) | 0.5d | All 4c–4f |
| P4h-02 | Propagate to all 12 other locales | Copy en.json admin keys to ar, de, es, fr, hi, ja, ko, ml, pt, si, ta, zh (machine translate initially) | 0.5d | P4h-01 |

**4h total: ~1.0 dev-days**

---

**Stage 4 total: ~13.5 dev-days**

---

## 2. Phased Delivery Plan

### Phase 0 — Foundation (Stage 0 tasks)
**Goal:** Schema ready; models updated; test fixtures in place.
**Tasks:** P0-01 through P0-06
**Effort:** ~2.25 dev-days
**Output:** `alembic upgrade head` succeeds; `models.py` has all new columns/tables; `conftest.py` has admin fixtures

### Phase 1 — Design (Stage 1) ✅ COMPLETE
**Output:** `docs/admin-console/` — HLD.md, DLD.md, execution-plan.md

### Phase 2 — Backend Core (Stages 2a–2d)
**Goal:** Registration simplified; graph cache safe; dashboard + student + session + analytics + user management + config endpoints live.
**Tasks:** P2a-01–P2a-03, P2b-01–P2b-03, P2c-01–P2c-11, P2d-01–P2d-05
**Effort:** ~9.0 dev-days
**Output:** 16 endpoints operational; registration no longer collects interests/style

### Phase 3 — Content Controls Backend (Stages 2e–2h)
**Goal:** All chunk and section content control endpoints operational; teaching flow respects new flags.
**Tasks:** P2e-01–P2e-08, P2f-01–P2f-03, P2g-01–P2g-04, P2h-01–P2h-05
**Effort:** ~10.5 dev-days
**Output:** ~12 new endpoints; is_hidden/exam_disabled applied in student flow

### Phase 4 — Testing (Stage 3)
**Goal:** Full test coverage of all new backend behaviour.
**Tasks:** P3-01 through P3-14
**Effort:** ~10.25 dev-days
**Output:** All 14 test files pass; CI green

### Phase 5 — Frontend (Stage 4)
**Goal:** Complete admin UI operational in browser.
**Tasks:** P4a-01 through P4h-02
**Effort:** ~13.5 dev-days
**Output:** All 6 new admin pages accessible; registration form simplified; 13 locales updated

### Phase 6 — Hardening and Release
**Goal:** Final security review; performance validation; rollout.
**Tasks:** Performance testing of dashboard query (target < 500 ms); verify thread safety test passes under load; documentation review
**Effort:** ~1.5 dev-days

---

## 3. Dependencies and Critical Path

```
P0-01 ──► P0-02 ──► P0-03 ──► P0-05
               │              │
               ▼              ▼
             P0-04 ──────► P0-06
               │
      ┌────────┴──────────────────────────┐
      ▼                                   ▼
  P2b-01 ──► P2b-02 ──► P2b-03       P2e-01 ──► (P2e-04, P2e-05) [CRITICAL]
      │                                   │
      ▼                                   ▼
  P2g-01–P2g-04                      P2h-01 ──► P2h-03 ──► P2h-04
      │
      ▼
  P3-12, P3-13 (graph tests)
      │
  [All Stage 3 tests require Stage 2 complete]
      │
  [All Stage 4 requires P4b-01]
```

### Critical Path Items
1. **P0-02 (Migration 012)** — blocks all content control backend tasks (P2e, P2f, P2g, P2h)
2. **P2b-02 (`reload_graph_with_overrides`)** — blocks all graph editing endpoints (P2g-03, P2g-04)
3. **P2e-04 + P2e-05 (merge/split)** — highest effort single tasks; complex chunk_progress migration; schedule first in Phase 3
4. **P4b-01 (admin.js wrappers)** — blocks all frontend page implementations; must be done before any frontend work begins

### External Blocking Dependencies
- **OpenAI API** — embedding regeneration calls (P2e-07, P2e-08); mock in tests
- **PostgreSQL `pgvector` extension** — must be installed for embedding column; already confirmed in production

---

## 4. Definition of Done (DoD)

### Phase 0 DoD
- [ ] `alembic upgrade head` succeeds on clean DB with all 12 migrations applied
- [ ] All new ORM models import without error
- [ ] `conftest.py` fixtures create admin user, test student, and test chunks successfully
- [ ] `alembic downgrade base` succeeds (reversibility verified)

### Phase 2 DoD
- [ ] All 16 Phase 2 endpoints return expected responses against a seeded test DB
- [ ] `RegisterRequest` Pydantic model rejects `interests` and `preferred_style` fields
- [ ] `age` field accepted as nullable integer; existing students unchanged
- [ ] `_graph_lock` prevents concurrent modification (verified by P3-13 before merge)
- [ ] No regressions in existing teaching flow endpoints (run `pytest backend/tests/` — all pre-existing tests pass)

### Phase 3 DoD
- [ ] All chunk edit/hide/exam-gate endpoints persist changes and student sessions immediately see the change
- [ ] Merge endpoint returns 409 for cross-concept; 422 for non-adjacent
- [ ] Split endpoint returns 422 for out-of-bounds paragraph index
- [ ] `chunk_progress` JSONB migration verified: active sessions survive merge/split without data loss
- [ ] `embedding_stale: true` returned whenever text is modified
- [ ] `is_hidden=True` chunk absent from `get_chunks_for_concept()` student calls
- [ ] `exam_disabled=True` chunk excluded from exam generation; full-concept disable → auto-pass
- [ ] Graph override persists after server restart (DB-backed)

### Phase 4 DoD
- [ ] All 14 test files pass with no skips
- [ ] Test coverage ≥ 80% on all new `admin_router.py` code paths
- [ ] Thread safety test passes with 10 concurrent goroutines
- [ ] Merge/split tests verify chunk_progress migration with real DB rows (not mocked)

### Phase 5 DoD
- [ ] All 6 new admin pages render without console errors
- [ ] Registration form: no interests or style fields visible; age field optional
- [ ] Admin student table: search, sort, paginate all functional
- [ ] Student detail page: mastery mark/unmark updates list immediately
- [ ] AdminReviewPage: chunk edit modal saves and refreshes chunk list
- [ ] Merge action: shows active_sessions_affected count and embedding warning in UI
- [ ] Graph editor: cycle warning shown on attempted cycle; edge addition/removal reflected immediately
- [ ] All new strings present in all 13 locale files
- [ ] WCAG 2.1 AA: all new form fields have labels; all interactive elements keyboard-navigable

### Phase 6 DoD
- [ ] `GET /api/admin/dashboard` responds in < 500 ms on a DB with 1,000 students and 10,000 sessions
- [ ] `GET /api/admin/students` with limit=50 responds in < 200 ms
- [ ] No 5xx errors in admin endpoints under 10 concurrent admin requests
- [ ] Final security review: all admin endpoints return 403 when accessed without admin JWT

---

## 5. Risk Register

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R1 | Merge chunk_progress migration corrupts active session state | Medium | High | Wrap in transaction; test against real JSONB rows; return affected count so admin can verify |
| R2 | Graph cache inconsistency under multi-worker Uvicorn | Low (current single-worker) | High | Document single-worker constraint; design reload_graph_with_overrides() for easy Redis upgrade |
| R3 | OpenAI rate limit during batch embedding regeneration | Medium | Low | Sequential processing with 100ms delay; 3 retries per chunk; partial success returned |
| R4 | Analytics query timeout for large datasets | Low | Medium | Add `EXPLAIN ANALYZE` during DoD validation; add covering indexes if > 500ms |
| R5 | Admin config key write breaks in-flight session | Low | Medium | Config read at session start; in-flight sessions unaffected; document eventual-consistency |
| R6 | Last admin accidentally demoted | Low | Critical | Backend guard: count admins before demote; reject if count == 1 |
| R7 | Split paragraph boundary off-by-one | Medium | Low | Unit test with 1-paragraph, 2-paragraph, N-paragraph chunks; boundary validation in Pydantic |
| R8 | Frontend admin pages break student routes (shared bundle) | Low | High | Admin pages behind `/admin` prefix and `require_admin` route guard; student routes unchanged |

---

## 6. Rollout Strategy

### Deployment Approach
**Feature flag:** No feature flag needed — admin console is only accessible to users with `role=admin`. Student UX is unaffected until Phase 3 backend changes land. Registration change (Part A) is the only student-visible change.

**Recommended sequence:**
1. Deploy Phase 0 migrations (non-breaking — only adds nullable columns and new tables)
2. Deploy Phase 2+3 backend code (admin endpoints are inert until frontend ships)
3. Deploy Phase 5 frontend (admin pages accessible; registration form simplified)

### Database Migration Rollout
```bash
# Pre-deploy: verify migration chain
alembic history --verbose

# Deploy (zero-downtime — only ADD operations, no column drops)
alembic upgrade head

# Verify
alembic current
```

Both migrations (011, 012) are additive-only (new nullable columns + new tables). No data backfill required. Zero downtime migration.

### Rollback Plan
```bash
# Roll back to before content controls
alembic downgrade 011_add_age_to_students

# Roll back age column
alembic downgrade 010_add_auth_tables
```

Application rollback: deploy previous Docker image tag. The DB downgrade removes the new columns without affecting existing data (age was nullable; content control columns have safe defaults).

### Monitoring at Launch
- Watch for 5xx rate on `/api/admin/*` in first 30 minutes post-deploy
- Monitor `avg_query_duration_ms` on `/api/admin/dashboard` — target < 500 ms
- Confirm `alembic current` shows `012_add_content_control_columns` on all instances

### Post-Launch Validation
Run the 20-point verification checklist from the plan document:
1. Register → only name, age, email, password
2. Admin dashboard → platform stats correct
3. Students → search, sort, paginate, edit, toggle access, manual mastery
4. Sessions → phase/book/date filters
5. Analytics → concept difficulty + mastery rates
6. Settings → threshold/XP change takes effect on next session
7. Edit chunk → student sees updated content
8. Hide chunk → absent from student view; visible in admin
9. Merge chunks → warning shown; active sessions migrated
10. Split chunk → two chunks; order correct; embedding warning
11. Reorder → student sees new sequence
12. Rename section → reflected in concept map
13. Section optional → skipped in mastery check
14. Subsection optional → single chunk skipped
15. Section exam gate off → auto-pass
16. Add prerequisite → concept locked; cycle rejected
17. Remove prerequisite → concept unlocked immediately
18. Admin user create/promote/demote
19. Graph cache thread-safe under load
20. Admin config write → takes effect on next session

---

## 7. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Phase 0 — Foundation | 6 infra tasks (migrations + models + fixtures) | 2.25 dev-days | 1 × devops-engineer |
| Phase 1 — Design | HLD + DLD + execution plan | 1.5 dev-days | 1 × solution-architect |
| Phase 2 — Backend Core | Registration, graph cache, dashboard, students, sessions, analytics, config | 9.0 dev-days | 1–2 × backend-developer |
| Phase 3 — Content Controls Backend | Chunk ops, section ops, graph editing, teaching flow flags | 10.5 dev-days | 1–2 × backend-developer |
| Phase 4 — Testing | 14 test files; unit + integration | 10.25 dev-days | 1 × comprehensive-tester |
| Phase 5 — Frontend | 6 new pages + registration + routing + i18n | 13.5 dev-days | 1–2 × frontend-developer |
| Phase 6 — Hardening | Perf testing, security review, rollout | 1.5 dev-days | 1 × backend + 1 × devops |
| **Total** | **~55 tasks** | **~48.5 dev-days** | **4–5 engineers** |

**With 4 engineers working in parallel (backend + frontend + tester + devops):**
Estimated calendar duration: ~14–16 working days

**Critical path constraint:** Phase 0 → Phase 2 backend core → Phase 3 content controls → Phase 4 tests must be sequential. Frontend (Phase 5) can run in parallel with Phase 4 once Phase 2 is complete and the API wrappers (P4b-01) are written.
