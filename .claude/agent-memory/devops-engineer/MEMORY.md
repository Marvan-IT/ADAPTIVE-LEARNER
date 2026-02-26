# DevOps Engineer Memory

## Key Infrastructure Decisions

- **Test framework**: pytest 8+ with pytest-asyncio 0.23+ (`asyncio_mode = auto`)
- **Test markers**: `unit`, `integration`, `e2e` registered in `conftest.py` via `pytest_configure`
- **sys.path setup**: `conftest.py` inserts `backend/src` at index 0 so tests import project source without an editable install
- **Test location**: `backend/tests/` — `pytest.ini` sets `testpaths = tests`

## Files Created / Owned

| File | Purpose |
|---|---|
| `backend/pytest.ini` | Pytest config: asyncio_mode, testpaths, filterwarnings |
| `backend/tests/conftest.py` | sys.path fix + marker registration |
| `backend/requirements.txt` | Added pytest>=8.0.0, pytest-asyncio>=0.23.0 |

## Tech Debt Status

| Issue | Status |
|---|---|
| No pytest.ini / conftest.py | Done |
| pytest / pytest-asyncio not in requirements.txt | Done |
| Base.metadata.create_all() instead of Alembic | Pending |
| No Dockerfile | Pending |
| No docker-compose.yml | Pending |
| No CI/CD pipeline | Pending |
| No frontend test framework (vitest) | Pending |
| No .env.example files | Pending |
| Bare print() statements in main.py | Pending |
| No startup env validation in config.py | Pending |

## Notes

- Platform: Windows 11, shell: bash — use forward slashes and Unix syntax in all scripts
- When integration tests are added, see `testing.md` (to be created) for test DB provisioning strategy
