import base64
import json
import re
import uuid
import tempfile
import os
from textwrap import dedent
from typing import Dict, Any, Optional, List, Tuple
from openai import OpenAI
from controllers.config import logger, s3_client, AWS_S3_BUCKET
from controllers.storage import s3_upload_file
import PyPDF2
import docx
from io import BytesIO
from PIL import Image
import csv
import html2text
import markdown
from pdf2image import convert_from_bytes
from .prompts import (
    DOCUMENT_PARSER_SYSTEM_PROMPT,
    FALLBACK_PARSER_SYSTEM_PROMPT,
    create_extraction_prompt,
    create_fallback_prompt,
)
from .assignment_schemas import get_assignment_parsing_schema


class DocumentProcessor:
    """Service for processing various document types and extracting text content"""

    def __init__(self):
        self.client = OpenAI()
        self.model = "gpt-4o"  # Vision-capable model for PDF extraction
        self.supported_types = {
            "application/pdf": self._extract_pdf_text,
            "text/plain": self._extract_text,
            "application/msword": self._extract_doc_text,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": self._extract_docx_text,
            "text/markdown": self._extract_markdown_text,
            "text/html": self._extract_html_text,
            "text/csv": self._extract_csv_text,
            "application/json": self._extract_json_text,
        }

    def extract_text_from_file(
        self, file_content: str, file_name: str, file_type: str
    ) -> str:
        """
        Extract text content from various file types

        Args:
            file_content: Base64 encoded file content
            file_name: Original file name
            file_type: MIME type or file extension

        Returns:
            Extracted text content
        """
        try:
            # Decode base64 content
            decoded_content = base64.b64decode(file_content)

            # Determine file type from extension if MIME type not recognized
            if file_type not in self.supported_types:
                extension = file_name.lower().split(".")[-1] if "." in file_name else ""
                file_type = self._get_mime_type_from_extension(extension)

            # Extract text based on file type
            if file_type in self.supported_types:
                extractor = self.supported_types[file_type]
                return extractor(decoded_content)
            else:
                raise ValueError(f"Unsupported file type: {file_type}")

        except Exception as e:
            logger.error(f"Error extracting text from {file_name}: {str(e)}")
            raise

    def _get_mime_type_from_extension(self, extension: str) -> str:
        """Map file extensions to MIME types"""
        extension_map = {
            "pdf": "application/pdf",
            "txt": "text/plain",
            "doc": "application/msword",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "md": "text/markdown",
            "html": "text/html",
            "htm": "text/html",
            "csv": "text/csv",
            "json": "application/json",
        }
        return extension_map.get(extension, "text/plain")

    def _extract_pdf_text(self, content: bytes) -> str:
        """Extract text from PDF files using Poppler and GPT-4o vision"""
        try:
            # Convert PDF pages to images using Poppler
            images = convert_from_bytes(content, dpi=200)
            logger.info(f"Converted PDF to {len(images)} images")

            # Convert all images to base64
            image_contents = []
            for page_num, image in enumerate(images, 1):
                buffered = BytesIO()
                image.save(buffered, format="PNG")
                img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
                image_contents.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_base64}"},
                    }
                )

            # Build message content with text instruction followed by all images
            user_content = [
                {
                    "type": "text",
                    "text": f"Extract ALL text from this {len(images)}-page PDF document. For each page, start with '--- Page N ---' followed by all the text from that page. Maintain the original formatting, structure, and layout. Extract text in page order.",
                }
            ]
            user_content.extend(image_contents)

            # Single API call to extract text from all pages
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise OCR system. Extract ALL text from images exactly as it appears, maintaining formatting, structure, and layout. Include all text visible in the images.",
                    },
                    {"role": "user", "content": user_content},
                ],
                max_tokens=16000,
            )

            extracted_text = response.choices[0].message.content
            if extracted_text:
                logger.info(
                    f"Successfully extracted text from all {len(images)} pages in one API call"
                )
                return extracted_text.strip()
            else:
                raise ValueError("Empty response from GPT-4o")

        except Exception as e:
            logger.error(f"Error extracting PDF text with Poppler/GPT-4o: {str(e)}")
            # Fallback to PyPDF2 if vision extraction fails
            logger.info("Attempting fallback to PyPDF2 text extraction...")
            try:
                pdf_file = BytesIO(content)
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
                return text.strip()
            except Exception as fallback_error:
                logger.error(f"Fallback extraction also failed: {str(fallback_error)}")
                raise ValueError("Failed to extract text from PDF file")

    def _extract_text(self, content: bytes) -> str:
        """Extract text from plain text files"""
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            # Try different encodings
            for encoding in ["latin-1", "cp1252", "iso-8859-1"]:
                try:
                    return content.decode(encoding)
                except UnicodeDecodeError:
                    continue
            raise ValueError("Unable to decode text file")

    def _extract_doc_text(self, content: bytes) -> str:
        """Extract text from DOC files (legacy Word format)"""
        # Note: python-docx doesn't support .doc files, only .docx
        # For .doc files, we'd need additional libraries like python-docx2txt or antiword
        # For now, we'll return an error message suggesting conversion
        raise ValueError(
            "Legacy .doc files are not supported. Please convert to .docx or save as plain text."
        )

    def _extract_docx_text(self, content: bytes) -> str:
        """Extract text from DOCX files"""
        try:
            doc_file = BytesIO(content)
            doc = docx.Document(doc_file)

            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"

            # Also extract text from tables
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        text += cell.text + "\t"
                    text += "\n"

            return text.strip()
        except Exception as e:
            logger.error(f"Error extracting DOCX text: {str(e)}")
            raise ValueError("Failed to extract text from DOCX file")

    def _extract_markdown_text(self, content: bytes) -> str:
        """Extract text from Markdown files"""
        try:
            md_text = content.decode("utf-8")
            # Convert markdown to HTML first, then to plain text
            html = markdown.markdown(md_text)
            h = html2text.HTML2Text()
            h.ignore_links = True
            return h.handle(html).strip()
        except Exception as e:
            logger.error(f"Error extracting Markdown text: {str(e)}")
            return content.decode("utf-8", errors="ignore")

    def _extract_html_text(self, content: bytes) -> str:
        """Extract text from HTML files"""
        try:
            html_content = content.decode("utf-8")
            h = html2text.HTML2Text()
            h.ignore_links = True
            h.ignore_images = True
            return h.handle(html_content).strip()
        except Exception as e:
            logger.error(f"Error extracting HTML text: {str(e)}")
            return content.decode("utf-8", errors="ignore")

    def _extract_csv_text(self, content: bytes) -> str:
        """Extract text from CSV files"""
        try:
            csv_text = content.decode("utf-8")
            csv_file = BytesIO(csv_text.encode())
            reader = csv.reader(csv_text.splitlines())

            text = ""
            for row_num, row in enumerate(reader):
                if row_num == 0:
                    text += "Headers: " + ", ".join(row) + "\n\n"
                else:
                    text += "Row " + str(row_num) + ": " + ", ".join(row) + "\n"

            return text.strip()
        except Exception as e:
            logger.error(f"Error extracting CSV text: {str(e)}")
            return content.decode("utf-8", errors="ignore")

    def _extract_json_text(self, content: bytes) -> str:
        """Extract text from JSON files"""
        try:
            json_text = content.decode("utf-8")
            json_data = json.loads(json_text)

            # Convert JSON to readable text format
            return self._json_to_text(json_data)
        except Exception as e:
            logger.error(f"Error extracting JSON text: {str(e)}")
            return content.decode("utf-8", errors="ignore")

    def _json_to_text(self, data: Any, indent: int = 0) -> str:
        """Convert JSON data to readable text format"""
        text = ""
        prefix = "  " * indent

        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    text += f"{prefix}{key}:\n"
                    text += self._json_to_text(value, indent + 1)
                else:
                    text += f"{prefix}{key}: {value}\n"
        elif isinstance(data, list):
            for i, item in enumerate(data):
                text += f"{prefix}Item {i + 1}:\n"
                text += self._json_to_text(item, indent + 1)
        else:
            text += f"{prefix}{data}\n"

        return text


