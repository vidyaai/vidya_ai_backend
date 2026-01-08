from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from utils.db import get_db
from utils.firebase_auth import get_current_user
from controllers.config import logger
from models import User, Subscription, PricingPlan
from schemas import PaymentRequest
import stripe
import os
from datetime import datetime, timezone

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
stripe_webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

router = APIRouter(prefix="/api/payments", tags=["Payments"])

# Pricing configuration
PRICING_PLANS = {
    "free": {
        "stripe_price_id": None,
        "name": "Free",
        "price": 0,
        "features": {
            "video_uploads_per_month": 10,
            "youtube_chats_per_month": 10,
            "translation_minutes_per_month": 60,
            "ai_model_quality": "basic",
            "priority_support": False,
            "team_collaboration": False,
        },
    },
    "vidya_plus": {
        "stripe_price_id": os.getenv("STRIPE_PLUS_MONTHLY_PRICE_ID"),
        "stripe_annual_price_id": os.getenv("STRIPE_PLUS_ANNUAL_PRICE_ID"),
        "name": "Vidya Plus",
        "price": {"monthly": 9.99, "annual": 100.0},
        "features": {
            "video_uploads_per_month": 100,
            "youtube_chats_per_month": -1,  # -1 means unlimited
            "translation_minutes_per_month": 500,
            "ai_model_quality": "advanced",
            "priority_support": True,
            "team_collaboration": False,
        },
    },
    "vidya_pro": {
        "stripe_price_id": os.getenv("STRIPE_PRO_MONTHLY_PRICE_ID"),
        "stripe_annual_price_id": os.getenv("STRIPE_PRO_ANNUAL_PRICE_ID"),
        "name": "Vidya Pro",
        "price": {"monthly": 14.99, "annual": 150.0},
        "features": {
            "video_uploads_per_month": -1,  # unlimited
            "youtube_chats_per_month": -1,  # unlimited
            "translation_minutes_per_month": -1,  # unlimited
            "ai_model_quality": "premium",
            "priority_support": True,
            "team_collaboration": True,
        },
    },
}


@router.get("/plans")
async def get_pricing_plans():
    """Get available pricing plans"""
    try:
        # Return public pricing information (without Stripe IDs)
        public_plans = {}
        for plan_key, plan_data in PRICING_PLANS.items():
            public_plans[plan_key] = {
                "name": plan_data["name"],
                "price": plan_data["price"],
                "features": plan_data["features"],
            }
        return public_plans
    except Exception as e:
        logger.error(f"Failed to get pricing plans: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get pricing plans")


