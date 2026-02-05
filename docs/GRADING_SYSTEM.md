# VidyaAI Assignment Grading System

This document explains how the AI-powered grading system works in the VidyaAI assignment platform.

## Overview

The VidyaAI grading system uses a hybrid approach combining:

1. **Deterministic grading** for objective questions (Multiple Choice, True/False)
2. **LLM-powered grading** for subjective questions (Short Answer, Long Answer, Multi-Part)
3. **Vision AI support** for grading answers that include diagrams

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Grading Pipeline                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐     ┌──────────────────┐     ┌──────────────────────┐ │
│  │  Submission  │────▶│  LLMGrader       │────▶│  GradeSubmission     │ │
│  │  (answers)   │     │  Service         │     │  Response            │ │
│  └──────────────┘     └──────────────────┘     └──────────────────────┘ │
│                              │                                           │
│                              ▼                                           │
│               ┌──────────────────────────────┐                          │
│               │  Question Type Router        │                          │
│               └──────────────────────────────┘                          │
│                       │              │                                   │
│           ┌───────────┘              └───────────┐                      │
│           ▼                                      ▼                      │
│  ┌──────────────────┐                   ┌──────────────────┐           │
│  │  Deterministic   │                   │  LLM Grading     │           │
│  │  (MCQ/T-F)       │                   │  (Short/Long/    │           │
│  │                  │                   │   Multi-Part)    │           │
│  └──────────────────┘                   └──────────────────┘           │
│                                                  │                      │
│                                                  ▼                      │
│                                         ┌──────────────────┐           │
│                                         │  Vision Support  │           │
│                                         │  (Diagrams)      │           │
│                                         └──────────────────┘           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. LLMGrader Service (`src/utils/grading_service.py`)

The main grading engine that orchestrates all grading operations.

```python
class LLMGrader:
    def __init__(self, api_key=None, model="gpt-5"):
        # Initializes OpenAI client

    def grade_submission(self, assignment, submission_answers, options=None):
        # Returns: total_score, total_points, feedback_by_question, overall_feedback
```

### 2. Grading Endpoint (`src/routes/assignments.py`)

```
POST /api/assignments/{assignment_id}/submissions/{submission_id}/grade
```

Triggers AI grading for a single submission.

### 3. Batch Grading Endpoint

```
POST /api/assignments/{assignment_id}/submissions/batch-grade
```

Queues multiple submissions for background grading.

## Question Types and Grading Methods

### Deterministic Grading (Automatic)

These question types are graded instantly without LLM calls:

#### Multiple Choice Questions

```python
def _grade_multiple_choice(question, answer_obj, max_points):
    # Supports various answer formats:
    # - Index: "0", "1", "2"
    # - Letters: "A", "B", "C", "D"
    # - Letter prefixes: "A)", "B.", "a)", "b."
    # - Roman numerals: "i)", "ii)", "I)", "II."
    # - Full option text matching

    # For multi-select questions:
    # Score = (intersection / union) * max_points
```

**Scoring Logic:**
- **Single-select**: Full points if correct, zero if incorrect
- **Multi-select**: Partial credit using Jaccard similarity (intersection/union)

#### True/False Questions

```python
def _grade_true_false(question, answer_obj, max_points):
    # Accepts: true/false, t/f, 1/0, yes/no, y/n
    # Case-insensitive matching
    # Full points or zero (no partial credit)
```

### LLM-Powered Grading

For subjective questions requiring AI evaluation:

#### Short Answer Questions
- Evaluated against reference answer and rubric
- AI considers semantic meaning, not just exact matching
- Provides detailed feedback

#### Long Answer Questions
- Comprehensive evaluation using rubric criteria
- Assesses completeness, accuracy, and depth
- Multi-factor scoring breakdown

#### Multi-Part Questions
- Each subquestion graded independently
- Supports nested multi-part questions (any depth)
- Optional parts filtering (only grades answered parts)

### Grading With Diagrams (Vision AI)

The system supports grading answers that include diagrams:

```python
# Answer structure with diagram
{
    "7": {
        "text": "Circuit explanation...",
        "diagram": {
            "s3_key": "submissions/<submission_id>/diagrams/q7.jpg",
            "file_id": "<uuid>",
            "filename": "circuit.jpg"
        }
    }
}
```

- Diagrams are stored in S3 and presigned URLs are generated
- GPT-4o (vision-enabled) model evaluates diagram correctness
- Considers labels, accuracy, completeness, and rubric alignment

## Answer Processing Pipeline

### 1. Question Flattening

Multi-part questions are flattened to create unique IDs:

```
Original:                    Flattened:
Q17 (multi-part)            Q17.1 (subquestion a)
  ├── (a)                   Q17.2 (subquestion b)
  ├── (b)                   Q17.3 (subquestion c)
  └── (c)
```

### 2. Answer Normalization

Student answers are normalized to match question structure:

```python
# Input formats supported:
- String: "My answer text"
- Object with text: {"text": "My answer text"}
- Object with diagram: {"text": "...", "diagram": {...}}
- Nested subAnswers: {"subAnswers": {"1": "...", "2": "..."}}
```

### 3. Bulk Prompt Construction

For LLM grading, all questions are combined into a single prompt:

