"""
Gemini Diagram Reviewer — Reviews generated diagram images using Gemini 2.5 Pro.

Used when engine=ai is selected. This reviewer uses Google's Gemini 2.5 Pro
(via Vertex AI) for vision-based quality assessment instead of GPT-4o.

Same interface as DiagramReviewer but powered by Gemini.
"""

import base64
import os
import json
from typing import Dict, Any, Optional

from controllers.config import logger


class GeminiDiagramReviewer:
    """Reviews generated diagrams using Gemini 2.5 Pro vision."""

    def __init__(self):
        self._model = None
        self._initialized = False
        self._credentials_path = None

        # Find the service account credentials file
        backend_root = os.path.join(os.path.dirname(__file__), '..', '..')
        for f in os.listdir(backend_root):
            if f.startswith("vidyaai-forms-integrations") and f.endswith(".json"):
                self._credentials_path = os.path.join(backend_root, f)
                break

    def _ensure_initialized(self):
        """Lazy-initialize Vertex AI and the Gemini model."""
        if self._initialized:
            return True

        if not self._credentials_path:
            logger.error("No Google service account credentials file found")
            return False

        try:
            import json as _json
            with open(self._credentials_path, 'r') as f:
                creds_data = _json.load(f)
            project_id = creds_data.get("project_id")
            location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self._credentials_path

            import vertexai
            from vertexai.generative_models import GenerativeModel
            vertexai.init(project=project_id, location=location)

            self._model = GenerativeModel("gemini-2.5-pro")
            self._initialized = True
            logger.info(f"Gemini reviewer initialized: project={project_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Gemini reviewer: {e}")
            return False

    async def review_diagram(
        self,
        image_bytes: bytes,
        question_text: str,
        diagram_description: str,
        user_prompt_context: str = "",
    ) -> Dict[str, Any]:
        """
        Review a generated diagram image using Gemini 2.5 Pro vision.

        Same interface as DiagramReviewer.review_diagram for drop-in replacement.

        Args:
            image_bytes: PNG image bytes of the generated diagram
            question_text: The question the diagram accompanies
            diagram_description: The description used to generate the diagram
            user_prompt_context: The original user prompt for the assignment

        Returns:
            Dict with:
                - passed (bool): True if diagram is acceptable
                - reason (str): Explanation of the verdict
                - corrected_description (str | None): If failed, a better description
                - issues (list[str]): Specific issues found
                - fixable (bool): True if issues are text/label/unit errors that
                  can be fixed by sending the image back for editing (vs. needing
                  a full regeneration due to structural/layout problems)
        """
        if not self._ensure_initialized():
            logger.warning("Gemini reviewer not initialized — passing through")
            return {
                "passed": True,
                "reason": "Gemini reviewer not available — skipped",
                "corrected_description": None,
                "issues": [],
                "fixable": False,
            }

        try:
            from vertexai.generative_models import Part, Image

            # Build the review prompt
            review_prompt = self._build_review_prompt(
                question_text, diagram_description, user_prompt_context
            )

            # Create image part from bytes
            image_part = Part.from_image(Image.from_bytes(image_bytes))

            # Call Gemini 2.5 Pro with vision
            response = self._model.generate_content(
                [review_prompt, image_part],
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 800,
                },
            )

            result_text = response.text.strip()
            return self._parse_review_result(result_text)

        except Exception as e:
            logger.error(f"Gemini diagram review failed: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "passed": True,
                "reason": f"Review skipped due to error: {str(e)}",
                "corrected_description": None,
                "issues": [],
                "fixable": False,
            }

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

        return f"""You are a strict diagram quality reviewer for an educational platform.

Review the attached diagram image and assess its quality.

QUESTION: {question_text}

DIAGRAM DESCRIPTION (used to generate it): {diagram_description}
{context_section}

CHECK ALL OF THE FOLLOWING:
1. Does the diagram correctly represent what was described? (overall structure and layout)
2. Is the diagram style appropriate? (gate-level vs transistor-level, standard symbols)
3. Are key components and their relationships visible?
4. Is the topology/structure correct for the described function?
5. Would a professor accept this diagram for a student assignment?
6. **ANSWER LEAK CHECK**: Does the diagram reveal the answer? Look for:
   - Output values shown ("Output = 0", "Y = 1")
   - Boolean expressions displayed on the diagram
   - Input values shown ("A=1", "B=0") instead of just variable names
   - Truth tables embedded in the diagram
   - Signal values (0/1) annotated on wires
   - Formulas or equations that solve the problem
   If ANY answer is visible, this is a FAIL.

TOLERANCE GUIDELINES (IMPORTANT):
- PASS diagrams with minor cosmetic issues that do NOT affect understanding:
  * Small typos in labels (e.g., "Silcon" instead of "Silicon") — PASS
  * Slightly imprecise units (e.g., "10m" instead of "10 mm") — PASS
  * Minor font size inconsistencies — PASS
  * Slightly cramped but still readable labels — PASS
- Only FAIL for issues that would genuinely confuse a student or are unprofessional:
  * Completely wrong or missing labels on critical components — FAIL
  * Totally illegible text that cannot be read at all — FAIL
  * Wrong diagram structure or topology — FAIL
  * Answer leaks — FAIL
  * Conflicting or duplicate dimension labels on the same edge/side — FAIL
    (e.g., showing both "10 mm" and "1 mm" on the same side of a component is contradictory)
  * A dimension placed on the wrong axis (width label on a height edge or vice versa) — FAIL

RESPOND IN THIS EXACT FORMAT:

VERDICT: PASS or FAIL
FIXABLE: YES or NO
REASON: <one sentence explanation>
ISSUES: <comma-separated list of specific issues, or "none">
CORRECTED_DESCRIPTION: <if FAIL, provide a better description for regeneration, or "none">

FIXABLE GUIDELINES:
- YES if the diagram structure/layout/topology is CORRECT but has text errors:
  wrong labels, misspelled words, incorrect units, garbled dimensions, illegible text
  (these can be fixed by sending the image back for text correction)
- NO if the diagram has STRUCTURAL problems: wrong diagram type, missing components,
  incorrect topology, wrong circuit/pipe/beam layout, answer leaks, fundamentally
  wrong representation (these require full regeneration from scratch)

Be strict ONLY about answer leaks and structural correctness.
Be lenient about minor text/label imperfections — students can still understand the diagram.
If an answer leak is detected, CORRECTED_DESCRIPTION must say:
"Show only circuit/diagram structure with generic input labels and output label. Do NOT show any computed values, boolean expressions, or truth tables."
"""

    def _parse_review_result(self, result_text: str) -> Dict[str, Any]:
        """Parse the structured review response."""
        lines = result_text.strip().split("\n")

        verdict = "PASS"
        reason = "Review completed"
        issues = []
        corrected_desc = None
        fixable = False

        for line in lines:
            line = line.strip()
            if line.upper().startswith("VERDICT:"):
                verdict = line.split(":", 1)[1].strip().upper()
            elif line.upper().startswith("FIXABLE:"):
                fixable_str = line.split(":", 1)[1].strip().upper()
                fixable = "YES" in fixable_str
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
            f"Gemini diagram review: {'PASSED' if passed else 'FAILED'} — {reason}"
        )
        if not passed:
            logger.info(f"  Fixable: {fixable}")
        if issues:
            logger.info(f"  Issues: {issues}")

        return {
            "passed": passed,
            "reason": reason,
            "corrected_description": corrected_desc,
            "issues": issues,
            "fixable": fixable,
        }
