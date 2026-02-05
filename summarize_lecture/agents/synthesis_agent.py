# Summary creation agent
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
import logging
from ..config import OPENAI_API_KEY, MODEL_NAME, TEMPERATURE
from ..prompts.agent_prompts import SYNTHESIS_PROMPT
from ..utils.google_search import format_research_results

logger = logging.getLogger(__name__)


class SynthesisAgent:
    """
    Agent responsible for creating the final markdown summary
    """

    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=OPENAI_API_KEY, model=MODEL_NAME, temperature=TEMPERATURE
        )

    def synthesize(self, transcript: str, research_results: list) -> str:
        """
        Create comprehensive markdown summary

        Args:
            transcript: Video transcript
            research_results: List of external resources

        Returns:
            Markdown formatted summary
        """
        try:
            logger.info("Synthesis Agent: Creating summary...")

            # Format research results
            research_formatted = format_research_results(research_results)

            # Create prompt
            prompt = SYNTHESIS_PROMPT.format(
                transcript=transcript[:4000],  # Limit length
                research_results=research_formatted,
            )

            messages = [
                SystemMessage(content="You are an expert educational content writer."),
                HumanMessage(content=prompt),
            ]

            response = self.llm.invoke(messages)
            summary = response.content.strip()

            logger.info("Synthesis Agent: Summary created successfully")
            return summary

        except Exception as e:
            logger.error(f"Synthesis Agent failed: {str(e)}")
            return f"# Error\n\nFailed to generate summary: {str(e)}"


def synthesis_node(state: dict) -> dict:
    """
    LangGraph node function for Synthesis Agent
    """
    logger.info("=== SYNTHESIS NODE ===")

    agent = SynthesisAgent()
    summary = agent.synthesize(state["transcript"], state["research_results"])

    state["summary_markdown"] = summary

    return state
