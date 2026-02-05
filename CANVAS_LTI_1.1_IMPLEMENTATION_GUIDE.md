# Canvas LTI 1.1 Implementation Guide - Per-Course Installation

## Overview

This guide implements LTI 1.1 alongside your existing LTI 1.3 integration to enable **instructors to install Vidya AI directly into their courses WITHOUT requiring Canvas admin approval**.

### Why Add LTI 1.1?

**LTI 1.3 (Current Implementation):**
- ✅ Modern, secure (OAuth 2.0 + JWT)
- ✅ Deep Linking (creates assignments in Canvas)
- ✅ Grade Passback (AGS)
- ❌ Requires Canvas admin to create Developer Key
- ❌ Instructors must wait for approval

**LTI 1.1 (This Implementation):**
- ✅ Instructors can install in 5 minutes
- ✅ No admin approval needed
- ✅ Works immediately for pilots
- ❌ Less secure (OAuth 1.0)
- ❌ No native Deep Linking
- ⚠️ Being phased out (but still widely supported)

### Strategy: Dual Support

Both LTI versions will coexist:
- **LTI 1.1** - Quick pilots, individual instructors
- **LTI 1.3** - Full institutional deployments

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Canvas LMS                                │
│                                                              │
│  Instructor clicks "Create using Vidya AI"                  │
│         │                                                    │
│         ├─> LTI 1.1 Launch (OAuth 1.0 signature)            │
│         │   POST /lti/v1/launch                             │
│         │                                                    │
│         └─> LTI 1.3 Launch (JWT token)                      │
│             POST /lti/launch                                 │
└─────────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              Vidya AI Backend (FastAPI)                      │
│                                                              │
│  /lti/v1/login      - OAuth 1.0 signature verification      │
│  /lti/v1/launch     - Create session, redirect to frontend  │
│  /lti/v1/config.xml - Canvas configuration XML              │
│  /lti/v1/return     - Return generated assignment           │
└─────────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│          Frontend (Next.js)                                  │
│                                                              │
│  /canvas-assignment-generator                                │
│  - Works with both LTI 1.1 and 1.3 sessions                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Checklist

### Backend Changes
- [ ] Install dependencies (`oauthlib`)
- [ ] Create LTI 1.1 controller (`src/controllers/lti_v1.py`)
- [ ] Create LTI 1.1 models (database table)
- [ ] Create configuration XML generator
- [ ] Add routes to main.py
- [ ] Create consumer key/secret management
- [ ] Update CORS settings

### Frontend Changes
- [ ] Update assignment generator to handle LTI 1.1 sessions
- [ ] Create assignment return flow (no Deep Linking)

### Configuration
- [ ] Create consumer keys database/config
- [ ] Create XML configuration template
- [ ] Update environment variables

### Testing
- [ ] Test OAuth 1.0 signature verification
- [ ] Test launch flow
- [ ] Test assignment generation
- [ ] Test return flow
- [ ] Test in real Canvas course

---

## Step 1: Backend Implementation

### 1.1 Install Dependencies

**File: `vidya_ai_backend/requirements.txt`**

Add:
```txt
oauthlib==3.2.2
```

Install:
```bash
cd vidya_ai_backend
pip install oauthlib==3.2.2 --break-system-packages
```

---

### 1.2 Create Database Models

**File: `vidya_ai_backend/src/models.py`**

Add this model to your existing models file:

```python
class LTI11Session(Base):
    """
    LTI 1.1 session data

    Unlike LTI 1.3, we store minimal session data since
    there's no complex OAuth 2.0 flow
    """
    __tablename__ = "lti11_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Canvas context
    consumer_key = Column(String, nullable=False)  # Identifies the Canvas instance
    course_id = Column(String, nullable=False)     # Canvas course ID
    course_name = Column(String)

    # User info
    user_id = Column(String, nullable=False)       # Canvas user ID
    user_email = Column(String)
    user_name = Column(String)
    user_roles = Column(String)  # Comma-separated roles

    # Assignment context (if launched from assignment)
    assignment_id = Column(String)
    assignment_name = Column(String)

    # Return URL for sending back assignment
    launch_presentation_return_url = Column(String)

    # OAuth parameters from launch
    resource_link_id = Column(String)
    resource_link_title = Column(String)

    # Session management
    session_token = Column(String, unique=True, nullable=False)  # For frontend
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    used = Column(Boolean, default=False)

    # Canvas API access (if Canvas provides API token)
    canvas_api_token = Column(String)
    canvas_instance_url = Column(String)

    __table_args__ = (
        Index('idx_session_token', 'session_token'),
        Index('idx_course_user', 'course_id', 'user_id'),
    )
```

**Create migration:**
```bash
cd vidya_ai_backend
alembic revision --autogenerate -m "Add LTI 1.1 session table"
alembic upgrade head
```

---

### 1.3 Create Consumer Key Configuration

**File: `vidya_ai_backend/lti_v1_consumers.json`**

