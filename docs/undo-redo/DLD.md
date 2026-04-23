# Detailed Low-Level Design — Admin Undo/Redo

## Revision History

### 2026-04-23 — Bug fixes (Admin undo/redo not visibly working)

Three defects were preventing the Admin Undo/Redo controls from functioning end-to-end:

1. **Backend list filter** — `GET /api/admin/changes` defaulted `include_undone=False`, so the frontend never received any undone entries. As a result, `useAdminAuditHistory.lastUndone` was always `null` and the Redo button was permanently disabled. Default flipped to `include_undone=True`; query param remains for callers that want filtering (e.g. `?include_undone=false`).

2. **Frontend listener gap on Review page** — `AdminTopBar` dispatches an `admin:audit-changed` window event after undo/redo, but only `AdminBookContentPage` was listening. `AdminReviewPage` now also listens and re-fetches its data so undo/redo is visible without a full reload.

3. **Sections sidebar not refetched** — On `AdminBookContentPage`, the audit-changed handler reloaded chunks for the selected concept but discarded the refetched sections payload, so `rename_section` undo left stale section titles in the left sidebar. Handler now applies the fresh sections array to local state.

No schema, contract, or API surface change. The fix preserves `include_undone` as an opt-in filter for callers that want only-active or only-undone slices.

---

## 1. Component Breakdown

| Component | File | Responsibility |
|-----------|------|---------------|
| **Alembic migration 020** | `backend/alembic/versions/020_add_admin_audit_logs.py` | Creates `admin_audit_logs` table, indexes, and CHECK constraints |
| **ORM model** | `backend/src/db/models.py` (modified) | `AdminAuditLog` SQLAlchemy model matching migration schema |
| **Audit service** | `backend/src/api/audit_service.py` (new) | Snapshot functions, `log_action`, `apply_undo`, `apply_redo`, `stale_check`, 11 undo handler dispatchers |
| **Audit schemas** | `backend/src/api/audit_schemas.py` (new) | Pydantic v2 response models for list/undo/redo endpoints |
| **Admin router** | `backend/src/api/admin_router.py` (modified) | Instruments 11 existing endpoints; adds 3 new endpoints |
| **Retention task** | `backend/src/tasks/audit_cleanup.py` (new) | `purge_old_audits_per_admin()` async function; wired into `main.py` lifespan |
| **API wrappers** | `frontend/src/api/admin.js` (modified) | Adds `getChanges`, `undoChange`, `redoChange` Axios wrappers |
| **Audit history hook** | `frontend/src/hooks/useAdminAuditHistory.js` (new) | Fetches history, exposes `canUndo`/`canRedo`, `undo(id)`, `redo(id)` |
| **Keyboard shortcut hook** | `frontend/src/hooks/useAdminKeyboardShortcuts.js` (new) | Global `Ctrl+Z` / `Ctrl+Shift+Z` / `Ctrl+Y` handler with focus guard |
| **Toolbar component** | `frontend/src/components/admin/UndoRedoControls.jsx` (new) | Undo/Redo icon buttons with disabled state and confirmation dialog |
| **AdminTopBar** | `frontend/src/layouts/AdminTopBar.jsx` (modified) | Renders `<UndoRedoControls />` on book content/review routes |
| **AdminBookContentPage** | `frontend/src/pages/AdminBookContentPage.jsx` (modified) | Clears drafts and refreshes data after undo/redo success |

---

## 2. Database Schema

### Table: `admin_audit_logs`

```sql
CREATE TABLE admin_audit_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id        UUID REFERENCES users(id) ON DELETE SET NULL,
    action_type     TEXT NOT NULL,
    resource_type   TEXT NOT NULL,           -- 'chunk' | 'section'
    resource_id     TEXT NOT NULL,           -- chunk UUID or concept_id string
    book_slug       TEXT NOT NULL,
    old_value       JSONB NOT NULL,
    new_value       JSONB NOT NULL,
    affected_count  INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    undone_by       UUID REFERENCES users(id) ON DELETE SET NULL,
    undone_at       TIMESTAMPTZ,
    redo_of         UUID REFERENCES admin_audit_logs(id) ON DELETE SET NULL,

    CONSTRAINT ck_audit_action_type CHECK (action_type IN (
        'update_chunk', 'toggle_chunk_visibility', 'toggle_chunk_exam_gate',
        'rename_section', 'toggle_section_optional', 'toggle_section_exam_gate',
        'toggle_section_visibility', 'reorder_chunks',
        'merge_chunks', 'split_chunk', 'promote'
    )),
    CONSTRAINT ck_audit_resource_type CHECK (resource_type IN ('chunk', 'section'))
);

CREATE INDEX ix_audit_admin_created ON admin_audit_logs (admin_id, created_at DESC);
CREATE INDEX ix_audit_resource     ON admin_audit_logs (resource_id);
CREATE INDEX ix_audit_book         ON admin_audit_logs (book_slug);
```

