# Round 5 Fixes — Detailed Low-Level Design

---

## Patch 1 — Hide-Section Filter on Student Graph Endpoints

### New Helper: `get_hidden_concept_ids`

File: `backend/src/api/chunk_knowledge_service.py`

```python
async def get_hidden_concept_ids(db: AsyncSession, book_slug: str) -> set[str]:
    """Return concept_ids where ALL chunks have is_hidden=True (fully-hidden sections)."""
    rows = (await db.execute(
        select(ConceptChunk.concept_id)
        .where(ConceptChunk.book_slug == book_slug)
        .group_by(ConceptChunk.concept_id)
        .having(func.bool_and(ConceptChunk.is_hidden) == True)  # noqa: E712
    )).scalars().all()
    return set(rows)
```

- Returns empty set if no hidden concepts exist (no exception).
- `func.bool_and` is a PostgreSQL aggregate — returns True only if every row in the group is True.
- If the DB query raises, the exception propagates to the endpoint and FastAPI returns 500. No silent catch — hiding a filter failure is worse than exposing it.

### Edge Filter Algorithm

```
hidden_set = await get_hidden_concept_ids(db, book_slug)

# Node filter: drop any node whose concept_id is in hidden_set
filtered_nodes = [n for n in base_nodes if n["concept_id"] not in hidden_set]

# Edge filter: drop edge if EITHER endpoint is hidden
filtered_edges = [
    e for e in edges
    if e["source"] not in hidden_set and e["target"] not in hidden_set
]
```

**Edge cases:**

| Scenario | Behaviour |
|----------|-----------|
| Both endpoints hidden | Edge dropped |
| Only source hidden | Edge dropped (dangling target is confusing) |
| Only target hidden | Edge dropped (avoids showing an unreachable dependency) |
| No hidden concepts | `hidden_set` is empty; filter is a no-op; no overhead |
| Concept hidden mid-session (cache stale) | Request-time filter catches it on the next request |

### Endpoints Modified (all in `backend/src/api/main.py`)

| Endpoint | Change |
|----------|--------|
| `GET /api/v1/graph/full` (L530) | filter nodes + edges after existing translation block |
| `GET /api/v1/graph/topological-order` (L568) | filter `order` list |
| `GET /api/v1/concepts/{id}` (L418) | if concept_id ∈ hidden_set → raise 404 |
| `GET /api/v1/concepts/{id}/prerequisites` (L430) | filter result list |
| `GET /api/v1/concepts/{id}/images` (L445) | if concept_id ∈ hidden_set → raise 404 |
| `GET /api/v1/concepts/next` (L407) | filter `ready_to_learn` and `locked` |

Pattern used for `get_concept` and `get_concept_images` (already open a DB session via `async for _db in _get_db()`): pass `_db` to `get_hidden_concept_ids`. For endpoints that use `db: AsyncSession = Depends(get_db)`, pass `db` directly.

### Cache Invalidation Gap Fix

File: `backend/src/api/admin_router.py`, line 2881

```python
# BEFORE
await invalidate_chunk_cache(db, _section_vis_chunk_ids)

# AFTER
await invalidate_chunk_cache(db, _section_vis_chunk_ids)
try:
    invalidate_graph_cache(book_slug)  # clears in-memory graph; no-op if not cached
except Exception:
    logger.warning("[admin-invalidate] graph cache invalidation failed for book=%s", book_slug)
```

`invalidate_graph_cache` is a sync function (existing in `chunk_knowledge_service.py`); no await needed.

### Mastery Preservation

No code change. `StudentMastery` rows are never touched by this patch. Hidden sections disappear from the concept map; if unhidden, they reappear with mastery intact.

---

## Patch 2 — Per-Language Commit in `translate_catalog`

### Transaction Boundary Change

File: `backend/scripts/translate_catalog.py`, lines 357-367 (inside `_translate_table`)

