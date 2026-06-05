"""
Transactional email layer built on Brevo's /v3/smtp/email API.

Mirrors the style of src/services/brevo.py (which handles only marketing-list
contact sync). All sends are fire-and-forget on a daemon thread so HTTP requests
are never blocked by email delivery, and an unset BREVO_API_KEY is a silent
no-op (warning logged) rather than a 500.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Thread
from typing import Any, Iterable

import jwt
import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL", "")
BREVO_SENDER_NAME = os.environ.get("BREVO_SENDER_NAME", "Vidya AI")
BREVO_SMTP_URL = "https://api.brevo.com/v3/smtp/email"

FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "http://localhost:3000").rstrip(
    "/"
)
INVITE_TOKEN_SECRET = os.environ.get("INVITE_TOKEN_SECRET", "")
INVITE_TOKEN_TTL_DAYS = 14

_TEMPLATES_DIR = Path(__file__).parent / "email_templates"
_jinja = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "htm"]),
    enable_async=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


# ── core sender ──────────────────────────────────────────────────────────


def _send_via_brevo(
    to_email: str,
    to_name: str | None,
    subject: str,
    html: str,
    text: str | None,
    tags: list[str] | None,
    reply_to: str | None,
) -> None:
    if not BREVO_API_KEY:
        logger.warning(
            "BREVO_API_KEY not set; skipping transactional email to %s (subject=%r)",
            to_email,
            subject,
        )
        return
    if not BREVO_SENDER_EMAIL:
        logger.error(
            "BREVO_SENDER_EMAIL not set; cannot send transactional email to %s",
            to_email,
        )
        return

    payload: dict[str, Any] = {
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": to_email, **({"name": to_name} if to_name else {})}],
        "subject": subject,
        "htmlContent": html,
    }
    if text:
        payload["textContent"] = text
    if tags:
        payload["tags"] = tags
    if reply_to:
        payload["replyTo"] = {"email": reply_to}

    try:
        response = requests.post(
            BREVO_SMTP_URL,
            json=payload,
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "api-key": BREVO_API_KEY,
            },
            timeout=10,
        )
        if response.status_code in (200, 201):
            logger.info(
                "Brevo: transactional email sent to %s (subject=%r, tags=%s)",
                to_email,
                subject,
                tags,
            )
        else:
            logger.error(
                "Brevo transactional error %s for %s: %s",
                response.status_code,
                to_email,
                response.text,
            )
    except Exception as e:
        logger.error("Brevo transactional send failed for %s: %s", to_email, e)


def send_transactional_email(
    to_email: str,
    to_name: str | None,
    subject: str,
    html: str,
    text: str | None = None,
    tags: list[str] | None = None,
    reply_to: str | None = None,
) -> None:
    """Send synchronously. Use the _background variant unless you have a reason."""
    _send_via_brevo(to_email, to_name, subject, html, text, tags, reply_to)


def send_transactional_email_background(
    to_email: str,
    to_name: str | None,
    subject: str,
    html: str,
    text: str | None = None,
    tags: list[str] | None = None,
    reply_to: str | None = None,
) -> None:
    """Fire-and-forget send. Never blocks the caller."""
    if not to_email:
        return
    Thread(
        target=_send_via_brevo,
        args=(to_email, to_name, subject, html, text, tags, reply_to),
        daemon=True,
    ).start()


# ── template rendering ──────────────────────────────────────────────────


def _render(template_base: str, ctx: dict[str, Any]) -> tuple[str, str]:
    """Render a (html, text) pair from `<template_base>.html.j2` + `<template_base>.txt.j2`."""
    html = _jinja.get_template(f"{template_base}.html.j2").render(**ctx)
    text = _jinja.get_template(f"{template_base}.txt.j2").render(**ctx)
    return html, text


# ── invite tokens (JWT) ─────────────────────────────────────────────────


def issue_invite_token(enrollment_id: str, email: str, course_id: str) -> str:
    if not INVITE_TOKEN_SECRET:
        # Tokens issued without a secret would be trivially forgeable; refuse.
        raise RuntimeError("INVITE_TOKEN_SECRET is not configured")
    payload = {
        "enrollment_id": enrollment_id,
        "email": email.lower(),
        "course_id": course_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=INVITE_TOKEN_TTL_DAYS),
        "iat": datetime.now(timezone.utc),
        "kind": "enrollment_invite",
    }
    return jwt.encode(payload, INVITE_TOKEN_SECRET, algorithm="HS256")


def verify_invite_token(token: str) -> dict[str, Any]:
    """Decode + validate. Raises jwt.PyJWTError on failure."""
    if not INVITE_TOKEN_SECRET:
        raise RuntimeError("INVITE_TOKEN_SECRET is not configured")
    payload = jwt.decode(token, INVITE_TOKEN_SECRET, algorithms=["HS256"])
    if payload.get("kind") != "enrollment_invite":
        raise jwt.InvalidTokenError("wrong token kind")
    return payload


def issue_share_invite_token(access_id: str, email: str, share_token: str) -> str:
    if not INVITE_TOKEN_SECRET:
        raise RuntimeError("INVITE_TOKEN_SECRET is not configured")
    payload = {
        "access_id": access_id,
        "email": email.lower(),
        "share_token": share_token,
        "exp": datetime.now(timezone.utc) + timedelta(days=INVITE_TOKEN_TTL_DAYS),
        "iat": datetime.now(timezone.utc),
        "kind": "share_invite",
    }
    return jwt.encode(payload, INVITE_TOKEN_SECRET, algorithm="HS256")


def verify_share_invite_token(token: str) -> dict[str, Any]:
    """Decode + validate a share-invite token. Raises jwt.PyJWTError on failure."""
    if not INVITE_TOKEN_SECRET:
        raise RuntimeError("INVITE_TOKEN_SECRET is not configured")
    payload = jwt.decode(token, INVITE_TOKEN_SECRET, algorithms=["HS256"])
    if payload.get("kind") != "share_invite":
        raise jwt.InvalidTokenError("wrong token kind")
    return payload


# ── domain-specific senders (welcome / enrollment / updates) ────────────


def send_welcome_email_background(user) -> None:
    """Trigger when User.user_type transitions NULL -> 'student' | 'professor'."""
    if not user.email:
        return
    first_name = (user.name or "").split(" ", 1)[0] if user.name else ""
    role = user.user_type
    if role not in ("student", "professor"):
        return
    template_base = f"welcome_{role}"
    ctx = {
        "first_name": first_name or "there",
        "frontend_url": FRONTEND_BASE_URL,
    }
    html, text = _render(template_base, ctx)
    subject = (
        "Welcome to Vidya AI"
        if role == "student"
        else "Welcome to Vidya AI — your instructor workspace is ready"
    )
    send_transactional_email_background(
        to_email=user.email,
        to_name=user.name,
        subject=subject,
        html=html,
        text=text,
        tags=[f"welcome-{role}"],
    )


def send_enrollment_active_email_background(enrollment, course) -> None:
    """Registered student enrolled — send a 'you're in' email with deep link."""
    if not enrollment.email:
        return
    ctx = {
        "course_title": course.title,
        "course_code": course.course_code or "",
        "course_url": f"{FRONTEND_BASE_URL}/assignments?courseId={course.id}",
        "role": enrollment.role,
    }
    html, text = _render("enrollment_active", ctx)
    send_transactional_email_background(
        to_email=enrollment.email,
        to_name=None,
        subject=f"You've been enrolled in {course.title}",
        html=html,
        text=text,
        tags=["enrollment-active"],
    )


