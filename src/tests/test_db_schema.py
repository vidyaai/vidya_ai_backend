#!/usr/bin/env python3
import sys
import os

sys.path.append("src")

from utils.db import engine
from sqlalchemy import text


def test_database_schema():
    try:
        with engine.connect() as conn:
            print("Database connection successful")

            # Check for submitted_by_user_id column
            result = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'assignment_submissions'"
                )
            )
            columns = [row[0] for row in result]
            print("AssignmentSubmission columns:", columns)

            # Check if submitted_by_user_id exists
            if "submitted_by_user_id" in columns:
                print("✅ submitted_by_user_id column exists")
            else:
                print("❌ submitted_by_user_id column missing")

    except Exception as e:
        print(f"Database error: {e}")


if __name__ == "__main__":
    test_database_schema()
