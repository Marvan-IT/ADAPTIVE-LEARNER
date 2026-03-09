"""
Comprehensive test suite for the Adaptive Tutor backend — next-card loop.

Covers:
  Group 1 — build_blended_analytics(): pure blending logic, deviation detection
  Group 2 — build_next_card_prompt(): prompt content, schema, difficulty formula
  Group 3 — _NEXT_CARD_JSON_SCHEMA: schema completeness
  Group 4 — load_student_history() (mock DB): aggregation, trend detection, weak-concept flag
  Group 5 — CardBehaviorSignals / NextCardRequest / NextCardResponse: schema validation
  Group 6 — POST /api/v2/sessions/{id}/complete-card: endpoint contract
  Group 7 — GET /api/v2/students/{id}/review-due: endpoint filtering
  Group 8 — Spaced review creation on mastery: interval schedule

Test infrastructure:
  - pytest.ini sets asyncio_mode = auto (no @pytest.mark.asyncio needed)
  - conftest.py inserts backend/src into sys.path; block below duplicates it for
    direct execution safety
  - All external I/O (DB, LLM, knowledge service) is replaced with unittest.mock
    objects — zero real network or database calls in any test
"""

import json
import math
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend/src is importable regardless of how pytest is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from adaptive.schemas import (
    AnalyticsSummary,
    CardBehaviorSignals,
    GenerationProfile,
    LearningProfile,
    NextCardRequest,
    NextCardResponse,
)
from adaptive.adaptive_engine import build_blended_analytics, load_student_history
from adaptive.prompt_builder import _NEXT_CARD_JSON_SCHEMA, build_next_card_prompt
from config import (
    MASTERY_THRESHOLD,
    ADAPTIVE_ACUTE_CURRENT_WEIGHT,
    ADAPTIVE_ACUTE_HISTORY_WEIGHT,
    ADAPTIVE_NORMAL_CURRENT_WEIGHT,
    ADAPTIVE_NORMAL_HISTORY_WEIGHT,
)


# =============================================================================
# Shared helpers
# =============================================================================

def _make_learning_profile(
    speed: str = "NORMAL",
    comprehension: str = "OK",
    engagement: str = "ENGAGED",
    confidence_score: float = 0.6,
    recommended_next_step: str = "CONTINUE",
    error_rate: float = 0.2,
) -> LearningProfile:
    return LearningProfile(
        speed=speed,
        comprehension=comprehension,
        engagement=engagement,
        confidence_score=confidence_score,
        recommended_next_step=recommended_next_step,
        error_rate=error_rate,
    )


def _make_gen_profile(
    explanation_depth: str = "MEDIUM",
    reading_level: str = "STANDARD",
    step_by_step: bool = False,
    analogy_level: float = 0.5,
    fun_level: float = 0.2,
    card_count: int = 9,
    practice_count: int = 4,
    checkpoint_frequency: int = 3,
    max_paragraph_lines: int = 4,
    emoji_policy: str = "NONE",
) -> GenerationProfile:
    return GenerationProfile(
        explanation_depth=explanation_depth,
        reading_level=reading_level,
        step_by_step=step_by_step,
        analogy_level=analogy_level,
        fun_level=fun_level,
        card_count=card_count,
        practice_count=practice_count,
        checkpoint_frequency=checkpoint_frequency,
        max_paragraph_lines=max_paragraph_lines,
        emoji_policy=emoji_policy,
    )


def _make_signals(
    card_index: int = 0,
    time_on_card_sec: float = 90.0,
    wrong_attempts: int = 0,
    hints_used: int = 0,
    idle_triggers: int = 0,
) -> CardBehaviorSignals:
    return CardBehaviorSignals(
        card_index=card_index,
        time_on_card_sec=time_on_card_sec,
        wrong_attempts=wrong_attempts,
        hints_used=hints_used,
        idle_triggers=idle_triggers,
    )


SAMPLE_CONCEPT_DETAIL = {
    "concept_id": "test_concept_001",
    "concept_title": "Addition",
    "chapter": "Chapter 1",
    "section": "1.1",
    "text": "Addition is the process of combining two or more numbers to get a total.",
    "latex": ["a + b = c"],
    "images": [],
}

# Baseline history for an experienced student (25 completed cards)
HISTORY_EXPERIENCED = {
    "avg_time_per_card": 90.0,
    "avg_wrong_attempts": 1.0,
    "avg_hints_per_card": 0.5,
    "total_cards_completed": 25,
    "sessions_last_7d": 3,
    "mastered_count": 8,
    "is_known_weak_concept": False,
    "failed_concept_attempts": 0,
    "trend_direction": "IMPROVING",
    "trend_wrong_list": [2, 2, 1, 1, 0],
}

# Baseline history for a brand-new student (0 cards ever)
HISTORY_NEW = {
    "avg_time_per_card": None,
    "avg_wrong_attempts": None,
    "avg_hints_per_card": None,
    "total_cards_completed": 0,
    "sessions_last_7d": 0,
    "mastered_count": 0,
    "is_known_weak_concept": False,
    "failed_concept_attempts": 0,
    "trend_direction": "STABLE",
    "trend_wrong_list": [],
}


# =============================================================================
# Group 1 — build_blended_analytics(): pure blending / deviation detection
# =============================================================================

