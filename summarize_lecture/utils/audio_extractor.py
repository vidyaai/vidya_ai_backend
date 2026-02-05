import os
import ffmpeg
import logging

logger = logging.getLogger(__name__)


def extract_audio_from_video(video_path: str, output_audio_path: str) -> str:
    """
    Extract audio from video file using ffmpeg

    Args:
        video_path: Path to input video file (.mp4)
        output_audio_path: Path for output audio file (.wav)

    Returns:
        Path to extracted audio file
    """
    try:
        logger.info(f"Extracting audio from: {video_path}")

        # Extract audio using ffmpeg
        stream = ffmpeg.input(video_path)
        stream = ffmpeg.output(
            stream,
            output_audio_path,
            acodec="pcm_s16le",  # PCM 16-bit
            ac=1,  # Mono
            ar="16000",  # 16kHz sample rate (good for speech)
        )

        # Overwrite output file if exists
        stream = ffmpeg.overwrite_output(stream)

        # Run ffmpeg
        ffmpeg.run(stream, capture_stdout=True, capture_stderr=True)

        logger.info(f"Audio extracted successfully: {output_audio_path}")
        return output_audio_path

    except ffmpeg.Error as e:
        error_message = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"FFmpeg error: {error_message}")
        raise Exception(f"Failed to extract audio: {error_message}")
    except Exception as e:
        logger.error(f"Audio extraction failed: {str(e)}")
        raise


def get_video_duration(video_path: str) -> float:
    """
    Get video duration in seconds

    Args:
        video_path: Path to video file

    Returns:
        Duration in seconds
    """
    try:
        probe = ffmpeg.probe(video_path)
        duration = float(probe["streams"][0]["duration"])
        return duration
    except Exception as e:
        logger.warning(f"Could not get video duration: {e}")
        return 0.0
