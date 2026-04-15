# DevOps Engineer Memory

## Key Infrastructure Decisions

- **Test framework**: pytest 8+ with pytest-asyncio 0.23+ (`asyncio_mode = auto`)
- **Test markers**: `unit`, `integration`, `e2e` registered in `conftest.py` via `pytest_configure`
- **sys.path setup**: `conftest.py` inserts `backend/src` at index 0 so tests import project source without an editable install
- **Test location**: `backend/tests/` — `pytest.ini` sets `testpaths = tests`
- **Async fixture decorator**: new async fixtures use `@pytest_asyncio.fixture`; existing `db_session` uses plain `@pytest.fixture` (works under `asyncio_mode=auto` — leave as-is to avoid churn)
- **DB factory fixtures**: `test_chunk` and `test_chunk_image` in `conftest.py` create live rows for integration tests; both auto-skip if DB is unavailable (inherit from `db_session`)
- **Model imports in fixtures**: lazy-imported inside the fixture body (`from db.models import ConceptChunk`) — `sys.path` is already set by the module-level insert so `db.models` resolves correctly

## Alembic Setup

- **Location**: `backend/alembic/` + `backend/alembic.ini` (NOT at project root)
- **sys.path**: `alembic.ini` sets `prepend_sys_path = src` — matches uvicorn's import context
- **URL strategy**: `sqlalchemy.url` intentionally blank in `alembic.ini`; `env.py` reads `DATABASE_URL` from `backend/.env` via `python-dotenv`
- **Async pattern**: `asyncio.run()` + `AsyncConnection.run_sync(do_run_migrations)` — required for asyncpg; `sync_engine.connect()` does NOT work (MissingGreenlet error)
- **compare_type=True**: set in `context.configure()` so column type changes are detected by autogenerate
- **Migration runbook**: `cd backend && alembic upgrade head` | rollback: `alembic downgrade -1`
- **connection.py init_db()**: replaced `create_all` with a connectivity ping (`SELECT 1`) — no DDL in app startup
- **Migration chain**: 0001 → e3c02cf4c22e → 92b08c7eb40b → 003 → 004 → 005_add_adaptive_history_columns → 006_chunk_architecture → 007_chunk_progress → 008_remove_book_slug_server_default → 009_add_admin_tables → … → 013_add_chunk_type_locked → 014_add_performance_indexes → 015_gamification_system (head)
- **0001 is the baseline**: tables students/teaching_sessions/conversation_messages/student_mastery pre-existed; 0001 uses SELECT 1 no-op + idempotent DO $$ blocks for CHECK constraints
- See `migrations.md` for detailed migration history

## Files Created / Owned

| File | Purpose |
|---|---|
| `backend/pytest.ini` | Pytest config: asyncio_mode, testpaths, filterwarnings |
| `backend/tests/conftest.py` | sys.path fix + marker registration + 3 shared fixtures (fake_concept_detail, mock_knowledge_svc, mock_llm_client) |
| `backend/requirements.txt` | Added pytest>=8.0.0, pytest-asyncio>=0.23.0 |
| `backend/alembic.ini` | Alembic config: script_location, prepend_sys_path=src, blank sqlalchemy.url |
| `backend/alembic/env.py` | Async-compatible env: asyncio.run + run_sync pattern |
| `backend/alembic/versions/e3c02cf4c22e_*.py` | Initial migration: card_interactions + spaced_reviews |
| `backend/alembic/versions/92b08c7eb40b_*.py` | card_interactions composite index + spaced_reviews unique constraint |
| `backend/alembic/versions/003_add_xp_streak_and_indices.py` | students.xp, students.streak, three FK indexes |
| `backend/alembic/versions/004_add_socratic_remediation_fields.py` | TeachingSession remediation columns + 3 new indexes |
| `backend/alembic/versions/0001_initial_schema.py` | Baseline: SELECT 1 no-op + ck_session_phase + ck_check_score_range CHECK constraints (idempotent) |
| `backend/alembic/versions/006_chunk_architecture.py` | pgvector extension + concept_chunks (HNSW index) + chunk_images + 5 TeachingSession exam columns — verified complete; no 007 needed |
| `backend/alembic/__init__.py` | Empty init file for alembic package |
| `backend/Dockerfile` | Multi-stage: python:3.11-slim, non-root user ada, port 8889 |
| `frontend/Dockerfile` | Multi-stage: node:20-alpine builder → nginx:alpine, port 80 |
| `frontend/nginx.conf` | SPA fallback + /api/ /images/ /static/ proxy to backend:8889 |
| `docker-compose.yml` (project root) | db (pgvector/pgvector:pg16-alpine) + backend + frontend; postgres_data named volume |
| `.github/workflows/ci.yml` | backend-lint + frontend-build + deploy jobs; deploy uses appleboy/ssh-action@v1, runs only on push to main after both jobs pass |
| `scripts/s3_pipeline_poller.py` | SQS poller: S3 PDF download → docker compose exec pipeline → hot-reload webhook; reads ADA_SQS_QUEUE_URL, ADA_S3_BUCKET, ADA_API_SECRET_KEY, ADA_PROJECT_PATH |
| `scripts/ada-pipeline.service` | systemd unit for the SQS poller; User=ubuntu, EnvironmentFile=scripts/.pipeline.env, RestartSec=30s |
| `scripts/aws-setup.md` | One-time AWS setup runbook: S3 bucket, SQS queue, S3→SQS notification, IAM instance profile, systemd deploy, GitHub Secrets |

## Rate Limiting Reference

All endpoints in `teaching_router.py` use `@limiter.limit()`. The `adaptive_router.py` was missing rate limits; fixed in health check 2026-03-10.

