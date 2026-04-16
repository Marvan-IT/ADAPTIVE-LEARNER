# Token Usage — RTK Required

**Always use `rtk` as a prefix for all shell commands to minimize token usage.**
`rtk` is installed at `~/.local/bin/rtk` and is in PATH. It filters and compresses command output before it reaches context, saving 60–99% tokens on builds, tests, git, file reads, and more.

```bash
# Every command should be prefixed:
rtk git status        # instead of: git status
rtk npm run build     # instead of: npm run build
rtk pytest            # instead of: pytest
rtk ls src/           # instead of: ls src/
```

See `~/.claude/CLAUDE.md` for the full command reference.

---

# Adaptive Learner — AI-Powered Education Platform

An AI-powered adaptive education platform (formerly "ADA") that teaches mathematics through personalized, chunk-based pedagogical loops. It combines Retrieval-Augmented Generation (RAG) with dependency graph traversal to deliver concept-by-concept lessons from 16 OpenStax textbooks across 13 languages.

---

## Project Structure

```
ADA/
├── docs/                     # Design artifacts — one folder per feature
├── backend/                  # Python FastAPI server
│   ├── src/
│   │   ├── api/              # FastAPI routers, services, schemas, prompts
│   │   ├── auth/             # JWT auth, OTP, email, password reset
│   │   ├── db/               # SQLAlchemy ORM models and PostgreSQL connection
│   │   ├── extraction/       # PDF → chunk pipeline
│   │   ├── graph/            # NetworkX dependency graph (JSON-backed)
│   │   ├── adaptive/         # Adaptive learning engine: profiling, XP, card generation
│   │   ├── config.py         # All constants, paths, API keys (auto-generates secrets in dev)
│   │   └── pipeline.py       # End-to-end extraction orchestration
│   ├── alembic/              # Database migrations (16 revisions)
│   ├── tests/                # pytest test suite
│   └── requirements.txt
├── frontend/                 # React 19 + Vite 7 SPA
│   ├── src/
│   │   ├── api/              # Axios client wrappers (auth, sessions, students, admin)
│   │   ├── layouts/          # Shared route layouts
│   │   │   ├── AuthLayout.jsx              # Split-panel auth shell + constellation bg
│   │   │   ├── ConstellationBackground.jsx # Animated SVG background
│   │   │   ├── StudentLayout.jsx           # Student shell (sidebar + topbar + content)
│   │   │   └── AdminLayout.jsx             # Admin shell (sidebar + topbar + content)
│   │   ├── pages/            # Route-level components (24 pages)
│   │   │   ├── DashboardPage.jsx           # Student home (NEW)
│   │   │   ├── ConceptMapPage.jsx          # Concept map + RPG skill tree
│   │   │   ├── LearningPage.jsx            # Main lesson UI
│   │   │   ├── StudentHistoryPage.jsx      # Past sessions
│   │   │   ├── LeaderboardPage.jsx         # Podium + rank list
│   │   │   ├── AchievementsPage.jsx        # Badge grid (NEW)
│   │   │   ├── SettingsPage.jsx            # Student settings (NEW)
│   │   │   ├── Admin*.jsx                  # 11 admin pages
│   │   │   └── (auth pages)               # Login, Register, OTP, Forgot, Reset
│   │   ├── components/
│   │   │   ├── ui/           # 20 reusable UI components (Button, Card, Badge, Input, etc.)
│   │   │   ├── layout/       # StudentSidebar, StudentTopBar, AdminSidebar, AdminTopBar, GamificationHUD
│   │   │   ├── learning/     # CardLearningView, AssistantPanel, CompletionView, etc.
│   │   │   ├── game/         # LevelBadge, StreakMeter, XPBurst, BadgeCelebration, etc.
│   │   │   └── conceptmap/   # ConceptGraph (SVG), MapLegend, SkillTreeView (NEW)
│   │   ├── context/          # AuthContext, StudentContext, SessionContext, ThemeContext
│   │   ├── store/            # Zustand: adaptiveStore.js
│   │   ├── locales/          # i18next (13 languages: en, ar, de, es, fr, hi, ja, ko, ml, pt, si, ta, zh)
│   │   ├── theme/            # themes.js (spring presets, stagger presets)
│   │   └── utils/            # PostHog analytics, constants
│   ├── e2e/                  # Playwright E2E tests (11 files, 90+ tests)
│   └── package.json
└── .claude/
    ├── agents/               # Subagent definitions
    └── agent-memory/         # Persistent per-agent memory
```

---

## Tech Stack

