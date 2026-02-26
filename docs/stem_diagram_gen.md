# STEM Diagram Generation System - Implementation Guide

## Project Overview

Build a multi-agent system that generates textbook-quality STEM diagrams by intelligently routing requests to specialized libraries (primary) or AI models (fallback). The system prioritizes programmatic generation for accuracy and uses AI only when necessary.

---

## System Architecture

```
User Request → Agent 1 (Analyzer) → Agent 2 (Router) → [Agent 3 OR Agent 4 OR Agent 5] → Agent 6 (Validator) → Agent 7 (Formatter) → Output
```

### Agents Overview

| Agent | Purpose | Technology | Priority |
|-------|---------|------------|----------|
| Agent 1 | Request Analyzer | Claude 3.5 Sonnet / GPT-4o | Critical |
| Agent 2 | Domain Router | Rule-based + LLM | Critical |
| Agent 3 | Library Executor | Python Libraries | Primary Path |
| Agent 4 | Hybrid Generator | Libraries + AI | Secondary Path |
| Agent 5 | AI Model Selector | Multi-model AI | Fallback Path |
| Agent 6 | Quality Validator | Vision LLM | Critical |
| Agent 7 | Post-Processor | Image processing | Critical |

---

## Project Structure

```
stem-diagram-generator/
├── src/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── agent_1_analyzer.py
│   │   ├── agent_2_router.py
│   │   ├── agent_3_library_executor.py
│   │   ├── agent_4_hybrid_generator.py
│   │   ├── agent_5_ai_selector.py
│   │   ├── agent_6_validator.py
│   │   └── agent_7_postprocessor.py
│   ├── generators/
│   │   ├── __init__.py
│   │   ├── electronics_generator.py
│   │   ├── mathematics_generator.py
│   │   ├── chemistry_generator.py
│   │   ├── physics_generator.py
│   │   ├── mechanical_generator.py
│   │   ├── civil_generator.py
│   │   └── computer_science_generator.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── diagram_request.py
│   │   ├── diagram_response.py
│   │   └── validation_result.py
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── image_utils.py
│   │   ├── llm_client.py
│   │   └── cache_manager.py
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py
│   │   └── routing_rules.yaml
│   └── main.py
├── tests/
├── requirements.txt
├── README.md
└── .env.example
```

---

## Data Models

### DiagramRequest (Input Schema)

```python
from pydantic import BaseModel
from typing import Optional, Dict, List, Any
from enum import Enum

class DiagramDomain(str, Enum):
    ELECTRONICS = "electronics"
    MATHEMATICS = "mathematics"
    COMPUTER_SCIENCE = "computer_science"
    MECHANICAL = "mechanical"
    CIVIL = "civil"
    CHEMISTRY = "chemistry"
    PHYSICS = "physics"
    BIOLOGY = "biology"

class GenerationMethod(str, Enum):
    PROGRAMMATIC = "programmatic"
    HYBRID = "hybrid"
    AI_ONLY = "ai_only"

class DiagramRequest(BaseModel):
    """Raw user request"""
    user_input: str
    user_level: Optional[str] = "undergraduate"  # high_school, undergraduate, graduate
    style_preference: Optional[str] = "textbook"  # textbook, colorful, minimal
    output_format: Optional[List[str]] = ["svg", "png"]
    language: Optional[str] = "en"

class AnalyzedRequest(BaseModel):
    """Output from Agent 1"""
    intent: str
    domain: DiagramDomain
    subdomain: str
    diagram_type: str
    parameters: Dict[str, Any]
    style: str
    complexity: str  # simple, medium, complex
    user_level: str

class RoutingDecision(BaseModel):
    """Output from Agent 2"""
    generation_method: GenerationMethod
    primary_generator: str  # e.g., "electronics_generator"
    fallback_generators: List[str]
    library_to_use: Optional[str]  # e.g., "schemdraw", "matplotlib"
    ai_model: Optional[str]  # if AI generation needed
    confidence: float  # 0-1

class DiagramOutput(BaseModel):
    """Final output"""
    diagram_data: bytes  # image bytes
    format: str  # svg, png, pdf
    metadata: Dict[str, Any]
    generation_method: str
    quality_score: float
    validation_passed: bool
    generation_time_ms: int
```

---

## Agent 1: Request Analyzer

### Responsibility
Parse user input and extract structured information using LLM.

### Implementation

```python
# src/agents/agent_1_analyzer.py

import asyncio
from typing import Dict, Any
from ..models.diagram_request import DiagramRequest, AnalyzedRequest, DiagramDomain
from ..utils.llm_client import LLMClient

class RequestAnalyzer:
    """Agent 1: Analyzes user requests and extracts structured information"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def analyze(self, request: DiagramRequest) -> AnalyzedRequest:
        """
        Analyze user request and return structured data

        Args:
            request: Raw user request

        Returns:
            AnalyzedRequest with structured information
        """

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(request)

        response = await self.llm.chat_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format="json"
        )

        # Parse and validate response
        analyzed = self._parse_llm_response(response)

        return analyzed

    def _build_system_prompt(self) -> str:
        return """You are a STEM diagram specification analyzer.

Your job is to analyze user requests for technical diagrams and extract:
1. Domain (electronics, mathematics, computer_science, mechanical, civil, chemistry, physics, biology)
2. Subdomain (specific area within domain)
3. Diagram type (specific diagram needed)
4. All technical parameters (values, labels, specifications)
5. Complexity level (simple, medium, complex)

Return ONLY valid JSON matching this schema:
{
    "intent": "string - what user wants to create",
    "domain": "string - one of the 8 domains",
    "subdomain": "string - specific area",
    "diagram_type": "string - specific diagram",
    "parameters": {
        "key": "value - all technical details extracted"
    },
    "style": "string - textbook/colorful/minimal",
    "complexity": "string - simple/medium/complex"
}

Examples:

Input: "Draw a MOSFET common source amplifier with Rd=10k and Rs=1k"
Output:
{
    "intent": "generate_circuit_diagram",
    "domain": "electronics",
    "subdomain": "analog_circuits",
    "diagram_type": "mosfet_amplifier",
    "parameters": {
        "mosfet_type": "nmos",
        "configuration": "common_source",
        "Rd": "10kΩ",
        "Rs": "1kΩ",
        "components": ["mosfet", "drain_resistor", "source_resistor"]
    },
    "style": "textbook",
    "complexity": "medium"
}

Input: "Plot y=x^2 from -5 to 5"
Output:
{
    "intent": "generate_mathematical_plot",
    "domain": "mathematics",
    "subdomain": "calculus",
    "diagram_type": "2d_function_plot",
    "parameters": {
        "function": "x**2",
        "x_range": [-5, 5],
        "plot_type": "line"
    },
    "style": "textbook",
    "complexity": "simple"
}

Be thorough in extracting ALL parameters from the user request."""

    def _build_user_prompt(self, request: DiagramRequest) -> str:
        return f"""Analyze this diagram request:

User Input: {request.user_input}
User Level: {request.user_level}
Style Preference: {request.style_preference}

Extract all specifications and return JSON."""

    def _parse_llm_response(self, response: str) -> AnalyzedRequest:
        """Parse LLM JSON response into AnalyzedRequest model"""
        import json

        data = json.loads(response)

        return AnalyzedRequest(
            intent=data["intent"],
            domain=DiagramDomain(data["domain"]),
            subdomain=data["subdomain"],
            diagram_type=data["diagram_type"],
            parameters=data["parameters"],
            style=data.get("style", "textbook"),
            complexity=data.get("complexity", "medium"),
            user_level=data.get("user_level", "undergraduate")
        )
```

---

## Agent 2: Domain Router

### Responsibility
Route requests to appropriate generation method based on rules and domain knowledge.

### Implementation

