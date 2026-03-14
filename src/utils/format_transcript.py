import json
import os
import re
from openai import OpenAI, AsyncOpenAI
from typing import List, Dict
import sys
import asyncio

from controllers.db_helpers import update_formatting_status
from utils.db import SessionLocal
from controllers.config import logger

# Initialize OpenAI clients (reads OPENAI_API_KEY from environment)
client = OpenAI()
async_client = AsyncOpenAI()


def load_transcript(file_path: str) -> Dict:
    """Load transcript from JSON file"""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data[0]  # Get first item from the list


def format_time(seconds: float) -> str:
    """Convert seconds to MM:SS format"""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


def group_subtitles(
    transcription: List[Dict], group_duration: float = 10.0
) -> List[Dict]:
    """Group subtitles into chunks based on duration"""
    groups = []
    current_group = []
    current_start = None
    current_end = None

    for item in transcription:
        start_time = item["start"]
        # Handle both 'dur' (duration) and 'end' (end time) formats
        if "dur" in item:
            end_time = start_time + item["dur"]
        else:
            end_time = item["end"]

        if current_start is None:
            current_start = start_time
            current_end = end_time
            current_group = [item]
        elif end_time - current_start <= group_duration:
            current_group.append(item)
            current_end = end_time
        else:
            # Finalize current group
            combined_text = " ".join(
                [
                    str(item.get("text", item.get("subtitle", "")))
                    for item in current_group
                ]
            )
            groups.append(
                {"start": current_start, "end": current_end, "text": combined_text}
            )

            # Start new group
            current_start = start_time
            current_end = end_time
            current_group = [item]

    # Add the last group
    if current_group:
        combined_text = " ".join(
            [str(item.get("text", item.get("subtitle", ""))) for item in current_group]
        )
        groups.append(
            {"start": current_start, "end": current_end, "text": combined_text}
        )

    return groups


async def format_chunk_async(
    chunk: str, chunk_index: int, semaphore: asyncio.Semaphore
) -> tuple[int, str]:
    """Format a single chunk using OpenAI API asynchronously"""
    async with semaphore:  # Limit concurrent requests
        try:
            response = await async_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a transcript formatter. Your task is to:
