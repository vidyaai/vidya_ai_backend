import base64
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Request,
    UploadFile,
    File,
    Form,
)
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, asc
from typing import List, Optional
from datetime import datetime, timezone
import json
import secrets
import string
import uuid
import os
import mimetypes

from utils.db import get_db
from controllers.config import logger, s3_client, AWS_S3_BUCKET
from controllers.storage import s3_upload_file, s3_presign_url
from utils.firebase_auth import get_current_user
from models import Assignment, SharedLink, SharedLinkAccess, AssignmentSubmission, Video
from schemas import (
    AssignmentCreate,
    AssignmentUpdate,
    AssignmentOut,
    AssignmentSummary,
    ShareAssignmentRequest,
    SharedAssignmentOut,
    SharedAssignmentAccessOut,
    AssignmentSubmissionDraft,
    AssignmentSubmissionUpdate,
    AssignmentSubmissionOut,
    AssignmentGenerateRequest,
    DocumentImportRequest,
    DocumentImportResponse,
    DiagramUploadResponse,
    DiagramDeleteResponse,
    GradeSubmissionRequest,
    GradeSubmissionResponse,
    BatchGradeRequest,
    BatchGradeResponse,
)
from fastapi.responses import Response
from utils.pdf_generator import AssignmentPDFGenerator
from utils.google_forms_service import get_google_forms_service

router = APIRouter()


def generate_share_token() -> str:
    """Generate a random share token"""
    return "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(32)
    )


def calculate_assignment_stats(assignment: Assignment) -> Assignment:
    """Calculate total points and questions for an assignment, handling optional parts correctly"""
    questions = assignment.questions or []
    total_questions = len(questions)

    def calculate_question_points(question: dict) -> float:
        """Recursively calculate points for a question, accounting for optional parts"""
        q_type = question.get("type", "")

        if q_type == "multi-part":
            subquestions = question.get("subquestions", [])
            if not subquestions:
                return float(question.get("points", 0))

            # For optional parts, only count required number of parts
            if question.get("optionalParts"):
                required_count = question.get("requiredPartsCount", len(subquestions))
                # Sort subquestions by points (descending) to get realistic total
                # This assumes students will choose higher-point questions
                subq_points = [calculate_question_points(sq) for sq in subquestions]
                subq_points.sort(reverse=True)
                # Sum only the required number of highest-point subquestions
                return sum(subq_points[:required_count])
            else:
                # Non-optional multi-part: sum all subquestion points
                return sum(calculate_question_points(sq) for sq in subquestions)
        else:
            # Regular question: return its points
            return float(question.get("points", 0))

    total_points = sum(calculate_question_points(q) for q in questions)

    assignment.total_questions = str(total_questions)
    assignment.total_points = str(int(total_points))
    return assignment


