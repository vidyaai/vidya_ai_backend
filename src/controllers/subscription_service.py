# controllers/subscription_service.py
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from models import User, Subscription, PricingPlan, UserUsage
from controllers.config import logger
import os


def initialize_pricing_plans(db: Session):
    """Initialize pricing plans in the database"""

    plans_data = [
        {
            "plan_key": "free",
            "name": "Free",
            "monthly_price": 0.0,
            "annual_price": 0.0,
            "stripe_monthly_price_id": None,
            "stripe_annual_price_id": None,
            "features": {
                # Daily limits
                "videos_per_day": 3,
                "questions_per_video_per_day": 6,
                # Legacy monthly limits (kept for backwards compatibility)
                "video_uploads_per_month": 10,
                "youtube_chats_per_month": 10,
                "translation_minutes_per_month": 60,
                "ai_model_quality": "basic",
                "priority_support": False,
                "team_collaboration": False,
            },
        },
        {
            "plan_key": "vidya_plus",
            "name": "Vidya Plus",
            "monthly_price": 9.99,
            "annual_price": 100.0,
            "stripe_monthly_price_id": os.getenv("STRIPE_PLUS_MONTHLY_PRICE_ID"),
            "stripe_annual_price_id": os.getenv("STRIPE_PLUS_ANNUAL_PRICE_ID"),
            "features": {
                # Daily limits
                "videos_per_day": 10,
                "questions_per_video_per_day": 20,
                # Legacy monthly limits (kept for backwards compatibility)
                "video_uploads_per_month": 100,
                "youtube_chats_per_month": -1,  # unlimited
                "translation_minutes_per_month": 500,
                "ai_model_quality": "advanced",
                "priority_support": True,
                "team_collaboration": False,
            },
        },
        {
            "plan_key": "vidya_pro",
            "name": "Vidya Pro",
            "monthly_price": 14.99,
            "annual_price": 150.0,
            "stripe_monthly_price_id": os.getenv("STRIPE_PRO_MONTHLY_PRICE_ID"),
            "stripe_annual_price_id": os.getenv("STRIPE_PRO_ANNUAL_PRICE_ID"),
            "features": {
                # Daily limits
                "videos_per_day": 20,
                "questions_per_video_per_day": -1,  # unlimited
                # Legacy monthly limits (kept for backwards compatibility)
                "video_uploads_per_month": 20,
                "youtube_chats_per_month": -1,  # unlimited
                "translation_minutes_per_month": 120,
                "ai_model_quality": "premium",
                "priority_support": True,
                "team_collaboration": True,
            },
        },
    ]

    for plan_data in plans_data:
        # Check if plan already exists
        existing_plan = (
            db.query(PricingPlan)
            .filter(PricingPlan.plan_key == plan_data["plan_key"])
            .first()
        )

        if not existing_plan:
            plan = PricingPlan(**plan_data)
            db.add(plan)
            logger.info(f"Created pricing plan: {plan_data['name']}")
        else:
            # Update existing plan
            for key, value in plan_data.items():
                if key != "plan_key":  # Don't update the key
                    setattr(existing_plan, key, value)
            logger.info(f"Updated pricing plan: {plan_data['name']}")

    db.commit()


def get_user_subscription(db: Session, user_id: str) -> Subscription:
    """Get user's current active subscription"""
    from sqlalchemy.orm import joinedload

    subscription = (
        db.query(Subscription)
        .options(joinedload(Subscription.plan))
        .filter(Subscription.user_id == user_id, Subscription.status == "active")
        .first()
    )

    if not subscription:
        # Create free subscription for user if none exists
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            free_plan = (
                db.query(PricingPlan).filter(PricingPlan.plan_key == "free").first()
            )

            if not free_plan:
                logger.error("Free plan not found in database!")
                return None

            subscription = Subscription(
                user_id=user_id,
                plan_id=free_plan.id,
                status="active",
            )
            db.add(subscription)
            db.commit()
            db.refresh(subscription)

            # Reload with plan relationship
            subscription = (
                db.query(Subscription)
                .options(joinedload(Subscription.plan))
                .filter(Subscription.id == subscription.id)
                .first()
            )
            logger.info(
                f"Created free subscription for user: {user_id} with plan: {subscription.plan.name if subscription.plan else 'None'}"
            )

    return subscription


