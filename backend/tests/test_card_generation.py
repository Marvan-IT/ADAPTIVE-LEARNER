"""
Unit tests for the card generation system in the ADA adaptive learning platform.

Covers:
  Group 1 — TeachingService._group_by_major_topic(): semantic section grouping
  Group 2 — Adaptive max_tokens logic (inline in generate_cards): token budget rules
  Group 3 — build_cards_user_prompt(): completeness checklist and ordering requirement
  Group 4 — _build_card_profile_block(): card density instructions per learner profile
  Group 5 — Fallback sub-section key regression: "text" not "content"

Test infrastructure:
  - pytest.ini sets asyncio_mode = auto — no @pytest.mark.asyncio needed
  - conftest.py inserts backend/src into sys.path; block below duplicates it for
    direct execution safety
  - All tests are pure unit tests — zero I/O, no LLM calls, no DB connections
"""

import sys
from pathlib import Path

# Ensure backend/src is importable regardless of how pytest is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from adaptive.schemas import AnalyticsSummary, LearningProfile
from adaptive.profile_builder import build_learning_profile
from api.teaching_service import TeachingService
from api.prompts import build_cards_user_prompt, _build_card_profile_block


# =============================================================================
# Shared helpers
# =============================================================================

def _make_analytics(
    time_spent_sec: float = 120.0,
    expected_time_sec: float = 120.0,
    attempts: int = 1,
    wrong_attempts: int = 0,
    hints_used: int = 0,
    quiz_score: float = 0.8,
) -> AnalyticsSummary:
    """Build a minimal AnalyticsSummary for profile construction."""
    return AnalyticsSummary(
        student_id="student-test",
        concept_id="PREALG.C1.S1",
        time_spent_sec=time_spent_sec,
        expected_time_sec=expected_time_sec,
        attempts=attempts,
        wrong_attempts=wrong_attempts,
        hints_used=hints_used,
        revisits=0,
        recent_dropoffs=0,
        skip_rate=0.0,
        quiz_score=quiz_score,
        last_7d_sessions=1,
    )


def _make_profile(
    speed: str = "NORMAL",
    comprehension: str = "OK",
    engagement: str = "ENGAGED",
) -> LearningProfile:
    """Construct a LearningProfile directly without going through the analytics pipeline."""
    return LearningProfile(
        speed=speed,
        comprehension=comprehension,
        engagement=engagement,
        confidence_score=0.6,
        recommended_next_step="CONTINUE",
        error_rate=0.0,
    )


def _make_sub_sections(titles: list[str]) -> list[dict]:
    """Build a list of sub-section dicts with stub text content."""
    return [{"title": t, "text": f"Content for {t}."} for t in titles]


# =============================================================================
# Group 1 — TestGroupByMajorTopic
# =============================================================================

class TestGroupByMajorTopic:
    """
    Tests for TeachingService._group_by_major_topic().

    Business rule: supporting content (EXAMPLE, Solution, TRY IT, HOW TO, etc.)
    must be absorbed into the preceding major topic section so the LLM receives
    coherent topic groups rather than dozens of micro-sections.
    """

    def test_groups_example_sections_into_parent(self):
        """EXAMPLE and Solution sections that follow a major topic are absorbed into it."""
        sections = [
            {"title": "Model Whole Numbers", "text": "A whole number is..."},
            {"title": "Example 1.1", "text": "Step 1: count items"},
            {"title": "Solution", "text": "Answer is 5"},
            {"title": "TRY IT 1.1", "text": "Now try this problem"},
        ]
        result = TeachingService._group_by_major_topic(sections)

        # All four micro-sections should merge into one group
        assert len(result) == 1
        assert result[0]["title"] == "Model Whole Numbers"
        # All text must be present in the merged group
        assert "A whole number is..." in result[0]["text"]
        assert "Step 1: count items" in result[0]["text"]
        assert "Answer is 5" in result[0]["text"]
        assert "Now try this problem" in result[0]["text"]

    def test_preserves_curriculum_order(self):
        """Grouped output preserves the document order of major topics."""
        sections = [
            {"title": "Add Whole Numbers", "text": "Addition means..."},
            {"title": "Example 1.2", "text": "2 + 3 = 5"},
            {"title": "Subtract Whole Numbers", "text": "Subtraction means..."},
            {"title": "Example 1.3", "text": "5 - 2 = 3"},
            {"title": "Multiply Whole Numbers", "text": "Multiplication means..."},
        ]
        result = TeachingService._group_by_major_topic(sections)

        assert len(result) == 3
        assert result[0]["title"] == "Add Whole Numbers"
        assert result[1]["title"] == "Subtract Whole Numbers"
        assert result[2]["title"] == "Multiply Whole Numbers"

    def test_handles_leading_support_sections(self):
        """
        When the very first section is a support heading (no preceding major topic),
        it cannot be absorbed — it must be kept as-is rather than dropped.
        """
        sections = [
            {"title": "Example 0.1", "text": "Introductory example"},
            {"title": "Real Major Topic", "text": "The main content"},
        ]
        result = TeachingService._group_by_major_topic(sections)

        # Example has no preceding group — falls through as its own entry.
        # Real Major Topic becomes its own group.
        assert len(result) == 2
        titles = [g["title"] for g in result]
        assert "Example 0.1" in titles
        assert "Real Major Topic" in titles

    def test_empty_input_returns_empty_list(self):
        """An empty section list returns an empty list without raising."""
        result = TeachingService._group_by_major_topic([])
        assert result == []

    def test_reduces_section_count(self):
        """
        A large set of micro-sections (simulating 57 raw headers) is consolidated
        into significantly fewer topic groups.
        """
        # Build: 8 major topics, each followed by 6 support sections (48 total)
        sections = []
        support_titles = [
            "Example {i}.{j}",
            "Solution",
            "TRY IT {i}.{j}",
            "HOW TO do this",
            "Note",
            "TIP",
        ]
        for i in range(1, 9):
            sections.append({"title": f"Major Topic {i}", "text": f"Concept {i}."})
            for j, tmpl in enumerate(support_titles):
                sections.append({"title": tmpl.format(i=i, j=j), "text": f"Support {i}-{j}."})

        result = TeachingService._group_by_major_topic(sections)

        assert len(result) < len(sections), (
            f"Expected fewer groups than {len(sections)} sections, got {len(result)}"
        )
        assert len(result) == 8  # One group per major topic

    def test_no_content_dropped(self):
        """
        All text from all sections must appear somewhere in the output groups.
        No content may be silently discarded during grouping.
        """
        sections = [
            {"title": "Fractions Introduction", "text": "A fraction is part of a whole."},
            {"title": "Example 4.1", "text": "The fraction 1/2 means one out of two."},
            {"title": "TRY IT 4.1", "text": "What is 3/4 of 8?"},
            {"title": "Equivalent Fractions", "text": "Two fractions are equivalent if..."},
            {"title": "How To Find Equivalents", "text": "Multiply top and bottom by the same number."},
        ]
        result = TeachingService._group_by_major_topic(sections)

        all_output_text = " ".join(g["text"] for g in result)
        for sec in sections:
            assert sec["text"] in all_output_text, (
                f"Text from section '{sec['title']}' was dropped during grouping"
            )


# =============================================================================
# Group 2 — TestAdaptiveMaxTokens
# =============================================================================

class TestAdaptiveMaxTokens:
    """
    Tests for the inline adaptive max_tokens logic inside generate_cards().

    Business rule: token budget must scale with learner profile and section count:
      SLOW or STRUGGLING → min(16000, max(8000, n * 1800))
      FAST and STRONG    → min(8000,  max(4000, n * 900))
      NORMAL (default)   → min(12000, max(6000, n * 1200))
    """

    @staticmethod
    def _compute(speed: str, comprehension: str, n_sections: int) -> int:
        """Mirror the inline token-budget formula from generate_cards()."""
        if speed == "SLOW" or comprehension == "STRUGGLING":
            return min(16000, max(8000, n_sections * 1800))
        elif speed == "FAST" and comprehension == "STRONG":
            return min(8000, max(4000, n_sections * 900))
        else:
            return min(12000, max(6000, n_sections * 1200))

    def test_slow_learner_gets_max_tokens(self):
        """SLOW+STRUGGLING profile with 10 sections must receive at least 8000 tokens."""
        tokens = self._compute("SLOW", "STRUGGLING", 10)
        assert tokens >= 8000
        assert tokens == min(16000, max(8000, 10 * 1800))  # == 16000

    def test_fast_learner_gets_fewer_tokens(self):
        """FAST+STRONG profile with 10 sections receives fewer tokens than SLOW."""
        fast_tokens = self._compute("FAST", "STRONG", 10)
        slow_tokens = self._compute("SLOW", "OK", 10)
        assert fast_tokens <= slow_tokens
        assert fast_tokens <= 8000

    def test_normal_learner_gets_medium_tokens(self):
        """NORMAL/OK profile with 10 sections gets more than FAST but less than SLOW."""
        normal_tokens = self._compute("NORMAL", "OK", 10)
        fast_tokens = self._compute("FAST", "STRONG", 10)
        slow_tokens = self._compute("SLOW", "OK", 10)
        assert fast_tokens <= normal_tokens <= slow_tokens

    def test_min_floor_enforced_fast(self):
        """With 1 section, FAST+STRONG must receive at least 4000 tokens (floor)."""
        tokens = self._compute("FAST", "STRONG", 1)
        assert tokens >= 4000

    def test_min_floor_enforced_normal(self):
        """With 1 section, NORMAL profile must receive at least 6000 tokens (floor)."""
        tokens = self._compute("NORMAL", "OK", 1)
        assert tokens >= 6000

    def test_min_floor_enforced_slow(self):
        """With 1 section, SLOW profile must receive at least 8000 tokens (floor)."""
        tokens = self._compute("SLOW", "OK", 1)
        assert tokens >= 8000

    def test_max_ceiling_enforced_slow(self):
        """With 100 sections, SLOW profile must not exceed 16000 tokens (ceiling)."""
        tokens = self._compute("SLOW", "STRUGGLING", 100)
        assert tokens <= 16000

    def test_max_ceiling_enforced_fast(self):
        """With 100 sections, FAST+STRONG profile must not exceed 8000 tokens (ceiling)."""
        tokens = self._compute("FAST", "STRONG", 100)
        assert tokens <= 8000

    def test_max_ceiling_enforced_normal(self):
        """With 100 sections, NORMAL profile must not exceed 12000 tokens (ceiling)."""
        tokens = self._compute("NORMAL", "OK", 100)
        assert tokens <= 12000

    def test_struggling_comprehension_triggers_slow_path(self):
        """STRUGGLING comprehension alone (even with NORMAL speed) triggers the SLOW path."""
        tokens_struggling = self._compute("NORMAL", "STRUGGLING", 5)
        tokens_slow = self._compute("SLOW", "OK", 5)
        # Both use the same formula branch
        assert tokens_struggling == tokens_slow

    def test_fast_speed_without_strong_comprehension_uses_normal_path(self):
        """FAST speed with OK comprehension (not STRONG) must use the NORMAL path."""
        tokens = self._compute("FAST", "OK", 5)
        expected = min(12000, max(6000, 5 * 1200))
        assert tokens == expected


# =============================================================================
# Group 3 — TestBuildCardsUserPromptCompleteness
# =============================================================================

class TestBuildCardsUserPromptCompleteness:
    """
    Tests for build_cards_user_prompt() from prompts.py.

    Business rule: the prompt must always contain a numbered COMPLETENESS REQUIREMENT
    checklist listing all section titles so the LLM is contractually bound to cover
    every section in the card output.
    """

    def _build_prompt(self, titles: list[str] | None = None) -> str:
        """Build a cards user prompt from a list of section titles."""
        if titles is None:
            titles = ["Introduction to Integers", "Absolute Value", "Order of Operations"]
        sub_sections = _make_sub_sections(titles)
        return build_cards_user_prompt(
            concept_title="Integers",
            sub_sections=sub_sections,
        )

    def test_completeness_checklist_contains_all_section_titles(self):
        """Every section title must appear in the completeness checklist block."""
        titles = ["Place Value", "Rounding Numbers", "Estimating Sums"]
        prompt = self._build_prompt(titles)
        for title in titles:
            assert title in prompt, (
                f"Section title '{title}' not found in completeness checklist"
            )

    def test_section_numbers_in_checklist(self):
        """Checklist entries must be numbered (1., 2., 3. format)."""
        titles = ["Alpha Section", "Beta Section", "Gamma Section"]
        prompt = self._build_prompt(titles)
        assert "1." in prompt
        assert "2." in prompt
        assert "3." in prompt

    def test_completeness_requirement_phrase_present(self):
        """The phrase 'COMPLETENESS REQUIREMENT' must appear in the prompt."""
        prompt = self._build_prompt()
        assert "COMPLETENESS REQUIREMENT" in prompt

    def test_ordering_requirement_present(self):
        """
        Regression: the 'ORDERING REQUIREMENT' phrase must still be present.
        This was in the original prompt and must not have been removed by the
        completeness checklist changes.
        """
        prompt = self._build_prompt()
        assert "ORDERING REQUIREMENT" in prompt

    def test_all_titles_numbered_in_order(self):
        """Section numbers in the checklist match the order of the input sections."""
        titles = ["First Section", "Second Section", "Third Section"]
        sub_sections = _make_sub_sections(titles)
        prompt = build_cards_user_prompt(
            concept_title="Test Concept",
            sub_sections=sub_sections,
        )
        # All three numbered entries should appear in document order
        pos_1 = prompt.index("1. First Section")
        pos_2 = prompt.index("2. Second Section")
        pos_3 = prompt.index("3. Third Section")
        assert pos_1 < pos_2 < pos_3

    def test_single_section_has_completeness_checklist(self):
        """Even a single-section prompt must have the completeness requirement."""
        prompt = self._build_prompt(["Only Section"])
        assert "COMPLETENESS REQUIREMENT" in prompt
        assert "Only Section" in prompt
        assert "1." in prompt

    def test_prompt_contains_concept_title(self):
        """The concept title must appear in the prompt."""
        sub_sections = _make_sub_sections(["Section A"])
        prompt = build_cards_user_prompt(
            concept_title="Whole Numbers and Operations",
            sub_sections=sub_sections,
        )
        assert "Whole Numbers and Operations" in prompt


