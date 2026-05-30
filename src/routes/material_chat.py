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
    LectureSummary,
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
    MaterialQuizRequest,
    MaterialSummaryRequest,
    MaterialSummaryResponse,
)
from services.chunking_embedding_service import EmbeddingService
from utils.db import get_db
from utils.firebase_auth import get_current_user
from utils.ml_models import OpenAIQuizClient, OpenAIVisionClient
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
- NEVER place a LaTeX expression inside bold markers. Wrong: **the matrix \\(K\\) represents…**.
  Right: the matrix \\(K\\) **represents…**. Bolding wraps math in raw HTML and breaks rendering.
- Always explain what the equation means in plain English first.

**Handle follow-ups gracefully:**
- The student is in an ongoing conversation. Short or pronoun-laden questions
  like "explain more", "deep dive into point 5", or "what about that?" almost
  always refer to your previous answer.
- ALWAYS read the conversation history first to figure out what the student
  is referring to before deciding the question is off-topic.
- Only say something is off-topic if it is clearly unrelated to the source
  AND unrelated to anything you said earlier in the conversation.

**Stay grounded in the source:**
- Use the provided context and conversation history as your sources of truth.
- If the source doesn't cover the question, say so honestly — don't invent.
"""

_SYSTEM_PROMPT_DOC = (
    "You are a friendly, enthusiastic tutor helping a student understand a "
    "document they're reading (lecture notes, a PDF chapter, or similar). "
    "Reference the material as 'the document', 'these notes', or 'this PDF' — "
    "never as a video or lecture recording.\n\n"
    "**Inline citations are required.** Every chunk of context you receive "
    "is prefixed with a `[Page N]` marker. When you state a fact drawn from "
    "the document, weave the exact `Page N` reference into the sentence — "
    "e.g. `As explained on Page 3, the matrix \\(K\\) represents…`. Always "
    "spell it as `Page N` (capital P, space, digits) — the UI renders this "
    "form as a clickable link that opens the PDF at that page.\n"
    + _SHARED_STYLE
)

_SYSTEM_PROMPT_VIDEO = (
    "You are a friendly, enthusiastic tutor helping a student understand a "
    "lecture video they're watching. The provided context is the lecture "
    "transcript. Reference the material as 'the lecture' or 'the video'.\n\n"
    "**Inline timestamp citations are required on EVERY topic, sub-topic, "
    "and bullet.** Every chunk of context you receive is prefixed with a "
    "`[MM:SS]` (or `[HH:MM:SS]`) timestamp from the lecture. Use those "
    "timestamps verbatim in your answer. The rules are absolute:\n"
    "- For a list of topics / sections, use a **numbered list** (`1.`, "
    "  `2.`, …) — NEVER a bulleted list (`-`). The exact format for each "
    "  topic line is:\n"
    "    `N. **Topic Title** (MM:SS - MM:SS):`\n"
    "  i.e. number + period + bold title + space + parenthesised range + "
    "  colon. Bold wraps ONLY the title text. The `(MM:SS - MM:SS)` range "
    "  MUST be outside the `**...**` markers, otherwise the UI can't "
    "  clickify the timestamps. Wrong: `1. **Topic (00:00 - 03:30)**`. "
    "  Right: `1. **Topic** (00:00 - 03:30):`.\n"
    "- Each numbered topic MUST carry its own range — start of the first "
    "  chunk you draw from for that topic, end of the last. Don't leave "
    "  any topic without a range.\n"
    "- Sub-bullets under a topic use `-` and end with a single starting "
    "  timestamp in parentheses, e.g. `   - the speaker introduces… "
    "  (00:21)`.\n"
    "- When you state a fact drawn from a specific moment inside a "
    "  paragraph, weave the exact starting timestamp into the sentence, "
    "  e.g. `Around 1:24 the professor explains…`. If the concept appears "
    "  at multiple moments, list each timestamp "
    "  (`…discussed at 5:30 and 6:28`).\n"
    "- Spell timestamps as plain `MM:SS` (or `HH:MM:SS`) digits with a "
    "  colon. Never replace a timestamp with a generic phrase like 'at "
    "  the start' or 'later on'. Never invent a timestamp the context "
    "  didn't give you. NEVER wrap a timestamp in bold or italic — the UI "
    "  can only clickify plain `MM:SS` substrings.\n\n"
    "**Worked example** of a section of a good answer:\n"
    "```\n"
    "1. **Introduction to Finite Element Method** (00:00 - 03:30):\n"
    "   - The professor introduces the displacement-based FEM (00:21).\n"
    "   - Ties it back to Ritz-Galerkin from earlier lectures (01:42).\n"
    "2. **Principle of Virtual Displacements** (03:30 - 07:00):\n"
    "   - States that external virtual work equals internal virtual work "
    "(03:48).\n"
    "```\n"
    + _SHARED_STYLE
)


def _system_prompt_for(material_type: str) -> str:
    return _SYSTEM_PROMPT_VIDEO if material_type == "video" else _SYSTEM_PROMPT_DOC


def _decode_frame_to_tempfile(image_base64: str) -> str:
    """Decode a base64 JPEG (sans data-uri prefix) to a temp file and return
    its path. Caller is responsible for unlinking."""
    import base64
    import os
    import tempfile

    if "," in image_base64 and image_base64.lstrip().startswith("data:"):
        image_base64 = image_base64.split(",", 1)[1]
    raw = base64.b64decode(image_base64)
    fd, path = tempfile.mkstemp(prefix="material_frame_", suffix=".jpg")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        raise
    return path


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
    # Prefix each chunk with a citation marker the model is told to quote
    # back inline:
    #   • Video chunks → `[MM:SS]` (or `[H:MM:SS]` past an hour). The
    #     frontend's parseMarkdownWithMath turns any MM:SS substring into
    #     a clickable button that seeks the player.
    #   • PDF chunks → `[Page N]`. The frontend's MaterialChatBox pre-
    #     transforms these into markdown links and intercepts clicks to
    #     drive the iframe to that page.
    def _fmt_citation_prefix(c: Dict[str, Any]) -> str:
        s = c.get("start_seconds")
        if s is not None:
            total = int(s)
            m, sec = divmod(total, 60)
            h = m // 60
            m = m % 60
            return f"[{h:02d}:{m:02d}:{sec:02d}] " if h else f"[{m:02d}:{sec:02d}] "
        p = c.get("page_number")
        if p is not None:
            return f"[Page {p}] "
        return ""

    context_text = "\n\n".join(
        f"{_fmt_citation_prefix(c)}{c.get('text', '')}"
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
    import os

    material = _user_can_access_material(db, current_user["uid"], body.material_id)

    # Frame queries only make sense for video materials.
    if body.is_image_query and material.material_type != "video":
        raise HTTPException(
            status_code=400,
            detail="Frame queries are only supported for video materials.",
        )
    if body.is_image_query and not body.image_base64:
        raise HTTPException(
            status_code=400,
            detail="Frame queries require an image_base64 payload.",
        )

    context_text, citations = _retrieve_context(db, material, body.query)
    if not context_text and not body.is_image_query:
        msg = _processing_message(material)
        if msg:
            return MaterialChatQueryResponse(
                response=msg, session_id=body.session_id or "", citations=[]
            )

    history: List[Dict[str, Any]] = []
    if body.session_id:
        history = get_merged_material_conversation_history(db, body.session_id)

    system_prompt = _system_prompt_for(material.material_type)
    vision_client = OpenAIVisionClient()

    frame_path: Optional[str] = None
    try:
        if body.is_image_query:
            frame_path = _decode_frame_to_tempfile(body.image_base64)
            ai_response = vision_client.ask_with_image(
                prompt=body.query,
                image_path=frame_path,
                context=context_text or "",
                conversation_history=history,
                system_prompt_override=system_prompt,
            )
        else:
            # Use the same augmented path the gallery uses so follow-up
            # questions like "deep dive into point 5" get rewritten with
            # conversation context before retrieval / answering. Web search
            # is off for material chat — answers must stay grounded in the
            # uploaded source.
            web_result = vision_client.ask_with_web_augmentation(
                prompt=body.query,
                context=context_text,
                conversation_history=history,
                video_title=material.title or "",
                enable_search=False,
                system_prompt_override=system_prompt,
            )
            ai_response = web_result.get("response", "")
    finally:
        if frame_path:
            try:
                os.remove(frame_path)
            except Exception:
                pass

    ai_response = normalize_ai_response(ai_response) if ai_response else ""

    session_id = store_material_conversation_turn(
        db=db,
        course_material_id=material.id,
        firebase_uid=current_user["uid"],
        user_message=body.query,
        ai_response=ai_response,
        citations=citations,
        timestamp_seconds=body.timestamp,
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
        import os

        frame_path: Optional[str] = None
        try:
            material = _user_can_access_material(
                db, current_user["uid"], body.material_id
            )

            # Frame queries: validate + decode upfront so we fail fast if
            # the client lied about its mode.
            if body.is_image_query and material.material_type != "video":
                yield (
                    "data: "
                    + json.dumps({
                        "type": "error",
                        "data": "Frame queries are only supported for video materials.",
                    })
                    + "\n\n"
                )
                return
            if body.is_image_query and not body.image_base64:
                yield (
                    "data: "
                    + json.dumps({
                        "type": "error",
                        "data": "Frame queries require an image_base64 payload.",
                    })
                    + "\n\n"
                )
                return

            context_text, citations = _retrieve_context(db, material, body.query)
            if not context_text and not body.is_image_query:
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
                            "query_type": "image" if body.is_image_query else "text",
                        },
                    }
                )
                + "\n\n"
            )

            system_prompt = _system_prompt_for(material.material_type)
            vision_client = OpenAIVisionClient()
            full_response = ""

            if body.is_image_query:
                # ask_with_image is non-streaming in the gallery; deliver the
                # full text as a single content frame to keep the SSE
                # contract identical.
                frame_path = _decode_frame_to_tempfile(body.image_base64)
                ai_response = vision_client.ask_with_image(
                    prompt=body.query,
                    image_path=frame_path,
                    context=context_text or "",
                    conversation_history=history,
                    system_prompt_override=system_prompt,
                )
                full_response = ai_response or ""
                if full_response:
                    yield (
                        "data: "
                        + json.dumps({"type": "content", "data": full_response})
                        + "\n\n"
                    )
            else:
                # ask_with_web_augmentation_stream yields JSON strings of
                # {"type":"metadata"|"content"|"done"|"error", "data":...}.
                # We only re-emit content events under our SSE envelope —
                # our own metadata + session + done frames are emitted
                # elsewhere in this function so the frontend contract is
                # unchanged.
                for chunk_json in vision_client.ask_with_web_augmentation_stream(
                    prompt=body.query,
                    context=context_text,
                    conversation_history=history,
                    video_title=material.title or "",
                    enable_search=False,
                    system_prompt_override=system_prompt,
                ):
                    try:
                        evt = json.loads(chunk_json)
                    except Exception:
                        continue
                    if evt.get("type") == "content":
                        delta = evt.get("data") or ""
                        if not delta:
                            continue
                        full_response += delta
                        yield (
                            "data: "
                            + json.dumps({"type": "content", "data": delta})
                            + "\n\n"
                        )
                    elif evt.get("type") == "error":
                        raise RuntimeError(evt.get("data") or "stream error")

            if full_response:
                full_response = normalize_ai_response(full_response)
                session_id = store_material_conversation_turn(
                    db=db,
                    course_material_id=material.id,
                    firebase_uid=current_user["uid"],
                    user_message=body.query,
                    ai_response=full_response,
                    citations=citations,
                    timestamp_seconds=body.timestamp,
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
        finally:
            if frame_path:
                try:
                    os.remove(frame_path)
                except Exception:
                    pass

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


# ── Quiz ────────────────────────────────────────────────────────────────


def _build_quiz_source_text(db: Session, material: CourseMaterial) -> str:
    """Build the source text the quiz generator should read from.

    Videos use the stored transcript (timed segments collapsed into plain
    text where available). PDFs/DOCXs use the concatenated MaterialChunk
    text in document order — same content the chat retrieval already grounds
    answers in.
    """
    if material.material_type == "video":
        text = (material.transcript_text or "").strip()
        if text:
            return text
        # Fallback to MaterialChunks (legacy materials transcribed pre-21)
    rows = (
        db.query(MaterialChunk)
        .filter(MaterialChunk.course_material_id == material.id)
        .order_by(MaterialChunk.chunk_index.asc())
        .all()
    )
    return "\n\n".join(r.text for r in rows if r.text)


@router.post("/quiz")
async def generate_material_quiz(
    body: MaterialQuizRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Generate an MCQ quiz for a CourseMaterial.

    Returns the same shape as /api/quiz/generate so the frontend QuizPanel
    flow can be reused: {success, quiz: [{id, question, options, answer,
    difficulty, explanation?}], message}.
    """
    material = _user_can_access_material(db, current_user["uid"], body.material_id)
    source_text = _build_quiz_source_text(db, material)
    if not source_text:
        raise HTTPException(
            status_code=400,
            detail="No transcript or indexed content available for this material yet.",
        )

    quiz_client = OpenAIQuizClient()
    try:
        result = quiz_client.generate_quiz(
            transcript=source_text,
            num_questions=body.num_questions,
            difficulty=body.difficulty,
            include_explanations=body.include_explanations,
            language=body.language,
        )
    except Exception as e:
        logger.error(f"Quiz generation failed for material {material.id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate quiz: {e}")

    # OpenAIQuizClient.generate_quiz normalizes into data["quiz"], but
    # OpenAI's json_object mode sometimes hands back the array under
    # "questions" instead of "quiz" — in which case the normalization
    # pass (which only reads "quiz") clobbers it with []. Read whichever
    # key is populated; mirror's the gallery quiz.py's same fallback.
    if isinstance(result, dict):
        questions = result.get("quiz") or result.get("questions") or []
    else:
        questions = []
    formatted: List[Dict[str, Any]] = []
    for i, q in enumerate(questions):
        item = {
            "id": f"q{i+1}",
            "question": q.get("question", ""),
            "options": q.get("options", []),
            "answer": q.get("answer", ""),
            "difficulty": body.difficulty,
        }
        if body.include_explanations and "explanation" in q:
            item["explanation"] = q["explanation"]
        formatted.append(item)

    return {
        "success": True,
        "material_id": material.id,
        "quiz": formatted,
        "message": f"Successfully generated {len(formatted)} questions",
    }


