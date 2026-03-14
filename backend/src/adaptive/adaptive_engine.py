"""
Adaptive Learning Generation Engine — main async orchestrator.

Pipeline:
  a) Fetch concept detail from KnowledgeService (RAG + graph)
  b) Determine remediation prerequisite from graph (one-hop)
  c) Build LearningProfile (deterministic, pure)
  d) Build GenerationProfile (deterministic, pure)
  e) Fetch prerequisite detail if remediation is triggered
  f) Build template-based remediation cards (no LLM)
  g) Build LLM prompts (pure)
  h) Call LLM with 3-retry exponential back-off
  i) Parse + Pydantic-validate JSON response
  j) Prepend remediation cards; return AdaptiveLesson
"""
import asyncio
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from json_repair import repair_json   # for robust JSON parsing of LLM output
except ImportError:
    def repair_json(s: str) -> str:  # type: ignore[misc]
        return s

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import AsyncOpenAI
from pydantic import ValidationError

from adaptive.schemas import (
    AnalyticsSummary,
    AdaptiveLessonCard,
    AdaptiveLessonContent,
    AdaptiveLesson,
    RemediationInfo,
)
from adaptive.profile_builder import build_learning_profile
from adaptive.generation_profile import build_generation_profile
from adaptive.remediation import find_remediation_prereq, build_remediation_cards
from adaptive.prompt_builder import build_adaptive_prompt
from config import (
    OPENAI_MODEL,
    ADAPTIVE_MIN_HISTORY_CARDS,
    ADAPTIVE_ACUTE_HIGH_TIME_RATIO,
    ADAPTIVE_ACUTE_LOW_TIME_RATIO,
    ADAPTIVE_ACUTE_WRONG_RATIO,
    ADAPTIVE_ACUTE_CURRENT_WEIGHT,
    ADAPTIVE_ACUTE_HISTORY_WEIGHT,
    ADAPTIVE_NORMAL_CURRENT_WEIGHT,
    ADAPTIVE_NORMAL_HISTORY_WEIGHT,
    ADAPTIVE_CARD_MODEL,
    WRONG_OPTION_PATTERN_THRESHOLD,
    ADAPTIVE_COLD_START_CURRENT_WEIGHT,
    ADAPTIVE_COLD_START_HISTORY_WEIGHT,
    ADAPTIVE_WARM_START_CURRENT_WEIGHT,
    ADAPTIVE_WARM_START_HISTORY_WEIGHT,
    ADAPTIVE_PARTIAL_CURRENT_WEIGHT,
    ADAPTIVE_PARTIAL_HISTORY_WEIGHT,
    ADAPTIVE_STATE_BLEND_CURRENT_WEIGHT,
    ADAPTIVE_STATE_BLEND_HISTORY_WEIGHT,
)

logger = logging.getLogger(__name__)


# ── JSON helpers ──────────────────────────────────────────────────────────────

def _extract_json_block(raw: str) -> str:
    """Strip markdown code fences if the LLM wrapped its output in them."""
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    return m.group(1).strip() if m else raw.strip()


def _salvage_truncated_json(raw: str) -> str:
    """
    Attempt to close unclosed JSON brackets and braces caused by a truncated
    LLM response.  Closes inner arrays first, then outer objects.
    """
    raw = raw.rstrip()
    opens = raw.count("{") - raw.count("}")
    arr_opens = raw.count("[") - raw.count("]")
    raw += "]" * max(0, arr_opens)
    raw += "}" * max(0, opens)
    return raw


# ── LLM client helper ─────────────────────────────────────────────────────────

