import base64
import json
import re
from typing import Dict, Any, Optional
from openai import OpenAI
from controllers.config import logger
import PyPDF2
import docx
from io import BytesIO
import csv
import html2text
import markdown
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
        """Extract text from PDF files"""
        try:
            pdf_file = BytesIO(content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)

            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"

            return text.strip()
        except Exception as e:
            logger.error(f"Error extracting PDF text: {str(e)}")
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
                    "content": DOCUMENT_PARSER_SYSTEM_PROMPT,
                },
                {"role": "user", "content": prompt},
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
                    "content": FALLBACK_PARSER_SYSTEM_PROMPT,
                },
                {"role": "user", "content": prompt},
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

                # Correct answer
                ca = (
                    src.get("correctAnswer")
                    or src.get("correct_answer")
                    or src.get("answer")
                )
                out["correctAnswer"] = str(ca) if ca is not None else ""

                # Code and diagram flags
                out["hasCode"] = src.get("hasCode", False)
                out["hasDiagram"] = src.get("hasDiagram", False)
                out["codeLanguage"] = src.get("codeLanguage", "")
                out["outputType"] = src.get("outputType", "")
                out["analysisType"] = src.get("analysisType", "")
                out["rubricType"] = src.get("rubricType", "per-subquestion")

                # Code content
                code_text = src.get("code", "")
                if code_text:
                    out["code"] = str(code_text)
                    out["hasCode"] = True
                else:
                    out["code"] = ""

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
