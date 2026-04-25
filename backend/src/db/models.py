"""
SQLAlchemy ORM models for Week 2: The Pedagogical Loop.
Tables: students, teaching_sessions, conversation_messages, student_mastery.
"""

import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    String, Text, Boolean, SmallInteger, Integer, Float, DateTime, Date,
    ForeignKey, UniqueConstraint, CheckConstraint, Column, Index, func, text,
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB, TIMESTAMP as TIMESTAMPTZ
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

if TYPE_CHECKING:
    from auth.models import User


class Base(DeclarativeBase):
    pass


class Student(Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    interests: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    custom_interests: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False)
    preferred_style: Mapped[str] = mapped_column(String(20), default="default")
    preferred_language: Mapped[str] = mapped_column(String(10), default="en")
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    xp: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    daily_streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    daily_streak_best: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_active_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ── Adaptive learning extended history ────────────────────────────────
    section_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    overall_accuracy_rate: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5", nullable=False)
    preferred_analogy_style: Mapped[str | None] = mapped_column(String(50), nullable=True)
    boredom_pattern: Mapped[str | None] = mapped_column(String(20), nullable=True)
    frustration_tolerance: Mapped[str | None] = mapped_column(String(20), default="medium", server_default=text("'medium'"), nullable=True)
    recovery_speed: Mapped[str | None] = mapped_column(String(20), default="normal", server_default=text("'normal'"), nullable=True)
    avg_state_score: Mapped[float] = mapped_column(Float, default=2.0, server_default=text("2.0"), nullable=False)
    effective_analogies: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False)
    effective_engagement: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False)
    ineffective_engagement: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False)
    state_distribution: Mapped[dict] = mapped_column(
        JSONB,
        default=lambda: {"struggling": 0, "normal": 0, "fast": 0},
        server_default=text("'{\"struggling\": 0, \"normal\": 0, \"fast\": 0}'::jsonb"),
        nullable=False,
    )

    # ── Auth link ─────────────────────────────────────────────────────────────
    # Nullable so that legacy Student rows (created before auth was added) are
    # not broken.  SET NULL on user delete keeps the learning history intact.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    user: Mapped["User"] = relationship(back_populates="student")

    sessions: Mapped[list["TeachingSession"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    mastery_records: Mapped[list["StudentMastery"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    card_interactions: Mapped[list["CardInteraction"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    spaced_reviews: Mapped[list["SpacedReview"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    xp_events: Mapped[list["XpEvent"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    badges: Mapped[list["StudentBadge"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    support_tickets: Mapped[list["SupportTicket"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )


class TeachingSession(Base):
    __tablename__ = "teaching_sessions"
    __table_args__ = (
        Index("ix_teaching_sessions_student_started", "student_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )
    concept_id: Mapped[str] = mapped_column(String(200), nullable=False)
    book_slug: Mapped[str] = mapped_column(String(50))
    phase: Mapped[str] = mapped_column(String(20), default="PRESENTING")
    style: Mapped[str] = mapped_column(String(20), default="default")
    lesson_interests: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    presentation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    check_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    concept_mastered: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Socratic remediation tracking ─────────────────────────────────────
    # Valid phase values:
    #   PRESENTING, CARDS, CARDS_DONE, CHECKING, REMEDIATING, RECHECKING,
    #   REMEDIATING_2, RECHECKING_2, COMPLETED
    # (phase is stored as a plain String — no DB-level enum constraint)
    socratic_attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    questions_asked: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    questions_correct: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0.0", nullable=False
    )
    best_check_score: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    remediation_context: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )

    # ── Chunk-based architecture tracking ─────────────────────────────────
    chunk_index: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    chunk_progress: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default=None,
        comment="Per-chunk learning progress: {chunk_id: {mode, score, correct, total, completed_at}}"
    )

    student: Mapped["Student"] = relationship(back_populates="sessions")
    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.message_order",
    )
    card_interactions: Mapped[list["CardInteraction"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teaching_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    message_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    session: Mapped["TeachingSession"] = relationship(back_populates="messages")


class StudentMastery(Base):
    __tablename__ = "student_mastery"
    __table_args__ = (
        UniqueConstraint("student_id", "concept_id", name="uq_student_concept"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )
    concept_id: Mapped[str] = mapped_column(String(200), nullable=False)
    mastered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teaching_sessions.id"),
        nullable=True,
    )

    student: Mapped["Student"] = relationship(back_populates="mastery_records")


class CardInteraction(Base):
    """Records a student's interaction with a single flashcard during a session.

    Captured by the adaptive card-learning view to drive hint/adaptation logic
    and feed into spaced-repetition scheduling.
    """

    __tablename__ = "card_interactions"
    __table_args__ = (
        Index("ix_card_interactions_student_concept", "student_id", "concept_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teaching_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    concept_id: Mapped[str] = mapped_column(String(200), nullable=False)
    card_index: Mapped[int] = mapped_column(Integer, nullable=False)
    time_on_card_sec: Mapped[float] = mapped_column(Float, default=0.0)
    wrong_attempts: Mapped[int] = mapped_column(Integer, default=0)
    selected_wrong_option: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    hints_used: Mapped[int] = mapped_column(Integer, default=0)
    idle_triggers: Mapped[int] = mapped_column(Integer, default=0)
    adaptation_applied: Mapped[str | None] = mapped_column(String(200), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # ── Engagement tracking ───────────────────────────────────────────────
    engagement_signal: Mapped[str | None] = mapped_column(String(50), nullable=True)
    strategy_applied: Mapped[str | None] = mapped_column(String(50), nullable=True)
    strategy_effective: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    difficulty: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    session: Mapped["TeachingSession"] = relationship(back_populates="card_interactions")
    student: Mapped["Student"] = relationship(back_populates="card_interactions")


class SpacedReview(Base):
    """Tracks a spaced-repetition review event for a student-concept pair.

    review_number increments each time the student reviews a mastered concept.
    due_at is computed by the SR scheduler (e.g. SM-2 algorithm).
    completed_at is NULL until the student completes the review.
    """

    __tablename__ = "spaced_reviews"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "concept_id", "review_number",
            name="uq_spaced_review_student_concept_number",
        ),
        Index(
            "ix_spaced_reviews_student_due_pending",
            "student_id", "due_at",
            postgresql_where=text("completed_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    concept_id: Mapped[str] = mapped_column(String(200), nullable=False)
    review_number: Mapped[int] = mapped_column(SmallInteger, default=1)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    student: Mapped["Student"] = relationship(back_populates="spaced_reviews")


class ConceptChunk(Base):
    __tablename__ = "concept_chunks"
    __table_args__ = (
        Index("ix_concept_chunks_book_concept", "book_slug", "concept_id"),
        Index("ix_concept_chunks_book_concept_order", "book_slug", "concept_id", "order_index"),
    )

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    book_slug   = Column(Text, nullable=False)
    concept_id  = Column(Text, nullable=False)
    section     = Column(Text, nullable=False)
    order_index = Column(Integer, nullable=False)
    heading     = Column(Text, nullable=False)
    text        = Column(Text, nullable=False)
    latex       = Column(ARRAY(Text), server_default="{}")
    chunk_type  = Column(Text, nullable=False, server_default="teaching")
    is_optional = Column(Boolean, nullable=False, server_default="false")
    is_hidden   = Column(Boolean, nullable=False, server_default="false")
    exam_disabled = Column(Boolean, nullable=False, server_default="false")
    chunk_type_locked = Column(Boolean, default=False, server_default="false", nullable=False)
    admin_section_name = Column(Text, nullable=True)
    admin_section_name_translations = Column(JSONB, nullable=False, server_default="'{}'::jsonb")
    embedding   = Column(Vector(1536), nullable=True)
    created_at  = Column(TIMESTAMPTZ(timezone=True), server_default=func.now())
    heading_translations = Column(JSONB, nullable=False, server_default="'{}'::jsonb")

    images = relationship("ChunkImage", back_populates="chunk", cascade="all, delete-orphan")


class ChunkImage(Base):
    __tablename__ = "chunk_images"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chunk_id    = Column(UUID(as_uuid=True), ForeignKey("concept_chunks.id", ondelete="CASCADE"), nullable=False, index=True)
    image_url   = Column(Text, nullable=False)
    caption     = Column(Text, nullable=True)
    order_index = Column(Integer, default=0)
    caption_translations = Column(JSONB, nullable=False, server_default="'{}'::jsonb")

    chunk = relationship("ConceptChunk", back_populates="images")


class Book(Base):
    __tablename__ = "books"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    book_slug    = Column(Text, unique=True, nullable=False)
    title        = Column(Text, nullable=False)
    subject      = Column(Text, nullable=False)
    status       = Column(Text, nullable=False, default="PROCESSING")
    pdf_filename = Column(Text, nullable=True)
    is_hidden    = Column(Boolean, nullable=False, server_default="false")
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    published_at = Column(DateTime(timezone=True), nullable=True)
    title_translations   = Column(JSONB, nullable=False, server_default="'{}'::jsonb")
    subject_translations = Column(JSONB, nullable=False, server_default="'{}'::jsonb")


class Subject(Base):
    __tablename__ = "subjects"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug       = Column(Text, unique=True, nullable=False)
    label      = Column(Text, nullable=False)
    is_hidden  = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    label_translations = Column(JSONB, nullable=False, server_default="'{}'::jsonb")


class AdminGraphOverride(Base):
    """Manual edge additions or removals applied on top of the auto-generated
    dependency graph.  Each override is scoped to a single book and records
    which admin created it."""

    __tablename__ = "admin_graph_overrides"
    __table_args__ = (
        UniqueConstraint(
            "book_slug", "action", "source_concept", "target_concept",
            name="uq_graph_override",
        ),
        CheckConstraint(
            "action IN ('add_edge', 'remove_edge')",
            name="ck_graph_override_action",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    book_slug: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # 'add_edge' or 'remove_edge'
    source_concept: Mapped[str] = mapped_column(Text, nullable=False)
    target_concept: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), server_default=func.now()
    )


class AdminConfig(Base):
    """Platform-wide admin configuration stored as key/value pairs.

    Tracks which admin last changed each setting and when."""

    __tablename__ = "admin_config"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), server_default=func.now()
    )


class XpEvent(Base):
    """Append-only audit log of every XP award.

    multiplier captures streak/bonus modifiers applied to base_xp.
    final_xp = round(base_xp * multiplier), minimum 1.
    metadata_ maps to the DB column 'metadata' (JSONB) to avoid clashing
    with SQLAlchemy's Base.metadata attribute.
    """

    __tablename__ = "xp_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teaching_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("card_interactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    base_xp: Mapped[int] = mapped_column(Integer, nullable=False)
    multiplier: Mapped[float] = mapped_column(
        Float, default=1.0, server_default="1.0", nullable=False
    )
    final_xp: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        index=True,
    )

    student: Mapped["Student"] = relationship(back_populates="xp_events")


class StudentBadge(Base):
    """One row per (student, badge_key) pair.

    The unique constraint on (student_id, badge_key) makes badge awards
    idempotent — the badge_engine can INSERT … ON CONFLICT DO NOTHING.
    metadata_ maps to the DB column 'metadata' (JSONB).
    """

    __tablename__ = "student_badges"
    __table_args__ = (
        UniqueConstraint("student_id", "badge_key", name="uq_student_badges_student_badge"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )
    badge_key: Mapped[str] = mapped_column(String(50), nullable=False)
    awarded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        index=True,
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )

    student: Mapped["Student"] = relationship(back_populates="badges")


class SupportTicket(Base):
    """A help/support request raised by a student.

    Messages are threaded under a ticket and may be authored by either
    the student or an admin.  Tickets start in 'open' status and are
    manually closed by an admin once resolved.
    """

    __tablename__ = "support_tickets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    student: Mapped["Student"] = relationship(back_populates="support_tickets")
    messages: Mapped[list["SupportMessage"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="SupportMessage.created_at",
    )


class SupportMessage(Base):
    """A single message within a support ticket thread.

    sender_id is nullable so that messages survive if the sender's user
    account is deleted (SET NULL).  sender_role records who wrote the
    message ('student' or 'admin') independently of the FK.
    """

    __tablename__ = "support_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    ticket: Mapped["SupportTicket"] = relationship(back_populates="messages")
    sender: Mapped["User | None"] = relationship()


class AdminAuditLog(Base):
    """Immutable audit record for every admin mutation that supports undo/redo.

    Rows are never deleted by application code; only the retention background
    task (purge_old_audits_per_admin) prunes old rows beyond the keep limit.
    The self-referential ``redo_of`` FK forms a singly-linked redo chain.
    """

    __tablename__ = "admin_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str] = mapped_column(Text, nullable=False)
    book_slug: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    new_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    affected_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    undone_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    undone_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    redo_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_audit_logs.id", ondelete="SET NULL"),
        nullable=True,
    )


# Register auth tables with Base.metadata so Alembic autogenerate and
# SQLAlchemy relationship resolution both see them.  This import must come
# AFTER the Base class is defined above.
import auth.models  # noqa: E402, F401
