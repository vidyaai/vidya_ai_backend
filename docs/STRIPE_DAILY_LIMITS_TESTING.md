# Stripe Integration Testing Guide - Daily Usage Limits

## Overview
This guide explains how to test the new daily usage limit system with Stripe integration in development mode.

## New Tier Limits

### Free Tier
- **3 videos per day** - User can analyze up to 3 different videos per day
- **6 questions per video per day** - User can ask up to 6 questions per video per day
- **Cost**: Free

### Plus Tier  
- **10 videos per day** - User can analyze up to 10 different videos per day
- **20 questions per video per day** - User can ask up to 20 questions per video per day
- **Cost**: $9.99/month or $100/year

### Pro Tier
- **20 videos per day** - User can analyze up to 20 different videos per day  
- **Unlimited questions** - No limit on questions per video
- **Cost**: $14.99/month or $150/year

## Database Migration

Before testing, run the database migration to add the new daily tracking columns:

```bash
cd /path/to/vidya_ai_backend
source venv/bin/activate  # or your virtual environment
alembic upgrade head
```

This will:
- Add `date` column for daily tracking (format: "YYYY-MM-DD")
- Add `videos_analyzed_today` column to track videos analyzed per day
- Add `questions_per_video` JSON column to track questions asked per video per day
- Create index on date for faster queries

## Stripe Test Cards

Use these test card numbers in Stripe Checkout:

### Successful Payment
- **Card Number**: `4242 4242 4242 4242`
- **Expiry**: Any future date (e.g., 12/34)
- **CVC**: Any 3 digits (e.g., 123)
- **ZIP**: Any 5 digits (e.g., 12345)

### Other Test Cards
- **Decline**: `4000 0000 0000 0002`
- **Insufficient funds**: `4000 0000 0000 9995`
- **Expired card**: `4000 0000 0000 0069`

## Testing Steps

### 1. Setup Environment Variables

Your `.env` file should be configured with Stripe test keys:

```env
# Stripe Configuration (TEST MODE)
STRIPE_SECRET_KEY=sk_test_your_test_secret_key_here
STRIPE_PUBLISHABLE_KEY=pk_test_your_test_publishable_key_here

# Stripe Price IDs (you'll need to create these in Stripe Dashboard)
STRIPE_PLUS_MONTHLY_PRICE_ID=price_...
STRIPE_PLUS_ANNUAL_PRICE_ID=price_...
STRIPE_PRO_MONTHLY_PRICE_ID=price_...
STRIPE_PRO_ANNUAL_PRICE_ID=price_...

# Stripe Webhook Secret (get this from Stripe CLI)
STRIPE_WEBHOOK_SECRET=whsec_...

FRONTEND_URL=http://localhost:5173  # or your frontend URL
```

**Important**: You need to create products and prices in Stripe Dashboard (Test Mode) and update the price IDs above.

### 2. Start Backend Server

```bash
cd vidya_ai_backend
source venv/bin/activate
python src/main.py
```

### 3. Start Frontend

```bash
cd vidya_ai_frontend
npm run dev
# or
yarn dev
```

### 4. Test Free Tier Limits

1. **Sign up/Login** with a new test account
2. **Analyze 3 videos** (use YouTube URLs)
   - First video: Should work ✅
   - Second video: Should work ✅
   - Third video: Should work ✅
   - Fourth video: Should get error "Daily video analysis limit reached (3/3)" ❌

3. **Ask questions on first video**
   - Question 1-6: Should work ✅
   - Question 7: Should get error "Daily question limit for this video reached (6/6)" ❌

4. **Expected behavior**:
   - Error response with status code `429` (Too Many Requests)
   - Error message shows current usage and limit
   - Error includes upgrade URL to pricing page

### 5. Test Upgrade to Plus Tier

1. **Go to Pricing page** (`/pricing`)
2. **Click "Start Plus Plan"** button
3. **Select billing period** (Monthly or Annual)
4. **Enter Stripe test card**:
   - Card: `4242 4242 4242 4242`
   - Expiry: `12/34`
   - CVC: `123`
   - ZIP: `12345`
5. **Complete checkout**
6. **Verify upgrade**:
   - User should be redirected to success page
   - Profile dropdown should show "Vidya Plus" plan
   - Status should be "active"

### 6. Test Plus Tier Limits

1. **Analyze 10 videos** 
   - Videos 1-10: Should work ✅
   - Video 11: Should get error "Daily video analysis limit reached (10/10)" ❌

2. **Ask questions on any video**
   - Questions 1-20 per video: Should work ✅
   - Question 21 on same video: Should get error "Daily question limit for this video reached (20/20)" ❌

### 7. Test Upgrade to Pro Tier

1. **Go to Pricing page**
2. **Click "Upgrade to Pro"** (or cancel current and subscribe to new)
3. **Complete checkout** with test card
4. **Verify Pro tier**:
   - Profile should show "Vidya Pro"
   - Should allow 20 videos per day
   - Should allow unlimited questions per video

### 8. Test Pro Tier Limits

1. **Analyze 20 videos**
   - Videos 1-20: Should work ✅
   - Video 21: Should get error ❌

2. **Ask unlimited questions**
   - Ask 50+ questions on same video: All should work ✅
   - No limit on questions per video

