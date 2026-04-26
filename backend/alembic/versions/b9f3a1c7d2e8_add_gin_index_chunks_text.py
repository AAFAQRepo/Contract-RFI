"""add gin index on chunks text for full text search

Revision ID: b9f3a1c7d2e8
Revises: a1b2c3d4e5f6
Create Date: 2026-04-26

Fixes applied (from audit):
  R-5 — Adds GIN indexes on chunks.text for both English and Arabic full-text
         search.  Without these, every sparse_search call performs a full
         table scan via to_tsvector(), which is O(N) and will collapse at
         any meaningful document count.

  Also adds a composite index on (document_id, chunk_type) to speed up the
  finalize task's chunk insert verification and the status endpoint count query.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b9f3a1c7d2e8'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── R-5 FIX: GIN indexes for full-text search ─────────────────────────────
    # English (default for most contract text)
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chunks_text_fts_english "
        "ON chunks USING GIN (to_tsvector('english', text))"
    )

    # Arabic (CRITICAL-7: without this, Arabic sparse_search falls back to
    # English lexicon and returns zero results for Arabic documents)
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chunks_text_fts_arabic "
        "ON chunks USING GIN (to_tsvector('arabic', text))"
    )

    # Simple (used for Hindi and other unsupported languages — unigram matching)
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chunks_text_fts_simple "
        "ON chunks USING GIN (to_tsvector('simple', text))"
    )

    # A-2 FIX: composite index to speed up COUNT/GROUP BY in get_document_status
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chunks_doc_type "
        "ON chunks (document_id, chunk_type)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_chunks_text_fts_english")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_chunks_text_fts_arabic")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_chunks_text_fts_simple")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_chunks_doc_type")