### Backend
| Concern | Technology |
|---|---|
| Framework | FastAPI 0.110+ (async) |
| Server | Uvicorn |
| Database | PostgreSQL 15 via SQLAlchemy 2.0 async + asyncpg 0.29 |
| Migrations | Alembic 1.13.0 |
| Vector Search | pgvector 0.3.0 — `Vector(1536)` column on `concept_chunks` table |
| Graph Engine | NetworkX 3+ (DAG of concept prerequisites, JSON-backed) |
| LLM | OpenAI API — `gpt-4o` for generation, `gpt-4o-mini` for lightweight tasks |
| Embeddings | `text-embedding-3-small` (1536 dimensions) |
| PDF Parsing | PyMuPDF 1.24+ |
| Math OCR | Mathpix API (optional) |
| Validation | Pydantic 2.5+ |
| Rate Limiting | slowapi 0.1.9 (optional Redis backend via `REDIS_URL`) |
| JSON Repair | json-repair 0.30.0 (LLM output fallback) |
| Image Processing | Pillow 10.0+ |

### Frontend
| Concern | Technology |
|---|---|
| Framework | React 19.2 + Vite 7.3 |
| Routing | React Router DOM 7.13 |
| Styling | Tailwind CSS 4 + PostCSS |
| Graph Viz | @react-sigma/core 5.0.6 + graphology (force-atlas2 layout) |
| HTTP | Axios 1.7.0 |
| Math Render | KaTeX 0.16 + remark-math + rehype-katex |
| Markdown | react-markdown 10 |
| i18n | i18next 25 (13 languages: en, ar, de, es, fr, hi, ja, ko, ml, pt, si, ta, zh) |
| Global State | Zustand 5.0.11 (adaptive store) |
| Animations | Framer Motion 12.34 |
| Analytics | PostHog JS |
| Icons | Lucide React |

### Infrastructure
- **Python venv**: `.venv/` at project root
- **Node**: npm (package-lock.json)
- **Environment**: `.env` files in `backend/` and `frontend/` — never commit these; `.env.example` files are the source of truth for required keys

---

## Environment Variables

### Backend (`backend/.env`)
```
OPENAI_API_KEY=
OPENAI_BASE_URL=           # optional, defaults to OpenAI
OPENAI_MODEL=gpt-4o
OPENAI_MODEL_MINI=gpt-4o-mini
MATHPIX_APP_ID=
MATHPIX_APP_KEY=
DATABASE_URL=postgresql+asyncpg://postgres:<password>@localhost:5432/AdaptiveLearner
API_SECRET_KEY=            # random 32-char hex string — required for API auth
REDIS_URL=                 # optional — enables cross-worker rate limiting
```

### Frontend (`frontend/.env`)
```
VITE_API_BASE_URL=http://localhost:8889
VITE_POSTHOG_KEY=
VITE_API_SECRET_KEY=       # must match backend API_SECRET_KEY
```

---

## Database Schema

### Tables (PostgreSQL, SQLAlchemy async ORM + pgvector)

All foreign keys enforce cascading deletes. Schema changes must go through Alembic migrations — never use `Base.metadata.create_all()` in production.

- **`students`** — UUID id, display_name, age (Integer, nullable), interests (ARRAY), preferred_style, preferred_language; XP, streak, section_count; adaptive state: overall_accuracy_rate, boredom_pattern, frustration_tolerance, recovery_speed, avg_state_score; JSONB profile fields: effective_analogies, effective_engagement, ineffective_engagement, state_distribution

- **`teaching_sessions`** — UUID id, student_id (FK), concept_id, book_slug, phase (PRESENTING / CARDS / CHECKING / SOCRATIC / COMPLETED); socratic_attempt_count, questions_asked, questions_correct, best_check_score; chunk_index, exam_phase, exam_attempt, exam_scores (JSONB), chunk_progress (JSONB); remediation_context, failed_chunk_ids

- **`conversation_messages`** — UUID id, session_id (FK), role (assistant/user), content, phase, message_order

- **`student_mastery`** — UUID id, student_id (FK), concept_id, mastered_at, session_id (FK); unique on (student_id, concept_id)

- **`card_interactions`** — UUID id, session_id (FK), student_id (FK), concept_id, card_index; telemetry: time_on_card_sec, wrong_attempts, selected_wrong_option, hints_used, idle_triggers; adaptation: adaptation_applied, engagement_signal, strategy_applied, strategy_effective

- **`spaced_reviews`** — UUID id, student_id (FK), concept_id, review_number, due_at, completed_at; unique on (student_id, concept_id, review_number)

- **`concept_chunks`** — UUID id, book_slug, concept_id, section, order_index, heading, text, **embedding Vector(1536)** (pgvector), latex (ARRAY), chunk_type, is_optional, created_at (TIMESTAMPTZ); admin fields: is_hidden (Boolean, default false), exam_disabled (Boolean, default false), admin_section_name (Text, nullable)

- **`chunk_images`** — UUID id, chunk_id (FK → concept_chunks), image_url, caption, order_index

