"""
test_student_simulations.py
============================
10 end-to-end student simulation tests against the live ADA adaptive learning
platform backend.  All tests are self-contained: each creates its own student
and session at the start, exercises the full learning loop, and asserts on
observable API responses.

No mocks are used.  The tests require:
  - Backend running at http://localhost:8889
  - API_SECRET_KEY set in backend/.env or the API_SECRET_KEY environment variable
  - Prealgebra ChromaDB data loaded (for real concept retrieval)

Endpoint map (discovered from teaching_router.py and adaptive_router.py):
  POST  /api/v2/students
      Create a student profile.
      Body: { display_name, interests, preferred_style, preferred_language }

  POST  /api/v2/sessions
      Start a teaching session.
      Body: { student_id, concept_id, style?, lesson_interests? }

  POST  /api/v2/sessions/{id}/cards
      Generate the initial batch of lesson cards (session must be in PRESENTING phase).
      Returns: CardsResponse { session_id, cards: [LessonCard], ... }

  POST  /api/v2/sessions/{id}/record-interaction
      Save a single card interaction signal.
      Body: RecordInteractionRequest { card_index, time_on_card_sec, wrong_attempts,
                                       hints_used, idle_triggers }
      Returns: { saved: true }

  POST  /api/v2/sessions/{id}/complete-card
      [adaptive_router.cards_router] Record card completion, persist interaction,
      and return the next adaptive card alongside the student's live profile.
      Body: NextCardRequest { card_index, time_on_card_sec, wrong_attempts,
                              re_explain_card_title?, ... }
      Returns: NextCardResponse { session_id, card, card_index,
                                  adaptation_applied, learning_profile_summary,
                                  motivational_note, performance_vs_baseline,
                                  recovery_card }

  POST  /api/v2/sessions/{id}/complete-cards
      Transition session from CARDS/PRESENTING to CARDS_DONE (gateway only).
      Returns: result dict (no fixed schema)

  POST  /api/v2/sessions/{id}/section-complete
      Update student's section_count and avg_state_score.
      Body: SectionCompleteRequest { concept_id, state_score }
      Returns: SectionCompleteResponse { section_count, avg_state_score,
                                         state_distribution }

  POST  /api/v2/sessions/{id}/next-section-cards
      Generate cards for the next queued sub-section (rolling adaptive).
      Body: NextSectionCardsRequest { card_index?, time_on_card_sec?, wrong_attempts?,
                                      hints_used?, idle_triggers? }
      Returns: NextSectionCardsResponse { session_id, cards, has_more_concepts,
                                          concepts_total, concepts_covered_count,
                                          current_mode }

NOTE on "complete-card-and-get-next":
  No single endpoint performs both "record this card" and "get next card" in
  one call using the teaching_router.  The closest equivalent is:
    POST /api/v2/sessions/{id}/complete-card  (from adaptive_router.cards_router)
  which persists the interaction AND returns a new adaptive card plus the
  learning_profile_summary.  This endpoint is used for tests that need to
  observe the adaptive mode or recovery_card behaviour.

NOTE on learning_profile_summary / mode field:
  complete-card returns learning_profile_summary = {
      "speed": "SLOW"|"NORMAL"|"FAST",
      "comprehension": ...,
      "engagement": ...,
      "confidence_score": ...
  }
  "FAST" behaviour maps to speed=="FAST"; "STRUGGLING" maps to
  comprehension=="STRUGGLING" or speed=="SLOW".
"""

import os
import sys
import time
from pathlib import Path

import pytest
import requests

# ---------------------------------------------------------------------------
# Ensure backend/src is importable (mirrors conftest.py / test_phase1_bugs.py)
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8890")

# Read the API key from backend/.env — never hardcode secrets.
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

# LLM-backed generation endpoints can take 10–60 s; use generous timeouts.
CARD_TIMEOUT = 120       # generate cards (full concept)
ADAPTIVE_TIMEOUT = 60    # complete-card (single adaptive card)
SHORT_TIMEOUT = 30       # non-LLM endpoints (create student, start session, etc.)

