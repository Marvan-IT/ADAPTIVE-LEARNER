"""Daily streak tracking and XP multiplier tiers.

Streak logic:
- If last_active_date is NULL or more than 1 day ago → reset streak to 1.
- If last_active_date is exactly yesterday → increment streak by 1.
- If last_active_date is today → no change (already active today).

Multiplier tiers are read from AdminConfig at call time so an admin can
tune them without a deploy.  All tiers default to values in STREAK_DEFAULTS
when no AdminConfig row exists.
"""

import logging
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Student, AdminConfig

logger = logging.getLogger(__name__)

STREAK_DEFAULTS = {
    "STREAK_TIER_1_DAYS": "3",
    "STREAK_TIER_1_MULT": "1.25",
    "STREAK_TIER_2_DAYS": "5",
    "STREAK_TIER_2_MULT": "1.5",
    "STREAK_TIER_3_DAYS": "7",
    "STREAK_TIER_3_MULT": "2.0",
    "STREAK_TIER_4_DAYS": "14",
    "STREAK_TIER_4_MULT": "2.5",
    "STREAK_MULTIPLIER_ENABLED": "true",
}


async def _get_streak_config(db: AsyncSession, key: str) -> str:
    result = await db.execute(
        select(AdminConfig.value).where(AdminConfig.key == key)
    )
    row = result.scalar_one_or_none()
    return row if row is not None else STREAK_DEFAULTS.get(key, "")


def _compute_multiplier(daily_streak: int, tiers: list[tuple[int, float]]) -> float:
    """Return the XP multiplier for the given streak day count.

    Iterates tiers from highest threshold to lowest so the first match wins.
    Returns 1.0 when the streak is below the lowest tier threshold.
    """
    multiplier = 1.0
    for min_days, mult in sorted(tiers, key=lambda t: t[0], reverse=True):
        if daily_streak >= min_days:
            multiplier = mult
            break
    return multiplier


async def update_daily_streak(db: AsyncSession, student_id: UUID) -> dict:
    """Update the student's daily streak and return current streak + multiplier.

    Must be called inside an active DB transaction; uses db.flush() rather
    than db.commit() so the caller controls the transaction boundary.

    Returns a dict with keys:
      daily_streak, daily_streak_best, multiplier, streak_updated
    """
    result = await db.execute(
        select(Student).where(Student.id == student_id)
    )
    student = result.scalar_one_or_none()
    if not student:
        return {
            "daily_streak": 0,
            "daily_streak_best": 0,
            "multiplier": 1.0,
            "streak_updated": False,
        }

    today = date.today()
    last_active = student.last_active_date
    current_streak = student.daily_streak or 0
    best_streak = student.daily_streak_best or 0

    streak_updated = False
    if last_active is None or last_active < today - timedelta(days=1):
        # First activity ever, or missed a day — reset to 1
        current_streak = 1
        streak_updated = True
    elif last_active == today - timedelta(days=1):
        # Consecutive day — extend streak
        current_streak += 1
        streak_updated = True
    # else: last_active == today — already counted today, no change

    if streak_updated:
        best_streak = max(best_streak, current_streak)
        await db.execute(
            update(Student).where(Student.id == student_id).values(
                daily_streak=current_streak,
                daily_streak_best=best_streak,
                last_active_date=today,
            )
        )
        await db.flush()
        logger.info(
            "[streak-update] student_id=%s streak=%d best=%d",
            student_id, current_streak, best_streak,
        )

    # Compute multiplier from AdminConfig tiers
    streak_enabled = await _get_streak_config(db, "STREAK_MULTIPLIER_ENABLED")
    if streak_enabled != "true":
        return {
            "daily_streak": current_streak,
            "daily_streak_best": best_streak,
            "multiplier": 1.0,
            "streak_updated": streak_updated,
        }

    tiers: list[tuple[int, float]] = []
    for i in range(1, 5):
        days = int(await _get_streak_config(db, f"STREAK_TIER_{i}_DAYS"))
        mult = float(await _get_streak_config(db, f"STREAK_TIER_{i}_MULT"))
        tiers.append((days, mult))

    multiplier = _compute_multiplier(current_streak, tiers)

    return {
        "daily_streak": current_streak,
        "daily_streak_best": best_streak,
        "multiplier": multiplier,
        "streak_updated": streak_updated,
    }
