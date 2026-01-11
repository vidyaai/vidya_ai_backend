# Canvas LTI Integration - Visual Flow Diagram

## Complete Workflow Visualization

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CANVAS LTI INTEGRATION FLOW                         │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐
│  STEP 1: Setup  │
└────────┬────────┘
         │
         ├── Generate RSA keys (private.key, public.key)
         ├── Configure lti_config.development.json
         ├── Create Canvas Developer Key
         ├── Update Client ID and Deployment ID
         └── Install app in Canvas course
         
         
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 2: Instructor Creates Assignment in Canvas                         │
└────────┬─────────────────────────────────────────────────────────────────┘
         │
         v
    ┌─────────────────┐
    │ Canvas UI       │
    │ - Assignments   │
    │ - + Assignment  │
    │ - External Tool │
    └────────┬────────┘
             │ Click "Create using Vidya AI"
             │
             v
    ┌────────────────────┐
    │ LTI Launch Flow    │
    │ (OIDC + JWT)       │
    └────────┬───────────┘
             │
             │ 1. POST /lti/login
             │    - Canvas sends: iss, client_id, login_hint
             │
             v
    ┌───────────────────────────┐
    │ Backend: /lti/login       │
    │ - Generate nonce & state  │
    │ - Build OIDC redirect URL │
    └────────┬──────────────────┘
             │
             │ 2. Redirect to Canvas auth
             │
             v
    ┌─────────────────────────┐
    │ Canvas Authentication   │
    │ - Verify instructor     │
    │ - Generate ID token     │
    └────────┬────────────────┘
             │
             │ 3. POST /lti/launch (with ID token)
             │
             v
    ┌──────────────────────────────────────────────┐
    │ Backend: /lti/launch                         │
    │ - Validate JWT signature (using JWKS)        │
    │ - Extract context: course_id, user_id, etc.  │
    │ - Create LTI session                         │
    │ - Store in database                          │
    └────────┬─────────────────────────────────────┘
             │
             │ 4. Redirect to frontend with session_id
             │
             v
    ┌────────────────────────────────────────────────┐
    │ Frontend: /canvas-assignment-generator         │
    │ URL: ?session_id=xxx&course_id=yyy             │
    └────────┬───────────────────────────────────────┘
             │
             
             
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 3: Select Lecture Notes from Canvas                                │
└────────┬─────────────────────────────────────────────────────────────────┘
         │
         v
    ┌────────────────────────────────┐
    │ Frontend UI                    │
    │ - Shows course name            │
    │ - Prompts for Canvas token (*) │
    └────────┬───────────────────────┘
             │
             │ (*) Temporary for testing
             │ Production: OAuth flow
             │
             │ 5. GET /lti/api/canvas/files
             │    params: session_id, canvas_access_token
             │
             v
    ┌─────────────────────────────────────────┐
    │ Backend: Fetch Canvas Files             │
    │ - Get LTI session                       │
    │ - Call Canvas API                       │
    │ - GET /api/v1/courses/{id}/files        │
    │ - Filter for PDFs                       │
    └────────┬────────────────────────────────┘
             │
             │ 6. Return file list
             │
             v
    ┌──────────────────────────────────┐
    │ Frontend: Display Files          │
    │ - List all PDFs                  │
    │ - Checkbox selection             │
    │ - File names and sizes           │
    └────────┬─────────────────────────┘
             │
             │ Instructor selects files
             │
             
             
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 4: Configure Assignment Settings                                   │
└────────┬─────────────────────────────────────────────────────────────────┘
         │
         v
    ┌──────────────────────────────────┐
    │ Frontend Configuration Form      │
    │ - Assignment Title               │
    │ - Description                    │
    │ - Number of Questions (1-50)     │
    │ - Total Points                   │
    │ - Question Types:                │
    │   • Multiple Choice              │
    │   • Short Answer                 │
    │   • True/False                   │
    │   • Numerical                    │
    │   • Multi-part                   │
    └────────┬─────────────────────────┘
             │
             │ Click "Generate Assignment"
             │
             
             
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 5: Generate Assignment from PDFs                                   │
└────────┬─────────────────────────────────────────────────────────────────┘
         │
         v
    ┌────────────────────────────────────────┐
    │ Frontend: Download Canvas Files        │
    │ For each selected file:                │
    │   7. POST /lti/api/canvas/download-file│
    │      - session_id                      │
    │      - file_id                         │
    │      - canvas_access_token             │
    └────────┬───────────────────────────────┘
             │
             v
    ┌─────────────────────────────────────────┐
    │ Backend: Download & Upload to S3        │
    │ - Get file from Canvas API              │
    │ - Upload to S3                          │
    │ - Return S3 key and presigned URL       │
    └────────┬────────────────────────────────┘
             │
             │ 8. POST /api/assignments/generate
             │    - title, description
             │    - generation_options
             │    - uploaded_files (S3 keys)
             │
             v
    ┌──────────────────────────────────────────┐
    │ Backend: AI Assignment Generation        │
    │ - Parse PDFs from S3                     │
    │ - Extract content                        │
    │ - Call OpenAI API                        │
    │ - Generate questions                     │
    │ - Create grading rubrics                 │
    │ - Calculate points distribution          │
    │ - Save to database                       │
    └────────┬─────────────────────────────────┘
             │
             │ 9. Return generated assignment
             │    - questions[]
             │    - rubrics[]
             │    - total_points
             │    - assignment_id
             │
             v
    ┌────────────────────────────────────┐
    │ Frontend: Display Preview          │
    │ - Show all questions               │
    │ - Display rubrics                  │
    │ - Show point distribution          │
    │ - "Regenerate" button              │
    │ - "Add to Canvas" button           │
    └────────┬───────────────────────────┘
             │
             
             
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 6: Add Assignment to Canvas (Deep Linking)                         │
└────────┬─────────────────────────────────────────────────────────────────┘
         │
         │ Click "Add to Canvas Course"
         │
         v
    ┌────────────────────────────────────┐
    │ Frontend: Submit to Canvas         │
    │ 10. POST /lti/deeplink/response    │
    │     - session_id                   │
    │     - assignment_id                │
    └────────┬───────────────────────────┘
             │
             v
    ┌─────────────────────────────────────────────┐
    │ Backend: Create Deep Link Response          │
    │ - Get LTI session                           │
    │ - Get assignment from database              │
    │ - Extract deep_link_return_url from launch  │
    │ - Create resource:                          │
    │   {                                         │
    │     type: "ltiResourceLink",                │
    │     title: assignment.title,                │
    │     url: /lti/assignment/{id},              │
    │     custom: { assignment_id, points }       │
    │   }                                         │
    │ - Sign JWT with private.key (RS256)         │
    │ - Create HTML form with JWT                 │
    └────────┬────────────────────────────────────┘
             │
             │ 11. Return auto-submit HTML form
             │
             v
    ┌──────────────────────────────────────┐
    │ Frontend: Auto-submit Form           │
    │ - Replace page with HTML form        │
    │ - Form auto-submits via JavaScript   │
    │ - POST to Canvas deep_link_return_url│
    │ - Includes JWT token                 │
    └────────┬─────────────────────────────┘
             │
             │ 12. Redirect to Canvas
             │
             v
    ┌────────────────────────────────────────┐
    │ Canvas: Process Deep Link              │
    │ - Verify JWT signature                 │
    │ - Extract resource data                │
    │ - Create assignment in course          │
    │ - Set title, points, external tool URL │
    └────────┬───────────────────────────────┘
             │
             │ ✅ Assignment Created!
             │
             v
    ┌─────────────────────────────────┐
    │ Canvas: Assignment List         │
    │ - New assignment appears        │
    │ - Shows title and points        │
    │ - Type: External Tool           │
    │ - Students can now see it       │
    └─────────────────────────────────┘


┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 7: Student Views Assignment                                        │
└────────┬─────────────────────────────────────────────────────────────────┘
         │
         v
    ┌──────────────────────────────────┐
    │ Student clicks assignment        │
    │ in Canvas                        │
    └────────┬─────────────────────────┘
             │
             │ Canvas launches external tool
             │ GET /lti/assignment/{id}
             │
             v
    ┌────────────────────────────────────────┐
    │ Backend: Render Assignment View        │
    │ - Get assignment from database         │
    │ - Generate HTML with:                  │
    │   • All questions                      │
    │   • Point values                       │
    │   • Rubrics (if enabled)               │
    │   • Formatted equations (if any)       │
    └────────┬───────────────────────────────┘
             │
             v
    ┌─────────────────────────────────────┐
    │ Student sees assignment questions   │
    │ - Can view all details              │
    │ - Sees grading rubrics              │
    │ - Knows point values                │
    └─────────────────────────────────────┘


═══════════════════════════════════════════════════════════════════════════

                            DATA FLOW DIAGRAM

═══════════════════════════════════════════════════════════════════════════

┌────────────┐         ┌────────────┐         ┌────────────┐
│   Canvas   │ ◄─────► │  Backend   │ ◄─────► │  Database  │
│    LMS     │         │   Server   │         │ PostgreSQL │
└─────┬──────┘         └──────┬─────┘         └────────────┘
      │                       │
      │                       │
      │                       ▼
      │              ┌────────────────┐
      │              │   S3 Storage   │ (Lecture PDFs)
      │              └────────────────┘
      │                       │
      │                       │
      │                       ▼
      │              ┌────────────────┐
      │              │  OpenAI API    │ (Generate Questions)
      │              └────────────────┘
      │
      ▼
