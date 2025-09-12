#!/usr/bin/env python3
"""
Migration script to move existing YouTube videos from global S3 structure to user-specific structure.

This script handles the migration from:
- Old: youtube_videos/{video_id}.mp4
- New: youtube_videos/{user_id}/{video_id}.mp4

And similarly for thumbnails and transcripts.
"""

import os
import sys
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from utils.db import SessionLocal
from models import Video
from controllers.config import s3_client, AWS_S3_BUCKET
from controllers.storage import s3_upload_file, s3_presign_url
import tempfile
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_youtube_videos():
    """Migrate existing YouTube videos to user-specific S3 structure."""
    if not s3_client or not AWS_S3_BUCKET:
        logger.error("S3 client or bucket not configured. Cannot perform migration.")
        return

    db = SessionLocal()
    try:
        # Find all YouTube videos that might need migration
        youtube_videos = (
            db.query(Video)
            .filter(Video.source_type == "youtube", Video.user_id.isnot(None))
            .all()
        )

        logger.info(
            f"Found {len(youtube_videos)} YouTube videos to check for migration"
        )

        migrated_count = 0
        skipped_count = 0
        error_count = 0

        for video in youtube_videos:
            try:
                # Check if video has old-style S3 keys
                old_s3_key = f"youtube_videos/{video.id}.mp4"
                old_thumb_key = f"youtube_thumbnails/{video.id}.jpg"
                old_transcript_key = f"youtube_transcripts/{video.id}_formatted.txt"

                # Check if old keys exist in S3
                old_video_exists = False
                old_thumb_exists = False
                old_transcript_exists = False

                try:
                    s3_client.head_object(Bucket=AWS_S3_BUCKET, Key=old_s3_key)
                    old_video_exists = True
                except:
                    pass

                try:
                    s3_client.head_object(Bucket=AWS_S3_BUCKET, Key=old_thumb_key)
                    old_thumb_exists = True
                except:
                    pass

                try:
                    s3_client.head_object(Bucket=AWS_S3_BUCKET, Key=old_transcript_key)
                    old_transcript_exists = True
                except:
                    pass

                # If no old objects exist, skip this video
                if not (old_video_exists or old_thumb_exists or old_transcript_exists):
                    skipped_count += 1
                    continue

                logger.info(f"Migrating video {video.id} for user {video.user_id}")

                # Create new user-specific keys
                new_s3_key = f"youtube_videos/{video.user_id}/{video.id}.mp4"
                new_thumb_key = f"youtube_thumbnails/{video.user_id}/{video.id}.jpg"
                new_transcript_key = (
                    f"youtube_transcripts/{video.user_id}/{video.id}_formatted.txt"
                )

                # Copy video file if it exists
                if old_video_exists:
                    logger.info(f"Copying video from {old_s3_key} to {new_s3_key}")
                    copy_s3_object(old_s3_key, new_s3_key)
                    video.s3_key = new_s3_key

                # Copy thumbnail if it exists
                if old_thumb_exists:
                    logger.info(
                        f"Copying thumbnail from {old_thumb_key} to {new_thumb_key}"
                    )
                    copy_s3_object(old_thumb_key, new_thumb_key)
                    video.thumb_key = new_thumb_key

                # Copy transcript if it exists
                if old_transcript_exists:
                    logger.info(
                        f"Copying transcript from {old_transcript_key} to {new_transcript_key}"
                    )
                    copy_s3_object(old_transcript_key, new_transcript_key)
                    video.transcript_s3_key = new_transcript_key

                # Update the video record
                db.add(video)
                db.commit()

                # Delete old objects after successful copy
                if old_video_exists:
                    s3_client.delete_object(Bucket=AWS_S3_BUCKET, Key=old_s3_key)
                    logger.info(f"Deleted old video: {old_s3_key}")

                if old_thumb_exists:
                    s3_client.delete_object(Bucket=AWS_S3_BUCKET, Key=old_thumb_key)
                    logger.info(f"Deleted old thumbnail: {old_thumb_key}")

                if old_transcript_exists:
                    s3_client.delete_object(
                        Bucket=AWS_S3_BUCKET, Key=old_transcript_key
                    )
                    logger.info(f"Deleted old transcript: {old_transcript_key}")

                migrated_count += 1
                logger.info(f"Successfully migrated video {video.id}")

            except Exception as e:
                logger.error(f"Error migrating video {video.id}: {str(e)}")
                error_count += 1
                db.rollback()

        logger.info(f"Migration completed:")
        logger.info(f"  - Migrated: {migrated_count}")
        logger.info(f"  - Skipped: {skipped_count}")
        logger.info(f"  - Errors: {error_count}")

    except Exception as e:
        logger.error(f"Migration failed: {str(e)}")
        db.rollback()
    finally:
        db.close()


def copy_s3_object(source_key: str, dest_key: str):
    """Copy an S3 object from source to destination."""
    try:
        # Use S3 copy operation
        copy_source = {"Bucket": AWS_S3_BUCKET, "Key": source_key}
        s3_client.copy_object(
            CopySource=copy_source, Bucket=AWS_S3_BUCKET, Key=dest_key
        )
        logger.info(f"Successfully copied {source_key} to {dest_key}")
    except Exception as e:
        logger.error(f"Failed to copy {source_key} to {dest_key}: {str(e)}")
        raise


if __name__ == "__main__":
    logger.info("Starting YouTube video migration to user-specific S3 structure...")
    migrate_youtube_videos()
    logger.info("Migration completed.")
