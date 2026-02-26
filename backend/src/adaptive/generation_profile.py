"""
Maps LearningProfile → GenerationProfile.

Uses a complete lookup table of all 9 (speed × comprehension) base configurations,
then applies engagement post-processing modifiers.  Both steps are pure functions
— no I/O, no side effects.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adaptive.schemas import LearningProfile, GenerationProfile


# ── Base profile lookup table (Speed × Comprehension) ────────────────────────
#
# Key: (speed, comprehension)
# Values mirror the DLD §4.1 mapping table exactly.
#
# Note on emoji_policy: the DLD table lists SPARING for SLOW×STRUGGLING and
# NORMAL×STRUGGLING; the engagement modifier can promote NONE → SPARING for
# BORED students regardless of base config.

_BASE_PROFILES: dict[tuple[str, str], dict] = {
    # ── SLOW ──────────────────────────────────────────────────────────
    ("SLOW", "STRUGGLING"): {
        "explanation_depth": "HIGH",
        "reading_level": "KID_SIMPLE",
        "step_by_step": True,
        "analogy_level": 0.8,
        "fun_level": 0.4,
        "card_count": 12,
        "practice_count": 7,
        "checkpoint_frequency": 2,
        "max_paragraph_lines": 2,
        "emoji_policy": "SPARING",
    },
    ("SLOW", "OK"): {
        "explanation_depth": "HIGH",
        "reading_level": "SIMPLE",
        "step_by_step": True,
        "analogy_level": 0.6,
        "fun_level": 0.3,
        "card_count": 11,
        "practice_count": 6,
        "checkpoint_frequency": 2,
        "max_paragraph_lines": 3,
        "emoji_policy": "NONE",
    },
    ("SLOW", "STRONG"): {
        "explanation_depth": "MEDIUM",
        "reading_level": "SIMPLE",
        "step_by_step": True,
        "analogy_level": 0.5,
        "fun_level": 0.3,
        "card_count": 10,
        "practice_count": 5,
        "checkpoint_frequency": 3,
        "max_paragraph_lines": 3,
        "emoji_policy": "NONE",
    },
    # ── NORMAL ────────────────────────────────────────────────────────
    ("NORMAL", "STRUGGLING"): {
        "explanation_depth": "HIGH",
        "reading_level": "SIMPLE",
        "step_by_step": True,
        "analogy_level": 0.7,
        "fun_level": 0.3,
        "card_count": 11,
        "practice_count": 6,
        "checkpoint_frequency": 2,
        "max_paragraph_lines": 3,
        "emoji_policy": "SPARING",
    },
    ("NORMAL", "OK"): {
        "explanation_depth": "MEDIUM",
        "reading_level": "STANDARD",
        "step_by_step": False,
        "analogy_level": 0.5,
        "fun_level": 0.2,
        "card_count": 9,
        "practice_count": 4,
        "checkpoint_frequency": 3,
        "max_paragraph_lines": 4,
        "emoji_policy": "NONE",
    },
    ("NORMAL", "STRONG"): {
        "explanation_depth": "LOW",
        "reading_level": "STANDARD",
        "step_by_step": False,
        "analogy_level": 0.3,
        "fun_level": 0.2,
        "card_count": 8,
        "practice_count": 3,
        "checkpoint_frequency": 4,
        "max_paragraph_lines": 4,
        "emoji_policy": "NONE",
    },
    # ── FAST ──────────────────────────────────────────────────────────
    ("FAST", "STRUGGLING"): {
        "explanation_depth": "HIGH",
        "reading_level": "SIMPLE",
        "step_by_step": True,
        "analogy_level": 0.6,
        "fun_level": 0.3,
        "card_count": 10,
        "practice_count": 6,
        "checkpoint_frequency": 2,
        "max_paragraph_lines": 3,
        "emoji_policy": "NONE",
    },
    ("FAST", "OK"): {
        "explanation_depth": "LOW",
        "reading_level": "STANDARD",
        "step_by_step": False,
        "analogy_level": 0.3,
        "fun_level": 0.2,
        "card_count": 8,
        "practice_count": 3,
        "checkpoint_frequency": 4,
        "max_paragraph_lines": 5,
        "emoji_policy": "NONE",
    },
    ("FAST", "STRONG"): {
        "explanation_depth": "LOW",
        "reading_level": "STANDARD",
        "step_by_step": False,
        "analogy_level": 0.2,
        "fun_level": 0.2,
        "card_count": 7,
        "practice_count": 3,
        "checkpoint_frequency": 5,
        "max_paragraph_lines": 5,
        "emoji_policy": "NONE",
    },
}


def build_generation_profile(profile: LearningProfile) -> GenerationProfile:
    """
    Derive all LLM generation parameters from a LearningProfile.

    Steps:
      1. Look up the base configuration by (speed, comprehension) key.
      2. Apply engagement post-processing modifiers (additive/overriding).
      3. Construct and return a validated GenerationProfile.

    Engagement modifiers (DLD §4.2):
      BORED       — fun_level += 0.3 (cap 1.0); emoji_policy = SPARING;
                    card_count -= 1 (floor 7)
      OVERWHELMED — card_count -= 3 (floor 7); practice_count -= 1 (floor 3);
                    step_by_step = True; analogy_level += 0.2 (cap 1.0)
      ENGAGED     — no modification

    Pure function — no I/O, no side effects.
    """
    # Step 1: Base config (copy so we do not mutate the lookup table)
    base = dict(_BASE_PROFILES[(profile.speed, profile.comprehension)])

    # Step 2: Engagement modifier
    if profile.engagement == "BORED":
        base["fun_level"] = min(1.0, base["fun_level"] + 0.3)
        base["emoji_policy"] = "SPARING"
        base["card_count"] = max(7, base["card_count"] - 1)

    elif profile.engagement == "OVERWHELMED":
        base["card_count"] = max(7, base["card_count"] - 3)
        base["practice_count"] = max(3, base["practice_count"] - 1)
        base["step_by_step"] = True
        base["analogy_level"] = min(1.0, base["analogy_level"] + 0.2)

    # Step 3: Construct validated model
    return GenerationProfile(**base)