┌────────────┐
│  Frontend  │
│   React    │
└────────────┘


═══════════════════════════════════════════════════════════════════════════

                        SECURITY & AUTHENTICATION

═══════════════════════════════════════════════════════════════════════════

1. LTI Launch Authentication:
   ┌──────────┐                    ┌──────────┐
   │  Canvas  │ ──── ID Token ───► │ Backend  │
   └──────────┘                    └────┬─────┘
                                        │
                                        │ Verify with
                                        │ Canvas JWKS
                                        ▼
                                   ┌─────────┐
                                   │  Valid  │
                                   └─────────┘

2. Deep Link Response:
   ┌──────────┐                    ┌──────────┐
   │ Backend  │ ──── JWT Token ──► │  Canvas  │
   └────┬─────┘   (signed with      └──────────┘
        │         private.key)
        │
        ▼
   ┌─────────────┐
   │ private.key │
   │  (RS256)    │
   └─────────────┘

3. Canvas API:
   ┌──────────┐                    ┌──────────┐
   │ Backend  │ ── Access Token ─► │ Canvas   │
   └──────────┘                    │   API    │
                                   └──────────┘


═══════════════════════════════════════════════════════════════════════════

                        DATABASE SCHEMA

═══════════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────┐
│     canvas_lti_sessions                 │
├─────────────────────────────────────────┤
│ id                 (UUID)               │
│ session_id         (unique, indexed)    │
│ canvas_course_id   (indexed)            │
│ canvas_course_name                      │
│ canvas_user_id                          │
│ canvas_user_name                        │
│ canvas_user_email                       │
│ canvas_api_domain                       │
│ launch_data        (JSONB)              │
│ is_deep_link       (boolean)            │
│ created_at         (timestamp)          │
│ expires_at         (timestamp)          │
└─────────────────────────────────────────┘
           │
           │ Links to existing
           │
           ▼
┌─────────────────────────────────────────┐
│     assignments                         │
├─────────────────────────────────────────┤
│ id                                      │
│ user_id                                 │
│ title                                   │
│ description                             │
│ questions          (JSONB)              │
│ total_points                            │
│ total_questions                         │
│ ...                                     │
└─────────────────────────────────────────┘


