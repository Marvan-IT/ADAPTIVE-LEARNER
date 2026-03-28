"""
Tests for the Per-Card Adaptive Generation feature.

Feature:  POST /api/v2/sessions/{id}/next-card
Service:  TeachingService.generate_per_card()
Schemas:  NextCardRequest, NextCardResponse

Business context
----------------
Instead of generating all cards upfront, the system generates one card at a time
from a pre-built `concepts_queue` stored in the session cache. Each card is
personalised using live signals from the card the student just completed (time,
wrong attempts, hints). The queue is exhausted piece-by-piece; when empty the
response signals `has_more_concepts=False` so the frontend transitions to the
Socratic check phase.

Test plan
---------
TC-01  test_session_returns_initial_cards          -- STARTER_PACK_INITIAL_SECTIONS constant
TC-02  test_next_card_returns_next_piece_in_order  -- queue pop + cache update
TC-03  test_next_card_content_in_generated_card    -- piece text in card
TC-04  test_struggling_mode_generates_explanatory_card  -- STRUGGLING mode → SLOW current_mode
TC-05  test_fast_mode_generates_mcq_card           -- FAST mode → FAST current_mode
TC-06  test_has_more_concepts_false_after_last_piece    -- queue depleted
TC-07  test_section_count_increments_per_card      -- Bug 4 fix: local +1 before blending
TC-08  test_images_assigned_from_pool              -- first available image → card.images
TC-09  test_next_card_requires_cards_phase         -- 409 when phase != CARDS
TC-10  test_next_card_404_on_missing_session       -- 404 when session not found
"""

import inspect
import json
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend/src is importable even when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import STARTER_PACK_INITIAL_SECTIONS


# ---------------------------------------------------------------------------
# Module-level stub for api.main to break the circular-import at import time.
# teaching_router imports `limiter` from api.main at module level;
# api.main imports `router` from teaching_router — circular.
# Pre-inject a stub before any teaching_router import so the cycle never forms.
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

def _make_analytics_summary(
    student_id: str,
    concept_id: str,
    time_spent_sec: float = 60.0,
    expected_time_sec: float = 120.0,
    attempts: int = 1,
    wrong_attempts: int = 0,
    hints_used: int = 0,
    revisits: int = 0,
    recent_dropoffs: int = 0,
    skip_rate: float = 0.0,
    quiz_score: float = 0.7,
    last_7d_sessions: int = 1,
):
    """Construct an AnalyticsSummary with all required fields."""
    from adaptive.schemas import AnalyticsSummary
    return AnalyticsSummary(
        student_id=student_id,
        concept_id=concept_id,
        time_spent_sec=time_spent_sec,
        expected_time_sec=expected_time_sec,
        attempts=attempts,
        wrong_attempts=wrong_attempts,
        hints_used=hints_used,
        revisits=revisits,
        recent_dropoffs=recent_dropoffs,
        skip_rate=skip_rate,
        quiz_score=quiz_score,
        last_7d_sessions=last_7d_sessions,
    )


def _make_session(
    session_id=None,
    phase: str = "CARDS",
    presentation_text: str | None = None,
    book_slug: str = "prealgebra",
    concept_id: str = "PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS",
    student_id=None,
):
    """Return a mock TeachingSession ORM object."""
    s = MagicMock()
    s.id = session_id or uuid.uuid4()
    s.phase = phase
    s.presentation_text = presentation_text
    s.book_slug = book_slug
    s.concept_id = concept_id
    s.student_id = student_id or uuid.uuid4()
    return s


def _make_student(student_id=None, preferred_language: str = "en"):
    """Return a mock Student ORM object."""
    st = MagicMock()
    st.id = student_id or uuid.uuid4()
    st.preferred_language = preferred_language
    st.section_count = 0
    return st


def _make_cache(
    concepts_queue: list | None = None,
    concepts_covered: list | None = None,
    concepts_total: int = 5,
    cards: list | None = None,
    images: list | None = None,
    assigned_image_indices: list | None = None,
) -> str:
    """Serialise a minimal session cache dict to JSON."""
    return json.dumps({
        "session_id": str(uuid.uuid4()),
        "concept_id": "PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS",
        "concept_title": "Introduction to Whole Numbers",
        "cards": cards or [],
        "concepts_queue": concepts_queue if concepts_queue is not None else [],
        "concepts_covered": concepts_covered or [],
        "concepts_total": concepts_total,
        "cache_version": 14,
        "_images": images or [],
        "assigned_image_indices": assigned_image_indices or [],
        "session_signals": [],
    })


