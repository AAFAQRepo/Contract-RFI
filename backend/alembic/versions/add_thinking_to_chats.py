"""add thinking to chats

Revision ID: add_thinking_to_chats
Revises: 
Create Date: 2026-04-26

"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('chats', sa.Column('thinking', sa.Text(), nullable=True))

def downgrade():
    op.drop_column('chats', 'thinking')
