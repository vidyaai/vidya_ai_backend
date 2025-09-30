"""Add missing user columns

Revision ID: c234567890cd
Revises: b123456789ab
Create Date: 2024-09-23 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c234567890cd'
down_revision = 'b123456789ab'
branch_labels = None
depends_on = None


def upgrade():
    # Add missing columns to users table
    op.add_column('users', sa.Column('firebase_uid', sa.String(), nullable=True))
    op.add_column('users', sa.Column('stripe_customer_id', sa.String(), nullable=True))
    
    # Create indexes for the new columns
    op.create_index('ix_users_firebase_uid', 'users', ['firebase_uid'], unique=True)
    op.create_index('ix_users_stripe_customer_id', 'users', ['stripe_customer_id'], unique=True)


def downgrade():
    # Drop indexes first
    op.drop_index('ix_users_stripe_customer_id', table_name='users')
    op.drop_index('ix_users_firebase_uid', table_name='users')
    
    # Drop columns
    op.drop_column('users', 'stripe_customer_id')
    op.drop_column('users', 'firebase_uid')
