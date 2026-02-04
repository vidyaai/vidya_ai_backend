import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from config import INPUT_DIR, OUTPUT_DIR, TEMP_DIR
from utils.audio_extractor import extract_audio_from_video, get_video_duration
from utils.deepgram_client import transcribe_audio_with_deepgram
from utils.gpt_cleaner import clean_transcript_with_gpt

logger = logging.getLogger(__name__)


def ensure_directories():
    """Create necessary directories if they don't exist"""
    for directory in [INPUT_DIR, OUTPUT_DIR, TEMP_DIR]:
        Path(directory).mkdir(parents=True, exist_ok=True)


def transcribe_video(video_path: str, output_filename: str = None) -> str:
    """
    Complete pipeline: Video → Audio → Deepgram → GPT cleanup → Text file

    Args:
        video_path: Path to input .mp4 file
        output_filename: Optional custom output filename

    Returns:
        Path to output .txt file
    """
    try:
        logger.info("=" * 60)
        logger.info("STARTING VIDEO TRANSCRIPTION PIPELINE")
        logger.info("=" * 60)

        # Validate input file
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        video_name = Path(video_path).stem
        logger.info(f"Processing video: {video_name}")

        # Get video duration
        duration = get_video_duration(video_path)
        logger.info(
            f"Video duration: {duration:.2f} seconds ({duration/60:.2f} minutes)"
        )

        # Step 1: Extract audio
        logger.info("\n[1/4] Extracting audio from video...")
        temp_audio_path = os.path.join(TEMP_DIR, f"{video_name}_audio.wav")
        extract_audio_from_video(video_path, temp_audio_path)

        # Step 2: Transcribe with Deepgram
        logger.info("\n[2/4] Transcribing audio with Deepgram...")
        transcription_result = transcribe_audio_with_deepgram(temp_audio_path)
        raw_transcript = transcription_result["text"]

        logger.info(f"Raw transcript length: {len(raw_transcript)} characters")

        # Confidence may not be available for chunked transcription
        if "confidence" in transcription_result["metadata"]:
            logger.info(
                f"Transcription confidence: {transcription_result['metadata']['confidence']:.2%}"
            )
        if "chunks_processed" in transcription_result["metadata"]:
            logger.info(
                f"Chunks processed: {transcription_result['metadata']['chunks_processed']}"
            )

        # Save raw transcript (optional)
        raw_output_path = os.path.join(OUTPUT_DIR, f"{video_name}_raw.txt")
        with open(raw_output_path, "w", encoding="utf-8") as f:
            f.write(raw_transcript)
        logger.info(f"Raw transcript saved to: {raw_output_path}")

        # Step 3: Clean with GPT-4o
        logger.info("\n[3/4] Cleaning transcript with GPT-4o...")
        cleaned_transcript = clean_transcript_with_gpt(raw_transcript)

        # Step 4: Save cleaned transcript
        logger.info("\n[4/4] Saving cleaned transcript...")

        if output_filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"{video_name}_cleaned_{timestamp}.txt"

        output_path = os.path.join(OUTPUT_DIR, output_filename)

        with open(output_path, "w", encoding="utf-8") as f:
            # Add metadata header
            f.write(f"# Transcript: {video_name}\n")
            f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Duration: {duration:.2f} seconds\n")
            f.write(f"# Model: Deepgram {transcription_result['metadata']['model']}\n")
            f.write(f"# Cleaned by: GPT-4o\n")
            f.write("\n" + "=" * 60 + "\n\n")
            f.write(cleaned_transcript)

        logger.info(f"\n✅ SUCCESS! Cleaned transcript saved to: {output_path}")

        # Cleanup temp files
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)
            logger.info("Temporary audio file deleted")

        # Print statistics
        logger.info("\n" + "=" * 60)
        logger.info("TRANSCRIPTION STATISTICS")
        logger.info("=" * 60)
        logger.info(f"Video: {video_name}")
        logger.info(f"Duration: {duration:.2f} seconds ({duration/60:.2f} minutes)")
        logger.info(f"Raw transcript: {len(raw_transcript)} characters")
        logger.info(f"Cleaned transcript: {len(cleaned_transcript)} characters")
        logger.info(f"Output file: {output_path}")
        logger.info("=" * 60)

        return output_path

    except Exception as e:
        logger.error(f"\n❌ TRANSCRIPTION FAILED: {str(e)}")
        raise
