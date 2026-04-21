"""Add CHECK constraint on concept_chunks.chunk_type to enforce valid values.

Revision ID: 019_add_chunk_type_check_constraint
Revises: 018_add_support_tickets_and_messages
Create Date: 2026-04-21
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019_add_chunk_type_check_constraint"
down_revision: Union[str, None] = "018_add_support_tickets_and_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "ck_concept_chunks_chunk_type"
VALID_VALUES = ("teaching", "exercise", "lab", "chapter_intro", "chapter_review")


def upgrade() -> None:
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "concept_chunks",
        "chunk_type IN ('teaching', 'exercise', 'lab', 'chapter_intro', 'chapter_review')",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "concept_chunks", type_="check")
