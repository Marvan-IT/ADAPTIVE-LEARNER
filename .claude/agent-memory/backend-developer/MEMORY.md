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

## Master System Prompt Upgrade (implemented 2026-03-05)

### New config constants (all now in config.py)
`MASTERY_THRESHOLD = 70` (raised from 60), `MAX_SOCRATIC_EXCHANGES = 20` (raised from 7),
`SOCRATIC_MAX_ATTEMPTS = 3`, `SOCRATIC_PROGRESS_INTERVAL = 3`,
`CARDS_MID_SESSION_CHECK_INTERVAL = 12`, `ADAPTIVE_CARD_CEILING = 20`

### New TeachingSession fields (db/models.py — Alembic migration needed)
`socratic_attempt_count: int`, `questions_asked: int`, `questions_correct: float`,
`best_check_score: int | None`, `remediation_context: str | None` (JSON string of failed topics)

### Valid TeachingSession phase values
PRESENTING, CARDS, CARDS_DONE, CHECKING, REMEDIATING, RECHECKING,
REMEDIATING_2, RECHECKING_2, COMPLETED

### New prompts.py functions
- `build_remediation_socratic_prompt(failed_topics, concept_title, concept_text, ...)` — for RECHECKING phase
- `build_mid_session_checkin_card() -> dict` — pure Python, returns CHECKIN card dict
- `build_socratic_system_prompt()` — extended with CONVERSATIONAL FLOW RULES block
- `build_cards_system_prompt()` — now supports 6 card types: TEACH, EXAMPLE, VISUAL, QUESTION, RECAP, FUN
  New JSON schema adds `card_type` and `quick_check` fields to each card.
  TEACH/EXAMPLE: quick_check required; QUESTION: 2 MCQ + 2 T/F in questions; others: null quick_check.

### New teaching_service.py methods
- `_get_phase_messages(db, session_id, phase)` — generic phase message fetcher
- `_extract_failed_topics(session_id, db) -> list[str]` — heuristic extraction from check messages
- `generate_remediation_cards(session_id, db) -> list[dict]` — TEACH+EXAMPLE+RECAP, no QUESTION cards
- `begin_recheck(session_id, db) -> dict` — transitions to RECHECKING/RECHECKING_2 phase
- `handle_student_response()` now accepts CHECKING, RECHECKING, RECHECKING_2 phases
  Remediation loop: score < 70 and attempts < 3 → REMEDIATING; exhausted → COMPLETED (not locked)
- `generate_cards()` now inserts CHECKIN cards every CARDS_MID_SESSION_CHECK_INTERVAL positions

### New teaching_router.py endpoints
- `POST /api/v2/sessions/{session_id}/remediation-cards` — phase must be REMEDIATING or REMEDIATING_2
- `POST /api/v2/sessions/{session_id}/recheck` — phase must be REMEDIATING or REMEDIATING_2
XP now only awarded when session.phase == "COMPLETED" (not on intermediate REMEDIATING steps).

### Updated teaching_schemas.py
SocraticResponse now includes: `remediation_needed: bool`, `attempt: int`, `locked: bool`, `best_score: int | None`
New schemas: `RemediationCardsResponse`, `RecheckResponse`

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
Added `socratic_profile=None`, `history=None`, and `session_card_stats=None` params. Appends `_build_session_stats_block()` block at end of prompt. `min_questions` is now dynamic (3/4/5 based on session error_rate). Old STRUGGLING/STRONG/BORED inline blocks replaced by the new helper.

## Hybrid Rolling Card Generation (implemented 2026-03-14)
See `rolling-card-generation.md` for full details.
- Initial request generates first 2 sub-sections only (`STARTER_PACK_INITIAL_SECTIONS=2`)
- Remaining sections stored in `concepts_queue` in session cache; fetched via `POST /next-section-cards`
- `LessonCard.question2` added — pre-generated second MCQ shown on wrong answer
- `_ADAPTIVE_CARD_CEILING` removed from `adaptive_router.py`
- cache_version bumped to 11; `_section_index` int stamp replaces fuzzy text sort

## Full Adaptive Upgrade (implemented 2026-03-02)

### XP Award Constants (config.py)
`XP_MASTERY=50`, `XP_MASTERY_BONUS=25`, `XP_MASTERY_BONUS_THRESHOLD=90`, `XP_CONSOLATION=10`, `XP_CARD_ADVANCE=5`

### generate_cards() adaptive wiring (teaching_service.py)
- `asyncio.gather(load_student_history(...), load_wrong_option_pattern(...))` runs concurrently
- Wraps both in try/except with safe fallback dict (total_cards_completed=0, etc.)
- Builds `LearningProfile` when `history["total_cards_completed"] >= 3` using proxy `quiz_score = max(0.1, 1.0 - min(avg_wrong_attempts * 0.15, 0.9))`
- Passes `learning_profile=card_profile, history=history` to `build_cards_system_prompt()`
- Passes `wrong_option_pattern=wrong_option_pattern` to `build_cards_user_prompt()`
- Log: `[cards-adaptive] student_id=... concept_id=... history_cards=N profile=S/C/E wrong_option_pattern=N|None`

