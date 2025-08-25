from fastapi import APIRouter, HTTPException, Depends
from controllers.storage import s3_presign_url
from controllers.config import s3_client, AWS_S3_BUCKET
from utils.firebase_auth import get_current_user


router = APIRouter(prefix="/api", tags=["Misc"])


@router.get("/storage/presign")
def presign_storage_key(
    key: str, expires_in: int = 3600, current_user=Depends(get_current_user)
):
    if not s3_client or not AWS_S3_BUCKET:
        raise HTTPException(status_code=500, detail="S3 is not configured")
    url = s3_presign_url(key, expires_in)
    return {"url": url}
