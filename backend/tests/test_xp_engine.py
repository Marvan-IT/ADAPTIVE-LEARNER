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


# ---------------------------------------------------------------------------
# award_recovery_xp
# ---------------------------------------------------------------------------

class TestAwardRecoveryXp:
    """Tests for recovery-card XP award.

    Business criteria
    -----------------
    BC-R1  award_recovery_xp returns 5 XP with event_type='recovery_card'.
    BC-R2  XpEvent is created and added to the DB session.
    BC-R3  Student.xp is incremented by the recovery amount via UPDATE.
    BC-R4  db.flush() is called to persist within the transaction.
    BC-R5  Return dict shape matches other award functions.
    BC-R6  XP_RECOVERY is AdminConfig-tunable.
    BC-R7  session_id=None is accepted without error.
    """

    @pytest.mark.asyncio
    async def test_bc_r1_recovery_awards_5_xp(self):
        """BC-R1: award_recovery_xp → final_xp=5, base_xp=5, multiplier=1.0."""
        from gamification.xp_engine import award_recovery_xp

        db = _make_mock_db()
        result = await award_recovery_xp(
            db=db,
            student_id=_student_id(),
            session_id=_session_id(),
        )

        assert result["final_xp"] == 5
        assert result["base_xp"] == 5
        assert result["multiplier"] == 1.0

    @pytest.mark.asyncio
    async def test_bc_r2_recovery_creates_xp_event_with_correct_event_type(self):
        """BC-R2: An XpEvent with event_type='recovery_card' is added to the session."""
        from gamification.xp_engine import award_recovery_xp
        from db.models import XpEvent

        db = _make_mock_db()
        added_objects = []
        db.add = MagicMock(side_effect=added_objects.append)

        sid = _student_id()
        sess_id = _session_id()
        await award_recovery_xp(db=db, student_id=sid, session_id=sess_id)

        xp_events = [o for o in added_objects if isinstance(o, XpEvent)]
        assert len(xp_events) == 1
        ev = xp_events[0]
        assert ev.event_type == "recovery_card"
        assert ev.base_xp == 5
        assert ev.final_xp == 5
        assert ev.multiplier == 1.0
        assert ev.student_id == sid
        assert ev.session_id == sess_id

    @pytest.mark.asyncio
    async def test_bc_r3_recovery_increments_student_xp_via_update(self):
        """BC-R3: db.execute() is called (at least once) to UPDATE Student.xp."""
        from gamification.xp_engine import award_recovery_xp

        db = _make_mock_db()
        await award_recovery_xp(
            db=db,
            student_id=_student_id(),
            session_id=None,
        )

        assert db.execute.called

    @pytest.mark.asyncio
    async def test_bc_r4_recovery_flushes_db(self):
        """BC-R4: award_recovery_xp calls db.flush() so the caller controls the commit."""
        from gamification.xp_engine import award_recovery_xp

        db = _make_mock_db()
        await award_recovery_xp(
            db=db,
            student_id=_student_id(),
            session_id=None,
        )

        assert db.flush.called

    @pytest.mark.asyncio
    async def test_bc_r5_recovery_return_dict_shape(self):
        """BC-R5: Return dict contains base_xp, multiplier, final_xp, new_badges."""
        from gamification.xp_engine import award_recovery_xp

        db = _make_mock_db()
        result = await award_recovery_xp(
            db=db,
            student_id=_student_id(),
            session_id=None,
        )

        assert "base_xp" in result
        assert "multiplier" in result
        assert "final_xp" in result
        assert "new_badges" in result
        assert isinstance(result["new_badges"], list)
        assert result["new_badges"] == []

    @pytest.mark.asyncio
    async def test_bc_r6_recovery_xp_uses_admin_config_value(self):
        """BC-R6: When XP_RECOVERY is overridden to 20 in AdminConfig, 20 XP is awarded."""
        from gamification.xp_engine import award_recovery_xp

        db = _make_mock_db({"XP_RECOVERY": "20"})
        result = await award_recovery_xp(
            db=db,
            student_id=_student_id(),
            session_id=None,
        )

        assert result["final_xp"] == 20
        assert result["base_xp"] == 20

    @pytest.mark.asyncio
    async def test_bc_r7_recovery_xp_works_with_none_session_id(self):
        """BC-R7: award_recovery_xp should succeed when session_id is None."""
        from gamification.xp_engine import award_recovery_xp

        db = _make_mock_db()
        result = await award_recovery_xp(
            db=db,
            student_id=_student_id(),
            session_id=None,
        )

        assert result["final_xp"] == 5


