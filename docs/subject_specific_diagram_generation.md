# Subject-Specific Diagram Generation — Architecture Plan

## Goal

Replace the current monolithic `DiagramAnalysisAgent` with a **routing-first architecture** that:

1. **Classifies** the question domain using a lightweight routing agent
2. **Routes** to a subject-specific AI prompt (for `engine=ai`) or a subject-specific fallback tool (for `engine=nonai`)
3. **Reviews** the output using a subject-aware reviewer (either shared generic reviewer or subject-specific variants)

The system must work across 8 STEM subjects with zero electrical/CMOS-specific assumptions baked into shared infrastructure.

---

## Supported Subjects

| ID | Subject | Key diagram types |
|----|---------|------------------|
| `electrical` | Electrical Engineering | Circuit schematics, Bode plots, I-V curves, waveforms, block diagrams |
| `mechanical` | Mechanical Engineering | Free body diagrams, beam diagrams, truss structures, stress-strain, P-V, flow systems |
| `cs` | Computer Science | Data structures (trees, graphs, lists), algorithm visualizations, flowcharts, automata |
| `civil` | Civil & Environmental Engineering | Cross-sections, truss/frame structures, flow networks, site plans, soil profiles |
| `math` | Mathematics | Function plots, geometric constructions, vector fields, 3D surfaces, coordinate geometry |
| `physics` | Physics | Ray diagrams, field lines, wave diagrams, optics setups, energy diagrams, phase diagrams |
| `chemistry` | Chemistry | Molecular structures, reaction mechanisms, apparatus setups, titration curves, orbital diagrams |
| `computer_eng` | Computer Engineering | CPU/ALU block diagrams, memory hierarchy, pipeline stages, ISA timing diagrams, logic circuits |

---

## Current Architecture (Baseline)

```
Assignment JSON (questions with hasDiagram=True)
    ↓
DiagramAnalysisAgent._analyze_single_question()
    ├── GPT-4o: "should this question have a diagram + which tool?"
    │       Tools available: svg_circuit_tool, claude_code_tool, matplotlib_tool,
    │                        schemdraw_tool, networkx_tool, dalle_tool, imagen_tool
    ├── engine=ai path:
    │       ↓ GPT-4o picks imagen_tool (description extracted)
    │       → Gemini image gen (3 attempts)
    │       → GeminiDiagramReviewer (vision review)
    │       → SVG fallback if all 3 attempts fail
    └── engine=nonai path:
            ↓ GPT-4o picks svg_circuit_tool / claude_code_tool / matplotlib_tool
            → Tool executes, produces PNG
            → GPT-4o vision reviewer
```

**Problems with current design:**
- GPT-4o system prompt is hardcoded with CMOS/electrical examples
- `svg_circuit_tool` description says "BEST FOR ALL CIRCUITS" → only fits electrical
- `lib_guidance` in `claude_code_tool` contains only `schemdraw` CMOS inverter example
- No subject-specific knowledge passed to Gemini image gen
- No subject-specific knowledge passed to the SVG fallback
- Reviewer prompt examples mention "logic gates", "transistor-level" — electrical only

---

## Proposed Architecture

```
Assignment JSON
    ↓
[NEW] DomainRouter  (fast, cheap: gpt-4o-mini)
    → outputs: { domain: "mechanical", diagram_type: "free_body_diagram",
                 complexity: "simple" | "moderate" | "complex" }
    ↓
DiagramAnalysisAgent (refactored)
    ├── Loads subject-specific system prompt  (from SubjectPromptRegistry)
    ├── engine=ai path:
    │       → SubjectSpecificImagenPromptBuilder
    │           → Subject-aware description fed to Gemini image gen
    │           → GeminiDiagramReviewer (unchanged — already generic)
    │           → [FALLBACK] SubjectSpecificFallbackRouter
    │               → picks correct nonai tool for the classified domain
    │               → passes subject-specific generation prompt to that tool
    └── engine=nonai path:
            → SubjectSpecificFallbackRouter
                → routes to correct tool + passes subject-specific prompt
                → GPT-4o reviewer (unchanged)
```

