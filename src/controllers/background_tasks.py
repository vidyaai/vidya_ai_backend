import os
from utils.db import SessionLocal
from utils.youtube_utils import download_video
from utils.format_transcript import create_formatted_transcript
from models import Video
from .config import (
    frames_path,
    output_path,
    s3_client,
    AWS_S3_BUCKET,
)
from .storage import s3_upload_file, generate_thumbnail
from .db_helpers import (
    update_download_status,
    update_formatting_status,
    get_formatting_status,
)


def download_video_background(video_id: str, url: str):
    db = SessionLocal()
    try:
        status = {
            "status": "downloading",
            "message": "Video download in progress...",
            "path": None,
        }
        update_download_status(db, video_id, status)
        video_local_path = download_video(url)
        if video_local_path and os.path.exists(video_local_path):
            s3_key = None
            thumb_key = None
            if s3_client and AWS_S3_BUCKET:
                try:
                    s3_key = f"youtube_videos/{video_id}.mp4"
                    s3_upload_file(video_local_path, s3_key, content_type="video/mp4")
                    thumb_path = os.path.join(frames_path, f"{video_id}_thumb.jpg")
                    if generate_thumbnail(video_local_path, thumb_path, ts_seconds=1.0):
                        thumb_key = f"youtube_thumbnails/{video_id}.jpg"
                        s3_upload_file(thumb_path, thumb_key, content_type="image/jpeg")
                        os.remove(thumb_path)
                    video_row = db.query(Video).filter(Video.id == video_id).first()
                    if video_row:
                        video_row.s3_key = s3_key
                        video_row.thumb_key = thumb_key
                        video_row.download_path = None
                        db.commit()
                    os.remove(video_local_path)
                    status = {
                        "status": "completed",
                        "message": "Video and thumbnail uploaded to S3 successfully",
                        "path": None,
                        "s3_key": s3_key,
                        "thumb_key": thumb_key,
                    }
                except Exception:
                    status = {
                        "status": "completed",
                        "message": "Video download complete (S3 upload failed)",
                        "path": video_local_path,
                    }
            else:
                status = {
                    "status": "completed",
                    "message": "Video download complete (S3 not configured)",
                    "path": video_local_path,
                }
            update_download_status(db, video_id, status)
        else:
            update_download_status(
                db,
                video_id,
                {"status": "failed", "message": "Video download failed", "path": None},
            )
    finally:
        db.close()


def format_transcript_background(video_id: str, json_data: dict):
    db = SessionLocal()
    try:
        status = {
            "status": "formatting",
            "message": "AI-based transcript formatting in progress...",
            "formatted_transcript": None,
            "error": None,
            "progress": 0,
            "total_chunks": 0,
            "current_chunk": 0,
        }
        update_formatting_status(db, video_id, status)
        formatted_transcript_lines = create_formatted_transcript(
            json_data, video_id=video_id
        )
        # Ensure all items are strings before join to avoid type errors
        formatted_transcript_text = "".join(
            [str(line) for line in formatted_transcript_lines]
        )
        transcript_s3_key = None
        if s3_client and AWS_S3_BUCKET and formatted_transcript_text:
            temp_transcript_path = os.path.join(
                output_path, f"{video_id}_formatted_transcript.txt"
            )
            with open(temp_transcript_path, "w", encoding="utf-8") as f:
                f.write(formatted_transcript_text)
            transcript_s3_key = f"youtube_transcripts/{video_id}_formatted.txt"
            s3_upload_file(
                temp_transcript_path, transcript_s3_key, content_type="text/plain"
            )
            os.remove(temp_transcript_path)
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.formatted_transcript = formatted_transcript_text
            if transcript_s3_key:
                video.transcript_s3_key = transcript_s3_key
            db.commit()
        current_status = get_formatting_status(db, video_id)
        status = {
            "status": "completed",
            "message": "AI transcript formatting complete",
            "formatted_transcript": formatted_transcript_text,
            "error": None,
            "progress": 100,
            "total_chunks": current_status.get("total_chunks", 0),
            "current_chunk": current_status.get("total_chunks", 0),
            "transcript_s3_key": transcript_s3_key,
        }
        update_formatting_status(db, video_id, status)
    except Exception as e:
        status = {
            "status": "failed",
            "message": f"Transcript formatting failed: {str(e)}",
            "formatted_transcript": None,
            "error": str(e),
            "progress": 0,
            "total_chunks": 0,
            "current_chunk": 0,
        }
        update_formatting_status(db, video_id, status)
    finally:
        db.close()


def format_uploaded_transcript_background(
    video_id: str, transcript_text: str, title: str = "Uploaded Video"
):
    db = SessionLocal()
    try:
        status = {
            "status": "formatting",
            "message": "AI-based transcript formatting in progress...",
            "formatted_transcript": None,
            "error": None,
            "progress": 0,
            "total_chunks": 0,
            "current_chunk": 0,
        }
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            video = Video(id=video_id, source_type="uploaded", title=title)
            db.add(video)
            db.commit()
            db.refresh(video)
        video.formatting_status = status
        db.add(video)
        db.commit()
        transcript_data = {"plain_text": transcript_text, "title": title, "duration": 0}
        formatted_transcript_lines = create_formatted_transcript(
            transcript_data, video_id=video_id
        )
        formatted_transcript_text = "".join(
            [str(line) for line in formatted_transcript_lines]
        )
        transcript_s3_key = None
        if s3_client and AWS_S3_BUCKET and formatted_transcript_text:
            temp_transcript_path = os.path.join(
                output_path, f"{video_id}_formatted_transcript.txt"
            )
            with open(temp_transcript_path, "w", encoding="utf-8") as f:
                f.write(formatted_transcript_text)
            transcript_s3_key = f"uploaded_transcripts/{video_id}_formatted.txt"
            s3_upload_file(
                temp_transcript_path, transcript_s3_key, content_type="text/plain"
            )
            os.remove(temp_transcript_path)
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.formatted_transcript = formatted_transcript_text
            if transcript_s3_key:
                video.transcript_s3_key = transcript_s3_key
            db.commit()
        current_status = get_formatting_status(db, video_id)
        status = {
            "status": "completed",
            "message": "AI transcript formatting complete",
            "formatted_transcript": formatted_transcript_text,
            "error": None,
            "progress": 100,
            "total_chunks": current_status.get("total_chunks", 0),
            "current_chunk": current_status.get("total_chunks", 0),
            "transcript_s3_key": transcript_s3_key,
        }
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.formatting_status = status
            video.formatted_transcript = formatted_transcript_text
            db.add(video)
            db.commit()
    except Exception as e:
        status = {
            "status": "failed",
            "message": f"Transcript formatting failed: {str(e)}",
            "formatted_transcript": None,
            "error": str(e),
            "progress": 0,
            "total_chunks": 0,
            "current_chunk": 0,
        }
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.formatting_status = status
            db.add(video)
            db.commit()
    finally:
        db.close()
