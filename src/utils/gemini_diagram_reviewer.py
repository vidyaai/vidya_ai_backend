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
                    # request_options={"timeout": 60},  # 60 second timeout
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

0. **DIAGRAM TYPE CORRECTNESS CHECK** (highest priority):
   Read the QUESTION and DIAGRAM DESCRIPTION to identify the REQUIRED diagram type
   (e.g., "right-angled triangle", "BCC unit cell", "Hohmann transfer orbit",
   "free body diagram", "bar chart", "sequence diagram", "Bloch sphere").

   Look at the image: is the diagram actually showing that type?

   FAIL if the diagram shows a FUNDAMENTALLY DIFFERENT type of structure than requested:
   - Wrong geometric shape (equilateral instead of right-angled triangle)
   - Wrong crystal structure type (FCC lattice instead of BCC lattice)
   - Wrong orbit type (circular orbit instead of elliptical transfer orbit)
   - Wrong chart type (pie chart instead of bar chart)
   - Completely wrong domain (circuit diagram shown for a biology question)
   - Normal insulator band structure shown instead of topological insulator band structure

   This is a fixable=NO failure — the diagram must be regenerated from scratch.
   For wrong_type failures, CORRECTED_DESCRIPTION is MANDATORY and must contain all four:
   1. "WRONG: [exact name of what was shown]"
   2. "CORRECT: [exact name of what must be shown]"
   3. "VISUAL FEATURES: [2-3 specific visual differences the eye can see]"
   4. "DO NOT: [the specific wrong default to avoid]"
   Example: "WRONG: normal semiconductor band structure with parabolic gap. CORRECT: topological
   insulator band structure. VISUAL FEATURES: valence band crosses ABOVE conduction band (band
   inversion); linear Dirac cone at k=0 crossing through the gap; two band sets (bulk + surface).
   DO NOT draw simple parabolic bands with a gap at zone center."
   Set FAILURE_TYPE: wrong_type

   DO NOT fail for incorrect wiring, component placement, or design rule violations
   within the correct diagram type — those are topology checks, not type checks.

