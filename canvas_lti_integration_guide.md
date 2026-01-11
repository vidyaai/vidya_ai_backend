# Canvas LTI 1.3 Integration Guide for Vidya AI Assignment Generator

## Project Overview

**Goal:** Integrate Vidya AI's assignment generation feature with Canvas LMS using LTI 1.3 (Learning Tools Interoperability)

**Current Setup:**
- FastAPI backend running on EC2: `https://api.vidyaai.co`
- Existing assignment generation endpoint: `/api/assignment/generate`
- Firebase authentication for direct users

**What We're Building:**
- Canvas professors click "Add Vidya Assignment" in their course
- Vidya AI's UI opens (embedded in Canvas)
- Professor generates assignment using existing UI
- Assignment automatically appears in Canvas course
- Students see assignment in Canvas

**Which UI:** Vidya AI's existing UI (Canvas embeds it via iframe)

---

## Architecture Overview

### The Flow

```
1. Professor in Canvas clicks "Add Vidya Assignment"
   ↓
2. Canvas sends professor to Vidya API with secure JWT token
   ↓
3. Vidya API validates token, extracts: course_id, professor_id, course_name
   ↓
4. Vidya API redirects to assignment generator UI
   ↓
5. Professor uses Vidya UI to generate assignment
   ↓
6. Professor clicks "Add to Canvas"
   ↓
7. Vidya API sends assignment data back to Canvas in LTI Deep Link format
   ↓
8. Assignment appears in Canvas course automatically
```

### Key Components to Build

1. **LTI Launch Endpoints** (3 endpoints)
   - `/lti/login` - OIDC login initiation
   - `/lti/launch` - Main LTI launch handler
   - `/lti/jwks` - Public key endpoint

2. **Configuration Endpoints**
   - `/lti/config.xml` - Canvas tool configuration

3. **Deep Linking**
   - `/lti/deeplink/response` - Send assignment to Canvas

4. **Assignment Generator Integration**
   - Modify existing UI to accept Canvas context
   - Add "Add to Canvas" functionality

---

## Phase 1: Setup Test Environment (30 minutes)

### Step 1: Create Canvas Free-for-Teacher Account

1. Go to: https://www.instructure.com/canvas/try-canvas
2. Click: "Try Canvas Free for Teachers"
3. Fill out form:
   - Name: Your name
   - Email: Your email
   - School: "Vidya AI Test School"
   - Role: "Teacher/Instructor"
4. You'll receive email with login to `yourname.instructure.com`
5. Login to see empty Canvas dashboard

### Step 2: Create Test Course

1. In Canvas, click: "Courses" → "Start a New Course"
2. Name it: "Test Course - CS101"
3. Click: "Create Course"
4. Publish the course: Click "Publish" button (right side)

### Step 3: Add Fake Students for Testing

1. In your course, click: "People" (left menu)
2. Click: "+ People" button
3. Add these fake students:
   ```
   Email: student1@test.com
   Name: Alice Test
   Role: Student
   
   Email: student2@test.com
   Name: Bob Test
   Role: Student
   
   Email: student3@test.com
   Name: Carol Test
   Role: Student
   ```
4. Canvas will send "invitations" - ignore them, you control these accounts

---

## Phase 2: Install Required Dependencies

### Python Libraries

```bash
pip install pylti1p3
pip install pyjwt
pip install cryptography
```

### Generate Security Keys

```bash
# Generate RSA key pair for LTI signing
openssl genrsa -out private.key 2048
openssl rsa -in private.key -pubout -out public.key
```

**Important:** 
- `private.key` - Keep secret! Add to `.gitignore`
- `public.key` - Share with Canvas

---

## Phase 3: Development vs Production Setup

### Development Setup (Local Testing)

**Tools Needed:**
- ngrok (for exposing localhost to Canvas)

```bash
# Install ngrok
# Mac: brew install ngrok
# Windows: Download from ngrok.com

# Run your FastAPI
uvicorn main:app --reload --port 8000

# In another terminal, expose it
ngrok http 8000

# You'll get a URL like: https://abc123.ngrok.io
# This URL changes every time you restart ngrok!
```

**Environment Variables (Development):**
```bash
ENVIRONMENT=development
API_BASE_URL=https://abc123.ngrok.io  # Your ngrok URL
```

### Production Setup (EC2)

**No ngrok needed!** Your EC2 is already publicly accessible.

**Environment Variables (Production):**
```bash
ENVIRONMENT=production
API_BASE_URL=https://api.vidyaai.co  # Your permanent EC2 URL
```

