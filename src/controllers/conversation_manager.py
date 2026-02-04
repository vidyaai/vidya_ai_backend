"""
Conversation Manager - Handles persistent storage and retrieval of chat sessions
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from models import Video
from controllers.config import logger


def store_conversation_turn(
    db: Session,
    video_id: str,
    user_id: str,
    firebase_uid: str,
    user_message: str,
    ai_response: str,
    timestamp: Optional[float],
    session_id: Optional[str] = None
) -> str:
    """
    Store a conversation turn (user question + AI response) in the database.

    Args:
        db: Database session
        video_id: YouTube video ID
        user_id: Internal user ID
        firebase_uid: Firebase user UID
        user_message: User's question
        ai_response: AI's response
        timestamp: Video timestamp (optional)
        session_id: Chat session ID (optional, will create new if not provided)

    Returns:
        str: The session_id used (either provided or newly created)
    """
    try:
        # Get or create video record
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            logger.warning(f"Video {video_id} not found, cannot store conversation")
            return session_id or ""

        # Get existing chat sessions or initialize empty list
        chat_sessions = video.chat_sessions or []

        # Find or create active session
        active_session = None
        if session_id:
            # Look for existing session with this ID
            active_session = next((s for s in chat_sessions if s.get("id") == session_id), None)
        else:
            # Get most recent session for this user
            user_sessions = [s for s in chat_sessions if s.get("user_id") == firebase_uid]
            if user_sessions:
                # Use the most recently updated session
                user_sessions.sort(key=lambda x: x.get("updatedAt", ""), reverse=True)
                active_session = user_sessions[0]

        # Create new session if needed
        if not active_session:
            new_session_id = str(uuid.uuid4())
            active_session = {
                "id": new_session_id,
                "user_id": firebase_uid,
                "title": f"Chat {datetime.now().strftime('%b %d, %I:%M %p')}",
                "messages": [],
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat()
            }
            chat_sessions.append(active_session)
            session_id = new_session_id
            logger.info(f"Created new chat session {new_session_id} for video {video_id}")
        else:
            session_id = active_session.get("id")

        # Add user message and AI response
        messages = active_session.get("messages", [])

        # User message
        messages.append({
            "role": "user",
            "content": user_message,
            "timestamp": timestamp
        })

        # AI response
        messages.append({
            "role": "assistant",
            "content": ai_response,
            "timestamp": timestamp
        })

        # Keep only last 50 messages to prevent database bloat
        active_session["messages"] = messages[-50:]
        active_session["updatedAt"] = datetime.now(timezone.utc).isoformat()

        # Update video record
        video.chat_sessions = chat_sessions
        db.add(video)
        db.commit()

        logger.info(f"Stored conversation turn in session {session_id} for video {video_id}")
        return session_id

    except Exception as e:
        logger.error(f"Error storing conversation turn: {e}")
        db.rollback()
        return session_id or ""


def get_merged_conversation_history(
    db: Session,
    video_id: str,
    firebase_uid: str,
    session_id: Optional[str],
    client_history: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Retrieve conversation history from database and merge with client-sent history.
    Database is the source of truth; client history is used as fallback.

    Args:
        db: Database session
        video_id: YouTube video ID
        firebase_uid: Firebase user UID
        session_id: Chat session ID (optional)
        client_history: Conversation history sent from client

    Returns:
        List[Dict]: Conversation history in OpenAI message format (last 20 messages)
    """
    try:
        # Get video record
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video or not video.chat_sessions:
            logger.info(f"No chat sessions found for video {video_id}, using client history")
            return client_history

        # Find the active session
        active_session = None
        if session_id:
            # Look for session with specific ID
            active_session = next((s for s in video.chat_sessions if s.get("id") == session_id), None)
        else:
            # Get most recent session for this user
            user_sessions = [s for s in video.chat_sessions if s.get("user_id") == firebase_uid]
            if user_sessions:
                user_sessions.sort(key=lambda x: x.get("updatedAt", ""), reverse=True)
                active_session = user_sessions[0]

        if not active_session:
            logger.info(f"No matching session found for video {video_id}, using client history")
            return client_history

        # Get messages from database (last 20 for context window)
        db_messages = active_session.get("messages", [])[-20:]

        # Convert to OpenAI format
        formatted_messages = []
        for msg in db_messages:
            formatted_messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
                "timestamp": msg.get("timestamp")
            })

        logger.info(f"Retrieved {len(formatted_messages)} messages from session {active_session.get('id')} for video {video_id}")
        return formatted_messages if formatted_messages else client_history

    except Exception as e:
        logger.error(f"Error retrieving conversation history: {e}")
        # Fall back to client history on error
        return client_history
