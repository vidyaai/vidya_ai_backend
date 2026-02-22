from pydantic import BaseModel
from typing import Optional, Dict, Any, List
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
    conversation_history: Optional[List[Dict[str, Any]]] = []
    session_id: Optional[str] = None


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
    course_id: Optional[str] = None
    due_date: Optional[datetime] = None
    status: str = "draft"
    engineering_level: str = "undergraduate"
    engineering_discipline: str = "general"
    question_types: Optional[List[str]] = None
    linked_videos: Optional[List[dict]] = None
    uploaded_files: Optional[List[dict]] = None
    generation_prompt: Optional[str] = None
    generation_options: Optional[dict] = None
    questions: List[dict] = []
    is_template: bool = False
    ai_penalty_percentage: float = 50.0


class AssignmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    course_id: Optional[str] = None
    due_date: Optional[datetime] = None
    status: Optional[str] = None
    engineering_level: Optional[str] = None
    engineering_discipline: Optional[str] = None
    question_types: Optional[List[str]] = None
    questions: Optional[List[dict]] = None
    is_template: Optional[bool] = None
    ai_penalty_percentage: Optional[float] = None


class AssignmentOut(BaseModel):
    id: str
    user_id: str
    title: str
    description: Optional[str] = None
    course_id: Optional[str] = None
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
    google_form_url: Optional[str] = None
    google_form_response_url: Optional[str] = None
    ai_penalty_percentage: Optional[float] = 50.0

    class Config:
        from_attributes = True


class AssignmentSummary(BaseModel):
    """Lightweight assignment info for lists"""

    id: str
    title: str
    description: Optional[str] = None
    course_id: Optional[str] = None
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
    shared_with_user_ids: List[str] = []  # Firebase UIDs
    pending_emails: List[str] = []  # Emails for users not yet registered
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


# AI Plagiarism Detection Schemas
class TelemetryData(BaseModel):
    """Behavioral telemetry captured from frontend during submission.

    Supports two formats:
    1. Legacy (submission-level): {"pasted": bool, "pasteCount": int, ...}
    2. New (per-question): {"per_question": {"1": {...}, "2": {...}}, "submission_level": {...}}
    """

    # Legacy format fields (submission-level)
    pasted: Optional[bool] = None
    pasteCount: Optional[int] = None
    tabSwitches: Optional[int] = None
    timeToComplete: Optional[int] = None  # milliseconds
    time_taken_seconds: Optional[int] = None  # seconds
    typingSpeed: Optional[float] = None  # words per minute

    # New format fields
    per_question: Optional[Dict[str, Any]] = None  # Question ID -> telemetry mapping
    submission_level: Optional[Dict[str, Any]] = None  # Overall submission metrics

    class Config:
        extra = "allow"  # Allow additional fields for flexibility


class AIFlagInfo(BaseModel):
    """AI plagiarism detection result for a single question."""

    flag_level: str  # "none", "soft", "hard"
    confidence: float  # 0.0 to 1.0
    reasons: List[str]  # List of detection reasons
    model_score: float  # Stylometric model score
    telemetry_score: float  # Behavioral telemetry score
    original_score: Optional[float] = None  # Score before penalty
    penalized_score: Optional[float] = None  # Score after penalty (for hard flags)
    override_status: Optional[
        Dict[str, Any]
    ] = None  # {"overridden": bool, "by": user_id, "at": timestamp, "reason": str, "action": str}
    timestamp: Optional[datetime] = None


class AIFlagOverrideRequest(BaseModel):
    """Request to override an AI flag on a specific question."""

    question_id: str
    action: str  # "dismiss", "apply_penalty", "remove_penalty"
    reason: Optional[str] = None


class SubmissionAnswerCreate(BaseModel):
    question_id: int
    answer: str  # JSON string or text answer
    time_spent: Optional[int] = None  # Time spent on this question in seconds


class AssignmentSubmissionCreate(BaseModel):
    assignment_id: str
    # Answers can be plain text (string) or structured objects containing optional diagram metadata
    # Structure examples:
    # {
    #   "7": {
    #       "text": "Circuit explanation",
    #       "diagram": {
    #           "s3_key": "submissions/<submission_id>/diagrams/q7.jpg",
    #           "file_id": "<uuid>",
    #           "filename": "circuit.jpg",
    #           "bounding_box": {"x": 120, "y": 240, "width": 460, "height": 320, "page_number": 1}
    #       }
    #   },
    #   "9": {
    #       "subAnswers": {
    #           "1": "Sub-answer 1",
    #           "2": {"text": "Sub-answer 2", "diagram": { ... }}
    #       }
    #   }
    # }
    answers: dict  # Question ID -> answer mapping (see above structure)
    submission_method: str = "in-app"
    submitted_files: Optional[List[dict]] = None
    time_spent: Optional[str] = None
    telemetry_data: Optional[
        Dict[str, Any]
    ] = None  # Behavioral telemetry for AI detection - supports legacy and per-question formats