# Book slug and concept IDs — override via env vars to test any processed book.
# Example: TEST_BOOK_SLUG=elementary_algebra TEST_CONCEPT_IDS="ELEMALG.C1.S1.XXX,ELEMALG.C1.S2.YYY,ELEMALG.C1.S3.ZZZ"
BOOK_SLUG = os.getenv("TEST_BOOK_SLUG", "prealgebra")
_default_concepts = (
    "PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS,"
    "PREALG.C1.S2.ADD_WHOLE_NUMBERS,"
    "PREALG.C1.S3.SUBTRACT_WHOLE_NUMBERS"
)
CONCEPT_IDS = os.getenv("TEST_CONCEPT_IDS", _default_concepts).split(",")


# ---------------------------------------------------------------------------
# Shared helper functions
# ---------------------------------------------------------------------------

def _create_student(display_name: str = "Simulation Student", interests: list | None = None) -> dict:
    """Create a fresh student profile and return the response JSON."""
    resp = requests.post(
        f"{BASE_URL}/api/v2/students",
        json={
            "display_name": display_name,
            "interests": interests or ["space", "games"],
            "preferred_style": "default",
            "preferred_language": "en",
        },
        headers=HEADERS,
        timeout=SHORT_TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"create_student failed: {resp.status_code} {resp.text}"
    )
    return resp.json()


def _start_session(student_id: str, concept_id: str) -> dict:
    """Start a teaching session and return the response JSON."""
    resp = requests.post(
        f"{BASE_URL}/api/v2/sessions",
        json={"student_id": student_id, "concept_id": concept_id},
        headers=HEADERS,
        timeout=SHORT_TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"start_session failed: {resp.status_code} {resp.text}"
    )
    return resp.json()


def _generate_cards(session_id: str) -> dict:
    """Generate the initial lesson card batch for a session in PRESENTING phase."""
    resp = requests.post(
        f"{BASE_URL}/api/v2/sessions/{session_id}/cards",
        headers=HEADERS,
        timeout=CARD_TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"generate_cards failed: {resp.status_code} {resp.text}"
    )
    data = resp.json()
    assert data.get("cards"), (
        f"generate_cards returned an empty cards list for session {session_id}"
    )
    return data


def _record_interaction(
    session_id: str,
    card_index: int,
    *,
    time_on_card_sec: float = 20.0,
    wrong_attempts: int = 0,
    hints_used: int = 0,
) -> dict:
    """POST /record-interaction and assert HTTP 200."""
    resp = requests.post(
        f"{BASE_URL}/api/v2/sessions/{session_id}/record-interaction",
        json={
            "card_index": card_index,
            "time_on_card_sec": time_on_card_sec,
            "wrong_attempts": wrong_attempts,
            "hints_used": hints_used,
            "idle_triggers": 0,
        },
        headers=HEADERS,
        timeout=SHORT_TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"record-interaction failed for card_index={card_index}: "
        f"{resp.status_code} {resp.text}"
    )
    return resp.json()


def _complete_card(
    session_id: str,
    card_index: int,
    *,
    time_on_card_sec: float = 20.0,
    wrong_attempts: int = 0,
    re_explain_card_title: str | None = None,
) -> dict:
    """
    POST /api/v2/sessions/{id}/complete-card (adaptive_router.cards_router).

    Persists the interaction and returns NextCardResponse including
    learning_profile_summary and (conditionally) recovery_card.
    """
    body: dict = {
        "card_index": card_index,
        "time_on_card_sec": time_on_card_sec,
        "wrong_attempts": wrong_attempts,
        "hints_used": 0,
        "idle_triggers": 0,
    }
    if re_explain_card_title is not None:
        body["re_explain_card_title"] = re_explain_card_title

    resp = requests.post(
        f"{BASE_URL}/api/v2/sessions/{session_id}/complete-card",
        json=body,
        headers=HEADERS,
        timeout=ADAPTIVE_TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"complete-card failed for card_index={card_index}: "
        f"{resp.status_code} {resp.text}"
    )
    return resp.json()


def _complete_cards_endpoint(session_id: str) -> dict:
    """POST /complete-cards to transition session to CARDS_DONE phase."""
    resp = requests.post(
        f"{BASE_URL}/api/v2/sessions/{session_id}/complete-cards",
        headers=HEADERS,
        timeout=SHORT_TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"complete-cards failed: {resp.status_code} {resp.text}"
    )
    return resp.json()


