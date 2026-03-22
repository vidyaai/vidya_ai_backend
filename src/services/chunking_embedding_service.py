"""
Combined Chunking and Embedding Service
Phase 1: Semantic chunking with embeddings

This service handles:
- Semantic chunking of transcripts (preserves timestamps)
- Embedding generation with OpenAI
- Similarity search for precise retrieval
"""

from openai import OpenAI
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from models import TranscriptChunk
from controllers.config import logger
import numpy as np
import re


class EmbeddingService:
    """
    Generates and searches embeddings using OpenAI text-embedding-3-small.
    Cost: $0.02/1M tokens (very cheap!)
    """

    def __init__(self):
        self.client = OpenAI()
        self.model = "text-embedding-3-small"
        self.dimension = 1536

    def embed_text(self, text: str) -> List[float]:
        """Generate embedding for single text."""
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=text,
                encoding_format="float"
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            raise

    def embed_batch(self, texts: List[str], batch_size: int = 100) -> List[List[float]]:
        """Generate embeddings for multiple texts (up to 2048 per batch)."""
        embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=batch,
                    encoding_format="float"
                )
                batch_embeddings = [item.embedding for item in response.data]
                embeddings.extend(batch_embeddings)
                logger.info(f"Generated {len(batch_embeddings)} embeddings (batch {i//batch_size + 1})")
            except Exception as e:
                logger.error(f"Error in batch {i}-{i+batch_size}: {e}")
                # Fallback to individual
                for text in batch:
                    embeddings.append(self.embed_text(text))

        return embeddings

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        return float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))

    def find_most_similar(
        self,
        query_embedding: List[float],
        candidates: List[Dict[str, Any]],
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find top-k most similar chunks.

        Args:
            query_embedding: Query vector
            candidates: List of dicts with 'embedding' and metadata
            top_k: Number of results

        Returns:
            Top-k sorted by similarity (highest first)
        """
        similarities = []

        for candidate in candidates:
            if not candidate.get("embedding"):
                continue

            similarity = self.cosine_similarity(
                query_embedding,
                candidate["embedding"]
            )
            similarities.append({
                **candidate,
                "similarity": similarity
            })

        similarities.sort(key=lambda x: x["similarity"], reverse=True)
        return similarities[:top_k]


class SemanticChunker:
    """
    Chunks transcripts semantically while preserving timestamps.
    Target: ~500 tokens per chunk with 50 token overlap.
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_transcript(self, transcript: str) -> List[Dict[str, Any]]:
        """
        Chunk transcript preserving timestamps.

        Returns:
            List of chunks with text, timestamps, metadata
        """
        # Parse transcript into timestamped sections
        sections = self._parse_transcript_sections(transcript)

        if not sections:
            # Fallback: plain chunking without timestamps
            return self._chunk_plain_text(transcript)

        # Group sections into chunks of target size
        chunks = []
        current_chunk_text = []
        current_start = None
        current_end = None

        for section in sections:
            # Estimate tokens (rough: 1 token ≈ 4 characters)
            test_text = "\n".join(current_chunk_text + [section["text"]])
            estimated_tokens = len(test_text) // 4

            if estimated_tokens <= self.chunk_size or not current_chunk_text:
                # Add to current chunk
                current_chunk_text.append(section["text"])
                if current_start is None:
                    current_start = section["start_time"]
                    current_start_sec = section["start_seconds"]
                current_end = section["end_time"]
                current_end_sec = section["end_seconds"]
            else:
                # Save current chunk
                chunks.append({
                    "text": "\n".join(current_chunk_text),
                    "start_time": current_start,
                    "end_time": current_end,
                    "start_seconds": current_start_sec,
                    "end_seconds": current_end_sec,
                    "word_count": len(" ".join(current_chunk_text).split())
                })

                # Start new chunk with overlap
                overlap_text = self._get_overlap(current_chunk_text)
                current_chunk_text = [overlap_text, section["text"]] if overlap_text else [section["text"]]
                current_start = section["start_time"]
                current_start_sec = section["start_seconds"]
                current_end = section["end_time"]
                current_end_sec = section["end_seconds"]

        # Add final chunk
        if current_chunk_text:
            chunks.append({
                "text": "\n".join(current_chunk_text),
                "start_time": current_start,
                "end_time": current_end,
                "start_seconds": current_start_sec,
                "end_seconds": current_end_sec,
                "word_count": len(" ".join(current_chunk_text).split())
            })

        return chunks

    def _parse_transcript_sections(self, transcript: str) -> List[Dict[str, Any]]:
        """Parse transcript with timestamp markers."""
        sections = []
        lines = transcript.split("\n")

        timestamp_pattern = re.compile(r"(\d{1,2}:\d{2}(?::\d{2})?)\s*(?:-\s*(\d{1,2}:\d{2}(?::\d{2})?))?")

        current_section = None
        current_text = []

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue

            match = timestamp_pattern.match(line_stripped)

            if match:
                # Save previous section
                if current_section and current_text:
                    current_section["text"] = "\n".join(current_text)
                    sections.append(current_section)

                # New section
                start_time = match.group(1)
                end_time = match.group(2) if match.group(2) else start_time

                current_section = {
                    "start_time": start_time,
                    "end_time": end_time,
                    "start_seconds": self._time_to_seconds(start_time),
                    "end_seconds": self._time_to_seconds(end_time),
                }
                current_text = []

                # Text after timestamp
                text_after = line_stripped[match.end():].strip()
                if text_after:
                    current_text.append(text_after)
            else:
                if current_section is not None:
                    current_text.append(line_stripped)

        # Final section
        if current_section and current_text:
            current_section["text"] = "\n".join(current_text)
            sections.append(current_section)

        return sections

    def _time_to_seconds(self, time_str: str) -> float:
        """Convert 'HH:MM:SS' or 'MM:SS' to seconds."""
        parts = time_str.split(":")
        try:
            if len(parts) == 3:
                h, m, s = map(int, parts)
                return h * 3600 + m * 60 + s
            elif len(parts) == 2:
                m, s = map(int, parts)
                return m * 60 + s
        except ValueError:
            pass
        return 0.0

    def _get_overlap(self, text_list: List[str]) -> str:
        """Get last portion for overlap (rough: last ~50 tokens)."""
        full_text = " ".join(text_list)
        # Rough overlap: last 200 chars ≈ 50 tokens
        if len(full_text) > 200:
            return full_text[-200:]
        return full_text

    def _chunk_plain_text(self, text: str) -> List[Dict[str, Any]]:
        """Fallback chunking without timestamps."""
        words = text.split()
        chunks = []

        # Rough: 500 tokens ≈ 2000 chars
        chunk_chars = 2000

        for i in range(0, len(text), chunk_chars):
            chunk_text = text[i:i + chunk_chars]
            chunks.append({
                "text": chunk_text,
                "start_time": None,
                "end_time": None,
                "start_seconds": None,
                "end_seconds": None,
                "word_count": len(chunk_text.split())
            })

        return chunks


class TranscriptProcessor:
    """
    Orchestrates chunking + embedding for videos.
    Phase 1: Complete RAG pipeline.
    """

    def __init__(self):
        self.chunker = SemanticChunker()
        self.embedder = EmbeddingService()

    def process_transcript(
        self,
        db: Session,
        video_id: str,
        transcript: str
    ) -> int:
        """
        Process transcript: chunk, embed, store.

        Returns:
            Number of chunks created
        """
        logger.info(f"[Phase 1] Processing transcript for video {video_id}")

        # Step 1: Chunk
        chunks = self.chunker.chunk_transcript(transcript)
        logger.info(f"Created {len(chunks)} semantic chunks")

        # Step 2: Generate embeddings
        chunk_texts = [chunk["text"] for chunk in chunks]
        embeddings = self.embedder.embed_batch(chunk_texts)
        logger.info(f"Generated {len(embeddings)} embeddings")

        # Step 3: Delete existing chunks (if reprocessing)
        db.query(TranscriptChunk).filter(
            TranscriptChunk.video_id == video_id
        ).delete()

        # Step 4: Store chunks
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_record = TranscriptChunk(
                video_id=video_id,
                chunk_index=idx,
                text=chunk["text"],
                start_time=chunk.get("start_time"),
                end_time=chunk.get("end_time"),
                start_seconds=chunk.get("start_seconds"),
                end_seconds=chunk.get("end_seconds"),
                embedding=embedding,
                word_count=chunk.get("word_count", 0)
            )
            db.add(chunk_record)

        db.commit()
        logger.info(f"[Phase 1] Stored {len(chunks)} chunks for video {video_id}")
        return len(chunks)

    def is_processed(self, db: Session, video_id: str) -> bool:
        """Check if video has chunks."""
        count = db.query(TranscriptChunk).filter(
            TranscriptChunk.video_id == video_id
        ).count()
        return count > 0
