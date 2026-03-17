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

### Card Generation Test File
`backend/tests/test_card_generation.py` — 74 tests across 12 groups (all passing).
Key facts:
- `TeachingService._group_by_major_topic(sections)` — static method; support headings matched by `_SUPPORT_HEADING` regex (EXAMPLE, Solution, TRY IT, HOW TO, Note, TIP, etc.); a leading support section with no preceding group is kept as-is (not dropped)
- Adaptive max_tokens formula (inline in generate_cards): SLOW/STRUGGLING=`min(16000, max(8000, n*1800))`; FAST+STRONG=`min(8000, max(4000, n*900))`; else=`min(12000, max(6000, n*1200))`; test via a mirrored `_compute()` helper — no mocking needed
- `_build_card_profile_block(profile, history)` from `api/prompts.py` — imports directly; returns "" when profile is None; SUPPORT mode triggered by SLOW OR STRUGGLING; ACCELERATE mode requires FAST AND STRONG (both)
- `build_cards_user_prompt()` sub-section dicts MUST have key `"text"` (not `"content"`); old `"content"` key raises KeyError — this is the regression the test guards
- COMPLETENESS REQUIREMENT phrase and numbered section list always present in user prompt; ORDERING REQUIREMENT phrase must not have been removed (regression guard)
- `_make_profile()` helper constructs LearningProfile directly (avoids AnalyticsSummary pipeline); `_make_sub_sections(titles)` builds stub section dicts
- `TeachingService._find_missing_sections(cards, sections)` — @staticmethod; title match is case-insensitive substring search across combined card title+content text
- `TeachingService._generate_cards_per_section(...)` — async; uses inner closure calling `self._generate_cards_single`; mock with `patch.object(service, "_generate_cards_single", new=AsyncMock(...))`; side_effect values must be `{"cards": [...]}` dicts (not bare lists); failed section returns `[]` not exception
- `build_cards_user_prompt()` new params: `concept_overview` and `section_position` — preamble with "OVERVIEW:" only injected when BOTH are non-None; missing either → no preamble
- `build_cards_system_prompt(remediation_weak_concepts=[...])` — appends "REMEDIATION RE-ATTEMPT" block only when list is non-empty; concept names appear verbatim in block
- `build_socratic_system_prompt()` question count: `base_min = max(8, n_topics)`, `base_max = min(15, n_topics + 4)` — so min >= 8, max <= 15 always; "SPREAD RULE" always present when covered_topics is non-empty; `MAX_SOCRATIC_EXCHANGES = 30` in config
- `_extract_failed_topics_from_messages(messages, covered_topics)` — @staticmethod; CORRECTION_PHRASES include "not quite", "actually,", "that is incorrect", "good try", etc.; regex `[^.!?]*\?` extracts first question-ending sentence from prior assistant message (stops at `.` in decimals — "3.45?" yields "45?"); deduplication by `last_assistant_msg[:50]` key; ignores student/non-assistant messages

### Playwright E2E Tests (frontend)
- `frontend/playwright.config.js` + `frontend/e2e/` — 9 spec files + helpers.js (36 tests total)
- `@playwright/test ^1.48.0` added to devDependencies; `"test:e2e": "playwright test"` script in package.json
- API key auto-read from `../../backend/.env` via `loadApiKey()` in helpers.js — no env config needed
- Student isolation: every test creates a unique student via `createStudent()` to prevent state pollution
- `waitForCards()` watches for `.rounded-full` dots AND absence of "crafting" loading text (90s default)
- MCQ buttons: `button:has(span:text-is("A"))` — circular letter badge (no data-testid exists in the codebase)
- WRONG_FEEDBACK_MS = 1800ms in app code — always wait 2200ms+ after a wrong click in tests
- See `playwright-e2e.md` for full DOM selector reference, helper API, and concept IDs

### Bug Regression Test File
`backend/tests/test_bug_regressions.py` — 22 tests across 5 groups (21 unit + 1 e2e):
- `TestLanguageValidation` (6 tests): B-07 — `UpdateLanguageRequest` pattern constraint rejects invalid codes
- `TestRecoveryCardImages` (5 tests): B-02 — `generate_recovery_card()` populates `card["images"]` from `concept_detail[:3]`
- `TestCallLlmTimeout` (2 tests): B-03 — `_call_llm()` passes `timeout=30.0` to OpenAI
- `TestJsonRepairPattern` (2 tests): B-05 — repair uses `json.loads(repair_json(raw))`, NOT `return_objects=True`
- `TestStyleLockPhaseGuard` (6 unit + 1 e2e tests): B-01 — `switch_style`/`update_session_interests` return 409 when phase != PRESENTING
- E2E test `test_switch_style_locked_after_cards_e2e` requires `TEST_API_KEY` env var and live backend