@router.post(
    "/api/assignments/{assignment_id}/submissions/{submission_id}/grade",
    response_model=GradeSubmissionResponse,
)
async def grade_submission_endpoint(
    assignment_id: str,
    submission_id: str,
    grade_req: GradeSubmissionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Trigger AI grading for a submission."""
    try:
        user_id = current_user["uid"]

        # Verify assignment ownership or edit permission
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
            )

        is_owner = assignment.user_id == user_id
        has_edit_access = (
            db.query(SharedLinkAccess)
            .join(SharedLink)
            .filter(
                and_(
                    SharedLink.assignment_id == assignment_id,
                    SharedLink.share_type == "assignment",
                    SharedLinkAccess.user_id == user_id,
                    SharedLinkAccess.permission == "edit",
                )
            )
            .first()
            is not None
        )

        if not (is_owner or has_edit_access):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to grade"
            )

        submission = (
            db.query(AssignmentSubmission)
            .filter(
                and_(
                    AssignmentSubmission.id == submission_id,
                    AssignmentSubmission.assignment_id == assignment_id,
                )
            )
            .first()
        )
        if not submission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
            )

        # Prepare assignment dict for grader
        assignment = calculate_assignment_stats(assignment)
        assignment_dict = {
            "id": assignment.id,
            "title": assignment.title,
            "questions": assignment.questions or [],
        }

        # Run grading
        from utils.grading_service import LLMGrader

        grader = LLMGrader(
            model=(
                grade_req.options.model
                if grade_req and grade_req.options and grade_req.options.model
                else "gpt-4o"
            )
        )
        (
            total_score,
            total_points,
            feedback_by_question,
            overall_feedback,
        ) = grader.grade_submission(
            assignment=assignment_dict,
            submission_answers=submission.answers or {},
            options=(
                grade_req.options.dict() if grade_req and grade_req.options else None
            ),
        )

        submission.score = f"{total_score:.2f}"
        submission.percentage = (
            f"{(total_score/total_points*100.0) if total_points>0 else 0.0:.2f}"
        )
        submission.feedback = feedback_by_question
        submission.overall_feedback = overall_feedback
        submission.status = "graded"
        submission.graded_at = datetime.now(timezone.utc)
        submission.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(submission)

        return {
            "submission_id": submission.id,
            "assignment_id": assignment_id,
            "total_score": float(total_score),
            "total_points": float(total_points),
            "percentage": float(submission.percentage),
            "overall_feedback": overall_feedback,
            "feedback_by_question": feedback_by_question,
            "graded_at": submission.graded_at,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(
            f"Error grading submission {submission_id} for assignment {assignment_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to grade submission",
        )


@router.post(
    "/api/assignments/{assignment_id}/submissions/batch-grade",
    response_model=BatchGradeResponse,
)
async def batch_grade_submissions(
    assignment_id: str,
    batch_req: BatchGradeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Trigger batch AI grading for multiple submissions (background processing)."""
    try:
        user_id = current_user["uid"]

        # Verify assignment ownership or edit permission
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
            )

        is_owner = assignment.user_id == user_id
        has_edit_access = (
            db.query(SharedLinkAccess)
            .join(SharedLink)
            .filter(
                and_(
                    SharedLink.assignment_id == assignment_id,
                    SharedLink.share_type == "assignment",
                    SharedLinkAccess.user_id == user_id,
                    SharedLinkAccess.permission == "edit",
                )
            )
            .first()
            is not None
        )

        if not (is_owner or has_edit_access):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to grade"
            )

        # Validate all submissions exist and belong to this assignment
        valid_submission_ids = []
        for sub_id in batch_req.submission_ids:
            submission = (
                db.query(AssignmentSubmission)
                .filter(
                    and_(
                        AssignmentSubmission.id == sub_id,
                        AssignmentSubmission.assignment_id == assignment_id,
                    )
                )
                .first()
            )
            if submission and submission.status == "submitted":
                # Mark as grading in progress
                submission.status = "grading"
                submission.updated_at = datetime.now(timezone.utc)
                valid_submission_ids.append(sub_id)

        db.commit()

        # Queue background grading task
        from controllers.background_tasks import queue_batch_grading

        queue_batch_grading(assignment_id, valid_submission_ids, batch_req.options)

        logger.info(f"Queued {len(valid_submission_ids)} submissions for grading")

        return {
            "message": f"Grading queued for {len(valid_submission_ids)} submissions",
            "queued_count": len(valid_submission_ids),
            "submission_ids": valid_submission_ids,
            "status": "queued",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(
            f"Error queueing batch grading for assignment {assignment_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue grading",
        )


def filter_sensitive_data_for_students(
    assignment_data: dict, user_id: str, db: Session
) -> dict:
    """Remove sensitive data (rubric, correctAnswer) from assignment for students without edit permission"""
    # Check if user is the owner
    if assignment_data.get("user_id") == user_id:
        return assignment_data  # Owner can see everything

    # Check if user has edit permission via shared access
    has_edit_permission = (
        db.query(SharedLinkAccess)
        .join(SharedLink)
        .filter(
            and_(
                SharedLink.assignment_id == assignment_data.get("id"),
                SharedLink.share_type == "assignment",
                SharedLinkAccess.user_id == user_id,
                SharedLinkAccess.permission == "edit",
            )
        )
        .first()
        is not None
    )

    if has_edit_permission:
        return assignment_data  # User with edit permission can see everything

    # Filter out sensitive data for students
    filtered_data = assignment_data.copy()
    if "questions" in filtered_data and filtered_data["questions"]:
        filtered_questions = []
        for question in filtered_data["questions"]:
            filtered_question = question.copy()
            # Remove sensitive fields
            filtered_question.pop("rubric", None)
            filtered_question.pop("correctAnswer", None)
            filtered_question.pop(
                "correct_answer", None
            )  # Handle both naming conventions

            # Handle subquestions for multi-part questions
            if "subquestions" in filtered_question:
                filtered_subquestions = []
                for subq in filtered_question["subquestions"]:
                    filtered_subq = subq.copy()
                    filtered_subq.pop("rubric", None)
                    filtered_subq.pop("correctAnswer", None)
                    filtered_subq.pop("correct_answer", None)

                    # Handle nested subquestions
                    if "subquestions" in filtered_subq:
                        nested_filtered = []
                        for nested_subq in filtered_subq["subquestions"]:
                            nested_filtered_subq = nested_subq.copy()
                            nested_filtered_subq.pop("rubric", None)
                            nested_filtered_subq.pop("correctAnswer", None)
                            nested_filtered_subq.pop("correct_answer", None)
                            nested_filtered.append(nested_filtered_subq)
                        filtered_subq["subquestions"] = nested_filtered

                    filtered_subquestions.append(filtered_subq)
                filtered_question["subquestions"] = filtered_subquestions

            filtered_questions.append(filtered_question)
        filtered_data["questions"] = filtered_questions

    return filtered_data


@router.get("/api/assignments", response_model=List[AssignmentSummary])
async def get_user_assignments(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    status_filter: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
):
    """Get all assignments created by the current user"""
    try:
        user_id = current_user["uid"]
        logger.info(f"Fetching assignments for user: {user_id}")

        # Build query
        query = db.query(Assignment).filter(Assignment.user_id == user_id)

        # Apply status filter
        if status_filter:
            query = query.filter(Assignment.status == status_filter)

        # Apply sorting
        if sort_by == "created_at":
            order_col = Assignment.created_at
        elif sort_by == "updated_at":
            order_col = Assignment.updated_at
        elif sort_by == "title":
            order_col = Assignment.title
        elif sort_by == "due_date":
            order_col = Assignment.due_date
        else:
            order_col = Assignment.created_at

        if sort_order == "asc":
            query = query.order_by(asc(order_col))
        else:
            query = query.order_by(desc(order_col))

        assignments = query.all()

        # Calculate stats for each assignment
        for assignment in assignments:
            assignment = calculate_assignment_stats(assignment)

        logger.info(f"Found {len(assignments)} assignments for user {user_id}")
        return assignments

    except Exception as e:
        logger.error(f"Error fetching assignments: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch assignments",
        )


@router.get("/api/assignments/shared-with-me", response_model=List[SharedAssignmentOut])
async def get_shared_assignments(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    status_filter: Optional[str] = None,
):
    """Get assignments shared with the current user"""
    try:
        user_id = current_user["uid"]
        logger.info(f"Fetching shared assignments for user: {user_id}")

        # Build query to get shared links with assignment access
        query = (
            db.query(SharedLink)
            .join(SharedLinkAccess, SharedLink.id == SharedLinkAccess.shared_link_id)
            .join(Assignment, SharedLink.assignment_id == Assignment.id)
            .filter(
                and_(
                    SharedLink.share_type == "assignment",
                    SharedLinkAccess.user_id == user_id,
                )
            )
        )

        # Apply status filter to the assignment
        if status_filter:
            query = query.filter(Assignment.status == status_filter)

        shared_links = query.order_by(desc(SharedLink.created_at)).all()

        # Collect all unique owner IDs to fetch user information
        owner_ids = set()
        for shared_link in shared_links:
            owner_ids.add(shared_link.owner_id)

        # Fetch user information for all owners
        from utils.firebase_users import get_users_by_uids

        users_data = await get_users_by_uids(list(owner_ids))
        users_map = {user["uid"]: user for user in users_data}

        # Convert to the expected format
        shared_assignments = []
        for shared_link in shared_links:
            if shared_link.assignment:
                assignment = calculate_assignment_stats(shared_link.assignment)
                # Get the user's access details
                access = (
                    db.query(SharedLinkAccess)
                    .filter(
                        and_(
                            SharedLinkAccess.shared_link_id == shared_link.id,
                            SharedLinkAccess.user_id == user_id,
                        )
                    )
                    .first()
                )

                # Get owner information
                owner_info = users_map.get(shared_link.owner_id, {})

                # Convert assignment to dict for filtering
                assignment_dict = {
                    "id": assignment.id,
                    "user_id": assignment.user_id,
                    "title": assignment.title,
                    "description": assignment.description,
                    "due_date": assignment.due_date,
                    "total_points": assignment.total_points,
                    "total_questions": assignment.total_questions,
                    "status": assignment.status,
                    "engineering_level": assignment.engineering_level,
                    "engineering_discipline": assignment.engineering_discipline,
                    "question_types": assignment.question_types,
                    "linked_videos": assignment.linked_videos,
                    "uploaded_files": assignment.uploaded_files,
                    "generation_prompt": assignment.generation_prompt,
                    "generation_options": assignment.generation_options,
                    "questions": assignment.questions,
                    "is_template": assignment.is_template,
                    "shared_count": assignment.shared_count,
                    "created_at": assignment.created_at,
                    "updated_at": assignment.updated_at,
                }

                # Filter sensitive data for students
                filtered_assignment = filter_sensitive_data_for_students(
                    assignment_dict, user_id, db
                )

                shared_assignment_data = {
                    "id": shared_link.id,
                    "share_token": shared_link.share_token,
                    "assignment_id": shared_link.assignment_id,
                    "owner_id": shared_link.owner_id,
                    "owner_name": owner_info.get("displayName", shared_link.owner_id),
                    "owner_email": owner_info.get("email", ""),
                    "title": shared_link.title,
                    "description": shared_link.description,
                    "is_public": shared_link.is_public,
                    "expires_at": shared_link.expires_at,
                    "created_at": shared_link.created_at,
                    "assignment": filtered_assignment,
                    "shared_accesses": [
                        {
                            "id": access.id,
                            "user_id": access.user_id,
                            "permission": access.permission,
                            "invited_at": access.invited_at,
                            "accessed_at": access.accessed_at,
                            "last_accessed_at": access.last_accessed_at,
                        }
                    ]
                    if access
                    else [],
                }
                shared_assignments.append(shared_assignment_data)

        logger.info(
            f"Found {len(shared_assignments)} shared assignments for user {user_id}"
        )
        return shared_assignments

    except Exception as e:
        logger.error(f"Error fetching shared assignments: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch shared assignments",
        )


@router.get("/api/assignments/available-videos")
async def get_available_videos_for_assignment(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get available videos for assignment generation"""
    try:
        user_id = current_user["uid"]
        logger.info(f"Fetching available videos for user: {user_id}")

        # Get user's videos with transcripts
        videos = (
            db.query(Video)
            .filter(
                and_(
                    Video.user_id == user_id,
                    Video.transcript_text.isnot(None),
                    Video.transcript_text != "",
                )
            )
            .order_by(desc(Video.created_at))
            .all()
        )

        # Format videos for frontend
        available_videos = []
        for video in videos:
            video_data = {
                "id": video.id,
                "title": video.title or "Untitled Video",
                "source_type": video.source_type,
                "youtube_id": video.youtube_id,
                "youtube_url": video.youtube_url,
                "transcript_text": video.transcript_text,
                "created_at": video.created_at.isoformat()
                if video.created_at
                else None,
            }
            available_videos.append(video_data)

        logger.info(
            f"Found {len(available_videos)} videos with transcripts for user {user_id}"
        )
        return {"videos": available_videos}

    except Exception as e:
        logger.error(f"Error fetching available videos: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch available videos",
        )


@router.get("/api/assignments/{assignment_id}", response_model=AssignmentOut)
async def get_assignment(
    assignment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get a specific assignment by ID"""
    try:
        user_id = current_user["uid"]
        logger.info(f"Fetching assignment {assignment_id} for user: {user_id}")

        # Check if user owns the assignment or has shared access
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()

        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
            )

        # Check access permissions
        has_access = (
            assignment.user_id == user_id
            or db.query(SharedLinkAccess)  # Owner
            .join(SharedLink)
            .filter(
                and_(
                    SharedLink.assignment_id == assignment_id,
                    SharedLink.share_type == "assignment",
                    SharedLinkAccess.user_id == user_id,
                )
            )
            .first()
            is not None  # Shared with user
        )

        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this assignment",
            )

        # Calculate stats
        assignment = calculate_assignment_stats(assignment)

        # Convert to dict and filter sensitive data for students
        assignment_dict = {
            "id": assignment.id,
            "user_id": assignment.user_id,
            "title": assignment.title,
            "description": assignment.description,
            "due_date": assignment.due_date,
            "total_points": assignment.total_points,
            "total_questions": assignment.total_questions,
            "status": assignment.status,
            "engineering_level": assignment.engineering_level,
            "engineering_discipline": assignment.engineering_discipline,
            "question_types": assignment.question_types,
            "linked_videos": assignment.linked_videos,
            "uploaded_files": assignment.uploaded_files,
            "generation_prompt": assignment.generation_prompt,
            "generation_options": assignment.generation_options,
            "questions": assignment.questions,
            "is_template": assignment.is_template,
            "shared_count": assignment.shared_count,
            "created_at": assignment.created_at,
            "updated_at": assignment.updated_at,
        }

        # Filter sensitive data for students
        filtered_assignment = filter_sensitive_data_for_students(
            assignment_dict, user_id, db
        )

        logger.info(f"Retrieved assignment: {assignment.title}")
        return filtered_assignment

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching assignment {assignment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch assignment",
        )


@router.post("/api/assignments", response_model=AssignmentOut)
async def create_assignment(
    assignment_data: AssignmentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Create a new assignment"""
    try:
        user_id = current_user["uid"]
        logger.info(f"Creating assignment for user: {user_id}")

        # Create assignment
        assignment = Assignment(
            user_id=user_id,
            title=assignment_data.title,
            description=assignment_data.description,
            due_date=assignment_data.due_date,
            engineering_level=assignment_data.engineering_level,
            engineering_discipline=assignment_data.engineering_discipline,
            question_types=assignment_data.question_types,
            linked_videos=assignment_data.linked_videos,
            uploaded_files=assignment_data.uploaded_files,
            generation_prompt=assignment_data.generation_prompt,
            generation_options=assignment_data.generation_options,
            questions=assignment_data.questions,
            is_template=assignment_data.is_template,
        )

        # Calculate stats
        assignment = calculate_assignment_stats(assignment)

        db.add(assignment)
        db.commit()
        db.refresh(assignment)

        logger.info(f"Created assignment: {assignment.id} - {assignment.title}")
        return assignment

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating assignment: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create assignment",
        )


@router.put("/api/assignments/{assignment_id}", response_model=AssignmentOut)
async def update_assignment(
    assignment_id: str,
    assignment_data: AssignmentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Update an existing assignment"""
    try:
        user_id = current_user["uid"]
        logger.info(f"Updating assignment {assignment_id} for user: {user_id}")

        # Get assignment
        assignment = (
            db.query(Assignment)
            .filter(and_(Assignment.id == assignment_id, Assignment.user_id == user_id))
            .first()
        )

        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Assignment not found or access denied",
            )

        # Update fields
        update_data = assignment_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(assignment, field, value)

        # Recalculate stats if questions were updated
        if "questions" in update_data:
            assignment = calculate_assignment_stats(assignment)

        assignment.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(assignment)

        logger.info(f"Updated assignment: {assignment.id} - {assignment.title}")
        return assignment

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating assignment {assignment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update assignment",
        )


