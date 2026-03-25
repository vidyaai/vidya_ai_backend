"""
DomainRouter — lightweight subject/diagram-type classifier.

Runs BEFORE diagram generation to classify the question domain and diagram type.
Uses gpt-4o-mini for speed and cost efficiency.
"""

import json
from typing import Dict, Any, Optional
from openai import OpenAI
from controllers.config import logger


# Diagram types that work better with code tools than AI image generation.
# These will override engine=ai → engine=nonai at the per-question level.
_CODE_BETTER_TYPES = frozenset(
    {
        "bode_plot",
        "iv_curve",
        "waveform",
        "timing_diagram",
        "stress_strain_curve",
        "pv_diagram",
        "binary_tree",
        "linked_list",
        "graph_network",
        "sorting_visualization",
        "stack_queue",
        "hash_table",
        "automata_fsm",
        "flowchart",
        "function_plot",
        "3d_surface",
        "number_line",
        "matrix_visualization",
        "titration_curve",
        "chromatography",
        "isa_timing",
        "cache_organization",
        "sequential_circuit",
        "flip_flop_circuit",
        "counter_circuit",
        "shift_register",
        "fsm_diagram",
        "cdc_diagram",
        "circuit_with_timing",
        # Medical sciences — precise scientific plots, not AI-generatable
        "action_potential",
        "cardiac_loop",
        "feedback_loop",
        "pressure_volume_loop",
        "metabolic_pathway",
        "enzyme_kinetics",
        "dose_response",
        "pharmacokinetics",
        "disease_progression",
        "infection_cycle",
        "growth_curve",
    }
)

_CLASSIFICATION_PROMPT = """You are a subject-domain classifier for educational diagrams.

Given a question, classify it into ONE of these 8 domains and select the most specific diagram type.

DOMAINS AND DIAGRAM TYPES:

electrical: circuit_schematic, bode_plot, iv_curve, waveform, block_diagram, timing_diagram, sequential_circuit, flip_flop_circuit, counter_circuit, shift_register, fsm_diagram, cdc_diagram, circuit_with_timing
mechanical: free_body_diagram, beam_diagram, truss_diagram, stress_strain_curve, pv_diagram, fluid_flow, mechanism_linkage
cs: binary_tree, linked_list, graph_network, sorting_visualization, flowchart, automata_fsm, stack_queue, hash_table
civil: truss_frame, cross_section, retaining_wall, flow_network, contour_map, soil_profile
math: function_plot, geometric_construction, vector_field, 3d_surface, number_line, coordinate_geometry, matrix_visualization
physics: ray_diagram, field_lines, wave_diagram, optics_setup, energy_level_diagram, phase_diagram, spring_mass, pendulum
chemistry: molecular_structure, reaction_mechanism, lab_apparatus, titration_curve, orbital_diagram, phase_diagram, chromatography
computer_eng: cpu_block_diagram, memory_hierarchy, pipeline_diagram, alu_circuit, logic_circuit, isa_timing, cache_organization
anatomy: anatomical_diagram, cross_section, histology
physiology: action_potential, feedback_loop, pressure_volume_loop, cardiac_loop
biochemistry: metabolic_pathway, enzyme_kinetics
pharmacology: dose_response, pharmacokinetics
pathology: disease_progression, histopathology
microbiology: bacterial_structure, infection_cycle, growth_curve

COMPLEXITY:
- simple: single concept, few components
- moderate: multiple components with interactions
- complex: many components, complex interactions

AI_SUITABLE (whether Gemini image gen works well — True for spatial/structural, False for precise mathematical plots and data structures):
- True: circuit_schematic, free_body_diagram, truss_diagram, ray_diagram, molecular_structure, cpu_block_diagram, lab_apparatus, mechanism_linkage, optics_setup, field_lines, energy_level_diagram, wave_diagram, spring_mass, pendulum, truss_frame, cross_section, retaining_wall, beam_diagram, orbital_diagram, reaction_mechanism, pipeline_diagram, memory_hierarchy, logic_circuit, alu_circuit, block_diagram, geometric_construction, fluid_flow, anatomical_diagram, histology, bacterial_structure
- False: all plots (bode_plot, iv_curve, function_plot, stress_strain_curve, titration_curve, pv_diagram, titration_curve), data structures (binary_tree, linked_list, graph_network, sorting_visualization, stack_queue, hash_table), timing_diagram, automata_fsm, flowchart, 3d_surface, number_line, matrix_visualization, isa_timing, cache_organization, waveform, chromatography, sequential_circuit, flip_flop_circuit, counter_circuit, shift_register, fsm_diagram, cdc_diagram, circuit_with_timing, action_potential, feedback_loop, pressure_volume_loop, cardiac_loop, metabolic_pathway, enzyme_kinetics, dose_response, pharmacokinetics, disease_progression, histopathology, infection_cycle, growth_curve

PREFERRED_TOOL (for nonai path):
- circuitikz: circuit_schematic, sequential_circuit, flip_flop_circuit, counter_circuit, shift_register, cdc_diagram (best for ALL electrical circuits with precise pin labels)
- neurokit2: action_potential, cardiac_loop (scipy-based physiological signal waveforms)
- scipy: dose_response, pharmacokinetics, enzyme_kinetics, pressure_volume_loop, growth_curve (scipy/numpy mathematical curves)
- networkx_pathway: metabolic_pathway, feedback_loop, infection_cycle, disease_progression (directed flow graphs)
- matplotlib: most diagram types, timing_diagram, waveform, bode_plot, iv_curve, fsm_diagram, and medical types not covered above
- networkx: binary_tree, linked_list, graph_network, automata_fsm, stack_queue, hash_table
- graphviz: flowchart, automata_fsm
- circuit_with_timing: Use circuitikz for the circuit + matplotlib for the timing → preferred_tool = circuitikz (primary)

IMPORTANT CLASSIFICATION RULES:
- If a question involves flip-flops, shift registers, counters, or sequential logic with gates → diagram_type = sequential_circuit or flip_flop_circuit
- If a question asks for BOTH a circuit diagram AND a timing/waveform diagram → diagram_type = circuit_with_timing
- circuit_with_timing means: the circuit schematic uses circuitikz AND the timing waveform uses matplotlib (two outputs)
- For questions about D flip-flops, JK flip-flops, SR latches etc → flip_flop_circuit or sequential_circuit, NOT block_diagram
- For questions about shift registers → shift_register, NOT block_diagram

Respond with ONLY valid JSON — no markdown, no explanation:
{
  "domain": "<one of the 8 domain IDs>",
  "diagram_type": "<specific type from the domain's list>",
  "complexity": "simple|moderate|complex",
  "ai_suitable": true|false,
  "preferred_tool": "matplotlib|networkx|graphviz|svg"
}"""


