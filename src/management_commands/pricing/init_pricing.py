#!/usr/bin/env python3
from dotenv import load_dotenv

# Load environment variables first before importing other modules
load_dotenv()

import sys
import os
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from controllers.subscription_service import initialize_pricing_plans
from utils.db import get_db


def main():
    try:
        print("Connecting to database...")
        db = next(get_db())
        print("Database connection successful!")

        print("Initializing pricing plans...")
        initialize_pricing_plans(db)
        print("Pricing plans initialized successfully!")

    except Exception as e:
        print(f"Error initializing pricing plans: {e}")
        import traceback

        traceback.print_exc()
    finally:
        try:
            db.close()
        except:
            pass


if __name__ == "__main__":
    main()
