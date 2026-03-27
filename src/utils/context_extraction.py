"""
Context Extraction Utilities
Fallback mechanisms for when RAG chunks aren't ready yet.
"""

import tiktoken
from typing import List
from controllers.config import logger


def extract_relevant_context(
    transcript: str, question: str, max_tokens: int = 3000, model: str = "gpt-4o-mini"
) -> str:
    """
    Fallback: Extract relevant section from transcript using keyword matching.
    Used when chunks aren't ready yet (progressive enhancement).

    Args:
        transcript: Full transcript text
        question: User's question
        max_tokens: Maximum tokens to return
        model: Model name for token counting

    Returns:
        Relevant excerpt from transcript
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")  # Fallback encoding

    # Extract keywords from question
    question_lower = question.lower()
    stop_words = {
        "what",
        "is",
        "how",
        "does",
        "why",
        "can",
        "the",
        "a",
        "an",
        "this",
        "that",
        "these",
        "those",
        "it",
        "be",
        "to",
        "of",
        "in",
        "for",
        "on",
        "at",
        "by",
        "with",
        "from",
        "about",
        "as",
        "into",
        "like",
        "through",
        "after",
        "over",
        "between",
        "out",
        "against",
        "during",
        "without",
        "before",
        "under",
        "around",
        "among",
    }
    keywords = [
        word
        for word in question_lower.split()
        if word not in stop_words and len(word) > 2
    ]

    if not keywords:
        # No meaningful keywords, return smart sample
        logger.warning("No keywords found, using smart sampling")
        return smart_sample_transcript(transcript, max_tokens, encoding)

    # Find first matching keyword
    transcript_lower = transcript.lower()
    for keyword in keywords:
        pos = transcript_lower.find(keyword)
        if pos >= 0:
            # Extract context around keyword (2K chars before, 8K chars after)
            start = max(0, pos - 4000)
            end = min(len(transcript), pos + 16000)
            relevant_text = transcript[start:end]

            # Truncate to max_tokens
            tokens = encoding.encode(relevant_text)
            if len(tokens) > max_tokens:
                relevant_text = encoding.decode(tokens[:max_tokens])

            logger.info(
                f"Fallback: Found '{keyword}' at pos {pos}, extracted {len(relevant_text)} chars ({len(tokens)} tokens)"
            )
            return relevant_text

    # No keywords found in transcript
    logger.warning("Keywords not found in transcript, using smart sampling")
    return smart_sample_transcript(transcript, max_tokens, encoding)


def smart_sample_transcript(
    transcript: str, max_tokens: int, encoding: tiktoken.Encoding = None
) -> str:
    """
    Sample from beginning (skip intro), middle, and end.
    Better than first N chars for relevance checking.

    Args:
        transcript: Full transcript
        max_tokens: Maximum tokens to return
        encoding: Tiktoken encoding (optional)

    Returns:
        Sampled transcript
    """
    if encoding is None:
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
        except:
            # Fallback: simple character-based estimation
            return transcript[: max_tokens * 4]  # Rough: 1 token ≈ 4 chars

    length = len(transcript)
    samples = []

    # Skip first 10% (often intros/ads), take next 10%
    samples.append(transcript[int(length * 0.1) : int(length * 0.2)])

    # Middle 40-50%
    samples.append(transcript[int(length * 0.4) : int(length * 0.5)])

    # Last 10% (often conclusion/summary)
    samples.append(transcript[int(length * 0.9) :])

    combined = "\n[...]\n".join(samples)
    tokens = encoding.encode(combined)

    if len(tokens) <= max_tokens:
        return combined

    return encoding.decode(tokens[:max_tokens])


def truncate_to_token_limit(
    context: str, max_tokens: int = 3000, model: str = "gpt-4o-mini"
) -> str:
    """
    Ensure context doesn't exceed token limit.

    Args:
        context: Input context
        max_tokens: Maximum allowed tokens
        model: Model name for token counting

    Returns:
        Truncated context
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")

    tokens = encoding.encode(context)

    if len(tokens) <= max_tokens:
        return context

    # Truncate and add marker
    truncated = encoding.decode(tokens[:max_tokens])
    return truncated + "\n\n[Content truncated to fit context window...]"
