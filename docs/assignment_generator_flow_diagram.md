# Vidya AI — Assignment Generator Flow

> End-to-end pipeline from HTTP request to stored assignment.

---

## Overview

The assignment generation system is a **multi-stage, multi-agent orchestration pipeline**.
A single HTTP request triggers four sequential stages, with the diagram generation stage being a full multi-agent sub-system of its own.

---

## Pipeline Diagram

See `assignment_generator_flow_diagram.pdf` in this folder for the full block diagram.

---

## Stage-by-Stage Breakdown

### Entry Point

| Component | File | Description |
|-----------|------|-------------|
| HTTP API Route | `src/routes/assignments.py` | `POST /api/assignments/generate` — accepts `AssignmentGenerateRequest`, creates a DB placeholder, then delegates to `AssignmentGenerator`. A streaming variant (`/generate-stream`) emits SSE log events in real time. |

---

### Stage 1 · Content Extraction

| Component | File | Description |
|-----------|------|-------------|
| DocumentProcessor | `src/utils/assignment_generator.py` | Extracts text from uploaded PDFs, DOCX files, and YouTube video transcripts. Produces the `content_context` string fed into all downstream agents. |

---

### Stage 2 · Question Generation Agent

| Component | Model | Description |
|-----------|-------|-------------|
| Question Generation Agent | GPT-4o | Receives the content context + generation options and produces structured questions via Pydantic-typed output (`AssignmentGenerationResponseFlat` / `AssignmentGenerationResponseNested`). |
| **Equation Extractor** *(side process)* | GPT-4o | A second GPT-4o call that identifies all LaTeX equations in the generated questions, replaces them with placeholder IDs (`<eq q1_eq1>`), and returns an `equations` array for proper rendering. |

**Inputs:** `content_context`, `generation_options` (question types, difficulty, points, discipline)
**Outputs:** Structured question list with optional diagram hints

---

### Stage 3 · Diagram Analysis Agent *(Multi-Agent System)*

This is the most complex stage. For every question the agent:

#### 3a — Domain Router
| Component | Model | Output |
|-----------|-------|--------|
| Domain Router | GPT-4o-mini | Classifies the question into `domain` / `diagram_type` / `complexity` / `ai_suitable` / `preferred_tool` |

#### 3b — Subject Prompt Registry
Injects domain-specific guidance into every downstream component:
- Agent system prompt additions
- Imagen-style descriptions for AI generation
- Non-AI tool prompts for code generation
- Reviewer style hints

#### 3c — Tool Selection Agent
| Component | Model | Description |
|-----------|-------|-------------|
| Tool Selection Agent | GPT-4o | Decides *whether* a diagram adds educational value and *which* tool to call (`tool_choice=auto`). Falls back to the **Fallback Router** for domain→tool mapping when the LLM is uncertain. |

#### 3d — Rendering Engine

Three rendering paths, selected by the diagram engine setting (`ai` / `nonai` / `both`):

| Tool | Engine | Description |
|------|--------|-------------|
| **Circuitikz Tool** | nonai | Generates LaTeX source, compiles to PNG via `pdflatex`. Best for electrical circuits. |
| **Claude Code Tool** | nonai | Calls Claude API to write Matplotlib or NetworkX code, then executes it locally. |
| **Gemini Image Gen** | ai | Sends a structured description to Gemini 2.5 Flash / Pro image model. Used when `engine=ai`. |

When `engine=both`, both AI and nonai paths run and their outputs are stitched vertically.

All code-based tools route through the **Diagram Executor** (`DiagramGenerator`) which runs the generated code, encodes the output as PNG, and hands it to the reviewer.

#### 3e — Gemini Diagram Reviewer
| Component | Model | Description |
|-----------|-------|-------------|
| Gemini Diagram Reviewer | Gemini 2.5 Pro Vision | Validates the rendered diagram for technical accuracy, label correctness, completeness, and answer-hiding compliance. Returns `{valid, reason, fixable, corrected_description}`. Failed diagrams enter a **retry loop (max 3 attempts)**. |

#### 3f — S3 Upload
Accepted diagrams are uploaded to `s3://vidya-diagrams/<assignment_id>/` and the S3 URL is attached to the question.

---

### Stage 4 · Question Review Agent

| Component | Model | Description |
|-----------|-------|-------------|
| Question Review Agent | GPT-4o | Reviews all generated questions against the original lecture notes. Scores each on `alignment` (0–10) and `quality` (0–10). Questions below threshold are filtered out. |

---

### Storage

| Component | Description |
|-----------|-------------|
| AWS S3 | Stores all generated diagram images |
| Database | Stores the final `Assignment` object with questions, diagrams, metadata |

---

## Agent Summary Table

| Agent | Model | Role |
|-------|-------|------|
| Question Generation Agent | GPT-4o | Generate structured questions from lecture content |
| Equation Extractor | GPT-4o | Extract and ID LaTeX equations |
| Domain Router | GPT-4o-mini | Classify question domain and diagram type |
| Tool Selection Agent | GPT-4o | Decide diagram tool with `tool_choice=auto` |
| Fallback Router | Rule-based | Map (domain, diagram_type) → rendering tool |
| Subject Prompt Registry | Rule-based | Inject per-subject guidance into all agents |
| Circuitikz Tool | LaTeX / pdflatex | Render electrical circuit diagrams |
| Claude Code Tool | Claude API + Python | Generate and execute Matplotlib / NetworkX code |
| Gemini Image Gen | Gemini 2.5 Flash/Pro | AI-generated diagram images |
| Diagram Executor | Python runtime | Execute rendering code, encode PNG |
| Gemini Diagram Reviewer | Gemini 2.5 Pro Vision | Validate diagram quality and technical accuracy |
| Question Review Agent | GPT-4o | Final quality gate — filter low-quality questions |

---

## Key Files

| File | Purpose |
|------|---------|
| `src/routes/assignments.py` | HTTP entry point, SSE streaming |
| `src/utils/assignment_generator.py` | Main orchestrator (Stages 1–4) |
| `src/utils/diagram_agent.py` | Diagram multi-agent system |
| `src/utils/domain_router.py` | GPT-4o-mini domain classifier |
| `src/utils/subject_prompt_registry.py` | Per-subject guidance registry |
| `src/utils/fallback_router.py` | Domain → tool routing rules |
| `src/utils/diagram_tools.py` | Tool executor wrappers |
| `src/utils/diagram_generator.py` | Code execution + S3 upload |
| `src/utils/gemini_diagram_reviewer.py` | Vision-based diagram validator |
| `src/utils/question_review_agent.py` | Final question quality reviewer |
| `src/utils/assignment_schemas.py` | Pydantic models for structured output |

---

*Vidya AI Backend · Assignment Generation Pipeline · 2026*