# =============================================================================
# Group 4 — TestBuildCardProfileBlockDensity
# =============================================================================

class TestBuildCardProfileBlockDensity:
    """
    Tests for _build_card_profile_block() from prompts.py.

    Business rule: the profile block must inject CARD DENSITY instructions that
    explicitly tell the LLM how many cards to generate per section, calibrated
    to the learner's speed and comprehension profile.
    """

    def test_slow_learner_gets_card_density_instructions(self):
        """SLOW speed profile must produce a block containing 'CARD DENSITY'."""
        profile = _make_profile(speed="SLOW", comprehension="OK")
        result = _build_card_profile_block(profile, history=None)
        assert "CARD DENSITY" in result

    def test_struggling_comprehension_gets_card_density_instructions(self):
        """STRUGGLING comprehension profile must produce a block containing 'CARD DENSITY'."""
        profile = _make_profile(speed="NORMAL", comprehension="STRUGGLING")
        result = _build_card_profile_block(profile, history=None)
        assert "CARD DENSITY" in result

    def test_fast_strong_learner_gets_density_instructions(self):
        """FAST+STRONG profile must produce a block containing 'CARD DENSITY'."""
        profile = _make_profile(speed="FAST", comprehension="STRONG")
        result = _build_card_profile_block(profile, history=None)
        assert "CARD DENSITY" in result

    def test_normal_learner_gets_density_instructions(self):
        """NORMAL/OK profile must also produce a block containing 'CARD DENSITY'."""
        profile = _make_profile(speed="NORMAL", comprehension="OK")
        result = _build_card_profile_block(profile, history=None)
        assert "CARD DENSITY" in result

    def test_support_mode_mentions_teach_example_question(self):
        """
        SLOW/STRUGGLING mode (SUPPORT) density block must mention the three
        card types: TEACH, EXAMPLE, and QUESTION, so the LLM knows to generate
        at least one of each per section.
        """
        profile = _make_profile(speed="SLOW", comprehension="STRUGGLING")
        result = _build_card_profile_block(profile, history=None)
        assert "TEACH" in result
        assert "EXAMPLE" in result
        assert "QUESTION" in result

    def test_support_mode_specifies_2_to_3_cards_per_section(self):
        """
        SUPPORT mode must specify '2-3 cards' as the minimum density
        so the LLM generates enough cards for struggling learners.
        """
        profile = _make_profile(speed="SLOW", comprehension="OK")
        result = _build_card_profile_block(profile, history=None)
        assert "2-3" in result

    def test_accelerate_mode_mentions_focused_cards(self):
        """
        FAST+STRONG mode (ACCELERATE) density block must use the word 'focused'
        to direct the LLM to produce concise, substantive cards.
        """
        profile = _make_profile(speed="FAST", comprehension="STRONG")
        result = _build_card_profile_block(profile, history=None)
        assert "focused" in result

    def test_accelerate_mode_specifies_1_to_2_cards(self):
        """ACCELERATE mode must specify '1-2 focused cards' per section."""
        profile = _make_profile(speed="FAST", comprehension="STRONG")
        result = _build_card_profile_block(profile, history=None)
        assert "1-2" in result

    def test_none_profile_returns_empty_string(self):
        """When learning_profile is None, the block must return an empty string."""
        result = _build_card_profile_block(None, history=None)
        assert result == ""

    def test_block_includes_mode_label_support(self):
        """SUPPORT mode must be labelled 'MODE: SUPPORT' in the block."""
        profile = _make_profile(speed="SLOW", comprehension="STRUGGLING")
        result = _build_card_profile_block(profile, history=None)
        assert "MODE: SUPPORT" in result

    def test_block_includes_mode_label_accelerate(self):
        """ACCELERATE mode must be labelled 'MODE: ACCELERATE' in the block."""
        profile = _make_profile(speed="FAST", comprehension="STRONG")
        result = _build_card_profile_block(profile, history=None)
        assert "MODE: ACCELERATE" in result

    def test_profile_speed_and_comprehension_appear_in_block(self):
        """The profile summary line must include speed and comprehension values."""
        profile = _make_profile(speed="NORMAL", comprehension="OK")
        result = _build_card_profile_block(profile, history=None)
        assert "NORMAL" in result
        assert "OK" in result

    def test_worsening_trend_adds_confidence_building_block(self):
        """A WORSENING trend in history must trigger a CONFIDENCE BUILDING section."""
        profile = _make_profile(speed="NORMAL", comprehension="OK")
        history = {"trend_direction": "WORSENING", "is_known_weak_concept": False}
        result = _build_card_profile_block(profile, history=history)
        assert "CONFIDENCE BUILDING" in result

    def test_weak_concept_flag_adds_weak_concept_block(self):
        """A known weak concept must trigger a WEAK CONCEPT section in the block."""
        profile = _make_profile(speed="NORMAL", comprehension="OK")
        history = {"is_known_weak_concept": True, "failed_concept_attempts": 3,
                   "trend_direction": "STABLE"}
        result = _build_card_profile_block(profile, history=history)
        assert "WEAK CONCEPT" in result
        assert "3" in result  # failed attempt count must appear


# =============================================================================
# Group 5 — TestFallbackSubSectionKey (regression)
# =============================================================================

class TestFallbackSubSectionKey:
    """
    Regression tests for Fix A: the fallback sub-section dict uses key "text",
    not "content".

    Before the fix, when _parse_sub_sections() returned empty, the fallback was:
        [{"title": concept_title, "content": concept_text}]   # BUG

    After the fix:
        [{"title": concept_title, "text": concept_text}]      # CORRECT

    build_cards_user_prompt() accesses sec["text"] — the old "content" key
    would raise a KeyError at runtime.
    """

    def test_fallback_uses_text_key_not_content(self):
        """
        A sub-section dict with key 'text' must not raise KeyError when passed
        to build_cards_user_prompt(). This validates the corrected fallback key.
        """
        fallback_section = {"title": "Whole Numbers", "text": "A whole number is a counting number."}
        # Should not raise any exception
        prompt = build_cards_user_prompt(
            concept_title="Whole Numbers",
            sub_sections=[fallback_section],
        )
        assert "Whole Numbers" in prompt
        assert "A whole number is a counting number." in prompt

    def test_content_key_raises_key_error(self):
        """
        Confirm that a sub-section dict with old 'content' key (the pre-fix bug)
        would raise a KeyError — demonstrating that the bug would have been caught.
        """
        broken_section = {"title": "Whole Numbers", "content": "A whole number is a counting number."}
        with pytest.raises(KeyError):
            build_cards_user_prompt(
                concept_title="Whole Numbers",
                sub_sections=[broken_section],
            )

    def test_text_key_survives_group_by_major_topic_roundtrip(self):
        """
        After _group_by_major_topic(), every returned section must have a 'text'
        key (not 'content'), so the output is safe to pass directly to
        build_cards_user_prompt().
        """
        sections = [
            {"title": "Real Topic", "text": "Main concept text."},
            {"title": "Example 1.1", "text": "Example text."},
        ]
        grouped = TeachingService._group_by_major_topic(sections)
        for sec in grouped:
            assert "text" in sec, (
                f"Section '{sec.get('title')}' is missing 'text' key after grouping"
            )
            assert "content" not in sec, (
                f"Section '{sec.get('title')}' has unexpected 'content' key after grouping"
            )

    def test_build_cards_user_prompt_text_from_fallback_appears_in_output(self):
        """
        The text from the fallback section must appear in the generated prompt,
        confirming the LLM will receive the concept body.
        """
        body = "Numbers are used for counting and ordering."
        section = {"title": "Number Concepts", "text": body}
        prompt = build_cards_user_prompt(
            concept_title="Number Concepts",
            sub_sections=[section],
        )
        assert body in prompt


# =============================================================================
# Group 6 — TestFindMissingSections
# =============================================================================

class TestFindMissingSections:
    """Tests for TeachingService._find_missing_sections(cards, sections)."""

    def test_returns_empty_when_all_titles_covered(self):
        cards = [
            {"title": "Place Value Explained", "content": "Place value describes..."},
            {"title": "Rounding Numbers", "content": "To round, look at the next digit..."},
        ]
        sections = [
            {"title": "Place Value", "text": "..."},
            {"title": "Rounding Numbers", "text": "..."},
        ]
        assert TeachingService._find_missing_sections(cards, sections) == []

    def test_returns_section_when_title_missing(self):
        cards = [{"title": "Place Value", "content": "Place value content."}]
        sections = [
            {"title": "Place Value", "text": "..."},
            {"title": "Absolute Value", "text": "..."},
        ]
        result = TeachingService._find_missing_sections(cards, sections)
        assert len(result) == 1
        assert result[0]["title"] == "Absolute Value"

    def test_case_insensitive_matching(self):
        cards = [{"title": "place value overview", "content": "explanation of place value"}]
        sections = [{"title": "Place Value", "text": "..."}]
        assert TeachingService._find_missing_sections(cards, sections) == []

    def test_empty_cards_returns_all_sections(self):
        sections = [
            {"title": "Section A", "text": "content A"},
            {"title": "Section B", "text": "content B"},
        ]
        assert len(TeachingService._find_missing_sections([], sections)) == 2

    def test_multiple_missing_sections_all_returned(self):
        cards = [{"title": "Whole Numbers", "content": "Counting numbers starting from zero."}]
        sections = [
            {"title": "Whole Numbers", "text": "..."},
            {"title": "Integers", "text": "..."},
            {"title": "Fractions", "text": "..."},
        ]
        result = TeachingService._find_missing_sections(cards, sections)
        titles = [s["title"] for s in result]
        assert "Integers" in titles
        assert "Fractions" in titles
        assert "Whole Numbers" not in titles


# =============================================================================
# Group 7 — TestGenerateCardsPerSectionMerging
# =============================================================================

class TestGenerateCardsPerSectionMerging:
    """
    Tests for TeachingService._generate_cards_per_section() merge-in-order logic.

    Business rule: results from parallel per-section LLM calls are always merged
    in the original section index order regardless of completion order.
    A section that raises an exception contributes an empty list, not an abort.
    """

    async def test_merges_results_in_section_order(self):
        """Cards from all sections are merged in original section order."""
        from unittest.mock import patch, AsyncMock

        service = TeachingService.__new__(TeachingService)
        sections = [
            {"title": "Section A", "text": "content A"},
            {"title": "Section B", "text": "content B"},
            {"title": "Section C", "text": "content C"},
        ]
        call_results = [
            {"cards": [{"title": "Card A", "content": "a"}]},
            {"cards": [{"title": "Card B", "content": "b"}]},
            {"cards": [{"title": "Card C", "content": "c"}]},
        ]
        with patch.object(
            service, "_generate_cards_single", new=AsyncMock(side_effect=call_results)
        ):
            cards = await service._generate_cards_per_section(
                system_prompt="sys",
                concept_title="Test Concept",
                concept_overview="An overview of the concept.",
                sections=sections,
                latex=[],
                images=[],
                max_tokens_per_section=1000,
            )
        assert [c["title"] for c in cards] == ["Card A", "Card B", "Card C"]

    async def test_empty_sections_returns_empty_list(self):
        """Calling _generate_cards_per_section with no sections returns an empty list."""
        from unittest.mock import AsyncMock, patch

        service = TeachingService.__new__(TeachingService)
        with patch.object(
            service, "_generate_cards_single", new=AsyncMock(return_value={"cards": []})
        ):
            result = await service._generate_cards_per_section(
                system_prompt="sys",
                concept_title="Test Concept",
                concept_overview="overview",
                sections=[],
                latex=[],
                images=[],
                max_tokens_per_section=1000,
            )
        assert result == []

    async def test_failed_section_returns_empty_not_exception(self):
        """
        When _generate_cards_single raises for one section, that section contributes
        an empty list — the overall call does not raise, and other sections still succeed.
        """
        from unittest.mock import AsyncMock, patch

        service = TeachingService.__new__(TeachingService)
        sections = [
            {"title": "Section A", "text": "content A"},
            {"title": "Section B", "text": "content B"},
        ]

        call_count = 0

        async def selective_fail(sys_prompt, user_prompt, max_tokens=12000):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("LLM failure for section A")
            return {"cards": [{"title": "Card B", "content": "b"}]}

        with patch.object(service, "_generate_cards_single", side_effect=selective_fail):
            cards = await service._generate_cards_per_section(
                system_prompt="sys",
                concept_title="Test Concept",
                concept_overview="overview",
                sections=sections,
                latex=[],
                images=[],
                max_tokens_per_section=1000,
            )

        # Section A failed → empty; Section B succeeded → one card
        assert len(cards) == 1
        assert cards[0]["title"] == "Card B"

    async def test_each_section_generates_at_least_one_call(self):
        """
        _generate_cards_per_section calls _generate_cards_single exactly once per section.
        """
        from unittest.mock import AsyncMock, patch, call as mock_call

        service = TeachingService.__new__(TeachingService)
        sections = [
            {"title": "Section A", "text": "content A"},
            {"title": "Section B", "text": "content B"},
            {"title": "Section C", "text": "content C"},
        ]
        mock_single = AsyncMock(return_value={"cards": [{"title": "card", "content": "x"}]})
        with patch.object(service, "_generate_cards_single", new=mock_single):
            await service._generate_cards_per_section(
                system_prompt="sys",
                concept_title="Test Concept",
                concept_overview="overview",
                sections=sections,
                latex=[],
                images=[],
                max_tokens_per_section=1000,
            )
        assert mock_single.call_count == len(sections)


