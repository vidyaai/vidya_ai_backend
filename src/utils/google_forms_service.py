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


class GoogleFormsService:
    """Service for creating and managing Google Forms from assignments."""
    
    def __init__(self):
        self.service = None
        self.credentials = None
        self._initialize_service()
    
    def _initialize_service(self):
        """Initialize Google Forms API service with credentials."""
        try:
            # Try to get credentials from various sources
            credentials = self._get_credentials()
            
            if credentials:
                self.credentials = credentials
                self.service = build('forms', 'v1', credentials=credentials)
                logger.info("Google Forms service initialized successfully")
            else:
                logger.warning("Google Forms service not available - no credentials found")
                
        except Exception as e:
            logger.error(f"Failed to initialize Google Forms service: {e}")
            self.service = None
    
    def _get_credentials(self):
        """Get Google Cloud credentials from multiple sources in order of preference."""
        
        # Method 1: Environment variable with JSON content (Production)
        creds_json = os.getenv('GOOGLE_CLOUD_CREDENTIALS_JSON')
        if creds_json:
            try:
                credentials_info = json.loads(creds_json)
                return service_account.Credentials.from_service_account_info(
                    credentials_info,
                    scopes=['https://www.googleapis.com/auth/forms.body']
                )
            except Exception as e:
                logger.error(f"Failed to parse GOOGLE_CLOUD_CREDENTIALS_JSON: {e}")
        
        # Method 2: Service account key file path (Development/Server)
        creds_file_path = os.getenv('GOOGLE_CLOUD_CREDENTIALS_FILE')
        if creds_file_path and os.path.exists(creds_file_path):
            try:
                return service_account.Credentials.from_service_account_file(
                    creds_file_path,
                    scopes=['https://www.googleapis.com/auth/forms.body']
                )
            except Exception as e:
                logger.error(f"Failed to load credentials from file {creds_file_path}: {e}")
        
        # Method 3: Default local development path (including your specific credentials file)
        local_creds_paths = [
            "vidyaai-forms-integrations-0270b6b160e0.json",  # Your specific file
            "credentials/vidyaai-forms-integrations-0270b6b160e0.json",
            "credentials/google-service-account.json",
            "../credentials/google-service-account.json",
            "google-service-account.json"
        ]
        
        for path in local_creds_paths:
            if os.path.exists(path):
                try:
                    return service_account.Credentials.from_service_account_file(
                        path,
                        scopes=['https://www.googleapis.com/auth/forms.body']
                    )
                except Exception as e:
                    logger.error(f"Failed to load credentials from {path}: {e}")
        
        # Method 4: Application Default Credentials (Google Cloud Platform)
        try:
            from google.auth import default
            credentials, _ = default(scopes=['https://www.googleapis.com/auth/forms.body'])
            return credentials
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
            # Create the form
            form_body = {
                "info": {
                    "title": assignment_data.get('title', 'Untitled Assignment'),
                    "description": assignment_data.get('description', '')
                }
            }
            
            # Create the form
            form = self.service.forms().create(body=form_body).execute()
            form_id = form['formId']
            
            # Add questions to the form
            questions_data = assignment_data.get('questions', [])
            if questions_data:
                self._add_questions_to_form(form_id, questions_data)
            
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
            logger.error(f"Google Forms API error: {e}")
            return {
                "success": False,
                "error": f"Google Forms API error: {e}"
            }
        except Exception as e:
            logger.error(f"Failed to create Google Form: {e}")
            return {
                "success": False,
                "error": f"Failed to create form: {str(e)}"
            }
    
    def _add_questions_to_form(self, form_id: str, questions: List[Dict[str, Any]]):
        """Add questions to a Google Form."""
        try:
            requests = []
            
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
            
            if requests:
                batch_update_body = {"requests": requests}
                self.service.forms().batchUpdate(
                    formId=form_id, 
                    body=batch_update_body
                ).execute()
                
        except Exception as e:
            logger.error(f"Failed to add questions to form {form_id}: {e}")
            raise
    
    def _create_multiple_choice_question(self, question: Dict[str, Any], index: int) -> Dict[str, Any]:
        """Create a multiple choice question request."""
        options = question.get('options', [])
        if not options:
            return None
        
        return {
            "createItem": {
                "item": {
                    "title": question.get('question', f'Question {index + 1}'),
                    "description": f"Points: {question.get('points', 1)}",
                    "questionItem": {
                        "question": {
                            "required": True,
                            "choiceQuestion": {
                                "type": "RADIO",
                                "options": [{"value": opt} for opt in options if opt.strip()]
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
                    "title": question.get('question', f'Question {index + 1}'),
                    "description": f"Points: {question.get('points', 1)}",
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
                    "title": question.get('question', f'Question {index + 1}'),
                    "description": f"Points: {question.get('points', 1)}",
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
                    "title": question.get('question', f'Question {index + 1}'),
                    "description": f"Points: {question.get('points', 1)}",
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


# Global instance
google_forms_service = GoogleFormsService()


def get_google_forms_service() -> GoogleFormsService:
    """Get the global Google Forms service instance."""
    return google_forms_service