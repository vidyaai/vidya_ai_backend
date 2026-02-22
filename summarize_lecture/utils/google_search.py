# Tavily Web Search integration
import requests
from typing import List, Dict
import logging
from ..config import TAVILY_API_KEY

logger = logging.getLogger(__name__)


def search_google(query: str, num_results: int = 4) -> List[Dict[str, str]]:
    """
    Search web using Tavily API (optimized for AI/LLM applications)

    Args:
        query: Search query string
        num_results: Number of results to return

    Returns:
        List of dicts with 'title', 'url', 'snippet'
    """
    try:
        if not TAVILY_API_KEY:
            logger.warning("TAVILY_API_KEY not set, skipping web search")
            print(f'   ⚠️  No API key configured for: "{query}"')
            return []

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": query,
            "search_depth": "basic",
            "max_results": num_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }

        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()

        search_results = []
        for result in data.get("results", []):
            search_results.append(
                {
                    "title": result.get("title", "No title"),
                    "url": result.get("url", ""),
                    "snippet": result.get("content", "No description available"),
                }
            )

        logger.info(f'Found {len(search_results)} results for query: "{query}"')

        # Print results to console for debugging
        if search_results:
            print(f'   ✅ Found {len(search_results)} results for: "{query}"')
        else:
            print(f'   ⚠️  No results for: "{query}"')

        return search_results

    except requests.RequestException as e:
        logger.error(f"Tavily search failed for query '{query}': {str(e)}")
        print(f'   ❌ Search failed for: "{query}" - {str(e)}')
        return []
    except Exception as e:
        logger.error(f"Unexpected error in search for query '{query}': {str(e)}")
        print(f'   ❌ Search error for: "{query}" - {str(e)}')
        return []


def format_research_results(results: List[Dict[str, str]]) -> str:
    """
    Format research results for display in prompt
    """
    if not results:
        return "No external resources found."

    formatted = []
    for i, result in enumerate(results, 1):
        formatted.append(
            f"{i}. **{result['title']}**\n"
            f"   URL: {result['url']}\n"
            f"   Description: {result['snippet']}\n"
        )

    return "\n".join(formatted)