═══════════════════════════════════════════════════════════════════════════

                        API ENDPOINTS SUMMARY

═══════════════════════════════════════════════════════════════════════════

LTI Endpoints:
  GET    /lti/config.xml              - Canvas configuration
  GET    /lti/jwks                    - Public key set
  GET    /lti/login                   - OIDC login initiation
  POST   /lti/login                   - OIDC login initiation
  POST   /lti/launch                  - Main LTI launch handler
  GET    /lti/api/canvas/files        - Fetch Canvas files
  POST   /lti/api/canvas/download-file- Download Canvas file
  POST   /lti/deeplink/response       - Deep Link response
  GET    /lti/assignment/{id}         - View assignment

Assignment Endpoints (Existing):
  POST   /api/assignments/generate    - Generate assignment
  GET    /api/assignments/{id}        - Get assignment
  POST   /api/assignments/{id}/grade  - Grade submission


═══════════════════════════════════════════════════════════════════════════

                        TESTING WORKFLOW

═══════════════════════════════════════════════════════════════════════════

1. Setup (One-time):
   ✓ Run ./setup_canvas_lti.sh
   ✓ Create Canvas Free-for-Teacher account
   ✓ Upload test PDFs to Canvas
   ✓ Create Developer Key in Canvas
   ✓ Update lti_config.development.json

2. Development Testing:
   ✓ Start backend (python src/main.py)
   ✓ Start frontend (yarn dev)
   ✓ Start ngrok (ngrok http 8000)
   ✓ Update API_BASE_URL to ngrok URL
   ✓ Install app in Canvas course

3. Test Flow:
   ✓ Canvas: Create Assignment
   ✓ Select "Create using Vidya AI"
   ✓ Select lecture PDFs
   ✓ Configure settings
   ✓ Generate assignment
   ✓ Add to Canvas
   ✓ Verify in Canvas assignments list

4. Verify:
   ✓ Assignment appears in Canvas
   ✓ Students can view it
   ✓ Questions display correctly
   ✓ Rubrics are visible


═══════════════════════════════════════════════════════════════════════════

                    TROUBLESHOOTING DECISION TREE

═══════════════════════════════════════════════════════════════════════════

Problem: LTI Launch Fails
  │
  ├─ Check: Backend logs
  │    └─ "LTI not configured" → Verify lti_config.json exists
  │
  ├─ Check: Canvas Developer Key
  │    └─ Key status: OFF → Turn it ON
  │
  ├─ Check: Client ID / Deployment ID
  │    └─ Mismatch → Update lti_config.json
  │
  └─ Check: ngrok URL
       └─ Changed → Update API_BASE_URL and Canvas config


Problem: Files Don't Load
  │
  ├─ Check: Canvas access token
  │    └─ Invalid/expired → Generate new token
  │
  ├─ Check: Canvas API response
  │    └─ 401 error → Token doesn't have permissions
  │
  └─ Check: Course has PDFs
       └─ Empty → Upload test PDFs to Canvas


Problem: Generation Fails
  │
  ├─ Check: S3 upload
  │    └─ Error → Verify AWS credentials
  │
  ├─ Check: OpenAI API
  │    └─ Error → Verify API key
  │
  └─ Check: File format
       └─ Not PDF → Currently only PDFs supported


Problem: Deep Link Fails
  │
  ├─ Check: private.key readable
  │    └─ Permission denied → chmod 600 private.key
  │
  ├─ Check: JWT signature
  │    └─ Invalid → Regenerate keys
  │
  └─ Check: Canvas response
       └─ Error → Check Canvas logs in Developer Keys


═══════════════════════════════════════════════════════════════════════════
                         END OF VISUAL FLOW DIAGRAM
═══════════════════════════════════════════════════════════════════════════
