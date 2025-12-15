"""
PDF Answer Sheet Processor - converts PDF submissions to JSON answers format.
Adapted from vidyaai_grading_experiments/PDFAnswerSheetToJSON.py
"""

import os
import base64
import json
import uuid
import tempfile
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

    def process_pdf_to_json(
        self, pdf_path: str, questions: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Convert PDF answer sheet to JSON format with diagram bounding boxes.

        Returns dict with structure:
        {
            "1": "answer text",
            "2": {
                "text": "answer with diagram",
                "diagram": {
                    "label": "Circuit diagram",
                    "page_number": 1
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

        # Get question numbers list if questions provided
        question_numbers = self._get_question_numbers(questions) if questions else None

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
                "page_number": 2
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
        - CRITICAL: DO NOT preserve the EXACT question numbering from the answer sheet:
          * If numbered as "17(a)", use "17.1"
          * If numbered as "17(b)", use "17.2"
          * If numbered as "33(a)(i)", use "33.1.1"
          * If numbered as "29.1", use "29.1"
          * Simple numbers like "1", "2", "3" should stay as is
          * Here is the list of question numbers to extract answers for: {', '.join(map(str, question_numbers)) if question_numbers else 'All questions found in the answer sheet'}
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
          - diagram: null if no diagram; otherwise include label and the page number where the diagram appears for that question only.
        - Each diagram must include a "page_number" field indicating which page (1, 2, 3, etc.) the diagram appears on.
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
                                            "page_number": {"type": "integer"},
                                        },
                                        "required": [
                                            "label",
                                            "page_number",
                                        ],
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
        print(f"[PDF Processor] Raw LLM result: {json.dumps(result, indent=2)[:50]}...")

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

            if diagram_data and diagram_data.get("page_number") is not None:
                # Answer with diagram (bounding box only, s3_key to be filled by background task)
                answers_dict[q_num] = {
                    "text": answer_normalized,
                    "diagram": {
                        "bounding_box": None,  # To be filled later
                        "label": diagram_data.get("label", "unlabeled"),
                        "page_number": diagram_data.get("page_number", None),
                        "s3_key": None,  # Will be filled by background task
                        "file_id": None,
                        "filename": None,
                    },
                }
            else:
                # Text-only answer
                answers_dict[q_num] = answer_normalized

        print(f"[PDF Processor] Extracted {len(answers_dict)} answers")

        # Enrich answers with YOLO-detected bounding boxes for diagrams
        answers_dict = self._enrich_answers_with_yolo_bounding_box(answers_dict, pages)

        return answers_dict

    def extract_diagram_from_pdf(
        self, pdf_path: str, bounding_box: List[int], page_num: int, output_path: str
    ) -> bool:
        """Extract a single diagram from PDF using bounding box coordinates."""
        try:
            # Handle both old format [x, y, width, height] and new format [ymin, xmin, ymax, xmax]
            if isinstance(bounding_box, list) and len(bounding_box) == 4:
                pass
            else:
                raise ValueError("Invalid bounding box format")

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
            cropped = page_img.crop(
                (
                    bounding_box[0],
                    bounding_box[1],
                    bounding_box[2],
                    bounding_box[3],
                )
            )

            # Save as JPEG
            cropped.save(output_path, "JPEG", quality=95)
            return True

        except Exception as e:
            print(f"Error extracting diagram: {e}")
            return False

    def _get_question_numbers(
        self, questions: List[Dict[str, Any]], parent_id: Optional[str] = None
    ) -> List[str]:
        """Recursively flatten questions to handle nested multi-part questions at any depth and return list of question numbers.

        Generates composite IDs that match the PDF extraction format:
        - Top-level questions: keep original ID (e.g., "1", "17", "33")
        - Subquestions: create composite IDs like "17.1", "17.2", "33.1.1" using sequential numbering
        - For multipart questions, do not include the main question ID. Only include leaf subquestion IDs.

        """
        question_numbers = []

        for i, question in enumerate(questions, 1):
            question_type = question.get("type", "")
            question_id = i
            subquestions = question.get("subquestions", [])

            # Build the current question's composite ID
            if parent_id:
                # This is a subquestion
                current_id = f"{parent_id}.{question_id}"
            else:
                # Top-level question - use the question id directly
                current_id = question_id

            # Check if this question has subquestions (multi-part question)
            if question_type == "multi-part" and subquestions:
                # Recursively process subquestions
                # Pass current_id as parent for generating composite IDs
                sub_numbers = self._get_question_numbers(subquestions, current_id)
                question_numbers.extend(sub_numbers)
            else:
                # Leaf question - add to the list
                question_numbers.append(current_id)

        return question_numbers

    def _enrich_answers_with_yolo_bounding_box(
        self, answers: Dict[str, Any], pages: List[Image.Image]
    ) -> Dict[str, Any]:
        """
        Enrich answer dict with YOLO-detected bounding boxes for diagrams.

        For each answer that has a diagram with page_number, run YOLO on that page
        to detect diagram regions and assign bounding boxes.
        """
        import tempfile

        try:
            from ultralytics import YOLO
        except ImportError:
            print(
                "[PDF Processor] WARNING: ultralytics not installed, skipping YOLO enrichment"
            )
            return answers

        # Model path should be configurable
        model_path = os.getenv(
            "DIAGRAM_YOLO_MODEL_PATH", "runs/detect/diagram_detector5/weights/best.pt"
        )
        confidence = float(os.getenv("DIAGRAM_YOLO_CONFIDENCE", "0.25"))

        try:
            yolo_model = YOLO(model_path)
        except Exception as e:
            print(f"[PDF Processor] WARNING: Failed to load YOLO model: {e}")
            return answers

        # Map: page_number -> [(question_id, answer_dict)]
        page_to_answers: Dict[int, List[tuple]] = {}

        for q_id, answer_data in answers.items():
            if isinstance(answer_data, dict) and answer_data.get("diagram"):
                diagram = answer_data["diagram"]
                page_number = diagram.get("page_number")
                if page_number and isinstance(page_number, int):
                    page_to_answers.setdefault(page_number, []).append(
                        (q_id, answer_data)
                    )

        if not page_to_answers:
            print(
                "[PDF Processor] No diagrams with page numbers found, skipping YOLO enrichment"
            )
            return answers

        print(
            f"[PDF Processor] Running YOLO on {len(page_to_answers)} pages with diagrams"
        )

        # For each relevant page, run YOLO and assign bounding boxes
        for page_number, answer_items in page_to_answers.items():
            if not (1 <= page_number <= len(pages)):
                print(
                    f"[PDF Processor] WARNING: Page {page_number} out of range (1-{len(pages)})"
                )
                continue

            page_img = pages[page_number - 1]

            # Save image to temp file for YOLO
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_img:
                page_img.save(tmp_img, "JPEG", quality=95)
                img_path = tmp_img.name

            try:
                results = yolo_model(img_path, conf=confidence, verbose=False)
                detections = []

                if len(results) > 0 and results[0].boxes is not None:
                    boxes = results[0].boxes
                    for box in boxes:
                        coords = box.xyxy[0].cpu().numpy()
                        x1, y1, x2, y2 = map(int, coords)
                        conf_score = float(box.conf[0])
                        cls = int(box.cls[0])
                        detection = {
                            "bbox": (x1, y1, x2, y2),
                            "confidence": conf_score,
                            "class_id": cls,
                            "ymin": y1,
                        }
                        detections.append(detection)

                # Sort detections by confidence (desc), then ymin (asc)
                detections.sort(key=lambda d: (-d["confidence"], d["ymin"]))

                n_answers = len(answer_items)
                n_diagrams = len(detections)

                print(
                    f"[PDF Processor] Page {page_number}: {n_diagrams} diagrams detected for {n_answers} answers"
                )

                # Assignment logic (matching assignment_document_parser.py)
                if n_answers == 1 and n_diagrams > 0:
                    # Assign highest confidence diagram
                    det = detections[0]
                    self._update_answer_with_bounding_box(
                        answer_items[0][1], det, page_number
                    )
                elif n_diagrams >= n_answers:
                    # Assign first n_answers diagrams sorted by ymin
                    top_diagrams = sorted(
                        detections[:n_answers], key=lambda d: d["ymin"]
                    )
                    for (q_id, answer_data), det in zip(answer_items, top_diagrams):
                        self._update_answer_with_bounding_box(
                            answer_data, det, page_number
                        )
                elif n_diagrams < n_answers and n_diagrams > 0:
                    # Assign all detected diagrams sorted by ymin
                    top_diagrams = sorted(detections, key=lambda d: d["ymin"])
                    for (q_id, answer_data), det in zip(answer_items, top_diagrams):
                        self._update_answer_with_bounding_box(
                            answer_data, det, page_number
                        )
                    # Remaining answers without diagrams keep bounding_box as None

            except Exception as e:
                print(f"[PDF Processor] ERROR running YOLO on page {page_number}: {e}")
            finally:
                # Clean up temp image
                try:
                    os.unlink(img_path)
                except Exception:
                    pass

        return answers

    def _update_answer_with_bounding_box(
        self, answer_data: Dict[str, Any], det: Dict[str, Any], page_number: int
    ) -> None:
        """Update answer's diagram with YOLO-detected bounding box."""
        x1, y1, x2, y2 = det["bbox"]

        if not isinstance(answer_data.get("diagram"), dict):
            answer_data["diagram"] = {}

        answer_data["diagram"].update(
            {
                "bounding_box": [x1, y1, x2, y2],
                "page_number": page_number,
                "confidence": det["confidence"],
            }
        )

        print(
            f"[PDF Processor] Diagram bbox assigned: {[x1, y1, x2, y2]} (conf: {det['confidence']:.2f})"
        )

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

    def extract_and_upload_diagrams(
        self,
        submission_id: str,
        pdf_s3_key: str,
        answers: Dict[str, Any],
        s3_client,
        s3_bucket: str,
        s3_upload_func,
        logger=None,
    ) -> Dict[str, Any]:
        """
        Extract diagram images from PDF submission using bounding boxes and upload to S3.

        This is a synchronous/foreground operation that:
        1. Downloads the PDF from S3
        2. For each answer with a diagram bounding_box but no s3_key, extracts the image
        3. Uploads to S3 and updates the answer dict with s3_key, file_id, filename

        Args:
            submission_id: The submission ID
            pdf_s3_key: S3 key of the PDF file
            answers: Dict of question_id -> answer data (may include diagrams)
            s3_client: boto3 S3 client
            s3_bucket: S3 bucket name
            s3_upload_func: Function to upload file to S3 (path, key, content_type)
            logger: Optional logger

        Returns:
            Updated answers dict with diagram s3_keys populated
        """
        if logger:
            logger.info(
                f"Starting PDF diagram extraction for submission {submission_id}"
            )
        else:
            print(
                f"[PDF Processor] Starting diagram extraction for submission {submission_id}"
            )

        if not answers:
            if logger:
                logger.warning(f"Submission {submission_id} has no answers")
            return answers

        # Download PDF from S3 to temp file
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                s3_client.download_fileobj(s3_bucket, pdf_s3_key, tmp)
                tmp_pdf_path = tmp.name
        except Exception as e:
            if logger:
                logger.error(f"Failed to download PDF from S3: {str(e)}")
            else:
                print(
                    f"[PDF Processor] ERROR: Failed to download PDF from S3: {str(e)}"
                )
            return answers

        updated = False

        try:
            for question_id, answer in answers.items():
                # Check if answer has diagram with bounding_box but no s3_key
                if isinstance(answer, dict) and answer.get("diagram"):
                    diagram = answer["diagram"]
                    bounding_box = diagram.get("bounding_box")
                    page_number = diagram.get("page_number", None)

                    if bounding_box and not diagram.get("s3_key"):
                        try:
                            # Extract diagram image from PDF
                            with tempfile.NamedTemporaryFile(
                                delete=False, suffix=".jpg"
                            ) as img_tmp:
                                img_output_path = img_tmp.name

                            success = self.extract_diagram_from_pdf(
                                tmp_pdf_path, bounding_box, page_number, img_output_path
                            )

                            if success and os.path.exists(img_output_path):
                                # Upload to S3
                                file_id = str(uuid.uuid4())
                                s3_key = f"submissions/{submission_id}/diagrams/q{question_id}_{file_id}.jpg"

                                s3_upload_func(
                                    img_output_path, s3_key, content_type="image/jpeg"
                                )

                                # Update answer with s3_key
                                answers[question_id]["diagram"]["s3_key"] = s3_key
                                answers[question_id]["diagram"]["file_id"] = file_id
                                answers[question_id]["diagram"][
                                    "filename"
                                ] = f"diagram_q{question_id}.jpg"
                                updated = True

                                if logger:
                                    logger.info(
                                        f"Extracted and uploaded diagram for Q{question_id} to {s3_key}"
                                    )
                                else:
                                    print(
                                        f"[PDF Processor] Extracted and uploaded diagram for Q{question_id} to {s3_key}"
                                    )

                                # Clean up temp image
                                os.unlink(img_output_path)

                        except Exception as e:
                            if logger:
                                logger.error(
                                    f"Error extracting diagram for Q{question_id}: {str(e)}"
                                )
                            else:
                                print(
                                    f"[PDF Processor] ERROR extracting diagram for Q{question_id}: {str(e)}"
                                )
                            continue

        finally:
            # Clean up temp PDF
            try:
                os.unlink(tmp_pdf_path)
            except Exception:
                pass

        if updated:
            if logger:
                logger.info(
                    f"Completed diagram extraction for submission {submission_id}"
                )
            else:
                print(
                    f"[PDF Processor] Completed diagram extraction for submission {submission_id}"
                )

        print(f"[PDF Processor] Diagram extraction process finished")
        print(f"[PDF Processor] Final answers: {json.dumps(answers, indent=2)}...")

        return answers
