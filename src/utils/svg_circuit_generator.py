"""
SVG Circuit Diagram Generator

Uses Claude to generate professional, textbook-quality circuit diagrams
as SVG markup, then converts to PNG using cairosvg.

This produces vertical CMOS layouts that look like real textbook diagrams
(VDD on top → PMOS → output → NMOS → GND on bottom), unlike SchemDraw's
horizontal-oriented output.
"""

import os
import io
import tempfile
from typing import Optional
from anthropic import Anthropic
from controllers.config import logger

try:
    import cairosvg
    CAIROSVG_AVAILABLE = True
except ImportError:
    CAIROSVG_AVAILABLE = False
    logger.warning("cairosvg not available — SVG circuit rendering disabled")


# ─── MOSFET Symbol Templates (for reference in prompt) ───

NMOS_SYMBOL_SVG = """<!-- NMOS transistor at position (cx, cy), gate on left, drain on top, source on bottom -->
<!-- Body: vertical line -->
<line x1="{cx}" y1="{cy_top}" x2="{cx}" y2="{cy_bot}" stroke="black" stroke-width="2"/>
<!-- Gate line (horizontal, to the left) -->
<line x1="{gx}" y1="{cy}" x2="{cx_gate}" y2="{cy}" stroke="black" stroke-width="2"/>
<!-- Gate plate (vertical, parallel to body) -->
<line x1="{cx_gate}" y1="{cy_top}" x2="{cx_gate}" y2="{cy_bot}" stroke="black" stroke-width="2"/>
<!-- Drain arrow pointing inward (NMOS) -->"""

PMOS_SYMBOL_SVG = """<!-- PMOS transistor: same as NMOS but with circle (bubble) on gate -->
<!-- Add a small circle between gate line and gate plate to indicate PMOS -->
<circle cx="{bubble_cx}" cy="{cy}" r="4" fill="white" stroke="black" stroke-width="1.5"/>"""


class SVGCircuitGenerator:
    """
    Generates professional circuit diagrams using Claude → SVG → PNG pipeline.

    The key insight: Claude can generate precise SVG markup for circuit diagrams
    that look like textbook schematics — vertical CMOS layouts, clean wiring,
    proper transistor symbols with gate bubbles, labeled nodes.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("Anthropic API key required")

        self.client = Anthropic(api_key=self.api_key)
        self.model = "claude-sonnet-4-20250514"
        self._api_key_valid = None

    def _build_system_prompt(self) -> str:
        return """You are an expert circuit diagram generator. You produce **SVG markup** for professional, textbook-quality electrical circuit schematics.

**YOUR OUTPUT**: Return ONLY valid SVG markup (no explanation, no markdown, no code fences). The SVG must be self-contained and render perfectly.

**CRITICAL LAYOUT RULES FOR CMOS CIRCUITS:**

1. **VERTICAL orientation** — ALWAYS draw circuits top-to-bottom:
   - VDD power rail at the TOP
   - PMOS transistor(s) below VDD (source connected to VDD)
   - Output node in the MIDDLE
   - NMOS transistor(s) below output (drain connected to output)
   - VSS/GND ground rail at the BOTTOM

2. **MOSFET Symbol Convention:**
   - Draw MOSFETs as standard textbook symbols:
     * A vertical channel line (body)
     * A vertical gate plate parallel to the body, separated by a small gap
     * Horizontal gate lead extending LEFT from the gate plate
     * Drain terminal at the top of the body
     * Source terminal at the bottom of the body
   - **PMOS**: Add a small circle (bubble) on the gate lead between the horizontal gate line and the gate plate
   - **NMOS**: No bubble on the gate — direct connection from gate lead to gate plate
   - The channel body should have 3 horizontal stubs connecting to drain (top), source (bottom), and a middle connection

3. **Wiring:**
   - Use clean, orthogonal (horizontal and vertical) wires only — no diagonal lines
   - Wires are simple black lines, stroke-width 2
   - Junction dots (filled circles, r=3) where 3+ wires meet
   - Connection nodes are small open circles (r=4, fill=white, stroke=black) for output terminals