**EC2 Requirements:**
- ✅ HTTPS enabled (you have this)
- ✅ Port 443 open in security group
- ✅ SSL certificate (Let's Encrypt or AWS Certificate Manager)
- ✅ Domain pointed to EC2 (api.vidyaai.co)

---

## Phase 4: Create LTI Configuration Files

### File Structure

```
your-fastapi-project/
├── main.py (existing)
├── controllers/
│   ├── lti.py (NEW - create this)
│   ├── assignments.py (existing)
│   └── ... (your existing files)
├── lti_config.development.json (NEW)
├── lti_config.production.json (NEW)
├── private.key (NEW - generated above)
├── public.key (NEW - generated above)
└── .env
```

### lti_config.development.json

**Create this file for testing:**

```json
{
  "https://yourname.instructure.com": {
    "client_id": "WILL_GET_FROM_CANVAS",
    "auth_login_url": "https://yourname.instructure.com/api/lti/authorize_redirect",
    "auth_token_url": "https://yourname.instructure.com/login/oauth2/token",
    "key_set_url": "https://yourname.instructure.com/api/lti/security/jwks",
    "deployment_ids": ["WILL_GET_FROM_CANVAS"],
    "private_key_file": "private.key",
    "public_key_file": "public.key"
  }
}
```

**Note:** Replace `yourname.instructure.com` with your actual Canvas Free-for-Teacher URL.

### lti_config.production.json

**Create this file for production (multiple institutions):**

```json
{
  "https://canvas.instructure.com": {
    "client_id": "PRODUCTION_CLIENT_ID_FROM_INSTITUTION",
    "auth_login_url": "https://canvas.instructure.com/api/lti/authorize_redirect",
    "auth_token_url": "https://canvas.instructure.com/login/oauth2/token",
    "key_set_url": "https://canvas.instructure.com/api/lti/security/jwks",
    "deployment_ids": ["PRODUCTION_DEPLOYMENT_ID"],
    "private_key_file": "private.key",
    "public_key_file": "public.key"
  },
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

**Note:** Each institution that installs your app will have their own entry.

---

## Phase 5: Implement LTI Endpoints

### Create controllers/lti.py

**This is the main LTI integration file:**

```python
import os
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pylti1p3.tool_config import ToolConfJsonFile
from pylti1p3.message_launch import MessageLaunch
from pylti1p3.deep_link import DeepLink
from pylti1p3.grade import Grade

router = APIRouter(prefix="/lti", tags=["LTI"])

# Load environment-specific configuration
ENV = os.getenv("ENVIRONMENT", "production")
config_file = f"lti_config.{ENV}.json"
tool_conf = ToolConfJsonFile(config_file)

# Get base URL from environment
BASE_URL = os.getenv("API_BASE_URL", "https://api.vidyaai.co")


@router.get("/config.xml")
async def lti_config():
    """
    Canvas uses this XML to install your tool.
    This endpoint returns the LTI configuration in Canvas-compatible format.
    """
    
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<cartridge_basiclti_link xmlns="http://www.imsglobal.org/xsd/imslticc_v1p0"
    xmlns:blti = "http://www.imsglobal.org/xsd/imsbasiclti_v1p0"
    xmlns:lticm ="http://www.imsglobal.org/xsd/imslticm_v1p0"
    xmlns:lticp ="http://www.imsglobal.org/xsd/imslticp_v1p0"
    xmlns:xsi = "http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation = "http://www.imsglobal.org/xsd/imslticc_v1p0 http://www.imsglobal.org/xsd/lti/ltiv1p0/imslticc_v1p0.xsd
    http://www.imsglobal.org/xsd/imsbasiclti_v1p0 http://www.imsglobal.org/xsd/lti/ltiv1p0/imsbasiclti_v1p0.xsd
    http://www.imsglobal.org/xsd/imslticm_v1p0 http://www.imsglobal.org/xsd/lti/ltiv1p0/imslticm_v1p0.xsd
    http://www.imsglobal.org/xsd/imslticp_v1p0 http://www.imsglobal.org/xsd/lti/ltiv1p0/imslticp_v1p0.xsd">
    <blti:title>Vidya AI Assignment Generator</blti:title>
    <blti:description>AI-powered assignment and question paper generation for STEM courses</blti:description>
    <blti:launch_url>{BASE_URL}/lti/launch</blti:launch_url>
    <blti:extensions platform="canvas.instructure.com">
        <lticm:property name="tool_id">vidya_ai_assignments</lticm:property>
        <lticm:property name="privacy_level">public</lticm:property>
        <lticm:options name="course_navigation">
            <lticm:property name="url">{BASE_URL}/lti/launch</lticm:property>
            <lticm:property name="text">Vidya AI Assignments</lticm:property>
            <lticm:property name="enabled">true</lticm:property>
        </lticm:options>
        <lticm:options name="assignment_selection">
            <lticm:property name="url">{BASE_URL}/lti/launch</lticm:property>
            <lticm:property name="message_type">ContentItemSelectionRequest</lticm:property>
            <lticm:property name="text">Vidya AI Assignment</lticm:property>
        </lticm:options>
    </blti:extensions>
</cartridge_basiclti_link>"""
    
    return HTMLResponse(content=xml, media_type="application/xml")


@router.get("/jwks")
async def get_jwks():
    """
    Canvas fetches your public key from this endpoint.
    This is used to verify signatures and secure communication.
    """
    
    # Read your public key
    with open('public.key', 'r') as f:
        public_key = f.read()
    
    from pylti1p3.registration import Registration
    registration = Registration()
    registration.set_public_key(public_key)
    
    return JSONResponse(content=registration.get_jwks())


@router.post("/login")
@router.get("/login")
async def lti_login(request: Request):
    """
    OIDC Login Initiation - Canvas redirects professor here first.
    This is the first step in the LTI 1.3 authentication flow.
    """
    
    # Get launch parameters from Canvas
    if request.method == "POST":
        form_data = await request.form()
    else:
        form_data = request.query_params
    
    target_link_uri = form_data.get('target_link_uri')
    lti_message_hint = form_data.get('lti_message_hint')
    login_hint = form_data.get('login_hint')
    client_id = form_data.get('client_id')
    iss = form_data.get('iss')
    
    # Generate nonce and state for security
    nonce = os.urandom(16).hex()
    state = os.urandom(16).hex()
    
    # Build OIDC auth URL to redirect back to Canvas
    oidc_url = (
        f"{iss}/api/lti/authorize_redirect?"
        f"client_id={client_id}&"
        f"login_hint={login_hint}&"
        f"lti_message_hint={lti_message_hint}&"
        f"nonce={nonce}&"
        f"redirect_uri={target_link_uri}&"
        f"response_mode=form_post&"
        f"response_type=id_token&"
        f"scope=openid&"
        f"state={state}"
    )
    
    return RedirectResponse(url=oidc_url)


@router.post("/launch")
async def lti_launch(request: Request):
    """
    Main LTI Launch Handler - Canvas sends professor here with course context.
    This validates the launch and redirects to the assignment generator UI.
    """
    
    try:
        # Validate the LTI launch using pylti1p3
        message_launch = MessageLaunch(request, tool_conf)
        launch_data = message_launch.get_launch_data()
        
        # Extract Canvas context
        context = launch_data.get('https://purl.imsglobal.org/spec/lti/claim/context', {})
        course_id = context.get('id')
        course_name = context.get('title', 'Unknown Course')
        
        user_id = launch_data.get('sub')
        user_name = launch_data.get('name', 'Unknown User')
        user_email = launch_data.get('email', '')
        
        # Get user roles
        roles = launch_data.get('https://purl.imsglobal.org/spec/lti/claim/roles', [])
        is_instructor = any('Instructor' in role for role in roles)
        
        # Store launch session ID for later use
        launch_id = message_launch.get_launch_id()
        
        # Check if this is a Deep Link request (assignment creation)
        if message_launch.is_deep_link_launch():
            # Redirect to assignment generator UI with Canvas context
            redirect_url = (
                f"{BASE_URL}/assignment-generator?"
                f"course_id={course_id}&"
                f"course_name={course_name}&"
                f"user_id={user_id}&"
                f"user_name={user_name}&"
                f"user_email={user_email}&"
                f"is_instructor={is_instructor}&"
                f"lti_session={launch_id}"
            )
            return RedirectResponse(url=redirect_url)
        else:
            # Regular launch - show course navigation view
            return HTMLResponse(content=f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Vidya AI - {course_name}</title>
                    <style>
                        body {{
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                            max-width: 800px;
                            margin: 50px auto;
                            padding: 20px;
                        }}
                        .header {{
                            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                            color: white;
                            padding: 30px;
                            border-radius: 10px;
                            margin-bottom: 30px;
                        }}
                        .info {{
                            background: #f7fafc;
                            padding: 20px;
                            border-radius: 8px;
                            margin-bottom: 20px;
                        }}
                        .button {{
                            display: inline-block;
                            background: #667eea;
                            color: white;
                            padding: 12px 24px;
                            border-radius: 6px;
                            text-decoration: none;
                            font-weight: 500;
                            transition: background 0.2s;
                        }}
                        .button:hover {{
                            background: #5a67d8;
                        }}
                    </style>
                </head>
                <body>
                    <div class="header">
                        <h1>Welcome to Vidya AI!</h1>
                        <p>AI-Powered Assignment Generation</p>
                    </div>
                    <div class="info">
                        <h2>Course: {course_name}</h2>
                        <p><strong>Instructor:</strong> {user_name}</p>
                        <p><strong>Email:</strong> {user_email}</p>
                    </div>
                    <a href="{BASE_URL}/assignment-generator?course_id={course_id}&lti_session={launch_id}" class="button">
                        Create New Assignment
                    </a>
                </body>
                </html>
            """)
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"LTI Launch failed: {str(e)}")


