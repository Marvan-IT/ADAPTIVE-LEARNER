"""Add chunk_progress JSONB column to teaching_sessions

Revision ID: 007_chunk_progress
Revises: 006_chunk_architecture
Create Date: 2026-03-29
"""
from typing import Sequence, Union

from alembic import op


revision: str = '007_chunk_progress'
down_revision: Union[str, Sequence[str], None] = '006_chunk_architecture'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE teaching_sessions ADD COLUMN IF NOT EXISTS chunk_progress JSONB"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE teaching_sessions DROP COLUMN IF EXISTS chunk_progress"
    )
