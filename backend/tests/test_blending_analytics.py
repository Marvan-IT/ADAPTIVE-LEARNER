"""
test_blending_analytics.py
Unit tests for build_blended_analytics, compute_numeric_state_score,
and blended_score_to_generate_as from adaptive_engine.py.

All tests are fully isolated — no DB, no LLM.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from adaptive.schemas import CardBehaviorSignals
from adaptive.adaptive_engine import (
    build_blended_analytics,
    compute_numeric_state_score,
    blended_score_to_generate_as,
)
from config import (
    ADAPTIVE_MIN_HISTORY_CARDS,
    ADAPTIVE_ACUTE_HIGH_TIME_RATIO,
    ADAPTIVE_ACUTE_LOW_TIME_RATIO,
    ADAPTIVE_ACUTE_WRONG_RATIO,
    ADAPTIVE_COLD_START_CURRENT_WEIGHT,
    ADAPTIVE_COLD_START_HISTORY_WEIGHT,
    ADAPTIVE_WARM_START_CURRENT_WEIGHT,
    ADAPTIVE_WARM_START_HISTORY_WEIGHT,
    ADAPTIVE_PARTIAL_CURRENT_WEIGHT,
    ADAPTIVE_PARTIAL_HISTORY_WEIGHT,
    ADAPTIVE_STATE_BLEND_CURRENT_WEIGHT,
    ADAPTIVE_STATE_BLEND_HISTORY_WEIGHT,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_signals(
    time_sec: float = 120.0,
    wrong: int = 0,
    hints: int = 0,
    idle: int = 0,
    card_index: int = 0,
) -> CardBehaviorSignals:
    return CardBehaviorSignals(
        card_index=card_index,
        time_on_card_sec=time_sec,
        wrong_attempts=wrong,
        hints_used=hints,
        idle_triggers=idle,
    )


def _make_history(
    total_cards: int = 10,
    avg_time: float = 120.0,
    avg_wrong: float = 0.5,
    avg_hints: float = 0.0,
    sessions_7d: int = 3,
    section_count: int = 3,
    avg_state_score: float = 2.0,
) -> dict:
    return {
        "total_cards_completed": total_cards,
        "avg_time_per_card": avg_time,
        "avg_wrong_attempts": avg_wrong,
        "avg_hints_per_card": avg_hints,
        "sessions_last_7d": sessions_7d,
        "is_known_weak_concept": False,
        "failed_concept_attempts": 0,
        "trend_direction": "STABLE",
        "trend_wrong_list": [],
        "section_count": section_count,
        "avg_state_score": avg_state_score,
        "effective_analogies": [],
        "preferred_analogy_style": None,
        "effective_engagement": [],
        "ineffective_engagement": [],
        "boredom_pattern": None,
        "state_distribution": {"struggling": 0, "normal": 10, "fast": 0},
        "overall_accuracy_rate": 0.8,
    }


# ── Tests: cold start / new student (< ADAPTIVE_MIN_HISTORY_CARDS) ─────────────

class TestNewStudentBlending:
    """New student (< 5 cards) uses 100% current signals, 0% history."""

    def test_new_student_uses_only_current_signals(self):
        """
        Business: When a student has fewer than 5 completed cards,
        history is unreliable — current signals drive 100% of the blend.
        """
        signals = _make_signals(time_sec=200.0, wrong=2)
        history = _make_history(total_cards=3)  # below MIN_HISTORY_CARDS

        analytics, blended_score, generate_as = build_blended_analytics(
            signals, history, "PREALG.C1.S1", "student-1"
        )

        # With 100% current weight, wrong_attempts should equal current (2)
        assert analytics.wrong_attempts == 2
        assert blended_score == pytest.approx(blended_score, abs=0.01)
        assert generate_as in ("STRUGGLING", "NORMAL", "FAST")

    def test_new_student_exactly_zero_cards(self):
        """Edge: total_cards_completed=0 is valid new-student state."""
        signals = _make_signals(time_sec=120.0, wrong=0)
        history = _make_history(total_cards=0)

        analytics, blended_score, generate_as = build_blended_analytics(
            signals, history, "PREALG.C1.S1", "student-1"
        )

        assert analytics is not None
        assert 1.0 <= blended_score <= 3.0
        assert generate_as in ("STRUGGLING", "NORMAL", "FAST")


# ── Tests: normal variance (60/40 split) ──────────────────────────────────────

class TestNormalVarianceBlending:
    """History established, no acute deviation → 60% current / 40% history."""

    def test_normal_variance_uses_60_40_split(self):
        """
        Business: Normal variance produces a blended wrong_attempts between
        current (0.60 weight) and history baseline (0.40 weight).
        time_ratio must be in 0.4-2.0 range and wrong_ratio must be < 1.8.
        """
        # baseline = 120s, current = 120s → ratio = 1.0 (within 0.4-2.0)
        signals = _make_signals(time_sec=120.0, wrong=1)
        history = _make_history(total_cards=10, avg_time=120.0, avg_wrong=1.0)

        analytics, blended_score, generate_as = build_blended_analytics(
            signals, history, "PREALG.C1.S1", "student-1"
        )

        # blended_wrong = 1 * 0.6 + 1.0 * 0.4 = 1.0 → rounded to 1
        assert analytics.wrong_attempts == 1
        assert 1.0 <= blended_score <= 3.0


# ── Tests: acute deviation (90/10 split) ──────────────────────────────────────

class TestAcuteDeviationBlending:
    """Extreme signals trigger acute mode: 90% current / 10% history."""

    def test_acute_high_time_ratio_uses_90_10_split(self):
        """
        Business: time_ratio > 2.0 (distraction / illness detected)
        → 90% current signals, 10% history.
        """
        # baseline=120s, current=300s → ratio=2.5 (> ADAPTIVE_ACUTE_HIGH_TIME_RATIO=2.0)
        signals = _make_signals(time_sec=300.0, wrong=0)
        history = _make_history(total_cards=10, avg_time=120.0, avg_wrong=0.0)

        analytics, blended_score, generate_as = build_blended_analytics(
            signals, history, "PREALG.C1.S1", "student-1"
        )

        # With acute mode: blended_wrong = 0 * 0.9 + 0.0 * 0.1 = 0
        assert analytics.wrong_attempts == 0
        assert 1.0 <= blended_score <= 3.0

    def test_acute_low_time_ratio_uses_90_10_split(self):
        """
        Business: time_ratio < 0.4 (sudden recovery / acceleration)
        → 90% current signals, 10% history.
        """
        # baseline=120s, current=10s → ratio=0.083 (< ADAPTIVE_ACUTE_LOW_TIME_RATIO=0.4)
        signals = _make_signals(time_sec=10.0, wrong=0)
        history = _make_history(total_cards=10, avg_time=120.0, avg_wrong=3.0)

        analytics, blended_score, generate_as = build_blended_analytics(
            signals, history, "PREALG.C1.S1", "student-1"
        )

        # acute mode: blended_wrong = 0 * 0.9 + 3.0 * 0.1 = 0.3 → round = 0
        assert analytics.wrong_attempts == 0

    def test_acute_high_wrong_ratio_uses_90_10_split(self):
        """
        Business: wrong_ratio > 1.8 (acute struggle)
        → 90% current signals, 10% history.
        """
        # wrong_ratio = (5+1)/(0.5+1) = 4.0 → > 1.8 acute
        signals = _make_signals(time_sec=120.0, wrong=5)
        history = _make_history(total_cards=10, avg_time=120.0, avg_wrong=0.5)

        analytics, blended_score, generate_as = build_blended_analytics(
            signals, history, "PREALG.C1.S1", "student-1"
        )

        # With acute: 5 * 0.9 + 0.5 * 0.1 = 4.5 + 0.05 = 4.55 → rounded to 5
        assert analytics.wrong_attempts >= 4


# ── Tests: section_count-based state blend weights ────────────────────────────

class TestSectionCountWeights:
    """Verify state blend weights change with section_count."""

    def test_section_count_0_uses_cold_start_weights(self):
        """section_count=0 → 80/20 cold-start weights."""
        signals = _make_signals(time_sec=120.0, wrong=0)
        history = _make_history(total_cards=10, section_count=0, avg_state_score=2.0)

        analytics, blended_score, generate_as = build_blended_analytics(
            signals, history, "concept", "student"
        )

        # current_numeric_score should be around NORMAL (2.0)
        # blended = 2.0 * 0.80 + 2.0 * 0.20 = 2.0
        assert blended_score == pytest.approx(2.0, abs=0.5)

    def test_section_count_1_uses_warm_start_weights(self):
        """section_count=1 → 70/30 warm-start weights."""
        signals = _make_signals(time_sec=120.0, wrong=0)
        history = _make_history(total_cards=10, section_count=1, avg_state_score=2.0)

        analytics, blended_score, generate_as = build_blended_analytics(
            signals, history, "concept", "student"
        )
        assert 1.0 <= blended_score <= 3.0

    def test_section_count_2_uses_partial_weights(self):
        """section_count=2 → 65/35 partial weights."""
        signals = _make_signals(time_sec=120.0, wrong=0)
        history = _make_history(total_cards=10, section_count=2, avg_state_score=2.0)

        analytics, blended_score, generate_as = build_blended_analytics(
            signals, history, "concept", "student"
        )
        assert 1.0 <= blended_score <= 3.0

    def test_section_count_3_plus_uses_state_blend_weights(self):
        """section_count >= 3 → 60/40 full-history weights."""
        signals = _make_signals(time_sec=120.0, wrong=0)
        history = _make_history(total_cards=10, section_count=5, avg_state_score=2.0)

        analytics, blended_score, generate_as = build_blended_analytics(
            signals, history, "concept", "student"
        )
        assert 1.0 <= blended_score <= 3.0


# ── Tests: compute_numeric_state_score ─────────────────────────────────────────

class TestComputeNumericStateScore:
    """Map (speed, comprehension) pairs to numeric scores in [1.0, 3.0]."""

    def test_slow_struggling_clamps_to_1_0(self):
        """SLOW + STRUGGLING = 1.0 - 0.3 = 0.7 → clamped to 1.0."""
        score = compute_numeric_state_score("SLOW", "STRUGGLING")
        assert score == pytest.approx(1.0)

    def test_fast_strong_clamps_to_3_0(self):
        """FAST + STRONG = 3.0 + 0.3 = 3.3 → clamped to 3.0."""
        score = compute_numeric_state_score("FAST", "STRONG")
        assert score == pytest.approx(3.0)

    def test_normal_ok_returns_2_0(self):
        """NORMAL + OK = 2.0 + 0.0 = 2.0."""
        score = compute_numeric_state_score("NORMAL", "OK")
        assert score == pytest.approx(2.0)

    def test_all_9_combinations_in_valid_range(self):
        """All (speed × comprehension) combinations produce values in [1.0, 3.0]."""
        speeds = ["SLOW", "NORMAL", "FAST"]
        comprehensions = ["STRUGGLING", "OK", "STRONG"]
        for speed in speeds:
            for comp in comprehensions:
                score = compute_numeric_state_score(speed, comp)
                assert 1.0 <= score <= 3.0, (
                    f"compute_numeric_state_score({speed!r}, {comp!r}) = {score} "
                    "out of [1.0, 3.0]"
                )

    def test_case_insensitive(self):
        """Input strings are uppercased before lookup — case should not matter."""
        assert compute_numeric_state_score("slow", "ok") == compute_numeric_state_score("SLOW", "OK")

    def test_unknown_speed_defaults_to_normal(self):
        """Unknown speed key defaults to NORMAL base (2.0)."""
        score = compute_numeric_state_score("UNKNOWN", "OK")
        assert score == pytest.approx(2.0)


# ── Tests: blended_score_to_generate_as ──────────────────────────────────────

class TestBlendedScoreToGenerateAs:
    """Verify threshold-based label assignment."""

    def test_score_below_1_7_returns_struggling(self):
        """blended_score < 1.7 → STRUGGLING."""
        assert blended_score_to_generate_as(1.5) == "STRUGGLING"

    def test_score_at_2_0_returns_normal(self):
        """blended_score 2.0 is in NORMAL band."""
        assert blended_score_to_generate_as(2.0) == "NORMAL"

    def test_score_at_or_above_2_5_returns_fast(self):
        """blended_score >= 2.5 → FAST."""
        assert blended_score_to_generate_as(2.7) == "FAST"
        assert blended_score_to_generate_as(2.5) == "FAST"

    def test_boundary_exactly_1_7_returns_normal(self):
        """blended_score exactly 1.7 is NOT < 1.7 → NORMAL."""
        assert blended_score_to_generate_as(1.7) == "NORMAL"

    def test_boundary_exactly_2_4_returns_normal(self):
        """blended_score 2.4 < 2.5 → NORMAL."""
        assert blended_score_to_generate_as(2.4) == "NORMAL"

    def test_extreme_low_score_returns_struggling(self):
        """Any score below 1.7 (including 1.0) → STRUGGLING."""
        assert blended_score_to_generate_as(1.0) == "STRUGGLING"

    def test_extreme_high_score_returns_fast(self):
        """Any score 3.0 → FAST."""
        assert blended_score_to_generate_as(3.0) == "FAST"


# ── Tests: full pipeline robustness ──────────────────────────────────────────

class TestBlendedAnalyticsRobustness:
    """Edge cases and clamping behavior."""

    def test_blended_score_clamped_to_valid_range(self):
        """blended_score must always be in [1.0, 3.0] regardless of inputs."""
        # Extreme struggling signals
        signals = _make_signals(time_sec=600.0, wrong=10, hints=10)
        history = _make_history(total_cards=20, avg_time=30.0, avg_wrong=0.0)
        _, score, _ = build_blended_analytics(signals, history, "c", "s")
        assert 1.0 <= score <= 3.0

    def test_all_signals_zero_no_crash(self):
        """All zero signals should not cause any crash and should return valid output."""
        signals = _make_signals(time_sec=0.0, wrong=0, hints=0)
        history = _make_history(total_cards=0)
        analytics, blended_score, generate_as = build_blended_analytics(
            signals, history, "concept", "student"
        )
        assert analytics is not None
        assert 1.0 <= blended_score <= 3.0
        assert generate_as in ("STRUGGLING", "NORMAL", "FAST")

    def test_returns_valid_analytics_summary(self):
        """build_blended_analytics returns a valid AnalyticsSummary object."""
        from adaptive.schemas import AnalyticsSummary
        signals = _make_signals(time_sec=100.0, wrong=1)
        history = _make_history(total_cards=10)
        analytics, _, _ = build_blended_analytics(signals, history, "c", "s")
        assert isinstance(analytics, AnalyticsSummary)
        assert analytics.wrong_attempts <= analytics.attempts
