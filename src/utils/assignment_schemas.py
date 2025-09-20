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

    # Define the base question schema that can be reused
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
            "correctAnswer": {"type": "string"},
            "allowMultipleCorrect": {"type": "boolean"},
            "multipleCorrectAnswers": {"type": "array", "items": {"type": "string"}},
            "explanation": {"type": "string"},
            "rubric": {"type": "string"},
            "order": {"type": "integer"},
            "hasCode": {"type": "boolean"},
            "hasDiagram": {"type": "boolean"},
            "codeLanguage": {"type": "string"},
            "outputType": {"type": "string"},
            "analysisType": {"type": "string"},
            "rubricType": {
                "type": "string",
                "enum": ["per-subquestion", "overall"],
            },
            "code": {"type": "string"},
            "subquestions": {
                "type": "array",
                "items": {
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
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "correctAnswer": {"type": "string"},
                        "allowMultipleCorrect": {"type": "boolean"},
                        "multipleCorrectAnswers": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "explanation": {"type": "string"},
                        "rubric": {"type": "string"},
                        "hasCode": {"type": "boolean"},
                        "hasDiagram": {"type": "boolean"},
                        "codeLanguage": {"type": "string"},
                        "outputType": {"type": "string"},
                        "analysisType": {"type": "string"},
                        "rubricType": {
                            "type": "string",
                            "enum": ["per-subquestion", "overall"],
                        },
                        "code": {"type": "string"},
                        "subquestions": {
                            "type": "array",
                            "items": {
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
                                    "options": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "correctAnswer": {"type": "string"},
                                    "allowMultipleCorrect": {"type": "boolean"},
                                    "multipleCorrectAnswers": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "explanation": {"type": "string"},
                                    "rubric": {"type": "string"},
                                    "hasCode": {"type": "boolean"},
                                    "hasDiagram": {"type": "boolean"},
                                    "codeLanguage": {"type": "string"},
                                    "outputType": {"type": "string"},
                                    "analysisType": {"type": "string"},
                                    "rubricType": {
                                        "type": "string",
                                        "enum": ["overall"],
                                    },
                                    "code": {"type": "string"},
                                },
                                "required": [
                                    "id",
                                    "type",
                                    "question",
                                    "points",
                                    "correctAnswer",
                                    "explanation",
                                    "rubric",
                                ],
                            },
                        },
                    },
                    "required": [
                        "id",
                        "type",
                        "question",
                        "points",
                        "correctAnswer",
                        "explanation",
                    ],
                },
            },
        },
        "required": [
            "id",
            "type",
            "question",
            "points",
            "difficulty",
            "correctAnswer",
            "explanation",
        ],
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
