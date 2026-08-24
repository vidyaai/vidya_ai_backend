"""19 migration Add embed_clients table

Revision ID: f564fb40bec5
Revises: 915759bda80e
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f564fb40bec5"
down_revision: Union[str, Sequence[str], None] = "915759bda80e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "embed_clients",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("embed_secret", sa.String(), nullable=False),
        sa.Column(
            "default_user_type",
            sa.String(length=20),
            nullable=False,
            server_default="student",
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(
        op.f("ix_embed_clients_slug"), "embed_clients", ["slug"], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_embed_clients_slug"), table_name="embed_clients")
    op.drop_table("embed_clients")
