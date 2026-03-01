# PDF Answer Processor — Data Flow, Usage & Output

**File**: `src/utils/pdf_answer_processor.py`
**Class**: `PDFAnswerProcessor`

---

## Overview

`PDFAnswerProcessor` converts student PDF answer sheets into a structured `Dict[str, Any]` keyed by normalized question IDs. It uses a two-stage pipeline:

1. **`process_pdf_to_json`** — PDF → images → GPT-5 vision extraction → YOLO bounding-box enrichment → answers dict
2. **`extract_and_upload_diagrams`** — answers dict → diagram crop from PDF → S3 upload → answers dict updated with S3 keys

---

## `process_pdf_to_json`

### Signature

```python
def process_pdf_to_json(
    self,
    pdf_path: str,
    questions: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `pdf_path` | `str` | Absolute local path to the PDF answer sheet |
| `questions` | `Optional[List[Dict]]` | Assignment questions list (used to derive expected question IDs). If `None`, all questions found in the sheet are extracted. |

### Data Flow

```
PDF file (disk)
    │
    ▼  convert_from_path (Poppler, 200 DPI)
List[PIL.Image]  (one per page)
    │
    ├── Each page → base64 JPEG data URL → image_contents[]
    │
    ▼  OpenAI gpt-5 multimodal (structured output / json_schema)
Raw LLM JSON:
{
  "answer_sheet": [
    { "question_number": "17(a)", "answer": "...", "diagram": { "label": "...", "page_number": 2 } },
    { "question_number": "1",    "answer": "C",   "diagram": null },
    ...
  ]
}
    │
    ▼  _normalize_question_number  (17(a) → 17.1, 33(a)(i) → 33.1.1, etc.)
    ▼  _normalize_mcq_answer       ("C, 16 x 10^6 J" → "C")
Internal answers dict (stub diagram bounding_box = None)
    │
    ▼  _enrich_answers_with_yolo_bounding_box
       │  For each page that has ≥1 diagram answer:
       │    Save page as temp JPEG
       │    Run YOLO model → List[{bbox, confidence, class_id, ymin}]
       │    Match detections → questions on that page
       └── answers dict with bounding_box populated
    │
    ▼
Return answers dict
```

### LLM Prompt Behaviour

- All PDF pages are sent as a single multimodal request (Page 1, Page 2, …).
- Structured output (`json_schema`) enforces the `answer_sheet` array schema; the model cannot return free-form JSON.
- The prompt instructs the model to:
  - Use dot notation for sub-parts (`17(a)` → `17.1`) — note this normalization is also applied in code post-LLM.
  - Return only the letter (`A`/`B`/`C`/`D`) for MCQ answers.
  - Include `diagram.page_number` when a drawn diagram is detected.

### YOLO Enrichment Logic

| Scenario | Assignment |
|----------|-----------|
| 1 answer needing a diagram on a page, N detections | Highest-confidence detection |
| N answers ≤ N detections | Top-N detections sorted by `ymin` (top of page first) |
| N answers > N detections | All detections assigned top-to-bottom; remaining answers keep `bounding_box = None` |

Model path and confidence threshold are configurable via environment variables:

```
DIAGRAM_YOLO_MODEL_PATH  (default: runs/detect/diagram_detector5/weights/best.pt)
DIAGRAM_YOLO_CONFIDENCE  (default: 0.25)
```

### Output Format

Returns `Dict[str, Any]` keyed by normalized question ID.

**Text-only answer** — value is a plain string:
```json
{
  "1": "C",
  "2": "The resistance increases with temperature because..."
}
```

**Answer with diagram** — value is a dict:
```json
{
  "17.1": {
    "text": "Applying coating of zinc",
    "diagram": {
      "bounding_box": [120, 340, 680, 810],
      "label": "Circuit diagram",
      "page_number": 2,
      "confidence": 0.87,
      "s3_key": null,
      "file_id": null,
      "filename": null
    }
  }
}
```

**Fields in diagram object after `process_pdf_to_json`**:

| Field | Type | Set by | Value at this stage |
|-------|------|--------|---------------------|
| `bounding_box` | `[x1, y1, x2, y2]` \| `null` | YOLO | Pixel coords on page image (200 DPI), or `null` if YOLO found nothing |
| `label` | `str` | LLM | Diagram label from answer sheet, or `"unlabeled"` |
| `page_number` | `int` | LLM | 1-based page number |
| `confidence` | `float` \| absent | YOLO | YOLO detection confidence (only present when YOLO assigned) |
| `s3_key` | `null` | — | Always `null` at this stage |
| `file_id` | `null` | — | Always `null` at this stage |
| `filename` | `null` | — | Always `null` at this stage |

### Error Behaviour

- Raises `RuntimeError` if Poppler is not installed or PDF conversion fails.
- Returns `{}` if the LLM returns an empty `answer_sheet`.
- If YOLO is not installed (`ultralytics` missing), it logs a warning and skips bounding-box enrichment — answers are still returned without bounding boxes.
- Per-page YOLO errors are caught and logged; the loop continues.

---

## `extract_and_upload_diagrams`

### Signature

```python
def extract_and_upload_diagrams(
    self,
    submission_id: str,
    pdf_s3_key: str,
    answers: Dict[str, Any],
    s3_client,
    s3_bucket: str,
    s3_upload_func,
) -> Dict[str, Any]:
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `submission_id` | `str` | Submission UUID (used in S3 key path) |
| `pdf_s3_key` | `str` | S3 object key of the original PDF submission |
| `answers` | `Dict[str, Any]` | Output from `process_pdf_to_json` |
| `s3_client` | `boto3.client` | Pre-authenticated boto3 S3 client |
| `s3_bucket` | `str` | Name of the S3 bucket |
| `s3_upload_func` | `Callable(path, key, content_type)` | Wrapper function that uploads a local file to S3 |