**Column notes:**
- `admin_id`: `SET NULL` on user delete — preserves audit history after admin account removal
- `undone_at` / `undone_by`: set when action is undone; row is never deleted
- `redo_of`: FK to the undone audit row; forms a singly-linked redo chain
- `affected_count`: number of DB rows mutated (useful for section bulk operations)

### SQLAlchemy ORM Model (`db/models.py`)

```python
class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id             = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    admin_id       = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action_type    = Column(Text, nullable=False)
    resource_type  = Column(Text, nullable=False)
    resource_id    = Column(Text, nullable=False)
    book_slug      = Column(Text, nullable=False)
    old_value      = Column(JSONB, nullable=False)
    new_value      = Column(JSONB, nullable=False)
    affected_count = Column(Integer, nullable=False, server_default="1")
    created_at     = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    undone_by      = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    undone_at      = Column(DateTime(timezone=True), nullable=True)
    redo_of        = Column(UUID(as_uuid=True), ForeignKey("admin_audit_logs.id", ondelete="SET NULL"), nullable=True)
```

---

## 3. Snapshot Schemas Per Action Type

All snapshots are serialized as JSONB. The `embedding` field stores base64-encoded IEEE 754 float32 bytes: `base64.b64encode(struct.pack(f'{len(vec)}f', *vec)).decode()`. A `null` embedding means the chunk had no embedding at snapshot time.

### 3.1 `update_chunk` (Easy)

```jsonc
// old_value — full mutable field snapshot before edit
{
  "heading": "Old Heading",
  "text": "Old paragraph text...",
  "chunk_type": "teaching",
  "is_optional": false,
  "is_hidden": false,
  "exam_disabled": false,
  "chunk_type_locked": false,
  "embedding": "<base64_float32_bytes or null>"
}
// new_value — same shape, post-mutation values
```

### 3.2 `toggle_chunk_visibility` (Easy)

```jsonc
// old_value
{ "is_hidden": false }
// new_value
{ "is_hidden": true }
```

### 3.3 `toggle_chunk_exam_gate` (Easy)

```jsonc
// old_value
{ "exam_disabled": false }
// new_value
{ "exam_disabled": true }
```

### 3.4 `rename_section` (Easy bulk)

```jsonc
// old_value — per-chunk original names + chunk IDs for restore
{
  "admin_section_name": "Old name or null",
  "affected_chunk_ids": ["uuid1", "uuid2", "uuid3"]
}
// new_value
{
  "admin_section_name": "New Section Name"
}
```

Rationale: `affected_chunk_ids` lets undo restore only the chunks that were actually renamed, not all chunks in the section.

### 3.5 `toggle_section_optional` (Easy bulk)

```jsonc
// old_value — per-chunk original values (preserves non-uniform state)
{
  "per_chunk": [
    { "id": "uuid1", "is_optional": false },
    { "id": "uuid2", "is_optional": true },
    { "id": "uuid3", "is_optional": false }
  ]
}
// new_value — uniform value applied
{ "is_optional": true }
```

### 3.6 `toggle_section_exam_gate` (Easy bulk)

```jsonc
// Same pattern as toggle_section_optional, field: exam_disabled
{
  "per_chunk": [
    { "id": "uuid1", "exam_disabled": false },
    { "id": "uuid2", "exam_disabled": false }
  ]
}
// new_value
{ "exam_disabled": true }
```

### 3.7 `toggle_section_visibility` (Medium)

Captures both `is_hidden` AND `chunk_type_locked` per chunk because the endpoint may modify both fields:

```jsonc
// old_value
{
  "per_chunk": [
    { "id": "uuid1", "is_hidden": false, "chunk_type_locked": false },
    { "id": "uuid2", "is_hidden": false, "chunk_type_locked": true }
  ]
}
// new_value
{ "is_hidden": true, "chunk_type_locked": true }
```

### 3.8 `reorder_chunks` (Medium)

```jsonc
// old_value — full per-chunk order before reorder
{
  "per_chunk": [
    { "id": "uuid1", "order_index": 0 },
    { "id": "uuid2", "order_index": 1 },
    { "id": "uuid3", "order_index": 2 }
  ]
}
// new_value — new order (only changed chunks need be listed)
{
  "per_chunk": [
    { "id": "uuid1", "order_index": 2 },
    { "id": "uuid2", "order_index": 0 },
    { "id": "uuid3", "order_index": 1 }
  ]
}
```

### 3.9 `merge_chunks` (Hard)

