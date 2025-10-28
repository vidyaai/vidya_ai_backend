# Assignment Document Parser - GPT-5 Implementation Summary

## Overview
Successfully upgraded the assignment document parser to use GPT-5 with comprehensive diagram extraction support across multiple document formats.

## Implementation Details

### 1. Enhanced Assignment Schema (✅ Complete)
**File: `src/utils/assignment_schemas.py`**

Added diagram metadata structure to all question levels (main questions, subquestions, nested subquestions):

```python
"diagram": {
    "page_number": int,        # Only for PDF/DOCX
    "bounding_box": {          # Only for PDF/DOCX
        "x": int,
        "y": int,
        "width": int,
        "height": int
    },
    "caption": str,
    "s3_key": str | null,      # For extracted diagrams (PDF/DOCX)
    "s3_url": str | null       # For URL-based diagrams (MD/HTML/CSV/JSON)
}
```

**Key Design Decision:**
- PDF/DOCX: Use `s3_key` (after extraction and upload), `s3_url` is null
- MD/HTML/CSV/JSON: Use `s3_url` (from content), `s3_key` is null

### 2. Updated PDF Parsing Prompt (✅ Complete)
**File: `src/utils/document_processor.py`**

Enhanced the PDF parsing instructions to include:
- Detailed diagram detection with bounding box coordinates
- Page number tracking (1-indexed)
- Caption/label extraction
- Coordinate system guidelines (top-left origin, pixel coordinates)
- Clear distinction between s3_key and s3_url fields

### 3. Helper Methods Implementation (✅ Complete)
**File: `src/utils/document_processor.py`**

#### `_extract_docx_images()`
- Extracts embedded images from DOCX files using python-docx
- Uploads images to S3: `users/{user_id}/temp_docx_images/{image_id}.{format}`
- Returns list of image metadata with s3_keys

#### `_detect_s3_urls()`
- Detects S3 URLs in text content (MD, HTML, CSV, JSON)
- Supports multiple S3 URL patterns:
  - `s3://...`
  - `https://s3.amazonaws.com/...`
  - `https://bucket.s3.amazonaws.com/...`

#### `extract_and_upload_diagrams()`
- Main pipeline for diagram extraction and S3 upload
- Handles PDF, DOCX, MD, HTML, CSV, JSON differently
- Updates question JSON with s3_keys after extraction

#### `_extract_pdf_diagrams()`
- Converts PDF pages to images (200 DPI)
- Crops diagrams using bounding boxes
- Recursively processes questions and subquestions
- Uploads to S3: `{base_s3_path}/q{question_id}_{uuid}.jpg`

### 4. Non-PDF Document Parser (✅ Complete)
**File: `src/utils/document_processor.py`**

#### `parse_non_pdf_document_to_assignment()`
Comprehensive parser supporting:

**TXT (Plain Text)**
- Text-only parsing, no diagram support
- hasDiagram must be false

**MD/HTML/CSV/JSON**
- Detects S3 URLs in content
- Populates `diagram.s3_url` for questions referencing images
- No bounding_box or page_number needed

**DOCX**
- Extracts embedded images first
- Uploads to S3 automatically
- LLM maps images to questions
- Populates `diagram.s3_key` from extracted images list

### 5. Updated Import Document Endpoint (✅ Complete)
**File: `src/routes/assignments.py`**

#### `/api/assignments/import-document`
- Removed PDF-only restriction
- Supports all document types: PDF, DOCX, TXT, MD, HTML, CSV, JSON
- Different processing paths:
  - **PDF**: Image-based parsing → Extract diagrams → Upload to S3
  - **DOCX**: Text parsing with image extraction → Upload images → Map to questions
  - **MD/HTML/CSV/JSON**: Text parsing → Detect S3 URLs → Return with s3_url
  - **TXT**: Text-only parsing (no diagrams)
- Calls `extract_and_upload_diagrams()` for PDF and DOCX
- Returns complete question JSON with populated s3_keys or s3_urls

### 6. Background Task for Diagram Extraction (✅ Complete)
**File: `src/controllers/background_tasks.py`**

