# Comprehensive Tester — Persistent Memory

## Project: ADA Adaptive Learning Platform

### Test Infrastructure
- pytest 8+, pytest-asyncio 0.23+; `asyncio_mode = auto` in `backend/pytest.ini`
- No `@pytest.mark.asyncio` needed — all async test methods work automatically
- `conftest.py` inserts `backend/src` into sys.path; test files duplicate this with `sys.path.insert(0, ...parent.parent/"src")` for direct execution safety
- Test files live in `backend/tests/`; run from repo root with `pytest backend/tests/`

### Adaptive Engine Module (backend/src/adaptive/)
- `schemas.py` — Pydantic v2 models: AnalyticsSummary, LearningProfile, GenerationProfile, AdaptiveLesson, RemediationInfo, AdaptiveLessonCard, AdaptiveLessonContent
- `profile_builder.py` — pure functions; `classify_next_step(comprehension, speed, has_unmet_prereq)` (comprehension is FIRST arg)
- `generation_profile.py` — `build_generation_profile(LearningProfile)` → 9-cell lookup + engagement modifiers
- `remediation.py` — graph.predecessors() returns iterator; wrap with `iter([...])` in mocks
- `prompt_builder.py` — `build_adaptive_prompt()` returns `(system_prompt, user_prompt)` tuple
- `adaptive_engine.py` — `generate_adaptive_lesson()` async; patches `adaptive.adaptive_engine.asyncio.sleep` for retry tests

### Mocking Patterns
- LLM mock: `AsyncMock` with `mock_llm.chat.completions.create = AsyncMock(return_value=mock_response)`; `mock_response.choices[0].message.content = "<json string>"`
- KnowledgeService mock: `MagicMock()`; `mock_ks.graph.predecessors.return_value = iter([...])` (must be `iter()`, not a list)
- For retry side_effect: construct separate mock_response objects per call — cannot reuse the same object in a `side_effect` list if content needs to vary
- Patch target for sleep in retry tests: `"adaptive.adaptive_engine.asyncio.sleep"`

### Key Business Rules (thresholds)
- SLOW: `time > expected * 1.5` (strict >; boundary = NORMAL)
- FAST: `time < expected * 0.7` AND `attempts <= 1` (strict <; attempts guard)
- STRUGGLING: `error_rate >= 0.5` OR `quiz < 0.5`
- STRONG: `quiz >= 0.8` AND `error_rate <= 0.2` AND `hints <= 2` (all inclusive)
- BORED: `skip_rate > 0.35` (strict >, checked before OVERWHELMED)
- OVERWHELMED: `hints >= 5` AND `revisits >= 2` (both required)
- Mastery threshold: 70 (integer, out of 100; `MASTERY_THRESHOLD = 70` in config.py)
- Confidence score: `clamp(quiz - error_rate*0.4 - min(hints,10)/10*0.2, 0.0, 1.0)`
- BORED modifier: fun += 0.3 (cap 1.0), emoji = SPARING, card_count = max(7, count-1)
- OVERWHELMED modifier: card_count = max(7, count-3), practice = max(3, p-1), step_by_step=True, analogy = min(1.0, a+0.2)
- `blended_score_to_generate_as(score)`: <1.7 → STRUGGLING, 1.7–2.499 → NORMAL, >=2.5 → FAST
- `build_blended_analytics(current, history, concept_id, student_id)` → `(AnalyticsSummary, float, str)`; blending: new_student=1.0/0.0, section_count 0→80/20, 1→70/30, 2→65/35, 3+→60/40; acute override=90/10

### System Prompt Strings to Assert
- `"GENERATION CONTROLS"` — always present
- `"Explanation depth"` — always present (capital E, with colon)
- `"DIFFICULTY RAMP"` — always present
- `"SLOW LEARNER MODE"` — only when speed == SLOW
- `"FAST/STRONG LEARNER MODE"` — only when speed == FAST AND comprehension == STRONG (both required)
- `"BORED LEARNER MODE"` — only when engagement == BORED
- `"PREREQUISITE REMEDIATION"` — in USER prompt, only when prereq_detail is not None
- `"Return ONLY the JSON object"` — always in user prompt

See `adaptive-engine-tests.md` for full test count and group breakdown.

### E2E Test File
`backend/tests/test_real_students_e2e.py` — 10 tests across 5 journey classes (all `@pytest.mark.e2e`).
Uses synchronous `requests`, no mocks. Backend at `http://localhost:8889`.
Key helpers: `_create_student`, `_start_session`, `_generate_cards`, `_record_interaction`,
`_section_complete`, `_complete_cards`, `_complete_card_adaptive`, `_next_section_cards`, `_get_student_mastery`.
Recovery card: `POST /api/v2/sessions/{id}/complete-card` with `wrong_attempts>=2` AND `re_explain_card_title` set.
Mode classification lives in `learning_profile_summary.speed` (SLOW/NORMAL/FAST) on the `NextCardResponse`.
Section persistence via `POST /api/v2/sessions/{id}/section-complete` (state_score: 1.0=STRUGGLING, 2.0=NORMAL, 3.0=FAST).
State blending: cold-start at section_count=0 (100% current); warm-start at 1; partial at 2; full history at 3+.
Skip pattern: `_start_session` calls `pytest.skip()` on 404 when ChromaDB not loaded.

