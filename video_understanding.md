# Video Understanding Optimization Plan

## Overview
Transform the current primitive video chat system from sending entire 5000-6000 token transcripts to an intelligent RAG-based system that maintains timestamp accuracy while reducing token usage by 80-90%.

**Current State:** Sending full transcript on every query
**Target State:** Smart retrieval with semantic chunking, hierarchical summaries, and timestamp preservation

---

## Phase 1: Basic RAG with Semantic Chunking

### Objective
Implement core RAG infrastructure with semantic chunking and vector-based retrieval while maintaining exact timestamp references.

### Components to Build

#### 1.1 Database Schema Extensions
**File:** `src/models.py`

Add new models for storing embeddings and chunks:

```python
class TranscriptChunk(Base):
    __tablename__ = "transcript_chunks"

    id = Column(String, primary_key=True)  # f"{video_id}_chunk_{index}"
    video_id = Column(String, ForeignKey("videos.id"), index=True)
    chunk_index = Column(Integer)

    # Content
    text = Column(Text)  # Chunk text content

    # Timestamps
    start_time = Column(String)  # "00:05:23"
    end_time = Column(String)    # "00:06:15"
    start_seconds = Column(Float)  # 323.0 (for easy math)
    end_seconds = Column(Float)    # 375.0

    # Embedding (stored as JSON array for now, migrate to pgvector later)
    embedding = Column(JSON)  # [0.123, -0.456, ...] 1536 dimensions

    # Metadata
    section_title = Column(String, nullable=True)  # "Introduction to Neural Networks"
    word_count = Column(Integer)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    video = relationship("Video", back_populates="transcript_chunks")

# Add to Video model:
# transcript_chunks = relationship("TranscriptChunk", back_populates="video")
```

#### 1.2 Semantic Chunking Service
**File:** `src/services/chunking_service.py` (NEW)

Smart chunking based on semantic boundaries (paragraphs, topic shifts):

