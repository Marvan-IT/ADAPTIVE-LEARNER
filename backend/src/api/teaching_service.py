"""
Teaching Service — The Pedagogical Loop.
Orchestrates the 2-step teaching flow:
  1. Presentation: metaphor-based explanation generated from RAG content
  2. Socratic Check: guided questioning to verify understanding (never gives answers)
"""

import asyncio
import base64
import json
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI

from config import (
    OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_MODEL_MINI,
    NEXT_CARD_MAX_TOKENS,
    CHUNK_MAX_TOKENS_STRUGGLING, CHUNK_MAX_TOKENS_NORMAL, CHUNK_MAX_TOKENS_FAST, CHUNK_MAX_TOKENS_RECOVERY,
)
from api.chunk_knowledge_service import ChunkKnowledgeService
from api.prompts import (
    build_presentation_system_prompt,
    build_presentation_user_prompt,
    build_cards_user_prompt,
    build_assistant_system_prompt,
    _language_instruction,
)
from db.models import TeachingSession, ConversationMessage, Student, CardInteraction, ConceptChunk
from api.teaching_schemas import CardMCQ, RegenerateMCQRequest

logger = logging.getLogger(__name__)

import re as _re  # noqa: E402

# Module-level constant — used by generate_per_chunk() and teaching_router.py
EXERCISE_HEADING_PATTERNS = (
    "exercises",
    "practice makes perfect",
    "everyday math",
    "writing exercises",
    "mixed practice",
    "practice test",
    "section exercises",
)


def _mode_from_chunk_score(score: int) -> str:
    """Map previous chunk MCQ score (0–100) to mode for next chunk."""
    if score >= 80:
        return "FAST"
    elif score >= 50:
        return "NORMAL"
    return "STRUGGLING"



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


def _coerce_difficulty(val) -> str:
    """Ensure difficulty is always a valid EASY/MEDIUM/HARD string."""
    if val in ("EASY", "MEDIUM", "HARD"):
        return val
    _int_map = {1: "EASY", 2: "EASY", 3: "MEDIUM", 4: "HARD", 5: "HARD"}
    if isinstance(val, int):
        return _int_map.get(val, "MEDIUM")
    return "MEDIUM"


def _image_to_data_url(image_url: str, book_slug: str) -> str | None:
    """Convert a local /images/{book_slug}/... URL to a base64 data URL for OpenAI vision API."""
    try:
        from config import OUTPUT_DIR
        from pathlib import Path as _ImgPath
        marker = f"/images/{book_slug}/"
        idx = image_url.find(marker)
        if idx == -1:
            return None
        rel_path = image_url[idx + len(marker):]
        file_path = _ImgPath(OUTPUT_DIR) / book_slug / rel_path
        if not file_path.exists():
            return None
        ext = file_path.suffix.lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/jpeg")
        data = file_path.read_bytes()
        b64 = base64.b64encode(data).decode("utf-8")
        return f"data:{mime};base64,{b64}"
    except Exception as _e:
        logger.debug("[vision] failed to encode image %s: %s", image_url, _e)
        return None


