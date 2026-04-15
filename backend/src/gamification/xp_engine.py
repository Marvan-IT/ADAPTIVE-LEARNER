"""XP calculation and award engine for the gamification system.

All XP values and penalties are read from AdminConfig at call time so
an admin can tune them without a deploy.  DEFAULTS provides fallback
values when no AdminConfig row exists for a key.

Entry points:
  compute_and_award_xp()  — called per correct card answer
  award_mastery_xp()      — called when a concept is mastered
  award_consolation_xp()  — called when a session ends without mastery

All functions flush (not commit) so the caller controls the transaction
boundary.
"""

import logging
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Student, XpEvent, AdminConfig

logger = logging.getLogger(__name__)

# Default config values — overridden by AdminConfig rows when present.
DEFAULTS = {
    "XP_PER_DIFFICULTY_POINT": "4",
    "XP_HINT_PENALTY": "0.25",
    "XP_WRONG_PENALTY": "0.15",
    "XP_FIRST_ATTEMPT_BONUS": "1.5",
    "XP_MASTERY": "50",
    "XP_MASTERY_BONUS": "25",
    "XP_MASTERY_BONUS_THRESHOLD": "90",
    "XP_CONSOLATION": "10",
    "GAMIFICATION_ENABLED": "true",
    "DIFFICULTY_WEIGHTED_XP_ENABLED": "true",
    "BADGES_ENABLED": "true",
}


async def _get_config(db: AsyncSession, key: str) -> str:
    """Read a single config value from AdminConfig, falling back to DEFAULTS."""
    result = await db.execute(
        select(AdminConfig.value).where(AdminConfig.key == key)
    )
    row = result.scalar_one_or_none()
    return row if row is not None else DEFAULTS.get(key, "")


async def _get_config_float(db: AsyncSession, key: str) -> float:
    return float(await _get_config(db, key))


async def _get_config_int(db: AsyncSession, key: str) -> int:
    return int(float(await _get_config(db, key)))


async def compute_and_award_xp(
    db: AsyncSession,
    student_id: UUID,
    session_id: UUID | None,
    interaction_id: UUID | None,
    difficulty: int,
    wrong_attempts: int,
    hints_used: int,
    is_correct: bool,
    time_on_card_sec: float = 0.0,
    answer_streak: int = 0,
) -> dict:
    """Calculate difficulty-weighted XP and award it atomically.

    Returns a dict with keys: base_xp, multiplier, final_xp, new_badges.

    When GAMIFICATION_ENABLED == 'false' a flat 10 XP is awarded instead
    of the difficulty-weighted formula.  When is_correct == False, 0 XP
    is returned without touching the DB.
    """
    # Master feature flag
    enabled = await _get_config(db, "GAMIFICATION_ENABLED")
    if enabled != "true":
        flat_xp = 10 if is_correct else 0
        if flat_xp > 0:
            event = XpEvent(
                student_id=student_id,
                session_id=session_id,
                interaction_id=interaction_id,
                event_type="card_correct",
                base_xp=flat_xp,
                multiplier=1.0,
                final_xp=flat_xp,
                metadata_={"gamification_disabled": True},
            )
            db.add(event)
            await db.execute(
                update(Student)
                .where(Student.id == student_id)
                .values(xp=Student.xp + flat_xp)
            )
            await db.flush()
        return {
            "base_xp": flat_xp,
            "multiplier": 1.0,
            "final_xp": flat_xp,
            "new_badges": [],
        }

    # No XP for wrong answers
    if not is_correct:
        return {"base_xp": 0, "multiplier": 1.0, "final_xp": 0, "new_badges": []}

    diff_enabled = await _get_config(db, "DIFFICULTY_WEIGHTED_XP_ENABLED")

    if diff_enabled == "true":
        xp_per_diff = await _get_config_float(db, "XP_PER_DIFFICULTY_POINT")
        hint_penalty = await _get_config_float(db, "XP_HINT_PENALTY")
        wrong_penalty = await _get_config_float(db, "XP_WRONG_PENALTY")
        first_bonus = await _get_config_float(db, "XP_FIRST_ATTEMPT_BONUS")

        base_xp = round(difficulty * xp_per_diff)
        # Each hint/wrong attempt reduces XP by a fixed fraction, floored at 0.25
        hint_factor = max(0.25, 1.0 - hint_penalty * hints_used)
        wrong_factor = max(0.25, 1.0 - wrong_penalty * wrong_attempts)
        first_attempt_bonus = (
            first_bonus if hints_used == 0 and wrong_attempts == 0 else 1.0
        )
    else:
        # Flat XP mode — use consolation value as the base
        base_xp = await _get_config_int(db, "XP_CONSOLATION")
        hint_factor = 1.0
        wrong_factor = 1.0
        first_attempt_bonus = 1.0

    # Update streak and get streak multiplier in the same transaction
    from gamification.streak_engine import update_daily_streak
    streak_result = await update_daily_streak(db, student_id)
    streak_mult = streak_result.get("multiplier", 1.0)

    total_multiplier = hint_factor * wrong_factor * first_attempt_bonus * streak_mult
    final_xp = max(1, round(base_xp * total_multiplier))

    event = XpEvent(
        student_id=student_id,
        session_id=session_id,
        interaction_id=interaction_id,
        event_type="card_correct",
        base_xp=base_xp,
        multiplier=round(total_multiplier, 4),
        final_xp=final_xp,
        metadata_={
            "difficulty": difficulty,
            "hints_used": hints_used,
            "wrong_attempts": wrong_attempts,
            "hint_factor": round(hint_factor, 4),
            "wrong_factor": round(wrong_factor, 4),
            "first_attempt_bonus": round(first_attempt_bonus, 4),
            "streak_multiplier": round(streak_mult, 4),
            "streak_day": streak_result.get("daily_streak", 0),
        },
    )
    db.add(event)

    # Atomically increment student XP
    await db.execute(
        update(Student)
        .where(Student.id == student_id)
        .values(xp=Student.xp + final_xp)
    )
    await db.flush()

    # Evaluate streak badges (streak was just updated)
    from gamification.badge_engine import evaluate_badges
    streak_badges = []
    if streak_result.get("streak_updated"):
        streak_badges = await evaluate_badges(
            db, student_id, "daily_streak", {}
        )

    # Evaluate per-card badges (first_correct, speed_demon, answer_streak)
    card_badges = await evaluate_badges(
        db, student_id, "card_correct",
        {
            "answer_streak": answer_streak,
            "time_on_card_sec": time_on_card_sec,
        },
    )
    if answer_streak > 0:
        streak_answer_badges = await evaluate_badges(
            db, student_id, "answer_streak", {"answer_streak": answer_streak}
        )
    else:
        streak_answer_badges = []

    new_badges = streak_badges + card_badges + streak_answer_badges

    logger.info(
        "[xp-awarded] student_id=%s base=%d mult=%.4f final=%d "
        "event=card_correct badges=%d streak=%d",
        student_id, base_xp, total_multiplier, final_xp,
        len(new_badges), streak_result.get("daily_streak", 0),
    )

    return {
        "base_xp": base_xp,
        "multiplier": round(total_multiplier, 4),
        "final_xp": final_xp,
        "new_badges": new_badges,
    }


