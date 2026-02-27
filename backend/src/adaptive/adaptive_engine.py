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
from config import OPENAI_MODEL

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
    Returns a dict with personal baselines, performance trend, and weak-concept flag.
    """
    from datetime import timedelta
    from sqlalchemy import select, func
    from db.models import CardInteraction, TeachingSession, StudentMastery
    import uuid as _uuid

    sid = _uuid.UUID(student_id) if isinstance(student_id, str) else student_id

    # 1. Global aggregate baseline
    agg_result = await db.execute(
        select(
            func.avg(CardInteraction.time_on_card_sec).label("avg_time"),
            func.avg(CardInteraction.wrong_attempts).label("avg_wrong"),
            func.avg(CardInteraction.hints_used).label("avg_hints"),
            func.count(CardInteraction.id).label("total_cards"),
        ).where(CardInteraction.student_id == sid)
    )
    agg = agg_result.one()

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
    }


def build_blended_analytics(
    current: "CardBehaviorSignals",
    history: dict,
    concept_id: str,
    student_id: str,
) -> AnalyticsSummary:
    """
    Blend current card signals with historical baseline using deviation detection.

    New student (< 5 cards): 100% current signals.
    Normal variance: 60% current / 40% history.
    Acute deviation (fever, distraction, or sudden recovery): 90% current / 10% history.
    """
    MIN_HISTORY_CARDS = 5
    has_history = history["total_cards_completed"] >= MIN_HISTORY_CARDS
    baseline_time = history["avg_time_per_card"] or 120.0
    baseline_wrong = history["avg_wrong_attempts"] or 0.0
    baseline_hints = history["avg_hints_per_card"] or 0.0

    if not has_history:
        cw, hw = 1.0, 0.0
    else:
        time_ratio = current.time_on_card_sec / max(baseline_time, 30.0)
        wrong_ratio = (current.wrong_attempts + 1) / max(baseline_wrong + 1, 1.0)
        is_acute = time_ratio > 2.0 or time_ratio < 0.4 or wrong_ratio > 3.0
        cw, hw = (0.9, 0.1) if is_acute else (0.6, 0.4)

    blended_wrong = current.wrong_attempts * cw + baseline_wrong * hw
    blended_hints = current.hints_used * cw + baseline_hints * hw
    expected_time = baseline_time  # personal baseline

    return AnalyticsSummary(
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
) -> tuple[dict, "LearningProfile", "GenerationProfile", str | None]:
    """
    Generate the next adaptive card using blended student analytics.
    Returns (card_dict, learning_profile, gen_profile, motivational_note).
    """
    from adaptive.prompt_builder import build_next_card_prompt
    from config import OPENAI_MODEL_MINI

    analytics = build_blended_analytics(signals, history, concept_id, student_id)
    has_prereq = find_remediation_prereq(concept_id, knowledge_svc, mastery_store) is not None
    profile = build_learning_profile(analytics, has_unmet_prereq=has_prereq)
    gen_profile = build_generation_profile(profile)

    concept_detail = knowledge_svc.get_concept_detail(concept_id)
    if concept_detail is None:
        raise ValueError(f"Concept not found: {concept_id}")

    sys_p, usr_p = build_next_card_prompt(
        concept_detail=concept_detail,
        learning_profile=profile,
        gen_profile=gen_profile,
        card_index=card_index,
        history=history,
        language=language,
    )

    messages = [
        {"role": "system", "content": sys_p},
        {"role": "user", "content": usr_p},
    ]
    raw = await _call_llm(llm_client, OPENAI_MODEL_MINI, messages, max_tokens=2200)
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
    }

    # Assign stable question IDs
    for i, q in enumerate(card["questions"]):
        q_type = q.get("type", "mcq")
        q["id"] = f"c{card_index}_{q_type}_{i}"

    return card, profile, gen_profile, motivational_note