def _normalise_per_card(parsed: dict, chunk_id: str) -> dict:
    """Stamp new LessonCard schema fields onto a parsed card dict.

    The LLM returns the single-card schema from _NEXT_CARD_JSON_SCHEMA.
    chunk_id is injected by the backend after generation — NOT asked from LLM.
    """
    # Handle legacy 'questions' list format: extract first MCQ if present
    raw_question = parsed.get("question")
    if not raw_question:
        questions = parsed.get("questions") or []
        for q in questions:
            if isinstance(q, dict) and q.get("type") in ("mcq", "multiple_choice"):
                raw_question = {
                    "text": q.get("question", ""),
                    "options": q.get("options", []),
                    "correct_index": int(q.get("correct_index", 0) or 0),
                    "explanation": q.get("explanation", ""),
                    "difficulty": "MEDIUM",
                }
                break

    # Normalise question field to CardMCQ shape
    normalised_question: dict | None = None
    if isinstance(raw_question, dict) and raw_question.get("text"):
        raw_opts = raw_question.get("options", [])
        # Ensure options is a list of exactly 4 strings (CardMCQ requires min/max=4)
        if not isinstance(raw_opts, list):
            raw_opts = []
        raw_opts = [str(o) for o in raw_opts]  # coerce to strings
        if len(raw_opts) > 4:
            raw_opts = raw_opts[:4]
        elif len(raw_opts) < 4:
            raw_opts = raw_opts + [""] * (4 - len(raw_opts))
        # Clamp correct_index to valid range [0, 3]
        try:
            correct_idx = int(raw_question.get("correct_index", 0))
        except (TypeError, ValueError):
            correct_idx = 0
        correct_idx = max(0, min(correct_idx, 3))
        if len(raw_opts) < 2:
            # Degenerate MCQ — drop question entirely
            raw_question = None
        else:
            normalised_question = {
                "text":          raw_question.get("text", ""),
                "options":       raw_opts,
                "correct_index": correct_idx,
                "explanation":   raw_question.get("explanation", ""),
                "difficulty":    _coerce_difficulty(raw_question.get("difficulty")),
            }

    return {
        "index":       parsed.get("index", 0),
        "title":       parsed.get("title", ""),
        "content":     parsed.get("content") or "",
        "image_url":   parsed.get("image_url"),
        "caption":     parsed.get("caption"),
        "question":    normalised_question,
        "chunk_id":    chunk_id,
        "is_recovery": parsed.get("is_recovery", False),
    }


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
    r'(?:\s+[\d\.]+(?:[\s:].+)?|:\s*.+)?$',
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

    def __init__(self):
        self._chunk_ksvc = ChunkKnowledgeService()
        self.openai = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        self.model = OPENAI_MODEL
        self.model_mini = OPENAI_MODEL_MINI

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
        book_slug: str = "prealgebra",
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

        # 1. Retrieve concept chunks from PostgreSQL
        # Build a synthetic concept dict from the first chunks of the concept for presentation
        chunks = await self._chunk_ksvc.get_chunks_for_concept(
            db, session.book_slug or "prealgebra", session.concept_id
        )
        if not chunks:
            raise ValueError(f"Concept not found: {session.concept_id}")
        # Aggregate chunk text/latex for presentation (take up to 3 chunks)
        combined_text = "\n\n".join(c["text"] for c in chunks[:3])
        combined_latex = []
        for c in chunks:
            combined_latex.extend(c.get("latex") or [])
        concept = {
            "concept_title": chunks[0].get("heading", session.concept_id),
            "text": combined_text,
            "latex": combined_latex[:10],
            "prerequisites": [],
            "images": [],
        }

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

        if session.phase == "PRESENTING" and session.presentation_text is not None:
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

    async def _initialize_queue(
        self,
        db: AsyncSession,
        session: TeachingSession,
    ) -> None:
        """Build the per-card concepts_queue from concept_chunks rows and persist it on the session.

        Called when generate_cards() is invoked on a session that has no queue yet (PRESENTING
        phase) or when generate_per_card() detects an empty queue at the start of a session.
        After this method returns, session.presentation_text contains a valid JSON cache dict
        and session.phase is "CARDS".
        """
        book_slug = getattr(session, "book_slug", None) or "prealgebra"
        stmt = (
            select(ConceptChunk)
            .where(
                ConceptChunk.concept_id == session.concept_id,
                ConceptChunk.book_slug == book_slug,
            )
            .order_by(ConceptChunk.order_index)
        )
        rows = (await db.execute(stmt)).scalars().all()
        queue = [
            {
                "id": str(c.id),
                "title": c.heading,
                "text": c.text,
                "latex": list(c.latex or []),
                "section": c.section or "",
                "chapter": (c.section or "").split(".")[0],
                "images": [],
                "chunk_type": c.chunk_type or "teaching",
            }
            for c in rows
        ]
        logger.info(
            "[_initialize_queue] built queue: session_id=%s concept_id=%s book_slug=%s chunks=%d",
            session.id, session.concept_id, book_slug, len(queue),
        )

        # Guard: if no chunks exist for this concept+book, do NOT transition to CARDS.
        # Transitioning with an empty queue would cause generate_per_card() to call
        # _initialize_queue() again, creating an infinite loop.
        if not queue:
            logger.error(
                "[_initialize_queue] empty_queue_abort: session_id=%s concept_id=%s book_slug=%s "
                "— no concept_chunks found; session remains in current phase",
                session.id, session.concept_id, book_slug,
            )
            raise HTTPException(
                status_code=422,
                detail=f"No content chunks found for concept '{session.concept_id}' in book '{book_slug}'. "
                       "Cannot start card-based learning for this concept.",
            )

        session.presentation_text = json.dumps({
            "concepts_queue": queue,
            "concepts_covered": [],
            "concepts_total": len(queue),
            "cache_version": 1,
        })
        session.phase = "CARDS"
        db.add(session)
        await db.flush()

    async def generate_cards(
        self,
        db: AsyncSession,
        session: TeachingSession,
        student: Student,
    ) -> dict:
        """Bootstraps the per-card generation queue for a fresh session.

        Previously a deprecated stub that returned an empty cards list. Now it initialises
        the concepts_queue from concept_chunks (if not already present), transitions the
        session to CARDS phase, generates the first adaptive card via generate_per_card(),
        and returns a response compatible with the legacy /sessions/{id}/cards contract so
        that the frontend SessionContext.startLesson() can proceed without changes.
        """
        from api.teaching_schemas import NextCardRequest

        # Parse existing cache, if any.
        try:
            cached = json.loads(session.presentation_text or "{}")
            if not isinstance(cached, dict):
                cached = {}
        except (json.JSONDecodeError, TypeError):
            cached = {}

        # Build queue if missing or empty.
        if not cached.get("concepts_queue"):
            await self._initialize_queue(db, session)
            cached = json.loads(session.presentation_text or "{}")

        # Generate the first card using zero-signal baseline request.
        zero_req = NextCardRequest(
            card_index=0,
            time_on_card_sec=0,
            wrong_attempts=0,
            hints_used=0,
            idle_triggers=0,
        )
        result = await self.generate_per_card(db, session, student, zero_req)

        return {
            "session_id": str(session.id),
            "concept_id": session.concept_id,
            "concept_title": session.concept_id,
            "style": session.style or "default",
            "phase": "CARDS",
            "cards": [result["card"]] if result.get("card") else [],
            "total_questions": 0,
            "cache_version": 1,
            "has_more_concepts": result["has_more_concepts"],
            "concepts_total": result["concepts_total"],
            "concepts_covered_count": result["concepts_covered_count"],
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

        # ── Step 1a: Language-change cache bust ──────────────────────────────────
        # When the student changes language, the PATCH /language endpoint sets
        # cache_version = -1.  Clear the cache so cards are regenerated in the
        # new language instead of serving stale English content.
        if cached.get("cache_version") == -1:
            logger.info(
                "[per-card] language_cache_bust: session_id=%s — clearing cache for language change",
                session.id,
            )
            session.presentation_text = None
            db.add(session)
            await db.flush()
            cached = {}
            concepts_queue = []
            concepts_covered = []
            all_sections_count = 1

        # ── Step 1b: Stale session reset ─────────────────────────────────────────
        # If the session was last updated more than 24 hours ago, the cached content
        # may be based on outdated concept chunk text. Clear the cache so the student
        # gets fresh, re-initialized content rather than stale presentation data.
        _updated = getattr(session, "updated_at", None)
        if _updated and (datetime.now(timezone.utc) - _updated) > timedelta(hours=24):
            logger.warning(
                "[per-card] stale_session_reset: session_id=%s last_updated=%s — clearing cache",
                session.id, _updated.isoformat(),
            )
            session.presentation_text = None
            db.add(session)
            await db.flush()
            cached = {}
            concepts_queue = []
            concepts_covered = []
            all_sections_count = 1

        # ── Step 2: Empty queue guard ────────────────────────────────────────────
        if not concepts_queue:
            # If the queue is empty and nothing has been covered yet, the session was
            # likely just created (PRESENTING phase) and never had its queue built.
            # Auto-initialize from concept_chunks so the student isn't stuck.
            # _initialize_queue() raises HTTPException(422) if no chunks exist, so this
            # path is NOT recursive — it either succeeds (queue populated) or raises.
            if not concepts_covered:
                logger.warning(
                    "[per-card] queue_empty_auto_init: session_id=%s — initialising queue from DB",
                    session.id,
                )
                await self._initialize_queue(db, session)  # raises 422 if DB has no chunks
                try:
                    _raw_cache = json.loads(session.presentation_text or "{}")
                    cached = _raw_cache if isinstance(_raw_cache, dict) else {}
                except (json.JSONDecodeError, TypeError):
                    cached = {}
                concepts_queue = list(cached.get("concepts_queue", []))
                all_sections_count = cached.get("concepts_total", 1)

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
        try:
            cached_images = await self._chunk_ksvc.get_chunk_images(db, str(req.chunk_id))
        except Exception as _img_err:
            logger.warning("[per-card] failed to load chunk images: %s", _img_err)
            cached_images = []
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
        # Use only data available from the cached piece — no ChromaDB lookup needed
        piece_concept_detail = {
            "concept_id":    session.concept_id,
            "concept_title": next_piece.get("title", session.concept_id),
            "text":          next_piece.get("text", ""),
            "chapter":       next_piece.get("chapter", ""),
            "section":       next_piece.get("section", ""),
            "latex":         next_piece.get("latex", []),
            "images":        content_piece_images,
        }

        # ── Step 10: Build prompts (Bug 6 fix — pass content_piece_images) ───────
        language = getattr(student, "preferred_language", "en") or "en"
        _card_style = getattr(session, "style", "default") or "default"
        _card_interests = (
            getattr(session, "lesson_interests", None)
            or getattr(student, "interests", None)
            or []
        )
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
            style=_card_style,
            interests=_card_interests,
        )

        # ── Step 10b: Inject already-used image note ──────────────────────────
        # Tell the LLM which image indices were already used on previous cards so
        # it does not reference the same image again in this card.
        if already_assigned:
            user_prompt += (
                f"\n\nNOTE: Images at indices {sorted(already_assigned)} were already used on "
                "previous cards. Use ONLY the images listed in RELEVANT IMAGES above."
            )

        # ── Step 11: Call LLM ──────────────────────────────────────────────────
        # Vision parts for per-card — same pattern as generate_per_chunk
        _pc_book_slug = getattr(session, "book_slug", None) or "prealgebra"
        _pc_vision_parts = []
        for _img in (content_piece_images or [])[:2]:   # cap at 2 per card for speed
            _img_url = _img.get("image_url") or _img.get("url", "")
            _data_url = _image_to_data_url(_img_url, _pc_book_slug)
            if _data_url:
                _pc_vision_parts.append({
                    "type": "image_url",
                    "image_url": {"url": _data_url, "detail": "low"},
                })
        _pc_user_content = (
            [{"type": "text", "text": user_prompt}] + _pc_vision_parts
            if _pc_vision_parts else user_prompt
        )

        raw = await self._chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _pc_user_content},
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
        len(cached.get("cards", []))
        card_dict = _normalise_per_card(parsed, chunk_id=next_piece.get("id") or session.concept_id)

        # ── Step 13: Resolve image — image_indices first, then LLM image_url match ──
        new_assigned: set[int] = set()
        resolved_image = None

        # Path A: LLM returned image_indices (future schema)
        for idx in (parsed.get("image_indices") or []):
            if 0 <= idx < len(content_piece_images):
                resolved_image = content_piece_images[idx]
                orig_idx = _cp_to_cached_idx.get(idx)
                if orig_idx is not None:
                    new_assigned.add(orig_idx)
                break

        # Path B: match LLM's image_url string to content_piece_images by filename
        if resolved_image is None and card_dict.get("image_url"):
            llm_filename = card_dict["image_url"].split("/")[-1]
            for pos, img in enumerate(content_piece_images):
                img_url = img.get("image_url") or img.get("url", "")
                if img_url and img_url.split("/")[-1] == llm_filename:
                    resolved_image = img
                    orig_idx = _cp_to_cached_idx.get(pos)
                    if orig_idx is not None:
                        new_assigned.add(orig_idx)
                    break

        if resolved_image:
            card_dict["image_url"] = resolved_image.get("url") or resolved_image.get("image_url")
            card_dict["caption"]   = resolved_image.get("caption") or resolved_image.get("description")

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

    # ── Chunk-Based Card Generation ────────────────────────────────────────

    async def generate_per_chunk(
        self,
        session: TeachingSession,
        db: AsyncSession,
        chunk_id: str,
    ) -> list[dict]:
        """Generate all cards for a single ConceptChunk in one LLM call.

        Returns a list of card dicts (new LessonCard schema).
        Each card has chunk_id stamped on it by _normalise_per_card().
        """
        try:
            from adaptive.adaptive_engine import build_blended_analytics  # noqa: F401
            from adaptive.prompt_builder import build_chunk_card_prompt, build_next_card_prompt, _CARD_MODE_DELIVERY  # noqa: F401
            from adaptive.schemas import CardBehaviorSignals  # noqa: F401
        except (ImportError, SyntaxError) as _imp_err:
            logger.error("[per-chunk] adaptive module import failed: %s", _imp_err)
            raise HTTPException(status_code=500, detail=f"Server configuration error: {_imp_err}")

        chunk = await self._chunk_ksvc.get_chunk(db, chunk_id)
        if not chunk:
            raise HTTPException(status_code=404, detail=f"Chunk not found: {chunk_id}")

        chunk_text = (chunk.get("text") or "").strip()
        if not chunk_text:
            logger.warning("[per-chunk] chunk has no text content, using fallback card: chunk_id=%s", chunk_id)
            return [{
                "index": 0,
                "title": chunk.get("heading") or "Lesson Content",
                "content": "Content for this section is currently being prepared.",
                "image_url": None,
                "caption": None,
                "question": None,
                "chunk_id": chunk_id,
                "is_recovery": False,
            }]

        _chunk_heading = (chunk.get("heading") or "") if isinstance(chunk, dict) else getattr(chunk, "heading", "")

        # Learning-objective chunks → single polished info card, no LLM call needed
        _INFO_HEADINGS = ("learning objectives", "key terms", "key concepts", "summary")
        if any(p in _chunk_heading.lower() for p in _INFO_HEADINGS):
            return [{
                "index": 0,
                "title": _chunk_heading,
                "content": chunk_text,
                "image_url": None,
                "caption": None,
                "question": None,
                "chunk_id": chunk_id,
                "is_recovery": False,
            }]

        try:
            images = await self._chunk_ksvc.get_chunk_images(db, chunk_id)
        except Exception as _img_err:
            logger.warning("[per-chunk] failed to load images for chunk %s: %s", chunk_id, _img_err)
            images = []

        # Fallback: use concept-level images if chunk has none
        if not images:
            try:
                concept_detail_for_images = await self._chunk_ksvc.get_concept_detail(
                    db, chunk.get("concept_id", ""), chunk.get("book_slug", "")
                )
                if concept_detail_for_images and concept_detail_for_images.get("images"):
                    images = concept_detail_for_images["images"][:3]
            except Exception as _cd_err:
                logger.warning("[per-chunk] failed to load concept images fallback for chunk %s: %s", chunk_id, _cd_err)

        # Determine mode using the existing blended-analytics engine
        from adaptive.adaptive_engine import (
            load_student_history, build_blended_analytics,
        )
        from adaptive.schemas import CardBehaviorSignals

        _history = await load_student_history(str(session.student_id), session.concept_id, db)

        _ci_result = await db.execute(
            select(
                func.count(CardInteraction.id).label("total"),
                func.coalesce(func.avg(CardInteraction.wrong_attempts), 0.0).label("avg_wrong"),
                func.coalesce(func.avg(CardInteraction.hints_used), 0.0).label("avg_hints"),
                func.coalesce(func.avg(CardInteraction.time_on_card_sec), 120.0).label("avg_time"),
                func.coalesce(func.sum(CardInteraction.idle_triggers), 0).label("idle"),
            ).where(CardInteraction.session_id == session.id)
        )
        _ci_row = _ci_result.one_or_none()
        _total_ci = int(_ci_row.total or 0) if _ci_row else 0

        if _total_ci == 0:
            _generate_as = "NORMAL"
        else:
            _current_signals = CardBehaviorSignals(
                time_on_card_sec=float(_ci_row.avg_time or 120.0),
                wrong_attempts=round(float(_ci_row.avg_wrong or 0.0)),
                hints_used=round(float(_ci_row.avg_hints or 0.0)),
                idle_triggers=int(_ci_row.idle or 0),
            )
            _, _blended_score, _generate_as = build_blended_analytics(
                current=_current_signals,
                history=_history,
                concept_id=session.concept_id,
                student_id=str(session.student_id),
            )
            logger.info("[per-chunk] mode=%s blended_score=%.2f (session_cards=%d)",
                        _generate_as, _blended_score, _total_ci)

        token_budgets = {
            "STRUGGLING": CHUNK_MAX_TOKENS_STRUGGLING,
            "NORMAL":     CHUNK_MAX_TOKENS_NORMAL,
            "FAST":       CHUNK_MAX_TOKENS_FAST,
        }
        max_tokens = token_budgets.get(_generate_as, CHUNK_MAX_TOKENS_NORMAL)

        # Build the user prompt
        student = await db.get(Student, session.student_id)
        language = getattr(student, "preferred_language", "en") or "en" if student else "en"
        interests = list(session.lesson_interests or [])
        if not interests and student:
            interests = list(getattr(student, "interests", None) or [])
        style = session.style or "default"

        # Build persona prefix to prepend at TOP of system prompts (before all other instructions)
        from api.prompts import STYLE_MODIFIERS as _STYLE_MODIFIERS
        _style_modifier = _STYLE_MODIFIERS.get(style, "")
        _persona_prefix = f"{_style_modifier}\n\n" if _style_modifier else ""

        # Build vision-capable user message (base64 encode local images for GPT-4o vision)
        # Must happen BEFORE build_chunk_card_prompt so only confirmed-visible images are listed in the text prompt.
        _book_slug_for_img = chunk.get("book_slug", "prealgebra")
        _vision_parts = []
        _visible_images = []  # only images successfully base64-encoded
        for _img in (images or [])[:4]:  # Cap at 4 images per call
            _data_url = _image_to_data_url(_img.get("image_url", ""), _book_slug_for_img)
            if _data_url:
                _vision_parts.append({
                    "type": "image_url",
                    "image_url": {"url": _data_url, "detail": "low"},
                })
                _visible_images.append(_img)

        user_prompt = build_chunk_card_prompt(
            chunk=chunk,
            images=_visible_images,
            student_mode=_generate_as,
            style=style,
            interests=interests,
            language=language,
        )

        # Detect exercise/practice chunks — prefer stored DB chunk_type, fall back to heading pattern
        _stored_type = chunk.get("chunk_type", "")
        is_exercise_chunk = (
            _stored_type == "exercise"
            or any(p in (chunk.get("heading") or "").lower() for p in EXERCISE_HEADING_PATTERNS)
        )

        if is_exercise_chunk:
            # Fetch preceding teaching subsections for this concept
            SKIP_HEADINGS = ("learning objectives", "key terms", "summary", "chapter review", "review exercises", "practice test")
            try:
                all_concept_chunks = await self._chunk_ksvc.get_chunks_for_concept(
                    db, chunk.get("book_slug", ""), chunk.get("concept_id", "")
                )
                # Get chunks that come before this one (lower order_index), excluding non-teaching chunks
                current_order = chunk.get("order_index", 9999)
                teaching_headings = [
                    c["heading"] for c in all_concept_chunks
                    if c.get("order_index", 0) < current_order
                    and not any(skip in c["heading"].lower() for skip in SKIP_HEADINGS)
                ]
            except Exception as _ex_err:
                logger.warning(f"[per-chunk] exercise chunk heading fetch failed: {_ex_err}")
                teaching_headings = []

            n_subsections = max(len(teaching_headings), 1)
            subsection_list = "\n".join(f"{i+1}. {h}" for i, h in enumerate(teaching_headings)) or "1. (this section)"

            # Per-mode explanation length for exercise wrong-answer feedback
            explanation_length = {
                "STRUGGLING": "full step-by-step numbered walkthrough of what went wrong",
                "NORMAL": "brief 2–3 sentence explanation of the correct approach",
                "FAST": "one-line correction only ('Correct: X because Y')",
            }.get(_generate_as, "brief 2–3 sentence explanation")

            system_prompt = (
                _persona_prefix +
                "You are Adaptive Learner, an adaptive math tutor.\n\n"
                "EXERCISE CHUNK MODE: Generate exactly 2 MCQ cards per teaching subsection listed below.\n\n"
                f"Teaching subsections covered in this section:\n{subsection_list}\n\n"
                f"Total required cards: {n_subsections * 2}\n\n"
                "RULES:\n"
                "1. Generate exactly 2 MCQ cards per subsection — in the same order as the subsection list.\n"
                "2. Use the EXERCISE CHUNK CONTENT provided as source for question wording.\n"
                "3. Every MCQ must be at REAL TEXTBOOK DIFFICULTY — same for all modes.\n"
                f"4. Wrong-answer explanation length: {explanation_length}.\n"
                "5. content field = brief problem context (1–2 sentences max); question = the MCQ.\n"
                "6. EVERY card's question field MUST have: options = exactly 4 non-empty strings; "
                "correct_index in [0, 1, 2, 3].\n"
                "7. Return ONLY a JSON array. No markdown fences. No commentary.\n"
                "SCHEMA per card: "
                '{"index":0,"title":"...","content":"...","image_url":null,"caption":null,'
                '"question":{"text":"...","options":["A","B","C","D"],'
                '"correct_index":0,"explanation":"...","difficulty":"HARD"},"is_recovery":false}\n'
                + _language_instruction(language)
            )
        else:
            system_prompt = (
                _persona_prefix +
                "You are Adaptive Learner, an adaptive math tutor. Generate lesson cards for the CHUNK CONTENT provided.\n\n"
                "RULE #1 — COVERAGE (non-negotiable):\n"
                "Every concept, definition, formula, and worked example in CHUNK CONTENT must appear on exactly one card. Never skip any item.\n"
                "For 'TRY IT' exercises: use them as inspiration for the MCQ question on the preceding example's card.\n"
                "Do NOT create a separate explanation card for each TRY IT — they are practice, not new content.\n\n"
                "RULE #2 — COMBINED CARDS (mandatory):\n"
                "Every card MUST have BOTH:\n"
                "- content: a full explanation (NEVER empty or null)\n"
                "- question: a complete MCQ object (NEVER null)\n"
                "A card without a question is WRONG.\n\n"
                "RULE #3 — IMAGE ASSIGNMENT:\n"
                "If IMAGES are listed in the user message: assign the most relevant image URL to the card whose content most closely relates to it.\n"
                "Set image_url to the exact URL string and caption to the exact caption string.\n"
                "NEVER set image_url=null on ALL cards when images are provided — distribute images across cards.\n\n"
                "RULE #4 — CONTENT QUALITY:\n"
                "For each concept in CHUNK CONTENT:\n"
                "(a) State the definition or rule IN FULL — do not paraphrase to fewer words than the original.\n"
                "(b) Write out every step of every worked example explicitly, IN SEQUENCE, on the SAME card.\n"
                "    A worked example with N steps must have all N steps — never split a worked example across cards.\n"
                "(c) Write the formula in $LaTeX$ notation if applicable.\n"
                "(d) Enrich with a mode-appropriate analogy or real-world hook.\n"
                "Enrichment ADDS to chunk content — it never replaces chunk content.\n"
                "Do NOT copy raw textbook sentences verbatim. Do NOT invent facts not present in CHUNK CONTENT.\n\n"
                "RULE #5 — MERGE RULES:\n"
                "NEVER merge: formula/LaTeX expressions, worked examples, numbered steps, named definitions.\n"
                "MAY merge ONLY when ALL three are true: (a) \u22642 sentences total, (b) continues the same topic, (c) introduces no new concept.\n"
                "Mode override: STRUGGLING \u2192 never merge. FAST \u2192 merge if conceptually related and both short.\n\n"
                "RULE #6 — MODE RULE:\n"
                "The student's current mode NEVER reduces content coverage. Mode only changes delivery style (tone, scaffolding, analogy density). All concepts from CHUNK CONTENT must still appear regardless of mode.\n\n"
                "RULE #7 — MCQ RULES:\n"
                "- EXACTLY 4 options (A, B, C, D). correct_index must be 0, 1, 2, or 3.\n"
                "- EXACTLY ONE option must be correct. Verify no other option is also defensible.\n"
                "- The question must test understanding or application — NEVER ask a question whose answer is explicitly written verbatim in the card content above it.\n"
                "- Wrong-answer options must be specific, plausible mistakes a real student makes —\n"
                "  e.g. confusing 0 as a counting number, or $-3$ as a whole number.\n"
                "  NEVER use 'None of the above', 'All of the above', or randomly implausible values.\n"
                "- Every math expression in question text and options MUST use $...$ LaTeX notation.\n\n"
                "RULE #8 — DIFFICULTY:\n"
                "Set the difficulty field on every question based on the student's current mode:\n"
                "STRUGGLING → \"EASY\"   NORMAL → \"MEDIUM\"   FAST → \"HARD\"\n"
                "All cards in this session use the SAME difficulty level determined by mode.\n\n"
                "RULE #9 — LANGUAGE:\n"
                "Write ALL card content, MCQ text, options, and explanations in the language specified by LANGUAGE in the user message.\n"
                "Keep formulas and $LaTeX$ expressions unchanged — mathematics notation is universal.\n"
                "Use the target language's standard mathematical terminology for all math terms.\n"
                + _language_instruction(language) + "\n"
                "OUTPUT: A JSON array only. No markdown fences. No commentary before or after.\n\n"
                "EXAMPLE card (topic: even/odd numbers — NOT your actual content):\n"
                "{\"index\":0,\"title\":\"Even and Odd Numbers\","
                "\"content\":\"An even number is any integer exactly divisible by 2. For example, 4 \u00f7 2 = 2 with no remainder, so 4 is even. An odd number leaves a remainder of 1. Think of it like sharing cookies \u2014 even means everyone gets the same share.\","
                "\"image_url\":\"<URL from IMAGES list or null>\",\"caption\":\"<caption text or null>\","
                "\"question\":{\"text\":\"Which of the following is an odd number?\","
                "\"options\":[\"$6$\",\"$9$\",\"$12$\",\"$4$\"],"
                "\"correct_index\":1,"
                "\"explanation\":\"$9 \u00f7 2 = 4$ remainder $1$, so 9 is odd. The others (6, 12, 4) are all divisible by 2 with no remainder.\","
                "\"difficulty\":\"MEDIUM\"},\"is_recovery\":false}\n\n"
                "NOTE: This example card covers a compact 2-definition chunk. Your chunk may require longer "
                "cards with full worked example steps — write as much as needed per the COMPLETENESS RULE.\n\n"
                f"STUDENT MODE (writing style, vocabulary, difficulty — not card structure):\n"
                f"{_CARD_MODE_DELIVERY.get(_generate_as, _CARD_MODE_DELIVERY['NORMAL'])}\n"
            )

        # Call LLM
        timeout = max(30.0, max_tokens / 80.0 + 15.0)

        def _parse_cards(raw_text: str) -> list:
            cleaned = self._extract_json_block(raw_text)
            cleaned = _fix_latex_backslashes(cleaned)
            for attempt_str in (cleaned, _clean_salvage(cleaned)):
                if attempt_str is None:
                    continue
                try:
                    parsed = json.loads(attempt_str)
                    if isinstance(parsed, list) and parsed:
                        return parsed
                except json.JSONDecodeError:
                    pass
            return []

        if _vision_parts:
            _user_content: list | str = [{"type": "text", "text": user_prompt}] + _vision_parts
        else:
            _user_content = user_prompt

        try:
            raw = await self._chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": _user_content},
                ],
                max_tokens=max_tokens,
                model="main",
                timeout=timeout,
            )
            cards_data = _parse_cards(raw)
        except Exception as _llm_err:
            logger.warning("[per-chunk] primary LLM call failed: session_id=%s chunk_id=%s err=%s",
                           session.id, chunk_id, _llm_err)
            raw = ""
            cards_data = []

        # Retry once with a minimal prompt if first attempt yielded nothing
        if not cards_data:
            logger.warning(
                "[per-chunk] first attempt empty, retrying with minimal prompt: session_id=%s chunk_id=%s raw=%s",
                session.id, chunk_id, raw[:300],
            )
            _difficulty_label = {"STRUGGLING": "EASY", "NORMAL": "MEDIUM", "FAST": "HARD"}.get(_generate_as, "MEDIUM")
            retry_system = (
                "You are Adaptive Learner, a math tutor. Output ONLY a JSON array of lesson cards — no markdown fences, no commentary.\n"
                "RULE 1 — COVERAGE: Every concept in CHUNK CONTENT must appear on a card. Never skip any.\n"
                "RULE 2 — COMBINED CARDS: Every card MUST have content AND question (NEVER null).\n"
                "RULE 3 — IMAGES: If IMAGES are listed in the user message, assign relevant URLs. "
                "Never set image_url=null on all cards when images exist.\n"
                "SCHEMA per card: "
                "{\"index\":0,\"title\":\"...\",\"content\":\"...\","
                "\"image_url\":\"<URL from IMAGES list or null>\","
                "\"caption\":\"<caption or null>\","
                "\"question\":{\"text\":\"...\","
                "\"options\":[\"A\",\"B\",\"C\",\"D\"],\"correct_index\":0,"
                f"\"explanation\":\"...\",\"difficulty\":\"{_difficulty_label}\"}},\"is_recovery\":false}}"
            )
            try:
                raw2 = await self._chat(
                    messages=[
                        {"role": "system", "content": retry_system},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=max_tokens,
                    model="mini",
                    timeout=timeout,
                )
                cards_data = _parse_cards(raw2)
            except Exception as _llm_err2:
                logger.warning("[per-chunk] retry LLM call failed: session_id=%s chunk_id=%s err=%s",
                               session.id, chunk_id, _llm_err2)
                cards_data = []

        # Normalise each card
        cards = []
        for i, parsed_card in enumerate(cards_data):
            if not isinstance(parsed_card, dict):
                continue
            parsed_card["index"] = i
            try:
                card = _normalise_per_card(parsed_card, chunk_id)
                cards.append(card)
            except Exception as _norm_err:
                logger.warning("[per-chunk] skipping malformed card %d: %s", i, _norm_err)

        # If chunk has images but LLM assigned none, distribute by keyword relevance
        if images:
            assigned_urls = {c.get("image_url") for c in cards if c.get("image_url")}
            remaining_imgs = [img for img in images if img.get("image_url") not in assigned_urls]

            if remaining_imgs:
                _STOP = {"a","an","the","is","in","of","to","and","or","for","with","this","that","it","its"}

                def _overlap(img_desc: str, card: dict) -> int:
                    img_words  = set(img_desc.lower().split()) - _STOP
                    card_words = set(
                        (card.get("content","") + " " + card.get("title","")).lower().split()
                    ) - _STOP
                    return len(img_words & card_words)

                for img in remaining_imgs:
                    desc = img.get("description") or img.get("caption") or ""
                    best_card, best_score = None, -1
                    for card in cards:
                        if card.get("image_url"):
                            continue
                        score = _overlap(desc, card)
                        if score > best_score:
                            best_score, best_card = score, card
                    if best_card is not None:
                        best_card["image_url"] = img.get("image_url")
                        best_card["caption"]   = img.get("caption") or img.get("description")

        # Final fallback: synthetic card from chunk content so student never sees a 500
        if not cards:
            logger.error(
                "[per-chunk] both attempts failed, using fallback card: session_id=%s chunk_id=%s",
                session.id, chunk_id,
            )
            heading = chunk.get("heading") or "Lesson Content"
            body = (chunk.get("text") or "")[:800]
            fallback: dict = {
                "index": 0,
                "title": heading,
                "content": body if body else "Content could not be loaded. Please try again.",
                "image_url": None,
                "caption": None,
                "question": {
                    "text": f"Which best describes: {heading}?",
                    "options": [heading, "None of the above", "Not defined here", "Unknown"],
                    "correct_index": 0,
                    "explanation": f"This card covers the topic: {heading}.",
                    "difficulty": {"STRUGGLING": "EASY", "NORMAL": "MEDIUM", "FAST": "HARD"}.get(_generate_as, "MEDIUM"),
                },
                "is_recovery": False,
                "chunk_id": chunk_id,
            }
            cards = [fallback]

        logger.info(
            "[per-chunk] generated: session_id=%s chunk_id=%s cards=%d mode=%s",
            session.id, chunk_id, len(cards), _generate_as,
        )
        return cards

    async def generate_recovery_card_for_chunk(
        self,
        session: TeachingSession,
        chunk: dict,
        chunk_images: list[dict],
        card_index: int = 0,
        wrong_answers: list[str] | None = None,
        is_exercise: bool = False,
    ) -> dict | None:
        """Generate a single recovery TEACH card for a chunk the student failed.

        Targeted re-explanation in STRUGGLING mode using chunk text directly.
        Returns card dict with is_recovery=True and chunk_id stamped, or None on failure.
        """

        chunk_id = chunk.get("id", "")
        topic_title = chunk.get("heading", "this topic")

        # Anti-loop guard
        if topic_title.startswith("Let's Try Again"):
            return None

        wrong_ctx = ""
        if wrong_answers:
            wrong_ctx = (
                f"\n\nThe student answered these MCQs INCORRECTLY: {', '.join(wrong_answers[:3])}. "
                "Re-explain specifically to correct these misconceptions.\n"
            )

        if is_exercise:
            system_prompt = (
                "You are Adaptive Learner, an adaptive math tutor. Generate ONE recovery TEACH card.\n"
                "The student struggled with this exercise. Show HOW TO SOLVE this type of problem.\n"
                "RULES:\n"
                "- Title MUST start exactly with: Let's Try Again — \n"
                "- Show the METHOD step-by-step (Step 1, Step 2, ...).\n"
                "- Include ONE fully worked example similar to the problem the student got wrong.\n"
                "- Use simple language, age 8–10 reading level.\n"
                "- End with ONE easy version of the same problem type as MCQ — confidence-building.\n"
                "- Return ONLY valid JSON matching the schema below. No markdown fences.\n"
                'SCHEMA: {"index": ' + str(card_index) + ', "title": "Let\'s Try Again — <topic>", '
                '"content": "<markdown step-by-step solution>", "image_url": null, "caption": null, '
                '"question": {"text": "<easy version of problem>", "options": ["A","B","C","D"], '
                '"correct_index": 0, "explanation": "<why>", "difficulty": "EASY"}, '
                '"is_recovery": true}'
            )
        else:
            system_prompt = (
                "You are Adaptive Learner, an adaptive math tutor. Generate ONE recovery TEACH card.\n"
                "The student struggled with this chunk twice. Re-explain in the SIMPLEST way.\n"
                "RULES:\n"
                "- Title MUST start exactly with: Let's Try Again — \n"
                "- Language: age 8-10 reading level. Define every term.\n"
                "- Open with a real-world analogy BEFORE any formula.\n"
                "- Use numbered step-by-step explanation.\n"
                "- End with ONE easy MCQ — confidence-building.\n"
                "- Return ONLY valid JSON matching the schema below. No markdown fences.\n"
                'SCHEMA: {"index": ' + str(card_index) + ', "title": "Let\'s Try Again — <topic>", '
                '"content": "<markdown>", "image_url": null, "caption": null, '
                '"question": {"text": "<question>", "options": ["A","B","C","D"], '
                '"correct_index": 0, "explanation": "<why>", "difficulty": "EASY"}, '
                '"is_recovery": true}'
            )

        image_note = ""
        if chunk_images:
            image_note = f"\nAVAILABLE IMAGE: {chunk_images[0]['image_url']}"
            if chunk_images[0].get("caption"):
                image_note += f" ({chunk_images[0]['caption']})"
            image_note += "\nSet image_url to this URL if the card references the image, otherwise null.\n"

        user_prompt = (
            f"Re-explain this chunk in STRUGGLING mode:\n"
            f"Heading: {topic_title}\n\n"
            f"Chunk text (use as factual basis):\n{chunk.get('text', '')[:2000]}"
            f"{image_note}{wrong_ctx}"
            "Return ONLY the JSON object."
        )

        raw = await self._chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=CHUNK_MAX_TOKENS_RECOVERY,
            model="mini",
            timeout=30.0,
            temperature=0.3,
        )

        cleaned = self._extract_json_block(raw)
        cleaned = _fix_latex_backslashes(cleaned)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            salvaged = _clean_salvage(cleaned)
            if salvaged:
                try:
                    parsed = json.loads(salvaged)
                except json.JSONDecodeError:
                    logger.error("[recovery-chunk] JSON parse failed: chunk_id=%s", chunk_id)
                    return None
            else:
                return None

        if not isinstance(parsed, dict):
            return None

        card = _normalise_per_card(parsed, chunk_id)
        # Inject first chunk image if the LLM didn't set one
        if not card.get("image_url") and chunk_images:
            card["image_url"] = chunk_images[0]["image_url"]
            card["caption"] = chunk_images[0].get("caption")
        card["is_recovery"] = True
        return card

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
            # Generate recovery card using ChunkKnowledgeService directly
            try:
                recovery_card = await generate_recovery_card(
                    topic_title=req.re_explain_card_title,
                    concept_id=session.concept_id,
                    chunk_ksvc=self._chunk_ksvc,
                    book_slug=session.book_slug or "prealgebra",
                    db=db,
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

        # 4. Award XP for correct answers (correct = no wrong attempts)
        is_correct = req.wrong_attempts == 0
        xp_result: dict = {"base_xp": 0, "multiplier": 1.0, "final_xp": 0, "new_badges": []}
        if is_correct:
            try:
                from gamification.xp_engine import compute_and_award_xp
                xp_result = await compute_and_award_xp(
                    db=db,
                    student_id=student.id,
                    session_id=session.id,
                    interaction_id=interaction.id,
                    difficulty=3,  # default difficulty for per-card adaptive cards
                    wrong_attempts=req.wrong_attempts,
                    hints_used=req.hints_used,
                    is_correct=True,
                    time_on_card_sec=req.time_on_card_sec,
                    answer_streak=0,
                )
            except Exception:
                logger.exception("[complete_card] XP award failed")

        await db.commit()

        return {
            "recovery_card": recovery_card,
            "learning_profile_summary": learning_profile_summary,
            "motivational_note": None,
            "adaptation_applied": "recovery" if recovery_card else None,
            "new_badges": xp_result.get("new_badges", []),
            "xp_awarded": {
                "base_xp": xp_result["base_xp"],
                "multiplier": xp_result["multiplier"],
                "final_xp": xp_result["final_xp"],
            },
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
        # Retrieve concept context from PostgreSQL chunks
        _rem_chunks = await self._chunk_ksvc.get_chunks_for_concept(
            db, session.book_slug or "prealgebra", session.concept_id
        )
        concept = {
            "concept_title": _rem_chunks[0].get("heading", session.concept_id) if _rem_chunks else session.concept_id,
            "text": "\n\n".join(c["text"] for c in _rem_chunks[:3]) if _rem_chunks else "",
        }
        student = await db.get(Student, session.student_id)

        system_prompt = self._build_remediation_cards_prompt(failed_topics, concept, student, session=session)
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
        session=None,
    ) -> str:
        """Build the system prompt for remediation card generation."""
        from api.prompts import STYLE_MODIFIERS as _STYLE_MODIFIERS
        from api.prompts import _build_interests_block

        interests = []
        if student:
            interests = getattr(student, "interests", []) or []
        language = getattr(student, "preferred_language", "en") or "en" if student else "en"

        style = getattr(session, "style", "default") or "default" if session else "default"
        style_modifier = _STYLE_MODIFIERS.get(style, "")
        style_prefix = f"{style_modifier}\n\n" if style_modifier else ""

        # Prefer session-level interests (set at lesson start) over student profile
        session_interests = getattr(session, "lesson_interests", None) if session else None
        effective_interests = session_interests or interests
        interests_block = _build_interests_block(effective_interests)

        failed_text = ", ".join(failed_topics[:5])

        base_prompt = (
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
            f"{interests_block}"
        )

        return style_prefix + base_prompt

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

