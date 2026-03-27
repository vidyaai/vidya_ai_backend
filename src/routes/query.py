from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import os
import json
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
from utils.cache import (
    get_cached_query_embedding,
    cache_query_embedding,
    get_cached_rag_results,
    cache_rag_results,
)

# from utils.youtube_frame_capturer import capture_youtube_frame  # Disabled - YouTube frame capture not working
from utils.ml_models import OpenAIVisionClient
from utils.context_extraction import extract_relevant_context, truncate_to_token_limit
from schemas import VideoQuery
from utils.firebase_auth import get_current_user
from models import User, Video, VideoSummary, TranscriptChunk
from services.summary_service import SummaryService, QueryRouter
from utils.text_utils import normalize_ai_response


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

        # Check if chunks are available for RAG
        chunks_available = (
            db.query(TranscriptChunk)
            .filter(TranscriptChunk.video_id == video_id)
            .count()
            > 0
        )

        # Default fallback: Use smart extraction instead of full transcript
        if not chunks_available and not video_summary and transcript_to_use:
            context_for_llm = extract_relevant_context(
                transcript_to_use, query, max_tokens=3000
            )
            retrieval_strategy = "fallback_extraction"
            logger.info(f"Using fallback extraction (no chunks/summary available yet)")
        else:
            context_for_llm = transcript_to_use  # Original fallback
            retrieval_strategy = "full_transcript"

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
                    # Fallback: Use smart keyword extraction when chunks not available
                    logger.warning(
                        f"No chunks available for video {video_id}, using smart extraction fallback"
                    )
                    context_for_llm = extract_relevant_context(
                        transcript_to_use, query, max_tokens=3000
                    )
                    retrieval_strategy = "fallback_extraction"

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

        # Normalize AI response for consistent frontend rendering
        logger.info(f"📝 BEFORE normalization (first 300 chars): {response[:300]}")
        logger.info(f"📝 BEFORE normalization (repr): {repr(response[:150])}")
        response = normalize_ai_response(response)
        logger.info(f"📝 AFTER normalization (first 300 chars): {response[:300]}")
        logger.info(f"📝 AFTER normalization (repr): {repr(response[:150])}")

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


