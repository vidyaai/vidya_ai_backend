"""
Diagram Analysis Agent

Multi-agent system for analyzing questions and generating diagrams using tool calls.
The agent decides which questions need diagrams and calls appropriate rendering tools.
"""

import json
import os
import re
import asyncio
from typing import Dict, List, Any, Optional
from openai import OpenAI
from controllers.config import logger
from utils.diagram_tools import DiagramTools, DIAGRAM_TOOLS
from utils.diagram_reviewer import DiagramReviewer


def _repair_truncated_json(s: str) -> dict:
    """
    Attempt to repair truncated / malformed JSON from OpenAI tool call arguments.

    Common issues:
    - Unterminated strings  (missing closing quote)
    - Missing closing braces / brackets
    """
    # 1. Try as-is first
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # 2. Try adding closing quote if an unterminated string
    repaired = s.rstrip()
    if repaired.count('"') % 2 != 0:
        repaired += '"'

    # 3. Balance braces / brackets
    open_braces = repaired.count('{') - repaired.count('}')
    open_brackets = repaired.count('[') - repaired.count(']')
    repaired += ']' * max(0, open_brackets)
    repaired += '}' * max(0, open_braces)

    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # 4. Last resort – try to extract a JSON object with regex
    match = re.search(r'\{[^{}]*\}', s)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError("Unable to repair JSON", s, 0)


