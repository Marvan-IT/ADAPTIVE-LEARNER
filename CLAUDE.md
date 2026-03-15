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

# ADA — Adaptive Learning Platform

An AI-powered adaptive education platform that teaches mathematics through personalized, Socratic pedagogical loops. It combines Retrieval-Augmented Generation (RAG) with dependency graph traversal to deliver concept-by-concept lessons from 16 OpenStax textbooks across 13 languages.

---

## Project Structure

```
ADA/
├── docs/                     # Design artifacts — one folder per feature
│   └── {feature-name}/
│       ├── HLD.md            # High-Level Design (produced by solution-architect)
│       ├── DLD.md            # Detailed Low-Level Design
│       └── execution-plan.md # Phased WBS, DoD, rollout strategy
├── backend/                  # Python FastAPI server
│   ├── src/
│   │   ├── api/              # FastAPI routers, services, schemas, prompts
│   │   ├── db/               # SQLAlchemy ORM models and PostgreSQL connection
│   │   ├── extraction/       # PDF → concept block pipeline
│   │   ├── graph/            # NetworkX dependency graph
│   │   ├── storage/          # ChromaDB vector store wrapper
│   │   ├── images/           # PDF image extraction + Mathpix OCR
│   │   ├── adaptive/         # Adaptive learning engine: profiling, XP, card generation
│   │   ├── config.py         # All constants, paths, API keys
│   │   ├── models.py         # Data models
│   │   └── pipeline.py       # End-to-end extraction orchestration
│   ├── data/                 # Input PDF textbooks (do not commit — 1GB+)
│   ├── output/               # Pipeline output: ChromaDB, JSON graphs, images (do not commit)
│   ├── tests/                # pytest test suite (directory exists, needs setup)
│   └── requirements.txt
├── frontend/                 # React 19 + Vite 7 SPA
│   ├── src/
│   │   ├── api/              # Axios client wrappers per resource
│   │   ├── pages/            # Route-level components
│   │   ├── components/       # Reusable UI components
│   │   ├── context/          # React Context for student, session, theme
│   │   ├── hooks/            # Custom React hooks
│   │   ├── locales/          # i18next translation files (13 languages)
│   │   ├── theme/            # Tailwind theme config
│   │   └── utils/            # PostHog analytics
│   └── package.json
└── .claude/
    ├── agents/               # Subagent definitions (5 agents)
    └── agent-memory/         # Persistent per-agent institutional memory
```

---

## Tech Stack

### Backend
| Concern | Technology |
|---|---|
| Framework | FastAPI 0.128+ (async) |
| Server | Uvicorn |
| Database | PostgreSQL 15 via SQLAlchemy 2.0 async + asyncpg |
| Migrations | Alembic (setup pending — see Technical Debt) |
| Vector Store | ChromaDB 0.5 (collection: `openstax_concepts`) |
| Graph Engine | NetworkX 3+ (DAG of concept prerequisites) |
| LLM | OpenAI API — `gpt-4o` for generation, `gpt-4o-mini` for lightweight tasks |
| Embeddings | `text-embedding-3-small` (1536 dimensions) |
| PDF Parsing | PyMuPDF 1.24 |
| Math OCR | Mathpix API |
| Validation | Pydantic 2.0+ |

### Frontend
| Concern | Technology |
|---|---|
| Framework | React 19 + Vite 7 |
| Routing | React Router DOM 7 |
| Styling | Tailwind CSS 4 + PostCSS |
| Graph Viz | Custom SVG component (`ConceptGraph.jsx`) with pan/zoom/blink |
| HTTP | Axios 1.13 |
| Math Render | KaTeX 0.16 + remark-math + rehype-katex |
| Markdown | react-markdown 10 |
| i18n | i18next 25 (13 languages: en, ar, de, es, fr, hi, ja, ko, ml, pt, si, ta, zh) |
| Analytics | PostHog |
| Icons | Lucide React |

### Infrastructure
- **Python venv**: `.venv/` at project root
- **Node**: npm (package-lock.json)
- **Environment**: `.env` files in `backend/` and `frontend/` — never commit these; `.env.example` files are the source of truth for required keys
- **ChromaDB data**: `backend/output/prealgebra/chroma_db/` — do not commit (large binary data)

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
```

### Frontend (`frontend/.env`)
```
VITE_API_BASE_URL=http://localhost:8000
VITE_POSTHOG_KEY=
VITE_API_SECRET_KEY=       # must match backend API_SECRET_KEY
```

---

## Database Schema

### Tables (PostgreSQL, SQLAlchemy async ORM)
- **`students`** — id, name, interests, language, style preferences
- **`teaching_sessions`** — id, student_id (FK), concept_id, phase, mastery_score, timestamps
- **`conversation_messages`** — id, session_id (FK), role, content, phase, order
- **`student_mastery`** — id, student_id (FK), concept_id, mastered_at (unique constraint)

Cascading deletes are enforced on all foreign keys. Schema changes must go through Alembic migrations — never use `Base.metadata.create_all()` in production.

---

## Core Architecture

### Hybrid RAG + Graph Engine
Every concept query combines two retrieval strategies:
1. **Semantic search** (ChromaDB) — finds the most relevant concept blocks by embedding similarity
2. **Graph traversal** (NetworkX) — resolves prerequisites and learning readiness from the DAG

Results are enriched with student mastery context before being passed to the LLM.

### Pedagogical Loop
Teaching sessions run through two phases managed by `teaching_service.py`:
1. **Presentation** — metaphor-based explanation using LLM + knowledge base context
2. **Socratic Check** — guided questioning; the assistant never gives direct answers
3. **Mastery threshold** — 70 points (out of 100) required to mark a concept as mastered (constant in `config.py` as `MASTERY_THRESHOLD = 70`)

### Data Extraction Pipeline
```
PDF → pdf_reader → text_cleaner → section_detector → content_filter
    → concept_builder → llm_extractor → ChromaDB + NetworkX graph
    → image_extractor → Mathpix OCR → image_index.json
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
FastAPI endpoints, services, schemas, ChromaDB/NetworkX integrations per DLD.

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
- Mastery threshold is `70` (score out of 100) — defined in `config.py` as `MASTERY_THRESHOLD = 70`, not hardcoded

