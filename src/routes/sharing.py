"""Sharing functionality routes for folders and chat sessions."""
import secrets
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_

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

router = APIRouter(tags=["Sharing"], prefix="/api/sharing")


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