```jsonc
// old_value — full row snapshots of both chunks + session state
{
  "chunk1": {
    "id": "uuid-A",
    "concept_id": "prealgebra_1.2",
    "section": "1.2 Use the Language of Algebra",
    "order_index": 3,
    "heading": "Variables and Expressions",
    "text": "Original text of chunk 1...",
    "chunk_type": "teaching",
    "is_optional": false,
    "is_hidden": false,
    "exam_disabled": false,
    "chunk_type_locked": false,
    "embedding": "<base64>",
    "latex": ["x + y", "a^2 + b^2"],
    "images": [
      { "image_url": "/images/uuid-A/fig1.png", "caption": "Figure 1", "order_index": 0 }
    ]
  },
  "chunk2": {
    "id": "uuid-B",
    /* ... same shape ... */
    "images": []
  },
  "affected_sessions": [
    {
      "session_id": "sess-uuid-1",
      "chunk_progress_before": { "uuid-A": true, "uuid-B": false }
    }
  ]
}
// new_value — describes the surviving chunk's new state
{
  "surviving_chunk_id": "uuid-A",
  "deleted_chunk_id": "uuid-B",
  "new_heading": "Variables and Expressions (merged)",
  "new_text": "Merged text of both chunks..."
}
```

**Undo steps:**
1. Re-INSERT `chunk2` row with original `id`, all fields from `old_value.chunk2`
2. Re-INSERT `chunk_images` rows for `chunk2` from `old_value.chunk2.images`
3. UPDATE `chunk1`: restore `heading`, `text`, `embedding` from `old_value.chunk1`
4. For each entry in `old_value.affected_sessions`: UPDATE `teaching_sessions SET chunk_progress = :before WHERE id = :session_id`

### 3.10 `split_chunk` (Hard)

```jsonc
// old_value — full original chunk snapshot + session state
{
  "original_chunk": {
    "id": "uuid-A",
    "text": "Full original text before split...",
    "embedding": "<base64>",
    /* ... all fields ... */
    "images": [{ "image_url": "...", "caption": "...", "order_index": 0 }]
  },
  "split_position": 512,
  "affected_sessions": [
    {
      "session_id": "sess-uuid-1",
      "chunk_progress_before": { "uuid-A": false }
    }
  ]
}
// new_value — describes what was created and reordered
{
  "original_chunk_id": "uuid-A",
  "created_chunk_id": "uuid-B",
  "original_new_text": "First half of text...",
  "new_chunk_text": "Second half of text...",
  "reorder_delta": [
    { "id": "uuid-X", "old_order": 5, "new_order": 6 },
    { "id": "uuid-Y", "old_order": 6, "new_order": 7 }
  ]
}
```

**Undo steps:**
1. DELETE created chunk (`uuid-B`) and its `chunk_images`
2. UPDATE original chunk (`uuid-A`): restore full `text` + `embedding` from `old_value.original_chunk`
3. For each entry in `new_value.reorder_delta`: UPDATE `concept_chunks SET order_index = :old_order WHERE id = :id`
4. Restore session `chunk_progress` for all affected sessions

### 3.11 `promote` (Hard — includes graph.json)

```jsonc
// old_value — chunk states + full graph.json before promote
{
  "old_concept_id": "prealgebra_1.1",
  "affected_chunks": [
    {
      "id": "uuid1",
      "concept_id": "prealgebra_1.1",
      "section": "Subsection: Introduction",
      "is_hidden": false
    },
    {
      "id": "uuid2",
      "concept_id": "prealgebra_1.1",
      "section": "Subsection: Introduction",
      "is_hidden": false
    }
  ],
  "graph_json_before": { /* full graph.json dict, verbatim */ }
}
// new_value — post-promote state
{
  "new_concept_id": "prealgebra_1.1b",
  "new_section_label": "Introduction",
  "affected_chunk_ids": ["uuid1", "uuid2"],
  "graph_json_after": { /* full graph.json dict, verbatim */ }
}
```

**Undo steps:**
1. For each chunk in `old_value.affected_chunks`: UPDATE `concept_chunks SET concept_id = :old_concept_id, section = :section, is_hidden = :is_hidden WHERE id = :id`
2. Overwrite `OUTPUT_DIR / book_slug / "graph.json"` with `json.dumps(old_value.graph_json_before)`
3. Call `await reload_graph_with_overrides(book_slug, db)` to refresh in-memory NetworkX cache

---

## 4. API Design

### Authentication
All three new endpoints use `Depends(require_admin)` — Bearer JWT required. The `X-API-Key` middleware bypass does not apply to `require_admin`-gated endpoints.

### Rate Limits
- `GET /api/admin/changes`: `@limiter.limit("30/minute")`
- `POST /api/admin/changes/{id}/undo`: `@limiter.limit("10/minute")`
- `POST /api/admin/changes/{id}/redo`: `@limiter.limit("10/minute")`

---

### `GET /api/admin/changes`

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `book_slug` | string | null | Filter to one book |
| `include_undone` | bool | false | Include entries with `undone_at IS NOT NULL` |
| `limit` | int | 50 | Max entries; capped at 50 server-side |

