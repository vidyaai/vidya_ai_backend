# Canvas LTI Integration Testing Guide

## Overview

This guide provides step-by-step instructions for testing the Vidya AI Canvas LTI integration. The integration allows Canvas instructors to generate AI-powered assignments from lecture notes stored in Canvas.

## Prerequisites

Before you begin testing, ensure you have:

1. ✅ Backend server running (with LTI endpoints implemented)
2. ✅ Frontend server running (with Canvas assignment generator page)
3. ✅ RSA key pair generated (`private.key` and `public.key`)
4. ✅ LTI configuration files created
5. ✅ Database migrations applied (for `CanvasLTISession` model)

## Part 1: Environment Setup

### Step 1: Install Python Dependencies

```bash
cd vidya_ai_backend
source venv/bin/activate  # or vai_venv/bin/activate
pip install -r requirements.txt
```

Verify the following packages are installed:
- `pylti1p3==3.2.0`
- `PyJWT==2.10.1`
- `cryptography==44.0.0`
- `canvasapi==3.3.0`

### Step 2: Configure Environment Variables

Create or update `.env` in `vidya_ai_backend/`:

```bash
# Environment
ENVIRONMENT=development

# API Base URL (for development, use ngrok)
API_BASE_URL=https://your-ngrok-url.ngrok.io

# Frontend URL
FRONTEND_URL=http://localhost:3000

# Database (your existing config)
DATABASE_URL=postgresql://...

# Firebase (your existing config)
FIREBASE_CONFIG=./vidyaai-app-firebase-adminsdk-*.json

# AWS S3 (your existing config)
AWS_S3_BUCKET=...
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...

# OpenAI (your existing config)
OPENAI_API_KEY=...
```

### Step 3: Run Database Migration

```bash
cd vidya_ai_backend

# Create a new migration for the CanvasLTISession model
alembic revision --autogenerate -m "Add CanvasLTISession model"

# Apply the migration
alembic upgrade head
```

### Step 4: Setup ngrok (for Development Testing)

Canvas requires HTTPS endpoints. Use ngrok to expose your local server:

```bash
# Install ngrok (if not installed)
brew install ngrok  # macOS

# Start ngrok in a separate terminal
ngrok http 8000
```

You'll see output like:
```
Forwarding    https://abc123def456.ngrok.io -> http://localhost:8000
```

**Copy the HTTPS URL** and update:
1. `.env` file: `API_BASE_URL=https://abc123def456.ngrok.io`
2. `lti_config.development.json`: Update all URLs to use your ngrok URL

### Step 5: Start Servers

**Terminal 1 - Backend:**
```bash
cd vidya_ai_backend/src
python main.py
```

**Terminal 2 - Frontend:**
```bash
cd vidya_ai_frontend
yarn dev
```

**Terminal 3 - ngrok:**
```bash
ngrok http 8000
```

## Part 2: Canvas Setup

### Step 1: Create Canvas Free-for-Teacher Account

1. Go to: https://www.instructure.com/canvas/try-canvas
2. Click: **"Try Canvas Free for Teachers"**
3. Fill out the registration form:
   - **Name:** Your name
   - **Email:** Your email
   - **School:** "Vidya AI Test School"
   - **Role:** "Teacher/Instructor"
4. Check your email for login credentials
5. You'll receive a Canvas URL like: `yourname.instructure.com`
6. Login to Canvas

### Step 2: Create Test Course

1. In Canvas, click: **"Courses"** (left menu)
2. Click: **"Start a New Course"**
3. Enter course details:
   - **Course Name:** "CS101 - Data Structures"
   - **Course Code:** "CS101"
4. Click: **"Create Course"**
5. Click: **"Publish"** button (top right) to make course active

### Step 3: Upload Test Lecture Notes

1. In your course, click: **"Files"** (left menu)
2. Click: **"Upload"** button
3. Upload some test PDF files (lecture notes, textbooks, etc.)
   - You can use any PDF for testing
   - Name them clearly: "Lecture 1 - Arrays.pdf", "Lecture 2 - Linked Lists.pdf", etc.
4. Make sure files are uploaded successfully

### Step 4: Create Developer Key

1. Click: **"Admin"** (left sidebar)
2. Click: **"Developer Keys"** (under "Admin")
3. Click: **"+ Developer Key"** → **"+ LTI Key"**

**Fill in the form:**

**Key Name:** `Vidya AI Assignment Generator`

**Owner Email:** Your email

**Redirect URIs:** 
```
https://your-ngrok-url.ngrok.io/lti/launch
```

**Method:** Manual Entry

**Title:** `Vidya AI`