---

## New Components

### 1. `DomainRouter` — `src/utils/domain_router.py`

A lightweight classifier agent that runs **before** diagram generation. Uses `gpt-4o-mini` for speed and cost.

**Inputs:** question text, subject (from assignment metadata)

**Outputs:**
```python
{
  "domain": "mechanical",          # one of the 8 subject IDs above
  "diagram_type": "free_body_diagram",  # specific type within domain
  "complexity": "simple",          # simple | moderate | complex
  "ai_suitable": True,             # True: Gemini can draw this; False: prefer code tool
  "preferred_tool": "matplotlib",  # for nonai path: matplotlib | schemdraw | networkx | graphviz | svg
}
```

**Classification prompt design:**
- Lists all 8 subjects with concrete diagram_type examples per subject
- Asks the model to also judge `ai_suitable`: AI image gen works well for structural/spatial diagrams but poorly for precise mathematical plots and data structure graphs (code tools are better)
- Very short response (JSON only, ~100 tokens)
- Fast: `gpt-4o-mini` at temperature=0.0

**Diagram type taxonomy per subject:**

| Subject | Diagram types |
|---------|--------------|
| `electrical` | `circuit_schematic`, `bode_plot`, `iv_curve`, `waveform`, `block_diagram`, `timing_diagram` |
| `mechanical` | `free_body_diagram`, `beam_diagram`, `truss_diagram`, `stress_strain_curve`, `pv_diagram`, `fluid_flow`, `mechanism_linkage` |
| `cs` | `binary_tree`, `linked_list`, `graph_network`, `sorting_visualization`, `flowchart`, `automata_fsm`, `stack_queue`, `hash_table` |
| `civil` | `truss_frame`, `cross_section`, `retaining_wall`, `flow_network`, `contour_map`, `soil_profile` |
| `math` | `function_plot`, `geometric_construction`, `vector_field`, `3d_surface`, `number_line`, `coordinate_geometry`, `matrix_visualization` |
| `physics` | `ray_diagram`, `field_lines`, `wave_diagram`, `optics_setup`, `energy_level_diagram`, `phase_diagram`, `spring_mass`, `pendulum` |
| `chemistry` | `molecular_structure`, `reaction_mechanism`, `lab_apparatus`, `titration_curve`, `orbital_diagram`, `phase_diagram`, `chromatography` |
| `computer_eng` | `cpu_block_diagram`, `memory_hierarchy`, `pipeline_diagram`, `alu_circuit`, `logic_circuit`, `isa_timing`, `cache_organization` |

**`ai_suitable` routing heuristic:**
- `True` (prefer Gemini): circuit_schematic, free_body_diagram, truss_diagram, ray_diagram, molecular_structure, cpu_block_diagram, lab_apparatus, mechanism_linkage, optics_setup, field_lines
- `False` (prefer code tools): all plots (bode_plot, iv_curve, function_plot, stress_strain_curve, titration_curve, pv_diagram), data structures (binary_tree, linked_list, graph_network, sorting_visualization, stack_queue, hash_table), timing_diagram, automata_fsm, flowchart, 3d_surface, number_line

---

### 2. `SubjectPromptRegistry` — `src/utils/subject_prompt_registry.py`

A registry that returns subject-specific prompt text for three use cases:

```python
class SubjectPromptRegistry:
    def get_agent_system_prompt(self, domain: str, diagram_type: str) -> str:
        """Returns subject-specific system prompt for the GPT-4o routing agent."""

    def get_imagen_description_prompt(self, domain: str, diagram_type: str) -> str:
        """Returns subject-specific guidance for building Gemini image gen descriptions."""

    def get_nonai_tool_prompt(self, domain: str, diagram_type: str, tool: str) -> str:
        """Returns subject-specific code generation guidance for a given tool."""
```

Each method dispatches to a subject-specific section. No CMOS defaults anywhere in shared code.

**Content per subject:**

