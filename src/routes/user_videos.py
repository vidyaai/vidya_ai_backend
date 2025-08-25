import os
import re
import tempfile
import shutil
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from utils.db import get_db
from models import Video
from controllers.config import (
    upload_executor,
    video_path,
    s3_client,
    AWS_S3_BUCKET,
)
from controllers.storage import (
    s3_upload_file,
    s3_presign_url,
    generate_thumbnail,
    transcribe_video_with_openai,
)
from controllers.db_helpers import update_upload_status, get_upload_status
from controllers.background_tasks import format_uploaded_transcript_background
from utils.firebase_auth import get_current_user


router = APIRouter(prefix="/api/user-videos", tags=["User Videos"])


@router.get("/upload-status/{video_id}")
async def get_upload_status_endpoint(video_id: str, db: Session = Depends(get_db)):
    return get_upload_status(db, video_id)


@router.post("/upload")
async def upload_user_video(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not s3_client or not AWS_S3_BUCKET:
        raise HTTPException(status_code=500, detail="S3 is not configured on server")
    vid = str(uuid.uuid4())
    try:
        suffix = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
        if suffix.lower() not in [".mp4", ".mov", ".mkv", ".webm", ".avi"]:
            suffix = ".mp4"
        temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(temp_fd)
        chunk_size = 1024 * 1024
        with open(temp_path, "wb") as out:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
        original_filename = file.filename or "Uploaded Video"
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to buffer uploaded file: {str(e)}"
        )
    user_id = current_user["uid"]
    upload_executor.submit(
        process_upload_background, vid, user_id, temp_path, original_filename
    )
    return {
        "success": True,
        "video_id": vid,
        "title": file.filename or "Uploaded Video",
        "message": f"Upload started. Use /api/user-videos/upload-status/{vid} to track progress.",
    }


def process_upload_background(
    video_id: str, user_id: str, temp_path: str, original_filename: str
):
    vid = video_id
    from utils.db import SessionLocal

    db = SessionLocal()
    uploaded_s3_objects = []
    local_files_to_cleanup = []
    update_upload_status(
        db,
        vid,
        {
            "status": "starting",
            "message": "Upload started",
            "progress": 0,
            "current_step": "initializing",
            "total_steps": 6,
        },
    )

    def rollback_upload():
        try:
            for s3_key in uploaded_s3_objects:
                if s3_client and AWS_S3_BUCKET:
                    s3_client.delete_object(Bucket=AWS_S3_BUCKET, Key=s3_key)
            for file_path in local_files_to_cleanup:
                if os.path.exists(file_path):
                    os.remove(file_path)
            video_row = db.query(Video).filter(Video.id == vid).first()
            if video_row:
                db.delete(video_row)
                db.commit()
        except Exception:
            db.rollback()

    try:
        update_upload_status(
            db,
            vid,
            {
                "status": "processing",
                "message": "Saving uploaded file...",
                "progress": 10,
                "current_step": "saving_file",
                "total_steps": 6,
            },
        )
        try:
            os.path.getsize(temp_path)
        except Exception:
            pass
        update_upload_status(
            db,
            vid,
            {
                "status": "processing",
                "message": "Preparing for cloud upload...",
                "progress": 20,
                "current_step": "preparing_upload",
                "total_steps": 6,
            },
        )
        safe_name = re.sub(
            r"[^A-Za-z0-9._-]+", "-", original_filename or "video.mp4"
        ).strip("-")
        s3_key = f"user_videos/{user_id}/{vid}_{safe_name}"
        thumb_key = f"thumbnails/{user_id}/{vid}.jpg"
        transcript_key = f"transcripts/{user_id}/{vid}.txt"
        update_upload_status(
            db,
            vid,
            {
                "status": "processing",
                "message": "Uploading video to cloud storage...",
                "progress": 35,
                "current_step": "uploading_video",
                "total_steps": 6,
            },
        )
        s3_upload_file(temp_path, s3_key, content_type="video/mp4")
        uploaded_s3_objects.append(s3_key)
        update_upload_status(
            db,
            vid,
            {
                "status": "processing",
                "message": "Generating thumbnail...",
                "progress": 50,
                "current_step": "generating_thumbnail",
                "total_steps": 6,
            },
        )
        thumb_fd, thumb_path = tempfile.mkstemp(suffix=".jpg")
        os.close(thumb_fd)
        local_files_to_cleanup.append(thumb_path)
        if generate_thumbnail(temp_path, thumb_path, ts_seconds=1.0):
            s3_upload_file(thumb_path, thumb_key, content_type="image/jpeg")
            uploaded_s3_objects.append(thumb_key)
        update_upload_status(
            db,
            vid,
            {
                "status": "processing",
                "message": "Transcribing audio (this may take a while)...",
                "progress": 65,
                "current_step": "transcribing",
                "total_steps": 6,
            },
        )
        transcript_text = transcribe_video_with_openai(temp_path)
        if transcript_text:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", delete=False, suffix=".txt"
            ) as tf:
                tf.write(transcript_text)
                transcript_tmp = tf.name
                local_files_to_cleanup.append(transcript_tmp)
            s3_upload_file(transcript_tmp, transcript_key, content_type="text/plain")
            uploaded_s3_objects.append(transcript_key)
        update_upload_status(
            db,
            vid,
            {
                "status": "processing",
                "message": "Finalizing upload...",
                "progress": 85,
                "current_step": "finalizing",
                "total_steps": 6,
            },
        )
        local_copy = os.path.join(video_path, f"{vid}.mp4")
        try:
            os.makedirs(video_path, exist_ok=True)
            shutil.move(temp_path, local_copy)
            local_files_to_cleanup.append(local_copy)
        except Exception:
            local_copy = temp_path
        video_row = db.query(Video).filter(Video.id == vid).first()
        if video_row:
            video_row.user_id = user_id
            video_row.title = original_filename or "Uploaded Video"
            video_row.s3_key = s3_key
            video_row.thumb_key = thumb_key
            video_row.transcript_s3_key = transcript_key
            video_row.local_path = local_copy
            video_row.transcript_text = transcript_text or None
            db.add(video_row)
            db.commit()
        else:
            video_row = Video(
                id=vid,
                user_id=user_id,
                source_type="uploaded",
                title=original_filename or "Uploaded Video",
                s3_key=s3_key,
                thumb_key=thumb_key,
                transcript_s3_key=transcript_key,
                local_path=local_copy,
                transcript_text=transcript_text or None,
            )
            db.add(video_row)
            db.commit()
        if transcript_text:
            format_uploaded_transcript_background(
                vid, transcript_text, original_filename or "Uploaded Video"
            )
        update_upload_status(
            db,
            vid,
            {
                "status": "completed",
                "message": "Upload completed successfully!",
                "progress": 100,
                "current_step": "completed",
                "total_steps": 6,
            },
        )
        s3_presign_url(s3_key, expires_in=3600)
        s3_presign_url(thumb_key, expires_in=3600)
        return
    except Exception as e:
        rollback_upload()
        update_upload_status(
            db,
            vid,
            {
                "status": "failed",
                "message": f"Upload failed: {str(e)}",
                "progress": 0,
                "current_step": "error",
                "total_steps": 6,
                "error": str(e),
            },
        )
        raise
    finally:
        try:
            db.close()
        except Exception:
            pass
        try:
            if "temp_path" in locals() and os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass


