"""
Claude Code Generator for Universal Diagram Generation

Uses Claude 3.5 Sonnet to generate matplotlib/schemdraw/networkx code
for ANY technical diagram across all domains.
"""

import os
import json
from typing import Dict, Any, Optional
from anthropic import Anthropic
from controllers.config import logger

# Import dynamic element detection
try:
    from utils.get_schemdraw_elements import format_elements_for_prompt, get_common_mistakes
    SCHEMDRAW_AVAILABLE = True
except ImportError:
    SCHEMDRAW_AVAILABLE = False


class ClaudeCodeGenerator:
    """Generates diagram code using Claude 3.5 Sonnet"""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Claude code generator

        Args:
            api_key: Anthropic API key (or use ANTHROPIC_API_KEY env var)
        """
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("Anthropic API key required. Set ANTHROPIC_API_KEY env var or pass api_key parameter")

        # Validate key format early
        if not self.api_key.startswith('sk-ant-'):
            logger.warning(f"ANTHROPIC_API_KEY doesn't start with 'sk-ant-' — may be invalid (first 12 chars: {self.api_key[:12]}...)")

        self.client = Anthropic(api_key=self.api_key)
        self.model = "claude-sonnet-4-20250514"
        self._api_key_valid = None  # Track whether the key actually works

        # Dynamically load valid schemdraw elements
        self.valid_elements_text = ""
        self.invalid_elements = []
        if SCHEMDRAW_AVAILABLE:
            try:
                self.valid_elements_text = format_elements_for_prompt()
                self.invalid_elements = get_common_mistakes()
                logger.info("Dynamically loaded schemdraw elements for validation")
            except Exception as e:
                logger.warning(f"Could not load schemdraw elements dynamically: {e}")
                self.valid_elements_text = "Unable to load elements - use basic ones only"

    async def generate_diagram_code(
        self,
        question_text: str,
        domain: str,
        diagram_type: str,
        tool_type: str = "matplotlib",
        subject_guidance: str = "",
    ) -> str:
        """
        Generate Python diagram code using Claude

        Args:
            question_text: The question text describing what diagram is needed
            domain: Domain (physics, electrical, computer_science, etc.)
            diagram_type: Specific diagram type
            tool_type: Library to use (matplotlib, schemdraw, networkx)
            subject_guidance: Subject-specific code generation guidance from SubjectPromptRegistry

        Returns:
            Complete executable Python code
        """
        logger.info(f"Generating {tool_type} code for {domain}/{diagram_type}")

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            question_text, domain, diagram_type, tool_type, subject_guidance
        )

        # Skip entirely if we already know the key is invalid
        if self._api_key_valid is False:
            raise RuntimeError("Claude API key previously failed authentication — skipping to avoid repeated 401 errors")

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                temperature=0.1,  # Low temperature for consistent, accurate code
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )

            self._api_key_valid = True  # Key works
            code = response.content[0].text

            # Extract code if wrapped in markdown
            code = self._extract_code(code)

            logger.info("Claude code generation successful")
            return code

        except Exception as e:
            error_str = str(e)
            # Mark key as invalid on auth errors so we don't keep retrying
            if '401' in error_str or 'authentication_error' in error_str:
                self._api_key_valid = False
                logger.error(
                    f"Claude API key is INVALID (401 auth error). "
                    f"Check your ANTHROPIC_API_KEY env var. "
                    f"Key starts with: {self.api_key[:12]}... "
                    f"All subsequent Claude calls will be skipped."
                )
            logger.error(f"Claude code generation failed: {error_str}")
            raise

    def _build_system_prompt(self) -> str:
        """Build system prompt for Claude"""

        # Format invalid elements list
        invalid_str = ", ".join([f"elm.{elem}()" for elem in self.invalid_elements]) if self.invalid_elements else "None detected"

        # Build the prompt with dynamically injected elements
        prompt_template = """You are an expert technical diagram code generator. Your task is to generate clean, executable Python code that creates educational-quality technical diagrams.

**CRITICAL REQUIREMENTS:**

1. **Code Quality:**
   - Generate ONLY Python code, no explanations
   - Code must be complete and immediately executable
   - Use correct syntax and library conventions
   - Add comments only for complex sections

