from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import stripe
from firebase_admin import auth as fb_auth
from utils.db import get_db
from utils.firebase_auth import get_current_user
from controllers.config import logger, s3_client, AWS_S3_BUCKET
from models import (
    User,
    Folder,
    Video,
    Assignment,
    AssignmentSubmission,
    Course,
    CourseMaterial,
    CourseEnrollment,
    LectureSummary,
    SharedLink,
    Subscription,
    UserUsage,
)
from schemas import UserProfileResponse, UserProfileUpdate

router = APIRouter(prefix="/api/users", tags=["Users"])


def _get_or_create_user(db: Session, current_user: dict) -> User:
    """Get existing user or create one if not found."""
    user = db.query(User).filter(User.firebase_uid == current_user["uid"]).first()
    if not user:
        user = User(
            firebase_uid=current_user["uid"],
            email=current_user.get("email"),
            name=current_user.get("name"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@router.get("/profile", response_model=UserProfileResponse)
async def get_user_profile(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get the current user's profile, including user_type."""
    user = _get_or_create_user(db, current_user)
    return UserProfileResponse(user_type=user.user_type)


@router.patch("/profile", response_model=UserProfileResponse)
async def update_user_profile(
    payload: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Update the current user's user_type ('professor' or 'student')."""
    user = _get_or_create_user(db, current_user)
    user.user_type = payload.user_type
    db.commit()
    db.refresh(user)
    logger.info(f"User {user.firebase_uid} set user_type to '{user.user_type}'")
    return UserProfileResponse(user_type=user.user_type)


def _delete_s3_key(key: str) -> None:
    """Delete a single S3 object, silently ignoring errors."""
    if not s3_client or not AWS_S3_BUCKET or not key:
        return
    try:
        s3_client.delete_object(Bucket=AWS_S3_BUCKET, Key=key)
    except Exception as e:
        logger.warning(f"S3 delete failed for key {key}: {e}")


@router.delete("/account")
async def delete_account(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Permanently delete the current user's account and all associated data."""
    firebase_uid = current_user["uid"]

    user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = user.id  # Internal UUID used by Subscription + UserUsage FKs

    try:
        # 1. Cancel active Stripe subscription (best-effort)
        active_sub = (
            db.query(Subscription)
            .filter(Subscription.user_id == user_id, Subscription.status == "active")
            .first()
        )
        if active_sub and active_sub.stripe_subscription_id:
            try:
                stripe.Subscription.delete(active_sub.stripe_subscription_id)
                logger.info(
                    f"Cancelled Stripe subscription {active_sub.stripe_subscription_id} for user {firebase_uid}"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to cancel Stripe subscription for user {firebase_uid}: {e}"
                )

        # 2. Delete SharedLinks owned by user (before Videos/Folders to avoid FK violations)
        # SharedLink.shared_accesses cascades via ORM, so SharedLinkAccess rows are handled
        db.query(SharedLink).filter(SharedLink.owner_id == firebase_uid).delete(
            synchronize_session=False
        )

        # 3. Delete LectureSummaries + S3
        summaries = (
            db.query(LectureSummary)
            .filter(LectureSummary.user_id == firebase_uid)
            .all()
        )
        for s in summaries:
            _delete_s3_key(s.summary_pdf_s3_key)
        db.query(LectureSummary).filter(LectureSummary.user_id == firebase_uid).delete(
            synchronize_session=False
        )

        # 4. Delete Videos + S3 (ORM cascades VideoSummary + TranscriptChunk)
        videos = db.query(Video).filter(Video.user_id == firebase_uid).all()
        for v in videos:
            _delete_s3_key(v.s3_key)
            _delete_s3_key(v.thumb_key)
            _delete_s3_key(v.transcript_s3_key)
        db.query(Video).filter(Video.user_id == firebase_uid).delete(
            synchronize_session=False
        )

        # 5. Delete CourseMaterials S3 + Courses (ORM cascades CourseMaterial + CourseEnrollment)
        courses = db.query(Course).filter(Course.user_id == firebase_uid).all()
        for course in courses:
            materials = (
                db.query(CourseMaterial)
                .filter(CourseMaterial.course_id == course.id)
                .all()
            )
            for mat in materials:
                _delete_s3_key(mat.s3_key)
        db.query(Course).filter(Course.user_id == firebase_uid).delete(
            synchronize_session=False
        )

        # 6. Delete AssignmentSubmissions by user on others' assignments
        submissions = (
            db.query(AssignmentSubmission)
            .filter(AssignmentSubmission.user_id == firebase_uid)
            .all()
        )
        for sub in submissions:
            for f in sub.submitted_files or []:
                if isinstance(f, dict):
                    _delete_s3_key(f.get("s3_key"))
        db.query(AssignmentSubmission).filter(
            AssignmentSubmission.user_id == firebase_uid
        ).delete(synchronize_session=False)

        # 7. Delete Assignments + S3 (ORM cascades submissions on own assignments + SharedLinks)
        assignments = (
            db.query(Assignment).filter(Assignment.user_id == firebase_uid).all()
        )
        for a in assignments:
            for f in a.uploaded_files or []:
                if isinstance(f, dict):
                    _delete_s3_key(f.get("s3_key"))
        db.query(Assignment).filter(Assignment.user_id == firebase_uid).delete(
            synchronize_session=False
        )

        # 8. Delete CourseEnrollments where user is a student in others' courses
        db.query(CourseEnrollment).filter(
            CourseEnrollment.user_id == firebase_uid
        ).delete(synchronize_session=False)

        # 9. Delete Folders (null parent_id first to avoid self-referential FK issues)
        db.query(Folder).filter(Folder.user_id == firebase_uid).update(
            {"parent_id": None}, synchronize_session=False
        )
        db.query(Folder).filter(Folder.user_id == firebase_uid).delete(
            synchronize_session=False
        )

        # 10. Explicitly delete Subscription + UserUsage (no ORM cascade on User side)
        db.query(Subscription).filter(Subscription.user_id == user_id).delete(
            synchronize_session=False
        )
        db.query(UserUsage).filter(UserUsage.user_id == user_id).delete(
            synchronize_session=False
        )

        # 11. Delete User row
        db.delete(user)
        db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting account for user {firebase_uid}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to delete account. No changes made."
        )

    # 12. Delete Firebase Auth user (after DB commit — best-effort)
    try:
        fb_auth.delete_user(firebase_uid)
        logger.info(f"Deleted Firebase Auth user {firebase_uid}")
    except Exception as e:
        logger.critical(
            f"DB deletion succeeded but Firebase Auth deletion FAILED for uid {firebase_uid}: {e}. Manual cleanup required."
        )

    logger.info(f"Account fully deleted for user {firebase_uid}")
    return {"message": "Account deleted successfully"}
