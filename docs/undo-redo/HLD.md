# High-Level Design — Admin Undo/Redo

## Revision History

### 2026-04-23 — Bug fixes (Admin undo/redo not visibly working)

Three defects were preventing the Admin Undo/Redo controls from functioning end-to-end:

1. **Backend list filter** — `GET /api/admin/changes` defaulted `include_undone=False`, so the frontend never received any undone entries. As a result, `useAdminAuditHistory.lastUndone` was always `null` and the Redo button was permanently disabled. Default flipped to `include_undone=True`; query param remains for callers that want filtering (e.g. `?include_undone=false`).

2. **Frontend listener gap on Review page** — `AdminTopBar` dispatches an `admin:audit-changed` window event after undo/redo, but only `AdminBookContentPage` was listening. `AdminReviewPage` now also listens and re-fetches its data so undo/redo is visible without a full reload.

3. **Sections sidebar not refetched** — On `AdminBookContentPage`, the audit-changed handler reloaded chunks for the selected concept but discarded the refetched sections payload, so `rename_section` undo left stale section titles in the left sidebar. Handler now applies the fresh sections array to local state.

No schema, contract, or API surface change. The fix preserves `include_undone` as an opt-in filter for callers that want only-active or only-undone slices.

---

## 1. Executive Summary

### Feature Name
Admin Undo/Redo — Server-Side Audit Log with Inverse-Action Replay

### Business Problem
Admin users on the ADA platform currently have no mechanism to reverse content edits. A misguided merge, an accidental section hide, or a botched promote-to-section requires manual SQL to repair. This creates operational risk and slows content moderation workflows because admins must be overly cautious or involve a developer for every correction.

### Key Stakeholders
- **Platform admins** — primary users of the undo/redo toolbar and keyboard shortcuts
- **Backend developer** — instruments 11 endpoints and implements `audit_service.py`
- **Frontend developer** — toolbar component, keyboard shortcuts, draft-mode conflict handling
- **DevOps engineer** — migration 020, retention background task wiring
- **Students** — indirect stakeholders; in-flight teaching sessions may observe transient state changes when a chunk is undone

### Scope

**Included:**
- 11 admin mutation endpoints (full list in Section 2)
- Per-admin audit log with JSONB old/new value snapshots
- Undo (apply inverse) and Redo (re-apply) via REST endpoints
- `GET /api/admin/changes` list endpoint
- Keyboard shortcuts: `Ctrl+Z` / `Ctrl+Shift+Z` / `Ctrl+Y`
- Undo/Redo toolbar buttons in `AdminTopBar.jsx`
- Retention: last 50 audit entries per admin (nightly purge)
- Stale-check before undo (409 if resource drifted)

**Excluded from v1:**
- Graph override add/remove endpoints
- `rename_book`, regenerate-embedding endpoints
- User/subject CRUD, system config endpoints
- WebSocket-based real-time draft invalidation (deferred to v2)
- Optimistic locking / version columns on `ConceptChunk`
- `flock` on `graph.json` for concurrent promote operations

---

## 2. Functional Requirements

| # | Requirement | Priority |
|---|-------------|----------|
| FR-01 | Every mutation to the 11 instrumented endpoints creates an audit row capturing old and new state within the same DB transaction | Must-have |
| FR-02 | `GET /api/admin/changes` returns the requesting admin's own audit history, newest first, max 50 entries | Must-have |
| FR-03 | `POST /api/admin/changes/{id}/undo` reverts the resource to its pre-mutation state | Must-have |
| FR-04 | `POST /api/admin/changes/{id}/redo` re-applies the mutation, creating a new audit row linked to the undone one | Must-have |
| FR-05 | Admin A cannot undo or redo Admin B's actions (403 enforced server-side) | Must-have |
| FR-06 | Stale-check: undo returns 409 if current resource state differs from the audit's `new_value` | Must-have |
| FR-07 | Double-undo returns 400 "Action already undone" | Must-have |
| FR-08 | `Ctrl+Z` / `Ctrl+Shift+Z` / `Ctrl+Y` keyboard shortcuts trigger undo/redo from any admin route | Must-have |
| FR-09 | Keyboard shortcuts are suppressed when focus is in `<input>`, `<textarea>`, `<select>`, or `contenteditable` | Must-have |
| FR-10 | Undo/Redo toolbar buttons in `AdminTopBar.jsx` reflect current `canUndo` / `canRedo` state | Must-have |
| FR-11 | Retention task purges per-admin entries older than the 50 newest; runs nightly | Must-have |
| FR-12 | Merge/split undo restores `teaching_sessions.chunk_progress` for all affected sessions | Must-have |
| FR-13 | Merge/split undo restores original chunk embeddings without calling OpenAI | Must-have |
| FR-14 | Promote undo restores `graph.json` byte-for-byte and reloads the in-memory graph cache | Must-have |
| FR-15 | On undo/redo success, frontend clears any pending in-memory drafts and shows a toast | Must-have |
| FR-16 | Confirmation dialog required before undoing hard actions (merge/split/promote) | Should-have |

