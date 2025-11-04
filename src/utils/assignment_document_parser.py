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
from controllers.config import logger, s3_client, AWS_S3_BUCKET
from controllers.storage import s3_upload_file
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
        Uses efficient 3-step extraction:
        1. Single LLM call to extract all content (questions, diagrams, equations, answers if present)
        2. Gemini calls to extract diagram bounding boxes
        3. Single LLM call to generate missing answers/rubrics

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

            # STEP 1: Single LLM call to extract ALL content including equations
            logger.info(
                "Step 1: Extracting all content (questions, diagrams, equations, answers)..."
            )
            extracted_data = self._extract_all_content(images, file_name)

            # Validate and normalize the response
            result = self._normalize_assignment_data(extracted_data, file_name)

            # STEP 2: Gemini calls to extract diagram bounding boxes
            logger.info("Step 2: Extracting diagram bounding boxes with Gemini...")
            try:
                from controllers.vision_gemini import detect_diagram_bbox

                def enrich_question(q: Dict[str, Any]) -> Dict[str, Any]:
                    if q.get("hasDiagram") and isinstance(q.get("diagram"), dict):
                        diagram = q["diagram"]
                        page_number = diagram.get("page_number")
                        bbox = diagram.get("bounding_box")
                        if page_number and not bbox:
                            if 1 <= page_number <= len(images):
                                page_img = images[page_number - 1]
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
                                        logger.info(
                                            f"Q{q.get('id')}: Gemini bbox detected: {predicted_bbox}"
                                        )
                                except Exception as _e:
                                    logger.warning(
                                        f"Q{q.get('id')}: Gemini bbox detection failed: {_e}"
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

            # STEP 3: Single LLM call to generate missing answers/rubrics
            logger.info("Step 3: Generating missing answers and rubrics...")
            result = self._generate_missing_answers_and_rubrics(result, images)

            result = self._normalize_assignment_data(result, file_name)

            logger.info(
                f"Successfully extracted {len(result.get('questions', []))} questions from PDF images"
            )

            return result

        except Exception as e:
            logger.error(f"Error parsing PDF images: {str(e)}")
            raise

    def _extract_all_content(
        self, images: List[Image.Image], file_name: str
    ) -> Dict[str, Any]:
        """
        Step 1: Single LLM call to extract ALL content.
        Extracts: title, description, questions, types, points, options, diagrams, equations,
        correct answers (if present), rubrics (if present).
        """
        # Convert images to base64
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

        # Create comprehensive extraction prompt
        prompt = f"""
            Analyze this {len(images)}-page PDF document: {file_name}

            Extract ALL assignment content and return the results in JSON format.

            For each question, extract:
            1. Question text (with placeholder for equations)
            2. Question type (multiple-choice, short-answer, long-answer, etc.)
            3. Points/marks
            4. Options (if multiple-choice) (with placeholder for equations)
            5. Diagrams:
            - page_number (which page the diagram appears on)
            - caption (description/title of the diagram)
            - DO NOT include bounding_box (will be extracted separately)
            6. Equations:
            - latex (the LaTeX formatted equation)
            - position (char_index: character position in question text, context: 'question' or 'options')
            - type ('inline' or 'display')
            7. Correct answers (with placeholder for equations) (if clearly stated in the document, otherwise leave as empty string)
            8. Grading rubrics (if provided in the document, otherwise leave as empty string)
            9. Sub-questions (if multi-part question) and sub-sub-question (if sub-question of multi-part question is of multi-part type)

            Also extract:
            - Assignment title (or generate from filename)
            - Assignment description (or brief summary)

            IMPORTANT for equations:
            - char_index is the character count in the question text AFTER which the equation appears
            - Count from the start of the question text (starting at 0)
            - For equations in options, set context to 'options' and include option_index
            - insert placeholders in the appropriate places in the format <eq equation_id>. example: <eq 1>, <eq A1_Q4>

            Return your response as a structured JSON object matching the provided schema.
        """

        # Get comprehensive schema (includes equations, allows empty answers/rubrics)
        response_schema = get_assignment_parsing_schema("step1_pdf_parsing_no_bbox")

        # Build message
        user_content = [{"type": "text", "text": dedent(prompt).strip()}]
        user_content.extend(image_contents)

        # Call LLM
        response = self.client.chat.completions.create(
            model=self.model,
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
                    "name": response_schema["name"],
                    "schema": response_schema,
                },
            },
        )

        extracted_data = json.loads(response.choices[0].message.content)

        logger.info(
            f"Step 1: Extracted {len(extracted_data.get('questions', []))} questions"
        )

        # Log sample of what was extracted
        sample_questions = extracted_data.get("questions", [])[:3]
        for q in sample_questions:
            logger.info(
                f"Step 1: Sample Q{q.get('id')} - answer='{q.get('correctAnswer', '')}', rubric='{q.get('rubric', '')}'"
            )

        logger.info("Step 1: Extracted all content including equations")
        return extracted_data

    def _generate_missing_answers_and_rubrics(
        self, data: Dict[str, Any], images: List[Image.Image]
    ) -> Dict[str, Any]:
        """
        Step 3: Single LLM call to generate missing answers and rubrics for ALL questions.
        Only processes questions that have empty correctAnswer or rubric fields.
        """
        questions = data.get("questions", [])
        logger.info(f"Step 3: Starting with {len(questions)} total questions")

        # Collect all questions that need answers/rubrics
        questions_needing_generation = []

        def collect_incomplete_questions(q: Dict[str, Any], path: str = "") -> None:
            """Recursively collect questions with missing answers/rubrics"""
            q_id = q.get("id", "unknown")
            current_path = f"{path}.{q_id}" if path else str(q_id)

            current_answer = q.get("correctAnswer", "")
            current_rubric = q.get("rubric", "")

            logger.info(
                f"Step 3: Checking Q{current_path} - answer='{current_answer}', rubric='{current_rubric}'"
            )

            needs_answer = not current_answer or current_answer == ""
            needs_rubric = not current_rubric or current_rubric == ""

            if needs_answer or needs_rubric:
                logger.info(
                    f"Step 3: Q{current_path} needs generation (answer={needs_answer}, rubric={needs_rubric})"
                )
                questions_needing_generation.append(
                    {
                        "path": current_path,
                        "question": q,
                        "needs_answer": needs_answer,
                        "needs_rubric": needs_rubric,
                    }
                )

            # Recurse into subquestions
            if q.get("subquestions"):
                logger.info(
                    f"Step 3: Q{current_path} has {len(q['subquestions'])} subquestions"
                )
                for sq in q["subquestions"]:
                    collect_incomplete_questions(sq, current_path)

        for q in questions:
            collect_incomplete_questions(q)

        if not questions_needing_generation:
            logger.info("Step 3: All questions already have answers and rubrics")
            return data

        logger.info(
            f"Step 3: Found {len(questions_needing_generation)} questions needing generation"
        )

        # Build batch prompt with all incomplete questions
        prompt_parts = [
            f"Generate missing correct answers and/or grading rubrics for the following {len(questions_needing_generation)} questions.",
            "Return your response in JSON format as an array of objects, each containing:",
            "- question_path: The path identifier (e.g., '1', '2.1', '3.2.1')",
            "- correct_answer: The correct answer (if needed) (if answer contains diagram, simply explain the diagram.)",
            "- rubric: Detailed grading criteria (if needed)",
            "",
            "Questions requiring generation:",
            "",
        ]

        for item in questions_needing_generation:
            q = item["question"]
            prompt_parts.append(f"Question Path: {item['path']}")
            prompt_parts.append(f"Type: {q.get('type', 'unknown')}")
            prompt_parts.append(f"Points: {q.get('points', 0)}")
            prompt_parts.append(f"Question: {q.get('question', '')}")

            if q.get("options"):
                prompt_parts.append(f"Options: {', '.join(q['options'])}")

            if q.get("equations"):
                eq_list = []
                for eq in q["equations"]:
                    eq_list.append(
                        f"  - {eq['latex']} (type: {eq['type']}, context: {eq['position']['context']})"
                    )
                prompt_parts.append("Equations:")
                prompt_parts.extend(eq_list)

            if q.get("hasDiagram") and q.get("diagram"):
                prompt_parts.append(
                    f"Diagram: {q['diagram'].get('caption', 'See diagram')}"
                )

            prompt_parts.append(
                f"Needs: {'answer' if item['needs_answer'] else ''}{' and ' if item['needs_answer'] and item['needs_rubric'] else ''}{'rubric' if item['needs_rubric'] else ''}"
            )
            prompt_parts.append("")

        prompt = "\n".join(prompt_parts)

        logger.info(f"Step 3: Prompt length: {len(prompt)} characters")
        logger.info(f"Step 3: First 500 chars of prompt: {prompt[:500]}")

        # Call LLM for batch generation
        logger.info("Step 3: Calling LLM for answer/rubric generation...")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert educator. Generate accurate answers and detailed grading rubrics. Return your response as a JSON array.",
                },
                {"role": "user", "content": dedent(prompt).strip()},
            ],
            response_format={"type": "json_object"},
        )

        response_content = response.choices[0].message.content
        logger.info(f"Step 3: LLM response length: {len(response_content)} characters")
        logger.info(f"Step 3: First 1000 chars of response: {response_content[:1000]}")

        result = json.loads(response_content)
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

        logger.info(
            f"Step 3: Created mapping for {len(path_to_generation)} paths: {list(path_to_generation.keys())}"
        )

        # Update questions with generated answers/rubrics
        def update_question_with_generation(
            q: Dict[str, Any], path: str = ""
        ) -> Dict[str, Any]:
            """Recursively update questions with generated answers/rubrics"""
            q_id = q.get("id", "unknown")
            current_path = f"{path}.{q_id}" if path else str(q_id)

            logger.info(
                f"Step 3: Updating Q{current_path}, looking for path in mapping..."
            )

            if current_path in path_to_generation:
                gen = path_to_generation[current_path]
                logger.info(f"Step 3: Found generation data for Q{current_path}")

                if not q.get("correctAnswer") and gen.get("correct_answer"):
                    q["correctAnswer"] = gen["correct_answer"]
                    logger.info(
                        f"Step 3: Updated Q{current_path} correctAnswer: {gen['correct_answer'][:100]}"
                    )

                if not q.get("rubric") and gen.get("rubric"):
                    q["rubric"] = gen["rubric"]
                    logger.info(
                        f"Step 3: Updated Q{current_path} rubric: {gen['rubric'][:100]}"
                    )
            else:
                logger.warning(f"Step 3: No generation data found for Q{current_path}")

            # Recurse into subquestions
            if q.get("subquestions"):
                logger.info(
                    f"Step 3: Processing {len(q['subquestions'])} subquestions of Q{current_path}"
                )
                q["subquestions"] = [
                    update_question_with_generation(sq, current_path)
                    for sq in q["subquestions"]
                ]

            return q

        data["questions"] = [update_question_with_generation(q) for q in questions]
        logger.info(f"Step 3: Completed updating all questions")
        logger.info(
            f"Step 3: Successfully generated answers/rubrics for {len(path_to_generation)} questions"
        )
        return data

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