Create this configuration file for managing consumer keys and secrets:

```json
{
  "consumers": [
    {
      "consumer_key": "vidyaai-lti-default",
      "shared_secret": "CHANGE_THIS_SECRET_IN_PRODUCTION",
      "description": "Default consumer key for course-level installations",
      "enabled": true,
      "created_at": "2026-01-11"
    }
  ],
  "default_consumer": "vidyaai-lti-default"
}
```

**IMPORTANT:** In production, generate secure secrets:
```python
import secrets
secret = secrets.token_urlsafe(32)
print(secret)  # Use this as shared_secret
```

**Add to `.gitignore`:**
```
lti_v1_consumers.json
```

---

### 1.4 Create LTI 1.1 Controller

**File: `vidya_ai_backend/src/controllers/lti_v1.py`**

```python
"""
LTI 1.1 Controller for Vidya AI

This implements Learning Tools Interoperability (LTI) 1.1 standard
for Canvas LMS integration at the course level.

LTI 1.1 allows instructors to install Vidya AI in their courses
WITHOUT requiring Canvas admin approval.

Key Differences from LTI 1.3:
- Uses OAuth 1.0 signature verification (vs OAuth 2.0 + JWT)
- No Deep Linking (cannot create assignments programmatically)
- Simpler flow but less secure
- Being phased out but still widely supported

Flow:
1. Instructor adds Vidya AI to Canvas course (via XML/URL/Manual)
2. Student/Instructor clicks "Create using Vidya AI"
3. Canvas sends LTI launch POST to /lti/v1/launch
4. We verify OAuth 1.0 signature
5. Create session and redirect to frontend
6. Frontend generates assignment
7. Return to Canvas (via launch_presentation_return_url)
"""

import json
import logging
import hashlib
import hmac
import base64
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from urllib.parse import quote, unquote, parse_qsl, urlencode

from fastapi import APIRouter, Request, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from sqlalchemy.orm import Session
from oauthlib.oauth1 import SignatureOnlyEndpoint
from oauthlib.oauth1.rfc5849 import signature

from ..database import get_db
from ..models import LTI11Session
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lti/v1", tags=["lti-1.1"])

# Load consumer keys
try:
    with open("lti_v1_consumers.json", "r") as f:
        CONSUMER_CONFIG = json.load(f)
except FileNotFoundError:
    logger.warning("lti_v1_consumers.json not found, using default consumer")
    CONSUMER_CONFIG = {
        "consumers": [
            {
                "consumer_key": "vidyaai-lti-default",
                "shared_secret": "CHANGE_THIS_SECRET",
                "description": "Default consumer",
                "enabled": True
            }
        ],
        "default_consumer": "vidyaai-lti-default"
    }


def get_consumer_secret(consumer_key: str) -> Optional[str]:
    """Get shared secret for a consumer key"""
    for consumer in CONSUMER_CONFIG["consumers"]:
        if consumer["consumer_key"] == consumer_key and consumer["enabled"]:
            return consumer["shared_secret"]
    return None


def verify_oauth_signature(
    request: Request,
    body: Dict[str, str]
) -> bool:
    """
    Verify OAuth 1.0 signature from Canvas LTI launch

    Canvas signs the LTI launch request using OAuth 1.0 signature.
    We verify this signature to ensure the request is authentic.

    Args:
        request: FastAPI request object
        body: Form data from POST request

    Returns:
        True if signature is valid, False otherwise
    """
    try:
        # Get consumer key and secret
        consumer_key = body.get("oauth_consumer_key")
        if not consumer_key:
            logger.error("Missing oauth_consumer_key in LTI launch")
            return False

        consumer_secret = get_consumer_secret(consumer_key)
        if not consumer_secret:
            logger.error(f"Unknown consumer key: {consumer_key}")
            return False

        # Build the base string for signature verification
        # OAuth 1.0 signature = HMAC-SHA1(base_string, consumer_secret&)

        # Get HTTP method
        http_method = request.method.upper()

        # Get base URL (without query parameters)
        base_url = str(request.url).split('?')[0]

        # Collect all parameters (OAuth + LTI)
        params = {}
        for key, value in body.items():
            if isinstance(value, str):
                params[key] = value

        # Remove signature from parameters
        params.pop('oauth_signature', None)

        # Sort parameters
        sorted_params = sorted(params.items())

        # Create parameter string
        param_string = "&".join([
            f"{quote(str(k), safe='')}={quote(str(v), safe='')}"
            for k, v in sorted_params
        ])

        # Create base string
        base_string = "&".join([
            quote(http_method, safe=''),
            quote(base_url, safe=''),
            quote(param_string, safe='')
        ])

        # Create signature key (consumer_secret&token_secret)
        # In LTI, there's no token_secret, so key is just consumer_secret&
        signing_key = f"{quote(consumer_secret, safe='')}&"

        # Calculate signature
        calculated_signature = base64.b64encode(
            hmac.new(
                signing_key.encode('utf-8'),
                base_string.encode('utf-8'),
                hashlib.sha1
            ).digest()
        ).decode('utf-8')

        # Get signature from request
        provided_signature = body.get("oauth_signature", "")

        # Compare signatures
        is_valid = hmac.compare_digest(
            calculated_signature,
            provided_signature
        )

        if not is_valid:
            logger.error(
                f"OAuth signature verification failed\n"
                f"Expected: {calculated_signature}\n"
                f"Received: {provided_signature}\n"
                f"Base string: {base_string[:200]}..."
            )

        return is_valid

    except Exception as e:
        logger.error(f"Error verifying OAuth signature: {str(e)}", exc_info=True)
        return False


@router.get("/config.xml")
async def get_config_xml():
    """
    Returns LTI 1.1 configuration XML for Canvas

    Instructors can use this URL when adding Vidya AI to their course:
    Configuration Type: "By URL"
    Config URL: https://api.vidyaai.co/lti/v1/config.xml
    Consumer Key: vidyaai-lti-default
    Shared Secret: [provided separately]

    This XML tells Canvas:
    - Where to launch the tool (/lti/v1/launch)
    - What placements to use (Assignment Selection)
    - What information to send (user info, course info)
    """

    base_url = settings.API_BASE_URL

    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<cartridge_basiclti_link xmlns="http://www.imsglobal.org/xsd/imslticc_v1p0"
    xmlns:blti="http://www.imsglobal.org/xsd/imsbasiclti_v1p0"
    xmlns:lticm="http://www.imsglobal.org/xsd/imslticm_v1p0"
    xmlns:lticp="http://www.imsglobal.org/xsd/imslticp_v1p0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.imsglobal.org/xsd/imslticc_v1p0 http://www.imsglobal.org/xsd/lti/ltiv1p0/imslticc_v1p0.xsd
    http://www.imsglobal.org/xsd/imsbasiclti_v1p0 http://www.imsglobal.org/xsd/lti/ltiv1p0/imsbasiclti_v1p0p1.xsd
    http://www.imsglobal.org/xsd/imslticm_v1p0 http://www.imsglobal.org/xsd/lti/ltiv1p0/imslticm_v1p0.xsd
    http://www.imsglobal.org/xsd/imslticp_v1p0 http://www.imsglobal.org/xsd/lti/ltiv1p0/imslticp_v1p0.xsd">

    <blti:title>Vidya AI Assignment Generator</blti:title>
    <blti:description>Generate AI-powered assignments from your lecture notes. Create custom quizzes, problem sets, and assessments in minutes.</blti:description>
    <blti:launch_url>{base_url}/lti/v1/launch</blti:launch_url>
    <blti:secure_launch_url>{base_url}/lti/v1/launch</blti:secure_launch_url>
    <blti:icon>{base_url}/static/vidya-icon.png</blti:icon>

    <blti:extensions platform="canvas.instructure.com">
        <lticm:property name="privacy_level">public</lticm:property>
        <lticm:property name="domain">{base_url.replace('https://', '').replace('http://', '')}</lticm:property>

        <!-- Assignment Selection Placement -->
        <lticm:options name="assignment_selection">
            <lticm:property name="enabled">true</lticm:property>
            <lticm:property name="text">Create using Vidya AI</lticm:property>
            <lticm:property name="message_type">ContentItemSelectionRequest</lticm:property>
            <lticm:property name="url">{base_url}/lti/v1/launch</lticm:property>
            <lticm:property name="icon_url">{base_url}/static/vidya-icon.png</lticm:property>
        </lticm:options>

        <!-- Optional: Course Navigation Placement -->
        <lticm:options name="course_navigation">
            <lticm:property name="enabled">true</lticm:property>
            <lticm:property name="text">Vidya AI</lticm:property>
            <lticm:property name="visibility">admins</lticm:property>
            <lticm:property name="default">disabled</lticm:property>
            <lticm:property name="url">{base_url}/lti/v1/launch</lticm:property>
        </lticm:options>
    </blti:extensions>

    <cartridge_bundle identifierref="BLTI001_Bundle"/>
    <cartridge_icon identifierref="BLTI001_Icon"/>
</cartridge_basiclti_link>'''

    return Response(content=xml, media_type="application/xml")


@router.post("/launch")
async def lti_launch(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    LTI 1.1 Launch Endpoint

    This is where Canvas sends the LTI launch POST request when:
    1. Instructor clicks "Create using Vidya AI" in assignment creation
    2. User clicks Vidya AI link in course navigation

    LTI 1.1 Launch Parameters (from Canvas):
    - oauth_consumer_key: Identifies the Canvas instance
    - oauth_signature: OAuth 1.0 signature for verification
    - user_id: Canvas user ID
    - roles: User roles (Instructor, Student, etc.)
    - context_id: Course ID
    - context_title: Course name
    - resource_link_id: Unique ID for this link
    - launch_presentation_return_url: Where to return after tool use
    - lis_person_contact_email_primary: User email
    - lis_person_name_full: User full name

    Flow:
    1. Verify OAuth signature
    2. Extract user and course info
    3. Create session in database
    4. Redirect to frontend with session token
    """
    try:
        # Parse form data
        form_data = await request.form()
        launch_params = dict(form_data)

        # Log launch (without sensitive data)
        logger.info(
            f"LTI 1.1 Launch received from {launch_params.get('oauth_consumer_key')} "
            f"for course {launch_params.get('context_id')}"
        )

        # Verify OAuth 1.0 signature
        if not verify_oauth_signature(request, launch_params):
            logger.error("LTI 1.1 launch failed: Invalid OAuth signature")
            raise HTTPException(
                status_code=401,
                detail="Invalid OAuth signature. Please check your consumer key and shared secret."
            )

        # Extract required parameters
        consumer_key = launch_params.get("oauth_consumer_key")
        user_id = launch_params.get("user_id")
        course_id = launch_params.get("context_id")

        if not all([consumer_key, user_id, course_id]):
            logger.error(f"Missing required LTI parameters: {launch_params.keys()}")
            raise HTTPException(
                status_code=400,
                detail="Missing required LTI parameters"
            )

        # Generate session token
        import secrets
        session_token = secrets.token_urlsafe(32)

        # Create session
        session = LTI11Session(
            consumer_key=consumer_key,
            course_id=course_id,
            course_name=launch_params.get("context_title", "Unknown Course"),
            user_id=user_id,
            user_email=launch_params.get("lis_person_contact_email_primary"),
            user_name=launch_params.get("lis_person_name_full"),
            user_roles=launch_params.get("roles", ""),
            assignment_id=launch_params.get("custom_canvas_assignment_id"),
            assignment_name=launch_params.get("resource_link_title"),
            launch_presentation_return_url=launch_params.get("launch_presentation_return_url"),
            resource_link_id=launch_params.get("resource_link_id"),
            resource_link_title=launch_params.get("resource_link_title"),
            session_token=session_token,
            expires_at=datetime.utcnow() + timedelta(hours=2),
            # Canvas instance URL (extract from launch URL if available)
            canvas_instance_url=launch_params.get("custom_canvas_api_domain")
        )

        db.add(session)
        db.commit()
        db.refresh(session)

        logger.info(
            f"Created LTI 1.1 session {session.id} for user {user_id} "
            f"in course {course_id}"
        )

        # Redirect to frontend
        frontend_url = f"{settings.FRONTEND_URL}/canvas-assignment-generator"
        redirect_url = f"{frontend_url}?lti_session={session_token}&lti_version=1.1"

        # Return HTML that auto-submits to frontend
        # This is necessary because some Canvas configurations don't support direct redirects
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Launching Vidya AI...</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                }}
                .loader {{
                    text-align: center;
                }}
                .spinner {{
                    border: 4px solid rgba(255,255,255,0.3);
                    border-radius: 50%;
                    border-top: 4px solid white;
                    width: 40px;
                    height: 40px;
                    animation: spin 1s linear infinite;
                    margin: 0 auto 20px;
                }}
                @keyframes spin {{
                    0% {{ transform: rotate(0deg); }}
                    100% {{ transform: rotate(360deg); }}
                }}
            </style>
        </head>
        <body>
            <div class="loader">
                <div class="spinner"></div>
                <h2>Launching Vidya AI Assignment Generator...</h2>
                <p>Please wait while we prepare your workspace.</p>
            </div>
            <script>
                // Auto-redirect to frontend
                setTimeout(function() {{
                    window.location.href = "{redirect_url}";
                }}, 1000);
            </script>
        </body>
        </html>
        """

        return HTMLResponse(content=html_content)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"LTI 1.1 launch error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during LTI launch: {str(e)}"
        )


@router.get("/session/{session_token}")
async def get_session(
    session_token: str,
    db: Session = Depends(get_db)
):
    """
    Get LTI 1.1 session details

    Frontend calls this to get course/user context after launch
    """
    session = db.query(LTI11Session).filter(
        LTI11Session.session_token == session_token
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Session expired")

    return {
        "session_id": session.id,
        "course_id": session.course_id,
        "course_name": session.course_name,
        "user_id": session.user_id,
        "user_name": session.user_name,
        "user_email": session.user_email,
        "user_roles": session.user_roles.split(",") if session.user_roles else [],
        "canvas_instance_url": session.canvas_instance_url,
        "assignment_id": session.assignment_id,
        "assignment_name": session.assignment_name,
        "expires_at": session.expires_at.isoformat(),
        "lti_version": "1.1"
    }


@router.post("/return")
async def return_assignment(
    request: Request,
    session_token: str = Form(...),
    assignment_title: str = Form(...),
    assignment_description: str = Form(...),
    assignment_points: int = Form(...),
    db: Session = Depends(get_db)
):
    """
    Return generated assignment to Canvas

    LTI 1.1 doesn't have Deep Linking, so we use ContentItemReturn
    or redirect back to Canvas with the assignment data

    This endpoint is called by the frontend after assignment generation
    """
    try:
        # Get session
        session = db.query(LTI11Session).filter(
            LTI11Session.session_token == session_token
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Mark session as used
        session.used = True
        db.commit()

        # If we have a return URL, redirect back to Canvas
        if session.launch_presentation_return_url:
            # For LTI 1.1, we can pass limited data back via query params
            return_url = session.launch_presentation_return_url

            # Add success message
            separator = "&" if "?" in return_url else "?"
            return_url = f"{return_url}{separator}lti_msg=Assignment created successfully"

            return RedirectResponse(url=return_url)
        else:
            # No return URL, show success message
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Assignment Created</title>
                <style>
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                        max-width: 600px;
                        margin: 50px auto;
                        padding: 20px;
                        text-align: center;
                    }}
                    .success {{
                        color: #28a745;
                        font-size: 48px;
                        margin-bottom: 20px;
                    }}
                </style>
            </head>
            <body>
                <div class="success">✓</div>
                <h1>Assignment Created Successfully!</h1>
                <p><strong>{assignment_title}</strong></p>
                <p>{assignment_points} points</p>
                <p>Please return to Canvas to view your assignment.</p>
                <p><small>You can close this window.</small></p>
            </body>
            </html>
            """
            return HTMLResponse(content=html_content)

    except Exception as e:
        logger.error(f"Error returning assignment: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/consumer-info")
async def get_consumer_info():
    """
    Returns consumer key information for instructors

    This endpoint helps instructors know what consumer key/secret to use
    """
    default_consumer = CONSUMER_CONFIG.get("default_consumer", "vidyaai-lti-default")

    return {
        "consumer_key": default_consumer,
        "config_url": f"{settings.API_BASE_URL}/lti/v1/config.xml",
        "instructions": "Use this consumer key and config URL when adding Vidya AI to your Canvas course",
        "shared_secret_note": "Contact support@vidyaai.co for the shared secret"
    }


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "lti_version": "1.1",
        "timestamp": datetime.utcnow().isoformat()
    }
```

