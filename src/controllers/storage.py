import cv2
import os
import mimetypes
import subprocess
import tempfile
from typing import List, Optional
from fastapi import HTTPException
from .config import s3_client, AWS_S3_BUCKET, deepgram_client, logger


def s3_upload_file(
    local_path: str, bucket_key: str, content_type: Optional[str] = None
):
    if not s3_client or not AWS_S3_BUCKET:
        raise HTTPException(status_code=500, detail="S3 is not configured")
    extra_args = {"ACL": "private"}
    if content_type:
        extra_args["ContentType"] = content_type
    s3_client.upload_file(local_path, AWS_S3_BUCKET, bucket_key, ExtraArgs=extra_args)


def s3_presign_url(bucket_key: str, expires_in: int = 3600) -> str:
    if not s3_client or not AWS_S3_BUCKET:
        raise HTTPException(status_code=500, detail="S3 is not configured")
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": AWS_S3_BUCKET, "Key": bucket_key},
        ExpiresIn=expires_in,
    )


def generate_thumbnail(
    input_video_path: str, output_image_path: str, ts_seconds: float = 1.0
) -> bool:
    try:
        cap = cv2.VideoCapture(input_video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 24
        frame_number = int(ts_seconds * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        success, frame = cap.read()
        if success:
            cv2.imwrite(output_image_path, frame)
            return True
        return False
    except Exception:
        return False
    finally:
        try:
            cap.release()
        except Exception:
            pass


def transcribe_video_with_openai(local_video_path: str) -> str:
    try:
        from openai import OpenAI

        client = OpenAI()
        with open(local_video_path, "rb") as f:
            transcript = client.audio.transcriptions.create(model="whisper-1", file=f)
        text = getattr(transcript, "text", None)
        if isinstance(transcript, dict):
            text = transcript.get("text")
        return text or ""
    except Exception as e:
        raise Exception(f"OpenAI transcription failed: {str(e)}")


def _extract_audio_with_ffmpeg(
    input_video_path: str, sample_rate: int = 16000
) -> Optional[str]:
    """Extract mono WAV audio using ffmpeg. Returns temp file path or None if failed."""
    try:
        fd, tmp_wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            input_video_path,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            tmp_wav_path,
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return tmp_wav_path
    except Exception:
        try:
            if "tmp_wav_path" in locals() and os.path.exists(tmp_wav_path):
                os.remove(tmp_wav_path)
        except Exception:
            pass
        return None


def _probe_media_duration_seconds(input_path: str) -> Optional[float]:
    """Return media duration in seconds using ffprobe, or None if unavailable."""
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            input_path,
        ]
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
        )
        output = result.stdout.decode("utf-8").strip()
        if not output:
            return None
        try:
            return float(output)
        except Exception:
            return None
    except Exception:
        return None


def _segment_media_to_wav_chunks(
    input_path: str, chunk_seconds: int = 600, sample_rate: int = 16000
) -> List[str]:
    """
    Segment input media into mono WAV chunks using ffmpeg. Returns list of temp file paths.

    Uses accurate seeking per chunk: ffmpeg -ss <start> -t <dur> -i <input> -vn -acodec pcm_s16le -ar 16000 -ac 1 <out>
    """
    chunk_paths: List[str] = []
    duration = _probe_media_duration_seconds(input_path) or 0.0
    # If duration unknown, fall back to a single extracted WAV to avoid complex logic
    if duration <= 0.0:
        extracted = _extract_audio_with_ffmpeg(input_path, sample_rate=sample_rate)
        return [extracted] if extracted else []

    temp_dir = tempfile.mkdtemp(prefix="vidyai_chunks_")
    start = 0.0
    chunk_index = 0
    # Ensure minimum chunk_seconds > 0
    chunk_len = max(30, int(chunk_seconds))
    while start < duration - 0.001:
        remaining = max(0.0, duration - start)
        this_len = min(float(chunk_len), remaining)
        out_path = os.path.join(temp_dir, f"chunk_{chunk_index:04d}.wav")
        cmd = [
            "ffmpeg",
            "-y",
            "-accurate_seek",
            "-ss",
            str(start),
            "-t",
            str(this_len),
            "-i",
            input_path,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            out_path,
        ]
        try:
            subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
            )
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                chunk_paths.append(out_path)
        except Exception:
            # Stop on failure to avoid infinite loops
            break
        chunk_index += 1
        start += this_len
    return chunk_paths