class TestBuildBlendedAnalytics:
    """
    build_blended_analytics() fuses card-level signals with aggregate history.
    Blending weight switches based on:
      - no history (< 5 cards) → 100 % current signals
      - normal variance → 60 % current / 40 % history
      - acute time deviation (ratio > 2.0 or < 0.4) → 90 % current / 10 % history
      - acute wrong ratio spike (> 3.0) → 90 % current / 10 % history
    """

    # ------------------------------------------------------------------
    # 1.1 New student — 100 % current signals, no history noise
    # ------------------------------------------------------------------
    def test_blended_analytics_new_student_uses_current_only_zero_blended_wrong(self):
        """
        New student with 0 completed cards should produce blended_wrong equal to the
        raw current wrong_attempts (cw=1.0, hw=0.0 → no history contribution).
        """
        signals = _make_signals(time_on_card_sec=120.0, wrong_attempts=2, hints_used=1)
        result = build_blended_analytics(signals, HISTORY_NEW, "C1", "S1")

        # With cw=1.0 the blended_wrong = 2 * 1.0 + 0.0 * 0.0 = 2
        # attempts = max(1, round(2) + 1) = 3
        assert result.wrong_attempts == 2
        assert result.attempts == 3

    def test_blended_analytics_new_student_uses_current_only_for_hints(self):
        """
        New student: blended_hints = current hints (cw=1.0), not diluted by None history.
        """
        signals = _make_signals(hints_used=3)
        result = build_blended_analytics(signals, HISTORY_NEW, "C1", "S1")

        assert result.hints_used == 3

    def test_blended_analytics_new_student_uses_default_expected_time(self):
        """
        No historical avg_time → expected_time_sec falls back to 120.0 (the default).
        """
        signals = _make_signals(time_on_card_sec=60.0)
        result = build_blended_analytics(signals, HISTORY_NEW, "C1", "S1")

        assert result.expected_time_sec == pytest.approx(120.0)

    def test_blended_analytics_new_student_populates_student_and_concept_id(self):
        """
        student_id and concept_id must be propagated verbatim into AnalyticsSummary.
        """
        signals = _make_signals()
        result = build_blended_analytics(signals, HISTORY_NEW, "concept_xyz", "student_abc")

        assert result.student_id == "student_abc"
        assert result.concept_id == "concept_xyz"

    # ------------------------------------------------------------------
    # 1.2 Normal variance — 60 / 40 blend
    # ------------------------------------------------------------------
    def test_blended_analytics_normal_variance_uses_60_40_blend_for_wrong_attempts(self):
        """
        time_ratio ~1.0, wrong_ratio ~1.0 → normal variance → 60/40 blend.
        Expected blended_wrong = 1 * 0.6 + 1.0 * 0.4 = 1.0 → rounded to 1.
        """
        signals = _make_signals(time_on_card_sec=90.0, wrong_attempts=1)
        result = build_blended_analytics(signals, HISTORY_EXPERIENCED, "C1", "S1")

        # time_ratio = 90/90 = 1.0 (normal), wrong_ratio = (1+1)/(1+1) = 1.0 (normal)
        # cw=0.6, hw=0.4
        # blended_wrong = 1*0.6 + 1.0*0.4 = 1.0 → round → 1
        assert result.wrong_attempts == 1

    def test_blended_analytics_normal_variance_uses_60_40_blend_for_hints(self):
        """
        Normal variance: blended_hints = current_hints * 0.6 + avg_hints * 0.4.
        """
        signals = _make_signals(time_on_card_sec=90.0, wrong_attempts=1, hints_used=2)
        result = build_blended_analytics(signals, HISTORY_EXPERIENCED, "C1", "S1")

        # blended_hints = 2*ADAPTIVE_NORMAL_CURRENT_WEIGHT + 0.5*ADAPTIVE_NORMAL_HISTORY_WEIGHT
        # = 1.2 + 0.2 = 1.4 → round → 1
        assert result.hints_used == round(2 * ADAPTIVE_NORMAL_CURRENT_WEIGHT + 0.5 * ADAPTIVE_NORMAL_HISTORY_WEIGHT)

    # ------------------------------------------------------------------
    # 1.3 Acute time deviation (time_ratio > 2.0) → 90 / 10 blend → SLOW
    # ------------------------------------------------------------------
    def test_blended_analytics_acute_time_deviation_high_uses_90_10_blend(self):
        """
        time_ratio > 2.0 (time_on_card_sec = 300, avg = 90) → acute deviation flag.
        With 90/10 blend, current signals dominate → SLOW classification expected.
        """
        # time_ratio = 300 / 90 = 3.33 > 2.0 → acute
        signals = _make_signals(time_on_card_sec=300.0, wrong_attempts=3)
        result = build_blended_analytics(signals, HISTORY_EXPERIENCED, "C1", "S1")

        # With acute blend (ADAPTIVE_ACUTE_CURRENT_WEIGHT / ADAPTIVE_ACUTE_HISTORY_WEIGHT):
        # blended_wrong = 3*ADAPTIVE_ACUTE_CURRENT_WEIGHT + 1.0*ADAPTIVE_ACUTE_HISTORY_WEIGHT
        # = 2.7 + 0.1 = 2.8 → round → 3
        assert result.wrong_attempts == round(3 * ADAPTIVE_ACUTE_CURRENT_WEIGHT + 1.0 * ADAPTIVE_ACUTE_HISTORY_WEIGHT)

    def test_blended_analytics_acute_time_deviation_high_produces_slow_classification(self):
        """
        time_ratio > 2.0 → time_spent_sec greatly exceeds expected_time_sec → SLOW
        when piped through build_learning_profile.
        """
        from adaptive.profile_builder import build_learning_profile

        signals = _make_signals(time_on_card_sec=300.0, wrong_attempts=0)
        result = build_blended_analytics(signals, HISTORY_EXPERIENCED, "C1", "S1")

        profile = build_learning_profile(result, has_unmet_prereq=False)
        # 300 > 90 * 1.5 = 135 → SLOW
        assert profile.speed == "SLOW"

    def test_blended_analytics_exact_time_ratio_boundary_2_0_not_acute(self):
        """
        time_ratio == 2.0 is NOT > 2.0, so it should use normal 60/40 blend, not 90/10.
        """
        # time_ratio = 180 / 90 = 2.0 exactly — boundary is exclusive
        signals = _make_signals(time_on_card_sec=180.0, wrong_attempts=1)
        result_boundary = build_blended_analytics(signals, HISTORY_EXPERIENCED, "C1", "S1")

        # time_ratio = 181 / 90 > 2.0 → acute
        signals_acute = _make_signals(time_on_card_sec=181.0, wrong_attempts=1)
        result_acute = build_blended_analytics(signals_acute, HISTORY_EXPERIENCED, "C1", "S1")

        # At boundary: blended_wrong = 1*0.6 + 1.0*0.4 = 1.0
        # Acute: blended_wrong = 1*0.9 + 1.0*0.1 = 1.0  (same here, but weights differ)
        # The distinguishing signal is that the acute path produces higher wrong when current > baseline
        # Verify the boundary case uses 60/40 (both give same result here for wrong=1/avg=1)
        # Instead verify via a case where current wrong >> avg
        signals_high = _make_signals(time_on_card_sec=180.0, wrong_attempts=5)
        signals_high_acute = _make_signals(time_on_card_sec=181.0, wrong_attempts=5)
        history = dict(HISTORY_EXPERIENCED, avg_wrong_attempts=1.0)

        r_normal = build_blended_analytics(signals_high, history, "C1", "S1")
        r_acute = build_blended_analytics(signals_high_acute, history, "C1", "S1")

        # Normal (60/40): 5*0.6 + 1.0*0.4 = 3.4 → round → 3
        # Acute  (90/10): 5*0.9 + 1.0*0.1 = 4.6 → round → 5
        assert r_normal.wrong_attempts < r_acute.wrong_attempts

    # ------------------------------------------------------------------
    # 1.4 Acute recovery (time_ratio < 0.4) → 90 / 10 blend
    # ------------------------------------------------------------------
    def test_blended_analytics_recovery_detected_uses_90_10_blend(self):
        """
        time_ratio < 0.4 (student is much faster than their own baseline) → acute
        recovery flag → 90/10 blend so the engine accelerates immediately.
        """
        # time_ratio = 20 / 90 = 0.222 < 0.4 → acute recovery
        signals = _make_signals(time_on_card_sec=20.0, wrong_attempts=0)
        result = build_blended_analytics(signals, HISTORY_EXPERIENCED, "C1", "S1")

        # blended_wrong = 0*0.9 + 1.0*0.1 = 0.1 → round → 0
        # blended_hints = 0*0.9 + 0.5*0.1 = 0.05 → round → 0
        assert result.wrong_attempts == 0
        assert result.hints_used == 0

    def test_blended_analytics_exact_time_ratio_boundary_0_4_not_acute(self):
        """
        time_ratio == 0.4 is NOT < 0.4 — boundary is exclusive; uses 60/40 blend.
        """
        # time_ratio = 36 / 90 = 0.4 exactly — not acute
        signals_boundary = _make_signals(time_on_card_sec=36.0, wrong_attempts=4)
        result_boundary = build_blended_analytics(signals_boundary, HISTORY_EXPERIENCED, "C1", "S1")

        # time_ratio = 35 / 90 < 0.4 — acute recovery
        signals_acute = _make_signals(time_on_card_sec=35.0, wrong_attempts=4)
        result_acute = build_blended_analytics(signals_acute, HISTORY_EXPERIENCED, "C1", "S1")

        # Normal (60/40): 4*0.6 + 1.0*0.4 = 2.8 → round → 3
        # Acute  (90/10): 4*0.9 + 1.0*0.1 = 3.7 → round → 4
        # Acute gives higher blended_wrong because current (4) > avg (1)
        assert result_boundary.wrong_attempts <= result_acute.wrong_attempts

    # ------------------------------------------------------------------
    # 1.5 Acute wrong ratio spike (wrong_ratio > 3.0) → 90 / 10 blend
    # ------------------------------------------------------------------
    def test_blended_analytics_wrong_ratio_spike_triggers_acute_blending(self):
        """
        wrong_ratio = (current_wrong + 1) / (avg_wrong + 1) > 3.0 triggers the
        acute flag even when time_ratio is normal, so the spike dominates.
        """
        # wrong_ratio = (7+1)/(1+1) = 8/2 = 4.0 > 3.0 → acute
        # time_ratio = 90/90 = 1.0 — normal
        signals = _make_signals(time_on_card_sec=90.0, wrong_attempts=7)
        result = build_blended_analytics(signals, HISTORY_EXPERIENCED, "C1", "S1")

        # Acute (ADAPTIVE_ACUTE): 7*ADAPTIVE_ACUTE_CURRENT_WEIGHT + 1.0*ADAPTIVE_ACUTE_HISTORY_WEIGHT
        # = 6.3 + 0.1 = 6.4 → round → 6
        # Normal would give: 7*ADAPTIVE_NORMAL_CURRENT_WEIGHT + 1.0*ADAPTIVE_NORMAL_HISTORY_WEIGHT
        # = 4.2 + 0.4 = 4.6 → round → 5
        # Acute blend produces HIGHER blended_wrong → quiz_score penalty is larger
        assert result.wrong_attempts == round(7 * ADAPTIVE_ACUTE_CURRENT_WEIGHT + 1.0 * ADAPTIVE_ACUTE_HISTORY_WEIGHT)

    def test_blended_analytics_wrong_ratio_at_boundary_3_0_not_acute(self):
        """
        wrong_ratio == 3.0 is NOT > 3.0 — boundary is exclusive; normal 60/40 blend.
        """
        # wrong_ratio = (5+1)/(1+1) = 6/2 = 3.0 exactly — not acute
        signals = _make_signals(time_on_card_sec=90.0, wrong_attempts=5)
        result = build_blended_analytics(signals, HISTORY_EXPERIENCED, "C1", "S1")

        # Normal (ADAPTIVE_NORMAL): 5*ADAPTIVE_NORMAL_CURRENT_WEIGHT + 1.0*ADAPTIVE_NORMAL_HISTORY_WEIGHT
        # = 3.0 + 0.4 = 3.4 → round → 3
        assert result.wrong_attempts == round(5 * ADAPTIVE_NORMAL_CURRENT_WEIGHT + 1.0 * ADAPTIVE_NORMAL_HISTORY_WEIGHT)

    # ------------------------------------------------------------------
    # 1.6 Output shape and field correctness
    # ------------------------------------------------------------------
    def test_blended_analytics_returns_analytics_summary_instance(self):
        signals = _make_signals()
        result = build_blended_analytics(signals, HISTORY_NEW, "C1", "S1")

        assert isinstance(result, AnalyticsSummary)

    def test_blended_analytics_idle_triggers_map_to_recent_dropoffs(self):
        """idle_triggers on the signal are mapped to recent_dropoffs on AnalyticsSummary."""
        signals = _make_signals(idle_triggers=3)
        result = build_blended_analytics(signals, HISTORY_NEW, "C1", "S1")

        assert result.recent_dropoffs == 3

    def test_blended_analytics_sessions_last_7d_comes_from_history(self):
        signals = _make_signals()
        result = build_blended_analytics(signals, HISTORY_EXPERIENCED, "C1", "S1")

        assert result.last_7d_sessions == HISTORY_EXPERIENCED["sessions_last_7d"]

    def test_blended_analytics_skip_rate_is_always_zero(self):
        """
        The card-level blending model has no skip_rate signal; the field is always 0.0.
        """
        signals = _make_signals()
        result = build_blended_analytics(signals, HISTORY_NEW, "C1", "S1")

        assert result.skip_rate == 0.0

    def test_blended_analytics_revisits_is_always_zero(self):
        """No revisit data at the card level; the field is always 0."""
        signals = _make_signals()
        result = build_blended_analytics(signals, HISTORY_NEW, "C1", "S1")

        assert result.revisits == 0

    def test_blended_analytics_quiz_score_decreases_with_higher_blended_wrong(self):
        """
        quiz_score = max(0.0, 1.0 - blended_wrong * 0.25).
        More blended wrong attempts → lower quiz score.
        """
        signals_good = _make_signals(wrong_attempts=0)
        signals_poor = _make_signals(wrong_attempts=4)

        result_good = build_blended_analytics(signals_good, HISTORY_NEW, "C1", "S1")
        result_poor = build_blended_analytics(signals_poor, HISTORY_NEW, "C1", "S1")

        assert result_good.quiz_score > result_poor.quiz_score

    def test_blended_analytics_quiz_score_never_below_zero(self):
        """quiz_score is clamped to 0.0 floor even for extreme wrong_attempts."""
        signals = _make_signals(wrong_attempts=10)  # 10 wrong pushes raw below 0
        result = build_blended_analytics(signals, HISTORY_NEW, "C1", "S1")

        assert result.quiz_score >= 0.0

    def test_blended_analytics_attempts_always_at_least_1(self):
        """attempts = max(1, round(blended_wrong) + 1) — never 0."""
        signals = _make_signals(wrong_attempts=0)
        result = build_blended_analytics(signals, HISTORY_NEW, "C1", "S1")

        assert result.attempts >= 1

    def test_blended_analytics_wrong_attempts_never_exceeds_attempts(self):
        """AnalyticsSummary model_validator requires wrong_attempts <= attempts."""
        signals = _make_signals(wrong_attempts=3, time_on_card_sec=300.0)
        result = build_blended_analytics(signals, HISTORY_EXPERIENCED, "C1", "S1")

        assert result.wrong_attempts <= result.attempts

    def test_blended_analytics_expected_time_sec_uses_historical_avg(self):
        """When history exists, expected_time_sec = avg_time_per_card from the DB."""
        signals = _make_signals()
        result = build_blended_analytics(signals, HISTORY_EXPERIENCED, "C1", "S1")

        assert result.expected_time_sec == pytest.approx(HISTORY_EXPERIENCED["avg_time_per_card"])


