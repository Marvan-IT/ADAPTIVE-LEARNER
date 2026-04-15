"""
test_streak_engine.py

Unit tests for the gamification streak engine.

Business criteria covered
--------------------------
BC-1  _compute_multiplier streak=1 → 1.0 (below first tier)
BC-2  _compute_multiplier streak=3 → 1.25
BC-3  _compute_multiplier streak=5 → 1.5
BC-4  _compute_multiplier streak=7 → 2.0
BC-5  _compute_multiplier streak=14 → 2.5
BC-6  First activity (last_active_date=None) → streak=1, multiplier=1.0
BC-7  Consecutive day activity → streak increments, best updated
BC-8  Missed day → streak resets to 1
BC-9  Same day activity → no DB write, streak unchanged
BC-10 STREAK_MULTIPLIER_ENABLED=false → multiplier always 1.0

Run: pytest backend/tests/test_streak_engine.py -v
"""
from __future__ import annotations

import sys
import uuid
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ---------------------------------------------------------------------------
# DB mock factory
# ---------------------------------------------------------------------------

def _make_mock_db(
    student_streak: int = 0,
    student_best: int = 0,
    last_active: date | None = None,
    streak_enabled: str = "true",
    tier_overrides: dict | None = None,
) -> AsyncMock:
    """Build an AsyncSession mock for streak engine tests."""

    tier_defaults = {
        "STREAK_TIER_1_DAYS": "3",
        "STREAK_TIER_1_MULT": "1.25",
        "STREAK_TIER_2_DAYS": "5",
        "STREAK_TIER_2_MULT": "1.5",
        "STREAK_TIER_3_DAYS": "7",
        "STREAK_TIER_3_MULT": "2.0",
        "STREAK_TIER_4_DAYS": "14",
        "STREAK_TIER_4_MULT": "2.5",
        "STREAK_MULTIPLIER_ENABLED": streak_enabled,
    }
    if tier_overrides:
        tier_defaults.update(tier_overrides)

    student = MagicMock()
    student.id = uuid.uuid4()
    student.daily_streak = student_streak
    student.daily_streak_best = student_best
    student.last_active_date = last_active

    db = AsyncMock()

    async def _execute_side_effect(stmt, *args, **kwargs):
        stmt_str = str(stmt)
        if "admin_config" in stmt_str.lower() or "adminconfig" in stmt_str:
            requested_key = None
            try:
                clause = stmt.whereclause
                if hasattr(clause, "right") and hasattr(clause.right, "value"):
                    requested_key = clause.right.value
            except Exception:
                pass
            if requested_key and requested_key in tier_defaults:
                r = MagicMock()
                r.scalar_one_or_none = MagicMock(return_value=tier_defaults[requested_key])
                return r
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=None)
            return r
        if "students" in stmt_str.lower():
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=student)
            return r
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=None)
        return r

    db.execute = AsyncMock(side_effect=_execute_side_effect)
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


# ---------------------------------------------------------------------------
# _compute_multiplier — pure function, no DB
# ---------------------------------------------------------------------------