```python
# src/agents/agent_2_router.py

from typing import Dict, List
import yaml
from ..models.diagram_request import AnalyzedRequest, RoutingDecision, GenerationMethod

class DomainRouter:
    """Agent 2: Routes requests to appropriate generation method"""

    def __init__(self, routing_rules_path: str):
        with open(routing_rules_path, 'r') as f:
            self.routing_rules = yaml.safe_load(f)

    def route(self, analyzed: AnalyzedRequest) -> RoutingDecision:
        """
        Determine generation method and route to appropriate generator

        Args:
            analyzed: Analyzed request from Agent 1

        Returns:
            RoutingDecision with generation method and generator info
        """

        # Look up routing rule
        domain = analyzed.domain.value
        subdomain = analyzed.subdomain
        diagram_type = analyzed.diagram_type

        # Try exact match first
        rule = self._find_routing_rule(domain, subdomain, diagram_type)

        if not rule:
            # Fall back to domain-level rule
            rule = self._find_routing_rule(domain, subdomain, None)

        if not rule:
            # Ultimate fallback: AI generation
            return RoutingDecision(
                generation_method=GenerationMethod.AI_ONLY,
                primary_generator="ai_generator",
                fallback_generators=[],
                ai_model="gpt-image-1.5",
                confidence=0.5
            )

        return self._build_routing_decision(rule, analyzed)

    def _find_routing_rule(self, domain: str, subdomain: str, diagram_type: str = None) -> Dict:
        """Find matching routing rule"""

        domain_rules = self.routing_rules.get(domain, {})
        subdomain_rules = domain_rules.get(subdomain, {})

        if diagram_type and diagram_type in subdomain_rules:
            return subdomain_rules[diagram_type]
        elif "default" in subdomain_rules:
            return subdomain_rules["default"]

        return None

    def _build_routing_decision(self, rule: Dict, analyzed: AnalyzedRequest) -> RoutingDecision:
        """Build RoutingDecision from rule"""

        return RoutingDecision(
            generation_method=GenerationMethod(rule["method"]),
            primary_generator=rule["generator"],
            fallback_generators=rule.get("fallbacks", []),
            library_to_use=rule.get("library"),
            ai_model=rule.get("ai_model"),
            confidence=rule.get("confidence", 0.9)
        )
```

### Routing Rules Configuration

```yaml
# src/config/routing_rules.yaml

electronics:
  analog_circuits:
    mosfet_amplifier:
      method: programmatic
      generator: electronics_generator
      library: schemdraw
      confidence: 0.95
      fallbacks:
        - hybrid_generator
        - ai_generator

    op_amp:
      method: programmatic
      generator: electronics_generator
      library: schemdraw
      confidence: 0.95

    default:
      method: programmatic
      generator: electronics_generator
      library: schemdraw
      confidence: 0.8

  digital_circuits:
    logic_gates:
      method: programmatic
      generator: electronics_generator
      library: schemdraw
      confidence: 0.95

    default:
      method: programmatic
      generator: electronics_generator
      library: schemdraw

  pcb_design:
    default:
      method: ai_only
      generator: ai_generator
      ai_model: imagen-3
      confidence: 0.6

mathematics:
  calculus:
    2d_function_plot:
      method: programmatic
      generator: mathematics_generator
      library: matplotlib
      confidence: 1.0

    3d_surface:
      method: programmatic
      generator: mathematics_generator
      library: matplotlib
      confidence: 0.95

  geometry:
    default:
      method: programmatic
      generator: mathematics_generator
      library: matplotlib
      confidence: 0.9

chemistry:
  molecular_structures:
    default:
      method: programmatic
      generator: chemistry_generator
      library: rdkit
      confidence: 0.95

  lab_equipment:
    default:
      method: ai_only
      generator: ai_generator
      ai_model: imagen-3
      confidence: 0.7

physics:
  mechanics:
    free_body_diagram:
      method: programmatic
      generator: physics_generator
      library: matplotlib
      confidence: 0.9

    projectile_motion:
      method: programmatic
      generator: physics_generator
      library: matplotlib
      confidence: 0.9

  optics:
    default:
      method: hybrid
      generator: hybrid_generator
      confidence: 0.7

mechanical:
  thermodynamics:
    heat_transfer:
      method: programmatic
      generator: mechanical_generator
      library: matplotlib
      confidence: 0.85

    manometer:
      method: programmatic
      generator: mechanical_generator
      library: matplotlib
      confidence: 0.85

  mechanisms:
    default:
      method: programmatic
      generator: mechanical_generator
      library: matplotlib
      confidence: 0.8

  cad_drawings:
    default:
      method: hybrid
      generator: hybrid_generator
      confidence: 0.7

civil:
  structures:
    beam_diagram:
      method: programmatic
      generator: civil_generator
      library: matplotlib
      confidence: 0.9

    truss:
      method: programmatic
      generator: civil_generator
      library: matplotlib
      confidence: 0.9

  site_plans:
    default:
      method: ai_only
      generator: ai_generator
      ai_model: imagen-3

computer_science:
  algorithms:
    flowchart:
      method: programmatic
      generator: cs_generator
      library: graphviz
      confidence: 0.95

    data_structure:
      method: programmatic
      generator: cs_generator
      library: networkx
      confidence: 0.9

  uml:
    default:
      method: programmatic
      generator: cs_generator
      library: plantuml
      confidence: 0.9

biology:
  cell_biology:
    default:
      method: ai_only
      generator: ai_generator
      ai_model: gpt-image-1.5
      confidence: 0.7

  molecular_biology:
    phylogenetic_tree:
      method: programmatic
      generator: biology_generator
      library: biopython
      confidence: 0.85
```

---

## Agent 3: Library Executor

### Responsibility
Generate diagrams using specialized Python libraries (primary generation path).

### Implementation

```python
# src/agents/agent_3_library_executor.py

from typing import Dict, Any, BytesIO
from ..models.diagram_request import AnalyzedRequest, RoutingDecision
from ..generators.electronics_generator import ElectronicsGenerator
from ..generators.mathematics_generator import MathematicsGenerator
from ..generators.chemistry_generator import ChemistryGenerator
from ..generators.physics_generator import PhysicsGenerator
from ..generators.mechanical_generator import MechanicalGenerator
from ..generators.civil_generator import CivilGenerator
from ..generators.computer_science_generator import ComputerScienceGenerator

class LibraryExecutor:
    """Agent 3: Executes programmatic diagram generation using libraries"""

    def __init__(self):
        self.generators = {
            "electronics_generator": ElectronicsGenerator(),
            "mathematics_generator": MathematicsGenerator(),
            "chemistry_generator": ChemistryGenerator(),
            "physics_generator": PhysicsGenerator(),
            "mechanical_generator": MechanicalGenerator(),
            "civil_generator": CivilGenerator(),
            "cs_generator": ComputerScienceGenerator(),
        }

    async def generate(
        self,
        analyzed: AnalyzedRequest,
        routing: RoutingDecision
    ) -> BytesIO:
        """
        Generate diagram using appropriate library

        Args:
            analyzed: Analyzed request
            routing: Routing decision

        Returns:
            BytesIO containing generated image
        """

        generator = self.generators.get(routing.primary_generator)

        if not generator:
            raise ValueError(f"Generator {routing.primary_generator} not found")

        # Call appropriate method based on diagram type
        result = await generator.generate(
            diagram_type=analyzed.diagram_type,
            parameters=analyzed.parameters,
            style=analyzed.style,
            user_level=analyzed.user_level
        )

        return result
```

---

## Domain-Specific Generators

### Electronics Generator

