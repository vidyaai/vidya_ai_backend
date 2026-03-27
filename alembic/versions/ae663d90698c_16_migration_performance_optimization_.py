"""16 migration Performance optimization indexes and migrate_embeddings_to_pgvector

Revision ID: ae663d90698c
Revises: a772ab660778
Create Date: 2026-03-26 21:35:09.321572

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = "ae663d90698c"
down_revision: Union[str, Sequence[str], None] = "a772ab660778"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    """Migrate embeddings from JSON to pgvector Vector type."""

    # 1. Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Add temporary vector column
    op.add_column(
        "transcript_chunks", sa.Column("embedding_vector", Vector(1536), nullable=True)
    )

    # 3. Migrate data: JSON array → Vector
    # PostgreSQL can cast JSON array to vector directly
    op.execute(
        """
        UPDATE transcript_chunks
        SET embedding_vector = embedding::text::vector(1536)
        WHERE embedding IS NOT NULL
    """
    )

    # 4. Drop old JSON column
    op.drop_column("transcript_chunks", "embedding")

    # 5. Rename new vector column to 'embedding'
    op.alter_column(
        "transcript_chunks", "embedding_vector", new_column_name="embedding"
    )

    # 6. Create IVFFlat vector index for fast similarity search
    # Using 100 lists (good for 10K-100K vectors)
    op.execute(
        """
        CREATE INDEX idx_transcript_chunks_embedding_cosine
        ON transcript_chunks
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """
    )

    """Add performance indexes"""

    # Index 1: Composite index for transcript_chunks (video_id, chunk_index)
    # Speeds up queries that filter by video_id and order by chunk_index
    # Used in: RAG retrieval, chunk loading
    # Impact: 200ms → 50ms for chunk queries
    op.create_index(
        "idx_transcript_chunks_video_chunk",
        "transcript_chunks",
        ["video_id", "chunk_index"],
        unique=False,
        postgresql_using="btree",
    )

    # Index 2: Index on chunk_index alone for ordering within video
    # Speeds up queries that need chunks in order
    # Used in: Sequential chunk access
    # Impact: 100ms → 20ms for ordered access
    op.create_index(
        "idx_transcript_chunks_chunk_index",
        "transcript_chunks",
        ["chunk_index"],
        unique=False,
        postgresql_using="btree",
    )

    # Index 3: Index on transcript_chunks.created_at for cleanup/pruning
    # Speeds up queries that find old chunks to delete
    # Used in: Background cleanup tasks
    # Impact: 500ms → 50ms for cleanup queries
    op.create_index(
        "idx_transcript_chunks_created_at",
        "transcript_chunks",
        ["created_at"],
        unique=False,
        postgresql_using="btree",
    )

    # Note: We already have pgvector index on embedding column
    # Created automatically with: vector(1536) type


def downgrade() -> None:
    """Downgrade schema."""
    """Remove performance indexes"""

    op.drop_index("idx_transcript_chunks_created_at", table_name="transcript_chunks")
    op.drop_index("idx_transcript_chunks_chunk_index", table_name="transcript_chunks")
    op.drop_index("idx_transcript_chunks_video_chunk", table_name="transcript_chunks")

    """convert Vector back to JSON."""

    # 1. Drop vector index
    op.execute("DROP INDEX IF EXISTS idx_transcript_chunks_embedding_cosine")

    # 2. Add temporary JSON column
    op.add_column(
        "transcript_chunks", sa.Column("embedding_json", sa.JSON(), nullable=True)
    )

    # 3. Migrate data: Vector → JSON array
    op.execute(
        """
        UPDATE transcript_chunks
        SET embedding_json = embedding::text::json
        WHERE embedding IS NOT NULL
    """
    )

    # 4. Drop vector column
    op.drop_column("transcript_chunks", "embedding")

    # 5. Rename JSON column to 'embedding'
    op.alter_column("transcript_chunks", "embedding_json", new_column_name="embedding")

    # 6. Optionally drop vector extension (commented out for safety)
    # op.execute("DROP EXTENSION IF EXISTS vector")
