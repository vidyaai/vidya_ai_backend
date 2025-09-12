from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from utils.db import get_db
from models import Video, Folder, SharedLink
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


def check_content_is_shared(
    db: Session, content_type: str, content_id: str
) -> Optional[dict]:
    """
    Check if content (video or folder) is part of any shared links.
    Returns shared link info if found, None otherwise.
    """
    if content_type == "video":
        # Check for video shares (chat shares)
        shared_links = (
            db.query(SharedLink)
            .filter(SharedLink.video_id == content_id, SharedLink.share_type == "chat")
            .all()
        )

        # Check for folder shares that include this video
        folder_shares = (
            db.query(SharedLink)
            .join(Video)
            .filter(
                Video.id == content_id,
                Video.folder_id == SharedLink.folder_id,
                SharedLink.share_type == "folder",
            )
            .all()
        )

        shared_links.extend(folder_shares)

    elif content_type == "folder":
        # Check for folder shares
        shared_links = (
            db.query(SharedLink)
            .filter(
                SharedLink.folder_id == content_id, SharedLink.share_type == "folder"
            )
            .all()
        )

        # Check for videos in this folder that are part of chat shares
        video_shares = (
            db.query(SharedLink)
            .join(Video)
            .filter(Video.folder_id == content_id, SharedLink.share_type == "chat")
            .all()
        )

        shared_links.extend(video_shares)
    else:
        return None

    if shared_links:
        # Return info about the first shared link found
        link = shared_links[0]
        return {
            "link_id": link.id,
            "share_token": link.share_token,
            "title": link.title or f"Shared {content_type}",
            "share_type": link.share_type,
            "is_public": link.is_public,
            "created_at": link.created_at,
        }

    return None


def delete_video_s3_objects(video: Video) -> None:
    """Delete S3 objects associated with a video (uploaded or YouTube)."""
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

    # Check user ownership for all video types
    if v.user_id != current_user["uid"]:
        raise HTTPException(
            status_code=403, detail="Not authorized to delete this video"
        )

    # Check if video is part of any shared content
    shared_info = check_content_is_shared(db, "video", req.video_id)
    if shared_info:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "content_is_shared",
                "message": f"This video is part of shared content and cannot be deleted. Please delete the share link first to remove it from shared content.",
                "shared_link": {
                    "id": shared_info["link_id"],
                    "title": shared_info["title"],
                    "share_type": shared_info["share_type"],
                    "is_public": shared_info["is_public"],
                    "created_at": shared_info["created_at"].isoformat()
                    if shared_info["created_at"]
                    else None,
                },
            },
        )

    # Delete associated S3 objects (works for both uploaded and YouTube videos)
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

    # Check if folder is part of any shared content
    shared_info = check_content_is_shared(db, "folder", folder_id)
    if shared_info:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "content_is_shared",
                "message": f"This folder is part of shared content and cannot be deleted. Please delete the share link first to remove it from shared content.",
                "shared_link": {
                    "id": shared_info["link_id"],
                    "title": shared_info["title"],
                    "share_type": shared_info["share_type"],
                    "is_public": shared_info["is_public"],
                    "created_at": shared_info["created_at"].isoformat()
                    if shared_info["created_at"]
                    else None,
                },
            },
        )

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

    # Check if any videos in the folder are part of shared content
    if videos_in_folder and req.confirm_delete_videos:
        for video in videos_in_folder:
            video_shared_info = check_content_is_shared(db, "video", video.id)
            if video_shared_info:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "content_is_shared",
                        "message": f"Video '{video.title or video.id}' in this folder is part of shared content and cannot be deleted. Please delete the share link first to remove it from shared content.",
                        "shared_link": {
                            "id": video_shared_info["link_id"],
                            "title": video_shared_info["title"],
                            "share_type": video_shared_info["share_type"],
                            "is_public": video_shared_info["is_public"],
                            "created_at": video_shared_info["created_at"].isoformat()
                            if video_shared_info["created_at"]
                            else None,
                        },
                    },
                )

    # Delete all videos in the folder if confirmed
    if videos_in_folder and req.confirm_delete_videos:
        for video in videos_in_folder:
            # Delete associated S3 objects (works for both uploaded and YouTube videos)
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

    # Check if folder is shared
    shared_info = check_content_is_shared(db, "folder", folder_id)

    return {
        "id": folder.id,
        "name": folder.name,
        "video_count": video_count,
        "subfolder_count": subfolder_count,
        "can_delete": subfolder_count == 0
        and shared_info is None,  # Can only delete if no subfolders and not shared
        "is_shared": shared_info is not None,
        "shared_link": shared_info,
    }


@router.get("/gallery/video/{video_id}/info")
def get_video_info(
    video_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get video information including sharing status."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Check user ownership
    if video.user_id != current_user["uid"]:
        raise HTTPException(status_code=403, detail="Not authorized to view this video")

    # Check if video is shared
    shared_info = check_content_is_shared(db, "video", video_id)

    return {
        "id": video.id,
        "title": video.title,
        "source_type": video.source_type,
        "can_delete": shared_info is None,
        "is_shared": shared_info is not None,
        "shared_link": shared_info,
    }
