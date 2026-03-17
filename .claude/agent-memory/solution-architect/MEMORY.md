# Solution Architect Agent Memory — ADA Platform

Last updated: 2026-03-17 (pre-deployment-audit-fixes added)

---

## Project: ADA Adaptive Learning Platform

### Tech Stack (confirmed from codebase)
- **Backend:** Python, FastAPI 0.128+ async, Uvicorn, SQLAlchemy 2.0 async + asyncpg, PostgreSQL 15
- **LLM:** OpenAI `gpt-4o` (generation), `gpt-4o-mini` (lightweight tasks); AsyncOpenAI client
- **Vector Store:** ChromaDB 0.5, collection `concepts_{book_slug}` (one per book)
- **Graph:** NetworkX 3+ DAG loaded via `KnowledgeService`; JSON file `dependency_graph.json`
- **Frontend:** React 19 + Vite 7, Tailwind CSS 4, Sigma/Graphology (graph viz), i18next (13 languages)
- **Testing:** pytest + pytest-asyncio (must be added to requirements — currently absent)
- **Embeddings:** `text-embedding-3-small`, 1536 dimensions

### API Versioning Convention
- `/api/v1` = RAG + Graph knowledge endpoints
- `/api/v2` = Teaching Loop (Socratic sessions) + Translation
- `/api/v3` = Adaptive Learning Engine (designed 2026-02-25)
- New capabilities get new version prefix, not appended to existing

### Router Wiring Pattern (established pattern)
All routers use module-level instance assignment set at startup in `main.py` `lifespan()`:
```python
import api.teaching_router as teaching_router_module
teaching_router_module.teaching_svc = TeachingService(knowledge_svc)
```
The adaptive engine follows this same pattern.

### Service Instantiation Pattern
`KnowledgeService` (ChromaDB + NetworkX) is instantiated **once** in `lifespan()` and shared across all services. Cold start ~2s. Never re-instantiate per request.

### LLM Retry Pattern (established in TeachingService)
3 attempts, `asyncio.sleep(2 * attempt)` back-off, JSON salvage via `_salvage_truncated_json()`, raise `ValueError` after exhaustion. Adaptive engine follows the same pattern.

### Mastery Threshold
`MASTERY_THRESHOLD = 70` in `teaching_service.py` (also `config.py` per CLAUDE.md). Do not hardcode in new modules — reference config.

### Key File Paths
| Path | Purpose |
|------|---------|
| `backend/src/api/main.py` | FastAPI app, lifespan, router registration |
| `backend/src/api/knowledge_service.py` | KnowledgeService (ChromaDB + NetworkX) |
| `backend/src/api/teaching_service.py` | Pedagogical loop, LLM pattern reference |
| `backend/src/config.py` | All constants — always add new constants here |
| `backend/src/db/models.py` | SQLAlchemy ORM: Student, TeachingSession, ConversationMessage, StudentMastery |
| `backend/src/adaptive/` | New adaptive engine package (designed 2026-02-25) |
| `docs/adaptive-learning-engine/` | HLD, DLD, execution-plan for adaptive engine |

### Known Technical Debt (from CLAUDE.md)
- `Base.metadata.create_all()` still used — Alembic migration pending (devops-engineer)
- No Dockerfile, no docker-compose, no CI/CD (devops-engineer)
- `get_db()` FastAPI async dependency may not yet be implemented in `db/connection.py` — critical blocker for Phase 3 of adaptive engine
- pytest not in requirements.txt — add with Phase 1 of adaptive engine

### Design Patterns Used in This Project
- **Pure-function classification:** LearningProfile is pure (no I/O), enabling exhaustive unit tests without mocking
- **GenerationProfile as strategy object:** Parameterizes LLM prompt; derived from LearningProfile via lookup table + modifier application
- **Template-based remediation cards (v1):** No LLM call for [Review] cards — reduces latency and cost; upgrade to LLM in v2
- **Single LLM call per lesson:** Full lesson (explanation + N cards) in one structured JSON call; cap `max_tokens=2800`

### Established Docs Structure
```
docs/{feature-name}/
├── HLD.md
├── DLD.md
└── execution-plan.md
```
Feature directories are kebab-case. Never combine two features in one directory.