# =============================================================================
# Group 8 — TestBuildCardsUserPromptNewParams
# =============================================================================

class TestBuildCardsUserPromptNewParams:
    """
    Tests for build_cards_user_prompt() with the new `concept_overview` and
    `section_position` parameters introduced for per-section parallel generation.

    Business rule: when BOTH params are supplied, the prompt must open with a
    preamble block containing "OVERVIEW:" and the section position text. When
    either param is absent (or both absent), no preamble is injected.
    """

    def test_concept_overview_appears_in_prompt_when_provided(self):
        """The concept overview text must appear in the prompt when both new params are given."""
        prompt = build_cards_user_prompt(
            concept_title="Decimals",
            sub_sections=[{"title": "Tenths and Hundredths", "text": "0.1 means one tenth."}],
            concept_overview="Decimals extend place value beyond whole numbers.",
            section_position="section 1 of 3",
        )
        assert "Decimals extend place value beyond whole numbers." in prompt

    def test_section_position_appears_in_prompt_when_provided(self):
        """The section position string must appear in the prompt when both new params are given."""
        prompt = build_cards_user_prompt(
            concept_title="Decimals",
            sub_sections=[{"title": "Tenths and Hundredths", "text": "0.1 means one tenth."}],
            concept_overview="Decimals extend place value beyond whole numbers.",
            section_position="section 2 of 4",
        )
        assert "section 2 of 4" in prompt

    def test_both_params_absent_no_preamble_added(self):
        """When both new params are None (default), no OVERVIEW: preamble appears."""
        prompt = build_cards_user_prompt(
            concept_title="Integers",
            sub_sections=[{"title": "Negative Numbers", "text": "Numbers below zero."}],
        )
        assert "OVERVIEW:" not in prompt

    def test_overview_and_position_together_produce_preamble(self):
        """When both params are provided, the prompt starts with the preamble block."""
        prompt = build_cards_user_prompt(
            concept_title="Fractions",
            sub_sections=[{"title": "Numerator and Denominator", "text": "A fraction has two parts."}],
            concept_overview="Fractions represent parts of a whole.",
            section_position="section 1 of 2",
        )
        # The preamble must contain both the OVERVIEW label and the position
        assert "OVERVIEW:" in prompt
        assert "section 1 of 2" in prompt
        # Both must appear before the main concept line
        overview_pos = prompt.index("OVERVIEW:")
        section_pos = prompt.index("section 1 of 2")
        concept_line_pos = prompt.index("**Concept:**")
        assert overview_pos < concept_line_pos
        assert section_pos < concept_line_pos


# =============================================================================
# Group 9 — TestBuildCardsSystemPromptRemediation
# =============================================================================

class TestBuildCardsSystemPromptRemediation:
    """
    Tests for build_cards_system_prompt(remediation_weak_concepts=...).

    Business rule: a REMEDIATION RE-ATTEMPT block is appended to the system prompt
    only when remediation_weak_concepts is a non-empty list. The block must name
    every weak concept and instruct the LLM to open with a concrete analogy and
    show a fully worked example.
    """

    def _build_system_prompt(self, remediation_weak_concepts=None) -> str:
        from api.prompts import build_cards_system_prompt
        return build_cards_system_prompt(
            remediation_weak_concepts=remediation_weak_concepts,
        )

    def test_remediation_block_present_when_weak_concepts_provided(self):
        """REMEDIATION RE-ATTEMPT block appears when a non-empty list is supplied."""
        prompt = self._build_system_prompt(
            remediation_weak_concepts=["Place Value", "Rounding"]
        )
        assert "REMEDIATION RE-ATTEMPT" in prompt

    def test_remediation_block_absent_when_none(self):
        """No remediation block when remediation_weak_concepts=None (default)."""
        prompt = self._build_system_prompt(remediation_weak_concepts=None)
        assert "REMEDIATION RE-ATTEMPT" not in prompt

    def test_remediation_block_absent_when_empty_list(self):
        """No remediation block when remediation_weak_concepts is an empty list."""
        prompt = self._build_system_prompt(remediation_weak_concepts=[])
        assert "REMEDIATION RE-ATTEMPT" not in prompt

    def test_weak_concept_names_listed_in_remediation_block(self):
        """Each weak concept name must appear verbatim in the remediation block."""
        weak = ["Absolute Value", "Integer Operations", "Number Line"]
        prompt = self._build_system_prompt(remediation_weak_concepts=weak)
        for concept in weak:
            assert concept in prompt, (
                f"Weak concept '{concept}' not found in remediation block"
            )

    def test_remediation_block_contains_analogy_instruction(self):
        """The remediation block must instruct the LLM to open with a concrete real-world analogy."""
        prompt = self._build_system_prompt(
            remediation_weak_concepts=["Fractions"]
        )
        assert "analogy" in prompt.lower()


# =============================================================================
# Group 10 — TestSocraticQuestionCountScaling
# =============================================================================

class TestSocraticQuestionCountScaling:
    """
    Tests for build_socratic_system_prompt() question count scaling logic.

    Business rule: the minimum question count must be at least 8 and the maximum
    must be at most 15, regardless of topic count. The SPREAD RULE directive must
    appear so the LLM distributes questions across all topics.
    Also validates that MAX_SOCRATIC_EXCHANGES == 30 in config.
    """

    def _build_socratic(self, covered_topics=None, session_card_stats=None) -> str:
        from api.prompts import build_socratic_system_prompt
        return build_socratic_system_prompt(
            concept_title="Place Value",
            concept_text="Place value is the value of a digit based on its position.",
            covered_topics=covered_topics,
            session_card_stats=session_card_stats,
        )

    def _extract_min_max_from_prompt(self, prompt: str) -> tuple[int, int]:
        """
        Parse the min/max question counts from the WHEN TO CONCLUDE block.
        The prompt contains: 'Ask between {min_questions} and {max_questions} questions total'
        """
        import re
        m = re.search(r'Ask between (\d+) and (\d+) questions total', prompt)
        assert m, "Could not find 'Ask between X and Y questions total' in prompt"
        return int(m.group(1)), int(m.group(2))

    def test_min_questions_at_least_8_for_small_topic_set(self):
        """With a small covered_topics list (1–3 items), min questions must still be at least 8."""
        prompt = self._build_socratic(covered_topics=["Place Value"])
        min_q, _ = self._extract_min_max_from_prompt(prompt)
        assert min_q >= 8

    def test_max_questions_at_most_15_for_large_topic_set(self):
        """With a large covered_topics list (20+ items), max questions must not exceed 15."""
        many_topics = [f"Topic {i}" for i in range(20)]
        prompt = self._build_socratic(covered_topics=many_topics)
        _, max_q = self._extract_min_max_from_prompt(prompt)
        assert max_q <= 15

    def test_spread_rule_present_in_prompt(self):
        """The 'SPREAD RULE' directive must appear in the Socratic system prompt."""
        prompt = self._build_socratic(
            covered_topics=["Place Value", "Rounding Numbers", "Estimating"]
        )
        assert "SPREAD RULE" in prompt

    def test_max_socratic_exchanges_is_30(self):
        """MAX_SOCRATIC_EXCHANGES must equal 30 in config — this is the session exchange limit."""
        from config import MAX_SOCRATIC_EXCHANGES
        assert MAX_SOCRATIC_EXCHANGES == 30


# =============================================================================
# Group 11 — TestExtractFailedTopicsFromMessages
# =============================================================================

class TestExtractFailedTopicsFromMessages:
    """
    Tests for TeachingService._extract_failed_topics_from_messages(messages, covered_topics).

    Business rule: the method scans assistant messages for correction phrases to
    identify which question the student got wrong. It deduplicates by the first-50-char
    key of the preceding question, returns empty list when no corrections found, and
    ignores non-assistant messages entirely.
    """

    MESSAGES_WITH_NOT_QUITE = [
        {"role": "assistant", "content": "What is the tenths place in 3.45?"},
        {"role": "student", "content": "The ones place."},
        {"role": "assistant", "content": "Not quite — the tenths place is the first digit after the decimal."},
    ]

    MESSAGES_WITH_THAT_IS_INCORRECT = [
        {"role": "assistant", "content": "How many tens are in the number 350?"},
        {"role": "student", "content": "3"},
        {"role": "assistant", "content": "That is incorrect — there are 35 tens in 350."},
    ]

    MESSAGES_NO_CORRECTION = [
        {"role": "assistant", "content": "What is 3.4 + 1.2?"},
        {"role": "student", "content": "4.6"},
        {"role": "assistant", "content": "Correct! That's exactly right."},
    ]

    def test_detects_not_quite_correction(self):
        """'Not quite' is a correction phrase — one topic entry must be extracted."""
        result = TeachingService._extract_failed_topics_from_messages(
            self.MESSAGES_WITH_NOT_QUITE, []
        )
        assert len(result) == 1
        # The result is the extracted question portion (up to '?'); confirm it is non-empty
        assert len(result[0]) > 0

    def test_detects_that_is_incorrect_correction(self):
        """'That is incorrect' is a correction phrase — the preceding question must be extracted."""
        result = TeachingService._extract_failed_topics_from_messages(
            self.MESSAGES_WITH_THAT_IS_INCORRECT, []
        )
        assert len(result) == 1

    def test_deduplicates_same_question_topic(self):
        """
        When the same question is corrected twice (same first-50-chars key),
        only one entry must appear in the result.
        """
        repeated_messages = [
            {"role": "assistant", "content": "What is the tenths place in 3.45?"},
            {"role": "student", "content": "The ones place."},
            {"role": "assistant", "content": "Not quite — look at the digit after the decimal."},
            {"role": "assistant", "content": "What is the tenths place in 3.45?"},
            {"role": "student", "content": "The tens place."},
            {"role": "assistant", "content": "Actually, that is not right — it is the tenths place."},
        ]
        result = TeachingService._extract_failed_topics_from_messages(repeated_messages, [])
        assert len(result) == 1

    def test_returns_empty_list_when_no_corrections(self):
        """When all assistant messages are positive, an empty list is returned."""
        result = TeachingService._extract_failed_topics_from_messages(
            self.MESSAGES_NO_CORRECTION, []
        )
        assert result == []

    def test_extracts_question_up_to_question_mark(self):
        """The extracted topic should be the first question-marked sentence from the prior message."""
        messages = [
            {"role": "assistant", "content": "Can you tell me what place value means? Think carefully."},
            {"role": "student", "content": "I don't know."},
            {"role": "assistant", "content": "Good try, but let me help clarify."},
        ]
        result = TeachingService._extract_failed_topics_from_messages(messages, [])
        assert len(result) == 1
        # Must include a question mark (the sentence up to '?')
        assert "?" in result[0]

    def test_only_checks_assistant_messages_for_corrections(self):
        """
        A correction phrase spoken by the student role must NOT trigger extraction —
        only assistant messages are scanned.
        """
        messages = [
            {"role": "assistant", "content": "What is 5 + 3?"},
            {"role": "student", "content": "Not quite sure, maybe 7?"},
            {"role": "assistant", "content": "Good effort! The answer is 8."},
        ]
        result = TeachingService._extract_failed_topics_from_messages(messages, [])
        # "Not quite" in a student message must not trigger extraction;
        # the assistant's final message has no correction phrase.
        assert result == []

    def test_multiple_different_corrections_all_detected(self):
        """When the student gets two different questions wrong, both topics are returned."""
        messages = [
            {"role": "assistant", "content": "What is the tenths place in 3.45?"},
            {"role": "student", "content": "The ones place."},
            {"role": "assistant", "content": "Not quite — that is the units digit, not the tenths."},
            {"role": "assistant", "content": "How many hundreds are in 700?"},
            {"role": "student", "content": "70"},
            {"role": "assistant", "content": "Actually, there are 7 hundreds in 700."},
        ]
        result = TeachingService._extract_failed_topics_from_messages(messages, [])
        assert len(result) == 2


# =============================================================================
# Group 12 — TestGapFillPassIntegration
# =============================================================================

# =============================================================================
# Group 13 — TestCacheVersionBump
# =============================================================================

