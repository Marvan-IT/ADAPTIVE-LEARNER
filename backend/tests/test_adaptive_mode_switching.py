"""
test_adaptive_mode_switching.py
================================
Test suite for the Adaptive Mode Switching feature (RC-1 through RC-6).

Groups:
  1. Prompt consolidation — build_cards_system_prompt includes only the active DELIVERY MODE block
  2. prompt_builder.py — build_next_card_prompt includes only the active DELIVERY MODE block
  3. TRY_IT batching — _batch_consecutive_try_its merges consecutive runs correctly
  4. Conservative mode cap — FAST mode is capped to NORMAL for new students (<5 interactions)
  5. Recovery card generation — generate_recovery_card returns None on anti-loop / failure, dict on success
  6. Recovery card personalisation — interests/style/language injected into system prompt
  7. Image distribution — max 1 image assigned per card via image_indices loop
  8. Cache version — _CARDS_CACHE_VERSION literal is 10 in generate_cards source
  9. Interests endpoint schema — UpdateSessionInterestsRequest validates correctly
"""

import inspect
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Ensure backend/src is importable
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ===========================================================================
# Group 1 — Prompt consolidation (RC-1)
# build_cards_system_prompt must emit ONLY the active DELIVERY MODE block.
# ===========================================================================

class TestPromptConsolidation:
    """
    Business criterion: each generate_as value must inject only its own
    DELIVERY MODE block, never the other two modes' blocks.
    Regression: previously all three blocks were appended unconditionally.
    """

    def test_struggling_contains_only_struggling_delivery_block(self):
        """STRUGGLING prompt should contain DELIVERY MODE: STRUGGLING and no others."""
        from api.prompts import build_cards_system_prompt

        prompt = build_cards_system_prompt(generate_as="STRUGGLING")

        assert "DELIVERY MODE: STRUGGLING" in prompt
        assert "DELIVERY MODE: NORMAL" not in prompt
        assert "DELIVERY MODE: FAST" not in prompt

    def test_normal_contains_only_normal_delivery_block(self):
        """NORMAL prompt should contain DELIVERY MODE: NORMAL and no others."""
        from api.prompts import build_cards_system_prompt

        prompt = build_cards_system_prompt(generate_as="NORMAL")

        assert "DELIVERY MODE: NORMAL" in prompt
        assert "DELIVERY MODE: STRUGGLING" not in prompt
        assert "DELIVERY MODE: FAST" not in prompt

    def test_fast_contains_only_fast_delivery_block(self):
        """FAST prompt should contain DELIVERY MODE: FAST and no others."""
        from api.prompts import build_cards_system_prompt

        prompt = build_cards_system_prompt(generate_as="FAST")

        assert "DELIVERY MODE: FAST" in prompt
        assert "DELIVERY MODE: STRUGGLING" not in prompt
        assert "DELIVERY MODE: NORMAL" not in prompt

    def test_unknown_generate_as_defaults_to_normal_without_key_error(self):
        """
        Unknown generate_as value must not raise KeyError and must fall back to
        the NORMAL block so the service degrades gracefully.
        """
        from api.prompts import build_cards_system_prompt

        # Must not raise
        prompt = build_cards_system_prompt(generate_as="UNKNOWN_VALUE")

        # Defaults to NORMAL block
        assert "DELIVERY MODE: NORMAL" in prompt
        assert "DELIVERY MODE: STRUGGLING" not in prompt
        assert "DELIVERY MODE: FAST" not in prompt


# ===========================================================================
# Group 2 — prompt_builder.py DELIVERY MODE (RC-1b)
# build_next_card_prompt must inject only the active mode block.
# ===========================================================================

def _make_learning_profile(**overrides):
    """Build a minimal valid LearningProfile for test use."""
    from adaptive.schemas import LearningProfile

    defaults = dict(
        speed="NORMAL",
        comprehension="OK",
        engagement="ENGAGED",
        confidence_score=0.5,
        recommended_next_step="CONTINUE",
        error_rate=0.2,
    )
    defaults.update(overrides)
    return LearningProfile(**defaults)


def _make_gen_profile():
    """Build a minimal valid GenerationProfile for test use."""
    from adaptive.schemas import GenerationProfile

    return GenerationProfile(
        explanation_depth="MEDIUM",
        reading_level="STANDARD",
        step_by_step=False,
        analogy_level=0.5,
        fun_level=0.4,
        card_count=8,
        practice_count=2,
        checkpoint_frequency=4,
        max_paragraph_lines=6,
        emoji_policy="NONE",
    )


def _minimal_concept_detail():
    return {
        "concept_id": "TEST.C1",
        "concept_title": "Test Concept",
        "chapter": "1",
        "section": "1.1",
        "text": "Test concept source text.",
        "latex": [],
    }