2. **Figure Size & DPI — scale to complexity:**
   - Simple diagram (single object, ≤3 labels): figsize=(8, 5)
   - Standard (multi-component, FBD, beam): figsize=(10, 6)
   - Complex (fluid flow, streamlines, truss, multi-label): figsize=(12, 8)
   - Two-panel comparative (e.g. laminar vs turbulent): figsize=(14, 7) with subplots(1, 2)
   - ALWAYS use DPI=200 for crisp, HD-quality output
   - NEVER use figsize smaller than (8, 5)

3. **Textbook Quality Style (apply to ALL diagrams):**
   - Prefer black/white or minimal color: black lines, white fill, light gray shading
   - Set professional font sizes BEFORE creating the figure:
     ```python
     plt.rcParams.update({'font.size': 13, 'font.family': 'serif',
                          'axes.titlesize': 16, 'axes.labelsize': 14,
                          'xtick.labelsize': 12, 'ytick.labelsize': 12,
                          'legend.fontsize': 12, 'lines.linewidth': 1.8})
     ```
   - **TEXT BACKGROUND BOX (MANDATORY):** ALL text labels MUST have a white background box so they are readable when placed on top of diagram elements:
     ```python
     # For ax.text():
     ax.text(x, y, 'Label', fontsize=14, ha='center', va='center',
             bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='gray', alpha=0.9))
     # For ax.annotate():
     ax.annotate('Label', xy=(x,y), xytext=(tx,ty),
                 fontsize=13, ha='center',
                 bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='gray', alpha=0.9),
                 arrowprops=dict(arrowstyle='->', color='black'))
     ```
   - NEVER place bare text without bbox on a diagram — text MUST always be readable
   - Use `ax.annotate()` with `arrowprops=dict(arrowstyle='->', color='black')` for labeled arrows
   - Add ≥10% padding so labels never clip at figure edges
   - Use `plt.tight_layout(pad=1.5)` before saving
   - Save with: `plt.savefig('output.png', dpi=200, bbox_inches='tight', facecolor='white')`

4. **Technical Accuracy:**
   - Extract ALL values, dimensions, labels from the question
   - Use correct symbols and conventions for the domain
   - Label all components clearly with values
   - Include units in labels

4. **Library-Specific Guidelines:**

**MATPLOTLIB** (general plots, 2D diagrams, physics):
```python
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

# Set HD textbook-quality style FIRST — large readable fonts
plt.rcParams.update({'font.size': 13, 'font.family': 'serif',
                     'axes.titlesize': 16, 'axes.labelsize': 14,
                     'xtick.labelsize': 12, 'ytick.labelsize': 12,
                     'legend.fontsize': 12, 'lines.linewidth': 1.8})

# Scale figsize to complexity (see rule 2 above) — MINIMUM (8, 5)
fig, ax = plt.subplots(figsize=(10, 6))  # adjust per complexity

# Use patches.Rectangle, Circle, Polygon for shapes
# Use ax.annotate() with arrowprops for labeled arrows (NOT FancyArrowPatch for labels)
# Use ax.text() only for standalone text with no arrow
# MANDATORY: ALL text must have white background box for readability:
#   bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='gray', alpha=0.9)
# For dimension labels, use fontsize=14 or larger
# For legend, use fontsize=12 with framealpha=0.9

ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.set_aspect('equal')  # For geometric diagrams
ax.axis('off')  # Hide axes for technical diagrams (NOT plots)
plt.tight_layout(pad=1.5)
plt.savefig('output.png', dpi=200, bbox_inches='tight', facecolor='white')
```

**SCHEMDRAW** (electrical circuits — schemdraw 0.19):

API REFERENCE (schemdraw 0.19 — MUST follow exactly):

.at() signature:  element.at(xy, dx=0, dy=0)
   - xy: a Point, a tuple (x,y), or a tuple (Element, 'anchorname')
   - dx, dy: optional float offsets
   - ❌ WRONG: .at(pos, ofst=(1,0))     — 'ofst' kwarg does NOT exist
   - ✅ CORRECT: .at(pos, dx=1.0)        — use dx/dy for offset
   - ✅ CORRECT: .at(pos)                — plain position

Point arithmetic:
   from schemdraw.util import Point
   - Point + Point → OK:   Point((1,2)) + Point((-1,0))  →  Point(0,2)
   - Point + tuple → ERROR: pmos.gate + (-1.5, 0)  CRASHES
   - ✅ ALWAYS wrap tuples: Point(pmos.gate) + Point((-1.5, 0))