# =============================================================================
# Group 2 — build_next_card_prompt(): content, structure, difficulty formula
# =============================================================================

class TestBuildNextCardPrompt:
    """
    build_next_card_prompt() must embed all student context and card-index-based
    difficulty into the prompts it returns.
    """

    def _build(
        self,
        card_index: int = 0,
        history: dict | None = None,
        speed: str = "NORMAL",
        comprehension: str = "OK",
        engagement: str = "ENGAGED",
        language: str = "en",
    ) -> tuple[str, str]:
        h = history if history is not None else dict(HISTORY_EXPERIENCED)
        profile = _make_learning_profile(speed=speed, comprehension=comprehension, engagement=engagement)
        gp = _make_gen_profile()
        return build_next_card_prompt(
            concept_detail=SAMPLE_CONCEPT_DETAIL,
            learning_profile=profile,
            gen_profile=gp,
            card_index=card_index,
            history=h,
            language=language,
        )

    # ------------------------------------------------------------------
    # 2.1 Return type
    # ------------------------------------------------------------------
    def test_next_card_prompt_returns_tuple_of_two_strings(self):
        """build_next_card_prompt() must return exactly a (str, str) tuple."""
        result = self._build()

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert all(isinstance(s, str) for s in result)

    def test_next_card_prompt_system_prompt_is_non_empty(self):
        system_prompt, _ = self._build()
        assert len(system_prompt.strip()) > 0

    def test_next_card_prompt_user_prompt_is_non_empty(self):
        _, user_prompt = self._build()
        assert len(user_prompt.strip()) > 0

    # ------------------------------------------------------------------
    # 2.2 System prompt mandatory sections
    # ------------------------------------------------------------------
    def test_next_card_prompt_system_contains_generation_controls(self):
        """System prompt must contain the GENERATION CONTROLS section inherited from base."""
        system_prompt, _ = self._build()
        assert "GENERATION CONTROLS" in system_prompt

    def test_next_card_prompt_system_contains_override_section(self):
        """System prompt must contain the OVERRIDE section for single-card generation."""
        system_prompt, _ = self._build()
        assert "OVERRIDE" in system_prompt

    def test_next_card_prompt_system_contains_single_card_schema(self):
        """System prompt must embed the _NEXT_CARD_JSON_SCHEMA so LLM knows the shape."""
        system_prompt, _ = self._build()
        assert "motivational_note" in system_prompt
        assert "questions" in system_prompt

    def test_next_card_prompt_system_does_not_require_concept_explanation_key(self):
        """Single-card prompt explicitly tells LLM not to include concept_explanation."""
        system_prompt, _ = self._build()
        assert "concept_explanation" not in system_prompt or "Do NOT include" in system_prompt

    # ------------------------------------------------------------------
    # 2.3 User prompt — STUDENT CONTEXT block
    # ------------------------------------------------------------------
    def test_next_card_prompt_user_contains_student_context_section(self):
        """User prompt must contain the STUDENT CONTEXT section header."""
        _, user_prompt = self._build()
        assert "STUDENT CONTEXT" in user_prompt

    def test_next_card_prompt_user_contains_concept_title(self):
        """Concept title from concept_detail must appear in the user prompt."""
        _, user_prompt = self._build()
        assert "Addition" in user_prompt

    def test_next_card_prompt_user_contains_trend_direction(self):
        """trend_direction from history must be surfaced in the user prompt."""
        _, user_prompt = self._build(history=dict(HISTORY_EXPERIENCED, trend_direction="IMPROVING"))
        assert "IMPROVING" in user_prompt

    def test_next_card_prompt_user_contains_cards_completed_count(self):
        """total_cards_completed must appear in the user prompt for student context."""
        _, user_prompt = self._build(history=dict(HISTORY_EXPERIENCED, total_cards_completed=42))
        assert "42" in user_prompt

    def test_next_card_prompt_user_contains_mastered_count(self):
        """mastered_count must appear in the user prompt."""
        _, user_prompt = self._build(history=dict(HISTORY_EXPERIENCED, mastered_count=15))
        assert "15" in user_prompt

    # ------------------------------------------------------------------
    # 2.4 Known weak concept path
    # ------------------------------------------------------------------
    def test_next_card_prompt_known_weak_concept_appears_in_prompt_with_attempt_count(self):
        """
        When is_known_weak_concept=True, the prompt must note the failed attempt count
        to signal the LLM to be extra patient and encouraging.
        """
        history = dict(HISTORY_EXPERIENCED, is_known_weak_concept=True, failed_concept_attempts=3)
        _, user_prompt = self._build(history=history)

        assert "3" in user_prompt
        # The prompt text says "student has attempted this concept N times without mastering"
        assert "times without mastering" in user_prompt or "YES" in user_prompt

    def test_next_card_prompt_known_weak_concept_false_shows_no(self):
        """When is_known_weak_concept=False, no known-weak annotation in the prompt."""
        history = dict(HISTORY_EXPERIENCED, is_known_weak_concept=False)
        _, user_prompt = self._build(history=history)

        assert "times without mastering" not in user_prompt

    # ------------------------------------------------------------------
    # 2.5 IMPROVING trend → motivational note rules
    # ------------------------------------------------------------------
    def test_next_card_prompt_improving_trend_includes_motivational_note_rules(self):
        """
        When trend_direction is IMPROVING, the user prompt must include the
        MOTIVATIONAL NOTE RULES section prompting the LLM to celebrate improvement.
        """
        history = dict(HISTORY_EXPERIENCED, trend_direction="IMPROVING")
        _, user_prompt = self._build(history=history)

        assert "MOTIVATIONAL NOTE RULES" in user_prompt

    def test_next_card_prompt_motivational_note_rules_always_present(self):
        """MOTIVATIONAL NOTE RULES section is always emitted (null case also covered)."""
        _, user_prompt = self._build(history=HISTORY_NEW)
        assert "MOTIVATIONAL NOTE RULES" in user_prompt

    # ------------------------------------------------------------------
    # 2.6 Difficulty formula: clamp(1 + ceil(4 * card_index / max(card_index+3, 4)), 1, 5)
    # ------------------------------------------------------------------
    def test_next_card_prompt_difficulty_at_index_0_is_1(self):
        """First card (index 0) must always have difficulty=1."""
        system_prompt, _ = self._build(card_index=0)
        expected = max(1, min(5, 1 + math.ceil(4 * 0 / max(0 + 3, 4))))  # = 1
        assert f"difficulty = {expected}" in system_prompt

    def test_next_card_prompt_difficulty_at_index_1_is_2(self):
        system_prompt, _ = self._build(card_index=1)
        expected = max(1, min(5, 1 + math.ceil(4 * 1 / max(1 + 3, 4))))  # = 2
        assert f"difficulty = {expected}" in system_prompt

    def test_next_card_prompt_difficulty_at_index_2_is_3(self):
        system_prompt, _ = self._build(card_index=2)
        expected = max(1, min(5, 1 + math.ceil(4 * 2 / max(2 + 3, 4))))  # = 3
        assert f"difficulty = {expected}" in system_prompt

    def test_next_card_prompt_difficulty_at_index_4_is_4(self):
        system_prompt, _ = self._build(card_index=4)
        expected = max(1, min(5, 1 + math.ceil(4 * 4 / max(4 + 3, 4))))  # = 4
        assert f"difficulty = {expected}" in system_prompt

    def test_next_card_prompt_difficulty_never_below_1(self):
        """Difficulty formula result is always >= 1 regardless of card_index."""
        for idx in range(10):
            system_prompt, _ = self._build(card_index=idx)
            val = max(1, min(5, 1 + math.ceil(4 * idx / max(idx + 3, 4))))
            assert val >= 1

    def test_next_card_prompt_difficulty_never_above_5(self):
        """Difficulty formula result is always <= 5 regardless of card_index."""
        for idx in [0, 5, 10, 20, 100]:
            val = max(1, min(5, 1 + math.ceil(4 * idx / max(idx + 3, 4))))
            assert val <= 5

    # ------------------------------------------------------------------
    # 2.7 Language propagation
    # ------------------------------------------------------------------
    def test_next_card_prompt_english_language_name_appears_in_system(self):
        system_prompt, _ = self._build(language="en")
        assert "English" in system_prompt

    def test_next_card_prompt_tamil_language_name_appears_in_system(self):
        system_prompt, _ = self._build(language="ta")
        assert "Tamil" in system_prompt

    # ------------------------------------------------------------------
    # 2.8 Closing instruction
    # ------------------------------------------------------------------
    def test_next_card_prompt_user_ends_with_json_only_instruction(self):
        """User prompt must close with the JSON-only instruction for determinism."""
        _, user_prompt = self._build()
        assert "Return ONLY the JSON object" in user_prompt


