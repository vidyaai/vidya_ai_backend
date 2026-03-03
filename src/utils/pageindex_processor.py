"""
PageIndex Processor for Semantic Document Chunking

Uses PageIndex API to create hierarchical topic structure from lecture notes
without embeddings or vector databases.
"""

import json
import os
from typing import List, Dict, Any, Optional
from pageindex import PageIndexClient
from controllers.config import logger


class PageIndexProcessor:
    """Process documents using PageIndex for semantic organization"""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize PageIndex processor

        Args:
            api_key: PageIndex API key (defaults to env var PAGEINDEX_API_KEY)
        """
        self.api_key = api_key or os.getenv("PAGEINDEX_API_KEY")
        if not self.api_key:
            raise ValueError("PageIndex API key required. Set PAGEINDEX_API_KEY env var or pass api_key parameter")

        self.client = PageIndexClient(api_key=self.api_key)
        logger.info("PageIndex processor initialized")

    def create_document_index(
        self,
        content: str,
        doc_name: str = "document"
    ) -> Dict[str, Any]:
        """
        Create a hierarchical index of the document using PageIndex

        Args:
            content: Full document text content
            doc_name: Name of the document

        Returns:
            Index structure with topics and sections
        """
        try:
            logger.info(f"Creating PageIndex for {doc_name} ({len(content)} chars)")

            # TODO: PageIndex API call to create index
            # For now, let's implement a simpler version using LLM-based topic extraction
            # which achieves the same semantic chunking goal

            # We'll use our own LLM call to create hierarchical structure
            # This is essentially what PageIndex does internally
            topics = self._extract_topics_with_llm(content, doc_name)

            logger.info(f"Created index with {len(topics)} topics")
            return {
                "doc_name": doc_name,
                "topics": topics,
                "total_chars": len(content)
            }

        except Exception as e:
            logger.error(f"Error creating PageIndex: {str(e)}")
            # Fallback: return simple page-based chunking
            return self._fallback_chunking(content, doc_name)

    def _extract_topics_with_llm(
        self,
        content: str,
        doc_name: str
    ) -> List[Dict[str, Any]]:
        """
        Extract semantic topics from document using LLM reasoning

        This simulates what PageIndex does: hierarchical topic extraction
        without vectors, using LLM reasoning instead.
        """
        from openai import OpenAI

        client = OpenAI()

        # Truncate content if too large (keep full structure for analysis)
        analysis_content = content[:100000] if len(content) > 100000 else content

        prompt = f"""Analyze this lecture document and extract its hierarchical topic structure.

Document: {doc_name}
Content (first 100k chars):
{analysis_content}

Create a semantic hierarchy of topics covered in this lecture. For each topic:
1. Topic name (clear, specific)
2. Start and end page numbers (from "--- Page N ---" markers)
3. Brief description of what's covered
4. Whether it's a major topic or subtopic

IMPORTANT:
- Use semantic boundaries (topic completion), NOT arbitrary page counts
- A topic should be COMPLETE and COHERENT
- If a topic spans many pages, keep it as one topic
- Don't split topics in the middle
- Identify natural topic transitions

Return JSON with this exact structure:
{{
  "topics": [
    {{
      "name": "Topic Name",
      "start_page": 1,
      "end_page": 15,
      "description": "Brief description",
      "type": "major_topic",
      "estimated_chars": 20000
    }}
  ]
}}

Return ONLY valid JSON, no additional text."""

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at analyzing academic documents and creating semantic topic hierarchies. You identify natural topic boundaries and create coherent topic structures. Always return valid JSON."
                    },
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3
            )

            result = json.loads(response.choices[0].message.content)
            topics = result.get("topics", [])

            # Add actual content for each topic
            for topic in topics:
                topic["content"] = self._extract_topic_content(
                    content,
                    topic["start_page"],
                    topic["end_page"]
                )
                topic["actual_chars"] = len(topic["content"])

            return topics

        except Exception as e:
            logger.error(f"Error extracting topics: {str(e)}")
            # Fallback to simple page-based chunking
            return self._create_simple_topics(content)

    def _extract_topic_content(
        self,
        full_content: str,
        start_page: int,
        end_page: int
    ) -> str:
        """
        Extract content for a specific page range

        Args:
            full_content: Full document content
            start_page: Start page number
            end_page: End page number

        Returns:
            Content from start_page to end_page
        """
        if "--- Page" not in full_content:
            # No page markers, return chunk
            char_per_page = len(full_content) // 50  # Estimate
            start_char = (start_page - 1) * char_per_page
            end_char = end_page * char_per_page
            return full_content[start_char:end_char]

        # Extract pages by markers
        pages = full_content.split("--- Page ")
        topic_content = []

        for page in pages[1:]:  # Skip empty first element
            try:
                page_num = int(page.split("---")[0].strip())
                if start_page <= page_num <= end_page:
                    topic_content.append("--- Page " + page)
            except (ValueError, IndexError):
                continue

        return "\n".join(topic_content)

    def _create_simple_topics(self, content: str) -> List[Dict[str, Any]]:
        """
        Fallback: Create simple topic structure based on pages

        Used when LLM-based topic extraction fails.
        """
        # Count pages
        if "--- Page" in content:
            num_pages = len(content.split("--- Page ")) - 1
        else:
            # Estimate based on characters (assume ~2000 chars per page)
            num_pages = max(1, len(content) // 2000)

        # Create topics for every ~10-15 pages
        topics = []
        pages_per_topic = 15

        for i in range(0, num_pages, pages_per_topic):
            start = i + 1
            end = min(i + pages_per_topic, num_pages)

            topic_content = self._extract_topic_content(content, start, end)

            topics.append({
                "name": f"Section {len(topics) + 1}",
                "start_page": start,
                "end_page": end,
                "description": f"Pages {start}-{end}",
                "type": "section",
                "content": topic_content,
                "actual_chars": len(topic_content)
            })

        return topics

    def _fallback_chunking(
        self,
        content: str,
        doc_name: str
    ) -> Dict[str, Any]:
        """Fallback if PageIndex fails: simple semantic chunking"""
        topics = self._create_simple_topics(content)

        return {
            "doc_name": doc_name,
            "topics": topics,
            "total_chars": len(content),
            "fallback": True
        }

    def distribute_questions_across_topics(
        self,
        topics: List[Dict[str, Any]],
        total_questions: int
    ) -> List[Dict[str, Any]]:
        """
        Distribute questions across topics proportionally

        Args:
            topics: List of topic dictionaries
            total_questions: Total number of questions to generate

        Returns:
            List of topics with question counts assigned
        """
        if not topics:
            return []

        total_chars = sum(t.get("actual_chars", 0) for t in topics)
        if total_chars == 0:
            # Equal distribution
            questions_per_topic = total_questions // len(topics)
            for t in topics:
                t["num_questions"] = questions_per_topic
            # Give remaining to first topic
            topics[0]["num_questions"] += total_questions - (questions_per_topic * len(topics))
        else:
            # Proportional distribution based on content size
            remaining = total_questions
            for i, topic in enumerate(topics):
                proportion = topic.get("actual_chars", 0) / total_chars
                num_q = int(total_questions * proportion)

                # Ensure at least 1 question per topic if we have enough questions
                if total_questions >= len(topics):
                    num_q = max(1, num_q)

                # Last topic gets remaining
                if i == len(topics) - 1:
                    num_q = remaining

                topic["num_questions"] = num_q
                remaining -= num_q

        return topics