```python
# src/generators/electronics_generator.py

import schemdraw
import schemdraw.elements as elm
from io import BytesIO
from typing import Dict, Any

class ElectronicsGenerator:
    """Generates electronic circuit diagrams using SchemDraw"""

    async def generate(
        self,
        diagram_type: str,
        parameters: Dict[str, Any],
        style: str,
        user_level: str
    ) -> BytesIO:
        """
        Generate electronic circuit diagram

        Supported types:
        - mosfet_amplifier (common_source, common_drain, common_gate)
        - bjt_amplifier (common_emitter, common_collector, common_base)
        - op_amp (inverting, non_inverting, differential, integrator, differentiator)
        - logic_gates (and, or, not, nand, nor, xor, xnor)
        - power_supply (linear, switching)
        - filter (low_pass, high_pass, band_pass)
        """

        if diagram_type == "mosfet_amplifier":
            return self._generate_mosfet_amplifier(parameters, style, user_level)
        elif diagram_type == "op_amp":
            return self._generate_op_amp(parameters, style, user_level)
        elif diagram_type == "logic_gates":
            return self._generate_logic_gates(parameters, style, user_level)
        elif diagram_type == "bjt_amplifier":
            return self._generate_bjt_amplifier(parameters, style, user_level)
        else:
            raise ValueError(f"Unsupported diagram type: {diagram_type}")

    def _generate_mosfet_amplifier(
        self,
        params: Dict,
        style: str,
        user_level: str
    ) -> BytesIO:
        """Generate MOSFET amplifier circuit"""

        config = params.get('configuration', 'common_source')
        mosfet_type = params.get('mosfet_type', 'nmos')

        with schemdraw.Drawing(show=False) as d:
            d.config(fontsize=12, font='sans-serif')

            if config == 'common_source':
                # Input
                d += elm.Ground()
                d += elm.SourceV().up().label('Vin')
                d += elm.Capacitor().right().label('C1')

                # Gate resistor
                d += elm.Resistor().right().label(f"Rg\n{params.get('Rg', '1MΩ')}")
                d += elm.Dot()
                gate_point = d.here

                # Bias resistors
                d += elm.Line().up().length(1)
                d += elm.Resistor().up().label(f"R1\n{params.get('R1', '100kΩ')}")
                d += elm.Line().up().label('VDD', loc='right')

                d += elm.Line().at(gate_point).down().length(1)
                d += elm.Resistor().down().label(f"R2\n{params.get('R2', '50kΩ')}")
                d += elm.Ground()

                # MOSFET
                d += elm.Line().at(gate_point).right().length(0.5)
                if mosfet_type == 'nmos':
                    mosfet = d += elm.NFet(bulk=True).anchor('gate')
                else:
                    mosfet = d += elm.PFet(bulk=True).anchor('gate')

                # Drain circuit
                d += elm.Line().at(mosfet.drain).up().length(1)
                d += elm.Resistor().up().label(f"Rd\n{params.get('Rd', '10kΩ')}")
                d += elm.Line().up().label('VDD', loc='right')

                d += elm.Line().at(mosfet.drain).right().length(1)
                d += elm.Capacitor().right().label('C2')
                d += elm.Gap().right().label('Vout', loc='right')

                # Source circuit
                d += elm.Line().at(mosfet.source).down().length(0.5)
                d += elm.Resistor().down().label(f"Rs\n{params.get('Rs', '1kΩ')}")

                # Bypass capacitor if specified
                if params.get('bypass_capacitor', True):
                    d.push()
                    d += elm.Line().right().length(0.5)
                    d += elm.Capacitor().down().toy(d.elements[-2].end).label('Cs')
                    d.pop()

                d += elm.Ground()

            elif config == 'common_drain':
                # Source follower configuration
                # TODO: Implement
                pass

            # Convert to BytesIO
            buf = BytesIO()
            d.save(buf, format='svg')
            buf.seek(0)
            return buf

    def _generate_op_amp(
        self,
        params: Dict,
        style: str,
        user_level: str
    ) -> BytesIO:
        """Generate op-amp circuit"""

        config = params.get('config', 'inverting')

        with schemdraw.Drawing(show=False) as d:
            d.config(fontsize=12)

            if config == 'inverting':
                # Inverting amplifier
                op = d += elm.Opamp()

                # Feedback resistor
                d += elm.Line().at(op.in2).left().length(1)
                d += elm.Resistor().down().label(f"Rf\n{params.get('Rf', '100kΩ')}")
                d += elm.Line().left().tox(op.in1)

                # Input resistor
                d += elm.Resistor().left().label(f"Rin\n{params.get('Rin', '10kΩ')}")
                d += elm.Gap().left().label('Vin')
                d += elm.Ground()

                # Non-inverting input to ground
                d += elm.Line().at(op.in1).down().length(0.5)
                d += elm.Ground()

                # Output
                d += elm.Line().at(op.out).right().length(1)
                d += elm.Dot().label('Vout', loc='right')

            elif config == 'non_inverting':
                # Non-inverting amplifier
                op = d += elm.Opamp()

                # Input to non-inverting terminal
                d += elm.Line().at(op.in1).left()
                d += elm.Gap().left().label('Vin')
                d += elm.Ground()

                # Feedback network
                d += elm.Line().at(op.in2).left().length(1)
                feedback_point = d.here

                d += elm.Resistor().down().label(f"R1\n{params.get('R1', '10kΩ')}")
                d += elm.Ground()

                d += elm.Line().at(feedback_point).up().length(1)
                d += elm.Resistor().up().label(f"R2\n{params.get('R2', '100kΩ')}")
                d += elm.Line().right().tox(op.out)

                # Output
                d += elm.Line().at(op.out).right().length(1)
                d += elm.Dot().label('Vout', loc='right')

            buf = BytesIO()
            d.save(buf, format='svg')
            buf.seek(0)
            return buf

    def _generate_logic_gates(
        self,
        params: Dict,
        style: str,
        user_level: str
    ) -> BytesIO:
        """Generate logic gate diagrams"""

        gates = params.get('gates', ['and', 'or', 'not'])

        with schemdraw.Drawing(show=False) as d:
            d.config(fontsize=12)

            for i, gate_type in enumerate(gates):
                d.push()

                # Input lines
                d += elm.Line().right().at((0, -i*2.5))

                # Gate
                if gate_type.lower() == 'and':
                    gate = d += elm.And()
                elif gate_type.lower() == 'or':
                    gate = d += elm.Or()
                elif gate_type.lower() == 'not':
                    gate = d += elm.Not()
                elif gate_type.lower() == 'nand':
                    gate = d += elm.Nand()
                elif gate_type.lower() == 'nor':
                    gate = d += elm.Nor()
                elif gate_type.lower() == 'xor':
                    gate = d += elm.Xor()
                else:
                    gate = d += elm.And()  # default

                # Output line
                d += elm.Line().right()

                # Label
                d += elm.Label().label(gate_type.upper(), loc='top')

                d.pop()

            buf = BytesIO()
            d.save(buf, format='svg')
            buf.seek(0)
            return buf

    def _generate_bjt_amplifier(
        self,
        params: Dict,
        style: str,
        user_level: str
    ) -> BytesIO:
        """Generate BJT amplifier circuit"""

        # TODO: Implement BJT amplifier configurations
        pass
```

### Mathematics Generator

