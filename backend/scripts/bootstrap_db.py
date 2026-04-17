"""Bootstrap a fresh database by creating all tables from ORM models.

Usage (inside Docker container):
    python -m scripts.bootstrap_db

This is the recommended way to set up a fresh production database.
It creates all tables using SQLAlchemy's create_all() and then stamps
Alembic to the latest revision so future migrations work correctly.

For existing databases, use `alembic upgrade head` instead.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

# Ensure backend/src is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Prefer the environment variable (set by Docker Compose) over .env file.
# This ensures the script works inside Docker where DATABASE_URL points to
# the 'db' service hostname, not 'localhost'.
_db_url = os.environ.get("DATABASE_URL", "")
if not _db_url:
    from config import DATABASE_URL
    _db_url = DATABASE_URL


async def main() -> None:
    if not _db_url:
        print("ERROR: DATABASE_URL is not set. Check backend/.env or environment.")
        sys.exit(1)

    print(f"Connecting to database...")
    engine = create_async_engine(_db_url, echo=False)

    # Import ALL model modules explicitly so Base.metadata knows every table.
    # db.models imports auth.models at the bottom, so both are covered.
    from db.models import Base  # noqa: F401
    import auth.models  # noqa: F401 — explicit import, don't rely on side effects

    # Enable pgvector extension (required for Vector column type)
    print("Enabling pgvector extension...")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    print("Creating all tables from ORM models...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("All tables created successfully.")

    # Stamp Alembic to the latest head so future migrations work
    print("Stamping Alembic to latest revision...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "stamp", "head"],
        cwd=str(Path(__file__).resolve().parent.parent),
        env=os.environ.copy(),  # Pass environment to subprocess
    )
    if result.returncode == 0:
        print("Database bootstrap complete!")
    else:
        print("WARNING: Alembic stamp failed. Run 'alembic stamp head' manually.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
