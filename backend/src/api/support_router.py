"""
Support ticket endpoints for the Adaptive Learner platform.

Student endpoints (/api/v2/support/...):
    Authenticated students can create tickets, send replies, and view their own tickets.

Admin endpoints (/api/admin/support/...):
    Admins can view all tickets, reply, change status, and mark messages as read.

Rate limits mirror the rest of the API (limiter from api.rate_limiter).
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth.dependencies import get_current_user, require_admin
from auth.models import User
from db.connection import get_db
from db.models import Student, SupportTicket, SupportMessage
from api.rate_limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["support"])


# ── Pydantic schemas ───────────────────────────────────────────────────────────

class CreateTicketRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=5000)


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)


class UpdateTicketStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(open|closed)$")


class MessageResponse(BaseModel):
    id: UUID
    ticket_id: UUID
    sender_role: str
    sender_name: str | None = None
    content: str
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TicketSummary(BaseModel):
    id: UUID
    subject: str
    status: str
    student_id: UUID | None = None
    student_name: str | None = None
    last_message_preview: str | None = None
    unread_count: int = 0
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class TicketDetailResponse(BaseModel):
    id: UUID
    subject: str
    status: str
    student_id: UUID | None = None
    student_name: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    messages: list[MessageResponse]


class UnreadCountResponse(BaseModel):
    count: int


# ── Internal helpers ───────────────────────────────────────────────────────────

async def _get_student_for_user(user: User, db: AsyncSession) -> Student:
    """Resolve the Student record owned by the authenticated user.

    Raises HTTP 403 if the user has no linked student profile (e.g. admin
    calling a student-only endpoint).
    """
    result = await db.execute(select(Student).where(Student.user_id == user.id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=403, detail="No student profile linked to this account")
    return student


async def _get_ticket_or_404(ticket_id: UUID, db: AsyncSession) -> SupportTicket:
    ticket = await db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


def _build_message_response(msg: SupportMessage, student_name: str | None = None) -> MessageResponse:
    """Convert a SupportMessage ORM object into a MessageResponse."""
    sender_name: str | None = None
    if msg.sender_role == "student" and student_name:
        sender_name = student_name
    elif msg.sender_role == "admin":
        try:
            sender_name = getattr(msg.sender, "email", None) if msg.sender else "Admin"
        except Exception:
            sender_name = "Admin"
    return MessageResponse(
        id=msg.id,
        ticket_id=msg.ticket_id,
        sender_role=msg.sender_role,
        sender_name=sender_name,
        content=msg.content,
        is_read=msg.is_read,
        created_at=msg.created_at,
    )


async def _build_ticket_summary(ticket: SupportTicket, db: AsyncSession, unread_role: str) -> TicketSummary:
    """Build a TicketSummary with last-message preview and unread count.

    unread_role: messages authored by this role are counted as unread
    (use 'admin' for the student view, 'student' for the admin view).
    """
    # Student name
    student_name: str | None = None
    student = await db.get(Student, ticket.student_id)
    if student:
        student_name = student.display_name

    # Last message
    last_msg_result = await db.execute(
        select(SupportMessage.content)
        .where(SupportMessage.ticket_id == ticket.id)
        .order_by(SupportMessage.created_at.desc())
        .limit(1)
    )
    last_content = last_msg_result.scalar_one_or_none()
    preview = last_content[:120] if last_content else None

    # Unread count
    unread_result = await db.execute(
        select(func.count())
        .select_from(SupportMessage)
        .where(
            SupportMessage.ticket_id == ticket.id,
            SupportMessage.sender_role == unread_role,
            SupportMessage.is_read.is_(False),
        )
    )
    unread = unread_result.scalar() or 0

    return TicketSummary(
        id=ticket.id,
        subject=ticket.subject,
        status=ticket.status,
        student_id=ticket.student_id,
        student_name=student_name,
        last_message_preview=preview,
        unread_count=unread,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


# ═══════════════════════════════════════════════════════════════════
# STUDENT ENDPOINTS  (/api/v2/support/...)
# ═══════════════════════════════════════════════════════════════════

@limiter.limit("20/minute")
@router.post("/api/v2/support/tickets", status_code=201)
async def create_ticket(
    request: Request,
    req: CreateTicketRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new support ticket with an initial message."""
    student = await _get_student_for_user(user, db)

    ticket = SupportTicket(
        student_id=student.id,
        subject=req.subject,
        status="open",
    )
    db.add(ticket)
    await db.flush()  # populate ticket.id

    message = SupportMessage(
        ticket_id=ticket.id,
        sender_id=user.id,
        sender_role="student",
        content=req.message,
        is_read=False,
    )
    db.add(message)
    await db.commit()
    await db.refresh(ticket)

    logger.info(
        "[support] ticket created ticket_id=%s student_id=%s subject=%r",
        ticket.id, student.id, req.subject,
    )
    return {
        "ticket_id": str(ticket.id),
        "subject": ticket.subject,
        "status": ticket.status,
        "created_at": ticket.created_at.isoformat(),
    }


