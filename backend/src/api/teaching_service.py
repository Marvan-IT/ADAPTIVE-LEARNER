"""
Teaching Service — The Pedagogical Loop.
Orchestrates the 2-step teaching flow:
  1. Presentation: metaphor-based explanation generated from RAG content
  2. Socratic Check: guided questioning to verify understanding (never gives answers)
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI

from config import (
    OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_MODEL_MINI,
    MASTERY_THRESHOLD, MAX_SOCRATIC_EXCHANGES, SOCRATIC_MAX_ATTEMPTS,
    CARDS_MID_SESSION_CHECK_INTERVAL, STARTER_PACK_MAX_SECTIONS, STARTER_PACK_INITIAL_SECTIONS,
    CARDS_MAX_TOKENS_SLOW, CARDS_MAX_TOKENS_SLOW_FLOOR, CARDS_MAX_TOKENS_SLOW_PER_SECTION,
    CARDS_MAX_TOKENS_NORMAL, CARDS_MAX_TOKENS_NORMAL_FLOOR, CARDS_MAX_TOKENS_NORMAL_PER_SECTION,
    CARDS_MAX_TOKENS_FAST, CARDS_MAX_TOKENS_FAST_FLOOR, CARDS_MAX_TOKENS_FAST_PER_SECTION,
    DEFAULT_BOOK_SLUG, NEXT_CARD_MAX_TOKENS,
)
from api.knowledge_service import KnowledgeService
from api.prompts import (
    build_presentation_system_prompt,
    build_presentation_user_prompt,
    build_socratic_system_prompt,
    build_remediation_socratic_prompt,
    build_cards_system_prompt,
    build_cards_user_prompt,
    build_assistant_system_prompt,
    build_mid_session_checkin_card,
)
from db.models import TeachingSession, ConversationMessage, StudentMastery, Student, SpacedReview, CardInteraction
from api.teaching_schemas import CardMCQ, RegenerateMCQRequest

logger = logging.getLogger(__name__)

import re as _re


def _sanitize_math(text: str) -> str:
    """Wrap bare LaTeX commands in $...$ and balance unmatched $ signs."""
    if not text:
        return text
    # Wrap bare \command not already inside $...$
    # Match \command followed by { or space, but not already preceded by $
    text = _re.sub(r'(?<!\$)(\\[a-zA-Z]+(?:\{|\s))', r'$\1', text)
    # Balance unmatched $ (odd count → append $)
    if text.count('$') % 2 != 0:
        text = text + '$'
    return text


_JSON_SAFE_ESCAPES = frozenset('"\\/u')
_JSON_WHITESPACE = frozenset('nrt')


def _fix_latex_backslashes(raw: str) -> str:
    """Escape unescaped backslashes in raw LLM JSON output, preserving LaTeX commands.

    JSON structural escapes (\\", \\/, \\\\, \\uXXXX) and true whitespace escapes
    (\\n, \\r, \\t not followed by a letter) are left as-is. Every other backslash
    is doubled so that json.loads keeps it as a literal backslash (LaTeX command).
    """
    out: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == '\\' and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt == '\\':
                # Double backslash: LaTeX line-break (\\ &=) OR JSON-escaped single backslash (\\frac)
                after = raw[i + 2] if i + 2 < len(raw) else ''
                if after.isalpha():
                    # \\command → keep as \\ so json.loads gives \command (e.g. \frac, \begin)
                    out.append(ch)
                    out.append(nxt)
                    i += 2
                else:
                    # LaTeX line break \\ followed by space/& — quadruple so json.loads gives \\ (LaTeX newline)
                    out.append('\\\\')
                    out.append('\\\\')
                    i += 2
            elif nxt in _JSON_SAFE_ESCAPES:
                out.append(ch)
                out.append(nxt)
                i += 2
            elif nxt in _JSON_WHITESPACE and (i + 2 >= len(raw) or not raw[i + 2].isalpha()):
                # Standalone \n \r \t — true JSON whitespace escape, not a LaTeX command
                out.append(ch)
                out.append(nxt)
                i += 2
            else:
                # LaTeX command backslash (e.g. \text, \times, \nabla) — double-escape
                out.append('\\\\')
                i += 1
        else:
            out.append(ch)
            i += 1
    return ''.join(out)


def _clean_salvage(raw: str) -> str | None:
    """Try to recover a truncated JSON string by closing open brackets/braces.

    Returns the salvaged string, or None if the input is empty or None.
    Companion to the per-card JSON parse loop in generate_per_card().
    """
    if not raw:
        return None
    raw = raw.rstrip()
    open_brackets = raw.count("[") - raw.count("]")
    open_braces = raw.count("{") - raw.count("}")
    if open_brackets < 0 or open_braces < 0:
        return None
    return raw + "]" * open_brackets + "}" * open_braces


def _normalise_per_card(parsed: dict, card_index: int) -> dict:
    """Normalise a raw per-card LLM dict to the shape expected by LessonCard.

    The LLM returns the single-card schema from _NEXT_CARD_JSON_SCHEMA.
    This function flattens it into the same dict shape used by generate_cards()
    and generate_next_section_cards() so the rest of the pipeline is uniform.
    """
    # Extract the first MCQ-type question from the 'questions' list, if present.
    questions = parsed.get("questions") or []
    question: dict | None = None
    for q in questions:
        if isinstance(q, dict) and q.get("type") in ("mcq", "multiple_choice"):
            question = q
            break

    card: dict = {
        "index": card_index,
        "card_type": parsed.get("card_type") or "TEACH",
        "title": parsed.get("title", f"Card {card_index + 1}"),
        "content": parsed.get("content", ""),
        "images": [],
        "image_indices": [],
        "difficulty": int(parsed["difficulty"]) if parsed.get("difficulty") is not None else 3,
        "options": None,
        "question": None,
        "question2": None,
    }

    if question:
        card["question"] = {
            "text": question.get("question", ""),
            "options": question.get("options", []),
            "correct_index": int(question.get("correct_index", 0)),
            "explanation": question.get("explanation", ""),
            "difficulty": "MEDIUM",
        }

    return card


# Section type classifier — priority order, first match wins
_SECTION_CLASSIFIER: list[tuple[str, str]] = [
    (r"^learning outcomes?\b",                                                 "LEARNING_OBJECTIVES"),
    (r"^section objectives?\b",                                                "LEARNING_OBJECTIVES"),
    (r"^chapter objectives?\b",                                                "LEARNING_OBJECTIVES"),
    (r"^section outcomes?\b",                                                  "LEARNING_OBJECTIVES"),
    (r"^after (?:studying|reading|completing) this (?:section|chapter)",      "LEARNING_OBJECTIVES"),
    (r"^by the end of this (?:section|chapter)",                              "LEARNING_OBJECTIVES"),
    (r"^students will be able to\b",                                          "LEARNING_OBJECTIVES"),
    (r"^objective\s+\d+\b",                                                   "LEARNING_OBJECTIVES"),
    (r"^learning objectives?\b",                                              "LEARNING_OBJECTIVES"),
    (r"^example\s+\d+\.\d+",                                                 "EXAMPLE"),
    (r"^try it\s+\d+\.\d+",                                                  "TRY_IT"),
    (r"^solution\b",                                                          "SOLUTION"),
    (r"^how to\b",                                                            "HOW_TO"),
    (r"^manipulative\b|^media\b|^access\b",                                  "SUPPLEMENTARY"),
    (r"^tip\b|^note\b|^be careful\b|^link to literacy\b|^everyday math\b",  "TIP"),
    (r"^be prepared\b",                                                       "PREREQ_CHECK"),
    (r"^writing exercises\b|^practice makes perfect\b|^mixed practice\b"
     r"|^review exercises\b|^practice test\b|^glossary\b|^key concepts\b",   "END_MATTER"),
]

# ALLCAPS section header pattern — matches OpenStax-style headers found in elementary_algebra,
# intermediate_algebra, algebra_1, and college_algebra books that lack markdown ## markers.
# Compiled at module level to avoid recompilation on every _parse_sub_sections() call.
_ALLCAPS_SECTION_RE = re.compile(
    r'^(EXAMPLE|TRY[\s\-]IT|SOLUTION|HOW\s+TO|LEARNING\s+OBJECTIVES?|LEARNING\s+OUTCOMES?|SECTION\s+OBJECTIVES?|CHAPTER\s+OBJECTIVES?|SECTION\s+OUTCOMES?|OBJECTIVE|'
    r'BE\s+PREPARED|MEDIA|ACCESS|MANIPULATIVE|LINK\s+TO\s+LITERACY|'
    r'EVERYDAY\s+MATH|WRITING\s+EXERCISES?|PRACTICE\s+MAKES\s+PERFECT|'
    r'MIXED\s+PRACTICE|KEY\s+CONCEPTS?|REVIEW\s+EXERCISES?|PRACTICE\s+TEST|'
    r'GLOSSARY|CHAPTER\s+REVIEW|CHAPTER\s+PRACTICE\s+TEST|HOMEWORK)'
    r'(?:\s+[\d\.]+)?(?:[\s:].+)?$',
    re.IGNORECASE | re.MULTILINE,
)

# Pedagogical card order within each section — secondary sort key after _section_index.
# Primary sort is always _section_index (textbook section position).
_CARD_TYPE_ORDER: dict[str, int] = {
    "FUN": 0,
    "TEACH": 1,
    "VISUAL": 2,
    "EXAMPLE": 3,
    "APPLICATION": 4,
    "QUESTION": 5,
    "EXERCISE": 6,
    "CHECKIN": 7,
    "RECAP": 8,
}

# Math domain classifier for section-type-specific prompt notes
# Text is normalized (underscores/dots → spaces) before matching, so \b word boundaries work correctly.
# Use leading \b on short tokens to prevent substring false-positives (e.g. "ratio" inside "operations").
_SECTION_DOMAIN_MAP: list[tuple[str, str]] = [
    (r"\badd\b|\bsubtract\b|\bmultiply\b|\bdivide\b|whole number|\binteger\b",        "TYPE_A"),
    (r"solve equation|solving equation|properties of equality",                        "TYPE_B"),
    (r"\bfraction|\bmixed number|\bnumerator\b|\bdenominator\b|\bimproper\b",         "TYPE_C"),
    (r"\bgeometry\b|\bangle\b|\btriangle\b|\brectangle\b|\bcircle\b|\bvolume\b|surface area", "TYPE_D"),
    (r"language of algebra|\bexpression\b|\bvariable\b|\bconstant\b|\bevaluate\b|\btranslate\b", "TYPE_E"),
    (r"\bpercent\b|\bratio\b|\brate\b|\bproportion\b|\bcommission\b|\bdiscount\b|\binterest\b", "TYPE_F"),
    (r"\bexponent\b|\bpolynomial\b|\bmonomial\b|\bfactor\b|scientific notation",      "TYPE_G"),
]


def validate_and_repair_cards(
    cards: list,
    section_order: list[str],
    required_sections: list[str] | None = None,
) -> tuple[list, list[str]]:
    """Validate and repair generated cards for coverage, ordering, and deduplication.

    Args:
        cards: List of card dicts (with keys: section_id, card_type, question, answer, etc.)
        section_order: Ordered list of section_ids defining correct sequence
        required_sections: If provided, sections that MUST have at least one card

    Returns:
        (repaired_cards, missing_sections) where:
        - repaired_cards: cards sorted by section_order, duplicates removed, section_ids inferred
        - missing_sections: list of required_sections with no card (triggers re-generation)
    """
    if not cards:
        return [], list(required_sections or [])

    # Step 1: Build section index for ordering
    section_index = {sid: i for i, sid in enumerate(section_order)}

    # Step 2: Infer missing section_id from content (fuzzy match against section_order)
    for card in cards:
        if not card.get("section_id"):
            # Try to match card content against section titles
            content = f"{card.get('question', '')} {card.get('answer', '')} {card.get('front', '')} {card.get('back', '')}".lower()
            best_match = None
            best_score = 0
            for sid in section_order:
                # Simple word overlap scoring
                sid_words = set(sid.lower().replace("_", " ").replace("-", " ").split())
                content_words = set(content.split())
                if sid_words:
                    score = len(sid_words & content_words) / len(sid_words)
                    if score > best_score and score > 0.3:
                        best_score = score
                        best_match = sid
            card["section_id"] = best_match or (section_order[0] if section_order else "unknown")

    # Step 3: Sort by section_order index
    def sort_key(card: dict) -> int:
        sid = card.get("section_id", "")
        return section_index.get(sid, len(section_order))

    sorted_cards = sorted(cards, key=sort_key)

    # Step 4: Remove duplicate section+card_type pairs (keep first occurrence)
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for card in sorted_cards:
        key = (card.get("section_id", ""), card.get("card_type", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(card)

    # Step 5: Check coverage
    sections_covered = {card.get("section_id", "") for card in deduped}
    missing: list[str] = []
    if required_sections:
        missing = [s for s in required_sections if s not in sections_covered]

    return deduped, missing


async def _update_strategy_effectiveness(
    db: AsyncSession,
    student_id: uuid.UUID,
    strategy: str,
    was_effective: bool,
) -> None:
    """Update student's effective/ineffective engagement lists based on strategy outcome.

    - was_effective=True  → add to effective_engagement, remove from ineffective_engagement
    - was_effective=False → add to ineffective_engagement (does not touch effective_engagement)

    Commits the change. Logs and swallows all errors so a feedback failure never
    blocks the card-interaction response.
    """
    try:
        result = await db.execute(select(Student).where(Student.id == student_id))
        student = result.scalar_one_or_none()
        if not student:
            logger.warning(
                "[strategy-feedback] student not found: student_id=%s strategy=%s",
                student_id, strategy,
            )
            return

        if was_effective:
            current = list(student.effective_engagement or [])
            if strategy not in current:
                current.append(strategy)
            student.effective_engagement = current
            # Remove from ineffective list if it was there
            ineffective = list(student.ineffective_engagement or [])
            student.ineffective_engagement = [s for s in ineffective if s != strategy]
        else:
            current = list(student.ineffective_engagement or [])
            if strategy not in current:
                current.append(strategy)
            student.ineffective_engagement = current

        await db.commit()
        logger.info(
            "[strategy-feedback] updated: student_id=%s strategy=%s was_effective=%s",
            student_id, strategy, was_effective,
        )
    except Exception:
        logger.exception(
            "[strategy-feedback] failed to update: student_id=%s strategy=%s was_effective=%s",
            student_id, strategy, was_effective,
        )


def _build_learning_profile_summary(summary, generate_as: str, blended_score: float) -> dict:
    """Map adaptive engine output → shape expected by detectMode() in adaptiveStore.js."""
    if generate_as == "STRUGGLING":
        speed, comprehension = "SLOW", "STRUGGLING"
    elif generate_as == "FAST":
        speed, comprehension = "FAST", "STRONG"
    else:
        speed, comprehension = "NORMAL", "OK"

    attempts = getattr(summary, "attempts", 1) or 1
    avg_time = getattr(summary, "time_spent_sec", 0.0) / attempts

    return {
        "speed": speed,
        "comprehension": comprehension,
        "engagement": "FOCUSED",
        "wrong_attempts": getattr(summary, "wrong_attempts", 0),
        "avg_time_per_card": avg_time,
    }


class TeachingService:
    """Manages the full lifecycle of a teaching session."""

    def __init__(self, knowledge_services: "dict[str, KnowledgeService]"):
        self.knowledge_services = knowledge_services
        self.openai = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        self.model = OPENAI_MODEL
        self.model_mini = OPENAI_MODEL_MINI

    def _get_ksvc(self, session: "TeachingSession") -> KnowledgeService:
        """Return the KnowledgeService for the session's book, falling back to default book."""
        slug = getattr(session, "book_slug", DEFAULT_BOOK_SLUG) or DEFAULT_BOOK_SLUG
        svc = self.knowledge_services.get(slug)
        if svc is None:
            svc = self.knowledge_services.get(DEFAULT_BOOK_SLUG) or next(iter(self.knowledge_services.values()))
        return svc

    async def _chat(self, messages: list, max_tokens: int = 2000, temperature: float = 0.7, model: str | None = None, timeout: float = 30.0) -> str:
        """Call GPT and return the response content. Pass model='mini' to use gpt-4o-mini."""
        use_model = self.model_mini if model == "mini" else self.model
        last_exc = None
        for attempt in range(3):
            try:
                response = await self.openai.chat.completions.create(
                    model=use_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
                if not response.choices:
                    raise ValueError("LLM returned no choices")
                content = response.choices[0].message.content or ""
                if not content.strip():
                    finish = response.choices[0].finish_reason
                    logger.warning("[%s] Attempt %d: empty content, finish_reason=%s",
                                   use_model, attempt + 1, finish)
                if content.strip():
                    return content.strip()
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
            except Exception as e:
                last_exc = e
                logger.warning("[%s] Attempt %d failed: %s", use_model, attempt + 1, e)
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
        raise ValueError(f"LLM ({use_model}) failed after 3 retries: {last_exc}")

    # ── Start Session ─────────────────────────────────────────────

    async def start_session(
        self,
        db: AsyncSession,
        student_id: uuid.UUID,
        concept_id: str,
        book_slug: str = DEFAULT_BOOK_SLUG,
        style: str = "default",
        lesson_interests: list[str] | None = None,
    ) -> TeachingSession:
        """Create a new teaching session for a student + concept."""
        session = TeachingSession(
            student_id=student_id,
            concept_id=concept_id,
            book_slug=book_slug,
            phase="PRESENTING",
            style=style,
            lesson_interests=lesson_interests or None,
        )
        db.add(session)
        await db.flush()
        return session

    # ── Generate Presentation ─────────────────────────────────────

    async def generate_presentation(
        self,
        db: AsyncSession,
        session: TeachingSession,
        student: Student,
    ) -> str:
        """
        Generate the metaphor-based explanation for the concept.
        Uses KnowledgeService to get concept text, then sends to OpenAI.
        Caches the result in session.presentation_text.
        """
        if session.presentation_text:
            return session.presentation_text

        # 1. Retrieve concept content from KnowledgeService (RAG)
        concept = self._get_ksvc(session).get_concept_detail(session.concept_id)
        if not concept:
            raise ValueError(f"Concept not found: {session.concept_id}")

        concept_text = concept["text"]
        concept_title = concept["concept_title"]
        latex = concept.get("latex", [])
        prerequisites = concept.get("prerequisites", [])
        images = concept.get("images", [])

        # 2. Build the prompt (per-lesson interests override student profile)
        effective_interests = session.lesson_interests if session.lesson_interests else student.interests
        language = getattr(student, "preferred_language", "en") or "en"
        system_prompt = build_presentation_system_prompt(
            style=session.style,
            interests=effective_interests,
            language=language,
        )
        user_prompt = build_presentation_user_prompt(
            concept_title=concept_title,
            concept_text=concept_text,
            latex=latex,
            prerequisites=prerequisites,
            images=images,
        )

        # 3. Call OpenAI
        presentation = await self._chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=2000,
            model="mini",
        )

        # 4. Cache in the session and store messages
        session.presentation_text = presentation
        msg_count = await self._get_message_count(db, session.id)
        await self._save_message(db, session.id, "system", system_prompt, "PRESENTING", msg_count)
        await self._save_message(db, session.id, "user", user_prompt, "PRESENTING", msg_count + 1)
        await self._save_message(db, session.id, "assistant", presentation, "PRESENTING", msg_count + 2)

        await db.flush()
        return presentation

    # ── Transition to Socratic Check ──────────────────────────────

    async def begin_socratic_check(
        self,
        db: AsyncSession,
        session: TeachingSession,
        student: Student,
    ) -> str:
        """
        Transition session to CHECKING phase.
        Returns the first Socratic question from the AI.
        """
        if session.phase not in ("PRESENTING", "CARDS_DONE"):
            raise ValueError(f"Cannot begin check: session is in {session.phase} phase")

        session.phase = "CHECKING"

        concept = self._get_ksvc(session).get_concept_detail(session.concept_id)
        concept_text = concept["text"]
        concept_title = concept["concept_title"]
        images = concept.get("images", [])

        # Query this session's card interaction stats for adaptive Socratic calibration
        session_card_stats = None
        try:
            stats_result = await db.execute(
                select(
                    func.count(CardInteraction.id).label("total_cards"),
                    func.coalesce(func.sum(CardInteraction.wrong_attempts), 0).label("total_wrong"),
                    func.coalesce(func.sum(CardInteraction.hints_used), 0).label("total_hints"),
                ).where(CardInteraction.session_id == session.id)
            )
            row = stats_result.one()
            total_cards = int(row.total_cards or 0)
            total_wrong = int(row.total_wrong or 0)
            total_hints = int(row.total_hints or 0)
            session_card_stats = {
                "total_cards": total_cards,
                "total_wrong": total_wrong,
                "total_hints": total_hints,
                "error_rate": total_wrong / max(total_cards, 1) if total_cards > 0 else 0.0,
            }
            logger.info(
                "[socratic-adaptive] session_id=%s session_cards=%d session_wrong=%d "
                "session_hints=%d error_rate=%.2f",
                str(session.id),
                session_card_stats["total_cards"],
                session_card_stats["total_wrong"],
                session_card_stats["total_hints"],
                session_card_stats["error_rate"],
            )
        except Exception as exc:
            logger.exception(
                "[socratic-adaptive] session_stats_failed: session_id=%s error=%s — continuing without stats",
                session.id, exc,
            )

        # Build student's learning profile from card interaction history
        from adaptive.adaptive_engine import load_student_history
        from adaptive.profile_builder import build_learning_profile
        from adaptive.schemas import AnalyticsSummary

        history = await load_student_history(str(session.student_id), session.concept_id, db)
        mini_analytics = AnalyticsSummary(
            student_id=str(session.student_id),
            concept_id=session.concept_id,
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

        # Extract the specific card titles the student actually studied.
        # Socratic questions must be restricted to these topics only.
        # Also build card_visuals: {title, description, image} for cards that have images.
        covered_topics: list[str] = []
        card_visuals: list[dict] = []
        if session.presentation_text:
            try:
                cached = json.loads(session.presentation_text)
                if isinstance(cached, dict):
                    card_list = cached.get("cards", [])
                elif isinstance(cached, list):
                    card_list = cached
                else:
                    card_list = []
                covered_topics = [c.get("title", "") for c in card_list if c.get("title")]
                for card in card_list:
                    imgs = card.get("images") or []
                    if imgs and card.get("title"):
                        card_visuals.append({
                            "title": card["title"],
                            "description": (imgs[0].get("description") or imgs[0].get("filename") or "")[:200],
                            "image": imgs[0],
                        })
            except Exception:
                logger.warning("[socratic-scope] Failed to parse presentation_text for session_id=%s", session.id, exc_info=True)
                covered_topics = []
        logger.info(
            "[socratic-scope] session_id=%s covered_topics=%s",
            str(session.id), covered_topics,
        )

        # Build the Socratic system prompt (per-lesson interests override profile)
        effective_interests = session.lesson_interests if session.lesson_interests else student.interests
        language = getattr(student, "preferred_language", "en") or "en"
        system_prompt = build_socratic_system_prompt(
            concept_title=concept_title,
            concept_text=concept_text,
            style=session.style,
            interests=effective_interests,
            card_visuals=card_visuals,
            language=language,
            socratic_profile=socratic_profile,
            history=history,
            session_card_stats=session_card_stats,
            covered_topics=covered_topics,
        )

        msg_count = await self._get_message_count(db, session.id)

        # Build conversation for the API
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "I've read the explanation. Please check my understanding."},
        ]

        raw_first_question = await self._chat(messages=messages, max_tokens=500, model="mini")
        first_question, first_image = self._parse_card_image_ref(raw_first_question, card_visuals)

        # Store messages
        await self._save_message(db, session.id, "system", system_prompt, "CHECKING", msg_count)
        await self._save_message(
            db, session.id, "user",
            "I've read the explanation. Please check my understanding.",
            "CHECKING", msg_count + 1,
        )
        await self._save_message(db, session.id, "assistant", first_question, "CHECKING", msg_count + 2)

        await db.flush()
        return first_question, first_image

    # ── Handle Student Response (Socratic Loop) ───────────────────

    async def handle_student_response(
        self,
        db: AsyncSession,
        session: TeachingSession,
        student_message: str,
    ) -> dict:
        """
        Process a student's response during the Socratic check.

        Returns:
            {
                "response": str,
                "phase": str,
                "check_complete": bool,
                "score": int | None,
                "mastered": bool | None,
            }
        """
        if session.phase not in ("CHECKING", "RECHECKING", "RECHECKING_2"):
            raise ValueError(f"Cannot respond: session is in {session.phase} phase")

        current_phase = session.phase

        # Get all previous messages for the current check phase
        messages = await self._get_phase_messages(db, session.id, current_phase)

        # Save the student's new message
        msg_count = await self._get_message_count(db, session.id)
        await self._save_message(db, session.id, "user", student_message, current_phase, msg_count)

        # Count student exchanges so far (before this message)
        user_exchange_count = sum(1 for m in messages if m.role == "user")

        # Build the OpenAI messages array from conversation history
        raw_messages = [{"role": m.role, "content": m.content} for m in messages]
        raw_messages.append({"role": "user", "content": student_message})

        # Window the history to avoid token blowup in long sessions
        openai_messages = self._build_windowed_messages(raw_messages)

        # Mid-session encouragement at halfway point
        if user_exchange_count == 12:
            if openai_messages and openai_messages[0]["role"] == "system":
                openai_messages.insert(1, {
                    "role": "system",
                    "content": (
                        "The student has been working hard for a while. Before your next question, "
                        "include one warm, brief sentence acknowledging their effort and encouraging them to keep going."
                    ),
                })

        # Safety net: force-conclude if ceiling reached
        if user_exchange_count >= MAX_SOCRATIC_EXCHANGES:
            force_directive = {
                "role": "system",
                "content": (
                    f"MANDATORY: You have already asked {user_exchange_count} questions. "
                    "Stop asking more questions. Give the student one warm sentence of encouragement "
                    "for their effort, then include [ASSESSMENT:XX] to conclude the session."
                ),
            }
            if openai_messages and openai_messages[0]["role"] == "system":
                openai_messages.insert(1, force_directive)
            else:
                openai_messages.insert(0, force_directive)

        # Build card_visuals for image resolution
        card_visuals: list[dict] = []
        if session.presentation_text:
            try:
                cached = json.loads(session.presentation_text)
                cv_card_list = cached.get("cards", []) if isinstance(cached, dict) else (cached if isinstance(cached, list) else [])
                for card in cv_card_list:
                    imgs = card.get("images") or []
                    if imgs and card.get("title"):
                        card_visuals.append({
                            "title": card["title"],
                            "description": (imgs[0].get("description") or imgs[0].get("filename") or "")[:200],
                            "image": imgs[0],
                        })
            except Exception:
                logger.warning("[socratic-respond] Failed to parse presentation_text for session_id=%s", session.id, exc_info=True)

        # Call OpenAI for the next Socratic response (150 tokens enforces 1-2 sentence hints)
        raw_ai_response = await self._chat(messages=openai_messages, max_tokens=150)
        ai_response, response_image = self._parse_card_image_ref(raw_ai_response, card_visuals)
        await self._save_message(db, session.id, "assistant", ai_response, current_phase, msg_count + 1)

        # Check if the AI signaled completion
        check_complete, score = self._parse_assessment(ai_response)

        # Strip the assessment marker from the visible response
        clean_response = ai_response
        if check_complete and score is not None:
            clean_response = re.sub(r'\[ASSESSMENT:\d+\]', '', ai_response).strip()

        result = {
            "response": clean_response,
            "phase": session.phase,
            "check_complete": check_complete,
            "score": score,
            "mastered": None,
            "remediation_needed": False,
            "attempt": session.socratic_attempt_count,
            "locked": False,
            "best_score": session.best_check_score,
            "image": response_image,
        }

        if check_complete:
            # Track the best score across all attempts
            session.best_check_score = max(session.best_check_score or 0, score)
            session.check_score = score

            mastered = score >= MASTERY_THRESHOLD
            result["mastered"] = mastered

            if mastered:
                # ── MASTERY PATH ──────────────────────────────────────────
                session.phase = "COMPLETED"
                session.concept_mastered = True
                session.completed_at = datetime.now(timezone.utc)
                result["phase"] = "COMPLETED"

                # Check for existing mastery (re-learn scenario)
                existing = await db.execute(
                    select(StudentMastery).where(
                        StudentMastery.student_id == session.student_id,
                        StudentMastery.concept_id == session.concept_id,
                    )
                )
                existing_mastery = existing.scalar_one_or_none()
                if existing_mastery:
                    existing_mastery.session_id = session.id
                    existing_mastery.mastered_at = datetime.now(timezone.utc)
                else:
                    db.add(StudentMastery(
                        student_id=session.student_id,
                        concept_id=session.concept_id,
                        session_id=session.id,
                    ))
                    # Create spaced review schedule only on FIRST mastery (Ebbinghaus)
                    from datetime import timedelta
                    REVIEW_INTERVALS_DAYS = [1, 3, 7, 14, 30]
                    now_utc = datetime.now(timezone.utc)
                    for i, days in enumerate(REVIEW_INTERVALS_DAYS, 1):
                        db.add(SpacedReview(
                            student_id=session.student_id,
                            concept_id=session.concept_id,
                            review_number=i,
                            due_at=now_utc + timedelta(days=days),
                        ))

                logger.info(
                    "[assessment] session_id=%s score=%d MASTERED", str(session.id), score
                )

            elif session.socratic_attempt_count < SOCRATIC_MAX_ATTEMPTS:
                # ── REMEDIATION PATH ──────────────────────────────────────
                session.socratic_attempt_count += 1
                # Extract covered card titles to help _extract_failed_topics identify weak spots
                _covered: list[str] = []
                if session.presentation_text:
                    try:
                        _cached = json.loads(session.presentation_text)
                        _card_list = _cached.get("cards", []) if isinstance(_cached, dict) else []
                        _covered = [c.get("title", "") for c in _card_list if c.get("title")]
                    except Exception:
                        pass
                failed_topics = await self._extract_failed_topics(session.id, db, covered_topics=_covered)
                # Fall back to generic message when no corrections were detected
                if not failed_topics:
                    failed_topics = _covered[:5] if _covered else ["the key concepts of this section"]
                session.remediation_context = json.dumps(failed_topics)

                # Set phase based on attempt count
                if session.socratic_attempt_count == 1:
                    session.phase = "REMEDIATING"
                else:
                    session.phase = "REMEDIATING_2"

                result["phase"] = session.phase
                result["remediation_needed"] = True
                result["attempt"] = session.socratic_attempt_count

                logger.info(
                    "[assessment] session_id=%s score=%d attempt=%d phase=%s",
                    str(session.id), score, session.socratic_attempt_count, session.phase,
                )

            else:
                # ── EXHAUSTED ALL ATTEMPTS ────────────────────────────────
                session.phase = "COMPLETED"
                session.concept_mastered = False
                session.completed_at = datetime.now(timezone.utc)
                result["phase"] = "COMPLETED"
                result["locked"] = False  # Student can retry from the concept map
                result["best_score"] = session.best_check_score

                logger.info(
                    "[assessment] session_id=%s score=%d attempts_exhausted best_score=%d",
                    str(session.id), score, session.best_check_score or 0,
                )

        await db.flush()
        return result

    # ── Style Switching ───────────────────────────────────────────

    async def switch_style(
        self,
        db: AsyncSession,
        session: TeachingSession,
        new_style: str,
        student: Student,
    ) -> str:
        """
        Switch the teaching style mid-session.
        Regenerates the presentation if in PRESENTING phase.
        """
        session.style = new_style

        if session.phase == "PRESENTING":
            session.presentation_text = None
            return await self.generate_presentation(db, session, student)

        await db.flush()
        return f"Style switched to {new_style}. The new style will apply to future responses."

    # ── Card-Based Learning ──────────────────────────────────────

    # Cards with these titles are artifacts of old mechanical grouping — reject their cache.
    _STALE_TITLE_RE = re.compile(r"^(solution$|how to$|\(r\))", re.IGNORECASE)

    @staticmethod
    def _has_stale_card_titles(cards: list[dict]) -> bool:
        """Return True if any card title looks like a support heading from old grouping."""
        return any(
            TeachingService._STALE_TITLE_RE.match(c.get("title", ""))
            for c in cards
        )

    async def generate_cards(
        self,
        db: AsyncSession,
        session: TeachingSession,
        student: Student,
    ) -> dict:
        """
        Generate card-based lesson: split concept into sub-section cards,
        each with AI-generated explanation and quiz questions.
        Returns dict with cards array and metadata.
        """
        # Return cached if available — reject stale sessions with old grouping artifacts
        _CARDS_CACHE_VERSION = 23  # Force regen: pedagogical within-section card ordering (TEACH before EXAMPLE)
        if session.presentation_text:
            try:
                cached = json.loads(session.presentation_text)
                if "cards" in cached:
                    # Bust cache when version is behind (old cards from before latest rebuild)
                    if cached.get("cache_version", 0) < _CARDS_CACHE_VERSION:
                        raise ValueError("stale cache version")
                    has_new_schema = any(card.get("card_type") for card in cached.get("cards", []))
                    is_stale = TeachingService._has_stale_card_titles(cached.get("cards", []))
                    if has_new_schema and not is_stale:
                        # Lightweight re-sort on cache load — no re-gen trigger, just ordering
                        cached_cards = cached.get("cards", [])
                        if cached_cards:
                            section_order = [c.get("section_id", "") for c in cached_cards if c.get("section_id")]
                            repaired, _ = validate_and_repair_cards(cached_cards, section_order)
                            if repaired:
                                cached["cards"] = repaired
                        return cached
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        # 1. Retrieve concept
        concept = self._get_ksvc(session).get_concept_detail(session.concept_id)
        if not concept:
            raise ValueError(f"Concept not found: {session.concept_id}")

        concept_text = concept["text"]
        concept_title = concept["concept_title"]
        latex = concept.get("latex", [])
        images = concept.get("images", [])

        # 2. Parse sub-sections from concept text. Use real sub-sections only;
        # fall back to single section if parsing yields nothing.
        sub_sections = self._parse_sub_sections(concept_text)
        if not sub_sections:
            sub_sections = [{"title": concept_title, "text": concept_text}]
        else:
            # Consolidate micro-sections using the textbook blueprint approach:
            # classify each section by pedagogical type, then build an ordered blueprint
            # that merges SOLUTION into preceding EXAMPLE and TIP into preceding item.
            # Falls back to _group_by_major_topic if the blueprint yields < 2 items.
            classified = self._classify_sections(sub_sections)

            # Ensure Learning Objectives is always first in the blueprint.
            # Case A: LO exists but is not at index 0 — move it to front.
            # Case B: No LO found — synthesize from first section's text if possible.
            lo_indices = [i for i, s in enumerate(classified) if s.get("section_type") == "LEARNING_OBJECTIVES"]
            if lo_indices and lo_indices[0] != 0:
                lo_section = classified.pop(lo_indices[0])
                classified.insert(0, lo_section)
            elif not lo_indices:
                # No LO section found — try to synthesize from intro text
                first = classified[0] if classified else None
                if first:
                    lo_match = re.search(
                        r'((?:by the end of this (?:section|chapter)'
                        r'|after (?:studying|reading|completing) this (?:section|chapter)'
                        r'|you will be able to'
                        r'|students will be able to'
                        r'|in this section[,\s]+(?:you|we|students)'
                        r'|upon completion)'
                        r'.*?)(?=\n\n|\Z)',
                        first.get("text", ""), re.IGNORECASE | re.DOTALL
                    )
                    if lo_match:
                        lo_text = lo_match.group(1).strip()
                        first["text"] = first["text"].replace(lo_match.group(0), "").strip()
                        classified.insert(0, {
                            "title": "Learning Objectives",
                            "text": lo_text,
                            "section_type": "LEARNING_OBJECTIVES",
                        })

            blueprint = self._build_textbook_blueprint(classified)
            if len(blueprint) >= 2:
                sub_sections = blueprint
                logger.info("[blueprint] concept=%s raw=%d blueprint=%d",
                            session.concept_id, len(classified), len(blueprint))
            else:
                logger.warning("[blueprint] fallback for concept=%s (%d items)",
                               session.concept_id, len(blueprint))
                sub_sections = self._group_by_major_topic(sub_sections)

        # Classify the math domain for section-type-specific prompt notes
        section_domain = self._classify_section_type(session.concept_id, concept_title)

        # Rolling architecture: generate only the first STARTER_PACK_INITIAL_SECTIONS sub-sections
        # on the initial request. The remaining sections are stored in concepts_queue and generated
        # one-by-one via POST /next-section-cards with live student signals.
        all_sub_sections = sub_sections[:]  # full list preserved for queue
        # Apply STARTER_PACK_MAX_SECTIONS as a safety cap on the total queue size
        if len(all_sub_sections) > STARTER_PACK_MAX_SECTIONS:
            logger.info(
                "[starter-pack] concept=%s capping total %d sections → %d (safety cap)",
                session.concept_id, len(all_sub_sections), STARTER_PACK_MAX_SECTIONS,
            )
            all_sub_sections = all_sub_sections[:STARTER_PACK_MAX_SECTIONS]
        sub_sections = all_sub_sections[:STARTER_PACK_INITIAL_SECTIONS]   # generate first N only
        concepts_queue = all_sub_sections[STARTER_PACK_INITIAL_SECTIONS:]  # remainder for rolling
        logger.info(
            "[starter-pack] concept=%s initial=%d queue=%d total=%d",
            session.concept_id, len(sub_sections), len(concepts_queue), len(all_sub_sections),
        )

        # 3. Only include images that are educational AND have a real vision description
        # AND are not self-assessment checklists/rubrics (which pass is_educational=True
        # but are not math diagrams the student needs to see).
        _CHECKLIST_KEYWORDS = (
            "checklist", "self-assessment", "i can", "confidently",
            "with some help", "rubric", "evaluate my understanding", "learning target",
        )
        useful_images = [
            img for img in images
            if img.get("is_educational") is not False
            and img.get("description")
            and not any(
                kw in (img.get("description") or "").lower()
                for kw in _CHECKLIST_KEYWORDS
            )
        ]
        _IMAGE_TYPE_PRIORITY = {"DIAGRAM": 0, "CHART": 1, "GRAPH": 1, "TABLE": 2, "PHOTO": 3}
        useful_images = sorted(
            useful_images,
            key=lambda img: (
                _IMAGE_TYPE_PRIORITY.get((img.get("image_type") or "").upper(), 4),
                -len(img.get("description") or ""),
            ),
        )[:16]
        logger.info(
            "cards concept=%s total_images=%d useful_images=%d",
            session.concept_id, len(images), len(useful_images),
        )

        # 3b. Load student history and wrong-option pattern concurrently for adaptive enrichment
        from adaptive.adaptive_engine import load_student_history, load_wrong_option_pattern, build_blended_analytics
        from adaptive.profile_builder import build_learning_profile
        from adaptive.schemas import AnalyticsSummary, CardBehaviorSignals

        try:
            history, wrong_option_pattern = await asyncio.gather(
                load_student_history(str(session.student_id), session.concept_id, db),
                load_wrong_option_pattern(str(session.student_id), session.concept_id, db),
            )
        except Exception as exc:
            logger.exception(
                "[cards-adaptive] history_load_failed: student_id=%s concept_id=%s error=%s — using defaults",
                session.student_id, session.concept_id, exc,
            )
            history = {
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
            wrong_option_pattern = None

        # Build LearningProfile via 60/40 blended analytics.
        # For Path A (initial card generation, no live interaction yet) we construct a synthetic
        # CardBehaviorSignals from historical averages and let build_blended_analytics apply
        # the 60/40 (or 90/10 acute deviation) blend against the historical baseline.
        current_signals = CardBehaviorSignals(
            card_index=history.get("total_cards_completed", 0),  # Bug 7 fix: use actual position
            time_on_card_sec=history["avg_time_per_card"] or 120.0,
            wrong_attempts=round(history["avg_wrong_attempts"] or 0),
            hints_used=round(history["avg_hints_per_card"] or 0),
            idle_triggers=0,
        )
        _blended_score: float = 2.0
        _generate_as: str = "NORMAL"
        try:
            blended, _blended_score, _generate_as = build_blended_analytics(
                current_signals, history,
                concept_id=session.concept_id,
                student_id=str(session.student_id),
            )
            # Conservative mode cap: new students (< 5 interactions) must not get FAST mode
            total_interactions = history.get("total_interactions", 0) if history else 0
            if total_interactions < 2 and _generate_as == "FAST":
                _generate_as = "NORMAL"
                _blended_score = min(_blended_score, 2.4)
                logger.info(
                    "[mode-cap] concept=%s FAST→NORMAL for new student (interactions=%d)",
                    session.concept_id, total_interactions,
                )
            card_profile = build_learning_profile(blended, has_unmet_prereq=False)
        except Exception as exc:
            logger.warning(
                "[cards-adaptive] blended_analytics_failed: student_id=%s — falling back to direct history: %s",
                session.student_id, exc,
            )
            mini = AnalyticsSummary(
                student_id=str(session.student_id),
                concept_id=session.concept_id,
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
        logger.info(
            "Card adaptive profile for student=%s concept=%s: speed=%s comp=%s eng=%s",
            session.student_id, session.concept_id,
            card_profile.speed, card_profile.comprehension, card_profile.engagement,
        )

        # Token budget is content-driven, not mode-driven — all modes reproduce 100% of source content
        per_section_floor = CARDS_MAX_TOKENS_SLOW_PER_SECTION

        logger.info(
            "[cards-adaptive] student_id=%s concept_id=%s history_cards=%d "
            "profile=%s/%s/%s wrong_option_pattern=%s",
            str(session.student_id), session.concept_id,
            history["total_cards_completed"],
            card_profile.speed,
            card_profile.comprehension,
            card_profile.engagement,
            wrong_option_pattern,
        )

        # 4. Build prompts
        effective_interests = session.lesson_interests if session.lesson_interests else student.interests
        language = getattr(student, "preferred_language", "en") or "en"

        # Extract remediation weak concepts from session context (set during earlier REMEDIATING phases)
        remediation_weak: list[str] = []
        if session is not None and getattr(session, "socratic_attempt_count", 0) > 0:
            raw_ctx = getattr(session, "remediation_context", None)
            if raw_ctx:
                try:
                    remediation_weak = json.loads(raw_ctx) if isinstance(raw_ctx, str) else (raw_ctx or [])
                except Exception:
                    pass

        system_prompt = build_cards_system_prompt(
            style=session.style,
            interests=effective_interests,
            language=language,
            learning_profile=card_profile,
            history=history,
            images=useful_images,
            remediation_weak_concepts=remediation_weak if remediation_weak else None,
            generate_as=_generate_as,
            blended_state_score=_blended_score,
            confidence_score=getattr(card_profile, "confidence_score", 0.5),
            trend_direction=history.get("trend_direction", "STABLE") if history else "STABLE",
            engagement=getattr(card_profile, "engagement", "ENGAGED"),
            section_domain=section_domain,
        )

        # Build a single user_prompt for cache saving purposes (saved to messages later)
        user_prompt = build_cards_user_prompt(
            concept_title=concept_title,
            sub_sections=sub_sections,
            latex=latex,
            images=useful_images,
            wrong_option_pattern=wrong_option_pattern,
            language=language,
            interests=effective_interests,
            style=session.style,
            learning_profile=card_profile,
            generate_as=_generate_as,
            blended_score=_blended_score,
        )

        # 5. Generate cards — per-section parallel calls so no section is dropped due to truncation.
        # Each section gets its own LLM call; results are merged in section order.
        n_sections = len(sub_sections)
        # Unified budget: scale with content (section count × per-section floor), not mode
        adaptive_max_tokens = max(CARDS_MAX_TOKENS_SLOW_FLOOR, n_sections * CARDS_MAX_TOKENS_SLOW_PER_SECTION)
        logger.info(
            "cards token_budget: concept=%s n_sections=%d profile=%s/%s max_tokens=%d",
            session.concept_id, n_sections,
            card_profile.speed, card_profile.comprehension, adaptive_max_tokens,
        )

        # Extract concept overview for per-section context
        concept_overview = concept_text[:400].rstrip() + ("..." if len(concept_text) > 400 else "")

        # FAST mode: merge consecutive TRY_IT sections into TRY_IT_BATCH before sending to LLM
        if _generate_as == "FAST":
            sub_sections = self._batch_consecutive_try_its(sub_sections)
            batch_count = sum(1 for s in sub_sections if s.get("section_type") == "TRY_IT_BATCH")
            if batch_count:
                logger.info("[fast-batch] concept=%s try_it_batches=%d total_sections=%d",
                            session.concept_id, batch_count, len(sub_sections))
            sub_sections = self._batch_consecutive_properties(sub_sections)
            prop_batch_count = sum(1 for s in sub_sections if s.get("section_type") == "PROPERTY_BATCH")
            if prop_batch_count:
                logger.info("[fast-batch] concept=%s property_batches=%d total_sections=%d",
                            session.concept_id, prop_batch_count, len(sub_sections))

        # Initialize concept/image tracking for coverage context
        concepts_covered: list[str] = []
        images_used_this_section: list[str] = []
        concept_index = 0

        # Per-section parallel generation (complete coverage, no content loss)
        all_raw_cards = await self._generate_cards_per_section(
            system_prompt=system_prompt,
            concept_title=concept_title,
            concept_overview=concept_overview,
            sections=sub_sections,
            latex=latex,
            images=useful_images,
            max_tokens_per_section=adaptive_max_tokens,
            per_section_floor=per_section_floor,
            concept_index=concept_index,
            concepts_covered=concepts_covered,
            images_used_this_section=images_used_this_section,
            generate_as=_generate_as,
            blended_score=_blended_score,
        )

        # Update tracking after main generation
        concept_index += len(sub_sections)
        concepts_covered.extend(s["title"] for s in sub_sections)
        for card in all_raw_cards:
            if card.get("images"):
                for img in card["images"]:
                    fname = img.get("filename") or img.get("file")
                    if fname and fname not in images_used_this_section:
                        images_used_this_section.append(fname)

        # Build section title order before gap-fill so actual_pos lookup is available.
        _section_order_titles = [s["title"] for s in sub_sections]

        # Gap-fill pass: detect and regenerate any section that produced no card
        missing = self._find_missing_sections(all_raw_cards, sub_sections)
        if missing:
            logger.warning(
                "[card-gen] gap-fill: %d sections missing: %s",
                len(missing), [s["title"] for s in missing],
            )
            for missing_section in missing:
                actual_pos = (
                    _section_order_titles.index(missing_section["title"])
                    if missing_section["title"] in _section_order_titles
                    else len(_section_order_titles)
                )
                section_cards = await self._generate_cards_per_section(
                    system_prompt=system_prompt,
                    concept_title=concept_title,
                    concept_overview=concept_overview,
                    sections=[missing_section],
                    latex=latex,
                    images=useful_images,
                    max_tokens_per_section=per_section_floor,
                    per_section_floor=per_section_floor,
                    concept_index=concept_index,
                    concepts_covered=concepts_covered,
                    images_used_this_section=images_used_this_section,
                    generate_as=_generate_as,
                    blended_score=_blended_score,
                )
                for card in section_cards:
                    card["_section_index"] = actual_pos
                all_raw_cards.extend(section_cards)

        # Post-generation validation: infer missing section_ids, deduplicate, and re-sort.
        # Build section_order from sub_section titles (used as stable section identifiers here).
        # NOTE: validate_and_repair_cards runs FIRST (fuzzy section assignment), then integer
        # _section_index sort runs SECOND so curriculum order is always the final authority.
        all_raw_cards, _still_missing = validate_and_repair_cards(
            all_raw_cards,
            section_order=_section_order_titles,
            required_sections=None,  # gap-fill pass above already handled re-gen; just repair
        )
        # RC4: Re-sort all_raw_cards to restore curriculum section order after gap-fill append.
        # Sort by section index only — preserve textbook order within each section
        all_raw_cards.sort(key=lambda c: (
            c.get("_section_index", len(sub_sections)),
            _CARD_TYPE_ORDER.get(c.get("card_type") or "", 5),
        ))
        # Remove cards with empty title or content — prevents blank card renders
        all_raw_cards = [
            c for c in all_raw_cards
            if c.get("title", "").strip() and c.get("content", "").strip()
        ]

        # Missed-image cleanup: attach any unassigned useful_image to the card whose
        # content has the most word overlap with the image description.
        # Ensures zero image loss — content-based matching, not random assignment.
        if useful_images:
            _assigned_fnames: set[str] = {
                img.get("filename") or img.get("file", "")
                for card in all_raw_cards
                for img in card.get("images", [])
            }
            for _img in useful_images:
                _fname = _img.get("filename") or _img.get("file", "")
                if _fname in _assigned_fnames or not _fname:
                    continue
                _desc_words = set((_img.get("description") or "").lower().split())
                if not _desc_words:
                    continue
                _best_card = None
                _best_score = 0
                for _card in all_raw_cards:
                    _content_words = set(_card.get("content", "").lower().split())
                    _score = len(_desc_words & _content_words)
                    if _score > _best_score:
                        _best_score = _score
                        _best_card = _card
                if _best_card is not None and _best_score > 0:
                    _best_card.setdefault("images", []).append(_img)
                    _assigned_fnames.add(_fname)

        if _still_missing:
            logger.warning(
                "[card-validate] session=%s sections still uncovered after gap-fill: %s",
                str(session.id), _still_missing,
            )

        cards_data = {"cards": all_raw_cards}
        raw_cards = cards_data.get("cards", [])

        # 7. Post-process: validate unified schema, normalise question, strip HTML wrappers
        import re as _re
        for ci, card in enumerate(raw_cards):
            card["index"] = ci
            # Strip any <markdown>...</markdown> wrapper the LLM may emit
            content = card.get("content", "")
            content = _re.sub(r"</?markdown>", "", content, flags=_re.IGNORECASE).strip()
            card["content"] = content
            # Forward difficulty from LLM response; fall back to 3 (medium) if absent or None
            if card.get("difficulty") is None:
                card["difficulty"] = 3
            else:
                try:
                    card["difficulty"] = int(card["difficulty"])
                except (TypeError, ValueError):
                    card["difficulty"] = 3

            # Validate and normalise the unified MCQ question field
            q = card.get("question")
            if q is None:
                # Accept backward-compat: old sessions may store quick_check
                q = card.get("quick_check")
                if isinstance(q, dict):
                    # Remap quick_check shape → question shape
                    q = {
                        "text": q.get("question", ""),
                        "options": q.get("options", []),
                        "correct_index": q.get("correct_index", 0),
                        "explanation": q.get("explanation", ""),
                    }
            if isinstance(q, dict):
                opts = q.get("options", [])
                if not isinstance(opts, list) or len(opts) != 4:
                    logger.warning(
                        "[card-schema] session=%s card=%d: question.options invalid "
                        "(got %s) — nullifying question",
                        str(session.id), ci, len(opts) if isinstance(opts, list) else type(opts).__name__,
                    )
                    card["question"] = None
                else:
                    ci_val = q.get("correct_index", 0)
                    if not isinstance(ci_val, int) or ci_val < 0 or ci_val >= len(opts):
                        logger.warning(
                            "[card-schema] session=%s card=%d: correct_index %s out of range — clamping to 0",
                            str(session.id), ci, ci_val,
                        )
                        ci_val = 0
                    card["question"] = {
                        "text": str(q.get("text", q.get("question", ""))),
                        "options": [str(o) for o in opts],
                        "correct_index": ci_val,
                        "explanation": str(q.get("explanation", "")),
                    }
            else:
                card["question"] = None

            # ---- Validate and normalise question2 ----
            q2 = card.get("question2")
            if isinstance(q2, dict):
                opts2 = q2.get("options", [])
                if not isinstance(opts2, list) or len(opts2) != 4:
                    logger.warning(
                        "[card-schema] session=%s card=%d '%s': question2.options invalid — will use question fallback",
                        str(session.id), ci, card.get("title", "?"),
                    )
                    card["question2"] = None
                else:
                    ci2 = q2.get("correct_index", 0)
                    if not isinstance(ci2, int) or not (0 <= ci2 < len(opts2)):
                        ci2 = 0
                    card["question2"] = {
                        "text": str(q2.get("text") or q2.get("question") or ""),
                        "options": [str(o) for o in opts2],
                        "correct_index": ci2,
                        "explanation": str(q2.get("explanation", "")),
                    }
            else:
                card["question2"] = None

            # Fallback: if question2 still null but question is valid, copy question as fallback
            if card.get("question2") is None and isinstance(card.get("question"), dict):
                card["question2"] = dict(card["question"])
                logger.warning(
                    "[card-schema] session=%s card=%d '%s': question2 missing from LLM — using question as fallback",
                    str(session.id), ci, card.get("title", "?"),
                )

            # Apply math sanitization: wrap bare LaTeX commands and balance $ signs
            if card.get("content"):
                card["content"] = _sanitize_math(card["content"])
            if card.get("question"):
                q = card["question"]
                if q.get("text"):
                    q["text"] = _sanitize_math(q["text"])
                if q.get("options"):
                    q["options"] = [_sanitize_math(o) if isinstance(o, str) else o for o in q["options"]]

            # Ensure image_indices is a list (LLM may omit it)
            if not isinstance(card.get("image_indices"), list):
                card["image_indices"] = []

            # Initialise empty images list; index-based resolution below
            card["images"] = []

        # 7c. Insert mid-session check-in cards at every CARDS_MID_SESSION_CHECK_INTERVAL position
        # e.g., after card index 11 (0-based), 23, 35 ... (every 12 cards)
        if CARDS_MID_SESSION_CHECK_INTERVAL > 0 and len(raw_cards) >= CARDS_MID_SESSION_CHECK_INTERVAL:
            cards_with_checkins = []
            for i, card in enumerate(raw_cards):
                cards_with_checkins.append(card)
                # Insert check-in after every Nth card (0-based: after index N-1, 2N-1, ...)
                if (i + 1) % CARDS_MID_SESSION_CHECK_INTERVAL == 0 and (i + 1) < len(raw_cards):
                    checkin = build_mid_session_checkin_card()
                    checkin["index"] = len(cards_with_checkins)
                    cards_with_checkins.append(checkin)
            # Re-index all cards after insertion
            for new_ci, card in enumerate(cards_with_checkins):
                card["index"] = new_ci
            raw_cards = cards_with_checkins

        # ── Index-based image assignment (trusts LLM's topic-relevant image_indices) ──
        # The LLM receives a numbered list of image descriptions and assigns each image
        # to the most topically relevant card via image_indices. We use those assignments
        # directly instead of overriding with positional/round-robin heuristics.
        if useful_images:
            import re as _re_img
            assigned_global: set[int] = set()
            for card in raw_cards:
                card.setdefault("images", [])
                image_indices = card.pop("image_indices", []) or []
                if not isinstance(image_indices, list):
                    image_indices = []

                # Build global→local index map and populate card.images — limit to max 1 image per card
                global_to_local: dict[int, int] = {}
                for global_idx in image_indices:
                    if (
                        isinstance(global_idx, int)
                        and 0 <= global_idx < len(useful_images)
                    ):
                        img_copy = dict(useful_images[global_idx])
                        img_copy["caption"] = (
                            img_copy.get("description")
                            or f"Diagram for: {card.get('title', '')}"
                        )
                        global_to_local[global_idx] = len(card["images"])
                        card["images"].append(img_copy)
                        assigned_global.add(global_idx)

                # Remap [IMAGE:N] markers in content: global index → local card.images index
                # so frontend lookup card.images[N] returns the correct image object.
                def _remap(m, g2l=global_to_local):
                    n = int(m.group(1))
                    return f"[IMAGE:{g2l[n]}]" if n in g2l else ""

                card["content"] = _re_img.sub(
                    r"\[IMAGE:(\d+)\]", _remap, card.get("content", "")
                )

            # RC5: Keyword-based fallback image assignment for VISUAL cards that the LLM
            # did not assign any images to (LLM skips [IMAGE:N] markers ~30% of the time).
            unassigned = [
                (i, img) for i, img in enumerate(useful_images)
                if i not in assigned_global
            ]
            for card in raw_cards:
                if card.get("images"):
                    continue  # Already has an image — skip
                if not unassigned:
                    break     # No more images to distribute
                # Use unassigned pool if available, otherwise allow sharing an already-assigned image
                pool = unassigned if unassigned else list(enumerate(useful_images))
                if not pool:
                    continue
                card_text = (card.get("title", "") + " " + card.get("content", "")).lower()
                best_score, best_pool_idx = -1, 0
                for pool_idx, (global_idx, img) in enumerate(pool):
                    desc = (img.get("description") or "").lower()
                    score = sum(1 for w in card_text.split() if len(w) > 3 and w in desc)
                    if score > best_score:
                        best_score, best_pool_idx = score, pool_idx
                global_idx, img = pool[best_pool_idx]
                min_score = 1 if card.get("card_type") == "VISUAL" else 2
                if best_score < min_score:
                    continue
                img_copy = dict(img)
                img_copy["caption"] = img.get("description") or f"Diagram: {card.get('title', '')}"
                card["images"] = [img_copy]
                if unassigned:
                    unassigned.pop(best_pool_idx)
                    assigned_global.add(global_idx)
                logger.info(
                    "[image-fallback] card '%s' (type=%s) assigned image %d via keyword fallback (score=%d)",
                    card.get("title", ""), card.get("card_type", ""), global_idx, best_score,
                )
        else:
            for card in raw_cards:
                card.pop("image_indices", None)
                card.setdefault("images", [])

        cards_with_images = sum(1 for c in raw_cards if c.get("images"))
        logger.info(
            "[cards-generated] session=%s concept=%s cards=%d with_images=%d",
            str(session.id), session.concept_id, len(raw_cards), cards_with_images,
        )

        # Save assigned image indices so rolling generation can exclude already-used images
        assigned_global = {
            idx
            for card in raw_cards
            for idx in (card.get("image_indices") or [])
            if isinstance(idx, int)
        }
        # Fallback: also collect indices from cards that received images via fallback assignment
        # by checking which useful_images are present in card["images"] by description match
        for gi, img in enumerate(useful_images):
            for card in raw_cards:
                if card.get("images") and any(
                    i.get("description") == img.get("description") for i in card["images"]
                ):
                    assigned_global.add(gi)

        result = {
            "session_id": str(session.id),
            "concept_id": session.concept_id,
            "concept_title": concept_title,
            "style": session.style,
            "phase": session.phase,
            "cards": raw_cards,
            "total_questions": 0,  # Retained for API compat; no longer a meaningful count
            "cache_version": _CARDS_CACHE_VERSION,
            "concepts_queue": concepts_queue,                          # remaining sub-sections
            "concepts_covered": [s["title"] for s in sub_sections],   # covered so far
            "concepts_total": len(all_sub_sections),                   # total count
            "needs_review": [],                                        # double-fail recovery tracking
            "system_prompt": system_prompt,                            # needed by generate_next_section_cards()
            "_images": useful_images,                                  # resolved images for rolling generation
            "assigned_image_indices": list(assigned_global),          # indices already used in initial batch
        }

        # 8. Cache and save messages
        session.presentation_text = json.dumps(result)
        msg_count = await self._get_message_count(db, session.id)
        await self._save_message(db, session.id, "system", system_prompt, "PRESENTING", msg_count)
        await self._save_message(db, session.id, "user", user_prompt, "PRESENTING", msg_count + 1)
        await self._save_message(db, session.id, "assistant", json.dumps(cards_data), "PRESENTING", msg_count + 2)

        await db.flush()
        return result

    async def generate_next_section_cards(
        self,
        db: AsyncSession,
        session: "TeachingSession",
        student,
        signals,  # NextSectionCardsRequest
    ) -> dict:
        """Pop next sub-section from concepts_queue, generate cards with live-signal mode, append to session.

        Returns a dict suitable for constructing NextSectionCardsResponse.
        """
        _raw_cache = json.loads(session.presentation_text or "{}")
        cached = _raw_cache if isinstance(_raw_cache, dict) else {}
        concepts_queue = list(cached.get("concepts_queue", []))
        concepts_covered = list(cached.get("concepts_covered", []))
        all_sub_sections_count = cached.get("concepts_total", 1)

        if not concepts_queue:
            return {
                "cards": [],
                "has_more_concepts": False,
                "concepts_total": all_sub_sections_count,
                "concepts_covered_count": len(concepts_covered),
                "current_mode": "NORMAL",
            }

        next_section = concepts_queue.pop(0)

        # Build blended analytics from accumulated session signals
        session_signals = list(cached.get("session_signals", []))
        session_signals.append({
            "card_index": signals.card_index,
            "time_on_card_sec": signals.time_on_card_sec,
            "wrong_attempts": signals.wrong_attempts,
            "hints_used": signals.hints_used,
        })

        # Determine adaptive mode via the same blended analytics path used in generate_cards()
        from adaptive.adaptive_engine import load_student_history, build_blended_analytics
        from adaptive.profile_builder import build_learning_profile
        from adaptive.schemas import AnalyticsSummary, CardBehaviorSignals

        _current_mode = "NORMAL"
        _per_section_floor = CARDS_MAX_TOKENS_NORMAL_PER_SECTION
        _blended_score: float = 2.0
        _generate_as: str = "NORMAL"
        blended = None
        try:
            history = await load_student_history(str(session.student_id), session.concept_id, db)
            # Use exponential recency-weighted aggregation of all session signals
            # so that a recovery event (high wrong_attempts) doesn't snap back to NORMAL
            # immediately on the next section.
            if len(session_signals) == 1:
                agg_time = session_signals[0]["time_on_card_sec"]
                agg_wrong = float(session_signals[0]["wrong_attempts"])
            else:
                weights = [0.5 ** (len(session_signals) - 1 - i) for i in range(len(session_signals))]
                total_w = sum(weights)
                agg_time  = sum(s["time_on_card_sec"] * w for s, w in zip(session_signals, weights)) / total_w
                agg_wrong = sum(s["wrong_attempts"]   * w for s, w in zip(session_signals, weights)) / total_w

            current_signals = CardBehaviorSignals(
                card_index=session_signals[-1]["card_index"],
                time_on_card_sec=agg_time,
                wrong_attempts=round(agg_wrong),
                hints_used=session_signals[-1].get("hints_used", 0),
                idle_triggers=session_signals[-1].get("idle_triggers", 0),
            )
            blended, _blended_score, _generate_as = build_blended_analytics(
                current_signals, history,
                concept_id=session.concept_id,
                student_id=str(session.student_id),
            )
            profile = build_learning_profile(blended, has_unmet_prereq=False)
            _current_mode = profile.speed
            # Map profile.speed keys to _CARD_MODE_DELIVERY keys (SLOW is not a valid key)
            _generate_as = "STRUGGLING" if (_current_mode == "SLOW" or getattr(profile, 'comprehension', '') == "STRUGGLING") else _current_mode
            if _current_mode == "SLOW" or profile.comprehension == "STRUGGLING":
                _per_section_floor = CARDS_MAX_TOKENS_SLOW_PER_SECTION
            elif _current_mode == "FAST" and profile.comprehension == "STRONG":
                _per_section_floor = CARDS_MAX_TOKENS_FAST_PER_SECTION
            else:
                _per_section_floor = CARDS_MAX_TOKENS_NORMAL_PER_SECTION
        except Exception as exc:
            logger.warning(
                "[next-section] blended_analytics_failed: student_id=%s — defaulting to NORMAL: %s",
                session.student_id, exc,
            )

        system_prompt = cached.get("system_prompt", "")
        concept_title = cached.get("concept_title", "")
        latex: list = []  # LaTeX already embedded in section text from initial generation

        # Load image pool from cache (saved during initial generation)
        cached_images = cached.get("_images", [])
        already_assigned = set(cached.get("assigned_image_indices", []))
        available_images = cached_images  # full image pool available for every per-card section

        # Generate cards for this ONE sub-section
        new_raw_cards = await self._generate_cards_per_section(
            system_prompt=system_prompt,
            concept_title=concept_title,
            concept_overview="",
            sections=[next_section],
            latex=latex,
            images=available_images,
            max_tokens_per_section=_per_section_floor,
            per_section_floor=_per_section_floor,
            generate_as=_generate_as,
            blended_score=_blended_score,
        )

        # Remove cards with empty title or content — prevents blank card renders
        new_raw_cards = [
            c for c in new_raw_cards
            if c.get("title", "").strip() and c.get("content", "").strip()
        ]

        # Track newly assigned images for future rolling calls
        new_assigned = {
            idx
            for card in new_raw_cards
            for idx in (card.get("image_indices") or [])
            if isinstance(idx, int)
        }
        cached["assigned_image_indices"] = list(already_assigned | new_assigned)

        # Stamp absolute indices starting after the existing cached cards
        base_idx = len(cached.get("cards", []))
        for i, card in enumerate(new_raw_cards):
            card["_section_index"] = base_idx + i
            card["index"] = base_idx + i
            # Ensure required defaults
            card.setdefault("images", [])
            card.setdefault("image_indices", [])
            if card.get("difficulty") is None:
                card["difficulty"] = 3
            else:
                try:
                    card["difficulty"] = int(card["difficulty"])
                except (TypeError, ValueError):
                    card["difficulty"] = 3

        # Append to session cache
        cached_cards = list(cached.get("cards", []))
        cached_cards.extend(new_raw_cards)
        cached["cards"] = cached_cards
        cached["concepts_queue"] = concepts_queue
        concepts_covered.append(next_section.get("title", ""))
        cached["concepts_covered"] = concepts_covered
        cached["session_signals"] = session_signals
        session.presentation_text = json.dumps(cached)
        await db.flush()

        logger.info(
            "[next-section] session=%s section=%r new_cards=%d mode=%s remaining=%d",
            str(session.id), next_section.get("title", "?"),
            len(new_raw_cards), _current_mode, len(concepts_queue),
        )

        return {
            "cards": new_raw_cards,
            "has_more_concepts": len(concepts_queue) > 0,
            "concepts_total": all_sub_sections_count,
            "concepts_covered_count": len(concepts_covered),
            "current_mode": _current_mode,
            "learning_profile_summary": _build_learning_profile_summary(blended, _generate_as, _blended_score),
        }

    async def generate_per_card(
        self,
        db: AsyncSession,
        session: "TeachingSession",
        student,
        req,  # NextCardRequest
    ) -> dict:
        """Generate exactly one adaptive card for the next content piece in the session queue.

        Uses live signals from the completed card (req) to determine presentation mode
        (STRUGGLING / NORMAL / FAST) via build_blended_analytics(). Pops one piece from
        concepts_queue, generates a single card via build_next_card_prompt() + _chat(),
        appends it to the cache, and returns metadata for NextCardResponse.

        Returns card=None with has_more_concepts=False when the queue is exhausted.
        """
        import time as _time
        from adaptive.adaptive_engine import load_student_history, load_wrong_option_pattern, build_blended_analytics
        from adaptive.profile_builder import build_learning_profile
        from adaptive.generation_profile import build_generation_profile
        from adaptive.schemas import CardBehaviorSignals
        from adaptive.prompt_builder import build_next_card_prompt
        from adaptive.adaptive_engine import _clean_card_string_fields

        _t0 = _time.monotonic()

        # ── Step 1: Parse session cache ─────────────────────────────────────────
        try:
            _raw_cache = json.loads(session.presentation_text or "{}")
            cached = _raw_cache if isinstance(_raw_cache, dict) else {}
        except (json.JSONDecodeError, TypeError):
            logger.exception(
                "[per-card] cache_parse_failed: session_id=%s — returning has_more=False",
                session.id,
            )
            return {
                "session_id": str(session.id),
                "card": None,
                "has_more_concepts": False,
                "current_mode": "NORMAL",
                "concepts_covered_count": 0,
                "concepts_total": 1,
            }

        concepts_queue = list(cached.get("concepts_queue", []))
        concepts_covered = list(cached.get("concepts_covered", []))
        all_sections_count = cached.get("concepts_total", 1)

        # ── Step 2: Empty queue guard ────────────────────────────────────────────
        if not concepts_queue:
            logger.info(
                "[per-card] queue_empty: session_id=%s covered=%d total=%d",
                session.id, len(concepts_covered), all_sections_count,
            )
            return {
                "session_id": str(session.id),
                "card": None,
                "has_more_concepts": False,
                "current_mode": "NORMAL",
                "concepts_covered_count": len(concepts_covered),
                "concepts_total": all_sections_count,
            }

        # ── Step 3: Pop next content piece ───────────────────────────────────────
        next_piece = concepts_queue.pop(0)

        # ── Step 4: Load history + wrong-option pattern concurrently ─────────────
        _history_default = {
            "total_cards_completed": 0,
            "avg_time_per_card": None,
            "avg_wrong_attempts": None,
            "avg_hints_per_card": None,
            "sessions_last_7d": 0,
            "section_count": 0,
            "is_known_weak_concept": False,
            "failed_concept_attempts": 0,
            "trend_direction": "STABLE",
            "trend_wrong_list": [],
        }
        wrong_option_pattern = None
        try:
            history, wrong_option_pattern = await asyncio.gather(
                load_student_history(str(session.student_id), session.concept_id, db),
                load_wrong_option_pattern(str(session.student_id), session.concept_id, db),
            )
        except Exception as exc:
            logger.warning(
                "[per-card] history_load_failed: student_id=%s — using defaults: %s",
                session.student_id, exc,
            )
            history = _history_default

        # ── Step 5: Fix Bug 4 — increment section_count locally ──────────────────
        # This lets blend weights graduate within a session without a DB round-trip.
        history["section_count"] = history.get("section_count", 0) + 1

        # ── Step 6: Build blended analytics from live signals ────────────────────
        _blended_score: float = 2.0
        _generate_as: str = "NORMAL"
        blended = None
        card_profile = None
        try:
            current_signals = CardBehaviorSignals(
                card_index=req.card_index,
                time_on_card_sec=req.time_on_card_sec,
                wrong_attempts=req.wrong_attempts,
                hints_used=req.hints_used,
                idle_triggers=getattr(req, "idle_triggers", 0),
            )
            blended, _blended_score, _generate_as = build_blended_analytics(
                current_signals, history,
                concept_id=session.concept_id,
                student_id=str(session.student_id),
            )
            card_profile = build_learning_profile(blended, has_unmet_prereq=False)
        except Exception as exc:
            logger.warning(
                "[per-card] blended_analytics_failed: student_id=%s — defaulting to NORMAL: %s",
                session.student_id, exc,
            )

        if card_profile is None:
            # Fall back to a minimal profile
            from adaptive.schemas import AnalyticsSummary
            card_profile = build_learning_profile(
                AnalyticsSummary(
                    student_id=str(session.student_id),
                    concept_id=session.concept_id,
                    time_spent_sec=120.0,
                    expected_time_sec=120.0,
                    attempts=1,
                    wrong_attempts=0,
                    hints_used=0,
                    revisits=0,
                    recent_dropoffs=0,
                    skip_rate=0.0,
                ),
                has_unmet_prereq=False,
            )

        # ── Step 7: Resolve available images ─────────────────────────────────────
        cached_images = cached.get("_images", [])
        already_assigned = set(cached.get("assigned_image_indices", []))
        available_images_with_idx = [
            (i, img) for i, img in enumerate(cached_images) if i not in already_assigned
        ]
        available_images = [img for _, img in available_images_with_idx]
        content_piece_images = available_images[:3]   # cap at 3 images per card
        # Map: position in content_piece_images → original index in cached_images
        _cp_to_cached_idx = {
            pos: orig_idx
            for pos, (orig_idx, _) in enumerate(available_images_with_idx[:3])
        }

        # ── Step 8: Build generation profile ─────────────────────────────────────
        gen_profile = build_generation_profile(card_profile)

        # ── Step 9: Build piece-scoped concept_detail ────────────────────────────
        concept_detail_base = self._get_ksvc(session).get_concept_detail(session.concept_id) or {}
        piece_concept_detail = {
            **concept_detail_base,
            "text": next_piece.get("text", ""),
            "concept_title": next_piece.get("title", concept_detail_base.get("concept_title", "")),
        }

        # ── Step 10: Build prompts (Bug 6 fix — pass content_piece_images) ───────
        language = getattr(student, "preferred_language", "en") or "en"
        system_prompt, user_prompt = build_next_card_prompt(
            concept_detail=piece_concept_detail,
            learning_profile=card_profile,
            gen_profile=gen_profile,
            card_index=req.card_index,
            history=history,
            language=language,
            wrong_option_pattern=wrong_option_pattern,
            difficulty_bias=None,
            generate_as=_generate_as,
            blended_state_score=_blended_score,
            content_piece_images=content_piece_images if content_piece_images else None,
        )

        # ── Step 11: Call LLM ──────────────────────────────────────────────────
        raw = await self._chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=NEXT_CARD_MAX_TOKENS,
            model="mini",
            timeout=30.0,
        )

        # ── Step 12: Parse + validate card ────────────────────────────────────
        cleaned = self._extract_json_block(raw)
        cleaned = _fix_latex_backslashes(cleaned)

        parsed: dict | None = None
        for attempt_raw in (cleaned, _clean_salvage(cleaned)):
            if attempt_raw is None:
                continue
            try:
                result = json.loads(attempt_raw)
                if isinstance(result, dict):
                    parsed = result
                    break
            except json.JSONDecodeError:
                pass

        if parsed is None:
            # Last resort: json_repair
            try:
                from json_repair import repair_json
                parsed = json.loads(repair_json(cleaned))
            except Exception:
                pass

        if parsed is None or not isinstance(parsed, dict):
            raise ValueError(
                f"[per-card] LLM output could not be parsed. Raw (first 300): {raw[:300]}"
            )

        parsed = _clean_card_string_fields(parsed)

        # Normalise to LessonCard shape
        card_position = len(cached.get("cards", []))
        card_dict = _normalise_per_card(parsed, card_index=card_position)

        # ── Step 13: Resolve image_indices from per-card LLM response ────────
        new_assigned: set[int] = set()
        image_indices = parsed.get("image_indices") or []
        resolved_images = []
        for idx in image_indices:
            if 0 <= idx < len(content_piece_images):
                img = dict(content_piece_images[idx])
                img.setdefault("caption", img.get("description", ""))
                resolved_images.append(img)
                # Track the original cached_images index so it is not re-assigned
                orig_idx = _cp_to_cached_idx.get(idx)
                if orig_idx is not None:
                    new_assigned.add(orig_idx)
                break  # max 1 image per card
        card_dict["images"] = resolved_images

        # ── Step 14: Update cache and flush ──────────────────────────────────
        cached["concepts_queue"] = concepts_queue
        cached["concepts_covered"] = concepts_covered + [next_piece.get("title", "")]
        cached_cards = list(cached.get("cards", []))
        cached_cards.append(card_dict)
        cached["cards"] = cached_cards
        cached["assigned_image_indices"] = list(already_assigned | new_assigned)
        session.presentation_text = json.dumps(cached)
        await db.flush()

        # ── Step 15: Optional — persist section_count increment to DB ────────
        try:
            from sqlalchemy import update as _sa_update
            from db.models import Student as _Student
            await db.execute(
                _sa_update(_Student)
                .where(_Student.id == session.student_id)
                .values(section_count=_Student.section_count + 1)
            )
        except Exception:
            logger.warning(
                "[per-card] section_count_persist_failed: student_id=%s",
                session.student_id,
            )

        # ── Step 16: Build and return result ─────────────────────────────────
        current_mode = {
            "STRUGGLING": "SLOW",
            "NORMAL": "NORMAL",
            "FAST": "FAST",
        }.get(_generate_as, "NORMAL")

        duration_ms = int((_time.monotonic() - _t0) * 1000)
        logger.info(
            "[per-card] generated: session_id=%s student_id=%s concept_id=%s "
            "section_count=%d generate_as=%s duration_ms=%d remaining_queue=%d",
            session.id, session.student_id, session.concept_id,
            history.get("section_count", 0), _generate_as, duration_ms, len(concepts_queue),
        )

        return {
            "session_id": str(session.id),
            "card": card_dict,
            "has_more_concepts": len(concepts_queue) > 0,
            "current_mode": current_mode,
            "concepts_covered_count": len(concepts_covered) + 1,
            "concepts_total": all_sections_count,
        }

    async def complete_card_interaction(
        self, db: AsyncSession, session, student, req
    ) -> dict:
        """Record card interaction, optionally generate recovery card, return learning profile."""
        from adaptive.adaptive_engine import (
            generate_recovery_card, load_student_history,
            build_blended_analytics,
        )
        from adaptive.schemas import CardBehaviorSignals
        import uuid as _uuid
        from datetime import datetime, timezone

        # 1. Record CardInteraction to DB
        interaction = CardInteraction(
            id=_uuid.uuid4(),
            session_id=session.id,
            student_id=student.id,
            concept_id=session.concept_id,
            card_index=req.card_index,
            time_on_card_sec=req.time_on_card_sec,
            wrong_attempts=req.wrong_attempts,
            selected_wrong_option=getattr(req, "selected_wrong_option", None),
            hints_used=req.hints_used,
            idle_triggers=req.idle_triggers,
            adaptation_applied="recovery" if (req.wrong_attempts >= 2 and req.re_explain_card_title) else None,
            completed_at=datetime.now(timezone.utc),
        )
        db.add(interaction)
        await db.flush()

        # 2. Compute learning profile summary
        history = await load_student_history(str(student.id), session.concept_id, db)
        current_signals = CardBehaviorSignals(
            card_index=req.card_index,
            time_on_card_sec=req.time_on_card_sec,
            wrong_attempts=req.wrong_attempts,
            hints_used=req.hints_used,
            idle_triggers=req.idle_triggers,
        )
        summary, blended_score, generate_as = build_blended_analytics(
            current_signals, history, session.concept_id, str(student.id)
        )
        learning_profile_summary = _build_learning_profile_summary(summary, generate_as, blended_score)

        # 3. Generate recovery card if needed
        recovery_card = None
        if req.wrong_attempts >= 2 and req.re_explain_card_title:
            cached = json.loads(session.presentation_text or "{}")
            seen_titles = cached.get("concepts_covered", [])
            ksvc = self._get_ksvc(session)
            try:
                recovery_card = await generate_recovery_card(
                    topic_title=req.re_explain_card_title,
                    concept_id=session.concept_id,
                    knowledge_svc=ksvc,
                    llm_client=self.openai,
                    language=getattr(student, "preferred_language", "en") or "en",
                    interests=getattr(student, "interests", None),
                    style=getattr(session, "style", None) or "default",
                    seen_titles=seen_titles,
                    wrong_question=req.wrong_question,
                    wrong_answer_text=req.wrong_answer_text,
                )
            except Exception:
                logger.exception("[complete_card] recovery card generation failed")
                recovery_card = None

        return {
            "recovery_card": recovery_card,
            "learning_profile_summary": learning_profile_summary,
            "motivational_note": None,
            "adaptation_applied": "recovery" if recovery_card else None,
        }

    async def _generate_cards_single(
        self, system_prompt: str, user_prompt: str, max_tokens: int = 12000
    ) -> dict:
        """Generate all cards in a single LLM call (primary model)."""
        # Increased floor (120s) and adjusted coefficient (/80 instead of /100)
        # to account for larger system prompt (~3000 tokens) processing overhead.
        card_timeout = max(120.0, max_tokens / 80.0 + 30.0)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        cards_data = None
        last_error = None
        for attempt in range(3):
            try:
                raw_json = await self._chat(messages=messages, max_tokens=max_tokens, timeout=card_timeout, model="mini")
            except ValueError:
                last_error = ValueError("LLM returned empty response")
                logger.warning("[cards-single] Empty response (attempt %d)", attempt + 1)
                continue
            raw_json = self._extract_json_block(raw_json)
            safe_json = _fix_latex_backslashes(raw_json)
            try:
                cards_data = json.loads(safe_json)
                break
            except json.JSONDecodeError as e:
                last_error = e
                # Try json_repair first — handles unescaped quotes, bad escapes, truncation
                try:
                    from json_repair import repair_json
                    repaired = json.loads(repair_json(safe_json))
                    if isinstance(repaired, dict) and "cards" in repaired and repaired["cards"]:
                        cards_data = repaired
                        logger.info("[cards-single] JSON repaired via json_repair (attempt %d)", attempt + 1)
                        break
                except Exception as repair_exc:
                    logger.debug("[cards-single] json_repair failed: %s", repair_exc)
                salvaged = self._salvage_truncated_json(raw_json)
                if salvaged is not None:
                    cards_data = salvaged
                    break
                logger.warning("[cards-single] JSON parse failed (attempt %d): %s", attempt + 1, e)
        if cards_data is None:
            raise ValueError(f"AI returned invalid JSON for cards: {last_error}")
        return cards_data

    async def _generate_cards_per_section(
        self,
        system_prompt: str,
        concept_title: str = "",
        concept_overview: str = "",
        sections: list[dict] = None,
        latex: list[str] = None,
        images: list[dict] = None,
        max_tokens_per_section: int = 4000,
        per_section_floor: int = 4_500,
        concept_index: int = 0,
        concepts_covered: list[str] | None = None,
        images_used_this_section: list[str] | None = None,
        generate_as: str = "NORMAL",
        blended_score: float = 2.0,
    ) -> list[dict]:
        """
        Generate cards for each section in a separate LLM call, all in parallel.
        Each call receives the section's full untruncated text plus concept context.
        Results are merged in section order.
        """

        async def generate_for_section(idx: int, sec: dict) -> tuple[int, list[dict]]:
            section_user_prompt = build_cards_user_prompt(
                concept_title=concept_title,
                sub_sections=[sec],
                latex=latex,
                images=images,
                concept_overview=concept_overview,
                section_position=f"section {idx + 1} of {len(sections)}",
                concept_index=concept_index + idx,
                concepts_remaining=len(sections) - idx - 1,
                concepts_covered=concepts_covered,
                blended_score=blended_score,
                generate_as=generate_as,
                images_used_this_section=images_used_this_section,
            )
            try:
                text_len = len(sec.get("text", ""))
                # Budget = max(profile floor, half the input text length).
                # This ensures rich section text drives a proportionally larger budget
                # while the profile floor guarantees adequate room for SLOW/NORMAL/FAST learners.
                text_driven_budget = max(per_section_floor, text_len // 2)
                data = await self._generate_cards_single(
                    system_prompt, section_user_prompt, max_tokens=text_driven_budget
                )
                generated_cards = data.get("cards", [])
                # Stamp stable integer section index so sort is O(n) and text-free.
                for card in generated_cards:
                    card["_section_index"] = idx
                # Collect image filenames used in returned cards for tracking
                for card in generated_cards:
                    if isinstance(card.get("images"), list):
                        for img in card["images"]:
                            fname = img.get("filename") or img.get("file")
                            if fname and images_used_this_section is not None and fname not in images_used_this_section:
                                images_used_this_section.append(fname)
                return idx, generated_cards
            except Exception as exc:
                logger.warning(
                    "[card-gen] section %d (%s) failed: %s",
                    idx, sec.get("title", "?"), exc,
                )
                return idx, []

        results = await asyncio.gather(
            *(generate_for_section(i, sec) for i, sec in enumerate(sections))
        )

        all_cards: list[dict] = []
        for _, cards in sorted(results, key=lambda x: x[0]):
            all_cards.extend(cards)
        # Secondary sort: within the same section index, enforce pedagogical card order
        all_cards.sort(key=lambda c: (
            c.get("_section_index", len(sections)),
            _CARD_TYPE_ORDER.get(c.get("card_type") or "", 5),
        ))
        return all_cards

    @staticmethod
    def _find_missing_sections(cards: list[dict], sections: list[dict]) -> list[dict]:
        """Return sections whose title does not appear in any card's title or content."""
        card_text = " ".join(
            (c.get("title") or "") + " " + (c.get("content") or "")
            for c in cards
        ).lower()
        return [s for s in sections if s["title"].lower() not in card_text]

    @staticmethod
    def _extract_json_block(raw: str) -> str:
        """Extract JSON from markdown code blocks if present."""
        if not raw:
            return raw
        if "```" in raw:
            m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
            if m:
                return m.group(1).strip()
        return raw

    @staticmethod
    def _parse_card_image_ref(text: str, card_visuals: list[dict]) -> tuple[str, dict | None]:
        """Strip [CARD:N] marker from AI response; return (cleaned_text, image_dict | None)."""
        m = re.search(r'\[CARD:(\d+)\]', text)
        if not m:
            return text, None
        idx = int(m.group(1))
        clean = re.sub(r'\s*\[CARD:\d+\]', '', text).strip()
        image = card_visuals[idx]["image"] if 0 <= idx < len(card_visuals) else None
        return clean, image

    async def handle_assist(
        self,
        db: AsyncSession,
        session: TeachingSession,
        card_index: int,
        message: str | None,
        trigger: str,
    ) -> str:
        """
        Handle AI assistant sidebar request during card-based learning.
        Returns the assistant's response text.
        """
        # Get card data from cache
        card_title = "the current topic"
        card_content = ""
        concept_title = session.concept_id

        if session.presentation_text:
            try:
                cached = json.loads(session.presentation_text)
                if isinstance(cached, dict):
                    concept_title = cached.get("concept_title", session.concept_id)
                    cards = cached.get("cards", [])
                elif isinstance(cached, list):
                    cards = cached
                else:
                    cards = []
                if 0 <= card_index < len(cards):
                    card_title = cards[card_index].get("title", card_title)
                    card_content = cards[card_index].get("content", "")
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass

        # Get student language
        student = await db.get(Student, session.student_id)
        language = getattr(student, "preferred_language", "en") or "en" if student else "en"

        # Build system prompt
        effective_interests = session.lesson_interests if session.lesson_interests else []
        system_prompt = build_assistant_system_prompt(
            concept_title=concept_title,
            card_title=card_title,
            card_content=card_content,
            style=session.style,
            interests=effective_interests,
            language=language,
        )

        # Get previous assistant messages
        result = await db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.session_id == session.id)
            .where(ConversationMessage.phase == "ASSISTING")
            .order_by(ConversationMessage.message_order)
        )
        prev_messages = list(result.scalars().all())

        # Build OpenAI messages — prune to last 4 non-system messages (2 exchanges)
        eligible = [m for m in prev_messages if m.role in ("user", "assistant")]
        pruned = eligible[-4:] if len(eligible) > 4 else eligible
        openai_messages = [{"role": "system", "content": system_prompt}]
        for m in pruned:
            openai_messages.append({"role": m.role, "content": m.content})

        # Add current message
        if trigger == "idle":
            user_text = (
                f"[The student has been on card '{card_title}' for a while "
                "and hasn't interacted. Gently check if they need help.]"
            )
        else:
            user_text = message or "Can you help me?"

        openai_messages.append({"role": "user", "content": user_text})

        # Call LLM for hints (uses gpt-4o-mini — cheaper for short nudges)
        ai_response = await self._chat(messages=openai_messages, max_tokens=400, model="mini")

        # Save messages
        msg_count = await self._get_message_count(db, session.id)
        if not prev_messages:
            await self._save_message(db, session.id, "system", system_prompt, "ASSISTING", msg_count)
            msg_count += 1
        await self._save_message(db, session.id, "user", user_text, "ASSISTING", msg_count)
        await self._save_message(db, session.id, "assistant", ai_response, "ASSISTING", msg_count + 1)

        await db.flush()
        return ai_response

    async def complete_cards(
        self,
        db: AsyncSession,
        session: TeachingSession,
    ) -> dict:
        """
        Transition session from CARDS to CARDS_DONE phase.
        Cards are gateways only — mastery is determined by the Socratic chat.
        """
        session.phase = "CARDS_DONE"
        await db.flush()
        return {"session_id": str(session.id), "phase": "CARDS_DONE"}

    # ── Remediation Card Generation ───────────────────────────────

    async def generate_remediation_cards(
        self,
        session_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[dict]:
        """
        Generate targeted re-teaching cards for topics the student struggled with.
        Uses TEACH + EXAMPLE + RECAP card types only — no QUESTION cards.
        """
        session = await db.get(TeachingSession, session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        failed_topics = json.loads(session.remediation_context or '["key concepts"]')
        concept = self._get_ksvc(session).get_concept_detail(session.concept_id)
        if not concept:
            raise ValueError(f"Concept not found: {session.concept_id}")
        student = await db.get(Student, session.student_id)

        system_prompt = self._build_remediation_cards_prompt(failed_topics, concept, student)
        concept_title = concept.get("concept_title", session.concept_id)
        user_prompt = (
            f"Generate remediation cards for concept: {concept_title}\n"
            f"Focus ONLY on these weak areas: {', '.join(failed_topics[:5])}\n"
            f"Generate TEACH and EXAMPLE cards with different explanations than the first time.\n"
            f"Use simpler vocabulary and shorter sentences than the first lesson.\n"
            f"Give a concrete real-world example BEFORE introducing any formula or symbol.\n"
            f"Assume the student found the original explanation difficult — make it genuinely easier.\n"
            f"End with one RECAP card summarizing the key points.\n"
            f"NO QUESTION cards in remediation — this is re-teaching, not testing.\n"
            f"Respond with valid JSON only."
        )

        raw_json = await self._chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=4000,
            temperature=0.7,
        )

        raw_json = self._extract_json_block(raw_json)
        try:
            cards_data = json.loads(raw_json)
        except json.JSONDecodeError:
            salvaged = self._salvage_truncated_json(raw_json)
            if salvaged is not None:
                cards_data = salvaged
            else:
                logger.error(
                    "[remediation-cards] JSON parse failed session_id=%s", str(session_id)
                )
                cards_data = {"cards": []}

        raw_cards = cards_data.get("cards", [])
        import re as _re
        for ci, card in enumerate(raw_cards):
            card["index"] = ci
            content = card.get("content", "")
            content = _re.sub(r"</?markdown>", "", content, flags=_re.IGNORECASE).strip()
            card["content"] = content
            card.setdefault("difficulty", 3)
            card.setdefault("image_indices", [])
            card.setdefault("images", [])

            # Validate and normalise unified MCQ question
            q = card.get("question")
            if q is None:
                # Backward compat: remediation prompt may return quick_check
                q = card.get("quick_check")
                if isinstance(q, dict):
                    q = {
                        "text": q.get("question", ""),
                        "options": q.get("options", []),
                        "correct_index": q.get("correct_index", 0),
                        "explanation": q.get("explanation", ""),
                    }
            if isinstance(q, dict):
                opts = q.get("options", [])
                if isinstance(opts, list) and len(opts) == 4:
                    ci_val = q.get("correct_index", 0)
                    if not isinstance(ci_val, int) or ci_val < 0 or ci_val >= 4:
                        ci_val = 0
                    card["question"] = {
                        "text": str(q.get("text", q.get("question", ""))),
                        "options": [str(o) for o in opts],
                        "correct_index": ci_val,
                        "explanation": str(q.get("explanation", "")),
                    }
                else:
                    card["question"] = None
            else:
                card["question"] = None

        logger.info(
            "[remediation-cards] session_id=%s cards_generated=%d",
            str(session_id), len(raw_cards),
        )
        return raw_cards

    def _build_remediation_cards_prompt(
        self,
        failed_topics: list[str],
        concept: dict,
        student,
    ) -> str:
        """Build the system prompt for remediation card generation."""
        interests = []
        if student:
            interests = getattr(student, "interests", []) or []
        language = getattr(student, "preferred_language", "en") or "en" if student else "en"

        failed_text = ", ".join(failed_topics[:5])
        interests_text = f"\nStudent interests: {', '.join(interests)}." if interests else ""

        return (
            f"You are a patient, encouraging tutor re-teaching specific topics a student found difficult.\n"
            f"The student struggled with: {failed_text}\n\n"
            f"Generate ONLY re-teaching cards and one final summary card.\n"
            f"Use COMPLETELY DIFFERENT explanations, analogies, and examples than before.\n"
            f"Keep language simple, warm, and encouraging — never make the student feel bad.\n"
            f"Every card MUST have a question (MCQ). No card_type, no quick_check, no questions[].\n"
            f"Output valid JSON with the cards array using this schema:\n"
            f'{{"cards": [{{"title": "...", "content": "...", "image_indices": [], '
            f'"question": {{"text": "...", "options": ["A","B","C","D"], '
            f'"correct_index": 0, "explanation": "..."}}}}]}}\n'
            f"{interests_text}"
        )

    # ── Recheck (after Remediation) ──────────────────────────────

    async def begin_recheck(
        self,
        session_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict:
        """
        Start a new Socratic check focused on previously failed topics.
        Transitions session to RECHECKING or RECHECKING_2 phase.
        """
        session = await db.get(TeachingSession, session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        failed_topics = json.loads(session.remediation_context or "[]")
        concept = self._get_ksvc(session).get_concept_detail(session.concept_id)
        if not concept:
            raise ValueError(f"Concept not found: {session.concept_id}")
        student = await db.get(Student, session.student_id)

        # Determine next phase based on attempt count
        if session.socratic_attempt_count == 1:
            session.phase = "RECHECKING"
        else:
            session.phase = "RECHECKING_2"

        effective_interests = (
            session.lesson_interests if session.lesson_interests
            else (getattr(student, "interests", []) or [] if student else [])
        )
        language = getattr(student, "preferred_language", "en") or "en" if student else "en"

        system_prompt = build_remediation_socratic_prompt(
            failed_topics=failed_topics,
            concept_title=concept.get("concept_title", session.concept_id),
            concept_text=concept.get("text", "")[:2000],
            student_interests=effective_interests,
            style=session.style or "default",
            language=language,
            session_stats={},
        )

        opening = await self._chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": "I've finished reviewing those parts again. I'm ready for the check!",
                },
            ],
            max_tokens=500,
            temperature=0.7,
            model="mini",
        )

        msg_count = await self._get_message_count(db, session.id)
        await self._save_message(db, session.id, "system", system_prompt, session.phase, msg_count)
        await self._save_message(
            db, session.id, "user",
            "I've finished reviewing those parts again. I'm ready for the check!",
            session.phase, msg_count + 1,
        )
        await self._save_message(db, session.id, "assistant", opening, session.phase, msg_count + 2)
        await db.flush()

        logger.info(
            "[recheck] session_id=%s phase=%s attempt=%d",
            str(session.id), session.phase, session.socratic_attempt_count,
        )

        return {
            "response": opening,
            "phase": session.phase,
            "attempt": session.socratic_attempt_count,
        }

    @staticmethod
    def _parse_sub_sections(text: str) -> list[dict]:
        """Split concept text by ## headers into sub-sections.

        Normalisation passes run before the ## split loop to handle the three
        header formats found across the supported OpenStax books:
          - prealgebra:           ## Title  (already markdown — no transform needed)
          - college_algebra:      \\section*{Title}  →  ## Title  (Pass 1)
          - elementary_algebra,
            intermediate_algebra,
            algebra_1:            EXAMPLE 1.5 / TRY IT / SOLUTION  →  ## …  (Pass 2)
        """
        # Pass 1 — LaTeX \section / \subsection  →  ## Title
        # Guard avoids regex cost on books that never contain backslash-section.
        if r'\section' in text:
            text = re.sub(r'\\(?:sub)?section\*?\{([^}]+)\}', r'## \1', text)

        # Pass 2 — bare ALLCAPS headers (OpenStax elementary/intermediate/algebra_1)
        lines = text.split('\n')
        normalised = []
        for line in lines:
            stripped = line.strip()
            if _ALLCAPS_SECTION_RE.fullmatch(stripped) and not stripped.startswith('## '):
                normalised.append(f'## {stripped}')
            else:
                normalised.append(line)
        text = '\n'.join(normalised)

        sections = []
        current_title = ""
        current_lines = []

        for line in text.split("\n"):
            if line.startswith("## "):
                # Save previous section
                if current_title or current_lines:
                    sections.append({
                        "title": current_title or "Introduction",
                        "text": "\n".join(current_lines).strip(),
                    })
                current_title = line[3:].strip()
                current_lines = []
            else:
                current_lines.append(line)

        # Save last section
        if current_title or current_lines:
            sections.append({
                "title": current_title or "Introduction",
                "text": "\n".join(current_lines).strip(),
            })

        # Filter out empty sections
        sections = [s for s in sections if s["text"]]

        # Pass 3 — Paragraph-level split for large non-example sections.
        # Threshold: 800 chars. EXAMPLE / SOLUTION / TRY_IT stay intact (worked examples
        # must not be broken across cards). All others are split at blank-line boundaries
        # so each sub-section fits within NEXT_CARD_MAX_TOKENS without truncation.
        _SPLIT_CHAR_THRESHOLD = 800
        _NO_SPLIT_TYPES = {"EXAMPLE", "SOLUTION", "TRY_IT"}
        expanded: list[dict] = []
        for sec in sections:
            stype = (sec.get("section_type") or "").upper()
            if stype in _NO_SPLIT_TYPES or len(sec["text"]) <= _SPLIT_CHAR_THRESHOLD:
                expanded.append(sec)
                continue
            paragraphs = [p.strip() for p in re.split(r'\n{2,}', sec["text"]) if p.strip()]
            if len(paragraphs) < 2:
                expanded.append(sec)
                continue
            # Pack paragraphs into budget-sized chunks
            chunks: list[list[str]] = []
            current: list[str] = []
            current_len = 0
            for para in paragraphs:
                if current_len + len(para) > _SPLIT_CHAR_THRESHOLD and current:
                    chunks.append(current)
                    current = []
                    current_len = 0
                current.append(para)
                current_len += len(para)
            if current:
                chunks.append(current)
            for k, chunk in enumerate(chunks):
                label = sec["title"] if k == 0 else f"{sec['title']} (Part {k + 1})"
                expanded.append({
                    "title": label,
                    "text": "\n\n".join(chunk),
                    "section_type": sec.get("section_type"),
                })
        sections = expanded

        return sections

    @staticmethod
    def _group_by_major_topic(sections: list[dict]) -> list[dict]:
        """
        Group sub-sections semantically: supporting content (examples, solutions,
        HOW TO steps, TRY IT exercises, etc.) is absorbed into its preceding major
        topic card. Each major topic becomes one card with all its supporting content
        included — nothing is dropped.

        Major topics: conceptual headings like "Model Whole Numbers", "Round Whole Numbers"
        Supporting content: EXAMPLE, Solution, TRY IT, HOW TO, Learning Objectives,
                            MANIPULATIVE MATHEMATICS, MEDIA, ACCESS ADDITIONAL..., etc.
        """
        import re
        _SUPPORT_HEADING = re.compile(
            r"^(example\b|solution\b|try it\b|how to\b|manipulative\b|media\b|"
            r"access\b|learning objectives\b|tip\b|note\b|be careful\b|"
            r"link to literacy\b|everyday math\b|writing exercises\b|"
            r"practice makes perfect\b|mixed practice\b|glossary\b|"
            r"key concepts\b|review exercises\b|practice test\b|\d+\.\d+|\(r\))",
            re.IGNORECASE,
        )

        groups: list[dict] = []

        for sec in sections:
            if _SUPPORT_HEADING.match(sec["title"]) and groups:
                # Supporting content — absorb into the preceding major topic
                groups[-1]["text"] += "\n\n" + sec["text"]
            else:
                # Major topic — start a new card
                groups.append({"title": sec["title"], "text": sec["text"]})

        return groups if groups else sections

    @staticmethod
    def _classify_sections(sections: list[dict]) -> list[dict]:
        """Classify each sub-section by its pedagogical type using regex patterns."""
        result = []
        for sec in sections:
            title_lower = sec["title"].lower().strip()
            sec_type = "CONCEPT"
            for pattern, stype in _SECTION_CLASSIFIER:
                if re.search(pattern, title_lower):
                    sec_type = stype
                    break
            result.append({**sec, "section_type": sec_type})
        return result

    @staticmethod
    def _build_textbook_blueprint(classified: list[dict]) -> list[dict]:
        """
        Ordered blueprint matching textbook pedagogical flow.
        SOLUTION → merged into preceding EXAMPLE.
        TIP → merged into preceding item.
        SUPPLEMENTARY / PREREQ_CHECK / END_MATTER → skipped.
        All others → independent blueprint items.
        """
        blueprint: list[dict] = []
        for sec in classified:
            stype = sec["section_type"]
            if stype in ("SUPPLEMENTARY", "PREREQ_CHECK", "END_MATTER"):
                continue
            elif stype == "SOLUTION" and blueprint:
                if blueprint[-1]["section_type"] == "EXAMPLE":
                    blueprint[-1]["text"] += "\n\n**Solution:**\n" + sec["text"]
                    continue
            elif stype == "TIP" and blueprint:
                blueprint[-1]["text"] += "\n\n> **Note:** " + sec["text"]
                continue
            blueprint.append({**sec})
        return blueprint

    @staticmethod
    def _batch_consecutive_try_its(
        sections: list[dict],
        max_batch: int = 4,
    ) -> list[dict]:
        """
        FAST mode only: merge runs of consecutive TRY_IT sections into a single TRY_IT_BATCH.
        Solo TRY_IT sections (run length = 1) are passed through unchanged.
        """
        result: list[dict] = []
        i = 0
        while i < len(sections):
            if sections[i].get("section_type") != "TRY_IT":
                result.append(sections[i])
                i += 1
                continue
            # Collect consecutive TRY_IT run
            batch: list[dict] = [sections[i]]
            while (
                i + len(batch) < len(sections)
                and sections[i + len(batch)].get("section_type") == "TRY_IT"
                and len(batch) < max_batch
            ):
                batch.append(sections[i + len(batch)])
            if len(batch) == 1:
                result.append(batch[0])
            else:
                first_title = batch[0]["title"]
                last_title  = batch[-1]["title"]
                merged_text = "\n\n".join(
                    f"({chr(97 + j)}) {s['title']}\n{s['text']}"
                    for j, s in enumerate(batch)
                )
                result.append({
                    "title": f"{first_title} – {last_title}",
                    "text":  merged_text,
                    "section_type": "TRY_IT_BATCH",
                })
            i += len(batch)
        return result

    @staticmethod
    def _batch_consecutive_properties(
        sections: list[dict],
        max_batch: int = 5,
    ) -> list[dict]:
        """
        FAST mode only: merge runs of consecutive CONCEPT sections whose titles
        contain property/rule keywords into a single PROPERTY_BATCH section.
        e.g., Zero Property + Identity Property + Commutative Property → 1 section.
        Solo sections (run length = 1) are passed through unchanged.
        """
        import re as _re2
        _PROP_TITLE = _re2.compile(
            r"\bproperty\b|\brule\b|\blaw\b|\bidentity\b|\bzero\b|\bcommutative\b"
            r"|\bassociative\b|\bdistributive\b",
            _re2.IGNORECASE,
        )
        result: list[dict] = []
        i = 0
        while i < len(sections):
            sec = sections[i]
            if sec.get("section_type") != "CONCEPT" or not _PROP_TITLE.search(sec.get("title", "")):
                result.append(sec)
                i += 1
                continue
            # Collect consecutive matching CONCEPT sections
            batch: list[dict] = [sec]
            while (
                i + len(batch) < len(sections)
                and sections[i + len(batch)].get("section_type") == "CONCEPT"
                and _PROP_TITLE.search(sections[i + len(batch)].get("title", ""))
                and len(batch) < max_batch
            ):
                batch.append(sections[i + len(batch)])
            if len(batch) == 1:
                result.append(batch[0])
            else:
                merged_text = "\n\n".join(
                    f"### {s['title']}\n{s['text']}" for s in batch
                )
                # Build a clean combined title: "Properties of Multiplication"
                first_title = batch[0]["title"]
                topic = first_title.split("Property")[0].split("property")[0].strip()
                result.append({
                    "title": f"Properties of {topic}" if topic else first_title,
                    "text": merged_text,
                    "section_type": "PROPERTY_BATCH",
                })
            i += len(batch)
        return result

    @staticmethod
    def _classify_section_type(concept_id: str, concept_title: str) -> str:
        """Return math domain type (TYPE_A–G) for domain-specific prompt rules."""
        # Normalize underscores and dots to spaces so \b word boundaries work on concept IDs
        raw = concept_id + " " + concept_title
        text = re.sub(r"[_.]", " ", raw).lower()
        for pattern, domain in _SECTION_DOMAIN_MAP:
            if re.search(pattern, text):
                return domain
        return "TYPE_A"

    @staticmethod
    def _salvage_truncated_json(raw: str):
        """Try to fix truncated JSON by closing open structures."""
        if not raw:
            return None
        # Find the last complete card object by looking for the pattern
        # Try progressively trimming from the end
        # First, try to find the last complete card in a "cards" array
        idx = raw.rfind('}')
        while idx > 0:
            candidate = raw[:idx+1]
            # Close any open arrays/objects
            open_brackets = candidate.count('[') - candidate.count(']')
            open_braces = candidate.count('{') - candidate.count('}')
            suffix = ']' * open_brackets + '}' * open_braces
            try:
                result = json.loads(candidate + suffix)
                if isinstance(result, dict) and "cards" in result:
                    return result
            except json.JSONDecodeError:
                pass
            idx = raw.rfind('}', 0, idx)
        return None

    @staticmethod
    def _build_windowed_messages(full_messages: list[dict]) -> list[dict]:
        """
        Trim conversation history to keep only: system prompt + first exchange + last 3 exchanges.
        Prevents input token blowup in long Socratic sessions.
        Each 'exchange' = one user + one assistant message pair.
        """
        if not full_messages:
            return full_messages

        # Separate system prompt from the rest
        system_msgs = [m for m in full_messages if m["role"] == "system"]
        non_system = [m for m in full_messages if m["role"] != "system"]

        # Build exchanges (pairs of user + assistant)
        exchanges = []
        i = 0
        while i < len(non_system):
            if non_system[i]["role"] == "user":
                pair = [non_system[i]]
                if i + 1 < len(non_system) and non_system[i + 1]["role"] == "assistant":
                    pair.append(non_system[i + 1])
                    i += 2
                else:
                    i += 1
                exchanges.append(pair)
            else:
                i += 1

        # Keep first exchange + last 3 exchanges (deduplicated)
        if len(exchanges) <= 4:
            kept = exchanges
        else:
            first = exchanges[:1]
            last3 = exchanges[-3:]
            kept = first + last3

        kept_msgs = [m for pair in kept for m in pair]
        return system_msgs + kept_msgs

    # ── Internal Helpers ──────────────────────────────────────────

    async def _save_message(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        role: str,
        content: str,
        phase: str,
        order: int,
    ):
        msg = ConversationMessage(
            session_id=session_id,
            role=role,
            content=content,
            phase=phase,
            message_order=order,
        )
        db.add(msg)

    async def _get_message_count(self, db: AsyncSession, session_id: uuid.UUID) -> int:
        result = await db.execute(
            select(func.count(ConversationMessage.id))
            .where(ConversationMessage.session_id == session_id)
        )
        return result.scalar_one()

    async def _get_phase_messages(
        self, db: AsyncSession, session_id: uuid.UUID, phase: str
    ) -> list[ConversationMessage]:
        """Return all messages for the given phase, ordered by message_order."""
        result = await db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.session_id == session_id)
            .where(ConversationMessage.phase == phase)
            .order_by(ConversationMessage.message_order)
        )
        return list(result.scalars().all())

    async def _extract_failed_topics(
        self, session_id: uuid.UUID, db: AsyncSession,
        covered_topics: list[str] | None = None,
    ) -> list[str]:
        """
        Extract topic keywords from wrong/partial answers in the Socratic check messages.
        Delegates to the static implementation after fetching ORM messages.
        """
        orm_messages = await self._get_checking_messages(db, session_id)
        # Convert ORM objects to plain dicts for the static analyser
        messages = [{"role": m.role, "content": m.content or ""} for m in orm_messages]
        return self._extract_failed_topics_from_messages(messages, covered_topics or [])

    @staticmethod
    def _extract_failed_topics_from_messages(
        messages: list[dict], covered_topics: list[str]
    ) -> list[str]:
        """
        Extract topics the student answered incorrectly by scanning for
        AI correction phrases paired with the preceding question.
        """
        CORRECTION_PHRASES = [
            "not quite", "not exactly", "actually,", "let me clarify",
            "the correct answer", "that's incorrect", "that is incorrect",
            "good try", "close, but", "almost, but", "let's revisit",
            "you said", "remember that", "recall that",
        ]
        failed: list[str] = []
        seen_keys: set[str] = set()
        last_assistant_msg = ""

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "") or ""
            content_lower = content.lower()

            if role == "assistant":
                # Check if this message contains a correction
                is_correction = any(phrase in content_lower for phrase in CORRECTION_PHRASES)
                if is_correction and last_assistant_msg:
                    # The previous assistant message was the question student got wrong
                    key = last_assistant_msg[:50]
                    if key not in seen_keys:
                        seen_keys.add(key)
                        # Extract just the question portion (first sentence ending with ?)
                        q_match = re.search(r'[^.!?]*\?', last_assistant_msg)
                        topic = q_match.group(0).strip() if q_match else last_assistant_msg[:100]
                        failed.append(topic)
                last_assistant_msg = content

        # Fallback: if no corrections detected, return empty list
        # (caller handles empty → uses covered_topics or generic message)
        return failed if failed else []

    async def regenerate_mcq(self, req: RegenerateMCQRequest) -> CardMCQ:
        """Generate a replacement MCQ after a wrong answer — same concept, different numbers/scenario."""
        system = (
            "You generate replacement MCQ questions for a K-12 math adaptive learning app. "
            "Generate ONE new multiple-choice question that tests the SAME concept as the previous "
            "question but uses DIFFERENT numbers, scenarios, and wording. "
            "The answer must NOT be directly stated verbatim in the card content. "
            "Return ONLY valid JSON (no markdown, no code block): "
            "{\"text\": \"...\", \"options\": [\"A\", \"B\", \"C\", \"D\"], "
            "\"correct_index\": 0, \"explanation\": \"...\"}"
        )
        user = (
            f"Card title: {req.card_title}\n"
            f"Card content:\n{req.card_content[:800]}\n\n"
            f"Previous question (do NOT reuse this exact question): {req.previous_question}\n\n"
            "Generate a new MCQ testing the same concept with different numbers or scenario."
        )
        try:
            response = await self._chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=300,
                model=OPENAI_MODEL_MINI,
                temperature=0.8,
            )
            raw = response.strip()
            # Strip markdown code blocks if present
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            data = json.loads(raw)
            return CardMCQ(**data)
        except Exception:
            logger.exception("regenerate_mcq failed, returning fallback")
            # Fallback: slightly rephrase the original question
            raise

    @staticmethod
    def _parse_assessment(text: str) -> tuple[bool, int | None]:
        """Check if AI included [ASSESSMENT:XX] marker."""
        match = re.search(r'\[ASSESSMENT:(\d+)\]', text)
        if match:
            return True, int(match.group(1))
        return False, None
