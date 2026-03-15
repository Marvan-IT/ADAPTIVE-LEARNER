"""
test_phase1_bugs.py
===================
Integration tests verifying four Phase-1 bug fixes applied to the ADA
adaptive learning platform.  All tests call the LIVE backend at
http://localhost:8889 using synchronous ``requests`` — no mocks.

Endpoint map (discovered from teaching_router.py):
    POST   /api/v2/students                                  — create student
    POST   /api/v2/sessions                                  — start session
    POST   /api/v2/sessions/{id}/cards                       — generate cards (PRESENTING phase)
    POST   /api/v2/sessions/{id}/record-interaction          — record one card interaction
    POST   /api/v2/sessions/{id}/section-complete            — mark a section done

Bug fixes under test:
  Bug 1 — Card ordering: cards must be sorted by _section_index so curriculum
           order is preserved across the rolling per-section generation pipeline.
           The public response ``index`` values must be strictly 0, 1, 2, ...
           and the source sort expression must be present.

  Bug 2 — question2 always present: every non-CHECKIN card in a CardsResponse
           must carry both ``question`` and ``question2`` MCQs with exactly 4
           options each and a correct_index in [0, 3].

  Bug 3 — Next button unblocked after 2 wrong attempts: calling
           POST /record-interaction with wrong_attempts=2 must succeed (HTTP 200)
           and return {"saved": true}.  This exercises the path that was
           previously blocking the frontend after a second wrong answer.

  Bug 4 — Cache version: _CARDS_CACHE_VERSION constant must equal 12 in the
           generate_cards source, and the HTTP CardsResponse body must contain
           "cache_version": 12.

Setup requirements:
    - Backend running at http://localhost:8889
    - API_SECRET_KEY set in backend/.env and reachable via os.getenv or direct read
    - Prealgebra ChromaDB data loaded (for real concept retrieval)
"""

import inspect
import os
import sys
from pathlib import Path

import pytest
import requests

# ---------------------------------------------------------------------------
# Ensure backend/src is importable (mirrors conftest.py pattern)
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:8890"

# Read the API key from the backend .env file so the test file contains no
# hardcoded secret.  Falls back to environment variable for CI use.
def _load_api_key() -> str:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("API_SECRET_KEY="):
                return line.split("=", 1)[1].strip()
    return os.getenv("API_SECRET_KEY", "")


API_KEY = _load_api_key()
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

# LLM-backed card generation can take 10–30 s per concept
CARD_TIMEOUT = 120

