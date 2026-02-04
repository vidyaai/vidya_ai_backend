import logging
import subprocess
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def split_large_audio(audio_path: str, chunk_duration_minutes: int = 30) -> list:
    """
    Split large audio file into smaller chunks for transcription

    Args:
        audio_path: Path to the audio file
        chunk_duration_minutes: Duration of each chunk in minutes (default: 30)

    Returns:
        List of paths to chunk files
    """
    try:
        logger.info(
            f"Splitting audio file into {chunk_duration_minutes}-minute chunks..."
        )

        # Create chunks directory
        audio_file = Path(audio_path)
        chunks_dir = audio_file.parent / f"{audio_file.stem}_chunks"
        chunks_dir.mkdir(exist_ok=True)

        # Get audio duration
        duration_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]

        result = subprocess.run(
            duration_cmd, capture_output=True, text=True, check=True
        )
        total_duration = float(result.stdout.strip())
        total_minutes = total_duration / 60

        logger.info(f"Total audio duration: {total_minutes:.2f} minutes")

        # Calculate number of chunks needed
        chunk_duration_seconds = chunk_duration_minutes * 60
        num_chunks = int(
            (total_duration + chunk_duration_seconds - 1) // chunk_duration_seconds
        )

        logger.info(
            f"Creating {num_chunks} chunks of ~{chunk_duration_minutes} minutes each..."
        )

        chunk_files = []

        for i in range(num_chunks):
            start_time = i * chunk_duration_seconds
            chunk_file = chunks_dir / f"chunk_{i+1:03d}.wav"

            # Use ffmpeg to extract chunk
            cmd = [
                "ffmpeg",
                "-i",
                str(audio_path),
                "-ss",
                str(start_time),
                "-t",
                str(chunk_duration_seconds),
                "-c",
                "copy",
                "-y",  # Overwrite output file if exists
                str(chunk_file),
            ]

            logger.info(
                f"  Creating chunk {i+1}/{num_chunks} (starting at {start_time/60:.1f} min)..."
            )
            subprocess.run(cmd, capture_output=True, check=True)

            if chunk_file.exists():
                chunk_size_mb = chunk_file.stat().st_size / (1024 * 1024)
                logger.info(f"  ✓ Chunk {i+1} created: {chunk_size_mb:.1f} MB")
                chunk_files.append(str(chunk_file))
            else:
                logger.error(f"  ✗ Failed to create chunk {i+1}")

        logger.info(f"✓ Successfully created {len(chunk_files)} audio chunks")
        return chunk_files

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error while splitting audio: {e}")
        logger.error(f"FFmpeg stderr: {e.stderr if hasattr(e, 'stderr') else 'N/A'}")
        raise Exception(f"Failed to split audio file: {str(e)}")
    except Exception as e:
        logger.error(f"Error splitting audio: {str(e)}")
        raise


def merge_transcripts(transcript_chunks: list) -> str:
    """
    Merge transcripts from multiple chunks into one

    Args:
        transcript_chunks: List of transcript texts

    Returns:
        Combined transcript
    """
    # Join with double newline to preserve separation
    merged = "\n\n".join(transcript_chunks)

    logger.info(f"✓ Merged {len(transcript_chunks)} transcript chunks")
    logger.info(f"  Total length: {len(merged):,} characters")

    return merged