class TestComputeMultiplier:
    """BC-1 through BC-5: pure multiplier function."""

    TIERS = [(3, 1.25), (5, 1.5), (7, 2.0), (14, 2.5)]

    def test_bc1_streak_below_first_tier_returns_1x(self):
        """BC-1: streak=1 → 1.0 (below first tier at day 3)."""
        from gamification.streak_engine import _compute_multiplier
        assert _compute_multiplier(1, self.TIERS) == 1.0

    def test_bc1_streak_2_returns_1x(self):
        """BC-1: streak=2 → still 1.0."""
        from gamification.streak_engine import _compute_multiplier
        assert _compute_multiplier(2, self.TIERS) == 1.0

    def test_bc2_streak_3_returns_1_25x(self):
        """BC-2: streak=3 → 1.25."""
        from gamification.streak_engine import _compute_multiplier
        assert _compute_multiplier(3, self.TIERS) == 1.25

    def test_bc2_streak_4_returns_1_25x(self):
        """BC-2: streak=4 → still 1.25 (not yet at tier 2)."""
        from gamification.streak_engine import _compute_multiplier
        assert _compute_multiplier(4, self.TIERS) == 1.25

    def test_bc3_streak_5_returns_1_5x(self):
        """BC-3: streak=5 → 1.5."""
        from gamification.streak_engine import _compute_multiplier
        assert _compute_multiplier(5, self.TIERS) == 1.5

    def test_bc3_streak_6_returns_1_5x(self):
        """BC-3: streak=6 → 1.5."""
        from gamification.streak_engine import _compute_multiplier
        assert _compute_multiplier(6, self.TIERS) == 1.5

    def test_bc4_streak_7_returns_2x(self):
        """BC-4: streak=7 → 2.0."""
        from gamification.streak_engine import _compute_multiplier
        assert _compute_multiplier(7, self.TIERS) == 2.0

    def test_bc4_streak_13_returns_2x(self):
        """BC-4: streak=13 → 2.0 (just below tier 4)."""
        from gamification.streak_engine import _compute_multiplier
        assert _compute_multiplier(13, self.TIERS) == 2.0

    def test_bc5_streak_14_returns_2_5x(self):
        """BC-5: streak=14 → 2.5."""
        from gamification.streak_engine import _compute_multiplier
        assert _compute_multiplier(14, self.TIERS) == 2.5

    def test_bc5_streak_30_returns_2_5x(self):
        """BC-5: streak=30 → 2.5 (above highest tier)."""
        from gamification.streak_engine import _compute_multiplier
        assert _compute_multiplier(30, self.TIERS) == 2.5

    def test_empty_tiers_returns_1x(self):
        """No tiers configured → fallback 1.0."""
        from gamification.streak_engine import _compute_multiplier
        assert _compute_multiplier(100, []) == 1.0

    def test_streak_zero_returns_1x(self):
        """Streak=0 edge case → 1.0."""
        from gamification.streak_engine import _compute_multiplier
        assert _compute_multiplier(0, self.TIERS) == 1.0


# ---------------------------------------------------------------------------
# update_daily_streak — DB-dependent
# ---------------------------------------------------------------------------

class TestFirstActivity:
    """BC-6: First activity ever (last_active_date=None)."""

    @pytest.mark.asyncio
    async def test_bc6_first_activity_sets_streak_to_1(self):
        """BC-6: last_active=None → streak=1."""
        from gamification.streak_engine import update_daily_streak
        db = _make_mock_db(student_streak=0, last_active=None)
        result = await update_daily_streak(db, uuid.uuid4())
        assert result["daily_streak"] == 1

    @pytest.mark.asyncio
    async def test_bc6_first_activity_multiplier_is_1x(self):
        """BC-6: First activity → multiplier=1.0 (below tier 1)."""
        from gamification.streak_engine import update_daily_streak
        db = _make_mock_db(student_streak=0, last_active=None)
        result = await update_daily_streak(db, uuid.uuid4())
        assert result["multiplier"] == 1.0

    @pytest.mark.asyncio
    async def test_bc6_first_activity_writes_to_db(self):
        """BC-6: First activity triggers a DB flush."""
        from gamification.streak_engine import update_daily_streak
        db = _make_mock_db(student_streak=0, last_active=None)
        result = await update_daily_streak(db, uuid.uuid4())
        assert result["streak_updated"] is True
        db.flush.assert_awaited_once()


class TestConsecutiveDay:
    """BC-7: Activity on consecutive calendar day increments streak."""

    @pytest.mark.asyncio
    async def test_bc7_consecutive_day_increments_streak(self):
        """BC-7: last_active=yesterday → streak increments by 1."""
        from gamification.streak_engine import update_daily_streak
        yesterday = date.today() - timedelta(days=1)
        db = _make_mock_db(student_streak=2, last_active=yesterday)
        result = await update_daily_streak(db, uuid.uuid4())
        assert result["daily_streak"] == 3

    @pytest.mark.asyncio
    async def test_bc7_consecutive_day_applies_tier_multiplier(self):
        """BC-7: After 3 consecutive days → 1.25x multiplier."""
        from gamification.streak_engine import update_daily_streak
        yesterday = date.today() - timedelta(days=1)
        db = _make_mock_db(student_streak=2, last_active=yesterday)
        result = await update_daily_streak(db, uuid.uuid4())
        # streak becomes 3 → tier 1 = 1.25x
        assert result["multiplier"] == 1.25

    @pytest.mark.asyncio
    async def test_bc7_best_streak_updated_when_exceeded(self):
        """BC-7: Best streak updates when current exceeds previous best."""
        from gamification.streak_engine import update_daily_streak
        yesterday = date.today() - timedelta(days=1)
        db = _make_mock_db(student_streak=4, student_best=4, last_active=yesterday)
        result = await update_daily_streak(db, uuid.uuid4())
        assert result["daily_streak_best"] == 5

    @pytest.mark.asyncio
    async def test_bc7_best_streak_preserved_when_not_exceeded(self):
        """BC-7: Best streak not overwritten if current is less."""
        from gamification.streak_engine import update_daily_streak
        yesterday = date.today() - timedelta(days=1)
        db = _make_mock_db(student_streak=2, student_best=10, last_active=yesterday)
        result = await update_daily_streak(db, uuid.uuid4())
        assert result["daily_streak_best"] == 10