```python
from typing import List, Dict, Any
import re
from langchain.text_splitter import RecursiveCharacterTextSplitter
from tiktoken import get_encoding

class SemanticChunker:
    """
    Chunks video transcripts semantically, preserving timestamps.
    Uses RecursiveCharacterTextSplitter for natural text boundaries.
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        """
        Args:
            chunk_size: Target tokens per chunk (not hard limit)
            chunk_overlap: Overlap tokens to preserve context
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.tokenizer = get_encoding("cl100k_base")  # GPT-4 tokenizer

        # Semantic splitter prioritizes natural boundaries
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=self._count_tokens,
            separators=[
                "\n\n",  # Paragraph breaks (highest priority)
                "\n",    # Line breaks
                ". ",    # Sentence ends
                "! ",    # Exclamations
                "? ",    # Questions
                "; ",    # Semicolons
                ", ",    # Commas
                " ",     # Words
                ""       # Characters (last resort)
            ],
            keep_separator=True
        )

    def _count_tokens(self, text: str) -> int:
        """Count tokens using GPT-4 tokenizer."""
        return len(self.tokenizer.encode(text))

    def chunk_transcript_with_timestamps(
        self,
        transcript: str,
        json_data: List[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Chunk transcript while preserving timestamps.

        Args:
            transcript: Full transcript text (formatted with timestamps)
            json_data: Original JSON from YouTube API with word-level timing

        Returns:
            List of chunk dicts with text, timestamps, and metadata
        """
        # Parse formatted transcript (e.g., "00:00 - 00:30\nWelcome to...")
        segments = self._parse_formatted_transcript(transcript)

        # If no timestamps found, fall back to plain chunking
        if not segments:
            return self._chunk_plain_text(transcript)

        # Chunk with timestamp awareness
        chunks = []
        current_text = []
        current_start = None
        current_end = None

        for segment in segments:
            # Try adding this segment to current chunk
            test_text = "\n".join(current_text + [segment["text"]])

            if self._count_tokens(test_text) <= self.chunk_size or not current_text:
                # Add to current chunk
                current_text.append(segment["text"])
                if current_start is None:
                    current_start = segment["start_time"]
                    current_start_sec = segment["start_seconds"]
                current_end = segment["end_time"]
                current_end_sec = segment["end_seconds"]
            else:
                # Save current chunk and start new one
                chunks.append({
                    "text": "\n".join(current_text),
                    "start_time": current_start,
                    "end_time": current_end,
                    "start_seconds": current_start_sec,
                    "end_seconds": current_end_sec,
                    "word_count": len(" ".join(current_text).split())
                })

                # Start new chunk with overlap
                overlap_text = self._get_overlap_text(current_text)
                current_text = [overlap_text, segment["text"]] if overlap_text else [segment["text"]]
                current_start = segment["start_time"]
                current_start_sec = segment["start_seconds"]
                current_end = segment["end_time"]
                current_end_sec = segment["end_seconds"]

        # Add final chunk
        if current_text:
            chunks.append({
                "text": "\n".join(current_text),
                "start_time": current_start,
                "end_time": current_end,
                "start_seconds": current_start_sec,
                "end_seconds": current_end_sec,
                "word_count": len(" ".join(current_text).split())
            })

        return chunks

    def _parse_formatted_transcript(self, transcript: str) -> List[Dict[str, Any]]:
        """Parse transcript with timestamp markers like '00:00 - 00:30'."""
        segments = []
        lines = transcript.split("\n")

        current_segment = None
        timestamp_pattern = re.compile(r"(\d{2}:\d{2}(?::\d{2})?)\s*-\s*(\d{2}:\d{2}(?::\d{2})?)")

        for line in lines:
            match = timestamp_pattern.match(line.strip())
            if match:
                # Save previous segment
                if current_segment:
                    segments.append(current_segment)

                # Start new segment
                start_time = match.group(1)
                end_time = match.group(2)
                current_segment = {
                    "start_time": start_time,
                    "end_time": end_time,
                    "start_seconds": self._time_to_seconds(start_time),
                    "end_seconds": self._time_to_seconds(end_time),
                    "text": ""
                }
            elif current_segment:
                current_segment["text"] += line + "\n"

        # Add final segment
        if current_segment:
            segments.append(current_segment)

        return segments

    def _time_to_seconds(self, time_str: str) -> float:
        """Convert '00:05:23' or '05:23' to seconds."""
        parts = time_str.split(":")
        if len(parts) == 3:
            h, m, s = map(int, parts)
            return h * 3600 + m * 60 + s
        elif len(parts) == 2:
            m, s = map(int, parts)
            return m * 60 + s
        return 0.0

    def _get_overlap_text(self, text_list: List[str]) -> str:
        """Get last N tokens for overlap."""
        full_text = " ".join(text_list)
        tokens = self.tokenizer.encode(full_text)

        if len(tokens) <= self.chunk_overlap:
            return full_text

        overlap_tokens = tokens[-self.chunk_overlap:]
        return self.tokenizer.decode(overlap_tokens)

    def _chunk_plain_text(self, text: str) -> List[Dict[str, Any]]:
        """Fallback for text without timestamps."""
        chunks = self.splitter.split_text(text)
        return [
            {
                "text": chunk,
                "start_time": None,
                "end_time": None,
                "start_seconds": None,
                "end_seconds": None,
                "word_count": len(chunk.split())
            }
            for chunk in chunks
        ]
```

#### 1.3 Embedding Service
**File:** `src/services/embedding_service.py` (NEW)

Generate and manage embeddings using OpenAI's text-embedding-3-small:

```python
from openai import OpenAI
from typing import List, Dict, Any
import numpy as np
from controllers.config import logger

class EmbeddingService:
    """
    Generates embeddings for text chunks using OpenAI.
    Uses text-embedding-3-small (cheaper, faster, good quality).
    """

    def __init__(self):
        self.client = OpenAI()
        self.model = "text-embedding-3-small"  # 1536 dimensions, $0.02/1M tokens
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
        """
        Generate embeddings for multiple texts in batches.
        OpenAI allows up to 2048 texts per batch.
        """
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
            except Exception as e:
                logger.error(f"Error in batch {i}-{i+batch_size}: {e}")
                # Fallback to individual embedding
                for text in batch:
                    embeddings.append(self.embed_text(text))

        return embeddings

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))

    def find_most_similar(
        self,
        query_embedding: List[float],
        candidate_embeddings: List[Dict[str, Any]],
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find top-k most similar embeddings.

        Args:
            query_embedding: Query vector
            candidate_embeddings: List of dicts with 'embedding' and metadata
            top_k: Number of results to return

        Returns:
            Top-k candidates sorted by similarity (highest first)
        """
        similarities = []

        for candidate in candidate_embeddings:
            similarity = self.cosine_similarity(
                query_embedding,
                candidate["embedding"]
            )
            similarities.append({
                **candidate,
                "similarity": similarity
            })

        # Sort by similarity descending
        similarities.sort(key=lambda x: x["similarity"], reverse=True)
        return similarities[:top_k]
```

