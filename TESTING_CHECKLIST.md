# 🧪 Stripe Testing Checklist

Use this checklist to verify the implementation is working correctly.

## Pre-Testing Setup

- [ ] `.env` file configured with test keys (already done ✅)
- [ ] Stripe products and price IDs added to `.env`
- [ ] Database migration run: `alembic upgrade head`
- [ ] Backend server running: `python src/main.py`
- [ ] Frontend server running: `npm run dev`
- [ ] Stripe CLI running (optional): `stripe listen --forward-to localhost:8000/api/payments/webhook`
- [ ] Test card ready: `4242 4242 4242 4242`

### ⚠️ Important First Step
Before testing, create products in Stripe Dashboard:
1. Go to https://dashboard.stripe.com/test/products
2. Create "Vidya Plus" ($9.99/month, $100/year)
3. Create "Vidya Pro" ($14.99/month, $150/year)
4. Copy price IDs to `.env` file

See `SETUP_GUIDE.md` for detailed instructions.

## Test 1: Free Tier Video Limits

- [ ] Login with new test account
- [ ] Paste YouTube URL #1 → Success ✅
- [ ] Paste YouTube URL #2 → Success ✅
- [ ] Paste YouTube URL #3 → Success ✅
- [ ] Paste YouTube URL #4 → **Error: "Daily video analysis limit reached (3/3)"** ❌
- [ ] Error includes upgrade message with pricing link

## Test 2: Free Tier Question Limits

- [ ] Open video #1 in chat
- [ ] Ask question 1 → Success ✅
- [ ] Ask question 2 → Success ✅
- [ ] Ask question 3 → Success ✅
- [ ] Ask question 4 → Success ✅
- [ ] Ask question 5 → Success ✅
- [ ] Ask question 6 → Success ✅
- [ ] Ask question 7 → **Error: "Daily question limit for this video reached (6/6)"** ❌
- [ ] Can still ask questions on video #2 (separate counter)

## Test 3: Upgrade to Plus Tier

- [ ] Click profile dropdown
- [ ] Current plan shows "Free"
- [ ] Click "Change Subscription"
- [ ] Redirects to pricing page
- [ ] Click "Start Plus Plan"
- [ ] Choose billing period (Monthly or Annual)
- [ ] Redirects to Stripe Checkout
- [ ] Enter test card: `4242 4242 4242 4242`
- [ ] Enter expiry: `12/34`
- [ ] Enter CVC: `123`
- [ ] Enter ZIP: `12345`
- [ ] Click "Subscribe"
- [ ] Redirects to success page
- [ ] Profile dropdown now shows "Vidya Plus"
- [ ] Status shows "active"
- [ ] No debug message visible ✅

## Test 4: Plus Tier Video Limits

- [ ] Analyze videos 4-10 (6 more videos) → All succeed ✅
- [ ] Try to analyze video #11 → **Error: limit reached (10/10)** ❌

## Test 5: Plus Tier Question Limits

- [ ] Open any video
- [ ] Ask questions 1-20 → All succeed ✅
- [ ] Ask question 21 → **Error: limit reached (20/20)** ❌

## Test 6: Upgrade to Pro Tier

- [ ] Go to pricing page
- [ ] Click "Upgrade to Pro" or cancel Plus and buy Pro
- [ ] Complete checkout with test card
- [ ] Profile shows "Vidya Pro"
- [ ] Status is "active"

## Test 7: Pro Tier Limits

- [ ] Analyze videos 11-20 (10 more videos) → All succeed ✅
- [ ] Try to analyze video #21 → **Error: limit reached (20/20)** ❌
- [ ] Open any video
- [ ] Ask 25+ questions → All succeed ✅ (unlimited)
- [ ] Verify no question limit on Pro

## Test 8: Subscription Management

- [ ] Click profile → "Cancel Subscription"
- [ ] Confirm cancellation
- [ ] Status shows "cancel_at_period_end: true"
- [ ] Can still use service (access until period end)
- [ ] Click "Reactivate Subscription"
- [ ] Status shows "cancel_at_period_end: false"

## Test 9: Error Messages Quality

- [ ] All error responses include:
  - [ ] Clear message explaining the limit
  - [ ] Current usage count (e.g., "3/3")
  - [ ] Current plan name
  - [ ] Upgrade suggestion
  - [ ] HTTP status 429 (Too Many Requests)

## Test 10: UI Cleanup

- [ ] Profile dropdown does NOT show "Debug: No subscription data found" ✅
- [ ] Subscription info displays cleanly
- [ ] All buttons work correctly

## Bonus Tests

### Test Daily Reset
- [ ] Run SQL to reset usage:
```sql
UPDATE user_usage 
SET videos_analyzed_today = 0, 
    questions_per_video = '{}'
WHERE date = CURRENT_DATE;
```
- [ ] Verify can analyze videos again
- [ ] Verify can ask questions again

### Test Database
- [ ] Check user_usage table has new columns:
  - [ ] `date` column exists
  - [ ] `videos_analyzed_today` column exists
  - [ ] `questions_per_video` column exists
- [ ] Run debug query:
```sql
SELECT u.email, uu.date, uu.videos_analyzed_today, 
       uu.questions_per_video, p.name as plan
FROM user_usage uu
JOIN users u ON uu.user_id = u.id
JOIN subscriptions s ON s.user_id = u.id AND s.status = 'active'
JOIN pricing_plans p ON s.plan_id = p.id;
```

## ✅ Success Criteria

All checkboxes should be ticked for complete verification:

- [ ] Free tier: 3 videos/day, 6 questions/video enforced
- [ ] Plus tier: 10 videos/day, 20 questions/video enforced
- [ ] Pro tier: 20 videos/day, unlimited questions enforced
- [ ] Stripe test card `4242...` works for payment
- [ ] Subscription upgrades reflect immediately
- [ ] Error messages are clear and helpful
- [ ] UI is clean (no debug messages)
- [ ] Cancellation and reactivation work

## 🐛 If Tests Fail

1. Check backend logs for errors
2. Verify database migration ran successfully
3. Check Stripe webhook configuration
4. Verify environment variables are set
5. See `docs/STRIPE_DAILY_LIMITS_TESTING.md` for troubleshooting

---

**Test completed on**: _______________  
**Tested by**: _______________  
**Result**: ⭐ Pass / ❌ Fail  
**Notes**: _______________________________________________
