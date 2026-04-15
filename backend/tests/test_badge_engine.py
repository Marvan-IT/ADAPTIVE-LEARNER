"""
test_badge_engine.py

Unit tests for the gamification badge engine.

Business criteria covered
--------------------------
BC-1   first_correct badge awarded when total_correct == 1
         (trigger=card_correct, DB aggregate returns 1 correct interaction)
BC-2   first_mastery badge awarded when mastered_count == 1
         (trigger=concept_mastery, DB aggregate returns 1 mastery row)
BC-3   mastery_5 badge awarded when mastered_count >= 5
BC-4   mastery_10 badge awarded when mastered_count >= 10
BC-5   mastery_25 badge awarded when mastered_count >= 25
BC-6   streak_3 badge awarded when daily_streak >= 3
         (trigger=daily_streak, DB returns student.daily_streak=3)
BC-7   streak_7 badge awarded when daily_streak >= 7
BC-8   streak_14 and streak_30 awarded at matching thresholds
BC-9   correct_10 badge awarded when answer_streak >= 10
         (trigger=answer_streak, context carries answer_streak)
BC-10  correct_25 badge awarded when answer_streak >= 25
BC-11  perfect_chunk badge awarded when chunk_perfect=True, accuracy=1.0, hints_used=0
         (trigger=chunk_complete)
BC-12  speed_demon badge awarded when time_on_card_sec < 5 and trigger=card_correct
BC-13  Badge deduplication — already-earned badge NOT re-awarded in same or later call
BC-14  Wrong trigger type does not award badges for unrelated triggers
BC-15  BADGES_ENABLED=false → evaluate_badges returns [] regardless of context

Run: pytest backend/tests/test_badge_engine.py -v
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ---------------------------------------------------------------------------
# DB mock factory
# ---------------------------------------------------------------------------

def _make_mock_db(
    existing_badges: list[str] | None = None,
    badges_enabled: str = "true",
    total_correct: int = 0,
    mastered_count: int = 0,
    daily_streak: int = 0,
) -> AsyncMock:
    """Build an AsyncSession mock for badge engine tests.

    Parameters
    ----------
    existing_badges:
        badge_keys already stored in student_badges — the engine must skip these.
    badges_enabled:
        Value for the BADGES_ENABLED AdminConfig key.
    total_correct:
        Return value for COUNT(CardInteraction.id) where wrong_attempts==0.
    mastered_count:
        Return value for COUNT(StudentMastery.id).
    daily_streak:
        Value returned by Student.daily_streak scalar select.
    """
    existing_badges = existing_badges or []

    db = AsyncMock()

    async def _execute_side_effect(stmt, *args, **kwargs):
        stmt_str = str(stmt)

        # For AdminConfig lookups the key value is a bind parameter (:key_1)
        # in the default compiled form, so we compile with literal_binds to
        # embed the actual string value before pattern-matching.
        try:
            stmt_literal = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        except Exception:
            stmt_literal = stmt_str

        # ------------------------------------------------------------
        # AdminConfig lookup for BADGES_ENABLED (via _get_config)
        # ------------------------------------------------------------
        if "admin_config" in stmt_str.lower() or "adminconfig" in stmt_str:
            r = MagicMock()
            if "BADGES_ENABLED" in stmt_literal:
                r.scalar_one_or_none = MagicMock(return_value=badges_enabled)
            else:
                r.scalar_one_or_none = MagicMock(return_value=None)
            return r

        # ------------------------------------------------------------
        # SELECT student_badges.badge_key WHERE student_id = ?
        # Returns the list of already-earned keys.
        # ------------------------------------------------------------
        if "student_badges" in stmt_str.lower():
            r = MagicMock()
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=existing_badges)))
            return r

        # ------------------------------------------------------------
        # COUNT(CardInteraction.id) — card_correct / answer_streak triggers
        # ------------------------------------------------------------
        if "card_interaction" in stmt_str.lower() or "cardinteraction" in stmt_str:
            r = MagicMock()
            r.scalar = MagicMock(return_value=total_correct)
            return r

        # ------------------------------------------------------------
        # COUNT(StudentMastery.id) — concept_mastery trigger
        # ------------------------------------------------------------
        if "student_mastery" in stmt_str.lower() or "studentmastery" in stmt_str:
            r = MagicMock()
            r.scalar = MagicMock(return_value=mastered_count)
            return r

        # ------------------------------------------------------------
        # Student.daily_streak scalar — daily_streak trigger
        # ------------------------------------------------------------
        if "students" in stmt_str.lower():
            r = MagicMock()
            r.scalar = MagicMock(return_value=daily_streak)
            return r

        # Fallback — shouldn't be hit in normal badge tests
        r = MagicMock()
        r.scalar = MagicMock(return_value=None)
        r.scalar_one_or_none = MagicMock(return_value=None)
        r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        return r

    db.execute = AsyncMock(side_effect=_execute_side_effect)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Helper: extract badge keys from the returned list
# ---------------------------------------------------------------------------

def _keys(badges: list[dict]) -> set[str]:
    return {b["badge_key"] for b in badges}


# ---------------------------------------------------------------------------
# BC-1: first_correct
# ---------------------------------------------------------------------------

class TestFirstCorrectBadge:
    """BC-1: first_correct awarded on the very first correct card answer."""

    @pytest.mark.asyncio
    async def test_bc1_first_correct_awarded_when_total_correct_is_1(self):
        """BC-1: total_correct=1 on card_correct trigger → first_correct badge."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=1)
        result = await evaluate_badges(db, uuid.uuid4(), "card_correct", {})
        assert "first_correct" in _keys(result)

    @pytest.mark.asyncio
    async def test_bc1_no_badge_when_total_correct_is_zero(self):
        """BC-1: total_correct=0 (first answer wrong) → no first_correct."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=0)
        result = await evaluate_badges(db, uuid.uuid4(), "card_correct", {})
        assert "first_correct" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc1_no_badge_when_total_correct_is_2(self):
        """BC-1: total_correct=2 (not the first) → first_correct NOT re-awarded."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=2)
        result = await evaluate_badges(db, uuid.uuid4(), "card_correct", {})
        assert "first_correct" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc1_badge_carries_correct_name_key(self):
        """BC-1: Returned badge dict includes the i18n name key."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=1)
        result = await evaluate_badges(db, uuid.uuid4(), "card_correct", {})
        badge = next(b for b in result if b["badge_key"] == "first_correct")
        assert badge["name_key"] == "badge.firstCorrect"

    @pytest.mark.asyncio
    async def test_bc1_db_add_called_for_new_badge(self):
        """BC-1: db.add() is called exactly once for the new badge row."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=1)
        await evaluate_badges(db, uuid.uuid4(), "card_correct", {})
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_bc1_db_flush_called_after_award(self):
        """BC-1: db.flush() is awaited after awarding new badges."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=1)
        await evaluate_badges(db, uuid.uuid4(), "card_correct", {})
        db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# BC-2: first_mastery
# ---------------------------------------------------------------------------

class TestFirstMasteryBadge:
    """BC-2: first_mastery awarded on the first concept mastered."""

    @pytest.mark.asyncio
    async def test_bc2_first_mastery_awarded_when_mastered_count_is_1(self):
        """BC-2: mastered_count=1 on concept_mastery trigger → first_mastery."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(mastered_count=1)
        result = await evaluate_badges(db, uuid.uuid4(), "concept_mastery", {})
        assert "first_mastery" in _keys(result)

    @pytest.mark.asyncio
    async def test_bc2_no_badge_when_mastered_count_is_zero(self):
        """BC-2: mastered_count=0 → no first_mastery."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(mastered_count=0)
        result = await evaluate_badges(db, uuid.uuid4(), "concept_mastery", {})
        assert "first_mastery" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc2_badge_name_key_correct(self):
        """BC-2: name_key resolves to the badge.firstMastery i18n key."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(mastered_count=1)
        result = await evaluate_badges(db, uuid.uuid4(), "concept_mastery", {})
        badge = next(b for b in result if b["badge_key"] == "first_mastery")
        assert badge["name_key"] == "badge.firstMastery"


