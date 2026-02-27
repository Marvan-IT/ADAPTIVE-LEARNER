"""
Builds (system_prompt, user_prompt) for the adaptive lesson LLM call.

Both functions are pure (no I/O, no side effects).  They are kept separate
from api/prompts.py to avoid coupling the adaptive module to the teaching
module's prompt conventions.

Key design decisions:
  - The JSON schema for AdaptiveLessonContent is embedded verbatim in the
    system prompt so the LLM has zero ambiguity about output structure.
  - All GenerationProfile fields are translated into human-readable rules in a
    dedicated GENERATION CONTROLS section.
  - Mode-specific behavioural blocks are appended conditionally (SLOW LEARNER,
    FAST/STRONG LEARNER, BORED LEARNER).
  - concept_text is hard-truncated at 3000 chars to prevent prompt injection
    via database content and to stay within a predictable token budget.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adaptive.schemas import GenerationProfile, LearningProfile

# ── Language name map ─────────────────────────────────────────────────────────
# Maintained locally to avoid cross-module coupling with api/prompts.py.
_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "ta": "Tamil",
    "si": "Sinhala",
    "ml": "Malayalam",
    "ar": "Arabic",
    "hi": "Hindi",
    "fr": "French",
    "es": "Spanish",
    "zh": "Chinese (Simplified)",
    "ja": "Japanese",
    "de": "German",
    "ko": "Korean",
    "pt": "Portuguese",
}

# Max chars of concept source text injected into the user prompt.
_CONCEPT_TEXT_LIMIT = 3000
_LATEX_LIMIT = 10


# ── JSON schema block (embedded in system prompt) ─────────────────────────────
# Written as a plain string so the LLM sees the exact expected output structure.

_LESSON_JSON_SCHEMA = """\
{
  "concept_explanation": "<markdown string — overview of the concept>",
  "cards": [
    {
      "type": "<one of: explain | example | mcq | short_answer | practice | checkpoint>",
      "title": "<concise card title string>",
      "content": "<markdown-formatted card body>",
      "answer": "<correct answer string, or null>",
      "hints": ["<hint string>", "..."],
      "difficulty": <integer 1-5>,
      "fun_element": "<optional fun hook string, or null>"
    }
  ]
}"""

_NEXT_CARD_JSON_SCHEMA = """\
{
  "title": "<concise card title>",
  "content": "<markdown-formatted explanation — maximum 6 lines>",
  "motivational_note": "<one warm encouraging sentence based on student progress, or null>",
  "questions": [
    {
      "type": "mcq",
      "question": "<question text>",
      "options": ["<A>", "<B>", "<C>", "<D>"],
      "correct_index": 0,
      "explanation": "<why the correct option is right>"
    },
    {
      "type": "true_false",
      "question": "<true/false statement>",
      "correct_answer": "true",
      "explanation": "<brief explanation>"
    }
  ]
}"""


def build_adaptive_prompt(
    concept_detail: dict,
    learning_profile: LearningProfile,
    gen_profile: GenerationProfile,
    prereq_detail: dict | None,
    language: str = "en",
) -> tuple[str, str]:
    """
    Build the (system_prompt, user_prompt) pair for the adaptive lesson LLM call.

    Args:
        concept_detail:  Dict returned by KnowledgeService.get_concept_detail().
                         Expected keys: concept_title, chapter, section, text, latex.
        learning_profile: Classified student profile.
        gen_profile:     Derived generation control parameters.
        prereq_detail:   If not None, the dict for the prerequisite concept
                         (same shape as concept_detail).  Triggers the
                         prerequisite remediation block in the user prompt.
        language:        BCP-47 language code for output language (default "en").

    Returns:
        Tuple of (system_prompt, user_prompt) strings ready to pass to the LLM.
    """
    system_prompt = _build_system_prompt(learning_profile, gen_profile, language)
    user_prompt = _build_user_prompt(
        concept_detail, learning_profile, gen_profile, prereq_detail
    )
    return system_prompt, user_prompt


# ── System prompt ─────────────────────────────────────────────────────────────

def _build_system_prompt(
    learning_profile: LearningProfile,
    gen_profile: GenerationProfile,
    language: str,
) -> str:
    """
    Assemble the system prompt.

    Sections (in order):
      1. Identity + JSON-only mandate
      2. JSON schema (verbatim)
      3. GENERATION CONTROLS — all GenerationProfile fields as rules
      4. Difficulty ramp requirement
      5. Conditional mode-specific blocks
    """
    lang_name = _LANGUAGE_NAMES.get(language, language)

    # ── Section 1: Identity + output mandate ──────────────────────────────
    parts: list[str] = [
        "You are an expert adaptive math tutor for the ADA platform.\n"
        "Your response MUST be a single valid JSON object — nothing else.\n"
        "Do NOT wrap it in markdown code fences. Do NOT add any commentary, "
        "explanation, or text before or after the JSON object.",
    ]

    # ── Section 2: JSON schema ─────────────────────────────────────────────
    parts.append(
        "\n\nOUTPUT SCHEMA (your response must match this exactly):\n"
        + _LESSON_JSON_SCHEMA
    )

    # ── Section 3: Generation controls ────────────────────────────────────
    depth_desc = {
        "LOW": "concise — assume prior knowledge, skip sub-steps",
        "MEDIUM": "moderate — cover all key sub-steps without exhaustive detail",
        "HIGH": "thorough — explain every sub-step explicitly, use worked examples throughout",
    }[gen_profile.explanation_depth]

    reading_desc = {
        "KID_SIMPLE": "age-10 vocabulary, very short sentences, avoid jargon entirely",
        "SIMPLE": "middle-school level, define any technical terms when first used",
        "STANDARD": "high-school / undergraduate level, normal mathematical vocabulary",
    }[gen_profile.reading_level]

    emoji_desc = {
        "NONE": "no emojis anywhere in the output",
        "SPARING": "at most one emoji per card, placed only in the fun_element field",
    }[gen_profile.emoji_policy]

    parts.append(
        "\n\nGENERATION CONTROLS — follow every rule exactly:\n"
        f"- Explanation depth:     {gen_profile.explanation_depth} — {depth_desc}\n"
        f"- Reading level:         {gen_profile.reading_level} — {reading_desc}\n"
        f"- Step-by-step required: {'YES — present each step on its own line' if gen_profile.step_by_step else 'NO — prose is acceptable'}\n"
        f"- Analogy density:       {gen_profile.analogy_level:.1f} (0.0 = no analogies; 1.0 = analogy for every concept)\n"
        f"- Fun level:             {gen_profile.fun_level:.1f} (0.0 = purely academic; 1.0 = maximise real-world fun hooks)\n"
        f"- Total cards:           {gen_profile.card_count} — generate EXACTLY this many cards\n"
        f"- Practice cards:        {gen_profile.practice_count} — include EXACTLY this many cards of type 'practice'\n"
        f"- Checkpoint frequency:  every {gen_profile.checkpoint_frequency} cards insert one card of type 'checkpoint'\n"
        f"- Max paragraph lines:   {gen_profile.max_paragraph_lines} — no explanation paragraph may exceed this many lines\n"
        f"- Emoji policy:          {gen_profile.emoji_policy} — {emoji_desc}\n"
        f"- Output language:       {lang_name} — ALL lesson content (titles, explanations, hints, answers) must be in {lang_name}; "
        "keep mathematical notation ($...$) and proper nouns in their original form"
    )

    # ── Section 4: Difficulty ramp ─────────────────────────────────────────
    parts.append(
        "\n\nDIFFICULTY RAMP — mandatory:\n"
        "difficulty must increase gradually across the cards array.\n"
        "The first card must have difficulty=1.\n"
        "The last card must have difficulty=5.\n"
        "Space difficulty values evenly across the sequence — do not cluster "
        "high-difficulty cards at the end."
    )

    # ── Section 5: Mode-specific blocks ───────────────────────────────────
    if learning_profile.speed == "SLOW":
        parts.append(
            "\n\nSLOW LEARNER MODE — additional requirements:\n"
            "- The very first card MUST be an ultra-simple worked example with difficulty=1.\n"
            "- Include at least 2 cards of type 'explain' that each use a concrete real-world analogy.\n"
            "- Include at least 2 cards of type 'checkpoint' spread through the sequence.\n"
            "- Prefer shorter card content; split complex ideas across multiple cards."
        )

    if learning_profile.speed == "FAST" and learning_profile.comprehension == "STRONG":
        parts.append(
            "\n\nFAST/STRONG LEARNER MODE — additional requirements:\n"
            "- Include at least 2 'practice' cards with difficulty >= 4.\n"
            "- Each of those challenge cards must have a non-null fun_element "
            "(e.g., a real-world puzzle, competitive challenge, or creative twist).\n"
            "- Skip introductory analogies; assume the student grasps concepts quickly.\n"
            "- Introduce edge cases and extensions where appropriate."
        )

    if learning_profile.engagement == "BORED":
        parts.append(
            "\n\nBORED LEARNER MODE — additional requirements:\n"
            "- At least 2 cards must have a non-null fun_element "
            "(game mechanic, puzzle hook, story scenario, or real-world challenge).\n"
            "- No two consecutive cards may be the same type "
            "(e.g., do not place two 'explain' cards back-to-back).\n"
            "- Open the concept_explanation with an attention-grabbing hook or surprising fact."
        )

    return "\n".join(parts)


# ── User prompt ───────────────────────────────────────────────────────────────

def _build_user_prompt(
    concept_detail: dict,
    learning_profile: LearningProfile,
    gen_profile: GenerationProfile,
    prereq_detail: dict | None,
) -> str:
    """
    Assemble the user prompt.

    Sections (in order):
      1. CONCEPT TO TEACH — title, chapter, section, truncated source text, LaTeX
      2. PREREQUISITE REMEDIATION — only present when prereq_detail is not None
      3. STUDENT PROFILE — classification values for LLM awareness
      4. Final instruction line
    """
    title = concept_detail.get("concept_title", "Unknown Concept")
    chapter = concept_detail.get("chapter", "")
    section = concept_detail.get("section", "")
    raw_text = concept_detail.get("text", "")
    latex_list: list[str] = concept_detail.get("latex", []) or []

    # Hard-truncate source text to prevent prompt injection and token overspend
    truncated_text = raw_text[:_CONCEPT_TEXT_LIMIT]
    if len(raw_text) > _CONCEPT_TEXT_LIMIT:
        truncated_text += "\n[... source text truncated ...]"

    # Limit LaTeX expressions
    latex_subset = latex_list[:_LATEX_LIMIT]
    latex_block = (
        "\n".join(f"  {expr}" for expr in latex_subset)
        if latex_subset
        else "  (none)"
    )

    parts: list[str] = [
        "CONCEPT TO TEACH:",
        f"  Title:   {title}",
        f"  Chapter: {chapter}",
        f"  Section: {section}",
        "",
        "Source material (use as the factual basis for your explanation and cards):",
        truncated_text,
        "",
        f"LaTeX expressions found in this concept (first {_LATEX_LIMIT}):",
        latex_block,
    ]

    # ── Prerequisite remediation block ────────────────────────────────────
    if prereq_detail is not None:
        prereq_title = prereq_detail.get("concept_title", "the prerequisite concept")
        remaining_cards = gen_profile.card_count - 3
        parts += [
            "",
            "PREREQUISITE REMEDIATION:",
            f"  The student has not yet fully mastered the prerequisite concept: \"{prereq_title}\".",
            f"  Prepend exactly 3 [Review]-prefixed cards at the START of the cards array.",
            "  These review cards must:",
            "    - Be of type 'explain' or 'example'",
            "    - Have difficulty 1 or 2",
            "    - Have titles starting with '[Review]'",
            "    - Gently reinforce the foundational idea before building to the main concept",
            f"  The remaining {remaining_cards} cards should then teach the main concept.",
        ]

    # ── Student profile block ──────────────────────────────────────────────
    parts += [
        "",
        "STUDENT PROFILE:",
        f"  Speed:               {learning_profile.speed}",
        f"  Comprehension:       {learning_profile.comprehension}",
        f"  Engagement:          {learning_profile.engagement}",
        f"  Confidence score:    {learning_profile.confidence_score:.2f}",
        f"  Recommended action:  {learning_profile.recommended_next_step}",
    ]

    # ── Final instruction ──────────────────────────────────────────────────
    parts += [
        "",
        "Return ONLY the JSON object. No explanation, no markdown fences, no commentary.",
    ]

    return "\n".join(parts)


def build_next_card_prompt(
    concept_detail: dict,
    learning_profile: LearningProfile,
    gen_profile: GenerationProfile,
    card_index: int,
    history: dict,
    language: str = "en",
) -> tuple[str, str]:
    """
    Build (system_prompt, user_prompt) for a single adaptive next-card LLM call.
    Reuses _build_system_prompt() unchanged, then overrides schema + card count.
    Adds STUDENT CONTEXT block with historical signals and motivational note rules.
    """
    import math

    # Reuse existing system prompt, then override schema and card rules
    base_sys = _build_system_prompt(learning_profile, gen_profile, language)

    # Replace the lesson JSON schema section with single-card schema
    sys_overrides = (
        "\n\nOVERRIDE — You are generating ONE card, not a full lesson.\n"
        "OUTPUT SCHEMA for this single card (your response must match exactly):\n"
        + _NEXT_CARD_JSON_SCHEMA
        + "\n\nGenerate EXACTLY 1 card (the JSON object above — NOT wrapped in an array).\n"
        "Do NOT include a 'concept_explanation' key.\n"
        f"Set difficulty = {max(1, min(5, 1 + math.ceil(4 * card_index / max(card_index + 3, 4))))}"
    )
    system_prompt = base_sys + sys_overrides

    # User prompt: concept info
    title = concept_detail.get("concept_title", "Unknown Concept")
    chapter = concept_detail.get("chapter", "")
    section = concept_detail.get("section", "")
    raw_text = concept_detail.get("text", "")
    truncated_text = raw_text[:_CONCEPT_TEXT_LIMIT]
    if len(raw_text) > _CONCEPT_TEXT_LIMIT:
        truncated_text += "\n[... source text truncated ...]"

    is_weak = history.get("is_known_weak_concept", False)
    failed_n = history.get("failed_concept_attempts", 0)
    trend = history.get("trend_direction", "STABLE")
    trend_list = history.get("trend_wrong_list", [])
    lang_name = _LANGUAGE_NAMES.get(language, language)

    parts = [
        "CONCEPT TO TEACH:",
        f"  Title:   {title}",
        f"  Chapter: {chapter}",
        f"  Section: {section}",
        "",
        "Source material:",
        truncated_text,
        "",
        "STUDENT PROFILE:",
        f"  Speed:               {learning_profile.speed}",
        f"  Comprehension:       {learning_profile.comprehension}",
        f"  Engagement:          {learning_profile.engagement}",
        f"  Confidence score:    {learning_profile.confidence_score:.2f}",
        "",
        "STUDENT CONTEXT:",
        f"  Cards completed historically:  {history.get('total_cards_completed', 0)}",
        f"  Sessions this week:            {history.get('sessions_last_7d', 0)}",
        f"  Concepts mastered:             {history.get('mastered_count', 0)}",
        f"  Performance trend (last 5 wrong_attempts): {trend_list}",
        f"  Trend direction:               {trend}",
        (
            f"  Known weak concept:            YES \u2014 student has attempted this concept "
            f"{failed_n} times without mastering. Be extra patient and encouraging."
            if is_weak
            else "  Known weak concept:            No"
        ),
        "",
        "MOTIVATIONAL NOTE RULES:",
        "  - If trend_direction is IMPROVING: celebrate the improvement warmly",
        "  - If is_known_weak_concept is YES: acknowledge persistence, be extra encouraging",
        "  - If student is FAST+STRONG: challenge them with 'Let\u2019s push further!'",
        f"  - Keep it to ONE natural teacher-voice sentence in {lang_name}",
        "  - Set motivational_note to null if no meaningful context exists yet",
        "",
        "Return ONLY the JSON object. No markdown fences, no commentary.",
    ]

    return system_prompt, "\n".join(parts)
