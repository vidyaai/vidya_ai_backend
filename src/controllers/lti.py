"""
Canvas LTI 1.3 Integration Controller
Handles LTI launches, Deep Linking, and Canvas API integration for assignment generation
"""

import os
import json
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from pylti1p3.tool_config import ToolConfJsonFile
from pylti1p3.message_launch import MessageLaunch
from pylti1p3.deep_link import DeepLink
from pylti1p3.registration import Registration
import requests

from utils.db import get_db
from controllers.config import logger
from models import Assignment, CanvasLTISession, Video
from utils.firebase_auth import get_current_user
from controllers.storage import s3_upload_file, s3_presign_url

router = APIRouter(prefix="/lti", tags=["LTI"])

# Load environment-specific configuration
ENV = os.getenv("ENVIRONMENT", "development")
BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# LTI configuration file path
CONFIG_FILE = f"lti_config.{ENV}.json"

# Check if config file exists
if not os.path.exists(CONFIG_FILE):
    logger.warning(f"LTI config file {CONFIG_FILE} not found. LTI features will be disabled.")
    tool_conf = None
else:
    try:
        tool_conf = ToolConfJsonFile(CONFIG_FILE)
        logger.info(f"LTI configuration loaded from {CONFIG_FILE}")
    except Exception as e:
        logger.error(f"Failed to load LTI configuration: {e}")
        tool_conf = None


# In-memory session storage (in production, use Redis or database)
lti_sessions = {}


def store_lti_session(session_id: str, data: dict):
    """Store LTI session data"""
    lti_sessions[session_id] = {
        "data": data,
        "timestamp": datetime.utcnow()
    }


def get_lti_session(session_id: str) -> Optional[dict]:
    """Retrieve LTI session data"""
    session = lti_sessions.get(session_id)
    if session:
        # Check if session is not expired (1 hour)
        if datetime.utcnow() - session["timestamp"] < timedelta(hours=1):
            return session["data"]
    return None


@router.get("/config.xml")
async def lti_config():
    """
    Canvas LTI 1.3 configuration endpoint
    Returns XML configuration for Canvas to install the tool
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
    <blti:description>AI-powered assignment generation from lecture notes and course materials</blti:description>
    <blti:launch_url>{BASE_URL}/lti/launch</blti:launch_url>
    <blti:extensions platform="canvas.instructure.com">
        <lticm:property name="tool_id">vidya_ai_assignments</lticm:property>
        <lticm:property name="privacy_level">public</lticm:property>
        <lticm:options name="assignment_selection">
            <lticm:property name="url">{BASE_URL}/lti/launch</lticm:property>
            <lticm:property name="message_type">ContentItemSelectionRequest</lticm:property>
            <lticm:property name="text">Create using Vidya AI</lticm:property>
            <lticm:property name="enabled">true</lticm:property>
        </lticm:options>
        <lticm:options name="course_navigation">
            <lticm:property name="url">{BASE_URL}/lti/launch</lticm:property>
            <lticm:property name="text">Vidya AI Assignments</lticm:property>
            <lticm:property name="enabled">true</lticm:property>
            <lticm:property name="visibility">admins</lticm:property>
        </lticm:options>
    </blti:extensions>
</cartridge_basiclti_link>"""
    
    return HTMLResponse(content=xml, media_type="application/xml")


@router.get("/jwks")
async def get_jwks():
    """
    JSON Web Key Set endpoint
    Canvas uses this to verify our signatures
    """
    if not tool_conf:
        raise HTTPException(status_code=503, detail="LTI not configured")
    
    try:
        # Read public key
        with open('public.key', 'r') as f:
            public_key = f.read()
        
        registration = Registration()
        registration.set_public_key(public_key)
        
        return JSONResponse(content=registration.get_jwks())
    except Exception as e:
        logger.error(f"Error generating JWKS: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate JWKS")


@router.post("/login")
@router.get("/login")
async def lti_login(request: Request):
    """
    OIDC Login Initiation
    Canvas redirects here first in the LTI 1.3 flow
    """
    if not tool_conf:
        raise HTTPException(status_code=503, detail="LTI not configured")
    
    try:
        # Get parameters from Canvas
        if request.method == "POST":
            form_data = await request.form()
            params = dict(form_data)
        else:
            params = dict(request.query_params)
        
        logger.info(f"LTI Login initiated: {params}")
        
        target_link_uri = params.get('target_link_uri')
        lti_message_hint = params.get('lti_message_hint')
        login_hint = params.get('login_hint')
        client_id = params.get('client_id')
        iss = params.get('iss')
        
        # Generate nonce and state
        nonce = str(uuid.uuid4())
        state = str(uuid.uuid4())
        
        # Build OIDC auth redirect URL
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
        
        logger.info(f"Redirecting to Canvas auth: {oidc_url}")
        return RedirectResponse(url=oidc_url)
        
    except Exception as e:
        logger.error(f"LTI login error: {e}")
        raise HTTPException(status_code=400, detail=f"LTI login failed: {str(e)}")


