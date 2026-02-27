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
- See `migrations.md` for detailed migration history

## Files Created / Owned

| File | Purpose |
|---|---|
| `backend/pytest.ini` | Pytest config: asyncio_mode, testpaths, filterwarnings |
| `backend/tests/conftest.py` | sys.path fix + marker registration |
| `backend/requirements.txt` | Added pytest>=8.0.0, pytest-asyncio>=0.23.0 |
| `backend/alembic.ini` | Alembic config: script_location, prepend_sys_path=src, blank sqlalchemy.url |
| `backend/alembic/env.py` | Async-compatible env: asyncio.run + run_sync pattern |
| `backend/alembic/versions/e3c02cf4c22e_*.py` | Initial migration: card_interactions + spaced_reviews |

## Tech Debt Status

| Issue | Status |
|---|---|
| No pytest.ini / conftest.py | Done |
| pytest / pytest-asyncio not in requirements.txt | Done |
| Base.metadata.create_all() instead of Alembic | Done — replaced with connectivity ping |
| No Dockerfile | Pending |
| No docker-compose.yml | Pending |
| No CI/CD pipeline | Pending |
| No frontend test framework (vitest) | Pending |
| No .env.example files | Pending |
| Bare print() statements in main.py | Pending |
| No startup env validation in config.py | Pending |

## Notes

- Platform: Windows 11, shell: bash — use forward slashes and Unix syntax in all scripts
- Venv: `.venv/` at project root; activate with `source ../.venv/Scripts/activate` from within `backend/`
- Database: `postgresql+asyncpg://postgres:postre2002@localhost:5432/AdaptiveLearner`
- When integration tests are added, see `testing.md` (to be created) for test DB provisioning strategy
