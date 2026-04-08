"""
Unit tests for all_study_complete logic in teaching_router.py.

Business criteria:
  BC-ASC-01  all_study_complete requires ALL teaching chunks AND all non-optional
             exercise chunks to be in chunk_progress — Writing Exercises are excluded.
  BC-ASC-02  Writing Exercises are NOT required — completing everything except Writing
             Exercises is sufficient for all_study_complete=True.
  BC-ASC-03  Non-optional exercise chunks (Practice Makes Perfect, Everyday Math) ARE
             required — leaving any of them incomplete means all_study_complete=False.
  BC-ASC-04  When the concept has no teaching or required-exercise chunks (e.g. only
             learning_objective chunks) required_ids is empty and all_study_complete=False.
  BC-ASC-05  When all required chunks are completed all_study_complete=True, which signals
             the frontend to unlock the exam gate.
  BC-ASC-06  section_review chunks are required — they gate the exam just like teaching
             chunks but are NOT sampled for exam questions.

Test strategy:
  The all_study_complete logic is a pure computation on two sets:
    required_ids = {chunks that are teaching OR section_review
                    OR (exercise AND NOT optional)}
    completed_ids = set(chunk_progress.keys())
    all_study_complete = bool(required_ids) and required_ids.issubset(completed_ids)

  We replicate this logic here with the real _get_chunk_type / _heading_is_optional
  functions to confirm each business rule.  No DB or HTTP needed.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ── Break circular import ─────────────────────────────────────────────────────

def _install_api_main_stub():
    if "api.main" not in sys.modules:
        stub = MagicMock()
        try:
            from slowapi import Limiter
            from slowapi.util import get_remote_address
            stub.limiter = Limiter(key_func=get_remote_address)
        except ImportError:
            stub.limiter = MagicMock()
        sys.modules["api.main"] = stub


_install_api_main_stub()


def _stub_heavyweight_modules():
    """Stub modules with import-time issues before importing teaching_router."""
    import sys as _sys
    if "db.connection" not in _sys.modules:
        stub_conn = MagicMock()
        stub_conn.get_db = MagicMock()
        _sys.modules["db.connection"] = stub_conn
    # db.models must NOT be stubbed — real SQLAlchemy classes required


_stub_heavyweight_modules()

from api.teaching_router import _get_chunk_type, _heading_is_optional  # noqa: E402


# ── Pure logic replica ────────────────────────────────────────────────────────

def _compute_all_study_complete(chunks: list[dict], completed_ids: set[str]) -> bool:
    """
    Mirrors the all_study_complete computation in complete_chunk().

    chunks: list of dicts with keys "id" (str) and "heading" (str).
    completed_ids: set of chunk id strings already in chunk_progress.
    """
    required_ids = {
        c["id"] for c in chunks
        if _get_chunk_type(c.get("heading", "")) in ("teaching", "section_review")
        or (
            _get_chunk_type(c.get("heading", "")) == "exercise"
            and not _heading_is_optional(c.get("heading", ""))
        )
    }
    return bool(required_ids) and required_ids.issubset(completed_ids)


# ── Chunk factory ─────────────────────────────────────────────────────────────

def _chunk(chunk_id: str, heading: str) -> dict:
    return {"id": chunk_id, "heading": heading}


# ═══════════════════════════════════════════════════════════════════════════════
# BC-ASC-01  Teaching chunks are required
# ═══════════════════════════════════════════════════════════════════════════════

class TestRequiresTeachingChunks:
    """
    BC-ASC-01: Teaching chunks are always required.  Completing only Learning
    Objectives is not sufficient — the student must finish the teaching content.
    """

    def test_teaching_chunk_not_completed_means_not_done(self):
        """
        Business criterion: all_study_complete=False when a teaching chunk is missing
        from chunk_progress.
        """
        chunks = [
            _chunk("c1", "Learning Objectives"),
            _chunk("c2", "Use Addition Notation"),   # teaching — required
        ]
        completed = {"c1"}  # only learning objective done
        assert _compute_all_study_complete(chunks, completed) is False

    def test_all_teaching_chunks_completed_means_done(self):
        """
        Business criterion: all_study_complete=True when all teaching chunks are in
        chunk_progress (no exercise chunks in this concept).
        """
        chunks = [
            _chunk("c1", "Learning Objectives"),
            _chunk("c2", "Use Addition Notation"),
            _chunk("c3", "Add Whole Numbers"),
        ]
        completed = {"c2", "c3"}  # all teaching chunks done (c1 is learning_objective → not required)
        assert _compute_all_study_complete(chunks, completed) is True

    def test_partial_teaching_completion_is_not_done(self):
        """
        Business criterion: Completing only some teaching chunks is insufficient.
        """
        chunks = [
            _chunk("c1", "Use Addition Notation"),
            _chunk("c2", "Add Whole Numbers"),
            _chunk("c3", "Subtract Whole Numbers"),
        ]
        completed = {"c1", "c2"}  # c3 missing
        assert _compute_all_study_complete(chunks, completed) is False


# ═══════════════════════════════════════════════════════════════════════════════
# BC-ASC-02  Writing Exercises NOT required
# ═══════════════════════════════════════════════════════════════════════════════

class TestWritingExercisesNotRequired:
    """
    BC-ASC-02: Writing Exercises are the only exercise type that does not gate
    the exam.  Even if Writing Exercises are incomplete, all_study_complete can
    be True as long as all teaching and other required exercise chunks are done.
    """

    def test_writing_exercises_incomplete_still_allows_completion(self):
        """
        Business criterion: Writing Exercises incomplete → all_study_complete can still be True.
        """
        chunks = [
            _chunk("c1", "Use Addition Notation"),    # teaching — required
            _chunk("c2", "Practice Makes Perfect"),   # exercise, not optional — required
            _chunk("c3", "Writing Exercises"),         # optional — NOT required
        ]
        completed = {"c1", "c2"}  # Writing Exercises NOT done
        assert _compute_all_study_complete(chunks, completed) is True

    def test_writing_exercise_singular_also_not_required(self):
        """
        Business criterion: Singular 'Writing Exercise' is also optional.
        """
        chunks = [
            _chunk("c1", "Use Addition Notation"),
            _chunk("c2", "Writing Exercise"),  # singular — still optional
        ]
        completed = {"c1"}  # Writing Exercise NOT done
        assert _compute_all_study_complete(chunks, completed) is True

    def test_writing_exercises_uppercase_not_required(self):
        """
        Business criterion: Case-insensitive optional detection — WRITING EXERCISES is optional.
        """
        chunks = [
            _chunk("c1", "Use Addition Notation"),
            _chunk("c2", "WRITING EXERCISES"),
        ]
        completed = {"c1"}
        assert _compute_all_study_complete(chunks, completed) is True


# ═══════════════════════════════════════════════════════════════════════════════
# BC-ASC-03  Non-optional exercise chunks ARE required
# ═══════════════════════════════════════════════════════════════════════════════

class TestNonOptionalExerciseChunksRequired:
    """
    BC-ASC-03: Practice Makes Perfect and Everyday Math are required exercise
    chunks.  Leaving them incomplete means all_study_complete=False even if all
    teaching chunks are done.
    """

    def test_practice_makes_perfect_incomplete_blocks_completion(self):
        """
        Business criterion: Practice Makes Perfect is a required exercise.
        """
        chunks = [
            _chunk("c1", "Use Addition Notation"),
            _chunk("c2", "Practice Makes Perfect"),
        ]
        completed = {"c1"}  # Practice Makes Perfect NOT done
        assert _compute_all_study_complete(chunks, completed) is False

    def test_everyday_math_incomplete_blocks_completion(self):
        """
        Business criterion: Everyday Math is a required exercise.
        """
        chunks = [
            _chunk("c1", "Use Addition Notation"),
            _chunk("c2", "Everyday Math"),
        ]
        completed = {"c1"}  # Everyday Math NOT done
        assert _compute_all_study_complete(chunks, completed) is False

    def test_review_exercises_incomplete_blocks_completion(self):
        """
        Business criterion: Review Exercises (non-optional) blocks completion.
        """
        chunks = [
            _chunk("c1", "Add Whole Numbers"),
            _chunk("c2", "Review Exercises"),
        ]
        completed = {"c1"}
        assert _compute_all_study_complete(chunks, completed) is False

    def test_all_required_including_practice_makes_perfect_done(self):
        """
        Business criterion: Teaching + Practice Makes Perfect all done → complete.
        """
        chunks = [
            _chunk("c1", "Use Addition Notation"),
            _chunk("c2", "Practice Makes Perfect"),
        ]
        completed = {"c1", "c2"}
        assert _compute_all_study_complete(chunks, completed) is True


# ═══════════════════════════════════════════════════════════════════════════════
# BC-ASC-04  Empty required_ids → all_study_complete=False
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmptyConceptNoStudyComplete:
    """
    BC-ASC-04: When the concept has no teaching or required-exercise chunks,
    required_ids is empty and all_study_complete must be False.  This prevents
    a student from trivially passing a concept with no real content.
    """

    def test_no_chunks_means_not_complete(self):
        """
        Business criterion: Concept with no chunks → all_study_complete=False.
        """
        assert _compute_all_study_complete([], set()) is False

    def test_only_learning_objective_chunks_not_complete(self):
        """
        Business criterion: Concepts with only Learning Objectives have no required
        chunks → all_study_complete=False even when all are 'completed'.
        """
        chunks = [
            _chunk("c1", "Learning Objectives"),
            _chunk("c2", "Be Prepared for Chapter 1"),
        ]
        completed = {"c1", "c2"}  # all done, but none are required
        assert _compute_all_study_complete(chunks, completed) is False

    def test_numeric_prefix_section_intro_counts_as_section_review(self):
        """
        BC-CT-02 / BC-ASC-06: '1.1 Introduction to Whole Numbers' is classified as
        section_review (not teaching). section_review chunks are required, so completing
        the only chunk satisfies required_ids → all_study_complete=True.
        """
        chunks = [
            _chunk("c1", "1.1 Introduction to Whole Numbers"),
        ]
        completed = {"c1"}
        assert _compute_all_study_complete(chunks, completed) is True


# ═══════════════════════════════════════════════════════════════════════════════
# BC-ASC-05  All required done → all_study_complete=True
# ═══════════════════════════════════════════════════════════════════════════════

class TestAllRequiredDone:
    """
    BC-ASC-05: When all teaching + non-optional exercise chunks are in
    chunk_progress, all_study_complete=True and the exam gate is unlocked.
    """

    def test_typical_concept_fully_completed(self):
        """
        Business criterion: A typical concept with teaching + exercises fully
        completed → all_study_complete=True.
        """
        chunks = [
            _chunk("c0", "Learning Objectives"),       # not required
            _chunk("c1", "Use Addition Notation"),     # teaching — required
            _chunk("c2", "Add Whole Numbers"),          # teaching — required
            _chunk("c3", "Practice Makes Perfect"),    # exercise, non-optional — required
            _chunk("c4", "Everyday Math"),              # exercise, non-optional — required
            _chunk("c5", "Writing Exercises"),          # optional — NOT required
        ]
        # All required completed; Writing Exercises intentionally absent
        completed = {"c1", "c2", "c3", "c4"}
        assert _compute_all_study_complete(chunks, completed) is True

    def test_extra_completed_chunks_do_not_break_logic(self):
        """
        Business criterion: Having more IDs in chunk_progress than required (e.g.
        Writing Exercises completed voluntarily) must still yield True.
        """
        chunks = [
            _chunk("c1", "Use Addition Notation"),
            _chunk("c2", "Writing Exercises"),
        ]
        completed = {"c1", "c2"}  # everything done, including optional
        assert _compute_all_study_complete(chunks, completed) is True


# ═══════════════════════════════════════════════════════════════════════════════
# BC-ASC-06  section_review chunks are required (gate the exam like teaching)
# ═══════════════════════════════════════════════════════════════════════════════

class TestChapterReviewRequired:
    """BC-ASC-06: section_review chunks are required — they gate the exam just like teaching chunks."""

    def test_section_review_incomplete_blocks_exam(self):
        """Incomplete section_review chunk means study not complete."""
        chunks = [_chunk("c1", "1.1 Introduction to Whole Numbers")]
        completed = set()
        assert _compute_all_study_complete(chunks, completed) is False

    def test_section_review_completed_allows_completion(self):
        """Completing the only section_review chunk satisfies required_ids."""
        chunks = [_chunk("c1", "1.1 Introduction to Whole Numbers")]
        completed = {"c1"}
        assert _compute_all_study_complete(chunks, completed) is True

    def test_section_review_and_teaching_both_required(self):
        """Both teaching and section_review must be completed."""
        chunks = [
            _chunk("c1", "Use Addition Notation"),
            _chunk("c2", "1.1 Introduction to Whole Numbers"),
        ]
        assert _compute_all_study_complete(chunks, {"c1"}) is False
        assert _compute_all_study_complete(chunks, {"c1", "c2"}) is True
