"""Shared helper for live AdminConfig reads.

P3 and P4 use this module to read admin-tunable settings from the database
at request time instead of at module-load time.  All reads fall back to the
constants in config.py when no AdminConfig row exists for the requested key.

No caching — AdminConfig values are single-column PK lookups (sub-millisecond).
Memoisation would reintroduce the stale-value problem being fixed here.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import AdminConfig
from config import CHUNK_EXAM_PASS_RATE, OPENAI_MODEL, OPENAI_MODEL_MINI


async def get_admin_config(db: AsyncSession, key: str, fallback: str = "") -> str:
    """Live read from AdminConfig with explicit fallback. Sub-millisecond PK lookup."""
    row = (await db.execute(
        select(AdminConfig.value).where(AdminConfig.key == key)
    )).scalar_one_or_none()
    return row if row is not None else fallback


async def get_openai_model(db: AsyncSession, slot: str = "default") -> str:
    """Return the live OpenAI model string for the given slot.

    slot ∈ {'default', 'mini'}.  Falls back to OPENAI_MODEL / OPENAI_MODEL_MINI
    from config.py (which itself falls back to the OPENAI_MODEL env var) when no
    AdminConfig row exists.
    """
    key = "OPENAI_MODEL_MINI" if slot == "mini" else "OPENAI_MODEL"
    fallback = OPENAI_MODEL_MINI if slot == "mini" else OPENAI_MODEL
    return await get_admin_config(db, key, fallback=fallback)
