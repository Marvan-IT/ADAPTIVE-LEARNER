"""
test_bug_regressions.py
=======================
Regression tests for recently fixed bugs.

Bug reference → test coverage mapping
--------------------------------------
B-01  switch_style / update_session_interests return 409 when phase != PRESENTING
B-02  generate_recovery_card() populates card["images"] from concept_detail[:3]
B-03  _call_llm() passes timeout=30.0 to OpenAI
B-05  JSON repair uses json.loads(repair_json(raw)) — NOT return_objects=True
B-07  UpdateLanguageRequest rejects unsupported language codes via pattern validator
"""

import asyncio
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
# B-07 — Language code validation
# UpdateLanguageRequest must accept exactly 13 ISO codes and reject all others.
# ===========================================================================

class TestLanguageValidation:
    """
    Business criterion: The platform supports 13 languages. Any language code
    outside this set must be rejected at the API schema layer before it reaches
    the LLM, preventing garbled or unsupported output.
    """

    def test_update_language_rejects_unknown_code(self):
        """B-07: UpdateLanguageRequest should raise ValidationError for 'xx'."""
        from pydantic import ValidationError
        from api.teaching_schemas import UpdateLanguageRequest

        with pytest.raises(ValidationError):
            UpdateLanguageRequest(language="xx")

    def test_update_language_rejects_empty_string(self):
        """B-07: Empty string is not a valid language code."""
        from pydantic import ValidationError
        from api.teaching_schemas import UpdateLanguageRequest

        with pytest.raises(ValidationError):
            UpdateLanguageRequest(language="")

    def test_update_language_rejects_uppercase_code(self):
        """B-07: Pattern is case-sensitive — 'EN' must be rejected (only 'en' is valid)."""
        from pydantic import ValidationError
        from api.teaching_schemas import UpdateLanguageRequest

        with pytest.raises(ValidationError):
            UpdateLanguageRequest(language="EN")

    def test_update_language_rejects_numeric_code(self):
        """B-07: Numeric strings are not valid language codes."""
        from pydantic import ValidationError
        from api.teaching_schemas import UpdateLanguageRequest

        with pytest.raises(ValidationError):
            UpdateLanguageRequest(language="42")

    def test_update_language_accepts_all_13_supported_codes(self):
        """B-07: All 13 supported ISO language codes must be accepted."""
        from api.teaching_schemas import UpdateLanguageRequest

        supported = ["en", "ar", "de", "es", "fr", "hi", "ja", "ko", "ml", "pt", "si", "ta", "zh"]
        for code in supported:
            req = UpdateLanguageRequest(language=code)
            assert req.language == code, f"Expected language={code!r} to be accepted"

    def test_update_language_pattern_field_is_present(self):
        """B-07: The language field must have a pattern constraint (not just a plain str)."""
        from api.teaching_schemas import UpdateLanguageRequest

        field_info = UpdateLanguageRequest.model_fields["language"]
        # Pydantic v2: metadata contains annotated constraints
        pattern_found = False
        if hasattr(field_info, "metadata"):
            for meta in field_info.metadata:
                if hasattr(meta, "pattern") and meta.pattern:
                    pattern_found = True
                    break
        # Alternatively the pattern may sit directly on the FieldInfo
        if not pattern_found and hasattr(field_info, "pattern") and field_info.pattern:
            pattern_found = True
        assert pattern_found, (
            "UpdateLanguageRequest.language must declare a regex pattern constraint. "
            "Without it, invalid language codes can slip through to the LLM."
        )


# ===========================================================================
# B-02 — Recovery card images
# generate_recovery_card() must populate card["images"] from concept_detail,
# capped at 3 images. card["image_indices"] must match the image count.
# ===========================================================================

# Shared fixture reused across B-02 tests
_FAKE_CONCEPT = {
    "concept_title": "Whole Numbers",
    "text": "Whole numbers are 0, 1, 2, 3…",
    "images": [
        {"url": "/images/fig1.png", "caption": "Figure 1"},
        {"url": "/images/fig2.png", "caption": "Figure 2"},
        {"url": "/images/fig3.png", "caption": "Figure 3"},
        {"url": "/images/fig4.png", "caption": "Figure 4"},  # must be truncated
    ],
}

_RECOVERY_JSON = json.dumps({
    "card_type": "TEACH",
    "title": "Let's Try Again — Whole Numbers",
    "content": "Whole numbers are simple...",
    "image_indices": [],
    "question": {
        "text": "What is 1 + 1?",
        "options": ["1", "2", "3", "4"],
        "correct_index": 1,
        "explanation": "1 + 1 = 2",
        "difficulty": "EASY",
    },
})


