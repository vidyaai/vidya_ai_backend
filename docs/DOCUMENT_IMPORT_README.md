# Document Import Feature

This document describes the implementation of the document import functionality that allows users to upload documents and automatically generate assignment questions using AI.

## Overview

The document import feature consists of:

1. **Backend API endpoint** (`/api/assignments/import-document`)
2. **Document processing service** for extracting text from various file formats
3. **AI-powered assignment parser** that generates questions from document content
4. **Frontend integration** with the existing assignment creation workflow

## Supported File Types

The system supports the following document formats:

- **PDF** (`.pdf`) - Uses PyPDF2 for text extraction
- **Microsoft Word** (`.docx`) - Uses python-docx library
- **Plain Text** (`.txt`) - Direct text processing
- **Markdown** (`.md`) - Converted to plain text
- **HTML** (`.html`, `.htm`) - Text extraction with html2text
- **CSV** (`.csv`) - Structured data processing
- **JSON** (`.json`) - Data structure to text conversion

**Note**: Legacy Word documents (`.doc`) are not supported and require conversion to `.docx` format.

## API Usage

### Endpoint: POST `/api/assignments/import-document`

**Request Body:**
```json
{
  "file_content": "base64_encoded_file_content",
  "file_name": "document.pdf",
  "file_type": "application/pdf",
  "generation_options": {
    "num_questions": 5,
    "question_types": ["multiple-choice", "short-answer", "long-answer"],
    "difficulty_level": "medium",
    "engineering_level": "undergraduate"
  }
}
```

**Response:**
```json
{
  "title": "Assignment from Document",
  "description": "Generated assignment description",
  "questions": [
    {
      "id": 1,
      "type": "multiple-choice",
      "question": "What is the main concept discussed?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correctAnswer": "Option A",
      "points": 5,
      "rubric": "Grading criteria",
      "order": 1
    }
  ],
  "extracted_text": "First 1000 characters of extracted text...",
  "file_info": {
    "original_filename": "document.pdf",
    "file_type": "application/pdf",
    "content_length": 5000,
    "questions_generated": 5,
    "total_points": 25
  }
}
```

## Installation Requirements

Install the additional dependencies for document processing:

```bash
pip install PyPDF2>=3.0.1 python-docx>=0.8.11 html2text>=2020.1.16 markdown>=3.4.4
```

Or install from the requirements file:

```bash
pip install -r requirements_document_processing.txt
```

## Implementation Details

### Document Processing (`utils/document_processor.py`)

The `DocumentProcessor` class handles text extraction from various file formats:

- **PDF Processing**: Uses PyPDF2 to extract text from all pages
- **Word Processing**: Uses python-docx to extract text from paragraphs and tables
- **Text Processing**: Handles various text encodings (UTF-8, Latin-1, etc.)
- **HTML Processing**: Converts HTML to plain text while preserving structure
- **Markdown Processing**: Converts Markdown to HTML then to plain text
- **CSV Processing**: Structures CSV data into readable text format
- **JSON Processing**: Converts JSON objects into structured text

### AI Assignment Parser (`utils/document_processor.py`)

The `AssignmentDocumentParser` class uses OpenAI GPT-4o to:

- Analyze document content and identify key concepts
- Generate appropriate assignment questions based on content
- Create questions of various types (multiple-choice, short-answer, etc.)
- Provide grading rubrics and point values
- Ensure questions are appropriate for the specified educational level

### Frontend Integration

The frontend `ImportFromDocumentModal` component:

- Provides drag-and-drop file upload interface
- Validates file types and sizes (10MB limit)
- Converts files to base64 for API transmission
- Displays progress during processing
- Integrates with existing assignment builder workflow

## Error Handling

The system includes comprehensive error handling for:

- **File Format Errors**: Unsupported or corrupted files
- **Content Extraction Errors**: Files with no extractable text
- **AI Processing Errors**: Issues with question generation
- **Network Errors**: API communication problems
- **Validation Errors**: Invalid request parameters

## Security Considerations

- File size limits (10MB maximum)
- File type validation on both frontend and backend
- Base64 encoding for secure file transmission
- User authentication required for all endpoints
- Input sanitization for extracted text content

## Usage Workflow

1. User selects "Import from Document" in the assignment creation interface
2. User drags and drops or selects a supported document file
3. Frontend validates file type and size
4. File is converted to base64 and sent to backend API
5. Backend extracts text content from the document
6. AI service analyzes content and generates assignment questions
7. Generated assignment data is returned to frontend
8. User can review and modify questions in the assignment builder

## Testing

Run the test script to verify functionality:

```bash
cd vidya_ai_backend/src
python tests/test_document_import.py
```

This will test both text extraction and AI-powered question generation.

## Limitations

- Legacy `.doc` files require conversion to `.docx`
- Complex PDF layouts may not extract text correctly
- AI-generated questions may require manual review and editing
- Processing time depends on document size and complexity
- Requires OpenAI API access for question generation

## Future Enhancements

Potential improvements include:

- Support for additional file formats (PowerPoint, Excel)
- OCR capabilities for image-based PDFs
- Batch processing of multiple documents
- Custom prompt templates for different subjects
- Question difficulty assessment and adjustment
- Integration with institutional content standards
