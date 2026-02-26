"""
Course management routes – CRUD, enrollment (individual + CSV), materials (upload + link video),
and course-scoped assignment listing.
"""
import csv
import io
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from controllers.config import AWS_S3_BUCKET, logger, s3_client, upload_executor
from controllers.storage import s3_presign_url, transcribe_video_with_deepgram_url
from utils.db import get_db, SessionLocal
from models import (
    Assignment,
    Course,
    CourseEnrollment,
    CourseMaterial,
    Video,
)
from schemas import (
    CourseMaterialLinkVideo,
    CourseMaterialOut,
    CourseCreate,
    CourseOut,
    CourseUpdate,
    EnrollmentOut,
    EnrollmentResultOut,
    EnrollStudentsRequest,
)
from utils.firebase_auth import get_current_user

router = APIRouter()

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


# ── helpers ──────────────────────────────────────────────────────────────


def _course_to_out(course: Course, db: Session) -> dict:
    """Convert a Course ORM object to a dict matching CourseOut, with counts."""
    enrollment_count = (
        db.query(func.count(CourseEnrollment.id))
        .filter(CourseEnrollment.course_id == course.id)
        .scalar()
        or 0
    )
    assignment_count = (
        db.query(func.count(Assignment.id))
        .filter(Assignment.course_id == course.id)
        .scalar()
        or 0
    )
    material_count = (
        db.query(func.count(CourseMaterial.id))
        .filter(CourseMaterial.course_id == course.id)
        .scalar()
        or 0
    )
    return {
        "id": course.id,
        "user_id": course.user_id,
        "title": course.title,
        "description": course.description,
        "course_code": course.course_code,
        "semester": course.semester,
        "is_active": course.is_active,
        "enrollment_code": course.enrollment_code,
        "enrollment_count": enrollment_count,
        "assignment_count": assignment_count,
        "material_count": material_count,
        "created_at": course.created_at,
        "updated_at": course.updated_at,
    }


def _verify_course_owner(course_id: str, user_uid: str, db: Session) -> Course:
    """Return the course if the user is the owner; otherwise raise 403."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.user_id != user_uid:
        raise HTTPException(status_code=403, detail="Access denied")
    return course


def _verify_course_access(course_id: str, user_uid: str, db: Session) -> Course:
    """Return the course if the user is the owner **or** an enrolled student."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.user_id == user_uid:
        return course
    enrolled = (
        db.query(CourseEnrollment)
        .filter(
            and_(
                CourseEnrollment.course_id == course_id,
                CourseEnrollment.user_id == user_uid,
                CourseEnrollment.status == "active",
            )
        )
        .first()
    )
    if not enrolled:
        raise HTTPException(status_code=403, detail="Access denied")
    return course


def _lookup_firebase_user(email: str):
    """Try to find a Firebase user by email. Returns (uid, found:bool)."""
    try:
        from firebase_admin import auth

        user_record = auth.get_user_by_email(email)
        return user_record.uid, True
    except Exception:
        return f"pending_{email}", False


def _transcribe_course_material_background(material_id: str, s3_key: str) -> None:
    """Background job: transcribe a directly-uploaded course video and store the result."""
    db = SessionLocal()
    try:
        # Generate presigned URL so Deepgram can pull from S3 directly
        try:
            presigned = s3_presign_url(s3_key, expires_in=60 * 60 * 12)
            transcript_text = transcribe_video_with_deepgram_url(presigned)
        except Exception as e:
            logger.error(
                f"Deepgram URL transcription failed for material {material_id}: {e}"
            )
            transcript_text = ""

        material = (
            db.query(CourseMaterial).filter(CourseMaterial.id == material_id).first()
        )
        if material:
            material.transcript_text = transcript_text or None
            material.transcript_status = "completed" if transcript_text else "failed"
            material.updated_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(
                f"Transcription {'completed' if transcript_text else 'failed'} "
                f"for course material {material_id}"
            )
    except Exception as e:
        logger.error(f"Background transcription error for material {material_id}: {e}")
        try:
            mat = (
                db.query(CourseMaterial)
                .filter(CourseMaterial.id == material_id)
                .first()
            )
            if mat:
                mat.transcript_status = "failed"
                mat.updated_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ── Course CRUD ──────────────────────────────────────────────────────────