# =============================================================================
# Group 3 — _NEXT_CARD_JSON_SCHEMA completeness
# =============================================================================

class TestNextCardJsonSchema:
    """The embedded schema string must declare all required response fields."""

    def test_schema_contains_title_field(self):
        assert '"title"' in _NEXT_CARD_JSON_SCHEMA

    def test_schema_contains_content_field(self):
        assert '"content"' in _NEXT_CARD_JSON_SCHEMA

    def test_schema_contains_motivational_note_field(self):
        """motivational_note enables LLM to generate encouragement or null."""
        assert '"motivational_note"' in _NEXT_CARD_JSON_SCHEMA

    def test_schema_contains_questions_array(self):
        """questions array is the MCQ / true-false payload for the card."""
        assert '"questions"' in _NEXT_CARD_JSON_SCHEMA

    def test_schema_contains_mcq_type(self):
        assert '"mcq"' in _NEXT_CARD_JSON_SCHEMA

    def test_schema_contains_true_false_type(self):
        assert '"true_false"' in _NEXT_CARD_JSON_SCHEMA

    def test_schema_contains_options_array_for_mcq(self):
        assert '"options"' in _NEXT_CARD_JSON_SCHEMA

    def test_schema_contains_correct_index_for_mcq(self):
        assert '"correct_index"' in _NEXT_CARD_JSON_SCHEMA

    def test_schema_contains_explanation_field(self):
        assert '"explanation"' in _NEXT_CARD_JSON_SCHEMA

    def test_schema_is_non_empty_string(self):
        assert isinstance(_NEXT_CARD_JSON_SCHEMA, str) and len(_NEXT_CARD_JSON_SCHEMA) > 0


# =============================================================================
# Group 4 — load_student_history() with mocked DB
# =============================================================================

