# Plan: AI-Generated Diagrams for Assignment Questions

## Problem
Currently, the assignment generator produces text-only questions. For engineering topics (manometers, circuits, FBDs, trusses, etc.), students need visual diagrams to comprehend spatial/structural problems. The attached `assignment2.pdf` demonstrates this — 10 manometer questions are described entirely in text when a simple labeled U-tube diagram would dramatically improve understanding.

## Current Architecture (Relevant)
- **`assignment_generator.py`**: GPT-5 generates questions as structured JSON via `_generate_questions()` → `_post_process_questions()`
- **Question schema**: Already has `hasDiagram: bool` and `diagram: { s3_key, s3_url, file_id, ... }` fields (used for PDF *import*, not generation)
- **S3 storage**: Diagrams already stored at `assignments/{id}/diagrams/{file_id}.png` with presigned URL support
- **Frontend**: `DiagramImage`/`DiagramPreviewImage` components already render diagrams from S3 for all question types — zero frontend rendering changes needed

## Recommended Approach: Hybrid Code-Based Generation

Use the LLM to generate **rendering code** (matplotlib/schemdraw) alongside questions, execute it in a sandboxed subprocess, upload the resulting PNG to S3, and attach it using the existing `diagram` field.

### Why this approach over alternatives
| Option | Verdict | Reason |
|--------|---------|--------|
| **matplotlib/schemdraw code gen** | **Primary** | Precise labels, exact dimensions, deterministic, cheap, fast |
| SVG markup | Fallback | LLMs struggle with complex SVG geometry; fine for simple shapes |
| AI image gen (DALL-E/GPT-4o) | Rejected | Imprecise labels, wrong topology for technical diagrams, expensive, slow |
| Mermaid/PlantUML | Phase 3 | Good for flowcharts only; can't draw manometers, circuits, FBDs |

### Model choice for code generation
The LLM that generates the matplotlib/schemdraw rendering code does NOT need to be GPT-5. Any strong code-generation model works since the output is Python code, not prose. Options:
- **Claude Sonnet/Opus** — excellent at generating correct matplotlib code
- **GPT-5 / GPT-4o** — already integrated in the codebase
- **Open-source (Codestral, DeepSeek)** — if cost is a concern

Recommendation: Use whichever model already powers question generation (currently GPT-5) to keep the pipeline simple — the diagram_spec is generated in the same API call as the questions. If diagram code quality is poor, a separate "diagram code refinement" call to Claude or GPT-4o can be added as a quick fix.

### Diagram type routing
| Engineering Domain | Renderer | Library |
|---|---|---|
| Fluid mechanics (manometers, pipes, vessels) | matplotlib + patches | matplotlib |
| Plots/graphs (P-V, T-S, stress-strain) | matplotlib | matplotlib |
| Circuits (Norton, Thevenin, RLC) | schemdraw | schemdraw |
| Statics/mechanics (FBD, truss, beam) | matplotlib + annotations | matplotlib |
| Simple geometry, cross-sections | SVG direct | cairosvg |
| Block diagrams, flowcharts | Mermaid (Phase 3) | mermaid-cli |

---

## Implementation Plan

### Phase 1: Core Pipeline (matplotlib)

#### 1.1 New file: `src/utils/diagram_generator.py`

Create a `DiagramGenerator` class with:

- **`render_matplotlib(code: str) -> bytes`**: Writes code to a temp file, executes via `subprocess.run()` with:
  - 10-second timeout
  - Memory limit (256MB via ulimit)
  - Restricted imports whitelist (matplotlib, numpy, schemdraw only)
  - Static analysis stripping of dangerous calls (`os`, `subprocess`, `open`, `exec`, `eval`)
  - Captures the saved PNG output
- **`render_svg(svg_markup: str) -> bytes`**: Validates SVG XML, converts to PNG via `cairosvg`
- **`upload_to_s3(image_bytes, assignment_id, question_index) -> dict`**: Uploads PNG to existing S3 path pattern, returns `{ file_id, filename, s3_key, s3_url, content_type, size }` matching the existing frontend contract exactly
- **`generate_diagrams_batch(specs, assignment_id) -> list[dict]`**: Processes all diagrams in parallel via `asyncio.gather` (concurrency limit: 5)

#### 1.2 Modify: `src/utils/assignment_generator.py`

**Add diagram_spec to the LLM prompt** (in `_create_generation_prompt()`):

