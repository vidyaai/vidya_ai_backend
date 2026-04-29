#!/usr/bin/env python3
"""
Fix S3 CORS configuration for video playback.

This script configures the S3 bucket to allow cross-origin requests
from the frontend, which is required for HTML5 video playback.
"""

import boto3
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-west-1")
BUCKET_NAME = os.getenv("AWS_S3_BUCKET", "uservideodownloads980")


def configure_s3_cors():
    """Configure CORS for the S3 bucket to allow video playback."""

    print(f"Configuring CORS for bucket: {BUCKET_NAME}")
    print(f"Region: {AWS_REGION}")

    # Create S3 client
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION,
    )

    # CORS configuration
    cors_configuration = {
        "CORSRules": [
            {
                "AllowedHeaders": ["*"],
                "AllowedMethods": ["GET", "HEAD"],
                "AllowedOrigins": [
                    "http://localhost:3000",
                    "http://localhost:3001",
                    "http://54.153.26.252:3000",
                    "http://54.153.26.252:8000",
                    "https://vidyaai.co",
                    "https://www.vidyaai.co",
                    "*",  # Allow all origins for now (can be restricted later)
                ],
                "ExposeHeaders": [
                    "Content-Length",
                    "Content-Type",
                    "ETag",
                    "Accept-Ranges",
                    "Content-Range",
                ],
                "MaxAgeSeconds": 3600,
            }
        ]
    }

    try:
        # Apply CORS configuration
        s3_client.put_bucket_cors(
            Bucket=BUCKET_NAME, CORSConfiguration=cors_configuration
        )
        print("✅ CORS configuration applied successfully!")

        # Verify the configuration
        response = s3_client.get_bucket_cors(Bucket=BUCKET_NAME)
        print("\n📋 Current CORS rules:")
        for idx, rule in enumerate(response["CORSRules"], 1):
            print(f"\nRule {idx}:")
            print(f"  Allowed Methods: {rule.get('AllowedMethods', [])}")
            print(f"  Allowed Origins: {rule.get('AllowedOrigins', [])}")
            print(f"  Allowed Headers: {rule.get('AllowedHeaders', [])}")
            print(f"  Expose Headers: {rule.get('ExposeHeaders', [])}")
            print(f"  Max Age: {rule.get('MaxAgeSeconds', 0)} seconds")

        return True

    except Exception as e:
        print(f"❌ Error configuring CORS: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("S3 CORS Configuration Script")
    print("=" * 60)
    print()

    success = configure_s3_cors()

    print()
    if success:
        print("✅ CORS configuration complete!")
        print("   Videos should now play correctly in the browser.")
        print("   You may need to refresh the page (Ctrl+Shift+R) to clear cache.")
    else:
        print("❌ CORS configuration failed!")
        print("   Please check your AWS credentials and bucket permissions.")
    print("=" * 60)
