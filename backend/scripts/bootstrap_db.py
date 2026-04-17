"""Bootstrap a fresh database by creating all tables from ORM models.

Usage (inside Docker container):
    python -m scripts.bootstrap_db

This is the recommended way to set up a fresh production database.
It creates all tables using SQLAlchemy's create_all() and then stamps
Alembic to the latest revision so future migrations work correctly.

For existing databases, use `alembic upgrade head` instead.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

# Ensure backend/src is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy.ext.asyncio import create_async_engine
from config import DATABASE_URL


async def main() -> None:
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL is not set. Check backend/.env")
        sys.exit(1)

    engine = create_async_engine(DATABASE_URL, echo=False)

    # Import all models so Base.metadata knows about every table
    from db.models import Base  # noqa: F401 — triggers auth.models import too

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
    )
    if result.returncode == 0:
        print("Database bootstrap complete!")
    else:
        print("WARNING: Alembic stamp failed. Run 'alembic stamp head' manually.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