#### `extract_question_diagrams_background()`
- Downloads source document from S3
- Extracts diagrams using AssignmentDocumentParser
- Updates assignment questions in database with s3_keys
- Handles errors gracefully

#### `queue_question_diagram_extraction()`
- Queue wrapper for background processing
- Runs in separate daemon thread

## Supported Document Types

| Format | Extension | MIME Type | Diagram Support | Method |
|--------|-----------|-----------|----------------|--------|
| PDF | .pdf | application/pdf | ✅ Yes | Bounding box extraction |
| DOCX | .docx | application/vnd.openxmlformats-officedocument.wordprocessingml.document | ✅ Yes | Embedded image extraction |
| Markdown | .md | text/markdown | ✅ Yes | S3 URL detection |
| HTML | .html/.htm | text/html | ✅ Yes | S3 URL detection |
| CSV | .csv | text/csv | ✅ Yes | S3 URL detection |
| JSON | .json | application/json | ✅ Yes | S3 URL detection |
| Text | .txt | text/plain | ❌ No | Text-only |

## S3 Storage Paths

### Question Diagrams (from question papers)
- **With assignment_id**: `assignments/{assignment_id}/question_diagrams/q{question_id}_{uuid}.jpg`
- **Temporary (no assignment)**: `users/{user_id}/temp_diagrams/q{question_id}_{uuid}.jpg`

### DOCX Images (temporary during parsing)
- `users/{user_id}/temp_docx_images/{image_id}.{format}`

### Submission Diagrams (from student answers)
- `submissions/{submission_id}/diagrams/q{question_id}_{file_id}.jpg`

## Database Storage Example

```json
{
  "id": 1,
  "type": "diagram-analysis",
  "question": "Analyze the circuit diagram and calculate total resistance",
  "hasDiagram": true,
  "diagram": {
    "page_number": 2,
    "bounding_box": {"x": 120, "y": 240, "width": 460, "height": 320},
    "caption": "RC Circuit Diagram",
    "s3_key": "assignments/abc-123/question_diagrams/q1_uuid-here.jpg",
    "s3_url": null
  },
  "points": 10,
  "rubric": "Award 5 points for correct calculation, 5 for methodology",
  "correctAnswer": "Total resistance is 150Ω"
}
```

## Key Features

1. **GPT-5 Integration**: All parsing uses GPT-5 for superior accuracy
2. **Structured Output**: JSON schema enforcement for consistent data
3. **Diagram Metadata**: Complete bounding box, page number, caption tracking
4. **Automatic Extraction**: Diagrams automatically cropped and uploaded to S3
5. **Multi-format Support**: 7 document types supported
6. **Recursive Processing**: Handles nested multi-part questions at any depth
7. **Error Handling**: Graceful degradation if diagram extraction fails
8. **Background Processing**: Optional async diagram extraction for large files

## Testing Checklist

- [x] Schema validation (diagram fields in all question levels)
- [x] PDF parsing with diagrams (multiple pages, multiple diagrams)
- [ ] DOCX parsing with embedded images
- [ ] MD/HTML with S3 URLs
- [ ] TXT (no diagram support verification)
- [ ] CSV/JSON with S3 URLs
- [ ] S3 upload paths and keys verification
- [ ] Database storage (questions JSON with s3_keys)
- [ ] Background task execution
- [ ] Error handling (missing diagrams, invalid bounding boxes)

## Files Modified

1. ✅ `src/utils/assignment_schemas.py` - Added diagram schema
2. ✅ `src/utils/document_processor.py` - Main implementation (450+ lines added)
3. ✅ `src/routes/assignments.py` - Updated import endpoint
4. ✅ `src/controllers/background_tasks.py` - Added background tasks

## Dependencies
All required dependencies already present:
- `pdf2image` (Poppler for PDF conversion)
- `python-docx` (DOCX processing)
- `Pillow` (Image manipulation)
- `openai` (GPT-5 API)
- `boto3` (S3 storage)

## Next Steps
1. Test with sample documents (PDF, DOCX, MD with diagrams)
2. Verify S3 uploads and diagram extraction
3. Test end-to-end flow: import → parse → extract → save → display
4. Monitor GPT-5 API usage and costs
5. Optimize bounding box accuracy if needed