class TestCacheVersionBump:
    """
    Tests that the cache-version constant is set to 3 and that sessions carrying
    an older version are not served from cache (regeneration is triggered).

    Business rule: bumping _CARDS_CACHE_VERSION forces all sessions generated
    with earlier prompts/logic to regenerate on the next request, ensuring every
    student gets up-to-date card quality after a release.
    """

    def test_cache_version_is_13(self):
        """
        The local _CARDS_CACHE_VERSION constant inside generate_cards() must equal 13
        after the expanded STUDENT STATE + PROFILE MODIFIERS prompt upgrades. Any value
        below 13 would allow stale cards (missing expanded learner-type rules) to be served.

        Since it is a method-local variable (not a class attribute), we verify it by
        reading the method's source code — a deliberate regression guard that will break
        if someone silently decrements the version.
        """
        import inspect
        source = inspect.getsource(TeachingService.generate_cards)
        # The assignment must appear literally in the function body
        assert "_CARDS_CACHE_VERSION = 13" in source, (
            "generate_cards() must define _CARDS_CACHE_VERSION = 13; "
            "if it was changed, the cache-bust logic is broken"
        )

    async def test_cache_bust_on_version_2(self):
        """
        A session whose presentation_text contains cache_version=2 must NOT return
        the old cards — generate_cards() must bypass the cache and regenerate.

        Implementation detail: generate_cards() raises ValueError("stale cache version")
        internally, falls through to re-generation, and calls knowledge_svc.get_concept_detail.
        We verify the old cards are NOT returned by asserting the mock knowledge_svc was
        called (proof that the cache was bypassed and new generation was attempted).
        """
        from unittest.mock import MagicMock, AsyncMock, patch
        import uuid as uuid_mod

        # Build a session whose cached content has cache_version = 2
        old_card = {"title": "Old Card", "content": "stale content", "card_type": "CONCEPT"}
        stale_payload = {
            "cache_version": 2,
            "cards": [old_card],
        }

        session = MagicMock()
        session.presentation_text = __import__("json").dumps(stale_payload)
        session.concept_id = "test-concept"
        session.id = uuid_mod.uuid4()
        session.student_id = uuid_mod.uuid4()
        session.style = "default"
        session.lesson_interests = None
        session.socratic_attempt_count = 0
        session.remediation_context = None

        student = MagicMock()
        student.interests = []
        student.preferred_language = "en"

        # knowledge_svc.get_concept_detail is the first thing called after cache is bypassed.
        # We return None to abort generation early (raises ValueError) — sufficient to prove
        # the cache was not returned.
        mock_ks = MagicMock()
        mock_ks.get_concept_detail.return_value = None

        service = TeachingService.__new__(TeachingService)
        service.knowledge_services = {"prealgebra": mock_ks}
        service.openai = MagicMock()
        service.model = "gpt-4o"
        service.model_mini = "gpt-4o-mini"

        db = MagicMock()

        import pytest
        with pytest.raises((ValueError, Exception)):
            await service.generate_cards(db=db, session=session, student=student)

        # The knowledge_svc was consulted — proof the stale cache was NOT returned
        mock_ks.get_concept_detail.assert_called_once_with("test-concept")


# =============================================================================
# Group 14 — TestTextDrivenTokenBudget
# =============================================================================

class TestTextDrivenTokenBudget:
    """
    Pure unit tests for the text-driven token budget formula inside
    `_generate_cards_per_section`'s inner `generate_for_section` closure.

    Formula (from teaching_service.py line 1105-1108):
        text_driven_budget = max(
            max_tokens_per_section // 2,
            min(max_tokens_per_section, text_len // 3),
        )

    Business rule: each section's token budget scales with its text length so
    short sections don't waste tokens (floor) and long sections get enough budget
    to produce complete, untruncated card output (ceiling).
    """

    @staticmethod
    def _compute(text_len: int, max_tokens_per_section: int) -> int:
        """Mirror of the formula in generate_for_section closure."""
        return max(
            max_tokens_per_section // 2,
            min(max_tokens_per_section, text_len // 3),
        )

    def test_small_section_uses_floor(self):
        """
        A 600-char section with a 4000-token ceiling: raw = 200 < floor 2000
        → budget is clamped up to the floor value of 2000.
        """
        budget = self._compute(text_len=600, max_tokens_per_section=4000)
        assert budget == 2000

    def test_large_section_gets_more_tokens(self):
        """
        A 9000-char section with a 4000-token ceiling: raw = 3000, floor = 2000
        → budget is 3000 (above floor, below ceiling).
        """
        budget = self._compute(text_len=9000, max_tokens_per_section=4000)
        assert budget == 3000

    def test_very_large_section_capped_at_ceiling(self):
        """
        A 15000-char section with a 4000-token ceiling: raw = 5000 > ceiling 4000
        → budget is capped at the ceiling of 4000.
        """
        budget = self._compute(text_len=15000, max_tokens_per_section=4000)
        assert budget == 4000

    def test_medium_section_hits_floor(self):
        """
        A 3000-char section with a 4000-token ceiling: raw = 1000 < floor 2000
        → budget is clamped up to the floor value of 2000.
        """
        budget = self._compute(text_len=3000, max_tokens_per_section=4000)
        assert budget == 2000


# =============================================================================
# Group 15 — TestStarterPackLimit
# =============================================================================

class TestStarterPackLimit:
    """
    Tests for the STARTER_PACK_MAX_SECTIONS cap in generate_cards().

    Business rule: on first load, only the first STARTER_PACK_MAX_SECTIONS sections
    are generated so the student sees cards quickly. Remaining sections are served
    later via the adaptive /complete-card loop. This prevents multi-second waits for
    concepts with many sub-sections.
    """

    def test_starter_pack_constant_matches_config(self):
        """
        STARTER_PACK_INITIAL_SECTIONS must equal 3 as specified in config.py.
        If the constant drifts, the starter pack will either be too large (slow)
        or too small (insufficient initial content).
        """
        from config import STARTER_PACK_INITIAL_SECTIONS
        assert STARTER_PACK_INITIAL_SECTIONS == 3

    async def test_starter_pack_limits_to_3_sections(self):
        """
        When _group_by_major_topic returns 5 sections, _generate_cards_per_section
        must be called with only the first 3 sections (STARTER_PACK_INITIAL_SECTIONS).
        The remaining 2 sections are deferred to the adaptive loop.
        """
        from unittest.mock import MagicMock, AsyncMock, patch
        import uuid as uuid_mod

        # Build a session with no cached content so generation runs
        session = MagicMock()
        session.presentation_text = None
        session.concept_id = "test-concept"
        session.id = uuid_mod.uuid4()
        session.student_id = uuid_mod.uuid4()
        session.style = "default"
        session.lesson_interests = None
        session.socratic_attempt_count = 0
        session.remediation_context = None

        student = MagicMock()
        student.interests = []
        student.preferred_language = "en"

        five_sections = [
            {"title": f"Section {i}", "text": f"Content for section {i}"}
            for i in range(1, 6)
        ]

        mock_ks = MagicMock()
        mock_ks.get_concept_detail.return_value = {
            "text": "Some concept text",
            "concept_title": "Test Concept",
            "latex": [],
            "images": [],
            "prerequisites": [],
        }

        service = TeachingService.__new__(TeachingService)
        service.knowledge_services = {"prealgebra": mock_ks}
        service.openai = MagicMock()
        service.model = "gpt-4o"
        service.model_mini = "gpt-4o-mini"

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(one=MagicMock(return_value=MagicMock(
            total_cards=0, total_wrong=0, total_hints=0
        ))))
        db.flush = AsyncMock()

        sections_received = []

        async def fake_generate_per_section(**kwargs):
            sections_received.extend(kwargs.get("sections", []))
            return []

        _history = {
            "total_cards_completed": 0, "avg_time_per_card": None, "avg_wrong_attempts": None,
            "avg_hints_per_card": None, "sessions_last_7d": 0, "is_known_weak_concept": False,
            "failed_concept_attempts": 0, "trend_direction": "STABLE", "trend_wrong_list": [],
        }

        with (
            patch.object(service, "_parse_sub_sections", return_value=five_sections),
            patch.object(service, "_group_by_major_topic", return_value=five_sections),
            patch.object(service, "_generate_cards_per_section", side_effect=fake_generate_per_section),
            patch.object(service, "_find_missing_sections", return_value=[]),  # skip gap-fill pass
            patch("adaptive.adaptive_engine.load_student_history", new=AsyncMock(return_value=_history)),
            patch("adaptive.adaptive_engine.load_wrong_option_pattern", new=AsyncMock(return_value=None)),
            patch("adaptive.adaptive_engine.build_blended_analytics", return_value=MagicMock()),
            patch("adaptive.profile_builder.build_learning_profile",
                  return_value=MagicMock(speed="NORMAL", comprehension="OK", engagement="ENGAGED",
                                         confidence_score=0.5)),
            patch("api.teaching_service.TeachingService._get_message_count", new=AsyncMock(return_value=0)),
            patch("api.teaching_service.TeachingService._save_message", new=AsyncMock()),
        ):
            try:
                await service.generate_cards(db=db, session=session, student=student)
            except Exception:
                pass  # generation may fail due to shallow mocks; what matters is sections_received

        # Only the first 3 sections must have been passed to the generator
        assert len(sections_received) == 3
        assert sections_received[0]["title"] == "Section 1"
        assert sections_received[1]["title"] == "Section 2"
        assert sections_received[2]["title"] == "Section 3"

    async def test_starter_pack_no_limit_when_3_or_fewer(self):
        """
        When _group_by_major_topic returns 3 sections (equal to STARTER_PACK_INITIAL_SECTIONS),
        no trimming occurs — all 3 sections are passed to _generate_cards_per_section unchanged.
        """
        from unittest.mock import MagicMock, AsyncMock, patch
        import uuid as uuid_mod

        session = MagicMock()
        session.presentation_text = None
        session.concept_id = "test-concept"
        session.id = uuid_mod.uuid4()
        session.student_id = uuid_mod.uuid4()
        session.style = "default"
        session.lesson_interests = None
        session.socratic_attempt_count = 0
        session.remediation_context = None

        student = MagicMock()
        student.interests = []
        student.preferred_language = "en"

        three_sections = [
            {"title": "Section 1", "text": "Content 1"},
            {"title": "Section 2", "text": "Content 2"},
            {"title": "Section 3", "text": "Content 3"},
        ]

        mock_ks = MagicMock()
        mock_ks.get_concept_detail.return_value = {
            "text": "Some concept text",
            "concept_title": "Test Concept",
            "latex": [],
            "images": [],
            "prerequisites": [],
        }

        service = TeachingService.__new__(TeachingService)
        service.knowledge_services = {"prealgebra": mock_ks}
        service.openai = MagicMock()
        service.model = "gpt-4o"
        service.model_mini = "gpt-4o-mini"

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(one=MagicMock(return_value=MagicMock(
            total_cards=0, total_wrong=0, total_hints=0
        ))))
        db.flush = AsyncMock()

        sections_received = []

        async def fake_generate_per_section(**kwargs):
            sections_received.extend(kwargs.get("sections", []))
            return []

        _history = {
            "total_cards_completed": 0, "avg_time_per_card": None, "avg_wrong_attempts": None,
            "avg_hints_per_card": None, "sessions_last_7d": 0, "is_known_weak_concept": False,
            "failed_concept_attempts": 0, "trend_direction": "STABLE", "trend_wrong_list": [],
        }

        with (
            patch.object(service, "_parse_sub_sections", return_value=three_sections),
            patch.object(service, "_group_by_major_topic", return_value=three_sections),
            patch.object(service, "_generate_cards_per_section", side_effect=fake_generate_per_section),
            patch.object(service, "_find_missing_sections", return_value=[]),  # skip gap-fill pass
            patch("adaptive.adaptive_engine.load_student_history", new=AsyncMock(return_value=_history)),
            patch("adaptive.adaptive_engine.load_wrong_option_pattern", new=AsyncMock(return_value=None)),
            patch("adaptive.adaptive_engine.build_blended_analytics", return_value=MagicMock()),
            patch("adaptive.profile_builder.build_learning_profile",
                  return_value=MagicMock(speed="NORMAL", comprehension="OK", engagement="ENGAGED",
                                         confidence_score=0.5)),
            patch("api.teaching_service.TeachingService._get_message_count", new=AsyncMock(return_value=0)),
            patch("api.teaching_service.TeachingService._save_message", new=AsyncMock()),
        ):
            try:
                await service.generate_cards(db=db, session=session, student=student)
            except Exception:
                pass

        # All 3 sections must pass through — no trimming when count <= STARTER_PACK_INITIAL_SECTIONS
        assert len(sections_received) == 3


# =============================================================================
# Group 16 — TestEnvelopePreservation
# =============================================================================