@router.delete("/api/assignments/{assignment_id}")
async def delete_assignment(
    assignment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Delete an assignment"""
    try:
        user_id = current_user["uid"]
        logger.info(f"Deleting assignment {assignment_id} for user: {user_id}")

        # Get assignment
        assignment = (
            db.query(Assignment)
            .filter(and_(Assignment.id == assignment_id, Assignment.user_id == user_id))
            .first()
        )

        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Assignment not found or access denied",
            )

        # Delete assignment (cascades will handle related records)
        db.delete(assignment)
        db.commit()

        logger.info(f"Deleted assignment: {assignment_id}")
        return {"message": "Assignment deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting assignment {assignment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete assignment",
        )


@router.post(
    "/api/assignments/{assignment_id}/share", response_model=SharedAssignmentOut
)
async def share_assignment(
    assignment_id: str,
    share_data: ShareAssignmentRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Share an assignment with other users via SharedLink"""
    try:
        user_id = current_user["uid"]
        logger.info(f"Sharing assignment {assignment_id} by user: {user_id}")

        # Verify assignment ownership
        assignment = (
            db.query(Assignment)
            .filter(and_(Assignment.id == assignment_id, Assignment.user_id == user_id))
            .first()
        )

        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Assignment not found or access denied",
            )

        # Check if a shared link already exists for this assignment
        existing_shared_link = (
            db.query(SharedLink)
            .filter(
                and_(
                    SharedLink.assignment_id == assignment_id,
                    SharedLink.owner_id == user_id,
                    SharedLink.share_type == "assignment",
                )
            )
            .first()
        )

        if existing_shared_link:
            shared_link = existing_shared_link
            # Update existing shared link
            shared_link.title = share_data.title or shared_link.title
            shared_link.description = share_data.description or shared_link.description
            shared_link.is_public = share_data.is_public
            shared_link.expires_at = share_data.expires_at
        else:
            # Create new shared link
            shared_link = SharedLink(
                share_token=generate_share_token(),
                owner_id=user_id,
                share_type="assignment",
                assignment_id=assignment_id,
                title=share_data.title or f"Shared Assignment: {assignment.title}",
                description=share_data.description,
                is_public=share_data.is_public,
                expires_at=share_data.expires_at,
            )
            db.add(shared_link)
            db.flush()  # Get the ID

        # Create or update shared access records for each user
        shared_accesses = []
        for shared_with_user_id in share_data.shared_with_user_ids:
            # Check if user already has access
            existing_access = (
                db.query(SharedLinkAccess)
                .filter(
                    and_(
                        SharedLinkAccess.shared_link_id == shared_link.id,
                        SharedLinkAccess.user_id == shared_with_user_id,
                    )
                )
                .first()
            )

            if existing_access:
                # Update existing access
                existing_access.permission = share_data.permission
                shared_accesses.append(existing_access)
            else:
                # Create new access
                shared_access = SharedLinkAccess(
                    shared_link_id=shared_link.id,
                    user_id=shared_with_user_id,
                    permission=share_data.permission,
                )
                db.add(shared_access)
                shared_accesses.append(shared_access)

        db.commit()
        db.refresh(shared_link)

        total_users = (
            db.query(SharedLinkAccess)
            .filter(SharedLinkAccess.shared_link_id == shared_link.id)
            .count()
        )
        logger.info(f"total_users: {total_users}")
        assignment.shared_count = str(total_users)

        db.commit()
        db.refresh(shared_link)

        # Prepare response
        assignment = calculate_assignment_stats(assignment)
        response_data = {
            "id": shared_link.id,
            "share_token": shared_link.share_token,
            "assignment_id": shared_link.assignment_id,
            "owner_id": shared_link.owner_id,
            "title": shared_link.title,
            "description": shared_link.description,
            "is_public": shared_link.is_public,
            "expires_at": shared_link.expires_at,
            "created_at": shared_link.created_at,
            "assignment": assignment,
            "shared_accesses": [
                {
                    "id": access.id,
                    "user_id": access.user_id,
                    "permission": access.permission,
                    "invited_at": access.invited_at,
                    "accessed_at": access.accessed_at,
                    "last_accessed_at": access.last_accessed_at,
                }
                for access in shared_accesses
            ],
        }

        logger.info(
            f"Shared assignment {assignment_id} with {len(share_data.shared_with_user_ids)} users"
        )
        return response_data

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error sharing assignment {assignment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to share assignment",
        )


@router.put(
    "/api/assignments/{assignment_id}/share/{share_id}",
    response_model=SharedAssignmentOut,
)
async def update_shared_assignment(
    assignment_id: str,
    share_id: str,
    share_data: ShareAssignmentRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Update an existing shared assignment link"""
    try:
        user_id = current_user["uid"]
        logger.info(
            f"Updating shared assignment link {share_id} for assignment {assignment_id} by user: {user_id}"
        )

        # Verify assignment ownership and shared link ownership
        shared_link = (
            db.query(SharedLink)
            .filter(
                and_(
                    SharedLink.id == share_id,
                    SharedLink.assignment_id == assignment_id,
                    SharedLink.owner_id == user_id,
                    SharedLink.share_type == "assignment",
                )
            )
            .first()
        )

        if not shared_link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Shared assignment link not found or access denied",
            )

        # Update shared link properties
        shared_link.title = share_data.title or shared_link.title
        shared_link.description = share_data.description
        shared_link.is_public = share_data.is_public
        shared_link.expires_at = share_data.expires_at

        # Update or create shared access records for each user
        shared_accesses = []
        for shared_with_user_id in share_data.shared_with_user_ids:
            # Check if user already has access
            existing_access = (
                db.query(SharedLinkAccess)
                .filter(
                    and_(
                        SharedLinkAccess.shared_link_id == shared_link.id,
                        SharedLinkAccess.user_id == shared_with_user_id,
                    )
                )
                .first()
            )

            if existing_access:
                # Update existing access
                existing_access.permission = share_data.permission
                shared_accesses.append(existing_access)
            else:
                # Create new access
                shared_access = SharedLinkAccess(
                    shared_link_id=shared_link.id,
                    user_id=shared_with_user_id,
                    permission=share_data.permission,
                )
                db.add(shared_access)
                shared_accesses.append(shared_access)

        # Remove access for users not in the new list
        existing_accesses = (
            db.query(SharedLinkAccess)
            .filter(SharedLinkAccess.shared_link_id == shared_link.id)
            .all()
        )

        for access in existing_accesses:
            if access.user_id not in share_data.shared_with_user_ids:
                db.delete(access)

        # Update shared count
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if assignment:
            total_users = len(share_data.shared_with_user_ids)
            assignment.shared_count = str(total_users)

        db.commit()
        db.refresh(shared_link)

        # Prepare response
        assignment = calculate_assignment_stats(assignment)
        response_data = {
            "id": shared_link.id,
            "share_token": shared_link.share_token,
            "assignment_id": shared_link.assignment_id,
            "owner_id": shared_link.owner_id,
            "title": shared_link.title,
            "description": shared_link.description,
            "is_public": shared_link.is_public,
            "expires_at": shared_link.expires_at,
            "created_at": shared_link.created_at,
            "assignment": assignment,
            "shared_accesses": [
                {
                    "id": access.id,
                    "user_id": access.user_id,
                    "permission": access.permission,
                    "invited_at": access.invited_at,
                    "accessed_at": access.accessed_at,
                    "last_accessed_at": access.last_accessed_at,
                }
                for access in shared_accesses
            ],
        }

        logger.info(f"Updated shared assignment link {share_id}")
        return response_data

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating shared assignment link {share_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update shared assignment link",
        )


@router.delete("/api/assignments/{assignment_id}/share/{share_id}")
async def delete_shared_assignment(
    assignment_id: str,
    share_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Delete a shared assignment link"""
    try:
        user_id = current_user["uid"]
        logger.info(
            f"Deleting shared assignment link {share_id} for assignment {assignment_id} by user: {user_id}"
        )

        # Verify assignment ownership and shared link ownership
        shared_link = (
            db.query(SharedLink)
            .filter(
                and_(
                    SharedLink.id == share_id,
                    SharedLink.assignment_id == assignment_id,
                    SharedLink.owner_id == user_id,
                    SharedLink.share_type == "assignment",
                )
            )
            .first()
        )

        if not shared_link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Shared assignment link not found or access denied",
            )

        # Delete the shared link (cascade will handle shared_accesses)
        db.delete(shared_link)

        # Update shared count
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if assignment:
            assignment.shared_count = "0"

        db.commit()

        logger.info(f"Deleted shared assignment link {share_id}")
        return {"message": "Shared assignment link deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting shared assignment link {share_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete shared assignment link",
        )


