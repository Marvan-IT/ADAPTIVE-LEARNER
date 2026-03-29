"""chunk architecture: concept_chunks, chunk_images, teaching_sessions exam columns

Revision ID: 006_chunk_architecture
Revises: 005_add_adaptive_history_columns
Create Date: 2026-03-27

Adds:
- pgvector extension
- concept_chunks table with HNSW index for semantic search
- chunk_images table (FK → concept_chunks)
- 5 new nullable columns on teaching_sessions for exam/chunk tracking
"""
from typing import Sequence, Union

from alembic import op


revision: str = '006_chunk_architecture'
down_revision: Union[str, Sequence[str], None] = '005_add_adaptive_history_columns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Enable pgvector extension ──────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── 2. concept_chunks table ───────────────────────────────────────────
    op.execute("""
        CREATE TABLE concept_chunks (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            book_slug   TEXT NOT NULL,
            concept_id  TEXT NOT NULL,
            section     TEXT NOT NULL,
            order_index INTEGER NOT NULL,
            heading     TEXT NOT NULL,
            text        TEXT NOT NULL,
            latex       TEXT[] DEFAULT '{}',
            embedding   vector(1536),
            created_at  TIMESTAMPTZ DEFAULT now()
        )
    """)

    # HNSW index for fast approximate nearest-neighbour cosine search
    op.execute(
        "CREATE INDEX ON concept_chunks USING hnsw (embedding vector_cosine_ops)"
    )
    # Composite index for ordered chunk retrieval per concept
    op.execute(
        "CREATE INDEX ON concept_chunks (book_slug, concept_id, order_index)"
    )

    # ── 3. chunk_images table ─────────────────────────────────────────────
    op.execute("""
        CREATE TABLE chunk_images (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            chunk_id    UUID NOT NULL REFERENCES concept_chunks(id) ON DELETE CASCADE,
            image_url   TEXT NOT NULL,
            caption     TEXT,
            order_index INTEGER DEFAULT 0
        )
    """)
    op.execute("CREATE INDEX ON chunk_images (chunk_id)")

    # ── 4. New columns on teaching_sessions ───────────────────────────────
    op.execute("ALTER TABLE teaching_sessions ADD COLUMN IF NOT EXISTS chunk_index INTEGER DEFAULT 0")
    op.execute("ALTER TABLE teaching_sessions ADD COLUMN IF NOT EXISTS exam_phase TEXT")
    op.execute("ALTER TABLE teaching_sessions ADD COLUMN IF NOT EXISTS exam_attempt INTEGER DEFAULT 0")
    op.execute("ALTER TABLE teaching_sessions ADD COLUMN IF NOT EXISTS exam_scores JSONB")
    op.execute("ALTER TABLE teaching_sessions ADD COLUMN IF NOT EXISTS failed_chunk_ids TEXT[]")


def downgrade() -> None:
    # ── Reverse new teaching_sessions columns ─────────────────────────────
    op.execute("ALTER TABLE teaching_sessions DROP COLUMN IF EXISTS failed_chunk_ids")
    op.execute("ALTER TABLE teaching_sessions DROP COLUMN IF EXISTS exam_scores")
    op.execute("ALTER TABLE teaching_sessions DROP COLUMN IF EXISTS exam_attempt")
    op.execute("ALTER TABLE teaching_sessions DROP COLUMN IF EXISTS exam_phase")
    op.execute("ALTER TABLE teaching_sessions DROP COLUMN IF EXISTS chunk_index")

    # ── Drop chunk_images first (FK dependency) ───────────────────────────
    op.execute("DROP TABLE IF EXISTS chunk_images")

    # ── Drop concept_chunks (indexes are dropped automatically with the table)
    op.execute("DROP TABLE IF EXISTS concept_chunks")

    # NOTE: The vector extension is NOT dropped here.
    # Other migrations or application code may depend on it, and
    # dropping an extension is a DBA-level destructive action.
