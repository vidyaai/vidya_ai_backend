"""
Prompts for document processing and assignment parsing.
"""

# System prompt for document parsing
from typing import List

from controllers.config import logger


DOCUMENT_PARSER_SYSTEM_PROMPT = """
    You are an expert document parser specializing in extracting assignment questions from educational documents. Your task is to identify and extract existing questions, exercises, problems, or assessment items from documents and structure them according to the provided JSON schema.

    Key guidelines:
    - EXTRACT only what already exists in the document - do NOT create new questions
    - Preserve the original wording and structure as much as possible
    - Map question types to the exact schema types provided
    - Extract all relevant metadata (points, rubrics, correct answers, etc.)
    - For multi-part questions, properly structure subquestions
    - Identify code content and diagram requirements accurately

    EQUATION EXTRACTION CRITICAL RULES:
    When processing documents with mathematical equations or formulas:
    1. EXTRACT equations as LaTeX format using standard delimiters:
       - Use $...$ for inline equations (e.g., $E = mc^2$)
       - Use $$...$$ for display equations (e.g., $$\\int_0^\\infty e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}$$)
    2. PRESERVE equations exactly as they appear in the document, converting to LaTeX syntax
    3. INCLUDE equations in question text, options, answers, and rubrics where they appear
    4. MAINTAIN mathematical notation accuracy - ensure all symbols, subscripts, superscripts are correctly converted
    5. If equations are detected in images or visual format, extract them as LaTeX from the visual representation

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
    try:
        match file_type:
            case "application/pdf":
                diagram_metadata_prompt_body = DIAGRAM_METADATA_PROMPT_PDF
                images_count = len(images) if images else 0
                return (
                    QUESTION_EXTRACTION_PROMPT_HEADER_PDF.format(
                        file_name=file_name, images_count=images_count
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
                        file_name=file_name,
                        images_info=images,
                        document_text=document_text,
                    )
                    + QUESTION_EXTRACTION_PROMPT_BODY_1
                    + QUESTION_EXTRACTION_PROMPT_BODY_2.format(
                        diagram_metadata_prompt_body=diagram_metadata_prompt_body
                    )
                    + QUESTION_EXTRACTION_PROMPT_BODY_3
                )

            case _:
                raise ValueError(f"Unsupported file type: {file_type}")
    except Exception as e:
        logger.error(f"Error getting question extraction prompt: {str(e)}")
        raise e


QUESTION_EXTRACTION_PROMPT_HEADER_PDF = """
    Analyze the following {images_count}-page PDF document and extract ALL existing assignment questions, exercises, problems, or assessment items.
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
    - EQUATION EXTRACTION: When you encounter mathematical equations or formulas:
        -- Extract them as LaTeX format using $...$ for inline equations and $$...$$ for display equations
        -- Preserve all mathematical notation accurately (symbols, subscripts, superscripts, fractions, integrals, etc.)
        -- Include equations in question text, options, answers, and rubrics where they appear
        -- Convert visual equations to LaTeX syntax when extracting from images
        -- Examples: $x^2 + y^2 = r^2$, $$\\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}$$, $\\int_0^\\infty f(x)dx$
    - Identify and set question type appropriately:
        -- multiple-choice: Questions with options (A, B, C, D or 1, 2, 3, 4)
        -- fill-blank: Questions with blanks (e.g., "The capital of France is ___")
        -- short-answer: Brief responses (1-2 sentences)
        -- numerical: Questions requiring numeric answers
        -- long-answer: Extended written responses (paragraphs)
        -- true-false: Binary true/false questions
        -- code-writing: Questions requiring code solutions
        -- diagram-analysis: Questions involving diagram interpretation
        -- multi-part: Questions with sub-parts (a, b, c) or (i, ii, iii)
            --- sub-parts can be of type "multiple-choice", "fill-blank", "short-answer", "numerical", "true-false", "code-writing", "diagram-analysis" and "multi-part"
            --- if sub-part is of type "multi-part", it will have sub-sub-parts of type "multiple-choice", "fill-blank", "short-answer", "numerical", "true-false", "code-writing" and "diagram-analysis"
            --- identify and set the type of sub-part and sub-sub-part appropriately
            --- maintain hierarchy, nesting level and order of sub-parts and sub-sub-parts
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
    - OPTIONAL PARTS DETECTION: When identifying multi-part questions, look for instructions indicating optional parts:
        -- PHRASES INDICATING OPTIONAL PARTS:
            --- "Answer any N", "Attempt any N", "Choose N of the following"
            --- "Do any N parts", "Select N questions", "Answer N out of M"
            --- "Solve any N problems", "Pick N to answer", "Complete N from the following"
            --- "[N × points] (Answer any N)", "Total N questions (Answer any N)"
        -- WHEN DETECTED:
            --- Set optionalParts: true on the parent question/subquestion
            --- Set requiredPartsCount: N (the number student must answer)
            --- Total parts count is derived from subquestions.length
            --- Example: "Answer any 2 of the following 3 parts" → optionalParts: true, requiredPartsCount: 2
        -- IMPORTANT:
            --- Only set optionalParts: true when explicit instructions are present
            --- If no optional instruction found, leave optionalParts: false (default)
            --- Apply this at any nesting level (main questions, subquestions, nested subquestions)
    - Extract following information:
        -- Question text (without question numbers or marks) - PRESERVE equations as LaTeX with $...$ or $$...$$
        -- Multiple choice options (without option letters/numbers) - PRESERVE equations as LaTeX where they appear
        -- Correct answers or solutions (DO generate if not present in the document) - PRESERVE equations as LaTeX
            --- For multiple choice: correctAnswer should be index string ("0", "1", "2", "3")
            --- For multi-part: provide empty string for correctAnswer (provide answers in subquestions)
        -- Point values
        -- Grading rubrics (DO generate if not present in the document) - PRESERVE equations as LaTeX where they appear
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
        -- PRESERVE equations in all sub-question text and rubrics as LaTeX
    - Regular questions:
        -- rubricType: "overall"
        -- rubric is required
        -- PRESERVE equations in question text and rubric as LaTeX
    - Code content:
        -- Set hasCode: true
        -- Specify codeLanguage
        -- Extract code in the code field
    - EQUATION PRESERVATION: Ensure all mathematical equations are preserved in question text, options, answers, and rubrics using LaTeX format ($...$ for inline, $$...$$ for display)
    Return the structured data according to the JSON schema.
"""
