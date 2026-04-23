"""Add conversation_id to documents for per-chat scoping

Revision ID: a1b2c3d4e5f6
Revises: 4fd58b29c9a0
Create Date: 2026-04-23 18:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '4fd58b29c9a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add conversation_id FK to documents table.
    # Existing documents will have NULL (orphaned) — intentional.
    op.add_column(
        'documents',
        sa.Column('conversation_id', sa.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        'fk_documents_conversation_id',
        'documents',
        'conversations',
        ['conversation_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'idx_documents_conversation_id',
        'documents',
        ['conversation_id'],
    )


def downgrade() -> None:
    op.drop_index('idx_documents_conversation_id', table_name='documents')
    op.drop_constraint('fk_documents_conversation_id', 'documents', type_='foreignkey')
    op.drop_column('documents', 'conversation_id')