@router.post("/launch")
async def lti_launch(request: Request, db: Session = Depends(get_db)):
    """
    Main LTI Launch Handler
    Canvas sends the professor here after OIDC authentication
    Extracts course context and redirects to assignment generator
    """
    if not tool_conf:
        raise HTTPException(status_code=503, detail="LTI not configured")
    
    try:
        # Validate LTI launch
        message_launch = MessageLaunch(request, tool_conf)
        launch_data = message_launch.get_launch_data()
        
        logger.info(f"LTI Launch Data: {json.dumps(launch_data, indent=2)}")
        
        # Extract Canvas context
        context = launch_data.get('https://purl.imsglobal.org/spec/lti/claim/context', {})
        course_id = context.get('id')
        course_name = context.get('title', 'Unknown Course')
        
        # Extract user information
        user_id = launch_data.get('sub')
        user_name = launch_data.get('name', 'Unknown User')
        user_email = launch_data.get('email', '')
        
        # Check user roles
        roles = launch_data.get('https://purl.imsglobal.org/spec/lti/claim/roles', [])
        is_instructor = any('Instructor' in role or 'Teacher' in role for role in roles)
        
        if not is_instructor:
            return HTMLResponse(content="""
                <!DOCTYPE html>
                <html>
                <head><title>Access Denied</title></head>
                <body style="font-family: Arial; padding: 50px; text-align: center;">
                    <h1>Access Denied</h1>
                    <p>Only instructors can access the Vidya AI Assignment Generator.</p>
                </body>
                </html>
            """)
        
        # Get Canvas access token from launch data
        canvas_base_url = launch_data.get('iss', '').replace('https://', '')
        
        # Extract custom parameters
        custom = launch_data.get('https://purl.imsglobal.org/spec/lti/claim/custom', {})
        canvas_api_domain = custom.get('canvas_api_domain', canvas_base_url)
        
        # Create session ID
        session_id = str(uuid.uuid4())
        
        # Store LTI session data
        session_data = {
            'course_id': course_id,
            'course_name': course_name,
            'user_id': user_id,
            'user_name': user_name,
            'user_email': user_email,
            'canvas_api_domain': canvas_api_domain,
            'launch_data': launch_data,
            'is_deep_link': message_launch.is_deep_link_launch()
        }
        store_lti_session(session_id, session_data)
        
        # Store in database
        lti_session_db = CanvasLTISession(
            session_id=session_id,
            canvas_course_id=course_id,
            canvas_course_name=course_name,
            canvas_user_id=user_id,
            canvas_user_name=user_name,
            canvas_user_email=user_email,
            canvas_api_domain=canvas_api_domain,
            launch_data=launch_data,
            is_deep_link=message_launch.is_deep_link_launch()
        )
        db.add(lti_session_db)
        db.commit()
        
        # Check if this is a Deep Link request (assignment creation)
        if message_launch.is_deep_link_launch():
            # Redirect to assignment generator UI
            frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
            redirect_url = (
                f"{frontend_url}/canvas-assignment-generator?"
                f"session_id={session_id}&"
                f"course_id={course_id}&"
                f"course_name={course_name}"
            )
            return RedirectResponse(url=redirect_url)
        else:
            # Regular course navigation launch
            return HTMLResponse(content=f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Vidya AI - {course_name}</title>
                    <meta charset="UTF-8">
                    <style>
                        body {{
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                            max-width: 800px;
                            margin: 50px auto;
                            padding: 20px;
                            background: #f5f5f5;
                        }}
                        .card {{
                            background: white;
                            padding: 30px;
                            border-radius: 12px;
                            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                            margin-bottom: 20px;
                        }}
                        .header {{
                            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                            color: white;
                            padding: 30px;
                            border-radius: 12px;
                            margin-bottom: 30px;
                            text-align: center;
                        }}
                        .button {{
                            display: inline-block;
                            background: #667eea;
                            color: white;
                            padding: 12px 24px;
                            border-radius: 8px;
                            text-decoration: none;
                            font-weight: 500;
                            transition: background 0.2s;
                        }}
                        .button:hover {{
                            background: #5a67d8;
                        }}
                        h1 {{ margin: 0 0 10px 0; }}
                        p {{ margin: 0; opacity: 0.9; }}
                    </style>
                </head>
                <body>
                    <div class="header">
                        <h1>🎓 Vidya AI Assignment Generator</h1>
                        <p>AI-powered assignments from your lecture notes</p>
                    </div>
                    <div class="card">
                        <h2>Welcome, {user_name}!</h2>
                        <p><strong>Course:</strong> {course_name}</p>
                        <p><strong>Email:</strong> {user_email}</p>
                        <br>
                        <p>To create an assignment:</p>
                        <ol>
                            <li>Go to the Assignments page in Canvas</li>
                            <li>Click "+ Assignment"</li>
                            <li>Look for "Create using Vidya AI" option</li>
                            <li>Select lecture notes and generate!</li>
                        </ol>
                    </div>
                </body>
                </html>
            """)
            
    except Exception as e:
        logger.error(f"LTI Launch error: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"LTI launch failed: {str(e)}")


@router.get("/api/canvas/files")
async def get_canvas_files(
    session_id: str,
    canvas_access_token: str,
    db: Session = Depends(get_db)
):
    """
    Fetch lecture notes and files from Canvas course
    """
    try:
        # Get LTI session
        session_data = get_lti_session(session_id)
        if not session_data:
            raise HTTPException(status_code=404, detail="Session not found or expired")
        
        course_id = session_data['course_id']
        canvas_api_domain = session_data['canvas_api_domain']
        
        # Use Canvas API to fetch files
        headers = {
            'Authorization': f'Bearer {canvas_access_token}'
        }
        
        # Get course files
        files_url = f"https://{canvas_api_domain}/api/v1/courses/{course_id}/files"
        params = {
            'per_page': 100,
            'content_types[]': ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
        }
        
        response = requests.get(files_url, headers=headers, params=params)
        response.raise_for_status()
        
        files = response.json()
        
        # Filter and format files
        lecture_files = []
        for file in files:
            if file.get('mime_class') in ['pdf', 'doc']:
                lecture_files.append({
                    'id': file['id'],
                    'name': file['display_name'],
                    'url': file['url'],
                    'size': file.get('size', 0),
                    'content_type': file.get('content-type', ''),
                    'created_at': file.get('created_at', ''),
                    'folder_id': file.get('folder_id')
                })
        
        return JSONResponse(content={
            'files': lecture_files,
            'course_name': session_data['course_name']
        })
        
    except requests.RequestException as e:
        logger.error(f"Canvas API error: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch Canvas files")
    except Exception as e:
        logger.error(f"Error fetching Canvas files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/canvas/download-file")
async def download_canvas_file(
    session_id: str = Form(...),
    file_id: str = Form(...),
    canvas_access_token: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Download a file from Canvas and prepare it for assignment generation
    """
    try:
        # Get LTI session
        session_data = get_lti_session(session_id)
        if not session_data:
            raise HTTPException(status_code=404, detail="Session not found")
        
        canvas_api_domain = session_data['canvas_api_domain']
        
        # Get file info from Canvas
        headers = {'Authorization': f'Bearer {canvas_access_token}'}
        file_url = f"https://{canvas_api_domain}/api/v1/files/{file_id}"
        
        response = requests.get(file_url, headers=headers)
        response.raise_for_status()
        file_info = response.json()
        
        # Download file content
        download_url = file_info['url']
        file_response = requests.get(download_url, headers=headers)
        file_response.raise_for_status()
        
        # Upload to S3
        file_name = file_info['display_name']
        s3_key = f"canvas-files/{session_id}/{file_id}/{file_name}"
        
        await s3_upload_file(file_response.content, s3_key)
        presigned_url = s3_presign_url(s3_key, expiration=3600)
        
        return JSONResponse(content={
            'file_id': file_id,
            'file_name': file_name,
            'file_type': file_info.get('content-type'),
            's3_key': s3_key,
            'presigned_url': presigned_url,
            'size': file_info.get('size')
        })
        
    except Exception as e:
        logger.error(f"Error downloading Canvas file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/deeplink/response")
async def deeplink_response(request: Request, db: Session = Depends(get_db)):
    """
    Send generated assignment back to Canvas via Deep Linking
    Called when instructor clicks "Add to Canvas" after generating assignment
    """
    if not tool_conf:
        raise HTTPException(status_code=503, detail="LTI not configured")
    
    try:
        data = await request.json()
        
        session_id = data.get('session_id')
        assignment_id = data.get('assignment_id')
        
        # Get LTI session
        session_data = get_lti_session(session_id)
        if not session_data:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Get assignment from database
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")
        
        # Reconstruct message launch from session
        # Note: pylti1p3 doesn't support session reconstruction easily
        # We'll use the launch data we stored
        launch_data = session_data['launch_data']
        
        # Create Deep Link response manually
        deep_link_return_url = launch_data.get(
            'https://purl.imsglobal.org/spec/lti-dl/claim/deep_linking_settings', {}
        ).get('deep_link_return_url')
        
        if not deep_link_return_url:
            raise HTTPException(status_code=400, detail="No deep link return URL")
        
        # Build the resource
        resource = {
            'type': 'ltiResourceLink',
            'title': assignment.title,
            'text': assignment.description or '',
            'url': f"{BASE_URL}/lti/assignment/{assignment_id}",
            'custom': {
                'assignment_id': assignment_id,
                'total_points': assignment.total_points,
                'question_count': assignment.total_questions
            }
        }
        
        # Create JWT for deep link response
        import jwt
        from datetime import datetime, timedelta
        
        with open('private.key', 'r') as f:
            private_key = f.read()
        
        payload = {
            'iss': BASE_URL,
            'aud': launch_data.get('iss'),
            'exp': datetime.utcnow() + timedelta(seconds=600),
            'iat': datetime.utcnow(),
            'nonce': str(uuid.uuid4()),
            'https://purl.imsglobal.org/spec/lti/claim/message_type': 'LtiDeepLinkingResponse',
            'https://purl.imsglobal.org/spec/lti/claim/version': '1.3.0',
            'https://purl.imsglobal.org/spec/lti/claim/deployment_id': launch_data.get(
                'https://purl.imsglobal.org/spec/lti/claim/deployment_id'
            ),
            'https://purl.imsglobal.org/spec/lti-dl/claim/content_items': [resource],
            'https://purl.imsglobal.org/spec/lti-dl/claim/data': launch_data.get(
                'https://purl.imsglobal.org/spec/lti-dl/claim/deep_linking_settings', {}
            ).get('data', '')
        }
        
        id_token = jwt.encode(payload, private_key, algorithm='RS256')
        
        # Return HTML form that auto-submits to Canvas
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Adding Assignment to Canvas...</title>
        </head>
        <body>
            <p>Adding assignment to Canvas...</p>
            <form id="deep-link-form" action="{deep_link_return_url}" method="POST">
                <input type="hidden" name="JWT" value="{id_token}" />
            </form>
            <script>
                document.getElementById('deep-link-form').submit();
            </script>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html)
        
    except Exception as e:
        logger.error(f"Deep link response error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create deep link: {str(e)}")


