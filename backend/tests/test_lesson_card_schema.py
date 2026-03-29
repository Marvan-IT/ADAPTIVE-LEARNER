"""
test_lesson_card_schema.py — Tests for the new clean LessonCard and CardMCQ schemas.

Business criteria covered:
  - Content cards have correct defaults (question=None, image_url=None, is_recovery=False)
  - MCQ cards carry a well-formed CardMCQ with the correct field names
  - Recovery flag is preserved
  - Image cards carry image_url and caption
  - Legacy fields (card_type, image_indices, images) are absent from the schema
  - Serialization produces the expected key set with no legacy keys
  - chunk_id links a card back to its source ConceptChunk
  - CardMCQ fields: text, options (4 choices), correct_index (0–3), explanation, difficulty
  - CardMCQ validation: options must be exactly 4; correct_index must be 0–3
"""

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from api.teaching_schemas import CardMCQ, LessonCard


# ── CardMCQ schema ────────────────────────────────────────────────────────────

class TestCardMCQSchema:
    """CardMCQ validates and serialises correctly."""

    def _valid_mcq(self, **overrides) -> dict:
        defaults = {
            "text": "What is 2+2?",
            "options": ["1", "2", "4", "6"],
            "correct_index": 2,
            "explanation": "2+2 equals 4.",
            "difficulty": "MEDIUM",
        }
        defaults.update(overrides)
        return defaults

    def test_valid_mcq_minimal(self):
        mcq = CardMCQ(**self._valid_mcq())
        assert mcq.text == "What is 2+2?"
        assert mcq.correct_index == 2
        assert len(mcq.options) == 4

    def test_explanation_defaults_to_empty_string(self):
        mcq = CardMCQ(text="Q?", options=["A", "B", "C", "D"], correct_index=0)
        assert mcq.explanation == ""

    def test_difficulty_defaults_to_medium(self):
        mcq = CardMCQ(text="Q?", options=["A", "B", "C", "D"], correct_index=0)
        assert mcq.difficulty == "MEDIUM"

    def test_correct_index_boundary_zero(self):
        mcq = CardMCQ(text="Q?", options=["A", "B", "C", "D"], correct_index=0)
        assert mcq.correct_index == 0

    def test_correct_index_boundary_three(self):
        mcq = CardMCQ(text="Q?", options=["A", "B", "C", "D"], correct_index=3)
        assert mcq.correct_index == 3

    def test_correct_index_too_large_raises(self):
        with pytest.raises(ValidationError):
            CardMCQ(text="Q?", options=["A", "B", "C", "D"], correct_index=4)

    def test_correct_index_negative_raises(self):
        with pytest.raises(ValidationError):
            CardMCQ(text="Q?", options=["A", "B", "C", "D"], correct_index=-1)

    def test_options_must_be_exactly_four(self):
        with pytest.raises(ValidationError):
            CardMCQ(text="Q?", options=["A", "B", "C"], correct_index=0)

    def test_options_too_many_raises(self):
        with pytest.raises(ValidationError):
            CardMCQ(text="Q?", options=["A", "B", "C", "D", "E"], correct_index=0)

    def test_mcq_uses_text_field_not_question(self):
        # Business rule: field name is 'text', not 'question' (legacy name)
        mcq = CardMCQ(text="Define a whole number.", options=["A", "B", "C", "D"], correct_index=1)
        assert hasattr(mcq, "text")
        assert not hasattr(mcq, "question")

    def test_mcq_uses_options_field_not_choices(self):
        mcq = CardMCQ(text="Q?", options=["A", "B", "C", "D"], correct_index=0)
        assert hasattr(mcq, "options")
        assert not hasattr(mcq, "choices")

    def test_mcq_uses_correct_index_not_correct(self):
        mcq = CardMCQ(text="Q?", options=["A", "B", "C", "D"], correct_index=0)
        assert hasattr(mcq, "correct_index")
        assert not hasattr(mcq, "correct")

    def test_serialization_keys(self):
        mcq = CardMCQ(text="Q?", options=["A", "B", "C", "D"], correct_index=2, explanation="Because.")
        d = mcq.model_dump()
        assert set(d.keys()) == {"text", "options", "correct_index", "explanation", "difficulty"}


# ── LessonCard schema ─────────────────────────────────────────────────────────