**Description:** `AI-powered assignment generation from lecture notes`

**Target Link URI:**
```
https://your-ngrok-url.ngrok.io/lti/launch
```

**OpenID Connect Initiation Url:**
```
https://your-ngrok-url.ngrok.io/lti/login
```

**JWK Method:** Public JWK URL

**Public JWK URL:**
```
https://your-ngrok-url.ngrok.io/lti/jwks
```

**LTI Advantage Services:**
- ✅ Can create and view assignment data in the gradebook
- ✅ Can view assignment data in the gradebook
- ✅ Can create and update assignment data in the gradebook

**Placements:**
- ✅ Assignment Selection
- ✅ Course Navigation

**Privacy Level:** Public

**Custom Fields:** (leave blank for now)

4. Click: **"Save"**

5. **IMPORTANT:** Copy the following values:
   - **Client ID** (looks like: `10000000000001`)
   - Click the key to view details
   - Copy **Deployment ID** (looks like: `1:abc123def456`)

6. Toggle the key to **"ON"** (green)

### Step 5: Update LTI Configuration

Edit `vidya_ai_backend/lti_config.development.json`:

```json
{
  "https://yourname.instructure.com": {
    "client_id": "PASTE_YOUR_CLIENT_ID_HERE",
    "auth_login_url": "https://yourname.instructure.com/api/lti/authorize_redirect",
    "auth_token_url": "https://yourname.instructure.com/login/oauth2/token",
    "key_set_url": "https://yourname.instructure.com/api/lti/security/jwks",
    "deployment_ids": ["PASTE_YOUR_DEPLOYMENT_ID_HERE"],
    "private_key_file": "private.key",
    "public_key_file": "public.key"
  }
}
```

**Important:** Replace:
- `yourname.instructure.com` with your actual Canvas domain
- `PASTE_YOUR_CLIENT_ID_HERE` with the Client ID from Canvas
- `PASTE_YOUR_DEPLOYMENT_ID_HERE` with the Deployment ID from Canvas

**Restart your backend server** after updating this file.

### Step 6: Install App in Course

1. Go to your test course in Canvas
2. Click: **"Settings"** (left menu)
3. Click: **"Apps"** tab
4. Click: **"+ App"** button
5. Configuration Type: **"By Client ID"**
6. Client ID: **Paste your Client ID**
7. Click: **"Submit"**

You should see "Vidya AI Assignment Generator" in the list of installed apps with status: **Active ✅**

## Part 3: Testing the Integration

### Test 1: Verify LTI Endpoints

Before testing in Canvas, verify endpoints are accessible:

```bash
# Test config.xml endpoint
curl https://your-ngrok-url.ngrok.io/lti/config.xml

# Test JWKS endpoint
curl https://your-ngrok-url.ngrok.io/lti/jwks
```

Both should return valid responses (XML for config, JSON for JWKS).

### Test 2: Launch from Assignment Creation

1. In Canvas course, click: **"Assignments"** (left menu)
2. Click: **"+ Assignment"** button
3. Enter assignment details:
   - **Assignment Name:** "Test Assignment 1"
   - **Points:** 100
4. Scroll to **"Submission Type"**
5. Click dropdown and select: **"External Tool"**
6. Click: **"Find"** button
7. You should see: **"Create using Vidya AI"**
8. Click on it
9. Click: **"Select"**

**Expected Behavior:**
- Canvas should redirect to your ngrok URL
- Backend `/lti/login` endpoint is called
- Canvas authenticates the user
- Backend `/lti/launch` endpoint is called
- User is redirected to: `http://localhost:3000/canvas-assignment-generator?session_id=...&course_id=...&course_name=...`

**Check Backend Logs:**
```
Incoming request: POST /lti/login
LTI Login initiated: {...}
Redirecting to Canvas auth: https://...
Incoming request: POST /lti/launch
LTI Launch Data: {...}
```

**If it fails:**
- Check backend logs for errors
- Verify ngrok is running
- Verify Client ID and Deployment ID are correct in `lti_config.development.json`
- Verify `/lti/login` and `/lti/launch` endpoints are accessible

### Test 3: Canvas File Selection

Once redirected to the assignment generator page:

1. You should see:
   - Page title: "Vidya AI Assignment Generator"
   - Course name displayed
   - A popup asking for Canvas access token (this is temporary for testing)