@router.get("/list")
async def list_user_videos(
    db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    user_id = current_user["uid"]
    rows = (
        db.query(Video)
        .filter(Video.user_id == user_id, Video.source_type == "uploaded")
        .order_by(Video.created_at.desc())
        .all()
    )
    items = []
    for v in rows:
        try:
            video_url = (
                s3_presign_url(v.s3_key, expires_in=3600)
                if (s3_client and AWS_S3_BUCKET and v.s3_key)
                else None
            )
            thumb_url = (
                s3_presign_url(v.thumb_key, expires_in=3600)
                if (s3_client and AWS_S3_BUCKET and v.thumb_key)
                else None
            )
        except Exception:
            video_url = None
            thumb_url = None
        items.append(
            {
                "video_id": v.id,
                "title": v.title or "Uploaded Video",
                "video_url": video_url,
                "thumbnail_url": thumb_url,
                "sourceType": "uploaded",
            }
        )
    return {"success": True, "items": items}


@router.get("/info")
async def get_user_video_info(video_id: str, db: Session = Depends(get_db)):
    v: Video = (
        db.query(Video)
        .filter(Video.id == video_id, Video.source_type == "uploaded")
        .first()
    )
    if not v:
        raise HTTPException(status_code=404, detail="Unknown video_id")
    try:
        video_url = (
            s3_presign_url(v.s3_key, expires_in=3600)
            if (s3_client and AWS_S3_BUCKET and v.s3_key)
            else None
        )
        thumb_url = (
            s3_presign_url(v.thumb_key, expires_in=3600)
            if (s3_client and AWS_S3_BUCKET and v.thumb_key)
            else None
        )
    except Exception:
        video_url = None
        thumb_url = None
    transcript_text = v.transcript_text or ""
    if not transcript_text and s3_client and AWS_S3_BUCKET and v.transcript_s3_key:
        try:
            obj = s3_client.get_object(Bucket=AWS_S3_BUCKET, Key=v.transcript_s3_key)
            transcript_text = obj["Body"].read().decode("utf-8")
            v.transcript_text = transcript_text
            db.add(v)
            db.commit()
        except Exception:
            pass
    return {
        "video_id": v.id,
        "title": v.title or "Uploaded Video",
        "video_url": video_url,
        "thumbnail_url": thumb_url,
        "transcript": transcript_text,
    }
