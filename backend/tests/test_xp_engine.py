"""
test_xp_engine.py

Unit tests for the gamification XP calculation engine.

Business criteria covered
--------------------------
BC-1  Difficulty 1, no hints/wrong → base_xp=4, first_attempt_bonus=1.5, final_xp=6
BC-2  Difficulty 5, no hints/wrong → base_xp=20, final_xp=30
BC-3  Difficulty 3, 2 hints → hint_factor=max(0.25, 1-0.5)=0.5, no first_attempt bonus
BC-4  Difficulty 3, 3 wrong attempts → wrong_factor=max(0.25, 1-0.45)=0.55
BC-5  Combined: difficulty 4, 1 hint, 1 wrong → final=round(16*0.75*0.85)=10
BC-6  Minimum floor: final_xp >= 1 even at maximum penalties
BC-7  award_mastery_xp score>=90 → 50+25=75 XP with mastery_bonus event
BC-8  award_mastery_xp score<90 → 50 XP with concept_mastery event
BC-9  award_consolation_xp → 10 XP
BC-10 GAMIFICATION_ENABLED=false → flat 10 XP for correct, 0 XP for wrong

Run: pytest backend/tests/test_xp_engine.py -v
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ---------------------------------------------------------------------------
# DB mock factory
# ---------------------------------------------------------------------------

def _make_mock_db(config_overrides: dict | None = None) -> AsyncMock:
    """
    Build an AsyncSession mock that returns AdminConfig values from
    config_overrides (falls back to XP engine DEFAULTS for any missing key).
    Streak query returns a mock student with streak=1/last_active_date=None
    so update_daily_streak returns multiplier=1.0 without extra setup.
    """
    from gamification.xp_engine import DEFAULTS

    config = {**DEFAULTS, **(config_overrides or {})}

    db = AsyncMock()

    async def _execute_side_effect(stmt, *args, **kwargs):
        # Inspect the compiled statement to decide what to return.
        stmt_str = str(stmt)

        # AdminConfig value lookup — extract the key from whereclause bind param
        if "admin_config" in stmt_str.lower() or "adminconfig" in stmt_str:
            requested_key = None
            try:
                clause = stmt.whereclause
                if hasattr(clause, "right") and hasattr(clause.right, "value"):
                    requested_key = clause.right.value
            except Exception:
                pass

            if requested_key and requested_key in config:
                r = MagicMock()
                r.scalar_one_or_none = MagicMock(return_value=config[requested_key])
                return r
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=None)
            return r

        # Student SELECT for streak engine
        if "students" in stmt_str.lower():
            student = MagicMock()
            student.id = uuid.uuid4()
            student.daily_streak = 0
            student.daily_streak_best = 0
            student.last_active_date = None
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=student)
            return r

        # Student UPDATE (streak write-back)
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=None)
        return r

    db.execute = AsyncMock(side_effect=_execute_side_effect)
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _student_id() -> uuid.UUID:
    return uuid.uuid4()


def _session_id() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# compute_and_award_xp — correct answers, difficulty-weighted mode
# ---------------------------------------------------------------------------

class TestComputeAndAwardXpDifficultyWeighted:
    """Tests for difficulty-weighted XP when GAMIFICATION_ENABLED=true."""

    @pytest.mark.asyncio
    async def test_bc1_difficulty_1_no_penalties_awards_6_xp(self):
        """BC-1: Difficulty 1, no hints, no wrong attempts → base=4, bonus=1.5x, final=6."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db()
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await compute_and_award_xp(
                db=db,
                student_id=_student_id(),
                session_id=_session_id(),
                interaction_id=uuid.uuid4(),
                difficulty=1,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
            )

        assert result["base_xp"] == 4
        assert result["final_xp"] == 6
        # XpEvent must be persisted
        assert db.add.called
        assert db.flush.called

    @pytest.mark.asyncio
    async def test_bc2_difficulty_5_no_penalties_awards_30_xp(self):
        """BC-2: Difficulty 5, no hints, no wrong attempts → base=20, bonus=1.5x, final=30."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db()
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await compute_and_award_xp(
                db=db,
                student_id=_student_id(),
                session_id=_session_id(),
                interaction_id=uuid.uuid4(),
                difficulty=5,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
            )

        assert result["base_xp"] == 20
        assert result["final_xp"] == 30

    @pytest.mark.asyncio
    async def test_bc3_hint_penalty_halves_xp_and_removes_first_attempt_bonus(self):
        """BC-3: Difficulty 3, 2 hints → hint_factor=0.5, no first_attempt_bonus.

        base=12, hint_factor=max(0.25, 1.0-0.25*2)=0.5, wrong_factor=1.0, bonus=1.0
        → final=round(12*0.5*1.0*1.0)=6
        """
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db()
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await compute_and_award_xp(
                db=db,
                student_id=_student_id(),
                session_id=_session_id(),
                interaction_id=uuid.uuid4(),
                difficulty=3,
                wrong_attempts=0,
                hints_used=2,
                is_correct=True,
            )

        assert result["base_xp"] == 12
        # hint_factor = 0.5; no first_attempt_bonus because hints_used > 0
        assert result["final_xp"] == 6

    @pytest.mark.asyncio
    async def test_bc3_hints_suppress_first_attempt_bonus(self):
        """BC-3 extension: any hints_used > 0 removes the 1.5x first_attempt_bonus."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db()
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await compute_and_award_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                interaction_id=None,
                difficulty=4,
                wrong_attempts=0,
                hints_used=1,   # one hint → no bonus
                is_correct=True,
            )

        # base=16, hint_factor=max(0.25,1-0.25)=0.75, bonus=1.0
        # final = round(16 * 0.75 * 1.0 * 1.0) = round(12.0) = 12
        assert result["base_xp"] == 16
        assert result["final_xp"] == 12

    @pytest.mark.asyncio
    async def test_bc4_wrong_attempts_apply_penalty(self):
        """BC-4: Difficulty 3, 3 wrong attempts → wrong_factor=max(0.25,1-0.45)=0.55.

        base=12, hint_factor=1.0, wrong_factor=0.55, bonus=1.0 (wrongs≠0)
        → final=round(12*0.55)=7 (rounded from 6.6)
        """
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db()
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await compute_and_award_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                interaction_id=None,
                difficulty=3,
                wrong_attempts=3,
                hints_used=0,
                is_correct=True,
            )

        assert result["base_xp"] == 12
        # wrong_factor = max(0.25, 1-0.45) = 0.55; bonus=1.0 (wrongs>0)
        assert result["final_xp"] == round(12 * 0.55)

    @pytest.mark.asyncio
    async def test_bc5_combined_difficulty_4_hint_1_wrong_1(self):
        """BC-5: difficulty=4, hints=1, wrong=1 → final=round(16*0.75*0.85)=10."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db()
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await compute_and_award_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                interaction_id=None,
                difficulty=4,
                wrong_attempts=1,
                hints_used=1,
                is_correct=True,
            )

        # base=16, hint_factor=0.75, wrong_factor=0.85, bonus=1.0
        assert result["base_xp"] == 16
        assert result["final_xp"] == round(16 * 0.75 * 0.85)
        assert result["final_xp"] == 10

    @pytest.mark.asyncio
    async def test_bc6_minimum_floor_is_1_at_maximum_penalties(self):
        """BC-6: Even with maximum penalties, final_xp >= 1.

        difficulty=1, hints=10, wrong=10 → hint_factor=0.25, wrong_factor=0.25, bonus=1.0
        → base=4, pre-floor=round(4*0.25*0.25)=round(0.25)=0 → clamped to 1.
        """
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db()
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await compute_and_award_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                interaction_id=None,
                difficulty=1,
                wrong_attempts=10,
                hints_used=10,
                is_correct=True,
            )

        assert result["final_xp"] >= 1

    @pytest.mark.asyncio
    async def test_wrong_answer_returns_zero_xp_and_skips_db_writes(self):
        """Incorrect answer → 0 XP; no XpEvent row, no Student XP increment."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db()
        result = await compute_and_award_xp(
            db=db,
            student_id=_student_id(),
            session_id=None,
            interaction_id=None,
            difficulty=3,
            wrong_attempts=1,
            hints_used=0,
            is_correct=False,
        )

        assert result["final_xp"] == 0
        assert result["base_xp"] == 0
        # No DB mutation should have occurred
        assert not db.add.called
        assert not db.flush.called

    @pytest.mark.asyncio
    async def test_xp_result_contains_expected_keys(self):
        """Return dict must always contain base_xp, multiplier, final_xp, new_badges."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db()
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await compute_and_award_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                interaction_id=None,
                difficulty=2,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
            )

        assert "base_xp" in result
        assert "multiplier" in result
        assert "final_xp" in result
        assert "new_badges" in result
        assert isinstance(result["new_badges"], list)


# ---------------------------------------------------------------------------
# compute_and_award_xp — gamification disabled (BC-10)
# ---------------------------------------------------------------------------

class TestComputeAndAwardXpDisabled:
    """Tests for the GAMIFICATION_ENABLED=false code path."""

    @pytest.mark.asyncio
    async def test_bc10_gamification_disabled_awards_flat_10_xp_for_correct(self):
        """BC-10: When GAMIFICATION_ENABLED=false, correct answer → flat 10 XP."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db({"GAMIFICATION_ENABLED": "false"})
        result = await compute_and_award_xp(
            db=db,
            student_id=_student_id(),
            session_id=None,
            interaction_id=None,
            difficulty=5,
            wrong_attempts=0,
            hints_used=0,
            is_correct=True,
        )

        assert result["final_xp"] == 10
        assert result["base_xp"] == 10
        assert result["multiplier"] == 1.0
        assert db.add.called  # XpEvent still written

    @pytest.mark.asyncio
    async def test_bc10_gamification_disabled_awards_0_xp_for_wrong(self):
        """BC-10: When GAMIFICATION_ENABLED=false, wrong answer → 0 XP, no DB writes."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db({"GAMIFICATION_ENABLED": "false"})
        result = await compute_and_award_xp(
            db=db,
            student_id=_student_id(),
            session_id=None,
            interaction_id=None,
            difficulty=5,
            wrong_attempts=0,
            hints_used=0,
            is_correct=False,
        )

        assert result["final_xp"] == 0
        assert not db.add.called

    @pytest.mark.asyncio
    async def test_bc10_gamification_disabled_ignores_difficulty_level(self):
        """BC-10: Flat XP is constant regardless of card difficulty."""
        from gamification.xp_engine import compute_and_award_xp

        for difficulty in (1, 3, 5):
            db = _make_mock_db({"GAMIFICATION_ENABLED": "false"})
            result = await compute_and_award_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                interaction_id=None,
                difficulty=difficulty,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
            )
            assert result["final_xp"] == 10, f"Expected 10 XP for difficulty={difficulty}"


# ---------------------------------------------------------------------------
# award_mastery_xp (BC-7, BC-8)
# ---------------------------------------------------------------------------

class TestAwardMasteryXp:
    """Tests for concept mastery XP award."""

    @pytest.mark.asyncio
    async def test_bc7_score_at_or_above_90_threshold_awards_bonus(self):
        """BC-7: score=95 (>=90) → base XP = 50 + 25 = 75, event_type=mastery_bonus."""
        from gamification.xp_engine import award_mastery_xp

        db = _make_mock_db()
        # Capture the XpEvent added to the session
        added_objects = []
        db.add = MagicMock(side_effect=added_objects.append)

        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await award_mastery_xp(
                db=db,
                student_id=_student_id(),
                session_id=_session_id(),
                score=95,
            )

        assert result["base_xp"] == 75
        assert result["final_xp"] == 75
        assert result["multiplier"] == 1.0
        # Check the event_type on the created XpEvent
        from db.models import XpEvent
        xp_events = [o for o in added_objects if isinstance(o, XpEvent)]
        assert len(xp_events) == 1
        assert xp_events[0].event_type == "mastery_bonus"

    @pytest.mark.asyncio
    async def test_bc7_score_exactly_90_qualifies_for_bonus(self):
        """BC-7 boundary: score=90 (exactly at threshold) → 75 XP."""
        from gamification.xp_engine import award_mastery_xp

        db = _make_mock_db()
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await award_mastery_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                score=90,
            )

        assert result["final_xp"] == 75

    @pytest.mark.asyncio
    async def test_bc8_score_below_90_awards_base_mastery_only(self):
        """BC-8: score=70 (<90) → 50 XP, event_type=concept_mastery."""
        from gamification.xp_engine import award_mastery_xp

        db = _make_mock_db()
        added_objects = []
        db.add = MagicMock(side_effect=added_objects.append)

        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await award_mastery_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                score=70,
            )

        assert result["base_xp"] == 50
        assert result["final_xp"] == 50
        from db.models import XpEvent
        xp_events = [o for o in added_objects if isinstance(o, XpEvent)]
        assert xp_events[0].event_type == "concept_mastery"

    @pytest.mark.asyncio
    async def test_bc8_score_just_below_threshold_does_not_get_bonus(self):
        """BC-8 boundary: score=89 → base 50 XP only."""
        from gamification.xp_engine import award_mastery_xp

        db = _make_mock_db()
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await award_mastery_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                score=89,
            )

        assert result["final_xp"] == 50

    @pytest.mark.asyncio
    async def test_award_mastery_xp_with_none_score_awards_base_only(self):
        """score=None (check not yet run) → 50 XP, no bonus."""
        from gamification.xp_engine import award_mastery_xp

        db = _make_mock_db()
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await award_mastery_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                score=None,
            )

        assert result["final_xp"] == 50

    @pytest.mark.asyncio
    async def test_award_mastery_xp_flushes_db(self):
        """award_mastery_xp must call db.flush() to persist within the transaction."""
        from gamification.xp_engine import award_mastery_xp

        db = _make_mock_db()
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            await award_mastery_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                score=80,
            )

        assert db.flush.called


# ---------------------------------------------------------------------------
# award_consolation_xp (BC-9)
# ---------------------------------------------------------------------------

class TestAwardConsolationXp:
    """Tests for consolation XP at session end without mastery."""

    @pytest.mark.asyncio
    async def test_bc9_consolation_awards_10_xp(self):
        """BC-9: award_consolation_xp → 10 XP, event_type=consolation."""
        from gamification.xp_engine import award_consolation_xp

        db = _make_mock_db()
        added_objects = []
        db.add = MagicMock(side_effect=added_objects.append)

        result = await award_consolation_xp(
            db=db,
            student_id=_student_id(),
            session_id=_session_id(),
        )

        assert result["final_xp"] == 10
        assert result["base_xp"] == 10
        assert result["multiplier"] == 1.0
        assert result["new_badges"] == []

        from db.models import XpEvent
        xp_events = [o for o in added_objects if isinstance(o, XpEvent)]
        assert len(xp_events) == 1
        assert xp_events[0].event_type == "consolation"

    @pytest.mark.asyncio
    async def test_consolation_xp_flushes_db(self):
        """award_consolation_xp must call db.flush()."""
        from gamification.xp_engine import award_consolation_xp

        db = _make_mock_db()
        await award_consolation_xp(
            db=db,
            student_id=_student_id(),
            session_id=None,
        )

        assert db.flush.called

    @pytest.mark.asyncio
    async def test_consolation_xp_returns_no_badges(self):
        """Consolation XP awards no badges — it is an encouragement event only."""
        from gamification.xp_engine import award_consolation_xp

        db = _make_mock_db()
        result = await award_consolation_xp(
            db=db,
            student_id=_student_id(),
            session_id=None,
        )

        assert result["new_badges"] == []
