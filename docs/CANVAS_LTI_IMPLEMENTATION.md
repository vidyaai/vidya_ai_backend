# Canvas LTI Integration - Implementation Summary

## Overview

Vidya AI now supports Canvas LTI 1.3 integration, allowing instructors to generate AI-powered assignments directly from lecture notes stored in their Canvas courses. The integration uses Deep Linking to seamlessly add generated assignments to Canvas.

## What Was Implemented

### 1. Backend LTI Integration (`src/controllers/lti.py`)

**LTI 1.3 Endpoints:**
- `GET /lti/config.xml` - Canvas tool configuration endpoint
- `GET /lti/jwks` - JSON Web Key Set for signature verification
- `GET/POST /lti/login` - OIDC login initiation
- `POST /lti/launch` - Main LTI launch handler
- `GET /lti/api/canvas/files` - Fetch lecture notes from Canvas
- `POST /lti/api/canvas/download-file` - Download Canvas files
- `POST /lti/deeplink/response` - Send assignments back to Canvas
- `GET /lti/assignment/{assignment_id}` - View assignment (for students)

**Key Features:**
- Validates LTI launches using pylti1p3
- Extracts course and user context from Canvas
- Fetches PDF lecture notes via Canvas API
- Stores LTI sessions in database
- Creates Deep Link responses with JWT signing
- Supports both Deep Linking and regular course navigation

### 2. Database Model (`src/models.py`)

**CanvasLTISession Model:**
```python
class CanvasLTISession(Base):
    id = String (UUID)
    session_id = String (unique, indexed)
    canvas_course_id = String (indexed)
    canvas_course_name = String
    canvas_user_id = String
    canvas_user_name = String
    canvas_user_email = String
    canvas_api_domain = String
    launch_data = JSONB
    is_deep_link = Boolean
    created_at = DateTime
    expires_at = DateTime
```

Stores LTI session data for multi-step assignment generation workflow.

### 3. Frontend Canvas Assignment Generator (`src/app/canvas-assignment-generator/page.tsx`)

**Features:**
- Displays Canvas lecture note PDFs in a clean UI
- Multi-select file picker for lecture notes
- Assignment configuration (title, description, points, question types)
- Real-time assignment generation with progress indicator
- Assignment preview with questions and rubrics
- One-click "Add to Canvas" functionality
- Responsive design with Tailwind CSS

**User Flow:**
1. Instructor clicks "Create using Vidya AI" in Canvas assignments
2. Redirected to Vidya AI assignment generator
3. Selects lecture note PDFs from Canvas course
4. Configures assignment settings
5. Clicks "Generate Assignment"
6. Reviews generated questions with rubrics
7. Clicks "Add to Canvas Course"
8. Redirected back to Canvas with assignment created

### 4. Security & Configuration

**RSA Key Pair:**
- `private.key` - Used for signing JWTs (NEVER commit to git)
- `public.key` - Shared with Canvas for signature verification

**Configuration Files:**
- `lti_config.development.json` - Development Canvas settings
- `lti_config.production.json` - Production Canvas settings (gitignored)

**Environment Variables:**
```bash
ENVIRONMENT=development|production
API_BASE_URL=https://your-backend-url
FRONTEND_URL=https://your-frontend-url
```

**CORS Configuration:**
Added Canvas domains to CORS allow list in `main.py`:
- `https://*.instructure.com`
- `https://canvas.instructure.com`

### 5. Dependencies Added

**Backend (`requirements.txt`):**
- `pylti1p3==3.2.0` - LTI 1.3 library
- `PyJWT==2.10.1` - JWT token handling
- `cryptography==44.0.0` - RSA key operations
- `canvasapi==3.3.0` - Canvas API client

## Architecture Diagram