@router.post("/verify-session")
async def verify_session(
    request: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Verify Stripe checkout session and update subscription (for local testing without webhooks)"""
    try:
        session_id = request.get("session_id")
        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID required")

        logger.info(f"Verifying session {session_id} for user {current_user['uid']}")

        # Retrieve the session from Stripe
        session = stripe.checkout.Session.retrieve(session_id)

        # Check if payment was successful
        if session.payment_status != "paid":
            raise HTTPException(
                status_code=400, detail="Payment not completed"
            )

        # Process the checkout completion
        await handle_checkout_completed(session, db)

        logger.info(f"✅ Session {session_id} verified and subscription updated")

        return {
            "success": True,
            "message": "Subscription activated successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to verify session: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to verify session: {str(e)}"
        )


@router.post("/create-checkout-session")
async def create_checkout_session(
    request: PaymentRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a Stripe Checkout session for subscription"""
    try:
        # Convert plan name to snake_case
        plan_key = request.plan_type.lower().replace(" ", "_")
        billing_period = request.billing_period.lower()

        # Get plan from database
        plan = (
            db.query(PricingPlan)
            .filter(PricingPlan.plan_key == plan_key, PricingPlan.is_active == True)
            .first()
        )

        if not plan:
            raise HTTPException(status_code=400, detail="Invalid plan type")

        if plan_key == "free":
            raise HTTPException(
                status_code=400, detail="Free plan doesn't require payment"
            )

        if billing_period not in ["monthly", "annual"]:
            raise HTTPException(status_code=400, detail="Invalid billing period")

        # Get the correct Stripe price ID based on billing period
        if billing_period == "annual":
            stripe_price_id = plan.stripe_annual_price_id
        else:
            stripe_price_id = plan.stripe_monthly_price_id

        if not stripe_price_id:
            raise HTTPException(
                status_code=400,
                detail=f"Stripe price ID not configured for {billing_period} billing",
            )

        # Create or retrieve user
        user = db.query(User).filter(User.firebase_uid == current_user["uid"]).first()
        if not user:
            # Create new user if doesn't exist
            user = User(
                firebase_uid=current_user["uid"],
                email=current_user.get("email"),
                name=current_user.get("name"),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(
                f"Created new user: {user.id} for firebase_uid: {current_user['uid']}"
            )

        stripe_customer = None
        if user.stripe_customer_id:
            try:
                stripe_customer = stripe.Customer.retrieve(user.stripe_customer_id)
            except stripe.error.InvalidRequestError:
                user.stripe_customer_id = None

        if not stripe_customer:
            stripe_customer = stripe.Customer.create(
                email=current_user.get("email"),
                name=current_user.get("name"),
                metadata={"firebase_uid": current_user["uid"]},
            )
            user.stripe_customer_id = stripe_customer.id
            db.commit()

        # Create checkout session
        checkout_session = stripe.checkout.Session.create(
            customer=stripe_customer.id,
            payment_method_types=["card"],
            line_items=[
                {
                    "price": stripe_price_id,
                    "quantity": 1,
                }
            ],
            mode="subscription",
            success_url=f"{os.getenv('FRONTEND_URL')}/payment-success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{os.getenv('FRONTEND_URL')}/pricing",
            metadata={
                "firebase_uid": current_user["uid"],
                "plan_type": plan_key,
                "billing_period": billing_period,
            },
        )

        return {"checkout_url": checkout_session.url, "session_id": checkout_session.id}

    except stripe.StripeError as e:
        logger.error(f"Stripe error: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Stripe error: {str(e)}")
    except Exception as e:
        logger.error(f"Payment creation failed: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Payment creation failed: {str(e)}"
        )


@router.get("/subscription/status")
async def get_subscription_status(
    db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    """Get current user's subscription status"""
    try:
        user = db.query(User).filter(User.firebase_uid == current_user["uid"]).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        subscription = (
            db.query(Subscription)
            .filter(Subscription.user_id == user.id, Subscription.status == "active")
            .first()
        )

        if not subscription:
            # No active subscription found - return Free plan
            return {
                "subscription": {
                    "plan_name": "Free",
                    "plan_key": "free",
                    "status": "free",
                    "billing_period": None,
                    "cancel_at_period_end": False,
                    "current_period_start": None,
                    "current_period_end": None,
                    "stripe_subscription_id": None,
                }
            }

        # Get plan details
        plan = (
            db.query(PricingPlan).filter(PricingPlan.id == subscription.plan_id).first()
        )

        return {
            "subscription": {
                "id": subscription.id,
                "plan_name": plan.name if plan else "Free",
                "plan_key": plan.plan_key if plan else "free",
                "status": subscription.status,
                "billing_period": subscription.billing_period,
                "cancel_at_period_end": subscription.cancel_at_period_end,
                "current_period_start": subscription.current_period_start.isoformat()
                if subscription.current_period_start
                else None,
                "current_period_end": subscription.current_period_end.isoformat()
                if subscription.current_period_end
                else None,
                "stripe_subscription_id": subscription.stripe_subscription_id,
            }
        }

    except Exception as e:
        logger.error(f"Failed to get subscription status: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get subscription status: {str(e)}"
        )


# Remove the old subscription-status endpoint that has the error
# @router.get("/subscription-status")


@router.post("/subscription/cancel")
async def cancel_subscription(
    db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    """Cancel user's subscription at period end"""
    try:
        user = db.query(User).filter(User.firebase_uid == current_user["uid"]).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        subscription = (
            db.query(Subscription)
            .filter(Subscription.user_id == user.id, Subscription.status == "active")
            .first()
        )

        if not subscription:
            raise HTTPException(status_code=404, detail="No active subscription found")

        # Cancel subscription in Stripe
        stripe_subscription = stripe.Subscription.modify(
            subscription.stripe_subscription_id, cancel_at_period_end=True
        )

        # Update in database
        subscription.cancel_at_period_end = True
        db.commit()

        return {
            "message": "Subscription will be cancelled at the end of current period"
        }

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Stripe error: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to cancel subscription: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to cancel subscription: {str(e)}"
        )


@router.post("/cancel-subscription")
async def cancel_subscription(
    db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    """Cancel user's subscription"""
    try:
        user = db.query(User).filter(User.firebase_uid == current_user["uid"]).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get user's active subscription
        subscription = (
            db.query(Subscription)
            .filter(Subscription.user_id == user.id, Subscription.status == "active")
            .first()
        )

        if not subscription:
            raise HTTPException(status_code=404, detail="No active subscription found")

        # Cancel the subscription in Stripe (if Stripe subscription exists)
        if subscription.stripe_subscription_id:
            stripe_subscription = stripe.Subscription.modify(
                subscription.stripe_subscription_id, cancel_at_period_end=True
            )

            # Update local subscription record with Stripe data
            subscription.cancel_at_period_end = stripe_subscription.cancel_at_period_end
            subscription.updated_at = datetime.now(timezone.utc)
            db.commit()

            logger.info(f"Stripe subscription cancelled for user {user.id}")
            return {
                "message": "Subscription cancelled successfully",
                "cancel_at_period_end": subscription.cancel_at_period_end,
                "current_period_end": subscription.current_period_end.isoformat()
                if subscription.current_period_end
                else None,
            }
        else:
            # Handle case where subscription exists in DB but not in Stripe
            # This can happen for manually created or legacy subscriptions

            # Try to get the subscription details from Stripe using customer email
            try:
                user_email = user.email

                # Search for Stripe customer by email
                customers = stripe.Customer.list(email=user_email, limit=1)
                if customers.data:
                    stripe_customer = customers.data[0]

                    # Get the customer's subscriptions
                    subscriptions = stripe.Subscription.list(
                        customer=stripe_customer.id, limit=1
                    )
                    if subscriptions.data:
                        stripe_subscription = subscriptions.data[0]

                        # Update our subscription with Stripe data
                        subscription.stripe_subscription_id = stripe_subscription.id
                        subscription.current_period_start = datetime.fromtimestamp(
                            stripe_subscription.current_period_start
                        ).replace(tzinfo=timezone.utc)
                        subscription.current_period_end = datetime.fromtimestamp(
                            stripe_subscription.current_period_end
                        ).replace(tzinfo=timezone.utc)

                        # Now cancel it in Stripe
                        cancelled_subscription = stripe.Subscription.modify(
                            stripe_subscription.id, cancel_at_period_end=True
                        )

                        subscription.cancel_at_period_end = (
                            cancelled_subscription.cancel_at_period_end
                        )
                        subscription.updated_at = datetime.now(timezone.utc)
                        db.commit()

                        logger.info(
                            f"Found and cancelled Stripe subscription for user {user.id}"
                        )
                        return {
                            "message": "Subscription cancelled successfully",
                            "cancel_at_period_end": subscription.cancel_at_period_end,
                            "current_period_end": subscription.current_period_end.isoformat(),
                        }

            except Exception as stripe_error:
                logger.warning(
                    f"Could not find Stripe subscription for user {user.id}: {stripe_error}"
                )

            # If no Stripe subscription found, cancel locally
            subscription.status = "cancelled"
            subscription.cancel_at_period_end = True
            subscription.updated_at = datetime.now(timezone.utc)
            db.commit()

            logger.info(
                f"Local subscription cancelled for user {user.id} (no Stripe subscription found)"
            )
            return {
                "message": "Subscription cancelled successfully",
                "cancel_at_period_end": True,
                "current_period_end": subscription.current_period_end.isoformat()
                if subscription.current_period_end
                else None,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel subscription: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to cancel subscription: {str(e)}"
        )


@router.post("/reactivate-subscription")
async def reactivate_subscription(
    db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    """Reactivate a cancelled subscription"""
    try:
        user = db.query(User).filter(User.firebase_uid == current_user["uid"]).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get user's subscription
        subscription = (
            db.query(Subscription)
            .filter(Subscription.user_id == user.id, Subscription.status == "active")
            .first()
        )

        if not subscription or not subscription.cancel_at_period_end:
            raise HTTPException(
                status_code=404, detail="No cancelled subscription found"
            )

        # Reactivate the subscription in Stripe
        if subscription.stripe_subscription_id:
            stripe_subscription = stripe.Subscription.modify(
                subscription.stripe_subscription_id, cancel_at_period_end=False
            )

            # Update local subscription record
            subscription.cancel_at_period_end = False
            subscription.updated_at = datetime.now(timezone.utc)
            db.commit()

            logger.info(f"Subscription reactivated for user {user.id}")
            return {
                "message": "Subscription reactivated successfully",
                "cancel_at_period_end": False,
            }
        else:
            raise HTTPException(
                status_code=400, detail="No Stripe subscription ID found"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reactivate subscription: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to reactivate subscription: {str(e)}"
        )


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhooks"""
    try:
        payload = await request.body()
        sig_header = request.headers.get("stripe-signature")

        # Verify webhook signature
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, stripe_webhook_secret
            )
        except ValueError as e:
            logger.error(f"Invalid payload: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid signature: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid signature")

        logger.info(f"✅ Received Stripe webhook: {event['type']}")

        # Handle different webhook events
        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            await handle_checkout_completed(session, db)

        elif event["type"] == "invoice.payment_succeeded":
            invoice = event["data"]["object"]
            await handle_payment_succeeded(invoice, db)

        elif event["type"] == "invoice.payment_failed":
            invoice = event["data"]["object"]
            await handle_payment_failed(invoice, db)

        elif event["type"] == "customer.subscription.updated":
            subscription = event["data"]["object"]
            await handle_subscription_updated(subscription, db)

        elif event["type"] == "customer.subscription.deleted":
            subscription = event["data"]["object"]
            await handle_subscription_deleted(subscription, db)

        return {"status": "success"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Webhook error: {str(e)}")


async def handle_checkout_completed(session, db: Session):
    """Handle successful checkout completion"""
    try:
        firebase_uid = session["metadata"]["firebase_uid"]
        plan_key = session["metadata"][
            "plan_type"
        ]  # Note: metadata uses 'plan_type' field
        billing_period = session["metadata"]["billing_period"]

        logger.info(
            f"Processing checkout completion for user {firebase_uid}, plan {plan_key}, billing {billing_period}"
        )

        user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
        if not user:
            logger.error(f"User not found for firebase_uid: {firebase_uid}")
            return

        # Get the pricing plan
        pricing_plan = (
            db.query(PricingPlan)
            .filter(PricingPlan.plan_key == plan_key, PricingPlan.is_active == True)
            .first()
        )

        if not pricing_plan:
            logger.error(f"Pricing plan not found for plan_key: {plan_key}")
            return

        # Get the subscription from Stripe
        stripe_subscription = stripe.Subscription.retrieve(session["subscription"])

        # Create or update subscription record
        subscription = (
            db.query(Subscription).filter(Subscription.user_id == user.id).first()
        )

        # Convert timestamps safely
        current_period_start = None
        current_period_end = None
        try:
            if stripe_subscription.current_period_start:
                current_period_start = datetime.fromtimestamp(
                    stripe_subscription.current_period_start
                ).replace(tzinfo=timezone.utc)
            if stripe_subscription.current_period_end:
                current_period_end = datetime.fromtimestamp(
                    stripe_subscription.current_period_end
                ).replace(tzinfo=timezone.utc)
        except Exception as e:
            logger.warning(f"Failed to convert timestamps: {e}")

        if subscription:
            # Update existing subscription
            subscription.stripe_subscription_id = stripe_subscription.id
            subscription.plan_id = pricing_plan.id
            subscription.billing_period = billing_period
            subscription.status = "active"
            subscription.current_period_start = current_period_start
            subscription.current_period_end = current_period_end
            subscription.cancel_at_period_end = False
            subscription.updated_at = datetime.now(timezone.utc)
            logger.info(f"Updated existing subscription for user {user.id}")
        else:
            # Create new subscription
            subscription = Subscription(
                user_id=user.id,
                stripe_subscription_id=stripe_subscription.id,
                plan_id=pricing_plan.id,
                billing_period=billing_period,
                status="active",
                current_period_start=current_period_start,
                current_period_end=current_period_end,
                cancel_at_period_end=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(subscription)
            logger.info(f"Created new subscription for user {user.id}")

        db.commit()
        logger.info(f"Subscription successfully processed for user {firebase_uid}")

    except Exception as e:
        logger.error(f"Failed to handle checkout completion: {str(e)}")
        db.rollback()
        raise
        logger.error(f"Failed to handle checkout completion: {str(e)}")
        db.rollback()


async def handle_payment_succeeded(invoice, db: Session):
    """Handle successful payment"""
    try:
        subscription_id = invoice["subscription"]

        subscription = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id == subscription_id)
            .first()
        )

        if subscription:
            subscription.status = "active"
            db.commit()
            logger.info(f"Payment succeeded for subscription {subscription_id}")

    except Exception as e:
        logger.error(f"Failed to handle payment success: {str(e)}")
        db.rollback()


async def handle_payment_failed(invoice, db: Session):
    """Handle failed payment"""
    try:
        subscription_id = invoice["subscription"]

        subscription = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id == subscription_id)
            .first()
        )

        if subscription:
            subscription.status = "past_due"
            db.commit()
            logger.info(f"Payment failed for subscription {subscription_id}")

    except Exception as e:
        logger.error(f"Failed to handle payment failure: {str(e)}")
        db.rollback()


def get_pricing_plans():
    """Get available pricing plans"""
    try:
        # Return public pricing information (without Stripe IDs)
        public_plans = {}
        for plan_key, plan_data in PRICING_PLANS.items():
            public_plans[plan_key] = {
                "name": plan_data["name"],
                "price": plan_data["price"],
                "features": plan_data["features"],
            }
        return public_plans
    except Exception as e:
        logger.error(f"Failed to get pricing plans: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get pricing plans")


async def handle_subscription_updated(stripe_subscription, db: Session):
    """Handle subscription updates"""
    try:
        subscription = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id == stripe_subscription["id"])
            .first()
        )

        if subscription:
            subscription.status = stripe_subscription["status"]

            # Safely convert timestamps
            try:
                if stripe_subscription.get("current_period_start"):
                    subscription.current_period_start = datetime.fromtimestamp(
                        stripe_subscription["current_period_start"]
                    ).replace(tzinfo=timezone.utc)
                if stripe_subscription.get("current_period_end"):
                    subscription.current_period_end = datetime.fromtimestamp(
                        stripe_subscription["current_period_end"]
                    ).replace(tzinfo=timezone.utc)
            except Exception as e:
                logger.warning(f"Failed to convert timestamps: {e}")

            subscription.cancel_at_period_end = stripe_subscription.get(
                "cancel_at_period_end", False
            )
            subscription.updated_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(f"Subscription updated: {stripe_subscription['id']}")
        else:
            logger.warning(
                f"No local subscription found for Stripe subscription: {stripe_subscription['id']}"
            )

    except Exception as e:
        logger.error(f"Failed to handle subscription update: {str(e)}")
        db.rollback()


async def handle_subscription_deleted(subscription, db: Session):
    """Handle subscription deletion"""
    try:
        # Find subscription by Stripe subscription ID
        local_subscription = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id == subscription["id"])
            .first()
        )

        if local_subscription:
            local_subscription.status = "cancelled"
            local_subscription.updated_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(f"Subscription deleted: {subscription['id']}")

    except Exception as e:
        logger.error(f"Failed to handle subscription deletion: {str(e)}")
        db.rollback()
