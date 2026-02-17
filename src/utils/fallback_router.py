"""
SubjectSpecificFallbackRouter — routes nonai diagram requests to the correct tool
based on (domain, diagram_type) classification.

Replaces the previous hardcoded "always use svg_circuit_tool or claude_code_tool" logic.
"""

from typing import Tuple, Optional
from controllers.config import logger


# Maps (domain, diagram_type) → (tool_name, tool_type)
# tool_type is the library hint passed to claude_code_tool
_FALLBACK_TOOL_MAP = {
    # ── Electrical ──────────────────────────────────────────────────────────
    ("electrical", "circuit_schematic"):    ("svg_circuit_tool", "svg"),
    ("electrical", "bode_plot"):            ("claude_code_tool", "matplotlib"),
    ("electrical", "iv_curve"):             ("claude_code_tool", "matplotlib"),
    ("electrical", "waveform"):             ("claude_code_tool", "matplotlib"),
    ("electrical", "block_diagram"):        ("claude_code_tool", "matplotlib"),
    ("electrical", "timing_diagram"):       ("claude_code_tool", "matplotlib"),

    # ── Mechanical ──────────────────────────────────────────────────────────
    ("mechanical", "free_body_diagram"):    ("claude_code_tool", "matplotlib"),
    ("mechanical", "beam_diagram"):         ("claude_code_tool", "matplotlib"),
    ("mechanical", "truss_diagram"):        ("claude_code_tool", "matplotlib"),
    ("mechanical", "stress_strain_curve"):  ("claude_code_tool", "matplotlib"),
    ("mechanical", "pv_diagram"):           ("claude_code_tool", "matplotlib"),
    ("mechanical", "fluid_flow"):           ("claude_code_tool", "matplotlib"),
    ("mechanical", "mechanism_linkage"):    ("claude_code_tool", "matplotlib"),

    # ── Computer Science ────────────────────────────────────────────────────
    ("cs", "binary_tree"):                  ("claude_code_tool", "networkx"),
    ("cs", "linked_list"):                  ("claude_code_tool", "matplotlib"),
    ("cs", "graph_network"):               ("claude_code_tool", "networkx"),
    ("cs", "sorting_visualization"):        ("claude_code_tool", "matplotlib"),
    ("cs", "flowchart"):                    ("claude_code_tool", "matplotlib"),
    ("cs", "automata_fsm"):                 ("claude_code_tool", "networkx"),
    ("cs", "stack_queue"):                  ("claude_code_tool", "matplotlib"),
    ("cs", "hash_table"):                   ("claude_code_tool", "matplotlib"),

    # ── Civil ───────────────────────────────────────────────────────────────
    ("civil", "truss_frame"):               ("claude_code_tool", "matplotlib"),
    ("civil", "cross_section"):             ("claude_code_tool", "matplotlib"),
    ("civil", "retaining_wall"):            ("claude_code_tool", "matplotlib"),
    ("civil", "flow_network"):              ("claude_code_tool", "networkx"),
    ("civil", "contour_map"):               ("claude_code_tool", "matplotlib"),
    ("civil", "soil_profile"):              ("claude_code_tool", "matplotlib"),

    # ── Mathematics ─────────────────────────────────────────────────────────
    ("math", "function_plot"):              ("claude_code_tool", "matplotlib"),
    ("math", "geometric_construction"):     ("claude_code_tool", "matplotlib"),
    ("math", "vector_field"):               ("claude_code_tool", "matplotlib"),
    ("math", "3d_surface"):                 ("claude_code_tool", "matplotlib"),
    ("math", "number_line"):                ("claude_code_tool", "matplotlib"),
    ("math", "coordinate_geometry"):        ("claude_code_tool", "matplotlib"),
    ("math", "matrix_visualization"):       ("claude_code_tool", "matplotlib"),

    # ── Physics ─────────────────────────────────────────────────────────────
    ("physics", "ray_diagram"):             ("claude_code_tool", "matplotlib"),
    ("physics", "field_lines"):             ("claude_code_tool", "matplotlib"),
    ("physics", "wave_diagram"):            ("claude_code_tool", "matplotlib"),
    ("physics", "optics_setup"):            ("claude_code_tool", "matplotlib"),
    ("physics", "energy_level_diagram"):    ("claude_code_tool", "matplotlib"),
    ("physics", "phase_diagram"):           ("claude_code_tool", "matplotlib"),
    ("physics", "spring_mass"):             ("claude_code_tool", "matplotlib"),
    ("physics", "pendulum"):                ("claude_code_tool", "matplotlib"),

    # ── Chemistry ───────────────────────────────────────────────────────────
    ("chemistry", "molecular_structure"):   ("claude_code_tool", "matplotlib"),
    ("chemistry", "reaction_mechanism"):    ("claude_code_tool", "matplotlib"),
    ("chemistry", "lab_apparatus"):         ("claude_code_tool", "matplotlib"),
    ("chemistry", "titration_curve"):       ("claude_code_tool", "matplotlib"),
    ("chemistry", "orbital_diagram"):       ("claude_code_tool", "matplotlib"),
    ("chemistry", "phase_diagram"):         ("claude_code_tool", "matplotlib"),
    ("chemistry", "chromatography"):        ("claude_code_tool", "matplotlib"),

    # ── Computer Engineering ─────────────────────────────────────────────────
    ("computer_eng", "cpu_block_diagram"):  ("claude_code_tool", "matplotlib"),
    ("computer_eng", "memory_hierarchy"):   ("claude_code_tool", "matplotlib"),
    ("computer_eng", "pipeline_diagram"):   ("claude_code_tool", "matplotlib"),
    ("computer_eng", "alu_circuit"):        ("svg_circuit_tool", "svg"),
    ("computer_eng", "logic_circuit"):      ("svg_circuit_tool", "svg"),
    ("computer_eng", "isa_timing"):         ("claude_code_tool", "matplotlib"),
    ("computer_eng", "cache_organization"): ("claude_code_tool", "matplotlib"),
}

