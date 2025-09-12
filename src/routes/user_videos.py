import os
import re
import tempfile
import shutil
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi import Body
from sqlalchemy.orm import Session
from utils.db import SessionLocal, get_db
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
    transcribe_video_with_deepgram,
    transcribe_video_with_deepgram_url,
)
from controllers.db_helpers import update_upload_status, get_upload_status
from controllers.background_tasks import format_uploaded_transcript_background
from utils.firebase_auth import get_current_user
from models import SharedLink, SharedLinkAccess
from routes.sharing import validate_shared_video_access
from routes.gallery_folders import check_content_is_shared


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
        transcript_text = ""
        # Prefer server-to-server URL pull by Deepgram to avoid write timeouts
        try:
            presigned = s3_presign_url(s3_key, expires_in=60 * 60 * 12)
            transcript_text = transcribe_video_with_deepgram_url(presigned)
        except Exception:
            transcript_text = ""
        # Fallback to local chunked transcription if URL approach fails
        if not transcript_text:
            transcript_text = transcribe_video_with_deepgram(temp_path)
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
        rollback_upload()
        raise
    finally:
        if transcript_text:
            format_uploaded_transcript_background(
                vid, transcript_text, original_filename or "Uploaded Video"
            )
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
async def get_user_video_info(
    video_id: str, share_token: str = None, db: Session = Depends(get_db)
):
    # If share_token is provided, validate it and get video info for shared videos
    if share_token:
        # Validate the shared video access
        video = validate_shared_video_access(db, share_token, video_id)
        if not video:
            raise HTTPException(
                status_code=404, detail="Video not found in shared content"
            )
    else:
        # Regular user video lookup (existing behavior)
        video = (
            db.query(Video)
            .filter(Video.id == video_id, Video.source_type == "uploaded")
            .first()
        )
        if not video:
            raise HTTPException(status_code=404, detail="Unknown video_id")

    try:
        video_url = (
            s3_presign_url(video.s3_key, expires_in=3600)
            if (s3_client and AWS_S3_BUCKET and video.s3_key)
            else None
        )
        thumb_url = (
            s3_presign_url(video.thumb_key, expires_in=3600)
            if (s3_client and AWS_S3_BUCKET and video.thumb_key)
            else None
        )
    except Exception:
        video_url = None
        thumb_url = None

    transcript_text = video.transcript_text or ""
    if not transcript_text and s3_client and AWS_S3_BUCKET and video.transcript_s3_key:
        try:
            obj = s3_client.get_object(
                Bucket=AWS_S3_BUCKET, Key=video.transcript_s3_key
            )
            transcript_text = obj["Body"].read().decode("utf-8")
            video.transcript_text = transcript_text
            db.add(video)
            db.commit()
        except Exception:
            pass

    return {
        "video_id": video.id,
        "title": video.title or "Uploaded Video",
        "video_url": video_url,
        "thumbnail_url": thumb_url,
        "transcript": transcript_text,
        "chat_sessions": video.chat_sessions or [],
        "source_type": video.source_type,
        "youtube_id": video.youtube_id,
        "youtube_url": video.youtube_url,
        "s3_key": video.s3_key,
    }


