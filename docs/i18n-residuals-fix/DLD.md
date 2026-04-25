# Detailed Low-Level Design — i18n Residuals Fix

**Feature slug:** `i18n-residuals-fix`
**Date:** 2026-04-24
**Status:** Approved — Phase 0 design

---

## 1. Component Breakdown

| Component | File | Responsibility |
|-----------|------|---------------|
| ORM model extension | `backend/src/db/models.py` | Add `admin_section_name_translations` mapped column to `ConceptChunk` |
| Translation helper | `backend/src/api/translation_helper.py` (NEW) | `translate_one_string()` — single-string LLM translation reusing primitives from `translate_catalog.py` |
| Rename handler | `backend/src/api/admin_router.py` | Wire translation call after `UPDATE admin_section_name`; extend audit payload |
| Display-path fix | `backend/src/api/teaching_router.py` | Use `admin_section_name_translations` in `resolve_translation` instead of `{}` |
| Audit snapshot | `backend/src/api/audit_service.py` | Extend `snapshot_section` and `_undo_rename_section` to cover the new column |
| Alembic migration | `backend/alembic/versions/022_add_admin_section_name_translations.py` (NEW) | `op.add_column` on `concept_chunks`; `downgrade` drops it |
| Frontend dialogs | `frontend/src/pages/AdminReviewPage.jsx` | Replace 3 `window.prompt` calls with `useDialog().prompt()` |
| Locale keys | `frontend/src/locales/*.json` (13 files) | Add 3 new `adminReview.*` keys |

---

## 2. Data Design

### 2.1 New column

```sql
-- On table: concept_chunks
admin_section_name_translations  JSONB  NOT NULL  DEFAULT '{}'::jsonb
```

**Schema of stored value:**
```json
{
  "en_source_hash": "sha1hex",
  "ar": "...",
  "de": "...",
  "es": "...",
  "fr": "...",
  "hi": "...",
  "ja": "...",
  "ko": "...",
  "ml": "...",
  "pt": "...",
  "si": "...",
  "ta": "...",
  "zh": "..."
}
```

Note: `en_source_hash` is stored so that a future re-trigger of `translate_catalog.py` can detect a changed English rename and re-translate. The `translate_one_string` helper must store it alongside the language translations.

**Existing `heading_translations` pattern (reference):**
Same shape — `{"en_source_hash": "...", "ar": "...", ...}`. The column is defined in `db/models.py` as:
```python
heading_translations: Mapped[dict] = mapped_column(
    JSONB, nullable=False, server_default=text("'{}'::jsonb")
)
```

### 2.2 ORM model extension

In `backend/src/db/models.py`, add immediately after the `admin_section_name` column declaration in `ConceptChunk`:

```python
admin_section_name_translations: Mapped[dict] = mapped_column(
    JSONB, nullable=False, server_default=text("'{}'::jsonb")
)
```

**Import:** `JSONB` is already imported via `from sqlalchemy.dialects.postgresql import JSONB` (used by `heading_translations`). Confirm presence before adding.

### 2.3 Data flow

```
Admin PATCH /rename
  │
  ├─► [1] UPDATE concept_chunks SET admin_section_name = :name
  │         WHERE concept_id = :cid AND book_slug = :slug
  │
  ├─► [2] translate_one_string(name) → {"ar": "...", "ml": "...", ...}
  │         (async, awaited, wrapped in asyncio.timeout(10.0))
  │
  ├─► [3] UPDATE concept_chunks
  │         SET admin_section_name_translations = :translations_json
  │         WHERE concept_id = :cid AND book_slug = :slug
  │
  ├─► [4] audit_service.log_action(old_value includes admin_section_name_translations snapshot)
  │
  ├─► [5] invalidate_chunk_cache(affected_chunk_ids)
  │
  └─► [6] db.commit()

Student GET /chunks
  └─► resolve_translation(
          admin_section_name or section,
          admin_section_name_translations or {},   ← WAS hardcoded {}
          lang
      )
```

### 2.4 Caching

No change to caching strategy. `invalidate_chunk_cache` already clears all per-language cache variants for affected chunk IDs. After a rename + translation, the next student fetch re-populates the cache with the translated `section_title`.

### 2.5 Data retention