4. **Labels:**
   - Use clear sans-serif font (font-family="Arial, Helvetica, sans-serif")
   - Input labels (A, B, Vin) on the LEFT side
   - Output labels (Out, Vout) on the RIGHT side
   - VDD/VSS labels at top/bottom
   - Component values where specified (e.g., "R = 2kΩ", "CL = 2fF")
   - Font size 14-16px for labels, 12px for values

5. **Sizing:**
   - SVG viewBox should be appropriately sized for the circuit complexity
   - Typical: viewBox="0 0 300 400" for simple inverter, "0 0 400 500" for 2-input gates
   - Leave adequate margins (30-40px) on all sides
   - Set width and height attributes matching the viewBox

6. **Style:**
   - Black lines on white background (no background rect needed)
   - stroke-width: 2 for wires and transistor bodies
   - stroke-width: 1.5 for gate details and bubbles
   - Clean, minimal design — like a university textbook

**MOSFET DRAWING TEMPLATE** (copy this pattern exactly):

For an NMOS transistor centered at (cx, cy) with channel_half_height=25:
```svg
<!-- NMOS Channel body: 3 horizontal stubs from a vertical line -->
<line x1="CX" y1="CY-25" x2="CX" y2="CY-8" stroke="black" stroke-width="2"/>  <!-- drain stub down to gap -->
<line x1="CX" y1="CY-8" x2="CX+15" y2="CY-8" stroke="black" stroke-width="2"/>  <!-- top channel stub -->
<line x1="CX+15" y1="CY-25" x2="CX+15" y2="CY-8" stroke="black" stroke-width="2"/>  <!-- drain vertical -->

<line x1="CX" y1="CY+8" x2="CX" y2="CY+25" stroke="black" stroke-width="2"/>  <!-- source stub up from gap -->
<line x1="CX" y1="CY+8" x2="CX+15" y2="CY+8" stroke="black" stroke-width="2"/>  <!-- bottom channel stub -->
<line x1="CX+15" y1="CY+8" x2="CX+15" y2="CY+25" stroke="black" stroke-width="2"/>  <!-- source vertical -->

<line x1="CX" y1="CY" x2="CX+15" y2="CY" stroke="black" stroke-width="2"/>  <!-- middle stub (for body connection) -->

<!-- Gate plate (vertical, left of channel, with gap) -->
<line x1="CX-5" y1="CY-20" x2="CX-5" y2="CY+20" stroke="black" stroke-width="2"/>

<!-- Gate lead (horizontal, going left) -->
<line x1="CX-5" y1="CY" x2="CX-40" y2="CY" stroke="black" stroke-width="2"/>
```

For a PMOS, add a circle bubble on the gate lead:
```svg
<circle cx="CX-10" cy="CY" r="4" fill="white" stroke="black" stroke-width="1.5"/>
<!-- Gate lead goes from bubble to the left -->
<line x1="CX-14" y1="CY" x2="CX-40" y2="CY" stroke="black" stroke-width="2"/>
```

**ALTERNATIVE SIMPLER MOSFET STYLE** (preferred for clarity):
Draw the MOSFET as commonly seen in VLSI textbooks:
- A vertical line for the channel
- Three horizontal stubs from the channel: top (drain), middle (body/substrate), bottom (source)
- A vertical gate plate to the left, separated by a thin gap
- Gate lead extending left from the gate plate
- PMOS: small bubble (open circle) on the gate lead
- NMOS: no bubble, arrow on source pointing inward

**VDD Symbol**: A horizontal line with "VDD" or "Vdd" text above it, with a short vertical wire going down to the circuit.
**GND/VSS Symbol**: Standard ground symbol — a horizontal line with 2-3 progressively shorter lines below it, or simply labeled "Vss" with the ground symbol.

