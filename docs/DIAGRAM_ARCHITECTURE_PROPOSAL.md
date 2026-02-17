# Universal Diagram Generation Architecture

## Problem
Current system is too manometer-specific. Need a universal system that handles:
- **Computer Science**: Data structures, algorithms, architectures
- **Electrical**: Circuits, waveforms, block diagrams, semiconductors
- **Mechanics**: Force diagrams, free body diagrams, linkages
- **Physics**: Pressure systems, optics, waves, fields
- **Mathematics**: Geometry, graphs, 3D plots, coordinate systems
- **Chemistry**: Molecular structures, reactions, apparatus
- **Any scientific domain**

---

## Solution Architecture

### 1. Smart Tool Router (Recommended)

```
Question → Domain Classifier → Tool Router → Specialized Tool → Diagram
```

**Flow**:
1. Analyze question to identify domain/topic
2. Route to most appropriate tool:
   - Matplotlib → Plots, graphs, 2D geometry, physics diagrams
   - Schemdraw → Electrical circuits
   - NetworkX → Trees, graphs, networks
   - Manim → Beautiful physics/math animations (static export)
   - Graphviz → Flowcharts, hierarchical diagrams
   - SymPy → Mathematical geometry, symbolic plots
   - API Model → Complex 3D, photorealistic, or when code fails

---

## Proposed Implementation

### Architecture 1: **Tool Router with Domain Experts** (Best Accuracy)

```python
# diagram_router.py

class DiagramRouter:
    """Routes questions to appropriate diagram generation tools"""

    DOMAIN_TOOLS = {
        'data_structures': 'networkx_tool',
        'algorithms': 'networkx_tool',
        'graphs_trees': 'networkx_tool',

        'electrical_circuits': 'schemdraw_tool',
        'electronics': 'schemdraw_tool',
        'semiconductors': 'schemdraw_tool',

        'plots_graphs': 'matplotlib_tool',
        'physics_mechanics': 'matplotlib_tool',
        'fluid_systems': 'matplotlib_tool',
        'geometry_2d': 'matplotlib_tool',
        'pressure_systems': 'matplotlib_tool',

        'flowcharts': 'graphviz_tool',
        'state_machines': 'graphviz_tool',
        'hierarchies': 'graphviz_tool',

        'math_symbolic': 'sympy_tool',
        'geometry_3d': 'sympy_tool',

        'complex_3d': 'api_model',  # Fallback to AI
        'photorealistic': 'api_model',
    }

    async def classify_domain(self, question: str) -> str:
        """Use LLM to classify question domain"""
        prompt = f"""Classify this question into ONE domain:

        Question: {question}

        Domains:
        - data_structures: arrays, trees, graphs, linked lists
        - algorithms: sorting, searching, dynamic programming
        - electrical_circuits: resistors, capacitors, MOSFETs, amplifiers
        - electronics: logic gates, semiconductors, transistors
        - plots_graphs: line plots, scatter, bar charts, histograms
        - physics_mechanics: forces, motion, free body diagrams
        - fluid_systems: manometers, pipes, flow, pressure
        - geometry_2d: shapes, coordinate geometry, trigonometry
        - pressure_systems: manometers, pressure gauges, U-tubes
        - flowcharts: process flows, decision trees
        - state_machines: FSM, automata
        - math_symbolic: calculus, algebra, symbolic math
        - geometry_3d: 3D shapes, surfaces, volumes
        - complex_3d: complex 3D scenes
        - photorealistic: realistic renderings

        Return ONLY the domain name."""

        # Call LLM for classification
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",  # Fast and cheap for classification
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        return response.choices[0].message.content.strip()

    async def route_to_tool(self, question: str) -> str:
        """Route question to appropriate tool"""
        domain = await self.classify_domain(question)
        tool = self.DOMAIN_TOOLS.get(domain, 'matplotlib_tool')  # Default to matplotlib
        logger.info(f"Routed {domain} → {tool}")
        return tool
```

---

### Architecture 2: **Multi-Tool Cascade** (Best Quality)

Try multiple tools in order of accuracy:

```python
async def generate_with_cascade(self, question: str) -> bytes:
    """Try tools in order until one succeeds"""

    # 1. Try domain-specific code tool (best accuracy)
    tool = await self.route_to_tool(question)
    result = await self.try_tool(tool, question)
    if result: return result

    # 2. Fallback to matplotlib (most versatile)
    result = await self.try_tool('matplotlib_tool', question)
    if result: return result

    # 3. Final fallback to AI generation
    return await self.generate_with_api(question)
```

---

## Best API-Based Image Generation Models

### Comparison Table

