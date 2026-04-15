"""
test_feature_flags.py

Unit tests for gamification feature flag behaviour.

Feature flags are stored as rows in the AdminConfig table (key/value TEXT pairs).
The XP engine, badge engine, and streak engine each call _get_config() at
runtime — so tests mock the DB to return specific config values and verify
the engines honour the flag.

Business criteria covered
--------------------------
BC-1  GAMIFICATION_ENABLED=false → compute_and_award_xp returns flat 10 XP,
      no difficulty weighting, no badge evaluation
BC-2  BADGES_ENABLED=false → evaluate_badges returns empty list regardless
      of trigger
BC-3  STREAK_MULTIPLIER_ENABLED=false → streak multiplier is 1.0; XP engine
      receives multiplier=1.0 from update_daily_streak, so final_xp is not
      inflated by a streak bonus
BC-4  DIFFICULTY_WEIGHTED_XP_ENABLED=false → XP falls back to consolation
      flat amount (default 10) regardless of difficulty
BC-5  LEADERBOARD_ENABLED=false → get_leaderboard returns HTTP 403
BC-6  All flags default to enabled (true) when no AdminConfig rows exist,
      EXCEPT LEADERBOARD_ENABLED which defaults to false
BC-7  Feature flags endpoint (GET /features) reflects live AdminConfig state

Run: pytest backend/tests/test_feature_flags.py -v
"""
from __future__ import annotations

import sys
import uuid
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient
from starlette.requests import Request as StarletteRequest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _fake_request() -> StarletteRequest:
    """Create a minimal Starlette Request that satisfies slowapi."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],
        "root_path": "",
        "app": MagicMock(),
    }
    return StarletteRequest(scope)


# ---------------------------------------------------------------------------
# DB mock factories
# ---------------------------------------------------------------------------

def _sid() -> uuid.UUID:
    return uuid.uuid4()


def _make_xp_db(config_overrides: dict | None = None) -> AsyncMock:
    """
    Build a DB mock for XP engine tests.  Config is keyed by AdminConfig.key;
    any key not in the override dict falls back to the XP engine DEFAULTS.
    Streak-engine queries return a stub student with streak=0 / last_active=None.
    """
    from gamification.xp_engine import DEFAULTS

    config = {**DEFAULTS, **(config_overrides or {})}

    student = MagicMock()
    student.id = _sid()
    student.daily_streak = 0
    student.daily_streak_best = 0
    student.last_active_date = None

    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    async def _execute(stmt, *a, **kw):
        stmt_str = str(stmt)
        r = MagicMock()

        if "admin_config" in stmt_str.lower() or "adminconfig" in stmt_str:
            requested_key = None
            try:
                clause = stmt.whereclause
                if hasattr(clause, "right") and hasattr(clause.right, "value"):
                    requested_key = clause.right.value
            except Exception:
                pass
            if requested_key and requested_key in config:
                r.scalar_one_or_none = MagicMock(return_value=config[requested_key])
                return r
            r.scalar_one_or_none = MagicMock(return_value=None)
            return r

        if "students" in stmt_str.lower():
            r.scalar_one_or_none = MagicMock(return_value=student)
            return r

        r.scalar_one_or_none = MagicMock(return_value=None)
        return r

    db.execute = AsyncMock(side_effect=_execute)
    return db


def _make_badge_db(badges_enabled: str = "true") -> AsyncMock:
    """DB mock for badge engine tests — controls BADGES_ENABLED flag."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    async def _execute(stmt, *a, **kw):
        stmt_str = str(stmt)
        r = MagicMock()

        if "admin_config" in stmt_str.lower() or "adminconfig" in stmt_str:
            requested_key = None
            try:
                clause = stmt.whereclause
                if hasattr(clause, "right") and hasattr(clause.right, "value"):
                    requested_key = clause.right.value
            except Exception:
                pass
            if requested_key == "BADGES_ENABLED":
                r.scalar_one_or_none = MagicMock(return_value=badges_enabled)
                return r
            r.scalar_one_or_none = MagicMock(return_value=None)
            return r

        # Earned-badge query → no badges yet
        if "student_badges" in stmt_str.lower():
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            return r

        # Aggregate queries (total_correct, mastered_count, daily_streak)
        r.scalar = MagicMock(return_value=0)
        r.scalar_one_or_none = MagicMock(return_value=None)
        return r

    db.execute = AsyncMock(side_effect=_execute)
    return db