**COMPLETE EXAMPLE — CMOS Inverter (vertical layout):**
```svg
<svg xmlns="http://www.w3.org/2000/svg" width="280" height="420" viewBox="0 0 280 420">
  <!-- VDD rail -->
  <line x1="140" y1="30" x2="140" y2="60" stroke="black" stroke-width="2"/>
  <line x1="120" y1="30" x2="160" y2="30" stroke="black" stroke-width="2"/>
  <text x="140" y="22" text-anchor="middle" font-family="Arial" font-size="15" font-weight="bold">Vdd</text>

  <!-- PMOS transistor (source at top connected to VDD) -->
  <!-- Drain/Source vertical wires -->
  <line x1="140" y1="60" x2="140" y2="100" stroke="black" stroke-width="2"/>
  <!-- Channel body -->
  <line x1="125" y1="100" x2="125" y2="170" stroke="black" stroke-width="2"/>
  <!-- Three stubs from channel -->
  <line x1="125" y1="105" x2="140" y2="105" stroke="black" stroke-width="2"/>
  <line x1="125" y1="135" x2="140" y2="135" stroke="black" stroke-width="2"/>
  <line x1="125" y1="165" x2="140" y2="165" stroke="black" stroke-width="2"/>
  <!-- Source wire up to VDD -->
  <line x1="140" y1="105" x2="140" y2="60" stroke="black" stroke-width="2"/>
  <!-- Drain wire down -->
  <line x1="140" y1="165" x2="140" y2="210" stroke="black" stroke-width="2"/>
  <!-- Gate plate -->
  <line x1="115" y1="105" x2="115" y2="165" stroke="black" stroke-width="2"/>
  <!-- Gate bubble (PMOS) -->
  <circle cx="108" cy="135" r="5" fill="white" stroke="black" stroke-width="1.5"/>
  <!-- Gate lead -->
  <line x1="103" y1="135" x2="50" y2="135" stroke="black" stroke-width="2"/>
  <text x="42" y="139" text-anchor="end" font-family="Arial" font-size="15">A</text>

  <!-- Output node (middle) -->
  <circle cx="140" cy="210" r="3" fill="black" stroke="black"/>
  <line x1="140" y1="210" x2="220" y2="210" stroke="black" stroke-width="2"/>
  <circle cx="224" cy="210" r="5" fill="white" stroke="black" stroke-width="1.5"/>
  <text x="240" y="215" font-family="Arial" font-size="15">Out</text>

  <!-- NMOS transistor (drain connected to output, source to GND) -->
  <line x1="140" y1="210" x2="140" y2="250" stroke="black" stroke-width="2"/>
  <!-- Channel body -->
  <line x1="125" y1="250" x2="125" y2="320" stroke="black" stroke-width="2"/>
  <!-- Three stubs -->
  <line x1="125" y1="255" x2="140" y2="255" stroke="black" stroke-width="2"/>
  <line x1="125" y1="285" x2="140" y2="285" stroke="black" stroke-width="2"/>
  <line x1="125" y1="315" x2="140" y2="315" stroke="black" stroke-width="2"/>
  <!-- Drain wire up to output -->
  <line x1="140" y1="255" x2="140" y2="210" stroke="black" stroke-width="2"/>
  <!-- Source wire down to GND -->
  <line x1="140" y1="315" x2="140" y2="370" stroke="black" stroke-width="2"/>
  <!-- Gate plate (no bubble for NMOS) -->
  <line x1="115" y1="255" x2="115" y2="315" stroke="black" stroke-width="2"/>
  <!-- Gate lead -->
  <line x1="115" y1="285" x2="50" y2="285" stroke="black" stroke-width="2"/>
  <text x="42" y="289" text-anchor="end" font-family="Arial" font-size="15">A</text>

  <!-- Connect input A: vertical line between PMOS gate and NMOS gate -->
  <line x1="50" y1="135" x2="50" y2="285" stroke="black" stroke-width="2"/>

  <!-- GND/VSS symbol -->
  <line x1="120" y1="370" x2="160" y2="370" stroke="black" stroke-width="2"/>
  <line x1="126" y1="376" x2="154" y2="376" stroke="black" stroke-width="2"/>
  <line x1="132" y1="382" x2="148" y2="382" stroke="black" stroke-width="2"/>
  <text x="140" y="398" text-anchor="middle" font-family="Arial" font-size="14">Vss</text>
</svg>
```

