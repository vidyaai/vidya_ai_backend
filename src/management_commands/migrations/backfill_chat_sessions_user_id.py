#!/usr/bin/env python3
"""
Migration script to backfill missing user_id in chat_sessions.

This script handles the migration of existing chat_sessions that don't have user_id
by setting user_id to the video owner's user_id for all sessions in that video.
"""

import os
import sys
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy.orm import Session
from utils.db import SessionLocal
from models import Video
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def backfill_chat_sessions_user_id():
    """Backfill missing user_id in chat_sessions with video owner's user_id."""
    db = SessionLocal()
    try:
        # Find all videos that have chat_sessions
        videos_with_sessions = (
            db.query(Video).filter(Video.chat_sessions.isnot(None)).all()
        )

        logger.info(f"Found {len(videos_with_sessions)} videos with chat sessions")

        updated_videos = 0
        updated_sessions = 0
        skipped_videos = 0

        for video in videos_with_sessions:
            if not video.chat_sessions or not isinstance(video.chat_sessions, list):
                skipped_videos += 1
                continue

            # Check if any sessions are missing user_id
            needs_update = False
            for session in video.chat_sessions:
                if isinstance(session, dict) and "user_id" not in session:
                    needs_update = True
                    break

            if not needs_update:
                skipped_videos += 1
                continue

            # Backfill missing user_id for all sessions in this video
            session_count = 0
            for session in video.chat_sessions:
                if isinstance(session, dict) and "user_id" not in session:
                    session["user_id"] = video.user_id
                    session_count += 1

            if session_count > 0:
                try:
                    db.add(video)
                    db.commit()
                    updated_videos += 1
                    updated_sessions += session_count
                    logger.info(
                        f"Updated video {video.id}: {session_count} sessions backfilled with user_id {video.user_id}"
                    )
                except Exception as e:
                    logger.error(f"Error updating video {video.id}: {str(e)}")
                    db.rollback()
                    continue

        logger.info(f"Migration completed:")
        logger.info(f"  - Videos updated: {updated_videos}")
        logger.info(f"  - Sessions backfilled: {updated_sessions}")
        logger.info(f"  - Videos skipped (no missing user_id): {skipped_videos}")

    except Exception as e:
        logger.error(f"Migration failed: {str(e)}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    logger.info("Starting chat_sessions user_id backfill migration...")
    backfill_chat_sessions_user_id()
    logger.info("Migration completed.")