def transcribe_video_with_deepgram(local_video_path: str) -> str:
    """Transcribe a local video/audio file using Deepgram's prerecorded API.

    If the input appears to be a video, attempts ffmpeg audio extraction first.
    """
    if not deepgram_client:
        raise Exception("Deepgram is not configured on server")

    temp_audio_path: Optional[str] = None
    transcript_result: str = ""
    chunk_paths: List[str] = []
    try:
        suffix = os.path.splitext(local_video_path)[1].lower()
        is_video = suffix in [".mp4", ".mov", ".mkv", ".webm", ".avi"]
        source_path = local_video_path
        mimetype = (
            mimetypes.guess_type(local_video_path)[0] or "application/octet-stream"
        )

        if is_video:
            # Prefer extracting audio to reduce payload size and ensure supported codec
            extracted = _extract_audio_with_ffmpeg(local_video_path)
            if extracted and os.path.exists(extracted):
                temp_audio_path = extracted
                source_path = extracted
                mimetype = "audio/wav"

        # Decide whether to chunk based on duration; default to chunking if > 12 minutes
        duration_seconds = _probe_media_duration_seconds(local_video_path) or 0.0
        should_chunk = duration_seconds >= 12 * 60

        # Lazy import to avoid hard dependency if SDK missing at import time
        try:
            from deepgram import PrerecordedOptions  # type: ignore
        except Exception:
            PrerecordedOptions = None  # type: ignore

        options = None
        if PrerecordedOptions is not None:
            options = PrerecordedOptions(
                model="nova-2",
                smart_format=True,
                punctuate=True,
            )

        def _transcribe_file_bytes(
            data_bytes: bytes, mimetype_hint: Optional[str]
        ) -> str:
            payload = {"buffer": data_bytes}
            if mimetype_hint:
                payload["mimetype"] = mimetype_hint
            response = deepgram_client.listen.rest.v("1").transcribe_file(
                payload, options
            )
            # Extract transcript text robustly
            transcript_text_inner = ""
            try:
                results = (
                    response.get("results")
                    if isinstance(response, dict)
                    else getattr(response, "results", None)
                )
                if results:
                    channels = (
                        results.get("channels")
                        if isinstance(results, dict)
                        else getattr(results, "channels", None)
                    )
                    if channels and len(channels) > 0:
                        alt = (
                            channels[0].get("alternatives")
                            if isinstance(channels[0], dict)
                            else getattr(channels[0], "alternatives", None)
                        )
                        if alt and len(alt) > 0:
                            transcript_text_inner = (
                                alt[0].get("transcript")
                                if isinstance(alt[0], dict)
                                else getattr(alt[0], "transcript", "")
                            )
            except Exception:
                transcript_text_inner = ""

            if not transcript_text_inner:
                transcript_text_inner = (
                    getattr(response, "transcript", "")
                    if not isinstance(response, dict)
                    else response.get("transcript", "")
                )
            return transcript_text_inner or ""

        if not should_chunk:
            with open(source_path, "rb") as f:
                data = f.read()
            transcript_result = _transcribe_file_bytes(data, mimetype)
            return transcript_result

        # For long media, segment into ~10-minute WAV chunks and transcribe sequentially
        chunk_paths = _segment_media_to_wav_chunks(local_video_path, chunk_seconds=600)
        if not chunk_paths:
            # Fallback to single-file flow if segmentation failed
            with open(source_path, "rb") as f:
                data = f.read()
            transcript_result = _transcribe_file_bytes(data, mimetype)
            return transcript_result

        transcripts: List[str] = []
        for chunk_path in chunk_paths:
            with open(chunk_path, "rb") as f:
                chunk_data = f.read()
            part = _transcribe_file_bytes(chunk_data, "audio/wav")
            if part:
                transcripts.append(part.strip())
        # Merge with double newlines to preserve separation
        transcript_result = "\n\n".join([p for p in transcripts if p])
        return transcript_result
    except Exception as e:
        raise Exception(f"Deepgram transcription failed: {str(e)}")
    finally:
        try:
            if temp_audio_path and os.path.exists(temp_audio_path):
                os.remove(temp_audio_path)
        except Exception:
            pass
        try:
            for p in chunk_paths:
                try:
                    if p and os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass
        except Exception:
            pass