- **`admin_graph_overrides`** — UUID id, book_slug, action ('add_edge'/'remove_edge'), source_concept, target_concept, created_by (FK users), created_at

- **`admin_config`** — key (Text PK), value, updated_by (FK users), updated_at

---

## Core Architecture

### Hybrid pgvector + Graph Engine
Every concept query combines two retrieval strategies:
1. **Semantic search** (pgvector) — queries `concept_chunks.embedding` column in PostgreSQL using cosine similarity
2. **Graph traversal** (NetworkX) — resolves prerequisites and learning readiness from the DAG loaded from `output/{book_slug}/graph.json`

Results are enriched with student mastery context before being passed to the LLM.

### Chunk-Based Pedagogical Loop
Teaching sessions operate on chunks (ordered sub-sections of a concept), not the whole concept at once:
1. **Presentation** — metaphor-based explanation of the concept using LLM + knowledge base context
2. **Cards phase** — cards generated per chunk; 3 cards upfront then each subsequent card generated on demand (per-card adaptive generation)
3. **Chunk Exam Gate** — open-ended questions per chunk; pass threshold is `CHUNK_EXAM_PASS_RATE = 0.50` (50%) in `config.py`
4. **Concept Mastery** — concept marked mastered when all required (non-optional) teaching chunks pass their exam gates

### Adaptive Engine
Each card is shaped by a blended student profile:
- Cold start (≤2 sections): 80/20 blend toward defaults
- Warm (3–10 sections): weight shifts toward observed data
- Acute deviation detection: overrides blending when student state spikes
- Modes: STRUGGLING / NORMAL / FAST — control token budget (6000 / 5000 / 3000)

### Admin Console
Full-featured admin console for platform management:
- **Dashboard** — platform stats, active students, mastery rates, struggling student alerts
- **Student Management** — CRUD, access control, manual mastery grant/revoke, password reset
- **Session Monitoring** — filter by phase/book, view all sessions across students
- **Analytics** — concept difficulty ranking, mastery rates, student performance distribution
- **Content Controls** — edit/hide/merge/split chunks, rename sections, toggle optional/exam-gate per section or subsection
- **Prerequisite Editing** — add/remove dependency graph edges with cycle detection, overrides stored in DB
- **System Config** — runtime-configurable settings (exam pass rate, XP values, AI model selection)
- **Admin User Management** — create admins, promote/demote roles

### Data Extraction Pipeline
```
PDF → pdf_reader → text_cleaner → section_detector → content_filter
    → chunk_builder → concept_builder → llm_extractor
    → PostgreSQL (concept_chunks + pgvector embeddings) + NetworkX graph (graph.json)
    → image_extractor → Mathpix OCR → chunk_images table
```
Supported: 16 OpenStax math textbooks (Prealgebra through Calculus III). Pipeline entry point: `backend/src/pipeline.py`.

---

## Development Workflow

### Claude Code Agentic Workflow (day-to-day)

All work is done through Claude Code with plan mode. Follow this flow for every non-trivial change:

1. **Enter plan mode** (`EnterPlanMode`) — explore affected files, design the approach, write it to the plan file, then call `ExitPlanMode` for approval before touching any code.
2. **Explore first** — use `Explore` subagents (via `Task` tool) to read the codebase before proposing changes. Launch up to 3 in parallel for multi-area tasks.
3. **Use specialist agents** for implementation work:
   - `backend-developer` — FastAPI endpoints, services, schemas, DB queries
   - `frontend-developer` — React components, Context reducers, JSX
   - `comprehensive-tester` — pytest unit/integration tests, React test coverage
   - `devops-engineer` — Alembic migrations, Docker, CI/CD, test infra
   - `solution-architect` — HLD/DLD docs for new features
4. **Track progress** with `TodoWrite` — mark tasks `in_progress` before starting, `completed` immediately after. One `in_progress` task at a time.
5. **Restart check** — after backend changes, uvicorn `--reload` picks them up automatically. After frontend changes, Vite HMR updates the browser automatically. A manual restart is only needed if:
   - New dependencies added (`pip install` / `npm install`)
   - `.env` values changed
   - Non-hot-reloadable config changes

### Formal Feature Workflow (significant new features)

For any new feature that spans multiple files or requires API contract changes, follow these stages:

#### Stage 0 — Infrastructure (`devops-engineer` agent)
**Trigger**: Schema changes, new deployment needs, test infra.
- Alembic migration scripts (never `create_all`)
- Dockerfile / `docker-compose.yml` / CI/CD
- `pytest.ini`, `conftest.py`, `.env.example`

#### Stage 1 — Design (`solution-architect` agent)
**Trigger**: Any new feature or significant change. Produces docs **before** any code:

```
docs/{feature-name}/
├── HLD.md            ← High-Level Design
├── DLD.md            ← Detailed Low-Level Design
└── execution-plan.md ← Phased WBS, DoD, rollout
```

#### Stage 2 — Backend (`backend-developer` agent)
FastAPI endpoints, services, schemas, pgvector/NetworkX integrations per DLD.

#### Stage 3 — Testing (`comprehensive-tester` agent)
Unit + integration + E2E tests. Every test name maps to a business criterion.

#### Stage 4 — Frontend (`frontend-developer` agent)
React components, Context state, i18n (13 languages), WCAG 2.1 AA, mobile-first.

---

## Design Documentation (`docs/`)

All architectural design artifacts live under `docs/`. The structure is enforced by the solution-architect agent.

```
docs/
└── {feature-name}/          # kebab-case feature slug
    ├── HLD.md               # High-Level Design
    ├── DLD.md               # Detailed Low-Level Design
    └── execution-plan.md    # WBS, phases, DoD, rollout strategy
```

**Rules:**
- One directory per feature — never combine features
- Sub-components may have nested folders: `docs/{feature-name}/{sub-component}/`
- Revisions add a `## Revision History` section at the top of the file
- These files are the source of truth; they are updated before implementation changes

---

## Coding Conventions

### Backend (Python)
- All FastAPI route handlers must be `async def`
- Use Pydantic v2 models for all request/response schemas — defined in `schemas.py` or `teaching_schemas.py`
- Database sessions use `AsyncSession` from SQLAlchemy; never use sync sessions
- All config values (paths, model names, thresholds) go in `config.py` — no magic strings in business logic
- Use Python `logging` module with structured format — never `print()` in production paths
- Alembic migration required for every schema change — alert the devops-engineer when models change
- Chunk exam pass rate is `CHUNK_EXAM_PASS_RATE = 0.50` in `config.py` — use this constant, not a hardcoded value. (`MASTERY_THRESHOLD = 70` is deprecated; chunk exam gate is now the mastery mechanism)

### Frontend (JavaScript/JSX)
- React 19 functional components only — no class components
- All API calls go through `src/api/` client wrappers — no direct `fetch`/axios in components
- State that crosses routes lives in a Context (`src/context/`) or Zustand store (`src/store/`) — no prop drilling beyond 2 levels
- i18n: all user-visible strings use `useTranslation()` hook — no hardcoded English strings
- Inline `style={{}}` objects are the primary styling approach for components; Tailwind classes are used for utility tokens only
- Handle all three UI states: loading, error, and empty
- Math content renders via KaTeX through `react-markdown` + `remark-math` + `rehype-katex`

### General
- Never commit `.env` files or PDF data files (`backend/data/`)
- Never commit secrets, API keys, or credentials
- No `console.log` or `print()` debug statements in committed code
- New API endpoints require: Pydantic schema (backend) + Axios wrapper (frontend) + tests
- New DB columns require an Alembic migration (coordinate with devops-engineer)

---

## Deployment Readiness Status

### ✅ Completed Security & Stability Fixes (2026-03-08)

| Issue | Fix Applied | File |
|---|---|---|
| `GET /students` no pagination | `limit`/`offset` params, max 200 | `teaching_router.py` |
| XSS via react-markdown | `skipHtml={true}` on all instances | `CardLearningView.jsx`, `SocraticChat.jsx`, `ChatBubble.jsx`, `PresentationView.jsx`, `ConceptImage.jsx`, `AssistantPanel.jsx` |
| OpenAI no timeout (600s) | `timeout=30.0` + exponential backoff | `teaching_service.py` |
| Unbounded DB queries | `.limit()` on mastery, analytics, card-interactions | `teaching_router.py` |
| Bare `except Exception:` hides errors | Changed to `logger.exception()` | `teaching_service.py` |
| slowapi per-worker rate limiter | Optional Redis backend via `REDIS_URL` env var | `rate_limiter.py` |
| Translation cache per-worker | Shared `_openai_client` singleton via lifespan | `main.py` |
| `print()` in API layer | Replaced with `logger.info/error()` | `main.py` |
| Empty `.catch(() => {})` in React | Logs to `console.error` | `SessionContext.jsx` |
| SQLAlchemy/OpenAI/Pydantic unpinned | Pinned to safe version ranges | `requirements.txt` |
| axios outdated | Updated to `^1.7.0` | `package.json` |
| LearningPage silent prereq fallback | Logs error before fallback | `LearningPage.jsx` |
| StudentContext promise chain | Granular error logging | `StudentContext.jsx` |

### ✅ UX & Pedagogical Fixes (2026-03-09)

