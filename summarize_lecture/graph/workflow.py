# LangGraph workflow
from langgraph.graph import StateGraph, END
from .state import SummaryState
from ..agents.analyzer_agent import analyzer_node
from ..agents.research_agent import research_node
from ..agents.synthesis_agent import synthesis_node
import logging

logger = logging.getLogger(__name__)


def create_summary_workflow():
    """
    Create and compile the LangGraph workflow
    """
    # Create graph
    workflow = StateGraph(SummaryState)

    # Add nodes
    workflow.add_node("analyzer", analyzer_node)
    workflow.add_node("research", research_node)
    workflow.add_node("synthesis", synthesis_node)

    # Define edges
    workflow.set_entry_point("analyzer")
    workflow.add_edge("analyzer", "research")
    workflow.add_edge("research", "synthesis")
    workflow.add_edge("synthesis", END)

    # Compile graph
    app = workflow.compile()

    logger.info("Workflow created successfully")
    return app


def run_summarization(video_id: str, transcript: str) -> dict:
    """
    Run the complete summarization workflow

    Args:
        video_id: Unique identifier for the video
        transcript: Video transcript text

    Returns:
        Final state with summary
    """
    logger.info(f"Starting summarization for video: {video_id}")

    # Initialize state
    initial_state = {
        "video_id": video_id,
        "transcript": transcript,
        "key_topics": [],
        "research_results": [],
        "summary_markdown": "",
        "errors": [],
    }

    # Create and run workflow
    app = create_summary_workflow()

    try:
        # Run the graph
        final_state = app.invoke(initial_state)

        logger.info("Summarization completed successfully")
        return final_state

    except Exception as e:
        logger.error(f"Workflow execution failed: {str(e)}")
        initial_state["errors"].append(f"Workflow failed: {str(e)}")
        return initial_state
