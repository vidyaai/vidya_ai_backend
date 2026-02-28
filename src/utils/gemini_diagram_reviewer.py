"""
Gemini Diagram Reviewer — Reviews generated diagram images using Gemini 2.5 Pro.

Used when engine=ai is selected. This reviewer uses Google's Gemini 2.5 Pro
(via Vertex AI) for vision-based quality assessment instead of GPT-4o.

Same interface as DiagramReviewer but powered by Gemini.
"""

import base64
import os
import json
import traceback
from typing import Dict, Any, Optional

from controllers.config import logger


class GeminiDiagramReviewer:
    """Reviews generated diagrams using Gemini 2.5 Pro vision."""

    def __init__(self):
        self._model = None
        self._initialized = False
        self._credentials_path = os.getenv("GOOGLE_CLOUD_CREDENTIALS_FILE")

    def _ensure_initialized(self):
        """Lazy-initialize Vertex AI and the Gemini model."""
        if self._initialized:
            return True

        if not self._credentials_path:
            logger.error("No Google service account credentials file found")
            return False

        try:
            import json as _json

            with open(self._credentials_path, "r") as f:
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
        domain: str = "",
        diagram_type: str = "",
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

        last_error = None  # Track last error for final fallback

        for attempt in range(2):
            try:
                from vertexai.generative_models import Part, Image
                import google.api_core.exceptions

                # Build the review prompt
                review_prompt = self._build_review_prompt(
                    question_text,
                    diagram_description,
                    user_prompt_context,
                    domain=domain,
                    diagram_type=diagram_type,
                )

                # Create image part from bytes
                image_part = Part.from_image(Image.from_bytes(image_bytes))

                # Call Gemini 2.5 Pro with vision with timeout
                response = self._model.generate_content(
                    [review_prompt, image_part],
                    generation_config={
                        "temperature": 0.1,
                        "max_output_tokens": 800,
                    },
                    request_options={"timeout": 60},  # 60 second timeout
                )

                result_text = response.text.strip()
                return self._parse_review_result(result_text)

            except google.api_core.exceptions.Cancelled as e:
                # Handle cancelled/timeout errors specifically
                last_error = e
                logger.error(f"Gemini diagram review cancelled (timeout): {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")

                # Don't retry on timeout - just fail fast
                return {
                    "passed": True,
                    "reason": f"Review skipped due to timeout after {attempt + 1} attempt(s)",
                    "corrected_description": None,
                    "issues": [],
                    "fixable": False,
                }

            except Exception as e:
                last_error = e
                err_str = str(e)

                # gRPC broken pipe / UNAVAILABLE — drop the channel and retry once
                is_connection_error = (
                    "Broken pipe" in err_str
                    or "503" in err_str
                    or "UNAVAILABLE" in err_str
                    or "StatusCode.UNAVAILABLE" in err_str
                )

                if is_connection_error and attempt == 0:
                    logger.warning(
                        f"Gemini reviewer gRPC connection dropped (broken pipe) — "
                        f"reinitializing and retrying..."
                    )
                    self._initialized = False
                    self._model = None
                    if not self._ensure_initialized():
                        break
                    continue

                logger.error(f"Gemini diagram review failed: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                break

        # Fallback return with proper error reference
        error_msg = str(last_error) if last_error else "Unknown error"
        return {
            "passed": True,
            "reason": f"Review skipped due to error: {error_msg}",
            "corrected_description": None,
            "issues": [],
            "fixable": False,
        }

    def _build_review_prompt(
        self,
        question_text: str,
        diagram_description: str,
        user_prompt_context: str,
        domain: str = "",
        diagram_type: str = "",
    ) -> str:
        # Subject style hint — not a new pass/fail rule, just visual guidance
        style_hint_section = ""
        if domain and diagram_type:
            try:
                from utils.subject_prompt_registry import SubjectPromptRegistry

                hint = SubjectPromptRegistry().get_reviewer_style_hint(
                    domain, diagram_type
                )
                if hint:
                    style_hint_section = f"\nDIAGRAM STYLE HINT: {hint}\n"
            except Exception:
                pass

        context_section = ""
        if user_prompt_context:
            context_section = f"""
ASSIGNMENT CONTEXT (the user's original prompt — for STYLE ONLY):
"{user_prompt_context}"

⚠️ CRITICAL: Use this context ONLY to determine the STYLE of diagram:
  - If context mentions "gate-level" or "logic gates" → use block-level IEEE gate symbols
  - If context mentions "transistor-level" or "CMOS schematic" → use transistor symbols
  - That is ALL this context is for.
⛔ DO NOT use this context to require components not mentioned in the QUESTION text above.
⛔ DO NOT fail the diagram for missing a component that appears only in this context but NOT in the QUESTION.
The QUESTION text is the ONLY authoritative source for what components must be present.
"""

        return f"""You are a strict diagram quality reviewer for an educational platform.

Review the attached diagram image and assess its quality.

QUESTION: {question_text}

DIAGRAM DESCRIPTION (used to generate it): {diagram_description}
{style_hint_section}{context_section}

CHECK ONLY THE FOLLOWING — DO NOT check topology, circuit correctness, or domain knowledge:

1. **ANSWER LEAK CHECK**: Does the diagram reveal the answer to the question? Look for:
   - Output values shown ("Output = 0", "Y = 1")
   - Boolean expressions displayed on the diagram
   - Input values shown ("A=1", "B=0") instead of just variable names
   - Truth tables embedded in the diagram
   - Signal values (0/1) annotated on wires
   - Formulas or equations that solve the problem
   If ANY answer is visible, this is a FAIL.

2. **LABEL PRESENCE CHECK**: Structural components explicitly named in the QUESTION text
   must appear as visible labels in the diagram. This applies universally to all subjects.
   - If a structural component named in the question (e.g., a resistor, gate, beam, molecule)
     is entirely absent from the diagram → FAIL
   - If a component is labeled with a different name than the question uses → FAIL
   - A duplicate/double label on a single element → FAIL fixable=YES
   - ⛔ Do NOT fail because a numerical "given" parameter (e.g., gm1=1.5mS, SR=5V/μs, F=250N)
     is absent — those are problem inputs, not required diagram labels.
   List every missing or mismatched component label explicitly in ISSUES.

3. **READABILITY CHECK**: Is the diagram legible enough for a student to use?
   - Totally illegible text that cannot be read at all → FAIL
   - Otherwise PASS even with minor typos or font issues

4. **SEMANTIC DATA CONSISTENCY CHECK** (CRITICAL — applies to ALL subjects):
   Extract EVERY specific data value, number, sequence, label, or transition from the
   QUESTION text. Then verify each one appears CORRECTLY in the diagram image. Any
   mismatch between what the question states and what the diagram shows is a FAIL
   with FIXABLE=NO (the diagram must be regenerated from scratch).

   What to compare (domain-generic examples):
   ── Electrical / Computer Engineering ──
   • FSM: state names (S0, S1…), transitions (input/output on arrows), reset state
   • Circuits: component labels (R1, C2), node names (Vout, Vin), pin names
   • Timing: signal names, clock edges, sequence order

   ── Computer Science ──
   • Linked lists: node values AND their order (3→5→7→9, NOT 3→5→7→8)
   • Trees: node values, parent-child relationships, left/right placement
   • Graphs: vertex labels, edge weights, directed vs undirected
   • Stack/Queue: element values and their top-to-bottom or front-to-back order
   • Hash tables: keys, values, bucket indices

   ── Physics ──
   • Free-body diagrams: force labels (F₁, mg, T), directions (up/down/left/right)
   • Optics: focal lengths, object/image distances, lens/mirror labels
   • Waves: wavelength (λ), amplitude (A), frequency values

   ── Mathematics ──
   • Graphs: axis labels, function names (f(x), g(x)), key points/intercepts
   • Geometry: side lengths, angle measures, vertex labels (A, B, C)
   • Coordinate geometry: specific point coordinates ((2,3), (-1,4))

   ── Chemistry ──
   • Molecular diagrams: atom labels, bond types (single/double/triple)
   • Reaction diagrams: reactant/product formulas, arrow directions
   • Orbital diagrams: energy levels, electron counts

   ── Mechanical / Civil Engineering ──
   • Free-body/structural: force magnitudes (F=250N), moment values, support types
   • Beams: lengths (L=4m), load positions, support locations (pin, roller)
   • Stress/strain: dimension labels, material regions

   HOW TO CHECK:
   a) Read the QUESTION text and list every specific value, name, or sequence.
   b) For each item in the list, locate it in the diagram image.
   c) If a value is DIFFERENT in the diagram than in the question → FAIL.
   d) If a sequence/order is DIFFERENT (e.g., linked list nodes in wrong order) → FAIL.
   e) If a structural relationship is WRONG (e.g., wrong parent-child in tree) → FAIL.
   f) Missing values that ARE structural labels → covered by Check #2 (LABEL CHECK).
   When FAILING for data mismatch, list EVERY mismatch in ISSUES, e.g.:
     "Question says node sequence 3→5→7→9 but diagram shows 3→5→7→8"
     "Question says state S2 transitions to S0 on input 1 but diagram shows S2→S3"

5. **DIAGRAM SOLVABILITY CHECK**: Can a student actually answer the question using only what
   the diagram shows, combined with the question text?
   - If the diagram contains a generic unlabeled block (e.g., "Combo Logic", "Logic Block",
     "CL", "?", or any unnamed black box) AND the question requires knowing what that block
     DOES in order to compute the answer → FAIL, fixable=NO.
   - The principle: any component that is structurally essential to answering the question
     must be shown with enough detail for the student to work with it. A placeholder or
     black box is only acceptable if the question explicitly asks students to DESIGN or FILL IN
     that component themselves.
   - This check is domain-generic: applies equally to circuit logic blocks, mechanical
     subsystems drawn as boxes, software modules, or any other unspecified element whose
     function is needed to answer the question.

⛔ DO NOT verify circuit topology correctness or domain-specific design rules.
⛔ DO NOT fail a diagram because you think a component is "wired incorrectly" or "in the wrong position".
⛔ DO NOT apply your knowledge of standard circuit topologies to judge the diagram.
✅ DO verify that specific data values, labels, sequences, and transitions in the QUESTION
   match what is shown in the diagram — this is a DATA ACCURACY check, not a design correctness check.

TOLERANCE GUIDELINES:
- PASS diagrams with minor cosmetic issues that do NOT affect understanding:
  * Small typos in labels (e.g., "Silcon" instead of "Silicon") — PASS
  * Slightly imprecise units (e.g., "10m" instead of "10 mm") — PASS
  * Minor font size inconsistencies — PASS
  * Slightly cramped but still readable labels — PASS
  * Any circuit topology you personally disagree with — PASS (not your job to verify)

RESPOND IN THIS EXACT FORMAT:

VERDICT: PASS or FAIL
FIXABLE: YES or NO
REASON: <one sentence explanation>
ISSUES: <comma-separated list of SPECIFIC label/readability issues found; write "none" if PASS>
CORRECTED_DESCRIPTION: <if FAIL due to missing/wrong labels, write a complete self-contained description that explicitly names all components from the question; write "none" if PASS>

FIXABLE GUIDELINES:
- YES if the diagram structure is visible but has PURE TEXT errors (wrong/missing labels, illegible text)
- NO for answer leaks or if the diagram is fundamentally unreadable/blank
- NO for semantic data mismatches (wrong values, wrong sequences, wrong transitions) — these require full regeneration

If an answer leak is detected, CORRECTED_DESCRIPTION must say:
"Show only the diagram structure with generic input labels and output label. Do NOT show any computed values, boolean expressions, or truth tables."
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
