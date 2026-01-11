# Canvas LTI Integration - Quick Start Guide

## For Developers: Local Testing

### 1. Quick Setup (5 minutes)

```bash
# Navigate to backend
cd vidya_ai_backend

# Run setup script
./setup_canvas_lti.sh

# Start backend
python src/main.py

# In another terminal, start frontend
cd vidya_ai_frontend
yarn dev

# In another terminal, start ngrok
ngrok http 8000
```

### 2. Configure Canvas (10 minutes)

1. **Get ngrok URL** (e.g., `https://abc123.ngrok.io`)
2. **Update `lti_config.development.json`** with your Canvas instance
3. **Go to Canvas** → Admin → Developer Keys → + LTI Key
4. **Fill in form:**
   - Redirect URIs: `https://abc123.ngrok.io/lti/launch`
   - Target Link URI: `https://abc123.ngrok.io/lti/launch`
   - OIDC URL: `https://abc123.ngrok.io/lti/login`
   - JWK URL: `https://abc123.ngrok.io/lti/jwks`
5. **Save and copy Client ID and Deployment ID**
6. **Update `lti_config.development.json`** with these values
7. **Restart backend**

### 3. Install in Course (2 minutes)

1. Go to Canvas Course → Settings → Apps → + App
2. Configuration Type: "By Client ID"
3. Enter Client ID
4. Submit

### 4. Test (5 minutes)

1. Canvas Course → Assignments → + Assignment
2. Submission Type: External Tool → Find
3. Select "Create using Vidya AI"
4. Upload lecture PDFs to Canvas Files first
5. Select files → Configure → Generate → Add to Canvas

**Total time: ~20 minutes**

---

## For Production Deployment

### Prerequisites Checklist

- [ ] Domain: `api.vidyaai.co` points to production server
- [ ] SSL: Valid HTTPS certificate installed
- [ ] Database: Production PostgreSQL ready
- [ ] S3: Production bucket configured
- [ ] Environment: All `.env` variables set

### Step 1: Update Production Config

**File: `lti_config.production.json`**
```json
{
  "https://canvas.instructure.com": {
    "client_id": "YOUR_PRODUCTION_CLIENT_ID",
    "auth_login_url": "https://canvas.instructure.com/api/lti/authorize_redirect",
    "auth_token_url": "https://canvas.instructure.com/login/oauth2/token",
    "key_set_url": "https://canvas.instructure.com/api/lti/security/jwks",
    "deployment_ids": ["YOUR_PRODUCTION_DEPLOYMENT_ID"],
    "private_key_file": "private.key",
    "public_key_file": "public.key"
  }
}
```

**File: `.env`**
```bash
ENVIRONMENT=production
API_BASE_URL=https://api.vidyaai.co
FRONTEND_URL=https://vidyaai.co
DATABASE_URL=postgresql://prod-db/vidyaai
# ... other production variables
```

### Step 2: Deploy Backend

```bash
# SSH to production server
ssh user@api.vidyaai.co

# Navigate to backend
cd /var/www/vidya_ai_backend

# Pull latest code
git pull origin main

# Install dependencies
source venv/bin/activate
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Restart service
sudo systemctl restart vidyaai-backend

# Verify it's running
curl https://api.vidyaai.co/
curl https://api.vidyaai.co/lti/config.xml
curl https://api.vidyaai.co/lti/jwks
```

### Step 3: Deploy Frontend

```bash
# SSH to frontend server (or same server)
ssh user@vidyaai.co

# Navigate to frontend
cd /var/www/vidya_ai_frontend

# Pull latest code
git pull origin main

# Install dependencies and build
yarn install
yarn build

# Restart service
pm2 restart vidyaai-frontend
```

### Step 4: Configure Production Canvas

**For Each Institution:**

1. Contact institution IT administrator
2. Provide configuration URL: `https://api.vidyaai.co/lti/config.xml`
3. They create Developer Key in their Canvas
4. They provide you with:
   - Client ID
   - Deployment ID
   - Canvas instance URL (e.g., `stanford.instructure.com`)
5. Add to `lti_config.production.json`:

```json
{
  "https://stanford.instructure.com": {
    "client_id": "STANFORD_CLIENT_ID",
    "auth_login_url": "https://stanford.instructure.com/api/lti/authorize_redirect",
    "auth_token_url": "https://stanford.instructure.com/login/oauth2/token",
    "key_set_url": "https://stanford.instructure.com/api/lti/security/jwks",
    "deployment_ids": ["STANFORD_DEPLOYMENT_ID"],
    "private_key_file": "private.key",
    "public_key_file": "public.key"
  }
}
```

6. Restart backend after each institution is added

### Step 5: Test Production

1. Have institution admin test in one course
2. Verify LTI launch works
3. Verify file loading from Canvas
4. Generate test assignment
5. Verify Deep Link back to Canvas
6. Check Canvas gradebook integration

