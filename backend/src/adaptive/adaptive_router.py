"""
FastAPI router for the Adaptive Learning Generation Engine.
Registered at prefix /api/v3 in main.py.

Injection pattern: module-level globals (adaptive_knowledge_svc,
adaptive_llm_client) are set by main.py's lifespan context manager,
identical to the pattern used in api/teaching_router.py.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import APIRouter, Depends, HTTPException, Request
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uuid import UUID

from auth.dependencies import get_current_user
from auth.models import User
from adaptive.schemas import AdaptiveLessonRequest, AdaptiveLesson, NextCardRequest, NextCardResponse
from adaptive.adaptive_engine import generate_adaptive_lesson, generate_recovery_card
from api.rate_limiter import limiter
from db.connection import get_db
from db.models import Student, StudentMastery
from config import ADAPTIVE_CARD_MODEL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3", tags=["adaptive"])

# NOTE: The duplicate /api/v2/sessions/{id}/complete-card endpoint (cards_router)
# has been removed — teaching_router owns that route. See git history for the old code.

# ── Service references — injected by main.py lifespan ─────────────────────────
# Set to None here; main.py assigns real instances after startup.
adaptive_chunk_ksvc = None               # ChunkKnowledgeService (injected by main.py)
adaptive_llm_client: AsyncOpenAI | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/adaptive/lesson",
    response_model=AdaptiveLesson,
    summary="Generate an adaptive lesson",
    description=(
        "Analyse a student's analytics signals, classify their learning profile, "
        "derive generation parameters, optionally insert prerequisite remediation "
        "cards, and call the LLM to produce a fully personalised lesson."
    ),
)
@limiter.limit("10/minute")
async def generate_lesson(
    request: Request,
    req: AdaptiveLessonRequest,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdaptiveLesson:
    """
    POST /api/v3/adaptive/lesson

    Steps:
      1. Verify the student exists in the DB (returns 404 if not).
      2. Load the student's mastery state in a single bulk SELECT (no N+1).
      3. Call generate_adaptive_lesson() from the engine module.

    Error responses:
      404 — student_id not found in the students table
      404 — concept_id not found in KnowledgeService (raised by engine as ValueError)
      502 — LLM failed after all retries (raised by engine as ValueError)
      500 — unexpected internal error
    """
    # 1. Verify student exists
    student = await db.get(Student, req.student_id)
    if student is None:
        raise HTTPException(
            status_code=404,
            detail=f"Student not found: {req.student_id}",
        )

    # 1b. Verify ownership — user must own this student (unless admin)
    if _user.role != "admin":
        from sqlalchemy import select as _sel
        _owned = (await db.execute(
            _sel(Student.id).where(Student.user_id == _user.id)
        )).scalar_one_or_none()
        if not _owned or _owned != req.student_id:
            raise HTTPException(status_code=403, detail="Access denied")

    # Resolve student's preferred language for LLM output
    language: str = getattr(student, "preferred_language", None) or "en"

    # 2. Bulk-load mastery state — one SELECT for all mastered concepts
    result = await db.execute(
        select(StudentMastery.concept_id).where(
            StudentMastery.student_id == req.student_id
        )
    )
    mastery_store: dict[str, bool] = {
        cid: True for cid in result.scalars().all()
    }
    logger.info(
        "Student %s has %d mastered concepts",
        req.student_id,
        len(mastery_store),
    )

    # 3. Delegate to the engine
    book_slug = getattr(req, "book_slug", None) or "prealgebra"
    try:
        lesson = await generate_adaptive_lesson(
            student_id=str(req.student_id),
            concept_id=req.concept_id,
            analytics_summary=req.analytics_summary,
            chunk_ksvc=adaptive_chunk_ksvc,
            book_slug=book_slug,
            db=db,
            mastery_store=mastery_store,
            llm_client=adaptive_llm_client,
            language=language,
        )
    except ValueError as exc:
        error_msg = str(exc)
        # Concept-not-found errors should be surfaced as 404
        if "Concept not found" in error_msg:
            logger.warning("Concept lookup failed: %s", error_msg)
            raise HTTPException(status_code=404, detail=error_msg)
        # LLM failures → 502
        logger.error("Adaptive engine error: %s", error_msg)
        raise HTTPException(status_code=502, detail=error_msg)
    except Exception as exc:
        logger.exception("Unexpected error in adaptive engine: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return lesson


# NOTE: The complete_card endpoint that was here has been removed.
# teaching_router.py owns POST /api/v2/sessions/{id}/complete-card.
# This avoids a duplicate route registration conflict.
# ── (end of file) ─────────────────────────────────────────────────────────────
_REMOVED_COMPLETE_CARD = True  # marker; old code in git history