class AssignmentDocumentParser:
    """AI-powered parser for extracting existing assignment questions from documents"""

    def __init__(self):
        self.client = OpenAI()
        self.model = "gpt-5"

    def parse_pdf_images_to_assignment(
        self,
        pdf_content: bytes,
        file_name: str,
        generation_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Parse PDF pages directly as images to extract assignment questions with diagram support.
        This method sends all PDF page images to the LLM in a single call for better diagram detection.

        Args:
            pdf_content: Raw PDF file content (bytes)
            file_name: Original file name for context
            generation_options: Additional options for parsing (mostly ignored for extraction)

        Returns:
            Dictionary containing assignment data with extracted questions and diagram metadata
        """
        try:
            # Convert PDF pages to images using Poppler
            images = convert_from_bytes(pdf_content, dpi=200)
            logger.info(
                f"Converted PDF to {len(images)} images for question extraction"
            )

            # Convert all images to base64
            image_contents = []
            for page_num, image in enumerate(images, 1):
                buffered = BytesIO()
                image.save(buffered, format="PNG")
                img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
                image_contents.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_base64}"},
                    }
                )

            # Build prompt for question extraction from images (no bbox from GPT-5)
            prompt_text = f"""
                Analyze the following {len(images)}-page PDF document and extract ALL existing assignment questions, exercises, problems, or assessment items.

                Document: {file_name}

                CRITICAL INSTRUCTIONS:
                1. EXTRACT only existing questions - do NOT create new ones
                2. Preserve exact question text as written in the document
                3. Map question types appropriately:
                - multiple-choice: Questions with options (A, B, C, D or 1, 2, 3, 4)
                - fill-blank: Questions with blanks (e.g., "The capital of France is ___")
                - short-answer: Brief responses (1-2 sentences)
                - numerical: Questions requiring numeric answers
                - long-answer: Extended written responses (paragraphs)
                - true-false: Binary true/false questions
                - code-writing: Questions requiring code solutions
                - diagram-analysis: Questions involving diagram interpretation
                - multi-part: Questions with sub-parts (a, b, c) or (i, ii, iii)

                4. For questions with DIAGRAMS/IMAGES:
                - Set hasDiagram: true
                - Provide diagram metadata in the "diagram" field with:
                  * page_number: Page where diagram appears (1-indexed)
                  * caption: Descriptive label or caption for the diagram

                5. Extract all information:
                - Question text (without question numbers or marks)
                - Multiple choice options (without option letters/numbers)
                - Correct answers or solutions (if present, generate if not)
                - For multiple choice: correctAnswer should be index string ("0", "1", "2", "3")
                - For multi-part: provide empty string for correctAnswer (answers in subquestions)
                - Point values
                - Grading rubrics (generate if not present)
                - Assignment title and description

                6. Multi-part questions:
                - Use type "multi-part"
                - Structure subquestions properly
                - rubricType: "per-subquestion"
                - Main question rubric not required, but required for all non-multi-part subquestions

                7. Regular questions:
                - rubricType: "overall"
                - rubric is required

                8. Code content:
                - Set hasCode: true
                - Specify codeLanguage
                - Extract code in the code field

                Return the structured data according to the JSON schema.
            """

            # Get the JSON schema for the response
            response_schema = get_assignment_parsing_schema(
                "pdf_image_parsing_response_no_bbox"
            )

            # Build multimodal message content
            user_content = [{"type": "text", "text": dedent(prompt_text).strip()}]
            user_content.extend(image_contents)

            # Call OpenAI with all images in one request
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": dedent(DOCUMENT_PARSER_SYSTEM_PROMPT),
                    },
                    {"role": "user", "content": user_content},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_schema["name"],
                        "schema": response_schema,
                    },
                },
            )

            # Parse the response
            response_text = response.choices[0].message.content
            logger.info(f"Response text: {response_text}")
            if not response_text:
                raise ValueError("Empty response from AI")

            try:
                parsed_data = json.loads(response_text)
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                logger.error(f"Raw response length: {len(response_text)}")
                raise ValueError("Failed to parse AI response as JSON")

            # Validate and normalize the response
            result = self._normalize_assignment_data(parsed_data, file_name)

            # Enrich with bounding boxes using Gemini for diagrammed questions
            try:
                from controllers.vision_gemini import detect_diagram_bbox

                page_images = images  # already computed

                def enrich_question(q: Dict[str, Any]) -> Dict[str, Any]:
                    if q.get("hasDiagram") and isinstance(q.get("diagram"), dict):
                        diagram = q["diagram"]
                        page_number = diagram.get("page_number")
                        bbox = diagram.get("bounding_box")
                        if page_number and not bbox:
                            if 1 <= page_number <= len(page_images):
                                page_img = page_images[page_number - 1]
                                try:
                                    predicted_bbox = detect_diagram_bbox(
                                        page_img, q.get("question", "")
                                    )
                                    if (
                                        isinstance(predicted_bbox, list)
                                        and len(predicted_bbox) == 4
                                    ):
                                        diagram["bounding_box"] = [
                                            float(predicted_bbox[0]),
                                            float(predicted_bbox[1]),
                                            float(predicted_bbox[2]),
                                            float(predicted_bbox[3]),
                                        ]
                                except Exception as _e:
                                    logger.warning(
                                        f"Gemini bbox detection failed: {_e}"
                                    )

                    # Recurse into subquestions
                    if isinstance(q.get("subquestions"), list):
                        q["subquestions"] = [
                            enrich_question(sq) for sq in q["subquestions"]
                        ]
                    return q

                questions = result.get("questions", [])
                result["questions"] = [enrich_question(q) for q in questions]
            except Exception as e:
                logger.warning(f"Skipping Gemini bbox enrichment due to error: {e}")

            logger.info(
                f"Successfully extracted {len(result.get('questions', []))} questions from PDF images"
            )

            return result

        except Exception as e:
            logger.error(f"Error parsing PDF images: {str(e)}")
            raise

    def parse_non_pdf_document_to_assignment(
        self,
        document_content: bytes,
        file_name: str,
        file_type: str,
        user_id: str,
        generation_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Parse non-PDF documents (DOCX, MD, HTML, CSV, JSON, TXT) to extract assignment questions.

        Args:
            document_content: Raw document content (bytes)
            file_name: Original file name
            file_type: MIME type
            user_id: User ID for S3 storage paths
            generation_options: Additional parsing options

        Returns:
            Dictionary containing assignment data with extracted questions
        """
        try:
            # Extract text content based on file type
            processor = DocumentProcessor()

            # Special handling for DOCX: extract images first
            extracted_images = []
            if (
                file_type
                == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ):
                extracted_images = self._extract_docx_images(document_content, user_id)

            # Extract text content from document
            # Use base64 encoding as expected by DocumentProcessor
            file_content_b64 = base64.b64encode(document_content).decode("utf-8")
            document_text = processor.extract_text_from_file(
                file_content_b64, file_name, file_type
            )

            # For text-based formats with S3 URLs, detect them
            s3_urls = []
            if file_type in [
                "text/markdown",
                "text/html",
                "text/csv",
                "application/json",
            ]:
                s3_urls = self._detect_s3_urls(document_text)

            # Build prompt based on document type
            if file_type == "text/plain":
                # TXT: No diagram support
                prompt = f"""
                    Analyze the following text document and extract ALL existing assignment questions.

                    Document: {file_name}

                    Content:
                    ---
                    {document_text}
                    ---

                    INSTRUCTIONS:
                    - EXTRACT only existing questions - do NOT create new ones
                    - Map question types appropriately (multiple-choice, short-answer, long-answer, etc.)
                    - Extract all information: question text, correct answers, points, rubrics
                    - For multiple choice: correctAnswer should be index string ("0", "1", "2", "3")
                    - Generate rubrics if not present
                    - NO DIAGRAM SUPPORT for TXT files (hasDiagram must be false)

                    Return the structured data according to the JSON schema.
                """
            elif file_type in [
                "text/markdown",
                "text/html",
                "text/csv",
                "application/json",
            ]:
                # MD/HTML/CSV/JSON: Support S3 URLs for diagrams
                s3_urls_info = (
                    "\n".join([f"- {url}" for url in s3_urls])
                    if s3_urls
                    else "None detected"
                )
                prompt = f"""
                    Analyze the following document and extract ALL existing assignment questions.

                    Document: {file_name}
                    Type: {file_type}

                    Detected S3 URLs in content:
                    {s3_urls_info}

                    Content:
                    ---
                    {document_text}
                    ---

                    INSTRUCTIONS:
                    - EXTRACT only existing questions - do NOT create new ones
                    - Map question types appropriately
                    - Extract all information: question text, correct answers, points, rubrics
                    - For diagrams: If a question references an S3 URL (image), set:
                      * hasDiagram: true
                      * diagram.s3_url: the full S3 URL
                      * diagram.s3_key: null
                      * diagram.caption: description of the image
                      * NO bounding_box or page_number for URL-based diagrams
                    - For multiple choice: correctAnswer should be index string ("0", "1", "2", "3")
                    - Generate rubrics if not present

                    Return the structured data according to the JSON schema.
                """
            else:
                # DOCX: Support embedded images
                images_info = (
                    "\n".join(
                        [
                            f"- Image {img['image_id']}: {img['s3_key']}"
                            for img in extracted_images
                        ]
                    )
                    if extracted_images
                    else "None"
                )
                prompt = f"""
                    Analyze the following DOCX document and extract ALL existing assignment questions.

                    Document: {file_name}

                    Extracted images (already uploaded to S3):
                    {images_info}

                    Content:
                    ---
                    {document_text}
                    ---

                    INSTRUCTIONS:
                    - EXTRACT only existing questions - do NOT create new ones
                    - Map question types appropriately
                    - Extract all information: question text, correct answers, points, rubrics
                    - For diagrams/images in the document:
                      * hasDiagram: true
                      * diagram.s3_key: use the s3_key from extracted images list above
                      * diagram.s3_url: null
                      * diagram.caption: description of the image
                      * NO bounding_box or page_number for DOCX images
                    - For multiple choice: correctAnswer should be index string ("0", "1", "2", "3")
                    - Generate rubrics if not present

                    Return the structured data according to the JSON schema.
                """

            # Get the JSON schema for the response
            response_schema = get_assignment_parsing_schema("non_pdf_parsing_response")

            # Call OpenAI for parsing
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": dedent(DOCUMENT_PARSER_SYSTEM_PROMPT),
                    },
                    {"role": "user", "content": dedent(prompt).strip()},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_schema["name"],
                        "schema": response_schema,
                    },
                },
            )

            # Parse the response
            response_text = response.choices[0].message.content
            if not response_text:
                raise ValueError("Empty response from AI")

            try:
                parsed_data = json.loads(response_text)
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                raise ValueError("Failed to parse AI response as JSON")

            # Validate and normalize the response
            result = self._normalize_assignment_data(parsed_data, file_name)
            logger.info(
                f"Successfully extracted {len(result.get('questions', []))} questions from {file_type}"
            )

            return result

        except Exception as e:
            logger.error(f"Error parsing non-PDF document: {str(e)}")
            raise

    def parse_document_to_assignment(
        self,
        document_text: str,
        file_name: str,
        generation_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Parse a document and extract existing assignment questions using AI

        Args:
            document_text: Extracted text content from the document
            file_name: Original file name for context
            generation_options: Additional options for parsing (mostly ignored for extraction)

        Returns:
            Dictionary containing assignment data with extracted questions
        """
        try:
            # Try the standard approach first
            return self._parse_with_standard_approach(document_text, file_name)

        except Exception as e:
            logger.warning(f"Standard parsing failed for {file_name}: {str(e)}")
            logger.info("Attempting fallback parsing with reduced content...")

            # Fallback: try with reduced content if the document is very large
            try:
                return self._parse_with_reduced_content(document_text, file_name)
            except Exception as fallback_error:
                logger.error(
                    f"Fallback parsing also failed for {file_name}: {str(fallback_error)}"
                )
                raise e  # Re-raise the original error

    def _parse_with_standard_approach(
        self, document_text: str, file_name: str
    ) -> Dict[str, Any]:
        """Standard parsing approach with full document content"""
        # Create the extraction prompt
        prompt = create_extraction_prompt(document_text, file_name)

        # Get the JSON schema for the response with dynamic naming
        response_schema = get_assignment_parsing_schema("document_parsing_response")

        # Call OpenAI to parse the document
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": dedent(DOCUMENT_PARSER_SYSTEM_PROMPT),
                },
                {"role": "user", "content": dedent(prompt).strip()},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema["name"],
                    "schema": response_schema,
                },
            },
        )

        # Parse the response
        response_text = response.choices[0].message.content
        if not response_text:
            raise ValueError("Empty response from AI")

        try:
            parsed_data = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            logger.error(f"Raw response length: {len(response_text)}")
            logger.error(f"Raw response (first 1000 chars): {response_text[:1000]}")
            logger.error(f"Raw response (last 1000 chars): {response_text[-1000:]}")

            # Try to fix common JSON issues
            try:
                # Check if response was truncated
                if not response_text.strip().endswith("}"):
                    logger.warning(
                        "Response appears to be truncated, attempting to fix..."
                    )
                    # Try to find the last complete object
                    last_brace = response_text.rfind("}")
                    if last_brace > 0:
                        # Try to close the JSON structure
                        fixed_response = response_text[: last_brace + 1]
                        parsed_data = json.loads(fixed_response)
                        logger.info("Successfully fixed truncated JSON response")
                    else:
                        raise ValueError("Response is too truncated to fix")
                else:
                    raise ValueError("Failed to parse AI response as JSON")
            except (json.JSONDecodeError, ValueError) as fix_error:
                logger.error(f"Failed to fix JSON: {fix_error}")
                raise ValueError(
                    "Failed to parse AI response as JSON and unable to fix truncation"
                )

        # Validate and normalize the response
        return self._normalize_assignment_data(parsed_data, file_name)

    def _parse_with_reduced_content(
        self, document_text: str, file_name: str
    ) -> Dict[str, Any]:
        """Fallback parsing with reduced content to avoid token limits"""
        # Reduce document content significantly
        max_doc_length = 10000  # Much smaller limit for fallback
        if len(document_text) > max_doc_length:
            # Try to find a good breaking point (e.g., end of a question)
            truncated_text = document_text[:max_doc_length]
            # Look for the last complete question or section
            last_question = max(
                truncated_text.rfind("Question"),
                truncated_text.rfind("Problem"),
                truncated_text.rfind("Exercise"),
                truncated_text.rfind("Part"),
            )
            if last_question > max_doc_length * 0.7:  # If we found a good break point
                document_text = (
                    truncated_text[:last_question]
                    + "... [document truncated for processing]"
                )
            else:
                document_text = (
                    truncated_text + "... [document truncated for processing]"
                )

        # Create a simpler prompt for reduced content
        prompt = create_fallback_prompt(document_text, file_name)

        # Get the JSON schema for fallback parsing with dynamic naming
        fallback_schema = get_assignment_parsing_schema(
            "assignment_parsing_fallback_response"
        )

        # Call OpenAI with reduced content
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": dedent(FALLBACK_PARSER_SYSTEM_PROMPT),
                },
                {"role": "user", "content": dedent(prompt).strip()},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": fallback_schema["name"],
                    "schema": fallback_schema,
                },
            },
            max_completion_tokens=4000,  # Smaller token limit for fallback
        )

        response_text = response.choices[0].message.content
        if not response_text:
            raise ValueError("Empty response from AI")

        try:
            parsed_data = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Fallback JSON decode error: {e}")
            raise ValueError("Failed to parse fallback AI response as JSON")

        return self._normalize_assignment_data(parsed_data, file_name)

    def _normalize_assignment_data(
        self, data: Dict[str, Any], file_name: str
    ) -> Dict[str, Any]:
        """Normalize and validate the parsed assignment data to match frontend schema"""
        try:
            if not isinstance(data, dict):
                raise ValueError("Response is not a valid dictionary")

            # Title/description defaults
            if "title" not in data or not data["title"]:
                data["title"] = f"Assignment from {file_name.replace('.', ' ').title()}"
            if "description" not in data or not data["description"]:
                data[
                    "description"
                ] = "Imported from document. Please review for accuracy."

            # Questions list
            questions = data.get("questions", [])
            if not isinstance(questions, list):
                questions = []

            def normalize_question_fields(
                src: Dict[str, Any], is_subquestion: bool = False
            ) -> Dict[str, Any]:
                """Normalize question fields to match frontend schema"""
                out: Dict[str, Any] = {}

                # Basic fields
                out["id"] = src.get("id", 1)
                out["type"] = src.get("type", "short-answer")
                out["question"] = src.get("question", "")
                out["points"] = self._parse_points(src.get("points", 0))
                out["rubric"] = src.get("rubric", "")
                out["order"] = src.get("order", 1)

                # Options (for multiple-choice)
                options = src.get("options", [])
                if isinstance(options, list):
                    out["options"] = [str(opt) for opt in options]
                else:
                    out["options"] = []

                # Correct answer - handle both single and multiple correct
                ca = (
                    src.get("correctAnswer")
                    or src.get("correct_answer")
                    or src.get("answer")
                )
                out["correctAnswer"] = str(ca) if ca is not None else ""

                # Multiple correct support
                out["allowMultipleCorrect"] = src.get("allowMultipleCorrect", False)
                multiple_correct = src.get("multipleCorrectAnswers", [])
                if isinstance(multiple_correct, list):
                    out["multipleCorrectAnswers"] = [
                        str(ans) for ans in multiple_correct
                    ]
                else:
                    out["multipleCorrectAnswers"] = []

                # Code and diagram flags
                out["hasCode"] = src.get("hasCode", False)
                # Derive hasDiagram from presence of diagram object if not explicitly provided
                has_diagram_flag = src.get("hasDiagram", False)
                out["codeLanguage"] = src.get("codeLanguage", "")
                out["outputType"] = src.get("outputType", "")
                out["rubricType"] = src.get("rubricType", "per-subquestion")

                # Code content
                code_text = src.get("code", "")
                if code_text:
                    out["code"] = str(code_text)
                    out["hasCode"] = True
                else:
                    out["code"] = ""

                # Diagram metadata
                diagram = src.get("diagram")
                if diagram and isinstance(diagram, dict):
                    # Normalize diagram metadata
                    normalized_diagram = {}

                    # Page number (for PDF/DOCX)
                    if "page_number" in diagram:
                        normalized_diagram["page_number"] = diagram["page_number"]

                    # Bounding box (for PDF/DOCX)
                    if "bounding_box" in diagram and isinstance(
                        diagram["bounding_box"], list
                    ):
                        normalized_diagram["bounding_box"] = diagram["bounding_box"]

                    # Caption
                    if "caption" in diagram:
                        normalized_diagram["caption"] = str(diagram["caption"])

                    # S3 key (for extracted diagrams from PDF/DOCX)
                    if "s3_key" in diagram:
                        normalized_diagram["s3_key"] = diagram["s3_key"]

                    # S3 URL (for URL-based diagrams from MD/HTML/CSV/JSON)
                    if "s3_url" in diagram:
                        normalized_diagram["s3_url"] = diagram["s3_url"]

                    out["diagram"] = normalized_diagram
                    has_diagram_flag = True
                elif has_diagram_flag:
                    # If hasDiagram is true but no diagram object, create empty one
                    out["diagram"] = None

                out["hasDiagram"] = bool(has_diagram_flag)

                return out

            def normalize_subquestions(subqs: Any) -> list:
                """Normalize subquestions for multi-part questions"""
                if not isinstance(subqs, list):
                    return []
                normalized_list: list = []
                for sub_index, sub in enumerate(subqs):
                    if not isinstance(sub, dict):
                        continue
                    nq = normalize_question_fields(sub, is_subquestion=True)
                    nq["id"] = sub.get("id", sub_index + 1)

                    # Handle nested subquestions (sub-sub-questions)
                    nested_subqs_src = (
                        sub.get("subquestions")
                        or sub.get("sub_questions")
                        or sub.get("parts")
                    )
                    if nested_subqs_src and isinstance(nested_subqs_src, list):
                        nested_normalized = []
                        for nested_index, nested_sub in enumerate(nested_subqs_src):
                            if not isinstance(nested_sub, dict):
                                continue
                            nested_nq = normalize_question_fields(
                                nested_sub, is_subquestion=True
                            )
                            nested_nq["id"] = nested_sub.get("id", nested_index + 1)
                            nested_normalized.append(nested_nq)
                        if nested_normalized:
                            nq["subquestions"] = nested_normalized

                    normalized_list.append(nq)
                return normalized_list

            normalized_questions: list = []
            total_points = 0

            for i, question in enumerate(questions):
                if not isinstance(question, dict):
                    continue

                # Check if it's a multi-part question
                subqs_src = (
                    question.get("subquestions")
                    or question.get("sub_questions")
                    or question.get("parts")
                )
                is_multi_part = bool(subqs_src)

                # Normalize main question
                normalized_q = normalize_question_fields(question)
                normalized_q["id"] = question.get("id", i + 1)
                normalized_q["order"] = question.get("order", i + 1)

                # Set type to multi-part if subquestions exist
                if is_multi_part:
                    normalized_q["type"] = "multi-part"

                # Handle subquestions for multi-part questions
                if is_multi_part:
                    subqs = normalize_subquestions(subqs_src)
                    if subqs:
                        normalized_q["subquestions"] = subqs

                normalized_questions.append(normalized_q)
                total_points += normalized_q["points"] or 0

            data["questions"] = normalized_questions
            data["total_points"] = total_points

            data["file_info"] = {
                "original_filename": file_name,
                "processed_at": str(json.dumps(None, default=str)),
                "question_count": len(normalized_questions),
            }

            return data

        except Exception as e:
            logger.error(f"Error normalizing assignment data: {str(e)}")
            raise ValueError(f"Failed to normalize assignment data: {str(e)}")

    def _parse_points(self, points: Any) -> float:
        """Parse points from various formats"""
        if isinstance(points, (int, float)):
            return float(points)

        if isinstance(points, str):
            # Extract numeric value from strings like "(10 points)" or "10 pts"
            match = re.search(r"(\d+(?:\.\d+)?)", points)
            if match:
                return float(match.group(1))

        return 0.0

    def _extract_docx_images(
        self, docx_content: bytes, user_id: str
    ) -> List[Dict[str, Any]]:
        """
        Extract embedded images from DOCX file and upload to S3.

        Returns list of image metadata with s3_key and temporary reference ID.
        """
        extracted_images = []

        try:
            doc_file = BytesIO(docx_content)
            doc = docx.Document(doc_file)

            # Extract images from document relationships
            for rel_id, rel in doc.part.rels.items():
                if "image" in rel.target_ref:
                    try:
                        image_data = rel.target_part.blob

                        # Determine image format
                        image_format = "png"
                        if rel.target_ref.endswith(".jpg") or rel.target_ref.endswith(
                            ".jpeg"
                        ):
                            image_format = "jpeg"
                        elif rel.target_ref.endswith(".gif"):
                            image_format = "gif"

                        # Generate unique ID for this image
                        image_id = str(uuid.uuid4())

                        # Create temporary file
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=f".{image_format}"
                        ) as tmp:
                            tmp.write(image_data)
                            tmp_path = tmp.name

                        # Upload to S3
                        s3_key = f"users/{user_id}/temp_docx_images/{image_id}.{image_format}"
                        content_type = f"image/{image_format}"

                        if s3_client and AWS_S3_BUCKET:
                            s3_upload_file(tmp_path, s3_key, content_type=content_type)

                            extracted_images.append(
                                {
                                    "image_id": image_id,
                                    "s3_key": s3_key,
                                    "format": image_format,
                                    "rel_id": rel_id,
                                }
                            )

                            logger.info(
                                f"Extracted DOCX image {image_id} to S3: {s3_key}"
                            )

                        # Clean up temp file
                        os.unlink(tmp_path)

                    except Exception as e:
                        logger.error(f"Error extracting DOCX image {rel_id}: {str(e)}")
                        continue

            logger.info(f"Extracted {len(extracted_images)} images from DOCX")
            return extracted_images

        except Exception as e:
            logger.error(f"Error processing DOCX images: {str(e)}")
            return []

    def _detect_s3_urls(self, content: str) -> List[str]:
        """
        Detect S3 URLs in text content (for MD, HTML, CSV, JSON formats).

        Returns list of S3 URLs found in the content.
        """
        # Pattern to match S3 URLs (both s3:// and https://s3.amazonaws.com or https://bucket.s3.amazonaws.com)
        s3_url_patterns = [
            r"s3://[a-zA-Z0-9.\-_/]+",
            r"https://s3[.-][a-zA-Z0-9.\-_]+\.amazonaws\.com/[a-zA-Z0-9.\-_/]+",
            r"https://[a-zA-Z0-9.\-_]+\.s3[.-][a-zA-Z0-9.\-_]*\.amazonaws\.com/[a-zA-Z0-9.\-_/]+",
        ]

        found_urls = []
        for pattern in s3_url_patterns:
            matches = re.findall(pattern, content)
            found_urls.extend(matches)

        # Remove duplicates while preserving order
        unique_urls = list(dict.fromkeys(found_urls))

        logger.info(f"Detected {len(unique_urls)} S3 URLs in content")
        return unique_urls

    def extract_and_upload_diagrams(
        self,
        parsed_data: Dict[str, Any],
        file_content: bytes,
        file_type: str,
        user_id: str,
        assignment_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract diagrams from source document and upload to S3.
        Updates question JSON with s3_key for each diagram.

        Args:
            parsed_data: Parsed assignment data with diagram metadata
            file_content: Raw file content (bytes)
            file_type: MIME type of the file
            user_id: User ID for S3 path organization
            assignment_id: Optional assignment ID (if None, uses user_id path)

        Returns:
            Updated parsed_data with s3_keys populated
        """
        try:
            # Use assignment_id if provided, otherwise use user_id for temporary storage
            base_s3_path = (
                f"assignments/{assignment_id}/question_diagrams"
                if assignment_id
                else f"users/{user_id}/temp_diagrams"
            )

            questions = parsed_data.get("questions", [])

            # For PDF: extract diagrams using bounding boxes
            if file_type == "application/pdf":
                updated_questions = self._extract_pdf_diagrams(
                    questions, file_content, base_s3_path
                )
                parsed_data["questions"] = updated_questions

            # For DOCX: diagrams already extracted, just update references
            elif (
                file_type
                == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ):
                # DOCX images are already uploaded during parsing
                # Just ensure the s3_keys are properly set
                pass

            # For MD/HTML/CSV/JSON: S3 URLs already detected, no extraction needed
            elif file_type in [
                "text/markdown",
                "text/html",
                "text/csv",
                "application/json",
            ]:
                # s3_url already populated by LLM, no extraction needed
                pass

            logger.info(f"Diagram extraction completed for {file_type}")
            return parsed_data

        except Exception as e:
            logger.error(f"Error in extract_and_upload_diagrams: {str(e)}")
            # Return original data if extraction fails
            return parsed_data

    def _extract_pdf_diagrams(
        self, questions: List[Dict[str, Any]], pdf_content: bytes, base_s3_path: str
    ) -> List[Dict[str, Any]]:
        """
        Extract diagrams from PDF using bounding boxes and upload to S3.
        """
        try:
            logger.info(
                f"Starting diagram extraction for {len(questions)} questions with base_s3_path: {base_s3_path}"
            )

            # Convert PDF pages to images
            images = convert_from_bytes(pdf_content, dpi=200)
            logger.info(f"Converted PDF to {len(images)} images for diagram extraction")
            logger.info(f"PDF image dimensions: {[img.size for img in images[:3]]}")

            def process_question_diagrams(question: Dict[str, Any]) -> Dict[str, Any]:
                """Recursively process diagrams in questions and subquestions"""
                question_id = question.get("id", "unknown")
                logger.info(f"Processing question {question_id} for diagrams")

                # Process main question diagram
                if question.get("hasDiagram") and question.get("diagram"):
                    diagram = question["diagram"]
                    bounding_box = diagram.get("bounding_box")
                    page_number = diagram.get("page_number", 1)

                    logger.info(
                        f"Q{question_id}: hasDiagram=True, bounding_box={bounding_box}, page_number={page_number}, existing_s3_key={diagram.get('s3_key')}"
                    )

                    if bounding_box and not diagram.get("s3_key"):
                        # Extract diagram from PDF
                        if 1 <= page_number <= len(images):
                            try:
                                logger.info(
                                    f"Q{question_id}: Extracting diagram from page {page_number} (0-indexed: {page_number-1})"
                                )

                                page_img: Image.Image = images[
                                    page_number - 1
                                ]  # Convert 1-indexed to 0-indexed

                                logger.info(
                                    f"Q{question_id}: Page image size: {page_img.size} (width={page_img.width}, height={page_img.height})"
                                )

                                # Crop using bounding box - handle both old and new formats
                                if (
                                    isinstance(bounding_box, list)
                                    and len(bounding_box) == 4
                                ):
                                    # New format: [xmin, ymin, xmax, ymax]
                                    ymin = bounding_box[0] / 1000 * page_img.height
                                    xmin = bounding_box[1] / 1000 * page_img.width
                                    ymax = bounding_box[2] / 1000 * page_img.height
                                    xmax = bounding_box[3] / 1000 * page_img.width

                                    logger.info(
                                        f"Q{question_id}: Bounding box values: {bounding_box}"
                                    )
                                    logger.info(
                                        f"Q{question_id}: Computed crop coordinates: ymin={ymin:.2f}, xmin={xmin:.2f}, ymax={ymax:.2f}, xmax={xmax:.2f}"
                                    )

                                    cropped = page_img.crop((xmin, ymin, xmax, ymax))
                                    logger.info(
                                        f"Q{question_id}: Cropped image size: {cropped.size}"
                                    )
                                else:
                                    raise ValueError("Invalid bounding box format")

                                # Save to temporary file
                                diagram_id = str(uuid.uuid4())
                                logger.info(
                                    f"Q{question_id}: Generated diagram_id={diagram_id}"
                                )

                                with tempfile.NamedTemporaryFile(
                                    delete=False, suffix=".jpg"
                                ) as tmp:
                                    cropped.save(tmp, "JPEG", quality=95)
                                    tmp_path = tmp.name
                                    logger.info(
                                        f"Q{question_id}: Saved cropped diagram to temp file: {tmp_path}"
                                    )

                                # Upload to S3
                                s3_key = (
                                    f"{base_s3_path}/q{question_id}_{diagram_id}.jpg"
                                )
                                logger.info(
                                    f"Q{question_id}: Prepared S3 key: {s3_key}"
                                )

                                if s3_client and AWS_S3_BUCKET:
                                    logger.info(
                                        f"Q{question_id}: Uploading to S3 bucket: {AWS_S3_BUCKET}"
                                    )
                                    s3_upload_file(
                                        tmp_path, s3_key, content_type="image/jpeg"
                                    )
                                    diagram["s3_key"] = s3_key
                                    diagram["s3_url"] = None
                                    logger.info(
                                        f"Uploaded diagram for Q{question_id} to {s3_key}"
                                    )

                                # Clean up temp file
                                os.unlink(tmp_path)
                                logger.info(f"Q{question_id}: Cleaned up temp file")

                            except Exception as e:
                                logger.error(
                                    f"Error extracting diagram for Q{question.get('id')}: {str(e)}"
                                )
                                import traceback

                                logger.info(f"Traceback: {traceback.format_exc()}")
                        else:
                            logger.warning(
                                f"Q{question_id}: Page number {page_number} out of range (1-{len(images)})"
                            )
                    elif not bounding_box:
                        logger.info(f"Q{question_id}: No bounding box provided")
                    elif diagram.get("s3_key"):
                        logger.info(
                            f"Q{question_id}: Diagram already has s3_key={diagram.get('s3_key')}"
                        )
                else:
                    logger.info(
                        f"Q{question_id}: hasDiagram=False or no diagram object"
                    )

                # Process subquestions recursively
                if question.get("subquestions"):
                    logger.info(
                        f"Q{question_id}: Processing {len(question['subquestions'])} subquestions"
                    )
                    updated_subquestions = []
                    for idx, subq in enumerate(question["subquestions"]):
                        logger.info(
                            f"Q{question_id}: Processing subquestion {idx+1}/{len(question['subquestions'])}"
                        )
                        updated_subq = process_question_diagrams(subq)
                        updated_subquestions.append(updated_subq)
                    question["subquestions"] = updated_subquestions
                    logger.info(
                        f"Q{question_id}: Completed processing all subquestions"
                    )

                return question

            # Process all questions
            updated_questions = []
            for idx, question in enumerate(questions):
                logger.info(f"Processing question {idx+1}/{len(questions)}")
                updated_q = process_question_diagrams(question)
                updated_questions.append(updated_q)

            logger.info(f"Completed diagram extraction for all questions")
            return updated_questions

        except Exception as e:
            logger.error(f"Error extracting PDF diagrams: {str(e)}")
            import traceback

            logger.info(f"Traceback: {traceback.format_exc()}")
            return questions