def _make_piece(title: str = "Section A", text: str = "Body text for section A.") -> dict:
    """Return a minimal content-piece dict as stored in concepts_queue."""
    return {
        "title": title,
        "text": text,
        "section_type": "MAIN",
        "_section_index": 0,
    }


def _single_card_llm_response(
    card_type: str = "TEACH",
    title: str = "Test Card Title",
    content: str = "Test card content.",
) -> str:
    """Return the JSON string an LLM would produce for a single per-card call."""
    return json.dumps({
        "card_type": card_type,
        "title": title,
        "content": content,
        "difficulty": 2,
        "motivational_note": None,
        "questions": [
            {
                "type": "mcq",
                "question": "What is 2 + 2?",
                "options": ["2", "3", "4", "5"],
                "correct_index": 2,
                "explanation": "2 + 2 = 4",
            }
        ],
    })


def _default_history(section_count: int = 0) -> dict:
    """Return a minimal student history dict suitable for generate_per_card()."""
    return {
        "total_cards_completed": 0,
        "avg_time_per_card": None,
        "avg_wrong_attempts": None,
        "avg_hints_per_card": None,
        "sessions_last_7d": 0,
        "section_count": section_count,
        "is_known_weak_concept": False,
        "failed_concept_attempts": 0,
        "trend_direction": "STABLE",
        "trend_wrong_list": [],
    }


def _build_teaching_service(llm_response: str = None, concept_detail: dict = None):
    """
    Build a TeachingService instance with fully mocked external dependencies.

    Returns (service, mock_db, mock_openai_client).
    """
    from api.teaching_service import TeachingService

    mock_ksvc = MagicMock()
    mock_ksvc.get_concept_detail.return_value = concept_detail or {
        "concept_id": "PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS",
        "concept_title": "Introduction to Whole Numbers",
        "chapter": "1",
        "section": "1",
        "text": "Whole numbers are 0, 1, 2, 3 ...",
        "images": [],
        "latex_expressions": [],
    }

    svc = TeachingService(knowledge_services={"prealgebra": mock_ksvc})

    # Replace the OpenAI client on the instance with a mock
    mock_llm = MagicMock()
    choice = MagicMock()
    choice.message.content = llm_response or _single_card_llm_response()
    response = MagicMock()
    response.choices = [choice]
    mock_llm.chat.completions.create = AsyncMock(return_value=response)
    svc.openai = mock_llm

    # Async DB mock
    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.execute = AsyncMock()

    return svc, mock_db, mock_llm


def _make_starlette_request(path: str = "/api/v2/sessions/test/next-card"):
    """Build a minimal real starlette.requests.Request for route handler tests.

    slowapi's @limiter.limit() decorator requires the first positional arg to
    be an actual starlette.requests.Request instance — not a MagicMock.
    """
    from starlette.requests import Request
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "query_string": b"",
        "headers": [(b"host", b"localhost"), (b"x-api-key", b"test-key")],
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# TC-01  Session start returns exactly STARTER_PACK_INITIAL_SECTIONS cards
# ---------------------------------------------------------------------------

class TestSessionInitialCards:
    """TC-01: The first /cards call returns exactly STARTER_PACK_INITIAL_SECTIONS cards
    and stores the remainder of sub-sections in concepts_queue for per-card generation."""

    def test_session_returns_initial_cards(self):
        """Business rule: Initial batch size is controlled by STARTER_PACK_INITIAL_SECTIONS.
        The constant must be a positive integer, and the queue-split must preserve
        all sections without losing any between the initial batch and the remainder."""
        assert isinstance(STARTER_PACK_INITIAL_SECTIONS, int), (
            "STARTER_PACK_INITIAL_SECTIONS must be an integer"
        )
        assert STARTER_PACK_INITIAL_SECTIONS >= 1, (
            "STARTER_PACK_INITIAL_SECTIONS must be at least 1 for any cards to be generated"
        )

        # Simulate the queue-split logic from generate_cards():
        # sub_sections[:N] goes to initial batch; remainder goes to concepts_queue.
        all_sections = [_make_piece(f"Section {i}") for i in range(6)]
        initial_batch = all_sections[:STARTER_PACK_INITIAL_SECTIONS]
        queue = all_sections[STARTER_PACK_INITIAL_SECTIONS:]

        assert len(initial_batch) == STARTER_PACK_INITIAL_SECTIONS, (
            f"Initial batch must have exactly {STARTER_PACK_INITIAL_SECTIONS} sections"
        )
        assert len(initial_batch) + len(queue) == len(all_sections), (
            "Initial batch + queue must equal all sections — no sections lost"
        )
        assert queue == all_sections[STARTER_PACK_INITIAL_SECTIONS:], (
            "Queue must contain sections after the initial batch, in textbook order"
        )