@limiter.limit("60/minute")
@router.get("/api/v2/support/tickets")
async def list_student_tickets(
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List the authenticated student's tickets, newest first."""
    student = await _get_student_for_user(user, db)

    result = await db.execute(
        select(SupportTicket)
        .where(SupportTicket.student_id == student.id)
        .order_by(SupportTicket.updated_at.desc(), SupportTicket.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    tickets = result.scalars().all()

    summaries = []
    for ticket in tickets:
        summaries.append(await _build_ticket_summary(ticket, db, unread_role="admin"))

    return summaries


@limiter.limit("60/minute")
@router.get("/api/v2/support/tickets/{ticket_id}", response_model=TicketDetailResponse)
async def get_student_ticket(
    request: Request,
    ticket_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single ticket with its full message thread.

    Marks all admin messages in this ticket as read upon retrieval.
    """
    student = await _get_student_for_user(user, db)
    ticket = await _get_ticket_or_404(ticket_id, db)

    if ticket.student_id != student.id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Mark all admin messages in this ticket as read
    await db.execute(
        update(SupportMessage)
        .where(
            SupportMessage.ticket_id == ticket_id,
            SupportMessage.sender_role == "admin",
            SupportMessage.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.commit()
    await db.refresh(ticket)

    # Eagerly load sender for sender_name resolution
    msgs_result = await db.execute(
        select(SupportMessage)
        .options(selectinload(SupportMessage.sender))
        .where(SupportMessage.ticket_id == ticket_id)
        .order_by(SupportMessage.created_at)
    )
    messages = msgs_result.scalars().all()

    return TicketDetailResponse(
        id=ticket.id,
        subject=ticket.subject,
        status=ticket.status,
        student_id=ticket.student_id,
        student_name=student.display_name,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        messages=[_build_message_response(m, student.display_name) for m in messages],
    )


@limiter.limit("20/minute")
@router.post("/api/v2/support/tickets/{ticket_id}/messages", status_code=201)
async def send_student_message(
    request: Request,
    ticket_id: UUID,
    req: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Append a student reply to an existing ticket."""
    student = await _get_student_for_user(user, db)
    ticket = await _get_ticket_or_404(ticket_id, db)

    if ticket.student_id != student.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if ticket.status == "closed":
        raise HTTPException(
            status_code=409, detail="Cannot reply to a closed ticket. Please open a new ticket."
        )

    message = SupportMessage(
        ticket_id=ticket_id,
        sender_id=user.id,
        sender_role="student",
        content=req.content,
        is_read=False,
    )
    db.add(message)

    # Touch updated_at on the parent ticket so it sorts to the top
    await db.execute(
        update(SupportTicket)
        .where(SupportTicket.id == ticket_id)
        .values(updated_at=func.now())
    )
    await db.commit()
    await db.refresh(message)

    logger.info(
        "[support] student reply ticket_id=%s student_id=%s",
        ticket_id, student.id,
    )
    return {"message_id": str(message.id), "created_at": message.created_at.isoformat()}


@limiter.limit("60/minute")
@router.get("/api/v2/support/unread-count", response_model=UnreadCountResponse)
async def student_unread_count(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the count of unread admin messages across all of the student's tickets."""
    student = await _get_student_for_user(user, db)

    result = await db.execute(
        select(func.count())
        .select_from(SupportMessage)
        .join(SupportTicket, SupportMessage.ticket_id == SupportTicket.id)
        .where(
            SupportTicket.student_id == student.id,
            SupportMessage.sender_role == "admin",
            SupportMessage.is_read.is_(False),
        )
    )
    count = result.scalar() or 0
    return UnreadCountResponse(count=count)


# ═══════════════════════════════════════════════════════════════════
# ADMIN ENDPOINTS  (/api/admin/support/...)
# ═══════════════════════════════════════════════════════════════════

@limiter.limit("60/minute")
@router.get("/api/admin/support/tickets")
async def admin_list_tickets(
    request: Request,
    status: str | None = Query(default=None, pattern="^(open|closed)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """List all support tickets, optionally filtered by status, newest first."""
    query = select(SupportTicket).order_by(
        SupportTicket.updated_at.desc(), SupportTicket.created_at.desc()
    )
    if status:
        query = query.where(SupportTicket.status == status)
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    tickets = result.scalars().all()

    summaries = []
    for ticket in tickets:
        # For the admin view, unread = student messages the admin hasn't read yet
        summaries.append(await _build_ticket_summary(ticket, db, unread_role="student"))
    return summaries


@limiter.limit("60/minute")
@router.get("/api/admin/support/tickets/{ticket_id}", response_model=TicketDetailResponse)
async def admin_get_ticket(
    request: Request,
    ticket_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Get any ticket with its full message thread."""
    logger.info("[admin-support] GET ticket detail ticket_id=%s", ticket_id)
    ticket = await _get_ticket_or_404(ticket_id, db)

    # Resolve student display name
    student_name: str | None = None
    student = await db.get(Student, ticket.student_id)
    if student:
        student_name = student.display_name

    msgs_result = await db.execute(
        select(SupportMessage)
        .options(selectinload(SupportMessage.sender))
        .where(SupportMessage.ticket_id == ticket_id)
        .order_by(SupportMessage.created_at)
    )
    messages = msgs_result.scalars().all()
    logger.info("[admin-support] returning %d messages for ticket %s, student=%s", len(messages), ticket_id, student_name)

    return TicketDetailResponse(
        id=ticket.id,
        subject=ticket.subject,
        status=ticket.status,
        student_id=ticket.student_id,
        student_name=student_name,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        messages=[_build_message_response(m, student_name) for m in messages],
    )


@limiter.limit("20/minute")
@router.post("/api/admin/support/tickets/{ticket_id}/messages", status_code=201)
async def admin_send_message(
    request: Request,
    ticket_id: UUID,
    req: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Send an admin reply to a support ticket."""
    ticket = await _get_ticket_or_404(ticket_id, db)

    message = SupportMessage(
        ticket_id=ticket_id,
        sender_id=user.id,
        sender_role="admin",
        content=req.content,
        is_read=False,
    )
    db.add(message)

    # Touch updated_at on the parent ticket
    await db.execute(
        update(SupportTicket)
        .where(SupportTicket.id == ticket_id)
        .values(updated_at=func.now())
    )
    await db.commit()
    await db.refresh(message)

    logger.info(
        "[support] admin reply ticket_id=%s admin_user_id=%s",
        ticket_id, user.id,
    )
    return {"message_id": str(message.id), "created_at": message.created_at.isoformat()}


@limiter.limit("30/minute")
@router.patch("/api/admin/support/tickets/{ticket_id}/status")
async def admin_update_ticket_status(
    request: Request,
    ticket_id: UUID,
    req: UpdateTicketStatusRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Open or close a support ticket."""
    ticket = await _get_ticket_or_404(ticket_id, db)

    if ticket.status == req.status:
        return {"ticket_id": str(ticket_id), "status": ticket.status}

    await db.execute(
        update(SupportTicket)
        .where(SupportTicket.id == ticket_id)
        .values(status=req.status, updated_at=func.now())
    )
    await db.commit()

    logger.info(
        "[support] ticket status changed ticket_id=%s status=%s",
        ticket_id, req.status,
    )
    return {"ticket_id": str(ticket_id), "status": req.status}


@limiter.limit("30/minute")
@router.patch("/api/admin/support/tickets/{ticket_id}/read")
async def admin_mark_ticket_read(
    request: Request,
    ticket_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Mark all student messages in a ticket as read (admin has seen them)."""
    await _get_ticket_or_404(ticket_id, db)  # ensure ticket exists

    result = await db.execute(
        update(SupportMessage)
        .where(
            SupportMessage.ticket_id == ticket_id,
            SupportMessage.sender_role == "student",
            SupportMessage.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.commit()

    marked = result.rowcount or 0
    logger.info(
        "[support] admin marked %d messages read for ticket_id=%s",
        marked, ticket_id,
    )
    return {"ticket_id": str(ticket_id), "marked_read": marked}


@limiter.limit("60/minute")
@router.get("/api/admin/support/unread-count", response_model=UnreadCountResponse)
async def admin_unread_count(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Return the total count of unread student messages across ALL tickets."""
    result = await db.execute(
        select(func.count())
        .select_from(SupportMessage)
        .where(
            SupportMessage.sender_role == "student",
            SupportMessage.is_read.is_(False),
        )
    )
    count = result.scalar() or 0
    return UnreadCountResponse(count=count)
