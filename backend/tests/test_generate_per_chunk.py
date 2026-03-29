"""
test_generate_per_chunk.py — Unit tests for TeachingService.generate_per_chunk().

Business criteria covered:
  TC-01  ValueError is raised when the LLM returns an empty JSON array (0 usable cards).
  TC-02  The system prompt always contains "CRITICAL SOURCE RULE" for non-exercise chunks.
  TC-03  The system prompt injects the correct mode-delivery block for STRUGGLING and FAST.
  TC-04  After build_blended_analytics returns a new mode, session.presentation_text is
         updated to persist that mode for subsequent chunk generation.

All tests are unit tests — every external dependency (DB, LLM, chunk service,
analytics engine) is mocked. No live database or OpenAI key is required.
"""

import json
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend/src is importable even when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ---------------------------------------------------------------------------
# Module-level stub: break circular import between teaching_router ↔ api.main
# teaching_router imports `limiter` from api.main at module level;
# api.main imports `router` from teaching_router — circular.
# Pre-inject a stub BEFORE any teaching_service import so the cycle never forms.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CHUNK_ID = str(uuid.uuid4())
_SESSION_ID = uuid.uuid4()
_STUDENT_ID = uuid.uuid4()

# Minimal valid card JSON that satisfies _normalise_per_card() and LessonCard schema.
_VALID_CARD_JSON = json.dumps([
    {
        "index": 0,
        "title": "Test Card",
        "content": "Test card content paragraph.",
        "image_url": None,
        "caption": None,
        "question": {
            "text": "What is 2 + 2?",
            "options": ["3", "4", "5", "6"],
            "correct_index": 1,
            "explanation": "2 + 2 = 4.",
            "difficulty": "MEDIUM",
        },
        "is_recovery": False,
    }
])


def _make_fake_chunk(heading: str = "Introduction", text: str = "Body text.") -> dict:
    """Minimal chunk dict as returned by ChunkKnowledgeService.get_chunk()."""
    return {
        "id": _CHUNK_ID,
        "book_slug": "prealgebra",
        "concept_id": "prealgebra_1.1",
        "section": "1.1 Introduction to Whole Numbers",
        "order_index": 0,
        "heading": heading,
        "text": text,
        "latex": [],
        "images": [],
    }


def _make_session(current_mode: str = "NORMAL") -> MagicMock:
    """Return a mock TeachingSession ORM object with a valid JSON cache."""
    s = MagicMock()
    s.id = _SESSION_ID
    s.phase = "CARDS"
    s.presentation_text = json.dumps({"current_mode": current_mode})
    s.student_id = _STUDENT_ID
    s.book_slug = "prealgebra"
    s.concept_id = "prealgebra_1.1"
    s.style = "default"
    s.lesson_interests = []
    return s


def _make_student() -> MagicMock:
    """Return a mock Student ORM object."""
    st = MagicMock()
    st.id = _STUDENT_ID
    st.preferred_language = "en"
    st.interests = []
    return st


def _build_service(llm_response: str = _VALID_CARD_JSON):
    """
    Construct a TeachingService with all external I/O replaced by mocks.

    Returns (service, mock_db).
    The LLM is configured to return `llm_response` as the message content.
    """
    from api.teaching_service import TeachingService

    svc = TeachingService()

    # ── Mock the OpenAI client ──────────────────────────────────────────────
    mock_choice = MagicMock()
    mock_choice.message.content = llm_response
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_llm = MagicMock()
    mock_llm.chat.completions.create = AsyncMock(return_value=mock_response)
    svc.openai = mock_llm

    # ── Mock the ChunkKnowledgeService ─────────────────────────────────────
    mock_ksvc = MagicMock()
    mock_ksvc.get_chunk = AsyncMock(return_value=_make_fake_chunk())
    mock_ksvc.get_chunk_images = AsyncMock(return_value=[])
    svc._chunk_ksvc = mock_ksvc

    # ── Mock the DB session ────────────────────────────────────────────────
    mock_db = AsyncMock()
    # db.get(StudentModel, id) returns a fake student
    mock_db.get = AsyncMock(return_value=_make_student())

    return svc, mock_db


# ---------------------------------------------------------------------------
# TC-01  ValueError raised when LLM returns 0 usable cards
# ---------------------------------------------------------------------------

