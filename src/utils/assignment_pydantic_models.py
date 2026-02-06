"""
Pydantic models for assignment parsing structured output.
These models are used with OpenAI's Responses API for type-safe structured output.
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class EquationPosition(BaseModel):
    """Position information for an equation within the question structure."""

    char_index: int = Field(
        description="Character count in text after which equation appears"
    )
    context: Literal["question_text", "options", "correctAnswer", "rubric"] = Field(
        description="Where in the question structure this equation appears"
    )


class Equation(BaseModel):
    """Mathematical equation with its character position."""

    id: str = Field(description="Unique equation identifier, e.g., q1_eq1")
    latex: str = Field(description="LaTeX representation of the equation")
    position: EquationPosition = Field(description="Position of the equation")
    type: Literal["inline", "display"] = Field(
        description="Whether equation is inline with text or display block"
    )


class DiagramNoBbox(BaseModel):
    """Diagram reference without bounding box (used in Step 1)."""

    page_number: int = Field(description="Page number where diagram appears")
    caption: str = Field(
        default="", description="Caption or description of the diagram"
    )


class SubquestionLevel3(BaseModel):
    """Deepest level subquestion (no further nesting)."""

    id: int = Field(description="Unique question identifier")
    type: Literal[
        "multiple-choice",
        "fill-blank",
        "short-answer",
        "numerical",
        "true-false",
        "code-writing",
        "diagram-analysis",
    ] = Field(description="Question type")
    question: str = Field(description="Question text with equation placeholders")
    points: float = Field(default=0, description="Points/marks for this question")
    options: List[str] = Field(default_factory=list, description="Options for MCQ")
    allowMultipleCorrect: bool = Field(
        default=False, description="Whether multiple options can be correct"
    )
    multipleCorrectAnswers: List[str] = Field(
        default_factory=list, description="List of correct answers if multiple"
    )
    hasCode: bool = Field(default=False, description="Whether question involves code")
    hasDiagram: bool = Field(
        default=False, description="Whether question has a diagram"
    )
    codeLanguage: str = Field(
        default="", description="Programming language if code question"
    )
    outputType: str = Field(default="", description="Expected output type")
    rubricType: Literal["overall"] = Field(default="overall", description="Rubric type")
    code: str = Field(default="", description="Code content if applicable")
    equations: List[Equation] = Field(
        default_factory=list, description="Mathematical equations"
    )
    diagram: Optional[DiagramNoBbox] = Field(
        default=None, description="Diagram reference"
    )
    optionalParts: bool = Field(
        default=False, description="Whether parts are optional (OR alternatives)"
    )
    requiredPartsCount: int = Field(
        default=0, description="Number of parts student must answer"
    )
    correctAnswer: str = Field(
        default="", description="Correct answer if present in document"
    )
    explanation: str = Field(default="", description="Explanation if present")
    rubric: str = Field(default="", description="Grading rubric if present")


class SubquestionLevel2(BaseModel):
    """Second level subquestion (can contain level 3 subquestions)."""

    id: int = Field(description="Unique question identifier")
    type: Literal[
        "multiple-choice",
        "fill-blank",
        "short-answer",
        "numerical",
        "true-false",
        "code-writing",
        "diagram-analysis",
        "multi-part",
    ] = Field(description="Question type")
    question: str = Field(description="Question text with equation placeholders")
    points: float = Field(default=0, description="Points/marks for this question")
    options: List[str] = Field(default_factory=list, description="Options for MCQ")
    allowMultipleCorrect: bool = Field(
        default=False, description="Whether multiple options can be correct"
    )
    multipleCorrectAnswers: List[str] = Field(
        default_factory=list, description="List of correct answers if multiple"
    )
    hasCode: bool = Field(default=False, description="Whether question involves code")
    hasDiagram: bool = Field(
        default=False, description="Whether question has a diagram"
    )
    codeLanguage: str = Field(
        default="", description="Programming language if code question"
    )
    outputType: str = Field(default="", description="Expected output type")
    rubricType: Literal["per-subquestion", "overall"] = Field(
        default="overall", description="Rubric type"
    )
    code: str = Field(default="", description="Code content if applicable")
    equations: List[Equation] = Field(
        default_factory=list, description="Mathematical equations"
    )
    diagram: Optional[DiagramNoBbox] = Field(
        default=None, description="Diagram reference"
    )
    optionalParts: bool = Field(
        default=False, description="Whether parts are optional (OR alternatives)"
    )
    requiredPartsCount: int = Field(
        default=0, description="Number of parts student must answer"
    )
    correctAnswer: str = Field(
        default="", description="Correct answer if present in document"
    )
    explanation: str = Field(default="", description="Explanation if present")
    rubric: str = Field(default="", description="Grading rubric if present")
    subquestions: List[SubquestionLevel3] = Field(
        default_factory=list, description="Nested subquestions"
    )


class Question(BaseModel):
    """Top-level question with full nesting support."""

    id: int = Field(description="Unique question identifier")
    type: Literal[
        "multiple-choice",
        "fill-blank",
        "short-answer",
        "numerical",
        "long-answer",
        "true-false",
        "code-writing",
        "diagram-analysis",
        "multi-part",
    ] = Field(description="Question type")
    question: str = Field(description="Question text with equation placeholders")
    points: float = Field(default=0, description="Points/marks for this question")
    difficulty: Literal["easy", "medium", "hard"] = Field(
        default="medium", description="Question difficulty"
    )
    options: List[str] = Field(default_factory=list, description="Options for MCQ")
    allowMultipleCorrect: bool = Field(
        default=False, description="Whether multiple options can be correct"
    )
    multipleCorrectAnswers: List[str] = Field(
        default_factory=list, description="List of correct answers if multiple"
    )
    order: int = Field(default=0, description="Question order in assignment")
    hasCode: bool = Field(default=False, description="Whether question involves code")
    hasDiagram: bool = Field(
        default=False, description="Whether question has a diagram"
    )
    codeLanguage: str = Field(
        default="", description="Programming language if code question"
    )
    outputType: str = Field(default="", description="Expected output type")
    rubricType: Literal["per-subquestion", "overall"] = Field(
        default="overall", description="Rubric type"
    )
    code: str = Field(default="", description="Code content if applicable")
    equations: List[Equation] = Field(
        default_factory=list, description="Mathematical equations"
    )
    diagram: Optional[DiagramNoBbox] = Field(
        default=None, description="Diagram reference"
    )
    optionalParts: bool = Field(
        default=False, description="Whether parts are optional (OR alternatives)"
    )
    requiredPartsCount: int = Field(
        default=0, description="Number of parts student must answer"
    )
    correctAnswer: str = Field(
        default="", description="Correct answer if present in document"
    )
    explanation: str = Field(default="", description="Explanation if present")
    rubric: str = Field(default="", description="Grading rubric if present")
    subquestions: List[SubquestionLevel2] = Field(
        default_factory=list, description="Nested subquestions"
    )


class AssignmentParsingResponse(BaseModel):
    """Complete assignment parsing response with all extracted content."""

    title: str = Field(description="Assignment title extracted from document")
    description: str = Field(
        default="", description="Assignment description if present"
    )
    questions: List[Question] = Field(
        default_factory=list, description="List of extracted questions"
    )
    total_points: float = Field(
        default=0, description="Total points for the assignment"
    )


class AssignmentGenerationResponse(BaseModel):
    """Complete assignment generation response with all generated content."""

    questions: List[Question] = Field(
        default_factory=list, description="List of generated questions"
    )


# ============================================================================
# GENERATION-SPECIFIC MODELS (without equations, optimized for token usage)
# ============================================================================


class SubquestionLevel3Generation(BaseModel):
    """Deepest level subquestion for GENERATION (no equations, no multi-part)."""

    id: int = Field(description="Unique question identifier")
    type: Literal[
        "multiple-choice",
        "short-answer",
        "numerical",
        "true-false",
        "code-writing",
        "diagram-analysis",
    ] = Field(description="Question type (multi-part not allowed at this level)")
    question: str = Field(description="Question text")
    points: float = Field(default=0, description="Points/marks for this question")
    options: List[str] = Field(default_factory=list, description="Options for MCQ")
    allowMultipleCorrect: bool = Field(
        default=False, description="Whether multiple options can be correct"
    )
    multipleCorrectAnswers: List[str] = Field(
        default_factory=list, description="List of correct answers if multiple"
    )
    hasCode: bool = Field(default=False, description="Whether question involves code")
    hasDiagram: bool = Field(
        default=False, description="Whether question has a diagram"
    )
    codeLanguage: str = Field(
        default="", description="Programming language if code question"
    )
    outputType: str = Field(default="", description="Expected output type")
    rubricType: Literal["overall"] = Field(default="overall", description="Rubric type")
    code: str = Field(default="", description="Code content if applicable")
    diagram: Optional[DiagramNoBbox] = Field(
        default=None, description="Diagram reference"
    )
    optionalParts: bool = Field(
        default=False, description="Whether parts are optional (OR alternatives)"
    )
    requiredPartsCount: int = Field(
        default=0, description="Number of parts student must answer"
    )
    correctAnswer: str = Field(
        default="", description="Correct answer if present in document"
    )
    explanation: str = Field(default="", description="Explanation if present")
    rubric: str = Field(default="", description="Grading rubric if present")


class SubquestionLevel2Generation(BaseModel):
    """Second level subquestion for GENERATION (no equations, can nest Level 3)."""

    id: int = Field(description="Unique question identifier")
    type: Literal[
        "multiple-choice",
        "short-answer",
        "numerical",
        "true-false",
        "code-writing",
        "diagram-analysis",
        "multi-part",
    ] = Field(description="Question type")
    question: str = Field(description="Question text")
    points: float = Field(default=0, description="Points/marks for this question")
    options: List[str] = Field(default_factory=list, description="Options for MCQ")
    allowMultipleCorrect: bool = Field(
        default=False, description="Whether multiple options can be correct"
    )
    multipleCorrectAnswers: List[str] = Field(
        default_factory=list, description="List of correct answers if multiple"
    )
    hasCode: bool = Field(default=False, description="Whether question involves code")
    hasDiagram: bool = Field(
        default=False, description="Whether question has a diagram"
    )
    codeLanguage: str = Field(
        default="", description="Programming language if code question"
    )
    outputType: str = Field(default="", description="Expected output type")
    rubricType: Literal["per-subquestion", "overall"] = Field(
        default="overall", description="Rubric type"
    )
    code: str = Field(default="", description="Code content if applicable")
    diagram: Optional[DiagramNoBbox] = Field(
        default=None, description="Diagram reference"
    )
    optionalParts: bool = Field(
        default=False, description="Whether parts are optional (OR alternatives)"
    )
    requiredPartsCount: int = Field(
        default=0, description="Number of parts student must answer"
    )
    correctAnswer: str = Field(
        default="", description="Correct answer if present in document"
    )
    explanation: str = Field(default="", description="Explanation if present")
    rubric: str = Field(default="", description="Grading rubric if present")
    subquestions: List[SubquestionLevel3Generation] = Field(
        default_factory=list, description="Nested subquestions (Level 3 only)"
    )


class QuestionGenerationFlat(BaseModel):
    """Top-level question for GENERATION without multi-part support (no equations, no subquestions)."""

    id: int = Field(description="Unique question identifier")
    type: Literal[
        "multiple-choice",
        "short-answer",
        "numerical",
        "long-answer",
        "true-false",
        "code-writing",
        "diagram-analysis",
    ] = Field(description="Question type (multi-part not included)")
    question: str = Field(description="Question text")
    points: float = Field(default=0, description="Points/marks for this question")
    difficulty: Literal["easy", "medium", "hard"] = Field(
        default="medium", description="Question difficulty"
    )
    options: List[str] = Field(default_factory=list, description="Options for MCQ")
    allowMultipleCorrect: bool = Field(
        default=False, description="Whether multiple options can be correct"
    )
    multipleCorrectAnswers: List[str] = Field(
        default_factory=list, description="List of correct answers if multiple"
    )
    order: int = Field(default=0, description="Question order in assignment")
    hasCode: bool = Field(default=False, description="Whether question involves code")
    hasDiagram: bool = Field(
        default=False, description="Whether question has a diagram"
    )
    codeLanguage: str = Field(
        default="", description="Programming language if code question"
    )
    outputType: str = Field(default="", description="Expected output type")
    rubricType: Literal["overall"] = Field(
        default="overall", description="Rubric type (no per-subquestion for flat)"
    )
    code: str = Field(default="", description="Code content if applicable")
    diagram: Optional[DiagramNoBbox] = Field(
        default=None, description="Diagram reference"
    )
    optionalParts: bool = Field(
        default=False, description="Whether parts are optional (OR alternatives)"
    )
    requiredPartsCount: int = Field(
        default=0, description="Number of parts student must answer"
    )
    correctAnswer: str = Field(
        default="", description="Correct answer if present in document"
    )
    explanation: str = Field(default="", description="Explanation if present")
    rubric: str = Field(default="", description="Grading rubric if present")


class QuestionGenerationNested(BaseModel):
    """Top-level question for GENERATION with multi-part support (no equations, has subquestions)."""

    id: int = Field(description="Unique question identifier")
    type: Literal[
        "multiple-choice",
        "short-answer",
        "numerical",
        "long-answer",
        "true-false",
        "code-writing",
        "diagram-analysis",
        "multi-part",
    ] = Field(description="Question type")
    question: str = Field(description="Question text")
    points: float = Field(default=0, description="Points/marks for this question")
    difficulty: Literal["easy", "medium", "hard"] = Field(
        default="medium", description="Question difficulty"
    )
    options: List[str] = Field(default_factory=list, description="Options for MCQ")
    allowMultipleCorrect: bool = Field(
        default=False, description="Whether multiple options can be correct"
    )
    multipleCorrectAnswers: List[str] = Field(
        default_factory=list, description="List of correct answers if multiple"
    )
    order: int = Field(default=0, description="Question order in assignment")
    hasCode: bool = Field(default=False, description="Whether question involves code")
    hasDiagram: bool = Field(
        default=False, description="Whether question has a diagram"
    )
    codeLanguage: str = Field(
        default="", description="Programming language if code question"
    )
    outputType: str = Field(default="", description="Expected output type")
    rubricType: Literal["per-subquestion", "overall"] = Field(
        default="overall", description="Rubric type"
    )
    code: str = Field(default="", description="Code content if applicable")
    diagram: Optional[DiagramNoBbox] = Field(
        default=None, description="Diagram reference"
    )
    optionalParts: bool = Field(
        default=False, description="Whether parts are optional (OR alternatives)"
    )
    requiredPartsCount: int = Field(
        default=0, description="Number of parts student must answer"
    )
    correctAnswer: str = Field(
        default="", description="Correct answer if present in document"
    )
    explanation: str = Field(default="", description="Explanation if present")
    rubric: str = Field(default="", description="Grading rubric if present")
    subquestions: List[SubquestionLevel2Generation] = Field(
        default_factory=list, description="Nested subquestions"
    )


class AssignmentGenerationResponseFlat(BaseModel):
    """Assignment generation response for flat questions (no multi-part)."""

    questions: List[QuestionGenerationFlat] = Field(
        default_factory=list, description="List of generated flat questions"
    )


class AssignmentGenerationResponseNested(BaseModel):
    """Assignment generation response with multi-part support."""

    questions: List[QuestionGenerationNested] = Field(
        default_factory=list,
        description="List of generated questions (may include multi-part)",
    )
