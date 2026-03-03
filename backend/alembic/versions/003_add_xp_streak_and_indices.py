"""add_xp_streak_and_indices

Adds xp and streak columns to the students table, and creates lookup indices
on the three highest-traffic FK columns to support paginated and filtered
queries in the adaptive engine without sequential scans.

Revision ID: 003_add_xp_streak_and_indices
Revises: 92b08c7eb40b
Create Date: 2026-03-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_add_xp_streak_and_indices'
down_revision: Union[str, Sequence[str], None] = '92b08c7eb40b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    1. Add xp INTEGER NOT NULL DEFAULT 0 to students.
    2. Add streak INTEGER NOT NULL DEFAULT 0 to students.
    3. Create index on teaching_sessions(student_id).
    4. Create index on conversation_messages(session_id).
    5. Create index on student_mastery(student_id).
    """
    # --- students: gamification columns ---
    op.add_column(
        "students",
        sa.Column("xp", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "students",
        sa.Column("streak", sa.Integer(), nullable=False, server_default="0"),
    )

    # --- teaching_sessions: speed up per-student session lookups ---
    op.create_index(
        "ix_teaching_sessions_student_id",
        "teaching_sessions",
        ["student_id"],
    )

    # --- conversation_messages: speed up per-session message fetches ---
    op.create_index(
        "ix_conversation_messages_session_id",
        "conversation_messages",
        ["session_id"],
    )

    # --- student_mastery: speed up per-student mastery queries ---
    op.create_index(
        "ix_student_mastery_student_id",
        "student_mastery",
        ["student_id"],
    )


def downgrade() -> None:
    """Downgrade schema.

    Reverses all changes in the reverse order of upgrade().
    """
    op.drop_index("ix_student_mastery_student_id", table_name="student_mastery")
    op.drop_index("ix_conversation_messages_session_id", table_name="conversation_messages")
    op.drop_index("ix_teaching_sessions_student_id", table_name="teaching_sessions")
    op.drop_column("students", "streak")
    op.drop_column("students", "xp")
