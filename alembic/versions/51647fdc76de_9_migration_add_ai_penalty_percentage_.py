"""9_migration add_ai_penalty_percentage_to_assignments

Revision ID: 51647fdc76de
Revises: cdb37dd9d323
Create Date: 2026-02-03 15:59:03.196756

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "51647fdc76de"
down_revision: Union[str, Sequence[str], None] = "cdb37dd9d323"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "assignments", sa.Column("ai_penalty_percentage", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("assignments", "ai_penalty_percentage")
