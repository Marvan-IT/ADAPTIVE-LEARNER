"""
SQLAlchemy ORM models for Week 2: The Pedagogical Loop.
Tables: students, teaching_sessions, conversation_messages, student_mastery.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String, Text, Boolean, SmallInteger, Integer, Float, DateTime,
    ForeignKey, UniqueConstraint, Column, func,
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB, TIMESTAMP as TIMESTAMPTZ
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    pass


class Student(Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    interests: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    preferred_style: Mapped[str] = mapped_column(String(20), default="default")
    preferred_language: Mapped[str] = mapped_column(String(10), default="en")
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

    # ── Adaptive learning extended history ────────────────────────────────
    section_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    overall_accuracy_rate: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5", nullable=False)
    preferred_analogy_style: Mapped[str | None] = mapped_column(String(50), nullable=True)
    boredom_pattern: Mapped[str | None] = mapped_column(String(20), nullable=True)
    frustration_tolerance: Mapped[str | None] = mapped_column(String(20), default="medium", server_default="'medium'", nullable=True)
    recovery_speed: Mapped[str | None] = mapped_column(String(20), default="normal", server_default="'normal'", nullable=True)
    avg_state_score: Mapped[float] = mapped_column(Float, default=2.0, server_default="2.0", nullable=False)
    effective_analogies: Mapped[list] = mapped_column(JSONB, default=list, server_default="'[]'::jsonb", nullable=False)
    effective_engagement: Mapped[list] = mapped_column(JSONB, default=list, server_default="'[]'::jsonb", nullable=False)
    ineffective_engagement: Mapped[list] = mapped_column(JSONB, default=list, server_default="'[]'::jsonb", nullable=False)
    state_distribution: Mapped[dict] = mapped_column(
        JSONB,
        default=lambda: {"struggling": 0, "normal": 0, "fast": 0},
        server_default='\'{"struggling": 0, "normal": 0, "fast": 0}\'::jsonb',
        nullable=False,
    )

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


class TeachingSession(Base):
    __tablename__ = "teaching_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )
    concept_id: Mapped[str] = mapped_column(String(200), nullable=False)
    book_slug: Mapped[str] = mapped_column(String(50), default="prealgebra")
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teaching_sessions.id", ondelete="CASCADE"), nullable=False
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
    embedding   = Column(Vector(1536), nullable=True)
    created_at  = Column(TIMESTAMPTZ(timezone=True), server_default=func.now())

    images = relationship("ChunkImage", back_populates="chunk", cascade="all, delete-orphan")


class ChunkImage(Base):
    __tablename__ = "chunk_images"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chunk_id    = Column(UUID(as_uuid=True), ForeignKey("concept_chunks.id", ondelete="CASCADE"), nullable=False)
    image_url   = Column(Text, nullable=False)
    caption     = Column(Text, nullable=True)
    order_index = Column(Integer, default=0)

    chunk = relationship("ConceptChunk", back_populates="images")
