"""
Diagram Generation Tools for Multi-Agent System

These tools are called by the DiagramAnalysisAgent to generate diagrams.
Each tool renders a diagram and uploads it to S3.
"""

import asyncio
from typing import Dict, Any
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
            "description": "RECOMMENDED: Use Claude to generate diagram code for any STEM domain. Works for: physics, mechanical, CS data structures, mathematics, chemistry, civil, biology — any technical diagram that is NOT a circuit schematic. Claude generates clean matplotlib/schemdraw/networkx code executed for technical accuracy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain: physics, electrical, computer_science, mathematics, chemistry, biology, mechanical, civil, or general",
                    },
                    "diagram_type": {
                        "type": "string",
                        "description": "Specific diagram type: manometer, circuit, free_body_diagram, graph, tree, etc.",
                    },
                    "tool_type": {
                        "type": "string",
                        "enum": ["matplotlib", "schemdraw", "networkx"],
                        "description": "Which library Claude should generate code for: matplotlib (plots, physics, general), schemdraw (circuits), networkx (graphs/trees)",
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
            "name": "svg_circuit_tool",
            "description": "Generate professional circuit/schematic diagrams via Claude SVG. Best for: electrical circuits, digital logic gates, ALU schematics, gate-level computer engineering diagrams. Supports IEEE block-level gate symbols (AND, OR, NOT, NAND, NOR, XOR) and CMOS transistor-level circuits with vertical VDD/PMOS/NMOS/GND layouts. Produces clean orthogonal wiring with standard component symbols. Preferred over schemdraw_tool for all circuit diagrams.",
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

            # Generate code using Claude
            code = await self.claude_generator.generate_diagram_code(
                question_text=question_text or description,
                domain=domain,
                diagram_type=diagram_type,
                tool_type=tool_type,
                subject_guidance=subject_guidance,
            )

            logger.info(f"Claude generated {len(code)} characters of {tool_type} code")
            logger.debug(f"Generated code:\n{code}")

            # Execute the generated code using appropriate tool
            if tool_type == "matplotlib":
                image_bytes = await self.diagram_gen.render_matplotlib(code)
            elif tool_type == "schemdraw":
                image_bytes = await self.diagram_gen.render_schemdraw(code)
            elif tool_type == "networkx":
                image_bytes = await self.diagram_gen.render_networkx(code)
            else:
                raise ValueError(f"Unsupported tool_type: {tool_type}")

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

    async def svg_circuit_tool(
        self,
        description: str,
        assignment_id: str,
        question_idx: int,
        question_text: str = "",
        subject_context: str = "",
    ) -> Dict[str, Any]:
        """
        Generate professional circuit diagram using Claude SVG generation.

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
            if not hasattr(self, '_svg_circuit_gen') or self._svg_circuit_gen is None:
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
            diagram_data['_image_bytes'] = image_bytes

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
                self._google_generator = GoogleDiagramGenerator(diagram_model=self.diagram_model)

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
            diagram_data['_image_bytes'] = image_bytes

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
                self._google_generator = GoogleDiagramGenerator(diagram_model=self.diagram_model)

            result = await self._google_generator.fix_diagram(
                image_bytes=image_bytes,
                issues=issues,
                reason=reason,
                original_description=original_description,
                question_text=question_text,
            )

            if not result or not result.get("image_bytes"):
                logger.warning(f"Gemini fix returned no image for question {question_idx}")
                return None

            fixed_bytes = result["image_bytes"]

            # Upload to S3
            diagram_data = await self.diagram_gen.upload_to_s3(
                fixed_bytes, assignment_id, question_idx
            )

            # Attach image_bytes for downstream review
            diagram_data['_image_bytes'] = fixed_bytes

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

    async def execute_tool_call(
        self,
        tool_name: str,
        tool_arguments: Dict[str, Any],
        assignment_id: str,
        question_idx: int,
        question_text: str = ""
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
            else:
                logger.error(f"Unknown tool: {tool_name}")
                return None

        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {str(e)}")
            return None
