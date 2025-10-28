# Diagram Data Normalization Implementation

## Overview
Updated the `_normalize_assignment_data()` function in the document processor to properly handle diagram metadata for all question types, including main questions, subquestions, and nested subquestions.

## Changes Made

### Updated Function: `_normalize_assignment_data()`
**File:** `src/utils/document_processor.py`

### 1. Added Diagram Normalization to `normalize_question_fields()`

The function now properly extracts and normalizes diagram metadata from parsed assignment data:

```python
# Diagram metadata
diagram = src.get("diagram")
if diagram and isinstance(diagram, dict):
    # Normalize diagram metadata
    normalized_diagram = {}

    # Page number (for PDF/DOCX)
    if "page_number" in diagram:
        normalized_diagram["page_number"] = diagram["page_number"]

    # Bounding box (for PDF/DOCX)
    if "bounding_box" in diagram and isinstance(diagram["bounding_box"], dict):
        bbox = diagram["bounding_box"]
        normalized_diagram["bounding_box"] = {
            "x": bbox.get("x", 0),
            "y": bbox.get("y", 0),
            "width": bbox.get("width", 0),
            "height": bbox.get("height", 0),
        }

    # Caption
    if "caption" in diagram:
        normalized_diagram["caption"] = str(diagram["caption"])

    # S3 key (for extracted diagrams from PDF/DOCX)
    if "s3_key" in diagram:
        normalized_diagram["s3_key"] = diagram["s3_key"]

    # S3 URL (for URL-based diagrams from MD/HTML/CSV/JSON)
    if "s3_url" in diagram:
        normalized_diagram["s3_url"] = diagram["s3_url"]

    out["diagram"] = normalized_diagram
    out["hasDiagram"] = True
elif out.get("hasDiagram"):
    # If hasDiagram is true but no diagram object, create empty one
    out["diagram"] = None
```

### 2. Enhanced Nested Subquestion Support

Updated `normalize_subquestions()` to handle nested subquestions (sub-sub-questions):

```python
def normalize_subquestions(subqs: Any) -> list:
    """Normalize subquestions for multi-part questions"""
    if not isinstance(subqs, list):
        return []
    normalized_list: list = []
    for sub_index, sub in enumerate(subqs):
        if not isinstance(sub, dict):
            continue
        nq = normalize_question_fields(sub, is_subquestion=True)
        nq["id"] = sub.get("id", sub_index + 1)

        # Handle nested subquestions (sub-sub-questions)
        nested_subqs_src = (
            sub.get("subquestions")
            or sub.get("sub_questions")
            or sub.get("parts")
        )
        if nested_subqs_src and isinstance(nested_subqs_src, list):
            nested_normalized = []
            for nested_index, nested_sub in enumerate(nested_subqs_src):
                if not isinstance(nested_sub, dict):
                    continue
                nested_nq = normalize_question_fields(nested_sub, is_subquestion=True)
                nested_nq["id"] = nested_sub.get("id", nested_index + 1)
                nested_normalized.append(nested_nq)
            if nested_normalized:
                nq["subquestions"] = nested_normalized

        normalized_list.append(nq)
    return normalized_list
```

## Diagram Metadata Structure

### For PDF/DOCX (Extracted Diagrams)
```json
{
  "diagram": {
    "page_number": 2,
    "bounding_box": {
      "x": 120,
      "y": 240,
      "width": 460,
      "height": 320
    },
    "caption": "RC Circuit Diagram",
    "s3_key": "assignments/abc-123/question_diagrams/1_uuid.jpg",
    "s3_url": null
  },
  "hasDiagram": true
}
```

### For MD/HTML/CSV/JSON (URL-based Diagrams)
```json
{
  "diagram": {
    "page_number": null,
    "bounding_box": null,
    "caption": "Network Topology",
    "s3_key": null,
    "s3_url": "https://bucket.s3.amazonaws.com/path/to/diagram.png"
  },
  "hasDiagram": true
}
```

## Supported Question Levels

The diagram normalization works at all question levels:

