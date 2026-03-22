#!/usr/bin/env python
"""
Process videos with Phase 1+2 Combined: Chunks + Summaries.

This script generates both:
- Phase 1: Semantic chunks with embeddings for precise retrieval
- Phase 2: Hierarchical summaries for broad queries

Usage:
    python -m src.management_commands.process_videos [options]

Options:
    --limit N       Only process first N videos (for testing)
    --force         Reprocess even if chunks/summaries already exist
    --video-id ID   Process only a specific video ID
    --chunks-only   Only generate chunks (skip summaries)
    --summaries-only Only generate summaries (skip chunks)

Examples:
    # Process all videos (both chunks and summaries)
    python -m src.management_commands.process_videos

    # Process first 10 videos for testing
    python -m src.management_commands.process_videos --limit 10

    # Reprocess a specific video
    python -m src.management_commands.process_videos --video-id abc123 --force

    # Only generate chunks for all videos
    python -m src.management_commands.process_videos --chunks-only
"""

import sys
import argparse
from datetime import datetime
from src.utils.db import SessionLocal
from src.models import Video, VideoSummary, TranscriptChunk
from src.services.summary_service import SummaryService
from src.services.chunking_embedding_service import TranscriptProcessor
from src.controllers.db_helpers import get_formatting_status, get_transcript_cache
from src.controllers.config import logger


def process_videos(
    limit: int = None,
    force: bool = False,
    video_id: str = None,
    chunks_only: bool = False,
    summaries_only: bool = False,
):
    """
    Process videos with Phase 1+2 combined.

    Args:
        limit: Maximum number of videos to process
        force: Reprocess even if already exists
        video_id: Process only this specific video
        chunks_only: Only generate chunks
        summaries_only: Only generate summaries
    """
    db = SessionLocal()
    summary_service = SummaryService()
    chunk_processor = TranscriptProcessor()

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

        chunks_success = 0
        chunks_skip = 0
        chunks_error = 0
        summaries_success = 0
        summaries_skip = 0
        summaries_error = 0

        for idx, video in enumerate(videos, 1):
            logger.info(f"\n[{idx}/{len(videos)}] Processing video: {video.id}")
            logger.info(f"  Title: {video.title or 'Unknown'}")

            try:
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
                    chunks_skip += 1
                    summaries_skip += 1
                    continue

                # Phase 1: Generate chunks with embeddings
                if not summaries_only:
                    try:
                        existing_chunks = (
                            db.query(TranscriptChunk)
                            .filter(TranscriptChunk.video_id == video.id)
                            .first()
                        )

                        if existing_chunks and not force:
                            logger.info(f"  ✓ Chunks already exist, skipping")
                            chunks_skip += 1
                        else:
                            logger.info(f"  Generating chunks with embeddings...")
                            start_time = datetime.now()

                            num_chunks = chunk_processor.process_transcript(
                                db=db, video_id=video.id, transcript=transcript_to_use
                            )

                            elapsed = (datetime.now() - start_time).total_seconds()
                            logger.info(
                                f"  ✓ Generated {num_chunks} chunks in {elapsed:.2f}s"
                            )
                            chunks_success += 1

                    except Exception as e:
                        logger.error(f"  ✗ Chunk generation error: {e}")
                        chunks_error += 1

                # Phase 2: Generate hierarchical summary
                if not chunks_only:
                    try:
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
                            summaries_skip += 1
                        else:
                            logger.info(f"  Generating hierarchical summary...")
                            start_time = datetime.now()

                            result = summary_service.generate_video_summary(
                                db=db, video_id=video.id, transcript=transcript_to_use
                            )

                            elapsed = (datetime.now() - start_time).total_seconds()
                            logger.info(f"  ✓ Summary generated in {elapsed:.2f}s")
                            logger.info(f"    - Sections: {len(result['sections'])}")
                            logger.info(f"    - Topics: {len(result['key_topics'])}")
                            summaries_success += 1

                    except Exception as e:
                        logger.error(f"  ✗ Summary generation error: {e}")
                        summaries_error += 1

            except Exception as e:
                logger.error(f"  ✗ Error processing video: {e}")
                continue

        # Final Summary
        logger.info(f"\n{'='*60}")
        logger.info(f"Phase 1+2 Processing Complete")
        logger.info(f"{'='*60}")
        logger.info(f"Total videos: {len(videos)}")

        if not summaries_only:
            logger.info(f"\nPhase 1 (Chunks):")
            logger.info(f"  ✓ Successfully generated: {chunks_success}")
            logger.info(f"  ⊘ Skipped (already exist): {chunks_skip}")
            logger.info(f"  ✗ Errors: {chunks_error}")

        if not chunks_only:
            logger.info(f"\nPhase 2 (Summaries):")
            logger.info(f"  ✓ Successfully generated: {summaries_success}")
            logger.info(f"  ⊘ Skipped (already exist): {summaries_skip}")
            logger.info(f"  ✗ Errors: {summaries_error}")

    finally:
        db.close()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Process videos with Phase 1+2 combined (Chunks + Summaries)",
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
        help="Reprocess even if chunks/summaries already exist",
    )

    parser.add_argument(
        "--video-id",
        type=str,
        help="Process only a specific video ID",
    )

    parser.add_argument(
        "--chunks-only",
        action="store_true",
        help="Only generate chunks (skip summaries)",
    )

    parser.add_argument(
        "--summaries-only",
        action="store_true",
        help="Only generate summaries (skip chunks)",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.chunks_only and args.summaries_only:
        logger.error("Cannot use both --chunks-only and --summaries-only")
        sys.exit(1)

    try:
        process_videos(
            limit=args.limit,
            force=args.force,
            video_id=args.video_id,
            chunks_only=args.chunks_only,
            summaries_only=args.summaries_only,
        )
    except KeyboardInterrupt:
        logger.info("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
