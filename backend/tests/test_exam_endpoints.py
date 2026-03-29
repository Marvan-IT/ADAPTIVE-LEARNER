"""
test_exam_endpoints.py
======================
Unit tests for the three Socratic exam endpoints:
  POST /api/v2/sessions/{session_id}/exam/start
  POST /api/v2/sessions/{session_id}/exam/submit
  POST /api/v2/sessions/{session_id}/exam/retry

Business criteria covered:
  BC-EXAM-01  Every teaching subsection gets exactly one exam question on exam/start.
  BC-EXAM-02  Chunks with non-teaching headings are excluded from exam questions.
  BC-EXAM-03  404 returned when concept has no chunks at all.
  BC-EXAM-04  409 returned when concept has no teaching chunks (all structural headings).
  BC-EXAM-05  Student passes when answering >= 65% of questions correctly.
  BC-EXAM-06  Student fails when answering < 65% of questions correctly.
  BC-EXAM-07  Passing the exam inserts a StudentMastery row (marks concept as mastered).
  BC-EXAM-08  Passing marks session.concept_mastered=True and phase="COMPLETED".
  BC-EXAM-09  Failing records failed_chunk_ids so retry routing knows what to repeat.
  BC-EXAM-10  retry_options excludes "targeted" after 3 attempts (exam_attempt == 3).
  BC-EXAM-11  retry_options includes "targeted" when exam_attempt < 3.
  BC-EXAM-12  Targeted retry returns HTTP 409 when exam_attempt >= 3.
  BC-EXAM-13  Targeted retry returns HTTP 200 when exam_attempt < 3.
  BC-EXAM-14  full_redo retry is always available regardless of attempt count.
  BC-EXAM-15  exam/start stores questions in session.exam_scores for later evaluation.
  BC-EXAM-16  exam/submit returns 400 when no exam questions have been started.
  BC-EXAM-17  exam/submit returns 400 when answer count does not match question count.
  BC-EXAM-18  exam/retry returns ExamRetryResponse with exam_phase="retry_study".

Test strategy
-------------
- All tests are unit-level: they mock the DB, OpenAI client, and chunk_ksvc.
- No live database, ChromaDB, or OpenAI required.
- The real router code is exercised via httpx.AsyncClient + FastAPI dependency_overrides.
- asyncio_mode = auto (pytest.ini) — no @pytest.mark.asyncio decorator needed.
"""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── Break circular import teaching_router ↔ api.main ─────────────────────────
def _install_api_main_stub():
    import sys as _sys
    if "api.main" not in _sys.modules:
        stub = MagicMock()
        try:
            from slowapi import Limiter
            from slowapi.util import get_remote_address
            stub.limiter = Limiter(key_func=get_remote_address)
        except ImportError:
            stub.limiter = MagicMock()
        _sys.modules["api.main"] = stub

_install_api_main_stub()

import httpx
from fastapi import FastAPI

import api.teaching_router as teaching_router_module
from api.rate_limiter import limiter
from db.connection import get_db


# ── Rate limiter reset fixture ────────────────────────────────────────────────
# The exam/submit endpoint has a 10/minute rate limit.  Tests all use the same
# source IP (127.0.0.1) and share the module-level in-memory limiter, so without
# a reset the 11th test in a test run triggers HTTP 429.
# Resetting the storage before each test class avoids this without touching
# production code.

@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset the in-memory rate limiter storage before each test."""
    try:
        limiter._storage.reset()
    except Exception:
        pass
    yield


# ── Test constants ─────────────────────────────────────────────────────────────

_STUDENT_ID = uuid.uuid4()
_SESSION_ID = uuid.uuid4()
_CONCEPT_ID = "prealgebra_1.1"
_BOOK_SLUG = "prealgebra"

# ── LLM response builders ─────────────────────────────────────────────────────

def _question_llm_response(question_text: str = "Explain the addition notation.") -> MagicMock:
    """Mock a single LLM response for question generation."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps({"question": question_text})
    return response