# ---------------------------------------------------------------------------
# BC-3 / BC-4 / BC-5: mastery milestones
# ---------------------------------------------------------------------------

class TestMasteryMilestoneBadges:
    """BC-3–BC-5: mastery_5, mastery_10, mastery_25 at respective thresholds."""

    @pytest.mark.asyncio
    async def test_bc3_mastery_5_awarded_at_exactly_5(self):
        """BC-3: mastered_count=5 → mastery_5 badge."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(mastered_count=5)
        result = await evaluate_badges(db, uuid.uuid4(), "concept_mastery", {})
        assert "mastery_5" in _keys(result)

    @pytest.mark.asyncio
    async def test_bc3_mastery_5_awarded_above_threshold(self):
        """BC-3: mastered_count=7 still earns mastery_5."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(mastered_count=7)
        result = await evaluate_badges(db, uuid.uuid4(), "concept_mastery", {})
        assert "mastery_5" in _keys(result)

    @pytest.mark.asyncio
    async def test_bc3_mastery_5_not_awarded_below_threshold(self):
        """BC-3: mastered_count=4 → no mastery_5."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(mastered_count=4)
        result = await evaluate_badges(db, uuid.uuid4(), "concept_mastery", {})
        assert "mastery_5" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc4_mastery_10_awarded_at_exactly_10(self):
        """BC-4: mastered_count=10 → mastery_10 badge."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(mastered_count=10)
        result = await evaluate_badges(db, uuid.uuid4(), "concept_mastery", {})
        assert "mastery_10" in _keys(result)

    @pytest.mark.asyncio
    async def test_bc4_mastery_10_not_awarded_at_9(self):
        """BC-4: mastered_count=9 → no mastery_10."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(mastered_count=9)
        result = await evaluate_badges(db, uuid.uuid4(), "concept_mastery", {})
        assert "mastery_10" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc5_mastery_25_awarded_at_exactly_25(self):
        """BC-5: mastered_count=25 → mastery_25 badge."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(mastered_count=25)
        result = await evaluate_badges(db, uuid.uuid4(), "concept_mastery", {})
        assert "mastery_25" in _keys(result)

    @pytest.mark.asyncio
    async def test_bc5_mastery_25_not_awarded_at_24(self):
        """BC-5: mastered_count=24 → no mastery_25."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(mastered_count=24)
        result = await evaluate_badges(db, uuid.uuid4(), "concept_mastery", {})
        assert "mastery_25" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc4_bc5_multiple_badges_awarded_at_count_25(self):
        """BC-4+BC-5: mastered_count=25 awards both mastery_10 and mastery_25."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(mastered_count=25)
        result = await evaluate_badges(db, uuid.uuid4(), "concept_mastery", {})
        keys = _keys(result)
        assert "mastery_10" in keys
        assert "mastery_25" in keys


