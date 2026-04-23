# Execution Plan — Admin Undo/Redo

## 1. Work Breakdown Structure (WBS)

| Task ID | Title | Description | Effort (days) | Dependencies | Component |
|---------|-------|-------------|--------------|--------------|-----------|
| **T0-01** | Alembic migration 020 | Create `admin_audit_logs` table with CHECK constraints, `ON DELETE SET NULL` FKs, and 3 indexes | 0.25 | — | `alembic/versions/020_add_admin_audit_logs.py` |
| **T0-02** | ORM model | Add `AdminAuditLog` SQLAlchemy model to `db/models.py` matching migration schema | 0.25 | T0-01 | `backend/src/db/models.py` |
| **T1-01** | Design docs | HLD, DLD, execution-plan in `docs/undo-redo/` | 0.5 | — | `docs/undo-redo/` |
| **T2A-01** | Snapshot helpers | `snapshot_chunk`, `snapshot_section`, `snapshot_session_progress_for_chunks`, `encode_embedding`, `decode_embedding` in `audit_service.py` | 0.5 | T0-02 | `audit_service.py` |
| **T2A-02** | Core audit ops | `log_action`, `stale_check`, `apply_undo` dispatcher, `apply_redo` in `audit_service.py` | 0.5 | T2A-01 | `audit_service.py` |
| **T2A-03** | Audit schemas | `AuditLogEntryResponse`, `UndoResponse`, `RedoResponse` Pydantic models in `audit_schemas.py` | 0.25 | T0-02 | `audit_schemas.py` |
| **T2B-01** | Instrument `update_chunk` | Write-ahead snapshot + `log_action` within same transaction | 0.15 | T2A-02 | `admin_router.py` |
| **T2B-02** | Instrument `toggle_chunk_visibility` | Boolean field snapshot + log | 0.10 | T2A-02 | `admin_router.py` |
| **T2B-03** | Instrument `toggle_chunk_exam_gate` | Boolean field snapshot + log | 0.10 | T2A-02 | `admin_router.py` |
| **T2B-04** | Instrument `rename_section` | Bulk `affected_chunk_ids` snapshot + log | 0.15 | T2A-02 | `admin_router.py` |
| **T2B-05** | Instrument `toggle_section_optional` | Per-chunk `is_optional` snapshot + log | 0.15 | T2A-02 | `admin_router.py` |
| **T2B-06** | Instrument `toggle_section_exam_gate` | Per-chunk `exam_disabled` snapshot + log | 0.15 | T2A-02 | `admin_router.py` |
| **T2B-07** | Easy undo handlers (6) | `_undo_update_chunk`, `_undo_toggle_chunk_visibility`, `_undo_toggle_chunk_exam_gate`, `_undo_rename_section`, `_undo_toggle_section_optional`, `_undo_toggle_section_exam_gate` | 0.5 | T2B-01 – T2B-06 | `audit_service.py` |
| **T2C-01** | Instrument `toggle_section_visibility` | Per-chunk `is_hidden` + `chunk_type_locked` snapshot + log | 0.20 | T2A-02 | `admin_router.py` |
| **T2C-02** | Instrument `reorder_chunks` | Per-chunk `order_index` snapshot + log | 0.20 | T2A-02 | `admin_router.py` |
| **T2C-03** | Medium undo handlers (2) | `_undo_toggle_section_visibility`, `_undo_reorder_chunks` | 0.25 | T2C-01, T2C-02 | `audit_service.py` |
| **T2D-01** | Instrument `merge_chunks` | Full row snapshots of both chunks + `chunk_images` + session `chunk_progress`; embed base64 embeddings | 0.5 | T2A-01, T2A-02 | `admin_router.py` |
| **T2D-02** | `_undo_merge_chunks` handler | Re-INSERT deleted chunk + images; restore surviving chunk text/heading/embedding; restore session progress | 0.75 | T2D-01 | `audit_service.py` |
| **T2D-03** | Instrument `split_chunk` | Original chunk full snapshot + session progress; capture `reorder_delta` in `new_value` | 0.4 | T2A-01, T2A-02 | `admin_router.py` |
| **T2D-04** | `_undo_split_chunk` handler | DELETE created chunk; restore original text + embedding; restore order_index for all reordered chunks; restore session progress | 0.6 | T2D-03 | `audit_service.py` |
| **T2D-05** | Instrument `promote_subsection_to_section` | Affected chunk snapshots + full `graph.json` pre/post in JSONB | 0.4 | T2A-01, T2A-02 | `admin_router.py` |
| **T2D-06** | `_undo_promote` handler | Revert chunk `concept_id`/`section`/`is_hidden`; overwrite `graph.json` from `old_value`; reload graph cache via `reload_graph_with_overrides()` | 0.75 | T2D-05 | `audit_service.py` |
| **T2E-01** | `GET /api/admin/changes` endpoint | Query, filter by book_slug/include_undone, cap at 50, return `AuditLogEntryResponse` list | 0.25 | T2A-03 | `admin_router.py` |
| **T2E-02** | `POST /api/admin/changes/{id}/undo` endpoint | Auth guard, already-undone check, `stale_check`, `apply_undo`, commit, log | 0.4 | T2A-02, T2A-03 | `admin_router.py` |
| **T2E-03** | `POST /api/admin/changes/{id}/redo` endpoint | Auth guard, not-undone guard, `apply_redo`, new audit row with `redo_of`, commit, log | 0.4 | T2A-02, T2A-03 | `admin_router.py` |
| **T2F-01** | Retention background task | `purge_old_audits_per_admin()` window-function query; `asyncio.Task` in `main.py` lifespan | 0.5 | T0-02 | `tasks/audit_cleanup.py`, `main.py` |
| **T3-01** | Unit tests — 11 action types | One test per action: do → audit row → undo → restored → redo → re-applied | 0.5 | T2E-02, T2E-03 | `tests/test_admin_audit.py` |
| **T3-02** | Integration tests — 5 scenarios | Merge+undo+redo, split+undo+redo, promote undo, cross-admin 403, session progress restoration | 0.35 | T3-01 | `tests/test_admin_audit.py` |
| **T3-03** | Edge-case tests — 4 scenarios | Stale 409, double-undo 400, retention boundary, redo chain consistency | 0.15 | T3-01 | `tests/test_admin_audit.py` |
| **T4-01** | API wrappers | `getChanges`, `undoChange`, `redoChange` in `frontend/src/api/admin.js` | 0.10 | T2E-01 – T2E-03 | `frontend/src/api/admin.js` |
| **T4-02** | `useAdminAuditHistory` hook | Fetch history, `canUndo`/`canRedo` computed state, `undo()`, `redo()` with 409 handling | 0.3 | T4-01 | `hooks/useAdminAuditHistory.js` |
| **T4-03** | `useAdminKeyboardShortcuts` hook | `Ctrl+Z` / `Ctrl+Shift+Z` / `Ctrl+Y`; focus guard; 300ms debounce; admin route guard | 0.25 | T4-02 | `hooks/useAdminKeyboardShortcuts.js` |
| **T4-04** | `UndoRedoControls` component | Icon buttons, disabled state, confirmation dialog for hard actions, toast on success/error, draft clear | 0.5 | T4-02, T4-03 | `components/admin/UndoRedoControls.jsx` |
| **T4-05** | AdminTopBar integration | Import and conditionally render `<UndoRedoControls />` on `/admin/books/:slug/review` and `/admin/books/:slug/content` routes | 0.15 | T4-04 | `layouts/AdminTopBar.jsx` |
| **T4-06** | Draft-mode conflict handling | `draftMode.clear()` after undo/redo; toast message; expose `clear()` on `useDraftMode` if missing | 0.2 | T4-04 | `AdminBookContentPage.jsx`, `useDraftMode.js` |

