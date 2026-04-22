"""saas_billing_and_conversations

Revision ID: 4fd58b29c9a0
Revises: 3ed1d414c0a0
Create Date: 2026-04-22 10:31:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4fd58b29c9a0'
down_revision: Union[str, None] = '3ed1d414c0a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create organizations table
    op.create_table(
        'organizations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('slug', sa.String(), nullable=True),
        sa.Column('owner_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug')
    )

    # 2. Add columns to users table
    op.add_column('users', sa.Column('company', sa.String(), nullable=True))
    op.add_column('users', sa.Column('role', sa.String(), server_default='user', nullable=True))
    op.add_column('users', sa.Column('is_verified', sa.Boolean(), server_default='false', nullable=True))
    op.add_column('users', sa.Column('onboarding_completed', sa.Boolean(), server_default='false', nullable=True))
    op.add_column('users', sa.Column('verification_token', sa.String(), nullable=True))
    op.add_column('users', sa.Column('reset_token', sa.String(), nullable=True))
    op.add_column('users', sa.Column('reset_token_expires', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('avatar_url', sa.String(), nullable=True))
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('org_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_users_org_id', 'users', 'organizations', ['org_id'], ['id'], ondelete='SET NULL')

    # 3. Handle 'chat_sessions' rename to 'conversations'
    # The previous migration 3ed1d414c0a0 created 'chat_sessions'
    op.rename_table('chat_sessions', 'conversations')
    
    # Update 'chats' table: rename 'chat_session_id' to 'conversation_id'
    op.alter_column('chats', 'chat_session_id', new_column_name='conversation_id')
    op.drop_index('idx_chats_user_session', table_name='chats')
    op.create_index('idx_chats_conv_id', 'chats', ['conversation_id'], unique=False)
    op.create_index('idx_chats_user_document', 'chats', ['user_id', 'document_id'], unique=False)

    # 4. Create onboarding_responses table
    op.create_table(
        'onboarding_responses',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('use_case', sa.String(), nullable=True),
        sa.Column('preferred_language', sa.String(), server_default='en', nullable=True),
        sa.Column('company_name', sa.String(), nullable=True),
        sa.Column('selected_plan', sa.String(), server_default='free', nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )

    # 5. Create subscriptions table
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('stripe_customer_id', sa.String(), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(), nullable=True),
        sa.Column('plan', sa.String(), server_default='free', nullable=False),
        sa.Column('status', sa.String(), server_default='active', nullable=False),
        sa.Column('current_period_start', sa.DateTime(), nullable=True),
        sa.Column('current_period_end', sa.DateTime(), nullable=True),
        sa.Column('cancel_at_period_end', sa.Boolean(), server_default='false', nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id')
    )

    # 6. Create usage_records table
    op.create_table(
        'usage_records',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('period_start', sa.DateTime(), nullable=False),
        sa.Column('documents_used', sa.Integer(), server_default='0', nullable=True),
        sa.Column('queries_used', sa.Integer(), server_default='0', nullable=True),
        sa.Column('storage_bytes_used', sa.BigInteger(), server_default='0', nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_usage_org_period', 'usage_records', ['org_id', 'period_start'], unique=False)

    # 7. Drop the temporary 'chat_session_documents' table if it exists (it's not in the new models)
    op.drop_table('chat_session_documents')

    # 8. DATA MIGRATION: Create organizations for existing users
    conn = op.get_bind()
    users = conn.execute(sa.text("SELECT id, name, email FROM users WHERE org_id IS NULL")).fetchall()
    
    import uuid
    for u_id, u_name, u_email in users:
        org_id = str(uuid.uuid4())
        org_name = f"{u_name or u_email.split('@')[0]}'s Team"
        
        # Create Org
        conn.execute(sa.text("""
            INSERT INTO organizations (id, name, created_at, owner_id)
            VALUES (:id, :name, NOW(), :owner_id)
        """), {"id": org_id, "name": org_name, "owner_id": u_id})
        
        # Link User to Org
        conn.execute(sa.text("""
            UPDATE users SET org_id = :org_id, role = 'owner' WHERE id = :u_id
        """), {"org_id": org_id, "u_id": u_id})
        
        # Create default subscription for the new org
        conn.execute(sa.text("""
            INSERT INTO subscriptions (id, org_id, plan, status, created_at, updated_at)
            VALUES (:sub_id, :org_id, 'free', 'active', NOW(), NOW())
        """), {"sub_id": str(uuid.uuid4()), "org_id": org_id})


def downgrade() -> None:
    op.create_table(
        'chat_session_documents',
        sa.Column('chat_session_id', sa.UUID(), sa.ForeignKey('conversations.id'), primary_key=True),
        sa.Column('document_id', sa.UUID(), sa.ForeignKey('documents.id'), primary_key=True),
    )
    op.drop_index('idx_usage_org_period', table_name='usage_records')
    op.drop_table('usage_records')
    op.drop_table('subscriptions')
    op.drop_table('onboarding_responses')
    op.rename_table('conversations', 'chat_sessions')
    op.alter_column('chats', 'conversation_id', new_column_name='chat_session_id')
    op.drop_column('users', 'org_id')
    op.drop_column('users', 'last_login_at')
    op.drop_column('users', 'avatar_url')
    op.drop_column('users', 'reset_token_expires')
    op.drop_column('users', 'reset_token')
    op.drop_column('users', 'verification_token')
    op.drop_column('users', 'onboarding_completed')
    op.drop_column('users', 'is_verified')
    op.drop_column('users', 'role')
    op.drop_column('users', 'company')
    op.drop_table('organizations')
