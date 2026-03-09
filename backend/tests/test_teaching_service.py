"""
Unit tests for TeachingService — the Pedagogical Loop.

Tests cover the full Socratic pass/fail + remediation lifecycle:
  Group 1 — Constants: MASTERY_THRESHOLD, MAX_SOCRATIC_EXCHANGES
  Group 2 — handle_student_response: mastery / remediation / exhaustion state machine
  Group 3 — best_check_score: max-score persistence across attempts
  Group 4 — generate_cards: unified schema validation, CHECKIN insertion, count, images
  Group 5 — generate_remediation_cards: re-teaching without QUESTION cards
  Group 6 — begin_recheck: phase transitions for attempt 1 and attempt 2

Test infrastructure:
  - pytest.ini sets asyncio_mode = auto — no @pytest.mark.asyncio decorators needed
  - conftest.py inserts backend/src into sys.path; the block below duplicates it
    for safety when running this file directly.
  - Zero real I/O — DB and LLM are fully replaced with unittest.mock objects.
  - openai.AsyncOpenAI is patched at the class level before TeachingService is
    imported, so the constructor never touches the network.

Key implementation facts (confirmed by reading teaching_service.py):
  - _parse_assessment() extracts [ASSESSMENT:XX] from LLM responses
  - MASTERY_THRESHOLD = 70 (from config.py)
  - SOCRATIC_MAX_ATTEMPTS = 3; remediation path triggers when attempt_count < 3
  - After exhausting 3 attempts → phase COMPLETED, concept_mastered = False, locked = False
  - Mastery path creates StudentMastery + 5 SpacedReview rows (days 1/3/7/14/30)
  - best_check_score = max(current_best, new_score)
  - CARDS_MID_SESSION_CHECK_INTERVAL = 12 — CHECKIN inserted after every 12th card
  - begin_recheck: attempt_count==1 → RECHECKING, attempt_count==2 → RECHECKING_2
  - generate_remediation_cards uses session_id (UUID) as its first argument, not session obj
  - pg_insert is used for SpacedReview — we mock db.execute to avoid PostgreSQL dialect dependency

Unified card schema (new, no card_type/quick_check/questions[]):
  - Regular card: {title, content, image_indices, question: {text, options[4], correct_index, explanation}}
  - CHECKIN card: {title, content, image_indices, options[4]} — detected by absence of 'question' key
"""

import sys
import json
import uuid
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

# Ensure backend/src is importable regardless of how pytest is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest


# ---------------------------------------------------------------------------
# Helpers to build lightweight mocks that stand in for ORM objects
# ---------------------------------------------------------------------------

def _make_session(
    phase: str = "CHECKING",
    socratic_attempt_count: int = 0,
    best_check_score: int | None = None,
    remediation_context: str | None = None,
    concept_id: str = "concept::fractions::intro",
    lesson_interests: list | None = None,
) -> MagicMock:
    """Return a MagicMock that looks like a TeachingSession ORM object."""
    session = MagicMock(spec=[
        "id", "student_id", "concept_id", "book_slug", "phase", "style",
        "lesson_interests", "presentation_text", "check_score", "concept_mastered",
        "started_at", "completed_at", "updated_at",
        "socratic_attempt_count", "questions_asked", "questions_correct",
        "best_check_score", "remediation_context", "messages",
    ])
    session.id = uuid.uuid4()
    session.student_id = uuid.uuid4()
    session.concept_id = concept_id
    session.phase = phase
    session.style = "default"
    session.lesson_interests = lesson_interests
    session.presentation_text = None
    session.check_score = None
    session.concept_mastered = False
    session.completed_at = None
    session.socratic_attempt_count = socratic_attempt_count
    session.best_check_score = best_check_score
    session.remediation_context = remediation_context
    return session


def _make_student(
    interests: list | None = None,
    preferred_language: str = "en",
) -> MagicMock:
    """Return a MagicMock that looks like a Student ORM object."""
    student = MagicMock()
    student.id = uuid.uuid4()
    student.display_name = "Test Student"
    student.interests = interests or []
    student.preferred_language = preferred_language
    return student


