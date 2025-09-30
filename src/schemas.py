from pydantic import BaseModel
from typing import Optional, Dict, Any
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


# Payment and Subscription schemas
class PaymentRequest(BaseModel):
    plan_type: str  # "Vidya Plus" or "Vidya Pro"
    billing_period: str = "monthly"  # "monthly" or "annual"


class SubscriptionResponse(BaseModel):
    plan_type: str
    status: str
    features: Dict[str, Any]
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    
    class Config:
        from_attributes = True


class SubscriptionOut(BaseModel):
    id: str
    user_id: str
    stripe_subscription_id: str
    plan_type: str
    status: str
    current_period_start: Optional[datetime]
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class UserOut(BaseModel):
    id: str
    firebase_uid: str
    email: Optional[str]
    name: Optional[str]
    stripe_customer_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True