#### 1.4 Transcript Processing Pipeline
**File:** `src/services/transcript_processor.py` (NEW)

Orchestrates chunking and embedding for new videos:

```python
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from models import Video, TranscriptChunk
from services.chunking_service import SemanticChunker
from services.embedding_service import EmbeddingService
from controllers.config import logger

class TranscriptProcessor:
    """
    Processes video transcripts: chunks, embeds, stores.
    """

    def __init__(self):
        self.chunker = SemanticChunker(chunk_size=500, chunk_overlap=50)
        self.embedder = EmbeddingService()

    def process_transcript(
        self,
        db: Session,
        video_id: str,
        transcript: str,
        json_data: List[Dict[str, Any]] = None
    ) -> int:
        """
        Process transcript: chunk, embed, store in database.

        Returns:
            Number of chunks created
        """
        logger.info(f"Processing transcript for video {video_id}")

        # Step 1: Chunk the transcript
        chunks = self.chunker.chunk_transcript_with_timestamps(transcript, json_data)
        logger.info(f"Created {len(chunks)} semantic chunks")

        # Step 2: Generate embeddings in batch
        chunk_texts = [chunk["text"] for chunk in chunks]
        embeddings = self.embedder.embed_batch(chunk_texts)
        logger.info(f"Generated {len(embeddings)} embeddings")

        # Step 3: Delete existing chunks for this video (if reprocessing)
        db.query(TranscriptChunk).filter(
            TranscriptChunk.video_id == video_id
        ).delete()

        # Step 4: Store chunks in database
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_record = TranscriptChunk(
                id=f"{video_id}_chunk_{idx}",
                video_id=video_id,
                chunk_index=idx,
                text=chunk["text"],
                start_time=chunk.get("start_time"),
                end_time=chunk.get("end_time"),
                start_seconds=chunk.get("start_seconds"),
                end_seconds=chunk.get("end_seconds"),
                embedding=embedding,  # Store as JSON for now
                word_count=chunk.get("word_count", 0)
            )
            db.add(chunk_record)

        db.commit()
        logger.info(f"Stored {len(chunks)} chunks for video {video_id}")
        return len(chunks)

    def is_processed(self, db: Session, video_id: str) -> bool:
        """Check if video already has chunks."""
        count = db.query(TranscriptChunk).filter(
            TranscriptChunk.video_id == video_id
        ).count()
        return count > 0
```

#### 1.5 RAG Query Service
**File:** `src/services/rag_service.py` (NEW)

Retrieve relevant chunks for user queries:

```python
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from models import TranscriptChunk
from services.embedding_service import EmbeddingService
from controllers.config import logger

class RAGService:
    """
    Retrieval-Augmented Generation service for video queries.
    """

    def __init__(self):
        self.embedder = EmbeddingService()

    def retrieve_relevant_chunks(
        self,
        db: Session,
        video_id: str,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Retrieve most relevant chunks for a query.

        Returns:
            List of chunk dicts with text, timestamps, similarity score
        """
        # Step 1: Embed the query
        query_embedding = self.embedder.embed_text(query)

        # Step 2: Get all chunks for this video
        chunks = db.query(TranscriptChunk).filter(
            TranscriptChunk.video_id == video_id
        ).order_by(TranscriptChunk.chunk_index).all()

        if not chunks:
            logger.warning(f"No chunks found for video {video_id}")
            return []

        # Step 3: Calculate similarities
        candidates = []
        for chunk in chunks:
            if chunk.embedding:
                candidates.append({
                    "chunk_id": chunk.id,
                    "text": chunk.text,
                    "start_time": chunk.start_time,
                    "end_time": chunk.end_time,
                    "start_seconds": chunk.start_seconds,
                    "end_seconds": chunk.end_seconds,
                    "embedding": chunk.embedding
                })

        # Step 4: Find top-k most similar
        results = self.embedder.find_most_similar(
            query_embedding,
            candidates,
            top_k=top_k
        )

        # Step 5: Format results
        formatted_results = []
        for result in results:
            formatted_results.append({
                "chunk_id": result["chunk_id"],
                "text": result["text"],
                "start_time": result["start_time"],
                "end_time": result["end_time"],
                "similarity": result["similarity"],
                "relevance_score": round(result["similarity"] * 100, 1)
            })

        logger.info(f"Retrieved {len(formatted_results)} chunks (top scores: {[r['relevance_score'] for r in formatted_results[:3]]})")
        return formatted_results

    def build_context_from_chunks(
        self,
        chunks: List[Dict[str, Any]],
        include_timestamps: bool = True
    ) -> str:
        """
        Build context string from retrieved chunks.

        Format:
        [00:05:23 - 00:06:15]
        Neural networks consist of layers...

        [00:12:30 - 00:13:45]
        Backpropagation is the process...
        """
        context_parts = []

        for chunk in chunks:
            if include_timestamps and chunk.get("start_time"):
                context_parts.append(
                    f"[{chunk['start_time']} - {chunk['end_time']}]\n{chunk['text']}"
                )
            else:
                context_parts.append(chunk['text'])

        return "\n\n".join(context_parts)
```