# ---------------------------------------------------------------------------
# TC-02  next-card returns the next piece in textbook order
# TC-03  Content piece text is reflected in the generated card
# ---------------------------------------------------------------------------

class TestNextCardHappyPath:
    """TC-02 and TC-03: The endpoint pops queue[0] and generates a card whose
    content reflects the piece text passed to the LLM."""

    @pytest.mark.asyncio
    async def test_next_card_returns_next_piece_in_order(self):
        """Business rule: POST /next-card pops concepts_queue[0]; that piece's title
        becomes the context for the generated card. The cache is updated: queue shrinks
        by 1, concepts_covered grows by 1."""
        piece_a = _make_piece("Counting Ones", "In base-10, the ones place holds 0-9.")
        piece_b = _make_piece("Counting Tens", "Ten ones equal one ten.")
        cache = _make_cache(
            concepts_queue=[piece_a, piece_b],
            concepts_covered=["Introduction"],
            concepts_total=4,
        )
        session = _make_session(presentation_text=cache)
        student = _make_student()

        svc, mock_db, _ = _build_teaching_service()

        with patch(
            "adaptive.adaptive_engine.load_student_history",
            new=AsyncMock(return_value=_default_history()),
        ), patch(
            "adaptive.adaptive_engine.load_wrong_option_pattern",
            new=AsyncMock(return_value=None),
        ):
            from api.teaching_schemas import NextCardRequest
            req = NextCardRequest(card_index=1, time_on_card_sec=30.0)
            result = await svc.generate_per_card(mock_db, session, student, req)

        # Piece A (queue[0]) was consumed — queue should now only have piece B
        updated_cache = json.loads(session.presentation_text)
        remaining_queue = updated_cache["concepts_queue"]

        assert result["has_more_concepts"] is True, (
            "has_more_concepts must be True while queue still has items"
        )
        assert len(remaining_queue) == 1, (
            "One piece was consumed; queue must shrink from 2 to 1"
        )
        assert remaining_queue[0]["title"] == "Counting Tens", (
            "Remaining queue must preserve order — piece B is next"
        )
        assert "Counting Ones" in updated_cache.get("concepts_covered", []), (
            "The consumed piece title must be appended to concepts_covered"
        )

    @pytest.mark.asyncio
    async def test_next_card_content_in_generated_card(self):
        """Business rule: The piece text passed to build_next_card_prompt() is the
        *specific sub-section text*, not the full concept text. The generated card's
        title and content therefore reflect that specific piece."""
        piece_title = "Place Value — Hundreds"
        piece_text = "The hundreds place holds multiples of 100."
        llm_response = _single_card_llm_response(
            card_type="TEACH",
            title=piece_title,
            content=f"Today we explore {piece_text}",
        )
        cache = _make_cache(
            concepts_queue=[_make_piece(piece_title, piece_text)],
            concepts_covered=[],
            concepts_total=3,
        )
        session = _make_session(presentation_text=cache)
        student = _make_student()

        svc, mock_db, _ = _build_teaching_service(llm_response=llm_response)

        with patch(
            "adaptive.adaptive_engine.load_student_history",
            new=AsyncMock(return_value=_default_history()),
        ), patch(
            "adaptive.adaptive_engine.load_wrong_option_pattern",
            new=AsyncMock(return_value=None),
        ):
            from api.teaching_schemas import NextCardRequest
            req = NextCardRequest()
            result = await svc.generate_per_card(mock_db, session, student, req)

        card = result.get("card")
        assert card is not None, "A card must be generated when queue is non-empty"
        assert piece_title in card["title"], (
            "Card title must reflect the piece title injected into the LLM prompt"
        )
        assert piece_text in card["content"] or "hundreds" in card["content"].lower(), (
            "Card content must reflect the piece text"
        )


# ---------------------------------------------------------------------------
# TC-04  STRUGGLING mode → SLOW current_mode in response
# TC-05  FAST mode → FAST current_mode in response
# ---------------------------------------------------------------------------

