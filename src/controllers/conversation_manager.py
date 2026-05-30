"""
Conversation Manager - Handles persistent storage and retrieval of chat sessions
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from models import Video, MaterialChatSession, MaterialChatMessage
from controllers.config import logger


def store_conversation_turn(
    db: Session,
    video_id: str,
    user_id: str,
    firebase_uid: str,
    user_message: str,
    ai_response: str,
    timestamp: Optional[float],
    session_id: Optional[str] = None,
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
            active_session = next(
                (s for s in chat_sessions if s.get("id") == session_id), None
            )
        else:
            # Get most recent session for this user
            user_sessions = [
                s for s in chat_sessions if s.get("user_id") == firebase_uid
            ]
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
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
            chat_sessions.append(active_session)
            session_id = new_session_id
            logger.info(
                f"Created new chat session {new_session_id} for video {video_id}"
            )
        else:
            session_id = active_session.get("id")

        # Add user message and AI response
        messages = active_session.get("messages", [])

        # User message
        messages.append(
            {"role": "user", "content": user_message, "timestamp": timestamp}
        )

        # AI response
        messages.append(
            {"role": "assistant", "content": ai_response, "timestamp": timestamp}
        )

        # Keep only last 50 messages to prevent database bloat
        active_session["messages"] = messages[-50:]
        active_session["updatedAt"] = datetime.now(timezone.utc).isoformat()

        # Update video record
        video.chat_sessions = chat_sessions
        db.add(video)
        db.commit()

        logger.info(
            f"Stored conversation turn in session {session_id} for video {video_id}"
        )
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
    client_history: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Retrieve conversation history from database ONLY (OPTIMIZED).
    Database is the ONLY source of truth; client history is IGNORED.

    OPTIMIZATION: Only selects chat_sessions column instead of full Video record.

    Args:
        db: Database session
        video_id: YouTube video ID
        firebase_uid: Firebase user UID
        session_id: Chat session ID (optional)
        client_history: Conversation history sent from client (IGNORED - for backward compatibility)

    Returns:
        List[Dict]: Conversation history in OpenAI message format (last 20 messages)
    """
    try:
        # OPTIMIZED: Only load chat_sessions column (not entire Video row)
        # Reduces load time from 80-180ms to 15-30ms
        result = db.query(Video.chat_sessions).filter(Video.id == video_id).first()

        if not result or not result[0]:
            logger.info(
                f"No chat sessions found for video {video_id}, returning empty history"
            )
            return []  # Return empty list, ignore client history

        chat_sessions = result[0]

        # Find the active session
        active_session = None
        if session_id:
            # Look for session with specific ID
            active_session = next(
                (s for s in chat_sessions if s.get("id") == session_id), None
            )
        else:
            # Get most recent session for this user
            user_sessions = [
                s for s in chat_sessions if s.get("user_id") == firebase_uid
            ]
            if user_sessions:
                user_sessions.sort(key=lambda x: x.get("updatedAt", ""), reverse=True)
                active_session = user_sessions[0]

        if not active_session:
            logger.info(
                f"No matching session found for video {video_id}, returning empty history"
            )
            return []  # Return empty list, ignore client history

        # Get messages from database (last 20 for context window)
        db_messages = active_session.get("messages", [])[-20:]

        # DEBUG: Log first message to see structure
        if db_messages:
            logger.info(f"DEBUG: First db_message: {db_messages[0]}")
            logger.info(
                f"DEBUG: Message keys: {db_messages[0].keys() if isinstance(db_messages[0], dict) else 'Not a dict'}"
            )

        # Convert to OpenAI format
        # Handle both formats: frontend sends {sender, text}, backend stores {role, content}
        formatted_messages = []
        for msg in db_messages:
            # Try both field names for compatibility
            role = msg.get("role") or msg.get("sender", "user")
            content = msg.get("content") or msg.get("text", "")

            # Map frontend role names to OpenAI role names
            # Frontend uses "ai", OpenAI expects "assistant"
            if role == "ai":
                role = "assistant"

            formatted_messages.append(
                {
                    "role": role,
                    "content": content,
                    "timestamp": msg.get("timestamp"),
                }
            )

        logger.info(
            f"Retrieved {len(formatted_messages)} messages from session {active_session.get('id')} for video {video_id}"
        )
        return formatted_messages  # Return whatever we got from DB (even if empty)

    except Exception as e:
        logger.error(f"Error retrieving conversation history: {e}")
        # Return empty list on error - do NOT use client history
        return []


# ── Per-CourseMaterial chat persistence ─────────────────────────────────


def _derive_session_title(first_user_message: str, max_chars: int = 48) -> str:
    """Build a human-readable session title from the first user message.

    Mirrors the gallery's pattern of showing past chats by their opening
    question instead of by timestamp.
    """
    text = (first_user_message or "").strip().replace("\n", " ")
    if not text:
        return f"Chat {datetime.now().strftime('%b %d, %I:%M %p')}"
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def store_material_conversation_turn(
    db: Session,
    course_material_id: str,
    firebase_uid: str,
    user_message: str,
    ai_response: str,
    citations: Optional[List[Dict[str, Any]]] = None,
    timestamp_seconds: Optional[float] = None,
    session_id: Optional[str] = None,
) -> str:
    """
    Append a user turn + assistant turn to a MaterialChatSession.

    If session_id is provided AND it belongs to (course_material_id,
    firebase_uid), reuse it. Otherwise — even if the user has earlier
    sessions for this material — create a *new* session. That's what
    the frontend's "New chat" button expects: clearing the active
    session id and sending the next message starts a fresh thread.

    Returns the session_id used (string).
    """
    try:
        session: Optional[MaterialChatSession] = None
        if session_id:
            session = (
                db.query(MaterialChatSession)
                .filter(
                    MaterialChatSession.id == session_id,
                    MaterialChatSession.course_material_id == course_material_id,
                    MaterialChatSession.user_id == firebase_uid,
                )
                .first()
            )

        is_new_session = session is None
        if is_new_session:
            session = MaterialChatSession(
                course_material_id=course_material_id,
                user_id=firebase_uid,
                title=_derive_session_title(user_message),
            )
            db.add(session)
            db.flush()  # populate session.id

        db.add(
            MaterialChatMessage(
                session_id=session.id,
                role="user",
                content=user_message,
                timestamp_seconds=timestamp_seconds,
            )
        )
        db.add(
            MaterialChatMessage(
                session_id=session.id,
                role="assistant",
                content=ai_response,
                citations=citations,
                timestamp_seconds=timestamp_seconds,
            )
        )

        session.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(
            f"Stored material chat turn in session {session.id} for material {course_material_id}"
        )
        return session.id

    except Exception as e:
        logger.error(f"Error storing material conversation turn: {e}")
        db.rollback()
        return session_id or ""


def get_merged_material_conversation_history(
    db: Session,
    session_id: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    Load up to `limit` most recent messages for a MaterialChatSession,
    returned in chronological order as OpenAI-style {role, content} dicts.

    Database is the only source of truth — no client-supplied history is merged.
    """
    try:
        rows = (
            db.query(MaterialChatMessage)
            .filter(MaterialChatMessage.session_id == session_id)
            .order_by(MaterialChatMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        rows.reverse()  # chronological
        return [{"role": r.role, "content": r.content} for r in rows]
    except Exception as e:
        logger.error(f"Error retrieving material conversation history: {e}")
        return []