class DomainRouter:
    """
    Lightweight classifier that runs before diagram generation.

    Classifies question domain, diagram type, complexity, and routing hints.
    Uses gpt-4o-mini for speed and cost efficiency.
    """

    def __init__(self, client: Optional[OpenAI] = None):
        self.client = client or OpenAI()
        self.model = "gpt-4o-mini"

    def classify(
        self,
        question_text: str,
        subject_hint: str = "",
    ) -> Dict[str, Any]:
        """
        Classify a question for diagram routing.

        Args:
            question_text: The full question text
            subject_hint: Optional subject from assignment metadata (may be empty)

        Returns:
            Dict with keys: domain, diagram_type, complexity, ai_suitable, preferred_tool
        """
        try:
            hint_section = (
                f"\nSubject hint from assignment metadata: {subject_hint}\n"
                if subject_hint
                else ""
            )
            user_message = f"{hint_section}Question: {question_text[:600]}"

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _CLASSIFICATION_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.0,
                max_tokens=150,
            )

            raw = response.choices[0].message.content.strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            result = json.loads(raw)

            # Validate required keys with fallbacks
            domain = result.get(
                "domain", self._infer_domain(question_text, subject_hint)
            )
            diagram_type = result.get("diagram_type", "block_diagram")
            complexity = result.get("complexity", "moderate")
            ai_suitable = result.get("ai_suitable", True)
            preferred_tool = result.get("preferred_tool", "matplotlib")

            logger.info(
                f"DomainRouter classified: domain={domain}, type={diagram_type}, "
                f"complexity={complexity}, ai_suitable={ai_suitable}, tool={preferred_tool}"
            )

            return {
                "domain": domain,
                "diagram_type": diagram_type,
                "complexity": complexity,
                "ai_suitable": ai_suitable,
                "preferred_tool": preferred_tool,
            }

        except Exception as e:
            logger.warning(f"DomainRouter classification failed: {e}, using fallback")
            return self._fallback_classification(question_text, subject_hint)

    def should_override_to_nonai(self, diagram_type: str) -> bool:
        """
        Returns True if this diagram type should always use code tools
        even when engine=ai is requested.
        """
        return diagram_type in _CODE_BETTER_TYPES

    def _infer_domain(self, question_text: str, subject_hint: str) -> str:
        """Simple keyword-based domain inference as fallback."""
        q = question_text.lower()
        hint = subject_hint.lower()

        if "electrical" in hint or any(
            kw in q
            for kw in [
                "circuit",
                "cmos",
                "mosfet",
                "transistor",
                "amplifier",
                "resistor",
                "capacitor",
                "voltage",
                "current",
                "inverter",
                "nand",
                "nor",
                "vdd",
                "drain",
                "source",
                "op-amp",
                "bode",
                "iv curve",
                "flip-flop",
                "flip flop",
                "d flip",
                "jk flip",
                "sr latch",
                "shift register",
                "counter",
                "sequential",
                "clock edge",
                "rising edge",
                "falling edge",
                "timing diagram",
                "waveform",
                "combinational logic",
                "and gate",
                "or gate",
                "xor gate",
                "mux",
                "demux",
                "decoder",
                "encoder",
                "alu",
                "register file",
            ]
        ):
            return "electrical"
        if "computer" in hint or any(
            kw in q
            for kw in [
                "cpu",
                "alu",
                "pipeline",
                "cache",
                "register",
                "instruction",
                "logic gate",
                "memory hierarchy",
                "isa",
                "risc",
            ]
        ):
            return "computer_eng"
        if (
            "cs" in hint
            or "computer science" in hint
            or any(
                kw in q
                for kw in [
                    "binary tree",
                    "linked list",
                    "graph",
                    "bst",
                    "sorting",
                    "algorithm",
                    "stack",
                    "queue",
                    "hash",
                    "automata",
                    "fsm",
                    "flowchart",
                ]
            )
        ):
            return "cs"
        if "mechanical" in hint or any(
            kw in q
            for kw in [
                "force",
                "beam",
                "truss",
                "free body",
                "stress",
                "strain",
                "moment",
                "torque",
                "mechanism",
                "fluid flow",
            ]
        ):
            return "mechanical"
        if "civil" in hint or any(
            kw in q
            for kw in [
                "retaining wall",
                "cross section",
                "contour",
                "soil",
                "structural frame",
                "reinforced concrete",
            ]
        ):
            return "civil"
        if "math" in hint or any(
            kw in q
            for kw in [
                "function plot",
                "integral",
                "derivative",
                "matrix",
                "polynomial",
                "eigenvalue",
                "vector field",
                "3d surface",
                "geometric construction",
                "number line",
            ]
        ):
            return "math"
        if "physics" in hint or any(
            kw in q
            for kw in [
                "ray diagram",
                "optics",
                "lens",
                "mirror",
                "field lines",
                "wave",
                "energy level",
                "phase diagram",
                "spring",
                "pendulum",
                "refraction",
                "reflection",
            ]
        ):
            return "physics"
        # ── Medical sciences — checked BEFORE chemistry so that:
        #    1. "biochemistry" hint is not caught by "chemistry" substring check
        #    2. "anatomical" text is not caught by chemistry's "atom" keyword
        if "anatomy" in hint or any(
            kw in q
            for kw in [
                "anatomical",
                "anatomy",
                "organ",
                "bone",
                "tissue",
                "muscle",
                "nerve",
                "histology",
                "cross-section",
                "sagittal",
                "coronal",
                "transverse section",
                "ligament",
                "tendon",
            ]
        ):
            return "anatomy"
        if "physiology" in hint or any(
            kw in q
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
                "homeostasis",
                "feedback loop",
                "cardiac output",
                "stroke volume",
                "heart rate",
                "renal physiology",
            ]
        ):
            return "physiology"
        if "biochemistry" in hint or any(
            kw in q
            for kw in [
                "metabolic pathway",
                "glycolysis",
                "krebs cycle",
                "citric acid cycle",
                "electron transport",
                "enzyme kinetics",
                "michaelis",
                "vmax",
                "km",
                "metabolite",
                "atp synthesis",
                "nadh",
                "coenzyme",
                "biochemical",
            ]
        ):
            return "biochemistry"
        if "pharmacology" in hint or any(
            kw in q
            for kw in [
                "dose-response",
                "dose response",
                "ec50",
                "ed50",
                "pharmacokinetics",
                "pharmacodynamics",
                "plasma concentration",
                "bioavailability",
                "half-life",
                "agonist",
                "antagonist",
                "receptor binding",
                "therapeutic index",
            ]
        ):
            return "pharmacology"
        if "pathology" in hint or any(
            kw in q
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
                "malignant",
                "benign",
            ]
        ):
            return "pathology"
        if "microbiology" in hint or any(
            kw in q
            for kw in [
                "bacterial",
                "bacteria",
                "gram stain",
                "gram-positive",
                "gram-negative",
                "infection cycle",
                "replication cycle",
                "pathogen",
                "virulence",
                "antibiotic",
                "antimicrobial",
                "growth curve",
                "colony forming",
            ]
        ):
            return "microbiology"
        if "chemistry" in hint or any(
            kw in q
            for kw in [
                "molecular",
                "molecule",
                "atom",
                "bond",
                "reaction mechanism",
                "lab apparatus",
                "titration",
                "orbital",
                "smiles",
                "rdkit",
            ]
        ):
            return "chemistry"
        return "electrical"  # safe default for STEM assignments

    def _fallback_classification(
        self, question_text: str, subject_hint: str
    ) -> Dict[str, Any]:
        """Returns a safe fallback classification."""
        domain = self._infer_domain(question_text, subject_hint)
        q = question_text.lower()

        # Determine diagram type and tool from keywords
        diagram_type = "block_diagram"
        preferred_tool = "matplotlib"
        ai_suitable = True

        if domain == "electrical":
            # Check for sequential / flip-flop circuits
            _seq_kws = [
                "flip-flop",
                "flip flop",
                "shift register",
                "counter",
                "d flip",
                "jk flip",
                "sr latch",
                "sequential",
            ]
            _timing_kws = [
                "timing diagram",
                "waveform",
                "clock cycle",
                "input waveform",
            ]
            has_circuit = any(kw in q for kw in _seq_kws + ["circuit", "gate", "logic"])
            has_timing = any(kw in q for kw in _timing_kws)

            if has_circuit and has_timing:
                diagram_type = "circuit_with_timing"
                preferred_tool = "circuitikz"
                ai_suitable = False
            elif any(kw in q for kw in _seq_kws):
                diagram_type = "sequential_circuit"
                preferred_tool = "circuitikz"
                ai_suitable = False
            elif any(
                kw in q
                for kw in [
                    "circuit",
                    "mosfet",
                    "cmos",
                    "transistor",
                    "op-amp",
                    "amplifier",
                    "resistor",
                ]
            ):
                diagram_type = "circuit_schematic"
                preferred_tool = "circuitikz"
                ai_suitable = False
            elif has_timing:
                diagram_type = "timing_diagram"
                preferred_tool = "matplotlib"
                ai_suitable = False

        elif domain in ("anatomy", "physiology", "biochemistry", "pharmacology", "pathology", "microbiology"):
            # Medical sciences: all plots use matplotlib; structural diagrams use imagen
            _medical_type_map = {
                "anatomy": ("anatomical_diagram", True),  # structural → ai_suitable
                "physiology": ("action_potential", False),
                "biochemistry": ("metabolic_pathway", False),
                "pharmacology": ("dose_response", False),
                "pathology": ("disease_progression", False),
                "microbiology": ("bacterial_structure", True),  # structural → ai_suitable
            }
            _q = q
            # Refine diagram type based on keywords
            if domain == "anatomy":
                if any(kw in _q for kw in ["histology", "histological", "microscopy", "slide"]):
                    diagram_type = "histology"
                    ai_suitable = True
                elif any(kw in _q for kw in ["cross section", "cross-section", "transverse", "sagittal", "coronal"]):
                    diagram_type = "cross_section"
                    ai_suitable = True
                else:
                    diagram_type = "anatomical_diagram"
                    ai_suitable = True
            elif domain == "physiology":
                if any(kw in _q for kw in ["pressure", "volume", "p-v loop", "pv loop", "cardiac loop"]):
                    diagram_type = "pressure_volume_loop"
                elif any(kw in _q for kw in ["feedback", "homeostasis", "set point"]):
                    diagram_type = "feedback_loop"
                else:
                    diagram_type = "action_potential"
                ai_suitable = False
            elif domain == "biochemistry":
                if any(kw in _q for kw in ["kinetics", "michaelis", "vmax", "km"]):
                    diagram_type = "enzyme_kinetics"
                else:
                    diagram_type = "metabolic_pathway"
                ai_suitable = False
            elif domain == "pharmacology":
                if any(kw in _q for kw in ["concentration", "time", "plasma", "half-life", "t½", "cmax", "auc"]):
                    diagram_type = "pharmacokinetics"
                else:
                    diagram_type = "dose_response"
                ai_suitable = False
            elif domain == "pathology":
                if any(kw in _q for kw in ["histopathology", "microscopy", "biopsy", "slide"]):
                    diagram_type = "histopathology"
                    ai_suitable = True
                else:
                    diagram_type = "disease_progression"
                    ai_suitable = False
            elif domain == "microbiology":
                if any(kw in _q for kw in ["growth curve", "growth rate", "bacterial growth", "lag phase", "log phase"]):
                    diagram_type = "growth_curve"
                    ai_suitable = False
                elif any(kw in _q for kw in ["infection", "replication", "cycle", "pathogen"]):
                    diagram_type = "infection_cycle"
                    ai_suitable = False
                else:
                    diagram_type = "bacterial_structure"
                    ai_suitable = True
            preferred_tool = "matplotlib"

        return {
            "domain": domain,
            "diagram_type": diagram_type,
            "complexity": "moderate",
            "ai_suitable": ai_suitable,
            "preferred_tool": preferred_tool,
        }
