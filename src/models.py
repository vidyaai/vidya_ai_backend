import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, Enum, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from utils.db import Base


class SourceTypeEnum(str):
    UPLOADED = "uploaded"
    YOUTUBE = "youtube"


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Folder(Base):
    __tablename__ = "folders"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    parent_id = Column(String, ForeignKey("folders.id"), nullable=True)
    source_type = Column(String, nullable=False, index=True)  # "uploaded" or "youtube"
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)

    parent = relationship("Folder", remote_side=[id])
    videos = relationship("Video", back_populates="folder")


class Video(Base):
    __tablename__ = "videos"

    id = Column(
        String, primary_key=True
    )  # we align with existing video_id (uuid or youtube id)
    user_id = Column(String, index=True, nullable=True)
    source_type = Column(String, nullable=False, index=True)  # "uploaded" or "youtube"
    title = Column(String, nullable=True)

    # YouTube specific
    youtube_id = Column(String, index=True, nullable=True)
    youtube_url = Column(String, nullable=True)

    # Uploaded specific / storage
    s3_key = Column(String, nullable=True)
    thumb_key = Column(String, nullable=True)
    transcript_s3_key = Column(String, nullable=True)
    local_path = Column(String, nullable=True)

    # Transcripts and formatting
    transcript_text = Column(Text, nullable=True)
    transcript_json = Column(JSONB, nullable=True)
    formatted_transcript = Column(Text, nullable=True)
    formatting_status = Column(JSONB, nullable=True)

    # Download and processing status
    download_status = Column(JSONB, nullable=True)  # Stores download progress/status
    download_path = Column(String, nullable=True)  # Path to downloaded video file

    # Upload progress tracking
    upload_status = Column(JSONB, nullable=True)  # Stores upload progress/status

    # Chat history per video per user (array of sessions with messages)
    chat_sessions = Column(JSONB, nullable=True)

    # Organization
    folder_id = Column(String, ForeignKey("folders.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)

    folder = relationship("Folder", back_populates="videos")


class ShareTypeEnum(str):
    FOLDER = "folder"
    CHAT = "chat"


class SharedLink(Base):
    __tablename__ = "shared_links"

    id = Column(String, primary_key=True, default=generate_uuid)
    share_token = Column(
        String, unique=True, nullable=False, index=True
    )  # Public shareable token
    owner_id = Column(String, nullable=False, index=True)  # Firebase UID of the owner
    share_type = Column(String, nullable=False)  # "folder" or "chat"

    # Resource identifiers
    folder_id = Column(String, ForeignKey("folders.id"), nullable=True)
    video_id = Column(String, ForeignKey("videos.id"), nullable=True)
    chat_session_id = Column(String, nullable=True)  # For specific chat session sharing

    # Sharing settings
    is_public = Column(
        Boolean, default=False
    )  # True for public links, False for invite-only
    title = Column(String, nullable=True)  # Custom title for the shared link
    description = Column(String, nullable=True)  # Optional description

    # Access control
    expires_at = Column(DateTime, nullable=True)  # Optional expiration date
    max_views = Column(String, nullable=True)  # Optional view limit
    view_count = Column(String, default="0")  # Current view count

    # Metadata
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc),
    )

    # Relationships
    folder = relationship("Folder")
    video = relationship("Video")
    shared_accesses = relationship(
        "SharedLinkAccess", back_populates="shared_link", cascade="all, delete-orphan"
    )


class SharedLinkAccess(Base):
    __tablename__ = "shared_link_access"

    id = Column(String, primary_key=True, default=generate_uuid)
    shared_link_id = Column(String, ForeignKey("shared_links.id"), nullable=False)
    user_id = Column(String, nullable=False, index=True)  # Firebase UID of invited user
    permission = Column(String, default="view")  # "view" or "edit"

    # Status tracking
    invited_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    accessed_at = Column(DateTime, nullable=True)  # First access time
    last_accessed_at = Column(DateTime, nullable=True)  # Last access time

    # Relationships
    shared_link = relationship("SharedLink", back_populates="shared_accesses")