#### 1.6 Update Query Route
**File:** `src/routes/query.py`

Modify to use RAG instead of full transcript:

```python
# Add imports at top
from services.transcript_processor import TranscriptProcessor
from services.rag_service import RAGService

# In process_query function, replace the transcript fetching logic:

processor = TranscriptProcessor()
rag_service = RAGService()

# Ensure transcript is processed (chunked + embedded)
if not processor.is_processed(db, video_id):
    # Get transcript
    formatting_status_info = get_formatting_status(db, video_id)
    if formatting_status_info["status"] == "completed":
        transcript_to_use = formatting_status_info["formatted_transcript"]
        json_data = None
    else:
        transcript_info = get_transcript_cache(db, video_id)
        if transcript_info and transcript_info.get("transcript_data"):
            transcript_to_use = transcript_info["transcript_data"]
            json_data = transcript_info.get("json_data")
        else:
            transcript_to_use, json_data = download_transcript_api(video_id)
            update_transcript_cache(db, video_id, transcript_to_use, json_data)

    # Process transcript (chunk + embed)
    processor.process_transcript(db, video_id, transcript_to_use, json_data)

# Retrieve relevant chunks using RAG
relevant_chunks = rag_service.retrieve_relevant_chunks(
    db=db,
    video_id=video_id,
    query=query,
    top_k=5  # Get top 5 most relevant chunks
)

# Build compact context from chunks
context_for_llm = rag_service.build_context_from_chunks(relevant_chunks)

# Use context_for_llm instead of full transcript (80-90% token reduction!)
```

### Migration Script
**File:** `src/management_commands/migrations/process_existing_transcripts.py` (NEW)

Process existing videos:

```python
"""
Migration: Process existing transcripts into chunks + embeddings
Run: python -m src.management_commands.migrations.process_existing_transcripts
"""

from utils.db import SessionLocal
from models import Video
from services.transcript_processor import TranscriptProcessor
from controllers.db_helpers import get_transcript_cache
from controllers.config import logger

def process_all_videos():
    db = SessionLocal()
    processor = TranscriptProcessor()

    videos = db.query(Video).all()
    logger.info(f"Processing {len(videos)} videos")

    for idx, video in enumerate(videos):
        logger.info(f"[{idx+1}/{len(videos)}] Processing video {video.id}")

        # Skip if already processed
        if processor.is_processed(db, video.id):
            logger.info(f"  Already processed, skipping")
            continue

        # Get transcript
        transcript_info = get_transcript_cache(db, video.id)
        if not transcript_info or not transcript_info.get("transcript_data"):
            logger.warning(f"  No transcript found, skipping")
            continue

        # Process
        try:
            num_chunks = processor.process_transcript(
                db=db,
                video_id=video.id,
                transcript=transcript_info["transcript_data"],
                json_data=transcript_info.get("json_data")
            )
            logger.info(f"  Created {num_chunks} chunks")
        except Exception as e:
            logger.error(f"  Error: {e}")
            continue

    logger.info("Migration complete!")
    db.close()

if __name__ == "__main__":
    process_all_videos()
```

### Testing & Validation
- Test with sample videos (short, medium, long)
- Compare responses: full transcript vs RAG
- Verify timestamp accuracy
- Measure token reduction

### Success Metrics
- ✅ 80-90% reduction in input tokens
- ✅ Timestamp accuracy maintained at 100%
- ✅ Response quality comparable to full transcript
- ✅ Retrieval speed < 100ms

---

## Phase 2: Hierarchical Summaries

### Objective
Add multi-level summaries for handling broad questions efficiently and improving context understanding.

### Components to Build

#### 2.1 Extended Database Schema
**File:** `src/models.py`

Add VideoSummary model:

```python
class VideoSummary(Base):
    __tablename__ = "video_summaries"

    id = Column(String, primary_key=True)
    video_id = Column(String, ForeignKey("videos.id"), unique=True, index=True)

    # Level 1: High-level overview
    overview_summary = Column(Text)  # 50-100 tokens
    key_topics = Column(JSON)  # ["Neural Networks", "Backpropagation", ...]

    # Level 2: Section summaries
    sections = Column(JSON)  # [{"title": "...", "start": "...", "end": "...", "summary": "..."}]

    # Metadata
    total_duration_seconds = Column(Float)
    num_chunks = Column(Integer)
    processing_status = Column(String)  # 'pending', 'completed', 'failed'

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    # Relationships
    video = relationship("Video", back_populates="summary")

# Add to Video model:
# summary = relationship("VideoSummary", back_populates="video", uselist=False)
```

#### 2.2 Summary Generation Service
**File:** `src/services/summary_service.py` (NEW)

Generate hierarchical summaries using LLM:

```python
from openai import OpenAI
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from models import Video, TranscriptChunk, VideoSummary
from controllers.config import logger
import json

class SummaryService:
    """
    Generates hierarchical summaries for videos.
    Level 1: Overview (50-100 tokens)
    Level 2: Section summaries (5-10 sections)
    """

    def __init__(self):
        self.client = OpenAI()
        self.model = "gpt-4o-mini"  # Cost-effective for summaries

    def generate_video_summary(
        self,
        db: Session,
        video_id: str
    ) -> Dict[str, Any]:
        """
        Generate complete hierarchical summary for a video.
        """
        logger.info(f"Generating summary for video {video_id}")

        # Get video and chunks
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise ValueError(f"Video {video_id} not found")

        chunks = db.query(TranscriptChunk).filter(
            TranscriptChunk.video_id == video_id
        ).order_by(TranscriptChunk.chunk_index).all()

        if not chunks:
            raise ValueError(f"No chunks found for video {video_id}")

        # Step 1: Generate overview summary
        overview = self._generate_overview(video, chunks)

        # Step 2: Generate section summaries
        sections = self._generate_sections(video, chunks)

        # Step 3: Extract key topics
        key_topics = self._extract_key_topics(overview, sections)

        # Step 4: Store in database
        summary_record = db.query(VideoSummary).filter(
            VideoSummary.video_id == video_id
        ).first()

        if summary_record:
            # Update existing
            summary_record.overview_summary = overview
            summary_record.sections = sections
            summary_record.key_topics = key_topics
            summary_record.num_chunks = len(chunks)
            summary_record.processing_status = "completed"
        else:
            # Create new
            summary_record = VideoSummary(
                id=f"summary_{video_id}",
                video_id=video_id,
                overview_summary=overview,
                sections=sections,
                key_topics=key_topics,
                total_duration_seconds=chunks[-1].end_seconds if chunks else 0,
                num_chunks=len(chunks),
                processing_status="completed"
            )
            db.add(summary_record)

        db.commit()
        logger.info(f"Summary created with {len(sections)} sections")

        return {
            "overview": overview,
            "sections": sections,
            "key_topics": key_topics
        }

    def _generate_overview(
        self,
        video: Video,
        chunks: List[TranscriptChunk]
    ) -> str:
        """Generate high-level overview (50-100 tokens)."""

        # Sample chunks throughout video for coverage
        sample_size = min(10, len(chunks))
        step = max(1, len(chunks) // sample_size)
        sampled_chunks = [chunks[i] for i in range(0, len(chunks), step)]

        context = "\n\n".join([c.text for c in sampled_chunks])

        prompt = f"""Analyze this video transcript and provide a concise overview.

Video Title: {video.title or 'Unknown'}

Sampled Content:
{context[:3000]}  # Limit to avoid token overflow

Provide a 2-3 sentence overview (50-100 tokens) covering:
1. Main topic/subject
2. Key concepts covered
3. Target audience or purpose

Overview:"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that creates concise video summaries."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.3
        )

        return response.choices[0].message.content.strip()

    def _generate_sections(
        self,
        video: Video,
        chunks: List[TranscriptChunk]
    ) -> List[Dict[str, Any]]:
        """
        Generate section summaries (5-10 sections).
        Each section covers a topic/time range.
        """

        # Divide chunks into sections (aim for 5-10 sections)
        num_sections = min(10, max(5, len(chunks) // 5))
        section_size = len(chunks) // num_sections

        sections = []

        for i in range(num_sections):
            start_idx = i * section_size
            end_idx = start_idx + section_size if i < num_sections - 1 else len(chunks)
            section_chunks = chunks[start_idx:end_idx]

            if not section_chunks:
                continue

            # Generate section summary
            section_text = "\n\n".join([c.text for c in section_chunks])

            prompt = f"""Summarize this section of a video transcript in 2-3 sentences (30-50 tokens).
Focus on the main concept or topic discussed.

Section Content:
{section_text[:2000]}

Summary:"""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You create brief section summaries."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=100,
                temperature=0.3
            )

            summary = response.choices[0].message.content.strip()

            # Extract title from first sentence
            title = summary.split('.')[0][:50]

            sections.append({
                "section_index": i,
                "title": title,
                "start_time": section_chunks[0].start_time,
                "end_time": section_chunks[-1].end_time,
                "start_seconds": section_chunks[0].start_seconds,
                "end_seconds": section_chunks[-1].end_seconds,
                "summary": summary,
                "chunk_ids": [c.id for c in section_chunks]
            })

        return sections

    def _extract_key_topics(
        self,
        overview: str,
        sections: List[Dict[str, Any]]
    ) -> List[str]:
        """Extract 3-7 key topics from overview and sections."""

        section_titles = [s["title"] for s in sections]

        prompt = f"""Extract 3-7 key topics from this video.

Overview: {overview}

Section Topics:
{chr(10).join(f"- {t}" for t in section_titles)}

Return ONLY a JSON object with a "topics" array:
{{"topics": ["Topic 1", "Topic 2", ...]}}"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "Extract key topics as JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            max_tokens=100,
            temperature=0.3
        )

        try:
            result = json.loads(response.choices[0].message.content)
            return result.get("topics", section_titles[:5])
        except:
            return section_titles[:5]  # Fallback
```