def transcribe_video_with_deepgram_url(media_url: str) -> str:
    """Transcribe media accessible via URL using Deepgram prerecorded URL API."""
    if not deepgram_client:
        raise Exception("Deepgram is not configured on server")
    try:
        try:
            from deepgram import PrerecordedOptions  # type: ignore
        except Exception:
            PrerecordedOptions = None  # type: ignore

        options = None
        if PrerecordedOptions is not None:
            options = PrerecordedOptions(
                model="nova-2",
                smart_format=True,
                punctuate=True,
            )

        payload = {"url": media_url}
        # Use URL-based transcription to avoid uploading bytes from our server
        # Prefer the same REST path family as file-based call
        response = deepgram_client.listen.rest.v("1").transcribe_url(payload, options)

        # Extract transcript similarly to file path
        transcript_text = ""
        try:
            results = (
                response.get("results")
                if isinstance(response, dict)
                else getattr(response, "results", None)
            )
            if results:
                channels = (
                    results.get("channels")
                    if isinstance(results, dict)
                    else getattr(results, "channels", None)
                )
                if channels and len(channels) > 0:
                    alt = (
                        channels[0].get("alternatives")
                        if isinstance(channels[0], dict)
                        else getattr(channels[0], "alternatives", None)
                    )
                    if alt and len(alt) > 0:
                        transcript_text = (
                            alt[0].get("transcript")
                            if isinstance(alt[0], dict)
                            else getattr(alt[0], "transcript", "")
                        )
        except Exception:
            transcript_text = ""

        if not transcript_text:
            transcript_text = (
                getattr(response, "transcript", "")
                if not isinstance(response, dict)
                else response.get("transcript", "")
            )
        return transcript_text or ""
    except Exception as e:
        raise Exception(f"Deepgram transcription failed: {str(e)}")


