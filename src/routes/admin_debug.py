from fastapi import APIRouter, HTTPException
from controllers.config import logger
from models import Video
from utils.db import SessionLocal
import os

router = APIRouter(prefix="/api", tags=["Admin & Debug"])


def cleanup_local_videos():
    db = SessionLocal()
    try:
        videos = (
            db.query(Video)
            .filter(Video.s3_key.isnot(None), Video.download_path.isnot(None))
            .all()
        )
        for video in videos:
            if video.download_path and os.path.exists(video.download_path):
                try:
                    os.remove(video.download_path)
                    video.download_path = None
                except Exception:
                    pass
        db.commit()
    except Exception as e:
        logger.error(f"Local video cleanup failed: {e}")
    finally:
        db.close()


@router.post("/admin/cleanup-local-videos")
async def cleanup_local_videos_endpoint():
    try:
        cleanup_local_videos()
        return {"success": True, "message": "Local video cleanup completed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