### ChromaDB Metadata Constraints (confirmed from codebase)
- Metadata values must be `str | int | float | bool` only — no lists or dicts
- Lists stored as comma-joined strings: `", ".join(prereqs)` (see `prerequisites`, `dependents`)
- JSON-encoded strings used for structured list data: `json.dumps(block.latex)` — the established pattern
- Practical metadata size warning threshold: 8192 bytes per field
- `latex_expressions` (new in concept-enrichment) stores full LaTeX list as JSON string alongside existing `latex_count` int

### Image Pipeline Patterns (confirmed from codebase)
- Images saved at `backend/output/{book_slug}/images/{concept_id}/{filename}`
- `image_index.json` at `backend/output/{book_slug}/image_index.json` — maps concept_id → list of image dicts
- FORMULA and DIAGRAM types are annotated; DECORATIVE is skipped
- Vision cache: `backend/output/{book_slug}/vision_cache/vision_{md5}.json` — MD5(image_bytes) cache key
- Static files mount in `main.py` already present: `/images` → `output/prealgebra/images/` (single-book only)
- Rate limit constant for API spacing: `VISION_RATE_LIMIT` in `config.py` (same pattern as `MATHPIX_RATE_LIMIT`)

### KnowledgeService Dual-Source Pattern
- `_latex_map`: loaded from `concept_blocks.json` at startup — fallback when ChromaDB field absent
- `_image_map`: loaded from `image_index.json` at startup — primary source for images
- Both are in-memory dicts; refreshed only on API restart
- `get_concept_images()` constructs URLs as `/images/{concept_id}/{filename}` — book slug currently hardcoded in mount

### Adaptive Real Tutor — Key Design Decisions (2026-02-27)
- **New DB tables (Alembic migration `e3c02cf4c22e` — applied):** `card_interactions`, `spaced_reviews`; ORM models in `db/models.py`
- **Per-card LLM generation:** `POST /api/v2/sessions/{id}/complete-card` — one LLM call per card advance (NOT batch). `max_tokens=1200`. Model: `ADAPTIVE_CARD_MODEL` (default `gpt-4o-mini`).
- **Ceiling constant:** `ADAPTIVE_CARD_CEILING = 8` in `config.py` — returns 409 `{"ceiling": true}` at boundary
- **Blending algorithm:** `adaptive/blending.py` — pure functions `blend_signals()` + `aggregate_student_baseline()`. Constants all in `config.py`.
- **Spaced repetition:** Fixed Ebbinghaus intervals `[1, 3, 7, 14, 30]` days in `SR_INTERVALS_DAYS` (config.py). `adaptive/spaced_review.py` — pure `compute_next_due()`.
- **New schemas file:** `adaptive/real_tutor_schemas.py` — separate from existing `adaptive/schemas.py`
- **Feature flag:** `ADAPTIVE_CARDS_ENABLED` in `config.py` — env-var driven
- **New prompt function:** `build_next_card_prompt()` added to existing `adaptive/prompt_builder.py` (not a new file)
- **Frontend signal tracking:** `useRef` (not state) for timer/counters — zero re-renders
- **Review badges:** ConceptMap overlays driven by `GET /api/v2/students/{id}/review-due`
- **409 format exception:** Uses `JSONResponse(status_code=409, content={"ceiling": True})` — not `HTTPException` with detail string

### Confirmed API Version Assignment
- `/api/v2/sessions/{id}/complete-card` and `/api/v2/students/{id}/review-due` — both under v2 (Teaching Loop resource)
- v2 now owns: Socratic sessions, card completion, spaced review scheduling
- v3 unchanged: initial adaptive lesson batch generation

