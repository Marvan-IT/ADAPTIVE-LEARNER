# DevOps Engineer Memory

## Key Infrastructure Decisions

- **Test framework**: pytest 8+ with pytest-asyncio 0.23+ (`asyncio_mode = auto`)
- **Test markers**: `unit`, `integration`, `e2e` registered in `conftest.py` via `pytest_configure`
- **sys.path setup**: `conftest.py` inserts `backend/src` at index 0 so tests import project source without an editable install
- **Test location**: `backend/tests/` — `pytest.ini` sets `testpaths = tests`

## Alembic Setup

- **Location**: `backend/alembic/` + `backend/alembic.ini` (NOT at project root)
- **sys.path**: `alembic.ini` sets `prepend_sys_path = src` — matches uvicorn's import context
- **URL strategy**: `sqlalchemy.url` intentionally blank in `alembic.ini`; `env.py` reads `DATABASE_URL` from `backend/.env` via `python-dotenv`
- **Async pattern**: `asyncio.run()` + `AsyncConnection.run_sync(do_run_migrations)` — required for asyncpg; `sync_engine.connect()` does NOT work (MissingGreenlet error)
- **compare_type=True**: set in `context.configure()` so column type changes are detected by autogenerate
- **Migration runbook**: `cd backend && alembic upgrade head` | rollback: `alembic downgrade -1`
- **connection.py init_db()**: replaced `create_all` with a connectivity ping (`SELECT 1`) — no DDL in app startup
- **Migration chain**: e3c02cf4c22e → 92b08c7eb40b → 003_add_xp_streak_and_indices → 004_add_socratic_remediation_fields (head)
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
| No Dockerfile | Pending |
| No docker-compose.yml | Pending |
| No CI/CD pipeline | Pending |
| No frontend test framework (vitest) | Pending |
| No startup env validation in config.py | Done — validate_required_env_vars() in config.py; called first in lifespan |

## Notes

- Platform: Windows 11, shell: bash — use forward slashes and Unix syntax in all scripts
- Venv: `.venv/` at project root; activate with `source ../.venv/Scripts/activate` from within `backend/`
- Database: `postgresql+asyncpg://postgres:<password>@localhost:5432/AdaptiveLearner` — password comes from DATABASE_URL env var; no hardcoded default in config.py
- `STARTER_PACK_MAX_SECTIONS` is a hardcoded constant in `config.py`, not an env var — no .env.example entry needed
- When integration tests are added, see `testing.md` (to be created) for test DB provisioning strategy