class TestMissedDay:
    """BC-8: Missing a day resets streak to 1."""

    @pytest.mark.asyncio
    async def test_bc8_missed_day_resets_streak_to_1(self):
        """BC-8: last_active=2 days ago → streak reset to 1."""
        from gamification.streak_engine import update_daily_streak
        two_days_ago = date.today() - timedelta(days=2)
        db = _make_mock_db(student_streak=7, last_active=two_days_ago)
        result = await update_daily_streak(db, uuid.uuid4())
        assert result["daily_streak"] == 1

    @pytest.mark.asyncio
    async def test_bc8_reset_streak_gives_1x_multiplier(self):
        """BC-8: After reset, multiplier returns to 1.0."""
        from gamification.streak_engine import update_daily_streak
        two_days_ago = date.today() - timedelta(days=2)
        db = _make_mock_db(student_streak=7, last_active=two_days_ago)
        result = await update_daily_streak(db, uuid.uuid4())
        assert result["multiplier"] == 1.0

    @pytest.mark.asyncio
    async def test_bc8_long_gap_also_resets(self):
        """BC-8: last_active=30 days ago → reset to 1."""
        from gamification.streak_engine import update_daily_streak
        month_ago = date.today() - timedelta(days=30)
        db = _make_mock_db(student_streak=30, last_active=month_ago)
        result = await update_daily_streak(db, uuid.uuid4())
        assert result["daily_streak"] == 1


class TestSameDay:
    """BC-9: Same day activity does not change streak."""

    @pytest.mark.asyncio
    async def test_bc9_same_day_no_change(self):
        """BC-9: last_active=today → streak unchanged."""
        from gamification.streak_engine import update_daily_streak
        today = date.today()
        db = _make_mock_db(student_streak=5, last_active=today)
        result = await update_daily_streak(db, uuid.uuid4())
        assert result["daily_streak"] == 5
        assert result["streak_updated"] is False

    @pytest.mark.asyncio
    async def test_bc9_same_day_no_db_flush(self):
        """BC-9: No flush on same-day re-activity."""
        from gamification.streak_engine import update_daily_streak
        today = date.today()
        db = _make_mock_db(student_streak=5, last_active=today)
        await update_daily_streak(db, uuid.uuid4())
        db.flush.assert_not_awaited()


class TestStreakMultiplierDisabled:
    """BC-10: STREAK_MULTIPLIER_ENABLED=false → always 1.0."""

    @pytest.mark.asyncio
    async def test_bc10_disabled_returns_1x_even_with_high_streak(self):
        """BC-10: Multiplier disabled → 1.0 regardless of streak."""
        from gamification.streak_engine import update_daily_streak
        yesterday = date.today() - timedelta(days=1)
        db = _make_mock_db(student_streak=13, last_active=yesterday, streak_enabled="false")
        result = await update_daily_streak(db, uuid.uuid4())
        assert result["multiplier"] == 1.0

    @pytest.mark.asyncio
    async def test_bc10_disabled_still_tracks_streak(self):
        """BC-10: Streak still increments even when multiplier disabled."""
        from gamification.streak_engine import update_daily_streak
        yesterday = date.today() - timedelta(days=1)
        db = _make_mock_db(student_streak=6, last_active=yesterday, streak_enabled="false")
        result = await update_daily_streak(db, uuid.uuid4())
        assert result["daily_streak"] == 7