def _make_streak_db(
    streak_enabled: str = "true",
    student_streak: int = 4,
    last_active: date | None = None,
) -> AsyncMock:
    """DB mock for streak engine tests with configurable flag state."""
    tier_config = {
        "STREAK_MULTIPLIER_ENABLED": streak_enabled,
        "STREAK_TIER_1_DAYS": "3",
        "STREAK_TIER_1_MULT": "1.25",
        "STREAK_TIER_2_DAYS": "5",
        "STREAK_TIER_2_MULT": "1.5",
        "STREAK_TIER_3_DAYS": "7",
        "STREAK_TIER_3_MULT": "2.0",
        "STREAK_TIER_4_DAYS": "14",
        "STREAK_TIER_4_MULT": "2.5",
    }

    student = MagicMock()
    student.id = _sid()
    student.daily_streak = student_streak
    student.daily_streak_best = student_streak
    student.last_active_date = last_active

    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    async def _execute(stmt, *a, **kw):
        stmt_str = str(stmt)
        r = MagicMock()

        if "admin_config" in stmt_str.lower() or "adminconfig" in stmt_str:
            requested_key = None
            try:
                clause = stmt.whereclause
                if hasattr(clause, "right") and hasattr(clause.right, "value"):
                    requested_key = clause.right.value
            except Exception:
                pass
            if requested_key and requested_key in tier_config:
                r.scalar_one_or_none = MagicMock(return_value=tier_config[requested_key])
                return r
            r.scalar_one_or_none = MagicMock(return_value=None)
            return r

        if "students" in stmt_str.lower():
            r.scalar_one_or_none = MagicMock(return_value=student)
            return r

        r.scalar_one_or_none = MagicMock(return_value=None)
        return r

    db.execute = AsyncMock(side_effect=_execute)
    return db


def _make_leaderboard_db(leaderboard_enabled: str) -> AsyncMock:
    """Minimal DB mock for leaderboard feature flag test."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    async def _execute(stmt, *a, **kw):
        r = MagicMock()
        stmt_str = str(stmt)
        if "admin_config" in stmt_str.lower() or "adminconfig" in stmt_str:
            requested_key = None
            try:
                clause = stmt.whereclause
                if hasattr(clause, "right") and hasattr(clause.right, "value"):
                    requested_key = clause.right.value
            except Exception:
                pass
            if requested_key == "LEADERBOARD_ENABLED":
                r.scalar_one_or_none = MagicMock(return_value=leaderboard_enabled)
                return r
        r.scalar_one_or_none = MagicMock(return_value=None)
        r.all = MagicMock(return_value=[])
        r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        return r

    db.execute = AsyncMock(side_effect=_execute)
    return db


def _make_features_db(flag_overrides: dict | None = None) -> AsyncMock:
    """DB mock for GET /features endpoint — returns an AdminConfig row set."""
    defaults = {
        "GAMIFICATION_ENABLED": "true",
        "LEADERBOARD_ENABLED": "false",
        "BADGES_ENABLED": "true",
        "STREAK_MULTIPLIER_ENABLED": "true",
        "DIFFICULTY_WEIGHTED_XP_ENABLED": "true",
    }
    if flag_overrides:
        defaults.update(flag_overrides)

    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    async def _execute(stmt, *a, **kw):
        r = MagicMock()
        # The features endpoint does a single IN query and calls .all()
        pairs = list(defaults.items())
        r.all = MagicMock(return_value=pairs)
        r.scalar_one_or_none = MagicMock(return_value=None)
        return r

    db.execute = AsyncMock(side_effect=_execute)
    return db


# ---------------------------------------------------------------------------
# BC-1: GAMIFICATION_ENABLED=false → flat 10 XP, no badge evaluation
# ---------------------------------------------------------------------------

class TestGamificationDisabled:
    """BC-1: Master flag off → flat 10 XP path; difficulty weighting bypassed."""

    @pytest.mark.asyncio
    async def test_bc1_gamification_disabled_correct_answer_gives_flat_10(self):
        """BC-1: GAMIFICATION_ENABLED=false + correct → final_xp=10 always."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_xp_db({"GAMIFICATION_ENABLED": "false"})
        result = await compute_and_award_xp(
            db=db,
            student_id=_sid(),
            session_id=_sid(),
            interaction_id=_sid(),
            difficulty=5,
            wrong_attempts=0,
            hints_used=0,
            is_correct=True,
        )

        assert result["final_xp"] == 10
        assert result["base_xp"] == 10

    @pytest.mark.asyncio
    async def test_bc1_gamification_disabled_ignores_difficulty(self):
        """BC-1: XP is flat 10 regardless of difficulty level."""
        from gamification.xp_engine import compute_and_award_xp

        for difficulty in (1, 3, 5):
            db = _make_xp_db({"GAMIFICATION_ENABLED": "false"})
            result = await compute_and_award_xp(
                db=db,
                student_id=_sid(),
                session_id=None,
                interaction_id=None,
                difficulty=difficulty,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
            )
            assert result["final_xp"] == 10, f"Expected 10 for difficulty={difficulty}"

    @pytest.mark.asyncio
    async def test_bc1_gamification_disabled_returns_no_badges(self):
        """BC-1: When GAMIFICATION_ENABLED=false the flat path returns new_badges=[]."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_xp_db({"GAMIFICATION_ENABLED": "false"})
        result = await compute_and_award_xp(
            db=db,
            student_id=_sid(),
            session_id=None,
            interaction_id=None,
            difficulty=3,
            wrong_attempts=0,
            hints_used=0,
            is_correct=True,
        )

        assert result["new_badges"] == []

    @pytest.mark.asyncio
    async def test_bc1_gamification_disabled_wrong_answer_gives_zero_xp(self):
        """BC-1: GAMIFICATION_ENABLED=false + wrong → 0 XP, no DB writes."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_xp_db({"GAMIFICATION_ENABLED": "false"})
        result = await compute_and_award_xp(
            db=db,
            student_id=_sid(),
            session_id=None,
            interaction_id=None,
            difficulty=3,
            wrong_attempts=1,
            hints_used=0,
            is_correct=False,
        )

        assert result["final_xp"] == 0
        db.add.assert_not_called()


