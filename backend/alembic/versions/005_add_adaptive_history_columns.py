"""add adaptive history columns to students and card_interactions

Revision ID: 005_add_adaptive_history_columns
Revises: 004_socratic_remediation
Create Date: 2026-03-10

Adds 11 columns to students (extended adaptive learning history) and
3 columns to card_interactions (engagement tracking).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


revision: str = '005_add_adaptive_history_columns'
down_revision: Union[str, Sequence[str], None] = '004_socratic_remediation'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── students: extended adaptive history ───────────────────────────────
    op.add_column('students', sa.Column(
        'section_count', sa.Integer(), nullable=False,
        server_default=sa.text('0')
    ))
    op.add_column('students', sa.Column(
        'overall_accuracy_rate', sa.Float(), nullable=False,
        server_default=sa.text('0.5')
    ))
    op.add_column('students', sa.Column(
        'preferred_analogy_style', sa.String(50), nullable=True
    ))
    op.add_column('students', sa.Column(
        'boredom_pattern', sa.String(20), nullable=True
    ))
    op.add_column('students', sa.Column(
        'frustration_tolerance', sa.String(20), nullable=True,
        server_default=sa.text("'medium'")
    ))
    op.add_column('students', sa.Column(
        'recovery_speed', sa.String(20), nullable=True,
        server_default=sa.text("'normal'")
    ))
    op.add_column('students', sa.Column(
        'avg_state_score', sa.Float(), nullable=False,
        server_default=sa.text('2.0')
    ))
    op.add_column('students', sa.Column(
        'effective_analogies', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        server_default=sa.text("'[]'::jsonb")
    ))
    op.add_column('students', sa.Column(
        'effective_engagement', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        server_default=sa.text("'[]'::jsonb")
    ))
    op.add_column('students', sa.Column(
        'ineffective_engagement', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        server_default=sa.text("'[]'::jsonb")
    ))
    op.add_column('students', sa.Column(
        'state_distribution',
        postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        server_default=sa.text('\'{"struggling": 0, "normal": 0, "fast": 0}\'::jsonb')
    ))

    # ── card_interactions: engagement tracking ────────────────────────────
    op.add_column('card_interactions', sa.Column(
        'engagement_signal', sa.String(50), nullable=True
    ))
    op.add_column('card_interactions', sa.Column(
        'strategy_applied', sa.String(50), nullable=True
    ))
    op.add_column('card_interactions', sa.Column(
        'strategy_effective', sa.Boolean(), nullable=True
    ))


def downgrade() -> None:
    # ── card_interactions ─────────────────────────────────────────────────
    op.drop_column('card_interactions', 'strategy_effective')
    op.drop_column('card_interactions', 'strategy_applied')
    op.drop_column('card_interactions', 'engagement_signal')

    # ── students ──────────────────────────────────────────────────────────
    op.drop_column('students', 'state_distribution')
    op.drop_column('students', 'ineffective_engagement')
    op.drop_column('students', 'effective_engagement')
    op.drop_column('students', 'effective_analogies')
    op.drop_column('students', 'avg_state_score')
    op.drop_column('students', 'recovery_speed')
    op.drop_column('students', 'frustration_tolerance')
    op.drop_column('students', 'boredom_pattern')
    op.drop_column('students', 'preferred_analogy_style')
    op.drop_column('students', 'overall_accuracy_rate')
    op.drop_column('students', 'section_count')