NFet/PFet anchors:  source, drain, gate, center, xy
   - PFet drawn .down(): source=top, drain=bottom, gate=left-middle
   - NFet drawn .down(): drain=top, source=bottom, gate=left-middle

VERTICAL LAYOUT (MANDATORY for CMOS circuits):
   - Draw circuits TOP-TO-BOTTOM: VDD → PMOS → output node → NMOS → GND
   - PMOS is ALWAYS on top (source to VDD), NMOS is ALWAYS on bottom (source to GND)
   - Use .down() direction for the main transistor chain (NOT .right())
   - Gates connect horizontally to the left, output goes horizontally to the right

ANTI-OVERLAP LAYOUT RULES:
   1. Use d.config(unit=3) for adequate spacing between components
   2. Chain components via .anchor(): pmos drain → nmos drain
   3. NEVER place two transistors at the same raw coordinates
   4. Use .at(previous_element.anchor) to chain, NOT manual coordinates

Valid elements (schemdraw.elements):
   {SCHEMDRAW_ELEMENTS}

❌ DO NOT USE (they don't exist):  {INVALID_ELEMENTS}

Logic gates: import schemdraw.logic as logic
   logic.And, logic.Or, logic.Not, logic.Nand, logic.Nor, logic.Xor, logic.Buf
   ❌ elm.Nand() does NOT exist — use logic.Nand()

★ WORKING CMOS INVERTER — VERTICAL layout, VDD top, GND bottom (copy EXACTLY):
```python
import matplotlib
matplotlib.use('Agg')
import schemdraw
import schemdraw.elements as elm
from schemdraw.util import Point

with schemdraw.Drawing(show=False) as d:
    d.config(fontsize=13, unit=3)

    # === TOP-TO-BOTTOM vertical chain ===
    # 1. VDD at the very top
    vdd = d.add(elm.Vdd().label('VDD = 5V'))

    # 2. PMOS directly below VDD (source connects to VDD)
    pmos = d.add(elm.PFet().down().anchor('source').label('PMOS', loc='left'))

    # 3. Output node at PMOS drain (middle of circuit)
    d.add(elm.Dot().at(pmos.drain))

    # 4. NMOS directly below PMOS (drain connects to PMOS drain)
    nmos = d.add(elm.NFet().at(pmos.drain).down().anchor('drain').label('NMOS', loc='left'))

    # 5. GND at the very bottom
    d.add(elm.Ground())

    # === Horizontal connections ===
    # Input: gates go LEFT
    d.add(elm.Line().at(pmos.gate).left().length(1.5))
    vin_top = d.here
    d.add(elm.Line().at(nmos.gate).left().length(1.5))
    vin_bot = d.here
    d.add(elm.Line().at(vin_top).down().toy(vin_bot))
    d.add(elm.Label().at(vin_top).label('Vin', loc='left'))

    # Output: goes RIGHT from middle node
    d.add(elm.Line().at(pmos.drain).right().length(1.5).label('Vout', loc='right'))

    d.save('output.png', dpi=200)
```

★ WORKING CMOS NAND GATE — VERTICAL layout, VDD top, GND bottom:
```python
import matplotlib
matplotlib.use('Agg')
import schemdraw
import schemdraw.elements as elm
from schemdraw.util import Point

with schemdraw.Drawing(show=False) as d:
    d.config(fontsize=13, unit=3)

    # === VERTICAL chain: VDD → PMOS (parallel) → NMOS (series) → GND ===
    # 1. VDD at top
    vdd = d.add(elm.Vdd().label('VDD'))

    # 2. PMOS P1 (source to VDD, drawn downward)
    p1 = d.add(elm.PFet().down().anchor('source').label('P1', loc='left'))
    d.add(elm.Dot().at(p1.drain))  # output node in the middle

    # 3. NMOS N1 in series below output (drain at output)
    n1 = d.add(elm.NFet().at(p1.drain).down().anchor('drain').label('N1', loc='left'))

    # 4. NMOS N2 in series below N1
    n2 = d.add(elm.NFet().down().anchor('drain').label('N2', loc='left'))

    # 5. GND at bottom
    d.add(elm.Ground())

    # PMOS P2 parallel to P1 (source also at VDD, drain at output)
    p2 = d.add(elm.PFet().at(vdd.start).down().anchor('source').flip().label('P2', loc='right'))
    d.add(elm.Line().at(p2.drain).left().tox(p1.drain))  # connect to output

    # Gate A (P1 + N1 gates), Gate B (P2 + N2 gates)
    d.add(elm.Line().at(p1.gate).left().length(1))
    d.add(elm.Label().at(d.here).label('A', loc='left'))
    d.add(elm.Line().at(n1.gate).left().length(1))
    a_top = Point(p1.gate) + Point((-1, 0))
    a_bot = Point(n1.gate) + Point((-1, 0))
    d.add(elm.Line().at(a_top).down().toy(a_bot))

    d.add(elm.Line().at(p2.gate).right().length(1))
    d.add(elm.Label().at(d.here).label('B', loc='right'))
    d.add(elm.Line().at(n2.gate).left().length(1))

    # Output goes RIGHT from middle node
    d.add(elm.Line().at(p1.drain).right().length(2).label('Vout', loc='right'))
    d.save('output.png', dpi=200)
```

**NETWORKX** (graphs, trees, algorithms):
```python
import networkx as nx
import matplotlib.pyplot as plt

plt.rcParams.update({'font.size': 13, 'font.family': 'serif'})
fig, ax = plt.subplots(figsize=(10, 7))

G = nx.Graph()  # or nx.DiGraph() for directed

# Add nodes and edges
G.add_node('A', label='Node A')
G.add_edge('A', 'B', weight=5)

# Choose layout
pos = nx.spring_layout(G)  # or hierarchical_layout, circular_layout

# Draw with large readable labels
nx.draw(G, pos, with_labels=True, node_color='lightblue',
        node_size=700, font_size=13, font_weight='bold')

plt.tight_layout(pad=1.5)
plt.savefig('output.png', dpi=200, bbox_inches='tight', facecolor='white')
```

5. **Domain-Specific Requirements:**

**SUBSCRIPTS & SUPERSCRIPTS (MANDATORY — applies to ALL domains):**
- ALWAYS use matplotlib mathtext for subscripts: `$y_1$`, `$y_2$`, `$P_1$`, `$V_{out}$`, `$F_{drag}$`
- NEVER write plain text like 'y1' or 'y2' — ALWAYS use `$y_1$` and `$y_2$`
- For Greek letters with subscripts: `$\\rho_{water}$`, `$\\mu_{air}$`
- Example: `ax.text(x, y, r'$y_1$', fontsize=16, bbox=dict(...))`
- For axis labels: `ax.set_ylabel(r'Depth $y$ (m)', fontsize=14)`

**Fluid Systems (manometers, pipes):**
- For U-tube: Draw TWO vertical rectangles + horizontal connection
- Show fluid layers with different colors
- Label heights, pressures, fluid names using mathtext subscripts
- Example: `ax.text(x, y, r'$P_1$', fontsize=16, bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='gray', alpha=0.9))`
- Use `$y_1$`, `$y_2$` for depths — NEVER plain 'y1', 'y2'
- ALL dimension labels and annotations MUST have white background bbox

**Electrical Circuits (schemdraw 0.19):**
⚠️  CRITICAL API RULES:
- .at(xy, dx=0, dy=0) — NO 'ofst' kwarg!
- Point arithmetic: ALWAYS use Point(anchor) + Point((dx,dy)), NEVER anchor + (dx,dy)
- from schemdraw.util import Point  — MUST import if doing Point math
- VERTICAL LAYOUT (MANDATORY): VDD on top → PMOS → output → NMOS → GND on bottom
- Use .down() for CMOS transistor chains (NEVER .right())
- Use .anchor('drain') / .anchor('source') to chain transistors WITHOUT overlap
- d.config(unit=3) for proper spacing between components
- Gates connect LEFT horizontally, output goes RIGHT horizontally
- ALWAYS add matplotlib.use('Agg') BEFORE any schemdraw imports
- ALWAYS use schemdraw.Drawing(show=False)
- Valid transistors: NFet (NMOS), PFet (PMOS), NMos, PMos, BjtNpn, BjtPnp
- Valid passive: Resistor, Capacitor, Inductor, Diode, Zener, LED
- Valid sources: SourceV, SourceI, Opamp, Ground, Vdd, Vss
- INVALID: Mosfet, MOSFET, PTrans (these don't exist!)
- Logic gates: import schemdraw.logic as logic → logic.Nand(), etc.
  elm.Nand() does NOT exist!

**Data Structures:**
- Use hierarchical layout for trees
- Label nodes clearly with bbox background
- Show parent-child relationships
- Use different colors for different types

**Geometry/Physics:**
- Use matplotlib.patches for shapes
- Show dimensions with arrows (FancyArrowPatch)
- Label angles, forces, distances with bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='gray', alpha=0.9)
- Use equal aspect ratio
- ALL text annotations must have white background box for readability

**Return ONLY Python code. No explanations, no markdown formatting (unless it's code block), no extra text.**"""

        # Replace placeholders with actual values
        return prompt_template.replace(
            "{SCHEMDRAW_ELEMENTS}", self.valid_elements_text
        ).replace(
            "{INVALID_ELEMENTS}", invalid_str
        )

    def _build_user_prompt(
        self,
        question_text: str,
        domain: str,
        diagram_type: str,
        tool_type: str,
        subject_guidance: str = "",
    ) -> str:
        """Build user prompt"""

        tool_guidance = self._get_tool_specific_guidance(tool_type, domain, diagram_type)

        subject_section = ""
        if subject_guidance:
            subject_section = f"\n**Subject-Specific Guidance:**\n{subject_guidance}\n"

        return f"""Generate complete Python code to create this diagram:

**Question/Description:**
{question_text}

**Domain:** {domain}
**Diagram Type:** {diagram_type}
**Library to use:** {tool_type}
{subject_section}
{tool_guidance}

**Requirements:**
1. Scale figsize to diagram complexity (see system prompt rule 2 — MINIMUM (8,5), use (10,7) or (14,7) for fluid/complex diagrams)
2. Extract ALL values, dimensions, labels from the question
3. Use correct technical symbols and conventions for the domain
4. Apply textbook style: serif font, black/white palette, rcParams with font.size=13, axes.labelsize=14
5. Save to 'output.png' with: plt.savefig('output.png', dpi=200, bbox_inches='tight', facecolor='white')
6. Use fontsize=14+ for dimension labels, axis labels, and annotations so text is readable in PDF
7. MANDATORY: Use matplotlib mathtext for ALL subscripts — $y_1$ NOT 'y1', $P_2$ NOT 'P2', $V_{{out}}$ NOT 'Vout'
8. MANDATORY: ALL text labels must have white bbox background for readability
9. ANSWER HIDING (CRITICAL): This is a student assignment — the diagram must NOT reveal the answer.
   - For timing/waveform diagrams: draw ONLY INPUT waveforms (CLK, D, A, B, EN, RESET).
     OUTPUT signals (Q, Q1, Q2, Q̄, Y) must be BLANK dashed lines with "?" labels.
     NEVER draw actual output waveform values — students must determine these.
   - For counter/state machine diagrams: show ONLY the circuit topology and initial state.
     Do NOT show state transition sequences or output values.
   - For any diagram where the question asks "find", "determine", "calculate", "draw",
     or "describe" an output — do NOT include that output in the diagram.

Return ONLY the Python code, ready to execute."""

    def _get_tool_specific_guidance(
        self,
        tool_type: str,
        domain: str,
        diagram_type: str
    ) -> str:
        """Get specific guidance based on tool and domain"""

        guidance = {
            'matplotlib': {
                'manometer': """
**Manometer-Specific:**
- For U-tube: Draw left tube, bottom connection, right tube
- Use patches.Rectangle for tubes and fluid layers
- Show different fluid heights in each tube
- Label: fluid names, heights, pressure points
- Use different colors: mercury (silver/gray), water (blue), oil (orange)

Example structure:
```python
# Left tube
left_tube = patches.Rectangle((2, 2), 0.4, 5, fill=False, edgecolor='black', linewidth=2)
# Fluid in left tube
left_fluid = patches.Rectangle((2, 2), 0.4, 3.5, fill=True, facecolor='silver', alpha=0.7)
# Add labels with heights
```
""",
                'free_body_diagram': """
**Free Body Diagram:**
- Draw object (block, beam, etc.) using Rectangle
- Show ALL forces as arrows (FancyArrowPatch)
- Label forces with names and magnitudes
- Use different colors for different force types
- Show ground/surface with hatching
- Mark center of mass
""",
                'circuit': """
**Circuit Diagram (using matplotlib patches):**
- Use basic shapes for components
- Connect with lines
- Label all components
- Show current flow with arrows
""",
                'default': """
**General matplotlib diagram:**
- Use patches for shapes
- Use ax.plot() for lines
- Use ax.text() for labels
- Use FancyArrowPatch for arrows
- Set appropriate xlim, ylim
"""
            },
            'schemdraw': {
                'default': """
**SchemDraw 0.19 circuit — CRITICAL API RULES:**

1. ALWAYS start with:
   import matplotlib; matplotlib.use('Agg')
   import schemdraw; import schemdraw.elements as elm
   from schemdraw.util import Point

2. .at() API:  element.at(xy, dx=0, dy=0)
   - ❌ .at(pos, ofst=(1,0))  — 'ofst' does NOT exist, will crash!
   - ✅ .at(pos, dx=1.0, dy=0)  — use dx/dy for offsets
   - ✅ .at(pmos.drain)  — position at an anchor

3. Point arithmetic:
   - ✅ Point(pmos.gate) + Point((-1.5, 0))  — ALWAYS wrap both sides
   - ❌ pmos.gate + (-1.5, 0)  — CRASHES with TypeError

4. VERTICAL LAYOUT (MANDATORY for CMOS):
   - Draw TOP-TO-BOTTOM: VDD → PMOS → output node → NMOS → GND
   - PMOS on top (source to VDD), NMOS on bottom (source to GND)
   - Use .down() for transistor chain, NEVER .right()
   - Gates go LEFT, output goes RIGHT

5. ANTI-OVERLAP LAYOUT:
   - Use d.config(unit=3) for proper spacing
   - Chain: .at(previous.drain).anchor('drain') so components don't overlap
   - NEVER d.add(elm.NFet()) after d.add(elm.PFet()) without .at() positioning!

6. NFet/PFet anchors: source, drain, gate, center
   - PFet .down(): source=top, drain=bottom, gate=left-middle
   - NFet .down(): drain=top, source=bottom, gate=left-middle

6. Gate connections: draw Line from gate anchor leftward, then vertical Line to join

7. Valid elements: Resistor, Capacitor, Inductor, Diode, NFet, PFet, NMos, PMos,
   BjtNpn, BjtPnp, Opamp, SourceV, SourceI, Ground, Vdd, Vss, Line, Dot, Label
   ❌ INVALID: Mosfet, MOSFET, PTrans, NTrans — do NOT exist

8. Logic gates: import schemdraw.logic as logic → logic.Nand(), logic.And(), etc.
   ❌ elm.Nand() does NOT exist!

Follow the CMOS INVERTER and CMOS NAND examples in the system prompt EXACTLY.
"""
            },
            'networkx': {
                'default': """
**NetworkX graph:**
- Create graph: nx.Graph() or nx.DiGraph()
- Add nodes: G.add_node(node_id, **attrs)
- Add edges: G.add_edge(source, target, **attrs)
- Choose layout: spring, hierarchical, circular
- Draw with labels and clear styling
"""
            }
        }

        # Get specific guidance if available
        if tool_type in guidance:
            if diagram_type in guidance[tool_type]:
                return guidance[tool_type][diagram_type]
            return guidance[tool_type].get('default', '')

        return ''

    def _extract_code(self, response: str) -> str:
        """Extract code from response (handles markdown code blocks)"""

        # If response is wrapped in ```python ... ```, extract it
        if '```python' in response:
            start = response.find('```python') + len('```python')
            end = response.find('```', start)
            if end != -1:
                code = response[start:end].strip()
                return code

        # If wrapped in ``` ... ```, extract it
        if '```' in response:
            start = response.find('```') + 3
            end = response.find('```', start)
            if end != -1:
                code = response[start:end].strip()
                return code

        # Otherwise return as-is
        return response.strip()


# Convenience function for direct use
async def generate_code_with_claude(
    question_text: str,
    domain: str = "general",
    diagram_type: str = "diagram",
    tool_type: str = "matplotlib",
    api_key: Optional[str] = None
) -> str:
    """
    Convenience function to generate diagram code

    Args:
        question_text: Description of what diagram to create
        domain: Domain (physics, electrical, etc.)
        diagram_type: Specific type
        tool_type: Library (matplotlib, schemdraw, networkx)
        api_key: Optional Anthropic API key

    Returns:
        Executable Python code
    """
    generator = ClaudeCodeGenerator(api_key=api_key)
    return await generator.generate_diagram_code(
        question_text, domain, diagram_type, tool_type
    )