@router.post("/deeplink/response")
async def deeplink_response(request: Request):
    """
    Send generated assignment back to Canvas via Deep Linking.
    This is called when professor clicks "Add to Canvas" after generating assignment.
    """
    
    try:
        data = await request.json()
        
        # Get the LTI session
        lti_session_id = data.get('lti_session')
        
        # Reconstruct message launch from session
        message_launch = MessageLaunch.from_cache(lti_session_id, request, tool_conf)
        
        # Create Deep Link response
        deep_link = DeepLink(message_launch)
        
        # Get the generated assignment data
        assignment_data = data.get('assignment')
        
        # Create resource for Canvas
        resource = deep_link.create_resource_link(
            title=assignment_data.get('title', 'Vidya AI Assignment'),
            text=assignment_data.get('description', ''),
            custom_params={
                'assignment_id': assignment_data.get('id'),
                'total_points': assignment_data.get('total_points', 100),
                'question_count': len(assignment_data.get('questions', []))
            }
        )
        
        # Add submission configuration (students submit via external tool)
        resource.set_submission({
            'submission_type': 'external_tool',
            'submission_url': f"{BASE_URL}/assignment/submit/{assignment_data.get('id')}"
        })
        
        # Return Deep Link form that auto-submits to Canvas
        return HTMLResponse(content=deep_link.output_response_form([resource]))
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Deep Link response failed: {str(e)}")
```

### Update main.py

**Add the LTI router to your main FastAPI app:**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from controllers.lti import router as lti_router
# ... your other imports

app = FastAPI()

# CORS configuration for Canvas
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://*.instructure.com",  # All Canvas instances
        "https://api.vidyaai.co",     # Your domain
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include LTI router
app.include_router(lti_router)

# ... your other routers
```

