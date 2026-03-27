# Assignment Generator — Technical Documentation

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [API Endpoint](#api-endpoint)
4. [Request Schema](#request-schema)
5. [Generation Pipeline](#generation-pipeline)
   - [Step 1: Content Extraction](#step-1-content-extraction)
   - [Step 2: Question Generation](#step-2-question-generation)
   - [Step 3: Equation Extraction](#step-3-equation-extraction)
   - [Step 4: Diagram Generation (Multi-Agent)](#step-4-diagram-generation-multi-agent)
   - [Step 5: Question Review & Quality Control](#step-5-question-review--quality-control)
   - [Step 6: Post-Processing & Sanitization](#step-6-post-processing--sanitization)
6. [Subject / Domain Routing](#subject--domain-routing)
7. [Question Types](#question-types)
8. [Question Structure (Schemas)](#question-structure-schemas)
9. [Difficulty & Scoring](#difficulty--scoring)
10. [Multi-Part Questions](#multi-part-questions)
11. [Diagram Generation](#diagram-generation)
12. [Document Processing](#document-processing)
13. [Prompt Design](#prompt-design)
14. [Error Handling & Degradation](#error-handling--degradation)
15. [SSE Streaming Endpoint](#sse-streaming-endpoint)
16. [Configuration Reference](#configuration-reference)

---

## Overview

The Assignment Generator is a multi-stage AI pipeline that produces complete educational assignments — including questions, answer keys, rubrics, diagrams, and LaTeX equations — from a variety of content sources. It is implemented in `src/utils/assignment_generator.py` and exposed via the `/api/assignments/generate` and `/api/assignments/generate-stream` FastAPI endpoints defined in `src/routes/assignments.py`.

Key capabilities:

- Generates questions from **YouTube video transcripts**, **uploaded documents** (PDF, DOCX, MD, HTML, CSV, JSON), and/or a **free-text custom prompt**.
- Supports **three subject domains**: engineering (discipline-specific), medical/clinical, and general academic.
- Produces **nine question types**, including multi-part nested questions (up to 3 levels deep).
- Automatically detects and formats **LaTeX equations** in a separate post-generation AI call.
- Optionally generates **PNG diagrams** (circuits, graphs, physiology curves, etc.) via a multi-agent diagram system and uploads them to S3.
- Runs a **quality-review agent** to filter hallucinated or off-topic questions when source material is provided.
- Exposes a **Server-Sent Events (SSE) stream** so the frontend can display live progress logs during generation.

---

## Architecture

```
POST /api/assignments/generate
         │
         ▼
  FastAPI route handler
  (src/routes/assignments.py)
         │
         │ creates placeholder Assignment row in DB (gets an ID for S3 uploads)
         │
         ▼
  AssignmentGenerator.generate_assignment()
  (src/utils/assignment_generator.py)
         │
         ├─► _extract_content_sources()      ← videos, documents, custom prompt
         │
         ├─► _generate_questions()           ← GPT-4o structured output (Responses API)
         │        │
         │        ├─► _create_generation_prompt()   ← domain-aware prompt builder
         │        ├─► _get_system_prompt()          ← domain-aware system prompt
         │        └─► _extract_equations_from_questions()  ← separate GPT-4o call
         │
         ├─► DiagramAnalysisAgent.analyze_and_generate_diagrams()
         │   (src/utils/diagram_agent.py)
         │        │
         │        ├─► DomainRouter             ← classifies question domain
         │        ├─► SubjectPromptRegistry    ← subject-specific diagram prompts
         │        ├─► DiagramTools             ← renders diagrams (CircuiTikZ / matplotlib / Claude Code)
         │        └─► GeminiDiagramReviewer    ← semantic accuracy check (Gemini 2.5 Pro)
         │
         ├─► QuestionReviewAgent.review_questions()
         │   (src/utils/question_review_agent.py)
         │
         ├─► _cleanup_diagram_metadata()
         ├─► _sanitize_questions()
         └─► _post_process_questions()
         │
         ▼
  Assignment saved to DB → returned as AssignmentOut
```

**AI Models Used**

| Stage                    | Model               | API                    |
|--------------------------|---------------------|------------------------|
| Question generation      | `gpt-4o`            | OpenAI Responses API   |
| Equation extraction      | `gpt-4o`            | OpenAI Chat Completions|
| Diagram decision-making  | `gpt-4o`            | OpenAI (tool calls)    |
| Diagram rendering (nonai)| CircuiTikZ / matplotlib / Claude Code | Various |
| Diagram review           | `gemini-2.5-pro`    | Google AI              |
| Question quality review  | `gpt-4o`            | OpenAI Chat Completions|
| PDF extraction           | `gpt-4o` (vision)   | OpenAI Chat Completions|

---

## API Endpoint

### `POST /api/assignments/generate`

Synchronous. Generates an assignment and returns the completed `AssignmentOut` object. The HTTP request blocks until all AI steps (question generation, diagram generation, review) are complete.

**Authentication**: Firebase ID token required (Bearer token in `Authorization` header).

**Response**: `AssignmentOut` — the fully populated assignment database record.

### `POST /api/assignments/generate-stream`

Streaming. Returns a `text/event-stream` (SSE) response. The frontend receives real-time log events as the pipeline progresses, followed by a final `complete` event containing the full assignment JSON. Useful for showing a progress indicator in the UI.

**Event types streamed**:

| Event type  | Payload                                   |
|-------------|-------------------------------------------|
| `log`       | `{ level, message }` — backend log lines |
| `complete`  | `{ assignment }` — final assignment data  |
| `error`     | `{ message }` — error description        |

---

## Request Schema

Defined in `src/schemas.py` as `AssignmentGenerateRequest`.

```python
class AssignmentGenerateRequest(BaseModel):
    linked_videos: Optional[List[dict]] = None   # Video objects with transcript_text
    uploaded_files: Optional[List[dict]] = None  # Base64-encoded file objects
    generation_prompt: Optional[str] = None      # Free-text topic / instructions
    generation_options: dict                     # See below
    title: Optional[str] = None                  # Override auto-generated title
    description: Optional[str] = None            # Override auto-generated description
```

### `generation_options` Dictionary

| Field                  | Type      | Default         | Description |
|------------------------|-----------|-----------------|-------------|
| `numQuestions`         | `int`     | `5`             | Total number of top-level questions to generate |
| `subjectCategory`      | `str`     | `"engineering"` | `"engineering"`, `"medical"`, or `""` (general) |
| `engineeringLevel`     | `str`     | `""`            | Academic level key (see [Levels](#subject--domain-routing)) |
| `engineeringDiscipline`| `str`     | `""`            | Discipline string (e.g. `"electrical"`, `"cardiology"`) |
| `questionTypes`        | `dict`    | `{}`            | Map of question type → `bool` (see [Question Types](#question-types)) |
| `difficultyLevel`      | `str`     | `"mixed"`       | `"easy"`, `"medium"`, `"hard"`, or `"mixed"` |
| `totalPoints`          | `int`     | `50`            | Total assignment point value |
| `perQuestionDifficulty`| `bool`    | `false`         | If `true`, use `difficultyDistribution` instead of `difficultyLevel` |
| `difficultyDistribution`| `dict`  | `{}`            | Per-difficulty question counts and point values |
| `diagramEngine`        | `str`     | `"nonai"`       | `"ai"` / `"nonai"` / `"both"` |
| `diagramModel`         | `str`     | `"flash"`       | `"flash"` (gemini-2.5-flash) or `"pro"` (gemini-3-pro) |

---

## Generation Pipeline

### Step 1: Content Extraction

**Method**: `_extract_content_sources()`

Aggregates content from all three possible sources into a unified `content_sources` dict:

```python
{
    "video_transcripts": [{ "title", "transcript", "youtube_id" }],
    "document_texts":    [{ "name", "content", "type" }],
    "custom_prompt":     str | None
}
```

**Video transcripts**: The `transcript_text` field from each linked video object is taken as-is (pre-processed by the YouTube pipeline).

**Uploaded documents**: Each file's `content` (base64) is decoded and parsed by `DocumentProcessor` (see [Document Processing](#document-processing)). On failure the error is propagated — no partial content is silently swallowed.

**Priority logic**: When a custom prompt is provided *without* any video/document content, it is treated as the *primary* and *exclusive* instruction. The AI is told to generate questions **only** on that specific topic. When source material is also present, the custom prompt supplements the content context.

---

### Step 2: Question Generation

**Method**: `_generate_questions()`

This is the core AI generation step. It uses OpenAI's **Responses API** (`client.responses.parse`) with **structured output** to guarantee the response matches a Pydantic schema.

**Schema selection** (`create_dynamic_generation_response()`):
- If `multi-part` is in the enabled types → `AssignmentGenerationResponseNested` (supports 3-level hierarchy)
- Otherwise → `AssignmentGenerationResponseFlat` (flat questions only)

Both schemas **exclude** the `equations` field to reduce token usage; equations are extracted in a separate step.

**Content context assembly** (`_prepare_content_context()`):
The content is assembled in this order:
1. `## PRIMARY TOPIC INSTRUCTIONS` — the user's custom prompt (if any)
2. `## Supporting Video Content` — video transcripts
3. `## Supporting Document Content` — parsed file text

**Prompt routing** (`_create_generation_prompt()`):
The user prompt is constructed based on three branches:

| Condition | Branch |
|---|---|
| `subjectCategory == "medical"` | Medical-specific prompt with clinical case guidelines |
| `engineeringDiscipline` is set | Engineering-specific prompt with code/circuit guidelines |
| Neither | General academic prompt |

Each branch further bifurcates based on whether a custom prompt is the sole input or content sources are present.

**System prompt routing** (`_get_system_prompt()`):
Matches the same three branches above, providing domain-expert persona and **self-contained question rules** (critical for questions that reference diagrams that don't yet exist).

---

### Step 3: Equation Extraction

**Method**: `_extract_equations_from_questions()`

A second GPT-4o call processes *all* generated questions in a single batched request. It:

1. Identifies all mathematical expressions (LaTeX formulas, Greek letters, integrals, etc.)
2. Produces a unique equation ID per equation (`q1_eq1`, `q1_1_eq1`, etc.)
3. Inserts placeholder tags into question text: `<eq q1_eq1>`
4. Returns equation metadata with the character index and context (`question_text`, `options`, `correctAnswer`, `rubric`)

The frontend uses these placeholders and metadata to render equations via a LaTeX renderer.

**Graceful degradation**: If this step fails, the original questions (without equation metadata) are returned unmodified. Assignment generation is not aborted.

---

### Step 4: Diagram Generation (Multi-Agent)

**Class**: `DiagramAnalysisAgent` (`src/utils/diagram_agent.py`)

This step is skipped if no `assignment_id` is available (since diagrams must be stored in S3 under the assignment's namespace).

The diagram agent is an OpenAI **tool-calling agent** that processes all questions and decides, for each one, whether a diagram would add educational value. When it decides "yes", it calls one of several diagram rendering tools:

| Tool | Use Case |
|---|---|
| `circuitikz_tool` | All electrical circuits (CMOS, op-amps, flip-flops, logic gates, RLC networks, datapaths) |
| `claude_code_tool` | Any non-circuit technical diagram (physics, CS, math, biology, medical physiology curves) |
| `matplotlib_tool` | Simple direct matplotlib plots |
| `networkx_tool` | Simple graph/network diagrams |
| `schemdraw_tool` | Avoided — produces unprofessional output |
| `dalle_tool` | Avoided — use code-based tools for technical accuracy |

**Critical diagram rule — answer hiding**: Diagrams must *never* reveal the answer. Timing diagrams show only input signals (CLK, D, A, B); output rows (Q, Q̄) are left blank with `?` labels. Tree diagrams show the tree *before* an operation. Metabolic pathways leave enzyme names blank when those are the answer.

**Domain routing**: `DomainRouter` classifies each question's subject domain (electrical, mechanical, medical, etc.) and `SubjectPromptRegistry` provides subject-specific diagram generation hints. `SubjectSpecificFallbackRouter` handles retry logic when the primary rendering path fails.

**Diagram review**: After rendering, `GeminiDiagramReviewer` (Gemini 2.5 Pro with vision) performs a semantic accuracy check — verifying that labeled values, connections, and structures match what the question text describes. Failed reviews trigger a fallback rendering attempt.

**S3 upload**: Approved diagrams are uploaded to S3 and their `s3_url` / `s3_key` are stored in the question's `diagram` field.

---

### Step 5: Question Review & Quality Control

**Class**: `QuestionReviewAgent` (`src/utils/question_review_agent.py`)

This step only runs when source material (videos or documents) was provided, since it validates questions against that content.

The review agent scores each question on:

| Criterion | Description |
|---|---|
| `alignment_score` (0–10) | How well the question maps to the lecture notes / source material |
| `quality_score` (0–10) | How natural and human-like the question feels |
| `keep` (bool) | Final recommendation: keep or remove |

**Removal rules**:
- Questions covering topics *not in* the lecture notes → `alignment_score = 0`, `keep = false`
- Technically inaccurate questions → `alignment_score ≤ 3`, `keep = false`
- Questions with fixable minor issues → `keep = true` with suggestions logged

Questions flagged as `keep = false` are removed from the final list. The count of filtered questions is logged.

---

### Step 6: Post-Processing & Sanitization

**Methods**: `_sanitize_questions()`, `_post_process_questions()`, `_cleanup_diagram_metadata()`

**Sanitization** (`_sanitize_questions()`): Recursively removes null bytes (`\x00`, `\u0000`) from all string fields in every question and subquestion. PostgreSQL rejects strings containing null bytes.

**Post-processing** (`_post_process_questions()`): Fills in default values for all fields the frontend expects but that were intentionally omitted from the lightweight generation schema (to conserve tokens):

- Sets sequential `id` and `order` fields
- Normalizes `question` ↔ `text` aliases
- Defaults for `allowMultipleCorrect`, `equations`, `hasCode`, `hasDiagram`, `rubricType`, `optionalParts`, etc.
- Converts `true-false` correct answers to Python booleans
- Sets `hasCode = True` / `False` based on whether the `code` field is populated
- Applies the same defaults recursively to Level 2 and Level 3 subquestions

**Diagram metadata cleanup** (`_cleanup_diagram_metadata()`): Removes `hasDiagram` flags and `diagram` objects from questions where the diagram agent decided not to generate a diagram (i.e., `s3_url` is absent). Prevents the frontend from rendering a broken diagram slot.

---

## Subject / Domain Routing

The generator branches its prompts and system instructions based on the `subjectCategory` and `engineeringDiscipline` fields.

### Academic Levels

| Key | Display Name | Domain |
|---|---|---|
| `undergraduate` | Undergraduate | Engineering / General |
| `graduate` | Graduate | Engineering / General |
| `pre_med` | Pre-Med | Medical |
| `mbbs_preclinical` | MBBS Pre-Clinical (Year 1–2) | Medical |
| `mbbs_clinical` | MBBS Clinical (Year 3–5) | Medical |
| `md` | MD / Postgraduate | Medical |

### Domain Personas

| Condition | AI Persona |
|---|---|
| `subjectCategory=medical` | Expert medical educator in the specified clinical discipline |
| `engineeringDiscipline` set | Expert engineering educator in the specified engineering field |
| Neither | General expert educator at the specified level |

### Medical-Specific Prompting

When `subjectCategory = "medical"`, the system prompt and user prompt include:
- **Clinical Case Study guidelines**: patient demographics, presenting complaint, investigations with normal ranges, diagnosis + management + mechanism questions
- **OSCE guidelines**: examiner instructions, structured marking schemes
- Requirement to use correct anatomical, physiological, and pharmacological terminology
- Difficulty calibration per level: Pre-Med (foundational) → MBBS Pre-Clinical (mechanisms) → MBBS Clinical (applied, patient-centred) → MD/PG (advanced, research-level)

### Engineering-Specific Prompting

When `engineeringDiscipline` is set (e.g., `"electrical"`, `"mechanical"`), extra guidelines are added:
- **Self-contained question rules**: every question must state all component values, node labels, and connection topology explicitly — no references to "the diagram above"
- **Code question guidelines**: templates for `code`, `function`, `algorithm`, and `output` output types
- **MCQ indexing**: `correctAnswer` is a 0-based string index (`"0"`, `"1"`, `"2"`, `"3"`)

---

## Question Types

Enabled via the `questionTypes` boolean map in `generation_options`.

| Type key | Level | Description |
|---|---|---|
| `multiple-choice` | Top / Sub | Options array; `correctAnswer` is a 0-based index string; supports `allowMultipleCorrect` |
| `true-false` | Top / Sub | `correctAnswer` is a boolean |
| `short-answer` | Top / Sub | Free-text short response |
| `long-answer` | Top only | Extended free-text response |
| `numerical` | Top / Sub | Numeric answer with units |
| `fill-blank` | Top / Sub | Fill-in-the-blank |
| `code-writing` | Top / Sub | Code template + expected answer; `outputType` in `{code, function, algorithm, output}` |
| `diagram-analysis` | Top / Sub | Question referencing a visual diagram; triggers diagram generation |
| `multi-part` | Top / Level 2 | Parent question containing subquestions (see [Multi-Part Questions](#multi-part-questions)) |

> `multi-part` is **not allowed at Level 3** (deepest nesting level).

---

## Question Structure (Schemas)

### Top-Level Question

Defined in `AssignmentGenerationResponseFlat` / `AssignmentGenerationResponseNested` (Pydantic, `src/utils/assignment_pydantic_models.py`) and mirrored in `base_question_schema` (JSON Schema, `src/utils/assignment_schemas.py`).

| Field | Type | Description |
|---|---|---|
| `id` | `int` | Sequential question number (1-based, set in post-processing) |
| `type` | `str` | Question type key |
| `question` | `str` | Question text (may contain `<eq q1_eq1>` placeholders) |
| `text` | `str` | Alias of `question` (both maintained for frontend compatibility) |
| `points` | `float` | Point value |
| `difficulty` | `str` | `"easy"` / `"medium"` / `"hard"` |
| `order` | `int` | Display order |
| `options` | `List[str]` | MCQ choices |
| `allowMultipleCorrect` | `bool` | Allow multiple correct MCQ answers |
| `multipleCorrectAnswers` | `List[str]` | Indices of correct answers when `allowMultipleCorrect` |
| `correctAnswer` | `str` | Model answer (see type-specific rules above) |
| `rubric` | `str` | Detailed grading rubric |
| `rubricType` | `str` | `"overall"` or `"per-subquestion"` |
| `hasCode` | `bool` | Whether `code` field is populated |
| `code` | `str` | Code template or snippet |
| `codeLanguage` | `str` | Programming language identifier |
| `outputType` | `str` | `"code"` / `"function"` / `"algorithm"` / `"output"` |
| `hasDiagram` | `bool` | Whether an S3 diagram is attached |
| `diagram` | `object` | `{ s3_url, s3_key }` |
| `equations` | `List[Equation]` | LaTeX equations with position metadata |
| `optionalParts` | `bool` | Whether subquestions are OR alternatives |
| `requiredPartsCount` | `int` | Number of subquestions student must answer |
| `subquestions` | `List[SubquestionLevel2]` | Nested sub-questions (multi-part only) |

### Equation Object

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique ID, e.g. `q1_eq1` or `q1_1_eq2` |
| `latex` | `str` | LaTeX source string |
| `position.char_index` | `int` | Character index in the question text after which the equation appears |
| `position.context` | `str` | `"question_text"`, `"options"`, `"correctAnswer"`, or `"rubric"` |
| `type` | `str` | `"inline"` or `"display"` |

---

## Difficulty & Scoring

### Uniform Difficulty

Set `difficultyLevel` to `"easy"`, `"medium"`, `"hard"`, or `"mixed"` (let the AI choose a natural spread). All questions are generated at that level and point values are set proportionally.

### Per-Question Difficulty Distribution

Set `perQuestionDifficulty: true` and provide `difficultyDistribution`:

```json
{
  "perQuestionDifficulty": true,
  "difficultyDistribution": {
    "easy":   { "count": 3, "pointsEach": 5 },
    "medium": { "count": 4, "pointsEach": 10 },
    "hard":   { "count": 3, "pointsEach": 15 }
  },
  "totalPoints": 110
}
```

The prompt explicitly instructs the AI on how many questions of each difficulty to produce and at what point value.

---

## Multi-Part Questions

Multi-part questions form a **3-level hierarchy**:

```
Level 1 (top-level)  — type: "multi-part"
  └─ Level 2 (subquestion)  — type: any, including "multi-part"
       └─ Level 3 (nested subquestion)  — type: any EXCEPT "multi-part"
```

**ID scheme**: Top-level questions have integer IDs. Subquestions have integer IDs within their parent (`1`, `2`, `3`…). Equation IDs follow the pattern `q<parent_id>_<sub_id>_eq<n>`.

**Behavior when `multi-part` is the only enabled type**: All top-level questions must be multi-part; each must contain subquestions.

**Behavior when `multi-part` is mixed with other types**: A natural mix of standalone and multi-part questions is generated.

**Behavior when `multi-part` is not enabled**: All questions are flat; no subquestions are generated.

**`optionalParts`**: When `true`, the parent question is an "answer any N of M parts" format. `requiredPartsCount` specifies N.

**Mandatory fields on subquestions**: Every subquestion at every level must include a `correctAnswer` and a `rubric`. The AI is explicitly instructed not to leave these empty.

---

## Diagram Generation

See [Step 4](#step-4-diagram-generation-multi-agent) for the pipeline overview. Key rules:

**When diagrams are added** (professor's-judgment heuristic):
- Physical setups with spatial configuration (circuit schematics, free-body diagrams, beam loading)
- Data structures with labeled values (trees, graphs with weighted edges)
- Multi-part questions sharing a common setup
- Medical physiology curves (action potential, PV loop, dose-response, pharmacokinetics)
- Anatomical cross-sections and histological setups

**When diagrams are NOT added**:
- Pure theoretical / definition questions
- Simple single-step calculations with no spatial complexity
- Medical questions that only ask for text explanations

**Diagram rendering toolchain (nonai engine)**:
1. `circuitikz_tool` → LaTeX/CircuiTikZ → PDF → PNG → S3
2. `claude_code_tool` → Claude generates matplotlib/networkx Python code → executed → PNG → S3
3. `matplotlib_tool` → Direct matplotlib code → PNG → S3

**Diagram size**: `figsize=(6,4)` or `(5,4)`, DPI 100–150. Large figures (10×8) are prohibited to keep assignment PDFs compact.

---

## Document Processing

**Class**: `DocumentProcessor` (`src/utils/document_processor.py`)

Supported input formats via MIME type or file extension:

| Format | MIME Type | Extraction Method |
|---|---|---|
| PDF | `application/pdf` | Poppler → page images → GPT-4o vision (multi-page batch) |
| Plain text | `text/plain` | Direct UTF-8 decode |
| DOCX | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | `python-docx` |
| DOC | `application/msword` | `python-docx` (legacy) |
| Markdown | `text/markdown` | `markdown` → HTML → `html2text` |
| HTML | `text/html` | `html2text` |
| CSV | `text/csv` | `csv.reader` → formatted text |
| JSON | `application/json` | `json.dumps` pretty-print |

PDF extraction is vision-based: each page is rendered at 200 DPI and sent to GPT-4o as base64-encoded images in a single multi-image completion request, preserving mathematical notation and table structure that text-layer extraction would corrupt.

---

## Prompt Design

### Priority Hierarchy

When multiple content sources are present, the AI is guided by the following priority:

1. **`generation_prompt`** (user free-text) — if present without source material, it is the *exclusive* topic; do not deviate
2. **Video transcripts** — primary lecture content
3. **Document texts** — supplementary reading material

### Self-Contained Question Rule

All system prompts enforce that every question must be fully self-contained:
- All numerical values, component labels, and state descriptions must appear *in the question text*
- No references to "the figure above", "see the table", "as shown"
- Diagrams may be added by a separate system later — the question text must be comprehensible without them

### Code Question Guidelines (Engineering)

| `outputType` | `code` field | `correctAnswer` |
|---|---|---|
| `"code"` | Template with key parts left blank | Full working code |
| `"function"` | Function signature with empty body | Full function implementation |
| `"algorithm"` | Outline with key steps blank | Detailed step-by-step description |
| `"output"` | The code snippet to analyze | Expected stdout / return value |

### Subquestion Requirements

All prompts explicitly state:
> EVERY subquestion at ALL levels MUST include `correctAnswer` and `rubric`. Do NOT leave these empty.

---

## Error Handling & Degradation

| Stage | Failure Mode | Behaviour |
|---|---|---|
| Document parsing | `DocumentProcessor` raises | Exception propagated; generation aborted |
| Question generation | OpenAI API error | Exception re-raised; HTTP 500 returned |
| Equation extraction | Any error | Warning logged; original questions returned unchanged (graceful degradation) |
| Diagram generation | Rendering failure | Fallback router tries alternative tools; if all fail, question proceeds without diagram |
| Diagram review | Gemini review fails | Logged; diagram may be kept or discarded depending on fallback policy |
| Question review | Any error | Review is skipped; all generated questions are kept |
| Database commit | Error | `db.rollback()` called; HTTP 500 returned |

---

## SSE Streaming Endpoint

`POST /api/assignments/generate-stream` runs the same generation pipeline in a **background thread**. A `_QueueLogHandler` is attached to the application logger and feeds log records into a `queue.Queue`. The FastAPI SSE generator reads from this queue and yields events to the client as `text/event-stream`.

**Event format** (JSON per line):

```
data: {"type": "log", "level": "info", "message": "Starting question generation..."}

data: {"type": "log", "level": "info", "message": "Diagram analysis complete"}

data: {"type": "complete", "assignment": { ...full AssignmentOut JSON... }}
```

The frontend uses this stream to drive a real-time progress log panel during the (potentially 30–120 second) generation process.

---

## Configuration Reference

| Parameter | Source | Default | Notes |
|---|---|---|---|
| `OPENAI_API_KEY` | Environment | — | Required; used by `AssignmentGenerator`, `DiagramAnalysisAgent`, `QuestionReviewAgent`, `DocumentProcessor` |
| `AWS_S3_BUCKET` | Environment | — | Required for diagram upload |
| `AWS_ACCESS_KEY_ID` | Environment | — | Required for S3 |
| `AWS_SECRET_ACCESS_KEY` | Environment | — | Required for S3 |
| `GOOGLE_API_KEY` / Vertex AI credentials | Environment | — | Required for Gemini diagram reviewer and `"ai"` engine |
| `generator.model` | Hardcoded | `"gpt-4o"` | Main text generation model |
| `diagram_agent.model` | Hardcoded | `"gpt-4o"` | Diagram decision-making model |
| `diagramEngine` | `generation_options` | `"nonai"` | `"ai"` / `"nonai"` / `"both"` |
| `diagramModel` | `generation_options` | `"flash"` | Gemini model variant for AI engine |

---

## File Map

| File | Role |
|---|---|
| `src/utils/assignment_generator.py` | Main orchestrator — `AssignmentGenerator` class |
| `src/utils/assignment_schemas.py` | JSON Schema definitions for structured output (parsing flow) |
| `src/utils/assignment_pydantic_models.py` | Pydantic models for Responses API structured output (generation flow) |
| `src/utils/diagram_agent.py` | `DiagramAnalysisAgent` — multi-agent diagram generation |
| `src/utils/diagram_tools.py` | Diagram rendering tool implementations and `DIAGRAM_TOOLS` definitions |
| `src/utils/domain_router.py` | Classifies question domain (electrical, mechanical, medical, etc.) |
| `src/utils/subject_prompt_registry.py` | Subject-specific diagram prompts per domain |
| `src/utils/fallback_router.py` | Fallback rendering strategy per subject |
| `src/utils/gemini_diagram_reviewer.py` | Gemini 2.5 Pro semantic diagram review |
| `src/utils/question_review_agent.py` | `QuestionReviewAgent` — quality control against source material |
| `src/utils/document_processor.py` | `DocumentProcessor` — multi-format file text extraction |
| `src/routes/assignments.py` | FastAPI route handlers: `/generate`, `/generate-stream` |
| `src/schemas.py` | `AssignmentGenerateRequest` and related Pydantic schemas |
