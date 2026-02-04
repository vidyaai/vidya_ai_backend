# Plan: Universal Technical Diagram Generation for Assignment Questions

## Problem
Currently, the assignment generator produces text-only questions. For technical topics across all domains (computer science, engineering, physics, electronics), students need visual diagrams to comprehend concepts. Whether it's a data structure like a binary tree, a neural network architecture, an RF circuit, CPU internals, or a physics diagram, visual representations dramatically improve understanding.

## Scope: Generate ANY Technical Image
This system should be capable of generating diagrams for:

### Computer Science Concepts
- **Data Structures**: Graphs (directed/undirected), linked lists (singly/doubly/circular), trees (binary, BST, AVL, red-black), arrays, stacks, queues, heaps, hash tables
- **Algorithms**: Sorting visualizations, search trees, dynamic programming tables, recursion trees
- **Machine Learning**: Neural network architectures, backpropagation flow diagrams, decision trees, computational graphs, activation functions
- **Computer Architecture**: CPU block diagrams, ALU circuits, memory hierarchy, cache organization, pipelining stages

### Electronics & Hardware
- **Circuits**: RF circuits, amplifiers, filters, oscillators, digital logic gates, flip-flops
- **Components**: Transistor configurations, IC diagrams, PCB layouts
- **Signal Processing**: Waveforms, frequency response, Bode plots

### Physics & Engineering
- **Mechanics**: Free body diagrams, trusses, beams, manometers, fluid systems
- **Thermodynamics**: P-V diagrams, T-S diagrams, heat engines
- **Optics**: Ray diagrams, lens systems, interference patterns
- **Electricity & Magnetism**: Electric fields, magnetic fields, Maxwell's equations visualizations

### Mathematics & Visualization
- **Plots**: Function graphs, 3D surfaces, vector fields, contour plots
- **Geometry**: Geometric constructions, cross-sections, projections

## Current Architecture (Relevant)
- **`assignment_generator.py`**: GPT-5 generates questions as structured JSON via `_generate_questions()` → `_post_process_questions()`
- **Question schema**: Already has `hasDiagram: bool` and `diagram: { s3_key, s3_url, file_id, ... }` fields (used for PDF *import*, not generation)
- **S3 storage**: Diagrams already stored at `assignments/{id}/diagrams/{file_id}.png` with presigned URL support
- **Frontend**: `DiagramImage`/`DiagramPreviewImage` components already render diagrams from S3 for all question types — zero frontend rendering changes needed

## Recommended Approach: Hybrid Code-Based + AI Generation

Use a **three-tier generation strategy**:

1. **Primary: Code-based rendering** (matplotlib/schemdraw/networkx) — LLM generates Python rendering code, execute in sandboxed subprocess
2. **Secondary: AI image generation** (DALL-E 3/GPT-4o) — When code-based rendering is not suitable or fails
3. **Tertiary: SVG markup** — Fallback for simple geometric shapes

### Why this layered approach

| Method | Use Cases | Advantages | Limitations |
|--------|-----------|------------|-------------|
| **matplotlib code** | Plots, graphs, diagrams, physics, simple structures | Precise labels, exact dimensions, deterministic, cheap, fast | Complex 3D or artistic rendering |
| **schemdraw code** | Electrical circuits, signal flow, block diagrams | Perfect for circuit symbols, clean routing | Only for circuit-type diagrams |
| **networkx + matplotlib** | Graphs, trees, network diagrams, data structures | Graph layout algorithms, easy node/edge styling | Layout can be unpredictable |
| **AI generation (DALL-E/GPT-4o)** | Complex visualizations, realistic renders, artistic diagrams, anything not easily coded | Handles any concept, flexible, no coding complexity | Imprecise labels, expensive, slower, less deterministic |
| **SVG markup** | Simple geometric shapes, basic icons | Lightweight, scalable | LLMs struggle with complex SVG geometry |

### Model choice for code generation
The LLM that generates the rendering code does NOT need to be GPT-5. Any strong code-generation model works since the output is Python code, not prose. Options:
- **Claude Sonnet/Opus** — excellent at generating correct matplotlib and data structure visualization code
- **GPT-5 / GPT-4o** — already integrated in the codebase
- **Open-source (Codestral, DeepSeek)** — if cost is a concern

Recommendation: Use whichever model already powers question generation (currently GPT-5) to keep the pipeline simple — the diagram_spec is generated in the same API call as the questions. If diagram code quality is poor, a separate "diagram code refinement" call to Claude or GPT-4o can be added.