No change. `admin_section_name_translations` lives on the `concept_chunks` row. Alembic downgrade drops the column (translations are regeneratable from `admin_section_name`).

---

## 3. API Design

No new endpoints. This fix modifies two existing handlers.

### 3.1 Modified: `PATCH /api/admin/sections/{concept_id}/rename`

**Behaviour change:** Response is delayed ~2s while OpenAI translates the new name. No change to request/response schema.

**Current response (unchanged):**
```json
{
  "concept_id": "string",
  "admin_section_name": "string",
  "chunks_updated": 1
}
```

**Error scenarios:**
- OpenAI timeout or error: rename still succeeds; `admin_section_name_translations` stays `{}` (or retains previous translations if any); warning logged.
- DB error on translation UPDATE: caught by outer try/except in handler; rename commit still proceeds.

### 3.2 Modified: `GET /api/v2/sessions/{session_id}/chunks/{concept_id}`

**Behaviour change:** `section_title` in the response now returns the translated section name for non-English students when an admin has set a custom name.

No schema change to `ChunkListResponse`.

### 3.3 Versioning

No version change. Both endpoints are in-place fixes to existing v2 behaviour.

---

## 4. New Module: `translation_helper.py`

**Location:** `backend/src/api/translation_helper.py`

**Public signature:**

```python
async def translate_one_string(
    text: str,
    target_langs: list[str] | None = None,   # defaults to all 12 non-English codes
    openai_client: openai.AsyncOpenAI | None = None,
) -> dict[str, str]:
    """Translate *text* into all 12 non-English locales (or *target_langs* if given).

    Returns dict with LANGUAGE_NAMES lang codes + "en_source_hash" key.
    Any per-language failure: that key is omitted. Total failure: returns {}.
    Caller should wrap in asyncio.timeout(10.0).
    """
```

**Internal structure (three private helpers):**

| Helper | Reuses from `translate_catalog.py` | Purpose |
|--------|-----------------------------------|---------|
| `_sha1(text)` | identical | SHA-1 fingerprint for staleness detection |
| `_build_system_prompt(lang)` | logic equivalent | System prompt per target language |
| `_call_llm_once(client, text, lang)` | pattern of existing `_call_llm_once` | Single OpenAI call, markdown-fence strip, JSON parse, length check |
| `_translate_one_lang_with_retry(client, text, lang)` | pattern of `_translate_batch_with_retry` | 5 retries on `[2,4,8,16,32]`s back-off; returns `None` on total failure |

**Algorithm:**
1. Guard: empty `text` → return `{}`.
2. Instantiate `openai.AsyncOpenAI` from `config.OPENAI_API_KEY` / `config.OPENAI_BASE_URL` if no client passed.
3. Launch `asyncio.gather` of 12 `_translate_one_lang_with_retry` coroutines (one per lang) — wall time ≈ slowest single call (~1–2 s), not 12×.
4. Build result dict: `{"en_source_hash": _sha1(text), lang: translated, ...}` — omit any lang whose coroutine raised or returned `None`.
5. Return dict (may be partial on failures).

**Imports required:** `asyncio`, `hashlib`, `json`, `logging`, `re`, `openai`; `from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL_MINI`; `from api.prompts import LANGUAGE_NAMES`.

---

## 5. Rename Handler Hook — `admin_router.py`

**Insertion point:** After line 2493 (`chunks_updated = result.rowcount`) and before `audit_service.log_action`. This ordering means the translation happens before the audit record is written, so `new_value` in the audit captures the translation state.

**Exact diff (lines 2494–2518 current, after insertion):**

