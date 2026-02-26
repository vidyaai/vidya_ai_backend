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
        domain: str = "",
        diagram_type: str = "",
    ) -> Dict[str, Any]:
        """
        Review a generated diagram image for quality and prompt alignment.

        Args:
            image_bytes: PNG image bytes of the generated diagram
            question_text: The question the diagram accompanies
            diagram_description: The description used to generate the diagram
            user_prompt_context: The original user prompt for the assignment
                (e.g., "digital logic gates at gate level")
            domain: Subject domain (e.g., "mechanical", "electrical")
            diagram_type: Type of diagram (e.g., "fluid_flow", "circuit_schematic")

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
                question_text,
                diagram_description,
                user_prompt_context,
                domain=domain,
                diagram_type=diagram_type,
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
            return self._parse_review_result(
                result_text, question_text, user_prompt_context
            )

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
  "Show only circuit structure with generic input labels (A, B, C) and output label (Y/Out). Do NOT show any computed values, boolean expressions, or truth tables.
- **LABEL CONSISTENCY CHECK**: Every named entity in the QUESTION text — regardless of
  subject, field, or discipline — must appear in the diagram with the EXACT same name or
  symbol. This rule applies universally: mathematics, physics, chemistry, biology, computer
  science, electrical engineering, mechanical engineering, astronomy, medicine, economics,
  or any other field. If the question names something, the diagram must use that same name.
  Any mismatch is a FAIL — the name used in the question is the authoritative label.
  Also verify that every specific numerical value stated in the question (quantities,
  measurements, parameters) appears on or near the corresponding element in the diagram.
  A duplicate/double label on the same element (same name rendered twice) is a rendering
  error — FAIL.
- **SEMANTIC DATA CONSISTENCY CHECK** (CRITICAL — applies to ALL subjects):
  Extract EVERY specific data value, number, sequence, label, or transition from the
  QUESTION text. Then verify each one appears CORRECTLY in the diagram image. Any
  mismatch between what the question states and what the diagram shows is a FAIL.
  Examples across domains:
  * Electrical/FSM: state names, transition labels (input/output), reset state MUST match question
  * CS linked-list: node values AND order must match (3→5→7→9 ≠ 3→5→7→8)
  * CS trees: node values, parent-child relationships, left/right placement
  * CS graphs: vertex labels, edge weights, directed vs undirected
  * Physics: force labels/directions, wavelengths, object/image distances
  * Math: axis labels, function names, specific points/coordinates
  * Chemistry: atom labels, bond types, reaction arrows
  * Mechanical/Civil: force magnitudes, beam lengths, support types/positions
  When a data mismatch is found, list EVERY mismatch explicitly in ISSUES and provide a
  CORRECTED_DESCRIPTION that includes ALL correct values from the question text."""

    def _build_review_prompt(
        self,
        question_text: str,
        diagram_description: str,
        user_prompt_context: str,
        domain: str = "",
        diagram_type: str = "",
    ) -> str:
        style_hint_section = ""
        domain_rules_section = ""

        if domain:
            try:
                from utils.subject_prompt_registry import SubjectPromptRegistry

                registry = SubjectPromptRegistry()

                # Get style hint for the specific diagram type
                if diagram_type:
                    hint = registry.get_reviewer_style_hint(domain, diagram_type)
                    if hint:
                        style_hint_section = f"\nDIAGRAM STYLE HINT: {hint}\n"

                # Get comprehensive domain-specific review rules
                domain_rules = registry.get_reviewer_domain_rules(domain)
                if domain_rules:
                    domain_rules_section = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  SUBJECT-SPECIFIC REVIEW RULES — Apply these rigorously for this domain      ║
╚══════════════════════════════════════════════════════════════════════════════╝
{domain_rules}
"""
            except Exception:
                pass

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
{style_hint_section}{domain_rules_section}{context_section}
══════════════════════════════════════════════════════════════════════════════
REVIEW CHECKLIST — Verify each item against the image
══════════════════════════════════════════════════════════════════════════════

1. **STRUCTURAL CORRECTNESS**: Does the diagram correctly represent what was described?
   - All components present and correctly connected
   - Topology matches the described function

2. **STYLE APPROPRIATENESS**: Is the diagram style correct for the domain?
   - For digital logic: IEEE gate symbols (not transistor-level) unless CMOS asked
   - For circuits: correct symbol conventions for the region/style

3. **VISUAL CLARITY**: Are all elements clearly visible?
   - No overlapping labels or wires
   - All text readable
   - No rendering artifacts

4. **WIRING/CONNECTION RULES**: Are connections drawn correctly?
   - Wires horizontal/vertical where required (e.g., circuit schematics)
   - No floating nodes (unless intentional open circuit)
   - Junction dots where wires connect

5. **LABELING COMPLETENESS**: Are all components properly labeled?
   - Every named entity in question appears in diagram with EXACT same name
   - All numerical values from question shown on corresponding elements
   - No duplicate/overlapping labels on same element

6. **ANSWER LEAK CHECK**: Does the diagram reveal the answer? FAIL if:
   - Output values shown ("Output = 0", "Y = 1")
   - Boolean expressions on output
   - Input values shown ("A=1") instead of just "A"
   - Truth tables embedded
   - Signal values on intermediate wires
   - Computed results shown (current, voltage, etc. that student should calculate)

7. **SEMANTIC DATA CONSISTENCY CHECK** (CRITICAL — applies to ALL subjects):
   Extract EVERY specific data value, number, sequence, label, or transition from the
   QUESTION text. Verify each one appears CORRECTLY in the diagram image.

   What to compare (domain-generic examples):
   • Electrical/FSM: state names (S0,S1…), transition labels, reset state
   • CS linked-list/tree/graph: node values AND their order/structure
   • Physics: force labels/magnitudes, directions, wavelengths
   • Math: axis labels, function names, point coordinates
   • Chemistry: atom labels, bond types, reaction formulas
   • Mech/Civil: force values, beam lengths, support types/positions

   HOW TO CHECK:
   a) Read the QUESTION and list every specific value, name, or sequence.
   b) For each item, locate it in the diagram.
   c) If a value is DIFFERENT in the diagram vs the question → FAIL.
   d) If a sequence/order is DIFFERENT (e.g., nodes in wrong order) → FAIL.
   e) If a structural relationship is WRONG (e.g., wrong parent in tree) → FAIL.
   List EVERY mismatch in ISSUES.

8. **DOMAIN-SPECIFIC RULES**: Apply ALL rules from the subject-specific section above.

Respond in the EXACT format:

VERDICT: PASS or FAIL
REASON: <one sentence explanation>
ISSUES: <comma-separated list of specific issues, or "none">
CORRECTED_DESCRIPTION: <if FAIL, provide a better description for regeneration, or "none">"""

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

        logger.info(f"Diagram review: {'PASSED' if passed else 'FAILED'} — {reason}")
        if issues:
            logger.info(f"  Issues: {issues}")

        return {
            "passed": passed,
            "reason": reason,
            "corrected_description": corrected_desc,
            "issues": issues,
        }
