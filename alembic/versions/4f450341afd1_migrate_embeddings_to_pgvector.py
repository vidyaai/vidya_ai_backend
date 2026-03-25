"""migrate_embeddings_to_pgvector

Revision ID: 4f450341afd1
Revises: 7c4bff3c6756
Create Date: 2026-03-23 21:44:22.531303

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '4f450341afd1'
down_revision: Union[str, Sequence[str], None] = '7c4bff3c6756'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Migrate embeddings from JSON to pgvector Vector type."""

    # 1. Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Add temporary vector column
    op.add_column('transcript_chunks',
        sa.Column('embedding_vector', Vector(1536), nullable=True))

    # 3. Migrate data: JSON array → Vector
    # PostgreSQL can cast JSON array to vector directly
    op.execute("""
        UPDATE transcript_chunks
        SET embedding_vector = embedding::vector(1536)
        WHERE embedding IS NOT NULL
    """)

    # 4. Drop old JSON column
    op.drop_column('transcript_chunks', 'embedding')

    # 5. Rename new vector column to 'embedding'
    op.alter_column('transcript_chunks', 'embedding_vector',
        new_column_name='embedding')

    # 6. Create IVFFlat vector index for fast similarity search
    # Using 100 lists (good for 10K-100K vectors)
    op.execute("""
        CREATE INDEX idx_transcript_chunks_embedding_cosine
        ON transcript_chunks
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)


def downgrade() -> None:
    """Downgrade schema - convert Vector back to JSON."""

    # 1. Drop vector index
    op.execute("DROP INDEX IF EXISTS idx_transcript_chunks_embedding_cosine")

    # 2. Add temporary JSON column
    op.add_column('transcript_chunks',
        sa.Column('embedding_json', sa.JSON(), nullable=True))

    # 3. Migrate data: Vector → JSON array
    op.execute("""
        UPDATE transcript_chunks
        SET embedding_json = embedding::text::json
        WHERE embedding IS NOT NULL
    """)

    # 4. Drop vector column
    op.drop_column('transcript_chunks', 'embedding')

    # 5. Rename JSON column to 'embedding'
    op.alter_column('transcript_chunks', 'embedding_json',
        new_column_name='embedding')

    # 6. Optionally drop vector extension (commented out for safety)
    # op.execute("DROP EXTENSION IF EXISTS vector")
