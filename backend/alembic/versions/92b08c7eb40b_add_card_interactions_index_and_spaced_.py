"""add_card_interactions_index_and_spaced_reviews_unique

Revision ID: 92b08c7eb40b
Revises: e3c02cf4c22e
Create Date: 2026-02-28 11:48:43.196800

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92b08c7eb40b'
down_revision: Union[str, Sequence[str], None] = 'e3c02cf4c22e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Adds:
    1. Composite index on card_interactions(student_id, completed_at DESC)
       — speeds up load_student_history() aggregate and LIMIT 5 trend queries.
    2. Unique constraint on spaced_reviews(student_id, concept_id, review_number)
       — prevents duplicate review rows when a student re-masters a concept.
    """
    # Composite index: covers both the aggregate (WHERE student_id=X) and
    # the trend query (ORDER BY completed_at DESC LIMIT 5).
    op.create_index(
        "ix_card_interactions_student_completed",
        "card_interactions",
        ["student_id", sa.text("completed_at DESC")],
    )

    # Unique constraint: idempotent inserts via ON CONFLICT DO NOTHING.
    op.create_unique_constraint(
        "uq_spaced_review_student_concept_number",
        "spaced_reviews",
        ["student_id", "concept_id", "review_number"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_spaced_review_student_concept_number",
        "spaced_reviews",
        type_="unique",
    )
    op.drop_index(
        "ix_card_interactions_student_completed",
        table_name="card_interactions",
    )