async def _call_llm(
    llm_client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    max_tokens: int = 8000,
    temperature: float = 0.7,
) -> str:
    """
    Call OpenAI with up to 3 attempts and exponential back-off (2 s, 4 s).

    Returns the raw string content on success.
    Raises ValueError after all retries are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = await llm_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content or ""
            if content.strip():
                return content
            logger.warning(
                "LLM returned empty content (attempt %d/3)", attempt
            )
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "adaptive_llm_retry: attempt=%d error=%s",
                attempt,
                exc,
            )
        if attempt < 3:
            await asyncio.sleep(2 * attempt)

    logger.error("adaptive_llm_failed: last_error=%s", last_exc)
    raise ValueError(f"LLM failed after 3 attempts. Last error: {last_exc}")


# ── Main orchestrator ─────────────────────────────────────────────────────────

async def generate_adaptive_lesson(
    student_id: str,
    concept_id: str,
    analytics_summary: AnalyticsSummary,
    knowledge_svc,                    # KnowledgeService — typed as Any to avoid circular import
    mastery_store: dict[str, bool],   # concept_id → True for every mastered concept
    llm_client: AsyncOpenAI,
    model: str = OPENAI_MODEL,
    language: str = "en",
) -> AdaptiveLesson:
    """
    Generate a fully adaptive lesson for a student.

    Args:
        student_id:        UUID string of the student.
        concept_id:        The concept to teach.
        analytics_summary: Behavioral signals from the client.
        knowledge_svc:     KnowledgeService; provides get_concept_detail() and .graph.
        mastery_store:     Pre-built mastery dict (caller's responsibility to query DB).
        llm_client:        Initialised AsyncOpenAI client.
        model:             OpenAI model identifier (defaults to OPENAI_MODEL from config).
        language:          BCP-47 language code for output (defaults to "en").

    Returns:
        A validated AdaptiveLesson instance.

    Raises:
        ValueError: If the concept is not found, or if the LLM fails after all retries.
    """
    start_ts = time.monotonic()

    # ── a) Fetch concept ───────────────────────────────────────────────────
    logger.info("Fetching concept detail: concept_id=%s", concept_id)
    concept_detail = knowledge_svc.get_concept_detail(concept_id)
    if concept_detail is None:
        raise ValueError(f"Concept not found in knowledge base: {concept_id}")

    # ── b) Determine remediation prerequisite (one-hop graph traversal) ───
    prereq_id = find_remediation_prereq(concept_id, knowledge_svc, mastery_store)
    logger.info(
        "Remediation prereq for concept_id=%s: %s",
        concept_id,
        prereq_id if prereq_id else "none",
    )

    # ── c) Build LearningProfile ───────────────────────────────────────────
    learning_profile = build_learning_profile(
        analytics_summary, has_unmet_prereq=prereq_id is not None
    )
    logger.info(
        "LearningProfile: speed=%s comprehension=%s engagement=%s confidence=%.2f next=%s",
        learning_profile.speed,
        learning_profile.comprehension,
        learning_profile.engagement,
        learning_profile.confidence_score,
        learning_profile.recommended_next_step,
    )

    # ── d) Build GenerationProfile ─────────────────────────────────────────
    gen_profile = build_generation_profile(learning_profile)
    logger.info(
        "GenerationProfile: depth=%s cards=%d practice=%d",
        gen_profile.explanation_depth,
        gen_profile.card_count,
        gen_profile.practice_count,
    )

    # ── e) Fetch prerequisite detail if remediation is needed ─────────────
    prereq_detail: dict | None = None
    if prereq_id:
        prereq_detail = knowledge_svc.get_concept_detail(prereq_id)
        if prereq_detail is None:
            logger.warning(
                "Prereq concept %s not found in knowledge base; skipping remediation",
                prereq_id,
            )
            prereq_id = None  # Cancel remediation — we cannot build cards without the text

    # ── f) Build template-based remediation cards (no LLM) ────────────────
    remediation_cards: list[dict] = []
    if prereq_id and prereq_detail:
        remediation_cards = build_remediation_cards(prereq_id, prereq_detail)
        logger.info(
            "Built %d remediation cards for prereq=%s",
            len(remediation_cards),
            prereq_id,
        )

    # ── g) Build LLM prompts ───────────────────────────────────────────────
    system_prompt, user_prompt = build_adaptive_prompt(
        concept_detail=concept_detail,
        learning_profile=learning_profile,
        gen_profile=gen_profile,
        prereq_detail=prereq_detail,
        language=language,
    )

    # ── h) Call LLM ───────────────────────────────────────────────────────
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    logger.info(
        "Calling LLM: model=%s max_tokens=8000 concept_id=%s",
        model,
        concept_id,
    )
    raw = await _call_llm(llm_client, model, messages, max_tokens=8000)

    # ── i) Parse and validate JSON response ───────────────────────────────
    cleaned = _extract_json_block(raw)
    lesson_content: AdaptiveLessonContent | None = None

    for attempt_raw in (cleaned, _salvage_truncated_json(cleaned)):
        try:
            parsed = json.loads(attempt_raw)
            lesson_content = AdaptiveLessonContent.model_validate(parsed)
            break
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("JSON parse/validate failed: %s", exc)

    if lesson_content is None:
        raise ValueError(
            "LLM output could not be parsed as AdaptiveLessonContent. "
            f"Raw output (first 500 chars): {raw[:500]}"
        )

    if len(lesson_content.cards) < gen_profile.practice_count:
        logger.warning(
            "LLM returned %d cards but practice_count=%d was requested",
            len(lesson_content.cards),
            gen_profile.practice_count,
        )

    # ── j) Prepend remediation cards ──────────────────────────────────────
    all_cards: list[AdaptiveLessonCard] = []

    # Validate template-built remediation card dicts through the Pydantic model
    for card_dict in remediation_cards:
        try:
            all_cards.append(AdaptiveLessonCard.model_validate(card_dict))
        except ValidationError as exc:
            logger.warning("Remediation card validation failed (skipped): %s", exc)

    all_cards.extend(lesson_content.cards)

    duration_ms = round((time.monotonic() - start_ts) * 1000)
    logger.info(
        "adaptive_lesson_generated: student_id=%s concept_id=%s speed=%s "
        "comprehension=%s engagement=%s card_count=%d remediation=%s duration_ms=%d",
        student_id,
        concept_id,
        learning_profile.speed,
        learning_profile.comprehension,
        learning_profile.engagement,
        len(all_cards),
        prereq_id is not None,
        duration_ms,
    )

    prereq_title: str | None = None
    if prereq_id and prereq_detail:
        prereq_title = prereq_detail.get("concept_title")

    return AdaptiveLesson(
        student_id=student_id,
        concept_id=concept_id,
        learning_profile=learning_profile,
        generation_profile=gen_profile,
        lesson=AdaptiveLessonContent(
            concept_explanation=lesson_content.concept_explanation,
            cards=all_cards,
        ),
        remediation=RemediationInfo(
            included=prereq_id is not None,
            prereq_concept_id=prereq_id,
            prereq_title=prereq_title,
        ),
    )


# ── Next-card adaptive loop ────────────────────────────────────────────────────

async def load_student_history(student_id: str, concept_id: str, db) -> dict:
    """
    Load and aggregate a student's full interaction history from the DB.
    Returns a dict with personal baselines, performance trend, weak-concept flag,
    and extended adaptive history fields from the Student profile.
    """
    from datetime import timedelta
    from sqlalchemy import select, func
    from db.models import CardInteraction, TeachingSession, StudentMastery, Student
    import uuid as _uuid

    sid = _uuid.UUID(student_id) if isinstance(student_id, str) else student_id

    # 1. Global aggregate baseline — capped at the 200 most recent interactions
    #    to prevent unbounded aggregation on high-volume students.
    recent_sq = (
        select(CardInteraction)
        .where(CardInteraction.student_id == sid)
        .order_by(CardInteraction.completed_at.desc())
        .limit(200)
        .subquery()
    )
    agg_result = await db.execute(
        select(
            func.avg(recent_sq.c.time_on_card_sec).label("avg_time"),
            func.avg(recent_sq.c.wrong_attempts).label("avg_wrong"),
            func.avg(recent_sq.c.hints_used).label("avg_hints"),
            func.count(recent_sq.c.id).label("total_cards"),
        )
    )
    agg = agg_result.one()

    if (agg.total_cards or 0) >= 200:
        logger.warning(
            "load_student_history: student_id=%s hit 200-record cap on card interactions",
            student_id,
        )

    # 2. Performance trend: last 5 cards
    trend_result = await db.execute(
        select(CardInteraction.wrong_attempts, CardInteraction.time_on_card_sec)
        .where(CardInteraction.student_id == sid)
        .order_by(CardInteraction.completed_at.desc())
        .limit(5)
    )
    recent = trend_result.all()
    trend_wrong_list = [r.wrong_attempts for r in recent]
    if len(trend_wrong_list) >= 3:
        first_half = trend_wrong_list[len(trend_wrong_list) // 2:]
        second_half = trend_wrong_list[:len(trend_wrong_list) // 2]
        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)
        if avg_second < avg_first - 0.3:
            trend_direction = "IMPROVING"
        elif avg_second > avg_first + 0.3:
            trend_direction = "WORSENING"
        else:
            trend_direction = "STABLE"
    else:
        trend_direction = "STABLE"

    # 3. Sessions last 7 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    sessions_7d_result = await db.execute(
        select(func.count(TeachingSession.id))
        .where(TeachingSession.student_id == sid)
        .where(TeachingSession.started_at >= cutoff)
    )
    sessions_7d = sessions_7d_result.scalar() or 0

    # 4. Total mastered count
    mastered_result = await db.execute(
        select(func.count(StudentMastery.id))
        .where(StudentMastery.student_id == sid)
    )
    mastered_count = mastered_result.scalar() or 0

    # 5. Known-weak-concept check
    weak_result = await db.execute(
        select(func.count(TeachingSession.id))
        .where(TeachingSession.student_id == sid)
        .where(TeachingSession.concept_id == concept_id)
        .where(TeachingSession.concept_mastered == False)  # noqa: E712
    )
    failed_attempts = weak_result.scalar() or 0

    # 6. Load extended adaptive history fields from the Student profile
    student_result = await db.execute(
        select(Student).where(Student.id == sid)
    )
    student_row = student_result.scalar_one_or_none()

    section_count = 0
    avg_state_score = 2.0
    effective_analogies: list = []
    preferred_analogy_style: str | None = None
    effective_engagement: list = []
    ineffective_engagement: list = []
    boredom_pattern: str | None = None
    state_distribution: dict = {"struggling": 0, "normal": 0, "fast": 0}
    overall_accuracy_rate = 0.5

    if student_row is not None:
        section_count = int(student_row.section_count or 0)
        avg_state_score = float(student_row.avg_state_score or 2.0)
        effective_analogies = list(student_row.effective_analogies or [])
        preferred_analogy_style = student_row.preferred_analogy_style
        effective_engagement = list(student_row.effective_engagement or [])
        ineffective_engagement = list(student_row.ineffective_engagement or [])
        boredom_pattern = student_row.boredom_pattern
        raw_dist = student_row.state_distribution
        if isinstance(raw_dist, dict):
            state_distribution = raw_dist
        overall_accuracy_rate = float(student_row.overall_accuracy_rate or 0.5)

    return {
        "avg_time_per_card": float(agg.avg_time) if agg.avg_time is not None else None,
        "avg_wrong_attempts": float(agg.avg_wrong) if agg.avg_wrong is not None else None,
        "avg_hints_per_card": float(agg.avg_hints) if agg.avg_hints is not None else None,
        "total_cards_completed": int(agg.total_cards) if agg.total_cards else 0,
        "sessions_last_7d": int(sessions_7d),
        "mastered_count": int(mastered_count),
        "is_known_weak_concept": failed_attempts >= 2,
        "failed_concept_attempts": int(failed_attempts),
        "trend_direction": trend_direction,
        "trend_wrong_list": trend_wrong_list,
        # Extended adaptive history fields from Student profile
        "section_count": section_count,
        "avg_state_score": avg_state_score,
        "effective_analogies": effective_analogies,
        "preferred_analogy_style": preferred_analogy_style,
        "effective_engagement": effective_engagement,
        "ineffective_engagement": ineffective_engagement,
        "boredom_pattern": boredom_pattern,
        "state_distribution": state_distribution,
        "overall_accuracy_rate": overall_accuracy_rate,
    }


async def load_wrong_option_pattern(
    student_id: str,
    concept_id: str,
    db,
) -> int | None:
    """
    Query the most persistently selected wrong option for a student on a concept.

    Returns the option index (0-based) if it has been selected >=
    WRONG_OPTION_PATTERN_THRESHOLD times, else None.

    Gracefully returns None on any DB error so that card generation can continue
    without pattern injection.
    """
    from sqlalchemy import select, func
    from db.models import CardInteraction
    import uuid as _uuid

    try:
        sid = _uuid.UUID(student_id) if isinstance(student_id, str) else student_id

        result = await db.execute(
            select(
                CardInteraction.selected_wrong_option,
                func.count(CardInteraction.id).label("freq"),
            )
            .where(CardInteraction.student_id == sid)
            .where(CardInteraction.concept_id == concept_id)
            .where(CardInteraction.selected_wrong_option.is_not(None))
            .group_by(CardInteraction.selected_wrong_option)
            .having(func.count(CardInteraction.id) >= WRONG_OPTION_PATTERN_THRESHOLD)
            .order_by(func.count(CardInteraction.id).desc())
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None

        pattern = row.selected_wrong_option
        logger.info(
            "wrong_option_pattern: student_id=%s concept_id=%s option=%s freq=%d",
            student_id, concept_id, pattern, row.freq,
        )
        return int(pattern)
    except Exception as exc:
        logger.warning("wrong_option_pattern_query_failed: error=%s (skipping)", exc)
        return None


def compute_numeric_state_score(speed: str, comprehension: str) -> float:
    """Map (speed, comprehension) classification to a numeric score [1.0, 3.0].

    Speed base values: SLOW=1.0, NORMAL=2.0, FAST=3.0
    Comprehension modifiers: STRUGGLING=-0.3, OK=0.0, STRONG=+0.3
    Result is clamped to [1.0, 3.0].
    """
    base = {"SLOW": 1.0, "NORMAL": 2.0, "FAST": 3.0}.get(speed.upper(), 2.0)
    modifier = {"STRUGGLING": -0.3, "OK": 0.0, "STRONG": 0.3}.get(comprehension.upper(), 0.0)
    return max(1.0, min(3.0, base + modifier))


def blended_score_to_generate_as(blended_score: float) -> str:
    """Convert a blended numeric state score to a generate_as label.

    < 1.5   -> 'STRUGGLING'
    1.5-2.4 -> 'NORMAL'
    >= 2.5  -> 'FAST'
    """
    if blended_score < 1.5:
        return "STRUGGLING"
    elif blended_score >= 2.5:
        return "FAST"
    return "NORMAL"


def build_blended_analytics(
    current: "CardBehaviorSignals",
    history: dict,
    concept_id: str,
    student_id: str,
) -> tuple["AnalyticsSummary", float, str]:
    """
    Blend current card signals with historical baseline using deviation detection.

    New student (< 5 cards): 100% current signals.
    Normal variance: 60% current / 40% history.
    Acute deviation (fever, distraction, or sudden recovery): 90% current / 10% history.

    Also blends the numeric state score using section_count-based cold-start weights.

    Returns a 3-tuple: (AnalyticsSummary, blended_score, generate_as)
      - blended_score: float in [1.0, 3.0]
      - generate_as: one of 'STRUGGLING', 'NORMAL', 'FAST'
    """
    MIN_HISTORY_CARDS = ADAPTIVE_MIN_HISTORY_CARDS
    has_history = history["total_cards_completed"] >= MIN_HISTORY_CARDS
    baseline_time = history["avg_time_per_card"] or 120.0
    baseline_wrong = history["avg_wrong_attempts"] or 0.0
    baseline_hints = history["avg_hints_per_card"] or 0.0

    if not has_history:
        cw, hw = 1.0, 0.0
    else:
        time_ratio = current.time_on_card_sec / max(baseline_time, 30.0)
        wrong_ratio = (current.wrong_attempts + 1) / max(baseline_wrong + 1, 1.0)
        is_acute = (
            time_ratio > ADAPTIVE_ACUTE_HIGH_TIME_RATIO
            or time_ratio < ADAPTIVE_ACUTE_LOW_TIME_RATIO
            or wrong_ratio > ADAPTIVE_ACUTE_WRONG_RATIO
        )
        cw, hw = (
            (ADAPTIVE_ACUTE_CURRENT_WEIGHT, ADAPTIVE_ACUTE_HISTORY_WEIGHT)
            if is_acute
            else (ADAPTIVE_NORMAL_CURRENT_WEIGHT, ADAPTIVE_NORMAL_HISTORY_WEIGHT)
        )

    blended_wrong = current.wrong_attempts * cw + baseline_wrong * hw
    blended_hints = current.hints_used * cw + baseline_hints * hw
    expected_time = baseline_time  # personal baseline

    analytics = AnalyticsSummary(
        student_id=student_id,
        concept_id=concept_id,
        time_spent_sec=current.time_on_card_sec,
        expected_time_sec=expected_time,
        attempts=max(1, round(blended_wrong) + 1),
        wrong_attempts=round(blended_wrong),
        hints_used=round(blended_hints),
        revisits=0,
        recent_dropoffs=current.idle_triggers,
        skip_rate=0.0,
        quiz_score=max(0.0, 1.0 - blended_wrong * 0.25),
        last_7d_sessions=history["sessions_last_7d"],
    )

    # ── Numeric state blending using section_count-based cold-start weights ──
    # Classify current session's speed/comprehension into a numeric score, then
    # blend with the student's historical avg_state_score.
    from adaptive.profile_builder import classify_speed, classify_comprehension
    current_speed = classify_speed(
        current.time_on_card_sec, expected_time, max(1, round(blended_wrong) + 1)
    )
    current_comprehension = classify_comprehension(
        round(blended_wrong),
        max(1, round(blended_wrong) + 1),
        max(0.0, 1.0 - blended_wrong * 0.25),
        round(blended_hints),
    )
    current_numeric_score = compute_numeric_state_score(current_speed, current_comprehension)
    history_avg_state = history.get("avg_state_score", 2.0)

    section_count = history.get("section_count", 0)
    if section_count == 0:
        w_current = ADAPTIVE_COLD_START_CURRENT_WEIGHT
        w_history = ADAPTIVE_COLD_START_HISTORY_WEIGHT
    elif section_count == 1:
        w_current = ADAPTIVE_WARM_START_CURRENT_WEIGHT
        w_history = ADAPTIVE_WARM_START_HISTORY_WEIGHT
    elif section_count == 2:
        w_current = ADAPTIVE_PARTIAL_CURRENT_WEIGHT
        w_history = ADAPTIVE_PARTIAL_HISTORY_WEIGHT
    else:
        w_current = ADAPTIVE_STATE_BLEND_CURRENT_WEIGHT
        w_history = ADAPTIVE_STATE_BLEND_HISTORY_WEIGHT

    blended_score = (current_numeric_score * w_current) + (history_avg_state * w_history)
    blended_score = max(1.0, min(3.0, blended_score))
    generate_as = blended_score_to_generate_as(blended_score)

    return analytics, blended_score, generate_as


async def generate_next_card(
    student_id: str,
    concept_id: str,
    signals: "CardBehaviorSignals",
    card_index: int,
    history: dict,
    knowledge_svc,
    mastery_store: dict[str, bool],
    llm_client: AsyncOpenAI,
    model: str,
    language: str = "en",
    db=None,  # Optional AsyncSession — required for wrong-option pattern detection
) -> tuple[dict, "LearningProfile", "GenerationProfile", str | None, str]:
    """
    Generate the next adaptive card using blended student analytics.

    Returns a 5-tuple:
        (card_dict, learning_profile, gen_profile, motivational_note, adaptation_label)

    adaptation_label is a human-readable string indicating the adaptation applied,
    including the difficulty bias if one was provided by the student.
    """
    from adaptive.prompt_builder import build_next_card_prompt

    analytics, blended_score, generate_as = build_blended_analytics(signals, history, concept_id, student_id)
    has_prereq = find_remediation_prereq(concept_id, knowledge_svc, mastery_store) is not None
    profile = build_learning_profile(analytics, has_unmet_prereq=has_prereq)
    gen_profile = build_generation_profile(profile)

    # ── Difficulty bias override ───────────────────────────────────────────────
    # The student explicitly indicated the content was too easy or too hard.
    # Override recommended_next_step so the prompt builder produces an
    # appropriately harder or simpler card without touching other profile fields.
    bias = getattr(signals, "difficulty_bias", None)
    if bias == "TOO_EASY":
        profile = profile.model_copy(update={"recommended_next_step": "CHALLENGE"})
        logger.info(
            "difficulty_bias_override: student_id=%s bias=TOO_EASY recommended=CHALLENGE",
            student_id,
        )
    elif bias == "TOO_HARD":
        profile = profile.model_copy(update={"recommended_next_step": "REMEDIATE_PREREQ"})
        logger.info(
            "difficulty_bias_override: student_id=%s bias=TOO_HARD recommended=REMEDIATE_PREREQ",
            student_id,
        )

    # ── Wrong-option pattern detection ────────────────────────────────────────
    wrong_option_pattern: int | None = None
    if db is not None:
        try:
            wrong_option_pattern = await load_wrong_option_pattern(
                student_id, concept_id, db
            )
        except Exception as exc:
            logger.warning(
                "wrong_option_pattern_query_failed: error=%s (skipping)", exc
            )

    concept_detail = knowledge_svc.get_concept_detail(concept_id)
    if concept_detail is None:
        raise ValueError(f"Concept not found: {concept_id}")

    # Determine engagement strategy, guarding against OVERWHELMED students getting challenge_bump
    from adaptive.boredom_detector import select_engagement_strategy, detect_boredom_signal
    _engagement_signal = getattr(signals, "engagement_signal", None)
    _strategy: str | None = None
    if _engagement_signal:
        _strategy = select_engagement_strategy(
            effective_engagement=history.get("effective_engagement", []),
            ineffective_engagement=history.get("ineffective_engagement", []),
            engagement_signal=_engagement_signal,
            engagement=profile.engagement,
        )

    sys_p, usr_p = build_next_card_prompt(
        concept_detail=concept_detail,
        learning_profile=profile,
        gen_profile=gen_profile,
        card_index=card_index,
        history=history,
        language=language,
        wrong_option_pattern=wrong_option_pattern,
        difficulty_bias=bias,
        generate_as=generate_as,
        blended_state_score=blended_score,
        engagement_strategy=_strategy,
    )

    messages = [
        {"role": "system", "content": sys_p},
        {"role": "user", "content": usr_p},
    ]
    raw = await _call_llm(llm_client, ADAPTIVE_CARD_MODEL, messages, max_tokens=2200)
    cleaned = _extract_json_block(raw)

    parsed: dict | None = None
    for attempt_raw in (cleaned, _salvage_truncated_json(cleaned)):
        try:
            parsed = json.loads(attempt_raw)
            break
        except json.JSONDecodeError:
            pass

    if parsed is None:
        raise ValueError(f"LLM output could not be parsed. Raw (first 300): {raw[:300]}")

    motivational_note = parsed.pop("motivational_note", None)

    # Normalise to frontend LessonCard shape
    card = {
        "index": card_index,
        "title": parsed.get("title", f"Card {card_index + 1}"),
        "content": parsed.get("content", ""),
        "images": [],
        "questions": parsed.get("questions", []),
        # Forward difficulty so the frontend can render the difficulty badge.
        # Prefer the LLM-returned value; fall back to 3 (mid-range default).
        "difficulty": int(parsed["difficulty"]) if parsed.get("difficulty") is not None else 3,
    }

    # Assign stable question IDs
    for i, q in enumerate(card["questions"]):
        q_type = q.get("type", "mcq")
        q["id"] = f"c{card_index}_{q_type}_{i}"

    # ── Adaptation label ───────────────────────────────────────────────────────
    base_label = profile.recommended_next_step
    adaptation_label = (
        f"{base_label} (student: {bias})" if bias else base_label
    )

    return card, profile, gen_profile, motivational_note, adaptation_label


# ── Recovery card generation ───────────────────────────────────────────────────

# Inline style modifiers — mirrors STYLE_MODIFIERS in api/prompts.py
# NOTE: kept decoupled intentionally (no api/ import in adaptive/).
# If styles added/changed in api/prompts.py, update this dict too.
_RECOVERY_STYLE_MODIFIERS: dict[str, str] = {
    "pirate":    "Use pirate language naturally: 'Ahoy!', 'matey', treasure=answer, ship=student.",
    "astronaut": "Frame as space mission: 'Mission Control', 'zero gravity', 'launch sequence'.",
    "gamer":     "Use gaming language: 'level up', 'XP gained', 'boss battle', 'respawn'.",
    "default":   "",
}

_RECOVERY_LANG_MAP: dict[str, str] = {
    "ta": "Tamil", "ar": "Arabic", "hi": "Hindi", "fr": "French",
    "es": "Spanish", "zh": "Chinese", "ja": "Japanese", "de": "German",
    "ko": "Korean", "pt": "Portuguese", "ml": "Malayalam", "si": "Sinhala",
}


async def generate_recovery_card(
    topic_title: str,
    concept_id: str,
    knowledge_svc,
    llm_client,
    language: str = "en",
    interests: list[str] | None = None,
    style: str = "default",
) -> dict | None:
    """
    Generate a recovery TEACH card re-explaining `topic_title` in STRUGGLING mode.
    Called when student gets wrong×2. Returns card dict or None on any failure.
    Non-fatal — caller continues without it if None.
    Anti-loop: skips titles already starting with "Let's Try Again".
    """
    if topic_title and topic_title.startswith("Let's Try Again"):
        logger.debug("generate_recovery_card: skipping recovery-of-recovery for %r", topic_title)
        return None

    try:
        concept_detail = knowledge_svc.get_concept_detail(concept_id)
        if not concept_detail:
            return None

        interests_text = ""
        if interests:
            interests_text = (
                f"\nStudent interests: {', '.join(interests[:3])}. "
                "Weave these naturally into your analogy and examples."
            )

        style_modifier = _RECOVERY_STYLE_MODIFIERS.get(style or "default", "")
        style_text = f"\n\n{style_modifier}" if style_modifier else ""

        lang_name = _RECOVERY_LANG_MAP.get(language, "English")
        lang_text = (
            f"\n\nIMPORTANT: Respond entirely in {lang_name}. All content must be in {lang_name}."
            if lang_name != "English" else ""
        )

        system_prompt = (
            "You are an expert adaptive math tutor. Generate ONE recovery TEACH card.\n"
            "The student just struggled with this topic twice. Re-explain in the SIMPLEST way.\n"
            "MANDATORY RULES:\n"
            "- card_type must be 'TEACH'\n"
            "- Title MUST start exactly with: Let's Try Again — \n"
            "- Language: age 8-10 reading level. Define every term.\n"
            "- Open with a real-world analogy BEFORE any formula or definition.\n"
            "- Use numbered step-by-step explanation.\n"
            "- For multiplication/arithmetic: include dot-array visual (● ● ● ● ●).\n"
            "- End with ONE easy MCQ — confidence-building, clearly correct answer.\n"
            "- Return ONLY valid JSON. No markdown fences.\n"
            "OUTPUT JSON SCHEMA (match exactly):\n"
            '{"card_type":"TEACH","title":"Let\'s Try Again — <topic>","content":"<markdown>",'
            '"image_indices":[],"question":{"text":"<question>","options":["A","B","C","D"],'
            '"correct_index":0,"explanation":"<why>","difficulty":"EASY"}}'
            + interests_text + style_text + lang_text
        )

        user_prompt = (
            f"Re-explain this topic in {lang_name}, STRUGGLING mode:\n"
            f"Topic: {topic_title}\n\n"
            f"Source material (use as factual basis):\n"
            f"{concept_detail.get('text', '')[:2000]}\n\n"
            "Return ONLY the JSON object."
        )

        response = await llm_client.chat.completions.create(
            model=ADAPTIVE_CARD_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            max_tokens=1200,
            temperature=0.3,
            timeout=20.0,
        )
        raw = response.choices[0].message.content or ""
        try:
            card = json.loads(raw)
        except json.JSONDecodeError:
            card = json.loads(repair_json(raw))

        card.setdefault("index", -1)
        card["is_recovery"] = True
        card.setdefault("images", [])
        card.setdefault("image_indices", [])
        return card

    except Exception as exc:
        logger.warning("generate_recovery_card failed (non-fatal): %s", exc)
        return None
