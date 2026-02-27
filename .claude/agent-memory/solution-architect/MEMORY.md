# Solution Architect Agent Memory — ADA Platform

Last updated: 2026-02-27

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

### Completed Designs
- `docs/adaptive-learning-engine/` — HLD, DLD, execution-plan (2026-02-25)
- `docs/concept-enrichment/` — HLD, DLD, execution-plan (2026-02-26)
- `docs/adaptive-real-tutor/` — HLD, DLD, execution-plan (2026-02-27)
