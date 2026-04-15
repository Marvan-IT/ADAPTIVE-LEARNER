"""Add gamification system: daily streak, xp_events, student_badges

Revision ID: 015_gamification_system
Revises: 014_add_performance_indexes
Create Date: 2026-04-13

Design notes:
- students.daily_streak / daily_streak_best: replace the existing
  `streak` column (which counted lesson-days loosely) with two precise
  columns. daily_streak is reset to 0 on a missed day; daily_streak_best
  is only ever increased, giving a permanent personal record.
- students.last_active_date: Date (no time component) — the calendar date
  of the student's most recent XP-earning activity. Used by the streak
  update logic to detect day boundaries without timezone ambiguity.
- card_interactions.difficulty: SmallInteger 1–5 set by the adaptive
  engine at card generation time. Nullable so existing rows are unaffected
  and the engine can leave it NULL when difficulty is not yet determined.
- xp_events: append-only audit log of every XP award. multiplier captures
  streak / bonus modifiers; final_xp = base_xp * multiplier (rounded).
  metadata JSONB holds context-specific payload (e.g. badge earned,
  mastery concept, streak milestone).
- student_badges: one row per (student, badge_key) pair; the UNIQUE
  constraint on (student_id, badge_key) makes badge awards idempotent —
  application code can INSERT … ON CONFLICT DO NOTHING.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "015_gamification_system"
down_revision: Union[str, Sequence[str], None] = "014_add_performance_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    """Check if a column already exists in a PostgreSQL table."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return result.scalar() is not None


def _table_exists(table: str) -> bool:
    """Check if a table already exists in the database."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :table"
        ),
        {"table": table},
    )
    return result.scalar() is not None


def upgrade() -> None:
    # ── students: streak tracking columns ────────────────────────────────────
    if not _column_exists("students", "daily_streak"):
        op.add_column(
            "students",
            sa.Column(
                "daily_streak",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
    if not _column_exists("students", "daily_streak_best"):
        op.add_column(
            "students",
            sa.Column(
                "daily_streak_best",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
    if not _column_exists("students", "last_active_date"):
        op.add_column(
            "students",
            sa.Column(
                "last_active_date",
                sa.Date(),
                nullable=True,
            ),
        )

    # ── card_interactions: per-card difficulty tag ────────────────────────────
    if not _column_exists("card_interactions", "difficulty"):
        op.add_column(
            "card_interactions",
            sa.Column(
                "difficulty",
                sa.SmallInteger(),
                nullable=True,
            ),
        )

    # ── xp_events: append-only XP audit log ──────────────────────────────────
    if not _table_exists("xp_events"):
        op.create_table(
            "xp_events",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "student_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("students.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "session_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("teaching_sessions.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "interaction_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("card_interactions.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("event_type", sa.String(30), nullable=False),
            sa.Column("base_xp", sa.Integer(), nullable=False),
            sa.Column(
                "multiplier",
                sa.Float(),
                nullable=False,
                server_default="1.0",
            ),
            sa.Column("final_xp", sa.Integer(), nullable=False),
            sa.Column("metadata", postgresql.JSONB(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    # ── student_badges: awarded badge log with idempotency guarantee ──────────
    if not _table_exists("student_badges"):
        op.create_table(
            "student_badges",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "student_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("students.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("badge_key", sa.String(50), nullable=False),
            sa.Column(
                "awarded_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("metadata", postgresql.JSONB(), nullable=True),
            sa.UniqueConstraint("student_id", "badge_key", name="uq_student_badges_student_badge"),
        )

    # ── indexes ───────────────────────────────────────────────────────────────
    # xp_events: time-range XP sum queries per student (leaderboard, weekly XP)
    op.create_index(
        "ix_xp_events_student_created",
        "xp_events",
        ["student_id", "created_at"],
        if_not_exists=True,
    )
    # xp_events: filter by event type for badge/streak trigger queries
    op.create_index(
        "ix_xp_events_student_type",
        "xp_events",
        ["student_id", "event_type"],
        if_not_exists=True,
    )
    # student_badges: all badges for a student (profile / badge showcase)
    op.create_index(
        "ix_student_badges_student",
        "student_badges",
        ["student_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    """Remove all gamification additions in reverse dependency order.

    Indexes are dropped implicitly when their table is dropped, so only
    the indexes on existing tables need an explicit drop call.
    """
    # Tables first (indexes on these tables drop automatically)
    op.drop_table("student_badges")
    op.drop_table("xp_events")

    # Columns added to existing tables
    op.drop_column("card_interactions", "difficulty")
    op.drop_column("students", "last_active_date")
    op.drop_column("students", "daily_streak_best")
    op.drop_column("students", "daily_streak")