```python
# src/generators/mathematics_generator.py

import matplotlib.pyplot as plt
import numpy as np
from io import BytesIO
from typing import Dict, Any
from mpl_toolkits.mplot3d import Axes3D

class MathematicsGenerator:
    """Generates mathematical diagrams using Matplotlib"""

    async def generate(
        self,
        diagram_type: str,
        parameters: Dict[str, Any],
        style: str,
        user_level: str
    ) -> BytesIO:
        """
        Generate mathematical diagram

        Supported types:
        - 2d_function_plot
        - 3d_surface
        - vector_field
        - geometry (shapes, constructions)
        - parametric_plot
        - polar_plot
        - contour_plot
        """

        if diagram_type == "2d_function_plot":
            return self._generate_2d_plot(parameters, style, user_level)
        elif diagram_type == "3d_surface":
            return self._generate_3d_surface(parameters, style, user_level)
        elif diagram_type == "geometry":
            return self._generate_geometry(parameters, style, user_level)
        elif diagram_type == "vector_field":
            return self._generate_vector_field(parameters, style, user_level)
        else:
            raise ValueError(f"Unsupported diagram type: {diagram_type}")

    def _generate_2d_plot(
        self,
        params: Dict,
        style: str,
        user_level: str
    ) -> BytesIO:
        """Generate 2D function plot"""

        function_str = params.get('function', 'x**2')
        x_range = params.get('x_range', [-10, 10])
        title = params.get('title', 'Function Plot')

        fig, ax = plt.subplots(figsize=(10, 7), dpi=150)

        # Generate points
        x = np.linspace(x_range[0], x_range[1], 1000)

        # Safely evaluate function
        try:
            # Create safe namespace
            safe_dict = {
                "x": x,
                "np": np,
                "sin": np.sin,
                "cos": np.cos,
                "tan": np.tan,
                "exp": np.exp,
                "log": np.log,
                "log10": np.log10,
                "sqrt": np.sqrt,
                "abs": np.abs,
                "pi": np.pi,
                "e": np.e
            }
            y = eval(function_str, {"__builtins__": {}}, safe_dict)
        except Exception as e:
            # Fallback to simple function
            y = x**2

        # Plot
        ax.plot(x, y, 'b-', linewidth=2.5, label=f'y = {function_str}')

        # Axes
        ax.axhline(y=0, color='k', linewidth=0.8, alpha=0.7)
        ax.axvline(x=0, color='k', linewidth=0.8, alpha=0.7)

        # Grid
        ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)

        # Labels
        ax.set_xlabel('x', fontsize=14, fontweight='bold')
        ax.set_ylabel('y', fontsize=14, fontweight='bold')
        ax.set_title(title, fontsize=16, fontweight='bold', pad=20)

        # Legend
        ax.legend(fontsize=12, loc='best')

        # Textbook styling
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_linewidth(1.5)
        ax.spines['bottom'].set_linewidth(1.5)

        # Ticks
        ax.tick_params(labelsize=11, width=1.5)

        # Save
        buf = BytesIO()
        plt.savefig(buf, format='svg', bbox_inches='tight', dpi=150)
        buf.seek(0)
        plt.close()

        return buf

    def _generate_3d_surface(
        self,
        params: Dict,
        style: str,
        user_level: str
    ) -> BytesIO:
        """Generate 3D surface plot"""

        function_str = params.get('function', 'X**2 + Y**2')
        x_range = params.get('x_range', [-5, 5])
        y_range = params.get('y_range', [-5, 5])
        title = params.get('title', '3D Surface Plot')

        fig = plt.figure(figsize=(12, 9), dpi=150)
        ax = fig.add_subplot(111, projection='3d')

        # Create mesh
        x = np.linspace(x_range[0], x_range[1], 100)
        y = np.linspace(y_range[0], y_range[1], 100)
        X, Y = np.meshgrid(x, y)

        # Evaluate function
        try:
            safe_dict = {
                "X": X,
                "Y": Y,
                "np": np,
                "sin": np.sin,
                "cos": np.cos,
                "exp": np.exp,
                "sqrt": np.sqrt
            }
            Z = eval(function_str, {"__builtins__": {}}, safe_dict)
        except:
            Z = X**2 + Y**2  # fallback

        # Plot surface
        surf = ax.plot_surface(
            X, Y, Z,
            cmap='viridis',
            alpha=0.9,
            linewidth=0,
            antialiased=True,
            edgecolor='none'
        )

        # Labels
        ax.set_xlabel('X', fontsize=12, fontweight='bold')
        ax.set_ylabel('Y', fontsize=12, fontweight='bold')
        ax.set_zlabel('Z', fontsize=12, fontweight='bold')
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)

        # Colorbar
        fig.colorbar(surf, shrink=0.5, aspect=5)

        # Save
        buf = BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=150)
        buf.seek(0)
        plt.close()

        return buf

    def _generate_geometry(
        self,
        params: Dict,
        style: str,
        user_level: str
    ) -> BytesIO:
        """Generate geometric diagrams"""

        from matplotlib.patches import Rectangle, Circle, Polygon

        shape = params.get('shape', 'triangle')

        fig, ax = plt.subplots(figsize=(10, 10), dpi=150)
        ax.set_aspect('equal')

        if shape == 'triangle':
            # Right triangle
            vertices = [(0, 0), (4, 0), (4, 3)]
            triangle = Polygon(
                vertices,
                fill=False,
                edgecolor='blue',
                linewidth=2.5
            )
            ax.add_patch(triangle)

            # Labels
            ax.text(2, -0.5, 'base = 4', ha='center', fontsize=12, fontweight='bold')
            ax.text(4.5, 1.5, 'height = 3', rotation=90, va='center', fontsize=12, fontweight='bold')
            ax.text(1.5, 2, 'hypotenuse = 5', rotation=37, ha='center', fontsize=12, fontweight='bold')

            # Right angle marker
            square = Rectangle((3.7, 0), 0.3, 0.3, fill=False, edgecolor='blue', linewidth=2)
            ax.add_patch(square)

            # Vertices
            for i, (x, y) in enumerate(vertices):
                ax.plot(x, y, 'ko', markersize=8)
                ax.text(x-0.3, y-0.3, chr(65+i), fontsize=12, fontweight='bold')

        elif shape == 'circle':
            radius = params.get('radius', 3)
            circle = Circle((0, 0), radius, fill=False, edgecolor='blue', linewidth=2.5)
            ax.add_patch(circle)

            # Radius line
            ax.plot([0, radius], [0, 0], 'r-', linewidth=2.5)
            ax.text(radius/2, 0.3, f'r = {radius}', fontsize=12, color='red', fontweight='bold')

            # Center
            ax.plot(0, 0, 'ko', markersize=8)
            ax.text(0.2, 0.2, 'O', fontsize=12, fontweight='bold')

        # Axes
        ax.set_xlim(-5, 6)
        ax.set_ylim(-5, 6)
        ax.axhline(y=0, color='k', linewidth=0.5, alpha=0.3)
        ax.axvline(x=0, color='k', linewidth=0.5, alpha=0.3)
        ax.grid(True, alpha=0.2, linestyle='--')

        ax.set_title(f'{shape.capitalize()} Diagram', fontsize=16, fontweight='bold', pad=20)

        # Save
        buf = BytesIO()
        plt.savefig(buf, format='svg', bbox_inches='tight', dpi=150)
        buf.seek(0)
        plt.close()

        return buf

    def _generate_vector_field(
        self,
        params: Dict,
        style: str,
        user_level: str
    ) -> BytesIO:
        """Generate vector field diagram"""

        # TODO: Implement vector field visualization
        pass
```

### Mechanical Generator