---

## Phase 6: Modify Assignment Generator UI

### Option A: If Using React/Vue Frontend

**Update your assignment generator component to accept Canvas context:**

```javascript
// AssignmentGenerator.jsx

import { useEffect, useState } from 'react';

function AssignmentGenerator() {
    const [canvasContext, setCanvasContext] = useState(null);
    const [generatedAssignment, setGeneratedAssignment] = useState(null);
    
    useEffect(() => {
        // Get Canvas context from URL parameters
        const params = new URLSearchParams(window.location.search);
        
        const context = {
            courseId: params.get('course_id'),
            courseName: params.get('course_name'),
            userId: params.get('user_id'),
            userName: params.get('user_name'),
            userEmail: params.get('user_email'),
            isInstructor: params.get('is_instructor') === 'true',
            ltiSession: params.get('lti_session')
        };
        
        setCanvasContext(context);
    }, []);
    
    const generateAssignment = async (formData) => {
        // Call your existing assignment generation API
        const response = await fetch('/api/assignment/generate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(formData)
        });
        
        const assignment = await response.json();
        setGeneratedAssignment(assignment);
    };
    
    const addToCanvas = async () => {
        if (!generatedAssignment || !canvasContext?.ltiSession) {
            alert('Missing assignment or Canvas session');
            return;
        }
        
        // Send assignment to Canvas via Deep Link
        const response = await fetch('/lti/deeplink/response', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                lti_session: canvasContext.ltiSession,
                assignment: generatedAssignment
            })
        });
        
        // Get the auto-submit form from response
        const formHtml = await response.text();
        
        // Replace page content with form and submit
        document.body.innerHTML = formHtml;
        document.forms[0].submit();
    };
    
    return (
        <div className="assignment-generator">
            {canvasContext && (
                <div className="canvas-context">
                    <h2>Course: {canvasContext.courseName}</h2>
                    <p>Instructor: {canvasContext.userName}</p>
                </div>
            )}
            
            {/* Your existing assignment generation form */}
            <form onSubmit={(e) => {
                e.preventDefault();
                generateAssignment({
                    // your form data
                });
            }}>
                {/* Your form fields */}
                <button type="submit">Generate Assignment</button>
            </form>
            
            {/* Show generated assignment preview */}
            {generatedAssignment && (
                <div className="assignment-preview">
                    <h3>{generatedAssignment.title}</h3>
                    <p>{generatedAssignment.description}</p>
                    <p>Questions: {generatedAssignment.questions?.length}</p>
                    <p>Total Points: {generatedAssignment.total_points}</p>
                    
                    {canvasContext?.ltiSession && (
                        <button onClick={addToCanvas} className="add-to-canvas-btn">
                            Add to Canvas
                        </button>
                    )}
                </div>
            )}
        </div>
    );
}

export default AssignmentGenerator;
```

### Option B: If Using Plain HTML/JavaScript

**Create: `templates/assignment_generator.html`**