### Slowapi Router Handler Testing Pattern
Direct invocation of `@limiter.limit()` decorated handlers fails with:
`Exception: parameter 'request' must be an instance of starlette.requests.Request`
Fix: use a minimal `FastAPI()` + `TestClient` app that replicates the handler logic, or test the phase guard via source code inspection (`inspect.getsource()`).

### Stale Constant-Pin Failures in Existing Tests (pre-existing, not regressions)
`test_adaptive_mode_switching.py` and `test_card_generation.py` have 10 tests asserting old constant values:
- `_CARDS_CACHE_VERSION = 6` / `= 12` — actual value is now `14` (bumped again 2026-03-16 for FUN/RECAP removal)
- `STARTER_PACK_INITIAL_SECTIONS = 2` — actual value is now `3` (bumped per CLAUDE.md, 2026-03-15)
These tests need their expected constants updated to 14 and 3 respectively.

### Bug Fixes Test File
`backend/tests/test_bug_fixes.py` — 96 tests across 19 groups (all passing):
- `TestCardOrdering` (4): Fix 1 — FUN/RECAP reorder block removed; _section_index sort is authoritative
- `TestImageFilter` (9): Fix 2A — image filter no longer restricts to DIAGRAM/FORMULA; PHOTO/TABLE/FIGURE all pass
- `TestImageFallback` (4): Fix 2B — file-not-found path retains indexed filename rather than dropping image
- `TestRecoveryCardInsertion` (4): Fix 3 — REPLACE_UPCOMING_CARD replaces targetIndex slot; appends when at end
- `TestFastModeDetection` + `TestConservativeCapThreshold` (13): Fix 4A/4B — expected_time floor 90s; cap threshold lowered 5→2
- `TestPropertyBatching` (10): Fix 5A — _batch_consecutive_properties merges consecutive property CONCEPT sections
- `TestFixLatexBackslashes` (9): Fix 6 — doubles non-safe-escape backslashes; `\t` IS safe so `\times` is NOT doubled
- `TestImageUrlIncludesBookSlug` (4): Fix 7 — image URLs include book_slug; uses `object.__new__` bypass
- `TestBlendedScoreForwarded` (2): Fix 8 — blended_score forwarded not hardcoded; `db.flush = AsyncMock()`
- `TestListBooksEndpoint` (5): Fix 9 — `/api/v2/books` endpoint; `_install_rate_limiter_stub()` pattern
- `TestCardBehaviorSignalsImport` (4): Fix 10 — CardBehaviorSignals comes from adaptive.schemas
- `TestSortCards` (6): Fix 11 — `_sort_cards()`: FUN first, difficulty-ascending middle, RECAP last
- `TestParseCardImageRef` (4): Fix 12 — strips [CARD:N], returns image at index, out-of-bounds → None
- `TestImageUrlNoHardcodedPort` (3): Fix 13 — base_url default is `""` not `localhost:8000`
- `TestAdaptiveModeDerivation` (5): SLOW/low-comp → STRUGGLING; FAST+high-comp → FAST; else NORMAL
- `TestCacheVersionBump` (1): Fix 14 — `_CARDS_CACHE_VERSION == 15`; read via source regex (local var, not importable)
- `TestBlankCardFilter` (2): Fix 15 — cards with empty/whitespace title or content are filtered out
- `TestRecoveryCardWrongAnswer` (3): Fix 16 — `CompleteCardRequest` has optional `wrong_question`/`wrong_answer_text`; `generate_recovery_card` accepts both
- `TestBookSlugRouting` (2): Fix 17 — `/api/v1/books` in main.py source; `graph_full` has `book_slug` param (AST inspection, no lifespan trigger)
- `TestRollingModeMapping` (4+4): Fix 18 — SLOW maps to STRUGGLING; `_CARD_MODE_DELIVERY` has no SLOW key

Key patterns:
- Method-local constants (not importable): use `pathlib + re.search` on source text
- Routes on `app` in `api/main.py` (lifespan requires DB): use `ast.parse` on source file to inspect functions/decorators
- Static method import: `from api.teaching_service import TeachingService as _TS; _fn = _TS._method`
- `inspect.signature(fn).parameters["param"].default` to assert no hardcoded values
- `object.__new__(KnowledgeService)` to bypass `__init__` (avoids ChromaDB/file I/O)