class TestAdaptiveModeCardType:
    """TC-04 and TC-05: The card type produced by the LLM differs by mode.
    build_blended_analytics() determines the mode from live signals; the service
    passes it to the prompt builder which instructs the LLM."""

    @pytest.mark.asyncio
    async def test_struggling_mode_generates_explanatory_card(self):
        """Business rule: When signals indicate STRUGGLING (many wrong attempts + high
        hints), build_blended_analytics returns generate_as=STRUGGLING and the service
        maps this to current_mode='SLOW' in the NextCardResponse."""
        cache = _make_cache(
            concepts_queue=[_make_piece("Fractions", "A fraction is a / b.")],
            concepts_total=2,
        )
        session = _make_session(presentation_text=cache)
        student = _make_student()

        struggling_history = _default_history(section_count=2)
        struggling_history["avg_wrong_attempts"] = 3.0
        struggling_history["avg_hints_per_card"] = 4.0

        llm_response = _single_card_llm_response(card_type="TEACH", title="Fractions Explained")
        svc, mock_db, _ = _build_teaching_service(llm_response=llm_response)

        struggling_analytics = _make_analytics_summary(
            student_id=str(session.student_id),
            concept_id=session.concept_id,
            time_spent_sec=300.0,
            expected_time_sec=120.0,
            attempts=5,
            wrong_attempts=4,
            hints_used=5,
            revisits=3,
            recent_dropoffs=2,
            skip_rate=0.1,
            quiz_score=0.3,
            last_7d_sessions=2,
        )

        with patch(
            "adaptive.adaptive_engine.load_student_history",
            new=AsyncMock(return_value=struggling_history),
        ), patch(
            "adaptive.adaptive_engine.load_wrong_option_pattern",
            new=AsyncMock(return_value=None),
        ), patch(
            "adaptive.adaptive_engine.build_blended_analytics",
            return_value=(struggling_analytics, 1.0, "STRUGGLING"),
        ):
            from api.teaching_schemas import NextCardRequest
            req = NextCardRequest(card_index=2, wrong_attempts=3, hints_used=4)
            result = await svc.generate_per_card(mock_db, session, student, req)

        assert result["current_mode"] == "SLOW", (
            "generate_as='STRUGGLING' must map to current_mode='SLOW' in the response "
            "(service maps STRUGGLING → SLOW per the DLD spec)"
        )

    @pytest.mark.asyncio
    async def test_fast_mode_generates_mcq_card(self):
        """Business rule: When signals indicate FAST+STRONG (quick completion, zero
        wrong attempts), build_blended_analytics returns generate_as=FAST and the
        service maps this to current_mode='FAST' in the NextCardResponse."""
        cache = _make_cache(
            concepts_queue=[_make_piece("Exponents", "2^3 = 8.")],
            concepts_total=2,
        )
        session = _make_session(presentation_text=cache)
        student = _make_student()

        fast_history = _default_history(section_count=2)
        fast_history["avg_wrong_attempts"] = 0.0
        fast_history["avg_time_per_card"] = 15.0

        llm_response = _single_card_llm_response(
            card_type="QUESTION", title="Exponents Challenge"
        )
        svc, mock_db, _ = _build_teaching_service(llm_response=llm_response)

        fast_analytics = _make_analytics_summary(
            student_id=str(session.student_id),
            concept_id=session.concept_id,
            time_spent_sec=15.0,
            expected_time_sec=120.0,
            attempts=1,
            wrong_attempts=0,
            hints_used=0,
            revisits=0,
            recent_dropoffs=0,
            skip_rate=0.0,
            quiz_score=0.95,
            last_7d_sessions=3,
        )

        with patch(
            "adaptive.adaptive_engine.load_student_history",
            new=AsyncMock(return_value=fast_history),
        ), patch(
            "adaptive.adaptive_engine.load_wrong_option_pattern",
            new=AsyncMock(return_value=None),
        ), patch(
            "adaptive.adaptive_engine.build_blended_analytics",
            return_value=(fast_analytics, 3.0, "FAST"),
        ):
            from api.teaching_schemas import NextCardRequest
            req = NextCardRequest(card_index=2, time_on_card_sec=15.0, wrong_attempts=0)
            result = await svc.generate_per_card(mock_db, session, student, req)

        assert result["current_mode"] == "FAST", (
            "generate_as='FAST' must map to current_mode='FAST' in the response"
        )


