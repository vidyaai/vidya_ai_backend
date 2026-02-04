# research_agent.py
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from typing import List, Dict
import logging
from ..config import OPENAI_API_KEY, MODEL_NAME, TEMPERATURE
from ..prompts.agent_prompts import RESEARCH_CONTEXT_PROMPT
from ..utils.google_search import search_google

logger = logging.getLogger(__name__)


class ResearchAgent:
    """
    Agent responsible for finding relevant external resources
    """

    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=OPENAI_API_KEY, model=MODEL_NAME, temperature=TEMPERATURE
        )

    def research(self, subject: str, topics: List[str]) -> List[Dict[str, str]]:
        """
        Search for external resources based on topics

        Args:
            subject: Main subject area
            topics: List of key topics

        Returns:
            List of research results
        """
        try:
            logger.info("Research Agent: Starting web research...")

            # Create optimized search queries using LLM
            topics_str = ", ".join(topics[:3])  # Use top 3 topics only
            prompt = RESEARCH_CONTEXT_PROMPT.format(subject=subject, topics=topics_str)

            messages = [
                SystemMessage(
                    content="You are an expert at creating simple, effective search queries."
                ),
                HumanMessage(content=prompt),
            ]

            response = self.llm.invoke(messages)
            query_response = response.content.strip()

            # Parse search queries from response
            search_queries = self._parse_search_queries(query_response, subject, topics)

            # CRITICAL: Clean queries (remove quotes, trim, etc.)
            search_queries = [self._clean_query(q) for q in search_queries]

            # Print cleaned search queries to console
            print(f"\n🔍 Generated Search Queries:")
            for i, query in enumerate(search_queries, 1):
                print(f"   {i}. {query}")
            print()

            # Search using each query and combine results
            all_results = []
            for query in search_queries:
                logger.info(f"Research Agent: Searching with query: '{query}'")
                results = search_google(query, num_results=3)

                if results:
                    print(f'   âœ… Found {len(results)} results for: "{query}"')
                    all_results.extend(results)
                else:
                    print(f'   âš ï¸ No results for: "{query}"')

            # Remove duplicates based on URL
            unique_results = []
            seen_urls = set()
            for result in all_results:
                if result["url"] not in seen_urls:
                    unique_results.append(result)
                    seen_urls.add(result["url"])

            # Limit to top 6 results
            final_results = unique_results[:6]

            print(f"\n📊 Total unique results found: {len(final_results)}\n")
            logger.info(f"Research Agent: Found {len(final_results)} unique resources")
            return final_results

        except Exception as e:
            logger.error(f"Research Agent failed: {str(e)}")
            return []

    def _clean_query(self, query: str) -> str:
        """
        Clean and sanitize search query

        Removes:
        - Quotation marks
        - Excessive whitespace
        - Special characters that break search
        - Boolean operators
        """
        # Remove all types of quotes
        query = query.replace('"', "").replace("'", "").replace("`", "")

        # Remove boolean operators (they don't work well in CSE)
        query = query.replace(" OR ", " ").replace(" AND ", " ").replace(" NOT ", " ")

        # Remove parentheses
        query = query.replace("(", "").replace(")", "")

        # Collapse multiple spaces
        query = " ".join(query.split())

        # Limit length (Google CSE works better with shorter queries)
        words = query.split()
        if len(words) > 10:
            query = " ".join(words[:10])

        return query.strip()

    def _parse_search_queries(
        self, response: str, subject: str = "", topics: List[str] = None
    ) -> List[str]:
        """Parse multiple search queries from LLM response"""
        queries = []
        lines = response.split("\n")

        for line in lines:
            line = line.strip()
            # Look for QUERY1:, QUERY2:, QUERY3: patterns
            if line.startswith("QUERY1:"):
                queries.append(line.replace("QUERY1:", "").strip())
            elif line.startswith("QUERY2:"):
                queries.append(line.replace("QUERY2:", "").strip())
            elif line.startswith("QUERY3:"):
                queries.append(line.replace("QUERY3:", "").strip())
            # Also try numbered format: 1., 2., 3.
            elif line.startswith("1.") and not queries:
                queries.append(line[2:].strip())
            elif line.startswith("2.") and len(queries) == 1:
                queries.append(line[2:].strip())
            elif line.startswith("3.") and len(queries) == 2:
                queries.append(line[2:].strip())

        # Fallback: Create simple queries from subject and topics
        if not queries and subject and topics:
            main_topic = topics[0] if topics else subject
            queries = [
                f"{main_topic} tutorial",
                f"{subject} guide",
                f"{main_topic} explained",
            ]
        elif not queries:
            # Last resort fallback with very simple queries
            queries = [
                f"{subject} tutorial" if subject else "educational tutorial",
                f"{subject} guide" if subject else "learning guide",
                f"{subject} explained" if subject else "concept explained",
            ]

        # Ensure we have exactly 3 queries
        while len(queries) < 3 and topics:
            queries.append(f"{topics[len(queries) % len(topics)]} tutorial")

        return queries[:3]  # Return only first 3


def research_node(state: dict) -> dict:
    """
    LangGraph node function for Research Agent
    """
    logger.info("=== RESEARCH NODE ===")

    agent = ResearchAgent()
    subject = state.get("subject", "General")
    topics = state["key_topics"]

    if not topics:
        logger.warning("No topics found, using subject for research")
        # Even without topics, try to search using subject
        topics = [subject] if subject != "General" else ["tutorial guide"]

    results = agent.research(subject, topics)
    state["research_results"] = results

    if not results:
        logger.warning(
            "No research results found - continuing without external resources"
        )
        # Don't add to errors, just continue without research

    return state
