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
from controllers.subscription_service import (
    check_usage_limits,
    increment_usage,
    get_user_subscription,
)
from controllers.conversation_manager import (
    store_conversation_turn,
    get_merged_conversation_history,
)
from utils.youtube_utils import download_transcript_api, grab_youtube_frame
from utils.ml_models import OpenAIVisionClient
from schemas import VideoQuery
from utils.firebase_auth import get_current_user
from models import User, Video


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

        # Get user from database to get internal user_id
        user = db.query(User).filter(User.firebase_uid == current_user["uid"]).first()
        if not user:
            # Create user if doesn't exist
            user = User(
                firebase_uid=current_user["uid"],
                email=current_user.get("email"),
                name=current_user.get("name"),
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        # Check daily question limit for this specific video
        usage_check = check_usage_limits(
            db, user.id, "question_per_video", video_id=video_id
        )
        if not usage_check["allowed"]:
            # Get subscription info for upgrade message
            subscription = get_user_subscription(db, user.id)
            plan_name = (
                subscription.plan.name if subscription and subscription.plan else "Free"
            )

            raise HTTPException(
                status_code=429,
                detail={
                    "error": "limit_reached",
                    "message": usage_check["reason"],
                    "limit": usage_check.get("limit"),
                    "current": usage_check.get("current"),
                    "current_plan": plan_name,
                    "upgrade_url": "/pricing",
                },
            )

        vision_client = OpenAIVisionClient()

        # Get merged conversation history from database (source of truth)
        conversation_context = get_merged_conversation_history(
            db=db,
            video_id=video_id,
            firebase_uid=current_user["uid"],
            session_id=query_request.session_id,
            client_history=query_request.conversation_history or [],
        )

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

        # Check if question is relevant to video content
        video_record = db.query(Video).filter(Video.id == video_id).first()
        video_title = video_record.title if video_record else ""

        relevance_check = vision_client.check_question_relevance(
            question=query,
            transcript_excerpt=transcript_to_use[:1000] if transcript_to_use else "",
            video_title=video_title,
        )

        # If question is clearly off-topic, provide gentle redirect
        if (
            not relevance_check.get("is_relevant", True)
            and relevance_check.get("confidence", 0) > 0.7
        ):
            # Don't increment usage for off-topic questions
            return {
                "response": relevance_check.get(
                    "suggested_redirect",
                    "I'm here to help you understand this specific video. Could you ask about something from the video content?",
                ),
                "video_id": video_id,
                "timestamp": timestamp,
                "query_type": "redirect",
                "is_off_topic": True,
            }

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
                query, frame_path, transcript_to_use, conversation_context
            )
            # Image queries don't use web search currently
            web_sources = []
            used_web_search = False
        else:
            # Use web-augmented answering for text queries
            web_result = vision_client.ask_with_web_augmentation(
                prompt=query,
                context=transcript_to_use,
                conversation_history=conversation_context,
                video_title=video_title,
                enable_search=True,  # Can be controlled via user settings
            )
            response = web_result["response"]
            web_sources = web_result.get("sources", [])
            used_web_search = web_result.get("used_web_search", False)

        # Store conversation turn in database
        session_id_used = store_conversation_turn(
            db=db,
            video_id=video_id,
            user_id=user.id,
            firebase_uid=current_user["uid"],
            user_message=query,
            ai_response=response,
            timestamp=timestamp,
            session_id=query_request.session_id,
        )

        # Increment question count for this video
        increment_usage(db, user.id, "question_per_video", 1, video_id=video_id)

        return {
            "response": response,
            "video_id": video_id,
            "timestamp": timestamp,
            "query_type": "image" if is_image_query else "text",
            "web_sources": web_sources,
            "used_web_search": used_web_search,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to process query: {str(e)}"
        )