class DiagramAnalysisAgent:
    """AI agent that analyzes questions and generates diagrams via tool calls"""

    def __init__(self, engine: str = "nonai", subject: str = "electrical", diagram_model: str = "flash"):
        """
        Initialize the diagram analysis agent.

        Args:
            engine: "ai" for Gemini native image gen + Gemini 2.5 Pro reviewer,
                    "nonai" for current flow (claude code + svg + schemdraw + matplotlib),
                    "both" for side-by-side comparison of ai and nonai outputs
            subject: Subject domain for diagram routing
            diagram_model: "flash" for gemini-2.5-flash-image (Vertex AI),
                           "pro"   for gemini-3-pro-image-preview (Google AI Studio)
        """
        self.client = OpenAI()
        self.model = "gpt-4o"
        self.diagram_tools = DiagramTools(diagram_model=diagram_model)
        self.engine = engine.lower().strip()
        self.subject = subject.lower().strip()
        self.diagram_model = diagram_model.lower().strip()

        # Select reviewer based on engine
        if self.engine in ("ai", "both"):
            from utils.gemini_diagram_reviewer import GeminiDiagramReviewer
            self.reviewer = GeminiDiagramReviewer()
            logger.info(f"DiagramAnalysisAgent: engine={self.engine}, diagram_model={self.diagram_model} → Gemini image gen + Gemini 2.5 Pro reviewer")
        else:
            self.reviewer = DiagramReviewer(client=self.client)
            logger.info("DiagramAnalysisAgent: engine=nonai → current flow + GPT-4o reviewer")

    def _get_agent_prompt(self, has_diagram_analysis: bool) -> str:
        """
        Get the system prompt for the diagram analysis agent.

        Args:
            has_diagram_analysis: Whether diagram-analysis question type is enabled

        Returns:
            System prompt string
        """
        # Always use intelligent mode that evaluates if diagrams add educational value
        # The has_diagram_analysis flag only affects the target percentage
        target_guidance = "Aim for ~33-40% total" if has_diagram_analysis else "Use good judgment - quality over quantity"
        mode_name = "GENEROUS (33%+ target)" if has_diagram_analysis else "INTELLIGENT (quality-focused)"

        return f"""You are a diagram analysis agent for educational assignments. Your role: add diagrams whenever they genuinely help students visualize and understand the problem.

OPERATING MODE: {mode_name}
- Generate diagrams when they ADD EDUCATIONAL VALUE
- Think like an experienced professor preparing teaching materials
- Diagrams should clarify complex concepts, show physical setups, or illustrate relationships
- Technical accuracy is paramount
- {target_guidance}

YOUR TASK:
1. Analyze each question carefully
2. Decide: Would a diagram significantly help the student understand or solve this problem?
3. If YES, generate the diagram:
   a) Choose the appropriate tool:
      - **svg_circuit_tool** (🏆 BEST FOR ALL CIRCUITS): Generates professional, textbook-quality vertical circuit diagrams via Claude SVG. Produces beautiful CMOS layouts with VDD on top, PMOS, output, NMOS, GND on bottom — like real textbook schematics. USE THIS FOR ALL electrical circuit diagrams (CMOS inverters, NAND/NOR gates, push-pull networks, amplifiers, any MOSFET/BJT circuit).
      - **claude_code_tool** (RECOMMENDED for non-circuit diagrams): Use Claude to generate matplotlib/networkx code for physics, CS, math, chemistry, biology, mechanical diagrams. Works for everything except circuits.
      - matplotlib_tool: Direct matplotlib code (ONLY if very simple plot)
      - schemdraw_tool: AVOID entirely — produces horizontal, unprofessional layouts
      - networkx_tool: Direct networkx code (ONLY if very simple graph)
      - dalle_tool: AVOID - use code-based tools for technical accuracy
   b) For svg_circuit_tool: Provide a description of the CIRCUIT STRUCTURE only — gate types, connections, topology.
      ⚠️ CRITICAL: NEVER include answer information in the description! This is a student assignment.
      - Do NOT include output values ("output is 0") or boolean expressions ("F = A'B")
      - Do NOT include specific input values ("A=1, B=0") — just say "inputs A and B"
      - Describe ONLY: what gates, how they connect, what inputs/outputs are named
      - Example GOOD: "Two-input AND gate with inputs A and B, output Y"
      - Example BAD: "AND gate with A=1, B=0, output = 0"
   c) For claude_code_tool: Specify domain, diagram_type, and tool_type (matplotlib/networkx)
   d) For other tools: Generate ACCURATE, executable code with correct technical details
   e) Rephrase question naturally to reference "the diagram below" or "shown below"

   ⚠️  CRITICAL: For ANY circuit diagram, ALWAYS use svg_circuit_tool.
   It produces vertical, textbook-quality schematics. Never use schemdraw_tool or claude_code_tool for circuits.

WHEN TO ADD DIAGRAMS (Examples across disciplines):

✅ PHYSICS/MECHANICS questions with physical setups:
   - "Calculate pressure in a manometer with three fluids..." → Add U-tube manometer diagram showing two connected columns with fluid layers
   - "Find the force on a beam with distributed load..." → Add beam diagram with forces
   - "A fluid flows through a pipe with varying diameter..." → Add pipe diagram with dimensions

✅ ELECTRICAL questions with circuits or configurations:
   - "Calculate VDS for a MOSFET with RD=2kΩ..." → Add circuit diagram (use svg_circuit_tool)
   - "Find the gain of this amplifier configuration..." → Add amplifier circuit (use svg_circuit_tool)
   - "Determine operating point from I-V characteristics..." → Add I-V curve plot (use claude_code_tool with matplotlib)
   - "CMOS inverter / NAND / NOR gate..." → Add circuit diagram (use svg_circuit_tool)
   - "Push-pull network / complementary MOS..." → Add circuit diagram (use svg_circuit_tool)
   NOTE: ALWAYS use svg_circuit_tool for circuit schematics. It produces professional vertical layouts.
   Only use claude_code_tool with matplotlib for I-V curves, characteristic plots, or transfer functions.

✅ NUMERICAL/CALCULATION questions describing specific setups:
   - "A manometer uses water, mercury, and oil (SG=0.85)..." → Add labeled diagram
   - "Three resistors are connected in series-parallel..." → Add circuit topology
   - "Calculate flow rate through the nozzle shown..." → Add nozzle geometry

✅ SHORT-ANSWER questions benefiting from visualization:
   - "Explain how pressure varies in this manometer..." → Add manometer with pressure points
   - "Describe current flow in this configuration..." → Add circuit with current paths
   - "Analyze the binary tree's structure..." → Add tree diagram

✅ MULTI-PART questions with consistent physical setup:
   - If the setup is reused across subquestions → Add diagram for main question

❌ DO NOT ADD DIAGRAMS for:
- Pure conceptual/theoretical questions ("Explain the difference between...")
- Definition questions ("What is threshold voltage?")
- Derivations without specific configurations
- Questions that work better with symbolic/abstract reasoning
- Simple calculations without complex setups

PROFESSOR'S JUDGMENT CRITERIA:
Ask yourself: "If I were teaching this in class, would I draw this on the board?"
✅ YES → Student needs to visualize the physical setup, geometry, or configuration
✅ YES → Multiple components/fluids/elements with spatial relationships
✅ YES → Numerical values assigned to specific parts of a system
✅ NO → Pure theory, definitions, or abstract concepts
✅ NO → Simple calculations without geometric/spatial complexity

CRITICAL RULES:
1. NEVER mention "image taken from page X" or reference source pages
2. Generate diagrams with CORRECT values, labels, and units from the question
3. For fluid systems: Show fluid levels, densities (SG values), dimensions
4. For circuits: Use correct component values and connection topology
5. For plots: Accurate axis labels, scales, and curves
6. Rephrase naturally: "For the manometer shown below" NOT "image from page 20"
7. If the question ALREADY generated by the first LLM has diagram metadata (caption, page_number),
   treat this as a STRONG HINT that a diagram would be valuable

DIAGRAM SIZE REQUIREMENTS:
- Use SMALLER figure sizes to fit in assignments: figsize=(6, 4) or figsize=(5, 4)
- NEVER use default large sizes like (10, 8) or (8, 6)
- Keep diagrams compact and clear
- DPI: Use 100-150 for good quality without huge file sizes

DOMAIN-SPECIFIC GUIDELINES:

**Fluid Systems** (manometers, pipes, pressure systems):
- For U-tube manometers: Draw TWO connected vertical tubes
- Show fluid layers with different colors and densities
- Label heights, pressures, measurement points clearly
- Use matplotlib.patches.Rectangle for tubes and fluid layers

**Electrical Circuits** (use svg_circuit_tool — ALWAYS):
- svg_circuit_tool generates professional textbook-quality circuit diagrams
- Produces VERTICAL layouts: VDD on top → PMOS → output → NMOS → GND on bottom
- PMOS gate bubbles, clean orthogonal wiring, proper labels
- Include all component values (R1=2kΩ, VDD=12V, CL=2fF) in description
- Include topology info (series/parallel, connections) in description
- ⚠️ NEVER use schemdraw_tool or claude_code_tool for circuit schematics — use svg_circuit_tool

**Description quality rules (apply to ALL domains — electrical, mechanical, physics, chemistry, math, civil):**
Your description MUST be derived DIRECTLY from the question text. Do NOT add components or details not in the question.
  1. Restate EXACTLY what the question mentions: every named component, value, and relationship
  2. Include ALL labeled values from the question (e.g., "gm1=1.5mS", "CL=10pF", "F=250N")
  3. For connections: state direction explicitly ("A connects to B via C", "X is in SERIES with Y")
  4. Name inputs and outputs as the question labels them (Vin+, Vin-, Vout, A, B, P1, etc.)
  5. State the diagram type: "circuit schematic", "free body diagram", "graph", "molecular structure"
  6. If the question only mentions certain components, include ONLY those — nothing extra
Example (electrical): Q says "two-stage op-amp, gm1=1.5mS, CL=10pF, Cc=2pF connecting output back to second-stage input" → description: "Two-stage op-amp schematic. Label gm1=1.5mS on first stage, CL=10pF load capacitor at output Vout, Miller capacitor Cc=2pF from Vout back to second-stage input. Differential inputs Vin+ and Vin-. VDD top, GND bottom."
Example (mechanical): Q says "simply-supported beam, 4m span, 500N midpoint load" → description: "Simply supported beam, length 4m, pin at left end, roller at right end. Point load 500N downward at midpoint. Label span 4m and load 500N."

**Data Structures** (use networkx):
- Trees: Use hierarchical layout with clear parent-child relationships
- Graphs: Label nodes and edges, show weights if applicable
- Use different colors for different node/edge types
- Add legends for node/edge meanings

**2D Geometry/Physics**:
- Use matplotlib with patches for shapes (Rectangle, Circle, Polygon)
- Show dimensions, angles, forces with arrows
- Label all key points and values
- Use coordinate system when needed

**Plots/Graphs**:
- Clear axis labels with units
- Legend for multiple series
- Grid for readability (if helpful)
- Title describing what's plotted

**Flowcharts/Algorithms** (if graphviz available):
- Use boxes for processes, diamonds for decisions
- Clear flow direction with arrows
- Label all steps and conditions

CODE GENERATION BEST PRACTICES:
1. Always import required libraries at top
2. Set figure size early: plt.subplots(figsize=(6, 4))
3. Use meaningful variable names
4. Add comments for complex sections
5. Use tight_layout() before saving
6. Save with: plt.savefig('output.png', dpi=100, bbox_inches='tight')

Example structure template:
```python
import matplotlib.pyplot as plt
import matplotlib.patches as patches  # If needed
import numpy as np  # If needed

fig, ax = plt.subplots(figsize=(6, 4))

# Set up axes
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.set_aspect('equal')  # If needed

# Draw diagram elements
# (rectangles, circles, lines, arrows, text)

# Add labels, title, legend
ax.set_xlabel('X axis')
ax.set_ylabel('Y axis')
ax.set_title('Diagram Title')
ax.legend()

plt.tight_layout()
plt.savefig('output.png', dpi=100, bbox_inches='tight')
```

REPHRASING EXAMPLES:
Original: "Calculate pressure in a manometer with three fluids..."
Better: "For the manometer shown below with three fluids (water, mercury, oil), calculate the pressure..."

Original: "A MOSFET circuit has RD=2kΩ, VDD=12V..."
Better: "For the MOSFET circuit shown below, calculate the drain current..."

Original: "Explain the difference between U-tube and well-type manometers"
Keep as-is: (conceptual comparison - no specific setup to diagram)"""

    async def _analyze_single_question(
        self,
        question: Dict[str, Any],
        assignment_id: str,
        question_idx: int,
        has_diagram_analysis: bool,
    ) -> Dict[str, Any]:
        """
        Analyze a single question and generate diagram if needed.

        Args:
            question: Question dict
            assignment_id: Assignment ID for S3 upload
            question_idx: Question index
            has_diagram_analysis: Whether diagram-analysis is enabled

        Returns:
            Modified question dict with diagram data (if generated)
        """
        try:
            # Prepare question text for analysis
            question_text = question.get("question") or question.get("text", "")
            question_type = question.get("type", "")
            existing_diagram_hint = question.get("diagram")  # Check if original LLM suggested a diagram

            logger.info(
                f"Analyzing question {question_idx}: {question_text[:100]}..."
            )

            # Check if the original question generation LLM suggested a diagram
            llm_diagram_hint = ""
            if existing_diagram_hint:
                caption = existing_diagram_hint.get("caption", "")
                page_num = existing_diagram_hint.get("page_number", "")
                llm_diagram_hint = f"""

IMPORTANT: The original question generator suggested this question would benefit from a diagram:
- Suggested caption: "{caption}"
- Page reference: {page_num}

This is a STRONG HINT that a diagram would add educational value. Consider generating one unless it's clearly unnecessary."""

            # Create analysis prompt
            mode_description = "GENEROUS mode (aim for 33%+ diagrams)" if has_diagram_analysis else "INTELLIGENT mode (generate when helpful)"

            analysis_prompt = f"""Analyze this question and decide if a diagram would help students visualize and understand the problem:

Question Type: {question_type}
Question Text: {question_text}{llm_diagram_hint}

If a diagram would genuinely enhance understanding and help students visualize the setup/problem:
1. Choose the appropriate tool (matplotlib_tool, schemdraw_tool, networkx_tool)
2. Generate complete, executable code with accurate values from the question
3. Call the tool to generate the diagram

If no diagram is needed (pure theory, definitions, abstract concepts):
- Respond with "No diagram needed" and briefly explain why

Mode: {mode_description}
"""

            # Call agent with tool access
            messages = [
                {"role": "system", "content": self._get_agent_prompt(has_diagram_analysis)},
                {"role": "user", "content": analysis_prompt},
            ]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=DIAGRAM_TOOLS,
                tool_choice="auto",  # Agent decides whether to call a tool
                temperature=0.3,  # Lower temperature for more consistent decisions
            )

            message = response.choices[0].message

            # Check if agent called a tool
            if message.tool_calls:
                tool_call = message.tool_calls[0]  # Get first tool call
                tool_name = tool_call.function.name

                # --- Robust JSON parsing with repair for truncated arguments ---
                try:
                    tool_arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as json_err:
                    logger.warning(
                        f"JSON parse error for question {question_idx} tool args, attempting repair: {json_err}"
                    )
                    try:
                        tool_arguments = _repair_truncated_json(tool_call.function.arguments)
                        logger.info(f"JSON repair succeeded for question {question_idx}")
                    except json.JSONDecodeError:
                        logger.error(
                            f"JSON repair failed for question {question_idx}. Raw args: {tool_call.function.arguments[:200]}"
                        )
                        # Fallback: if the agent wanted a diagram, try claude_code_tool with description from question
                        logger.info(f"Falling back to claude_code_tool for question {question_idx} after JSON error")
                        tool_name = "claude_code_tool"
                        tool_arguments = {
                            "domain": "general",
                            "diagram_type": "diagram",
                            "tool_type": "matplotlib",
                            "description": question_text[:300],
                        }

                logger.info(
                    f"Agent decided to use {tool_name} for question {question_idx}"
                )

                imagen_accepted = False  # Track whether Imagen retry loop accepted a diagram

                # ── ENGINE=AI or BOTH: Route to Gemini native image gen with retry loop ──
                if self.engine in ("ai", "both"):
                    # Extract description from whatever tool the agent picked
                    imagen_description = tool_arguments.get(
                        "description", tool_arguments.get("prompt", question_text[:300])
                    )
                    # Strip <eq qN_eqM> placeholders — they confuse Gemini image gen
                    imagen_description = re.sub(r'<eq\s+\S+>', '', imagen_description).strip()
                    logger.info(
                        f"Engine=ai: Routing Q{question_idx} to imagen_tool "
                        f"(agent originally picked {tool_name})"
                    )

                    max_imagen_attempts = 3
                    imagen_accepted = False
                    last_image_bytes = None  # Track bytes for fix-vs-regen
                    _ai_image_bytes_for_stitch = None  # Only used when engine=both
                    dimension_failures = 0  # Track dimension/label related failures

                    # Determine local save directory for AI-generated images
                    # Saves to the current working directory under assignment_id subfolder
                    _ai_save_dir = os.path.join(os.getcwd(), f"ai_diagrams_{assignment_id}")
                    os.makedirs(_ai_save_dir, exist_ok=True)

                    for attempt in range(1, max_imagen_attempts + 1):
                        logger.info(
                            f"Gemini image gen attempt {attempt}/{max_imagen_attempts} for Q{question_idx}"
                        )

                        # On 3rd attempt, if previous failures were dimension/label related,
                        # switch to symbolic variable names instead of numeric dimensions
                        current_description = imagen_description
                        if attempt == max_imagen_attempts and dimension_failures >= 2:
                            current_description += (
                                "\n\nIMPORTANT - USE SYMBOLIC LABELS INSTEAD OF NUMERIC DIMENSIONS:\n"
                                "Do NOT write specific numeric dimension values on the diagram.\n"
                                "Instead, use symbolic variable names for ALL dimensions, e.g.:\n"
                                "  - W_chip or W_silicon (for chip width)\n"
                                "  - L_chip or L_silicon (for chip length)\n"
                                "  - t_chip or t_silicon (for chip thickness)\n"
                                "  - t_sub or t_aluminum (for substrate thickness)\n"
                                "  - h_air (for convection coefficient)\n"
                                "  - T_air (for air temperature)\n"
                                "  - k_si, k_al (for thermal conductivities)\n"
                                "This avoids dimension labeling errors. Use clean variable names only."
                            )
                            logger.info(
                                f"Attempt {attempt}: switching to symbolic variable names "
                                f"after {dimension_failures} dimension-related failures"
                            )

                        if attempt == 1 or last_image_bytes is None:
                            # First attempt or no fixable image -- generate from scratch
                            diagram_data = await self.diagram_tools.execute_tool_call(
                                tool_name="imagen_tool",
                                tool_arguments={
                                    "description": current_description,
                                    "subject": self.subject,
                                },
                                assignment_id=assignment_id,
                                question_idx=question_idx,
                                question_text=question_text,
                            )
                        else:
                            # We have a fixable image -- send it back for correction
                            logger.info(
                                f"Fixing existing diagram (attempt {attempt}) -- "
                                f"issues: {last_review_issues[:120]}"
                            )
                            diagram_data = await self.diagram_tools.imagen_fix_tool(
                                image_bytes=last_image_bytes,
                                issues=last_review_result.get("issues", []),
                                reason=last_review_result.get("reason", ""),
                                original_description=current_description,
                                assignment_id=assignment_id,
                                question_idx=question_idx,
                                question_text=question_text,
                            )

                        if diagram_data is None:
                            logger.warning(
                                f"Gemini image gen failed on attempt {attempt} for Q{question_idx}"
                            )
                            last_image_bytes = None  # Reset so next attempt regenerates from scratch
                            last_review_result = None
                            continue

                        # Save AI-generated image locally for inspection
                        _attempt_bytes = diagram_data.get("_image_bytes")
                        if _attempt_bytes:
                            _local_name = f"Q{question_idx}_attempt{attempt}.png"
                            _local_path = os.path.join(_ai_save_dir, _local_name)
                            try:
                                with open(_local_path, "wb") as _f:
                                    _f.write(_attempt_bytes)
                                logger.info(f"Saved AI diagram locally: {_local_path} ({len(_attempt_bytes)} bytes)")
                            except Exception as _save_err:
                                logger.warning(f"Could not save AI diagram locally: {_save_err}")

                        # Review the generated image immediately
                        image_bytes_for_review = _attempt_bytes
                        if image_bytes_for_review is None:
                            try:
                                import requests as _req
                                resp = _req.get(diagram_data["s3_url"], timeout=15)
                                if resp.status_code == 200:
                                    image_bytes_for_review = resp.content
                            except Exception as dl_err:
                                logger.warning(f"Could not download Gemini diagram for review: {dl_err}")

                        if image_bytes_for_review:
                            # Use current_description (may be updated corrected description),
                            # not the stale original tool_arguments description.
                            description_for_review = current_description
                            # Strip <eq qN_eqM> placeholder tags from question_text before
                            # passing to reviewer — they cause false label-mismatch failures
                            # because the reviewer sees "<eq" as a label name.
                            clean_question_for_review = re.sub(
                                r'<eq\s+\S+>', '', question_text
                            ).strip()
                            review_result = await self.reviewer.review_diagram(
                                image_bytes=image_bytes_for_review,
                                question_text=clean_question_for_review,
                                diagram_description=description_for_review,
                                user_prompt_context=getattr(self, "_generation_prompt", ""),
                            )

                            if review_result["passed"]:
                                logger.info(
                                    f"Gemini diagram PASSED review on attempt {attempt} for Q{question_idx}: "
                                    f"{review_result['reason'][:100]}"
                                )
                                # For engine=both, keep the AI image bytes for stitching later
                                if self.engine == "both":
                                    _ai_image_bytes_for_stitch = image_bytes_for_review
                                # Remove _image_bytes before attaching to question
                                diagram_data.pop("_image_bytes", None)
                                imagen_accepted = True
                                break
                            else:
                                is_fixable = review_result.get("fixable", False)
                                last_review_issues = ", ".join(review_result.get("issues", []))
                                last_review_result = review_result

                                # Check if failure is dimension/label related
                                _reason_lower = review_result.get("reason", "").lower()
                                _issues_lower = last_review_issues.lower()
                                _dim_keywords = ["dimension", "label", "unit", "thickness", "width",
                                                 "conflicting", "duplicate", "wrong axis", "mm", "cm"]
                                if any(kw in _reason_lower or kw in _issues_lower for kw in _dim_keywords):
                                    dimension_failures += 1
                                    logger.info(f"Dimension-related failure #{dimension_failures} for Q{question_idx}")

                                logger.warning(
                                    f"Gemini diagram FAILED review on attempt {attempt}/{max_imagen_attempts} "
                                    f"for Q{question_idx} (fixable={is_fixable}): "
                                    f"{review_result['reason'][:120]}"
                                )

                                if is_fixable:
                                    # Structure is good, just text/label issues
                                    # Keep the image bytes so next iteration uses fix_diagram
                                    last_image_bytes = image_bytes_for_review
                                    logger.info(
                                        f"Diagram is fixable -- will send back for text correction "
                                        f"on next attempt"
                                    )
                                else:
                                    # Structural issue -- regenerate from scratch
                                    last_image_bytes = None
                                    corrected = review_result.get("corrected_description")
                                    if corrected:
                                        imagen_description = corrected
                                        logger.info(
                                            f"Structural issue -- regenerating from scratch with "
                                            f"corrected description: {corrected[:120]}..."
                                        )
                                diagram_data = None  # Reset so we retry
                        else:
                            # Can't review -- accept it and move on
                            logger.warning(f"No image bytes for review on attempt {attempt}, accepting as-is")
                            if self.engine == "both":
                                _ai_image_bytes_for_stitch = diagram_data.get("_image_bytes")
                            diagram_data.pop("_image_bytes", None)
                            imagen_accepted = True
                            break

                    if not imagen_accepted:
                        logger.warning(
                            f"Gemini image gen failed all {max_imagen_attempts} attempts for Q{question_idx}, "
                            f"falling back to nonai flow (claude_code_tool/schemdraw/matplotlib)"
                        )
                        diagram_data = None  # Force nonai fallback

                # ── ENGINE=NONAI / BOTH (or Gemini fallback): Use the original code-based flow ──
                # For engine=both we always run nonai even when AI succeeded.
                # For engine=ai we only run nonai as a fallback when Gemini failed.
                # For engine=both: save the AI result before running nonai
                _ai_diagram_data = diagram_data if self.engine == "both" and imagen_accepted else None

                # Run nonai when: engine=nonai, engine=both (always), or engine=ai as fallback
                if self.engine != "ai" or diagram_data is None:
                    diagram_data = await self.diagram_tools.execute_tool_call(
                        tool_name=tool_name,
                        tool_arguments=tool_arguments,
                        assignment_id=assignment_id,
                        question_idx=question_idx,
                        question_text=question_text,
                    )

                # --- Retry with svg_circuit_tool (for electrical) or claude_code_tool (for others) ---
                if diagram_data is None and tool_name not in ("svg_circuit_tool", "claude_code_tool"):
                    domain = self._infer_domain(question_text)

                    if domain == "electrical":
                        # For circuits, try svg_circuit_tool first (produces better results)
                        logger.warning(
                            f"Primary tool '{tool_name}' failed for question {question_idx}. "
                            f"Retrying with svg_circuit_tool..."
                        )
                        fallback_args = {
                            "description": tool_arguments.get("description", question_text[:300]),
                        }
                        diagram_data = await self.diagram_tools.execute_tool_call(
                            tool_name="svg_circuit_tool",
                            tool_arguments=fallback_args,
                            assignment_id=assignment_id,
                            question_idx=question_idx,
                            question_text=question_text,
                        )
                        if diagram_data:
                            logger.info(f"svg_circuit_tool fallback succeeded for question {question_idx}")
                    else:
                        logger.warning(
                            f"Primary tool '{tool_name}' failed for question {question_idx}. "
                            f"Retrying with claude_code_tool..."
                        )
                        claude_tool_type = "matplotlib"
                        if tool_name == "networkx_tool":
                            claude_tool_type = "networkx"

                        fallback_args = {
                            "domain": domain,
                            "diagram_type": tool_arguments.get("description", "diagram")[:100],
                            "tool_type": claude_tool_type,
                            "description": tool_arguments.get("description", question_text[:300]),
                        }
                        diagram_data = await self.diagram_tools.execute_tool_call(
                            tool_name="claude_code_tool",
                            tool_arguments=fallback_args,
                            assignment_id=assignment_id,
                            question_idx=question_idx,
                            question_text=question_text,
                        )
                        if diagram_data:
                            logger.info(f"claude_code_tool fallback succeeded for question {question_idx}")

                # If svg_circuit_tool failed, retry svg_circuit_tool with enriched description
                if diagram_data is None and tool_name == "svg_circuit_tool":
                    logger.warning(
                        f"svg_circuit_tool failed for question {question_idx}. "
                        f"Retrying svg_circuit_tool with enriched description..."
                    )
                    # Provide a more explicit description to help Claude
                    enriched_desc = (
                        f"Draw a professional SVG circuit diagram for: {question_text[:200]}. "
                        f"Original description: {tool_arguments.get('description', '')}. "
                        f"Use standard IEEE logic gate symbols (AND, OR, NOT shapes) for digital logic gates. "
                        f"Use CMOS transistor symbols only for transistor-level circuits. "
                        f"Keep the diagram simple and clean."
                    )
                    fallback_args = {
                        "description": enriched_desc,
                    }
                    diagram_data = await self.diagram_tools.execute_tool_call(
                        tool_name="svg_circuit_tool",
                        tool_arguments=fallback_args,
                        assignment_id=assignment_id,
                        question_idx=question_idx,
                        question_text=question_text,
                    )
                    if diagram_data:
                        logger.info(f"svg_circuit_tool retry succeeded for question {question_idx}")
                    else:
                        logger.error(f"All fallbacks failed for question {question_idx}")

                # --- Final fallback: GPT-4o direct code generation if Claude is unavailable ---
                if diagram_data is None:
                    domain = self._infer_domain(question_text)
                    if domain == "electrical":
                        # For electrical, give svg_circuit_tool one more try with explicit instructions
                        logger.warning(
                            f"All primary tools failed for question {question_idx}. "
                            f"Final retry with svg_circuit_tool (explicit instructions)..."
                        )
                        final_desc = (
                            f"SIMPLE circuit diagram for: {question_text[:200]}. "
                            f"Use standard IEEE block-level logic gate symbols for digital gates. "
                            f"Keep it minimal and clean."
                        )
                        diagram_data = await self.diagram_tools.execute_tool_call(
                            tool_name="svg_circuit_tool",
                            tool_arguments={"description": final_desc},
                            assignment_id=assignment_id,
                            question_idx=question_idx,
                            question_text=question_text,
                        )
                        if not diagram_data:
                            logger.warning(f"Final svg_circuit_tool retry failed. Trying GPT-4o fallback...")
                            diagram_data = await self._gpt_direct_code_fallback(
                                question_text=question_text,
                                description=tool_arguments.get("description", question_text[:300]),
                                assignment_id=assignment_id,
                                question_idx=question_idx,
                            )
                    else:
                        logger.warning(
                            f"All primary tools failed for question {question_idx}. "
                            f"Trying GPT-4o direct code generation fallback..."
                        )
                        diagram_data = await self._gpt_direct_code_fallback(
                            question_text=question_text,
                            description=tool_arguments.get("description", question_text[:300]),
                            assignment_id=assignment_id,
                            question_idx=question_idx,
                        )

                # ── ENGINE=BOTH: Stitch AI + Claude images side by side ────────
                if self.engine == "both" and _ai_diagram_data and diagram_data:
                    try:
                        # Get AI bytes
                        ai_bytes = _ai_image_bytes_for_stitch
                        if ai_bytes is None:
                            import requests as _req
                            resp = _req.get(_ai_diagram_data["s3_url"], timeout=15)
                            ai_bytes = resp.content if resp.status_code == 200 else None

                        # Get nonai bytes
                        nonai_bytes = diagram_data.pop("_image_bytes", None)
                        if nonai_bytes is None:
                            import requests as _req
                            resp = _req.get(diagram_data["s3_url"], timeout=15)
                            nonai_bytes = resp.content if resp.status_code == 200 else None

                        if ai_bytes and nonai_bytes:
                            logger.info(f"Stitching AI + Claude diagrams for Q{question_idx}")
                            stitched_bytes = self._stitch_side_by_side(ai_bytes, nonai_bytes)
                            # Upload stitched image to S3
                            stitched_data = await self.diagram_tools.diagram_gen.upload_to_s3(
                                image_bytes=stitched_bytes,
                                assignment_id=assignment_id,
                                question_index=question_idx,
                            )
                            stitched_data.pop("_image_bytes", None)
                            diagram_data = stitched_data
                            logger.info(f"Stitched comparison diagram uploaded for Q{question_idx}")
                        else:
                            logger.warning(f"Could not get both image bytes for stitching Q{question_idx}, using nonai only")
                    except Exception as _stitch_err:
                        logger.error(f"Stitch failed for Q{question_idx}: {_stitch_err} — using nonai diagram")

                if diagram_data:
                    # ── Diagram Review Step ──────────────────────────────
                    # Skip review if engine=ai/both already reviewed in the Imagen retry loop
                    if self.engine in ("ai", "both") and imagen_accepted:
                        logger.info(
                            f"Skipping duplicate review for Q{question_idx} — "
                            f"already reviewed in Imagen retry loop"
                        )
                    else:
                        image_bytes_for_review = diagram_data.pop("_image_bytes", None)

                        if image_bytes_for_review is None:
                            # Fallback: download from S3 presigned URL
                            try:
                                import requests as _req
                                resp = _req.get(diagram_data["s3_url"], timeout=15)
                                if resp.status_code == 200:
                                    image_bytes_for_review = resp.content
                            except Exception as dl_err:
                                logger.warning(f"Could not download diagram for review: {dl_err}")

                        if image_bytes_for_review:
                            description_for_review = tool_arguments.get("description", question_text[:300])
                            # Strip <eq> placeholders to prevent false label-mismatch failures
                            clean_question_for_review = re.sub(
                                r'<eq\s+\S+>', '', question_text
                            ).strip()
                            review_result = await self.reviewer.review_diagram(
                                image_bytes=image_bytes_for_review,
                                question_text=clean_question_for_review,
                                diagram_description=description_for_review,
                                user_prompt_context=getattr(self, "_generation_prompt", ""),
                            )

                            if not review_result["passed"]:
                                logger.warning(
                                    f"Diagram review FAILED for Q{question_idx}: {review_result['reason']}  "
                                    f"Issues: {review_result['issues']}"
                                )
                                corrected_desc = review_result.get("corrected_description")
                                if corrected_desc:
                                    logger.info(
                                        f"Regenerating Q{question_idx} with corrected description: "
                                        f"{corrected_desc[:120]}..."
                                    )
                                    regen_data = await self.diagram_tools.execute_tool_call(
                                        tool_name="svg_circuit_tool",
                                        tool_arguments={"description": corrected_desc},
                                        assignment_id=assignment_id,
                                        question_idx=question_idx,
                                        question_text=question_text,
                                    )
                                    if regen_data:
                                        # Pop transient key before attaching
                                        regen_data.pop("_image_bytes", None)
                                        diagram_data = regen_data
                                        logger.info(f"Regenerated diagram accepted for Q{question_idx}")
                                    else:
                                        logger.warning(
                                            f"Regeneration failed for Q{question_idx}; keeping original diagram"
                                        )
                            else:
                                logger.info(
                                    f"Diagram review PASSED for Q{question_idx}: {review_result['reason']}"
                                )
                        else:
                            logger.warning(
                                f"No image bytes available for review of Q{question_idx}; skipping review"
                            )
                    # ── End review step ───────────────────────────────────

                    # Tool succeeded, now ask agent to rephrase question
                    logger.info(
                        f"Diagram generated successfully, asking agent to rephrase question {question_idx}"
                    )

                    rephrase_prompt = f"""The diagram has been generated successfully.

Original question: {question_text}

Rephrase the question to reference "the diagram below" or "the circuit shown below". Respond with ONLY the rephrased question text.

CRITICAL RULES:
1. NEVER mention page numbers, sources, or "taken from" references
2. Use only "the diagram below", "the circuit shown below", "the plot below", etc.
3. Keep rephrasing natural and concise
4. Remove any existing page references from the original question
5. PRESERVE ALL numerical values, dimensions, given data, material properties, and units from the original question — do NOT omit them
   The question text must contain every number, dimension, and value that a student needs to solve the problem.
   The diagram is a visual aid, NOT a replacement for the given data.
   For example, if the original says "10 mm x 10 mm x 1 mm" and "thermal conductivity of 149 W/m·K",
   the rephrased question MUST still include those exact values.

Examples:
- "What is a binary tree?" → "Analyze the binary tree shown in the diagram below."
- "Calculate VDS for the circuit on page 20 with R=10kΩ" → "For the MOSFET circuit shown below with R = 10 kΩ, calculate VDS."
- "A silicon chip (10 mm x 10 mm x 1 mm) with k=149 W/m·K, refer to Figure 3.5" → "Consider the silicon chip (10 mm x 10 mm x 1 mm, k = 149 W/m·K) shown in the diagram below..."
"""

                    rephrase_response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": "You are a helpful assistant that rephrases questions to reference diagrams naturally."},
                            {"role": "user", "content": rephrase_prompt},
                        ],
                        temperature=0.3,
                    )

                    rephrased_text = rephrase_response.choices[0].message.content.strip()

                    # Update question
                    if rephrased_text != "KEEP_ORIGINAL":
                        question["question"] = rephrased_text
                        question["text"] = rephrased_text
                        logger.info(f"Question {question_idx} rephrased to: {rephrased_text[:100]}...")

                    # Attach diagram data
                    question["diagram"] = {
                        "s3_url": diagram_data.get("s3_url"),
                        "s3_key": diagram_data.get("s3_key"),
                        "file_id": diagram_data.get("file_id"),
                        "filename": diagram_data.get("filename"),
                    }
                    question["hasDiagram"] = True

                    logger.info(
                        f"Successfully added diagram to question {question_idx}"
                    )
                else:
                    logger.warning(
                        f"All tool attempts failed for question {question_idx} - no diagram generated"
                    )

            else:
                # Agent decided no diagram needed
                logger.info(
                    f"Agent decided no diagram needed for question {question_idx}: {message.content[:100] if message.content else 'No reason provided'}"
                )

            return question

        except Exception as e:
            logger.error(
                f"Error analyzing question {question_idx}: {str(e)}"
            )
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return question  # Return unchanged on error

    def _stitch_side_by_side(
        self,
        ai_bytes: bytes,
        nonai_bytes: bytes,
        ai_label: str = "AI Generated",
        nonai_label: str = "Schematic Generated",
    ) -> bytes:
        """
        Combine two PNG images into a side-by-side comparison layout.
        Each diagram is placed in its own named box with a coloured header bar.

        Layout per box:
          ┌─────────────────────────┐
          │  ■ AI Generated         │  ← coloured header bar
          ├─────────────────────────┤
          │                         │
          │       <image>           │  ← white image area with padding
          │                         │
          └─────────────────────────┘
        """
        from PIL import Image, ImageDraw, ImageFont
        import io

        AI_COLOR    = (25,  100, 210)   # blue  — AI Generated header
        NONAI_COLOR = (20,  145,  65)   # green — Schematic Generated header
        HEADER_TEXT = (255, 255, 255)   # white text in header
        BOX_BORDER  = (200, 200, 200)   # light grey outer border
        BG          = (245, 246, 248)   # off-white canvas background

        HEADER_H  = 38    # header bar height
        IMG_PAD   = 16    # padding around image inside box
        BOX_GAP   = 28    # horizontal gap between the two boxes
        OUTER_PAD = 20    # canvas margin on all sides
        BORDER_W  = 2     # box border width

        # ── Load & normalise images ──────────────────────────────────────
        img_ai    = Image.open(io.BytesIO(ai_bytes)).convert("RGB")
        img_nonai = Image.open(io.BytesIO(nonai_bytes)).convert("RGB")

        # Scale both to the same width (use the larger width as target)
        target_w = max(img_ai.width, img_nonai.width)

        def scale_to_width(img, w):
            if img.width == w:
                return img
            ratio = w / img.width
            return img.resize((w, int(img.height * ratio)), Image.LANCZOS)

        img_ai    = scale_to_width(img_ai,    target_w)
        img_nonai = scale_to_width(img_nonai, target_w)

        # ── Compute box dimensions ───────────────────────────────────────
        box_inner_w = target_w + IMG_PAD * 2

        ai_box_h    = HEADER_H + IMG_PAD + img_ai.height    + IMG_PAD
        nonai_box_h = HEADER_H + IMG_PAD + img_nonai.height + IMG_PAD
        max_box_h   = max(ai_box_h, nonai_box_h)

        total_w = OUTER_PAD + box_inner_w + BORDER_W * 2 + BOX_GAP + box_inner_w + BORDER_W * 2 + OUTER_PAD
        total_h = OUTER_PAD + max_box_h + BORDER_W * 2 + OUTER_PAD

        canvas = Image.new("RGB", (total_w, total_h), BG)
        draw   = ImageDraw.Draw(canvas)

        # ── Font ─────────────────────────────────────────────────────────
        try:
            font_bold   = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 17)
            font_normal = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
        except Exception:
            font_bold   = ImageFont.load_default()
            font_normal = font_bold

        # ── Draw one box ─────────────────────────────────────────────────
        def draw_box(x0, y0, img, label, header_color):
            box_h = HEADER_H + IMG_PAD + img.height + IMG_PAD
            x1 = x0 + BORDER_W * 2 + box_inner_w
            y1 = y0 + BORDER_W * 2 + box_h

            # Outer border
            draw.rectangle([x0, y0, x1, y1], outline=BOX_BORDER, width=BORDER_W)

            # Header bar
            hx0 = x0 + BORDER_W
            hy0 = y0 + BORDER_W
            hx1 = x1 - BORDER_W
            hy1 = hy0 + HEADER_H
            draw.rectangle([hx0, hy0, hx1, hy1], fill=header_color)

            # ■ icon + label text centred vertically in header
            icon_x  = hx0 + 12
            icon_y  = hy0 + (HEADER_H - 14) // 2
            draw.rectangle([icon_x, icon_y, icon_x + 12, icon_y + 12], fill=HEADER_TEXT)
            text_x  = icon_x + 20
            text_y  = hy0 + (HEADER_H - 17) // 2
            draw.text((text_x, text_y), label, fill=HEADER_TEXT, font=font_bold)

            # Divider line between header and image area
            draw.line([hx0, hy1, hx1, hy1], fill=header_color, width=1)

            # Paste image centred horizontally inside the box
            img_x = x0 + BORDER_W + IMG_PAD
            img_y = hy1 + IMG_PAD
            canvas.paste(img, (img_x, img_y))

        # Left box — AI Generated
        left_x = OUTER_PAD
        left_y = OUTER_PAD
        draw_box(left_x, left_y, img_ai, ai_label, AI_COLOR)

        # Right box — Schematic Generated
        right_x = left_x + BORDER_W * 2 + box_inner_w + BOX_GAP
        right_y = OUTER_PAD
        draw_box(right_x, right_y, img_nonai, nonai_label, NONAI_COLOR)

        out = io.BytesIO()
        canvas.save(out, format="PNG")
        return out.getvalue()

    def _infer_domain(self, question_text: str) -> str:
        """Infer the domain from question text for diagram generation."""
        q_lower = question_text.lower()
        if any(kw in q_lower for kw in ["circuit", "cmos", "mosfet", "nmos", "pmos", "transistor",
                                         "amplifier", "resistor", "capacitor", "voltage", "current",
                                         "inverter", "nand", "nor", "logic gate", "vdd", "drain", "source"]):
            return "electrical"
        elif any(kw in q_lower for kw in ["force", "pressure", "velocity", "fluid", "manometer",
                                           "beam", "torque", "moment", "friction"]):
            return "physics"
        elif any(kw in q_lower for kw in ["tree", "graph", "node", "linked list", "binary",
                                           "stack", "queue", "hash", "algorithm"]):
            return "computer_science"
        elif any(kw in q_lower for kw in ["integral", "derivative", "matrix", "equation",
                                           "polynomial", "eigenvalue", "vector"]):
            return "mathematics"
        return "general"

    def _strip_code_fences(self, code: str) -> str:
        """Strip markdown code fences from generated code."""
        code = code.strip()
        if code.startswith("```python"):
            code = code[len("```python"):]
        elif code.startswith("```"):
            code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
        return code.strip()

    async def _gpt_direct_code_fallback(
        self,
        question_text: str,
        description: str,
        assignment_id: str,
        question_idx: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Final fallback: Ask GPT-4o to generate diagram code directly with
        strict element-name guidance, then execute it.
        This is used when claude_code_tool is unavailable (API key issues, etc.).
        Includes a retry loop that feeds errors back to GPT-4o for auto-repair.
        """
        MAX_ATTEMPTS = 3

        try:
            domain = self._infer_domain(question_text)

            # Determine the best library
            if domain == "electrical":
                lib = "schemdraw"
                lib_guidance = """SCHEMDRAW 0.19 API RULES (follow EXACTLY or code will crash):

IMPORTS (always start with these):
  import matplotlib; matplotlib.use('Agg')
  import schemdraw; import schemdraw.elements as elm
  from schemdraw.util import Point

.at() API:  element.at(xy, dx=0, dy=0)
  ❌ .at(pos, ofst=(1,0))  — 'ofst' does NOT exist, crashes with TypeError!
  ✅ .at(pos, dx=1.0)  — use dx/dy for offset
  ✅ .at(pmos.drain)   — position at anchor

Point arithmetic:
  ✅ Point(pmos.gate) + Point((-1.5, 0))  — ALWAYS wrap BOTH sides in Point()
  ❌ pmos.gate + (-1.5, 0)  — CRASHES: "unsupported operand type(s)"

VERTICAL LAYOUT (MANDATORY for all CMOS circuits):
  - Draw TOP-TO-BOTTOM: VDD → PMOS → output node → NMOS → GND
  - PMOS is ALWAYS on top (source to VDD), NMOS is ALWAYS on bottom (source to GND)
  - Use .down() for the main transistor chain, NEVER .right()
  - Gates connect LEFT horizontally, output goes RIGHT horizontally

ANTI-OVERLAP LAYOUT:
  - d.config(unit=3) for spacing
  - Chain transistors: .at(previous.drain).anchor('drain')
  - NEVER add two transistors without explicit .at() positioning

NFet/PFet anchors: source, drain, gate, center
  PFet .down(): source=top, drain=bottom, gate=left-middle
  NFet .down(): drain=top, source=bottom, gate=left-middle

Valid elements: Resistor, Capacitor, Inductor, Diode, NFet, PFet, NMos, PMos,
  BjtNpn, BjtPnp, Opamp, SourceV, SourceI, Ground, Vdd, Vss, Line, Dot, Label
  ❌ INVALID: Mosfet, MOSFET, PTrans, NTrans — do NOT exist!

Logic gates: import schemdraw.logic as logic → logic.Nand(), etc.
  ❌ elm.Nand() does NOT exist!

★ WORKING CMOS INVERTER — VERTICAL: VDD on top, GND on bottom:
```python
import matplotlib
matplotlib.use('Agg')
import schemdraw
import schemdraw.elements as elm
from schemdraw.util import Point

with schemdraw.Drawing(show=False) as d:
    d.config(fontsize=11, unit=3)
    # TOP-TO-BOTTOM: VDD → PMOS → output → NMOS → GND
    vdd = d.add(elm.Vdd().label('VDD = 5V'))              # 1. VDD at top
    pmos = d.add(elm.PFet().down().anchor('source').label('PMOS', loc='left'))  # 2. PMOS below VDD
    d.add(elm.Dot().at(pmos.drain))                        # 3. Output node (middle)
    nmos = d.add(elm.NFet().at(pmos.drain).down().anchor('drain').label('NMOS', loc='left'))  # 4. NMOS below
    d.add(elm.Ground())                                    # 5. GND at bottom
    # Gates go LEFT
    d.add(elm.Line().at(pmos.gate).left().length(1.5))
    vin_top = d.here
    d.add(elm.Line().at(nmos.gate).left().length(1.5))
    vin_bot = d.here
    d.add(elm.Line().at(vin_top).down().toy(vin_bot))
    d.add(elm.Label().at(vin_top).label('Vin', loc='left'))
    # Output goes RIGHT
    d.add(elm.Line().at(pmos.drain).right().length(1.5).label('Vout', loc='right'))
    d.save('output.png', dpi=100)
```

KEEP IT SIMPLE: 15–40 lines max. A correct simple diagram beats a broken complex one."""
            else:
                lib = "matplotlib"
                lib_guidance = """MATPLOTLIB RULES:
- import matplotlib; matplotlib.use('Agg')
- import matplotlib.pyplot as plt
- Use figsize=(6, 4)
- Save with: plt.savefig('output.png', dpi=100, bbox_inches='tight')

KEEP IT SIMPLE:
- Generate a SIMPLE, CLEAN diagram — 20–50 lines of code max
- Focus on clarity and correctness"""

            code_gen_prompt = f"""Generate COMPLETE, EXECUTABLE Python code to create a SIMPLE, CLEAN diagram for this question.

Question: {question_text}

Diagram description: {description}
Domain: {domain}
Library: {lib}

{lib_guidance}

CRITICAL: Keep the code SHORT and SIMPLE (under 60 lines). A simple, correct diagram is better than a complex, broken one.
Return ONLY Python code. No explanations. The code must be immediately executable and produce output.png."""

            logger.info(f"GPT-4o direct code fallback for question {question_idx} (domain={domain}, lib={lib})")

            messages = [
                {"role": "system", "content": "You are an expert code generator. Return ONLY executable Python code. No markdown, no explanations. Keep code SHORT and SIMPLE — under 60 lines. Simple correct diagrams beat complex broken ones."},
                {"role": "user", "content": code_gen_prompt},
            ]

            last_error = None
            for attempt in range(MAX_ATTEMPTS):
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.2 + (attempt * 0.1),  # Slightly increase creativity on retries
                    max_tokens=2000,  # Hard cap to prevent 40K+ char code blobs
                )

                code = self._strip_code_fences(response.choices[0].message.content)

                logger.info(f"GPT-4o generated {len(code)} chars of {lib} code for question {question_idx} (attempt {attempt + 1}/{MAX_ATTEMPTS})")

                # Guard: reject absurdly long code (likely garbage)
                if len(code) > 5000:
                    logger.warning(f"GPT-4o generated excessively long code ({len(code)} chars) for question {question_idx} — requesting simpler version")
                    messages.append({"role": "assistant", "content": code})
                    messages.append({"role": "user", "content": f"That code is {len(code)} characters — way too long and complex. Generate a MUCH SIMPLER version. A basic {lib} diagram should be 20-40 lines of code. Strip it down to essentials."})
                    continue

                # Try to render
                try:
                    if lib == "schemdraw":
                        image_bytes = await self.diagram_tools.diagram_gen.render_schemdraw(code)
                    else:
                        image_bytes = await self.diagram_tools.diagram_gen.render_matplotlib(code)

                    # Upload to S3
                    diagram_data = await self.diagram_tools.diagram_gen.upload_to_s3(
                        image_bytes, assignment_id, question_idx
                    )

                    logger.info(f"GPT-4o direct code fallback succeeded for question {question_idx} (attempt {attempt + 1})")
                    return diagram_data

                except Exception as render_err:
                    last_error = str(render_err)
                    logger.warning(f"GPT-4o code render failed (attempt {attempt + 1}/{MAX_ATTEMPTS}): {last_error[:200]}")

                    if attempt < MAX_ATTEMPTS - 1:
                        # Feed the error back so GPT-4o can fix it
                        messages.append({"role": "assistant", "content": code})
                        messages.append({"role": "user", "content": f"""The code above failed with this error:

{last_error[:500]}

Fix the code. Common schemdraw 0.19 issues:
- .at(pos, ofst=...) → ofst does NOT exist. Use .at(pos) or .at(pos, dx=1.0)
- anchor + (dx, dy) → CRASHES. Use Point(anchor) + Point((dx, dy))
- elm.Mosfet, elm.PTrans → do NOT exist. Use elm.NFet() / elm.PFet()
- elm.Nand() → does NOT exist. Use: import schemdraw.logic as logic; logic.Nand()
- Overlapping transistors → chain with .at(prev.drain).anchor('drain')
- Missing 'from schemdraw.util import Point' when using Point()

Return the COMPLETE fixed code. Keep it SIMPLE — under 40 lines."""})

            logger.error(f"GPT-4o direct code fallback failed after {MAX_ATTEMPTS} attempts for question {question_idx}: {last_error}")
            return None

        except Exception as e:
            logger.error(f"GPT-4o direct code fallback failed for question {question_idx}: {str(e)}")
            return None

    async def _process_questions_batch(
        self,
        questions: List[Dict[str, Any]],
        assignment_id: str,
        has_diagram_analysis: bool,
    ) -> List[Dict[str, Any]]:
        """
        Process multiple questions in parallel with concurrency limit.

        Args:
            questions: List of questions to analyze
            assignment_id: Assignment ID for S3 upload
            has_diagram_analysis: Whether diagram-analysis is enabled

        Returns:
            List of modified questions with diagrams
        """
        # Process questions in parallel with semaphore for concurrency control
        semaphore = asyncio.Semaphore(3)  # Max 3 concurrent analyses

        async def process_with_semaphore(q: Dict[str, Any], idx: int):
            async with semaphore:
                return await self._analyze_single_question(
                    q, assignment_id, idx, has_diagram_analysis
                )

        tasks = [
            process_with_semaphore(q, i) for i, q in enumerate(questions)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results

    def _ensure_minimum_percentage(
        self,
        questions: List[Dict[str, Any]],
        assignment_id: str,
        target_percentage: float = 0.33,
    ) -> List[Dict[str, Any]]:
        """
        Ensure at least target_percentage of questions have diagrams.

        Args:
            questions: List of questions
            assignment_id: Assignment ID
            target_percentage: Minimum percentage of questions with diagrams (default 33%)

        Returns:
            Questions with enough diagrams
        """
        total_questions = len(questions)
        questions_with_diagrams = sum(
            1 for q in questions if q.get("hasDiagram", False)
        )

        current_percentage = (
            questions_with_diagrams / total_questions if total_questions > 0 else 0
        )

        logger.info(
            f"Current diagram percentage: {current_percentage:.1%} ({questions_with_diagrams}/{total_questions})"
        )

        if current_percentage >= target_percentage:
            logger.info(
                f"Already met target of {target_percentage:.1%}, skipping enforcement"
            )
            return questions

        # Calculate how many more diagrams we need
        target_count = int(total_questions * target_percentage)
        needed_count = target_count - questions_with_diagrams

        logger.info(
            f"Need {needed_count} more diagrams to reach {target_percentage:.1%}"
        )

        # Find questions without diagrams that would benefit from them
        candidates = [
            (i, q)
            for i, q in enumerate(questions)
            if not q.get("hasDiagram", False)
        ]

        # TODO: In a future iteration, we could re-run agent analysis on candidates
        # in "force diagram" mode to reach the target percentage
        # For now, we log the shortfall
        logger.warning(
            f"Diagram percentage ({current_percentage:.1%}) is below target ({target_percentage:.1%}). Consider adjusting agent prompts or running additional analysis pass."
        )

        return questions

    def analyze_and_generate_diagrams(
        self,
        questions: List[Dict[str, Any]],
        assignment_id: str,
        has_diagram_analysis: bool,
        generation_prompt: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Main entry point: Analyze questions and generate diagrams via multi-agent system.

        Args:
            questions: List of generated questions (without diagrams)
            assignment_id: Assignment ID for S3 upload paths
            has_diagram_analysis: Whether "diagram-analysis" question type is enabled
            generation_prompt: The user's original prompt for the assignment

        Returns:
            Modified questions list with diagrams attached
        """
        try:
            logger.info(
                f"Starting multi-agent diagram analysis for {len(questions)} questions"
            )
            logger.info(
                f"Mode: {'GENEROUS (33%+ target)' if has_diagram_analysis else 'INTELLIGENT (quality-focused)'}"
            )
            logger.info(
                f"Engine: {self.engine} | Subject: {self.subject} | "
                f"Reviewer: {'Gemini 2.5 Pro' if self.engine == 'ai' else 'GPT-4o'}"
            )

            # Store generation_prompt for use by the reviewer
            self._generation_prompt = generation_prompt

            # Run async processing
            # Use asyncio.run() which properly manages the event loop
            try:
                questions = asyncio.run(
                    self._process_questions_batch(
                        questions, assignment_id, has_diagram_analysis
                    )
                )
            except RuntimeError as e:
                # If there's already a running loop, process synchronously in thread
                logger.warning(f"Event loop conflict, using thread-based processing: {e}")
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        asyncio.run,
                        self._process_questions_batch(
                            questions, assignment_id, has_diagram_analysis
                        )
                    )
                    questions = future.result()

            # Enforce minimum percentage if diagram-analysis is enabled
            if has_diagram_analysis:
                questions = self._ensure_minimum_percentage(
                    questions, assignment_id, target_percentage=0.33
                )

            # Log final statistics
            final_count = sum(
                1 for q in questions if q.get("hasDiagram", False)
            )
            final_percentage = final_count / len(questions) if questions else 0

            logger.info(
                f"Diagram analysis complete: {final_count}/{len(questions)} questions have diagrams ({final_percentage:.1%})"
            )

            return questions

        except Exception as e:
            logger.error(f"Error in diagram analysis: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return questions  # Return unchanged on error