**Total estimated effort: ~9.5 dev-days**

---

## 2. Phased Delivery Plan

### Stage 0 — Infrastructure (0.5 day) — `devops-engineer`

**Tasks:** T0-01, T0-02

**Goal:** Database schema ready; ORM model in place. No application code yet.

**Deliverable:** `alembic upgrade head` succeeds with `020_add_admin_audit_logs`; `alembic downgrade -1` and `upgrade head` round-trip cleanly.

---

### Stage 1 — Design (0.5 day) — `solution-architect`

**Tasks:** T1-01

**Goal:** HLD, DLD, and execution plan approved by stakeholders before any backend code is written.

**Deliverable:** `docs/undo-redo/HLD.md`, `docs/undo-redo/DLD.md`, `docs/undo-redo/execution-plan.md` committed.

---

### Stage 2A — Audit Infrastructure (1.0 day) — `backend-developer`

**Tasks:** T2A-01, T2A-02, T2A-03

**Goal:** `audit_service.py` and `audit_schemas.py` exist with all function signatures, snapshot helpers, dispatcher, and stale-check logic. No endpoints yet instrumented.

**Deliverable:** `audit_service.py` imports cleanly; `snapshot_chunk` tested manually against a live chunk; `encode_embedding` / `decode_embedding` round-trip verified.