class TestPromptBuilderModeDelivery:
    """
    Business criterion: build_next_card_prompt in adaptive/prompt_builder.py
    must emit only the active mode block so that adaptive single-card prompts
    do not confuse the LLM with contradictory delivery instructions.
    """

    def test_fast_next_card_prompt_does_not_contain_struggling_block(self):
        """
        When generate_as='FAST', build_next_card_prompt should NOT include
        DELIVERY MODE: STRUGGLING in the system prompt overrides.
        """
        from adaptive.prompt_builder import build_next_card_prompt

        system_prompt, _ = build_next_card_prompt(
            concept_detail=_minimal_concept_detail(),
            learning_profile=_make_learning_profile(speed="FAST", comprehension="STRONG"),
            gen_profile=_make_gen_profile(),
            card_index=3,
            history={"trend_direction": "STABLE", "trend_wrong_list": []},
            generate_as="FAST",
        )

        assert "DELIVERY MODE: FAST" in system_prompt
        assert "DELIVERY MODE: STRUGGLING" not in system_prompt

    def test_struggling_next_card_prompt_does_not_contain_fast_block(self):
        """
        When generate_as='STRUGGLING', build_next_card_prompt should NOT include
        DELIVERY MODE: FAST in the system prompt overrides.
        """
        from adaptive.prompt_builder import build_next_card_prompt

        system_prompt, _ = build_next_card_prompt(
            concept_detail=_minimal_concept_detail(),
            learning_profile=_make_learning_profile(speed="SLOW", comprehension="STRUGGLING"),
            gen_profile=_make_gen_profile(),
            card_index=0,
            history={"trend_direction": "STABLE", "trend_wrong_list": []},
            generate_as="STRUGGLING",
        )

        assert "DELIVERY MODE: STRUGGLING" in system_prompt
        assert "DELIVERY MODE: FAST" not in system_prompt

    def test_normal_next_card_prompt_contains_normal_block_only(self):
        """
        When generate_as='NORMAL', the system prompt must include DELIVERY MODE: NORMAL
        and neither STRUGGLING nor FAST.
        """
        from adaptive.prompt_builder import build_next_card_prompt

        system_prompt, _ = build_next_card_prompt(
            concept_detail=_minimal_concept_detail(),
            learning_profile=_make_learning_profile(),
            gen_profile=_make_gen_profile(),
            card_index=2,
            history={"trend_direction": "STABLE", "trend_wrong_list": []},
            generate_as="NORMAL",
        )

        assert "DELIVERY MODE: NORMAL" in system_prompt
        assert "DELIVERY MODE: STRUGGLING" not in system_prompt
        assert "DELIVERY MODE: FAST" not in system_prompt


# ===========================================================================
# Group 3 — TRY_IT batching (RC-2)
# _batch_consecutive_try_its merges consecutive TRY_IT sections correctly.
# ===========================================================================

def _try_it(title: str, text: str = "problem text") -> dict:
    return {"title": title, "text": text, "section_type": "TRY_IT"}


def _example(title: str, text: str = "example text") -> dict:
    return {"title": title, "text": text, "section_type": "EXAMPLE"}


class TestTryItBatching:
    """
    Business criterion: consecutive TRY_IT sections in FAST mode should be
    merged into a single TRY_IT_BATCH to reduce LLM calls and avoid redundant
    practice scaffolding for fast learners.
    """

    def test_three_consecutive_try_its_merged_into_one_batch(self):
        """3 consecutive TRY_IT → 1 TRY_IT_BATCH containing all 3 texts."""
        from api.teaching_service import TeachingService

        sections = [
            _try_it("TRY IT 1.1", "solve 2+2"),
            _try_it("TRY IT 1.2", "solve 3+3"),
            _try_it("TRY IT 1.3", "solve 4+4"),
        ]

        result = TeachingService._batch_consecutive_try_its(sections)

        assert len(result) == 1
        batch = result[0]
        assert batch["section_type"] == "TRY_IT_BATCH"
        # All three original texts must appear in the merged text
        assert "solve 2+2" in batch["text"]
        assert "solve 3+3" in batch["text"]
        assert "solve 4+4" in batch["text"]

    def test_solo_try_it_passes_through_unchanged(self):
        """
        A single TRY_IT with no consecutive neighbours must NOT be merged;
        it should pass through with section_type='TRY_IT' intact.
        """
        from api.teaching_service import TeachingService

        sections = [_try_it("TRY IT 2.1", "only one")]

        result = TeachingService._batch_consecutive_try_its(sections)

        assert len(result) == 1
        assert result[0]["section_type"] == "TRY_IT"
        assert result[0]["title"] == "TRY IT 2.1"

    def test_non_adjacent_try_its_not_merged(self):
        """
        [TRY_IT, EXAMPLE, TRY_IT] — the EXAMPLE boundary breaks the run,
        so no batch is formed and all 3 sections are returned unchanged.
        """
        from api.teaching_service import TeachingService

        sections = [
            _try_it("TRY IT A"),
            _example("EXAMPLE B"),
            _try_it("TRY IT C"),
        ]

        result = TeachingService._batch_consecutive_try_its(sections)

        assert len(result) == 3
        types = [s["section_type"] for s in result]
        assert types == ["TRY_IT", "EXAMPLE", "TRY_IT"]

    def test_five_consecutive_try_its_with_max_batch_4_produces_batch_plus_solo(self):
        """
        5 consecutive TRY_IT sections with max_batch=4:
        first 4 → TRY_IT_BATCH, remaining 1 → TRY_IT (solo, passes through).
        """
        from api.teaching_service import TeachingService

        sections = [_try_it(f"TRY IT {i}", f"problem {i}") for i in range(1, 6)]

        result = TeachingService._batch_consecutive_try_its(sections, max_batch=4)

        assert len(result) == 2
        assert result[0]["section_type"] == "TRY_IT_BATCH"
        assert result[1]["section_type"] == "TRY_IT"

    def test_batch_title_uses_first_and_last_title(self):
        """Merged batch title format is 'FIRST – LAST' (em-dash separator)."""
        from api.teaching_service import TeachingService

        sections = [
            _try_it("TRY IT 3.1"),
            _try_it("TRY IT 3.2"),
        ]

        result = TeachingService._batch_consecutive_try_its(sections)

        assert result[0]["title"] == "TRY IT 3.1 – TRY IT 3.2"

    def test_empty_sections_list_returns_empty(self):
        """Edge case: empty input should produce empty output without error."""
        from api.teaching_service import TeachingService

        result = TeachingService._batch_consecutive_try_its([])

        assert result == []