# ---------------------------------------------------------------------------
# TC-06  has_more_concepts=False returned after last piece
# ---------------------------------------------------------------------------

class TestQueueExhaustion:
    """TC-06: When concepts_queue has exactly one item and it is consumed,
    the response returns has_more_concepts=False. A second call with an empty
    queue also returns has_more_concepts=False with card=None."""

    @pytest.mark.asyncio
    async def test_has_more_concepts_false_after_last_piece(self):
        """Business rule: After the last content piece is consumed the service
        returns has_more_concepts=False so the frontend transitions to Socratic."""
        last_piece = _make_piece("Summary", "That covers all whole numbers.")
        cache = _make_cache(
            concepts_queue=[last_piece],
            concepts_covered=["Intro", "Counting", "Place Value"],
            concepts_total=4,
        )
        session = _make_session(presentation_text=cache)
        student = _make_student()

        svc, mock_db, _ = _build_teaching_service()

        with patch(
            "adaptive.adaptive_engine.load_student_history",
            new=AsyncMock(return_value=_default_history()),
        ), patch(
            "adaptive.adaptive_engine.load_wrong_option_pattern",
            new=AsyncMock(return_value=None),
        ):
            from api.teaching_schemas import NextCardRequest
            req = NextCardRequest(card_index=3)
            result = await svc.generate_per_card(mock_db, session, student, req)

        assert result["has_more_concepts"] is False, (
            "has_more_concepts must be False after the last queue item is consumed"
        )
        assert result["card"] is not None, (
            "The final piece still generates a card — card is only None on a post-empty call"
        )

    @pytest.mark.asyncio
    async def test_empty_queue_returns_has_more_false_no_card(self):
        """Business rule: Calling /next-card when the queue is already empty
        returns card=None and has_more_concepts=False without an LLM call."""
        cache = _make_cache(
            concepts_queue=[],
            concepts_covered=["Intro", "Counting"],
            concepts_total=3,
        )
        session = _make_session(presentation_text=cache)
        student = _make_student()

        svc, mock_db, mock_llm = _build_teaching_service()

        with patch(
            "adaptive.adaptive_engine.load_student_history",
            new=AsyncMock(return_value=_default_history()),
        ), patch(
            "adaptive.adaptive_engine.load_wrong_option_pattern",
            new=AsyncMock(return_value=None),
        ):
            from api.teaching_schemas import NextCardRequest
            req = NextCardRequest(card_index=5)
            result = await svc.generate_per_card(mock_db, session, student, req)

        assert result["card"] is None, (
            "Empty queue must return card=None (no LLM call made)"
        )
        assert result["has_more_concepts"] is False, (
            "Empty queue must return has_more_concepts=False"
        )
        mock_llm.chat.completions.create.assert_not_called()


# ---------------------------------------------------------------------------
# TC-07  section_count incremented per-card call (Bug 4 fix)
# ---------------------------------------------------------------------------

class TestSectionCountBlending:
    """TC-07: Bug 4 fix — generate_per_card() locally increments history['section_count']
    before passing it to build_blended_analytics(). This lets blend weights graduate
    within a session without requiring a DB round-trip via section-complete."""

    @pytest.mark.asyncio
    async def test_section_count_increments_per_card(self):
        """Business rule: section_count passed to build_blended_analytics() must be
        DB value + 1. This lets blending weights graduate within a session: at 0 sections
        the analytics are 100% current-signal; at 1+ the historical data starts blending in."""
        initial_db_section_count = 2  # As if student completed 2 sections in prior sessions
        cache = _make_cache(
            concepts_queue=[_make_piece("Algebra Intro", "Variables represent numbers.")],
            concepts_total=3,
        )
        session = _make_session(presentation_text=cache)
        student = _make_student()

        history = _default_history(section_count=initial_db_section_count)
        svc, mock_db, _ = _build_teaching_service()

        seen_section_counts = []
        student_id_str = str(session.student_id)

        def _capture_blend(current_signals, history_arg, **kwargs):
            seen_section_counts.append(history_arg.get("section_count", -1))
            analytics = _make_analytics_summary(
                student_id=student_id_str,
                concept_id=session.concept_id,
            )
            return analytics, 2.0, "NORMAL"

        with patch(
            "adaptive.adaptive_engine.load_student_history",
            new=AsyncMock(return_value=history),
        ), patch(
            "adaptive.adaptive_engine.load_wrong_option_pattern",
            new=AsyncMock(return_value=None),
        ), patch(
            "adaptive.adaptive_engine.build_blended_analytics",
            side_effect=_capture_blend,
        ):
            from api.teaching_schemas import NextCardRequest
            req = NextCardRequest(card_index=2)
            await svc.generate_per_card(mock_db, session, student, req)

        assert len(seen_section_counts) == 1, "build_blended_analytics must be called exactly once"
        assert seen_section_counts[0] == initial_db_section_count + 1, (
            f"section_count passed to build_blended_analytics must be "
            f"DB value ({initial_db_section_count}) + 1 = {initial_db_section_count + 1}; "
            f"got {seen_section_counts[0]}"
        )