```html
<!DOCTYPE html>
<html>
<head>
    <title>Vidya AI - Generate Assignment</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f7fafc;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
        }
        .canvas-info {
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .form-section {
            background: white;
            padding: 30px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 500;
            color: #2d3748;
        }
        input[type="file"],
        textarea,
        select {
            width: 100%;
            padding: 10px;
            border: 1px solid #cbd5e0;
            border-radius: 6px;
            font-size: 14px;
        }
        textarea {
            min-height: 100px;
            resize: vertical;
        }
        .button {
            background: #667eea;
            color: white;
            padding: 12px 24px;
            border: none;
            border-radius: 6px;
            font-size: 16px;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s;
        }
        .button:hover {
            background: #5a67d8;
        }
        .button:disabled {
            background: #cbd5e0;
            cursor: not-allowed;
        }
        .preview {
            background: white;
            padding: 30px;
            border-radius: 8px;
            margin-top: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            display: none;
        }
        .preview.show {
            display: block;
        }
        .question-item {
            background: #f7fafc;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 15px;
        }
        .loading {
            text-align: center;
            padding: 40px;
        }
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Vidya AI Assignment Generator</h1>
        <p>Create AI-powered assignments for your Canvas course</p>
    </div>
    
    <div class="canvas-info" id="canvas-info">
        <h2 id="course-name">Loading...</h2>
        <p><strong>Instructor:</strong> <span id="user-name"></span></p>
    </div>
    
    <div class="form-section">
        <h2>Generate Assignment</h2>
        <form id="assignment-form">
            <div class="form-group">
                <label>Assignment Title:</label>
                <input type="text" id="title" placeholder="e.g., Midterm Exam - Data Structures" required>
            </div>
            
            <div class="form-group">
                <label>Upload Question Paper or Course Material (Optional):</label>
                <input type="file" id="document" accept=".pdf,.docx,.txt">
            </div>
            
            <div class="form-group">
                <label>Or Describe Assignment Topic:</label>
                <textarea id="topic" placeholder="e.g., Create questions on Binary Search Trees, Graph Algorithms, and Dynamic Programming"></textarea>
            </div>
            
            <div class="form-group">
                <label>Number of Questions:</label>
                <select id="num_questions">
                    <option value="5">5 Questions</option>
                    <option value="10" selected>10 Questions</option>
                    <option value="15">15 Questions</option>
                    <option value="20">20 Questions</option>
                </select>
            </div>
            
            <div class="form-group">
                <label>Difficulty Level:</label>
                <select id="difficulty">
                    <option value="easy">Easy</option>
                    <option value="medium" selected>Medium</option>
                    <option value="hard">Hard</option>
                </select>
            </div>
            
            <button type="submit" class="button" id="generate-btn">Generate Assignment</button>
        </form>
    </div>
    
    <div id="loading" class="loading" style="display: none;">
        <div class="spinner"></div>
        <p>Generating your assignment...</p>
    </div>
    
    <div class="preview" id="preview">
        <h2>Generated Assignment Preview</h2>
        <div id="assignment-preview"></div>
        <button id="add-to-canvas-btn" class="button">Add to Canvas Course</button>
    </div>
    
    <script>
        // Get Canvas context from URL
        const params = new URLSearchParams(window.location.search);
        const canvasContext = {
            courseId: params.get('course_id'),
            courseName: params.get('course_name'),
            userId: params.get('user_id'),
            userName: params.get('user_name'),
            userEmail: params.get('user_email'),
            isInstructor: params.get('is_instructor') === 'true',
            ltiSession: params.get('lti_session')
        };
        
        // Display Canvas context
        document.getElementById('course-name').textContent = canvasContext.courseName || 'Unknown Course';
        document.getElementById('user-name').textContent = canvasContext.userName || 'Unknown User';
        
        // Store generated assignment globally
        let generatedAssignment = null;
        
        // Form submission
        document.getElementById('assignment-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            // Show loading
            document.getElementById('loading').style.display = 'block';
            document.getElementById('preview').classList.remove('show');
            
            // Prepare form data
            const formData = new FormData();
            
            const documentFile = document.getElementById('document').files[0];
            if (documentFile) {
                formData.append('file', documentFile);
            }
            
            const requestData = {
                title: document.getElementById('title').value,
                topic: document.getElementById('topic').value,
                num_questions: parseInt(document.getElementById('num_questions').value),
                difficulty: document.getElementById('difficulty').value,
                course_id: canvasContext.courseId,
                instructor_id: canvasContext.userId
            };
            
            try {
                // Call your existing assignment generation API
                const response = await fetch('/api/assignment/generate', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(requestData)
                });
                
                if (!response.ok) {
                    throw new Error('Failed to generate assignment');
                }
                
                const assignment = await response.json();
                generatedAssignment = assignment;
                
                // Display preview
                displayAssignmentPreview(assignment);
                
                // Hide loading, show preview
                document.getElementById('loading').style.display = 'none';
                document.getElementById('preview').classList.add('show');
                
            } catch (error) {
                console.error('Error:', error);
                alert('Failed to generate assignment: ' + error.message);
                document.getElementById('loading').style.display = 'none';
            }
        });
        
        // Display assignment preview
        function displayAssignmentPreview(assignment) {
            const previewDiv = document.getElementById('assignment-preview');
            
            let html = `
                <h3>${assignment.title}</h3>
                <p><strong>Description:</strong> ${assignment.description || 'No description'}</p>
                <p><strong>Total Questions:</strong> ${assignment.questions?.length || 0}</p>
                <p><strong>Total Points:</strong> ${assignment.total_points || 0}</p>
                <hr>
                <h4>Questions:</h4>
            `;
            
            if (assignment.questions && assignment.questions.length > 0) {
                assignment.questions.forEach((q, index) => {
                    html += `
                        <div class="question-item">
                            <strong>Q${index + 1}.</strong> ${q.question}
                            <br><small>Type: ${q.type} | Points: ${q.points}</small>
                        </div>
                    `;
                });
            }
            
            previewDiv.innerHTML = html;
        }
        
        // Add to Canvas button
        document.getElementById('add-to-canvas-btn').addEventListener('click', async () => {
            if (!generatedAssignment || !canvasContext.ltiSession) {
                alert('Missing assignment or Canvas session');
                return;
            }
            
            try {
                // Send to Canvas via Deep Link
                const response = await fetch('/lti/deeplink/response', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        lti_session: canvasContext.ltiSession,
                        assignment: generatedAssignment
                    })
                });
                
                if (!response.ok) {
                    throw new Error('Failed to add to Canvas');
                }
                
                // Get the auto-submit form from response
                const formHtml = await response.text();
                
                // Replace page content with form and submit
                document.body.innerHTML = formHtml;
                document.forms[0].submit();
                
            } catch (error) {
                console.error('Error:', error);
                alert('Failed to add assignment to Canvas: ' + error.message);
            }
        });
    </script>
</body>
</html>
```

---

## Phase 7: Configure Canvas Developer Key

### Step 1: Create Developer Key in Canvas

1. In Canvas, click: **"Admin"** (left menu)
2. Click: **"Developer Keys"**
3. Click: **"+ Developer Key"** → **"LTI Key"**

### Step 2: Fill in Configuration

**Key Name:** `Vidya AI Assignment Generator`

**Owner Email:** Your email

**Redirect URIs:**
- Development: `https://abc123.ngrok.io/lti/launch`
- Production: `https://api.vidyaai.co/lti/launch`

**Method:** Manual Entry

