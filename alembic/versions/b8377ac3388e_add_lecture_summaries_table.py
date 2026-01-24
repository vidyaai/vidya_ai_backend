"""Add lecture_summaries table

Revision ID: b8377ac3388e
Revises: a885b1015adc
Create Date: 2026-01-24 02:10:39.246823

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b8377ac3388e'
down_revision: Union[str, Sequence[str], None] = 'a885b1015adc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'lecture_summaries',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('video_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('summary_markdown', sa.Text(), nullable=False),
        sa.Column('summary_pdf_s3_key', sa.String(), nullable=True),
        sa.Column('summary_metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_lecture_summaries_user_id'), 'lecture_summaries', ['user_id'], unique=False)
    op.create_index(op.f('ix_lecture_summaries_video_id'), 'lecture_summaries', ['video_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_lecture_summaries_video_id'), table_name='lecture_summaries')
    op.drop_index(op.f('ix_lecture_summaries_user_id'), table_name='lecture_summaries')
    op.drop_table('lecture_summaries')
