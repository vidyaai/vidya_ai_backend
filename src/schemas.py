from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[str] = None
    source_type: str  # "uploaded" | "youtube"


class FolderOut(BaseModel):
    id: str
    user_id: str
    name: str
    parent_id: Optional[str]
    source_type: str

    class Config:
        from_attributes = True


class VideoOut(BaseModel):
    id: str
    user_id: Optional[str] = None
    source_type: str
    title: Optional[str] = None
    youtube_id: Optional[str] = None
    youtube_url: Optional[str] = None
    s3_key: Optional[str] = None
    thumb_key: Optional[str] = None
    transcript_s3_key: Optional[str] = None
    local_path: Optional[str] = None
    transcript_text: Optional[str] = None
    formatted_transcript: Optional[str] = None
    folder_id: Optional[str] = None

    class Config:
        from_attributes = True


class MoveVideoRequest(BaseModel):
    video_id: str
    target_folder_id: Optional[str]


class DeleteVideoRequest(BaseModel):
    video_id: str


class DeleteFolderRequest(BaseModel):
    folder_id: str
    confirm_delete_videos: bool = False


# Requests used by routes
class YouTubeRequest(BaseModel):
    url: str


class VideoQuery(BaseModel):
    video_id: str
    query: str
    timestamp: Optional[float] = None
    is_image_query: bool = False


class TranslationRequest(BaseModel):
    youtube_url: str
    source_language: str = "en"
    target_language: str


class QuizRequest(BaseModel):
    video_id: str
    num_questions: int = 5
    difficulty: str = "medium"
    include_explanations: bool = True
    language: str = "en"


# Sharing-related schemas
class FirebaseUser(BaseModel):
    uid: str
    email: Optional[str] = None
    displayName: Optional[str] = None
    photoURL: Optional[str] = None


class CreateSharedLinkRequest(BaseModel):
    share_type: str  # "folder" or "chat"
    folder_id: Optional[str] = None
    video_id: Optional[str] = None
    chat_session_id: Optional[str] = None
    is_public: bool = False
    title: Optional[str] = None
    description: Optional[str] = None
    expires_at: Optional[datetime] = None
    max_views: Optional[int] = None
    invited_users: List[str] = []  # List of Firebase UIDs


class UpdateSharedLinkRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    is_public: Optional[bool] = None
    expires_at: Optional[datetime] = None
    max_views: Optional[int] = None


class SharedLinkAccessOut(BaseModel):
    id: str
    user_id: str
    permission: str
    invited_at: datetime
    accessed_at: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None
    user: Optional[FirebaseUser] = None  # Populated from Firebase

    class Config:
        from_attributes = True


class SharedLinkOut(BaseModel):
    id: str
    share_token: str
    owner_id: str
    share_type: str
    folder_id: Optional[str] = None
    video_id: Optional[str] = None
    chat_session_id: Optional[str] = None
    is_public: bool
    title: Optional[str] = None
    description: Optional[str] = None
    expires_at: Optional[datetime] = None
    max_views: Optional[int] = None
    view_count: int
    created_at: datetime
    updated_at: datetime
    shared_accesses: List[SharedLinkAccessOut] = []
    owner: Optional[FirebaseUser] = None  # Populated from Firebase

    class Config:
        from_attributes = True


class ShareEmailSearchRequest(BaseModel):
    query: str


class AddUsersToSharedLinkRequest(BaseModel):
    user_ids: List[str]  # Firebase UIDs
    permission: str = "view"  # "view" or "edit"


class RemoveUserFromSharedLinkRequest(BaseModel):
    user_id: str


class PublicSharedResourceOut(BaseModel):
    """Public view of shared resource - limited information"""

    share_token: str
    share_type: str
    title: Optional[str] = None
    description: Optional[str] = None
    owner_display_name: Optional[str] = None
    created_at: datetime
    # Resource data will be included separately based on type