### Concept Enrichment Module (chroma_store + vision_annotator + knowledge_service)
- `store_concept_blocks` upserts with `latex_expressions=json.dumps(block.latex)` and `latex_count=len(block.latex)` — both always present
- `annotate_image(image_bytes, concept_title, image_type, llm_client, model, cache_dir)` — skips DECORATIVE immediately; graceful degradation on API/JSON errors → `{"description": None, "relevance": None}`
- Vision MD5 cache: `{cache_dir}/vision_{md5_hex}.json`; second call with same bytes hits cache, no API call
- `KnowledgeService._get_latex(concept_id, chroma_metadata)` — primary: `chroma_metadata["latex_expressions"]` (JSON string); fallback: `_latex_map`
- `KnowledgeService.get_concept_images` always returns `description` and `relevance` keys (None if unannotated)

### KnowledgeService Test Isolation Pattern
Use `object.__new__` to bypass `__init__` entirely (avoids ChromaDB/file I/O):
```python
ks = object.__new__(KnowledgeService)
ks.book_slug = "prealgebra"
ks._latex_map = {}; ks._image_map = {}
type(ks.graph).__contains__ = MagicMock(return_value=True)  # for `in` operator
```
MagicMock dunder `__contains__` must be set on `type(mock_obj)`, not the instance.

See `backend/tests/test_concept_enrichment.py` — 17 tests across 3 groups.

### Circular Import Problem: teaching_router ↔ api.main
`api/teaching_router.py` imports `limiter` from `api/main.py` at module level, and `api/main.py` imports `router` from `api/teaching_router.py` at module level. This causes a circular import when any test imports either module directly.

**Fix**: Pre-inject a stub for `api.main` into `sys.modules` BEFORE any import of `teaching_router`. Do this at module level in the test file (outside any test class/function) so it runs during collection:
```python
def _install_api_main_stub():
    if "api.main" not in sys.modules:
        stub = MagicMock()
        from slowapi import Limiter
        from slowapi.util import get_remote_address
        stub.limiter = Limiter(key_func=get_remote_address)
        sys.modules["api.main"] = stub
_install_api_main_stub()
```
After this, `from api.teaching_router import ProgressUpdate` (or any other export) works cleanly.

### Auth Middleware Testing Pattern
Do NOT import `api.main.app` for middleware tests — the lifespan tries to load ChromaDB + PostgreSQL. Instead, replicate the middleware logic in a lightweight synthetic FastAPI app:
```python
def _build_app(api_key: str):
    app = FastAPI()
    @app.middleware("http")
    async def api_key_middleware(request, call_next):
        if request.url.path in SKIP_AUTH or not api_key:
            return await call_next(request)
        provided = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(provided, api_key):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)
    # add test routes
    return app
```
This mirrors production logic exactly without requiring services.

### Missing Packages (install before running tests)
`slowapi` and `Pillow` are in `requirements.txt` but may not be installed in the dev venv. Run:
`pip install slowapi Pillow`
The existing `test_teaching_router.py` is BROKEN due to the circular import — it was not fixed. Only `test_platform_hardening.py` uses the stub pattern.

### Test File Registry
See `test-file-registry.md` for per-file test counts, group names, and key implementation facts for all 15+ test files.

Critical reminders:
- `_CARDS_CACHE_VERSION` is a local variable (not importable) — always verify via source regex; current value is 21 but changes frequently
- `STARTER_PACK_INITIAL_SECTIONS = 2` (config.py line ~57)
- `AnalyticsSummary` needs `quiz_score` + `last_7d_sessions` — use `_make_analytics_summary()` helper everywhere
- `SOCRATIC_MAX_ATTEMPTS=3`; exhaustion fires at `attempt_count >= 3` (not `< 3`)
- result dict from handle_student_response has "mastered" key (NOT "passed")
- SpacedReview uses PostgreSQL-specific pg_insert — keep db.execute as generic AsyncMock

### Slowapi Router Handler Testing Pattern
Direct invocation of `@limiter.limit()` decorated handlers fails:
`Exception: parameter 'request' must be an instance of starlette.requests.Request`
Fix: build a real Starlette Request from a scope dict:
```python
from starlette.requests import Request
req = Request({"type":"http","method":"POST","path":"/...","query_string":b"","headers":[(b"host",b"localhost")],"client":("127.0.0.1",0)})
```

### Integration Test Patterns (httpx + FastAPI)
- httpx 0.28+ removed the `app=` shortcut from `AsyncClient`. Use `transport=httpx.ASGITransport(app=...)` instead.
  ```python
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
  ```
- Do NOT use the real `api.main.app` — its lifespan loads ChromaDB + PostgreSQL. Build a synthetic FastAPI app with `dependency_overrides` for DB injection.
- DB aggregate mocks: `db.execute(...).one()` returns a `MagicMock` by default — its numeric attributes are also `MagicMock`, causing `float()` conversion errors. Use a plain `_FakeAggRow` dataclass/namedtuple with explicit numeric fields (`total=0`, `avg_wrong=0.0`, etc.).
- `one_or_none()` should return `None` explicitly (not a `MagicMock`) when the test expects "no result found".
- Service async methods called via `await` in router handlers must be `AsyncMock`, not plain `MagicMock`. Forgetting this produces: `TypeError: object MagicMock can't be used in 'await' expression`.

### _parse_sub_sections Test File
`backend/tests/test_parse_sub_sections.py` — 22 tests across 7 classes (all passing).
See `parse-sub-sections-tests.md` for edge-case notes (LaTeX guard, whitespace stripping, false-positive scope).

Key patterns:
- Method-local constants (not importable): use `pathlib + re.search` on source text
- Routes on `app` in `api/main.py` (lifespan requires DB): use `ast.parse` on source file to inspect functions/decorators
- Static method import: `from api.teaching_service import TeachingService as _TS; _fn = _TS._method`
- `inspect.signature(fn).parameters["param"].default` to assert no hardcoded values
- `object.__new__(KnowledgeService)` to bypass `__init__` (avoids ChromaDB/file I/O)
