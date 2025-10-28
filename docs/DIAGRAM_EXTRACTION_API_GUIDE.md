# Diagram Extraction API Guide

## Overview
This guide explains how to use the enhanced assignment document parser with diagram extraction support.

## API Endpoint

### POST `/api/assignments/import-document`

Import assignment questions from various document formats with automatic diagram extraction.

**Supported Formats:**
- PDF (`.pdf`)
- DOCX (`.docx`)
- Markdown (`.md`)
- HTML (`.html`)
- CSV (`.csv`)
- JSON (`.json`)
- Plain Text (`.txt`)

## Request Format

```json
{
  "file_name": "physics_assignment.pdf",
  "file_type": "application/pdf",
  "file_content": "base64_encoded_content_here",
  "generation_options": {
    "detectDiagrams": true
  }
}
```

## Response Format

```json
{
  "title": "Physics Assignment - Circuits",
  "description": "Assignment on electrical circuits",
  "questions": [
    {
      "id": 1,
      "type": "diagram-analysis",
      "question": "Calculate the total resistance in the circuit shown below",
      "points": 10,
      "hasDiagram": true,
      "diagram": {
        "page_number": 2,
        "bounding_box": {
          "x": 120,
          "y": 240,
          "width": 460,
          "height": 320
        },
        "caption": "RC Circuit Diagram",
        "s3_key": "assignments/temp/question_diagrams/q1_abc123.jpg",
        "s3_url": null
      },
      "rubric": "Award 5 points for correct calculation, 5 for methodology",
      "correctAnswer": "Total resistance is 150Ω"
    }
  ],
  "extracted_text": "PDF content processed via image analysis",
  "file_info": {
    "original_filename": "physics_assignment.pdf",
    "file_type": "application/pdf",
    "questions_generated": 10,
    "total_points": 100
  }
}
```

## Document Type Examples

### 1. PDF Documents
**Diagram Extraction:** Automatic with bounding boxes

```python
# PDF diagrams are automatically detected and extracted
# The LLM provides bounding box coordinates
# Diagrams are cropped and uploaded to S3
# s3_key is populated, s3_url is null
```

**Example Question:**
```json
{
  "id": 1,
  "hasDiagram": true,
  "diagram": {
    "page_number": 3,
    "bounding_box": {"x": 100, "y": 200, "width": 400, "height": 300},
    "caption": "Free body diagram",
    "s3_key": "assignments/xyz/question_diagrams/q1_uuid.jpg",
    "s3_url": null
  }
}
```

### 2. DOCX Documents
**Diagram Extraction:** Embedded images extracted

```python
# Embedded images are extracted from DOCX
# Images are uploaded to S3 during parsing
# LLM maps images to questions
# s3_key is populated, s3_url is null
```

**Example Question:**
```json
{
  "id": 2,
  "hasDiagram": true,
  "diagram": {
    "caption": "Molecular structure diagram",
    "s3_key": "users/user123/temp_docx_images/img_uuid.png",
    "s3_url": null
  }
}
```

### 3. Markdown/HTML Documents
**Diagram Extraction:** S3 URLs detected in content

```markdown
# Sample Question

Analyze the diagram below:

![Circuit Diagram](https://my-bucket.s3.amazonaws.com/diagrams/circuit1.png)

Calculate the voltage across R1.
```

**Example Question:**
```json
{
  "id": 3,
  "hasDiagram": true,
  "diagram": {
    "caption": "Circuit Diagram",
    "s3_key": null,
    "s3_url": "https://my-bucket.s3.amazonaws.com/diagrams/circuit1.png"
  }
}
```

### 4. Plain Text Documents
**Diagram Extraction:** Not supported

```json
{
  "id": 4,
  "hasDiagram": false,
  "diagram": null
}
```

## Diagram Field Reference

### For PDF and DOCX (Extracted Diagrams)
```json
{
  "page_number": 2,              // Page where diagram appears (PDF only)
  "bounding_box": {              // Cropping coordinates (PDF only)
    "x": 120,                    // Left edge (pixels from left)
    "y": 240,                    // Top edge (pixels from top)
    "width": 460,                // Diagram width in pixels
    "height": 320                // Diagram height in pixels
  },
  "caption": "Circuit Diagram",  // Description or label
  "s3_key": "path/to/diagram.jpg", // S3 storage path
  "s3_url": null                 // Not used for extracted diagrams
}
```

