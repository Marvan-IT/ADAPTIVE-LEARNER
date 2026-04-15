"""Add content-control columns to concept_chunks and new admin tables

Revision ID: 012_add_content_control_columns
Revises: 011_add_age_to_students
Create Date: 2026-04-13

Design notes:
- concept_chunks gains three admin-control columns:
    is_hidden       — soft-hide a chunk from students without deleting it
    exam_disabled   — exclude the chunk from exam/card generation
    admin_section_name — optional override label shown in the admin console
- admin_graph_overrides stores manual edge additions/removals applied on top
  of the auto-generated dependency graph.  A unique constraint prevents
  duplicate overrides for the same (book, action, source, target) tuple.
- admin_config is a simple key/value store for platform-wide admin settings.
- Both new tables carry a nullable created_by / updated_by FK to users(id)
  using ON DELETE SET NULL so that deleting an admin account does not erase
  the audit trail of which settings were changed.
- No PostgreSQL ENUM types — action is a plain Text column with a CHECK
  constraint, matching the convention used throughout this project.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "012_add_content_control_columns"
down_revision: Union[str, Sequence[str], None] = "011_add_age_to_students"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. concept_chunks — content-control columns ───────────────────────
    op.add_column(
        "concept_chunks",
        sa.Column(
            "is_hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "concept_chunks",
        sa.Column(
            "exam_disabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "concept_chunks",
        sa.Column("admin_section_name", sa.Text(), nullable=True),
    )

    # ── 2. admin_graph_overrides ──────────────────────────────────────────
    op.create_table(
        "admin_graph_overrides",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("book_slug", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("source_concept", sa.Text(), nullable=False),
        sa.Column("target_concept", sa.Text(), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "book_slug", "action", "source_concept", "target_concept",
            name="uq_graph_override",
        ),
        sa.CheckConstraint(
            "action IN ('add_edge', 'remove_edge')",
            name="ck_graph_override_action",
        ),
    )

    # ── 3. admin_config ───────────────────────────────────────────────────
    op.create_table(
        "admin_config",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    # Reverse in dependency order — tables first, then columns
    op.drop_table("admin_config")
    op.drop_table("admin_graph_overrides")

    op.drop_column("concept_chunks", "admin_section_name")
    op.drop_column("concept_chunks", "exam_disabled")
    op.drop_column("concept_chunks", "is_hidden")