@router.get(
    "/api/assignments/{assignment_id}/share", response_model=SharedAssignmentOut
)
async def get_shared_assignment_link(
    assignment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get the shared assignment link for an assignment"""
    try:
        user_id = current_user["uid"]
        logger.info(
            f"Getting shared assignment link for assignment {assignment_id} by user: {user_id}"
        )

        # Verify assignment ownership
        assignment = (
            db.query(Assignment)
            .filter(and_(Assignment.id == assignment_id, Assignment.user_id == user_id))
            .first()
        )

        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Assignment not found or access denied",
            )

        # Find the shared link for this assignment
        shared_link = (
            db.query(SharedLink)
            .filter(
                and_(
                    SharedLink.assignment_id == assignment_id,
                    SharedLink.owner_id == user_id,
                    SharedLink.share_type == "assignment",
                )
            )
            .first()
        )

        if not shared_link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No shared link found for this assignment",
            )

        # Get all shared accesses for this link
        shared_accesses = (
            db.query(SharedLinkAccess)
            .filter(SharedLinkAccess.shared_link_id == shared_link.id)
            .all()
        )

        # Calculate assignment stats
        assignment = calculate_assignment_stats(assignment)

        # Prepare response
        response_data = {
            "id": shared_link.id,
            "share_token": shared_link.share_token,
            "assignment_id": shared_link.assignment_id,
            "owner_id": shared_link.owner_id,
            "title": shared_link.title,
            "description": shared_link.description,
            "is_public": shared_link.is_public,
            "expires_at": shared_link.expires_at,
            "created_at": shared_link.created_at,
            "assignment": assignment,
            "shared_accesses": [
                {
                    "id": access.id,
                    "user_id": access.user_id,
                    "permission": access.permission,
                    "invited_at": access.invited_at,
                    "accessed_at": access.accessed_at,
                    "last_accessed_at": access.last_accessed_at,
                }
                for access in shared_accesses
            ],
        }

        logger.info(
            f"Found shared assignment link {shared_link.id} for assignment {assignment_id}"
        )
        return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting shared assignment link for assignment {assignment_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get shared assignment link",
        )


@router.delete("/api/assignments/share/{share_id}/users")
async def remove_user_from_shared_assignment(
    share_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Remove a user from a shared assignment link"""
    try:
        user_id = current_user["uid"]
        request_data = await request.json()
        user_to_remove = request_data.get("user_id")

        if not user_to_remove:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="user_id is required"
            )

        logger.info(
            f"Removing user {user_to_remove} from shared assignment link {share_id} by user: {user_id}"
        )

        # Verify shared link ownership
        shared_link = (
            db.query(SharedLink)
            .filter(
                and_(
                    SharedLink.id == share_id,
                    SharedLink.owner_id == user_id,
                    SharedLink.share_type == "assignment",
                )
            )
            .first()
        )

        if not shared_link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Shared assignment link not found or access denied",
            )

        # Find and remove the user's access
        user_access = (
            db.query(SharedLinkAccess)
            .filter(
                and_(
                    SharedLinkAccess.shared_link_id == share_id,
                    SharedLinkAccess.user_id == user_to_remove,
                )
            )
            .first()
        )

        if not user_access:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User access not found"
            )

        db.delete(user_access)

        # Update shared count
        assignment = (
            db.query(Assignment)
            .filter(Assignment.id == shared_link.assignment_id)
            .first()
        )
        if assignment:
            remaining_users = (
                db.query(SharedLinkAccess)
                .filter(SharedLinkAccess.shared_link_id == share_id)
                .count()
                - 1
            )  # -1 because we haven't committed yet
            assignment.shared_count = str(max(0, remaining_users))

        db.commit()

        logger.info(
            f"Removed user {user_to_remove} from shared assignment link {share_id}"
        )
        return {"message": "User removed from shared assignment successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(
            f"Error removing user from shared assignment link {share_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove user from shared assignment",
        )


@router.post("/api/assignments/generate", response_model=AssignmentOut)
async def generate_assignment(
    generate_data: AssignmentGenerateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Generate an assignment using AI"""
    try:
        user_id = current_user["uid"]
        logger.info(f"Generating assignment for user: {user_id}")

        # Import the assignment generator
        from utils.assignment_generator import AssignmentGenerator

        # Initialize the generator
        generator = AssignmentGenerator()

        # Generate assignment using AI
        generated_data = generator.generate_assignment(
            generation_options=generate_data.generation_options,
            linked_videos=generate_data.linked_videos,
            uploaded_files=generate_data.uploaded_files,
            generation_prompt=generate_data.generation_prompt,
            title=generate_data.title,
            description=generate_data.description,
        )

        # Extract question types for database storage
        question_types = []
        for q_type, enabled in generate_data.generation_options.get(
            "questionTypes", {}
        ).items():
            if enabled:
                question_types.append(q_type)

        # Create assignment
        assignment = Assignment(
            user_id=user_id,
            title=generated_data["title"],
            description=generated_data["description"],
            engineering_level=generate_data.generation_options.get(
                "engineeringLevel", "undergraduate"
            ),
            engineering_discipline=generate_data.generation_options.get(
                "engineeringDiscipline", "general"
            ),
            question_types=question_types,
            linked_videos=generate_data.linked_videos,
            uploaded_files=generate_data.uploaded_files,
            generation_prompt=generate_data.generation_prompt,
            generation_options=generate_data.generation_options,
            questions=generated_data["questions"],
            status="draft",
        )

        # Calculate stats
        assignment = calculate_assignment_stats(assignment)

        db.add(assignment)
        db.commit()
        db.refresh(assignment)

        logger.info(f"Generated assignment: {assignment.id} - {assignment.title}")
        return assignment

    except Exception as e:
        db.rollback()
        logger.error(f"Error generating assignment: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate assignment:" + str(e),
        )


@router.post("/api/assignments/import-document", response_model=DocumentImportResponse)
async def import_document_to_assignment(
    request: Request,
    current_user: dict = Depends(get_current_user),
    file: UploadFile = File(None),
    file_name: str = Form(None),
    file_type: str = Form(None),
    generation_options: str = Form(None),
    # Legacy support for base64 JSON
    import_data: DocumentImportRequest = None,
):
    """Import assignment questions from documents (PDF, DOCX, MD, HTML, CSV, JSON, TXT) using AI parsing with diagram support

    Supports two modes:
    1. File upload (multipart/form-data) - Preferred for better performance
    2. Legacy base64 JSON - For backward compatibility
    """
    try:
        user_id = current_user["uid"]

        # Determine if this is a file upload or JSON request
        is_file_upload = file is not None

        if is_file_upload:
            # File upload mode (preferred)
            actual_file_name = file_name or file.filename
            actual_file_type = file_type or file.content_type
            logger.info(
                f"Importing document via file upload: {actual_file_name} ({actual_file_type}) for user: {user_id}"
            )

            # Read file content
            document_content = await file.read()

            # Parse generation options
            gen_options = None
            if generation_options:
                try:
                    gen_options = json.loads(generation_options)
                except:
                    gen_options = None

            if import_data is None:
                import_data = DocumentImportRequest(
                    file_name=actual_file_name,
                    file_type=actual_file_type,
                    generation_options=gen_options,
                    file_content="",
                )
        else:
            # Legacy base64 JSON mode (backward compatibility)
            if import_data is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Either file upload or import_data JSON is required",
                )

            actual_file_name = import_data.file_name
            actual_file_type = import_data.file_type
            gen_options = import_data.generation_options

            logger.info(
                f"Importing document via base64 JSON: {actual_file_name} ({actual_file_type}) for user: {user_id}"
            )

            # Decode document content
            try:
                document_content = base64.b64decode(import_data.file_content)
            except Exception as e:
                logger.error(f"Error decoding document content: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid file content. Please ensure the file is properly encoded.",
                )

        # Validate supported file types
        supported_types = [
            "application/pdf",
            # "text/plain",
            # "application/msword",
            # "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            # "text/markdown",
            # "text/html",
            # "text/csv",
            # "application/json",
        ]

        # Also check file extension
        file_extension = (
            actual_file_name.lower().split(".")[-1] if "." in actual_file_name else ""
        )

        if actual_file_type not in supported_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type: {actual_file_type}. Supported types: PDF",
                # detail=f"Unsupported file type: {actual_file_type}. Supported types: PDF, DOCX, TXT, MD, HTML, CSV, JSON",
            )

        # Import document processing services
        from utils.assignment_document_parser import AssignmentDocumentParser

        # Initialize parser
        assignment_parser = AssignmentDocumentParser(user_id=user_id)

        # Parse document based on type
        try:
            if actual_file_type == "application/pdf" or file_extension == "pdf":
                # PDF: Use image-based parsing with diagram bounding boxes
                parsed_assignment = assignment_parser.parse_pdf_images_to_assignment(
                    document_content,
                    actual_file_name,
                    gen_options,
                )

                # logger.info(f"Parsed assignment: {parsed_assignment}")

                # # Extract diagrams from PDF and upload to S3
                # parsed_assignment = assignment_parser.extract_and_upload_diagrams(
                #     parsed_assignment,
                #     document_content,
                #     "application/pdf",
                #     user_id,
                #     assignment_id=None,  # Temporary storage under user_id
                # )

                # logger.info(f"Parsed assignment after extracting diagrams: {parsed_assignment}")

                text_preview = "PDF content processed via image analysis"
            else:
                # Non-PDF: Use text-based parsing
                parsed_assignment = (
                    assignment_parser.parse_non_pdf_document_to_assignment(
                        document_content,
                        actual_file_name,
                        actual_file_type,
                        user_id,
                        gen_options,
                    )
                )

                logger.info(
                    f"Parsed assignment after parsing non-PDF document: {parsed_assignment}"
                )

                if (
                    actual_file_type
                    == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ):
                    # For DOCX: extract and upload diagrams
                    # DOCX images already extracted during parsing, but run extraction pipeline for consistency
                    parsed_assignment = assignment_parser.extract_and_upload_diagrams(
                        parsed_assignment,
                        document_content,
                        actual_file_type,
                        user_id,
                        assignment_id=None,
                    )

                text_preview = f"{actual_file_type} content processed"

                logger.info(
                    f"Parsed assignment after extracting diagrams: {parsed_assignment}"
                )

        except Exception as e:
            logger.error(f"Error parsing document with AI: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to extract assignment questions from document. Please ensure the document contains assignment questions, exercises, or problems. Error: {str(e)}",
            )

        # Prepare the response
        response_data = DocumentImportResponse(
            title=parsed_assignment.get(
                "title", f"Assignment from {import_data.file_name}"
            ),
            description=parsed_assignment.get("description"),
            questions=parsed_assignment.get("questions", []),
            extracted_text=text_preview,  # Preview of extracted text
            file_info={
                "original_filename": import_data.file_name,
                "file_type": import_data.file_type,
                "content_length": len(text_preview),
                "questions_generated": len(parsed_assignment.get("questions", [])),
                "total_points": parsed_assignment.get("total_points", 0),
            },
        )

        # Debug: Log first question's answer and rubric
        if parsed_assignment.get("questions"):
            first_q = parsed_assignment["questions"][0]
            logger.info(
                f"DEBUG - First question before response: ID={first_q.get('id')}, "
                f"correctAnswer='{first_q.get('correctAnswer', 'MISSING')}', "
                f"rubric='{first_q.get('rubric', 'MISSING')[:50]}...'"
            )

        logger.info(
            f"Successfully imported document {import_data.file_name}: "
            f"{len(parsed_assignment.get('questions', []))} questions generated"
        )

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error importing document {import_data.file_name if import_data else 'unknown file'}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to import document",
        )


# Submission endpoints
@router.get(
    "/api/assignments/{assignment_id}/submissions",
    response_model=List[AssignmentSubmissionOut],
)
async def get_assignment_submissions(
    assignment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get all submissions for an assignment (assignment owner only)"""
    try:
        user_id = current_user["uid"]
        logger.info(
            f"Fetching submissions for assignment {assignment_id} by user: {user_id}"
        )

        # Verify assignment ownership
        assignment = (
            db.query(Assignment)
            .filter(and_(Assignment.id == assignment_id, Assignment.user_id == user_id))
            .first()
        )

        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Assignment not found or access denied",
            )

        # Get submissions
        submissions = (
            db.query(AssignmentSubmission)
            .filter(AssignmentSubmission.assignment_id == assignment_id)
            .order_by(desc(AssignmentSubmission.submitted_at))
            .all()
        )

        logger.info(
            f"Found {len(submissions)} submissions for assignment {assignment_id}"
        )
        return submissions

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error fetching submissions for assignment {assignment_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch submissions",
        )