### Adaptive Transparency — Key Design Decisions (2026-02-28)
- **No new ORM/migration:** All Group B features read from existing `card_interactions` columns. `difficulty_bias` is transient (Pydantic-only, not persisted).
- **`difficulty_bias` field:** Added to `CardBehaviorSignals` as `Literal["TOO_EASY", "TOO_HARD"] | None = None`. Inherited by `NextCardRequest`. Backward compatible.
- **Bias override mechanism:** `generate_next_card()` calls `profile.model_copy(update={"recommended_next_step": ...})` AFTER `build_learning_profile()` — keeps prompt builder pure.
- **Wrong-option pattern:** `load_wrong_option_pattern()` async function in `adaptive_engine.py`. Threshold = `WRONG_OPTION_PATTERN_THRESHOLD = 3` in config.py. Failure is graceful (returns None, logs warning).
- **5-tuple return from `generate_next_card()`:** Now returns `(card, profile, gen_profile, motivational_note, adaptation_label)`. All callers in `adaptive_router.py` must unpack 5 values. Breaking change — grep all call sites before commit.
- **`difficulty` key forwarded in card dict:** `generate_next_card()` now includes `"difficulty": parsed.get("difficulty", 3)` in the normalised card dict.
- **Card history endpoint:** `GET /api/v2/students/{id}/card-history?limit=50` in `teaching_router.py`. Constants `CARD_HISTORY_DEFAULT_LIMIT=50`, `CARD_HISTORY_MAX_LIMIT=200` in config.py. Uses `CardHistoryResponse` + `CardInteractionRecord` in `teaching_schemas.py`.
- **SessionContext additions:** `learningProfileSummary`, `adaptationApplied`, `difficultyBias` added to state. `ADAPTIVE_CARD_LOADED` now clears `difficultyBias` (one-shot semantics). New action: `SET_DIFFICULTY_BIAS`.
- **AdaptiveSignalTracker:** New component at `frontend/src/components/learning/AdaptiveSignalTracker.jsx`. Reads refs via `setInterval(1000)` — NOT useState on every tick. Props: refs + context values + `onDifficultyBias` callback.
- **StudentHistoryPage:** Route `/history` in App.jsx. Redirects to `/` if no student in context. Client-side groups by `session_id`. SessionArcSparkline: inline SVG polyline, returns null for < 2 data points.
- **Group A + Group B sequencing:** Must complete `CardLearningView` Group A changes (P4-5, P4-6) before inserting Group B `AdaptiveSignalTracker` (P5-8, P5-9).
- **`build_next_card_prompt()` signature extended:** Accepts `wrong_option_pattern: int | None = None` and `difficulty_bias: str | None = None`. Pure function — no side effects.

### Confirmed API Version Assignment (updated)
- `GET /api/v2/students/{id}/card-history` — added to v2 (student resource pattern)
- v2 endpoint count: students CRUD, sessions CRUD, cards, assist, complete-card, review-due, card-history

### Completed Designs
- `docs/adaptive-learning-engine/` — HLD, DLD, execution-plan (2026-02-25)
- `docs/concept-enrichment/` — HLD, DLD, execution-plan (2026-02-26)
- `docs/adaptive-real-tutor/` — HLD, DLD, execution-plan (2026-02-27)
- `docs/adaptive-transparency/` — HLD, DLD, execution-plan (2026-02-28)
- `docs/ai-native-learning-os/` — HLD, DLD, execution-plan (2026-03-01)
- `docs/platform-hardening/` — HLD, execution-plan (2026-03-01); DLD pre-specified by team
- `docs/unified-card-schema/` — HLD, DLD, execution-plan (2026-03-06)
- `docs/card-generation-rebuild/` — HLD, DLD, execution-plan (2026-03-09)
- `docs/card-blank-screen-fix/` — HLD, DLD, execution-plan (2026-03-09)
- `docs/real-time-adaptive-cards/` — HLD, DLD, execution-plan (2026-03-10) → details in `real-time-adaptive-cards.md`
- `docs/adaptive-flashcard-system/` — HLD, DLD, execution-plan (2026-03-10) → details below
- `docs/master-card-generation/` — HLD, DLD, execution-plan (2026-03-11) → see `master-card-generation.md`
- `docs/hybrid-adaptive-cards/` — HLD, DLD, execution-plan (2026-03-14) → see `hybrid-adaptive-cards.md`
- `docs/pre-deployment-audit-fixes/` — HLD, DLD, execution-plan (2026-03-17) → see below

### Pre-Deployment Audit Fixes — Key Design Decisions (2026-03-17)
- **No schema changes, no migration, no new env vars** — pure logic fixes in service layer and frontend reducer
- **Fix 1 (card ordering):** FUN/RECAP type-based reorder block removed; `_section_index` integer stamp is sole sort authority (cache version 14 already reflects this)
- **Fix 2A (image filter):** `image_type in ("DIAGRAM","FORMULA")` restriction removed — any `is_educational != False` image with a description now passes through
- **Fix 4A (FAST floor):** `expected_time = max(baseline_time, 90.0)` — normative 90s floor prevents sub-10s averages from suppressing FAST classification
- **Fix 4B (conservative cap):** Mode-switch consecutive-signal threshold 5 → 2 for responsive adaptation
- **P1-A (SessionContext):** `passed` field removed from `SOCRATIC_RESPONSE` reducer destructure + PostHog call — `passed` never existed in `SocraticResponse` backend schema
- **P2 caution:** `_find_missing_sections` and `_get_checking_messages` have confirmed call sites in live code despite audit report — backend developer must re-verify before deletion
- **test_bug_fixes.py** already exists at `backend/tests/test_bug_fixes.py` as an untracked file covering 5 fix classes (7+ test classes, 19+ tests)
- **Effort:** 9.5 dev-days total; 3 calendar days with 4 parallel agents