def create_subscription(
    db: Session,
    user_id: str,
    plan_type: str,
    billing_period: str,
    stripe_subscription_id: str = None,
) -> Subscription:
    """Create a new subscription for user"""

    # Get the pricing plan
    plan = db.query(PricingPlan).filter(PricingPlan.plan_key == plan_type).first()

    if not plan:
        raise ValueError(f"Pricing plan not found: {plan_type}")

    # Deactivate any existing active subscriptions
    existing_subscriptions = (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id, Subscription.status == "active")
        .all()
    )

    for sub in existing_subscriptions:
        sub.status = "cancelled"

    # Create new subscription
    subscription = Subscription(
        user_id=user_id,
        plan_id=plan.id,
        stripe_subscription_id=stripe_subscription_id,
        plan_type=plan_type,
        billing_period=billing_period,
        status="active",
        current_period_start=datetime.now(timezone.utc),
    )

    db.add(subscription)
    db.commit()

    logger.info(
        f"Created subscription for user {user_id}: {plan_type} ({billing_period})"
    )
    return subscription


def get_user_usage(db: Session, user_id: str, date: str = None) -> UserUsage:
    """Get user's current day usage or create if doesn't exist"""

    if not date:
        now = datetime.now(timezone.utc)
        date = now.strftime("%Y-%m-%d")
        month_year = f"{now.year}-{now.month:02d}"
    else:
        # Extract month_year from date
        date_parts = date.split("-")
        month_year = f"{date_parts[0]}-{date_parts[1]}"

    usage = (
        db.query(UserUsage)
        .filter(UserUsage.user_id == user_id, UserUsage.date == date)
        .first()
    )

    if not usage:
        usage = UserUsage(
            user_id=user_id, date=date, month_year=month_year, questions_per_video={}
        )
        db.add(usage)
        db.commit()

    return usage


