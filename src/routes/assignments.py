from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, asc
from typing import List, Optional
from datetime import datetime, timezone
import json
import secrets
import string

from utils.db import get_db
from controllers.config import logger
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
    AssignmentSubmissionCreate,
    AssignmentSubmissionUpdate,
    AssignmentSubmissionOut,
    AssignmentGenerateRequest,
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

                shared_assignment_data = {
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

        logger.info(f"Retrieved assignment: {assignment.title}")
        return assignment

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
    """Generate an assignment using AI (mock implementation)"""
    try:
        user_id = current_user["uid"]
        logger.info(f"Generating assignment for user: {user_id}")

        # Mock AI generation logic (replace with actual AI service)
        generation_options = generate_data.generation_options

        # Generate mock questions based on options
        questions = []
        question_types = []
        for q_type, enabled in generation_options.get("questionTypes", {}).items():
            if enabled:
                question_types.append(q_type)

        num_questions = int(generation_options.get("numQuestions", 5))

        for i in range(num_questions):
            q_type = (
                question_types[i % len(question_types)]
                if question_types
                else "multiple-choice"
            )
            question = {
                "id": i + 1,
                "type": q_type,
                "question": f'Generated {q_type.replace("-", " ")} question {i + 1}',
                "points": 5,
                "options": ["Option A", "Option B", "Option C", "Option D"]
                if q_type == "multiple-choice"
                else [],
                "correctAnswer": "Option A"
                if q_type == "multiple-choice"
                else "Sample answer",
            }
            questions.append(question)

        # Create assignment
        assignment = Assignment(
            user_id=user_id,
            title=generate_data.title
            or f"{generation_options.get('engineeringLevel', 'Undergraduate')} Assignment",
            description=generate_data.description or "AI-generated assignment",
            engineering_level=generation_options.get(
                "engineeringLevel", "undergraduate"
            ),
            engineering_discipline=generation_options.get(
                "engineeringDiscipline", "general"
            ),
            question_types=question_types,
            linked_videos=generate_data.linked_videos,
            uploaded_files=generate_data.uploaded_files,
            generation_prompt=generate_data.generation_prompt,
            generation_options=generation_options,
            questions=questions,
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
    submission_data: AssignmentSubmissionCreate,
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
            # Update existing submission
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
                assignment_id=assignment_id,
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