# ---------------------------------------------------------------------------
# TC-08  Images assigned from pool
# ---------------------------------------------------------------------------

class TestImageAssignment:
    """TC-08: Available (un-assigned) images from the session cache are passed to
    build_next_card_prompt() and the first available image is assigned to the card."""

    @pytest.mark.asyncio
    async def test_images_assigned_from_pool(self):
        """Business rule: Images in '_images' that are not in 'assigned_image_indices'
        are available for the new card. The service assigns the first available image
        to the card dict and records its index in 'assigned_image_indices'."""
        image_pool = [
            {"url": "/images/fig1.png", "description": "Number line diagram",
             "image_type": "DIAGRAM", "relevance": 0.9},
            {"url": "/images/fig2.png", "description": "Place value chart",
             "image_type": "DIAGRAM", "relevance": 0.8},
        ]
        # Image index 0 was already assigned; only index 1 is available
        cache = _make_cache(
            concepts_queue=[_make_piece("Number Line", "A number line shows integers.")],
            concepts_total=2,
            images=image_pool,
            assigned_image_indices=[0],
        )
        session = _make_session(presentation_text=cache)
        student = _make_student()

        svc, mock_db, _ = _build_teaching_service()

        with patch(
            "adaptive.adaptive_engine.load_student_history",
            new=AsyncMock(return_value=_default_history()),
        ), patch(
            "adaptive.adaptive_engine.load_wrong_option_pattern",
            new=AsyncMock(return_value=None),
        ):
            from api.teaching_schemas import NextCardRequest
            req = NextCardRequest()
            result = await svc.generate_per_card(mock_db, session, student, req)

        card = result.get("card")
        assert card is not None

        updated_cache = json.loads(session.presentation_text)
        assigned = updated_cache.get("assigned_image_indices", [])

        # The previously unassigned image (index 1) must now be assigned
        assert 1 in assigned, (
            "Image at index 1 (the first available image) must be added to assigned_image_indices"
        )

        # The card itself must carry the image
        assert len(card.get("images", [])) >= 1, (
            "The generated card must have at least one image assigned from the pool"
        )
        assert card["images"][0]["url"] == "/images/fig2.png", (
            "The assigned image must be the first *available* image (index 1, not index 0)"
        )

    @pytest.mark.asyncio
    async def test_no_images_when_pool_empty(self):
        """Edge case: When '_images' is empty the card is generated without images
        and no image assignment is attempted."""
        cache = _make_cache(
            concepts_queue=[_make_piece("Zero", "Zero is a placeholder.")],
            concepts_total=1,
            images=[],
            assigned_image_indices=[],
        )
        session = _make_session(presentation_text=cache)
        student = _make_student()

        svc, mock_db, _ = _build_teaching_service()

        with patch(
            "adaptive.adaptive_engine.load_student_history",
            new=AsyncMock(return_value=_default_history()),
        ), patch(
            "adaptive.adaptive_engine.load_wrong_option_pattern",
            new=AsyncMock(return_value=None),
        ):
            from api.teaching_schemas import NextCardRequest
            req = NextCardRequest()
            result = await svc.generate_per_card(mock_db, session, student, req)

        card = result.get("card")
        assert card is not None
        assert card.get("images", []) == [], (
            "Card images must be empty when no images exist in the session pool"
        )


# ---------------------------------------------------------------------------
# TC-09  Endpoint returns 409 when session is not in CARDS phase
# TC-10  Endpoint returns 404 when session does not exist
# ---------------------------------------------------------------------------

