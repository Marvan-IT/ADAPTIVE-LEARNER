"""
Comprehensive unit tests for the Adaptive Learning Generation Engine.

Covers:
  Group 1 — profile_builder: threshold boundary tests for every classifier
  Group 2 — generation_profile: base lookup table + engagement modifier tests
  Group 3 — remediation: graph traversal, card construction
  Group 4 — prompt_builder: system/user prompt content assertions
  Group 5 — adaptive_engine: async orchestration, retry logic, remediation injection

Test infrastructure:
  - pytest.ini sets asyncio_mode = auto, so no @pytest.mark.asyncio decorators needed
  - conftest.py inserts backend/src into sys.path; the block below duplicates it
    so this file can also be executed directly without conftest.
  - All external dependencies (LLM, knowledge service, graph) are replaced with
    unittest.mock objects — zero I/O in any test.
"""

import sys
import json
from pathlib import Path

# Ensure backend/src is importable regardless of how pytest is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from adaptive.schemas import AnalyticsSummary, LearningProfile, GenerationProfile
from adaptive.profile_builder import (
    classify_speed,
    classify_comprehension,
    classify_engagement,
    compute_confidence_score,
    classify_next_step,
    build_learning_profile,
)
from adaptive.generation_profile import build_generation_profile
from adaptive.remediation import (
    find_remediation_prereq,
    has_unmet_prereq,
    build_remediation_cards,
)
from adaptive.prompt_builder import build_adaptive_prompt, build_next_card_prompt
from adaptive.adaptive_engine import generate_adaptive_lesson, generate_next_card, load_wrong_option_pattern
from adaptive.schemas import AdaptiveLesson, CardBehaviorSignals


# =============================================================================
# Shared test fixtures / helpers
# =============================================================================

def _make_learning_profile(
    speed: str = "NORMAL",
    comprehension: str = "OK",
    engagement: str = "ENGAGED",
    confidence_score: float = 0.6,
    recommended_next_step: str = "CONTINUE",
    error_rate: float = 0.2,
) -> LearningProfile:
    """Construct a LearningProfile directly for use in generation_profile and
    prompt_builder tests without going through the full analytics pipeline."""
    return LearningProfile(
        speed=speed,
        comprehension=comprehension,
        engagement=engagement,
        confidence_score=confidence_score,
        recommended_next_step=recommended_next_step,
        error_rate=error_rate,
    )


MOCK_CONCEPT = {
    "concept_title": "Multiply and Divide Fractions",
    "chapter": "4",
    "section": "4.2",
    "text": "When multiplying fractions...",
    "latex": [r"\frac{a}{b} \times \frac{c}{d} = \frac{ac}{bd}"],
}

MOCK_PREREQ_DETAIL = {
    "concept_id": "PREALG.C4.S1",
    "concept_title": "Introduction to Fractions",
    "chapter": "4",
    "section": "4.1",
    "text": "A fraction represents part of a whole number.",
    "latex": [],
    "images": [],
    "prerequisites": [],
    "dependents": ["PREALG.C4.S2"],
}

MOCK_LESSON_JSON = json.dumps(
    {
        "concept_explanation": "Fractions are parts of a whole.",
        "cards": [
            {
                "type": "explain",
                "title": "What are fractions?",
                "content": "A fraction represents part of a whole.",
                "answer": None,
                "hints": ["Think of a pizza cut into slices"],
                "difficulty": 1,
                "fun_element": None,
            }
        ],
    }
)

# Valid AnalyticsSummary used by engine integration tests.
ANALYTICS = AnalyticsSummary(
    student_id="abc",
    concept_id="PREALG.C4.S2",
    time_spent_sec=820,
    expected_time_sec=450,
    attempts=6,
    wrong_attempts=4,
    hints_used=7,
    revisits=3,
    recent_dropoffs=1,
    skip_rate=0.05,
    quiz_score=0.4,
    last_7d_sessions=2,
)