def _eval_llm_response(correct: bool, feedback: str = "Good answer.") -> MagicMock:
    """Mock a single LLM response for answer evaluation."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps(
        {"correct": correct, "feedback": feedback}
    )
    return response


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_fake_session(
    *,
    concept_id: str = _CONCEPT_ID,
    book_slug: str = _BOOK_SLUG,
    chunk_index: int = 0,
    exam_attempt: int = 0,
    exam_scores: dict | None = None,
    failed_chunk_ids: list | None = None,
):
    s = MagicMock()
    s.id = _SESSION_ID
    s.student_id = _STUDENT_ID
    s.concept_id = concept_id
    s.book_slug = book_slug
    s.phase = "CARDS_DONE"
    s.style = "default"
    s.chunk_index = chunk_index
    s.started_at = datetime.now(timezone.utc)
    s.completed_at = None
    s.check_score = None
    s.concept_mastered = False
    s.exam_attempt = exam_attempt
    s.exam_scores = exam_scores
    s.exam_phase = None
    s.failed_chunk_ids = failed_chunk_ids
    return s


def _make_chunk_dict(
    *,
    chunk_id: str | None = None,
    order_index: int = 0,
    heading: str = "Use Addition Notation",
    text: str = "Addition notation uses the plus sign.",
) -> dict:
    """Build a chunk dict as returned by chunk_ksvc.get_chunks_for_concept()."""
    return {
        "id": chunk_id or str(uuid.uuid4()),
        "book_slug": _BOOK_SLUG,
        "concept_id": _CONCEPT_ID,
        "section": "1.1 Introduction",
        "order_index": order_index,
        "heading": heading,
        "text": text,
        "latex": [],
        "images": [],
    }


class _ExamMockDb:
    """
    Configurable async DB mock for exam endpoint handlers.

    db.get(TeachingSession, pk) is the primary lookup;
    db.execute() handles StudentMastery queries (passed/retry scenarios).
    """

    def __init__(
        self,
        *,
        session=None,
        existing_mastery_row=None,
    ):
        self._session = session
        self._existing_mastery_row = existing_mastery_row

        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.add = MagicMock()
        self._execute_call_count = 0

    async def get(self, cls, pk):
        from db.models import TeachingSession
        if cls == TeachingSession and pk == _SESSION_ID:
            return self._session
        return None

    async def execute(self, stmt):
        """
        Handles StudentMastery select (for race-condition guard in submit) and
        ChunkImage batch query in retry handler.
        """
        self._execute_call_count += 1
        result = MagicMock()
        # Default: StudentMastery check returns None (no existing row)
        result.scalar_one_or_none.return_value = self._existing_mastery_row
        result.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        result.fetchall.return_value = []
        return result


def _make_mock_llm_client(llm_responses: list[MagicMock]) -> MagicMock:
    """
    Build an OpenAI-compatible async mock that returns responses sequentially.
    Each response in llm_responses is returned in order per call.
    """
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=llm_responses)
    return client


def _make_mock_svc(chunks: list[dict], llm_responses: list[MagicMock]) -> MagicMock:
    """Build a teaching_svc mock with chunk_ksvc wired and LLM responses pre-loaded."""
    mock_ksvc = MagicMock()
    mock_ksvc.get_chunks_for_concept = AsyncMock(return_value=chunks)

    llm_client = _make_mock_llm_client(llm_responses)

    mock_svc = MagicMock()
    mock_svc.openai = llm_client

    return mock_svc, mock_ksvc


def _build_test_app(mock_db_instance, mock_svc, mock_ksvc) -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter

    async def _get_test_db():
        yield mock_db_instance

    app.dependency_overrides[get_db] = _get_test_db

    teaching_router_module.teaching_svc = mock_svc
    teaching_router_module.chunk_ksvc = mock_ksvc

    app.include_router(teaching_router_module.router)
    return app


async def _post(app: FastAPI, path: str, body: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=body)


# ═══════════════════════════════════════════════════════════════════════════════
# BC-EXAM-01/02/03/04  exam/start — question generation
# ═══════════════════════════════════════════════════════════════════════════════

class TestExamStart:
    """Tests for POST /sessions/{id}/exam/start."""

    @pytest.mark.asyncio
    async def test_exam_start_returns_questions_for_each_teaching_chunk(self):
        """
        Business criterion: Every exam_question_source chunk gets CHUNK_EXAM_QUESTIONS_PER_CHUNK
        exam questions (currently 2 per chunk).  Two exam source chunks → 4 questions total.

        _get_chunk_type() returns "exam_question_source" for headings that contain
        "(exercises)" but not "everyday math", "writing exercises", or "practice makes perfect".
        """
        from config import CHUNK_EXAM_QUESTIONS_PER_CHUNK
        chunk_a = _make_chunk_dict(order_index=0, heading="Addition Notation (Exercises)")
        chunk_b = _make_chunk_dict(order_index=1, heading="Properties of Addition (Exercises)")

        # Need CHUNK_EXAM_QUESTIONS_PER_CHUNK responses per chunk
        llm_responses = [
            _question_llm_response(f"Question {i} for chunk.")
            for i in range(2 * CHUNK_EXAM_QUESTIONS_PER_CHUNK)
        ]
        session = _make_fake_session()
        mock_svc, mock_ksvc = _make_mock_svc([chunk_a, chunk_b], llm_responses)
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(app, f"/api/v2/sessions/{_SESSION_ID}/exam/start",
                           {"concept_id": _CONCEPT_ID})

        assert resp.status_code == 200
        data = resp.json()
        expected_total = 2 * CHUNK_EXAM_QUESTIONS_PER_CHUNK
        assert data["total_questions"] == expected_total
        assert len(data["questions"]) == expected_total

    @pytest.mark.asyncio
    async def test_exam_start_excludes_non_teaching_chunks(self):
        """
        Business criterion: Non-exam-source chunks (teaching, practice, exercise_gate,
        everyday-math) must not produce exam questions.
        Three chunks: 1 teaching + 1 everyday-math-excluded + 1 exam_question_source → 1 question.

        _get_chunk_type() rules:
          - "Addition Notation"        → "teaching"             (excluded)
          - "Everyday Math (Exercises)"→ "practice"             (excluded)
          - "Review (Exercises)"       → "exam_question_source" (included)
        """
        from config import CHUNK_EXAM_QUESTIONS_PER_CHUNK
        non_exam_a = _make_chunk_dict(order_index=0, heading="Learning Objectives")
        non_exam_b = _make_chunk_dict(order_index=1, heading="Addition Notation")
        exam_source = _make_chunk_dict(order_index=2, heading="Review (Exercises)")

        # Only exam_source generates questions; need CHUNK_EXAM_QUESTIONS_PER_CHUNK responses
        llm_responses = [
            _question_llm_response(f"Question {i} for review.")
            for i in range(CHUNK_EXAM_QUESTIONS_PER_CHUNK)
        ]
        session = _make_fake_session()
        mock_svc, mock_ksvc = _make_mock_svc(
            [non_exam_a, non_exam_b, exam_source], llm_responses
        )
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(app, f"/api/v2/sessions/{_SESSION_ID}/exam/start",
                           {"concept_id": _CONCEPT_ID})

        # Only the exam_question_source chunk produces questions — non-exam chunks are excluded.
        assert resp.status_code == 200
        assert resp.json()["total_questions"] == CHUNK_EXAM_QUESTIONS_PER_CHUNK

    @pytest.mark.asyncio
    async def test_exam_start_returns_404_when_no_chunks_exist(self):
        """
        Business criterion: 404 is returned when the concept has no chunks —
        signals that the concept is not in the chunk-based architecture.
        """
        session = _make_fake_session()
        mock_svc, mock_ksvc = _make_mock_svc([], [])
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(app, f"/api/v2/sessions/{_SESSION_ID}/exam/start",
                           {"concept_id": _CONCEPT_ID})

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_exam_start_returns_409_when_all_chunks_are_structural(self):
        """
        Business criterion: 409 is returned when all chunks have non-teaching
        headings ('Learning Objectives', 'Key Terms') — no exam is possible.
        """
        structural_a = _make_chunk_dict(order_index=0, heading="Learning Objectives")
        structural_b = _make_chunk_dict(order_index=1, heading="Key Terms")

        session = _make_fake_session()
        mock_svc, mock_ksvc = _make_mock_svc([structural_a, structural_b], [])
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(app, f"/api/v2/sessions/{_SESSION_ID}/exam/start",
                           {"concept_id": _CONCEPT_ID})

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_exam_start_response_contains_pass_threshold(self):
        """
        Business criterion: The response includes the pass_threshold constant so
        the frontend can display it to the student before they start.
        Uses an exam_question_source chunk heading (contains "(exercises)" without
        excluded substrings) so the endpoint returns 200.
        """
        from config import CHUNK_EXAM_PASS_RATE, CHUNK_EXAM_QUESTIONS_PER_CHUNK
        chunk = _make_chunk_dict(heading="Addition Review (Exercises)")
        # Need CHUNK_EXAM_QUESTIONS_PER_CHUNK LLM responses for this one exam source chunk
        llm_responses = [
            _question_llm_response(f"What is addition? (Q{i})")
            for i in range(CHUNK_EXAM_QUESTIONS_PER_CHUNK)
        ]
        session = _make_fake_session()
        mock_svc, mock_ksvc = _make_mock_svc([chunk], llm_responses)
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(app, f"/api/v2/sessions/{_SESSION_ID}/exam/start",
                           {"concept_id": _CONCEPT_ID})

        assert resp.status_code == 200
        assert resp.json()["pass_threshold"] == pytest.approx(CHUNK_EXAM_PASS_RATE)

    @pytest.mark.asyncio
    async def test_exam_start_returns_404_for_unknown_session(self):
        """
        Business criterion: Requesting an exam for an unknown session returns 404.
        """
        unknown_id = uuid.uuid4()
        session = _make_fake_session()
        mock_svc, mock_ksvc = _make_mock_svc([], [])
        db = _ExamMockDb(session=None)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(app, f"/api/v2/sessions/{unknown_id}/exam/start",
                           {"concept_id": _CONCEPT_ID})

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_exam_start_stores_questions_in_session_exam_scores(self):
        """
        Business criterion (BC-EXAM-15): Questions are persisted on the session
        so that exam/submit can evaluate them without re-generating.
        Uses an exam_question_source chunk heading so the endpoint returns 200.
        """
        from config import CHUNK_EXAM_QUESTIONS_PER_CHUNK
        chunk_id = str(uuid.uuid4())
        chunk = _make_chunk_dict(chunk_id=chunk_id, heading="Addition Review (Exercises)")
        # Need CHUNK_EXAM_QUESTIONS_PER_CHUNK LLM responses for this one exam source chunk
        llm_responses = [
            _question_llm_response(f"What is addition? (Q{i})")
            for i in range(CHUNK_EXAM_QUESTIONS_PER_CHUNK)
        ]
        session = _make_fake_session()
        mock_svc, mock_ksvc = _make_mock_svc([chunk], llm_responses)
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        await _post(app, f"/api/v2/sessions/{_SESSION_ID}/exam/start",
                    {"concept_id": _CONCEPT_ID})

        # The handler sets session.exam_scores before commit
        assert session.exam_scores is not None
        assert "questions" in session.exam_scores
        assert len(session.exam_scores["questions"]) == CHUNK_EXAM_QUESTIONS_PER_CHUNK
        assert session.exam_scores["questions"][0]["chunk_id"] == chunk_id


# ═══════════════════════════════════════════════════════════════════════════════
# BC-EXAM-05/06/07/08/09/10/11  exam/submit — scoring and mastery
# ═══════════════════════════════════════════════════════════════════════════════

class TestExamSubmit:
    """Tests for POST /sessions/{id}/exam/submit."""

    def _make_stored_questions(self, n: int) -> dict:
        """Build an exam_scores dict with n teaching questions pre-stored."""
        questions = []
        for i in range(n):
            chunk_id = str(uuid.uuid4())
            questions.append({
                "question_index": i,
                "chunk_id": chunk_id,
                "chunk_heading": f"Topic {i}",
                "question_text": f"Explain topic {i}.",
            })
        return {
            "questions": questions,
            "answers": {},
        }

    def _make_answers(self, n: int) -> list[dict]:
        return [{"question_index": i, "answer_text": f"My answer to {i}"} for i in range(n)]

    @pytest.mark.asyncio
    async def test_exam_submit_pass_at_75_percent(self):
        """
        Business criterion (BC-EXAM-05): Student passes when answering >= 65%
        correctly. 3 correct out of 4 = 75% ≥ 65% → passed=True.
        """
        stored = self._make_stored_questions(4)
        session = _make_fake_session(exam_scores=stored, exam_attempt=0)

        # 3 correct, 1 wrong
        llm_responses = [
            _eval_llm_response(True),
            _eval_llm_response(True),
            _eval_llm_response(True),
            _eval_llm_response(False),
        ]
        mock_svc, mock_ksvc = _make_mock_svc([], llm_responses)
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/submit",
            {"answers": self._make_answers(4)}
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is True
        assert data["score"] >= 0.65

    @pytest.mark.asyncio
    async def test_exam_submit_pass_at_exact_65_percent(self):
        """
        Business criterion (BC-EXAM-05): Score exactly at the CHUNK_EXAM_PASS_RATE threshold passes.
        The pass rate is now 70% (CHUNK_EXAM_PASS_RATE=0.70). 65% is below threshold → failed=True.

        This test now verifies the 70% threshold behaviour instead of 65%.
        14 correct out of 20 = 70% = exactly at threshold → passed=True.
        """
        from config import CHUNK_EXAM_PASS_RATE
        stored = self._make_stored_questions(20)
        session = _make_fake_session(exam_scores=stored, exam_attempt=0)

        # 14 correct, 6 wrong = 70% = exactly at CHUNK_EXAM_PASS_RATE threshold
        n_correct = round(CHUNK_EXAM_PASS_RATE * 20)
        n_wrong = 20 - n_correct
        llm_responses = (
            [_eval_llm_response(True)] * n_correct
            + [_eval_llm_response(False)] * n_wrong
        )
        mock_svc, mock_ksvc = _make_mock_svc([], llm_responses)
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/submit",
            {"answers": self._make_answers(20)}
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is True
        assert data["score"] == pytest.approx(CHUNK_EXAM_PASS_RATE)

    @pytest.mark.asyncio
    async def test_exam_submit_fail_below_65_percent(self):
        """
        Business criterion (BC-EXAM-06): Student must demonstrate sufficient
        understanding to pass. 2 correct out of 4 = 50% < 65% → passed=False.
        """
        stored = self._make_stored_questions(4)
        session = _make_fake_session(exam_scores=stored, exam_attempt=0)

        # 2 correct, 2 wrong = 50%
        llm_responses = [
            _eval_llm_response(True),
            _eval_llm_response(True),
            _eval_llm_response(False),
            _eval_llm_response(False),
        ]
        mock_svc, mock_ksvc = _make_mock_svc([], llm_responses)
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/submit",
            {"answers": self._make_answers(4)}
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is False
        assert len(data["failed_chunks"]) > 0

    @pytest.mark.asyncio
    async def test_exam_submit_records_mastery_on_pass(self):
        """
        Business criterion (BC-EXAM-07): Passing the exam inserts a StudentMastery
        row so the student's concept mastery is persisted.
        """
        stored = self._make_stored_questions(2)
        session = _make_fake_session(exam_scores=stored, exam_attempt=0)

        llm_responses = [
            _eval_llm_response(True),
            _eval_llm_response(True),
        ]
        mock_svc, mock_ksvc = _make_mock_svc([], llm_responses)
        db = _ExamMockDb(session=session, existing_mastery_row=None)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/submit",
            {"answers": self._make_answers(2)}
        )

        # A new StudentMastery row must have been added
        db.add.assert_called_once()
        added_obj = db.add.call_args[0][0]
        from db.models import StudentMastery
        assert isinstance(added_obj, StudentMastery)
        assert added_obj.student_id == _STUDENT_ID
        assert added_obj.concept_id == _CONCEPT_ID

    @pytest.mark.asyncio
    async def test_exam_submit_marks_session_mastered_on_pass(self):
        """
        Business criterion (BC-EXAM-08): Passing the exam sets
        session.concept_mastered=True and session.phase="COMPLETED".
        """
        stored = self._make_stored_questions(2)
        session = _make_fake_session(exam_scores=stored, exam_attempt=0)

        llm_responses = [
            _eval_llm_response(True),
            _eval_llm_response(True),
        ]
        mock_svc, mock_ksvc = _make_mock_svc([], llm_responses)
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/submit",
            {"answers": self._make_answers(2)}
        )

        assert session.concept_mastered is True
        assert session.phase == "COMPLETED"

    @pytest.mark.asyncio
    async def test_exam_submit_records_failed_chunk_ids_on_fail(self):
        """
        Business criterion (BC-EXAM-09): Failing records failed_chunk_ids on the
        session so the retry handler knows which chunks to target.
        """
        stored = self._make_stored_questions(3)
        session = _make_fake_session(exam_scores=stored, exam_attempt=0)

        # First 2 correct, last 1 wrong (67% passes BUT let's do all fail to check IDs)
        # Use 1 correct, 2 wrong (33% < 65%) to guarantee fail + failed_chunk_ids
        llm_responses = [
            _eval_llm_response(True),
            _eval_llm_response(False),
            _eval_llm_response(False),
        ]
        mock_svc, mock_ksvc = _make_mock_svc([], llm_responses)
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/submit",
            {"answers": self._make_answers(3)}
        )

        assert session.failed_chunk_ids is not None
        assert len(session.failed_chunk_ids) == 2

    @pytest.mark.asyncio
    async def test_exam_submit_retry_options_excludes_targeted_after_3_attempts(self):
        """
        Business criterion (BC-EXAM-10): Frontend receives correct retry options.
        When exam_attempt is already 2 (about to become 3), "targeted" must be
        excluded from retry_options.
        """
        stored = self._make_stored_questions(2)
        # exam_attempt=2; after increment it becomes 3 → targeted blocked
        session = _make_fake_session(exam_scores=stored, exam_attempt=2)

        llm_responses = [
            _eval_llm_response(False),
            _eval_llm_response(False),
        ]
        mock_svc, mock_ksvc = _make_mock_svc([], llm_responses)
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/submit",
            {"answers": self._make_answers(2)}
        )

        assert resp.status_code == 200
        retry_options = resp.json()["retry_options"]
        assert "targeted" not in retry_options
        assert "full_redo" in retry_options

    @pytest.mark.asyncio
    async def test_exam_submit_retry_options_includes_targeted_before_3_attempts(self):
        """
        Business criterion (BC-EXAM-11): Frontend receives "targeted" as an option
        when exam_attempt is 0 (first attempt) so the student can focus on weak areas.
        """
        stored = self._make_stored_questions(2)
        # exam_attempt=0; after increment it becomes 1 → targeted allowed
        session = _make_fake_session(exam_scores=stored, exam_attempt=0)

        llm_responses = [
            _eval_llm_response(False),
            _eval_llm_response(False),
        ]
        mock_svc, mock_ksvc = _make_mock_svc([], llm_responses)
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/submit",
            {"answers": self._make_answers(2)}
        )

        assert resp.status_code == 200
        retry_options = resp.json()["retry_options"]
        assert "targeted" in retry_options
        assert "full_redo" in retry_options

    @pytest.mark.asyncio
    async def test_exam_submit_returns_400_when_no_questions_stored(self):
        """
        Business criterion (BC-EXAM-16): Submit returns 400 when no exam has been
        started — prevents evaluation without questions.
        """
        # exam_scores is None → no questions stored
        session = _make_fake_session(exam_scores=None)
        mock_svc, mock_ksvc = _make_mock_svc([], [])
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/submit",
            {"answers": [{"question_index": 0, "answer_text": "Some answer"}]}
        )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_exam_submit_returns_400_when_answer_count_mismatch(self):
        """
        Business criterion (BC-EXAM-17): Submit returns 400 when answer count
        does not match question count — prevents partial grading.
        """
        stored = self._make_stored_questions(3)  # 3 questions
        session = _make_fake_session(exam_scores=stored)
        mock_svc, mock_ksvc = _make_mock_svc([], [])
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        # Only 2 answers for 3 questions
        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/submit",
            {"answers": self._make_answers(2)}  # wrong count
        )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_exam_submit_increments_exam_attempt(self):
        """
        Business criterion: exam_attempt must be incremented on each submit so
        the retry limit logic can enforce the 3-attempt cap.
        """
        stored = self._make_stored_questions(1)
        session = _make_fake_session(exam_scores=stored, exam_attempt=1)

        llm_responses = [_eval_llm_response(False)]
        mock_svc, mock_ksvc = _make_mock_svc([], llm_responses)
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/submit",
            {"answers": self._make_answers(1)}
        )

        assert resp.status_code == 200
        assert resp.json()["exam_attempt"] == 2

    @pytest.mark.asyncio
    async def test_exam_submit_does_not_insert_mastery_on_fail(self):
        """
        Business criterion: A failed exam must not create a StudentMastery row —
        only passing demonstrates sufficient concept understanding.
        """
        stored = self._make_stored_questions(2)
        session = _make_fake_session(exam_scores=stored, exam_attempt=0)

        llm_responses = [
            _eval_llm_response(False),
            _eval_llm_response(False),
        ]
        mock_svc, mock_ksvc = _make_mock_svc([], llm_responses)
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/submit",
            {"answers": self._make_answers(2)}
        )

        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_exam_submit_handles_existing_mastery_row_gracefully(self):
        """
        Business criterion: Race-condition guard — if a StudentMastery row already
        exists (parallel request), the endpoint must not crash or raise 500.
        It updates the existing row's mastered_at instead of inserting a new one.
        """
        stored = self._make_stored_questions(2)
        session = _make_fake_session(exam_scores=stored, exam_attempt=0)

        existing_mastery = MagicMock()
        existing_mastery.session_id = None
        existing_mastery.mastered_at = None

        llm_responses = [
            _eval_llm_response(True),
            _eval_llm_response(True),
        ]
        mock_svc, mock_ksvc = _make_mock_svc([], llm_responses)
        db = _ExamMockDb(session=session, existing_mastery_row=existing_mastery)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/submit",
            {"answers": self._make_answers(2)}
        )

        assert resp.status_code == 200
        assert resp.json()["passed"] is True
        # No new add() call — updated existing row
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_exam_submit_total_correct_count_matches_llm_verdicts(self):
        """
        Business criterion: total_correct in the response must equal the number
        of questions the LLM graded as correct.
        """
        stored = self._make_stored_questions(5)
        session = _make_fake_session(exam_scores=stored, exam_attempt=0)

        # 4 correct, 1 wrong
        llm_responses = [
            _eval_llm_response(True),
            _eval_llm_response(True),
            _eval_llm_response(True),
            _eval_llm_response(True),
            _eval_llm_response(False),
        ]
        mock_svc, mock_ksvc = _make_mock_svc([], llm_responses)
        db = _ExamMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/submit",
            {"answers": self._make_answers(5)}
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_correct"] == 4
        assert data["total_questions"] == 5

    @pytest.mark.asyncio
    async def test_exam_submit_returns_404_for_unknown_session(self):
        """Business criterion: Unknown session_id returns 404 on submit."""
        unknown_id = uuid.uuid4()
        db = _ExamMockDb(session=None)
        mock_svc, mock_ksvc = _make_mock_svc([], [])
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{unknown_id}/exam/submit",
            {"answers": [{"question_index": 0, "answer_text": "answer"}]}
        )

        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# BC-EXAM-12/13/14/18  exam/retry — targeted vs full_redo routing
# ═══════════════════════════════════════════════════════════════════════════════

class _RetryMockDb:
    """
    Configurable async DB mock for the retry handler.

    The retry handler calls:
      1. db.get(TeachingSession, session_id)
      2. chunk_ksvc.get_chunks_for_concept(db, book_slug, concept_id)  [via mock_ksvc]
      3. db.execute(select(ChunkImage.chunk_id).distinct())  — for has_images enrichment
    """

    def __init__(self, *, session=None):
        self._session = session
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.add = MagicMock()

    async def get(self, cls, pk):
        from db.models import TeachingSession
        if cls == TeachingSession and pk == _SESSION_ID:
            return self._session
        return None

    async def execute(self, stmt):
        result = MagicMock()
        result.fetchall.return_value = []
        return result


class TestExamRetry:
    """Tests for POST /sessions/{id}/exam/retry."""

    @pytest.mark.asyncio
    async def test_exam_retry_targeted_allowed_under_3_attempts(self):
        """
        Business criterion (BC-EXAM-13): Student can target failed subsections
        for up to 3 retries. exam_attempt=2 → targeted is still allowed.
        Response: HTTP 200, exam_phase='retry_study'.
        """
        failed_id = str(uuid.uuid4())
        session = _make_fake_session(
            exam_attempt=2,
            failed_chunk_ids=[failed_id],
        )
        failed_chunk = _make_chunk_dict(chunk_id=failed_id, heading="Addition Notation")

        mock_ksvc = MagicMock()
        mock_ksvc.get_chunks_for_concept = AsyncMock(return_value=[failed_chunk])
        mock_svc = MagicMock()
        db = _RetryMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/retry",
            {"retry_type": "targeted", "failed_chunk_ids": [failed_id]}
        )

        assert resp.status_code == 200
        assert resp.json()["exam_phase"] == "retry_study"

    @pytest.mark.asyncio
    async def test_exam_retry_targeted_blocked_at_3_attempts(self):
        """
        Business criterion (BC-EXAM-12): After 3 targeted retries, only full
        redo is available. exam_attempt=3 → targeted returns HTTP 409.
        """
        session = _make_fake_session(exam_attempt=3, failed_chunk_ids=[])
        mock_ksvc = MagicMock()
        mock_ksvc.get_chunks_for_concept = AsyncMock(return_value=[])
        mock_svc = MagicMock()
        db = _RetryMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/retry",
            {"retry_type": "targeted", "failed_chunk_ids": []}
        )

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_exam_retry_full_redo_always_allowed(self):
        """
        Business criterion (BC-EXAM-14): full_redo retry is always available
        regardless of how many attempts the student has made.
        exam_attempt=10 (well above cap) → full_redo returns HTTP 200.
        """
        all_chunks = [
            _make_chunk_dict(order_index=0, heading="Addition Notation"),
            _make_chunk_dict(order_index=1, heading="Subtraction Notation"),
        ]
        session = _make_fake_session(exam_attempt=10, failed_chunk_ids=[])
        mock_ksvc = MagicMock()
        mock_ksvc.get_chunks_for_concept = AsyncMock(return_value=all_chunks)
        mock_svc = MagicMock()
        db = _RetryMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/retry",
            {"retry_type": "full_redo", "failed_chunk_ids": []}
        )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_exam_retry_response_has_exam_phase_retry_study(self):
        """
        Business criterion (BC-EXAM-18): The response must include exam_phase='retry_study'
        so the frontend can switch to the correct UI state.
        """
        chunk = _make_chunk_dict(heading="Addition Notation")
        session = _make_fake_session(exam_attempt=1, failed_chunk_ids=[chunk["id"]])
        mock_ksvc = MagicMock()
        mock_ksvc.get_chunks_for_concept = AsyncMock(return_value=[chunk])
        mock_svc = MagicMock()
        db = _RetryMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/retry",
            {"retry_type": "targeted", "failed_chunk_ids": [chunk["id"]]}
        )

        assert resp.status_code == 200
        assert resp.json()["exam_phase"] == "retry_study"

    @pytest.mark.asyncio
    async def test_exam_retry_targeted_returns_only_failed_chunks(self):
        """
        Business criterion: targeted retry returns only the chunks the student
        failed — not the ones they got right — so they can focus on weak areas.
        """
        passed_id = str(uuid.uuid4())
        failed_id = str(uuid.uuid4())
        all_chunks = [
            _make_chunk_dict(chunk_id=passed_id, order_index=0, heading="Topic A"),
            _make_chunk_dict(chunk_id=failed_id, order_index=1, heading="Topic B"),
        ]
        session = _make_fake_session(exam_attempt=1, failed_chunk_ids=[failed_id])
        mock_ksvc = MagicMock()
        mock_ksvc.get_chunks_for_concept = AsyncMock(return_value=all_chunks)
        mock_svc = MagicMock()
        db = _RetryMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/retry",
            {"retry_type": "targeted", "failed_chunk_ids": [failed_id]}
        )

        assert resp.status_code == 200
        retry_chunks = resp.json()["retry_chunks"]
        returned_ids = [c["chunk_id"] for c in retry_chunks]
        assert failed_id in returned_ids
        assert passed_id not in returned_ids

    @pytest.mark.asyncio
    async def test_exam_retry_full_redo_returns_all_chunks(self):
        """
        Business criterion: full_redo retry returns all concept chunks so the
        student can review everything from scratch.
        """
        chunk_a = _make_chunk_dict(order_index=0, heading="Topic A")
        chunk_b = _make_chunk_dict(order_index=1, heading="Topic B")
        session = _make_fake_session(exam_attempt=1, failed_chunk_ids=[chunk_b["id"]])
        mock_ksvc = MagicMock()
        mock_ksvc.get_chunks_for_concept = AsyncMock(return_value=[chunk_a, chunk_b])
        mock_svc = MagicMock()
        db = _RetryMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/retry",
            {"retry_type": "full_redo", "failed_chunk_ids": []}
        )

        assert resp.status_code == 200
        retry_chunks = resp.json()["retry_chunks"]
        assert len(retry_chunks) == 2

    @pytest.mark.asyncio
    async def test_exam_retry_sets_exam_phase_on_session(self):
        """
        Business criterion: exam/retry must update session.exam_phase to 'retry_study'
        so subsequent requests know the session is in retry mode.
        """
        chunk = _make_chunk_dict(heading="Addition Notation")
        session = _make_fake_session(exam_attempt=1, failed_chunk_ids=[chunk["id"]])
        mock_ksvc = MagicMock()
        mock_ksvc.get_chunks_for_concept = AsyncMock(return_value=[chunk])
        mock_svc = MagicMock()
        db = _RetryMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/retry",
            {"retry_type": "targeted", "failed_chunk_ids": [chunk["id"]]}
        )

        assert session.exam_phase == "retry_study"

    @pytest.mark.asyncio
    async def test_exam_retry_returns_400_for_invalid_retry_type(self):
        """
        Business criterion: Invalid retry_type (not 'targeted' or 'full_redo')
        must return HTTP 400.
        """
        session = _make_fake_session(exam_attempt=1)
        mock_ksvc = MagicMock()
        mock_ksvc.get_chunks_for_concept = AsyncMock(return_value=[])
        mock_svc = MagicMock()
        db = _RetryMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/retry",
            {"retry_type": "invalid_type", "failed_chunk_ids": []}
        )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_exam_retry_returns_404_for_unknown_session(self):
        """Business criterion: Unknown session_id returns 404 on retry."""
        unknown_id = uuid.uuid4()
        db = _RetryMockDb(session=None)
        mock_ksvc = MagicMock()
        mock_ksvc.get_chunks_for_concept = AsyncMock(return_value=[])
        mock_svc = MagicMock()
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{unknown_id}/exam/retry",
            {"retry_type": "full_redo", "failed_chunk_ids": []}
        )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_exam_retry_response_includes_exam_attempt_count(self):
        """
        Business criterion: The response must include the current exam_attempt
        count so the frontend can display how many retries remain.
        """
        chunk = _make_chunk_dict(heading="Addition Notation")
        session = _make_fake_session(exam_attempt=1, failed_chunk_ids=[chunk["id"]])
        mock_ksvc = MagicMock()
        mock_ksvc.get_chunks_for_concept = AsyncMock(return_value=[chunk])
        mock_svc = MagicMock()
        db = _RetryMockDb(session=session)
        app = _build_test_app(db, mock_svc, mock_ksvc)

        resp = await _post(
            app, f"/api/v2/sessions/{_SESSION_ID}/exam/retry",
            {"retry_type": "targeted", "failed_chunk_ids": [chunk["id"]]}
        )

        assert resp.status_code == 200
        assert "exam_attempt" in resp.json()
        assert resp.json()["exam_attempt"] == 1