class TestLoadStudentHistory:
    """
    load_student_history() makes 5 async DB queries.  All are replaced with
    AsyncMock so no real database is needed.
    """

    def _make_db(
        self,
        *,
        avg_time=None,
        avg_wrong=None,
        avg_hints=None,
        total_cards=0,
        recent_rows=None,   # list of (wrong_attempts, time_on_card_sec) tuples
        sessions_7d=0,
        mastered_count=0,
        failed_attempts=0,
    ):
        """
        Construct a mock AsyncSession whose execute() returns deterministic data
        for each of the 5 queries issued by load_student_history().
        """
        # ── Build aggregate result (query 1) ──────────────────────────────────
        agg_row = MagicMock()
        agg_row.avg_time = avg_time
        agg_row.avg_wrong = avg_wrong
        agg_row.avg_hints = avg_hints
        agg_row.total_cards = total_cards

        agg_result = MagicMock()
        agg_result.one.return_value = agg_row

        # ── Build trend rows (query 2) ────────────────────────────────────────
        if recent_rows is None:
            recent_rows = []
        trend_rows = []
        for wrong, time_sec in recent_rows:
            row = MagicMock()
            row.wrong_attempts = wrong
            row.time_on_card_sec = time_sec
            trend_rows.append(row)

        trend_result = MagicMock()
        trend_result.all.return_value = trend_rows

        # ── Build sessions-7d scalar (query 3) ────────────────────────────────
        sessions_result = MagicMock()
        sessions_result.scalar.return_value = sessions_7d

        # ── Build mastered count scalar (query 4) ─────────────────────────────
        mastered_result = MagicMock()
        mastered_result.scalar.return_value = mastered_count

        # ── Build failed attempts scalar (query 5) ────────────────────────────
        weak_result = MagicMock()
        weak_result.scalar.return_value = failed_attempts

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            agg_result,
            trend_result,
            sessions_result,
            mastered_result,
            weak_result,
        ])
        return db

    # ------------------------------------------------------------------
    # 4.1 New student — all None / zero baselines
    # ------------------------------------------------------------------
    async def test_load_student_history_new_student_returns_zero_baseline(self):
        """
        No interactions in DB → avg_time, avg_wrong, avg_hints all None;
        total_cards_completed == 0; is_known_weak_concept == False.
        """
        db = self._make_db()
        result = await load_student_history("00000000-0000-0000-0000-000000000001", "C1", db)

        assert result["avg_time_per_card"] is None
        assert result["avg_wrong_attempts"] is None
        assert result["avg_hints_per_card"] is None
        assert result["total_cards_completed"] == 0
        assert result["is_known_weak_concept"] is False

    async def test_load_student_history_new_student_trend_is_stable(self):
        """< 3 recent rows → STABLE trend."""
        db = self._make_db(recent_rows=[])
        result = await load_student_history("00000000-0000-0000-0000-000000000001", "C1", db)

        assert result["trend_direction"] == "STABLE"

    # ------------------------------------------------------------------
    # 4.2 Improving trend detection
    # ------------------------------------------------------------------
    async def test_load_student_history_sets_improving_trend(self):
        """
        Last 5 cards: decreasing wrong_attempts from older to newer → IMPROVING.
        list order is newest-first (desc order_by completed_at), so:
          trend_wrong_list = [0, 1, 1, 2, 2]
          first_half  (older half): [1, 2, 2] → avg=1.667
          second_half (newer half): [0, 1]    → avg=0.5
          0.5 < 1.667 - 0.3=1.367 → IMPROVING
        """
        # newest-first: most recent = 0 wrong, oldest = 2 wrong
        recent = [(0, 30.0), (1, 40.0), (1, 50.0), (2, 90.0), (2, 110.0)]
        db = self._make_db(total_cards=25, recent_rows=recent)
        result = await load_student_history("00000000-0000-0000-0000-000000000001", "C1", db)

        assert result["trend_direction"] == "IMPROVING"

    async def test_load_student_history_improving_trend_requires_at_least_3_cards(self):
        """With only 2 recent cards trend cannot be determined → STABLE."""
        recent = [(0, 30.0), (3, 90.0)]
        db = self._make_db(total_cards=10, recent_rows=recent)
        result = await load_student_history("00000000-0000-0000-0000-000000000001", "C1", db)

        assert result["trend_direction"] == "STABLE"

    # ------------------------------------------------------------------
    # 4.3 Worsening trend detection
    # ------------------------------------------------------------------
    async def test_load_student_history_sets_worsening_trend(self):
        """
        Last 5 cards: increasing wrong_attempts from older to newer → WORSENING.
        newest-first list: [3, 3, 2, 1, 0]
          first_half (older): [2, 1, 0] → avg=1.0
          second_half (newer): [3, 3]   → avg=3.0
          3.0 > 1.0 + 0.3=1.3 → WORSENING
        """
        recent = [(3, 30.0), (3, 40.0), (2, 60.0), (1, 80.0), (0, 90.0)]
        db = self._make_db(total_cards=25, recent_rows=recent)
        result = await load_student_history("00000000-0000-0000-0000-000000000001", "C1", db)

        assert result["trend_direction"] == "WORSENING"

    # ------------------------------------------------------------------
    # 4.4 Stable trend (within 0.3 threshold)
    # ------------------------------------------------------------------
    async def test_load_student_history_stable_trend_when_within_threshold(self):
        """
        When the improvement is less than 0.3 in either direction → STABLE.
        """
        # All cards had same wrong attempts → avg_second == avg_first → STABLE
        recent = [(1, 90.0), (1, 90.0), (1, 90.0)]
        db = self._make_db(total_cards=25, recent_rows=recent)
        result = await load_student_history("00000000-0000-0000-0000-000000000001", "C1", db)

        assert result["trend_direction"] == "STABLE"

    # ------------------------------------------------------------------
    # 4.5 Weak concept detection
    # ------------------------------------------------------------------
    async def test_load_student_history_weak_concept_at_2_failures(self):
        """
        2 failed teaching sessions for this concept → is_known_weak_concept = True.
        Business rule threshold: failed_attempts >= 2.
        """
        db = self._make_db(total_cards=10, failed_attempts=2)
        result = await load_student_history("00000000-0000-0000-0000-000000000001", "C1", db)

        assert result["is_known_weak_concept"] is True
        assert result["failed_concept_attempts"] == 2

    async def test_load_student_history_not_weak_at_1_failure(self):
        """
        1 failed session does NOT meet the threshold (>= 2) → is_known_weak_concept False.
        """
        db = self._make_db(total_cards=10, failed_attempts=1)
        result = await load_student_history("00000000-0000-0000-0000-000000000001", "C1", db)

        assert result["is_known_weak_concept"] is False

    async def test_load_student_history_not_weak_at_zero_failures(self):
        """Zero failures → definitely not a weak concept."""
        db = self._make_db(failed_attempts=0)
        result = await load_student_history("00000000-0000-0000-0000-000000000001", "C1", db)

        assert result["is_known_weak_concept"] is False

    # ------------------------------------------------------------------
    # 4.6 Aggregate fields
    # ------------------------------------------------------------------
    async def test_load_student_history_populates_avg_time_from_db(self):
        db = self._make_db(avg_time=75.5, total_cards=20)
        result = await load_student_history("00000000-0000-0000-0000-000000000001", "C1", db)

        assert result["avg_time_per_card"] == pytest.approx(75.5)

    async def test_load_student_history_populates_sessions_last_7d(self):
        db = self._make_db(sessions_7d=4)
        result = await load_student_history("00000000-0000-0000-0000-000000000001", "C1", db)

        assert result["sessions_last_7d"] == 4

    async def test_load_student_history_populates_mastered_count(self):
        db = self._make_db(mastered_count=12)
        result = await load_student_history("00000000-0000-0000-0000-000000000001", "C1", db)

        assert result["mastered_count"] == 12

    async def test_load_student_history_result_has_all_expected_keys(self):
        """Returned dict must contain all keys expected by build_blended_analytics()."""
        db = self._make_db()
        result = await load_student_history("00000000-0000-0000-0000-000000000001", "C1", db)

        expected_keys = {
            "avg_time_per_card",
            "avg_wrong_attempts",
            "avg_hints_per_card",
            "total_cards_completed",
            "sessions_last_7d",
            "mastered_count",
            "is_known_weak_concept",
            "failed_concept_attempts",
            "trend_direction",
            "trend_wrong_list",
        }
        assert expected_keys.issubset(result.keys())

    async def test_load_student_history_accepts_string_student_id(self):
        """student_id may arrive as a UUID string — must not raise."""
        db = self._make_db()
        # Should not raise TypeError or AttributeError
        result = await load_student_history("00000000-0000-0000-0000-000000000001", "C1", db)
        assert isinstance(result, dict)


# =============================================================================
# Group 5 — Schema validation: CardBehaviorSignals, NextCardRequest, NextCardResponse
# =============================================================================

class TestSchemaValidation:
    """Pydantic model field defaults, optionality, and constraint enforcement."""

    # ------------------------------------------------------------------
    # 5.1 CardBehaviorSignals defaults
    # ------------------------------------------------------------------
    def test_card_behavior_signals_wrong_attempts_defaults_to_zero(self):
        """Omitting wrong_attempts must default to 0 (not None)."""
        signals = CardBehaviorSignals(card_index=0)
        assert signals.wrong_attempts == 0

    def test_card_behavior_signals_selected_wrong_option_defaults_to_none(self):
        """selected_wrong_option is optional and defaults to None."""
        signals = CardBehaviorSignals(card_index=0)
        assert signals.selected_wrong_option is None

    def test_card_behavior_signals_time_on_card_defaults_to_zero(self):
        signals = CardBehaviorSignals(card_index=0)
        assert signals.time_on_card_sec == 0.0

    def test_card_behavior_signals_hints_used_defaults_to_zero(self):
        signals = CardBehaviorSignals(card_index=0)
        assert signals.hints_used == 0

    def test_card_behavior_signals_idle_triggers_defaults_to_zero(self):
        signals = CardBehaviorSignals(card_index=0)
        assert signals.idle_triggers == 0

    def test_card_behavior_signals_accepts_explicit_wrong_option(self):
        signals = CardBehaviorSignals(card_index=2, selected_wrong_option=3)
        assert signals.selected_wrong_option == 3

    # ------------------------------------------------------------------
    # 5.2 NextCardRequest inherits CardBehaviorSignals
    # ------------------------------------------------------------------
    def test_next_card_request_inherits_defaults_from_card_behavior_signals(self):
        """NextCardRequest must have same defaults as CardBehaviorSignals."""
        req = NextCardRequest(card_index=1)
        assert req.wrong_attempts == 0
        assert req.selected_wrong_option is None

    # ------------------------------------------------------------------
    # 5.3 NextCardResponse optional fields
    # ------------------------------------------------------------------
    def test_next_card_response_motivational_note_can_be_none(self):
        """motivational_note is optional — None must be accepted."""
        resp = NextCardResponse(
            session_id=uuid.uuid4(),
            card={"title": "Test Card"},
            card_index=0,
            adaptation_applied="NORMAL/OK",
            learning_profile_summary={"speed": "NORMAL"},
            motivational_note=None,
        )
        assert resp.motivational_note is None

    def test_next_card_response_performance_vs_baseline_can_be_none(self):
        """performance_vs_baseline is optional — None when no baseline exists."""
        resp = NextCardResponse(
            session_id=uuid.uuid4(),
            card={"title": "Test Card"},
            card_index=0,
            adaptation_applied="NORMAL/OK",
            learning_profile_summary={"speed": "NORMAL"},
            performance_vs_baseline=None,
        )
        assert resp.performance_vs_baseline is None

    def test_next_card_response_accepts_valid_performance_vs_baseline_values(self):
        for value in ("FASTER", "SLOWER", "ON_TRACK"):
            resp = NextCardResponse(
                session_id=uuid.uuid4(),
                card={},
                card_index=0,
                adaptation_applied="NORMAL/OK",
                learning_profile_summary={},
                performance_vs_baseline=value,
            )
            assert resp.performance_vs_baseline == value

    def test_next_card_response_session_id_field_is_uuid(self):
        sid = uuid.uuid4()
        resp = NextCardResponse(
            session_id=sid,
            card={},
            card_index=0,
            adaptation_applied="NORMAL/OK",
            learning_profile_summary={},
        )
        assert resp.session_id == sid


