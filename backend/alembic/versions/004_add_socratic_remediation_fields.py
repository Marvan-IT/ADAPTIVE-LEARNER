"""add_socratic_remediation_fields

Adds five new columns to teaching_sessions to track state across the
multi-attempt Socratic remediation loop, and three performance indexes
for the most common adaptive-engine query patterns.

New columns on teaching_sessions:
  - socratic_attempt_count  INTEGER NOT NULL DEFAULT 0
        Counts how many remediation+recheck cycles have run (max 3).
  - questions_asked         INTEGER NOT NULL DEFAULT 0
        Running counter of Socratic questions posed in this session.
  - questions_correct       FLOAT   NOT NULL DEFAULT 0.0
        Running accumulator of correct-answer scores (used for progress %).
  - best_check_score        INTEGER NULL
        Highest mastery-check score achieved across all attempts.
  - remediation_context     TEXT    NULL
        JSON-encoded list of topic areas that failed the last mastery check;
        consumed by the next remediation pass.

New indexes:
  - ix_card_interactions_student_concept  on card_interactions(student_id, concept_id)
        Speeds up per-student per-concept card history queries.
  - ix_sessions_student                   on teaching_sessions(student_id)
        Additional covering index for student-scoped session lookups.
  - ix_mastery_student                    on student_mastery(student_id)
        Additional covering index for student-scoped mastery queries.

Revision ID: 004_add_socratic_remediation_fields
Revises: 003_add_xp_streak_and_indices
Create Date: 2026-03-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004_socratic_remediation'
down_revision: Union[str, Sequence[str], None] = '003_add_xp_streak_and_indices'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    1. Add socratic_attempt_count INTEGER NOT NULL DEFAULT 0 to teaching_sessions.
    2. Add questions_asked INTEGER NOT NULL DEFAULT 0 to teaching_sessions.
    3. Add questions_correct FLOAT NOT NULL DEFAULT 0.0 to teaching_sessions.
    4. Add best_check_score INTEGER NULL to teaching_sessions.
    5. Add remediation_context TEXT NULL to teaching_sessions.
    6. Create composite index on card_interactions(student_id, concept_id).
    7. Create index on teaching_sessions(student_id) as ix_sessions_student.
    8. Create index on student_mastery(student_id) as ix_mastery_student.
    """
    # --- teaching_sessions: Socratic remediation state columns ---
    op.add_column(
        "teaching_sessions",
        sa.Column(
            "socratic_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "teaching_sessions",
        sa.Column(
            "questions_asked",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "teaching_sessions",
        sa.Column(
            "questions_correct",
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
    )
    op.add_column(
        "teaching_sessions",
        sa.Column(
            "best_check_score",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "teaching_sessions",
        sa.Column(
            "remediation_context",
            sa.Text(),
            nullable=True,
        ),
    )

    # --- card_interactions: composite index for per-student per-concept queries ---
    op.create_index(
        "ix_card_interactions_student_concept",
        "card_interactions",
        ["student_id", "concept_id"],
    )

    # --- teaching_sessions: additional student-scoped lookup index ---
    op.create_index(
        "ix_sessions_student",
        "teaching_sessions",
        ["student_id"],
    )

    # --- student_mastery: additional student-scoped lookup index ---
    op.create_index(
        "ix_mastery_student",
        "student_mastery",
        ["student_id"],
    )


def downgrade() -> None:
    """Downgrade schema.

    Reverses all changes in the reverse order of upgrade().
    """
    # Drop indexes first (no data dependency)
    op.drop_index("ix_mastery_student", table_name="student_mastery")
    op.drop_index("ix_sessions_student", table_name="teaching_sessions")
    op.drop_index("ix_card_interactions_student_concept", table_name="card_interactions")

    # Drop columns in reverse order of addition
    op.drop_column("teaching_sessions", "remediation_context")
    op.drop_column("teaching_sessions", "best_check_score")
    op.drop_column("teaching_sessions", "questions_correct")
    op.drop_column("teaching_sessions", "questions_asked")
    op.drop_column("teaching_sessions", "socratic_attempt_count")
