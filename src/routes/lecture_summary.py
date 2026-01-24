from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import and_
import sys
import os
import tempfile
from datetime import datetime
import time

from utils.db import get_db
from controllers.config import logger, s3_client, AWS_S3_BUCKET
from controllers.storage import s3_upload_file, s3_presign_url
from utils.firebase_auth import get_current_user
from models import Video, LectureSummary
from schemas import LectureSummaryRequest, LectureSummaryResponse

# Add the parent directory to path so we can import summarize_lecture as a package
parent_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_path not in sys.path:
    sys.path.insert(0, parent_path)

# Import lecture summarization modules with package namespace
try:
    from summarize_lecture.graph.workflow import run_summarization
    from summarize_lecture.utils.pdf_generator import LectureSummaryPDFGenerator
except ImportError as e:
    logger.error(f"Failed to import summarize_lecture modules: {e}")
    logger.error(f"sys.path: {sys.path}")
    raise

router = APIRouter()


@router.post("/api/lecture-summary/generate", response_model=LectureSummaryResponse)
async def generate_lecture_summary(
    request: LectureSummaryRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Generate a lecture summary for a video.
    Checks cache first unless force_regenerate is True.
    """
    try:
        user_id = current_user["uid"]
        video_id = request.video_id

        logger.info(
            f"Summary generation requested for video {video_id} by user {user_id}"
        )

        # Fetch video and verify access
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Video not found"
            )

        # Verify user has access to this video
        if video.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this video",
            )

        # Check if transcript is available
        if not video.transcript_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Video transcript not available. Please ensure video has been processed.",
            )

        # Check cache unless force_regenerate
        if not request.force_regenerate:
            existing_summary = (
                db.query(LectureSummary)
                .filter(
                    and_(
                        LectureSummary.video_id == video_id,
                        LectureSummary.user_id == user_id,
                    )
                )
                .order_by(LectureSummary.created_at.desc())
                .first()
            )

            if existing_summary:
                logger.info(f"Returning cached summary for video {video_id}")
                return LectureSummaryResponse(
                    summary_id=existing_summary.id,
                    video_id=existing_summary.video_id,
                    created_at=existing_summary.created_at,
                    summary_metadata=existing_summary.summary_metadata,
                )

        # Generate new summary
        logger.info(f"Generating new summary for video {video_id}")
        start_time = time.time()

        # Run summarization workflow
        final_state = run_summarization(video_id, video.transcript_text)

        # Check for errors
        if final_state.get("errors"):
            error_msg = "; ".join(final_state["errors"])
            logger.error(f"Summarization workflow failed: {error_msg}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Summarization failed: {error_msg}",
            )

        # Extract results
        summary_markdown = final_state.get("summary_markdown", "")
        key_topics = final_state.get("key_topics", [])
        research_results = final_state.get("research_results", [])

        if not summary_markdown:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Summary generation failed - no content generated",
            )

        # Generate PDF
        logger.info(f"Generating PDF for video {video_id}")
        pdf_generator = LectureSummaryPDFGenerator()

        temp_pdf_path = None
        try:
            # Create temporary file for PDF
            temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            temp_pdf_path = temp_pdf.name
            temp_pdf.close()

            # Prepare video metadata
            video_metadata = {
                "title": video.title or "Untitled Video",
                "video_id": video_id,
                "key_topics": key_topics,
            }

            # Generate PDF with video metadata
            pdf_path = pdf_generator.generate_pdf_from_content(
                summary_markdown, temp_pdf_path, video_metadata=video_metadata
            )

            # Read PDF content (pdf_path should be the same as temp_pdf_path)
            if not pdf_path or not os.path.exists(pdf_path):
                raise Exception(f"PDF generation failed - file not found at {pdf_path}")

            # Upload to S3
            from uuid import uuid4

            summary_id = str(uuid4())
            s3_key = f"lecture-summaries/{video_id}/{summary_id}.pdf"

            logger.info(f"Uploading PDF to S3: {s3_key}")
            s3_upload_file(pdf_path, s3_key, "application/pdf")

            # Calculate generation time
            generation_time = time.time() - start_time

            # Save to database
            summary_metadata = {
                "key_topics": key_topics,
                "video_title": video.title or "Untitled Video",
                "research_sources_count": len(research_results),
                "generation_time_seconds": round(generation_time, 2),
            }

            lecture_summary = LectureSummary(
                id=summary_id,
                video_id=video_id,
                user_id=user_id,
                summary_markdown=summary_markdown,
                summary_pdf_s3_key=s3_key,
                summary_metadata=summary_metadata,
            )

            db.add(lecture_summary)
            db.commit()
            db.refresh(lecture_summary)

            logger.info(
                f"Summary generated successfully for video {video_id} in {generation_time:.2f}s"
            )

            return LectureSummaryResponse(
                summary_id=lecture_summary.id,
                video_id=lecture_summary.video_id,
                created_at=lecture_summary.created_at,
                summary_metadata=summary_metadata,
            )

        finally:
            # Cleanup
            pdf_generator.cleanup()
            if temp_pdf_path and os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error generating summary: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate summary: {str(e)}",
        )


@router.get("/api/lecture-summary/{summary_id}/download")
async def download_lecture_summary(
    summary_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Download the PDF for a lecture summary.
    Verifies user has access to the associated video.
    """
    try:
        user_id = current_user["uid"]

        # Fetch summary
        summary = db.query(LectureSummary).filter(LectureSummary.id == summary_id).first()
        if not summary:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Summary not found"
            )

        # Verify access (user owns the summary OR has access to the video)
        video = db.query(Video).filter(Video.id == summary.video_id).first()
        if not video:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Associated video not found"
            )

        if video.user_id != user_id and summary.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this summary",
            )

        # Get PDF from S3
        if not summary.summary_pdf_s3_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="PDF file not found"
            )

        logger.info(f"Downloading summary PDF: {summary.summary_pdf_s3_key}")

        try:
            # Download from S3
            response = s3_client.get_object(
                Bucket=AWS_S3_BUCKET, Key=summary.summary_pdf_s3_key
            )
            pdf_content = response["Body"].read()

            # Generate filename
            video_title = video.title or "lecture"
            # Clean filename (remove special characters)
            clean_title = "".join(
                c for c in video_title if c.isalnum() or c in (" ", "_", "-")
            ).replace(" ", "_")
            filename = f"{clean_title}_Summary.pdf"

            logger.info(f"Returning PDF: {filename}")

            return Response(
                content=pdf_content,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "Access-Control-Expose-Headers": "Content-Disposition",
                },
            )

        except Exception as s3_error:
            logger.error(f"Error downloading from S3: {str(s3_error)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve PDF from storage",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error downloading summary: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download summary: {str(e)}",
        )
