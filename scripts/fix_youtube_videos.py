#!/usr/bin/env python3
"""
Fix YouTube videos without youtube_id.
"""

import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy import text
from utils.db import SessionLocal


def fix_youtube_videos():
    """Fix YouTube videos without youtube_id."""
    db = SessionLocal()
    try:
        # Get YouTube videos without youtube_id
        result = db.execute(
            text(
                """
            SELECT id, title, youtube_url
            FROM videos
            WHERE source_type = 'youtube' AND (youtube_id IS NULL OR youtube_id = '')
        """
            )
        )
        rows = result.fetchall()

        if not rows:
            print("No YouTube videos without youtube_id found")
            return

        print(f"Found {len(rows)} YouTube videos without youtube_id:")
        for row in rows:
            video_id, title, youtube_url = row
            print(f"\n  - ID: {video_id}")
            print(f"    Title: {title}")
            print(f"    YouTube URL: {youtube_url}")

            # Try to extract youtube_id from the video ID or URL
            if youtube_url and "youtube.com" in youtube_url:
                # Extract youtube_id from URL
                import re

                match = re.search(r"(?:v=|/)([a-zA-Z0-9_-]{11})", youtube_url)
                if match:
                    youtube_id = match.group(1)
                    print(f"    Extracted youtube_id: {youtube_id}")

                    # Update the record
                    db.execute(
                        text(
                            """
                        UPDATE videos
                        SET youtube_id = :youtube_id
                        WHERE id = :video_id
                    """
                        ),
                        {"youtube_id": youtube_id, "video_id": video_id},
                    )
                    db.commit()
                    print(f"    ✓ Updated youtube_id")
                else:
                    print(f"    ✗ Could not extract youtube_id from URL")
            elif video_id and len(video_id) == 11:
                # The video ID itself might be the youtube_id
                print(f"    Video ID looks like a youtube_id, updating...")
                db.execute(
                    text(
                        """
                    UPDATE videos
                    SET youtube_id = :youtube_id
                    WHERE id = :video_id
                """
                    ),
                    {"youtube_id": video_id, "video_id": video_id},
                )
                db.commit()
                print(f"    ✓ Updated youtube_id")
            else:
                print(f"    ✗ Could not fix this video")

        print("\n✓ YouTube video fix completed")

    except Exception as e:
        db.rollback()
        print(f"Error fixing YouTube videos: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    fix_youtube_videos()