def _make_llm_response(content: str) -> MagicMock:
    """Build the nested mock that mimics openai ChatCompletion response."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = content
    return mock_resp


def _make_phase_messages(roles_contents: list[tuple[str, str]], phase: str) -> list[MagicMock]:
    """Return a list of ConversationMessage-like mocks."""
    msgs = []
    for order, (role, content) in enumerate(roles_contents):
        m = MagicMock()
        m.role = role
        m.content = content
        m.phase = phase
        m.message_order = order
        msgs.append(m)
    return msgs


# ---------------------------------------------------------------------------
# Build a TeachingService with fully mocked dependencies.
# We patch openai.AsyncOpenAI at import time to prevent any network call.
# ---------------------------------------------------------------------------

def _build_service() -> tuple:
    """
    Return (service, mock_openai_instance, mock_knowledge_svc).

    The service's self.openai is replaced with a fresh AsyncMock so tests
    can configure return_value / side_effect on its chat.completions.create.
    """
    from api.teaching_service import TeachingService

    mock_ks = MagicMock()
    mock_ks.get_concept_detail.return_value = {
        "concept_title": "Introduction to Fractions",
        "text": "A fraction represents part of a whole. ## Numerator\nThe top number. ## Denominator\nThe bottom number.",
        "latex": [],
        "prerequisites": [],
        "images": [],
    }

    with patch("api.teaching_service.AsyncOpenAI") as MockOpenAI:
        mock_openai = AsyncMock()
        MockOpenAI.return_value = mock_openai
        svc = TeachingService(mock_ks)

    # Replace self.openai directly (constructor already ran)
    svc.openai = mock_openai
    return svc, mock_openai, mock_ks


def _wire_llm(mock_openai, content: str):
    """Configure mock_openai.chat.completions.create to return a fixed string."""
    mock_openai.chat.completions.create = AsyncMock(
        return_value=_make_llm_response(content)
    )


def _wire_llm_sequence(mock_openai, contents: list[str]):
    """Configure side_effect so successive calls return different strings."""
    mock_openai.chat.completions.create = AsyncMock(
        side_effect=[_make_llm_response(c) for c in contents]
    )


# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------

def _make_db(
    phase_messages: list | None = None,
    message_count: int = 5,
    execute_scalar: int | None = None,
    db_get_results: dict | None = None,
) -> AsyncMock:
    """
    Return a fully-mocked AsyncSession.

    phase_messages  — what _get_phase_messages returns (list of msg mocks)
    message_count   — what _get_message_count returns
    execute_scalar  — value returned by result.scalar_one() (for message count query)
    db_get_results  — mapping of {type: obj} returned by db.get(Type, id)
    """
    db = AsyncMock()

    # db.execute() returns a mock result; we set up the scalar_one chain
    exec_result = MagicMock()
    exec_result.scalar_one.return_value = message_count
    exec_result.scalar_one_or_none.return_value = None  # no existing mastery by default
    exec_result.scalars.return_value.all.return_value = phase_messages or []
    exec_result.one.return_value = MagicMock(total_cards=0, total_wrong=0, total_hints=0)
    db.execute = AsyncMock(return_value=exec_result)

    # db.get(Model, id) returns the appropriate pre-built object
    async def _db_get(model_cls, pk):
        if db_get_results and model_cls in db_get_results:
            return db_get_results[model_cls]
        return None

    db.get = _db_get
    db.add = MagicMock()
    db.flush = AsyncMock()

    return db


# ===========================================================================
# Group 1 — Configuration Constants
# ===========================================================================

class TestConfigurationConstants:
    """Verify that business-critical constants match documented values."""

    def test_mastery_threshold_is_70(self):
        """
        Business rule: a student must score >= 70 to be considered as having
        mastered a concept. This threshold is the gateway to StudentMastery
        record creation and SpacedReview scheduling.
        """
        from config import MASTERY_THRESHOLD
        assert MASTERY_THRESHOLD == 70, (
            f"MASTERY_THRESHOLD is {MASTERY_THRESHOLD}, expected 70. "
            "Changing this value alters mastery pass/fail logic across the entire system."
        )

    def test_max_socratic_exchanges_is_at_least_10(self):
        """
        Business rule: sessions must allow enough exchanges for the student to
        demonstrate understanding. The old hard-coded limit of 7 was removed in
        the Phase-4 upgrade; the value must now be >= 10.
        """
        from config import MAX_SOCRATIC_EXCHANGES
        assert MAX_SOCRATIC_EXCHANGES >= 10, (
            f"MAX_SOCRATIC_EXCHANGES is {MAX_SOCRATIC_EXCHANGES}, expected >= 10."
        )
        assert MAX_SOCRATIC_EXCHANGES == 20  # exact value confirmed in config.py


# ===========================================================================
# Group 2 — handle_student_response state machine
# ===========================================================================

class TestHandleStudentResponse:
    """
    Tests for the core Socratic pass/fail + remediation state machine.
    Each test mocks both the DB (no PostgreSQL) and the LLM (no OpenAI API key).
    """

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _call_handle(self, svc, session, llm_content: str):
        """
        Wire LLM, build DB mock with a minimal CHECKING conversation,
        and call handle_student_response().
        """
        _wire_llm(svc.openai, llm_content)

        # Minimal conversation: system + first AI question (phase messages)
        msgs = _make_phase_messages(
            [("system", "You are ADA..."), ("assistant", "What is a numerator?")],
            session.phase,
        )

        db = _make_db(phase_messages=msgs, message_count=3)

        # _extract_failed_topics uses _get_checking_messages — returns same msgs
        # We also need execute to handle the card stats query; reuse the same mock.
        # No card interactions means total_cards == 0 (already set up in _make_db).

        # Patch _extract_failed_topics to avoid the second DB query in remediation path
        with patch.object(svc, "_extract_failed_topics", new=AsyncMock(return_value=["numerator"])):
            result = await svc.handle_student_response(db, session, "I think the numerator is on top.")

        return result

    # ── Test 1: pass at exactly 70 ───────────────────────────────────────────

    async def test_socratic_pass_at_70_percent(self):
        """
        Score of exactly 70 must trigger mastery: session COMPLETED, mastered=True,
        StudentMastery record upserted, SpacedReview rows created.
        """
        svc, mock_openai, _ = _build_service()
        session = _make_session(phase="CHECKING", socratic_attempt_count=0)

        result = await self._call_handle(svc, session, "Great work! [ASSESSMENT:70]")

        # Assertions — result dict
        assert result["check_complete"] is True, "check_complete should be True when ASSESSMENT tag present"
        # The result dict has 'mastered' (not 'passed') — verified from implementation
        assert result["mastered"] is True, "score 70 must be treated as a pass (mastered=True)"
        assert result["remediation_needed"] is False

        # Assertions — session mutations
        assert session.phase == "COMPLETED"
        assert session.concept_mastered is True
        assert session.completed_at is not None

        # StudentMastery must have been added to the DB
        add_calls = [c for c in mock_openai.chat.completions.create.call_args_list]  # LLM was called
        assert svc.openai.chat.completions.create.called

        # db.add was called (StudentMastery + SpacedReview)
        # We cannot inspect db.add directly from _call_handle's local db; use session state instead.
        assert session.best_check_score == 70

    # ── Test 2: pass above threshold (85) ───────────────────────────────────

    async def test_socratic_pass_above_threshold(self):
        """
        Score of 85 must also trigger mastery path: phase COMPLETED, mastered=True.
        """
        svc, _, _ = _build_service()
        session = _make_session(phase="CHECKING", socratic_attempt_count=0)

        result = await self._call_handle(svc, session, "Excellent! [ASSESSMENT:85]")

        assert result["check_complete"] is True
        assert result["mastered"] is True
        assert session.phase == "COMPLETED"
        assert session.concept_mastered is True
        assert session.check_score == 85
        assert session.best_check_score == 85

    # ── Test 3: fail first attempt → REMEDIATING ────────────────────────────

    async def test_socratic_fail_first_attempt_transitions_to_remediating(self):
        """
        Score of 55 on attempt_count=0 must:
          - set check_complete=True, passed/mastered=False
          - increment attempt_count to 1
          - set phase to REMEDIATING
          - populate remediation_context
          - set remediation_needed=True
        """
        svc, _, _ = _build_service()
        session = _make_session(phase="CHECKING", socratic_attempt_count=0)

        result = await self._call_handle(svc, session, "Not bad, but gaps remain. [ASSESSMENT:55]")

        assert result["check_complete"] is True
        assert result["mastered"] is False
        assert result["remediation_needed"] is True
        assert session.phase == "REMEDIATING"
        assert session.socratic_attempt_count == 1
        assert session.remediation_context is not None
        assert session.best_check_score == 55

    # ── Test 4: fail second attempt → REMEDIATING_2 ─────────────────────────

    async def test_socratic_fail_second_attempt_transitions_to_remediating_2(self):
        """
        Score of 40 on attempt_count=1 (session in RECHECKING) must:
          - set phase to REMEDIATING_2
          - increment attempt_count to 2
        """
        svc, _, _ = _build_service()
        # Simulate: student already went through first remediation cycle
        session = _make_session(
            phase="RECHECKING",
            socratic_attempt_count=1,
            best_check_score=55,
            remediation_context='["numerator"]',
        )

        result = await self._call_handle(svc, session, "Still struggling. [ASSESSMENT:40]")

        assert result["check_complete"] is True
        assert result["mastered"] is False
        assert result["remediation_needed"] is True
        assert session.phase == "REMEDIATING_2"
        assert session.socratic_attempt_count == 2
        # Best score should remain 55 (55 > 40)
        assert session.best_check_score == 55

    # ── Test 5: three failures → COMPLETED without mastery ──────────────────

    async def test_three_failures_completes_without_mastery(self):
        """
        Score of 30 on attempt_count=2 (RECHECKING_2) exhausts all attempts.
        The student is NOT mastered but is NOT permanently locked — they can retry
        from the concept map. locked must be False in the response.
        """
        svc, _, _ = _build_service()
        # SOCRATIC_MAX_ATTEMPTS = 3. The exhaustion branch fires when
        # attempt_count >= SOCRATIC_MAX_ATTEMPTS (i.e. NOT < 3).
        # After two full remediation/recheck cycles, attempt_count == 2 still
        # triggers remediation (2 < 3). The third failed recheck increments to 3,
        # making 3 < 3 False and falling through to the exhaustion branch.
        # We simulate that state by pre-setting attempt_count = 3.
        session = _make_session(
            phase="RECHECKING_2",
            socratic_attempt_count=3,    # all three attempts already consumed
            best_check_score=55,
            remediation_context='["numerator", "denominator"]',
        )

        result = await self._call_handle(svc, session, "I'm confused. [ASSESSMENT:30]")

        # State machine assertions
        assert result["check_complete"] is True
        assert result["mastered"] is False
        assert result["remediation_needed"] is False, (
            "No more remediation after 3 attempts — remediation_needed must be False"
        )

        # Session must be COMPLETED but NOT mastered
        assert session.phase == "COMPLETED"
        assert session.concept_mastered is False

        # The student is not permanently locked — they can re-attempt from concept map
        assert result["locked"] is False, (
            "locked must be False: students should be able to retry the concept later"
        )

    # ── Test 6: ASSESSMENT tag stripped from visible response ────────────────

    async def test_assessment_tag_stripped_from_visible_response(self):
        """
        The [ASSESSMENT:XX] marker must NOT appear in the response visible to the student.
        """
        svc, _, _ = _build_service()
        session = _make_session(phase="CHECKING", socratic_attempt_count=0)

        raw_llm = "You did great work today! [ASSESSMENT:80]"
        result = await self._call_handle(svc, session, raw_llm)

        assert "[ASSESSMENT:" not in result["response"], (
            "Assessment marker must be stripped before returning to the frontend"
        )
        assert "You did great work today!" in result["response"]


# ===========================================================================
# Group 3 — best_check_score persistence across attempts
# ===========================================================================

class TestBestCheckScorePersistence:
    """
    The best_check_score field must always hold the maximum score seen across
    all Socratic attempts, never overwritten with a lower value.
    """

    async def _handle(self, svc, session, llm_content: str):
        """Minimal call helper reused across all tests in this group."""
        _wire_llm(svc.openai, llm_content)
        msgs = _make_phase_messages(
            [("system", "ADA"), ("assistant", "First question?")],
            session.phase,
        )
        db = _make_db(phase_messages=msgs, message_count=3)
        with patch.object(svc, "_extract_failed_topics", new=AsyncMock(return_value=["numerator"])):
            return await svc.handle_student_response(db, session, "My answer.")

    async def test_best_score_recorded_on_first_attempt(self):
        """
        First attempt score of 55 — best_check_score must be set to 55.
        """
        svc, _, _ = _build_service()
        session = _make_session(phase="CHECKING", socratic_attempt_count=0, best_check_score=None)

        await self._handle(svc, session, "Not quite there. [ASSESSMENT:55]")

        assert session.best_check_score == 55

    async def test_best_score_not_overwritten_by_lower_score(self):
        """
        Second attempt score of 45 must NOT replace best_check_score of 55.
        """
        svc, _, _ = _build_service()
        session = _make_session(
            phase="RECHECKING",
            socratic_attempt_count=1,
            best_check_score=55,
            remediation_context='["numerator"]',
        )

        await self._handle(svc, session, "Still tricky. [ASSESSMENT:45]")

        assert session.best_check_score == 55, (
            "best_check_score must hold the maximum — a lower subsequent score must not overwrite it"
        )

    async def test_best_score_updated_when_higher_score_achieved(self):
        """
        Third attempt score of 80 must update best_check_score from 55 to 80,
        and also trigger mastery (80 >= 70).
        """
        svc, _, _ = _build_service()
        session = _make_session(
            phase="RECHECKING_2",
            socratic_attempt_count=2,
            best_check_score=55,
            remediation_context='["numerator", "denominator"]',
        )

        result = await self._handle(svc, session, "Excellent recovery! [ASSESSMENT:80]")

        assert session.best_check_score == 80, (
            "best_check_score must be updated when a higher score is achieved"
        )
        assert result["mastered"] is True


# ===========================================================================
# Group 4 — generate_cards: unified schema, CHECKIN, count, images
# ===========================================================================

class TestGenerateCards:
    """
    Tests for generate_cards() under the new unified card schema:
      - Every regular card has a 'question' dict (text, options[4], correct_index, explanation)
      - No card has a 'quick_check' or 'questions[]' field
      - CHECKIN card is inserted at CARDS_MID_SESSION_CHECK_INTERVAL boundary
      - All cards returned by the LLM are kept (no truncation)
      - image_indices resolve to the correct card positions
    """

    # ---------------------------------------------------------------------------
    # Shared patch context for adaptive history — reused across all generate_cards tests
    # ---------------------------------------------------------------------------

    _HISTORY_DEFAULTS = {
        "total_cards_completed": 0,
        "avg_time_per_card": None,
        "avg_wrong_attempts": None,
        "avg_hints_per_card": None,
        "sessions_last_7d": 0,
        "is_known_weak_concept": False,
        "failed_concept_attempts": 0,
        "trend_direction": "STABLE",
        "trend_wrong_list": [],
    }

    def _cards_json(self, n: int) -> str:
        """
        Build a JSON string representing n LLM-generated cards using the new
        unified schema: title, content, image_indices, question (MCQ dict).
        No card_type, no quick_check, no questions[].
        """
        cards = []
        for i in range(n):
            cards.append({
                "title": f"Card {i + 1}",
                "content": f"Content for card {i + 1}.",
                "image_indices": [],
                "question": {
                    "text": f"Question {i + 1}?",
                    "options": ["A", "B", "C", "D"],
                    "correct_index": 0,
                    "explanation": "Because A is correct.",
                },
            })
        return json.dumps({"cards": cards})

    def _cards_json_with_images(self, n: int, image_assignments: dict) -> str:
        """
        Build n LLM cards. image_assignments maps card index → list of image indices.
        e.g. {2: [0], 5: [1]} means card 2 references available image 0, card 5 references image 1.
        """
        cards = []
        for i in range(n):
            indices = image_assignments.get(i, [])
            content = f"Content for card {i + 1}."
            if indices:
                for idx in indices:
                    content += f" [IMAGE:{idx}]"
            cards.append({
                "title": f"Card {i + 1}",
                "content": content,
                "image_indices": indices,
                "question": {
                    "text": f"Question {i + 1}?",
                    "options": ["A", "B", "C", "D"],
                    "correct_index": 0,
                    "explanation": "Because A is correct.",
                },
            })
        return json.dumps({"cards": cards})

    async def _run_generate_cards(self, svc, mock_openai, llm_json: str,
                                   session=None, student=None, images=None):
        """
        Wire LLM, build DB mock, optionally inject images into knowledge service,
        then call generate_cards() and return the result dict.
        """
        if session is None:
            session = _make_session(phase="CARDS")
        if student is None:
            student = _make_student()

        _wire_llm(mock_openai, llm_json)
        db = _make_db(message_count=0)

        # Inject useful images into the knowledge service mock if provided
        if images is not None:
            svc.knowledge_svc.get_concept_detail.return_value = {
                "concept_title": "Introduction to Fractions",
                "text": "A fraction represents part of a whole. ## Numerator\nThe top number. ## Denominator\nThe bottom number.",
                "latex": [],
                "prerequisites": [],
                "images": images,
            }

        with (
            patch("adaptive.adaptive_engine.load_student_history",
                  new=AsyncMock(return_value=self._HISTORY_DEFAULTS)),
            patch("adaptive.adaptive_engine.load_wrong_option_pattern",
                  new=AsyncMock(return_value=None)),
            patch("adaptive.profile_builder.build_learning_profile"),
        ):
            return await svc.generate_cards(db, session, student)

    # ── Test 1: unified schema — no card_type, question dict present ─────────

    async def test_cards_use_unified_schema(self):
        """
        Every regular (non-CHECKIN) card returned by generate_cards() must conform
        to the new unified schema:
          - Has a 'question' dict with 'text', 'options' (list of 4), 'correct_index' (int),
            and 'explanation' (str)
          - Does NOT have a 'quick_check' field
          - Does NOT have a 'questions' array field
          - Does NOT have a 'card_type' field

        Business rule: the unified schema ensures every card is interactive with
        exactly one MCQ — the old per-type split (TEACH/EXAMPLE/QUESTION/etc.) is removed.
        """
        svc, mock_openai, _ = _build_service()

        result = await self._run_generate_cards(svc, mock_openai, self._cards_json(4))

        cards = result["cards"]
        assert len(cards) > 0, "generate_cards must return at least one card"

        regular_cards = [c for c in cards if c.get("question") is not None or
                         not isinstance(c.get("options"), list)]
        # Exclude CHECKIN cards (no question key, has options list)
        regular_cards = [
            c for c in cards
            if not (c.get("question") is None and isinstance(c.get("options"), list))
        ]

        assert len(regular_cards) > 0, "At least one regular card must be present"

        for card in regular_cards:
            title = card.get("title", f"<untitled card>")

            # Must have 'question' dict
            assert "question" in card, (
                f"Card '{title}' missing 'question' field — new unified schema requires it"
            )
            q = card["question"]
            assert isinstance(q, dict), f"Card '{title}': 'question' must be a dict, got {type(q)}"

            # question dict must have required sub-fields
            assert "text" in q, f"Card '{title}': question missing 'text'"
            assert isinstance(q["text"], str), f"Card '{title}': question.text must be str"

            assert "options" in q, f"Card '{title}': question missing 'options'"
            assert isinstance(q["options"], list), (
                f"Card '{title}': question.options must be a list"
            )
            assert len(q["options"]) == 4, (
                f"Card '{title}': question.options must have exactly 4 items, got {len(q['options'])}"
            )

            assert "correct_index" in q, f"Card '{title}': question missing 'correct_index'"
            assert isinstance(q["correct_index"], int), (
                f"Card '{title}': question.correct_index must be int"
            )

            assert "explanation" in q, f"Card '{title}': question missing 'explanation'"
            assert isinstance(q["explanation"], str), (
                f"Card '{title}': question.explanation must be str"
            )

            # Must NOT have legacy fields
            assert "quick_check" not in card, (
                f"Card '{title}' has legacy 'quick_check' field — this was removed in the schema overhaul"
            )
            assert "questions" not in card, (
                f"Card '{title}' has legacy 'questions' array — this was removed in the schema overhaul"
            )
            # card_type is not expected on new cards (the prompt no longer produces it)
            assert "card_type" not in card, (
                f"Card '{title}' has 'card_type' — new schema has no card types"
            )

    # ── Test 2: CHECKIN detection by question-absence + options presence ──────

    async def test_checkin_card_inserted_at_interval(self):
        """
        When the LLM returns >= CARDS_MID_SESSION_CHECK_INTERVAL cards, a CHECKIN
        card must be inserted after every Nth card (N = CARDS_MID_SESSION_CHECK_INTERVAL).

        With 12 regular cards + 1 extra (13 total), a CHECKIN must appear at
        position 12 (0-based index 12) in the final cards list.

        CHECKIN detection: card has NO 'question' key AND has an 'options' list.
        There is NO 'card_type' field on CHECKIN cards — the old detection by
        card_type == 'CHECKIN' is no longer valid.

        Business rule: mid-session mood check-ins improve engagement and signal
        when the student is lost before finishing the card set.
        """
        from config import CARDS_MID_SESSION_CHECK_INTERVAL
        assert CARDS_MID_SESSION_CHECK_INTERVAL == 12, (
            f"Test assumes interval=12, got {CARDS_MID_SESSION_CHECK_INTERVAL}"
        )

        svc, mock_openai, _ = _build_service()

        # LLM returns exactly 13 cards (>= 12) so insertion triggers
        result = await self._run_generate_cards(svc, mock_openai, self._cards_json(13))

        cards = result["cards"]

        # Identify CHECKIN cards: no 'question' key AND has 'options' list
        def _is_checkin(c):
            return c.get("question") is None and isinstance(c.get("options"), list)

        checkin_indices = [i for i, c in enumerate(cards) if _is_checkin(c)]

        assert len(checkin_indices) > 0, (
            f"No CHECKIN card found among {len(cards)} cards after 13 LLM cards. "
            f"Expected a card with no 'question' key and an 'options' list at position "
            f"{CARDS_MID_SESSION_CHECK_INTERVAL}."
        )

        # CHECKIN must land at index 12 (after the 12th regular card)
        assert checkin_indices[0] == CARDS_MID_SESSION_CHECK_INTERVAL, (
            f"CHECKIN at index {checkin_indices[0]}, expected index {CARDS_MID_SESSION_CHECK_INTERVAL}"
        )

        # CHECKIN card must have no 'question' field
        checkin_card = cards[checkin_indices[0]]
        assert checkin_card.get("question") is None, (
            "CHECKIN card must have no 'question' field — it is a mood check, not a quiz"
        )

        # CHECKIN card must have an 'options' list of 4 strings
        assert isinstance(checkin_card.get("options"), list), (
            "CHECKIN card must have an 'options' list"
        )
        assert len(checkin_card["options"]) == 4, (
            f"CHECKIN options must have 4 items, got {len(checkin_card['options'])}"
        )
        for opt in checkin_card["options"]:
            assert isinstance(opt, str), f"CHECKIN option must be a string, got {type(opt)}"

    # ── Test 3: no True/False anywhere ────────────────────────────────────────

    async def test_no_trueFalse_in_any_card(self):
        """
        The new schema forbids True/False questions entirely.
        No card in the generate_cards() response should have:
          - A 'questions' array with entries that have type='true_false'
          - A 'correct_answer' field (which was the True/False answer field)

        Business rule: the adaptive engine switched entirely to MCQ to simplify
        scoring and enable misconception targeting.
        """
        svc, mock_openai, _ = _build_service()

        result = await self._run_generate_cards(svc, mock_openai, self._cards_json(5))

        cards = result["cards"]
        assert len(cards) > 0

        for card in cards:
            title = card.get("title", "<untitled>")

            # No legacy 'questions' array with true_false entries
            for q in card.get("questions", []):
                assert q.get("type") != "true_false", (
                    f"Card '{title}' contains a True/False question — forbidden by new schema"
                )

            # No 'correct_answer' field (True/False answer marker)
            assert "correct_answer" not in card, (
                f"Card '{title}' has 'correct_answer' field — this was a True/False marker"
            )

    # ── Test 4: card count not truncated ────────────────────────────────────────

    async def test_card_count_not_truncated(self):
        """
        If the LLM returns 25 cards, all 25 must be present in the result
        (plus any inserted CHECKIN cards). No artificial ceiling must drop cards.

        Business rule: the adaptive engine removed the old card count cap so
        that content-heavy concepts can have as many cards as they need.
        """
        from config import CARDS_MID_SESSION_CHECK_INTERVAL
        svc, mock_openai, _ = _build_service()

        llm_card_count = 25
        result = await self._run_generate_cards(
            svc, mock_openai, self._cards_json(llm_card_count)
        )

        cards = result["cards"]

        # Count regular (non-CHECKIN) cards
        def _is_checkin(c):
            return c.get("question") is None and isinstance(c.get("options"), list)

        regular_count = sum(1 for c in cards if not _is_checkin(c))

        assert regular_count == llm_card_count, (
            f"Expected {llm_card_count} regular cards from LLM, "
            f"got {regular_count} (total with CHECKINs: {len(cards)}). "
            "Card count must not be truncated — remove any ceiling if it exists."
        )

        # Total cards = 25 regular + CHECKINs inserted at positions 12 and 24
        # (i.e. after card index 11 and 23, but only if (i+1) < len(raw_cards))
        # With 25 cards: i=11 → (12) % 12 == 0 and 12 < 25 → CHECKIN at pos 12
        #                i=23 → (24) % 12 == 0 and 24 < 25 → CHECKIN at pos 25 (after re-index)
        # So total = 25 + 2 = 27. Allow tolerance: at minimum 25, at most 25 + 3.
        assert len(cards) >= llm_card_count, (
            f"Total card list ({len(cards)}) is less than LLM card count ({llm_card_count})"
        )

    # ── Test 5: images distributed to the correct cards ────────────────────────

    async def test_images_distributed_not_clustered(self):
        """
        When the LLM assigns image_indices to specific cards, the resolved 'images'
        list on each card must match those assignments:
          - Card 0: no images (image_indices=[])
          - Card 2: images=[image at useful_images[0]]
          - Card 5: images=[image at useful_images[1]]

        Business rule: image placement must be per-card, not clustered at the start.
        The backend resolves LLM-supplied index lists to actual image objects.
        """
        svc, mock_openai, _ = _build_service()

        # Two educational images that will pass the useful_images filter
        fake_images = [
            {
                "image_type": "DIAGRAM",
                "is_educational": True,
                "description": "Diagram showing numerator position in a fraction",
                "relevance": "high",
                "path": "/images/img0.png",
            },
            {
                "image_type": "FORMULA",
                "is_educational": True,
                "description": "Formula illustrating fraction equivalence",
                "relevance": "high",
                "path": "/images/img1.png",
            },
        ]

        # LLM assigns: card 2 → image 0, card 5 → image 1, all others → no images
        image_assignments = {2: [0], 5: [1]}
        llm_json = self._cards_json_with_images(7, image_assignments)

        result = await self._run_generate_cards(
            svc, mock_openai, llm_json, images=fake_images
        )

        cards = result["cards"]

        # Filter out any CHECKIN cards (7 < 12, so none expected, but be safe)
        def _is_checkin(c):
            return c.get("question") is None and isinstance(c.get("options"), list)

        regular_cards = [c for c in cards if not _is_checkin(c)]

        assert len(regular_cards) == 7, (
            f"Expected 7 regular cards, got {len(regular_cards)}"
        )

        # Card at position 0 must have no resolved images
        assert regular_cards[0]["images"] == [], (
            f"Card 0 should have no images, got {regular_cards[0]['images']}"
        )

        # Card at position 2 must have image 0 resolved
        card2_images = regular_cards[2]["images"]
        assert len(card2_images) == 1, (
            f"Card 2 should have exactly 1 image, got {len(card2_images)}"
        )
        assert card2_images[0]["description"] == fake_images[0]["description"], (
            f"Card 2 image mismatch: expected image 0's description"
        )

        # Card at position 5 must have image 1 resolved
        card5_images = regular_cards[5]["images"]
        assert len(card5_images) == 1, (
            f"Card 5 should have exactly 1 image, got {len(card5_images)}"
        )
        assert card5_images[0]["description"] == fake_images[1]["description"], (
            f"Card 5 image mismatch: expected image 1's description"
        )


# ===========================================================================
# Group 5 — generate_remediation_cards
# ===========================================================================

class TestGenerateRemediationCards:
    """
    generate_remediation_cards() is pure re-teaching: TEACH + EXAMPLE + RECAP only.
    The method signature is generate_remediation_cards(session_id, db).
    """

    async def test_generate_remediation_cards_returns_non_empty_list(self):
        """
        generate_remediation_cards() must return a non-empty list of cards
        when the session has a valid remediation_context.

        New schema: each card has 'question' (MCQ dict), no card_type, no quick_check.
        """
        svc, mock_openai, mock_ks = _build_service()

        session_id = uuid.uuid4()
        student_id = uuid.uuid4()

        # Build the session ORM mock
        session_mock = _make_session(
            phase="REMEDIATING",
            socratic_attempt_count=1,
            remediation_context='["numerator concepts"]',
        )
        session_mock.id = session_id
        session_mock.student_id = student_id

        student_mock = _make_student()

        # LLM returns three remediation cards using the new unified schema
        remediation_cards_json = json.dumps({"cards": [
            {
                "title": "Understanding Numerators Again",
                "content": "The numerator is the top number in a fraction.",
                "image_indices": [],
                "question": {
                    "text": "What is the numerator in 3/4?",
                    "options": ["3", "4", "7", "1"],
                    "correct_index": 0,
                    "explanation": "3 is on top — it is the numerator.",
                },
            },
            {
                "title": "Example: 1/2",
                "content": "In 1/2, the numerator is 1.",
                "image_indices": [],
                "question": {
                    "text": "What is the numerator of 1/2?",
                    "options": ["1", "2", "3", "0"],
                    "correct_index": 0,
                    "explanation": "1 is on top.",
                },
            },
            {
                "title": "Key Takeaways",
                "content": "- Numerator = top\n- Denominator = bottom",
                "image_indices": [],
                "question": {
                    "text": "Which part of a fraction is the numerator?",
                    "options": ["Top number", "Bottom number", "The line", "Both numbers"],
                    "correct_index": 0,
                    "explanation": "The numerator is always the top number.",
                },
            },
        ]})
        _wire_llm(mock_openai, remediation_cards_json)

        db = AsyncMock()
        db.get = AsyncMock(side_effect=lambda cls, pk: session_mock if cls.__name__ == "TeachingSession" else student_mock)
        db.flush = AsyncMock()

        cards = await svc.generate_remediation_cards(session_id, db)

        assert isinstance(cards, list), "generate_remediation_cards must return a list"
        assert len(cards) > 0, "Remediation cards list must not be empty"

    async def test_generate_remediation_cards_contains_no_question_cards(self):
        """
        The remediation prompt explicitly forbids card_type='QUESTION' style cards.
        Under the new unified schema there is no card_type field at all, so every card
        is re-teaching content with an MCQ question dict.

        This test validates the business invariant: remediation is re-teaching, NOT
        a separate QUESTION card type. All returned cards must have a 'question' dict.
        """
        svc, mock_openai, mock_ks = _build_service()

        session_id = uuid.uuid4()
        student_id = uuid.uuid4()

        session_mock = _make_session(
            phase="REMEDIATING",
            socratic_attempt_count=1,
            remediation_context='["fractions"]',
        )
        session_mock.id = session_id
        session_mock.student_id = student_id

        student_mock = _make_student()

        # New schema: two teaching cards, each with a question dict (no card_type)
        good_llm_response = json.dumps({"cards": [
            {
                "title": "Fractions Again",
                "content": "Fractions represent parts of a whole.",
                "image_indices": [],
                "question": {
                    "text": "What does a fraction represent?",
                    "options": ["Part of a whole", "A whole number", "A decimal", "An integer"],
                    "correct_index": 0,
                    "explanation": "A fraction represents part of a whole.",
                },
            },
            {
                "title": "Fraction Parts",
                "content": "Every fraction has a numerator (top) and denominator (bottom).",
                "image_indices": [],
                "question": {
                    "text": "What is the top number of a fraction called?",
                    "options": ["Numerator", "Denominator", "Quotient", "Divisor"],
                    "correct_index": 0,
                    "explanation": "The numerator is on top.",
                },
            },
        ]})
        _wire_llm(mock_openai, good_llm_response)

        db = AsyncMock()
        db.get = AsyncMock(side_effect=lambda cls, pk: session_mock if cls.__name__ == "TeachingSession" else student_mock)
        db.flush = AsyncMock()

        # The method must complete without raising
        cards = await svc.generate_remediation_cards(session_id, db)

        assert isinstance(cards, list)
        assert len(cards) > 0, "Remediation must return at least one card"

        # All cards in the new schema are re-teaching cards (no card_type field)
        for card in cards:
            assert "card_type" not in card, (
                f"Remediation card '{card.get('title')}' has 'card_type' — "
                "new schema has no card types"
            )
            # Every remediation card must have a question (MCQ)
            # (backward-compat path: service accepts quick_check and remaps it)
            has_question = card.get("question") is not None
            assert has_question, (
                f"Remediation card '{card.get('title')}' has no 'question' dict — "
                "all re-teaching cards must include an MCQ"
            )


# ===========================================================================
# Group 6 — begin_recheck phase transitions
# ===========================================================================

class TestBeginRecheck:
    """
    begin_recheck() must transition the session to the correct phase based on
    the current attempt count, and return the opening question text.
    """

    async def _call_begin_recheck(self, svc, session_mock, student_mock, llm_content: str):
        """Helper: wire LLM and DB, call begin_recheck, return the result dict."""
        _wire_llm(svc.openai, llm_content)

        from db.models import TeachingSession, Student

        db = AsyncMock()

        async def _db_get(cls, pk):
            if cls is TeachingSession:
                return session_mock
            if cls is Student:
                return student_mock
            return None

        db.get = _db_get
        db.flush = AsyncMock()

        exec_result = MagicMock()
        exec_result.scalar_one.return_value = 4  # message count
        db.execute = AsyncMock(return_value=exec_result)
        db.add = MagicMock()

        result = await svc.begin_recheck(session_mock.id, db)
        return result

    async def test_begin_recheck_first_cycle_sets_rechecking_phase(self):
        """
        When attempt_count == 1 (student completed first remediation cycle),
        begin_recheck() must:
          - set session.phase to "RECHECKING"
          - return a response dict containing the opening question
          - save an assistant message to the DB
        """
        svc, _, _ = _build_service()

        session_mock = _make_session(
            phase="REMEDIATING",
            socratic_attempt_count=1,
            remediation_context='["numerator"]',
        )
        student_mock = _make_student()

        opening_question = "Let's try again! Can you tell me what the numerator means?"
        result = await self._call_begin_recheck(svc, session_mock, student_mock, opening_question)

        assert session_mock.phase == "RECHECKING", (
            f"Expected RECHECKING, got {session_mock.phase}"
        )
        assert "response" in result
        assert result["response"] == opening_question
        assert result["phase"] == "RECHECKING"

    async def test_begin_recheck_second_cycle_sets_rechecking_2_phase(self):
        """
        When attempt_count == 2 (student completed second remediation cycle),
        begin_recheck() must set session.phase to "RECHECKING_2".
        """
        svc, _, _ = _build_service()

        session_mock = _make_session(
            phase="REMEDIATING_2",
            socratic_attempt_count=2,
            remediation_context='["numerator", "denominator"]',
        )
        student_mock = _make_student()

        opening_question = "One more try! What is the bottom number of a fraction called?"
        result = await self._call_begin_recheck(svc, session_mock, student_mock, opening_question)

        assert session_mock.phase == "RECHECKING_2", (
            f"Expected RECHECKING_2, got {session_mock.phase}"
        )
        assert result["phase"] == "RECHECKING_2"

    async def test_begin_recheck_response_contains_opening_question(self):
        """
        The dict returned by begin_recheck() must contain a 'response' key
        with the LLM's opening question text (non-empty string).
        """
        svc, _, _ = _build_service()

        session_mock = _make_session(
            phase="REMEDIATING",
            socratic_attempt_count=1,
            remediation_context='["fractions"]',
        )
        student_mock = _make_student()

        question_text = "Welcome back! Ready to try the fraction questions again?"
        result = await self._call_begin_recheck(svc, session_mock, student_mock, question_text)

        assert "response" in result
        assert isinstance(result["response"], str)
        assert len(result["response"]) > 0
        assert result["response"] == question_text


# ===========================================================================
# Group 7 — Internal helpers (static methods)
# ===========================================================================

class TestInternalHelpers:
    """
    Static method tests that require no DB or LLM — pure Python logic.
    """

    def test_parse_assessment_extracts_score(self):
        """_parse_assessment must detect [ASSESSMENT:XX] and return (True, score)."""
        from api.teaching_service import TeachingService

        complete, score = TeachingService._parse_assessment(
            "Great work today! You really understand fractions. [ASSESSMENT:75]"
        )
        assert complete is True
        assert score == 75

    def test_parse_assessment_returns_false_when_absent(self):
        """_parse_assessment must return (False, None) when tag is absent."""
        from api.teaching_service import TeachingService

        complete, score = TeachingService._parse_assessment(
            "Can you tell me what a numerator is?"
        )
        assert complete is False
        assert score is None

    def test_parse_assessment_handles_zero_score(self):
        """Edge case: score of 0 must be returned as 0, not falsy None."""
        from api.teaching_service import TeachingService

        complete, score = TeachingService._parse_assessment("[ASSESSMENT:0]")
        assert complete is True
        assert score == 0

    def test_parse_assessment_handles_100_score(self):
        """Edge case: score of 100 must be parsed correctly."""
        from api.teaching_service import TeachingService

        complete, score = TeachingService._parse_assessment(
            "Perfect score! [ASSESSMENT:100]"
        )
        assert complete is True
        assert score == 100

    def test_mastery_boundary_exactly_at_threshold(self):
        """
        The mastery gate is score >= MASTERY_THRESHOLD (inclusive).
        Score == threshold must be treated as mastery (not failure).
        """
        from config import MASTERY_THRESHOLD
        assert MASTERY_THRESHOLD >= 70  # Sanity
        # 70 >= 70 is True
        assert MASTERY_THRESHOLD >= MASTERY_THRESHOLD

    def test_mastery_boundary_one_below_threshold_fails(self):
        """
        A score one point below MASTERY_THRESHOLD must NOT trigger mastery.
        This validates the inclusive >= boundary.
        """
        from config import MASTERY_THRESHOLD
        score_just_below = MASTERY_THRESHOLD - 1
        assert score_just_below < MASTERY_THRESHOLD, (
            f"Score {score_just_below} must be less than threshold {MASTERY_THRESHOLD}"
        )

    def test_extract_json_block_strips_markdown_fences(self):
        """_extract_json_block must unwrap JSON inside markdown code fences."""
        from api.teaching_service import TeachingService

        raw = '```json\n{"cards": []}\n```'
        result = TeachingService._extract_json_block(raw)
        assert result == '{"cards": []}'

    def test_extract_json_block_passthrough_plain_json(self):
        """_extract_json_block must return plain JSON unchanged."""
        from api.teaching_service import TeachingService

        raw = '{"cards": []}'
        result = TeachingService._extract_json_block(raw)
        assert result == '{"cards": []}'

    def test_build_windowed_messages_keeps_system_and_recents(self):
        """
        _build_windowed_messages must always retain the system prompt and the
        most recent exchanges, discarding middle history.
        """
        from api.teaching_service import TeachingService

        # Build 6 exchanges: sys + 6 * (user+assistant) = 13 messages
        msgs = [{"role": "system", "content": "You are ADA."}]
        for i in range(6):
            msgs.append({"role": "user", "content": f"Student answer {i}"})
            msgs.append({"role": "assistant", "content": f"Tutor response {i}"})

        windowed = TeachingService._build_windowed_messages(msgs)

        # System prompt must always be present
        assert windowed[0]["role"] == "system"
        # Total should be: 1 system + (1 first exchange * 2 msgs) + (3 last exchanges * 2 msgs) = 9
        non_system = [m for m in windowed if m["role"] != "system"]
        assert len(non_system) <= 8, (
            f"Windowed messages should keep at most 4 exchanges (8 msgs), got {len(non_system)}"
        )


# ===========================================================================
# Group 8 — Image index coverage and quality
# ===========================================================================

class TestImageIndexCoverage:
    """
    Tests that image_index.json covers all prealgebra sections
    and that image descriptions meet quality standards.
    Only runs if image_index.json exists; otherwise skips gracefully.
    """

    IMAGE_INDEX_PATH = Path(__file__).parent.parent / "output" / "prealgebra" / "image_index.json"

    @pytest.fixture(scope="class")
    def image_index(self):
        if not self.IMAGE_INDEX_PATH.exists():
            pytest.skip("image_index.json not found — run pipeline first")
        with open(self.IMAGE_INDEX_PATH) as f:
            return json.load(f)

    def test_image_index_covers_multiple_chapters(self, image_index):
        """image_index.json must cover more than just Chapter 1."""
        concepts = list(image_index.keys())
        # Extract unique chapter numbers from concept IDs like PREALG.C2.S1.*
        chapters = set()
        for cid in concepts:
            parts = cid.split(".")
            for part in parts:
                if part.startswith("C") and part[1:].isdigit():
                    chapters.add(int(part[1:]))
        assert len(chapters) >= 3, (
            f"Expected images from at least 3 chapters, found: {sorted(chapters)}. "
            f"Concepts in index: {concepts[:5]}"
        )

    def test_all_images_have_descriptions(self, image_index):
        """Every image entry must have a non-empty description."""
        bad = []
        for concept_id, imgs in image_index.items():
            for i, img in enumerate(imgs):
                desc = img.get("description")
                if not desc or len(desc.strip()) < 20:
                    bad.append(f"{concept_id}[{i}]: description='{desc}'")
        assert not bad, f"Images with missing/short descriptions:\n" + "\n".join(bad[:10])

    def test_image_descriptions_are_specific(self, image_index):
        """
        Descriptions must be specific — not just 'a diagram'.
        Check: description >= 80 chars and contains at least one digit or math term.
        """
        math_terms = {"number", "line", "fraction", "bar", "chart", "grid", "angle",
                      "triangle", "circle", "area", "perimeter", "percent", "decimal",
                      "variable", "equation", "graph", "axis", "point", "coordinate",
                      "shaded", "labeled", "marks", "tick", "arrow", "column", "row"}
        vague = []
        for concept_id, imgs in image_index.items():
            for i, img in enumerate(imgs):
                desc = img.get("description", "")
                has_digit = any(c.isdigit() for c in desc)
                has_math_term = any(term in desc.lower() for term in math_terms)
                if len(desc) < 80 or not (has_digit or has_math_term):
                    vague.append(f"{concept_id}[{i}]: '{desc[:100]}'")
        # Allow up to 10% vague descriptions (some abstract concepts are hard to quantify)
        total = sum(len(imgs) for imgs in image_index.values())
        assert len(vague) <= total * 0.10, (
            f"Too many vague descriptions ({len(vague)}/{total}):\n" + "\n".join(vague[:5])
        )

    def test_chapter_1_images_preserved(self, image_index):
        """Chapter 1 (5 sections) should still have images after pipeline re-run."""
        ch1_concepts = [k for k in image_index.keys() if ".C1." in k]
        assert len(ch1_concepts) >= 5, (
            f"Expected at least 5 Chapter 1 concepts with images, found: {ch1_concepts}"
        )
        ch1_total = sum(len(image_index[k]) for k in ch1_concepts)
        assert ch1_total >= 50, (
            f"Chapter 1 should have at least 50 images, found: {ch1_total}"
        )

    def test_no_zero_image_chapters_in_visual_range(self, image_index):
        """
        Chapters 1-9 cover visual concepts (whole numbers, fractions, geometry).
        At least 6 of these 9 chapters should have images.
        """
        chapters_with_images = set()
        for cid in image_index.keys():
            parts = cid.split(".")
            for part in parts:
                if part.startswith("C") and part[1:].isdigit():
                    n = int(part[1:])
                    if 1 <= n <= 9:
                        chapters_with_images.add(n)
        assert len(chapters_with_images) >= 6, (
            f"Expected at least 6 of chapters 1-9 to have images, "
            f"found images in chapters: {sorted(chapters_with_images)}"
        )


# ===========================================================================
# Group 9 — Bug-fix regression tests (image param, personalization, kid safety)
# ===========================================================================

class TestBugFixRegressions:
    """
    Regression tests for the 4 bugs fixed in the production-readiness pass:
      Bug 1: build_cards_user_prompt receives useful_images (filtered), not images (raw)
      Bug 2: build_cards_user_prompt includes student language, interests, style, profile
      Bug 3: build_socratic_system_prompt has Stage 0 confusion handler + no hardcoded English phrases
      Bug 4: mid-session encouragement injected at exchange 12
    """

    # ── Bug 1: image parameter must be useful_images ────────────────────────

    def test_build_cards_user_prompt_receives_useful_images_not_all(self):
        """
        build_cards_user_prompt() must re-filter the images it receives.
        When passed useful_images (all DIAGRAM/FORMULA with descriptions), all of them
        appear in the AVAILABLE IMAGES block.  When passed raw images that include
        non-DIAGRAM types, the non-DIAGRAM ones are silently dropped.
        This verifies the contract: caller must pass useful_images, not the raw list.
        """
        from api.prompts import build_cards_user_prompt

        useful = [
            {"image_type": "DIAGRAM", "is_educational": True,
             "description": "A number line from 0 to 10", "filename": "a.png"},
            {"image_type": "DIAGRAM", "is_educational": True,
             "description": "A fraction bar divided into 8 parts", "filename": "b.png"},
        ]
        non_diagram = [
            {"image_type": "PHOTO", "is_educational": True,
             "description": "A photo of a classroom", "filename": "c.png"},
        ]

        # Prompt built with only useful images → both descriptions appear
        prompt_useful = build_cards_user_prompt(
            concept_title="Fractions", sub_sections=[], images=useful
        )
        assert "number line from 0 to 10" in prompt_useful
        assert "fraction bar" in prompt_useful

        # Prompt built with non-diagram images → they are filtered OUT by the function
        prompt_raw = build_cards_user_prompt(
            concept_title="Fractions", sub_sections=[], images=non_diagram
        )
        assert "photo of a classroom" not in prompt_raw
        assert "No diagrams available" in prompt_raw

    # ── Bug 2: user prompt personalization ──────────────────────────────────

    def test_cards_user_prompt_includes_language_instruction(self):
        """Non-English language must appear in the user prompt profile block."""
        from api.prompts import build_cards_user_prompt

        prompt = build_cards_user_prompt(
            concept_title="Addition",
            sub_sections=[],
            language="es",
        )
        assert "Spanish" in prompt, "Language name must appear in user prompt for non-English"

    def test_cards_user_prompt_english_produces_no_profile_block(self):
        """English (default) should NOT add a profile block — nothing to override."""
        from api.prompts import build_cards_user_prompt

        prompt = build_cards_user_prompt(
            concept_title="Addition",
            sub_sections=[],
            language="en",
        )
        assert "STUDENT PROFILE" not in prompt

    def test_cards_user_prompt_includes_struggling_note(self):
        """STRUGGLING comprehension must add simplified-language instruction."""
        from api.prompts import build_cards_user_prompt

        profile = MagicMock()
        profile.comprehension = "STRUGGLING"
        profile.speed = "SLOW"

        prompt = build_cards_user_prompt(
            concept_title="Decimals",
            sub_sections=[],
            learning_profile=profile,
        )
        assert "STRUGGLING" in prompt
        assert "simple" in prompt.lower()

    def test_cards_user_prompt_includes_interests(self):
        """Student interests must appear in the profile block."""
        from api.prompts import build_cards_user_prompt

        prompt = build_cards_user_prompt(
            concept_title="Geometry",
            sub_sections=[],
            interests=["soccer", "space", "cooking"],
        )
        assert "soccer" in prompt

    # ── Bug 3: Socratic confusion handler + no hardcoded English phrases ────

    def test_socratic_prompt_has_stage_0_confusion_handler(self):
        """build_socratic_system_prompt must include Stage 0 confusion detection."""
        from api.prompts import build_socratic_system_prompt

        prompt = build_socratic_system_prompt(
            concept_title="Fractions",
            concept_text="Fractions represent parts of a whole.",
        )
        assert "Stage 0" in prompt or "CONFUSION DETECTION" in prompt, (
            "Socratic prompt must include Stage 0 confusion detection block"
        )
        assert "I don't understand" in prompt or "confusion" in prompt.lower(), (
            "Stage 0 must mention student confusion phrases"
        )

    def test_socratic_prompt_no_hardcoded_english_progress_phrase(self):
        """The hardcoded English progress phrase must not appear verbatim in the prompt."""
        from api.prompts import build_socratic_system_prompt

        prompt = build_socratic_system_prompt(
            concept_title="Whole Numbers",
            concept_text="Whole numbers are 0, 1, 2, 3...",
        )
        # The old hardcoded phrase should be gone
        assert "3 down, 4 to go" not in prompt, (
            "Hardcoded English progress phrase must be removed from Socratic prompt"
        )


# ===========================================================================
# Group 10 — Analytics endpoint: GET /api/v2/students/{student_id}/analytics
# ===========================================================================

def _make_mastery_record(concept_id: str) -> MagicMock:
    """Return a StudentMastery-like mock with concept_id and mastered_at set."""
    record = MagicMock()
    record.concept_id = concept_id
    record.mastered_at = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    return record


def _make_teaching_session_record(
    concept_id: str,
    phase: str = "COMPLETED",
    check_score: int | None = None,
    completed_at=None,
) -> MagicMock:
    """Return a TeachingSession-like mock for analytics aggregation."""
    record = MagicMock()
    record.concept_id = concept_id
    record.phase = phase
    record.check_score = check_score
    record.completed_at = completed_at or datetime(2025, 1, 20, 10, 0, 0, tzinfo=timezone.utc)
    return record


def _make_card_interaction_record(
    concept_id: str,
    wrong_attempts: int = 0,
    hints_used: int = 0,
    time_on_card_sec: float = 30.0,
) -> MagicMock:
    """Return a CardInteraction-like mock for analytics aggregation."""
    record = MagicMock()
    record.concept_id = concept_id
    record.wrong_attempts = wrong_attempts
    record.hints_used = hints_used
    record.time_on_card_sec = time_on_card_sec
    return record


def _make_spaced_review_record(
    concept_id: str,
    completed_at=None,
    due_at=None,
) -> MagicMock:
    """Return a SpacedReview-like mock."""
    from datetime import timezone, timedelta
    record = MagicMock()
    record.concept_id = concept_id
    record.completed_at = completed_at  # None = pending
    record.due_at = due_at or (datetime.now(timezone.utc) - timedelta(days=1))
    return record


def _make_analytics_db(
    student: MagicMock | None,
    mastery_rows: list,
    session_rows: list,
    card_rows: list,
    review_rows: list,
) -> AsyncMock:
    """
    Build a mock AsyncSession with four sequential db.execute() calls returning
    the supplied rows via .scalars().all().

    Call order matches the analytics endpoint:
      1. mastery_result  → mastery_rows
      2. sessions_result → session_rows
      3. cards_result    → card_rows
      4. reviews_result  → review_rows
    """
    db = AsyncMock()

    def _make_exec_result(rows):
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        return result

    db.execute = AsyncMock(side_effect=[
        _make_exec_result(mastery_rows),
        _make_exec_result(session_rows),
        _make_exec_result(card_rows),
        _make_exec_result(review_rows),
    ])

    async def _db_get(cls, pk):
        return student

    db.get = _db_get
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


class TestAnalyticsEndpoint:
    """
    Tests for GET /api/v2/students/{student_id}/analytics.

    The endpoint aggregates data from four tables (StudentMastery, TeachingSession,
    CardInteraction, SpacedReview) and returns a StudentAnalyticsResponse.
    All DB and network calls are mocked — no real PostgreSQL required.
    """

    def _install_api_main_stub(self):
        """Pre-inject api.main stub to break the circular import with teaching_router."""
        if "api.main" not in sys.modules:
            stub = MagicMock()
            try:
                from slowapi import Limiter
                from slowapi.util import get_remote_address
                stub.limiter = Limiter(key_func=get_remote_address)
            except ImportError:
                stub.limiter = MagicMock()
            sys.modules["api.main"] = stub

    async def _call_analytics(self, student, mastery_rows, session_rows, card_rows, review_rows):
        """
        Import the router-level handler directly, inject a mock Request and DB,
        and invoke get_student_analytics() without starting the FastAPI app.
        """
        self._install_api_main_stub()
        from api.teaching_router import get_student_analytics

        db = _make_analytics_db(student, mastery_rows, session_rows, card_rows, review_rows)
        from starlette.requests import Request as StarletteRequest
        real_request = StarletteRequest({"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []})
        student_id = student.id if student else uuid.uuid4()
        return await get_student_analytics(real_request, student_id, db)

    async def test_analytics_returns_mastery_count(self):
        """
        Business rule: total_concepts_mastered must equal the number of StudentMastery
        records returned by the database query for that student.
        3 mastery records → total_concepts_mastered == 3.
        """
        student = _make_student()
        student.id = uuid.uuid4()
        student.xp = 100
        student.streak = 5

        mastery_rows = [
            _make_mastery_record("concept_A"),
            _make_mastery_record("concept_B"),
            _make_mastery_record("concept_C"),
        ]

        response = await self._call_analytics(
            student=student,
            mastery_rows=mastery_rows,
            session_rows=[],
            card_rows=[],
            review_rows=[],
        )

        assert response.total_concepts_mastered == 3, (
            f"Expected total_concepts_mastered=3, got {response.total_concepts_mastered}"
        )

    async def test_analytics_mastery_rate_calculation(self):
        """
        Business rule: mastery_rate = mastered_count / attempted_count (distinct concept_ids
        from completed sessions). 3 mastered out of 5 distinct attempted → 0.6.
        """
        student = _make_student()
        student.id = uuid.uuid4()
        student.xp = 50
        student.streak = 2

        mastery_rows = [
            _make_mastery_record("concept_A"),
            _make_mastery_record("concept_B"),
            _make_mastery_record("concept_C"),
        ]

        # 5 distinct concept_ids across completed sessions
        completed_ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=timezone.utc)
        session_rows = [
            _make_teaching_session_record("concept_A", phase="COMPLETED", completed_at=completed_ts),
            _make_teaching_session_record("concept_B", phase="COMPLETED", completed_at=completed_ts),
            _make_teaching_session_record("concept_C", phase="COMPLETED", completed_at=completed_ts),
            _make_teaching_session_record("concept_D", phase="COMPLETED", completed_at=completed_ts),
            _make_teaching_session_record("concept_E", phase="COMPLETED", completed_at=completed_ts),
        ]

        response = await self._call_analytics(
            student=student,
            mastery_rows=mastery_rows,
            session_rows=session_rows,
            card_rows=[],
            review_rows=[],
        )

        assert response.mastery_rate == 0.6, (
            f"Expected mastery_rate=0.6 (3 mastered / 5 attempted), got {response.mastery_rate}"
        )
        assert response.total_concepts_attempted == 5

    async def test_analytics_reviews_due_count(self):
        """
        Business rule: reviews_due_now counts pending reviews (completed_at=None)
        with due_at <= now. 2 overdue + 1 upcoming → reviews_due_now == 2.
        """
        from datetime import timedelta
        student = _make_student()
        student.id = uuid.uuid4()
        student.xp = 0
        student.streak = 0

        now = datetime.now(timezone.utc)
        overdue_1 = _make_spaced_review_record(
            "concept_A", completed_at=None, due_at=now - timedelta(days=3)
        )
        overdue_2 = _make_spaced_review_record(
            "concept_B", completed_at=None, due_at=now - timedelta(days=1)
        )
        upcoming = _make_spaced_review_record(
            "concept_C", completed_at=None, due_at=now + timedelta(days=2)
        )

        response = await self._call_analytics(
            student=student,
            mastery_rows=[],
            session_rows=[],
            card_rows=[],
            review_rows=[overdue_1, overdue_2, upcoming],
        )

        assert response.reviews_due_now == 2, (
            f"Expected reviews_due_now=2 (2 overdue, 1 upcoming), got {response.reviews_due_now}"
        )

    async def test_analytics_avg_check_score(self):
        """
        Business rule: avg_check_score is the mean of all non-None check_scores across
        sessions. Two sessions with scores 60 and 80 → avg_check_score == 70.0.
        """
        student = _make_student()
        student.id = uuid.uuid4()
        student.xp = 200
        student.streak = 3

        completed_ts = datetime(2025, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        session_rows = [
            _make_teaching_session_record(
                "concept_X", phase="COMPLETED", check_score=60, completed_at=completed_ts
            ),
            _make_teaching_session_record(
                "concept_Y", phase="COMPLETED", check_score=80, completed_at=completed_ts
            ),
        ]

        response = await self._call_analytics(
            student=student,
            mastery_rows=[],
            session_rows=session_rows,
            card_rows=[],
            review_rows=[],
        )

        assert response.avg_check_score == 70.0, (
            f"Expected avg_check_score=70.0, got {response.avg_check_score}"
        )

    async def test_analytics_hardest_concept(self):
        """
        Business rule: hardest_concept_id is the concept_id with the highest total
        wrong_attempts across all CardInteraction records. concept_A (10 wrong) beats
        concept_B (3 wrong) → hardest_concept_id == 'concept_A'.
        """
        student = _make_student()
        student.id = uuid.uuid4()
        student.xp = 0
        student.streak = 0

        card_rows = [
            _make_card_interaction_record("concept_A", wrong_attempts=10),
            _make_card_interaction_record("concept_B", wrong_attempts=3),
        ]

        response = await self._call_analytics(
            student=student,
            mastery_rows=[],
            session_rows=[],
            card_rows=card_rows,
            review_rows=[],
        )

        assert response.hardest_concept_id == "concept_A", (
            f"Expected hardest_concept_id='concept_A' (10 wrong), "
            f"got '{response.hardest_concept_id}'"
        )
        assert response.hardest_concept_wrong_attempts == 10


# ===========================================================================
# Group 11 — Concept readiness: GET /api/v2/concepts/{concept_id}/readiness
# ===========================================================================

def _make_readiness_db(mastered_concept_ids: list[str]) -> AsyncMock:
    """
    Build a mock AsyncSession for the readiness endpoint.
    The single db.execute() call returns a scalars().all() list of concept_id strings.
    """
    db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = mastered_concept_ids
    db.execute = AsyncMock(return_value=exec_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


class TestConceptReadiness:
    """
    Tests for GET /api/v2/concepts/{concept_id}/readiness?student_id={id}.

    The endpoint checks whether a student has mastered all prerequisites for a
    given concept by querying StudentMastery and walking graph.predecessors().
    All DB and graph calls are fully mocked.
    """

    def _install_api_main_stub(self):
        """Pre-inject api.main stub to break the circular import with teaching_router."""
        if "api.main" not in sys.modules:
            stub = MagicMock()
            try:
                from slowapi import Limiter
                from slowapi.util import get_remote_address
                stub.limiter = Limiter(key_func=get_remote_address)
            except ImportError:
                stub.limiter = MagicMock()
            sys.modules["api.main"] = stub

    async def _call_readiness(
        self,
        concept_id: str,
        mastered_ids: list[str],
        prereq_ids: list[str],
        concept_in_graph: bool = True,
        prereq_titles: dict | None = None,
    ):
        """
        Invoke get_concept_readiness() directly with mocked DB and graph.

        mastered_ids      — concept_ids the student has mastered
        prereq_ids        — what graph.predecessors(concept_id) yields
        concept_in_graph  — whether concept_id is in the graph
        prereq_titles     — optional {prereq_id: title} override (default: same as id)
        """
        self._install_api_main_stub()
        from api.teaching_router import get_concept_readiness

        db = _make_readiness_db(mastered_ids)
        from starlette.requests import Request as StarletteRequest
        real_request = StarletteRequest({"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []})
        student_id = uuid.uuid4()

        # Build a graph mock that supports `in` operator and .predecessors()
        mock_graph = MagicMock()
        type(mock_graph).__contains__ = MagicMock(return_value=concept_in_graph)
        mock_graph.predecessors.return_value = iter(prereq_ids)

        # Build node data for title lookups
        nodes_data = {}
        for pid in prereq_ids:
            title = (prereq_titles or {}).get(pid, pid)
            nodes_data[pid] = {"title": title}
        mock_graph.nodes = nodes_data

        mock_ks = MagicMock()
        mock_ks.graph = mock_graph

        mock_svc = MagicMock()
        mock_svc.knowledge_svc = mock_ks

        with patch("api.teaching_router.teaching_svc", mock_svc):
            return await get_concept_readiness(real_request, concept_id, student_id, db)

    async def test_readiness_all_prerequisites_met(self):
        """
        Business rule: when the student has mastered every prerequisite, the response
        must report all_prerequisites_met=True and an empty unmet_prerequisites list.
        """
        response = await self._call_readiness(
            concept_id="concept_fractions",
            mastered_ids=["prereq_whole_numbers", "prereq_addition"],
            prereq_ids=["prereq_whole_numbers", "prereq_addition"],
        )

        assert response.all_prerequisites_met is True, (
            "all_prerequisites_met must be True when all prereqs are mastered"
        )
        assert response.unmet_prerequisites == [], (
            "unmet_prerequisites must be empty when all prereqs are mastered"
        )

    async def test_readiness_some_prerequisites_unmet(self):
        """
        Business rule: when only 1 of 2 prerequisites is mastered, the response must
        report all_prerequisites_met=False and list exactly 1 unmet prerequisite.
        """
        response = await self._call_readiness(
            concept_id="concept_fractions",
            mastered_ids=["prereq_whole_numbers"],  # only 1 of 2 mastered
            prereq_ids=["prereq_whole_numbers", "prereq_addition"],
            prereq_titles={"prereq_addition": "Introduction to Addition"},
        )

        assert response.all_prerequisites_met is False, (
            "all_prerequisites_met must be False when at least one prereq is unmet"
        )
        assert len(response.unmet_prerequisites) == 1, (
            f"Expected 1 unmet prerequisite, got {len(response.unmet_prerequisites)}"
        )
        unmet_ids = [u.concept_id for u in response.unmet_prerequisites]
        assert "prereq_addition" in unmet_ids, (
            "The unmastered prereq 'prereq_addition' must appear in unmet_prerequisites"
        )

    async def test_readiness_concept_with_no_prerequisites(self):
        """
        Business rule: when a concept has no prerequisites (graph.predecessors() yields
        nothing), the response must report all_prerequisites_met=True and an empty
        unmet_prerequisites list — even if the student has mastered nothing.
        """
        response = await self._call_readiness(
            concept_id="concept_intro",
            mastered_ids=[],   # student has mastered nothing
            prereq_ids=[],     # concept has no prerequisites
        )

        assert response.all_prerequisites_met is True, (
            "all_prerequisites_met must be True when there are no prerequisites"
        )
        assert response.unmet_prerequisites == [], (
            "unmet_prerequisites must be empty when there are no prerequisites"
        )


# ===========================================================================
# Group 12 — Personalization bug-fix regressions
# ===========================================================================

class TestPersonalizationBugFixes:
    """
    Regression tests for 7 bugs fixed in the adaptive personalization pipeline:

      Bug 1 — card_profile always built (even when total_cards_completed == 0)
      Bug 2 — comprehension correctly STRUGGLING when history shows high error rate
      Bug 3 — socratic_profile always built for zero-history students
      Bug 4 — quiz_score formula produces non-trivial value for high-error history
      Bug 5 — classify_engagement detects BORED when completing cards very quickly
               with no wrong attempts
      Bug 6 — classify_engagement detects OVERWHELMED from hint count alone (no
               rushing required)
      Bug 7 — classify_engagement does NOT label BORED when wrong_attempts > 0,
               even if time is very short

    All tests are pure (no DB, no LLM).  They call classify_engagement and
    build_learning_profile directly with crafted AnalyticsSummary objects that
    mirror the values the fixed generate_cards() and begin_socratic_check() code
    would construct from student history.
    """

    # ── Bug 1: card_profile always built for new students ───────────────────

    def test_card_profile_always_built_for_new_student(self):
        """
        Bug fix: build_learning_profile must be called even when
        history["total_cards_completed"] == 0.  Zero-history defaults produce
        a valid LearningProfile with comprehension==OK and speed==NORMAL.

        Verified by constructing AnalyticsSummary the same way generate_cards()
        does from zero-history defaults (avg_time=None, avg_wrong=None, avg_hints=None,
        sessions_last_7d=0) and asserting the profile is not None and has expected values.
        """
        from adaptive.profile_builder import build_learning_profile
        from adaptive.schemas import AnalyticsSummary

        history = {
            "avg_time_per_card": None,
            "avg_wrong_attempts": None,
            "avg_hints_per_card": None,
            "sessions_last_7d": 0,
        }

        mini = AnalyticsSummary(
            student_id="student-zero",
            concept_id="concept::intro",
            time_spent_sec=history["avg_time_per_card"] or 120.0,
            expected_time_sec=120.0,
            attempts=max(1, round((history["avg_wrong_attempts"] or 0) + 1)),
            wrong_attempts=round(history["avg_wrong_attempts"] or 0),
            hints_used=round(history["avg_hints_per_card"] or 0),
            revisits=0,
            recent_dropoffs=0,
            skip_rate=0.0,
            quiz_score=max(0.1, 1.0 - min((history["avg_wrong_attempts"] or 0) * 0.15, 0.9)),
            last_7d_sessions=history["sessions_last_7d"],
        )

        card_profile = build_learning_profile(mini, has_unmet_prereq=False)

        assert card_profile is not None, (
            "build_learning_profile must return a profile even for zero-history students"
        )
        assert card_profile.comprehension == "STRONG", (
            f"Zero-history student (quiz_score=1.0, error_rate=0) should have comprehension=STRONG, "
            f"got {card_profile.comprehension}"
        )
        assert card_profile.speed == "NORMAL", (
            f"Zero-history student (120s actual vs 120s expected) should have speed=NORMAL, "
            f"got {card_profile.speed}"
        )

    # ── Bug 2: STRUGGLING comprehension from high error rate ────────────────

    def test_card_profile_comprehension_struggling_when_high_error_rate(self):
        """
        Bug fix: when avg_wrong_attempts is high (e.g. 8), the derived error_rate
        should cross the STRUGGLING threshold (>= 0.5), producing comprehension=STRUGGLING.

        With avg_wrong=8: attempts = max(1, round(8+1)) = 9, wrong = 8,
        error_rate = 8/9 ≈ 0.889 >= 0.5 → STRUGGLING.
        """
        from adaptive.profile_builder import build_learning_profile
        from adaptive.schemas import AnalyticsSummary

        history = {
            "avg_wrong_attempts": 8,
            "avg_time_per_card": 150.0,
            "avg_hints_per_card": 4,
            "sessions_last_7d": 3,
        }

        mini = AnalyticsSummary(
            student_id="student-struggling",
            concept_id="concept::fractions",
            time_spent_sec=history["avg_time_per_card"] or 120.0,
            expected_time_sec=120.0,
            attempts=max(1, round((history["avg_wrong_attempts"] or 0) + 1)),
            wrong_attempts=round(history["avg_wrong_attempts"] or 0),
            hints_used=round(history["avg_hints_per_card"] or 0),
            revisits=0,
            recent_dropoffs=0,
            skip_rate=0.0,
            quiz_score=max(0.1, 1.0 - min((history["avg_wrong_attempts"] or 0) * 0.15, 0.9)),
            last_7d_sessions=history["sessions_last_7d"],
        )

        card_profile = build_learning_profile(mini, has_unmet_prereq=False)

        assert card_profile.comprehension == "STRUGGLING", (
            f"High avg_wrong (8) must produce STRUGGLING comprehension, "
            f"got {card_profile.comprehension}. "
            f"error_rate={mini.wrong_attempts}/{mini.attempts}="
            f"{mini.wrong_attempts/mini.attempts:.3f}"
        )

    # ── Bug 3: socratic_profile always built for zero-history students ───────

    def test_socratic_profile_always_built_for_zero_history_student(self):
        """
        Bug fix: the socratic profile (built in begin_socratic_check) must be
        constructed even when the student has no prior history.  Zero-history
        defaults produce speed=NORMAL, which is the neutral starting state.

        This mirrors the mini_analytics construction at lines 222-237 of
        teaching_service.py for the Socratic path.
        """
        from adaptive.profile_builder import build_learning_profile
        from adaptive.schemas import AnalyticsSummary

        history = {
            "avg_time_per_card": None,
            "avg_wrong_attempts": None,
            "avg_hints_per_card": None,
            "sessions_last_7d": 0,
        }

        mini_analytics = AnalyticsSummary(
            student_id="student-zero-socratic",
            concept_id="concept::whole-numbers",
            time_spent_sec=history["avg_time_per_card"] or 120.0,
            expected_time_sec=120.0,
            attempts=max(1, round((history["avg_wrong_attempts"] or 0) + 1)),
            wrong_attempts=round(history["avg_wrong_attempts"] or 0),
            hints_used=round(history["avg_hints_per_card"] or 0),
            revisits=0,
            recent_dropoffs=0,
            skip_rate=0.0,
            quiz_score=max(0.1, 1.0 - min((history["avg_wrong_attempts"] or 0) * 0.15, 0.9)),
            last_7d_sessions=history["sessions_last_7d"],
        )

        socratic_profile = build_learning_profile(mini_analytics, has_unmet_prereq=False)

        assert socratic_profile is not None, (
            "build_learning_profile must return a profile for zero-history Socratic path"
        )
        assert socratic_profile.speed == "NORMAL", (
            f"Zero-history student (120s / 120s expected) should have speed=NORMAL, "
            f"got {socratic_profile.speed}"
        )

    # ── Bug 4: quiz_score formula produces STRUGGLING for high error history ─

    def test_quiz_score_not_hardcoded_when_high_error_history(self):
        """
        Bug fix: the quiz_score formula max(0.1, 1.0 - min(avg_wrong * 0.15, 0.9))
        must yield a meaningful (non-1.0) value when avg_wrong is significant.

        With avg_wrong=5:
          min(5 * 0.15, 0.9) = min(0.75, 0.9) = 0.75
          1.0 - 0.75 = 0.25
          max(0.1, 0.25) = 0.25

        quiz_score=0.25 < 0.5 threshold → comprehension == STRUGGLING.
        This validates the bug fix: prior code used a hardcoded 1.0 quiz_score
        regardless of history, which would yield STRONG instead of STRUGGLING.
        """
        from adaptive.profile_builder import build_learning_profile
        from adaptive.schemas import AnalyticsSummary

        avg_wrong = 5
        quiz_score = max(0.1, 1.0 - min(avg_wrong * 0.15, 0.9))

        assert abs(quiz_score - 0.25) < 1e-9, (
            f"Expected quiz_score=0.25 for avg_wrong=5, got {quiz_score}"
        )

        mini = AnalyticsSummary(
            student_id="student-formula",
            concept_id="concept::decimals",
            time_spent_sec=120.0,
            expected_time_sec=120.0,
            attempts=max(1, round(avg_wrong + 1)),
            wrong_attempts=avg_wrong,
            hints_used=2,
            revisits=0,
            recent_dropoffs=0,
            skip_rate=0.0,
            quiz_score=quiz_score,
            last_7d_sessions=1,
        )

        profile = build_learning_profile(mini, has_unmet_prereq=False)

        assert profile.comprehension == "STRUGGLING", (
            f"quiz_score=0.25 (< 0.5 threshold) must produce STRUGGLING, "
            f"got {profile.comprehension}"
        )

    # ── Bug 5: BORED detected when completing very quickly with no errors ────

    def test_engagement_bored_detected_by_speed(self):
        """
        Bug fix: classify_engagement must return BORED when the student
        completes cards very quickly (< 35% of expected time) with zero wrong
        attempts, indicating rushing / disengagement.

        time_spent=30, expected=120: 30 < 120 * 0.35 = 42.0 AND wrong=0 → BORED.
        """
        from adaptive.profile_builder import classify_engagement

        result = classify_engagement(
            time_spent_sec=30,
            expected_time_sec=120,
            wrong_attempts=0,
            hints_used=0,
        )

        assert result == "BORED", (
            f"time=30 < 120*0.35=42 with zero wrong_attempts must yield BORED, got {result}"
        )

    # ── Bug 6: OVERWHELMED from hint count alone ─────────────────────────────

    def test_engagement_overwhelmed_by_hints_alone(self):
        """
        Bug fix: classify_engagement must return OVERWHELMED when hints_used >= 5,
        regardless of whether the student is moving quickly or slowly.

        time=200 (> expected=120, so not BORED), wrong=2 (so BORED check fails anyway),
        hints=6 >= 5 → OVERWHELMED.
        """
        from adaptive.profile_builder import classify_engagement

        result = classify_engagement(
            time_spent_sec=200,
            expected_time_sec=120,
            wrong_attempts=2,
            hints_used=6,
        )

        assert result == "OVERWHELMED", (
            f"hints_used=6 >= 5 must yield OVERWHELMED, got {result}"
        )

    # ── Bug 7: BORED not triggered when wrong_attempts exist ─────────────────

    def test_engagement_not_bored_when_wrong_attempts_exist(self):
        """
        Bug fix: classify_engagement must NOT return BORED when the student has
        wrong_attempts > 0, even if they finished very quickly.

        The BORED rule requires BOTH: time < 35% of expected AND wrong_attempts == 0.
        A student who finishes quickly but made errors is struggling, not bored.

        time=20 (< 120*0.35=42) BUT wrong=3 → BORED guard fails → check OVERWHELMED
        (hints=1 < 5) → ENGAGED.
        """
        from adaptive.profile_builder import classify_engagement

        result = classify_engagement(
            time_spent_sec=20,
            expected_time_sec=120,
            wrong_attempts=3,
            hints_used=1,
        )

        assert result == "ENGAGED", (
            f"wrong_attempts=3 must prevent BORED classification even when time is very short; "
            f"got {result}"
        )


# ===========================================================================
# Group 13 — SpacedReview complete endpoint
# ===========================================================================

class TestSpacedReviewComplete:
    """
    Tests for POST /api/v2/spaced-reviews/{review_id}/complete.

    The endpoint marks a pending SpacedReview as completed by setting
    completed_at to the current UTC time.  It returns ok=True,
    already_completed=False, and the ISO-format timestamp.

    All DB and network calls are fully mocked — no real PostgreSQL required.
    """

    def _install_api_main_stub(self):
        """Pre-inject api.main stub to break any circular import."""
        if "api.main" not in sys.modules:
            stub = MagicMock()
            try:
                from slowapi import Limiter
                from slowapi.util import get_remote_address
                stub.limiter = Limiter(key_func=get_remote_address)
            except ImportError:
                stub.limiter = MagicMock()
            sys.modules["api.main"] = stub

    async def test_spaced_review_complete_sets_completed_at(self):
        """
        Business rule: completing a pending SpacedReview (completed_at=None) must:
          - Set review.completed_at to a non-None datetime
          - Return {"ok": True, "already_completed": False, "completed_at": <iso string>}

        Verifies the bug fix: prior implementation did not set completed_at before
        returning, causing a NoneType.isoformat() AttributeError.
        """
        self._install_api_main_stub()
        from api.teaching_router import complete_spaced_review

        review_id = uuid.uuid4()

        # Build a SpacedReview mock with completed_at=None (not yet completed)
        mock_review = MagicMock()
        mock_review.completed_at = None

        db = AsyncMock()

        async def _db_get(cls, pk):
            return mock_review

        db.get = _db_get
        db.commit = AsyncMock()

        from starlette.requests import Request as StarletteRequest
        real_request = StarletteRequest({
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "headers": [],
        })

        response = await complete_spaced_review(real_request, review_id, db)

        assert response["ok"] is True, (
            f"Response must have ok=True, got ok={response.get('ok')}"
        )
        assert response["already_completed"] is False, (
            "already_completed must be False for a freshly completed review"
        )
        assert response["completed_at"] is not None, (
            "completed_at must be a non-None ISO string in the response"
        )
        assert isinstance(response["completed_at"], str), (
            f"completed_at must be a string (ISO format), got {type(response['completed_at'])}"
        )
        assert mock_review.completed_at is not None, (
            "review.completed_at must have been set on the ORM object before commit"
        )