@router.post(
    "/api/assignments/{assignment_id}/submit", response_model=AssignmentSubmissionOut
)
async def submit_assignment(
    assignment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Submit an assignment - handles both in-app and PDF submissions."""
    try:
        user_id = current_user["uid"]
        logger.info(f"Submitting assignment {assignment_id} by user: {user_id}")

        # Verify assignment access
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
            )

        # Check if user has access to submit
        has_access = (
            assignment.user_id == user_id
            or db.query(SharedLinkAccess)  # Owner can submit (for testing)
            .join(SharedLink)
            .filter(
                and_(
                    SharedLink.assignment_id == assignment_id,
                    SharedLink.share_type == "assignment",
                    SharedLinkAccess.user_id == user_id,
                    SharedLinkAccess.permission.in_(["complete", "edit"]),
                )
            )
            .first()
            is not None
        )

        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to submit this assignment",
            )

        # Parse body supporting both JSON and multipart form (for PDF)
        content_type = request.headers.get("content-type", "")
        from schemas import AssignmentSubmissionDraft as _SubmissionDraft
        import json as _json

        submission_data: _SubmissionDraft

        if "multipart/form-data" in content_type:
            form = await request.form()
            submission_method = form.get("submission_method") or "pdf"
            answers_raw = form.get("answers") or "{}"
            time_spent = form.get("time_spent") or "0"
            submitted_files_raw = form.get("submitted_files")
            uploaded_file = form.get("file")  # type: ignore

            # Build submitted_files from uploaded file if provided
            submitted_files = None
            if uploaded_file is not None:
                # uploaded_file is a Starlette UploadFile
                file_bytes = await uploaded_file.read()
                import uuid, tempfile, os as _os

                tmp_path = None
                try:
                    with tempfile.NamedTemporaryFile(
                        delete=False, suffix=".pdf"
                    ) as tmp:
                        tmp.write(file_bytes)
                        tmp_path = tmp.name
                    # Upload to S3 under assignment uploads path
                    file_id = str(uuid.uuid4())
                    s3_key = f"assignments/{assignment_id}/uploads/{file_id}.pdf"
                    s3_upload_file(
                        tmp_path,
                        s3_key,
                        content_type=uploaded_file.content_type or "application/pdf",
                    )
                finally:
                    try:
                        if tmp_path and _os.path.exists(tmp_path):
                            _os.unlink(tmp_path)
                    except Exception:
                        pass

                submitted_files = [
                    {
                        "s3_key": s3_key,
                        "file_id": file_id,
                        "filename": uploaded_file.filename,
                        "content_type": uploaded_file.content_type or "application/pdf",
                        "size": len(file_bytes),
                        "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    }
                ]
            elif submitted_files_raw:
                try:
                    submitted_files = _json.loads(submitted_files_raw)
                except Exception:
                    submitted_files = None

            try:
                answers_obj = _json.loads(answers_raw)
            except Exception:
                answers_obj = {}

            submission_data = _SubmissionDraft(
                answers=answers_obj,
                submission_method=submission_method,
                submitted_files=submitted_files,
                time_spent=time_spent,
            )
        else:
            # JSON body
            body_json = await request.json()
            submission_data = _SubmissionDraft(**body_json)

        # Check for existing submission
        existing_submission = (
            db.query(AssignmentSubmission)
            .filter(
                and_(
                    AssignmentSubmission.assignment_id == assignment_id,
                    AssignmentSubmission.user_id == user_id,
                )
            )
            .first()
        )

        # Handle PDF submission method - convert PDF to JSON immediately
        if (
            submission_data.submission_method == "pdf"
            and submission_data.submitted_files
        ):
            # Get the PDF file from submitted_files
            pdf_file_info = (
                submission_data.submitted_files[0]
                if submission_data.submitted_files
                else None
            )

            if pdf_file_info and pdf_file_info.get("s3_key"):
                try:
                    # Download PDF from S3 temporarily
                    import tempfile

                    with tempfile.NamedTemporaryFile(
                        delete=False, suffix=".pdf"
                    ) as tmp:
                        s3_client.download_fileobj(
                            AWS_S3_BUCKET, pdf_file_info["s3_key"], tmp
                        )
                        tmp_pdf_path = tmp.name

                    # Convert PDF to JSON using PDFAnswerProcessor
                    from utils.pdf_answer_processor import PDFAnswerProcessor

                    processor = PDFAnswerProcessor()
                    answers_from_pdf = processor.process_pdf_to_json(tmp_pdf_path)

                    # Clean up temp file
                    os.unlink(tmp_pdf_path)

                    # Override answers with extracted data
                    submission_data.answers = answers_from_pdf

                    logger.info(
                        f"Converted PDF to JSON for submission: {len(answers_from_pdf)} answers extracted"
                    )

                except Exception as e:
                    logger.error(f"Error processing PDF to JSON: {str(e)}")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to process PDF submission: {str(e)}",
                    )

        # Validate optional parts selection
        questions = assignment.questions or []
        for question in questions:
            q_id = str(question.get("id"))
            if question.get("type") == "multi-part" and question.get("optionalParts"):
                required_count = question.get("requiredPartsCount", 0)
                answer_obj = submission_data.answers.get(q_id)

                answered_subqs = []
                if answer_obj and isinstance(answer_obj, dict):
                    subanswers = answer_obj.get("subAnswers", {})
                    # Count non-empty answers
                    answered_subqs = [k for k, v in subanswers.items() if v]

                if len(answered_subqs) != required_count:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Question {q_id}: Must answer exactly {required_count} of {len(question.get('subquestions', []))} parts (answered {len(answered_subqs)})",
                    )

                # Recursively validate nested optional parts
                if question.get("subquestions"):
                    for subq in question.get("subquestions", []):
                        subq_id = str(subq.get("id"))
                        if subq.get("type") == "multi-part" and subq.get(
                            "optionalParts"
                        ):
                            subq_required_count = subq.get("requiredPartsCount", 0)
                            subq_answer = (
                                answer_obj.get("subAnswers", {}).get(subq_id)
                                if answer_obj
                                else None
                            )

                            subq_answered = []
                            if subq_answer and isinstance(subq_answer, dict):
                                subq_subanswers = subq_answer.get("subAnswers", {})
                                subq_answered = [
                                    k for k, v in subq_subanswers.items() if v
                                ]

                            if len(subq_answered) != subq_required_count:
                                raise HTTPException(
                                    status_code=status.HTTP_400_BAD_REQUEST,
                                    detail=f"Question {q_id}, Sub-question {subq_id}: Must answer exactly {subq_required_count} of {len(subq.get('subquestions', []))} parts",
                                )

        if existing_submission:
            # Check if already submitted - prevent resubmission
            if (
                existing_submission.status == "submitted"
                or existing_submission.status == "graded"
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Assignment has already been submitted and cannot be resubmitted",
                )

            # Update existing draft submission
            existing_submission.answers = submission_data.answers
            existing_submission.submission_method = submission_data.submission_method
            existing_submission.submitted_files = submission_data.submitted_files
            existing_submission.time_spent = submission_data.time_spent
            existing_submission.status = "submitted"
            existing_submission.submitted_at = datetime.now(timezone.utc)
            existing_submission.updated_at = datetime.now(timezone.utc)

            db.commit()
            db.refresh(existing_submission)

            # Queue background task to extract diagrams if PDF submission
            if (
                submission_data.submission_method == "pdf"
                and submission_data.submitted_files
            ):
                from controllers.background_tasks import queue_pdf_diagram_extraction

                queue_pdf_diagram_extraction(
                    existing_submission.id,
                    submission_data.submitted_files[0].get("s3_key"),
                )

            logger.info(
                f"Updated submission for assignment {assignment_id} by user {user_id}"
            )
            return existing_submission
        else:
            # Create new submission
            submission = AssignmentSubmission(
                assignment_id=assignment_id,  # Use assignment_id from URL path
                user_id=user_id,
                answers=submission_data.answers,
                submission_method=submission_data.submission_method,
                submitted_files=submission_data.submitted_files,
                time_spent=submission_data.time_spent,
                status="submitted",
                submitted_at=datetime.now(timezone.utc),
            )

            db.add(submission)
            db.commit()
            db.refresh(submission)

            # Queue background task to extract diagrams if PDF submission
            if (
                submission_data.submission_method == "pdf"
                and submission_data.submitted_files
            ):
                from controllers.background_tasks import queue_pdf_diagram_extraction

                queue_pdf_diagram_extraction(
                    submission.id, submission_data.submitted_files[0].get("s3_key")
                )

            logger.info(
                f"Created submission for assignment {assignment_id} by user {user_id}"
            )
            return submission

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error submitting assignment {assignment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit assignment",
        )


@router.get(
    "/api/assignments/{assignment_id}/my-submission",
    response_model=AssignmentSubmissionOut,
)
async def get_my_submission(
    assignment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get current user's submission for an assignment"""
    try:
        user_id = current_user["uid"]
        logger.info(
            f"Fetching submission for assignment {assignment_id} by user: {user_id}"
        )

        # Get submission
        submission = (
            db.query(AssignmentSubmission)
            .filter(
                and_(
                    AssignmentSubmission.assignment_id == assignment_id,
                    AssignmentSubmission.user_id == user_id,
                )
            )
            .first()
        )

        if not submission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
            )

        logger.info(
            f"Found submission for assignment {assignment_id} by user {user_id}"
        )
        return submission

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error fetching submission for assignment {assignment_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch submission",
        )