---

### 1.5 Update Main Application

**File: `vidya_ai_backend/src/main.py`**

Add LTI 1.1 router to your existing main.py:

```python
# Add import at top
from .controllers import lti_v1

# Add router (after existing routers)
app.include_router(lti_v1.router)
```

**Update CORS to allow Canvas:**

```python
# In CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        "https://*.instructure.com",  # Canvas instances
        "https://canvas.instructure.com",
        # Add your test Canvas instance if different
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Step 2: Frontend Updates

### 2.1 Update Assignment Generator Page

**File: `vidya_ai_frontend/src/app/canvas-assignment-generator/page.tsx`**

Add support for LTI 1.1 sessions. Update the existing page to handle both LTI versions:

```typescript
// Add to the component
const [ltiVersion, setLtiVersion] = useState<'1.1' | '1.3'>('1.3');

// Update session loading effect
useEffect(() => {
  const urlParams = new URLSearchParams(window.location.search);
  const sessionToken = urlParams.get('lti_session');
  const version = urlParams.get('lti_version') as '1.1' | '1.3' || '1.3';

  setLtiVersion(version);

  if (sessionToken) {
    // Load session based on version
    const endpoint = version === '1.1'
      ? `/lti/v1/session/${sessionToken}`
      : `/lti/session/${sessionToken}`;

    fetch(`${API_BASE_URL}${endpoint}`)
      .then(res => res.json())
      .then(data => {
        setSession(data);
        // ... rest of session loading
      });
  }
}, []);

