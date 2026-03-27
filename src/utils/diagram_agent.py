"""
Diagram Analysis Agent

Multi-agent system for analyzing questions and generating diagrams using tool calls.
The agent decides which questions need diagrams and calls appropriate rendering tools.
"""

import json
import os
import re
import asyncio
import shutil
import tempfile
from typing import Dict, List, Any, Optional
from openai import OpenAI
from controllers.config import logger
from utils.diagram_tools import DiagramTools, DIAGRAM_TOOLS
from utils.domain_router import DomainRouter
from utils.subject_prompt_registry import SubjectPromptRegistry
from utils.fallback_router import SubjectSpecificFallbackRouter
from pylatexenc.latex2text import LatexNodes2Text


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
    open_braces = repaired.count("{") - repaired.count("}")
    open_brackets = repaired.count("[") - repaired.count("]")
    repaired += "]" * max(0, open_brackets)
    repaired += "}" * max(0, open_braces)

    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # 4. Last resort – try to extract a JSON object with regex
    match = re.search(r"\{[^{}]*\}", s)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError("Unable to repair JSON", s, 0)


class DiagramAnalysisAgent:
    """AI agent that analyzes questions and generates diagrams via tool calls"""

    def __init__(
        self,
        engine: str = "nonai",
        subject: str = "electrical",
        diagram_model: str = "flash",
    ):
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

        # Subject-aware routing components
        self.domain_router = DomainRouter(client=self.client)
        self.prompt_registry = SubjectPromptRegistry()
        self.fallback_router = SubjectSpecificFallbackRouter()

        # Always use Gemini 2.5 Pro as the diagram reviewer (best vision
        # accuracy for semantic consistency checks across all subjects).
        from utils.gemini_diagram_reviewer import GeminiDiagramReviewer

        self.reviewer = GeminiDiagramReviewer()
        logger.info(
            f"DiagramAnalysisAgent: engine={self.engine}, diagram_model={self.diagram_model} "
            f"→ Gemini 2.5 Pro reviewer (unified for ai/nonai/fallback)"
        )

    def _get_agent_prompt(
        self,
        has_diagram_analysis: bool,
        domain: str = "",
        diagram_type: str = "",
    ) -> str:
        """
        Get the system prompt for the diagram analysis agent.

        Args:
            has_diagram_analysis: Whether diagram-analysis question type is enabled
            domain: Classified domain from DomainRouter (for subject-specific additions)
            diagram_type: Classified diagram type from DomainRouter

        Returns:
            System prompt string
        """
        target_guidance = (
            "Aim for ~33-40% total"
            if has_diagram_analysis
            else "Use good judgment - quality over quantity"
        )
        mode_name = (
            "GENEROUS (33%+ target)"
            if has_diagram_analysis
            else "INTELLIGENT (quality-focused)"
        )

        base_prompt = f"""You are a diagram analysis agent for educational assignments. Your role: add diagrams whenever they genuinely help students visualize and understand the problem.

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
      - **circuitikz_tool** ⭐ BEST FOR ALL CIRCUITS: Generates publication-quality circuit diagrams via CircuiTikZ (LaTeX). Output is identical to Sedra & Smith / Mano textbook diagrams. Use for: ALL electrical circuits, MOSFET/CMOS transistor circuits, analog circuits, digital logic gates, op-amp circuits, BJT circuits, RLC networks, D/JK/SR/T flip-flop circuits, shift registers, counters, sequential logic, encoders/decoders, MUX/DEMUX, register files, ALU/datapath, CDC. ALWAYS use this for any circuit schematic.
      - **claude_code_tool** (RECOMMENDED for non-circuit diagrams AND timing/waveform): Use Claude to generate matplotlib/networkx code for any technical domain — physics, CS, math, chemistry, biology, mechanical, civil. ALSO use this for timing diagrams and waveforms (with tool_type=matplotlib). Highly versatile.
      - matplotlib_tool: Direct matplotlib code (ONLY if very simple plot)
      - schemdraw_tool: AVOID entirely — produces unprofessional layouts
      - svg_circuit_tool: DEPRECATED — use circuitikz_tool instead
      - networkx_tool: Direct networkx code (ONLY if very simple graph)
      - dalle_tool: AVOID - use code-based tools for technical accuracy
   b) For svg_circuit_tool: Provide a description of the CIRCUIT STRUCTURE only.
      ⚠️ CRITICAL: NEVER include answer information in the description! This is a student assignment.
      - Do NOT include output values, boolean expressions, or specific input values
      - Describe ONLY: what components, how they connect, what nodes are named
   c) For claude_code_tool: Specify domain, diagram_type, and tool_type (matplotlib/networkx)
   d) For MEDICAL questions: use the most specific specialist tool — never circuitikz
      - neurokit2_tool      → action_potential (neuronal AP waveform), cardiac_loop (P-V loop)
      - scipy_curve_tool    → dose_response, pharmacokinetics, enzyme_kinetics,
                               pressure_volume_loop, growth_curve
      - networkx_pathway_tool → metabolic_pathway, feedback_loop, infection_cycle,
                                 disease_progression
      - imagen_tool          → anatomical_diagram, histology, bacterial_structure, histopathology
        (falls back to claude_code_tool with matplotlib if imagen unavailable)
   e) Rephrase question naturally to reference "the diagram below" or "shown below"

WHEN TO ADD DIAGRAMS:

✅ Questions with physical setups, spatial configurations, or geometric relationships
✅ Questions with multiple components that have labeled values and connections
✅ Data structure questions (trees, graphs) — students need to see the structure
✅ Questions where the setup is reused across multiple sub-questions
✅ Questions where the original LLM suggested a diagram (strong hint)
✅ Medical/physiology questions asking about specific curves or plots:
   - Action potential graph (axes, phases, threshold)
   - Pressure-volume loops (cardiac cycle)
   - Dose-response / pharmacokinetics curves
   - Metabolic pathway diagrams
✅ Anatomical/histological setup diagrams (organ relationships, tissue layers)

❌ DO NOT ADD for pure theory, definitions, or abstract conceptual questions
❌ DO NOT ADD for simple single-step calculations without spatial complexity
❌ DO NOT ADD for medical questions that only ask to explain or describe mechanisms without a visual component

PROFESSOR'S JUDGMENT:
Ask: "If I were drafting the question, would I include this diagram?"

CRITICAL RULES:
1. NEVER mention page numbers or source references
2. Generate diagrams with CORRECT values, labels, and units from the question BUT DONOT include the answer information (e.g., labels, computed reactions, deflections, waveforms) — that is for the student to fill in
3. Rephrase naturally: "For the beam shown below" NOT "image from page 20"
4. PRESERVE ALL numerical values and given data in the rephrased question

⚠️ ANSWER HIDING IN DIAGRAMS (CRITICAL — THIS IS A STUDENT ASSIGNMENT):
Diagrams must NEVER reveal the answer to the question. Students must work out the answer themselves.
This rule applies to ALL subjects and ALL diagram types.

**Timing / Waveform Diagrams (Electrical, Computer Eng):**
- Show ONLY the INPUT signals that are GIVEN in the question (CLK, D, A, B, RESET, EN, etc.)
- OUTPUT signals (Q, Q1, Q2, Q̄, Y, etc.) must be drawn as BLANK rows with "?" labels
  or left completely empty for the student to fill in
- For a D flip-flop circuit: show CLK and D waveforms, but leave Q and Q̄ blank
- For sequential circuits with multiple FFs: show input waveforms only, leave ALL output waveforms blank
- The purpose is for students to DRAW the output waveforms themselves

**Counter / State Machine Diagrams (Electrical, Computer Eng):**
- Show ONLY the circuit topology (flip-flops, gates, feedback connections)
- Show the initial state if given in the question
- Do NOT show state transition sequences, state tables, or output sequences
- For ring counters: show the shift register circuit with feedback, NOT the sequence of states
- For Johnson counters: show the twisted ring counter circuit, NOT the state table
- Students must determine the state transitions themselves

**Mechanical / Civil / Physics Diagrams:**
- Do NOT show computed reaction forces, deflections, or resultant forces if students must calculate them
- Do NOT draw shear force / bending moment diagrams if the question asks students to draw them
- For FBDs: show given forces and setup, NOT the net force or acceleration
- For ray diagrams: show setup (lens, object), NOT the image location if students must find it

**CS / Math / Chemistry Diagrams:**
- Do NOT show algorithm results (sorted array, shortest path, traversal order) if asked to trace/compute
- For BST/tree operations: show the tree BEFORE, NOT after the operation
- Do NOT shade/label areas, intersection points, or derivatives if students must compute them
- Do NOT show reaction products or mechanisms if students must predict/draw them

**Medical / Life Sciences Diagrams:**
- Action potential: Do NOT label a phase or mark a threshold value if students must identify it
- Metabolic pathway: Do NOT label an enzyme name if students must name it; use a numbered blank ("Enzyme ?")
- Pharmacokinetics: Do NOT show Cmax, t½, or AUC values if students must calculate them
- Dose-response: Do NOT mark EC50 if students must read it off or calculate it
- Histology / pathology: Do NOT write the disease diagnosis or tissue type label if students must identify it
  (use neutral numbered callouts instead)
- Anatomical diagrams: Leave blank callouts for structures students must identify
- Feedback loop: Show the loop structure, but omit the specific hormone/messenger names if those are the answer**
- If the question asks "what is the output?", "determine", "find", "calculate",
  "draw", "sketch", "describe", "predict", or "trace" — the diagram must NOT contain that answer
- Diagrams are visual aids showing the PROBLEM SETUP, not the SOLUTION

DIAGRAM SIZE REQUIREMENTS:
- Use compact sizes: figsize=(6, 4) or figsize=(5, 4)
- NEVER use large sizes like (10, 8) or (8, 6)
- DPI: 100-150

DESCRIPTION QUALITY RULES (all domains):
Your description MUST be derived DIRECTLY from the question text.
  1. Restate EXACTLY what the question mentions: every named component, value, relationship
  2. Include ALL labeled values from the question (e.g., "F=250N", "R1=2kΩ", "n=5 nodes")
  3. Name inputs and outputs as the question labels them
  4. State the diagram type clearly
  5. Include ONLY what the question mentions — nothing extra

CODE GENERATION BEST PRACTICES:
1. Set figure size early: plt.subplots(figsize=(6, 4))
2. Use tight_layout() before saving
3. Save with: plt.savefig('output.png', dpi=100, bbox_inches='tight')

REPHRASING EXAMPLES:
"A simply-supported beam 4m long with 500N load..." → "For the beam shown below (L=4m, P=500N), find the reactions."
"Insert 5,3,7,1 into a BST..." → "For the BST shown below, insert the values 5, 3, 7, 1."
"Explain the difference between..." → Keep as-is (no diagram needed)

MULTI-DIAGRAM QUESTIONS (CRITICAL — when a question needs more than one diagram):
When a question requires BOTH a schematic/structure AND a supplementary diagram (timing, graph, chart):
1. Make TWO tool calls in your response:
   - FIRST: The primary diagram (e.g. circuitikz_tool for circuit, matplotlib for structure)
   - SECOND: claude_code_tool with tool_type="matplotlib" for the supplementary diagram
2. The system will automatically combine both diagrams into one image (primary on top, supplementary below).
3. Examples that need two diagrams:
   - "D flip-flop circuit with timing diagrams for CLK, D, Q"
   - "Shift register with input waveforms"
   - "Sequential logic circuit — draw timing diagrams for 8 clock cycles"
   - "Beam with loading diagram and blank SFD/BMD axes"
   - Any question asking students to "draw/complete" diagrams based on a given structure
4. For the supplementary diagram:
   - Show ONLY the GIVEN information (inputs, loading, boundary conditions, etc.)
   - Any values the student must DETERMINE → draw as BLANK rows with "?" labels
   - NEVER draw actual answer values — that IS the answer
   - Title the figure descriptively based on what it shows (e.g. 'Input Signals',
     'Given Loading', 'Initial Conditions') — NOT based on the answer
   - For digital waveforms: use matplotlib ax.step() for rectangular/square-wave style
   - Include alignment aids (dashed grid lines, clock edges, reference lines)

QUESTION TYPE AUTO-CONVERSION:
When the question requires students to draw, determine, or analyze output waveforms, counter states,
or timing diagrams, the question type SHOULD be "diagram-analysis" (not "short-answer" or "numerical").
If you detect such a question, note this in your response so the system can update the type.

DIAGRAM-REQUIRED-IN-ANSWER QUESTIONS:
Questions with type "diagram-required-in-answer" require the student to draw/sketch/create a diagram as their answer.
These questions may also benefit from a QUESTION diagram (to show the problem setup), just like any other question type.
Treat them the same as any question when deciding whether to add a question-level diagram.
A separate system will generate the ANSWER KEY diagram — you only handle the question-level diagram.
"""

        # Append subject-specific prompt additions from registry
        if domain:
            subject_section = self.prompt_registry.get_agent_system_prompt(
                domain, diagram_type
            )
            if subject_section:
                base_prompt += f"\n{subject_section}"

        return base_prompt

    def _get_answer_key_agent_prompt(
        self,
        domain: str = "",
        diagram_type: str = "",
    ) -> str:
        """
        Get the system prompt for the ANSWER KEY diagram agent.

        This mirrors _get_agent_prompt() in structure (tool guidance, code practices,
        medical routing, multi-diagram support) but has the OPPOSITE answer rules:
        it instructs the agent to show COMPLETE solutions with ALL computed values.

        Args:
            domain: Classified domain from DomainRouter
            diagram_type: Classified diagram type from DomainRouter

        Returns:
            System prompt string for the answer-key diagram agent
        """
        base_prompt = """You are an ANSWER KEY diagram agent for educational assignments. Your role: generate instructor reference diagrams that show the COMPLETE, CORRECT solution.

PURPOSE: These diagrams are NEVER shown to students. They are instructor-only answer keys used for grading reference. You MUST always generate a diagram — never skip.

YOUR TASK:
1. Read the question and correct answer carefully
2. Choose the appropriate tool to generate the answer-key diagram
3. Generate a diagram that shows the FULL SOLUTION with ALL values, labels, and results

TOOL SELECTION:
   a) Choose the appropriate tool:
      - **circuitikz_tool** ⭐ BEST FOR ALL CIRCUITS: Generates publication-quality circuit diagrams via CircuiTikZ (LaTeX). Use for: ALL electrical circuits, MOSFET/CMOS transistor circuits, analog circuits, digital logic gates, op-amp circuits, BJT circuits, RLC networks, flip-flop circuits, shift registers, counters, sequential logic, encoders/decoders, MUX/DEMUX, register files, ALU/datapath.
      - **claude_code_tool** (RECOMMENDED for non-circuit diagrams AND timing/waveform): Use Claude to generate matplotlib/networkx code for any technical domain — physics, CS, math, chemistry, biology, mechanical, civil. ALSO use this for timing diagrams and waveforms (with tool_type=matplotlib). Highly versatile.
      - matplotlib_tool: Direct matplotlib code (ONLY if very simple plot)
      - networkx_tool: Direct networkx code (ONLY if very simple graph)
      - For MEDICAL questions: use the most specific specialist tool — never circuitikz
        - neurokit2_tool      → action_potential, cardiac_loop
        - scipy_curve_tool    → dose_response, pharmacokinetics, enzyme_kinetics,
                                 pressure_volume_loop, growth_curve
        - networkx_pathway_tool → metabolic_pathway, feedback_loop, infection_cycle,
                                   disease_progression
        - imagen_tool          → anatomical_diagram, histology, bacterial_structure
   b) For claude_code_tool: Specify domain, diagram_type, and tool_type (matplotlib/networkx)

MULTI-DIAGRAM ANSWER KEYS (CRITICAL — when an answer needs more than one diagram):
When an answer requires BOTH a schematic/structure AND a supplementary diagram:
1. Make TWO tool calls in your response:
   - FIRST: The primary diagram (e.g. circuitikz for circuit, matplotlib for structure)
   - SECOND: claude_code_tool with tool_type="matplotlib" for the supplementary diagram
2. The system will automatically combine both diagrams into one image.
3. Examples that need two diagrams:
   - Circuit schematic + complete timing diagram showing all output waveforms
   - Beam structure + completed SFD/BMD with all values
   - Sequential logic circuit + state transition diagram with all states filled in
4. For the supplementary diagram:
   - Show ALL computed values — this is the answer key
   - For digital waveforms: use matplotlib ax.step() for rectangular/square-wave style
   - Include alignment aids (dashed grid lines, clock edges, reference lines)

⚠️ ANSWER SHOWING RULES (CRITICAL — THIS IS AN INSTRUCTOR ANSWER KEY):
Diagrams MUST show the COMPLETE CORRECT SOLUTION. Show every computed value, output, result.

**Timing / Waveform Diagrams (Electrical, Computer Eng):**
- Show ALL signals — BOTH inputs AND outputs with correct logic levels
- Output waveforms (Q, Q1, Q2, Q̄, Y) must show the CORRECT computed values at every clock edge
- Include propagation delays, setup/hold timing, and correct logic transitions
- For D flip-flop circuits: show CLK, D, AND the correct Q, Q̄ waveforms
- For sequential circuits: show ALL input and output waveforms with correct timing

**Counter / State Machine Diagrams (Electrical, Computer Eng):**
- Show the COMPLETE state transition diagram with ALL states and transitions
- Include output values at each state
- For ring/Johnson counters: show the complete state sequence over all clock cycles
- Show state table with ALL states filled in

**Mechanical / Civil / Physics Diagrams:**
- Show ALL computed reaction forces with magnitudes and directions
- Draw complete SFD/BMD with correct values at all key points
- Show deflection curves with magnitudes
- For FBDs: show all resolved forces including reactions
- For ray diagrams: show complete image location, magnification, and type

**CS / Math / Chemistry Diagrams:**
- Show the FINAL result: sorted array, completed tree, shortest path with distances
- For BST operations: show the tree AFTER the operation (the answer)
- Shade/label computed areas, intersection points, derivatives
- Show complete reaction products and mechanisms

**Medical / Life Sciences Diagrams:**
- Label ALL phases, enzymes, thresholds, and values
- Action potential: label all phases, mark threshold, overshoot, resting potential with values
- Metabolic pathway: label ALL enzyme names and metabolite names
- Pharmacokinetics: mark Cmax, t½, AUC, MEC values on the curve
- Dose-response: mark EC50, Emax values
- Anatomical diagrams: label ALL structures with correct names

DIAGRAM SIZE REQUIREMENTS:
- Use compact sizes: figsize=(6, 4) or figsize=(5, 4)
- NEVER use large sizes like (10, 8) or (8, 6)
- DPI: 100-150

DESCRIPTION QUALITY RULES:
Your description MUST incorporate information from BOTH the question AND the correct answer.
  1. Include ALL values from the question text
  2. Include ALL computed/derived values from the correct answer
  3. State the diagram type clearly
  4. Specify every label, annotation, and value that must appear

CODE GENERATION BEST PRACTICES:
1. Set figure size early: plt.subplots(figsize=(6, 4))
2. Use tight_layout() before saving
3. Save with: plt.savefig('output.png', dpi=100, bbox_inches='tight')
"""

        # Append subject-specific prompt additions from registry
        if domain:
            subject_section = self.prompt_registry.get_agent_system_prompt(
                domain, diagram_type
            )
            if subject_section:
                base_prompt += f"\n{subject_section}"

        return base_prompt

    def _sanitize_text_for_prompt(
        self, text: str, equations: List[dict[str, Any]] = []
    ) -> str:
        if not text:
            return ""

        # Replace LaTeX equations with text equations
        for eq in equations:
            eq_id = eq.get("id")
            latex = eq.get("latex")
            eq_text = LatexNodes2Text().latex_to_text(latex)
            eq_type = eq.get("type", "inline")
            if eq_id and latex:
                # Replace equation placeholders with LaTeX representation
                placeholder = f"<eq {eq_id}>"
                replacement = f"{eq_text}"
                print(
                    f"[_sanitize_text_for_prompt] Replacing equation placeholder {placeholder} with {replacement}"
                )
                text = text.replace(placeholder, replacement)

        # Replace excessive whitespace
        sanitized = text.replace("   ", " ").replace("  ", " ").strip()
        return sanitized

    def _resolve_equation_placeholders(
        self, question: Dict[str, Any], text: str
    ) -> str:
        """
        Replace <eq ID> placeholders with their LaTeX values so the diagram
        agent and downstream tools see actual values instead of opaque tokens.

        Example: "<eq q2_eq1>" → "01"  (from the question's equations array)
        """
        equations = question.get("equations", [])
        if not equations:
            return text

        resolved = self._sanitize_text_for_prompt(text, equations)
        if resolved != text:
            logger.info(
                f"Resolved {len(equations)} equation placeholders in question text"
            )
        return resolved

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
            existing_diagram_hint = question.get(
                "diagram"
            )  # Check if original LLM suggested a diagram

            # ── Resolve <eq> placeholders so diagram tools see actual values ──
            # The equation extractor runs BEFORE the diagram agent, replacing
            # math expressions with tokens like <eq q2_eq1>.  We substitute
            # the LaTeX values back so the diagram description is precise.
            equation_resolved_question_text = self._resolve_equation_placeholders(
                question, question_text
            )

            logger.info(
                f"Analyzing question {question_idx}: {equation_resolved_question_text[:100]}..."
            )

            # ── Step 1: DomainRouter classification ──────────────────────────
            classification = self.domain_router.classify(
                question_text=equation_resolved_question_text,
                subject_hint=self.subject,
            )
            q_domain = classification["domain"]
            q_diagram_type = classification["diagram_type"]
            q_ai_suitable = classification["ai_suitable"]
            q_preferred_tool = classification["preferred_tool"]
            logger.info(
                f"Q{question_idx} classified: domain={q_domain}, type={q_diagram_type}, "
                f"ai_suitable={q_ai_suitable}, preferred_tool={q_preferred_tool}"
            )

            # ── Phase 5: ai_suitable override ────────────────────────────────
            # If engine=ai but diagram type is better rendered by code tools, downgrade
            effective_engine = self.engine
            if self.engine in ("ai", "both") and not q_ai_suitable:
                if self.domain_router.should_override_to_nonai(q_diagram_type):
                    effective_engine = "nonai"
                    logger.info(
                        f"Q{question_idx}: ai_suitable=False for {q_diagram_type} → "
                        f"overriding engine=ai to nonai (code tools are better)"
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
            mode_description = (
                "GENEROUS mode (aim for 33%+ diagrams)"
                if has_diagram_analysis
                else "INTELLIGENT mode (generate when helpful)"
            )

            analysis_prompt = f"""Analyze this question and decide if a diagram would help students visualize and understand the problem:

Question Type: {question_type}
Question Text: {equation_resolved_question_text}
Domain classification: {q_domain} / {q_diagram_type}{llm_diagram_hint}

If a diagram would genuinely enhance understanding:
1. Choose the appropriate tool for this domain
2. Provide an accurate description of what to draw
3. Call the tool

If no diagram is needed (pure theory, definitions, abstract concepts):
- Respond with "No diagram needed" and briefly explain why

Mode: {mode_description}
"""

            # Call agent with tool access — use subject-specific system prompt
            messages = [
                {
                    "role": "system",
                    "content": self._get_agent_prompt(
                        has_diagram_analysis, q_domain, q_diagram_type
                    ),
                },
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

                # ── Parse secondary tool calls (for multi-diagram questions) ──
                # When the agent makes 2+ tool calls (e.g., circuitikz for circuit +
                # claude_code for timing), we process each and stitch vertically.
                secondary_tool_calls = []
                for tc in message.tool_calls[1:]:
                    try:
                        sec_args = json.loads(tc.function.arguments)
                        secondary_tool_calls.append((tc.function.name, sec_args))
                        logger.info(
                            f"Q{question_idx}: Parsed secondary tool call: {tc.function.name}"
                        )
                    except json.JSONDecodeError:
                        try:
                            sec_args = _repair_truncated_json(tc.function.arguments)
                            secondary_tool_calls.append((tc.function.name, sec_args))
                        except json.JSONDecodeError:
                            logger.warning(
                                f"Q{question_idx}: Could not parse secondary tool call args"
                            )

                # --- Robust JSON parsing with repair for truncated arguments ---
                try:
                    tool_arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as json_err:
                    logger.warning(
                        f"JSON parse error for question {question_idx} tool args, attempting repair: {json_err}"
                    )
                    try:
                        tool_arguments = _repair_truncated_json(
                            tool_call.function.arguments
                        )
                        logger.info(
                            f"JSON repair succeeded for question {question_idx}"
                        )
                    except json.JSONDecodeError:
                        logger.error(
                            f"JSON repair failed for question {question_idx}. Raw args: {tool_call.function.arguments[:200]}"
                        )
                        # Fallback: if the agent wanted a diagram, try claude_code_tool with description from question
                        logger.info(
                            f"Falling back to claude_code_tool for question {question_idx} after JSON error"
                        )
                        tool_name = "claude_code_tool"
                        tool_arguments = {
                            "domain": "general",
                            "diagram_type": "diagram",
                            "tool_type": "matplotlib",
                            "description": equation_resolved_question_text[:300],
                        }

                logger.info(
                    f"Agent decided to use {tool_name} for question {question_idx}"
                )

                imagen_accepted = (
                    False  # Track whether Imagen retry loop accepted a diagram
                )

                # ── ENGINE=AI or BOTH: Route to Gemini native image gen with retry loop ──
                if effective_engine in ("ai", "both"):
                    # Extract description from whatever tool the agent picked
                    imagen_description = tool_arguments.get(
                        "description",
                        tool_arguments.get(
                            "prompt", equation_resolved_question_text[:300]
                        ),
                    )
                    # Strip <eq qN_eqM> placeholders — they confuse Gemini image gen
                    imagen_description = re.sub(
                        r"<eq\s+\S+>", "", imagen_description
                    ).strip()

                    # ── Phase 3: Prepend subject-specific imagen style guidance ──
                    style_guidance = self.prompt_registry.get_imagen_description_prompt(
                        q_domain, q_diagram_type
                    )
                    if style_guidance:
                        imagen_description = f"{style_guidance}\n\n{imagen_description}"
                        logger.info(
                            f"Q{question_idx}: Prepended {q_domain}/{q_diagram_type} imagen guidance"
                        )

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
                    # Uses a temporary directory that is cleaned up after all attempts
                    _ai_save_dir = tempfile.mkdtemp(
                        prefix=f"ai_diagrams_{assignment_id}_"
                    )
                    logger.info(f"AI diagrams temp dir: {_ai_save_dir}")

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
                                question_text=equation_resolved_question_text,
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
                                question_text=equation_resolved_question_text,
                            )

                        if diagram_data is None:
                            logger.warning(
                                f"Gemini image gen failed on attempt {attempt} for Q{question_idx}"
                            )
                            last_image_bytes = (
                                None  # Reset so next attempt regenerates from scratch
                            )
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
                                logger.info(
                                    f"Saved AI diagram locally: {_local_path} ({len(_attempt_bytes)} bytes)"
                                )
                            except Exception as _save_err:
                                logger.warning(
                                    f"Could not save AI diagram locally: {_save_err}"
                                )

                        # Review the generated image immediately
                        image_bytes_for_review = _attempt_bytes
                        if image_bytes_for_review is None:
                            try:
                                import requests as _req

                                resp = _req.get(diagram_data["s3_url"], timeout=15)
                                if resp.status_code == 200:
                                    image_bytes_for_review = resp.content
                            except Exception as dl_err:
                                logger.warning(
                                    f"Could not download Gemini diagram for review: {dl_err}"
                                )

                        if image_bytes_for_review:
                            # Use current_description (may be updated corrected description),
                            # not the stale original tool_arguments description.
                            description_for_review = current_description
                            # Strip <eq qN_eqM> placeholder tags from question_text before
                            # passing to reviewer — they cause false label-mismatch failures
                            # because the reviewer sees "<eq" as a label name.
                            clean_question_for_review = re.sub(
                                r"<eq\s+\S+>", "", equation_resolved_question_text
                            ).strip()
                            review_result = await self.reviewer.review_diagram(
                                image_bytes=image_bytes_for_review,
                                question_text=clean_question_for_review,
                                diagram_description=description_for_review,
                                user_prompt_context=getattr(
                                    self, "_generation_prompt", ""
                                ),
                                domain=q_domain,
                                diagram_type=q_diagram_type,
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
                                last_review_issues = ", ".join(
                                    review_result.get("issues", [])
                                )
                                last_review_result = review_result

                                # Check if failure is dimension/label related
                                _reason_lower = review_result.get("reason", "").lower()
                                _issues_lower = last_review_issues.lower()
                                _dim_keywords = [
                                    "dimension",
                                    "label",
                                    "unit",
                                    "thickness",
                                    "width",
                                    "conflicting",
                                    "duplicate",
                                    "wrong axis",
                                    "mm",
                                    "cm",
                                ]
                                if any(
                                    kw in _reason_lower or kw in _issues_lower
                                    for kw in _dim_keywords
                                ):
                                    dimension_failures += 1
                                    logger.info(
                                        f"Dimension-related failure #{dimension_failures} for Q{question_idx}"
                                    )

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
                                    corrected = review_result.get(
                                        "corrected_description"
                                    )
                                    if corrected:
                                        imagen_description = corrected
                                        logger.info(
                                            f"Structural issue -- regenerating from scratch with "
                                            f"corrected description: {corrected[:120]}..."
                                        )
                                diagram_data = None  # Reset so we retry
                        else:
                            # Can't review -- accept it and move on
                            logger.warning(
                                f"No image bytes for review on attempt {attempt}, accepting as-is"
                            )
                            if self.engine == "both":
                                _ai_image_bytes_for_stitch = diagram_data.get(
                                    "_image_bytes"
                                )
                            diagram_data.pop("_image_bytes", None)
                            imagen_accepted = True
                            break

                    if not imagen_accepted:
                        logger.warning(
                            f"Gemini image gen failed all {max_imagen_attempts} attempts for Q{question_idx}, "
                            f"falling back to nonai flow (claude_code_tool/schemdraw/matplotlib)"
                        )
                        diagram_data = None  # Force nonai fallback

                    # Clean up the temp directory used for AI-generated images
                    try:
                        shutil.rmtree(_ai_save_dir, ignore_errors=True)
                        logger.info(f"Cleaned up AI diagrams temp dir: {_ai_save_dir}")
                    except Exception as _cleanup_err:
                        logger.warning(
                            f"Could not clean up AI diagrams temp dir: {_cleanup_err}"
                        )

                # ── ENGINE=NONAI / BOTH (or Gemini fallback): Use the code-based flow ──
                # For engine=both we always run nonai even when AI succeeded.
                # For engine=ai we only run nonai as a fallback when Gemini failed.
                # For engine=both: save the AI result before running nonai
                _ai_diagram_data = (
                    diagram_data
                    if effective_engine == "both" and imagen_accepted
                    else None
                )

                # ── Inject subject_guidance into primary tool call ────────────
                # The GPT-4o agent doesn't know about our registry, so we inject
                # subject-specific code generation guidance here for quality/style.
                if tool_name == "claude_code_tool" and not tool_arguments.get(
                    "subject_guidance"
                ):
                    injected_guidance = self.prompt_registry.get_nonai_tool_prompt(
                        q_domain, q_diagram_type, "matplotlib"
                    )
                    if injected_guidance:
                        tool_arguments = dict(tool_arguments)  # copy before mutating
                        tool_arguments["subject_guidance"] = injected_guidance
                        logger.info(
                            f"Q{question_idx}: Injected {q_domain}/{q_diagram_type} subject_guidance "
                            f"into claude_code_tool ({len(injected_guidance)} chars)"
                        )
                elif tool_name == "svg_circuit_tool" and not tool_arguments.get(
                    "subject_context"
                ):
                    injected_ctx = self.prompt_registry.get_nonai_tool_prompt(
                        q_domain, q_diagram_type, "svg"
                    )
                    if injected_ctx:
                        tool_arguments = dict(tool_arguments)
                        tool_arguments["subject_context"] = injected_ctx

                # Run nonai when: engine=nonai, engine=both (always), or engine=ai as fallback
                if effective_engine != "ai" or diagram_data is None:
                    diagram_data = await self.diagram_tools.execute_tool_call(
                        tool_name=tool_name,
                        tool_arguments=tool_arguments,
                        assignment_id=assignment_id,
                        question_idx=question_idx,
                        question_text=equation_resolved_question_text,
                    )

                # ── Phase 4: Subject-specific fallback routing ─────────────────
                # If primary tool failed, use FallbackRouter to pick the right tool
                if diagram_data is None and tool_name not in (
                    "circuitikz_tool",
                    "svg_circuit_tool",
                    "claude_code_tool",
                ):
                    logger.warning(
                        f"Primary tool '{tool_name}' failed for Q{question_idx}. "
                        f"Using subject-specific fallback router..."
                    )
                    (
                        fallback_tool,
                        fallback_args,
                    ) = self.fallback_router.build_tool_arguments(
                        domain=q_domain,
                        diagram_type=q_diagram_type,
                        description=tool_arguments.get(
                            "description", equation_resolved_question_text[:300]
                        ),
                        question_text=equation_resolved_question_text,
                    )
                    logger.info(f"FallbackRouter selected: {fallback_tool}")

                    diagram_data = await self.diagram_tools.execute_tool_call(
                        tool_name=fallback_tool,
                        tool_arguments=fallback_args,
                        assignment_id=assignment_id,
                        question_idx=question_idx,
                        question_text=equation_resolved_question_text,
                    )
                    if diagram_data:
                        logger.info(
                            f"Subject-specific fallback succeeded for Q{question_idx}"
                        )

                # If circuitikz_tool failed, retry with enriched description
                if diagram_data is None and tool_name in (
                    "circuitikz_tool",
                    "svg_circuit_tool",
                ):
                    logger.warning(
                        f"circuit tool failed for question {question_idx}. "
                        f"Retrying circuitikz_tool with enriched description..."
                    )
                    enriched_desc = (
                        f"Draw a professional circuit diagram for: {equation_resolved_question_text[:200]}. "
                        f"Original description: {tool_arguments.get('description', '')}. "
                        f"Use standard MOSFET symbols for transistor circuits. "
                        f"Use IEEE gate symbols (AND, OR, NOT shapes) for digital logic gates. "
                        f"Draw flip-flops as labeled rectangles with D/CLK/Q/Q-bar pins. "
                        f"Draw shift registers as chained flip-flops with Q→D connections. "
                        f"Keep wiring clean and orthogonal."
                    )
                    fallback_args = {
                        "description": enriched_desc,
                    }
                    diagram_data = await self.diagram_tools.execute_tool_call(
                        tool_name="circuitikz_tool",
                        tool_arguments=fallback_args,
                        assignment_id=assignment_id,
                        question_idx=question_idx,
                        question_text=equation_resolved_question_text,
                    )
                    if diagram_data:
                        logger.info(
                            f"circuitikz_tool retry succeeded for question {question_idx}"
                        )
                    else:
                        logger.error(
                            f"All fallbacks failed for question {question_idx}"
                        )

                # --- Final fallback: GPT-4o direct code generation if all tools unavailable ---
                if diagram_data is None:
                    # Use the classified domain (not keyword inference) for the final fallback
                    if q_domain in (
                        "electrical",
                        "computer_eng",
                    ) and q_diagram_type in (
                        "circuit_schematic",
                        "analog_circuit",
                        "mosfet_circuit",
                        "logic_circuit",
                        "alu_circuit",
                        "sequential_circuit",
                        "flip_flop_circuit",
                        "counter_circuit",
                        "shift_register",
                        "cdc_diagram",
                        "block_diagram",
                        "circuit_with_timing",
                    ):
                        # For circuit types, try circuitikz_tool one more time with simplified description
                        logger.warning(
                            f"All primary tools failed for Q{question_idx}. "
                            f"Final retry with circuitikz_tool (simplified)..."
                        )
                        final_desc = (
                            f"SIMPLE circuit diagram for: {equation_resolved_question_text[:200]}. "
                            f"Use standard MOSFET symbols for transistor circuits. "
                            f"Use standard IEEE gate symbols for digital gates. "
                            f"Keep it minimal and clean."
                        )
                        diagram_data = await self.diagram_tools.execute_tool_call(
                            tool_name="circuitikz_tool",
                            tool_arguments={"description": final_desc},
                            assignment_id=assignment_id,
                            question_idx=question_idx,
                            question_text=equation_resolved_question_text,
                        )
                        if not diagram_data:
                            logger.warning(
                                f"Final circuitikz_tool retry failed. Trying GPT-4o fallback..."
                            )
                            diagram_data = await self._gpt_direct_code_fallback(
                                question_text=equation_resolved_question_text,
                                description=tool_arguments.get(
                                    "description", equation_resolved_question_text[:300]
                                ),
                                assignment_id=assignment_id,
                                question_idx=question_idx,
                                domain=q_domain,
                            )
                    else:
                        logger.warning(
                            f"All primary tools failed for Q{question_idx}. "
                            f"Trying GPT-4o direct code generation fallback..."
                        )
                        diagram_data = await self._gpt_direct_code_fallback(
                            question_text=equation_resolved_question_text,
                            description=tool_arguments.get(
                                "description", equation_resolved_question_text[:300]
                            ),
                            assignment_id=assignment_id,
                            question_idx=question_idx,
                            domain=q_domain,
                        )

                # ── ENGINE=BOTH: Stitch AI + Claude images side by side ────────
                if effective_engine == "both" and _ai_diagram_data and diagram_data:
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
                            nonai_bytes = (
                                resp.content if resp.status_code == 200 else None
                            )

                        if ai_bytes and nonai_bytes:
                            logger.info(
                                f"Stitching AI + Claude diagrams for Q{question_idx}"
                            )
                            stitched_bytes = self._stitch_side_by_side(
                                ai_bytes, nonai_bytes
                            )
                            # Upload stitched image to S3
                            stitched_data = (
                                await self.diagram_tools.diagram_gen.upload_to_s3(
                                    image_bytes=stitched_bytes,
                                    assignment_id=assignment_id,
                                    question_index=question_idx,
                                )
                            )
                            stitched_data.pop("_image_bytes", None)
                            diagram_data = stitched_data
                            logger.info(
                                f"Stitched comparison diagram uploaded for Q{question_idx}"
                            )
                        else:
                            logger.warning(
                                f"Could not get both image bytes for stitching Q{question_idx}, using nonai only"
                            )
                    except Exception as _stitch_err:
                        logger.error(
                            f"Stitch failed for Q{question_idx}: {_stitch_err} — using nonai diagram"
                        )

                # ── Multi-diagram stitching (circuit + timing/waveform) ────────
                # If the agent made secondary tool calls, execute them and
                # stitch all results vertically (primary on top).
                if diagram_data and secondary_tool_calls:
                    primary_bytes = diagram_data.pop("_image_bytes", None)
                    if primary_bytes is None:
                        try:
                            import requests as _req

                            resp = _req.get(diagram_data["s3_url"], timeout=15)
                            if resp.status_code == 200:
                                primary_bytes = resp.content
                        except Exception:
                            pass

                    if primary_bytes:
                        all_image_bytes = [primary_bytes]
                        all_labels = [self._label_for_tool(tool_name, q_diagram_type)]

                        for sec_tool_name, sec_tool_args in secondary_tool_calls:
                            # Inject subject_guidance for secondary claude_code_tool calls
                            if (
                                sec_tool_name == "claude_code_tool"
                                and not sec_tool_args.get("subject_guidance")
                            ):
                                sec_guidance = (
                                    self.prompt_registry.get_nonai_tool_prompt(
                                        q_domain,
                                        q_diagram_type,
                                        sec_tool_args.get("tool_type", "matplotlib"),
                                    )
                                )
                                if sec_guidance:
                                    sec_tool_args = dict(sec_tool_args)
                                    sec_tool_args["subject_guidance"] = sec_guidance

                            logger.info(
                                f"Q{question_idx}: Executing secondary tool: {sec_tool_name}"
                            )
                            sec_data = await self.diagram_tools.execute_tool_call(
                                tool_name=sec_tool_name,
                                tool_arguments=sec_tool_args,
                                assignment_id=assignment_id,
                                question_idx=question_idx,
                                question_text=equation_resolved_question_text,
                            )
                            if sec_data:
                                sec_bytes = sec_data.pop("_image_bytes", None)
                                if sec_bytes is None:
                                    try:
                                        import requests as _req

                                        resp = _req.get(sec_data["s3_url"], timeout=15)
                                        if resp.status_code == 200:
                                            sec_bytes = resp.content
                                    except Exception:
                                        pass
                                if sec_bytes:
                                    all_image_bytes.append(sec_bytes)
                                    all_labels.append(
                                        self._label_for_tool(
                                            sec_tool_name, q_diagram_type
                                        )
                                    )
                                    logger.info(
                                        f"Q{question_idx}: Secondary diagram from {sec_tool_name} ready"
                                    )
                            else:
                                logger.warning(
                                    f"Q{question_idx}: Secondary tool {sec_tool_name} failed, skipping"
                                )

                        # Stitch all diagrams vertically if we have more than one
                        if len(all_image_bytes) > 1:
                            try:
                                stitched = self._stitch_vertical(
                                    all_image_bytes, all_labels
                                )
                                stitched_data = (
                                    await self.diagram_tools.diagram_gen.upload_to_s3(
                                        image_bytes=stitched,
                                        assignment_id=assignment_id,
                                        question_index=question_idx,
                                    )
                                )
                                stitched_data.pop("_image_bytes", None)
                                diagram_data = stitched_data
                                logger.info(
                                    f"Q{question_idx}: Multi-diagram stitch uploaded "
                                    f"({len(all_image_bytes)} diagrams)"
                                )
                            except Exception as _stitch_err:
                                logger.error(
                                    f"Q{question_idx}: Multi-diagram stitch failed: {_stitch_err}"
                                )
                    else:
                        # Could not get primary bytes — skip secondary calls
                        diagram_data.pop("_image_bytes", None)

                if diagram_data:
                    # ── Diagram Review Step ──────────────────────────────
                    # Skip review if engine=ai/both already reviewed in the Imagen retry loop
                    if effective_engine in ("ai", "both") and imagen_accepted:
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
                                logger.warning(
                                    f"Could not download diagram for review: {dl_err}"
                                )

                        if image_bytes_for_review:
                            description_for_review = tool_arguments.get(
                                "description", equation_resolved_question_text[:300]
                            )
                            # Strip <eq> placeholders to prevent false label-mismatch failures
                            clean_question_for_review = re.sub(
                                r"<eq\s+\S+>", "", equation_resolved_question_text
                            ).strip()
                            review_result = await self.reviewer.review_diagram(
                                image_bytes=image_bytes_for_review,
                                question_text=clean_question_for_review,
                                diagram_description=description_for_review,
                                user_prompt_context=getattr(
                                    self, "_generation_prompt", ""
                                ),
                                domain=q_domain,
                                diagram_type=q_diagram_type,
                            )

                            if not review_result["passed"]:
                                logger.warning(
                                    f"Diagram review FAILED for Q{question_idx}: {review_result['reason']}  "
                                    f"Issues: {review_result['issues']}"
                                )
                                corrected_desc = review_result.get(
                                    "corrected_description"
                                )
                                if corrected_desc:
                                    logger.info(
                                        f"Regenerating Q{question_idx} with corrected description: "
                                        f"{corrected_desc[:120]}..."
                                    )
                                    # Preserve the original tool for regeneration so matplotlib
                                    # diagrams don't degrade to SVG (which can't render LaTeX
                                    # and produces overlapping text for plots/iv_curves).
                                    if tool_name == "claude_code_tool":
                                        regen_tool = "claude_code_tool"
                                        regen_args = dict(tool_arguments)
                                        regen_args["description"] = (
                                            corrected_desc
                                            + " Do NOT include any computed answer values, "
                                            "specific numeric results, or parameters that reveal "
                                            "the solution."
                                        )
                                    else:
                                        regen_tool = "circuitikz_tool"
                                        regen_args = {"description": corrected_desc}
                                    logger.info(
                                        f"Regenerating Q{question_idx} using {regen_tool} "
                                        f"(original tool preserved)"
                                    )
                                    regen_data = await self.diagram_tools.execute_tool_call(
                                        tool_name=regen_tool,
                                        tool_arguments=regen_args,
                                        assignment_id=assignment_id,
                                        question_idx=question_idx,
                                        question_text=equation_resolved_question_text,
                                    )
                                    if regen_data:
                                        # Pop transient key before attaching
                                        regen_data.pop("_image_bytes", None)
                                        diagram_data = regen_data
                                        logger.info(
                                            f"Regenerated diagram accepted for Q{question_idx}"
                                        )
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
Original question with equations resolved: {equation_resolved_question_text}

Rephrase the question to reference "the diagram below" or "the circuit shown below". Respond with ONLY the rephrased question text WITH EQUATION PLACEHOLDERS.

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
6. Preserve all equation place holders (like <eq_q_1>, <eq_q_2>, etc.) in the rephrased question so they can be resolved later.

Examples:
- "What is a binary tree?" → "Analyze the binary tree shown in the diagram below."
- "Calculate VDS for the circuit on page 20 with R=10kΩ" → "For the MOSFET circuit shown below with R = 10 kΩ, calculate VDS."
- "A silicon chip (10 mm x 10 mm x 1 mm) with k=149 W/m·K, refer to Figure 3.5" → "Consider the silicon chip (10 mm x 10 mm x 1 mm, k = 149 W/m·K) shown in the diagram below..."
"""

                    rephrase_response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a helpful assistant that rephrases questions to reference diagrams naturally.",
                            },
                            {"role": "user", "content": rephrase_prompt},
                        ],
                        temperature=0.3,
                    )

                    rephrased_text = rephrase_response.choices[
                        0
                    ].message.content.strip()

                    # Update question
                    if rephrased_text != "KEEP_ORIGINAL":
                        question["question"] = rephrased_text
                        question["text"] = rephrased_text
                        logger.info(
                            f"Question {question_idx} rephrased to: {rephrased_text[:100]}..."
                        )

                    # ── Rephrase correctAnswer and rubric to reference diagram ──
                    q_type = question.get("type", "")
                    correct_answer = question.get("correctAnswer", "")
                    rubric_text = question.get("rubric", "")

                    # Only rephrase text-based answers (not MCQ indices or true/false)
                    _skip_answer_types = {"multiple-choice", "true-false"}
                    _is_text_answer = (
                        q_type not in _skip_answer_types
                        and isinstance(correct_answer, str)
                        and len(correct_answer) > 3
                    )

                    if _is_text_answer and (correct_answer or rubric_text):
                        try:
                            answer_rephrase_prompt = f"""A diagram has been generated for the following question. Update the correct answer and rubric so they naturally reference the diagram where appropriate.

Question (rephrased): {question.get("question", question_text)}

Current correct answer:
{correct_answer}

Current rubric:
{rubric_text}

INSTRUCTIONS:
1. Update the correct answer and rubric to reference "the diagram" / "the diagram below" / "the circuit shown" where it makes sense
2. PRESERVE ALL numerical values, formulas, derivation steps, grading criteria, and point allocations exactly
3. Do NOT change the substance or meaning — only update references to align with the diagram context
4. If the answer or rubric already makes sense without referencing the diagram, keep it as-is
5. Preserve all equation placeholders (like <eq_q_1>, <eq_q_2>, etc.)

Respond in this exact format:
CORRECT_ANSWER:
<the updated correct answer>
RUBRIC:
<the updated rubric>
"""
                            answer_rephrase_response = self.client.chat.completions.create(
                                model=self.model,
                                messages=[
                                    {
                                        "role": "system",
                                        "content": "You are a helpful assistant that updates correct answers and rubrics to reference diagrams naturally. Preserve all technical content exactly.",
                                    },
                                    {"role": "user", "content": answer_rephrase_prompt},
                                ],
                                temperature=0.3,
                            )
                            ar_text = answer_rephrase_response.choices[
                                0
                            ].message.content.strip()

                            # Parse the structured response
                            if "CORRECT_ANSWER:" in ar_text and "RUBRIC:" in ar_text:
                                ca_start = ar_text.index("CORRECT_ANSWER:") + len(
                                    "CORRECT_ANSWER:"
                                )
                                rubric_start = ar_text.index("RUBRIC:")
                                new_correct_answer = ar_text[
                                    ca_start:rubric_start
                                ].strip()
                                new_rubric = ar_text[
                                    rubric_start + len("RUBRIC:") :
                                ].strip()

                                if new_correct_answer:
                                    question["correctAnswer"] = new_correct_answer
                                if new_rubric:
                                    question["rubric"] = new_rubric
                                logger.info(
                                    f"Q{question_idx}: correctAnswer and rubric rephrased to reference diagram"
                                )
                            else:
                                logger.warning(
                                    f"Q{question_idx}: Could not parse answer/rubric rephrase response, keeping originals"
                                )
                        except Exception as e:
                            logger.warning(
                                f"Q{question_idx}: Error rephrasing answer/rubric: {e}; keeping originals"
                            )

                    # Attach diagram data
                    question["diagram"] = {
                        "s3_url": diagram_data.get("s3_url"),
                        "s3_key": diagram_data.get("s3_key"),
                        "file_id": diagram_data.get("file_id"),
                        "filename": diagram_data.get("filename"),
                    }
                    question["hasDiagram"] = True

                    # ── Auto-convert question type for diagram-dependent questions ──
                    # When a diagram is generated for a question that asks students
                    # to draw, determine, or analyze outputs/results from a diagram,
                    # the question type should be "diagram-analysis" so students know
                    # they need to work with the diagram (e.g., draw waveforms, trace
                    # algorithms, complete diagrams).
                    _qt_lower = equation_resolved_question_text.lower()

                    # Electrical/CompEng: waveform, timing, counter, sequential circuit questions
                    _is_waveform_or_counter_q = q_diagram_type in (
                        "waveform",
                        "timing_diagram",
                        "circuit_with_timing",
                        "flip_flop_circuit",
                        "sequential_circuit",
                        "counter_circuit",
                        "shift_register",
                        "isa_timing",
                    ) and any(
                        kw in _qt_lower
                        for kw in [
                            "output waveform",
                            "draw the waveform",
                            "sketch the waveform",
                            "determine the output",
                            "describe the output",
                            "find the output",
                            "complete the timing",
                            "state after",
                            "clock pulse",
                            "clock cycle",
                            "state of the counter",
                            "state transition",
                        ]
                    )

                    # Generic across all domains: questions that ask students to
                    # draw, sketch, trace, or complete something on the diagram
                    _is_draw_or_trace_q = question.get("hasDiagram", False) and any(
                        kw in _qt_lower
                        for kw in [
                            "draw the",
                            "sketch the",
                            "complete the diagram",
                            "trace the",
                            "fill in the",
                            "plot the",
                            "draw a free body",
                            "draw the shear",
                            "draw the bending moment",
                            "draw the ray diagram",
                            "draw the mechanism",
                            "draw the state diagram",
                            "complete the truth table",
                            "complete the timing diagram",
                            "draw the output",
                            "construct the",
                        ]
                    )

                    if (
                        _is_waveform_or_counter_q or _is_draw_or_trace_q
                    ) and question.get("type") in (
                        "short-answer",
                        "numerical",
                        "fill-in-blanks",
                    ):
                        old_type = question["type"]
                        question["type"] = "diagram-analysis"
                        logger.info(
                            f"Q{question_idx}: Auto-converted type '{old_type}' → "
                            f"'diagram-analysis' (question requires diagram interaction)"
                        )

                    # ── correctAnswerDiagram generation is handled below, outside the question-diagram branch ──

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

            # ── Generate correctAnswerDiagram (runs independently of question diagram) ──
            # DRA questions: MUST generate. diagram-analysis: generate if draw/sketch detected.
            await self._generate_correct_answer_diagram(
                question=question,
                question_idx=question_idx,
                assignment_id=assignment_id,
                question_text=equation_resolved_question_text,
                q_domain=q_domain,
                q_diagram_type=q_diagram_type,
                q_ai_suitable=q_ai_suitable,
            )

            return question

        except Exception as e:
            logger.error(f"Error analyzing question {question_idx}: {str(e)}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return question  # Return unchanged on error

    async def _ai_decide_correct_answer_diagram_needed(
        self,
        question_text: str,
        question_idx: int,
    ) -> bool:
        """
        Use an AI call to decide whether a correctAnswerDiagram should be generated
        for a diagram-analysis type question.

        Returns True if the question requires the student to produce a diagram
        (draw, sketch, complete, trace, plot, etc.) and therefore an answer-key
        diagram would be useful.  Returns False otherwise.
        """
        system_prompt = (
            "You are an expert educational content reviewer. "
            "Your task is to decide whether a 'diagram-analysis' question requires the student "
            "to produce, draw, sketch, complete, trace, or plot a diagram as part of their answer. "
            'Answer with a single JSON object: {"required": true} or {"required": false}. '
            "Output ONLY the JSON — no explanation, no markdown fences."
        )
        user_prompt = (
            "Question:\n"
            f"{question_text}\n\n"
            "Does answering this question require the student to draw, sketch, complete, "
            "trace, plot, or otherwise produce a diagram or waveform? "
            'Respond with {"required": true} or {"required": false}.'
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                max_tokens=20,
            )
            raw = response.choices[0].message.content or ""
            # Strip any accidental markdown fences
            raw = raw.strip().strip("`").strip()
            result = json.loads(raw)
            decision = bool(result.get("required", False))
            if decision:
                logger.info(
                    f"Q{question_idx}: AI decided correctAnswerDiagram IS required "
                    f"(diagram-analysis)"
                )
            else:
                logger.info(
                    f"Q{question_idx}: AI decided correctAnswerDiagram NOT required "
                    f"(diagram-analysis)"
                )
            return decision
        except Exception as e:
            # Fall back to not generating on any error to avoid spurious diagrams
            logger.warning(
                f"Q{question_idx}: AI decision for correctAnswerDiagram failed ({e}); "
                f"defaulting to skip"
            )
            return False

    async def _generate_correct_answer_diagram(
        self,
        question: Dict[str, Any],
        question_idx: int,
        assignment_id: str,
        question_text: str,
        q_domain: str,
        q_diagram_type: str,
        q_ai_suitable: bool = True,
    ) -> None:
        """
        Generate a correctAnswerDiagram for questions that require it.

        Uses the FULL agent pipeline: GPT-4o picks tool (tool_choice="auto"),
        imagen retry loop with Gemini review, non-AI fallback, multi-diagram
        stitching, and Gemini review for code-generated diagrams.

        Decision logic:
        - diagram-required-in-answer: ALWAYS generate (this is the whole point of DRA)
        - diagram-analysis, short-answer, numerical: AI decides (via _ai_decide_correct_answer_diagram_needed)
        - All other types: Skip
        """
        if not assignment_id:
            return

        q_type = question.get("type", "")

        # Determine if we should generate a correctAnswerDiagram
        should_generate = False

        if q_type == "diagram-required-in-answer":
            should_generate = True
            logger.info(
                f"Q{question_idx}: DRA type — generating correctAnswerDiagram (mandatory)"
            )
        elif q_type in ["diagram-analysis", "short-answer", "numerical"]:
            should_generate = await self._ai_decide_correct_answer_diagram_needed(
                question_text=question_text,
                question_idx=question_idx,
            )

        if not should_generate:
            return

        try:
            correct_answer = question.get("correctAnswer", "")
            answer_qidx = f"{question_idx}_answer"
            answer_qtext = f"ANSWER KEY: {question_text}"

            # ── A. Build user message via _get_answer_diagram_description ──
            answer_description = self._get_answer_diagram_description(
                question_text=question_text,
                correct_answer=correct_answer,
                domain=q_domain,
                diagram_type=q_diagram_type,
            )

            analysis_prompt = (
                f"Generate the answer-key diagram for this question.\n\n"
                f"{answer_description}\n\n"
                f"Domain classification: {q_domain} / {q_diagram_type}\n\n"
                f"You MUST generate a diagram — this is an answer key. "
                f"Choose the appropriate tool and provide a detailed description."
            )

            # ── B. Call GPT-4o with DIAGRAM_TOOLS ──
            messages = [
                {
                    "role": "system",
                    "content": self._get_answer_key_agent_prompt(
                        q_domain, q_diagram_type
                    ),
                },
                {"role": "user", "content": analysis_prompt},
            ]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=DIAGRAM_TOOLS,
                tool_choice="auto",
                temperature=0.3,
            )

            message = response.choices[0].message

            if not message.tool_calls:
                logger.warning(
                    f"Q{question_idx}: Answer-key agent did not call a tool; "
                    f"falling back to claude_code_tool"
                )
                tool_name = "claude_code_tool"
                tool_arguments = {
                    "domain": q_domain or "general",
                    "diagram_type": q_diagram_type or "diagram",
                    "tool_type": "matplotlib",
                    "description": answer_description,
                }
                secondary_tool_calls = []
            else:
                # ── C. Parse tool call response ──
                tool_call = message.tool_calls[0]
                tool_name = tool_call.function.name

                # Parse secondary tool calls (multi-diagram)
                secondary_tool_calls = []
                for tc in message.tool_calls[1:]:
                    try:
                        sec_args = json.loads(tc.function.arguments)
                        secondary_tool_calls.append((tc.function.name, sec_args))
                        logger.info(
                            f"Q{question_idx} answer: Parsed secondary tool call: {tc.function.name}"
                        )
                    except json.JSONDecodeError:
                        try:
                            sec_args = _repair_truncated_json(tc.function.arguments)
                            secondary_tool_calls.append((tc.function.name, sec_args))
                        except json.JSONDecodeError:
                            logger.warning(
                                f"Q{question_idx} answer: Could not parse secondary tool call args"
                            )

                # Robust JSON parsing with repair
                try:
                    tool_arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as json_err:
                    logger.warning(
                        f"Q{question_idx} answer: JSON parse error, attempting repair: {json_err}"
                    )
                    try:
                        tool_arguments = _repair_truncated_json(
                            tool_call.function.arguments
                        )
                        logger.info(f"Q{question_idx} answer: JSON repair succeeded")
                    except json.JSONDecodeError:
                        logger.error(
                            f"Q{question_idx} answer: JSON repair failed. "
                            f"Raw args: {tool_call.function.arguments[:200]}"
                        )
                        tool_name = "claude_code_tool"
                        tool_arguments = {
                            "domain": q_domain or "general",
                            "diagram_type": q_diagram_type or "diagram",
                            "tool_type": "matplotlib",
                            "description": answer_description,
                        }

            logger.info(f"Q{question_idx} answer: Agent decided to use {tool_name}")

            # ── D. Determine effective_engine ──
            effective_engine = self.engine
            if self.engine in ("ai", "both") and not q_ai_suitable:
                if self.domain_router.should_override_to_nonai(q_diagram_type):
                    effective_engine = "nonai"
                    logger.info(
                        f"Q{question_idx} answer: ai_suitable=False → overriding to nonai"
                    )

            diagram_data = None
            imagen_accepted = False

            # ── E. ENGINE=AI or BOTH: Imagen retry loop ──
            if effective_engine in ("ai", "both"):
                imagen_description = tool_arguments.get(
                    "description",
                    tool_arguments.get("prompt", answer_description[:300]),
                )
                imagen_description = re.sub(
                    r"<eq\s+\S+>", "", imagen_description
                ).strip()

                # Prepend subject-specific imagen style guidance
                style_guidance = self.prompt_registry.get_imagen_description_prompt(
                    q_domain, q_diagram_type
                )
                if style_guidance:
                    imagen_description = f"{style_guidance}\n\n{imagen_description}"

                logger.info(
                    f"Q{question_idx} answer: Engine=ai routing to imagen_tool "
                    f"(agent picked {tool_name})"
                )

                max_imagen_attempts = 3
                last_image_bytes = None
                dimension_failures = 0
                last_review_result = None

                _ai_save_dir = tempfile.mkdtemp(prefix=f"ai_answer_{assignment_id}_")

                for attempt in range(1, max_imagen_attempts + 1):
                    logger.info(
                        f"Q{question_idx} answer: Imagen attempt {attempt}/{max_imagen_attempts}"
                    )

                    current_description = imagen_description
                    if attempt == max_imagen_attempts and dimension_failures >= 2:
                        current_description += (
                            "\n\nIMPORTANT - USE SYMBOLIC LABELS INSTEAD OF NUMERIC DIMENSIONS:\n"
                            "Do NOT write specific numeric dimension values on the diagram.\n"
                            "Instead, use symbolic variable names for ALL dimensions."
                        )
                        logger.info(
                            f"Q{question_idx} answer: Attempt {attempt}: switching to symbolic "
                            f"after {dimension_failures} dimension failures"
                        )

                    if attempt == 1 or last_image_bytes is None:
                        diagram_data = await self.diagram_tools.execute_tool_call(
                            tool_name="imagen_tool",
                            tool_arguments={
                                "description": current_description,
                                "subject": self.subject,
                            },
                            assignment_id=assignment_id,
                            question_idx=answer_qidx,
                            question_text=answer_qtext,
                        )
                    else:
                        logger.info(
                            f"Q{question_idx} answer: Fixing existing diagram (attempt {attempt})"
                        )
                        diagram_data = await self.diagram_tools.imagen_fix_tool(
                            image_bytes=last_image_bytes,
                            issues=last_review_result.get("issues", []),
                            reason=last_review_result.get("reason", ""),
                            original_description=current_description,
                            assignment_id=assignment_id,
                            question_idx=answer_qidx,
                            question_text=answer_qtext,
                        )

                    if diagram_data is None:
                        logger.warning(
                            f"Q{question_idx} answer: Imagen failed on attempt {attempt}"
                        )
                        last_image_bytes = None
                        last_review_result = None
                        continue

                    # Save locally for inspection
                    _attempt_bytes = diagram_data.get("_image_bytes")
                    if _attempt_bytes:
                        _local_path = os.path.join(
                            _ai_save_dir, f"Q{question_idx}_answer_attempt{attempt}.png"
                        )
                        try:
                            with open(_local_path, "wb") as _f:
                                _f.write(_attempt_bytes)
                        except Exception:
                            pass

                    # Review the generated image
                    image_bytes_for_review = _attempt_bytes
                    if image_bytes_for_review is None:
                        try:
                            import requests as _req

                            resp = _req.get(diagram_data["s3_url"], timeout=15)
                            if resp.status_code == 200:
                                image_bytes_for_review = resp.content
                        except Exception:
                            pass

                    if image_bytes_for_review:
                        clean_question = re.sub(
                            r"<eq\s+\S+>", "", question_text
                        ).strip()
                        review_result = await self.reviewer.review_diagram(
                            image_bytes=image_bytes_for_review,
                            question_text=f"ANSWER KEY for: {clean_question}",
                            diagram_description=current_description,
                            user_prompt_context=answer_description,
                            domain=q_domain,
                            diagram_type=q_diagram_type,
                        )

                        if review_result["passed"]:
                            logger.info(
                                f"Q{question_idx} answer: Imagen PASSED review on attempt {attempt}"
                            )
                            diagram_data.pop("_image_bytes", None)
                            imagen_accepted = True
                            break
                        else:
                            is_fixable = review_result.get("fixable", False)
                            last_review_issues = ", ".join(
                                review_result.get("issues", [])
                            )
                            last_review_result = review_result

                            _reason_lower = review_result.get("reason", "").lower()
                            _issues_lower = last_review_issues.lower()
                            _dim_keywords = [
                                "dimension",
                                "label",
                                "unit",
                                "thickness",
                                "width",
                                "conflicting",
                                "duplicate",
                            ]
                            if any(
                                kw in _reason_lower or kw in _issues_lower
                                for kw in _dim_keywords
                            ):
                                dimension_failures += 1

                            logger.warning(
                                f"Q{question_idx} answer: Imagen FAILED review attempt "
                                f"{attempt}/{max_imagen_attempts} (fixable={is_fixable}): "
                                f"{review_result['reason'][:120]}"
                            )

                            if is_fixable:
                                last_image_bytes = image_bytes_for_review
                            else:
                                last_image_bytes = None
                                corrected = review_result.get("corrected_description")
                                if corrected:
                                    imagen_description = corrected
                                    logger.info(
                                        f"Q{question_idx} answer: Regenerating with "
                                        f"corrected description"
                                    )
                            diagram_data = None
                    else:
                        logger.warning(
                            f"Q{question_idx} answer: No bytes for review, accepting as-is"
                        )
                        diagram_data.pop("_image_bytes", None)
                        imagen_accepted = True
                        break

                if not imagen_accepted:
                    logger.warning(
                        f"Q{question_idx} answer: Imagen failed all attempts, "
                        f"falling back to nonai"
                    )
                    diagram_data = None

                # Clean up temp dir
                try:
                    shutil.rmtree(_ai_save_dir, ignore_errors=True)
                except Exception:
                    pass

            # ── F. ENGINE=NONAI or AI fallback: Execute code tool ──
            # Inject subject_guidance for claude_code_tool
            if tool_name == "claude_code_tool" and not tool_arguments.get(
                "subject_guidance"
            ):
                injected_guidance = self.prompt_registry.get_nonai_tool_prompt(
                    q_domain, q_diagram_type, "matplotlib"
                )
                if injected_guidance:
                    tool_arguments = dict(tool_arguments)
                    tool_arguments["subject_guidance"] = injected_guidance

            if effective_engine != "ai" or diagram_data is None:
                diagram_data = await self.diagram_tools.execute_tool_call(
                    tool_name=tool_name,
                    tool_arguments=tool_arguments,
                    assignment_id=assignment_id,
                    question_idx=answer_qidx,
                    question_text=answer_qtext,
                )

            # Fallback to claude_code_tool if primary tool failed
            if diagram_data is None and tool_name != "claude_code_tool":
                logger.warning(
                    f"Q{question_idx} answer: Primary tool '{tool_name}' failed, "
                    f"falling back to claude_code_tool"
                )
                fallback_args = {
                    "domain": q_domain or "general",
                    "diagram_type": q_diagram_type or "diagram",
                    "tool_type": "matplotlib",
                    "description": answer_description,
                }
                diagram_data = await self.diagram_tools.execute_tool_call(
                    tool_name="claude_code_tool",
                    tool_arguments=fallback_args,
                    assignment_id=assignment_id,
                    question_idx=answer_qidx,
                    question_text=answer_qtext,
                )

            # ── G. Multi-diagram stitching ──
            if diagram_data and secondary_tool_calls:
                primary_bytes = diagram_data.pop("_image_bytes", None)
                if primary_bytes is None:
                    try:
                        import requests as _req

                        resp = _req.get(diagram_data["s3_url"], timeout=15)
                        if resp.status_code == 200:
                            primary_bytes = resp.content
                    except Exception:
                        pass

                if primary_bytes:
                    all_image_bytes = [primary_bytes]
                    all_labels = [self._label_for_tool(tool_name, q_diagram_type)]

                    for sec_tool_name, sec_tool_args in secondary_tool_calls:
                        if (
                            sec_tool_name == "claude_code_tool"
                            and not sec_tool_args.get("subject_guidance")
                        ):
                            sec_guidance = self.prompt_registry.get_nonai_tool_prompt(
                                q_domain,
                                q_diagram_type,
                                sec_tool_args.get("tool_type", "matplotlib"),
                            )
                            if sec_guidance:
                                sec_tool_args = dict(sec_tool_args)
                                sec_tool_args["subject_guidance"] = sec_guidance

                        logger.info(
                            f"Q{question_idx} answer: Executing secondary tool: {sec_tool_name}"
                        )
                        sec_data = await self.diagram_tools.execute_tool_call(
                            tool_name=sec_tool_name,
                            tool_arguments=sec_tool_args,
                            assignment_id=assignment_id,
                            question_idx=answer_qidx,
                            question_text=answer_qtext,
                        )
                        if sec_data:
                            sec_bytes = sec_data.pop("_image_bytes", None)
                            if sec_bytes is None:
                                try:
                                    import requests as _req

                                    resp = _req.get(sec_data["s3_url"], timeout=15)
                                    if resp.status_code == 200:
                                        sec_bytes = resp.content
                                except Exception:
                                    pass
                            if sec_bytes:
                                all_image_bytes.append(sec_bytes)
                                all_labels.append(
                                    self._label_for_tool(sec_tool_name, q_diagram_type)
                                )

                    if len(all_image_bytes) > 1:
                        try:
                            stitched = self._stitch_vertical(
                                all_image_bytes, all_labels
                            )
                            stitched_data = (
                                await self.diagram_tools.diagram_gen.upload_to_s3(
                                    image_bytes=stitched,
                                    assignment_id=assignment_id,
                                    question_index=answer_qidx,
                                )
                            )
                            stitched_data.pop("_image_bytes", None)
                            diagram_data = stitched_data
                            logger.info(
                                f"Q{question_idx} answer: Multi-diagram stitch uploaded "
                                f"({len(all_image_bytes)} diagrams)"
                            )
                        except Exception as _stitch_err:
                            logger.error(
                                f"Q{question_idx} answer: Multi-diagram stitch failed: "
                                f"{_stitch_err}"
                            )
                else:
                    diagram_data.pop("_image_bytes", None)

            # ── H. Gemini review for non-AI/fallback diagrams ──
            if diagram_data and not (
                effective_engine in ("ai", "both") and imagen_accepted
            ):
                image_bytes_for_review = diagram_data.pop("_image_bytes", None)
                if image_bytes_for_review is None:
                    try:
                        import requests as _req

                        resp = _req.get(diagram_data["s3_url"], timeout=15)
                        if resp.status_code == 200:
                            image_bytes_for_review = resp.content
                    except Exception:
                        pass

                if image_bytes_for_review:
                    description_for_review = tool_arguments.get(
                        "description", answer_description[:300]
                    )
                    clean_question = re.sub(r"<eq\s+\S+>", "", question_text).strip()
                    review_result = await self.reviewer.review_diagram(
                        image_bytes=image_bytes_for_review,
                        question_text=f"ANSWER KEY for: {clean_question}",
                        diagram_description=description_for_review,
                        user_prompt_context=answer_description,
                        domain=q_domain,
                        diagram_type=q_diagram_type,
                    )

                    if not review_result["passed"]:
                        logger.warning(
                            f"Q{question_idx} answer: Diagram review FAILED: "
                            f"{review_result['reason'][:120]}"
                        )
                        corrected_desc = review_result.get("corrected_description")
                        if corrected_desc:
                            logger.info(
                                f"Q{question_idx} answer: Regenerating with "
                                f"corrected description"
                            )
                            if tool_name == "claude_code_tool":
                                regen_tool = "claude_code_tool"
                                regen_args = dict(tool_arguments)
                                regen_args["description"] = corrected_desc
                            else:
                                regen_tool = "circuitikz_tool"
                                regen_args = {"description": corrected_desc}

                            regen_data = await self.diagram_tools.execute_tool_call(
                                tool_name=regen_tool,
                                tool_arguments=regen_args,
                                assignment_id=assignment_id,
                                question_idx=answer_qidx,
                                question_text=answer_qtext,
                            )
                            if regen_data:
                                regen_data.pop("_image_bytes", None)
                                diagram_data = regen_data
                                logger.info(
                                    f"Q{question_idx} answer: Regenerated diagram accepted"
                                )
                    else:
                        logger.info(f"Q{question_idx} answer: Diagram review PASSED")

            # ── I. Store result ──
            if diagram_data and diagram_data.get("s3_url"):
                diagram_data.pop("_image_bytes", None)
                question["correctAnswerDiagram"] = {
                    "s3_url": diagram_data.get("s3_url"),
                    "s3_key": diagram_data.get("s3_key"),
                    "file_id": diagram_data.get("file_id"),
                    "filename": diagram_data.get("filename"),
                }
                logger.info(
                    f"Q{question_idx}: correctAnswerDiagram generated successfully"
                )
            else:
                logger.warning(
                    f"Q{question_idx}: correctAnswerDiagram generation failed, "
                    f"continuing without it"
                )
        except Exception as e:
            logger.warning(
                f"Q{question_idx}: Error generating correctAnswerDiagram: {e}; "
                f"continuing without it"
            )

    def _get_answer_diagram_description(
        self,
        question_text: str,
        correct_answer: str,
        domain: str,
        diagram_type: str,
    ) -> str:
        """
        Build a self-contained description for the correct-answer diagram.

        This prompt is completely independent of the question-diagram prompts.
        It contains NO answer-hiding rules — this is the instructor's answer key.
        """
        # Domain-specific guidance for what a complete answer looks like
        domain_guidance = ""
        if domain in ("electrical", "electronics", "digital_logic", "vlsi"):
            if diagram_type in ("waveform", "timing_diagram", "circuit_with_timing"):
                domain_guidance = (
                    "Show ALL signal waveforms including computed outputs. "
                    "Draw both input and output signals with correct timing relationships, "
                    "propagation delays, and logic levels clearly marked at each clock edge."
                )
            elif diagram_type in ("circuit_schematic", "logic_gate", "analog_circuit"):
                domain_guidance = (
                    "Show the complete circuit with ALL computed values annotated — "
                    "node voltages, branch currents, power dissipation, gain values. "
                    "Label every component with its value."
                )
            elif diagram_type in (
                "flip_flop_circuit",
                "sequential_circuit",
                "counter_circuit",
            ):
                domain_guidance = (
                    "Show the complete state transition diagram or timing diagram with "
                    "ALL states, outputs, and transitions filled in. Include state values "
                    "at each clock cycle."
                )
            else:
                domain_guidance = (
                    "Show the complete solution with all computed electrical values, "
                    "waveforms, and annotations."
                )
        elif domain in ("mechanical", "civil", "structural"):
            domain_guidance = (
                "Show the complete solution: all reaction forces with magnitudes and directions, "
                "shear force diagram, bending moment diagram, deflection curves, or free body diagram "
                "with all forces resolved. Label every value with correct units."
            )
        elif domain in ("cs", "algorithms", "data_structures"):
            domain_guidance = (
                "Show the final result: sorted array, completed tree after operations, "
                "shortest path with distances, traversal order, or algorithm trace with "
                "all intermediate states. Label each step clearly."
            )
        elif domain in (
            "medical",
            "biology",
            "biochemistry",
            "pharmacology",
            "physiology",
        ):
            domain_guidance = (
                "Show the complete diagram with ALL labels filled in: enzyme names, "
                "metabolite names, hormone names, receptor types, pathway steps. "
                "Include numerical values (Cmax, EC50, t½) if relevant. "
                "Mark all phases, thresholds, and key points."
            )
        elif domain in ("physics", "optics", "thermodynamics"):
            domain_guidance = (
                "Show the complete solution: ray diagram with image location, "
                "force diagram with resultants, energy diagrams with values, "
                "or phase diagrams with all regions labeled. Include all computed values."
            )
        elif domain in ("chemistry", "organic_chemistry"):
            domain_guidance = (
                "Show the complete reaction products, mechanism arrows, "
                "molecular structures with stereochemistry, or energy profile "
                "with activation energies and intermediate species labeled."
            )
        elif domain in ("math", "calculus", "linear_algebra"):
            domain_guidance = (
                "Show the complete graph with shaded areas, intersection points, "
                "critical points, asymptotes, and all computed values labeled. "
                "Include axis scales and key coordinates."
            )
        else:
            domain_guidance = (
                "Show the complete solution with all values, labels, and annotations "
                "that represent the correct answer."
            )

        description = (
            f"INSTRUCTOR ANSWER KEY diagram — this is a reference solution, NOT shown to students.\n\n"
            f"Question: {question_text[:500]}\n\n"
            f"Correct answer: {correct_answer[:500]}\n\n"
            f"REQUIREMENTS:\n"
            f"- {domain_guidance}\n"
            f"- This diagram must show the COMPLETE, CORRECT solution — every value, label, and result.\n"
            f"- Use clear, professional formatting suitable for an answer key.\n"
            f"- Use compact figure size: figsize=(6, 4), dpi=100.\n"
        )
        return description

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

        AI_COLOR = (25, 100, 210)  # blue  — AI Generated header
        NONAI_COLOR = (20, 145, 65)  # green — Schematic Generated header
        HEADER_TEXT = (255, 255, 255)  # white text in header
        BOX_BORDER = (200, 200, 200)  # light grey outer border
        BG = (245, 246, 248)  # off-white canvas background

        HEADER_H = 38  # header bar height
        IMG_PAD = 16  # padding around image inside box
        BOX_GAP = 28  # horizontal gap between the two boxes
        OUTER_PAD = 20  # canvas margin on all sides
        BORDER_W = 2  # box border width

        # ── Load & normalise images ──────────────────────────────────────
        img_ai = Image.open(io.BytesIO(ai_bytes)).convert("RGB")
        img_nonai = Image.open(io.BytesIO(nonai_bytes)).convert("RGB")

        # Scale both to the same width (use the larger width as target)
        target_w = max(img_ai.width, img_nonai.width)

        def scale_to_width(img, w):
            if img.width == w:
                return img
            ratio = w / img.width
            return img.resize((w, int(img.height * ratio)), Image.LANCZOS)

        img_ai = scale_to_width(img_ai, target_w)
        img_nonai = scale_to_width(img_nonai, target_w)

        # ── Compute box dimensions ───────────────────────────────────────
        box_inner_w = target_w + IMG_PAD * 2

        ai_box_h = HEADER_H + IMG_PAD + img_ai.height + IMG_PAD
        nonai_box_h = HEADER_H + IMG_PAD + img_nonai.height + IMG_PAD
        max_box_h = max(ai_box_h, nonai_box_h)

        total_w = (
            OUTER_PAD
            + box_inner_w
            + BORDER_W * 2
            + BOX_GAP
            + box_inner_w
            + BORDER_W * 2
            + OUTER_PAD
        )
        total_h = OUTER_PAD + max_box_h + BORDER_W * 2 + OUTER_PAD

        canvas = Image.new("RGB", (total_w, total_h), BG)
        draw = ImageDraw.Draw(canvas)

        # ── Font ─────────────────────────────────────────────────────────
        try:
            font_bold = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 17)
            font_normal = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
        except Exception:
            font_bold = ImageFont.load_default()
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
            icon_x = hx0 + 12
            icon_y = hy0 + (HEADER_H - 14) // 2
            draw.rectangle([icon_x, icon_y, icon_x + 12, icon_y + 12], fill=HEADER_TEXT)
            text_x = icon_x + 20
            text_y = hy0 + (HEADER_H - 17) // 2
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

    @staticmethod
    def _label_for_tool(tool_name: str, diagram_type: str = "") -> str:
        """Return a human-readable label for a tool name.

        For multi-diagram stitching, uses diagram_type to produce
        context-aware labels. When a secondary diagram is stitched
        below a primary one, we label it generically ('Given Information')
        so it works across all subjects — not just electrical.
        """
        # Context-aware labels for the secondary (supplementary) portion
        # of multi-diagram questions — generic across all subjects.
        # The primary diagram gets its own label (Circuit Diagram, etc.);
        # the secondary one is labeled generically so it works for any domain.
        _multi_diagram_secondary_types = {
            "circuit_with_timing",
            "sequential_circuit",
            "flip_flop_circuit",
            "counter_circuit",
            "shift_register",
        }
        if (
            tool_name in ("claude_code_tool", "matplotlib_tool")
            and diagram_type in _multi_diagram_secondary_types
        ):
            return "Given Information"

        _labels = {
            "circuitikz_tool": "Circuit Diagram",
            "svg_circuit_tool": "Circuit Diagram",
            "schemdraw_tool": "Circuit Diagram",
            "claude_code_tool": "Timing / Waveform Diagram",
            "matplotlib_tool": "Timing / Waveform Diagram",
            "networkx_tool": "Graph / Tree Diagram",
            "imagen_tool": "AI Generated",
            "dalle_tool": "AI Generated",
        }
        return _labels.get(tool_name, "Diagram")

    def _stitch_vertical(
        self,
        image_bytes_list: list,
        labels: list = None,
    ) -> bytes:
        """
        Stack multiple PNG images vertically with optional header labels.

        Layout:
          ┌──────────────────────────────┐
          │  ■ Circuit Diagram           │  ← header bar
          ├──────────────────────────────┤
          │        <circuit image>       │
          ├──────────────────────────────┤
          │  ■ Timing / Waveform Diagram │  ← header bar
          ├──────────────────────────────┤
          │       <waveform image>       │
          └──────────────────────────────┘
        """
        from PIL import Image, ImageDraw, ImageFont
        import io

        if not image_bytes_list:
            raise ValueError("No images to stitch")

        COLORS = [
            (25, 100, 210),  # blue
            (20, 145, 65),  # green
            (180, 70, 20),  # orange
            (120, 50, 160),  # purple
        ]
        HEADER_TEXT = (255, 255, 255)
        BG = (245, 246, 248)
        BOX_BORDER = (200, 200, 200)

        HEADER_H = 34
        IMG_PAD = 12
        OUTER_PAD = 16
        BORDER_W = 2
        BOX_GAP = 12  # vertical gap between boxes

        # ── Load images ──────────────────────────────────────────────────
        images = []
        for ib in image_bytes_list:
            images.append(Image.open(io.BytesIO(ib)).convert("RGB"))

        # Scale all to the same width (use the max width)
        target_w = max(img.width for img in images)

        def scale_to_width(img, w):
            if img.width == w:
                return img
            ratio = w / img.width
            return img.resize((w, int(img.height * ratio)), Image.LANCZOS)

        images = [scale_to_width(img, target_w) for img in images]

        if labels is None:
            labels = [f"Diagram {i+1}" for i in range(len(images))]

        # ── Compute total canvas size ────────────────────────────────────
        box_inner_w = target_w + IMG_PAD * 2
        total_w = OUTER_PAD * 2 + BORDER_W * 2 + box_inner_w

        total_h = OUTER_PAD
        for img in images:
            total_h += (
                BORDER_W * 2 + HEADER_H + IMG_PAD + img.height + IMG_PAD + BOX_GAP
            )
        total_h += OUTER_PAD - BOX_GAP  # remove last gap, add bottom pad

        canvas = Image.new("RGB", (total_w, total_h), BG)
        draw = ImageDraw.Draw(canvas)

        # ── Font ─────────────────────────────────────────────────────────
        try:
            font_bold = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 15)
        except Exception:
            font_bold = ImageFont.load_default()

        # ── Draw each box ────────────────────────────────────────────────
        y_cursor = OUTER_PAD
        for idx, (img, label) in enumerate(zip(images, labels)):
            color = COLORS[idx % len(COLORS)]

            x0 = OUTER_PAD
            y0 = y_cursor
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
            draw.rectangle([hx0, hy0, hx1, hy1], fill=color)

            # ■ icon + label
            icon_x = hx0 + 10
            icon_y = hy0 + (HEADER_H - 12) // 2
            draw.rectangle([icon_x, icon_y, icon_x + 10, icon_y + 10], fill=HEADER_TEXT)
            text_x = icon_x + 16
            text_y = hy0 + (HEADER_H - 15) // 2
            draw.text((text_x, text_y), label, fill=HEADER_TEXT, font=font_bold)

            # Divider
            draw.line([hx0, hy1, hx1, hy1], fill=color, width=1)

            # Paste image
            img_x = x0 + BORDER_W + IMG_PAD
            img_y = hy1 + IMG_PAD
            canvas.paste(img, (img_x, img_y))

            y_cursor = y1 + BOX_GAP

        out = io.BytesIO()
        canvas.save(out, format="PNG")
        return out.getvalue()

    def _infer_domain(self, question_text: str) -> str:
        """Infer the domain from question text for diagram generation."""
        q_lower = question_text.lower()
        if any(
            kw in q_lower
            for kw in [
                "circuit",
                "cmos",
                "mosfet",
                "nmos",
                "pmos",
                "transistor",
                "amplifier",
                "resistor",
                "capacitor",
                "voltage",
                "current",
                "inverter",
                "nand",
                "nor",
                "logic gate",
                "vdd",
                "drain",
                "source",
            ]
        ):
            return "electrical"
        elif any(
            kw in q_lower
            for kw in [
                "force",
                "pressure",
                "velocity",
                "fluid",
                "manometer",
                "beam",
                "torque",
                "moment",
                "friction",
            ]
        ):
            return "physics"
        elif any(
            kw in q_lower
            for kw in [
                "tree",
                "graph",
                "node",
                "linked list",
                "binary",
                "stack",
                "queue",
                "hash",
                "algorithm",
            ]
        ):
            return "computer_science"
        elif any(
            kw in q_lower
            for kw in [
                "integral",
                "derivative",
                "matrix",
                "equation",
                "polynomial",
                "eigenvalue",
                "vector",
            ]
        ):
            return "mathematics"
        # ── Medical sciences ──────────────────────────────────────────────────
        elif any(
            kw in q_lower
            for kw in [
                "anatomical",
                "anatomy",
                "histology",
                "histological",
                "cross-section",
                "sagittal",
                "coronal",
                "transverse section",
                "organ",
                "bone",
                "ligament",
                "tendon",
            ]
        ):
            return "anatomy"
        elif any(
            kw in q_lower
            for kw in [
                "action potential",
                "membrane potential",
                "resting potential",
                "depolarization",
                "repolarization",
                "excitation-contraction",
                "sarcoplasmic reticulum",
                "cardiac cycle",
                "pressure-volume",
                "p-v loop",
                "homeostasis",
                "feedback loop",
                "cardiac output",
                "stroke volume",
            ]
        ):
            return "physiology"
        elif any(
            kw in q_lower
            for kw in [
                "metabolic pathway",
                "glycolysis",
                "krebs cycle",
                "citric acid",
                "enzyme kinetics",
                "michaelis",
                "vmax",
                "metabolite",
                "atp synthesis",
                "nadh",
                "coenzyme",
                "biochemical",
            ]
        ):
            return "biochemistry"
        elif any(
            kw in q_lower
            for kw in [
                "dose-response",
                "dose response",
                "ec50",
                "pharmacokinetics",
                "plasma concentration",
                "bioavailability",
                "half-life",
                "agonist",
                "antagonist",
                "therapeutic index",
            ]
        ):
            return "pharmacology"
        elif any(
            kw in q_lower
            for kw in [
                "histopathology",
                "disease progression",
                "cancer staging",
                "neoplasia",
                "necrosis",
                "inflammation",
                "pathogenesis",
                "tumour",
                "tumor",
            ]
        ):
            return "pathology"
        elif any(
            kw in q_lower
            for kw in [
                "bacterial",
                "bacteria",
                "gram stain",
                "gram-positive",
                "gram-negative",
                "infection cycle",
                "replication cycle",
                "pathogen",
                "antimicrobial",
                "growth curve",
                "colony forming",
            ]
        ):
            return "microbiology"
        return "general"

    def _strip_code_fences(self, code: str) -> str:
        """Strip markdown code fences from generated code."""
        code = code.strip()
        if code.startswith("```python"):
            code = code[len("```python") :]
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
        domain: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        Final fallback: Ask GPT-4o to generate diagram code directly with
        strict element-name guidance, then execute it.
        This is used when claude_code_tool is unavailable (API key issues, etc.).
        Includes a retry loop that feeds errors back to GPT-4o for auto-repair.
        """
        MAX_ATTEMPTS = 3

        try:
            # Use the passed domain if available, otherwise infer
            if not domain:
                domain = self._infer_domain(question_text)

            # Determine the best library
            if domain in ("electrical", "computer_eng"):
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

            logger.info(
                f"GPT-4o direct code fallback for question {question_idx} (domain={domain}, lib={lib})"
            )

            messages = [
                {
                    "role": "system",
                    "content": "You are an expert code generator. Return ONLY executable Python code. No markdown, no explanations. Keep code SHORT and SIMPLE — under 60 lines. Simple correct diagrams beat complex broken ones.",
                },
                {"role": "user", "content": code_gen_prompt},
            ]

            last_error = None
            for attempt in range(MAX_ATTEMPTS):
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.2
                    + (attempt * 0.1),  # Slightly increase creativity on retries
                    max_tokens=2000,  # Hard cap to prevent 40K+ char code blobs
                )

                code = self._strip_code_fences(response.choices[0].message.content)

                logger.info(
                    f"GPT-4o generated {len(code)} chars of {lib} code for question {question_idx} (attempt {attempt + 1}/{MAX_ATTEMPTS})"
                )

                # Guard: reject absurdly long code (likely garbage)
                if len(code) > 5000:
                    logger.warning(
                        f"GPT-4o generated excessively long code ({len(code)} chars) for question {question_idx} — requesting simpler version"
                    )
                    messages.append({"role": "assistant", "content": code})
                    messages.append(
                        {
                            "role": "user",
                            "content": f"That code is {len(code)} characters — way too long and complex. Generate a MUCH SIMPLER version. A basic {lib} diagram should be 20-40 lines of code. Strip it down to essentials.",
                        }
                    )
                    continue

                # Try to render
                try:
                    if lib == "schemdraw":
                        image_bytes = (
                            await self.diagram_tools.diagram_gen.render_schemdraw(code)
                        )
                    else:
                        image_bytes = (
                            await self.diagram_tools.diagram_gen.render_matplotlib(code)
                        )

                    # Upload to S3
                    diagram_data = await self.diagram_tools.diagram_gen.upload_to_s3(
                        image_bytes, assignment_id, question_idx
                    )

                    logger.info(
                        f"GPT-4o direct code fallback succeeded for question {question_idx} (attempt {attempt + 1})"
                    )
                    return diagram_data

                except Exception as render_err:
                    last_error = str(render_err)
                    logger.warning(
                        f"GPT-4o code render failed (attempt {attempt + 1}/{MAX_ATTEMPTS}): {last_error[:200]}"
                    )

                    if attempt < MAX_ATTEMPTS - 1:
                        # Feed the error back so GPT-4o can fix it
                        messages.append({"role": "assistant", "content": code})
                        messages.append(
                            {
                                "role": "user",
                                "content": f"""The code above failed with this error:

{last_error[:500]}

Fix the code. Common schemdraw 0.19 issues:
- .at(pos, ofst=...) → ofst does NOT exist. Use .at(pos) or .at(pos, dx=1.0)
- anchor + (dx, dy) → CRASHES. Use Point(anchor) + Point((dx, dy))
- elm.Mosfet, elm.PTrans → do NOT exist. Use elm.NFet() / elm.PFet()
- elm.Nand() → does NOT exist. Use: import schemdraw.logic as logic; logic.Nand()
- Overlapping transistors → chain with .at(prev.drain).anchor('drain')
- Missing 'from schemdraw.util import Point' when using Point()

Return the COMPLETE fixed code. Keep it SIMPLE — under 40 lines.""",
                            }
                        )

            logger.error(
                f"GPT-4o direct code fallback failed after {MAX_ATTEMPTS} attempts for question {question_idx}: {last_error}"
            )
            return None

        except Exception as e:
            logger.error(
                f"GPT-4o direct code fallback failed for question {question_idx}: {str(e)}"
            )
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

        tasks = [process_with_semaphore(q, i) for i, q in enumerate(questions)]

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
            (i, q) for i, q in enumerate(questions) if not q.get("hasDiagram", False)
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
                logger.warning(
                    f"Event loop conflict, using thread-based processing: {e}"
                )
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        asyncio.run,
                        self._process_questions_batch(
                            questions, assignment_id, has_diagram_analysis
                        ),
                    )
                    questions = future.result()

            # Enforce minimum percentage if diagram-analysis is enabled
            if has_diagram_analysis:
                questions = self._ensure_minimum_percentage(
                    questions, assignment_id, target_percentage=0.33
                )

            # Log final statistics
            final_count = sum(1 for q in questions if q.get("hasDiagram", False))
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
