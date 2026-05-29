"""
Per-CourseMaterial chat endpoints.

Ported from src/routes/query.py but anchored to CourseMaterial (course
videos + lecture-note PDFs) instead of a standalone Video. Sessions and
messages live in dedicated tables (material_chat_sessions /
material_chat_messages); the existing Video.chat_sessions JSONB and
/api/query/video remain untouched.
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from controllers.config import logger
from controllers.conversation_manager import (
    get_merged_material_conversation_history,
    store_material_conversation_turn,
)
from models import (
    Course,
    CourseEnrollment,
    CourseMaterial,
    MaterialChatMessage,
    MaterialChatSession,
    MaterialChunk,
    TranscriptChunk,
)
from schemas import (
    MaterialChatMessageOut,
    MaterialChatQuery,
    MaterialChatQueryResponse,
    MaterialChatSessionCreate,
    MaterialChatSessionOut,
    MaterialChatSessionRename,
)
from openai import OpenAI
from services.chunking_embedding_service import EmbeddingService
from utils.db import get_db
from utils.firebase_auth import get_current_user
from utils.text_utils import normalize_ai_response


router = APIRouter(prefix="/api/material-chat", tags=["Material Chat"])


# ── Source-aware system prompt ──────────────────────────────────────────
#
# The Chat-with-Video product (utils/system_prompt.py) hard-codes "video"
# everywhere — using it for a PDF makes the model say "the video explains…"
# even when it's looking at lecture notes. Build a small, material-type-
# aware prompt here so PDFs read as documents and lectures read as videos.

_SHARED_STYLE = """
**Be conversational and warm:**
- Talk like a real person, use contractions, show enthusiasm.
- Encouraging and supportive, never robotic.

**Response style:**
- Open with a brief, friendly acknowledgement.
- Explain in clear, simple language; use examples and analogies.
- Bold key terms. Bullets for lists.
- Use emojis sparingly — at most one per response.

**Math and technical content:**
- Use LaTeX ONLY: \\( inline \\) and \\[ display \\]. NEVER HTML or MathML.
- Always explain what the equation means in plain English first.

