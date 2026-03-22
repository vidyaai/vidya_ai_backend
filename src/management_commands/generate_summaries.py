#!/usr/bin/env python
"""
Generate hierarchical summaries for all existing videos.

Usage:
    python -m src.management_commands.generate_summaries [options]

Options:
    --limit N       Only process first N videos (for testing)
    --force         Regenerate summaries even if they already exist
    --video-id ID   Process only a specific video ID

Examples:
    # Generate summaries for all videos
    python -m src.management_commands.generate_summaries

    # Generate for first 10 videos only (testing)
    python -m src.management_commands.generate_summaries --limit 10

    # Regenerate summary for a specific video
    python -m src.management_commands.generate_summaries --video-id abc123 --force
"""

import sys
import argparse
from datetime import datetime
from src.utils.db import SessionLocal
from src.models import Video, VideoSummary
from src.services.summary_service import SummaryService
from src.controllers.db_helpers import get_formatting_status, get_transcript_cache
from src.controllers.config import logger


def generate_summaries(limit: int = None, force: bool = False, video_id: str = None):
    """
    Generate hierarchical summaries for videos.

    Args:
        limit: Maximum number of videos to process
        force: Regenerate summaries even if they exist
        video_id: Process only this specific video
    """
    db = SessionLocal()
    summary_service = SummaryService()

    try:
        # Get videos to process
        if video_id:
            videos = [db.query(Video).filter(Video.id == video_id).first()]
            if not videos[0]:
                logger.error(f"Video {video_id} not found")
                return
            logger.info(f"Processing specific video: {video_id}")
        else:
            query = db.query(Video)
            if limit:
                query = query.limit(limit)
            videos = query.all()
            logger.info(f"Found {len(videos)} videos to process")

        success_count = 0
        skip_count = 0
        error_count = 0

        for idx, video in enumerate(videos, 1):
            logger.info(f"\n[{idx}/{len(videos)}] Processing video: {video.id}")
            logger.info(f"  Title: {video.title or 'Unknown'}")

            try:
                # Check if summary already exists
                existing_summary = (
                    db.query(VideoSummary)
                    .filter(VideoSummary.video_id == video.id)
                    .first()
                )

                if (
                    existing_summary
                    and existing_summary.processing_status == "completed"
                    and not force
                ):
                    logger.info(f"  ✓ Summary already exists, skipping")
                    skip_count += 1
                    continue

                # Get transcript
                transcript_to_use = None

                # Try formatted transcript first
                formatting_status_info = get_formatting_status(db, video.id)
                if formatting_status_info["status"] == "completed":
                    transcript_to_use = formatting_status_info["formatted_transcript"]
                    logger.info(f"  Using formatted transcript")

                # Fall back to raw transcript
                if not transcript_to_use:
                    transcript_info = get_transcript_cache(db, video.id)
                    if transcript_info and transcript_info.get("transcript_data"):
                        transcript_to_use = transcript_info["transcript_data"]
                        logger.info(f"  Using raw transcript")

                # Check if we have any transcript
                if not transcript_to_use:
                    logger.warning(f"  ⚠ No transcript found, skipping")
                    skip_count += 1
                    continue

                # Generate summary
                logger.info(f"  Generating summary...")
                start_time = datetime.now()

                result = summary_service.generate_video_summary(
                    db=db, video_id=video.id, transcript=transcript_to_use
                )

                elapsed = (datetime.now() - start_time).total_seconds()

                logger.info(f"  ✓ Summary generated in {elapsed:.2f}s")
                logger.info(f"    - Overview: {len(result['overview'])} chars")
                logger.info(f"    - Sections: {len(result['sections'])}")
                logger.info(f"    - Topics: {len(result['key_topics'])}")

                success_count += 1

            except Exception as e:
                logger.error(f"  ✗ Error: {e}")
                error_count += 1
                continue

        # Summary
        logger.info(f"\n{'='*60}")
        logger.info(f"Summary Generation Complete")
        logger.info(f"{'='*60}")
        logger.info(f"Total videos: {len(videos)}")
        logger.info(f"✓ Successfully generated: {success_count}")
        logger.info(f"⊘ Skipped (already exist): {skip_count}")
        logger.info(f"✗ Errors: {error_count}")

    finally:
        db.close()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate hierarchical summaries for videos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--limit",
        type=int,
        help="Only process first N videos (useful for testing)",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate summaries even if they already exist",
    )

    parser.add_argument(
        "--video-id",
        type=str,
        help="Process only a specific video ID",
    )

    args = parser.parse_args()

    try:
        generate_summaries(
            limit=args.limit,
            force=args.force,
            video_id=args.video_id,
        )
    except KeyboardInterrupt:
        logger.info("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