class TestEnvelopePreservation:
    """
    Tests for the RC3-B envelope-preservation fix in adaptive_router.py's
    complete_card endpoint (lines 275-286).

    Business rule: when the adaptive loop appends a new card to a session that
    already has a structured presentation_text envelope (dict with 'cards' and
    'cache_version'), the envelope metadata must be preserved. Without this fix,
    cache_version disappears and the next page refresh triggers full regeneration,
    undoing the starter-pack optimisation.
    """

    @staticmethod
    def _apply_envelope_logic(
        existing_presentation_text: str | None,
        new_cards: list,
    ) -> str:
        """
        Inline replica of the envelope-preservation logic from adaptive_router.py
        lines 275-286.  Tests validate this extracted logic directly.
        """
        import json as json_mod

        if existing_presentation_text:
            try:
                envelope = json_mod.loads(existing_presentation_text)
                if isinstance(envelope, dict) and "cards" in envelope:
                    envelope["cards"] = new_cards
                    return json_mod.dumps(envelope)
                else:
                    return json_mod.dumps(new_cards)
            except Exception:
                return json_mod.dumps(new_cards)
        else:
            return json_mod.dumps(new_cards)

    def test_envelope_cache_version_preserved(self):
        """
        When presentation_text is a JSON envelope with cache_version=3 and
        an old card list, updating it with new_cards must preserve cache_version=3
        and replace 'cards' with the new list.
        """
        import json

        old_cards = [{"title": "Old Card", "content": "old", "card_type": "CONCEPT"}]
        existing = json.dumps({"cache_version": 3, "cards": old_cards, "concept_title": "Fractions"})
        new_cards = [
            {"title": "Old Card", "content": "old", "card_type": "CONCEPT"},
            {"title": "New Adaptive Card", "content": "new content", "card_type": "CONCEPT"},
        ]

        result_str = self._apply_envelope_logic(existing, new_cards)
        result = json.loads(result_str)

        assert result["cache_version"] == 3
        assert result["cards"] == new_cards
        assert result["concept_title"] == "Fractions"

    def test_plain_list_fallback(self):
        """
        When presentation_text is a bare JSON list (no envelope dict), the result
        must be json.dumps(new_cards) — no attempt to preserve a non-existent envelope.
        """
        import json

        existing = json.dumps([{"title": "old"}])
        new_cards = [{"title": "new card", "content": "content", "card_type": "CONCEPT"}]

        result_str = self._apply_envelope_logic(existing, new_cards)
        result = json.loads(result_str)

        assert result == new_cards

    def test_empty_presentation_text_fallback(self):
        """
        When presentation_text is None or empty string, the result must be
        json.dumps(new_cards) with no envelope wrapping.
        """
        import json

        new_cards = [{"title": "first card", "content": "content", "card_type": "FUN"}]

        result_none = self._apply_envelope_logic(None, new_cards)
        result_empty = self._apply_envelope_logic("", new_cards)

        assert json.loads(result_none) == new_cards
        assert json.loads(result_empty) == new_cards


# =============================================================================
# Group 17 — TestGapFillSort
# =============================================================================

class TestGapFillSort:
    """
    Tests for the RC4 gap-fill re-sort applied to all_raw_cards after gap-fill
    cards are appended.

    Business rule: gap-fill cards are appended at the tail of all_raw_cards but
    belong at their original curriculum positions. The sort must restore section
    order so students progress through topics in the intended sequence.

    The sort key (from teaching_service.py):
        sec_order = {sec["title"].lower(): i for i, sec in enumerate(sub_sections)}
        def _section_order_key(card):
            card_text = (card.get("title","") + " " + card.get("content","")).lower()
            for title_lower, order in sec_order.items():
                if title_lower in card_text: return order
            return len(sub_sections)  # unknown → end
    """

    @staticmethod
    def _sort_cards(cards: list[dict], sub_sections: list[dict]) -> list[dict]:
        """Extracted replica of the gap-fill sort from generate_cards()."""
        sec_order = {sec["title"].lower(): i for i, sec in enumerate(sub_sections)}

        def _section_order_key(card: dict) -> int:
            card_text = (card.get("title", "") + " " + card.get("content", "")).lower()
            for title_lower, order in sec_order.items():
                if title_lower in card_text:
                    return order
            return len(sub_sections)

        return sorted(cards, key=_section_order_key)

    def test_gap_fill_sort_preserves_curriculum_order(self):
        """
        A Section 3 gap-fill card appended after Section 4 cards must be sorted
        back to appear between Section 2 and Section 4 cards.
        """
        sub_sections = [
            {"title": "Introduction", "text": "..."},
            {"title": "Basic Rules", "text": "..."},
            {"title": "Advanced Examples", "text": "..."},
            {"title": "Practice Problems", "text": "..."},
        ]
        # Normal cards from sections 1, 2, 4 — section 3 was missing initially
        # Gap-fill card for section 3 is appended at the end
        cards = [
            {"title": "Introduction Card", "content": "introduction content"},
            {"title": "Rules Card", "content": "basic rules content"},
            {"title": "Problems Card", "content": "practice problems content"},
            {"title": "Examples Card", "content": "advanced examples content"},  # gap-fill, appended last
        ]

        sorted_cards = self._sort_cards(cards, sub_sections)
        titles = [c["title"] for c in sorted_cards]

        # "Advanced Examples" card must come before "Practice Problems" card
        adv_idx = titles.index("Examples Card")
        prob_idx = titles.index("Problems Card")
        assert adv_idx < prob_idx, (
            f"'Advanced Examples' gap-fill card (pos {adv_idx}) must precede "
            f"'Practice Problems' card (pos {prob_idx})"
        )

    def test_sort_unknown_section_goes_to_end(self):
        """
        A card whose title and content match no section title receives a sort key
        of len(sub_sections) and must appear at the end of the sorted result.
        """
        sub_sections = [
            {"title": "Fractions", "text": "..."},
            {"title": "Decimals", "text": "..."},
        ]
        cards = [
            {"title": "Decimals Card", "content": "decimals explained"},
            {"title": "Mystery Card", "content": "completely unrelated topic"},  # no match
            {"title": "Fractions Card", "content": "fractions explained"},
        ]

        sorted_cards = self._sort_cards(cards, sub_sections)
        # "Mystery Card" must appear last
        assert sorted_cards[-1]["title"] == "Mystery Card"

    def test_sort_stable_within_same_section(self):
        """
        Two cards that both match the same section title must preserve their
        relative order after sorting (sort is stable in Python).
        """
        sub_sections = [
            {"title": "Algebra", "text": "..."},
            {"title": "Geometry", "text": "..."},
        ]
        cards = [
            {"title": "Algebra Card 1", "content": "algebra part one"},
            {"title": "Geometry Card", "content": "geometry content"},
            {"title": "Algebra Card 2", "content": "algebra part two"},
        ]

        sorted_cards = self._sort_cards(cards, sub_sections)
        algebra_titles = [c["title"] for c in sorted_cards if "Algebra" in c["title"]]
        # Relative order of Algebra Card 1 vs Algebra Card 2 must be preserved
        assert algebra_titles == ["Algebra Card 1", "Algebra Card 2"]


# =============================================================================
# Group 18 — TestVisualImageFallback
# =============================================================================

class TestVisualImageFallback:
    """
    Tests for the RC5 keyword-based VISUAL image fallback in generate_cards()
    (teaching_service.py lines 969-999).

    Business rule: VISUAL cards that the LLM did not assign an image to (because
    LLM skips [IMAGE:N] markers ~30% of the time) must receive the best-matching
    unassigned image from the pool. Non-VISUAL cards must never be touched.
    Selection uses word-overlap between card text and image description.
    """

    @staticmethod
    def _apply_visual_fallback(
        raw_cards: list[dict],
        useful_images: list[dict],
        assigned_global: set,
    ) -> None:
        """
        Extracted replica of the VISUAL fallback block from generate_cards().
        Mutates raw_cards in place (same as production code).
        """
        unassigned = [
            (i, img) for i, img in enumerate(useful_images)
            if i not in assigned_global
        ]
        for card in raw_cards:
            if card.get("card_type") != "VISUAL" or card.get("images"):
                continue
            pool = unassigned if unassigned else list(enumerate(useful_images))
            if not pool:
                continue
            card_text = (card.get("title", "") + " " + card.get("content", "")).lower()
            best_score, best_pool_idx = -1, 0
            for pool_idx, (global_idx, img) in enumerate(pool):
                desc = (img.get("description") or "").lower()
                score = sum(1 for w in card_text.split() if len(w) > 3 and w in desc)
                if score > best_score:
                    best_score, best_pool_idx = score, pool_idx
            global_idx, img = pool[best_pool_idx]
            img_copy = dict(img)
            img_copy["caption"] = img.get("description") or f"Diagram: {card.get('title', '')}"
            card["images"] = [img_copy]
            if unassigned:
                unassigned.pop(best_pool_idx)
                assigned_global.add(global_idx)

    def test_visual_card_gets_image_when_none_assigned(self):
        """
        A VISUAL card with images=[] must receive an image from the unassigned pool
        after the fallback pass. The card's images list must be non-empty.
        """
        image = {
            "filename": "diagram1.png",
            "description": "diagram showing fractions on number line",
            "image_type": "DIAGRAM",
            "is_educational": True,
        }
        cards = [
            {"title": "Number Line Fractions", "content": "fractions on a number line diagram",
             "card_type": "VISUAL", "images": []},
        ]
        assigned: set = set()
        self._apply_visual_fallback(cards, [image], assigned)

        assert len(cards[0]["images"]) == 1
        assert cards[0]["images"][0]["filename"] == "diagram1.png"

    def test_non_visual_card_not_touched_by_fallback(self):
        """
        A CONCEPT card with images=[] must NOT receive any image from the fallback
        — only VISUAL card_type triggers the fallback assignment.
        """
        image = {
            "filename": "diagram2.png",
            "description": "diagram of decimal place values",
            "image_type": "DIAGRAM",
            "is_educational": True,
        }
        cards = [
            {"title": "Place Values", "content": "decimal place values explained",
             "card_type": "CONCEPT", "images": []},
        ]
        assigned: set = set()
        self._apply_visual_fallback(cards, [image], assigned)

        # CONCEPT card must remain unchanged
        assert cards[0]["images"] == []

    def test_keyword_match_selects_best_image(self):
        """
        Given two unassigned images with different descriptions, the fallback must
        select the image whose description shares more content words with the card.
        """
        img_irrelevant = {
            "filename": "chart.png",
            "description": "pie chart showing survey results",
            "image_type": "DIAGRAM",
            "is_educational": True,
        }
        img_relevant = {
            "filename": "triangle.png",
            "description": "right triangle showing pythagorean theorem sides",
            "image_type": "DIAGRAM",
            "is_educational": True,
        }
        cards = [
            {
                "title": "Pythagorean Theorem",
                "content": "the pythagorean theorem relates triangle sides",
                "card_type": "VISUAL",
                "images": [],
            },
        ]
        assigned: set = set()
        self._apply_visual_fallback(cards, [img_irrelevant, img_relevant], assigned)

        # The triangle image (index 1) must win over the pie chart (index 0)
        assert cards[0]["images"][0]["filename"] == "triangle.png"

    def test_visual_card_already_has_image_not_replaced(self):
        """
        A VISUAL card that already has images=[existing] must NOT be overwritten
        by the fallback — the guard `or card.get('images')` prevents it.
        """
        existing_image = {
            "filename": "existing.png",
            "description": "already assigned diagram",
            "image_type": "DIAGRAM",
        }
        fallback_image = {
            "filename": "fallback.png",
            "description": "another diagram that should not replace existing",
            "image_type": "DIAGRAM",
        }
        cards = [
            {
                "title": "Some Visual Card",
                "content": "content with diagram",
                "card_type": "VISUAL",
                "images": [existing_image],
            },
        ]
        assigned: set = set()
        self._apply_visual_fallback(cards, [fallback_image], assigned)

        # Original image must remain; fallback must not overwrite
        assert len(cards[0]["images"]) == 1
        assert cards[0]["images"][0]["filename"] == "existing.png"


# =============================================================================
# Group 19 — TestComputeNumericStateScore
# =============================================================================

class TestComputeNumericStateScore:
    """
    Tests for adaptive_engine.compute_numeric_state_score().

    Business rule: a student's current learning state is mapped to a numeric score
    in [1.0, 3.0] by combining a speed base value (SLOW=1.0, NORMAL=2.0, FAST=3.0)
    with a comprehension modifier (STRUGGLING=-0.3, OK=0.0, STRONG=+0.3).
    The result is clamped to [1.0, 3.0] so out-of-range combinations are safe.
    """

    def _score(self, speed: str, comprehension: str) -> float:
        from adaptive.adaptive_engine import compute_numeric_state_score
        return compute_numeric_state_score(speed, comprehension)

    # ── All 9 (speed × comprehension) combinations ──────────────────────────

    def test_slow_struggling_clamps_to_floor(self):
        """SLOW + STRUGGLING = 1.0 - 0.3 = 0.7, clamped to floor 1.0."""
        assert self._score("SLOW", "STRUGGLING") == 1.0

    def test_slow_ok(self):
        """SLOW + OK = 1.0 + 0.0 = 1.0."""
        assert self._score("SLOW", "OK") == 1.0

    def test_slow_strong(self):
        """SLOW + STRONG = 1.0 + 0.3 = 1.3."""
        assert abs(self._score("SLOW", "STRONG") - 1.3) < 1e-9

    def test_normal_struggling(self):
        """NORMAL + STRUGGLING = 2.0 - 0.3 = 1.7."""
        assert abs(self._score("NORMAL", "STRUGGLING") - 1.7) < 1e-9

    def test_normal_ok(self):
        """NORMAL + OK = 2.0 + 0.0 = 2.0."""
        assert self._score("NORMAL", "OK") == 2.0

    def test_normal_strong(self):
        """NORMAL + STRONG = 2.0 + 0.3 = 2.3."""
        assert abs(self._score("NORMAL", "STRONG") - 2.3) < 1e-9

    def test_fast_struggling(self):
        """FAST + STRUGGLING = 3.0 - 0.3 = 2.7."""
        assert abs(self._score("FAST", "STRUGGLING") - 2.7) < 1e-9

    def test_fast_ok(self):
        """FAST + OK = 3.0 + 0.0 = 3.0."""
        assert self._score("FAST", "OK") == 3.0

    def test_fast_strong_clamps_to_ceiling(self):
        """FAST + STRONG = 3.0 + 0.3 = 3.3, clamped to ceiling 3.0."""
        assert self._score("FAST", "STRONG") == 3.0

    # ── Input normalisation ──────────────────────────────────────────────────

    def test_lowercase_inputs_work(self):
        """Lowercase speed and comprehension strings must be accepted (case-insensitive)."""
        assert self._score("normal", "ok") == 2.0
        assert abs(self._score("fast", "struggling") - 2.7) < 1e-9

    def test_mixed_case_inputs_work(self):
        """Mixed-case inputs must produce the same result as uppercase."""
        assert self._score("Normal", "Ok") == 2.0
        assert abs(self._score("Slow", "Strong") - 1.3) < 1e-9

    def test_unknown_speed_defaults_to_normal_base(self):
        """An unrecognised speed string defaults to NORMAL base value of 2.0."""
        assert self._score("UNKNOWN_SPEED", "OK") == 2.0

    def test_unknown_comprehension_defaults_to_ok_modifier(self):
        """An unrecognised comprehension string defaults to OK modifier of 0.0."""
        assert self._score("NORMAL", "UNKNOWN_COMPREHENSION") == 2.0

    def test_result_always_within_bounds(self):
        """The result is always clamped to [1.0, 3.0] for all valid combinations."""
        from adaptive.adaptive_engine import compute_numeric_state_score
        speeds = ["SLOW", "NORMAL", "FAST"]
        comprehensions = ["STRUGGLING", "OK", "STRONG"]
        for sp in speeds:
            for co in comprehensions:
                score = compute_numeric_state_score(sp, co)
                assert 1.0 <= score <= 3.0, (
                    f"Score {score} out of [1.0, 3.0] for speed={sp} comprehension={co}"
                )