---

### Stage 2B — Easy Actions (1.0 day) — `backend-developer`

**Tasks:** T2B-01 through T2B-07

**Goal:** 6 easy endpoints instrumented; their 6 undo handlers implemented in `audit_service.py`. Undo/redo endpoints not yet exposed.

**Deliverable:** Manual test: call `rename_section`, inspect `admin_audit_logs` row, verify `old_value` and `new_value` correct.

---

### Stage 2C — Medium Actions (0.65 day) — `backend-developer`

**Tasks:** T2C-01, T2C-02, T2C-03

**Goal:** `toggle_section_visibility` and `reorder_chunks` instrumented with per-chunk snapshots.

---

### Stage 2D — Hard Actions (2.4 days) — `backend-developer`

**Tasks:** T2D-01 through T2D-06

**Goal:** All 3 hard endpoints instrumented; full undo handlers including session progress restoration and `graph.json` file I/O implemented.

**Deliverable:** Manual test: merge two chunks → inspect audit row (both full snapshots + session progress) → verify `new_value` contains correct surviving/deleted chunk IDs.

---

### Stage 2E — Undo/Redo Endpoints (1.05 days) — `backend-developer`

**Tasks:** T2E-01, T2E-02, T2E-03

**Goal:** All 3 new API endpoints live and functional end-to-end.

**Deliverable:** `GET /api/admin/changes` returns audit history; `POST .../undo` reverts and marks `undone_at`; `POST .../redo` re-applies and creates new row with `redo_of`.

---

### Stage 2F — Retention Task (0.5 day) — `backend-developer`

**Tasks:** T2F-01

**Goal:** Nightly `asyncio.Task` running in lifespan; manual invocation tested with 51 seed rows.

---

### Stage 3 — Testing (1.0 day) — `comprehensive-tester`

**Tasks:** T3-01, T3-02, T3-03

**Goal:** 20 new tests pass; existing 135 tests continue to pass (total: 155).

---

### Stage 4 — Frontend (1.5 days) — `frontend-developer`

**Tasks:** T4-01 through T4-06

**Goal:** Undo/Redo buttons visible in AdminTopBar on book content/review pages; `Ctrl+Z` / `Ctrl+Shift+Z` functional; draft-mode conflict handled with toast.

---

## 3. Dependencies and Critical Path

```
T0-01 → T0-02 → T2A-01 → T2A-02 → T2A-03
                    ↓          ↓         ↓
                T2B series  T2C series  T2E series
                    ↓          ↓
                T2D series ───────────┘
                    ↓
                T2E-02, T2E-03
                    ↓
                T3-01 → T3-02 → T3-03
                    ↓
                T4-01 → T4-02 → T4-03 → T4-04 → T4-05, T4-06
```

