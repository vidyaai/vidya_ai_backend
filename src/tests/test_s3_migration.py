#!/usr/bin/env python3
"""
Test script for S3 migration functionality
"""

import os
import sys
import requests
import json
from dotenv import load_dotenv
from controllers.config import logger

# Load environment variables
load_dotenv()

# Base URL for the API
BASE_URL = "http://localhost:8000"  # Change this to your actual API URL


def test_s3_configuration():
    """Test if S3 is properly configured"""
    logger.info("Testing S3 configuration...")

    # Check if required environment variables are set
    required_vars = ["AWS_S3_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    missing_vars = []

    for var in required_vars:
        if not os.environ.get(var):
            missing_vars.append(var)

    if missing_vars:
        logger.info(f"❌ Missing environment variables: {missing_vars}")
        logger.info("Please set these variables in your .env file")
        return False
    else:
        logger.info("✅ S3 environment variables are configured")
        return True


def test_migration_endpoint():
    """Test the migration endpoint"""
    logger.info("\nTesting migration endpoint...")

    try:
        response = requests.post(f"{BASE_URL}/api/admin/migrate-local-videos-to-s3")

        if response.status_code == 200:
            result = response.json()
            logger.info(f"✅ Migration successful: {result.get('message', '')}")
            return True
        else:
            logger.info(f"❌ Migration failed: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        logger.info(f"❌ Migration test failed: {e}")
        return False


def test_cleanup_endpoint():
    """Test the cleanup endpoint"""
    logger.info("\nTesting cleanup endpoint...")

    try:
        response = requests.post(f"{BASE_URL}/api/admin/cleanup-local-videos")

        if response.status_code == 200:
            result = response.json()
            logger.info(f"✅ Cleanup successful: {result.get('message', '')}")
            return True
        else:
            logger.info(f"❌ Cleanup failed: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        logger.info(f"❌ Cleanup test failed: {e}")
        return False


def test_youtube_download_with_s3():
    """Test YouTube download with S3 upload"""
    logger.info("\nTesting YouTube download with S3 upload...")

    # Test with a short YouTube video
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # Rick Roll - short video

    try:
        payload = {"url": test_url, "user_id": "test_user"}

        response = requests.post(f"{BASE_URL}/api/youtube/info", json=payload)

        if response.status_code == 200:
            result = response.json()
            logger.info(f"✅ YouTube info successful: {result.get('title', '')}")
            logger.info(f"   Download status: {result.get('download_status', '')}")
            logger.info(
                f"   Video URL: {'✅ Available' if result.get('video_url') else '❌ Not available'}"
            )
            logger.info(
                f"   Thumbnail URL: {'✅ Available' if result.get('thumbnail_url') else '❌ Not available'}"
            )
            logger.info(
                f"   Formatted transcript URL: {'✅ Available' if result.get('formatted_transcript_url') else '❌ Not available'}"
            )
            return True
        else:
            logger.info(
                f"❌ YouTube info failed: {response.status_code} - {response.text}"
            )
            return False

    except Exception as e:
        logger.info(f"❌ YouTube test failed: {e}")
        return False


def main():
    """Run all tests"""
    logger.info("🧪 Testing S3 Migration Functionality")
    logger.info("=" * 50)

    # Test S3 configuration
    if not test_s3_configuration():
        logger.info(
            "\n❌ S3 not properly configured. Please check your environment variables."
        )
        return

    # Test migration endpoint
    test_migration_endpoint()

    # Test cleanup endpoint
    test_cleanup_endpoint()

    # Test YouTube download with S3
    test_youtube_download_with_s3()

    logger.info("\n" + "=" * 50)
    logger.info("✅ All tests completed!")


if __name__ == "__main__":
    main()
