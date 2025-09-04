"""Firebase user management utilities for sharing functionality."""
import os
from typing import List, Dict, Any, Optional

try:
    import firebase_admin
    from firebase_admin import auth as fb_auth
except Exception:  # pragma: no cover
    firebase_admin = None
    fb_auth = None

from utils.firebase_auth import ensure_firebase_initialized


async def search_users_by_email(
    email_query: str, limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Search Firebase users by email pattern.
    Returns list of users with uid, email, and displayName.
    """
    ensure_firebase_initialized()

    if not email_query or len(email_query.strip()) < 2:
        return []

    try:
        # Firebase Admin SDK doesn't have built-in email search
        # We'll use list_users and filter on the backend
        # For production, consider implementing a more efficient search solution

        users = []
        page = fb_auth.list_users()

        while page:
            for user in page.users:
                if user.email and email_query.lower() in user.email.lower():
                    users.append(
                        {
                            "uid": user.uid,
                            "email": user.email,
                            "displayName": user.display_name
                            or user.email.split("@")[0],
                            "photoURL": user.photo_url,
                        }
                    )

                    if len(users) >= limit:
                        return users

            # Get next page
            page = page.get_next_page() if page.has_next_page else None

    except Exception as e:
        print(f"Error searching users: {e}")
        return []

    return users


async def get_user_by_uid(uid: str) -> Optional[Dict[str, Any]]:
    """Get user details by Firebase UID."""
    ensure_firebase_initialized()

    try:
        user = fb_auth.get_user(uid)
        return {
            "uid": user.uid,
            "email": user.email,
            "displayName": user.display_name
            or (user.email.split("@")[0] if user.email else "Unknown"),
            "photoURL": user.photo_url,
        }
    except Exception as e:
        print(f"Error getting user {uid}: {e}")
        return None


async def get_users_by_uids(uids: List[str]) -> List[Dict[str, Any]]:
    """Get multiple users by their Firebase UIDs."""
    ensure_firebase_initialized()

    if not uids:
        return []

    print(f"Getting users for UIDs: {uids}")

    users = []
    try:
        # Firebase Admin SDK supports batch user retrieval
        user_records = fb_auth.get_users([fb_auth.UidIdentifier(uid) for uid in uids])

        for user in user_records.users:
            users.append(
                {
                    "uid": user.uid,
                    "email": user.email,
                    "displayName": user.display_name
                    or (user.email.split("@")[0] if user.email else "Unknown"),
                    "photoURL": user.photo_url,
                }
            )

        # Handle users that weren't found
        for not_found in user_records.not_found:
            print(f"User not found: {not_found.uid}")

        print(f"Successfully retrieved {len(users)} users")

    except Exception as e:
        print(f"Error getting users {uids}: {e}")

    return users


async def validate_user_exists(uid: str) -> bool:
    """Check if a Firebase user exists."""
    user = await get_user_by_uid(uid)
    return user is not None
