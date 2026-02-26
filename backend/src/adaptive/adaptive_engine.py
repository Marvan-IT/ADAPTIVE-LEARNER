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