```python
# src/generators/mechanical_generator.py

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle, Circle, FancyBboxPatch, Polygon, FancyArrowPatch
from io import BytesIO
from typing import Dict, Any

class MechanicalGenerator:
    """Generates mechanical engineering diagrams"""

    async def generate(
        self,
        diagram_type: str,
        parameters: Dict[str, Any],
        style: str,
        user_level: str
    ) -> BytesIO:
        """
        Generate mechanical engineering diagram

        Supported types:
        - free_body_diagram
        - heat_transfer (slab, cylinder, sphere)
        - manometer (u-tube, differential, inclined)
        - mechanism (four_bar, slider_crank)
        - stress_strain
        - mohr_circle
        """

        if diagram_type == "free_body_diagram":
            return self._generate_fbd(parameters, style, user_level)
        elif diagram_type == "heat_transfer":
            return self._generate_heat_transfer(parameters, style, user_level)
        elif diagram_type == "manometer":
            return self._generate_manometer(parameters, style, user_level)
        elif diagram_type == "mechanism":
            return self._generate_mechanism(parameters, style, user_level)
        else:
            raise ValueError(f"Unsupported diagram type: {diagram_type}")

    def _generate_fbd(
        self,
        params: Dict,
        style: str,
        user_level: str
    ) -> BytesIO:
        """Generate free body diagram"""

        object_type = params.get('object', 'block')
        forces = params.get('forces', [
            {'name': 'W', 'direction': 'down', 'magnitude': 100, 'color': 'blue'},
            {'name': 'N', 'direction': 'up', 'magnitude': 100, 'color': 'red'},
            {'name': 'F', 'direction': 'right', 'magnitude': 50, 'color': 'green'}
        ])

        fig, ax = plt.subplots(figsize=(12, 10), dpi=150)
        ax.set_aspect('equal')

        # Draw object (block)
        block_width = 2
        block_height = 2
        block_x = 4
        block_y = 3

        if object_type == 'block':
            block = Rectangle(
                (block_x, block_y),
                block_width,
                block_height,
                fill=True,
                facecolor='lightblue',
                edgecolor='black',
                linewidth=2.5,
                alpha=0.7
            )
            ax.add_patch(block)

            # Center of mass
            cm_x = block_x + block_width/2
            cm_y = block_y + block_height/2
            ax.plot(cm_x, cm_y, 'ko', markersize=12)
            ax.text(cm_x + 0.2, cm_y + 0.2, 'CM', fontsize=11, fontweight='bold')

        # Draw forces
        arrow_scale = 0.02  # scale for magnitude

        for force in forces:
            magnitude = force['magnitude']
            direction = force['direction']
            name = force['name']
            color = force.get('color', 'red')

            arrow_length = magnitude * arrow_scale

            if direction == 'up':
                arrow = FancyArrowPatch(
                    (cm_x, cm_y),
                    (cm_x, cm_y + arrow_length),
                    arrowstyle='->',
                    mutation_scale=30,
                    linewidth=3,
                    color=color
                )
                ax.add_patch(arrow)
                ax.text(
                    cm_x + 0.3,
                    cm_y + arrow_length/2,
                    f'{name} = {magnitude}N',
                    fontsize=11,
                    fontweight='bold',
                    color=color
                )

            elif direction == 'down':
                arrow = FancyArrowPatch(
                    (cm_x, cm_y),
                    (cm_x, cm_y - arrow_length),
                    arrowstyle='->',
                    mutation_scale=30,
                    linewidth=3,
                    color=color
                )
                ax.add_patch(arrow)
                ax.text(
                    cm_x + 0.3,
                    cm_y - arrow_length/2,
                    f'{name} = {magnitude}N',
                    fontsize=11,
                    fontweight='bold',
                    color=color
                )

            elif direction == 'right':
                arrow = FancyArrowPatch(
                    (cm_x, cm_y),
                    (cm_x + arrow_length, cm_y),
                    arrowstyle='->',
                    mutation_scale=30,
                    linewidth=3,
                    color=color
                )
                ax.add_patch(arrow)
                ax.text(
                    cm_x + arrow_length/2,
                    cm_y + 0.3,
                    f'{name} = {magnitude}N',
                    fontsize=11,
                    fontweight='bold',
                    color=color
                )

            elif direction == 'left':
                arrow = FancyArrowPatch(
                    (cm_x, cm_y),
                    (cm_x - arrow_length, cm_y),
                    arrowstyle='->',
                    mutation_scale=30,
                    linewidth=3,
                    color=color
                )
                ax.add_patch(arrow)
                ax.text(
                    cm_x - arrow_length/2,
                    cm_y + 0.3,
                    f'{name} = {magnitude}N',
                    fontsize=11,
                    fontweight='bold',
                    color=color
                )

        # Ground/surface
        ground_y = block_y
        ax.plot([2, 8], [ground_y, ground_y], 'k-', linewidth=4)

        # Hatching for ground
        for i in np.linspace(2, 8, 25):
            ax.plot([i, i - 0.15], [ground_y, ground_y - 0.3], 'k-', linewidth=1.5)

        # Settings
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.axis('off')
        ax.set_title('Free Body Diagram', fontsize=16, fontweight='bold', pad=20)

        # Save
        buf = BytesIO()
        plt.savefig(buf, format='svg', bbox_inches='tight', dpi=150)
        buf.seek(0)
        plt.close()

        return buf

    def _generate_manometer(
        self,
        params: Dict,
        style: str,
        user_level: str
    ) -> BytesIO:
        """Generate manometer diagram"""

        manometer_type = params.get('type', 'u_tube')
        fluid = params.get('fluid', 'mercury')

        fig, ax = plt.subplots(figsize=(10, 12), dpi=150)
        ax.set_aspect('equal')

        if manometer_type == 'u_tube':
            # U-tube dimensions
            tube_width = 0.4
            left_x = 3
            right_x = 7
            bottom_y = 2

            # Left column
            left_tube = Rectangle(
                (left_x, bottom_y),
                tube_width,
                6,
                fill=False,
                edgecolor='black',
                linewidth=2.5
            )
            ax.add_patch(left_tube)

            # Right column
            right_tube = Rectangle(
                (right_x, bottom_y),
                tube_width,
                5,
                fill=False,
                edgecolor='black',
                linewidth=2.5
            )
            ax.add_patch(right_tube)

            # Bottom connection
            bottom_tube = Rectangle(
                (left_x, bottom_y),
                right_x - left_x + tube_width,
                0.4,
                fill=False,
                edgecolor='black',
                linewidth=2.5
            )
            ax.add_patch(bottom_tube)

            # Fluid levels
            left_fluid_height = params.get('left_height', 4)
            right_fluid_height = params.get('right_height', 3.5)

            # Left fluid
            left_fluid = Rectangle(
                (left_x, bottom_y),
                tube_width,
                left_fluid_height,
                fill=True,
                facecolor='silver' if fluid == 'mercury' else 'lightblue',
                alpha=0.7,
                edgecolor='gray',
                linewidth=1.5
            )
            ax.add_patch(left_fluid)

            # Right fluid
            right_fluid = Rectangle(
                (right_x, bottom_y),
                tube_width,
                right_fluid_height,
                fill=True,
                facecolor='silver' if fluid == 'mercury' else 'lightblue',
                alpha=0.7,
                edgecolor='gray',
                linewidth=1.5
            )
            ax.add_patch(right_fluid)

            # Bottom fluid
            bottom_fluid = Rectangle(
                (left_x, bottom_y),
                right_x - left_x + tube_width,
                0.4,
                fill=True,
                facecolor='silver' if fluid == 'mercury' else 'lightblue',
                alpha=0.7,
                edgecolor='gray',
                linewidth=1.5
            )
            ax.add_patch(bottom_fluid)

            # Pressure labels
            ax.text(
                left_x + tube_width/2,
                bottom_y + left_fluid_height + 0.7,
                'P₁',
                ha='center',
                fontsize=16,
                fontweight='bold'
            )
            ax.text(
                right_x + tube_width/2,
                bottom_y + right_fluid_height + 0.7,
                'P₂',
                ha='center',
                fontsize=16,
                fontweight='bold'
            )

            # Height difference annotation
            h_diff = left_fluid_height - right_fluid_height
            arrow_x = right_x + tube_width + 0.8

            arrow = FancyArrowPatch(
                (arrow_x, bottom_y + left_fluid_height),
                (arrow_x, bottom_y + right_fluid_height),
                arrowstyle='<->',
                mutation_scale=20,
                linewidth=2.5,
                color='red'
            )
            ax.add_patch(arrow)
            ax.text(
                arrow_x + 0.5,
                bottom_y + (left_fluid_height + right_fluid_height)/2,
                f'h = {h_diff:.1f}',
                fontsize=13,
                color='red',
                fontweight='bold'
            )

            # Datum line
            ax.plot(
                [left_x - 0.5, right_x + tube_width + 0.5],
                [bottom_y, bottom_y],
                'k--',
                linewidth=1.5,
                alpha=0.6
            )
            ax.text(left_x - 1, bottom_y, 'Datum', fontsize=11, va='center')

            # Fluid label
            ax.text(
                (left_x + right_x)/2 + tube_width/2,
                bottom_y - 0.8,
                f'{fluid.capitalize()}',
                ha='center',
                fontsize=12,
                style='italic'
            )

        # Settings
        ax.set_xlim(0, 12)
        ax.set_ylim(0, 12)
        ax.axis('off')
        ax.set_title('U-Tube Manometer', fontsize=16, fontweight='bold', pad=20)

        # Save
        buf = BytesIO()
        plt.savefig(buf, format='svg', bbox_inches='tight', dpi=150)
        buf.seek(0)
        plt.close()

        return buf

    def _generate_heat_transfer(
        self,
        params: Dict,
        style: str,
        user_level: str
    ) -> BytesIO:
        """Generate heat transfer diagram"""

        geometry = params.get('geometry', 'slab')

        fig, ax = plt.subplots(figsize=(12, 8), dpi=150)

        if geometry == 'slab':
            # Heat transfer through a slab
            slab_x = 2
            slab_y = 2
            slab_width = 5
            slab_height = 4

            slab = Rectangle(
                (slab_x, slab_y),
                slab_width,
                slab_height,
                fill=True,
                facecolor='lightgray',
                edgecolor='black',
                linewidth=2.5,
                alpha=0.7
            )
            ax.add_patch(slab)

            # Temperature labels
            ax.text(
                slab_x - 0.8,
                slab_y + slab_height/2,
                'T₁ (hot)',
                fontsize=14,
                fontweight='bold',
                color='red',
                va='center'
            )
            ax.text(
                slab_x + slab_width + 0.8,
                slab_y + slab_height/2,
                'T₂ (cold)',
                fontsize=14,
                fontweight='bold',
                color='blue',
                va='center'
            )

            # Heat flux arrows
            for y_pos in np.linspace(slab_y + 0.5, slab_y + slab_height - 0.5, 5):
                arrow = FancyArrowPatch(
                    (slab_x, y_pos),
                    (slab_x + slab_width, y_pos),
                    arrowstyle='->',
                    mutation_scale=25,
                    linewidth=2.5,
                    color='red',
                    alpha=0.7
                )
                ax.add_patch(arrow)

            # Q label
            ax.text(
                slab_x + slab_width/2,
                slab_y + slab_height + 0.8,
                'Q (Heat Flow)',
                ha='center',
                fontsize=13,
                fontweight='bold',
                color='red'
            )

            # Thickness dimension
            arrow = FancyArrowPatch(
                (slab_x, slab_y - 0.8),
                (slab_x + slab_width, slab_y - 0.8),
                arrowstyle='<->',
                mutation_scale=20,
                linewidth=2,
                color='black'
            )
            ax.add_patch(arrow)
            ax.text(
                slab_x + slab_width/2,
                slab_y - 1.2,
                'L (thickness)',
                ha='center',
                fontsize=12
            )

            # Material property
            ax.text(
                slab_x + slab_width/2,
                slab_y + slab_height/2,
                'k (thermal conductivity)',
                ha='center',
                fontsize=11,
                style='italic',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8)
            )

            # Equation (optional)
            if user_level in ['undergraduate', 'graduate']:
                ax.text(
                    slab_x + slab_width/2,
                    slab_y - 2,
                    r'$Q = -kA\frac{dT}{dx}$',
                    ha='center',
                    fontsize=14,
                    bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8)
                )

        # Settings
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.set_aspect('equal')
        ax.axis('off')
        ax.set_title('Heat Transfer Through Slab', fontsize=16, fontweight='bold', pad=20)

        # Save
        buf = BytesIO()
        plt.savefig(buf, format='svg', bbox_inches='tight', dpi=150)
        buf.seek(0)
        plt.close()

        return buf

    def _generate_mechanism(
        self,
        params: Dict,
        style: str,
        user_level: str
    ) -> BytesIO:
        """Generate mechanism diagram"""

        # TODO: Implement four-bar linkage, slider-crank, etc.
        pass
```