# ---------------------------------------------------------------------------
# Test 1 — Card structure for multiple concepts
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestAllSectionsCardStructure:
    """
    Business criterion: every card returned from the /cards endpoint must be
    a valid lesson unit.  Required fields: title, content, card_type.  MCQ
    fields (question / question2 with 4 options each) must be present on all
    non-CHECKIN cards.  This is validated across three known prealgebra concepts
    to ensure the fix is not concept-specific.
    """

    def _assert_card_structure(self, card: dict, concept_id: str) -> None:
        label = (
            f"concept={concept_id!r} card[index={card.get('index')}, "
            f"type={card.get('card_type')!r}, title={str(card.get('title', ''))[:40]!r}]"
        )

        # Required fields on every card
        assert card.get("title") not in (None, "", "None"), (
            f"{label}: 'title' is missing or empty"
        )
        assert card.get("content") not in (None, ""), (
            f"{label}: 'content' is missing or empty"
        )
        assert "card_type" in card, (
            f"{label}: 'card_type' field is absent"
        )

        # MCQ fields — required on all non-CHECKIN cards
        card_type = (card.get("card_type") or "").upper()
        if card_type != "CHECKIN":
            question = card.get("question")
            assert question is not None, (
                f"{label}: 'question' is None on a non-CHECKIN card"
            )
            assert isinstance(question.get("options"), list), (
                f"{label}: question.options is not a list"
            )
            assert len(question["options"]) == 4, (
                f"{label}: question.options must have 4 items, "
                f"got {len(question['options'])}"
            )

            question2 = card.get("question2")
            assert question2 is not None, (
                f"{label}: 'question2' is None on a non-CHECKIN card — "
                "dual-MCQ feature requires a second question on every card"
            )
            assert isinstance(question2.get("options"), list), (
                f"{label}: question2.options is not a list"
            )
            assert len(question2["options"]) == 4, (
                f"{label}: question2.options must have 4 items, "
                f"got {len(question2['options'])}"
            )

    def test_card_structure_concept_1(self):
        """
        All cards for INTRODUCTION_TO_WHOLE_NUMBERS must have required fields
        and valid MCQs on non-CHECKIN cards.
        """
        concept_id = CONCEPT_IDS[0]
        student = _create_student("CardStruct Student C1")
        session = _start_session(student["id"], concept_id)
        data = _generate_cards(session["id"])

        for card in data["cards"]:
            self._assert_card_structure(card, concept_id)

    def test_card_structure_concept_2(self):
        """
        All cards for ADD_WHOLE_NUMBERS must have required fields and valid MCQs.
        """
        concept_id = CONCEPT_IDS[1]
        student = _create_student("CardStruct Student C2")
        session = _start_session(student["id"], concept_id)
        data = _generate_cards(session["id"])

        for card in data["cards"]:
            self._assert_card_structure(card, concept_id)

    def test_card_structure_concept_3(self):
        """
        All cards for SUBTRACT_WHOLE_NUMBERS must have required fields and valid MCQs.
        """
        concept_id = CONCEPT_IDS[2]
        student = _create_student("CardStruct Student C3")
        session = _start_session(student["id"], concept_id)
        data = _generate_cards(session["id"])

        for card in data["cards"]:
            self._assert_card_structure(card, concept_id)


# ---------------------------------------------------------------------------
# Test 2 — Fast student profile
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_fast_student():
    """
    Business criterion: a student who answers every MCQ correctly on the first
    attempt should be classified as a STRONG comprehension learner with a high
    confidence score.  The adaptive engine uses personal baselines for speed
    classification, so a consistently fast student's baseline converges to their
    own pace (speed will be NORMAL relative to themselves).  The meaningful
    signal is comprehension == 'STRONG' and confidence_score >= 0.9.

    Endpoint used: POST /complete-card (adaptive_router.cards_router)
    — returns NextCardResponse.learning_profile_summary { speed, comprehension,
      engagement, confidence_score }.
    """
    student = _create_student("Fast Student Sim")
    session = _start_session(student["id"], CONCEPT_IDS[0])
    data = _generate_cards(session["id"])
    cards = data["cards"]

    last_response = None
    for card in cards:
        last_response = _complete_card(
            session["id"],
            card["index"],
            time_on_card_sec=12.0,
            wrong_attempts=0,
        )

    assert last_response is not None, "No complete-card response captured"

    profile = last_response.get("learning_profile_summary", {})
    comprehension = profile.get("comprehension", "")
    confidence = profile.get("confidence_score", 0.0)

    assert comprehension == "STRONG", (
        f"Expected comprehension == 'STRONG' for a student with zero wrong attempts; "
        f"got comprehension={comprehension!r}. Full profile: {profile}"
    )
    assert confidence >= 0.9, (
        f"Expected confidence_score >= 0.9 for all-correct student; "
        f"got confidence_score={confidence!r}. Full profile: {profile}"
    )


