"""Add share_format and google_resource_url to shared_links

Revision ID: add_share_format
Revises: 
Create Date: 2025-12-15

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_share_format'
down_revision = '2c041f13225f'  # Points to the previous migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add share_format column with default value
    op.add_column('shared_links', sa.Column('share_format', sa.String(), nullable=True))
    op.execute("UPDATE shared_links SET share_format = 'html_form' WHERE share_format IS NULL")
    op.alter_column('shared_links', 'share_format', nullable=False, server_default='html_form')
    
    # Add google_resource_url column
    op.add_column('shared_links', sa.Column('google_resource_url', sa.String(), nullable=True))


def downgrade() -> None:
    # Remove columns
    op.drop_column('shared_links', 'google_resource_url')
    op.drop_column('shared_links', 'share_format')
