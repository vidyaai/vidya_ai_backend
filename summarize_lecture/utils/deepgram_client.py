import logging
import os
import httpx
from pathlib import Path
from deepgram import (
    DeepgramClient,
    PrerecordedOptions,
    FileSource,
    DeepgramClientOptions,
)
from deepgram.clients.listen import ListenRESTOptions
from config import (
    DEEPGRAM_API_KEY,
    DEEPGRAM_MODEL,
    DEEPGRAM_LANGUAGE,
    DEEPGRAM_SMART_FORMAT,
    DEEPGRAM_PUNCTUATE,
    DEEPGRAM_PARAGRAPHS,
)
from utils.audio_splitter import split_large_audio, merge_transcripts

logger = logging.getLogger(__name__)


def _transcribe_single_file(audio_path: str) -> dict:
    """
    Transcribe a single audio file using Deepgram API

    Args:
        audio_path: Path to audio file

    Returns:
        Dict with 'text' (raw transcript) and 'metadata'
    """
    try:
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)

        # Initialize Deepgram client
        deepgram = DeepgramClient(DEEPGRAM_API_KEY)

        # Read audio file
        logger.info("📖 Reading audio file into memory...")
        with open(audio_path, "rb") as audio:
            buffer_data = audio.read()

        logger.info(f"✓ Audio file loaded: {len(buffer_data) / (1024*1024):.2f} MB")

        payload: FileSource = {
            "buffer": buffer_data,
        }

        # Configure transcription options
        options = PrerecordedOptions(
            model=DEEPGRAM_MODEL,
            language=DEEPGRAM_LANGUAGE,
            smart_format=DEEPGRAM_SMART_FORMAT,
            punctuate=DEEPGRAM_PUNCTUATE,
            paragraphs=DEEPGRAM_PARAGRAPHS,
            utterances=True,
            diarize=False,
        )

        # Make transcription request
        logger.info("📤 Uploading to Deepgram API...")
        response = deepgram.listen.rest.v("1").transcribe_file(payload, options)

        logger.info("✓ Upload complete, processing transcription...")

        # Extract transcript
        transcript_data = response.to_dict()

        # Get the main transcript text
        if transcript_data and "results" in transcript_data:
            channels = transcript_data["results"]["channels"]
            if channels and len(channels) > 0:
                alternatives = channels[0]["alternatives"]
                if alternatives and len(alternatives) > 0:
                    transcript_text = alternatives[0]["transcript"]
                    paragraphs = alternatives[0].get("paragraphs", {})
                    word_count = len(transcript_text.split())

                    logger.info(f"✅ Transcription completed!")
                    logger.info(f"   📝 Length: {len(transcript_text):,} characters")
                    logger.info(f"   📊 Words: ~{word_count:,}")

                    return {
                        "text": transcript_text,
                        "paragraphs": paragraphs,
                        "metadata": {
                            "model": DEEPGRAM_MODEL,
                            "language": DEEPGRAM_LANGUAGE,
                            "confidence": alternatives[0].get("confidence", 0),
                            "file_size_mb": file_size_mb,
                            "word_count": word_count,
                        },
                    }

        raise Exception("No transcript found in Deepgram response")

    except Exception as e:
        logger.error(f"Transcription failed: {str(e)}")
        raise


def transcribe_audio_with_deepgram(audio_path: str) -> dict:
    """
    Transcribe audio file using Deepgram API with automatic chunking for large files

    Args:
        audio_path: Path to audio file

    Returns:
        Dict with 'text' (raw transcript) and 'metadata'
    """
    try:
        logger.info(f"Starting Deepgram transcription for: {audio_path}")

        # Check file size
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        logger.info(f"Audio file size: {file_size_mb:.2f} MB")

        # For very large files, split into chunks to avoid timeout
        if file_size_mb > 150:
            logger.warning(f"⚠️  Large file detected ({file_size_mb:.2f} MB).")
            logger.info(f"📦 Splitting into smaller chunks to avoid timeout...")

            chunk_files = split_large_audio(audio_path, chunk_duration_minutes=30)

            logger.info(f"🔄 Transcribing {len(chunk_files)} chunks...")
            transcript_chunks = []

            for i, chunk_file in enumerate(chunk_files, 1):
                logger.info(f"\n📤 Processing chunk {i}/{len(chunk_files)}...")
                chunk_result = _transcribe_single_file(chunk_file)
                transcript_chunks.append(chunk_result["text"])
                logger.info(
                    f"✓ Chunk {i} completed ({len(chunk_result['text']):,} chars)"
                )

            # Merge all chunks
            merged_transcript = merge_transcripts(transcript_chunks)

            # Clean up chunk files
            logger.info("🧹 Cleaning up temporary chunk files...")
            chunk_dir = Path(chunk_files[0]).parent
            for chunk_file in chunk_files:
                try:
                    os.remove(chunk_file)
                except:
                    pass
            try:
                chunk_dir.rmdir()
            except:
                pass

            word_count = len(merged_transcript.split())
            logger.info(f"✅ All chunks transcribed and merged successfully!")
            logger.info(
                f"   📝 Total transcript length: {len(merged_transcript):,} characters"
            )
            logger.info(f"   📊 Total word count: ~{word_count:,} words")

            return {
                "text": merged_transcript,
                "paragraphs": {},
                "metadata": {
                    "model": DEEPGRAM_MODEL,
                    "language": DEEPGRAM_LANGUAGE,
                    "file_size_mb": file_size_mb,
                    "word_count": word_count,
                    "chunks_processed": len(chunk_files),
                },
            }

        # For smaller files, process normally
        return _transcribe_single_file(audio_path)

    except TimeoutError as e:
        logger.error(
            f"⏱️ Timeout error: The file is too large and the upload timed out"
        )
        logger.error(
            f"💡 Suggestion: Try using a shorter video or split it into smaller segments"
        )
        raise Exception(
            f"Transcription timeout for large file. Try splitting the video into smaller parts."
        )
    except Exception as e:
        logger.error(f"Deepgram transcription failed: {str(e)}")
        if "timed out" in str(e).lower():
            logger.error(f"💡 Suggestion: For large files (>200MB), consider:")
            logger.error(f"   1. Splitting the video into smaller segments")
            logger.error(f"   2. Using a lower quality audio format")
            logger.error(f"   3. Trying again (network issues can cause timeouts)")
        raise


def format_deepgram_paragraphs(paragraphs_data: dict) -> str:
    """
    Format Deepgram paragraphs response into readable text

    Args:
        paragraphs_data: Paragraphs data from Deepgram

    Returns:
        Formatted text with paragraph breaks
    """
    if not paragraphs_data or "paragraphs" not in paragraphs_data:
        return ""

    formatted_text = []
    for paragraph in paragraphs_data["paragraphs"]:
        # Get all sentences in paragraph
        sentences = paragraph.get("sentences", [])
        paragraph_text = " ".join([s.get("text", "") for s in sentences])
        formatted_text.append(paragraph_text)

    return "\n\n".join(formatted_text)
