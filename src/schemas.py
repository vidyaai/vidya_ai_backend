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


# Assignment-related schemas
class QuestionBase(BaseModel):
    id: int
    type: str
    question: str
    points: int
    rubric: Optional[str] = None
    order: Optional[int] = None


class MultipleChoiceQuestion(QuestionBase):
    options: List[str]
    correct_answer: str


class CodeWritingQuestion(QuestionBase):
    code_language: str = "python"
    output_type: str = "code"
    starter_code: Optional[str] = None


class DiagramAnalysisQuestion(QuestionBase):
    analysis_type: str = "description"
    diagram: Optional[dict] = None  # {file: str, url: str}


class MultiPartSubQuestion(BaseModel):
    id: int
    question: str
    points: int
    type: str
    # Type-specific fields
    options: Optional[List[str]] = None
    correct_answer: Optional[str] = None
    code_language: Optional[str] = None
    has_sub_code: Optional[bool] = False
    sub_code: Optional[str] = None
    has_sub_diagram: Optional[bool] = False
    sub_diagram: Optional[dict] = None
    subquestions: Optional[List["MultiPartSubQuestion"]] = None  # For nested multi-part


class MultiPartQuestion(QuestionBase):
    subquestions: List[MultiPartSubQuestion]
    has_main_code: Optional[bool] = False
    has_main_diagram: Optional[bool] = False
    main_code_language: Optional[str] = "python"
    main_code: Optional[str] = None
    main_diagram: Optional[dict] = None


class AssignmentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    engineering_level: str = "undergraduate"
    engineering_discipline: str = "general"
    question_types: Optional[List[str]] = None
    linked_videos: Optional[List[dict]] = None
    uploaded_files: Optional[List[dict]] = None
    generation_prompt: Optional[str] = None
    generation_options: Optional[dict] = None
    questions: List[dict] = []
    is_template: bool = False


class AssignmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    status: Optional[str] = None
    engineering_level: Optional[str] = None
    engineering_discipline: Optional[str] = None
    question_types: Optional[List[str]] = None
    questions: Optional[List[dict]] = None
    is_template: Optional[bool] = None


class AssignmentOut(BaseModel):
    id: str
    user_id: str
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    total_points: str
    total_questions: str
    status: str
    engineering_level: str
    engineering_discipline: str
    question_types: Optional[List[str]] = None
    linked_videos: Optional[List[dict]] = None
    uploaded_files: Optional[List[dict]] = None
    generation_prompt: Optional[str] = None
    generation_options: Optional[dict] = None
    questions: List[dict]
    is_template: bool
    shared_count: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AssignmentSummary(BaseModel):
    """Lightweight assignment info for lists"""

    id: str
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    total_points: str
    total_questions: str
    status: str
    engineering_level: str
    engineering_discipline: str
    question_types: Optional[List[str]] = None
    shared_count: str
    created_at: datetime

    class Config:
        from_attributes = True


class ShareAssignmentRequest(BaseModel):
    assignment_id: str
    shared_with_user_ids: List[str]  # Firebase UIDs
    permission: str = "view"  # "view", "edit", "complete"
    title: Optional[str] = None  # Custom title for the shared assignment
    description: Optional[str] = None  # Optional description
    is_public: bool = False  # Whether this creates a public link
    expires_at: Optional[datetime] = None  # Optional expiration date


class SharedAssignmentOut(BaseModel):
    id: str
    share_token: str  # The shareable token/link
    assignment_id: str
    owner_id: str  # The user who shared the assignment
    owner_name: Optional[str] = None  # Display name of the owner
    owner_email: Optional[str] = None  # Email of the owner
    title: Optional[str] = None
    description: Optional[str] = None
    is_public: bool
    expires_at: Optional[datetime] = None
    created_at: datetime
    assignment: Optional[AssignmentOut] = None
    shared_accesses: Optional[List[dict]] = None  # List of users with access

    class Config:
        from_attributes = True


class SharedAssignmentAccessOut(BaseModel):
    id: str
    user_id: str
    permission: str
    invited_at: datetime
    accessed_at: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SubmissionAnswerCreate(BaseModel):
    question_id: int
    answer: str  # JSON string or text answer
    time_spent: Optional[int] = None  # Time spent on this question in seconds


class AssignmentSubmissionCreate(BaseModel):
    assignment_id: str
    answers: dict  # Question ID -> answer mapping
    submission_method: str = "in-app"
    submitted_files: Optional[List[dict]] = None
    time_spent: Optional[str] = None


class AssignmentSubmissionDraft(BaseModel):
    answers: dict  # Question ID -> answer mapping
    submission_method: str = "in-app"
    submitted_files: Optional[List[dict]] = None
    time_spent: Optional[str] = None


class AssignmentSubmissionUpdate(BaseModel):
    answers: Optional[dict] = None
    status: Optional[str] = None
    score: Optional[str] = None
    percentage: Optional[str] = None
    feedback: Optional[dict] = None
    overall_feedback: Optional[str] = None
    submitted_files: Optional[List[dict]] = None


class AssignmentSubmissionOut(BaseModel):
    id: str
    assignment_id: str
    user_id: str
    answers: dict
    submission_method: str
    submitted_files: Optional[List[dict]] = None
    score: Optional[str] = None
    percentage: Optional[str] = None
    feedback: Optional[dict] = None
    overall_feedback: Optional[str] = None
    status: str
    is_late: bool
    attempt_number: str
    time_spent: Optional[str] = None
    started_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    graded_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    assignment: Optional[AssignmentOut] = None

    class Config:
        from_attributes = True


class AssignmentGenerateRequest(BaseModel):
    """Request for AI assignment generation"""

    linked_videos: Optional[List[dict]] = None
    uploaded_files: Optional[List[dict]] = None
    generation_prompt: Optional[str] = None
    generation_options: dict
    title: Optional[str] = None
    description: Optional[str] = None


class DocumentImportRequest(BaseModel):
    """Request for document import and parsing"""

    file_content: str  # Base64 encoded file content or plain text
    file_name: str
    file_type: str  # MIME type or file extension
    generation_options: Optional[dict] = None  # Additional parsing options


class DocumentImportResponse(BaseModel):
    """Response from document import"""

    title: str
    description: Optional[str] = None
    questions: List[dict]
    extracted_text: Optional[str] = None  # For debugging/review purposes
    file_info: dict  # Original file metadata


# Update MultiPartSubQuestion to handle forward reference
MultiPartSubQuestion.model_rebuild()
