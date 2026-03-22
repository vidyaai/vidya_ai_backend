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
from controllers.background_tasks import (
    download_video_background,
    generate_summary_background,
)
from controllers.config import frames_path, download_executor, logger
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

# from utils.youtube_frame_capturer import capture_youtube_frame  # Disabled - YouTube frame capture not working
from utils.ml_models import OpenAIVisionClient
from schemas import VideoQuery
from utils.firebase_auth import get_current_user
from models import User, Video, VideoSummary
from services.summary_service import SummaryService, QueryRouter


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

        # Get full transcript (needed for summary generation and specific queries)
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

        # Initialize services for Phase 2: Hierarchical Summaries
        summary_service = SummaryService()
        query_router = QueryRouter()

        # Check if summary exists
        video_summary = summary_service.get_summary(db, video_id)

        # If no summary exists, trigger background generation
        if not video_summary and transcript_to_use:
            logger.info(
                f"No summary found for video {video_id}, triggering background generation"
            )
            download_executor.submit(
                generate_summary_background, video_id, transcript_to_use
            )

        # Classify query type for intelligent routing
        query_type = query_router.classify_query(query)
        logger.info(f"Query classified as: {query_type}")

        # Build context based on query type and summary availability
        # Phase 1+2 Combined: Uses both semantic chunks and hierarchical summaries
        context_for_llm = transcript_to_use  # Default fallback
        retrieval_strategy = "full_transcript"  # Default

        if video_summary:
            if query_type == "broad":
                # Use summary only for broad questions (80-90% token reduction)
                context_for_llm = query_router.build_context_from_summary(video_summary)
                retrieval_strategy = "summary_only"
                logger.info(
                    f"Using summary-only context ({len(context_for_llm)} chars vs {len(transcript_to_use)} chars)"
                )

            elif query_type == "hybrid":
                # Phase 1+2: Use summary + semantic chunks for hybrid queries
                context_for_llm = query_router.build_hybrid_context(
                    db, video_id, query, video_summary, transcript_to_use
                )
                retrieval_strategy = "hybrid_semantic"
                logger.info(f"Using hybrid context (summary + top-3 semantic chunks)")

            elif query_type == "specific":
                # Phase 1: Use semantic chunk retrieval for specific queries
                semantic_context = query_router.build_semantic_context(
                    db, video_id, query, top_k=5
                )
                if semantic_context:
                    context_for_llm = semantic_context
                    retrieval_strategy = "semantic_chunks"
                    logger.info(
                        f"Using semantic chunks context (top-5 relevant chunks)"
                    )
                else:
                    # Fallback to full transcript if no chunks available yet
                    logger.warning(
                        f"No chunks available for video {video_id}, using full transcript"
                    )

        # Check if question is relevant to video content
        video_record = db.query(Video).filter(Video.id == video_id).first()
        video_title = video_record.title if video_record else ""

        relevance_check = vision_client.check_question_relevance(
            question=query,
            transcript_excerpt=transcript_to_use[:1000] if transcript_to_use else "",
            video_title=video_title,
            conversation_history=conversation_context,  # Pass conversation history for context
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
            # YouTube image queries disabled - video download not working
            if video_record and video_record.source_type == "youtube":
                raise HTTPException(
                    status_code=400,
                    detail="Image queries are not supported for YouTube videos. Please ask questions based on the transcript instead.",
                )

            if timestamp is None:
                raise HTTPException(
                    status_code=400, detail="Timestamp is required for image queries"
                )

            # Only for non-YouTube videos (uploaded videos)
            video_path_local = get_video_path(db, video_id)
            if not video_path_local:
                raise HTTPException(
                    status_code=400, detail="Video not available for frame extraction"
                )

            # Extract frame from local video
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
            web_sources = []
            used_web_search = False
        else:
            # Use web-augmented answering for text queries with intelligent context
            web_result = vision_client.ask_with_web_augmentation(
                prompt=query,
                context=context_for_llm,  # Use intelligent context instead of full transcript
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
            "retrieval_strategy": retrieval_strategy,  # For analytics
            "classified_query_type": query_type,  # For analytics
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to process query: {str(e)}"
        )
