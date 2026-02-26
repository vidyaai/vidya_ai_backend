"""13 migration Add transcript fields to course_materials

Revision ID: a1b2c3d4e5f6
Revises: f452b6cb5374
Create Date: 2026-02-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f452b6cb5374"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add transcript_text and transcript_status to course_materials."""
    op.add_column(
        "course_materials",
        sa.Column("transcript_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "course_materials",
        sa.Column("transcript_status", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Remove transcript columns from course_materials."""
    op.drop_column("course_materials", "transcript_status")
    op.drop_column("course_materials", "transcript_text")
