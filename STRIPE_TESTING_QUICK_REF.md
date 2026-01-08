# Stripe Daily Usage Limits - Quick Reference

## 📊 Tier Limits Summary

| Tier | Videos/Day | Questions/Video/Day | Price |
|------|------------|---------------------|-------|
| Free | 3 | 6 | $0 |
| Plus | 10 | 20 | $9.99/mo or $100/yr |
| Pro | 20 | Unlimited | $14.99/mo or $150/yr |

## 🧪 Quick Test Steps

### 1. Run Migration
```bash
cd vidya_ai_backend
alembic upgrade head
```

### 2. Test Card Numbers
- **Success**: `4242 4242 4242 4242`
- **Expiry**: `12/34`
- **CVC**: `123`

### 3. Test Free Tier
1. Login/Signup
2. Analyze 3 videos ✅
3. Try 4th video ❌ (should fail)
4. Ask 6 questions on video 1 ✅
5. Try 7th question ❌ (should fail)

### 4. Test Upgrade
1. Go to `/pricing`
2. Click "Start Plus Plan"
3. Use test card `4242...`
4. Complete checkout
5. Verify "Vidya Plus" in profile

### 5. Test Plus Tier
1. Analyze 10 videos ✅
2. Try 11th video ❌
3. Ask 20 questions per video ✅
4. Try 21st question ❌

## 🔍 Debug Queries

### Check Current Usage
```sql
SELECT u.email, uu.date, uu.videos_analyzed_today, 
       uu.questions_per_video, p.name as plan
FROM user_usage uu
JOIN users u ON uu.user_id = u.id
JOIN subscriptions s ON s.user_id = u.id
JOIN pricing_plans p ON s.plan_id = p.id
WHERE u.email = 'your-email@example.com';
```

### Reset Usage for Testing
```sql
UPDATE user_usage 
SET videos_analyzed_today = 0, 
    questions_per_video = '{}'
WHERE user_id = 'user-id' 
  AND date = CURRENT_DATE;
```

## 📁 Files Modified

### Backend
- `src/models.py` - Added daily tracking columns
- `src/controllers/subscription_service.py` - Updated limits & tracking
- `src/routes/youtube.py` - Enforce video limits
- `src/routes/query.py` - Enforce question limits
- `alembic/versions/6_add_daily_usage_tracking.py` - Migration

### Frontend
- `src/components/generic/TopBar.jsx` - Removed debug message

## ✅ Success Criteria
- [ ] Free: 3 videos/day, 6 questions/video
- [ ] Plus: 10 videos/day, 20 questions/video
- [ ] Pro: 20 videos/day, unlimited questions
- [ ] Stripe test card works
- [ ] Upgrade flow functional
- [ ] Limits reset daily (midnight UTC)
- [ ] Clear error messages with upgrade CTA
- [ ] Debug message removed from UI

## 📖 Full Documentation
See `docs/STRIPE_DAILY_LIMITS_TESTING.md` for complete testing guide.
