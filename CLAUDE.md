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
| Graph Viz | Sigma 3 + React-Sigma 5 + Graphology |
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
```

### Frontend (`frontend/.env`)
```
VITE_API_BASE_URL=http://localhost:8000
VITE_POSTHOG_KEY=
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
3. **Mastery threshold** — 70% score required to mark a concept as mastered (constant in `config.py`)

### Data Extraction Pipeline
```
PDF → pdf_reader → text_cleaner → section_detector → content_filter
    → concept_builder → llm_extractor → ChromaDB + NetworkX graph
    → image_extractor → Mathpix OCR → image_index.json
```
Supported: 16 OpenStax math textbooks (Prealgebra through Calculus III). Pipeline entry point: `backend/src/pipeline.py`.

---

## Development Workflow

This project uses a structured 5-agent workflow. Every significant feature follows these stages:

### Stage 0 — Infrastructure (`devops-engineer` agent)
**Trigger**: Before a new feature can be tested or deployed; or whenever schema, deployment, or test infrastructure changes are needed.

The devops engineer handles all operational concerns:
- Alembic migration scripts for every schema change (never `create_all`)
- Dockerfile and `docker-compose.yml` for containerized local dev
- GitHub Actions CI/CD workflows (lint, test, build, deploy)
- `pytest.ini`, `conftest.py`, test database provisioning
- `.env.example` templates with all required keys documented
- Structured logging setup, health/readiness endpoints
- Secrets validation on startup (fail fast if required env vars are missing)

### Stage 1 — Design (`solution-architect` agent)
**Trigger**: Any new feature, system component, or significant change.

The solution architect produces three mandatory deliverables **written to disk** before any code is written:

```
docs/{feature-name}/
├── HLD.md            ← High-Level Design
├── DLD.md            ← Detailed Low-Level Design
└── execution-plan.md ← Phased WBS, DoD, rollout
```

The HLD/DLD/Execution Plan are the source of truth for implementation. No backend or frontend work begins without them.

### Stage 2 — Backend Implementation (`backend-developer` agent)
**Trigger**: After `docs/{feature-name}/` contains the complete design artifacts.

The backend developer consumes the design artifacts and implements:
- FastAPI endpoints and routers per DLD API contracts
- SQLAlchemy models per DLD data model (schema changes flagged to devops-engineer for migration)
- Business logic services (knowledge, teaching, extraction, graph)
- ChromaDB and NetworkX integrations
- Security, error handling, and observability as specified in DLD
- Follows execution plan phases: Foundation → Core Logic → Integration → Hardening

### Stage 3 — Testing (`comprehensive-tester` agent)
**Trigger**: After each backend implementation phase (can run in parallel with Stage 4).

The tester writes coverage for all criteria in the execution plan's Definition of Done:
- **Unit tests** (pytest): isolated logic, mocks for DB/LLM/ChromaDB/NetworkX
- **Integration tests**: FastAPI TestClient + PostgreSQL test DB, ChromaDB in-memory
- **E2E tests**: full session lifecycle from student creation to mastery

Every test name must map to a business criterion (e.g., `test_teaching_session_marks_mastery_at_70_percent_score`). Test infrastructure (conftest.py, DB setup) is owned by the devops-engineer.

### Stage 4 — Frontend (`frontend-developer` agent)
**Trigger**: Runs in parallel with Stages 2 and 3, consuming `docs/{feature-name}/HLD.md` and `DLD.md` API contracts.

The frontend developer implements:
- React components consuming the API contracts defined in DLD
- State via React Context (StudentContext, SessionContext, ThemeContext)
- Graph visualization (Sigma + Graphology)
- Socratic chat UI, presentation view, spaced-repetition card view
- i18n for all 13 supported languages; RTL support for Arabic
- WCAG 2.1 AA accessibility, dark/light mode, mobile-first responsive design

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
- Mastery threshold is `0.70` — defined in `config.py`, not hardcoded in service files

### Frontend (JavaScript/JSX)
- React 19 functional components only — no class components
- All API calls go through `src/api/` client wrappers — no direct `fetch`/axios in components
- State that crosses routes lives in a Context (`src/context/`) — no prop drilling beyond 2 levels
- i18n: all user-visible strings use `useTranslation()` hook — no hardcoded English strings
- Tailwind utility classes only — no inline styles, no custom CSS unless unavoidable
- Handle all three UI states: loading, error, and empty
- Math content renders via KaTeX through `react-markdown` + `remark-math` + `rehype-katex`

### General
- Never commit `.env` files, PDF data files (`backend/data/`), or ChromaDB data (`backend/output/`)
- Never commit secrets, API keys, or credentials
- No `console.log` or `print()` debug statements in committed code
- New API endpoints require: Pydantic schema (backend) + Axios wrapper (frontend) + tests
- New DB columns require an Alembic migration (coordinate with devops-engineer)

---

## Known Technical Debt

These are real gaps identified in the codebase that must be addressed by the `devops-engineer` agent:

| Issue | File | Priority |
|---|---|---|
| `Base.metadata.create_all()` instead of Alembic | `backend/src/db/connection.py:29` | Critical |
| No Dockerfile | — | Critical |
| No `docker-compose.yml` | — | Critical |
| No CI/CD pipeline | — | Critical |
| No `pytest.ini` or `conftest.py` | `backend/tests/` (empty) | High |
| No frontend test framework (no vitest) | `frontend/package.json` | High |
| No `.env.example` files | `backend/`, `frontend/` | High |
| Bare `print()` statements as logging | `backend/src/api/main.py` | Medium |
| No startup env variable validation | `backend/src/config.py` | Medium |
| `backend/src/models.py` duplicates `db/models.py` | `backend/src/models.py` | Low |

---

## Running the Project

### Backend
```bash
cd backend
source ../.venv/Scripts/activate   # Windows: source ../.venv/Scripts/activate.bat
pip install -r requirements.txt
uvicorn src.api.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
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
| `backend/src/api/teaching_service.py` | Pedagogical loop (presentation + Socratic check) |
| `backend/src/api/prompts.py` | All LLM system prompts (including multi-language) |
| `backend/src/db/models.py` | SQLAlchemy ORM tables |
| `backend/src/config.py` | All constants: paths, model names, thresholds, book slugs |
| `frontend/src/App.jsx` | Root component with React Router routes |
| `frontend/src/pages/ConceptMapPage.jsx` | Dependency graph visualization (Sigma) |
| `frontend/src/pages/LearningPage.jsx` | Teaching session interface |
| `frontend/src/context/` | StudentContext, SessionContext, ThemeContext |
| `docs/` | All HLD/DLD/execution-plan artifacts (source of truth for design) |
| `.claude/agents/` | Subagent definitions for the 5-agent workflow |
| `.claude/agent-memory/` | Persistent per-agent memory (do not delete) |
