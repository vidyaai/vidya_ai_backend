"""
Google Forms Service for Assignment Integration

This service handles Google Forms API integration with proper credential management
for both development and production environments.
"""

import os
import json
from typing import Dict, Any, Optional, List
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from controllers.config import logger


def sanitize_text_for_forms(text: str) -> str:
    """
    Sanitize text for Google Forms API by removing newlines and excessive whitespace.
    
    Google Forms API doesn't allow newlines in displayed text fields like titles,
    descriptions, and option values.
    """
    if not text or not isinstance(text, str):
        return text or ""
    
    # Replace newlines with spaces and clean up excessive whitespace
    sanitized = text.replace('\n', ' ').replace('\r', ' ')
    # Replace multiple consecutive spaces with single space
    sanitized = ' '.join(sanitized.split())
    # Trim the result
    return sanitized.strip()


class GoogleFormsService:
    """Service for creating and managing Google Forms from assignments."""
    
    def __init__(self):
        self.service = None
        self.drive_service = None
        self.credentials = None
        self._initialize_service()
    
    def _initialize_service(self):
        """Initialize Google Forms and Drive API services with credentials."""
        try:
            # Try to get credentials from various sources
            credentials = self._get_credentials()
            
            if credentials:
                self.credentials = credentials
                # Build both Forms and Drive services (matching your working script)
                self.service = build('forms', 'v1', credentials=credentials)
                self.drive_service = build('drive', 'v3', credentials=credentials)
                logger.info("Google Forms and Drive services initialized successfully with domain-wide delegation")
            else:
                logger.warning("Google Forms service not available - no credentials found")
                
        except Exception as e:
            logger.error(f"Failed to initialize Google Forms service: {e}")
            self.service = None
            self.drive_service = None
    
    def _get_credentials(self):
        """Get Google Cloud credentials from multiple sources in order of preference."""
        
        # Define scopes - both Forms and Drive API for complete functionality
        scopes = [
            'https://www.googleapis.com/auth/forms.body',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # Domain-wide delegation user (must match your working script)
        subject_email = 'admin@vidyaai.co'
        
        # Method 1: Environment variable with JSON content (Production)
        creds_json = os.getenv('GOOGLE_CLOUD_CREDENTIALS_JSON')
        if creds_json:
            try:
                credentials_info = json.loads(creds_json)
                base_credentials = service_account.Credentials.from_service_account_info(
                    credentials_info,
                    scopes=scopes
                )
                # Apply domain-wide delegation
                return base_credentials.with_subject(subject_email)
            except Exception as e:
                logger.error(f"Failed to parse GOOGLE_CLOUD_CREDENTIALS_JSON: {e}")
        
        # Method 2: Service account key file path (Development/Server)
        creds_file_path = os.getenv('GOOGLE_CLOUD_CREDENTIALS_FILE')
        if creds_file_path and os.path.exists(creds_file_path):
            try:
                base_credentials = service_account.Credentials.from_service_account_file(
                    creds_file_path,
                    scopes=scopes
                )
                # Apply domain-wide delegation
                return base_credentials.with_subject(subject_email)
            except Exception as e:
                logger.error(f"Failed to load credentials from file {creds_file_path}: {e}")
        
        # Method 3: Default local development path (including your specific credentials file)
        local_creds_paths = [
            "vidyaai-forms-integrations-0270b6b160e0.json",  # Your specific file
            "../vidyaai-forms-integrations-0270b6b160e0.json",  # Your specific file in parent dir
            "credentials/vidyaai-forms-integrations-0270b6b160e0.json",
            "credentials/google-service-account.json",
            "../credentials/google-service-account.json",
            "google-service-account.json"
        ]
        
        for path in local_creds_paths:
            if os.path.exists(path):
                try:
                    base_credentials = service_account.Credentials.from_service_account_file(
                        path,
                        scopes=scopes
                    )
                    # Apply domain-wide delegation
                    return base_credentials.with_subject(subject_email)
                except Exception as e:
                    logger.error(f"Failed to load credentials from {path}: {e}")
        
        # Method 4: Application Default Credentials (Google Cloud Platform)
        try:
            from google.auth import default
            base_credentials, _ = default(scopes=scopes)
            # Apply domain-wide delegation if supported
            if hasattr(base_credentials, 'with_subject'):
                return base_credentials.with_subject(subject_email)
            return base_credentials
        except Exception as e:
            logger.error(f"Failed to get default credentials: {e}")
        
        return None
    
    def is_available(self) -> bool:
        """Check if Google Forms service is available."""
        return self.service is not None
    
    def create_form_from_assignment(self, assignment_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a Google Form from assignment data.
        
        Args:
            assignment_data: Assignment data containing questions and metadata
            
        Returns:
            Dictionary with form creation result or None if failed
        """
        if not self.is_available():
            return {
                "success": False,
                "error": "Google Forms service not available - credentials not configured"
            }
        
        try:
            # Create the form with only title (API restriction)
            form_body = {
                "info": {
                    "title": sanitize_text_for_forms(assignment_data.get('title', 'Untitled Assignment'))
                }
            }
            
            # Create the form
            form = self.service.forms().create(body=form_body).execute()
            form_id = form['formId']
            
            # Add description and questions using batchUpdate
            description = assignment_data.get('description', '')
            questions_data = assignment_data.get('questions', [])
            
            self._setup_form_content(form_id, description, questions_data)
            
            # Make the form publicly accessible
            self._make_form_public(form_id)
            
            # Get form URLs
            edit_url = f"https://docs.google.com/forms/d/{form_id}/edit"
            response_url = f"https://docs.google.com/forms/d/e/{form['responderUri'].split('/')[-2]}/viewform"
            
            return {
                "success": True,
                "form_id": form_id,
                "edit_url": edit_url,
                "response_url": response_url,
                "form_data": form
            }
            
        except HttpError as e:
            error_details = e.error_details if hasattr(e, 'error_details') else 'No additional details'
            logger.error(f"Google Forms API error: {e}")
            logger.error(f"Error details: {error_details}")
            
            # Provide more helpful error messages
            if e.resp.status == 403:
                error_msg = "Permission denied. Please ensure the Google Forms API is enabled and the service account has proper permissions."
            elif e.resp.status == 500:
                error_msg = "Google Forms API internal error. This might be a temporary issue - please try again later."
            else:
                error_msg = f"Google Forms API error: {e}"
                
            return {
                "success": False,
                "error": error_msg,
                "api_error": str(e)
            }
        except Exception as e:
            logger.error(f"Failed to create Google Form: {e}")
            return {
                "success": False,
                "error": f"Failed to create form: {str(e)}"
            }
    
    def _setup_form_content(self, form_id: str, description: str, questions: List[Dict[str, Any]]):
        """Add description and questions to a Google Form using batchUpdate."""
        try:
            requests = []
            
            # Add description if provided
            if description:
                requests.append({
                    "updateFormInfo": {
                        "info": {
                            "description": sanitize_text_for_forms(description)
                        },
                        "updateMask": "description"
                    }
                })
            
            # Add questions
            for i, question in enumerate(questions):
                q_type = question.get('type', 'text')
                
                if q_type == 'multiple-choice':
                    request = self._create_multiple_choice_question(question, i)
                elif q_type == 'true-false':
                    request = self._create_true_false_question(question, i)
                elif q_type in ['short-answer', 'numerical', 'fill-blank']:
                    request = self._create_text_question(question, i)
                elif q_type == 'long-answer':
                    request = self._create_paragraph_question(question, i)
                else:
                    # Default to text question for unsupported types
                    request = self._create_text_question(question, i)
                
                if request:
                    requests.append(request)
            
            # Execute batch update if we have any requests
            if requests:
                batch_update_body = {"requests": requests}
                self.service.forms().batchUpdate(
                    formId=form_id, 
                    body=batch_update_body
                ).execute()
                
        except Exception as e:
            logger.error(f"Failed to setup form content for {form_id}: {e}")
            raise
    
    def _create_multiple_choice_question(self, question: Dict[str, Any], index: int) -> Dict[str, Any]:
        """Create a multiple choice question request."""
        options = question.get('options', [])
        if not options:
            return None
        
        return {
            "createItem": {
                "item": {
                    "title": sanitize_text_for_forms(question.get('question', f'Question {index + 1}')),
                    "description": sanitize_text_for_forms(f"Points: {question.get('points', 1)}"),
                    "questionItem": {
                        "question": {
                            "required": True,
                            "choiceQuestion": {
                                "type": "RADIO",
                                "options": [{"value": sanitize_text_for_forms(opt)} for opt in options if opt and opt.strip()]
                            }
                        }
                    }
                },
                "location": {"index": index}
            }
        }
    
    def _create_true_false_question(self, question: Dict[str, Any], index: int) -> Dict[str, Any]:
        """Create a true/false question request."""
        return {
            "createItem": {
                "item": {
                    "title": sanitize_text_for_forms(question.get('question', f'Question {index + 1}')),
                    "description": sanitize_text_for_forms(f"Points: {question.get('points', 1)}"),
                    "questionItem": {
                        "question": {
                            "required": True,
                            "choiceQuestion": {
                                "type": "RADIO",
                                "options": [
                                    {"value": "True"},
                                    {"value": "False"}
                                ]
                            }
                        }
                    }
                },
                "location": {"index": index}
            }
        }
    
    def _create_text_question(self, question: Dict[str, Any], index: int) -> Dict[str, Any]:
        """Create a short text question request."""
        return {
            "createItem": {
                "item": {
                    "title": sanitize_text_for_forms(question.get('question', f'Question {index + 1}')),
                    "description": sanitize_text_for_forms(f"Points: {question.get('points', 1)}"),
                    "questionItem": {
                        "question": {
                            "required": True,
                            "textQuestion": {
                                "paragraph": False
                            }
                        }
                    }
                },
                "location": {"index": index}
            }
        }
    
    def _create_paragraph_question(self, question: Dict[str, Any], index: int) -> Dict[str, Any]:
        """Create a paragraph text question request."""
        return {
            "createItem": {
                "item": {
                    "title": sanitize_text_for_forms(question.get('question', f'Question {index + 1}')),
                    "description": sanitize_text_for_forms(f"Points: {question.get('points', 1)}"),
                    "questionItem": {
                        "question": {
                            "required": True,
                            "textQuestion": {
                                "paragraph": True
                            }
                        }
                    }
                },
                "location": {"index": index}
            }
        }

    def _make_form_public(self, form_id: str):
        """Make a Google Form publicly accessible to anyone with the link."""
        try:
            if not self.drive_service:
                logger.warning("Drive service not available - cannot make form public")
                return
            
            # Create permission for anyone with link to view and respond
            permission = {
                'type': 'anyone',
                'role': 'writer',  # Writer role allows responding to the form
                'allowFileDiscovery': False  # Don't allow discovery in search
            }
            
            # Apply the permission to make form public
            self.drive_service.permissions().create(
                fileId=form_id,
                body=permission,
                fields='id'
            ).execute()
            
            logger.info(f"Successfully made Google Form {form_id} publicly accessible")
            
        except HttpError as e:
            logger.error(f"Failed to make form {form_id} public: {e}")
            # Don't fail the entire form creation if sharing fails
        except Exception as e:
            logger.error(f"Unexpected error making form {form_id} public: {e}")

    def test_connection(self) -> Dict[str, Any]:
        """Test the Google Forms service connection by creating a simple test form."""
        if not self.is_available():
            return {
                "success": False,
                "error": "Service not available - credentials not configured"
            }
        
        try:
            # Create a simple test form (like your working script)
            form_body = {
                "info": {
                    "title": "Test Form - VidyaAI Integration"
                }
            }
            
            form = self.service.forms().create(body=form_body).execute()
            form_id = form['formId']
            
            # Add a few test questions using batchUpdate
            requests = [
                {
                    "createItem": {
                        "item": {
                            "title": "What is 2 + 2?",
                            "questionItem": {
                                "question": {
                                    "required": True,
                                    "choiceQuestion": {
                                        "type": "RADIO",
                                        "options": [
                                            {"value": "3"},
                                            {"value": "4"},
                                            {"value": "5"}
                                        ]
                                    }
                                }
                            }
                        },
                        "location": {"index": 0}
                    }
                },
                {
                    "createItem": {
                        "item": {
                            "title": "Is the sky blue?",
                            "questionItem": {
                                "question": {
                                    "required": True,
                                    "choiceQuestion": {
                                        "type": "RADIO",
                                        "options": [
                                            {"value": "True"},
                                            {"value": "False"}
                                        ]
                                    }
                                }
                            }
                        },
                        "location": {"index": 1}
                    }
                }
            ]
            
            # Apply the questions
            if requests:
                self.service.forms().batchUpdate(
                    formId=form_id,
                    body={"requests": requests}
                ).execute()
            
            # Make the test form publicly accessible
            self._make_form_public(form_id)
            
            # Get URLs
            edit_url = f"https://docs.google.com/forms/d/{form_id}/edit"
            response_url = form.get('responderUri', '')
            
            return {
                "success": True,
                "form_id": form_id,
                "edit_url": edit_url,
                "response_url": response_url,
                "message": "Test form created successfully with domain-wide delegation"
            }
            
        except Exception as e:
            logger.error(f"Test connection failed: {e}")
            return {
                "success": False,
                "error": f"Test failed: {str(e)}"
            }


# Global instance
google_forms_service = GoogleFormsService()


def get_google_forms_service() -> GoogleFormsService:
    """Get the global Google Forms service instance."""
    return google_forms_service