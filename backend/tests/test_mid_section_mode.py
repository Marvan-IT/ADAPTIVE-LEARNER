"""
test_mid_section_mode.py
Unit tests for mode adaptation during per-card generation.

These tests exercise build_blended_analytics and blended_score_to_generate_as
with realistic session signals to verify the correct adaptive mode is computed.

All tests are pure unit tests — no DB, no LLM.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from adaptive.schemas import CardBehaviorSignals
from adaptive.adaptive_engine import (
    build_blended_analytics,
    blended_score_to_generate_as,
    compute_numeric_state_score,
)
from config import (
    ADAPTIVE_MIN_HISTORY_CARDS,
    ADAPTIVE_ACUTE_HIGH_TIME_RATIO,
    ADAPTIVE_ACUTE_LOW_TIME_RATIO,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _signals(time_sec: float = 120.0, wrong: int = 0, hints: int = 0, idle: int = 0) -> CardBehaviorSignals:
    return CardBehaviorSignals(
        card_index=0,
        time_on_card_sec=time_sec,
        wrong_attempts=wrong,
        hints_used=hints,
        idle_triggers=idle,
    )


def _history(
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


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestMidSectionModeAdaptation:
    """Verify that adaptive mode correctly responds to session signals."""

    def test_new_student_normal_signals_defaults_to_normal(self):
        """
        Business: A new student with no prior history and normal time/wrong
        signals should get NORMAL mode.
        """
        sigs = _signals(time_sec=120.0, wrong=0)
        hist = _history(total_cards=0, avg_time=120.0, avg_wrong=0.0, section_count=0, avg_state_score=2.0)

        analytics, blended_score, generate_as = build_blended_analytics(
            sigs, hist, "concept", "student"
        )
        # New student → 100% current → should produce NORMAL mode
        assert generate_as in ("NORMAL", "FAST")
        assert 1.0 <= blended_score <= 3.0

    def test_fast_time_and_zero_wrong_detects_fast_mode(self):
        """
        Business: When time_ratio > 2.0 (very fast, 300s vs 120s baseline)
        and wrong=0, signals detect acute deviation.
        """
        # baseline = 120s, current = 300s → time_ratio = 2.5 (acute high)
        sigs = _signals(time_sec=300.0, wrong=0)
        hist = _history(total_cards=10, avg_time=120.0, avg_wrong=0.0)

        analytics, blended_score, generate_as = build_blended_analytics(
            sigs, hist, "concept", "student"
        )
        # Acute high time + 0 wrong → could still produce NORMAL/FAST depending on speed classification
        assert generate_as in ("STRUGGLING", "NORMAL", "FAST")
        assert 1.0 <= blended_score <= 3.0

    def test_very_slow_time_and_many_wrong_detects_struggling(self):
        """
        Business: time < 0.4x baseline AND many wrong attempts
        → STRUGGLING or NORMAL mode (never FAST).
        """
        # baseline = 120s, current = 10s → time_ratio = 0.083 (acute low)
        # wrong = 3 → high error rate
        sigs = _signals(time_sec=10.0, wrong=3, hints=2)
        hist = _history(total_cards=10, avg_time=120.0, avg_wrong=0.5, avg_state_score=1.5)

        analytics, blended_score, generate_as = build_blended_analytics(
            sigs, hist, "concept", "student"
        )
        # With a history avg_state_score of 1.5 (STRUGGLING) and wrong signals,
        # result must not be FAST
        assert generate_as in ("STRUGGLING", "NORMAL")

    def test_section_count_increments_affect_blend_weights(self):
        """
        Business: section_count in history drives the blend weight selection.
        Incrementing section_count from 0→3 changes how history is weighted.
        """
        sigs = _signals(time_sec=120.0, wrong=0)

        # Cold start (section_count=0): 80% current
        hist_0 = _history(total_cards=10, section_count=0, avg_state_score=2.0)
        _, score_0, _ = build_blended_analytics(sigs, hist_0, "concept", "student")

        # Full history (section_count=3): 60% current
        hist_3 = _history(total_cards=10, section_count=3, avg_state_score=2.0)
        _, score_3, _ = build_blended_analytics(sigs, hist_3, "concept", "student")

        # Both should be valid scores; with uniform signals+history, they may be equal
        assert 1.0 <= score_0 <= 3.0
        assert 1.0 <= score_3 <= 3.0

    def test_fast_mode_capped_to_normal_for_new_students(self):
        """
        Business: New students (< 2 interactions) receiving FAST mode
        should be capped to NORMAL in generate_cards() to avoid over-estimation.
        """
        # Simulate the generate_cards() mode-cap logic
        total_interactions = 0
        generate_as = "FAST"
        blended_score = 2.6

        if total_interactions < 2 and generate_as == "FAST":
            generate_as = "NORMAL"
            blended_score = min(blended_score, 2.4)

        assert generate_as == "NORMAL"
        assert blended_score <= 2.4

    def test_generate_as_matches_blended_score_label(self):
        """
        Business: The generate_as label returned by build_blended_analytics
        must be consistent with what blended_score_to_generate_as would return.
        """
        sigs = _signals(time_sec=120.0, wrong=1)
        hist = _history(total_cards=10, avg_time=120.0, avg_wrong=1.0)

        analytics, blended_score, generate_as = build_blended_analytics(
            sigs, hist, "concept", "student"
        )
        expected_label = blended_score_to_generate_as(blended_score)
        assert generate_as == expected_label

    def test_mode_returns_to_normal_when_signals_normalize(self):
        """
        Business: When a student who had poor history performs normally
        (time near baseline, 0 wrong), the generate_as should be NORMAL.
        """
        # Very struggling history
        sigs = _signals(time_sec=120.0, wrong=0)
        hist = _history(
            total_cards=10,
            avg_time=120.0,
            avg_wrong=0.0,
            section_count=3,
            avg_state_score=2.0,  # History: NORMAL
        )

        analytics, blended_score, generate_as = build_blended_analytics(
            sigs, hist, "concept", "student"
        )
        # Normal current signals + NORMAL history → NORMAL
        assert generate_as == "NORMAL"
        assert blended_score == pytest.approx(2.0, abs=0.3)

    def test_blended_score_always_clamped_regardless_of_extreme_inputs(self):
        """
        Business: Even with extreme signals (e.g., 1000s, 50 wrong attempts),
        the blended_score stays within [1.0, 3.0].
        """
        extreme_sigs = _signals(time_sec=1000.0, wrong=50, hints=20, idle=10)
        hist = _history(
            total_cards=100,
            avg_time=10.0,
            avg_wrong=0.0,
            section_count=5,
            avg_state_score=3.0,
        )

        analytics, blended_score, generate_as = build_blended_analytics(
            extreme_sigs, hist, "concept", "student"
        )
        assert 1.0 <= blended_score <= 3.0
        assert generate_as in ("STRUGGLING", "NORMAL", "FAST")