#### 2.3 Enhanced RAG Service
**File:** `src/services/rag_service.py`

Add intelligent routing using summaries:

```python
from services.summary_service import SummaryService
from models import VideoSummary

class RAGService:
    # ... existing code ...

    def __init__(self):
        self.embedder = EmbeddingService()
        self.summary_service = SummaryService()  # NEW

    def retrieve_with_hierarchy(
        self,
        db: Session,
        video_id: str,
        query: str,
        top_k: int = 5
    ) -> Dict[str, Any]:
        """
        Intelligent retrieval using hierarchical summaries.

        Strategy:
        1. Classify query type (broad vs specific)
        2. For broad: use overview + section summaries
        3. For specific: use RAG chunk retrieval
        4. Hybrid: combine both
        """

        # Get video summary
        summary = db.query(VideoSummary).filter(
            VideoSummary.video_id == video_id
        ).first()

        if not summary:
            # Fallback to basic RAG
            chunks = self.retrieve_relevant_chunks(db, video_id, query, top_k)
            return {
                "strategy": "basic_rag",
                "chunks": chunks,
                "context": self.build_context_from_chunks(chunks)
            }

        # Classify query
        query_type = self._classify_query(query, summary)

        if query_type == "broad":
            # Use overview + sections
            context = self._build_hierarchical_context(summary)
            return {
                "strategy": "hierarchical",
                "summary": summary.overview_summary,
                "sections": summary.sections,
                "context": context
            }

        elif query_type == "specific":
            # Use detailed RAG chunks
            chunks = self.retrieve_relevant_chunks(db, video_id, query, top_k)
            return {
                "strategy": "specific_rag",
                "chunks": chunks,
                "context": self.build_context_from_chunks(chunks)
            }

        else:  # hybrid
            # Combine overview + relevant chunks
            chunks = self.retrieve_relevant_chunks(db, video_id, query, top_k=3)
            context = f"Video Overview: {summary.overview_summary}\n\n"
            context += "Relevant Sections:\n"
            context += self.build_context_from_chunks(chunks)

            return {
                "strategy": "hybrid",
                "summary": summary.overview_summary,
                "chunks": chunks,
                "context": context
            }

    def _classify_query(
        self,
        query: str,
        summary: VideoSummary
    ) -> str:
        """
        Classify query as:
        - 'broad': Overview questions (What is this about? Summarize...)
        - 'specific': Detailed questions (How does X work? At what timestamp...)
        - 'hybrid': Middle ground
        """

        # Simple heuristic-based classification
        query_lower = query.lower()

        broad_indicators = [
            "what is this about", "summarize", "overview", "main topic",
            "what does this cover", "key points", "in general"
        ]

        specific_indicators = [
            "how does", "why does", "explain", "at what time",
            "timestamp", "when does", "what happens at"
        ]

        broad_score = sum(1 for phrase in broad_indicators if phrase in query_lower)
        specific_score = sum(1 for phrase in specific_indicators if phrase in query_lower)

        if broad_score > specific_score:
            return "broad"
        elif specific_score > broad_score:
            return "specific"
        else:
            return "hybrid"

    def _build_hierarchical_context(self, summary: VideoSummary) -> str:
        """Build context from overview + sections."""

        context = f"Video Overview:\n{summary.overview_summary}\n\n"
        context += "Key Topics:\n" + ", ".join(summary.key_topics) + "\n\n"
        context += "Sections:\n"

        for section in summary.sections:
            context += f"\n[{section['start_time']} - {section['end_time']}] {section['title']}\n"
            context += f"{section['summary']}\n"

        return context
```