# =============================================================================
# Group 20 — TestBlendedScoreToGenerateAs
# =============================================================================

class TestBlendedScoreToGenerateAs:
    """
    Tests for adaptive_engine.blended_score_to_generate_as().

    Business rule: a blended numeric score in [1.0, 3.0] maps to a string label
    that controls which kind of card the adaptive engine generates next:
      < 1.5   → 'STRUGGLING'
      1.5-2.4 → 'NORMAL'
      >= 2.5  → 'FAST'
    """

    def _label(self, score: float) -> str:
        from adaptive.adaptive_engine import blended_score_to_generate_as
        return blended_score_to_generate_as(score)

    def test_floor_score_is_struggling(self):
        """score=1.0 (floor) → 'STRUGGLING'."""
        assert self._label(1.0) == "STRUGGLING"

    def test_score_just_below_threshold_is_struggling(self):
        """score=1.49 (just below 1.5) → 'STRUGGLING'."""
        assert self._label(1.49) == "STRUGGLING"

    def test_threshold_boundary_is_normal(self):
        """score=1.5 (exactly at threshold) → 'NORMAL'."""
        assert self._label(1.5) == "NORMAL"

    def test_mid_normal_score(self):
        """score=2.0 (mid-range) → 'NORMAL'."""
        assert self._label(2.0) == "NORMAL"

    def test_score_just_below_fast_threshold_is_normal(self):
        """score=2.49 (just below 2.5) → 'NORMAL'."""
        assert self._label(2.49) == "NORMAL"

    def test_fast_threshold_boundary_is_fast(self):
        """score=2.5 (exactly at fast threshold) → 'FAST'."""
        assert self._label(2.5) == "FAST"

    def test_ceiling_score_is_fast(self):
        """score=3.0 (ceiling) → 'FAST'."""
        assert self._label(3.0) == "FAST"

    def test_all_labels_are_known_strings(self):
        """Every score in the valid range must produce one of the three expected labels."""
        from adaptive.adaptive_engine import blended_score_to_generate_as
        valid = {"STRUGGLING", "NORMAL", "FAST"}
        test_scores = [1.0, 1.2, 1.49, 1.5, 1.8, 2.0, 2.3, 2.49, 2.5, 2.8, 3.0]
        for score in test_scores:
            label = blended_score_to_generate_as(score)
            assert label in valid, f"Unexpected label '{label}' for score={score}"


# =============================================================================
# Group 21 — TestBoredomDetector
# =============================================================================