// Update the "Add to Canvas" button handler
const handleAddToCanvas = async () => {
  if (ltiVersion === '1.1') {
    // LTI 1.1: No Deep Linking, manual return
    // Show assignment text to copy or redirect back to Canvas

    // Option 1: Download assignment as file
    downloadAssignmentAsFile(generatedAssignment);

    // Option 2: Show assignment in modal for copy-paste
    setShowAssignmentModal(true);

    // Option 3: Call return endpoint
    const formData = new FormData();
    formData.append('session_token', session.session_token);
    formData.append('assignment_title', assignment.title);
    formData.append('assignment_description', assignment.description);
    formData.append('assignment_points', assignment.points.toString());

    await fetch(`${API_BASE_URL}/lti/v1/return`, {
      method: 'POST',
      body: formData
    });

  } else {
    // LTI 1.3: Use Deep Linking (existing code)
    // ... existing Deep Link code
  }
};
```

---

## Step 3: Configuration and Setup

### 3.1 Environment Variables

**File: `vidya_ai_backend/.env`**

Add:
```bash
# LTI 1.1 Settings
LTI_V1_ENABLED=true
LTI_V1_CONSUMER_KEY=vidyaai-lti-default
LTI_V1_SHARED_SECRET=your-secure-secret-here
```

**Generate secure secret:**
```python
import secrets
print(secrets.token_urlsafe(32))
```

---

### 3.2 Create Consumer Key Management Script

**File: `vidya_ai_backend/manage_lti_consumers.py`**

```python
#!/usr/bin/env python3
"""
Manage LTI 1.1 Consumer Keys

Usage:
  python manage_lti_consumers.py list
  python manage_lti_consumers.py add <key> <secret> [description]
  python manage_lti_consumers.py disable <key>
  python manage_lti_consumers.py enable <key>
"""