1. Add proper punctuation (periods, commas, question marks, exclamation marks)
2. Capitalize the first letter of sentences
3. Fix common transcription errors
4. Make the text readable while preserving the original meaning
5. Do not add or remove content, only format it properly
6. Return only the formatted text without any additional comments""",
                    },
                    {
                        "role": "user",
                        "content": f"Format this transcript text with proper punctuation and capitalization: {chunk}",
                    },
                ],
                max_tokens=500,
                temperature=0.3,
            )

            formatted_text = response.choices[0].message.content.strip()
            logger.debug(f"✓ Chunk {chunk_index+1} formatted successfully")
            return (chunk_index, formatted_text)

        except Exception as e:
            logger.error(f"✗ Error formatting chunk {chunk_index+1}: {e}")
            return (chunk_index, chunk)  # Use original if formatting fails


async def format_with_openai_async(
    text_chunks: List[str], video_id: str = None, max_concurrent: int = 15
) -> List[str]:
    """Use OpenAI to format text chunks in parallel"""
    total_chunks = len(text_chunks)
    logger.info(
        f"Formatting {total_chunks} chunks with OpenAI (max {max_concurrent} concurrent) for video_id: {video_id}..."
    )

    # Initialize progress tracking
    if video_id:
        try:
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            db = SessionLocal()
            try:
                update_formatting_status(
                    db,
                    video_id,
                    {
                        "status": "formatting",
                        "message": f"AI formatting in progress... 0/{total_chunks} chunks (0%)",
                        "formatted_transcript": None,
                        "error": None,
                        "progress": 0,
                        "total_chunks": total_chunks,
                        "current_chunk": 0,
                    },
                )
            finally:
                db.close()
        except ImportError:
            pass

    # Create semaphore to limit concurrent requests
    semaphore = asyncio.Semaphore(max_concurrent)

    # Create tasks for all chunks
    tasks = [
        format_chunk_async(chunk, i, semaphore)
        for i, chunk in enumerate(text_chunks)
    ]

    # Process all chunks in parallel and update progress periodically
    formatted_results = []
    completed = 0

    for coro in asyncio.as_completed(tasks):
        chunk_index, formatted_text = await coro
        formatted_results.append((chunk_index, formatted_text))
        completed += 1

        # Update progress every 5 chunks or on last chunk
        if video_id and (completed % 5 == 0 or completed == total_chunks):
            try:
                db = SessionLocal()
                try:
                    current_progress = int((completed / total_chunks) * 100)
                    update_formatting_status(
                        db,
                        video_id,
                        {
                            "status": "formatting",
                            "message": f"AI formatting in progress... {completed}/{total_chunks} chunks ({current_progress}%)",
                            "formatted_transcript": None,
                            "error": None,
                            "progress": current_progress,
                            "total_chunks": total_chunks,
                            "current_chunk": completed,
                        },
                    )
                finally:
                    db.close()
            except:
                pass

    # Sort results by original index to maintain order
    formatted_results.sort(key=lambda x: x[0])
    formatted_chunks = [text for _, text in formatted_results]

    logger.info(f"✓ All {total_chunks} chunks formatted successfully")
    return formatted_chunks


def format_with_openai(text_chunks: List[str], video_id: str = None) -> List[str]:
    """Synchronous wrapper for async formatting function"""
    return asyncio.run(format_with_openai_async(text_chunks, video_id))


def convert_plain_text_to_transcript_data(
    plain_text: str, title: str = "Uploaded Video", duration: int = 0
) -> Dict:
    """Convert plain text transcript to the format expected by create_formatted_transcript"""
    # Split text into sentences/chunks for processing
    sentences = []
    if plain_text:
        # Split by sentence boundaries but maintain reasonable chunk sizes
        sentence_splits = re.split(r"(?<=[.!?])\s+", plain_text)

        # Group sentences into chunks of reasonable size (roughly 15-30 seconds worth)
        chunk_size = 3  # sentences per chunk
        for i in range(0, len(sentence_splits), chunk_size):
            chunk_text = " ".join(sentence_splits[i : i + chunk_size]).strip()
            if chunk_text:
                sentences.append(chunk_text)

    # Create fake timestamps - each chunk gets ~15 seconds
    chunk_duration = 15.0
    transcription = []

    for i, text in enumerate(sentences):
        start_time = i * chunk_duration
        end_time = start_time + chunk_duration

        transcription.append({"text": text, "start": start_time, "end": end_time})

    # If we have actual duration, adjust the last timestamp
    if duration > 0 and transcription:
        transcription[-1]["end"] = min(transcription[-1]["end"], duration)

    # Create the expected format
    return [
        {
            "title": title,
            "lengthInSeconds": duration or (len(sentences) * chunk_duration),
            "transcription": transcription,
        }
    ]


def create_formatted_transcript(
    transcript_data, output_file: str = None, video_id: str = None
):
    """Create formatted transcript with timestamps"""
    # Handle both dict and plain text input
    if isinstance(transcript_data, str):
        # Plain text input - convert to expected format
        transcript_data = convert_plain_text_to_transcript_data(
            transcript_data, "Uploaded Video"
        )
    elif isinstance(transcript_data, dict) and "plain_text" in transcript_data:
        # Handle special format for uploaded videos
        plain_text = transcript_data["plain_text"]
        title = transcript_data.get("title", "Uploaded Video")
        duration = transcript_data.get("duration", 0)
        transcript_data = convert_plain_text_to_transcript_data(
            plain_text, title, duration
        )

    logger.debug(f"transcript_data: {transcript_data[0]}")

    # Group subtitles into manageable chunks
    groups = group_subtitles(transcript_data[0]["transcription"], group_duration=30.0)

    # Extract text chunks for formatting
    text_chunks = [group["text"] for group in groups]

    # Format with OpenAI
    logger.info("Formatting text with OpenAI...")
    formatted_chunks = format_with_openai(text_chunks, video_id)

    # Create final formatted transcript
    formatted_transcript = []
    formatted_transcript.append(f"Title: {transcript_data[0]['title']}\n")
    formatted_transcript.append(
        f"Duration: {transcript_data[0]['lengthInSeconds']} seconds\n"
    )
    formatted_transcript.append("=" * 80 + "\n")

    for i, (group, formatted_text) in enumerate(zip(groups, formatted_chunks)):
        start_time = format_time(group["start"])
        end_time = format_time(group["end"])

        formatted_transcript.append(f"{start_time} - {end_time}\n")
        formatted_transcript.append(f"{formatted_text}\n\n")

    # Save to file only if output_file is specified
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.writelines(formatted_transcript)
        logger.info(f"Formatted transcript saved to {output_file}")
    else:
        logger.info("Formatted transcript created (not saved to file)")

    return formatted_transcript