def transcribe_video_with_deepgram_timed(
    local_video_path: str, video_title: str = "Video"
) -> dict:
    """
    Transcribe a local video/audio file using Deepgram and return timed segments.

    Returns format compatible with RapidAPI:
    {
        "title": "Video Title",
        "lengthInSeconds": 500,
        "transcription": [
            {"start": 0.0, "dur": 2.5, "text": "Hello world"},
            {"start": 2.5, "dur": 1.8, "text": "This is a test"}
        ]
    }
    """
    if not deepgram_client:
        raise Exception("Deepgram is not configured on server")

    temp_audio_path: Optional[str] = None

    try:
        suffix = os.path.splitext(local_video_path)[1].lower()
        is_video = suffix in [".mp4", ".mov", ".mkv", ".webm", ".avi"]
        source_path = local_video_path
        mimetype = (
            mimetypes.guess_type(local_video_path)[0] or "application/octet-stream"
        )

        if is_video:
            # Extract audio to reduce payload size
            extracted = _extract_audio_with_ffmpeg(local_video_path)
            if extracted and os.path.exists(extracted):
                temp_audio_path = extracted
                source_path = extracted
                mimetype = "audio/wav"

        # Import Deepgram options
        try:
            from deepgram import PrerecordedOptions
        except Exception:
            PrerecordedOptions = None

        # Request word-level timestamps
        options = None
        if PrerecordedOptions is not None:
            options = PrerecordedOptions(
                model="nova-2",
                smart_format=True,
                punctuate=True,
                utterances=True,  # Get utterance-level timestamps
                utt_split=3.0,  # Split utterances every ~3 seconds
            )

        # Transcribe
        with open(source_path, "rb") as f:
            data = f.read()

        payload = {"buffer": data}
        if mimetype:
            payload["mimetype"] = mimetype

        # Use extended timeout for large files (up to 5 minutes)
        try:
            import httpx

            response = deepgram_client.listen.rest.v("1").transcribe_file(
                payload, options, timeout=httpx.Timeout(300.0)
            )
        except Exception:
            # Fallback without timeout if httpx not available
            response = deepgram_client.listen.rest.v("1").transcribe_file(
                payload, options
            )

        # Extract utterances with timing
        transcription_segments = []
        total_duration = 0

        try:
            results = (
                response.get("results")
                if isinstance(response, dict)
                else getattr(response, "results", None)
            )

            if results:
                # Try to get utterances first (better for timing)
                utterances = (
                    results.get("utterances")
                    if isinstance(results, dict)
                    else getattr(results, "utterances", None)
                )

                if utterances:
                    for utt in utterances:
                        start = (
                            utt.get("start")
                            if isinstance(utt, dict)
                            else getattr(utt, "start", 0)
                        )
                        end = (
                            utt.get("end")
                            if isinstance(utt, dict)
                            else getattr(utt, "end", 0)
                        )
                        text = (
                            utt.get("transcript")
                            if isinstance(utt, dict)
                            else getattr(utt, "transcript", "")
                        )

                        if text:
                            transcription_segments.append(
                                {"start": start, "dur": end - start, "text": text}
                            )
                            total_duration = max(total_duration, end)

                # Fallback to channels if no utterances
                if not transcription_segments:
                    channels = (
                        results.get("channels")
                        if isinstance(results, dict)
                        else getattr(results, "channels", None)
                    )

                    if channels and len(channels) > 0:
                        alternatives = (
                            channels[0].get("alternatives")
                            if isinstance(channels[0], dict)
                            else getattr(channels[0], "alternatives", None)
                        )

                        if alternatives and len(alternatives) > 0:
                            words = (
                                alternatives[0].get("words")
                                if isinstance(alternatives[0], dict)
                                else getattr(alternatives[0], "words", None)
                            )

                            if words:
                                # Group words into ~3 second segments
                                current_segment = {"start": 0, "words": []}

                                for word in words:
                                    word_start = (
                                        word.get("start")
                                        if isinstance(word, dict)
                                        else getattr(word, "start", 0)
                                    )
                                    word_end = (
                                        word.get("end")
                                        if isinstance(word, dict)
                                        else getattr(word, "end", 0)
                                    )
                                    word_text = (
                                        word.get("word") or word.get("punctuated_word")
                                        if isinstance(word, dict)
                                        else getattr(word, "word", "")
                                        or getattr(word, "punctuated_word", "")
                                    )

                                    if not current_segment["words"]:
                                        current_segment["start"] = word_start

                                    current_segment["words"].append(word_text)

                                    # Split segment every ~3 seconds
                                    if word_end - current_segment["start"] >= 3.0:
                                        text = " ".join(current_segment["words"])
                                        transcription_segments.append(
                                            {
                                                "start": current_segment["start"],
                                                "dur": word_end
                                                - current_segment["start"],
                                                "text": text,
                                            }
                                        )
                                        current_segment = {"start": 0, "words": []}
                                        total_duration = max(total_duration, word_end)

                                # Add remaining words
                                if current_segment["words"]:
                                    last_word = words[-1]
                                    last_end = (
                                        last_word.get("end")
                                        if isinstance(last_word, dict)
                                        else getattr(last_word, "end", 0)
                                    )
                                    text = " ".join(current_segment["words"])
                                    transcription_segments.append(
                                        {
                                            "start": current_segment["start"],
                                            "dur": last_end - current_segment["start"],
                                            "text": text,
                                        }
                                    )
                                    total_duration = max(total_duration, last_end)

        except Exception as parse_error:
            logger.error(f"Failed to parse Deepgram timing data: {parse_error}")
            # Return empty segments if parsing fails
            pass

        # Return in RapidAPI-compatible format
        return {
            "title": video_title,
            "lengthInSeconds": int(total_duration),
            "transcription": transcription_segments,
        }

    except Exception as e:
        raise Exception(f"Deepgram timed transcription failed: {str(e)}")
    finally:
        try:
            if temp_audio_path and os.path.exists(temp_audio_path):
                os.remove(temp_audio_path)
        except Exception:
            pass
