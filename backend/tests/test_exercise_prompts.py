"""
Unit tests for exercise prompt functions:
  - build_exercise_card_system_prompt()  (api/prompts.py)
  - build_exercise_recovery_prompt()     (api/prompts.py)
  - build_exercise_card_prompt()         (adaptive/prompt_builder.py)

Business criteria:
  BC-EP-01  build_exercise_card_system_prompt() always includes JSON output format
            instructions ("JSON" + "cards") so the LLM returns parseable card data.
  BC-EP-02  For non-English languages the system prompt contains the language name
            so the LLM generates cards in the student's preferred language.
  BC-EP-03  build_exercise_recovery_prompt() embeds the exact failed question text
            so the walkthrough addresses the student's specific problem.
  BC-EP-04  build_exercise_recovery_prompt() embeds the student's wrong answer so
            the walkthrough can point out what went wrong.
  BC-EP-05  build_exercise_recovery_prompt() instructs card_type "INFO" to signal
            the frontend to render it as a read-only explanation card (no MCQ).
  BC-EP-06  build_exercise_card_prompt() truncates chunk text longer than 3000 chars
            to prevent token-limit failures on large exercise blocks.
  BC-EP-07  build_exercise_card_prompt() returns a dict with "system" and "user" keys
            as expected by generate_per_card() caller code.

Test strategy:
  Pure unit tests.  No DB, no HTTP, no async.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from api.prompts import build_exercise_card_system_prompt, build_exercise_recovery_prompt
from adaptive.prompt_builder import build_exercise_card_prompt


# ═══════════════════════════════════════════════════════════════════════════════
# BC-EP-01  System prompt contains JSON format instruction
# ═══════════════════════════════════════════════════════════════════════════════

class TestExerciseCardSystemPromptJsonFormat:
    """
    BC-EP-01: The system prompt must contain both "JSON" and "cards" so that the
    LLM knows it must return a JSON object with a "cards" array.  Without this
    instruction the LLM may respond in prose and cause a parse failure.
    """

    def test_system_prompt_contains_json_keyword(self):
        """
        Business criterion: LLM instructed to output JSON (not prose).
        """
        prompt = build_exercise_card_system_prompt("en")
        assert "JSON" in prompt, "System prompt must contain 'JSON' output instruction"

    def test_system_prompt_contains_cards_keyword(self):
        """
        Business criterion: LLM instructed that output structure has a 'cards' key.
        """
        prompt = build_exercise_card_system_prompt("en")
        assert "cards" in prompt, "System prompt must reference 'cards' array key"

    def test_system_prompt_is_non_empty_string(self):
        """
        Business criterion: Prompt must not be blank — a blank prompt causes the
        LLM to produce unguided output.
        """
        prompt = build_exercise_card_system_prompt("en")
        assert isinstance(prompt, str)
        assert len(prompt.strip()) > 50


# ═══════════════════════════════════════════════════════════════════════════════
# BC-EP-02  Non-English language name injected into system prompt
# ═══════════════════════════════════════════════════════════════════════════════

class TestExerciseCardSystemPromptLanguage:
    """
    BC-EP-02: For non-English students the system prompt must contain the language
    name so the LLM generates exercise cards in the student's preferred language.
    English prompts must NOT contain an unnecessary language instruction.
    """

    def test_spanish_prompt_contains_spanish_language_name(self):
        """
        Business criterion: Spanish students receive exercise cards in Spanish.
        """
        prompt = build_exercise_card_system_prompt("es")
        assert "Spanish" in prompt, "Prompt for 'es' must name 'Spanish'"

    def test_french_prompt_contains_french_language_name(self):
        """
        Business criterion: French students receive exercise cards in French.
        """
        prompt = build_exercise_card_system_prompt("fr")
        assert "French" in prompt

    def test_arabic_prompt_contains_arabic_language_name(self):
        """
        Business criterion: Arabic students receive exercise cards in Arabic.
        """
        prompt = build_exercise_card_system_prompt("ar")
        assert "Arabic" in prompt

    def test_english_prompt_has_no_language_instruction(self):
        """
        Business criterion: English is the default — no extra language instruction
        needed (reduces prompt noise).
        """
        prompt = build_exercise_card_system_prompt("en")
        # _language_instruction returns "" for English — no LANGUAGE REQUIREMENT block
        assert "LANGUAGE REQUIREMENT" not in prompt

    def test_tamil_prompt_contains_tamil_language_name(self):
        """
        Business criterion: Tamil (one of the 13 supported languages) works correctly.
        """
        prompt = build_exercise_card_system_prompt("ta")
        assert "Tamil" in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# BC-EP-03  Recovery prompt contains the failed question
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecoveryPromptContainsFailedQuestion:
    """
    BC-EP-03: The recovery prompt must embed the exact question text the student
    failed so the LLM builds a walkthrough for that specific problem (not a generic
    explanation).
    """

    def test_recovery_prompt_contains_failed_question_text(self):
        """
        Business criterion: Walkthrough addresses the student's specific problem.
        """
        question = "What is 3/4 + 1/4?"
        prompt = build_exercise_recovery_prompt(question, "1/8", "en")
        assert question in prompt, "Recovery prompt must embed the failed question verbatim"

    def test_recovery_prompt_with_long_question(self):
        """
        Business criterion: Long questions are still embedded completely.
        """
        question = "Simplify the expression: 2(3x + 4) - 5(x - 1) + 7"
        prompt = build_exercise_recovery_prompt(question, "x + 7", "en")
        assert question in prompt

    def test_recovery_prompt_is_non_empty_string(self):
        """
        Business criterion: Prompt must be a non-blank string.
        """
        prompt = build_exercise_recovery_prompt("What is 2+2?", "3", "en")
        assert isinstance(prompt, str)
        assert len(prompt.strip()) > 50


# ═══════════════════════════════════════════════════════════════════════════════
# BC-EP-04  Recovery prompt contains the student's wrong answer
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecoveryPromptContainsWrongAnswer:
    """
    BC-EP-04: The recovery prompt must include the student's wrong answer so the
    LLM can explain why that specific answer is incorrect, making the walkthrough
    more targeted and educational.
    """

    def test_recovery_prompt_contains_wrong_answer_text(self):
        """
        Business criterion: Walkthrough references the student's wrong answer.
        """
        wrong_answer = "1/8"
        prompt = build_exercise_recovery_prompt("What is 3/4 + 1/4?", wrong_answer, "en")
        assert wrong_answer in prompt, "Recovery prompt must embed the student's wrong answer"

    def test_recovery_prompt_different_wrong_answer(self):
        """
        Business criterion: Different wrong answers produce different prompts.
        """
        prompt1 = build_exercise_recovery_prompt("What is 2+2?", "3", "en")
        prompt2 = build_exercise_recovery_prompt("What is 2+2?", "5", "en")
        # Both contain the question; they differ by wrong answer
        assert "3" in prompt1
        assert "5" in prompt2
        assert prompt1 != prompt2


# ═══════════════════════════════════════════════════════════════════════════════
# BC-EP-05  Recovery prompt instructs card_type INFO
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecoveryPromptCardTypeInfo:
    """
    BC-EP-05: The recovery prompt must instruct the LLM to return card_type="INFO"
    so the frontend renders it as a read-only explanation card without an MCQ panel.
    Returning card_type="MCQ" would confuse the frontend into showing an unanswerable
    question.
    """

    def test_recovery_prompt_contains_info_card_type(self):
        """
        Business criterion: Recovery prompt requests an INFO card (no question).
        """
        prompt = build_exercise_recovery_prompt("What is 2+2?", "3", "en")
        assert "INFO" in prompt, "Recovery prompt must specify card_type='INFO'"

    def test_recovery_prompt_does_not_request_mcq(self):
        """
        Business criterion: Recovery cards must NOT be MCQ — they are explanations.
        The LLM is not instructed to include options/correct_answer as a quiz.
        """
        prompt = build_exercise_recovery_prompt("What is 2+2?", "3", "en")
        # The JSON format block shows options: [] (empty) and correct_answer: null
        # We just confirm "MCQ" is not used as the card_type instruction
        assert '"card_type": "MCQ"' not in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# BC-EP-06  build_exercise_card_prompt() truncates long text
# ═══════════════════════════════════════════════════════════════════════════════

class TestExerciseCardPromptTruncatesLongText:
    """
    BC-EP-06: Exercise chunks can be very long (hundreds of numbered problems).
    Text longer than 3000 characters must be truncated with "..." so the LLM
    call stays within token limits and avoids 413 / context-length errors.
    """

    def test_text_over_3000_chars_is_truncated(self):
        """
        Business criterion: Chunk text > 3000 chars is truncated to prevent token
        limit failures.
        """
        long_text = "x" * 4000
        chunk = {"heading": "Practice Makes Perfect", "text": long_text}
        result = build_exercise_card_prompt(chunk, {}, "en")
        # The user message must contain the truncated text with ellipsis
        assert "..." in result["user"], "Truncated text must end with '...'"
        assert len(result["user"]) < 4500, "User message must be shorter than raw 4000-char input"

    def test_text_under_3000_chars_is_not_truncated(self):
        """
        Business criterion: Short chunk text must not be needlessly truncated.
        """
        short_text = "Problem 1: What is 2 + 2?\nProblem 2: What is 3 + 3?"
        chunk = {"heading": "Practice Makes Perfect", "text": short_text}
        result = build_exercise_card_prompt(chunk, {}, "en")
        assert short_text in result["user"], "Short text must appear verbatim in user message"

    def test_exactly_3000_chars_not_truncated(self):
        """
        Business criterion: Text of exactly 3000 chars is at the boundary and
        must NOT be truncated (truncation is strictly > 3000).
        """
        exact_text = "y" * 3000
        chunk = {"heading": "Everyday Math", "text": exact_text}
        result = build_exercise_card_prompt(chunk, {}, "en")
        # No ellipsis appended
        assert "..." not in result["user"]


# ═══════════════════════════════════════════════════════════════════════════════
# BC-EP-07  build_exercise_card_prompt() returns dict with system + user keys
# ═══════════════════════════════════════════════════════════════════════════════

class TestExerciseCardPromptReturnsDictWithSystemAndUser:
    """
    BC-EP-07: build_exercise_card_prompt() must return a dict with exactly
    "system" and "user" keys.  The caller (generate_per_card) destructures this
    dict directly — a missing key causes a KeyError crash.
    """

    def test_returns_dict_type(self):
        """
        Business criterion: Return type is dict (not tuple, not string).
        """
        chunk = {"heading": "Practice Makes Perfect", "text": "Problem 1: 2+2=?"}
        result = build_exercise_card_prompt(chunk, {}, "en")
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_has_system_key(self):
        """
        Business criterion: 'system' key must be present for the LLM system role.
        """
        chunk = {"heading": "Practice Makes Perfect", "text": "Problem 1: 2+2=?"}
        result = build_exercise_card_prompt(chunk, {}, "en")
        assert "system" in result, "'system' key missing from exercise card prompt dict"

    def test_has_user_key(self):
        """
        Business criterion: 'user' key must be present for the LLM user message.
        """
        chunk = {"heading": "Practice Makes Perfect", "text": "Problem 1: 2+2=?"}
        result = build_exercise_card_prompt(chunk, {}, "en")
        assert "user" in result, "'user' key missing from exercise card prompt dict"

    def test_system_value_is_non_empty_string(self):
        """
        Business criterion: System prompt must not be blank.
        """
        chunk = {"heading": "Everyday Math", "text": "Problem 1: 3+3=?"}
        result = build_exercise_card_prompt(chunk, {}, "en")
        assert isinstance(result["system"], str)
        assert len(result["system"].strip()) > 0

    def test_user_value_contains_chunk_heading(self):
        """
        Business criterion: The user message must include the chunk heading so the
        LLM knows which exercise section it is processing.
        """
        chunk = {"heading": "Everyday Math", "text": "Problem 1: 3+3=?"}
        result = build_exercise_card_prompt(chunk, {}, "en")
        assert "Everyday Math" in result["user"], "User message must include chunk heading"

    def test_missing_heading_uses_default(self):
        """
        Business criterion: Chunks with no 'heading' key must not raise KeyError —
        a safe default must be used.
        """
        chunk = {"text": "Problem 1: 2+2=?"}  # no heading
        result = build_exercise_card_prompt(chunk, {}, "en")
        assert isinstance(result, dict)
        assert "system" in result
        assert "user" in result

    def test_missing_text_uses_empty_string(self):
        """
        Business criterion: Chunks with no 'text' key must not raise KeyError.
        """
        chunk = {"heading": "Practice Makes Perfect"}  # no text
        result = build_exercise_card_prompt(chunk, {}, "en")
        assert isinstance(result, dict)
        assert "user" in result