### Diagram type routing

| Concept Domain | Renderer | Library/Method |
|---|---|---|
| **Data structures (trees, lists, arrays)** | matplotlib + networkx | matplotlib, networkx, graphviz |
| **Graphs (CS)** | networkx | networkx, matplotlib |
| **Neural networks, ML diagrams** | matplotlib + custom drawing | matplotlib, annotate |
| **Plots/graphs (P-V, T-S, math functions)** | matplotlib | matplotlib |
| **Circuits (RF, digital, analog)** | schemdraw | schemdraw |
| **CPU, ALU, architecture diagrams** | matplotlib + patches OR AI | matplotlib or DALL-E |
| **Statics/mechanics (FBD, truss, beam)** | matplotlib + annotations | matplotlib |
| **Physics diagrams (optics, fields)** | matplotlib OR AI | matplotlib or DALL-E |
| **Simple geometry, cross-sections** | SVG direct OR matplotlib | cairosvg or matplotlib |
| **Block diagrams, flowcharts** | matplotlib OR Mermaid | matplotlib or mermaid-cli |
| **Complex/artistic visualizations** | AI image generation | DALL-E 3, GPT-4o |

---

## Implementation Plan

### Phase 1: Core Multi-Library Pipeline

#### 1.1 New file: `src/utils/diagram_generator.py`

Create a `DiagramGenerator` class with:

- **`render_matplotlib(code: str) -> bytes`**: Writes code to a temp file, executes via `subprocess.run()` with:
  - 10-second timeout
  - Memory limit (256MB via ulimit)
  - Restricted imports whitelist (matplotlib, numpy, schemdraw, networkx, graphviz only)
  - Static analysis stripping of dangerous calls (`os`, `subprocess`, `open`, `exec`, `eval`)
  - Captures the saved PNG output

- **`render_schemdraw(code: str) -> bytes`**: Similar to matplotlib but specifically for circuit diagrams

- **`render_networkx(code: str) -> bytes`**: For graph/tree data structures using networkx layout algorithms

- **`render_ai_image(prompt: str, model: str = "dall-e-3") -> bytes`**:
  - Calls OpenAI DALL-E 3 or GPT-4o image generation
  - Downloads the generated image
  - Validates and resizes if needed
  - Use for: complex visualizations, realistic renders, concepts difficult to code

- **`render_svg(svg_markup: str) -> bytes`**: Validates SVG XML, converts to PNG via `cairosvg`

- **`upload_to_s3(image_bytes, assignment_id, question_index) -> dict`**: Uploads PNG to existing S3 path pattern, returns `{ file_id, filename, s3_key, s3_url, content_type, size }` matching the existing frontend contract exactly

- **`generate_diagrams_batch(specs, assignment_id) -> list[dict]`**: Processes all diagrams in parallel via `asyncio.gather` (concurrency limit: 5)

#### 1.2 Modify: `src/utils/assignment_generator.py`

**Add diagram_spec to the LLM prompt** (in `_create_generation_prompt()`):

Instruct GPT-5 to include a `diagram_spec` field per question:
```json
{
  "needs_diagram": true,
  "diagram_type": "matplotlib_networkx",  // or "schemdraw", "ai_image", "svg"
  "description": "Binary search tree with nodes 50, 30, 70, 20, 40, 60, 80 showing search path",
  "code": "import matplotlib.pyplot as plt\nimport networkx as nx\n...\nplt.savefig('output.png', dpi=150, bbox_inches='tight')",
  "ai_prompt": "If diagram_type is 'ai_image', this field contains the detailed prompt for DALL-E"
}
```

**Include comprehensive few-shot examples** in the prompt for:

**Computer Science:**
- Binary tree traversal diagram (networkx)
- Linked list with pointers (matplotlib custom)
- Graph with weighted edges (networkx)
- Neural network with layers (matplotlib)
- Backpropagation flow diagram (matplotlib arrows)
- Stack/queue operations (matplotlib)

**Hardware/Electronics:**
- CPU block diagram showing ALU, registers, control unit (matplotlib patches OR AI)
- ALU circuit with logic gates (schemdraw)
- RF amplifier circuit (schemdraw)
- Digital logic circuit (schemdraw)

**Physics/Engineering:**
- U-tube manometer diagram (matplotlib)
- Circuit with resistors and capacitors (schemdraw)
- Free body diagram with force vectors (matplotlib)
- Ray diagram for lenses (matplotlib)