# ---------------------------------------------------------------------------
# BC-6 / BC-7 / BC-8: daily streak badges
# ---------------------------------------------------------------------------

class TestDailyStreakBadges:
    """BC-6–BC-8: streak_3, streak_7, streak_14, streak_30 badges."""

    @pytest.mark.asyncio
    async def test_bc6_streak_3_awarded_at_exactly_3(self):
        """BC-6: daily_streak=3 → streak_3 badge."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(daily_streak=3)
        result = await evaluate_badges(db, uuid.uuid4(), "daily_streak", {})
        assert "streak_3" in _keys(result)

    @pytest.mark.asyncio
    async def test_bc6_streak_3_not_awarded_at_2(self):
        """BC-6: daily_streak=2 → no streak_3."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(daily_streak=2)
        result = await evaluate_badges(db, uuid.uuid4(), "daily_streak", {})
        assert "streak_3" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc7_streak_7_awarded_at_exactly_7(self):
        """BC-7: daily_streak=7 → streak_7 badge."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(daily_streak=7)
        result = await evaluate_badges(db, uuid.uuid4(), "daily_streak", {})
        assert "streak_7" in _keys(result)

    @pytest.mark.asyncio
    async def test_bc7_streak_7_not_awarded_at_6(self):
        """BC-7: daily_streak=6 → no streak_7."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(daily_streak=6)
        result = await evaluate_badges(db, uuid.uuid4(), "daily_streak", {})
        assert "streak_7" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc8_streak_14_awarded_at_exactly_14(self):
        """BC-8: daily_streak=14 → streak_14 badge."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(daily_streak=14)
        result = await evaluate_badges(db, uuid.uuid4(), "daily_streak", {})
        assert "streak_14" in _keys(result)

    @pytest.mark.asyncio
    async def test_bc8_streak_30_awarded_at_exactly_30(self):
        """BC-8: daily_streak=30 → streak_30 badge."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(daily_streak=30)
        result = await evaluate_badges(db, uuid.uuid4(), "daily_streak", {})
        assert "streak_30" in _keys(result)

    @pytest.mark.asyncio
    async def test_bc8_streak_30_not_awarded_at_29(self):
        """BC-8: daily_streak=29 → no streak_30."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(daily_streak=29)
        result = await evaluate_badges(db, uuid.uuid4(), "daily_streak", {})
        assert "streak_30" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc6_bc8_multiple_streak_badges_at_30(self):
        """BC-6+BC-7+BC-8: daily_streak=30 awards streak_3, streak_7, streak_14, streak_30."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(daily_streak=30)
        result = await evaluate_badges(db, uuid.uuid4(), "daily_streak", {})
        keys = _keys(result)
        assert {"streak_3", "streak_7", "streak_14", "streak_30"}.issubset(keys)