```python
    chunks_updated = result.rowcount

    # ── NEW: translate the new section name into all 12 non-English locales ──
    translations: dict = {}
    try:
        import asyncio
        from api.translation_helper import translate_one_string
        async with asyncio.timeout(10.0):
            translations = await translate_one_string(str(name))
        if translations:
            await db.execute(
                text(
                    "UPDATE concept_chunks "
                    "SET admin_section_name_translations = :t "
                    "WHERE concept_id = :cid AND book_slug = :slug"
                ),
                {"t": json.dumps(translations), "cid": concept_id, "slug": book_slug},
            )
            logger.info(
                "[admin] admin_section_name_translations populated for concept=%s (%d langs)",
                concept_id, len(translations) - 1,  # minus en_source_hash
            )
    except Exception:
        logger.warning(
            "[admin] admin_section_name translation failed — English name will be shown "
            "until a manual re-trigger. concept=%s",
            concept_id,
        )
    # ── END NEW ──

    try:
        await audit_service.log_action(
            db,
            admin_id=_user.id,
            action_type="rename_section",
            resource_type="section",
            resource_id=concept_id,
            book_slug=book_slug,
            old_value={
                "admin_section_name": old_name,
                "admin_section_name_translations": section_snap[0].get(
                    "admin_section_name_translations", {}
                ) if section_snap else {},
                "affected_chunk_ids": affected_chunk_ids,
            },
            new_value={
                "admin_section_name": str(name),
                "admin_section_name_translations": translations,
            },
            affected_count=chunks_updated,
        )
    except Exception:
        logger.warning("[admin] Audit log failed for rename_section — proceeding")
```

**Import additions required at top of `admin_router.py`:**
- `import json` (may already be present — verify)
- `from api.translation_helper import translate_one_string` (add with other local imports)

---

## 6. Display-Path Fix — `teaching_router.py`

**Current code (lines 1721–1726):**

```python
            if section_title and chunks:
                section_title = resolve_translation(
                    chunks[0].admin_section_name or chunks[0].section or "",
                    {},
                    lang,
                )
```

**Fixed code:**

```python
            if section_title and chunks:
                # Use admin-set translations if available; fall back to heading_translations.
                trans = (
                    chunks[0].admin_section_name_translations or {}
                    if chunks[0].admin_section_name
                    else chunks[0].heading_translations or {}
                )
                section_title = resolve_translation(
                    chunks[0].admin_section_name or chunks[0].section or "",
                    trans,
                    lang,
                )
```

**Fallback logic explained:**
1. If `admin_section_name` is set → use `admin_section_name_translations` (the new column).
2. If `admin_section_name` is not set → use `heading_translations` (the original section heading).
3. If either translations dict is `{}` or the lang key is missing, `resolve_translation` returns the English source string (existing fallback behaviour).

---

## 7. Audit Service Extension — `audit_service.py`

### 7.1 `snapshot_section` extension

Current dict returned per chunk (lines 141–151) does not include `admin_section_name_translations`. Extend:

```python
    return [
        {
            "id": str(c.id),
            "concept_id": c.concept_id,
            "section": c.section,
            "order_index": c.order_index,
            "is_hidden": c.is_hidden,
            "chunk_type_locked": c.chunk_type_locked,
            "is_optional": c.is_optional,
            "exam_disabled": c.exam_disabled,
            "admin_section_name": c.admin_section_name,
            "admin_section_name_translations": c.admin_section_name_translations or {},  # NEW
        }
        for c in chunks
    ]
```

### 7.2 `_undo_rename_section` extension

Current handler (lines 419–432) restores `admin_section_name` only. Extend:

```python
async def _undo_rename_section(db: AsyncSession, audit: AdminAuditLog) -> None:
    old = audit.old_value
    original_name = old.get("admin_section_name")
    original_translations = old.get("admin_section_name_translations", {})  # NEW
    chunk_ids = old.get("affected_chunk_ids", [])
    for chunk_id_str in chunk_ids:
        chunk = await db.get(ConceptChunk, UUID(chunk_id_str))
        if chunk is None:
            continue
        chunk.admin_section_name = original_name
        chunk.admin_section_name_translations = original_translations  # NEW
    await invalidate_chunk_cache(db, chunk_ids)
    await db.flush()
```

### 7.3 `apply_redo` rename_section branch extension

In `apply_redo` (lines 755–761), extend to restore translations:

```python
    elif action == "rename_section":
        new_name = audit.new_value.get("admin_section_name")
        new_translations = audit.new_value.get("admin_section_name_translations", {})  # NEW
        for chunk_id_str in audit.old_value.get("affected_chunk_ids", []):
            chunk = await db.get(ConceptChunk, UUID(chunk_id_str))
            if chunk is None:
                continue
            chunk.admin_section_name = new_name
            chunk.admin_section_name_translations = new_translations  # NEW
```

### 7.4 `stale_check` for `rename_section`

The existing stale check (lines 283–295) checks `admin_section_name` only. No change required — the translations column is derived from the name, so checking the name is sufficient for staleness detection.

---

