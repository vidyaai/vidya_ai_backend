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
from pylatexenc.latex2text import LatexNodes2Text
from controllers.config import logger

try:
    import boto3
    from botocore.exceptions import ClientError

    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.warning("boto3 not available - S3 diagram embedding will be disabled")


def sanitize_text_for_forms(text: str, equations: list = []) -> str:
    """
    Sanitize text for Google Forms API by removing newlines and excessive whitespace.

    Google Forms API doesn't allow newlines in displayed text fields like titles,
    descriptions, and option values.
    """
    if not text or not isinstance(text, str):
        return text or ""

    for eq in equations:
        eq_id = eq.get("id")
        latex = eq.get("latex")
        eq_text = LatexNodes2Text().latex_to_text(latex)
        eq_type = eq.get("type", "inline")
        if eq_id and latex:
            # Replace equation placeholders with LaTeX representation
            placeholder = f"<eq {eq_id}>"
            replacement = f"{eq_text}"
            logger.info(
                f"Replacing equation placeholder {placeholder} with {replacement}"
            )
            text = text.replace(placeholder, replacement)

    # Replace newlines with spaces and clean up excessive whitespace
    sanitized = text.replace("\n", " ").replace("\r", " ")
    # Replace multiple consecutive spaces with single space
    sanitized = " ".join(sanitized.split())

    # Trim the result
    logger.info(f"Sanitized text: {sanitized}")
    return sanitized.strip()


