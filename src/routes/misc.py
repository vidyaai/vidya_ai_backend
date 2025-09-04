from fastapi import APIRouter, HTTPException, Depends, Query
from controllers.storage import s3_presign_url
from controllers.config import s3_client, AWS_S3_BUCKET
from utils.firebase_auth import get_current_user
from utils.db import get_db
from sqlalchemy.orm import Session
from models import SharedLink


router = APIRouter(prefix="/api", tags=["Misc"])


@router.get("/storage/presign")
def presign_storage_key(
    key: str, expires_in: int = 3600, current_user=Depends(get_current_user)
):
    """Get presigned URL for authenticated users."""
    if not s3_client or not AWS_S3_BUCKET:
        raise HTTPException(status_code=500, detail="S3 is not configured")
    url = s3_presign_url(key, expires_in)
    return {"url": url}


@router.get("/storage/presign/public")
def presign_storage_key_public(
    key: str,
    expires_in: int = 3600,
    share_token: str = Query(..., description="Share token for shared content access"),
    db: Session = Depends(get_db),
):
    """Get presigned URL for shared content (both public and private with valid token)."""
    if not s3_client or not AWS_S3_BUCKET:
        raise HTTPException(status_code=500, detail="S3 is not configured")

    # Verify the share token is valid (both public and private shares are allowed)
    shared_link = (
        db.query(SharedLink).filter(SharedLink.share_token == share_token).first()
    )
    if not shared_link:
        raise HTTPException(status_code=403, detail="Invalid share token")

    url = s3_presign_url(key, expires_in)
    return {"url": url}
