"""
Hierarchical Summary Generation Service

Generates multi-level summaries for videos:
- Level 1: Overview (50-100 tokens)
- Level 2: Section summaries (5-10 sections with timestamps)

This enables intelligent query routing:
- Broad queries → Use summaries (low token usage)
- Specific queries → Use full transcript sections
"""

from openai import OpenAI
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from models import Video, VideoSummary, TranscriptChunk
from controllers.config import logger
from services.chunking_embedding_service import EmbeddingService
import json
import re


class SummaryService:
    """
    Generates hierarchical summaries for videos.
    """

    def __init__(self):
        self.client = OpenAI()
        self.model = "gpt-4o-mini"  # Cost-effective for summaries

    def generate_video_summary(
        self, db: Session, video_id: str, transcript: str
    ) -> Dict[str, Any]:
        """
        Generate complete hierarchical summary for a video.

        Args:
            db: Database session
            video_id: Video identifier
            transcript: Full transcript text

        Returns:
            Dictionary with overview, sections, and key_topics
        """
        logger.info(f"Generating summary for video {video_id}")

        # Get video record
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise ValueError(f"Video {video_id} not found")

        # Parse transcript to extract timestamps if available
        sections_data = self._parse_transcript_sections(transcript)

        try:
            # Step 1: Generate overview summary
            overview = self._generate_overview(video, transcript)

            # Step 2: Generate section summaries
            sections = self._generate_sections(sections_data, transcript)

            # Step 3: Extract key topics
            key_topics = self._extract_key_topics(overview, sections)

            # Calculate total duration
            total_duration = sections[-1]["end_seconds"] if sections else 0

            # Step 4: Store or update in database
            summary_record = (
                db.query(VideoSummary).filter(VideoSummary.video_id == video_id).first()
            )

            if summary_record:
                # Update existing
                summary_record.overview_summary = overview
                summary_record.sections = sections
                summary_record.key_topics = key_topics
                summary_record.total_duration_seconds = total_duration
                summary_record.processing_status = "completed"
                summary_record.error_message = None
            else:
                # Create new
                summary_record = VideoSummary(
                    video_id=video_id,
                    overview_summary=overview,
                    sections=sections,
                    key_topics=key_topics,
                    total_duration_seconds=total_duration,
                    processing_status="completed",
                )
                db.add(summary_record)

            db.commit()
            logger.info(
                f"Summary created for video {video_id} with {len(sections)} sections"
            )

            return {
                "overview": overview,
                "sections": sections,
                "key_topics": key_topics,
                "video_id": video_id,
            }

        except Exception as e:
            logger.error(f"Error generating summary for {video_id}: {e}")

            # Mark as failed in database
            summary_record = (
                db.query(VideoSummary).filter(VideoSummary.video_id == video_id).first()
            )
            if summary_record:
                summary_record.processing_status = "failed"
                summary_record.error_message = str(e)
            else:
                summary_record = VideoSummary(
                    video_id=video_id,
                    processing_status="failed",
                    error_message=str(e),
                )
                db.add(summary_record)

            db.commit()
            raise

    def _parse_transcript_sections(self, transcript: str) -> List[Dict[str, Any]]:
        """
        Parse transcript to identify natural sections based on timestamps.
        Looks for timestamp patterns like "00:00 - 00:30" or "0:00"
        """
        sections = []
        lines = transcript.split("\n")

        # Pattern for timestamps: "MM:SS" or "HH:MM:SS" or "MM:SS - MM:SS"
        timestamp_pattern = re.compile(
            r"(\d{1,2}:\d{2}(?::\d{2})?)\s*(?:-\s*(\d{1,2}:\d{2}(?::\d{2})?))?"
        )

        current_section = None
        current_text = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if line contains timestamp
            match = timestamp_pattern.search(line)

            if match:
                # Save previous section
                if current_section and current_text:
                    current_section["text"] = "\n".join(current_text)
                    sections.append(current_section)

                # Start new section
                start_time = match.group(1)
                end_time = match.group(2) if match.group(2) else start_time

                current_section = {
                    "start_time": start_time,
                    "end_time": end_time,
                    "start_seconds": self._time_to_seconds(start_time),
                    "end_seconds": self._time_to_seconds(end_time),
                }
                current_text = []

                # Add text after timestamp on same line
                text_after = line[match.end() :].strip()
                if text_after:
                    current_text.append(text_after)
            else:
                # Add to current section
                if current_section is not None:
                    current_text.append(line)

        # Add final section
        if current_section and current_text:
            current_section["text"] = "\n".join(current_text)
            sections.append(current_section)

        # If no timestamps found, create one section with full transcript
        if not sections:
            sections = [
                {
                    "start_time": "0:00",
                    "end_time": "0:00",
                    "start_seconds": 0,
                    "end_seconds": 0,
                    "text": transcript,
                }
            ]

        return sections

    def _time_to_seconds(self, time_str: str) -> float:
        """Convert '00:05:23' or '05:23' to seconds."""
        parts = time_str.split(":")
        try:
            if len(parts) == 3:
                h, m, s = map(int, parts)
                return h * 3600 + m * 60 + s
            elif len(parts) == 2:
                m, s = map(int, parts)
                return m * 60 + s
            else:
                return 0.0
        except ValueError:
            return 0.0

    def _generate_overview(self, video: Video, transcript: str) -> str:
        """Generate high-level overview (50-100 tokens)."""

        # Use first 3000 characters for overview generation
        context = transcript[:3000]

        prompt = f"""Analyze this video transcript and provide a concise overview.

Video Title: {video.title or 'Unknown'}

Transcript Excerpt:
{context}

Provide a 2-3 sentence overview (50-100 tokens) covering:
1. Main topic/subject
2. Key concepts covered
3. Target audience or purpose

Overview:"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that creates concise video summaries.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=150,
                temperature=0.3,
            )

            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Error generating overview: {e}")
            return "Unable to generate overview."

    def _generate_sections(
        self, sections_data: List[Dict[str, Any]], full_transcript: str
    ) -> List[Dict[str, Any]]:
        """
        Generate section summaries (5-10 sections).
        Each section covers a topic/time range with timestamps.
        """

        # If we have many small sections, group them into 5-10 larger sections
        target_sections = min(10, max(5, len(sections_data) // 3))

        if len(sections_data) <= target_sections:
            # Use existing sections
            grouped_sections = sections_data
        else:
            # Group smaller sections together
            section_size = len(sections_data) // target_sections
            grouped_sections = []

            for i in range(target_sections):
                start_idx = i * section_size
                end_idx = (
                    start_idx + section_size
                    if i < target_sections - 1
                    else len(sections_data)
                )

                group = sections_data[start_idx:end_idx]
                combined_text = "\n".join([s["text"] for s in group])

                grouped_sections.append(
                    {
                        "start_time": group[0]["start_time"],
                        "end_time": group[-1]["end_time"],
                        "start_seconds": group[0]["start_seconds"],
                        "end_seconds": group[-1]["end_seconds"],
                        "text": combined_text,
                    }
                )

        # Generate summaries for each section
        sections = []

        for i, section_data in enumerate(grouped_sections):
            section_text = section_data["text"][:2000]  # Limit to 2000 chars

            prompt = f"""Summarize this section of a video transcript in 2-3 sentences (30-50 tokens).
