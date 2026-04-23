"""Add admin_audit_logs table for admin undo/redo audit log feature.

Revision ID: 020_add_admin_audit_logs
Revises: 019_add_chunk_type_check_constraint
Create Date: 2026-04-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "020_add_admin_audit_logs"
down_revision: Union[str, None] = "019_add_chunk_type_check_constraint"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "admin_audit_logs"
CK_ACTION_TYPE = "ck_audit_action_type"
CK_RESOURCE_TYPE = "ck_audit_resource_type"
IX_ADMIN_CREATED = "ix_audit_admin_created"
IX_RESOURCE = "ix_audit_resource"
IX_BOOK = "ix_audit_book"

# 11 valid action_type values
_VALID_ACTION_TYPES = (
    "update_chunk",
    "toggle_chunk_visibility",
    "toggle_chunk_exam_gate",
    "rename_section",
    "toggle_section_optional",
    "toggle_section_exam_gate",
    "toggle_section_visibility",
    "reorder_chunks",
    "merge_chunks",
    "split_chunk",
    "promote",
)
_ACTION_TYPE_CHECK = "action_type IN ({})".format(
    ", ".join(f"'{v}'" for v in _VALID_ACTION_TYPES)
)


def upgrade() -> None:
    # ── admin_audit_logs ──────────────────────────────────────────────────
    op.create_table(
        TABLE_NAME,
        # Primary key — generated server-side so inserts never need to supply it
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Admin who performed the action — SET NULL on user deletion so history
        # is preserved even when the admin account is removed
        sa.Column(
            "admin_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Discriminator columns with CHECK constraints
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        # resource_id holds either a chunk UUID string or a concept_id string
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column("book_slug", sa.Text(), nullable=False),
        # Pre- and post-mutation snapshots stored as JSONB
        sa.Column("old_value", JSONB(), nullable=False),
        sa.Column("new_value", JSONB(), nullable=False),
        sa.Column(
            "affected_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Undo linkage — SET NULL so undo history survives admin deletion
        sa.Column(
            "undone_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "undone_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        # Self-referential redo FK — added after table creation via use_alter
        # to avoid forward-reference issues during table construction
        sa.Column(
            "redo_of",
            UUID(as_uuid=True),
            nullable=True,
        ),
        # Named CHECK constraints inline so Alembic tracks them by name
        sa.CheckConstraint(_ACTION_TYPE_CHECK, name=CK_ACTION_TYPE),
        sa.CheckConstraint(
            "resource_type IN ('chunk', 'section')", name=CK_RESOURCE_TYPE
        ),
    )

    # Self-referential FK added separately with use_alter=True — required when
    # the referenced table is the same table being created (Alembic/psycopg
    # cannot resolve the forward reference during CREATE TABLE)
    op.create_foreign_key(
        "fk_audit_logs_redo_of",
        TABLE_NAME,
        TABLE_NAME,
        ["redo_of"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )

    # ── Indexes ───────────────────────────────────────────────────────────
    # Composite index for list queries filtered by admin and sorted newest-first
    op.create_index(
        IX_ADMIN_CREATED,
        TABLE_NAME,
        ["admin_id", sa.text("created_at DESC")],
    )
    # Index for stale-check lookups by resource (chunk UUID or concept_id)
    op.create_index(IX_RESOURCE, TABLE_NAME, ["resource_id"])
    # Index for per-book content filtering
    op.create_index(IX_BOOK, TABLE_NAME, ["book_slug"])


def downgrade() -> None:
    # Drop indexes first (reverse creation order)
    op.drop_index(IX_BOOK, table_name=TABLE_NAME)
    op.drop_index(IX_RESOURCE, table_name=TABLE_NAME)
    op.drop_index(IX_ADMIN_CREATED, table_name=TABLE_NAME)

    # Drop the self-referential FK before dropping the table
    op.drop_constraint("fk_audit_logs_redo_of", TABLE_NAME, type_="foreignkey")

    # Drop the table (CHECK constraints are dropped implicitly with it)
    op.drop_table(TABLE_NAME)