**CMOS NAND GATE (2-input) — vertical layout:**
- Two PMOS transistors in PARALLEL at top (both sources to VDD, both drains to output)
- Two NMOS transistors in SERIES at bottom (N1 drain to output, N1 source to N2 drain, N2 source to GND)
- Input A connects to gates of P1 and N1
- Input B connects to gates of P2 and N2

**CMOS NOR GATE (2-input) — vertical layout:**
- Two PMOS transistors in SERIES at top (VDD → P1 source, P1 drain → P2 source, P2 drain → output)
- Two NMOS transistors in PARALLEL at bottom (both drains to output, both sources to GND)
- Input A connects to gates of P1 and N1
- Input B connects to gates of P2 and N2

**DIGITAL LOGIC GATE SYMBOLS (block-level, NOT transistor-level):**

When asked about digital logic gates (AND, OR, NOT, NAND, NOR, XOR), draw the standard IEEE/IEC block-level gate symbols — NOT CMOS transistor implementations unless specifically asked for CMOS transistor-level.

Gate symbol conventions:
- **AND gate**: D-shaped body — flat left side, curved right side meeting at a point for the output
- **OR gate**: Curved left side (concave inward), curved right side meeting at a point
- **NOT gate (Inverter)**: Triangle pointing right with a small bubble (circle) at the output
- **NAND gate**: AND gate body + small bubble at output
- **NOR gate**: OR gate body + small bubble at output
- **XOR gate**: OR gate body with an extra curved line on the left input side
- **Buffer**: Triangle pointing right (no bubble)

DRAWING LOGIC GATE SYMBOLS IN SVG:

1. Use `<path>` elements with cubic Bezier curves for smooth gate shapes
2. Gate bodies should be ~60px wide and ~40px tall
3. Input wires extend LEFT from the gate body, output wire extends RIGHT
4. Inputs labeled on the left, output labeled on the right
5. Flow direction: LEFT-TO-RIGHT (inputs on left, output on right)
6. Use horizontal/vertical wires for connections between gates
7. Junction dots where wires branch or connect

GATE SYMBOL TEMPLATES:

```svg
<!-- AND gate at position (x, y) center -->
<g transform="translate(x, y)">
  <path d="M-30,-20 L0,-20 A20,20 0 0,1 0,20 L-30,20 Z" fill="white" stroke="black" stroke-width="2"/>
  <!-- Input wires -->
  <line x1="-60" y1="-10" x2="-30" y2="-10" stroke="black" stroke-width="2"/>
  <line x1="-60" y1="10" x2="-30" y2="10" stroke="black" stroke-width="2"/>
  <!-- Output wire -->
  <line x1="20" y1="0" x2="50" y2="0" stroke="black" stroke-width="2"/>
</g>

<!-- NOT gate (inverter) at position (x, y) -->
<g transform="translate(x, y)">
  <polygon points="-20,-18 20,0 -20,18" fill="white" stroke="black" stroke-width="2"/>
  <circle cx="24" cy="0" r="4" fill="white" stroke="black" stroke-width="2"/>
  <!-- Input wire -->
  <line x1="-50" y1="0" x2="-20" y2="0" stroke="black" stroke-width="2"/>
  <!-- Output wire -->
  <line x1="28" y1="0" x2="58" y2="0" stroke="black" stroke-width="2"/>
</g>

<!-- NAND gate = AND body + bubble -->
<g transform="translate(x, y)">
  <path d="M-30,-20 L0,-20 A20,20 0 0,1 0,20 L-30,20 Z" fill="white" stroke="black" stroke-width="2"/>
  <circle cx="24" cy="0" r="4" fill="white" stroke="black" stroke-width="2"/>
</g>

<!-- OR gate -->
<g transform="translate(x, y)">
  <path d="M-30,-20 Q-10,0 -30,20 L0,20 Q30,20 35,0 Q30,-20 0,-20 L-30,-20 Z" fill="white" stroke="black" stroke-width="2"/>
</g>

<!-- NOR gate = OR body + bubble -->
<g transform="translate(x, y)">
  <path d="M-30,-20 Q-10,0 -30,20 L0,20 Q30,20 35,0 Q30,-20 0,-20 L-30,-20 Z" fill="white" stroke="black" stroke-width="2"/>
  <circle cx="39" cy="0" r="4" fill="white" stroke="black" stroke-width="2"/>
</g>
```