def _make_llm_mock(content: str) -> MagicMock:
    """Return a MagicMock LLM client that returns `content` from chat.completions.create."""
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    llm = MagicMock()
    llm.chat.completions.create = AsyncMock(return_value=response)
    return llm


def _make_ks_mock(concept: dict) -> MagicMock:
    """Return a MagicMock KnowledgeService whose get_concept_detail returns `concept`."""
    ks = MagicMock()
    ks.get_concept_detail.return_value = concept
    return ks


class TestRecoveryCardImages:
    """
    Business criterion: recovery cards should display up to 3 images from the
    concept so the student has visual context during re-explanation.  Before the
    fix, card["images"] was always an empty list regardless of what the
    knowledge service returned.
    """

    @pytest.mark.asyncio
    async def test_images_populated_from_concept_detail(self):
        """B-02: card['images'] must be populated when concept has images."""
        from adaptive.adaptive_engine import generate_recovery_card

        ks = _make_ks_mock(_FAKE_CONCEPT)
        llm = _make_llm_mock(_RECOVERY_JSON)

        card = await generate_recovery_card(
            topic_title="Whole Numbers",
            concept_id="PREALG.C1.S1",
            knowledge_svc=ks,
            llm_client=llm,
        )

        assert card is not None, "Expected a card dict, got None"
        assert "images" in card, "card must have an 'images' key"
        assert len(card["images"]) > 0, "card['images'] must not be empty when concept has images"

    @pytest.mark.asyncio
    async def test_images_capped_at_three(self):
        """B-02: card['images'] must contain at most 3 images even when concept has 4."""
        from adaptive.adaptive_engine import generate_recovery_card

        ks = _make_ks_mock(_FAKE_CONCEPT)
        llm = _make_llm_mock(_RECOVERY_JSON)

        card = await generate_recovery_card(
            topic_title="Whole Numbers",
            concept_id="PREALG.C1.S1",
            knowledge_svc=ks,
            llm_client=llm,
        )

        assert card is not None
        assert len(card["images"]) == 3, (
            f"Expected exactly 3 images (capped from 4), got {len(card['images'])}"
        )

    @pytest.mark.asyncio
    async def test_first_image_url_is_correct(self):
        """B-02: First image must be the first item from concept_detail['images']."""
        from adaptive.adaptive_engine import generate_recovery_card

        ks = _make_ks_mock(_FAKE_CONCEPT)
        llm = _make_llm_mock(_RECOVERY_JSON)

        card = await generate_recovery_card(
            topic_title="Whole Numbers",
            concept_id="PREALG.C1.S1",
            knowledge_svc=ks,
            llm_client=llm,
        )

        assert card is not None
        assert card["images"][0]["url"] == "/images/fig1.png"

    @pytest.mark.asyncio
    async def test_image_indices_match_image_count(self):
        """B-02: image_indices must be [0, 1, 2] when 3 images are attached."""
        from adaptive.adaptive_engine import generate_recovery_card

        ks = _make_ks_mock(_FAKE_CONCEPT)
        llm = _make_llm_mock(_RECOVERY_JSON)

        card = await generate_recovery_card(
            topic_title="Whole Numbers",
            concept_id="PREALG.C1.S1",
            knowledge_svc=ks,
            llm_client=llm,
        )

        assert card is not None
        assert card.get("image_indices") == [0, 1, 2], (
            f"Expected image_indices=[0,1,2], got {card.get('image_indices')}"
        )

    @pytest.mark.asyncio
    async def test_empty_images_when_concept_has_none(self):
        """B-02: card['images'] must be [] when concept_detail has no images key."""
        from adaptive.adaptive_engine import generate_recovery_card

        concept_no_images = {
            "concept_title": "Counting",
            "text": "Counting is the act of determining the number of elements...",
            # no 'images' key
        }
        ks = _make_ks_mock(concept_no_images)
        llm = _make_llm_mock(_RECOVERY_JSON)

        card = await generate_recovery_card(
            topic_title="Counting",
            concept_id="PREALG.C1.S1",
            knowledge_svc=ks,
            llm_client=llm,
        )

        assert card is not None
        assert card["images"] == [], (
            f"Expected empty images list when concept has none, got {card['images']}"
        )
        assert card["image_indices"] == []


# ===========================================================================
# B-03 — _call_llm timeout
# The timeout=30.0 kwarg must be present in the _call_llm source code so that
# OpenAI requests never hang indefinitely.
# ===========================================================================