| Issue | Fix Applied | Files |
|---|---|---|
| MCQ questions trivially answered from lesson text | `MCQ QUESTION QUALITY RULE` added to both card prompts | `prompts.py`, `prompt_builder.py` |
| Dangling "shows..." text with no image | `MATH_DIAGRAM` marker system + SVG renderer component | `prompts.py`, `MathDiagram.jsx`, `CardLearningView.jsx` |
| Socratic ADA over-explains on "don't know" | `RESPONSE LENGTH LIMIT` rule + Socratic `max_tokens` 600→150 | `prompts.py`, `teaching_service.py` |
| Same MCQ reappears after wrong answer | New `POST /sessions/{id}/regenerate-mcq` endpoint; frontend replaces question after timeout | `teaching_schemas.py`, `teaching_service.py`, `teaching_router.py`, `sessions.js`, `CardLearningView.jsx` |
| Cards generated in random order | `CARD SEQUENCE ORDER` mandatory rule in system prompt + ordinal section labels in user prompt + FUN/RECAP safety-net sort | `prompts.py`, `teaching_service.py` |
| Mastery readiness bar showing stale historical data | Bar now computed from live in-session `cardStates` (correct/total MCQs seen); color-coded green/primary/amber | `CardLearningView.jsx` |

### ✅ Card Generation & Rendering Fixes (2026-03-09)

| Issue | Fix Applied | File |
|---|---|---|
| `is_educational: None` filtered out all images | Changed filter to `is not False` | `teaching_service.py`, `prompts.py` |
| `_group_by_major_topic()` never called — 57 micro-sections sent to LLM | Now called after `_parse_sub_sections()` — groups into 8-10 topic blocks | `teaching_service.py` |
| `max_tokens=8000` hardcoded — truncated slow-learner output | Adaptive budget: 8,000–16,000 tokens based on learner profile × section count | `teaching_service.py` |
| Stale cached cards returned forever despite prompt rebuilds | `cache_version` check forces regeneration when version is behind | `teaching_service.py` |
| Card completeness not enforced — LLM skipped sections | Numbered section checklist appended to user prompt + CARD DENSITY instructions | `prompts.py` |
| Blank screen when card index out of bounds | `if (!card) return null` replaced with loading/error UI | `CardLearningView.jsx` |
| `NEXT_CARD` had no bounds check — index drifted past cards.length | Added `Math.min` clamp to NEXT_CARD reducer | `SessionContext.jsx` |
| `ADAPTIVE_CARD_ERROR` triggered -1 index when cards empty | Safe clamp: `cards.length > 0 ? Math.min(index, length-1) : 0` | `SessionContext.jsx` |
| Adaptive API called on every Next click — fought pre-generated cards | Skip adaptive call when pre-generated cards remain (`index < cards.length - 1`) | `SessionContext.jsx` |
| `goToNextCard` stale closure — adaptive API never triggered at last card | Added `state.currentCardIndex` to `useCallback` deps array | `SessionContext.jsx` |
| Frontend port drift — Vite picks 5177+ breaking CORS | Added `server: { port: 5173, strictPort: false }` to vite.config.js | `vite.config.js` |
| Port 5177 not in CORS allowed list | Added ports 5177, 5178 to `FRONTEND_URL` in `backend/.env` | `backend/.env` |
| `allow_methods=["*"]` and `allow_headers=["*"]` overly permissive | Restricted to explicit methods and headers; filter empty FRONTEND_URL | `main.py` |
| `completion.excellent` and `completion.keepPracticing` missing from all 13 locales | Added to all locale files | `locales/*.json` |

### ✅ Card Generation & API Fixes (2026-03-09)

| Issue | Fix Applied | File |
|---|---|---|
| LibertAI model `qwen3-coder-next` outputs LaTeX `\ldots` breaking JSON parse | `json-repair>=0.30.0` fallback in `_generate_cards_single()` | `teaching_service.py`, `requirements.txt` |
| `finish_reason: length` — only 1 card from truncated LLM output | Section texts truncated to 600 chars; `adaptive_max_tokens` raised to 4000–6000 | `teaching_service.py` |
| `card_type: None` — Pydantic silently dropped unknown field | Added `card_type` field to `LessonCard` schema | `teaching_schemas.py` |
| DB cache poisoning — bad 1-card result cached forever | `cache_version` check; DB cache cleared manually | `teaching_service.py` |
| LLM timeout too short for ~130 tok/s model | Updated formula: `max_tokens / 100.0 + 15.0` | `teaching_service.py` |
| Ghost uvicorn processes on port 8888 | Switched to port 8889; updated `vite.config.js` proxy | `vite.config.js`, `backend/.env` |

### ✅ Socratic Chat Image Fix (2026-03-09)

