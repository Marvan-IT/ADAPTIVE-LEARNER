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
    CARDS_MID_SESSION_CHECK_INTERVAL,
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

class TeachingService:
    """Manages the full lifecycle of a teaching session."""

    def __init__(self, knowledge_svc: KnowledgeService):
        self.knowledge_svc = knowledge_svc
        self.openai = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        self.model = OPENAI_MODEL
        self.model_mini = OPENAI_MODEL_MINI

    async def _chat(self, messages: list, max_tokens: int = 2000, temperature: float = 0.7, model: str | None = None) -> str:
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
                    timeout=30.0,
                )
                if not response.choices:
                    raise ValueError("LLM returned no choices")
                content = response.choices[0].message.content or ""
                if content.strip():
                    return content.strip()
                logger.warning("[%s] Attempt %d: empty response", use_model, attempt + 1)
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
        style: str = "default",
        lesson_interests: list[str] | None = None,
    ) -> TeachingSession:
        """Create a new teaching session for a student + concept."""
        session = TeachingSession(
            student_id=student_id,
            concept_id=concept_id,
            book_slug="prealgebra",
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
        concept = self.knowledge_svc.get_concept_detail(session.concept_id)
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

        concept = self.knowledge_svc.get_concept_detail(session.concept_id)
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
        covered_topics: list[str] = []
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
            images=images,
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

        first_question = await self._chat(messages=messages, max_tokens=500, model="mini")

        # Store messages
        await self._save_message(db, session.id, "system", system_prompt, "CHECKING", msg_count)
        await self._save_message(
            db, session.id, "user",
            "I've read the explanation. Please check my understanding.",
            "CHECKING", msg_count + 1,
        )
        await self._save_message(db, session.id, "assistant", first_question, "CHECKING", msg_count + 2)

        await db.flush()
        return first_question

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

        # Call OpenAI for the next Socratic response (150 tokens enforces 1-2 sentence hints)
        ai_response = await self._chat(messages=openai_messages, max_tokens=150)
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
                failed_topics = await self._extract_failed_topics(session.id, db)
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
    _STALE_TITLE_RE = re.compile(
        r"^(solution\b|how to\b|example\b|learning objectives\b|\d+\.\d+|\(r\))",
        re.IGNORECASE,
    )

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
        if session.presentation_text:
            try:
                cached = json.loads(session.presentation_text)
                if "cards" in cached:
                    has_new_schema = any(card.get("card_type") for card in cached.get("cards", []))
                    is_stale = TeachingService._has_stale_card_titles(cached.get("cards", []))
                    if has_new_schema and not is_stale:
                        return cached
            except (json.JSONDecodeError, TypeError):
                pass

        # 1. Retrieve concept
        concept = self.knowledge_svc.get_concept_detail(session.concept_id)
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
            sub_sections = [{"title": concept_title, "content": concept_text}]

        # 3. Only include images that are educational AND have a real vision description
        # AND are not self-assessment checklists/rubrics (which pass is_educational=True
        # but are not math diagrams the student needs to see).
        _CHECKLIST_KEYWORDS = (
            "checklist", "self-assessment", "i can", "confidently",
            "with some help", "rubric", "evaluate my understanding", "learning target",
        )
        useful_images = [
            img for img in images
            if img.get("image_type", "").upper() in ("DIAGRAM", "FORMULA")
            and img.get("is_educational", True)
            and img.get("description")
            and not any(
                kw in (img.get("description") or "").lower()
                for kw in _CHECKLIST_KEYWORDS
            )
        ]
        logger.info(
            "cards concept=%s total_images=%d useful_images=%d",
            session.concept_id, len(images), len(useful_images),
        )

        # 3b. Load student history and wrong-option pattern concurrently for adaptive enrichment
        from adaptive.adaptive_engine import load_student_history, load_wrong_option_pattern
        from adaptive.profile_builder import build_learning_profile
        from adaptive.schemas import AnalyticsSummary

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

        # Build LearningProfile from history (defaults give NORMAL/OK for new students with no history)
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
        system_prompt = build_cards_system_prompt(
            style=session.style,
            interests=effective_interests,
            language=language,
            learning_profile=card_profile,
            history=history,
            images=useful_images,
        )

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
        )

        # 5. Generate cards in a single LLM call
        cards_data = await self._generate_cards_single(
            system_prompt, user_prompt,
        )

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

            # Ensure image_indices is a list (LLM may omit it)
            if not isinstance(card.get("image_indices"), list):
                card["image_indices"] = []

            # Initialise empty images list; index-based resolution below
            card["images"] = []

        # 7b. Pedagogical ordering safety net:
        # Move FUN cards to the front (engagement opener) and RECAP cards to the back.
        # Preserves all other relative order — only corrects clearly misplaced bookend cards.
        _front_cards = [c for c in raw_cards if c.get("card_type") == "FUN"]
        _middle_cards = [c for c in raw_cards if c.get("card_type") not in ("FUN", "RECAP")]
        _back_cards = [c for c in raw_cards if c.get("card_type") == "RECAP"]
        if _front_cards or _back_cards:
            raw_cards = _front_cards + _middle_cards + _back_cards
            for new_ci, card in enumerate(raw_cards):
                card["index"] = new_ci
            logger.info(
                "[cards-ordering] session=%s reordered: %d FUN front, %d RECAP back",
                str(session.id), len(_front_cards), len(_back_cards),
            )

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

                # Build global→local index map and populate card.images
                global_to_local: dict[int, int] = {}
                for global_idx in image_indices:
                    if (
                        isinstance(global_idx, int)
                        and 0 <= global_idx < len(useful_images)
                        and global_idx not in assigned_global
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
        else:
            for card in raw_cards:
                card.pop("image_indices", None)
                card.setdefault("images", [])

        cards_with_images = sum(1 for c in raw_cards if c.get("images"))
        logger.info(
            "[cards-generated] session=%s concept=%s cards=%d with_images=%d",
            str(session.id), session.concept_id, len(raw_cards), cards_with_images,
        )

        result = {
            "session_id": str(session.id),
            "concept_id": session.concept_id,
            "concept_title": concept_title,
            "style": session.style,
            "phase": session.phase,
            "cards": raw_cards,
            "total_questions": 0,  # Retained for API compat; no longer a meaningful count
        }

        # 8. Cache and save messages
        session.presentation_text = json.dumps(result)
        msg_count = await self._get_message_count(db, session.id)
        await self._save_message(db, session.id, "system", system_prompt, "PRESENTING", msg_count)
        await self._save_message(db, session.id, "user", user_prompt, "PRESENTING", msg_count + 1)
        await self._save_message(db, session.id, "assistant", json.dumps(cards_data), "PRESENTING", msg_count + 2)

        await db.flush()
        return result

    async def _generate_cards_single(self, system_prompt: str, user_prompt: str) -> dict:
        """Generate all cards in a single LLM call (primary model)."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        cards_data = None
        last_error = None
        for attempt in range(3):
            try:
                raw_json = await self._chat(messages=messages, max_tokens=8000)
            except ValueError:
                last_error = ValueError("LLM returned empty response")
                logger.warning("[cards-single] Empty response (attempt %d)", attempt + 1)
                continue
            raw_json = self._extract_json_block(raw_json)
            try:
                cards_data = json.loads(raw_json)
                break
            except json.JSONDecodeError as e:
                last_error = e
                salvaged = self._salvage_truncated_json(raw_json)
                if salvaged is not None:
                    cards_data = salvaged
                    break
                logger.warning("[cards-single] JSON parse failed (attempt %d): %s", attempt + 1, e)
        if cards_data is None:
            raise ValueError(f"AI returned invalid JSON for cards: {last_error}")
        return cards_data

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
        concept = self.knowledge_svc.get_concept_detail(session.concept_id)
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
        concept = self.knowledge_svc.get_concept_detail(session.concept_id)
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
        """Split concept text by ## headers into sub-sections."""
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

        return sections

    @staticmethod
    def _split_into_n_chunks(text: str, n: int) -> list[dict]:
        """Split concept text into n equal chunks when header-based parsing yields < n sections."""
        sentences = [s.strip() for s in text.replace('\n', ' ').split('. ') if s.strip()]
        if not sentences:
            return [{"title": "Part 1", "text": text}]
        chunk_size = max(1, len(sentences) // n)
        chunks = []
        for i in range(0, len(sentences), chunk_size):
            part = '. '.join(sentences[i:i + chunk_size]).strip()
            if part:
                chunks.append({"title": f"Part {len(chunks) + 1}", "text": part})
        # Pad to n if sentence splitting produced fewer chunks
        while len(chunks) < n:
            chunks.append(chunks[-1])
        return chunks[:n]

    @staticmethod
    def _group_sub_sections(
        sections: list[dict], max_chars: int = 4000, max_cards: int = 10
    ) -> list[dict]:
        """
        Greedily group adjacent sub-sections so each card's combined text stays
        within max_chars. If that still yields more than max_cards groups, merge
        the two adjacent groups with the smallest combined size until within limit.
        No content is ever dropped.
        """
        groups: list[dict] = []
        current_title = sections[0]["title"]
        current_texts = [sections[0]["text"]]
        current_len = len(sections[0]["text"])

        for sec in sections[1:]:
            addition = len(sec["text"]) + 2  # +2 for the "\n\n" separator
            if current_len + addition <= max_chars:
                current_texts.append(sec["text"])
                current_len += addition
            else:
                groups.append({"title": current_title, "text": "\n\n".join(current_texts)})
                current_title = sec["title"]
                current_texts = [sec["text"]]
                current_len = len(sec["text"])

        if current_texts:
            groups.append({"title": current_title, "text": "\n\n".join(current_texts)})

        # If still over max_cards, merge the pair of adjacent groups with smallest combined size
        while len(groups) > max_cards:
            min_combined = float("inf")
            min_idx = 0
            for i in range(len(groups) - 1):
                combined = len(groups[i]["text"]) + len(groups[i + 1]["text"])
                if combined < min_combined:
                    min_combined = combined
                    min_idx = i
            merged = {
                "title": groups[min_idx]["title"],
                "text": groups[min_idx]["text"] + "\n\n" + groups[min_idx + 1]["text"],
            }
            groups = groups[:min_idx] + [merged] + groups[min_idx + 2:]

        return groups

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
    def _extract_inline_image_filenames(text: str) -> list[str]:
        """
        Extract bare filenames from inline image refs in sub-section text.
        Matches: ![any description](/images/concept_id/filename.jpeg)
        Returns filenames in reading order (positional — matches PDF layout).
        """
        import re
        return re.findall(r"!\[.*?\]\(/images/[^/]+/([^)\s]+)\)", text)

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

    async def _get_checking_messages(
        self, db: AsyncSession, session_id: uuid.UUID
    ) -> list[ConversationMessage]:
        result = await db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.session_id == session_id)
            .where(ConversationMessage.phase == "CHECKING")
            .order_by(ConversationMessage.message_order)
        )
        return list(result.scalars().all())

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
        self, session_id: uuid.UUID, db: AsyncSession
    ) -> list[str]:
        """
        Extract topic keywords from wrong/partial answers in the Socratic check messages.
        Uses simple heuristics: looks for assistant correction phrases and extracts
        the question text from 2 positions prior.
        """
        messages = await self._get_checking_messages(db, session_id)
        failed_topics = []

        correction_phrases = [
            "not quite", "hmm", "close but", "actually", "let me explain",
            "let's think", "the correct answer", "let me clarify",
        ]

        for i, msg in enumerate(messages):
            if msg.role == "assistant":
                content_lower = msg.content.lower()
                if any(phrase in content_lower for phrase in correction_phrases):
                    # Look 2 messages back for the question the student was answering
                    if i >= 2 and messages[i - 2].role == "assistant":
                        question_text = messages[i - 2].content[:100]
                        failed_topics.append(question_text)

        return failed_topics if failed_topics else ["the key concepts of this section"]

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
            raw = response.choices[0].message.content.strip()
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