#### 2.4 Background Processing
**File:** `src/controllers/background_tasks.py`

Add summary generation to background tasks:

```python
from services.summary_service import SummaryService
from utils.db import SessionLocal

def generate_summary_background(video_id: str):
    """Background task to generate video summary."""
    db = SessionLocal()
    summary_service = SummaryService()

    try:
        summary_service.generate_video_summary(db, video_id)
        logger.info(f"Summary generated for video {video_id}")
    except Exception as e:
        logger.error(f"Error generating summary for {video_id}: {e}")
    finally:
        db.close()

# Trigger after transcript processing in query.py:
# from controllers.background_tasks import generate_summary_background
# download_executor.submit(generate_summary_background, video_id)
```

#### 2.5 Update Query Route
**File:** `src/routes/query.py`

Use hierarchical retrieval:

```python
# Replace basic RAG call with hierarchical:

retrieval_result = rag_service.retrieve_with_hierarchy(
    db=db,
    video_id=video_id,
    query=query,
    top_k=5
)

context_for_llm = retrieval_result["context"]
retrieval_strategy = retrieval_result["strategy"]

# Log strategy for analytics
logger.info(f"Used {retrieval_strategy} strategy for query")
```

### Migration Script
**File:** `src/management_commands/migrations/generate_video_summaries.py` (NEW)

```python
"""
Generate summaries for all existing videos
Run: python -m src.management_commands.migrations.generate_video_summaries
"""

from utils.db import SessionLocal
from models import Video
from services.summary_service import SummaryService
from controllers.config import logger

def generate_all_summaries():
    db = SessionLocal()
    summary_service = SummaryService()

    videos = db.query(Video).all()

    for idx, video in enumerate(videos):
        logger.info(f"[{idx+1}/{len(videos)}] Generating summary for {video.id}")

        try:
            summary_service.generate_video_summary(db, video.id)
        except Exception as e:
            logger.error(f"Error: {e}")

    logger.info("Done!")
    db.close()

if __name__ == "__main__":
    generate_all_summaries()
```

### Success Metrics
- ✅ Broad questions answered from summaries only (minimal tokens)
- ✅ Specific questions get precise chunks with timestamps
- ✅ Hybrid approach handles middle-ground queries
- ✅ Average token usage: 600-1200 (vs 5000-6000 baseline)

---

## Phase 3: Adaptive Chunking Optimization

### Objective
Optimize chunking strategy based on actual query patterns and user behavior.

### Components

#### 3.1 Query Analytics Schema
```python
class QueryAnalytics(Base):
    __tablename__ = "query_analytics"

    id = Column(String, primary_key=True)
    video_id = Column(String, ForeignKey("videos.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"))

    query_text = Column(Text)
    query_type = Column(String)  # 'broad', 'specific', 'hybrid'

    # Retrieval metrics
    retrieval_strategy = Column(String)
    chunks_retrieved = Column(JSON)
    num_chunks = Column(Integer)

    # Quality metrics
    response_time_ms = Column(Float)
    tokens_used = Column(Integer)
    user_satisfaction = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
```

#### 3.2 Analytics Service
Track and analyze query patterns to identify:
- Hot chunks (frequently retrieved)
- Cold chunks (rarely accessed)
- Optimal chunk sizes per content type
- Query patterns by video

#### 3.3 Adaptive Chunking
Dynamically adjust chunk size based on:
- Content density (technical vs narrative)
- Video length
- Historical query patterns
- User engagement

#### 3.4 A/B Testing
Test different chunking strategies:
- Small chunks (300 tokens)
- Medium chunks (500 tokens)
- Large chunks (700 tokens)
- Adaptive (variable based on content)

### Success Metrics
- ✅ 15-20% further token reduction
- ✅ Improved retrieval relevance
- ✅ Optimal chunk size identified per content type

---

## Phase 4: Hybrid Search & Advanced Retrieval

