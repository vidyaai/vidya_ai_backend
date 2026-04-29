"""
Diagram Generation Tools for Multi-Agent System

These tools are called by the DiagramAnalysisAgent to generate diagrams.
Each tool renders a diagram and uploads it to S3.
"""

import asyncio
from typing import Dict, Any, Optional
from controllers.config import logger
from utils.diagram_generator import DiagramGenerator


# Tool definitions for OpenAI function calling
DIAGRAM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "matplotlib_tool",
            "description": "Generate diagrams using matplotlib. Use for: plots, graphs, mathematical visualizations, physics diagrams, force diagrams, and general 2D/3D visualizations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Complete Python code using matplotlib to generate the diagram. Must include 'import matplotlib.pyplot as plt' and 'plt.savefig('output.png', dpi=200, bbox_inches='tight')'",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of what the diagram shows",
                    },
                },
                "required": ["code", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "networkx_tool",
            "description": "Generate graph and tree diagrams using networkx + matplotlib. Use for: data structures (binary trees, graphs, linked lists), network diagrams, dependency graphs, state machines.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Complete Python code using networkx and matplotlib to generate the diagram. Must include necessary imports and 'plt.savefig('output.png', dpi=200, bbox_inches='tight')'",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of the graph/tree structure",
                    },
                },
                "required": ["code", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schemdraw_tool",
            "description": "Generate electrical circuit diagrams using schemdraw. Use for: electrical circuits (RF, analog, digital), circuit analysis, signal flow diagrams, logic gates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Complete Python code using schemdraw to generate the circuit diagram. Must include 'import schemdraw' and save the drawing with 'd.save('output.png', dpi=200)'",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of the circuit",
                    },
                },
                "required": ["code", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "claude_code_tool",
            "description": "General-purpose diagram generator using Claude + matplotlib/networkx/schemdraw. Use when no specialist tool (tikz_tool, plotly_tool, rdkit_tool, circuitikz_tool) is a better fit. Good for: 2D scientific plots, waveforms, timing diagrams, phase diagrams, action potentials, dose-response curves, pharmacokinetics, metabolic pathways, disease progression, data structures (trees/graphs/lists), flowcharts, CS/math/biology/mechanical/civil diagrams that need a 2D plot or graph. Falls back from specialist tools automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain: physics, electrical, computer_science, mathematics, chemistry, biology, mechanical, civil, anatomy, physiology, biochemistry, pharmacology, pathology, microbiology, or general",
                    },
                    "diagram_type": {
                        "type": "string",
                        "description": "Specific diagram type: manometer, circuit, free_body_diagram, graph, tree, action_potential, feedback_loop, pressure_volume_loop, cardiac_loop, metabolic_pathway, enzyme_kinetics, dose_response, pharmacokinetics, disease_progression, infection_cycle, growth_curve, etc.",
                    },
                    "tool_type": {
                        "type": "string",
                        "enum": ["matplotlib", "schemdraw", "networkx"],
                        "description": "Which library Claude should generate code for: matplotlib (plots, physics, ALL medical scientific plots), schemdraw (circuits), networkx (graphs/trees)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of what the diagram shows",
                    },
                },
                "required": ["domain", "diagram_type", "tool_type", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "circuitikz_tool",
            "description": "BEST for ALL circuit diagrams: Generates publication-quality circuit schematics via CircuiTikZ (LaTeX). Output is identical to Sedra & Smith / Mano textbook diagrams. Use for: ALL electrical circuits including MOSFET/CMOS transistor circuits, analog circuits with Vgs/Vds sources, digital logic gate circuits, op-amp circuits, BJT circuits, RLC networks, D/JK/SR/T flip-flop circuits, shift registers, counters, sequential logic circuits, encoders/decoders, MUX/DEMUX, register files, ALU/datapath, clock domain crossing. Produces perfect component symbols, proper SI unit labels, and textbook-standard layouts. ALWAYS prefer this over svg_circuit_tool for ANY circuit schematic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Detailed description of the circuit: all components, values, connections, and node labels. Example: 'NMOS transistor with Vgs=3V source on gate, Vds=4V source from drain to ground, Vth=1V, kn=300uA/V2, find ID'",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "svg_circuit_tool",
            "description": "DEPRECATED — use circuitikz_tool instead. Legacy SVG circuit generator. Only use if circuitikz_tool is unavailable.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Detailed description of the circuit to draw, including all component values, connections, and labels",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dalle_tool",
            "description": "Generate complex visualizations using DALL-E 3 AI. Use for: complex 3D visualizations, realistic renderings, artistic diagrams, or when code-based tools are insufficient.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Detailed prompt for DALL-E 3 describing the diagram to generate. Should be clear, specific, and technical.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of what the diagram shows",
                    },
                },
                "required": ["prompt", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "neurokit2_tool",
            "description": "Generate physiological signal waveforms for medical education using neurokit2 + scipy. Use for: action_potential (neuronal AP with depolarization/repolarization/hyperpolarization phases, threshold line, resting potential), cardiac_loop (cardiac pressure-volume P-V loop with 4 phases, EDV/ESV/SV labels). Produces scientifically accurate waveforms with correct axes, units, and phase annotations. Preferred over claude_code_tool for these diagram types.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain: physiology",
                    },
                    "diagram_type": {
                        "type": "string",
                        "description": "Diagram type: action_potential or cardiac_loop",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of what the diagram shows, including any specific features to highlight",
                    },
                },
                "required": ["domain", "diagram_type", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scipy_curve_tool",
            "description": "Generate precise mathematical and pharmacological curves using scipy + numpy. Use for: dose_response (sigmoid logistic curve with EC50/Emax markers, via scipy.special.expit), pharmacokinetics (plasma concentration-time curve using one-compartment PK model, marking Cmax/tmax/AUC/t½), enzyme_kinetics (Michaelis-Menten hyperbola with Vmax/Km dashed markers), pressure_volume_loop (cardiac P-V loop), growth_curve (bacterial growth with lag/exponential/stationary/death phases). Produces mathematically accurate curves using real scientific models rather than arbitrary matplotlib code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain: pharmacology, biochemistry, physiology, or microbiology",
                    },
                    "diagram_type": {
                        "type": "string",
                        "description": "Diagram type: dose_response, pharmacokinetics, enzyme_kinetics, pressure_volume_loop, or growth_curve",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of the curve, including specific values (EC50, Km, drug names) mentioned in the question",
                    },
                },
                "required": ["domain", "diagram_type", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "networkx_pathway_tool",
            "description": "Generate directed flow/pathway/cycle diagrams using networkx DiGraph + matplotlib. Use for: metabolic_pathway (metabolites as oval nodes, enzymes as edge labels, cofactor side-nodes in glycolysis/TCA/ETC), feedback_loop (homeostatic loop: stimulus→receptor→integrator→effector→response in circular layout), infection_cycle (pathogen lifecycle: attachment→entry→replication→assembly→release in circular layout), disease_progression (staging flow: Normal→Stage I→Stage II→Stage III with colour-coded nodes). Produces professional pathway diagrams with correct directed edges, node labels, and standard biological layout.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain: biochemistry, physiology, microbiology, or pathology",
                    },
                    "diagram_type": {
                        "type": "string",
                        "description": "Diagram type: metabolic_pathway, feedback_loop, infection_cycle, or disease_progression",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of the pathway/cycle, including specific metabolites, steps, or stages mentioned in the question",
                    },
                },
                "required": ["domain", "diagram_type", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "imagen_tool",
            "description": "PREFERRED for spatial/visual medical diagrams: Generate anatomical illustrations, histology slides, bacterial morphology diagrams, and histopathology images using Gemini native image generation. Use for: anatomical_diagram (organ/body region illustrations), histology (tissue cross-sections, cell types), bacterial_structure (cell wall, flagella, pili, capsule), histopathology (diseased vs. normal tissue), and any medical diagram where spatial structure and visual realism matter more than precise data plots. Do NOT use for mathematical plots (action_potential, metabolic_pathway, dose_response, pharmacokinetics) — use neurokit2_tool, scipy_curve_tool, or networkx_pathway_tool for those.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Detailed description of the medical diagram to generate. Include all structures, labels, anatomical region, orientation (anterior/posterior, superior/inferior), and any specific features to highlight.",
                    },
                    "subject": {
                        "type": "string",
                        "enum": [
                            "anatomy",
                            "histology",
                            "pathology",
                            "microbiology",
                            "biochemistry",
                            "physiology",
                            "pharmacology",
                            "general",
                        ],
                        "description": "Medical subject domain for the diagram",
                    },
                },
                "required": ["description", "subject"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tikz_tool",
            "description": "SPECIALIST — PREFER over claude_code_tool for: physics ray/optics diagrams, Feynman diagrams, free body diagrams with vector arrows, spring-mass systems, field lines, 2D crystal lattice projections and non-3D lattice structures (for 3D unit cells with atom spheres use plotly_tool instead), geometric constructions, Lewis structures, chemical structural formulas, mechanical engineering diagrams. Use whenever LaTeX-quality vector rendering is needed. Falls back to claude_code_tool automatically if compilation fails.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Detailed description of the diagram to draw, including all components, labels, and spatial relationships.",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rdkit_tool",
            "description": "SPECIALIST — PREFER over claude_code_tool for any 2D molecular skeletal formula: organic chemistry structures, drug molecules, amino acids, nucleotides, reaction mechanisms, functional group diagrams. Produces publication-quality 2D structures from SMILES notation. Falls back to claude_code_tool automatically if SMILES conversion fails.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Description of the molecule or chemical structure. Include the molecule name, functional groups, and any structural features to highlight.",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plotly_tool",
            "description": "SPECIALIST — PREFER over claude_code_tool when true 3D perspective is essential: 3D crystal unit cells with atom spheres at correct lattice positions (BCC/FCC/HCP), 3D molecular orbitals, 3D potential energy surfaces, 3D vector fields, any diagram where rotating 3D geometry is the point. Falls back to claude_code_tool automatically if Plotly/kaleido export fails.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Description of the 3D diagram, including structure type, atom positions, labels, and what to highlight.",
                    },
                },
                "required": ["description"],
            },
        },
    },
]


