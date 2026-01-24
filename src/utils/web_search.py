"""
Web Search Utility - Augments video answers with internet research
Supports multiple search APIs: Tavily (recommended), Serper, Google Custom Search
"""
import os
import json
import requests
from typing import List, Dict, Any, Optional
from controllers.config import logger


class WebSearchClient:
    """
    Web search client that can use different search APIs.
    Default: Tavily API (optimized for AI/LLM use cases)
    """

    def __init__(self, provider: str = "tavily"):
        """
        Initialize web search client.

        Args:
            provider: "tavily", "serper", or "google"
        """
        self.provider = provider
        self.tavily_api_key = os.getenv("TAVILY_API_KEY")
        self.serper_api_key = os.getenv("SERPER_API_KEY")
        self.google_api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
        self.google_cse_id = os.getenv("GOOGLE_CSE_ID")

    def search(
        self, query: str, max_results: int = 3, search_depth: str = "basic"
    ) -> List[Dict[str, Any]]:
        """
        Perform web search and return results.

        Args:
            query: Search query
            max_results: Maximum number of results to return (default 3)
            search_depth: "basic" or "advanced" (Tavily only)

        Returns:
            List of search results with title, url, snippet, score
        """
        if self.provider == "tavily":
            return self._search_tavily(query, max_results, search_depth)
        elif self.provider == "serper":
            return self._search_serper(query, max_results)
        elif self.provider == "google":
            return self._search_google(query, max_results)
        else:
            logger.error(f"Unknown search provider: {self.provider}")
            return []

    def _search_tavily(
        self, query: str, max_results: int, search_depth: str
    ) -> List[Dict[str, Any]]:
        """Search using Tavily API (recommended for AI applications)"""
        if not self.tavily_api_key:
            logger.warning("TAVILY_API_KEY not set, skipping web search")
            return []

        try:
            url = "https://api.tavily.com/search"
            payload = {
                "api_key": self.tavily_api_key,
                "query": query,
                "search_depth": search_depth,  # "basic" or "advanced"
                "max_results": max_results,
                "include_answer": False,  # We'll synthesize our own answer
                "include_raw_content": False,
                "include_images": False,
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()

            results = []
            for result in data.get("results", []):
                results.append(
                    {
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "snippet": result.get("content", ""),
                        "score": result.get("score", 0),
                    }
                )

            logger.info(f"Tavily search returned {len(results)} results for: {query}")
            return results

        except requests.RequestException as e:
            logger.error(f"Tavily search error: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in Tavily search: {e}")
            return []

    def _search_serper(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Search using Serper API (Google search)"""
        if not self.serper_api_key:
            logger.warning("SERPER_API_KEY not set, skipping web search")
            return []

        try:
            url = "https://google.serper.dev/search"
            headers = {"X-API-KEY": self.serper_api_key, "Content-Type": "application/json"}
            payload = {"q": query, "num": max_results}

            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()

            results = []
            for result in data.get("organic", [])[:max_results]:
                results.append(
                    {
                        "title": result.get("title", ""),
                        "url": result.get("link", ""),
                        "snippet": result.get("snippet", ""),
                        "score": 1.0,  # Serper doesn't provide scores
                    }
                )

            logger.info(f"Serper search returned {len(results)} results for: {query}")
            return results

        except requests.RequestException as e:
            logger.error(f"Serper search error: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in Serper search: {e}")
            return []

    def _search_google(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Search using Google Custom Search API"""
        if not self.google_api_key or not self.google_cse_id:
            logger.warning("Google Search API credentials not set, skipping web search")
            return []

        try:
            url = "https://www.googleapis.com/customsearch/v1"
            params = {
                "key": self.google_api_key,
                "cx": self.google_cse_id,
                "q": query,
                "num": min(max_results, 10),  # Google max is 10
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("items", [])[:max_results]:
                results.append(
                    {
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                        "score": 1.0,
                    }
                )

            logger.info(f"Google search returned {len(results)} results for: {query}")
            return results

        except requests.RequestException as e:
            logger.error(f"Google search error: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in Google search: {e}")
            return []

    def format_search_results_for_llm(self, results: List[Dict[str, Any]]) -> str:
        """
        Format search results for LLM consumption.

        Returns:
            Formatted string with search results and sources
        """
        if not results:
            return ""

        formatted = "## Additional Context from Web Search\n\n"
        for i, result in enumerate(results, 1):
            formatted += f"**Source {i}: {result['title']}**\n"
            formatted += f"{result['snippet']}\n"
            formatted += f"URL: {result['url']}\n\n"

        return formatted

    def extract_citations(self, results: List[Dict[str, Any]]) -> List[str]:
        """
        Extract citation URLs from search results.

        Returns:
            List of URLs for citation
        """
        return [result["url"] for result in results if result.get("url")]


class SearchDecisionAgent:
    """
    Intelligent agent that decides when web search is needed to augment video content.
    """

    def __init__(self, openai_client):
        """
        Initialize with OpenAI client for decision making.

        Args:
            openai_client: OpenAI client instance
        """
        self.client = openai_client

    def should_search_web(
        self,
        user_question: str,
        transcript_excerpt: str,
        video_title: str = "",
    ) -> Dict[str, Any]:
        """
        Determine if web search is needed to answer the question.

        Args:
            user_question: The student's question
            transcript_excerpt: Sample of video transcript (should be full transcript for keyword search)
            video_title: Video title

        Returns:
            dict: {
                "should_search": bool,
                "search_query": str,
                "reason": str,
                "confidence": float
            }
        """
        try:
            # CRITICAL: First check if the question's key terms appear ANYWHERE in the transcript
            # This prevents web search for topics that ARE covered in the video
            question_lower = user_question.lower()
            transcript_lower = transcript_excerpt.lower() if transcript_excerpt else ""

            # Extract key terms from the question (simple extraction)
            # Remove common question words and get meaningful terms
            stop_words = {'what', 'is', 'are', 'the', 'a', 'an', 'how', 'does', 'do', 'why', 'can', 'you', 'explain', 'tell', 'me', 'about', 'please', 'i', 'want', 'to', 'know'}
            question_words = [w.strip('?.,!') for w in question_lower.split() if w.strip('?.,!') not in stop_words and len(w.strip('?.,!')) > 2]

            # Check if key terms appear in transcript
            terms_found_in_transcript = []
            for term in question_words:
                if term in transcript_lower:
                    terms_found_in_transcript.append(term)

            # If the main topic/term is found in transcript, likely no web search needed
            if len(terms_found_in_transcript) > 0:
                # Find where in the transcript the term appears to provide better context
                main_term = question_words[0] if question_words else ""
                term_position = transcript_lower.find(main_term) if main_term else -1

                # If term is found, use context around that position
                if term_position >= 0:
                    # Extract context around where the term appears (up to 2000 chars)
                    start_pos = max(0, term_position - 500)
                    end_pos = min(len(transcript_excerpt), term_position + 1500)
                    relevant_excerpt = transcript_excerpt[start_pos:end_pos]

                    logger.info(f"Found term '{main_term}' in transcript at position {term_position}, using relevant excerpt")
                else:
                    relevant_excerpt = transcript_excerpt[:2000]
            else:
                relevant_excerpt = transcript_excerpt[:2000]

            prompt = f"""You are an AI assistant helping students learn from videos. Analyze whether web search is needed to supplement the video content.

Video title: {video_title or "Unknown"}
Video content sample: {relevant_excerpt}

Student's question: {user_question}

IMPORTANT: Terms found in transcript: {terms_found_in_transcript if terms_found_in_transcript else 'None detected'}

Determine if the video content alone is sufficient to answer the question, or if additional web search would help provide:
1. More detailed explanations
2. Related concepts not in the video
3. Up-to-date information
4. Broader context
5. Alternative perspectives

Respond with a JSON object:
{{
  "should_search": true/false,
  "search_query": "optimized search query (if should_search is true, empty otherwise)",
  "reason": "brief explanation",
  "confidence": 0.0-1.0
}}

CRITICAL Guidelines:
- **If the question terms are found in the transcript, the video likely covers it - set should_search = false**
- If the video FULLY covers the topic: should_search = false
- If question asks about related concepts CLEARLY not in video: should_search = true
- If question needs VERY current/external info: should_search = true
- Be CONSERVATIVE about web search - prefer video content first
- Keep search_query concise and specific"""

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that determines when web search would enhance learning. Be conservative - prefer using video content when the topic is covered in the video.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=200,
                temperature=0.3,
            )

            result = json.loads(response.choices[0].message.content)

            # Override: If key terms are clearly in transcript, don't search
            if len(terms_found_in_transcript) >= 2 and result.get("should_search"):
                logger.info(f"Overriding search decision: terms {terms_found_in_transcript} found in transcript")
                result["should_search"] = False
                result["reason"] = f"Topic terms ({', '.join(terms_found_in_transcript)}) found in video transcript"
                result["confidence"] = 0.3  # Low confidence in search decision

            logger.info(
                f"Search decision: {result.get('should_search')} - {result.get('reason')}"
            )
            return result

        except Exception as e:
            logger.error(f"Error in search decision: {e}")
            # Default to not searching on error
            return {
                "should_search": False,
                "search_query": "",
                "reason": "Error in decision making",
                "confidence": 0.0,
            }

    def generate_search_query(self, user_question: str, video_topic: str = "") -> str:
        """
        Generate an optimized search query from the user's question.

        Args:
            user_question: The student's question
            video_topic: The video's main topic

        Returns:
            Optimized search query string
        """
        # Simple query optimization
        query = user_question.strip()

        # Remove question words for better search results
        question_words = ["what is", "how does", "why is", "can you explain", "tell me about"]
        for word in question_words:
            query = query.lower().replace(word, "").strip()

        # Add video topic context if available
        if video_topic:
            query = f"{query} {video_topic}"

        return query[:100]  # Limit length


def synthesize_with_web_results(
    openai_client,
    user_question: str,
    video_content: str,
    search_results: List[Dict[str, Any]],
    conversation_history: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """
    Synthesize answer combining video content and web search results.

    Args:
        openai_client: OpenAI client
        user_question: Student's question
        video_content: Transcript or video context
        search_results: Web search results
        conversation_history: Previous conversation

    Returns:
        dict: {
            "answer": str,
            "sources": List[str],
            "used_web_search": bool
        }
    """
    try:
        # Format search results
        web_context = WebSearchClient().format_search_results_for_llm(search_results)

        # Import system prompts
        from .system_prompt import SYSTEM_PROMPT_CONVERSATIONAL_FORMATTED

        # Find relevant sections of transcript based on question
        # Search for key terms in the question within the transcript
        question_lower = user_question.lower()
        stop_words = {'what', 'is', 'are', 'the', 'a', 'an', 'how', 'does', 'do', 'why', 'can', 'you', 'explain', 'tell', 'me', 'about'}
        question_terms = [w.strip('?.,!') for w in question_lower.split() if w.strip('?.,!') not in stop_words and len(w.strip('?.,!')) > 2]

        # Try to find relevant section of transcript
        video_content_lower = video_content.lower() if video_content else ""
        relevant_video_content = video_content

        if question_terms and video_content_lower:
            # Find position of first matching term
            for term in question_terms:
                pos = video_content_lower.find(term)
                if pos >= 0:
                    # Extract a larger context around where the term is found
                    start = max(0, pos - 1000)
                    end = min(len(video_content), pos + 4000)
                    relevant_video_content = video_content[start:end]
                    logger.info(f"Found term '{term}' at position {pos}, using context from {start} to {end}")
                    break

        # Use more transcript content (up to 5000 chars for better context)
        video_excerpt = relevant_video_content[:5000] if len(relevant_video_content) > 5000 else relevant_video_content

        # Build enhanced prompt
        enhanced_prompt = f"""Answer the student's question using BOTH the video content and additional web sources.

**Video Content (SEARCH THIS CAREFULLY FOR TIMESTAMPS):**
{video_excerpt}

{web_context}

**Student's Question:** {user_question}

**CRITICAL Instructions:**

1. **PRIORITY: Video Content First** - If the concept is explained in the video, use THAT explanation primarily
2. **SEARCH THE ENTIRE VIDEO CONTENT** above for where the topic is discussed
3. **TIMESTAMP EXTRACTION (VERY IMPORTANT):**
   - Timestamps in the video content appear as "MM:SS - MM:SS" at the start of each segment
   - When you find where the concept is explained, cite THAT timestamp
   - Format timestamps as $MM:SS$ in your answer
   - Example: If you see "10:57 - 11:12" before the explanation, cite $10:57$
   - NEVER just cite $00:00$ - find the ACTUAL timestamp where the concept appears
4. **Web Sources** - Only supplement with web sources if video doesn't cover it adequately
   - If web results seem unrelated (e.g., different topic with same name), IGNORE them
5. **Citations at End:**

**Sources:**
- Video: $MM:SS$, $MM:SS$ (list ALL relevant timestamps)
- [Web Source Title](URL) (only if actually used)

**Common Mistakes to Avoid:**
- ❌ Citing $00:00$ when concept is actually at $10:57$
- ❌ Saying "video doesn't explain" when it does (just later in transcript)
- ❌ Using unrelated web results that happen to share the same term name
"""

        messages = [{"role": "system", "content": SYSTEM_PROMPT_CONVERSATIONAL_FORMATTED}]

        # Add conversation history (increased to 10 messages for better memory)
        if conversation_history:
            for msg in conversation_history[-10:]:  # Last 10 messages for context (5 Q&A pairs)
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    messages.append({"role": msg["role"], "content": msg["content"]})

        # Add current question
        messages.append({"role": "user", "content": enhanced_prompt})

        response = openai_client.chat.completions.create(
            model="gpt-4o",  # Use GPT-4o for better synthesis
            messages=messages,
            max_tokens=1200,
            temperature=0.4,
        )

        answer = response.choices[0].message.content

        # Extract citation URLs as markdown links (clickable)
        citations = [f"[{r['title']}]({r['url']})"
                    for r in search_results]

        return {
            "answer": answer,
            "sources": citations,
            "used_web_search": True,
        }

    except Exception as e:
        logger.error(f"Error synthesizing with web results: {e}")
        # Return without web enhancement on error
        return {
            "answer": f"Error synthesizing answer: {str(e)}",
            "sources": [],
            "used_web_search": False,
        }
