"""Badge evaluation engine — checks and awards milestone badges.

evaluate_badges() is the single entry point.  It is called by the XP
engine after every XP-earning event so badge checks happen in the same
DB transaction as the XP award.

Design notes:
- Badge awards are idempotent: the unique constraint uq_student_badges_student_badge
  prevents duplicate rows.  This module skips already-earned badges in
  Python before touching the DB to avoid unnecessary round-trips.
- Each BadgeDefinition.check() is called inside a try/except so a
  buggy check function cannot break the XP flow.
- Context dict is built lazily per trigger type: only queries relevant
  to the active trigger are executed.
"""

import logging
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import StudentBadge, StudentMastery, CardInteraction, Student
from gamification.badge_definitions import BADGE_REGISTRY

logger = logging.getLogger(__name__)


async def _build_badge_context(
    db: AsyncSession,
    student_id: UUID,
    trigger: str,
    extra: dict,
) -> dict:
    """Build context dict with aggregated stats needed for badge evaluation.

    Only executes DB queries relevant to the given trigger to minimise
    round-trips.  The extra dict from the caller is merged in first so
    caller-supplied keys (e.g. answer_streak, time_on_card_sec) are
    available alongside the queried aggregates.
    """
    context = dict(extra)

    if trigger in ("card_correct", "answer_streak"):
        # Count interactions where the student never used a wrong attempt
        # (proxy for "first-attempt correct").
        result = await db.execute(
            select(func.count(CardInteraction.id))
            .where(CardInteraction.student_id == student_id)
            .where(CardInteraction.wrong_attempts == 0)
        )
        context["total_correct"] = result.scalar() or 0
        context["is_correct"] = True  # Caller only invokes this on correct events

    if trigger == "concept_mastery":
        result = await db.execute(
            select(func.count(StudentMastery.id))
            .where(StudentMastery.student_id == student_id)
        )
        context["mastered_count"] = result.scalar() or 0

    if trigger == "daily_streak":
        result = await db.execute(
            select(Student.daily_streak).where(Student.id == student_id)
        )
        context["daily_streak"] = result.scalar() or 0

    return context


async def evaluate_badges(
    db: AsyncSession,
    student_id: UUID,
    trigger: str,
    extra: dict,
) -> list[dict]:
    """Evaluate all badge definitions for the given trigger event.

    Returns a list of newly awarded badge dicts (badge_key, name_key).
    An empty list means no new badges were earned.

    Skips evaluation entirely when BADGES_ENABLED != 'true' in AdminConfig.
    """
    # Lazy import to avoid circular dependency: xp_engine imports badge_engine,
    # badge_engine imports xp_engine's _get_config helper.
    from gamification.xp_engine import _get_config
    badges_enabled = await _get_config(db, "BADGES_ENABLED")
    if badges_enabled == "false":
        return []

    # Fetch already-earned badge keys in a single query
    result = await db.execute(
        select(StudentBadge.badge_key).where(StudentBadge.student_id == student_id)
    )
    earned_keys: set[str] = set(result.scalars().all())

    # Build context once for all badge checks
    context = await _build_badge_context(db, student_id, trigger, extra)

    new_badges: list[dict] = []
    for badge_def in BADGE_REGISTRY:
        if badge_def.key in earned_keys:
            continue
        if badge_def.trigger != trigger:
            continue
        try:
            if badge_def.check(context):
                badge = StudentBadge(
                    student_id=student_id,
                    badge_key=badge_def.key,
                    metadata_={"trigger": trigger},
                )
                db.add(badge)
                new_badges.append({
                    "badge_key": badge_def.key,
                    "name_key": badge_def.name_i18n_key,
                })
                # Prevent double-award within the same batch (e.g. mastery_5 and mastery_10
                # both match when mastered_count == 10 for the first time)
                earned_keys.add(badge_def.key)
                logger.info(
                    "[badge-awarded] student_id=%s badge=%s trigger=%s",
                    student_id, badge_def.key, trigger,
                )
        except Exception as exc:
            logger.warning(
                "[badge-eval-error] badge=%s trigger=%s error=%s",
                badge_def.key, trigger, exc,
            )

    if new_badges:
        await db.flush()

    return new_badges


async def sync_student_badges(
    db: AsyncSession,
    student_id: UUID,
) -> list[dict]:
    """Evaluate ALL badge triggers for a student, awarding any missing badges.

    This is the general catch-up mechanism: it runs every trigger type so
    that badges are never missed regardless of when criteria were met.
    Called by the GET badges endpoint to ensure the student always sees
    an up-to-date badge list.

    Returns a combined list of all newly awarded badge dicts.
    """
    from gamification.xp_engine import _get_config
    badges_enabled = await _get_config(db, "BADGES_ENABLED")
    if badges_enabled == "false":
        return []

    # Fetch already-earned badge keys once — shared across all triggers
    result = await db.execute(
        select(StudentBadge.badge_key).where(StudentBadge.student_id == student_id)
    )
    earned_keys: set[str] = set(result.scalars().all())

    # Collect all unique triggers from the registry
    all_triggers = {bd.trigger for bd in BADGE_REGISTRY}

    # Build contexts for ALL triggers and evaluate every badge
    new_badges: list[dict] = []
    for trigger in all_triggers:
        context = await _build_badge_context(db, student_id, trigger, {})
        for badge_def in BADGE_REGISTRY:
            if badge_def.key in earned_keys:
                continue
            if badge_def.trigger != trigger:
                continue
            try:
                if badge_def.check(context):
                    badge = StudentBadge(
                        student_id=student_id,
                        badge_key=badge_def.key,
                        metadata_={"trigger": trigger, "source": "sync"},
                    )
                    db.add(badge)
                    new_badges.append({
                        "badge_key": badge_def.key,
                        "name_key": badge_def.name_i18n_key,
                    })
                    earned_keys.add(badge_def.key)
                    logger.info(
                        "[badge-sync] student_id=%s badge=%s trigger=%s",
                        student_id, badge_def.key, trigger,
                    )
            except Exception as exc:
                logger.warning(
                    "[badge-sync-error] badge=%s trigger=%s error=%s",
                    badge_def.key, trigger, exc,
                )

    if new_badges:
        await db.flush()

    return new_badges