def send_enrollment_invite_email_background(enrollment, course) -> None:
    """Unregistered student — issue a token and send the accept link."""
    if not enrollment.email:
        return
    if not INVITE_TOKEN_SECRET:
        logger.error(
            "INVITE_TOKEN_SECRET not set; cannot issue invite token for enrollment %s",
            enrollment.id,
        )
        return
    token = issue_invite_token(enrollment.id, enrollment.email, course.id)
    accept_url = f"{FRONTEND_BASE_URL}/enroll/accept?token={token}"
    ctx = {
        "course_title": course.title,
        "course_code": course.course_code or "",
        "accept_url": accept_url,
        "expires_days": INVITE_TOKEN_TTL_DAYS,
    }
    html, text = _render("enrollment_invite", ctx)
    send_transactional_email_background(
        to_email=enrollment.email,
        to_name=None,
        subject=f"You're invited to join {course.title} on Vidya AI",
        html=html,
        text=text,
        tags=["enrollment-invite"],
    )


def _fanout_course_email(
    template_base: str,
    subject: str,
    tags: list[str],
    recipients: Iterable[tuple[str, str | None]],
    ctx: dict[str, Any],
) -> None:
    """
    One daemon thread iterates the recipient list and sends per-email.
    Avoids spawning N threads for large classes.
    """
    recipients_list = [(e, n) for e, n in recipients if e]
    if not recipients_list:
        return
    html, text = _render(template_base, ctx)

    def _worker() -> None:
        for to_email, to_name in recipients_list:
            _send_via_brevo(to_email, to_name, subject, html, text, tags, None)

    Thread(target=_worker, daemon=True).start()


