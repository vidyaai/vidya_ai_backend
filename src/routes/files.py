import os
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session
from utils.db import get_db
from controllers.db_helpers import get_video_path
from controllers.config import frames_path


router = APIRouter(prefix="/api", tags=["Files"])


@router.get("/videos/{video_id}")
async def serve_video(video_id: str, db: Session = Depends(get_db)):
    video_path = get_video_path(db, video_id)
    if video_path:
        if video_path.startswith("http"):
            return RedirectResponse(url=video_path)
        else:
            return FileResponse(video_path, media_type="video/mp4")
    raise HTTPException(status_code=404, detail="Video not found")


@router.get("/frames/{frame_filename}")
async def serve_frame(frame_filename: str):
    frame_path = os.path.join(frames_path, frame_filename)
    if os.path.exists(frame_path):
        return FileResponse(frame_path, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Frame not found")
