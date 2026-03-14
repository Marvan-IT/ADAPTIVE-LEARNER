"""
Boredom and engagement signal detection for the adaptive flashcard system.

Detects when a student is disengaged (short responses, explicit boredom phrases,
autopilot pattern) and selects an engagement strategy based on effectiveness history.
"""
from __future__ import annotations

SHORT_RESPONSE_THRESHOLD = 15

BOREDOM_EXPLICIT_PHRASES: frozenset[str] = frozenset([
    "ok", "okay", "sure", "k", "next", "boring", "bored",
    "i know", "i know this", "i already know", "easy",
    "yep", "yup", "yeah", "fine", "whatever", "skip",
    "got it", "understood", "ugh", "meh",
])

ALL_STRATEGIES = ["challenge_bump", "real_world_hook", "context_switch", "micro_break"]


def detect_boredom_signal(message: str) -> str | None:
    """Detect boredom or disengagement signal from a student message.

    Returns:
        'boredom_explicit'  — message matches a known boredom phrase
        'short_response'    — message is under SHORT_RESPONSE_THRESHOLD chars (after strip)
        None                — no signal detected
    """
    stripped = message.strip()
    lower = stripped.lower()

    if lower in BOREDOM_EXPLICIT_PHRASES:
        return "boredom_explicit"

    if len(stripped) < SHORT_RESPONSE_THRESHOLD:
        return "short_response"

    return None


def detect_autopilot_pattern(recent_messages: list[str]) -> bool:
    """Return True if the student appears to be on autopilot.

    Criteria: 3 or more of the last 5 student messages are under
    SHORT_RESPONSE_THRESHOLD characters.
    """
    last_five = recent_messages[-5:] if len(recent_messages) >= 5 else recent_messages
    short_count = sum(1 for m in last_five if len(m.strip()) < SHORT_RESPONSE_THRESHOLD)
    return short_count >= 3


def select_engagement_strategy(
    effective_engagement: list[str],
    ineffective_engagement: list[str],
    engagement_signal: str | None = None,
    engagement: str | None = None,
) -> str:
    """Select the best engagement strategy based on effectiveness history.

    Priority order:
    1. Guard: OVERWHELMED students always receive 'micro_break' — never challenge_bump.
    2. Strategies that have worked before (in effective_engagement)
    3. Strategies not yet tried (not in either list)
    4. Strategies that have not worked (in ineffective_engagement) — last resort

    Within each tier, strategies are selected in ALL_STRATEGIES order for
    deterministic behavior.

    Args:
        effective_engagement: Strategies known to have worked for this student.
        ineffective_engagement: Strategies known NOT to have worked for this student.
        engagement_signal: Optional signal from the frontend (e.g. 'boredom_explicit').
        engagement: Current engagement classification from LearningProfile
                    ('BORED', 'ENGAGED', 'OVERWHELMED'). OVERWHELMED always → 'micro_break'.

    Returns one of: 'challenge_bump', 'real_world_hook', 'context_switch', 'micro_break'
    """
    # Guard: OVERWHELMED students must never receive challenge_bump
    if engagement == "OVERWHELMED":
        return "micro_break"

    effective_set = set(effective_engagement or [])
    ineffective_set = set(ineffective_engagement or [])

    # Tier 1: known effective
    for strategy in ALL_STRATEGIES:
        if strategy in effective_set:
            return strategy

    # Tier 2: untested
    for strategy in ALL_STRATEGIES:
        if strategy not in effective_set and strategy not in ineffective_set:
            return strategy

    # Tier 3: last resort — least recently failed
    for strategy in ALL_STRATEGIES:
        if strategy in ineffective_set:
            return strategy

    # Fallback (should never reach here)
    return "challenge_bump"