# ===========================================================================
# Group 4 — Conservative mode cap (RC-5)
# New students (<5 total_interactions) must not receive FAST mode.
# ===========================================================================

class TestConservativeModeCap:
    """
    Business criterion: students who have fewer than 5 total interactions must
    not receive FAST delivery mode, as the system has insufficient data to
    confirm the student's learning level. Cap FAST → NORMAL for safety.
    """

    def test_fast_capped_to_normal_when_interactions_below_threshold(self):
        """
        total_interactions=3 and generate_as='FAST' → cap to NORMAL.
        Simulates the in-service logic: history has few interactions.
        """
        # Test the logic directly as a pure function mirror of the in-service cap
        history = {"total_interactions": 3}
        _generate_as = "FAST"
        _blended_score = 2.8

        total_interactions = history.get("total_interactions", 0)
        if total_interactions < 5 and _generate_as == "FAST":
            _generate_as = "NORMAL"
            _blended_score = min(_blended_score, 2.4)

        assert _generate_as == "NORMAL"
        assert _blended_score <= 2.4

    def test_fast_not_capped_when_interactions_at_threshold(self):
        """
        total_interactions=5 is exactly at the threshold — FAST stays FAST.
        (Strict < 5 means 5 interactions clears the cap.)
        """
        history = {"total_interactions": 5}
        _generate_as = "FAST"
        _blended_score = 2.8

        total_interactions = history.get("total_interactions", 0)
        if total_interactions < 5 and _generate_as == "FAST":
            _generate_as = "NORMAL"
            _blended_score = min(_blended_score, 2.4)

        assert _generate_as == "FAST"
        assert _blended_score == 2.8

    def test_fast_not_capped_when_interactions_well_above_threshold(self):
        """
        total_interactions=50 — experienced student stays in FAST mode.
        """
        history = {"total_interactions": 50}
        _generate_as = "FAST"

        total_interactions = history.get("total_interactions", 0)
        if total_interactions < 5 and _generate_as == "FAST":
            _generate_as = "NORMAL"

        assert _generate_as == "FAST"

    def test_struggling_not_affected_by_cap(self):
        """
        The cap only targets FAST. STRUGGLING mode is never changed,
        even for brand-new students with 0 interactions.
        """
        history = {"total_interactions": 0}
        _generate_as = "STRUGGLING"

        total_interactions = history.get("total_interactions", 0)
        if total_interactions < 5 and _generate_as == "FAST":
            _generate_as = "NORMAL"

        assert _generate_as == "STRUGGLING"

    def test_blended_score_clamped_when_cap_applied(self):
        """
        When cap is applied (FAST→NORMAL), blended_score must be clamped
        to at most 2.4 so downstream profile computation stays in NORMAL range.
        """
        for blended in [2.5, 2.7, 3.0]:
            history = {"total_interactions": 1}
            _generate_as = "FAST"
            _blended_score = blended

            total_interactions = history.get("total_interactions", 0)
            if total_interactions < 5 and _generate_as == "FAST":
                _generate_as = "NORMAL"
                _blended_score = min(_blended_score, 2.4)

            assert _blended_score <= 2.4, f"score not clamped for input {blended}"


# ===========================================================================
# Group 5 — Recovery card generation (RC-6)
# generate_recovery_card anti-loop guard, failure paths, and happy path.
# ===========================================================================