**Response `200 OK`:**
```jsonc
[
  {
    "id": "uuid",
    "admin_id": "uuid",
    "action_type": "rename_section",
    "resource_type": "section",
    "resource_id": "prealgebra_1.2",
    "book_slug": "prealgebra",
    "old_value": { "admin_section_name": "Old Name", "affected_chunk_ids": ["..."] },
    "new_value": { "admin_section_name": "New Name" },
    "affected_count": 4,
    "created_at": "2026-04-21T10:23:45Z",
    "undone_at": null,
    "undone_by": null,
    "redo_of": null
  }
]
```

**Error codes:**

| Code | Condition |
|------|-----------|
| 401 | Missing or invalid JWT |
| 403 | JWT belongs to non-admin user |

---

### `POST /api/admin/changes/{audit_id}/undo`

**Path parameter:** `audit_id` — UUID of the audit entry to undo.

**Request body:** empty (no body required)

**Response `200 OK`:**
```jsonc
{
  "success": true,
  "message": "Undone: rename_section on prealgebra_1.2",
  "audit_id": "uuid",
  "action_type": "rename_section"
}
```

**Error codes:**

| Code | Condition | Body |
|------|-----------|------|
| 400 | `undone_at IS NOT NULL` | `{"detail": "Action already undone"}` |
| 403 | `audit.admin_id != current_user.id` | `{"detail": "Cannot undo another admin's action"}` |
| 404 | Audit entry not found | `{"detail": "Audit entry not found"}` |
| 409 | Stale-check failed | `{"detail": "Cannot undo — resource was modified since this audit was recorded. Field 'heading' expected 'Old' but found 'Different'. Refresh and retry."}` |

---

### `POST /api/admin/changes/{audit_id}/redo`

**Path parameter:** `audit_id` — UUID of an entry where `undone_at IS NOT NULL`.

**Response `200 OK`:**
```jsonc
{
  "success": true,
  "message": "Redone: rename_section on prealgebra_1.2",
  "original_audit_id": "uuid-original",
  "new_audit_id": "uuid-new",
  "action_type": "rename_section"
}
```

**Error codes:**

