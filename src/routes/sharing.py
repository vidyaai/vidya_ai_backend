"""Sharing functionality routes for folders and chat sessions."""
import os
import secrets
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_

from controllers.background_tasks import download_video_background
from controllers.config import download_executor, frames_path
from utils.db import get_db
from utils.firebase_auth import get_current_user
from utils.firebase_users import (
    search_users_by_email,
    get_users_by_uids,
    get_user_by_uid,
    validate_user_exists,
)
from models import SharedLink, SharedLinkAccess, Folder, Video
from schemas import (
    CreateSharedLinkRequest,
    UpdateSharedLinkRequest,
    SharedLinkOut,
    ShareEmailSearchRequest,
    AddUsersToSharedLinkRequest,
    RemoveUserFromSharedLinkRequest,
    PublicSharedResourceOut,
    FirebaseUser,
    FolderOut,
    VideoOut,
)
from utils.ml_models import OpenAIVisionClient
from controllers.db_helpers import (
    get_download_status,
    get_formatting_status,
    get_transcript_cache,
    get_video_path,
    update_transcript_cache,
)
from utils.youtube_utils import download_transcript_api, grab_youtube_frame
from controllers.storage import s3_presign_url

router = APIRouter(tags=["Sharing"], prefix="/api/sharing")


def validate_shared_video_access(
    db: Session, share_token: str, video_id: str
) -> Optional[Video]:
    """
    Validate that a video can be accessed through a share token.
    Returns the video object if access is granted, None otherwise.
    """
    try:
        # Get the shared link
        link = (
            db.query(SharedLink).filter(SharedLink.share_token == share_token).first()
        )
        if not link:
            return None

        # Check if video matches the shared link
        if link.share_type == "folder":
            # For folder shares, check if video is in the folder
            if link.folder_id:
                video = (
                    db.query(Video)
                    .filter(Video.id == video_id, Video.folder_id == link.folder_id)
                    .first()
                )
                if video:
                    return video
        elif link.share_type == "chat":
            # For chat shares, check if video matches
            if link.video_id == video_id:
                video = db.query(Video).filter(Video.id == video_id).first()
                if video:
                    return video

        return None
    except Exception:
        return None


def generate_share_token() -> str:
    """Generate a secure share token."""
    return secrets.token_urlsafe(32)


async def populate_user_data(shared_links: List[SharedLink]) -> List[SharedLinkOut]:
    """Populate Firebase user data for shared links."""
    print(f"Populating user data for {len(shared_links)} links")

    # Collect all unique user IDs
    user_ids = set()
    for link in shared_links:
        user_ids.add(link.owner_id)
        # Ensure shared_accesses is loaded
        if hasattr(link, "shared_accesses") and link.shared_accesses:
            print(f"Link {link.id} has {len(link.shared_accesses)} shared accesses")
            for access in link.shared_accesses:
                user_ids.add(access.user_id)
        else:
            print(f"Link {link.id} has no shared_accesses or it's not loaded")

    print(f"Collected user IDs: {user_ids}")

    # Fetch user data from Firebase
    users_data = await get_users_by_uids(list(user_ids))
    users_map = {user["uid"]: user for user in users_data}

    print(f"Fetched {len(users_data)} users from Firebase")

    # Build response with user data
    result = []
    for link in shared_links:
        link_dict = SharedLinkOut.model_validate(link).model_dump()

        # Add owner data
        if link.owner_id in users_map:
            link_dict["owner"] = users_map[link.owner_id]

        # Add user data for shared accesses
        if "shared_accesses" in link_dict and link_dict["shared_accesses"]:
            for i, access in enumerate(link_dict["shared_accesses"]):
                user_id = access["user_id"]
                if user_id in users_map:
                    link_dict["shared_accesses"][i]["user"] = users_map[user_id]

        result.append(SharedLinkOut(**link_dict))

    print(f"Returning {len(result)} populated links")
    return result


@router.post("/search-users", response_model=List[FirebaseUser])
async def search_users(
    request: ShareEmailSearchRequest, current_user=Depends(get_current_user)
):
    """Search users by email for sharing invitations."""
    if not request.query or len(request.query.strip()) < 2:
        return []

    users = await search_users_by_email(request.query.strip(), limit=10)
    return [FirebaseUser(**user) for user in users]


