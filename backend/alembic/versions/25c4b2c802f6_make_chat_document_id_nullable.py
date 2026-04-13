"""make_chat_document_id_nullable

Revision ID: 25c4b2c802f6
Revises: 86c052853518
Create Date: 2026-04-07 18:55:13.130997
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '25c4b2c802f6'
down_revision: Union[str, None] = '86c052853518'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('chats', 'document_id',
               existing_type=sa.UUID(),
               nullable=True)


def downgrade() -> None:
    op.alter_column('chats', 'document_id',
               existing_type=sa.UUID(),
               nullable=False)