**Stay grounded in the source:**
- Use the provided context as your source of truth.
- If the question is off-topic, gently redirect to what the source covers.
- If the source doesn't cover the question, say so honestly — don't invent.
"""

_SYSTEM_PROMPT_DOC = (
    "You are a friendly, enthusiastic tutor helping a student understand a "
    "document they're reading (lecture notes, a PDF chapter, or similar). "
    "Reference the material as 'the document', 'these notes', or 'this PDF' — "
    "never as a video or lecture recording.\n"
    + _SHARED_STYLE
)

_SYSTEM_PROMPT_VIDEO = (
    "You are a friendly, enthusiastic tutor helping a student understand a "
    "lecture video they're watching. The provided context is the lecture "
    "transcript. Reference the material as 'the lecture' or 'the video'.\n"
    + _SHARED_STYLE
)


def _system_prompt_for(material_type: str) -> str:
    return _SYSTEM_PROMPT_VIDEO if material_type == "video" else _SYSTEM_PROMPT_DOC


def _build_messages(
    material_type: str,
    context_text: str,
    query: str,
    history: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": _system_prompt_for(material_type)},
    ]
    for msg in history or []:
        if isinstance(msg, dict) and "role" in msg and "content" in msg:
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append(
        {
            "role": "user",
            "content": f"Context from the source:\n{context_text}\n\nQuestion: {query}",
        }
    )
    return messages


# ── Access control ──────────────────────────────────────────────────────


def _user_can_access_material(
    db: Session, user_uid: str, material_id: str
) -> CourseMaterial:
    """Return the CourseMaterial if user_uid is owner or active enrollee, else 4xx."""
    material = (
        db.query(CourseMaterial).filter(CourseMaterial.id == material_id).first()
    )
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")

    course = db.query(Course).filter(Course.id == material.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    if course.user_id == user_uid:
        return material

    enrolled = (
        db.query(CourseEnrollment)
        .filter(
            CourseEnrollment.course_id == material.course_id,
            CourseEnrollment.user_id == user_uid,
            CourseEnrollment.status == "active",
        )
        .first()
    )
    if not enrolled:
        raise HTTPException(
            status_code=403, detail="Not authorized to access this material"
        )
    return material


def _owned_session_or_403(
    db: Session, user_uid: str, session_id: str
) -> MaterialChatSession:
    """Return the session if user_uid is its owner. 404 if missing, 403 if not theirs."""
    session = (
        db.query(MaterialChatSession)
        .filter(MaterialChatSession.id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != user_uid:
        raise HTTPException(status_code=403, detail="Not your session")
    return session


# ── Retrieval ──────────────────────────────────────────────────────────


def _retrieve_context(
    db: Session, material: CourseMaterial, query: str
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Pull top-k chunks for the material and format them for the LLM.

    For video materials with a linked Video row, retrieve from TranscriptChunk
    (existing embeddings populated by the Chat-with-Video pipeline).
    For PDF/DOCX materials, retrieve from MaterialChunk (populated by
    chunk_pdf_material_background).

    Returns (context_text, citations).
    """
    embedder = EmbeddingService()
    q_emb = embedder.embed_text(query)

    candidates: List[Dict[str, Any]] = []
    cache_key: str

    if material.material_type == "video" and material.video_id:
        rows = (
            db.query(TranscriptChunk)
            .filter(TranscriptChunk.video_id == material.video_id)
            .all()
        )
        candidates = [
            {
                "text": r.text,
                "embedding": r.embedding,
                "chunk_index": r.chunk_index,
                "start_seconds": r.start_seconds,
                "end_seconds": r.end_seconds,
            }
            for r in rows
        ]
        cache_key = f"video:{material.video_id}"
    else:
        rows = (
            db.query(MaterialChunk)
            .filter(MaterialChunk.course_material_id == material.id)
            .all()
        )
        candidates = [
            {
                "text": r.text,
                "embedding": r.embedding,
                "chunk_index": r.chunk_index,
                "page_number": r.page_number,
                "start_seconds": r.start_seconds,
                "end_seconds": r.end_seconds,
            }
            for r in rows
        ]
        cache_key = f"material:{material.id}"

    if not candidates:
        return "", []

    top = embedder.hybrid_search(
        query=query,
        query_embedding=q_emb,
        candidates=candidates,
        top_k=5,
        cache_key=cache_key,
    )

    # Keep the LLM context in retrieval-ranking order (best chunks first
    # are more likely to fit inside the model's attention budget).
    # For video chunks, prefix each with an [MM:SS] marker so the LLM
    # naturally weaves clickable timestamps into its prose — the
    # frontend's parseMarkdownWithMath turns any MM:SS into a button.
    def _fmt_timestamp_prefix(c: Dict[str, Any]) -> str:
        s = c.get("start_seconds")
        if s is None:
            return ""
        total = int(s)
        m, sec = divmod(total, 60)
        h = m // 60
        m = m % 60
        return f"[{h:02d}:{m:02d}:{sec:02d}] " if h else f"[{m:02d}:{sec:02d}] "

    context_text = "\n\n".join(
        f"{_fmt_timestamp_prefix(c)}[{c.get('chunk_index')}] {c.get('text', '')}"
        for c in top
    )

    citations: List[Dict[str, Any]] = []
    for c in top:
        citation = {"chunk_index": c.get("chunk_index")}
        for k in ("page_number", "start_seconds", "end_seconds"):
            v = c.get(k)
            if v is not None:
                citation[k] = v
        citations.append(citation)

    # Surface citations in *document* order — users read them as "where to
    # look in the source", not "how relevant each is". Sort by page (PDFs),
    # then start_seconds (videos), then chunk_index as a stable fallback.
    citations.sort(
        key=lambda c: (
            c.get("page_number") if c.get("page_number") is not None else float("inf"),
            c.get("start_seconds") if c.get("start_seconds") is not None else float("inf"),
            c.get("chunk_index") if c.get("chunk_index") is not None else float("inf"),
        )
    )
    return context_text, citations


def _processing_message(material: CourseMaterial) -> Optional[str]:
    """If retrieval has no content because the material is still being processed,
    return a user-friendly message; otherwise None."""
    if material.material_type == "video":
        if (material.transcript_status or "").lower() in ("pending", "processing"):
            return (
                "This video is still being transcribed. Please try again in a "
                "few minutes."
            )
    else:
        status = (material.chunking_status or "").lower()
        if status in ("pending", "processing"):
            return (
                "This document is still being indexed. Please try again in a "
                "few minutes."
            )
        if status == "failed":
            return (
                "We couldn't index this document for chat. Please re-upload or "
                "contact support."
            )
    return None


# ── Endpoints: query ────────────────────────────────────────────────────


@router.post("/query", response_model=MaterialChatQueryResponse)
async def query_material(
    body: MaterialChatQuery,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> MaterialChatQueryResponse:
    material = _user_can_access_material(db, current_user["uid"], body.material_id)

    context_text, citations = _retrieve_context(db, material, body.query)

    if not context_text:
        msg = _processing_message(material)
        if msg:
            return MaterialChatQueryResponse(
                response=msg, session_id=body.session_id or "", citations=[]
            )

    history: List[Dict[str, Any]] = []
    if body.session_id:
        history = get_merged_material_conversation_history(db, body.session_id)

    messages = _build_messages(material.material_type, context_text, body.query, history)
    client = OpenAI()
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=1500,
        temperature=0.3,
    )
    ai_response = completion.choices[0].message.content or ""
    ai_response = normalize_ai_response(ai_response) if ai_response else ""

    session_id = store_material_conversation_turn(
        db=db,
        course_material_id=material.id,
        firebase_uid=current_user["uid"],
        user_message=body.query,
        ai_response=ai_response,
        citations=citations,
        session_id=body.session_id,
    )

    return MaterialChatQueryResponse(
        response=ai_response, session_id=session_id, citations=citations
    )