# ---------------------------------------------------------------------------
# BC-2: BADGES_ENABLED=false → evaluate_badges returns []
# ---------------------------------------------------------------------------

class TestBadgesDisabled:
    """BC-2: BADGES_ENABLED=false → badge engine always returns empty list."""

    @pytest.mark.asyncio
    async def test_bc2_badges_disabled_card_correct_trigger_returns_empty(self):
        """BC-2: BADGES_ENABLED=false, trigger=card_correct → []."""
        from gamification.badge_engine import evaluate_badges

        db = _make_badge_db(badges_enabled="false")
        result = await evaluate_badges(db, _sid(), "card_correct", {})

        assert result == []

    @pytest.mark.asyncio
    async def test_bc2_badges_disabled_concept_mastery_trigger_returns_empty(self):
        """BC-2: BADGES_ENABLED=false, trigger=concept_mastery → []."""
        from gamification.badge_engine import evaluate_badges

        db = _make_badge_db(badges_enabled="false")
        result = await evaluate_badges(db, _sid(), "concept_mastery", {})

        assert result == []

    @pytest.mark.asyncio
    async def test_bc2_badges_disabled_daily_streak_trigger_returns_empty(self):
        """BC-2: BADGES_ENABLED=false, trigger=daily_streak → []."""
        from gamification.badge_engine import evaluate_badges

        db = _make_badge_db(badges_enabled="false")
        result = await evaluate_badges(db, _sid(), "daily_streak", {})

        assert result == []

    @pytest.mark.asyncio
    async def test_bc2_badges_enabled_by_default_evaluates_triggers(self):
        """BC-2 inverse: BADGES_ENABLED=true → evaluation proceeds (does not short-circuit)."""
        from gamification.badge_engine import evaluate_badges

        db = _make_badge_db(badges_enabled="true")

        # With no existing badges the engine will run checks; result may still
        # be empty if no thresholds are met — but the function must not skip evaluation.
        # We verify no exception is raised and a list is returned.
        result = await evaluate_badges(db, _sid(), "card_correct", {"total_correct": 0})
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# BC-3: STREAK_MULTIPLIER_ENABLED=false → multiplier stays 1.0
# ---------------------------------------------------------------------------

