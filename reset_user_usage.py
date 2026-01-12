#!/usr/bin/env python3
"""
Reset user usage counts to 0 for testing purposes.
Resets videos_analyzed_today and questions_per_video for all users.
"""

import os
import sys
from datetime import date

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from sqlalchemy import text
from utils.db import engine


def reset_user_usage():
    """Reset all user usage counts to 0."""
    today = date.today().isoformat()

    try:
        with engine.connect() as conn:
            # Reset videos analyzed today and questions per video
            result = conn.execute(
                text(
                    """
                    UPDATE user_usage
                    SET videos_analyzed_today = 0,
                        questions_per_video = '{}'
                    WHERE date = :today
                """
                ),
                {"today": today},
            )
            conn.commit()

            rows_affected = result.rowcount

            if rows_affected > 0:
                print(
                    f"✅ Successfully reset usage for {rows_affected} user(s) on {today}"
                )

                # Show current state
                result = conn.execute(
                    text(
                        """
                        SELECT u.email, uu.date, uu.videos_analyzed_today,
                               uu.questions_per_video
                        FROM user_usage uu
                        JOIN users u ON uu.user_id = u.id
                        WHERE uu.date = :today
                        ORDER BY u.email
                    """
                    ),
                    {"today": today},
                )

                print("\n📊 Current usage state:")
                print("-" * 80)
                for row in result:
                    print(f"Email: {row.email}")
                    print(f"  Videos: {row.videos_analyzed_today}")
                    print(f"  Questions: {row.questions_per_video}")
                    print()
            else:
                print(f"ℹ️  No usage records found for {today}")
                print(
                    "This might be normal if no users have used the service today yet."
                )

    except Exception as e:
        print(f"❌ Error resetting usage: {e}")
        sys.exit(1)


if __name__ == "__main__":
    print("🔄 Resetting user usage counts...\n")
    reset_user_usage()
    print("✨ Done!")