### 9. Test Daily Reset

Daily limits reset at midnight UTC. To test:

**Option A: Change system date (not recommended for production testing)**

**Option B: Manually update database**
```sql
-- Change date to yesterday to simulate next day
UPDATE user_usage 
SET date = '2026-01-04'  -- previous day
WHERE user_id = 'your-user-id';
```

Then verify:
- Video count resets to 0
- Questions per video reset to empty {}
- User can analyze videos again

### 10. Test Subscription Management

**Cancel Subscription:**
1. Click profile dropdown
2. Click "Cancel Subscription"
3. Confirm cancellation
4. Subscription should show "cancel_at_period_end: true"
5. User keeps access until period end

**Reactivate Subscription:**
1. Click "Reactivate Subscription" (if cancelled)
2. Subscription should be reactivated
3. "cancel_at_period_end" should be false

## API Endpoints for Testing

### Check Usage Limits
```bash
# Get current subscription and usage
curl -X GET http://localhost:8000/api/payments/subscription/status \
  -H "Authorization: Bearer YOUR_FIREBASE_TOKEN"
```

### Analyze Video (triggers video_per_day check)
```bash
curl -X POST http://localhost:8000/api/youtube/info \
  -H "Authorization: Bearer YOUR_FIREBASE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=VIDEO_ID"}'
```

### Ask Question (triggers question_per_video check)
```bash
curl -X POST http://localhost:8000/api/query/video \
  -H "Authorization: Bearer YOUR_FIREBASE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "video_id": "VIDEO_ID",
    "query": "What is this video about?",
    "is_image_query": false
  }'
```

## Expected Error Responses

### Video Limit Reached
```json
{
  "detail": {
    "error": "limit_reached",
    "message": "Daily video analysis limit reached (3/3). Upgrade your plan for more videos per day.",
    "limit": 3,
    "current": 3,
    "current_plan": "Free",
    "upgrade_url": "/pricing"
  }
}
```

### Question Limit Reached
```json
{
  "detail": {
    "error": "limit_reached",
    "message": "Daily question limit for this video reached (6/6). Upgrade to ask more questions per video.",
    "limit": 6,
    "current": 6,
    "current_plan": "Free",
    "upgrade_url": "/pricing"
  }
}
```

## Troubleshooting

### Issue: Limits not resetting daily
**Solution**: Check that `date` field is being set correctly in `get_user_usage()`. Should be format "YYYY-MM-DD".

### Issue: Questions count not tracking per video
**Solution**: Verify `questions_per_video` is JSON column and being updated correctly. Check database:
```sql
SELECT date, videos_analyzed_today, questions_per_video 
FROM user_usage 
WHERE user_id = 'your-user-id' 
ORDER BY date DESC;
```

### Issue: Stripe webhook not working
**Solution**: 
1. Use Stripe CLI to forward webhooks to localhost:
```bash
stripe listen --forward-to localhost:8000/api/payments/webhook
```
2. Copy webhook signing secret to `.env` as `STRIPE_WEBHOOK_SECRET`

### Issue: Payment succeeds but subscription not created
**Solution**: Check webhook events in Stripe dashboard and backend logs. Ensure `checkout.session.completed` event is being processed.

## Database Queries for Debugging

### Check user's current usage
```sql
SELECT 
  u.email,
  uu.date,
  uu.videos_analyzed_today,
  uu.questions_per_video,
  p.name as plan_name,
  p.features
FROM user_usage uu
JOIN users u ON uu.user_id = u.id
JOIN subscriptions s ON s.user_id = u.id AND s.status = 'active'
JOIN pricing_plans p ON s.plan_id = p.id
WHERE u.email = 'test@example.com'
ORDER BY uu.date DESC;
```

### Check all subscriptions
```sql
SELECT 
  u.email,
  p.name as plan_name,
  s.status,
  s.billing_period,
  s.stripe_subscription_id,
  s.current_period_end
FROM subscriptions s
JOIN users u ON s.user_id = u.id
JOIN pricing_plans p ON s.plan_id = p.id
WHERE s.status = 'active'
ORDER BY s.created_at DESC;
```

### Reset usage for testing
```sql
-- Reset daily usage for a user
UPDATE user_usage 
SET videos_analyzed_today = 0, 
    questions_per_video = '{}'
WHERE user_id = 'your-user-id' 
  AND date = CURRENT_DATE;
```

## Notes

- All limits are **per day** (resets at midnight UTC)
- Video count increments when user **first analyzes** a video (not on subsequent questions)
- Question count tracks **per video per day** (each video has separate counter)
- Free tier is automatically assigned to new users
- Subscription status syncs with Stripe via webhooks
- Test in incognito/private mode to avoid auth caching

## Success Criteria

✅ Free tier user blocked after 3 videos and 6 questions per video
✅ Plus tier user blocked after 10 videos and 20 questions per video  
✅ Pro tier user blocked after 20 videos but unlimited questions
✅ Stripe payment flow works with test card 4242...
✅ Subscription upgrades reflect immediately in UI
✅ Limits reset daily at midnight UTC
✅ Error messages are clear and include upgrade CTA
✅ Debug message "No subscription data found" is removed from UI