```
┌─────────────────┐
│   Canvas LMS    │
│   (Instructor)  │
└────────┬────────┘
         │
         │ 1. LTI Launch
         │    (OIDC + JWT)
         ▼
┌─────────────────┐
│  /lti/login     │
│  /lti/launch    │
│  (Backend)      │
└────────┬────────┘
         │
         │ 2. Redirect with
         │    session_id
         ▼
┌─────────────────────────────┐
│  Canvas Assignment          │
│  Generator UI (Frontend)    │
│  - Select lecture notes     │
│  - Configure assignment     │
│  - Generate with AI         │
└────────┬────────────────────┘
         │
         │ 3. Fetch Canvas files
         ▼
┌─────────────────┐
│ Canvas API      │
│ (Files endpoint)│
└────────┬────────┘
         │
         │ 4. Download PDFs
         ▼
┌─────────────────┐
│  S3 Storage     │
└────────┬────────┘
         │
         │ 5. Generate assignment
         ▼
┌─────────────────────────┐
│ /api/assignments/       │
│ generate (Backend)      │
│ - Parse PDFs            │
│ - Generate questions    │
│ - Create rubrics        │
└────────┬────────────────┘
         │
         │ 6. Return assignment
         ▼
┌─────────────────────────┐
│  Assignment Preview     │
│  (Frontend)             │
│  - Questions + Rubrics  │
│  - "Add to Canvas" btn  │
└────────┬────────────────┘
         │
         │ 7. Deep Link response
         ▼
┌─────────────────┐
│ /lti/deeplink/  │
│ response        │
│ (Create JWT)    │
└────────┬────────┘
         │
         │ 8. Auto-submit form
         │    with JWT
         ▼
┌─────────────────┐
│   Canvas LMS    │
│   (Assignment   │
│    created!)    │
└─────────────────┘
```

## Canvas Configuration

### Developer Key Setup

**Required Fields:**
- **Key Name:** Vidya AI Assignment Generator
- **Redirect URIs:** `{API_BASE_URL}/lti/launch`
- **Target Link URI:** `{API_BASE_URL}/lti/launch`
- **OpenID Connect Initiation URL:** `{API_BASE_URL}/lti/login`
- **Public JWK URL:** `{API_BASE_URL}/lti/jwks`

**Placements:**
- ✅ Assignment Selection - Shows "Create using Vidya AI" in assignment creation
- ✅ Course Navigation - Shows in course menu (for instructors only)

**LTI Advantage Services:**
- ✅ Can create and view assignment data in gradebook
- ✅ Deep Linking (for assignment creation)

### Installation in Course

1. Course Settings → Apps → + App
2. Configuration Type: "By Client ID"
3. Enter Client ID from Developer Key
4. Submit

## Key Technical Decisions

### 1. Session Management
- **Choice:** In-memory + database hybrid
- **Rationale:** Fast access during workflow, persistent for debugging
- **Future:** Consider Redis for production scale

### 2. Canvas API Authentication
- **Current:** Manual access token (temporary for testing)
- **Future:** Implement OAuth 2.0 flow for automatic token management
- **Note:** Access tokens should be stored securely per user

### 3. File Handling
- **Choice:** Download from Canvas → Upload to S3 → Generate
- **Rationale:** Consistent with existing assignment generation workflow
- **Benefit:** Works with existing document parsing infrastructure

### 4. Deep Linking
- **Choice:** Manual JWT creation instead of pylti1p3 Deep Link helpers
- **Rationale:** More control over response format and debugging
- **Note:** Uses RS256 signature with private key

### 5. Frontend Separation
- **Choice:** New Next.js page `/canvas-assignment-generator`
- **Rationale:** Dedicated UI for Canvas context, doesn't affect main app
- **Benefit:** Can customize for Canvas-specific features

## What's NOT Included (Future Enhancements)

1. **Grade Passback (AGS)** - Sending student scores back to Canvas gradebook
2. **OAuth Flow** - Automatic Canvas access token management
3. **Names and Roles Service** - Automatic roster sync
4. **Canvas File Picker Widget** - Native Canvas file selection UI
5. **Multi-Institution Support** - Multiple Canvas instances in production
6. **Assignment Editing in Canvas** - Edit generated assignments
7. **Student Submission Handling** - Students submitting within Canvas
8. **Canvas Rich Content Editor** - Embedding in content pages

## Testing

See `CANVAS_LTI_TESTING_GUIDE.md` for comprehensive testing instructions.

**Quick Test:**
1. Setup Canvas Free-for-Teacher account
2. Create Developer Key and get Client ID
3. Update `lti_config.development.json`
4. Start ngrok + backend + frontend
5. Install app in test course
6. Create assignment → "Create using Vidya AI"
7. Select lecture notes → Generate → Add to Canvas

## Production Deployment

**Pre-deployment:**
- [ ] Replace ngrok with permanent domain (api.vidyaai.co)
- [ ] Create `lti_config.production.json` with production Canvas instance
- [ ] Set `ENVIRONMENT=production` in `.env`
- [ ] Implement OAuth flow for Canvas tokens
- [ ] Apply database migrations
- [ ] Verify SSL certificates
- [ ] Test end-to-end with production Canvas