import json
import sys
import secrets
from datetime import datetime

CONFIG_FILE = "lti_v1_consumers.json"

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"consumers": [], "default_consumer": None}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def list_consumers():
    config = load_config()
    print(f"\n{'Consumer Key':<30} {'Status':<10} {'Description':<40}")
    print("-" * 80)
    for c in config['consumers']:
        status = "Enabled" if c['enabled'] else "Disabled"
        desc = c.get('description', 'No description')
        default = " (DEFAULT)" if c['consumer_key'] == config.get('default_consumer') else ""
        print(f"{c['consumer_key']:<30} {status:<10} {desc:<40}{default}")

def add_consumer(key, secret, description=""):
    config = load_config()

    # Check if exists
    for c in config['consumers']:
        if c['consumer_key'] == key:
            print(f"Error: Consumer key '{key}' already exists")
            return

    consumer = {
        "consumer_key": key,
        "shared_secret": secret,
        "description": description,
        "enabled": True,
        "created_at": datetime.now().isoformat()
    }

    config['consumers'].append(consumer)

    # Set as default if first consumer
    if not config.get('default_consumer'):
        config['default_consumer'] = key

    save_config(config)
    print(f"✓ Added consumer key: {key}")

def toggle_consumer(key, enable):
    config = load_config()

    for c in config['consumers']:
        if c['consumer_key'] == key:
            c['enabled'] = enable
            save_config(config)
            status = "enabled" if enable else "disabled"
            print(f"✓ Consumer key '{key}' {status}")
            return

    print(f"Error: Consumer key '{key}' not found")