### Objective
Combine semantic search with keyword matching for maximum retrieval accuracy.

### Components

#### 4.1 BM25 Keyword Search
Classic keyword matching for exact term retrieval:
- Handles technical terms, names, acronyms
- Complements semantic search
- Fast exact matching

#### 4.2 Hybrid Retrieval
Combine semantic + keyword search using Reciprocal Rank Fusion (RRF):
```
RRF_score = (weight_semantic / (k + rank_semantic)) + (weight_keyword / (k + rank_keyword))
```

Default weights:
- Semantic: 0.7
- Keyword: 0.3

#### 4.3 Query Expansion
Expand queries with synonyms and related terms using LLM:
- Original: "neural network training"
- Expanded: ["neural network training", "backpropagation process", "gradient descent optimization"]

#### 4.4 Re-ranking with Cross-Encoder
Final precision boost using cross-encoder model:
- Re-rank top-k candidates
- More accurate than bi-encoder embeddings
- Applied only to final candidates (efficiency)

#### 4.5 Configuration
```python
class RAGConfig:
    # Phase 1: Basic RAG
    ENABLE_RAG = True
    DEFAULT_CHUNK_SIZE = 500
    DEFAULT_TOP_K = 5

    # Phase 2: Hierarchical
    ENABLE_HIERARCHICAL_SUMMARIES = True

    # Phase 3: Adaptive
    ENABLE_ANALYTICS = True
    ENABLE_ADAPTIVE_CHUNKING = False  # Enable after testing

    # Phase 4: Hybrid
    ENABLE_HYBRID_SEARCH = False  # Enable after testing
    ENABLE_RERANKING = False
    SEMANTIC_WEIGHT = 0.7
    KEYWORD_WEIGHT = 0.3
```

### Success Metrics
- ✅ 10-15% improvement in retrieval precision
- ✅ Better handling of technical terminology
- ✅ Reduced "no relevant answer" responses

---

## Implementation Timeline

### Phase 1 (Week 1-2)
- Database migrations
- Semantic chunking service
- Embedding service
- Basic RAG retrieval
- Migration script for existing videos
- **Deliverable:** 80-90% token reduction

### Phase 2 (Week 2-3)
- Summary generation service
- Hierarchical retrieval logic
- Query classification
- Background processing
- **Deliverable:** Intelligent routing

### Phase 3 (Week 3-4)
- Analytics schema and service
- Adaptive chunking
- A/B testing framework
- **Deliverable:** Data-driven optimization

### Phase 4 (Week 4-5)
- BM25 keyword search
- Hybrid retrieval
- Re-ranking
- Query expansion
- **Deliverable:** Production-ready advanced RAG

---

## Cost Analysis

### Current System
- Input: 5500 tokens/query
- Model: GPT-4o ($3/1M input tokens)
- Cost per 1K queries: **$16.50**

### Phase 1 (Basic RAG)
- Input: 800 tokens/query
- Embedding cost: $0.02/1M tokens (one-time)
- Cost per 1K queries: **$2.40** (85% savings)

### Phase 2 (Hierarchical)
- Broad queries: 400 tokens
- Specific queries: 800 tokens
- Average: 600 tokens/query
- Cost per 1K queries: **$1.80** (89% savings)

### Annual Savings (100K queries/month)
- Current: $19,800/year
- Optimized: $2,760/year
- **Savings: $17,040/year (86% reduction)**

---

## Monitoring & Success Metrics

### Key Metrics

1. **Token Efficiency**
   - Average input tokens per query
   - Target: < 1000 (vs 5500 baseline)

2. **Retrieval Quality**
   - Relevance score (similarity)
   - Target: > 0.75 average

3. **Response Quality**
   - Timestamp citation accuracy
   - Target: 100%

4. **Performance**
   - Retrieval latency
   - Target: < 150ms

5. **Cost**
   - Cost per query
   - Target: < $0.003

---

## Rollback Plan

Each phase can be independently disabled via feature flags in `RAGConfig`. If issues arise, disable the problematic phase and fall back to previous implementation.

---

## Next Steps After Phase 4

1. **Vector Database Migration**
   - Move to proper vector DB (Pinecone, Qdrant, Weaviate)
   - Enable faster similarity search at scale

2. **Multi-Modal RAG**
   - Add image frame embeddings
   - Combine visual + textual retrieval

3. **Personalized Retrieval**
   - User-specific query history
   - Personalized relevance ranking

4. **Real-time Processing**
   - Process chunks as transcript arrives
   - Enable chat on live videos