**Title:** `Vidya AI`

**Target Link URI:**
- Development: `https://abc123.ngrok.io/lti/launch`
- Production: `https://api.vidyaai.co/lti/launch`

**OpenID Connect Initiation Url:**
- Development: `https://abc123.ngrok.io/lti/login`
- Production: `https://api.vidyaai.co/lti/login`

**JWK Method:** Public JWK URL

**Public JWK URL:**
- Development: `https://abc123.ngrok.io/lti/jwks`
- Production: `https://api.vidyaai.co/lti/jwks`

**LTI Advantage Services:**
- ✅ Can create and view assignment data in the gradebook (for future grade passback)
- ✅ Can view assignment data in the gradebook
- ✅ Can create and update assignment data in the gradebook

**Additional Settings:**
- **Domain:** (leave blank or use your domain)
- **Privacy Level:** Public
- **Placements:** Assignment Selection, Course Navigation

### Step 3: Save and Get Credentials

1. Click: **"Save"**
2. **Copy the Client ID** (looks like: `10000000000001`)
3. Click the toggle to turn the key **"ON"** (green)
4. Click the key again to view details
5. **Copy the Deployment ID** (looks like: `1:abc123def456`)

### Step 4: Update Your Configuration

**Edit `lti_config.development.json` or `lti_config.production.json`:**

```json
{
  "https://yourname.instructure.com": {
    "client_id": "10000000000001",  // ← PASTE YOUR CLIENT ID HERE
    "auth_login_url": "https://yourname.instructure.com/api/lti/authorize_redirect",
    "auth_token_url": "https://yourname.instructure.com/login/oauth2/token",
    "key_set_url": "https://yourname.instructure.com/api/lti/security/jwks",
    "deployment_ids": ["1:abc123def456"],  // ← PASTE YOUR DEPLOYMENT ID HERE
    "private_key_file": "private.key",
    "public_key_file": "public.key"
  }
}
```

---

## Phase 8: Install Tool in Canvas Course

### Step 1: Navigate to Course Settings

1. Go to your test course in Canvas
2. Click: **"Settings"** (left menu)
3. Click: **"Apps"** tab
4. Click: **"+ App"** button

### Step 2: Add External Tool

**Configuration Type:** By Client ID

**Client ID:** (paste the Client ID from Developer Key)

**Submit URL:** (leave blank - not needed for LTI 1.3)

Click: **"Submit"**

### Step 3: Verify Installation

You should see "Vidya AI Assignment Generator" in the list of installed apps.

**Status should be:** Active ✅

---

## Phase 9: Testing

### Test 1: Launch Tool from Canvas

1. In your Canvas course, click: **"Assignments"** (left menu)
2. Click: **"+ Assignment"**
3. Give it a name: "Test Assignment"
4. Set points (e.g., 100)
5. Click: **"Submission Type"** dropdown
6. Select: **"External Tool"**
7. Click: **"Find"** button
8. Find and click: **"Vidya AI Assignment Generator"**
9. Click: **"Select"**

**What should happen:**
- Canvas redirects to your app (ngrok URL or api.vidyaai.co)
- Your assignment generator UI loads
- Shows course name and instructor name at top

**If it fails:**
- Check ngrok is running (development)
- Check your server logs for errors
- Verify Client ID and Deployment ID in config
- Check `/lti/login` and `/lti/launch` endpoints are accessible

### Test 2: Generate Assignment

1. In your UI, fill in the form:
   - Title: "Test Assignment - Data Structures"
   - Topic: "Binary Search Trees and Graph Algorithms"
   - Number of Questions: 10
   - Difficulty: Medium

2. Click: **"Generate Assignment"**

3. Wait for generation (your existing API endpoint)

4. Preview should show generated assignment

**What should happen:**
- Assignment generates successfully
- Preview shows title, questions, points
- "Add to Canvas" button appears

### Test 3: Add to Canvas

1. Click: **"Add to Canvas"** button

**What should happen:**
- Page auto-redirects back to Canvas
- Assignment appears in your Canvas course
- Assignment has the title and points you specified
- Students will see this assignment

### Test 4: View as Student

1. In Canvas, click your avatar (top right)
2. Click: **"Act as User"**
3. Enter: `student1@test.com`
4. Click: **"Proceed"**
5. Go to **"Assignments"**
6. You should see the assignment you created

---

## Phase 10: Production Deployment Checklist

### Pre-Deployment

- [ ] Test thoroughly in development (Canvas Free-for-Teacher)
- [ ] All endpoints working (login, launch, jwks, deeplink)
- [ ] Assignment generation working end-to-end
- [ ] Test with multiple question types (MCQ, short answer, etc.)
- [ ] Test with equations and diagrams
- [ ] Error handling implemented

### Security

- [ ] `private.key` added to `.gitignore`
- [ ] Environment variables set on EC2
- [ ] HTTPS enabled (SSL certificate valid)
- [ ] CORS configured properly
- [ ] Rate limiting on endpoints (optional but recommended)

### Production Configuration

- [ ] Update `API_BASE_URL` to `https://api.vidyaai.co`
- [ ] Update all LTI config files to production URLs
- [ ] Test `/lti/config.xml` endpoint is accessible
- [ ] Test `/lti/jwks` endpoint is accessible
- [ ] Verify nginx/apache reverse proxy configured

