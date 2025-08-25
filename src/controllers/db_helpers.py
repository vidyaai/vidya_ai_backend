import os
from typing import Optional
from sqlalchemy.orm import Session
from models import Video
from .config import s3_client, AWS_S3_BUCKET
from .storage import s3_presign_url, s3_client


def get_or_create_video(db: Session, video_id: str, **kwargs) -> Video:
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            if "source_type" not in kwargs:
                raise ValueError(
                    f"source_type is required when creating new video {video_id}"
                )
            video = Video(id=video_id, **kwargs)
            db.add(video)
            db.commit()
            db.refresh(video)
        return video
    except Exception:
        db.rollback()
        raise


def update_upload_status(db: Session, video_id: str, status: dict):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        video = get_or_create_video(db, video_id, source_type="uploaded")
    else:
        video.upload_status = status
        db.add(video)
        db.commit()
    return video


def get_upload_status(db: Session, video_id: str) -> dict:
    video = db.query(Video).filter(Video.id == video_id).first()
    if video and video.upload_status:
        return video.upload_status
    return {"status": "not_found", "message": "No upload record found"}


def update_download_status(db: Session, video_id: str, status: dict):
    video = get_or_create_video(db, video_id, source_type="youtube")
    video.download_status = status
    if status.get("path"):
        video.download_path = status["path"]
    db.add(video)
    db.commit()


def get_download_status(db: Session, video_id: str) -> dict:
    video = db.query(Video).filter(Video.id == video_id).first()
    if video and video.download_status:
        return video.download_status
    return {"status": "not_found", "message": "No download record found"}


def update_formatting_status(db: Session, video_id: str, status: dict):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        video = get_or_create_video(db, video_id, source_type="youtube")
    video.formatting_status = status
    if status.get("formatted_transcript"):
        video.formatted_transcript = status["formatted_transcript"]
    db.add(video)
    db.commit()


def get_formatting_status(db: Session, video_id: str) -> dict:
    video = db.query(Video).filter(Video.id == video_id).first()
    if video and video.formatting_status:
        return video.formatting_status
    return {
        "status": "not_found",
        "message": "No formatting record found for this video",
        "formatted_transcript": None,
        "error": None,
    }


def get_transcript_cache(db: Session, video_id: str) -> dict:
    video = db.query(Video).filter(Video.id == video_id).first()
    if video:
        return {
            "transcript_data": video.transcript_text or "",
            "json_data": video.transcript_json or {},
        }
    return {}


def update_transcript_cache(
    db: Session, video_id: str, transcript_data: str, json_data: dict
):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        video = get_or_create_video(db, video_id, source_type="youtube")
    video.transcript_text = transcript_data
    video.transcript_json = json_data
    db.add(video)
    db.commit()


def get_video_path(db: Session, video_id: str) -> Optional[str]:
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return None
    if video.s3_key and s3_client and AWS_S3_BUCKET:
        try:
            return s3_presign_url(video.s3_key, expires_in=3600)
        except Exception:
            return None
    if video.download_path and os.path.exists(video.download_path):
        return video.download_path
    return None