def send_course_material_added_email_background(
    course, material, recipients: Iterable[tuple[str, str | None]]
) -> None:
    ctx = {
        "course_title": course.title,
        "course_code": course.course_code or "",
        "material_title": material.title,
        "material_type": material.material_type or "material",
        "course_url": f"{FRONTEND_BASE_URL}/assignments?courseId={course.id}",
    }
    _fanout_course_email(
        template_base="course_material_added",
        subject=f"New material in {course.title}: {material.title}",
        tags=["course-material-added"],
        recipients=recipients,
        ctx=ctx,
    )


def _share_resource_label(share_link, resource_title: str) -> str:
    """Human label for the share type, e.g. 'a chat' or 'a folder'."""
    if share_link.share_type == "folder":
        return f'folder "{resource_title}"' if resource_title else "a folder"
    if share_link.share_type == "chat":
        return f'chat "{resource_title}"' if resource_title else "a chat"
    return f'"{resource_title}"' if resource_title else "a resource"


def send_share_invite_registered_email_background(
    share_link, owner_name: str, to_email: str, resource_title: str
) -> None:
    """Send to a registered Firebase user with a direct link to /shared/<token>."""
    if not to_email:
        return
    share_url = f"{FRONTEND_BASE_URL}/shared/{share_link.share_token}"
    type_label = "chat" if share_link.share_type == "chat" else "folder"
    title = resource_title or share_link.title or ""
    ctx = {
        "owner_name": owner_name or "Someone",
        "resource_type": type_label,
        "resource_label": _share_resource_label(share_link, title),
        "resource_title": title,
        "description": share_link.description or "",
        "share_url": share_url,
    }
    html, text = _render("share_invite_registered", ctx)
    subject_title = title or type_label
    send_transactional_email_background(
        to_email=to_email,
        to_name=None,
        subject=f"{ctx['owner_name']} shared a {type_label} with you: {subject_title}",
        html=html,
        text=text,
        tags=["share-invite-registered"],
    )


def send_share_invite_unregistered_email_background(
    access, share_link, owner_name: str, resource_title: str
) -> None:
    """Send to an unregistered email; recipient signs in/up to accept the share."""
    if not access.email:
        return
    if not INVITE_TOKEN_SECRET:
        logger.error(
            "INVITE_TOKEN_SECRET not set; cannot issue share-invite token for access %s",
            access.id,
        )
        return
    token = issue_share_invite_token(access.id, access.email, share_link.share_token)
    accept_url = f"{FRONTEND_BASE_URL}/shared/accept?token={token}"
    type_label = "chat" if share_link.share_type == "chat" else "folder"
    title = resource_title or share_link.title or ""
    ctx = {
        "owner_name": owner_name or "Someone",
        "resource_type": type_label,
        "resource_label": _share_resource_label(share_link, title),
        "resource_title": title,
        "description": share_link.description or "",
        "accept_url": accept_url,
        "expires_days": INVITE_TOKEN_TTL_DAYS,
    }
    html, text = _render("share_invite_unregistered", ctx)
    subject_title = title or type_label
    send_transactional_email_background(
        to_email=access.email,
        to_name=None,
        subject=f"{ctx['owner_name']} shared a {type_label} with you: {subject_title}",
        html=html,
        text=text,
        tags=["share-invite-unregistered"],
    )


def send_assignment_published_email_background(
    course, assignment, recipients: Iterable[tuple[str, str | None]]
) -> None:
    due_str = ""
    if assignment.due_date:
        try:
            due_str = assignment.due_date.strftime("%b %d, %Y at %I:%M %p UTC")
        except Exception:
            due_str = str(assignment.due_date)
    ctx = {
        "course_title": course.title,
        "course_code": course.course_code or "",
        "assignment_title": assignment.title,
        "due_str": due_str,
        "assignment_url": f"{FRONTEND_BASE_URL}/assignments?courseId={course.id}",
    }
    _fanout_course_email(
        template_base="assignment_published",
        subject=f"New assignment in {course.title}: {assignment.title}",
        tags=["assignment-published"],
        recipients=recipients,
        ctx=ctx,
    )
