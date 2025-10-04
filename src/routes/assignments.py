from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File
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
)

router = APIRouter()


def generate_share_token() -> str:
    """Generate a random share token"""
    return "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(32)
    )


def calculate_assignment_stats(assignment: Assignment) -> Assignment:
    """Calculate total points and questions for an assignment"""
    questions = assignment.questions or []
    total_questions = len(questions)
    total_points = sum(q.get("points", 0) for q in questions)

    assignment.total_questions = str(total_questions)
    assignment.total_points = str(total_points)
    return assignment


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
            detail="Failed to generate assignment",
        )


@router.post("/api/assignments/import-document", response_model=DocumentImportResponse)
async def import_document_to_assignment(
    import_data: DocumentImportRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Import assignment questions from a document using AI parsing"""
    try:
        user_id = current_user["uid"]
        logger.info(f"Importing document {import_data.file_name} for user: {user_id}")

        # Import document processing services
        from utils.document_processor import DocumentProcessor, AssignmentDocumentParser

        # Initialize processors
        doc_processor = DocumentProcessor()
        assignment_parser = AssignmentDocumentParser()

        # Extract text from the document
        try:
            extracted_text = doc_processor.extract_text_from_file(
                import_data.file_content, import_data.file_name, import_data.file_type
            )

            if not extracted_text or len(extracted_text.strip()) < 50:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Document appears to be empty or contains insufficient content for assignment extraction",
                )

        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        # Parse the document to extract assignment questions
        try:
            parsed_assignment = assignment_parser.parse_document_to_assignment(
                extracted_text, import_data.file_name, import_data.generation_options
            )
        except Exception as e:
            logger.error(f"Error parsing document with AI: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to extract assignment questions from document. Please ensure the document contains assignment questions, exercises, or problems.",
            )

        # Prepare the response
        response_data = DocumentImportResponse(
            title=parsed_assignment.get(
                "title", f"Assignment from {import_data.file_name}"
            ),
            description=parsed_assignment.get("description"),
            questions=parsed_assignment.get("questions", []),
            extracted_text=extracted_text[:1000] + "..."
            if len(extracted_text) > 1000
            else extracted_text,  # Truncate for response
            file_info={
                "original_filename": import_data.file_name,
                "file_type": import_data.file_type,
                "content_length": len(extracted_text),
                "questions_generated": len(parsed_assignment.get("questions", [])),
                "total_points": parsed_assignment.get("total_points", 0),
            },
        )

        logger.info(
            f"Successfully imported document {import_data.file_name}: "
            f"{len(parsed_assignment.get('questions', []))} questions generated"
        )

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error importing document {import_data.file_name}: {str(e)}")
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
    submission_data: AssignmentSubmissionDraft,  # Use same schema as draft
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Submit an assignment"""
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

        if existing_submission:
            # Check if already submitted - prevent resubmission
            if existing_submission.status == "submitted":
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
