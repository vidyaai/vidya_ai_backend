import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, Enum, ForeignKey, Boolean, func, Float, Integer, JSON
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

    # Organization
    folder_id = Column(String, ForeignKey("folders.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)

    folder = relationship("Folder", back_populates="videos")


class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    firebase_uid = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, nullable=True)
    name = Column(String, nullable=True)
    stripe_customer_id = Column(String, nullable=True, unique=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    
    # Relationships
    subscriptions = relationship("Subscription", back_populates="user")


class Subscription(Base):
    __tablename__ = "subscriptions"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    plan_id = Column(String, ForeignKey("pricing_plans.id"), nullable=True, index=True)
    stripe_subscription_id = Column(String, unique=True, nullable=True)  # Null for free plan
    billing_period = Column(String, nullable=True)  # monthly, annual (null for free)
    status = Column(String, nullable=False)  # active, past_due, cancelled, etc.
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    cancel_at_period_end = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User", back_populates="subscriptions")
    plan = relationship("PricingPlan", backref="subscriptions")


class PricingPlan(Base):
    __tablename__ = "pricing_plans"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    plan_key = Column(String, unique=True, nullable=False, index=True)  # free, vidya_plus, vidya_pro
    name = Column(String, nullable=False)  # "Free", "Vidya Plus", "Vidya Pro"
    monthly_price = Column(Float, nullable=False, default=0.0)
    annual_price = Column(Float, nullable=False, default=0.0)
    stripe_monthly_price_id = Column(String, nullable=True)
    stripe_annual_price_id = Column(String, nullable=True)
    features = Column(JSON, nullable=False)  # Store features as JSON
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class UserUsage(Base):
    __tablename__ = "user_usage"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    month_year = Column(String, nullable=False, index=True)  # Format: "2024-09"
    video_uploads_count = Column(Integer, default=0, nullable=False)
    youtube_chats_count = Column(Integer, default=0, nullable=False)
    translation_minutes_used = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    
    # Relationship
    user = relationship("User", backref="usage_records")