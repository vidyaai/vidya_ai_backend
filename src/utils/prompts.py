"""
Prompts for document processing and assignment parsing.
"""

# System prompt for document parsing
DOCUMENT_PARSER_SYSTEM_PROMPT = """You are an expert document parser. Your task is to extract existing assignment questions from documents and structure them properly for import into an assignment system. Do not create new questions - only extract what already exists in the document."""

# Fallback system prompt for reduced content parsing
FALLBACK_PARSER_SYSTEM_PROMPT = """Extract assignment questions concisely. Keep responses brief to avoid token limits."""


def create_extraction_prompt(document_text: str, file_name: str) -> str:
    """Create a detailed prompt for extracting existing assignment questions from documents"""

    # Truncate document text if too long (keep within token limits)
    # Increased limit to allow for larger documents while leaving room for response
    max_doc_length = (
        20000  # Characters, roughly 5000 tokens - more space for extraction
    )
    if len(document_text) > max_doc_length:
        document_text = document_text[:max_doc_length] + "... [document truncated]"

    prompt = f"""
Please analyze the following document and extract all existing assignment questions, exercises, problems, or assessment items.

Document filename: {file_name}

Document content:
---
{document_text}
---

Instructions:
1. EXTRACT existing questions/problems from the document - do NOT create new ones
2. Map question types to these EXACT frontend types:
   - multiple-choice: Questions with multiple options (A, B, C, D or 1, 2, 3, 4)
   - fill-blank: Questions with blanks to fill in (e.g., "The capital of France is ___")
   - short-answer: Brief written responses (1-2 sentences)
   - numerical: Questions requiring numeric answers
   - long-answer: Extended written responses (paragraphs)
   - true-false: Binary true/false questions
   - code-writing: Questions requiring code solutions
   - diagram-analysis: Questions involving diagram interpretation
   - multi-part: Questions with sub-parts (a, b, c) or (i, ii, iii)
3. Extract the exact question text as written in the document
4. For multiple choice questions, extract all provided options. If not explicitly provided, extract options from the question text or code block.
5. Extract any provided correct answers, solutions, or answer keys
6. Extract any point values or scoring information mentioned
7. Extract any grading rubrics or evaluation criteria
8. Maintain the original question numbering/ordering if present
9. If no explicit questions are found, look for exercises, problems, or tasks that could be converted to questions
10. Extract the assignment title and description if present in the document

IMPORTANT: Keep your response concise but complete. Focus on extracting the essential information without unnecessary verbosity.

Return your response as a JSON object with the following structure:
{{
    "title": "Assignment title from document or based on filename",
    "description": "Assignment description if found in document",
    "questions": [
        {{
            "id": 1,
            "type": "multiple-choice|fill-blank|short-answer|numerical|long-answer|true-false|code-writing|diagram-analysis|multi-part",
            "question": "Exact question text from document",
            "options": ["Option A", "Option B", "Option C", "Option D"],
            "correctAnswer": "Correct answer if provided in document",
            "points": 5,
            "rubric": "Grading criteria if provided in document",
            "order": 1,
            "hasCode": true/false,
            "hasDiagram": true/false,
            "codeLanguage": "python|javascript|java|etc",
            "outputType": "expected output format",
            "analysisType": "diagram analysis type",
            "rubricType": "points|criteria",
            "code": "code block if question has code",
            "subquestions": [
                {{
                    "id": 1,
                    "type": "sub_question_type",
                    "question": "Sub-question text",
                    "points": 2,
                    "options": [],
                    "correctAnswer": "sub_answer",
                    "rubric": "sub_rubric",
                    "hasCode": true/false,
                    "hasDiagram": true/false,
                    "codeLanguage": "sub_language_if_code",
                    "outputType": "sub_output_format",
                    "analysisType": "sub_analysis_type",
                    "rubricType": "sub_rubric_type",
                    "code": "sub_code_if_present"
                }}
            ]
        }}
    ],
    "source_info": {{
        "questions_found": 5,
        "has_answer_key": true,
        "has_rubrics": false,
        "document_type": "assignment|exam|quiz|homework|exercise"
    }},
    "total_points": 25
}}

Important:
- If the document doesn't contain clear assignment questions, return an empty questions array
- Only extract what actually exists in the document
- Preserve the original wording and structure as much as possible
- Make sure the JSON is valid and follows this exact structure
- Keep responses concise to avoid token limits
"""
    return prompt


def create_fallback_prompt(document_text: str, file_name: str) -> str:
    """Create a simpler prompt for reduced content parsing"""
    prompt = f"""
Extract assignment questions from this document. Keep response concise.

Document: {file_name}
Content: {document_text}

Return JSON with this structure:
{{
    "title": "Assignment title",
    "description": "Brief description",
    "questions": [
        {{
            "id": 1,
            "type": "multiple-choice|short-answer|long-answer|numerical|true-false|fill-blank|code-writing|multi-part",
            "question": "Question text",
            "options": ["A", "B", "C", "D"],
            "correctAnswer": "Answer if provided",
            "points": 5,
            "rubric": "Grading criteria if provided",
            "order": 1,
            "hasCode": false,
            "hasDiagram": false,
            "codeLanguage": "",
            "outputType": "",
            "analysisType": "",
            "rubricType": "points",
            "code": "",
            "subquestions": []
        }}
    ],
    "total_points": 25
}}
"""
    return prompt
