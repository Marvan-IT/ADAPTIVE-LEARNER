"""Add missing indexes for query performance.

Revision ID: 016_add_missing_indexes
Revises: 015_gamification_system
Create Date: 2026-04-13
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = "016_add_missing_indexes"
down_revision: Union[str, Sequence[str], None] = "015_gamification_system"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_conversation_messages_session_id",
        "conversation_messages",
        ["session_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_chunk_images_chunk_id",
        "chunk_images",
        ["chunk_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_card_interactions_session_id",
        "card_interactions",
        ["session_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_xp_events_created_at",
        "xp_events",
        ["created_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_student_badges_awarded_at",
        "student_badges",
        ["awarded_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_student_badges_awarded_at", table_name="student_badges")
    op.drop_index("ix_xp_events_created_at", table_name="xp_events")
    op.drop_index("ix_card_interactions_session_id", table_name="card_interactions")
    op.drop_index("ix_chunk_images_chunk_id", table_name="chunk_images")
    op.drop_index("ix_conversation_messages_session_id", table_name="conversation_messages")
