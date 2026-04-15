"""Add chunk_type_locked column to concept_chunks

Revision ID: 013_add_chunk_type_locked
Revises: 012_add_content_control_columns
Create Date: 2026-04-13

Design notes:
- chunk_type_locked protects admin-overridden chunk_type values from being
  silently overwritten during pipeline re-runs.  When True, the extraction
  pipeline skips its automatic chunk_type classification for that row and
  preserves whatever value the admin set via the admin console.
- Defaults to false (server-side) so all existing rows are unaffected.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_add_chunk_type_locked"
down_revision: Union[str, Sequence[str], None] = "012_add_content_control_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "concept_chunks",
        sa.Column(
            "chunk_type_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("concept_chunks", "chunk_type_locked")
