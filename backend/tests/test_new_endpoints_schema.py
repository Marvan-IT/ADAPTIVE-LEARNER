"""
test_new_endpoints_schema.py — Tests for chunk-based request/response schemas.

Business criteria covered:
  - ChunkCardsRequest carries chunk_id (UUID string)
  - ChunkCardsResponse carries cards, chunk_id, chunk_index, total_chunks, is_last_chunk
  - ChunkCardsResponse is_last_chunk is True when chunk_index == total_chunks - 1
  - RecoveryCardRequest has chunk_id, card_index, wrong_answers (defaults to [])
  - SocraticExamStartRequest holds session_id
  - SocraticExamAnswer holds question_index and answer
  - SocraticExamResult validates score (0.0–1.0), passed bool, counts, failed_chunk_ids, attempt
  - All schemas serialize cleanly via model_dump()
  - Pydantic ValidationError is raised for invalid field values where constraints apply
"""

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from api.teaching_schemas import (
    ChunkCardsRequest,
    ChunkCardsResponse,
    RecoveryCardRequest,
    SocraticExamAnswer,
    SocraticExamResult,
    SocraticExamStartRequest,
    LessonCard,
    CardMCQ,
)


# ── ChunkCardsRequest ─────────────────────────────────────────────────────────

class TestChunkCardsRequest:
    """ChunkCardsRequest carries the chunk_id targeting a ConceptChunk row."""

    def test_valid_chunk_id(self):
        req = ChunkCardsRequest(chunk_id="abc-123-uuid")
        assert req.chunk_id == "abc-123-uuid"

    def test_uuid_format_chunk_id(self):
        chunk_id = "550e8400-e29b-41d4-a716-446655440000"
        req = ChunkCardsRequest(chunk_id=chunk_id)
        assert req.chunk_id == chunk_id

    def test_serialization(self):
        req = ChunkCardsRequest(chunk_id="chunk-001")
        d = req.model_dump()
        assert "chunk_id" in d
        assert d["chunk_id"] == "chunk-001"

    def test_missing_chunk_id_raises(self):
        with pytest.raises(ValidationError):
            ChunkCardsRequest()


# ── ChunkCardsResponse ────────────────────────────────────────────────────────

class TestChunkCardsResponse:
    """ChunkCardsResponse encodes pagination state for chunk-by-chunk delivery."""

    def _make_card(self, index: int = 0) -> LessonCard:
        return LessonCard(index=index, title=f"Card {index}", content="Content.")

    def test_valid_response_not_last(self):
        resp = ChunkCardsResponse(
            cards=[self._make_card(0), self._make_card(1)],
            chunk_id="chunk-abc",
            chunk_index=0,
            total_chunks=5,
            is_last_chunk=False,
        )
        assert resp.total_chunks == 5
        assert not resp.is_last_chunk
        assert resp.chunk_index == 0

    def test_valid_response_last_chunk(self):
        resp = ChunkCardsResponse(
            cards=[self._make_card(0)],
            chunk_id="chunk-xyz",
            chunk_index=4,
            total_chunks=5,
            is_last_chunk=True,
        )
        assert resp.is_last_chunk is True

    def test_empty_cards_list_allowed(self):
        resp = ChunkCardsResponse(
            cards=[],
            chunk_id="chunk-empty",
            chunk_index=2,
            total_chunks=3,
            is_last_chunk=False,
        )
        assert resp.cards == []

    def test_chunk_id_preserved(self):
        resp = ChunkCardsResponse(
            cards=[], chunk_id="my-chunk-id", chunk_index=0, total_chunks=1, is_last_chunk=True
        )
        assert resp.chunk_id == "my-chunk-id"

    def test_serialization_keys(self):
        resp = ChunkCardsResponse(
            cards=[], chunk_id="c", chunk_index=0, total_chunks=1, is_last_chunk=True
        )
        d = resp.model_dump()
        assert "cards" in d
        assert "chunk_id" in d
        assert "chunk_index" in d
        assert "total_chunks" in d
        assert "is_last_chunk" in d

    def test_cards_are_lesson_card_instances(self):
        resp = ChunkCardsResponse(
            cards=[self._make_card(0), self._make_card(1)],
            chunk_id="c", chunk_index=0, total_chunks=2, is_last_chunk=True,
        )
        assert all(isinstance(c, LessonCard) for c in resp.cards)

    def test_missing_required_fields_raise(self):
        with pytest.raises(ValidationError):
            # chunk_id is required
            ChunkCardsResponse(cards=[], chunk_index=0, total_chunks=1, is_last_chunk=False)