| Issue | Fix Applied | Files |
|---|---|---|
| Socratic chat shows ALL card images whenever any keyword detected | `[CARD:N]` marker: AI tags which card's image it references; backend resolves exact image; frontend renders only that one per message | `prompts.py`, `teaching_service.py`, `teaching_schemas.py`, `teaching_router.py`, `SessionContext.jsx`, `SocraticChat.jsx` |
| `DiagramPanel` showed every image always visible at top of chat | Removed entirely — replaced by per-message `msg.image` inline render | `SocraticChat.jsx` |

### ✅ Multi-Book Support & Simulation Tests (2026-03-15)

| Issue | Fix Applied | File |
|---|---|---|
| Code only worked for prealgebra | Auto-discovery of processed books; per-book KnowledgeService routing | `main.py`, `teaching_service.py`, `teaching_router.py` |
| `book_slug` not in session API | Added `book_slug` to `StartSessionRequest` + session creation | `teaching_schemas.py`, `teaching_service.py`, `teaching_router.py` |
| `STARTER_PACK_INITIAL_SECTIONS=2` caused test failure | Bumped to 3; cache version 12→13 | `config.py`, `teaching_service.py` |
| Vite proxy pointed to wrong port (8891) | Fixed proxy to port 8889 | `vite.config.js` |
| 10/12 simulation tests failing | All 12/12 now passing | `test_student_simulations.py` |

### ✅ Real Student Readiness Fixes (2026-03-16)

| Issue | Fix Applied | File |
|---|---|---|
| Language/style/interests changeable mid-lesson (confusing) | Settings locked at session start; customize panel disabled during active lesson; backend returns HTTP 409 if style/interest change attempted after cards started | `teaching_router.py`, `LearningPage.jsx` |
| Recovery cards had no images | Use `concept_detail.images[:3]` in `generate_recovery_card()` | `adaptive_engine.py` |
| Missing LLM timeout in adaptive engine | Added `timeout=30.0` to `_call_llm()` | `adaptive_engine.py` |
| Mastery threshold (70) not communicated to student | Added "score 70 to pass" opening rule to Socratic system prompt | `prompts.py` |
| Language code not validated (invalid codes silently accepted) | Added `pattern` validator to `UpdateLanguageRequest` | `teaching_schemas.py` |
| JSON repair `return_objects=True` silently discarded repaired cards | Removed flag; `json.loads()` on repair string output | `teaching_service.py` |
| `StudentMastery` IntegrityError on race condition (500 error) | Pre-check before insert; skip gracefully if already exists | `teaching_router.py` |
| Duplicate language map in `adaptive_engine` (could diverge) | Import `LANGUAGE_NAMES` from `prompts.py` | `adaptive_engine.py` |
| Hardcoded DB password in `config.py` fallback | Removed; raise `ValueError` on missing `DATABASE_URL` | `config.py` |
| 20+ hardcoded English strings in frontend (breaks 13-language support) | Replaced with `t()` calls; added keys to all 13 locale files | `SocraticChat.jsx`, `CardLearningView.jsx`, `LearningPage.jsx` |
| MCQ timer not cancelled on Next click (race condition) | `clearTimeout()` before card advance | `CardLearningView.jsx` |
| `.env.example` files missing | Created `backend/.env.example` and `frontend/.env.example` | `backend/.env.example`, `frontend/.env.example` |
| No startup env-var validation | Raise clear `ValueError` on startup if required vars missing | `config.py` |

### ✅ Per-Card Adaptive Generation (2026-03-24)

| Issue / Feature | Fix Applied | Files |
|---|---|---|
| Cards generated as static batch — never adapts mid-session | Per-card generation: 3 cards upfront, then each subsequent card generated on demand per content piece in textbook order | `teaching_service.py`, `adaptive_engine.py`, `prompt_builder.py`, `teaching_router.py`, `teaching_schemas.py`, `SessionContext.jsx`, `sessions.js` |
| `section_count` never incremented — blending weights frozen at 80/20 cold-start forever | `section_count` now incremented in session cache on each `generate_per_card()` call | `teaching_service.py`, `adaptive_engine.py` |
| `card_index=0` hardcoded in initial `build_blended_analytics()` call | Now uses `history.get("total_cards_completed", 0)` | `teaching_service.py` |
| `NEXT_CARD` reducer clamped at `cards.length - 1` — student stuck at last pre-generated card | Conditional clamp: allows index to advance past last card when `nextCardInFlight=true` | `SessionContext.jsx` |
| No race condition guard — rapid taps triggered duplicate next-card fetches | `nextCardInFlight` state flag + `NEXT_CARD_FETCH_STARTED/DONE` reducer cases | `SessionContext.jsx` |
| `build_next_card_prompt()` had no image injection | Extended with `content_piece_images` parameter; injects up to 3 images per card | `prompt_builder.py` |
| New endpoint | `POST /api/v2/sessions/{id}/next-card` — generates single adaptive card for next content piece | `teaching_router.py`, `teaching_schemas.py` |
| Design docs | `docs/per-card-adaptive-generation/` — HLD, DLD, execution-plan | `docs/per-card-adaptive-generation/` |
| Tests | 20 tests covering all business rules (content order, mode shaping, blending, images, race condition) | `backend/tests/test_per_card_adaptive.py` |

