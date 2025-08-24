import os
import cv2
from typing import Optional
from fastapi import HTTPException
from .config import s3_client, AWS_S3_BUCKET


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