class DiagramTools:
    """Execution handlers for diagram generation tools"""

    def __init__(self, diagram_model: str = "flash"):
        """
        Initialize diagram tools with generator.

        Args:
            diagram_model: "flash" for gemini-2.5-flash-image (Vertex AI),
                           "pro"   for gemini-3-pro-image-preview (Google AI Studio)
        """
        self.diagram_gen = DiagramGenerator()
        self.diagram_model = diagram_model
        self.claude_generator = None  # Lazy load to avoid requiring API key if not used
        self._google_generator = None  # Lazy load for Gemini image gen

    async def matplotlib_tool(
        self, code: str, description: str, assignment_id: str, question_idx: int
    ) -> Dict[str, Any]:
        """
        Execute matplotlib code and generate diagram.

        Args:
            code: Python code using matplotlib
            description: Description of the diagram
            assignment_id: Assignment ID for S3 upload
            question_idx: Question index for filename

        Returns:
            Diagram data dict with S3 info
        """
        try:
            logger.info(
                f"Executing matplotlib_tool for question {question_idx}: {description}"
            )

            # Render diagram
            image_bytes = await self.diagram_gen.render_matplotlib(code)

            # Upload to S3
            diagram_data = await self.diagram_gen.upload_to_s3(
                image_bytes, assignment_id, question_idx
            )

            logger.info(f"Successfully generated matplotlib diagram: {description}")
            return diagram_data

        except Exception as e:
            logger.error(f"Error in matplotlib_tool: {str(e)}")
            return None

    async def networkx_tool(
        self, code: str, description: str, assignment_id: str, question_idx: int
    ) -> Dict[str, Any]:
        """
        Execute networkx code and generate diagram.

        Args:
            code: Python code using networkx + matplotlib
            description: Description of the graph/tree
            assignment_id: Assignment ID for S3 upload
            question_idx: Question index for filename

        Returns:
            Diagram data dict with S3 info
        """
        try:
            logger.info(
                f"Executing networkx_tool for question {question_idx}: {description}"
            )

            # Render diagram
            image_bytes = await self.diagram_gen.render_networkx(code)

            # Upload to S3
            diagram_data = await self.diagram_gen.upload_to_s3(
                image_bytes, assignment_id, question_idx
            )

            logger.info(f"Successfully generated networkx diagram: {description}")
            return diagram_data

        except Exception as e:
            logger.error(f"Error in networkx_tool: {str(e)}")
            return None

    async def schemdraw_tool(
        self, code: str, description: str, assignment_id: str, question_idx: int
    ) -> Dict[str, Any]:
        """
        Execute schemdraw code and generate circuit diagram.

        Args:
            code: Python code using schemdraw
            description: Description of the circuit
            assignment_id: Assignment ID for S3 upload
            question_idx: Question index for filename

        Returns:
            Diagram data dict with S3 info
        """
        try:
            logger.info(
                f"Executing schemdraw_tool for question {question_idx}: {description}"
            )

            # Render diagram
            image_bytes = await self.diagram_gen.render_schemdraw(code)

            # Upload to S3
            diagram_data = await self.diagram_gen.upload_to_s3(
                image_bytes, assignment_id, question_idx
            )

            logger.info(f"Successfully generated schemdraw diagram: {description}")
            return diagram_data

        except Exception as e:
            logger.error(f"Error in schemdraw_tool: {str(e)}")
            return None

    async def claude_code_tool(
        self,
        domain: str,
        diagram_type: str,
        tool_type: str,
        description: str,
        assignment_id: str,
        question_idx: int,
        question_text: str = "",
        subject_guidance: str = "",
        reference_image_bytes: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """
        Generate diagram code using Claude 3.5 Sonnet, then execute it.

        Args:
            domain: Domain (physics, electrical, etc.)
            diagram_type: Specific diagram type
            tool_type: Library to use (matplotlib, schemdraw, networkx)
            description: Description of the diagram
            assignment_id: Assignment ID for S3 upload
            question_idx: Question index for filename
            question_text: Full question text for context

        Returns:
            Diagram data dict with S3 info
        """
        try:
            logger.info(
                f"Executing claude_code_tool for question {question_idx}: {domain}/{diagram_type} using {tool_type}"
            )

            # Lazy load Claude generator
            if self.claude_generator is None:
                from utils.claude_code_generator import ClaudeCodeGenerator

                self.claude_generator = ClaudeCodeGenerator()

            # Generate code using Claude, then execute with up to 2 attempts.
            # On failure the error is fed back to Claude so it self-corrects.
            execution_error = ""
            image_bytes = None
            for _exec_attempt in range(2):
                code = await self.claude_generator.generate_diagram_code(
                    question_text=question_text or description,
                    domain=domain,
                    diagram_type=diagram_type,
                    tool_type=tool_type,
                    subject_guidance=subject_guidance,
                    reference_image_bytes=reference_image_bytes if _exec_attempt == 0 else None,
                    execution_error=execution_error,
                )

                logger.info(
                    f"Claude generated {len(code)} chars of {tool_type} code "
                    f"(attempt {_exec_attempt + 1})"
                )
                logger.debug(f"Generated code:\n{code}")

                try:
                    if tool_type == "matplotlib":
                        image_bytes = await self.diagram_gen.render_matplotlib(code)
                    elif tool_type == "schemdraw":
                        image_bytes = await self.diagram_gen.render_schemdraw(code)
                    elif tool_type == "networkx":
                        image_bytes = await self.diagram_gen.render_networkx(code)
                    else:
                        raise ValueError(f"Unsupported tool_type: {tool_type}")
                    break  # execution succeeded

                except Exception as exec_err:
                    execution_error = str(exec_err)
                    logger.warning(
                        f"Code execution failed (attempt {_exec_attempt + 1}): "
                        f"{execution_error[:200]}"
                    )

                    # Auto-install any missing Python package before retrying
                    import re as _re, subprocess as _sp, sys as _sys
                    mod_match = _re.search(
                        r"No module named '([^']+)'", execution_error
                    )
                    if mod_match:
                        pkg = mod_match.group(1).split(".")[0]
                        logger.info(f"Attempting pip install {pkg} ...")
                        _sp.run(
                            [_sys.executable, "-m", "pip", "install", pkg],
                            capture_output=True,
                            timeout=60,
                        )

                    if _exec_attempt == 1:
                        raise  # both attempts failed

            # Upload to S3
            diagram_data = await self.diagram_gen.upload_to_s3(
                image_bytes, assignment_id, question_idx
            )

            logger.info(f"Successfully generated Claude-powered diagram: {description}")
            return diagram_data

        except Exception as e:
            logger.error(f"Error in claude_code_tool: {str(e)}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    async def circuitikz_tool(
        self,
        description: str,
        assignment_id: str,
        question_idx: int,
        question_text: str = "",
        subject_context: str = "",
    ) -> Dict[str, Any]:
        """
        Generate publication-quality circuit diagram using CircuiTikZ (LaTeX).

        Pipeline: Claude → CircuiTikZ LaTeX → pdflatex → pdf2image → PNG → S3

        Output matches Sedra & Smith textbook style:
        - American-style components with siunitx unit labels
        - Proper MOSFET symbols (NMOS/PMOS with G/D/S terminals)
        - Vertical CMOS layout (VDD → PMOS → output → NMOS → GND)
        - Clean orthogonal wiring

        Args:
            description: Description of the circuit
            assignment_id: Assignment ID for S3 upload
            question_idx: Question index for filename
            question_text: Full question text for context
            subject_context: Optional subject hint

        Returns:
            Diagram data dict with S3 info
        """
        try:
            logger.info(
                f"Executing circuitikz_tool for question {question_idx}: {description[:100]}"
            )

            # Lazy load generator
            if not hasattr(self, "_circuitikz_gen") or self._circuitikz_gen is None:
                from utils.circuitikz_generator import CircuiTikZGenerator

                self._circuitikz_gen = CircuiTikZGenerator()

            # Generate PNG via CircuiTikZ pipeline (300 DPI = print quality)
            image_bytes = await self._circuitikz_gen.generate_circuit_png(
                question_text=question_text or description,
                diagram_description=description,
                output_dpi=300,
                subject_context=subject_context,
            )

            # Upload to S3
            diagram_data = await self.diagram_gen.upload_to_s3(
                image_bytes, assignment_id, question_idx
            )

            # Attach image_bytes for downstream review
            diagram_data["_image_bytes"] = image_bytes

            logger.info(
                f"Successfully generated CircuiTikZ diagram: {description[:80]}"
            )
            return diagram_data

        except Exception as e:
            logger.error(f"Error in circuitikz_tool: {str(e)}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    async def svg_circuit_tool(
        self,
        description: str,
        assignment_id: str,
        question_idx: int,
        question_text: str = "",
        subject_context: str = "",
    ) -> Dict[str, Any]:
        """
        Generate circuit diagram using Claude SVG generation (legacy).

        Pipeline: Claude → SVG → cairosvg → PNG → S3

        Args:
            description: Description of the circuit to draw
            assignment_id: Assignment ID for S3 upload
            question_idx: Question index for filename
            question_text: Full question text for context

        Returns:
            Diagram data dict with S3 info
        """
        try:
            logger.info(
                f"Executing svg_circuit_tool for question {question_idx}: {description}"
            )

            # Lazy load SVG circuit generator
            if not hasattr(self, "_svg_circuit_gen") or self._svg_circuit_gen is None:
                from utils.svg_circuit_generator import SVGCircuitGenerator

                self._svg_circuit_gen = SVGCircuitGenerator()

            # Generate PNG via SVG pipeline (HD: 800px wide at 200 DPI)
            image_bytes = await self._svg_circuit_gen.generate_circuit_png(
                question_text=question_text or description,
                diagram_description=description,
                output_width=800,
                dpi=200,
                subject_context=subject_context,
            )

            # Upload to S3
            diagram_data = await self.diagram_gen.upload_to_s3(
                image_bytes, assignment_id, question_idx
            )

            # Attach image_bytes for downstream review (not serialized to JSON)
            diagram_data["_image_bytes"] = image_bytes

            logger.info(f"Successfully generated SVG circuit diagram: {description}")
            return diagram_data

        except Exception as e:
            logger.error(f"Error in svg_circuit_tool: {str(e)}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    async def dalle_tool(
        self, prompt: str, description: str, assignment_id: str, question_idx: int
    ) -> Dict[str, Any]:
        """
        Generate diagram using DALL-E 3 AI.

        Args:
            prompt: Detailed prompt for DALL-E 3
            description: Description of the diagram
            assignment_id: Assignment ID for S3 upload
            question_idx: Question index for filename

        Returns:
            Diagram data dict with S3 info
        """
        try:
            logger.info(
                f"Executing dalle_tool for question {question_idx}: {description}"
            )

            # Render diagram
            image_bytes = await self.diagram_gen.render_ai_image(prompt)

            # Upload to S3
            diagram_data = await self.diagram_gen.upload_to_s3(
                image_bytes, assignment_id, question_idx
            )

            logger.info(f"Successfully generated DALL-E diagram: {description}")
            return diagram_data

        except Exception as e:
            logger.error(f"Error in dalle_tool: {str(e)}")
            return None

    async def imagen_tool(
        self,
        description: str,
        assignment_id: str,
        question_idx: int,
        question_text: str = "",
        subject: str = "electrical",
    ) -> Dict[str, Any]:
        """
        Generate diagram using Gemini native image generation via Vertex AI.

        Args:
            description: Description of the diagram to generate
            assignment_id: Assignment ID for S3 upload
            question_idx: Question index for filename
            question_text: Full question text for context
            subject: Subject domain

        Returns:
            Diagram data dict with S3 info, or None on failure
        """
        try:
            logger.info(
                f"Executing imagen_tool for question {question_idx}: {description[:100]}..."
            )

            # Lazy load Google generator
            if self._google_generator is None:
                from utils.google_diagram_generator import GoogleDiagramGenerator

                self._google_generator = GoogleDiagramGenerator(
                    diagram_model=self.diagram_model
                )

            result = await self._google_generator.generate_diagram(
                description=description,
                subject=subject,
                question_text=question_text,
            )

            if not result or not result.get("image_bytes"):
                logger.warning(f"Gemini returned no image for question {question_idx}")
                return None

            image_bytes = result["image_bytes"]

            # Upload to S3
            diagram_data = await self.diagram_gen.upload_to_s3(
                image_bytes, assignment_id, question_idx
            )

            # Attach image_bytes for downstream review
            diagram_data["_image_bytes"] = image_bytes

            logger.info(
                f"Successfully generated Gemini diagram for question {question_idx}: "
                f"{len(image_bytes)} bytes"
            )
            return diagram_data

        except Exception as e:
            logger.error(f"Error in imagen_tool: {str(e)}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    async def neurokit2_tool(
        self,
        domain: str,
        diagram_type: str,
        description: str,
        assignment_id: str,
        question_idx: int,
        question_text: str = "",
        subject_guidance: str = "",
    ) -> Dict[str, Any]:
        """
        Generate physiological signal waveforms using neurokit2 + scipy.

        Specialized for action_potential (neuronal AP waveform) and cardiac_loop
        (P-V loop). Uses scipy.interpolate and numpy to produce scientifically
        accurate waveforms with correct phases, axes, and annotations.

        The generated code leverages neurokit2 for cardiac ECG simulations and
        scipy for neuronal membrane potential models, producing publication-quality
        physiological plots rather than hand-crafted matplotlib approximations.
        """
        try:
            logger.info(
                f"Executing neurokit2_tool for Q{question_idx}: {domain}/{diagram_type}"
            )

            # Look up neurokit2-specific guidance (falls back to matplotlib guidance)
            if not subject_guidance:
                if not hasattr(self, "_registry"):
                    from utils.subject_prompt_registry import SubjectPromptRegistry

                    self._registry = SubjectPromptRegistry()
                subject_guidance = self._registry.get_nonai_tool_prompt(
                    domain, diagram_type, "neurokit2"
                ) or self._registry.get_nonai_tool_prompt(
                    domain, diagram_type, "matplotlib"
                )

            # neurokit2 output is matplotlib-based — render with matplotlib pipeline
            return await self.claude_code_tool(
                domain=domain,
                diagram_type=diagram_type,
                tool_type="matplotlib",
                description=description,
                assignment_id=assignment_id,
                question_idx=question_idx,
                question_text=question_text,
                subject_guidance=subject_guidance,
            )
        except Exception as e:
            logger.error(f"Error in neurokit2_tool: {e}")
            return None

    async def scipy_curve_tool(
        self,
        domain: str,
        diagram_type: str,
        description: str,
        assignment_id: str,
        question_idx: int,
        question_text: str = "",
        subject_guidance: str = "",
    ) -> Dict[str, Any]:
        """
        Generate precise mathematical/pharmacological curves using scipy + numpy.

        Specialized for dose_response (scipy.special.expit sigmoid), pharmacokinetics
        (one-compartment PK model), enzyme_kinetics (Michaelis-Menten hyperbola),
        pressure_volume_loop (cardiac P-V loop), and growth_curve (bacterial logistic
        growth). Produces scientifically accurate curves using real mathematical models.
        """
        try:
            logger.info(
                f"Executing scipy_curve_tool for Q{question_idx}: {domain}/{diagram_type}"
            )

            # Look up scipy-specific guidance (falls back to matplotlib guidance)
            if not subject_guidance:
                if not hasattr(self, "_registry"):
                    from utils.subject_prompt_registry import SubjectPromptRegistry

                    self._registry = SubjectPromptRegistry()
                subject_guidance = self._registry.get_nonai_tool_prompt(
                    domain, diagram_type, "scipy"
                ) or self._registry.get_nonai_tool_prompt(
                    domain, diagram_type, "matplotlib"
                )

            # scipy curves render to matplotlib output
            return await self.claude_code_tool(
                domain=domain,
                diagram_type=diagram_type,
                tool_type="matplotlib",
                description=description,
                assignment_id=assignment_id,
                question_idx=question_idx,
                question_text=question_text,
                subject_guidance=subject_guidance,
            )
        except Exception as e:
            logger.error(f"Error in scipy_curve_tool: {e}")
            return None

    async def networkx_pathway_tool(
        self,
        domain: str,
        diagram_type: str,
        description: str,
        assignment_id: str,
        question_idx: int,
        question_text: str = "",
        subject_guidance: str = "",
    ) -> Dict[str, Any]:
        """
        Generate directed flow/pathway/cycle diagrams using networkx DiGraph + matplotlib.

        Specialized for metabolic_pathway (metabolites as nodes, enzymes as edge labels),
        feedback_loop (circular homeostatic loop), infection_cycle (pathogen lifecycle),
        and disease_progression (staging flow diagram). Uses networkx layout algorithms
        for professional graph positioning.
        """
        try:
            logger.info(
                f"Executing networkx_pathway_tool for Q{question_idx}: {domain}/{diagram_type}"
            )

            # Look up networkx-specific guidance (falls back to matplotlib guidance)
            if not subject_guidance:
                if not hasattr(self, "_registry"):
                    from utils.subject_prompt_registry import SubjectPromptRegistry

                    self._registry = SubjectPromptRegistry()
                subject_guidance = self._registry.get_nonai_tool_prompt(
                    domain, diagram_type, "networkx"
                ) or self._registry.get_nonai_tool_prompt(
                    domain, diagram_type, "matplotlib"
                )

            # networkx renders via matplotlib pipeline
            return await self.claude_code_tool(
                domain=domain,
                diagram_type=diagram_type,
                tool_type="networkx",
                description=description,
                assignment_id=assignment_id,
                question_idx=question_idx,
                question_text=question_text,
                subject_guidance=subject_guidance,
            )
        except Exception as e:
            logger.error(f"Error in networkx_pathway_tool: {e}")
            return None

    async def imagen_fix_tool(
        self,
        image_bytes: bytes,
        issues: list,
        reason: str,
        original_description: str,
        assignment_id: str,
        question_idx: int,
        question_text: str = "",
    ) -> Dict[str, Any]:
        """
        Fix an existing Gemini diagram by sending it back with correction instructions.

        This sends the image + issues back to Gemini to fix only text/label/unit
        errors while preserving the diagram structure and layout.

        Args:
            image_bytes: The existing diagram PNG bytes
            issues: List of specific issues from the reviewer
            reason: The reviewer's reason for failure
            original_description: The original generation description
            assignment_id: Assignment ID for S3 upload
            question_idx: Question index for filename
            question_text: Full question text for context

        Returns:
            Diagram data dict with S3 info, or None on failure
        """
        try:
            logger.info(
                f"Executing imagen_fix_tool for question {question_idx} "
                f"(fixing {len(issues)} issues)..."
            )

            # Lazy load Google generator
            if self._google_generator is None:
                from utils.google_diagram_generator import GoogleDiagramGenerator

                self._google_generator = GoogleDiagramGenerator(
                    diagram_model=self.diagram_model
                )

            result = await self._google_generator.fix_diagram(
                image_bytes=image_bytes,
                issues=issues,
                reason=reason,
                original_description=original_description,
                question_text=question_text,
            )

            if not result or not result.get("image_bytes"):
                logger.warning(
                    f"Gemini fix returned no image for question {question_idx}"
                )
                return None

            fixed_bytes = result["image_bytes"]

            # Upload to S3
            diagram_data = await self.diagram_gen.upload_to_s3(
                fixed_bytes, assignment_id, question_idx
            )

            # Attach image_bytes for downstream review
            diagram_data["_image_bytes"] = fixed_bytes

            logger.info(
                f"Successfully fixed Gemini diagram for question {question_idx}: "
                f"{len(fixed_bytes)} bytes"
            )
            return diagram_data

        except Exception as e:
            logger.error(f"Error in imagen_fix_tool: {str(e)}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    async def tikz_tool(
        self,
        description: str,
        assignment_id: str,
        question_idx: int,
        question_text: str = "",
        subject_guidance: str = "",
    ) -> Dict[str, Any]:
        """
        Generate publication-quality diagram using general TikZ (LaTeX).

        Pipeline: Claude → TikZ LaTeX → pdflatex → pdf2image → PNG → S3
        """
        try:
            logger.info(f"Executing tikz_tool for question {question_idx}: {description[:100]}")

            if not hasattr(self, "_tikz_gen") or self._tikz_gen is None:
                from utils.tikz_generator import TikZGenerator
                self._tikz_gen = TikZGenerator()

            image_bytes = await self._tikz_gen.generate_diagram_png(
                question_text=question_text or description,
                diagram_description=description,
                subject_guidance=subject_guidance,
                output_dpi=300,
            )

            diagram_data = await self.diagram_gen.upload_to_s3(image_bytes, assignment_id, question_idx)
            diagram_data["_image_bytes"] = image_bytes
            logger.info(f"Successfully generated TikZ diagram: {description[:80]}")
            return diagram_data

        except Exception as e:
            logger.error(f"Error in tikz_tool: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    async def rdkit_tool(
        self,
        description: str,
        assignment_id: str,
        question_idx: int,
        question_text: str = "",
    ) -> Dict[str, Any]:
        """
        Generate 2D molecular structure diagram using RDKit.

        Pipeline: Claude → SMILES string → RDKit Draw.MolToImage → PNG → S3
        Falls back to claude_code_tool if RDKit is unavailable or SMILES is invalid.
        """
        try:
            logger.info(f"Executing rdkit_tool for question {question_idx}: {description[:100]}")

            try:
                from rdkit import Chem
                from rdkit.Chem import Draw
                from rdkit.Chem.Draw import rdMolDraw2D
            except ImportError:
                logger.warning("RDKit not installed — falling back to claude_code_tool")
                return await self.claude_code_tool(
                    domain="chemistry",
                    diagram_type="molecular_structure",
                    tool_type="matplotlib",
                    description=description,
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                    question_text=question_text,
                )

            # Ask Claude to provide the SMILES for the described molecule
            import os
            from anthropic import Anthropic
            client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
            smiles_response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                system=(
                    "You are a chemistry expert. Given a molecule description, return ONLY the "
                    "canonical SMILES string. No explanation, no markdown, no extra text."
                ),
                messages=[{"role": "user", "content": f"Molecule: {description}\n\nQuestion context: {question_text[:300]}"}],
            )
            smiles = smiles_response.content[0].text.strip()

            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                raise ValueError(f"Invalid SMILES generated: {smiles!r}")

            # Render at 600x600 with white background
            drawer = rdMolDraw2D.MolDraw2DCairo(600, 600)
            drawer.drawOptions().addStereoAnnotation = True
            drawer.DrawMolecule(mol)
            drawer.FinishDrawing()
            image_bytes = drawer.GetDrawingText()

            diagram_data = await self.diagram_gen.upload_to_s3(image_bytes, assignment_id, question_idx)
            diagram_data["_image_bytes"] = image_bytes
            logger.info(f"Successfully generated RDKit diagram (SMILES: {smiles[:60]})")
            return diagram_data

        except Exception as e:
            logger.error(f"Error in rdkit_tool: {str(e)} — falling back to claude_code_tool")
            return await self.claude_code_tool(
                domain="chemistry",
                diagram_type="molecular_structure",
                tool_type="matplotlib",
                description=description,
                assignment_id=assignment_id,
                question_idx=question_idx,
                question_text=question_text,
            )

    async def plotly_tool(
        self,
        description: str,
        assignment_id: str,
        question_idx: int,
        question_text: str = "",
        subject_guidance: str = "",
    ) -> Dict[str, Any]:
        """
        Generate 3D diagram using Plotly exported to PNG.

        Pipeline: Claude → Plotly Python code → execute → kaleido PNG export → S3
        Falls back to claude_code_tool (matplotlib) if Plotly/kaleido unavailable.
        """
        try:
            logger.info(f"Executing plotly_tool for question {question_idx}: {description[:100]}")

            try:
                import plotly  # noqa: F401
                import kaleido  # noqa: F401
            except ImportError:
                logger.warning("plotly/kaleido not installed — falling back to claude_code_tool")
                return await self.claude_code_tool(
                    domain="general",
                    diagram_type="3d_diagram",
                    tool_type="matplotlib",
                    description=description,
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                    question_text=question_text,
                    subject_guidance=subject_guidance,
                )

            # Ask Claude to generate Plotly code
            import os
            import tempfile
            import subprocess
            from anthropic import Anthropic
            client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

            guidance_section = f"\nDrawing instructions: {subject_guidance}" if subject_guidance else ""
            plotly_response = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=3000,
                system=(
                    "You are an expert Plotly diagram generator for educational content. "
                    "Generate complete Python code using plotly that creates a 3D diagram. "
                    "The code must save the figure to 'output.png' using: "
                    "fig.write_image('output.png', width=800, height=700, scale=2)\n"
                    "Return ONLY the Python code. No markdown, no explanation.\n"
                    "Do NOT include any computed answer values or formulas revealing the solution."
                ),
                messages=[{"role": "user", "content": (
                    f"Question: {question_text[:600]}\n"
                    f"Diagram: {description}"
                    f"{guidance_section}"
                )}],
            )
            code = plotly_response.content[0].text.strip()
            if code.startswith("```"):
                import re
                code = re.sub(r"^```[a-z]*\n?", "", code)
                code = re.sub(r"\n?```$", "", code).strip()

            # Validate syntax before executing; repair with AI if broken
            import ast
            for _attempt in range(2):
                try:
                    ast.parse(code)
                    break  # syntax OK
                except SyntaxError as syn_err:
                    if _attempt == 1:
                        raise RuntimeError(f"Plotly execution failed: {syn_err}")
                    logger.warning(f"Plotly code has syntax error, requesting AI repair: {syn_err}")
                    repair_response = client.messages.create(
                        model="claude-opus-4-5",
                        max_tokens=3000,
                        system=(
                            "You are an expert Python debugger. "
                            "Fix ONLY the syntax errors in the provided Python code. "
                            "Do not change logic or diagram content. "
                            "Return ONLY the corrected Python code. No markdown, no explanation."
                        ),
                        messages=[{"role": "user", "content": (
                            f"This Python code has a syntax error:\n{syn_err}\n\n"
                            f"Fix it:\n{code}"
                        )}],
                    )
                    fixed = repair_response.content[0].text.strip()
                    if fixed.startswith("```"):
                        import re
                        fixed = re.sub(r"^```[a-z]*\n?", "", fixed)
                        fixed = re.sub(r"\n?```$", "", fixed).strip()
                    code = fixed

            # Execute in a temp directory; retry once with AI repair on runtime error
            image_bytes: Optional[bytes] = None
            for _exec_attempt in range(2):
                with tempfile.TemporaryDirectory() as tmpdir:
                    output_path = os.path.join(tmpdir, "output.png")
                    run_code = code.replace("'output.png'", f"'{output_path}'").replace('"output.png"', f"'{output_path}'")
                    script_path = os.path.join(tmpdir, "plot.py")
                    with open(script_path, "w", encoding="utf-8") as f:
                        f.write(run_code)

                    result = subprocess.run(
                        ["python", script_path],
                        capture_output=True, text=True, timeout=60
                    )
                    if result.returncode != 0:
                        exec_error = result.stderr[-600:] or result.stdout[-600:]
                        if _exec_attempt == 1:
                            raise RuntimeError(f"Plotly execution failed: {exec_error}")
                        logger.warning(f"Plotly execution failed (attempt 1), requesting AI repair: {exec_error[:200]}")
                        repair_response = client.messages.create(
                            model="claude-opus-4-5",
                            max_tokens=3000,
                            system=(
                                "You are an expert Python debugger. "
                                "Fix the runtime error in the provided Python code. "
                                "Do not change the diagram logic or content. "
                                "Return ONLY the corrected Python code. No markdown, no explanation."
                            ),
                            messages=[{"role": "user", "content": (
                                f"This Python code raised a runtime error:\n{exec_error}\n\n"
                                f"Fix it:\n{code}"
                            )}],
                        )
                        fixed = repair_response.content[0].text.strip()
                        if fixed.startswith("```"):
                            import re as _re
                            fixed = _re.sub(r"^```[a-z]*\n?", "", fixed)
                            fixed = _re.sub(r"\n?```$", "", fixed).strip()
                        code = fixed
                        continue

                    if not os.path.isfile(output_path):
                        raise RuntimeError("Plotly code ran but produced no output.png")

                    with open(output_path, "rb") as f:
                        image_bytes = f.read()
                    break

            diagram_data = await self.diagram_gen.upload_to_s3(image_bytes, assignment_id, question_idx)
            diagram_data["_image_bytes"] = image_bytes
            logger.info(f"Successfully generated Plotly 3D diagram: {description[:80]}")
            return diagram_data

        except Exception as e:
            logger.error(f"Error in plotly_tool: {str(e)} — falling back to claude_code_tool")
            return await self.claude_code_tool(
                domain="general",
                diagram_type="3d_diagram",
                tool_type="matplotlib",
                description=description,
                assignment_id=assignment_id,
                question_idx=question_idx,
                question_text=question_text,
                subject_guidance=subject_guidance,
            )

    async def execute_tool_call(
        self,
        tool_name: str,
        tool_arguments: Dict[str, Any],
        assignment_id: str,
        question_idx: int,
        question_text: str = "",
    ) -> Dict[str, Any]:
        """
        Execute a tool call from the agent.

        Args:
            tool_name: Name of the tool to execute
            tool_arguments: Arguments for the tool
            assignment_id: Assignment ID for S3 upload
            question_idx: Question index
            question_text: Full question text (for Claude code generation)

        Returns:
            Diagram data dict or None if execution fails
        """
        try:
            if tool_name == "claude_code_tool":
                return await self.claude_code_tool(
                    domain=tool_arguments.get("domain", "general"),
                    diagram_type=tool_arguments.get("diagram_type", "diagram"),
                    tool_type=tool_arguments.get("tool_type", "matplotlib"),
                    description=tool_arguments.get("description"),
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                    question_text=question_text,
                    subject_guidance=tool_arguments.get("subject_guidance", ""),
                    reference_image_bytes=tool_arguments.get("reference_image_bytes"),
                )
            elif tool_name == "matplotlib_tool":
                return await self.matplotlib_tool(
                    code=tool_arguments.get("code"),
                    description=tool_arguments.get("description"),
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                )
            elif tool_name == "networkx_tool":
                return await self.networkx_tool(
                    code=tool_arguments.get("code"),
                    description=tool_arguments.get("description"),
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                )
            elif tool_name == "schemdraw_tool":
                return await self.schemdraw_tool(
                    code=tool_arguments.get("code"),
                    description=tool_arguments.get("description"),
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                )
            elif tool_name == "circuitikz_tool":
                return await self.circuitikz_tool(
                    description=tool_arguments.get("description"),
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                    question_text=question_text,
                    subject_context=tool_arguments.get("subject_context", ""),
                )
            elif tool_name == "svg_circuit_tool":
                return await self.svg_circuit_tool(
                    description=tool_arguments.get("description"),
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                    question_text=question_text,
                    subject_context=tool_arguments.get("subject_context", ""),
                )
            elif tool_name == "dalle_tool":
                return await self.dalle_tool(
                    prompt=tool_arguments.get("prompt"),
                    description=tool_arguments.get("description"),
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                )
            elif tool_name == "imagen_tool":
                return await self.imagen_tool(
                    description=tool_arguments.get("description", ""),
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                    question_text=question_text,
                    subject=tool_arguments.get("subject", "electrical"),
                )
            elif tool_name == "neurokit2_tool":
                return await self.neurokit2_tool(
                    domain=tool_arguments.get("domain", "physiology"),
                    diagram_type=tool_arguments.get("diagram_type", "action_potential"),
                    description=tool_arguments.get("description", ""),
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                    question_text=question_text,
                    subject_guidance=tool_arguments.get("subject_guidance", ""),
                )
            elif tool_name == "scipy_curve_tool":
                return await self.scipy_curve_tool(
                    domain=tool_arguments.get("domain", "pharmacology"),
                    diagram_type=tool_arguments.get("diagram_type", "dose_response"),
                    description=tool_arguments.get("description", ""),
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                    question_text=question_text,
                    subject_guidance=tool_arguments.get("subject_guidance", ""),
                )
            elif tool_name == "networkx_pathway_tool":
                return await self.networkx_pathway_tool(
                    domain=tool_arguments.get("domain", "biochemistry"),
                    diagram_type=tool_arguments.get(
                        "diagram_type", "metabolic_pathway"
                    ),
                    description=tool_arguments.get("description", ""),
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                    question_text=question_text,
                    subject_guidance=tool_arguments.get("subject_guidance", ""),
                )
            elif tool_name == "tikz_tool":
                return await self.tikz_tool(
                    description=tool_arguments.get("description"),
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                    question_text=question_text,
                    subject_guidance=tool_arguments.get("subject_guidance", ""),
                )
            elif tool_name == "rdkit_tool":
                return await self.rdkit_tool(
                    description=tool_arguments.get("description"),
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                    question_text=question_text,
                )
            elif tool_name == "plotly_tool":
                return await self.plotly_tool(
                    description=tool_arguments.get("description"),
                    assignment_id=assignment_id,
                    question_idx=question_idx,
                    question_text=question_text,
                    subject_guidance=tool_arguments.get("subject_guidance", ""),
                )
            else:
                logger.error(f"Unknown tool: {tool_name}")
                return None

        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {str(e)}")
            return None