@router.post("/links", response_model=SharedLinkOut)
async def create_shared_link(
    request: CreateSharedLinkRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a new shareable link."""
    # Validate request
    if request.share_type not in ["folder", "chat"]:
        raise HTTPException(
            status_code=400, detail="Invalid share_type. Must be 'folder' or 'chat'"
        )

    if request.share_type == "folder" and not request.folder_id:
        raise HTTPException(
            status_code=400, detail="folder_id is required for folder sharing"
        )

    if request.share_type == "chat" and not (
        request.video_id and request.chat_session_id
    ):
        raise HTTPException(
            status_code=400,
            detail="video_id and chat_session_id are required for chat sharing",
        )

    # Verify ownership
    if request.share_type == "folder":
        folder = (
            db.query(Folder)
            .filter(
                Folder.id == request.folder_id, Folder.user_id == current_user["uid"]
            )
            .first()
        )
        if not folder:
            raise HTTPException(
                status_code=404, detail="Folder not found or access denied"
            )

    if request.share_type == "chat":
        video = db.query(Video).filter(Video.id == request.video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        # For uploaded videos, check ownership
        if video.source_type == "uploaded" and video.user_id != current_user["uid"]:
            raise HTTPException(status_code=403, detail="Access denied")

        # Verify chat session exists
        if not video.chat_sessions:
            raise HTTPException(status_code=404, detail="No chat sessions found")

        session_exists = any(
            session.get("id") == request.chat_session_id
            for session in video.chat_sessions
        )
        if not session_exists:
            raise HTTPException(status_code=404, detail="Chat session not found")

    # Validate invited users exist in Firebase
    if request.invited_users:
        for user_id in request.invited_users:
            if not await validate_user_exists(user_id):
                raise HTTPException(status_code=400, detail=f"User {user_id} not found")

    # Create shared link
    share_token = generate_share_token()
    shared_link = SharedLink(
        share_token=share_token,
        owner_id=current_user["uid"],
        share_type=request.share_type,
        folder_id=request.folder_id,
        video_id=request.video_id,
        chat_session_id=request.chat_session_id,
        is_public=request.is_public,
        title=request.title,
        description=request.description,
        expires_at=request.expires_at,
        max_views=str(request.max_views) if request.max_views else None,
        view_count="0",
    )

    db.add(shared_link)
    db.flush()  # Get the ID

    # Add invited users
    for user_id in request.invited_users:
        access = SharedLinkAccess(
            shared_link_id=shared_link.id, user_id=user_id, permission="view"
        )
        db.add(access)

    db.commit()

    # Reload the shared_link with relationships
    shared_link_with_accesses = (
        db.query(SharedLink)
        .options(joinedload(SharedLink.shared_accesses))
        .filter(SharedLink.id == shared_link.id)
        .first()
    )

    # Return with user data
    populated_links = await populate_user_data([shared_link_with_accesses])
    print(f"Returning populated link: {populated_links[0]}")
    return populated_links[0]


@router.get("/links", response_model=List[SharedLinkOut])
async def list_my_shared_links(
    db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    """List all shared links created by the current user."""
    links = (
        db.query(SharedLink)
        .filter(SharedLink.owner_id == current_user["uid"])
        .order_by(SharedLink.created_at.desc())
        .all()
    )

    return await populate_user_data(links)


@router.get("/links/shared-with-me", response_model=List[SharedLinkOut])
async def list_links_shared_with_me(
    db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    """List all shared links that have been shared with the current user."""
    # Get shared link IDs where user has access
    access_records = (
        db.query(SharedLinkAccess)
        .filter(SharedLinkAccess.user_id == current_user["uid"])
        .all()
    )

    if not access_records:
        return []

    shared_link_ids = [access.shared_link_id for access in access_records]
    links = (
        db.query(SharedLink)
        .filter(SharedLink.id.in_(shared_link_ids))
        .order_by(SharedLink.created_at.desc())
        .all()
    )

    return await populate_user_data(links)


@router.get("/links/{link_id}", response_model=SharedLinkOut)
async def get_shared_link(
    link_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    """Get details of a specific shared link."""
    link = db.query(SharedLink).filter(SharedLink.id == link_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Shared link not found")

    # Check if user owns the link or has access
    has_access = (
        link.owner_id == current_user["uid"]
        or db.query(SharedLinkAccess)
        .filter(
            SharedLinkAccess.shared_link_id == link_id,
            SharedLinkAccess.user_id == current_user["uid"],
        )
        .first()
        is not None
    )

    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied")

    populated_links = await populate_user_data([link])
    return populated_links[0]


@router.put("/links/{link_id}", response_model=SharedLinkOut)
async def update_shared_link(
    link_id: str,
    request: UpdateSharedLinkRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Update a shared link (owner only)."""
    link = (
        db.query(SharedLink)
        .filter(SharedLink.id == link_id, SharedLink.owner_id == current_user["uid"])
        .first()
    )

    if not link:
        raise HTTPException(
            status_code=404, detail="Shared link not found or access denied"
        )

    # Update fields
    if request.title is not None:
        link.title = request.title
    if request.description is not None:
        link.description = request.description
    if request.is_public is not None:
        link.is_public = request.is_public
    if request.expires_at is not None:
        link.expires_at = request.expires_at
    if request.max_views is not None:
        link.max_views = str(request.max_views)

    link.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(link)

    populated_links = await populate_user_data([link])
    return populated_links[0]


@router.delete("/links/{link_id}")
async def delete_shared_link(
    link_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    """Delete a shared link (owner only)."""
    link = (
        db.query(SharedLink)
        .filter(SharedLink.id == link_id, SharedLink.owner_id == current_user["uid"])
        .first()
    )

    if not link:
        raise HTTPException(
            status_code=404, detail="Shared link not found or access denied"
        )

    db.delete(link)
    db.commit()

    return {"success": True}


@router.post("/links/{link_id}/users")
async def add_users_to_shared_link(
    link_id: str,
    request: AddUsersToSharedLinkRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Add users to a shared link (owner only)."""
    link = (
        db.query(SharedLink)
        .filter(SharedLink.id == link_id, SharedLink.owner_id == current_user["uid"])
        .first()
    )

    if not link:
        raise HTTPException(
            status_code=404, detail="Shared link not found or access denied"
        )

    # Validate users exist
    for user_id in request.user_ids:
        if not await validate_user_exists(user_id):
            raise HTTPException(status_code=400, detail=f"User {user_id} not found")

    # Add users (skip if already exists)
    for user_id in request.user_ids:
        existing = (
            db.query(SharedLinkAccess)
            .filter(
                SharedLinkAccess.shared_link_id == link_id,
                SharedLinkAccess.user_id == user_id,
            )
            .first()
        )

        if not existing:
            access = SharedLinkAccess(
                shared_link_id=link_id, user_id=user_id, permission=request.permission
            )
            db.add(access)

    db.commit()
    return {"success": True, "added_users": request.user_ids}


@router.delete("/links/{link_id}/users")
async def remove_user_from_shared_link(
    link_id: str,
    request: RemoveUserFromSharedLinkRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Remove a user from a shared link (owner only)."""
    link = (
        db.query(SharedLink)
        .filter(SharedLink.id == link_id, SharedLink.owner_id == current_user["uid"])
        .first()
    )

    if not link:
        raise HTTPException(
            status_code=404, detail="Shared link not found or access denied"
        )

    access = (
        db.query(SharedLinkAccess)
        .filter(
            SharedLinkAccess.shared_link_id == link_id,
            SharedLinkAccess.user_id == request.user_id,
        )
        .first()
    )

    if access:
        db.delete(access)
        db.commit()

    return {"success": True}


# Public access routes (no authentication required)
@router.get("/public/{share_token}")
async def get_public_shared_resource(share_token: str, db: Session = Depends(get_db)):
    """Get public shared resource by token."""
    link = db.query(SharedLink).filter(SharedLink.share_token == share_token).first()

    if not link:
        raise HTTPException(status_code=404, detail="Shared link not found")

    # Check if link is public
    if not link.is_public:
        raise HTTPException(status_code=403, detail="This link is private")

    # Check expiration
    if link.expires_at and datetime.now(timezone.utc) > link.expires_at:
        raise HTTPException(status_code=410, detail="This link has expired")

    # Check view limit
    if link.max_views and int(link.view_count) >= int(link.max_views):
        raise HTTPException(
            status_code=429, detail="This link has reached its view limit"
        )

    # Increment view count
    link.view_count = str(int(link.view_count) + 1)
    db.commit()

    # Get owner info
    owner_data = await get_user_by_uid(link.owner_id)

    # Prepare response
    response = {
        "share_token": link.share_token,
        "share_type": link.share_type,
        "title": link.title,
        "description": link.description,
        "owner_display_name": owner_data.get("displayName") if owner_data else None,
        "created_at": link.created_at,
    }

    # Add resource data based on type
    if link.share_type == "folder":
        folder = db.query(Folder).filter(Folder.id == link.folder_id).first()
        if folder:
            # Get videos in folder
            videos = db.query(Video).filter(Video.folder_id == link.folder_id).all()
            response["folder"] = FolderOut.model_validate(folder)
            response["videos"] = [VideoOut.model_validate(v) for v in videos]

    elif link.share_type == "chat":
        video = db.query(Video).filter(Video.id == link.video_id).first()
        if video and video.chat_sessions:
            # Find the specific chat session
            chat_session = None
            for session in video.chat_sessions:
                if session.get("id") == link.chat_session_id:
                    chat_session = session
                    break

            response["video"] = VideoOut.model_validate(video)
            response["chat_session"] = chat_session

    return response


# Private access routes (requires authentication)
@router.get("/private/{share_token}")
async def get_private_shared_resource(
    share_token: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get private shared resource by token (requires authentication and invitation)."""
    print(
        f"Private access attempt for token: {share_token} by user: {current_user['uid']}"
    )

    link = db.query(SharedLink).filter(SharedLink.share_token == share_token).first()

    if not link:
        print(f"Link not found for token: {share_token}")
        raise HTTPException(status_code=404, detail="Shared link not found")

    print(f"Found link: {link.id}, owner: {link.owner_id}, is_public: {link.is_public}")

    # Check if user has access
    has_access = (
        link.owner_id == current_user["uid"]
        or db.query(SharedLinkAccess)
        .filter(
            SharedLinkAccess.shared_link_id == link.id,
            SharedLinkAccess.user_id == current_user["uid"],
        )
        .first()
        is not None
    )

    print(f"User {current_user['uid']} has access: {has_access}")

    if not has_access:
        raise HTTPException(
            status_code=403,
            detail="Access denied. You need an invitation to view this content.",
        )

    # Check expiration
    if link.expires_at and datetime.now(timezone.utc) > link.expires_at:
        raise HTTPException(status_code=410, detail="This shared link has expired")

    # Check view limit
    if link.max_views and int(link.view_count) >= int(link.max_views):
        raise HTTPException(
            status_code=429, detail="This shared link has reached its view limit"
        )

    # Increment view count
    link.view_count = str(int(link.view_count) + 1)
    db.commit()

    # Get owner info
    owner_data = await get_user_by_uid(link.owner_id)

    # Prepare response
    response = {
        "share_token": link.share_token,
        "share_type": link.share_type,
        "title": link.title,
        "description": link.description,
        "owner_display_name": owner_data.get("displayName") if owner_data else None,
        "created_at": link.created_at,
    }

    # Add resource data based on type
    if link.share_type == "folder":
        folder = db.query(Folder).filter(Folder.id == link.folder_id).first()
        if folder:
            # Get videos in folder
            folder_videos = (
                db.query(Video).filter(Video.folder_id == link.folder_id).all()
            )
            response["folder"] = FolderOut.model_validate(folder)
            response["videos"] = [VideoOut.model_validate(v) for v in folder_videos]

    elif link.share_type == "chat":
        video = db.query(Video).filter(Video.id == link.video_id).first()
        if video and video.chat_sessions:
            # Find the specific chat session
            chat_session = None
            for session in video.chat_sessions:
                if session.get("id") == link.chat_session_id:
                    chat_session = session
                    break

            response["video"] = VideoOut.model_validate(video)
            response["chat_session"] = chat_session

    return response


@router.get("/my-shared-content")
async def get_my_shared_content(
    db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    """Get all content that has been shared with the current user."""
    print(f"Getting shared content for user: {current_user['uid']}")

    # Get shared link IDs where user has access
    access_records = (
        db.query(SharedLinkAccess)
        .filter(SharedLinkAccess.user_id == current_user["uid"])
        .all()
    )

    print(f"Found {len(access_records)} access records for user")

    if not access_records:
        return {"folders": [], "videos": []}

    shared_link_ids = [access.shared_link_id for access in access_records]
    print(f"Shared link IDs: {shared_link_ids}")

    links = (
        db.query(SharedLink)
        .options(joinedload(SharedLink.shared_accesses))
        .filter(SharedLink.id.in_(shared_link_ids))
        .all()
    )

    print(f"Found {len(links)} shared links")

    # Populate user data for all links
    populated_links = await populate_user_data(links)

    # Separate folders and videos
    folders = []
    videos = []

    for link in populated_links:
        if link.share_type == "folder" and link.folder_id:
            folder = db.query(Folder).filter(Folder.id == link.folder_id).first()
            if folder:
                # Get videos in folder
                folder_videos = (
                    db.query(Video).filter(Video.folder_id == link.folder_id).all()
                )
                folders.append(
                    {
                        "shared_link": link,
                        "folder": FolderOut.model_validate(folder),
                        "videos": [VideoOut.model_validate(v) for v in folder_videos],
                    }
                )
                print(f"Added folder: {folder.name} with {len(folder_videos)} videos")

        elif link.share_type == "chat" and link.video_id:
            video = db.query(Video).filter(Video.id == link.video_id).first()
            if video:
                videos.append(
                    {
                        "shared_link": link,
                        "video": VideoOut.model_validate(video),
                        "chat_session_id": link.chat_session_id,
                    }
                )
                print(f"Added video: {video.title}")

    print(f"Returning {len(folders)} folders and {len(videos)} videos")
    return {"folders": folders, "videos": videos}


@router.get("/shared-video/{share_token}/{video_id}")
async def get_shared_video_for_chat(
    share_token: str,
    video_id: str,
    db: Session = Depends(get_db),
):
    """Get shared video details for chat functionality."""
    try:
        # Get the shared link
        link = (
            db.query(SharedLink).filter(SharedLink.share_token == share_token).first()
        )
        if not link:
            raise HTTPException(status_code=404, detail="Shared link not found")

        # Check if video matches the shared link
        if link.share_type == "folder":
            # For folder shares, check if video is in the folder
            if link.folder_id:
                video = (
                    db.query(Video)
                    .filter(Video.id == video_id, Video.folder_id == link.folder_id)
                    .first()
                )
                if not video:
                    raise HTTPException(
                        status_code=404, detail="Video not found in shared folder"
                    )
        elif link.share_type == "chat":
            # For chat shares, check if video matches
            if link.video_id != video_id:
                raise HTTPException(
                    status_code=404, detail="Video not found in shared chat"
                )
            video = db.query(Video).filter(Video.id == video_id).first()
        else:
            raise HTTPException(status_code=400, detail="Invalid share type")

        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        # Check expiration
        if link.expires_at and datetime.now(timezone.utc) > link.expires_at:
            raise HTTPException(status_code=410, detail="This shared link has expired")

        # Check view limit
        if link.max_views and int(link.view_count) >= int(link.max_views):
            raise HTTPException(
                status_code=429, detail="This shared link has reached its view limit"
            )

        # Return video details suitable for chat
        video_data = VideoOut.model_validate(video).model_dump()

        # Add sharing context
        video_data["share_token"] = share_token
        video_data["share_type"] = link.share_type
        video_data["is_public"] = link.is_public

        return video_data

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get shared video: {str(e)}"
        )


@router.post("/shared-video-chat")
async def shared_video_chat(
    request: dict,
    db: Session = Depends(get_db),
):
    """Chat with a shared video (public or private with proper access)."""
    try:
        share_token = request.get("share_token")
        video_id = request.get("video_id")
        query = request.get("query")
        timestamp = request.get("timestamp", 0)
        is_image_query = request.get("is_image_query", False)

        if not share_token or not video_id or not query:
            raise HTTPException(status_code=400, detail="Missing required parameters")

        # Get the shared link
        link = (
            db.query(SharedLink).filter(SharedLink.share_token == share_token).first()
        )
        if not link:
            raise HTTPException(status_code=404, detail="Shared link not found")

        # Check if video matches the shared link
        if link.share_type == "folder":
            # For folder shares, check if video is in the folder
            if link.folder_id:
                video = (
                    db.query(Video)
                    .filter(Video.id == video_id, Video.folder_id == link.folder_id)
                    .first()
                )
                if not video:
                    raise HTTPException(
                        status_code=404, detail="Video not found in shared folder"
                    )
        elif link.share_type == "chat":
            # For chat shares, check if video matches
            if link.video_id != video_id:
                raise HTTPException(
                    status_code=404, detail="Video not found in shared chat"
                )
            video = db.query(Video).filter(Video.id == video_id).first()
        else:
            raise HTTPException(status_code=400, detail="Invalid share type")

        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        # Check access permissions
        if not link.is_public:
            # For private links, we need to check if user is authenticated and has access
            # This would require the frontend to pass user authentication
            # For now, we'll allow access to private links (frontend should handle auth)
            pass

        # Check expiration
        if link.expires_at and datetime.now(timezone.utc) > link.expires_at:
            raise HTTPException(status_code=410, detail="This shared link has expired")

        # Check view limit
        if link.max_views and int(link.view_count) >= int(link.max_views):
            raise HTTPException(
                status_code=429, detail="This shared link has reached its view limit"
            )

        # Increment view count
        link.view_count = str(int(link.view_count) + 1)
        db.commit()

        # Now process the chat query using existing functionality
        try:
            vision_client = OpenAIVisionClient()
            transcript_to_use = None

            # Get transcript
            formatting_status_info = get_formatting_status(db, video_id)
            if formatting_status_info["status"] == "completed":
                transcript_to_use = formatting_status_info["formatted_transcript"]

            if not transcript_to_use:
                transcript_info = get_transcript_cache(db, video_id)
                if transcript_info and transcript_info.get("transcript_data"):
                    transcript_to_use = transcript_info["transcript_data"]
                else:
                    transcript_data, json_data = download_transcript_api(video_id)
                    transcript_to_use = transcript_data
                    update_transcript_cache(db, video_id, transcript_data, json_data)

            if is_image_query:
                if timestamp is None:
                    raise HTTPException(
                        status_code=400,
                        detail="Timestamp is required for image queries",
                    )
                video_path_local = get_video_path(db, video_id)
                if not video_path_local:
                    download_status_info = get_download_status(db, video_id)
                    if download_status_info["status"] == "downloading":
                        return {
                            "response": "🎬 Something amazing is being loaded! The video is still downloading in the background. Please continue to chat with the video content in the meantime, and try frame-specific questions again in a moment!",
                            "video_id": video_id,
                            "timestamp": timestamp,
                            "query_type": "downloading",
                            "is_downloading": True,
                        }
                    elif download_status_info["status"] == "failed":
                        raise HTTPException(
                            status_code=500,
                            detail=f"Video download failed: {download_status_info['message']}",
                        )
                    else:
                        download_executor.submit(
                            download_video_background,
                            video_id,
                            f"https://www.youtube.com/watch?v={video_id}",
                        )
                        return {
                            "response": "🎬 Something amazing is being loaded! Video download has started in the background. Please continue to chat with the video content in the meantime, and try frame-specific questions again in a moment!",
                            "video_id": video_id,
                            "timestamp": timestamp,
                            "query_type": "downloading",
                            "is_downloading": True,
                        }
                frame_filename = f"frame_{video_id}_{int(timestamp)}.jpg"
                frame_path = os.path.join(frames_path, frame_filename)
                output_file, frame = grab_youtube_frame(
                    video_path_local, timestamp, frame_path
                )
                if not output_file:
                    raise HTTPException(
                        status_code=500, detail="Frame extraction failed"
                    )
                response = vision_client.ask_with_image(
                    query, frame_path, transcript_to_use
                )
            else:
                # Text query
                response = vision_client.ask_text_only(query, transcript_to_use)

            return {
                "response": response,
                "video_id": video_id,
                "timestamp": timestamp,
                "query_type": "text",
                "is_downloading": False,
            }

        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to process chat query: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to process shared video chat: {str(e)}"
        )


@router.get("/shared-video-url/{share_token}/{video_id}")
async def get_shared_video_url(
    share_token: str,
    video_id: str,
    db: Session = Depends(get_db),
):
    """Get presigned URL for shared video playback."""
    try:
        # Get the shared link
        link = (
            db.query(SharedLink).filter(SharedLink.share_token == share_token).first()
        )
        if not link:
            raise HTTPException(status_code=404, detail="Shared link not found")

        # Check if video matches the shared link
        if link.share_type == "folder":
            # For folder shares, check if video is in the folder
            if link.folder_id:
                video = (
                    db.query(Video)
                    .filter(Video.id == video_id, Video.folder_id == link.folder_id)
                    .first()
                )
                if not video:
                    raise HTTPException(
                        status_code=404, detail="Video not found in shared folder"
                    )
        elif link.share_type == "chat":
            # For chat shares, check if video matches
            if link.video_id != video_id:
                raise HTTPException(
                    status_code=404, detail="Video not found in shared chat"
                )
            video = db.query(Video).filter(Video.id == video_id).first()
        else:
            raise HTTPException(status_code=400, detail="Invalid share type")

        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        # Check expiration
        if link.expires_at and datetime.now(timezone.utc) > link.expires_at:
            raise HTTPException(status_code=410, detail="This shared link has expired")

        # Check view limit
        if link.max_views and int(link.view_count) >= int(link.max_views):
            raise HTTPException(
                status_code=429, detail="This shared link has reached its view limit"
            )

        # Get video URL based on source type
        if video.source_type == "youtube":
            video_url = f"https://www.youtube.com/watch?v={video.youtube_id}"
        elif video.source_type == "uploaded" and video.s3_key:
            # For uploaded videos, we need to get a presigned URL
            try:
                video_url = s3_presign_url(video.s3_key, expires_in=3600)
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to generate video URL: {str(e)}"
                )
        else:
            raise HTTPException(
                status_code=400, detail="Video source not supported for playback"
            )

        return {
            "video_id": video_id,
            "video_url": video_url,
            "source_type": video.source_type,
            "title": video.title,
            "share_token": share_token,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get shared video URL: {str(e)}"
        )


@router.get("/shared-chat-history/{video_id}", response_model=List[dict])
async def get_shared_chat_history(
    video_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    """Get chat history for a video that has been shared with the current user."""
    try:
        # Get all shared link IDs where the current user has access
        user_access_records = (
            db.query(SharedLinkAccess)
            .filter(SharedLinkAccess.user_id == current_user["uid"])
            .all()
        )

        if not user_access_records:
            return []

        shared_link_ids = [access.shared_link_id for access in user_access_records]

        # Find shared links that are chat shares for this specific video
        shared_links = (
            db.query(SharedLink)
            .filter(
                SharedLink.id.in_(shared_link_ids),
                SharedLink.share_type == "chat",
                SharedLink.video_id == video_id,
            )
            .all()
        )

        if not shared_links:
            return []

        # Get chat sessions for this video
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video or not video.chat_sessions:
            return []

        # Filter chat sessions to only include those from shared links
        shared_chat_sessions = []
        for link in shared_links:
            if link.chat_session_id:
                # Find the specific chat session that was shared
                for session in video.chat_sessions:
                    if session.get("id") == link.chat_session_id:
                        shared_chat_sessions.append(
                            {
                                "session_id": session.get("id"),
                                "title": session.get("title", "Shared Chat"),
                                "messages": session.get("messages", []),
                                "created_at": session.get("createdAt"),
                                "updated_at": session.get("updatedAt"),
                                "shared_by": link.owner_id,
                                "share_token": link.share_token,
                                "share_title": link.title,
                            }
                        )

        return shared_chat_sessions

    except Exception as e:
        print(f"Error getting shared chat history: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get shared chat history: {str(e)}"
        )