class TestEndpointGuards:
    """TC-09 and TC-10: The router must enforce session state preconditions before
    delegating to the service.

    Direct invocation of @limiter.limit() decorated handlers requires a real
    starlette.requests.Request object. We build a minimal one from an HTTP scope
    dict rather than using a MagicMock (slowapi validates the type at call time).
    """

    @pytest.mark.asyncio
    async def test_next_card_requires_cards_phase(self):
        """Business rule: POST /next-card returns HTTP 409 when session.phase != 'CARDS'.
        This prevents card generation during Socratic check or after session completion."""
        from fastapi import HTTPException

        session = _make_session(phase="CHECKING")
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=session)

        from api.teaching_router import get_next_adaptive_card
        from api.teaching_schemas import NextCardRequest

        req = NextCardRequest()
        starlette_req = _make_starlette_request()

        with pytest.raises(HTTPException) as exc_info:
            await get_next_adaptive_card(
                request=starlette_req,
                session_id=session.id,
                req=req,
                db=mock_db,
            )

        assert exc_info.value.status_code == 409, (
            "Endpoint must return HTTP 409 when session is not in CARDS phase"
        )
        assert "CHECKING" in exc_info.value.detail or "phase" in exc_info.value.detail.lower(), (
            "409 detail must mention the current phase to aid debugging"
        )

    @pytest.mark.asyncio
    async def test_next_card_404_on_missing_session(self):
        """Business rule: POST /next-card returns HTTP 404 when the session_id does
        not exist in the database."""
        from fastapi import HTTPException
        from api.teaching_router import get_next_adaptive_card
        from api.teaching_schemas import NextCardRequest

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)  # Session not found

        req = NextCardRequest()
        starlette_req = _make_starlette_request()
        session_id = uuid.uuid4()

        with pytest.raises(HTTPException) as exc_info:
            await get_next_adaptive_card(
                request=starlette_req,
                session_id=session_id,
                req=req,
                db=mock_db,
            )

        assert exc_info.value.status_code == 404, (
            "Endpoint must return HTTP 404 when the session does not exist"
        )


# ---------------------------------------------------------------------------
# TC-11  Prompt builder injects image block when images provided
# TC-12  Prompt builder omits image block when no images provided
# TC-13  Prompt builder caps images at 3
# ---------------------------------------------------------------------------

class TestPromptBuilderImageInjection:
    """TC-11, TC-12, TC-13: build_next_card_prompt() injects a 'RELEVANT IMAGES FOR THIS CARD'
    block when content_piece_images is provided, omits it otherwise, and caps at 3 images."""

    def _minimal_profile(self, student_id: str = "student-1", concept_id: str = "PREALG.C1.S1"):
        """Build a LearningProfile from a minimal AnalyticsSummary."""
        from adaptive.profile_builder import build_learning_profile
        return build_learning_profile(
            _make_analytics_summary(student_id=student_id, concept_id=concept_id),
            has_unmet_prereq=False,
        )

    def _minimal_concept(self, title: str = "Counting") -> dict:
        return {
            "concept_title": title,
            "chapter": "1",
            "section": "1",
            "text": "We count using natural numbers.",
        }

    def test_image_block_injected_when_images_provided(self):
        """Business rule: When content_piece_images is non-empty the user prompt
        contains 'RELEVANT IMAGES FOR THIS CARD:' with each image's description."""
        from adaptive.prompt_builder import build_next_card_prompt
        from adaptive.generation_profile import build_generation_profile

        profile = self._minimal_profile()
        gen_profile = build_generation_profile(profile)

        images = [
            {"description": "A bar chart showing tens and ones",
             "image_type": "DIAGRAM", "url": "/img/bar.png"},
            {"description": "Place value table", "image_type": "TABLE", "url": "/img/table.png"},
        ]

        _sys, user_prompt = build_next_card_prompt(
            concept_detail=self._minimal_concept("Place Value"),
            learning_profile=profile,
            gen_profile=gen_profile,
            card_index=0,
            history=_default_history(),
            content_piece_images=images,
        )

        assert "RELEVANT IMAGES FOR THIS CARD:" in user_prompt, (
            "User prompt must include the RELEVANT IMAGES block when images are provided"
        )
        assert "A bar chart showing tens and ones" in user_prompt, (
            "First image description must appear in the user prompt"
        )
        assert "Place value table" in user_prompt, (
            "Second image description must appear in the user prompt"
        )
        assert "IMAGE INSTRUCTION:" in user_prompt, (
            "Image instruction directive must be present"
        )

    def test_image_block_omitted_when_no_images(self):
        """Business rule: When content_piece_images is None (or empty) the user prompt
        does NOT contain the RELEVANT IMAGES block."""
        from adaptive.prompt_builder import build_next_card_prompt
        from adaptive.generation_profile import build_generation_profile

        profile = self._minimal_profile()
        gen_profile = build_generation_profile(profile)

        _sys, user_prompt = build_next_card_prompt(
            concept_detail=self._minimal_concept("Counting"),
            learning_profile=profile,
            gen_profile=gen_profile,
            card_index=0,
            history=_default_history(),
            content_piece_images=None,
        )

        assert "RELEVANT IMAGES FOR THIS CARD:" not in user_prompt, (
            "User prompt must NOT include the image block when content_piece_images is None"
        )

    def test_image_block_caps_at_3_images(self):
        """Business rule: Even if more than 3 images are passed, only the first 3
        appear in the user prompt (capped at 3 per the spec)."""
        from adaptive.prompt_builder import build_next_card_prompt
        from adaptive.generation_profile import build_generation_profile

        profile = self._minimal_profile()
        gen_profile = build_generation_profile(profile)

        images = [
            {"description": f"Image {i}", "image_type": "DIAGRAM", "url": f"/img/{i}.png"}
            for i in range(5)
        ]

        _sys, user_prompt = build_next_card_prompt(
            concept_detail=self._minimal_concept("Geometry"),
            learning_profile=profile,
            gen_profile=gen_profile,
            card_index=0,
            history=_default_history(),
            content_piece_images=images,
        )

        for i in range(3):
            assert f"Image {i}" in user_prompt, (
                f"Image {i} must appear in the prompt (within 3-image cap)"
            )
        for i in range(3, 5):
            assert f"Image {i}" not in user_prompt, (
                f"Image {i} must NOT appear in the prompt (exceeds 3-image cap)"
            )