| Endpoint | Limit | Reason |
|---|---|---|
| `POST /api/v3/adaptive/lesson` | 10/min | Full LLM lesson generation — expensive |
| `POST /api/v2/sessions/{id}/complete-card` | 60/min | Per-card adaptive call; ~20 cards/session ceiling; 60/min allows bursting |
| `POST /sessions/{id}/cards` | 10/min | Starter-pack LLM generation |
| `POST /sessions/{id}/respond` | 10/min | Socratic LLM call |
| General CRUD | 30/min | Standard CRUD endpoints |

- `complete-card` is now called once per card click (not once per session). 60/min gives 3 clicks/second headroom — well above any human pace.
- `cards_router` in `adaptive_router.py` uses `APIRouter(tags=["adaptive-cards"])` with no prefix. Rate limiter from `api.rate_limiter` must be imported explicitly (no automatic inheritance from app.state).

## Tech Debt Status

| Issue | Status |
|---|---|
| No pytest.ini / conftest.py | Done |
| pytest / pytest-asyncio not in requirements.txt | Done |
| Base.metadata.create_all() instead of Alembic | Done — replaced with connectivity ping |
| .env.example files | Done — backend/.env.example and frontend/.env.example exist |
| Bare print() statements in main.py | Done |
| No rate limit on complete-card endpoint | Done (2026-03-10 health check) |
| No Dockerfile | Done — backend/Dockerfile + frontend/Dockerfile |
| No docker-compose.yml | Done — docker-compose.yml at project root |
| No CI/CD pipeline | Done — .github/workflows/ci.yml (lint + build + deploy to EC2 via SSH) |
| No frontend test framework (vitest) | Pending |
| No startup env validation in config.py | Done — validate_required_env_vars() in config.py; called first in lifespan |

## Pipeline / Image Extraction Notes

- ALG1 PDF TOC uses `"Lesson N.N Title"` format; all other books use bare `"N.N Title"`. Fix: add `toc_section_pattern` key to ALG1 entry in `BOOK_REGISTRY` and update `_load_source_pages_from_pdf()` in `pipeline.py` to prefer it.
- `_load_source_pages_from_pdf()` returns empty dict when 0 TOC entries match → Stage C silently skips image extraction. Always confirm `len(toc_sections) > 0` after adding a new book.
- Re-running pipeline with cached MMD overwrites `dependency_graph.json` (Stage E). Any manual graph patches must be re-applied AFTER the pipeline completes.
- `image_index.json` is keyed by `concept_id`; values are lists of `{filename, width, height, image_type, page, description, relevance}`. Only images where `is_educational=True` AND `description` is non-null are indexed.

## Dependency Graph Patch History (2026-03-17)

| Book | Edge Added | Reason |
|---|---|---|
| algebra_1 | `ALG1.C4.S18` → `ALG1.C5.S1.PROPERTIES_OF_EXPONENTS` | Ch4→Ch5 continuity |
| college_algebra | 7 cross-chapter edges (Ch2→Ch5, Ch3→Ch4, Ch3→Ch6, Ch5→Ch7, etc.) | Missing inter-chapter prerequisite links |
| elementary_algebra | `ELEMALG.C2.S7` → `ELEMALG.C3.S1.USE_A_PROBLEM_SOLVING_STRATEGY` | Isolated node fix |
| intermediate_algebra | `INTERALG.C9.S8` → `INTERALG.C10.S1.FINDING_COMPOSITE_AND_INVERSE_FUNCTIONS` | Isolated node fix |

## graph_builder.py Notes

- `psql` binary is at `C:/Program Files/PostgreSQL/18/bin/psql.exe` on this machine (not in PATH)
- When running graph_builder.py directly, use `PYTHONPATH=backend/src python backend/src/extraction/graph_builder.py --book <slug>`
- **Bug fixed 2026-03-28**: `SELECT DISTINCT ... ORDER BY order_index` fails in PostgreSQL when `order_index` is not in the SELECT list. Fixed by removing `.order_by(ConceptChunk.order_index)` — the numeric re-sort on `_section_sort_key` at line 96 gives correct chapter/section ordering anyway.
- Prealgebra graph: 60 nodes, 49 edges (60 sections - 11 chapters = 49 sequential edges, one per chapter boundary)
- Concept ID format in graph.json: `{book_slug}_{chapter}.{section}` e.g. `prealgebra_1.1`

## concept_chunks Cleanup (2026-03-28)

- Prealgebra had 70 spurious concept_ids (exercise problem numbers like `prealgebra_2.9`); reparented 10 of them to their parent sections
- After cleanup: 60 distinct concept_ids, 1063 total chunks preserved (no data deleted)
- Rows updated per statement: 2.9+2.10→2.1 (8 rows), 3.7+3.8→3.1 (12 rows), 6.6+6.10→6.1 (6 rows), 6.7→6.2 (11 rows), 10.9→10.4 (19 rows), 11.7+11.8→11.1 (11 rows)

## Notes

- Platform: Windows 11, shell: bash — use forward slashes and Unix syntax in all scripts
- Venv: `.venv/` at project root; activate with `source ../.venv/Scripts/activate` from within `backend/`
- Database: `postgresql+asyncpg://postgres:<password>@localhost:5432/AdaptiveLearner` — password comes from DATABASE_URL env var; no hardcoded default in config.py
- `STARTER_PACK_MAX_SECTIONS` is a hardcoded constant in `config.py`, not an env var — no .env.example entry needed
- When integration tests are added, see `testing.md` (to be created) for test DB provisioning strategy
