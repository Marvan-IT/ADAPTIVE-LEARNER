"""
test_student_analytics.py
Unit tests for XP constants, mastery threshold, AnalyticsSummary validation,
CardBehaviorSignals defaults, and LearningProfile constraints.

All tests are pure unit tests — no DB, no LLM.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from pydantic import ValidationError
from adaptive.schemas import (
    AnalyticsSummary,
    CardBehaviorSignals,
    LearningProfile,
)
from adaptive.adaptive_engine import (
    blended_score_to_generate_as,
    compute_numeric_state_score,
)
from config import (
    XP_MASTERY,
    XP_MASTERY_BONUS,
    XP_CONSOLATION,
    MASTERY_THRESHOLD,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_analytics(
    time_spent: float = 120.0,
    expected_time: float = 120.0,
    attempts: int = 1,
    wrong_attempts: int = 0,
    hints_used: int = 0,
    revisits: int = 0,
    recent_dropoffs: int = 0,
    skip_rate: float = 0.0,
    quiz_score: float = 0.8,
    last_7d_sessions: int = 3,
) -> AnalyticsSummary:
    return AnalyticsSummary(
        student_id="student-1",
        concept_id="PREALG.C1.S1",
        time_spent_sec=time_spent,
        expected_time_sec=expected_time,
        attempts=attempts,
        wrong_attempts=wrong_attempts,
        hints_used=hints_used,
        revisits=revisits,
        recent_dropoffs=recent_dropoffs,
        skip_rate=skip_rate,
        quiz_score=quiz_score,
        last_7d_sessions=last_7d_sessions,
    )


# ── Tests: XP and mastery constants ──────────────────────────────────────────

class TestConstants:
    """Verify that XP and mastery constants match expected values from config."""

    def test_xp_mastery_equals_50(self):
        """Business: XP_MASTERY = 50 — base XP awarded on concept mastery."""
        assert XP_MASTERY == 50

    def test_xp_mastery_bonus_equals_25(self):
        """Business: XP_MASTERY_BONUS = 25 — bonus XP for high-score mastery."""
        assert XP_MASTERY_BONUS == 25

    def test_xp_consolation_equals_10(self):
        """Business: XP_CONSOLATION = 10 — consolation XP when session ends without mastery."""
        assert XP_CONSOLATION == 10

    def test_mastery_threshold_equals_70(self):
        """Business: MASTERY_THRESHOLD = 70 — score out of 100 to mark a concept as mastered."""
        assert MASTERY_THRESHOLD == 70


# ── Tests: mastery determination ─────────────────────────────────────────────

class TestMasteryDetermination:
    """Verify mastery is awarded based on check score vs MASTERY_THRESHOLD."""

    def test_check_score_at_threshold_grants_mastery(self):
        """check_score >= 70 → concept_mastered = True."""
        check_score = 70
        mastered = check_score >= MASTERY_THRESHOLD
        assert mastered is True

    def test_check_score_above_threshold_grants_mastery(self):
        """check_score = 85 → concept_mastered = True."""
        check_score = 85
        mastered = check_score >= MASTERY_THRESHOLD
        assert mastered is True

    def test_check_score_below_threshold_denies_mastery(self):
        """check_score = 69 → concept_mastered = False."""
        check_score = 69
        mastered = check_score >= MASTERY_THRESHOLD
        assert mastered is False

    def test_check_score_zero_denies_mastery(self):
        """check_score = 0 → concept_mastered = False."""
        mastered = 0 >= MASTERY_THRESHOLD
        assert mastered is False


# ── Tests: blended_score_to_generate_as boundary precision ───────────────────

class TestBlendedScoreBoundaries:
    """Verify exact boundary behavior of blended_score_to_generate_as."""

    def test_score_exactly_1_7_returns_normal(self):
        """1.7 is not < 1.7 and not >= 2.5 → NORMAL."""
        assert blended_score_to_generate_as(1.7) == "NORMAL"

    def test_score_exactly_2_5_returns_fast(self):
        """2.5 >= 2.5 → FAST."""
        assert blended_score_to_generate_as(2.5) == "FAST"

    def test_score_1_699_returns_struggling(self):
        """1.699 < 1.7 → STRUGGLING."""
        assert blended_score_to_generate_as(1.699) == "STRUGGLING"

    def test_score_2_499_returns_normal(self):
        """2.499 < 2.5 and >= 1.7 → NORMAL."""
        assert blended_score_to_generate_as(2.499) == "NORMAL"


# ── Tests: AnalyticsSummary validation ───────────────────────────────────────

class TestAnalyticsSummaryValidation:
    """Verify model_validator and field constraints on AnalyticsSummary."""

    def test_wrong_attempts_exceeding_attempts_raises_validation_error(self):
        """
        Business: wrong_attempts must never exceed total attempts.
        Having wrong_attempts > attempts is a data integrity violation.
        """
        with pytest.raises(ValidationError) as exc_info:
            AnalyticsSummary(
                student_id="s",
                concept_id="c",
                time_spent_sec=100.0,
                expected_time_sec=120.0,
                attempts=2,
                wrong_attempts=3,  # wrong_attempts > attempts: invalid
                hints_used=0,
                revisits=0,
                recent_dropoffs=0,
                skip_rate=0.0,
                quiz_score=0.5,
                last_7d_sessions=1,
            )
        assert "wrong_attempts" in str(exc_info.value).lower() or "attempts" in str(exc_info.value).lower()

    def test_wrong_attempts_equal_to_attempts_is_valid(self):
        """wrong_attempts == attempts is a valid edge case (all attempts were wrong)."""
        analytics = _make_analytics(attempts=3, wrong_attempts=3)
        assert analytics.wrong_attempts == analytics.attempts

    def test_quiz_score_out_of_range_raises_validation_error(self):
        """quiz_score must be in [0.0, 1.0]."""
        with pytest.raises(ValidationError):
            AnalyticsSummary(
                student_id="s",
                concept_id="c",
                time_spent_sec=100.0,
                expected_time_sec=120.0,
                attempts=1,
                wrong_attempts=0,
                hints_used=0,
                revisits=0,
                recent_dropoffs=0,
                skip_rate=0.0,
                quiz_score=1.5,  # out of [0, 1]
                last_7d_sessions=1,
            )

    def test_skip_rate_out_of_range_raises_validation_error(self):
        """skip_rate must be in [0.0, 1.0]."""
        with pytest.raises(ValidationError):
            AnalyticsSummary(
                student_id="s",
                concept_id="c",
                time_spent_sec=100.0,
                expected_time_sec=120.0,
                attempts=1,
                wrong_attempts=0,
                hints_used=0,
                revisits=0,
                recent_dropoffs=0,
                skip_rate=1.5,  # > 1.0 invalid
                quiz_score=0.8,
                last_7d_sessions=1,
            )

    def test_missing_required_field_raises_validation_error(self):
        """Omitting required field (e.g., quiz_score) raises ValidationError."""
        with pytest.raises(ValidationError):
            AnalyticsSummary(
                student_id="s",
                concept_id="c",
                time_spent_sec=100.0,
                expected_time_sec=120.0,
                attempts=1,
                wrong_attempts=0,
                hints_used=0,
                revisits=0,
                recent_dropoffs=0,
                skip_rate=0.0,
                # quiz_score missing
                last_7d_sessions=1,
            )


# ── Tests: CardBehaviorSignals defaults ─────────────────────────────────────

class TestCardBehaviorSignalsDefaults:
    """Verify default values in CardBehaviorSignals."""

    def test_all_default_values_are_zero_or_none(self):
        """
        Business: CardBehaviorSignals with only card_index provided
        should have all other fields defaulting to safe zero/None values.
        """
        signals = CardBehaviorSignals(card_index=5)
        assert signals.time_on_card_sec == 0.0
        assert signals.wrong_attempts == 0
        assert signals.selected_wrong_option is None
        assert signals.hints_used == 0
        assert signals.idle_triggers == 0
        assert signals.difficulty_bias is None
        assert signals.engagement_signal is None

    def test_difficulty_bias_valid_values_accepted(self):
        """difficulty_bias accepts TOO_EASY, TOO_HARD, and None."""
        for val in ("TOO_EASY", "TOO_HARD", None):
            s = CardBehaviorSignals(card_index=0, difficulty_bias=val)
            assert s.difficulty_bias == val


# ── Tests: LearningProfile constraints ───────────────────────────────────────

class TestLearningProfileConstraints:
    """Verify LearningProfile field constraints."""

    def _make_profile(
        self,
        speed: str = "NORMAL",
        comprehension: str = "OK",
        engagement: str = "ENGAGED",
        confidence_score: float = 0.7,
        recommended_next_step: str = "CONTINUE",
        error_rate: float = 0.1,
    ) -> LearningProfile:
        return LearningProfile(
            speed=speed,
            comprehension=comprehension,
            engagement=engagement,
            confidence_score=confidence_score,
            recommended_next_step=recommended_next_step,
            error_rate=error_rate,
        )

    def test_slow_speed_recommended_next_step_is_not_challenge(self):
        """
        Business: A SLOW learner should not receive a CHALLENGE recommendation
        (that would be pedagogically inappropriate).
        """
        from adaptive.profile_builder import build_learning_profile
        analytics = _make_analytics(
            time_spent=300.0,
            expected_time=100.0,  # very slow
            attempts=3,
            wrong_attempts=2,
            quiz_score=0.3,
        )
        profile = build_learning_profile(analytics, has_unmet_prereq=False)
        assert profile.speed == "SLOW"
        assert profile.recommended_next_step != "CHALLENGE"

    def test_all_9_state_combinations_produce_valid_numeric_scores(self):
        """
        Business: compute_numeric_state_score for all (speed × comprehension)
        combinations produces scores in [1.0, 3.0].
        """
        speeds = ["SLOW", "NORMAL", "FAST"]
        comprehensions = ["STRUGGLING", "OK", "STRONG"]
        for speed in speeds:
            for comp in comprehensions:
                score = compute_numeric_state_score(speed, comp)
                assert 1.0 <= score <= 3.0, (
                    f"compute_numeric_state_score({speed!r}, {comp!r}) = {score}"
                )