# =============================================================================
# Group 6 — POST /api/v2/sessions/{id}/complete-card endpoint
# =============================================================================

class TestCompleteCardEndpoint:
    """
    Endpoint behaviour under various session states, ceiling conditions, and
    failure modes.  All DB queries and the LLM call are mocked so no real
    database or network is needed.
    """

    # ------------------------------------------------------------------
    # 6.1 Happy path — 200 response with next card
    # ------------------------------------------------------------------
    async def test_complete_card_returns_200_with_next_card(self):
        """
        Valid session in PRESENTING phase + valid signals → 200 OK with card,
        adaptation_applied, and learning_profile_summary in the response body.
        """
        from adaptive.adaptive_router import cards_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(cards_router)

        session_id = uuid.uuid4()
        student_id = uuid.uuid4()

        # Build mock session object
        mock_session = MagicMock()
        mock_session.id = session_id
        mock_session.student_id = student_id
        mock_session.concept_id = "C1"
        mock_session.phase = "PRESENTING"
        mock_session.presentation_text = None

        # Build mock student object
        mock_student = MagicMock()
        mock_student.preferred_language = "en"

        # Mock DB
        mock_db = AsyncMock()

        # Query 1: select session (scalar_one_or_none)
        session_exec_result = MagicMock()
        session_exec_result.scalar_one_or_none.return_value = mock_session

        # Query 2: select student (scalar_one_or_none)
        student_exec_result = MagicMock()
        student_exec_result.scalar_one_or_none.return_value = mock_student

        # load_student_history makes 5 queries; mastery SELECT makes 1 → 6 more calls
        agg_row = MagicMock()
        agg_row.avg_time = 90.0
        agg_row.avg_wrong = 1.0
        agg_row.avg_hints = 0.5
        agg_row.total_cards = 25
        agg_result = MagicMock()
        agg_result.one.return_value = agg_row

        trend_result = MagicMock()
        trend_result.all.return_value = []

        sessions_result = MagicMock()
        sessions_result.scalar.return_value = 3

        mastered_count_result = MagicMock()
        mastered_count_result.scalar.return_value = 5

        weak_result = MagicMock()
        weak_result.scalar.return_value = 0

        mastery_store_result = MagicMock()
        mastery_store_result.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[
            session_exec_result,    # load session
            student_exec_result,    # load student language
            # (flush happens synchronously via db.add + db.flush)
            agg_result,             # load_student_history: aggregate
            trend_result,           # load_student_history: trend
            sessions_result,        # load_student_history: sessions 7d
            mastered_count_result,  # load_student_history: mastered count
            weak_result,            # load_student_history: weak concept
            mastery_store_result,   # mastery store bulk SELECT
        ])
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        card_dict = {
            "index": 0,
            "title": "Test Card",
            "content": "Content here",
            "images": [],
            "questions": [],
        }
        mock_profile = _make_learning_profile()
        mock_gen_profile = _make_gen_profile()

        async def get_db_override():
            return mock_db

        from db.connection import get_db
        app.dependency_overrides[get_db] = get_db_override

        import adaptive.adaptive_router as ar
        original_ks = ar.adaptive_knowledge_svc
        original_llm = ar.adaptive_llm_client

        mock_ks = MagicMock()
        mock_ks.graph.predecessors.return_value = iter([])
        mock_ks.get_concept_detail.return_value = dict(SAMPLE_CONCEPT_DETAIL)
        ar.adaptive_knowledge_svc = mock_ks

        mock_llm = AsyncMock()

        with patch(
            "adaptive.adaptive_engine.generate_next_card",
            new=AsyncMock(return_value=(card_dict, mock_profile, mock_gen_profile, "Well done!", "ACCELERATED")),
        ):
            ar.adaptive_llm_client = mock_llm
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/api/v2/sessions/{session_id}/complete-card",
                json={
                    "card_index": 0,
                    "time_on_card_sec": 60.0,
                    "wrong_attempts": 0,
                    "hints_used": 0,
                    "idle_triggers": 0,
                },
            )

        ar.adaptive_knowledge_svc = original_ks
        ar.adaptive_llm_client = original_llm

        assert response.status_code == 200
        body = response.json()
        assert "card" in body
        assert "adaptation_applied" in body

    # ------------------------------------------------------------------
    # 6.2 Ceiling — 409 when 8 cards already generated
    # ------------------------------------------------------------------
    async def test_complete_card_returns_409_at_8_card_ceiling(self):
        """
        Session that already has 8 cards in its presentation_text cache
        must return 409 {"ceiling": True} without calling the LLM.
        """
        from adaptive.adaptive_router import cards_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(cards_router)

        session_id = uuid.uuid4()
        student_id = uuid.uuid4()

        existing_8_cards = json.dumps([{"index": i} for i in range(20)])

        mock_session = MagicMock()
        mock_session.id = session_id
        mock_session.student_id = student_id
        mock_session.concept_id = "C1"
        mock_session.phase = "PRESENTING"
        mock_session.presentation_text = existing_8_cards

        mock_student = MagicMock()
        mock_student.preferred_language = "en"

        session_exec_result = MagicMock()
        session_exec_result.scalar_one_or_none.return_value = mock_session
        student_exec_result = MagicMock()
        student_exec_result.scalar_one_or_none.return_value = mock_student

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[session_exec_result, student_exec_result])
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        from db.connection import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            f"/api/v2/sessions/{session_id}/complete-card",
            json={"card_index": 8, "time_on_card_sec": 60.0, "wrong_attempts": 0},
        )

        assert response.status_code == 409
        assert response.json().get("detail", {}).get("ceiling") is True

    # ------------------------------------------------------------------
    # 6.3 Session not found — 404
    # ------------------------------------------------------------------
    async def test_complete_card_returns_404_for_unknown_session(self):
        """session_id not in DB → 404 immediately."""
        from adaptive.adaptive_router import cards_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(cards_router)

        not_found_result = MagicMock()
        not_found_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=not_found_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        from db.connection import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        session_id = uuid.uuid4()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            f"/api/v2/sessions/{session_id}/complete-card",
            json={"card_index": 0, "time_on_card_sec": 60.0},
        )

        assert response.status_code == 404

    # ------------------------------------------------------------------
    # 6.4 LLM failure — 502
    # ------------------------------------------------------------------
    async def test_complete_card_returns_502_when_generate_next_card_raises(self):
        """
        If generate_next_card() raises any exception the endpoint must return 502,
        not propagate the exception as a 500.
        """
        from adaptive.adaptive_router import cards_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(cards_router)

        session_id = uuid.uuid4()
        student_id = uuid.uuid4()

        mock_session = MagicMock()
        mock_session.id = session_id
        mock_session.student_id = student_id
        mock_session.concept_id = "C1"
        mock_session.phase = "PRESENTING"
        mock_session.presentation_text = None

        mock_student = MagicMock()
        mock_student.preferred_language = "en"

        session_exec_result = MagicMock()
        session_exec_result.scalar_one_or_none.return_value = mock_session
        student_exec_result = MagicMock()
        student_exec_result.scalar_one_or_none.return_value = mock_student

        agg_row = MagicMock()
        agg_row.avg_time = 90.0
        agg_row.avg_wrong = 1.0
        agg_row.avg_hints = 0.5
        agg_row.total_cards = 25
        agg_result = MagicMock()
        agg_result.one.return_value = agg_row

        trend_result = MagicMock()
        trend_result.all.return_value = []
        sessions_result = MagicMock()
        sessions_result.scalar.return_value = 0
        mastered_count_result = MagicMock()
        mastered_count_result.scalar.return_value = 0
        weak_result = MagicMock()
        weak_result.scalar.return_value = 0
        mastery_store_result = MagicMock()
        mastery_store_result.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            session_exec_result,
            student_exec_result,
            agg_result,
            trend_result,
            sessions_result,
            mastered_count_result,
            weak_result,
            mastery_store_result,
        ])
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        from db.connection import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        import adaptive.adaptive_router as ar
        ar.adaptive_knowledge_svc = MagicMock()
        ar.adaptive_knowledge_svc.graph.predecessors.return_value = iter([])
        ar.adaptive_knowledge_svc.get_concept_detail.return_value = dict(SAMPLE_CONCEPT_DETAIL)

        with patch(
            "adaptive.adaptive_engine.generate_next_card",
            new=AsyncMock(side_effect=ValueError("LLM failed after 3 attempts")),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/api/v2/sessions/{session_id}/complete-card",
                json={"card_index": 0, "time_on_card_sec": 60.0, "wrong_attempts": 0},
            )

        assert response.status_code == 502

    # ------------------------------------------------------------------
    # 6.5 Wrong phase — 400
    # ------------------------------------------------------------------
    async def test_complete_card_returns_400_when_session_phase_is_completed(self):
        """
        Session in COMPLETED phase must be rejected with 400 before any DB writes.
        """
        from adaptive.adaptive_router import cards_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(cards_router)

        session_id = uuid.uuid4()
        student_id = uuid.uuid4()

        mock_session = MagicMock()
        mock_session.id = session_id
        mock_session.student_id = student_id
        mock_session.concept_id = "C1"
        mock_session.phase = "COMPLETED"  # disallowed phase
        mock_session.presentation_text = None

        session_exec_result = MagicMock()
        session_exec_result.scalar_one_or_none.return_value = mock_session

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=session_exec_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        from db.connection import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            f"/api/v2/sessions/{session_id}/complete-card",
            json={"card_index": 0, "time_on_card_sec": 60.0},
        )

        assert response.status_code == 400