### ✅ Admin Console (2026-04-13)

| Feature | Status | Files |
|---|---|---|
| Admin dashboard with platform stats | Done | `admin_router.py`, `AdminPage.jsx` |
| Student CRUD + access control + manual mastery | Done | `admin_router.py`, `AdminStudentsPage.jsx`, `AdminStudentDetailPage.jsx` |
| Session monitoring with filters | Done | `admin_router.py`, `AdminSessionsPage.jsx` |
| Platform analytics (difficulty, mastery rates) | Done | `admin_router.py`, `AdminAnalyticsPage.jsx` |
| System config (runtime settings) | Done | `admin_router.py`, `AdminSettingsPage.jsx` |
| Content controls (edit/hide/merge/split chunks) | Done | `admin_router.py`, `AdminReviewPage.jsx`, `AdminBookContentPage.jsx` |
| Section controls (rename, optional, exam gate) | Done | `admin_router.py` |
| Prerequisite editing (add/remove edges, cycle detection) | Done | `admin_router.py`, `chunk_knowledge_service.py` |
| Simplified registration (removed interests + style, added age) | Done | `auth/schemas.py`, `RegisterPage.jsx` |
| Thread-safe graph cache | Done | `chunk_knowledge_service.py` |

### ✅ Admin Section Toggle Fix (2026-04-16)

| Issue | Fix Applied | Files |
|---|---|---|
| Section Hide toggle didn't update sidebar (button stayed "Hide", no hidden styling) | Optimistic state update flips `is_hidden` + `hidden_count` immediately; reverts on error; server reconciliation follows | `AdminBookContentPage.jsx` |
| Hide toggle sent `is_hidden=true` repeatedly (never toggled to unhide) | Fixed by optimistic update making `sec.is_hidden` reflect true state before next click | `AdminBookContentPage.jsx` |
| Backend: 0-chunk updates logged silently | Added `logger.warning()` when section visibility toggle matches 0 chunks | `admin_router.py` |
| Backend: response missing `is_hidden` echo | Added `is_hidden` to toggle response payload | `admin_router.py` |

### ⚠️ Known Technical Debt (Requires devops-engineer)

| Issue | File | Priority |
|---|---|---|
| No Dockerfile | — | Critical |
| No `docker-compose.yml` | — | Critical |
| No CI/CD pipeline | — | Critical |
| No frontend unit test framework (no vitest/jest) | `frontend/package.json` | High |

### 🏗️ Out of Scope (Architectural — Defer)

- **Translation cache persistence**: Per-worker dict; use PostgreSQL `concept_translations` table for multi-worker.
- **Circuit breaker for OpenAI**: Requires `tenacity` library.
- **C1 Per-student authorization**: Full COPPA/FERPA compliance requires auth middleware overhaul.
- **pgvector horizontal scaling**: Single RDS instance; migrate to managed vector DB (Pinecone/Weaviate) for multi-region.

---

## Running the Project

### Backend
```bash
cd backend
source ../.venv/Scripts/activate   # Windows: source ../.venv/Scripts/activate.bat
pip install -r requirements.txt
# IMPORTANT: use python -m uvicorn (not bare uvicorn) to ensure venv deps are loaded
# Port 8889 is the canonical backend port
python -m uvicorn src.api.main:app --reload --port 8889
```

### Frontend
```bash
cd frontend
npm install
npm run dev
# Dev server runs on http://localhost:5173 (or 5174 if 5173 is taken)
# VITE_API_BASE_URL in frontend/.env must match the backend port (e.g. http://localhost:8889)
# vite.config.js proxy already points to http://127.0.0.1:8889
```

### Database (initial setup)
```bash
# Tables are created on first backend start via init_db()
# Apply all migrations (including admin console tables):
cd backend
alembic upgrade head
```

### Data Extraction Pipeline
```bash
# Run once per textbook to populate PostgreSQL chunks (pgvector) + graph.json
cd backend
python -m src.pipeline --book prealgebra
```

---

## Key File Locations

