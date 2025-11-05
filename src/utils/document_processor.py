import base64
import json
from typing import Any
from openai import OpenAI
from controllers.config import logger
import PyPDF2
import docx
from io import BytesIO
import csv
import html2text
import markdown
from pdf2image import convert_from_bytes


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