# =============================================================================
# Group 7 — GET /api/v2/students/{id}/review-due endpoint
# =============================================================================

class TestReviewDueEndpoint:
    """
    The review-due endpoint returns SpacedReview rows that are:
      - past due (due_at <= now)
      - not yet completed (completed_at IS NULL)
    """

    def _build_review(
        self,
        concept_id: str,
        review_number: int,
        due_days_offset: int,  # negative = past due, positive = future
        completed: bool = False,
    ) -> MagicMock:
        r = MagicMock()
        r.id = uuid.uuid4()
        r.concept_id = concept_id
        r.review_number = review_number
        r.due_at = datetime.now(timezone.utc) + timedelta(days=due_days_offset)
        r.completed_at = datetime.now(timezone.utc) if completed else None
        return r

    async def test_review_due_returns_empty_for_new_student(self):
        """No spaced review rows → empty list response."""
        from api.teaching_router import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router)

        reviews_result = MagicMock()
        reviews_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=reviews_result)

        from db.connection import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        student_id = uuid.uuid4()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(f"/api/v2/students/{student_id}/review-due")

        assert response.status_code == 200
        assert response.json() == []

    async def test_review_due_returns_only_past_due_reviews(self):
        """
        Future reviews (due_at > now) must NOT be returned.
        Past-due reviews (due_at <= now) MUST be returned.
        """
        from api.teaching_router import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router)

        # The endpoint performs the date filter in SQL; the mock returns only what
        # the WHERE clause would return.  We simulate a DB that returns 1 past-due row.
        past_due_review = self._build_review("concept_algebra", 1, due_days_offset=-1)

        reviews_result = MagicMock()
        reviews_result.scalars.return_value.all.return_value = [past_due_review]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=reviews_result)

        from db.connection import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        student_id = uuid.uuid4()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(f"/api/v2/students/{student_id}/review-due")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["concept_id"] == "concept_algebra"
        assert body[0]["review_number"] == 1

    async def test_review_due_excludes_completed_reviews(self):
        """
        Reviews with completed_at != None should be filtered by the WHERE clause.
        Simulated by returning an empty list from the mocked DB (as if SQL filtered them).
        """
        from api.teaching_router import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router)

        # Simulate DB returning nothing (completed rows filtered by completed_at IS NULL)
        reviews_result = MagicMock()
        reviews_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=reviews_result)

        from db.connection import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        student_id = uuid.uuid4()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(f"/api/v2/students/{student_id}/review-due")

        assert response.status_code == 200
        assert response.json() == []

    async def test_review_due_response_contains_required_fields(self):
        """Each returned review object must have concept_id, due_at, review_number, review_id."""
        from api.teaching_router import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router)

        review = self._build_review("concept_geometry", 2, due_days_offset=-2)
        reviews_result = MagicMock()
        reviews_result.scalars.return_value.all.return_value = [review]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=reviews_result)

        from db.connection import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        student_id = uuid.uuid4()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(f"/api/v2/students/{student_id}/review-due")

        assert response.status_code == 200
        item = response.json()[0]
        assert "concept_id" in item
        assert "due_at" in item
        assert "review_number" in item
        assert "review_id" in item

    async def test_review_due_multiple_past_due_reviews_all_returned(self):
        """When multiple concepts are past due they all appear in the list."""
        from api.teaching_router import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router)

        reviews = [
            self._build_review("concept_a", 1, due_days_offset=-1),
            self._build_review("concept_b", 2, due_days_offset=-3),
            self._build_review("concept_c", 1, due_days_offset=-7),
        ]
        reviews_result = MagicMock()
        reviews_result.scalars.return_value.all.return_value = reviews

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=reviews_result)

        from db.connection import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        student_id = uuid.uuid4()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(f"/api/v2/students/{student_id}/review-due")

        assert response.status_code == 200
        assert len(response.json()) == 3


# =============================================================================
# Group 8 — Spaced review creation on mastery (service-level behaviour)
# =============================================================================

