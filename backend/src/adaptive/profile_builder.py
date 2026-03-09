"""
Converts AnalyticsSummary → LearningProfile deterministically.

All functions are pure (no I/O, no side effects) and are directly unit-testable
without any mocks.  Classification order within each function matters — see
inline comments for the reasoning behind the evaluation sequence.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adaptive.schemas import AnalyticsSummary, LearningProfile
from config import ADAPTIVE_ERROR_PENALTY_WEIGHT, ADAPTIVE_HINT_PENALTY_WEIGHT

logger = logging.getLogger(__name__)


# ── Speed ──────────────────────────────────────────────────────────────────────

def classify_speed(time_spent_sec: float, expected_time_sec: float, attempts: int) -> str:
    """
    Classify a student's working speed.

    Rules (evaluated in order):
      SLOW   — time_spent > expected * 1.5
      FAST   — time_spent < expected * 0.7  AND  attempts <= 1
               (the attempts guard prevents a student who guessed rapidly from
               being labelled FAST)
      NORMAL — everything else

    Returns one of: "SLOW", "NORMAL", "FAST"
    """
    if time_spent_sec > expected_time_sec * 1.5:
        return "SLOW"
    if time_spent_sec < expected_time_sec * 0.7 and attempts <= 1:
        return "FAST"
    return "NORMAL"


# ── Comprehension ──────────────────────────────────────────────────────────────

def classify_comprehension(
    wrong_attempts: int,
    attempts: int,
    quiz_score: float,
    hints_used: int,
) -> str:
    """
    Classify a student's concept comprehension.

    Derives error_rate = wrong_attempts / attempts internally.

    Rules (evaluated in order):
      STRUGGLING — error_rate >= 0.5  OR  quiz_score < 0.5
                   (STRUGGLING check runs first: a high quiz score does not
                   override extremely high error rate)
      STRONG     — quiz_score >= 0.8  AND  error_rate <= 0.2  AND  hints_used <= 2
      OK         — everything else

    Returns one of: "STRUGGLING", "OK", "STRONG"
    """
    error_rate = wrong_attempts / attempts if attempts > 0 else 0.0
    if error_rate >= 0.5 or quiz_score < 0.5:
        return "STRUGGLING"
    if quiz_score >= 0.8 and error_rate <= 0.2 and hints_used <= 2:
        return "STRONG"
    return "OK"


# ── Engagement ─────────────────────────────────────────────────────────────────

def classify_engagement(
    time_spent_sec: float,
    expected_time_sec: float,
    wrong_attempts: int,
    hints_used: int,
) -> str:
    """
    Classify a student's engagement level using signals that are actually captured.

    Rules (evaluated in order):
      BORED       — completing cards very quickly with no errors (rushing, not engaging)
                    time_spent < 35% of expected AND wrong_attempts == 0
      OVERWHELMED — needs many hints (concept is genuinely too difficult)
                    hints_used >= 5
      ENGAGED     — everything else

    Returns one of: "BORED", "ENGAGED", "OVERWHELMED"
    """
    if expected_time_sec > 0 and time_spent_sec < expected_time_sec * 0.35 and wrong_attempts == 0:
        return "BORED"
    if hints_used >= 5:
        return "OVERWHELMED"
    return "ENGAGED"


# ── Confidence score ───────────────────────────────────────────────────────────

def compute_confidence_score(
    quiz_score: float,
    wrong_attempts: int,
    attempts: int,
    hints_used: int,
) -> float:
    """
    Compute a composite confidence score in [0.0, 1.0].

    Formula (from config weights):
      error_rate    = wrong_attempts / attempts
      error_penalty = error_rate    * ADAPTIVE_ERROR_PENALTY_WEIGHT   (default 0.40)
      hint_penalty  = (min(hints_used, 10) / 10) * ADAPTIVE_HINT_PENALTY_WEIGHT  (default 0.20)
      raw           = quiz_score - error_penalty - hint_penalty
      result        = clamp(raw, 0.0, 1.0)

    quiz_score dominates; excessive errors and hint usage subtract from confidence.
    """
    error_rate = wrong_attempts / attempts if attempts > 0 else 0.0
    error_penalty = error_rate * ADAPTIVE_ERROR_PENALTY_WEIGHT
    hint_penalty = (min(hints_used, 10) / 10.0) * ADAPTIVE_HINT_PENALTY_WEIGHT
    raw = quiz_score - error_penalty - hint_penalty
    return max(0.0, min(1.0, raw))


# ── Recommended next step ──────────────────────────────────────────────────────

def classify_next_step(comprehension: str, speed: str, has_unmet_prereq: bool) -> str:
    """
    Recommend the next pedagogical action for the student.

    Rules (evaluated in order — highest priority first):
      REMEDIATE_PREREQ — STRUGGLING  AND  has_unmet_prereq
      ADD_PRACTICE     — STRUGGLING  (but all prereqs mastered)
      CHALLENGE        — FAST  AND  STRONG
      CONTINUE         — everything else

    Returns one of: "CONTINUE", "REMEDIATE_PREREQ", "ADD_PRACTICE", "CHALLENGE"
    """
    if comprehension == "STRUGGLING" and has_unmet_prereq:
        return "REMEDIATE_PREREQ"
    if comprehension == "STRUGGLING":
        return "ADD_PRACTICE"
    if speed == "FAST" and comprehension == "STRONG":
        return "CHALLENGE"
    return "CONTINUE"


# ── Orchestrator ───────────────────────────────────────────────────────────────

def build_learning_profile(
    analytics: AnalyticsSummary,
    has_unmet_prereq: bool,
) -> LearningProfile:
    """
    Orchestrate all classification functions and return a fully populated
    LearningProfile.

    Args:
        analytics:         Raw behavioral signals from the client.
        has_unmet_prereq:  True if the concept has at least one direct
                           prerequisite that the student has not yet mastered.
                           Pre-computed by the caller (adaptive_engine) to
                           keep this function pure.

    Returns:
        LearningProfile with speed, comprehension, engagement, confidence_score,
        recommended_next_step, and error_rate fields populated.
    """
    error_rate = (
        analytics.wrong_attempts / analytics.attempts
        if analytics.attempts > 0
        else 0.0
    )

    speed = classify_speed(
        analytics.time_spent_sec,
        analytics.expected_time_sec,
        analytics.attempts,
    )
    comprehension = classify_comprehension(
        analytics.wrong_attempts,
        analytics.attempts,
        analytics.quiz_score,
        analytics.hints_used,
    )
    engagement = classify_engagement(
        analytics.time_spent_sec,
        analytics.expected_time_sec,
        analytics.wrong_attempts,
        analytics.hints_used,
    )
    confidence = compute_confidence_score(
        analytics.quiz_score,
        analytics.wrong_attempts,
        analytics.attempts,
        analytics.hints_used,
    )
    next_step = classify_next_step(comprehension, speed, has_unmet_prereq)

    profile = LearningProfile(
        speed=speed,
        comprehension=comprehension,
        engagement=engagement,
        confidence_score=confidence,
        recommended_next_step=next_step,
        error_rate=round(error_rate, 4),
    )
    logger.debug(
        "LearningProfile built: speed=%s comprehension=%s engagement=%s "
        "confidence=%.2f next_step=%s error_rate=%.2f",
        profile.speed,
        profile.comprehension,
        profile.engagement,
        profile.confidence_score,
        profile.recommended_next_step,
        profile.error_rate,
    )
    return profile
