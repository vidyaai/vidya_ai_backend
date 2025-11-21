import base64
import json
import re
import uuid
import tempfile
import os
import traceback
from textwrap import dedent
from typing import Dict, Any, Optional, List
from openai import OpenAI
from google import genai
from controllers.config import logger, s3_client, AWS_S3_BUCKET
from controllers.storage import s3_presign_url, s3_upload_file
import concurrent.futures
import docx
from io import BytesIO
from PIL import Image
from pdf2image import convert_from_bytes
from .prompts import (
    DOCUMENT_PARSER_SYSTEM_PROMPT,
    DOCUMENT_PARSER_SYSTEM_PROMPT_STEP1,
    get_question_extraction_prompt,
)
from .assignment_schemas import get_assignment_parsing_schema
from .document_processor import DocumentProcessor


class AssignmentDocumentParser:
    """AI-powered parser for extracting existing assignment questions from documents"""

    def __init__(self, user_id: Optional[int] = None):
        self.user_id = user_id
        self.GPTclient = OpenAI()
        self.gpt5_model = "gpt-5"
        self.gpt4o_model = "gpt-4o"

    def parse_pdf_images_to_assignment(
        self,
        pdf_content: bytes,
        file_name: str,
        generation_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Parse PDF pages directly as images to extract assignment questions with diagram support.
        Uses efficient 4-step extraction:
        0. Group pages into batches using Gemini (ensuring no incomplete questions at batch boundaries)
        1. Parallel LLM calls to extract all content from each batch (questions, diagrams, equations, answers if present)
        2. YOLO calls to extract diagram bounding boxes for relevant pages
        3. Single LLM call to generate missing answers/rubrics

        Args:
            pdf_content: Raw PDF file content (bytes)
            file_name: Original file name for context

        Returns:
            Dictionary containing assignment data with extracted questions and diagram metadata
        """
        try:
            # Convert PDF pages to images using Poppler
            images = convert_from_bytes(pdf_content, dpi=200)
            logger.info(
                f"Converted PDF to {len(images)} images for question extraction"
            )

            # STEP 0: Unified filtering + batching using GPT-4o
            logger.info(
                "Step 0: Filtering pages, detecting language, extracting title/description, and grouping into optimized batches using GPT-4o..."
            )
            (
                page_batches,
                detected_title,
                detected_description,
            ) = self._filter_and_group_pages_gpt4o(images, generation_options)
            logger.info(
                f"Step 0: Created {len(page_batches)} batches for parallel processing (pages with questions)"
            )

            # STEP 1: Parallel LLM calls to extract ALL content from each batch
            logger.info(
                "Step 1: Extracting all content in parallel from all batches..."
            )
            extracted_data = self._extract_all_content_parallel(page_batches, file_name)

            # Validate and normalize the response
            result = self._normalize_assignment_data(extracted_data, file_name)

            # Override title/description from STEP 0 if GPT returned them (STEP 0 extracts title/description)
            try:
                if detected_title:
                    result["title"] = detected_title
                if detected_description:
                    result["description"] = detected_description
            except Exception:
                # Be robust if result isn't a dict for any reason
                logger.debug(
                    "Step 0: Could not apply detected title/description to result"
                )

            # STEP 2: YOLO calls to extract diagram bounding boxes for relevant pages
            logger.info("Step 2: Extracting diagram bounding boxes with YOLO...")
            try:
                result["questions"] = self._assign_diagrams_with_yolo(
                    result.get("questions", []), images
                )
            except Exception as e:
                logger.warning(f"Skipping YOLO bbox enrichment due to error: {e}")

            # STEP 3: Single LLM call to generate missing answers/rubrics
            logger.info("Step 3: Generating missing answers and rubrics...")
            result = self._generate_missing_answers_and_rubrics(result, images)

            # Debug: Log first question after Step 3
            if result.get("questions"):
                first_q = result["questions"][0]
                logger.info(
                    f"DEBUG - After Step 3, first question: ID={first_q.get('id')}, "
                    f"correctAnswer='{first_q.get('correctAnswer', 'MISSING')}', "
                    f"rubric='{first_q.get('rubric', 'MISSING')[:50] if first_q.get('rubric') else 'MISSING'}...'"
                )

            result = self._normalize_assignment_data(result, file_name)

            # Debug: Log first question after final normalization
            if result.get("questions"):
                first_q = result["questions"][0]
                logger.info(
                    f"DEBUG - After final normalization, first question: ID={first_q.get('id')}, "
                    f"correctAnswer='{first_q.get('correctAnswer', 'MISSING')}', "
                    f"rubric='{first_q.get('rubric', 'MISSING')[:50] if first_q.get('rubric') else 'MISSING'}...'"
                )

            logger.info(
                f"Successfully extracted {len(result.get('questions', []))} questions from PDF images"
            )

            return result

        except Exception as e:
            logger.error(f"Error parsing PDF images: {str(e)}")
            raise

    def _filter_and_group_pages_gpt4o(
        self,
        images: List[Image.Image],
        generation_options: Optional[Dict[str, Any]] = None,
    ) -> tuple[list[list[tuple[Image.Image, int]]], str, str]:
        """
        Unified STEP 0: Use GPT-4o to detect languages, filter pages that contain questions
        (preferring English when present per rules), extract title and description, and
        return dynamically optimized batches that avoid splitting questions across batches.

        Returns: (page_batches, title, description)
        where page_batches is a list of batches, each batch is a list of (image, original_page_number)
        """
        logger.info(
            f"Step 0: Running unified language detection, page filtering and batching for {len(images)} pages"
        )

        try:
            # Convert images to base64 parts
            image_parts = []
            for idx, image in enumerate(images):
                buffered = BytesIO()
                image.save(buffered, format="PNG")
                img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
                image_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_base64}"},
                    }
                )

            # Build prompt instructing GPT-4o to do detection, filtering and batching
            prompt = dedent(
                f"""
            Analyze all {len(images)} pages of this assignment document.

            1) Detect what languages are present on the pages. Return a list of languages and a single
               `selected_language` according to these rules:
               - If the document contains English anywhere, `selected_language` should be "English".
               - If the document is entirely another single language, selected_language should be that language.
               - If multiple non-English languages exist and no English, pick any one language to focus on (you may choose the majority language).

            2) For the `selected_language`, determine for EACH page (1..{len(images)}) whether that page contains
               assignment questions in that language. Look for question numbering, question prompts, options, problem statements, etc.

            3) Group the pages that contain questions into OPTIMIZED batches for parallel LLM extraction. Requirements:
               - Batches should be sized dynamically to balance parallelism and token limits; do not use a fixed page size.
               - Ensure NO question is split across a batch boundary (i.e., if a question continues across pages, put all its pages in the same batch).
               - Try to minimize number of batches while keeping batch sizes reasonable (avoid extremely large batches).

            4) Also extract assignment `title` and `description` (if present) from the document in the selected language.

            Return JSON with the following structure:
            {{
                "languages": ["lang1", "lang2", ...],
                "selected_language": "English",
                "pages": [{{"page_number": 1, "has_questions": true/false, "confidence":"high|medium|low", "reason":"..."}}, ...],
                "batches": [[1,2,3], [4,5], ...],
                "title": "..." ,
                "description": "..."
            }}

            IMPORTANT: `batches` must cover ONLY pages that have `has_questions=true` and use ORIGINAL page numbers.
            """
            )

            user_content = [{"type": "text", "text": prompt}]
            user_content.extend(image_parts)

            # JSON Schema for STEP 0 response to ensure strict structure
            response_schema = {
                "type": "object",
                "properties": {
                    "languages": {"type": "array", "items": {"type": "string"}},
                    "selected_language": {"type": "string"},
                    "pages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "page_number": {"type": "integer"},
                                "has_questions": {"type": "boolean"},
                                "confidence": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                },
                                "reason": {"type": "string"},
                            },
                            "required": ["page_number", "has_questions"],
                        },
                    },
                    "batches": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "integer"}},
                    },
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["languages", "selected_language", "pages", "batches"],
            }

            response = self.GPTclient.chat.completions.create(
                model=self.gpt4o_model,
                messages=[{"role": "user", "content": user_content}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "step0_batching_response",
                        "schema": response_schema,
                    },
                },
            )

            result = json.loads(response.choices[0].message.content)

            # Parse results
            pages_info = {p.get("page_number"): p for p in result.get("pages", [])}
            batches_numbers = result.get("batches", [])
            title = result.get("title") or ""
            description = result.get("description") or ""

            # Validate batches and convert to image tuples
            if not batches_numbers:
                logger.warning(
                    "Step 0: GPT-4o returned no batches; falling back to single batch of all pages that have questions"
                )
                # Fallback: include pages flagged as has_questions, else all pages
                question_pages = [
                    pn for pn, info in pages_info.items() if info.get("has_questions")
                ]
                if not question_pages:
                    question_pages = list(range(1, len(images) + 1))
                batches_numbers = [question_pages]

            page_batches: list[list[tuple[Image.Image, int]]] = []
            for batch_nums in batches_numbers:
                batch = []
                for pn in batch_nums:
                    if 1 <= pn <= len(images):
                        batch.append((images[pn - 1], pn))
                if batch:
                    page_batches.append(batch)

            if not page_batches:
                # Final fallback: single batch with all pages
                page_batches = [[(img, idx + 1) for idx, img in enumerate(images)]]

            return page_batches, title, description

        except Exception as e:
            logger.warning(
                f"Step 0: Error in unified GPT-4o batching: {e}. Falling back to single batch."
            )
            return [[(img, idx + 1) for idx, img in enumerate(images)]], "", ""

    def _extract_all_content_parallel(
        self, page_batches: List[List[tuple[Image.Image, int]]], file_name: str
    ) -> Dict[str, Any]:
        """
        Step 1: Extract content from all batches in parallel, then consolidate.

        Args:
            page_batches: List of page batches, each batch contains tuples (image, original_page_number)
            file_name: Original file name

        Returns:
            Consolidated extracted data from all batches
        """
        # Process batches in parallel
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(page_batches)
        ) as executor:
            future_to_batch = {
                executor.submit(
                    self._extract_all_content, batch, file_name, batch_idx
                ): batch_idx
                for batch_idx, batch in enumerate(page_batches)
            }

            batch_results = []
            for future in concurrent.futures.as_completed(future_to_batch):
                batch_idx = future_to_batch[future]
                try:
                    result = future.result()
                    batch_results.append((batch_idx, result))
                    logger.info(
                        f"Step 1: Completed batch {batch_idx + 1}/{len(page_batches)}"
                    )
                except Exception as e:
                    logger.error(f"Step 1: Error processing batch {batch_idx}: {e}")
                    raise

        # Sort results by batch index to maintain order
        batch_results.sort(key=lambda x: x[0])

        # Consolidate results
        logger.info(f"Step 1: Consolidating {len(batch_results)} batch results...")

        try:
            consolidated = self._consolidate_batch_results(
                [result for _, result in batch_results], file_name
            )
        except Exception as e:
            logger.error(f"Step 1: Error during consolidation: {e}")
            logger.error(
                f"Step 1: Batch results types: {[type(r) for _, r in batch_results]}"
            )
            raise

        logger.info(
            f"Step 1: Consolidated {len(consolidated.get('questions', []))} questions from all batches"
        )

        # Log consolidated data safely (avoid huge JSON dumps)
        logger.info(
            f"Step 1: Consolidated {len(consolidated.get('questions', []))} total questions"
        )
        return consolidated

    def _consolidate_batch_results(
        self, batch_results: List[Dict[str, Any]], file_name: str
    ) -> Dict[str, Any]:
        """
        Consolidate extraction results from multiple batches.

        Args:
            batch_results: List of extraction results from each batch
            file_name: Original file name

        Returns:
            Single consolidated result dictionary
        """
        if not batch_results:
            return {"title": file_name, "description": "", "questions": []}

        if len(batch_results) == 1:
            return batch_results[0]

        # Use first batch's title and description as base
        consolidated = {
            "title": batch_results[0].get("title", file_name),
            "description": batch_results[0].get("description", ""),
            "questions": [],
        }

        # Consolidate questions from all batches
        question_id_offset = 0
        for idx, batch_result in enumerate(batch_results):
            # Validate batch_result is a dict
            if not isinstance(batch_result, dict):
                logger.error(
                    f"Consolidation: Batch {idx} result is not a dict, it's {type(batch_result)}. "
                    f"Value: {str(batch_result)[:200]}"
                )
                continue

            batch_questions = batch_result.get("questions", [])

            # Renumber question IDs to avoid conflicts
            for question in batch_questions:
                self._renumber_question_ids(question, question_id_offset)
                consolidated["questions"].append(question)

            # Update offset for next batch (find max ID in this batch)
            if batch_questions:
                max_id = self._find_max_question_id(batch_questions)
                question_id_offset = max_id

        logger.info(
            f"Consolidation: Combined {len(batch_results)} batches into {len(consolidated['questions'])} questions"
        )
        return consolidated

    def _renumber_question_ids(self, question: Dict[str, Any], offset: int) -> None:
        """
        Recursively renumber question IDs by adding an offset.
        Modifies question in place.
        """
        if "id" in question:
            question["id"] = question["id"] + offset

        # Update equation IDs to match new question ID
        # if question.get("equations"):
        #     old_id = question["id"] - offset
        #     new_id = question["id"]
        #     for eq in question["equations"]:
        #         eq_id = eq.get("id", "")
        #         # Replace old question ID in equation ID
        #         if eq_id.startswith(f"q{old_id}_"):
        #             eq["id"] = eq_id.replace(f"q{old_id}_", f"q{new_id}_", 1)

        # Recursively renumber subquestions
        if question.get("subquestions"):
            for subq in question["subquestions"]:
                self._renumber_question_ids(subq, offset)

    def _find_max_question_id(self, questions: List[Dict[str, Any]]) -> int:
        """
        Recursively find the maximum question ID in a list of questions.
        """
        max_id = 0
        for q in questions:
            q_id = q.get("id", 0)
            max_id = max(max_id, q_id)

            # Check subquestions
            if q.get("subquestions"):
                subq_max = self._find_max_question_id(q["subquestions"])
                max_id = max(max_id, subq_max)

        return max_id

    def _extract_all_content(
        self,
        page_batch: List[tuple[Image.Image, int]],
        file_name: str,
        batch_idx: int = 0,
    ) -> Dict[str, Any]:
        """
        Step 1: Single LLM call to extract ALL content from a batch of pages.
        Extracts: title, description, questions, types, points, options, diagrams, equations,
        correct answers (if present), rubrics (if present).

        Args:
            page_batch: List of tuples (image, original_page_number) for this batch
            file_name: Original file name
            batch_idx: Index of this batch (for logging)

        Returns:
            Extracted data for this batch
        """
        logger.info(f"Step 1 (Batch {batch_idx}): Processing {len(page_batch)} pages")

        # Extract images and page numbers from tuples
        images = [img for img, _ in page_batch]
        page_numbers = [page_num for _, page_num in page_batch]

        logger.info(
            f"Step 1 (Batch {batch_idx}): Page numbers in batch: {page_numbers}"
        )

        # Convert images to base64
        image_contents = []
        for idx, image in enumerate(images):
            buffered = BytesIO()
            image.save(buffered, format="PNG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            image_contents.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_base64}"},
                }
            )

        # Build page number mapping for the prompt
        page_mapping_text = "\n".join(
            [
                f"- Image {idx + 1} corresponds to original page {page_num}"
                for idx, page_num in enumerate(page_numbers)
            ]
        )

        # Create comprehensive extraction prompt
        prompt = f"""
            Extract ALL content from this {len(images)}-page STEM assignment batch: {file_name}

            PAGE MAPPING:
            {page_mapping_text}
            (Use ORIGINAL page numbers for diagrams)

            ═══════════════════════════════════════════════════════════
            CRITICAL: EXTRACTION RULES
            ═══════════════════════════════════════════════════════════
            1. EXTRACT ONLY - Never generate or create questions not in the document
            2. EQUATION PLACEHOLDERS - Replace ALL math/formulas with <eq equation_id>
            3. DO NOT leave raw LaTeX (\\(...\\), \\[...\\], $...$) or math symbols in text fields

            ✓ CORRECT: "Solve <eq q1_eq1> for x."
            ✗ WRONG: "Solve \\(2x + 5 = 13\\) for x."

            EXTRACT FOR EACH QUESTION:
            1. Question text (with <eq equation_id> placeholders)
            2. Type (multiple-choice, short-answer, long-answer, multi-part, etc.)
            3. Points/marks
            4. Options (if MCQ) (with equation placeholders)
            5. Diagrams: page_number, caption (NO bounding_box)
            6. Equations (from ALL contexts: question, options, correctAnswer, rubric):
            - id: q{{qid}}_eq{{n}}, q{{qid}}_opt{{A}}_eq{{n}}, q{{qid}}_ans_eq{{n}}, q{{qid}}_rub_eq{{n}}
            - latex: LaTeX representation
            - position: {{char_index: position AFTER placeholder, context: 'question_text'|'options'|'correctAnswer'|'rubric'}}
            - type: 'inline'|'display'
            7. Correct answers (with placeholders; if in document, else "")
            - Extract complete derivations/solutions with all steps
            - For MCQ: 0-based index (e.g., 0 for A) OR list [0,2] if multiple correct (set allowMultipleCorrect=true, multipleCorrectAnswers=[...])
            8. Rubrics (with placeholders; if in document, else "")
            9. Subquestions (if multi-part) with nested sub-subquestions

            MULTI-PART QUESTION RULES:
            - optionalParts=TRUE ONLY for explicit OR alternatives ("answer any X of Y", "either...or")
            - optionalParts=FALSE if ALL parts (a,b,c) must be answered
            - requiredPartsCount: number of parts student must answer
            - ID scheme: parent 30 → subquestions 301,302,303; nested 3001,3002 → 300101,300102
            - Avoid deep nesting; keep hierarchy flat

            EXAMPLES:

            Equation Placeholder:
            Q: "Solve <eq q1_eq1> for x."
            Ans: "Solution is <eq q1_ans_eq1>"
            Rub: "Full marks for <eq q1_rub_eq1>"
            Equations: [
            {{"id":"q1_eq1","latex":"2x+5=13","position":{{"char_index":6,"context":"question_text"}},"type":"inline"}},
            {{"id":"q1_ans_eq1","latex":"x=4","position":{{"char_index":16,"context":"correctAnswer"}},"type":"inline"}},
            {{"id":"q1_rub_eq1","latex":"x=4","position":{{"char_index":21,"context":"rubric"}},"type":"inline"}}
            ]

            Multi-part (optional OR at nested level):
            Q30: "Two slits 2μm wide, 6μm apart. λ=450nm.
            (i) Peaks: (A)2 (B)3 (C)4 (D)6
            (ii) If width doubled, peaks: (A)1 (B)2 (C)3 (D)4
            (iii) EITHER (a) OR (b):
            (a) If λ=680nm, peaks: (A)2 (B)4 (C)6 (D)9
            (b) First min at <eq q30_3032_eq1>: (A)<eq q30_3032_optA_eq1> (B)<eq q30_3032_optB_eq1>"

            JSON: {{"id":30,"type":"multi-part","optionalParts":false,"requiredPartsCount":0,"subquestions":[
            {{"id":301,"type":"multiple-choice","question":"Peaks:","options":["2","3","4","6"]}},
            {{"id":302,"type":"multiple-choice","question":"If width doubled:","options":["1","2","3","4"]}},
            {{"id":303,"type":"multi-part","optionalParts":true,"requiredPartsCount":1,"subquestions":[
                {{"id":3031,"type":"multiple-choice","question":"If λ=680nm:","options":["2","4","6","9"]}},
                {{"id":3032,"type":"multiple-choice","question":"First min at <eq q30_3032_eq1>:","options":["<eq q30_3032_optA_eq1>","<eq q30_3032_optB_eq1>"],"equations":[...]}}
            ]}}
            ]}}

            Multi-part (optional OR at root):
            Q31: "ATTEMPT ANY TWO:
            (a) Derive capacitance expression
            (b) Find potential (charge=6μC, r=0.2m)
            (c) Gauss theorem for conducting shell
            (d) Show E-field 2x for conducting vs nonconducting"

            JSON: {{"id":31,"type":"multi-part","optionalParts":true,"requiredPartsCount":2,"subquestions":[
            {{"id":311,"type":"long-answer","question":"Derive capacitance...","points":5}},
            {{"id":312,"type":"long-answer","question":"Find potential...","points":5}},
            {{"id":313,"type":"long-answer","question":"Gauss theorem...","points":5}},
            {{"id":314,"type":"long-answer","question":"Show E-field...","points":5}}
            ]}}

            Multi-part (ALL required):
            Q24: "Voltage applied to 'X', current leads by π/2.
            (a) Identify X
            (b) Reactance formula
            (c) Graph: reactance vs frequency
            (d) Behavior in AC & DC"

            JSON: {{"id":24,"type":"multi-part","optionalParts":false,"requiredPartsCount":4,"subquestions":[
            {{"id":241,"type":"short-answer","question":"Identify X"}},
            {{"id":242,"type":"short-answer","question":"Reactance formula"}},
            {{"id":243,"type":"short-answer","question":"Graph reactance vs freq"}},
            {{"id":244,"type":"short-answer","question":"Behavior AC & DC"}}
            ]}}

            Return structured JSON matching schema.
        """

        # Get comprehensive schema (includes equations, allows empty answers/rubrics)
        response_schema = get_assignment_parsing_schema("step1_pdf_parsing_no_bbox")

        # Build message
        user_content = [{"type": "text", "text": dedent(prompt).strip()}]
        user_content.extend(image_contents)

        # Call LLM
        response = self.GPTclient.chat.completions.create(
            model=self.gpt5_model,
            messages=[
                {
                    "role": "system",
                    "content": dedent(DOCUMENT_PARSER_SYSTEM_PROMPT_STEP1),
                },
                {"role": "user", "content": user_content},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "step1_pdf_parsing_no_bbox",
                    "schema": response_schema,
                },
            },
            # max_completion_tokens=16384,
            # temperature=0.2,
        )

        extracted_data = json.loads(response.choices[0].message.content)

        # Validate extracted_data is a dict
        if not isinstance(extracted_data, dict):
            logger.error(
                f"Step 1 (Batch {batch_idx}): Extracted data is not a dict, it's {type(extracted_data)}. "
                f"Content: {response.choices[0].message.content[:500]}"
            )
            raise ValueError(f"LLM returned invalid data type: {type(extracted_data)}")

        logger.info(
            f"Step 1 (Batch {batch_idx}): Extracted {len(extracted_data.get('questions', []))} questions"
        )

        logger.info(
            f"Step 1 (Batch {batch_idx}): Extracted data: {json.dumps(extracted_data)}"
        )

        logger.info(
            f"Step 1 (Batch {batch_idx}): Extracted all content including equations"
        )
        return extracted_data

    def _assign_diagrams_with_yolo(
        self, questions: List[Dict[str, Any]], images: List[Image.Image]
    ) -> List[Dict[str, Any]]:
        """
        Assign diagrams to questions using YOLO for only relevant pages.
        """
        from ultralytics import YOLO
        import tempfile
        import shutil

        # Model path should be configurable
        model_path = os.getenv(
            "DIAGRAM_YOLO_MODEL_PATH", "runs/detect/diagram_detector5/weights/best.pt"
        )
        confidence = float(os.getenv("DIAGRAM_YOLO_CONFIDENCE", "0.25"))
        yolo_model = YOLO(model_path)

        # Map: page_number -> [questions needing diagram]
        page_to_questions = {}
        for q in questions:
            diagram = q.get("diagram")
            if q.get("hasDiagram") and isinstance(diagram, dict):
                page_number = diagram.get("page_number")
                if page_number:
                    page_to_questions.setdefault(page_number, []).append(q)

        # For each relevant page, run YOLO and assign diagrams
        for page_number, qs in page_to_questions.items():
            if not (1 <= page_number <= len(images)):
                continue
            page_img = images[page_number - 1]
            # Save image to temp file for YOLO
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_img:
                page_img.save(tmp_img, "JPEG", quality=95)
                img_path = tmp_img.name

            results = yolo_model(img_path, conf=confidence, verbose=False)
            detections = []
            if len(results) > 0 and results[0].boxes is not None:
                boxes = results[0].boxes
                for i, box in enumerate(boxes):
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

            n_questions = len(qs)
            n_diagrams = len(detections)
            # Assignment logic
            if n_questions == 1 and n_diagrams > 0:
                # Assign highest confidence diagram
                det = detections[0]
                self._update_question_with_diagram(qs[0], page_img, det, page_number)
            elif n_diagrams >= n_questions:
                # Assign first n_questions diagrams sorted by ymin
                top_diagrams = sorted(detections[:n_questions], key=lambda d: d["ymin"])
                for q, det in zip(qs, top_diagrams):
                    self._update_question_with_diagram(q, page_img, det, page_number)
                # Leave unmatched diagrams empty
            elif n_diagrams < n_questions:
                # Assign all detected diagrams sorted by ymin
                top_diagrams = sorted(detections, key=lambda d: d["ymin"])
                for q, det in zip(qs, top_diagrams):
                    self._update_question_with_diagram(q, page_img, det, page_number)
                # Leave unmatched questions empty

            # Clean up temp image
            try:
                os.unlink(img_path)
            except Exception:
                pass

        return questions

    def _update_question_with_diagram(self, q, page_img, det, page_number):
        # Crop diagram region and upload to S3
        x1, y1, x2, y2 = det["bbox"]
        cropped = page_img.crop((x1, y1, x2, y2))
        import tempfile
        import uuid

        diagram_id = str(uuid.uuid4())
        base_s3_path = f"users/{self.user_id}/temp_diagrams"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            cropped.save(tmp, "JPEG", quality=95)
            tmp_path = tmp.name
        s3_key = f"{base_s3_path}/q{q.get('id')}_{diagram_id}.jpg"
        if s3_client and AWS_S3_BUCKET:
            s3_upload_file(tmp_path, s3_key, content_type="image/jpeg")
            s3_url = None
        else:
            s3_url = None
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        # Update question diagram info
        if not isinstance(q.get("diagram"), dict):
            q["diagram"] = {}
        q["diagram"].update(
            {
                "page_number": page_number,
                "bounding_box": [x1, y1, x2, y2],
                "s3_key": s3_key,
                "s3_url": s3_url,
                "confidence": det["confidence"],
            }
        )
        logger.info(f"Q{q.get('id')}: YOLO bbox assigned: {[x1, y1, x2, y2]}")

    def _generate_missing_answers_and_rubrics(
        self, data: Dict[str, Any], images: List[Image.Image]
    ) -> Dict[str, Any]:
        """
        Step 3: Generate missing answers and rubrics in four steps:
        1. Use GPT-4o to group questions into dynamic batches.
        2. Create prepared prompts (with image contents) for each batch.
        3. Process prepared batches in parallel using GPT-5.
        4. Consolidate results into a single output.
        """
        questions = data.get("questions", [])
        logger.info(f"Step 3: Starting with {len(questions)} total questions")

        # Step 1: Collect questions that need generation and group into dynamic batches using GPT-4o
        logger.info(
            "Step 3.1: Collecting incomplete questions and grouping into dynamic batches using GPT-4o..."
        )
        # Flatten questions and create a list of items expected by _generate_batch_answers
        def _collect_questions_to_generate(
            q_list: List[Dict[str, Any]]
        ) -> List[Dict[str, Any]]:
            out: List[Dict[str, Any]] = []
            for q in q_list:
                q_id = q.get("id")
                path = str(q_id) if q_id is not None else None
                needs_answer = not bool(q.get("correctAnswer"))
                needs_rubric = not bool(q.get("rubric"))
                if path and (needs_answer or needs_rubric):
                    out.append(
                        {
                            "path": path,
                            "question": q,
                            "needs_answer": needs_answer,
                            "needs_rubric": needs_rubric,
                        }
                    )
                # Recurse into subquestions
                for sub in q.get("subquestions", []):
                    out.extend(_collect_questions_to_generate([sub]))
            return out

        questions_needing_generation = _collect_questions_to_generate(questions)
        logger.info(
            f"Step 3.1: Found {len(questions_needing_generation)} questions needing generation"
        )

        try:
            if not questions_needing_generation:
                logger.info("Step 3: No questions need generation; skipping Step 3")
                return data

            question_batches = self._group_questions_into_batches_gpt4o(
                questions_needing_generation
            )
            logger.info(
                f"Step 3.1: Grouped questions into {len(question_batches)} batches"
            )
        except Exception as e:
            logger.error(f"Error during GPT-4o batching: {str(e)}")
            raise

        # Step 2: Prepare prompts (with images) for each batch, then process batches in parallel using GPT-5
        logger.info(
            "Step 3.2: Preparing prompts for GPT-5 generation and processing batches in parallel..."
        )
        batch_results = []
        try:
            # Prepare prompts + image contents for each batch (may presign S3 or inline small images)
            prepared_prompts = self._create_batch_prompts_with_images(
                question_batches, images
            )

            max_workers = (
                min(len(prepared_prompts), int(os.getenv("MAX_PARALLEL_BATCHES", "6")))
                or 1
            )
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers
            ) as executor:
                futures = [
                    executor.submit(self._generate_batch_answers, prepared)
                    for prepared in prepared_prompts
                ]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        res = future.result()
                        batch_results.append(res)
                    except Exception as e:
                        logger.error(f"Error in batch future: {e}")
            logger.info(f"Step 3.2: Processed {len(batch_results)} batches")
        except Exception as e:
            logger.error(f"Error during GPT-5 batch processing: {str(e)}")
            raise

        # Step 3: Consolidate results
        logger.info("Step 3.3: Consolidating batch results...")
        try:
            # Merge batch mappings into a single mapping path -> generated data
            all_generated: Dict[str, Dict[str, Any]] = {}
            for br in batch_results:
                if isinstance(br, dict):
                    all_generated.update(br)

            logger.info(
                f"Step 3.3: Merging generated answers for {len(all_generated)} paths"
            )

            # Update original questions in-place using the mapping
            def _apply_generation_to_question(q: Dict[str, Any]):
                path = str(q.get("id")) if q.get("id") is not None else None
                if path and path in all_generated:
                    gen = all_generated[path]
                    # Accept multiple possible key names from LLM
                    ca = gen.get("correct_answer") or gen.get("correctAnswer")
                    rub = gen.get("rubric") or gen.get("rubrics")
                    if ca:
                        q["correctAnswer"] = ca
                    if rub:
                        q["rubric"] = rub
                    # Merge equations if present
                    gen_eqs = gen.get("equations") or []
                    if gen_eqs:
                        eqs = q.get("equations") or []
                        # Append new equations, avoid duplicates by id
                        existing_ids = {e.get("id") for e in eqs}
                        for ge in gen_eqs:
                            if ge.get("id") not in existing_ids:
                                eqs.append(ge)
                        q["equations"] = eqs

                for sub in q.get("subquestions", []) or []:
                    _apply_generation_to_question(sub)

            for q in questions:
                _apply_generation_to_question(q)

            logger.info(
                "Step 3: Successfully applied generated answers and rubrics to questions"
            )
            return data
        except Exception as e:
            logger.error(f"Error during result application/consolidation: {str(e)}")
            raise

    def _group_questions_into_batches_gpt4o(
        self, questions: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """
        Use GPT-4o to group questions into dynamic batches based on complexity and token limits.

        Args:
            questions: List of questions needing generation.

        Returns:
            List of question batches.
        """
        logger.info(f"Grouping {len(questions)} questions into batches using GPT-4o...")

        # Build the prompt for GPT-4o
        prompt = dedent(
            f"""
            Group the following {len(questions)} questions into dynamic batches such that each batch
            can be comfortably processed by GPT-5 without exceeding token limits. Return the batches
            as a JSON array of arrays, where each inner array contains question indices.

            QUESTIONS:
            {json.dumps(questions, indent=2)}

            RULES:
            - Minimize the number of batches while ensuring token safety.
            - Group questions of similar complexity together when possible.
            - Each batch should not exceed approximately 1500 tokens.

            Return JSON in the format: [[0, 1, 2], [3, 4], ...]
            """
        )

        # Call GPT-4o
        try:
            # Use an object-shaped JSON schema: top-level must be an object per API requirements.
            response = self.GPTclient.chat.completions.create(
                model=self.gpt4o_model,
                messages=[
                    {"role": "system", "content": DOCUMENT_PARSER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "batch_indices",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "batches": {
                                    "type": "array",
                                    "items": {
                                        "type": "array",
                                        "items": {"type": "integer"},
                                    },
                                }
                            },
                            "required": ["batches"],
                        },
                    },
                },
            )

            # Validate response content
            response_content = response.choices[0].message.content
            if not response_content or response_content.strip() == "":
                logger.error("GPT-4o returned an empty response")
                raise ValueError("Empty response from GPT-4o")

            parsed = json.loads(response_content)

            # Support both the new object format and a legacy array format
            if isinstance(parsed, dict):
                batch_indices = parsed.get("batches") or parsed.get("batch_indices")
            elif isinstance(parsed, list):
                batch_indices = parsed
            else:
                raise ValueError("Unexpected GPT-4o response shape for batching")

            if not isinstance(batch_indices, list):
                raise ValueError("Parsed 'batches' is not a list")

            # Validate and sanitize batch indices
            sanitized_batches: List[List[int]] = []
            for batch in batch_indices:
                if not isinstance(batch, list):
                    logger.warning(f"Skipping non-list batch entry: {batch}")
                    continue
                int_indices = []
                for idx in batch:
                    try:
                        i = int(idx)
                    except Exception:
                        logger.warning(f"Ignoring non-integer batch index: {idx}")
                        continue
                    if i < 0 or i >= len(questions):
                        logger.warning(f"Ignoring out-of-range batch index: {i}")
                        continue
                    int_indices.append(i)
                if int_indices:
                    sanitized_batches.append(int_indices)

            if not sanitized_batches:
                raise ValueError("No valid batches returned by GPT-4o")

            question_batches = [
                [questions[i] for i in batch] for batch in sanitized_batches
            ]
            logger.info(f"GPT-4o created {len(question_batches)} batches")
            return question_batches

        except json.JSONDecodeError as e:
            logger.error(f"Error parsing GPT-4o response: {str(e)}")
            logger.debug(f"Raw GPT-4o response: {response.choices[0].message.content}")
            raise

        except Exception as e:
            logger.error(f"Unexpected error during GPT-4o batching: {str(e)}")
            logger.debug(
                f"Raw GPT-4o response: {response.choices[0].message.content if 'response' in locals() else 'No response'}"
            )

            # Fallback: Create default batches
            fallback_batch_size = max(1, len(questions) // 5)  # Default to 5 batches
            question_batches = [
                questions[i : i + fallback_batch_size]
                for i in range(0, len(questions), fallback_batch_size)
            ]
            logger.warning(
                f"Using fallback batching: {len(question_batches)} batches created"
            )
            return question_batches

    def _create_batch_prompts_with_images(
        self, question_batches: List[List[Dict[str, Any]]], images: List[Image.Image]
    ) -> List[Dict[str, Any]]:
        """
        Prepare per-batch prompt text and image contents for GPT-5 calls.

        Returns a list of prepared payloads with keys:
        - batch_index: int
        - batch_questions: List[Dict]
        - prompt_text: str
        - image_contents: List[Dict] (image_url entries, either presigned URLs or data URLs)
        - diagram_s3_keys: List[str]
        - metadata: dict (char_length, image_count, missing_images flag)
        """
        prepared: List[Dict[str, Any]] = []

        for batch_idx, batch in enumerate(question_batches):
            prompt_parts = [
                f"Generate correct answers and/or grading rubrics for {len(batch)} STEM questions.",
                "",
                "ANSWER GENERATION RULES:",
                "Mathematical/Scientific/Engineering: FULL STEP-BY-STEP DERIVATIONS with ALL intermediate steps",
                "- Algebra: Show every equation manipulation",
                "- Calculus: Show differentiation/integration with all rules (chain, product, u-sub, etc.)",
                "- Physics/Chemistry/Engineering: List givens → formulas → substitutions → calculations → final answer with units",
                "- Numerical: Complete calculation process",
                "- Conceptual: Thorough explanations with key definitions/concepts",
                "",
                "MCQ ANSWERS:",
                "- Provide 0-based index only (e.g., '0' for option A, '1' for B)",
                "- DO NOT include option text or explanations",
                "- Multiple correct: comma-separated (e.g., '0,2' for A and C)",
                "",
                "EQUATION PLACEHOLDERS:",
                "- Format: <eq equation_id> where math appears",
                "- Naming: q{path}_ans_eq{n} (answers), q{path}_rub_eq{n} (rubrics)",
                "- REQUIRED: Include ALL equation objects in 'equations' array",
                '- Each equation: {"id":"...", "latex":"...", "type":"inline|display", "position":{"context":"correctAnswer|rubric", "char_index":...}}',
                "",
                "JSON RESPONSE:",
                '{"responses":[{"question_path":"1","correct_answer":"...<eq q1_ans_eq1>...","rubric":"...<eq q1_rub_eq1>...","equations":[...]}]}',
                "",
                "QUESTIONS:",
            ]

            diagram_s3_keys: List[str] = []
            for item in batch:
                q = item["question"]
                prompt_parts.append(f"Question Path: {item['path']}")
                prompt_parts.append(f"Type: {q.get('type', 'unknown')}")
                prompt_parts.append(f"Points: {q.get('points', 0)}")
                prompt_parts.append(f"Question: {q.get('question', '')}")

                if q.get("options"):
                    try:
                        prompt_parts.append(f"Options: {', '.join(q['options'])}")
                    except Exception:
                        prompt_parts.append("Options: ")

                if q.get("equations"):
                    eq_list = []
                    for eq in q["equations"]:
                        try:
                            eq_list.append(
                                f"  - {eq.get('latex','')} (type: {eq.get('type','')}, context: {eq.get('position',{}).get('context','')})"
                            )
                        except Exception:
                            continue
                    if eq_list:
                        prompt_parts.append("Equations:")
                        prompt_parts.extend(eq_list)

                if q.get("hasDiagram") and q.get("diagram"):
                    s3_key = q["diagram"].get("s3_key", "")
                    logger.info(
                        f"Step 3: Preparing diagram for Q{item['path']} with S3 key {s3_key}"
                    )
                    diagram_s3_keys.append(s3_key)
                    prompt_parts.append(
                        f"Diagram: {q['diagram'].get('caption', 'See diagram')}"
                    )

                prompt_parts.append(
                    f"Needs: {'answer' if item['needs_answer'] else ''}{' and ' if item['needs_answer'] and item['needs_rubric'] else ''}{'rubric' if item['needs_rubric'] else ''}"
                )
                prompt_parts.append("")

            prompt_text = "\n".join(prompt_parts)

            # Convert diagram s3 keys to image contents (presign). On failure, attempt to inline crop from original images.
            image_contents: List[Dict[str, Any]] = []
            missing_images = False
            for s3_key in diagram_s3_keys:
                if not s3_key:
                    continue
                try:
                    logger.info(f"Step 3: Presigning S3 URL for {s3_key}")
                    s3_url = s3_presign_url(s3_key)
                    image_contents.append(
                        {"type": "image_url", "image_url": {"url": s3_url}}
                    )
                except Exception as e:
                    logger.warning(
                        f"Step 3: Failed to presign S3 URL for {s3_key}: {e}"
                    )
                    # Try to find matching question and inline the image from page crop if available
                    inlined = False
                    for batch_item in batch:
                        dq = batch_item.get("question", {}).get("diagram") or {}
                        if dq.get("s3_key") == s3_key:
                            page_number = dq.get("page_number")
                            bbox = dq.get("bounding_box")
                            if page_number and bbox and 1 <= page_number <= len(images):
                                try:
                                    page_img = images[page_number - 1]
                                    x1, y1, x2, y2 = bbox
                                    cropped = page_img.crop((x1, y1, x2, y2))
                                    # Resize to a max dimension to limit payload
                                    max_dim = 800
                                    w, h = cropped.size
                                    if max(w, h) > max_dim:
                                        scale = max_dim / float(max(w, h))
                                        cropped = cropped.resize(
                                            (int(w * scale), int(h * scale)),
                                            Image.LANCZOS,
                                        )
                                    buf = BytesIO()
                                    cropped.save(buf, format="JPEG", quality=85)
                                    data = base64.b64encode(buf.getvalue()).decode(
                                        "utf-8"
                                    )
                                    image_contents.append(
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": f"data:image/jpeg;base64,{data}"
                                            },
                                        }
                                    )
                                    inlined = True
                                    break
                                except Exception as ie:
                                    logger.warning(
                                        f"Failed to inline crop for {s3_key}: {ie}"
                                    )
                                    continue
                    if not inlined:
                        missing_images = True

            metadata = {
                "char_length": len(prompt_text),
                "image_count": len(image_contents),
                "missing_images": missing_images,
            }

            prepared.append(
                {
                    "batch_index": batch_idx,
                    "batch_questions": batch,
                    "prompt_text": dedent(prompt_text).strip(),
                    "image_contents": image_contents,
                    "diagram_s3_keys": diagram_s3_keys,
                    "metadata": metadata,
                }
            )

        return prepared

    def _generate_batch_answers(
        self, prepared_batch: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Generate answers and rubrics for a batch of questions.

        Args:
            batch_questions: List of question items needing generation
            images: PDF page images (for diagram context)

        Returns:
            Dictionary mapping question paths to generated data
        """
        # prepared_batch expected to have keys: prompt_text, image_contents, batch_questions, batch_index
        prompt = prepared_batch.get("prompt_text", "")
        image_contents = prepared_batch.get("image_contents", [])
        batch_questions = prepared_batch.get("batch_questions", [])

        logger.info(
            f"Step 3: Prepared prompt length: {len(prompt)} characters for batch {prepared_batch.get('batch_index')}"
        )
        logger.info(
            f"Step 3: Including {len(image_contents)} images in batch {prepared_batch.get('batch_index')}"
        )

        # Build message contents from prepared data
        user_content = [{"type": "text", "text": dedent(prompt).strip()}]
        user_content.extend(image_contents)

        # Call LLM for batch generation
        logger.info("Step 3: Calling LLM for answer/rubric generation...")
        response = self.GPTclient.chat.completions.create(
            model=self.gpt5_model,
            messages=[
                {
                    "role": "system",
                    "content": dedent(
                        """You are an expert educator and mathematical problem solver.

                        CRITICAL INSTRUCTIONS FOR ANSWER GENERATION:
                        1. For mathematical, physics, chemistry, or scientific questions: Provide COMPLETE STEP-BY-STEP DERIVATIONS
                        2. Show ALL intermediate steps - never skip steps
                        3. Explain the reasoning/theorem/principle behind each step
                        4. For algebraic problems: Show every equation manipulation
                        5. For calculus: Show differentiation/integration with all rules applied
                        6. For physics/chemistry: List givens, formulas, substitutions, calculations, and final answer with units
                        7. For numerical problems: Show the complete calculation process
                        8. For conceptual questions: Provide thorough explanations with definitions and examples

                        Use 0-based indexing for options in multiple-choice questions.
                        Use equation placeholders <eq equation_id> for all mathematical expressions.
                        Generate detailed grading rubrics that award partial credit for intermediate steps.
                        Return your response as a JSON object with 'responses' array."""
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            # max_completion_tokens=16384,
            # temperature=0.2,
        )

        response_content = response.choices[0].message.content
        logger.info(
            f"Step 3: LLM response length: {len(response_content) if response_content else 0} characters"
        )
        logger.info(
            f"Step 3: First 1000 chars of response: {response_content[:1000] if response_content else 'EMPTY'}"
        )

        # Handle empty response
        if not response_content or response_content.strip() == "":
            logger.error(
                f"Step 3: LLM returned empty response for {len(batch_questions)} questions. "
                "This may indicate the request was too large or the model failed."
            )
            # Return empty dict if generation fails
            return {}

        result = json.loads(response_content)

        logger.info(f"Step 3: Parsed LLM response as JSON: {result}")

        logger.info(f"Step 3: Parsed JSON keys: {list(result.keys())}")

        # Try multiple possible keys where the LLM might return the data
        generated_answers = (
            result.get("responses", [])
            or result.get("answers", [])
            or result.get("questions", [])
            or result.get("result", [])
            or result.get("results", [])
            or result.get("data", [])
            or []
        )
        logger.info(
            f"Step 3: Found {len(generated_answers)} generated answers in response"
        )

        # If still empty, log the full response for debugging
        if not generated_answers:
            logger.warning(
                f"Step 3: Could not find answers in expected keys. Full response: {response_content[:2000]}"
            )

        # Create a mapping of path to generated data
        path_to_generation = {}
        for gen in generated_answers:
            path = gen.get("question_path")
            if path:
                path_to_generation[path] = gen
                logger.info(
                    f"Step 3: Mapped path '{path}' -> answer='{gen.get('correct_answer', '')[:50]}...', rubric='{gen.get('rubric', '')[:50]}...'"
                )

        logger.info(f"Step 3: Created mapping for {len(path_to_generation)} paths")

        return path_to_generation

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
                prompt = get_question_extraction_prompt(
                    file_name=file_name,
                    file_type="text/plain",
                    images=None,
                    document_text=document_text,
                    s3_urls_info=None,
                )
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
                prompt = get_question_extraction_prompt(
                    file_name=file_name,
                    file_type=file_type,
                    images=None,
                    document_text=document_text,
                    s3_urls_info=s3_urls_info,
                )
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
                prompt = get_question_extraction_prompt(
                    file_name=file_name,
                    file_type=file_type,
                    images=images_info,
                    document_text=document_text,
                    s3_urls_info=None,
                )

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
                        "name": "non_pdf_parsing_response",
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

            def validate_equation_placeholders(
                question: Dict[str, Any], path: str = ""
            ) -> None:
                """Validate that equation placeholders in text match equation metadata"""
                q_id = question.get("id", 0)
                current_path = f"{path}.{q_id}" if path else str(q_id)

                equations = question.get("equations", [])
                if not equations:
                    return

                # Build a map of equation IDs by context
                equations_by_id = {eq["id"]: eq for eq in equations}
                equations_by_context = {}
                for eq in equations:
                    context = eq.get("position", {}).get("context", "unknown")
                    if context not in equations_by_context:
                        equations_by_context[context] = set()
                    equations_by_context[context].add(eq["id"])

                # Check question text
                question_text = question.get("question", "")
                if question_text:
                    question_placeholders = set(
                        re.findall(r"<eq ([^>]+)>", question_text)
                    )
                    question_eq_ids = equations_by_context.get("question_text", set())

                    if question_placeholders != question_eq_ids:
                        logger.warning(
                            f"Q{current_path}: Equation mismatch in question text. "
                            f"Placeholders: {question_placeholders}, Equation IDs: {question_eq_ids}"
                        )

                # Check correct answer
                correct_answer = question.get("correctAnswer", "")
                if correct_answer:
                    answer_placeholders = set(
                        re.findall(r"<eq ([^>]+)>", correct_answer)
                    )
                    answer_eq_ids = equations_by_context.get("correctAnswer", set())

                    if answer_placeholders != answer_eq_ids:
                        logger.warning(
                            f"Q{current_path}: Equation mismatch in correctAnswer. "
                            f"Placeholders: {answer_placeholders}, Equation IDs: {answer_eq_ids}"
                        )

                # Check rubric
                rubric = question.get("rubric", "")
                if rubric:
                    rubric_placeholders = set(re.findall(r"<eq ([^>]+)>", rubric))
                    rubric_eq_ids = equations_by_context.get("rubric", set())

                    if rubric_placeholders != rubric_eq_ids:
                        logger.warning(
                            f"Q{current_path}: Equation mismatch in rubric. "
                            f"Placeholders: {rubric_placeholders}, Equation IDs: {rubric_eq_ids}"
                        )

                # Check options
                options = question.get("options", [])
                for idx, option in enumerate(options):
                    option_placeholders = set(re.findall(r"<eq ([^>]+)>", option))
                    if option_placeholders:
                        # Options context equations should exist
                        options_eq_ids = equations_by_context.get("options", set())
                        # Check if placeholder IDs are in options equations
                        missing = option_placeholders - options_eq_ids
                        if missing:
                            logger.warning(
                                f"Q{current_path}: Option {idx} has placeholders not in equations: {missing}"
                            )

                # Recursively validate subquestions
                for sub in question.get("subquestions", []):
                    validate_equation_placeholders(sub, current_path)

            def normalize_question_fields(
                src: Dict[str, Any], is_subquestion: bool = False
            ) -> Dict[str, Any]:
                """Normalize question fields to match frontend schema"""
                out: Dict[str, Any] = {}

                # Basic fields
                out["id"] = src.get("id", 1)
                out["type"] = src.get("type", "short-answer")

                # Handle empty parent question text for multi-part questions
                question_text = src.get("question", "")
                if (
                    not question_text
                    and src.get("type") == "multi-part"
                    and src.get("subquestions")
                ):
                    # Use a default prompt if parent question is empty
                    subqs = src.get("subquestions", [])
                    if subqs and len(subqs) > 0:
                        question_text = f"Answer the following ({len(subqs)} parts):"
                        logger.warning(
                            f"Q{src.get('id')}: Empty parent question for multi-part type. Using default: '{question_text}'"
                        )

                out["question"] = question_text
                out["points"] = self._parse_points(src.get("points", 0))
                out["rubric"] = src.get("rubric", "")
                out["order"] = src.get("order", 1)

                # Options (for multiple-choice)
                options = src.get("options", [])
                if isinstance(options, list):
                    out["options"] = [str(opt) for opt in options]
                else:
                    out["options"] = []

                # Equations
                out["equations"] = src.get("equations", [])

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

                # Optional parts configuration
                out["optionalParts"] = src.get("optionalParts", False)
                out["requiredPartsCount"] = src.get("requiredPartsCount", 0)

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

                # Validate optional parts configuration
                if normalized_q.get("optionalParts"):
                    required_count = normalized_q.get("requiredPartsCount", 0)
                    subquestion_count = len(normalized_q.get("subquestions", []))

                    if required_count <= 0 or required_count > subquestion_count:
                        logger.warning(
                            f"Question {normalized_q.get('id')}: Invalid optional parts config. "
                            f"Required count ({required_count}) must be between 1 and {subquestion_count}. "
                            f"Disabling optional parts."
                        )
                        normalized_q["optionalParts"] = False
                        normalized_q["requiredPartsCount"] = 0

                normalized_questions.append(normalized_q)
                total_points += normalized_q["points"] or 0

            data["questions"] = normalized_questions
            data["total_points"] = total_points

            # Validate equation placeholders for all questions
            for question in normalized_questions:
                validate_equation_placeholders(question)

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
            logger.info(f"Traceback: {traceback.format_exc()}")
            return questions