```python
# BEFORE
    await db.flush()
    return rows_written, llm_calls, rows_skipped, batches_sent, retries_performed, per_item_fallbacks

# AFTER
    await db.flush()
    if not dry_run:
        await session.commit()   # survive backend restart between languages
    return rows_written, llm_calls, rows_skipped, batches_sent, retries_performed, per_item_fallbacks
```

- `db` and `session` are the same object in the current call chain (`db` is the `AsyncSession`). Use `db.commit()` (or the local alias, whichever name the function receives — verify against the function signature).
- If `commit()` raises (e.g., connection lost), the exception propagates up to `translate_book()`, which lets it crash. The next restart will re-attempt only the current language because prior languages are already committed.
- **No try/except around the commit.** Swallowing a commit failure is worse than crashing.

### Idempotency Logging in `_needs_translate`

File: `backend/scripts/translate_catalog.py`, lines 73-88

```python
def _needs_translate(translations, en_value, languages, force):
    if force:
        return True, languages
    stored_hash = translations.get("en_source_hash", "")
    current_hash = _sha1(en_value)
    if stored_hash != current_hash:
        logger.info(
            "[translate_catalog] _needs_translate: hash mismatch row stored=%s current=%s — retranslating all",
            stored_hash[:8] if stored_hash else "(none)", current_hash[:8],
        )
        return True, languages
    missing = [lang for lang in languages if not translations.get(lang)]
    if missing:
        logger.info(
            "[translate_catalog] _needs_translate: missing langs=%s — partial retranslation",
            missing,
        )
    return bool(missing), missing
```

### Test Update

File: `backend/tests/test_translate_catalog_script.py`, line 81

Replace the mock that only patches `db.flush` with a test that uses a real in-memory session (or a `MagicMock` that tracks both `flush` and `commit` calls), and asserts:

1. `commit` is called once per language after each `flush`.
2. When `_needs_translate` is called after a simulated partial commit (first language committed, second not), only the second language is returned as needing translation.

---

## Patch 3 — CHUNK_EXAM_PASS_RATE from Live AdminConfig

### New Shared Helper Module

File (new): `backend/src/services/admin_config_helper.py`

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import AdminConfig
from config import CHUNK_EXAM_PASS_RATE, OPENAI_MODEL, OPENAI_MODEL_MINI


async def get_admin_config(db: AsyncSession, key: str, fallback: str = "") -> str:
    """Live read from AdminConfig with explicit fallback. Sub-millisecond PK lookup."""
    row = (await db.execute(
        select(AdminConfig.value).where(AdminConfig.key == key)
    )).scalar_one_or_none()
    return row if row is not None else fallback


async def get_openai_model(db: AsyncSession, slot: str = "default") -> str:
    """slot ∈ {'default', 'mini'}. Live read with config.py env fallback."""
    key = "OPENAI_MODEL_MINI" if slot == "mini" else "OPENAI_MODEL"
    fallback = OPENAI_MODEL_MINI if slot == "mini" else OPENAI_MODEL
    return await get_admin_config(db, key, fallback=fallback)
```

- No caching. No module-level state. Thread-safe by design.
- If `db.execute` raises, exception propagates to caller. Callers already have error handling at the HTTP layer.

### teaching_router.py Changes (2 sites)

```python
# ADD import at top of teaching_router.py
from services.admin_config_helper import get_admin_config

# LINE 1285 — inside chunk_progress endpoint
# BEFORE
_cc_passed = score >= round(CHUNK_EXAM_PASS_RATE * 100)

# AFTER
_raw_rate = await get_admin_config(db, "CHUNK_EXAM_PASS_RATE", fallback=str(CHUNK_EXAM_PASS_RATE))
_live_pass_rate = float(_raw_rate)
_cc_passed = score >= round(_live_pass_rate * 100)

# LINE 1530 — inside evaluate-chunk endpoint
# BEFORE
passed = score_frac >= CHUNK_EXAM_PASS_RATE

