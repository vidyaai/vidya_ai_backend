"""
Prompts for document processing and assignment parsing.
"""

# System prompt for document parsing
from typing import List


DOCUMENT_PARSER_SYSTEM_PROMPT = """
    You are an expert document parser specializing in extracting assignment questions from educational documents. Your task is to identify and extract existing questions, exercises, problems, or assessment items from documents and structure them according to the provided JSON schema.

    Key guidelines:
    - EXTRACT only what already exists in the document - do NOT create new questions
    - Preserve the original wording and structure as much as possible
    - Map question types to the exact schema types provided
    - Extract all relevant metadata (points, rubrics, correct answers, etc.)
    - For multi-part questions, properly structure subquestions
    - Identify code content and diagram requirements accurately

    DIAGRAM IDENTIFICATION CRITICAL RULES:
    When processing documents with diagrams/images, you must carefully determine which question or sub-question each diagram belongs to:

    1. SPATIAL ANALYSIS: Analyze the position of diagrams relative to question text
    2. TEXTUAL REFERENCES: Look for explicit mentions like "see diagram", "refer to figure", "using the image"
    3. LOGICAL ASSOCIATION: Determine if the diagram supports the entire question or just a specific sub-part
    4. HIERARCHY PRECEDENCE: When uncertain, associate diagrams with the most specific question/sub-question that references them
    5. MULTI-PART CONSIDERATION: For questions with sub-parts, determine if diagrams apply to the whole question or individual sub-questions

    This ensures accurate diagram-question relationships for proper educational content structure.
"""


def get_question_extraction_prompt(
    file_name: str,
    file_type: str,
    images: List[str],
    document_text: str,
    s3_urls_info: str,
) -> str:
    match file_type:
        case "application/pdf":
            diagram_metadata_prompt_body = DIAGRAM_METADATA_PROMPT_PDF
            return (
                QUESTION_EXTRACTION_PROMPT_HEADER_PDF.format(
                    file_name=file_name, images=images
                )
                + QUESTION_EXTRACTION_PROMPT_BODY_1
                + QUESTION_EXTRACTION_PROMPT_BODY_2.format(
                    diagram_metadata_prompt_body=diagram_metadata_prompt_body
                )
                + QUESTION_EXTRACTION_PROMPT_BODY_3
            )

        case "text/plain":
            return (
                QUESTION_EXTRACTION_PROMPT_HEADER_TXT.format(
                    file_name=file_name, document_text=document_text
                )
                + QUESTION_EXTRACTION_PROMPT_BODY_1
                + QUESTION_EXTRACTION_PROMPT_BODY_3
            )

        case "text/markdown" | "text/html" | "text/csv" | "application/json":
            diagram_metadata_prompt_body = DIAGRAM_METADATA_PROMPT_MD_HTML_CSV_JSON
            return (
                QUESTION_EXTRACTION_PROMPT_HEADER_MD_HTML_CSV_JSON.format(
                    file_name=file_name,
                    file_type=file_type,
                    s3_urls_info=s3_urls_info,
                    document_text=document_text,
                )
                + QUESTION_EXTRACTION_PROMPT_BODY_1
                + QUESTION_EXTRACTION_PROMPT_BODY_2.format(
                    diagram_metadata_prompt_body=diagram_metadata_prompt_body
                )
                + QUESTION_EXTRACTION_PROMPT_BODY_3
            )

        case "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            diagram_metadata_prompt_body = DIAGRAM_METADATA_PROMPT_DOCX
            return (
                QUESTION_EXTRACTION_PROMPT_HEADER_DOCX.format(
                    file_name=file_name, images_info=images, document_text=document_text
                )
                + QUESTION_EXTRACTION_PROMPT_BODY_1
                + QUESTION_EXTRACTION_PROMPT_BODY_2.format(
                    diagram_metadata_prompt_body=diagram_metadata_prompt_body
                )
                + QUESTION_EXTRACTION_PROMPT_BODY_3
            )

        case _:
            raise ValueError(f"Unsupported file type: {file_type}")


QUESTION_EXTRACTION_PROMPT_HEADER_PDF = """
    Analyze the following {len(images)}-page PDF document and extract ALL existing assignment questions, exercises, problems, or assessment items.
    Document: {file_name}
"""

QUESTION_EXTRACTION_PROMPT_HEADER_TXT = """
    Analyze the following text document and extract ALL existing assignment questions.
    Document: {file_name}
    Content:
    ---
    {document_text}
    ---
"""

QUESTION_EXTRACTION_PROMPT_HEADER_MD_HTML_CSV_JSON = """
    Analyze the following document and extract ALL existing assignment questions.

    Document: {file_name}
    Type: {file_type}

    Detected S3 URLs in content:
    {s3_urls_info}

    Content:
    ---
    {document_text}
    ---
"""