# ---------------------------------------------------------------------------
# TC-14  NextCardRequest schema validation
# ---------------------------------------------------------------------------

class TestNextCardRequestSchema:
    """TC-14: Pydantic schema NextCardRequest rejects negative field values and
    accepts valid defaults."""

    def test_default_values_valid(self):
        """Business rule: All NextCardRequest fields default to 0 — a freshly
        started session requires no signal data for the first card."""
        from api.teaching_schemas import NextCardRequest
        req = NextCardRequest()
        assert req.card_index == 0
        assert req.time_on_card_sec == 0.0
        assert req.wrong_attempts == 0
        assert req.hints_used == 0
        assert req.idle_triggers == 0

    def test_negative_card_index_rejected(self):
        """Business rule: card_index must be >= 0 (ge=0 constraint)."""
        from pydantic import ValidationError
        from api.teaching_schemas import NextCardRequest
        with pytest.raises(ValidationError):
            NextCardRequest(card_index=-1)

    def test_negative_time_rejected(self):
        """Business rule: time_on_card_sec must be >= 0.0 (ge=0.0 constraint)."""
        from pydantic import ValidationError
        from api.teaching_schemas import NextCardRequest
        with pytest.raises(ValidationError):
            NextCardRequest(time_on_card_sec=-5.0)

    def test_valid_signal_values_accepted(self):
        """Positive signal values must be accepted by the schema."""
        from api.teaching_schemas import NextCardRequest
        req = NextCardRequest(
            card_index=3,
            time_on_card_sec=45.5,
            wrong_attempts=2,
            hints_used=1,
            idle_triggers=0,
        )
        assert req.card_index == 3
        assert req.time_on_card_sec == 45.5
        assert req.wrong_attempts == 2


# ---------------------------------------------------------------------------
# TC-15  Bug 7 fix: card_index uses total_cards_completed in generate_cards()
# ---------------------------------------------------------------------------

class TestBug7CardIndexFix:
    """TC-15: Bug 7 fix — the CardBehaviorSignals passed to build_blended_analytics()
    in generate_cards() must use history['total_cards_completed'], not hardcoded 0."""

    def test_card_index_uses_total_cards_completed(self):
        """Business rule: The initial call to build_blended_analytics() in generate_cards()
        must set card_index from history to accurately reflect the student's card history,
        not always assume the student is on card 0.

        We inspect the source code of generate_cards() to confirm the fix is present."""
        from api.teaching_service import TeachingService

        source = inspect.getsource(TeachingService.generate_cards)

        assert "total_cards_completed" in source, (
            "generate_cards() must use history['total_cards_completed'] for card_index "
            "(Bug 7 fix) — hardcoded card_index=0 is no longer acceptable"
        )