class AssignmentSubmissionDraft(BaseModel):
    # Same structure as AssignmentSubmissionCreate.answers
    answers: dict
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
    submitted_by_user_id: Optional[
        str
    ] = None  # Who submitted on behalf (for bulk uploads)
    answers: dict
    submission_method: str
    submitted_files: Optional[List[dict]] = None
    score: Optional[str] = None
    percentage: Optional[str] = None
    feedback: Optional[dict] = None
    overall_feedback: Optional[str] = None
    telemetry_data: Optional[Dict[str, Any]] = None  # Behavioral telemetry
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


# Diagram-aware answer structures (for documentation and request/response typing)
class DiagramBoundingBox(BaseModel):
    x: int
    y: int
    width: int
    height: int
    page_number: Optional[int] = None  # Present for PDF-derived diagrams


class DiagramRef(BaseModel):
    s3_key: str
    file_id: Optional[str] = None
    filename: Optional[str] = None
    content_type: Optional[str] = None
    bounding_box: Optional[DiagramBoundingBox] = None


class AnswerWithDiagram(BaseModel):
    text: Optional[str] = None
    diagram: Optional[DiagramRef] = None  # One diagram per answer/sub-answer
    subAnswers: Optional[
        Dict[str, Any]
    ] = None  # Nested answers (may be string or AnswerWithDiagram)


# Grading API schemas
class GradeSubmissionOptions(BaseModel):
    regrade: bool = False
    max_tokens: Optional[int] = 8000
    model: Optional[str] = "gpt-4o"  # Vision-enabled for diagram grading
    temperature: Optional[float] = 0.1


class GradeSubmissionRequest(BaseModel):
    options: Optional[GradeSubmissionOptions] = None


class BatchGradeRequest(BaseModel):
    submission_ids: List[str]
    options: Optional[GradeSubmissionOptions] = None


class BatchGradeResponse(BaseModel):
    message: str
    queued_count: int
    submission_ids: List[str]
    status: str  # "queued" for background processing


class QuestionGradeFeedback(BaseModel):
    score: float
    max_points: float
    breakdown: Optional[str] = None
    strengths: Optional[str] = None
    areas_for_improvement: Optional[str] = None
    rubric_alignment: Optional[Dict[str, Any]] = None
    ai_flag: Optional[
        Dict[str, Any]
    ] = None  # AI plagiarism detection info (AIFlagInfo)


class GradeSubmissionResponse(BaseModel):
    submission_id: str
    assignment_id: str
    total_score: float
    total_points: float
    percentage: float
    overall_feedback: Optional[str] = None
    feedback_by_question: Dict[str, QuestionGradeFeedback]
    graded_at: datetime


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


# Diagram Upload Schemas
class DiagramUploadResponse(BaseModel):
    file_id: str
    filename: str
    content_type: str
    size: int
    s3_key: str
    url: str
    uploaded_at: str


class DiagramDeleteResponse(BaseModel):
    message: str
    file_id: str
    deleted_keys: List[str]


# Update MultiPartSubQuestion to handle forward reference
MultiPartSubQuestion.model_rebuild()


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


# Lecture Summary schemas
class LectureSummaryRequest(BaseModel):
    video_id: str
    force_regenerate: bool = False


class LectureSummaryResponse(BaseModel):
    summary_id: str
    video_id: str
    created_at: datetime
    summary_metadata: Optional[dict] = None

    class Config:
        from_attributes = True


# ── Course Organization Schemas ──────────────────────────────────────────


class CourseCreate(BaseModel):
    title: str
    description: Optional[str] = None
    course_code: Optional[str] = None
    semester: Optional[str] = None


class CourseUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    course_code: Optional[str] = None
    semester: Optional[str] = None
    is_active: Optional[bool] = None


class CourseOut(BaseModel):
    id: str
    user_id: str
    title: str
    description: Optional[str] = None
    course_code: Optional[str] = None
    semester: Optional[str] = None
    is_active: bool
    enrollment_code: Optional[str] = None
    enrollment_count: int = 0
    assignment_count: int = 0
    material_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EnrollStudentItem(BaseModel):
    email: str


class EnrollStudentsRequest(BaseModel):
    students: List[EnrollStudentItem]
    role: str = "student"
    send_email: bool = False


class EnrollmentOut(BaseModel):
    id: str
    course_id: str
    user_id: str
    email: Optional[str] = None
    role: str
    status: str
    enrolled_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EnrollmentResultOut(BaseModel):
    enrolled: int
    pending: int
    failed: List[str]
    enrollments: List[EnrollmentOut]


class CourseMaterialLinkVideo(BaseModel):
    video_id: str
    title: str
    description: Optional[str] = None
    folder: Optional[str] = None


class CourseMaterialOut(BaseModel):
    id: str
    course_id: str
    title: str
    description: Optional[str] = None
    material_type: str
    s3_key: Optional[str] = None
    video_id: Optional[str] = None
    external_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[str] = None
    mime_type: Optional[str] = None
    order: int = 0
    folder: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
