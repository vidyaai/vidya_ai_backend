import os
import time
from collections import defaultdict
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from utils.db import get_db
from utils.embed_auth import mint_embed_session, verify_embed_token
from controllers.config import logger
from models import EmbedClient
from schemas import EmbedSessionRequest, EmbedSessionResponse

router = APIRouter(prefix="/api/embed", tags=["Embed"])

EMBED_DEMO_UID = os.environ.get("EMBED_DEMO_UID", "demo")
EMBED_DEMO_COURSE_ID = os.environ.get("EMBED_DEMO_COURSE_ID")

# Simple in-memory sliding-window rate limiter for the demo endpoint.
# Single-instance only; swap for Redis if running multiple backend instances.
_DEMO_RATE_LIMIT = 10  # requests
_DEMO_RATE_WINDOW = 60  # seconds
_demo_request_log: dict[str, list[float]] = defaultdict(list)
_demo_rate_lock = Lock()


def _check_demo_rate_limit(ip: str) -> None:
    now = time.time()
    with _demo_rate_lock:
        recent = [t for t in _demo_request_log[ip] if now - t < _DEMO_RATE_WINDOW]
        if len(recent) >= _DEMO_RATE_LIMIT:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, "Too many demo session requests"
            )
        recent.append(now)
        _demo_request_log[ip] = recent


@router.post("/session", response_model=EmbedSessionResponse)
async def create_embed_session(
    payload: EmbedSessionRequest, db: Session = Depends(get_db)
):
    """Exchange a tenant-signed handoff JWT for a Firebase custom token."""
    client, claims = verify_embed_token(payload.token, db)
    custom_token, user = mint_embed_session(db, client, claims)

    logger.info(f"Embed session created for tenant={client.slug} sub={claims['sub']}")

    return EmbedSessionResponse(
        firebase_token=custom_token,
        course_id=claims.get("course"),
        video_id=claims.get("video"),
        user_type=user.user_type,
    )


@router.get("/demo-session", response_model=EmbedSessionResponse)
async def create_demo_session(request: Request, db: Session = Depends(get_db)):
    """No-auth demo session for public embeds (e.g. Google Sites)."""
    client_ip = request.client.host if request.client else "unknown"
    _check_demo_rate_limit(client_ip)

    demo_client = EmbedClient(slug="demo", default_user_type="student")
    claims = {"sub": EMBED_DEMO_UID, "name": "Demo User"}
    custom_token, user = mint_embed_session(db, demo_client, claims)

    return EmbedSessionResponse(
        firebase_token=custom_token,
        course_id=EMBED_DEMO_COURSE_ID,
        user_type=user.user_type,
    )
