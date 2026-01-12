from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from utils.db import get_db
from utils.youtube_utils import (
    download_transcript_api,
    extract_youtube_id,
)
from controllers.config import (
    download_executor,
    formatting_executor,
    s3_client,
    AWS_S3_BUCKET,
)
from controllers.db_helpers import (
    get_video_path,
    get_download_status,
    get_transcript_cache,
    get_formatting_status,
)
from controllers.background_tasks import (
    download_video_background,
    format_transcript_background,
)
from controllers.storage import s3_presign_url
from controllers.video_service import get_video_title
from schemas import YouTubeRequest
from utils.firebase_auth import get_current_user
from models import Video


router = APIRouter(prefix="/api/youtube", tags=["YouTube"])


@router.get("/download-status/{video_id}")
async def get_download_status_endpoint(
    video_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    # Check if video belongs to current user
    video = (
        db.query(Video)
        .filter(Video.id == video_id, Video.user_id == current_user["uid"])
        .first()
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found or access denied")

    video_path = get_video_path(db, video_id)
    if video_path:
        return {
            "status": "completed",
            "message": "Video download complete",
            "path": video_path,
        }
    return get_download_status(db, video_id)


@router.get("/formatting-status/{video_id}")
async def get_formatting_status_endpoint(
    video_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    # Check if video belongs to current user
    video = (
        db.query(Video)
        .filter(Video.id == video_id, Video.user_id == current_user["uid"])
        .first()
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found or access denied")

    return get_formatting_status(db, video_id)


@router.get("/formatted-transcript/{video_id}")
async def get_formatted_transcript(
    video_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    status = get_formatting_status(db, video_id)
    if status["status"] == "completed":
        return {
            "video_id": video_id,
            "status": "completed",
            "formatted_transcript": status["formatted_transcript"],
        }
    if status["status"] == "formatting":
        return {
            "video_id": video_id,
            "status": "formatting",
            "message": "Transcript is still being formatted. Please wait...",
        }
    if status["status"] == "failed":
        return {"video_id": video_id, "status": "failed", "error": status["error"]}
    video = (
        db.query(Video)
        .filter(Video.id == video_id, Video.user_id == current_user["uid"])
        .first()
    )
    if video and video.formatted_transcript:
        return {
            "video_id": video_id,
            "status": "completed",
            "formatted_transcript": video.formatted_transcript,
        }
    raise HTTPException(status_code=404, detail="Formatted transcript not found")


@router.post("/info")
async def get_youtube_info(
    request: YouTubeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    url = request.url
    video_id = extract_youtube_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    title = await get_video_title(video_id)
    video_path = get_video_path(db, video_id)
    if video_path:
        download_message = (
            "Video available in cloud storage"
            if video_path.startswith("http")
            else f"Video available locally: {video_path}"
        )
    else:
        status = get_download_status(db, video_id)
        if status["status"] != "not_found":
            download_message = (
                f"Download status: {status['status']} - {status['message']}"
            )
        else:
            download_executor.submit(
                download_video_background, video_id, url, current_user["uid"]
            )
            download_message = "Video download, thumbnail generation, and cloud upload started in background"
    transcript_info = get_transcript_cache(db, video_id)
    if transcript_info and transcript_info.get("transcript_data"):
        transcript_data = transcript_info["transcript_data"]
        json_data = transcript_info["json_data"]
    else:
        transcript_data, json_data = download_transcript_api(video_id)
        try:
            v = db.query(Video).filter(Video.id == video_id).first()
            if v is None:
                v = Video(
                    id=video_id,
                    user_id=current_user["uid"],
                    source_type="youtube",
                    title=title,
                    youtube_id=video_id,
                    youtube_url=url,
                    transcript_text=transcript_data,
                    transcript_json=json_data,
                )
                db.add(v)
            else:
                v.user_id = v.user_id or current_user["uid"]
                v.source_type = "youtube"
                v.title = title or v.title
                v.youtube_id = video_id
                v.youtube_url = url
                v.transcript_text = transcript_data or v.transcript_text
                v.transcript_json = json_data or v.transcript_json
            db.commit()
        except Exception:
            pass
    formatting_message = "Transcript not formatted"
    status = get_formatting_status(db, video_id)
    if status["status"] == "not_found":
        if json_data:
            formatting_executor.submit(
                format_transcript_background, video_id, json_data
            )
            formatting_message = "AI transcript formatting started in background"
        else:
            formatting_message = "No JSON data available for formatting"
    elif status["status"] == "failed":
        # Retry formatting if previous attempt failed and json data is available
        if json_data:
            formatting_executor.submit(
                format_transcript_background, video_id, json_data
            )
            formatting_message = "Retrying AI transcript formatting in background"
        else:
            formatting_message = (
                f"Formatting status: {status['status']} - {status['message']}"
            )
    else:
        formatting_message = (
            f"Formatting status: {status['status']} - {status['message']}"
        )
    video_url = None
    thumbnail_url = None
    formatted_transcript_url = None
    video_record = (
        db.query(Video)
        .filter(Video.id == video_id, Video.user_id == current_user["uid"])
        .first()
    )
    if video_record:
        if video_record.s3_key and s3_client and AWS_S3_BUCKET:
            try:
                video_url = s3_presign_url(video_record.s3_key, expires_in=3600)
            except Exception:
                pass
        if video_record.thumb_key and s3_client and AWS_S3_BUCKET:
            try:
                thumbnail_url = s3_presign_url(video_record.thumb_key, expires_in=3600)
            except Exception:
                pass
        if video_record.transcript_s3_key and s3_client and AWS_S3_BUCKET:
            try:
                formatted_transcript_url = s3_presign_url(
                    video_record.transcript_s3_key, expires_in=3600
                )
            except Exception:
                pass
    return {
        "video_id": video_id,
        "title": title,
        "url": url,
        "transcript": transcript_data,
        "embed_url": f"https://www.youtube.com/embed/{video_id}?enablejsapi=1",
        "download_status": download_message,
        "formatting_status": formatting_message,
        "video_url": video_url,
        "thumbnail_url": thumbnail_url,
        "formatted_transcript_url": formatted_transcript_url,
    }
