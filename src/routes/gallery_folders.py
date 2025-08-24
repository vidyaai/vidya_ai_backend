from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from utils.db import get_db
from models import Video, Folder
from schemas import FolderCreate, FolderOut, VideoOut, MoveVideoRequest


router = APIRouter(tags=["Gallery & Folders"], prefix="/api")


@router.post("/folders", response_model=FolderOut)
def create_folder(folder: FolderCreate, db: Session = Depends(get_db)):
    f = Folder(
        user_id=folder.user_id,
        name=folder.name,
        parent_id=folder.parent_id,
        source_type=folder.source_type,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


@router.get("/folders", response_model=List[FolderOut])
def list_folders(user_id: str, source_type: str, db: Session = Depends(get_db)):
    rows = (
        db.query(Folder)
        .filter(Folder.user_id == user_id, Folder.source_type == source_type)
        .order_by(Folder.created_at.desc())
        .all()
    )
    return rows


@router.get("/gallery", response_model=List[VideoOut])
def list_gallery(
    user_id: str,
    source_type: str,
    folder_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Video).filter(Video.source_type == source_type)
    if user_id:
        q = q.filter(Video.user_id == user_id)
    if folder_id is None:
        q = q.filter(Video.folder_id.is_(None))
    else:
        q = q.filter(Video.folder_id == folder_id)
    rows = q.order_by(Video.created_at.desc()).all()
    return rows


@router.post("/gallery/move")
def move_video(req: MoveVideoRequest, db: Session = Depends(get_db)):
    v = db.query(Video).filter(Video.id == req.video_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")
    v.folder_id = req.target_folder_id
    db.add(v)
    db.commit()
    return {"success": True}
