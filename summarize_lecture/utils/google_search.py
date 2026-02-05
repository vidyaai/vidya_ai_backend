# Google CSE integration
from googleapiclient.discovery import build
from typing import List, Dict
import logging
from ..config import GOOGLE_CSE_API_KEY, GOOGLE_CSE_ID

logger = logging.getLogger(__name__)


def search_google(query: str, num_results: int = 4) -> List[Dict[str, str]]:
    """
    Search Google using Custom Search API

    Args:
        query: Search query string
        num_results: Number of results to return (max 10)

    Returns:
        List of dicts with 'title', 'url', 'snippet'
    """
    try:
        service = build("customsearch", "v1", developerKey=GOOGLE_CSE_API_KEY)

        result = (
            service.cse().list(q=query, cx=GOOGLE_CSE_ID, num=num_results).execute()
        )

        search_results = []

        if "items" in result:
            for item in result["items"]:
                search_results.append(
                    {
                        "title": item.get("title", "No title"),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", "No description available"),
                    }
                )
        else:
            logger.warning(f"No search results found for query: {query}")

        logger.info(f'Found {len(search_results)} results for query: "{query}"')

        # Print results to console for debugging
        if search_results:
            print(f'   ✅ Found {len(search_results)} results for: "{query}"')
        else:
            print(f'   ❌ No results for: "{query}"')

        return search_results

    except Exception as e:
        logger.error(f"Google search failed for query '{query}': {str(e)}")
        print(f'   ❌ Search failed for: "{query}" - {str(e)}')
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