### Canvas Configuration

- [ ] Create production Developer Keys for each institution
- [ ] Document installation process for IT admins
- [ ] Create support documentation
- [ ] Privacy policy created and linked
- [ ] Terms of service created and linked

### Monitoring

- [ ] Logging implemented for LTI launches
- [ ] Error tracking (Sentry, CloudWatch, etc.)
- [ ] Usage analytics
- [ ] Performance monitoring

---

## Phase 11: Edu App Center Submission

### Prerequisites

1. **Working Production Installation**
   - At least 1 real institution using it successfully
   - Or comprehensive testing in Canvas Free-for-Teacher

2. **Required Documents**
   - Privacy Policy
   - Terms of Service
   - Support documentation
   - Installation guide for IT admins

3. **Screenshots**
   - Tool installation in Canvas
   - Assignment generation workflow
   - Student view of assignment
   - Error handling examples

### Submission Process

1. Go to: https://www.eduappcenter.com
2. Click: **"Submit an App"**
3. Fill in application:

**Basic Information:**
- **App Name:** Vidya AI Assignment Generator
- **Category:** Assessment, Course Content
- **Configuration URL:** `https://api.vidyaai.co/lti/config.xml`
- **Description:** "AI-powered assignment and question paper generation for STEM courses. Automatically create assignments from course materials, syllabus, or topic descriptions."

**Support Information:**
- **Support Email:** your-support-email@vidyaai.co
- **Documentation URL:** Link to your docs
- **Privacy Policy URL:** Link to privacy policy
- **Terms of Service URL:** Link to TOS

**Technical Information:**
- **LTI Version:** 1.3
- **Supported Placements:** Assignment Selection, Course Navigation
- **Required Services:** Deep Linking, Assignment and Grade Services (AGS)

**Uploads:**
- Screenshots of your tool in action
- Logo (high resolution)
- Company information

4. Submit for review

**Review Timeline:** 1-3 weeks typically

---

## Troubleshooting Guide

### Common Issues

#### 1. "Invalid launch request"

**Symptoms:** Error when trying to launch tool from Canvas

**Causes:**
- Incorrect Client ID or Deployment ID
- JWT signature verification failed
- Clock skew between servers

**Solutions:**
- Verify Client ID and Deployment ID in `lti_config.json`
- Check server time is synchronized (NTP)
- Verify public key is accessible at `/lti/jwks`

#### 2. "JWKS not found"

**Symptoms:** Canvas can't verify your signatures

**Solutions:**
- Test endpoint: `curl https://api.vidyaai.co/lti/jwks`
- Verify `public.key` file exists and is readable
- Check file permissions on public.key

#### 3. "Deep Link failed"

**Symptoms:** Assignment doesn't appear in Canvas after clicking "Add to Canvas"

**Solutions:**
- Verify LTI session is being passed correctly
- Check Deep Link response format
- Look for JavaScript console errors
- Verify CORS headers are set

#### 4. Canvas shows blank page

**Symptoms:** White screen when launching tool

**Solutions:**
- Check browser console for errors
- Verify CORS headers include Canvas domain
- Check `/lti/launch` endpoint logs
- Ensure iframe embedding is allowed

#### 5. Assignment appears but has no content

**Symptoms:** Assignment created but empty

**Solutions:**
- Verify Deep Link resource includes all required fields
- Check that assignment data is properly formatted
- Look at Canvas assignment settings

### Debugging Tips

**Enable Verbose Logging:**

```python
import logging

logging.basicConfig(level=logging.DEBUG)

@router.post("/lti/launch")
async def lti_launch(request: Request):
    body = await request.body()
    logging.debug(f"LTI Launch received: {body}")
    # ... rest of code
```

**Check Canvas Logs:**

1. In Canvas, go to: **Settings** → **Developer Keys**
2. Click your key
3. View launch logs

**Test Endpoints Manually:**

```bash
# Test config XML
curl https://api.vidyaai.co/lti/config.xml

# Test JWKS
curl https://api.vidyaai.co/lti/jwks

# Check if endpoints are accessible from internet
curl -I https://api.vidyaai.co/lti/launch
```

---

## Multi-Institution Support

### Configuration Strategy

Each institution gets their own entry in `lti_config.production.json`:

```json
{
  "https://stanford.instructure.com": {
    "client_id": "STANFORD_CLIENT_ID",
    "auth_login_url": "https://stanford.instructure.com/api/lti/authorize_redirect",
    "auth_token_url": "https://stanford.instructure.com/login/oauth2/token",
    "key_set_url": "https://stanford.instructure.com/api/lti/security/jwks",
    "deployment_ids": ["STANFORD_DEPLOYMENT_1", "STANFORD_DEPLOYMENT_2"],
    "private_key_file": "private.key",
    "public_key_file": "public.key"
  },
  "https://mit.instructure.com": {
    "client_id": "MIT_CLIENT_ID",
    "auth_login_url": "https://mit.instructure.com/api/lti/authorize_redirect",
    "auth_token_url": "https://mit.instructure.com/login/oauth2/token",
    "key_set_url": "https://mit.instructure.com/api/lti/security/jwks",
    "deployment_ids": ["MIT_DEPLOYMENT_ID"],
    "private_key_file": "private.key",
    "public_key_file": "public.key"
  }
}
```

### Installation Process for New Institutions