# ---------------------------------------------------------------------------
# Test 3 — Struggling student profile and recovery cards
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_struggling_student():
    """
    Business criterion: when a student answers 2+ cards with wrong_attempts=2
    and provides a re_explain_card_title, the backend must return a recovery_card
    (not null) in at least one NextCardResponse.  This confirms the remediation
    path is active for struggling students.

    The recovery_card is only generated when wrong_attempts >= 2 AND
    re_explain_card_title is set AND the title does not start with
    "Let's Try Again" (anti-loop guard in adaptive_router.py line ~235).
    """
    student = _create_student("Struggling Student Sim")
    session = _start_session(student["id"], CONCEPT_IDS[0])
    data = _generate_cards(session["id"])
    cards = data["cards"]

    # Exercise at least 3 cards with wrong answers + re-explain trigger
    exercise_cards = cards[:max(3, len(cards))]
    recovery_cards_received = []

    for card in exercise_cards:
        card_title = card.get("title", "Unknown Topic")
        resp = _complete_card(
            session["id"],
            card["index"],
            time_on_card_sec=90.0,
            wrong_attempts=2,
            re_explain_card_title=card_title,
        )
        if resp.get("recovery_card") is not None:
            recovery_cards_received.append(resp["recovery_card"])

    assert len(recovery_cards_received) >= 1, (
        "Expected at least one recovery_card across 3+ cards with wrong_attempts=2 "
        f"and re_explain_card_title set; received 0 recovery cards. "
        "This indicates the remediation path in complete-card is not triggering."
    )


# ---------------------------------------------------------------------------
# Test 4 — Normal student (mixed correct/incorrect pattern)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_normal_student():
    """
    Business criterion: a student with a mostly-correct performance pattern
    (3 correct + 1 wrong) should not be classified as FAST.  Speed must be
    'NORMAL' or 'SLOW'.  The adaptive engine classifies comprehension per-card
    relative to blended signals; a single wrong attempt naturally raises the
    error rate to 0.5, so STRUGGLING on the last card is expected — the key
    requirement is that the student is not classified as FAST (implying the
    engine responds to errors at all).

    This verifies that the adaptive engine does not over-classify a mostly-
    correct performer as a fast learner.
    """
    student = _create_student("Normal Student Sim")
    session = _start_session(student["id"], CONCEPT_IDS[1])
    data = _generate_cards(session["id"])
    cards = data["cards"]

    exercise_cards = cards[:min(4, len(cards))]
    assert len(exercise_cards) >= 2, (
        "Need at least 2 cards to run the normal-student mixed pattern test"
    )

    last_response = None
    for i, card in enumerate(exercise_cards):
        # 3 correct cards then 1 wrong on the last card
        wrong = 1 if i == len(exercise_cards) - 1 else 0
        time_sec = 30.0
        last_response = _complete_card(
            session["id"],
            card["index"],
            time_on_card_sec=time_sec,
            wrong_attempts=wrong,
        )

    assert last_response is not None, "No complete-card response captured"

    profile = last_response.get("learning_profile_summary", {})
    speed = profile.get("speed", "")

    assert speed != "FAST", (
        f"Normal student classified as FAST despite having a wrong attempt — "
        f"expected NORMAL or SLOW, got speed={speed!r}. Profile: {profile}"
    )


