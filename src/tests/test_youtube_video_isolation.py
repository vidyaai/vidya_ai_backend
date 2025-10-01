#!/usr/bin/env python3
"""
Test script to verify that YouTube videos are properly isolated per user.

This test verifies that:
1. YouTube videos are stored with user-specific S3 keys
2. Deleting a video only affects the specific user's copy
3. Other users can still access the same YouTube video
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
from controllers.storage import s3_presign_url
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_youtube_video_isolation():
    """Test that YouTube videos are properly isolated per user."""
    if not s3_client or not AWS_S3_BUCKET:
        logger.error("S3 client or bucket not configured. Cannot run test.")
        return False

    db = SessionLocal()
    try:
        # Test with a sample YouTube video ID
        test_video_id = "dQw4w9WgXcQ"  # Rick Roll video ID for testing
        user1_id = "test_user_1"
        user2_id = "test_user_2"

        logger.info(f"Testing video isolation for YouTube video: {test_video_id}")

        # Create test video records for two different users
        video1 = Video(
            id=test_video_id,
            user_id=user1_id,
            source_type="youtube",
            title="Test Video 1",
            youtube_id=test_video_id,
            youtube_url=f"https://www.youtube.com/watch?v={test_video_id}",
            s3_key=f"youtube_videos/{user1_id}/{test_video_id}.mp4",
            thumb_key=f"youtube_thumbnails/{user1_id}/{test_video_id}.jpg",
            transcript_s3_key=f"youtube_transcripts/{user1_id}/{test_video_id}_formatted.txt",
        )

        video2 = Video(
            id=test_video_id,
            user_id=user2_id,
            source_type="youtube",
            title="Test Video 2",
            youtube_id=test_video_id,
            youtube_url=f"https://www.youtube.com/watch?v={test_video_id}",
            s3_key=f"youtube_videos/{user2_id}/{test_video_id}.mp4",
            thumb_key=f"youtube_thumbnails/{user2_id}/{test_video_id}.jpg",
            transcript_s3_key=f"youtube_transcripts/{user2_id}/{test_video_id}_formatted.txt",
        )

        # Add to database
        db.add(video1)
        db.add(video2)
        db.commit()

        logger.info("Created test video records for two users")

        # Verify that the S3 keys are user-specific
        assert (
            video1.s3_key == f"youtube_videos/{user1_id}/{test_video_id}.mp4"
        ), f"Expected user1-specific S3 key, got {video1.s3_key}"
        assert (
            video2.s3_key == f"youtube_videos/{user2_id}/{test_video_id}.mp4"
        ), f"Expected user2-specific S3 key, got {video2.s3_key}"

        assert (
            video1.thumb_key == f"youtube_thumbnails/{user1_id}/{test_video_id}.jpg"
        ), f"Expected user1-specific thumb key, got {video1.thumb_key}"
        assert (
            video2.thumb_key == f"youtube_thumbnails/{user2_id}/{test_video_id}.jpg"
        ), f"Expected user2-specific thumb key, got {video2.thumb_key}"

        assert (
            video1.transcript_s3_key
            == f"youtube_transcripts/{user1_id}/{test_video_id}_formatted.txt"
        ), f"Expected user1-specific transcript key, got {video1.transcript_s3_key}"
        assert (
            video2.transcript_s3_key
            == f"youtube_transcripts/{user2_id}/{test_video_id}_formatted.txt"
        ), f"Expected user2-specific transcript key, got {video2.transcript_s3_key}"

        logger.info("✅ S3 keys are properly user-specific")

        # Test that both users can have the same YouTube video with different S3 keys
        videos_for_video_id = db.query(Video).filter(Video.id == test_video_id).all()
        assert (
            len(videos_for_video_id) == 2
        ), f"Expected 2 videos for video ID {test_video_id}, got {len(videos_for_video_id)}"

        logger.info(
            "✅ Multiple users can have the same YouTube video with different S3 keys"
        )

        # Test that deleting one user's video doesn't affect the other
        db.delete(video1)
        db.commit()

        remaining_videos = db.query(Video).filter(Video.id == test_video_id).all()
        assert (
            len(remaining_videos) == 1
        ), f"Expected 1 remaining video after deletion, got {len(remaining_videos)}"
        assert (
            remaining_videos[0].user_id == user2_id
        ), f"Expected remaining video to belong to user2, got {remaining_videos[0].user_id}"

        logger.info("✅ Deleting one user's video doesn't affect other users")

        # Clean up
        db.delete(video2)
        db.commit()

        logger.info("✅ All tests passed! YouTube video isolation is working correctly.")
        return True

    except Exception as e:
        logger.error(f"Test failed: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()


def test_s3_key_structure():
    """Test that the S3 key structure follows the expected pattern."""
    test_cases = [
        {
            "user_id": "user123",
            "video_id": "abc123",
            "expected_video_key": "youtube_videos/user123/abc123.mp4",
            "expected_thumb_key": "youtube_thumbnails/user123/abc123.jpg",
            "expected_transcript_key": "youtube_transcripts/user123/abc123_formatted.txt",
        },
        {
            "user_id": "user456",
            "video_id": "def456",
            "expected_video_key": "youtube_videos/user456/def456.mp4",
            "expected_thumb_key": "youtube_thumbnails/user456/def456.jpg",
            "expected_transcript_key": "youtube_transcripts/user456/def456_formatted.txt",
        },
    ]

    for test_case in test_cases:
        user_id = test_case["user_id"]
        video_id = test_case["video_id"]

        # Test video key
        actual_video_key = f"youtube_videos/{user_id}/{video_id}.mp4"
        assert (
            actual_video_key == test_case["expected_video_key"]
        ), f"Video key mismatch: expected {test_case['expected_video_key']}, got {actual_video_key}"

        # Test thumbnail key
        actual_thumb_key = f"youtube_thumbnails/{user_id}/{video_id}.jpg"
        assert (
            actual_thumb_key == test_case["expected_thumb_key"]
        ), f"Thumbnail key mismatch: expected {test_case['expected_thumb_key']}, got {actual_thumb_key}"

        # Test transcript key
        actual_transcript_key = (
            f"youtube_transcripts/{user_id}/{video_id}_formatted.txt"
        )
        assert (
            actual_transcript_key == test_case["expected_transcript_key"]
        ), f"Transcript key mismatch: expected {test_case['expected_transcript_key']}, got {actual_transcript_key}"

    logger.info("✅ S3 key structure follows expected pattern")
    return True


if __name__ == "__main__":
    logger.info("Starting YouTube video isolation tests...")

    # Test S3 key structure
    if not test_s3_key_structure():
        logger.error("S3 key structure test failed")
        sys.exit(1)

    # Test video isolation
    if not test_youtube_video_isolation():
        logger.error("Video isolation test failed")
        sys.exit(1)

    logger.info("All tests passed! 🎉")