| Code | Condition |
|------|-----------|
| 400 | Entry has not been undone (`undone_at IS NULL`) — cannot redo an active action |
| 403 | `audit.admin_id != current_user.id` |
| 404 | Audit entry not found |
| 409 | Stale-check on redo (current state doesn't match `old_value` — someone made a change after the undo) |

### Versioning
These endpoints follow the existing pattern: no version prefix change — all admin endpoints live under `/api/admin/`. No v4 bump required.

---

## 5. Audit Service — Function Signatures

```python
# backend/src/api/audit_service.py

import base64, struct
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

# ─── Snapshot helpers ───────────────────────────────────────────────────────

async def snapshot_chunk(db: AsyncSession, chunk_id: UUID) -> dict:
    """
    Returns a dict capturing all auditable fields of a ConceptChunk row,
    plus its chunk_images and base64-encoded embedding.
    Raises 404 if chunk not found.
    """

async def snapshot_section(
    db: AsyncSession, concept_id: str, book_slug: str
) -> list[dict]:
    """
    Returns a list of per-chunk dicts for all chunks in the section.
    Each dict contains: id, is_hidden, chunk_type_locked, is_optional,
    exam_disabled, admin_section_name, order_index.
    """

async def snapshot_session_progress_for_chunks(
    db: AsyncSession, chunk_ids: list[UUID]
) -> list[dict]:
    """
    Returns list of {session_id, chunk_progress_before} for all active
    teaching_sessions whose chunk_progress JSONB contains any of chunk_ids.
    """

def encode_embedding(vec: list[float] | None) -> str | None:
    """Encodes a list of float32 values to base64 string."""
    if vec is None:
        return None
    return base64.b64encode(struct.pack(f"{len(vec)}f", *vec)).decode()

def decode_embedding(b64: str | None) -> list[float] | None:
    """Decodes base64 string back to list of float32 values."""
    if b64 is None:
        return None
    raw = base64.b64decode(b64)
    count = len(raw) // 4
    return list(struct.unpack(f"{count}f", raw))

# ─── Core audit operations ────────────────────────────────────────────────

async def log_action(
    db: AsyncSession,
    *,
    admin_id: UUID,
    action_type: str,
    resource_type: str,
    resource_id: str,
    book_slug: str,
    old_value: dict,
    new_value: dict,
    affected_count: int = 1,
    redo_of: UUID | None = None,
) -> AdminAuditLog:
    """
    Inserts an AdminAuditLog row. Must be called within an open transaction
    (before db.commit()). Returns the ORM instance.
    """

async def stale_check(db: AsyncSession, audit: AdminAuditLog) -> None:
    """
    Compares current DB state of the resource to audit.new_value.
    Raises HTTPException(409) with a human-readable message if state drifted.
    No-op if state matches.
    """

async def apply_undo(
    db: AsyncSession, audit: AdminAuditLog, current_admin_id: UUID
) -> None:
    """
    Dispatches to the matching _undo_<action_type> handler.
    Sets audit.undone_at and audit.undone_by within the current transaction.
    """

async def apply_redo(
    db: AsyncSession, audit: AdminAuditLog, current_admin_id: UUID
) -> AdminAuditLog:
    """
    Re-applies audit.new_value to the resource.
    Creates and returns a new AdminAuditLog row with redo_of=audit.id.
    """
```

---

## 6. Undo Handler Dispatch Table

```python
# Internal to audit_service.py

_UNDO_HANDLERS: dict[str, Callable] = {
    "update_chunk":             _undo_update_chunk,
    "toggle_chunk_visibility":  _undo_toggle_chunk_visibility,
    "toggle_chunk_exam_gate":   _undo_toggle_chunk_exam_gate,
    "rename_section":           _undo_rename_section,
    "toggle_section_optional":  _undo_toggle_section_optional,
    "toggle_section_exam_gate": _undo_toggle_section_exam_gate,
    "toggle_section_visibility":_undo_toggle_section_visibility,
    "reorder_chunks":           _undo_reorder_chunks,
    "merge_chunks":             _undo_merge_chunks,
    "split_chunk":              _undo_split_chunk,
    "promote":                  _undo_promote,
}

async def apply_undo(db, audit, current_admin_id):
    handler = _UNDO_HANDLERS[audit.action_type]
    await handler(db, audit)
    audit.undone_at = datetime.now(timezone.utc)
    audit.undone_by = current_admin_id
```

Each `_undo_<action>` function:
- Reads `audit.old_value`
- Executes the inverse DB writes (UPDATEs, re-INSERTs, DELETEs)
- Does NOT call `db.commit()` — caller commits

---

## 7. Instrumentation Pattern for 11 Endpoints

The same pattern is applied to every endpoint. Example for `update_chunk`:

```python
@limiter.limit("30/minute")
@router.patch("/api/admin/chunks/{chunk_id}")
async def update_chunk(
    chunk_id: UUID, request: UpdateChunkRequest, req: Request,
    _user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    chunk = await db.get(ConceptChunk, chunk_id)
    if chunk is None:
        raise HTTPException(404, "Chunk not found")

    # 1. Capture old state (write-ahead)
    old_snapshot = await audit_service.snapshot_chunk(db, chunk_id)

    # 2. Apply mutation (existing logic — unchanged)
    if request.heading is not None:
        chunk.heading = request.heading
    # ... etc ...
    await db.flush()  # write to txn without committing

    # 3. Capture new state
    new_snapshot = await audit_service.snapshot_chunk(db, chunk_id)

    # 4. Log audit within same transaction
    try:
        await audit_service.log_action(
            db, admin_id=_user.id,
            action_type="update_chunk", resource_type="chunk",
            resource_id=str(chunk_id), book_slug=chunk.book_slug,
            old_value=old_snapshot, new_value=new_snapshot,
        )
    except Exception:
        logger.warning("[admin] Audit log failed for update_chunk %s — proceeding", chunk_id)

    # 5. Commit both mutation and audit atomically
    await db.commit()
    logger.info("[admin] Chunk %s updated by admin %s (audit_logged)", chunk_id, _user.id)
    return { ... }  # unchanged response
```

**Hard action additions (merge, split, promote):**
- Before step 1: also call `snapshot_session_progress_for_chunks()`
- For promote: also read `graph.json` from disk and embed in `old_value`

---

## 8. Stale-Check Algorithm

```python
async def stale_check(db: AsyncSession, audit: AdminAuditLog) -> None:
    action = audit.action_type
    new_val = audit.new_value

    if action == "update_chunk":
        chunk = await db.get(ConceptChunk, UUID(audit.resource_id))
        if chunk is None:
            raise HTTPException(409, "Resource no longer exists")
        for field in ("heading", "text", "chunk_type", "is_optional",
                      "is_hidden", "exam_disabled", "chunk_type_locked"):
            if field in new_val and getattr(chunk, field) != new_val[field]:
                raise HTTPException(
                    409,
                    f"Cannot undo — resource was modified since this audit was recorded. "
                    f"Field '{field}' expected {new_val[field]!r} but found "
                    f"{getattr(chunk, field)!r}. Refresh and retry."
                )

    elif action in ("toggle_chunk_visibility", "toggle_chunk_exam_gate"):
        chunk = await db.get(ConceptChunk, UUID(audit.resource_id))
        field = "is_hidden" if action == "toggle_chunk_visibility" else "exam_disabled"
        expected = new_val[field]
        if getattr(chunk, field) != expected:
            raise HTTPException(409, f"Field '{field}' has been modified. Refresh and retry.")

    elif action in ("rename_section", "toggle_section_optional",
                    "toggle_section_exam_gate", "toggle_section_visibility"):
        # For bulk section ops: verify each chunk in new_val matches DB
        # (abbreviated for doc; full implementation checks all per-chunk fields)
        ...

    elif action == "reorder_chunks":
        for entry in new_val.get("per_chunk", []):
            chunk = await db.get(ConceptChunk, UUID(entry["id"]))
            if chunk and chunk.order_index != entry["order_index"]:
                raise HTTPException(409, f"Chunk {entry['id']} order has changed. Refresh and retry.")

    elif action == "merge_chunks":
        # Check surviving chunk's text matches new_value.new_text
        surviving = await db.get(ConceptChunk, UUID(new_val["surviving_chunk_id"]))
        if surviving and surviving.text != new_val.get("new_text"):
            raise HTTPException(409, "Merged chunk has been further edited. Cannot safely undo.")

    elif action == "split_chunk":
        created = await db.get(ConceptChunk, UUID(new_val["created_chunk_id"]))
        if created is None:
            raise HTTPException(409, "Split chunk no longer exists. Cannot undo.")

    elif action == "promote":
        # Verify concept_id of affected chunks matches new_value.new_concept_id
        for chunk_id in new_val.get("affected_chunk_ids", []):
            chunk = await db.get(ConceptChunk, UUID(chunk_id))
            if chunk and chunk.concept_id != new_val["new_concept_id"]:
                raise HTTPException(409, "Promoted chunks have been modified. Cannot safely undo.")
```

---

## 9. Retention Background Task

```python
# backend/src/tasks/audit_cleanup.py

from sqlalchemy import text
from backend.src.db.connection import async_session_factory

KEEP_PER_ADMIN = 50

async def purge_old_audits_per_admin(keep_per_admin: int = KEEP_PER_ADMIN) -> int:
    """
    Deletes audit rows older than the N newest per admin.
    Uses a window function to identify rows to delete.
    Returns the count of deleted rows.
    """
    async with async_session_factory() as db:
        result = await db.execute(
            text("""
                DELETE FROM admin_audit_logs
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY admin_id
                                   ORDER BY created_at DESC
                               ) AS rn
                        FROM admin_audit_logs
                    ) ranked
                    WHERE rn > :keep
                )
            """),
            {"keep": keep_per_admin},
        )
        await db.commit()
        deleted = result.rowcount
        logger.info("[audit_cleanup] Purged %d old audit rows (keep=%d)", deleted, keep_per_admin)
        return deleted
```

**Wiring in `main.py` lifespan:**

```python
# In lifespan() startup section:
async def _run_nightly_audit_cleanup():
    while True:
        await asyncio.sleep(86400)   # 24 hours
        try:
            await purge_old_audits_per_admin()
        except Exception:
            logger.exception("[audit_cleanup] Nightly purge failed")

asyncio.create_task(_run_nightly_audit_cleanup())
```

---

## 10. Frontend — Hook: `useAdminAuditHistory`

```javascript
// frontend/src/hooks/useAdminAuditHistory.js

import { useState, useEffect, useCallback } from 'react';
import { getChanges, undoChange, redoChange } from '../api/admin';

export function useAdminAuditHistory(bookSlug = null) {
  const [entries, setEntries]   = useState([]);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params = bookSlug ? { book_slug: bookSlug } : {};
      const { data } = await getChanges(params);
      setEntries(data);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [bookSlug]);

  useEffect(() => { refresh(); }, [refresh]);

  // Most recent active (not undone) entry
  const lastActive = entries.find(e => e.undone_at === null) ?? null;
  // Most recent undone entry (candidate for redo)
  const lastUndone = entries.find(e => e.undone_at !== null) ?? null;

  const canUndo = lastActive !== null;
  const canRedo = lastUndone !== null;

  const undo = useCallback(async (id, onSuccess, onStale) => {
    try {
      const { data } = await undoChange(id);
      await refresh();
      onSuccess?.(data);
    } catch (e) {
      if (e.response?.status === 409) {
        await refresh();
        onStale?.(e.response.data?.detail);
      }
      throw e;
    }
  }, [refresh]);

  const redo = useCallback(async (id, onSuccess, onStale) => {
    try {
      const { data } = await redoChange(id);
      await refresh();
      onSuccess?.(data);
    } catch (e) {
      if (e.response?.status === 409) {
        await refresh();
        onStale?.(e.response.data?.detail);
      }
      throw e;
    }
  }, [refresh]);

  return { entries, canUndo, canRedo, lastActive, lastUndone,
           undo, redo, refresh, loading, error };
}
```

---

## 11. Frontend — Hook: `useAdminKeyboardShortcuts`

```javascript
// frontend/src/hooks/useAdminKeyboardShortcuts.js

import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';

const ADMIN_ROUTE_PREFIX = '/admin';
const FOCUS_BLOCK_SELECTORS = ['input', 'textarea', 'select', '[contenteditable]'];

export function useAdminKeyboardShortcuts({ onUndo, onRedo, canUndo, canRedo }) {
  const location = useLocation();
  const debounceRef = useRef(null);

  useEffect(() => {
    if (!location.pathname.startsWith(ADMIN_ROUTE_PREFIX)) return;

    const handleKeyDown = (e) => {
      // Suppress when focus is in a text-input context
      const active = document.activeElement;
      if (active && FOCUS_BLOCK_SELECTORS.some(sel => active.matches(sel))) return;

      const isUndo = e.ctrlKey && !e.shiftKey && e.key === 'z';
      const isRedo = (e.ctrlKey && e.shiftKey && e.key === 'z') ||
                     (e.ctrlKey && e.key === 'y');

      if (!isUndo && !isRedo) return;
      e.preventDefault();

      // 300ms debounce to prevent accidental double-trigger
      if (debounceRef.current) return;
      debounceRef.current = setTimeout(() => { debounceRef.current = null; }, 300);

      if (isUndo && canUndo) onUndo();
      if (isRedo && canRedo) onRedo();
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [location.pathname, onUndo, onRedo, canUndo, canRedo]);
}
```

---

## 12. Frontend — Component: `UndoRedoControls`

```jsx
// frontend/src/components/admin/UndoRedoControls.jsx
// Renders two icon buttons in AdminTopBar.
// Confirmation dialog shown for hard actions (merge/split/promote).

const HARD_ACTIONS = new Set(['merge_chunks', 'split_chunk', 'promote']);

export function UndoRedoControls({ bookSlug, onPageRefresh }) {
  const { canUndo, canRedo, lastActive, lastUndone, undo, redo, refresh }
    = useAdminAuditHistory(bookSlug);
  const [confirming, setConfirming] = useState(null); // 'undo' | 'redo' | null
  const toast = useAdminToast();
  const { clearDrafts } = useDraftMode();

  const handleUndo = async () => {
    if (!lastActive) return;
    if (HARD_ACTIONS.has(lastActive.action_type)) {
      setConfirming('undo'); return;       // show confirmation dialog first
    }
    await executeUndo(lastActive.id);
  };

  const executeUndo = async (id) => {
    try {
      await undo(id,
        (data) => {
          toast.success(`Undone: ${data.action_type}`);
          clearDrafts();
          onPageRefresh?.();
        },
        (msg) => toast.error(msg ?? 'Resource was modified. Refresh and try again.')
      );
    } catch (e) {
      if (e.response?.status === 400) toast.error('Already undone.');
      else toast.error('Undo failed. Please try again.');
    } finally {
      setConfirming(null);
    }
  };

  // ... handleRedo follows same pattern ...

  useAdminKeyboardShortcuts({
    onUndo: handleUndo, onRedo: handleRedo,
    canUndo, canRedo
  });

  return (
    <>
      <button
        onClick={handleUndo} disabled={!canUndo}
        title="Undo (Ctrl+Z)"
        style={{ opacity: canUndo ? 1 : 0.4, cursor: canUndo ? 'pointer' : 'not-allowed' }}
      >
        <Undo2 size={18} />
      </button>
      <button
        onClick={handleRedo} disabled={!canRedo}
        title="Redo (Ctrl+Shift+Z)"
        style={{ opacity: canRedo ? 1 : 0.4, cursor: canRedo ? 'pointer' : 'not-allowed' }}
      >
        <Redo2 size={18} />
      </button>
      {confirming && (
        <ConfirmDialog
          message={`This will undo a ${confirming === 'undo' ? lastActive?.action_type : lastUndone?.action_type}. Affected sessions may see changes. Proceed?`}
          onConfirm={() => confirming === 'undo' ? executeUndo(lastActive.id) : executeRedo(lastUndone.id)}
          onCancel={() => setConfirming(null)}
        />
      )}
    </>
  );
}
```

---

## 13. Draft-Mode Conflict Handling

`AdminBookContentPage.jsx` maintains an in-memory draft stash (`useDraftMode`). Server-side undo silently invalidates these drafts.

**v1 resolution (implemented in this feature):**
1. After any undo/redo success, call `draftMode.clear()` — drops all pending frontend edits
2. Show toast: `"Your unsaved drafts were cleared because an action was undone. Please review the current state."`
3. Call `onPageRefresh()` to re-fetch section data from server

**`useDraftMode` change required:**
- Expose a `clear()` method if not already present: `const clear = () => setDrafts({})` or equivalent

**v2 resolution (deferred):** Server-sent events (SSE) channel per admin session broadcasts audit events; frontend subscribes and automatically invalidates stale drafts without requiring a page refresh.

---

## 14. Security Design

| Concern | Implementation |
|---------|---------------|
| **Authentication** | `Depends(require_admin)` on all 3 new endpoints — Bearer JWT only |
| **Authorization** | `audit.admin_id != current_user.id` → 403; enforced in both undo and redo endpoints |
| **Input validation** | `audit_id` path parameter validated as UUID by Pydantic before DB query |
| **SQL injection** | All queries use SQLAlchemy parameterized statements; no string interpolation |
| **JSONB injection** | Snapshot functions only read known ORM attributes — no raw user input in JSONB |
| **Rate limiting** | 30/min list, 10/min undo/redo — consistent with existing admin rate limits |
| **Audit of audit** | Undo/redo operations are themselves logged via `undone_by` / `undone_at` columns |

---

## 15. Observability Design

**Logging — structured log line per operation:**
```
[admin] Action 'rename_section' on 'prealgebra_1.2' by admin {admin_id} → audit_id={audit_id}
[admin] Undone action 'rename_section' ({audit_id}) by admin {admin_id}
[admin] Redo action 'rename_section' ({audit_id}) → new audit_id={new_audit_id} by admin {admin_id}
[audit_cleanup] Purged 3 old audit rows (keep=50)
[admin] Audit log failed for update_chunk {chunk_id} — proceeding  ← WARNING level
```

**Metrics to track:**
- `audit_rows_total` — counter per `action_type`
- `undo_success_total` / `undo_stale_total` — counter (stale 409s indicate concurrent edits)
- `audit_cleanup_deleted_total` — counter

**Alerting thresholds:**
- `undo_stale_total > 5/hour` — possible concurrent admin conflict — review admin workflow

---

## 16. Error Handling and Resilience

| Scenario | Handling |
|----------|---------|
| `log_action()` DB error (e.g., disk full) | `try/except` in router; `logger.warning` + mutation proceeds; no 500 to client |
| `snapshot_chunk()` raises 404 | Bubble to caller as 404 — mutation should not proceed on missing resource |
| `graph.json` missing on promote undo | Log error; raise 500 with message "graph.json not found — manual recovery required" |
| Partial undo of merge (chunk re-INSERT succeeds, session restore fails) | Transaction rolls back atomically — no partial state |
| Retention task failure | `logger.exception` + task sleeps 86400s and retries next cycle |
| Undo of already-deleted resource | `stale_check` detects `resource is None` → 409 "Resource no longer exists" |

---

## 17. Testing Strategy

### Unit Tests (`backend/tests/test_admin_audit.py`)
- 11 tests: one per action type — do action → verify audit row → undo → verify state restored → redo → verify re-applied
- Test `encode_embedding` / `decode_embedding` round-trip (exact float comparison)
- Test `stale_check` returns 409 when field differs, no-op when field matches

### Integration Tests
1. **Merge undo+redo** — full round-trip including chunk_images and session progress
2. **Split undo+redo** — full round-trip including order_index restoration
3. **Promote undo** — graph.json file round-trip; graph cache reload verified
4. **Cross-admin isolation** — Admin A's audit → Admin B attempt → 403
5. **Session progress restoration** — 3 active sessions affected by merge; all restored

### Edge-Case Tests
- **Stale undo** — external chunk edit between audit creation and undo → 409
- **Double undo** — second call → 400 "already undone"
- **Retention** — seed 51 rows → purge → 50 remain
- **Redo chain** — action → undo → redo → undo → redo; `redo_of` chain stays consistent

### Contract Tests
- `GET /api/admin/changes` response matches `AuditLogEntryResponse` Pydantic model
- `POST undo` response matches `UndoResponse`
- `POST redo` response matches `RedoResponse`

---

## Key Decisions Requiring Stakeholder Input

1. **Degraded-mode behavior**: If `log_action()` fails silently, the admin has no undo capability for that action but the mutation succeeds. Is this acceptable, or should the mutation also fail (stricter consistency)?
2. **Redo of a redo**: The redo creates a new audit row that is itself undoable. Is infinite redo-chain depth acceptable, or should redo depth be capped at 1?
3. **`useDraftMode.clear()` scope**: Should draft clearing on undo affect only the current section being edited, or all pending drafts across all sections in the page?
4. **Embedding storage budget**: At ~11 KB base64 per chunk, a merge audit row can be ~22 KB plus ~50 KB for `graph_json_before`. Confirm that 50 rows × 50 KB max = ~2.5 MB per admin is within acceptable PostgreSQL JSONB budget.
5. **Promote undo graph reload**: `reload_graph_with_overrides()` is a potentially slow operation (reads `graph.json` + applies DB overrides). Should it be done synchronously (blocks the undo response) or as a background task (response returns immediately, cache stale for seconds)?
