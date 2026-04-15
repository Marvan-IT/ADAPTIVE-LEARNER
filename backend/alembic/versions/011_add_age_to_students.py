"""Add age column to students table

Revision ID: 011_add_age_to_students
Revises: 010_add_auth_tables
Create Date: 2026-04-13

Design notes:
- age is nullable Integer — not all students will provide their age, and
  legacy rows created before this migration must not break.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_add_age_to_students"
down_revision: Union[str, Sequence[str], None] = "010_add_auth_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "students",
        sa.Column("age", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("students", "age")