### For MD/HTML/CSV/JSON (URL-based Diagrams)
```json
{
  "caption": "Circuit Diagram",
  "s3_key": null,               // Not used for URL-based diagrams
  "s3_url": "https://s3.amazonaws.com/bucket/image.png"
}
```

## Error Handling

### Unsupported File Type
```json
{
  "detail": "Unsupported file type: application/xyz. Supported types: PDF, DOCX, TXT, MD, HTML, CSV, JSON"
}
```

### Invalid File Content
```json
{
  "detail": "Invalid file content. Please ensure the file is properly encoded."
}
```

### Parsing Failure
```json
{
  "detail": "Failed to extract assignment questions from document. Please ensure the document contains assignment questions, exercises, or problems."
}
```

## Best Practices

### 1. PDF Documents
- Use high-quality PDFs (not scanned images)
- Ensure diagrams are clearly separated from text
- Avoid overlapping diagrams
- Use standard fonts for better text extraction

### 2. DOCX Documents
- Embed images directly (not as floating objects)
- Use standard image formats (PNG, JPEG)
- Keep images reasonably sized (< 5MB each)

### 3. Markdown/HTML
- Use valid S3 URLs for images
- Ensure images are publicly accessible or use presigned URLs
- Include alt text for better diagram detection

### 4. CSV/JSON
- Store S3 URLs as complete URLs
- Use consistent URL format
- Validate URLs before submission

## Performance Considerations

### Processing Time
- **PDF**: 10-30 seconds (depends on page count and diagrams)
- **DOCX**: 5-15 seconds (depends on image count)
- **MD/HTML/CSV/JSON**: 3-10 seconds (text-only parsing)
- **TXT**: 2-5 seconds (fastest, no diagrams)

### File Size Limits
- Maximum file size: 10MB
- Maximum pages (PDF): 50 pages
- Maximum images (DOCX): 20 images

### GPT-5 Token Usage
- PDF (10 pages): ~15,000 tokens
- DOCX (5 pages): ~8,000 tokens
- Text formats: ~2,000-5,000 tokens

## Accessing Extracted Diagrams

### S3 Presigned URLs
To display diagrams to users, generate presigned URLs:

```python
from controllers.storage import s3_presign_url

# Get diagram URL (valid for 1 hour)
diagram_url = s3_presign_url(s3_key, expires_in=3600)
```

### Frontend Display
```javascript
// Display diagram in question
if (question.hasDiagram && question.diagram.s3_key) {
  const imageUrl = await fetchPresignedUrl(question.diagram.s3_key);
  // Display image
} else if (question.hasDiagram && question.diagram.s3_url) {
  // Use S3 URL directly
  const imageUrl = question.diagram.s3_url;
}
```

## Background Processing

For large documents or batch processing, diagrams can be extracted asynchronously:

```python
from controllers.background_tasks import queue_question_diagram_extraction

# Queue diagram extraction (runs in background)
queue_question_diagram_extraction(
    assignment_id="abc-123",
    file_content_s3_key="uploads/document.pdf",
    file_type="application/pdf",
    user_id="user-456"
)
```

## Troubleshooting

### Diagrams Not Detected
- Verify PDF quality (not scanned)
- Check if diagrams are embedded (not external links)
- Ensure diagrams have clear boundaries

### Incorrect Bounding Boxes
- May occur with complex layouts
- LLM provides best-effort coordinates
- Can be manually adjusted if needed

### Missing S3 Keys
- Check S3 permissions
- Verify AWS credentials
- Ensure bucket exists

### S3 URLs Not Detected
- Verify URL format matches patterns
- Check if URLs are in text content
- Ensure URLs are valid S3 paths

## Examples

See `test_diagram_upload.py` for complete examples of:
- PDF document import with diagrams
- DOCX document import with images
- Markdown import with S3 URLs
- Error handling scenarios