QUESTION_EXTRACTION_PROMPT_HEADER_DOCX = """
    Analyze the following DOCX document and extract ALL existing assignment questions.

    Document: {file_name}

    Extracted images (already uploaded to S3):
    {images_info}

    Content:
    ---
    {document_text}
    ---
"""

QUESTION_EXTRACTION_PROMPT_BODY_1 = """
    - EXTRACT only existing questions - do NOT create new ones
    - Preserve exact question text as written in the document
    - Set question type appropriately:
        -- multiple-choice: Questions with options (A, B, C, D or 1, 2, 3, 4)
        -- fill-blank: Questions with blanks (e.g., "The capital of France is ___")
        -- short-answer: Brief responses (1-2 sentences)
        -- numerical: Questions requiring numeric answers
        -- long-answer: Extended written responses (paragraphs)
        -- true-false: Binary true/false questions
        -- code-writing: Questions requiring code solutions
        -- diagram-analysis: Questions involving diagram interpretation
        -- multi-part: Questions with sub-parts (a, b, c) or (i, ii, iii)
"""

QUESTION_EXTRACTION_PROMPT_BODY_2 = """
    - DIAGRAM IDENTIFICATION AND ASSOCIATION: When identifying diagrams/images, carefully determine which question or sub-question they belong to:
        -- DIAGRAM BELONGS TO MAIN QUESTION if:
            --- The diagram appears before or immediately after the main question text
            --- The diagram is referenced in the main question text (e.g., "Refer to the diagram below", "Using the figure shown")
            --- The diagram is positioned between the main question and its sub-questions
            --- The diagram is clearly associated with the overall question concept
        -- DIAGRAM BELONGS TO SUB-QUESTION if:
            --- The diagram appears immediately before or after a specific sub-question (a, b, c, etc.)
            --- The diagram is referenced only in that specific sub-question text
            --- The diagram is positioned between sub-questions
            --- The diagram is clearly associated with only that sub-question's content
        -- DIAGRAM ASSOCIATION RULES:
            --- Analyze the spatial relationship between diagrams and text
            --- Look for explicit references in question text ("see diagram", "refer to figure", etc.)
            --- Consider the logical flow: diagram → question or question → diagram
            --- For multi-part questions, determine if diagram applies to entire question or specific sub-part
            --- If uncertain, prefer associating with the most specific question/sub-question that references it
        {diagram_metadata_prompt_body}
"""

DIAGRAM_METADATA_PROMPT_PDF = """
        -- DIAGRAM METADATA:
            --- Set hasDiagram: true for the appropriate question/sub-question
            --- Provide diagram metadata in the "diagram" field with:
                ---- page_number: Page where diagram appears (1-indexed)
                ---- caption: Descriptive label or caption for the diagram
"""

DIAGRAM_METADATA_PROMPT_MD_HTML_CSV_JSON = """
        -- DIAGRAM METADATA:
           --- Set hasDiagram: true for the appropriate question/sub-question
           --- For diagrams: If a question/sub-question references an S3 URL (image), set:
                ---- hasDiagram: true
                ---- diagram.s3_key: null
                ---- diagram.s3_url: the full S3 URL
                ---- diagram.caption: description of the image
"""

DIAGRAM_METADATA_PROMPT_DOCX = """
        -- DIAGRAM METADATA:
            --- Set hasDiagram: true for the appropriate question/sub-question
            --- For diagrams/images in the document set folllowing for the appropriate question/sub-question:
                ---- hasDiagram: true
                ---- diagram.s3_key: use the s3_key from extracted images list above
                ---- diagram.s3_url: null
                ---- diagram.caption: description of the image
"""

QUESTION_EXTRACTION_PROMPT_BODY_3 = """
    - Extract following information:
        -- Question text (without question numbers or marks)
        -- Multiple choice options (without option letters/numbers)
        -- Correct answers or solutions (DO generate if not present in the document)
            --- For multiple choice: correctAnswer should be index string ("0", "1", "2", "3")
            --- For multi-part: provide empty string for correctAnswer (provide answers in subquestions)
        -- Point values
        -- Grading rubrics (DO generate if not present in the document)
        -- Assignment title and description
    - Multi-part questions:
        -- Use type "multi-part"
        -- Structure subquestions properly
        -- rubricType: "per-subquestion"
        -- Main question rubric not required, but required for all non-multi-part subquestions
        -- if sub-question is multi-part, set rubricType: "per-subquestion" for the sub-question
        -- if sub-question is not multi-part, set rubricType: "overall" for the sub-question
        -- remember to set rubric for each sub-question and sub-sub-questions
        -- Apply diagram association rules to determine if diagrams belong to main question or specific sub-questions
    - Regular questions:
        -- rubricType: "overall"
        -- rubric is required
    - Code content:
        -- Set hasCode: true
        -- Specify codeLanguage
        -- Extract code in the code field
    Return the structured data according to the JSON schema.
"""