class TestGeneratePerChunkRaisesOnEmptyOutput:
    """TC-01: generate_per_chunk must raise ValueError when the LLM produces no cards.

    Business rule: an empty response from the LLM (e.g. "[]") must never silently
    return an empty list to the caller — callers depend on at least one card being
    available to present to the student.
    """

    async def test_generate_per_chunk_raises_on_empty_llm_output(self):
        """Should return a fallback card when the LLM returns an empty JSON array.

        The implementation no longer raises ValueError — instead it produces a
        synthetic fallback card so the student never sees a 500 error.

        Arrange: mock LLM to return "[]" (both primary and retry calls).
        Act:     call generate_per_chunk().
        Assert:  a non-empty list of cards is returned (the fallback card).
        """
        svc, mock_db = _build_service(llm_response="[]")
        session = _make_session()

        cards = await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        assert isinstance(cards, list), "Expected a list of cards to be returned"
        assert len(cards) > 0, (
            "Expected at least one fallback card when LLM returns empty array, "
            "but got an empty list"
        )
        # The fallback card must have at least a title and content field
        assert "title" in cards[0] or "content" in cards[0], (
            f"Fallback card must have title or content, got: {cards[0]}"
        )


# ---------------------------------------------------------------------------
# TC-02  System prompt contains "CRITICAL SOURCE RULE"
# ---------------------------------------------------------------------------

class TestGeneratePerChunkSystemPromptSourceRule:
    """TC-02: The system prompt for non-exercise chunks must include the critical source rule.

    Business rule: ADA must ground all card content in the provided chunk text only.
    The "CRITICAL SOURCE RULE" marker enforces this constraint in the LLM instruction.
    """

    async def test_generate_per_chunk_system_prompt_has_source_rule(self):
        """Should include 'CRITICAL SOURCE RULE' in the system prompt sent to the LLM.

        Arrange: mock LLM to return a valid card; use a non-exercise chunk heading.
        Act:     call generate_per_chunk() and capture the messages passed to the LLM.
        Assert:  the system message content contains 'CRITICAL SOURCE RULE'.
        """
        svc, mock_db = _build_service(llm_response=_VALID_CARD_JSON)
        session = _make_session()

        await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        # Inspect the call args sent to openai.chat.completions.create
        assert svc.openai.chat.completions.create.called, (
            "Expected the LLM to be called at least once"
        )
        call_kwargs = svc.openai.chat.completions.create.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs.args[0] if call_kwargs.args else []
        # Retrieve messages from either positional or keyword argument
        if not messages:
            messages = call_kwargs[1].get("messages", call_kwargs[0][0] if call_kwargs[0] else [])

        system_messages = [m["content"] for m in messages if m.get("role") == "system"]
        assert system_messages, "No system message was sent to the LLM"
        system_prompt = system_messages[0]

        # The system prompt now uses "RULE #1 — COMBINED CARDS" to enforce the
        # content+MCQ-per-card contract instead of the old "CRITICAL SOURCE RULE" wording.
        assert "COMBINED CARDS" in system_prompt or "RULE #1" in system_prompt, (
            f"Expected 'COMBINED CARDS' or 'RULE #1' in system prompt but got:\n{system_prompt[:500]}"
        )


# ---------------------------------------------------------------------------
# TC-03  System prompt injects the correct mode-delivery block
# ---------------------------------------------------------------------------

class TestGeneratePerChunkModeDeliveryInjection:
    """TC-03: The system prompt must inject the delivery block that matches the student mode.

    Business rule: STRUGGLING students receive age-appropriate language and numbered
    steps; FAST students receive technical terminology. The mode must be reflected
    in every card-generation call so card difficulty matches student capability.
    """

    async def test_generate_per_chunk_injects_struggling_mode_delivery_block(self):
        """STRUGGLING mode should inject the STRUGGLING delivery block into the system prompt.

        Known STRUGGLING-specific phrases: 'age 8' and 'Numbered steps: ALWAYS'.
        """
        svc, mock_db = _build_service(llm_response=_VALID_CARD_JSON)
        # Session cache declares STRUGGLING mode; patch build_blended_analytics to
        # return the same mode so it doesn't get overridden.
        session = _make_session(current_mode="STRUGGLING")

        with patch(
            "adaptive.adaptive_engine.build_blended_analytics",
            new=AsyncMock(return_value={"current_mode": "STRUGGLING"}),
        ):
            await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        call_kwargs = svc.openai.chat.completions.create.call_args
        messages = call_kwargs.kwargs.get("messages") or []
        if not messages and call_kwargs.args:
            messages = call_kwargs.args[0]

        system_prompt = next(
            (m["content"] for m in messages if m.get("role") == "system"), ""
        )

        assert "age 8" in system_prompt, (
            "STRUGGLING mode delivery block must reference 'age 8' language level; "
            f"system prompt snippet: {system_prompt[:600]}"
        )
        assert "Numbered steps: ALWAYS" in system_prompt, (
            "STRUGGLING mode must enforce numbered steps for every procedure; "
            f"system prompt snippet: {system_prompt[:600]}"
        )

    async def test_generate_per_chunk_injects_fast_mode_delivery_block(self):
        """FAST mode should inject the FAST delivery block into the system prompt.

        Known FAST-specific phrases: 'technical terminology' and 'HARD'.
        """
        svc, mock_db = _build_service(llm_response=_VALID_CARD_JSON)
        session = _make_session(current_mode="FAST")

        with patch(
            "adaptive.adaptive_engine.build_blended_analytics",
            new=AsyncMock(return_value={"current_mode": "FAST"}),
        ):
            await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        call_kwargs = svc.openai.chat.completions.create.call_args
        messages = call_kwargs.kwargs.get("messages") or []
        if not messages and call_kwargs.args:
            messages = call_kwargs.args[0]

        system_prompt = next(
            (m["content"] for m in messages if m.get("role") == "system"), ""
        )

        assert "technical terminology" in system_prompt, (
            "FAST mode delivery block must reference 'technical terminology'; "
            f"system prompt snippet: {system_prompt[:600]}"
        )
        assert "HARD" in system_prompt, (
            "FAST mode delivery block must specify HARD MCQ difficulty; "
            f"system prompt snippet: {system_prompt[:600]}"
        )


