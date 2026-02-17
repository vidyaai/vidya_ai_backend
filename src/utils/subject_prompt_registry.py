"""
SubjectPromptRegistry — per-subject prompt content for diagram generation.

Returns subject-specific guidance for three use cases:
  1. Agent system prompt additions (appended to base GPT-4o prompt)
  2. Gemini imagen description style guidance (prepended to image gen description)
  3. Nonai tool-specific code generation guidance (injected into claude_code_tool / svg_circuit_tool)
"""


# ─────────────────────────────────────────────────────────────────────────────
# Agent system prompt additions — one per domain
# ─────────────────────────────────────────────────────────────────────────────

_AGENT_SYSTEM_PROMPTS = {
    "electrical": """
ELECTRICAL ENGINEERING DIAGRAM RULES:
- Circuit schematics: describe component types, topology (series/parallel), standard symbols
- Use svg_circuit_tool for schematics; claude_code_tool with matplotlib for Bode/IV curves
- Do NOT include answer values in diagrams
- Label: component names, values (R1=2kΩ), supply rails (VDD, GND), node names (Vout, Vin)
- For Bode plots: label axes (frequency in Hz/rad/s, magnitude in dB, phase in degrees)
- For I-V curves: label axes (VDS, ID), operating regions (saturation, triode)
- Tool priority: svg_circuit_tool → claude_code_tool(matplotlib)
""",
    "mechanical": """
MECHANICAL ENGINEERING DIAGRAM RULES:
- Free body diagrams: show forces as arrows with labels (direction, magnitude)
- Beam diagrams: mark supports (pin/roller/fixed), distributed/point loads, dimensions
- Use claude_code_tool with matplotlib for ALL mechanical diagrams
- Label: all force magnitudes and directions (F₁, N, W), material properties, dimensions
- For FBDs: show object as simple box/circle, forces radiating outward
- For beams: horizontal beam with vertical arrows for loads, triangles for supports
- For P-V diagrams: label axes, process paths (isothermal, adiabatic, etc.)
- Include dimension annotations (span, load position, cross-section)
""",
    "cs": """
COMPUTER SCIENCE DIAGRAM RULES:
- Data structures: use claude_code_tool with networkx for trees and graphs
- Flowcharts/automata: use claude_code_tool with graphviz (or matplotlib as fallback)
- Label: node values, edge weights, pointers/references, step numbers, state names
- NEVER show the answer (e.g., do NOT show final sorted array if question asks to sort)
- For BSTs/trees: root at top, children below, directed edges from parent to child
- For graphs: circles for nodes, lines/arrows for edges, label weights
- For flowcharts: rectangles for processes, diamonds for decisions, clear direction
- For automata/FSM: circles for states, arrows for transitions, double circle for final state
- Tool: networkx for trees/graphs, matplotlib for sorting visualizations
""",
    "civil": """
CIVIL ENGINEERING DIAGRAM RULES:
- Structural diagrams: trusses, beams, retaining walls with dimensions and loads
- Use claude_code_tool with matplotlib + patches for all civil diagrams
- Label: member forces, support reactions, dimensions, material types, cross-section properties
- For trusses: show all members as lines, joints as circles, applied loads as arrows
- For cross-sections: show geometry with dimensions and material labels
- For retaining walls: show wall geometry, soil pressure distribution, drainage
- Include scale or dimension annotations when given in the question
""",
    "math": """
MATHEMATICS DIAGRAM RULES:
- Function plots: use claude_code_tool with matplotlib; label axes, show key points
- Geometric constructions: labeled shapes with dimensions and angles
- NEVER show the answer on the plot (e.g., don't mark the answer to "find the area")
- Label: axis names and units, function names (f(x), g(x)), key coordinates
- For function plots: include x-intercepts, y-intercepts, maxima/minima if relevant
- For vector fields: show grid of arrows indicating direction and magnitude
- For 3D surfaces: use mpl_toolkits.mplot3d, label axes with proper variable names
- For geometric constructions: show all sides, angles, and relevant measurements
- Grid: use alpha=0.3 for subtle background grid
""",
    "physics": """
PHYSICS DIAGRAM RULES:
- Ray diagrams: show incident/reflected/refracted rays with correct angles
- Spring-mass/pendulum: show dimensions, mass labels, angle labels
- Use claude_code_tool with matplotlib for most; svg/imagen for complex setups
- Label: all physical quantities with units, coordinate system if relevant
- For ray diagrams: show optical axis, lens/mirror symbol, focal points F and F', ray paths
- For field lines: show arrows indicating field direction, stronger near source
- For wave diagrams: label wavelength, amplitude, period
- For spring-mass: label spring constant k, mass m, displacement x
- For energy diagrams: label energy levels, transitions, energy differences
""",
    "chemistry": """
CHEMISTRY DIAGRAM RULES:
- Molecular structures: use SMILES-based description for Gemini; matplotlib for structural
- Lab apparatus: labeled glass components, reagents, connections, measurements
- Use imagen_tool for molecular structures and lab setups; claude_code_tool for plots
- Label: element symbols, bond types (single/double/triple), reagent names, measurement labels
- For structural formulas: show carbon skeleton as zigzag, label heteroatoms (O, N, S)
- For reaction mechanisms: show curved arrows for electron flow, intermediate structures
- For titration curves: label equivalence point, axes (volume of titrant, pH/potential)
- For orbital diagrams: show energy levels, electron spin arrows, orbital labels (1s, 2p, etc.)
""",
    "computer_eng": """
COMPUTER ENGINEERING DIAGRAM RULES:
- Block diagrams: ALU, control unit, registers, buses — each as labeled rectangle
- Pipeline stages: labeled stages with data flow arrows between them
- Use imagen_tool for architectural diagrams; claude_code_tool for timing/logic
- Logic circuits: use svg_circuit_tool or claude_code_tool for gate-level schematics
- Label: ALL block names, bus widths (32-bit, 64-bit), signal names, stage names
- For CPU diagrams: standard layout (fetch → decode → execute → memory → writeback)
- For memory hierarchy: pyramid layout (registers → cache → RAM → disk)
- For pipeline: horizontal stages with arrows, show data flowing left to right
- For logic circuits: use standard IEEE gate symbols (AND, OR, NOT shapes)
- Bus lines: use double arrows or thick lines labeled with bus width
""",
}