# Default fallback for unrecognized domain/diagram_type
_DEFAULT_ROUTE = ("claude_code_tool", "matplotlib")


class SubjectSpecificFallbackRouter:
    """
    Routes nonai diagram generation to the correct tool based on domain + diagram_type.

    Replaces the previous hardcoded logic that always defaulted to svg_circuit_tool
    or claude_code_tool without subject-awareness.
    """

    def __init__(self):
        from utils.subject_prompt_registry import SubjectPromptRegistry
        self.registry = SubjectPromptRegistry()

    def route(
        self,
        domain: str,
        diagram_type: str,
        description: str,
        question_text: str = "",
    ) -> Tuple[str, str, str, str]:
        """
        Determine the correct tool and tool arguments for a given domain/diagram_type.

        Args:
            domain: Classified domain (e.g., "mechanical")
            diagram_type: Classified diagram type (e.g., "free_body_diagram")
            description: The agent-generated description of the diagram
            question_text: Full question text for context

        Returns:
            Tuple of (tool_name, tool_type, subject_guidance, description)
            - tool_name: "claude_code_tool" or "svg_circuit_tool"
            - tool_type: "matplotlib", "networkx", "svg", etc.
            - subject_guidance: Subject-specific generation guidance string
            - description: The original description (passed through)
        """
        key = (domain, diagram_type)
        tool_name, tool_type = _FALLBACK_TOOL_MAP.get(key, _DEFAULT_ROUTE)

        # Get subject-specific generation guidance
        subject_guidance = self.registry.get_nonai_tool_prompt(
            domain, diagram_type, tool_type
        )

        logger.info(
            f"FallbackRouter: ({domain}, {diagram_type}) → {tool_name} [{tool_type}]"
        )

        return tool_name, tool_type, subject_guidance, description

    def build_tool_arguments(
        self,
        domain: str,
        diagram_type: str,
        description: str,
        question_text: str = "",
    ) -> Tuple[str, dict]:
        """
        Build the complete tool_name + tool_arguments dict for execute_tool_call.

        Args:
            domain: Classified domain
            diagram_type: Classified diagram type
            description: Agent-generated description
            question_text: Full question text

        Returns:
            Tuple of (tool_name, tool_arguments_dict)
        """
        tool_name, tool_type, subject_guidance, desc = self.route(
            domain, diagram_type, description, question_text
        )

        if tool_name == "svg_circuit_tool":
            # For SVG tool: prepend subject context to description
            enhanced_desc = description
            if subject_guidance:
                enhanced_desc = f"{subject_guidance}\n\n{description}"
            return tool_name, {
                "description": enhanced_desc,
                "subject_context": subject_guidance,
            }
        else:
            # For claude_code_tool: pass domain, type, tool_type, and enhanced description
            return tool_name, {
                "domain": domain,
                "diagram_type": diagram_type,
                "tool_type": tool_type,
                "description": description,
                "subject_guidance": subject_guidance,
            }

    def get_preferred_tool_for_domain(
        self, domain: str, diagram_type: str
    ) -> Optional[str]:
        """Returns just the tool name for a given domain/diagram_type."""
        key = (domain, diagram_type)
        tool_name, _ = _FALLBACK_TOOL_MAP.get(key, _DEFAULT_ROUTE)
        return tool_name
