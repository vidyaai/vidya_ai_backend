#!/usr/bin/env python3
"""
Fix orphaned video_summaries with NULL video_id.
This script cleans up any video_summaries that have NULL video_id values.
"""

import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from sqlalchemy import text
from utils.db import SessionLocal


def fix_orphaned_summaries():
    """Delete video_summaries with NULL video_id."""
    db = SessionLocal()
    try:
        # Check for orphaned summaries
        result = db.execute(text("""
            SELECT COUNT(*) as count
            FROM video_summaries
            WHERE video_id IS NULL
        """))
        orphaned_count = result.scalar()

        if orphaned_count > 0:
            print(f"Found {orphaned_count} orphaned video_summaries with NULL video_id")

            # Delete them
            db.execute(text("""
                DELETE FROM video_summaries
                WHERE video_id IS NULL
            """))
            db.commit()
            print(f"Successfully deleted {orphaned_count} orphaned video_summaries")
        else:
            print("No orphaned video_summaries found")

        # Also check for summaries pointing to non-existent videos
        result = db.execute(text("""
            SELECT COUNT(*) as count
            FROM video_summaries vs
            LEFT JOIN videos v ON vs.video_id = v.id
            WHERE v.id IS NULL AND vs.video_id IS NOT NULL
        """))
        invalid_count = result.scalar()

        if invalid_count > 0:
            print(f"\nFound {invalid_count} video_summaries pointing to non-existent videos")

            # Delete them
            db.execute(text("""
                DELETE FROM video_summaries
                WHERE id IN (
                    SELECT vs.id
                    FROM video_summaries vs
                    LEFT JOIN videos v ON vs.video_id = v.id
                    WHERE v.id IS NULL AND vs.video_id IS NOT NULL
                )
            """))
            db.commit()
            print(f"Successfully deleted {invalid_count} invalid video_summaries")
        else:
            print("No invalid video_summaries found")

        print("\nDatabase cleanup completed successfully!")

    except Exception as e:
        db.rollback()
        print(f"Error fixing database: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    fix_orphaned_summaries()
