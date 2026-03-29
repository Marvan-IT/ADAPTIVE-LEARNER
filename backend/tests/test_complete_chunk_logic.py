"""
Unit tests for score calculation and score-to-mode mapping.

Business criteria:
- MCQ score is computed as round((correct / total) * 100), 0 when total=0
- Scores correctly classify into STRUGGLING / NORMAL / FAST modes
- Division-by-zero is guarded (no cards seen yet → score 0)
- Rounding matches expected percentage values for common correct/total pairs

These tests require no database, no HTTP calls, and no external services.

Import strategy:
  Same stub pattern as test_chunk_mode.py — pre-inject MagicMock stubs for
  heavyweight modules before importing teaching_service.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Ensure backend/src is on the path first
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── Stub heavyweight modules before any teaching_service import ────────────────

def _stub_modules():
    if "db.connection" not in sys.modules:
        stub_conn = MagicMock()
        stub_conn.get_db = MagicMock()
        sys.modules["db.connection"] = stub_conn

    if "db.models" not in sys.modules:
        sys.modules["db.models"] = MagicMock()

    if "api.teaching_schemas" not in sys.modules:
        sys.modules["api.teaching_schemas"] = MagicMock()

    if "api.chunk_knowledge_service" not in sys.modules:
        sys.modules["api.chunk_knowledge_service"] = MagicMock()

    if "api.prompts" not in sys.modules:
        sys.modules["api.prompts"] = MagicMock()


_stub_modules()

import pytest
from api.teaching_service import _mode_from_chunk_score


# ── Local score formula (mirrors the intended computation) ────────────────────

def compute_score(correct: int, total: int) -> int:
    """Compute MCQ score as a 0–100 integer, guarding against division by zero."""
    return round((correct / total) * 100) if total > 0 else 0


# ── Score calculation tests ────────────────────────────────────────────────────

def test_compute_score_zero_correct():
    """0/5 correct → score 0."""
    assert compute_score(0, 5) == 0


def test_compute_score_three_of_five():
    """3/5 correct → score 60."""
    assert compute_score(3, 5) == 60


def test_compute_score_four_of_five():
    """4/5 correct → score 80."""
    assert compute_score(4, 5) == 80


def test_compute_score_five_of_five():
    """5/5 correct → score 100."""
    assert compute_score(5, 5) == 100


def test_compute_score_zero_total_returns_zero():
    """When no cards have been seen yet, score must be 0 (no ZeroDivisionError)."""
    assert compute_score(0, 0) == 0


# ── Score → mode integration tests ────────────────────────────────────────────

def test_score_from_two_of_five_maps_to_struggling():
    """2/5 = 40% → score 40 → STRUGGLING mode."""
    score = compute_score(2, 5)
    assert score == 40
    assert _mode_from_chunk_score(score) == "STRUGGLING"


def test_score_from_three_of_five_maps_to_normal():
    """3/5 = 60% → score 60 → NORMAL mode."""
    score = compute_score(3, 5)
    assert score == 60
    assert _mode_from_chunk_score(score) == "NORMAL"


def test_score_from_four_of_five_maps_to_fast():
    """4/5 = 80% → score 80 → FAST mode."""
    score = compute_score(4, 5)
    assert score == 80
    assert _mode_from_chunk_score(score) == "FAST"


# ── Rounding edge-cases ────────────────────────────────────────────────────────

def test_compute_score_rounds_down():
    """1/3 = 33.33...% must round to 33."""
    assert compute_score(1, 3) == 33


def test_compute_score_rounds_up():
    """2/3 = 66.666...% must round to 67."""
    assert compute_score(2, 3) == 67


# ── Zero-total guard consistency ──────────────────────────────────────────────

def test_zero_total_maps_to_struggling_mode():
    """When no MCQs have been answered, the resulting score (0) maps to STRUGGLING."""
    score = compute_score(0, 0)
    assert _mode_from_chunk_score(score) == "STRUGGLING"