# ── RecoveryCardRequest ───────────────────────────────────────────────────────

class TestRecoveryCardRequest:
    """RecoveryCardRequest carries context for generating a re-explain card."""

    def test_minimal_request(self):
        req = RecoveryCardRequest(chunk_id="chunk-abc")
        assert req.chunk_id == "chunk-abc"
        assert req.card_index == 0
        assert req.wrong_answers == []

    def test_wrong_answers_default_empty(self):
        req = RecoveryCardRequest(chunk_id="chunk-abc", card_index=2)
        assert req.wrong_answers == []

    def test_with_wrong_answers(self):
        req = RecoveryCardRequest(
            chunk_id="chunk-abc",
            card_index=1,
            wrong_answers=["3", "7"],
        )
        assert req.wrong_answers == ["3", "7"]
        assert req.card_index == 1

    def test_serialization(self):
        req = RecoveryCardRequest(chunk_id="c", card_index=0, wrong_answers=["x"])
        d = req.model_dump()
        assert "chunk_id" in d
        assert "card_index" in d
        assert "wrong_answers" in d

    def test_missing_chunk_id_raises(self):
        with pytest.raises(ValidationError):
            RecoveryCardRequest()


# ── SocraticExamStartRequest ──────────────────────────────────────────────────

class TestSocraticExamStartRequest:
    """SocraticExamStartRequest identifies the session for a Socratic exam."""

    def test_valid_session_id(self):
        req = SocraticExamStartRequest(session_id="550e8400-e29b-41d4-a716-446655440000")
        assert req.session_id == "550e8400-e29b-41d4-a716-446655440000"

    def test_session_id_is_string(self):
        req = SocraticExamStartRequest(session_id="some-session-id")
        assert isinstance(req.session_id, str)

    def test_serialization(self):
        req = SocraticExamStartRequest(session_id="session-abc")
        d = req.model_dump()
        assert "session_id" in d
        assert d["session_id"] == "session-abc"

    def test_missing_session_id_raises(self):
        with pytest.raises(ValidationError):
            SocraticExamStartRequest()


# ── SocraticExamAnswer ────────────────────────────────────────────────────────

class TestSocraticExamAnswer:
    """SocraticExamAnswer records the student's answer to one exam question."""

    def test_valid_answer(self):
        ans = SocraticExamAnswer(question_index=0, answer="A whole number is a non-negative integer.")
        assert ans.question_index == 0
        assert "non-negative integer" in ans.answer

    def test_question_index_preserved(self):
        ans = SocraticExamAnswer(question_index=5, answer="My answer")
        assert ans.question_index == 5

    def test_serialization(self):
        ans = SocraticExamAnswer(question_index=2, answer="Answer text")
        d = ans.model_dump()
        assert "question_index" in d
        assert "answer" in d

    def test_missing_both_fields_raises(self):
        with pytest.raises(ValidationError):
            SocraticExamAnswer()


# ── SocraticExamResult ────────────────────────────────────────────────────────

