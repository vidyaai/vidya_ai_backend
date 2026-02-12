"""
Diagram Review Agent — Reviews generated circuit/diagram images for quality
and prompt alignment using GPT-4o vision.

This agent:
1. Takes a generated diagram PNG and the original prompt/description
2. Uses GPT-4o vision to analyze whether the diagram matches the intent
3. Returns a pass/fail verdict with reasoning
4. If FAIL, provides a corrected description for regeneration
"""

import base64
import os
from typing import Dict, Any, Optional, Tuple

from openai import OpenAI
from controllers.config import logger


class DiagramReviewer:
    """Reviews generated diagrams for quality and prompt alignment."""

    def __init__(self, client: Optional[OpenAI] = None):
        self.client = client or OpenAI()
        self.model = "gpt-4o"

    async def review_diagram(
        self,
        image_bytes: bytes,
        question_text: str,
        diagram_description: str,
        user_prompt_context: str = "",
    ) -> Dict[str, Any]:
        """
        Review a generated diagram image for quality and prompt alignment.

        Args:
            image_bytes: PNG image bytes of the generated diagram
            question_text: The question the diagram accompanies
            diagram_description: The description used to generate the diagram
            user_prompt_context: The original user prompt for the assignment
                (e.g., "digital logic gates at gate level")

        Returns:
            Dict with:
                - passed (bool): True if diagram is acceptable
                - reason (str): Explanation of the verdict
                - corrected_description (str | None): If failed, a better
                    description to regenerate the diagram
                - issues (list[str]): Specific issues found
        """
        try:
            # Encode image to base64
            img_b64 = base64.b64encode(image_bytes).decode("utf-8")

            review_prompt = self._build_review_prompt(
                question_text, diagram_description, user_prompt_context
            )

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": review_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img_b64}",
                                    "detail": "high",
                                },
                            },
                        ],
                    },
                ],
                temperature=0.1,
                max_tokens=800,
            )

            result_text = response.choices[0].message.content.strip()
            return self._parse_review_result(result_text, question_text, user_prompt_context)

        except Exception as e:
            logger.error(f"Diagram review failed: {e}")
            # On error, pass through (don't block diagram generation)
            return {
                "passed": True,
                "reason": f"Review skipped due to error: {str(e)}",
                "corrected_description": None,
                "issues": [],
            }

    def _get_system_prompt(self) -> str:
        return """You are a strict diagram quality reviewer for an educational platform.
You review circuit and technical diagrams to ensure they:
1. Match the question and description intent
2. Use the correct diagram style (gate-level vs transistor-level)
3. Are visually clear and not garbled/overlapping
4. Have proper labels and connections

You MUST respond in this exact format:

VERDICT: PASS or FAIL
REASON: <one sentence explanation>
ISSUES: <comma-separated list of specific issues, or "none">
CORRECTED_DESCRIPTION: <if FAIL, provide a better description for regeneration, or "none">

Be STRICT about these failure criteria:
- If the user prompt asks for "digital logic gates" or "gate-level" circuits,
  the diagram MUST use IEEE block-level gate symbols (D-shaped AND, curved OR,
  triangle NOT with bubble, etc.) — NOT CMOS transistor-level MOSFET diagrams.
- If wires are overlapping, garbled, or unreadable → FAIL
- If labels are missing or illegible → FAIL
- If the circuit topology is clearly wrong for the described function → FAIL
- If the diagram is mostly blank or has rendering artifacts → FAIL
- **ANSWER LEAK CHECK**: If the diagram reveals the answer to the student → FAIL
  Examples of answer leaks that MUST cause FAIL:
  * Output wire labeled with a computed value like "Output = 0", "Y = 1"
  * Boolean expression shown on or near the output (e.g., "F = A'B + AB'")
  * Input wires labeled with specific values like "A=1", "B=0" instead of just "A", "B"
  * Truth table included in the diagram
  * Signal values (0 or 1) annotated on intermediate wires
  If an answer leak is detected, CORRECTED_DESCRIPTION must instruct:
  "Show only circuit structure with generic input labels (A, B, C) and output label (Y/Out). Do NOT show any computed values, boolean expressions, or truth tables."""

    def _build_review_prompt(
        self,
        question_text: str,
        diagram_description: str,
        user_prompt_context: str,
    ) -> str:
        context_section = ""
        if user_prompt_context:
            context_section = f"""
ASSIGNMENT CONTEXT (the user's original prompt):
"{user_prompt_context}"

This context tells you what STYLE of diagram the user expects.
For example, if the context mentions "digital logic gates" or "gate-level",
the diagram MUST show block-level IEEE gate symbols, NOT CMOS transistor-level circuits.
"""

        return f"""Review this generated diagram image.

QUESTION: {question_text}

DIAGRAM DESCRIPTION (used to generate it): {diagram_description}
{context_section}
Analyze the image and check:
1. Does the diagram correctly represent what was described?
2. Is the diagram style appropriate? (gate-level vs transistor-level)
3. Are all labels, wires, and components clearly visible and not overlapping?
4. Is the circuit topology correct for the described function?
5. Would a professor approve this diagram for a student assignment?
6. **ANSWER LEAK CHECK**: Does the diagram reveal the answer? Look for:
   - Output values shown ("Output = 0", "Y = 1")
   - Boolean expressions displayed on the diagram
   - Input values shown ("A=1", "B=0") instead of just variable names
   - Truth tables embedded in the diagram
   - Signal values (0/1) annotated on wires
   If ANY answer is visible, this is a FAIL.

Respond in the EXACT format specified."""

    def _parse_review_result(
        self,
        result_text: str,
        question_text: str,
        user_prompt_context: str,
    ) -> Dict[str, Any]:
        """Parse the structured review response."""
        lines = result_text.strip().split("\n")

        verdict = "PASS"
        reason = "Review completed"
        issues = []
        corrected_desc = None

        for line in lines:
            line = line.strip()
            if line.upper().startswith("VERDICT:"):
                verdict = line.split(":", 1)[1].strip().upper()
            elif line.upper().startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()
            elif line.upper().startswith("ISSUES:"):
                issues_str = line.split(":", 1)[1].strip()
                if issues_str.lower() != "none":
                    issues = [i.strip() for i in issues_str.split(",") if i.strip()]
            elif line.upper().startswith("CORRECTED_DESCRIPTION:"):
                desc = line.split(":", 1)[1].strip()
                if desc.lower() != "none":
                    corrected_desc = desc

        passed = "PASS" in verdict

        logger.info(
            f"Diagram review: {'PASSED' if passed else 'FAILED'} — {reason}"
        )
        if issues:
            logger.info(f"  Issues: {issues}")

        return {
            "passed": passed,
            "reason": reason,
            "corrected_description": corrected_desc,
            "issues": issues,
        }