async def award_mastery_xp(
    db: AsyncSession,
    student_id: UUID,
    session_id: UUID | None,
    score: int | None,
) -> dict:
    """Award XP for mastering a concept.

    Adds a bonus when the student's check score is >= XP_MASTERY_BONUS_THRESHOLD.
    Returns the same dict shape as compute_and_award_xp.
    """
    mastery_xp = await _get_config_int(db, "XP_MASTERY")
    bonus_threshold = await _get_config_int(db, "XP_MASTERY_BONUS_THRESHOLD")
    bonus_xp = await _get_config_int(db, "XP_MASTERY_BONUS")

    base_xp = mastery_xp
    event_type = "concept_mastery"

    if score is not None and score >= bonus_threshold:
        base_xp += bonus_xp
        event_type = "mastery_bonus"

    event = XpEvent(
        student_id=student_id,
        session_id=session_id,
        interaction_id=None,
        event_type=event_type,
        base_xp=base_xp,
        multiplier=1.0,
        final_xp=base_xp,
        metadata_={"score": score},
    )
    db.add(event)
    await db.execute(
        update(Student)
        .where(Student.id == student_id)
        .values(xp=Student.xp + base_xp)
    )
    await db.flush()

    from gamification.badge_engine import evaluate_badges
    new_badges = await evaluate_badges(db, student_id, "concept_mastery", {})

    logger.info(
        "[xp-mastery] student_id=%s xp=%d score=%s event=%s badges=%d",
        student_id, base_xp, score, event_type, len(new_badges),
    )
    return {
        "base_xp": base_xp,
        "multiplier": 1.0,
        "final_xp": base_xp,
        "new_badges": new_badges,
    }


async def award_consolation_xp(
    db: AsyncSession,
    student_id: UUID,
    session_id: UUID | None,
) -> dict:
    """Award consolation XP when a session completes without mastery.

    Encourages continued learning even when the student didn't reach mastery.
    Returns the same dict shape as compute_and_award_xp.
    """
    consolation = await _get_config_int(db, "XP_CONSOLATION")
    event = XpEvent(
        student_id=student_id,
        session_id=session_id,
        interaction_id=None,
        event_type="consolation",
        base_xp=consolation,
        multiplier=1.0,
        final_xp=consolation,
        metadata_={"consolation": True},
    )
    db.add(event)
    await db.execute(
        update(Student)
        .where(Student.id == student_id)
        .values(xp=Student.xp + consolation)
    )
    await db.flush()
    logger.info("[xp-consolation] student_id=%s xp=%d", student_id, consolation)
    return {
        "base_xp": consolation,
        "multiplier": 1.0,
        "final_xp": consolation,
        "new_badges": [],
    }
