"""
Alembic environment configuration for ADA.

Uses asyncio.run() + AsyncConnection.run_sync() so that Alembic's synchronous
migration runner works with asyncpg (an async-only DBAPI).  This is the
pattern recommended in the SQLAlchemy 2.0 docs for async + Alembic:
https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic

DATABASE_URL is read from backend/.env via python-dotenv.
"""

import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncConnection
from sqlalchemy import pool

from alembic import context

# ---------------------------------------------------------------------------
# 1.  Load .env — must happen before any DB URL is read.
#     __file__ is backend/alembic/env.py; parent.parent is backend/.
# ---------------------------------------------------------------------------
_backend_dir = Path(__file__).resolve().parent.parent
load_dotenv(_backend_dir / ".env")

# ---------------------------------------------------------------------------
# 2.  Import ORM Base for autogenerate support.
#     alembic.ini prepends backend/src to sys.path, matching uvicorn's path.
# ---------------------------------------------------------------------------
from db.models import Base  # noqa: E402
import auth.models  # noqa: E402, F401  — register auth tables with Base.metadata

# ---------------------------------------------------------------------------
# 3.  Standard Alembic config wiring.
# ---------------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# 4.  Resolve database URL.
#     Env var takes priority; alembic.ini sqlalchemy.url is left blank
#     so secrets are never committed to source control.
# ---------------------------------------------------------------------------
def _get_url() -> str:
    url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Add it to backend/.env or export it as an environment variable."
        )
    return url


# ---------------------------------------------------------------------------
# 5.  Offline mode — emit SQL without a live connection.
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """Generate a SQL script without connecting to the database."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# 6.  Online mode — asyncio.run() + run_sync() pattern.
#
#     Alembic is sync; asyncpg is async-only.  The supported bridge is:
#       async with engine.connect() as async_conn:
#           await async_conn.run_sync(do_run_migrations)
#     where do_run_migrations receives a regular sync Connection object that
#     Alembic can use normally.
# ---------------------------------------------------------------------------
def do_run_migrations(connection) -> None:
    """Called by run_sync inside an async context; receives a sync Connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,  # detect column type changes (e.g. Float -> Numeric)
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async() -> None:
    """Create async engine, open async connection, hand sync conn to Alembic."""
    url = _get_url()
    async_engine = create_async_engine(url, poolclass=pool.NullPool)

    async with async_engine.connect() as async_conn:
        await async_conn.run_sync(do_run_migrations)

    await async_engine.dispose()


def run_migrations_online() -> None:
    """Entry point for online mode; bridges into asyncio."""
    asyncio.run(run_migrations_online_async())


# ---------------------------------------------------------------------------
# 7.  Dispatch.
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
