import os
import threading
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from utils.db import SessionLocal
from utils.youtube_utils import download_video
from utils.format_transcript import create_formatted_transcript
from models import Video, Assignment, AssignmentSubmission
from .config import (
    frames_path,
    output_path,
    s3_client,
    AWS_S3_BUCKET,
    logger,
)
from .storage import s3_upload_file, generate_thumbnail
from .db_helpers import (
    update_download_status,
    update_formatting_status,
    get_formatting_status,
)


def download_video_background(video_id: str, url: str, user_id: str):
    logger.info(f"Starting background download for video ID: {video_id}")
    db = SessionLocal()
    try:
        status = {
            "status": "downloading",
            "message": "Video download in progress...",
            "path": None,
        }
        update_download_status(db, video_id, status)
        logger.info(f"Downloading video from URL: {url}")
        video_local_path = download_video(url, video_id_param=video_id)
        if video_local_path and os.path.exists(video_local_path):
            logger.info(f"Video downloaded successfully to: {video_local_path}")
            s3_key = None
            thumb_key = None
            if s3_client and AWS_S3_BUCKET:
                try:
                    logger.info(
                        f"Uploading video to S3 for video ID: {video_id}, user: {user_id}"
                    )
                    # Use user-specific S3 key structure
                    s3_key = f"youtube_videos/{user_id}/{video_id}.mp4"
                    s3_upload_file(video_local_path, s3_key, content_type="video/mp4")
                    logger.info(f"Video uploaded to S3 with key: {s3_key}")

                    logger.info(f"Generating thumbnail for video ID: {video_id}")
                    thumb_path = os.path.join(frames_path, f"{video_id}_thumb.jpg")
                    if generate_thumbnail(video_local_path, thumb_path, ts_seconds=1.0):
                        # Use user-specific thumbnail key structure
                        thumb_key = f"youtube_thumbnails/{user_id}/{video_id}.jpg"
                        s3_upload_file(thumb_path, thumb_key, content_type="image/jpeg")
                        logger.info(f"Thumbnail uploaded to S3 with key: {thumb_key}")
                        os.remove(thumb_path)
                    video_row = db.query(Video).filter(Video.id == video_id).first()
                    if video_row:
                        video_row.s3_key = s3_key
                        video_row.thumb_key = thumb_key
                        video_row.download_path = None
                        db.commit()
                    os.remove(video_local_path)
                    logger.info(
                        f"Local video file removed after S3 upload for video ID: {video_id}"
                    )
                    status = {
                        "status": "completed",
                        "message": "Video and thumbnail uploaded to S3 successfully",
                        "path": None,
                        "s3_key": s3_key,
                        "thumb_key": thumb_key,
                    }
                except Exception as e:
                    logger.error(f"S3 upload failed for video ID {video_id}: {e}")
                    status = {
                        "status": "completed",
                        "message": "Video download complete (S3 upload failed)",
                        "path": video_local_path,
                    }
            else:
                logger.info(
                    f"S3 not configured, keeping local file for video ID: {video_id}"
                )
                status = {
                    "status": "completed",
                    "message": "Video download complete (S3 not configured)",
                    "path": video_local_path,
                }
            update_download_status(db, video_id, status)
            logger.info(f"Download status updated for video ID: {video_id}")
        else:
            logger.error(f"Video download failed for video ID: {video_id}")
            update_download_status(
                db,
                video_id,
                {"status": "failed", "message": "Video download failed", "path": None},
            )
    finally:
        db.close()


def format_transcript_background(video_id: str, json_data: dict):
    logger.info(f"Starting transcript formatting for video ID: {video_id}")
    db = SessionLocal()
    try:
        status = {
            "status": "formatting",
            "message": "AI-based transcript formatting in progress...",
            "formatted_transcript": None,
            "error": None,
            "progress": 0,
            "total_chunks": 0,
            "current_chunk": 0,
        }
        update_formatting_status(db, video_id, status)
        logger.info(f"Creating formatted transcript for video ID: {video_id}")
        formatted_transcript_lines = create_formatted_transcript(
            json_data, video_id=video_id
        )
        # Ensure all items are strings before join to avoid type errors
        formatted_transcript_text = "".join(
            [str(line) for line in formatted_transcript_lines]
        )
        transcript_s3_key = None
        if s3_client and AWS_S3_BUCKET and formatted_transcript_text:
            # Get the video record to find the user_id
            video = db.query(Video).filter(Video.id == video_id).first()
            user_id = video.user_id if video else None

            if user_id:
                logger.info(
                    f"Uploading formatted transcript to S3 for video ID: {video_id}, user: {user_id}"
                )
                temp_transcript_path = os.path.join(
                    output_path, f"{video_id}_formatted_transcript.txt"
                )
                with open(temp_transcript_path, "w", encoding="utf-8") as f:
                    f.write(formatted_transcript_text)
                # Use user-specific transcript key structure
                transcript_s3_key = (
                    f"youtube_transcripts/{user_id}/{video_id}_formatted.txt"
                )
                s3_upload_file(
                    temp_transcript_path, transcript_s3_key, content_type="text/plain"
                )
                logger.info(
                    f"Formatted transcript uploaded to S3 with key: {transcript_s3_key}"
                )
                os.remove(temp_transcript_path)
            else:
                logger.warning(
                    f"User ID not found for video {video_id}, skipping transcript upload"
                )
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.formatted_transcript = formatted_transcript_text
            if transcript_s3_key:
                video.transcript_s3_key = transcript_s3_key
            db.commit()
        current_status = get_formatting_status(db, video_id)
        status = {
            "status": "completed",
            "message": "AI transcript formatting complete",
            "formatted_transcript": formatted_transcript_text,
            "error": None,
            "progress": 100,
            "total_chunks": current_status.get("total_chunks", 0),
            "current_chunk": current_status.get("total_chunks", 0),
            "transcript_s3_key": transcript_s3_key,
        }
        update_formatting_status(db, video_id, status)
        logger.info(
            f"Transcript formatting completed successfully for video ID: {video_id}"
        )
    except Exception as e:
        logger.error(f"Transcript formatting failed for video ID {video_id}: {e}")
        status = {
            "status": "failed",
            "message": f"Transcript formatting failed: {str(e)}",
            "formatted_transcript": None,
            "error": str(e),
            "progress": 0,
            "total_chunks": 0,
            "current_chunk": 0,
        }
        update_formatting_status(db, video_id, status)
    finally:
        db.close()