---

## 3. Non-Functional Requirements

| Category | Requirement | Target |
|----------|-------------|--------|
| **Correctness** | Undo restores the exact byte sequence of text, embeddings, and JSONB fields | 100% round-trip fidelity |
| **Atomicity** | Mutation + audit log written in a single DB transaction; no partial writes | Zero partial-write incidents |
| **Latency** | Undo/Redo endpoint p95 response time (excluding hard actions) | < 500 ms |
| **Latency — hard actions** | Merge/split/promote undo (includes file I/O and session restore) | < 2000 ms |
| **Cost** | No OpenAI embedding calls during undo; embeddings restored from snapshot | $0 additional LLM cost per undo |
| **Storage** | Audit row JSONB budget | ~10 KB easy/medium; ~50 KB hard (merge/promote with graph) |
| **Growth cap** | Max audit rows per admin at steady state | 50 rows ≈ ~2.5 MB max per admin |
| **Backward compatibility** | All 11 instrumented endpoints continue to return identical responses to existing callers | No breaking changes to response schemas |
| **Security** | New endpoints use `Depends(require_admin)` (Bearer JWT only); X-API-Key bypass does not apply | Per existing auth pattern |
| **Rate limiting** | List endpoint: 30 req/min; Undo/Redo endpoints: 10 req/min per admin | Consistent with existing admin rate limits |
| **Availability** | Audit infrastructure failure must not block mutations (degraded mode: log warning, skip audit) | Mutations never fail due to audit errors |
| **Observability** | Structured log line per audit row: `action_type`, `resource_id`, `admin_id`, `audit_id` | 100% coverage |

---