@router.get("/assignment/{assignment_id}")
async def view_assignment(assignment_id: str, db: Session = Depends(get_db)):
    """
    View assignment details (when student clicks on assignment in Canvas)
    """
    try:
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")
        
        # Generate HTML view of the assignment
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{assignment.title}</title>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    max-width: 900px;
                    margin: 20px auto;
                    padding: 20px;
                    line-height: 1.6;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px;
                    border-radius: 12px;
                    margin-bottom: 30px;
                }}
                .question {{
                    background: #f8f9fa;
                    padding: 20px;
                    border-radius: 8px;
                    margin-bottom: 20px;
                    border-left: 4px solid #667eea;
                }}
                .question-header {{
                    font-weight: 600;
                    font-size: 1.1em;
                    margin-bottom: 10px;
                }}
                .points {{
                    color: #666;
                    font-size: 0.9em;
                }}
                .rubric {{
                    background: #e9ecef;
                    padding: 15px;
                    border-radius: 6px;
                    margin-top: 10px;
                    font-size: 0.95em;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>{assignment.title}</h1>
                <p>{assignment.description or ''}</p>
                <p><strong>Total Points:</strong> {assignment.total_points} | <strong>Questions:</strong> {assignment.total_questions}</p>
            </div>
        """
        
        # Add questions
        questions = assignment.questions or []
        for idx, q in enumerate(questions, 1):
            html += f"""
            <div class="question">
                <div class="question-header">Question {idx} <span class="points">({q.get('points', 0)} points)</span></div>
                <p>{q.get('question', '')}</p>
            """
            
            if q.get('rubric'):
                html += f"""
                <div class="rubric">
                    <strong>Grading Rubric:</strong><br>
                    {q.get('rubric')}
                </div>
                """
            
            html += "</div>"
        
        html += """
        </body>
        </html>
        """
        
        return HTMLResponse(content=html)
        
    except Exception as e:
        logger.error(f"Error viewing assignment: {e}")
        raise HTTPException(status_code=500, detail=str(e))
