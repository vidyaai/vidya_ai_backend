#!/usr/bin/env python3
"""
Check for videos without thumbnails.
"""

import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from sqlalchemy import text
from utils.db import SessionLocal


def check_thumbnails():
    """Check for videos without thumbnails."""
    db = SessionLocal()
    try:
        # Check uploaded videos without thumb_key
        result = db.execute(text("""
            SELECT COUNT(*) as count
            FROM videos
            WHERE source_type = 'uploaded' AND (thumb_key IS NULL OR thumb_key = '')
        """))
        uploaded_no_thumb = result.scalar()

        print(f"Uploaded videos without thumbnails: {uploaded_no_thumb}")

        # Get some examples
        if uploaded_no_thumb > 0:
            result = db.execute(text("""
                SELECT id, title, s3_key, thumb_key
                FROM videos
                WHERE source_type = 'uploaded' AND (thumb_key IS NULL OR thumb_key = '')
                LIMIT 5
            """))
            rows = result.fetchall()
            print("\nExamples:")
            for row in rows:
                print(f"  - ID: {row[0]}, Title: {row[1]}, S3 Key: {row[2]}, Thumb Key: {row[3]}")

        # Check youtube videos
        result = db.execute(text("""
            SELECT COUNT(*) as count
            FROM videos
            WHERE source_type = 'youtube' AND (youtube_id IS NULL OR youtube_id = '')
        """))
        youtube_no_id = result.scalar()

        print(f"\nYouTube videos without youtube_id: {youtube_no_id}")

        # Total videos by type
        result = db.execute(text("""
            SELECT source_type, COUNT(*) as count
            FROM videos
            GROUP BY source_type
        """))
        rows = result.fetchall()
        print("\nTotal videos by type:")
        for row in rows:
            print(f"  - {row[0]}: {row[1]}")

    except Exception as e:
        print(f"Error checking thumbnails: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    check_thumbnails()
