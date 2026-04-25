"""Add admin_section_name_translations JSONB column to concept_chunks

Revision ID: 022_add_admin_section_name_translations
Revises: 021_add_i18n_translation_columns
Create Date: 2026-04-24

Adds one JSONB column (default '{}') to concept_chunks:
  concept_chunks.admin_section_name_translations

NOT NULL with server_default '{}'::jsonb — every existing row is immediately
valid. No data backfill required — English fallback operates from the empty
dict until translate_catalog.py or the rename handler populates it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '022_add_admin_section_name_translations'
down_revision: Union[str, Sequence[str], None] = '021_add_i18n_translation_columns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSONB_EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    """Add admin_section_name_translations JSONB column to concept_chunks."""
    op.add_column(
        'concept_chunks',
        sa.Column(
            'admin_section_name_translations',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=_JSONB_EMPTY,
        ),
    )


def downgrade() -> None:
    """Remove admin_section_name_translations column from concept_chunks."""
    op.drop_column('concept_chunks', 'admin_section_name_translations')