## 8. Alembic Migration Skeleton — `022_add_admin_section_name_translations.py`

Mirror the pattern of `021_add_i18n_translation_columns.py` exactly:

```python
"""Add admin_section_name_translations JSONB column to concept_chunks

Revision ID: 022_add_admin_section_name_translations
Revises: 021_add_i18n_translation_columns
Create Date: 2026-04-24

Adds one JSONB column (default '{}') to concept_chunks:
  concept_chunks.admin_section_name_translations

NOT NULL with server_default '{}'::jsonb — every existing row is immediately
valid. No data backfill required — English fallback operates from the empty
dict until translate_catalog.py or the rename handler populates it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '022_add_admin_section_name_translations'
down_revision: Union[str, Sequence[str], None] = '021_add_i18n_translation_columns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSONB_EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.add_column(
        'concept_chunks',
        sa.Column(
            'admin_section_name_translations',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=_JSONB_EMPTY,
        ),
    )


def downgrade() -> None:
    op.drop_column('concept_chunks', 'admin_section_name_translations')
```

**Note on `down_revision`:** The actual `down_revision` must be the revision ID of the last applied migration in the chain. `021_add_i18n_translation_columns` is the direct predecessor per plan. Verify with `alembic current` before creating.

---

## 9. Locale Keys Catalogue

### AdminReviewPage.jsx — current `window.prompt` calls (verified from source)

| Locale key (new) | Current line | Current English string (exact) | Handler |
|-----------------|-------------|-------------------------------|---------|
| `adminReview.promptNewHeading` | 387 | `"New heading:"` | `handleRenameChunkHeading` |
| `adminReview.promptPromoteLabel` | 465 | `"New section label (leave blank to use chunk heading):"` | `handlePromoteToSection` |
| `adminReview.promptNewSectionName` | 501 | `"New section name:"` | `handleRenameSection` |

**Note on line numbers:** Lines 387, 465, and 501 were verified against the current file. The `window.prompt` at line 387 passes `chunk.heading` as a default; line 465 passes `chunk.heading`; line 501 passes `sec.heading || sec.section`. The default value parameter maps to `dialog.prompt({ ..., defaultValue: ... })`.

### Replacement pattern (mirror `AdminBookContentPage.jsx`)

Current (line 387):
```jsx
const newHeading = window.prompt("New heading:", chunk.heading || "");
```

Replacement:
```jsx
const newHeading = await dialog.prompt({
  title: t("adminReview.promptNewHeading"),
  defaultValue: chunk.heading || "",
});
```

Current (line 465):
```jsx
const label = window.prompt(
  "New section label (leave blank to use chunk heading):",
  chunk.heading || ""
);
```

Replacement:
```jsx
const label = await dialog.prompt({
  title: t("adminReview.promptPromoteLabel"),
  defaultValue: chunk.heading || "",
});
```

Current (line 501):
```jsx
const newName = window.prompt("New section name:", sec.heading || sec.section || "");
```

Replacement:
```jsx
const newName = await dialog.prompt({
  title: t("adminReview.promptNewSectionName"),
  defaultValue: sec.heading || sec.section || "",
});
```

### `useDialog` import

`AdminReviewPage.jsx` does NOT currently import `useDialog`. Add:
```jsx
import { useDialog } from "../context/DialogProvider";
```

And inside the component function where the handlers live, add:
```jsx
const dialog = useDialog();
```

### New locale key values (all 13 files)

Add to `frontend/src/locales/en.json` under an `adminReview` namespace:
```json
"adminReview": {
  "promptNewHeading": "New heading:",
  "promptPromoteLabel": "New section label (leave blank to use chunk heading):",
  "promptNewSectionName": "New section name:"
}
```

Then run `frontend/scripts/translate_locales.py` to populate `ar.json`, `de.json`, `es.json`, `fr.json`, `hi.json`, `ja.json`, `ko.json`, `ml.json`, `pt.json`, `si.json`, `ta.json`, `zh.json`.

---

## 10. Sequence Diagrams

