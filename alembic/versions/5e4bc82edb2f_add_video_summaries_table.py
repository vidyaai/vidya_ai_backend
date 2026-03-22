"""add_video_summaries_table

Revision ID: 5e4bc82edb2f
Revises: a1b2c3d4e5f6
Create Date: 2026-03-13 02:13:16.332959

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e4bc82edb2f'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'  # Fixed: chain after latest migration
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add video_summaries table for hierarchical video summaries."""
    op.create_table(
        'video_summaries',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('video_id', sa.String(), nullable=False),
        sa.Column('overview_summary', sa.Text(), nullable=True),
        sa.Column('key_topics', sa.JSON(), nullable=True),
        sa.Column('sections', sa.JSON(), nullable=True),
        sa.Column('total_duration_seconds', sa.Float(), nullable=True),
        sa.Column('processing_status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id'], ),
    )
    op.create_index('ix_video_summaries_video_id', 'video_summaries', ['video_id'], unique=True)


def downgrade() -> None:
    """Remove video_summaries table."""
    op.drop_index('ix_video_summaries_video_id', table_name='video_summaries')
    op.drop_table('video_summaries')