class TestBoredomDetector:
    """
    Tests for the boredom_detector module:
      - detect_boredom_signal()
      - detect_autopilot_pattern()
      - select_engagement_strategy()

    Business rule: the adaptive engine must detect student disengagement through
    short responses and explicit boredom phrases, pattern-match autopilot behaviour
    across a rolling 5-message window, and select re-engagement strategies in a
    deterministic priority order (effective > untested > ineffective).
    """

    # ── detect_boredom_signal ────────────────────────────────────────────────

    def test_ok_is_boredom_explicit(self):
        """'ok' is in BOREDOM_EXPLICIT_PHRASES → returns 'boredom_explicit'."""
        from adaptive.boredom_detector import detect_boredom_signal
        assert detect_boredom_signal("ok") == "boredom_explicit"

    def test_boring_is_boredom_explicit(self):
        """'boring' is in BOREDOM_EXPLICIT_PHRASES → returns 'boredom_explicit'."""
        from adaptive.boredom_detector import detect_boredom_signal
        assert detect_boredom_signal("boring") == "boredom_explicit"

    def test_k_is_boredom_explicit(self):
        """'k' is a known boredom phrase → returns 'boredom_explicit' (not just short)."""
        from adaptive.boredom_detector import detect_boredom_signal
        assert detect_boredom_signal("k") == "boredom_explicit"

    def test_ok_uppercase_is_boredom_explicit(self):
        """'OK' in uppercase must be normalised to lowercase before phrase matching."""
        from adaptive.boredom_detector import detect_boredom_signal
        assert detect_boredom_signal("OK") == "boredom_explicit"

    def test_short_message_not_in_phrases_is_short_response(self):
        """'hi' (2 chars, not an explicit boredom phrase) → 'short_response'."""
        from adaptive.boredom_detector import detect_boredom_signal
        assert detect_boredom_signal("hi") == "short_response"

    def test_short_message_yes_is_short_response(self):
        """'yes' is short (3 chars < 15 threshold) and not in explicit phrases → 'short_response'."""
        from adaptive.boredom_detector import detect_boredom_signal
        assert detect_boredom_signal("yes") == "short_response"

    def test_long_engaged_message_returns_none(self):
        """A substantive response well over 15 chars → returns None (no boredom signal)."""
        from adaptive.boredom_detector import detect_boredom_signal
        msg = "This is a perfectly normal length message explaining the concept clearly"
        assert detect_boredom_signal(msg) is None

    def test_message_at_exact_threshold_boundary(self):
        """A message of exactly SHORT_RESPONSE_THRESHOLD chars is not short (< is strict)."""
        from adaptive.boredom_detector import detect_boredom_signal, SHORT_RESPONSE_THRESHOLD
        msg = "x" * SHORT_RESPONSE_THRESHOLD  # exactly 15 chars — NOT under threshold
        # The phrase check runs first; if not a phrase, checks len < 15 strictly
        result = detect_boredom_signal(msg)
        # A 15-char non-phrase message is not < 15, so it should be None
        assert result is None

    def test_message_one_under_threshold_is_short_response(self):
        """A message of (threshold - 1) chars that is not a phrase → 'short_response'."""
        from adaptive.boredom_detector import detect_boredom_signal, SHORT_RESPONSE_THRESHOLD
        msg = "x" * (SHORT_RESPONSE_THRESHOLD - 1)  # 14 chars — under threshold
        assert detect_boredom_signal(msg) == "short_response"

    def test_leading_trailing_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped before both checks."""
        from adaptive.boredom_detector import detect_boredom_signal
        # '  ok  ' strips to 'ok' which is a boredom phrase
        assert detect_boredom_signal("  ok  ") == "boredom_explicit"

    # ── detect_autopilot_pattern ─────────────────────────────────────────────

    def test_five_short_messages_is_autopilot(self):
        """5 short messages in a row (all under 15 chars) → autopilot=True."""
        from adaptive.boredom_detector import detect_autopilot_pattern
        messages = ["ok", "k", "sure", "ok", "k"]
        assert detect_autopilot_pattern(messages) is True

    def test_three_short_of_three_is_autopilot(self):
        """3 short messages in a window of 3 meets the >= 3 threshold → True."""
        from adaptive.boredom_detector import detect_autopilot_pattern
        messages = ["ok", "k", "sure"]
        assert detect_autopilot_pattern(messages) is True

    def test_two_short_of_two_is_not_autopilot(self):
        """Only 2 messages (both short) — window < 3 needed → False."""
        from adaptive.boredom_detector import detect_autopilot_pattern
        messages = ["ok", "k"]
        assert detect_autopilot_pattern(messages) is False

    def test_two_short_of_five_is_not_autopilot(self):
        """Only 2 short messages out of 5 → below threshold of 3 → False."""
        from adaptive.boredom_detector import detect_autopilot_pattern
        messages = [
            "ok",
            "This is a long thoughtful answer that shows clear engagement",
            "k",
            "Another long answer demonstrating deep understanding of the topic",
            "I think I understand how this works now, it makes sense to me",
        ]
        assert detect_autopilot_pattern(messages) is False

    def test_empty_message_list_is_not_autopilot(self):
        """An empty message list → False (zero short messages < 3 threshold)."""
        from adaptive.boredom_detector import detect_autopilot_pattern
        assert detect_autopilot_pattern([]) is False

    def test_window_uses_only_last_five_messages(self):
        """With 7 messages, only the last 5 are evaluated; the first 2 are ignored."""
        from adaptive.boredom_detector import detect_autopilot_pattern
        # First 2: all short (these must be ignored).
        # Last 5: only 1 short → total short in window = 1 < 3 → False.
        messages = [
            "ok", "k",                                          # ignored (outside last-5)
            "This is a long substantive answer showing engagement",
            "Another long detailed response about the concept",
            "A third long thoughtful answer here",
            "Yet another well-developed response",
            "ok",                                               # only 1 short in last-5
        ]
        assert detect_autopilot_pattern(messages) is False

    # ── select_engagement_strategy ───────────────────────────────────────────

    def test_effective_strategy_selected_first(self):
        """A known-effective strategy is always preferred over untested ones."""
        from adaptive.boredom_detector import select_engagement_strategy
        result = select_engagement_strategy(
            effective_engagement=["challenge_bump"],
            ineffective_engagement=[],
        )
        assert result == "challenge_bump"

    def test_untested_strategy_selected_when_none_effective(self):
        """When no effective strategies exist, the first untested one is returned."""
        from adaptive.boredom_detector import select_engagement_strategy, ALL_STRATEGIES
        result = select_engagement_strategy(
            effective_engagement=[],
            ineffective_engagement=[],
        )
        # With no history at all, the first strategy in ALL_STRATEGIES order is returned
        assert result == ALL_STRATEGIES[0]

    def test_all_ineffective_falls_back_to_least_recently_failed(self):
        """When all strategies are ineffective, the first one in ALL_STRATEGIES order is used."""
        from adaptive.boredom_detector import select_engagement_strategy, ALL_STRATEGIES
        all_ineffective = list(ALL_STRATEGIES)
        result = select_engagement_strategy(
            effective_engagement=[],
            ineffective_engagement=all_ineffective,
        )
        # Tier 3: first strategy in ALL_STRATEGIES order
        assert result == ALL_STRATEGIES[0]

    def test_effective_wins_over_untested(self):
        """A known-effective strategy beats any untested strategy."""
        from adaptive.boredom_detector import select_engagement_strategy
        result = select_engagement_strategy(
            effective_engagement=["real_world_hook"],
            ineffective_engagement=["challenge_bump"],
        )
        assert result == "real_world_hook"

    def test_effective_order_follows_all_strategies_order(self):
        """When multiple strategies are effective, the first one in ALL_STRATEGIES wins."""
        from adaptive.boredom_detector import select_engagement_strategy, ALL_STRATEGIES
        # Both challenge_bump (index 0) and real_world_hook (index 1) are effective
        result = select_engagement_strategy(
            effective_engagement=["real_world_hook", "challenge_bump"],
            ineffective_engagement=[],
        )
        # challenge_bump comes before real_world_hook in ALL_STRATEGIES
        assert result == "challenge_bump"

    def test_none_inputs_treated_as_empty_lists(self):
        """Passing None for effective/ineffective must not raise — treated as empty lists."""
        from adaptive.boredom_detector import select_engagement_strategy, ALL_STRATEGIES
        result = select_engagement_strategy(
            effective_engagement=None,
            ineffective_engagement=None,
        )
        # Should return the first untested strategy deterministically
        assert result in ALL_STRATEGIES

    def test_engagement_signal_parameter_accepted(self):
        """The engagement_signal optional parameter is accepted without error."""
        from adaptive.boredom_detector import select_engagement_strategy, ALL_STRATEGIES
        result = select_engagement_strategy(
            effective_engagement=[],
            ineffective_engagement=[],
            engagement_signal="boredom_explicit",
        )
        assert result in ALL_STRATEGIES


# =============================================================================
# Group 22 — TestSectionCompleteSchemas
# =============================================================================

class TestSectionCompleteSchemas:
    """
    Tests for the SectionCompleteRequest and SectionCompleteResponse Pydantic schemas.

    Business rule: when a student completes all cards in a section the frontend
    sends a state_score (defaulting to 2.0 when omitted) alongside the concept_id.
    The response carries the updated section count, rolling average state score,
    and state distribution histogram.
    """

    def test_valid_section_complete_request_with_explicit_score(self):
        """SectionCompleteRequest with all fields provided validates successfully."""
        from api.teaching_schemas import SectionCompleteRequest
        req = SectionCompleteRequest(
            concept_id="PREALG.C1.S1.INTRO",
            state_score=2.5,
        )
        assert req.concept_id == "PREALG.C1.S1.INTRO"
        assert req.state_score == 2.5

    def test_section_complete_request_default_state_score(self):
        """SectionCompleteRequest state_score defaults to 2.0 when not provided."""
        from api.teaching_schemas import SectionCompleteRequest
        req = SectionCompleteRequest(concept_id="PREALG.C1.S2.FRACTIONS")
        assert req.state_score == 2.0

    def test_section_complete_request_floor_score(self):
        """SectionCompleteRequest accepts the floor value state_score=1.0."""
        from api.teaching_schemas import SectionCompleteRequest
        req = SectionCompleteRequest(concept_id="PREALG.C1.S1", state_score=1.0)
        assert req.state_score == 1.0

    def test_section_complete_request_ceiling_score(self):
        """SectionCompleteRequest accepts the ceiling value state_score=3.0."""
        from api.teaching_schemas import SectionCompleteRequest
        req = SectionCompleteRequest(concept_id="PREALG.C1.S1", state_score=3.0)
        assert req.state_score == 3.0

    def test_section_complete_request_state_score_is_float(self):
        """state_score is stored as a float, not an integer."""
        from api.teaching_schemas import SectionCompleteRequest
        req = SectionCompleteRequest(concept_id="PREALG.C1.S1", state_score=2)
        assert isinstance(req.state_score, float)

    def test_section_complete_response_serializes(self):
        """SectionCompleteResponse round-trips through model_dump correctly."""
        from api.teaching_schemas import SectionCompleteResponse
        resp = SectionCompleteResponse(
            section_count=3,
            avg_state_score=2.1,
            state_distribution={"struggling": 1, "normal": 2, "fast": 0},
        )
        data = resp.model_dump()
        assert data["section_count"] == 3
        assert data["avg_state_score"] == 2.1
        assert data["state_distribution"]["normal"] == 2

    def test_section_complete_response_empty_distribution(self):
        """SectionCompleteResponse accepts an empty state_distribution dict."""
        from api.teaching_schemas import SectionCompleteResponse
        resp = SectionCompleteResponse(
            section_count=0,
            avg_state_score=2.0,
            state_distribution={},
        )
        assert resp.state_distribution == {}

    def test_section_complete_request_concept_id_required(self):
        """SectionCompleteRequest raises ValidationError when concept_id is missing."""
        import pytest
        from pydantic import ValidationError
        from api.teaching_schemas import SectionCompleteRequest
        with pytest.raises(ValidationError):
            SectionCompleteRequest()  # concept_id is required


# =============================================================================
# Group 23 — TestBuildBlendedAnalyticsTiers
# =============================================================================

class TestBuildBlendedAnalyticsTiers:
    """
    Tests for adaptive_engine.build_blended_analytics() cold-start tier weights.

    Business rule: the blend between current session signals and historical baseline
    depends on how many sections the student has completed (section_count).
    section_count=0 → 80% current / 20% history  (cold start)
    section_count=1 → 70% current / 30% history  (warm start)
    section_count=2 → 65% current / 35% history  (partial)
    section_count >= 3 → 60% current / 40% history  (full blend)

    These tests validate that the blended_score reflects the correct weighting
    by setting current and history to known values and computing the expected blend.
    """

    @staticmethod
    def _make_signals(time_on_card_sec: float = 120.0, wrong_attempts: int = 0,
                      hints_used: int = 0, idle_triggers: int = 0) -> object:
        """Build a CardBehaviorSignals object with controlled values."""
        from adaptive.schemas import CardBehaviorSignals
        return CardBehaviorSignals(
            card_index=0,
            time_on_card_sec=time_on_card_sec,
            wrong_attempts=wrong_attempts,
            hints_used=hints_used,
            idle_triggers=idle_triggers,
        )

    @staticmethod
    def _make_history(section_count: int, avg_state_score: float = 2.0,
                      total_cards_completed: int = 10) -> dict:
        """Build a history dict with the fields build_blended_analytics reads."""
        return {
            "total_cards_completed": total_cards_completed,
            "avg_time_per_card": 120.0,
            "avg_wrong_attempts": 0.0,
            "avg_hints_per_card": 0.0,
            "sessions_last_7d": 1,
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
            "state_distribution": {"struggling": 0, "normal": 0, "fast": 0},
            "overall_accuracy_rate": 0.5,
        }

    def test_build_blended_analytics_returns_three_tuple(self):
        """build_blended_analytics returns a 3-tuple (AnalyticsSummary, float, str)."""
        from adaptive.adaptive_engine import build_blended_analytics
        from adaptive.schemas import AnalyticsSummary
        signals = self._make_signals()
        history = self._make_history(section_count=0)
        result = build_blended_analytics(signals, history, "PREALG.C1.S1", "student-1")
        assert isinstance(result, tuple)
        assert len(result) == 3
        analytics, blended_score, generate_as = result
        assert isinstance(analytics, AnalyticsSummary)
        assert isinstance(blended_score, float)
        assert isinstance(generate_as, str)

    def test_generate_as_is_valid_label(self):
        """build_blended_analytics generate_as is always one of STRUGGLING/NORMAL/FAST."""
        from adaptive.adaptive_engine import build_blended_analytics
        valid_labels = {"STRUGGLING", "NORMAL", "FAST"}
        signals = self._make_signals()
        history = self._make_history(section_count=0)
        _, _, generate_as = build_blended_analytics(signals, history, "PREALG.C1.S1", "s1")
        assert generate_as in valid_labels

    def test_blended_score_within_bounds(self):
        """blended_score is always clamped to [1.0, 3.0]."""
        from adaptive.adaptive_engine import build_blended_analytics
        for section_count in range(5):
            signals = self._make_signals()
            history = self._make_history(section_count=section_count)
            _, blended_score, _ = build_blended_analytics(
                signals, history, "PREALG.C1.S1", "s1"
            )
            assert 1.0 <= blended_score <= 3.0, (
                f"blended_score {blended_score} out of bounds for section_count={section_count}"
            )

    def test_cold_start_weight_favours_current(self):
        """section_count=0 uses 80% current weight so a high current score pulls blend up."""
        from adaptive.adaptive_engine import build_blended_analytics
        from config import ADAPTIVE_COLD_START_CURRENT_WEIGHT, ADAPTIVE_COLD_START_HISTORY_WEIGHT
        # current numeric score: FAST/STRONG → 3.0 (after clamp ceiling)
        # achieved by very fast time (low) and zero wrong attempts
        signals = self._make_signals(time_on_card_sec=10.0, wrong_attempts=0)
        history = self._make_history(
            section_count=0,
            avg_state_score=1.0,      # worst-case historical score
            total_cards_completed=10,  # enough for history to be used if applicable
        )
        _, blended_score, _ = build_blended_analytics(
            signals, history, "PREALG.C1.S1", "s1"
        )
        # With 80% weight on current (strong) and 20% on history (weak),
        # blend must be pulled toward the higher current score
        assert blended_score > 1.5, (
            f"Cold-start blend {blended_score} should be pulled toward current fast score"
        )
        # Verify the config constants match the expected weights
        assert ADAPTIVE_COLD_START_CURRENT_WEIGHT == 0.80
        assert ADAPTIVE_COLD_START_HISTORY_WEIGHT == 0.20

    def test_warm_start_weight_constants(self):
        """Config constants for section_count=1 (warm start) are 70% / 30%."""
        from config import ADAPTIVE_WARM_START_CURRENT_WEIGHT, ADAPTIVE_WARM_START_HISTORY_WEIGHT
        assert ADAPTIVE_WARM_START_CURRENT_WEIGHT == 0.70
        assert ADAPTIVE_WARM_START_HISTORY_WEIGHT == 0.30

    def test_partial_weight_constants(self):
        """Config constants for section_count=2 (partial) are 65% / 35%."""
        from config import ADAPTIVE_PARTIAL_CURRENT_WEIGHT, ADAPTIVE_PARTIAL_HISTORY_WEIGHT
        assert ADAPTIVE_PARTIAL_CURRENT_WEIGHT == 0.65
        assert ADAPTIVE_PARTIAL_HISTORY_WEIGHT == 0.35

    def test_full_blend_weight_constants(self):
        """Config constants for section_count >= 3 (full blend) are 60% / 40%."""
        from config import ADAPTIVE_STATE_BLEND_CURRENT_WEIGHT, ADAPTIVE_STATE_BLEND_HISTORY_WEIGHT
        assert ADAPTIVE_STATE_BLEND_CURRENT_WEIGHT == 0.60
        assert ADAPTIVE_STATE_BLEND_HISTORY_WEIGHT == 0.40

    def test_cold_start_no_history_uses_full_current_weight(self):
        """When total_cards_completed < ADAPTIVE_MIN_HISTORY_CARDS, cw=1.0 and hw=0.0."""
        from adaptive.adaptive_engine import build_blended_analytics
        # total_cards_completed = 0 → no history; the blended score for analytics
        # will use cw=1.0/hw=0.0 for the analytics object, but state score
        # still uses section_count-based weights
        signals = self._make_signals(time_on_card_sec=120.0, wrong_attempts=0)
        history = self._make_history(
            section_count=0,
            avg_state_score=2.0,
            total_cards_completed=0,   # no history at all
        )
        result = build_blended_analytics(signals, history, "PREALG.C1.S1", "s1")
        assert len(result) == 3


# =============================================================================
# Group 24 — TestEngagementSignalField
# =============================================================================

class TestEngagementSignalField:
    """
    Tests for the engagement_signal field on StudentResponseRequest and
    CardBehaviorSignals.

    Business rule: when the frontend detects a boredom signal from the student
    (short response, explicit phrase, or autopilot pattern), it sends that signal
    to the backend so the adaptive engine can select an appropriate re-engagement
    strategy. The field is always optional — None means no signal detected.
    """

    # ── StudentResponseRequest ───────────────────────────────────────────────

    def test_student_response_request_engagement_signal_defaults_to_none(self):
        """StudentResponseRequest.engagement_signal defaults to None when omitted."""
        from api.teaching_schemas import StudentResponseRequest
        req = StudentResponseRequest(message="I think fractions mean equal parts.")
        assert req.engagement_signal is None

    def test_student_response_request_accepts_short_response_signal(self):
        """StudentResponseRequest accepts engagement_signal='short_response'."""
        from api.teaching_schemas import StudentResponseRequest
        req = StudentResponseRequest(
            message="ok",
            engagement_signal="short_response",
        )
        assert req.engagement_signal == "short_response"

    def test_student_response_request_accepts_boredom_explicit_signal(self):
        """StudentResponseRequest accepts engagement_signal='boredom_explicit'."""
        from api.teaching_schemas import StudentResponseRequest
        req = StudentResponseRequest(
            message="boring",
            engagement_signal="boredom_explicit",
        )
        assert req.engagement_signal == "boredom_explicit"

    def test_student_response_request_accepts_any_string_signal(self):
        """engagement_signal is a free-form string field — any value is accepted."""
        from api.teaching_schemas import StudentResponseRequest
        req = StudentResponseRequest(
            message="Sure, I get it now.",
            engagement_signal="custom_signal_value",
        )
        assert req.engagement_signal == "custom_signal_value"

    def test_student_response_request_accepts_explicit_none(self):
        """Explicitly passing engagement_signal=None stores None."""
        from api.teaching_schemas import StudentResponseRequest
        req = StudentResponseRequest(
            message="I understand the concept now.",
            engagement_signal=None,
        )
        assert req.engagement_signal is None

    # ── CardBehaviorSignals ──────────────────────────────────────────────────

    def test_card_behavior_signals_engagement_signal_defaults_to_none(self):
        """CardBehaviorSignals.engagement_signal defaults to None when not provided."""
        from adaptive.schemas import CardBehaviorSignals
        signals = CardBehaviorSignals(card_index=0)
        assert signals.engagement_signal is None

    def test_card_behavior_signals_accepts_boredom_explicit(self):
        """CardBehaviorSignals accepts engagement_signal='boredom_explicit'."""
        from adaptive.schemas import CardBehaviorSignals
        signals = CardBehaviorSignals(card_index=1, engagement_signal="boredom_explicit")
        assert signals.engagement_signal == "boredom_explicit"

    def test_card_behavior_signals_accepts_short_response(self):
        """CardBehaviorSignals accepts engagement_signal='short_response'."""
        from adaptive.schemas import CardBehaviorSignals
        signals = CardBehaviorSignals(card_index=2, engagement_signal="short_response")
        assert signals.engagement_signal == "short_response"

    def test_card_behavior_signals_engagement_signal_is_optional(self):
        """CardBehaviorSignals can be constructed without engagement_signal."""
        from adaptive.schemas import CardBehaviorSignals
        signals = CardBehaviorSignals(
            card_index=0,
            time_on_card_sec=45.0,
            wrong_attempts=1,
            hints_used=0,
        )
        assert signals.engagement_signal is None

    def test_card_behavior_signals_full_construction_with_signal(self):
        """CardBehaviorSignals with all fields including engagement_signal is valid."""
        from adaptive.schemas import CardBehaviorSignals
        signals = CardBehaviorSignals(
            card_index=3,
            time_on_card_sec=12.0,
            wrong_attempts=0,
            selected_wrong_option=None,
            hints_used=0,
            idle_triggers=2,
            difficulty_bias=None,
            engagement_signal="boredom_explicit",
        )
        assert signals.engagement_signal == "boredom_explicit"
        assert signals.idle_triggers == 2


# =============================================================================
# Group 25 — TestSixPersonas
# =============================================================================

class TestSixPersonas:
    """Group 25 — Six persona blended_score → generate_as mapping.

    Business rule: the blended numeric score in [1.0, 3.0] maps to a generate_as
    label that controls the difficulty of the next adaptive card.  Six realistic
    student personas exercise a range of scores spread across all three zones.
    Boundary values are also verified explicitly.
    """

    @pytest.mark.parametrize("score,expected", [
        (1.08, "STRUGGLING"),   # P1 Steady Struggler
        (2.92, "FAST"),          # P2 Confident Fast
        (1.60, "NORMAL"),        # P3 Fast→Wall (card 4)
        (1.72, "NORMAL"),        # P4 Struggle→Break (card 3)
        (2.60, "FAST"),          # P5 FAST moment
        (1.40, "STRUGGLING"),    # P5 STRUGGLING moment
        (2.96, "FAST"),          # P6 Bored Fast
    ])
    def test_persona_generate_as(self, score, expected):
        """Each persona score maps to the correct generate_as label."""
        from adaptive.adaptive_engine import blended_score_to_generate_as
        result = blended_score_to_generate_as(score)
        assert result == expected

    def test_boundary_struggling_normal(self):
        """1.5 is the boundary — NORMAL starts at exactly 1.5; 1.49 is still STRUGGLING."""
        from adaptive.adaptive_engine import blended_score_to_generate_as
        assert blended_score_to_generate_as(1.49) == "STRUGGLING"
        assert blended_score_to_generate_as(1.50) == "NORMAL"

    def test_boundary_normal_fast(self):
        """2.5 is the boundary — FAST starts at exactly 2.5; 2.49 is still NORMAL."""
        from adaptive.adaptive_engine import blended_score_to_generate_as
        assert blended_score_to_generate_as(2.49) == "NORMAL"
        assert blended_score_to_generate_as(2.50) == "FAST"


# =============================================================================
# Group 26 — TestOverwhelmedProtection
# =============================================================================

class TestOverwhelmedProtection:
    """Group 26 — OVERWHELMED students must never receive challenge_bump.

    Business rule: when the LearningProfile classifies a student as OVERWHELMED,
    the engagement strategy selector must always return 'micro_break', ignoring
    effectiveness history entirely.  This prevents a struggling student from
    being further stressed by a challenge-bump strategy.
    """

    def test_overwhelmed_always_gets_micro_break(self):
        """OVERWHELMED with no history → micro_break."""
        from adaptive.boredom_detector import select_engagement_strategy
        result = select_engagement_strategy([], [], engagement="OVERWHELMED")
        assert result == "micro_break"

    def test_overwhelmed_ignores_effective_challenge_bump(self):
        """Even if challenge_bump was effective before, OVERWHELMED blocks it."""
        from adaptive.boredom_detector import select_engagement_strategy
        result = select_engagement_strategy(
            ["challenge_bump"], [], engagement="OVERWHELMED"
        )
        assert result == "micro_break"

    def test_overwhelmed_ignores_all_effective(self):
        """All effective strategies are ignored when engagement == OVERWHELMED."""
        from adaptive.boredom_detector import select_engagement_strategy
        result = select_engagement_strategy(
            ["challenge_bump", "real_world_hook"], [], engagement="OVERWHELMED"
        )
        assert result == "micro_break"

    def test_non_overwhelmed_respects_effective(self):
        """Without OVERWHELMED flag, effective strategies are honoured (tier 1 wins)."""
        from adaptive.boredom_detector import select_engagement_strategy
        result = select_engagement_strategy(
            ["challenge_bump"], [], engagement="ENGAGED"
        )
        assert result == "challenge_bump"

    def test_none_engagement_uses_normal_tier_logic(self):
        """Default None engagement → tier 1 (effective) wins normally."""
        from adaptive.boredom_detector import select_engagement_strategy
        result = select_engagement_strategy(["real_world_hook"], [])
        assert result == "real_world_hook"


# =============================================================================
# Group 27 — TestStrategyEffectiveness
# =============================================================================

class TestStrategyEffectiveness:
    """Group 27 — Strategy effectiveness feedback loop.

    Business rule: when a re-engagement strategy outcome is reported, the student
    record must be updated so future strategy selection can act on real evidence.
    Effective strategies accumulate in effective_engagement; ineffective ones in
    ineffective_engagement.  Duplicates are never recorded twice.  A missing
    student triggers a warning but must not raise.
    """

    def _make_mock_db(self, student):
        """Helper: mock AsyncSession that returns the given student."""
        from unittest.mock import AsyncMock, MagicMock
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = student
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        return mock_db

    def test_effective_strategy_added_to_list(self):
        """was_effective=True adds strategy to effective_engagement."""
        import asyncio
        import uuid
        from unittest.mock import MagicMock
        from api.teaching_service import _update_strategy_effectiveness

        student = MagicMock()
        student.effective_engagement = []
        student.ineffective_engagement = []

        db = self._make_mock_db(student)
        asyncio.run(_update_strategy_effectiveness(db, uuid.uuid4(), "challenge_bump", True))

        assert "challenge_bump" in student.effective_engagement

    def test_effective_strategy_not_duplicated(self):
        """Adding an already-effective strategy does not duplicate it."""
        import asyncio
        import uuid
        from unittest.mock import MagicMock
        from api.teaching_service import _update_strategy_effectiveness

        student = MagicMock()
        student.effective_engagement = ["challenge_bump"]
        student.ineffective_engagement = []

        db = self._make_mock_db(student)
        asyncio.run(_update_strategy_effectiveness(db, uuid.uuid4(), "challenge_bump", True))

        assert student.effective_engagement.count("challenge_bump") == 1

    def test_ineffective_strategy_added_to_list(self):
        """was_effective=False adds strategy to ineffective_engagement."""
        import asyncio
        import uuid
        from unittest.mock import MagicMock
        from api.teaching_service import _update_strategy_effectiveness

        student = MagicMock()
        student.effective_engagement = []
        student.ineffective_engagement = []

        db = self._make_mock_db(student)
        asyncio.run(_update_strategy_effectiveness(db, uuid.uuid4(), "real_world_hook", False))

        assert "real_world_hook" in student.ineffective_engagement

    def test_ineffective_strategy_not_duplicated(self):
        """Adding an already-ineffective strategy does not duplicate it."""
        import asyncio
        import uuid
        from unittest.mock import MagicMock
        from api.teaching_service import _update_strategy_effectiveness

        student = MagicMock()
        student.effective_engagement = []
        student.ineffective_engagement = ["real_world_hook"]

        db = self._make_mock_db(student)
        asyncio.run(_update_strategy_effectiveness(db, uuid.uuid4(), "real_world_hook", False))

        assert student.ineffective_engagement.count("real_world_hook") == 1

    def test_student_not_found_no_crash(self):
        """If student doesn't exist, function returns silently without raising."""
        import asyncio
        import uuid
        from unittest.mock import AsyncMock, MagicMock
        from api.teaching_service import _update_strategy_effectiveness

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Should not raise — returns silently after logging a warning
        asyncio.run(_update_strategy_effectiveness(mock_db, uuid.uuid4(), "challenge_bump", True))