### Adaptive Flashcard System — Key Design Decisions (2026-03-10)
- **DB schema (already in models.py):** 11 new `students` cols + 3 new `card_interactions` cols. Alembic migration `005_add_adaptive_history_columns` needed. Models are already updated in `db/models.py`.
- **Numeric state score scale [0.0–4.0]:** `compute_numeric_state_score(speed, comprehension) -> float`. Baseline: NORMAL×OK = 2.0. Lookup dict `_NUMERIC_STATE_MAP`. FAST×STRUGGLING = 2.0 (same as NORMAL×OK — overconfident student, needs normal scaffolding).
- **blended_score_to_generate_as() thresholds:** < 1.25 = SLOW_STRUGGLING, < 1.75 = SLOW_OK, < 2.25 = NORMAL_OK, < 2.75 = NORMAL_STRONG, else FAST_STRONG. These are PROMPT labels only — not GenerationProfile lookup keys.
- **Cold-start boundary: section_count >= 3** (not card count). Weights: cold-start = 80/20, graduated = 60/40.
- **New config constants:** `ADAPTIVE_COLD_START_SECTION_THRESHOLD=3`, `ADAPTIVE_COLD_START_CURRENT_WEIGHT=0.8`, `ADAPTIVE_COLD_START_HISTORY_WEIGHT=0.2`, `ADAPTIVE_STATE_EMA_ALPHA=0.3`, `BOREDOM_SIGNAL_COOLDOWN_CARDS=5`, `BOREDOM_AUTOPILOT_WINDOW=4`, `BOREDOM_AUTOPILOT_SIMILARITY_THRESHOLD=0.85`.
- **build_blended_analytics() now returns tuple[AnalyticsSummary, float, str]** — BREAKING CHANGE to callers. All call sites in `adaptive_router.py` must unpack 3 values.
- **Feature flag:** `ADAPTIVE_NUMERIC_BLENDING_ENABLED: bool = True` in config.py — allows instant rollback via env var without redeploy.
- **Boredom detector:** `adaptive/boredom_detector.py` (NEW). Pure functions, stdlib only (re + difflib.SequenceMatcher). 4 strategies: GAMIFY, CHALLENGE, STORY, BREAK_SUGGESTION. Strategy selection avoids `ineffective_engagement` list.
- **New endpoint:** `POST /api/v2/sessions/{id}/section-complete` → `SectionCompleteRequest` / `SectionCompleteResponse`. Idempotency guard via `sectionCompleteSentRef` on frontend + `SELECT ... FOR UPDATE` on backend.
- **EMA formula:** `new_avg = ADAPTIVE_STATE_EMA_ALPHA * section_score + (1 - alpha) * old_avg` where alpha = 0.3.
- **Prompt additions:** `STUDENT STATE` block in system prompt; `COVERAGE CONTEXT` block in user prompt. Both optional dict params in `build_next_card_prompt()` and `build_adaptive_prompt()`.
- **Effort:** ~28.5 dev-days; ~17 calendar days with 4 parallel agents. Critical path: P0-04 → A-01 → A-02 → B-03 → B-04 → B-05/B-06 → B-07 → D-04/D-05 → E-05 → E-06.

