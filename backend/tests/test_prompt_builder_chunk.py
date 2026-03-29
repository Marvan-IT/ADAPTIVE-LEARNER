"""
test_prompt_builder_chunk.py — Tests for build_chunk_card_prompt in adaptive/prompt_builder.py.

Business criteria covered:
  - Prompt includes the chunk heading so LLM knows what topic to cover
  - Prompt includes the chunk text (content to teach)
  - Student mode string is present so LLM applies the correct delivery style
  - STRUGGLING mode produces different output from NORMAL and FAST
  - NORMAL and FAST modes produce different output from each other
  - Student interests are woven into the prompt for personalization
  - Language code is present for multilingual output
  - Image block appears when images are provided (includes URL and caption)
  - Image block is absent when no images are provided
  - All three modes produce valid, non-empty strings
  - Prompt instructs LLM to produce interleaved content+MCQ pairs
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from adaptive.prompt_builder import build_chunk_card_prompt


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sample_chunk(**overrides) -> dict:
    defaults = {
        "id": "abc-123",
        "heading": "Round Whole Numbers",
        "text": "To round a number, find the rounding digit...\n$$1846 \\rightarrow 1800$$",
        "latex": ["1846 \\rightarrow 1800"],
    }
    defaults.update(overrides)
    return defaults


def _build(chunk=None, images=None, student_mode="NORMAL",
           style="default", interests=None, language="en") -> str:
    return build_chunk_card_prompt(
        chunk=chunk or _sample_chunk(),
        images=images if images is not None else [],
        student_mode=student_mode,
        style=style,
        interests=interests if interests is not None else [],
        language=language,
    )


# ── Heading and content inclusion ─────────────────────────────────────────────

class TestContentInclusion:
    """Prompt must faithfully embed chunk heading and body text."""

    def test_includes_heading(self):
        prompt = _build()
        assert "Round Whole Numbers" in prompt

    def test_includes_chunk_text(self):
        prompt = _build()
        assert "rounding digit" in prompt

    def test_includes_chunk_with_different_heading(self):
        chunk = _sample_chunk(heading="Identify Whole Numbers", text="Whole numbers include 0, 1, 2...")
        prompt = _build(chunk=chunk)
        assert "Identify Whole Numbers" in prompt
        assert "0, 1, 2" in prompt

    def test_long_text_is_present(self):
        long_text = "Mathematics " * 200
        chunk = _sample_chunk(text=long_text)
        prompt = _build(chunk=chunk)
        assert "Mathematics" in prompt


# ── Student mode ──────────────────────────────────────────────────────────────

class TestStudentMode:
    """Student mode string must appear and differentiate prompts."""

    def test_struggling_mode_in_prompt(self):
        prompt = _build(student_mode="STRUGGLING")
        assert "STRUGGLING" in prompt

    def test_normal_mode_in_prompt(self):
        prompt = _build(student_mode="NORMAL")
        assert "NORMAL" in prompt

    def test_fast_mode_in_prompt(self):
        prompt = _build(student_mode="FAST")
        assert "FAST" in prompt

    def test_struggling_differs_from_normal(self):
        p_s = _build(student_mode="STRUGGLING")
        p_n = _build(student_mode="NORMAL")
        assert p_s != p_n

    def test_normal_differs_from_fast(self):
        p_n = _build(student_mode="NORMAL")
        p_f = _build(student_mode="FAST")
        assert p_n != p_f

    def test_struggling_differs_from_fast(self):
        p_s = _build(student_mode="STRUGGLING")
        p_f = _build(student_mode="FAST")
        assert p_s != p_f

    def test_all_modes_produce_non_empty_strings(self):
        for mode in ("STRUGGLING", "NORMAL", "FAST"):
            prompt = _build(student_mode=mode)
            assert prompt.strip(), f"Empty prompt for mode: {mode}"


# ── Personalization ───────────────────────────────────────────────────────────

class TestPersonalization:
    """Interests and style must appear in the prompt."""

    def test_single_interest_included(self):
        prompt = _build(interests=["football"])
        assert "football" in prompt

    def test_multiple_interests_included(self):
        prompt = _build(interests=["gaming", "cooking", "basketball"])
        assert "gaming" in prompt
        assert "cooking" in prompt
        assert "basketball" in prompt

    def test_no_interests_produces_general_fallback(self):
        prompt = _build(interests=[])
        assert "general" in prompt

    def test_pirate_style_in_prompt(self):
        prompt = _build(style="pirate")
        assert "pirate" in prompt

    def test_astronaut_style_in_prompt(self):
        prompt = _build(style="astronaut")
        assert "astronaut" in prompt

    def test_struggling_with_interests(self):
        prompt = _build(student_mode="STRUGGLING", interests=["football"])
        assert "STRUGGLING" in prompt
        assert "football" in prompt


# ── Language ──────────────────────────────────────────────────────────────────

class TestLanguage:
    """Language code must be present; different languages produce different prompts."""

    def test_english_language_code_included(self):
        prompt = _build(language="en")
        assert "en" in prompt

    def test_arabic_language_code_included(self):
        prompt = _build(language="ar")
        assert "ar" in prompt

    def test_spanish_language_code_included(self):
        prompt = _build(language="es")
        assert "es" in prompt

    def test_different_languages_produce_different_prompts(self):
        p_en = _build(language="en")
        p_ar = _build(language="ar")
        assert p_en != p_ar


# ── Image block ───────────────────────────────────────────────────────────────

class TestImageBlock:
    """Image block appears iff images are provided."""

    def test_image_block_included_when_images_present(self):
        images = [{"image_url": "http://localhost:8889/images/test.jpg", "caption": "Number line"}]
        prompt = _build(images=images)
        assert "IMAGES IN THIS CHUNK" in prompt
        assert "test.jpg" in prompt

    def test_image_caption_included(self):
        images = [{"image_url": "http://localhost:8889/images/test.jpg", "caption": "Number line"}]
        prompt = _build(images=images)
        assert "Number line" in prompt

    def test_image_url_without_caption(self):
        images = [{"image_url": "http://localhost:8889/images/nocaption.jpg"}]
        prompt = _build(images=images)
        assert "nocaption.jpg" in prompt

    def test_multiple_images_all_included(self):
        images = [
            {"image_url": "http://localhost:8889/images/a.jpg", "caption": "Fig A"},
            {"image_url": "http://localhost:8889/images/b.jpg", "caption": "Fig B"},
        ]
        prompt = _build(images=images)
        assert "a.jpg" in prompt
        assert "b.jpg" in prompt
        assert "Fig A" in prompt
        assert "Fig B" in prompt

    def test_no_image_block_when_no_images(self):
        prompt = _build(images=[])
        assert "IMAGES IN THIS CHUNK" not in prompt

    def test_image_block_instructs_llm_to_set_image_url(self):
        images = [{"image_url": "http://localhost:8889/images/x.jpg", "caption": None}]
        prompt = _build(images=images)
        assert "image_url" in prompt

    def test_image_block_instructs_llm_null_when_no_reference(self):
        images = [{"image_url": "http://localhost:8889/images/x.jpg", "caption": None}]
        prompt = _build(images=images)
        assert "null" in prompt


# ── Output format instruction ─────────────────────────────────────────────────

class TestOutputFormatInstruction:
    """Prompt must instruct LLM to produce interleaved content+MCQ pairs as JSON."""

    def test_interleaved_pairs_instruction(self):
        # The prompt now uses "COMBINED" language (content+MCQ in a single card object)
        # rather than the old "interleaved pairs" / separate content_card/mcq_card wording.
        prompt = _build()
        assert (
            "COMBINED" in prompt
            or "interleaved" in prompt.lower()
            or "content_card" in prompt
            or "mcq_card" in prompt
        )

    def test_json_array_instruction(self):
        prompt = _build()
        # Must ask for a JSON array
        prompt_lower = prompt.lower()
        assert "json" in prompt_lower

    def test_return_instruction_present(self):
        prompt = _build()
        # Must contain some generation instruction
        assert "generate" in prompt.lower() or "return" in prompt.lower()


# ── Determinism ───────────────────────────────────────────────────────────────

class TestDeterminism:
    """Same inputs must always produce identical prompts (no randomness)."""

    def test_same_inputs_same_output(self):
        chunk = _sample_chunk()
        kwargs = dict(images=[], student_mode="NORMAL", style="default", interests=["math"], language="en")
        p1 = build_chunk_card_prompt(chunk=chunk, **kwargs)
        p2 = build_chunk_card_prompt(chunk=chunk, **kwargs)
        assert p1 == p2

    def test_different_chunks_different_prompts(self):
        chunk_a = _sample_chunk(heading="Rounding", text="Round to the nearest ten.")
        chunk_b = _sample_chunk(heading="Fractions", text="A fraction represents a part of a whole.")
        p_a = _build(chunk=chunk_a)
        p_b = _build(chunk=chunk_b)
        assert p_a != p_b