### Step 6: Monitor

```bash
# Check backend logs
tail -f /var/www/vidya_ai_backend/logs/server.log

# Check for LTI-specific logs
grep "LTI" /var/www/vidya_ai_backend/logs/server.log

# Monitor Canvas API calls
grep "Canvas API" /var/www/vidya_ai_backend/logs/server.log
```

---

## For Institutions: Installation Guide

### Institution IT Admin Steps

**1. Create Developer Key**

In Canvas, navigate to:
- Admin → Developer Keys → + Developer Key → + LTI Key

Fill in:
```
Key Name: Vidya AI Assignment Generator
Owner Email: your-admin@institution.edu
Redirect URIs: https://api.vidyaai.co/lti/launch
Target Link URI: https://api.vidyaai.co/lti/launch
OpenID Connect Initiation URL: https://api.vidyaai.co/lti/login
JWK Method: Public JWK URL
Public JWK URL: https://api.vidyaai.co/lti/jwks

LTI Advantage Services:
  ✅ Can create and view assignment data in gradebook
  ✅ Deep Linking enabled

Placements:
  ✅ Assignment Selection
  ✅ Course Navigation (optional)

Privacy Level: Public
```

**2. Share Credentials**

- Client ID (e.g., `10000000000001`)
- Deployment ID (e.g., `1:abc123def456`)
- Canvas Instance URL (e.g., `institution.instructure.com`)

Send these securely to Vidya AI support team.

**3. Enable Key**

Toggle the Developer Key to "ON" (green).

**4. Pilot Testing**

Select 1-2 courses for initial testing:
- Instructors create test assignments
- Verify integration works
- Collect feedback

**5. Full Rollout**

After successful pilot:
- Enable for all courses
- Provide instructor training
- Monitor usage

---

## Common Scenarios

### Scenario 1: Single Institution (University)

```
Canvas: stanford.instructure.com
→ Configure Developer Key
→ Add to lti_config.production.json
→ Test with pilot course
→ Roll out campus-wide
```

### Scenario 2: Multiple Institutions

```
Stanford: stanford.instructure.com
MIT: mit.instructure.com
Harvard: harvard.instructure.com

→ Each gets own entry in lti_config.production.json
→ Each has separate Client ID and Deployment ID
→ Backend handles all dynamically
```

### Scenario 3: Canvas Cloud (canvas.instructure.com)

```
Use default Canvas Cloud configuration
→ Most common for smaller institutions
→ Configuration same as any institution
→ Client ID and Deployment ID from Canvas Cloud admin
```

---

## Troubleshooting Quick Reference

| Issue | Check | Fix |
|-------|-------|-----|
| LTI launch fails | Client ID correct? | Update lti_config |
| Can't see files | Canvas token valid? | Regenerate token |
| Deep Link fails | Private key readable? | Check file permissions |
| 404 on endpoints | Backend running? | Restart backend |
| CORS error | Canvas domain allowed? | Update CORS in main.py |

---

## Support Contacts

**For Developers:**
- Backend issues: Check `CANVAS_LTI_IMPLEMENTATION.md`
- Testing help: See `CANVAS_LTI_TESTING_GUIDE.md`
- GitHub Issues: [vidyaai/vidya_ai_backend/issues]

**For Institutions:**
- Email: support@vidyaai.co
- Documentation: https://docs.vidyaai.co/canvas
- Setup assistance: Schedule call with our team

---

## Resources

- **Canvas LTI Docs:** https://canvas.instructure.com/doc/api/file.lti_dev_key_config.html
- **Canvas Free Trial:** https://www.instructure.com/canvas/try-canvas
- **LTI 1.3 Spec:** https://www.imsglobal.org/spec/lti/v1p3/
- **Vidya AI Docs:** https://docs.vidyaai.co

---

## FAQ

**Q: Do we need a separate Developer Key for each course?**
A: No, one Developer Key per Canvas instance works for all courses.

**Q: Can multiple instructors use this simultaneously?**
A: Yes, each LTI launch creates a separate session.

**Q: What types of files are supported?**
A: Currently PDFs. Future: DOCX, PPTX, TXT.

**Q: Does this work with Canvas Free for Teachers?**
A: Yes! Perfect for testing before production deployment.

**Q: How do we handle Canvas access tokens?**
A: Currently manual (for testing). Production will use OAuth flow.

**Q: Can students see the generated assignments?**
A: Yes, assignments appear in Canvas like any other assignment.

**Q: Does this send grades back to Canvas?**
A: Not yet. Grade passback (AGS) is planned for future release.

**Q: Is this listed in Canvas App Center?**
A: Not yet. Submit after production validation.

---

**Last Updated:** January 11, 2026  
**Version:** 1.0.0  
**Status:** Ready for Testing
