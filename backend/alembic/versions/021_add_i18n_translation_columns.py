"""Add translation JSONB columns for i18n rework

Revision ID: 021_add_i18n_translation_columns
Revises: 8dff038cb7f9
Create Date: 2026-04-23

Adds five JSONB columns (default '{}') across four tables:
  books.title_translations
  books.subject_translations
  subjects.label_translations
  concept_chunks.heading_translations
  chunk_images.caption_translations

All columns are NOT NULL with server_default '{}'::jsonb so every existing
row is immediately valid. No data backfill is required — English fallback
operates from the empty dict until the translate_catalog.py script runs.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '021_add_i18n_translation_columns'
down_revision: Union[str, Sequence[str], None] = '8dff038cb7f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSONB_EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    """Add five JSONB translation columns."""
    op.add_column(
        'books',
        sa.Column(
            'title_translations',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=_JSONB_EMPTY,
        ),
    )
    op.add_column(
        'books',
        sa.Column(
            'subject_translations',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=_JSONB_EMPTY,
        ),
    )
    op.add_column(
        'subjects',
        sa.Column(
            'label_translations',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=_JSONB_EMPTY,
        ),
    )
    op.add_column(
        'concept_chunks',
        sa.Column(
            'heading_translations',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=_JSONB_EMPTY,
        ),
    )
    op.add_column(
        'chunk_images',
        sa.Column(
            'caption_translations',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=_JSONB_EMPTY,
        ),
    )


def downgrade() -> None:
    """Remove five JSONB translation columns."""
    op.drop_column('chunk_images', 'caption_translations')
    op.drop_column('concept_chunks', 'heading_translations')
    op.drop_column('subjects', 'label_translations')
    op.drop_column('books', 'subject_translations')
    op.drop_column('books', 'title_translations')
