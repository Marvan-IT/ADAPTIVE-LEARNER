"""
Tests for the Master Card Generation Engine — Blueprint Pipeline (Stage 3).

Groups covered:
  1. TeachingService._classify_sections()       — 14 tests
  2. TeachingService._build_textbook_blueprint() — 10 tests
  3. TeachingService._classify_section_type()    —  9 tests
  4. CardMCQ.difficulty field                    —  4 tests
  5. Blueprint fallback condition                —  1 test

All tests are pure-unit: no DB, no OpenAI calls, no fixtures required.
Business mapping: every test name expresses the expected behaviour so that
a non-technical stakeholder can understand what is being validated.
"""

import sys
from pathlib import Path

# Ensure backend/src is importable regardless of how pytest is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from api.teaching_service import TeachingService, _SECTION_CLASSIFIER, _SECTION_DOMAIN_MAP
from api.teaching_schemas import CardMCQ


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sec(title: str, text: str = "some content") -> dict:
    """Build a minimal section dict with the given title and text."""
    return {"title": title, "text": text}


def _classified(title: str, text: str = "some content", section_type: str = "CONCEPT") -> dict:
    """Build a section dict that already has a section_type annotation."""
    return {"title": title, "text": text, "section_type": section_type}


# ─────────────────────────────────────────────────────────────────────────────
# Group 1 — _classify_sections()
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifySections:
    """
    Business criterion: the classifier must annotate every incoming section dict
    with the correct pedagogical type so downstream pipeline stages can route
    each section appropriately.
    """

    def test_learning_objectives_heading_classified_as_learning_objectives(self):
        # Arrange
        sections = [_sec("Learning Objectives")]
        # Act
        result = TeachingService._classify_sections(sections)
        # Assert
        assert result[0]["section_type"] == "LEARNING_OBJECTIVES"

    def test_learning_objective_singular_heading_classified_as_learning_objectives(self):
        """'Learning Objective' (no trailing s) must still match the pattern."""
        sections = [_sec("Learning Objective")]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "LEARNING_OBJECTIVES"

    def test_example_numbered_heading_classified_as_example(self):
        sections = [_sec("Example 1.41")]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "EXAMPLE"

    def test_example_with_word_problem_suffix_classified_as_example(self):
        sections = [_sec("Example 1.52 — Word Problem")]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "EXAMPLE"

    def test_try_it_numbered_heading_classified_as_try_it(self):
        sections = [_sec("Try It 1.77")]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "TRY_IT"

    def test_solution_heading_classified_as_solution(self):
        sections = [_sec("Solution")]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "SOLUTION"

    def test_how_to_heading_classified_as_how_to(self):
        sections = [_sec("HOW TO: Multiply whole numbers")]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "HOW_TO"

    def test_be_prepared_heading_classified_as_prereq_check(self):
        sections = [_sec("Be Prepared")]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "PREREQ_CHECK"

    def test_writing_exercises_heading_classified_as_end_matter(self):
        sections = [_sec("Writing Exercises")]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "END_MATTER"

    def test_practice_makes_perfect_heading_classified_as_end_matter(self):
        sections = [_sec("Practice Makes Perfect")]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "END_MATTER"

    def test_tip_heading_classified_as_tip(self):
        sections = [_sec("Tip")]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "TIP"

    def test_note_heading_classified_as_tip(self):
        sections = [_sec("Note")]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "TIP"

    def test_unrecognised_heading_classified_as_concept_default(self):
        """A heading that matches no pattern must fall back to CONCEPT."""
        sections = [_sec("Use Multiplication Notation")]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == "CONCEPT"

    @pytest.mark.parametrize("title,expected_type", [
        ("Learning Objectives",          "LEARNING_OBJECTIVES"),
        ("Example 2.3",                  "EXAMPLE"),
        ("Try It 3.11",                  "TRY_IT"),
        ("Solution",                     "SOLUTION"),
        ("Practice Makes Perfect",       "END_MATTER"),
    ])
    def test_mixed_batch_all_headings_classified_correctly(self, title: str, expected_type: str):
        """Mixed batch: five different section headings are each classified correctly."""
        sections = [_sec(title)]
        result = TeachingService._classify_sections(sections)
        assert result[0]["section_type"] == expected_type, (
            f"Expected '{expected_type}' for title '{title}', "
            f"got '{result[0]['section_type']}'"
        )

    def test_empty_sections_list_returns_empty_list(self):
        result = TeachingService._classify_sections([])
        assert result == []

    def test_original_section_fields_are_preserved_after_classification(self):
        """Classification must not discard existing keys on the section dict."""
        sec = {"title": "Example 1.1", "text": "hello", "extra_key": "preserved"}
        result = TeachingService._classify_sections([sec])
        assert result[0]["extra_key"] == "preserved"
        assert result[0]["text"] == "hello"
        assert result[0]["title"] == "Example 1.1"


