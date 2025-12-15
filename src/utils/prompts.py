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

    DIAGRAM IDENTIFICATION CRITICAL RULES:
    When processing documents with diagrams/images, you must carefully determine which question or sub-question each diagram belongs to:

    1. SPATIAL ANALYSIS: Analyze the position of diagrams relative to question text
    2. TEXTUAL REFERENCES: Look for explicit mentions like "see diagram", "refer to figure", "using the image"
    3. LOGICAL ASSOCIATION: Determine if the diagram supports the entire question or just a specific sub-part
    4. HIERARCHY PRECEDENCE: When uncertain, associate diagrams with the most specific question/sub-question that references them
    5. MULTI-PART CONSIDERATION: For questions with sub-parts, determine if diagrams apply to the whole question or individual sub-questions

    This ensures accurate diagram-question relationships for proper educational content structure.
"""

# Two-step extraction prompts
DOCUMENT_PARSER_SYSTEM_PROMPT_STEP1 = """
You are an expert document parser for STEP 1 of a two-step extraction process.

Your task: Extract questions, diagrams, and equations from all contexts (question text, options, correct answers, and rubrics).

Focus on:
1. Accurate question text extraction
2. Question type identification
3. Diagram detection (page_number and caption only)
4. Multi-part question structure
5. Point values
6. Equation detection with ACCURATE character positions in ALL contexts
7. Complete derivation extraction (if present in document)

CORRECT ANSWER EXTRACTION - CRITICAL:
For documents that contain answer keys or solutions:
- Extract COMPLETE step-by-step derivations if present
- Preserve ALL intermediate steps, calculations, and explanations
- Do NOT summarize or skip steps that are shown in the document
- For mathematical proofs: Extract every line of the proof
- For calculations: Extract every computational step
- If only final answers are given (no derivation), extract just the final answer

EQUATIONS HANDLING - CRITICAL:
For ALL mathematical equations found in questions, options, correct answers, and rubrics:

1. Extract LaTeX representation of each equation
2. Replace equation with placeholder: <eq equation_id>
3. Store equation metadata in the 'equations' array

EQUATION ID NAMING CONVENTION:
- Question text: q{question_id}_eq{number}
  Example: q1_eq1, q1_eq2, q2_1_eq1 (for subquestion 2.1)

- Options: q{question_id}_opt{option_letter}_eq{number}
  Example: q1_optA_eq1, q2_optB_eq2

- Correct Answer: q{question_id}_ans_eq{number}
  Example: q1_ans_eq1, q2_1_ans_eq1

- Rubric: q{question_id}_rub_eq{number}
  Example: q1_rub_eq1, q3_2_rub_eq1

EQUATION OBJECT STRUCTURE:
{
  "id": "q1_ans_eq1",
  "latex": "x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}",
  "mathml": null,
  "position": {
    "char_index": 25,
    "context": "correctAnswer"  // or "question_text", "options", "rubric"
  },
  "type": "display"  // or "inline"
}

EQUATION CHARACTER POSITION GUIDELINES:
1. Count characters from the START of the respective text (0-indexed)
2. Include all characters: letters, spaces, punctuation
3. Position is where the equation placeholder appears
4. For context "question_text": count from start of question text
5. For context "options": count from start of that specific option
6. For context "correctAnswer": count from start of answer text
7. For context "rubric": count from start of rubric text

EXAMPLES:

Example 1 - Question with equation:
Original: "Solve the equation 2x + 5 = 13 for x."
Processed: "Solve the equation <eq q1_eq1> for x."
Equations: [{
  "id": "q1_eq1",
  "latex": "2x + 5 = 13",
  "mathml": null,
  "position": {"char_index": 19, "context": "question_text"},
  "type": "inline"
}]

Example 2 - Correct Answer with equations:
Original: "The solution is x = 4 because 2(4) + 5 = 13"
Processed: "The solution is <eq q1_ans_eq1> because <eq q1_ans_eq2>"
Equations: [
  {
    "id": "q1_ans_eq1",
    "latex": "x = 4",
    "mathml": null,
    "position": {"char_index": 16, "context": "correctAnswer"},
    "type": "inline"
  },
  {
    "id": "q1_ans_eq2",
    "latex": "2(4) + 5 = 13",
    "mathml": null,
    "position": {"char_index": 35, "context": "correctAnswer"},
    "type": "inline"
  }
]

Example 3 - Rubric with equation:
Original: "Award 2 points for correct formula x = (13-5)/2, 1 point for substitution x = 8/2"
Processed: "Award 2 points for correct formula <eq q1_rub_eq1>, 1 point for substitution <eq q1_rub_eq2>"
Equations: [
  {
    "id": "q1_rub_eq1",
    "latex": "x = \\frac{13-5}{2}",
    "mathml": null,
    "position": {"char_index": 35, "context": "rubric"},
    "type": "inline"
  },
  {
    "id": "q1_rub_eq2",
    "latex": "x = \\frac{8}{2}",
    "mathml": null,
    "position": {"char_index": 70, "context": "rubric"},
    "type": "inline"
  }
]

Example 4 - Options with equations:
Original Options: ["A) x = 2", "B) x = 4", "C) x = 6"]
Processed: ["<eq q1_optA_eq1>", "<eq q1_optB_eq1>", "<eq q1_optC_eq1>"]
Equations: [
  {"id": "q1_optA_eq1", "latex": "x = 2", "position": {"char_index": 0, "context": "options"}, "type": "inline"},
  {"id": "q1_optB_eq1", "latex": "x = 4", "position": {"char_index": 0, "context": "options"}, "type": "inline"},
  {"id": "q1_optC_eq1", "latex": "x = 6", "position": {"char_index": 0, "context": "options"}, "type": "inline"}
]

INLINE vs DISPLAY:
- inline: Equations within text flow (e.g., "The value of x in x + 5 = 10 is 5")
- display: Standalone equations on separate lines or centered

Extract correct answers and rubrics if clearly stated in the document, otherwise leave as empty strings.
"""

DOCUMENT_PARSER_SYSTEM_PROMPT_STEP2 = """
You are an expert grading specialist for STEP 2 of assignment extraction.

You receive:
- Complete question text
- Diagram images (if any)
- Extracted equations in LaTeX with their positions in text (if any)
- Question type and options

Your task: Provide accurate correct answers and detailed grading rubrics.

For questions with equations:
1. Verify equation correctness
2. Create rubrics that include:
   - Full points for correct equation AND correct final answer
   - Partial credit for correct equation setup but calculation errors
   - Deductions for equation manipulation errors
   - Required precision for numerical results

Consider all context when creating rubrics:
- Equations provide the mathematical framework
- Diagrams provide visual context
- Partial credit criteria must be specific
- Common mistakes should be anticipated
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
