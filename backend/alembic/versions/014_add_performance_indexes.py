"""Add performance indexes for high-traffic query paths

Revision ID: 014_add_performance_indexes
Revises: 013_add_chunk_type_locked
Create Date: 2026-04-13

Design notes:
- concept_chunks(book_slug, concept_id): covers chunk_knowledge_service.py
  lookups that filter by book and concept in every lesson and RAG query.
- concept_chunks(book_slug, concept_id, order_index): covers the ordered
  retrieval used when building the card sequence and exam gate progression.
- card_interactions(student_id, concept_id): covers card history queries in
  the adaptive engine that load all interactions for a student/concept pair.
- teaching_sessions(student_id, started_at): covers session history and
  analytics queries that list a student's sessions newest-first.
- spaced_reviews(student_id, due_at) WHERE completed_at IS NULL: partial
  index that covers only pending reviews, making due-review lookups fast even
  when a student has a large completed-review history.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_add_performance_indexes"
down_revision: Union[str, Sequence[str], None] = "013_add_chunk_type_locked"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add five performance indexes covering the most frequent query patterns.

    1. concept_chunks composite (book_slug, concept_id)
    2. concept_chunks composite (book_slug, concept_id, order_index)
    3. card_interactions composite (student_id, concept_id)
    4. teaching_sessions composite (student_id, started_at)
    5. spaced_reviews partial (student_id, due_at) WHERE completed_at IS NULL
    """
    # ── concept_chunks: lookup by book + concept ────────────────────────────
    op.create_index(
        "ix_concept_chunks_book_concept",
        "concept_chunks",
        ["book_slug", "concept_id"],
        if_not_exists=True,
    )

    # ── concept_chunks: ordered retrieval by book + concept + position ──────
    op.create_index(
        "ix_concept_chunks_book_concept_order",
        "concept_chunks",
        ["book_slug", "concept_id", "order_index"],
        if_not_exists=True,
    )

    # ── card_interactions: history queries per student/concept ───────────────
    op.create_index(
        "ix_card_interactions_student_concept",
        "card_interactions",
        ["student_id", "concept_id"],
        if_not_exists=True,
    )

    # ── teaching_sessions: session history / analytics newest-first ──────────
    op.create_index(
        "ix_teaching_sessions_student_started",
        "teaching_sessions",
        ["student_id", "started_at"],
        if_not_exists=True,
    )

    # ── spaced_reviews: pending due-review lookups (partial index) ───────────
    # PostgreSQL-specific: only indexes rows where the review is not yet done,
    # keeping the index small as completed reviews accumulate.
    op.create_index(
        "ix_spaced_reviews_student_due_pending",
        "spaced_reviews",
        ["student_id", "due_at"],
        postgresql_where=sa.text("completed_at IS NULL"),
        if_not_exists=True,
    )


def downgrade() -> None:
    """Drop all five indexes added in upgrade(), in reverse order."""
    op.drop_index(
        "ix_spaced_reviews_student_due_pending",
        table_name="spaced_reviews",
    )
    op.drop_index(
        "ix_teaching_sessions_student_started",
        table_name="teaching_sessions",
    )
    op.drop_index(
        "ix_card_interactions_student_concept",
        table_name="card_interactions",
    )
    op.drop_index(
        "ix_concept_chunks_book_concept_order",
        table_name="concept_chunks",
    )
    op.drop_index(
        "ix_concept_chunks_book_concept",
        table_name="concept_chunks",
    )
