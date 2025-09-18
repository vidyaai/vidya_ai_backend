"""
Prompts for document processing and assignment parsing.
"""

# System prompt for document parsing
from controllers.config import logger


DOCUMENT_PARSER_SYSTEM_PROMPT = """You are an expert document parser specializing in extracting assignment questions from educational documents. Your task is to identify and extract existing questions, exercises, problems, or assessment items from documents and structure them according to the provided JSON schema.

Key guidelines:
- EXTRACT only what already exists in the document - do NOT create new questions
- Preserve the original wording and structure as much as possible
- Map question types to the exact schema types provided
- Extract all relevant metadata (points, rubrics, correct answers, etc.)
- For multi-part questions, properly structure subquestions
- Identify code content and diagram requirements accurately"""

# Fallback system prompt for reduced content parsing
FALLBACK_PARSER_SYSTEM_PROMPT = """You are a document parser extracting assignment questions from educational content. Focus on identifying key questions and structure them according to the provided JSON schema. Keep responses concise due to token limits."""


def create_extraction_prompt(document_text: str, file_name: str) -> str:
    """Create a detailed prompt for extracting existing assignment questions from documents"""

    # Truncate document text if too long (keep within token limits)
    # Increased limit to allow for larger documents while leaving room for response
    max_doc_length = (
        20000  # Characters, roughly 5000 tokens - more space for extraction
    )
    if len(document_text) > max_doc_length:
        logger.warning(
            f"Document text is too long, truncating to {max_doc_length} characters"
        )
        document_text = document_text[:max_doc_length] + "... [document truncated]"

    prompt = f"""
Analyze the following document and extract all existing assignment questions, exercises, problems, or assessment items.

Document: {file_name}

Content:
---
{document_text}
---

Extraction guidelines:
1. EXTRACT only existing questions - do NOT create new ones
2. Map question types to schema types:
   - multiple-choice: Questions with options (A, B, C, D or 1, 2, 3, 4)
   - fill-blank: Questions with blanks (e.g., "The capital of France is ___")
   - short-answer: Brief responses (1-2 sentences)
   - numerical: Questions requiring numeric answers
   - long-answer: Extended written responses (paragraphs)
   - true-false: Binary true/false questions
   - code-writing: Questions requiring code solutions
   - diagram-analysis: Questions involving diagram interpretation
   - multi-part: Questions with sub-parts (a, b, c) or (i, ii, iii)

3. Extract all provided information:
   - Exact question text as written
   - Multiple choice options (infer if not explicit)
   - Correct answers, solutions, or answer keys (if not present, generate if possible)
   - Point values and scoring information
   - Grading rubrics or evaluation criteria (if not present, generate if possible)
   - Assignment title and description

4. For multi-part questions, structure subquestions properly
5. Identify code content and set hasCode/codeLanguage appropriately
6. Identify diagram requirements and set hasDiagram/analysisType appropriately

Rubric requirements:
- rubricType: "overall" for non-multi-part questions, "per-subquestion" for multi-part questions
- If rubricType is "overall": rubric is required (generate if not present)
- If rubricType is "per-subquestion": rubric not required for main question, but required for all non-multi-part subquestions

Note: The response will be automatically structured according to the provided JSON schema. Focus on accurate extraction rather than formatting.
"""
    return prompt


def create_fallback_prompt(document_text: str, file_name: str) -> str:
    """Create a simpler prompt for reduced content parsing"""
    prompt = f"""
Extract assignment questions from this document. Focus on key questions due to token limits.

Document: {file_name}
Content: {document_text}

Extract:
- Assignment title and description
- Questions with their types, text, points, and answers (if not present, generate if possible)
- Code content and diagram requirements
- Multi-part question structure

Rubric rules:
- rubricType: "overall" for non-multi-part, "per-subquestion" for multi-part
- "overall": rubric required
- "per-subquestion": rubric not required for main question, required for non-multi-part subquestions

The response will be automatically structured according to the provided JSON schema.
"""
    return prompt
