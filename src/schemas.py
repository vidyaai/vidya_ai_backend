from pydantic import BaseModel
from typing import Optional


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
