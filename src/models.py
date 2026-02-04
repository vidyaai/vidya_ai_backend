import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Text,
    Enum,
    ForeignKey,
    Boolean,
    func,
    Float,
    Integer,
    JSON,
    Boolean,
)
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
    share_type = Column(String, nullable=False)  # "folder", "chat", or "assignment"

    # Resource identifiers
    folder_id = Column(String, ForeignKey("folders.id"), nullable=True)
    video_id = Column(String, ForeignKey("videos.id"), nullable=True)
    chat_session_id = Column(String, nullable=True)  # For specific chat session sharing
    assignment_id = Column(
        String, ForeignKey("assignments.id"), nullable=True
    )  # For assignment sharing

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
    assignment = relationship("Assignment")
    shared_accesses = relationship(
        "SharedLinkAccess", back_populates="shared_link", cascade="all, delete-orphan"
    )


class SharedLinkAccess(Base):
    __tablename__ = "shared_link_access"

    id = Column(String, primary_key=True, default=generate_uuid)
    shared_link_id = Column(String, ForeignKey("shared_links.id"), nullable=False)
    user_id = Column(
        String, nullable=False, index=True
    )  # Firebase UID of invited user (or 'pending_<email>' for pending invites)
    email = Column(String, nullable=True, index=True)  # Email for pending invitations
    permission = Column(
        String, default="view"
    )  # "view", "edit", or "complete" (for assignments)

    # Status tracking
    invited_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    accessed_at = Column(DateTime, nullable=True)  # First access time
    last_accessed_at = Column(DateTime, nullable=True)  # Last access time

    # Relationships
    shared_link = relationship("SharedLink", back_populates="shared_accesses")


# Assignment-related models
class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, index=True, nullable=False)  # Firebase UID of the creator
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    # Assignment metadata
    due_date = Column(DateTime, nullable=True)
    total_points = Column(String, default="0")  # Total points possible
    total_questions = Column(String, default="0")  # Number of questions
    status = Column(String, default="draft")  # "draft", "published", "archived"

    # Assignment configuration
    engineering_level = Column(
        String, default="undergraduate"
    )  # "undergraduate", "graduate"
    engineering_discipline = Column(
        String, default="general"
    )  # "general", "electrical", etc.
    question_types = Column(JSONB, nullable=True)  # Array of question types used
    ai_penalty_percentage = Column(
        Float, default=50.0
    )  # Percentage penalty for AI-flagged answers (0-100)

    # Content sources (for AI-generated assignments)
    linked_videos = Column(JSONB, nullable=True)  # Array of video IDs/data
    uploaded_files = Column(JSONB, nullable=True)  # Array of file metadata
    generation_prompt = Column(Text, nullable=True)  # Original prompt if AI-generated
    generation_options = Column(JSONB, nullable=True)  # AI generation settings

    # Questions data
    questions = Column(JSONB, nullable=False, default=list)  # Array of question objects

    # Sharing and collaboration
    is_template = Column(Boolean, default=False)  # Can be used as template by others
    shared_count = Column(String, default="0")  # Number of times shared

    # External integrations
    google_form_url = Column(String, nullable=True)  # Google Form edit URL
    google_form_response_url = Column(String, nullable=True)  # Google Form response URL

    # Timestamps
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc),
    )

    # Relationships
    submissions = relationship(
        "AssignmentSubmission",
        back_populates="assignment",
        cascade="all, delete-orphan",
    )
    shared_links = relationship(
        "SharedLink", back_populates="assignment", cascade="all, delete-orphan"
    )


