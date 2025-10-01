#!/usr/bin/env python3
"""
Script to view all users and their subscription status
"""

import os
import sys
from datetime import datetime, timezone

# Add the src directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.db import get_db
from models import User, Subscription, PricingPlan

def show_all_users_and_subscriptions():
    """Display all users and their subscription information"""
    
    print("👥 VidyaAI Users and Subscriptions Report")
    print("=" * 80)
    
    # Get database session
    db = next(get_db())
    
    try:
        # Get all users with their subscriptions
        users = db.query(User).all()
        
        print(f"📊 Total Users: {len(users)}")
        print()
        
        for user in users:
            print(f"👤 User: {user.email}")
            print(f"   - ID: {user.id}")
            print(f"   - Firebase UID: {user.firebase_uid}")
            print(f"   - Created: {user.created_at}")
            
            # Get user's subscriptions
            subscriptions = db.query(Subscription).filter(
                Subscription.user_id == user.id
            ).all()
            
            if subscriptions:
                print(f"   - Subscriptions ({len(subscriptions)}):")
                for sub in subscriptions:
                    # Get plan details
                    plan = db.query(PricingPlan).filter(
                        PricingPlan.id == sub.plan_id
                    ).first()
                    
                    plan_name = plan.name if plan else "Unknown Plan"
                    
                    print(f"     🔸 Subscription ID: {sub.id}")
                    print(f"       - Plan: {plan_name}")
                    print(f"       - Status: {sub.status}")
                    print(f"       - Billing Period: {sub.billing_period}")
                    print(f"       - Stripe ID: {sub.stripe_subscription_id or 'None'}")
                    print(f"       - Cancel at Period End: {sub.cancel_at_period_end}")
                    print(f"       - Period Start: {sub.current_period_start or 'None'}")
                    print(f"       - Period End: {sub.current_period_end or 'None'}")
                    print(f"       - Created: {sub.created_at}")
                    print(f"       - Updated: {sub.updated_at}")
                    print()
            else:
                print("   - ❌ No subscriptions found")
            
            print("-" * 80)
        
        # Summary statistics
        print("\n📈 Summary Statistics:")
        total_subscriptions = db.query(Subscription).count()
        active_subscriptions = db.query(Subscription).filter(
            Subscription.status == 'active'
        ).count()
        cancelled_subscriptions = db.query(Subscription).filter(
            Subscription.status == 'cancelled'
        ).count()
        subscriptions_with_stripe = db.query(Subscription).filter(
            Subscription.stripe_subscription_id.isnot(None)
        ).count()
        subscriptions_without_stripe = db.query(Subscription).filter(
            Subscription.stripe_subscription_id.is_(None)
        ).count()
        
        print(f"   - Total Subscriptions: {total_subscriptions}")
        print(f"   - Active Subscriptions: {active_subscriptions}")
        print(f"   - Cancelled Subscriptions: {cancelled_subscriptions}")
        print(f"   - With Stripe ID: {subscriptions_with_stripe}")
        print(f"   - Without Stripe ID: {subscriptions_without_stripe}")
        
    except Exception as e:
        print(f"❌ Error fetching data: {str(e)}")
    finally:
        db.close()

def show_subscription_summary():
    """Show a quick summary of subscriptions"""
    
    print("📋 Quick Subscription Summary")
    print("=" * 50)
    
    db = next(get_db())
    
    try:
        # Query for summary data
        from sqlalchemy import text
        
        query = text("""
            SELECT 
                u.email,
                p.name as plan_name,
                s.status,
                s.billing_period,
                s.stripe_subscription_id,
                s.cancel_at_period_end,
                s.current_period_end
            FROM subscriptions s
            JOIN users u ON s.user_id = u.id
            JOIN pricing_plans p ON s.plan_id = p.id
            ORDER BY s.created_at DESC
        """)
        
        result = db.execute(query)
        rows = result.fetchall()
        
        if rows:
            print(f"{'Email':<30} {'Plan':<15} {'Status':<10} {'Billing':<10} {'Stripe ID':<15} {'Cancel':<8} {'End Date':<12}")
            print("-" * 120)
            
            for row in rows:
                email = row[0][:25] + "..." if len(row[0]) > 25 else row[0]
                plan_name = row[1] or "Unknown"
                status = row[2] or "None"
                billing = row[3] or "None"
                stripe_id = "Yes" if row[4] else "No"
                cancel = "Yes" if row[5] else "No"
                end_date = row[6].strftime("%Y-%m-%d") if row[6] else "None"
                
                print(f"{email:<30} {plan_name:<15} {status:<10} {billing:<10} {stripe_id:<15} {cancel:<8} {end_date:<12}")
        else:
            print("No subscriptions found.")
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="View user and subscription data")
    parser.add_argument("--summary", action="store_true", help="Show quick summary only")
    parser.add_argument("--detailed", action="store_true", help="Show detailed view (default)")
    
    args = parser.parse_args()
    
    if args.summary:
        show_subscription_summary()
    else:
        show_all_users_and_subscriptions()
