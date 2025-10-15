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

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o") -> None:
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
        """Grade a single submission.

        Returns: total_score, total_points, feedback_by_question, overall_feedback
        """
        flattened_questions = self._flatten_questions(assignment.get("questions", []))

        total_points = 0.0
        total_score = 0.0
        feedback_by_question: Dict[str, Any] = {}

        for q in flattened_questions:
            q_id = str(q.get("id"))
            max_points = float(q.get("points", 0) or 0)
            total_points += max_points

            answer_obj = submission_answers.get(q_id)
            score, fb = self._grade_single_question(q, answer_obj, max_points)
            total_score += max(0.0, min(score, max_points))
            feedback_by_question[q_id] = {
                "score": score,
                "max_points": max_points,
                **fb,
            }

        percentage = (total_score / total_points * 100.0) if total_points > 0 else 0.0
        overall_feedback = self._synthesize_overall_feedback(
            feedback_by_question, percentage
        )
        return total_score, total_points, feedback_by_question, overall_feedback

    def _flatten_questions(
        self, questions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        flattened: List[Dict[str, Any]] = []
        for q in questions:
            if q.get("type") == "multi-part" and q.get("subquestions"):
                # include a synthetic container for scoring by parts later if needed
                for subq in self._flatten_questions(q.get("subquestions", [])):
                    flattened.append(subq)
            else:
                flattened.append(q)
        return flattened

    def _grade_single_question(
        self, question: Dict[str, Any], answer_obj: Any, max_points: float
    ) -> Tuple[float, Dict[str, Any]]:
        """Grade a single question, supporting text-only and diagram-inclusive answers."""
        q_type = question.get("type")
        question_text = question.get("question")
        rubric = question.get("rubric")
        correct_answer = question.get("correctAnswer") or question.get("correct_answer")

        # Normalize answer
        text_answer: Optional[str] = None
        diagram_s3_key: Optional[str] = None

        if isinstance(answer_obj, str):
            text_answer = answer_obj
        elif isinstance(answer_obj, dict):
            text_answer = (
                answer_obj.get("text")
                if isinstance(answer_obj.get("text"), str)
                else None
            )
            if answer_obj.get("diagram") and isinstance(
                answer_obj.get("diagram"), dict
            ):
                diagram_s3_key = answer_obj["diagram"].get("s3_key")

        # Build multimodal messages
        system_msg = {
            "role": "system",
            "content": (
                "You are an expert academic grader. Grade strictly per rubric and points. "
                "Always return concise, fair judgments."
            ),
        }

        user_content: List[Dict[str, Any]] = []
        prompt_text = self._build_prompt(
            question_text, q_type, rubric, correct_answer, text_answer, max_points
        )
        user_content.append({"type": "text", "text": prompt_text})

        if diagram_s3_key:
            try:
                presigned = s3_presign_url(diagram_s3_key, expires_in=3600)
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": presigned},
                    }
                )
            except Exception:
                # If presign fails, proceed without image
                pass

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[system_msg, {"role": "user", "content": user_content}],
            temperature=0.1,
            max_tokens=1200,
        )

        result_text = (response.choices[0].message.content or "").strip()
        # Expected lightweight protocol: first line "SCORE: <float>" then feedback lines
        score, feedback = self._parse_score_and_feedback(
            result_text, default_max=max_points
        )
        return score, feedback

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

    def _synthesize_overall_feedback(
        self, per_q: Dict[str, Any], percentage: float
    ) -> str:
        # Concise rollup
        lines = [f"Overall Percentage: {percentage:.2f}%"]
        lines.append("Summary:")
        # Heuristic brief summary from first few questions
        count = 0
        for qid, fb in per_q.items():
            if count >= 3:
                break
            s = fb.get("strengths") or ""
            a = fb.get("areas_for_improvement") or ""
            lines.append(f"Q{qid} — + {s[:100]} | - {a[:100]}")
            count += 1
        return "\n".join(lines)
