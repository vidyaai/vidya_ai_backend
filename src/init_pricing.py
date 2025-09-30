#!/usr/bin/env python3
import os
import sys

# Set the database URL with the correct password (URL-encoded)
os.environ['DATABASE_URL'] = 'postgresql://vidyaai_user:Vidya%40123@localhost:5432/vidyaai_db'

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