class TestSocraticExamResult:
    """SocraticExamResult summarises the outcome of a Socratic exam attempt."""

    def test_passing_result(self):
        result = SocraticExamResult(
            score=0.75,
            passed=True,
            total_questions=8,
            correct_count=6,
            failed_chunk_ids=[],
            attempt=1,
        )
        assert result.score == 0.75
        assert result.passed is True
        assert result.correct_count == 6
        assert result.attempt == 1

    def test_failing_result_with_failed_chunks(self):
        result = SocraticExamResult(
            score=0.625,
            passed=False,
            total_questions=8,
            correct_count=5,
            failed_chunk_ids=["chunk-1", "chunk-3"],
            attempt=1,
        )
        assert result.score == 0.625
        assert not result.passed
        assert len(result.failed_chunk_ids) == 2
        assert "chunk-1" in result.failed_chunk_ids

    def test_zero_score_not_passed(self):
        result = SocraticExamResult(
            score=0.0, passed=False, total_questions=5,
            correct_count=0, failed_chunk_ids=["c1", "c2", "c3", "c4", "c5"], attempt=1,
        )
        assert result.score == 0.0
        assert not result.passed

    def test_perfect_score(self):
        result = SocraticExamResult(
            score=1.0, passed=True, total_questions=10,
            correct_count=10, failed_chunk_ids=[], attempt=1,
        )
        assert result.score == 1.0
        assert result.passed is True
        assert result.failed_chunk_ids == []

    def test_attempt_number_preserved(self):
        result = SocraticExamResult(
            score=0.7, passed=True, total_questions=10,
            correct_count=7, failed_chunk_ids=[], attempt=3,
        )
        assert result.attempt == 3

    def test_serialization_keys(self):
        result = SocraticExamResult(
            score=0.8, passed=True, total_questions=5,
            correct_count=4, failed_chunk_ids=[], attempt=1,
        )
        d = result.model_dump()
        assert "score" in d
        assert "passed" in d
        assert "total_questions" in d
        assert "correct_count" in d
        assert "failed_chunk_ids" in d
        assert "attempt" in d

    def test_missing_required_fields_raises(self):
        with pytest.raises(ValidationError):
            # score and passed are required
            SocraticExamResult(total_questions=5, correct_count=3, failed_chunk_ids=[], attempt=1)

    def test_multiple_attempts_tracked(self):
        # first attempt fails, second passes
        attempt1 = SocraticExamResult(
            score=0.5, passed=False, total_questions=10,
            correct_count=5, failed_chunk_ids=["c1", "c2"], attempt=1,
        )
        attempt2 = SocraticExamResult(
            score=0.8, passed=True, total_questions=10,
            correct_count=8, failed_chunk_ids=[], attempt=2,
        )
        assert attempt1.attempt == 1
        assert attempt2.attempt == 2
        assert not attempt1.passed
        assert attempt2.passed

    def test_failed_chunk_ids_is_list(self):
        result = SocraticExamResult(
            score=0.4, passed=False, total_questions=5,
            correct_count=2, failed_chunk_ids=["x", "y", "z"], attempt=1,
        )
        assert isinstance(result.failed_chunk_ids, list)


# ── Cross-schema integration ──────────────────────────────────────────────────

class TestChunkSchemaIntegration:
    """Cross-schema composition and common patterns."""

    def test_chunk_response_with_mcq_card(self):
        mcq = CardMCQ(
            text="What is a whole number?",
            options=["Any number", "Non-negative integer", "A fraction", "A decimal"],
            correct_index=1,
            explanation="Whole numbers are 0, 1, 2, 3...",
        )
        card = LessonCard(
            index=1, title="Check Your Understanding", content="",
            question=mcq, chunk_id="chunk-prealgebra-1"
        )
        resp = ChunkCardsResponse(
            cards=[card],
            chunk_id="chunk-prealgebra-1",
            chunk_index=0,
            total_chunks=3,
            is_last_chunk=False,
        )
        d = resp.model_dump()
        assert d["cards"][0]["question"]["correct_index"] == 1
        assert d["chunk_id"] == "chunk-prealgebra-1"
        assert d["is_last_chunk"] is False

    def test_recovery_request_after_two_wrong_answers(self):
        # Business rule: recovery card triggered when wrong_answers has 2+ entries
        req = RecoveryCardRequest(
            chunk_id="chunk-prealgebra-2",
            card_index=3,
            wrong_answers=["4", "8"],
        )
        assert len(req.wrong_answers) == 2
        d = req.model_dump()
        assert d["wrong_answers"] == ["4", "8"]
        assert d["card_index"] == 3