def generate_secret():
    """Generate a secure random secret"""
    return secrets.token_urlsafe(32)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "list":
        list_consumers()
    elif command == "add":
        if len(sys.argv) < 4:
            print("Usage: manage_lti_consumers.py add <key> <secret> [description]")
            sys.exit(1)
        key = sys.argv[2]
        secret = sys.argv[3]
        desc = sys.argv[4] if len(sys.argv) > 4 else ""
        add_consumer(key, secret, desc)
    elif command == "disable":
        if len(sys.argv) < 3:
            print("Usage: manage_lti_consumers.py disable <key>")
            sys.exit(1)
        toggle_consumer(sys.argv[2], False)
    elif command == "enable":
        if len(sys.argv) < 3:
            print("Usage: manage_lti_consumers.py enable <key>")
            sys.exit(1)
        toggle_consumer(sys.argv[2], True)
    elif command == "generate-secret":
        print(f"Generated secret: {generate_secret()}")
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)
```

Make executable:
```bash
chmod +x manage_lti_consumers.py
```

---

## Step 4: Testing Guide

### 4.1 Local Testing Setup

**Terminal 1 - Start Backend:**
```bash
cd vidya_ai_backend
python src/main.py
```

**Terminal 2 - Start Frontend:**
```bash
cd vidya_ai_frontend
yarn dev
```

**Terminal 3 - Start ngrok:**
```bash
ngrok http 8000
```

Copy the ngrok URL (e.g., `https://abc123.ngrok.io`)

---

### 4.2 Test with Canvas Free for Teachers

**Step 1: Create Test Course**
1. Go to https://www.instructure.com/canvas/try-canvas
2. Sign up for free account
3. Create a test course: "Vidya AI Test Course"

**Step 2: Add Vidya AI to Course (Via URL)**
1. In Canvas course, go to: **Settings → Apps → + App**
2. Configuration Type: **"By URL"**
3. Fill in:
   - **Name:** Vidya AI Assignment Generator
   - **Consumer Key:** `vidyaai-lti-default`
   - **Shared Secret:** (from your lti_v1_consumers.json)
   - **Config URL:** `https://YOUR-NGROK-URL.ngrok.io/lti/v1/config.xml`
4. Click **Submit**

**Step 3: Test Launch**
1. Go to **Assignments → + Assignment**
2. In "Submission Type", select **External Tool**
3. Click **Find**
4. You should see **"Create using Vidya AI"**
5. Click it

**Expected Flow:**
```
Canvas → LTI Launch POST → Backend verifies signature →
Creates session → Redirects to Frontend →
Frontend loads with session → Generate assignment →
Return to Canvas
```

---

### 4.3 Alternative: Manual Entry

If URL method doesn't work, try manual entry:

**Settings → Apps → + App**
- Configuration Type: **"Manual Entry"**
- **Name:** Vidya AI
- **Consumer Key:** `vidyaai-lti-default`
- **Shared Secret:** (from config)
- **Launch URL:** `https://YOUR-NGROK-URL.ngrok.io/lti/v1/launch`
- **Domain:** `YOUR-NGROK-URL.ngrok.io`
- **Privacy:** Public
- **Custom Fields:** (leave empty)

**Click Submit**

---

### 4.4 Testing Checklist

Test each scenario:

**✓ OAuth Signature Verification**
```bash
# Check backend logs for:
# "OAuth signature verified successfully"
```

**✓ Session Creation**
```bash
# Query database
psql -d vidyaai -c "SELECT * FROM lti11_sessions ORDER BY created_at DESC LIMIT 5;"
```

**✓ Frontend Launch**
- [ ] Frontend loads with course context
- [ ] User info displayed correctly
- [ ] Can select lecture files
- [ ] Assignment generates successfully

**✓ Return Flow**
- [ ] Returns to Canvas after generation
- [ ] Success message displayed

**✓ Error Handling**
- [ ] Invalid signature rejected
- [ ] Expired session handled
- [ ] Missing parameters caught

---

## Step 5: Production Deployment

### 5.1 Security Checklist

**Before Production:**

- [ ] Generate strong consumer secret: `secrets.token_urlsafe(32)`
- [ ] Store secrets in environment variables (not JSON file)
- [ ] Use HTTPS for all URLs
- [ ] Set up rate limiting
- [ ] Enable request logging
- [ ] Set up monitoring/alerts
- [ ] Add consumer key rotation mechanism

---

### 5.2 Update for Production

**File: `vidya_ai_backend/.env.production`**

```bash
API_BASE_URL=https://api.vidyaai.co
LTI_V1_ENABLED=true
LTI_V1_CONSUMER_KEY=vidyaai-lti-prod
LTI_V1_SHARED_SECRET=<STRONG_SECRET_HERE>
```

**Update config.xml endpoint:**
```python
# In lti_v1.py, update config.xml to use production URL
base_url = settings.API_BASE_URL  # Will use production URL in prod
```

---

### 5.3 Instructor Documentation

Create this for users:

**File: `INSTRUCTOR_SETUP_GUIDE.md`**

```markdown
# Vidya AI - Canvas Setup Guide for Instructors

## Quick Setup (5 minutes)

### Option 1: By URL (Easiest)

1. Go to your Canvas course
2. Click **Settings → Apps → + App**
3. Configuration Type: **"By URL"**
4. Fill in:
   - **Name:** Vidya AI
   - **Consumer Key:** `vidyaai-lti-default`
   - **Shared Secret:** Contact support@vidyaai.co
   - **Config URL:** `https://api.vidyaai.co/lti/v1/config.xml`
5. Click **Submit**

### Option 2: By XML (Alternative)

1. Download XML: https://api.vidyaai.co/lti/v1/config.xml
2. Go to **Settings → Apps → + App**
3. Configuration Type: **"Paste XML"**
4. **Consumer Key:** `vidyaai-lti-default`
5. **Shared Secret:** Contact support@vidyaai.co
6. Paste XML content
7. Click **Submit**

## Using Vidya AI

### Create an Assignment

1. Go to **Assignments → + Assignment**
2. Under "Submission Type", select **External Tool**
3. Click **Find**
4. Select **"Create using Vidya AI"**
5. Upload your lecture notes (PDF)
6. Configure questions (count, type, points)
7. Click **Generate**
8. Review and **Add to Canvas**

### Tips

- Upload lecture PDFs to Canvas Files first
- Vidya AI works best with clear, structured lecture notes
- You can edit the assignment in Canvas after creation

## Need Help?

- Email: support@vidyaai.co
- Documentation: https://docs.vidyaai.co
- Demo Video: https://vidyaai.co/demo
```

---

## Step 6: Monitoring and Debugging

### 6.1 Add Logging

**File: `vidya_ai_backend/src/controllers/lti_v1.py`**

Add detailed logging:

```python
# At module level
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/lti_v1.log'),
        logging.StreamHandler()
    ]
)
```

---

### 6.2 Debug Endpoints

**Add to lti_v1.py:**

```python
@router.get("/debug/last-launch")
async def debug_last_launch(db: Session = Depends(get_db)):
    """Get details of last LTI launch (for debugging)"""
    session = db.query(LTI11Session).order_by(
        LTI11Session.created_at.desc()
    ).first()

    if not session:
        return {"message": "No launches yet"}

    return {
        "session_id": session.id,
        "consumer_key": session.consumer_key,
        "course_id": session.course_id,
        "course_name": session.course_name,
        "user_id": session.user_id,
        "created_at": session.created_at.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "used": session.used
    }
```

---

## Step 7: Common Issues and Solutions

### Issue 1: OAuth Signature Verification Fails

**Symptoms:**
- Error: "Invalid OAuth signature"
- Launch fails immediately

**Debug:**
```bash
# Check backend logs
tail -f logs/lti_v1.log | grep "OAuth"