1. **ANSWER LEAK CHECK** (applies to ALL subjects — not just circuits):
   Step 1 — Identify the TARGET: Read the QUESTION and determine what the student
   is being asked to FIND, IDENTIFY, EXPLAIN, CALCULATE, or DESCRIBE. This is the "target".
   Step 2 — Check the diagram: Does the diagram directly show or trivially reveal the target?

   PRINCIPLE: The diagram must show SETUP and CONTEXT. It must NOT show the CONCLUSION.

   IMPORTANT EXCEPTIONS — these are NEVER answer leaks:
   - Quantum gate and qubit names: "Data qubit", "Ancilla qubit", "H", "CNOT", "X", "Z", "T", "S",
     "Toffoli", "Hadamard", "measurement gate", "control qubit", "target qubit", "ancilla bit".
   - Band structure axis labels: "Valence Band", "Conduction Band", "E" (energy axis), "k" (momentum
     axis), "E_F" (Fermi energy), "E_g" (band gap label) — these identify axes/regions used to READ
     the answer, not the answer itself.
   - Crystal/lattice component labels: "lattice point", "unit cell", "corner atom", "body-center atom",
     "face-center atom", "basis vector a", "basis vector b", "basis vector c".
   - Orbital mechanics structural labels: "perihelion", "aphelion", "semi-major axis a",
     "transfer ellipse", "orbit path", "space probe", "planet".
   - Game theory structural labels: player node names (Player 1, Player 2), strategy branch labels
     (High, Low, Cooperate, Defect) — but NOT solution labels (Nash Equilibrium, Pareto Frontier).
   - Node names (Vout, Vin, VDD), axis labels (Energy, Momentum, Temperature, Frequency),
     species names (He-3, He-4, proton, neutron), geometric labels (angle A, side c, hypotenuse).
   - Physical quantities given as SETUP context in the question (not as the answer).
   - Structural labels that identify WHAT a component IS, not the ANSWER to the question.

   THESE ARE answer leaks (conclude the student's task):
   - "Z2 Topological Invariant", "Band Inversion", or region labeled "Topological"/"Trivial"
   - "Systematic absences" in a crystallography legend or annotation
   - "Pareto Frontier", "Pareto Front", "Nash Equilibrium", "Dominant Strategy" labels
   - Shell element products (C, O, Ne, Si, Fe) in stellar nucleosynthesis if students must identify them
   - "Syndrome Table", "Logical Qubit Encoding Path", or any annotation naming what a QEC circuit DOES
   - "Feasible Region", "Infeasible Region", "Stable", "Unstable", "Optimal" region labels

   ONLY fail for labels that name the CONCLUSION the student must derive, not component names.

   FAIL if the diagram shows the target answer through ANY of these patterns:
   - LABELS: Any text label, annotation, or region name that names or interprets the
     answer the student is supposed to derive (e.g., "Feasible", "Infeasible", "Stable",
     "Unstable", "Optimal", "Threshold Region", "Detection occurs here", "Fusion viable").
   - PRODUCTS/OUTCOMES: In flowcharts or reaction diagrams, the specific outputs/products
     on each step fully labeled when the question asks the student to identify those steps
     or products.
   - FORMULAS: A formula or equation rendered as text on the diagram that encodes the
     relationship the student must explain or derive.
   - CONCLUSIONS: A title, caption, or annotation that states the conclusion of a
     comparison or analysis (e.g., "A uses less energy than B", "X is more accurate").
   - COMPUTED VALUES: Specific numerical answers, thresholds, or equilibrium values
     annotated when the student must calculate or determine those values.

   If the diagram reveals the target answer → FAIL with fixable=NO. In CORRECTED_DESCRIPTION,
   you MUST explicitly list the exact label text(s) to remove, e.g.:
   "Remove the label 'Feasible Region' and the annotation '5 m/s'. Keep all input values
   and structural labels. [rest of description]"
   Always name the offending labels verbatim — do not paraphrase them.

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

   When data_mismatch is detected, CORRECTED_DESCRIPTION is MANDATORY. Use this format
   for each mismatch found:
     "MISMATCH [n]: diagram shows [X] but question requires [Y].
      VISUAL FIX: [exact visual change needed, e.g. 'plane must be parallel to yz-axis',
      'near-perihelion sector must be ~3x smaller area than near-aphelion sector',
      'payoff for (Low,High) must be exactly (2,4) not (3,3)']"
   List every mismatch as a separate numbered entry. Be quantitatively specific.

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
  * Redundant or duplicate labels (the same label appearing twice on one element) — PASS, do not fail for this
  * Minor label redundancy that doesn't cause genuine confusion (e.g., "Incoming Space Probe" on a trajectory already showing a probe path) — PASS
  * A label that names what an element IS (e.g., "Space Probe", "Orbit Path", "Transfer Ellipse") even if it seems obvious — PASS, these are structural identifiers not answer leaks

RESPOND IN THIS EXACT FORMAT:

VERDICT: PASS or FAIL
FAILURE_TYPE: none|wrong_type|answer_leak|missing_labels|data_mismatch|readability
FIXABLE: YES or NO
REASON: <one sentence explanation>
ISSUES: <comma-separated list of SPECIFIC label/readability issues found; write "none" if PASS>
CORRECTED_DESCRIPTION: <if FAIL due to missing/wrong labels, write a complete self-contained description that explicitly names all components from the question; write "none" if PASS>

FAILURE_TYPE values:
- none: diagram passed
- wrong_type: diagram is the wrong fundamental type (Check 0)
- answer_leak: diagram reveals the answer (Check 1)
- missing_labels: required structural labels absent (Check 2)
- readability: text illegible (Check 3)
- data_mismatch: specific values/sequences don't match question (Check 4)

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
        failure_type = "none"
        reason = "Review completed"
        issues = []
        corrected_desc = None
        fixable = False

        # Known field prefixes — used to detect where one field ends and the next begins
        _FIELD_PREFIXES = (
            "VERDICT:", "FAILURE_TYPE:", "FIXABLE:", "REASON:", "ISSUES:", "CORRECTED_DESCRIPTION:"
        )

        current_field = None
        field_lines: Dict[str, list] = {}

        for line in lines:
            stripped = line.strip()
            upper = stripped.upper()
            matched = next((p for p in _FIELD_PREFIXES if upper.startswith(p)), None)
            if matched:
                current_field = matched.rstrip(":")
                value_part = stripped[len(matched):].strip()
                field_lines.setdefault(current_field, [])
                if value_part:
                    field_lines[current_field].append(value_part)
            elif current_field and stripped:
                # Continuation line for the current field
                field_lines[current_field].append(stripped)

        def _get(key: str) -> str:
            return " ".join(field_lines.get(key, [])).strip()

        if "VERDICT" in field_lines:
            verdict = _get("VERDICT").upper()
        if "FAILURE_TYPE" in field_lines:
            failure_type = _get("FAILURE_TYPE").lower()
        if "FIXABLE" in field_lines:
            fixable = "YES" in _get("FIXABLE").upper()
        if "REASON" in field_lines:
            reason = _get("REASON")
        if "ISSUES" in field_lines:
            issues_str = _get("ISSUES")
            if issues_str.lower() != "none":
                issues = [i.strip() for i in issues_str.split(",") if i.strip()]
        if "CORRECTED_DESCRIPTION" in field_lines:
            desc = _get("CORRECTED_DESCRIPTION")
            if desc.lower() != "none":
                corrected_desc = desc

        passed = "PASS" in verdict
        if passed:
            failure_type = "none"

        logger.info(
            f"Gemini diagram review: {'PASSED' if passed else 'FAILED'} — {reason}"
        )
        if not passed:
            logger.info(f"  Fixable: {fixable}")
        if issues:
            logger.info(f"  Issues: {issues}")

        return {
            "passed": passed,
            "failure_type": failure_type,
            "reason": reason,
            "corrected_description": corrected_desc,
            "issues": issues,
            "fixable": fixable,
        }
