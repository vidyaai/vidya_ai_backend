#!/usr/bin/env python3
"""
Auto-create subscription for paid users
This script finds users who made payments but don't have subscriptions and creates them automatically
"""
import os
import sys
sys.path.append('/opt/vidyaai_backend/src')

# Set the database URL
os.environ['DATABASE_URL'] = 'postgresql://vidyaai_user:Vidya%40123@localhost:5432/vidyaai_db'

from datetime import datetime, timezone
from utils.db import get_db
from models import User, Subscription, PricingPlan
import uuid

def create_missing_subscriptions():
    """Create subscriptions for users who paid but don't have subscription records"""
    db = next(get_db())
    
    try:
        print("🔍 Checking for users without subscriptions...")
        
        # Find users who don't have subscriptions
        users_without_subs = db.query(User).filter(
            ~User.id.in_(
                db.query(Subscription.user_id).distinct()
            )
        ).all()
        
        print(f"📊 Found {len(users_without_subs)} users without subscriptions")
        
        if not users_without_subs:
            print("✅ All users already have subscriptions!")
            return
        
        # Get the Vidya Plus plan (assuming they paid for Plus plan)
        plus_plan = db.query(PricingPlan).filter(
            PricingPlan.plan_key == 'vidya_plus',
            PricingPlan.is_active == True
        ).first()
        
        if not plus_plan:
            print("❌ Error: Vidya Plus plan not found in database!")
            return
        
        print(f"📦 Using plan: {plus_plan.name} (ID: {plus_plan.id})")
        
        # Create subscriptions for each user
        created_count = 0
        for user in users_without_subs:
            try:
                print(f"👤 Creating subscription for: {user.email}")
                
                # Create new subscription
                subscription = Subscription(
                    id=str(uuid.uuid4()),
                    user_id=user.id,
                    plan_id=plus_plan.id,
                    billing_period='monthly',
                    status='active',
                    cancel_at_period_end=False,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                
                db.add(subscription)
                created_count += 1
                print(f"✅ Created subscription for {user.email}")
                
            except Exception as e:
                print(f"❌ Failed to create subscription for {user.email}: {e}")
        
        # Commit all changes
        db.commit()
        print(f"🎉 Successfully created {created_count} subscriptions!")
        
        # Verify created subscriptions
        print("\n📋 Current subscriptions:")
        subscriptions = db.query(Subscription).join(User).join(PricingPlan).all()
        for sub in subscriptions:
            user = db.query(User).filter(User.id == sub.user_id).first()
            plan = db.query(PricingPlan).filter(PricingPlan.id == sub.plan_id).first()
            print(f"  • {user.email} -> {plan.name} ({sub.billing_period}) - {sub.status}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    print("🚀 Auto-creating subscriptions for paid users...")
    create_missing_subscriptions()
    print("✨ Done!")
