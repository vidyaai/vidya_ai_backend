from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from utils.db import get_db
from models import Video, Folder
from schemas import (
    FolderCreate,
    FolderOut,
    VideoOut,
    MoveVideoRequest,
    DeleteVideoRequest,
    DeleteFolderRequest,
)
from utils.firebase_auth import get_current_user
from controllers.config import s3_client, AWS_S3_BUCKET


router = APIRouter(tags=["Gallery & Folders"], prefix="/api")


def delete_video_s3_objects(video: Video) -> None:
    """Delete S3 objects associated with an uploaded video."""
    if not s3_client or not AWS_S3_BUCKET:
        return

    # Delete main video file
    if video.s3_key:
        try:
            s3_client.delete_object(Bucket=AWS_S3_BUCKET, Key=video.s3_key)
        except Exception:
            pass  # Continue deleting other objects even if one fails

    # Delete thumbnail
    if video.thumb_key:
        try:
            s3_client.delete_object(Bucket=AWS_S3_BUCKET, Key=video.thumb_key)
        except Exception:
            pass

    # Delete transcript
    if video.transcript_s3_key:
        try:
            s3_client.delete_object(Bucket=AWS_S3_BUCKET, Key=video.transcript_s3_key)
        except Exception:
            pass


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
    q = q.filter(Video.user_id == current_user["uid"])
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


@router.delete("/gallery/video")
def delete_video(
    req: DeleteVideoRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    v = db.query(Video).filter(Video.id == req.video_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    # For uploaded videos, check user ownership
    if v.user_id != current_user["uid"]:
        raise HTTPException(
            status_code=403, detail="Not authorized to delete this video"
        )

    # Delete associated S3 objects if this is an uploaded video
    delete_video_s3_objects(v)

    db.delete(v)
    db.commit()
    return {"success": True}


@router.delete("/folders/{folder_id}")
def delete_folder(
    folder_id: str,
    req: DeleteFolderRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    folder = (
        db.query(Folder)
        .filter(Folder.id == folder_id, Folder.user_id == current_user["uid"])
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Check if folder has videos
    videos_in_folder = db.query(Video).filter(Video.folder_id == folder_id).all()

    # Check if folder has subfolders
    subfolders = db.query(Folder).filter(Folder.parent_id == folder_id).all()

    if videos_in_folder and not req.confirm_delete_videos:
        return {
            "success": False,
            "error": "folder_has_videos",
            "video_count": len(videos_in_folder),
            "message": f"This folder contains {len(videos_in_folder)} video(s). Set confirm_delete_videos=true to delete them.",
        }

    if subfolders:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete folder with subfolders. Please delete or move {len(subfolders)} subfolder(s) first.",
        )

    # Delete all videos in the folder if confirmed
    if videos_in_folder and req.confirm_delete_videos:
        for video in videos_in_folder:
            # Delete associated S3 objects for uploaded videos
            delete_video_s3_objects(video)
            db.delete(video)

    # Delete the folder
    db.delete(folder)
    db.commit()
    return {"success": True}


@router.get("/folders/{folder_id}/info")
def get_folder_info(
    folder_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    folder = (
        db.query(Folder)
        .filter(Folder.id == folder_id, Folder.user_id == current_user["uid"])
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Count videos in folder
    video_count = db.query(Video).filter(Video.folder_id == folder_id).count()

    # Count subfolders
    subfolder_count = db.query(Folder).filter(Folder.parent_id == folder_id).count()

    return {
        "id": folder.id,
        "name": folder.name,
        "video_count": video_count,
        "subfolder_count": subfolder_count,
        "can_delete": subfolder_count == 0,  # Can only delete if no subfolders
    }
