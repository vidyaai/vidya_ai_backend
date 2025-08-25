from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from utils.db import get_db
from models import Video, Folder
from schemas import FolderCreate, FolderOut, VideoOut, MoveVideoRequest
from utils.firebase_auth import get_current_user


router = APIRouter(tags=["Gallery & Folders"], prefix="/api")


@router.post("/folders", response_model=FolderOut)
def create_folder(
    folder: FolderCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    f = Folder(
        user_id=current_user["uid"],
        name=folder.name,
        parent_id=folder.parent_id,
        source_type=folder.source_type,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


@router.get("/folders", response_model=List[FolderOut])
def list_folders(
    source_type: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows = (
        db.query(Folder)
        .filter(
            Folder.user_id == current_user["uid"], Folder.source_type == source_type
        )
        .order_by(Folder.created_at.desc())
        .all()
    )
    return rows


@router.get("/gallery", response_model=List[VideoOut])
def list_gallery(
    source_type: str,
    folder_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(Video).filter(Video.source_type == source_type)
    q = (
        q.filter(Video.user_id == current_user["uid"])
        if source_type == "uploaded"
        else q
    )
    if folder_id is None:
        q = q.filter(Video.folder_id.is_(None))
    else:
        q = q.filter(Video.folder_id == folder_id)
    rows = q.order_by(Video.created_at.desc()).all()
    return rows


@router.post("/gallery/move")
def move_video(
    req: MoveVideoRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    v = (
        db.query(Video)
        .filter(Video.id == req.video_id, Video.user_id == current_user["uid"])
        .first()
    )
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")
    v.folder_id = req.target_folder_id
    db.add(v)
    db.commit()
    return {"success": True}
