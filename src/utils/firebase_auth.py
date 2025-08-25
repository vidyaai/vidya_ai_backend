import os
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, status

try:
    import firebase_admin
    from firebase_admin import auth as fb_auth, credentials
except Exception:  # pragma: no cover
    firebase_admin = None
    fb_auth = None
    credentials = None


def ensure_firebase_initialized() -> None:
    if firebase_admin is None or credentials is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Firebase admin SDK not available on server",
        )
    if not firebase_admin._apps:
        service_account_path: Optional[str] = os.getenv(
            "FIREBASE_SERVICE_ACCOUNT_JSON_PATH"
        )
        if not service_account_path or not os.path.exists(service_account_path):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Firebase service account path not configured",
            )
        cred = credentials.Certificate(service_account_path)
        firebase_admin.initialize_app(cred)


async def get_current_user(
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    ensure_firebase_initialized()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token"
        )
    token = authorization.split(" ", 1)[1]
    try:
        decoded = fb_auth.verify_id_token(token)
        return decoded
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
