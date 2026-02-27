# Backend Developer Memory — ADA Platform

## Project Overview
FastAPI async backend for ADA adaptive learning platform.
Working dir: `c:\files\Desktop\ADA\`
Backend source root: `c:\files\Desktop\ADA\backend\src\`
sys.path convention: `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` so all imports
inside `backend/src/` use bare package names (`from api.knowledge_service import ...`, `from db.models import ...`).

## Key Architectural Decisions

### Service injection pattern (all routers)
Module-level globals set by `main.py` lifespan — never constructor injection.
```python
# In router module (e.g., adaptive_router.py):
some_svc = None    # set by main.py
# In main.py lifespan:
some_router_module.some_svc = SomeService(...)
```

### Router prefix convention
- `/api/v1` — RAG + graph (main.py inline handlers)
- `/api/v2` — Teaching/Socratic loop (api/teaching_router.py)
- `/api/v3` — Adaptive Learning Engine (adaptive/adaptive_router.py)

### LLM retry pattern (3 attempts, exponential back-off)
```python
for attempt in range(1, 4):
    try:
        response = await client.chat.completions.create(...)
        content = response.choices[0].message.content or ""
        if content.strip(): return content
    except Exception as exc:
        last_exc = exc
    if attempt < 3:
        await asyncio.sleep(2 * attempt)
raise ValueError(f"LLM failed after 3 attempts: {last_exc}")
```

### JSON parsing helpers (replicate locally in each module — do NOT cross-import)
```python
def _extract_json_block(raw: str) -> str:
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    return m.group(1).strip() if m else raw.strip()

def _salvage_truncated_json(raw: str) -> str:
    raw = raw.rstrip()
    raw += "]" * max(0, raw.count("[") - raw.count("]"))
    raw += "}" * max(0, raw.count("{") - raw.count("}"))
    return raw
