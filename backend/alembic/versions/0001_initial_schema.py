"""Initial schema baseline

Registers the four core tables (students, teaching_sessions,
conversation_messages, student_mastery) that were created by
SQLAlchemy create_all() during early development.  No DDL is
emitted for those tables — they already exist.  This migration
only records the baseline in alembic_version and adds two CHECK
constraints that were missing from the original create_all schema.

Revision ID: 0001
Revises:
Create Date: 2026-03-18

"""
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The four core tables already exist in production (created by create_all
    # before Alembic was introduced).  We do not recreate them here.
    # The no-op SELECT 1 lets Alembic stamp alembic_version = '0001' so that
    # subsequent migrations in the chain can run cleanly.
    op.execute("SELECT 1")

    # Add phase CHECK constraint — all code paths use only these phase values.
    # Using IF NOT EXISTS pattern via DO block so this is idempotent on
    # databases that already had the constraint applied manually.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_session_phase'
                  AND conrelid = 'teaching_sessions'::regclass
            ) THEN
                ALTER TABLE teaching_sessions
                ADD CONSTRAINT ck_session_phase
                CHECK (phase IN (
                    'PRESENTING','CARDS','CARDS_DONE','CHECKING','REMEDIATING',
                    'REMEDIATING_2','RECHECKING','RECHECKING_2',
                    'COMPLETED','ATTEMPTS_EXHAUSTED'
                ));
            END IF;
        END
        $$;
    """)

    # Add check_score range constraint.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_check_score_range'
                  AND conrelid = 'teaching_sessions'::regclass
            ) THEN
                ALTER TABLE teaching_sessions
                ADD CONSTRAINT ck_check_score_range
                CHECK (check_score IS NULL OR (check_score >= 0 AND check_score <= 100));
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE teaching_sessions "
        "DROP CONSTRAINT IF EXISTS ck_session_phase"
    )
    op.execute(
        "ALTER TABLE teaching_sessions "
        "DROP CONSTRAINT IF EXISTS ck_check_score_range"
    )