Instruct GPT-5 to include a `diagram_spec` field per question:
```json
{
  "needs_diagram": true,
  "diagram_type": "matplotlib",
  "description": "U-tube manometer with mercury, water (left), oil (right), labeled heights",
  "code": "import matplotlib.pyplot as plt\nimport matplotlib.patches as patches\n...\nplt.savefig('output.png', dpi=150, bbox_inches='tight')"
}
```

Include few-shot examples in the prompt for:
- U-tube manometer diagram
- Simple circuit (using schemdraw)
- Free body diagram with force vectors
- P-V thermodynamic plot

**Decision rules for the LLM:**
- Spatial/structural arrangements → ALWAYS generate diagram
- Circuit problems → ALWAYS generate diagram (use schemdraw)
- Pure calculation/formula → usually NO diagram
- Questions saying "as shown" → MUST have diagram

**Add new pipeline step** `_generate_diagrams()` between `_generate_questions()` and `_post_process_questions()`:
1. Extract `diagram_spec` from each question
2. Pass specs to `DiagramGenerator.generate_diagrams_batch()`
3. Attach resulting S3 diagram data to questions
4. Strip `diagram_spec` from final output (internal field only)

**Modified flow:**
```
generate_assignment()
  → _extract_content_sources()
  → _generate_questions()         # GPT-5 now outputs diagram_spec per question
  → _generate_diagrams()          # NEW: render code → PNG → S3
  → _post_process_questions()     # existing, links diagram data
```

#### 1.3 Modify: `src/utils/assignment_schemas.py`

Add `diagram_spec` as an optional field to the **generation-time** JSON schema (used in the GPT-5 structured output call). This field is NOT part of the persisted/storage schema — it's stripped before saving.

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

#### 1.6 Error handling
- If matplotlib code fails → retry once by re-prompting LLM to generate SVG fallback
- If SVG also fails → skip diagram, set `hasDiagram: false`, log error
- Never block entire assignment generation on a single diagram failure
- S3 upload: retry 3x with exponential backoff

#### 1.7 New dependencies
- `schemdraw` — circuit schematic rendering (`pip install schemdraw`)
- `cairosvg` — SVG to PNG conversion (`pip install cairosvg`, requires system `cairo` lib)

---

### Phase 2: Circuits + Regeneration Endpoint

- Add `render_schemdraw(code: str) -> bytes` to `DiagramGenerator`
- New endpoint: `POST /api/assignments/{id}/regenerate-diagram` — takes `question_index` + optional `feedback` string, re-prompts GPT-5 for a corrected diagram
- Add "Regenerate Diagram" button in `QuestionCard.jsx` for AI-generated diagrams
- Test with electrical engineering circuit problems

### Phase 3: Mermaid + Polish

- Add `render_mermaid(code: str) -> bytes` using `mermaid-cli` (`mmdc`)
- Diagram generation progress indicators in wizard
- Comprehensive cross-discipline testing

---

## Performance Impact

| Step | Time Added |
|------|-----------|
| LLM outputs diagram_spec inline | +0s (same API call, ~200-400 extra tokens per diagram) |
| Render 4 diagrams in parallel | ~3-4s |
| S3 upload (parallel) | ~0.5s |
| **Total additional** | **~4s on top of existing ~15-30s generation** |

## Files to Modify/Create

| File | Action |
|------|--------|
| `[backend] src/utils/diagram_generator.py` | **CREATE** — DiagramGenerator class |
| `[backend] src/utils/assignment_generator.py` | MODIFY — add diagram_spec to prompt, add `_generate_diagrams()` step |
| `[backend] src/utils/assignment_schemas.py` | MODIFY — add diagram_spec to generation-time schema |
| `[backend] src/routes/assignments.py` | MODIFY — pass generateDiagrams option |
| `[frontend] src/components/Assignments/Aiassignmentgeneratorwizard.jsx` | MODIFY — add toggle + progress text + badge |

## Verification
1. Generate a mechanical engineering assignment about manometers — verify ~3-4 questions get diagrams with labeled U-tube drawings
2. Generate an electrical engineering assignment about Thevenin/Norton — verify circuit diagrams render correctly with schemdraw
3. Toggle off "Auto-generate diagrams" — verify no diagrams are generated
4. Verify diagrams display correctly in AssignmentPreview, DoAssignmentModal, and exported PDF
5. Test error case: intentionally provide a topic unlikely to need diagrams (e.g., essay questions) — verify no unnecessary diagrams are generated
6. Check S3 storage: diagrams are at the correct path and presigned URLs resolve
