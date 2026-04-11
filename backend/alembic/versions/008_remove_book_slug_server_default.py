"""Remove server default from teaching_sessions.book_slug

The book_slug column was created by SQLAlchemy create_all() with no server
default (the Python-side default="prealgebra" was ORM-only).  This migration
explicitly drops any server default that may exist and enforces NOT NULL,
making book_slug a required field that callers must always supply.

Revision ID: 008_remove_book_slug_server_default
Revises: 007_chunk_progress
Create Date: 2026-04-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '008_remove_book_slug_server_default'
down_revision: Union[str, Sequence[str], None] = '007_chunk_progress'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the server default if one exists (idempotent — safe to run even
    # if no server default is currently set).
    op.execute(
        "ALTER TABLE teaching_sessions "
        "ALTER COLUMN book_slug DROP DEFAULT"
    )
    # Ensure the column is NOT NULL.  Any rows with a NULL book_slug would
    # indicate a data integrity issue; surface it here rather than silently
    # accepting bad data.
    op.execute(
        "ALTER TABLE teaching_sessions "
        "ALTER COLUMN book_slug SET NOT NULL"
    )


def downgrade() -> None:
    # Restore the 'prealgebra' server default so that old code that relies
    # on it continues to work after a rollback.
    op.execute(
        "ALTER TABLE teaching_sessions "
        "ALTER COLUMN book_slug SET DEFAULT 'prealgebra'"
    )