### Platform Hardening — Key Design Decisions (2026-03-01)
- **Auth:** `APIKeyMiddleware` (custom `BaseHTTPMiddleware`) — single shared `API_SECRET_KEY`. Skip paths: `/health`, `/docs`, `/openapi.json`, `/redoc`. Use `secrets.compare_digest()`. Fail fast at startup if key absent.
- **Rate limiting:** `slowapi` 0.1.x + `SlowAPIMiddleware`. Constants in config.py: `RATE_LIMIT_DEFAULT=60/minute`, `RATE_LIMIT_LLM_HEAVY=10/minute`, `RATE_LIMIT_READ=120/minute`. In-memory (no Redis).
- **Middleware order:** Auth registered LAST in main.py (Starlette LIFO = executes FIRST). slowapi registered before auth.
- **XP/streak columns:** `students.xp INTEGER NOT NULL DEFAULT 0`, `students.streak INTEGER NOT NULL DEFAULT 0`. Atomic UPDATE via `xp = xp + :delta`.
- **New endpoint:** `PATCH /api/v2/students/{id}/progress` — `xp_delta: int (ge=0)`, `streak: int (ge=0)`. Under v2 (student resource).
- **Frontend XP sync:** Fire-and-forget after card completion. Hydrate from `GET /students/{id}` on app start into Zustand `hydrateProgress()` action.
- **DB indices (Alembic):** `ix_teaching_sessions_student_id`, `ix_conversation_messages_session_id`, `ix_student_mastery_student_concept` (composite).
- **Connection pool:** `pool_size=20, max_overflow=80` — requires PostgreSQL `max_connections >= 150`.
- **Image validation:** Pillow open + `ImageStat.Stat(img).mean < IMAGE_BLACK_THRESHOLD (default=5)` → skip. At extraction time (offline pipeline only).
- **UNMAPPED resolver:** ±5 pages proximity scan. `UNMAPPED_PROXIMITY_PAGES=5` in config.py. Run after initial concept-assignment pass.
- **Vision prompt:** Single prose paragraph, 40–120 words. No "What it shows:" / "Why it helps:" labels.
- **Vision injection:** `[Visual Context]` block appended to presentation, Socratic, and card prompts. No new LLM calls — descriptions already in ChromaDB.

### AI-Native Learning OS — Key Design Decisions (2026-03-01)
- **New packages (already installed):** `framer-motion ^12.x` + `zustand ^5.x` in `frontend/package.json` — no install step needed.
- **New store:** `frontend/src/store/adaptiveStore.js` — Zustand, session-scoped only (no persistence). State: `{ mode, xp, level, streak, streakBest, lastXpGain, burnoutScore }`. XP_PER_LEVEL=100, BURNOUT_THRESHOLD=60.
- **New component dir:** `frontend/src/components/game/` — 5 components: GameBackground (canvas 120-particle), XPBurst (AnimatePresence), StreakMeter, LevelBadge (SVG arc), AdaptiveModeIndicator.
- **Critical bug fix (ship first, standalone PR):** AssistantPanel sticky: wrapper needs `position: sticky; top: 70px; alignSelf: flex-start` in CardLearningView; panel needs `height: calc(100vh - 86px)` in AssistantPanel. Root cause: sticky requires align-self: flex-start in flex container.
- **AppShell nav height:** 58px → 64px. Glassmorphism: `backdrop-filter: blur(16px)`. Adaptive glow bottom border.
- **Mode CSS classes:** `.adaptive-excelling/.adaptive-struggling/.adaptive-slow/.adaptive-bored` applied to card container.
- **XP per answer:** MCQ correct=10 XP, short-answer correct=5 XP, wrong=0 XP + burnoutScore+20 + streak reset.
- **Sigma node CSS limitation:** If Sigma uses WebGL (canvas-only), DOM node class application is not feasible — use Sigma color attribute or legend fallback. Verify before starting P7-2.
- **WBS total:** 31 tasks, ~19.75 engineer-days. With 2 engineers: ~10 calendar days.

### Card Generation Rebuild — Key Design Decisions (2026-03-09)
- **No DB/frontend changes:** Pure fix to `teaching_service.py`, `prompts.py`, `config.py`.
- **Fix A (dead code):** `_group_by_major_topic()` was never called. Now wired in `generate_cards()` after `_parse_sub_sections()`. Also fixes fallback key `"content"` → `"text"` (KeyError for new students).
- **Fix B+C (token truncation):** `_generate_cards_single()` now accepts `max_tokens` param (default 12000, was hardcoded 8000). Caller computes adaptive budget: SLOW/STRUGGLING → `min(16000, max(8000, n*1800))`; NORMAL → `min(12000, max(6000, n*1200))`; FAST/STRONG → `min(8000, max(4000, n*900))`.
- **Fix D (density):** `_build_card_profile_block()` SUPPORT branch gets "2–3 cards/section"; ACCELERATE gets "1–2 cards/section". NORMAL gets no density instruction.
- **Fix E (completeness):** `build_cards_user_prompt()` appends numbered checklist of all section titles as COMPLETENESS REQUIREMENT — last instruction before return.
- **Fix F (coverage):** COMPLETE COVERAGE line in system prompt now says "NON-NEGOTIABLE" and cross-references the checklist.
- **New config constants:** `CARDS_MAX_TOKENS_SLOW/NORMAL/FAST` + `_FLOOR` + `_PER_SECTION` variants (9 total).
- **New log lines:** `cards section_grouping: raw=%d grouped=%d` and `cards token_budget: max_tokens=%d`.
- **Effort:** 4.65 engineer-days; 2.5 calendar days with 2 engineers.