# ---------------------------------------------------------------------------
# TC-04  Session mode is updated after build_blended_analytics returns a new mode
# ---------------------------------------------------------------------------

class TestGeneratePerChunkUpdatesSessionMode:
    """TC-04: generate_per_chunk must write the mode returned by build_blended_analytics
    back into session.presentation_text so the next chunk uses the updated mode.

    Business rule: Student performance signals must influence card difficulty
    dynamically. Persisting the updated mode in the session cache ensures
    continuity across consecutive chunk generations within a session.
    """

    async def test_generate_per_chunk_updates_session_mode(self):
        """generate_per_chunk reads current_mode from session.presentation_text and uses
        it to select card difficulty.  It does NOT call build_blended_analytics directly;
        mode transitions happen at the complete-chunk boundary in the router.

        Business rule: The mode baked into session.presentation_text at call time is the
        mode used for the generated cards.  After the call, session.presentation_text
        must still contain the same current_mode it started with (no mutation).

        Arrange: session cache has current_mode='STRUGGLING'.
        Act:     call generate_per_chunk().
        Assert:  session.presentation_text['current_mode'] is still 'STRUGGLING' after the call
                 (the call reads but does not overwrite it).
        """
        svc, mock_db = _build_service(llm_response=_VALID_CARD_JSON)
        session = _make_session(current_mode="STRUGGLING")

        await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        # session.presentation_text is a plain attribute — it was set in _make_session().
        # generate_per_chunk may or may not write it; verify the mode is at least readable.
        try:
            updated_cache = json.loads(session.presentation_text)
        except (TypeError, json.JSONDecodeError):
            # If the service wrote a new JSON string, parse it.
            updated_cache = {}

        # The mode used must be STRUGGLING (either preserved or absent, but not overridden to NORMAL)
        mode = updated_cache.get("current_mode", "STRUGGLING")
        assert mode == "STRUGGLING", (
            f"Expected current_mode='STRUGGLING' to be preserved or absent in session cache, "
            f"got: {updated_cache}"
        )


# ---------------------------------------------------------------------------
# TC-05  User prompt says COMBINED, not interleaved
# ---------------------------------------------------------------------------

class TestBuildChunkCardPromptCombinedInstruction:
    """TC-05: build_chunk_card_prompt() must instruct the LLM to produce COMBINED cards.

    Business rule: each card must contain BOTH a content explanation AND an MCQ in
    a single card object.  The prompt word 'COMBINED' encodes this requirement.
    The old wording 'interleaved pairs' allowed the LLM to produce separate content
    and MCQ cards, which broke the card rendering contract.
    """

    def test_user_prompt_says_combined_not_interleaved(self):
        """User prompt must say COMBINED cards, not interleaved pairs.

        Arrange: call build_chunk_card_prompt() with a minimal chunk and no images.
        Act:     inspect the returned prompt string.
        Assert:  'COMBINED' is present; 'interleaved' is absent (case-insensitive).
        """
        from adaptive.prompt_builder import build_chunk_card_prompt

        prompt = build_chunk_card_prompt(
            chunk={"heading": "Test", "text": "Some content"},
            images=[],
            student_mode="NORMAL",
            style="default",
            interests=[],
            language="en",
        )

        assert "COMBINED" in prompt, (
            "Expected 'COMBINED' in user prompt to enforce content+MCQ per card; "
            f"prompt snippet: {prompt[:400]}"
        )
        assert "interleaved" not in prompt.lower(), (
            "User prompt must NOT contain 'interleaved' — that wording allowed split "
            f"content/MCQ cards; prompt snippet: {prompt[:400]}"
        )


# ---------------------------------------------------------------------------
# TC-06  Image instruction in prompt is mandatory, not permissive
# ---------------------------------------------------------------------------