| Model | Strengths | Weaknesses | Technical Accuracy | Cost | Speed |
|-------|-----------|------------|-------------------|------|-------|
| **DALL-E 3** | General images, good composition | Poor technical accuracy | ⭐⭐ | $$$ | Medium |
| **Claude 3.5 Sonnet + Artifacts** | Generates SVG/code, very accurate | Requires prompt engineering | ⭐⭐⭐⭐⭐ | $$ | Fast |
| **Gemini 2.0 Flash** | Good at technical diagrams | Limited availability | ⭐⭐⭐⭐ | $ | Very Fast |
| **Ideogram 2.0** | Excellent for infographics/charts | API in beta | ⭐⭐⭐⭐ | $$ | Medium |
| **GPT-4 + Code Interpreter** | Generates matplotlib code | Token heavy | ⭐⭐⭐⭐ | $$$ | Slow |

---

## Recommendations

### Option 1: **Claude 3.5 Sonnet for Code Generation** (BEST - Recommended)

**Why**:
- ✅ Generates clean matplotlib/SVG code
- ✅ Understands technical requirements perfectly
- ✅ Can create any type of diagram
- ✅ Already using Anthropic API

**Implementation**:

```python
# diagram_code_generator.py

class ClaudeCodeGenerator:
    """Use Claude to generate diagram code"""

    async def generate_diagram_code(
        self,
        question: str,
        domain: str,
        tool_type: str
    ) -> str:
        """Generate Python code for diagram"""

        prompt = f"""Generate complete, executable Python code to create a diagram for this question.

Question: {question}
Domain: {domain}
Tool: {tool_type}

Requirements:
1. Use figsize=(6, 4) for compact size
2. Include all necessary imports
3. Add clear labels, titles, and legends
4. Use accurate values from the question
5. Save to 'output.png' with dpi=100
6. For {tool_type}:
   {self._get_tool_guidelines(tool_type)}

Return ONLY the Python code, no explanations."""

        response = anthropic_client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        return response.content[0].text

    def _get_tool_guidelines(self, tool_type: str) -> str:
        """Tool-specific guidelines"""
        guidelines = {
            'matplotlib': """
                - Use matplotlib.patches for shapes
                - Use different colors for different elements
                - Add grid if helpful
                - Use tight_layout()
            """,
            'schemdraw': """
                - Import schemdraw and schemdraw.elements as elm
                - Use correct circuit symbols
                - Label all components with values
                - Use proper electrical conventions
            """,
            'networkx': """
                - Create graph with nx.Graph() or nx.DiGraph()
                - Use appropriate layout (spring, hierarchical, circular)
                - Label nodes clearly
                - Use edge labels for weights if applicable
            """,
        }
        return guidelines.get(tool_type, "Follow best practices for this tool")
```

**Pros**:
- ⭐⭐⭐⭐⭐ Technical accuracy
- Works for ANY domain
- Generates clean, executable code
- Cost-effective

**Cons**:
- Requires code execution (already implemented)

---

### Option 2: **Gemini 2.0 Flash + Imagen** (Good for complex diagrams)

**Why**:
- Better at technical diagrams than DALL-E 3
- Faster and cheaper
- Good understanding of scientific concepts

**Implementation**:

```python
# gemini_diagram_generator.py

import google.generativeai as genai

class GeminiDiagramGenerator:
    """Use Gemini for diagram generation"""

    def __init__(self):
        genai.configure(api_key=os.environ['GOOGLE_API_KEY'])
        self.model = genai.GenerativeModel('gemini-2.0-flash-exp')

    async def generate_diagram(self, question: str, domain: str) -> bytes:
        """Generate diagram using Gemini"""

        # First, generate detailed diagram description
        description_prompt = f"""Create a detailed description for a technical diagram:

Question: {question}
Domain: {domain}

Describe:
1. Overall layout and structure
2. All components/elements with exact labels
3. Dimensions, values, and measurements
4. Colors for different elements
5. Annotations and arrows
6. Style: Clean, educational, textbook-quality

Be extremely specific and technical."""

        description = self.model.generate_content(description_prompt).text

        # Then generate image using imagen
        # Note: Imagen integration coming soon to Gemini API
        # For now, use Gemini to generate code instead

        code_prompt = f"""Generate Python matplotlib code for:

{description}

Requirements:
- figsize=(6, 4)
- Technical accuracy is critical
- Clear labels and values
- Save to 'output.png'

Return ONLY Python code."""

        code = self.model.generate_content(code_prompt).text

        # Extract and execute code
        return await self.execute_code(code)
```

**Pros**:
- Fast and cheap
- Better than DALL-E for technical content
- Good at understanding context

**Cons**:
- Still not as accurate as code generation

---

### Option 3: **Hybrid Router System** (BEST OVERALL)

Combine multiple approaches:

```python
class HybridDiagramGenerator:
    """Smart hybrid system"""

    async def generate(self, question: str) -> bytes:
        # 1. Classify domain
        domain = await self.classify_domain(question)

        # 2. Route to best method
        if domain in ['data_structures', 'algorithms', 'electrical_circuits']:
            # Use code generation (most accurate)
            tool = self.route_to_code_tool(domain)
            code = await self.claude_generate_code(question, tool)
            return await self.execute_code(code)

        elif domain in ['complex_3d', 'molecular_structures']:
            # Use Gemini/DALL-E for complex 3D
            return await self.gemini_generate_image(question)

        else:
            # Default: Claude generates matplotlib code
            code = await self.claude_generate_code(question, 'matplotlib')
            return await self.execute_code(code)
```

---

## Recommended Libraries to Add

### 1. **Manim** (For beautiful physics/math diagrams)
```bash
pip install manim
```

**Best for**: Physics animations, mathematical proofs, geometry

**Example**:
```python
from manim import *

class ForcesDiagram(Scene):
    def construct(self):
        # Create beautiful force diagram
        pass

# Render to PNG
scene = ForcesDiagram()
scene.render()
```

---

### 2. **Graphviz** (For flowcharts, trees, state machines)
```bash
pip install graphviz
```

**Best for**: Flowcharts, decision trees, state machines, hierarchies

**Example**:
```python
from graphviz import Digraph

dot = Digraph()
dot.node('A', 'Start')
dot.node('B', 'Process')
dot.edge('A', 'B')
dot.render('flowchart', format='png')
```

---

### 3. **SymPy + matplotlib** (For symbolic math)
```bash
pip install sympy
```

**Best for**: Calculus plots, geometric constructions, symbolic math

**Example**:
```python
from sympy import symbols, plot, sin
x = symbols('x')
plot(sin(x), (x, -pi, pi))
```

---

### 4. **Plotly** (Interactive, publication quality)
```bash
pip install plotly kaleido
```

**Best for**: 3D plots, interactive diagrams, complex visualizations

---

## Implementation Roadmap

### Phase 1: Generalize Current System (1-2 hours)
1. ✅ Remove manometer-specific prompt
2. ✅ Add domain-agnostic guidelines
3. ✅ Keep existing tools (matplotlib, schemdraw, networkx)

### Phase 2: Add Tool Router (2-3 hours)
1. Implement DiagramRouter class
2. Add domain classification
3. Route questions to appropriate tools

### Phase 3: Add Claude Code Generation (3-4 hours)
1. Implement ClaudeCodeGenerator
2. Use Claude 3.5 Sonnet to generate matplotlib/schemdraw code
3. Execute generated code

### Phase 4: Add Specialized Libraries (2-3 hours)
1. Add Graphviz support for flowcharts
2. Add Manim support for physics diagrams
3. Add SymPy support for math diagrams

### Phase 5: Add API Fallback (1-2 hours)
1. Add Gemini 2.0 Flash as fallback
2. Keep DALL-E 3 as final fallback

---

## Recommended Implementation (Immediate)

**Start with Claude 3.5 Sonnet for code generation**:

```python
# Updated diagram_tools.py

DIAGRAM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "claude_code_tool",
            "description": """Generate diagram code using Claude 3.5 Sonnet.
            Works for ANY domain: CS, electrical, mechanics, physics, math, chemistry.
            Claude generates clean matplotlib/schemdraw/networkx code.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain: data_structures, circuits, physics, geometry, etc."
                    },
                    "tool_type": {
                        "type": "string",
                        "enum": ["matplotlib", "schemdraw", "networkx", "graphviz"],
                        "description": "Which library to use"
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description of what diagram should show"
                    }
                },
                "required": ["domain", "tool_type", "description"]
            }
        }
    },
    # Keep existing tools...
]
```

---

## Cost Comparison

| Approach | Cost per Diagram | Accuracy | Speed |
|----------|------------------|----------|-------|
| Claude Code Gen | ~$0.01 | ⭐⭐⭐⭐⭐ | Fast |
| DALL-E 3 | ~$0.04 | ⭐⭐ | Medium |
| Gemini 2.0 Flash | ~$0.005 | ⭐⭐⭐⭐ | Very Fast |
| Matplotlib (current) | ~$0.01 | ⭐⭐⭐⭐ | Fast |

**Recommendation**: Claude Code Generation is best bang-for-buck.

---

## Next Steps

1. **Immediate**: Generalize system prompt (remove manometer specifics)
2. **Phase 1**: Implement Claude code generation
3. **Phase 2**: Add tool router
4. **Phase 3**: Add Graphviz + Manim libraries
5. **Phase 4**: Add Gemini as fallback

Want me to implement any of these phases?