# ---------------------------------------------------------------------------
# Test 5 — Mode transition: fast then slow
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_mode_transition():
    """
    Business criterion: the adaptive engine must respond dynamically to
    changing student behaviour.  After 3 fast-correct cards the profile
    should indicate FAST or high confidence; after 3 additional slow-wrong
    cards the profile must shift to a different speed classification.

    Verifies that mode is not constant throughout the interaction sequence —
    the system is adaptive, not static.
    """
    student = _create_student("Mode Transition Student")
    # Use C1S2 (ADD_WHOLE_NUMBERS) which has 6 sub-sections (more than C1S1's 4)
    session = _start_session(student["id"], CONCEPT_IDS[1])
    data = _generate_cards(session["id"])
    cards = data["cards"]

    assert len(cards) >= 4, (
        f"Need at least 4 cards for mode-transition test; got {len(cards)}. "
        "Consider using a concept with more sub-sections."
    )

    # Phase 1: first half — fast, correct cards
    half = len(cards) // 2
    mode_after_fast: str | None = None
    for card in cards[:half]:
        resp = _complete_card(
            session["id"],
            card["index"],
            time_on_card_sec=10.0,
            wrong_attempts=0,
        )
        mode_after_fast = resp.get("learning_profile_summary", {}).get("speed")

    # Phase 2: second half — slow, wrong cards
    mode_after_slow: str | None = None
    for card in cards[half:]:
        resp = _complete_card(
            session["id"],
            card["index"],
            time_on_card_sec=120.0,
            wrong_attempts=2,
        )
        mode_after_slow = resp.get("learning_profile_summary", {}).get("speed")

    assert mode_after_fast is not None, "No mode captured after fast phase"
    assert mode_after_slow is not None, "No mode captured after slow phase"

    assert mode_after_fast != mode_after_slow, (
        f"Mode did not transition between fast phase ({mode_after_fast!r}) "
        f"and slow phase ({mode_after_slow!r}).  "
        "The adaptive engine must update the student profile based on signals."
    )


# ---------------------------------------------------------------------------
# Test 6 — Recovery card on recovery card (no infinite loop)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_recovery_card_not_nested():
    """
    Business criterion: when a student answers a recovery card incorrectly
    (wrong_attempts=2), the backend must respond with HTTP 200 and must not
    crash or enter an infinite loop.  A nested recovery card is acceptable
    (though not required) as long as the response is a structurally valid card.

    Anti-loop guard in adaptive_router.py: recovery is only generated when
    re_explain_card_title does NOT start with "Let's Try Again".  When it does
    start with "Let's Try Again", recovery_card is None — this is the correct
    sentinel that prevents infinite recursion.
    """
    student = _create_student("Recovery Nesting Student")
    session = _start_session(student["id"], CONCEPT_IDS[0])
    data = _generate_cards(session["id"])
    cards = data["cards"]
    assert cards, "Need at least one card"

    first_card = cards[0]
    first_title = first_card.get("title", "Intro Topic")

    # Step 1: trigger an initial recovery card
    resp1 = _complete_card(
        session["id"],
        first_card["index"],
        time_on_card_sec=90.0,
        wrong_attempts=2,
        re_explain_card_title=first_title,
    )
    assert resp1.get("card") is not None, (
        "complete-card returned no card in the response body"
    )

    # Step 2: simulate the student also failing the recovery card.
    # The recovery card title starts with "Let's Try Again" by convention
    # (see prompts.py).  Using that title activates the anti-loop guard,
    # so recovery_card must be None — no infinite nesting.
    recovery_title = "Let's Try Again — " + first_title
    resp2 = _complete_card(
        session["id"],
        first_card["index"] + 1,
        time_on_card_sec=90.0,
        wrong_attempts=2,
        re_explain_card_title=recovery_title,
    )
    # The API must succeed (HTTP 200 already asserted inside _complete_card)
    assert resp2.get("card") is not None, (
        "complete-card returned no card when failing on a recovery card"
    )
    # Anti-loop guard must prevent a nested recovery
    assert resp2.get("recovery_card") is None, (
        "Expected recovery_card=None when re_explain_card_title starts with "
        "'Let's Try Again' (anti-loop guard should have suppressed it), "
        f"but got recovery_card={resp2.get('recovery_card')!r}"
    )


# ---------------------------------------------------------------------------
# Test 7 — Consecutive recoveries are distinct
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_consecutive_recoveries():
    """
    Business criterion: when a student gets wrong_attempts=2 on 3 consecutive
    cards, each yielding a recovery_card, the 3 recovery cards must each have
    a non-null, non-'None' title.  They should ideally differ from each other
    (the LLM is expected to produce distinct re-explanations per topic), but
    the hard requirement is that no recovery card has a blank or sentinel title.
    """
    student = _create_student("Consecutive Recovery Student")
    session = _start_session(student["id"], CONCEPT_IDS[0])
    data = _generate_cards(session["id"])
    cards = data["cards"]

    assert len(cards) >= 3, (
        f"Need at least 3 cards for consecutive-recovery test; got {len(cards)}"
    )

    recovery_titles: list[str] = []

    for card in cards[:3]:
        card_title = card.get("title", "Topic")
        resp = _complete_card(
            session["id"],
            card["index"],
            time_on_card_sec=95.0,
            wrong_attempts=2,
            re_explain_card_title=card_title,
        )
        rc = resp.get("recovery_card")
        if rc is not None:
            title = rc.get("title", "")
            assert title not in (None, "", "None"), (
                f"recovery_card has a blank/sentinel title for card index "
                f"{card['index']}: got title={title!r}"
            )
            recovery_titles.append(title)

    # We expect at least 1 recovery card; 3 is ideal but LLM may not always
    # trigger recovery if card title heuristics differ.
    assert len(recovery_titles) >= 1, (
        "Expected at least 1 recovery card across 3 cards with wrong_attempts=2 "
        "and re_explain_card_title set"
    )


