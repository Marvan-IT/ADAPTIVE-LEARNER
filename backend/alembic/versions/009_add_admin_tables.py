"""Add books and subjects tables for admin console

Revision ID: 009_add_admin_tables
Revises: 008_remove_book_slug_server_default
Create Date: 2026-04-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "009_add_admin_tables"
down_revision: Union[str, Sequence[str], None] = "008_remove_book_slug_server_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subjects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("slug", name="uq_subjects_slug"),
    )

    op.create_table(
        "books",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("book_slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PROCESSING"),
        sa.Column("pdf_filename", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("book_slug", name="uq_books_book_slug"),
    )

    # Seed 3 initial subjects
    op.execute("INSERT INTO subjects (slug, label) VALUES ('mathematics', 'Mathematics') ON CONFLICT (slug) DO NOTHING")
    op.execute("INSERT INTO subjects (slug, label) VALUES ('business', 'Business') ON CONFLICT (slug) DO NOTHING")
    op.execute("INSERT INTO subjects (slug, label) VALUES ('nursing', 'Nursing') ON CONFLICT (slug) DO NOTHING")


def downgrade() -> None:
    op.drop_table("books")
    op.drop_table("subjects")
