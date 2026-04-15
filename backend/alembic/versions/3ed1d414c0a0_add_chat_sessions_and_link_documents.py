"""add_chat_sessions_and_link_documents

Revision ID: 3ed1d414c0a0
Revises: 25c4b2c802f6
Create Date: 2026-04-13 11:22:08.347752
"""
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = '3ed1d414c0a0'
down_revision: Union[str, None] = '25c4b2c802f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create chat_sessions table
    op.create_table(
        'chat_sessions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String, nullable=False, server_default='New Chat'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('idx_chat_sessions_user_id', 'chat_sessions', ['user_id'])
    op.create_index('idx_chat_sessions_created_at', 'chat_sessions', ['created_at'])

    # 2. Create association table
    op.create_table(
        'chat_session_documents',
        sa.Column('chat_session_id', UUID(as_uuid=True), sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('document_id', UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), primary_key=True),
    )

    # 3. Add chat_session_id to chats
    op.add_column('chats', sa.Column('chat_session_id', UUID(as_uuid=True), nullable=True))
    op.create_index('idx_chats_user_session', 'chats', ['user_id', 'chat_session_id'])

    # 4. Migrate existing data
    conn = op.get_bind()

    # 4a. Create a session for every distinct document-linked chat grouping
    # Group by (user_id, document_id) where document_id IS NOT NULL
    rows = conn.execute(sa.text("""
        SELECT DISTINCT user_id, document_id
        FROM chats
        WHERE document_id IS NOT NULL
    """)).fetchall()

    for user_id, document_id in rows:
        session_id = str(uuid4())
        # Create session
        conn.execute(sa.text("""
            INSERT INTO chat_sessions (id, user_id, title, created_at, updated_at)
            VALUES (:id, :user_id, :title, NOW(), NOW())
        """), {"id": session_id, "user_id": user_id, "title": "Chat"})

        # Link document to session
        conn.execute(sa.text("""
            INSERT INTO chat_session_documents (chat_session_id, document_id)
            VALUES (:session_id, :document_id)
            ON CONFLICT DO NOTHING
        """), {"session_id": session_id, "document_id": document_id})

        # Update chats
        conn.execute(sa.text("""
            UPDATE chats
            SET chat_session_id = :session_id
            WHERE user_id = :user_id AND document_id = :document_id
        """), {"session_id": session_id, "user_id": user_id, "document_id": document_id})

    # 4b. Create a single global session per user for chats with no document
    global_rows = conn.execute(sa.text("""
        SELECT DISTINCT user_id
        FROM chats
        WHERE document_id IS NULL
    """)).fetchall()

    for (user_id,) in global_rows:
        session_id = str(uuid4())
        conn.execute(sa.text("""
            INSERT INTO chat_sessions (id, user_id, title, created_at, updated_at)
            VALUES (:id, :user_id, :title, NOW(), NOW())
        """), {"id": session_id, "user_id": user_id, "title": "General Chat"})

        conn.execute(sa.text("""
            UPDATE chats
            SET chat_session_id = :session_id
            WHERE user_id = :user_id AND document_id IS NULL
        """), {"session_id": session_id, "user_id": user_id})


def downgrade() -> None:
    op.drop_index('idx_chats_user_session', table_name='chats')
    op.drop_column('chats', 'chat_session_id')
    op.drop_table('chat_session_documents')
    op.drop_index('idx_chat_sessions_created_at', table_name='chat_sessions')
    op.drop_index('idx_chat_sessions_user_id', table_name='chat_sessions')
    op.drop_table('chat_sessions')