---

## Agent 5: AI Model Selector

```python
# src/agents/agent_5_ai_selector.py

from typing import Dict, Any, BytesIO
from ..models.diagram_request import AnalyzedRequest, RoutingDecision
from ..utils.llm_client import LLMClient

class AIModelSelector:
    """Agent 5: Selects and uses AI models for diagram generation"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def generate(
        self,
        analyzed: AnalyzedRequest,
        routing: RoutingDecision
    ) -> BytesIO:
        """
        Generate diagram using AI models

        Model selection priority:
        1. Gemini 2.5 Flash Image - for text rendering + technical diagrams
        2. GPT-Image-1.5 - for general technical diagrams
        3. Imagen-3 - for photorealistic scientific scenes
        4. DALL-E 3 - fallback
        """

        # Select model based on requirements
        model = self._select_model(analyzed, routing)

        # Build enhanced prompt
        prompt = self._build_prompt(analyzed)

        # Generate image
        image_data = await self._generate_with_model(model, prompt)

        return image_data

    def _select_model(
        self,
        analyzed: AnalyzedRequest,
        routing: RoutingDecision
    ) -> str:
        """Select appropriate AI model"""

        # If routing specifies a model, use it
        if routing.ai_model:
            return routing.ai_model

        # Otherwise, select based on requirements
        domain = analyzed.domain.value

        # Biology, complex organic structures
        if domain in ['biology', 'chemistry'] and analyzed.diagram_type in ['cell_diagram', 'organ_system']:
            return 'gpt-image-1.5'

        # Technical diagrams with text labels
        if analyzed.parameters.get('requires_labels', True):
            return 'gemini-2.5-flash-image'

        # Photorealistic scenes
        if analyzed.style == 'photorealistic':
            return 'imagen-3'

        # Default
        return 'gpt-image-1.5'

    def _build_prompt(self, analyzed: AnalyzedRequest) -> str:
        """Build optimized prompt for AI image generation"""

        base_prompt = f"""Textbook-style technical diagram of {analyzed.intent}.

Domain: {analyzed.domain.value}
Type: {analyzed.diagram_type}

Style: Educational textbook illustration, clean lines, clear labels, professional quality.
Format: Black and white line art with minimal color for clarity.
Background: White or transparent.
Quality: Publication-ready, high detail, accurate technical representation.

Specifications:
"""

        # Add parameters
        for key, value in analyzed.parameters.items():
            base_prompt += f"- {key}: {value}\n"

        base_prompt += """
Additional requirements:
- Use standard symbols and conventions for this domain
- All labels must be clearly readable
- Maintain technical accuracy
- Professional academic style
- No artistic interpretation unless specified
"""

        return base_prompt

    async def _generate_with_model(
        self,
        model: str,
        prompt: str
    ) -> BytesIO:
        """Generate image with specified model"""

        if model == 'gpt-image-1.5':
            return await self.llm.generate_image_openai(prompt, model='gpt-image-1.5')
        elif model == 'gemini-2.5-flash-image':
            return await self.llm.generate_image_google(prompt, model='gemini-2.5-flash-image')
        elif model == 'imagen-3':
            return await self.llm.generate_image_google(prompt, model='imagen-3.0-generate-002')
        elif model == 'dall-e-3':
            return await self.llm.generate_image_openai(prompt, model='dall-e-3')
        else:
            # Fallback to default
            return await self.llm.generate_image_openai(prompt, model='gpt-image-1.5')
```

---

## Agent 6: Quality Validator