# ---------------------------------------------------------------------------
# BC-9 / BC-10: consecutive correct answer streaks
# ---------------------------------------------------------------------------

class TestAnswerStreakBadges:
    """BC-9–BC-10: correct_10 and correct_25 badges via answer_streak trigger."""

    @pytest.mark.asyncio
    async def test_bc9_correct_10_awarded_at_exactly_10(self):
        """BC-9: answer_streak=10 in extra dict → correct_10 badge."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=10)
        result = await evaluate_badges(db, uuid.uuid4(), "answer_streak", {"answer_streak": 10})
        assert "correct_10" in _keys(result)

    @pytest.mark.asyncio
    async def test_bc9_correct_10_not_awarded_at_9(self):
        """BC-9: answer_streak=9 → no correct_10."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=9)
        result = await evaluate_badges(db, uuid.uuid4(), "answer_streak", {"answer_streak": 9})
        assert "correct_10" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc10_correct_25_awarded_at_exactly_25(self):
        """BC-10: answer_streak=25 → correct_25 badge."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=25)
        result = await evaluate_badges(db, uuid.uuid4(), "answer_streak", {"answer_streak": 25})
        assert "correct_25" in _keys(result)

    @pytest.mark.asyncio
    async def test_bc10_correct_25_not_awarded_at_24(self):
        """BC-10: answer_streak=24 → no correct_25."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=24)
        result = await evaluate_badges(db, uuid.uuid4(), "answer_streak", {"answer_streak": 24})
        assert "correct_25" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc9_bc10_both_awarded_at_25(self):
        """BC-9+BC-10: answer_streak=25 awards both correct_10 and correct_25."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=25)
        result = await evaluate_badges(db, uuid.uuid4(), "answer_streak", {"answer_streak": 25})
        keys = _keys(result)
        assert "correct_10" in keys
        assert "correct_25" in keys

    @pytest.mark.asyncio
    async def test_bc9_correct_10_name_key(self):
        """BC-9: correct_10 badge returns the expected i18n name key."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=10)
        result = await evaluate_badges(db, uuid.uuid4(), "answer_streak", {"answer_streak": 10})
        badge = next(b for b in result if b["badge_key"] == "correct_10")
        assert badge["name_key"] == "badge.tenInARow"


# ---------------------------------------------------------------------------
# BC-11: perfect_chunk
# ---------------------------------------------------------------------------