#### `electrical` — Agent system prompt additions:
- Circuit schematics: describe component types, topology (series/parallel), standard symbols
- Use `imagen_tool` for schematics, `claude_code_tool` with matplotlib for Bode/IV curves
- No answer values in diagrams
- Label: component names, values (R1=2kΩ), supply rails (VDD, GND), node names (Vout, Vin)

#### `mechanical` — Agent system prompt additions:
- Free body diagrams: show forces as arrows with labels (direction, magnitude)
- Beam diagrams: supports (pin/roller/fixed), distributed/point loads, dimensions
- Use `claude_code_tool` with matplotlib for all mechanical diagrams
- Label: all force magnitudes and directions, material properties, dimensions

#### `cs` — Agent system prompt additions:
- Data structures: use `claude_code_tool` with networkx for trees/graphs
- Flowcharts: use `claude_code_tool` with graphviz for process flows
- Label: node values, edge weights, pointers/references, step numbers
- Never show answer (e.g., don't show the final sorted array if the question asks to sort)

#### `civil` — Agent system prompt additions:
- Structural diagrams: trusses, beams, retaining walls with dimensions and loads
- Use `claude_code_tool` with matplotlib + patches
- Label: member forces, support reactions, dimensions, material types

#### `math` — Agent system prompt additions:
- Function plots: use `claude_code_tool` with matplotlib, label axes, show key points
- Geometric constructions: labeled shapes with dimensions and angles
- Never show the answer on the plot (e.g., don't mark the answer to "find the area")
- Label: axis names and units, function names, key coordinates

#### `physics` — Agent system prompt additions:
- Ray diagrams: show incident/reflected/refracted rays with correct angles
- Spring-mass / pendulum: dimensions, mass labels, angle labels
- Use `claude_code_tool` with matplotlib for most; `imagen_tool` for complex setups
- Label: all physical quantities with units, coordinate system if relevant

#### `chemistry` — Agent system prompt additions:
- Molecular structures: use SMILES-based description for Gemini; `claude_code_tool` for structural diagrams
- Lab apparatus: labeled glass components, reagents, connections
- Use `imagen_tool` for molecular structures and lab setups
- Label: element symbols, bond types, reagent names, measurement labels

#### `computer_eng` — Agent system prompt additions:
- Block diagrams: ALU, control unit, registers, buses
- Pipeline stages: labeled stages with data flow arrows
- Use `imagen_tool` for architectural diagrams; `claude_code_tool` for timing/logic
- Logic circuits: use `svg_circuit_tool` or `claude_code_tool` for gate-level schematics
- Label: all block names, bus widths, signal names, stage names

---

### 3. Refactored `DiagramAnalysisAgent` — `src/utils/diagram_agent.py`

**Changes to `_get_agent_prompt()`:**
- Remove ALL hardcoded CMOS/electrical examples from the base system prompt
- The base prompt only contains: general rules (when to add diagrams), tool descriptions, description quality rules, code best practices
- Append subject-specific section from `SubjectPromptRegistry.get_agent_system_prompt(domain, diagram_type)` before passing to GPT-4o

**Changes to `_analyze_single_question()`:**
1. Call `DomainRouter.classify()` first → get `{ domain, diagram_type, complexity, ai_suitable, preferred_tool }`
2. If `engine=ai` AND `ai_suitable=False` → override to `engine=nonai` for this question (code tool is better)
3. Pass domain + diagram_type to `SubjectPromptRegistry` to get the appended system prompt
4. Pass domain context to the Gemini image description builder
5. Pass `preferred_tool` + domain-specific guidance to the nonai fallback path

**Changes to `imagen_description` building:**
- Before sending description to Gemini, prepend subject-specific style guidance from registry
- Example for `mechanical/free_body_diagram`: "This is a mechanical free body diagram. Draw labeled force arrows on the object. Use standard FBD conventions: object as a box or dot, forces as straight arrows pointing away, label with variable name (F₁, N, W) and direction."
- Example for `chemistry/molecular_structure`: "This is a chemistry molecular structure diagram. Use skeletal/line-angle formula. Label heteroatoms. Show all charges if present."

---

### 4. `SubjectSpecificFallbackRouter` — `src/utils/fallback_router.py`

Replaces the current "always use svg_circuit_tool or claude_code_tool" fallback with subject-aware routing.

```python
FALLBACK_TOOL_MAP = {
    # (domain, diagram_type) → tool + subject-specific generation system prompt
    ("electrical", "circuit_schematic"):    ("svg_circuit_tool", electrical_svg_prompt),
    ("electrical", "bode_plot"):            ("claude_code_tool", electrical_matplotlib_prompt),
    ("electrical", "iv_curve"):             ("claude_code_tool", electrical_matplotlib_prompt),
    ("electrical", "block_diagram"):        ("claude_code_tool", electrical_blockdiag_prompt),
    ("mechanical", "free_body_diagram"):    ("claude_code_tool", mechanical_fbd_prompt),
    ("mechanical", "beam_diagram"):         ("claude_code_tool", mechanical_beam_prompt),
    ("mechanical", "truss_diagram"):        ("claude_code_tool", mechanical_truss_prompt),
    ("cs", "binary_tree"):                  ("claude_code_tool", cs_networkx_prompt),
    ("cs", "graph_network"):               ("claude_code_tool", cs_networkx_prompt),
    ("cs", "flowchart"):                    ("claude_code_tool", cs_graphviz_prompt),
    ("cs", "automata_fsm"):                 ("claude_code_tool", cs_graphviz_prompt),
    ("civil", "truss_frame"):               ("claude_code_tool", civil_truss_prompt),
    ("civil", "cross_section"):             ("claude_code_tool", civil_matplotlib_prompt),
    ("math", "function_plot"):              ("claude_code_tool", math_matplotlib_prompt),
    ("math", "geometric_construction"):     ("claude_code_tool", math_matplotlib_prompt),
    ("math", "3d_surface"):                 ("claude_code_tool", math_matplotlib3d_prompt),
    ("physics", "ray_diagram"):             ("claude_code_tool", physics_optics_prompt),
    ("physics", "spring_mass"):             ("claude_code_tool", physics_matplotlib_prompt),
    ("physics", "field_lines"):             ("claude_code_tool", physics_matplotlib_prompt),
    ("chemistry", "molecular_structure"):   ("claude_code_tool", chemistry_rdkit_prompt),
    ("chemistry", "lab_apparatus"):         ("claude_code_tool", chemistry_matplotlib_prompt),
    ("computer_eng", "cpu_block_diagram"):  ("claude_code_tool", compeng_blockdiag_prompt),
    ("computer_eng", "pipeline_diagram"):   ("claude_code_tool", compeng_matplotlib_prompt),
    ("computer_eng", "alu_circuit"):        ("svg_circuit_tool", compeng_svg_prompt),
    ("computer_eng", "logic_circuit"):      ("svg_circuit_tool", compeng_svg_prompt),
    # Default fallback for any unrecognized combination:
    ("*", "*"):                             ("claude_code_tool", generic_matplotlib_prompt),
}
```

Each `*_prompt` above is a short (5–15 line) tool-specific generation guidance string stored in `SubjectPromptRegistry`, injected into `claude_code_tool`'s or `svg_circuit_tool`'s system prompt.

**`svg_circuit_generator.py` changes:**
- Keep all current CMOS/logic gate content — it IS the right tool for electrical and computer_eng circuits
- Add a preamble section: "The following subject context applies to this diagram:" which is filled by the fallback router
- For `computer_eng/alu_circuit`: inject "Draw a digital logic circuit at gate-level. Use standard IEEE gate symbols. Inputs on left, outputs on right."
- For `electrical/circuit_schematic`: inject current CMOS layout rules (unchanged)
- No domain is forced by default — only injected when the router specifically sends a circuit question here

---

### 5. Reviewer Changes — `src/utils/gemini_diagram_reviewer.py`

**Current state:** Already generic (answer leaks + label presence + readability). No electrical-specific checks remain after earlier fixes.

**Proposed change:** Keep a single shared reviewer. Add **optional subject-aware tips** in the context section (alongside existing `user_prompt_context`):

```python
def _build_review_prompt(
    self,
    question_text: str,
    diagram_description: str,
    user_prompt_context: str = "",
    domain: str = "",          # NEW
    diagram_type: str = "",    # NEW
) -> str:
```

The new `domain` + `diagram_type` parameters generate a small "style hint" appended to the review prompt — NOT new pass/fail rules, just guidance for what to expect visually:

| Domain/Type | Style hint added to reviewer |
|-------------|------------------------------|
| `electrical/circuit_schematic` | "Expect a circuit schematic with component symbols and wires." |
| `mechanical/free_body_diagram` | "Expect a free body diagram with labeled force arrows on an object." |
| `cs/binary_tree` | "Expect a tree diagram with nodes and directed edges." |
| `math/function_plot` | "Expect a coordinate plot with labeled axes and a curve." |
| `chemistry/molecular_structure` | "Expect a molecular structure diagram with atomic symbols and bonds." |
| `computer_eng/cpu_block_diagram` | "Expect a block diagram with labeled blocks and connecting arrows/buses." |

These hints help Gemini 2.5 Pro correctly assess whether what it sees is the right *type* of diagram, without adding domain-specific pass/fail criteria. The three core checks (answer leak, label presence, readability) remain unchanged and fully generic.

**Alternative considered:** Subject-specific reviewer subclasses. Decision: **Reject** — the current generic reviewer already works well. Subject-specific style hints as optional parameters are sufficient and far simpler to maintain.

---

## File Structure Changes

### New files:
```
src/utils/domain_router.py              # DomainRouter class
src/utils/subject_prompt_registry.py    # SubjectPromptRegistry class
src/utils/fallback_router.py            # SubjectSpecificFallbackRouter class
```

### Modified files:
```
src/utils/diagram_agent.py
  - _get_agent_prompt(): remove hardcoded electrical examples; load from registry
  - _analyze_single_question(): call DomainRouter first; pass domain context throughout
  - imagen path: prepend subject style guidance to description
  - nonai path: use SubjectSpecificFallbackRouter instead of fixed tool choice

src/utils/svg_circuit_generator.py
  - _build_system_prompt(): accept optional subject_context parameter
  - _build_user_prompt(): accept optional subject_context parameter
  - No removal of existing CMOS content — it stays for electrical/computer_eng

src/utils/gemini_diagram_reviewer.py
  - _build_review_prompt(): add optional domain + diagram_type params
  - Append style hint (not new rules) based on domain/type

src/utils/diagram_tools.py
  - Update tool descriptions to be domain-agnostic (remove "BEST FOR ALL CIRCUITS")
  - Add subject_context parameter to svg_circuit_tool and claude_code_tool tool specs
```

### Unchanged:
```
src/utils/diagram_reviewer.py           # GPT-4o reviewer — already generic enough
src/utils/gemini_imagen_generator.py    # Gemini API calls — no domain logic here
```

---

## Data Flow (Detailed)

### engine=ai path (with new routing):

```
Question: "A simply supported beam of length 4m carries a point load of 500N at midpoint.
           Draw the free body diagram and find the reactions."
Subject from assignment: "mechanical"

Step 1 — DomainRouter (gpt-4o-mini):
  → domain="mechanical", diagram_type="free_body_diagram",
    complexity="simple", ai_suitable=True, preferred_tool="matplotlib"

Step 2 — SubjectPromptRegistry.get_agent_system_prompt("mechanical", "free_body_diagram"):
  → returns mechanical FBD-specific rules appended to base system prompt

Step 3 — GPT-4o agent (with mechanical FBD system prompt):
  → picks imagen_tool (since ai_suitable=True)
  → generates description: "Free body diagram of a horizontal beam, length 4m.
     Pin support at left end (vertical + horizontal reaction). Roller support at right end
     (vertical reaction only). Downward point load 500N at midpoint (x=2m).
     Label all forces with arrows: RA at left, RB at right, 500N downward at center."

Step 4 — description enriched with style guidance from registry:
  → prepend: "Draw a mechanical free body diagram. Show forces as labeled arrows.
     Standard FBD: object in center, reaction forces at supports pointing upward,
     applied loads pointing in direction of application."

Step 5 — Gemini image gen (3 attempts):
  → generates FBD image

Step 6 — GeminiDiagramReviewer with domain hint:
  → style hint: "Expect a free body diagram with labeled force arrows."
  → checks: label presence (RA, RB, 500N), answer leak, readability

Step 7 — if all 3 attempts fail → SubjectSpecificFallbackRouter:
  → ("mechanical", "free_body_diagram") → claude_code_tool + mechanical_fbd_prompt
  → passes mechanical FBD code generation guidance to claude_code_tool
```

### engine=nonai path:

```
Same question, same DomainRouter output.

Step 3 — SubjectSpecificFallbackRouter:
  → ("mechanical", "free_body_diagram") → ("claude_code_tool", mechanical_fbd_prompt)

Step 4 — claude_code_tool called with:
  - description: (from GPT-4o agent)
  - system_prompt: base code gen prompt + mechanical_fbd_prompt
  → Claude generates matplotlib code:
      - Horizontal beam with labels
      - Arrow patches for RA, RB, 500N
      - Dimension annotation for 4m span

Step 5 — GPT-4o reviewer reviews the generated image
```

---

## Subject-Specific Prompt Content (Detail)

### `electrical/circuit_schematic` — imagen description style:
> "Draw a circuit schematic. Use standard electrical symbols. Show power supply rails (VDD at top, GND at bottom for CMOS). Label each component with its designator and value. Label input and output nodes. Draw wires as horizontal and vertical lines only (orthogonal routing)."

### `electrical/circuit_schematic` — nonai (svg_circuit_tool) guidance:
> Current `svg_circuit_generator.py` content unchanged — it already handles this correctly.

### `mechanical/free_body_diagram` — imagen description style:
> "Draw a free body diagram (FBD). Show the object as a simple shape (box, circle, or dot). Draw each force as a straight arrow pointing in the direction the force acts. Label each force arrow with its variable name and/or value. Include support reactions at constraints. Use standard FBD conventions: no internal forces shown."

### `mechanical/free_body_diagram` — nonai (matplotlib) guidance:
> "Use matplotlib.patches.FancyArrowPatch for force arrows. Draw the object as a Rectangle. Place reaction arrows at support points. Use ax.annotate() for force labels. Standard FBD layout: object centered, forces radiating outward. figsize=(6, 5)."

### `cs/binary_tree` — imagen description style:
> "Draw a binary tree diagram. Root node at top. Child nodes below, connected by directed edges (arrows pointing downward from parent to child). Label each node with its value. Use circular nodes. Use hierarchical layout with even horizontal spacing at each level."

### `cs/binary_tree` — nonai (networkx) guidance:
> "Use networkx with a hierarchical layout. Create nx.DiGraph(). Add nodes with labels equal to their values. Add edges from parent to child. Use nx.drawing.nx_pydot.graphviz_layout with prog='dot' for top-down tree layout. Draw with circular node markers, black edges, value labels centered in nodes."

### `math/function_plot` — imagen description style:
> "Draw a mathematical function plot. Show x-axis and y-axis with labels and tick marks. Plot the function as a smooth curve. Label key points (intercepts, maxima, minima, asymptotes) if relevant to the question. Include a legend if multiple functions are shown. White background, clean grid."

### `math/function_plot` — nonai (matplotlib) guidance:
> "Use numpy linspace for x values. Use matplotlib plot() for the curve. Label axes with ax.set_xlabel/ylabel. Mark key points with ax.scatter() and ax.annotate(). Add grid with ax.grid(alpha=0.3). figsize=(6, 4)."

### `chemistry/molecular_structure` — imagen description style:
> "Draw a chemical molecular structure using skeletal/line-angle formula. Show carbon skeleton as angled lines (zigzag). Label heteroatoms explicitly (O, N, S, etc.). Show all charges and formal charges. Draw aromatic rings as hexagons with alternating double bonds or circle notation. Label substituents."

### `chemistry/molecular_structure` — nonai (matplotlib) guidance:
> "Use matplotlib to draw structural formula. Draw bonds as line segments. Use ax.text() for atom labels. Place atoms at calculated positions using standard bond angles (120° for sp2, 109.5° for sp3). Use RDKit if available for SMILES-based rendering (from rdkit import Chem; from rdkit.Chem import Draw)."

### `computer_eng/cpu_block_diagram` — imagen description style:
> "Draw a CPU/computer architecture block diagram. Show each functional unit as a labeled rectangle. Connect units with arrows or bus lines labeled with bus width (e.g., '32-bit data bus'). Standard layout: instruction fetch at top, execution units in middle, memory interfaces on sides/bottom. All block names must match question text exactly."

### `computer_eng/cpu_block_diagram` — nonai (matplotlib) guidance:
> "Use matplotlib.patches.FancyBboxPatch for blocks. Use ax.annotate() with arrowprops for connections. Label each block in its center. Use different colors for different functional unit types (e.g., control=blue, execution=green, memory=orange). figsize=(8, 6)."

### `civil/truss_frame` — imagen description style:
> "Draw a truss structure diagram. Show each member as a line segment. Label joints with letters (A, B, C...). Show applied loads as arrows with values. Show support reactions (pin = triangle, roller = triangle on wheels). Label member lengths and angles if given in the question."

### `physics/ray_diagram` — imagen description style:
> "Draw a ray diagram for an optical system. Show the optical axis as a horizontal line. Draw lens or mirror as vertical line with appropriate symbol (convex/concave). Show at least two principal rays (parallel ray, chief ray, focal ray). Label focal points (F, F'), image, and object positions. Mark image as real (solid) or virtual (dashed)."

---

## Implementation Phases

### Phase 1 — Domain Router + Registry skeleton
1. Create `DomainRouter` with full taxonomy and `gpt-4o-mini` classifier
2. Create `SubjectPromptRegistry` skeleton with all 8 subjects, initially returning placeholder prompts
3. Wire `DomainRouter` into `DiagramAnalysisAgent._analyze_single_question()` — just log the classification, no behavior change yet
4. **Test:** Classify 20 questions across 8 subjects, check accuracy

### Phase 2 — Subject-Specific Agent System Prompt
1. Fill in `SubjectPromptRegistry.get_agent_system_prompt()` for all 8 subjects
2. Replace `_get_agent_prompt()` in `DiagramAnalysisAgent` with base prompt + registry append
3. Remove CMOS/electrical hardcoding from base prompt
4. **Test:** Run existing run8 (electrical) — should still work. Run new test with mechanical/math question.

### Phase 3 — Subject-Specific imagen Descriptions (engine=ai)
1. Fill in `SubjectPromptRegistry.get_imagen_description_prompt()` for all 8 subjects
2. Prepend subject style guidance to Gemini descriptions in `_analyze_single_question()`
3. Pass `domain` + `diagram_type` to `GeminiDiagramReviewer._build_review_prompt()`
4. **Test:** Generate diagrams for each subject, verify Gemini gets correct style guidance

### Phase 4 — Subject-Specific Fallback Router (engine=nonai)
1. Create `SubjectSpecificFallbackRouter` with `FALLBACK_TOOL_MAP`
2. Fill in all `*_prompt` strings in `SubjectPromptRegistry.get_nonai_tool_prompt()`
3. Update `svg_circuit_generator.py` to accept `subject_context` parameter
4. Replace fixed `svg_circuit_tool/claude_code_tool` selection with `FallbackRouter.route()`
5. **Test:** Test nonai path for electrical, mechanical, CS, math

### Phase 5 — ai_suitable Routing Override
1. Use `ai_suitable` from `DomainRouter` to override `engine=ai` → `engine=nonai` for code-better types
2. This means function plots, data structures, timing diagrams always go to code tools even when `engine=ai`
3. **Test:** Ask for a binary tree question with `engine=ai` — should route to networkx code, not Gemini

### Phase 6 — Integration Test Across All Subjects
1. Create `question_generation_test/run_multisubject.py` test script
2. Test 3 questions × 8 subjects = 24 questions, verify:
   - Correct domain classification
   - Correct tool selected
   - Diagram visually correct
   - Reviewer passes/fails correctly
   - PDF generated with all diagrams

---

## Tool Description Updates (`diagram_tools.py`)

Current `imagen_tool` description is already generic. Current `svg_circuit_tool` description says:
> "USE THIS FOR ALL electrical circuit diagrams (CMOS inverters, NAND/NOR gates...)"

**Replace with:**
> "Generates professional circuit/schematic diagrams via Claude SVG. Best for: electrical circuits, digital logic, ALU schematics, gate-level computer engineering diagrams. Produces clean orthogonal wiring with standard component symbols."

Current `claude_code_tool` description is reasonably generic but the `lib_guidance` injected in the tool call contains a CMOS inverter example.

**Replace `lib_guidance` with:** Subject-appropriate code example from `SubjectPromptRegistry.get_nonai_tool_prompt()` based on the classified domain/diagram_type — no default CMOS example.

---

## Testing Plan

### Unit tests (per subject, 2 questions each):

| Subject | Test question | Expected diagram_type | Expected tool |
|---------|--------------|----------------------|---------------|
| Electrical | "MOSFET amplifier with RD=2kΩ" | circuit_schematic | svg_circuit_tool |
| Electrical | "Plot Bode magnitude for RC low-pass filter" | bode_plot | claude_code_tool/matplotlib |
| Mechanical | "Simply supported beam 4m, 500N load" | free_body_diagram | claude_code_tool/matplotlib |
| Mechanical | "P-V diagram for Otto cycle" | pv_diagram | claude_code_tool/matplotlib |
| CS | "Insert 5,3,7,1 into a BST" | binary_tree | claude_code_tool/networkx |
| CS | "Merge sort: show divide step on [5,2,4,6,1]" | sorting_visualization | claude_code_tool/matplotlib |
| Civil | "Warren truss with 3 panels, 10kN load" | truss_frame | claude_code_tool/matplotlib |
| Math | "Plot f(x)=x²−4x+3, find roots" | function_plot | claude_code_tool/matplotlib |
| Physics | "Convex lens, object at 2F, show image" | ray_diagram | claude_code_tool/matplotlib |
| Chemistry | "Draw structural formula of ethanol" | molecular_structure | claude_code_tool/matplotlib |
| Computer Eng | "5-stage RISC pipeline: IF, ID, EX, MEM, WB" | pipeline_diagram | claude_code_tool/matplotlib |
| Computer Eng | "1-bit ALU with AND, OR, ADD operations" | alu_circuit | svg_circuit_tool |

---

## Key Design Decisions & Rationale

| Decision | Rationale |
|----------|-----------|
| Single `GeminiDiagramReviewer` (not 8 subject variants) | Current generic reviewer already works well after recent fixes. Style hints (not new rules) are sufficient. Adding 8 reviewer variants would be over-engineering. |
| `DomainRouter` uses `gpt-4o-mini`, not `gpt-4o` | Classification is a short, structured task. `gpt-4o-mini` is 10× cheaper and almost as accurate for taxonomy classification. |
| `ai_suitable` flag overrides `engine` per question | Some diagram types (function plots, data structures) are always better rendered by code tools regardless of the user's engine preference. This prevents wasted Gemini calls. |
| Subject prompts stored in a registry class, not inline | Keeps `diagram_agent.py` clean and makes prompts independently editable/testable without touching agent logic. |
| `svg_circuit_generator.py` CMOS content is NOT removed | It is the right content for electrical and computer_eng circuits. The fix is routing — only send circuit questions here, not all questions. |
| `fallback_router.py` as separate file | The routing table is complex (24+ entries). Keeping it separate from agent logic makes it independently maintainable. |