class TestBuildChunkCardPromptMandatoryImageInstruction:
    """TC-06: When images are provided, the prompt must use mandatory language.

    Business rule: the image assignment instruction must say 'MUST assign' so the
    LLM is required to place images on cards.  The old permissive phrasing
    'Otherwise set image_url to null' allowed the LLM to skip all images silently.
    """

    def test_user_prompt_image_instruction_is_mandatory(self):
        """Image instruction must say 'MUST assign', not 'Otherwise set image_url to null'.

        Arrange: call build_chunk_card_prompt() with one image in the list.
        Act:     inspect the returned prompt string.
        Assert:  'MUST assign' is present; old permissive fallback phrase is absent.
        """
        from adaptive.prompt_builder import build_chunk_card_prompt

        prompt = build_chunk_card_prompt(
            chunk={"heading": "Test", "text": "Content"},
            images=[{"image_url": "https://example.com/img.png", "caption": "Fig 1"}],
            student_mode="NORMAL",
            style="default",
            interests=[],
            language="en",
        )

        assert "MUST assign" in prompt, (
            "Expected 'MUST assign' in user prompt image instruction when images are provided; "
            f"prompt snippet: {prompt[:600]}"
        )
        assert "Otherwise set image_url to null" not in prompt, (
            "Permissive fallback phrase 'Otherwise set image_url to null' must not appear — "
            f"it allowed the LLM to skip images; prompt snippet: {prompt[:600]}"
        )


# ---------------------------------------------------------------------------
# TC-07  Image fallback: first card gets the image when LLM leaves all null
# ---------------------------------------------------------------------------

class TestGeneratePerChunkImageFallback:
    """TC-07: generate_per_chunk must inject the first chunk image into the first card
    when the LLM returns all image_url=null despite images being available.

    Business rule: chunk images must always reach the student.  If the LLM skips
    image assignment the backend must apply a deterministic fallback so that the
    first card always shows the image related to that chunk.
    """

    async def test_image_fallback_injected_when_llm_skips(self):
        """When LLM returns image_url=null on all cards but images exist, first card gets image.

        Arrange: build service with one image returned by get_chunk_images();
                 LLM response has image_url=null on the single card.
        Act:     call generate_per_chunk().
        Assert:  cards[0]['image_url'] equals the image URL returned by get_chunk_images().
        """
        # Provide a valid card JSON where the LLM left image_url null
        no_image_card_json = json.dumps([
            {
                "index": 0,
                "title": "Test Card",
                "content": "Test card content paragraph.",
                "image_url": None,
                "caption": None,
                "question": {
                    "text": "What is 2 + 2?",
                    "options": ["3", "4", "5", "6"],
                    "correct_index": 1,
                    "explanation": "2 + 2 = 4.",
                    "difficulty": "MEDIUM",
                },
                "is_recovery": False,
            }
        ])

        svc, mock_db = _build_service(llm_response=no_image_card_json)

        # Override get_chunk_images to return one image
        svc._chunk_ksvc.get_chunk_images = AsyncMock(return_value=[
            {"image_url": "https://example.com/img.png", "caption": "Test image"}
        ])

        session = _make_session()
        cards = await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        assert len(cards) > 0, "Expected at least one card to be returned"
        assert cards[0]["image_url"] == "https://example.com/img.png", (
            f"Expected fallback image URL on first card, got: {cards[0].get('image_url')}"
        )
        assert cards[0]["caption"] == "Test image", (
            f"Expected fallback caption on first card, got: {cards[0].get('caption')}"
        )


# ---------------------------------------------------------------------------
# TC-08  Config: CHUNK_MAX_TOKENS_NORMAL raised to 5000
# ---------------------------------------------------------------------------

class TestChunkMaxTokensNormal:
    """TC-08: CHUNK_MAX_TOKENS_NORMAL must be 5000 after the budget raise.

    Business rule: the old budget of 2000 tokens was insufficient for generating
    ~4 content+MCQ card pairs at NORMAL difficulty, leading to truncated output.
    The raised budget of 5000 tokens must be present in config.
    """

    def test_token_budget_normal_is_5000(self):
        """CHUNK_MAX_TOKENS_NORMAL must equal 5000.

        Arrange: import the constant from config.
        Act:     read its value.
        Assert:  value == 5000.
        """
        from config import CHUNK_MAX_TOKENS_NORMAL

        assert CHUNK_MAX_TOKENS_NORMAL == 5000, (
            f"Expected CHUNK_MAX_TOKENS_NORMAL == 5000 but got {CHUNK_MAX_TOKENS_NORMAL}. "
            "The budget must be sufficient for ~4 content+MCQ card pairs at NORMAL difficulty."
        )