@router.post(
    "/api/assignments/{assignment_id}/save-draft",
    response_model=AssignmentSubmissionOut,
)
async def save_assignment_draft(
    assignment_id: str,
    submission_data: AssignmentSubmissionDraft,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Save assignment as draft"""
    try:
        user_id = current_user["uid"]
        logger.info(f"Saving draft for assignment {assignment_id} by user: {user_id}")

        # Verify assignment access
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
            )

        # Check if user has access
        has_access = (
            assignment.user_id == user_id
            or db.query(SharedLinkAccess)
            .join(SharedLink)
            .filter(
                and_(
                    SharedLink.assignment_id == assignment_id,
                    SharedLink.share_type == "assignment",
                    SharedLinkAccess.user_id == user_id,
                    SharedLinkAccess.permission.in_(["complete", "edit"]),
                )
            )
            .first()
            is not None
        )

        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to save draft for this assignment",
            )

        # Check for existing submission/draft
        existing_submission = (
            db.query(AssignmentSubmission)
            .filter(
                and_(
                    AssignmentSubmission.assignment_id == assignment_id,
                    AssignmentSubmission.user_id == user_id,
                )
            )
            .first()
        )

        if existing_submission:
            # Update existing draft/submission
            existing_submission.answers = submission_data.answers
            existing_submission.submission_method = submission_data.submission_method
            existing_submission.submitted_files = submission_data.submitted_files
            existing_submission.time_spent = submission_data.time_spent
            # Keep status as draft unless it was already submitted
            if existing_submission.status != "submitted":
                existing_submission.status = "draft"
            existing_submission.updated_at = datetime.now(timezone.utc)

            db.commit()
            db.refresh(existing_submission)

            logger.info(
                f"Updated draft for assignment {assignment_id} by user {user_id}"
            )
            return existing_submission
        else:
            # Create new draft
            submission = AssignmentSubmission(
                assignment_id=assignment_id,
                user_id=user_id,
                answers=submission_data.answers,
                submission_method=submission_data.submission_method,
                submitted_files=submission_data.submitted_files,
                time_spent=submission_data.time_spent,
                status="draft",
                started_at=datetime.now(timezone.utc),
            )

            db.add(submission)
            db.commit()
            db.refresh(submission)

            logger.info(
                f"Created draft for assignment {assignment_id} by user {user_id}"
            )
            return submission

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving draft for assignment {assignment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save draft",
        )


@router.get(
    "/api/assignments/{assignment_id}/submissions/{submission_id}/files/{file_id}"
)
async def download_submission_file(
    assignment_id: str,
    submission_id: str,
    file_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get presigned URL for a submitted file (assignment owner/sharer only)"""
    try:
        user_id = current_user["uid"]
        logger.info(
            f"Downloading file {file_id} from submission {submission_id} for assignment {assignment_id} by user: {user_id}"
        )

        # Verify assignment ownership or edit permission
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
            )

        is_owner = assignment.user_id == user_id
        has_edit_access = (
            db.query(SharedLinkAccess)
            .join(SharedLink)
            .filter(
                and_(
                    SharedLink.assignment_id == assignment_id,
                    SharedLink.share_type == "assignment",
                    SharedLinkAccess.user_id == user_id,
                    SharedLinkAccess.permission == "edit",
                )
            )
            .first()
            is not None
        )

        if not (is_owner or has_edit_access):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to download files",
            )

        # Get submission and verify it belongs to this assignment
        submission = (
            db.query(AssignmentSubmission)
            .filter(
                and_(
                    AssignmentSubmission.id == submission_id,
                    AssignmentSubmission.assignment_id == assignment_id,
                )
            )
            .first()
        )

        if not submission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
            )

        # Find the file in submitted_files by file_id
        if not submission.submitted_files:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No files found in submission",
            )

        file_info = None
        for file_data in submission.submitted_files:
            if file_data.get("file_id") == file_id:
                file_info = file_data
                break

        if not file_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found in submission",
            )

        # Generate presigned URL
        s3_key = file_info.get("s3_key")
        if not s3_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="File S3 key not found"
            )

        from controllers.storage import s3_presign_url

        presigned_url = s3_presign_url(s3_key, expires_in=3600)  # 1 hour expiry

        logger.info(
            f"Generated presigned URL for file {file_id} in submission {submission_id}"
        )
        return {
            "url": presigned_url,
            "filename": file_info.get("filename", "submission.pdf"),
            "content_type": file_info.get("content_type", "application/pdf"),
            "size": file_info.get("size", 0),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error downloading file {file_id} from submission {submission_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate download URL",
        )


@router.get("/api/assignments/{assignment_id}/status")
async def get_assignment_status(
    assignment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get assignment status for current user"""
    try:
        user_id = current_user["uid"]
        logger.info(f"Getting status for assignment {assignment_id} by user: {user_id}")

        # Verify assignment access
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
            )

        # Check if user has access
        has_access = (
            assignment.user_id == user_id
            or db.query(SharedLinkAccess)
            .join(SharedLink)
            .filter(
                and_(
                    SharedLink.assignment_id == assignment_id,
                    SharedLink.share_type == "assignment",
                    SharedLinkAccess.user_id == user_id,
                )
            )
            .first()
            is not None
        )

        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to view this assignment status",
            )

        # Get user's submission
        submission = (
            db.query(AssignmentSubmission)
            .filter(
                and_(
                    AssignmentSubmission.assignment_id == assignment_id,
                    AssignmentSubmission.user_id == user_id,
                )
            )
            .first()
        )

        # Calculate status based on submission and due date
        now = datetime.now(timezone.utc)

        # Ensure due_date is timezone-aware for comparison
        due_date = None
        if assignment.due_date:
            if assignment.due_date.tzinfo is None:
                # If due_date is naive, assume it's UTC
                due_date = assignment.due_date.replace(tzinfo=timezone.utc)
            else:
                due_date = assignment.due_date

        # Convert submission to dict if it exists
        submission_dict = None
        if submission:
            submission_dict = {
                "id": submission.id,
                "assignment_id": submission.assignment_id,
                "user_id": submission.user_id,
                "answers": submission.answers,
                "submission_method": submission.submission_method,
                "submitted_files": submission.submitted_files,
                "score": submission.score,
                "percentage": submission.percentage,
                "feedback": submission.feedback,
                "overall_feedback": submission.overall_feedback,
                "status": submission.status,
                "is_late": submission.is_late,
                "attempt_number": submission.attempt_number,
                "time_spent": submission.time_spent,
                "started_at": submission.started_at.isoformat()
                if submission.started_at
                else None,
                "submitted_at": submission.submitted_at.isoformat()
                if submission.submitted_at
                else None,
                "graded_at": submission.graded_at.isoformat()
                if submission.graded_at
                else None,
                "created_at": submission.created_at.isoformat()
                if submission.created_at
                else None,
                "updated_at": submission.updated_at.isoformat()
                if submission.updated_at
                else None,
            }

        status_info = {
            "assignment_id": assignment_id,
            "user_id": user_id,
            "submission": submission_dict,
        }

        if not submission:
            # No submission yet
            if due_date and now > due_date:
                status_info["status"] = "overdue"
                status_info["progress"] = 0
            else:
                status_info["status"] = "not_started"
                status_info["progress"] = 0
        else:
            # Has submission
            if submission.status == "submitted":
                if submission.score is not None:
                    status_info["status"] = "graded"
                    status_info["grade"] = submission.score
                    status_info["percentage"] = submission.percentage
                else:
                    status_info["status"] = "submitted"
                status_info["progress"] = 100
            elif submission.status == "draft":
                # Calculate progress based on answered questions
                total_questions = len(assignment.questions or [])
                answered_questions = len(submission.answers or {})
                progress = (
                    (answered_questions / total_questions * 100)
                    if total_questions > 0
                    else 0
                )

                if due_date and now > due_date:
                    status_info["status"] = "overdue"
                else:
                    status_info["status"] = "in_progress"
                status_info["progress"] = min(progress, 99)  # Max 99% for draft
            elif submission.status == "graded":
                status_info["status"] = "graded"
                status_info["progress"] = submission.percentage
                status_info["grade"] = submission.score
                status_info["percentage"] = submission.percentage
            else:
                status_info["status"] = submission.status
                status_info["progress"] = (
                    100 if submission.status == "submitted" else 50
                )

        # Add due date info
        if due_date:
            status_info["due_date"] = due_date.isoformat()
            status_info["is_overdue"] = now > due_date and (
                not submission or submission.status != "submitted"
            )
            status_info["time_remaining"] = (
                str(due_date - now) if due_date > now else None
            )

        logger.info(
            f"Status for assignment {assignment_id} by user {user_id}: {status_info['status']}"
        )
        return status_info

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting status for assignment {assignment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get assignment status",
        )


# Diagram/File Upload Endpoints
@router.post("/api/assignments/upload-diagram", response_model=DiagramUploadResponse)
async def upload_assignment_diagram(
    file: UploadFile = File(...),
    assignment_id: Optional[str] = None,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Upload a diagram/image file for assignment questions"""
    try:
        user_id = current_user["uid"]
        logger.info(
            f"Uploading diagram file for user: {user_id}, assignment: {assignment_id}"
        )

        # Validate file type
        allowed_types = [
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/gif",
            "image/svg+xml",
            "application/pdf",
        ]
        allowed_extensions = [".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf"]

        file_extension = os.path.splitext(file.filename or "")[1].lower()
        content_type = file.content_type

        if (
            content_type not in allowed_types
            and file_extension not in allowed_extensions
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file type. Only images (PNG, JPG, GIF, SVG) and PDF files are allowed.",
            )

        # Validate file size (max 10MB)
        file_content = await file.read()
        if len(file_content) > 10 * 1024 * 1024:  # 10MB
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File size exceeds 10MB limit.",
            )

        # Check S3 configuration
        if not s3_client or not AWS_S3_BUCKET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="File storage is not configured",
            )

        # If assignment_id is provided, verify user has access
        if assignment_id:
            assignment = (
                db.query(Assignment).filter(Assignment.id == assignment_id).first()
            )
            if not assignment:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
                )

            # Check if user owns the assignment or has edit access
            has_access = (
                assignment.user_id == user_id
                or db.query(SharedLinkAccess)
                .join(SharedLink)
                .filter(
                    and_(
                        SharedLink.assignment_id == assignment_id,
                        SharedLink.share_type == "assignment",
                        SharedLinkAccess.user_id == user_id,
                        SharedLinkAccess.permission == "edit",
                    )
                )
                .first()
                is not None
            )

            if not has_access:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to upload diagrams for this assignment",
                )

        # Generate unique file ID and S3 key
        file_id = str(uuid.uuid4())
        file_extension = file_extension or mimetypes.guess_extension(content_type) or ""

        # Organize files by assignment or user
        if assignment_id:
            s3_key = f"assignments/{assignment_id}/diagrams/{file_id}{file_extension}"
        else:
            s3_key = f"users/{user_id}/diagrams/{file_id}{file_extension}"

        # Create temporary file and upload to S3
        import tempfile

        with tempfile.NamedTemporaryFile(
            delete=False, suffix=file_extension
        ) as temp_file:
            temp_file.write(file_content)
            temp_file_path = temp_file.name

        try:
            # Upload to S3
            s3_upload_file(temp_file_path, s3_key, content_type=content_type)

            # Generate presigned URL for immediate access (expires in 1 hour)
            presigned_url = s3_presign_url(s3_key, expires_in=3600)

            # Clean up temp file
            os.unlink(temp_file_path)

            logger.info(f"Successfully uploaded diagram: {file_id} to S3: {s3_key}")

            return {
                "file_id": file_id,
                "filename": file.filename,
                "content_type": content_type,
                "size": len(file_content),
                "s3_key": s3_key,
                "url": presigned_url,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            # Clean up temp file on error
            try:
                os.unlink(temp_file_path)
            except:
                pass
            raise e

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading diagram: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload diagram",
        )