class TestPerfectChunkBadge:
    """BC-11: perfect_chunk badge when chunk completed with 100% accuracy and no hints."""

    @pytest.mark.asyncio
    async def test_bc11_perfect_chunk_awarded_when_chunk_perfect_true(self):
        """BC-11: chunk_perfect=True in context → perfect_chunk badge."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db()
        result = await evaluate_badges(
            db, uuid.uuid4(), "chunk_complete",
            {"chunk_perfect": True, "accuracy": 1.0, "hints_used": 0},
        )
        assert "perfect_chunk" in _keys(result)

    @pytest.mark.asyncio
    async def test_bc11_no_badge_when_chunk_perfect_false(self):
        """BC-11: chunk_perfect=False → no perfect_chunk."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db()
        result = await evaluate_badges(
            db, uuid.uuid4(), "chunk_complete",
            {"chunk_perfect": False, "accuracy": 0.8, "hints_used": 1},
        )
        assert "perfect_chunk" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc11_no_badge_when_chunk_perfect_missing(self):
        """BC-11: chunk_perfect key absent from context → no badge (defaults False)."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db()
        result = await evaluate_badges(db, uuid.uuid4(), "chunk_complete", {})
        assert "perfect_chunk" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc11_badge_name_key(self):
        """BC-11: perfect_chunk badge returns badge.flawless i18n key."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db()
        result = await evaluate_badges(
            db, uuid.uuid4(), "chunk_complete", {"chunk_perfect": True},
        )
        badge = next(b for b in result if b["badge_key"] == "perfect_chunk")
        assert badge["name_key"] == "badge.flawless"


# ---------------------------------------------------------------------------
# BC-12: speed_demon
# ---------------------------------------------------------------------------

class TestSpeedDemonBadge:
    """BC-12: speed_demon badge for correct answers completed in under 5 seconds."""

    @pytest.mark.asyncio
    async def test_bc12_speed_demon_awarded_when_time_lt_5(self):
        """BC-12: time_on_card_sec=2.3 on card_correct → speed_demon badge."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=5)
        result = await evaluate_badges(
            db, uuid.uuid4(), "card_correct", {"time_on_card_sec": 2.3},
        )
        assert "speed_demon" in _keys(result)

    @pytest.mark.asyncio
    async def test_bc12_speed_demon_not_awarded_when_time_eq_5(self):
        """BC-12: time_on_card_sec=5.0 (boundary, not strictly <5) → no speed_demon."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=5)
        result = await evaluate_badges(
            db, uuid.uuid4(), "card_correct", {"time_on_card_sec": 5.0},
        )
        assert "speed_demon" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc12_speed_demon_not_awarded_when_time_gt_5(self):
        """BC-12: time_on_card_sec=6.0 → no speed_demon."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=5)
        result = await evaluate_badges(
            db, uuid.uuid4(), "card_correct", {"time_on_card_sec": 6.0},
        )
        assert "speed_demon" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc12_speed_demon_not_awarded_when_time_missing(self):
        """BC-12: time_on_card_sec absent → defaults to 999 → no speed_demon."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=5)
        result = await evaluate_badges(db, uuid.uuid4(), "card_correct", {})
        assert "speed_demon" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc12_speed_demon_name_key(self):
        """BC-12: speed_demon badge returns badge.speedDemon i18n key."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=5)
        result = await evaluate_badges(
            db, uuid.uuid4(), "card_correct", {"time_on_card_sec": 1.0},
        )
        badge = next(b for b in result if b["badge_key"] == "speed_demon")
        assert badge["name_key"] == "badge.speedDemon"


# ---------------------------------------------------------------------------
# BC-13: Badge deduplication
# ---------------------------------------------------------------------------

class TestBadgeDeduplication:
    """BC-13: Already-earned badges must not be awarded again."""

    @pytest.mark.asyncio
    async def test_bc13_already_earned_badge_not_in_result(self):
        """BC-13: first_correct already in student_badges → not in returned list."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(existing_badges=["first_correct"], total_correct=1)
        result = await evaluate_badges(db, uuid.uuid4(), "card_correct", {})
        assert "first_correct" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc13_db_add_not_called_for_duplicate(self):
        """BC-13: db.add() is never called when badge already earned."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(
            existing_badges=["first_correct", "speed_demon"],
            total_correct=1,
        )
        await evaluate_badges(
            db, uuid.uuid4(), "card_correct", {"time_on_card_sec": 1.0},
        )
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_bc13_new_badge_still_awarded_alongside_existing(self):
        """BC-13: speed_demon already earned but first_correct new → first_correct awarded."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(existing_badges=["speed_demon"], total_correct=1)
        result = await evaluate_badges(
            db, uuid.uuid4(), "card_correct", {"time_on_card_sec": 1.0},
        )
        keys = _keys(result)
        assert "first_correct" in keys
        assert "speed_demon" not in keys

    @pytest.mark.asyncio
    async def test_bc13_flush_not_called_when_no_new_badges(self):
        """BC-13: When all eligible badges are already earned, db.flush() not called."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(existing_badges=["first_correct"], total_correct=1)
        await evaluate_badges(db, uuid.uuid4(), "card_correct", {})
        db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bc13_same_call_awards_mastery_badges_without_duplicates(self):
        """BC-13: mastery_5 already earned; mastered_count=10 → only mastery_10 awarded."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(
            existing_badges=["first_mastery", "mastery_5"],
            mastered_count=10,
        )
        result = await evaluate_badges(db, uuid.uuid4(), "concept_mastery", {})
        keys = _keys(result)
        assert "mastery_10" in keys
        assert "mastery_5" not in keys
        assert "first_mastery" not in keys