def _to_roman_numeral(num: int) -> str:
    """
    Convert integer to lowercase roman numeral.

    Args:
        num: Integer to convert (1-20 supported)

    Returns:
        Roman numeral string (i, ii, iii, iv, etc.)
    """
    val_map = [(10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]

    if num < 1 or num > 20:
        return str(num)  # Fallback for out of range

    result = ""
    for value, numeral in val_map:
        count = num // value
        if count:
            result += numeral * count
            num -= value * count
    return result


class GoogleFormsService:
    """Service for creating and managing Google Forms from assignments."""

    def __init__(self):
        self.service = None
        self.drive_service = None
        self.credentials = None
        self.s3_client = None
        self.aws_s3_bucket = None
        self.aws_s3_region = None
        self._initialize_service()
        self._initialize_s3_client()

    def _initialize_service(self):
        """Initialize Google Forms and Drive API services with credentials."""
        try:
            # Try to get credentials from various sources
            credentials = self._get_credentials()

            if credentials:
                self.credentials = credentials
                # Build both Forms and Drive services (matching your working script)
                self.service = build("forms", "v1", credentials=credentials)
                self.drive_service = build("drive", "v3", credentials=credentials)
                logger.info(
                    "Google Forms and Drive services initialized successfully with domain-wide delegation"
                )
            else:
                logger.warning(
                    "Google Forms service not available - no credentials found"
                )

        except Exception as e:
            logger.error(f"Failed to initialize Google Forms service: {e}")
            self.service = None
            self.drive_service = None

    def _initialize_s3_client(self):
        """Initialize S3 client for diagram embedding."""
        if not BOTO3_AVAILABLE:
            logger.warning("boto3 not available - S3 diagram embedding disabled")
            return

        try:
            # Get AWS credentials from environment
            self.aws_s3_bucket = os.getenv("AWS_S3_BUCKET")
            self.aws_s3_region = os.getenv("AWS_S3_REGION", "us-east-1")
            aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
            aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")

            if not self.aws_s3_bucket:
                logger.warning(
                    "AWS_S3_BUCKET not configured - S3 diagram embedding disabled"
                )
                return

            # Initialize S3 client
            if aws_access_key and aws_secret_key:
                self.s3_client = boto3.client(
                    "s3",
                    aws_access_key_id=aws_access_key,
                    aws_secret_access_key=aws_secret_key,
                    region_name=self.aws_s3_region,
                )
            else:
                # Try default credentials (IAM role, etc.)
                self.s3_client = boto3.client("s3", region_name=self.aws_s3_region)

            logger.info("S3 client initialized successfully for diagram embedding")

        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")
            self.s3_client = None

    def _get_credentials(self):
        """Get Google Cloud credentials from multiple sources in order of preference."""

        # Define scopes - both Forms and Drive API for complete functionality
        scopes = [
            "https://www.googleapis.com/auth/forms.body",
            "https://www.googleapis.com/auth/drive",
        ]

        # Domain-wide delegation user (must match your working script)
        subject_email = "admin@vidyaai.co"

        # Method 1: Environment variable with JSON content (Production)
        creds_json = os.getenv("GOOGLE_CLOUD_CREDENTIALS_JSON")
        if creds_json:
            try:
                credentials_info = json.loads(creds_json)
                base_credentials = (
                    service_account.Credentials.from_service_account_info(
                        credentials_info, scopes=scopes
                    )
                )
                # Apply domain-wide delegation
                return base_credentials.with_subject(subject_email)
            except Exception as e:
                logger.error(f"Failed to parse GOOGLE_CLOUD_CREDENTIALS_JSON: {e}")

        # Method 2: Service account key file path (Development/Server)
        creds_file_path = os.getenv("GOOGLE_CLOUD_CREDENTIALS_FILE")
        if creds_file_path and os.path.exists(creds_file_path):
            try:
                base_credentials = (
                    service_account.Credentials.from_service_account_file(
                        creds_file_path, scopes=scopes
                    )
                )
                # Apply domain-wide delegation
                return base_credentials.with_subject(subject_email)
            except Exception as e:
                logger.error(
                    f"Failed to load credentials from file {creds_file_path}: {e}"
                )

        # Method 3: Default local development path (including your specific credentials file)
        local_creds_paths = [
            "vidyaai-forms-integrations-0270b6b160e0.json",  # Your specific file
            "../vidyaai-forms-integrations-0270b6b160e0.json",  # Your specific file in parent dir
            "credentials/vidyaai-forms-integrations-0270b6b160e0.json",
            "credentials/google-service-account.json",
            "../credentials/google-service-account.json",
            "google-service-account.json",
        ]

        for path in local_creds_paths:
            if os.path.exists(path):
                try:
                    base_credentials = (
                        service_account.Credentials.from_service_account_file(
                            path, scopes=scopes
                        )
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
            if hasattr(base_credentials, "with_subject"):
                return base_credentials.with_subject(subject_email)
            return base_credentials
        except Exception as e:
            logger.error(f"Failed to get default credentials: {e}")

        return None

    def is_available(self) -> bool:
        """Check if Google Forms service is available."""
        return self.service is not None

    def _make_s3_object_public(self, s3_key: str) -> Optional[str]:
        """
        Generate a public URL for an S3 object.

        Note: This assumes the bucket has a policy that allows public read access.
        We don't use ACLs since many buckets have ACLs disabled.

        Args:
            s3_key: S3 object key

        Returns:
            Public URL or None if S3 not configured
        """
        if not self.aws_s3_bucket:
            logger.warning("S3 bucket not configured - cannot generate public URL")
            return None

        try:
            # Construct permanent public URL
            # Note: This assumes bucket has public read policy configured
            public_url = f"https://{self.aws_s3_bucket}.s3.{self.aws_s3_region}.amazonaws.com/{s3_key}"
            logger.info(f"Generated public S3 URL: {s3_key}")
            return public_url

        except Exception as e:
            logger.warning(f"Could not generate public URL for {s3_key}: {e}")
            return None

    def _get_public_diagram_url(self, diagram: Dict[str, Any]) -> Optional[str]:
        """
        Get a public URL for a diagram, either from existing s3_url or by generating one.

        Note: For S3 diagrams to work in Google Forms, the bucket must have a policy
        that allows public read access, such as:
        {
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::bucket-name/*"
        }

        Args:
            diagram: Diagram object with s3_url or s3_key

        Returns:
            Public URL or None if failed
        """
        if not diagram:
            return None

        # First check if we already have a public URL
        if diagram.get("s3_url"):
            return diagram["s3_url"]

        # Otherwise try to generate a public URL from s3_key
        s3_key = diagram.get("s3_key")
        if s3_key:
            return self._make_s3_object_public(s3_key)

        logger.warning("Diagram has neither s3_url nor s3_key")
        return None

    def _determine_required_status(
        self,
        question: Dict[str, Any],
        parent_question: Optional[Dict[str, Any]],
        subq_index: int,
    ) -> bool:
        """
        Determine if a subquestion is required based on parent's optionalParts and requiredPartsCount.

        Args:
            question: The subquestion to check
            parent_question: The parent multi-part question (if any)
            subq_index: Index of this subquestion in parent's subquestions array

        Returns:
            True if required, False if optional
        """
        # return False  # Default to not required for all questions
        if not parent_question:
            return True  # Top-level questions are always required

        # Check if parent has optional parts
        has_optional_parts = parent_question.get("optionalParts", False)

        # If no optional parts, all subquestions are required
        if not has_optional_parts:
            return True

        # If there are optional parts, check requiredPartsCount
        required_count = parent_question.get("requiredPartsCount")

        if required_count is not None and isinstance(required_count, int):
            # Subquestions with index >= required_count are optional
            # (0-indexed, so if requiredPartsCount=2, indices 0,1 are required, 2+ are optional)
            return subq_index < required_count

        # If optionalParts is True but no requiredPartsCount specified,
        # default to all parts being optional
        return False

    def _add_image_to_question_item(
        self, item: Dict[str, Any], diagram: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Add image embedding to a Google Forms question item.

        Args:
            item: The question item dict to modify
            diagram: Diagram object with s3_url or s3_key

        Returns:
            Modified item dict (modifies in place and returns for convenience)
        """
        if not diagram:
            return item

        # Get public URL for diagram
        public_url = self._get_public_diagram_url(diagram)

        if not public_url:
            logger.warning(
                "Could not get public URL for diagram - continuing without image"
            )
            # Optionally add caption to description if available
            caption = diagram.get("caption")
            if caption and "description" in item:
                item[
                    "description"
                ] = f"{item.get('description', '')} [Diagram: {caption}]".strip()
            return item

        # Add image to questionItem
        if "questionItem" not in item:
            logger.warning(
                "Question item missing questionItem field - cannot add image"
            )
            return item

        item["questionItem"]["image"] = {
            "sourceUri": public_url,
            "properties": {"alignment": "CENTER"},
        }

        # Optionally add caption to description
        caption = diagram.get("caption")
        if caption and "description" in item:
            item[
                "description"
            ] = f"{item.get('description', '')} [Diagram: {caption}]".strip()

        logger.info(f"Added image to question: {public_url}")
        return item

    def create_form_from_assignment(
        self, assignment_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
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
                "error": "Google Forms service not available - credentials not configured",
            }

        try:
            # Create the form with only title (API restriction)
            form_body = {
                "info": {
                    "title": sanitize_text_for_forms(
                        assignment_data.get("title", "Untitled Assignment")
                    )
                }
            }

            # Create the form
            form = self.service.forms().create(body=form_body).execute()
            form_id = form["formId"]

            # Add description and questions using batchUpdate
            description = assignment_data.get("description", "")
            questions_data = assignment_data.get("questions", [])

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
                "form_data": form,
            }

        except HttpError as e:
            error_details = (
                e.error_details
                if hasattr(e, "error_details")
                else "No additional details"
            )
            logger.error(f"Google Forms API error: {e}")
            logger.error(f"Error details: {error_details}")

            # Provide more helpful error messages
            if e.resp.status == 403:
                error_msg = "Permission denied. Please ensure the Google Forms API is enabled and the service account has proper permissions."
            elif e.resp.status == 500:
                error_msg = "Google Forms API internal error. This might be a temporary issue - please try again later."
            else:
                error_msg = f"Google Forms API error: {e}"

            return {"success": False, "error": error_msg, "api_error": str(e)}
        except Exception as e:
            logger.error(f"Failed to create Google Form: {e}")
            return {"success": False, "error": f"Failed to create form: {str(e)}"}

    def _setup_form_content(
        self, form_id: str, description: str, questions: List[Dict[str, Any]]
    ):
        """Add description and questions to a Google Form using batchUpdate."""
        try:
            requests = []

            # Add description if provided
            if description:
                requests.append(
                    {
                        "updateFormInfo": {
                            "info": {
                                "description": sanitize_text_for_forms(description)
                            },
                            "updateMask": "description",
                        }
                    }
                )

            # Track the current item index (updateFormInfo doesn't consume an index)
            # Questions start at index 0
            current_item_index = 0

            # Process questions - handle both flat and multi-part questions
            for i, question in enumerate(questions):
                q_type = question.get("type", "text")

                if q_type == "multi-part":
                    # Flatten multi-part question into sequential items
                    flattened_requests = self._flatten_question(
                        question,
                        str(i + 1),  # Question number (1, 2, 3, ...)
                        current_item_index,  # Current index for placement
                        parent_question=None,  # Top-level question
                        depth=1,
                    )
                    requests.extend(flattened_requests)
                    current_item_index += len(flattened_requests)
                else:
                    # Create regular question
                    request = self._create_question_by_type(
                        question,
                        current_item_index,
                        title_prefix=str(i + 1),  # Question number
                        parent_question=None,
                        subq_index=0,
                    )
                    if request:
                        requests.append(request)
                        current_item_index += 1

            # Execute batch update if we have any requests
            if requests:
                # Log request details for debugging
                logger.info(f"Submitting {len(requests)} requests to Google Forms API")
                for i, req in enumerate(requests):
                    if "createItem" in req:
                        item_type = (
                            "questionItem"
                            if "questionItem" in req["createItem"]["item"]
                            else "section"
                        )
                        index = (
                            req["createItem"]
                            .get("location", {})
                            .get("index", "MISSING")
                        )
                        logger.info(f"Request {i}: {item_type} at index {index}")

                batch_update_body = {"requests": requests}
                self.service.forms().batchUpdate(
                    formId=form_id, body=batch_update_body
                ).execute()

        except Exception as e:
            logger.error(f"Failed to setup form content for {form_id}: {e}")
            raise

    def _flatten_question(
        self,
        question: Dict[str, Any],
        number_prefix: str,
        current_index: int,
        parent_question: Optional[Dict[str, Any]] = None,
        depth: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Flatten a multi-part question into sequential Google Forms items.

        Args:
            question: The question to flatten (can be multi-part)
            number_prefix: Numbering prefix (e.g., "1", "1a", "1b(i)")
            current_index: Current index for form item placement
            parent_question: Parent question for determining required status
            depth: Current nesting depth (1=top level, 2=alphabetic, 3=roman)

        Returns:
            List of Google Forms API request dicts
        """
        requests = []

        # If this is a multi-part question, create a descriptive text item
        if question.get("type") == "multi-part":
            main_text = question.get("question", "")
            points = question.get("points", 0)

            # Create a text description item for the multi-part question
            # Using questionItem with textQuestion but not required, just for display
            description_item = {
                "createItem": {
                    "item": {
                        "title": sanitize_text_for_forms(
                            f"Question {number_prefix}: {main_text} (Total: {points} points)"
                        ),
                        "description": sanitize_text_for_forms(
                            "Answer the following parts:"
                        ),
                        "textItem": {},
                    },
                    "location": {"index": current_index},
                }
            }

            requests.append(description_item)

            # Process subquestions
            subquestions = question.get("subquestions", [])
            for idx, subq in enumerate(subquestions):
                # Determine labeling based on depth
                if depth == 1:
                    # Top level subquestions use alphabetic (a, b, c, ...)
                    sublabel = chr(97 + idx)  # a, b, c
                    full_number = f"{number_prefix}({sublabel})"
                elif depth == 2:
                    # Second level uses roman numerals (i, ii, iii, ...)
                    sublabel = _to_roman_numeral(idx + 1)
                    full_number = f"{number_prefix}({sublabel})"
                else:
                    # Deeper levels (shouldn't happen per schema, but fallback)
                    full_number = f"{number_prefix}.{idx + 1}"

                # Recursively process subquestion
                if subq.get("type") == "multi-part":
                    subq_requests = self._flatten_question(
                        subq,
                        full_number,
                        current_index + len(requests),
                        parent_question=question,
                        depth=depth + 1,
                    )
                    requests.extend(subq_requests)
                else:
                    # Create regular question for this subquestion
                    subq_request = self._create_question_by_type(
                        subq,
                        current_index + len(requests),
                        title_prefix=full_number,
                        parent_question=question,
                        subq_index=idx,
                    )
                    if subq_request:
                        requests.append(subq_request)
        else:
            # Not a multi-part question - create single question
            request = self._create_question_by_type(
                question,
                current_index,
                title_prefix=number_prefix,
                parent_question=parent_question,
                subq_index=0,
            )
            if request:
                requests.append(request)

        return requests

    def _create_question_by_type(
        self,
        question: Dict[str, Any],
        index: int,
        title_prefix: str = "",
        parent_question: Optional[Dict[str, Any]] = None,
        subq_index: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        Create a question of the appropriate type.

        Args:
            question: Question data
            index: Form item index
            title_prefix: Prefix for question numbering (e.g., "1(a)")
            parent_question: Parent question for required status
            subq_index: Index in parent's subquestions array

        Returns:
            Question request dict or None
        """
        q_type = question.get("type", "text")

        if q_type == "multiple-choice":
            return self._create_multiple_choice_question(
                question, index, title_prefix, parent_question, subq_index
            )
        elif q_type == "true-false":
            return self._create_true_false_question(
                question, index, title_prefix, parent_question, subq_index
            )
        elif q_type in ["short-answer", "numerical", "fill-blank"]:
            return self._create_text_question(
                question, index, title_prefix, parent_question, subq_index
            )
        elif q_type == "long-answer":
            return self._create_paragraph_question(
                question, index, title_prefix, parent_question, subq_index
            )
        else:
            # Default to text question for unsupported types
            return self._create_text_question(
                question, index, title_prefix, parent_question, subq_index
            )

    def _create_multiple_choice_question(
        self,
        question: Dict[str, Any],
        index: int,
        title_prefix: str = "",
        parent_question: Optional[Dict[str, Any]] = None,
        subq_index: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """Create a multiple choice question request with checkbox support."""
        options = question.get("options", [])
        if not options:
            return None

        # Determine if checkboxes (multiple correct) or radio (single)
        allow_multiple = question.get("allowMultipleCorrect", False)
        question_type = "CHECKBOX" if allow_multiple else "RADIO"

        equations = question.get("equations", [])

        # Build title with prefix
        question_text = question.get("question", f"Question {index + 1}")
        if title_prefix:
            title = f"{title_prefix}. {question_text}"
        else:
            title = question_text

        # Determine if required
        is_required = self._determine_required_status(
            question, parent_question, subq_index
        )

        # Build description with points
        points = question.get("points", 1)
        description = f"Points: {points}"
        if not is_required:
            description += " (Optional)"

        # Create the question item
        item = {
            "title": sanitize_text_for_forms(title, equations=equations),
            "description": sanitize_text_for_forms(description),
            "questionItem": {
                "question": {
                    "required": False,
                    "choiceQuestion": {
                        "type": question_type,
                        "options": [
                            {"value": sanitize_text_for_forms(opt, equations=equations)}
                            for opt in options
                            if opt and opt.strip()
                        ],
                    },
                }
            },
        }

        # Add image if diagram present
        if question.get("hasDiagram") and question.get("diagram"):
            item = self._add_image_to_question_item(item, question["diagram"])

        return {"createItem": {"item": item, "location": {"index": index}}}

    def _create_true_false_question(
        self,
        question: Dict[str, Any],
        index: int,
        title_prefix: str = "",
        parent_question: Optional[Dict[str, Any]] = None,
        subq_index: int = 0,
    ) -> Dict[str, Any]:
        """Create a true/false question request."""
        equations = question.get("equations", [])
        # Build title with prefix
        question_text = question.get("question", f"Question {index + 1}")
        if title_prefix:
            title = f"{title_prefix}. {question_text}"
        else:
            title = question_text

        # Determine if required
        is_required = self._determine_required_status(
            question, parent_question, subq_index
        )

        # Build description
        points = question.get("points", 1)
        description = f"Points: {points}"
        if not is_required:
            description += " (Optional)"

        # Create the question item
        item = {
            "title": sanitize_text_for_forms(title, equations=equations),
            "description": sanitize_text_for_forms(description),
            "questionItem": {
                "question": {
                    "required": False,
                    "choiceQuestion": {
                        "type": "RADIO",
                        "options": [{"value": "True"}, {"value": "False"}],
                    },
                }
            },
        }

        # Add image if diagram present
        if question.get("hasDiagram") and question.get("diagram"):
            item = self._add_image_to_question_item(item, question["diagram"])

        return {"createItem": {"item": item, "location": {"index": index}}}

    def _create_text_question(
        self,
        question: Dict[str, Any],
        index: int,
        title_prefix: str = "",
        parent_question: Optional[Dict[str, Any]] = None,
        subq_index: int = 0,
    ) -> Dict[str, Any]:
        """Create a short text question request."""
        equations = question.get("equations", [])
        # Build title with prefix
        question_text = question.get("question", f"Question {index + 1}")
        if title_prefix:
            title = f"{title_prefix}. {question_text}"
        else:
            title = question_text

        # Determine if required
        is_required = self._determine_required_status(
            question, parent_question, subq_index
        )

        # Build description
        points = question.get("points", 1)
        description = f"Points: {points}"
        if not is_required:
            description += " (Optional)"

        # Create the question item
        item = {
            "title": sanitize_text_for_forms(title, equations=equations),
            "description": sanitize_text_for_forms(description),
            "questionItem": {
                "question": {"required": False, "textQuestion": {"paragraph": False}}
            },
        }

        # Add image if diagram present
        if question.get("hasDiagram") and question.get("diagram"):
            item = self._add_image_to_question_item(item, question["diagram"])

        return {"createItem": {"item": item, "location": {"index": index}}}

    def _create_paragraph_question(
        self,
        question: Dict[str, Any],
        index: int,
        title_prefix: str = "",
        parent_question: Optional[Dict[str, Any]] = None,
        subq_index: int = 0,
    ) -> Dict[str, Any]:
        """Create a paragraph text question request."""
        equations = question.get("equations", [])
        # Build title with prefix
        question_text = question.get("question", f"Question {index + 1}")
        if title_prefix:
            title = f"{title_prefix}. {question_text}"
        else:
            title = question_text

        # Determine if required
        is_required = self._determine_required_status(
            question, parent_question, subq_index
        )

        # Build description
        points = question.get("points", 1)
        description = f"Points: {points}"
        if not is_required:
            description += " (Optional)"

        # Create the question item
        item = {
            "title": sanitize_text_for_forms(title, equations=equations),
            "description": sanitize_text_for_forms(description),
            "questionItem": {
                "question": {"required": False, "textQuestion": {"paragraph": True}}
            },
        }

        # Add image if diagram present
        if question.get("hasDiagram") and question.get("diagram"):
            item = self._add_image_to_question_item(item, question["diagram"])

        return {"createItem": {"item": item, "location": {"index": index}}}

    def _make_form_public(self, form_id: str):
        """Make a Google Form publicly accessible to anyone with the link."""
        try:
            if not self.drive_service:
                logger.warning("Drive service not available - cannot make form public")
                return

            # Create permission for anyone with link to view and respond
            permission = {
                "type": "anyone",
                "role": "writer",  # Writer role allows responding to the form
                "allowFileDiscovery": False,  # Don't allow discovery in search
            }

            # Apply the permission to make form public
            self.drive_service.permissions().create(
                fileId=form_id, body=permission, fields="id"
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
                "error": "Service not available - credentials not configured",
            }

        try:
            # Create a simple test form (like your working script)
            form_body = {"info": {"title": "Test Form - VidyaAI Integration"}}

            form = self.service.forms().create(body=form_body).execute()
            form_id = form["formId"]

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
                                            {"value": "5"},
                                        ],
                                    },
                                }
                            },
                        },
                        "location": {"index": 0},
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
                                            {"value": "False"},
                                        ],
                                    },
                                }
                            },
                        },
                        "location": {"index": 1},
                    }
                },
            ]

            # Apply the questions
            if requests:
                self.service.forms().batchUpdate(
                    formId=form_id, body={"requests": requests}
                ).execute()

            # Make the test form publicly accessible
            self._make_form_public(form_id)

            # Get URLs
            edit_url = f"https://docs.google.com/forms/d/{form_id}/edit"
            response_url = form.get("responderUri", "")

            return {
                "success": True,
                "form_id": form_id,
                "edit_url": edit_url,
                "response_url": response_url,
                "message": "Test form created successfully with domain-wide delegation",
            }

        except Exception as e:
            logger.error(f"Test connection failed: {e}")
            return {"success": False, "error": f"Test failed: {str(e)}"}


# Global instance
google_forms_service = GoogleFormsService()


def get_google_forms_service() -> GoogleFormsService:
    """Get the global Google Forms service instance."""
    return google_forms_service