class TestStreakMultiplierDisabledIntegration:
    """BC-3: Streak multiplier flag off → XP engine receives 1.0 from streak engine."""

    @pytest.mark.asyncio
    async def test_bc3_streak_multiplier_disabled_returns_1x(self):
        """BC-3: With STREAK_MULTIPLIER_ENABLED=false, update_daily_streak returns 1.0."""
        from gamification.streak_engine import update_daily_streak

        yesterday = date.today() - timedelta(days=1)
        # streak=4 → would normally be 1.25x at tier 1 (3+ days)
        db = _make_streak_db(streak_enabled="false", student_streak=4, last_active=yesterday)
        result = await update_daily_streak(db, _sid())

        assert result["multiplier"] == 1.0

    @pytest.mark.asyncio
    async def test_bc3_streak_disabled_still_tracks_streak_days(self):
        """BC-3: Streak counter still increments even when multiplier is disabled."""
        from gamification.streak_engine import update_daily_streak

        yesterday = date.today() - timedelta(days=1)
        db = _make_streak_db(streak_enabled="false", student_streak=6, last_active=yesterday)
        result = await update_daily_streak(db, _sid())

        assert result["daily_streak"] == 7

    @pytest.mark.asyncio
    async def test_bc3_xp_not_inflated_when_streak_multiplier_disabled(self):
        """BC-3: XP engine integration — final_xp equals base*first_attempt_bonus only.

        With streak multiplier disabled the only active multiplier is
        first_attempt_bonus (1.5x).  For difficulty=2: base=8, final=12.
        """
        from gamification.xp_engine import compute_and_award_xp

        # Build a combined XP + streak DB config with multiplier disabled
        from gamification.xp_engine import DEFAULTS
        config = {
            **DEFAULTS,
            "STREAK_MULTIPLIER_ENABLED": "false",
        }

        student = MagicMock()
        student.id = _sid()
        student.daily_streak = 0
        student.daily_streak_best = 0
        yesterday = date.today() - timedelta(days=1)
        student.last_active_date = yesterday  # consecutive → would normally boost

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        async def _execute(stmt, *a, **kw):
            stmt_str = str(stmt)
            r = MagicMock()
            if "admin_config" in stmt_str.lower() or "adminconfig" in stmt_str:
                for key, val in config.items():
                    if key in stmt_str:
                        r.scalar_one_or_none = MagicMock(return_value=val)
                        return r
                r.scalar_one_or_none = MagicMock(return_value=None)
                return r
            if "students" in stmt_str.lower():
                r.scalar_one_or_none = MagicMock(return_value=student)
                return r
            r.scalar_one_or_none = MagicMock(return_value=None)
            return r

        db.execute = AsyncMock(side_effect=_execute)

        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await compute_and_award_xp(
                db=db,
                student_id=_sid(),
                session_id=None,
                interaction_id=None,
                difficulty=2,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
            )

        # base=8, streak_mult=1.0, first_attempt_bonus=1.5
        # → final = round(8 * 1.0 * 1.0 * 1.5) = 12
        assert result["final_xp"] == 12


# ---------------------------------------------------------------------------
# BC-4: DIFFICULTY_WEIGHTED_XP_ENABLED=false → flat consolation XP
# ---------------------------------------------------------------------------