@router.post("/api/courses", status_code=201)
def create_course(
    data: CourseCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    course = Course(
        user_id=current_user["uid"],
        title=data.title,
        description=data.description,
        course_code=data.course_code,
        semester=data.semester,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    logger.info(f"Course created: {course.id} by {current_user['uid']}")
    return _course_to_out(course, db)


@router.get("/api/courses")
def list_courses(
    role: str = Query(None, description="'instructor' or 'student'"),
    is_active: bool = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    uid = current_user["uid"]

    if role == "student":
        # Courses the user is enrolled in
        query = (
            db.query(Course)
            .join(CourseEnrollment, CourseEnrollment.course_id == Course.id)
            .filter(
                CourseEnrollment.user_id == uid,
                CourseEnrollment.status == "active",
            )
        )
    elif role == "instructor":
        query = db.query(Course).filter(Course.user_id == uid)
    else:
        # Return both owned and enrolled
        enrolled_ids = (
            db.query(CourseEnrollment.course_id)
            .filter(
                CourseEnrollment.user_id == uid,
                CourseEnrollment.status == "active",
            )
            .subquery()
        )
        query = db.query(Course).filter(
            or_(Course.user_id == uid, Course.id.in_(enrolled_ids))
        )

    if is_active is not None:
        query = query.filter(Course.is_active == is_active)

    courses = query.order_by(Course.created_at.desc()).all()
    return [_course_to_out(c, db) for c in courses]


@router.get("/api/courses/{course_id}")
def get_course(
    course_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    course = _verify_course_access(course_id, current_user["uid"], db)
    out = _course_to_out(course, db)

    # Attach enrollment list for the owner
    if course.user_id == current_user["uid"]:
        enrollments = (
            db.query(CourseEnrollment)
            .filter(CourseEnrollment.course_id == course_id)
            .order_by(CourseEnrollment.enrolled_at.desc())
            .all()
        )
        out["enrollments"] = [
            {
                "id": e.id,
                "course_id": e.course_id,
                "user_id": e.user_id,
                "email": e.email,
                "role": e.role,
                "status": e.status,
                "enrolled_at": e.enrolled_at,
                "updated_at": e.updated_at,
            }
            for e in enrollments
        ]

    return out


@router.put("/api/courses/{course_id}")
def update_course(
    course_id: str,
    data: CourseUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    course = _verify_course_owner(course_id, current_user["uid"], db)
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(course, key, value)
    course.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(course)
    return _course_to_out(course, db)


@router.delete("/api/courses/{course_id}", status_code=204)
def delete_course(
    course_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    course = _verify_course_owner(course_id, current_user["uid"], db)

    # Unlink assignments (set course_id = NULL)
    db.query(Assignment).filter(Assignment.course_id == course_id).update(
        {"course_id": None}
    )

    # Delete materials S3 objects
    materials = (
        db.query(CourseMaterial).filter(CourseMaterial.course_id == course_id).all()
    )
    for mat in materials:
        if mat.s3_key and s3_client and AWS_S3_BUCKET:
            try:
                s3_client.delete_object(Bucket=AWS_S3_BUCKET, Key=mat.s3_key)
            except Exception as e:
                logger.warning(f"Failed to delete S3 object {mat.s3_key}: {e}")

    db.delete(course)  # cascades enrollments + materials
    db.commit()
    logger.info(f"Course deleted: {course_id}")
    return None


# ── Enrollment ───────────────────────────────────────────────────────────


@router.post("/api/courses/{course_id}/enroll")
def enroll_students(
    course_id: str,
    data: EnrollStudentsRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    course = _verify_course_owner(course_id, current_user["uid"], db)
    enrolled, pending, failed = [], [], []

    for item in data.students:
        email = item.email.strip().lower()
        if not EMAIL_RE.match(email):
            failed.append(email)
            continue

        user_id, found = _lookup_firebase_user(email)
        status = "active" if found else "pending"

        # Duplicate check
        existing = (
            db.query(CourseEnrollment)
            .filter(
                and_(
                    CourseEnrollment.course_id == course_id,
                    or_(
                        CourseEnrollment.user_id == user_id,
                        CourseEnrollment.email == email,
                    ),
                )
            )
            .first()
        )
        if existing:
            continue

        enrollment = CourseEnrollment(
            course_id=course_id,
            user_id=user_id,
            email=email,
            role=data.role,
            status=status,
        )
        db.add(enrollment)
        if found:
            enrolled.append(enrollment)
        else:
            pending.append(enrollment)

    db.commit()

    all_enrollments = enrolled + pending
    for e in all_enrollments:
        db.refresh(e)

    return {
        "enrolled": len(enrolled),
        "pending": len(pending),
        "failed": failed,
        "enrollments": [
            {
                "id": e.id,
                "course_id": e.course_id,
                "user_id": e.user_id,
                "email": e.email,
                "role": e.role,
                "status": e.status,
                "enrolled_at": e.enrolled_at,
                "updated_at": e.updated_at,
            }
            for e in all_enrollments
        ],
    }


@router.post("/api/courses/{course_id}/enroll-csv")
async def enroll_students_csv(
    course_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    course = _verify_course_owner(course_id, current_user["uid"], db)

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not parse CSV file")

    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty")

    # Find email column (flexible matching)
    email_column = None
    for col in rows[0].keys():
        if col.strip().lower().replace("-", "").replace("_", "") in (
            "email",
            "emailaddress",
            "emailid",
        ):
            email_column = col
            break

    if email_column is None:
        raise HTTPException(
            status_code=400,
            detail="CSV must contain a column named 'email' (case-insensitive)",
        )

    seen = set()
    emails = []
    for row in rows:
        val = row.get(email_column, "")
        if val and val.strip() and val.strip().lower() not in seen:
            seen.add(val.strip().lower())
            emails.append(val.strip().lower())

    enrolled, pending, failed = [], [], []

    for email in emails:
        email = str(email).strip().lower()
        if not EMAIL_RE.match(email):
            failed.append(email)
            continue

        user_id, found = _lookup_firebase_user(email)
        status = "active" if found else "pending"

        # Duplicate check
        existing = (
            db.query(CourseEnrollment)
            .filter(
                and_(
                    CourseEnrollment.course_id == course_id,
                    or_(
                        CourseEnrollment.user_id == user_id,
                        CourseEnrollment.email == email,
                    ),
                )
            )
            .first()
        )
        if existing:
            continue

        enrollment = CourseEnrollment(
            course_id=course_id,
            user_id=user_id,
            email=email,
            role="student",
            status=status,
        )
        db.add(enrollment)
        if found:
            enrolled.append(enrollment)
        else:
            pending.append(enrollment)

    db.commit()

    all_enrollments = enrolled + pending
    for e in all_enrollments:
        db.refresh(e)

    return {
        "enrolled": len(enrolled),
        "pending": len(pending),
        "failed": failed,
        "enrollments": [
            {
                "id": e.id,
                "course_id": e.course_id,
                "user_id": e.user_id,
                "email": e.email,
                "role": e.role,
                "status": e.status,
                "enrolled_at": e.enrolled_at,
                "updated_at": e.updated_at,
            }
            for e in all_enrollments
        ],
    }


@router.get("/api/courses/{course_id}/enrollments")
def list_enrollments(
    course_id: str,
    status: str = Query(None),
    role: str = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _verify_course_access(course_id, current_user["uid"], db)
    query = db.query(CourseEnrollment).filter(CourseEnrollment.course_id == course_id)
    if status:
        query = query.filter(CourseEnrollment.status == status)
    if role:
        query = query.filter(CourseEnrollment.role == role)
    return [
        {
            "id": e.id,
            "course_id": e.course_id,
            "user_id": e.user_id,
            "email": e.email,
            "role": e.role,
            "status": e.status,
            "enrolled_at": e.enrolled_at,
            "updated_at": e.updated_at,
        }
        for e in query.order_by(CourseEnrollment.enrolled_at.desc()).all()
    ]


@router.delete("/api/courses/{course_id}/enrollments/{enrollment_id}", status_code=204)
def remove_enrollment(
    course_id: str,
    enrollment_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _verify_course_owner(course_id, current_user["uid"], db)
    enrollment = (
        db.query(CourseEnrollment)
        .filter(
            and_(
                CourseEnrollment.id == enrollment_id,
                CourseEnrollment.course_id == course_id,
            )
        )
        .first()
    )
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    db.delete(enrollment)
    db.commit()
    return None


# ── Materials ────────────────────────────────────────────────────────────


@router.post("/api/courses/{course_id}/materials", status_code=201)
async def upload_course_material(
    course_id: str,
    file: UploadFile = File(...),
    title: str = Form(...),
    material_type: str = Form("lecture_notes"),
    description: str = Form(None),
    folder: str = Form(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    course = _verify_course_owner(course_id, current_user["uid"], db)

    fname = (file.filename or "").lower()

    if material_type == "video":
        video_types = [
            "video/mp4",
            "video/webm",
            "video/quicktime",
            "video/x-msvideo",
            "video/x-matroska",
            "video/ogg",
        ]
        video_extensions = (".mp4", ".webm", ".mov", ".avi", ".mkv", ".ogg")
        if file.content_type not in video_types and not fname.endswith(
            video_extensions
        ):
            raise HTTPException(
                status_code=400,
                detail="Only MP4, WebM, MOV, AVI, MKV, and OGG video files are supported",
            )
        max_size = 500 * 1024 * 1024  # 500 MB for videos
    else:
        allowed_types = [
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ]
        allowed_extensions = (".pdf", ".docx", ".pptx")
        if file.content_type not in allowed_types and not fname.endswith(
            allowed_extensions
        ):
            raise HTTPException(
                status_code=400, detail="Only PDF, DOCX, and PPTX files are supported"
            )
        max_size = 50 * 1024 * 1024  # 50 MB for documents

    file_content = await file.read()
    if len(file_content) > max_size:
        limit_mb = max_size // (1024 * 1024)
        raise HTTPException(
            status_code=400, detail=f"File too large (max {limit_mb} MB)"
        )

    file_uuid = str(uuid.uuid4())
    s3_key = f"courses/{course_id}/materials/{file_uuid}_{file.filename}"

    if not s3_client or not AWS_S3_BUCKET:
        raise HTTPException(
            status_code=500, detail="S3 storage not configured on this server"
        )

    try:
        s3_client.put_object(
            Bucket=AWS_S3_BUCKET,
            Key=s3_key,
            Body=file_content,
            ContentType=file.content_type,
        )
    except Exception as e:
        logger.error(f"S3 upload failed: {e}")
        raise HTTPException(status_code=500, detail="File upload to S3 failed")

    material = CourseMaterial(
        course_id=course_id,
        title=title,
        description=description,
        material_type=material_type,
        s3_key=s3_key,
        file_name=file.filename,
        file_size=str(len(file_content)),
        mime_type=file.content_type,
        folder=folder,
        transcript_status="processing" if material_type == "video" else None,
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    logger.info(f"Material uploaded: {material.id} to course {course_id}")

    # Kick off background transcription for video uploads
    if material_type == "video":
        upload_executor.submit(
            _transcribe_course_material_background, material.id, s3_key
        )

    return {
        "id": material.id,
        "course_id": material.course_id,
        "title": material.title,
        "description": material.description,
        "material_type": material.material_type,
        "s3_key": material.s3_key,
        "file_name": material.file_name,
        "file_size": material.file_size,
        "mime_type": material.mime_type,
        "folder": material.folder,
        "order": material.order,
        "transcript_status": material.transcript_status,
        "transcript_text": material.transcript_text,
        "created_at": material.created_at,
        "updated_at": material.updated_at,
    }


@router.post("/api/courses/{course_id}/materials/link-video", status_code=201)
def link_video_to_course(
    course_id: str,
    data: CourseMaterialLinkVideo,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    course = _verify_course_owner(course_id, current_user["uid"], db)

    video = (
        db.query(Video)
        .filter(and_(Video.id == data.video_id, Video.user_id == current_user["uid"]))
        .first()
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    material = CourseMaterial(
        course_id=course_id,
        video_id=data.video_id,
        title=data.title,
        description=data.description,
        material_type="video",
        folder=data.folder,
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    return {
        "id": material.id,
        "course_id": material.course_id,
        "video_id": material.video_id,
        "title": material.title,
        "description": material.description,
        "material_type": material.material_type,
        "folder": material.folder,
        "order": material.order,
        "created_at": material.created_at,
        "updated_at": material.updated_at,
    }


@router.get("/api/courses/{course_id}/materials")
def list_materials(
    course_id: str,
    material_type: str = Query(None),
    folder: str = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _verify_course_access(course_id, current_user["uid"], db)
    query = (
        db.query(CourseMaterial)
        .options(joinedload(CourseMaterial.video))
        .filter(CourseMaterial.course_id == course_id)
    )
    if material_type:
        query = query.filter(CourseMaterial.material_type == material_type)
    if folder:
        query = query.filter(CourseMaterial.folder == folder)
    materials = query.order_by(CourseMaterial.order, CourseMaterial.created_at).all()

    result = []
    for m in materials:
        # Resolve transcript from linked Gallery video when video_id is present
        if m.video_id and m.video:
            eff_transcript_text = m.video.transcript_text
            eff_transcript_status = (
                "completed" if m.video.transcript_text else "not_available"
            )
        else:
            eff_transcript_text = m.transcript_text
            eff_transcript_status = m.transcript_status

        result.append(
            {
                "id": m.id,
                "course_id": m.course_id,
                "title": m.title,
                "description": m.description,
                "material_type": m.material_type,
                "s3_key": m.s3_key,
                "video_id": m.video_id,
                "external_url": m.external_url,
                "file_name": m.file_name,
                "file_size": m.file_size,
                "mime_type": m.mime_type,
                "order": m.order,
                "folder": m.folder,
                "transcript_text": eff_transcript_text,
                "transcript_status": eff_transcript_status,
                "created_at": m.created_at,
                "updated_at": m.updated_at,
            }
        )
    return result


@router.get("/api/courses/{course_id}/materials/{material_id}/download")
def download_material(
    course_id: str,
    material_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _verify_course_access(course_id, current_user["uid"], db)
    material = (
        db.query(CourseMaterial)
        .filter(
            and_(
                CourseMaterial.id == material_id,
                CourseMaterial.course_id == course_id,
            )
        )
        .first()
    )
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")
    if not material.s3_key:
        raise HTTPException(status_code=400, detail="Material has no downloadable file")

    if not s3_client or not AWS_S3_BUCKET:
        raise HTTPException(status_code=500, detail="S3 not configured")

    try:
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": AWS_S3_BUCKET, "Key": material.s3_key},
            ExpiresIn=3600,
        )
    except Exception as e:
        logger.error(f"Presign failed: {e}")
        raise HTTPException(status_code=500, detail="Could not generate download link")

    return {"download_url": url, "expires_in": 3600}


@router.delete("/api/courses/{course_id}/materials/{material_id}", status_code=204)
def delete_material(
    course_id: str,
    material_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _verify_course_owner(course_id, current_user["uid"], db)
    material = (
        db.query(CourseMaterial)
        .filter(
            and_(
                CourseMaterial.id == material_id,
                CourseMaterial.course_id == course_id,
            )
        )
        .first()
    )
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")

    # Delete from S3
    if material.s3_key and s3_client and AWS_S3_BUCKET:
        try:
            s3_client.delete_object(Bucket=AWS_S3_BUCKET, Key=material.s3_key)
        except Exception as e:
            logger.warning(f"S3 delete failed for {material.s3_key}: {e}")

    db.delete(material)
    db.commit()
    return None


# ── Course-scoped Assignment Listing ─────────────────────────────────────


@router.get("/api/courses/{course_id}/assignments")
def list_course_assignments(
    course_id: str,
    status: str = Query(None, description="Filter by assignment status"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    course = _verify_course_access(course_id, current_user["uid"], db)
    if not status:
        assignments = (
            db.query(Assignment)
            .filter(Assignment.course_id == course_id)
            .order_by(Assignment.created_at.desc())
            .all()
        )
    else:
        assignments = (
            db.query(Assignment)
            .filter(Assignment.course_id == course_id)
            .filter(Assignment.status == status)
            .order_by(Assignment.created_at.desc())
            .all()
        )

    from routes.assignments import filter_sensitive_data_for_students

    user_uid = current_user["uid"]
    is_owner = course.user_id == user_uid

    result = []
    for a in assignments:
        assignment_dict = {
            "id": a.id,
            "user_id": a.user_id,
            "title": a.title,
            "description": a.description,
            "course_id": a.course_id,
            "due_date": a.due_date,
            "total_points": a.total_points,
            "total_questions": a.total_questions,
            "status": a.status,
            "shared_count": a.shared_count,
            "question_types": a.question_types,
            "engineering_level": a.engineering_level,
            "engineering_discipline": a.engineering_discipline,
            "google_form_url": a.google_form_url,
            "google_form_response_url": a.google_form_response_url,
            "questions": a.questions,
            "created_at": a.created_at,
            "updated_at": a.updated_at,
        }
        if not is_owner:
            assignment_dict = filter_sensitive_data_for_students(
                assignment_dict, user_uid, db
            )
        result.append(assignment_dict)

    return result
