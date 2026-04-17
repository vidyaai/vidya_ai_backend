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

═══ ANALOG CIRCUITS ═══
- Circuit schematics: describe component types, topology (series/parallel), standard symbols
- Use circuitikz_tool for professional circuit schematics (preferred)
- Use svg_circuit_tool as fallback for schematics
- Use claude_code_tool with matplotlib for Bode/IV curves and plots
- Do NOT include answer values in diagrams
- Label: component names, values (R1=2kΩ), supply rails (VDD, GND), node names (Vout, Vin)
- For Bode plots: label axes (frequency in Hz/rad/s, magnitude in dB, phase in degrees)
- For I-V curves: label axes (VDS, ID), operating regions (saturation, triode)

═══ DIGITAL CIRCUITS ═══
- Logic gates: Use IEEE/ANSI symbols (D-shaped AND, curved OR, triangle NOT with bubble)
- Flip-flops: Show as rectangles with clock (>), D/J/K/T inputs, Q/Q̄ outputs
- MUX/DEMUX: Trapezoid shape, data inputs, select lines, outputs labeled
- Encoders/Decoders: Rectangular blocks with input/output labels (I0-In, Y0-Yn)
- FSM diagrams: States as circles, transitions as labeled arrows, start/accepting states marked
- Timing diagrams: Horizontal time axis, signal waveforms as square waves, clock at top
- Setup/Hold timing: Show clock edge, data transitions, tsetup and thold regions
- Verilog modules: Rectangular block with module name, input/output ports on sides
- Bus notation: Thick line with slash and width label (e.g., /8 for 8-bit bus)
- Clock domain crossing: Show CDC boundary, synchronizer flip-flops, metastability region

⚠️ ANSWER HIDING FOR DIGITAL CIRCUITS (CRITICAL):
- Timing/waveform diagrams: Draw ONLY INPUT waveforms (CLK, D, A, B, EN, RESET).
  OUTPUT signals (Q, Q1, Q2, Q̄, Y) must be BLANK rows with "?" — students draw them.
  NEVER draw actual output waveforms — that reveals the answer.
- Counter diagrams (ring, Johnson, BCD, binary): Show ONLY the circuit topology
  (flip-flops, feedback connections, gates). Show initial state if given.
  Do NOT show state transition tables, state sequences, or output values.
- Rising-edge triggered D-FF: Q changes ONLY on rising CLK edges (low→high).
  D is sampled at the moment of the rising edge.

═══ TOOL PRIORITY ═══
- Circuit schematics: circuitikz_tool → svg_circuit_tool
- Timing diagrams: claude_code_tool (matplotlib with step plots)
- FSM diagrams: claude_code_tool (networkx or matplotlib)
- Block diagrams: imagen_tool or claude_code_tool
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

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT show computed reaction forces, support moments, or resultant forces
  (those are what students must calculate)
- Do NOT show shear force / bending moment diagrams if the question asks students to draw them
- Do NOT label work done, net heat, or efficiency on P-V diagrams if those are asked
- Show ONLY the problem setup: given loads, geometry, supports, dimensions, material properties
- If the question asks "find the reactions at A and B", do NOT show RA and RB values on the diagram
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

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT show the result of an algorithm if the question asks students to trace/compute it
  (e.g., do NOT show the final sorted array, traversal order, shortest path result)
- For BST operations: show the tree BEFORE the operation, NOT after
  (e.g., if question says "insert 5, 3, 7 into empty BST", show the empty tree or just the first node)
- For graph algorithms (Dijkstra, BFS, DFS): show the graph with weights, NOT the solution path
- For sorting: show the initial array, NOT intermediate or final sorted states
- For FSM/automata: show the state machine diagram, but do NOT mark the answer
  to "what string does this accept?" or "what is the final state?"
