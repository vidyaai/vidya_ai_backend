"""add_transcript_chunks_table_phase1

Revision ID: c1b1b80bc8ef
Revises: 5e4bc82edb2f
Create Date: 2026-03-13 05:17:51.161327

Phase 1: Semantic chunking with embeddings for precise retrieval
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1b1b80bc8ef'
down_revision: Union[str, Sequence[str], None] = '5e4bc82edb2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add transcript_chunks table for semantic chunking."""
    op.create_table(
        'transcript_chunks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('video_id', sa.String(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('start_time', sa.String(), nullable=True),
        sa.Column('end_time', sa.String(), nullable=True),
        sa.Column('start_seconds', sa.Float(), nullable=True),
        sa.Column('end_seconds', sa.Float(), nullable=True),
        sa.Column('embedding', sa.JSON(), nullable=True),
        sa.Column('word_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id'], ),
    )
    op.create_index('ix_transcript_chunks_video_id', 'transcript_chunks', ['video_id'])


def downgrade() -> None:
    """Remove transcript_chunks table."""
    op.drop_index('ix_transcript_chunks_video_id', table_name='transcript_chunks')
    op.drop_table('transcript_chunks')