```python
# src/agents/agent_6_validator.py

from typing import Dict, Any, List
from ..models.diagram_request import AnalyzedRequest
from ..models.validation_result import ValidationResult
from ..utils.llm_client import LLMClient
import base64

class QualityValidator:
    """Agent 6: Validates diagram quality and accuracy"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def validate(
        self,
        image_data: bytes,
        analyzed: AnalyzedRequest,
        generation_method: str
    ) -> ValidationResult:
        """
        Validate generated diagram

        Returns:
            ValidationResult with pass/fail and detailed feedback
        """

        # Convert image to base64 for vision model
        image_b64 = base64.b64encode(image_data).decode('utf-8')

        # Build validation prompt
        validation_prompt = self._build_validation_prompt(analyzed)

        # Use vision model to analyze
        analysis = await self.llm.analyze_image(image_b64, validation_prompt)

        # Parse analysis into ValidationResult
        result = self._parse_validation(analysis, analyzed)

        return result

    def _build_validation_prompt(self, analyzed: AnalyzedRequest) -> str:
        """Build validation prompt for vision model"""

        return f"""Analyze this technical diagram and validate it against these requirements:

Domain: {analyzed.domain.value}
Diagram Type: {analyzed.diagram_type}
User Level: {analyzed.user_level}

Required Parameters:
{self._format_parameters(analyzed.parameters)}

Validation Checklist:

1. STRUCTURAL VALIDATION:
   - Is this the correct type of diagram? (yes/no)
   - Are all required components present? (list missing if any)
   - Are connections/relationships correct? (yes/no)

2. ACCURACY VALIDATION:
   - Are all labels correct and readable? (yes/no)
   - Do values match specifications? (yes/no)
   - Does it follow standard conventions for this domain? (yes/no)

3. QUALITY VALIDATION:
   - Is it textbook-quality professional? (score 1-10)
   - Is it readable and clear? (score 1-10)
   - Are there any errors or mistakes? (list if any)

4. COMPLETENESS:
   - List all elements that are present
   - List any missing elements
   - Suggestions for improvement

Return your analysis in JSON format:
{{
    "diagram_type_correct": true/false,
    "all_components_present": true/false,
    "missing_components": [],
    "connections_correct": true/false,
    "labels_correct": true/false,
    "values_match": true/false,
    "follows_standards": true/false,
    "professional_score": 1-10,
    "readability_score": 1-10,
    "errors": [],
    "present_elements": [],
    "missing_elements": [],
    "suggestions": [],
    "overall_pass": true/false
}}
"""

    def _format_parameters(self, params: Dict[str, Any]) -> str:
        """Format parameters for prompt"""
        return "\n".join([f"- {k}: {v}" for k, v in params.items()])

    def _parse_validation(
        self,
        analysis: str,
        analyzed: AnalyzedRequest
    ) -> ValidationResult:
        """Parse LLM validation response"""

        import json

        data = json.loads(analysis)

        # Calculate overall quality score
        quality_score = (
            data['professional_score'] +
            data['readability_score']
        ) / 20.0  # Normalize to 0-1

        return ValidationResult(
            passed=data['overall_pass'],
            quality_score=quality_score,
            errors=data['errors'],
            missing_elements=data['missing_elements'],
            suggestions=data['suggestions'],
            details=data
        )
```

---

## Agent 7: Post-Processor

```python
# src/agents/agent_7_postprocessor.py

from io import BytesIO
from typing import List, Dict, Any
from PIL import Image
import cairosvg

class PostProcessor:
    """Agent 7: Post-processes and formats diagrams"""

    async def process(
        self,
        image_data: BytesIO,
        output_formats: List[str],
        metadata: Dict[str, Any]
    ) -> Dict[str, BytesIO]:
        """
        Post-process diagram and convert to requested formats

        Args:
            image_data: Input image (SVG or PNG)
            output_formats: List of formats (svg, png, pdf)
            metadata: Diagram metadata

        Returns:
            Dictionary of format -> BytesIO
        """

        results = {}

        # Detect input format
        image_data.seek(0)
        content = image_data.read()
        image_data.seek(0)

        is_svg = content.startswith(b'<?xml') or content.startswith(b'<svg')

        for fmt in output_formats:
            if fmt == 'svg':
                if is_svg:
                    results['svg'] = image_data
                else:
                    # Can't convert raster to SVG easily
                    continue

            elif fmt == 'png':
                if is_svg:
                    # Convert SVG to PNG
                    png_data = self._svg_to_png(content, dpi=300)
                    results['png'] = png_data
                else:
                    # Already PNG
                    results['png'] = image_data

            elif fmt == 'pdf':
                if is_svg:
                    # Convert SVG to PDF
                    pdf_data = self._svg_to_pdf(content)
                    results['pdf'] = pdf_data
                else:
                    # Convert PNG to PDF
                    pdf_data = self._png_to_pdf(image_data)
                    results['pdf'] = pdf_data

        return results

    def _svg_to_png(self, svg_content: bytes, dpi: int = 300) -> BytesIO:
        """Convert SVG to PNG"""

        png_data = cairosvg.svg2png(
            bytestring=svg_content,
            dpi=dpi
        )

        buf = BytesIO(png_data)
        buf.seek(0)
        return buf

    def _svg_to_pdf(self, svg_content: bytes) -> BytesIO:
        """Convert SVG to PDF"""

        pdf_data = cairosvg.svg2pdf(bytestring=svg_content)

        buf = BytesIO(pdf_data)
        buf.seek(0)
        return buf

    def _png_to_pdf(self, png_data: BytesIO) -> BytesIO:
        """Convert PNG to PDF"""

        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader

        png_data.seek(0)
        img = Image.open(png_data)

        # Create PDF
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=(img.width, img.height))

        png_data.seek(0)
        c.drawImage(ImageReader(png_data), 0, 0, img.width, img.height)
        c.save()

        buf.seek(0)
        return buf
```

---

## Main Orchestrator

```python
# src/main.py

from typing import Dict, Any
from .models.diagram_request import DiagramRequest, DiagramOutput
from .agents.agent_1_analyzer import RequestAnalyzer
from .agents.agent_2_router import DomainRouter
from .agents.agent_3_library_executor import LibraryExecutor
from .agents.agent_4_hybrid_generator import HybridGenerator
from .agents.agent_5_ai_selector import AIModelSelector
from .agents.agent_6_validator import QualityValidator
from .agents.agent_7_postprocessor import PostProcessor
from .utils.llm_client import LLMClient
import time

class DiagramGenerationOrchestrator:
    """Main orchestrator for diagram generation system"""

    def __init__(self, config: Dict[str, Any]):
        # Initialize LLM client
        self.llm_client = LLMClient(config)

        # Initialize agents
        self.analyzer = RequestAnalyzer(self.llm_client)
        self.router = DomainRouter(config['routing_rules_path'])
        self.library_executor = LibraryExecutor()
        self.hybrid_generator = HybridGenerator(self.llm_client)
        self.ai_selector = AIModelSelector(self.llm_client)
        self.validator = QualityValidator(self.llm_client)
        self.postprocessor = PostProcessor()

        self.max_retries = config.get('max_retries', 3)

    async def generate_diagram(
        self,
        request: DiagramRequest
    ) -> DiagramOutput:
        """
        Main entry point for diagram generation

        Args:
            request: User request for diagram

        Returns:
            DiagramOutput with generated diagram and metadata
        """

        start_time = time.time()

        # Agent 1: Analyze request
        analyzed = await self.analyzer.analyze(request)

        # Agent 2: Route to generation method
        routing = self.router.route(analyzed)

        # Generation with retries
        diagram_data = None
        validation_result = None
        attempt = 0

        while attempt < self.max_retries:
            try:
                # Agent 3, 4, or 5: Generate diagram
                if routing.generation_method.value == "programmatic":
                    diagram_data = await self.library_executor.generate(
                        analyzed, routing
                    )
                elif routing.generation_method.value == "hybrid":
                    diagram_data = await self.hybrid_generator.generate(
                        analyzed, routing
                    )
                else:  # ai_only
                    diagram_data = await self.ai_selector.generate(
                        analyzed, routing
                    )

                # Agent 6: Validate
                diagram_data.seek(0)
                validation_result = await self.validator.validate(
                    diagram_data.read(),
                    analyzed,
                    routing.generation_method.value
                )

                if validation_result.passed:
                    break

                # If validation failed, try fallback
                if routing.fallback_generators and attempt < self.max_retries - 1:
                    # Update routing to use fallback
                    routing.primary_generator = routing.fallback_generators[0]
                    routing.generation_method = "ai_only"  # Fallback to AI

                attempt += 1

            except Exception as e:
                print(f"Generation attempt {attempt + 1} failed: {e}")
                attempt += 1

                if attempt >= self.max_retries:
                    raise

        # Agent 7: Post-process
        diagram_data.seek(0)
        outputs = await self.postprocessor.process(
            diagram_data,
            request.output_format,
            {
                "domain": analyzed.domain.value,
                "diagram_type": analyzed.diagram_type,
                "generation_method": routing.generation_method.value
            }
        )

        # Get primary output format
        primary_format = request.output_format[0]
        primary_output = outputs[primary_format]

        # Calculate generation time
        generation_time_ms = int((time.time() - start_time) * 1000)

        # Build final output
        return DiagramOutput(
            diagram_data=primary_output.read(),
            format=primary_format,
            metadata={
                "domain": analyzed.domain.value,
                "subdomain": analyzed.subdomain,
                "diagram_type": analyzed.diagram_type,
                "generation_method": routing.generation_method.value,
                "library_used": routing.library_to_use,
                "ai_model_used": routing.ai_model,
                "parameters": analyzed.parameters,
                "validation_passed": validation_result.passed if validation_result else False,
                "validation_details": validation_result.details if validation_result else {}
            },
            generation_method=routing.generation_method.value,
            quality_score=validation_result.quality_score if validation_result else 0.0,
            validation_passed=validation_result.passed if validation_result else False,
            generation_time_ms=generation_time_ms
        )
```

