from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

from openai import OpenAI

from controllers.storage import s3_presign_url


class LLMGrader:
    """Grades assignment submissions using LLMs with optional diagram (vision) support.

    This service expects assignment questions (including rubrics and points) and a student's
    answers. Answers can be strings or structured objects containing `text`, optional
    `diagram` (with `s3_key`), and nested `subAnswers` for multi-part questions.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-5") -> None:
        if api_key:
            self.client = OpenAI(api_key=api_key)
        else:
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = model

    def grade_submission(
        self,
        assignment: Dict[str, Any],
        submission_answers: Dict[str, Any],
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[float, float, Dict[str, Any], str]:
        """Grade a single submission using bulk LLM call.

        Returns: total_score, total_points, feedback_by_question, overall_feedback
        """
        # Extract answered subquestion IDs for optional parts filtering
        answered_subquestion_ids = self._extract_answered_subquestion_ids(
            assignment.get("questions", []), submission_answers
        )

        flattened_questions = self._flatten_questions(
            assignment.get("questions", []), "", answered_subquestion_ids
        )
        flattened_answers = self._flatten_answers(submission_answers)

        # Partition questions: deterministic (MCQ/TF) vs LLM-required
        deterministic_questions: List[Dict[str, Any]] = []
        llm_questions: List[Dict[str, Any]] = []
        for q in flattened_questions:
            if self._is_deterministic_question(q):
                deterministic_questions.append(q)
            else:
                llm_questions.append(q)

        feedback_by_question: Dict[str, Any] = {}
        overall_feedback = ""

        # Grade deterministic questions locally
        for question in deterministic_questions:
            q_id = str(question.get("id"))
            max_points = float(question.get("points", 0) or 0)
            answer_obj = flattened_answers.get(q_id)
            q_type = (question.get("type") or "").lower()
            if q_type == "multiple-choice":
                score, fb = self._grade_multiple_choice(
                    question, answer_obj, max_points
                )
            elif q_type == "true-false":
                score, fb = self._grade_true_false(question, answer_obj, max_points)
            else:
                score, fb = 0.0, {"breakdown": "Unsupported deterministic type"}
            feedback_by_question[q_id] = {
                "score": score,
                "max_points": max_points,
                "strengths": fb.get("strengths", ""),
                "areas_for_improvement": fb.get("areas_for_improvement", ""),
                "breakdown": fb.get("breakdown", ""),
            }

        print("feedback_by_question before LLM", feedback_by_question)

        # If there are LLM-required questions, build prompt only for them
        if llm_questions:
            prompt_text, diagram_s3_keys = self._build_bulk_prompt(
                llm_questions, flattened_answers
            )

            print("prompt_text", prompt_text)
            # print("diagram_s3_keys", diagram_s3_keys)

            # Build multimodal messages
            system_msg = {
                "role": "system",
                "content": (
                    "You are an expert academic grader. Grade strictly per rubric and points. "
                    "Always return concise, fair judgments in the exact JSON format requested."
                ),
            }

            user_content: List[Dict[str, Any]] = []
            user_content.append({"type": "text", "text": prompt_text})

            # Add all diagram images
            for s3_key in diagram_s3_keys:
                try:
                    presigned = s3_presign_url(s3_key, expires_in=3600)
                    user_content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": presigned},
                        }
                    )
                except Exception:
                    # If presign fails, proceed without image
                    pass

            # Make single LLM call
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[system_msg, {"role": "user", "content": user_content}],
                temperature=0.1,
                max_tokens=2000,  # Increased for bulk response
            )

            result_text = (response.choices[0].message.content or "").strip()

            # Parse bulk response
            (
                llm_feedback_by_question,
                overall_feedback_llm,
            ) = self._parse_bulk_grading_response(result_text, llm_questions)

            # Merge results
            feedback_by_question.update(llm_feedback_by_question)
            # Keep overall feedback from LLM if present
            overall_feedback = overall_feedback_llm or overall_feedback

        print("feedback_by_question after LLM", feedback_by_question)

        # Calculate totals
        total_points = sum(float(q.get("points", 0) or 0) for q in flattened_questions)
        total_score = sum(fb.get("score", 0.0) for fb in feedback_by_question.values())

        return total_score, total_points, feedback_by_question, overall_feedback

    def _is_deterministic_question(self, question: Dict[str, Any]) -> bool:
        q_type = (question.get("type") or "").lower()
        return q_type in {"multiple-choice", "true-false"}

    def _parse_mcq_answer_to_index(
        self, answer: str, options: List[str]
    ) -> Optional[str]:
        """Parse MCQ answer to index string. Handles:
        - Index strings: "0", "1", "2"
        - Single letters: "A", "B", "C", "D" (most common format)
        - Letter prefixes: "A)", "B.", "a)", "b."
        - Roman numerals: "i)", "ii)", "I)", "II."
        - Numbered: "1.", "2.", "3)"
        - Full option text match
        """
        if not answer or not options:
            return None

        answer = answer.strip()

        # Direct index match
        if answer.isdigit():
            idx = int(answer)
            if 0 <= idx < len(options):
                return str(idx)

        # Single letter match (A, B, C, D, etc.) - Handle before letter prefix
        # This is the most common format in student answers
        if len(answer) == 1 and answer.isalpha():
            letter = answer.upper()
            letter_idx = ord(letter) - ord("A")
            if 0 <= letter_idx < len(options):
                return str(letter_idx)

        # Letter prefix match (A), B., a), b.)
        if len(answer) >= 2 and answer[0].isalpha() and answer[1] in ".)":
            letter = answer[0].upper()
            letter_idx = ord(letter) - ord("A")
            if 0 <= letter_idx < len(options):
                return str(letter_idx)

        # Roman numeral match (i, ii, iii, iv, etc.)
        roman_map = {
            "i": 0,
            "ii": 1,
            "iii": 2,
            "iv": 3,
            "v": 4,
            "vi": 5,
            "vii": 6,
            "viii": 7,
            "ix": 8,
            "x": 9,
            "I": 0,
            "II": 1,
            "III": 2,
            "IV": 3,
            "V": 4,
            "VI": 5,
            "VII": 6,
            "VIII": 7,
            "IX": 8,
            "X": 9,
        }
        if answer.lower() in roman_map:
            idx = roman_map[answer.lower()]
            if idx < len(options):
                return str(idx)

        # Numbered prefix match (1., 2., 3), etc.)
        if len(answer) > 1 and answer[0].isdigit() and answer[1] in ".)":
            idx = int(answer[0]) - 1  # Convert 1-based to 0-based
            if 0 <= idx < len(options):
                return str(idx)

        # Full text match
        for i, option in enumerate(options):
            if answer.lower() == option.lower():
                return str(i)

        return None

    def _normalize_mcq_correct_set(self, question: Dict[str, Any]) -> List[str]:
        """Return list of correct answers as indices (strings) when possible.
        Accepts either `correctAnswer` (single index string) or `multipleCorrectAnswers` which may
        contain option texts or indices.
        """
        options: List[str] = question.get("options") or []
        correct_set: List[str] = []
        correct_answer = question.get("correctAnswer")
        allow_multi = bool(question.get("allowMultipleCorrect"))
        multi_list: List[str] = question.get("multipleCorrectAnswers") or []

        # If allowMulti and multi_list provided, map texts to indices when needed
        if allow_multi and multi_list:
            for item in multi_list:
                item_str = str(item)
                parsed_idx = self._parse_mcq_answer_to_index(item_str, options)
                if parsed_idx is not None:
                    correct_set.append(parsed_idx)
            # De-duplicate
            correct_set = sorted(set(correct_set), key=lambda x: int(x))
        else:
            # Single-select: prefer `correctAnswer` if present, otherwise fall back to first of multi_list
            if correct_answer is not None:
                parsed_idx = self._parse_mcq_answer_to_index(
                    str(correct_answer), options
                )
                if parsed_idx is not None:
                    correct_set = [parsed_idx]
            elif multi_list:
                # Try to map first entry
                first = str(multi_list[0])
                parsed_idx = self._parse_mcq_answer_to_index(first, options)
                if parsed_idx is not None:
                    correct_set = [parsed_idx]
        return correct_set

    def _normalize_mcq_student_selection(
        self, answer_obj: Any, options: List[str]
    ) -> List[str]:
        """Return list of selected indices (strings). Accepts:
        - single string index (e.g., "1")
        - list/array of strings/ints (e.g., ["0", "2"]) for multi-select
        - comma-separated string (e.g., "0,2,3")
        - text-based answers (e.g., "A)", "B.", "i)", "1.", "b)", full option text)
        """
        if answer_obj is None:
            return []
        if isinstance(answer_obj, dict):
            # Accept object answers that may carry text/diagram; in MCQ we expect selection in `text`
            if "text" in answer_obj:
                answer_obj = answer_obj.get("text")
            else:
                # No text field; nothing to grade
                return []

        # Handle list/array inputs
        if isinstance(answer_obj, list):
            indices = []
            for item in answer_obj:
                parsed_idx = self._parse_mcq_answer_to_index(str(item), options)
                if parsed_idx is not None:
                    indices.append(parsed_idx)
            return indices

        # Handle string inputs
        if isinstance(answer_obj, str):
            s = answer_obj.strip()
            if "," in s:
                # Comma-separated values
                indices = []
                for part in s.split(","):
                    part = part.strip()
                    if part:
                        parsed_idx = self._parse_mcq_answer_to_index(part, options)
                        if parsed_idx is not None:
                            indices.append(parsed_idx)
                return indices
            else:
                # Single value
                parsed_idx = self._parse_mcq_answer_to_index(s, options)
                return [parsed_idx] if parsed_idx is not None else []

        # Handle numeric inputs
        try:
            parsed_idx = self._parse_mcq_answer_to_index(str(int(answer_obj)), options)
            return [parsed_idx] if parsed_idx is not None else []
        except Exception:
            return []

    def _grade_multiple_choice(
        self, question: Dict[str, Any], answer_obj: Any, max_points: float
    ) -> Tuple[float, Dict[str, Any]]:
        allow_multi = bool(question.get("allowMultipleCorrect"))
        options = question.get("options") or []
        correct_set = set(self._normalize_mcq_correct_set(question))
        selected_set = set(self._normalize_mcq_student_selection(answer_obj, options))

        if not correct_set:
            return 0.0, {"breakdown": "No correct answer configured"}

        if not allow_multi:
            score = (
                max_points
                if selected_set and list(selected_set)[0] in correct_set
                else 0.0
            )
        else:
            if not selected_set:
                score = 0.0
            else:
                intersection = len(correct_set & selected_set)
                union = len(correct_set | selected_set)
                score = (intersection / union) * max_points if union > 0 else 0.0

        return score, {
            "breakdown": f"Selected={sorted(selected_set)} Correct={sorted(correct_set)}",
            "strengths": "Correct selection" if selected_set == correct_set else "",
            "areas_for_improvement": "Review correct options"
            if score < max_points
            else "",
        }

    def _grade_true_false(
        self, question: Dict[str, Any], answer_obj: Any, max_points: float
    ) -> Tuple[float, Dict[str, Any]]:
        correct_raw = question.get("correctAnswer")
        correct_val: Optional[bool] = None
        if isinstance(correct_raw, bool):
            correct_val = correct_raw
        elif isinstance(correct_raw, str):
            cr = correct_raw.strip().lower()
            if cr in {"true", "t", "1", "yes", "y"}:
                correct_val = True
            elif cr in {"false", "f", "0", "no", "n"}:
                correct_val = False

        # Normalize student answer
        student_val: Optional[bool] = None
        if isinstance(answer_obj, dict) and "text" in answer_obj:
            answer_obj = answer_obj.get("text")
        if isinstance(answer_obj, bool):
            student_val = answer_obj
        elif isinstance(answer_obj, str):
            s = answer_obj.strip().lower()
            if s in {"true", "t", "1", "yes", "y"}:
                student_val = True
            elif s in {"false", "f", "0", "no", "n"}:
                student_val = False

        if correct_val is None or student_val is None:
            return 0.0, {"breakdown": "Invalid or missing true/false answer"}

        score = max_points if correct_val == student_val else 0.0
        return score, {
            "breakdown": f"Student={student_val} Correct={correct_val}",
            "strengths": "Correct truth value" if score == max_points else "",
            "areas_for_improvement": "Review statement truth value"
            if score == 0
            else "",
        }

    def _flatten_questions(
        self,
        questions: List[Dict[str, Any]],
        parent_id: str = "",
        answered_subquestion_ids: Dict[str, List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Recursively flatten questions to handle nested multi-part questions at any depth.

        Generates composite IDs that match the PDF extraction format:
        - Top-level questions: keep original ID (e.g., "1", "17", "33")
        - Subquestions: create composite IDs like "17.1", "17.2", "33.1.1" using sequential numbering
        This matches the format from _normalize_question_number() in pdf_answer_processor.py

        For optional parts (optionalParts: true), only includes subquestions that were answered.
        """
        if answered_subquestion_ids is None:
            answered_subquestion_ids = {}

        flattened: List[Dict[str, Any]] = []
        subquestion_counter = 0  # Counter for subquestions at current level

        for q in questions:
            original_id = str(q.get("id"))

            if q.get("type") == "multi-part" and q.get("subquestions"):
                # For multi-part questions, flatten subquestions
                if parent_id:
                    # Nested multi-part: increment counter and use as part of parent ID
                    subquestion_counter += 1
                    sub_parent_id = f"{parent_id}.{subquestion_counter}"
                else:
                    # Top-level multi-part: use original ID as prefix
                    sub_parent_id = original_id

                # For optional parts, filter to only include answered subquestions
                subquestions_to_process = q.get("subquestions", [])
                if q.get("optionalParts"):
                    # Get list of answered subquestion IDs for this question
                    answered_subq_ids = answered_subquestion_ids.get(original_id, [])
                    # Filter to only include answered subquestions
                    subquestions_to_process = [
                        subq
                        for subq in subquestions_to_process
                        if str(subq.get("id")) in answered_subq_ids
                    ]

                # Recursively flatten subquestions with composite parent ID
                sub_flattened = self._flatten_questions(
                    subquestions_to_process, sub_parent_id, answered_subquestion_ids
                )
                flattened.extend(sub_flattened)
            else:
                # Regular question - create composite ID if we have a parent
                if parent_id:
                    # Use SEQUENTIAL numbering (1, 2, 3...) to match PDF extraction format
                    # This matches how 17(a) -> 17.1, 17(b) -> 17.2 in pdf_answer_processor
                    subquestion_counter += 1
                    composite_id = f"{parent_id}.{subquestion_counter}"
                    # Create a copy of the question with the composite ID
                    q_copy = q.copy()
                    q_copy["id"] = composite_id
                    q_copy["original_id"] = original_id  # Keep original for reference
                    flattened.append(q_copy)
                else:
                    # Top-level question - keep original ID
                    flattened.append(q)
        return flattened

    def _flatten_answers(self, answers: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively flatten student answers to match the structure of flattened questions.

        Handles different answer structures:
        - String answers: keep as-is
        - Object answers with text/diagram: keep object structure
        - Answers with subAnswers: recursively flatten at any depth
        - Direct answers to multi-part questions: stored at parent level for fallback
        """
        flattened: Dict[str, Any] = {}

        for question_id, answer in answers.items():
            if isinstance(answer, str):
                # Simple string answer - keep as-is
                flattened[question_id] = answer
            elif isinstance(answer, dict):
                if "subAnswers" in answer:
                    # Multi-part answer - recursively flatten subAnswers
                    sub_answers = answer.get("subAnswers", {})
                    sub_flattened = self._flatten_answers(sub_answers)
                    for sub_id, sub_answer in sub_flattened.items():
                        # Create composite question ID (e.g., "17.171", "29.294.1761205736950")
                        composite_id = f"{question_id}.{sub_id}"
                        flattened[composite_id] = sub_answer

                    # Also store the parent-level answer if it has text/diagram
                    # This handles cases where student provides answer at parent level
                    if answer.get("text") or answer.get("diagram"):
                        flattened[question_id] = {
                            k: v for k, v in answer.items() if k != "subAnswers"
                        }
                else:
                    # Object answer with text/diagram but no subAnswers
                    # This might be a direct answer to a multi-part question
                    # Store it at the parent level - the grading logic will handle it
                    flattened[question_id] = answer
            else:
                # Fallback - convert to string
                flattened[question_id] = str(answer)

        return flattened

    def _extract_answered_subquestion_ids(
        self, questions: List[Dict[str, Any]], answers: Dict[str, Any]
    ) -> Dict[str, List[str]]:
        """Extract which subquestions were answered for optional parts questions.

        Returns a dictionary mapping question IDs to lists of answered subquestion IDs.
        """
        answered_map = {}

        for q in questions:
            q_id = str(q.get("id"))
            if q.get("type") == "multi-part" and q.get("optionalParts"):
                answer_obj = answers.get(q_id)
                if answer_obj and isinstance(answer_obj, dict):
                    subanswers = answer_obj.get("subAnswers", {})
                    # Track which subquestions have non-empty answers
                    answered_subq_ids = [k for k, v in subanswers.items() if v]
                    answered_map[q_id] = answered_subq_ids

                    # Recursively handle nested optional parts
                    if q.get("subquestions"):
                        for subq in q.get("subquestions"):
                            subq_id = str(subq.get("id"))
                            if subq.get("type") == "multi-part" and subq.get(
                                "optionalParts"
                            ):
                                subq_answer = subanswers.get(subq_id)
                                if subq_answer and isinstance(subq_answer, dict):
                                    subq_subanswers = subq_answer.get("subAnswers", {})
                                    answered_subsubq_ids = [
                                        k for k, v in subq_subanswers.items() if v
                                    ]
                                    answered_map[subq_id] = answered_subsubq_ids

        return answered_map

    def _build_bulk_prompt(
        self,
        flattened_questions: List[Dict[str, Any]],
        flattened_answers: Dict[str, Any],
    ) -> Tuple[str, List[str]]:
        """Build a comprehensive prompt with all questions and answers in interleaved format.

        Returns:
            Tuple of (prompt_text, list_of_diagram_s3_keys)
        """
        prompt_parts = []
        diagram_s3_keys = []

        prompt_parts.append(
            "You are an expert academic grader. Grade this student's submission for all questions. "
            "For each question, provide a score, strengths, areas for improvement, and detailed breakdown. "
            "Return your response as JSON with the following structure:\n"
            "{\n"
            '  "question_<id>": {\n'
            '    "score": <float in [0, max_points]>,\n'
            '    "strengths": "<brief strengths>",\n'
            '    "areas_for_improvement": "<areas to improve>",\n'
            '    "breakdown": "<detailed analysis>"\n'
            "  },\n"
            '  "overall_feedback": "<overall assessment>"\n'
            "}\n\n"
            "GRADING CRITERIA:\n"
        )

        for question in flattened_questions:
            q_id = str(question.get("id"))
            q_type = question.get("type", "text")
            question_text = question.get("question", "")
            rubric = question.get("rubric", "")
            correct_answer = question.get("correctAnswer") or question.get(
                "correct_answer", ""
            )
            max_points = float(question.get("points", 0) or 0)

            # Add question details
            prompt_parts.append(f"QUESTION {q_id} ({q_type}):")
            prompt_parts.append(f"{question_text}")

            if correct_answer:
                prompt_parts.append(f"REFERENCE ANSWER:\n{correct_answer}")

            if rubric:
                prompt_parts.append(f"RUBRIC:\n{rubric}")

            prompt_parts.append(f"MAX POINTS: {max_points}")

            # Add student answer
            answer_obj = flattened_answers.get(q_id)
            if answer_obj is not None:
                if isinstance(answer_obj, str):
                    prompt_parts.append(f"STUDENT ANSWER:\n{answer_obj}")
                elif isinstance(answer_obj, dict):
                    text_answer = answer_obj.get("text", "")
                    if text_answer:
                        prompt_parts.append(f"STUDENT ANSWER (text):\n{text_answer}")

                    # Check for diagram
                    diagram = answer_obj.get("diagram")
                    if diagram and isinstance(diagram, dict):
                        s3_key = diagram.get("s3_key")
                        if s3_key:
                            diagram_s3_keys.append(s3_key)
                            prompt_parts.append(
                                f"STUDENT ANSWER (diagram): [Image attached - see diagram for question {q_id}]"
                            )
            else:
                prompt_parts.append("STUDENT ANSWER: <no answer provided>")

            prompt_parts.append("")  # Empty line between questions

        return "\n".join(prompt_parts), diagram_s3_keys

    def _parse_bulk_grading_response(
        self, response_text: str, flattened_questions: List[Dict[str, Any]]
    ) -> Tuple[Dict[str, Any], str]:
        """Parse JSON response from bulk grading LLM call.

        Returns:
            Tuple of (feedback_by_question, overall_feedback)
        """
        import json

        feedback_by_question = {}
        overall_feedback = ""

        try:
            # Try to parse as JSON
            response_data = json.loads(response_text)

            # Extract overall feedback
            overall_feedback = response_data.get("overall_feedback", "")

            # Extract per-question feedback
            for question in flattened_questions:
                q_id = str(question.get("id"))
                max_points = float(question.get("points", 0) or 0)

                question_key = f"question_{q_id}"
                question_data = response_data.get(question_key, {})

                # Extract score and feedback
                score = float(question_data.get("score", 0.0))
                score = max(0.0, min(score, max_points))  # Clamp to valid range

                feedback_by_question[q_id] = {
                    "score": score,
                    "max_points": max_points,
                    "strengths": question_data.get("strengths", ""),
                    "areas_for_improvement": question_data.get(
                        "areas_for_improvement", ""
                    ),
                    "breakdown": question_data.get("breakdown", ""),
                }

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # Fallback: try to extract information using regex patterns
            import re

            # Extract overall feedback
            overall_match = re.search(r'"overall_feedback":\s*"([^"]*)"', response_text)
            if overall_match:
                overall_feedback = overall_match.group(1)

            # Extract per-question scores and feedback
            for question in flattened_questions:
                q_id = str(question.get("id"))
                max_points = float(question.get("points", 0) or 0)

                # Try to find score for this question
                score_pattern = rf'"question_{q_id}":\s*{{[^}}]*"score":\s*([0-9.]+)'
                score_match = re.search(score_pattern, response_text)
                score = float(score_match.group(1)) if score_match else 0.0
                score = max(0.0, min(score, max_points))

                # Extract other fields
                strengths = ""
                areas = ""
                breakdown = ""

                strengths_match = re.search(
                    rf'"question_{q_id}":\s*{{[^}}]*"strengths":\s*"([^"]*)"',
                    response_text,
                )
                if strengths_match:
                    strengths = strengths_match.group(1)

                areas_match = re.search(
                    rf'"question_{q_id}":\s*{{[^}}]*"areas_for_improvement":\s*"([^"]*)"',
                    response_text,
                )
                if areas_match:
                    areas = areas_match.group(1)

                breakdown_match = re.search(
                    rf'"question_{q_id}":\s*{{[^}}]*"breakdown":\s*"([^"]*)"',
                    response_text,
                )
                if breakdown_match:
                    breakdown = breakdown_match.group(1)

                feedback_by_question[q_id] = {
                    "score": score,
                    "max_points": max_points,
                    "strengths": strengths,
                    "areas_for_improvement": areas,
                    "breakdown": breakdown,
                }

        return feedback_by_question, overall_feedback

    def _build_prompt(
        self,
        question_text: Optional[str],
        q_type: Optional[str],
        rubric: Optional[str],
        correct_answer: Optional[str],
        text_answer: Optional[str],
        max_points: float,
    ) -> str:
        parts: List[str] = []
        if question_text:
            parts.append(f"Question ({q_type or 'text'}):\n{question_text}")
        if correct_answer:
            parts.append(f"Sample/Reference Answer:\n{correct_answer}")
        if rubric:
            parts.append(f"Rubric:\n{rubric}")
        parts.append(f"Max Points: {max_points}")
        if text_answer is not None:
            parts.append(f"Student Answer (text):\n{text_answer}")
        else:
            parts.append("Student Answer (text): <none>")
        parts.append(
            (
                "If an image is attached, evaluate correctness, completeness, labels, and alignment "
                "with the rubric. Respond with this exact format:\n"
                "SCORE: <float in [0,max_points]>\n"
                "Strengths: ...\n"
                "AreasForImprovement: ...\n"
                "Breakdown: ...\n"
            )
        )
        return "\n\n".join(parts)

    def _parse_score_and_feedback(
        self, text: str, default_max: float
    ) -> Tuple[float, Dict[str, Any]]:
        score = 0.0
        strengths = None
        areas = None
        breakdown = text
        try:
            import re

            m = re.search(r"SCORE:\s*([0-9]+(?:\.[0-9]+)?)", text)
            if m:
                score = float(m.group(1))
            strengths_m = re.search(r"Strengths:\s*(.*)", text, re.IGNORECASE)
            if strengths_m:
                strengths = strengths_m.group(1).strip()
            areas_m = re.search(r"AreasForImprovement:\s*(.*)", text, re.IGNORECASE)
            if areas_m:
                areas = areas_m.group(1).strip()
            breakdown_m = re.search(
                r"Breakdown:\s*(.*)", text, re.IGNORECASE | re.DOTALL
            )
            if breakdown_m:
                breakdown = breakdown_m.group(1).strip()
        except Exception:
            pass
        score = max(0.0, min(score, default_max))
        return score, {
            "breakdown": breakdown,
            "strengths": strengths,
            "areas_for_improvement": areas,
        }