**Critical path (longest chain):**
`T0-01 → T0-02 → T2A-01 → T2A-02 → T2D-01 → T2D-02 → T2E-02 → T3-02 → T4-04`

**Parallelizable:**
- T2B series (6 tasks) can proceed in parallel once T2A-02 is done
- T2C series can proceed in parallel with T2B
- T2D-01/T2D-03/T2D-05 (snapshot instrumentation for 3 hard endpoints) can proceed in parallel once T2A-01 is done
- Frontend work (T4-01 through T4-06) can begin as soon as T2E-01 returns a working API response — does not require T3 to finish

**External blockers:**
- T2D-06 (`_undo_promote`) depends on `reload_graph_with_overrides()` being accessible from `audit_service.py` — confirm import path with backend team before starting T2D-05
- T4-06 depends on `useDraftMode` exposing a `clear()` method — confirm existence before starting T4-06; add if missing

---

## 4. Definition of Done (DoD)

### Stage 0
- [ ] `alembic upgrade head` succeeds with revision `020_add_admin_audit_logs`
- [ ] `alembic downgrade -1` + `upgrade head` round-trips without errors
- [ ] `AdminAuditLog` ORM model importable from `db.models`
- [ ] CHECK constraints verified: invalid `action_type` INSERT raises `IntegrityError`

### Stage 2A
- [ ] `audit_service.py` passes `python -c "import ast; ast.parse(open(...).read())"`
- [ ] `snapshot_chunk()` returns all 8 fields including `embedding` as base64 or null
- [ ] `encode_embedding` + `decode_embedding` round-trip: original vector == decoded vector (within float32 precision)
- [ ] `log_action()` inserts a row with correct `action_type` CHECK constraint

### Stage 2B + 2C + 2D
- [ ] Each of the 11 instrumented endpoints creates an `admin_audit_logs` row on every successful call
- [ ] `old_value` always captures pre-mutation state (verified by calling endpoint twice and comparing rows)
- [ ] Session `chunk_progress` snapshots present in `merge_chunks` and `split_chunk` audit rows
- [ ] `graph_json_before` present in `promote` audit `old_value`

### Stage 2E
- [ ] `GET /api/admin/changes` returns only the requesting admin's rows
- [ ] `POST .../undo` sets `undone_at` and `undone_by` on the audit row
- [ ] `POST .../redo` creates a new row with `redo_of` pointing to the undone row
- [ ] 403 returned when Admin B attempts to undo Admin A's audit row
- [ ] 409 returned when stale-check detects a field drift
- [ ] 400 returned on second undo attempt of same row

### Stage 2F
- [ ] Seed 51 audit rows for a test admin → run `purge_old_audits_per_admin()` → 50 rows remain
- [ ] Background task registered in `main.py` lifespan (visible in startup logs)

### Stage 3
- [ ] `pytest backend/tests/test_admin_audit.py -v` → 20 tests pass
- [ ] `pytest backend/tests/ -v` → 155 total tests pass (135 existing + 20 new)
- [ ] No regressions in existing admin endpoint tests

### Stage 4
- [ ] Undo/Redo buttons visible in AdminTopBar on `/admin/books/:slug/content` and `/admin/books/:slug/review`
- [ ] Buttons disabled when `canUndo`/`canRedo` are false
- [ ] `Ctrl+Z` triggers undo; `Ctrl+Shift+Z` / `Ctrl+Y` triggers redo
- [ ] Keyboard shortcuts suppressed when focus is in `<input>`, `<textarea>`, `<select>`, or `contenteditable`
- [ ] Success toast shows action type name
- [ ] 409 stale toast shows human-readable message from server
- [ ] Confirmation dialog shown for hard actions (merge/split/promote) before executing undo
- [ ] `draftMode.clear()` called after undo/redo success; draft-cleared toast shown

---

## 5. Test Matrix