Focus on the main concept or topic discussed.

Section Content:
{section_text}

Summary:"""

            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You create brief section summaries.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=100,
                    temperature=0.3,
                )

                summary = response.choices[0].message.content.strip()

                # Extract title from first sentence (max 50 chars)
                title = summary.split(".")[0][:50]

                sections.append(
                    {
                        "section_index": i,
                        "title": title,
                        "start_time": section_data["start_time"],
                        "end_time": section_data["end_time"],
                        "start_seconds": section_data["start_seconds"],
                        "end_seconds": section_data["end_seconds"],
                        "summary": summary,
                    }
                )

            except Exception as e:
                logger.error(f"Error generating section {i} summary: {e}")
                # Fallback: use truncated text as summary
                sections.append(
                    {
                        "section_index": i,
                        "title": f"Section {i+1}",
                        "start_time": section_data["start_time"],
                        "end_time": section_data["end_time"],
                        "start_seconds": section_data["start_seconds"],
                        "end_seconds": section_data["end_seconds"],
                        "summary": section_text[:100] + "...",
                    }
                )

        return sections

    def _extract_key_topics(
        self, overview: str, sections: List[Dict[str, Any]]
    ) -> List[str]:
        """Extract 3-7 key topics from overview and sections."""

        section_titles = [s["title"] for s in sections]

        prompt = f"""Extract 3-7 key topics from this video.

Overview: {overview}

Section Topics:
{chr(10).join(f"- {t}" for t in section_titles)}

