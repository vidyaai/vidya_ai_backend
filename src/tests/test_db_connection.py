#!/usr/bin/env python3
"""
Test script to verify database connection and table structure
"""
import os
import sys
from sqlalchemy import text
from utils.db import engine, SessionLocal
from models import Video, Base
from controllers.config import logger


def test_database_connection():
    """Test database connection and table structure"""
    try:
        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            logger.info("✅ Database connection successful")

        # Test table structure
        db = SessionLocal()
        try:
            # Check if videos table exists and has required columns
            result = db.execute(
                text(
                    """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'videos'
                ORDER BY ordinal_position
            """
                )
            )

            columns = result.fetchall()
            logger.info(f"✅ Videos table found with {len(columns)} columns:")

            required_columns = {
                "id": "character varying",
                "source_type": "character varying",
                "upload_status": "jsonb",
            }

            found_columns = {col[0]: col[1] for col in columns}

            for col_name, expected_type in required_columns.items():
                if col_name in found_columns:
                    logger.info(f"  ✅ {col_name}: {found_columns[col_name]}")
                else:
                    logger.info(f"  ❌ {col_name}: MISSING")

            # Test creating a video record
            test_video = Video(
                id="test-video-123", source_type="youtube", title="Test Video"
            )
            db.add(test_video)
            db.commit()
            logger.info("✅ Test video record created successfully")

            # Clean up test record
            db.delete(test_video)
            db.commit()
            logger.info("✅ Test video record cleaned up")

        finally:
            db.close()

    except Exception as e:
        logger.info(f"❌ Database test failed: {e}")
        return False

    return True


if __name__ == "__main__":
    success = test_database_connection()
    sys.exit(0 if success else 1)