# ─────────────────────────────────────────────────────────────────────────────
# Group 2 — _build_textbook_blueprint()
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildTextbookBlueprint:
    """
    Business criterion: the blueprint must reflect the textbook's pedagogical
    flow — collapsing worked examples with their solutions, attaching tips to
    their anchors, and discarding non-instructional scaffolding so the LLM
    receives a clean, teaching-ordered sequence.
    """

    def test_solution_merged_into_preceding_example_text(self):
        """SOLUTION text appended to the preceding EXAMPLE with a Solution header."""
        classified = [
            _classified("Example 1.1", text="Example body",     section_type="EXAMPLE"),
            _classified("Solution",     text="The answer is 4.", section_type="SOLUTION"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        # Only one item in blueprint (SOLUTION was merged)
        assert len(blueprint) == 1
        assert blueprint[0]["section_type"] == "EXAMPLE"
        assert "The answer is 4." in blueprint[0]["text"]
        assert "**Solution:**" in blueprint[0]["text"]

    def test_solution_merge_appends_with_newlines(self):
        """Merged solution is separated from example body with two newlines."""
        classified = [
            _classified("Example 2.5", text="Body.", section_type="EXAMPLE"),
            _classified("Solution",    text="X=3.",   section_type="SOLUTION"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        assert "\n\n**Solution:**\n" in blueprint[0]["text"]

    def test_tip_merged_into_preceding_item_text(self):
        """TIP text appended to the preceding blueprint item with '> **Note:**' prefix."""
        classified = [
            _classified("How To: Add Fractions", text="Step 1.", section_type="HOW_TO"),
            _classified("Tip",                   text="Watch sign!", section_type="TIP"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        assert len(blueprint) == 1
        assert "> **Note:**" in blueprint[0]["text"]
        assert "Watch sign!" in blueprint[0]["text"]

    def test_supplementary_section_skipped(self):
        classified = [
            _classified("Concept A",    section_type="CONCEPT"),
            _classified("Manipulative", section_type="SUPPLEMENTARY"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        assert len(blueprint) == 1
        assert blueprint[0]["section_type"] == "CONCEPT"

    def test_prereq_check_section_skipped(self):
        classified = [
            _classified("Concept A",   section_type="CONCEPT"),
            _classified("Be Prepared", section_type="PREREQ_CHECK"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        assert len(blueprint) == 1
        assert blueprint[0]["section_type"] == "CONCEPT"

    def test_end_matter_section_skipped(self):
        classified = [
            _classified("Concept A",           section_type="CONCEPT"),
            _classified("Writing Exercises",   section_type="END_MATTER"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        assert len(blueprint) == 1
        assert blueprint[0]["section_type"] == "CONCEPT"

    def test_full_sequence_produces_correct_blueprint_item_count(self):
        """
        Sequence: LEARNING_OBJECTIVES + CONCEPT + EXAMPLE + SOLUTION produces
        3 blueprint items — SOLUTION is merged into EXAMPLE.
        """
        classified = [
            _classified("Learning Objectives", section_type="LEARNING_OBJECTIVES"),
            _classified("Main Concept",         section_type="CONCEPT"),
            _classified("Example 1.1",          section_type="EXAMPLE"),
            _classified("Solution",             section_type="SOLUTION"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        assert len(blueprint) == 3
        types = [item["section_type"] for item in blueprint]
        assert types == ["LEARNING_OBJECTIVES", "CONCEPT", "EXAMPLE"]

    def test_solution_without_preceding_example_kept_as_independent_item(self):
        """
        When SOLUTION has no preceding EXAMPLE (e.g., follows a CONCEPT), it
        must NOT be merged — it is added as an independent blueprint item.
        """
        classified = [
            _classified("Concept A", section_type="CONCEPT"),
            _classified("Solution",  section_type="SOLUTION"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        assert len(blueprint) == 2
        assert blueprint[1]["section_type"] == "SOLUTION"

    def test_solution_with_empty_blueprint_kept_as_independent_item(self):
        """
        When SOLUTION is the very first item (blueprint is empty), it must be
        kept as an independent item rather than discarded.
        """
        classified = [
            _classified("Solution", section_type="SOLUTION"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        assert len(blueprint) == 1
        assert blueprint[0]["section_type"] == "SOLUTION"

    def test_empty_classified_list_returns_empty_blueprint(self):
        blueprint = TeachingService._build_textbook_blueprint([])
        assert blueprint == []

    def test_all_supplementary_sections_returns_empty_blueprint(self):
        """When every section is SUPPLEMENTARY, blueprint is empty (len < 2 fallback condition)."""
        classified = [
            _classified("Manipulative 1", section_type="SUPPLEMENTARY"),
            _classified("Media",          section_type="SUPPLEMENTARY"),
            _classified("Access Feature", section_type="SUPPLEMENTARY"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        assert blueprint == []

    def test_full_realistic_sequence_skips_prereq_and_produces_five_items(self):
        """
        Full realistic sequence:
          LO + CONCEPT + HOW_TO + EXAMPLE + SOLUTION + TRY_IT + TIP + PREREQ_CHECK
        Expected blueprint (5 items):
          LO, CONCEPT, HOW_TO, EXAMPLE(+solution text merged), TRY_IT(+note text merged)
          PREREQ_CHECK → skipped
        """
        classified = [
            _classified("Learning Objectives",    text="LO text",       section_type="LEARNING_OBJECTIVES"),
            _classified("Introduction",           text="Intro text",    section_type="CONCEPT"),
            _classified("HOW TO: Solve",          text="Steps text",    section_type="HOW_TO"),
            _classified("Example 3.1",            text="Ex body",       section_type="EXAMPLE"),
            _classified("Solution",               text="Sol text",      section_type="SOLUTION"),
            _classified("Try It 3.2",             text="TryIt body",    section_type="TRY_IT"),
            _classified("Tip",                    text="Tip text",      section_type="TIP"),
            _classified("Be Prepared",            text="Prereq text",   section_type="PREREQ_CHECK"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        assert len(blueprint) == 5
        types = [item["section_type"] for item in blueprint]
        assert types == ["LEARNING_OBJECTIVES", "CONCEPT", "HOW_TO", "EXAMPLE", "TRY_IT"]
        # SOLUTION merged into EXAMPLE
        assert "Sol text" in blueprint[3]["text"]
        # TIP merged into TRY_IT
        assert "Tip text" in blueprint[4]["text"]


# ─────────────────────────────────────────────────────────────────────────────
# Group 3 — _classify_section_type()
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifySectionType:
    """
    Business criterion: the math domain classifier must map concept IDs and
    titles to the correct domain type so that prompt-builder can inject
    domain-specific teaching notes.
    """

    def test_concept_id_with_multiply_returns_type_a(self):
        result = TeachingService._classify_section_type("PREALG.C1.S4.MULTIPLY", "")
        assert result == "TYPE_A"

    def test_concept_title_with_solve_equation_returns_type_b(self):
        """TYPE_B requires a space between 'solve' and 'equation' — use concept_title."""
        result = TeachingService._classify_section_type("PREALG.C2.S1", "Solve Equation Basics")
        assert result == "TYPE_B"

    def test_concept_title_with_fraction_returns_type_c(self):
        result = TeachingService._classify_section_type("PREALG.C4.S1.INTRO", "Introduction to Fractions")
        assert result == "TYPE_C"

    def test_concept_id_with_geometry_returns_type_d(self):
        result = TeachingService._classify_section_type("PREALG.C9.GEOMETRY_BASICS", "")
        assert result == "TYPE_D"

    def test_concept_id_with_expression_returns_type_e(self):
        result = TeachingService._classify_section_type("PREALG.C2.EXPRESSION_EVALUATION", "")
        assert result == "TYPE_E"

    def test_concept_id_with_percent_returns_type_f(self):
        result = TeachingService._classify_section_type("PREALG.C6.PERCENT_APPLICATIONS", "")
        assert result == "TYPE_F"

    def test_concept_id_with_exponent_returns_type_g(self):
        result = TeachingService._classify_section_type("PREALG.C10.EXPONENT_RULES", "")
        assert result == "TYPE_G"

    def test_no_match_returns_type_a_default(self):
        """When neither concept_id nor concept_title matches any domain, TYPE_A is the default."""
        result = TeachingService._classify_section_type("PREALG.C0.UNKNOWN_TOPIC", "A Completely Unknown Topic")
        assert result == "TYPE_A"

    def test_real_concept_id_multiply_whole_numbers_returns_type_a(self):
        """Real-world concept ID for 'Multiply Whole Numbers' must classify as TYPE_A."""
        result = TeachingService._classify_section_type(
            "PREALG.C1.S4.MULTIPLY_WHOLE_NUMBERS",
            "Multiply Whole Numbers",
        )
        assert result == "TYPE_A"

    @pytest.mark.parametrize("concept_id,concept_title,expected", [
        # TYPE_A — arithmetic keywords present in concept_id or title
        ("ADD_WHOLE",             "",                             "TYPE_A"),
        ("SUBTRACT_INTEGERS",     "",                             "TYPE_A"),
        ("DIVIDE_BY",             "Divide Whole Numbers",         "TYPE_A"),
        # TYPE_B — pattern requires a space: use concept_title so the space is preserved
        ("PREALG.C2.S1.EQ",      "Solve Equation Basics",        "TYPE_B"),
        ("PREALG.C3.EQ",         "Properties of Equality",       "TYPE_B"),
        # TYPE_C — fraction keywords
        ("IMPROPER_FRACTIONS",    "",                             "TYPE_C"),
        ("C4.S2",                 "Numerator and Denominator",    "TYPE_C"),
        # TYPE_D — geometry keywords
        ("C9.TRIANGLE_BASICS",    "",                             "TYPE_D"),
        ("C9.SHAPES",             "Circle Area Formula",          "TYPE_D"),
        # TYPE_E — algebra language keywords
        ("PREALG.C2.INTRO",      "Language of Algebra",          "TYPE_E"),
        ("PREALG.C2.S2",         "Variable Expressions",         "TYPE_E"),
        # TYPE_F — ratio/percent keywords
        ("RATIO_PROBLEMS",        "",                             "TYPE_F"),
        ("C5.DISCOUNT",           "Discount and Commission",      "TYPE_F"),
        # TYPE_G — exponent/polynomial keywords
        ("MONOMIAL_OPERATIONS",   "",                             "TYPE_G"),
        ("C10.POLY",              "Polynomial Factoring",         "TYPE_G"),
    ])
    def test_domain_patterns_parametrized(self, concept_id: str, concept_title: str, expected: str):
        """Parametrized coverage of all TYPE_A–G domain keywords."""
        result = TeachingService._classify_section_type(concept_id, concept_title)
        assert result == expected, (
            f"Expected {expected} for concept_id='{concept_id}', "
            f"concept_title='{concept_title}', got {result}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Group 4 — CardMCQ.difficulty field
# ─────────────────────────────────────────────────────────────────────────────

class TestCardMCQDifficultyField:
    """
    Business criterion: MCQ cards carry an explicit difficulty level so that
    adaptive algorithms can select appropriately challenging questions.
    """

    def test_default_difficulty_is_medium(self):
        mcq = CardMCQ(
            text="What is 2+2?",
            options=["1", "2", "4", "8"],
            correct_index=2,
        )
        assert mcq.difficulty == "MEDIUM"

    def test_explicit_easy_difficulty_accepted(self):
        mcq = CardMCQ(
            text="What is 1+1?",
            options=["1", "2", "3", "4"],
            correct_index=1,
            difficulty="EASY",
        )
        assert mcq.difficulty == "EASY"

    def test_explicit_hard_difficulty_accepted(self):
        mcq = CardMCQ(
            text="What is the derivative?",
            options=["2x", "x²", "2", "x"],
            correct_index=0,
            difficulty="HARD",
        )
        assert mcq.difficulty == "HARD"

    def test_backward_compat_dict_without_difficulty_parses_with_default(self):
        """
        A legacy MCQ dict produced before the difficulty field was introduced
        must still parse correctly — difficulty must default to 'MEDIUM'.
        """
        legacy_dict = {
            "text": "What is 3×3?",
            "options": ["6", "9", "12", "8"],
            "correct_index": 1,
            "explanation": "Three times three equals nine.",
            # No 'difficulty' key present — must not raise a validation error
        }
        mcq = CardMCQ(**legacy_dict)
        assert mcq.difficulty == "MEDIUM"


# ─────────────────────────────────────────────────────────────────────────────
# Group 5 — Blueprint fallback condition
# ─────────────────────────────────────────────────────────────────────────────

class TestBlueprintFallbackCondition:
    """
    Business criterion: when the blueprint pipeline cannot extract at least
    2 usable items from the textbook structure (e.g., all sections are
    SUPPLEMENTARY scaffolding), the system must detect this and fall back to
    the topic-grouping strategy so learners always receive a complete lesson.
    """

    def test_all_supplementary_input_produces_blueprint_with_fewer_than_two_items(self):
        """
        A list of entirely SUPPLEMENTARY sections must produce a blueprint with
        len < 2, confirming that the downstream fallback condition
        `if len(blueprint) < 2` would evaluate to True and trigger
        `_group_by_major_topic()`.
        """
        # Arrange — four sections that are all scaffolding, none instructional
        classified = [
            _classified("Manipulative Activity", section_type="SUPPLEMENTARY"),
            _classified("Media",                 section_type="SUPPLEMENTARY"),
            _classified("Access",                section_type="SUPPLEMENTARY"),
            _classified("Be Prepared",           section_type="PREREQ_CHECK"),
        ]
        # Act
        blueprint = TeachingService._build_textbook_blueprint(classified)
        # Assert
        assert len(blueprint) < 2, (
            f"Expected blueprint length < 2 to trigger fallback, got {len(blueprint)}"
        )

    def test_single_supplementary_and_one_prereq_check_produces_empty_blueprint(self):
        """
        All skipped section types produce an empty blueprint — len 0 < 2 confirms
        the fallback condition is met.
        """
        classified = [
            _classified("Writing Exercises", section_type="END_MATTER"),
            _classified("Be Prepared",       section_type="PREREQ_CHECK"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        assert len(blueprint) == 0

    def test_one_instructional_section_produces_blueprint_length_one_triggering_fallback(self):
        """
        A single instructional section (e.g., one CONCEPT plus all skipped types)
        produces a blueprint of length 1, which is still < 2 and triggers fallback.
        """
        classified = [
            _classified("Main Concept",    section_type="CONCEPT"),
            _classified("Be Prepared",     section_type="PREREQ_CHECK"),
            _classified("Media",           section_type="SUPPLEMENTARY"),
        ]
        blueprint = TeachingService._build_textbook_blueprint(classified)
        assert len(blueprint) == 1
        assert len(blueprint) < 2