# ---------------------------------------------------------------------------
# streak_info in compute_and_award_xp return value
# ---------------------------------------------------------------------------

class TestComputeAndAwardXpStreakInfo:
    """Tests that verify the streak_info field in compute_and_award_xp's return value.

    Business criteria
    -----------------
    BC-S1  Correct answer → return dict includes 'streak_info' with daily_streak,
           daily_streak_best, and multiplier keys (non-None).
    BC-S2  Wrong answer → 'streak_info' is None (early return, no streak update).
    BC-S3  Gamification disabled → 'streak_info' is None for both correct and wrong.
    BC-S4  streak_info.multiplier reflects the streak tier multiplier from streak engine.
    """

    @pytest.mark.asyncio
    async def test_bc_s1_correct_answer_has_streak_info_dict(self):
        """BC-S1: Correct answer return value includes streak_info with required keys."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db()
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await compute_and_award_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                interaction_id=None,
                difficulty=3,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
            )

        assert result["streak_info"] is not None
        si = result["streak_info"]
        assert "daily_streak" in si
        assert "daily_streak_best" in si
        assert "multiplier" in si

    @pytest.mark.asyncio
    async def test_bc_s2_wrong_answer_streak_info_is_none(self):
        """BC-S2: Wrong answer triggers early return; streak_info must be None."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db()
        result = await compute_and_award_xp(
            db=db,
            student_id=_student_id(),
            session_id=None,
            interaction_id=None,
            difficulty=3,
            wrong_attempts=0,
            hints_used=0,
            is_correct=False,
        )

        assert result["streak_info"] is None

    @pytest.mark.asyncio
    async def test_bc_s3_gamification_disabled_streak_info_is_none_for_correct(self):
        """BC-S3: When gamification is disabled, streak_info is None even for correct answers."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db({"GAMIFICATION_ENABLED": "false"})
        result = await compute_and_award_xp(
            db=db,
            student_id=_student_id(),
            session_id=None,
            interaction_id=None,
            difficulty=3,
            wrong_attempts=0,
            hints_used=0,
            is_correct=True,
        )

        assert result["streak_info"] is None

    @pytest.mark.asyncio
    async def test_bc_s3_gamification_disabled_streak_info_is_none_for_wrong(self):
        """BC-S3: When gamification is disabled and answer is wrong, streak_info is None."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db({"GAMIFICATION_ENABLED": "false"})
        result = await compute_and_award_xp(
            db=db,
            student_id=_student_id(),
            session_id=None,
            interaction_id=None,
            difficulty=3,
            wrong_attempts=0,
            hints_used=0,
            is_correct=False,
        )

        assert result["streak_info"] is None

    @pytest.mark.asyncio
    async def test_bc_s4_streak_info_multiplier_reflects_streak_engine_result(self):
        """BC-S4: streak_info.multiplier equals whatever update_daily_streak returns."""
        from gamification.xp_engine import compute_and_award_xp

        fake_streak_result = {
            "daily_streak": 7,
            "daily_streak_best": 10,
            "multiplier": 2.0,
            "streak_updated": True,
        }

        db = _make_mock_db()
        with patch(
            "gamification.streak_engine.update_daily_streak",
            new=AsyncMock(return_value=fake_streak_result),
        ), patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await compute_and_award_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                interaction_id=None,
                difficulty=3,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
            )

        assert result["streak_info"]["daily_streak"] == 7
        assert result["streak_info"]["daily_streak_best"] == 10
        assert result["streak_info"]["multiplier"] == 2.0


# ---------------------------------------------------------------------------
# answer_streak badge evaluation path in compute_and_award_xp
# ---------------------------------------------------------------------------