```

## Adaptive Learning Engine (backend/src/adaptive/)
Files: `__init__.py`, `schemas.py`, `profile_builder.py`, `generation_profile.py`,
`remediation.py`, `prompt_builder.py`, `adaptive_engine.py`, `adaptive_router.py`

Key design:
- `build_learning_profile(analytics, has_unmet_prereq)` — pure, deterministic
- `build_generation_profile(learning_profile)` — 9-cell lookup table (speed × comprehension) + engagement modifiers
- `find_remediation_prereq(concept_id, knowledge_svc, mastery_store)` — one-hop graph traversal, no I/O
- `build_remediation_cards(prereq_id, prereq_detail)` — template-based, 3 cards, no LLM call
- `build_adaptive_prompt(concept_detail, learning_profile, gen_profile, prereq_detail, language)` — pure, returns (system, user) tuple
- `generate_adaptive_lesson(...)` — async orchestrator, calls all of the above + LLM
- Router: `POST /api/v3/adaptive/lesson` — loads mastery store from DB (bulk SELECT), then calls engine

Config constants added: `ADAPTIVE_ERROR_PENALTY_WEIGHT = 0.4`, `ADAPTIVE_HINT_PENALTY_WEIGHT = 0.2`

## DB Schema
- `students` — id (UUID PK), display_name, interests, preferred_style, preferred_language
- `student_mastery` — id, student_id (FK), concept_id, mastered_at, session_id
- `card_interactions` — id, session_id, student_id, concept_id, card_index, time_on_card_sec (Float), wrong_attempts, selected_wrong_option (SmallInt nullable), hints_used, idle_triggers, adaptation_applied (nullable), completed_at
- `spaced_reviews` — id, student_id, concept_id, review_number (SmallInt), due_at, completed_at (nullable)

## KnowledgeService contract (knowledge_svc)
- `knowledge_svc.get_concept_detail(concept_id) -> dict | None`
  Keys: concept_title, chapter, section, text, latex (list), images (list), prerequisites (list)
- `knowledge_svc.graph` — NetworkX DiGraph; use `.predecessors(concept_id)` for direct prereqs

## Logging convention
All modules: `logger = logging.getLogger(__name__)` — never `print()`.
Log key structured events at INFO, retries at WARNING, failures at ERROR.

## Concept Enrichment Feature (implemented 2026-02-26)

### Sub-feature A — LaTeX in ChromaDB
- `chroma_store.store_concept_blocks()` now serialises `block.latex` as
  `"latex_expressions": json.dumps(block.latex, ensure_ascii=False)`.
- `LATEX_METADATA_SIZE_WARN_THRESHOLD = 8192` (bytes) in `config.py` — warn, don't error.
- `knowledge_service._get_latex(concept_id, chroma_metadata=None)` prefers
  `latex_expressions` from the already-fetched ChromaDB metadata dict (no second DB call);
  falls back to `_latex_map` from `concept_blocks.json` for old collections or parse failures.
- `get_concept_detail()` passes `chroma_metadata=metadata` to `_get_latex()`.
- `query_concept_with_prerequisites()` passes nothing — uses fallback path (metadata not available
  from a `query` call, only from `get`).

### Sub-feature B — Image Semantic Annotation
- `vision_annotator.annotate_image()` at `backend/src/images/vision_annotator.py`:
  async, MD5-keyed disk cache at `output/{book_slug}/vision_cache/vision_{md5}.json`.
  Skips DECORATIVE. Returns `{"description": None, "relevance": None}` on any failure — never raises.
- `extract_images.extract_and_save_images()` is now async. Accepts `annotate: bool = True` flag.
  Instantiates one `AsyncOpenAI` client per run. Uses `asyncio.sleep(VISION_RATE_LIMIT)` between calls.
  `__main__` block uses `asyncio.run(...)` with `--no-annotate` flag.
  `VISION_RATE_LIMIT = 0.5` seconds in `config.py`.
- `knowledge_service.get_concept_images()` now returns `description` and `relevance`
  from `_image_map` (loaded from `image_index.json` at startup; `None` if not annotated).
- `ConceptImage` Pydantic schema: added `description: str | None = None` and
  `relevance: str | None = None` (backward-compatible).

### ChromaDB metadata note
All list values stored as JSON-serialised strings — ChromaDB does not support list metadata values.

## Complete Adaptive Real Tutor Feature (implemented 2026-02-27)

### New endpoints
- `POST /api/v2/sessions/{session_id}/complete-card` — in `adaptive_router.py` via `cards_router` (no prefix), registered separately in `main.py` as `adaptive_cards_router`. Records CardInteraction, blends signals with history, generates next adaptive card via LLM (gpt-4o-mini). Returns 409 `{"ceiling": True}` at 8-card limit.
- `GET /api/v2/students/{student_id}/review-due` — in `teaching_router.py`. Returns SpacedReview rows where `due_at <= now` and `completed_at IS NULL`.

### Two-router pattern in adaptive_router.py
`router` (prefix `/api/v3`) + `cards_router` (no prefix, full paths) both exported. `main.py` imports both:
```python
from adaptive.adaptive_router import router as adaptive_router, cards_router as adaptive_cards_router
app.include_router(adaptive_router)
app.include_router(adaptive_cards_router)
```

### New adaptive engine functions (adaptive_engine.py)
- `load_student_history(student_id, concept_id, db) -> dict` — async, 5 DB queries, returns baselines + trend + weak-concept flag
- `build_blended_analytics(current, history, concept_id, student_id) -> AnalyticsSummary` — sync, blends 60/40 or 90/10 based on deviation detection
- `generate_next_card(...)` — async orchestrator, uses OPENAI_MODEL_MINI, returns (card_dict, profile, gen_profile, motivational_note)

### New prompt builder function (prompt_builder.py)
- `build_next_card_prompt(...)` — reuses `_build_system_prompt()` + appends override block with `_NEXT_CARD_JSON_SCHEMA`; single-card output, no `concept_explanation` key

### SpacedReview creation on mastery
`teaching_service.py` `handle_student_response()` now creates 5 SpacedReview rows after mastery (days: 1, 3, 7, 14, 30).

### Socratic profile injection
`begin_socratic_check()` calls `load_student_history()` and, if >= 5 cards completed, builds `AnalyticsSummary` + `LearningProfile` from aggregate history. Passes `socratic_profile` and `history` to `build_socratic_system_prompt()`.

### build_socratic_system_prompt extended signature
Added `socratic_profile=None` and `history=None` params. Appends STUDENT CONTEXT block at end of prompt for STRUGGLING/STRONG/BORED profiles and known-weak-concept flag.

## Detailed notes
See `patterns.md` for generation_profile lookup table and profile_builder classification rules.
