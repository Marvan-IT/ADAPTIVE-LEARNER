"""
test_gamification_endpoints.py

Handler-level tests for gamification endpoints in teaching_router.py.
The tests call handler functions directly with mocked DB sessions and
mocked gamification engines — this avoids the circular import from
api.main and the ChromaDB/PostgreSQL lifespan requirements.

Business criteria covered
--------------------------
BC-1  POST record-interaction, is_correct=True, difficulty=3
      → response includes xp_awarded with non-zero final_xp
BC-2  POST record-interaction, is_correct=False
      → xp_awarded is zeroed out (base=0, multiplier=1.0, final=0)
BC-3  POST record-interaction, is_correct=True, difficulty=None
      → XP engine not called; xp_awarded final_xp is 0
BC-4  GET badges returns list of earned badges ordered newest-first
BC-5  GET leaderboard returns ranked list when LEADERBOARD_ENABLED=true
BC-6  GET leaderboard returns HTTP 403 when LEADERBOARD_ENABLED is not 'true'
BC-7  GET progress-report (admin) returns aggregated XP totals and accuracy
BC-8  GET /features returns all five feature flags as booleans

Run: pytest backend/tests/test_gamification_endpoints.py -v
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request as StarletteRequest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _sid() -> uuid.UUID:
    return uuid.uuid4()


def _make_user(role: str = "admin") -> MagicMock:
    """Return a minimal auth.models.User stub."""
    user = MagicMock()
    user.id = _sid()
    user.role = role
    return user


def _make_session(student_id: uuid.UUID | None = None) -> MagicMock:
    """Return a minimal TeachingSession stub."""
    sess = MagicMock()
    sess.id = _sid()
    sess.student_id = student_id or _sid()
    sess.concept_id = "prealgebra_1.1"
    return sess


def _make_student(student_id: uuid.UUID | None = None, xp: int = 0) -> MagicMock:
    """Return a minimal Student stub."""
    s = MagicMock()
    s.id = student_id or _sid()
    s.display_name = "Alice"
    s.xp = xp
    s.daily_streak = 0
    s.daily_streak_best = 0
    s.user_id = _sid()
    return s


def _make_badge(badge_key: str = "first_correct") -> MagicMock:
    b = MagicMock()
    b.badge_key = badge_key
    b.awarded_at = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
    b.metadata_ = {"trigger": "card_correct"}
    return b


# ---------------------------------------------------------------------------
# Shared DB mock used by endpoint handler tests
# ---------------------------------------------------------------------------

def _make_db(
    session: MagicMock | None = None,
    student: MagicMock | None = None,
    badges: list | None = None,
    leaderboard_enabled: str = "true",
    feature_flags: dict | None = None,
) -> AsyncMock:
    """
    Build a minimal AsyncSession mock that can service multiple query patterns
    used by the gamification endpoint handlers.
    """
    sess_obj = session or _make_session()
    stu_obj = student or _make_student(student_id=sess_obj.student_id)
    badge_list = badges if badges is not None else []

    db = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()

    default_flags = {
        "GAMIFICATION_ENABLED": "true",
        "LEADERBOARD_ENABLED": leaderboard_enabled,
        "BADGES_ENABLED": "true",
        "STREAK_MULTIPLIER_ENABLED": "true",
        "DIFFICULTY_WEIGHTED_XP_ENABLED": "true",
    }
    if feature_flags:
        default_flags.update(feature_flags)

    async def _get(model_class, pk):
        from db.models import TeachingSession, Student
        if model_class is TeachingSession:
            return sess_obj if str(pk) == str(sess_obj.id) else None
        if model_class is Student:
            return stu_obj if str(pk) == str(stu_obj.id) else None
        return None

    db.get = AsyncMock(side_effect=_get)

    async def _execute(stmt, *args, **kwargs):
        stmt_str = str(stmt)
        r = MagicMock()

        # AdminConfig / feature flag query
        if "admin_config" in stmt_str.lower() or "adminconfig" in stmt_str:
            # Extract the config key from the whereclause bind parameter
            requested_key = None
            try:
                clause = stmt.whereclause
                if hasattr(clause, "right") and hasattr(clause.right, "value"):
                    requested_key = clause.right.value
            except Exception:
                pass
            # Multi-key IN query (features endpoint) — requested_key is a list
            if isinstance(requested_key, list):
                pairs = [(k, v) for k, v in default_flags.items() if k in requested_key]
                r.all = MagicMock(return_value=pairs)
                r.scalar_one_or_none = MagicMock(return_value=None)
                return r
            # Single-key lookup
            if requested_key and requested_key in default_flags:
                r.scalar_one_or_none = MagicMock(return_value=default_flags[requested_key])
                return r
            # Fallback — return all flags for any unrecognized admin_config query
            r.all = MagicMock(return_value=list(default_flags.items()))
            r.scalar_one_or_none = MagicMock(return_value=None)
            return r

        # StudentBadge query
        if "student_badges" in stmt_str.lower() or "studentbadge" in stmt_str:
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=badge_list)))
            r.all = MagicMock(return_value=[(b.student_id if hasattr(b, "student_id") else _sid(), 1) for b in badge_list])
            return r

        # Leaderboard student XP query
        if "students" in stmt_str.lower():
            r.scalar_one_or_none = MagicMock(return_value=stu_obj)
            r.all = MagicMock(return_value=[
                (stu_obj.id, stu_obj.display_name, stu_obj.xp)
            ])
            r.scalar = MagicMock(return_value=0)
            return r

        r.scalar_one_or_none = MagicMock(return_value=None)
        r.scalar = MagicMock(return_value=0)
        r.all = MagicMock(return_value=[])
        r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        return r

    db.execute = AsyncMock(side_effect=_execute)
    return db


# ---------------------------------------------------------------------------
# BC-1: record-interaction, correct + difficulty → XP awarded
# ---------------------------------------------------------------------------

class TestRecordInteractionXpAwarded:
    """BC-1: Correct answer with difficulty level → xp_awarded populated."""

    @pytest.mark.asyncio
    async def test_bc1_correct_answer_with_difficulty_returns_xp(self):
        """BC-1: is_correct=True, difficulty=3 → xp_awarded.final_xp > 0."""
        from api.teaching_router import record_card_interaction, RecordInteractionRequest

        session_obj = _make_session()
        user = _make_user(role="admin")
        db = _make_db(session=session_obj)

        req = RecordInteractionRequest(
            card_index=0,
            time_on_card_sec=25.0,
            wrong_attempts=0,
            hints_used=0,
            is_correct=True,
            difficulty=3,
        )

        fake_xp_result = {
            "base_xp": 12,
            "multiplier": 1.5,
            "final_xp": 18,
            "new_badges": [],
        }

        with patch("api.teaching_router._validate_student_ownership", new=AsyncMock(return_value=None)):
            with patch("gamification.xp_engine.compute_and_award_xp", new=AsyncMock(return_value=fake_xp_result)):
                result = await record_card_interaction(
                    request=_fake_request(),
                    session_id=session_obj.id,
                    req=req,
                    user=user,
                    db=db,
                )

        assert result["saved"] is True
        assert result["xp_awarded"]["final_xp"] == 18
        assert result["xp_awarded"]["base_xp"] == 12
        assert result["xp_awarded"]["multiplier"] == 1.5

    @pytest.mark.asyncio
    async def test_bc1_new_badges_returned_in_response(self):
        """BC-1: Newly earned badges surface in the response new_badges list."""
        from api.teaching_router import record_card_interaction, RecordInteractionRequest

        session_obj = _make_session()
        user = _make_user(role="admin")
        db = _make_db(session=session_obj)

        req = RecordInteractionRequest(
            card_index=1,
            is_correct=True,
            difficulty=2,
        )
        fake_xp_result = {
            "base_xp": 8,
            "multiplier": 1.0,
            "final_xp": 8,
            "new_badges": [{"badge_key": "first_correct", "name_key": "badge.first_correct"}],
        }

        with patch("api.teaching_router._validate_student_ownership", new=AsyncMock(return_value=None)):
            with patch("gamification.xp_engine.compute_and_award_xp", new=AsyncMock(return_value=fake_xp_result)):
                result = await record_card_interaction(
                    request=_fake_request(),
                    session_id=session_obj.id,
                    req=req,
                    user=user,
                    db=db,
                )

        assert result["new_badges"] == [{"badge_key": "first_correct", "name_key": "badge.first_correct"}]


# ---------------------------------------------------------------------------
# BC-2: record-interaction, wrong answer → no XP
# ---------------------------------------------------------------------------

class TestRecordInteractionNoXpOnWrong:
    """BC-2: Incorrect answer → xp_awarded is all zeros."""

    @pytest.mark.asyncio
    async def test_bc2_wrong_answer_xp_awarded_is_zero(self):
        """BC-2: is_correct=False → xp_awarded zeros; XP engine not called."""
        from api.teaching_router import record_card_interaction, RecordInteractionRequest

        session_obj = _make_session()
        user = _make_user(role="admin")
        db = _make_db(session=session_obj)

        req = RecordInteractionRequest(
            card_index=2,
            wrong_attempts=2,
            is_correct=False,
            difficulty=3,
        )

        mock_xp_engine = AsyncMock()

        with patch("api.teaching_router._validate_student_ownership", new=AsyncMock(return_value=None)):
            with patch("gamification.xp_engine.compute_and_award_xp", new=mock_xp_engine):
                result = await record_card_interaction(
                    request=_fake_request(),
                    session_id=session_obj.id,
                    req=req,
                    user=user,
                    db=db,
                )

        # XP engine should NOT be called for wrong answers
        mock_xp_engine.assert_not_called()

        assert result["saved"] is True
        assert result["xp_awarded"]["final_xp"] == 0
        assert result["xp_awarded"]["base_xp"] == 0
        assert result["xp_awarded"]["multiplier"] == 1.0

    @pytest.mark.asyncio
    async def test_bc2_wrong_answer_no_new_badges(self):
        """BC-2: Incorrect answer → empty new_badges list."""
        from api.teaching_router import record_card_interaction, RecordInteractionRequest

        session_obj = _make_session()
        db = _make_db(session=session_obj)
        req = RecordInteractionRequest(card_index=0, is_correct=False, difficulty=4)

        with patch("api.teaching_router._validate_student_ownership", new=AsyncMock(return_value=None)):
            with patch("gamification.xp_engine.compute_and_award_xp", new=AsyncMock()):
                result = await record_card_interaction(
                    request=_fake_request(),
                    session_id=session_obj.id,
                    req=req,
                    user=_make_user(role="admin"),
                    db=db,
                )

        assert result["new_badges"] == []


# ---------------------------------------------------------------------------
# BC-3: record-interaction, correct=True but difficulty=None → no XP call
# ---------------------------------------------------------------------------

class TestRecordInteractionMissingDifficulty:
    """BC-3: correct=True but no difficulty provided → XP engine not called."""

    @pytest.mark.asyncio
    async def test_bc3_missing_difficulty_skips_xp_engine(self):
        """BC-3: difficulty=None → compute_and_award_xp not invoked; final_xp=0."""
        from api.teaching_router import record_card_interaction, RecordInteractionRequest

        session_obj = _make_session()
        db = _make_db(session=session_obj)
        req = RecordInteractionRequest(
            card_index=0,
            is_correct=True,
            difficulty=None,  # deliberately missing
        )

        mock_xp_engine = AsyncMock()

        with patch("api.teaching_router._validate_student_ownership", new=AsyncMock(return_value=None)):
            with patch("gamification.xp_engine.compute_and_award_xp", new=mock_xp_engine):
                result = await record_card_interaction(
                    request=_fake_request(),
                    session_id=session_obj.id,
                    req=req,
                    user=_make_user(role="admin"),
                    db=db,
                )

        mock_xp_engine.assert_not_called()
        assert result["xp_awarded"]["final_xp"] == 0

    @pytest.mark.asyncio
    async def test_bc3_saved_is_true_despite_no_xp(self):
        """BC-3: Interaction row is still saved even without XP calculation."""
        from api.teaching_router import record_card_interaction, RecordInteractionRequest

        session_obj = _make_session()
        db = _make_db(session=session_obj)
        req = RecordInteractionRequest(card_index=1, is_correct=True, difficulty=None)

        with patch("api.teaching_router._validate_student_ownership", new=AsyncMock(return_value=None)):
            with patch("gamification.xp_engine.compute_and_award_xp", new=AsyncMock()):
                result = await record_card_interaction(
                    request=_fake_request(),
                    session_id=session_obj.id,
                    req=req,
                    user=_make_user(role="admin"),
                    db=db,
                )

        assert result["saved"] is True


# ---------------------------------------------------------------------------
# BC-4: GET badges returns ordered badge list
# ---------------------------------------------------------------------------

class TestGetStudentBadges:
    """BC-4: Badges endpoint returns list of earned badges, newest first."""

    @pytest.mark.asyncio
    async def test_bc4_returns_badge_list(self):
        """BC-4: Two earned badges → response has two items with badge_key and awarded_at."""
        from api.teaching_router import get_student_badges

        student_id = _sid()
        b1 = _make_badge("first_correct")
        b1.awarded_at = datetime(2026, 4, 13, 10, 0, 0, tzinfo=timezone.utc)
        b1.metadata_ = {}
        b2 = _make_badge("streak_3")
        b2.awarded_at = datetime(2026, 4, 13, 11, 0, 0, tzinfo=timezone.utc)
        b2.metadata_ = {}

        db = _make_db(student=_make_student(student_id=student_id), badges=[b2, b1])

        with patch("api.teaching_router._validate_student_ownership", new=AsyncMock(return_value=None)):
            result = await get_student_badges(
                request=_fake_request(),
                student_id=student_id,
                user=_make_user(role="admin"),
                db=db,
            )

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["badge_key"] == "streak_3"
        assert result[1]["badge_key"] == "first_correct"
        assert "awarded_at" in result[0]

    @pytest.mark.asyncio
    async def test_bc4_empty_badge_list_when_none_earned(self):
        """BC-4: Student with no badges → empty list returned."""
        from api.teaching_router import get_student_badges

        student_id = _sid()
        db = _make_db(student=_make_student(student_id=student_id), badges=[])

        with patch("api.teaching_router._validate_student_ownership", new=AsyncMock(return_value=None)):
            result = await get_student_badges(
                request=_fake_request(),
                student_id=student_id,
                user=_make_user(role="admin"),
                db=db,
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_bc4_badge_response_contains_metadata_key(self):
        """BC-4: Each badge dict must include the 'metadata' key."""
        from api.teaching_router import get_student_badges

        student_id = _sid()
        b = _make_badge("speed_demon")
        b.awarded_at = datetime(2026, 4, 13, tzinfo=timezone.utc)
        b.metadata_ = {"trigger": "card_correct"}
        db = _make_db(student=_make_student(student_id=student_id), badges=[b])

        with patch("api.teaching_router._validate_student_ownership", new=AsyncMock(return_value=None)):
            result = await get_student_badges(
                request=_fake_request(),
                student_id=student_id,
                user=_make_user(role="admin"),
                db=db,
            )

        assert "metadata" in result[0]


# ---------------------------------------------------------------------------
# BC-5 & BC-6: GET leaderboard
# ---------------------------------------------------------------------------

class TestGetLeaderboard:
    """BC-5 / BC-6: Leaderboard returns ranked list when enabled; 403 when disabled."""

    @pytest.mark.asyncio
    async def test_bc5_leaderboard_enabled_returns_ranked_list(self):
        """BC-5: LEADERBOARD_ENABLED=true → ranked leaderboard dict returned."""
        from api.teaching_router import get_leaderboard

        student = _make_student(xp=200)
        student.user_id = _sid()
        db = _make_db(student=student, leaderboard_enabled="true")
        user = _make_user(role="student")
        user.id = student.user_id

        result = await get_leaderboard(
            request=_fake_request(),
            limit=20,
            user=user,
            db=db,
        )

        assert "leaderboard" in result
        assert isinstance(result["leaderboard"], list)
        assert len(result["leaderboard"]) >= 1
        entry = result["leaderboard"][0]
        assert "rank" in entry
        assert "xp" in entry
        assert "level" in entry
        assert "badge_count" in entry

    @pytest.mark.asyncio
    async def test_bc5_leaderboard_level_computed_correctly(self):
        """BC-5: level = (xp // 100) + 1; xp=200 → level=3."""
        from api.teaching_router import get_leaderboard

        student = _make_student(xp=200)
        student.user_id = _sid()
        db = _make_db(student=student, leaderboard_enabled="true")
        user = _make_user(role="student")
        user.id = student.user_id

        result = await get_leaderboard(request=_fake_request(), limit=20, user=user, db=db)
        assert result["leaderboard"][0]["level"] == 3

    @pytest.mark.asyncio
    async def test_bc6_leaderboard_disabled_raises_403(self):
        """BC-6: LEADERBOARD_ENABLED != 'true' → HTTP 403."""
        from fastapi import HTTPException
        from api.teaching_router import get_leaderboard

        db = _make_db(leaderboard_enabled="false")

        with pytest.raises(HTTPException) as exc_info:
            await get_leaderboard(
                request=_fake_request(),
                limit=20,
                user=_make_user(),
                db=db,
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_bc6_leaderboard_missing_config_also_raises_403(self):
        """BC-6: No LEADERBOARD_ENABLED row (defaults to 'false') → 403."""
        from fastapi import HTTPException
        from api.teaching_router import get_leaderboard

        # Simulate no AdminConfig row by returning None for the key
        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()

        async def _execute(stmt, *a, **kw):
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=None)  # key missing → None
            r.all = MagicMock(return_value=[])
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            return r

        db.execute = AsyncMock(side_effect=_execute)

        with pytest.raises(HTTPException) as exc_info:
            await get_leaderboard(
                request=_fake_request(),
                limit=20,
                user=_make_user(),
                db=db,
            )

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# BC-7: GET progress-report (admin router)
# ---------------------------------------------------------------------------

class TestGetProgressReport:
    """BC-7: progress-report returns aggregated XP, accuracy, mastery count, badges."""

    def _make_admin_db(
        self,
        student: MagicMock | None = None,
        total_xp: int = 150,
        correct_count: int = 8,
        total_int: int = 10,
        concepts_mastered: int = 3,
        badges: list | None = None,
    ) -> AsyncMock:
        stu = student or _make_student()
        daily_xp_rows: list = []
        type_rows: list = [("card_correct", total_xp)]
        badge_list = badges or []

        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()

        async def _get(model_class, pk):
            from db.models import Student
            if model_class is Student:
                return stu
            return None

        db.get = AsyncMock(side_effect=_get)

        call_count = [0]

        async def _execute(stmt, *a, **kw):
            call_count[0] += 1
            r = MagicMock()
            stmt_str = str(stmt)

            if "student_badges" in stmt_str.lower() or "studentbadge" in stmt_str:
                r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=badge_list)))
                return r

            # Return scalar results in the order they're called
            n = call_count[0]
            if n == 1:
                # total_xp query
                r.scalar = MagicMock(return_value=total_xp)
            elif n == 2:
                # daily_xp breakdown
                r.all = MagicMock(return_value=daily_xp_rows)
            elif n == 3:
                # xp_by_type
                r.all = MagicMock(return_value=type_rows)
            elif n == 4:
                # concepts mastered count
                r.scalar = MagicMock(return_value=concepts_mastered)
            elif n == 5:
                # correct card count
                r.scalar = MagicMock(return_value=correct_count)
            elif n == 6:
                # total interaction count
                r.scalar = MagicMock(return_value=total_int)
            else:
                r.scalar = MagicMock(return_value=0)
                r.all = MagicMock(return_value=[])
                r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

            return r

        db.execute = AsyncMock(side_effect=_execute)
        return db

    @pytest.mark.asyncio
    async def test_bc7_progress_report_returns_total_xp(self):
        """BC-7: progress-report returns total_xp summed over the period."""
        from api.admin_router import get_progress_report

        student_id = _sid()
        stu = _make_student(student_id=student_id)
        db = self._make_admin_db(student=stu, total_xp=150)

        result = await get_progress_report(
            student_id=student_id,
            period="week",
            _user=_make_user(role="admin"),
            db=db,
        )

        assert result["total_xp"] == 150

    @pytest.mark.asyncio
    async def test_bc7_progress_report_returns_accuracy_rate(self):
        """BC-7: accuracy_rate = correct_count / total_interactions."""
        from api.admin_router import get_progress_report

        student_id = _sid()
        stu = _make_student(student_id=student_id)
        db = self._make_admin_db(student=stu, correct_count=8, total_int=10)

        result = await get_progress_report(
            student_id=student_id,
            period="week",
            _user=_make_user(role="admin"),
            db=db,
        )

        assert result["accuracy_rate"] == 0.8

    @pytest.mark.asyncio
    async def test_bc7_progress_report_returns_concepts_mastered(self):
        """BC-7: concepts_mastered count is populated from StudentMastery query."""
        from api.admin_router import get_progress_report

        student_id = _sid()
        stu = _make_student(student_id=student_id)
        db = self._make_admin_db(student=stu, concepts_mastered=3)

        result = await get_progress_report(
            student_id=student_id,
            period="week",
            _user=_make_user(role="admin"),
            db=db,
        )

        assert result["concepts_mastered"] == 3

    @pytest.mark.asyncio
    async def test_bc7_invalid_period_raises_400(self):
        """BC-7: period='invalid' → HTTP 400."""
        from fastapi import HTTPException
        from api.admin_router import get_progress_report

        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_progress_report(
                student_id=_sid(),
                period="invalid",
                _user=_make_user(role="admin"),
                db=db,
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_bc7_unknown_student_raises_404(self):
        """BC-7: Student not found → HTTP 404."""
        from fastapi import HTTPException
        from api.admin_router import get_progress_report

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_progress_report(
                student_id=_sid(),
                period="week",
                _user=_make_user(role="admin"),
                db=db,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_bc7_zero_interactions_accuracy_is_zero(self):
        """BC-7: No interactions in period → accuracy_rate = 0.0 (no ZeroDivisionError)."""
        from api.admin_router import get_progress_report

        student_id = _sid()
        stu = _make_student(student_id=student_id)
        db = self._make_admin_db(student=stu, correct_count=0, total_int=0)

        result = await get_progress_report(
            student_id=student_id,
            period="week",
            _user=_make_user(role="admin"),
            db=db,
        )

        assert result["accuracy_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_bc7_all_period_values_are_accepted(self):
        """BC-7: All valid period values (day/week/month/all) are accepted without error."""
        from api.admin_router import get_progress_report

        for period in ("day", "week", "month", "all"):
            student_id = _sid()
            stu = _make_student(student_id=student_id)
            db = self._make_admin_db(student=stu)
            result = await get_progress_report(
                student_id=student_id,
                period=period,
                _user=_make_user(role="admin"),
                db=db,
            )
            assert result["period"] == period, f"period={period} not reflected in response"


# ---------------------------------------------------------------------------
# BC-8: GET /features returns all feature flag booleans
# ---------------------------------------------------------------------------

class TestGetFeatureFlags:
    """BC-8: /features endpoint returns all five flags as booleans."""

    @pytest.mark.asyncio
    async def test_bc8_all_flags_returned_as_booleans(self):
        """BC-8: All five feature flags present in response as True/False."""
        from api.teaching_router import get_feature_flags

        db = _make_db()

        result = await get_feature_flags(request=_fake_request(), db=db)

        expected_keys = {
            "gamification_enabled",
            "leaderboard_enabled",
            "badges_enabled",
            "streak_multiplier_enabled",
            "difficulty_weighted_xp_enabled",
        }
        assert set(result.keys()) == expected_keys
        for key, value in result.items():
            assert isinstance(value, bool), f"{key} should be bool, got {type(value)}"

    @pytest.mark.asyncio
    async def test_bc8_defaults_when_no_config_rows(self):
        """BC-8: When AdminConfig table is empty, default values are used.

        Defaults: GAMIFICATION=true, LEADERBOARD=false, BADGES=true,
                  STREAK_MULTIPLIER=true, DIFFICULTY_WEIGHTED=true.
        """
        from api.teaching_router import get_feature_flags

        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()

        async def _execute_empty(stmt, *a, **kw):
            r = MagicMock()
            r.all = MagicMock(return_value=[])  # No rows in admin_config
            r.scalar_one_or_none = MagicMock(return_value=None)
            return r

        db.execute = AsyncMock(side_effect=_execute_empty)

        result = await get_feature_flags(request=_fake_request(), db=db)

        assert result["gamification_enabled"] is True
        assert result["leaderboard_enabled"] is False
        assert result["badges_enabled"] is True
        assert result["streak_multiplier_enabled"] is True
        assert result["difficulty_weighted_xp_enabled"] is True

    @pytest.mark.asyncio
    async def test_bc8_admin_config_overrides_defaults(self):
        """BC-8: AdminConfig row with LEADERBOARD_ENABLED=true overrides the default false."""
        from api.teaching_router import get_feature_flags

        db = _make_db(leaderboard_enabled="true")

        result = await get_feature_flags(request=_fake_request(), db=db)

        assert result["leaderboard_enabled"] is True