Return ONLY a JSON object with a "topics" array:
{{"topics": ["Topic 1", "Topic 2", ...]}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Extract key topics as JSON."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=100,
                temperature=0.3,
            )

            result = json.loads(response.choices[0].message.content)
            return result.get("topics", section_titles[:5])

        except Exception as e:
            logger.error(f"Error extracting topics: {e}")
            return section_titles[:5]  # Fallback

    def get_summary(self, db: Session, video_id: str) -> Optional[Dict[str, Any]]:
        """
        Get existing summary for a video.

        Returns:
            Dictionary with summary data or None if not found/not completed
        """
        summary = (
            db.query(VideoSummary).filter(VideoSummary.video_id == video_id).first()
        )

        if not summary or summary.processing_status != "completed":
            return None

        return {
            "overview": summary.overview_summary,
            "sections": summary.sections,
            "key_topics": summary.key_topics,
            "video_id": video_id,
        }


class QueryRouter:
    """
    Routes queries to appropriate retrieval strategy based on query type.
    Combines Phase 1 (semantic chunks) with Phase 2 (hierarchical summaries).
    """

    def __init__(self):
        self.embedder = EmbeddingService()

    def classify_query(self, query: str) -> str:
        """
        Classify query as:
        - 'broad': Overview questions (What is this about? Summarize...)
        - 'specific': Detailed questions (How does X work? At what timestamp...)
        - 'hybrid': Middle ground

        Uses simple heuristics for fast classification.
        """

        query_lower = query.lower()

        # Broad query indicators
        broad_indicators = [
            "what is this about",
            "what is this video about",
            "summarize",
            "summary",
            "overview",
            "main topic",
            "what does this cover",
            "key points",
            "in general",
            "overall",
            "explain the video",
            "what does the video",
        ]

        # Specific query indicators
        specific_indicators = [
            "how does",
            "how do",
            "why does",
            "why is",
            "explain how",
            "at what time",
            "timestamp",
            "when does",
            "when is",
            "what happens at",
            "where does",
            "who is",
            "which",
            "define",
            "what is the difference",
        ]

        broad_score = sum(1 for phrase in broad_indicators if phrase in query_lower)
        specific_score = sum(
            1 for phrase in specific_indicators if phrase in query_lower
        )

        # Check query length (broad queries tend to be shorter)
        word_count = len(query.split())

        if broad_score > specific_score or (broad_score > 0 and word_count < 8):
            return "broad"
        elif specific_score > broad_score:
            return "specific"
        else:
            # Default to hybrid for ambiguous queries
            return "hybrid"

    def build_context_from_summary(self, summary: Dict[str, Any]) -> str:
        """Build compact context from hierarchical summary."""

        context = f"Video Overview:\n{summary['overview']}\n\n"
        context += "Key Topics:\n" + ", ".join(summary["key_topics"]) + "\n\n"
        context += "Sections:\n"

        for section in summary["sections"]:
            context += f"\n[{section['start_time']} - {section['end_time']}] {section['title']}\n"
            context += f"{section['summary']}\n"

        return context

    def build_hybrid_context(
        self,
        db: Session,
        video_id: str,
        query: str,
        summary: Dict[str, Any],
        full_transcript: str,
    ) -> str:
        """
        Build context combining summary overview with semantic chunks.
        Uses embeddings to find relevant sections instead of first 1500 chars.
        """
        # Start with overview
        context = f"Video Overview: {summary['overview']}\n\n"

        # Try to get semantic chunks
        relevant_chunks = self.retrieve_relevant_chunks(db, video_id, query, top_k=3)

        if relevant_chunks:
            context += "Relevant Sections:\n\n"
            for chunk in relevant_chunks:
                timestamp_info = ""
                if chunk.get("start_time"):
                    timestamp_info = f"[{chunk['start_time']} - {chunk['end_time']}] "
                context += f"{timestamp_info}{chunk['text']}\n\n"
        else:
            # Fallback to first 1500 chars if no chunks available
            context += "Transcript Excerpt:\n"
            context += full_transcript[:1500]

        return context

    def build_semantic_context(
        self, db: Session, video_id: str, query: str, top_k: int = 5
    ) -> str:
        """
        Build context from semantically relevant chunks only.
        Used for specific queries that need precise information.
        """
        relevant_chunks = self.retrieve_relevant_chunks(
            db, video_id, query, top_k=top_k
        )

        if not relevant_chunks:
            return ""

        context = "Relevant Sections from Video:\n\n"

        for i, chunk in enumerate(relevant_chunks, 1):
            timestamp_info = ""
            if chunk.get("start_time"):
                timestamp_info = f"[{chunk['start_time']} - {chunk['end_time']}] "

            context += (
                f"{i}. {timestamp_info}(Relevance: {chunk.get('similarity', 0):.2f})\n"
            )
            context += f"{chunk['text']}\n\n"

        return context

    def retrieve_relevant_chunks(
        self, db: Session, video_id: str, query: str, top_k: int = 5, use_hybrid: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Retrieve most relevant chunks using database-level vector search with caching.

        OPTIMIZED: Uses pgvector for fast similarity search + Redis cache for repeated queries.

        Args:
            db: Database session
            video_id: Video identifier
            query: User query
            top_k: Number of chunks to retrieve
            use_hybrid: Use hybrid retrieval (dense + BM25 rerank) if True, else pure semantic

        Returns:
            List of relevant chunks with text, timestamps, and relevance scores
        """
        # Check cache first (30 min TTL)
        from utils.cache import get_cached_rag_results, cache_rag_results

        cached_results = get_cached_rag_results(video_id, f"{query}:k{top_k}:h{use_hybrid}")
        if cached_results:
            logger.info(f"Cache HIT: RAG results for video {video_id}, query '{query[:50]}...'")
            return cached_results

        logger.info(f"Cache MISS: Performing RAG retrieval for video {video_id}")

        try:
            # Generate query embedding (this is also cached)
            query_embedding = self.embedder.embed_text(query)
            logger.info(f"[DEBUG] Query embedding shape: {len(query_embedding) if query_embedding else None}")

            # Check total chunks for this video
            total_chunks = db.query(TranscriptChunk).filter(TranscriptChunk.video_id == video_id).count()
            logger.info(f"[DEBUG] Total chunks in DB for video {video_id}: {total_chunks}")

            if use_hybrid:
                # HYBRID: Get top 20 from dense search, then rerank with BM25
                # Step 1: Database-level dense retrieval using pgvector
                logger.info(f"[DEBUG] Executing pgvector cosine_distance query...")
                dense_chunks = (
                    db.query(TranscriptChunk)
                    .filter(TranscriptChunk.video_id == video_id)
                    # Skip .isnot(None) check - pgvector handles null vectors
                    .order_by(TranscriptChunk.embedding.cosine_distance(query_embedding))
                    .limit(20)  # Get top 20 for reranking
                    .all()
                )
                logger.info(f"[DEBUG] Dense chunks retrieved: {len(dense_chunks)}")

                if not dense_chunks:
                    logger.warning(f"No chunks with embeddings found for video {video_id}")
                    return []

                # Step 2: BM25 rerank (only on top 20, not all chunks)
                candidates = []
                for chunk in dense_chunks:
                    candidates.append(
                        {
                            "text": chunk.text,
                            "start_time": chunk.start_time,
                            "end_time": chunk.end_time,
                            "start_seconds": chunk.start_seconds,
                            "end_seconds": chunk.end_seconds,
                            "chunk_index": chunk.chunk_index,
                            "embedding": chunk.embedding,
                        }
                    )

                # BM25 rerank (with BM25 index caching per video)
                relevant = self.embedder.hybrid_search(
                    query, query_embedding, candidates, top_k=top_k, alpha=0.5, cache_key=f"bm25:{video_id}"
                )
                logger.info(f"Retrieved {len(relevant)} chunks (hybrid: pgvector + BM25 rerank)")

            else:
                # SEMANTIC ONLY: Pure pgvector similarity search
                semantic_chunks = (
                    db.query(TranscriptChunk)
                    .filter(TranscriptChunk.video_id == video_id)
                    # Skip .isnot(None) check - pgvector handles null vectors
                    .order_by(TranscriptChunk.embedding.cosine_distance(query_embedding))
                    .limit(top_k)
                    .all()
                )

                if not semantic_chunks:
                    logger.warning(f"No chunks with embeddings found for video {video_id}")
                    return []

                relevant = []
                for chunk in semantic_chunks:
                    relevant.append(
                        {
                            "text": chunk.text,
                            "start_time": chunk.start_time,
                            "end_time": chunk.end_time,
                            "start_seconds": chunk.start_seconds,
                            "end_seconds": chunk.end_seconds,
                            "chunk_index": chunk.chunk_index,
                            "embedding": chunk.embedding,
                        }
                    )
                logger.info(f"Retrieved {len(relevant)} chunks (pure semantic: pgvector)")

            # Cache results before returning (30 min TTL)
            cache_rag_results(video_id, f"{query}:k{top_k}:h{use_hybrid}", relevant, ttl=1800)

            return relevant

        except Exception as e:
            logger.error(f"Error retrieving chunks with pgvector: {e}")
            # Fallback: return empty list
            return []