MULTI-GATE CIRCUIT LAYOUT:
- Arrange gates in columns left-to-right for multi-stage circuits
- Space gates ~120px apart horizontally
- Align wires orthogonally (horizontal + vertical only)
- Label all inputs (A, B, C...) on the far left
- Label the final output (Y, F, Out) on the far right
- Add truth table below the circuit if specifically requested
- For NOR-only or NAND-only implementations, show the equivalent circuit using only that gate type

**FOR CIRCUITS WITH COMPONENT VALUES:**
- Add value labels near components: "CL = 2 fF", "I = 10 µA"
- Add calculation annotations if requested: "tpd = CL × VDD / I"
- Use subscript text where appropriate

**CRITICAL — NEVER REVEAL ANSWERS IN THE DIAGRAM:**
These diagrams are for STUDENT ASSIGNMENTS. The student must figure out the answer themselves.
- NEVER label output wires with computed values like "Output = 0", "Y = 1", "F = A'B + AB'"
- NEVER show the final boolean expression of the circuit on the diagram
- NEVER include truth tables in the diagram
- NEVER annotate intermediate or final signal values (0/1) on any wire
- DO label inputs with their VARIABLE NAMES (A, B, C...) but NOT their specific values (A=1, B=0)
- DO label the output node with just a generic name: "Y", "Out", "F", "Output" — but NEVER its value or expression
- The diagram should show the CIRCUIT STRUCTURE only — gates, connections, input/output labels
- If the question says "inputs A=1, B=0", draw the circuit with inputs labeled "A" and "B" only

Return ONLY the SVG markup. No explanation. No markdown fences. Just pure SVG starting with <svg and ending with </svg>."""

    def _build_user_prompt(self, question_text: str, diagram_description: str) -> str:
        return f"""Generate a professional, textbook-quality SVG circuit diagram for this question:

**Question:** {question_text}

**Diagram Description:** {diagram_description}

**Requirements:**
1. If this is a CMOS transistor-level circuit: Use VERTICAL layout — VDD at top, GND/VSS at bottom, proper MOSFET symbols (bubble on PMOS gate, no bubble on NMOS)
2. If this is a digital logic gate circuit (AND, OR, NOT, NAND, NOR, XOR): Use LEFT-TO-RIGHT flow with standard IEEE gate symbols (D-shaped AND, curved OR, triangle NOT with bubble, etc.)
3. Professional textbook style with clean orthogonal wiring
4. All component values and labels from the question
5. Input labels on the LEFT, output labels on the RIGHT
6. Appropriate sizing for the circuit complexity
7. Properly labeled inputs and outputs

IMPORTANT: Use block-level logic gate symbols (AND/OR/NOT shapes) for digital logic circuits. Only use transistor-level MOSFET symbols when explicitly asked about CMOS transistor implementation.

CRITICAL: This is a STUDENT ASSIGNMENT diagram. NEVER reveal the answer in the diagram:
- Label inputs with variable names ONLY (A, B, C) — NOT their values (A=1, B=0)
- Label the output as just "Y", "Out", or "F" — NEVER show its computed value or boolean expression
- Do NOT include truth tables or signal annotations on wires
- Show ONLY the circuit structure, gates, connections, and generic labels