2. **Get Canvas Access Token:**
   - In Canvas, click your avatar (top left)
   - Click: **"Settings"**
   - Scroll down to: **"Approved Integrations"**
   - Click: **"+ New Access Token"**
   - Purpose: "Testing Vidya AI"
   - Expiration: (leave blank or set future date)
   - Click: **"Generate Token"**
   - **COPY THE TOKEN** (you'll only see it once!)
   - Paste it in the popup

3. After entering token:
   - The page should load your lecture note PDFs
   - You should see a list of files you uploaded earlier
   - Each file should be clickable with a checkbox

**Expected Behavior:**
- Files from Canvas appear in the list
- You can select/deselect files
- File names, sizes are displayed correctly

**If it fails:**
- Check browser console for errors
- Verify Canvas access token is valid
- Check backend logs for Canvas API errors
- Verify `/lti/api/canvas/files` endpoint is working

### Test 4: Assignment Generation

1. Select one or more lecture note PDFs (click to toggle selection)
2. Fill in assignment details:
   - **Title:** "Midterm Exam - Data Structures"
   - **Description:** "Test assignment from lecture notes"
   - **Number of Questions:** 10
   - **Total Points:** 100
3. Select question types (multiple-choice, short-answer, etc.)
4. Click: **"Generate Assignment"** button

**Expected Behavior:**
- "Generating Assignment..." message appears
- Backend downloads selected files from Canvas
- Files are uploaded to S3
- Assignment generation API is called
- After 30-60 seconds, assignment preview appears
- Questions are displayed with points and rubrics

**Check Backend Logs:**
```
Incoming request: POST /lti/api/canvas/download-file
Downloading Canvas file: lecture-1.pdf
Uploading to S3: canvas-files/...
Incoming request: POST /api/assignments/generate
Generating assignment for user: ...
Generated assignment: {assignment_id} - Midterm Exam
```

**If it fails:**
- Check browser console and network tab
- Verify assignment generation API works outside Canvas
- Check S3 upload permissions
- Verify OpenAI API key is set

### Test 5: Add to Canvas

After assignment is generated:

1. Review the generated assignment:
   - Questions should be relevant to lecture content
   - Points should be distributed
   - Rubrics should be present
2. Click: **"Add to Canvas Course"** button

**Expected Behavior:**
- "Adding to Canvas..." message appears
- Backend creates Deep Link response
- HTML form auto-submits back to Canvas
- You're redirected back to Canvas
- Assignment appears in Canvas assignments list

**Check Backend Logs:**
```
Incoming request: POST /lti/deeplink/response
Creating Deep Link response for assignment: {assignment_id}
Sending Deep Link JWT to Canvas
```

**In Canvas:**
- Go to: **"Assignments"** (left menu)
- You should see your new assignment: "Midterm Exam - Data Structures"
- Click on it to view
- Assignment should show:
  - Title and description
  - Points: 100
  - Submission type: External Tool
  - Questions preview

**If it fails:**
- Check if Deep Link return URL is present in launch data
- Verify JWT signing with private key works
- Check Canvas logs (in Developer Keys section)
- Verify assignment was saved to database

### Test 6: Student View

1. In Canvas, click your avatar (top right)
2. Click: **"Act as User"**
3. Create a fake student:
   - Email: `student1@test.com`
   - Name: "Test Student"
4. Click: **"Proceed"**
5. Go to: **"Assignments"**
6. Click on the assignment you created

**Expected Behavior:**
- Student sees assignment details
- Questions are displayed (without solutions if configured)
- Student can view rubrics
- Assignment shows point values

## Part 4: Troubleshooting

### Common Issues

#### Issue 1: "LTI not configured" error

**Cause:** LTI config file not found or invalid

**Solution:**
- Verify `lti_config.development.json` exists in backend root
- Check file permissions
- Verify JSON syntax is correct
- Restart backend server

#### Issue 2: "Invalid launch request"

**Cause:** JWT validation failed or incorrect Client ID/Deployment ID

**Solution:**
- Double-check Client ID in `lti_config.development.json`
- Verify Deployment ID is correct
- Ensure Developer Key is "ON" in Canvas
- Check that public.key file is readable

#### Issue 3: Canvas files not loading

**Cause:** Canvas API authentication failed or permissions issue

**Solution:**
- Generate a new Canvas access token
- Verify token has proper permissions
- Check Canvas API domain is correct
- Ensure course has files uploaded

#### Issue 4: Assignment generation fails

**Cause:** File download from Canvas failed or S3 upload failed

**Solution:**
- Check Canvas access token is valid
- Verify S3 credentials in `.env`
- Ensure files are accessible in Canvas
- Check backend logs for specific error

#### Issue 5: Deep Link response not working

**Cause:** JWT signing failed or return URL missing

**Solution:**
- Verify `private.key` file exists and is readable
- Check Deep Link return URL in launch data
- Verify JWT payload structure
- Check Canvas Developer Key has Deep Linking enabled

#### Issue 6: ngrok URL keeps changing

**Cause:** Free ngrok restarts generate new URLs

**Solution:**
- Update `API_BASE_URL` in `.env` when ngrok restarts
- Update Canvas Developer Key Redirect URIs
- For production, use permanent domain (api.vidyaai.co)
- Consider ngrok paid plan for static domain

### Debugging Commands

**Check if backend is running:**
```bash
curl http://localhost:8000/
# Should return: {"status": "Vidya AI backend is running"}
```

**Test ngrok tunnel:**
```bash
curl https://your-ngrok-url.ngrok.io/
```

**Check LTI endpoints:**
```bash
curl https://your-ngrok-url.ngrok.io/lti/config.xml
curl https://your-ngrok-url.ngrok.io/lti/jwks
```

**View backend logs:**
```bash
tail -f vidya_ai_backend/logs/server.log
```

**Check database:**
```bash
psql $DATABASE_URL
SELECT * FROM canvas_lti_sessions ORDER BY created_at DESC LIMIT 5;
```

## Part 5: Production Deployment

### Pre-deployment Checklist

- [ ] All tests pass in development
- [ ] ngrok replaced with permanent domain (api.vidyaai.co)
- [ ] `lti_config.production.json` created with production settings
- [ ] `ENVIRONMENT=production` in `.env`
- [ ] Private key secured (not in git)
- [ ] Canvas OAuth flow implemented (for access tokens)
- [ ] Database migrations applied to production
- [ ] SSL certificate valid
- [ ] CORS configured for Canvas domains
- [ ] Error handling and logging configured
- [ ] Rate limiting implemented

### Production Configuration

Update `lti_config.production.json`:

```json
{
  "https://canvas.instructure.com": {
    "client_id": "PRODUCTION_CLIENT_ID",
    "auth_login_url": "https://canvas.instructure.com/api/lti/authorize_redirect",
    "auth_token_url": "https://canvas.instructure.com/login/oauth2/token",
    "key_set_url": "https://canvas.instructure.com/api/lti/security/jwks",
    "deployment_ids": ["PRODUCTION_DEPLOYMENT_ID"],
    "private_key_file": "private.key",
    "public_key_file": "public.key"
  }
}
```

Update `.env` for production:

```bash
ENVIRONMENT=production
API_BASE_URL=https://api.vidyaai.co
FRONTEND_URL=https://vidyaai.co
```

### Deploy to Production

```bash
# Backend
cd vidya_ai_backend
git pull origin main
pip install -r requirements.txt
alembic upgrade head
sudo systemctl restart vidyaai-backend

# Frontend
cd vidya_ai_frontend
git pull origin main
yarn install
yarn build
pm2 restart vidyaai-frontend
```

### Post-Deployment Testing

Repeat Tests 1-6 using production URLs and real Canvas instance.

## Part 6: Canvas App Center Submission (Optional)

Once production deployment is successful and tested:

1. Go to: https://www.eduappcenter.com
2. Click: **"Submit an App"**
3. Fill in details:
   - **App Name:** Vidya AI Assignment Generator
   - **Configuration URL:** `https://api.vidyaai.co/lti/config.xml`
   - **Description:** AI-powered assignment generation from lecture notes
   - **Support Email:** support@vidyaai.co
   - **Privacy Policy URL:** https://vidyaai.co/privacy
   - **Terms of Service URL:** https://vidyaai.co/terms
4. Upload screenshots
5. Submit for review

Review typically takes 1-3 weeks.

## Conclusion

This completes the Canvas LTI integration testing guide. If you encounter any issues not covered here, check:

1. Backend logs: `vidya_ai_backend/logs/server.log`
2. Browser console (F12)
3. Canvas Developer Key logs
4. ngrok request inspector: http://127.0.0.1:4040

For additional help, refer to:
- Canvas LTI Documentation: https://canvas.instructure.com/doc/api/file.lti_dev_key_config.html
- pylti1p3 Documentation: https://github.com/dmitry-viskov/pylti1p3
- IMS Global LTI Spec: https://www.imsglobal.org/spec/lti/v1p3/

---

**Testing Status Checklist:**

- [ ] Environment setup complete
- [ ] Canvas account created
- [ ] Test course created with lecture notes
- [ ] Developer Key created and configured
- [ ] LTI endpoints responding
- [ ] Assignment creation flow works
- [ ] Canvas files load correctly
- [ ] Assignment generates successfully
- [ ] Assignment adds to Canvas
- [ ] Student can view assignment
- [ ] Ready for production deployment
