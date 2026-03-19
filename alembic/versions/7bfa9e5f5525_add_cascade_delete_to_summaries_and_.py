"""add_cascade_delete_to_summaries_and_chunks

Revision ID: 7bfa9e5f5525
Revises: c1b1b80bc8ef
Create Date: 2026-03-13 05:52:18.096606

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7bfa9e5f5525'
down_revision: Union[str, Sequence[str], None] = 'c1b1b80bc8ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add CASCADE delete to video_summaries and transcript_chunks foreign keys."""

    # Drop existing foreign key constraints
    op.drop_constraint('video_summaries_video_id_fkey', 'video_summaries', type_='foreignkey')
    op.drop_constraint('transcript_chunks_video_id_fkey', 'transcript_chunks', type_='foreignkey')

    # Recreate with CASCADE delete
    op.create_foreign_key(
        'video_summaries_video_id_fkey',
        'video_summaries', 'videos',
        ['video_id'], ['id'],
        ondelete='CASCADE'
    )

    op.create_foreign_key(
        'transcript_chunks_video_id_fkey',
        'transcript_chunks', 'videos',
        ['video_id'], ['id'],
        ondelete='CASCADE'
    )


def downgrade() -> None:
    """Remove CASCADE delete from foreign keys."""

    # Drop CASCADE constraints
    op.drop_constraint('video_summaries_video_id_fkey', 'video_summaries', type_='foreignkey')
    op.drop_constraint('transcript_chunks_video_id_fkey', 'transcript_chunks', type_='foreignkey')

    # Recreate without CASCADE
    op.create_foreign_key(
        'video_summaries_video_id_fkey',
        'video_summaries', 'videos',
        ['video_id'], ['id']
    )

    op.create_foreign_key(
        'transcript_chunks_video_id_fkey',
        'transcript_chunks', 'videos',
        ['video_id'], ['id']
    )
