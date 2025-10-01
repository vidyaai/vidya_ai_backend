from fastapi import APIRouter, Depends, HTTPException
import os
from sqlalchemy.orm import Session
from utils.db import get_db
from controllers.db_helpers import (
    get_formatting_status,
    get_transcript_cache,
    update_transcript_cache,
    get_download_status,
    get_video_path,
)
from controllers.background_tasks import download_video_background
from controllers.config import frames_path, download_executor
from utils.youtube_utils import download_transcript_api, grab_youtube_frame
from utils.ml_models import OpenAIVisionClient
from schemas import VideoQuery
from utils.firebase_auth import get_current_user


router = APIRouter(prefix="/api/query", tags=["Query"])


@router.post("/video")
async def process_query(
    query_request: VideoQuery,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        video_id = query_request.video_id
        query = query_request.query
        timestamp = query_request.timestamp
        is_image_query = query_request.is_image_query
        vision_client = OpenAIVisionClient()
        transcript_to_use = None
        formatting_status_info = get_formatting_status(db, video_id)
        if formatting_status_info["status"] == "completed":
            transcript_to_use = formatting_status_info["formatted_transcript"]
        if not transcript_to_use:
            transcript_info = get_transcript_cache(db, video_id)
            if transcript_info and transcript_info.get("transcript_data"):
                transcript_to_use = transcript_info["transcript_data"]
            else:
                transcript_data, json_data = download_transcript_api(video_id)
                transcript_to_use = transcript_data
                update_transcript_cache(db, video_id, transcript_data, json_data)
        if is_image_query:
            if timestamp is None:
                raise HTTPException(
                    status_code=400, detail="Timestamp is required for image queries"
                )
            video_path_local = get_video_path(db, video_id)
            if not video_path_local:
                download_status_info = get_download_status(db, video_id)
                if download_status_info["status"] == "downloading":
                    return {
                        "response": "🎬 Something amazing is being loaded! The video is still downloading in the background. Please continue to chat with the video content in the meantime, and try frame-specific questions again in a moment!",
                        "video_id": video_id,
                        "timestamp": timestamp,
                        "query_type": "downloading",
                        "is_downloading": True,
                    }
                elif download_status_info["status"] == "failed":
                    raise HTTPException(
                        status_code=500,
                        detail=f"Video download failed: {download_status_info['message']}",
                    )
                else:
                    download_executor.submit(
                        download_video_background,
                        video_id,
                        f"https://www.youtube.com/watch?v={video_id}",
                        current_user["uid"],
                    )
                    return {
                        "response": "🎬 Something amazing is being loaded! Video download has started in the background. Please continue to chat with the video content in the meantime, and try frame-specific questions again in a moment!",
                        "video_id": video_id,
                        "timestamp": timestamp,
                        "query_type": "downloading",
                        "is_downloading": True,
                    }
            frame_filename = f"frame_{video_id}_{int(timestamp)}.jpg"
            frame_path = os.path.join(frames_path, frame_filename)
            output_file, frame = grab_youtube_frame(
                video_path_local, timestamp, frame_path
            )
            if not output_file:
                raise HTTPException(status_code=500, detail="Frame extraction failed")
            response = vision_client.ask_with_image(
                query, frame_path, transcript_to_use
            )
        else:
            response = vision_client.ask_text_only(query, transcript_to_use)
        return {
            "response": response,
            "video_id": video_id,
            "timestamp": timestamp,
            "query_type": "image" if is_image_query else "text",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to process query: {str(e)}"
        )