### Frontend (JavaScript/JSX)
- React 19 functional components only — no class components
- All API calls go through `src/api/` client wrappers — no direct `fetch`/axios in components
- State that crosses routes lives in a Context (`src/context/`) — no prop drilling beyond 2 levels
- i18n: all user-visible strings use `useTranslation()` hook — no hardcoded English strings
- Inline `style={{}}` objects are the primary styling approach for components; Tailwind classes are used for utility tokens only
- Handle all three UI states: loading, error, and empty
- Math content renders via KaTeX through `react-markdown` + `remark-math` + `rehype-katex`

### General
- Never commit `.env` files, PDF data files (`backend/data/`), or ChromaDB data (`backend/output/`)
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
| Stale cached cards returned forever despite prompt rebuilds | `cache_version: 2` check forces regeneration when version is behind | `teaching_service.py` |
| Image filenames in index don't match files on disk | `get_concept_images()` tries indexed name then PDF page-number fallback | `knowledge_service.py` |
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

### ⚠️ Known Technical Debt (Requires devops-engineer)

| Issue | File | Priority |
|---|---|---|
| `Base.metadata.create_all()` instead of Alembic | `backend/src/db/connection.py:29` | Critical |
| No Dockerfile | — | Critical |
| No `docker-compose.yml` | — | Critical |
| No CI/CD pipeline | — | Critical |
| No frontend test framework (no vitest) | `frontend/package.json` | High |
| `backend/src/models.py` duplicates `db/models.py` | `backend/src/models.py` | Low |

### 🏗️ Out of Scope (Architectural — Defer)

- **ChromaDB local storage**: Cannot scale horizontally. Requires Chroma Cloud / Pinecone / Weaviate.
- **Translation cache persistence**: Per-worker dict; use PostgreSQL `concept_translations` table for multi-worker.
- **Circuit breaker for OpenAI**: Requires `tenacity` library.
- **C1 Per-student authorization**: Full COPPA/FERPA compliance requires auth middleware overhaul.

---

## Running the Project

### Backend
```bash
cd backend
source ../.venv/Scripts/activate   # Windows: source ../.venv/Scripts/activate.bat
pip install -r requirements.txt
# IMPORTANT: use python -m uvicorn (not bare uvicorn) to ensure venv deps are loaded
# Port 8889 is used (8000/8001/8888 may be held by stale OS processes from previous sessions)
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
# Until Alembic is initialized, the DB tables are created on first backend start
# Once Alembic is set up by the devops-engineer, use:
cd backend
alembic upgrade head
```

### Data Extraction Pipeline
```bash
# Run once per textbook to populate ChromaDB + graph
cd backend
python -m src.pipeline --book prealgebra
```

---

## Key File Locations

| File | Purpose |
|---|---|
| `backend/src/api/main.py` | FastAPI app entrypoint, CORS, lifespan, routers |
| `backend/src/api/knowledge_service.py` | RAG + graph query orchestration |
| `backend/src/api/teaching_service.py` | Pedagogical loop (presentation + Socratic check) + card generation |
| `backend/src/api/prompts.py` | All LLM system prompts — card generation, Socratic, adaptive |
| `backend/src/api/teaching_schemas.py` | Pydantic request/response schemas including `RegenerateMCQRequest` |
| `backend/src/api/teaching_router.py` | All `/api/v2/sessions/` endpoints including `regenerate-mcq` |
| `backend/src/db/models.py` | SQLAlchemy ORM tables |
| `backend/src/config.py` | All constants: paths, model names, thresholds, book slugs |
| `backend/src/adaptive/adaptive_engine.py` | Adaptive learning engine: student profiling, XP, card difficulty |
| `backend/src/adaptive/prompt_builder.py` | Single-card adaptive prompt builder |
| `frontend/src/App.jsx` | Root component with React Router routes |
| `frontend/src/pages/ConceptMapPage.jsx` | Dependency graph visualization (Sigma) |
| `frontend/src/pages/LearningPage.jsx` | Teaching session interface |
| `frontend/src/context/` | StudentContext, SessionContext, ThemeContext |
| `frontend/src/components/learning/CardLearningView.jsx` | Card-based lesson UI: MCQ, mastery bar, diagram rendering |
| `frontend/src/components/learning/MathDiagram.jsx` | SVG renderer for `[MATH_DIAGRAM:type:params]` markers |
| `frontend/src/api/sessions.js` | Axios wrappers for all session endpoints |
| `docs/` | All HLD/DLD/execution-plan artifacts (source of truth for design) |
| `.claude/agents/` | Subagent definitions for the 5-agent workflow |
| `.claude/agent-memory/` | Persistent per-agent memory (do not delete) |
