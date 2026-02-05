# State schema definition
from typing import TypedDict, List, Dict, Any


class SummaryState(TypedDict):
    """
    State schema for the video summarization workflow.
    This state is passed between all agents in the graph.
    """

    # Input
    video_id: str
    transcript: str

    # Intermediate results
    key_topics: List[str]
    research_results: List[Dict[str, str]]

    # Output
    summary_markdown: str

    # Error handling
    errors: List[str]
