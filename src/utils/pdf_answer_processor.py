"""
PDF Answer Sheet Processor - converts PDF submissions to JSON answers format.
Adapted from vidyaai_grading_experiments/PDFAnswerSheetToJSON.py
"""

import os
import base64
import json
from io import BytesIO
from typing import List, Dict, Any, Optional
from textwrap import dedent

from openai import OpenAI
from pdf2image import convert_from_path
from PIL import Image


class PDFAnswerProcessor:
    """Process PDF answer sheets into structured JSON format."""

    def __init__(self, api_key: Optional[str] = None):
        if api_key:
            self.client = OpenAI(api_key=api_key)
        else:
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def process_pdf_to_json(self, pdf_path: str) -> Dict[str, Any]:
        """
        Convert PDF answer sheet to JSON format with diagram bounding boxes.

        Returns dict with structure:
        {
            "1": "answer text",
            "2": {
                "text": "answer with diagram",
                "diagram": {
                    "bounding_box": {"x": 120, "y": 240, "width": 460, "height": 320, "page_number": 1},
                    "label": "Circuit diagram"
                }
            }
        }
        """
        # Convert PDF pages to images
        poppler_path = os.getenv("POPPLER_PATH", None)

        try:
            pages = convert_from_path(pdf_path, dpi=200, poppler_path=poppler_path)
        except Exception as e:
            raise RuntimeError(
                f"Failed to convert PDF to images. Ensure Poppler is installed. Error: {e}"
            )

        # Build multimodal prompt with all pages
        image_contents: List[dict] = []
        for page_num, page_img in enumerate(pages, 1):
            image_contents.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._pil_image_to_data_url(page_img)},
                }
            )

        system_prompt = """
        You are a precise assistant that converts answer sheets into structured JSON.
        Return only JSON, adhering strictly to the provided schema.
        """

        prompt = f"""
        Convert the following answer sheet images into a JSON object. The images are provided in order: Page 1, Page 2, Page 3, etc.

        Example JSON structure:
        {{
          "answer_sheet": [
            {{
              "question_number": "1",
              "answer": "Applying coating of zinc",
              "diagram": {{
                "label": "Circuit diagram for Q2",
                "bounding_box": {{"x": 120, "y": 240, "width": 460, "height": 320, "page_number": 1}}
              }}
            }},
            {{
              "question_number": "2",
              "answer": "increases",
              "diagram": null
            }}
          ]
        }}

        Rules:
        - DO NOT MAKE ANYTHING UP. DO NOT INCLUDE ANYTHING OTHER THAN THE ANSWER SHEET.
        - TRY TO INCLUDE THE FULL ANSWER FROM THE ANSWER SHEET.
        - Use simple question numbers (e.g., "1", "2", "3" not "1.1", "1.2" unless explicitly numbered that way).
        - Each item must include:
          - question_number: string
          - answer: extracted answer from the answer sheet
          - diagram: null if no diagram; otherwise include label and a tight bounding_box around the drawn diagram for that question only.
        - Bounding boxes must be integers in image pixel coordinates of the provided JPEGs (top-left origin).
        - CRITICAL: Each bounding_box must include a "page_number" field indicating which page (1, 2, 3, etc.) the diagram appears on.
        - If a diagram is present but unlabeled, just put "unlabeled" in the label field.
        - Preserve question order and ignore non-answer metadata.
        - Return only valid JSON that conforms to the schema.
        """

        answer_sheet_json = {
            "name": "answer_sheet_json",
            "type": "object",
            "properties": {
                "answer_sheet": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question_number": {"type": "string"},
                            "answer": {"type": "string"},
                            "diagram": {
                                "oneOf": [
                                    {"type": "null"},
                                    {
                                        "type": "object",
                                        "properties": {
                                            "label": {"type": "string"},
                                            "bounding_box": {
                                                "type": "object",
                                                "properties": {
                                                    "x": {"type": "integer"},
                                                    "y": {"type": "integer"},
                                                    "width": {"type": "integer"},
                                                    "height": {"type": "integer"},
                                                    "page_number": {"type": "integer"},
                                                },
                                                "required": [
                                                    "x",
                                                    "y",
                                                    "width",
                                                    "height",
                                                    "page_number",
                                                ],
                                            },
                                        },
                                        "required": ["label", "bounding_box"],
                                    },
                                ]
                            },
                        },
                        "required": ["question_number", "answer", "diagram"],
                    },
                }
            },
            "required": ["answer_sheet"],
        }

        completion = self.client.chat.completions.parse(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": dedent(system_prompt)},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": dedent(prompt)},
                        *image_contents,
                    ],
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": answer_sheet_json["name"],
                    "schema": answer_sheet_json,
                },
            },
        )

        result = json.loads(completion.choices[0].message.content)

        # Convert to our internal format: question_id -> answer
        answers_dict = {}
        for item in result.get("answer_sheet", []):
            q_num = str(item.get("question_number"))
            answer_text = item.get("answer", "")
            diagram_data = item.get("diagram")

            if diagram_data and diagram_data.get("bounding_box"):
                # Answer with diagram (bounding box only, s3_key to be filled by background task)
                answers_dict[q_num] = {
                    "text": answer_text,
                    "diagram": {
                        "bounding_box": diagram_data["bounding_box"],
                        "label": diagram_data.get("label", "unlabeled"),
                        "s3_key": None,  # Will be filled by background task
                        "file_id": None,
                        "filename": None,
                    },
                }
            else:
                # Text-only answer
                answers_dict[q_num] = answer_text

        return answers_dict

    def extract_diagram_from_pdf(
        self, pdf_path: str, bounding_box: Dict[str, int], output_path: str
    ) -> bool:
        """Extract a single diagram from PDF using bounding box coordinates."""
        try:
            page_num = bounding_box.get("page_number", 1)
            x = bounding_box.get("x", 0)
            y = bounding_box.get("y", 0)
            width = bounding_box.get("width", 100)
            height = bounding_box.get("height", 100)

            # Convert specific page to image
            poppler_path = os.getenv("POPPLER_PATH", None)
            pages = convert_from_path(
                pdf_path,
                dpi=200,
                first_page=page_num,
                last_page=page_num,
                poppler_path=poppler_path,
            )

            if not pages:
                return False

            page_img = pages[0]

            # Crop diagram using bounding box
            cropped = page_img.crop((x, y, x + width, y + height))

            # Save as JPEG
            cropped.save(output_path, "JPEG", quality=95)
            return True

        except Exception as e:
            print(f"Error extracting diagram: {e}")
            return False

    @staticmethod
    def _pil_image_to_data_url(img: Image.Image) -> str:
        """Convert PIL image to base64 data URL."""
        buffered = BytesIO()
        img.save(buffered, format="JPEG")
        encoded = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"
