"""Badge definition registry for the gamification system.

Each BadgeDefinition is a pure, immutable record describing when a badge
is earned.  The check callable receives a context dict populated by
badge_engine._build_badge_context() and returns True when the criteria
are met.  All callables must be side-effect-free.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class BadgeDefinition:
    key: str
    name_i18n_key: str
    trigger: str  # 'card_correct' | 'concept_mastery' | 'daily_streak' | 'answer_streak' | 'chunk_complete'
    check: Callable[[dict], bool]  # Takes context dict, returns True if badge should be awarded
    description_i18n_key: str = ""


def _check_first_correct(ctx: dict) -> bool:
    return ctx.get("total_correct", 0) == 1


def _check_first_mastery(ctx: dict) -> bool:
    return ctx.get("mastered_count", 0) == 1


def _check_mastery_n(n: int):
    def check(ctx: dict) -> bool:
        return ctx.get("mastered_count", 0) >= n
    return check


def _check_streak_n(n: int):
    def check(ctx: dict) -> bool:
        return ctx.get("daily_streak", 0) >= n
    return check


def _check_answer_streak_n(n: int):
    def check(ctx: dict) -> bool:
        return ctx.get("answer_streak", 0) >= n
    return check


def _check_perfect_chunk(ctx: dict) -> bool:
    return ctx.get("chunk_perfect", False)


def _check_speed_demon(ctx: dict) -> bool:
    return ctx.get("time_on_card_sec", 999) < 5.0 and ctx.get("is_correct", False)


BADGE_REGISTRY: list[BadgeDefinition] = [
    BadgeDefinition("first_correct", "badge.firstCorrect", "card_correct", _check_first_correct),
    BadgeDefinition("first_mastery", "badge.firstMastery", "concept_mastery", _check_first_mastery),
    BadgeDefinition("mastery_5", "badge.knowledgeSeeker", "concept_mastery", _check_mastery_n(5)),
    BadgeDefinition("mastery_10", "badge.scholar", "concept_mastery", _check_mastery_n(10)),
    BadgeDefinition("mastery_25", "badge.expert", "concept_mastery", _check_mastery_n(25)),
    BadgeDefinition("streak_3", "badge.onARoll", "daily_streak", _check_streak_n(3)),
    BadgeDefinition("streak_7", "badge.weekWarrior", "daily_streak", _check_streak_n(7)),
    BadgeDefinition("streak_14", "badge.fortnightForce", "daily_streak", _check_streak_n(14)),
    BadgeDefinition("streak_30", "badge.monthlyMaster", "daily_streak", _check_streak_n(30)),
    BadgeDefinition("correct_10", "badge.tenInARow", "answer_streak", _check_answer_streak_n(10)),
    BadgeDefinition("correct_25", "badge.unstoppable", "answer_streak", _check_answer_streak_n(25)),
    BadgeDefinition("perfect_chunk", "badge.flawless", "chunk_complete", _check_perfect_chunk),
    BadgeDefinition("speed_demon", "badge.speedDemon", "card_correct", _check_speed_demon),
]