@router.get("/chat-sessions")
async def get_chat_sessions(
    video_id: str,
    share_id: str = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # If share_id is provided, validate shared access
    if share_id:
        # Get the shared link to validate access
        shared_link = db.query(SharedLink).filter(SharedLink.id == share_id).first()
        if not shared_link:
            raise HTTPException(status_code=404, detail="Shared link not found")

        # Check if user has access to this shared link
        has_access = (
            shared_link.owner_id == current_user["uid"]
            or db.query(SharedLinkAccess)
            .filter(
                SharedLinkAccess.shared_link_id == share_id,
                SharedLinkAccess.user_id == current_user["uid"],
            )
            .first()
            is not None
        )

        if not has_access:
            raise HTTPException(
                status_code=403, detail="Access denied to shared content"
            )

        # Validate that the video matches the shared link
        if shared_link.share_type == "chat" and shared_link.video_id == video_id:
            v = db.query(Video).filter(Video.id == video_id).first()
            if not v:
                raise HTTPException(status_code=404, detail="Video not found")
            return {"video_id": video_id, "chat_sessions": v.chat_sessions or []}
        else:
            raise HTTPException(
                status_code=404, detail="Video not found in shared content"
            )

    # Regular user video lookup (existing behavior)
    v: Video = db.query(Video).filter(Video.id == video_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Unknown video_id")

    return {"video_id": video_id, "chat_sessions": v.chat_sessions or []}


@router.post("/chat-sessions")
async def save_chat_sessions(
    video_id: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    v: Video = db.query(Video).filter(Video.id == video_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Unknown video_id")
    sessions = payload.get("chat_sessions", [])
    if not isinstance(sessions, list):
        raise HTTPException(status_code=400, detail="chat_sessions must be a list")
    try:
        v.chat_sessions = sessions
        db.add(v)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    return {"success": True}


@router.delete("/chat-sessions/{video_id}/{session_id}")
async def delete_chat_session(
    video_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Delete a specific chat session from a video."""
    v: Video = db.query(Video).filter(Video.id == video_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    # Check user ownership
    if v.user_id != current_user["uid"]:
        raise HTTPException(
            status_code=403, detail="Not authorized to delete this chat session"
        )

    if not v.chat_sessions:
        raise HTTPException(status_code=404, detail="No chat sessions found")

    # Check if this specific chat session is part of any shared content
    shared_links = (
        db.query(SharedLink)
        .filter(
            SharedLink.video_id == video_id,
            SharedLink.chat_session_id == session_id,
            SharedLink.share_type == "chat",
        )
        .all()
    )

    if shared_links:
        link = shared_links[0]
        raise HTTPException(
            status_code=400,
            detail={
                "error": "content_is_shared",
                "message": f"This chat session is part of shared content and cannot be deleted. Please delete the share link first to remove it from shared content.",
                "shared_link": {
                    "id": link.id,
                    "title": link.title or "Shared Chat Session",
                    "share_type": link.share_type,
                    "is_public": link.is_public,
                    "created_at": link.created_at.isoformat()
                    if link.created_at
                    else None,
                },
            },
        )

    # Find and remove the specific chat session
    updated_sessions = []
    session_found = False

    for session in v.chat_sessions:
        if session.get("id") == session_id:
            session_found = True
            # Skip this session (effectively deleting it)
        else:
            updated_sessions.append(session)

    if not session_found:
        raise HTTPException(status_code=404, detail="Chat session not found")

    try:
        v.chat_sessions = updated_sessions
        db.add(v)
        db.commit()
        return {"success": True, "message": "Chat session deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to delete chat session: {str(e)}"
        )


@router.get("/chat-sessions/{video_id}/{session_id}/info")
async def get_chat_session_info(
    video_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get chat session information including sharing status."""
    v: Video = db.query(Video).filter(Video.id == video_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    # Check user ownership
    if v.user_id != current_user["uid"]:
        raise HTTPException(
            status_code=403, detail="Not authorized to view this chat session"
        )

    if not v.chat_sessions:
        raise HTTPException(status_code=404, detail="No chat sessions found")

    # Find the specific chat session
    target_session = None
    for session in v.chat_sessions:
        if session.get("id") == session_id:
            target_session = session
            break

    if not target_session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    # Check if this specific chat session is part of any shared content
    shared_links = (
        db.query(SharedLink)
        .filter(
            SharedLink.video_id == video_id,
            SharedLink.chat_session_id == session_id,
            SharedLink.share_type == "chat",
        )
        .all()
    )

    shared_info = None
    if shared_links:
        link = shared_links[0]
        shared_info = {
            "id": link.id,
            "title": link.title or "Shared Chat Session",
            "share_type": link.share_type,
            "is_public": link.is_public,
            "created_at": link.created_at.isoformat() if link.created_at else None,
        }

    return {
        "video_id": video_id,
        "session_id": session_id,
        "session_title": target_session.get("title", "Untitled Chat"),
        "message_count": len(target_session.get("messages", [])),
        "created_at": target_session.get("createdAt"),
        "updated_at": target_session.get("updatedAt"),
        "can_delete": shared_info is None,
        "is_shared": shared_info is not None,
        "shared_link": shared_info,
    }