def format_uploaded_transcript_background(
    video_id: str, transcript_text: str, title: str = "Uploaded Video"
):
    db = SessionLocal()
    try:
        status = {
            "status": "formatting",
            "message": "AI-based transcript formatting in progress...",
            "formatted_transcript": None,
            "error": None,
            "progress": 0,
            "total_chunks": 0,
            "current_chunk": 0,
        }
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            video = Video(id=video_id, source_type="uploaded", title=title)
            db.add(video)
            db.commit()
            db.refresh(video)
        video.formatting_status = status
        db.add(video)
        db.commit()
        transcript_data = {"plain_text": transcript_text, "title": title, "duration": 0}
        formatted_transcript_lines = create_formatted_transcript(
            transcript_data, video_id=video_id
        )
        formatted_transcript_text = "".join(
            [str(line) for line in formatted_transcript_lines]
        )
        transcript_s3_key = None
        if s3_client and AWS_S3_BUCKET and formatted_transcript_text:
            temp_transcript_path = os.path.join(
                output_path, f"{video_id}_formatted_transcript.txt"
            )
            with open(temp_transcript_path, "w", encoding="utf-8") as f:
                f.write(formatted_transcript_text)
            transcript_s3_key = f"uploaded_transcripts/{video_id}_formatted.txt"
            s3_upload_file(
                temp_transcript_path, transcript_s3_key, content_type="text/plain"
            )
            os.remove(temp_transcript_path)
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.formatted_transcript = formatted_transcript_text
            if transcript_s3_key:
                video.transcript_s3_key = transcript_s3_key
            db.commit()
        current_status = get_formatting_status(db, video_id)
        status = {
            "status": "completed",
            "message": "AI transcript formatting complete",
            "formatted_transcript": formatted_transcript_text,
            "error": None,
            "progress": 100,
            "total_chunks": current_status.get("total_chunks", 0),
            "current_chunk": current_status.get("total_chunks", 0),
            "transcript_s3_key": transcript_s3_key,
        }
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.formatting_status = status
            video.formatted_transcript = formatted_transcript_text
            db.add(video)
            db.commit()
    except Exception as e:
        status = {
            "status": "failed",
            "message": f"Transcript formatting failed: {str(e)}",
            "formatted_transcript": None,
            "error": str(e),
            "progress": 0,
            "total_chunks": 0,
            "current_chunk": 0,
        }
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.formatting_status = status
            db.add(video)
            db.commit()
    finally:
        db.close()


def grade_submission_background(
    assignment_id: str, submission_id: str, options: Optional[Dict[str, Any]] = None
):
    """Grade a single submission in the background."""
    logger.info(f"Starting background grading for submission {submission_id}")
    db = SessionLocal()
    try:
        # Get assignment and submission
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        submission = (
            db.query(AssignmentSubmission)
            .filter(AssignmentSubmission.id == submission_id)
            .first()
        )

        if not assignment or not submission:
            logger.error(
                f"Assignment or submission not found: {assignment_id}, {submission_id}"
            )
            return

        # Prepare assignment dict
        assignment_dict = {
            "id": assignment.id,
            "title": assignment.title,
            "questions": assignment.questions or [],
            "ai_penalty_percentage": assignment.ai_penalty_percentage
            if assignment.ai_penalty_percentage is not None
            else 50.0,
        }

        # Run grading
        from utils.grading_service import LLMGrader

        model = options.get("model", "gpt-4o") if options else "gpt-4o"
        grader = LLMGrader(model=model)

        (
            total_score,
            total_points,
            feedback_by_question,
            overall_feedback,
        ) = grader.grade_submission(
            assignment=assignment_dict,
            submission_answers=submission.answers or {},
            options=options,
            telemetry_data=submission.telemetry_data,  # Pass telemetry for AI detection
            submission_method=submission.submission_method or "in-app",
        )

        # Update submission with results
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
        logger.info(
            f"Successfully graded submission {submission_id}: {total_score}/{total_points}"
        )

    except Exception as e:
        logger.error(f"Error grading submission {submission_id}: {str(e)}")
        # Update status to failed
        try:
            submission = (
                db.query(AssignmentSubmission)
                .filter(AssignmentSubmission.id == submission_id)
                .first()
            )
            if submission:
                submission.status = "submitted"  # Revert to submitted
                submission.updated_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def queue_batch_grading(
    assignment_id: str, submission_ids: List[str], options: Optional[Any] = None
):
    """Queue multiple submissions for background grading."""
    logger.info(f"Queueing {len(submission_ids)} submissions for background grading")

    # Convert options to dict if it's a Pydantic model
    options_dict = options.dict() if hasattr(options, "dict") else (options or {})

    # Start grading each submission in a separate thread
    for sub_id in submission_ids:
        thread = threading.Thread(
            target=grade_submission_background,
            args=(assignment_id, sub_id, options_dict),
            daemon=True,
        )
        thread.start()

    logger.info(f"Started {len(submission_ids)} grading threads")