class TestLessonCardSchema:
    """LessonCard validates, defaults and serialises correctly."""

    def test_content_card_minimal(self):
        card = LessonCard(index=0, title="Test", content="Some content")
        assert card.question is None
        assert card.image_url is None
        assert card.is_recovery is False
        assert card.chunk_id == ""

    def test_content_card_caption_defaults_none(self):
        card = LessonCard(index=0, title="T", content="C")
        assert card.caption is None

    def test_mcq_card(self):
        mcq = CardMCQ(
            text="What is 2+2?",
            options=["3", "4", "5", "6"],
            correct_index=1,
            explanation="Addition.",
        )
        card = LessonCard(index=1, title="MCQ", content="", question=mcq, chunk_id="abc-123")
        assert card.question is not None
        assert card.question.correct_index == 1
        assert card.chunk_id == "abc-123"

    def test_recovery_card_flag(self):
        card = LessonCard(
            index=2, title="Try Again", content="Let's revisit...", is_recovery=True
        )
        assert card.is_recovery is True

    def test_image_card(self):
        card = LessonCard(
            index=0,
            title="Number Line",
            content="See the diagram",
            image_url="http://localhost:8889/images/prealgebra/images_downloaded/abc123.jpg",
            caption="Figure 1.1",
        )
        assert card.image_url is not None
        assert card.caption == "Figure 1.1"

    def test_chunk_id_stored_correctly(self):
        card = LessonCard(index=5, title="T", content="C", chunk_id="deadbeef-1234")
        assert card.chunk_id == "deadbeef-1234"

    def test_index_stored_correctly(self):
        card = LessonCard(index=7, title="T", content="C")
        assert card.index == 7

    def test_no_legacy_card_type_field(self):
        card = LessonCard(index=0, title="T", content="C")
        assert not hasattr(card, "card_type")

    def test_no_legacy_image_indices_field(self):
        card = LessonCard(index=0, title="T", content="C")
        assert not hasattr(card, "image_indices")

    def test_no_legacy_images_list_field(self):
        card = LessonCard(index=0, title="T", content="C")
        assert not hasattr(card, "images")

    def test_no_legacy_question2_field(self):
        card = LessonCard(index=0, title="T", content="C")
        assert not hasattr(card, "question2")

    def test_serialization_contains_required_keys(self):
        card = LessonCard(index=0, title="T", content="C", chunk_id="x")
        d = card.model_dump()
        assert "index" in d
        assert "title" in d
        assert "content" in d
        assert "image_url" in d
        assert "caption" in d
        assert "question" in d
        assert "chunk_id" in d
        assert "is_recovery" in d

    def test_serialization_excludes_legacy_keys(self):
        card = LessonCard(index=0, title="T", content="C")
        d = card.model_dump()
        assert "card_type" not in d
        assert "image_indices" not in d
        assert "images" not in d

    def test_serialization_image_url_is_none_by_default(self):
        card = LessonCard(index=0, title="T", content="C")
        d = card.model_dump()
        assert d["image_url"] is None

    def test_serialization_question_is_none_for_content_card(self):
        card = LessonCard(index=0, title="T", content="C")
        d = card.model_dump()
        assert d["question"] is None

    def test_serialization_is_recovery_false_by_default(self):
        card = LessonCard(index=0, title="T", content="C")
        d = card.model_dump()
        assert d["is_recovery"] is False

    def test_full_round_trip_with_mcq(self):
        mcq = CardMCQ(
            text="Which number is prime?",
            options=["4", "6", "7", "9"],
            correct_index=2,
            explanation="7 is prime.",
            difficulty="HARD",
        )
        card = LessonCard(
            index=3,
            title="Prime Numbers",
            content="A prime has exactly two factors.",
            question=mcq,
            chunk_id="chunk-uuid-001",
            is_recovery=False,
        )
        d = card.model_dump()
        assert d["question"]["text"] == "Which number is prime?"
        assert d["question"]["correct_index"] == 2
        assert d["question"]["difficulty"] == "HARD"
        assert d["chunk_id"] == "chunk-uuid-001"

    def test_recovery_card_serialization(self):
        card = LessonCard(
            index=0, title="Let's Revisit", content="You got it wrong. Here's why...",
            is_recovery=True, chunk_id="chunk-abc"
        )
        d = card.model_dump()
        assert d["is_recovery"] is True
        assert d["chunk_id"] == "chunk-abc"