**Mathematical:**
- Function plot with annotations (matplotlib)
- Vector field visualization (matplotlib)

**Decision rules for the LLM:**
- Data structures (trees, graphs, lists, arrays) → **ALWAYS** generate diagram (use networkx + matplotlib)
- Neural networks, ML architectures → **ALWAYS** generate diagram (use matplotlib custom)
- Computer architecture (CPU, ALU, cache) → Generate diagram (use matplotlib OR ai_image for complex)
- Circuits (any type) → **ALWAYS** generate diagram (use schemdraw)
- Spatial/structural arrangements → **ALWAYS** generate diagram
- Mathematical plots → Generate diagram when helpful (use matplotlib)
- Pure calculation/formula → usually NO diagram
- Questions saying "as shown" or "in the diagram" → **MUST** have diagram
- Complex visualizations that are difficult to code → Use ai_image

**Add new pipeline step** `_generate_diagrams()` between `_generate_questions()` and `_post_process_questions()`:
1. Extract `diagram_spec` from each question
2. Route to appropriate renderer based on `diagram_type`
3. Pass specs to `DiagramGenerator.generate_diagrams_batch()`
4. Attach resulting S3 diagram data to questions
5. Strip `diagram_spec` from final output (internal field only)

**Modified flow:**
```
generate_assignment()
  → _extract_content_sources()
  → _generate_questions()         # GPT-5 now outputs diagram_spec per question
  → _generate_diagrams()          # NEW: route → render code/AI → PNG → S3
  → _post_process_questions()     # existing, links diagram data
```

#### 1.3 Modify: `src/utils/assignment_schemas.py`

Add `diagram_spec` as an optional field to the **generation-time** JSON schema (used in the GPT-5 structured output call). This field is NOT part of the persisted/storage schema — it's stripped before saving.

```python
diagram_spec: Optional[Dict] = {
    "needs_diagram": bool,
    "diagram_type": str,  # "matplotlib", "matplotlib_networkx", "schemdraw", "ai_image", "svg"
    "description": str,
    "code": Optional[str],  # Required for code-based rendering
    "ai_prompt": Optional[str]  # Required for AI image generation
}
```

No changes to the existing `diagram` field schema — it's reused as-is.

#### 1.4 Modify: `src/routes/assignments.py`

- Pass `generateDiagrams` option from `generation_options` to the generator
- The `generate` endpoint already creates the assignment record with an ID before generation — use this ID for the S3 path

#### 1.5 Frontend: `Aiassignmentgeneratorwizard.jsx`

- **Step 2**: Add a checkbox toggle "Auto-generate diagrams for questions" (default: **ON**)
- **Step 4**: Update loading text to "Generating questions and diagrams..."
- **Step 4 preview**: Add a small badge indicator for questions that received diagrams

**No changes needed to:**
- `AssignmentPreview.jsx` — already renders `question.diagram`
- `DoAssignmentModal.jsx` — already has `DiagramImage` component
- `QuestionCard.jsx` — already shows diagrams and allows upload/delete
- `assignmentApi.js` — `generateAssignment()` sends to the same endpoint

#### 1.6 Error handling & fallback chain
```
Code-based (matplotlib/schemdraw/networkx)
    ↓ (if code execution fails)
AI image generation (DALL-E 3)
    ↓ (if AI fails or not suitable)
SVG fallback
    ↓ (if all fail)
Skip diagram, log error, continue with text-only question
```

Specific handling:
- If matplotlib/networkx code fails → retry once with modified code, then fall back to AI generation
- If schemdraw fails → try SVG circuit representation, then AI generation
- If AI image generation fails → try simpler AI prompt, then skip diagram
- Never block entire assignment generation on a single diagram failure
- S3 upload: retry 3x with exponential backoff

#### 1.7 New dependencies
- `schemdraw` — circuit schematic rendering (`pip install schemdraw`)
- `networkx` — graph/tree data structures (`pip install networkx`)
- `pygraphviz` (optional) — advanced graph layouts (`pip install pygraphviz`)
- `cairosvg` — SVG to PNG conversion (`pip install cairosvg`, requires system `cairo` lib)
- OpenAI API for DALL-E 3 (already integrated)

---

### Phase 2: Enhanced Routing + Regeneration

- Improve diagram type auto-detection based on question content
- Add intelligent routing: analyze question content to choose best rendering method
- New endpoint: `POST /api/assignments/{id}/regenerate-diagram` — takes `question_index` + optional `feedback` string + optional `preferred_method`, re-prompts for a corrected diagram
- Add "Regenerate Diagram" button in `QuestionCard.jsx` with method selection dropdown
- Add "Switch to AI generation" option if code-based rendering produces poor results
- Test across all domains: CS data structures, neural networks, CPU architecture, RF circuits, physics diagrams

