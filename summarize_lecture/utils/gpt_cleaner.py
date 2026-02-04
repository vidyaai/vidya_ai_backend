import logging
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_TEMPERATURE

logger = logging.getLogger(__name__)

# System prompt for transcript cleanup
CLEANUP_PROMPT = """You are an expert transcript editor specializing in cleaning and formatting video transcripts.

Your task is to:
1. Remove any timestamps, time markers, or metadata (e.g., "[00:05]", "0:32", etc.)
2. Fix grammar and add proper punctuation
3. Add paragraph breaks where natural topic shifts occur
4. Fix capitalization
5. Remove filler words (um, uh, like) only if excessive
6. Keep the original meaning and words intact - DO NOT paraphrase or summarize
7. Maintain the speaker's voice and style
8. Add paragraph breaks every 3-5 sentences or when topic changes
9. DO NOT add any commentary, headers, or your own text

Output only the cleaned transcript text with proper formatting.
"""


def clean_transcript_with_gpt(raw_transcript: str) -> str:
    """
    Clean and format transcript using GPT-4o

    Args:
        raw_transcript: Raw transcript from Deepgram

    Returns:
        Cleaned and formatted transcript
    """
    try:
        logger.info("Starting GPT-4o transcript cleanup...")
        logger.info(f"Input length: {len(raw_transcript)} characters")

        # Initialize OpenAI client
        client = OpenAI(api_key=OPENAI_API_KEY)

        # If transcript is very long, process in chunks
        max_chunk_size = 12000  # characters (to stay under token limit)

        if len(raw_transcript) > max_chunk_size:
            logger.info(
                f"Transcript is long ({len(raw_transcript)} chars), processing in chunks..."
            )
            cleaned_chunks = []

            # Split into sentences for better chunking
            sentences = raw_transcript.split(". ")
            current_chunk = ""

            for sentence in sentences:
                if len(current_chunk) + len(sentence) < max_chunk_size:
                    current_chunk += sentence + ". "
                else:
                    # Process current chunk
                    cleaned = _process_chunk(client, current_chunk)
                    cleaned_chunks.append(cleaned)
                    current_chunk = sentence + ". "

            # Process final chunk
            if current_chunk:
                cleaned = _process_chunk(client, current_chunk)
                cleaned_chunks.append(cleaned)

            # Combine chunks
            final_transcript = "\n\n".join(cleaned_chunks)
        else:
            # Process entire transcript at once
            final_transcript = _process_chunk(client, raw_transcript)

        logger.info(
            f"Cleanup completed. Output length: {len(final_transcript)} characters"
        )
        return final_transcript

    except Exception as e:
        logger.error(f"GPT cleanup failed: {str(e)}")
        # Return original transcript if cleanup fails
        logger.warning("Returning original transcript due to error")
        return raw_transcript


def _process_chunk(client: OpenAI, text_chunk: str) -> str:
    """
    Process a single chunk of text with GPT-4o

    Args:
        client: OpenAI client
        text_chunk: Text to process

    Returns:
        Cleaned text
    """
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=OPENAI_TEMPERATURE,
            messages=[
                {"role": "system", "content": CLEANUP_PROMPT},
                {
                    "role": "user",
                    "content": f"Please clean and format this transcript:\n\n{text_chunk}",
                },
            ],
        )

        cleaned_text = response.choices[0].message.content.strip()
        return cleaned_text

    except Exception as e:
        logger.error(f"Error processing chunk: {str(e)}")
        return text_chunk  # Return original if processing fails
