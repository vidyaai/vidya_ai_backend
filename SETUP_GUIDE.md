# 🚀 Quick Setup Guide - Stripe Testing

## Step 1: Configure Environment Variables

Your `.env` file should be configured with **Stripe Test Keys**:

```env
# Stripe Configuration (TEST MODE)
STRIPE_SECRET_KEY=sk_test_your_test_secret_key_here
STRIPE_PUBLISHABLE_KEY=pk_test_your_test_publishable_key_here
```

### Important: Update Frontend with Publishable Key

Edit your frontend `.env` file:
```env
VITE_STRIPE_PUBLISHABLE_KEY=pk_test_your_test_publishable_key_here
```

## Step 2: Setup Stripe Webhook (for local testing)

### Option A: Using Stripe CLI (Recommended)

1. **Install Stripe CLI**:
```bash
# macOS
brew install stripe/stripe-cli/stripe

# Or download from https://stripe.com/docs/stripe-cli
```

2. **Login to Stripe**:
```bash
stripe login
```

3. **Forward webhooks to localhost**:
```bash
stripe listen --forward-to localhost:8000/api/payments/webhook
```

4. **Copy the webhook secret** (starts with `whsec_...`) and add to `.env`:
```env
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxx
```

### Option B: Without Stripe CLI (Limited Testing)

If you skip this step, you can still test:
- ✅ Creating checkout sessions
- ✅ Payment flow with test cards
- ❌ Webhook events (subscription updates won't sync automatically)

## Step 3: Create Stripe Products & Prices

### In Stripe Dashboard (Test Mode):

1. Go to https://dashboard.stripe.com/test/products
2. Create products for each tier:

#### Vidya Plus
- **Product Name**: Vidya Plus
- **Monthly Price**: $9.99 → Copy price ID to `.env` as `STRIPE_PLUS_MONTHLY_PRICE_ID`
- **Annual Price**: $100.00 → Copy price ID to `.env` as `STRIPE_PLUS_ANNUAL_PRICE_ID`

#### Vidya Pro
- **Product Name**: Vidya Pro  
- **Monthly Price**: $14.99 → Copy price ID to `.env` as `STRIPE_PRO_MONTHLY_PRICE_ID`
- **Annual Price**: $150.00 → Copy price ID to `.env` as `STRIPE_PRO_ANNUAL_PRICE_ID`

### Update `.env` with Price IDs:
```env
STRIPE_PLUS_MONTHLY_PRICE_ID=price_xxxxxxxxxxxxx
STRIPE_PLUS_ANNUAL_PRICE_ID=price_xxxxxxxxxxxxx
STRIPE_PRO_MONTHLY_PRICE_ID=price_xxxxxxxxxxxxx
STRIPE_PRO_ANNUAL_PRICE_ID=price_xxxxxxxxxxxxx
```

## Step 4: Run Database Migration

```bash
cd vidya_ai_backend
source venv/bin/activate  # or your virtualenv
alembic upgrade head
```

Expected output:
```
INFO  [alembic.runtime.migration] Running upgrade ... -> 6_add_daily_usage, Add daily usage tracking
```

## Step 5: Start Servers

### Terminal 1 - Backend:
```bash
cd vidya_ai_backend
source venv/bin/activate
python src/main.py
```

### Terminal 2 - Frontend:
```bash
cd vidya_ai_frontend
npm run dev
# or: yarn dev
```

### Terminal 3 - Stripe Webhooks (Optional):
```bash
stripe listen --forward-to localhost:8000/api/payments/webhook
```

## Step 6: Test with Test Card

### Test Card Details:
```
Card Number: 4242 4242 4242 4242
Expiry:      12/34
CVC:         123
ZIP:         12345
```

### Test Flow:
1. Open browser: http://localhost:5173
2. Sign up / Login
3. Try to analyze 4 videos (4th should fail - Free tier limit)
4. Go to Pricing → Subscribe to Plus
5. Use test card above
6. Verify upgrade worked
7. Follow checklist in `TESTING_CHECKLIST.md`

## 🎯 Quick Test Commands

### Check if migration ran:
```bash
psql -d vidyaai_db -c "SELECT column_name FROM information_schema.columns WHERE table_name='user_usage' AND column_name IN ('date', 'videos_analyzed_today', 'questions_per_video');"
```

Should return 3 rows.

### Check pricing plans:
```bash
psql -d vidyaai_db -c "SELECT plan_key, name, features->>'videos_per_day' as videos_per_day, features->>'questions_per_video_per_day' as questions FROM pricing_plans;"
```

Should show:
```
 plan_key   |    name     | videos_per_day | questions
------------+-------------+----------------+-----------
 free       | Free        | 3              | 6
 vidya_plus | Vidya Plus  | 10             | 20
 vidya_pro  | Vidya Pro   | 20             | -1
```

### Reset usage for testing:
```sql
UPDATE user_usage 
SET videos_analyzed_today = 0, 
    questions_per_video = '{}'
WHERE date = CURRENT_DATE;
```

## 🐛 Troubleshooting

### Error: "No active subscription found"
**Solution**: User needs to be assigned a plan. Free tier should auto-assign. Check:
```sql
SELECT u.email, s.plan_type, s.status 
FROM subscriptions s 
JOIN users u ON s.user_id = u.id 
WHERE u.email = 'test@example.com';
```

### Error: "Invalid price ID"
**Solution**: Make sure you created the products in Stripe Dashboard (Test Mode) and copied the price IDs to `.env`

### Webhook not receiving events
**Solution**: 
1. Make sure Stripe CLI is running: `stripe listen --forward-to localhost:8000/api/payments/webhook`
2. Copy the webhook secret to `.env`
3. Restart backend server

### Payment succeeds but subscription not created
**Solution**: Check webhook logs in Stripe CLI terminal. Look for `checkout.session.completed` event.

## ✅ Ready to Test!

Everything is configured! Follow the **TESTING_CHECKLIST.md** for complete testing.

### Test Card: `4242 4242 4242 4242`

### Verification URLs:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000/docs
- Stripe Dashboard: https://dashboard.stripe.com/test/payments

Happy testing! 🚀