**Happy path (admin rename → student fetch):**
1. Admin `PATCH /rename` → `UPDATE admin_section_name` → `translate_one_string(name)` (12 concurrent OpenAI calls, ~1-2s) → `UPDATE admin_section_name_translations` → `audit_service.log_action` → `invalidate_chunk_cache` → `db.commit()` → 200 OK.
2. Student `GET /chunks/{concept_id}` → `SELECT ... admin_section_name_translations` → `resolve_translation(name, translations, "ml")` → `section_title = "1.1 സാധ്യതയുടെ അടിസ്ഥാനങ്ങള്‍"` in response.

**Failure path (OpenAI error):**
`asyncio.timeout(10.0)` fires → caught by `except Exception` → `translations = {}` → second UPDATE skipped → audit + `db.commit()` proceed → 200 OK returned; students see English until next rename.

**Undo path:**
`POST /undo/{audit_id}` → `apply_undo` → `_undo_rename_section` restores `chunk.admin_section_name = old_name` AND `chunk.admin_section_name_translations = old_translations` → `invalidate_chunk_cache` → `db.commit()` → 200 OK.

---

## 11. Security Design

No new attack surface introduced.

- `translate_one_string` input: the `name` parameter comes from `request.json()["name"]`, already validated as a non-None string in the rename handler. No injection risk into SQL (parameterised query). Sent to OpenAI as a plain string in a JSON array — no prompt injection risk for a section name.
- The translation result is stored via a parameterised `json.dumps(translations)` bind — no SQL injection.
- `admin_section_name_translations` is read-only to students via the teaching_router — no student can write to it.
- Locale key additions are static strings — no XSS risk.

---

## 12. Observability Design

### Logging

| Location | Log level | Message |
|----------|-----------|---------|
| `translation_helper.py` | `WARNING` | Per-language retry exhausted |
| `translation_helper.py` | `WARNING` | Exception from `asyncio.gather` for a language |
| `admin_router.py` | `INFO` | `admin_section_name_translations populated for concept=X (12 langs)` |
| `admin_router.py` | `WARNING` | `admin_section_name translation failed — English name will be shown` |

All logging uses structured format with `concept_id` in message for grep-ability. No new metrics or dashboards required — rename volume is negligible.

---

## 13. Error Handling and Resilience

| Failure | Handling |
|---------|---------|
| OpenAI timeout (>10s) | `asyncio.timeout(10.0)` fires `TimeoutError`; caught by broad `except Exception`; rename succeeds; `admin_section_name_translations` stays `{}` |
| OpenAI returns wrong count | `ValueError` caught by retry loop in `_call_llm_once`; up to 5 retries per language; total wall time bounded by outer `asyncio.timeout` |
| One of 12 language tasks raises | `asyncio.gather` returns the exception object for that task; caught in result loop; that language is omitted from dict |
| DB error on translations UPDATE | Caught by broad `except Exception` in rename handler; rename name UPDATE already committed (separate prior statement); warning logged |
| `admin_section_name_translations` column absent (pre-migration) | SQLAlchemy raises `ProgrammingError` on attribute access; deploy migration before code |

---

## 14. Testing Strategy

Covered in execution-plan.md Phase 3. Summary:

- **Unit tests** (`test_admin_rename_translation.py`): mock `translate_one_string`; assert DB state, response shape, failure mode, undo restoration.
- **Audit extension tests** (`test_admin_audit.py`): assert snapshot includes `admin_section_name_translations`; assert undo restores both columns.
- **Integration test**: actual rename with mocked OpenAI (no live API calls in CI); verify chunk-list response returns translated `section_title`.
- **Frontend**: `npm run lint` + `npm run build` clean; manual spot-check of 3 dialogs in Malayalam locale.

---

## Key Decisions Requiring Stakeholder Input

1. **Concurrent vs. sequential language translation in `translate_one_string`:** The design above uses `asyncio.gather` for 12 concurrent calls. If OpenAI rate limits are a concern for high-volume admin rename sessions, consider batching (all 12 languages in one call using the existing `_llm_translate_batch` pattern). Current choice is concurrent for lower latency.

2. **`en_source_hash` storage in `admin_section_name_translations`:** Storing the SHA-1 hash allows `translate_catalog.py` to detect stale renames. If `translate_catalog.py` is never expected to touch this column, the hash can be omitted to simplify the dict schema. Confirm with the team.

3. **Backfill of existing renamed sections:** Sections renamed before this fix have `{}` translations. A one-off migration script can backfill them. No action required to ship, but product should confirm whether admins will be asked to re-save or a backfill will be run.