### Data Flow

```
answers dict  (from process_pdf_to_json)
    │
    ▼  Filter: answers where diagram.bounding_box is set AND s3_key is null
    │
    ▼  Download PDF from S3 → temp local file
    │
    ├─ For each qualifying question:
    │      │
    │      ▼  _extract_diagram_from_pdf
    │         convert_from_path (single page, 200 DPI)
    │         page_img.crop(bounding_box)  →  JPEG (quality 95)  →  temp file
    │      │
    │      ▼  s3_upload_func(temp_path, s3_key, "image/jpeg")
    │         S3 key pattern: submissions/{submission_id}/diagrams/q{question_id}_{uuid}.jpg
    │      │
    │      ▼  Update answers[question_id]["diagram"]:
    │             s3_key   = "submissions/.../diagrams/q17.1_<uuid>.jpg"
    │             file_id  = "<uuid>"
    │             filename = "diagram_q17.1.jpg"
    │
    ▼  Cleanup temp files (PDF + per-diagram JPEGs)
    │
    ▼
Return updated answers dict
```

### Output Format

Returns the same `Dict[str, Any]` with diagram fields populated for every successfully uploaded diagram:

```json
{
  "17.1": {
    "text": "Applying coating of zinc",
    "diagram": {
      "bounding_box": [120, 340, 680, 810],
      "label": "Circuit diagram",
      "page_number": 2,
      "confidence": 0.87,
      "s3_key": "submissions/abc-123/diagrams/q17.1_550e8400-e29b-41d4-a716-446655440000.jpg",
      "file_id": "550e8400-e29b-41d4-a716-446655440000",
      "filename": "diagram_q17.1.jpg"
    }
  }
}
```

**Fields updated by `extract_and_upload_diagrams`**:

| Field | Value |
|-------|-------|
| `s3_key` | Full S3 object key to the cropped JPEG |
| `file_id` | UUIDv4 string, unique per diagram |
| `filename` | Human-readable filename `diagram_q{question_id}.jpg` |

Answers that **do not** have a diagram, or whose diagram has no `bounding_box`, are returned unchanged.

### Error Behaviour

- If the PDF cannot be downloaded from S3, returns the original `answers` dict unchanged and logs the error.
- Individual diagram extraction failures are caught per-question; the loop continues for remaining questions.
- On any exception the temp PDF file is always cleaned up via a `finally` block.

---

## Typical Usage (Submissions Route)

```python
from utils.pdf_answer_processor import PDFAnswerProcessor

processor = PDFAnswerProcessor()

# Stage 1: run synchronously before saving the submission
answers = processor.process_pdf_to_json(
    pdf_path="/tmp/submission_abc123.pdf",
    questions=assignment["questions"],
)

# Stage 2: extract & upload diagrams (can run in background task)
answers = processor.extract_and_upload_diagrams(
    submission_id=submission_id,
    pdf_s3_key=f"submissions/{submission_id}/answer_sheet.pdf",
    answers=answers,
    s3_client=boto3.client("s3"),
    s3_bucket=os.getenv("AWS_S3_BUCKET"),
    s3_upload_func=s3_upload_file,
)

# answers is now a fully-populated dict ready for the grading service
```

---

## Dependencies & Environment Variables

| Dependency | Purpose |
|------------|---------|
| `pdf2image` + Poppler | PDF → PIL images |
| `openai` (`gpt-5`) | Vision-based answer extraction |
| `ultralytics` (optional) | YOLO diagram detection |
| `Pillow` | Image cropping |
| `boto3` | S3 download/upload (caller-provided) |

| Environment Variable | Default | Description |
|----------------------|---------|-------------|
| `OPENAI_API_KEY` | — | OpenAI API key (required unless passed to constructor) |
| `POPPLER_PATH` | system PATH | Path to Poppler `bin/` directory |
| `DIAGRAM_YOLO_MODEL_PATH` | `runs/detect/diagram_detector5/weights/best.pt` | YOLO weights file |
| `DIAGRAM_YOLO_CONFIDENCE` | `0.25` | Minimum detection confidence for diagram boxes |

---

## Question Number Normalization

Both the LLM prompt and the post-processing step normalize question numbering to dot notation so IDs are consistent with the assignment question tree:

| Raw (answer sheet) | Normalized |
|--------------------|------------|
| `17(a)` | `17.1` |
| `17(b)` | `17.2` |
| `33(a)(i)` | `33.1.1` |
| `33(a)(ii)` | `33.1.2` |
| `29.1` | `29.1` *(unchanged)* |
| `1` | `1` *(unchanged)* |