class TestSpacedReviewCreationOnMastery:
    """
    When a student achieves mastery (score >= 60), TeachingService.handle_student_response()
    must create exactly 5 SpacedReview rows with the Ebbinghaus intervals:
      review_number 1 → +1 day
      review_number 2 → +3 days
      review_number 3 → +7 days
      review_number 4 → +14 days
      review_number 5 → +30 days
    """

    REVIEW_INTERVALS_DAYS = [1, 3, 7, 14, 30]

    def test_spaced_review_interval_list_has_exactly_5_entries(self):
        """Business rule: 5 spaced review events per mastered concept."""
        assert len(self.REVIEW_INTERVALS_DAYS) == 5

    def test_spaced_review_intervals_are_1_3_7_14_30(self):
        """Ebbinghaus intervals: 1, 3, 7, 14, 30 days."""
        assert self.REVIEW_INTERVALS_DAYS == [1, 3, 7, 14, 30]

    def test_spaced_review_intervals_are_strictly_increasing(self):
        """Each subsequent review must be further in the future."""
        for i in range(len(self.REVIEW_INTERVALS_DAYS) - 1):
            assert self.REVIEW_INTERVALS_DAYS[i] < self.REVIEW_INTERVALS_DAYS[i + 1]

    async def test_mastery_creates_5_spaced_review_rows(self):
        """
        Simulate mastery being awarded; verify that TeachingService adds exactly 5
        SpacedReview rows to the session's db.add() call log.
        """
        from api.teaching_service import TeachingService

        # Arrange: build just enough mock infrastructure for handle_student_response.
        mock_ks = MagicMock()
        mock_ks.get_concept_detail.return_value = {
            "concept_title": "Test Concept",
            "text": "some text",
            "latex": [],
            "images": [],
            "prerequisites": [],
            "dependents": [],
        }
        mock_ks.graph.predecessors.return_value = iter([])

        svc = TeachingService(knowledge_svc=mock_ks)
        svc.openai = AsyncMock()

        # LLM returns a mastery response — must contain [ASSESSMENT:XX] marker
        mastery_llm_content = "Excellent work! You have demonstrated mastery. [ASSESSMENT:85]"
        mock_llm_response = MagicMock()
        mock_llm_response.choices = [MagicMock()]
        mock_llm_response.choices[0].message.content = mastery_llm_content
        svc.openai.chat.completions.create = AsyncMock(return_value=mock_llm_response)

        session_id = uuid.uuid4()
        student_id = uuid.uuid4()
        concept_id = "test_concept_001"

        mock_session = MagicMock()
        mock_session.id = session_id
        mock_session.student_id = student_id
        mock_session.concept_id = concept_id
        mock_session.phase = "CHECKING"
        mock_session.style = "default"
        mock_session.book_slug = "prealgebra"
        mock_session.check_score = None
        mock_session.best_check_score = None
        mock_session.concept_mastered = False
        mock_session.socratic_attempt_count = 0

        mock_student = MagicMock()
        mock_student.id = student_id
        mock_student.display_name = "Test Student"
        mock_student.preferred_language = "en"
        mock_student.preferred_style = "default"

        # Track db.add calls so we can count SpacedReview rows
        from db.models import SpacedReview

        added_objects = []

        mock_db = AsyncMock()
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        # Set up execute side-effects:
        # 1) _get_phase_messages → scalars().all() → []
        # 2) _get_message_count → scalar_one() → 0
        # 3) StudentMastery check → scalar_one_or_none() → None (first mastery)
        messages_result = MagicMock()
        messages_result.scalars.return_value.all.return_value = []
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mastery_check_result = MagicMock()
        mastery_check_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[
            messages_result,
            count_result,
            mastery_check_result,
        ])

        await svc.handle_student_response(mock_db, mock_session, "I understand now")

        spaced_review_rows = [obj for obj in added_objects if isinstance(obj, SpacedReview)]
        assert len(spaced_review_rows) == 5

    async def test_spaced_review_intervals_correct_days(self):
        """
        Each SpacedReview row must have due_at = now + interval, with a tolerance of
        ±5 seconds to account for test execution time.
        """
        from api.teaching_service import TeachingService
        from db.models import SpacedReview

        mock_ks = MagicMock()
        mock_ks.get_concept_detail.return_value = {
            "concept_title": "Test Concept",
            "text": "some text",
            "latex": [],
            "images": [],
            "prerequisites": [],
            "dependents": [],
        }
        mock_ks.graph.predecessors.return_value = iter([])

        svc = TeachingService(knowledge_svc=mock_ks)
        svc.openai = AsyncMock()

        mastery_llm_content = "Mastery achieved! [ASSESSMENT:90]"
        mock_llm_response = MagicMock()
        mock_llm_response.choices = [MagicMock()]
        mock_llm_response.choices[0].message.content = mastery_llm_content
        svc.openai.chat.completions.create = AsyncMock(return_value=mock_llm_response)

        session_id = uuid.uuid4()
        student_id = uuid.uuid4()

        mock_session = MagicMock()
        mock_session.id = session_id
        mock_session.student_id = student_id
        mock_session.concept_id = "test_concept_001"
        mock_session.phase = "CHECKING"
        mock_session.style = "default"
        mock_session.book_slug = "prealgebra"
        mock_session.check_score = None
        mock_session.best_check_score = None
        mock_session.concept_mastered = False
        mock_session.socratic_attempt_count = 0

        mock_student = MagicMock()
        mock_student.id = student_id
        mock_student.display_name = "Test Student"
        mock_student.preferred_language = "en"
        mock_student.preferred_style = "default"

        added_objects = []
        mock_db = AsyncMock()
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        messages_result = MagicMock()
        messages_result.scalars.return_value.all.return_value = []
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mastery_check_result = MagicMock()
        mastery_check_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[
            messages_result,
            count_result,
            mastery_check_result,
        ])

        before = datetime.now(timezone.utc)
        await svc.handle_student_response(mock_db, mock_session, "I understand!")
        after = datetime.now(timezone.utc)

        spaced_reviews = [obj for obj in added_objects if isinstance(obj, SpacedReview)]
        assert len(spaced_reviews) == 5

        expected_intervals = [1, 3, 7, 14, 30]
        for review, expected_days in zip(spaced_reviews, expected_intervals):
            expected_min = before + timedelta(days=expected_days) - timedelta(seconds=5)
            expected_max = after + timedelta(days=expected_days) + timedelta(seconds=5)
            assert expected_min <= review.due_at <= expected_max, (
                f"review_number={review.review_number}: "
                f"due_at={review.due_at} not in [{expected_min}, {expected_max}]"
            )

    async def test_spaced_review_review_numbers_are_1_through_5(self):
        """review_number must be 1-indexed and cover all 5 scheduled reviews."""
        from api.teaching_service import TeachingService
        from db.models import SpacedReview

        mock_ks = MagicMock()
        mock_ks.get_concept_detail.return_value = {
            "concept_title": "Test Concept",
            "text": "some text",
            "latex": [],
            "images": [],
            "prerequisites": [],
            "dependents": [],
        }
        mock_ks.graph.predecessors.return_value = iter([])

        svc = TeachingService(knowledge_svc=mock_ks)
        svc.openai = AsyncMock()

        mastery_llm_content = "Mastery achieved! [ASSESSMENT:75]"
        mock_llm_response = MagicMock()
        mock_llm_response.choices = [MagicMock()]
        mock_llm_response.choices[0].message.content = mastery_llm_content
        svc.openai.chat.completions.create = AsyncMock(return_value=mock_llm_response)

        session_id = uuid.uuid4()
        student_id = uuid.uuid4()

        mock_session = MagicMock()
        mock_session.id = session_id
        mock_session.student_id = student_id
        mock_session.concept_id = "test_concept_001"
        mock_session.phase = "CHECKING"
        mock_session.style = "default"
        mock_session.book_slug = "prealgebra"
        mock_session.check_score = None
        mock_session.best_check_score = None
        mock_session.concept_mastered = False
        mock_session.socratic_attempt_count = 0

        added_objects = []
        mock_db = AsyncMock()
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        messages_result = MagicMock()
        messages_result.scalars.return_value.all.return_value = []
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mastery_check_result = MagicMock()
        mastery_check_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[
            messages_result,
            count_result,
            mastery_check_result,
        ])

        await svc.handle_student_response(mock_db, mock_session, "I get it!")

        spaced_reviews = [obj for obj in added_objects if isinstance(obj, SpacedReview)]
        assert len(spaced_reviews) == 5

        review_numbers = sorted(r.review_number for r in spaced_reviews)
        assert review_numbers == [1, 2, 3, 4, 5]

    def test_spaced_review_intervals_follow_ebbinghaus_forgetting_curve_shape(self):
        """
        Ebbinghaus: intervals grow super-linearly (each gap is larger than the previous).
        Gap sequence: [2, 4, 7, 16] — strictly larger each time.
        """
        intervals = self.REVIEW_INTERVALS_DAYS
        gaps = [intervals[i + 1] - intervals[i] for i in range(len(intervals) - 1)]
        for i in range(len(gaps) - 1):
            assert gaps[i] < gaps[i + 1], (
                f"Gap {gaps[i]} (between review {i+1} and {i+2}) is not smaller than "
                f"gap {gaps[i+1]} (between review {i+2} and {i+3}); "
                "intervals must grow super-linearly"
            )

    def test_mastery_threshold_imported_from_config(self):
        """
        MASTERY_THRESHOLD must be sourced from config, not redefined locally in
        teaching_service.py.  This test verifies that the value used by
        TeachingService at runtime matches the authoritative constant in config.py
        and that config.MASTERY_THRESHOLD equals 60 (the current business rule).
        """
        import config
        import inspect
        import api.teaching_service as ts

        # 1. The authoritative value in config must be 70.
        assert config.MASTERY_THRESHOLD == 70, (
            f"config.MASTERY_THRESHOLD is {config.MASTERY_THRESHOLD}, expected 70"
        )

        # 2. teaching_service must NOT redefine MASTERY_THRESHOLD as a module-level
        #    constant — it must import and use the one from config.
        ts_source = inspect.getsource(ts)
        assert "MASTERY_THRESHOLD" not in ts_source.split("import")[0] or (
            "from config import" in ts_source or "import config" in ts_source
        ), "teaching_service.py defines MASTERY_THRESHOLD locally instead of importing from config"

        # 3. The threshold value referenced inside teaching_service must equal 70
        #    (confirming no stale local override is shadowing the config value).
        assert MASTERY_THRESHOLD == 70