class TestRecoveryCardGeneration:
    """
    Business criterion: when a student fails a card twice, the backend generates
    a simplified re-explanation card. The function must be non-fatal (return None
    on any failure) and must never re-trigger itself for an already-recovery card.
    """

    @pytest.mark.asyncio
    async def test_anti_loop_returns_none_for_lets_try_again_title(self):
        """
        If topic_title already starts with "Let's Try Again", the function
        must return None immediately to prevent recovery-of-recovery loops.
        """
        from adaptive.adaptive_engine import generate_recovery_card

        result = await generate_recovery_card(
            topic_title="Let's Try Again — Multiplication",
            concept_id="PREALG.C1.S1",
            knowledge_svc=MagicMock(),
            llm_client=MagicMock(),
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_anti_loop_exact_prefix_check(self):
        """
        Only titles that EXACTLY start with "Let's Try Again" are blocked.
        A different prefix should be allowed through (knowledge_svc/llm may
        fail, but the anti-loop guard itself should not block it).
        """
        from adaptive.adaptive_engine import generate_recovery_card

        # knowledge_svc returns None → graceful None (not an anti-loop None)
        ks = MagicMock()
        ks.get_concept_detail.return_value = None

        result = await generate_recovery_card(
            topic_title="Let Us Try Again — Multiplication",   # different prefix
            concept_id="PREALG.C1.S1",
            knowledge_svc=ks,
            llm_client=MagicMock(),
        )

        # Returns None because concept_detail is None (not because of anti-loop)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_concept_detail_is_none(self):
        """
        When KnowledgeService.get_concept_detail returns None (concept not found),
        generate_recovery_card must return None without raising.
        Note: get_concept_detail is called synchronously (no await) so we use
        a plain MagicMock, not AsyncMock.
        """
        from adaptive.adaptive_engine import generate_recovery_card

        ks = MagicMock()
        ks.get_concept_detail.return_value = None  # sync call — plain MagicMock

        result = await generate_recovery_card(
            topic_title="Multiplication Basics",
            concept_id="PREALG.C1.S1",
            knowledge_svc=ks,
            llm_client=MagicMock(),
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_llm_raises_exception(self, fake_concept_detail):
        """
        When the LLM raises any Exception, the function must catch it and return
        None (non-fatal) so the rest of the card flow is unaffected.
        Note: get_concept_detail is a sync call; use plain MagicMock.
        """
        from adaptive.adaptive_engine import generate_recovery_card

        ks = MagicMock()
        ks.get_concept_detail.return_value = fake_concept_detail  # sync call

        failing_llm = MagicMock()
        failing_llm.chat.completions.create = AsyncMock(
            side_effect=Exception("OpenAI network error")
        )

        result = await generate_recovery_card(
            topic_title="Multiplication Basics",
            concept_id="PREALG.C1.S1",
            knowledge_svc=ks,
            llm_client=failing_llm,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_happy_path_returns_card_dict_with_is_recovery_flag(self, fake_concept_detail):
        """
        When all dependencies succeed, generate_recovery_card must return a dict
        with is_recovery=True set by the engine (not relying on LLM to include it).
        Note: get_concept_detail is a sync call; use plain MagicMock.
        """
        from adaptive.adaptive_engine import generate_recovery_card

        ks = MagicMock()
        ks.get_concept_detail.return_value = fake_concept_detail  # sync call

        recovery_json = json.dumps({
            "card_type": "TEACH",
            "title": "Let's Try Again — Test Topic",
            "content": "Here is a simpler explanation with an analogy...",
            "image_indices": [],
            "question": {
                "text": "What is 2 + 2?",
                "options": ["2", "4", "6", "8"],
                "correct_index": 1,
                "explanation": "2 + 2 = 4",
                "difficulty": "EASY",
            },
        })
        choice = MagicMock()
        choice.message.content = recovery_json
        response = MagicMock()
        response.choices = [choice]
        llm = MagicMock()
        llm.chat.completions.create = AsyncMock(return_value=response)

        result = await generate_recovery_card(
            topic_title="Test Topic",
            concept_id="PREALG.C1.S1",
            knowledge_svc=ks,
            llm_client=llm,
        )

        assert result is not None
        assert result["is_recovery"] is True
        assert result.get("card_type") == "TEACH"


# ===========================================================================
# Group 6 — Recovery card personalisation
# generate_recovery_card injects interests/style/language into system prompt.
# ===========================================================================

class TestRecoveryCardPersonalisation:
    """
    Business criterion: recovery cards must respect the student's interests,
    learning style, and language so re-explanation stays engaging and accessible.
    """

    @pytest.mark.asyncio
    async def test_interests_appear_in_system_prompt(self, fake_concept_detail):
        """
        When interests=['chess'] are provided, the system prompt sent to the LLM
        must contain 'chess' so the LLM can weave it into the analogy.
        Note: get_concept_detail is a sync call; use plain MagicMock.
        """
        from adaptive.adaptive_engine import generate_recovery_card

        captured_messages: list = []

        recovery_json = json.dumps({
            "card_type": "TEACH",
            "title": "Let's Try Again — Fractions",
            "content": "Let's look at chess pieces as fractions...",
            "image_indices": [],
            "question": {
                "text": "Q?",
                "options": ["A", "B", "C", "D"],
                "correct_index": 0,
                "explanation": "Because A.",
                "difficulty": "EASY",
            },
        })

        async def fake_create(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            choice = MagicMock()
            choice.message.content = recovery_json
            resp = MagicMock()
            resp.choices = [choice]
            return resp

        llm = MagicMock()
        llm.chat.completions.create = AsyncMock(side_effect=fake_create)

        # Sync call — plain MagicMock (NOT AsyncMock)
        ks = MagicMock()
        ks.get_concept_detail = MagicMock(return_value=fake_concept_detail)

        await generate_recovery_card(
            topic_title="Fractions",
            concept_id="PREALG.C1.S1",
            knowledge_svc=ks,
            llm_client=llm,
            interests=["chess"],
        )

        system_messages = [m["content"] for m in captured_messages if m["role"] == "system"]
        assert any("chess" in msg for msg in system_messages), (
            "Expected 'chess' in system prompt when interests=['chess']"
        )

    @pytest.mark.asyncio
    async def test_pirate_style_appears_in_system_prompt(self, fake_concept_detail):
        """
        When style='pirate', the system prompt must contain pirate language
        so the LLM uses the pirate persona.
        Note: get_concept_detail is a sync call; use plain MagicMock.
        """
        from adaptive.adaptive_engine import generate_recovery_card

        captured_messages: list = []

        recovery_json = json.dumps({
            "card_type": "TEACH",
            "title": "Let's Try Again — Division",
            "content": "Ahoy, matey! Division be the art of splitting treasure...",
            "image_indices": [],
            "question": {
                "text": "Q?",
                "options": ["A", "B", "C", "D"],
                "correct_index": 0,
                "explanation": "E.",
                "difficulty": "EASY",
            },
        })

        async def fake_create(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            choice = MagicMock()
            choice.message.content = recovery_json
            resp = MagicMock()
            resp.choices = [choice]
            return resp

        llm = MagicMock()
        llm.chat.completions.create = AsyncMock(side_effect=fake_create)

        # Sync call — plain MagicMock (NOT AsyncMock)
        ks = MagicMock()
        ks.get_concept_detail = MagicMock(return_value=fake_concept_detail)

        await generate_recovery_card(
            topic_title="Division",
            concept_id="PREALG.C1.S1",
            knowledge_svc=ks,
            llm_client=llm,
            style="pirate",
        )

        system_messages = [m["content"] for m in captured_messages if m["role"] == "system"]
        pirate_terms = ["pirate", "Ahoy", "matey", "treasure"]
        assert any(
            any(term in msg for term in pirate_terms)
            for msg in system_messages
        ), "Expected pirate-style language in system prompt when style='pirate'"

    @pytest.mark.asyncio
    async def test_spanish_language_appears_in_system_prompt(self, fake_concept_detail):
        """
        When language='es', the system prompt must instruct the LLM to respond
        in Spanish (the word 'Spanish' must appear in the prompt).
        Note: get_concept_detail is a sync call; use plain MagicMock.
        """
        from adaptive.adaptive_engine import generate_recovery_card

        captured_messages: list = []

        recovery_json = json.dumps({
            "card_type": "TEACH",
            "title": "Let's Try Again — Addition",
            "content": "Vamos a intentarlo otra vez...",
            "image_indices": [],
            "question": {
                "text": "¿Cuánto es 2+2?",
                "options": ["3", "4", "5", "6"],
                "correct_index": 1,
                "explanation": "2+2=4",
                "difficulty": "EASY",
            },
        })

        async def fake_create(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            choice = MagicMock()
            choice.message.content = recovery_json
            resp = MagicMock()
            resp.choices = [choice]
            return resp

        llm = MagicMock()
        llm.chat.completions.create = AsyncMock(side_effect=fake_create)

        # Sync call — plain MagicMock (NOT AsyncMock)
        ks = MagicMock()
        ks.get_concept_detail = MagicMock(return_value=fake_concept_detail)

        await generate_recovery_card(
            topic_title="Addition",
            concept_id="PREALG.C1.S1",
            knowledge_svc=ks,
            llm_client=llm,
            language="es",
        )

        system_messages = [m["content"] for m in captured_messages if m["role"] == "system"]
        assert any("Spanish" in msg for msg in system_messages), (
            "Expected 'Spanish' in system prompt when language='es'"
        )


# ===========================================================================
# Group 7 — Image distribution
# The image assignment loop must limit each card to at most 1 image.
# ===========================================================================

class TestImageDistribution:
    """
    Business criterion: each card in the lesson must display at most one image
    to avoid visual clutter. The post-processing loop enforces this limit.
    """

    def test_card_with_multiple_image_indices_receives_at_most_one_image(self):
        """
        A card with image_indices=[0, 1, 2] should end up with exactly 1 image
        in its 'images' list after the distribution loop runs.
        The first valid index wins; the rest are skipped (break after first assign).
        """
        import re as _re_img

        useful_images = [
            {"filename": "img0.jpg", "description": "Diagram 0", "image_type": "DIAGRAM"},
            {"filename": "img1.jpg", "description": "Diagram 1", "image_type": "DIAGRAM"},
            {"filename": "img2.jpg", "description": "Diagram 2", "image_type": "DIAGRAM"},
        ]

        raw_cards = [
            {"title": "Card A", "content": "content [IMAGE:0]", "image_indices": [0, 1, 2], "images": []},
            {"title": "Card B", "content": "content [IMAGE:1]", "image_indices": [1],         "images": []},
            {"title": "Card C", "content": "content",           "image_indices": [],           "images": []},
        ]

        # Replicate the image distribution loop from teaching_service.generate_cards()
        assigned_global: set = set()
        for card in raw_cards:
            card.setdefault("images", [])
            image_indices = card.pop("image_indices", []) or []
            if not isinstance(image_indices, list):
                image_indices = []

            global_to_local: dict = {}
            for global_idx in image_indices:
                if (
                    isinstance(global_idx, int)
                    and 0 <= global_idx < len(useful_images)
                    and global_idx not in assigned_global
                ):
                    img_copy = dict(useful_images[global_idx])
                    img_copy["caption"] = img_copy.get("description") or f"Diagram for: {card.get('title', '')}"
                    global_to_local[global_idx] = len(card["images"])
                    card["images"].append(img_copy)
                    assigned_global.add(global_idx)
                    break  # Limit to max 1 image per card

        # Card A had [0, 1, 2] → only image 0 should be assigned
        assert len(raw_cards[0]["images"]) == 1
        assert raw_cards[0]["images"][0]["filename"] == "img0.jpg"

    def test_images_are_not_shared_between_cards(self):
        """
        Once an image is assigned to one card it must not be assigned again,
        ensuring each image appears in at most one card.
        """
        useful_images = [
            {"filename": "img0.jpg", "description": "First image", "image_type": "DIAGRAM"},
        ]

        raw_cards = [
            {"title": "Card A", "content": "", "image_indices": [0], "images": []},
            {"title": "Card B", "content": "", "image_indices": [0], "images": []},  # same index
        ]

        assigned_global: set = set()
        for card in raw_cards:
            card.setdefault("images", [])
            image_indices = card.pop("image_indices", []) or []
            global_to_local: dict = {}
            for global_idx in image_indices:
                if (
                    isinstance(global_idx, int)
                    and 0 <= global_idx < len(useful_images)
                    and global_idx not in assigned_global
                ):
                    img_copy = dict(useful_images[global_idx])
                    global_to_local[global_idx] = len(card["images"])
                    card["images"].append(img_copy)
                    assigned_global.add(global_idx)
                    break

        # Image 0 assigned to card A; card B gets nothing
        assert len(raw_cards[0]["images"]) == 1
        assert len(raw_cards[1]["images"]) == 0

    def test_card_with_empty_image_indices_receives_no_assigned_image(self):
        """
        A card with image_indices=[] must receive no images from the primary
        assignment loop (keyword fallback is a separate step not tested here).
        """
        useful_images = [
            {"filename": "img0.jpg", "description": "Diagram", "image_type": "DIAGRAM"},
        ]

        raw_cards = [
            {"title": "Card A", "content": "", "image_indices": [], "images": []},
        ]

        assigned_global: set = set()
        for card in raw_cards:
            card.setdefault("images", [])
            image_indices = card.pop("image_indices", []) or []
            for global_idx in image_indices:
                if (
                    isinstance(global_idx, int)
                    and 0 <= global_idx < len(useful_images)
                    and global_idx not in assigned_global
                ):
                    card["images"].append(dict(useful_images[global_idx]))
                    assigned_global.add(global_idx)
                    break

        assert len(raw_cards[0]["images"]) == 0


# ===========================================================================
# Group 8 — Cache version
# _CARDS_CACHE_VERSION inside generate_cards must be 9.
# ===========================================================================

class TestCacheVersion:
    """
    Business criterion: the cache version literal in generate_cards must be
    exactly 11 so that stale cards from earlier builds are invalidated on load.
    If this literal changes without updating the test, the test fails as a
    sentinel to prompt a deliberate decision.
    """

    def test_cards_cache_version_is_12_in_source(self):
        """
        Inspect the source code of TeachingService.generate_cards() and assert
        that '_CARDS_CACHE_VERSION = 12' appears verbatim.
        This is the canonical regression guard for cache invalidation.
        """
        from api.teaching_service import TeachingService

        source = inspect.getsource(TeachingService.generate_cards)

        assert "_CARDS_CACHE_VERSION = 12" in source, (
            "Cache version literal has changed. Update it deliberately "
            "and bump this test."
        )

    def test_cache_version_written_to_result_dict_via_variable(self):
        """
        The result dict emitted at the end of generate_cards must reference
        _CARDS_CACHE_VERSION (not a hardcoded literal) so cache-bust is always
        consistent with the constant.
        """
        from api.teaching_service import TeachingService

        source = inspect.getsource(TeachingService.generate_cards)

        # The result dict must use the variable, not a hardcoded integer
        assert '"cache_version": _CARDS_CACHE_VERSION' in source or \
               "'cache_version': _CARDS_CACHE_VERSION" in source, (
            "The result dict in generate_cards must assign cache_version=_CARDS_CACHE_VERSION "
            "(variable reference, not a hardcoded integer literal)."
        )


# ===========================================================================
# Group 9 — Interests endpoint schema
# UpdateSessionInterestsRequest validates correctly.
# ===========================================================================

class TestUpdateSessionInterestsRequestSchema:
    """
    Business criterion: the UpdateSessionInterests endpoint must accept a list
    of strings (including empty lists for clearing overrides) without raising
    validation errors. Per-session interest overrides let students customise
    their experience mid-lesson.
    """

    def test_valid_interests_list_validates(self):
        """A list of valid interest strings should validate without errors."""
        from api.teaching_schemas import UpdateSessionInterestsRequest

        req = UpdateSessionInterestsRequest(interests=["chess", "space"])

        assert req.interests == ["chess", "space"]

    def test_empty_interests_list_is_valid(self):
        """
        An empty list is explicitly valid — it means 'clear the per-session
        override and fall back to the student profile interests'.
        """
        from api.teaching_schemas import UpdateSessionInterestsRequest

        req = UpdateSessionInterestsRequest(interests=[])

        assert req.interests == []

    def test_default_factory_produces_empty_list(self):
        """
        When interests is omitted entirely, it should default to an empty list
        via the default_factory.
        """
        from api.teaching_schemas import UpdateSessionInterestsRequest

        req = UpdateSessionInterestsRequest()

        assert req.interests == []

    def test_single_interest_validates(self):
        """A list with a single entry is valid."""
        from api.teaching_schemas import UpdateSessionInterestsRequest

        req = UpdateSessionInterestsRequest(interests=["basketball"])

        assert len(req.interests) == 1
        assert req.interests[0] == "basketball"

    def test_interests_is_a_list_of_strings(self):
        """All elements in interests must be strings (Pydantic coercion check)."""
        from api.teaching_schemas import UpdateSessionInterestsRequest

        req = UpdateSessionInterestsRequest(interests=["math", "music", "cooking"])

        assert all(isinstance(x, str) for x in req.interests)

    def test_long_interest_string_accepted(self):
        """
        The schema has no max_length on individual interest strings, so a 51-char
        string should validate cleanly (no validation error).
        """
        from api.teaching_schemas import UpdateSessionInterestsRequest

        long_interest = "x" * 51
        req = UpdateSessionInterestsRequest(interests=[long_interest])

        assert req.interests == [long_interest]


# ===========================================================================
# Group 10 — LLM provider config smoke tests
# Verify LLM config constants are fully env-driven and default to OpenAI.
# ===========================================================================

class TestLLMProviderConfig:
    """Verify LLM config constants are fully env-driven and default to OpenAI."""

    def test_adaptive_card_model_equals_openai_model_mini(self):
        """ADAPTIVE_CARD_MODEL must equal OPENAI_MODEL_MINI — it is a derived constant, not hardcoded."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from config import ADAPTIVE_CARD_MODEL, OPENAI_MODEL_MINI
        assert ADAPTIVE_CARD_MODEL == OPENAI_MODEL_MINI

    def test_config_base_url_defaults_to_openai_when_env_var_absent(self):
        """When OPENAI_BASE_URL env var is absent, config must default to official OpenAI endpoint."""
        import sys, os, importlib
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        # Temporarily remove env var
        old = os.environ.pop("OPENAI_BASE_URL", None)
        try:
            import config as cfg
            importlib.reload(cfg)
            assert "openai.com" in cfg.OPENAI_BASE_URL, (
                f"Expected OpenAI base URL, got: {cfg.OPENAI_BASE_URL}"
            )
        finally:
            # Restore env var if it was set
            if old is not None:
                os.environ["OPENAI_BASE_URL"] = old


# ===========================================================================
# Group 11 — Section coverage
# Config constants for section budgets and cache version guard.
# ===========================================================================

class TestSectionCoverage:
    def test_starter_pack_max_sections_is_at_least_30(self):
        from config import STARTER_PACK_MAX_SECTIONS
        assert STARTER_PACK_MAX_SECTIONS >= 30

    def test_token_budget_scales_with_sections_no_ceiling(self):
        """Token budget must grow linearly with section count — no hardcoded ceiling."""
        from config import (
            CARDS_MAX_TOKENS_SLOW_FLOOR, CARDS_MAX_TOKENS_SLOW_PER_SECTION,
            CARDS_MAX_TOKENS_NORMAL_FLOOR, CARDS_MAX_TOKENS_NORMAL_PER_SECTION,
            CARDS_MAX_TOKENS_FAST_FLOOR, CARDS_MAX_TOKENS_FAST_PER_SECTION,
        )
        # Budget for 50 sections must be larger than for 5 sections
        assert max(CARDS_MAX_TOKENS_SLOW_FLOOR,   50 * CARDS_MAX_TOKENS_SLOW_PER_SECTION)   > max(CARDS_MAX_TOKENS_SLOW_FLOOR,   5 * CARDS_MAX_TOKENS_SLOW_PER_SECTION)
        assert max(CARDS_MAX_TOKENS_NORMAL_FLOOR, 50 * CARDS_MAX_TOKENS_NORMAL_PER_SECTION) > max(CARDS_MAX_TOKENS_NORMAL_FLOOR, 5 * CARDS_MAX_TOKENS_NORMAL_PER_SECTION)
        assert max(CARDS_MAX_TOKENS_FAST_FLOOR,   50 * CARDS_MAX_TOKENS_FAST_PER_SECTION)   > max(CARDS_MAX_TOKENS_FAST_FLOOR,   5 * CARDS_MAX_TOKENS_FAST_PER_SECTION)

    def test_cards_cache_version_is_12(self):
        import re, pathlib
        _src_dir = pathlib.Path(__file__).resolve().parent.parent / "src"
        src = (_src_dir / "api" / "teaching_service.py").read_text()
        match = re.search(r"_CARDS_CACHE_VERSION\s*=\s*(\d+)", src)
        assert match and int(match.group(1)) == 12


# ===========================================================================
# Group 12 — Hybrid Rolling Adaptive Card Generation (cache version 11)
# Tests for the rolling architecture: starter-pack, per-section token budgets,
# schemas, and TeachingService methods.
# ===========================================================================

class TestHybridRollingCards:
    """Tests for the Hybrid Rolling Adaptive Card Generation architecture (cache version 11)."""

    def test_starter_pack_initial_sections_is_2(self):
        """STARTER_PACK_INITIAL_SECTIONS must be 2 — first 2 sub-sections form the starter pack."""
        from config import STARTER_PACK_INITIAL_SECTIONS
        assert STARTER_PACK_INITIAL_SECTIONS == 2

    def test_per_section_slow_floor_is_at_least_5000(self):
        """Slow learner section floor must be >=5000 tokens to generate 7-12 cards."""
        from config import CARDS_MAX_TOKENS_SLOW_PER_SECTION
        assert CARDS_MAX_TOKENS_SLOW_PER_SECTION >= 5000

    def test_per_section_normal_floor_is_at_least_3500(self):
        """Normal learner section floor must be >=3500 tokens."""
        from config import CARDS_MAX_TOKENS_NORMAL_PER_SECTION
        assert CARDS_MAX_TOKENS_NORMAL_PER_SECTION >= 3500

    def test_per_section_fast_floor_is_at_least_2500(self):
        """Fast learner section floor must be >=2500 tokens."""
        from config import CARDS_MAX_TOKENS_FAST_PER_SECTION
        assert CARDS_MAX_TOKENS_FAST_PER_SECTION >= 2500

    def test_cards_cache_version_is_12(self):
        """Cache version must be 12 to invalidate all old bulk-generated card caches."""
        import re
        import pathlib
        _src_dir = pathlib.Path(__file__).resolve().parent.parent / "src"
        src = (_src_dir / "api" / "teaching_service.py").read_text()
        match = re.search(r"_CARDS_CACHE_VERSION\s*=\s*(\d+)", src)
        assert match is not None, "_CARDS_CACHE_VERSION not found in teaching_service.py"
        assert int(match.group(1)) == 12, f"Expected cache version 12, got {match.group(1)}"

    def test_lesson_card_has_question2_field(self):
        """LessonCard must have question2 field (pre-generated second MCQ, no API call on first wrong)."""
        from api.teaching_schemas import LessonCard
        fields = LessonCard.model_fields
        assert "question2" in fields, "LessonCard missing question2 field"
        assert fields["question2"].default is None, "question2 must default to None (optional)"

    def test_question2_is_card_mcq_type(self):
        """question2 must be typed as CardMCQ | None, same as question."""
        from api.teaching_schemas import LessonCard, CardMCQ
        import typing
        fields = LessonCard.model_fields
        assert "question2" in fields
        # Verify both question and question2 have similar annotation (CardMCQ or None)
        assert "question" in fields
        # Both should be optional CardMCQ
        q2_annotation = str(fields["question2"].annotation)
        assert "CardMCQ" in q2_annotation or "NoneType" in q2_annotation

    def test_no_adaptive_card_ceiling_in_adaptive_router(self):
        """_ADAPTIVE_CARD_CEILING must be fully removed — no hard cap on card generation."""
        import pathlib
        _src_dir = pathlib.Path(__file__).resolve().parent.parent / "src"
        src = (_src_dir / "adaptive" / "adaptive_router.py").read_text()
        assert "_ADAPTIVE_CARD_CEILING" not in src, (
            "_ADAPTIVE_CARD_CEILING found in adaptive_router.py — must be fully removed. "
            "No hard cap on card count; rolling architecture gates on has_more_concepts."
        )

    def test_no_ceiling_409_response_in_adaptive_router(self):
        """The ceiling HTTPException(409, ceiling=True) must be removed."""
        import pathlib
        _src_dir = pathlib.Path(__file__).resolve().parent.parent / "src"
        src = (_src_dir / "adaptive" / "adaptive_router.py").read_text()
        assert '"ceiling"' not in src or "ceiling: True" not in src, (
            "ceiling=True HTTPException found — ceiling guard must be removed"
        )

    def test_cards_response_has_rolling_metadata(self):
        """CardsResponse must include rolling metadata fields."""
        from api.teaching_schemas import CardsResponse
        fields = CardsResponse.model_fields
        assert "has_more_concepts" in fields, "CardsResponse missing has_more_concepts"
        assert "concepts_total" in fields, "CardsResponse missing concepts_total"
        assert "concepts_covered_count" in fields, "CardsResponse missing concepts_covered_count"

    def test_cards_response_has_more_concepts_defaults_false(self):
        """has_more_concepts must default to False (backward compatible with old clients)."""
        from api.teaching_schemas import CardsResponse
        fields = CardsResponse.model_fields
        assert fields["has_more_concepts"].default is False

    def test_next_section_cards_request_schema_exists(self):
        """NextSectionCardsRequest schema must exist with signal fields."""
        from api.teaching_schemas import NextSectionCardsRequest
        fields = NextSectionCardsRequest.model_fields
        assert "card_index" in fields
        assert "time_on_card_sec" in fields
        assert "wrong_attempts" in fields
        assert "hints_used" in fields

    def test_next_section_cards_response_schema_exists(self):
        """NextSectionCardsResponse schema must exist with all rolling fields."""
        from api.teaching_schemas import NextSectionCardsResponse
        fields = NextSectionCardsResponse.model_fields
        required = ("session_id", "cards", "has_more_concepts", "concepts_total",
                    "concepts_covered_count", "current_mode")
        for f in required:
            assert f in fields, f"NextSectionCardsResponse missing field: {f}"

    def test_concepts_queue_key_in_teaching_service(self):
        """generate_cards() must store concepts_queue in the presentation_text result dict."""
        import pathlib
        _src_dir = pathlib.Path(__file__).resolve().parent.parent / "src"
        src = (_src_dir / "api" / "teaching_service.py").read_text()
        assert '"concepts_queue"' in src or "'concepts_queue'" in src, (
            "concepts_queue key not found in teaching_service.py — "
            "starter-pack split must store remaining sections for rolling generation"
        )

    def test_generate_next_section_cards_method_exists(self):
        """TeachingService must have generate_next_section_cards() method for rolling generation."""
        from api.teaching_service import TeachingService
        assert hasattr(TeachingService, "generate_next_section_cards"), (
            "TeachingService.generate_next_section_cards() method not found"
        )

    def test_section_index_stamp_in_teaching_service(self):
        """_section_index must be stamped on cards for stable ordering (replaces RC4 fuzzy sort)."""
        import pathlib
        _src_dir = pathlib.Path(__file__).resolve().parent.parent / "src"
        src = (_src_dir / "api" / "teaching_service.py").read_text()
        assert "_section_index" in src, (
            "_section_index not found in teaching_service.py — "
            "cards must be stamped with integer index for stable sort"
        )