@router.post("/video/stream")
async def process_query_stream(
    query_request: VideoQuery,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Stream AI responses word-by-word for better UX.

    Returns Server-Sent Events (SSE) with JSON chunks:
    - {"type": "metadata", "data": {"used_web_search": bool, "sources": []}}
    - {"type": "content", "data": "text chunk"}
    - {"type": "done"}
    """

    async def generate_stream():
        try:
            video_id = query_request.video_id
            query = query_request.query
            timestamp = query_request.timestamp
            is_image_query = query_request.is_image_query

            # Get user from database
            user = (
                db.query(User).filter(User.firebase_uid == current_user["uid"]).first()
            )
            if not user:
                user = User(
                    firebase_uid=current_user["uid"],
                    email=current_user.get("email"),
                    name=current_user.get("name"),
                )
                db.add(user)
                db.commit()
                db.refresh(user)

            # Check daily question limit
            usage_check = check_usage_limits(
                db, user.id, "question_per_video", video_id=video_id
            )
            if not usage_check["allowed"]:
                subscription = get_user_subscription(db, user.id)
                plan_name = (
                    subscription.plan.name
                    if subscription and subscription.plan
                    else "Free"
                )

                error_msg = {
                    "type": "error",
                    "data": {
                        "error": "limit_reached",
                        "message": usage_check["reason"],
                        "current_plan": plan_name,
                    },
                }
                yield f"data: {json.dumps(error_msg)}\n\n"
                return

            vision_client = OpenAIVisionClient()

            # Get conversation history (with caching optimization)
            conversation_context = get_merged_conversation_history(
                db=db,
                video_id=video_id,
                firebase_uid=current_user["uid"],
                session_id=query_request.session_id,
                client_history=query_request.conversation_history or [],
            )

            # Get transcript (with caching)
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

            # Initialize services
            summary_service = SummaryService()
            query_router = QueryRouter()

            # Check if summary exists (trigger generation if missing)
            video_summary = summary_service.get_summary(db, video_id)
            if not video_summary and transcript_to_use:
                logger.info(f"[STREAM] No summary, triggering background generation")
                download_executor.submit(
                    generate_summary_background, video_id, transcript_to_use
                )

            # Classify query type
            query_type = query_router.classify_query(query)
            logger.info(f"[STREAM] Query classified as: {query_type}")

            # Build context based on query type (uses caching)
            chunks_available = (
                db.query(TranscriptChunk)
                .filter(TranscriptChunk.video_id == video_id)
                .count()
                > 0
            )

            if not chunks_available and not video_summary and transcript_to_use:
                context_for_llm = extract_relevant_context(
                    transcript_to_use, query, max_tokens=3000
                )
                retrieval_strategy = "fallback_extraction"
            else:
                context_for_llm = transcript_to_use

            if video_summary:
                if query_type == "broad":
                    context_for_llm = query_router.build_context_from_summary(
                        video_summary
                    )
                    retrieval_strategy = "summary_only"
                elif query_type == "hybrid":
                    context_for_llm = query_router.build_hybrid_context(
                        db, video_id, query, video_summary, transcript_to_use
                    )
                    retrieval_strategy = "hybrid_semantic"
                elif query_type == "specific":
                    semantic_context = query_router.build_semantic_context(
                        db, video_id, query, top_k=5
                    )
                    if semantic_context:
                        context_for_llm = semantic_context
                        retrieval_strategy = "semantic_chunks"
                    else:
                        context_for_llm = extract_relevant_context(
                            transcript_to_use, query, max_tokens=3000
                        )
                        retrieval_strategy = "fallback_extraction"

            # Check question relevance
            video_record = db.query(Video).filter(Video.id == video_id).first()
            video_title = video_record.title if video_record else ""

            relevance_check = vision_client.check_question_relevance(
                question=query,
                transcript_excerpt=transcript_to_use[:1000]
                if transcript_to_use
                else "",
                video_title=video_title,
                conversation_history=conversation_context,
            )

            if (
                not relevance_check.get("is_relevant", True)
                and relevance_check.get("confidence", 0) > 0.7
            ):
                redirect_msg = {
                    "type": "content",
                    "data": relevance_check.get(
                        "suggested_redirect",
                        "I'm here to help you understand this specific video. Could you ask about something from the video content?",
                    ),
                }
                yield f"data: {json.dumps(redirect_msg)}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

            # Image queries not supported for streaming (rare case)
            if is_image_query:
                error_msg = {
                    "type": "error",
                    "data": "Streaming not supported for image queries",
                }
                yield f"data: {json.dumps(error_msg)}\n\n"
                return

            # Stream the response!
            full_response = ""
            for chunk_json in vision_client.ask_with_web_augmentation_stream(
                prompt=query,
                context=context_for_llm,
                conversation_history=conversation_context,
                video_title=video_title,
                enable_search=True,
            ):
                yield f"data: {chunk_json}\n\n"

                # Collect full response for storage
                try:
                    chunk_data = json.loads(chunk_json)
                    if chunk_data.get("type") == "content":
                        full_response += chunk_data.get("data", "")
                except:
                    pass

            # Store conversation turn in database
            if full_response:
                from utils.text_utils import normalize_ai_response

                full_response = normalize_ai_response(full_response)

                store_conversation_turn(
                    db=db,
                    video_id=video_id,
                    user_id=user.id,
                    firebase_uid=current_user["uid"],
                    user_message=query,
                    ai_response=full_response,
                    timestamp=timestamp,
                    session_id=query_request.session_id,
                )

            # Increment usage
            increment_usage(db, user.id, "question_per_video", 1, video_id=video_id)

        except Exception as e:
            logger.error(f"[STREAM] Error: {e}")
            error_msg = {"type": "error", "data": str(e)}
            yield f"data: {json.dumps(error_msg)}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