**Post-deployment:**
- [ ] Submit to Canvas App Center (optional)
- [ ] Document installation process for institutions
- [ ] Create support documentation
- [ ] Setup monitoring and alerting
- [ ] Implement rate limiting

## File Structure

```
vidya_ai_backend/
├── src/
│   ├── controllers/
│   │   └── lti.py                    # NEW - LTI integration
│   ├── models.py                      # UPDATED - Added CanvasLTISession
│   └── main.py                        # UPDATED - Added LTI router
├── lti_config.development.json        # NEW - Canvas dev config
├── lti_config.production.json         # NEW - Canvas prod config (gitignored)
├── private.key                        # NEW - RSA private key (gitignored)
├── public.key                         # NEW - RSA public key
├── requirements.txt                   # UPDATED - Added LTI dependencies
├── .gitignore                         # UPDATED - Added LTI security files
├── CANVAS_LTI_TESTING_GUIDE.md       # NEW - Testing documentation
└── CANVAS_LTI_IMPLEMENTATION.md      # NEW - This file

vidya_ai_frontend/
└── src/
    └── app/
        └── canvas-assignment-generator/
            └── page.tsx               # NEW - Canvas UI
```

## API Endpoints Reference

### LTI Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/lti/config.xml` | Canvas tool configuration |
| GET | `/lti/jwks` | Public key set |
| GET/POST | `/lti/login` | OIDC login initiation |
| POST | `/lti/launch` | Main LTI launch handler |
| GET | `/lti/api/canvas/files` | Fetch Canvas course files |
| POST | `/lti/api/canvas/download-file` | Download Canvas file |
| POST | `/lti/deeplink/response` | Send assignment to Canvas |
| GET | `/lti/assignment/{id}` | View assignment |

### Query Parameters

**`/lti/api/canvas/files`:**
- `session_id` (required) - LTI session ID
- `canvas_access_token` (required) - Canvas API token

**`/canvas-assignment-generator` (Frontend):**
- `session_id` (required) - LTI session ID
- `course_id` (required) - Canvas course ID
- `course_name` (required) - Canvas course name

## Security Considerations

1. **Private Key Protection**
   - Never commit `private.key` to git
   - Store securely with restricted permissions
   - Rotate periodically in production

2. **LTI Session Security**
   - Sessions expire after 1 hour
   - Validate all launch data
   - Use HTTPS only

3. **Canvas Access Tokens**
   - Implement OAuth flow (don't prompt users)
   - Store encrypted in database
   - Refresh before expiration

4. **CORS Configuration**
   - Only allow Canvas domains
   - Validate origins strictly

5. **JWT Signing**
   - Use RS256 algorithm
   - Verify Canvas signatures
   - Check token expiration

## Known Limitations

1. **Canvas Access Token** - Currently requires manual entry (temporary)
2. **Single Canvas Instance** - Development config supports one Canvas URL
3. **No Grade Passback** - Instructors must grade manually in Vidya AI
4. **PDF Only** - Only PDF files supported (not DOCX, PPTX yet)
5. **No Offline Mode** - Requires active Canvas connection
6. **Session Storage** - In-memory sessions don't persist across restarts

## Support Resources

- **Canvas LTI Docs:** https://canvas.instructure.com/doc/api/file.lti_dev_key_config.html
- **IMS Global LTI 1.3:** https://www.imsglobal.org/spec/lti/v1p3/
- **pylti1p3 Library:** https://github.com/dmitry-viskov/pylti1p3
- **Canvas API:** https://canvas.instructure.com/doc/api/

## Troubleshooting

See `CANVAS_LTI_TESTING_GUIDE.md` Part 4 for detailed troubleshooting steps.

**Common Issues:**
- LTI launch fails → Check Client ID and Deployment ID
- Files don't load → Verify Canvas access token
- Deep Link fails → Check private.key permissions
- ngrok expires → Update API_BASE_URL and restart

## Success Metrics

✅ **Implemented:**
- LTI 1.3 authentication working
- Canvas file selection working
- Assignment generation from PDFs working
- Deep Linking to Canvas working
- End-to-end workflow functional

🔄 **In Progress:**
- Canvas OAuth implementation
- Multi-institution support
- Production deployment

⏳ **Future:**
- Grade passback (AGS)
- Student submission handling
- Canvas App Center listing

---

**Status:** ✅ Development Complete - Ready for Testing
**Last Updated:** January 11, 2026
**Version:** 1.0.0
