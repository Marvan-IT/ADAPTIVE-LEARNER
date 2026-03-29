"""
Unit tests for _get_chunk_type() classification logic.

Business criteria:
- Teaching chunks (no suffix, no section pattern) → "teaching"
- Exercise gate headings ("SECTION X.X EXERCISES" or "Practice Makes Perfect (Exercises)") → "exercise_gate"
- Exam source chunks (e.g. "Identify Whole Numbers (Exercises)") → "exam_question_source"
- Practice-only chunks ("Everyday Math (Exercises)", "Writing Exercises (Exercises)") → "practice"
- Classification is case-insensitive for the SECTION X.X EXERCISES pattern

Note: _get_chunk_type is a pure function (no DB/FastAPI deps) duplicated here
to avoid triggering FastAPI route validation at teaching_router import time.
"""
import re
import pytest


def _get_chunk_type(heading: str) -> str:
    """Classify a chunk by its heading (mirrors teaching_router._get_chunk_type)."""
    h = heading.lower()
    if re.match(r"^section\s+\d+\.\d+", h):
        return "exercise_gate"
    if "(exercises)" not in h:
        return "teaching"
    if "everyday math" in h or "writing exercises" in h:
        return "practice"
    if "practice makes perfect" in h:
        return "exercise_gate"
    return "exam_question_source"


# ── Teaching chunks (no "(Exercises)" suffix, no SECTION X.X pattern) ─────────

def test_plain_topic_heading_is_teaching():
    assert _get_chunk_type("Identify Whole Numbers") == "teaching"


def test_learning_objectives_is_teaching():
    assert _get_chunk_type("Learning Objectives") == "teaching"


def test_model_whole_numbers_is_teaching():
    assert _get_chunk_type("Model Whole Numbers") == "teaching"


# ── Exam question source chunks ────────────────────────────────────────────────

def test_identify_with_exercises_suffix_is_exam_question_source():
    assert _get_chunk_type("Identify Whole Numbers (Exercises)") == "exam_question_source"


def test_model_with_exercises_suffix_is_exam_question_source():
    assert _get_chunk_type("Model Whole Numbers (Exercises)") == "exam_question_source"


# ── Exercise gate chunks ───────────────────────────────────────────────────────

def test_practice_makes_perfect_exercises_is_exercise_gate():
    """Practice Makes Perfect is the PM container — an exercise gate, not a source."""
    assert _get_chunk_type("Practice Makes Perfect (Exercises)") == "exercise_gate"


def test_section_exercises_uppercase_is_exercise_gate():
    assert _get_chunk_type("SECTION 1.1 EXERCISES") == "exercise_gate"


def test_section_exercises_different_number_is_exercise_gate():
    assert _get_chunk_type("SECTION 3.2 EXERCISES") == "exercise_gate"


def test_section_exercises_lowercase_is_exercise_gate():
    """SECTION X.X EXERCISES check must be case-insensitive."""
    assert _get_chunk_type("section 1.1 exercises") == "exercise_gate"


# ── Practice-only chunks ───────────────────────────────────────────────────────

def test_everyday_math_exercises_is_practice():
    assert _get_chunk_type("Everyday Math (Exercises)") == "practice"


def test_writing_exercises_exercises_is_practice():
    assert _get_chunk_type("Writing Exercises (Exercises)") == "practice"