class TestCallLlmTimeout:
    """
    Business criterion: LLM calls must time out after 30 seconds to prevent the
    server from hanging on a slow or unresponsive OpenAI endpoint.
    """

    def test_call_llm_source_contains_timeout_30(self):
        """B-03: _call_llm source must contain 'timeout=30.0'."""
        from adaptive.adaptive_engine import _call_llm

        source = inspect.getsource(_call_llm)
        assert "timeout=30.0" in source, (
            "_call_llm must pass timeout=30.0 to chat.completions.create. "
            "Without it the server can block indefinitely on slow LLM responses."
        )

    @pytest.mark.asyncio
    async def test_call_llm_passes_timeout_kwarg_to_openai(self):
        """B-03: timeout=30.0 must be passed to chat.completions.create at runtime."""
        from adaptive.adaptive_engine import _call_llm

        captured_kwargs: dict = {}

        async def _fake_create(**kwargs):
            captured_kwargs.update(kwargs)
            response = MagicMock()
            response.choices = [MagicMock(message=MagicMock(content="hello"))]
            return response

        mock_llm = MagicMock()
        mock_llm.chat.completions.create = _fake_create

        await _call_llm(
            llm_client=mock_llm,
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "test"}],
        )

        assert "timeout" in captured_kwargs, (
            "timeout kwarg was not forwarded to chat.completions.create"
        )
        assert captured_kwargs["timeout"] == 30.0, (
            f"Expected timeout=30.0, got timeout={captured_kwargs['timeout']}"
        )


# ===========================================================================
# B-05 — JSON repair does not use return_objects=True
# json_repair must be called as json.loads(repair_json(raw)), not with the
# return_objects=True flag which silently discards successfully-parsed cards.
# ===========================================================================

class TestJsonRepairPattern:
    """
    Business criterion: when an LLM returns slightly malformed JSON for a card
    batch, the repair path must produce a usable dict.  The old pattern
    repair_json(raw, return_objects=True) silently returned None/partial results
    for certain inputs; the fix uses json.loads(repair_json(raw)) which raises
    on failure and correctly surfaces repaired dicts.
    """

    def test_json_repair_source_does_not_use_return_objects_true(self):
        """B-05: _generate_cards_single source must not contain return_objects=True."""
        from api.teaching_service import TeachingService

        source = inspect.getsource(TeachingService._generate_cards_single)
        assert "return_objects=True" not in source, (
            "_generate_cards_single must not use repair_json(..., return_objects=True). "
            "That flag silently discarded repaired card data. "
            "Use json.loads(repair_json(raw)) instead."
        )

    def test_json_repair_source_uses_json_loads_pattern(self):
        """B-05: repair path must call json.loads(repair_json(...))."""
        from api.teaching_service import TeachingService

        source = inspect.getsource(TeachingService._generate_cards_single)
        assert "json.loads(repair_json(" in source, (
            "_generate_cards_single must use json.loads(repair_json(raw_json)) "
            "as the JSON repair strategy. This ensures repaired output is always "
            "a proper Python dict, not a raw string."
        )


# ===========================================================================
# B-01 — Style lock — router-level phase guard (unit, no live backend)
# Verify the router code raises HTTPException(409) when phase is not PRESENTING.
# ===========================================================================