class AssignmentSubmission(Base):
    __tablename__ = "assignment_submissions"

    id = Column(String, primary_key=True, default=generate_uuid)
    assignment_id = Column(String, ForeignKey("assignments.id"), nullable=False)
    user_id = Column(String, nullable=False, index=True)  # Firebase UID of submitter

    # Submission data
    answers = Column(JSONB, nullable=False, default=dict)  # User's answers to questions
    submission_method = Column(String, default="in-app")  # "in-app", "pdf", "file"

    # File submissions (for PDF/file uploads)
    submitted_files = Column(JSONB, nullable=True)  # Array of file metadata

    # Grading and feedback
    score = Column(String, nullable=True)  # Points earned
    percentage = Column(String, nullable=True)  # Percentage score
    feedback = Column(
        JSONB, nullable=True
    )  # Question-by-question feedback (includes per-question AI flags)
    overall_feedback = Column(Text, nullable=True)  # General feedback

    # AI Plagiarism Detection (submission-level telemetry, per-question flags in feedback JSONB)
    telemetry_data = Column(
        JSONB, nullable=True
    )  # Frontend behavioral data (paste events, typing speed, tab switches)

    # Status tracking
    status = Column(
        String, default="draft"
    )  # "draft", "submitted", "graded", "returned"
    is_late = Column(Boolean, default=False)
    attempt_number = Column(String, default="1")  # For multiple attempts

    # Time tracking
    time_spent = Column(String, nullable=True)  # Time spent in seconds
    started_at = Column(DateTime, nullable=True)  # When user started
    submitted_at = Column(DateTime, nullable=True)  # When submitted
    graded_at = Column(DateTime, nullable=True)  # When graded

    # Timestamps
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc),
    )

    # Relationships
    assignment = relationship("Assignment", back_populates="submissions")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    firebase_uid = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, nullable=True)
    name = Column(String, nullable=True)
    stripe_customer_id = Column(String, nullable=True, unique=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc),
    )

    # Relationships
    subscriptions = relationship("Subscription", back_populates="user")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    plan_id = Column(String, ForeignKey("pricing_plans.id"), nullable=True, index=True)
    stripe_subscription_id = Column(
        String, unique=True, nullable=True
    )  # Null for free plan
    billing_period = Column(String, nullable=True)  # monthly, annual (null for free)
    status = Column(String, nullable=False)  # active, past_due, cancelled, etc.
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    cancel_at_period_end = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc),
    )

    # Relationships
    user = relationship("User", back_populates="subscriptions")
    plan = relationship("PricingPlan", backref="subscriptions")


class PricingPlan(Base):
    __tablename__ = "pricing_plans"

    id = Column(String, primary_key=True, default=generate_uuid)
    plan_key = Column(
        String, unique=True, nullable=False, index=True
    )  # free, vidya_plus, vidya_pro
    name = Column(String, nullable=False)  # "Free", "Vidya Plus", "Vidya Pro"
    monthly_price = Column(Float, nullable=False, default=0.0)
    annual_price = Column(Float, nullable=False, default=0.0)
    stripe_monthly_price_id = Column(String, nullable=True)
    stripe_annual_price_id = Column(String, nullable=True)
    features = Column(JSON, nullable=False)  # Store features as JSON
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc),
    )


class UserUsage(Base):
    __tablename__ = "user_usage"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(
        String, nullable=False, index=True
    )  # Format: "2026-01-05" for daily tracking
    month_year = Column(
        String, nullable=False, index=True
    )  # Format: "2024-09" for legacy

    # Daily limits tracking
    videos_analyzed_today = Column(
        Integer, default=0, nullable=False
    )  # Videos analyzed per day
    questions_per_video = Column(
        JSON, default={}, nullable=False
    )  # {video_id: question_count}

    # Legacy monthly tracking (kept for backwards compatibility)
    video_uploads_count = Column(Integer, default=0, nullable=False)
    youtube_chats_count = Column(Integer, default=0, nullable=False)
    translation_minutes_used = Column(Float, default=0.0, nullable=False)

    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc),
    )

    # Relationship
    user = relationship("User", backref="usage_records")


class LectureSummary(Base):
    __tablename__ = "lecture_summaries"

    id = Column(String, primary_key=True, default=generate_uuid)
    video_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    summary_markdown = Column(Text, nullable=False)
    summary_pdf_s3_key = Column(String, nullable=True)
    summary_metadata = Column(JSON, nullable=True)  # topics, video_title, generation_time, etc.
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc),
    )