class TestComputeAndAwardXpAnswerStreakBadges:
    """Tests that verify badge evaluation is triggered correctly based on answer_streak.

    Business criteria
    -----------------
    BC-A1  answer_streak=0 → evaluate_badges called for 'card_correct' but NOT
           'answer_streak' event.
    BC-A2  answer_streak>0 → evaluate_badges called for all three events:
           'daily_streak' (when streak_updated), 'card_correct', 'answer_streak'.
    BC-A3  Badges returned by evaluate_badges are aggregated into new_badges list.
    """

    @pytest.mark.asyncio
    async def test_bc_a1_zero_answer_streak_skips_answer_streak_badge_eval(self):
        """BC-A1: answer_streak=0 → 'answer_streak' badge evaluation never called."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db()
        calls = []

        async def mock_evaluate_badges(db_, student_id, event_type, ctx):
            calls.append(event_type)
            return []

        with patch(
            "gamification.badge_engine.evaluate_badges",
            side_effect=mock_evaluate_badges,
        ):
            await compute_and_award_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                interaction_id=None,
                difficulty=2,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
                answer_streak=0,
            )

        assert "answer_streak" not in calls

    @pytest.mark.asyncio
    async def test_bc_a2_positive_answer_streak_triggers_answer_streak_badge_eval(self):
        """BC-A2: answer_streak=5 → evaluate_badges called with 'answer_streak' event type."""
        from gamification.xp_engine import compute_and_award_xp

        # Force streak_updated=True so daily_streak badge eval also fires
        fake_streak_result = {
            "daily_streak": 3,
            "daily_streak_best": 3,
            "multiplier": 1.25,
            "streak_updated": True,
        }

        db = _make_mock_db()
        calls = []

        async def mock_evaluate_badges(db_, student_id, event_type, ctx):
            calls.append(event_type)
            return []

        with patch(
            "gamification.streak_engine.update_daily_streak",
            new=AsyncMock(return_value=fake_streak_result),
        ), patch(
            "gamification.badge_engine.evaluate_badges",
            side_effect=mock_evaluate_badges,
        ):
            await compute_and_award_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                interaction_id=None,
                difficulty=2,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
                answer_streak=5,
            )

        assert "answer_streak" in calls
        assert "card_correct" in calls
        assert "daily_streak" in calls

    @pytest.mark.asyncio
    async def test_bc_a3_badges_from_all_evaluations_are_aggregated(self):
        """BC-A3: new_badges list contains badges from all three evaluate_badges calls."""
        from gamification.xp_engine import compute_and_award_xp

        fake_streak_result = {
            "daily_streak": 7,
            "daily_streak_best": 7,
            "multiplier": 2.0,
            "streak_updated": True,
        }

        db = _make_mock_db()
        call_count = 0

        async def mock_evaluate_badges(db_, student_id, event_type, ctx):
            nonlocal call_count
            call_count += 1
            return [{"badge_id": f"badge_{event_type}"}]

        with patch(
            "gamification.streak_engine.update_daily_streak",
            new=AsyncMock(return_value=fake_streak_result),
        ), patch(
            "gamification.badge_engine.evaluate_badges",
            side_effect=mock_evaluate_badges,
        ):
            result = await compute_and_award_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                interaction_id=None,
                difficulty=3,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
                answer_streak=3,
            )

        # Three badge evaluations fired (daily_streak, card_correct, answer_streak)
        assert call_count == 3
        assert len(result["new_badges"]) == 3


# ---------------------------------------------------------------------------
# XP_MASTERY_BONUS_THRESHOLD boundary precision
# ---------------------------------------------------------------------------

class TestMasteryXpBoundaryPrecision:
    """Additional boundary tests for the mastery bonus threshold.

    Business criteria
    -----------------
    BC-M1  Custom bonus threshold (e.g. 80) awards bonus at exactly 80.
    BC-M2  Custom bonus threshold (e.g. 80) does NOT award bonus at 79.
    BC-M3  score=0 → no bonus.
    BC-M4  score=100 (perfect) → bonus awarded; final_xp=75.
    """

    @pytest.mark.asyncio
    async def test_bc_m1_custom_threshold_awards_bonus_at_exact_boundary(self):
        """BC-M1: XP_MASTERY_BONUS_THRESHOLD=80, score=80 → bonus awarded (75 XP)."""
        from gamification.xp_engine import award_mastery_xp

        db = _make_mock_db({"XP_MASTERY_BONUS_THRESHOLD": "80"})
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await award_mastery_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                score=80,
            )

        assert result["final_xp"] == 75

    @pytest.mark.asyncio
    async def test_bc_m2_custom_threshold_no_bonus_below_boundary(self):
        """BC-M2: XP_MASTERY_BONUS_THRESHOLD=80, score=79 → no bonus (50 XP)."""
        from gamification.xp_engine import award_mastery_xp

        db = _make_mock_db({"XP_MASTERY_BONUS_THRESHOLD": "80"})
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await award_mastery_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                score=79,
            )

        assert result["final_xp"] == 50

    @pytest.mark.asyncio
    async def test_bc_m3_score_zero_no_bonus(self):
        """BC-M3: score=0 → 50 XP, no bonus, event_type=concept_mastery."""
        from gamification.xp_engine import award_mastery_xp
        from db.models import XpEvent

        db = _make_mock_db()
        added_objects = []
        db.add = MagicMock(side_effect=added_objects.append)

        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await award_mastery_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                score=0,
            )

        assert result["final_xp"] == 50
        xp_events = [o for o in added_objects if isinstance(o, XpEvent)]
        assert xp_events[0].event_type == "concept_mastery"

    @pytest.mark.asyncio
    async def test_bc_m4_perfect_score_awards_mastery_bonus(self):
        """BC-M4: score=100 (perfect) → bonus triggered, final_xp=75."""
        from gamification.xp_engine import award_mastery_xp

        db = _make_mock_db()
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await award_mastery_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                score=100,
            )

        assert result["final_xp"] == 75


# ---------------------------------------------------------------------------
# Flat XP mode (DIFFICULTY_WEIGHTED_XP_ENABLED=false)
# ---------------------------------------------------------------------------

class TestFlatXpMode:
    """Tests for the DIFFICULTY_WEIGHTED_XP_ENABLED=false code path.

    When this flag is off, all difficulty weighting, hint/wrong penalties, and
    the first-attempt bonus are ignored — the base_xp is set to the consolation
    value (XP_CONSOLATION default=10) and streak multiplier still applies.

    Business criteria
    -----------------
    BC-F1  Flat mode: difficulty=5, no penalties → base_xp=10 (consolation value).
    BC-F2  Flat mode: hints/wrongs have no effect on XP.
    BC-F3  Flat mode: first_attempt_bonus is not applied (bonus=1.0).
    """

    @pytest.mark.asyncio
    async def test_bc_f1_flat_mode_uses_consolation_as_base(self):
        """BC-F1: DIFFICULTY_WEIGHTED_XP_ENABLED=false → base_xp equals XP_CONSOLATION."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db({"DIFFICULTY_WEIGHTED_XP_ENABLED": "false"})
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
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

        assert result["base_xp"] == 10

    @pytest.mark.asyncio
    async def test_bc_f2_flat_mode_hints_and_wrongs_do_not_reduce_xp(self):
        """BC-F2: In flat mode, hint and wrong attempt penalties are not applied."""
        from gamification.xp_engine import compute_and_award_xp

        db_no_penalty = _make_mock_db({"DIFFICULTY_WEIGHTED_XP_ENABLED": "false"})
        db_with_penalty = _make_mock_db({"DIFFICULTY_WEIGHTED_XP_ENABLED": "false"})

        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result_clean = await compute_and_award_xp(
                db=db_no_penalty,
                student_id=_student_id(),
                session_id=None,
                interaction_id=None,
                difficulty=3,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
            )
            result_penalised = await compute_and_award_xp(
                db=db_with_penalty,
                student_id=_student_id(),
                session_id=None,
                interaction_id=None,
                difficulty=3,
                wrong_attempts=5,
                hints_used=5,
                is_correct=True,
            )

        assert result_clean["final_xp"] == result_penalised["final_xp"]

    @pytest.mark.asyncio
    async def test_bc_f3_flat_mode_first_attempt_bonus_not_applied(self):
        """BC-F3: No 1.5x first_attempt_bonus in flat mode; base=10 stays at 10."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_mock_db({"DIFFICULTY_WEIGHTED_XP_ENABLED": "false"})
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await compute_and_award_xp(
                db=db,
                student_id=_student_id(),
                session_id=None,
                interaction_id=None,
                difficulty=3,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
            )

        # If the 1.5x bonus were applied: round(10 * 1.5) = 15.
        # In flat mode it must stay at 10.
        assert result["final_xp"] == 10