---

## API Integration (FastAPI)

```python
# api.py - FastAPI integration for Vidya AI

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from src.main import DiagramGenerationOrchestrator
from src.models.diagram_request import DiagramRequest
import base64

app = FastAPI(title="STEM Diagram Generator API")

# Initialize orchestrator
orchestrator = DiagramGenerationOrchestrator({
    "routing_rules_path": "src/config/routing_rules.yaml",
    "openai_api_key": "your-key",
    "anthropic_api_key": "your-key",
    "google_api_key": "your-key",
    "max_retries": 3
})

class DiagramGenerateRequest(BaseModel):
    user_input: str
    user_level: str = "undergraduate"
    style_preference: str = "textbook"
    output_format: list[str] = ["svg", "png"]
    language: str = "en"

class DiagramGenerateResponse(BaseModel):
    diagram_base64: str
    format: str
    metadata: dict
    generation_method: str
    quality_score: float
    validation_passed: bool
    generation_time_ms: int

@app.post("/generate-diagram", response_model=DiagramGenerateResponse)
async def generate_diagram(request: DiagramGenerateRequest):
    """Generate STEM diagram from text description"""

    try:
        # Convert to DiagramRequest
        diagram_request = DiagramRequest(
            user_input=request.user_input,
            user_level=request.user_level,
            style_preference=request.style_preference,
            output_format=request.output_format,
            language=request.language
        )

        # Generate diagram
        output = await orchestrator.generate_diagram(diagram_request)

        # Encode to base64
        diagram_b64 = base64.b64encode(output.diagram_data).decode('utf-8')

        return DiagramGenerateResponse(
            diagram_base64=diagram_b64,
            format=output.format,
            metadata=output.metadata,
            generation_method=output.generation_method,
            quality_score=output.quality_score,
            validation_passed=output.validation_passed,
            generation_time_ms=output.generation_time_ms
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
```

---

## Dependencies (requirements.txt)

```txt
# Core
fastapi==0.109.0
pydantic==2.5.0
uvicorn==0.27.0

# AI/LLM Clients
anthropic==0.18.1
openai==1.12.0
google-generativeai==0.3.2

# Diagram Generation Libraries
schemdraw==0.18
matplotlib==3.8.2
numpy==1.26.3
scipy==1.12.0

# Chemistry
rdkit==2023.9.4
py3Dmol==2.0.4

# Computer Science
graphviz==0.20.1
networkx==3.2.1

# Image Processing
Pillow==10.2.0
cairosvg==2.7.1
reportlab==4.0.9

# Utilities
pyyaml==6.0.1
python-dotenv==1.0.1
redis==5.0.1
celery==5.3.6

# Testing
pytest==8.0.0
pytest-asyncio==0.23.4
```

---

## Environment Variables (.env.example)

```bash
# LLM API Keys
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
GOOGLE_API_KEY=your_google_key

# Configuration
ROUTING_RULES_PATH=src/config/routing_rules.yaml
MAX_RETRIES=3
CACHE_ENABLED=true
REDIS_URL=redis://localhost:6379

# Output Settings
DEFAULT_OUTPUT_FORMAT=svg,png
DEFAULT_DPI=300
DEFAULT_STYLE=textbook
```

---

## Usage Example

```python
# Example usage

from src.main import DiagramGenerationOrchestrator
from src.models.diagram_request import DiagramRequest

# Initialize
orchestrator = DiagramGenerationOrchestrator(config={
    "routing_rules_path": "src/config/routing_rules.yaml",
    "openai_api_key": "sk-...",
    "anthropic_api_key": "sk-ant-...",
    "google_api_key": "...",
    "max_retries": 3
})

# Create request
request = DiagramRequest(
    user_input="Draw a MOSFET common source amplifier with Rd=10k, Rs=1k, VDD=12V",
    user_level="undergraduate",
    style_preference="textbook",
    output_format=["svg", "png"]
)

# Generate diagram
output = await orchestrator.generate_diagram(request)

# Save output
with open("mosfet_amplifier.svg", "wb") as f:
    f.write(output.diagram_data)

print(f"Generation method: {output.generation_method}")
print(f"Quality score: {output.quality_score}")
print(f"Time taken: {output.generation_time_ms}ms")
```

---

## Implementation Priority

1. **Phase 1: Core Framework** (Week 1-2)
   - Set up project structure
   - Implement data models
   - Build Agent 1 (Analyzer) and Agent 2 (Router)
   - Create routing rules for common diagrams

2. **Phase 2: Programmatic Generators** (Week 3-4)
   - Implement Agent 3 (Library Executor)
   - Build Electronics Generator (SchemDraw)
   - Build Mathematics Generator (Matplotlib)
   - Test with common diagram types

3. **Phase 3: AI Integration** (Week 5-6)
   - Implement Agent 5 (AI Selector)
   - Integrate with OpenAI, Google, Anthropic APIs
   - Build prompt templates
   - Test AI generation fallback

4. **Phase 4: Quality & Polish** (Week 7-8)
   - Implement Agent 6 (Validator)
   - Implement Agent 7 (Post-Processor)
   - Add remaining domain generators
   - Performance optimization

5. **Phase 5: Production Ready** (Week 9-10)
   - Add caching layer
   - Implement monitoring
   - Load testing
   - Documentation

---

## Success Metrics

- **Accuracy Rate**: >95% for programmatic generation, >80% for AI generation
- **Generation Time**: <5s for programmatic, <15s for AI
- **Validation Pass Rate**: >90% on first attempt
- **User Satisfaction**: >4.5/5 rating
- **Coverage**: Support for 50+ diagram types across all domains

---

## Notes for Coding Agent

- **Start with Agent 1 and Agent 2** - these are the foundation
- **Use async/await** throughout for better performance
- **Add comprehensive error handling** - graceful degradation is critical
- **Implement caching** early to avoid redundant API calls
- **Write tests** for each agent independently
- **Log everything** for debugging and monitoring
- **Keep prompts in separate files** for easy iteration
- **Make it modular** - easy to add new generators
- **Focus on programmatic first** - it's more reliable than AI

This system prioritizes **accuracy through programmatic generation** while providing **AI fallback for flexibility**. Perfect for educational use cases like Vidya AI where correctness is paramount.
