#!/usr/bin/env python3
"""
Test YouTube video limit enforcement for Free tier (3 videos/day)
"""
import sys
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from sqlalchemy.orm import Session
from models import User, Subscription, PricingPlan, UserUsage, Video
from utils.db import engine, SessionLocal
from controllers.subscription_service import (
    check_usage_limits,
    increment_usage,
    get_user_subscription,
)
from datetime import datetime, timezone

# Test videos
TEST_VIDEOS = ["GXR77O_mS3I", "cqrJzG03ENE", "I-R1bc1rlFs", "nB6avolnVOE"]


def test_youtube_limits():
    """Test that Free tier allows 3 videos and blocks the 4th"""
    db = SessionLocal()

    try:
        # Use your existing user
        firebase_uid = "QUNGaGMTvdU8xcD0o98TIPnOiHj2"
        user = db.query(User).filter(User.firebase_uid == firebase_uid).first()

        if not user:
            print("❌ User not found!")
            return

        print(f"✅ Testing with user: {user.email}")
        print(f"   User ID: {user.id}")

        # Get subscription
        subscription = get_user_subscription(db, user.id)
        if not subscription or not subscription.plan:
            print("❌ No subscription found!")
            return

        print(f"   Plan: {subscription.plan.name}")
        print(
            f"   Videos per day limit: {subscription.plan.features.get('videos_per_day', 0)}"
        )
        print()

        # Clear any existing videos for this user (for testing)
        print("🧹 Clearing existing videos...")
        db.query(Video).filter(Video.user_id == firebase_uid).delete()

        # Clear today's usage
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        db.query(UserUsage).filter(
            UserUsage.user_id == user.id, UserUsage.date == today
        ).delete()
        db.commit()
        print("   ✓ Cleared existing data\n")

        # Test each video
        for i, video_id in enumerate(TEST_VIDEOS, 1):
            print(f"📹 Video {i}: https://www.youtube.com/watch?v={video_id}")

            # Check if video already exists (shouldn't for first attempt)
            existing_video = (
                db.query(Video)
                .filter(Video.id == video_id, Video.user_id == firebase_uid)
                .first()
            )

            if not existing_video:
                # Check usage limits
                usage_check = check_usage_limits(db, user.id, "video_per_day")

                if usage_check["allowed"]:
                    print(
                        f"   ✅ ALLOWED ({usage_check['current']}/{usage_check['limit']})"
                    )

                    # Simulate adding the video
                    video = Video(
                        id=video_id,
                        user_id=firebase_uid,
                        title=f"Test Video {i}",
                        source_type="youtube",
                        youtube_id=video_id,
                        youtube_url=f"https://www.youtube.com/watch?v={video_id}",
                        folder_id=None,
                    )
                    db.add(video)

                    # Increment usage
                    increment_usage(db, user.id, "video_per_day", 1)
                    db.commit()
                else:
                    print(f"   ❌ BLOCKED: {usage_check['reason']}")
                    print(
                        f"      Current: {usage_check.get('current')}/{usage_check.get('limit')}"
                    )
            else:
                print(f"   ℹ️  Already exists (won't count towards limit)")

            print()

        # Final status
        print("=" * 60)
        print("📊 Final Usage Summary:")
        usage = (
            db.query(UserUsage)
            .filter(UserUsage.user_id == user.id, UserUsage.date == today)
            .first()
        )

        if usage:
            print(f"   Videos analyzed today: {usage.videos_analyzed_today}")
            print(f"   Limit: {subscription.plan.features.get('videos_per_day', 0)}")

        print("\n✨ Test Result:")
        video_count = db.query(Video).filter(Video.user_id == firebase_uid).count()
        if video_count == 3 and usage and usage.videos_analyzed_today == 3:
            print("   ✅ PASS: Exactly 3 videos were allowed, 4th was blocked")
        else:
            print(f"   ❌ FAIL: Expected 3 videos, got {video_count}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    print("🧪 Testing YouTube Video Limits (Free Tier)\n")
    print("=" * 60)
    test_youtube_limits()