def _make_mock_llm(content: str = MOCK_LESSON_JSON) -> AsyncMock:
    """Return a mock AsyncOpenAI client whose first completion returns *content*."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = content
    mock_llm = AsyncMock()
    mock_llm.chat.completions.create = AsyncMock(return_value=mock_response)
    return mock_llm


def _make_mock_ks(has_prereqs: bool = False) -> MagicMock:
    """Return a mock KnowledgeService suitable for engine integration tests."""
    mock_ks = MagicMock()
    mock_ks.get_concept_detail.return_value = {
        "concept_id": "PREALG.C4.S2",
        "concept_title": "Multiply and Divide Fractions",
        "chapter": "4",
        "section": "4.2",
        "text": "When multiplying fractions, multiply the numerators and denominators.",
        "latex": [],
        "images": [],
        "prerequisites": ["PREALG.C4.S1"] if has_prereqs else [],
        "dependents": [],
    }
    if has_prereqs:
        mock_ks.graph.predecessors.return_value = iter(["PREALG.C4.S1"])
    else:
        mock_ks.graph.predecessors.return_value = iter([])
    return mock_ks


# =============================================================================
# Group 1 — profile_builder: threshold boundary tests
# =============================================================================

class TestClassifySpeed:
    """Speed classification is gated by strict inequality against 1.5× and 0.7× thresholds."""

    def test_classify_speed_slow_above_1_5x_threshold(self):
        # 226 > 150 * 1.5 (225) — strictly above the boundary → SLOW
        assert classify_speed(226, 150, 3) == "SLOW"

    def test_classify_speed_slow_boundary_exactly_1_5x_returns_normal(self):
        # 225 is NOT > 225 — boundary is exclusive, so not SLOW
        # Also not FAST: 225 < 0.7*150=105 is False → NORMAL
        assert classify_speed(225, 150, 3) == "NORMAL"

    def test_classify_speed_fast_single_attempt(self):
        # 100 < 200 * 0.7 (140) AND attempts == 1 → FAST
        assert classify_speed(100, 200, 1) == "FAST"

    def test_classify_speed_fast_blocked_by_multiple_attempts(self):
        # Time qualifies (100 < 140) but attempts == 2 prevents FAST → NORMAL
        assert classify_speed(100, 200, 2) == "NORMAL"

    def test_classify_speed_normal_midrange(self):
        # 200 is not > 300 (1.5*200) and not < 140 (0.7*200) → NORMAL
        assert classify_speed(200, 200, 3) == "NORMAL"

    def test_classify_speed_slow_well_above_threshold(self):
        # Clear SLOW case: 700 > 1.5*300 = 450
        assert classify_speed(700, 300, 1) == "SLOW"

    def test_classify_speed_fast_boundary_exactly_0_7x_returns_normal(self):
        # 140 is NOT < 140 (0.7*200) — FAST threshold is exclusive → NORMAL
        assert classify_speed(140, 200, 1) == "NORMAL"


class TestClassifyComprehension:
    """Comprehension thresholds: error_rate >= 0.5 or quiz < 0.5 → STRUGGLING;
    quiz >= 0.8 and error <= 0.2 and hints <= 2 → STRONG; else OK."""

    def test_classify_comprehension_struggling_by_error_rate(self):
        # wrong=5, attempts=10 → error_rate = 0.5 >= 0.5 → STRUGGLING
        assert classify_comprehension(5, 10, 0.7, 1) == "STRUGGLING"

    def test_classify_comprehension_struggling_by_quiz_score(self):
        # quiz=0.49 < 0.5 → STRUGGLING regardless of low error rate
        assert classify_comprehension(1, 10, 0.49, 1) == "STRUGGLING"

    def test_classify_comprehension_strong_all_signals(self):
        # error_rate=0.1, quiz=0.85, hints=1 — all STRONG conditions met
        assert classify_comprehension(1, 10, 0.85, 1) == "STRONG"

    def test_classify_comprehension_ok_middle(self):
        # error_rate=0.2, quiz=0.7 — not STRUGGLING, not STRONG (hints=4 > 2) → OK
        assert classify_comprehension(2, 10, 0.7, 4) == "OK"

    def test_classify_comprehension_strong_boundary_quiz_0_8(self):
        # quiz==0.8 (inclusive), error==0.2 (inclusive), hints==2 (inclusive) → STRONG
        assert classify_comprehension(2, 10, 0.8, 2) == "STRONG"

    def test_classify_comprehension_strong_boundary_error_above_0_2_returns_ok(self):
        # error_rate = 3/10 = 0.3 > 0.2; STRONG gate fails → OK
        assert classify_comprehension(3, 10, 0.85, 1) == "OK"

    def test_classify_comprehension_strong_boundary_hints_3_returns_ok(self):
        # hints=3 > 2; STRONG gate fails → OK
        assert classify_comprehension(1, 10, 0.85, 3) == "OK"

    def test_classify_comprehension_struggling_overrides_high_quiz_when_error_high(self):
        # STRUGGLING check runs first: error_rate=0.5 fires before STRONG check
        assert classify_comprehension(5, 10, 0.95, 0) == "STRUGGLING"


class TestClassifyEngagement:
    """BORED = fast+no errors; OVERWHELMED = many hints; ENGAGED = everything else."""

    def test_classify_engagement_bored_fast_no_errors(self):
        # time=30 < expected=120*0.35=42, wrong=0 → BORED
        assert classify_engagement(30.0, 120.0, 0, 0) == "BORED"

    def test_classify_engagement_not_bored_at_boundary(self):
        # time=42 == expected*0.35=42 — boundary NOT strict → not BORED, hints=5 → OVERWHELMED
        assert classify_engagement(42.0, 120.0, 0, 5) == "OVERWHELMED"

    def test_classify_engagement_not_bored_and_not_overwhelmed_returns_engaged(self):
        # time=90, expected=120, wrong=2, hints=4 → ENGAGED
        assert classify_engagement(90.0, 120.0, 2, 4) == "ENGAGED"

    def test_classify_engagement_overwhelmed_by_hints_alone(self):
        # hints=5, no revisit requirement → OVERWHELMED
        assert classify_engagement(60.0, 120.0, 0, 5) == "OVERWHELMED"

    def test_classify_engagement_not_overwhelmed_below_hint_threshold(self):
        # hints=4 < 5 → not OVERWHELMED → ENGAGED
        assert classify_engagement(60.0, 120.0, 0, 4) == "ENGAGED"

    def test_classify_engagement_not_bored_when_wrong_attempts_exist(self):
        # time=10 (very fast) but wrong=2 → BORED guard requires wrong_attempts==0
        assert classify_engagement(10.0, 120.0, 2, 0) == "ENGAGED"

    def test_classify_engagement_bored_takes_priority_over_hints(self):
        # time=20 < expected*0.35=42, wrong=0, hints=10 — BORED checked first
        assert classify_engagement(20.0, 120.0, 0, 10) == "BORED"

    def test_classify_engagement_overwhelmed_exact_boundary(self):
        # hints exactly 5 — inclusive boundary → OVERWHELMED
        assert classify_engagement(90.0, 120.0, 1, 5) == "OVERWHELMED"


class TestComputeConfidenceScore:
    """Formula: clamp(quiz - (error_rate * 0.4) - (min(hints,10)/10 * 0.2), 0.0, 1.0)"""

    def test_confidence_score_perfect(self):
        # quiz=1.0, no errors, no hints → raw=1.0 → 1.0
        assert compute_confidence_score(1.0, 0, 1, 0) == pytest.approx(1.0)

    def test_confidence_score_zero_clamped(self):
        # quiz=0.0, all wrong (error=1.0), max hints → raw = 0-(0.4)-(0.2) = -0.6 → clamp 0.0
        result = compute_confidence_score(0.0, 6, 6, 10)
        assert result == pytest.approx(0.0)

    def test_confidence_score_formula_mid_values(self):
        # quiz=0.7, wrong=2/4 (error=0.5), hints=6
        # raw = 0.7 - (0.5*0.4) - (0.6*0.2) = 0.7 - 0.2 - 0.12 = 0.38
        result = compute_confidence_score(0.7, 2, 4, 6)
        assert result == pytest.approx(0.38, abs=1e-6)

    def test_confidence_score_hint_penalty_caps_at_10_hints(self):
        # hints=20 is capped to 10 for penalty: min(20,10)/10 = 1.0
        # raw = 0.8 - (0*0.4) - (1.0*0.2) = 0.6
        result = compute_confidence_score(0.8, 0, 5, 20)
        assert result == pytest.approx(0.6, abs=1e-6)

    def test_confidence_score_clamped_to_1_0_when_over(self):
        # With no penalties, quiz=1.0 → exactly 1.0, never above
        result = compute_confidence_score(1.0, 0, 1, 0)
        assert result <= 1.0

    def test_confidence_score_error_penalty_partial(self):
        # quiz=0.9, error_rate=0.25 (1/4), hints=0
        # raw = 0.9 - (0.25*0.4) - 0 = 0.9 - 0.1 = 0.8
        result = compute_confidence_score(0.9, 1, 4, 0)
        assert result == pytest.approx(0.8, abs=1e-6)


class TestClassifyNextStep:
    """Next step priority: REMEDIATE_PREREQ > ADD_PRACTICE > CHALLENGE > CONTINUE."""

    def test_next_step_remediate_prereq_when_struggling_with_unmet_prereq(self):
        # STRUGGLING + unmet prereq → highest priority action
        assert classify_next_step("STRUGGLING", "SLOW", has_unmet_prereq=True) == "REMEDIATE_PREREQ"

    def test_next_step_add_practice_when_struggling_no_unmet_prereq(self):
        # STRUGGLING but all prereqs mastered → practice more on this concept
        assert classify_next_step("STRUGGLING", "NORMAL", has_unmet_prereq=False) == "ADD_PRACTICE"

    def test_next_step_challenge_when_fast_and_strong(self):
        # FAST speed + STRONG comprehension → student is ready for harder material
        assert classify_next_step("STRONG", "FAST", has_unmet_prereq=False) == "CHALLENGE"

    def test_next_step_continue_normal_ok(self):
        # Normal progress — no special action needed
        assert classify_next_step("OK", "NORMAL", has_unmet_prereq=False) == "CONTINUE"

    def test_next_step_continue_when_fast_but_not_strong(self):
        # FAST speed but only OK comprehension → CHALLENGE requires STRONG
        assert classify_next_step("OK", "FAST", has_unmet_prereq=False) == "CONTINUE"

    def test_next_step_struggling_prereq_overrides_fast_speed(self):
        # Even if speed is FAST, STRUGGLING + unmet prereq → REMEDIATE_PREREQ
        assert classify_next_step("STRUGGLING", "FAST", has_unmet_prereq=True) == "REMEDIATE_PREREQ"

    def test_next_step_add_practice_struggling_fast_no_prereq(self):
        # STRUGGLING overrides speed when no unmet prereq
        assert classify_next_step("STRUGGLING", "FAST", has_unmet_prereq=False) == "ADD_PRACTICE"


class TestBuildLearningProfile:
    """build_learning_profile orchestrates all classifiers and exposes error_rate."""

    def test_build_learning_profile_error_rate_field_is_populated(self):
        analytics = AnalyticsSummary(
            student_id="s1",
            concept_id="C1",
            time_spent_sec=300,
            expected_time_sec=300,
            attempts=4,
            wrong_attempts=2,
            hints_used=1,
            revisits=0,
            recent_dropoffs=0,
            skip_rate=0.0,
            quiz_score=0.7,
            last_7d_sessions=3,
        )
        profile = build_learning_profile(analytics, has_unmet_prereq=False)
        assert profile.error_rate == pytest.approx(0.5, abs=1e-4)

    def test_build_learning_profile_returns_learning_profile_instance(self):
        analytics = AnalyticsSummary(
            student_id="s2",
            concept_id="C2",
            time_spent_sec=200,
            expected_time_sec=300,
            attempts=2,
            wrong_attempts=0,
            hints_used=0,
            revisits=0,
            recent_dropoffs=0,
            skip_rate=0.0,
            quiz_score=0.9,
            last_7d_sessions=5,
        )
        profile = build_learning_profile(analytics, has_unmet_prereq=False)
        assert isinstance(profile, LearningProfile)

    def test_analytics_summary_rejects_wrong_attempts_exceeding_attempts(self):
        # Business rule: wrong_attempts > attempts is invalid data
        with pytest.raises(Exception):
            AnalyticsSummary(
                student_id="s3",
                concept_id="C3",
                time_spent_sec=100,
                expected_time_sec=100,
                attempts=3,
                wrong_attempts=5,  # Invalid: 5 > 3
                hints_used=0,
                revisits=0,
                recent_dropoffs=0,
                skip_rate=0.0,
                quiz_score=0.5,
                last_7d_sessions=1,
            )


# =============================================================================
# Group 2 — generation_profile: base table + engagement modifier tests
# =============================================================================

class TestBuildGenerationProfileBaseLookup:
    """Each (speed, comprehension) cell must return exactly the values from the DLD table."""

    def test_slow_struggling_engaged_base_values(self):
        profile = _make_learning_profile(speed="SLOW", comprehension="STRUGGLING", engagement="ENGAGED")
        gp = build_generation_profile(profile)
        assert gp.explanation_depth == "HIGH"
        assert gp.reading_level == "KID_SIMPLE"
        assert gp.step_by_step is True
        assert gp.analogy_level == pytest.approx(0.8)
        assert gp.fun_level == pytest.approx(0.4)
        assert gp.card_count == 12
        assert gp.practice_count == 7
        assert gp.checkpoint_frequency == 2
        assert gp.max_paragraph_lines == 2
        assert gp.emoji_policy == "SPARING"

    def test_slow_ok_engaged_base_values(self):
        profile = _make_learning_profile(speed="SLOW", comprehension="OK", engagement="ENGAGED")
        gp = build_generation_profile(profile)
        assert gp.explanation_depth == "HIGH"
        assert gp.reading_level == "SIMPLE"
        assert gp.step_by_step is True
        assert gp.card_count == 11
        assert gp.practice_count == 6
        assert gp.checkpoint_frequency == 2
        assert gp.max_paragraph_lines == 3
        assert gp.emoji_policy == "NONE"

    def test_slow_strong_engaged_base_values(self):
        profile = _make_learning_profile(speed="SLOW", comprehension="STRONG", engagement="ENGAGED")
        gp = build_generation_profile(profile)
        assert gp.explanation_depth == "MEDIUM"
        assert gp.reading_level == "SIMPLE"
        assert gp.step_by_step is True
        assert gp.card_count == 10
        assert gp.practice_count == 5
        assert gp.checkpoint_frequency == 3

    def test_normal_ok_engaged_base_values(self):
        profile = _make_learning_profile(speed="NORMAL", comprehension="OK", engagement="ENGAGED")
        gp = build_generation_profile(profile)
        assert gp.explanation_depth == "MEDIUM"
        assert gp.reading_level == "STANDARD"
        assert gp.step_by_step is False
        assert gp.card_count == 9
        assert gp.practice_count == 4
        assert gp.checkpoint_frequency == 3
        assert gp.max_paragraph_lines == 4
        assert gp.emoji_policy == "NONE"

    def test_normal_struggling_engaged_base_values(self):
        profile = _make_learning_profile(speed="NORMAL", comprehension="STRUGGLING", engagement="ENGAGED")
        gp = build_generation_profile(profile)
        assert gp.explanation_depth == "HIGH"
        assert gp.reading_level == "SIMPLE"
        assert gp.step_by_step is True
        assert gp.card_count == 11
        assert gp.practice_count == 6
        assert gp.emoji_policy == "SPARING"

    def test_normal_strong_engaged_base_values(self):
        profile = _make_learning_profile(speed="NORMAL", comprehension="STRONG", engagement="ENGAGED")
        gp = build_generation_profile(profile)
        assert gp.explanation_depth == "LOW"
        assert gp.reading_level == "STANDARD"
        assert gp.step_by_step is False
        assert gp.card_count == 8
        assert gp.practice_count == 3
        assert gp.checkpoint_frequency == 4

    def test_fast_strong_engaged_base_values(self):
        profile = _make_learning_profile(speed="FAST", comprehension="STRONG", engagement="ENGAGED")
        gp = build_generation_profile(profile)
        assert gp.explanation_depth == "LOW"
        assert gp.reading_level == "STANDARD"
        assert gp.step_by_step is False
        assert gp.card_count == 7
        assert gp.practice_count == 3
        assert gp.checkpoint_frequency == 5
        assert gp.max_paragraph_lines == 5
        assert gp.emoji_policy == "NONE"

    def test_fast_ok_engaged_base_values(self):
        profile = _make_learning_profile(speed="FAST", comprehension="OK", engagement="ENGAGED")
        gp = build_generation_profile(profile)
        assert gp.explanation_depth == "LOW"
        assert gp.reading_level == "STANDARD"
        assert gp.step_by_step is False
        assert gp.card_count == 8
        assert gp.practice_count == 3
        assert gp.checkpoint_frequency == 4
        assert gp.max_paragraph_lines == 5

    def test_fast_struggling_engaged_base_values(self):
        profile = _make_learning_profile(speed="FAST", comprehension="STRUGGLING", engagement="ENGAGED")
        gp = build_generation_profile(profile)
        assert gp.explanation_depth == "HIGH"
        assert gp.reading_level == "SIMPLE"
        assert gp.step_by_step is True
        assert gp.card_count == 10
        assert gp.practice_count == 6
        assert gp.checkpoint_frequency == 2


class TestBuildGenerationProfileEngagementModifiers:
    """Engagement modifiers are applied additively on top of the base lookup."""

    def test_bored_modifier_increases_fun_level_by_0_3(self):
        # NORMAL + OK + BORED: base fun=0.2, +0.3 → 0.5
        profile = _make_learning_profile(speed="NORMAL", comprehension="OK", engagement="BORED")
        gp = build_generation_profile(profile)
        assert gp.fun_level == pytest.approx(0.5)

    def test_bored_modifier_sets_emoji_policy_to_sparing(self):
        # BORED always promotes emoji to SPARING regardless of base
        profile = _make_learning_profile(speed="NORMAL", comprehension="OK", engagement="BORED")
        gp = build_generation_profile(profile)
        assert gp.emoji_policy == "SPARING"

    def test_bored_modifier_reduces_card_count_by_1(self):
        # NORMAL + OK + BORED: base card_count=9, -1 = max(7, 8) = 8
        profile = _make_learning_profile(speed="NORMAL", comprehension="OK", engagement="BORED")
        gp = build_generation_profile(profile)
        assert gp.card_count == 8

    def test_bored_modifier_card_count_floor_is_7(self):
        # FAST + STRONG + BORED: base=7, max(7, 7-1) = 7 (floor prevents going below 7)
        profile = _make_learning_profile(speed="FAST", comprehension="STRONG", engagement="BORED")
        gp = build_generation_profile(profile)
        assert gp.card_count == 7

    def test_bored_modifier_fun_level_capped_at_1_0(self):
        # Use a combination where base fun + 0.3 would exceed 1.0 to verify the cap.
        # SLOW + STRUGGLING has base fun=0.4; +0.3=0.7 (does not hit cap)
        # Directly verify cap: manually check FAST+OK base fun=0.2; +0.3=0.5 (≤ 1.0)
        # To hit cap: SLOW+STRUGGLING has fun=0.4+0.3=0.7; still under.
        # The cap logic is min(1.0, x+0.3) — verify it never exceeds 1.0
        profile = _make_learning_profile(speed="SLOW", comprehension="STRUGGLING", engagement="BORED")
        gp = build_generation_profile(profile)
        assert gp.fun_level <= 1.0

    def test_overwhelmed_modifier_reduces_card_count_by_3(self):
        # NORMAL + OK + OVERWHELMED: base=9, max(7, 9-3) = 7
        profile = _make_learning_profile(speed="NORMAL", comprehension="OK", engagement="OVERWHELMED")
        gp = build_generation_profile(profile)
        assert gp.card_count == max(7, 9 - 3)

    def test_overwhelmed_modifier_card_count_floor_is_7(self):
        # FAST + STRONG + OVERWHELMED: base=7, max(7, 7-3) = 7 (floor prevents negative)
        profile = _make_learning_profile(speed="FAST", comprehension="STRONG", engagement="OVERWHELMED")
        gp = build_generation_profile(profile)
        assert gp.card_count == 7

    def test_overwhelmed_modifier_forces_step_by_step_true(self):
        # step_by_step must be True for OVERWHELMED regardless of base setting
        profile = _make_learning_profile(speed="NORMAL", comprehension="OK", engagement="OVERWHELMED")
        gp = build_generation_profile(profile)
        assert gp.step_by_step is True

    def test_overwhelmed_modifier_reduces_practice_count_floor_3(self):
        # NORMAL + OK + OVERWHELMED: base practice=4, max(3, 4-1) = 3
        profile = _make_learning_profile(speed="NORMAL", comprehension="OK", engagement="OVERWHELMED")
        gp = build_generation_profile(profile)
        assert gp.practice_count == 3

    def test_overwhelmed_modifier_increases_analogy_level_by_0_2(self):
        # FAST + STRONG + OVERWHELMED: base analogy=0.2, +0.2 = 0.4
        profile = _make_learning_profile(speed="FAST", comprehension="STRONG", engagement="OVERWHELMED")
        gp = build_generation_profile(profile)
        assert gp.analogy_level == pytest.approx(0.4)

    def test_overwhelmed_modifier_analogy_level_capped_at_1_0(self):
        # SLOW + STRUGGLING + OVERWHELMED: base analogy=0.8, min(1.0, 0.8+0.2) = 1.0
        profile = _make_learning_profile(speed="SLOW", comprehension="STRUGGLING", engagement="OVERWHELMED")
        gp = build_generation_profile(profile)
        assert gp.analogy_level == pytest.approx(1.0)

    def test_overwhelmed_practice_floor_3_not_broken_when_base_practice_already_3(self):
        # FAST + STRONG + OVERWHELMED: base practice=3, max(3, 3-1=2) = 3
        profile = _make_learning_profile(speed="FAST", comprehension="STRONG", engagement="OVERWHELMED")
        gp = build_generation_profile(profile)
        assert gp.practice_count == 3

    def test_engaged_modifier_leaves_all_values_unchanged(self):
        # ENGAGED means no modifications — verify against known base values
        profile = _make_learning_profile(speed="NORMAL", comprehension="OK", engagement="ENGAGED")
        gp = build_generation_profile(profile)
        # These are the exact base values from the DLD table for NORMAL+OK
        assert gp.fun_level == pytest.approx(0.2)
        assert gp.emoji_policy == "NONE"
        assert gp.card_count == 9
        assert gp.practice_count == 4
        assert gp.analogy_level == pytest.approx(0.5)


# =============================================================================
# Group 3 — remediation: graph traversal + card construction
# =============================================================================

class TestFindRemediationPrereq:
    """One-hop graph traversal; mastery_store keys absent = unmastered."""

    def test_find_prereq_returns_first_unmastered_prereq(self):
        # "A" is mastered, "B" is not → returns "B"
        mock_ks = MagicMock()
        mock_ks.graph.predecessors.return_value = iter(["A", "B"])
        result = find_remediation_prereq("TARGET", mock_ks, {"A": True, "B": False})
        assert result == "B"

    def test_find_prereq_returns_none_when_all_prereqs_mastered(self):
        mock_ks = MagicMock()
        mock_ks.graph.predecessors.return_value = iter(["A"])
        result = find_remediation_prereq("TARGET", mock_ks, {"A": True})
        assert result is None

    def test_find_prereq_returns_none_when_no_prereqs_exist(self):
        mock_ks = MagicMock()
        mock_ks.graph.predecessors.return_value = iter([])
        result = find_remediation_prereq("TARGET", mock_ks, {})
        assert result is None

    def test_find_prereq_treats_missing_mastery_store_key_as_unmastered(self):
        # mastery_store is empty — every prereq is implicitly unmastered
        mock_ks = MagicMock()
        mock_ks.graph.predecessors.return_value = iter(["PREREQ_1"])
        result = find_remediation_prereq("TARGET", mock_ks, {})
        assert result == "PREREQ_1"

    def test_find_prereq_handles_graph_exception_gracefully(self):
        # If the graph raises (e.g., node not in graph), function returns None
        mock_ks = MagicMock()
        mock_ks.graph.predecessors.side_effect = Exception("NetworkX node not found")
        result = find_remediation_prereq("MISSING_CONCEPT", mock_ks, {})
        assert result is None

    def test_find_prereq_returns_first_of_multiple_unmastered_prereqs(self):
        # Both "A" and "B" unmastered — should return "A" (first in insertion order)
        mock_ks = MagicMock()
        mock_ks.graph.predecessors.return_value = iter(["A", "B"])
        result = find_remediation_prereq("TARGET", mock_ks, {})
        assert result == "A"


class TestHasUnmetPrereq:
    """has_unmet_prereq is a thin boolean wrapper over find_remediation_prereq."""

    def test_has_unmet_prereq_true_when_prereq_unmastered(self):
        mock_ks = MagicMock()
        mock_ks.graph.predecessors.return_value = iter(["P1"])
        assert has_unmet_prereq("C1", mock_ks, {}) is True

    def test_has_unmet_prereq_false_when_all_mastered(self):
        mock_ks = MagicMock()
        mock_ks.graph.predecessors.return_value = iter(["P1"])
        assert has_unmet_prereq("C1", mock_ks, {"P1": True}) is False

    def test_has_unmet_prereq_false_when_no_prereqs(self):
        mock_ks = MagicMock()
        mock_ks.graph.predecessors.return_value = iter([])
        assert has_unmet_prereq("C1", mock_ks, {}) is False


class TestBuildRemediationCards:
    """Template-based cards: exactly 3, specific types, titles, and difficulty values."""

    def _get_cards(self) -> list[dict]:
        return build_remediation_cards(
            "PREALG.C4.S1",
            {
                "concept_title": "Introduction to Fractions",
                "text": "A fraction is a way to represent parts of a whole.",
            },
        )

    def test_build_remediation_cards_returns_exactly_3_cards(self):
        cards = self._get_cards()
        assert len(cards) == 3

    def test_build_remediation_cards_all_titles_start_with_review_prefix(self):
        cards = self._get_cards()
        for card in cards:
            assert card["title"].startswith("[Review]"), (
                f"Expected title to start with '[Review]', got: {card['title']!r}"
            )

    def test_build_remediation_cards_types_are_explain_example_checkpoint(self):
        cards = self._get_cards()
        assert cards[0]["type"] == "explain"
        assert cards[1]["type"] == "example"
        assert cards[2]["type"] == "checkpoint"

    def test_build_remediation_cards_difficulty_values_are_1_1_2(self):
        cards = self._get_cards()
        assert cards[0]["difficulty"] == 1
        assert cards[1]["difficulty"] == 1
        assert cards[2]["difficulty"] == 2

    def test_build_remediation_cards_uses_prereq_title_in_card_titles(self):
        cards = self._get_cards()
        for card in cards:
            assert "Introduction to Fractions" in card["title"], (
                f"Expected prereq title in card title, got: {card['title']!r}"
            )

    def test_build_remediation_cards_each_card_has_required_fields(self):
        cards = self._get_cards()
        required_fields = {"type", "title", "content", "answer", "hints", "difficulty", "fun_element"}
        for card in cards:
            assert required_fields.issubset(card.keys()), (
                f"Card missing required fields: {required_fields - card.keys()}"
            )

    def test_build_remediation_cards_with_empty_text_does_not_crash(self):
        # When text is absent the card should fall back to a descriptive string
        cards = build_remediation_cards("C1", {"concept_title": "Basics", "text": ""})
        assert len(cards) == 3
        assert all(card["title"].startswith("[Review]") for card in cards)

    def test_build_remediation_cards_uses_concept_id_as_fallback_title(self):
        # When concept_title key is missing, concept_id is used as fallback
        cards = build_remediation_cards("FALLBACK_ID", {"text": "Some text"})
        # All cards should still have the [Review] prefix and reference the fallback
        assert len(cards) == 3
        for card in cards:
            assert card["title"].startswith("[Review]")


# =============================================================================
# Group 4 — prompt_builder: system and user prompt content assertions
# =============================================================================

class TestBuildAdaptivePromptSystemPrompt:
    """System prompt must contain mandatory structural sections and mode-specific blocks."""

    def _build(
        self,
        speed: str = "NORMAL",
        comprehension: str = "OK",
        engagement: str = "ENGAGED",
        language: str = "en",
        prereq_detail=None,
    ) -> tuple[str, str]:
        profile = _make_learning_profile(
            speed=speed,
            comprehension=comprehension,
            engagement=engagement,
        )
        gp = build_generation_profile(profile)
        return build_adaptive_prompt(MOCK_CONCEPT, profile, gp, prereq_detail, language)

    def test_system_prompt_contains_generation_controls_section(self):
        system_prompt, _ = self._build()
        assert "GENERATION CONTROLS" in system_prompt

    def test_system_prompt_contains_explanation_depth_field(self):
        system_prompt, _ = self._build()
        # The system prompt renders this as "Explanation depth:" (see prompt_builder.py line 151)
        assert "Explanation depth" in system_prompt

    def test_system_prompt_contains_difficulty_ramp_section(self):
        system_prompt, _ = self._build()
        assert "DIFFICULTY RAMP" in system_prompt

    def test_system_prompt_contains_json_schema(self):
        system_prompt, _ = self._build()
        assert "concept_explanation" in system_prompt
        assert "cards" in system_prompt

    def test_slow_mode_block_present_in_system_prompt(self):
        system_prompt, _ = self._build(speed="SLOW", comprehension="OK")
        assert "SLOW LEARNER MODE" in system_prompt

    def test_slow_mode_block_absent_for_non_slow_student(self):
        system_prompt, _ = self._build(speed="NORMAL", comprehension="OK")
        assert "SLOW LEARNER MODE" not in system_prompt

    def test_fast_strong_mode_block_present_in_system_prompt(self):
        system_prompt, _ = self._build(speed="FAST", comprehension="STRONG")
        assert "FAST/STRONG LEARNER MODE" in system_prompt

    def test_fast_strong_mode_block_absent_when_only_fast(self):
        system_prompt, _ = self._build(speed="FAST", comprehension="OK")
        assert "FAST/STRONG LEARNER MODE" not in system_prompt

    def test_fast_strong_mode_block_absent_when_only_strong(self):
        system_prompt, _ = self._build(speed="NORMAL", comprehension="STRONG")
        assert "FAST/STRONG LEARNER MODE" not in system_prompt

    def test_bored_mode_block_present_in_system_prompt(self):
        system_prompt, _ = self._build(speed="NORMAL", comprehension="OK", engagement="BORED")
        assert "BORED LEARNER MODE" in system_prompt

    def test_bored_mode_block_absent_for_non_bored_student(self):
        system_prompt, _ = self._build(speed="NORMAL", comprehension="OK", engagement="ENGAGED")
        assert "BORED LEARNER MODE" not in system_prompt

    def test_system_prompt_language_name_appears_for_non_english(self):
        system_prompt, _ = self._build(language="ta")
        assert "Tamil" in system_prompt

    def test_system_prompt_language_defaults_to_english(self):
        system_prompt, _ = self._build(language="en")
        assert "English" in system_prompt


class TestBuildAdaptivePromptUserPrompt:
    """User prompt must include concept data, optional prereq block, and closing instruction."""

    def _build(
        self,
        speed: str = "NORMAL",
        comprehension: str = "OK",
        engagement: str = "ENGAGED",
        prereq_detail=None,
        concept_text_override: str | None = None,
    ) -> tuple[str, str]:
        concept = dict(MOCK_CONCEPT)
        if concept_text_override is not None:
            concept["text"] = concept_text_override
        profile = _make_learning_profile(speed=speed, comprehension=comprehension, engagement=engagement)
        gp = build_generation_profile(profile)
        return build_adaptive_prompt(concept, profile, gp, prereq_detail)

    def test_user_prompt_contains_concept_title(self):
        _, user_prompt = self._build()
        assert "Multiply and Divide Fractions" in user_prompt

    def test_prereq_remediation_block_present_when_prereq_detail_provided(self):
        _, user_prompt = self._build(prereq_detail=MOCK_PREREQ_DETAIL)
        assert "PREREQUISITE REMEDIATION" in user_prompt

    def test_prereq_remediation_block_absent_when_prereq_detail_is_none(self):
        _, user_prompt = self._build(prereq_detail=None)
        assert "PREREQUISITE REMEDIATION" not in user_prompt

    def test_user_prompt_ends_with_json_only_instruction(self):
        _, user_prompt = self._build()
        assert "Return ONLY the JSON object" in user_prompt

    def test_concept_source_text_is_truncated_to_3000_chars_maximum(self):
        # Supply a 5000-char text; the source block in the prompt must be truncated.
        # We use 3001 consecutive x's as a sentinel — if truncation happened at 3000,
        # that substring can never appear (the template itself contains no such run).
        long_text = "x" * 5000
        _, user_prompt = self._build(concept_text_override=long_text)
        assert "x" * 3001 not in user_prompt

    def test_concept_source_text_not_truncated_when_under_limit(self):
        # Short text should appear fully without a truncation marker
        _, user_prompt = self._build(concept_text_override="Short text.")
        assert "[... source text truncated ...]" not in user_prompt

    def test_concept_source_text_truncation_marker_present_for_long_text(self):
        long_text = "y" * 5000
        _, user_prompt = self._build(concept_text_override=long_text)
        assert "[... source text truncated ...]" in user_prompt

    def test_prereq_title_appears_in_prereq_block(self):
        _, user_prompt = self._build(prereq_detail=MOCK_PREREQ_DETAIL)
        assert "Introduction to Fractions" in user_prompt


# =============================================================================
# Group 5 — engine integration: async orchestration tests
# =============================================================================

class TestGenerateAdaptiveLesson:
    """Full pipeline tests; all external I/O is mocked."""

    async def test_generate_lesson_happy_path_no_remediation_returns_adaptive_lesson(self):
        # When all prereqs are mastered, the engine produces a valid AdaptiveLesson
        mock_ks = _make_mock_ks(has_prereqs=False)
        mock_llm = _make_mock_llm()

        result = await generate_adaptive_lesson(
            student_id="abc",
            concept_id="PREALG.C4.S2",
            analytics_summary=ANALYTICS,
            knowledge_svc=mock_ks,
            mastery_store={},
            llm_client=mock_llm,
        )

        assert isinstance(result, AdaptiveLesson)

    async def test_generate_lesson_happy_path_remediation_not_included_when_no_prereqs(self):
        mock_ks = _make_mock_ks(has_prereqs=False)
        mock_llm = _make_mock_llm()

        result = await generate_adaptive_lesson(
            student_id="abc",
            concept_id="PREALG.C4.S2",
            analytics_summary=ANALYTICS,
            knowledge_svc=mock_ks,
            mastery_store={},
            llm_client=mock_llm,
        )

        assert result.remediation.included is False

    async def test_generate_lesson_happy_path_lesson_contains_at_least_one_card(self):
        mock_ks = _make_mock_ks(has_prereqs=False)
        mock_llm = _make_mock_llm()

        result = await generate_adaptive_lesson(
            student_id="abc",
            concept_id="PREALG.C4.S2",
            analytics_summary=ANALYTICS,
            knowledge_svc=mock_ks,
            mastery_store={},
            llm_client=mock_llm,
        )

        assert len(result.lesson.cards) >= 1

    async def test_struggling_student_with_unmet_prereq_triggers_remediation(self):
        # has_prereqs=True and mastery_store is empty → prereq is unmastered
        mock_ks = _make_mock_ks(has_prereqs=True)
        # get_concept_detail must also return the prereq when called for "PREALG.C4.S1"
        call_count = {"n": 0}
        original_return = mock_ks.get_concept_detail.return_value

        def concept_detail_side_effect(cid):
            if cid == "PREALG.C4.S1":
                return MOCK_PREREQ_DETAIL
            return original_return

        mock_ks.get_concept_detail.side_effect = concept_detail_side_effect
        mock_llm = _make_mock_llm()

        result = await generate_adaptive_lesson(
            student_id="abc",
            concept_id="PREALG.C4.S2",
            analytics_summary=ANALYTICS,
            knowledge_svc=mock_ks,
            mastery_store={},  # empty = nothing mastered
            llm_client=mock_llm,
        )

        assert result.remediation.included is True

    async def test_remediation_prereq_concept_id_is_set_correctly(self):
        mock_ks = _make_mock_ks(has_prereqs=True)
        original_return = mock_ks.get_concept_detail.return_value

        def concept_detail_side_effect(cid):
            if cid == "PREALG.C4.S1":
                return MOCK_PREREQ_DETAIL
            return original_return

        mock_ks.get_concept_detail.side_effect = concept_detail_side_effect
        mock_llm = _make_mock_llm()

        result = await generate_adaptive_lesson(
            student_id="abc",
            concept_id="PREALG.C4.S2",
            analytics_summary=ANALYTICS,
            knowledge_svc=mock_ks,
            mastery_store={},
            llm_client=mock_llm,
        )

        assert result.remediation.prereq_concept_id == "PREALG.C4.S1"

    async def test_remediation_prepends_3_review_cards_before_main_lesson_cards(self):
        mock_ks = _make_mock_ks(has_prereqs=True)
        original_return = mock_ks.get_concept_detail.return_value

        def concept_detail_side_effect(cid):
            if cid == "PREALG.C4.S1":
                return MOCK_PREREQ_DETAIL
            return original_return

        mock_ks.get_concept_detail.side_effect = concept_detail_side_effect
        mock_llm = _make_mock_llm()

        result = await generate_adaptive_lesson(
            student_id="abc",
            concept_id="PREALG.C4.S2",
            analytics_summary=ANALYTICS,
            knowledge_svc=mock_ks,
            mastery_store={},
            llm_client=mock_llm,
        )

        # 3 remediation cards prepended + at least 1 main card from MOCK_LESSON_JSON
        assert len(result.lesson.cards) >= 4

    async def test_generate_lesson_raises_value_error_when_concept_not_found(self):
        # knowledge_svc returns None → engine should raise ValueError immediately
        mock_ks = MagicMock()
        mock_ks.get_concept_detail.return_value = None
        mock_ks.graph.predecessors.return_value = iter([])
        mock_llm = _make_mock_llm()

        with pytest.raises(ValueError, match="Concept not found"):
            await generate_adaptive_lesson(
                student_id="abc",
                concept_id="NONEXISTENT",
                analytics_summary=ANALYTICS,
                knowledge_svc=mock_ks,
                mastery_store={},
                llm_client=mock_llm,
            )

    async def test_generate_lesson_retries_on_empty_llm_response_succeeds_on_third_attempt(self):
        # First two LLM calls return empty content; third returns valid JSON
        mock_ks = _make_mock_ks(has_prereqs=False)

        mock_response_empty = MagicMock()
        mock_response_empty.choices = [MagicMock()]
        mock_response_empty.choices[0].message.content = ""

        mock_response_valid = MagicMock()
        mock_response_valid.choices = [MagicMock()]
        mock_response_valid.choices[0].message.content = MOCK_LESSON_JSON

        mock_llm = AsyncMock()
        mock_llm.chat.completions.create = AsyncMock(
            side_effect=[mock_response_empty, mock_response_empty, mock_response_valid]
        )

        with patch("adaptive.adaptive_engine.asyncio.sleep", new_callable=AsyncMock):
            result = await generate_adaptive_lesson(
                student_id="abc",
                concept_id="PREALG.C4.S2",
                analytics_summary=ANALYTICS,
                knowledge_svc=mock_ks,
                mastery_store={"PREALG.C4.S1": True},
                llm_client=mock_llm,
            )

        assert result is not None
        assert mock_llm.chat.completions.create.call_count == 3

    async def test_generate_lesson_raises_value_error_when_all_3_retries_exhausted(self):
        # All three LLM calls return empty string → ValueError after exhausting retries
        mock_ks = _make_mock_ks(has_prereqs=False)

        mock_response_empty = MagicMock()
        mock_response_empty.choices = [MagicMock()]
        mock_response_empty.choices[0].message.content = ""

        mock_llm = AsyncMock()
        mock_llm.chat.completions.create = AsyncMock(
            side_effect=[mock_response_empty, mock_response_empty, mock_response_empty]
        )

        with patch("adaptive.adaptive_engine.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ValueError):
                await generate_adaptive_lesson(
                    student_id="abc",
                    concept_id="PREALG.C4.S2",
                    analytics_summary=ANALYTICS,
                    knowledge_svc=mock_ks,
                    mastery_store={},
                    llm_client=mock_llm,
                )

    async def test_generate_lesson_student_id_and_concept_id_are_preserved_in_response(self):
        mock_ks = _make_mock_ks(has_prereqs=False)
        mock_llm = _make_mock_llm()

        result = await generate_adaptive_lesson(
            student_id="student-xyz",
            concept_id="PREALG.C4.S2",
            analytics_summary=ANALYTICS,
            knowledge_svc=mock_ks,
            mastery_store={},
            llm_client=mock_llm,
        )

        assert result.student_id == "student-xyz"
        assert result.concept_id == "PREALG.C4.S2"

    async def test_generate_lesson_learning_profile_included_in_response(self):
        mock_ks = _make_mock_ks(has_prereqs=False)
        mock_llm = _make_mock_llm()

        result = await generate_adaptive_lesson(
            student_id="abc",
            concept_id="PREALG.C4.S2",
            analytics_summary=ANALYTICS,
            knowledge_svc=mock_ks,
            mastery_store={},
            llm_client=mock_llm,
        )

        assert isinstance(result.learning_profile, LearningProfile)

    async def test_generate_lesson_generation_profile_included_in_response(self):
        mock_ks = _make_mock_ks(has_prereqs=False)
        mock_llm = _make_mock_llm()

        result = await generate_adaptive_lesson(
            student_id="abc",
            concept_id="PREALG.C4.S2",
            analytics_summary=ANALYTICS,
            knowledge_svc=mock_ks,
            mastery_store={},
            llm_client=mock_llm,
        )

        assert isinstance(result.generation_profile, GenerationProfile)

    async def test_generate_lesson_llm_exception_triggers_retry(self):
        # When LLM raises an exception the engine should retry; success on third call
        mock_ks = _make_mock_ks(has_prereqs=False)

        mock_response_valid = MagicMock()
        mock_response_valid.choices = [MagicMock()]
        mock_response_valid.choices[0].message.content = MOCK_LESSON_JSON

        mock_llm = AsyncMock()
        mock_llm.chat.completions.create = AsyncMock(
            side_effect=[
                Exception("Connection error"),
                Exception("Timeout"),
                mock_response_valid,
            ]
        )

        with patch("adaptive.adaptive_engine.asyncio.sleep", new_callable=AsyncMock):
            result = await generate_adaptive_lesson(
                student_id="abc",
                concept_id="PREALG.C4.S2",
                analytics_summary=ANALYTICS,
                knowledge_svc=mock_ks,
                mastery_store={},
                llm_client=mock_llm,
            )

        assert result is not None
        assert mock_llm.chat.completions.create.call_count == 3


# =============================================================================
# Group 6 — Adaptive Transparency: difficulty_bias, wrong_option_pattern,
#           build_next_card_prompt misconception injection
# =============================================================================

# A minimal single-card JSON that generate_next_card's LLM mock can return.
_MOCK_NEXT_CARD_JSON = json.dumps({
    "type": "mcq",
    "title": "Quick Check",
    "content": "What is 1/2 × 1/2?",
    "answer": "1/4",
    "options": ["1/4", "1/2", "1", "2/4"],
    "hints": ["Multiply top and bottom separately."],
    "difficulty": 3,
    "fun_element": None,
    "motivational_note": None,
})

# A minimal history dict accepted by build_blended_analytics.
_MOCK_HISTORY = {
    "total_cards_completed": 10,
    "avg_time_per_card": 60.0,
    "avg_wrong_attempts": 0.5,
    "avg_hints_per_card": 0.2,
    "sessions_last_7d": 3,
    "mastered_count": 2,
    "is_known_weak_concept": False,
    "failed_concept_attempts": 0,
    "trend_direction": "STABLE",
    "trend_wrong_list": [],
}


class TestDifficultyBiasOverride:
    """
    generate_next_card must apply the student's explicit difficulty feedback
    by overriding recommended_next_step in the LearningProfile before the
    next card is generated.

    Business criteria:
      - TOO_EASY → recommended_next_step forced to CHALLENGE
      - TOO_HARD  → recommended_next_step forced to REMEDIATE_PREREQ
    """

    def _make_llm(self) -> AsyncMock:
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = _MOCK_NEXT_CARD_JSON
        llm = AsyncMock()
        llm.chat.completions.create = AsyncMock(return_value=resp)
        return llm

    async def test_difficulty_bias_too_easy_triggers_challenge(self):
        """
        When signals.difficulty_bias == 'TOO_EASY', the returned LearningProfile
        must have recommended_next_step == 'CHALLENGE' regardless of the raw
        analytics signals, so the LLM generates a harder card.
        """
        mock_ks = _make_mock_ks(has_prereqs=False)
        signals = CardBehaviorSignals(
            card_index=2,
            time_on_card_sec=50.0,
            wrong_attempts=0,
            hints_used=0,
            idle_triggers=0,
            difficulty_bias="TOO_EASY",
        )

        _card, profile, _gen, _note, _label = await generate_next_card(
            student_id="student-bias-easy",
            concept_id="PREALG.C4.S2",
            signals=signals,
            card_index=2,
            history=_MOCK_HISTORY,
            knowledge_svc=mock_ks,
            mastery_store={},
            llm_client=self._make_llm(),
            model="gpt-4o-mini",
            language="en",
            db=None,
        )

        assert profile.recommended_next_step == "CHALLENGE", (
            f"Expected CHALLENGE for TOO_EASY bias, got {profile.recommended_next_step!r}"
        )

    async def test_difficulty_bias_too_hard_triggers_remediate(self):
        """
        When signals.difficulty_bias == 'TOO_HARD', the returned LearningProfile
        must have recommended_next_step == 'REMEDIATE_PREREQ' so the next card
        revisits prerequisite material.
        """
        mock_ks = _make_mock_ks(has_prereqs=False)
        signals = CardBehaviorSignals(
            card_index=1,
            time_on_card_sec=300.0,
            wrong_attempts=3,
            hints_used=2,
            idle_triggers=0,
            difficulty_bias="TOO_HARD",
        )

        _card, profile, _gen, _note, _label = await generate_next_card(
            student_id="student-bias-hard",
            concept_id="PREALG.C4.S2",
            signals=signals,
            card_index=1,
            history=_MOCK_HISTORY,
            knowledge_svc=mock_ks,
            mastery_store={},
            llm_client=self._make_llm(),
            model="gpt-4o-mini",
            language="en",
            db=None,
        )

        assert profile.recommended_next_step == "REMEDIATE_PREREQ", (
            f"Expected REMEDIATE_PREREQ for TOO_HARD bias, got {profile.recommended_next_step!r}"
        )

    async def test_no_difficulty_bias_does_not_override_profile(self):
        """
        When difficulty_bias is None (the common case), generate_next_card must
        leave recommended_next_step as determined by the analytics.
        """
        mock_ks = _make_mock_ks(has_prereqs=False)
        signals = CardBehaviorSignals(
            card_index=0,
            time_on_card_sec=60.0,
            wrong_attempts=0,
            hints_used=0,
            idle_triggers=0,
            difficulty_bias=None,
        )

        _card, profile, _gen, _note, _label = await generate_next_card(
            student_id="student-no-bias",
            concept_id="PREALG.C4.S2",
            signals=signals,
            card_index=0,
            history=_MOCK_HISTORY,
            knowledge_svc=mock_ks,
            mastery_store={},
            llm_client=self._make_llm(),
            model="gpt-4o-mini",
            language="en",
            db=None,
        )

        valid_steps = {"CONTINUE", "REMEDIATE_PREREQ", "ADD_PRACTICE", "CHALLENGE"}
        assert profile.recommended_next_step in valid_steps


class TestLoadWrongOptionPattern:
    """
    load_wrong_option_pattern must return the option index that the student has
    repeatedly selected incorrectly (>= WRONG_OPTION_PATTERN_THRESHOLD times),
    or None when no pattern exists.
    """

    async def test_wrong_option_pattern_detected(self):
        """
        When the DB returns a row with selected_wrong_option=2 and freq >= threshold,
        load_wrong_option_pattern must return 2 (the option index).
        """
        mock_row = MagicMock()
        mock_row.selected_wrong_option = 2
        mock_row.freq = 3

        mock_result = MagicMock()
        mock_result.first.return_value = mock_row

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        import uuid
        result = await load_wrong_option_pattern(
            student_id=str(uuid.uuid4()),
            concept_id="PREALG.C4.S2",
            db=mock_db,
        )

        assert result == 2, f"Expected option index 2, got {result!r}"

    async def test_wrong_option_pattern_none_when_no_row(self):
        """
        When no option reaches the threshold, load_wrong_option_pattern must
        return None so card generation continues without a misconception block.
        """
        mock_result = MagicMock()
        mock_result.first.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        import uuid
        result = await load_wrong_option_pattern(
            student_id=str(uuid.uuid4()),
            concept_id="PREALG.C4.S2",
            db=mock_db,
        )

        assert result is None

    async def test_wrong_option_pattern_returns_none_on_db_error(self):
        """
        Any DB exception must be swallowed and None returned — transient DB errors
        must never block card generation (graceful degradation).
        """
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("DB connection lost"))

        import uuid
        result = await load_wrong_option_pattern(
            student_id=str(uuid.uuid4()),
            concept_id="PREALG.C4.S2",
            db=mock_db,
        )

        assert result is None


class TestBuildNextCardPromptInjections:
    """
    build_next_card_prompt must append MISCONCEPTION PATTERN and/or DIFFICULTY
    ADJUSTMENT blocks to the user prompt when the corresponding signals are present.
    """

    def _base_args(self, recommended_next_step: str = "CONTINUE") -> dict:
        profile = _make_learning_profile(recommended_next_step=recommended_next_step)
        gen_profile = build_generation_profile(profile)
        return {
            "concept_detail": MOCK_CONCEPT,
            "learning_profile": profile,
            "gen_profile": gen_profile,
            "card_index": 2,
            "history": _MOCK_HISTORY,
            "language": "en",
        }

    def test_next_card_prompt_includes_misconception_when_wrong_option_pattern_set(self):
        """
        When wrong_option_pattern=2, the user prompt must contain a MISCONCEPTION
        PATTERN block referencing option index 2.
        """
        _sys, user = build_next_card_prompt(
            **self._base_args(),
            wrong_option_pattern=2,
            difficulty_bias=None,
        )

        assert "MISCONCEPTION PATTERN" in user
        assert "2" in user

    def test_next_card_prompt_no_misconception_when_wrong_option_pattern_is_none(self):
        """
        When wrong_option_pattern is None, the MISCONCEPTION PATTERN block must
        be absent from the user prompt.
        """
        _sys, user = build_next_card_prompt(
            **self._base_args(),
            wrong_option_pattern=None,
            difficulty_bias=None,
        )

        assert "MISCONCEPTION PATTERN" not in user

    def test_next_card_prompt_includes_difficulty_adjustment_for_too_easy(self):
        """
        When difficulty_bias='TOO_EASY', the user prompt must contain a
        DIFFICULTY ADJUSTMENT block instructing the LLM to raise challenge.
        """
        _sys, user = build_next_card_prompt(
            **self._base_args(),
            wrong_option_pattern=None,
            difficulty_bias="TOO_EASY",
        )

        assert "DIFFICULTY ADJUSTMENT" in user
        assert "too easy" in user.lower() or "increase" in user.lower() or "higher difficulty" in user.lower()

    def test_next_card_prompt_includes_difficulty_adjustment_for_too_hard(self):
        """
        When difficulty_bias='TOO_HARD', the user prompt must contain a
        DIFFICULTY ADJUSTMENT block instructing the LLM to simplify.
        """
        _sys, user = build_next_card_prompt(
            **self._base_args(),
            wrong_option_pattern=None,
            difficulty_bias="TOO_HARD",
        )

        assert "DIFFICULTY ADJUSTMENT" in user
        assert "too hard" in user.lower() or "simplif" in user.lower() or "lower difficulty" in user.lower()

    def test_next_card_prompt_no_difficulty_adjustment_when_bias_is_none(self):
        """
        When difficulty_bias is None, the DIFFICULTY ADJUSTMENT block must be absent.
        """
        _sys, user = build_next_card_prompt(
            **self._base_args(),
            wrong_option_pattern=None,
            difficulty_bias=None,
        )

        assert "DIFFICULTY ADJUSTMENT" not in user

    def test_next_card_prompt_both_injections_present_simultaneously(self):
        """
        Both MISCONCEPTION PATTERN and DIFFICULTY ADJUSTMENT blocks must appear
        when both wrong_option_pattern and difficulty_bias are set.
        """
        _sys, user = build_next_card_prompt(
            **self._base_args(),
            wrong_option_pattern=0,
            difficulty_bias="TOO_EASY",
        )

        assert "MISCONCEPTION PATTERN" in user
        assert "DIFFICULTY ADJUSTMENT" in user