@router.get("/api/assignments/diagrams/{file_id}")
async def serve_assignment_diagram(
    file_id: str,
    assignment_id: Optional[str] = None,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Serve a diagram file by generating a presigned URL"""
    try:
        user_id = current_user["uid"]
        logger.info(f"Serving diagram {file_id} for user: {user_id}")

        # Check S3 configuration
        if not s3_client or not AWS_S3_BUCKET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="File storage is not configured",
            )

        # Construct potential S3 keys to check
        possible_keys = []

        if assignment_id:
            # Check assignment-specific location first
            possible_keys.append(f"assignments/{assignment_id}/diagrams/{file_id}.png")
            possible_keys.append(f"assignments/{assignment_id}/diagrams/{file_id}.jpg")
            possible_keys.append(f"assignments/{assignment_id}/diagrams/{file_id}.jpeg")
            possible_keys.append(f"assignments/{assignment_id}/diagrams/{file_id}.gif")
            possible_keys.append(f"assignments/{assignment_id}/diagrams/{file_id}.svg")
            possible_keys.append(f"assignments/{assignment_id}/diagrams/{file_id}.pdf")

            # Verify user has access to the assignment
            assignment = (
                db.query(Assignment).filter(Assignment.id == assignment_id).first()
            )
            if assignment:
                has_access = (
                    assignment.user_id == user_id
                    or db.query(SharedLinkAccess)
                    .join(SharedLink)
                    .filter(
                        and_(
                            SharedLink.assignment_id == assignment_id,
                            SharedLink.share_type == "assignment",
                            SharedLinkAccess.user_id == user_id,
                        )
                    )
                    .first()
                    is not None
                )

                if not has_access:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Access denied to this diagram",
                    )

        # Also check user-specific location
        possible_keys.extend(
            [
                f"users/{user_id}/diagrams/{file_id}.png",
                f"users/{user_id}/diagrams/{file_id}.jpg",
                f"users/{user_id}/diagrams/{file_id}.jpeg",
                f"users/{user_id}/diagrams/{file_id}.gif",
                f"users/{user_id}/diagrams/{file_id}.svg",
                f"users/{user_id}/diagrams/{file_id}.pdf",
            ]
        )

        # Try to find the file by checking if objects exist
        found_key = None
        for key in possible_keys:
            try:
                s3_client.head_object(Bucket=AWS_S3_BUCKET, Key=key)
                found_key = key
                break
            except:
                continue

        if not found_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Diagram file not found"
            )

        # Generate presigned URL (expires in 1 hour)
        presigned_url = s3_presign_url(found_key, expires_in=3600)

        logger.info(f"Generated presigned URL for diagram: {file_id}")

        # Return redirect to presigned URL
        return RedirectResponse(url=presigned_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving diagram {file_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to serve diagram",
        )


@router.delete(
    "/api/assignments/diagrams/{file_id}", response_model=DiagramDeleteResponse
)
async def delete_assignment_diagram(
    file_id: str,
    assignment_id: Optional[str] = None,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Delete a diagram file from storage"""
    try:
        user_id = current_user["uid"]
        logger.info(f"Deleting diagram {file_id} for user: {user_id}")

        # Check S3 configuration
        if not s3_client or not AWS_S3_BUCKET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="File storage is not configured",
            )

        # If assignment_id is provided, verify user has edit access
        if assignment_id:
            assignment = (
                db.query(Assignment).filter(Assignment.id == assignment_id).first()
            )
            if not assignment:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
                )

            has_access = (
                assignment.user_id == user_id
                or db.query(SharedLinkAccess)
                .join(SharedLink)
                .filter(
                    and_(
                        SharedLink.assignment_id == assignment_id,
                        SharedLink.share_type == "assignment",
                        SharedLinkAccess.user_id == user_id,
                        SharedLinkAccess.permission == "edit",
                    )
                )
                .first()
                is not None
            )

            if not has_access:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to delete diagrams for this assignment",
                )

        # Construct potential S3 keys to check and delete
        possible_keys = []

        if assignment_id:
            possible_keys.extend(
                [
                    f"assignments/{assignment_id}/diagrams/{file_id}.png",
                    f"assignments/{assignment_id}/diagrams/{file_id}.jpg",
                    f"assignments/{assignment_id}/diagrams/{file_id}.jpeg",
                    f"assignments/{assignment_id}/diagrams/{file_id}.gif",
                    f"assignments/{assignment_id}/diagrams/{file_id}.svg",
                    f"assignments/{assignment_id}/diagrams/{file_id}.pdf",
                ]
            )

        # Also check user-specific location
        possible_keys.extend(
            [
                f"users/{user_id}/diagrams/{file_id}.png",
                f"users/{user_id}/diagrams/{file_id}.jpg",
                f"users/{user_id}/diagrams/{file_id}.jpeg",
                f"users/{user_id}/diagrams/{file_id}.gif",
                f"users/{user_id}/diagrams/{file_id}.svg",
                f"users/{user_id}/diagrams/{file_id}.pdf",
            ]
        )

        # Find and delete the file
        deleted_keys = []
        for key in possible_keys:
            try:
                s3_client.head_object(Bucket=AWS_S3_BUCKET, Key=key)
                s3_client.delete_object(Bucket=AWS_S3_BUCKET, Key=key)
                deleted_keys.append(key)
                logger.info(f"Deleted diagram from S3: {key}")
            except:
                continue

        if not deleted_keys:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Diagram file not found"
            )

        return {
            "message": "Diagram deleted successfully",
            "file_id": file_id,
            "deleted_keys": deleted_keys,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting diagram {file_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete diagram",
        )


@router.get("/api/assignments/{assignment_id}/download-pdf")
async def download_assignment_pdf(
    assignment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Generate and download a professional PDF for a published assignment.
    Returns a LaTeX-style formatted document with equations and images.
    """
    try:
        user_id = current_user["uid"]
        logger.info(
            f"PDF download requested for assignment {assignment_id} by user {user_id}"
        )

        # Fetch the assignment
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
            )

        # Verify user has access (owner or shared access)
        has_access = assignment.user_id == user_id

        if not has_access:
            # Check if user has shared access
            shared_access = (
                db.query(SharedLinkAccess)
                .join(SharedLink)
                .filter(
                    and_(
                        SharedLink.assignment_id == assignment_id,
                        SharedLink.share_type == "assignment",
                        SharedLinkAccess.user_id == user_id,
                    )
                )
                .first()
            )
            has_access = shared_access is not None

        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this assignment",
            )

        # Only allow PDF download for published assignments
        if assignment.status != "published":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF download is only available for published assignments",
            )

        # Prepare assignment data for PDF generation
        assignment_data = {
            "id": assignment.id,
            "title": assignment.title,
            "description": assignment.description,
            "questions": assignment.questions or [],
            "total_points": assignment.total_points,
            "total_questions": assignment.total_questions,
            "engineering_level": assignment.engineering_level,
            "engineering_discipline": assignment.engineering_discipline,
            "created_at": assignment.created_at,
        }

        # Process diagram URLs in questions to be accessible
        for question in assignment_data["questions"]:
            # Handle main question diagrams
            if question.get("diagram") and question["diagram"].get("file_id"):
                try:
                    # Generate presigned URL for the diagram
                    file_id = question["diagram"]["file_id"]
                    s3_key = f"assignments/{assignment_id}/diagrams/{file_id}.png"  # Assume PNG, could be improved

                    # Try to generate presigned URL
                    try:
                        presigned_url = s3_presign_url(s3_key, expires_in=3600)
                        question["diagram"]["url"] = presigned_url
                    except Exception as e:
                        logger.warning(
                            f"Could not generate presigned URL for diagram {file_id}: {e}"
                        )
                        # Remove diagram if URL generation fails
                        question["diagram"] = None

                except Exception as e:
                    logger.warning(f"Error processing diagram for question: {e}")

            # Handle subquestion diagrams
            if question.get("subquestions"):
                for subq in question["subquestions"]:
                    if subq.get("diagram") and subq["diagram"].get("file_id"):
                        try:
                            file_id = subq["diagram"]["file_id"]
                            s3_key = (
                                f"assignments/{assignment_id}/diagrams/{file_id}.png"
                            )
                            presigned_url = s3_presign_url(s3_key, expires_in=3600)
                            subq["diagram"]["url"] = presigned_url
                        except Exception as e:
                            logger.warning(
                                f"Could not generate presigned URL for subquestion diagram {file_id}: {e}"
                            )
                            subq["diagram"] = None

        # Generate PDF
        pdf_generator = AssignmentPDFGenerator()
        try:
            pdf_content = pdf_generator.generate_assignment_pdf(assignment_data)

            # Clean filename for download
            safe_title = "".join(
                c for c in assignment.title if c.isalnum() or c in (" ", "-", "_")
            ).strip()
            safe_title = safe_title.replace(" ", "_")[:50]  # Limit length
            filename = f"{safe_title}_Assignment.pdf"

            logger.info(
                f"Successfully generated PDF for assignment {assignment_id}, size: {len(pdf_content)} bytes"
            )

            # Return PDF response
            return Response(
                content=pdf_content,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename={filename}",
                    "Content-Length": str(len(pdf_content)),
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )

        finally:
            # Always cleanup temporary files
            pdf_generator.cleanup()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating PDF for assignment {assignment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate assignment PDF",
        )


@router.get("/api/assignments/test-google-forms")
async def test_google_forms_connection(current_user=Depends(get_current_user)):
    """Test Google Forms service connection and domain-wide delegation."""
    try:
        # Get Google Forms service
        google_forms_service = get_google_forms_service()

        # Test the connection
        result = google_forms_service.test_connection()

        if result["success"]:
            return {
                "success": True,
                "message": "Google Forms service is working correctly with domain-wide delegation",
                "form_id": result["form_id"],
                "edit_url": result["edit_url"],
                "response_url": result["response_url"],
                "service_available": google_forms_service.is_available(),
            }
        else:
            return {
                "success": False,
                "message": "Google Forms service test failed",
                "error": result.get("error", "Unknown error"),
                "service_available": google_forms_service.is_available(),
            }

    except Exception as e:
        logger.error(f"Error testing Google Forms service: {str(e)}")
        return {
            "success": False,
            "message": "Google Forms service test failed with exception",
            "error": str(e),
            "service_available": False,
        }


@router.post("/api/assignments/{assignment_id}/generate-google-form")
async def generate_google_form(
    assignment_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Generate a Google Form from an existing assignment."""
    try:
        # Get the assignment
        assignment = (
            db.query(Assignment)
            .filter(
                and_(
                    Assignment.id == assignment_id,
                    Assignment.user_id == current_user["uid"],
                )
            )
            .first()
        )

        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
            )

        # Get Google Forms service
        google_forms_service = get_google_forms_service()

        if not google_forms_service.is_available():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google Forms service not available. Please contact administrator to configure Google Cloud credentials.",
            )

        # Prepare assignment data for form creation
        assignment_data = {
            "title": assignment.title,
            "description": assignment.description,
            "questions": assignment.questions or [],
        }

        # Create Google Form
        result = google_forms_service.create_form_from_assignment(assignment_data)

        if result["success"]:
            # Update assignment with Google Form URLs
            assignment.google_form_url = result["edit_url"]
            assignment.google_form_response_url = result["response_url"]
            db.commit()

            logger.info(
                f"Created Google Form for assignment {assignment_id}: {result['form_id']}"
            )

            return {
                "success": True,
                "form_id": result["form_id"],
                "edit_url": result["edit_url"],
                "response_url": result["response_url"],
                "google_resource_url": result[
                    "edit_url"
                ],  # Frontend expects this field
                "message": "Google Form created successfully",
            }
        else:
            error_message = result.get("error", "Unknown error")
            logger.error(
                f"Failed to create Google Form for assignment {assignment_id}: {error_message}"
            )

            # Provide user-friendly error messages
            if "Permission denied" in error_message or "403" in str(
                result.get("api_error", "")
            ):
                user_message = "Google Forms integration is not properly configured. Please contact your administrator."
            elif "internal error" in error_message.lower() or "500" in str(
                result.get("api_error", "")
            ):
                user_message = "Google Forms service is temporarily unavailable. Please try again later."
            else:
                user_message = (
                    "Failed to create Google Form. Please try again or contact support."
                )

            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=user_message
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error generating Google Form for assignment {assignment_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate Google Form",
        )