| File | Purpose |
|---|---|
| **Backend** | |
| `backend/src/api/main.py` | FastAPI app entrypoint, CORS, lifespan, routers |
| `backend/src/api/teaching_router.py` | All `/api/v2/` student endpoints (~36 endpoints) |
| `backend/src/api/teaching_service.py` | Card generation, session management, LLM orchestration |
| `backend/src/api/prompts.py` | All LLM system prompts (style, interests, language, mode) |
| `backend/src/api/admin_router.py` | Admin console endpoints (~48 endpoints, rate-limited) |
| `backend/src/api/chunk_knowledge_service.py` | pgvector search + graph traversal + override management |
| `backend/src/auth/router.py` | Auth endpoints (rate-limited: 3-60/min per endpoint) |
| `backend/src/auth/service.py` | JWT creation, refresh token rotation with reuse detection |
| `backend/src/adaptive/prompt_builder.py` | Per-card adaptive prompt builder (mode delivery blocks) |
| `backend/src/adaptive/generation_profile.py` | 9-cell speed×comprehension matrix for card parameters |
| `backend/src/db/models.py` | SQLAlchemy ORM (13 tables, indexed, pgvector column) |
| `backend/src/config.py` | Constants, paths, API keys (auto-generates secrets in dev) |
| **Frontend — Layouts** | |
| `frontend/src/layouts/AuthLayout.jsx` | Split-panel auth shell (constellation + form) |
| `frontend/src/layouts/StudentLayout.jsx` | Student shell (sidebar + topbar + content) |
| `frontend/src/layouts/AdminLayout.jsx` | Admin shell (sidebar + topbar + content) |
| **Frontend — Pages** | |
| `frontend/src/pages/DashboardPage.jsx` | Student home (welcome hero, stats, subjects) |
| `frontend/src/pages/ConceptMapPage.jsx` | Concept map + RPG skill tree (Tree/Graph toggle) |
| `frontend/src/pages/LearningPage.jsx` | Teaching session (chunk selection → cards → completion) |
| `frontend/src/pages/AchievementsPage.jsx` | Badge grid by category |
| `frontend/src/pages/LeaderboardPage.jsx` | Podium top 3 + rank list |
| `frontend/src/pages/SettingsPage.jsx` | Student settings (profile, appearance, account) |
| **Frontend — Components** | |
| `frontend/src/components/ui/` | 20 reusable UI components (Button, Card, Badge, Input, etc.) |
| `frontend/src/components/layout/StudentSidebar.jsx` | Collapsible sidebar (260/72px, colored nav icons) |
| `frontend/src/components/layout/AdminSidebar.jsx` | Admin sidebar (280px, grouped nav) |
| `frontend/src/components/conceptmap/SkillTreeView.jsx` | RPG skill tree (chapter tiers, gradient circle nodes) |
| `frontend/src/components/learning/CardLearningView.jsx` | Card UI: MCQ, teaching, check-in (44KB) |
| **Frontend — State** | |
| `frontend/src/context/AuthContext.jsx` | JWT auth, refresh token rotation, visibility-based refresh |
| `frontend/src/context/SessionContext.jsx` | Session state machine (phases, cards, chunks) |
| `frontend/src/store/adaptiveStore.js` | Zustand: XP, level, streak, mode, badges |
| **Testing** | |
| `frontend/e2e/` | 11 Playwright test files, 90+ E2E tests |
| `frontend/playwright.config.js` | Playwright config (Chromium, 1 worker, 60s timeout) |

---

## Design System (Orange Primary)

| Token | Light | Dark |
|-------|-------|------|
| `--color-primary` | `#F97316` | `#FB923C` |
| `--color-primary-dark` | `#EA580C` | `#F97316` |
| `--color-bg` | `#FAFAFA` | `#0F172A` |
| `--color-surface` | `#FFFFFF` | `#1E293B` |
| `--color-success` | `#22C55E` | `#4ADE80` |
| `--color-danger` | `#EF4444` | `#F87171` |
| `--color-info` | `#3B82F6` | `#60A5FA` |

Shape: pill buttons (rounded-full), rounded-2xl cards, rounded-xl inputs. Framer Motion on all interactions.

---

## Security Hardening (Applied)

| Fix | Description |
|-----|-------------|
| Auth rate limiting | All 9 auth endpoints: 3-60 req/min per endpoint |
| Secret auto-generation | JWT_SECRET_KEY + API_SECRET_KEY auto-generated in dev mode |
| SMTP warning | Startup log if SMTP not configured (OTPs will fail) |
| Ownership validation | `/api/v3/adaptive/lesson` checks user owns student_id |
| Route deduplication | Removed duplicate `/api/v2/sessions/{id}/complete-card` from adaptive_router |
| Student creation commit | `await db.commit()` after student flush |
| Refresh token race fix | `refreshPromiseRef` deduplicates concurrent refresh calls |
| Auth persistence fix | Only 401/403 clears session; transient errors retry without logout |
| Exception leak fix | Generic error messages to client, detailed logs server-side |
| datetime fix | `datetime.utcnow()` → `datetime.now(timezone.utc)` |
| DB indexes | 5 new indexes (conversation_messages, chunk_images, card_interactions, xp_events, student_badges) |
| Admin pagination | `GET /api/admin/users` now paginated (limit/offset) |