# Concepts known to exist in the prealgebra ChromaDB (used across tests)
CONCEPT_IDS = [
    "PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS",
    "PREALG.C1.S2.ADD_WHOLE_NUMBERS",
    "PREALG.C1.S3.SUBTRACT_WHOLE_NUMBERS",
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _create_student(display_name: str = "Phase1 Test Student") -> dict:
    """Create a fresh student and return the response JSON."""
    resp = requests.post(
        f"{BASE_URL}/api/v2/students",
        json={
            "display_name": display_name,
            "interests": ["space"],
            "preferred_style": "default",
            "preferred_language": "en",
        },
        headers=HEADERS,
        timeout=30,
    )
    assert resp.status_code == 200, f"create_student failed: {resp.status_code} {resp.text}"
    return resp.json()


def _start_session(student_id: str, concept_id: str) -> dict:
    """Start a teaching session and return the response JSON."""
    resp = requests.post(
        f"{BASE_URL}/api/v2/sessions",
        json={"student_id": student_id, "concept_id": concept_id},
        headers=HEADERS,
        timeout=30,
    )
    assert resp.status_code == 200, f"start_session failed: {resp.status_code} {resp.text}"
    return resp.json()


def _generate_cards(session_id: str) -> dict:
    """Generate cards for a session in PRESENTING phase; return response JSON."""
    resp = requests.post(
        f"{BASE_URL}/api/v2/sessions/{session_id}/cards",
        headers=HEADERS,
        timeout=CARD_TIMEOUT,
    )
    assert resp.status_code == 200, f"generate_cards failed: {resp.status_code} {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# Bug 1 — Card ordering
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestBug1CardOrdering:
    """
    Business criterion: cards returned by POST /cards must be in curriculum
    order.  The backend sorts by _section_index (an internal integer stamp
    assigned during per-section generation).  The public ``index`` field
    reflects final position (0, 1, 2, ...) after the sort.

    Two sub-tests:
    1. Source-level: the sort expression is present in generate_cards source.
    2. HTTP-level: ``index`` values across all returned cards are exactly
       0, 1, 2, ... (no gaps, no duplicates, strictly ascending by 1).
    """

    def test_sort_expression_present_in_source(self):
        """generate_cards source must contain the _section_index sort expression."""
        from api.teaching_service import TeachingService

        source = inspect.getsource(TeachingService.generate_cards)

        assert "_section_index" in source, (
            "_section_index stamp not found in generate_cards source — "
            "the curriculum-order sort may have been removed"
        )
        assert "all_raw_cards.sort" in source, (
            "all_raw_cards.sort not found in generate_cards source — "
            "the card ordering sort call may have been removed"
        )

    def test_card_index_values_are_sequential_for_two_concepts(self):
        """
        For each of two different concepts, the ``index`` values across all
        returned cards must be exactly [0, 1, 2, ..., N-1] — indicating the
        backend assigned positions correctly after sorting by section order.
        """
        test_concepts = CONCEPT_IDS[:2]

        for concept_id in test_concepts:
            student = _create_student(f"Bug1 Student for {concept_id[:20]}")
            session = _start_session(student["id"], concept_id)
            data = _generate_cards(session["id"])

            cards = data.get("cards", [])
            assert len(cards) > 0, (
                f"No cards returned for concept {concept_id!r} — "
                "cannot verify ordering"
            )

            indices = [card["index"] for card in cards]
            expected = list(range(len(cards)))

            assert indices == expected, (
                f"Card indices for {concept_id!r} are not sequential: "
                f"got {indices}, expected {expected}.  "
                "This indicates the post-sort index assignment failed."
            )

    def test_card_index_values_are_sequential_for_third_concept(self):
        """
        Repeat the ordering check for a third concept to confirm the fix is
        not concept-specific.
        """
        concept_id = CONCEPT_IDS[2]
        student = _create_student("Bug1 Student Third Concept")
        session = _start_session(student["id"], concept_id)
        data = _generate_cards(session["id"])

        cards = data.get("cards", [])
        assert len(cards) > 0, f"No cards returned for {concept_id!r}"

        indices = [card["index"] for card in cards]
        expected = list(range(len(cards)))

        assert indices == expected, (
            f"Card indices for {concept_id!r} are not sequential: "
            f"got {indices}, expected {expected}"
        )


# ---------------------------------------------------------------------------
# Bug 2 — question2 always present on every non-CHECKIN card
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestBug2Question2AlwaysPresent:
    """
    Business criterion: every LLM-generated card (card_type != 'CHECKIN') must
    have both ``question`` and ``question2`` populated with valid 4-option MCQs.
    Frontend relies on question2 to show a replacement question after the first
    wrong answer without a network round-trip.

    Tested across 3 different concepts to ensure this is not concept-specific.
    """

    def _assert_mcq_valid(self, mcq: dict, label: str) -> None:
        """Assert that a single MCQ dict has the required structure."""
        assert mcq is not None, f"{label} is None"
        assert isinstance(mcq, dict), f"{label} is not a dict, got {type(mcq)}"

        options = mcq.get("options")
        assert options is not None, f"{label}.options is missing"
        assert isinstance(options, list), f"{label}.options is not a list"
        assert len(options) == 4, (
            f"{label}.options must have exactly 4 items, got {len(options)}: {options}"
        )

        correct_index = mcq.get("correct_index")
        assert correct_index is not None, f"{label}.correct_index is missing"
        assert isinstance(correct_index, int), (
            f"{label}.correct_index must be int, got {type(correct_index)}"
        )
        assert 0 <= correct_index <= 3, (
            f"{label}.correct_index must be in [0, 3], got {correct_index}"
        )

    def _check_concept_cards(self, concept_id: str) -> None:
        """Create a student/session, generate cards, and validate all non-CHECKIN cards."""
        student = _create_student(f"Bug2 Student {concept_id[-12:]}")
        session = _start_session(student["id"], concept_id)
        data = _generate_cards(session["id"])

        cards = data.get("cards", [])
        assert len(cards) > 0, f"No cards returned for {concept_id!r}"

        non_checkin_cards = [
            card for card in cards
            if card.get("card_type", "").upper() != "CHECKIN"
        ]
        assert len(non_checkin_cards) > 0, (
            f"All cards for {concept_id!r} are CHECKIN cards — cannot test MCQ presence"
        )

        for card in non_checkin_cards:
            card_label = f"card[index={card.get('index')}, type={card.get('card_type')!r}, title={card.get('title', '')[:40]!r}]"

            question = card.get("question")
            assert question is not None, (
                f"{card_label}: ``question`` is None — bug2 fix did not apply"
            )
            self._assert_mcq_valid(question, f"{card_label}.question")

            question2 = card.get("question2")
            assert question2 is not None, (
                f"{card_label}: ``question2`` is None — bug2 fix: "
                "second MCQ must always be present for non-CHECKIN cards"
            )
            self._assert_mcq_valid(question2, f"{card_label}.question2")

    def test_question2_present_for_concept_1(self):
        """All non-CHECKIN cards for concept 1 should carry both question and question2."""
        self._check_concept_cards(CONCEPT_IDS[0])

    def test_question2_present_for_concept_2(self):
        """All non-CHECKIN cards for concept 2 should carry both question and question2."""
        self._check_concept_cards(CONCEPT_IDS[1])

    def test_question2_present_for_concept_3(self):
        """All non-CHECKIN cards for concept 3 should carry both question and question2."""
        self._check_concept_cards(CONCEPT_IDS[2])


# ---------------------------------------------------------------------------
# Bug 3 — Next button unblocked after 2 wrong attempts
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestBug3NextButtonUnblocked:
    """
    Business criterion: a student who answers a card incorrectly twice must
    still be able to proceed.  The backend must accept a card interaction with
    wrong_attempts=2 and return HTTP 200 {"saved": true} — it must not block,
    error, or return a stuck state.

    Endpoint: POST /api/v2/sessions/{session_id}/record-interaction
    Schema (RecordInteractionRequest):
        card_index: int (required, >= 0)
        time_on_card_sec: float (default 0.0)
        wrong_attempts: int (default 0)
        hints_used: int (default 0)
        idle_triggers: int (default 0)
    """

    def test_record_interaction_with_two_wrong_attempts_returns_200(self):
        """
        POST /record-interaction with wrong_attempts=2 must return HTTP 200
        and {"saved": true}.  This verifies the backend does not block the
        student after two consecutive wrong answers on the same card.
        """
        student = _create_student("Bug3 Test Student")
        session = _start_session(student["id"], CONCEPT_IDS[0])

        # Generate cards first so the session has context (phase stays PRESENTING
        # since we never call complete-cards, but record-interaction only requires
        # the session to exist — not a specific phase)
        cards_data = _generate_cards(session["id"])
        assert cards_data.get("cards"), "Need at least one card for bug3 test"

        session_id = session["id"]
        first_card_index = cards_data["cards"][0]["index"]

        resp = requests.post(
            f"{BASE_URL}/api/v2/sessions/{session_id}/record-interaction",
            json={
                "card_index": first_card_index,
                "time_on_card_sec": 45.0,
                "wrong_attempts": 2,
                "hints_used": 1,
                "idle_triggers": 0,
            },
            headers=HEADERS,
            timeout=30,
        )

        assert resp.status_code == 200, (
            f"record-interaction with wrong_attempts=2 returned {resp.status_code}: {resp.text}.  "
            "Bug3: the backend should not block on a second wrong answer."
        )
        body = resp.json()
        assert body.get("saved") is True, (
            f"Expected {{\"saved\": true}} but got {body}.  "
            "Bug3: interaction was not saved successfully after 2 wrong attempts."
        )

    def test_record_interaction_with_zero_wrong_attempts_returns_200(self):
        """
        Baseline: POST /record-interaction with wrong_attempts=0 (correct answer)
        must also return HTTP 200 and {"saved": true}.
        """
        student = _create_student("Bug3 Baseline Student")
        session = _start_session(student["id"], CONCEPT_IDS[1])
        cards_data = _generate_cards(session["id"])
        assert cards_data.get("cards"), "Need at least one card for bug3 baseline test"

        session_id = session["id"]
        first_card_index = cards_data["cards"][0]["index"]

        resp = requests.post(
            f"{BASE_URL}/api/v2/sessions/{session_id}/record-interaction",
            json={
                "card_index": first_card_index,
                "time_on_card_sec": 20.0,
                "wrong_attempts": 0,
                "hints_used": 0,
                "idle_triggers": 0,
            },
            headers=HEADERS,
            timeout=30,
        )

        assert resp.status_code == 200, (
            f"record-interaction with wrong_attempts=0 returned {resp.status_code}: {resp.text}"
        )
        assert resp.json().get("saved") is True

    def test_record_interaction_on_multiple_cards_does_not_block(self):
        """
        Record interactions with wrong_attempts=2 for every card in a generated
        lesson.  None of the calls should return a non-200 status, confirming
        the backend is stateless with respect to blocking on repeated errors.
        """
        student = _create_student("Bug3 Multi-Card Student")
        session = _start_session(student["id"], CONCEPT_IDS[2])
        cards_data = _generate_cards(session["id"])
        cards = cards_data.get("cards", [])
        assert cards, "Need cards for multi-card bug3 test"

        session_id = session["id"]
        for card in cards:
            resp = requests.post(
                f"{BASE_URL}/api/v2/sessions/{session_id}/record-interaction",
                json={
                    "card_index": card["index"],
                    "time_on_card_sec": 30.0,
                    "wrong_attempts": 2,
                    "hints_used": 0,
                    "idle_triggers": 0,
                },
                headers=HEADERS,
                timeout=30,
            )
            assert resp.status_code == 200, (
                f"record-interaction blocked on card index {card['index']} "
                f"with wrong_attempts=2: {resp.status_code} {resp.text}"
            )
            assert resp.json().get("saved") is True, (
                f"record-interaction did not save card index {card['index']}: {resp.json()}"
            )


# ---------------------------------------------------------------------------
# Bug 4 — Cache version
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestBug4CacheVersion:
    """
    Business criterion: the card cache must use version 12 so that any
    sessions cached under an earlier version are automatically regenerated.
    This prevents stale cards (e.g. missing question2, wrong ordering) from
    being served from the DB cache.

    Two sub-tests:
    1. Source-level: the literal 12 is present in generate_cards source.
    2. HTTP-level: the JSON response from POST /cards contains
       "cache_version": 12.
    """

    def test_cache_version_constant_is_12_in_source(self):
        """
        _CARDS_CACHE_VERSION must be assigned the literal value 12 inside
        generate_cards.  This is a local variable (not module-level), so we
        verify it through source inspection.
        """
        from api.teaching_service import TeachingService

        source = inspect.getsource(TeachingService.generate_cards)

        assert "_CARDS_CACHE_VERSION = 12" in source, (
            "_CARDS_CACHE_VERSION = 12 not found in generate_cards source.  "
            "Expected the cache version to be 12 after the rolling-architecture upgrade."
        )

    def test_cards_response_contains_cache_version_12(self):
        """
        POST /sessions/{id}/cards response JSON must include "cache_version": 12.
        This confirms the constant is used when building the result dict, not
        just assigned but unused.
        """
        student = _create_student("Bug4 Cache Version Student")
        session = _start_session(student["id"], CONCEPT_IDS[0])
        data = _generate_cards(session["id"])

        cache_version = data.get("cache_version")
        assert cache_version is not None, (
            "Response JSON does not contain 'cache_version' key.  "
            "The result dict must include cache_version for staleness detection."
        )
        assert cache_version == 12, (
            f"Expected cache_version == 12 but got {cache_version!r}.  "
            "Bug4: cache version must be bumped to 12 to bust stale sessions."
        )

    def test_second_cards_request_returns_same_cache_version(self):
        """
        Calling POST /cards twice on the same session must return
        cache_version == 12 on both calls (the second call hits the DB cache).
        This confirms the cache version is preserved through the cache round-trip.
        """
        student = _create_student("Bug4 Cache Roundtrip Student")
        session = _start_session(student["id"], CONCEPT_IDS[1])

        first = _generate_cards(session["id"])
        assert first.get("cache_version") == 12, (
            f"First cards call returned cache_version={first.get('cache_version')!r}, expected 12"
        )

        # Second call — should hit the DB cache (session.presentation_text is populated)
        second = _generate_cards(session["id"])
        assert second.get("cache_version") == 12, (
            f"Second cards call (cache hit) returned cache_version={second.get('cache_version')!r}, "
            "expected 12.  The cached result dict must preserve the version field."
        )

        # Both responses should return the same number of cards
        assert len(first.get("cards", [])) == len(second.get("cards", [])), (
            "Cache hit returned a different card count than the first generation — "
            "cache is not stable."
        )
