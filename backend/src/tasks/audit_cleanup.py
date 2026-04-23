"""Background retention task for admin_audit_logs.

Deletes audit rows beyond the 50 most recent per admin_id to prevent
unbounded table growth.

Usage — wire into main.py lifespan:

    from tasks.audit_cleanup import run_cleanup

    async def _run_nightly_audit_cleanup():
        while True:
            await asyncio.sleep(86400)   # 24 hours
            try:
                await run_cleanup()
            except Exception:
                logger.exception("[audit_cleanup] Nightly purge failed")

    asyncio.create_task(_run_nightly_audit_cleanup())

If no lifespan exists in main.py, this task can be scheduled externally
(e.g. via cron: ``python -c "import asyncio; from tasks.audit_cleanup import run_cleanup; asyncio.run(run_cleanup())"``).
"""
from __future__ import annotations

import logging

from db.connection import async_session_factory
from api.audit_service import purge_old_audits_per_admin

logger = logging.getLogger(__name__)

KEEP_PER_ADMIN = 50


async def run_cleanup(keep_per_admin: int = KEEP_PER_ADMIN) -> int:
    """Run the audit log retention purge as a standalone async task.

    Opens its own DB session (does not accept one as a parameter) so it can
    be called from a long-running background task without sharing a session
    with request handlers.

    Returns the number of rows deleted.
    """
    async with async_session_factory() as db:
        deleted = await purge_old_audits_per_admin(db, keep_per_admin=keep_per_admin)
        await db.commit()
        return deleted
