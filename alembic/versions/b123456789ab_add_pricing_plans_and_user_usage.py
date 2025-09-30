"""Add pricing plans and user usage tables

Revision ID: b123456789ab
Revises: 8505b008b9c8
Create Date: 2024-09-19 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'b123456789ab'
down_revision = '8505b008b9c8'
branch_labels = None
depends_on = None


def upgrade():
    # Create pricing_plans table
    op.create_table('pricing_plans',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('plan_key', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('monthly_price', sa.Float(), nullable=False),
        sa.Column('annual_price', sa.Float(), nullable=False),
        sa.Column('stripe_monthly_price_id', sa.String(), nullable=True),
        sa.Column('stripe_annual_price_id', sa.String(), nullable=True),
        sa.Column('features', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pricing_plans_plan_key'), 'pricing_plans', ['plan_key'], unique=True)

    # Create user_usage table
    op.create_table('user_usage',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('month_year', sa.String(), nullable=False),
        sa.Column('video_uploads_count', sa.Integer(), nullable=False),
        sa.Column('youtube_chats_count', sa.Integer(), nullable=False),
        sa.Column('translation_minutes_used', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_usage_user_id'), 'user_usage', ['user_id'])
    op.create_index(op.f('ix_user_usage_month_year'), 'user_usage', ['month_year'])

    # Modify subscriptions table
    op.add_column('subscriptions', sa.Column('plan_id', sa.String(), nullable=True))
    op.add_column('subscriptions', sa.Column('billing_period', sa.String(), nullable=True))
    op.create_index(op.f('ix_subscriptions_plan_id'), 'subscriptions', ['plan_id'])
    op.create_foreign_key('fk_subscriptions_plan_id', 'subscriptions', 'pricing_plans', ['plan_id'], ['id'])
    
    # Make stripe_subscription_id nullable (for free plans)
    op.alter_column('subscriptions', 'stripe_subscription_id',
                    existing_type=sa.VARCHAR(),
                    nullable=True)


def downgrade():
    # Remove foreign key and columns from subscriptions
    op.drop_constraint('fk_subscriptions_plan_id', 'subscriptions', type_='foreignkey')
    op.drop_index(op.f('ix_subscriptions_plan_id'), table_name='subscriptions')
    op.drop_column('subscriptions', 'billing_period')
    op.drop_column('subscriptions', 'plan_id')
    
    # Make stripe_subscription_id not nullable again
    op.alter_column('subscriptions', 'stripe_subscription_id',
                    existing_type=sa.VARCHAR(),
                    nullable=False)

    # Drop user_usage table
    op.drop_index(op.f('ix_user_usage_month_year'), table_name='user_usage')
    op.drop_index(op.f('ix_user_usage_user_id'), table_name='user_usage')
    op.drop_table('user_usage')

    # Drop pricing_plans table
    op.drop_index(op.f('ix_pricing_plans_plan_key'), table_name='pricing_plans')
    op.drop_table('pricing_plans')