1. **Institution IT admin contacts you**
2. **They provide:**
   - Canvas instance URL (e.g., `harvard.instructure.com`)
   - Your config URL: `https://api.vidyaai.co/lti/config.xml`
3. **They create Developer Key in their Canvas:**
   - Follow same steps as Phase 7
   - They get Client ID and Deployment ID
4. **They send you:**
   - Client ID
   - Deployment ID
   - Canvas instance URL
5. **You add to `lti_config.production.json`**
6. **Restart your server**
7. **They install tool in their courses**

---

## Environment Variables Reference

### Required Environment Variables

```bash
# Environment (development or production)
ENVIRONMENT=production

# Base URL for LTI endpoints
API_BASE_URL=https://api.vidyaai.co

# Database (your existing)
DATABASE_URL=your_database_url

# Firebase (your existing)
FIREBASE_CONFIG=your_firebase_config

# AWS S3 (your existing)
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_S3_BUCKET=your_bucket

# OpenAI (your existing)
OPENAI_API_KEY=your_openai_key
```

### .env.development Example

```bash
ENVIRONMENT=development
API_BASE_URL=https://abc123.ngrok.io
DATABASE_URL=postgresql://localhost/vidyaai_dev
# ... other vars
```

### .env.production Example

```bash
ENVIRONMENT=production
API_BASE_URL=https://api.vidyaai.co
DATABASE_URL=postgresql://prod-db/vidyaai
# ... other vars
```

---

## File Checklist

### New Files to Create

```
✅ controllers/lti.py
✅ lti_config.development.json
✅ lti_config.production.json
✅ private.key (generated)
✅ public.key (generated)
✅ templates/assignment_generator.html (if not using React)
✅ .env.development
✅ .env.production
```

### Modified Files

```
✅ main.py (add LTI router and CORS)
✅ .gitignore (add private.key, *.env)
✅ requirements.txt (add pylti1p3, pyjwt, cryptography)
```

### Files to Keep Secret

```
⚠️ private.key - NEVER commit to git
⚠️ .env.production - NEVER commit to git
⚠️ lti_config.production.json - Contains sensitive client IDs
```

---

## Timeline Summary

### Week 1: Setup & Development
- Day 1-2: Create Canvas account, generate keys, install dependencies
- Day 3-4: Implement LTI endpoints
- Day 5-7: Test in Canvas Free-for-Teacher

### Week 2: Integration & Testing
- Day 1-2: Modify assignment generator UI
- Day 3-4: End-to-end testing
- Day 5-7: Fix bugs, polish UI

### Week 3: Production Prep
- Day 1-2: Deploy to production EC2
- Day 3-4: Test in production environment
- Day 5-7: Create documentation

### Week 4: Launch
- Day 1-2: Submit to Edu App Center
- Day 3-7: Onboard first institution (if you have one)

**Total: 3-4 weeks to production-ready**

---

## Next Steps After LTI Integration

### Phase 2: Grade Passback (Future)
- Implement Assignment and Grade Services (AGS)
- Send student scores back to Canvas gradebook
- Handle late submissions, retakes

### Phase 3: Additional Features
- Names and Roles service (roster sync)
- Canvas file picker integration
- Canvas rich content editor integration
- Mobile app support

### Phase 4: Scale
- Multi-tenant database architecture
- Institution-specific customizations
- SLA commitments for enterprise
- Dedicated support channels

---

## Support Resources

### Documentation Links

- **Canvas LTI 1.3 Docs:** https://canvas.instructure.com/doc/api/file.lti_dev_key_config.html
- **IMS Global LTI Spec:** https://www.imsglobal.org/spec/lti/v1p3/
- **pylti1p3 Docs:** https://github.com/dmitry-viskov/pylti1p3
- **Canvas Developer Portal:** https://community.canvaslms.com/community/developers

### Community Support

- Canvas Community: https://community.canvaslms.com/
- IMS Global Forums: https://www.imsglobal.org/forums
- Stack Overflow: Tag `canvas-lms` and `lti`

### Getting Help

For implementation questions:
1. Check Canvas LTI documentation first
2. Review pylti1p3 examples
3. Post in Canvas Community Developer forum
4. Canvas has excellent support for LTI integrations

---

## Appendix: Complete Code Reference

All code examples are provided in the sections above. Key files:

1. **controllers/lti.py** - Complete LTI implementation
2. **lti_config.json templates** - Canvas configuration
3. **assignment_generator.html** - UI integration
4. **main.py modifications** - CORS and router setup

Refer to Phase 5 and Phase 6 for complete, copy-paste ready code.

---

## Success Criteria

✅ **Development Success:**
- Tool launches from Canvas Free-for-Teacher
- Assignment generates successfully
- Assignment appears in Canvas course
- Students can view assignment

✅ **Production Success:**
- Deployed to api.vidyaai.co
- Working with at least 1 real institution
- Edu App Center listing approved
- Documentation complete

✅ **Scale Success:**
- 5+ institutions using it
- 100+ assignments created
- Positive feedback from professors
- Minimal support tickets

---

## End of Guide

This guide covers everything you need to integrate Vidya AI's assignment generation with Canvas LMS using LTI 1.3. Start with Phase 1 (test environment) and work through each phase sequentially.

**Good luck with your integration! 🚀**

For questions or clarifications, refer to the troubleshooting section or Canvas LTI documentation.