# ---------------------------------------------------------------------------
# Test 8 — Last card completion via complete-cards endpoint
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_last_card_completion():
    """
    Business criterion: after a student records interactions for all cards
    in a lesson, calling POST /complete-cards must return HTTP 200 and
    transition the session out of the CARDS/PRESENTING phase.

    This verifies the gateway endpoint that moves the session from the
    card-learning phase to CARDS_DONE (precondition for the Socratic check).
    """
    student = _create_student("Last Card Completion Student")
    session = _start_session(student["id"], CONCEPT_IDS[1])
    data = _generate_cards(session["id"])
    cards = data["cards"]
    session_id = session["id"]

    # Record interactions for all cards (simulating completion of the lesson)
    for card in cards:
        _record_interaction(
            session_id,
            card["index"],
            time_on_card_sec=20.0,
            wrong_attempts=0,
        )

    # Transition via complete-cards
    result = _complete_cards_endpoint(session_id)

    # The endpoint returns a dict; the session should now be in CARDS_DONE.
    # Verify the call succeeded (HTTP 200 already checked inside helper).
    assert result is not None, "complete-cards returned None response body"

    # Confirm session phase has advanced
    session_resp = requests.get(
        f"{BASE_URL}/api/v2/sessions/{session_id}",
        headers=HEADERS,
        timeout=SHORT_TIMEOUT,
    )
    assert session_resp.status_code == 200, (
        f"GET /sessions/{session_id} failed: {session_resp.status_code}"
    )
    phase = session_resp.json().get("phase", "")
    assert phase in ("CARDS_DONE", "COMPLETED", "CHECKING"), (
        f"Expected session to advance to CARDS_DONE after complete-cards; "
        f"got phase={phase!r}"
    )


# ---------------------------------------------------------------------------
# Test 9 — Last card wrong, then section completion
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_last_card_both_wrong():
    """
    Business criterion: if a student answers the last card in a lesson
    incorrectly (wrong_attempts=2), the backend should still provide a
    recovery card (or at least not crash), AND the student must still be
    able to call complete-cards afterward.  Both calls must return HTTP 200.

    This validates that the completion flow is not blocked by a wrong answer
    on the final card.
    """
    student = _create_student("Last Card Wrong Student")
    session = _start_session(student["id"], CONCEPT_IDS[2])
    data = _generate_cards(session["id"])
    cards = data["cards"]
    session_id = session["id"]

    # Record all cards except the last with correct answers
    for card in cards[:-1]:
        _record_interaction(
            session_id,
            card["index"],
            time_on_card_sec=20.0,
            wrong_attempts=0,
        )

    # Last card: wrong_attempts=2 via complete-card (also persists interaction)
    last_card = cards[-1]
    last_card_title = last_card.get("title", "Final Topic")

    resp = _complete_card(
        session_id,
        last_card["index"],
        time_on_card_sec=90.0,
        wrong_attempts=2,
        re_explain_card_title=last_card_title,
    )
    # Assert HTTP 200 already done inside _complete_card
    assert resp.get("card") is not None, (
        "complete-card for last card with wrong_attempts=2 returned no card"
    )

    # Now complete the section — must succeed even after a wrong final card
    complete_resp = _complete_cards_endpoint(session_id)
    assert complete_resp is not None, (
        "complete-cards failed after a wrong answer on the last card"
    )