| # | Test Name | Type | Verifies |
|---|-----------|------|---------|
| 1 | `test_update_chunk_audit_round_trip` | Unit | do → audit row → undo → restored → redo → re-applied |
| 2 | `test_toggle_chunk_visibility_round_trip` | Unit | Boolean flip + restore |
| 3 | `test_toggle_chunk_exam_gate_round_trip` | Unit | Boolean flip + restore |
| 4 | `test_rename_section_round_trip` | Unit | Bulk name restore using `affected_chunk_ids` |
| 5 | `test_toggle_section_optional_round_trip` | Unit | Non-uniform per-chunk restore |
| 6 | `test_toggle_section_exam_gate_round_trip` | Unit | Non-uniform per-chunk restore |
| 7 | `test_toggle_section_visibility_round_trip` | Unit | Both `is_hidden` + `chunk_type_locked` restore |
| 8 | `test_reorder_chunks_round_trip` | Unit | `order_index` restoration for all affected chunks |
| 9 | `test_merge_chunks_round_trip` | Unit | Deleted chunk re-created; surviving chunk restored |
| 10 | `test_split_chunk_round_trip` | Unit | Created chunk deleted; original text + order restored |
| 11 | `test_promote_round_trip` | Unit | Chunk `concept_id` reverted; `graph.json` overwritten |
| 12 | `test_embed_encode_decode` | Unit | Base64 float32 round-trip: decoded == original (within float32 precision) |
| 13 | `test_merge_undo_redo_full_integration` | Integration | Merge → chunk2 deleted + chunk1 merged → undo → chunk2 re-created incl. images + chunk1 restored → redo → matches post-merge state |
| 14 | `test_split_undo_redo_full_integration` | Integration | Split → new chunk + reordering → undo → new chunk deleted + text + order restored → redo |
| 15 | `test_promote_undo_integration` | Integration | Promote → graph.json written + chunks moved → undo → chunks reverted + graph.json matches pre-promote + graph cache reloaded |
| 16 | `test_cross_admin_isolation_403` | Integration | Admin A creates audit → Admin B POST undo → 403; Admin B POST redo → 403 |
| 17 | `test_session_progress_restoration` | Integration | Merge chunks in 3 active sessions → undo → all 3 sessions' `chunk_progress` byte-for-byte restored |
| 18 | `test_stale_check_409` | Edge case | Create audit → external UPDATE on same field → undo → 409 with field-name message |
| 19 | `test_double_undo_400` | Edge case | Undo same action twice → second call 400 "already undone" |
| 20 | `test_retention_boundary` | Edge case | Seed 51 rows for one admin → run purge → 50 newest remain; oldest deleted |

---

## 6. Rollback Plan

The feature is entirely additive. If deployed and found to be broken:

1. **Remove 3 new endpoints** from `admin_router.py` (GET/changes, POST/undo, POST/redo) — existing 11 endpoints continue working unchanged
2. **Drop audit table:** `alembic downgrade -1` — removes `admin_audit_logs` table and indexes cleanly
3. **Hide frontend UI:** `UndoRedoControls` conditionally renders only if `GET /api/admin/changes` returns 200 — returns 404 after endpoint removal, so buttons auto-hide
4. **No data loss** — audit is additive; no existing tables are modified
5. **No behavior change to existing mutations** — all 11 endpoints return identical responses to current callers

**Degraded mode (if downgrade is not desired):** Comment out `log_action()` calls in each instrumented endpoint. Mutations continue to work; audit rows stop being created. UI buttons remain visible but undo/redo return 404/500.

---

## 7. Verification Checklist (Pre-Release)