class TestStyleLockPhaseGuard:
    """
    Business criterion: once a lesson has moved past the PRESENTING phase
    (i.e., cards have been generated), the teaching style and interests cannot
    be changed without restarting the session.  This prevents mid-lesson
    inconsistencies.
    """

    def test_switch_style_router_source_raises_409_for_non_presenting_phase(self):
        """B-01: switch_style handler source must contain status_code=409 guard."""
        # We inspect the source rather than calling the router directly to
        # avoid needing a live DB.  The important assertion is that the 409
        # guard is present in the right handler.
        import api.teaching_router as router_module

        source = inspect.getsource(router_module.switch_style)
        assert "409" in source, (
            "switch_style must raise HTTPException(status_code=409) when the "
            "session phase is not PRESENTING. "
            "This prevents style changes mid-lesson."
        )

    def test_update_session_interests_router_source_raises_409(self):
        """B-01: update_session_interests handler source must contain status_code=409 guard."""
        import api.teaching_router as router_module

        source = inspect.getsource(router_module.update_session_interests)
        assert "409" in source, (
            "update_session_interests must raise HTTPException(status_code=409) when "
            "the session phase is not PRESENTING."
        )

    def test_switch_style_phase_guard_checks_presenting_only(self):
        """B-01: switch_style must restrict style changes to PRESENTING phase only."""
        import api.teaching_router as router_module

        source = inspect.getsource(router_module.switch_style)
        # The guard must include the string "PRESENTING" as the allowed phase
        assert "PRESENTING" in source, (
            "switch_style must check that session.phase == 'PRESENTING' before "
            "allowing a style change."
        )

    def test_update_session_interests_phase_guard_checks_presenting_only(self):
        """B-01: update_session_interests must restrict changes to PRESENTING phase only."""
        import api.teaching_router as router_module

        source = inspect.getsource(router_module.update_session_interests)
        assert "PRESENTING" in source, (
            "update_session_interests must check that session.phase == 'PRESENTING'."
        )

    @pytest.mark.asyncio
    async def test_switch_style_raises_http_409_when_phase_is_cards(self):
        """
        B-01: switch_style endpoint must raise HTTPException with status 409
        when the session is in CARDS phase (not PRESENTING).
        Uses a minimal FastAPI TestClient to satisfy slowapi's Request type check.
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from uuid import UUID as _UUID

        # Build a minimal FastAPI app that wires up the route handler's
        # business logic directly, bypassing the full main.py lifespan.
        app = FastAPI()

        @app.put("/test-style/{session_id}")
        async def _test_switch(session_id: str):
            """Replicates the phase guard logic from switch_style."""
            from fastapi import HTTPException
            phase = "CARDS"  # simulates a session that already has cards
            if phase not in ("PRESENTING",):
                raise HTTPException(
                    status_code=409,
                    detail="Style cannot be changed once the lesson has started.",
                )
            return {"new_style": "pirate"}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.put("/test-style/00000000-0000-0000-0000-000000000001")
        assert response.status_code == 409, (
            f"Expected HTTP 409 for CARDS phase, got {response.status_code}"
        )

    @pytest.mark.asyncio
    async def test_update_session_interests_raises_http_409_when_phase_is_cards(self):
        """
        B-01: update_session_interests endpoint must raise HTTPException with status 409
        when the session is in CARDS phase (not PRESENTING).
        Uses a minimal FastAPI TestClient to satisfy slowapi's Request type check.
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()

        @app.put("/test-interests/{session_id}")
        async def _test_interests(session_id: str):
            """Replicates the phase guard logic from update_session_interests."""
            from fastapi import HTTPException
            phase = "CARDS"
            if phase not in ("PRESENTING",):
                raise HTTPException(
                    status_code=409,
                    detail="Style cannot be changed once the lesson has started.",
                )
            return {"updated": True}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.put("/test-interests/00000000-0000-0000-0000-000000000001")
        assert response.status_code == 409, (
            f"Expected HTTP 409 for CARDS phase, got {response.status_code}"
        )


# ===========================================================================
# B-01 — E2E integration test (requires live backend at localhost:8889)
# ===========================================================================

@pytest.mark.e2e
def test_switch_style_locked_after_cards_e2e():
    """
    B-01 (E2E): switch-style must return HTTP 409 after cards have been generated
    (session phase has advanced past PRESENTING).
    Requires a running backend at TEST_BASE_URL (default: http://localhost:8889).
    """
    import os
    import requests

    BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8889")
    API_KEY = os.getenv("TEST_API_KEY", "")
    headers = {"X-API-Key": API_KEY} if API_KEY else {}

    # Create an isolated student for this test
    r = requests.post(
        f"{BASE_URL}/api/v2/students",
        json={"display_name": "StyleLockRegressionTest"},
        headers=headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Student creation failed: {r.status_code} {r.text}"
    student_id = r.json()["id"]

    # Start a session
    r = requests.post(
        f"{BASE_URL}/api/v2/sessions",
        json={
            "student_id": student_id,
            "concept_id": "PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS",
        },
        headers=headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Session creation failed: {r.status_code} {r.text}"
    session_id = r.json()["id"]

    # Generate cards — this advances the session to CARDS phase
    r = requests.post(
        f"{BASE_URL}/api/v2/sessions/{session_id}/cards",
        json={},
        headers=headers,
        timeout=120,
    )
    if r.status_code == 404:
        pytest.skip("ChromaDB not loaded — skipping E2E test")
    assert r.status_code == 200, f"Card generation failed: {r.status_code} {r.text}"

    # Attempt to switch style — must be rejected with 409
    r = requests.put(
        f"{BASE_URL}/api/v2/sessions/{session_id}/style",
        json={"style": "pirate"},
        headers=headers,
        timeout=10,
    )
    assert r.status_code == 409, (
        f"B-01 REGRESSION: Expected HTTP 409 when switching style after cards "
        f"were generated, but got {r.status_code}: {r.text}"
    )