### Unified Card Schema — Key Design Decisions (2026-03-06)
- **No DB changes:** Pure prompt + service logic change. No migration required.
- **LLM owns image placement:** `image_indices` + `[IMAGE:N]` markers in content. Backend resolves indices → image objects. Backend no longer calls `.pop("image_indices")` or round-robins.
- **Unified question field:** All cards use `question: {text, options[4], correct_index, explanation}`. No `card_type`, no `quick_check`, no `questions[]`, no True/False anywhere.
- **CHECKIN exception:** CHECKIN cards (backend-generated, not LLM) have no `question`; detected by frontend as `!card.question && Array.isArray(card.options)`.
- **Removed constants:** `ADAPTIVE_CARD_CEILING` deleted from `config.py`. Sub-section soft cap (10) deleted from `teaching_service.py`.
- **Card counter:** "Card N" only (no total). i18n key `learning.cardN = "Card {{n}}"` added to all 13 locales.
- **Frontend parser:** `parseInlineImages(content, images)` — regex `/\[IMAGE:(\d+)\]/gi`; returns array of `{type: "text"}` / `{type: "image"}` segments.
- **Out-of-scope:** `build_next_card_prompt()` adaptive per-card schema is NOT updated — coexists with old schema until follow-up feature.
- **`difficulty` field ambiguity:** Not included in unified LLM schema spec — open stakeholder question whether to add it back or default to 3.
- **Effort:** ~15.25 engineer-days, ~5-6 calendar days with 2 engineers + 1 tester.

### Full Adaptive Upgrade — Key Design Decisions (2026-03-02)
- **Completed designs:** `docs/full-adaptive-upgrade/` — HLD, DLD, execution-plan (2026-03-02)
- **generate_cards() wiring:** `asyncio.gather(load_student_history(), load_wrong_option_pattern())` — concurrent, not sequential. Threshold for building LearningProfile = 3 cards (not 5 — lower for card generation vs Socratic).
- **quiz_score proxy:** `1.0 - min(avg_wrong_attempts * 0.15, 0.9)` — converts avg_wrong_attempts from history into a plausible quiz_score for AnalyticsSummary when used in generate_cards().
- **New config constants:** `XP_MASTERY=50`, `XP_MASTERY_BONUS=25`, `XP_MASTERY_BONUS_THRESHOLD=90`, `XP_CONSOLATION=10`, `XP_CARD_ADVANCE=5` — all in `config.py`.
- **XP award implementation:** Inline (not background task) in `teaching_router.py::respond_to_check`. Direct SQLAlchemy UPDATE, not HTTP call to self. `xp_awarded: int | None = None` added to `SocraticResponse`.
- **session_card_stats dict keys:** `{ total_cards, total_wrong, total_hints, error_rate }` — passed to `build_socratic_system_prompt()` as `session_card_stats` param.
- **Socratic dynamic min-questions:** error_rate >= 0.4 → 5 questions min; error_rate <= 0.1 and no hints → 3 questions min; else → 4 questions.
- **FAST/STRONG wording fix location:** `adaptive/prompt_builder.py` ~line 213 — replace "Skip introductory analogies" with "ALL content MUST appear, replace analogies with applications".
- **`build_cards_system_prompt()` new signature:** `(style, interests, language, learning_profile=None, history=None)` — all new params keyword-only with None default → fully backward compatible.
- **`build_socratic_system_prompt()` new signature:** adds `session_card_stats: dict | None = None` as last parameter — backward compatible.
- **AppShell status:** `LevelBadge`, `StreakMeter`, `AdaptiveModeIndicator` already mounted. Only `XPBurst` missing — needs mounting at root div level (overlay).
- **XP_CARD_ADVANCE in frontend:** Add to `frontend/src/utils/constants.js` — not synced to DB per card (too expensive); Zustand XP corrected by hydration on next GET /students/{id}.
- **16 tasks, ~12.2 engineer-days, ~5-6 calendar days** with 2 engineers + 1 tester.
