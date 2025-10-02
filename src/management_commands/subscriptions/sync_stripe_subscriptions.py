#!/usr/bin/env python3
"""
Script to sync existing database subscriptions with Stripe subscription data
This will update subscriptions that have null stripe_subscription_id
"""
from dotenv import load_dotenv

# Load environment variables first before importing other modules
load_dotenv()

import os
import sys
from datetime import datetime, timezone
from sqlalchemy.orm import Session

# Add parent directories to path to access src modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db import get_db
from models import User, Subscription
import stripe

# Note: Stripe API key will be initialized in main section


def sync_stripe_subscriptions():
    """Sync database subscriptions with Stripe data"""

    print("🔄 Starting Stripe subscription sync...")

    # Get database session
    db = next(get_db())

    try:
        # Get all subscriptions that don't have stripe_subscription_id
        subscriptions_without_stripe_id = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id.is_(None))
            .all()
        )

        print(
            f"📊 Found {len(subscriptions_without_stripe_id)} subscriptions without Stripe IDs"
        )

        synced_count = 0

        for subscription in subscriptions_without_stripe_id:
            try:
                # Get the user
                user = db.query(User).filter(User.id == subscription.user_id).first()
                if not user or not user.email:
                    print(
                        f"❌ User not found or no email for subscription {subscription.id}"
                    )
                    continue

                print(f"🔍 Syncing subscription for user: {user.email}")

                # Search for Stripe customer by email
                customers = stripe.Customer.list(email=user.email, limit=1)
                if not customers.data:
                    print(f"❌ No Stripe customer found for {user.email}")
                    continue

                stripe_customer = customers.data[0]
                print(f"✅ Found Stripe customer: {stripe_customer.id}")

                # Get the customer's subscriptions
                stripe_subscriptions = stripe.Subscription.list(
                    customer=stripe_customer.id, limit=10
                )

                if not stripe_subscriptions.data:
                    print(
                        f"❌ No Stripe subscriptions found for customer {stripe_customer.id}"
                    )
                    continue

                # Find the most recent active or recently cancelled subscription
                target_subscription = None
                for stripe_sub in stripe_subscriptions.data:
                    if stripe_sub.status in ["active", "canceled", "past_due"]:
                        target_subscription = stripe_sub
                        break

                if not target_subscription:
                    print(f"❌ No suitable Stripe subscription found for {user.email}")
                    continue

                print(
                    f"✅ Found Stripe subscription: {target_subscription.id} (status: {target_subscription.status})"
                )

                # Update the database subscription with Stripe data
                subscription.stripe_subscription_id = target_subscription.id
                subscription.status = target_subscription.status

                # Update period dates
                if (
                    hasattr(target_subscription, "current_period_start")
                    and target_subscription.current_period_start
                ):
                    subscription.current_period_start = datetime.fromtimestamp(
                        target_subscription.current_period_start
                    ).replace(tzinfo=timezone.utc)

                if (
                    hasattr(target_subscription, "current_period_end")
                    and target_subscription.current_period_end
                ):
                    subscription.current_period_end = datetime.fromtimestamp(
                        target_subscription.current_period_end
                    ).replace(tzinfo=timezone.utc)

                subscription.cancel_at_period_end = getattr(
                    target_subscription, "cancel_at_period_end", False
                )
                subscription.updated_at = datetime.now(timezone.utc)

                db.commit()
                synced_count += 1

                print(f"✅ Synced subscription {subscription.id}")
                print(f"   - Stripe ID: {target_subscription.id}")
                print(f"   - Status: {target_subscription.status}")
                print(f"   - Period End: {subscription.current_period_end}")
                print(f"   - Cancel at Period End: {subscription.cancel_at_period_end}")
                print()

            except Exception as e:
                print(f"❌ Error syncing subscription {subscription.id}: {str(e)}")
                db.rollback()
                continue

        print(f"🎉 Sync completed! Updated {synced_count} subscriptions.")

    except Exception as e:
        print(f"❌ Fatal error during sync: {str(e)}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    # Debug: Check if Stripe key is loaded
    stripe_key = os.getenv("STRIPE_SECRET_KEY")
    if stripe_key:
        print(f"🔑 Stripe API key found: sk_...{stripe_key[-10:]}")
        # Set the Stripe API key explicitly
        stripe.api_key = stripe_key
    else:
        print("❌ STRIPE_SECRET_KEY not found in environment variables")
        print("🔍 Available environment variables:")
        for key in sorted(os.environ.keys()):
            if "STRIPE" in key.upper():
                print(f"   - {key}: {os.environ[key][:20]}...")
        sys.exit(1)

    sync_stripe_subscriptions()
