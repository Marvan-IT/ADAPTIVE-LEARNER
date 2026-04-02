"""
test_chunk_questions.py — Unit tests for per-chunk question generation and evaluation.

Business criteria covered:
  BC-CQ-01  Questions endpoint returns 1 question for short chunks (< 300 chars)
  BC-CQ-02  Returns 2 questions for medium chunks (300–800 chars)
  BC-CQ-03  Returns 3 questions for long chunks (> 800 chars)
  BC-CQ-04  teaching and chapter_review chunks both get questions
  BC-CQ-05  evaluate returns passed=True when >= 70% correct
  BC-CQ-06  evaluate returns passed=False when < 70% correct
  BC-CQ-07  evaluate marks chunk_progress when passed
  BC-CQ-08  evaluate sets all_study_complete=True when last required chunk passes
  BC-CQ-09  exercise chunks skip Q&A (questions field is empty list)

All tests are unit tests — every external dependency (DB, LLM, chunk service)
is mocked. No live database or OpenAI key is required.
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


def _stub_heavyweight_modules():
    """Stub modules with import-time issues before importing teaching_router."""
    if "db.connection" not in sys.modules:
        stub_conn = MagicMock()
        stub_conn.get_db = MagicMock()
        sys.modules["db.connection"] = stub_conn


_stub_heavyweight_modules()


# ---------------------------------------------------------------------------
# Shared test constants
# ---------------------------------------------------------------------------

_CHUNK_ID = str(uuid.uuid4())
_SESSION_ID = uuid.uuid4()
_STUDENT_ID = uuid.uuid4()

# Short text: < 300 chars → 1 question
_SHORT_TEXT = "A whole number is any non-negative integer (0, 1, 2, 3...). These are the counting numbers plus zero."

# Medium text: 300–800 chars → 2 questions
_MEDIUM_TEXT = (
    "A whole number is any non-negative integer starting from zero. "
    "The set includes 0, 1, 2, 3, and so on without any upper bound. "
    "Whole numbers are used in everyday counting and in basic arithmetic operations. "
    "They do not include fractions, decimals, or negative numbers. "
    "Every natural number is a whole number, but zero is a whole number that is not a natural number. "
    "This distinction matters in set theory and formal mathematics."
)

# Long text: > 800 chars → 3 questions
_LONG_TEXT = (
    "A whole number is any non-negative integer starting from zero. "
    "The set includes 0, 1, 2, 3, and so on without any upper bound. "
    "Whole numbers are used in everyday counting and in basic arithmetic. "
    "They do not include fractions, decimals, or negative numbers. "
    "Every natural number is a whole number, but zero is a whole number that is not a natural number. "
    "This distinction matters in set theory and formal mathematics. "
    "When adding two whole numbers, the result is always a whole number (closure under addition). "
    "When multiplying two whole numbers, the result is also always a whole number (closure under multiplication). "
    "Subtraction of whole numbers does not always yield a whole number — for example, 3 minus 5 is negative two, "
    "which is outside the set. This is why integers were introduced as an extension. "
    "Division is similarly not always closed: 7 divided by 2 yields 3.5, which is not a whole number."
)

# Minimal valid card JSON returned by the first LLM call (card generation)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_chunk(heading: str = "Introduction", text: str = _SHORT_TEXT) -> dict:
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
    s.chunk_progress = {}
    return s


def _make_student() -> MagicMock:
    """Return a mock Student ORM object."""
    st = MagicMock()
    st.id = _STUDENT_ID
    st.preferred_language = "en"
    st.interests = []
    return st


def _make_llm_response(content: str) -> MagicMock:
    """Build a mock OpenAI completion response with given content string."""
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


def _make_questions_json(n: int) -> str:
    """Build a JSON string of n question strings for the second LLM call."""
    questions = [f"Explain concept {i+1} in your own words?" for i in range(n)]
    return json.dumps({"questions": questions})


def _build_service_with_side_effect(card_json: str, questions_json: str):
    """
    Construct a TeachingService where:
      - First LLM call (card generation via _chat) returns card_json
      - Second LLM call (question generation via openai.chat.completions.create) returns questions_json

    Returns (service, mock_db).
    Both calls go through svc.openai.chat.completions.create. The _chat() method
    calls it for card generation; question generation calls it directly. We use
    side_effect to return card_json first and questions_json second.
    """
    from api.teaching_service import TeachingService

    svc = TeachingService()

    cards_response = _make_llm_response(card_json)
    questions_response = _make_llm_response(questions_json)

    mock_llm = MagicMock()
    mock_llm.chat.completions.create = AsyncMock(
        side_effect=[cards_response, questions_response]
    )
    svc.openai = mock_llm

    # Mock the ChunkKnowledgeService
    mock_ksvc = MagicMock()
    mock_ksvc.get_chunk = AsyncMock(return_value=_make_fake_chunk())
    mock_ksvc.get_chunk_images = AsyncMock(return_value=[])
    mock_ksvc.get_concept_detail = AsyncMock(return_value={"images": []})
    svc._chunk_ksvc = mock_ksvc

    # Mock the DB session
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=_make_student())

    return svc, mock_db


def _build_service_with_chunk(
    heading: str,
    text: str,
    card_json: str = _VALID_CARD_JSON,
    questions_json: str | None = None,
):
    """
    Build a service pre-configured with a specific chunk.
    If questions_json is None, uses a 1-question default.
    """
    if questions_json is None:
        questions_json = _make_questions_json(1)

    from api.teaching_service import TeachingService

    svc = TeachingService()

    cards_response = _make_llm_response(card_json)
    questions_response = _make_llm_response(questions_json)

    mock_llm = MagicMock()
    mock_llm.chat.completions.create = AsyncMock(
        side_effect=[cards_response, questions_response]
    )
    svc.openai = mock_llm

    mock_ksvc = MagicMock()
    mock_ksvc.get_chunk = AsyncMock(return_value=_make_fake_chunk(heading=heading, text=text))
    mock_ksvc.get_chunk_images = AsyncMock(return_value=[])
    mock_ksvc.get_concept_detail = AsyncMock(return_value={"images": []})
    svc._chunk_ksvc = mock_ksvc

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=_make_student())

    return svc, mock_db


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CQ-01  Short chunks generate 1 question
# ═══════════════════════════════════════════════════════════════════════════════

class TestShortChunkOneQuestion:
    """BC-CQ-01: Short chunk text (< 300 chars) should produce exactly 1 question.

    Business rule: question count is proportional to content density. Short subsections
    have limited teachable content — one question is sufficient to assess understanding
    without overwhelming the student.
    """

    async def test_short_chunk_returns_one_question(self):
        """Should return exactly 1 question when chunk text is < 300 characters.

        Arrange: chunk text is short (< 300 chars); LLM question call returns 1 question.
        Act:     call generate_per_chunk().
        Assert:  result["questions"] has exactly 1 item.
        """
        assert len(_SHORT_TEXT) < 300, (
            f"Test setup error: _SHORT_TEXT must be < 300 chars but is {len(_SHORT_TEXT)}"
        )

        questions_json = _make_questions_json(1)
        svc, mock_db = _build_service_with_chunk(
            heading="Introduction",
            text=_SHORT_TEXT,
            questions_json=questions_json,
        )
        session = _make_session()

        result = await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        assert isinstance(result, dict), "generate_per_chunk must return a dict"
        questions = result.get("questions", [])
        assert len(questions) == 1, (
            f"Expected 1 question for short chunk (< 300 chars), got {len(questions)}: {questions}"
        )

    async def test_short_chunk_question_has_index_and_text(self):
        """Each returned question must have 'index' and 'text' fields.

        Arrange: short chunk with 1-question LLM response.
        Act:     call generate_per_chunk().
        Assert:  questions[0] has non-empty 'index' and 'text'.
        """
        questions_json = json.dumps({"questions": ["What is a whole number?"]})
        svc, mock_db = _build_service_with_chunk(
            heading="Introduction",
            text=_SHORT_TEXT,
            questions_json=questions_json,
        )
        session = _make_session()

        result = await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        questions = result.get("questions", [])
        assert len(questions) >= 1, "Expected at least 1 question"
        q = questions[0]
        assert "index" in q, f"Question must have 'index' field: {q}"
        assert "text" in q, f"Question must have 'text' field: {q}"
        assert q["text"].strip(), f"Question text must not be empty: {q}"


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CQ-02  Medium chunks generate 2 questions
# ═══════════════════════════════════════════════════════════════════════════════

class TestMediumChunkTwoQuestions:
    """BC-CQ-02: Medium chunk text (300–800 chars) should produce exactly 2 questions.

    Business rule: medium-length subsections cover multiple concepts or worked examples
    that require more than one comprehension check to assess adequately.
    """

    async def test_medium_chunk_returns_two_questions(self):
        """Should return exactly 2 questions when chunk text is 300–800 characters.

        Arrange: chunk text is medium-length (300–800 chars); LLM question call returns 2 questions.
        Act:     call generate_per_chunk().
        Assert:  result["questions"] has exactly 2 items.
        """
        assert 300 <= len(_MEDIUM_TEXT) < 800, (
            f"Test setup error: _MEDIUM_TEXT must be 300–800 chars but is {len(_MEDIUM_TEXT)}"
        )

        questions_json = _make_questions_json(2)
        svc, mock_db = _build_service_with_chunk(
            heading="Introduction",
            text=_MEDIUM_TEXT,
            questions_json=questions_json,
        )
        session = _make_session()

        result = await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        assert isinstance(result, dict), "generate_per_chunk must return a dict"
        questions = result.get("questions", [])
        assert len(questions) == 2, (
            f"Expected 2 questions for medium chunk (300–800 chars), got {len(questions)}: {questions}"
        )

    async def test_medium_chunk_question_system_prompt_requests_two(self):
        """The question generation system prompt must request exactly 2 questions for medium chunks.

        Arrange: medium-length chunk; capture LLM calls.
        Act:     call generate_per_chunk() and inspect the second LLM call.
        Assert:  the system prompt in the second LLM call contains 'exactly 2'.
        """
        questions_json = _make_questions_json(2)
        svc, mock_db = _build_service_with_chunk(
            heading="Introduction",
            text=_MEDIUM_TEXT,
            questions_json=questions_json,
        )
        session = _make_session()

        await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        calls = svc.openai.chat.completions.create.call_args_list
        # The second call (index 1) is the question generation call
        assert len(calls) >= 2, (
            "Expected at least 2 LLM calls (card generation + question generation), "
            f"got {len(calls)}"
        )
        second_call_kwargs = calls[1].kwargs
        second_call_messages = second_call_kwargs.get("messages") or []
        system_msgs = [m["content"] for m in second_call_messages if m.get("role") == "system"]
        assert system_msgs, "Question generation call must include a system message"
        assert "exactly 2" in system_msgs[0], (
            f"System prompt must request 'exactly 2' questions for medium chunk; "
            f"got: {system_msgs[0][:300]}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CQ-03  Long chunks generate 3 questions
# ═══════════════════════════════════════════════════════════════════════════════

class TestLongChunkThreeQuestions:
    """BC-CQ-03: Long chunk text (> 800 chars) should produce exactly 3 questions.

    Business rule: long subsections typically cover multiple concepts and step-by-step
    worked examples. Three questions ensure comprehensive coverage of all main ideas
    and prevent students from skimming to answer a single question.
    """

    async def test_long_chunk_returns_three_questions(self):
        """Should return exactly 3 questions when chunk text is > 800 characters.

        Arrange: chunk text is long (> 800 chars); LLM question call returns 3 questions.
        Act:     call generate_per_chunk().
        Assert:  result["questions"] has exactly 3 items.
        """
        assert len(_LONG_TEXT) > 800, (
            f"Test setup error: _LONG_TEXT must be > 800 chars but is {len(_LONG_TEXT)}"
        )

        questions_json = _make_questions_json(3)
        svc, mock_db = _build_service_with_chunk(
            heading="Introduction",
            text=_LONG_TEXT,
            questions_json=questions_json,
        )
        session = _make_session()

        result = await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        assert isinstance(result, dict), "generate_per_chunk must return a dict"
        questions = result.get("questions", [])
        assert len(questions) == 3, (
            f"Expected 3 questions for long chunk (> 800 chars), got {len(questions)}: {questions}"
        )

    async def test_long_chunk_question_system_prompt_requests_three(self):
        """The question generation system prompt must request exactly 3 questions for long chunks.

        Arrange: long chunk; capture LLM calls.
        Act:     call generate_per_chunk() and inspect the second LLM call.
        Assert:  the system prompt in the second LLM call contains 'exactly 3'.
        """
        questions_json = _make_questions_json(3)
        svc, mock_db = _build_service_with_chunk(
            heading="Introduction",
            text=_LONG_TEXT,
            questions_json=questions_json,
        )
        session = _make_session()

        await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        calls = svc.openai.chat.completions.create.call_args_list
        assert len(calls) >= 2, (
            f"Expected at least 2 LLM calls for long chunk, got {len(calls)}"
        )
        second_call_messages = (calls[1].kwargs.get("messages") or [])
        system_msgs = [m["content"] for m in second_call_messages if m.get("role") == "system"]
        assert system_msgs, "Question generation call must include a system message"
        assert "exactly 3" in system_msgs[0], (
            f"System prompt must request 'exactly 3' questions for long chunk; "
            f"got: {system_msgs[0][:300]}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CQ-04  Both teaching and chapter_review chunks get questions
# ═══════════════════════════════════════════════════════════════════════════════

class TestTeachingAndChapterReviewBothGetQuestions:
    """BC-CQ-04: Both 'teaching' and 'chapter_review' chunk types should receive questions.

    Business rule: chapter_review chunks (e.g. "1.1 Introduction to Whole Numbers") are
    section-intro content that students must also engage with actively. Skipping question
    generation for them would leave the section intro unassessed.
    """

    async def test_teaching_chunk_gets_questions(self):
        """A chunk with a plain teaching heading should produce questions.

        Arrange: heading is plain instructional content ('Use Addition Notation');
                 LLM question call returns 1 question.
        Act:     call generate_per_chunk().
        Assert:  result["questions"] is non-empty.
        """
        questions_json = _make_questions_json(1)
        svc, mock_db = _build_service_with_chunk(
            heading="Use Addition Notation",  # classified as 'teaching'
            text=_SHORT_TEXT,
            questions_json=questions_json,
        )
        session = _make_session()

        result = await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        questions = result.get("questions", [])
        assert len(questions) >= 1, (
            f"Expected at least 1 question for teaching chunk, got {len(questions)}"
        )

    async def test_chapter_review_chunk_gets_questions(self):
        """A chunk with a numeric-prefixed heading (chapter_review type) should produce questions.

        Arrange: heading matches r'^\\d+\\.\\d+\\s+\\w' pattern (e.g. '1.1 Introduction');
                 LLM question call returns 1 question.
        Act:     call generate_per_chunk().
        Assert:  result["questions"] is non-empty.
        """
        questions_json = _make_questions_json(1)
        svc, mock_db = _build_service_with_chunk(
            heading="1.1 Introduction to Whole Numbers",  # classified as 'chapter_review'
            text=_SHORT_TEXT,
            questions_json=questions_json,
        )
        session = _make_session()

        result = await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        questions = result.get("questions", [])
        assert len(questions) >= 1, (
            f"Expected at least 1 question for chapter_review chunk, got {len(questions)}"
        )

    async def test_both_chunk_types_make_two_llm_calls(self):
        """Both teaching and chapter_review chunks should trigger a second LLM call for questions.

        Arrange: two separate service instances — one with teaching heading, one with chapter_review.
        Act:     call generate_per_chunk() for each.
        Assert:  both instances show >= 2 calls to openai.chat.completions.create.
        """
        for heading in ("Use Addition Notation", "1.1 Introduction to Whole Numbers"):
            questions_json = _make_questions_json(1)
            svc, mock_db = _build_service_with_chunk(
                heading=heading,
                text=_SHORT_TEXT,
                questions_json=questions_json,
            )
            session = _make_session()

            await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

            call_count = svc.openai.chat.completions.create.call_count
            assert call_count >= 2, (
                f"Expected >= 2 LLM calls for '{heading}' chunk, got {call_count}. "
                "The second call must be the question generation call."
            )


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CQ-05  evaluate returns passed=True when >= 70% correct
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvaluatePassesAtSeventyPercent:
    """BC-CQ-05: evaluate_chunk_answers must return passed=True when score >= 70%.

    Business rule: 70% is the mastery threshold across the entire ADA platform.
    Consistent thresholds (Socratic check, MCQ, and chunk Q&A all use 70) ensure
    students cannot game one pathway while failing another.
    """

    async def test_evaluate_passes_when_all_correct(self):
        """Should return passed=True when every answer is marked correct by the LLM.

        Arrange: 2 questions; LLM marks both correct → score = 1.0.
        Act:     call evaluate_chunk_answers().
        Assert:  response.passed is True and response.score == 1.0.
        """
        from api.teaching_router import evaluate_chunk_answers
        from api.teaching_schemas import (
            ChunkEvaluateRequest, ChunkQuestion, ChunkAnswerItem,
        )
        from starlette.requests import Request as StarletteRequest

        session = _make_session()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=session)
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        # Mock chunk_ksvc used inside evaluate_chunk_answers
        mock_chunk_ksvc = MagicMock()
        mock_chunk_ksvc.get_chunks_for_concept = AsyncMock(return_value=[
            {"id": _CHUNK_ID, "heading": "Introduction"},
        ])

        # LLM marks both answers correct
        correct_resp = _make_llm_response('{"correct": true, "feedback": "Great answer!"}')
        mock_llm = MagicMock()
        mock_llm.chat.completions.create = AsyncMock(return_value=correct_resp)

        req_body = ChunkEvaluateRequest(
            questions=[
                ChunkQuestion(index=0, text="What is a whole number?"),
                ChunkQuestion(index=1, text="Give an example of a whole number."),
            ],
            answers=[
                ChunkAnswerItem(index=0, answer_text="A non-negative integer starting from zero."),
                ChunkAnswerItem(index=1, answer_text="The number 5 is a whole number."),
            ],
            mode_used="NORMAL",
        )

        fake_request = StarletteRequest({
            "type": "http", "method": "POST",
            "path": f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/evaluate",
            "query_string": b"", "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 0),
        })

        with (
            patch("api.teaching_router.teaching_svc") as mock_svc,
            patch("api.teaching_router.chunk_ksvc", mock_chunk_ksvc),
        ):
            mock_svc.openai = mock_llm

            response = await evaluate_chunk_answers(
                request=fake_request,
                session_id=_SESSION_ID,
                chunk_id=_CHUNK_ID,
                req=req_body,
                db=mock_db,
            )

        assert response.passed is True, (
            f"Expected passed=True when all answers correct, got passed={response.passed}"
        )
        assert response.score == 1.0, (
            f"Expected score=1.0 when all answers correct, got score={response.score}"
        )

    async def test_evaluate_passes_at_exact_seventy_percent(self):
        """Should return passed=True when exactly 70% of answers are correct.

        Arrange: 10 questions; LLM marks 7 correct and 3 incorrect → score = 0.7.
        Act:     call evaluate_chunk_answers().
        Assert:  response.passed is True and response.score == 0.7.
        """
        from api.teaching_router import evaluate_chunk_answers
        from api.teaching_schemas import (
            ChunkEvaluateRequest, ChunkQuestion, ChunkAnswerItem,
        )
        from starlette.requests import Request as StarletteRequest

        session = _make_session()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=session)
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        mock_chunk_ksvc = MagicMock()
        mock_chunk_ksvc.get_chunks_for_concept = AsyncMock(return_value=[
            {"id": _CHUNK_ID, "heading": "Introduction"},
        ])

        # 7 correct then 3 incorrect
        correct_resp = _make_llm_response('{"correct": true, "feedback": "Correct!"}')
        wrong_resp = _make_llm_response('{"correct": false, "feedback": "Review this."}')
        mock_llm = MagicMock()
        mock_llm.chat.completions.create = AsyncMock(
            side_effect=[correct_resp] * 7 + [wrong_resp] * 3
        )

        req_body = ChunkEvaluateRequest(
            questions=[ChunkQuestion(index=i, text=f"Q{i}?") for i in range(10)],
            answers=[ChunkAnswerItem(index=i, answer_text=f"Answer {i}") for i in range(10)],
            mode_used="NORMAL",
        )

        fake_request = StarletteRequest({
            "type": "http", "method": "POST",
            "path": f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/evaluate",
            "query_string": b"", "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 0),
        })

        with (
            patch("api.teaching_router.teaching_svc") as mock_svc,
            patch("api.teaching_router.chunk_ksvc", mock_chunk_ksvc),
        ):
            mock_svc.openai = mock_llm

            response = await evaluate_chunk_answers(
                request=fake_request,
                session_id=_SESSION_ID,
                chunk_id=_CHUNK_ID,
                req=req_body,
                db=mock_db,
            )

        assert response.passed is True, (
            f"Expected passed=True at exactly 70% score, got passed={response.passed} score={response.score}"
        )
        assert abs(response.score - 0.7) < 1e-9, (
            f"Expected score=0.7 (7/10 correct), got score={response.score}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CQ-06  evaluate returns passed=False when < 70% correct
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvaluateFailsBelowSeventyPercent:
    """BC-CQ-06: evaluate_chunk_answers must return passed=False when score < 70%.

    Business rule: students who do not demonstrate 70% understanding must re-study
    before being allowed to advance to the next chunk or attempt the exam gate.
    """

    async def test_evaluate_fails_when_all_wrong(self):
        """Should return passed=False when every answer is marked incorrect.

        Arrange: 2 questions; LLM marks both incorrect → score = 0.0.
        Act:     call evaluate_chunk_answers().
        Assert:  response.passed is False and response.score == 0.0.
        """
        from api.teaching_router import evaluate_chunk_answers
        from api.teaching_schemas import (
            ChunkEvaluateRequest, ChunkQuestion, ChunkAnswerItem,
        )
        from starlette.requests import Request as StarletteRequest

        session = _make_session()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=session)

        wrong_resp = _make_llm_response('{"correct": false, "feedback": "Incorrect."}')
        mock_llm = MagicMock()
        mock_llm.chat.completions.create = AsyncMock(return_value=wrong_resp)

        req_body = ChunkEvaluateRequest(
            questions=[
                ChunkQuestion(index=0, text="What is a whole number?"),
                ChunkQuestion(index=1, text="Give an example."),
            ],
            answers=[
                ChunkAnswerItem(index=0, answer_text="I don't know."),
                ChunkAnswerItem(index=1, answer_text="Banana."),
            ],
            mode_used="NORMAL",
        )

        fake_request = StarletteRequest({
            "type": "http", "method": "POST",
            "path": f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/evaluate",
            "query_string": b"", "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 0),
        })

        with (
            patch("api.teaching_router.teaching_svc") as mock_svc,
            patch("api.teaching_router.chunk_ksvc"),
        ):
            mock_svc.openai = mock_llm

            response = await evaluate_chunk_answers(
                request=fake_request,
                session_id=_SESSION_ID,
                chunk_id=_CHUNK_ID,
                req=req_body,
                db=mock_db,
            )

        assert response.passed is False, (
            f"Expected passed=False when all answers incorrect, got passed={response.passed}"
        )
        assert response.score == 0.0, (
            f"Expected score=0.0 when all answers incorrect, got score={response.score}"
        )

    async def test_evaluate_fails_at_sixty_nine_percent(self):
        """Should return passed=False when score is just below the 70% threshold.

        Arrange: 10 questions; LLM marks 6 correct and 4 incorrect → score = 0.6.
        Act:     call evaluate_chunk_answers().
        Assert:  response.passed is False.
        """
        from api.teaching_router import evaluate_chunk_answers
        from api.teaching_schemas import (
            ChunkEvaluateRequest, ChunkQuestion, ChunkAnswerItem,
        )
        from starlette.requests import Request as StarletteRequest

        session = _make_session()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=session)

        correct_resp = _make_llm_response('{"correct": true, "feedback": "Correct!"}')
        wrong_resp = _make_llm_response('{"correct": false, "feedback": "Wrong."}')
        mock_llm = MagicMock()
        mock_llm.chat.completions.create = AsyncMock(
            side_effect=[correct_resp] * 6 + [wrong_resp] * 4
        )

        req_body = ChunkEvaluateRequest(
            questions=[ChunkQuestion(index=i, text=f"Q{i}?") for i in range(10)],
            answers=[ChunkAnswerItem(index=i, answer_text=f"A{i}") for i in range(10)],
            mode_used="NORMAL",
        )

        fake_request = StarletteRequest({
            "type": "http", "method": "POST",
            "path": f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/evaluate",
            "query_string": b"", "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 0),
        })

        with (
            patch("api.teaching_router.teaching_svc") as mock_svc,
            patch("api.teaching_router.chunk_ksvc"),
        ):
            mock_svc.openai = mock_llm

            response = await evaluate_chunk_answers(
                request=fake_request,
                session_id=_SESSION_ID,
                chunk_id=_CHUNK_ID,
                req=req_body,
                db=mock_db,
            )

        assert response.passed is False, (
            f"Expected passed=False at score=0.6 (below 70% threshold), "
            f"got passed={response.passed} score={response.score}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CQ-07  evaluate marks chunk_progress when passed
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvaluateMarksChunkProgressWhenPassed:
    """BC-CQ-07: When a student passes (score >= 70%), chunk_id must appear in chunk_progress.

    Business rule: chunk_progress tracks which chunks a student has demonstrated
    understanding of. This gate prevents skipping ahead without mastery and determines
    when the exam gate unlocks (all_study_complete).
    """

    async def test_passing_evaluation_updates_chunk_progress(self):
        """chunk_progress in the response must include the evaluated chunk_id after passing.

        Arrange: session with empty chunk_progress; LLM marks all answers correct.
        Act:     call evaluate_chunk_answers().
        Assert:  response.chunk_progress contains the evaluated chunk_id.
        """
        from api.teaching_router import evaluate_chunk_answers
        from api.teaching_schemas import (
            ChunkEvaluateRequest, ChunkQuestion, ChunkAnswerItem,
        )
        from starlette.requests import Request as StarletteRequest

        session = _make_session()
        session.chunk_progress = {}

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=session)
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        mock_chunk_ksvc = MagicMock()
        mock_chunk_ksvc.get_chunks_for_concept = AsyncMock(return_value=[
            {"id": _CHUNK_ID, "heading": "Introduction"},
        ])

        correct_resp = _make_llm_response('{"correct": true, "feedback": "Correct!"}')
        mock_llm = MagicMock()
        mock_llm.chat.completions.create = AsyncMock(return_value=correct_resp)

        req_body = ChunkEvaluateRequest(
            questions=[ChunkQuestion(index=0, text="Describe whole numbers.")],
            answers=[ChunkAnswerItem(index=0, answer_text="Non-negative integers starting at zero.")],
            mode_used="NORMAL",
        )

        fake_request = StarletteRequest({
            "type": "http", "method": "POST",
            "path": f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/evaluate",
            "query_string": b"", "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 0),
        })

        with (
            patch("api.teaching_router.teaching_svc") as mock_svc,
            patch("api.teaching_router.chunk_ksvc", mock_chunk_ksvc),
        ):
            mock_svc.openai = mock_llm

            response = await evaluate_chunk_answers(
                request=fake_request,
                session_id=_SESSION_ID,
                chunk_id=_CHUNK_ID,
                req=req_body,
                db=mock_db,
            )

        assert response.passed is True, "Precondition: evaluation must pass"
        assert response.chunk_progress is not None, (
            "chunk_progress in response must not be None when passed=True"
        )
        assert _CHUNK_ID in response.chunk_progress, (
            f"Evaluated chunk_id must appear in response.chunk_progress. "
            f"Got: {response.chunk_progress}"
        )

    async def test_failing_evaluation_does_not_update_chunk_progress(self):
        """chunk_progress in the response must be None when the student fails.

        Arrange: session with empty chunk_progress; LLM marks answers incorrect.
        Act:     call evaluate_chunk_answers().
        Assert:  response.chunk_progress is None (no update recorded).
        """
        from api.teaching_router import evaluate_chunk_answers
        from api.teaching_schemas import (
            ChunkEvaluateRequest, ChunkQuestion, ChunkAnswerItem,
        )
        from starlette.requests import Request as StarletteRequest

        session = _make_session()
        session.chunk_progress = {}

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=session)

        wrong_resp = _make_llm_response('{"correct": false, "feedback": "Incorrect."}')
        mock_llm = MagicMock()
        mock_llm.chat.completions.create = AsyncMock(return_value=wrong_resp)

        req_body = ChunkEvaluateRequest(
            questions=[ChunkQuestion(index=0, text="Explain whole numbers.")],
            answers=[ChunkAnswerItem(index=0, answer_text="Wrong answer.")],
            mode_used="NORMAL",
        )

        fake_request = StarletteRequest({
            "type": "http", "method": "POST",
            "path": f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/evaluate",
            "query_string": b"", "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 0),
        })

        with (
            patch("api.teaching_router.teaching_svc") as mock_svc,
            patch("api.teaching_router.chunk_ksvc"),
        ):
            mock_svc.openai = mock_llm

            response = await evaluate_chunk_answers(
                request=fake_request,
                session_id=_SESSION_ID,
                chunk_id=_CHUNK_ID,
                req=req_body,
                db=mock_db,
            )

        assert response.passed is False, "Precondition: evaluation must fail"
        assert response.chunk_progress is None, (
            f"chunk_progress must be None when student fails evaluation. "
            f"Got: {response.chunk_progress}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CQ-08  evaluate sets all_study_complete=True when last required chunk passes
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvaluateSetsAllStudyCompleteOnLastChunk:
    """BC-CQ-08: When the evaluated chunk is the last required chunk and passes,
    all_study_complete must be True.

    Business rule: the exam gate only unlocks when every required teaching/chapter_review
    and non-optional exercise chunk has a passing score in chunk_progress. Passing the
    last required chunk in a single Q&A evaluation triggers this gate.
    """

    async def test_all_study_complete_true_when_last_chunk_passes(self):
        """Should set all_study_complete=True when evaluated chunk completes all required chunks.

        Arrange: concept has exactly 1 required teaching chunk (the one being evaluated);
                 session.chunk_progress is empty; LLM marks the answer correct.
        Act:     call evaluate_chunk_answers().
        Assert:  response.all_study_complete is True.
        """
        from api.teaching_router import evaluate_chunk_answers
        from api.teaching_schemas import (
            ChunkEvaluateRequest, ChunkQuestion, ChunkAnswerItem,
        )
        from starlette.requests import Request as StarletteRequest

        session = _make_session()
        session.chunk_progress = {}

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=session)
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        # The concept has exactly 1 required chunk — the one we're evaluating
        mock_chunk_ksvc = MagicMock()
        mock_chunk_ksvc.get_chunks_for_concept = AsyncMock(return_value=[
            {"id": _CHUNK_ID, "heading": "Use Addition Notation"},  # teaching type
        ])

        correct_resp = _make_llm_response('{"correct": true, "feedback": "Correct!"}')
        mock_llm = MagicMock()
        mock_llm.chat.completions.create = AsyncMock(return_value=correct_resp)

        req_body = ChunkEvaluateRequest(
            questions=[ChunkQuestion(index=0, text="Describe addition.")],
            answers=[ChunkAnswerItem(index=0, answer_text="Adding two numbers together.")],
            mode_used="NORMAL",
        )

        fake_request = StarletteRequest({
            "type": "http", "method": "POST",
            "path": f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/evaluate",
            "query_string": b"", "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 0),
        })

        with (
            patch("api.teaching_router.teaching_svc") as mock_svc,
            patch("api.teaching_router.chunk_ksvc", mock_chunk_ksvc),
        ):
            mock_svc.openai = mock_llm

            response = await evaluate_chunk_answers(
                request=fake_request,
                session_id=_SESSION_ID,
                chunk_id=_CHUNK_ID,
                req=req_body,
                db=mock_db,
            )

        assert response.passed is True, "Precondition: evaluation must pass"
        assert response.all_study_complete is True, (
            f"Expected all_study_complete=True when last required chunk passes, "
            f"got all_study_complete={response.all_study_complete}"
        )

    async def test_all_study_complete_false_when_other_chunks_remain(self):
        """Should set all_study_complete=False when other required chunks are still incomplete.

        Arrange: concept has 2 teaching chunks; only 1 is being evaluated now;
                 session.chunk_progress starts empty; LLM marks the answer correct.
        Act:     call evaluate_chunk_answers().
        Assert:  response.all_study_complete is False (second chunk still pending).
        """
        from api.teaching_router import evaluate_chunk_answers
        from api.teaching_schemas import (
            ChunkEvaluateRequest, ChunkQuestion, ChunkAnswerItem,
        )
        from starlette.requests import Request as StarletteRequest

        _second_chunk_id = str(uuid.uuid4())

        session = _make_session()
        session.chunk_progress = {}

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=session)
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        # Two required teaching chunks — evaluating only the first
        mock_chunk_ksvc = MagicMock()
        mock_chunk_ksvc.get_chunks_for_concept = AsyncMock(return_value=[
            {"id": _CHUNK_ID, "heading": "Use Addition Notation"},
            {"id": _second_chunk_id, "heading": "Use Subtraction Notation"},
        ])

        correct_resp = _make_llm_response('{"correct": true, "feedback": "Correct!"}')
        mock_llm = MagicMock()
        mock_llm.chat.completions.create = AsyncMock(return_value=correct_resp)

        req_body = ChunkEvaluateRequest(
            questions=[ChunkQuestion(index=0, text="Describe addition.")],
            answers=[ChunkAnswerItem(index=0, answer_text="Adding two numbers together.")],
            mode_used="NORMAL",
        )

        fake_request = StarletteRequest({
            "type": "http", "method": "POST",
            "path": f"/api/v2/sessions/{_SESSION_ID}/chunks/{_CHUNK_ID}/evaluate",
            "query_string": b"", "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 0),
        })

        with (
            patch("api.teaching_router.teaching_svc") as mock_svc,
            patch("api.teaching_router.chunk_ksvc", mock_chunk_ksvc),
        ):
            mock_svc.openai = mock_llm

            response = await evaluate_chunk_answers(
                request=fake_request,
                session_id=_SESSION_ID,
                chunk_id=_CHUNK_ID,
                req=req_body,
                db=mock_db,
            )

        assert response.passed is True, "Precondition: evaluation must pass"
        assert response.all_study_complete is False, (
            f"Expected all_study_complete=False when second chunk still pending, "
            f"got all_study_complete={response.all_study_complete}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BC-CQ-09  exercise chunks skip Q&A (questions field is empty list)
# ═══════════════════════════════════════════════════════════════════════════════

class TestExerciseChunksSkipQuestions:
    """BC-CQ-09: Chunks classified as 'exercise' must not receive open-ended questions.

    Business rule: exercise chunks (Practice Makes Perfect, Everyday Math, Mixed Practice,
    etc.) are already structured as practice problems. Overlaying open-ended comprehension
    questions would create redundant and confusing assessment for students.
    """

    async def test_exercise_chunk_returns_empty_questions(self):
        """A chunk with an exercise heading should return an empty questions list.

        Arrange: heading contains 'exercises' keyword (exercise type);
                 LLM returns valid cards for the first call only (no second call expected).
        Act:     call generate_per_chunk().
        Assert:  result["questions"] is an empty list.
        """
        # For exercise chunks, only 1 LLM call is expected (card generation).
        # Providing a single response — if a second call happened it would raise StopIteration.
        from api.teaching_service import TeachingService

        svc = TeachingService()

        cards_response = _make_llm_response(_VALID_CARD_JSON)
        mock_llm = MagicMock()
        mock_llm.chat.completions.create = AsyncMock(return_value=cards_response)
        svc.openai = mock_llm

        mock_ksvc = MagicMock()
        # Exercise heading — classified as 'exercise' by _classify_chunk_type in generate_per_chunk
        exercise_chunk = _make_fake_chunk(heading="Section Exercises", text=_SHORT_TEXT)
        mock_ksvc.get_chunk = AsyncMock(return_value=exercise_chunk)
        mock_ksvc.get_chunk_images = AsyncMock(return_value=[])
        mock_ksvc.get_concept_detail = AsyncMock(return_value={"images": []})
        mock_ksvc.get_chunks_for_concept = AsyncMock(return_value=[exercise_chunk])
        svc._chunk_ksvc = mock_ksvc

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=_make_student())

        session = _make_session()

        result = await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        assert isinstance(result, dict), "generate_per_chunk must return a dict"
        questions = result.get("questions", "NOT_PRESENT")
        assert questions != "NOT_PRESENT", (
            "Result dict must have a 'questions' key even for exercise chunks"
        )
        assert questions == [], (
            f"Expected questions=[] for exercise chunk, got: {questions}"
        )

    async def test_exercise_chunk_makes_only_one_llm_call(self):
        """An exercise chunk must not trigger a second LLM call for question generation.

        Arrange: exercise heading; single LLM response configured.
        Act:     call generate_per_chunk().
        Assert:  openai.chat.completions.create was called exactly once (no Q-gen call).
        """
        from api.teaching_service import TeachingService

        svc = TeachingService()

        cards_response = _make_llm_response(_VALID_CARD_JSON)
        mock_llm = MagicMock()
        mock_llm.chat.completions.create = AsyncMock(return_value=cards_response)
        svc.openai = mock_llm

        mock_ksvc = MagicMock()
        exercise_chunk = _make_fake_chunk(heading="Practice Makes Perfect", text=_SHORT_TEXT)
        mock_ksvc.get_chunk = AsyncMock(return_value=exercise_chunk)
        mock_ksvc.get_chunk_images = AsyncMock(return_value=[])
        mock_ksvc.get_concept_detail = AsyncMock(return_value={"images": []})
        mock_ksvc.get_chunks_for_concept = AsyncMock(return_value=[exercise_chunk])
        svc._chunk_ksvc = mock_ksvc

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=_make_student())

        session = _make_session()

        await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

        call_count = svc.openai.chat.completions.create.call_count
        # Exercise chunks go through the is_exercise_chunk path in generate_per_chunk
        # which uses _chat() (1 call). No question generation call should follow.
        assert call_count == 1, (
            f"Expected exactly 1 LLM call for exercise chunk (no Q-gen), "
            f"got {call_count} calls"
        )

    async def test_multiple_exercise_heading_patterns_all_skip_questions(self):
        """All exercise-heading variants must produce empty questions.

        Arrange: 4 exercise headings known to the system.
        Act:     call generate_per_chunk() for each.
        Assert:  all return questions=[].
        """
        from api.teaching_service import TeachingService

        exercise_headings = [
            "Practice Makes Perfect",
            "Everyday Math",
            "Mixed Practice",
            "Review Exercises",
        ]

        for heading in exercise_headings:
            svc = TeachingService()

            cards_response = _make_llm_response(_VALID_CARD_JSON)
            mock_llm = MagicMock()
            mock_llm.chat.completions.create = AsyncMock(return_value=cards_response)
            svc.openai = mock_llm

            mock_ksvc = MagicMock()
            ex_chunk = _make_fake_chunk(heading=heading, text=_SHORT_TEXT)
            mock_ksvc.get_chunk = AsyncMock(return_value=ex_chunk)
            mock_ksvc.get_chunk_images = AsyncMock(return_value=[])
            mock_ksvc.get_concept_detail = AsyncMock(return_value={"images": []})
            mock_ksvc.get_chunks_for_concept = AsyncMock(return_value=[ex_chunk])
            svc._chunk_ksvc = mock_ksvc

            mock_db = AsyncMock()
            mock_db.get = AsyncMock(return_value=_make_student())
            session = _make_session()

            result = await svc.generate_per_chunk(session, mock_db, _CHUNK_ID)

            questions = result.get("questions", "NOT_PRESENT")
            assert questions == [], (
                f"Expected questions=[] for exercise heading '{heading}', got: {questions}"
            )
