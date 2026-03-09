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
- Mastery threshold: 60 (integer, out of 100; `MASTERY_THRESHOLD = 60` in config.py — changed from 70)
- Confidence score: `clamp(quiz - error_rate*0.4 - min(hints,10)/10*0.2, 0.0, 1.0)`
- BORED modifier: fun += 0.3 (cap 1.0), emoji = SPARING, card_count = max(7, count-1)
- OVERWHELMED modifier: card_count = max(7, count-3), practice = max(3, p-1), step_by_step=True, analogy = min(1.0, a+0.2)

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

### TeachingService Test File
`backend/tests/test_teaching_service.py` — 27 tests across 7 groups (all passing).
Key facts confirmed by reading teaching_service.py:
- SOCRATIC_MAX_ATTEMPTS=3; exhaustion fires when `attempt_count >= 3` (NOT `< 3`). Test exhaustion with attempt_count=3, not 2.
- result dict from handle_student_response has NO "passed" key; use "mastered" instead.
- generate_cards() imports load_student_history/load_wrong_option_pattern locally inside the method. Patch targets: `"adaptive.adaptive_engine.load_student_history"` and `"adaptive.adaptive_engine.load_wrong_option_pattern"` (not via teaching_service).
- build_learning_profile: patch as `"adaptive.profile_builder.build_learning_profile"`.
- generate_remediation_cards(session_id: UUID, db) — first arg is UUID; session fetched internally via db.get.
- CHECKIN insertion: `(i+1) % INTERVAL == 0 and (i+1) < len(raw_cards)` — needs N+1 cards (13 for interval=12).
- SpacedReview uses PostgreSQL-specific pg_insert — keep db.execute as generic AsyncMock.
- begin_recheck: db.get receives cls (not str); mock with `async def _db_get(cls, pk)` pattern.

### Platform Hardening Test File
`backend/tests/test_platform_hardening.py` — 32 tests across 5 suites:
- Suite 1 (6 tests): auth middleware (synthetic app, no real DB)
- Suite 2 (6 tests): ProgressUpdate Pydantic schema validation
- Suite 3 (11 tests): _nearest_concept() + Pillow image validation
- Suite 4 (5 tests): vision annotator with mocked LLM
- Suite 5 (4 tests): list_students N+1 fix structural inspection