# ---------------------------------------------------------------------------
# BC-14: Wrong trigger type
# ---------------------------------------------------------------------------

class TestWrongTriggerType:
    """BC-14: Badges should only fire on their matching trigger."""

    @pytest.mark.asyncio
    async def test_bc14_concept_mastery_trigger_does_not_award_card_badges(self):
        """BC-14: concept_mastery trigger → card_correct badges (first_correct, speed_demon) not awarded."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(mastered_count=1, total_correct=1)
        result = await evaluate_badges(db, uuid.uuid4(), "concept_mastery", {})
        keys = _keys(result)
        assert "first_correct" not in keys
        assert "speed_demon" not in keys

    @pytest.mark.asyncio
    async def test_bc14_card_correct_trigger_does_not_award_mastery_badges(self):
        """BC-14: card_correct trigger → mastery badges not evaluated."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(total_correct=1, mastered_count=5)
        result = await evaluate_badges(db, uuid.uuid4(), "card_correct", {})
        keys = _keys(result)
        assert "mastery_5" not in keys
        assert "first_mastery" not in keys

    @pytest.mark.asyncio
    async def test_bc14_daily_streak_trigger_does_not_award_chunk_badges(self):
        """BC-14: daily_streak trigger → chunk_complete badges not evaluated."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(daily_streak=7)
        result = await evaluate_badges(
            db, uuid.uuid4(), "daily_streak",
            {"chunk_perfect": True},
        )
        assert "perfect_chunk" not in _keys(result)

    @pytest.mark.asyncio
    async def test_bc14_chunk_complete_trigger_does_not_award_streak_badges(self):
        """BC-14: chunk_complete trigger → daily_streak badges not evaluated."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db()
        result = await evaluate_badges(
            db, uuid.uuid4(), "chunk_complete",
            {"chunk_perfect": True, "daily_streak": 30},
        )
        keys = _keys(result)
        assert "streak_3" not in keys
        assert "streak_30" not in keys

    @pytest.mark.asyncio
    async def test_bc14_unknown_trigger_returns_empty_list(self):
        """BC-14: An unrecognised trigger type produces no badge awards."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db()
        result = await evaluate_badges(db, uuid.uuid4(), "unknown_event", {})
        assert result == []


# ---------------------------------------------------------------------------
# BC-15: BADGES_ENABLED=false
# ---------------------------------------------------------------------------

class TestBadgesDisabled:
    """BC-15: BADGES_ENABLED=false in AdminConfig → evaluate_badges always returns []."""

    @pytest.mark.asyncio
    async def test_bc15_badges_disabled_returns_empty_list(self):
        """BC-15: BADGES_ENABLED=false → empty list regardless of trigger context."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(badges_enabled="false", total_correct=1)
        result = await evaluate_badges(db, uuid.uuid4(), "card_correct", {})
        assert result == []

    @pytest.mark.asyncio
    async def test_bc15_no_db_add_when_disabled(self):
        """BC-15: db.add() never called when badges disabled."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(badges_enabled="false", mastered_count=25)
        await evaluate_badges(db, uuid.uuid4(), "concept_mastery", {})
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_bc15_no_flush_when_disabled(self):
        """BC-15: db.flush() never awaited when badges disabled."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(badges_enabled="false", daily_streak=30)
        await evaluate_badges(db, uuid.uuid4(), "daily_streak", {})
        db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bc15_badges_enabled_true_still_evaluates(self):
        """BC-15: BADGES_ENABLED=true (default) → evaluation proceeds normally."""
        from gamification.badge_engine import evaluate_badges
        db = _make_mock_db(badges_enabled="true", total_correct=1)
        result = await evaluate_badges(db, uuid.uuid4(), "card_correct", {})
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Extra: badge definitions registry sanity checks (pure, no DB)
# ---------------------------------------------------------------------------

