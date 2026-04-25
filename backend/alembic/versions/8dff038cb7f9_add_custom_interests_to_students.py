"""add custom_interests to students

Revision ID: 8dff038cb7f9
Revises: 020_add_admin_audit_logs
Create Date: 2026-04-23 17:48:53.953408

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8dff038cb7f9'
down_revision: Union[str, Sequence[str], None] = '020_add_admin_audit_logs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add custom_interests column to students table.

    server_default='[]'::jsonb backfills existing rows with an empty list
    rather than NULL, keeping the NOT NULL constraint immediately satisfiable.
    """
    op.add_column(
        'students',
        sa.Column(
            'custom_interests',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Remove custom_interests column from students table."""
    op.drop_column('students', 'custom_interests')