### begin_socratic_check() session stats wiring (teaching_service.py)
- Queries `CardInteraction` by `session_id` for count, sum(wrong_attempts), sum(hints_used)
- Wrapped in try/except; sets `session_card_stats=None` on failure
- Passes `session_card_stats=session_card_stats` to `build_socratic_system_prompt()`
- Log: `[socratic-adaptive] session_id=... session_cards=N session_wrong=N session_hints=N error_rate=F`
- `CardInteraction` is now imported at module level in `teaching_service.py`

### teaching_service.py — added module-level logger + CardInteraction import
```python
import logging
from db.models import TeachingSession, ..., CardInteraction
logger = logging.getLogger(__name__)
```

### prompts.py — new helpers
- `_build_card_profile_block(learning_profile, history)` — appended to `build_cards_system_prompt()`; returns "" when profile is None (backward compat)
- `_build_misconception_block` logic inlined in `build_cards_user_prompt()`; injected when `wrong_option_pattern is not None`
- `_build_session_stats_block(session_card_stats, socratic_profile, history)` — appended to `build_socratic_system_prompt()`; returns "" when both args None

### teaching_router.py — XP award after mastery
- `_award_xp(student_id, xp_delta, new_streak, mastered, score, db)` — private async fn; logs `[xp-awarded]` / `[xp-award-failed]`; swallows exceptions
- `respond_to_check` handler: fetches `student_for_xp = await db.get(Student, session.student_id)`, computes `new_streak = current_streak + 1 if mastered`, calls `_award_xp` inline (not background task)
- `SocraticResponse` schema now has `xp_awarded: int | None = None`
- Imports: `XP_MASTERY, XP_MASTERY_BONUS, XP_MASTERY_BONUS_THRESHOLD, XP_CONSOLATION` from config

### adaptive/prompt_builder.py — FAST/STRONG wording fix
Line ~213: replaced `"- Skip introductory analogies..."` with `"- ALL content, definitions, and formulas MUST appear..."`

## Enhanced Adaptive Flashcard System (implemented 2026-03-10)

### build_blended_analytics() now returns 3-tuple
`(AnalyticsSummary, float, str)` — always unpack: `summary, blended_score, generate_as = build_blended_analytics(...)`.
Old single-value return is gone. All callers updated: `generate_next_card()`, `generate_cards()`.

### load_student_history() now returns extended Student profile fields
Added keys: `section_count`, `avg_state_score`, `effective_analogies`, `preferred_analogy_style`,
`effective_engagement`, `ineffective_engagement`, `boredom_pattern`, `state_distribution`, `overall_accuracy_rate`.

### New module: backend/src/adaptive/boredom_detector.py
Functions: `detect_boredom_signal(msg)`, `detect_autopilot_pattern(msgs)`, `select_engagement_strategy(eff, ineff)`.

### New endpoint: POST /api/v2/sessions/{id}/section-complete
Response: `SectionCompleteResponse(section_count, avg_state_score, state_distribution)`.
Increments rolling avg_state_score. Buckets: score < 1.5 → struggling, >= 2.5 → fast, else normal.

### Adaptive blend weight constants (config.py)
`ADAPTIVE_COLD_START_*` (section_count=0), `ADAPTIVE_WARM_START_*` (=1), `ADAPTIVE_PARTIAL_*` (=2),
`ADAPTIVE_STATE_BLEND_*` (>=3). Each has `_CURRENT_WEIGHT` and `_HISTORY_WEIGHT`.
`ADAPTIVE_NUMERIC_STATE_STRUGGLING_MAX = 1.5`, `ADAPTIVE_NUMERIC_STATE_FAST_MIN = 2.5`.

### New functions in adaptive_engine.py (module-level, not methods)
- `compute_numeric_state_score(speed, comprehension) -> float` — maps to [1.0, 3.0]
- `blended_score_to_generate_as(score) -> str` — maps to STRUGGLING/NORMAL/FAST

### Prompt functions with new params (all have safe defaults for backward compat)
- `build_cards_system_prompt(generate_as, blended_state_score)` — appends STUDENT STATE block
- `build_cards_user_prompt(concept_index, concepts_remaining, concepts_covered, blended_score, generate_as, images_used_this_section)` — appends COVERAGE CONTEXT block
- `build_adaptive_prompt(generate_as, blended_state_score, engagement_strategy)` — appends STUDENT STATE + engagement block
- `build_next_card_prompt(generate_as, blended_state_score, engagement_strategy)` — same additions

### Schema additions
- `CardBehaviorSignals.engagement_signal: str | None` (adaptive/schemas.py)
- `StudentResponseRequest.engagement_signal, .strategy_applied` (api/teaching_schemas.py)
- `RecordInteractionRequest.engagement_signal, .strategy_applied` (api/teaching_router.py inline)
- New: `SectionCompleteRequest`, `SectionCompleteResponse` (api/teaching_schemas.py)

### No verify_api_key in this project
The `verify_api_key` FastAPI dependency does NOT exist. Never add it to new endpoints.
Follow existing endpoint pattern — no API key dependency at route level.

## Detailed notes
See `patterns.md` for generation_profile lookup table and profile_builder classification rules.