| # | Check | Command / Method |
|---|-------|-----------------|
| 1 | Python syntax check on all modified backend files | `python -c "import ast; ast.parse(open('backend/src/api/admin_router.py').read())"` + same for `audit_service.py`, `audit_schemas.py`, `audit_cleanup.py` |
| 2 | Migration round-trip | `cd backend && alembic upgrade head` → revision `020` appears; `alembic downgrade -1` → table dropped; `alembic upgrade head` again → table recreated |
| 3 | Unit + integration tests | `pytest backend/tests/test_admin_audit.py -v` → 20 pass; `pytest backend/tests/ -v` → 155 total pass |
| 4 | Manual per-action matrix | Perform all 11 action types via admin UI → verify audit row via `GET /api/admin/changes` → `Ctrl+Z` → verify state restored in DB + UI refreshed → `Ctrl+Shift+Z` → verify re-applied |
| 5 | Cross-admin 403 | Log in as Admin A → create audit row → new browser tab as Admin B → call `POST /api/admin/changes/{admin_a_audit_id}/undo` → expect 403 |
| 6 | Stale 409 | Create audit row → modify same chunk via DB (`UPDATE concept_chunks SET heading='MANUAL' WHERE id=...`) → attempt undo → expect 409 with field name |
| 7 | Retention boundary | Seed 51 audit rows for test admin (`INSERT INTO admin_audit_logs ...`) → run `purge_old_audits_per_admin()` → `SELECT COUNT(*) FROM admin_audit_logs WHERE admin_id=:id` → 50 |
| 8 | graph.json round-trip | Promote a section → `cp graph.json graph.json.bak` → undo → `diff graph.json graph.json.bak` → 0 differences |
| 9 | Session progress round-trip | Start teaching session on affected concept → record `chunk_progress` value → admin merges chunks → undo → `SELECT chunk_progress FROM teaching_sessions WHERE id=:id` → matches original value |

---

## 8. Effort Summary Table

| Stage | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| 0 — Infrastructure | Migration 020, ORM model | 0.5 days | 1 × devops-engineer |
| 1 — Design | HLD, DLD, execution-plan | 0.5 days | 1 × solution-architect |
| 2A — Audit Infrastructure | `audit_service.py`, `audit_schemas.py` | 1.0 days | 1 × backend-developer |
| 2B — Easy Actions (6) | Instrument 6 endpoints + 6 undo handlers | 1.0 days | 1 × backend-developer |
| 2C — Medium Actions (2) | Instrument 2 endpoints + 2 undo handlers | 0.65 days | 1 × backend-developer |
| 2D — Hard Actions (3) | Instrument 3 endpoints + 3 undo handlers | 2.4 days | 1 × backend-developer |
| 2E — Undo/Redo Endpoints | 3 new API endpoints | 1.05 days | 1 × backend-developer |
| 2F — Retention Task | `audit_cleanup.py` + lifespan wiring | 0.5 days | 1 × backend-developer |
| 3 — Testing | 20 new tests (unit + integration + edge) | 1.0 days | 1 × comprehensive-tester |
| 4 — Frontend | Hooks, component, TopBar, draft handling | 1.5 days | 1 × frontend-developer |
| **Buffer** | Integration, review, unexpected issues | 0.5 days | — |
| **Total** | | **~9.5 days** | 2–3 engineers (backend + test + frontend in parallel after Stage 2E) |

---

## Key Decisions Requiring Stakeholder Input

1. **Parallelization of stages 2B–2D**: All three sub-stages depend on the same `audit_service.py` base. A second backend developer could take 2D (hard actions) in parallel with another taking 2B/2C, saving ~1 calendar day. Confirm team allocation.
2. **Buffer scope**: The 0.5-day buffer is sized for a senior developer. If the developer handling Stage 2D is less familiar with the `promote_subsection_to_section` code path, budget an additional 0.5 days.
3. **Stage 4 start gate**: Frontend work can start as soon as `GET /api/admin/changes` returns a valid response (mid Stage 2E). Confirm with frontend developer whether they can start from a mock API response or need the real endpoint.
4. **Retention constant**: `KEEP_PER_ADMIN = 50` is hardcoded in `audit_cleanup.py`. If the team wants this configurable via `admin_config` table, add 0.25 days to Stage 2F.
