"""Add daily usage tracking

Revision ID: 6_add_daily_usage
Revises: 2c041f13225f
Create Date: 2026-01-05

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '6_add_daily_usage'
down_revision = '2c041f13225f'
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns to user_usage table
    op.add_column('user_usage', sa.Column('date', sa.String(), nullable=True))
    op.add_column('user_usage', sa.Column('videos_analyzed_today', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('user_usage', sa.Column('questions_per_video', postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default='{}'))
    
    # Create index on date column for faster queries
    op.create_index('ix_user_usage_date', 'user_usage', ['date'])
    
    # Update existing rows to have date based on month_year (set to first day of month)
    op.execute("""
        UPDATE user_usage 
        SET date = month_year || '-01' 
        WHERE date IS NULL
    """)
    
    # Now make date column NOT NULL
    op.alter_column('user_usage', 'date', nullable=False)


def downgrade():
    # Remove index
    op.drop_index('ix_user_usage_date', table_name='user_usage')
    
    # Drop columns
    op.drop_column('user_usage', 'questions_per_video')
    op.drop_column('user_usage', 'videos_analyzed_today')
    op.drop_column('user_usage', 'date')
