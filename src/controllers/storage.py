import cv2
import os
import mimetypes
import subprocess
import tempfile
from typing import Optional
from fastapi import HTTPException
from .config import s3_client, AWS_S3_BUCKET, deepgram_client


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


def transcribe_video_with_deepgram(local_video_path: str) -> str:
    """Transcribe a local video/audio file using Deepgram's prerecorded API.

    If the input appears to be a video, attempts ffmpeg audio extraction first.
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
            # Prefer extracting audio to reduce payload size and ensure supported codec
            extracted = _extract_audio_with_ffmpeg(local_video_path)
            if extracted and os.path.exists(extracted):
                temp_audio_path = extracted
                source_path = extracted
                mimetype = "audio/wav"

        with open(source_path, "rb") as f:
            data = f.read()

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

        # Prepare payload for Deepgram v4 SDK
        payload = {"buffer": data}
        # include mimetype if we know it (harmless, sometimes improves detection)
        if mimetype:
            payload["mimetype"] = mimetype

        # Perform request (sync) using v4 client path
        response = deepgram_client.listen.rest.v("1").transcribe_file(payload, options)

        # Extract transcript text robustly
        transcript_text = ""
        try:
            # dict-like access
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
            # Fallback: some SDK versions expose top-level transcript string
            transcript_text = (
                getattr(response, "transcript", "")
                if not isinstance(response, dict)
                else response.get("transcript", "")
            )

        return transcript_text or ""
    except Exception as e:
        raise Exception(f"Deepgram transcription failed: {str(e)}")
    finally:
        try:
            if temp_audio_path and os.path.exists(temp_audio_path):
                os.remove(temp_audio_path)
        except Exception:
            pass