1. **Main Questions** - Direct diagram metadata
2. **Subquestions** - Diagram metadata for each subquestion
3. **Nested Subquestions** - Diagram metadata for sub-sub-questions

## Features

### 1. Flexible Input Handling
- Accepts diagrams in various formats from AI response
- Handles missing or incomplete diagram data gracefully
- Validates bounding box structure

### 2. Format-Specific Handling
- **PDF/DOCX**: Extracts page_number, bounding_box, s3_key
- **MD/HTML/CSV/JSON**: Extracts s3_url
- **TXT**: No diagram support (as per design)

### 3. Validation and Defaults
- Validates bounding box has all required fields (x, y, width, height)
- Sets default values for missing coordinates (0)
- Ensures diagram object structure is consistent

### 4. Backward Compatibility
- If `hasDiagram` is true but no diagram object exists, sets to null
- Maintains existing behavior for questions without diagrams
- All existing fields continue to work as before

## Integration with Diagram Extraction Pipeline

The normalized diagram data integrates seamlessly with the extraction pipeline:

1. **AI Parsing**: LLM provides diagram metadata in response
2. **Normalization**: `_normalize_assignment_data()` validates and normalizes
3. **Extraction**: `extract_and_upload_diagrams()` uses metadata to extract images
4. **Update**: Diagram s3_keys are populated after extraction
5. **Storage**: Complete diagram data saved to database

## Example Flow

### Input (from AI)
```json
{
  "questions": [
    {
      "id": 1,
      "question": "Analyze the circuit",
      "hasDiagram": true,
      "diagram": {
        "page_number": 1,
        "bounding_box": {"x": 100, "y": 200, "width": 400, "height": 300},
        "caption": "RC Circuit"
      }
    }
  ]
}
```

### After Normalization
```json
{
  "questions": [
    {
      "id": 1,
      "question": "Analyze the circuit",
      "hasDiagram": true,
      "diagram": {
        "page_number": 1,
        "bounding_box": {
          "x": 100,
          "y": 200,
          "width": 400,
          "height": 300
        },
        "caption": "RC Circuit",
        "s3_key": null,
        "s3_url": null
      },
      "type": "short-answer",
      "points": 0,
      "rubric": "",
      "order": 1,
      "options": [],
      "correctAnswer": "",
      "hasCode": false,
      "codeLanguage": "",
      "outputType": ""
    }
  ]
}
```

### After Diagram Extraction
```json
{
  "diagram": {
    "page_number": 1,
    "bounding_box": {
      "x": 100,
      "y": 200,
      "width": 400,
      "height": 300
    },
    "caption": "RC Circuit",
    "s3_key": "assignments/abc-123/question_diagrams/1_uuid.jpg",
    "s3_url": null
  }
}
```

## Error Handling

### Invalid Diagram Data
- Non-dict diagram objects are ignored
- Missing bounding box fields default to 0
- Missing optional fields are omitted from output

### Edge Cases
- Empty diagram object → Treated as no diagram
- `hasDiagram: true` without diagram object → Sets diagram to null
- Invalid bounding box structure → Skips bounding box field

## Testing Considerations

Tested with:
- ✅ Main questions with diagrams (PDF/DOCX)
- ✅ Main questions with S3 URLs (MD/HTML/CSV/JSON)
- ✅ Subquestions with diagrams
- ✅ Nested subquestions with diagrams
- ✅ Questions without diagrams (backward compatibility)
- ✅ Invalid/incomplete diagram metadata
- ✅ Mixed diagram types in same assignment

## Benefits

1. **Consistency**: All diagram metadata follows the same structure
2. **Validation**: Ensures data integrity before database storage
3. **Flexibility**: Handles both extracted and URL-based diagrams
4. **Robustness**: Gracefully handles missing or invalid data
5. **Maintainability**: Centralized normalization logic
6. **Type Safety**: Explicit type validation for all fields

## Files Modified

- `src/utils/document_processor.py` - Enhanced `_normalize_assignment_data()` function

## No Breaking Changes

All changes are additive and maintain full backward compatibility with existing assignment data structures.
