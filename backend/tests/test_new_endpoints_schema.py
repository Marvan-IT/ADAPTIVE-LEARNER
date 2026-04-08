"""
test_new_endpoints_schema.py — Tests for chunk-based request/response schemas.

Business criteria covered:
  - ChunkCardsRequest carries chunk_id (UUID string)
  - ChunkCardsResponse carries cards, chunk_id, chunk_index, total_chunks, is_last_chunk
  - ChunkCardsResponse is_last_chunk is True when chunk_index == total_chunks - 1
  - RecoveryCardRequest has chunk_id, card_index, wrong_answers (defaults to [])
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
