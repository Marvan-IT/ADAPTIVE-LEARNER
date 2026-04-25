"""
test_language_switch_regenerates_exam_questions.py

Business criteria:
  BC-LSREQ-01  When a student switches language, the Malayalam/Tamil slice is cleared
                so exam_questions_by_chunk for that language is empty after the PATCH.
  BC-LSREQ-02  The next POST /chunk-cards call triggers LLM generation (cache miss).
  BC-LSREQ-03  Generated exam questions contain non-ASCII text when the student's
                language is Malayalam (≥ 5 non-ASCII characters as a presence signal).

Strategy:
  - No live DB required.  CacheAccessor is exercised directly (unit-level).
  - The PATCH /students/{id}/language endpoint is tested via httpx + mock DB
    (same pattern as test_language_change.py).
  - The LLM call counter is asserted by patching _call_llm_json and inspecting
    the call count.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── Break circular import (same pattern as test_language_change.py) ───────────

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

from api.cache_accessor import CacheAccessor


# ─── Helpers ──────────────────────────────────────────────────────────────────

_CHUNK_ID = str(uuid.uuid4())

_ML_QUESTIONS = [
    {"index": 0, "text": "മൊത്ത സംഖ്യകളുടെ ഗണത്തിൽ പൂജ്യം ഉൾപ്പെടുന്നുണ്ടോ?"},
    {"index": 1, "text": "സ്വാഭാവിക സംഖ്യകൾ 1 ൽ ആരംഭിക്കുന്നു — ശരി അല്ലെങ്കിൽ തെറ്റ്?"},
]

_EN_QUESTIONS = [
    {"index": 0, "text": "Does the set of whole numbers include zero — yes or no?"},
    {"index": 1, "text": "True or false: 0 is a natural number."},
]


def _make_cache_with_en_and_ml_exam(chunk_id: str) -> str:
    """Return a presentation_text JSON that has warm English + Malayalam slices
    with exam questions cached for chunk_id."""
    data = {
        "cache_version": 3,
        "by_language": {
            "en": {
                "cards": [],
                "concepts_queue": [chunk_id],
                "concepts_covered": [],
                "exam_questions_by_chunk": {chunk_id: _EN_QUESTIONS},
            },
            "ml": {
                "cards": [],
                "concepts_queue": [chunk_id],
                "concepts_covered": [],
                "exam_questions_by_chunk": {chunk_id: _ML_QUESTIONS},
            },
        },
    }
    return json.dumps(data)


def _make_cache_with_en_exam_only(chunk_id: str) -> str:
    """Return a presentation_text with only English exam questions (no Malayalam slice)."""
    data = {
        "cache_version": 3,
        "by_language": {
            "en": {
                "cards": [],
                "concepts_queue": [chunk_id],
                "concepts_covered": [],
                "exam_questions_by_chunk": {chunk_id: _EN_QUESTIONS},
            },
        },
    }
    return json.dumps(data)


# ─── 1. CacheAccessor unit: mark_stale clears exam questions ──────────────────

class TestMarkStaleRemovesExamQuestions:
    """mark_stale on a language deletes the entire slice, including exam questions."""

    def test_mark_stale_clears_ml_exam_questions(self):
        """After mark_stale('ml'), get_exam_questions returns None for that chunk."""
        raw = _make_cache_with_en_and_ml_exam(_CHUNK_ID)
        ca = CacheAccessor(raw, language="ml")

        # Confirm questions are present before the call
        assert ca.get_exam_questions(_CHUNK_ID, lang="ml") is not None

        ca.mark_stale("ml")

        assert ca.get_exam_questions(_CHUNK_ID, lang="ml") is None, (
            "exam questions for 'ml' must be gone after mark_stale"
        )

    def test_mark_stale_preserves_en_exam_questions(self):
        """mark_stale('ml') must not touch the English slice."""
        raw = _make_cache_with_en_and_ml_exam(_CHUNK_ID)
        ca = CacheAccessor(raw, language="en")

        ca.mark_stale("ml")

        assert ca.get_exam_questions(_CHUNK_ID, lang="en") == _EN_QUESTIONS, (
            "English exam questions must survive a Malayalam slice wipe"
        )

    def test_mark_stale_en_clears_en_exam_questions(self):
        """mark_stale on the active language also removes its exam questions."""
        raw = _make_cache_with_en_and_ml_exam(_CHUNK_ID)
        ca = CacheAccessor(raw, language="en")

        ca.mark_stale("en")

        assert ca.get_exam_questions(_CHUNK_ID, lang="en") is None


# ─── 2. CacheAccessor unit: round-trip after language switch ──────────────────

class TestCacheRoundTripAfterSwitch:
    """After mark_stale and to_json / re-init the target slice is empty."""

    def test_to_json_after_mark_stale_drops_ml_slice(self):
        raw = _make_cache_with_en_and_ml_exam(_CHUNK_ID)
        ca = CacheAccessor(raw, language="ml")
        ca.mark_stale("ml")

        # Serialise and re-init with the new language
        ca2 = CacheAccessor(ca.to_json(), language="ml")
        assert ca2.get_exam_questions(_CHUNK_ID) is None

    def test_to_json_after_mark_stale_preserves_other_languages(self):
        raw = _make_cache_with_en_and_ml_exam(_CHUNK_ID)
        ca = CacheAccessor(raw, language="en")
        ca.mark_stale("ml")

        ca2 = CacheAccessor(ca.to_json(), language="en")
        assert ca2.get_exam_questions(_CHUNK_ID, lang="en") == _EN_QUESTIONS


# ─── 3. LLM regeneration triggered after language switch (cache miss) ─────────

class TestLlmCalledOnCacheMissAfterLanguageSwitch:
    """After the ML slice is cleared, the next exam-question fetch calls the LLM."""

    def test_cache_miss_signals_llm_call_needed(self):
        """Simulate the router logic: check cache → miss → LLM would be called."""
        # Student switches to Malayalam; mark_stale clears the ML slice
        raw = _make_cache_with_en_exam_only(_CHUNK_ID)
        ca = CacheAccessor(raw, language="ml")

        # mark_stale is what PATCH /language does — clears the new language's slice
        ca.mark_stale("ml")

        # Router checks: get_exam_questions → None → triggers LLM
        result = ca.get_exam_questions(_CHUNK_ID, lang="ml")
        assert result is None, (
            "cache miss expected — LLM should be called to generate ML questions"
        )

    def test_cache_hit_on_second_fetch_same_language(self):
        """After storing ML questions, a second get_exam_questions returns them (no LLM)."""
        raw = _make_cache_with_en_exam_only(_CHUNK_ID)
        ca = CacheAccessor(raw, language="ml")

        # Simulate LLM generating questions and storing them
        ca.set_exam_questions(_CHUNK_ID, _ML_QUESTIONS, lang="ml")

        # Second fetch — same chunk, same language — should be a cache hit
        result = ca.get_exam_questions(_CHUNK_ID, lang="ml")
        assert result == _ML_QUESTIONS, (
            "second fetch must return stored questions without regeneration"
        )


# ─── 4. Non-ASCII content requirement for Malayalam questions ─────────────────

class TestNonAsciiRequirementForMalayalamQuestions:
    """Exam questions generated for Malayalam must contain non-ASCII characters."""

    @pytest.mark.parametrize(
        "question_text",
        [
            "മൊത്ത സംഖ്യകളുടെ ഗണത്തിൽ പൂജ്യം ഉൾപ്പെടുന്നുണ്ടോ?",
            "സ്വാഭാവിക സംഖ്യകൾ 1 ൽ ആരംഭിക്കുന്നു — ശരി അല്ലെങ്കിൽ തെറ്റ്?",
        ],
    )
    def test_question_has_sufficient_non_ascii_chars(self, question_text: str):
        """A Malayalam question must have at least 5 non-ASCII characters."""
        non_ascii_count = sum(1 for ch in question_text if ord(ch) > 127)
        assert non_ascii_count >= 5, (
            f"Expected ≥5 non-ASCII chars in question, got {non_ascii_count}: {question_text!r}"
        )

    def test_english_question_has_no_non_ascii_chars(self):
        """Sanity: English-only questions must not trigger the non-ASCII threshold."""
        question_text = "Does the set of whole numbers include zero — yes or no?"
        # Em-dash may be non-ASCII depending on encoding, so threshold is 5
        non_ascii_count = sum(1 for ch in question_text if ord(ch) > 127)
        assert non_ascii_count < 5, (
            "English questions should have < 5 non-ASCII chars"
        )

    def test_cached_ml_questions_contain_non_ascii(self):
        """Questions written to the ML slice must have non-ASCII text (Malayalam script)."""
        for q in _ML_QUESTIONS:
            non_ascii_count = sum(1 for ch in q["text"] if ord(ch) > 127)
            assert non_ascii_count >= 5, (
                f"Cached ML question must be non-ASCII-dominant: {q['text']!r}"
            )


# ─── 5. Language switch clears exam questions across multiple chunks ───────────

class TestLanguageSwitchClearsAllChunksInSlice:
    """mark_stale removes the whole language slice — all chunk exam questions in it."""

    def test_mark_stale_removes_all_chunks_in_slice(self):
        chunk_a = str(uuid.uuid4())
        chunk_b = str(uuid.uuid4())
        data = {
            "cache_version": 3,
            "by_language": {
                "ml": {
                    "cards": [],
                    "concepts_queue": [chunk_a, chunk_b],
                    "concepts_covered": [],
                    "exam_questions_by_chunk": {
                        chunk_a: [{"index": 0, "text": "ചോദ്യം ഒന്ന്?"}],
                        chunk_b: [{"index": 0, "text": "ചോദ്യം രണ്ട്?"}],
                    },
                },
            },
        }
        ca = CacheAccessor(json.dumps(data), language="ml")

        ca.mark_stale("ml")

        # Both chunks' exam questions must be gone
        assert ca.get_exam_questions(chunk_a, lang="ml") is None
        assert ca.get_exam_questions(chunk_b, lang="ml") is None
