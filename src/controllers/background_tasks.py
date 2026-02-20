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
    update_transcript_status,
    get_transcript_status,
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


def download_transcript_background(video_id: str, user_id: str):
    """
    Background task to download/transcribe YouTube video when captions aren't available.
    Uses RapidAPI video download + FFmpeg audio extraction + Deepgram transcription with word-level timing + GPT-4o cleaning.
    """
    logger.info(f"Starting background transcript generation for video ID: {video_id}")
    db = SessionLocal()
    temp_audio_file = None

    try:
        # Import here to avoid circular dependency
        from utils.youtube_utils import download_youtube_audio_rapidapi
        from controllers.storage import transcribe_video_with_deepgram_timed
        from controllers.video_service import get_video_title
        from controllers.config import openai_client

        # Get video title
        video_title = "YouTube Video"
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            video_title = loop.run_until_complete(get_video_title(video_id))
            loop.close()
        except Exception as title_error:
            logger.warning(f"Failed to get video title: {title_error}")

        # Update status: Downloading video
        status = {
            "status": "processing",
            "message": "Downloading video from YouTube...",
            "progress": 10,
            "stage": "download"
        }
        update_transcript_status(db, video_id, status)

        # Download and extract audio using RapidAPI
        logger.info(f"Downloading video for {video_id} via RapidAPI...")
        temp_audio_file = download_youtube_audio_rapidapi(video_id)

        if not temp_audio_file:
            raise Exception("Failed to download audio from YouTube")

        # Update status: Extracting audio (FFmpeg already did this in download function)
        status = {
            "status": "processing",
            "message": "Audio extracted successfully, preparing for transcription...",
            "progress": 30,
            "stage": "extract"
        }
        update_transcript_status(db, video_id, status)

        # Update status: Transcribing
        status = {
            "status": "processing",
            "message": "Transcribing with AI (this may take a few minutes for long videos)...",
            "progress": 40,
            "stage": "transcribe"
        }
        update_transcript_status(db, video_id, status)

        # Transcribe with Deepgram (with word-level timing)
        logger.info(f"Transcribing audio for video {video_id} with Deepgram (timed)...")
        timed_data = transcribe_video_with_deepgram_timed(temp_audio_file, video_title)

        # Clean up temp file
        if temp_audio_file and os.path.exists(temp_audio_file):
            try:
                os.remove(temp_audio_file)
                logger.info(f"Cleaned up temporary audio file: {temp_audio_file}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to clean up temp file: {cleanup_error}")
            temp_audio_file = None

        if not timed_data or not timed_data.get("transcription"):
            raise Exception("Deepgram returned empty transcript")

        # Extract plain text from timed segments
        raw_transcript = " ".join([seg["text"] for seg in timed_data["transcription"]])

        # Update status: Cleaning transcript
        status = {
            "status": "processing",
            "message": "Cleaning transcript with AI for better readability...",
            "progress": 75,
            "stage": "clean"
        }
        update_transcript_status(db, video_id, status)

        # Clean transcript with GPT-4o
        logger.info(f"Cleaning transcript with GPT-4o for video {video_id}...")
        cleaned_transcript = raw_transcript  # Default to raw if cleaning fails
        try:
            if openai_client:
                response = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    temperature=0.3,
                    messages=[
                        {
                            "role": "system",
                            "content": """You are an expert transcript editor. Clean this transcript by:
1. Removing timestamps and metadata
2. Fixing grammar and punctuation
3. Adding paragraph breaks every 3-5 sentences
4. Removing excessive filler words (um, uh)
5. Keeping original meaning intact - DO NOT paraphrase

Output only the cleaned text."""
                        },
                        {
                            "role": "user",
                            "content": f"Clean this transcript:\n\n{raw_transcript[:15000]}"  # Limit to prevent token overflow
                        },
                    ],
                )
                cleaned_transcript = response.choices[0].message.content.strip()
                logger.info(f"Transcript cleaned successfully")
        except Exception as clean_error:
            logger.warning(f"GPT-4o cleaning failed, using raw transcript: {clean_error}")

        # Save transcript to video record in RapidAPI-compatible format
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.transcript_text = cleaned_transcript
            # Save in RapidAPI-compatible format with timing
            json_data = [timed_data]  # Wrap in array to match RapidAPI format
            video.transcript_json = json_data
            db.commit()
            logger.info(f"Transcript with {len(timed_data['transcription'])} timed segments saved to database for video {video_id}")

        # Update status to completed
        status = {
            "status": "completed",
            "message": "Timed transcript generated and cleaned successfully! Ready to use.",
            "progress": 100,
            "stage": "done",
            "transcript_length": len(cleaned_transcript),
            "segments_count": len(timed_data["transcription"]),
        }
        update_transcript_status(db, video_id, status)
        logger.info(f"Transcript generation completed for video ID: {video_id}")

    except Exception as e:
        logger.error(f"Transcript generation failed for video ID {video_id}: {e}")
        status = {
            "status": "failed",
            "message": f"Failed: {str(e)[:100]}",
            "progress": 0,
            "stage": "error",
            "error": str(e),
        }
        update_transcript_status(db, video_id, status)
    finally:
        # Ensure cleanup
        if temp_audio_file and os.path.exists(temp_audio_file):
            try:
                os.remove(temp_audio_file)
            except Exception:
                pass
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
            "ai_penalty_percentage": assignment.ai_penalty_percentage or 50.0,
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