class TestBadgeDefinitionsRegistry:
    """Sanity checks on BADGE_REGISTRY — no DB required."""

    def test_registry_contains_13_definitions(self):
        """All 13 expected badge definitions are present in BADGE_REGISTRY."""
        from gamification.badge_definitions import BADGE_REGISTRY
        assert len(BADGE_REGISTRY) == 13

    def test_all_badge_keys_unique(self):
        """No two badge definitions share the same key."""
        from gamification.badge_definitions import BADGE_REGISTRY
        keys = [b.key for b in BADGE_REGISTRY]
        assert len(keys) == len(set(keys))

    def test_expected_keys_present(self):
        """Each of the 13 documented badge keys exists in the registry."""
        from gamification.badge_definitions import BADGE_REGISTRY
        expected = {
            "first_correct", "first_mastery",
            "mastery_5", "mastery_10", "mastery_25",
            "streak_3", "streak_7", "streak_14", "streak_30",
            "correct_10", "correct_25",
            "perfect_chunk", "speed_demon",
        }
        assert expected == {b.key for b in BADGE_REGISTRY}

    def test_all_check_functions_are_callable(self):
        """Every BadgeDefinition.check field is a callable."""
        from gamification.badge_definitions import BADGE_REGISTRY
        for badge in BADGE_REGISTRY:
            assert callable(badge.check), f"{badge.key}.check is not callable"

    def test_speed_demon_check_boundary_at_5_seconds(self):
        """speed_demon check: <5 returns True, ==5 returns False (strict boundary)."""
        from gamification.badge_definitions import BADGE_REGISTRY
        badge = next(b for b in BADGE_REGISTRY if b.key == "speed_demon")
        assert badge.check({"time_on_card_sec": 4.99, "is_correct": True}) is True
        assert badge.check({"time_on_card_sec": 5.0, "is_correct": True}) is False

    def test_first_correct_check_only_at_exactly_1(self):
        """first_correct check: True only at total_correct==1, not 0 or 2."""
        from gamification.badge_definitions import BADGE_REGISTRY
        badge = next(b for b in BADGE_REGISTRY if b.key == "first_correct")
        assert badge.check({"total_correct": 0}) is False
        assert badge.check({"total_correct": 1}) is True
        assert badge.check({"total_correct": 2}) is False

    def test_mastery_checks_use_gte_not_eq(self):
        """mastery_5 check uses >= so it fires at 5, 6, 7 ... not just exactly 5."""
        from gamification.badge_definitions import BADGE_REGISTRY
        badge = next(b for b in BADGE_REGISTRY if b.key == "mastery_5")
        assert badge.check({"mastered_count": 5}) is True
        assert badge.check({"mastered_count": 100}) is True
        assert badge.check({"mastered_count": 4}) is False
