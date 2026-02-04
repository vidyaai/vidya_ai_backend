# Topic extraction agent
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from typing import List
import logging
from ..config import OPENAI_API_KEY, MODEL_NAME, TEMPERATURE
from ..prompts.agent_prompts import ANALYZER_PROMPT

logger = logging.getLogger(__name__)


class AnalyzerAgent:
    """
    Agent responsible for analyzing transcript and extracting key topics
    """

    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=OPENAI_API_KEY, model=MODEL_NAME, temperature=TEMPERATURE
        )

    def analyze(self, transcript: str) -> tuple[str, List[str]]:
        """
        Analyze transcript and extract key topics

        Args:
            transcript: Video transcript text

        Returns:
            Tuple of (subject, list of topics)
        """
        try:
            logger.info("Analyzer Agent: Starting transcript analysis...")

            prompt = ANALYZER_PROMPT.format(
                transcript=transcript[:3000]
            )  # Limit length

            messages = [
                SystemMessage(content="You are an expert content analyzer."),
                HumanMessage(content=prompt),
            ]

            response = self.llm.invoke(messages)
            content = response.content

            # Parse response
            subject = "General"
            topics = []

            lines = content.strip().split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("SUBJECT:"):
                    subject = line.replace("SUBJECT:", "").strip()
                elif line.startswith("-"):
                    topic = line.lstrip("- ").strip()
                    if topic:
                        topics.append(topic)

            logger.info(
                f"Analyzer Agent: Found subject '{subject}' with {len(topics)} topics"
            )
            return subject, topics

        except Exception as e:
            logger.error(f"Analyzer Agent failed: {str(e)}")
            return "General", []


def analyzer_node(state: dict) -> dict:
    """
    LangGraph node function for Analyzer Agent
    """
    logger.info("=== ANALYZER NODE ===")

    agent = AnalyzerAgent()
    subject, topics = agent.analyze(state["transcript"])

    state["key_topics"] = topics
    state["subject"] = subject

    if not topics:
        state["errors"].append("Failed to extract topics from transcript")

    return state
