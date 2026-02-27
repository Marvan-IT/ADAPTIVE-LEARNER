"""
Teaching Service — The Pedagogical Loop.
Orchestrates the 2-step teaching flow:
  1. Presentation: metaphor-based explanation generated from RAG content
  2. Socratic Check: guided questioning to verify understanding (never gives answers)
"""

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI

from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_MODEL_MINI
from api.knowledge_service import KnowledgeService
from api.prompts import (
    build_presentation_system_prompt,
    build_presentation_user_prompt,
    build_socratic_system_prompt,
    build_cards_system_prompt,
    build_cards_user_prompt,
    build_assistant_system_prompt,
)
from db.models import TeachingSession, ConversationMessage, StudentMastery, Student, SpacedReview

MASTERY_THRESHOLD = 70  # Score >= 70 marks concept as mastered


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
                )
                if not response.choices:
                    raise ValueError("LLM returned no choices")
                content = response.choices[0].message.content or ""
                if content.strip():
                    return content.strip()
                print(f"[{use_model}] Attempt {attempt+1}: empty response")
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
            except Exception as e:
                last_exc = e
                print(f"[{use_model}] Attempt {attempt+1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
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

        # Build student's learning profile from card interaction history
        from adaptive.adaptive_engine import load_student_history
        from adaptive.profile_builder import build_learning_profile
        from adaptive.schemas import AnalyticsSummary

        history = await load_student_history(str(session.student_id), session.concept_id, db)
        socratic_profile = None
        if history["total_cards_completed"] >= 5:
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
                quiz_score=1.0,
                last_7d_sessions=history["sessions_last_7d"],
            )
            socratic_profile = build_learning_profile(mini_analytics, has_unmet_prereq=False)

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
        if session.phase != "CHECKING":
            raise ValueError(f"Cannot respond: session is in {session.phase} phase")

        # Get all previous messages for the CHECKING phase
        messages = await self._get_checking_messages(db, session.id)

        # Save the student's new message
        msg_count = await self._get_message_count(db, session.id)
        await self._save_message(db, session.id, "user", student_message, "CHECKING", msg_count)

        # Build the OpenAI messages array from conversation history
        raw_messages = [{"role": m.role, "content": m.content} for m in messages]
        raw_messages.append({"role": "user", "content": student_message})

        # Window the history to avoid token blowup in long sessions
        openai_messages = self._build_windowed_messages(raw_messages)

        # Call OpenAI for the next Socratic response
        ai_response = await self._chat(messages=openai_messages, max_tokens=800)
        await self._save_message(db, session.id, "assistant", ai_response, "CHECKING", msg_count + 1)

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
        }

        if check_complete:
            session.phase = "COMPLETED"
            session.check_score = score
            session.completed_at = datetime.now(timezone.utc)

            mastered = score >= MASTERY_THRESHOLD
            session.concept_mastered = mastered
            result["phase"] = "COMPLETED"
            result["mastered"] = mastered

            if mastered:
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

                # Create spaced review schedule (Ebbinghaus: +1, +3, +7, +14, +30 days)
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
        # Return cached if available
        if session.presentation_text:
            try:
                cached = json.loads(session.presentation_text)
                if "cards" in cached:
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

        # 2. Parse sub-sections from concept text (cap at 6 cards max)
        sub_sections = self._parse_sub_sections(concept_text)
        if len(sub_sections) > 6:
            # Merge the last sections into the 6th card to keep it manageable
            merged_text = "\n\n".join(s["text"] for s in sub_sections[5:])
            merged_title = sub_sections[5]["title"]
            sub_sections = sub_sections[:5] + [{"title": merged_title, "text": merged_text}]

        # Truncate very long sub-sections to keep prompt size reasonable
        for sec in sub_sections:
            if len(sec["text"]) > 1500:
                sec["text"] = sec["text"][:1500] + "..."

        # 3. Filter useful diagrams
        useful_images = [
            img for img in images
            if img.get("image_type", "").upper() == "DIAGRAM"
            and img.get("width", 0) >= 200
            and img.get("height", 0) >= 80
        ]

        # 4. Build prompts
        effective_interests = session.lesson_interests if session.lesson_interests else student.interests
        language = getattr(student, "preferred_language", "en") or "en"
        system_prompt = build_cards_system_prompt(
            style=session.style,
            interests=effective_interests,
            language=language,
        )

        user_prompt = build_cards_user_prompt(
            concept_title=concept_title,
            sub_sections=sub_sections,
            latex=latex,
            images=images,
        )

        # 5. Generate cards in a single LLM call
        cards_data = await self._generate_cards_single(
            system_prompt, user_prompt,
        )

        raw_cards = cards_data.get("cards", [])

        # 7. Post-process: filter question types, assign IDs, attach images
        total_questions = 0
        for ci, card in enumerate(raw_cards):
            card["index"] = ci
            # Filter to only mcq and true_false, cap at 2 each (1 primary + 1 backup)
            questions = card.get("questions", [])
            mcq_qs = [q for q in questions if q.get("type") == "mcq"][:2]
            tf_qs = [q for q in questions if q.get("type") == "true_false"][:2]
            # Assign typed IDs
            for mi, q in enumerate(mcq_qs):
                q["id"] = f"c{ci}_mcq_{mi}"
            for ti, q in enumerate(tf_qs):
                q["id"] = f"c{ci}_tf_{ti}"
            card["questions"] = mcq_qs + tf_qs
            total_questions += len(card["questions"])

            # Map image_indices to actual image objects with captions
            card_images = []
            for idx in card.get("image_indices", []):
                if 1 <= idx <= len(useful_images):
                    img_copy = dict(useful_images[idx - 1])
                    img_copy["caption"] = f"Diagram for: {card.get('title', '')}"
                    card_images.append(img_copy)
            card["images"] = card_images
            # Remove raw image_indices from response
            card.pop("image_indices", None)

        result = {
            "session_id": str(session.id),
            "concept_id": session.concept_id,
            "concept_title": concept_title,
            "style": session.style,
            "phase": session.phase,
            "cards": raw_cards,
            "total_questions": total_questions,
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
                print(f"[cards-single] Empty response (attempt {attempt+1})")
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
                print(f"[cards-single] JSON parse failed (attempt {attempt+1}): {e}")
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
                concept_title = cached.get("concept_title", session.concept_id)
                cards = cached.get("cards", [])
                if 0 <= card_index < len(cards):
                    card_title = cards[card_index].get("title", card_title)
                    card_content = cards[card_index].get("content", "")
            except (json.JSONDecodeError, TypeError):
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

    @staticmethod
    def _parse_assessment(text: str) -> tuple[bool, int | None]:
        """Check if AI included [ASSESSMENT:XX] marker."""
        match = re.search(r'\[ASSESSMENT:(\d+)\]', text)
        if match:
            return True, int(match.group(1))
        return False, None
