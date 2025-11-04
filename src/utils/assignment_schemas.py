"""
Shared JSON schemas for assignment-related AI responses.
This module provides reusable schemas for structured output from AI models.
"""

from typing import Dict, Any


def get_assignment_parsing_schema(
    schema_name: str = "assignment_parsing_response",
) -> Dict[str, Any]:
    """
    Get the JSON schema for assignment parsing with dynamic naming.
    This includes title, description, and total_points in addition to questions.

    Args:
        schema_name: The name for the schema (default: "assignment_parsing_response")

    Returns:
        JSON schema dictionary for structured output
    """

    no_bbox = "no_bbox" in schema_name
    step1_mode = "step1" in schema_name  # Step 1 excludes answers/rubrics

    # Define equation schema
    equation_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "latex": {"type": "string"},
            "mathml": {"type": ["string", "null"]},
            "position": {
                "type": "object",
                "properties": {
                    "char_index": {
                        "type": "integer",
                        "description": "Character count in question text after which equation appears",
                    },
                    "context": {
                        "type": "string",
                        "enum": ["question_text", "options", "correctAnswer"],
                        "description": "Where in the question structure this equation appears",
                    },
                },
                "required": ["char_index", "context"],
            },
            "type": {
                "type": "string",
                "enum": ["inline", "display"],
                "description": "Whether equation is inline with text or display block",
            },
        },
        "required": ["id", "latex", "position", "type"],
    }

    # Build base question properties
    base_question_properties = {
        "id": {"type": "integer"},
        "type": {
            "type": "string",
            "enum": [
                "multiple-choice",
                "fill-blank",
                "short-answer",
                "numerical",
                "long-answer",
                "true-false",
                "code-writing",
                "diagram-analysis",
                "multi-part",
            ],
        },
        "question": {"type": "string"},
        "points": {"type": "number"},
        "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
        "options": {"type": "array", "items": {"type": "string"}},
        "allowMultipleCorrect": {"type": "boolean"},
        "multipleCorrectAnswers": {"type": "array", "items": {"type": "string"}},
        "order": {"type": "integer"},
        "hasCode": {"type": "boolean"},
        "hasDiagram": {"type": "boolean"},
        "codeLanguage": {"type": "string"},
        "outputType": {"type": "string"},
        "rubricType": {
            "type": "string",
            "enum": ["per-subquestion", "overall"],
        },
        "code": {"type": "string"},
        "equations": {
            "type": "array",
            "items": equation_schema,
            "description": "Mathematical equations with their character positions in question text",
        },
        "diagram": {
            "type": "object",
            "properties": (
                {"page_number": {"type": "integer"}, "caption": {"type": "string"}}
                if no_bbox
                else {
                    "s3_url": {"type": ["string", "null"]},
                    "s3_key": {"type": ["string", "null"]},
                }
            ),
        },
        "optionalParts": {"type": "boolean"},
        "requiredPartsCount": {"type": "integer"},
    }

    # Add answer-related fields only if NOT step1
    if not step1_mode:
        base_question_properties["correctAnswer"] = {"type": "string"}
        base_question_properties["explanation"] = {"type": "string"}
        base_question_properties["rubric"] = {"type": "string"}

    # Build subquestion properties (level 2)
    subquestion_level2_properties = {
        "id": {"type": "integer"},
        "type": {
            "type": "string",
            "enum": [
                "multiple-choice",
                "fill-blank",
                "short-answer",
                "numerical",
                "true-false",
                "code-writing",
                "diagram-analysis",
                "multi-part",
            ],
        },
        "question": {"type": "string"},
        "points": {"type": "number"},
        "options": {"type": "array", "items": {"type": "string"}},
        "allowMultipleCorrect": {"type": "boolean"},
        "multipleCorrectAnswers": {"type": "array", "items": {"type": "string"}},
        "hasCode": {"type": "boolean"},
        "hasDiagram": {"type": "boolean"},
        "codeLanguage": {"type": "string"},
        "outputType": {"type": "string"},
        "rubricType": {
            "type": "string",
            "enum": ["per-subquestion", "overall"],
        },
        "code": {"type": "string"},
        "equations": {
            "type": "array",
            "items": equation_schema,
            "description": "Mathematical equations with their character positions",
        },
        "diagram": {
            "type": "object",
            "properties": (
                {"page_number": {"type": "integer"}, "caption": {"type": "string"}}
                if no_bbox
                else {
                    "s3_url": {"type": ["string", "null"]},
                    "s3_key": {"type": ["string", "null"]},
                }
            ),
        },
        "optionalParts": {"type": "boolean"},
        "requiredPartsCount": {"type": "integer"},
    }

    if not step1_mode:
        subquestion_level2_properties["correctAnswer"] = {"type": "string"}
        subquestion_level2_properties["explanation"] = {"type": "string"}
        subquestion_level2_properties["rubric"] = {"type": "string"}

    # Build subquestion properties (level 3 - deepest)
    subquestion_level3_properties = {
        "id": {"type": "integer"},
        "type": {
            "type": "string",
            "enum": [
                "multiple-choice",
                "fill-blank",
                "short-answer",
                "numerical",
                "true-false",
                "code-writing",
                "diagram-analysis",
            ],
        },
        "question": {"type": "string"},
        "points": {"type": "number"},
        "options": {"type": "array", "items": {"type": "string"}},
        "allowMultipleCorrect": {"type": "boolean"},
        "multipleCorrectAnswers": {"type": "array", "items": {"type": "string"}},
        "hasCode": {"type": "boolean"},
        "hasDiagram": {"type": "boolean"},
        "codeLanguage": {"type": "string"},
        "outputType": {"type": "string"},
        "rubricType": {
            "type": "string",
            "enum": ["overall"],
        },
        "code": {"type": "string"},
        "equations": {
            "type": "array",
            "items": equation_schema,
            "description": "Mathematical equations with their character positions",
        },
        "diagram": {
            "type": "object",
            "properties": (
                {"page_number": {"type": "integer"}, "caption": {"type": "string"}}
                if no_bbox
                else {
                    "s3_url": {"type": ["string", "null"]},
                    "s3_key": {"type": ["string", "null"]},
                }
            ),
        },
        "optionalParts": {"type": "boolean"},
        "requiredPartsCount": {"type": "integer"},
    }

    if not step1_mode:
        subquestion_level3_properties["correctAnswer"] = {"type": "string"}
        subquestion_level3_properties["explanation"] = {"type": "string"}
        subquestion_level3_properties["rubric"] = {"type": "string"}

    # Build level 3 schema (deepest subquestions)
    subquestion_level3_required = ["id", "type", "question", "points"]
    if not step1_mode:
        subquestion_level3_required.extend(["correctAnswer", "explanation", "rubric"])

    subquestion_level3_schema = {
        "type": "object",
        "properties": subquestion_level3_properties,
        "required": subquestion_level3_required,
    }

    # Build level 2 schema (with level 3 subquestions)
    subquestion_level2_properties["subquestions"] = {
        "type": "array",
        "items": subquestion_level3_schema,
    }

    subquestion_level2_required = ["id", "type", "question", "points"]
    if not step1_mode:
        subquestion_level2_required.extend(["correctAnswer", "explanation"])

    subquestion_level2_schema = {
        "type": "object",
        "properties": subquestion_level2_properties,
        "required": subquestion_level2_required,
    }

    # Build base question schema (with level 2 subquestions)
    base_question_properties["subquestions"] = {
        "type": "array",
        "items": subquestion_level2_schema,
    }

    base_question_required = ["id", "type", "question", "points", "difficulty"]
    if not step1_mode:
        base_question_required.extend(["correctAnswer", "rubric"])

    base_question_schema = {
        "type": "object",
        "properties": base_question_properties,
        "required": base_question_required,
    }

    # Create the full parsing schema with additional fields
    schema = {
        "name": schema_name,
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "questions": {"type": "array", "items": base_question_schema},
            "total_points": {"type": "number"},
        },
        "required": ["title", "questions", "total_points"],
    }

    return schema