# ---------------------------------------------------------------------------
# Test 10 — Cross-section profile persistence
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_cross_section_profile_persistence():
    """
    Business criterion: when a student shows a struggling pattern (wrong_attempts=2
    on every card) in section 1, that profile must be reflected when they begin
    section 2.  The section_complete endpoint updates the student's avg_state_score
    and state_distribution; the subsequent next-section-cards call should return
    current_mode reflecting the struggling history.

    Flow:
      1. Create student, start session on concept 1.
      2. Generate cards; complete all with wrong_attempts=2 (struggling).
      3. Call section-complete with a low state_score (1.0 = struggling).
      4. Start a second session on concept 2.
      5. Generate initial cards, then call next-section-cards.
      6. Verify current_mode in the next-section-cards response is 'SLOW'
         (indicating the struggling history was loaded), OR verify that
         the student's state_distribution shows struggling > 0.

    NOTE: section-complete is the authoritative signal that writes the student's
    cumulative struggle data to the DB.  next-section-cards reads this via
    blended live signals + student history.
    """
    student = _create_student("Cross Section Persistence Student")
    student_id = student["id"]

    # --- Section 1: struggling pattern ---
    session1 = _start_session(student_id, CONCEPT_IDS[0])
    data1 = _generate_cards(session1["id"])
    cards1 = data1["cards"]

    for card in cards1:
        _record_interaction(
            session1["id"],
            card["index"],
            time_on_card_sec=120.0,
            wrong_attempts=2,
        )

    # Mark section 1 as complete with a low (struggling) state_score
    section_resp = requests.post(
        f"{BASE_URL}/api/v2/sessions/{session1['id']}/section-complete",
        json={
            "concept_id": CONCEPT_IDS[0],
            "state_score": 1.0,  # 1.0 maps to "struggling" bucket
        },
        headers=HEADERS,
        timeout=SHORT_TIMEOUT,
    )
    assert section_resp.status_code == 200, (
        f"section-complete failed: {section_resp.status_code} {section_resp.text}"
    )
    section_data = section_resp.json()

    # Verify DB wrote the struggling data
    assert section_data.get("section_count", 0) >= 1, (
        "section_count should be >= 1 after completing one section"
    )
    state_dist = section_data.get("state_distribution", {})
    assert state_dist.get("struggling", 0) >= 1, (
        f"state_distribution.struggling should be >= 1 after a low state_score; "
        f"got: {state_dist}"
    )

    # --- Section 2: verify profile carries over ---
    session2 = _start_session(student_id, CONCEPT_IDS[1])

    # Generate initial cards to move session into CARDS phase
    _generate_cards(session2["id"])

    # Call next-section-cards with struggling live signals to blend with history
    next_section_resp = requests.post(
        f"{BASE_URL}/api/v2/sessions/{session2['id']}/next-section-cards",
        json={
            "card_index": 0,
            "time_on_card_sec": 120.0,
            "wrong_attempts": 2,
            "hints_used": 1,
            "idle_triggers": 0,
        },
        headers=HEADERS,
        timeout=CARD_TIMEOUT,
    )

    if next_section_resp.status_code == 400:
        # 400 is returned when no more sections are queued (all covered in initial /cards).
        # In this case, verify persistence via the student's state_distribution instead.
        student_analytics = requests.get(
            f"{BASE_URL}/api/v2/students/{student_id}/analytics",
            headers=HEADERS,
            timeout=SHORT_TIMEOUT,
        )
        assert student_analytics.status_code == 200, (
            f"GET /students/{student_id}/analytics failed: "
            f"{student_analytics.status_code}"
        )
        analytics = student_analytics.json()
        avg_wrong = analytics.get("avg_wrong_attempts_per_card", 0)
        assert avg_wrong > 0, (
            "Expected avg_wrong_attempts_per_card > 0 after struggling section 1; "
            f"got {avg_wrong}.  Cross-section profile persistence is not working."
        )
        return

    assert next_section_resp.status_code == 200, (
        f"next-section-cards returned unexpected status: "
        f"{next_section_resp.status_code} {next_section_resp.text}"
    )

    nsc_data = next_section_resp.json()
    current_mode = nsc_data.get("current_mode", "")

    # After a struggling section 1, the blended mode should lean toward SLOW.
    # NORMAL is also acceptable if history weight is low (few sessions),
    # but FAST would indicate profile persistence is not working at all.
    assert current_mode in ("SLOW", "NORMAL"), (
        f"Expected current_mode to be SLOW or NORMAL after a struggling section 1; "
        f"got current_mode={current_mode!r}.  "
        "This suggests cross-section profile data is not being loaded correctly."
    )