Return ONLY the SVG markup. No explanations."""

    async def generate_circuit_svg(
        self,
        question_text: str,
        diagram_description: str = "",
    ) -> str:
        """
        Generate SVG markup for a circuit diagram using Claude.

        Args:
            question_text: The question describing the circuit
            diagram_description: Additional description of what to draw

        Returns:
            SVG markup string

        Raises:
            RuntimeError: If API key is invalid
        """
        if self._api_key_valid is False:
            raise RuntimeError("Claude API key previously failed — skipping")

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8000,  # SVG can be longer than code
                temperature=0.1,
                system=self._build_system_prompt(),
                messages=[{
                    "role": "user",
                    "content": self._build_user_prompt(question_text, diagram_description)
                }]
            )

            self._api_key_valid = True
            svg_content = response.content[0].text.strip()

            # Extract SVG if wrapped in markdown fences
            svg_content = self._extract_svg(svg_content)

            # Validate it's actually SVG
            if not svg_content.strip().startswith('<svg') and not svg_content.strip().startswith('<?xml'):
                logger.warning("Claude response doesn't look like SVG, attempting extraction")
                # Try to find SVG tags in the response
                import re
                svg_match = re.search(r'(<svg[\s\S]*?</svg>)', svg_content, re.IGNORECASE)
                if svg_match:
                    svg_content = svg_match.group(1)
                else:
                    raise ValueError("Claude did not return valid SVG markup")

            logger.info(f"Claude generated {len(svg_content)} chars of SVG")
            return svg_content

        except Exception as e:
            error_str = str(e)
            if '401' in error_str or 'authentication_error' in error_str:
                self._api_key_valid = False
                logger.error(f"Claude API key is INVALID: {error_str}")
            logger.error(f"SVG circuit generation failed: {error_str}")
            raise

    def _extract_svg(self, response: str) -> str:
        """Extract SVG from response, handling markdown fences."""
        import re

        # Remove markdown code fences
        if '```svg' in response:
            start = response.find('```svg') + len('```svg')
            end = response.find('```', start)
            if end != -1:
                return response[start:end].strip()

        if '```xml' in response:
            start = response.find('```xml') + len('```xml')
            end = response.find('```', start)
            if end != -1:
                return response[start:end].strip()

        if '```' in response:
            start = response.find('```') + 3
            end = response.find('```', start)
            if end != -1:
                candidate = response[start:end].strip()
                if '<svg' in candidate:
                    return candidate

        return response.strip()

    async def generate_circuit_png(
        self,
        question_text: str,
        diagram_description: str = "",
        output_width: int = 400,
        dpi: int = 200,
    ) -> bytes:
        """
        Generate a circuit diagram as PNG bytes.

        Pipeline: Claude → SVG → cairosvg → PNG

        Args:
            question_text: The question describing the circuit
            diagram_description: Additional description
            output_width: Output image width in pixels
            dpi: Output DPI

        Returns:
            PNG image bytes
        """
        if not CAIROSVG_AVAILABLE:
            raise RuntimeError("cairosvg is required for SVG→PNG conversion. Install with: pip install cairosvg")

        # Generate SVG
        svg_content = await self.generate_circuit_svg(question_text, diagram_description)

        # Convert SVG → PNG
        try:
            png_bytes = cairosvg.svg2png(
                bytestring=svg_content.encode('utf-8'),
                output_width=output_width,
                dpi=dpi,
                background_color="white",
            )

            if not png_bytes or len(png_bytes) < 1000:
                raise ValueError(f"SVG→PNG conversion produced empty/tiny output ({len(png_bytes) if png_bytes else 0} bytes)")

            logger.info(f"SVG→PNG conversion successful: {len(png_bytes)} bytes")
            return png_bytes

        except Exception as e:
            logger.error(f"SVG→PNG conversion failed: {e}")
            # Save SVG for debugging
            try:
                debug_path = os.path.join(tempfile.gettempdir(), "debug_circuit.svg")
                with open(debug_path, 'w') as f:
                    f.write(svg_content)
                logger.info(f"Debug SVG saved to {debug_path}")
            except Exception:
                pass
            raise
