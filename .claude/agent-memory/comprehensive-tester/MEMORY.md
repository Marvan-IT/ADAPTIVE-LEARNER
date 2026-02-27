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
- Mastery threshold: 0.70 (in config.py)
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
