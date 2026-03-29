"""
Unit tests for _mode_from_chunk_score() in teaching_service.py.

Business criteria:
- Scores below 50 map to STRUGGLING mode (student needs extra support)
- Scores 50–79 map to NORMAL mode (standard pacing)
- Scores 80+ map to FAST mode (student is excelling, can advance quickly)
- Boundary values (0, 49, 50, 79, 80, 100) are classified correctly

Import strategy:
  teaching_service imports db.models, db.connection (via sqlalchemy),
  and openai at module level. We pre-inject MagicMock stubs for the
  heavyweight modules before importing teaching_service, following the
  pattern established in test_per_card_adaptive.py.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

# Ensure backend/src is on the path first
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── Stub heavyweight modules before any teaching_service import ────────────────

def _stub_modules():
    """Inject stubs so teaching_service's module-level imports succeed
    without a live database, OpenAI key, or ChromaDB instance."""

    # db.connection is imported transitively and runs create_async_engine at module level
    if "db.connection" not in sys.modules:
        stub_conn = MagicMock()
        stub_conn.get_db = MagicMock()
        sys.modules["db.connection"] = stub_conn

    # db.models: imported for ORM model class references only
    if "db.models" not in sys.modules:
        sys.modules["db.models"] = MagicMock()

    # api.teaching_schemas: imported for Pydantic model classes; MagicMock is safe
    if "api.teaching_schemas" not in sys.modules:
        sys.modules["api.teaching_schemas"] = MagicMock()

    # api.chunk_knowledge_service: imported at top of teaching_service
    if "api.chunk_knowledge_service" not in sys.modules:
        sys.modules["api.chunk_knowledge_service"] = MagicMock()

    # api.prompts: imported for prompt-builder functions; MagicMock is safe
    if "api.prompts" not in sys.modules:
        sys.modules["api.prompts"] = MagicMock()


_stub_modules()

import pytest
from api.teaching_service import _mode_from_chunk_score


# ── STRUGGLING boundary tests ──────────────────────────────────────────────────

def test_score_zero_is_struggling():
    """A score of 0 (no correct answers) must produce STRUGGLING mode."""
    assert _mode_from_chunk_score(0) == "STRUGGLING"


def test_score_49_is_struggling():
    """Score just below the NORMAL threshold must remain STRUGGLING."""
    assert _mode_from_chunk_score(49) == "STRUGGLING"


# ── NORMAL boundary tests ──────────────────────────────────────────────────────

def test_score_50_is_normal():
    """Score at exactly the NORMAL lower boundary must return NORMAL."""
    assert _mode_from_chunk_score(50) == "NORMAL"


def test_score_79_is_normal():
    """Score just below the FAST threshold must remain NORMAL."""
    assert _mode_from_chunk_score(79) == "NORMAL"


# ── FAST boundary tests ────────────────────────────────────────────────────────

def test_score_80_is_fast():
    """Score at exactly the FAST lower boundary must return FAST."""
    assert _mode_from_chunk_score(80) == "FAST"


def test_score_100_is_fast():
    """A perfect score (100) must produce FAST mode."""
    assert _mode_from_chunk_score(100) == "FAST"