@router.get("/api/assignments/{assignment_id}/google-form-url")
async def get_google_form_url(
    assignment_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get the Google Form URL for an existing assignment."""
    try:
        # Get the assignment
        assignment = (
            db.query(Assignment)
            .filter(
                and_(
                    Assignment.id == assignment_id,
                    Assignment.user_id == current_user["uid"],
                )
            )
            .first()
        )

        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
            )

        # Check if Google Form URL exists
        if not assignment.google_form_url:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No Google Form exists for this assignment",
            )

        return {
            "google_resource_url": assignment.google_form_url,
            "google_form_response_url": assignment.google_form_response_url,
            "message": "Google Form URL retrieved successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting Google Form URL for assignment {assignment_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve Google Form URL",
        )


@router.post("/api/assignments/{assignment_id}/make-google-form-public")
async def make_google_form_public(
    assignment_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Make an existing Google Form publicly accessible."""
    try:
        # Get the assignment
        assignment = (
            db.query(Assignment)
            .filter(
                and_(
                    Assignment.id == assignment_id,
                    Assignment.user_id == current_user["uid"],
                )
            )
            .first()
        )

        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
            )

        # Check if Google Form exists
        if not assignment.google_form_url:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No Google Form exists for this assignment",
            )

        # Extract form ID from URL
        try:
            # URL format: https://docs.google.com/forms/d/{form_id}/edit
            form_id = assignment.google_form_url.split("/d/")[1].split("/")[0]
        except (IndexError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Google Form URL format",
            )

        # Get Google Forms service and make form public
        google_forms_service = get_google_forms_service()

        if not google_forms_service.is_available():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google Forms service not available",
            )

        # Make the form public
        google_forms_service._make_form_public(form_id)

        logger.info(
            f"Made existing Google Form {form_id} public for assignment {assignment_id}"
        )

        return {
            "success": True,
            "form_id": form_id,
            "message": "Google Form is now publicly accessible",
            "google_resource_url": assignment.google_form_url,
            "google_form_response_url": assignment.google_form_response_url,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error making Google Form public for assignment {assignment_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to make Google Form public",
        )


@router.post("/api/assignments/make-all-google-forms-public")
async def make_all_google_forms_public(
    db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    """Make all existing Google Forms for the current user publicly accessible."""
    try:
        # Get all assignments with Google Forms for this user
        assignments = (
            db.query(Assignment)
            .filter(
                and_(
                    Assignment.user_id == current_user["uid"],
                    Assignment.google_form_url.isnot(None),
                    Assignment.google_form_url != "",
                )
            )
            .all()
        )

        if not assignments:
            return {
                "success": True,
                "message": "No Google Forms found to make public",
                "processed_count": 0,
                "successful_count": 0,
                "failed_count": 0,
            }

        google_forms_service = get_google_forms_service()

        if not google_forms_service.is_available():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google Forms service not available",
            )

        successful_count = 0
        failed_count = 0
        failed_assignments = []

        for assignment in assignments:
            try:
                # Extract form ID from URL
                form_id = assignment.google_form_url.split("/d/")[1].split("/")[0]

                # Make the form public
                google_forms_service._make_form_public(form_id)
                successful_count += 1

                logger.info(
                    f"Made Google Form {form_id} public for assignment {assignment.id}"
                )

            except Exception as e:
                failed_count += 1
                failed_assignments.append(
                    {
                        "assignment_id": assignment.id,
                        "assignment_title": assignment.title,
                        "error": str(e),
                    }
                )
                logger.error(
                    f"Failed to make form public for assignment {assignment.id}: {e}"
                )

        return {
            "success": True,
            "message": f"Processed {len(assignments)} Google Forms",
            "processed_count": len(assignments),
            "successful_count": successful_count,
            "failed_count": failed_count,
            "failed_assignments": failed_assignments if failed_assignments else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error making all Google Forms public for user {current_user['uid']}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to make Google Forms public",
        )