- For BB84 Bloch sphere diagrams showing the encoding alphabet (question is
  about Alice's transmitted states or the four encoding bases): show all
  four states |0⟩, |1⟩, |+⟩, |−⟩ with clear labels. For BB84 questions
  about a single-state preparation, angle illustration, or a specific
  measurement, show only the components the question requires — do NOT
  add the full four-state alphabet when it would crowd out the required
  geometry (polar/azimuthal angles, axis labels). In either case, do NOT
  include eavesdropping detection labels or note boxes stating conclusions
  about cloning/entanglement.
- For quantum error correction: do NOT label "Threshold" lines, "Logical Operator"
  annotations, or "Syndrome Table" entries if students must identify them.
- Diagrams show the PROBLEM SETUP — students must work out the SOLUTION
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

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT show computed member forces, support reactions, or deflections
  if the question asks students to calculate them
- Do NOT show shear / bending moment diagrams if students are asked to draw them
- For trusses: show applied loads and geometry, NOT internal member forces
- For retaining walls: show geometry and soil properties, NOT computed pressures
  if the question asks to "determine" or "calculate" them
- Show ONLY the problem setup: given loads, geometry, supports, material properties
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

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT mark/shade/label the answer if the question asks students to compute it
  (e.g., don't shade the area if the question is "find the area under the curve")
- Do NOT label the intersection point if the question asks "find where f(x) and g(x) intersect"
- Do NOT plot the derivative/integral if the question asks students to compute it
- For optimization: show the function but do NOT mark the max/min point if that's the question
- For geometric proofs: show the given construction, NOT the proven result
- Diagrams show the PROBLEM SETUP — students must derive the ANSWER
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

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT show computed quantities if the question asks students to calculate them
  (e.g., don't label the image distance if the question asks "find the image position")
- For ray diagrams: show the setup (lens, object) but do NOT draw the image
  if the question asks to "locate the image" or "draw the ray diagram"
- For circuit diagrams in physics: show the circuit, NOT the computed current/voltage
- For energy level diagrams: show levels, but do NOT label transition energies
  if the question asks students to calculate them
- For projectile motion: show the setup, NOT the trajectory if asked to "determine the path"
- For free body diagrams: show the setup, NOT the net force or acceleration result
- For Kepler's second law (equal areas): draw the elliptical orbit with TWO sectors
  clearly marked but shade only ONE sector. Label the other sector with "?" or "Area = ?".
  Do NOT draw both sectors with visually identical size/shading — the student must prove
  they are equal.
- For stellar nucleosynthesis (identify products/stages/shells): draw the structural layout
  (layers, arrows, reaction paths) but replace the KEY product/element labels with "?"
  placeholders. The student must identify what is produced at each stage.
- For plasma confinement: do NOT label drift directions, stability boundaries, or threshold
  values if the student must determine them.
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

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT show the product(s) of a reaction if the question asks to "predict the product"
- Do NOT show the complete mechanism if the question asks students to "draw the mechanism"
  (show only the starting materials and reagents)
- For titration curves: do NOT label the pH at the equivalence point if asked to "determine" it
- For molecular orbital diagrams: do NOT fill in electron configurations if students must do it
- For lab setups: show the apparatus, NOT the expected measurement readings
- For crystallography / X-ray diffraction (systematic absences): render ALL candidate
  reflection positions as same-size, same-style dots with (hkl) coordinate labels only.
  Do NOT use dot size, colour, or presence/absence to distinguish allowed from forbidden
  reflections — the student must determine which are systematically absent.
- Diagrams show the PROBLEM SETUP — students must determine the OUTCOME
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

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Timing/waveform diagrams: Draw ONLY INPUT waveforms. OUTPUT signals must be BLANK
  rows with "?" labels — students determine the output themselves.
- For pipeline hazard questions: show the pipeline stages and instruction sequence,
  NOT the resolved hazard (forwarding paths, stalls) if students must determine those
- For cache questions: show the cache structure and memory access sequence,
  NOT the hit/miss results if the question asks to "determine" them
- For logic circuit output: show the circuit and inputs, NOT the output truth table
  if students are asked to derive it
- Show ONLY the problem setup — students must work out the SOLUTION
""",
    # ─── Medical subjects ───────────────────────────────────────────────────
    "anatomy": """
ANATOMY DIAGRAM RULES:
- Anatomical diagrams: show regional or systemic anatomy with standard directional labels
- Use imagen_tool for anatomical illustrations; claude_code_tool with matplotlib for schematic cross-sections
- Label: structures using correct anatomical terminology (Latin/English as appropriate)
- For cross-sections (e.g., spinal cord, limb): show all relevant layers/compartments with labels
- For nerve/vessel courses: show trajectory with key branching points and relationships labeled
- For osteology: show bone landmarks (processes, foramina, facets) with labels
- For histology slides: label cell types, layers, and distinct structural features
- Include orientation indicators (superior/inferior, medial/lateral, anterior/posterior)

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT label the structure being asked about ("identify this structure")
- For nerve/vessel identification questions: show the diagram and leave target structures with "?" labels
- For surface anatomy: show landmarks, NOT the answer to "mark the position of X"
- Show ONLY the problem setup; students must identify or annotate the answers
""",
    "physiology": """
PHYSIOLOGY DIAGRAM RULES:
- Functional diagrams: organ system flow diagrams, feedback loops, signal transduction pathways

═══ TOOL SELECTION ═══
- neurokit2_tool  → action_potential (neuronal AP waveform), cardiac_loop (P-V loop)
- scipy_curve_tool → pressure_volume_loop (cardiac P-V loop), growth-related curves
- networkx_pathway_tool → feedback_loop (homeostatic feedback circuit)
- claude_code_tool (matplotlib) → lung compliance curves, organ system flow diagrams,
    and any physiology diagram NOT covered by the specialist tools above

- For action potential: use neurokit2_tool — scipy CubicSpline waveform with threshold/resting lines
- For cardiac P-V loop: use neurokit2_tool or scipy_curve_tool — 4-phase closed loop with valve annotations
- For feedback loops: use networkx_pathway_tool — FancyBboxPatch nodes with circular directed edges
- Label axes with CORRECT units: time in ms, membrane potential in mV, volume in mL, pressure in mmHg

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT label numerical values if the question asks students to calculate or identify them
- For action potential: show the waveform setup, NOT the ionic basis if students must explain it
- For cardiac loops: show the graph, NOT the calculated stroke volume or ejection fraction
- Show ONLY the problem setup — students must derive the physiological explanation
""",
    "biochemistry": """
BIOCHEMISTRY DIAGRAM RULES:
- Metabolic pathway diagrams: show substrates, products, enzymes, and cofactors as labeled nodes/arrows

═══ TOOL SELECTION ═══
- scipy_curve_tool    → enzyme_kinetics (Michaelis-Menten curve with Vmax/Km markers)
- networkx_pathway_tool → metabolic_pathway (DiGraph with oval metabolite nodes, enzyme edge labels)
- claude_code_tool (matplotlib) → Lineweaver-Burk plots, molecular structure schematics,
    ETC/glycolysis diagrams where custom layout is needed

- For enzyme kinetics: use scipy_curve_tool — exact v=Vmax*S/(Km+S) with numpy; Km and Vmax annotations
- For metabolic pathways: use networkx_pathway_tool — DiGraph with oval nodes, enzyme labels on edges,
    cofactor side-nodes in lighter colour
- For Lineweaver-Burk: use claude_code_tool with 1/[S] vs 1/V axes, x-intercept = −1/Km, y-intercept = 1/Vmax

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT label the enzyme name if the question asks students to identify the enzyme at a step
- For pathway diagrams: show the pathway with key intermediates, NOT the answer to "what is the product of this step?"
- For kinetics plots: show the graph, NOT the calculated Km or Vmax if students must determine them
- For CRISPR-Cas9 structural questions (identifying domains, features): generate a DETAILED
  schematic showing at minimum the Cas9 protein outline, guide RNA, target DNA strand, and
  PAM site. Use "?" placeholders for domains the student must identify (e.g., do NOT label
  "RuvC", "HNH", or "Bridge Helix" if those are the answer). Do NOT generate a simple
  arrow-and-box diagram — the question requires molecular-level detail.
- Show ONLY the problem setup — students must complete or interpret the pathway
""",
    "pharmacology": """
PHARMACOLOGY DIAGRAM RULES:

═══ TOOL SELECTION ═══
- scipy_curve_tool    → dose_response (sigmoid via scipy.special.expit), pharmacokinetics (PK model)
- imagen_tool          → receptor mechanism illustrations, drug-receptor structural diagrams
- claude_code_tool (matplotlib) → Lineweaver-Burk-style plots, any other pharmacology diagram

- For dose-response curves: use scipy_curve_tool — y=100*expit(x) sigmoid; EC50 and Emax marked;
    for agonist/antagonist comparison overlay two curves with correct relative EC50/Emax shifts
- For pharmacokinetics: use scipy_curve_tool — one-compartment oral absorption model;
    Cmax/tmax/AUC/t½ all annotated; IV vs oral overlay where relevant
- For drug mechanism (receptor level): use imagen_tool
- For drug receptor interaction overview: claude_code_tool with labeled arrow diagram

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT label EC50 / ED50 values if the question asks students to determine them from the graph
- For shifted curves (antagonists): show both curves, NOT the numerical shift value if students must calculate it
- For pharmacokinetics: show the graph, NOT the half-life calculation if that is the question
- Show ONLY the problem setup — students must read values or interpret the pharmacodynamics
""",
    "pathology": """
PATHOLOGY DIAGRAM RULES:
- Histopathology diagrams: describe tissue section with key pathological features labeled
- Use imagen_tool for histopathology illustrations; claude_code_tool for disease progression charts
- For histology: label cell type, tissue layer, key abnormal features (e.g., necrosis type, inflammatory infiltrate)
- For disease progression charts: show stages/grades as labeled boxes connected by arrows with progression criteria
- For gross pathology: describe macroscopic features (colour, texture, size, borders) in labels
- For oncology staging: show TNM or grade progression as a labeled flow diagram
- For immunofluorescence patterns: describe pattern (linear, granular, mesangial) with structure labels

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT label the diagnosis if the question asks students to "identify the pathological finding"
- For histology images: show the tissue features with neutral labels, NOT the full diagnosis
- For disease progression: show the stages, NOT the answer to "what is the next stage?"
- Show ONLY the problem setup — students must interpret the histopathological findings
""",
    "microbiology": """
MICROBIOLOGY DIAGRAM RULES:

═══ TOOL SELECTION ═══
- scipy_curve_tool       → growth_curve (4-phase piecewise: lag/exponential/stationary/death)
- networkx_pathway_tool  → infection_cycle (circular 5-node directed cycle)
- imagen_tool             → bacterial_structure (morphology and ultrastructure illustrations)
- claude_code_tool (matplotlib) → antibiotic mechanism diagrams, Gram stain workflows,
    serology/ELISA steps, and any other microbiology diagram not listed above

- For bacterial growth curves: use scipy_curve_tool — piecewise log(CFU/mL) vs time with
    phase boundary dashed verticals; annotate Lag, Exponential, Stationary, Death regions
- For infection/replication cycles: use networkx_pathway_tool — circular DiGraph with
    5 steps (Attachment, Entry, Replication, Assembly, Release) and directed arrows
- For bacterial cell structure: use imagen_tool for realism;
    claude_code_tool if a schematic cross-section is explicitly requested

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT label the organism name if the question asks students to "identify the organism from the diagram"
- For infection cycles: show the cycle steps, NOT the answer to "what is the virulence factor responsible?"
- For culture growth curves: show the curve, NOT the calculated generation time if students must calculate it
- Show ONLY the problem setup — students must identify or analyse the microbiological findings
""",
    # ─── Advanced physics / quantum / condensed matter ──────────────────────
    "quantum_computing": """
QUANTUM COMPUTING / QEC DIAGRAM RULES:
- Quantum circuits: horizontal qubit lines (wires), gates as labeled boxes or standard symbols
- Use tikz_tool for quantum circuit diagrams (preferred); claude_code_tool as fallback
- Label: qubit wire names (q0, q1, ancilla, data), gate names (H, CNOT, X, Z, T, S, Toffoli),
  measurement gates as meter symbols, classical wires as double lines

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT label the error correction code type if students must identify it
- Do NOT label syndrome measurement results, logical operation names, or error type conclusions
- Do NOT add a "Syndrome Table", "Logical Qubit Encoding Path", or annotations that name
  what the circuit DOES — those are what students must derive
- DO label structural components: qubit wire names, individual gate symbols (H, CNOT, X, Z),
  ancilla qubit lines, data qubit lines, measurement output lines

⚠️ DIAGRAM SUBTYPE DISAMBIGUATION:
- Stabilizer/QEC circuit: horizontal qubit lines with gate boxes — NOT a block diagram
- Logical qubit encoding circuit: show physical qubit wires + gate sequence; do NOT add
  a "logical qubit" annotation block that names the encoding scheme
""",
    "condensed_matter": """
CONDENSED MATTER / TOPOLOGICAL INSULATORS DIAGRAM RULES:
- Band structure diagrams: energy E on y-axis, momentum k on x-axis
- Use tikz_tool for band structures; claude_code_tool with matplotlib as fallback
- Label: energy axis (E), momentum axis (k), Fermi level (E_F), "Valence Band",
  "Conduction Band" — these identify axes/regions, not answers

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT label the topological phase name ("Topological Insulator", "Trivial Insulator",
  "Quantum Spin Hall") if students must identify it
- Do NOT label "Z2 Topological Invariant", "Z2 = 1", or the invariant value
- Do NOT label "Band Inversion" as a title or annotation — that names the phenomenon
  students must observe and describe
- Do NOT annotate regions as "Topological" or "Trivial"
- DO label: axes (E, k, E_F), band labels ("Valence Band", "Conduction Band"),
  surface state lines, Dirac point location

⚠️ DIAGRAM SUBTYPE DISAMBIGUATION (CRITICAL — wrong type is the top failure for this subject):
- NORMAL insulator band structure: parabolic valence band (below) + parabolic conduction band
  (above) with an energy gap between them. No surface states crossing the gap.
- TOPOLOGICAL insulator band structure: SAME parabolic bulk bands with gap, BUT with LINEAR
  surface state bands (V-shaped or X-shaped Dirac cone) crossing through the gap at k=0.
  BOTH the bulk bands AND the Dirac cone surface states MUST be drawn. The Dirac cone
  is the KEY distinguishing feature.
  WRONG defaults to avoid: (a) drawing ONLY the Dirac cone without bulk bands,
  (b) drawing parabolic bands with a gap but no crossing surface states (that is trivial insulator).
- DIRAC CONE (standalone): two cones touching at a single point, linear dispersion (V-shape) —
  NOT parabolic. The touching point is the Dirac point at k=0.
""",
    "crystallography": """
CRYSTALLOGRAPHY / X-RAY DIFFRACTION DIAGRAM RULES:
- Crystal unit cells: show atoms at correct lattice positions with bonds
- Use tikz_tool or plotly_tool for 3D unit cells; claude_code_tool for diffraction plots
- Label: lattice points, unit cell boundaries, basis vectors (a, b, c), Miller indices on planes,
  atom species labels (if given), angle labels (θ), plane spacing (d)

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT label "Systematic absences" in a legend or annotation — that is the answer
- Do NOT label diffraction condition outcomes (e.g. "constructive interference here")
- Do NOT annotate structure factor calculation results or Bragg condition conclusions
- DO label: lattice points, unit cell corners, body-center atom, face-center atoms,
  axis labels (a, b, c), Miller plane notation (hkl), angle θ, spacing d

MILLER PLANE GEOMETRY (CRITICAL for data_mismatch prevention):
- (hkl) plane intercepts: x-axis at 1/h, y-axis at 1/k, z-axis at 1/l
  (index 0 means the plane is PARALLEL to that axis — no intercept)
- (100): parallel to the yz-plane, cuts x-axis only at x=1
- (110): cuts x-axis at 1 and y-axis at 1, parallel to z-axis — diagonal in xy-plane
- (111): cuts all three axes equally at 1,1,1 — diagonal through the cube corner to corner
- Draw planes using these exact intercepts; do NOT draw aesthetically pleasing but incorrect orientations
""",
    "game_theory": """
GAME THEORY / ECONOMICS DIAGRAM RULES:
- Payoff matrices: rows = player 1 strategies, columns = player 2 strategies, cells = (P1, P2) payoffs
- Game trees (extensive form): nodes as circles, branches as lines, payoffs as tuples at terminal nodes
- Use claude_code_tool with matplotlib for all game theory diagrams
- Label: player names (Player 1, Player 2), ALL strategy names, ALL payoff values

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT label Nash equilibrium solutions, dominant strategies, or best responses
  (those are what students must find)
- Do NOT label "Pareto Frontier", "Pareto Front", "Pareto Optimal" on curves
- Do NOT highlight or annotate optimal payoff nodes as "optimal" or "equilibrium"
- DO label: player names, strategy branch names, ALL payoff values from the question

⚠️ DATA ACCURACY (CRITICAL — top failure cause for this subject):
- Use EXACT payoff values from the question text — NEVER substitute generic values (a,b,c or 1,2,3)
- If the question specifies payoffs as math expressions (e.g., rendered from equations), use
  the resolved numeric values, not placeholder tokens
- For game trees: use EXACT branch labels (High/Low, Cooperate/Defect, etc.) from the question
""",
    "crispr": """
CRISPR-CAS9 / MOLECULAR BIOLOGY DIAGRAM RULES:
- Molecular mechanism diagrams: labeled protein complexes, DNA strands, guide RNA
- Use imagen_tool for molecular illustrations; claude_code_tool for pathway/comparison diagrams
- Label structural components: Cas9 protein, guide RNA (gRNA), PAM sequence, target DNA strand,
  non-target DNA strand, cleavage site

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT label specific key residues (e.g., R1335, H840, D10, H840) if the question asks
  students to identify which residues are involved in a function
- Do NOT label outcome annotations on mechanism arrows if the question asks what happens
- Do NOT show mechanism conclusions (e.g., "HNH cleaves here" if students must determine it)
- DO label: Cas9 body, gRNA, PAM sequence, DNA strands (target/non-target), cleavage position marker

⚠️ DIAGRAM SUBTYPE DISAMBIGUATION (CRITICAL — wrong type is the top failure for this subject):
- Comparison diagrams (Q asking to compare two pathways/mechanisms): Show as TWO DISTINCT
  SIDE-BY-SIDE PANELS — left panel = Mechanism A (sequential steps top-to-bottom),
  right panel = Mechanism B (sequential steps top-to-bottom).
  NEVER use a concept map, tangled flowchart, or merged single diagram for comparisons.
  Each panel has its own clearly labeled header and sequential numbered steps.
""",
    "stellar_nucleosynthesis": """
STELLAR NUCLEOSYNTHESIS DIAGRAM RULES:
- Stellar interior diagrams: concentric shells showing different burning zones
- Use tikz_tool or claude_code_tool with matplotlib for shell diagrams; matplotlib for HR diagrams
- Label: shell layer names by position (innermost = Fe core outward), burning reactions per shell
  (if NOT the answer), temperature annotations, arrow indicating increasing depth

⚠️ ANSWER HIDING (CRITICAL — STUDENT ASSIGNMENT):
- Do NOT label element products in each shell (C, O, Ne, Si, Fe etc.) if the question asks
  students to identify what nuclear reaction occurs in which shell
- DO label: shell boundaries, layer numbers/positions, temperature ranges if given,
  arrows showing inward/outward direction

⚠️ ONION SHELL STRUCTURE (CRITICAL for wrong_type prevention):
- The diagram MUST be drawn as concentric circles (onion shell cross-section), not a bar chart,
  linear diagram, or abstract schematic
- Layer order from OUTSIDE to CENTER: H-burning → He-burning → C-burning → O-burning →
  Ne-burning → Mg-burning → Si-burning → Fe core
- All layers must be visible as concentric rings; the Fe core is the innermost circle
- Wrong defaults to avoid: drawing only the core, omitting the concentric ring structure,
  or drawing a linear/sequential flowchart instead of concentric shells
""",
}

# ─────────────────────────────────────────────────────────────────────────────
# Imagen description style guidance — one per (domain, diagram_type)
# ─────────────────────────────────────────────────────────────────────────────

_IMAGEN_DESCRIPTION_PROMPTS = {
    # Electrical - Analog
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
    # Electrical - Digital Circuits
    ("electrical", "logic_circuit"): (
        "Draw a digital logic circuit using standard IEEE gate symbols. "
        "AND gate: D-shape (flat left, curved right). OR gate: Shield/bullet shape. "
        "NOT gate: Triangle with small circle (bubble) at output. "
        "NAND/NOR: Same as AND/OR with output bubble. XOR: OR with extra curved line at input. "
        "Inputs on LEFT, outputs on RIGHT. Label all inputs (A, B, C) and outputs (Y, F). "
        "Orthogonal wiring only. Junction dots where wires connect."
    ),
    ("electrical", "flip_flop"): (
        "Draw a flip-flop circuit diagram. Show flip-flop as a rectangle. "
        "Clock input with > (rising edge) or ○> (falling edge) symbol. "
        "For D flip-flop: D input on left, Q and Q̄ outputs on right. "
        "For JK flip-flop: J and K inputs on left, Q and Q̄ on right. "
        "For SR flip-flop: S and R inputs on left, Q and Q̄ on right. "
        "Label all inputs and outputs. Show preset/clear if asynchronous."
    ),
    ("electrical", "mux_demux"): (
        "Draw a multiplexer or demultiplexer diagram. Use trapezoid shape. "
        "MUX: wider on input side (left), narrower on output side (right). "
        "DEMUX: narrower on input side, wider on output side. "
        "Label data inputs (D0, D1, D2...), select lines (S0, S1...), output(s) (Y or Y0, Y1...). "
        "Show select inputs at bottom of trapezoid."
    ),
    ("electrical", "encoder_decoder"): (
        "Draw an encoder or decoder block diagram. Use rectangular block. "
        "Encoder: n input lines → log2(n) output lines (e.g., 8-to-3). "
        "Decoder: log2(n) input lines → n output lines (e.g., 3-to-8). "
        "Label inputs (I0, I1... or A, B, C) and outputs (Y0, Y1... or D0, D1...). "
        "Show enable input (EN) if present."
    ),
    ("electrical", "timing_diagram"): (
        "Draw a digital timing diagram. Time flows left to right along X-axis. "
        "Each signal on a separate horizontal row. Clock signal at TOP. "
        "Digital signals as rectangular waveforms (high=1, low=0). "
        "Show signal transitions as vertical edges (rising/falling). "
        "Label each signal name on the LEFT. Add time markers or period labels. "
        "Align related transitions vertically. Show propagation delay if relevant. "
        "CRITICAL: Only draw INPUT waveforms (CLK, D, A, B, EN, RESET). "
        "OUTPUT signals (Q, Q1, Q2, Q̄, Y) must be left BLANK with '?' labels — "
        "students must determine these themselves. Do NOT reveal the answer."
    ),
    ("electrical", "setup_hold_timing"): (
        "Draw a setup and hold time timing diagram. Show clock signal with clear rising edge. "
        "Show data signal transitioning. Mark tsetup (setup time) region BEFORE clock edge. "
        "Mark thold (hold time) region AFTER clock edge. "
        "Use shaded/hatched regions for setup and hold windows. "
        "Label: CLK, D (data), tsetup, thold, and any violation regions."
    ),
    ("electrical", "fsm_diagram"): (
        "Draw a finite state machine (FSM) state diagram. States as circles with state names inside. "
        "Start state: incoming arrow from outside (or double circle for initial state). "
        "Transitions as arrows between states labeled with input/output conditions. "
        "Moore machine: output inside state circle. Mealy machine: output on transition arrow. "
        "Reset state clearly marked. All transitions must be accounted for."
    ),
    ("electrical", "verilog_module"): (
        "Draw a Verilog/VHDL module block diagram. Module as a rectangle. "
        "Module name centered at top inside the block. "
        "Input ports on LEFT side with arrows pointing INTO block. "
        "Output ports on RIGHT side with arrows pointing OUT of block. "
        "Bidirectional (inout) ports with double-headed arrows. "
        "Bus signals shown with thick lines and width notation (/8, [7:0]). "
        "Clock and reset inputs typically at top-left."
    ),
    ("electrical", "fpga_block"): (
        "Draw an FPGA architecture block diagram. Show CLBs (Configurable Logic Blocks) as rectangles in a grid. "
        "IOBs (I/O Blocks) around the perimeter. Interconnect routing shown as lines between blocks. "
        "Block RAM locations marked if relevant. DSP blocks shown if relevant. "
        "Label major sections: CLB array, I/O ring, interconnect fabric."
    ),
    ("electrical", "clock_domain_crossing"): (
        "Draw a clock domain crossing (CDC) diagram. Show two clock domains separated by a vertical boundary. "
        "Source domain (CLK_A) on left, destination domain (CLK_B) on right. "
        "Show 2-FF synchronizer: two D flip-flops in series in the destination domain. "
        "Label: async signal input, sync_ff1, sync_ff2, synchronized output. "
        "Indicate metastability settling time between FFs. Show clock frequencies if given."
    ),
    ("electrical", "bus_interface"): (
        "Draw a bus interface diagram. Show bus as thick horizontal line with width label. "
        "Connected devices as rectangles above/below the bus. "
        "Address bus, data bus, and control bus as separate lines or as combined system bus. "
        "Label: bus width (32-bit, 64-bit), device names, bus protocol name if relevant (AXI, AHB, Wishbone)."
    ),
    ("electrical", "register_file"): (
        "Draw a register file block diagram. Show as rectangular block with multiple registers inside. "
        "Read ports: address inputs (RA1, RA2), data outputs (RD1, RD2). "
        "Write port: address input (WA), data input (WD), write enable (WE). "
        "Clock input. Label register width and count (e.g., 32 registers × 32 bits)."
    ),
    ("electrical", "alu_datapath"): (
        "Draw an ALU or datapath diagram. ALU as trapezoid or rectangle with operation select. "
        "Show input operands (A, B), output (Result), and status flags (Zero, Carry, Overflow). "
        "Operation select input labeled (ALUOp or Func). "
        "For full datapath: show register file, ALU, muxes, and data paths between them."
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
    # ─── Medical subjects ────────────────────────────────────────────────────
    ("anatomy", "anatomical_diagram"): (
        "Draw a schematic anatomical diagram. Use clean line-art style. "
        "Label all visible structures with leader lines and correct anatomical terminology. "
        "Include directional indicators (superior/inferior, medial/lateral, anterior/posterior). "
        "Colour-code or differentiate tissue types (muscle, bone, nerve, vessel) if helpful. "
        "Do NOT label structures that are the subject of identification questions."
    ),
    ("anatomy", "cross_section"): (
        "Draw an anatomical cross-section (transverse, sagittal, or coronal as specified). "
        "Show all compartments/layers with labeled boundaries. "
        "Use standard anatomical shading conventions: bone (white/stippled), muscle (pink), fat (yellow). "
        "Label key structures with leader lines. Include a small orientation inset diagram."
    ),
    ("anatomy", "histology"): (
        "Draw a schematic histology diagram (light microscopy appearance). "
        "Show tissue layers and cell types clearly. Label cell nuclei, cytoplasm, and key organelles if relevant. "
        "Label each layer/cell type with standard histological terminology. "
        "Include magnification indicator or scale bar. "
        "CRITICAL: Do NOT label the tissue name or diagnosis if that is what students must identify."
    ),
    ("physiology", "action_potential"): (
        "Draw an action potential graph. X-axis: time (ms), Y-axis: membrane potential (mV). "
        "Show threshold line (~-55 mV), resting potential (~-70 mV), depolarization peak (~+30 mV), "
        "repolarization, and hyperpolarization. Label all phases and key voltage levels. "
        "Use a clean single-line waveform on a white background. "
        "CRITICAL: If the question asks students to identify a specific phase or its ionic basis, "
        "do NOT label that phase — use a '?' callout instead."
    ),
    ("physiology", "feedback_loop"): (
        "Draw a homeostatic feedback loop diagram. Show boxes for: stimulus, receptor/sensor, "
        "afferent pathway, integrating centre (e.g., hypothalamus), efferent pathway, effector, response. "
        "Connect with directional arrows. Label the feedback type (negative/positive). "
        "Include the set point and deviation indicators. "
        "CRITICAL: If the question asks students to identify the feedback type, a specific hormone/messenger, "
        "or the effector organ, do NOT label that element — leave it as a blank '?' node."
    ),
    ("physiology", "pressure_volume_loop"): (
        "Draw a cardiac pressure-volume loop. X-axis: ventricular volume (mL), "
        "Y-axis: ventricular pressure (mmHg). Show four phases: isovolumetric contraction, "
        "ejection, isovolumetric relaxation, filling. Label EDV, ESV, stroke volume, "
        "mitral valve opening/closing, aortic valve opening/closing points. "
        "CRITICAL: If the question asks students to calculate or identify stroke volume, EDV, ESV, "
        "or a specific valve event, do NOT annotate that value — omit its label from the diagram."
    ),
    ("biochemistry", "metabolic_pathway"): (
        "Draw a metabolic pathway diagram. Show intermediates as labeled oval nodes. "
        "Show reactions as arrows between nodes. Label enzyme names above/below arrows. "
        "Show cofactors (NAD+/NADH, ATP/ADP, CoA) as labeled side branches. "
        "Use colour to distinguish input substrates (blue), output products (red), and intermediates (white). "
        "CRITICAL: Do NOT label enzymes that are the subject of identification questions."
    ),
    ("biochemistry", "enzyme_kinetics"): (
        "Draw a Michaelis-Menten enzyme kinetics curve. "
        "X-axis: substrate concentration [S] (mM), Y-axis: reaction velocity V (μmol/min). "
        "Show a hyperbolic curve reaching Vmax asymptote. "
        "Mark Vmax with a dashed horizontal line. Mark Km at V = Vmax/2 with dashed lines to both axes. "
        "Label Vmax, Km, and both axes with units. "
        "CRITICAL: If the question asks students to determine Km, Vmax, or inhibitor type, "
        "do NOT mark or label those values — show the curve shape only without those annotations."
    ),
    ("pharmacology", "dose_response"): (
        "Draw a dose-response curve. X-axis: log dose (or log concentration), "
        "Y-axis: % maximum response (0–100%). Show a sigmoid (S-shaped) curve. "
        "Mark EC50 or ED50 at 50% response with dashed lines to both axes. "
        "Label Emax, EC50, and the curve (drug name if specified). "
        "If comparing two drugs or agonist/antagonist, label each curve distinctly. "
        "CRITICAL: If the question asks students to determine EC50/ED50, potency, or Emax, "
        "do NOT mark those values on the graph — show the curve(s) without EC50/Emax markers."
    ),
    ("pharmacology", "pharmacokinetics"): (
        "Draw a plasma concentration-time curve. X-axis: time (hours), "
        "Y-axis: plasma drug concentration (μg/mL or ng/mL). "
        "Show curve with labeled Cmax, tmax, AUC (shaded region), and elimination phase. "
        "Mark t½ (half-life) with dashed lines. If comparing IV vs oral, overlay both curves with labels. "
        "CRITICAL: If the question asks students to calculate Cmax, tmax, AUC, or t½, "
        "do NOT annotate those values — show the curve shape without those markers."
    ),
    ("pathology", "disease_progression"): (
        "Draw a disease progression/staging flow diagram. "
        "Show stages as labeled rectangular boxes connected by directional arrows. "
        "Label each stage with its name, key histological or clinical features. "
        "Use colour coding (normal=green, early=yellow, late=orange, end-stage=red). "
        "CRITICAL: Do NOT reveal the diagnosis if students must identify it."
    ),
    ("microbiology", "bacterial_structure"): (
        "Draw a labeled bacterial cell diagram. Show and label: cell wall, plasma membrane, "
        "cytoplasm, nucleoid (chromosome), ribosomes, flagella (if present), pili, capsule (if present), plasmid. "
        "Differentiate Gram-positive (thick peptidoglycan, no outer membrane) vs "
        "Gram-negative (thin peptidoglycan + outer membrane) if specified. "
        "CRITICAL: Do NOT label the species name if identification is asked."
    ),
    ("microbiology", "infection_cycle"): (
        "Draw a pathogen infection/replication cycle diagram. Show steps as labeled boxes: "
        "attachment → entry → replication → assembly → release. "
        "Use directional arrows between steps. Label key virulence factors at relevant steps. "
        "Show host cell schematically. "
        "CRITICAL: Do NOT label the pathogen name if identification is the question."
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
    # Electrical - Digital Circuits (matplotlib-based)
    ("electrical", "timing_diagram", "matplotlib"): (
        "Draw a digital timing diagram using matplotlib. figsize=(10, 6), dpi=150. "
        "Use ax.step() or ax.fill_between() for rectangular digital waveforms. "
        "Clock signal at top row: use step function with period T. "
        "Other INPUT signals below: use step() with transitions at appropriate times. "
        "Each signal on its own y-level (offset by 1.5 units). "
        "Label signals on LEFT side using ax.text(-0.5, y_level, 'SIGNAL_NAME'). "
        "Add vertical dashed lines at clock edges for alignment. "
        "X-axis: time (ns, µs, or clock cycles). Remove y-axis ticks but keep signal labels. "
        "CRITICAL — ANSWER HIDING: OUTPUT signals (Q, Q1, Q2, Q̄, Y) must be drawn as "
        "BLANK rows with '?' labels or empty horizontal lines for students to fill in. "
        "NEVER draw actual output waveform values — those are the ANSWER. "
        "Only draw INPUT waveforms (CLK, D, A, B, EN, RESET) that are GIVEN in the question. "
        "For rising-edge triggered D-FF: Q changes only at rising CLK edges (low→high). "
        "plt.rcParams({'font.size':10,'font.family':'serif'}), ax.set_xlim(0, T_total), dpi=150."
    ),
    # ── Circuit-with-timing: secondary matplotlib call for the timing portion ──
    ("electrical", "circuit_with_timing", "matplotlib"): (
        "Draw a DIGITAL TIMING DIAGRAM using matplotlib. figsize=(10, 6), dpi=150. "
        "FIGURE TITLE — Choose a descriptive title that reflects WHAT IS GIVEN, "
        "not the answer. Examples: 'Input Waveforms', 'Given Signals', 'Clock & Input Signals'. "
        "NEVER use a title that describes the answer (e.g. NOT 'Output Waveforms'). "
        "WAVEFORM STYLE — CRITICAL: "
        "  - Use ax.step(x, y, where='post') for ALL digital signals — NEVER ax.plot(). "
        "  - Waveforms must be RECTANGULAR / SQUARE (instant transitions, flat tops). "
        "  - NO smooth curves, NO sinusoidal shapes, NO rounded transitions. "
        "Clock signal at top row: perfect square wave using step() with period T. "
        "Other INPUT signals below: use step() with transitions aligned to clock edges. "
        "Each signal on its own y-level (offset by 1.5 units). "
        "Label signals on LEFT side using ax.text(-0.5, y_level, 'SIGNAL_NAME'). "
        "Add vertical dashed lines at clock edges for alignment. "
        "X-axis: time in clock cycles. Remove y-axis ticks but keep signal labels. "
        "CRITICAL — ANSWER HIDING: OUTPUT signals (Q, Q1, Q2, Q̄, Y, Z) must be drawn as "
        "BLANK rows — a dashed gray horizontal line at mid-level with '? (student fills in)' label. "
        "NEVER draw actual output waveform values — those are the ANSWER. "
        "Only draw INPUT waveforms (CLK, D, A, B, EN, RESET) that are GIVEN in the question. "
        "plt.rcParams({'font.size':10,'font.family':'serif'}), ax.set_xlim(0, T_total), dpi=150."
    ),
    ("electrical", "sequential_circuit", "matplotlib"): (
        "Draw a DIGITAL TIMING DIAGRAM for a sequential circuit using matplotlib. figsize=(10, 6), dpi=150. "
        "FIGURE TITLE — Use a descriptive title for what is GIVEN (e.g. 'Input Signals', "
        "'Given Waveforms'). NEVER title it with the answer type. "
        "WAVEFORM STYLE — CRITICAL: "
        "  - Use ax.step(x, y, where='post') for ALL digital signals — NEVER ax.plot(). "
        "  - Waveforms MUST be RECTANGULAR / SQUARE — instant transitions, flat tops. "
        "Clock signal at top: perfect square wave via step(). "
        "Other INPUT signals below: step() with transitions at clock edges. "
        "Each signal offset by 1.5 y-units. Label on LEFT. "
        "Vertical dashed lines at clock edges. "
        "ANSWER HIDING: OUTPUT signals (Q, Q1, Q2, etc.) → BLANK rows with '?' labels. "
        "NEVER draw actual output waveforms. "
        "plt.rcParams({'font.size':10,'font.family':'serif'}), dpi=150."
    ),
    ("electrical", "flip_flop_circuit", "matplotlib"): (
        "Draw a DIGITAL TIMING DIAGRAM for a flip-flop circuit using matplotlib. figsize=(10, 6), dpi=150. "
        "FIGURE TITLE — Use a descriptive title for what is GIVEN (e.g. 'CLK & Data Inputs'). "
        "WAVEFORM STYLE — CRITICAL: "
        "  - Use ax.step(x, y, where='post') for ALL signals — NEVER ax.plot(). "
        "  - Waveforms MUST be RECTANGULAR / SQUARE — instant transitions, flat tops. "
        "Clock (CLK): perfect square wave via step(). D/J/K inputs: step() with given values. "
        "Each signal offset by 1.5 y-units. Label on LEFT. "
        "Vertical dashed lines at rising clock edges. "
        "ANSWER HIDING: Q, Q̄ outputs → BLANK rows with '?' labels. "
        "For rising-edge triggered D-FF: note that Q changes only at rising CLK edges. "
        "plt.rcParams({'font.size':10,'font.family':'serif'}), dpi=150."
    ),
    ("electrical", "counter_circuit", "matplotlib"): (
        "Draw a DIGITAL TIMING DIAGRAM for a counter using matplotlib. figsize=(10, 6), dpi=150. "
        "FIGURE TITLE — Use a descriptive title for what is GIVEN (e.g. 'Clock Signal', 'Counter Inputs'). "
        "WAVEFORM STYLE — CRITICAL: "
        "  - Use ax.step(x, y, where='post') for ALL signals — NEVER ax.plot(). "
        "  - Waveforms MUST be RECTANGULAR / SQUARE — instant transitions, flat tops. "
        "Clock at top row: perfect square wave. "
        "Counter outputs (Q0, Q1, Q2, Q3) below: use step() for each bit toggling at the right edges. "
        "ANSWER HIDING: If the question asks students to 'determine' or 'draw' the counter states, "
        "show ONLY the clock and leave output rows as BLANK with '?' labels. "
        "plt.rcParams({'font.size':10,'font.family':'serif'}), dpi=150."
    ),
    ("electrical", "shift_register", "matplotlib"): (
        "Draw a DIGITAL TIMING DIAGRAM for a shift register using matplotlib. figsize=(10, 6), dpi=150. "
        "FIGURE TITLE — Use a descriptive title for what is GIVEN (e.g. 'Serial Input & Clock'). "
        "WAVEFORM STYLE — CRITICAL: "
        "  - Use ax.step(x, y, where='post') for ALL signals — NEVER ax.plot(). "
        "  - Waveforms MUST be RECTANGULAR / SQUARE. "
        "Clock at top, Serial Input below if given. "
        "Outputs (Q0-Q3 or QA-QD): blank rows with '?' if students must determine them. "
        "plt.rcParams({'font.size':10,'font.family':'serif'}), dpi=150."
    ),
    ("electrical", "waveform", "matplotlib"): (
        "Draw a DIGITAL TIMING/WAVEFORM DIAGRAM using matplotlib. figsize=(10, 6), dpi=150. "
        "WAVEFORM STYLE — CRITICAL: "
        "  - Use ax.step(x, y, where='post') for ALL digital signals — NEVER ax.plot(). "
        "  - Waveforms MUST be RECTANGULAR / SQUARE — instant transitions, flat tops. "
        "  - For analog waveforms only: ax.plot() with smooth lines is acceptable. "
        "Each signal on its own y-level (offset by 1.5 units). "
        "Label signals on LEFT. Vertical dashed lines at clock edges if clock is present. "
        "ANSWER HIDING: Any OUTPUT signal the student must determine → BLANK row with '?'. "
        "plt.rcParams({'font.size':10,'font.family':'serif'}), dpi=150."
    ),
    ("electrical", "setup_hold_timing", "matplotlib"): (
        "Draw setup/hold timing diagram using matplotlib. figsize=(8, 5), dpi=150. "
        "Top row: CLK signal with clear rising edge transition. "
        "Middle row: DATA signal showing stable region around clock edge. "
        "Use ax.axvspan() to shade setup time region BEFORE clock edge (light blue, alpha=0.3). "
        "Use ax.axvspan() to shade hold time region AFTER clock edge (light green, alpha=0.3). "
        "Add dimension arrows for tsetup and thold using ax.annotate(). "
        "Label: 'Setup Time (tsu)', 'Hold Time (th)', metastability window if relevant. "
        "Vertical dashed line at active clock edge. "
        "plt.rcParams({'font.size':10,'font.family':'serif'}), dpi=150."
    ),
    ("electrical", "fsm_diagram", "networkx"): (
        "Draw an FSM state diagram using networkx. Create nx.DiGraph(). "
        "Add state nodes as strings ('S0', 'S1', 'IDLE', 'RUN'). "
        "Add edges with labels for transitions: G.add_edge('S0', 'S1', label='x=1'). "
        "Use nx.circular_layout() or nx.spring_layout(k=2) for positioning. "
        "Draw nodes: nx.draw_networkx_nodes(G, pos, node_size=2000, node_color='lightblue'). "
        "Draw edges: nx.draw_networkx_edges(G, pos, arrows=True, arrowsize=20, connectionstyle='arc3,rad=0.1'). "
        "Draw labels: nx.draw_networkx_labels(G, pos), nx.draw_networkx_edge_labels(G, pos). "
        "Mark start state with an incoming arrow from a 'hidden' node. "
        "figsize=(8, 6). ax.axis('off'). dpi=150."
    ),
    ("electrical", "logic_circuit", "svg"): (
        "Draw a digital logic circuit with standard IEEE gate symbols. "
        "AND gate: D-shape (flat input side, curved output side). "
        "OR gate: Shield/bullet curved shape. "
        "NOT/Inverter: Triangle pointing right with small circle at output. "
        "NAND: AND shape with bubble at output. NOR: OR shape with bubble. "
        "XOR: OR shape with additional curved line on input side. "
        "Inputs on LEFT, outputs on RIGHT. Orthogonal wiring only. "
        "Junction dots where wires connect. Label all inputs (A, B) and outputs (Y, F)."
    ),
    ("electrical", "flip_flop", "svg"): (
        "Draw flip-flop symbol as a rectangle. "
        "Clock input: Triangle symbol (>) on the left edge for rising-edge triggered. "
        "Add bubble before triangle for falling-edge triggered. "
        "D flip-flop: D input left, Q and Q̄ (or Qn) outputs right. "
        "JK flip-flop: J and K inputs on left, Q and Q̄ on right. "
        "Asynchronous inputs (PRE, CLR) at top/bottom with bubbles if active-low. "
        "Label all pins clearly."
    ),
    ("electrical", "mux_demux", "matplotlib"): (
        "Draw MUX/DEMUX using matplotlib.patches.Polygon (trapezoid shape). "
        "MUX: vertices forming trapezoid wider on left (inputs), narrower on right (output). "
        "DEMUX: trapezoid wider on right (outputs), narrower on left (input). "
        "Use ax.text() for input labels (I0, I1, I2, I3) and output labels (Y or Y0-Y3). "
        "Select lines (S0, S1) at bottom with arrows pointing in. "
        "Use FancyArrowPatch for input/output arrows. "
        "figsize=(6, 5), dpi=150."
    ),
    ("electrical", "encoder_decoder", "matplotlib"): (
        "Draw encoder/decoder as rectangular block using patches.FancyBboxPatch. "
        "Input lines on left: use horizontal lines with ax.hlines(). "
        "Output lines on right: use horizontal lines with ax.hlines(). "
        "Label inputs (I0, I1...In or A, B, C...) and outputs (Y0, Y1...Ym). "
        "Show enable input (EN) if present. "
        "Add block label inside: '8:3 Encoder', '3:8 Decoder', etc. "
        "Use ax.annotate() with arrowprops for signal flow direction. "
        "figsize=(6, 5), dpi=150."
    ),
    ("electrical", "verilog_module", "matplotlib"): (
        "Draw Verilog module block using matplotlib.patches.FancyBboxPatch. "
        "Module as a large rounded rectangle. Module name at top-center inside. "
        "Input ports on LEFT edge: draw as small arrows pointing INTO the block. "
        "Output ports on RIGHT edge: draw as small arrows pointing OUT of the block. "
        "Bus signals: thick line with '/8' or '[7:0]' annotation nearby. "
        "Clock (clk) and reset (rst) typically at top-left. "
        "Port names labeled outside the block boundary. "
        "figsize=(7, 6), dpi=150."
    ),
    ("electrical", "clock_domain_crossing", "matplotlib"): (
        "Draw CDC diagram using matplotlib. figsize=(10, 6), dpi=150. "
        "Draw vertical dashed line separating CLK_A domain (left) from CLK_B domain (right). "
        "Label domains: 'Clock Domain A' above left region, 'Clock Domain B' above right region. "
        "Draw signal source in left domain as a box or just a labeled wire. "
        "Draw 2-FF synchronizer in right domain: two D-FF symbols in series. "
        "Label: 'async_in', 'sync_ff1', 'sync_ff2', 'sync_out'. "
        "Use ax.annotate() for metastability note between FF1 and FF2. "
        "Show clock signals CLK_A and CLK_B at bottom of respective domains. dpi=150."
    ),
    ("electrical", "register_file", "matplotlib"): (
        "Draw register file block using matplotlib.patches. figsize=(8, 6), dpi=150. "
        "Main block as FancyBboxPatch rectangle with label 'Register File (32x32)' inside. "
        "Read port 1: RA1 (address in), RD1 (data out). Read port 2: RA2, RD2. "
        "Write port: WA (address in), WD (data in), WE (write enable). "
        "Clock input (CLK) at top or side. "
        "Use small arrows for input/output direction. "
        "Bus lines shown as thick lines with width annotation. dpi=150."
    ),
    ("electrical", "alu_datapath", "matplotlib"): (
        "Draw ALU/datapath using matplotlib.patches. figsize=(10, 7), dpi=150. "
        "ALU as trapezoid (or labeled rectangle) with inputs A, B from top/sides. "
        "Result output at bottom. ALUOp/Func control input. "
        "Status flags (Zero, Carry, Overflow, Negative) as small outputs. "
        "For full datapath: include register file block, muxes (small trapezoids), "
        "PC register, instruction memory, data memory blocks. "
        "Data paths as arrows connecting components. Control signals as thin dashed lines. "
        "Label all signals and bus widths. dpi=150."
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
    # ─── Medical subjects ────────────────────────────────────────────────────
    ("anatomy", "anatomical_diagram", "matplotlib"): (
        "Draw a schematic anatomical diagram using matplotlib. "
        "Use Polygon and Circle patches for organ/structure outlines. "
        "Label structures with ax.annotate() and leader lines. "
        "Use anatomical colour conventions: bone=white/grey, muscle=pink/red, fat=yellow, nerve=yellow/white, vessel=red (artery)/blue (vein). "
        "figsize=(8, 7). ax.axis('off'). Clean white background."
    ),
    ("anatomy", "cross_section", "matplotlib"): (
        "Draw an anatomical cross-section using matplotlib.patches. "
        "Show concentric or layered regions for each compartment. "
        "Use FancyBboxPatch or Polygon for each layer. "
        "Label each region with ax.annotate(). Include a small orientation legend. "
        "figsize=(7, 7). ax.set_aspect('equal'). ax.axis('off')."
    ),
    ("physiology", "action_potential", "matplotlib"): (
        "Draw an action potential curve using matplotlib. "
        "x-axis: 'Time (ms)', range 0–5 ms. y-axis: 'Membrane Potential (mV)', range -90 to +40. "
        "Draw the waveform: resting (-70 mV), threshold (-55 mV dashed line), depolarization rise, +30 mV peak, repolarization, hyperpolarization, return to rest. "
        "Add dashed horizontal lines for threshold and resting potential. Label phases as text annotations. "
        "CRITICAL: If the question asks students to identify a specific phase or its ionic mechanism, "
        "omit that phase's text annotation — leave it blank or use a '?' label. "
        "figsize=(7, 5). Include grid (alpha=0.3)."
    ),
    ("physiology", "pressure_volume_loop", "matplotlib"): (
        "Draw a cardiac pressure-volume (P-V) loop using matplotlib. "
        "x-axis: 'Ventricular Volume (mL)', y-axis: 'Ventricular Pressure (mmHg)'. "
        "Draw a closed loop rectangle with rounded corners representing the four phases. "
        "Label EDV, ESV, stroke volume (horizontal arrow), systolic and diastolic pressures. "
        "Add dashed vertical lines at EDV and ESV. "
        "CRITICAL: If the question asks students to calculate stroke volume, identify EDV/ESV, "
        "or determine a specific valve event, omit the corresponding label from the diagram. "
        "figsize=(6, 5)."
    ),
    ("biochemistry", "metabolic_pathway", "matplotlib"): (
        "Draw a metabolic pathway using matplotlib. "
        "Represent each metabolite as an oval (Ellipse patch) with its name inside. "
        "Connect metabolites with directional arrows (ax.annotate arrowprops). "
        "Label enzyme names above each arrow. Show cofactors (ATP, NADH, CoA) as smaller side-branch ovals. "
        "Use colour: substrate=light blue, product=light green, enzyme=orange label. "
        "CRITICAL: Do NOT label enzyme names if students must identify them — use '?' in place of the enzyme label. "
        "figsize=(10, 6). ax.axis('off')."
    ),
    ("biochemistry", "enzyme_kinetics", "matplotlib"): (
        "Draw a Michaelis-Menten enzyme kinetics curve using matplotlib. "
        "x-axis: '[S] (mM)', y-axis: 'v (μmol/min)'. Plot a hyperbolic curve approaching Vmax. "
        "Draw a dashed horizontal line at Vmax and label it. "
        "Mark Km at V=Vmax/2: draw dashed vertical and horizontal lines from the curve to both axes. "
        "Label Vmax and Km. "
        "CRITICAL: If the question asks students to determine Km or Vmax, "
        "omit those dashed marker lines and labels — show the hyperbolic curve shape only. "
        "figsize=(6, 5). Include grid (alpha=0.3)."
    ),
    ("pharmacology", "dose_response", "matplotlib"): (
        "Draw a dose-response curve using matplotlib. "
        "x-axis: 'Log Dose' (or 'Log [Drug] (M)'), y-axis: '% Maximum Response', range 0–100. "
        "Plot a sigmoid (S-shaped) curve using logistic function. "
        "Mark EC50 at 50% response with dashed lines to both axes. Label EC50, Emax. "
        "If comparing two drugs: overlay curves with different colours and a legend. "
        "CRITICAL: If the question asks students to determine EC50/ED50, Emax, or potency ratio, "
        "omit those dashed marker lines and labels — show the sigmoid curve(s) without EC50/Emax markers. "
        "figsize=(6, 5). Include grid (alpha=0.3)."
    ),
    ("pharmacology", "pharmacokinetics", "matplotlib"): (
        "Draw a plasma concentration-time curve using matplotlib. "
        "x-axis: 'Time (hours)', y-axis: 'Plasma Concentration (μg/mL)'. "
        "Plot absorption rise then exponential decline. "
        "Mark Cmax and tmax with dashed lines and labels. Shade AUC region (alpha=0.2). "
        "Mark t½ on the elimination phase with a dashed horizontal line. "
        "CRITICAL: If the question asks students to calculate Cmax, tmax, AUC, or t½, "
        "omit those annotations — show the curve shape without those markers. "
        "figsize=(7, 5). Include grid (alpha=0.3)."
    ),
    ("microbiology", "bacterial_structure", "matplotlib"): (
        "Draw a labeled bacterial cell diagram using matplotlib.patches. "
        "Draw cell body as an Ellipse. Add Patch layers for: cell wall (outer), membrane (inner), cytoplasm fill. "
        "Add Ellipse for nucleoid, small circles for ribosomes, lines for flagella and pili, outer layer for capsule if relevant. "
        "Label all structures with ax.annotate() leader lines. "
        "figsize=(8, 6). ax.set_aspect('equal'). ax.axis('off')."
    ),
    ("microbiology", "infection_cycle", "matplotlib"): (
        "Draw a pathogen infection/replication cycle using matplotlib. "
        "Represent each step as a FancyBboxPatch with the step name. "
        "Connect steps with curved directional arrows (ax.annotate with connectionstyle='arc3,rad=0.3'). "
        "Steps: Attachment → Entry → Replication → Assembly → Release. "
        "Add small labels for key virulence factors at relevant steps. "
        "CRITICAL: Do NOT label the virulence factor or pathogen name if identification is the question — "
        "use '?' instead. "
        "figsize=(8, 6). ax.axis('off')."
    ),
    ("microbiology", "growth_curve", "matplotlib"): (
        "Draw a bacterial growth curve using matplotlib. "
        "x-axis: 'Time (hours)', y-axis: 'log(CFU/mL)' or 'OD600'. "
        "Plot a sigmoid-like curve with four labeled phases: Lag, Exponential (Log), Stationary, Decline (Death). "
        "Mark phase boundaries with dashed vertical lines. Label each phase with a text annotation. "
        "CRITICAL: If the question asks students to identify a specific phase or calculate generation time, "
        "omit that phase label or the calculated value. "
        "figsize=(7, 5). Include grid (alpha=0.3)."
    ),
    # Missing anatomy/histology nonai prompt
    ("anatomy", "histology", "matplotlib"): (
        "Draw a schematic histology diagram using matplotlib. "
        "Use ax.add_patch() with FancyBboxPatch or Ellipse shapes to represent cell layers. "
        "Show 2-4 distinct tissue layers as horizontal bands with different fill colours. "
        "Add cell nuclei as small dark Ellipse patches within each layer. "
        "Label each layer with ax.annotate() leader lines. "
        "CRITICAL: Do NOT label the tissue or cell type names if that is what students must identify. "
        "figsize=(7, 6). ax.axis('off'). ax.set_aspect('equal')."
    ),
    # Missing pathology/disease_progression nonai prompt
    ("pathology", "disease_progression", "matplotlib"): (
        "Draw a disease progression/staging diagram using matplotlib. "
        "Draw each stage as a FancyBboxPatch. Arrange stages left-to-right or in a flow. "
        "Connect stages with thick directional arrows. "
        "Colour-code stages: normal=green, early=yellow, progressive=orange, end-stage=red. "
        "Label each box with stage name and key features. "
        "CRITICAL: Do NOT label the disease name if students must identify it. "
        "figsize=(10, 5). ax.axis('off')."
    ),
    ("pathology", "histopathology", "matplotlib"): (
        "Draw a schematic histopathology diagram using matplotlib. "
        "Show abnormal tissue architecture using layered FancyBboxPatch shapes. "
        "Indicate cellular changes: enlarged nuclei (larger dark Ellipse patches), "
        "irregular cell shapes (Polygon patches), loss of normal layer organisation. "
        "Label key pathological features with ax.annotate() leader lines. "
        "CRITICAL: Do NOT write the disease name as a label if identification is asked. "
        "figsize=(7, 6). ax.axis('off')."
    ),

    # ── Missing cardiac_loop matplotlib baseline ──────────────────────────────
    ("physiology", "cardiac_loop", "matplotlib"): (
        "Draw a cardiac pressure-volume (P-V) loop using matplotlib. "
        "x-axis: 'Ventricular Volume (mL)', y-axis: 'Ventricular Pressure (mmHg)'. "
        "Construct 4 phases as line segments forming a closed counterclockwise loop: "
        "  Phase 1 (ventricular filling): low pressure ~10 mmHg, volume increases ESV→EDV. "
        "  Phase 2 (isovolumetric contraction): pressure rises 10→80 mmHg, volume constant at EDV=130. "
        "  Phase 3 (ejection): parabolic; volume decreases 130→50 mL, pressure rises to ~120 then falls to 80. "
        "  Phase 4 (isovolumetric relaxation): pressure drops 80→10 mmHg, volume constant at ESV=50. "
        "Label on x-axis: 'EDV=130 mL', 'ESV=50 mL'. "
        "Add horizontal bracket labeled 'SV = EDV − ESV'. "
        "Mark 'Aortic valve opens' and 'Aortic valve closes' at transition corners. "
        "Mark 'Mitral valve opens' and 'Mitral valve closes' at other corners. "
        "Add dashed vertical lines at EDV and ESV. figsize=(6, 5). Include grid (alpha=0.3). "
        "plt.savefig('output.png', dpi=150, bbox_inches='tight')."
    ),

    # ── neurokit2 tool-type prompts ───────────────────────────────────────────
    ("physiology", "action_potential", "neurokit2"): (
        "Generate a neuronal action potential waveform using scipy and matplotlib. "
        "import numpy as np; import matplotlib.pyplot as plt; from scipy.interpolate import CubicSpline. "
        "Model piecewise: resting=-70, threshold=-55, peak=+30, trough=-80. "
        "Time points t=[0,0.5,1.0,1.5,2.5,5.0] ms. "
        "Voltage v=[-70,-70,-55,+30,-80,-70] mV — smooth with CubicSpline(t,v). "
        "t_fine = np.linspace(0,5,500). Plot v_fine = cs(t_fine). "
        "x-axis: 'Time (ms)', 0–5. y-axis: 'Membrane Potential (mV)', −90 to +40. "
        "Add dashed horizontal lines: threshold at -55 (label 'Threshold −55 mV'), "
        "resting at -70 (label 'Resting Potential −70 mV'). "
        "Annotate phase regions with ax.text: 'Depolarisation', 'Repolarisation', 'Hyperpolarisation'. "
        "figsize=(7, 5). ax.grid(alpha=0.3). ax.set_facecolor('#f9f9f9'). "
        "plt.title('Neuronal Action Potential'). "
        "plt.savefig('output.png', dpi=150, bbox_inches='tight')."
    ),
    ("physiology", "cardiac_loop", "neurokit2"): (
        "Generate a cardiac pressure-volume (P-V) loop using numpy and matplotlib. "
        "import numpy as np; import matplotlib.pyplot as plt. "
        "Model: EDV=130 mL, ESV=50 mL, peak_pressure=120 mmHg, baseline_pressure=10 mmHg. "
        "Phase 1 – filling: v1=np.linspace(50,130,100), p1=np.ones(100)*10. "
        "Phase 2 – isovolumetric contraction: v2=np.ones(50)*130, p2=np.linspace(10,80,50). "
        "Phase 3 – ejection: v3=np.linspace(130,50,100), "
        "  p3 = 80 + 40*np.sin(np.linspace(0,np.pi,100))  # parabolic rise-fall. "
        "Phase 4 – isovolumetric relaxation: v4=np.ones(50)*50, p4=np.linspace(80,10,50). "
        "v_all = np.concatenate([v1,v2,v3,v4]); p_all = np.concatenate([p1,p2,p3,p4]). "
        "plt.plot(v_all, p_all, 'b-', linewidth=2.5). "
        "Label: annotate('EDV=130',(130,5)), annotate('ESV=50',(50,5)). "
        "Dashed verticals at x=50 and x=130. Arrow bracket 'SV = 80 mL'. "
        "ax.set_xlabel('Ventricular Volume (mL)'); ax.set_ylabel('Ventricular Pressure (mmHg)'). "
        "figsize=(6,5). ax.grid(alpha=0.3). "
        "plt.savefig('output.png', dpi=150, bbox_inches='tight')."
    ),

    # ── scipy tool-type prompts ───────────────────────────────────────────────
    ("pharmacology", "dose_response", "scipy"): (
        "Generate a dose-response sigmoid curve using scipy.special.expit and matplotlib. "
        "from scipy.special import expit; import numpy as np; import matplotlib.pyplot as plt. "
        "x = np.linspace(-3, 3, 300)  # log10 of dose. "
        "y = 100 * expit(x)  # where x=0 → 50% (EC50 at dose=1 arbitrary unit). "
        "For drug comparisons: plot two curves with different EC50 shifts on same axes. "
        "x-axis: 'Log [Drug] (M)' or 'Log Dose'. y-axis: '% Maximum Response', range 0–105. "
        "Mark EC50 with dashed lines to X and Y axes, label 'EC50 = log10(1) = 0'. "
        "Add horizontal dashed line: Emax = 100%, label 'Emax'. "
        "figsize=(6, 5). ax.grid(alpha=0.3). Legend if multiple curves. "
        "plt.title('Dose-Response Curve'). "
        "plt.savefig('output.png', dpi=150, bbox_inches='tight')."
    ),
    ("pharmacology", "pharmacokinetics", "scipy"): (
        "Generate a pharmacokinetics plasma concentration-time curve using numpy and matplotlib. "
        "import numpy as np; import matplotlib.pyplot as plt. "
        "One-compartment oral absorption model: "
        "  Ka=1.2, Ke=0.2, Vd=30, F=0.8, D=500  # Ka/hr, Ke/hr, Vd in L, D in mg. "
        "  C = (F*D*Ka) / (Vd*(Ka-Ke)) * (np.exp(-Ke*t) - np.exp(-Ka*t))  # μg/mL. "
        "t = np.linspace(0.001, 24, 500) hours. "
        "x-axis: 'Time (hours)'. y-axis: 'Plasma Concentration (μg/mL)'. "
        "Mark Cmax: find index of max C; add dashed lines to both axes, label 'Cmax'. "
        "Mark tmax: x-value at Cmax, dashed vertical line, label 'tmax'. "
        "Shade AUC: ax.fill_between(t, C, alpha=0.15, color='lightblue', label='AUC'). "
        "For IV vs oral: overlay IV curve C_iv = (D/Vd)*np.exp(-Ke*t) in different colour. "
        "figsize=(7, 5). ax.grid(alpha=0.3). Legend. "
        "plt.savefig('output.png', dpi=150, bbox_inches='tight')."
    ),
    ("biochemistry", "enzyme_kinetics", "scipy"): (
        "Generate a Michaelis-Menten enzyme kinetics curve using numpy and matplotlib. "
        "import numpy as np; import matplotlib.pyplot as plt. "
        "Vmax=10, Km=0.5  # μmol/min and mM. "
        "S = np.linspace(0, 5, 500)  # mM. "
        "v = Vmax * S / (Km + S). "
        "x-axis: '[S] (mM)', 0–5. y-axis: 'v (μmol/min)', 0 to 1.1*Vmax. "
        "Add dashed horizontal: y=Vmax, label 'Vmax = {Vmax}'. "
        "Mark Km: at v=Vmax/2; ax.plot([0,Km],[Vmax/2,Vmax/2],'--', color='grey'); "
        "  ax.plot([Km,Km],[0,Vmax/2],'--', color='grey'); "
        "  ax.text(Km,-0.5,'Km',ha='center'); ax.text(-0.15,Vmax/2,'Vmax/2',ha='right'). "
        "For inhibitor comparisons: plot competitive (same Vmax, Km×2) and/or non-competitive "
        "  (Vmax/2, same Km) in different colours with legend. "
        "figsize=(6, 5). ax.grid(alpha=0.3). "
        "plt.savefig('output.png', dpi=150, bbox_inches='tight')."
    ),
    ("physiology", "pressure_volume_loop", "scipy"): (
        "Generate a cardiac pressure-volume (P-V) loop using numpy and matplotlib. "
        "import numpy as np; import matplotlib.pyplot as plt. "
        "Model: EDV=130 mL, ESV=50 mL, systolic BP=120 mmHg, diastolic baseline=10 mmHg. "
        "Phase 1 – filling: v1=np.linspace(50,130,100), p1=np.ones(100)*10. "
        "Phase 2 – isovolumetric contraction: v2=np.ones(50)*130, p2=np.linspace(10,80,50). "
        "Phase 3 – ejection: v3=np.linspace(130,50,100), "
        "  p3 = 80 + 40*np.sin(np.linspace(0,np.pi,100)). "
        "Phase 4 – isovolumetric relaxation: v4=np.ones(50)*50, p4=np.linspace(80,10,50). "
        "v_all=np.concatenate([v1,v2,v3,v4]); p_all=np.concatenate([p1,p2,p3,p4]). "
        "plt.plot(v_all, p_all, 'b-', linewidth=2.5). "
        "ax.axvline(130,ls='--',color='grey',alpha=0.7); ax.axvline(50,ls='--',color='grey',alpha=0.7). "
        "Annotate EDV, ESV, SV on x-axis. Note valve events at corners. "
        "ax.set_xlabel('Ventricular Volume (mL)'); ax.set_ylabel('Ventricular Pressure (mmHg)'). "
        "figsize=(6, 5). ax.grid(alpha=0.3). "
        "plt.savefig('output.png', dpi=150, bbox_inches='tight')."
    ),
    ("physiology", "cardiac_loop", "scipy"): (
        "Generate a cardiac pressure-volume (P-V) loop using numpy and matplotlib. "
        "import numpy as np; import matplotlib.pyplot as plt. "
        "Model: EDV=130 mL, ESV=50 mL, systolic peak=120 mmHg, diastolic=10 mmHg. "
        "Construct 4 phases as numpy arrays and concatenate into a closed loop. "
        "Plot as a smooth closed curve. Label EDV, ESV, stroke volume, valve events. "
        "ax.set_xlabel('Ventricular Volume (mL)'); ax.set_ylabel('Ventricular Pressure (mmHg)'). "
        "figsize=(6, 5). ax.grid(alpha=0.3). "
        "plt.savefig('output.png', dpi=150, bbox_inches='tight')."
    ),
    ("microbiology", "growth_curve", "scipy"): (
        "Generate a bacterial growth curve using numpy and matplotlib (4-phase piecewise model). "
        "import numpy as np; import matplotlib.pyplot as plt. "
        "Piecewise log(CFU/mL) vs time: "
        "  Lag phase (0–2 hr): t1=np.linspace(0,2,50), y1=np.ones(50)*3. "
        "  Exponential phase (2–8 hr): t2=np.linspace(2,8,100), y2=3+(6/6)*(t2-2). "
        "  Stationary phase (8–14 hr): t3=np.linspace(8,14,60), y3=np.ones(60)*9. "
        "  Death phase (14–20 hr): t4=np.linspace(14,20,60), y4=9-0.3*(t4-14). "
        "t_all=np.concatenate([t1,t2,t3,t4]); y_all=np.concatenate([y1,y2,y3,y4]). "
        "plt.plot(t_all, y_all, 'b-', linewidth=2.5). "
        "Phase boundary dashed verticals at t=2,8,14. "
        "Annotate phase names above curve: 'Lag', 'Exponential', 'Stationary', 'Death'. "
        "x-axis: 'Time (hours)', 0–20. y-axis: 'log(CFU/mL)', 2–10. "
        "figsize=(7, 5). ax.grid(alpha=0.3). "
        "plt.savefig('output.png', dpi=150, bbox_inches='tight')."
    ),

    # ── networkx tool-type prompts ────────────────────────────────────────────
    ("microbiology", "infection_cycle", "networkx"): (
        "Generate a pathogen infection/replication cycle diagram using matplotlib + FancyBboxPatch. "
        "import numpy as np, matplotlib.pyplot as plt, matplotlib.patches as mpatches, textwrap. "
        "NODES: define as an ordered clockwise list (e.g. "
        "  ['Attachment', 'Entry / Penetration', 'Replication', 'Assembly', 'Release']). "
        "  n = len(nodes). "
        "  SCALE = max(2.8, n * 0.42). "
        "  FIG_DIM = max(9.0, SCALE * 2.4). "
        "  MARGIN = SCALE + 2.0. "
        "  fig, ax = plt.subplots(figsize=(FIG_DIM, FIG_DIM)). "
        "  pos = {nodes[i]: (SCALE*np.cos(2*np.pi*i/n - np.pi/2), SCALE*np.sin(2*np.pi*i/n - np.pi/2)) "
        "          for i in range(n)}. "
        "EDGES: ONLY sequential [(nodes[i], nodes[(i+1)%n]) for i in range(n)] — NO skipping nodes. "
        "DRAW ORDER (arrows below cards): "
        "  (1) Arrows FIRST (zorder=1): ax.annotate('', xy=pos[dst], xytext=pos[src], "
        "        arrowprops=dict(arrowstyle='->', color='#990000', lw=1.8, mutation_scale=18, "
        "          connectionstyle='arc3,rad=0.25'), zorder=1). "
        "  (2) FancyBboxPatch SECOND (zorder=3), BOX_W=1.5, BOX_H=0.65: "
        "        p = mpatches.FancyBboxPatch((x-BOX_W/2,y-BOX_H/2), BOX_W, BOX_H, "
        "          boxstyle='round,pad=0.12', facecolor='#FFCCCC', edgecolor='#990000', lw=1.8); "
        "        p.set_zorder(3); ax.add_patch(p). "
        "  (3) Text labels LAST (zorder=4): wrap to width=12, fontsize=9, fontweight='bold'. "
        "  (4) Optional edge event labels: ax.text(midpoint, event_name, fontsize=8, color='#660000', zorder=2). "
        "ax.set_xlim(-MARGIN,MARGIN); ax.set_ylim(-MARGIN,MARGIN); ax.set_aspect('equal'); ax.axis('off'). "
        "plt.tight_layout(pad=1.5). plt.savefig('output.png', dpi=150, bbox_inches='tight', facecolor='white')."
    ),
    ("pathology", "disease_progression", "networkx"): (
        "Generate a disease staging/progression flow diagram using networkx DiGraph and matplotlib. "
        "import networkx as nx; import matplotlib.pyplot as plt; "
        "from matplotlib.patches import FancyBboxPatch. "
        "Create nodes for each stage (e.g., 'Normal', 'Grade I / Mild', 'Grade II / Moderate', "
        "  'Grade III / Severe', 'End-Stage'). "
        "Connect stages as a linear left-to-right digraph. "
        "Fixed horizontal positions: pos = {node: (i*2, 0) for i, node in enumerate(stages)}. "
        "DRAW ORDER (critical — prevents arrows appearing on top of cards): "
        "  (1) draw all ax.annotate arrows first (add zorder=1 inside arrowprops dict), "
        "  (2) add FancyBboxPatch per node with patch.set_zorder(3), colour-coded: "
        "  Normal='#90EE90'(green), early='#FFFF99'(yellow), "
        "  intermediate='#FFA500'(orange), end-stage='#FF6B6B'(red), "
        "  (3) add ax.text labels last with zorder=4. "
        "Annotate key histological/clinical features below each stage box (ax.text). "
        "CRITICAL: Do NOT label the disease name if identification is the question. "
        "ax.axis('off'). figsize=(11, 4). "
        "plt.savefig('output.png', dpi=150, bbox_inches='tight')."
    ),
    # ── Physiology ─────────────────────────────────────────────────────────────
    ("physiology", "feedback_loop", "networkx"): (
        "Generate a physiological FEEDBACK LOOP diagram (matplotlib + FancyBboxPatch). "
        "TWO-COLUMN LAYOUT — size scales with node count (see STEP 1). "
        "Draw the circular loop ONLY in ax_loop. Draw any key/mechanism list ONLY in ax_key. "
        "\n"
        "STEP 1 — NODES + DYNAMIC SIZING: "
        "  import textwrap, numpy as np, matplotlib.pyplot as plt, matplotlib.patches as mpatches. "
        "  nodes = ['NodeA', 'NodeB', ..., 'NodeN']  # ordered clockwise. "
        "  n = len(nodes). "
        "  # Scale circle radius and canvas with number of nodes: "
        "  SCALE = max(2.8, n * 0.42)          # e.g. n=7->2.94, n=10->4.2, n=12->5.04. "
        "  FIG_H = max(8.0, SCALE * 2.4)       # canvas height in inches. "
        "  FIG_W = FIG_H * 1.75               # width (3:1 loop:key split). "
        "  MARGIN = SCALE + 2.0               # axes limits = SCALE + box half-width buffer. "
        "  fig, (ax_loop, ax_key) = plt.subplots(1, 2, figsize=(FIG_W, FIG_H), "
        "    gridspec_kw={'width_ratios': [3, 1]}). "
        "  pos = {nodes[i]: (SCALE*np.cos(2*np.pi*i/n - np.pi/2), "
        "                    SCALE*np.sin(2*np.pi*i/n - np.pi/2)) for i in range(n)}. "
        "  wrapped = {nd: textwrap.fill(nd, 12) for nd in nodes}. "
        "\n"
        "STEP 2 — EDGES. ONLY sequential pairs — NO skipping nodes: "
        "  edges = [(nodes[i], nodes[(i+1) % n]) for i in range(n)]. "
        "  *** NEVER add an edge between non-consecutive nodes — it draws a crossing diagonal. *** "
        "\n"
        "STEP 3 — DRAW ORDER (arrows below cards): "
        "  BOX_W, BOX_H = 1.5, 0.65. "
        "  (a) Arrows FIRST (zorder=1): "
        "      for src, dst in edges: "
        "        ax_loop.annotate('', xy=pos[dst], xytext=pos[src], "
        "          arrowprops=dict(arrowstyle='->', color='#CC0000', lw=1.8, "
        "            mutation_scale=18, connectionstyle='arc3,rad=0.25'), zorder=1). "
        "  (b) FancyBboxPatch SECOND (zorder=3): "
        "      for nd in nodes: "
        "        x, y = pos[nd]. "
        "        p = mpatches.FancyBboxPatch((x-BOX_W/2, y-BOX_H/2), BOX_W, BOX_H, "
        "          boxstyle='round,pad=0.12', facecolor='#FFEEDD', edgecolor='#CC4400', lw=1.8). "
        "        p.set_zorder(3); ax_loop.add_patch(p). "
        "  (c) Text labels LAST (zorder=4): "
        "      ax_loop.text(x, y, wrapped[nd], ha='center', va='center', fontsize=9, "
        "        fontweight='bold', zorder=4). "
        "  (d) Central concept (if any): ax_loop.text(0, 0, '...', ha='center', va='center', "
        "        fontsize=11, fontweight='bold', color='#884400', "
        "        bbox=dict(boxstyle='round,pad=0.3', facecolor='#FFFFAA', edgecolor='#CC8800', lw=2), "
        "        zorder=5). "
        "\n"
        "STEP 4 — AXES: "
        "  ax_loop.set_xlim(-MARGIN, MARGIN); ax_loop.set_ylim(-MARGIN, MARGIN). "
        "  ax_loop.set_aspect('equal'); ax_loop.axis('off'). "
        "  ax_key.axis('off'). "
        "  plt.tight_layout(pad=1.5). "
        "  plt.savefig('output.png', dpi=200, bbox_inches='tight', facecolor='white')."
    ),
    ("physiology", "feedback_loop", "matplotlib"): (
        "Generate a FEEDBACK LOOP diagram using matplotlib with TWO subplots. "
        "import textwrap, numpy as np, matplotlib.patches as mpatches. "
        "NODES: define as an ordered clockwise list. "
        "  n = len(nodes). "
        "  SCALE = max(2.8, n * 0.42). "
        "  FIG_H = max(8.0, SCALE * 2.4); FIG_W = FIG_H * 1.75. "
        "  MARGIN = SCALE + 2.0. "
        "  fig, (ax_loop, ax_key) = plt.subplots(1, 2, figsize=(FIG_W, FIG_H), "
        "    gridspec_kw={'width_ratios': [3, 1]}). "
        "  pos = {nodes[i]: (SCALE*np.cos(2*np.pi*i/n-np.pi/2), SCALE*np.sin(2*np.pi*i/n-np.pi/2)) for i in range(n)}. "
        "EDGES: ONLY sequential [(nodes[i], nodes[(i+1)%n]) for i in range(n)] — NO skipping. "
        "DRAW ORDER: "
        "  (1) Arrows first (zorder=1): ax_loop.annotate('', xy=pos[dst], xytext=pos[src], "
        "        arrowprops=dict(arrowstyle='->', color='#CC0000', lw=1.8, mutation_scale=18, "
        "        connectionstyle='arc3,rad=0.25'), zorder=1). "
        "  (2) FancyBboxPatch per node (zorder=3): BOX_W=1.5, BOX_H=0.65. "
        "        p = mpatches.FancyBboxPatch((x-BOX_W/2, y-BOX_H/2), BOX_W, BOX_H, "
        "          boxstyle='round,pad=0.12', facecolor='#FFEEDD', edgecolor='#CC4400', lw=1.8). "
        "        p.set_zorder(3); ax_loop.add_patch(p). "
        "  (3) Text labels last (zorder=4): wrap to width=12, fontsize=9, fontweight='bold'. "
        "  (4) Central concept: ax_loop.text(0,0,...) yellow bbox, zorder=5. "
        "ax_loop.set_xlim(-MARGIN, MARGIN); ax_loop.set_ylim(-MARGIN, MARGIN); "
        "ax_loop.set_aspect('equal'); ax_loop.axis('off'). ax_key.axis('off'). "
        "plt.tight_layout(pad=1.5). plt.savefig('output.png', dpi=200, bbox_inches='tight', facecolor='white')."
    ),
    # ── Biochemistry ────────────────────────────────────────────────────────────
    ("biochemistry", "metabolic_pathway", "networkx"): (
        "Generate a METABOLIC PATHWAY diagram using networkx DiGraph + matplotlib. figsize=(12, 8). "
        "Wrap all node labels: import textwrap; label = textwrap.fill(raw, 14). "
        "Layout: try nx.nx_agraph.graphviz_layout(G, prog='dot') first; "
        "fallback to nx.spring_layout(G, k=2.5, seed=42). "
        "node_size=4000, font_size=9. "
        "Edge labels (enzyme names): nx.draw_networkx_edge_labels with font_size=8 — short abbreviations. "
        "All text: bbox=dict(boxstyle='round,pad=0.2', facecolor='white', edgecolor='gray', alpha=0.85). "
        "ax.axis('off'). plt.tight_layout(pad=2.0). "
        "plt.savefig('output.png', dpi=200, bbox_inches='tight', facecolor='white')."
    ),
    ("microbiology", "disease_progression", "networkx"): (
        "Generate a DISEASE PROGRESSION diagram using networkx DiGraph + matplotlib. "
        "figsize=(12, 5) for linear <=5 stages, (14, 8) for branching. "
        "Wrap stage labels: import textwrap; label = textwrap.fill(raw, 12). "
        "Linear layout: pos = {nodes[i]: (i*3, 0) for i in range(len(nodes))}. "
        "DRAW ORDER (critical — prevents arrows appearing on top of cards): "
        "  (1) draw all ax.annotate curved arrows first (zorder=1 in arrowprops), "
        "  (2) add FancyBboxPatch per node (width=2.0, height=0.8) with patch.set_zorder(3), "
        "      colour-coded from green (normal) to red (severe), "
        "  (3) add ax.text stage labels (font_size=9, zorder=4). "
        "NEVER call nx.draw_networkx_nodes()/nx.draw_networkx_edges() — use FancyBboxPatch + ax.annotate exclusively. "
        "Feature annotations BELOW each box at y=-0.9 with fontsize=8. "
        "ax.axis('off'). plt.tight_layout(pad=2.0). "
        "plt.savefig('output.png', dpi=200, bbox_inches='tight', facecolor='white')."
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
    "Use svg_circuit_tool for any circuit schematics. "
    "ANSWER HIDING (CRITICAL): This is a student assignment — diagrams must NEVER reveal the answer. "
    "If the question asks to 'find', 'determine', 'calculate', 'draw', 'describe', or 'predict' something, "
    "do NOT include that result in the diagram. Show only the PROBLEM SETUP, not the SOLUTION."
)

# ─────────────────────────────────────────────────────────────────────────────
# Subject-Specific Reviewer Rules — comprehensive validation criteria per domain
# ─────────────────────────────────────────────────────────────────────────────

_REVIEWER_DOMAIN_RULES = {
    "electrical": r"""
═══════════════════════════════════════════════════════════════════════════════
ELECTRICAL ENGINEERING DIAGRAM REVIEW RULES
═══════════════════════════════════════════════════════════════════════════════

▶ WIRING & LAYOUT
  • ALL wires MUST be horizontal or vertical — NO diagonal wires
  • Exception: Wheatstone bridge, star-delta conversion, bridge rectifier where diagonal wires are standard
  • No wires crossing through components
  • No floating nodes — every node must connect to at least one component or terminal
  • Power rails: VDD/VCC at top, GND/VSS at bottom (for vertical layouts)

▶ TRANSISTORS — MOSFET (NMOS/PMOS)
  • Three terminals must be clearly labeled or identifiable: Gate (G), Drain (D), Source (S)
  • NMOS: Arrow on source points OUT (away from channel)
  • PMOS: Arrow on source points IN (toward channel), or bubble on gate
  • Body/bulk terminal shown if relevant (4-terminal MOSFET)
  • Verify D-S orientation: for NMOS with VDD at top, Drain is UP, Source is DOWN
  • Transistor name label (M1, M2, Q1) must be present if multiple transistors

▶ TRANSISTORS — BJT (NPN/PNP)
  • Three terminals: Base (B), Collector (C), Emitter (E)
  • NPN: Arrow on emitter points OUT (Not Pointing iN)
  • PNP: Arrow on emitter points IN (Pointing iN Positively)
  • Collector typically toward supply, Emitter toward ground (common-emitter)
  • Transistor name label (Q1, Q2) must be present

▶ RESISTORS
  • Symbol: rectangular (American/IEEE) or zigzag
  • Must have label (R1, R2, RD, RS, RL, etc.) if named in question
  • Must show value (1kΩ, 10kΩ, 1MΩ) if given in question
  • Label and value should not overlap — use white background boxes if needed

▶ CAPACITORS
  • Symbol: two parallel lines (one may be curved for polarized/electrolytic)
  • Polarized capacitors: + terminal must be marked
  • Must have label (C1, CL, Cin, Cout) and value (1µF, 10pF) if specified

▶ INDUCTORS
  • Symbol: coiled/looped line
  • Must have label (L1, L) and value (10mH, 100µH) if specified

▶ DIODES
  • Symbol: triangle pointing to bar (cathode)
  • Current flows from anode (triangle) to cathode (bar)
  • Zener: additional bent lines at cathode
  • LED: with light rays emanating
  • Must have label (D1, D2) if named

▶ VOLTAGE SOURCES
  • DC: Circle with + and − clearly marked, or battery symbol (long/short lines)
  • AC: Circle with sine wave inside
  • Dependent/controlled source: Diamond shape
  • Must show polarity (+ / −) for DC
  • Must show value (5V, 12V, Vdd) if specified
  • Voltage source label (V1, Vgs, Vds, Vin) must match question

▶ CURRENT SOURCES
  • Symbol: Circle with arrow inside indicating current direction
  • Dependent current source: Diamond with arrow
  • Arrow direction MUST match specified current flow direction
  • Must show value (10mA, 1µA) if specified

▶ OPERATIONAL AMPLIFIERS (OP-AMPS)
  • Standard triangle symbol with five terminals:
    - Inverting input (−) on one side
    - Non-inverting input (+) on same side
    - Output on opposite vertex
    - Power supply rails (V+, V−) optional but should be shown if in question
  • Op-amp name (U1, A1) if multiple op-amps
  • Verify correct input polarity signs

▶ LOGIC GATES (Digital Circuits)
  • MUST use standard IEEE/ANSI symbols:
    - AND: D-shaped (flat left, curved right)
    - OR: Curved shield shape
    - NOT/Inverter: Triangle with bubble
    - NAND: AND shape with bubble on output
    - NOR: OR shape with bubble on output
    - XOR: OR shape with additional curved line on input side
    - XNOR: XOR with bubble on output
  • Inputs on LEFT, outputs on RIGHT
  • All inputs and outputs must be labeled (A, B, C for inputs; Y, F, Out for output)
  • If question asks for "gate-level" — must NOT show transistor-level CMOS implementation

▶ CMOS CIRCUITS (Transistor-level)
  • Must show both PMOS (pull-up network) and NMOS (pull-down network)
  • PMOS connected to VDD, NMOS connected to GND
  • Output node between PMOS drain and NMOS drain
  • All transistors must be properly labeled

▶ TRANSFORMERS
  • Two coils with parallel lines between (magnetic core)
  • Primary and secondary windings clearly distinguished
  • Polarity dots if relevant

▶ OSCILLATORS, FILTERS, AMPLIFIERS
  • All components in the topology must be present and correctly connected
  • Feedback paths clearly shown
  • Input and output terminals marked

═══════════════════════════════════════════════════════════════════════════════
DIGITAL CIRCUITS — EXTENDED RULES
═══════════════════════════════════════════════════════════════════════════════

▶ FLIP-FLOPS (D, JK, SR, T)
  • Must use rectangular block symbol with correct pin labels:
    - D flip-flop: D (data), CLK (clock with edge symbol), Q, Qʼ or Q̄
    - JK flip-flop: J, K, CLK, Q, Qʼ
    - SR flip-flop: S (Set), R (Reset), CLK (optional), Q, Qʼ
    - T flip-flop: T (toggle), CLK, Q, Qʼ
  • Clock input MUST have edge indicator:
    - Rising edge: small triangle (▷) inside block at CLK pin
    - Falling edge: bubble (○) followed by triangle
  • Asynchronous inputs (if present):
    - PRE (preset) or SET: typically at top, active-low bubble if inverted
    - CLR (clear) or RST: typically at bottom, active-low bubble if inverted
  • Q and Qʼ on opposite sides — Qʼ is complement of Q
  • Multiple flip-flops should be aligned and labeled (FF0, FF1, FF2 or by function)

▶ MUX (MULTIPLEXER)
  • Standard symbol: Trapezoid with wider side for inputs, narrower for output
  • Data inputs labeled: I0, I1, I2... or D0, D1, D2... (2^n inputs for n select lines)
  • Select lines labeled: S0, S1, S2... or SEL with bus notation [n-1:0]
  • Single output labeled: Y, OUT, or F
  • Optional enable input (EN or G): shown with bubble if active-low
  • Size notation (2:1 MUX, 4:1 MUX, 8:1 MUX) should match pin count

▶ DEMUX (DEMULTIPLEXER)
  • Standard symbol: Trapezoid mirrored from MUX (narrower input side)
  • Single data input labeled: D, IN, or A
  • Select lines labeled: S0, S1, S2... (n select lines give 2^n outputs)
  • Outputs labeled: Y0, Y1, Y2... or O0, O1, O2...
  • Optional enable (EN): active-low shown with bubble
  • Common variations: 1:2, 1:4, 1:8 DEMUX

▶ ENCODER
  • Priority encoder must handle multiple active inputs
  • Inputs: I0, I1, I2... (2^n inputs produce n outputs)
  • Outputs: binary code Y0, Y1... or A0, A1...
  • Valid output (V) or GS (group signal) indicates at least one input active
  • Standard block shape (rectangle) with labeled pins
  • Specify type if relevant: 4-to-2, 8-to-3, priority vs. simple

▶ DECODER
  • Inputs: A0, A1, A2... (n inputs produce 2^n outputs)
  • Outputs: Y0, Y1, Y2... only ONE output active at a time (for simple decoder)
  • Enable input (EN, G1, G2A, G2B): multiple enables may be AND-ed
  • Active-low outputs indicated with bubbles or overbar (Ȳ0, Ȳ1)
  • Standard examples: 2-to-4, 3-to-8 decoder
  • Seven-segment decoder: outputs labeled a, b, c, d, e, f, g

▶ TIMING DIAGRAMS
  • Clock signal MUST be at TOP of diagram
  • All signals vertically aligned with consistent time scale
  • Each signal labeled on LEFT side (CLK, D, Q, RST, EN, etc.)
  • High level at top, low level at bottom for each signal trace
  • Transition edges should be vertical (or near-vertical with small slope for rise/fall time)
  • Time markers/divisions if specific timing values given
  • Causality: output transitions should occur slightly AFTER input transitions
  • Setup and hold regions shaded differently if showing timing constraints
  • Bus signals shown with X-crossover at transitions or hexagonal notation

▶ SETUP & HOLD TIMING DIAGRAMS
  • Clock edge clearly marked with vertical line or arrow
  • Setup time (tsu): Region BEFORE clock edge where data must be stable
    - Shaded region or labeled with double-headed arrow
  • Hold time (th): Region AFTER clock edge where data must remain stable
    - Different shading from setup region, labeled
  • Data valid region clearly distinguished from invalid/changing region
  • Timing violation regions shown if illustrating metastability
  • Annotations: tsu, th, tpd (propagation delay), tclk-q (clock-to-Q delay)
  • Clock period (T or Tclk) labeled if relevant
  • Metastability region shown as shaded uncertain level if applicable

▶ FSM (FINITE STATE MACHINE) STATE DIAGRAMS
  • States represented as CIRCLES or rounded rectangles
  • Each state labeled with:
    - State name (S0, S1, S2 or IDLE, FETCH, DECODE, etc.)
    - Output values (for Moore: inside state; for Mealy: on transitions)
  • INITIAL state marked with:
    - Incoming arrow with no source, OR
    - Double circle, OR
    - Labeled "START" or "RESET"
  • Accepting/final states (if applicable): Double circle or bold outline
  • Transitions as ARROWS between states
  • Each transition labeled with:
    - Input condition triggering the transition
    - Output produced (for Mealy machine): input/output notation
  • Self-loops for transitions that stay in same state
  • Reset transitions shown (often to initial state) if RST signal exists
  • State encoding noted if specified (binary, one-hot, gray)

▶ VERILOG/HDL MODULE DIAGRAMS
  • Module shown as rectangular block
  • Module name at TOP CENTER of block
  • Input ports on LEFT side with arrows pointing IN
  • Output ports on RIGHT side with arrows pointing OUT
  • Bidirectional (inout) ports with double-headed arrows or special notation
  • Each port labeled with signal name
  • Bus widths shown in brackets: data[7:0], addr[15:0]
  • Clock (clk) and reset (rst, rst_n) inputs clearly marked
  • Active-low signals indicated with _n suffix or overbar (rst_n or r̄st)
  • Parameter values shown if parameterized module (WIDTH=8)

▶ FPGA BLOCK DIAGRAMS
  • CLB/Logic blocks as rectangular arrays
  • IOB (I/O blocks) on perimeter
  • Interconnect routing channels shown between blocks
  • Block RAM locations marked if relevant
  • DSP slices marked if used
  • Clock distribution network if shown (H-tree or spine structure)
  • Configuration interface (JTAG, SPI) if showing programming
  • Labels for major blocks: CLB, IOB, BRAM, DSP, PLL/MMCM

▶ CLOCK DOMAIN CROSSING (CDC)
  • Different clock domains clearly separated:
    - Different colors/shading for each domain, OR
    - Explicit domain boundary lines
  • Synchronizer flip-flops at domain boundaries:
    - Minimum 2 flip-flops in series shown
    - Labeled as SYNC or synchronizer
  • Clock signals for each domain labeled (clk_a, clk_b or clk_src, clk_dst)
  • Metastability indication at first synchronizer FF if illustrating concept
  • Handshake signals shown for multi-bit CDC (req, ack)
  • FIFO for multi-bit data crossing with dual-port indication
  • Gray code encoding noted for multi-bit counters crossing domains

▶ BUS & INTERFACE DIAGRAMS
  • Bus width labeled: 8-bit, 16-bit, 32-bit or [7:0], [31:0]
  • Bus drawn as thick line or multiple parallel lines merging
  • Protocol signals grouped logically:
    - Address bus, Data bus, Control signals
  • Standard interface labels if applicable: AXI, APB, Wishbone, SPI, I2C
  • Direction arrows on bus segments (bidirectional data buses noted)
  • Read/Write control signals (RD, WR, R/W̄) clearly marked
  • Chip select (CS) and enable signals shown

▶ REGISTER FILE / REGISTER BANK
  • Rectangular block with register indicators inside
  • Read ports labeled: RD1, RD2 or Read Data 1, Read Data 2
  • Write port labeled: WD or Write Data
  • Address/select inputs: RA1, RA2 (read addresses), WA (write address)
  • Write enable signal: WE, WEN, or Write Enable
  • Clock input for synchronous write
  • Number of registers and width noted: 32×32 (32 registers, 32 bits each)

▶ ALU / DATAPATH DIAGRAMS
  • ALU as standard pentagon or chevron shape
  • Inputs labeled: A, B (operands), ALUControl or Op (operation select)
  • Output labeled: Result, Y, or ALUOut
  • Status flags shown if relevant: Zero (Z), Negative (N), Carry (C), Overflow (V)
  • Function select bits labeled with operation encoding if detailed
  • Internal components (adder, shifter, comparator) shown if expanded view
  • Datapath connections to register file, memory, multiplexers

▶ COUNTER DIAGRAMS
  • Count direction indicated: UP, DOWN, or UP/DOWN with control
  • Reset input (RST, CLR): synchronous or asynchronous noted
  • Load input (LD, LOAD) for parallel load
  • Enable input (EN, CE): controls whether counting occurs
  • Carry/Borrow outputs for cascading (CO, TC)
  • Mode: Binary, BCD, Gray code, Ring, Johnson
  • Modulus: MOD-N counter with N specified
  • Output width: Q[3:0] for 4-bit counter
  ⚠️ ANSWER HIDING: Show ONLY circuit topology and initial state.
  • Do NOT show state transition tables, state sequences, or output values
  • Students must determine state transitions themselves
  • For ring/Johnson counters: show the register circuit with feedback, NOT the sequence of states
""",
    "mechanical": r"""
═══════════════════════════════════════════════════════════════════════════════
MECHANICAL ENGINEERING DIAGRAM REVIEW RULES
═══════════════════════════════════════════════════════════════════════════════

▶ FREE BODY DIAGRAMS (FBD)
  • Object represented as simple shape (rectangle, circle, point mass)
  • ALL forces acting ON the object must be shown as arrows
  • Force arrows must originate from or point to the object's surface/center
  • Each force arrow must be labeled with:
    - Variable name (F1, W, N, f, T)
    - Magnitude if given (100N, 50kg×g)
  • Reaction forces at supports must be shown
  • Weight (W or mg) always points straight DOWN
  • Normal force (N) always PERPENDICULAR to contact surface
  • Friction force (f) always PARALLEL to contact surface, opposing motion
  • No internal forces shown (e.g., don't show stress inside the object)
  • Coordinate system (x-y axes) should be shown if angles are involved

▶ BEAM DIAGRAMS
  • Beam shown as horizontal line or thin rectangle
  • Support types correctly depicted:
    - Pin/Hinge support: Triangle pointing UP (allows rotation, prevents translation)
    - Roller support: Circle or triangle on wheels (allows horizontal movement)
    - Fixed/Built-in support: Hatched rectangle connected to beam (no movement)
  • Point loads: Single arrow with magnitude label
  • Distributed loads (UDL): Multiple arrows or shaded region with w (N/m or kN/m)
  • Moments: Curved arrow with magnitude label
  • Support reactions (RA, RB, MA) shown if asked
  • Dimension annotations showing span length and load positions

▶ TRUSS DIAGRAMS
  • All members as line segments connected at joints
  • Joints labeled alphabetically (A, B, C, D...)
  • Member labels if named (AB, BC, member 1)
  • Support symbols at base joints
  • Applied external loads as arrows with magnitudes
  • Angles and lengths labeled if given

▶ SHEAR FORCE & BENDING MOMENT DIAGRAMS
  • Correctly positioned below the beam diagram
  • X-axis represents position along beam
  • Y-axis represents SFD (kN) or BMD (kN·m)
  • Key values labeled at supports, load points, and points of zero crossing
  • Sign convention consistent (typically: positive shear up, positive moment causing concave-up)

▶ STRESS-STRAIN DIAGRAMS
  • Axes: X = Strain (ε, dimensionless or %), Y = Stress (σ, Pa or MPa)
  • Regions labeled: Elastic region (linear), Yield point, Plastic region, Strain hardening
  • Key points marked: Proportional limit, Yield strength, Ultimate strength, Fracture point
  • Elastic modulus E = slope of linear region (should be noted if asked)

▶ P-V (PRESSURE-VOLUME) DIAGRAMS
  • Axes: X = Volume (V, m³ or L), Y = Pressure (P, Pa, kPa, atm)
  • Process paths clearly drawn:
    - Isothermal: Hyperbolic curve (PV = constant)
    - Isobaric: Horizontal line
    - Isochoric (Isometric): Vertical line
    - Adiabatic: Steeper curve than isothermal (PV^γ = constant)
    - Polytropic: PV^n = constant
  • State points labeled (1, 2, 3 or A, B, C)
  • Direction arrows on process paths showing the process direction

▶ T-S (TEMPERATURE-ENTROPY) DIAGRAMS
  • Axes: X = Entropy (S, J/K or kJ/kg·K), Y = Temperature (T, K or °C)
  • Process paths labeled (isothermal = horizontal, adiabatic/isentropic = vertical)
  • Cycle enclosed area represents net work or heat transfer

▶ FLUID FLOW DIAGRAMS
  • Streamlines shown as curves around objects
  • Flow direction indicated with arrows
  • Boundary layer region indicated near surfaces
  • Separation point marked if relevant
  • Wake region shown behind bluff bodies
  • Free-stream velocity U∞ arrow shown

▶ MOHR'S CIRCLE
  • Circle drawn on σ-τ axes
  • Center correctly positioned at (σ_avg, 0)
  • Radius = √[(σx-σy)²/4 + τxy²]
  • Principal stresses marked on σ-axis
  • Original stress state points labeled

▶ MECHANISMS & LINKAGES
  • All links shown as lines or rectangles
  • Joints marked: pin joint (circle), sliding joint (rectangle on rail)
  • Ground/fixed links shown with hatching
  • Degrees of freedom should be correct for the mechanism type
""",
    "cs": r"""
═══════════════════════════════════════════════════════════════════════════════
COMPUTER SCIENCE DIAGRAM REVIEW RULES
═══════════════════════════════════════════════════════════════════════════════

▶ BINARY TREES
  • Root node at TOP of diagram
  • Children below parent, connected by directed edges (arrows pointing DOWN)
  • Left child to the LEFT of parent, right child to the RIGHT
  • Each node clearly labeled with its value/key
  • Node shape: circles or rounded rectangles
  • No overlapping nodes or crossing edges
  • BST property: for each node, left subtree values < node < right subtree values

▶ GENERAL TREES (N-ary)
  • Root at top, children below
  • Children ordered left-to-right if order matters
  • Each node labeled
  • Level/depth clearly visible from layout

▶ GRAPHS (Directed and Undirected)
  • Nodes as circles with labels inside or adjacent
  • Undirected edges: plain lines
  • Directed edges: arrows pointing in edge direction
  • Edge weights labeled on or near edges if weighted graph
  • Self-loops shown as small circles returning to same node
  • No label collisions — node labels must not overlap edge labels

▶ HEAPS
  • Complete binary tree shape
  • Max-heap: parent ≥ children at every node
  • Min-heap: parent ≤ children at every node
  • Array index mapping shown if asked (root=1, left=2i, right=2i+1)

▶ HASH TABLES
  • Array of buckets shown vertically or horizontally
  • Index numbers visible (0, 1, 2, ...)
  • Key-value pairs in correct buckets
  • Collision handling shown:
    - Chaining: linked list extending from bucket
    - Open addressing: probe sequence indicated

▶ LINKED LISTS
  • Each node as rectangle with two parts: data | pointer
  • Arrows from pointer section to next node
  • NULL/None shown at end (ground symbol or crossed box)
  • Head pointer clearly marked
  • For doubly linked: arrows in both directions

▶ STACKS
  • Vertical arrangement of elements
  • TOP clearly marked (usually at top of drawing)
  • Push/pop direction indicated
  • LIFO principle: most recent element at top

▶ QUEUES
  • Horizontal or vertical arrangement
  • FRONT (dequeue end) and REAR (enqueue end) clearly marked
  • FIFO principle: oldest element at front
  • For circular queue: show wrap-around structure

▶ FLOWCHARTS
  • START/END: Rounded rectangle (oval/stadium shape)
  • PROCESS: Rectangle
  • DECISION: Diamond with Yes/No branches
  • INPUT/OUTPUT: Parallelogram
  • Flow arrows connecting all elements
  • One entry point (START), clear exit points (END)
  • Decision branches labeled (Yes/No, True/False)
  • No dangling elements — every element connected

▶ FINITE STATE MACHINES (FSM/DFA/NFA)
  • States as circles
  • Start state: arrow pointing to it from left/outside
  • Accepting states: double circle
  • Transitions: directed arrows between states
  • Transition labels: input symbols (and output for Mealy machines)
  • All states reachable from start state

▶ SORTING VISUALIZATIONS
  • Array elements as vertical bars or rectangles
  • Bar height proportional to element value
  • Current comparison elements highlighted
  • Sorted portion vs unsorted portion distinguished
  • DO NOT show final sorted result if question asks student to perform sorting

▶ RECURSION TREES / CALL STACKS
  • Each function call as a node
  • Recursive calls as children
  • Return values shown on edges back to parent
  • Base cases clearly marked
  • Stack frames shown in correct LIFO order

▶ UML CLASS DIAGRAMS
  • Class as rectangle divided into 3 sections: Name | Attributes | Methods
  • Visibility markers: + public, - private, # protected
  • Relationships: arrow types for inheritance, composition, aggregation
  • Multiplicity annotations on associations

▶ NETWORK DIAGRAMS (OSI Model, etc.)
  • Layers shown in correct order
  • Data encapsulation shown at each layer
  • Protocol names labeled at each layer
""",
    "civil": r"""
═══════════════════════════════════════════════════════════════════════════════
CIVIL ENGINEERING DIAGRAM REVIEW RULES
═══════════════════════════════════════════════════════════════════════════════

▶ STRUCTURAL FRAMES & TRUSSES
  • All members shown as line segments
  • Joints (nodes) clearly marked — circles or dots
  • Joint labels: alphabetical (A, B, C) or numerical (1, 2, 3)
  • Member labels if specified (member AB, member 1-2)
  • Support symbols correct:
    - Pin: filled triangle
    - Roller: circle under triangle or triangle on wheels
    - Fixed: hatched rectangle attached to member
  • Applied loads as arrows with magnitude labels
  • Dimensions and angles labeled if given

▶ BEAM CROSS-SECTIONS
  • Geometry accurately drawn to scale or proportion
  • Dimensions clearly labeled with dimension lines
  • Neutral axis marked if relevant
  • Centroid location indicated
  • Material type noted if multiple materials
  • For reinforced concrete: rebar placement shown with correct cover

▶ RETAINING WALLS
  • Wall geometry shown with correct dimensions
  • Soil on retained side indicated with hatching or shading
  • Active earth pressure distribution shown (triangular)
  • Water table level if relevant
  • Drainage system if present
  • Base dimensions and thickness labeled

▶ FOUNDATION DIAGRAMS
  • Footing dimensions (width, depth)
  • Column or wall above footing
  • Soil layers indicated if given
  • Bearing pressure distribution shown

▶ COLUMN INTERACTION DIAGRAMS
  • Axes: P (axial load) vs M (moment)
  • Interaction curve showing failure envelope
  • Key points: pure compression, balance point, pure bending
  • Design point plotted if asked

▶ INFLUENCE LINE DIAGRAMS
  • X-axis: position along span
  • Y-axis: influence coefficient for the response quantity
  • Triangular shape for reaction influence lines
  • Trapezoidal for moment at a section
  • Key ordinates labeled

▶ SLOPE STABILITY
  • Cross-section through slope
  • Failure surface (circular arc or planar)
  • Soil layers with properties labeled
  • Water table if present
  • Factor of safety notation
""",
    "math": r"""
═══════════════════════════════════════════════════════════════════════════════
MATHEMATICS DIAGRAM REVIEW RULES
═══════════════════════════════════════════════════════════════════════════════

▶ FUNCTION PLOTS (2D)
  • X-axis and Y-axis clearly drawn with arrow heads
  • Axis labels present (x, y, or variable names from question)
  • Axis tick marks with numerical values at regular intervals
  • Function curve smooth and continuous (unless piecewise)
  • Key points labeled: intercepts (x=0, y=0), maxima, minima, inflection points
  • Asymptotes shown as dashed lines if present
  • Grid lines (optional but helpful) — subtle, not distracting
  • Legend if multiple functions plotted

▶ 3D SURFACE PLOTS
  • Three axes (x, y, z) clearly labeled
  • Orientation clear — which axis is vertical
  • Surface rendered without excessive occlusion
  • Contour lines or mesh visible
  • Color scale with legend if using color mapping

▶ VECTOR FIELDS
  • Grid of arrows covering the domain
  • Arrow direction indicates vector direction at that point
  • Arrow length proportional to vector magnitude (or normalized)
  • Axes labeled
  • Special points (sources, sinks, saddles) identifiable from arrow patterns

▶ GEOMETRIC CONSTRUCTIONS
  • All vertices labeled (A, B, C, ...)
  • All given side lengths labeled with dimension lines
  • All given angles labeled with arc notation
  • Construction lines (dashed) distinguished from final figure
  • Right angle markers (small square) where applicable
  • Circle center points marked if relevant

▶ COORDINATE GEOMETRY
  • Coordinate axes with origin (0,0) marked
  • Points plotted at correct coordinates
  • Point labels (P, Q, A, B) adjacent to points
  • Lines, circles, or curves accurately drawn
  • Equations or parameters labeled on the figure

▶ TRIGONOMETRIC DIAGRAMS
  • Unit circle correctly drawn (radius = 1)
  • Angle θ shown from positive x-axis
  • Reference point on circle clearly marked
  • sin(θ) and cos(θ) projections shown if asked
  • Quadrant labels if relevant

▶ SET DIAGRAMS (Venn Diagrams)
  • Sets as overlapping circles or ellipses
  • Universal set as enclosing rectangle
  • Each set labeled (A, B, C)
  • Regions correctly shaded for operations (union, intersection, complement)
  • Elements listed inside regions if enumerable

▶ NUMBER LINES
  • Horizontal line with arrow heads at both ends
  • Tick marks at regular intervals
  • Numbers labeled at ticks
  • Points or intervals marked as specified
  • Open circles (○) for exclusive bounds, filled circles (●) for inclusive

▶ MATRICES & TRANSFORMATIONS
  • Before and after figures shown for transformations
  • Transformation matrix written in standard notation
  • Original points and transformed points labeled
  • Grid showing deformation if helpful

▶ PROBABILITY TREE DIAGRAMS
  • Branches labeled with probabilities (must sum to 1 at each node)
  • Outcomes labeled at terminal nodes
  • Events described along branches
""",
    "physics": r"""
═══════════════════════════════════════════════════════════════════════════════
PHYSICS DIAGRAM REVIEW RULES
═══════════════════════════════════════════════════════════════════════════════

▶ FREE BODY DIAGRAMS (see Mechanical rules — same principles)
  • All forces shown as labeled arrows
  • Weight pointing down, normal perpendicular to surface
  • Friction opposing motion direction

▶ RAY DIAGRAMS (OPTICS)
  • Optical axis: horizontal line through center of lens/mirror
  • Lens shown as vertical line with appropriate arrow heads:
    - Convex (converging): arrows pointing outward (> <)
    - Concave (diverging): arrows pointing inward (< >)
  • Mirror shown as curved line with correct orientation:
    - Concave: reflecting surface curves toward object
    - Convex: reflecting surface curves away from object
  • Principal rays correctly drawn:
    (1) Ray parallel to axis → through focal point (or appears to come from F)
    (2) Ray through center → continues straight through
    (3) Ray through F → emerges parallel to axis
  • Object shown as vertical arrow (upright)
  • Image: solid lines for real image, dashed for virtual
  • Focal points (F, F') marked on both sides of lens
  • Center (C) and focal length (f) labeled if given

▶ WAVE DIAGRAMS
  • Sinusoidal wave drawn smoothly
  • Wavelength (λ) marked between two corresponding points (crest to crest)
  • Amplitude (A) marked from equilibrium to crest
  • Equilibrium line (x-axis) shown
  • Direction of wave propagation if relevant

▶ ELECTRIC FIELD LINES
  • Lines originate from positive charges (+)
  • Lines terminate on negative charges (−)
  • Lines never cross each other
  • Line density represents field strength (denser = stronger)
  • Lines perpendicular to conductor surfaces
  • Arrowheads show field direction

▶ MAGNETIC FIELD LINES
  • Form closed loops (exit N pole, enter S pole externally)
  • Current-carrying wire: concentric circles (right-hand rule)
  • Solenoid: straight lines inside, loops outside
  • Arrowheads indicate field direction

▶ CIRCUIT DIAGRAMS (see Electrical rules)
  • Standard symbols for all components
  • Current direction marked if asked
  • Voltage polarities shown

▶ SPRING-MASS SYSTEMS
  • Spring attached to fixed support (wall/ceiling with hatching)
  • Mass as a block or labeled circle
  • Equilibrium position marked
  • Displacement x from equilibrium labeled
  • Spring force direction (if shown) opposing displacement

▶ PENDULUMS
  • Pivot point at top (with support indicated)
  • String/rod as a line
  • Bob at bottom (filled circle or shape with mass label)
  • Angle θ from vertical labeled
  • Arc showing swing path if relevant

▶ PROJECTILE MOTION
  • Parabolic path shown
  • Initial velocity vector with components (vx, vy)
  • Key points: launch, apex (max height), landing
  • Range and maximum height dimensions if given

▶ ENERGY LEVEL DIAGRAMS
  • Horizontal lines at different heights representing energy levels
  • Lines labeled with quantum numbers (n = 1, 2, 3...) or energy values
  • Ground state at bottom, excited states above
  • Transitions shown as vertical arrows between levels
  • Photon emission: downward arrow (with λ or E labeled)
  • Photon absorption: upward arrow

▶ NUCLEAR/ATOMIC STRUCTURE
  • Nucleus at center (protons + neutrons shown or labeled)
  • Electron shells/orbits as concentric circles
  • Electrons shown on orbits
  • Atomic number (Z) and mass number (A) labeled if relevant
""",
    "chemistry": r"""
═══════════════════════════════════════════════════════════════════════════════
CHEMISTRY DIAGRAM REVIEW RULES
═══════════════════════════════════════════════════════════════════════════════

▶ MOLECULAR STRUCTURES (Skeletal/Line-Angle)
  • Carbon atoms implied at vertices (not labeled unless necessary)
  • Heteroatoms (O, N, S, P, halogens) explicitly labeled
  • Hydrogen atoms on heteroatoms shown explicitly (OH, NH2)
  • Single bonds as single lines
  • Double bonds as double lines (=)
  • Triple bonds as triple lines (≡)
  • Correct bond angles (sp³ ~ 109.5°, sp² ~ 120°, sp ~ 180°)
  • Stereochemistry: wedge (toward viewer), dashed (away from viewer)
  • Aromatic rings: hexagon with circle inside or alternating double bonds

▶ LEWIS STRUCTURES
  • All valence electrons shown (dots or lines for bonding pairs)
  • Lone pairs shown as pairs of dots
  • Formal charges indicated (+, −) where non-zero
  • Octet rule satisfied (or exceptions noted: expanded octet, etc.)
  • Resonance structures connected with double-headed arrows

▶ ORBITAL DIAGRAMS
  • Energy levels shown as horizontal lines
  • Orbitals grouped by sublevel (1s, 2s, 2p, etc.)
  • Labels for each orbital
  • Electrons shown as arrows (↑ or ↓)
  • Pauli exclusion: max 2 electrons per orbital, opposite spins
  • Hund's rule: electrons fill orbitals singly first

▶ REACTION MECHANISMS
  • Reactants on left, products on right
  • Curved arrows showing electron movement:
    - Arrow head toward electron destination
    - Arrow tail from electron source
  • Intermediates shown in brackets
  • Transition states shown in brackets with ‡ symbol
  • All formal charges maintained
  • Proper nucleophile → electrophile attack arrows

▶ REACTION COORDINATE DIAGRAMS (Energy Profiles)
  • X-axis: Reaction progress/coordinate
  • Y-axis: Free energy (G) or potential energy
  • Reactants' energy on left, products' energy on right
  • Transition state(s) at peak(s)
  • Activation energy (Ea) marked from reactants to transition state
  • ΔG or ΔH labeled (difference between products and reactants)
  • Intermediates in valleys between transition states

▶ PHASE DIAGRAMS
  • Axes: Temperature (T) vs Pressure (P)
  • Phase boundary lines clearly drawn
  • Triple point marked (all three phases in equilibrium)
  • Critical point marked (end of liquid-gas boundary)
  • Regions labeled: Solid, Liquid, Gas (Vapor)
  • Slope of solid-liquid line correct (positive for most, negative for water)

▶ TITRATION CURVES
  • X-axis: Volume of titrant added (mL)
  • Y-axis: pH (for acid-base) or potential (for redox)
  • Equivalence point marked (steepest region)
  • Initial pH value consistent with analyte
  • Final pH value consistent with excess titrant
  • Buffer region relatively flat (for weak acid/base)

▶ LAB APPARATUS DIAGRAMS
  • All glassware clearly drawn (flask, beaker, burette, condenser, etc.)
  • Labels for each piece of equipment
  • Reagent labels inside containers
  • Connections shown (tubes, clamps, stands)
  • Heat source indicated if relevant
  • Safety equipment if relevant (fume hood implied)

▶ CRYSTAL STRUCTURES (Unit Cells)
  • Lattice points shown as spheres or labeled points
  • Unit cell boundaries clearly marked
  • Coordination number visible from structure
  • Face-centered, body-centered, or simple cubic distinguished
""",
    "computer_eng": r"""
═══════════════════════════════════════════════════════════════════════════════
COMPUTER ENGINEERING DIAGRAM REVIEW RULES
═══════════════════════════════════════════════════════════════════════════════

▶ CPU BLOCK DIAGRAMS
  • Major functional units as labeled rectangles:
    - Control Unit (CU)
    - Arithmetic Logic Unit (ALU)
    - Register File / Registers
    - Program Counter (PC)
    - Instruction Register (IR)
    - Memory Address Register (MAR)
    - Memory Data Register (MDR)
  • Data buses shown as thick lines or double lines with width labels (32-bit, 64-bit)
  • Control signals as thin arrows with labels
  • Address bus, data bus, control bus distinguished
  • Memory interface shown (Cache, RAM)
  • Clock signal if relevant

▶ PIPELINE DIAGRAMS
  • Standard 5-stage RISC pipeline stages:
    - IF (Instruction Fetch)
    - ID (Instruction Decode / Register Read)
    - EX (Execute / ALU)
    - MEM (Memory Access)
    - WB (Write Back)
  • Stages shown as rectangles in a row
  • Pipeline registers between stages (IF/ID, ID/EX, EX/MEM, MEM/WB)
  • Data flow arrows left-to-right
  • Hazards indicated if asked (data hazards, control hazards)
  • Forwarding paths shown if relevant

▶ MEMORY HIERARCHY
  • Pyramid or layered diagram
  • Fastest/smallest at top: Registers
  • Then: L1 Cache → L2 Cache → L3 Cache → RAM → SSD/HDD
  • Labels for each level
  • Typical sizes and access times if given
  • Arrows showing data movement direction

▶ CACHE ORGANIZATION
  • Array structure showing sets and ways
  • Tag, Index, Offset breakdown of address
  • Valid bit, tag field, data field in each line
  • Hit/miss path shown if relevant

▶ LOGIC CIRCUITS (Digital Design)
  • MUST use standard IEEE/ANSI gate symbols:
    - AND: D-shaped (flat on input side, curved on output)
    - OR: Shield/bullet shape with curved back
    - NOT: Triangle with bubble at output
    - NAND: AND with bubble at output
    - NOR: OR with bubble at output
    - XOR: OR with extra curved line at input
    - XNOR: XOR with bubble at output
    - Buffer: Triangle (no bubble)
  • Inputs on LEFT side of gates
  • Outputs on RIGHT side of gates
  • Input labels (A, B, C, X1, X2, ...) at left edge
  • Output labels (Y, F, Z, Out) at right edge
  • Signal flow LEFT to RIGHT
  • Wires: horizontal and vertical only (no diagonals)
  • Junction dots where wires connect
  • No dots where wires simply cross without connecting

▶ FLIP-FLOPS & SEQUENTIAL CIRCUITS
  • Standard symbols:
    - SR flip-flop: Rectangle with S, R inputs, Q, Q' outputs
    - D flip-flop: Rectangle with D input, clock, Q, Q' outputs
    - JK flip-flop: Rectangle with J, K inputs, clock, Q, Q' outputs
    - T flip-flop: Rectangle with T input, clock, Q, Q' outputs
  • Clock input shown with > symbol (triangle at edge)
  • Active-low inputs indicated with bubble
  • Asynchronous preset/clear inputs if present

▶ MULTIPLEXERS & DEMULTIPLEXERS
  • Trapezoid shape (wider on input side for MUX, wider on output side for DEMUX)
  • Data inputs labeled (D0, D1, D2, ...)
  • Select inputs labeled (S0, S1, ...)
  • Output labeled (Y or Out for MUX; Y0, Y1, ... for DEMUX)

▶ ARITHMETIC CIRCUITS
  • Half adder: shows A, B inputs; Sum, Carry outputs
  • Full adder: shows A, B, Cin inputs; Sum, Cout outputs
  • Ripple carry adder: chain of full adders with carry propagation shown
  • ALU: rectangular block with operation select, data inputs, result output, status flags

▶ FINITE STATE MACHINE (FSM) DIAGRAMS
  • States as circles with state names inside
  • Start state indicated by arrow from nowhere (or double arrow)
  • Accepting/final states as double circles (if applicable)
  • Transitions as labeled arrows between states
  • Transition labels: input / output (for Mealy) or just input (for Moore)

▶ TIMING DIAGRAMS
  • Time axis horizontal (left to right)
  • Each signal on a separate row
  • Digital signals as square waves (high/low)
  • Clock signal at top
  • Signal transitions aligned vertically where simultaneous
  • Setup time, hold time marked if relevant
  • Propagation delay indicated if asked
""",
    # ── Medical sciences ────────────────────────────────────────────────────
    "anatomy": r"""
═══════════════════════════════════════════════════════════════════════════════
ANATOMY DIAGRAM REVIEW RULES
═══════════════════════════════════════════════════════════════════════════════

▶ LABELS & TERMINOLOGY
  • All visible structures must be labeled with correct anatomical terminology
  • Directional indicators (superior/inferior, medial/lateral, anterior/posterior, proximal/distal)
    must be correct and present where the diagram type requires them
  • Labels must NOT overlap with drawing elements — use leader lines
  • Abbreviations must match standard anatomical convention (e.g., LV = Left Ventricle, not arbitrary)

▶ COLOUR CONVENTIONS
  • Bone/cartilage: white or pale grey (stippled shading acceptable)
  • Muscle: pink or red (matching depth/type if labelled)
  • Fat/adipose: yellow
  • Nerve: yellow or white with thin outline
  • Artery: red
  • Vein: blue or purple
  • Lymphatic: green (when shown)

▶ STRUCTURAL ACCURACY
  • Relative proportions of organs/structures must be approximately correct
  • Organs must be shown in anatomically correct spatial relationships
  • For layered cross-sections: layer order must be anatomically accurate (e.g., skin → subcutaneous fat → fascia → muscle)

▶ ANSWER HIDING
  • If the question asks students to IDENTIFY or LABEL a structure:
    - The corresponding label must NOT appear in the diagram
    - Use a blank arrow or numbered callout instead
  • If the question asks students to TRACE a pathway or NAME a nerve/vessel:
    - Do NOT label the pathway/nerve/vessel being asked about

▶ CROSS-SECTION SPECIFICS
  • Include a small orientation inset (e.g., axial/sagittal/coronal indicator)
  • Show correct relative sizes of compartments
  • Left/right orientation must match anatomical convention (patient's left = diagram right for axial views)

▶ HISTOLOGY SPECIFICS
  • Cell layers must be distinct and clearly separated
  • Cell nuclei: small, dark, correctly positioned within cell
  • Scale bar or magnification indicator must be present if shown in original question
  • Do NOT label cell type / tissue name if that is what students must identify
""",
    "physiology": r"""
═══════════════════════════════════════════════════════════════════════════════
PHYSIOLOGY DIAGRAM REVIEW RULES
═══════════════════════════════════════════════════════════════════════════════

▶ ACTION POTENTIAL PLOTS
  • x-axis must be time (ms), y-axis must be membrane potential (mV)
  • Resting potential: ~–70 mV; threshold: ~–55 mV (dashed line); peak: ~+30 mV
  • Phases must be correctly sequenced: rest → depolarization → peak → repolarization → hyperpolarization → rest
  • Dashed reference lines for threshold and resting potential must be present
  • Phase labels (depolarization, repolarization, etc.) must be correctly positioned
  • ANSWER HIDING: Do NOT show the phase name/arrow that students are asked to identify

▶ PRESSURE-VOLUME LOOPS
  • x-axis: ventricular volume (mL), y-axis: ventricular pressure (mmHg)
  • Four phases of the cardiac cycle must be correctly labeled: isovolumetric contraction, ejection, isovolumetric relaxation, filling
  • EDV and ESV must be marked (vertical dashed lines)
  • Stroke volume = EDV − ESV (shown as horizontal arrow or bracket)
  • Mitral and aortic valve events at correct corners
  • ANSWER HIDING: Do NOT draw a modified loop (e.g., afterload/preload change) if that is what students must predict

▶ FEEDBACK LOOP DIAGRAMS
  • Must include: stimulus, sensor/receptor, afferent pathway, control centre (integrating centre), efferent pathway, effector, response
  • Negative vs positive feedback must be clearly labeled
  • Set point must be indicated
  • Arrows must show correct directional flow

▶ AXES & UNITS
  • All axes must have correct units (mV, mmHg, mL, s, ms, Hz)
  • Grid lines acceptable at alpha=0.3
  • Font size ≥ 10 pt for readability
""",
    "biochemistry": r"""
═══════════════════════════════════════════════════════════════════════════════
BIOCHEMISTRY DIAGRAM REVIEW RULES
═══════════════════════════════════════════════════════════════════════════════

▶ METABOLIC PATHWAY DIAGRAMS
  • Each intermediate metabolite must be shown as a labeled oval/node
  • Enzyme name must be labeled on or adjacent to each reaction arrow
  • Cofactors (ATP, ADP, NAD+, NADH, CoA, Pi) shown as side branches with correct directionality
  • Irreversible reactions: single-headed arrow; reversible: double-headed arrow
  • ANSWER HIDING: If students must name an enzyme or metabolite, leave that label blank/numbered

▶ ENZYME KINETICS CURVES
  • x-axis: [S] with concentration units (e.g., mM, μM); y-axis: reaction velocity V (μmol/min or equivalent)
  • Curve must be hyperbolic (Michaelis-Menten) reaching Vmax asymptote
  • Vmax: horizontal dashed line clearly labeled
  • Km: marked at V = Vmax/2 with dashed lines to both axes, clearly labeled
  • For inhibitor comparisons: correctly show competitive (same Vmax, higher Km) or non-competitive (lower Vmax, same Km)
  • ANSWER HIDING: Do NOT label Vmax or Km values if students are asked to calculate them from given data

▶ ACCURACY
  • Pathway direction (anabolic vs catabolic) must match the question context
  • Regulatory enzyme steps (committed steps) may be marked if given in question
""",
    "pharmacology": r"""
═══════════════════════════════════════════════════════════════════════════════
PHARMACOLOGY DIAGRAM REVIEW RULES
═══════════════════════════════════════════════════════════════════════════════

▶ DOSE-RESPONSE CURVES
  • x-axis: log dose or log[Drug] with units; y-axis: % maximum response (0–100%)
  • Curve shape must be sigmoid (S-shaped logistic function), not linear
  • EC50 (or ED50) marked at 50% response with dashed lines to both axes, labeled
  • Emax (100% response) horizontal dashed line, labeled
  • For agonist/antagonist comparison: correct relative positions (competitive antagonist shifts curve right; non-competitive lowers Emax)
  • ANSWER HIDING: Do NOT label EC50 values if students must read them off or calculate them

▶ PHARMACOKINETICS CURVES
  • x-axis: time with units (hours); y-axis: plasma drug concentration with units (μg/mL, ng/mL)
  • Curve shape: absorption rise (first-order) followed by elimination decline (exponential)
  • Cmax (peak concentration) and tmax (time to peak) labeled with dashed lines to axes
  • AUC region shaded (alpha=0.2) if reference in question
  • t½ marked on elimination slope with dashed line
  • For IV vs oral: IV curve starts high and declines; oral curve has a rising phase
  • ANSWER HIDING: Do NOT show AUC value, t½ value, or Cmax value if students must calculate them

▶ DRUG NAMING
  • Drug names must be spelled correctly (use INN names)
  • Do NOT include mechanism of action text if students must describe it
""",
    "pathology": r"""
═══════════════════════════════════════════════════════════════════════════════
PATHOLOGY DIAGRAM REVIEW RULES
═══════════════════════════════════════════════════════════════════════════════

▶ DISEASE PROGRESSION DIAGRAMS
  • Stages must flow in correct pathological sequence (e.g., Normal → Hyperplasia → Dysplasia → CIS → Invasive)
  • Colour coding must progress logically (green→yellow→orange→red for severity)
  • Each stage box must include key pathological features (cellular/histological changes)
  • Stage names must be clinically standard (TNM staging, WHO grading, etc.)
  • ANSWER HIDING: Do NOT write the disease diagnosis label if students must identify it
    (use a neutral title like "Disease X Progression" or "Progression Stages")

▶ HISTOPATHOLOGY DIAGRAMS
  • Show architectural distortion: enlarged, irregular nuclei; high N:C ratio; loss of polarity
  • Normal tissue shown for comparison on same diagram (if relevant)
  • Do NOT annotate "malignant" / "carcinoma" / specific diagnosis if that is what students must identify

▶ GENERAL
  • Microscopic vs macroscopic view must be clearly distinguished
  • Scale bar or level indicator (low/high magnification) should be present if relevant
""",
    "microbiology": r"""
═══════════════════════════════════════════════════════════════════════════════
MICROBIOLOGY DIAGRAM REVIEW RULES
═══════════════════════════════════════════════════════════════════════════════

▶ BACTERIAL STRUCTURE DIAGRAMS
  • Must label: cell wall, plasma membrane, cytoplasm, nucleoid, ribosomes
  • Optional (if relevant): capsule, flagella, pili, plasmid, outer membrane (Gram-negative)
  • Gram-positive: thick peptidoglycan layer, NO outer membrane
  • Gram-negative: thin peptidoglycan, WITH outer membrane (lipopolysaccharide)
  • ANSWER HIDING: Do NOT label the Gram-type or species name if students must identify it

▶ INFECTION/REPLICATION CYCLE DIAGRAMS
  • Steps must be in correct biological sequence for the pathogen type
  • Correct terminology: adsorption/attachment → penetration/entry → uncoating → replication → assembly → release
  • Bacteriophage cycles: lytic (immediate) vs lysogenic (integration) clearly differentiated
  • ANSWER HIDING: Do NOT label the pathogen species or the step name/mechanism if students must identify it

▶ GROWTH CURVE DIAGRAMS
  • Four phases must be labeled: Lag, Exponential (Log), Stationary, Death (Decline)
  • x-axis: time (hours); y-axis: log(CFU/mL) or OD600
  • Phase boundaries shown with dashed vertical lines
  • Annotations may note generation time during exponential phase
  • ANSWER HIDING: Do NOT include specific CFU numbers or time values if students must calculate them
""",
}

# ─────────────────────────────────────────────────────────────────────────────
# Reviewer style hints — for GeminiDiagramReviewer
# ─────────────────────────────────────────────────────────────────────────────

_REVIEWER_STYLE_HINTS = {
    (
        "electrical",
        "circuit_schematic",
    ): "Expect a circuit schematic with component symbols and wires.",
    (
        "electrical",
        "bode_plot",
    ): "Expect two subplots: magnitude (dB) and phase (degrees) vs frequency.",
    ("electrical", "iv_curve"): "Expect an I-V characteristic curve with labeled axes.",
    (
        "mechanical",
        "free_body_diagram",
    ): "Expect a free body diagram with labeled force arrows on an object.",
    (
        "mechanical",
        "beam_diagram",
    ): "Expect a beam with support symbols and load arrows.",
    (
        "mechanical",
        "truss_diagram",
    ): "Expect a truss structure with members, joints, and load arrows.",
    (
        "mechanical",
        "fluid_flow",
    ): "Expect a fluid flow diagram around a cylinder with streamlines, boundary layer, separation point, wake region, and U∞ velocity arrow. Two-panel layout (Laminar/Turbulent) is correct.",
    (
        "mechanical",
        "pressure_distribution",
    ): "Expect a Cp vs angle curve showing pressure coefficient distribution around a cylinder.",
    (
        "mechanical",
        "stress_strain",
    ): "Expect a stress-strain curve with labeled yield point, ultimate strength, and fracture.",
    (
        "cs",
        "binary_tree",
    ): "Expect a tree diagram with circular nodes and directed edges.",
    ("cs", "graph_network"): "Expect a graph with labeled nodes and edges.",
    (
        "cs",
        "flowchart",
    ): "Expect a flowchart with process boxes, decision diamonds, and flow arrows.",
    (
        "civil",
        "truss_frame",
    ): "Expect a truss structure with labeled members and support reactions.",
    (
        "math",
        "function_plot",
    ): "Expect a coordinate plot with labeled axes and a smooth curve.",
    (
        "math",
        "geometric_construction",
    ): "Expect a geometric figure with labeled vertices and dimensions.",
    (
        "physics",
        "ray_diagram",
    ): "Expect a ray diagram with optical axis, lens/mirror, and ray paths.",
    (
        "physics",
        "spring_mass",
    ): "Expect a spring-mass diagram with labeled spring and mass.",
    (
        "chemistry",
        "molecular_structure",
    ): "Expect a molecular structure diagram with atomic symbols and bonds.",
    (
        "chemistry",
        "lab_apparatus",
    ): "Expect labeled laboratory glassware and equipment.",
    (
        "computer_eng",
        "cpu_block_diagram",
    ): "Expect a block diagram with labeled functional units and data buses.",
    (
        "computer_eng",
        "pipeline_diagram",
    ): "Expect pipeline stages shown as labeled boxes in sequence.",
    (
        "computer_eng",
        "logic_circuit",
    ): "Expect a logic circuit with standard IEEE gate symbols.",
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

    def get_reviewer_domain_rules(self, domain: str) -> str:
        """
        Returns comprehensive subject-specific review rules for the diagram reviewer.
        These are detailed validation criteria covering all component types for the domain.
        """
        return _REVIEWER_DOMAIN_RULES.get(domain, "")

    def get_all_domains(self) -> list:
        """Returns list of all supported domains."""
        return list(_REVIEWER_DOMAIN_RULES.keys())