# not used
def extract_pdf_diagrams_background(submission_id: str, pdf_s3_key: str):
    """Extract diagram images from PDF submission using bounding boxes and upload to S3."""
    logger.info(f"Starting PDF diagram extraction for submission {submission_id}")
    db = SessionLocal()
    try:
        submission = (
            db.query(AssignmentSubmission)
            .filter(AssignmentSubmission.id == submission_id)
            .first()
        )
        if not submission or not submission.answers:
            logger.warning(f"Submission {submission_id} not found or has no answers")
            return

        # Download PDF from S3
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            s3_client.download_fileobj(AWS_S3_BUCKET, pdf_s3_key, tmp)
            tmp_pdf_path = tmp.name

        # Process each answer to extract diagrams
        from utils.pdf_answer_processor import PDFAnswerProcessor

        processor = PDFAnswerProcessor()

        answers = submission.answers
        updated = False

        for question_id, answer in answers.items():
            # Check if answer has diagram with bounding_box but no s3_key
            if isinstance(answer, dict) and answer.get("diagram"):
                diagram = answer["diagram"]
                bounding_box = diagram.get("bounding_box")
                page_number = diagram.get("page_number", None)

                if bounding_box and not diagram.get("s3_key"):
                    try:
                        # Extract diagram image from PDF
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=".jpg"
                        ) as img_tmp:
                            img_output_path = img_tmp.name

                        success = processor.extract_diagram_from_pdf(
                            tmp_pdf_path, bounding_box, page_number, img_output_path
                        )

                        if success and os.path.exists(img_output_path):
                            # Upload to S3
                            import uuid

                            file_id = str(uuid.uuid4())
                            s3_key = f"submissions/{submission_id}/diagrams/q{question_id}_{file_id}.jpg"

                            s3_upload_file(
                                img_output_path, s3_key, content_type="image/jpeg"
                            )

                            # Update answer with s3_key
                            answer["diagram"]["s3_key"] = s3_key
                            answer["diagram"]["file_id"] = file_id
                            answer["diagram"][
                                "filename"
                            ] = f"diagram_q{question_id}.jpg"
                            updated = True

                            logger.info(
                                f"Extracted and uploaded diagram for Q{question_id} to {s3_key}"
                            )

                            # Clean up temp image
                            os.unlink(img_output_path)

                    except Exception as e:
                        logger.error(
                            f"Error extracting diagram for Q{question_id}: {str(e)}"
                        )
                        continue

        # Clean up temp PDF
        os.unlink(tmp_pdf_path)

        # Update submission if any diagrams were extracted
        if updated:
            submission.answers = answers
            submission.updated_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(
                f"Updated submission {submission_id} with extracted diagram s3_keys"
            )

    except Exception as e:
        logger.error(
            f"Error in PDF diagram extraction for submission {submission_id}: {str(e)}"
        )
    finally:
        db.close()


# not used
def queue_pdf_diagram_extraction(submission_id: str, pdf_s3_key: str):
    """Queue PDF diagram extraction as a background task."""
    logger.info(f"Queueing PDF diagram extraction for submission {submission_id}")
    thread = threading.Thread(
        target=extract_pdf_diagrams_background,
        args=(submission_id, pdf_s3_key),
        daemon=True,
    )
    thread.start()


# not used
def extract_question_diagrams_background(
    assignment_id: str, file_content_s3_key: str, file_type: str, user_id: str
):
    """Extract diagrams from question paper (PDF or DOCX) and update assignment in database."""
    logger.info(f"Starting question diagram extraction for assignment {assignment_id}")
    db = SessionLocal()
    try:
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            logger.warning(f"Assignment {assignment_id} not found")
            return

        # Download file from S3
        import tempfile

        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".pdf" if file_type == "application/pdf" else ".docx"
        ) as tmp:
            s3_client.download_fileobj(AWS_S3_BUCKET, file_content_s3_key, tmp)
            tmp_file_path = tmp.name

        # Read file content
        with open(tmp_file_path, "rb") as f:
            file_content = f.read()

        # Process diagrams
        from utils.assignment_document_parser import AssignmentDocumentParser

        parser = AssignmentDocumentParser()

        # Create assignment data structure from existing questions
        assignment_data = {
            "title": assignment.title,
            "description": assignment.description,
            "questions": assignment.questions or [],
            "total_points": assignment.total_points,
        }

        # Extract and upload diagrams
        updated_data = parser.extract_and_upload_diagrams(
            assignment_data,
            file_content,
            file_type,
            user_id,
            assignment_id=assignment_id,
        )

        # Update assignment with new diagram s3_keys
        assignment.questions = updated_data.get("questions", [])
        assignment.updated_at = datetime.now(timezone.utc)
        db.commit()

        # Clean up temp file
        os.unlink(tmp_file_path)

        logger.info(f"Successfully extracted diagrams for assignment {assignment_id}")

    except Exception as e:
        logger.error(
            f"Error in question diagram extraction for assignment {assignment_id}: {str(e)}"
        )
    finally:
        db.close()


# not used
def queue_question_diagram_extraction(
    assignment_id: str, file_content_s3_key: str, file_type: str, user_id: str
):
    """Queue question diagram extraction as a background task."""
    logger.info(f"Queueing question diagram extraction for assignment {assignment_id}")
    thread = threading.Thread(
        target=extract_question_diagrams_background,
        args=(assignment_id, file_content_s3_key, file_type, user_id),
        daemon=True,
    )
    thread.start()