```
QUESTION 1 (short-answer):
[Question text]
REFERENCE ANSWER:
[Correct answer]
RUBRIC:
[Grading criteria]
MAX POINTS: 5
STUDENT ANSWER:
[Student's response]

QUESTION 2 (long-answer):
...
```

### 4. Response Parsing

The LLM returns structured JSON feedback:

```json
{
    "question_1": {
        "score": 4.5,
        "strengths": "Clear explanation of concept",
        "areas_for_improvement": "Missing specific example",
        "breakdown": "Detailed analysis..."
    },
    "overall_feedback": "Good understanding demonstrated..."
}
```

## Grading Response Schema

```python
class GradeSubmissionResponse:
    submission_id: str
    assignment_id: str
    total_score: float          # Sum of all question scores
    total_points: float         # Sum of all max points
    percentage: float           # (total_score / total_points) * 100
    overall_feedback: str       # General assessment
    feedback_by_question: Dict[str, QuestionGradeFeedback]
    graded_at: datetime

class QuestionGradeFeedback:
    score: float
    max_points: float
    breakdown: str              # Detailed analysis
    strengths: str              # What student did well
    areas_for_improvement: str  # Suggestions for improvement
```

## Submission Status Flow

```
draft → submitted → grading → graded → returned
                      │
                      └── (if error) → submitted
```

## Grading Options

```python
class GradeSubmissionOptions:
    regrade: bool = False       # Force regrading
    max_tokens: int = 8000      # LLM response limit
    model: str = "gpt-4o"       # Model for LLM grading
    temperature: float = 0.1    # Low for consistent grading
```

## Batch Grading

For grading multiple submissions efficiently:

1. **Request** includes list of submission IDs
2. **Validation** confirms all submissions exist and are submitted
3. **Status Update** marks submissions as "grading"
4. **Background Processing** via `queue_batch_grading()`
5. **Results** stored in database as each completes

```python
# Batch grading request
{
    "submission_ids": ["sub-1", "sub-2", "sub-3"],
    "options": {
        "model": "gpt-4o"
    }
}
```

## PDF Submission Processing

For PDF answer sheet submissions:

1. **PDFAnswerProcessor** converts PDF to images
2. **Vision AI** extracts answers from each page
3. **Answer Mapping** matches extracted answers to question IDs
4. **Diagram Extraction** crops and stores diagram regions
5. **Standard Grading** proceeds with extracted answers

## Access Control

Grading operations require:
- **Assignment owner** OR
- **User with "edit" permission** via shared link

```python
is_owner = assignment.user_id == user_id
has_edit_access = SharedLinkAccess.permission == "edit"
```

## API Endpoints Summary

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/assignments/{id}/submissions/{sub_id}/grade` | POST | Grade single submission |
| `/api/assignments/{id}/submissions/batch-grade` | POST | Queue batch grading |
| `/api/assignments/{id}/submissions` | GET | List submissions with grades |
| `/api/assignments/{id}/submissions/{sub_id}` | GET | Get submission with feedback |

## Error Handling

- **429 Rate Limit**: LLM API rate limits handled with retry logic
- **Invalid Answers**: Graceful handling of malformed answer data
- **Vision Failures**: Falls back to text-only grading if image processing fails
- **Timeout**: Long submissions may timeout; batch grading recommended

## Best Practices

1. **Include Rubrics**: Detailed rubrics improve grading accuracy
2. **Provide Reference Answers**: Especially for subjective questions
3. **Use Batch Grading**: For large numbers of submissions
4. **Review Edge Cases**: Spot-check AI grades for unusual answers
5. **Set Reasonable Points**: Partial credit works best with granular point values

## Database Schema

### AssignmentSubmission Model

```python
class AssignmentSubmission:
    id: str
    assignment_id: str
    user_id: str
    answers: JSONB              # Student's answers
    submission_method: str      # "in-app", "pdf", "file"
    submitted_files: JSONB      # File metadata
    score: str                  # Points earned
    percentage: str             # Percentage score
    feedback: JSONB             # Per-question feedback
    overall_feedback: str       # General feedback
    status: str                 # "draft", "submitted", "graded", "returned"
    graded_at: datetime
```

## Configuration

### Environment Variables

```bash
OPENAI_API_KEY=sk-...          # Required for LLM grading
AWS_S3_BUCKET=...              # For diagram storage
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

### Model Selection

- **gpt-4o**: Default, vision-enabled, best accuracy
- **gpt-4o-mini**: Faster, lower cost, good for simple questions
- **gpt-5**: Latest model for most accurate results

---

## Example Grading Flow

```
1. Student submits assignment
   └── POST /api/assignments/{id}/submissions

2. Teacher triggers grading
   └── POST /api/assignments/{id}/submissions/{sub_id}/grade

3. LLMGrader processes submission
   ├── Flatten questions/answers
   ├── Grade MCQ/T-F deterministically
   ├── Build LLM prompt for subjective questions
   ├── Include diagrams if present
   └── Parse LLM response

4. Results stored in database
   ├── submission.score = "85.00"
   ├── submission.percentage = "92.39"
   ├── submission.feedback = {...}
   └── submission.status = "graded"

5. Student views feedback
   └── GET /api/assignments/{id}/submissions/{sub_id}
```
