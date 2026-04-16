"""
Async database connection and session factory for PostgreSQL.
"""

import os

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from config import DATABASE_URL

# PRODUCTION: Ensure DATABASE_URL includes ?sslmode=require for encrypted connections to RDS.
# Example: postgresql+asyncpg://user:pass@host:5432/db?sslmode=require
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=int(os.environ.get("DB_POOL_SIZE", 20)),
    max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", 80)),
    pool_pre_ping=True,   # detect stale connections after RDS failover
    pool_recycle=3600,    # recycle connections every hour to avoid server-side timeouts
)

async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db():
    """FastAPI dependency that yields a database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """
    Database initialisation hook called at FastAPI lifespan startup.

    Schema management is handled exclusively by Alembic migrations.
    To apply migrations before starting the server run:

        cd backend && alembic upgrade head

    This function intentionally performs no DDL so that production schema
    changes are always versioned, reviewed, and reversible.
    """
    # Verify that the engine can reach the database on startup.
    # This gives an early, clear error if DATABASE_URL is misconfigured.
    async with engine.connect() as conn:
        await conn.execute(__import__("sqlalchemy").text("SELECT 1"))


async def close_db():
    """Dispose of the engine connection pool."""
    await engine.dispose()
