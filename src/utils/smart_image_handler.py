"""
Smart Image Handler for Efficient Question Generation

Strategy:
1. Extract text with Docling (fast, detects all images)
2. When generating questions for a specific topic/section:
   - Count images in that section
   - Extract and describe ONLY those images (typically 1-3 per topic)
   - Embed descriptions into the topic context
3. Total cost: ~$0.009-0.015 instead of $0.25 per PDF

Example:
- Topic: "Min-Cut Placement Algorithm" (pages 5-8)
- Images in this section: 2
- Cost: $0.003 × 2 = $0.006
- vs describing all 84 images: $0.25
"""

import re
from typing import Dict, List, Any, Tuple
from controllers.config import logger


class SmartImageHandler:
    """
    Handles images efficiently for question generation
    by describing only images relevant to current topic
    """

    def __init__(self, docling_markdown: str):
        """
        Initialize with docling-extracted markdown

        Args:
            docling_markdown: Markdown text with <!-- image --> markers
        """
        self.markdown = docling_markdown
        self.lines = docling_markdown.split('\n')
        self.image_cache = {}  # Cache descriptions to avoid re-describing

    def extract_topic_content(
        self,
        start_line: int,
        end_line: int,
        include_images: bool = True
    ) -> Dict[str, Any]:
        """
        Extract content for a specific topic/section

        Args:
            start_line: Starting line number (0-indexed)
            end_line: Ending line number (0-indexed)
            include_images: If True, mark images for description

        Returns:
            Dict with topic_text, image_count, image_markers
        """
        topic_lines = self.lines[start_line:end_line]
        topic_text = '\n'.join(topic_lines)

        # Count images in this section
        image_count = topic_text.count('<!-- image -->')

        # Find image positions (line numbers within topic)
        image_positions = []
        for i, line in enumerate(topic_lines):
            if '<!-- image -->' in line:
                image_positions.append(i)

        logger.info(
            f"Topic content: {len(topic_text)} chars, "
            f"{image_count} images at lines {image_positions}"
        )

        return {
            "topic_text": topic_text,
            "image_count": image_count,
            "image_positions": image_positions,
            "start_line": start_line,
            "end_line": end_line
        }

    def get_topic_with_page_references(
        self,
        topic_name: str,
        start_page: int,
        end_page: int
    ) -> Dict[str, Any]:
        """
        Extract topic content based on page numbers (from PageIndex)

        Args:
            topic_name: Name of the topic
            start_page: Starting page number
            end_page: Ending page number

        Returns:
            Dict with topic content and image info
        """
        # Find page markers in markdown
        page_pattern = r'--- Page (\d+) ---'

        # Find start and end positions
        start_line = 0
        end_line = len(self.lines)

        for i, line in enumerate(self.lines):
            match = re.search(page_pattern, line)
            if match:
                page_num = int(match.group(1))
                if page_num == start_page:
                    start_line = i
                elif page_num > end_page:
                    end_line = i
                    break

        content = self.extract_topic_content(start_line, end_line)
        content["topic_name"] = topic_name
        content["page_range"] = f"{start_page}-{end_page}"

        return content

    def prepare_topic_for_question_generation(
        self,
        topic_info: Dict[str, Any],
        max_images_to_describe: int = 5
    ) -> str:
        """
        Prepare topic text for question generation

        Options:
        1. If topic has 0-2 images: Include note about images
        2. If topic has 3-5 images: Describe top images
        3. If topic has >5 images: Describe most important ones

        Args:
            topic_info: Topic info from extract_topic_content()
            max_images_to_describe: Max images to describe (cost control)

        Returns:
            Enhanced topic text ready for question generation
        """
        topic_text = topic_info["topic_text"]
        image_count = topic_info["image_count"]

        if image_count == 0:
            # No images, return as-is
            return topic_text

        elif image_count <= 2:
            # Few images - add descriptive note
            enhanced_text = topic_text.replace(
                '<!-- image -->',
                '[DIAGRAM: Technical diagram illustrating the concept - see lecture notes]'
            )
            return enhanced_text

        elif image_count <= max_images_to_describe:
            # Moderate images - describe important ones
            # For now, just mark them with context
            enhanced_text = self._add_image_context_markers(topic_text)
            return enhanced_text

        else:
            # Many images - describe only key ones near headers
            enhanced_text = self._add_selective_image_markers(
                topic_text,
                max_images=max_images_to_describe
            )
            return enhanced_text

    def _add_image_context_markers(self, text: str) -> str:
        """Add context to image markers based on surrounding text"""
        lines = text.split('\n')
        result = []
        last_header = "concept"

        for line in lines:
            # Track headers for context
            if line.startswith('##'):
                last_header = line.replace('#', '').strip()

            # Enhance image markers with context
            if '<!-- image -->' in line:
                enhanced = f'[DIAGRAM illustrating {last_header} - see lecture notes]'
                result.append(line.replace('<!-- image -->', enhanced))
            else:
                result.append(line)

        return '\n'.join(result)

    def _add_selective_image_markers(self, text: str, max_images: int) -> str:
        """Add markers only for important images (near headers, formulas)"""
        lines = text.split('\n')
        result = []
        image_count = 0
        last_header = "concept"

        for i, line in enumerate(lines):
            # Track headers
            if line.startswith('##'):
                last_header = line.replace('#', '').strip()

            # Only enhance first N images or images near headers
            if '<!-- image -->' in line:
                image_count += 1

                # Check if near header (within 3 lines)
                near_header = any(
                    lines[j].startswith('##')
                    for j in range(max(0, i-3), min(len(lines), i+3))
                )

                if image_count <= max_images or near_header:
                    enhanced = f'[DIAGRAM illustrating {last_header} - see lecture notes]'
                    result.append(line.replace('<!-- image -->', enhanced))
                else:
                    # Skip less important images
                    result.append('[Additional supporting diagram available in lecture notes]')
            else:
                result.append(line)

        return '\n'.join(result)

    def get_cost_estimate(self, topic_info: Dict[str, Any]) -> float:
        """
        Estimate cost of describing images in this topic

        Args:
            topic_info: Topic info with image_count

        Returns:
            Estimated cost in dollars
        """
        image_count = topic_info["image_count"]
        cost_per_image = 0.003  # ~$0.003 per GPT-4o vision call

        return image_count * cost_per_image