# Verify consumer key/secret match
curl http://localhost:8000/lti/v1/consumer-info
```

**Solutions:**
1. Ensure consumer key matches exactly (case-sensitive)
2. Ensure shared secret is correct
3. Check that ngrok URL is used consistently
4. Verify no extra spaces in consumer key/secret

---

### Issue 2: Session Not Found

**Symptoms:**
- Frontend shows "Session not found"

**Debug:**
```bash
# Check if session was created
psql -d vidyaai -c "SELECT * FROM lti11_sessions ORDER BY created_at DESC LIMIT 1;"
```

**Solutions:**
1. Check that database migration ran
2. Verify session token is passed correctly
3. Check session hasn't expired

---

### Issue 3: Canvas Doesn't Show "Create using Vidya AI"

**Symptoms:**
- External tool installed but not appearing

**Solutions:**
1. Check XML configuration has `assignment_selection` placement
2. Verify tool is installed in the correct course
3. Try refreshing Canvas page
4. Check browser console for errors

---

### Issue 4: Return to Canvas Fails

**Symptoms:**
- Assignment generates but doesn't return to Canvas

**Debug:**
```python
# Check if return URL was provided
# In backend logs, look for:
logger.info(f"Return URL: {session.launch_presentation_return_url}")
```

**Solutions:**
1. Canvas may not provide return URL - this is OK
2. Show success message instead
3. User can manually close window

---

## Step 8: Production Checklist

Before going live:

**Security:**
- [ ] Strong consumer secrets generated
- [ ] Secrets stored in environment variables
- [ ] HTTPS enabled for all endpoints
- [ ] Rate limiting configured
- [ ] CORS properly configured

**Testing:**
- [ ] OAuth signature verification works
- [ ] Session creation/retrieval works
- [ ] Frontend launch works
- [ ] Assignment generation works
- [ ] Return flow works
- [ ] Error handling works

**Documentation:**
- [ ] Instructor setup guide created
- [ ] Support email configured
- [ ] FAQ documented
- [ ] Demo video recorded

**Monitoring:**
- [ ] Logging configured
- [ ] Error alerts set up
- [ ] Usage analytics tracking
- [ ] Health check endpoint

**Deployment:**
- [ ] Backend deployed to production
- [ ] Frontend deployed
- [ ] Database migration run
- [ ] Config URL accessible
- [ ] Consumer key/secret documented

---

## Next Steps

1. **Implement the code** using Claude Code or GitHub Copilot
2. **Test locally** with Canvas Free for Teachers
3. **Deploy to staging** and test with real instructors
4. **Document** any institution-specific setup
5. **Go to production** once testing is complete

---

## Support and Resources

**Canvas Documentation:**
- LTI 1.1 Spec: https://www.imsglobal.org/specs/ltiv1p1/implementation-guide
- Canvas LTI: https://canvas.instructure.com/doc/api/file.tools_intro.html

**Testing Tools:**
- Canvas Free for Teachers: https://www.instructure.com/canvas/try-canvas
- LTI Test Tool: https://lti.tools/saltire/tc

**Vidya AI:**
- Support: support@vidyaai.co
- Documentation: https://docs.vidyaai.co

---

## Appendix A: LTI 1.1 vs 1.3 Comparison

| Feature | LTI 1.1 | LTI 1.3 |
|---------|---------|---------|
| **Security** | OAuth 1.0 | OAuth 2.0 + JWT |
| **Admin Required** | No | Yes (Developer Key) |
| **Installation** | Per-course | Account or Course |
| **Deep Linking** | No | Yes |
| **Grade Passback** | Basic (Outcomes) | Advanced (AGS) |
| **Setup Time** | 5 minutes | Days (admin approval) |
| **Future Support** | Being phased out | Current standard |
| **Best For** | Pilots, individuals | Institutions |

---

## Appendix B: OAuth 1.0 Signature Verification

How OAuth 1.0 signature works in LTI 1.1:

```
1. Canvas creates base string:
   METHOD + URL + SORTED_PARAMS

2. Canvas signs with HMAC-SHA1:
   signature = HMAC-SHA1(base_string, consumer_secret)

3. Canvas sends signature in oauth_signature parameter

4. We verify by:
   a. Recreate base string from received params
   b. Sign with our copy of consumer_secret
   c. Compare signatures
```

**Example Base String:**
```
POST&https%3A%2F%2Fapi.vidyaai.co%2Flti%2Fv1%2Flaunch&
oauth_consumer_key%3Dvidyaai-lti-default%26
oauth_nonce%3D12345%26
oauth_signature_method%3DHMAC-SHA1%26
oauth_timestamp%3D1234567890%26
oauth_version%3D1.0%26
user_id%3D123
```

---

**End of Implementation Guide**

Feed this entire file to Claude Code with:
```
Implement the LTI 1.1 integration for Vidya AI as described in this guide.
Focus on backend implementation first, then frontend updates.
```