# ─────────────────────────────────────────────────────────────────────────────
# Imagen description style guidance — one per (domain, diagram_type)
# ─────────────────────────────────────────────────────────────────────────────

_IMAGEN_DESCRIPTION_PROMPTS = {
    # Electrical
    ("electrical", "circuit_schematic"): (
        "Draw a circuit schematic. Use standard electrical symbols. "
        "Show power supply rails (VDD at top, GND at bottom for CMOS). "
        "Label each component with its designator and value. "
        "Label input and output nodes. Draw wires as horizontal and vertical lines only (orthogonal routing)."
    ),
    ("electrical", "block_diagram"): (
        "Draw an electrical block diagram. Show each functional block as a labeled rectangle. "
        "Connect blocks with directional arrows. Label signal names on connections."
    ),

    # Mechanical
    ("mechanical", "free_body_diagram"): (
        "Draw a free body diagram (FBD). Show the object as a simple shape (box, circle, or dot). "
        "Draw each force as a straight arrow pointing in the direction the force acts. "
        "Label each force arrow with its variable name and/or value. "
        "Include support reactions at constraints. "
        "Use standard FBD conventions: no internal forces shown."
    ),
    ("mechanical", "beam_diagram"): (
        "Draw a beam diagram. Show a horizontal beam with support symbols: "
        "triangle for pin support, triangle on wheels for roller, built-in block for fixed end. "
        "Show loads as arrows: downward arrows for point loads, distributed arrows for UDL. "
        "Label support reactions (RA, RB) and all load values and positions."
    ),
    ("mechanical", "truss_diagram"): (
        "Draw a truss structure diagram. Show each member as a line segment. "
        "Label joints with letters (A, B, C...). Show applied loads as arrows with values. "
        "Show support reactions (pin = triangle, roller = triangle on wheels). "
        "Label member lengths and angles if given."
    ),
    ("mechanical", "pv_diagram"): (
        "Draw a P-V (pressure-volume) thermodynamic diagram. "
        "X-axis: Volume (V), Y-axis: Pressure (P). "
        "Show process curves (isothermal = hyperbola, adiabatic = steeper curve, isobaric = horizontal, isochoric = vertical). "
        "Label all state points, process paths, and key values."
    ),

    # Computer Science
    ("cs", "binary_tree"): (
        "Draw a binary tree diagram. Root node at top. "
        "Child nodes below, connected by directed edges (arrows pointing downward from parent to child). "
        "Label each node with its value. Use circular nodes. "
        "Use hierarchical layout with even horizontal spacing at each level."
    ),
    ("cs", "graph_network"): (
        "Draw a graph diagram. Show nodes as circles with labels. "
        "Show edges as lines (undirected) or arrows (directed) between nodes. "
        "Label edge weights if applicable. Use clear spacing between nodes."
    ),
    ("cs", "flowchart"): (
        "Draw a flowchart. Use rectangles for process steps, diamonds for decisions, "
        "rounded rectangles for start/end. Connect with directed arrows. "
        "Label each shape with its step or condition."
    ),

    # Civil
    ("civil", "truss_frame"): (
        "Draw a truss structure diagram. Show each member as a line segment. "
        "Label joints with letters. Show applied loads as arrows with values. "
        "Show support reactions. Label member lengths and load values."
    ),
    ("civil", "cross_section"): (
        "Draw a structural cross-section diagram. "
        "Show the geometry of the cross-section with dimensions labeled. "
        "Label material types, reinforcement if present, and key measurements."
    ),

    # Math
    ("math", "function_plot"): (
        "Draw a mathematical function plot. Show x-axis and y-axis with labels and tick marks. "
        "Plot the function as a smooth curve. "
        "Label key points (intercepts, maxima, minima, asymptotes) if relevant. "
        "Include a legend if multiple functions are shown. White background, clean grid."
    ),
    ("math", "geometric_construction"): (
        "Draw a geometric construction. Show all shapes clearly with labeled vertices (A, B, C...). "
        "Mark all given dimensions and angles. Show construction lines if relevant. "
        "Label sides and angles with given values."
    ),
    ("math", "vector_field"): (
        "Draw a 2D vector field. Show a grid of arrows where each arrow indicates "
        "the direction and relative magnitude of the vector at that point. "
        "Label the axes and show the coordinate system."
    ),

    # Physics
    ("physics", "ray_diagram"): (
        "Draw a ray diagram for an optical system. "
        "Show the optical axis as a horizontal line. "
        "Draw lens or mirror as vertical line with appropriate symbol (convex/concave). "
        "Show at least two principal rays (parallel ray, chief ray, focal ray). "
        "Label focal points (F, F'), image, and object positions. "
        "Mark image as real (solid) or virtual (dashed)."
    ),
    ("physics", "spring_mass"): (
        "Draw a spring-mass system diagram. "
        "Show the spring attached to a fixed wall, with a mass block attached to the free end. "
        "Label spring constant k, mass m, and displacement x from equilibrium. "
        "Show forces on the mass if relevant."
    ),
    ("physics", "field_lines"): (
        "Draw electric or magnetic field lines. "
        "Show field lines as curves with arrowheads indicating direction. "
        "Lines should be denser where the field is stronger. "
        "Label source charges or poles clearly."
    ),
    ("physics", "wave_diagram"): (
        "Draw a wave diagram. Show a sinusoidal wave on a coordinate system. "
        "Label wavelength (λ), amplitude (A), and period (T). "
        "Show the x-axis (position or time) and y-axis (displacement) with labels."
    ),
    ("physics", "energy_level_diagram"): (
        "Draw an energy level diagram. Show horizontal lines representing energy levels. "
        "Label each level with its quantum number and energy value. "
        "Show transitions as vertical arrows with wavelength or energy labels."
    ),

    # Chemistry
    ("chemistry", "molecular_structure"): (
        "Draw a chemical molecular structure using skeletal/line-angle formula. "
        "Show carbon skeleton as angled lines (zigzag). "
        "Label heteroatoms explicitly (O, N, S, etc.). "
        "Show all charges and formal charges. "
        "Draw aromatic rings as hexagons with alternating double bonds or circle notation. "
        "Label substituents."
    ),
    ("chemistry", "lab_apparatus"): (
        "Draw a chemistry laboratory apparatus setup. "
        "Show all glass components (flask, condenser, burette, etc.) in cross-section style. "
        "Label each component and all reagents. "
        "Show connections between components with proper symbols."
    ),
    ("chemistry", "reaction_mechanism"): (
        "Draw a chemical reaction mechanism. "
        "Show starting materials on the left, products on the right. "
        "Draw curved arrows to show electron flow. "
        "Show all intermediates and transition states. "
        "Label all relevant atoms and charges."
    ),

    # Computer Engineering
    ("computer_eng", "cpu_block_diagram"): (
        "Draw a CPU/computer architecture block diagram. "
        "Show each functional unit as a labeled rectangle. "
        "Connect units with arrows or bus lines labeled with bus width (e.g., '32-bit data bus'). "
        "Standard layout: instruction fetch at top, execution units in middle, memory interfaces on sides/bottom. "
        "All block names must match question text exactly."
    ),
    ("computer_eng", "pipeline_diagram"): (
        "Draw a CPU pipeline diagram. "
        "Show pipeline stages as labeled rectangles in a horizontal row: IF, ID, EX, MEM, WB. "
        "Connect stages with arrows showing data flow. "
        "Label each stage with its full name. Show pipeline registers between stages."
    ),
    ("computer_eng", "memory_hierarchy"): (
        "Draw a memory hierarchy diagram. "
        "Show memory levels as a pyramid from top (fastest/smallest) to bottom (slowest/largest): "
        "Registers → L1 Cache → L2 Cache → RAM → Disk. "
        "Label each level with its name, typical size, and access time if given."
    ),
    ("computer_eng", "logic_circuit"): (
        "Draw a digital logic circuit using standard IEEE gate symbols. "
        "Show gates as: AND (D-shape), OR (curved), NOT (triangle with bubble), "
        "NAND (D-shape with bubble), NOR (curved with bubble). "
        "Label all inputs and outputs. Inputs on left, outputs on right."
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# Nonai tool-specific code generation guidance
# ─────────────────────────────────────────────────────────────────────────────

_NONAI_TOOL_PROMPTS = {
    # Electrical
    ("electrical", "circuit_schematic", "svg"): (
        "Draw an electrical circuit schematic. Use standard IEEE component symbols. "
        "For CMOS circuits: vertical layout VDD→PMOS→output→NMOS→GND. "
        "Orthogonal wiring only (horizontal + vertical lines). "
        "Label all components (R1, R2, C1, etc.) and nodes (Vin, Vout, VDD, GND)."
    ),
    ("electrical", "bode_plot", "matplotlib"): (
        "Generate a Bode plot using matplotlib with two subplots: "
        "top = magnitude (dB) vs frequency, bottom = phase (degrees) vs frequency. "
        "Use semilogx for frequency axis. Label axes with units. "
        "figsize=(6, 5). Include grid on both subplots."
    ),
    ("electrical", "iv_curve", "matplotlib"): (
        "Generate an I-V characteristic curve using matplotlib. "
        "Label x-axis as voltage (V), y-axis as current (mA or A). "
        "Show operating regions if MOSFET/diode (saturation, triode, cutoff). "
        "figsize=(6, 4). Include grid."
    ),
    ("electrical", "block_diagram", "matplotlib"): (
        "Draw an electrical block diagram using matplotlib.patches.FancyBboxPatch. "
        "Each block as a rounded rectangle with centered label. "
        "Use ax.annotate() with arrowprops for signal flow arrows. "
        "figsize=(7, 4)."
    ),

    # Mechanical
    ("mechanical", "free_body_diagram", "matplotlib"): (
        "Draw a free body diagram using matplotlib. figsize=(8, 6), dpi=150. "
        "Use ax.annotate() with arrowprops=dict(arrowstyle='->', lw=2, color='black') for all force arrows. "
        "Draw the body as a Rectangle (light gray fill, black edge). "
        "Place ALL forces from the question as arrows with magnitude labels. "
        "Apply textbook style: plt.rcParams({'font.size':11,'font.family':'serif'}), "
        "ax.axis('off'), plt.savefig('output.png', dpi=150, bbox_inches='tight', facecolor='white')."
    ),
    ("mechanical", "beam_diagram", "matplotlib"): (
        "Draw a beam diagram using matplotlib. figsize=(10, 5), dpi=150. "
        "Draw horizontal beam as a thick filled rectangle (height=0.1 relative to span). "
        "Use filled triangles (patches.Polygon) for pin supports, filled circles+line for roller. "
        "Use ax.annotate() with arrowstyle='-|>' for all point loads and distributed loads. "
        "Label supports (A, B), load magnitudes, and span dimensions with dimension lines. "
        "plt.rcParams({'font.size':11,'font.family':'serif'}), ax.axis('off'), dpi=150."
    ),
    ("mechanical", "truss_diagram", "matplotlib"): (
        "Draw a truss diagram using matplotlib. figsize=(10, 6), dpi=150. "
        "Draw members as line segments (ax.plot, linewidth=2, black). "
        "Mark joints with filled circles (scatter, size=80, black). "
        "Label joints alphabetically (A, B, C...) offset from the joint. "
        "Annotate loads with ax.annotate arrows. Show support symbols at base nodes. "
        "plt.rcParams({'font.size':11,'font.family':'serif'}), ax.axis('off'), dpi=150."
    ),
    ("mechanical", "pv_diagram", "matplotlib"): (
        "Draw a P-V thermodynamic diagram using matplotlib. "
        "X-axis: Volume (m³ or L), Y-axis: Pressure (Pa, kPa, or atm). "
        "Plot process curves using numpy (isothermal: P=nRT/V, adiabatic: PV^gamma=const). "
        "Mark state points with scatter + annotate. figsize=(8, 5), dpi=150."
    ),
    ("mechanical", "fluid_flow", "matplotlib"): (
        "Draw a textbook-quality fluid flow diagram using matplotlib. figsize=(12, 6) with two side-by-side panels (subplots(1,2)): "
        "LEFT panel = Laminar flow, RIGHT panel = Turbulent flow. "
        "In EACH panel: "
        "(1) Draw a filled circle (patches.Circle) centered at (0,0) with the given diameter D, black edge, white/light-gray fill. "
        "(2) Draw horizontal streamlines above and below the cylinder: "
        "  - Far-field: use ax.plot() with slight sinusoidal curves deviating around the cylinder "
        "  - Near-field: use numpy to compute potential-flow streamlines: y = y0 + (a²/2)*sin(2θ) approximation "
        "  - 5-7 streamlines on each side, evenly spaced "
        "(3) Mark boundary layer with a dashed gray arc around the cylinder surface. "
        "(4) Mark separation point with a filled circle and annotate φ_lam (≈82°) for laminar, φ_turb (≈120°) for turbulent. "
        "(5) Indicate wake region with curved recirculation arrows (ax.annotate with connectionstyle='arc3,rad=0.4'). "
        "(6) Draw dashed rectangle for control volume boundary. "
        "(7) Add free-stream velocity arrow U∞ on the left side. "
        "(8) Label: cylinder diameter D, boundary layer, separation point, wake. "
        "STYLE: black/white only (no colored lines except light gray for boundary layer), "
        "serif font, plt.rcParams({'font.size':10,'font.family':'serif','lines.linewidth':1.2}), "
        "ax.set_aspect('equal'), ax.axis('off'), "
        "plt.savefig('output.png', dpi=150, bbox_inches='tight', facecolor='white')."
    ),
    ("mechanical", "pressure_distribution", "matplotlib"): (
        "Draw a pressure coefficient (Cp) distribution plot around a cylinder using matplotlib. "
        "figsize=(8, 5). X-axis: angle θ from 0° to 360°. Y-axis: Cp (inverted — negative up is conventional). "
        "Plot two curves: (1) Ideal potential flow: Cp = 1 - 4sin²(θ), solid black line. "
        "(2) Experimental/actual: show separation and wake region with dashed line. "
        "Mark stagnation points (θ=0°, θ=180°) and separation angles. "
        "Label axes with units. Add legend. Include horizontal reference line at Cp=1. "
        "plt.rcParams({'font.size':11, 'font.family':'serif'}). dpi=150."
    ),
    ("mechanical", "stress_strain", "matplotlib"): (
        "Draw a stress-strain curve using matplotlib. "
        "figsize=(8, 5). X-axis: strain (ε), Y-axis: stress (σ, MPa or Pa). "
        "Mark key regions: elastic region (linear slope = E), yield point, "
        "plastic region, ultimate strength, fracture point. "
        "Use np.piecewise or manual segments to draw the curve shape. "
        "Annotate all key points with ax.annotate(). "
        "plt.rcParams({'font.size':11, 'font.family':'serif'}). dpi=150."
    ),

    # CS
    ("cs", "binary_tree", "networkx"): (
        "Use networkx to draw a binary tree. Create nx.DiGraph(). "
        "Add nodes with integer/string values. Add directed edges parent→child. "
        "Use nx.drawing.nx_pydot.graphviz_layout with prog='dot' for top-down tree layout, "
        "or compute positions manually if graphviz unavailable. "
        "Draw with nx.draw_networkx: circular nodes, black edges, labels centered. "
        "figsize=(6, 5)."
    ),
    ("cs", "graph_network", "networkx"): (
        "Use networkx to draw a graph. Create nx.Graph() or nx.DiGraph(). "
        "Add nodes and edges. Use nx.spring_layout or nx.circular_layout for positioning. "
        "Draw with nx.draw_networkx: show labels, edge weights if present. "
        "figsize=(6, 5)."
    ),
    ("cs", "flowchart", "matplotlib"): (
        "Draw a flowchart using matplotlib. "
        "Use FancyBboxPatch (boxstyle='round') for process boxes, "
        "Polygon (diamond shape) for decision nodes, "
        "FancyBboxPatch (boxstyle='round,pad=0.2') for start/end (oval shape). "
        "Use ax.annotate with arrowprops for flow arrows. "
        "Label all nodes and decision branches (Yes/No). figsize=(6, 8)."
    ),
    ("cs", "sorting_visualization", "matplotlib"): (
        "Draw a sorting algorithm visualization using matplotlib bar chart. "
        "Show array elements as vertical bars with values. "
        "Use different colors to highlight: elements being compared, sorted region, pivot. "
        "Label each bar with its value. figsize=(7, 4)."
    ),
    ("cs", "automata_fsm", "networkx"): (
        "Draw a finite state machine using networkx. Create nx.DiGraph(). "
        "Add state nodes (regular circles for normal states, double circle for accepting states). "
        "Add labeled transition edges. Mark the start state with an arrow from left. "
        "Use nx.circular_layout or spring_layout. figsize=(7, 5)."
    ),
    ("cs", "stack_queue", "matplotlib"): (
        "Draw a stack or queue data structure using matplotlib. "
        "For stack: vertical column of rectangles, label each element, mark top. "
        "For queue: horizontal row of rectangles, label front and rear. "
        "Use FancyBboxPatch for each element cell. figsize=(5, 6) for stack, (8, 3) for queue."
    ),
    ("cs", "hash_table", "matplotlib"): (
        "Draw a hash table using matplotlib. "
        "Show index column on left, key-value cells as rectangles. "
        "For chaining: show linked list chains extending to the right from each bucket. "
        "Label buckets with index numbers and cells with key-value pairs. figsize=(7, 6)."
    ),

    # Civil
    ("civil", "truss_frame", "matplotlib"): (
        "Draw a truss frame diagram using matplotlib. "
        "Use ax.plot for members (line segments). Mark joints with scatter. "
        "Label joints alphabetically. Annotate loads with arrows. "
        "Show support symbols: triangle for pin, circle+triangle for roller. figsize=(9, 5)."
    ),
    ("civil", "cross_section", "matplotlib"): (
        "Draw a structural cross-section using matplotlib.patches. "
        "Use Rectangle/Polygon patches for the cross-section geometry. "
        "Add dimension lines with double-headed arrows. "
        "Label dimensions and material types. figsize=(5, 6)."
    ),

    # Math
    ("math", "function_plot", "matplotlib"): (
        "Use numpy linspace for x values. Use ax.plot() for the curve. "
        "Label axes with ax.set_xlabel/ylabel. "
        "Mark key points (roots, maxima, intersections) with ax.scatter() and ax.annotate(). "
        "Add grid with ax.grid(alpha=0.3). ax.axhline(0) and ax.axvline(0) for axes. "
        "figsize=(6, 4)."
    ),
    ("math", "geometric_construction", "matplotlib"): (
        "Draw the geometric construction using matplotlib.patches. "
        "Use Polygon for triangles/polygons, Circle for circles. "
        "Label vertices with ax.text(), sides with midpoint annotations. "
        "Mark angles with Arc patches. ax.set_aspect('equal'). figsize=(6, 5)."
    ),
    ("math", "3d_surface", "matplotlib"): (
        "Generate a 3D surface plot using mpl_toolkits.mplot3d. "
        "from mpl_toolkits.mplot3d import Axes3D. "
        "Use np.meshgrid and ax.plot_surface with colormap. "
        "Label all three axes (x, y, z). figsize=(7, 5)."
    ),
    ("math", "vector_field", "matplotlib"): (
        "Draw a 2D vector field using ax.quiver(). "
        "Create meshgrid of x,y points. Compute U,V components at each point. "
        "Use ax.quiver(X, Y, U, V) with scale parameter. "
        "Label axes and add title. figsize=(6, 5)."
    ),
    ("math", "number_line", "matplotlib"): (
        "Draw a number line using matplotlib. "
        "Draw horizontal line with ax.plot. Mark points with ax.scatter. "
        "Label points and intervals. Use ax.annotate for labels above/below line. "
        "Hide y-axis. figsize=(8, 2)."
    ),

    # Physics
    ("physics", "ray_diagram", "matplotlib"): (
        "Draw a ray diagram using matplotlib. "
        "Draw optical axis as horizontal line. Draw lens as vertical line with arrows at ends. "
        "Mark focal points F and F' on the axis. "
        "Draw at least 2 principal rays from object tip: parallel→refract through F', "
        "chief ray through center (undeviated), ray through F→parallel after. "
        "Draw image as arrow at intersection point. "
        "Label object, image, F, F', and optical axis. figsize=(8, 5)."
    ),
    ("physics", "spring_mass", "matplotlib"): (
        "Draw a spring-mass system using matplotlib. "
        "Draw spring as zigzag line (plt.plot with sin pattern). "
        "Draw mass as rectangle at end of spring. "
        "Label spring constant k, mass m, displacement x. "
        "Show equilibrium position with dashed line if relevant. figsize=(5, 5)."
    ),
    ("physics", "field_lines", "matplotlib"): (
        "Draw field lines using matplotlib. "
        "Use ax.streamplot() for continuous field lines, or manually draw curved arrows. "
        "Show source charges/poles as colored circles (+red, -blue). "
        "Lines should be denser near charges. figsize=(6, 6)."
    ),
    ("physics", "wave_diagram", "matplotlib"): (
        "Draw a wave diagram using matplotlib. "
        "Plot y = A*sin(2*pi*x/lambda) using numpy. "
        "Label wavelength λ with double-headed arrow, amplitude A with vertical arrow. "
        "Label axes: x for position or time, y for displacement. figsize=(7, 4)."
    ),
    ("physics", "energy_level_diagram", "matplotlib"): (
        "Draw an energy level diagram using matplotlib. "
        "Draw horizontal lines for energy levels using ax.plot. "
        "Label each level on the left with quantum number (n=1, n=2, etc.) and energy. "
        "Draw vertical arrows for transitions. Label arrow with photon energy or wavelength. "
        "figsize=(5, 7)."
    ),

    # Chemistry
    ("chemistry", "molecular_structure", "matplotlib"): (
        "Draw a molecular structural formula using matplotlib. "
        "Draw bonds as line segments (ax.plot). "
        "Place atoms at calculated positions: use standard bond angles (120° sp2, 109.5° sp3). "
        "Use ax.text() for atom labels (C, O, N, H explicit if needed). "
        "For aromatic rings: draw hexagon then inner circle. "
        "figsize=(5, 5). ax.set_aspect('equal'). Hide axes."
    ),
    ("chemistry", "lab_apparatus", "matplotlib"): (
        "Draw lab apparatus using matplotlib.patches. "
        "Use Ellipse for flask openings, Rectangle for tubes/cylinders, Arc for curved glassware. "
        "Draw liquid levels with filled rectangles/polygons of blue color. "
        "Label each component with ax.text. Include measurement scales where relevant. "
        "figsize=(5, 7)."
    ),
    ("chemistry", "titration_curve", "matplotlib"): (
        "Draw a titration curve using matplotlib. "
        "X-axis: Volume of titrant (mL), Y-axis: pH or potential (mV). "
        "Plot sigmoidal curve using numpy (logistic-like function). "
        "Mark equivalence point with vertical dashed line and annotation. "
        "figsize=(6, 4). Include grid."
    ),

    # Computer Engineering
    ("computer_eng", "cpu_block_diagram", "matplotlib"): (
        "Draw a CPU architecture block diagram using matplotlib.patches.FancyBboxPatch. "
        "Show functional units as colored rounded rectangles: "
        "control=light blue, execution=light green, memory=light orange. "
        "Use ax.annotate() with arrowprops for bus connections. "
        "Label each block in its center. Label bus widths on connections. "
        "figsize=(8, 6)."
    ),
    ("computer_eng", "pipeline_diagram", "matplotlib"): (
        "Draw a pipeline diagram using matplotlib.patches. "
        "Show pipeline stages as rectangles in a horizontal row. "
        "Use FancyBboxPatch for each stage. Add arrows between stages. "
        "Label each stage: IF (Instruction Fetch), ID (Decode), EX (Execute), MEM, WB. "
        "Optional: show pipeline registers as vertical lines between stages. "
        "figsize=(9, 3)."
    ),
    ("computer_eng", "memory_hierarchy", "matplotlib"): (
        "Draw a memory hierarchy pyramid using matplotlib. "
        "Use Polygon patches for pyramid levels, widening from top to bottom. "
        "Label each level (Registers, L1 Cache, L2 Cache, RAM, Disk) in the center. "
        "Add size and access time annotations on the right side. "
        "figsize=(6, 7)."
    ),
    ("computer_eng", "logic_circuit", "svg"): (
        "Draw a digital logic circuit at gate-level. "
        "Use standard IEEE gate symbols: D-shape for AND, curved for OR, triangle with bubble for NOT, "
        "D-shape with bubble for NAND, curved with bubble for NOR. "
        "Inputs on left, outputs on right. "
        "Label all inputs and outputs. Orthogonal wiring only."
    ),
    ("computer_eng", "alu_circuit", "svg"): (
        "Draw an ALU (Arithmetic Logic Unit) circuit at gate/block level. "
        "Show ALU as central block with labeled inputs (A, B, operation select) and output. "
        "Internal logic gates if detailed, or block-level if architectural. "
        "Label all signals and bus widths. Standard IEEE gate symbols."
    ),
}

# Default fallback prompts for unrecognized (domain, diagram_type, tool) combinations
_DEFAULT_IMAGEN_GUIDANCE = (
    "Draw a clear, labeled technical diagram. Show all components mentioned in the question. "
    "Use standard conventions for the diagram type. White background, black lines, clear labels."
)

_DEFAULT_NONAI_GUIDANCE = (
    "Generate a clean, labeled technical diagram using matplotlib. "
    "Scale figsize to complexity: (6,4) simple, (8,5) standard, (10,7) complex. "
    "Apply textbook style: plt.rcParams({'font.size':11,'font.family':'serif'}), "
    "use ax.annotate() for labeled arrows, ax.axis('off') for technical diagrams. "
    "plt.savefig('output.png', dpi=150, bbox_inches='tight', facecolor='white')."
)

_DEFAULT_AGENT_PROMPT = (
    "For this domain, generate clear diagrams with labeled components. "
    "Use claude_code_tool with matplotlib for most diagram types. "
    "Use svg_circuit_tool for any circuit schematics."
)

# ─────────────────────────────────────────────────────────────────────────────
# Reviewer style hints — for GeminiDiagramReviewer
# ─────────────────────────────────────────────────────────────────────────────

_REVIEWER_STYLE_HINTS = {
    ("electrical", "circuit_schematic"): "Expect a circuit schematic with component symbols and wires.",
    ("electrical", "bode_plot"): "Expect two subplots: magnitude (dB) and phase (degrees) vs frequency.",
    ("electrical", "iv_curve"): "Expect an I-V characteristic curve with labeled axes.",
    ("mechanical", "free_body_diagram"): "Expect a free body diagram with labeled force arrows on an object.",
    ("mechanical", "beam_diagram"): "Expect a beam with support symbols and load arrows.",
    ("mechanical", "truss_diagram"): "Expect a truss structure with members, joints, and load arrows.",
    ("mechanical", "fluid_flow"): "Expect a fluid flow diagram around a cylinder with streamlines, boundary layer, separation point, wake region, and U∞ velocity arrow. Two-panel layout (Laminar/Turbulent) is correct.",
    ("mechanical", "pressure_distribution"): "Expect a Cp vs angle curve showing pressure coefficient distribution around a cylinder.",
    ("mechanical", "stress_strain"): "Expect a stress-strain curve with labeled yield point, ultimate strength, and fracture.",
    ("cs", "binary_tree"): "Expect a tree diagram with circular nodes and directed edges.",
    ("cs", "graph_network"): "Expect a graph with labeled nodes and edges.",
    ("cs", "flowchart"): "Expect a flowchart with process boxes, decision diamonds, and flow arrows.",
    ("civil", "truss_frame"): "Expect a truss structure with labeled members and support reactions.",
    ("math", "function_plot"): "Expect a coordinate plot with labeled axes and a smooth curve.",
    ("math", "geometric_construction"): "Expect a geometric figure with labeled vertices and dimensions.",
    ("physics", "ray_diagram"): "Expect a ray diagram with optical axis, lens/mirror, and ray paths.",
    ("physics", "spring_mass"): "Expect a spring-mass diagram with labeled spring and mass.",
    ("chemistry", "molecular_structure"): "Expect a molecular structure diagram with atomic symbols and bonds.",
    ("chemistry", "lab_apparatus"): "Expect labeled laboratory glassware and equipment.",
    ("computer_eng", "cpu_block_diagram"): "Expect a block diagram with labeled functional units and data buses.",
    ("computer_eng", "pipeline_diagram"): "Expect pipeline stages shown as labeled boxes in sequence.",
    ("computer_eng", "logic_circuit"): "Expect a logic circuit with standard IEEE gate symbols.",
}


class SubjectPromptRegistry:
    """
    Registry that returns subject-specific prompt text for diagram generation.

    Three use cases:
      1. get_agent_system_prompt — appended to base GPT-4o system prompt
      2. get_imagen_description_prompt — prepended to Gemini image gen description
      3. get_nonai_tool_prompt — injected into claude_code_tool or svg_circuit_tool
    """

    def get_agent_system_prompt(self, domain: str, diagram_type: str) -> str:
        """
        Returns subject-specific system prompt addition for the GPT-4o routing agent.
        """
        return _AGENT_SYSTEM_PROMPTS.get(domain, _DEFAULT_AGENT_PROMPT)

    def get_imagen_description_prompt(self, domain: str, diagram_type: str) -> str:
        """
        Returns subject-specific style guidance for Gemini image generation.
        Prepend this to the agent-generated description.
        """
        # Try specific (domain, diagram_type) first
        key = (domain, diagram_type)
        if key in _IMAGEN_DESCRIPTION_PROMPTS:
            return _IMAGEN_DESCRIPTION_PROMPTS[key]
        # Fall back to domain-level default from agent prompt (first sentence)
        domain_prompt = _AGENT_SYSTEM_PROMPTS.get(domain, "")
        if domain_prompt:
            # Extract first meaningful line as a brief style hint
            first_line = domain_prompt.strip().split("\n")[1].strip()
            if first_line and len(first_line) > 10:
                return first_line
        return _DEFAULT_IMAGEN_GUIDANCE

    def get_nonai_tool_prompt(self, domain: str, diagram_type: str, tool: str) -> str:
        """
        Returns subject-specific code generation guidance for a given tool.
        Injected into claude_code_tool's or svg_circuit_tool's system prompt.
        """
        # Normalize tool name
        tool_key = tool.lower()
        if "svg" in tool_key or "circuit" in tool_key:
            tool_key = "svg"
        elif "networkx" in tool_key or "network" in tool_key:
            tool_key = "networkx"
        elif "graphviz" in tool_key:
            tool_key = "graphviz"
        else:
            tool_key = "matplotlib"

        key = (domain, diagram_type, tool_key)
        if key in _NONAI_TOOL_PROMPTS:
            return _NONAI_TOOL_PROMPTS[key]

        # Try with just matplotlib as fallback for any domain
        fallback_key = (domain, diagram_type, "matplotlib")
        if fallback_key in _NONAI_TOOL_PROMPTS:
            return _NONAI_TOOL_PROMPTS[fallback_key]

        return _DEFAULT_NONAI_GUIDANCE

    def get_reviewer_style_hint(self, domain: str, diagram_type: str) -> str:
        """
        Returns a style hint for the diagram reviewer.
        Not a pass/fail rule — just guidance for what to expect visually.
        """
        return _REVIEWER_STYLE_HINTS.get((domain, diagram_type), "")
