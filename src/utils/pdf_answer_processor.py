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
            print(f"[PDF Processor] Converting PDF: {pdf_path}")
            print(
                f"[PDF Processor] Poppler path: {poppler_path or 'Using system PATH'}"
            )
            pages = convert_from_path(pdf_path, dpi=200, poppler_path=poppler_path)
            print(f"[PDF Processor] Successfully converted {len(pages)} pages")
        except Exception as e:
            print(f"[PDF Processor] ERROR: Failed to convert PDF - {str(e)}")
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
              "answer": "A",
              "diagram": null
            }},
            {{
              "question_number": "17(a)",
              "answer": "Applying coating of zinc",
              "diagram": {{
                "label": "Circuit diagram",
                "bounding_box": {{"x": 120, "y": 240, "width": 460, "height": 320, "page_number": 1}}
              }}
            }},
            {{
              "question_number": "17(b)",
              "answer": "Resistance increases with temperature",
              "diagram": null
            }},
            {{
              "question_number": "33(a)(i)",
              "answer": "Derive the expression",
              "diagram": null
            }}
          ]
        }}

        Rules:
        - DO NOT MAKE ANYTHING UP. DO NOT INCLUDE ANYTHING OTHER THAN THE ANSWER SHEET.
        - TRY TO INCLUDE THE FULL ANSWER FROM THE ANSWER SHEET.
        - CRITICAL: Preserve the EXACT question numbering from the answer sheet:
          * If numbered as "17(a)", use "17(a)"
          * If numbered as "17(b)", use "17(b)"
          * If numbered as "33(a)(i)", use "33(a)(i)"
          * If numbered as "29.1", use "29.1"
          * Simple numbers like "1", "2", "3" should stay as is
        - For multiple choice questions (MCQ):
          * Extract ONLY the option letter (A, B, C, or D)
          * DO NOT include the option text or any additional explanation
          * Example: If answer shows "C, 16 x 10^6 J", extract only "C"
          * Example: If answer shows "B, 0.3 MB", extract only "B"
        - For descriptive/long answer questions:
          * Include the full answer text from the answer sheet
        - Each item must include:
          - question_number: string (exact as written in the answer sheet)
          - answer: extracted answer (just the letter for MCQ, full text for descriptive)
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
            model="gpt-5",
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

        # Debug: Log the raw result
        print(
            f"[PDF Processor] Raw LLM result: {json.dumps(result, indent=2)[:500]}..."
        )

        # Check if answer_sheet exists
        answer_sheet = result.get("answer_sheet", [])
        if not answer_sheet:
            print(f"[PDF Processor] WARNING: Empty answer_sheet in LLM response!")
            print(f"[PDF Processor] Full result: {json.dumps(result, indent=2)}")
            return {}

        # Convert to our internal format: question_id -> answer
        answers_dict = {}
        for item in answer_sheet:
            q_num_raw = str(item.get("question_number"))
            answer_text = item.get("answer", "")
            diagram_data = item.get("diagram")

            # Normalize question number: 17(a) -> 17.1, 17(b) -> 17.2, 33(a)(i) -> 33.1.1
            q_num = self._normalize_question_number(q_num_raw)

            # Normalize MCQ answer: "C" -> "C" (keep letters as-is for grading service)
            answer_normalized = self._normalize_mcq_answer(answer_text)

            if diagram_data and diagram_data.get("bounding_box"):
                # Answer with diagram (bounding box only, s3_key to be filled by background task)
                answers_dict[q_num] = {
                    "text": answer_normalized,
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
                answers_dict[q_num] = answer_normalized

        print(f"[PDF Processor] Extracted {len(answers_dict)} answers")
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
    def _normalize_question_number(q_num: str) -> str:
        """
        Normalize question numbers from various formats to dot notation.

        Examples:
            "17(a)" -> "17.1"
            "17(b)" -> "17.2"
            "33(a)(i)" -> "33.1.1"
            "33(a)(ii)" -> "33.1.2"
            "29.1" -> "29.1" (already normalized)
            "1" -> "1" (simple number)
        """
        import re

        # If already in dot notation or simple number, return as is
        if not re.search(r"[()]", q_num):
            return q_num

        # Replace (a), (b), (c), etc. with .1, .2, .3
        letter_map = {
            "(a)": ".1",
            "(b)": ".2",
            "(c)": ".3",
            "(d)": ".4",
            "(e)": ".5",
            "(f)": ".6",
            "(g)": ".7",
            "(h)": ".8",
        }

        # Replace (i), (ii), (iii), etc. with .1, .2, .3
        roman_map = {
            "(i)": ".1",
            "(ii)": ".2",
            "(iii)": ".3",
            "(iv)": ".4",
            "(v)": ".5",
            "(vi)": ".6",
            "(vii)": ".7",
            "(viii)": ".8",
        }

        result = q_num

        # First pass: replace letter sub-parts
        for letter, num in letter_map.items():
            result = result.replace(letter, num)

        # Second pass: replace roman numeral sub-parts
        for roman, num in roman_map.items():
            result = result.replace(roman, num)

        # Clean up any remaining parentheses
        result = result.replace("(", ".").replace(")", "")

        return result

    @staticmethod
    def _normalize_mcq_answer(answer: str) -> str:
        """
        Normalize MCQ answers to just the option letter.

        Examples:
            "C" -> "C"
            "B, 0.3 MB" -> "B"
            "A, Applying Galvanometer" -> "A"
            "D" -> "D"
            "Long descriptive answer" -> "Long descriptive answer" (unchanged)
        """
        if not answer:
            return answer

        answer = answer.strip()

        # Check if it starts with a single letter (A-D) followed by comma or space
        import re

        mcq_pattern = r"^([A-Da-d])[\s,]"
        match = re.match(mcq_pattern, answer)

        if match:
            # Extract just the letter
            return match.group(1).upper()

        # Check if it's just a single letter
        if len(answer) == 1 and answer.upper() in "ABCD":
            return answer.upper()

        # Otherwise return as is (descriptive answer)
        return answer

    @staticmethod
    def _pil_image_to_data_url(img: Image.Image) -> str:
        """Convert PIL image to base64 data URL."""
        buffered = BytesIO()
        img.save(buffered, format="JPEG")
        encoded = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"