# ── Summary ─────────────────────────────────────────────────────────────


_MATERIAL_SUMMARY_TAG = "course_material_v1"


@router.post("/summary", response_model=MaterialSummaryResponse)
async def generate_material_summary(
    body: MaterialSummaryRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Generate a lecture-style summary for a CourseMaterial.

    Mirrors POST /api/lecture-summary/generate but anchored to a
    CourseMaterial: takes a material_id, builds the source text the
    same way the quiz endpoint does, runs the existing summarization
    workflow, persists the result in LectureSummary (with the
    material_id stored in the loose video_id column and a metadata
    tag so the download endpoint can distinguish), and returns the
    summary markdown alongside the summary_id.
    """
    import os
    import tempfile
    import time
    from uuid import uuid4
    from controllers.storage import s3_upload_file

    user_id = current_user["uid"]
    material = _user_can_access_material(db, user_id, body.material_id)
    source_text = _build_quiz_source_text(db, material)
    if not source_text:
        raise HTTPException(
            status_code=400,
            detail="No transcript or indexed content available for this material yet.",
        )

    # Check cache unless force_regenerate
    if not body.force_regenerate:
        existing = (
            db.query(LectureSummary)
            .filter(
                LectureSummary.video_id == material.id,
                LectureSummary.user_id == user_id,
            )
            .order_by(LectureSummary.created_at.desc())
            .first()
        )
        if existing:
            return MaterialSummaryResponse(
                summary_id=existing.id,
                material_id=material.id,
                summary=existing.summary_markdown or "",
                summary_metadata=existing.summary_metadata,
                created_at=existing.created_at,
            )

    # Generate new summary
    try:
        from summarize_lecture.graph.workflow import run_summarization
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Summarization module not available: {e}"
        )

    start = time.time()
    final_state = run_summarization(material.id, source_text)
    if final_state.get("errors"):
        raise HTTPException(
            status_code=500,
            detail=f"Summarization failed: {'; '.join(final_state['errors'])}",
        )

    summary_markdown = final_state.get("summary_markdown", "")
    key_topics = final_state.get("key_topics", [])
    research_results = final_state.get("research_results", [])
    if not summary_markdown:
        raise HTTPException(
            status_code=500, detail="Summary generation returned no content."
        )

    # Generate + upload PDF
    s3_key: Optional[str] = None
    summary_id = str(uuid4())
    try:
        from summarize_lecture.utils.pdf_generator import LectureSummaryPDFGenerator

        pdf_generator = LectureSummaryPDFGenerator()
        temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        temp_pdf_path = temp_pdf.name
        temp_pdf.close()
        try:
            pdf_path = pdf_generator.generate_pdf_from_content(
                summary_markdown, temp_pdf_path
            )
            if pdf_path and os.path.exists(pdf_path):
                s3_key = f"lecture-summaries/material-{material.id}/{summary_id}.pdf"
                s3_upload_file(pdf_path, s3_key, "application/pdf")
        finally:
            try:
                pdf_generator.cleanup()
            except Exception:
                pass
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)
    except Exception as e:
        # PDF is a nice-to-have; persist the markdown summary even if PDF fails.
        logger.error(f"PDF generation failed for material {material.id}: {e}")

    generation_time = time.time() - start
    summary_metadata = {
        "source": _MATERIAL_SUMMARY_TAG,
        "material_id": material.id,
        "material_title": material.title or "Untitled material",
        "key_topics": key_topics,
        "research_sources_count": len(research_results),
        "generation_time_seconds": round(generation_time, 2),
    }

    row = LectureSummary(
        id=summary_id,
        video_id=material.id,  # loose String column reused for material id
        user_id=user_id,
        summary_markdown=summary_markdown,
        summary_pdf_s3_key=s3_key,
        summary_metadata=summary_metadata,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return MaterialSummaryResponse(
        summary_id=row.id,
        material_id=material.id,
        summary=summary_markdown,
        summary_metadata=summary_metadata,
        created_at=row.created_at,
    )


@router.get("/transcript/{material_id}")
async def get_material_transcript(
    material_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return the lecture's transcript in both plain-text and timed-segment
    form so the frontend can render the same Transcript / Timestamps tab
    pattern the gallery's TranscriptComponent uses.

    Response shape:
      {
        "material_id": str,
        "material_type": str,
        "transcript_status": str | null,
        "transcript_text": str | null,
        "segments": [{"start": float, "dur": float, "text": str}, ...],
        "length_seconds": int | null,
      }
    For PDF (lecture_notes) materials the segments list will be empty —
    documents have no audio timeline — but transcript_text may still
    carry the joined chunk text the chat uses for retrieval.
    """
    material = _user_can_access_material(db, current_user["uid"], material_id)
    segments: List[Dict[str, Any]] = []
    length_seconds = None
    if isinstance(material.transcript_json, dict):
        raw = material.transcript_json.get("transcription") or []
        for s in raw:
            if not isinstance(s, dict):
                continue
            seg_text = s.get("text") or ""
            start = s.get("start")
            dur = s.get("dur")
            if seg_text and start is not None and dur is not None:
                segments.append(
                    {"start": float(start), "dur": float(dur), "text": seg_text}
                )
        length_seconds = material.transcript_json.get("lengthInSeconds")

    return {
        "material_id": material.id,
        "material_type": material.material_type,
        "transcript_status": material.transcript_status,
        "transcript_text": material.transcript_text or "",
        "segments": segments,
        "length_seconds": length_seconds,
    }


@router.get("/summary/{summary_id}/download")
async def download_material_summary(
    summary_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Stream the PDF for a previously generated material-chat summary."""
    from fastapi.responses import Response
    from controllers.storage import s3_presign_url
    from controllers.config import s3_client, AWS_S3_BUCKET

    user_id = current_user["uid"]
    summary = (
        db.query(LectureSummary).filter(LectureSummary.id == summary_id).first()
    )
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")

    # Trust boundary: summary owner OR a user who can access the underlying material.
    if summary.user_id != user_id:
        try:
            _user_can_access_material(db, user_id, summary.video_id)
        except HTTPException:
            raise HTTPException(status_code=403, detail="Not authorized")

    if not summary.summary_pdf_s3_key:
        raise HTTPException(status_code=404, detail="PDF not available for this summary")

    if not s3_client or not AWS_S3_BUCKET:
        raise HTTPException(status_code=500, detail="S3 not configured")

    try:
        obj = s3_client.get_object(
            Bucket=AWS_S3_BUCKET, Key=summary.summary_pdf_s3_key
        )
        body = obj["Body"].read()
    except Exception as e:
        logger.error(f"Failed to fetch summary PDF from S3: {e}")
        raise HTTPException(status_code=500, detail="Failed to download summary PDF")

    fname = "summary.pdf"
    if isinstance(summary.summary_metadata, dict):
        t = summary.summary_metadata.get("material_title") or ""
        clean = "".join(c if c.isalnum() else "_" for c in t).strip("_")
        if clean:
            fname = f"{clean[:60]}_Summary.pdf"
    return Response(
        content=body,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
