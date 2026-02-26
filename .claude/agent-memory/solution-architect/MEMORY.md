# Solution Architect Agent Memory — ADA Platform

Last updated: 2026-02-25

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

### Completed Designs
- `docs/adaptive-learning-engine/` — HLD, DLD, execution-plan (2026-02-25)