## 4. System Context Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Admin Browser                            │
│                                                                 │
│  ┌──────────────────┐    ┌──────────────────────────────────┐  │
│  │  AdminTopBar.jsx  │    │   AdminBookContentPage.jsx       │  │
│  │  UndoRedoControls │    │   (draft mode, section editing)  │  │
│  └────────┬─────────┘    └───────────────┬──────────────────┘  │
│           │ Ctrl+Z / button               │ mutation calls      │
│           ▼                               ▼                     │
│  useAdminKeyboardShortcuts        useAdminAuditHistory          │
│           └──────────────────┬────────────┘                    │
│                              │ Axios → admin.js API wrappers   │
└──────────────────────────────┼─────────────────────────────────┘
                               │ HTTPS / JSON
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                       FastAPI Backend                           │
│                                                                 │
│  admin_router.py                                                │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  11 instrumented mutation endpoints                    │    │
│  │  (update_chunk, toggle_*, rename_*, reorder_*,         │    │
│  │   merge_*, split_*, promote_*)                         │    │
│  │                                                        │    │
│  │  3 new audit endpoints                                 │    │
│  │  GET  /api/admin/changes                               │    │
│  │  POST /api/admin/changes/{id}/undo                     │    │
│  │  POST /api/admin/changes/{id}/redo                     │    │
│  └─────────────────────────┬──────────────────────────────┘    │
│                            │                                    │
│                            ▼                                    │
│  audit_service.py                                               │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  snapshot_chunk()   snapshot_section()                 │    │
│  │  log_action()       stale_check()                      │    │
│  │  apply_undo()       apply_redo()                       │    │
│  │  _undo_<action>() handlers (11 dispatchers)            │    │
│  └─────────────────────────┬──────────────────────────────┘    │
│                            │                                    │
│             ┌──────────────┼───────────────┐                   │
│             ▼              ▼               ▼                   │
│    PostgreSQL DB      graph.json        AsyncSession           │
│    admin_audit_logs   (file on disk)    (concept_chunks,       │
│    concept_chunks     ← overwritten     teaching_sessions,     │
│    teaching_sessions    on promote undo  chunk_images)         │
│                                                                 │
│  tasks/audit_cleanup.py                                        │
│  └── nightly: DELETE oldest-beyond-50 per admin               │
└─────────────────────────────────────────────────────────────────┘
```

**Data flow for a mutation (e.g., rename_section):**
1. Admin calls `PATCH /api/admin/sections/{cid}/rename`
2. `admin_router.rename_section` calls `audit_service.snapshot_section()` → captures `old_value`
3. Mutation SQL executes (still within open transaction)
4. `audit_service.snapshot_section()` again → captures `new_value`
5. `audit_service.log_action()` inserts `admin_audit_logs` row
6. `db.commit()` — both mutation and audit row committed atomically
7. Frontend receives response, `useAdminAuditHistory.refresh()` updates toolbar state

---

## 5. Architectural Style and Patterns

**Style: Layered monolith with write-ahead audit side-channel**

The existing codebase is a FastAPI monolith. The audit feature adds a horizontal cross-cutting concern implemented as a service layer (`audit_service.py`) called from the router layer. No new service processes are introduced.

**Key patterns:**
- **Write-ahead audit** — state is captured before mutation, not after (see ADR-1)
- **Dispatcher pattern** — `apply_undo()` routes to `_undo_<action_type>()` handler (11 functions)
- **Snapshot-based undo** — stores full row snapshots rather than delta instructions (see ADR-2)
- **Stale-check optimistic validation** — lightweight conflict detection without version columns (see ADR-3)

---

## 6. Technology Stack

All choices are constrained to the existing project stack — no new dependencies are introduced for the core feature.

| Concern | Technology | Rationale |
|---------|-----------|-----------|
| Audit storage | PostgreSQL JSONB column | Already used for `exam_scores`, `chunk_progress`; flexible schema per action type |
| Embedding snapshot | Base64-encoded float32 bytes in JSONB | Avoids side-table complexity; ~8 KB per chunk embedding |
| Background retention | `asyncio.Task` created in `main.py` lifespan | No new dependency (APScheduler not in project); simple `asyncio.sleep(86400)` loop |
| Frontend state | React hook (`useAdminAuditHistory`) | Consistent with existing hook pattern (`useAdminKeyboardShortcuts`) |
| Keyboard shortcuts | `window.addEventListener('keydown')` in useEffect | Standard DOM pattern; no external library needed |
| Toast notifications | Existing toast system in admin UI | Consistent UX; no new library |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-1: Write-ahead vs Write-behind Audit

**Decision:** Write-ahead — capture `old_value` BEFORE the mutation executes, within the same transaction.

**Options considered:**
- Write-behind (capture after mutation, infer old from diff): simpler code but requires either a separate SELECT or change-data-capture infrastructure. Cannot reconstruct old JSONB embedding or old session progress without the pre-mutation SELECT anyway.
- Write-ahead (capture before): requires one extra SELECT per mutation but gives exact old state with no inference.

**Chosen:** Write-ahead. The extra SELECT is negligible compared to the mutation itself. Atomicity is guaranteed because the audit INSERT and the mutation UPDATE share the same `AsyncSession` and are committed together.

**Trade-off:** If the mutation fails (e.g., DB constraint violation), the transaction rolls back and no audit row is created. This is the correct behavior — we only audit successful mutations.

---

### ADR-2: Single JSONB Table vs Per-Action-Type Tables

**Decision:** Single `admin_audit_logs` table with a `JSONB old_value` and `JSONB new_value` column.

**Options considered:**
- Per-action-type tables (e.g., `audit_chunk_updates`, `audit_merges`): strongly typed, no JSONB, but requires 11 tables + 22 migration columns. Undo/redo logic cannot be unified into a single `apply_undo()` dispatcher.
- Single table with JSONB: one migration, one ORM model, one dispatcher. Schema flexibility per action type is a feature, not a bug — each action's snapshot shape is documented in the DLD.

**Chosen:** Single JSONB table. Given that only 11 action types exist and their snapshot shapes are stable, JSONB is proportionate. The CHECK constraint on `action_type` enforces the enum at the DB layer.

**Trade-off:** JSONB is not schema-validated at the DB level beyond the CHECK constraint. Validation is enforced by `audit_service.py`'s snapshot functions and Pydantic schemas.

---

### ADR-3: Stale-Check vs Optimistic Locking

**Decision:** Stale-check on undo — compare current DB state to `audit.new_value` and return 409 if they differ.

**Options considered:**
- Optimistic locking with a `version` column on `ConceptChunk`: zero false negatives but requires a schema migration on a heavily queried table and changes to every UPDATE statement.
- Stale-check (current approach): reads the current row state at undo time, compares key fields to `new_value`. If any field differs, the resource was modified after the audit was created.

**Chosen:** Stale-check. Adding a `version` column is out of scope for v1. The stale-check catches the most important case: another admin edited the same chunk between the audit row creation and the undo attempt. The 409 response tells the requesting admin to review the current state before retrying.

**Trade-off:** Stale-check has a TOCTOU window between the comparison and the undo write. Two simultaneous undo requests on the same audit entry could both pass the stale-check before either writes. Acceptable for v1 given the low concurrency of admin operations. v2 mitigation: `SELECT ... FOR UPDATE` on the audit row.

---

### ADR-4: Snapshot Embeddings vs Regenerate on Undo

**Decision:** Snapshot the original embedding as base64-encoded float32 bytes in the `old_value` JSONB field; restore as-is on undo.

**Options considered:**
- Regenerate embedding via OpenAI on undo: costs money, adds latency (2–5s), requires network call, and may produce slightly different vectors due to model updates.
- Store embedding in a side table with FK to audit row: cleaner schema but adds complexity and another migration.
- Base64 in JSONB: self-contained, zero cost to restore, ~8 KB overhead per chunk embedding (1536 floats × 4 bytes → ~8.2 KB → ~11 KB base64).

**Chosen:** Base64 in JSONB. The size overhead is bounded by the 50-entry retention limit (~550 KB of embedding data per admin at maximum). The restore is deterministic and free.

**Trade-off:** Large JSONB rows for merge/promote operations (up to ~50 KB). Retention limit bounds total storage to ~2.5 MB per admin for all audit data.

---

### ADR-5: Per-Admin Isolation vs Shared Timeline

**Decision:** Each admin sees and operates on only their own audit entries.

**Options considered:**
- Shared timeline (any admin can undo any other admin's action): simpler for small teams but creates audit confusion and potential blame-shifting. Requires coordination protocol to avoid conflicts.
- Per-admin isolation: each admin operates on their own history. Conflicts between admins surface via the stale-check (409).

**Chosen:** Per-admin isolation. Enforced at the endpoint level: `audit.admin_id != current_user.id` → 403. This is the standard pattern for audit systems (e.g., Git's local history model).

**Trade-off:** Admin A cannot undo Admin B's destructive action. A super-admin override capability can be added in v2 via an explicit `force_undo` flag gated on a `superadmin` role.

---

## 8. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| R1 | Snapshot size blows up DB (merge/promote can be 50+ KB each) | Low | Medium | 50-entry retention caps growth to ~5 MB per admin. Monitor with `pg_relation_size('admin_audit_logs')` alert |
| R2 | Embedding base64 bloats JSONB (~11 KB per chunk) | Medium | Low | Bounded by retention. If budget exceeded in v2, move embeddings to a side table with FK |
| R3 | `graph.json` lock race: two admins promote simultaneously | Low | High | Accept for v1 (rare event). Last-write-wins; stale-check detects second undo attempt. Add `flock` in v2. Document in admin user guide |
| R4 | Undo triggers stale DB cache in running teaching sessions | Medium | Medium | Sessions refresh chunk data on next card fetch; admin undo toast warns "active sessions may see state change within 30s" |
| R5 | Draft mode silently invalidated on undo | Low | Medium | v1: clear drafts + show toast. v2: SSE invalidation channel per admin session |
| R6 | Admin accidentally undoes hard action (merge/split/promote) | Medium | High | Confirmation dialog for hard-action undo; easy/medium actions undo without prompt |
| R7 | Audit service error blocks mutation | Low | High | `try/except` around `log_action()`; log warning and allow mutation to succeed. Mutation correctness > audit completeness |
| R8 | TOCTOU window in stale-check allows duplicate undo | Very Low | Low | Accept for v1. v2 mitigation: `SELECT ... FOR UPDATE` on audit row |

---

## Key Decisions Requiring Stakeholder Input

1. **Confirmation dialog for hard actions (R6):** Should the confirmation dialog list the affected chunks and session count to help the admin make an informed decision, or is a generic "Are you sure?" sufficient?
2. **Super-admin override (ADR-5):** Is there a use case where an admin needs to undo another admin's action? If yes, define the role requirement before v2.
3. **Degraded mode behavior (R7):** If `log_action()` fails (e.g., DB disk full), should the mutation succeed silently or return a 500? Current proposal is to log a warning and allow the mutation — confirm this is acceptable.
4. **Retention window:** 50 entries per admin is a product decision. Should it be configurable via `admin_config` table or hardcoded?
5. **Draft-mode toast copy:** Confirm exact wording: "Your unsaved drafts were cleared because an action was undone. Please review the current state before editing."
