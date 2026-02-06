"""
Shared JSON schemas for assignment-related AI responses.
This module provides reusable schemas for structured output from AI models.
"""

from typing import Dict, Any, List, Optional, Union, Type
from pydantic import BaseModel


def create_dynamic_generation_response(
    enabled_types: List[str],
) -> Union[Type[BaseModel], Type[BaseModel]]:
    """
    Create a dynamic Pydantic response model based on enabled question types.

    This function returns the appropriate response model for assignment generation:
    - If "multi-part" is in enabled_types: Returns AssignmentGenerationResponseNested
      (supports nested subquestions with full 3-level hierarchy)
    - Otherwise: Returns AssignmentGenerationResponseFlat
      (flat questions only, no subquestions field)

    The returned models exclude the 'equations' field for token efficiency.
    Equations will be extracted in a separate API call after question generation.

    Args:
        enabled_types: List of enabled question type strings
            (e.g., ["multiple-choice", "short-answer", "multi-part"])

    Returns:
        Appropriate Pydantic response model class (Flat or Nested)

    Examples:
        >>> # For flat questions only
        >>> schema = create_dynamic_generation_response(["multiple-choice", "short-answer"])
        >>> # Returns AssignmentGenerationResponseFlat

        >>> # For questions with multi-part support
        >>> schema = create_dynamic_generation_response(["multi-part", "short-answer"])
        >>> # Returns AssignmentGenerationResponseNested
    """
    from utils.assignment_pydantic_models import (
        AssignmentGenerationResponseFlat,
        AssignmentGenerationResponseNested,
    )

    # Check if multi-part questions are enabled
    if "multi-part" in enabled_types:
        return AssignmentGenerationResponseNested
    else:
        return AssignmentGenerationResponseFlat


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
            "position": {
                "type": "object",
                "properties": {
                    "char_index": {
                        "type": "integer",
                        "description": "Character count in question text after which equation appears",
                    },
                    "context": {
                        "type": "string",
                        "enum": ["question_text", "options", "correctAnswer", "rubric"],
                        "description": "Where in the question structure this equation appears",
                    },
                },
                "required": ["char_index", "context"],
                "additionalProperties": False,
            },
            "type": {
                "type": "string",
                "enum": ["inline", "display"],
                "description": "Whether equation is inline with text or display block",
            },
        },
        "required": ["id", "latex", "position", "type"],
        "additionalProperties": False,
    }

    # Define diagram schema based on no_bbox flag
    if no_bbox:
        diagram_schema = {
            "type": "object",
            "properties": {
                "page_number": {"type": "integer"},
                "caption": {"type": "string"},
            },
            "required": ["page_number", "caption"],
            "additionalProperties": False,
        }
    else:
        diagram_schema = {
            "type": "object",
            "properties": {
                "s3_url": {"type": ["string", "null"]},
                "s3_key": {"type": ["string", "null"]},
            },
            "required": ["s3_url", "s3_key"],
            "additionalProperties": False,
        }

    # Build subquestion properties (level 3 - deepest, no further nesting)
    subquestion_level3_schema = {
        "type": "object",
        "properties": {
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
            "rubricType": {"type": "string", "enum": ["overall"]},
            "code": {"type": "string"},
            "equations": {
                "type": "array",
                "items": equation_schema,
                "description": "Mathematical equations with their character positions",
            },
            "diagram": diagram_schema,
            "optionalParts": {"type": "boolean"},
            "requiredPartsCount": {"type": "integer"},
            "correctAnswer": {"type": "string"},
            "explanation": {"type": "string"},
            "rubric": {"type": "string"},
        },
        "required": [
            "id",
            "type",
            "question",
            "points",
            "options",
            "allowMultipleCorrect",
            "multipleCorrectAnswers",
            "hasCode",
            "hasDiagram",
            "codeLanguage",
            "outputType",
            "rubricType",
            "code",
            "equations",
            "diagram",
            "optionalParts",
            "requiredPartsCount",
            "correctAnswer",
            "explanation",
            "rubric",
        ],
        "additionalProperties": False,
    }

    # Build subquestion properties (level 2)
    subquestion_level2_schema = {
        "type": "object",
        "properties": {
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
            "rubricType": {"type": "string", "enum": ["per-subquestion", "overall"]},
            "code": {"type": "string"},
            "equations": {
                "type": "array",
                "items": equation_schema,
                "description": "Mathematical equations with their character positions",
            },
            "diagram": diagram_schema,
            "optionalParts": {"type": "boolean"},
            "requiredPartsCount": {"type": "integer"},
            "correctAnswer": {"type": "string"},
            "explanation": {"type": "string"},
            "rubric": {"type": "string"},
            "subquestions": {"type": "array", "items": subquestion_level3_schema},
        },
        "required": [
            "id",
            "type",
            "question",
            "points",
            "options",
            "allowMultipleCorrect",
            "multipleCorrectAnswers",
            "hasCode",
            "hasDiagram",
            "codeLanguage",
            "outputType",
            "rubricType",
            "code",
            "equations",
            "diagram",
            "optionalParts",
            "requiredPartsCount",
            "correctAnswer",
            "explanation",
            "rubric",
            "subquestions",
        ],
        "additionalProperties": False,
    }

    # Build base question schema
    base_question_schema = {
        "type": "object",
        "properties": {
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
            "rubricType": {"type": "string", "enum": ["per-subquestion", "overall"]},
            "code": {"type": "string"},
            "equations": {
                "type": "array",
                "items": equation_schema,
                "description": "Mathematical equations with their character positions in question text",
            },
            "diagram": diagram_schema,
            "optionalParts": {"type": "boolean"},
            "requiredPartsCount": {"type": "integer"},
            "correctAnswer": {"type": "string"},
            "explanation": {"type": "string"},
            "rubric": {"type": "string"},
            "subquestions": {"type": "array", "items": subquestion_level2_schema},
        },
        "required": [
            "id",
            "type",
            "question",
            "points",
            "difficulty",
            "options",
            "allowMultipleCorrect",
            "multipleCorrectAnswers",
            "order",
            "hasCode",
            "hasDiagram",
            "codeLanguage",
            "outputType",
            "rubricType",
            "code",
            "equations",
            "diagram",
            "optionalParts",
            "requiredPartsCount",
            "correctAnswer",
            "explanation",
            "rubric",
            "subquestions",
        ],
        "additionalProperties": False,
    }

    # Create the full parsing schema with additional fields
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "questions": {"type": "array", "items": base_question_schema},
            "total_points": {"type": "number"},
        },
        "required": ["title", "description", "questions", "total_points"],
        "additionalProperties": False,
    }

    return schema