### Phase 3: Advanced Visualizations + Polish

- Add `render_mermaid(code: str) -> bytes` using `mermaid-cli` (`mmdc`) for flowcharts
- Add 3D visualization support using matplotlib 3D axes
- Support animated diagrams (GIF) for algorithm visualizations
- Diagram generation progress indicators in wizard (show which diagrams are being generated)
- Batch optimization: group similar diagram types together
- Comprehensive cross-discipline testing (CS, EE, Physics, Math)
- Quality metrics: track diagram generation success rate by type
- User feedback collection: allow users to rate diagram quality

---

## Performance Impact

| Step | Time Added | Cost |
|------|-----------|------|
| LLM outputs diagram_spec inline | +0s (same API call, ~200-500 extra tokens per diagram) | ~$0.001 per diagram |
| Render 4 code-based diagrams in parallel | ~3-5s | $0 |
| AI image generation (if used, 1-2 diagrams) | ~10-15s | ~$0.04-0.08 per image (DALL-E 3) |
| S3 upload (parallel) | ~0.5s | Negligible |
| **Total additional (code-based only)** | **~4-5s on top of existing ~15-30s generation** | **~$0.004 per diagram** |
| **Total additional (with AI images)** | **~15-20s if using AI for some diagrams** | **~$0.02-0.04 per diagram** |

**Cost optimization:**
- Prefer code-based rendering (matplotlib/schemdraw/networkx) whenever possible — nearly free
- Use AI generation selectively for complex visualizations that are hard to code
- Cache common diagram patterns to avoid regeneration

## Files to Modify/Create

| File | Action |
|------|--------|
| `[backend] src/utils/diagram_generator.py` | **CREATE** — DiagramGenerator class with multi-method support |
| `[backend] src/utils/assignment_generator.py` | MODIFY — add comprehensive diagram_spec to prompt, add `_generate_diagrams()` with routing |
| `[backend] src/utils/assignment_schemas.py` | MODIFY — add diagram_spec to generation-time schema |
| `[backend] src/routes/assignments.py` | MODIFY — pass generateDiagrams option, add regeneration endpoint |
| `[frontend] src/components/Assignments/Aiassignmentgeneratorwizard.jsx` | MODIFY — add toggle + progress text + badge |

## Verification & Testing

### Computer Science Tests
1. Generate a data structures assignment (binary trees, linked lists, graphs) — verify diagrams show correct topology with labeled nodes
2. Generate a machine learning assignment (neural networks, backpropagation) — verify layer diagrams are clear and labeled
3. Generate an algorithms assignment (sorting, searching) — verify visualizations show steps correctly

### Hardware/Electronics Tests
4. Generate a computer architecture assignment (CPU, ALU, cache) — verify block diagrams are clear
5. Generate an RF circuits assignment — verify schemdraw renders amplifiers, filters correctly
6. Generate a digital logic assignment — verify logic gates and flip-flops render properly

### Physics/Engineering Tests
7. Generate a mechanics assignment (FBD, trusses) — verify force vectors and structures are labeled
8. Generate a thermodynamics assignment (P-V, T-S diagrams) — verify plots are accurate
9. Generate an optics assignment (ray diagrams) — verify lens systems render correctly

### General Tests
10. Toggle off "Auto-generate diagrams" — verify no diagrams are generated
11. Verify diagrams display correctly in AssignmentPreview, DoAssignmentModal, and exported PDF
12. Test error case: provide intentionally broken diagram code — verify fallback to AI generation works
13. Test AI generation: provide a complex visualization requirement — verify DALL-E generates appropriate image
14. Check S3 storage: diagrams are at the correct path and presigned URLs resolve
15. Performance test: generate assignment with 10 mixed diagram types — verify parallel processing completes in reasonable time

## Future Enhancements

- **Interactive diagrams**: SVG with clickable elements for web view
- **Diagram editing**: Allow users to modify generated diagrams via simple UI
- **Diagram templates**: Pre-built templates for common patterns (binary tree, circuit types)
- **Multi-language support**: Generate diagrams with labels in different languages
- **Accessibility**: Add alt-text generation for all diagrams
- **Version control**: Track diagram regeneration history
- **A/B testing**: Compare user comprehension with vs without diagrams
