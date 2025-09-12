#!/usr/bin/env python3
"""
Run the chat_sessions user_id backfill migration.
"""

import sys
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from migrations.backfill_chat_sessions_user_id import backfill_chat_sessions_user_id

if __name__ == "__main__":
    print("Running chat_sessions user_id backfill migration...")
    backfill_chat_sessions_user_id()
    print("Migration completed.")