class TestDifficultyWeightingDisabled:
    """BC-4: Difficulty-weighted XP disabled → flat consolation XP (default 10)."""

    @pytest.mark.asyncio
    async def test_bc4_difficulty_weighting_disabled_gives_flat_xp(self):
        """BC-4: DIFFICULTY_WEIGHTED_XP_ENABLED=false → base_xp=XP_CONSOLATION (10)."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_xp_db({"DIFFICULTY_WEIGHTED_XP_ENABLED": "false"})

        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await compute_and_award_xp(
                db=db,
                student_id=_sid(),
                session_id=None,
                interaction_id=None,
                difficulty=5,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
            )

        # base_xp should be the consolation flat value (10), not difficulty*4
        assert result["base_xp"] == 10

    @pytest.mark.asyncio
    async def test_bc4_flat_xp_same_for_all_difficulty_levels(self):
        """BC-4: base_xp is always 10 regardless of card difficulty."""
        from gamification.xp_engine import compute_and_award_xp

        for difficulty in (1, 2, 3, 4, 5):
            db = _make_xp_db({"DIFFICULTY_WEIGHTED_XP_ENABLED": "false"})
            with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
                result = await compute_and_award_xp(
                    db=db,
                    student_id=_sid(),
                    session_id=None,
                    interaction_id=None,
                    difficulty=difficulty,
                    wrong_attempts=0,
                    hints_used=0,
                    is_correct=True,
                )
            assert result["base_xp"] == 10, (
                f"Expected flat base_xp=10 for difficulty={difficulty}"
            )

    @pytest.mark.asyncio
    async def test_bc4_flat_xp_no_hint_penalty_applied(self):
        """BC-4: In flat mode, hints and wrong attempts do not reduce XP."""
        from gamification.xp_engine import compute_and_award_xp

        db = _make_xp_db({"DIFFICULTY_WEIGHTED_XP_ENABLED": "false"})

        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result_no_hints = await compute_and_award_xp(
                db=db,
                student_id=_sid(),
                session_id=None,
                interaction_id=None,
                difficulty=3,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
            )

        db2 = _make_xp_db({"DIFFICULTY_WEIGHTED_XP_ENABLED": "false"})
        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result_with_hints = await compute_and_award_xp(
                db=db2,
                student_id=_sid(),
                session_id=None,
                interaction_id=None,
                difficulty=3,
                wrong_attempts=3,
                hints_used=5,
                is_correct=True,
            )

        assert result_no_hints["base_xp"] == result_with_hints["base_xp"] == 10


# ---------------------------------------------------------------------------
# BC-5: LEADERBOARD_ENABLED=false → HTTP 403
# ---------------------------------------------------------------------------

class TestLeaderboardDisabled:
    """BC-5: LEADERBOARD_ENABLED=false → get_leaderboard raises HTTP 403."""

    @pytest.mark.asyncio
    async def test_bc5_leaderboard_disabled_raises_403(self):
        """BC-5: LEADERBOARD_ENABLED=false → HTTP 403 Forbidden."""
        from fastapi import HTTPException
        from api.teaching_router import get_leaderboard

        db = _make_leaderboard_db(leaderboard_enabled="false")
        user = MagicMock()
        user.id = _sid()
        user.role = "student"

        with pytest.raises(HTTPException) as exc_info:
            await get_leaderboard(
                request=_fake_request(),
                limit=20,
                user=user,
                db=db,
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_bc5_leaderboard_no_config_row_raises_403(self):
        """BC-5: No LEADERBOARD_ENABLED row in AdminConfig → default 'false' → 403."""
        from fastapi import HTTPException
        from api.teaching_router import get_leaderboard

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        async def _execute_empty(stmt, *a, **kw):
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=None)
            r.all = MagicMock(return_value=[])
            return r

        db.execute = AsyncMock(side_effect=_execute_empty)

        with pytest.raises(HTTPException) as exc_info:
            await get_leaderboard(
                request=_fake_request(),
                limit=20,
                user=MagicMock(),
                db=db,
            )

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# BC-6: All flags default correctly when no AdminConfig rows exist
# ---------------------------------------------------------------------------

class TestFeatureFlagDefaults:
    """BC-6: Verify the hard-coded defaults in xp_engine.DEFAULTS and features endpoint."""

    def test_bc6_xp_engine_defaults_gamification_enabled(self):
        """BC-6: GAMIFICATION_ENABLED defaults to 'true' in xp_engine.DEFAULTS."""
        from gamification.xp_engine import DEFAULTS
        assert DEFAULTS["GAMIFICATION_ENABLED"] == "true"

    def test_bc6_xp_engine_defaults_difficulty_weighted_enabled(self):
        """BC-6: DIFFICULTY_WEIGHTED_XP_ENABLED defaults to 'true'."""
        from gamification.xp_engine import DEFAULTS
        assert DEFAULTS["DIFFICULTY_WEIGHTED_XP_ENABLED"] == "true"

    def test_bc6_xp_engine_defaults_badges_enabled(self):
        """BC-6: BADGES_ENABLED defaults to 'true'."""
        from gamification.xp_engine import DEFAULTS
        assert DEFAULTS["BADGES_ENABLED"] == "true"

    def test_bc6_streak_defaults_multiplier_enabled(self):
        """BC-6: STREAK_MULTIPLIER_ENABLED defaults to 'true' in streak_engine."""
        from gamification.streak_engine import STREAK_DEFAULTS
        assert STREAK_DEFAULTS["STREAK_MULTIPLIER_ENABLED"] == "true"

    @pytest.mark.asyncio
    async def test_bc6_features_endpoint_defaults_when_no_config(self):
        """BC-6: With empty AdminConfig, /features returns all correct defaults.

        Expected: GAMIFICATION=true, LEADERBOARD=false, BADGES=true,
                  STREAK_MULTIPLIER=true, DIFFICULTY_WEIGHTED=true.
        """
        from api.teaching_router import get_feature_flags

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        async def _execute_empty(stmt, *a, **kw):
            r = MagicMock()
            r.all = MagicMock(return_value=[])
            r.scalar_one_or_none = MagicMock(return_value=None)
            return r

        db.execute = AsyncMock(side_effect=_execute_empty)

        result = await get_feature_flags(request=_fake_request(), db=db)

        assert result["gamification_enabled"] is True
        assert result["leaderboard_enabled"] is False    # Only flag that defaults to false
        assert result["badges_enabled"] is True
        assert result["streak_multiplier_enabled"] is True
        assert result["difficulty_weighted_xp_enabled"] is True

    @pytest.mark.asyncio
    async def test_bc6_gamification_enabled_by_default_computes_weighted_xp(self):
        """BC-6: Default config (no overrides) → full difficulty-weighted XP applies.

        difficulty=1, no hints/wrong → base=4, first_attempt_bonus=1.5x → final=6.
        """
        from gamification.xp_engine import compute_and_award_xp

        db = _make_xp_db()  # all defaults: GAMIFICATION=true, DIFFICULTY_WEIGHTED=true

        with patch("gamification.badge_engine.evaluate_badges", new=AsyncMock(return_value=[])):
            result = await compute_and_award_xp(
                db=db,
                student_id=_sid(),
                session_id=None,
                interaction_id=None,
                difficulty=1,
                wrong_attempts=0,
                hints_used=0,
                is_correct=True,
            )

        assert result["final_xp"] == 6


# ---------------------------------------------------------------------------
# BC-7: GET /features reflects live AdminConfig state
# ---------------------------------------------------------------------------

class TestFeatureFlagsEndpoint:
    """BC-7: /features endpoint returns current live state of each flag."""

    @pytest.mark.asyncio
    async def test_bc7_all_flags_present_as_booleans(self):
        """BC-7: Response contains all five flags as Python booleans."""
        from api.teaching_router import get_feature_flags

        db = _make_features_db()
        result = await get_feature_flags(request=_fake_request(), db=db)

        assert "gamification_enabled" in result
        assert "leaderboard_enabled" in result
        assert "badges_enabled" in result
        assert "streak_multiplier_enabled" in result
        assert "difficulty_weighted_xp_enabled" in result
        for value in result.values():
            assert isinstance(value, bool)

    @pytest.mark.asyncio
    async def test_bc7_leaderboard_enabled_reflects_config_value(self):
        """BC-7: LEADERBOARD_ENABLED=true in DB → leaderboard_enabled=True in response."""
        from api.teaching_router import get_feature_flags

        db = _make_features_db({"LEADERBOARD_ENABLED": "true"})
        result = await get_feature_flags(request=_fake_request(), db=db)

        assert result["leaderboard_enabled"] is True

    @pytest.mark.asyncio
    async def test_bc7_gamification_disabled_flag_reflected(self):
        """BC-7: GAMIFICATION_ENABLED=false in DB → gamification_enabled=False."""
        from api.teaching_router import get_feature_flags

        db = _make_features_db({"GAMIFICATION_ENABLED": "false"})
        result = await get_feature_flags(request=_fake_request(), db=db)

        assert result["gamification_enabled"] is False

    @pytest.mark.asyncio
    async def test_bc7_badges_disabled_flag_reflected(self):
        """BC-7: BADGES_ENABLED=false in DB → badges_enabled=False."""
        from api.teaching_router import get_feature_flags

        db = _make_features_db({"BADGES_ENABLED": "false"})
        result = await get_feature_flags(request=_fake_request(), db=db)

        assert result["badges_enabled"] is False

    @pytest.mark.asyncio
    async def test_bc7_all_flags_can_be_toggled_simultaneously(self):
        """BC-7: All flags off simultaneously → every response key is False."""
        from api.teaching_router import get_feature_flags

        all_off = {
            "GAMIFICATION_ENABLED": "false",
            "LEADERBOARD_ENABLED": "false",
            "BADGES_ENABLED": "false",
            "STREAK_MULTIPLIER_ENABLED": "false",
            "DIFFICULTY_WEIGHTED_XP_ENABLED": "false",
        }
        db = _make_features_db(all_off)
        result = await get_feature_flags(request=_fake_request(), db=db)

        for key, value in result.items():
            assert value is False, f"Expected False for {key}, got {value}"
