"""Class performance analytics for a course — stats endpoint + XLSX export."""
from __future__ import annotations

import asyncio
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from utils.db import get_db
from utils.firebase_auth import get_current_user
from utils.firebase_users import get_users_by_uids
from utils.performance_stats import (
    coerce_percentages,
    compute_assignment_stats,
    compute_histogram,
    compute_submission_rates,
    is_on_time,
    normalize_weightages,
)
from utils.performance_xlsx import build_workbook
from models import Assignment, AssignmentSubmission, CourseEnrollment
from routes.courses import _verify_course_owner

router = APIRouter()


# ── helpers ──────────────────────────────────────────────────────────────


def _split_assignment_ids(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [a.strip() for a in raw.split(",") if a.strip()]


def _build_performance_payload(
    course_id: str,
    assignment_ids: list[str],
    db: Session,
) -> dict:
    """Shared aggregation used by both endpoints."""
    q = db.query(Assignment).filter(Assignment.course_id == course_id)
    if assignment_ids:
        q = q.filter(Assignment.id.in_(assignment_ids))
    else:
        q = q.filter(Assignment.status == "published")
    assignments = q.order_by(
        Assignment.due_date.asc().nullslast(), Assignment.created_at.asc()
    ).all()

    if not assignments:
        return {"assignments": [], "students": [], "trend": []}

    aids = [a.id for a in assignments]

    students_q = (
        db.query(CourseEnrollment)
        .filter(
            CourseEnrollment.course_id == course_id,
            CourseEnrollment.role == "student",
            CourseEnrollment.status == "active",
        )
        .all()
    )
    real_uids = [
        e.user_id
        for e in students_q
        if e.user_id and not e.user_id.startswith("pending_")
    ]

    try:
        fb_records = asyncio.run(get_users_by_uids(real_uids)) if real_uids else []
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            fb_records = (
                loop.run_until_complete(get_users_by_uids(real_uids))
                if real_uids
                else []
            )
        finally:
            loop.close()
    fb_by_uid = {r["uid"]: r for r in fb_records}

    submissions = (
        db.query(AssignmentSubmission)
        .filter(AssignmentSubmission.assignment_id.in_(aids))
        .filter(AssignmentSubmission.status.in_(["submitted", "graded", "returned"]))
        .all()
    )
    subs_by_assignment: dict[str, list[AssignmentSubmission]] = {
        aid: [] for aid in aids
    }
    for s in submissions:
        subs_by_assignment.setdefault(s.assignment_id, []).append(s)

    enrolled_count = len(students_q)

    assignments_out = []
    trend = []
    for a in assignments:
        subs = subs_by_assignment.get(a.id, [])
        percentages = coerce_percentages(s.percentage for s in subs)
        stats = compute_assignment_stats(percentages)
        histogram = compute_histogram(percentages)
        submitted_count = len(subs)
        on_time_count = sum(1 for s in subs if is_on_time(s.submitted_at, a.due_date))
        sub_rate, on_time_rate = compute_submission_rates(
            submitted_count, on_time_count, enrolled_count
        )
        assignments_out.append(
            {
                "id": a.id,
                "title": a.title,
                "due_date": a.due_date.isoformat() if a.due_date else None,
                "total_points": a.total_points,
                "stats": stats,
                "histogram": histogram,
                "submission_rate": sub_rate,
                "on_time_rate": on_time_rate,
            }
        )
        trend.append(
            {
                "assignment_id": a.id,
                "title": a.title,
                "due_date": a.due_date.isoformat() if a.due_date else None,
                "mean_pct": stats["mean"],
            }
        )

    students_out = []
    for e in students_q:
        fb = fb_by_uid.get(e.user_id) if e.user_id else None
        scores: dict[str, Optional[float]] = {}
        for aid in aids:
            match = next(
                (s for s in subs_by_assignment.get(aid, []) if s.user_id == e.user_id),
                None,
            )
            if match is None:
                scores[aid] = None
            else:
                try:
                    scores[aid] = (
                        float(match.percentage)
                        if match.percentage is not None
                        else None
                    )
                except (TypeError, ValueError):
                    scores[aid] = None
        students_out.append(
            {
                "user_id": e.user_id,
                "email": (fb["email"] if fb else None) or e.email,
                "name": (fb["displayName"] if fb else None)
                or (e.email.split("@")[0] if e.email else "Student"),
                "scores": scores,
            }
        )

    return {"assignments": assignments_out, "students": students_out, "trend": trend}


# ── endpoints ────────────────────────────────────────────────────────────


@router.get("/api/courses/{course_id}/performance")
def get_class_performance(
    course_id: str,
    assignment_ids: Optional[str] = Query(
        None, description="Comma-separated assignment IDs; omit for all published"
    ),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _verify_course_owner(course_id, current_user["uid"], db)
    aids = _split_assignment_ids(assignment_ids)
    return _build_performance_payload(course_id, aids, db)


class PerformanceExportRequest(BaseModel):
    assignment_ids: list[str] = Field(default_factory=list)
    weightages: dict[str, float] = Field(default_factory=dict)


@router.post("/api/courses/{course_id}/performance/export")
def export_class_performance(
    course_id: str,
    body: PerformanceExportRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    course = _verify_course_owner(course_id, current_user["uid"], db)

    if not body.assignment_ids:
        raise HTTPException(
            status_code=400, detail="Select at least one assignment to export"
        )

    payload = _build_performance_payload(course_id, body.assignment_ids, db)
    if not payload["assignments"]:
        raise HTTPException(
            status_code=404, detail="No assignments found for the selected IDs"
        )

    actual_ids = [a["id"] for a in payload["assignments"]]
    weights = normalize_weightages(body.weightages, actual_ids)

    buffer = build_workbook(
        course_title=course.title,
        assignments=payload["assignments"],
        students=payload["students"],
        weightages=weights,
    )

    safe_code = (course.course_code or course.title or "course").replace(" ", "_")
    filename = f"{safe_code}_class_performance.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{quote(filename)}"'},
    )
