"""Add is_hidden to books and subjects tables

Revision ID: 017_is_hidden
Revises: 016
"""
from alembic import op
import sqlalchemy as sa

revision = "017_is_hidden"
down_revision = None  # standalone migration — safe to run anytime


def upgrade():
    # Add is_hidden to books (default false)
    op.add_column("books", sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default="false"))
    # Add is_hidden to subjects (default false)
    op.add_column("subjects", sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default="false"))


def downgrade():
    op.drop_column("subjects", "is_hidden")
    op.drop_column("books", "is_hidden")
