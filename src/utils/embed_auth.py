import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

import jwt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from utils.firebase_auth import ensure_firebase_initialized
from utils.user_utils import get_or_create_user
from models import EmbedClient, User

try:
    from firebase_admin import auth as fb_auth
except Exception:  # pragma: no cover
    fb_auth = None

EMBED_AUDIENCE = "vidyaai-embed"
# How old a token's `iat` may be at verification time, regardless of `exp`.
# Override locally (e.g. EMBED_MAX_TOKEN_AGE_SECONDS=3600) to avoid re-minting
# test tokens every 5 minutes during manual testing.
MAX_TOKEN_AGE_SECONDS = int(os.environ.get("EMBED_MAX_TOKEN_AGE_SECONDS", "300"))


def verify_embed_token(token: str, db: Session) -> Tuple[EmbedClient, Dict[str, Any]]:
    """Verify a tenant-signed embed handoff JWT and return the client + claims."""
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed token")

    tenant_slug = unverified.get("iss")
    client = (
        db.query(EmbedClient)
        .filter(EmbedClient.slug == tenant_slug, EmbedClient.active.is_(True))
        .first()
    )
    if not client:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown tenant")

    try:
        claims = jwt.decode(
            token,
            client.embed_secret,
            algorithms=["HS256"],
            audience=EMBED_AUDIENCE,
            issuer=tenant_slug,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Token invalid: {e}")

    iat = datetime.fromtimestamp(claims["iat"], tz=timezone.utc)
    if (datetime.now(timezone.utc) - iat).total_seconds() > MAX_TOKEN_AGE_SECONDS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token too old")

    return client, claims


def _build_embed_uid(client_slug: str, external_id: str) -> str:
    """Build a Firebase-UID-safe, tenant-namespaced uid for an embed user."""
    safe_external_id = re.sub(r"[^a-zA-Z0-9_-]", "_", external_id)
    uid = f"embed_{client_slug}_{safe_external_id}"
    return uid[:128]


def mint_embed_session(
    db: Session, client: EmbedClient, claims: Dict[str, Any]
) -> Tuple[str, User]:
    """Ensure the embed user exists in Firebase + Postgres, return a custom token + user."""
    ensure_firebase_initialized()

    uid = _build_embed_uid(client.slug, claims["sub"])
    email = claims.get("email")
    name = claims.get("name")

    try:
        fb_auth.get_user(uid)
        if email or name:
            fb_auth.update_user(uid, email=email or None, display_name=name or None)
    except fb_auth.UserNotFoundError:
        fb_auth.create_user(uid=uid, email=email or None, display_name=name or None)

    user_type = claims.get("role") or client.default_user_type
    user = get_or_create_user(
        db,
        firebase_uid=uid,
        email=email,
        name=name,
        user_type=user_type,
    )

    custom_token = fb_auth.create_custom_token(
        uid, {"tenant": client.slug, "embed": True}
    )
    # create_custom_token returns bytes
    if isinstance(custom_token, bytes):
        custom_token = custom_token.decode("utf-8")

    return custom_token, user