# AFTER
_raw_rate = await get_admin_config(db, "CHUNK_EXAM_PASS_RATE", fallback=str(CHUNK_EXAM_PASS_RATE))
_live_pass_rate = float(_raw_rate)
passed = score_frac >= _live_pass_rate
```

`CHUNK_EXAM_PASS_RATE` import in `teaching_router.py` is kept as the fallback default. No constant is removed.

---

## Patch 4 — OPENAI_MODEL from Live AdminConfig

### TeachingService Refactor (Before / After)

`teaching_service.py` currently captures the model at `__init__`:

```python
# BEFORE — __init__ (line ~445)
def __init__(self, knowledge_svc: ChunkKnowledgeService):
    self.knowledge_svc = knowledge_svc
    self.model = OPENAI_MODEL
    self.model_mini = OPENAI_MODEL_MINI
    self.client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
```

```python
# AFTER — __init__
def __init__(self, knowledge_svc: ChunkKnowledgeService):
    self.knowledge_svc = knowledge_svc
    self.client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    # model resolved per operation, not captured here
```

Each public entry point resolves the model once at the top:

```python
async def generate_per_chunk(self, db: AsyncSession, ...) -> ...:
    model = await get_openai_model(db, slot="default")
    model_mini = await get_openai_model(db, slot="mini")
    # use model / model_mini throughout this function; never re-read
    ...
```

**Mid-run guarantee:** within a single call to `generate_per_chunk` or `evaluate_exam`, `model` is a local variable — an AdminConfig change mid-function has no effect. The new value takes effect on the next top-level call.

### Other 6 Files — Read-Once Pattern

| File | Entry point where model is resolved |
|------|-------------------------------------|
| `teaching_router.py` (L1828) | At top of the endpoint handler before first LLM call |
| `adaptive_engine.py` (L199) | At top of `generate_card_batch` or equivalent entry |
| `translation_helper.py` (L72) | At top of `translate_texts` / main public function |
| `llm_extractor.py` (L286) | At top of `extract_*` entry points |
| `graph_builder.py` (L144) | At top of `build_graph` or equivalent |
| `translate_catalog.py` (L34) | At top of `translate_book()`, passed through to `_translate_table` |

`translate_catalog.py` passes the resolved model as a parameter so that all languages in one book run use the same model string. Pattern:

```python
async def translate_book(slug, db, ...):
    model = await get_openai_model(db, slot="default")
    ...
    await _translate_table(..., model=model)
```

### Exception Handling

If `get_openai_model` fails (DB unreachable), the exception propagates and the endpoint returns 500. This is preferable to silently using a stale module-level constant when the intent is live resolution.

---

## Observability Additions

| Patch | Log added |
|-------|-----------|
| P1 | DEBUG: `[graph-filter] book=%s hidden_concepts=%d` when hidden_set is non-empty |
| P2 | INFO: `[translate_catalog] committed language=%s rows=%d` after each commit; existing `_needs_translate` INFO lines (see above) |
| P3 | DEBUG: `[exam-gate] live CHUNK_EXAM_PASS_RATE=%.2f` at each evaluation |
| P4 | DEBUG: `[llm] resolved model=%s slot=%s` once per operation |

---

## Key Decisions Requiring Stakeholder Input

1. **P1 `next_concepts` endpoint:** `get_next_concepts` and `get_locked_concepts` return concept_id strings from the graph cache. Should the filter remove hidden IDs from both `ready_to_learn` and `locked`, or only from `ready_to_learn`? Current proposal: filter both.
2. **P4 extraction scripts:** `llm_extractor.py` and `graph_builder.py` run as offline pipeline tools (not during live requests). They do not have a `db` session available at their current entry points. If adapting them is out of scope, they can keep the module-level import as-is and be addressed in a future patch.
3. **P2 `session` vs `db` naming:** Verify whether the `_translate_table` function receives the session under the name `db` or `session` before implementing the commit call.