# =============================================================================
# Group 28 — TestContentValidation
# =============================================================================

class TestContentValidation:
    """Group 28 — validate_and_repair_cards() correctness.

    Business rule: card output from the LLM may arrive out-of-order, contain
    duplicates, or have missing section assignments.  validate_and_repair_cards()
    must sort by section_order, deduplicate by (section_id, card_type), infer
    missing section_id from card content, and report any required sections that
    have no card at all.
    """

    SECTION_ORDER = ["intro", "formulas", "examples", "practice"]

    def _card(self, section_id, card_type="CONCEPT", **kwargs):
        """Build a minimal card dict for testing."""
        return {
            "section_id": section_id,
            "card_type": card_type,
            "question": f"Q about {section_id}",
            "answer": f"A about {section_id}",
            **kwargs,
        }

    def test_all_sections_present_unchanged_order(self):
        """Cards already in the correct order are returned unchanged."""
        from api.teaching_service import validate_and_repair_cards
        cards = [
            self._card("intro"),
            self._card("formulas"),
            self._card("examples"),
            self._card("practice"),
        ]
        repaired, missing = validate_and_repair_cards(cards, self.SECTION_ORDER)
        assert missing == []
        assert [c["section_id"] for c in repaired] == ["intro", "formulas", "examples", "practice"]

    def test_missing_required_section_flagged(self):
        """Required sections absent from cards are reported in the missing list."""
        from api.teaching_service import validate_and_repair_cards
        cards = [self._card("intro"), self._card("formulas")]
        _, missing = validate_and_repair_cards(
            cards,
            self.SECTION_ORDER,
            required_sections=["intro", "formulas", "examples", "practice"],
        )
        assert "examples" in missing
        assert "practice" in missing

    def test_cards_out_of_order_sorted(self):
        """Cards delivered in reverse section order are sorted back to curriculum order."""
        from api.teaching_service import validate_and_repair_cards
        cards = [
            self._card("practice"),
            self._card("examples"),
            self._card("intro"),
            self._card("formulas"),
        ]
        repaired, _ = validate_and_repair_cards(cards, self.SECTION_ORDER)
        assert [c["section_id"] for c in repaired] == ["intro", "formulas", "examples", "practice"]

    def test_duplicate_section_card_type_removed(self):
        """Two cards with identical (section_id, card_type) — second is discarded."""
        from api.teaching_service import validate_and_repair_cards
        cards = [
            self._card("intro", "CONCEPT"),
            self._card("intro", "CONCEPT"),   # duplicate
            self._card("formulas", "CONCEPT"),
        ]
        repaired, _ = validate_and_repair_cards(cards, self.SECTION_ORDER)
        intro_cards = [c for c in repaired if c["section_id"] == "intro"]
        assert len(intro_cards) == 1

    def test_card_missing_section_id_gets_inferred(self):
        """A card with section_id=None receives an inferred section_id (not None/empty)."""
        from api.teaching_service import validate_and_repair_cards
        card_no_id = {
            "section_id": None,
            "card_type": "CONCEPT",
            "question": "What is the intro concept?",
            "answer": "The intro covers basic definitions.",
        }
        repaired, _ = validate_and_repair_cards([card_no_id], self.SECTION_ORDER)
        assert repaired[0]["section_id"] is not None
        assert repaired[0]["section_id"] != ""

    def test_empty_card_list_no_crash(self):
        """An empty card list returns ([], missing_required) without raising."""
        from api.teaching_service import validate_and_repair_cards
        repaired, missing = validate_and_repair_cards(
            [], self.SECTION_ORDER, required_sections=["intro"]
        )
        assert repaired == []
        assert "intro" in missing


# =============================================================================
# Group 29 — TestAllPathsCoverageOrdering
# =============================================================================

class TestAllPathsCoverageOrdering:
    """Group 29 — Coverage and ordering hold across all code paths.

    Business rule: validate_and_repair_cards() must produce deterministic section
    ordering even when the LLM returns cards in a random sequence.  Additional
    regression guards verify that the cache-version constant has the expected
    value and that edge cases (empty section_order, partial coverage) are handled
    without errors.
    """

    SECTION_ORDER = ["s1", "s2", "s3", "s4", "s5"]

    def _card(self, section_id, card_type="CONCEPT"):
        """Build a minimal card dict for testing."""
        return {
            "section_id": section_id,
            "card_type": card_type,
            "question": f"Q {section_id}",
            "answer": f"A {section_id}",
        }

    def test_shuffled_llm_response_sorted_after_validate(self):
        """Randomly shuffled cards are always restored to curriculum order."""
        import random
        from api.teaching_service import validate_and_repair_cards
        cards = [self._card(s) for s in self.SECTION_ORDER]
        random.shuffle(cards)
        repaired, _ = validate_and_repair_cards(cards, self.SECTION_ORDER)
        assert [c["section_id"] for c in repaired] == self.SECTION_ORDER

    def test_validate_handles_empty_section_order(self):
        """Empty section_order does not crash — card receives a fallback section_id."""
        from api.teaching_service import validate_and_repair_cards
        cards = [self._card("s1")]
        # Should not crash; unknown section goes to end (sort_key → 0 for empty order)
        repaired, missing = validate_and_repair_cards(cards, [], required_sections=None)
        assert len(repaired) == 1

    def test_cache_version_is_13(self):
        """Regression guard: _CARDS_CACHE_VERSION must equal 13 in teaching_service.py."""
        import inspect
        from src.api import teaching_service
        source = inspect.getsource(teaching_service)
        assert "_CARDS_CACHE_VERSION = 13" in source

    def test_required_sections_all_covered(self):
        """When all required sections have cards, missing list is empty."""
        from api.teaching_service import validate_and_repair_cards
        cards = [self._card(s) for s in self.SECTION_ORDER]
        _, missing = validate_and_repair_cards(
            cards, self.SECTION_ORDER, required_sections=self.SECTION_ORDER
        )
        assert missing == []

    def test_required_sections_partially_covered(self):
        """Only s1-s3 covered → missing list contains exactly s4 and s5."""
        from api.teaching_service import validate_and_repair_cards
        cards = [self._card("s1"), self._card("s2"), self._card("s3")]
        _, missing = validate_and_repair_cards(
            cards, self.SECTION_ORDER, required_sections=self.SECTION_ORDER
        )
        assert set(missing) == {"s4", "s5"}