def check_usage_limits(
    db: Session, user_id: str, usage_type: str, video_id: str = None
) -> dict:
    """Check if user has exceeded usage limits for their plan

    Args:
        db: Database session
        user_id: User ID
        usage_type: Type of usage to check ('video_per_day', 'question_per_video', 'video_upload', 'youtube_chat', 'translation')
        video_id: Video ID (required for 'question_per_video' check)
    """

    subscription = get_user_subscription(db, user_id)
    if not subscription or not subscription.plan:
        return {"allowed": False, "reason": "No active subscription found"}

    usage = get_user_usage(db, user_id)
    features = subscription.plan.features

    # New daily limits
    if usage_type == "video_per_day":
        limit = features.get("videos_per_day", 0)
        current = usage.videos_analyzed_today

        if limit == -1:  # unlimited
            return {"allowed": True, "limit": "unlimited", "current": current}

        if current >= limit:
            # Calculate time until midnight UTC for reset
            from datetime import datetime, timezone, timedelta

            now_utc = datetime.now(timezone.utc)
            next_midnight = (now_utc + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            time_remaining = next_midnight - now_utc
            hours = int(time_remaining.total_seconds() // 3600)
            minutes = int((time_remaining.total_seconds() % 3600) // 60)
            time_msg = f"{hours}h {minutes}m" if hours > 0 else f"{minutes} minutes"

            return {
                "allowed": False,
                "reason": f"Daily video limit reached ({current}/{limit}). Resets in {time_msg}.",
                "limit": limit,
                "current": current,
                "time_until_reset": time_msg,
            }

        return {"allowed": True, "limit": limit, "current": current}

    elif usage_type == "question_per_video":
        if not video_id:
            return {
                "allowed": False,
                "reason": "Video ID required for question limit check",
            }

        limit = features.get("questions_per_video_per_day", 0)
        questions_per_video = usage.questions_per_video or {}
        current = questions_per_video.get(video_id, 0)

        if limit == -1:  # unlimited
            return {"allowed": True, "limit": "unlimited", "current": current}

        if current >= limit:
            # Calculate time until midnight UTC for reset
            from datetime import datetime, timezone, timedelta

            now_utc = datetime.now(timezone.utc)
            next_midnight = (now_utc + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            time_remaining = next_midnight - now_utc
            hours = int(time_remaining.total_seconds() // 3600)
            minutes = int((time_remaining.total_seconds() % 3600) // 60)
            time_msg = f"{hours}h {minutes}m" if hours > 0 else f"{minutes} minutes"

            return {
                "allowed": False,
                "reason": f"Daily question limit for this video reached ({current}/{limit}). Resets in {time_msg}.",
                "limit": limit,
                "current": current,
                "time_until_reset": time_msg,
            }

        return {"allowed": True, "limit": limit, "current": current}

    # Legacy monthly limits (kept for backwards compatibility)
    elif usage_type == "video_upload":
        limit = features.get("video_uploads_per_month", 0)
        current = usage.video_uploads_count

        if limit == -1:  # unlimited
            return {"allowed": True, "limit": "unlimited", "current": current}

        if current >= limit:
            return {
                "allowed": False,
                "reason": f"Monthly video upload limit reached ({current}/{limit})",
            }

        return {"allowed": True, "limit": limit, "current": current}

    elif usage_type == "youtube_chat":
        limit = features.get("youtube_chats_per_month", 0)
        current = usage.youtube_chats_count

        if limit == -1:  # unlimited
            return {"allowed": True, "limit": "unlimited", "current": current}

        if current >= limit:
            return {
                "allowed": False,
                "reason": f"Monthly YouTube chat limit reached ({current}/{limit})",
            }

        return {"allowed": True, "limit": limit, "current": current}

    elif usage_type == "translation":
        limit = features.get("translation_minutes_per_month", 0)
        current = usage.translation_minutes_used

        if limit == -1:  # unlimited
            return {"allowed": True, "limit": "unlimited", "current": current}

        if current >= limit:
            return {
                "allowed": False,
                "reason": f"Monthly translation limit reached ({current:.1f}/{limit} minutes)",
            }

        return {"allowed": True, "limit": limit, "current": current}

    return {"allowed": False, "reason": "Invalid usage type"}


def increment_usage(
    db: Session,
    user_id: str,
    usage_type: str,
    amount: float = 1.0,
    video_id: str = None,
):
    """Increment user's usage counter

    Args:
        db: Database session
        user_id: User ID
        usage_type: Type of usage ('video_per_day', 'question_per_video', 'video_upload', 'youtube_chat', 'translation')
        amount: Amount to increment (default 1.0)
        video_id: Video ID (required for 'question_per_video')
    """

    usage = get_user_usage(db, user_id)

    # New daily tracking
    if usage_type == "video_per_day":
        usage.videos_analyzed_today += int(amount)
        logger.info(
            f"Incremented videos_per_day for user {user_id}: +{amount} (total: {usage.videos_analyzed_today})"
        )

    elif usage_type == "question_per_video":
        if not video_id:
            logger.error(f"video_id required for question_per_video increment")
            return

        questions_per_video = usage.questions_per_video or {}
        questions_per_video[video_id] = questions_per_video.get(video_id, 0) + int(
            amount
        )
        usage.questions_per_video = questions_per_video
        logger.info(
            f"Incremented questions for user {user_id} on video {video_id}: +{amount} (total: {questions_per_video[video_id]})"
        )

    # Legacy monthly tracking
    elif usage_type == "video_upload":
        usage.video_uploads_count += int(amount)
        logger.info(f"Incremented video_upload for user {user_id}: +{amount}")

    elif usage_type == "youtube_chat":
        usage.youtube_chats_count += int(amount)
        logger.info(f"Incremented youtube_chat for user {user_id}: +{amount}")

    elif usage_type == "translation":
        usage.translation_minutes_used += amount
        logger.info(f"Incremented translation for user {user_id}: +{amount}")

    db.commit()


def get_subscription_features(db: Session, user_id: str) -> dict:
    """Get user's subscription features"""

    subscription = get_user_subscription(db, user_id)
    if not subscription or not subscription.plan:
        # Return free plan features as default
        free_plan = db.query(PricingPlan).filter(PricingPlan.plan_key == "free").first()
        return free_plan.features if free_plan else {}

    return subscription.plan.features
