"""
Tests for the Full Adaptive Learning Upgrade.

Covers:
  Group 1 — build_cards_system_prompt(): adaptive profile block injection
  Group 2 — build_cards_user_prompt(): wrong_option_pattern / misconception alert
  Group 3 — build_socratic_system_prompt(): session_card_stats / dynamic min_questions
  Group 4 — prompt_builder.py: FAST/STRONG no longer skips content
  Group 5 — XP award logic: constants and computation

All tests are pure unit tests — zero I/O, no database, no LLM calls.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from api.prompts import (
    build_cards_system_prompt,
    build_cards_user_prompt,
    build_socratic_system_prompt,
    _build_card_profile_block,
    _build_session_stats_block,
)
from config import (
    XP_MASTERY,
    XP_MASTERY_BONUS,
    XP_MASTERY_BONUS_THRESHOLD,
    XP_CONSOLATION,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _profile(speed="NORMAL", comprehension="STANDARD", engagement="NORMAL",
             confidence_score=0.6):
    """Create a minimal LearningProfile-like object with required fields."""
    return SimpleNamespace(
        speed=speed,
        comprehension=comprehension,
        engagement=engagement,
        confidence_score=confidence_score,
    )


def _history(
    trend_direction="STABLE",
    mastered_count=5,
    total_cards_completed=20,
    is_known_weak_concept=False,
    failed_concept_attempts=0,
    sessions_last_7d=3,
):
    return {
        "trend_direction": trend_direction,
        "mastered_count": mastered_count,
        "total_cards_completed": total_cards_completed,
        "is_known_weak_concept": is_known_weak_concept,
        "failed_concept_attempts": failed_concept_attempts,
        "sessions_last_7d": sessions_last_7d,
    }


# ── Group 1: build_cards_system_prompt() — profile block ─────────────────────

class TestCardsSystemPromptProfileBlock:

    def test_no_profile_no_block(self):
        result = build_cards_system_prompt(learning_profile=None, history=None)
        assert "STUDENT PROFILE" not in result

    def test_profile_injects_summary_header(self):
        result = build_cards_system_prompt(
            learning_profile=_profile(),
            history=_history(),
        )
        assert "STUDENT PROFILE SUMMARY" in result

    def test_struggling_comprehension_injects_support_mode(self):
        result = build_cards_system_prompt(
            learning_profile=_profile(comprehension="STRUGGLING"),
            history=_history(),
        )
        assert "SUPPORT" in result

    def test_slow_speed_injects_support_mode(self):
        result = build_cards_system_prompt(
            learning_profile=_profile(speed="SLOW"),
            history=_history(),
        )
        assert "SUPPORT" in result

    def test_fast_strong_injects_accelerate_mode(self):
        result = build_cards_system_prompt(
            learning_profile=_profile(speed="FAST", comprehension="STRONG"),
            history=_history(),
        )
        assert "ACCELERATE" in result

    def test_fast_strong_does_not_skip_substance(self):
        """FAST/STRONG mode must not tell LLM to skip content."""
        result = build_cards_system_prompt(
            learning_profile=_profile(speed="FAST", comprehension="STRONG"),
            history=_history(),
        )
        assert "Skip introductory analogies" not in result
        # Instead it must require all content to appear
        assert "never skip substance" in result

    def test_bored_engagement_injects_engagement_boost(self):
        result = build_cards_system_prompt(
            learning_profile=_profile(engagement="BORED"),
            history=_history(),
        )
        assert "ENGAGEMENT BOOST" in result

    def test_worsening_trend_injects_confidence_building(self):
        result = build_cards_system_prompt(
            learning_profile=_profile(),
            history=_history(trend_direction="WORSENING"),
        )
        assert "CONFIDENCE BUILDING" in result

    def test_improving_trend_no_confidence_building(self):
        result = build_cards_system_prompt(
            learning_profile=_profile(),
            history=_history(trend_direction="IMPROVING"),
        )
        assert "CONFIDENCE BUILDING" not in result

    def test_weak_concept_injects_weak_concept_block(self):
        result = build_cards_system_prompt(
            learning_profile=_profile(),
            history=_history(is_known_weak_concept=True, failed_concept_attempts=3),
        )
        assert "WEAK CONCEPT" in result
        assert "3" in result

    def test_profile_shows_speed_comprehension_engagement(self):
        result = build_cards_system_prompt(
            learning_profile=_profile(speed="FAST", comprehension="STRONG",
                                      engagement="ENTHUSIASTIC"),
            history=_history(),
        )
        assert "FAST" in result
        assert "STRONG" in result
        assert "ENTHUSIASTIC" in result

    def test_textbook_accuracy_rule_present(self):
        """Base prompt must include the textbook accuracy non-negotiable rule."""
        result = build_cards_system_prompt()
        assert "TEXTBOOK ACCURACY" in result or "textbook" in result.lower()


# ── Group 2: build_cards_user_prompt() — misconception alert ─────────────────

class TestCardsUserPromptMisconceptionAlert:

    _SECTIONS = [{"title": "Intro", "text": "Decimals are fractions of 10."}]

    def test_no_wrong_pattern_no_alert(self):
        result = build_cards_user_prompt(
            "Decimals", self._SECTIONS, wrong_option_pattern=None
        )
        assert "MISCONCEPTION" not in result

    def test_wrong_pattern_injects_alert(self):
        result = build_cards_user_prompt(
            "Decimals", self._SECTIONS, wrong_option_pattern=2
        )
        assert "MISCONCEPTION ALERT" in result

    def test_wrong_pattern_includes_index_number(self):
        result = build_cards_user_prompt(
            "Decimals", self._SECTIONS, wrong_option_pattern=1
        )
        assert "1" in result

    def test_wrong_pattern_zero_still_injects(self):
        """Option index 0 is valid — must not be treated as falsy."""
        result = build_cards_user_prompt(
            "Decimals", self._SECTIONS, wrong_option_pattern=0
        )
        assert "MISCONCEPTION ALERT" in result


# ── Group 3: build_socratic_system_prompt() — session_card_stats ─────────────

class TestSocraticSessionStats:

    _CONCEPT = "Decimals"
    _TEXT = "A decimal is a number with a decimal point."

    def _stats(self, total_cards, total_wrong, total_hints=0):
        error_rate = total_wrong / total_cards if total_cards else 0
        return {
            "total_cards": total_cards,
            "total_wrong": total_wrong,
            "total_hints": total_hints,
            "error_rate": error_rate,
        }

    def test_no_stats_uses_3_min_questions(self):
        result = build_socratic_system_prompt(
            self._CONCEPT, self._TEXT, session_card_stats=None
        )
        # Default is 3
        assert "3 question" in result or "at least 3" in result

    def test_high_error_rate_uses_5_min_questions(self):
        """error_rate = 3/5 = 0.60 >= 0.40 → min_questions = 5"""
        result = build_socratic_system_prompt(
            self._CONCEPT, self._TEXT,
            session_card_stats=self._stats(5, 3),
        )
        assert "5 question" in result or "at least 5" in result

    def test_zero_error_rate_uses_3_min_questions(self):
        """Perfect score → min_questions = 3"""
        result = build_socratic_system_prompt(
            self._CONCEPT, self._TEXT,
            session_card_stats=self._stats(4, 0, 0),
        )
        assert "5 question" not in result
        assert "3 question" in result or "at least 3" in result

    def test_moderate_error_rate_uses_4_min_questions(self):
        """error_rate = 1/4 = 0.25 → moderate → min_questions = 4"""
        result = build_socratic_system_prompt(
            self._CONCEPT, self._TEXT,
            session_card_stats=self._stats(4, 1),
        )
        assert "4 question" in result or "at least 4" in result

    def test_struggling_profile_uses_5_min_questions_without_stats(self):
        """STRUGGLING profile with no stats → min_questions = 5"""
        result = build_socratic_system_prompt(
            self._CONCEPT, self._TEXT,
            session_card_stats=None,
            socratic_profile=_profile(comprehension="STRUGGLING"),
        )
        assert "5 question" in result or "at least 5" in result

    def test_session_stats_block_included_in_prompt(self):
        result = build_socratic_system_prompt(
            self._CONCEPT, self._TEXT,
            session_card_stats=self._stats(4, 2, 1),
        )
        assert "WHAT YOU KNOW ABOUT THIS STUDENT" in result

    def test_worsening_trend_mentioned_in_socratic_prompt(self):
        result = build_socratic_system_prompt(
            self._CONCEPT, self._TEXT,
            session_card_stats=self._stats(3, 0),
            history=_history(trend_direction="WORSENING"),
        )
        assert "WORSENING" in result or "declining" in result.lower()

    def test_improving_trend_mentioned_in_socratic_prompt(self):
        result = build_socratic_system_prompt(
            self._CONCEPT, self._TEXT,
            session_card_stats=self._stats(3, 0),
            history=_history(trend_direction="IMPROVING"),
        )
        assert "IMPROVING" in result or "improving" in result.lower()


# ── Group 4: _build_card_profile_block() unit tests ──────────────────────────

class TestBuildCardProfileBlock:

    def test_none_profile_returns_empty_string(self):
        assert _build_card_profile_block(None, None) == ""

    def test_none_profile_with_history_returns_empty_string(self):
        assert _build_card_profile_block(None, _history()) == ""

    def test_has_separator_markers(self):
        result = _build_card_profile_block(_profile(), _history())
        assert "---" in result

    def test_struggling_has_support_label(self):
        result = _build_card_profile_block(
            _profile(comprehension="STRUGGLING"), _history()
        )
        assert "SUPPORT" in result

    def test_fast_strong_has_accelerate_label(self):
        result = _build_card_profile_block(
            _profile(speed="FAST", comprehension="STRONG"), _history()
        )
        assert "ACCELERATE" in result

    def test_fast_strong_content_preservation_wording(self):
        result = _build_card_profile_block(
            _profile(speed="FAST", comprehension="STRONG"), _history()
        )
        assert "never skip substance" in result

    def test_bored_has_engagement_boost_label(self):
        result = _build_card_profile_block(
            _profile(engagement="BORED"), _history()
        )
        assert "ENGAGEMENT BOOST" in result

    def test_weak_concept_shows_failed_count(self):
        result = _build_card_profile_block(
            _profile(), _history(is_known_weak_concept=True, failed_concept_attempts=2)
        )
        assert "WEAK CONCEPT" in result
        assert "2" in result


# ── Group 5: XP award logic constants ────────────────────────────────────────

class TestXPConstants:

    def test_xp_mastery_base_value(self):
        assert XP_MASTERY == 50

    def test_xp_mastery_bonus_value(self):
        assert XP_MASTERY_BONUS == 25

    def test_xp_mastery_bonus_threshold(self):
        assert XP_MASTERY_BONUS_THRESHOLD == 90

    def test_xp_consolation_value(self):
        assert XP_CONSOLATION == 10

    def test_xp_computation_mastery_below_threshold(self):
        """Score 80 mastery → base only = 50"""
        score = 80
        mastered = True
        xp = XP_MASTERY + (XP_MASTERY_BONUS if score >= XP_MASTERY_BONUS_THRESHOLD else 0)
        assert xp == 50

    def test_xp_computation_mastery_at_threshold(self):
        """Score exactly 90 → qualifies for bonus = 75"""
        score = 90
        mastered = True
        xp = XP_MASTERY + (XP_MASTERY_BONUS if score >= XP_MASTERY_BONUS_THRESHOLD else 0)
        assert xp == 75

    def test_xp_computation_mastery_above_threshold(self):
        """Score 95 mastery → base + bonus = 75"""
        score = 95
        mastered = True
        xp = XP_MASTERY + (XP_MASTERY_BONUS if score >= XP_MASTERY_BONUS_THRESHOLD else 0)
        assert xp == 75

    def test_xp_computation_no_mastery(self):
        """No mastery → consolation = 10"""
        mastered = False
        xp = XP_CONSOLATION
        assert xp == 10

    def test_xp_consolation_less_than_mastery(self):
        assert XP_CONSOLATION < XP_MASTERY
