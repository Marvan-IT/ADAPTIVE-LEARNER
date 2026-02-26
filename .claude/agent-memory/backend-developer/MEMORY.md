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

## DB Schema (read-only tables used by adaptive engine)
- `students` — id (UUID PK), display_name, interests, preferred_style, preferred_language
- `student_mastery` — id, student_id (FK), concept_id, mastered_at, session_id

## KnowledgeService contract (knowledge_svc)
- `knowledge_svc.get_concept_detail(concept_id) -> dict | None`
  Keys: concept_title, chapter, section, text, latex (list), images (list), prerequisites (list)
- `knowledge_svc.graph` — NetworkX DiGraph; use `.predecessors(concept_id)` for direct prereqs

## Logging convention
All modules: `logger = logging.getLogger(__name__)` — never `print()`.
Log key structured events at INFO, retries at WARNING, failures at ERROR.

## Detailed notes
See `patterns.md` for generation_profile lookup table and profile_builder classification rules.