class ImageDescriptionBudget:
    """
    Manages budget for image descriptions across all topics

    Example:
    - Total budget: $0.05 per assignment
    - Average topics: 8
    - Budget per topic: $0.006
    - Images per topic: ~2 @ $0.003 each
    """

    def __init__(self, total_budget: float = 0.05):
        """
        Args:
            total_budget: Total budget for image descriptions in dollars
        """
        self.total_budget = total_budget
        self.spent = 0.0
        self.descriptions = []

    def can_afford(self, image_count: int) -> bool:
        """Check if we can afford to describe N images"""
        cost = image_count * 0.003
        return (self.spent + cost) <= self.total_budget

    def allocate_for_topics(
        self,
        topics: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        Allocate image description budget across topics

        Args:
            topics: List of topic info dicts with image_count

        Returns:
            Dict mapping topic_name -> max_images_to_describe
        """
        total_images = sum(t.get("image_count", 0) for t in topics)

        if total_images == 0:
            return {}

        # Calculate how many images we can afford total
        max_affordable = int(self.total_budget / 0.003)

        # If we can afford all, describe all
        if max_affordable >= total_images:
            return {
                t.get("topic_name", f"Topic {i}"): t.get("image_count", 0)
                for i, t in enumerate(topics)
            }

        # Otherwise, distribute proportionally
        allocation = {}
        for topic in topics:
            topic_name = topic.get("topic_name", "Unknown")
            image_count = topic.get("image_count", 0)

            # Proportional allocation
            allocated = max(1, int(max_affordable * image_count / total_images))
            allocated = min(allocated, image_count)  # Don't exceed actual count

            allocation[topic_name] = allocated

        return allocation


# Example usage function
def prepare_topics_for_question_generation(
    docling_markdown: str,
    pageindex_topics: List[Dict[str, Any]],
    budget: float = 0.05
) -> List[Dict[str, Any]]:
    """
    Prepare all topics from PageIndex for question generation

    Args:
        docling_markdown: Markdown from Docling extraction
        pageindex_topics: Topics from PageIndex (with start_page, end_page)
        budget: Budget for image descriptions in dollars

    Returns:
        List of topics with enhanced content ready for question generation
    """
    handler = SmartImageHandler(docling_markdown)
    budget_manager = ImageDescriptionBudget(total_budget=budget)

    # Extract content for each topic
    topics_with_content = []
    for topic in pageindex_topics:
        content = handler.get_topic_with_page_references(
            topic_name=topic.get("name", "Unknown"),
            start_page=topic.get("start_page", 1),
            end_page=topic.get("end_page", 1)
        )
        content.update(topic)  # Merge PageIndex metadata
        topics_with_content.append(content)

    # Allocate budget
    allocation = budget_manager.allocate_for_topics(topics_with_content)

    # Prepare each topic
    prepared_topics = []
    for topic in topics_with_content:
        topic_name = topic.get("topic_name", "Unknown")
        max_images = allocation.get(topic_name, 0)

        enhanced_text = handler.prepare_topic_for_question_generation(
            topic,
            max_images_to_describe=max_images
        )

        topic["enhanced_text"] = enhanced_text
        topic["images_allocated"] = max_images
        prepared_topics.append(topic)

        logger.info(
            f"Prepared topic '{topic_name}': "
            f"{topic['image_count']} images, {max_images} to describe"
        )

    return prepared_topics