@router.post("/query/stream")
async def query_material_stream(
    body: MaterialChatQuery,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Stream the assistant response as SSE.

    Frames:
      data: {"type": "metadata", "data": {"citations": [...], "session_id": "..."}}
      data: {"type": "content",  "data": "..."}     # repeated
      data: {"type": "done"}
    """

    async def generate_stream():
        try:
            material = _user_can_access_material(
                db, current_user["uid"], body.material_id
            )

            context_text, citations = _retrieve_context(db, material, body.query)

            if not context_text:
                msg = _processing_message(material)
                if msg:
                    yield (
                        "data: "
                        + json.dumps({"type": "content", "data": msg})
                        + "\n\n"
                    )
                    yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                    return

            history: List[Dict[str, Any]] = []
            if body.session_id:
                history = get_merged_material_conversation_history(db, body.session_id)

            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "metadata",
                        "data": {
                            "citations": citations,
                            "session_id": body.session_id,
                        },
                    }
                )
                + "\n\n"
            )

            messages = _build_messages(
                material.material_type, context_text, body.query, history
            )
            client = OpenAI()
            stream = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=1500,
                temperature=0.3,
                stream=True,
            )
            full_response = ""
            for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if not delta:
                    continue
                full_response += delta
                yield (
                    "data: "
                    + json.dumps({"type": "content", "data": delta})
                    + "\n\n"
                )

            if full_response:
                full_response = normalize_ai_response(full_response)
                session_id = store_material_conversation_turn(
                    db=db,
                    course_material_id=material.id,
                    firebase_uid=current_user["uid"],
                    user_message=body.query,
                    ai_response=full_response,
                    citations=citations,
                    session_id=body.session_id,
                )
                yield (
                    "data: "
                    + json.dumps(
                        {"type": "session", "data": {"session_id": session_id}}
                    )
                    + "\n\n"
                )

            yield "data: " + json.dumps({"type": "done"}) + "\n\n"

        except HTTPException as e:
            yield (
                "data: "
                + json.dumps({"type": "error", "data": e.detail})
                + "\n\n"
            )
        except Exception as e:
            logger.error(f"[MATERIAL-CHAT STREAM] {e}")
            yield (
                "data: "
                + json.dumps({"type": "error", "data": str(e)})
                + "\n\n"
            )

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Endpoints: sessions ────────────────────────────────────────────────


@router.get("/sessions", response_model=List[MaterialChatSessionOut])
def list_sessions(
    material_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> List[MaterialChatSession]:
    _user_can_access_material(db, current_user["uid"], material_id)
    sessions = (
        db.query(MaterialChatSession)
        .filter(
            MaterialChatSession.course_material_id == material_id,
            MaterialChatSession.user_id == current_user["uid"],
        )
        .order_by(MaterialChatSession.updated_at.desc().nullslast())
        .all()
    )
    return sessions


@router.post(
    "/sessions", response_model=MaterialChatSessionOut, status_code=201
)
def create_session(
    body: MaterialChatSessionCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> MaterialChatSession:
    _user_can_access_material(db, current_user["uid"], body.material_id)
    session = MaterialChatSession(
        course_material_id=body.material_id,
        user_id=current_user["uid"],
        title=body.title
        or f"Chat {datetime.now().strftime('%b %d, %I:%M %p')}",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.patch("/sessions/{session_id}", response_model=MaterialChatSessionOut)
def rename_session(
    session_id: str,
    body: MaterialChatSessionRename,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> MaterialChatSession:
    session = _owned_session_or_403(db, current_user["uid"], session_id)
    session.title = body.title
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(session)
    return session


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> None:
    session = _owned_session_or_403(db, current_user["uid"], session_id)
    db.delete(session)
    db.commit()
    return None


@router.get(
    "/sessions/{session_id}/messages",
    response_model=List[MaterialChatMessageOut],
)
def list_messages(
    session_id: str,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> List[MaterialChatMessage]:
    _owned_session_or_403(db, current_user["uid"], session_id)
    rows = (
        db.query(MaterialChatMessage)
        .filter(MaterialChatMessage.session_id == session_id)
        .order_by(MaterialChatMessage.created_at.asc())
        .limit(limit)
        .all()
    )
    return rows
