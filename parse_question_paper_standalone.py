#!/usr/bin/env python3
"""
Standalone script to parse question paper PDF and generate JSON with answers and rubrics.
This script runs independently of the backend API for faster processing.
"""

import os
import json
import base64
from io import BytesIO
from pathlib import Path
from datetime import datetime
from textwrap import dedent

# Set up environment
import dotenv
dotenv.load_dotenv()

from openai import OpenAI
from pdf2image import convert_from_path
from PIL import Image


class QuestionPaperParser:
    """Parse question papers and generate answers with rubrics"""

    def __init__(self):
        self.client = OpenAI()
        self.model = "gpt-4o"  # Using gpt-4o for efficient multimodal processing

    def _pil_image_to_data_url(self, img: Image.Image) -> str:
        """Convert PIL image to base64 data URL."""
        buffered = BytesIO()
        img.save(buffered, format="JPEG")
        encoded = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"

    def parse_question_paper(self, pdf_path: str, output_json_path: str) -> dict:
        """
        Parse question paper PDF and generate structured JSON with answers and rubrics.

        Args:
            pdf_path: Path to the PDF file
            output_json_path: Path to save the output JSON

        Returns:
            Dictionary containing parsed questions with answers and rubrics
        """
        print(f"[QuestionPaperParser] Starting to parse: {pdf_path}")

        # Convert PDF to images
        print("[QuestionPaperParser] Converting PDF to images...")
        poppler_path = os.getenv("POPPLER_PATH", None)

        try:
            images = convert_from_path(pdf_path, dpi=200, poppler_path=poppler_path)
            print(f"[QuestionPaperParser] Converted {len(images)} pages")
        except Exception as e:
            print(f"[QuestionPaperParser] ERROR: {e}")
            raise

        # Build multimodal prompt with all pages
        print("[QuestionPaperParser] Building LLM prompt with images...")
        image_contents = []
        for page_num, page_img in enumerate(images, 1):
            image_contents.append({
                "type": "image_url",
                "image_url": {"url": self._pil_image_to_data_url(page_img)}
            })

        system_prompt = """
        You are an expert educational assessment analyzer.
        Your task is to parse question papers and generate model answers with detailed rubrics.
        Return structured JSON with all questions, their answers, and marking rubrics.
        """

        user_prompt = """
        Parse this question paper and extract ALL questions with the following information:

        1. Question number and text
        2. Marks allocated
        3. Model answer (correct/expected answer)
        4. Rubric (marking scheme breakdown)

        For each question, provide:
        - question_number: The question identifier (e.g., "1", "2a", "4c")
        - question_text: The full question text
        - marks: Total marks for the question
        - answer: A complete model answer
        - rubric: Detailed marking breakdown showing how marks should be allocated

        IMPORTANT INSTRUCTIONS:
        - Extract ALL questions from ALL parts of the paper (Part 1 and Part 2)
        - For multi-part questions, create separate entries for each sub-part
        - Generate complete, detailed model answers based on the question requirements
        - Create comprehensive rubrics that break down how marks should be awarded
        - For mathematical/engineering questions, include key equations and steps in the answer
        - For conceptual questions, provide detailed explanations

        Return a JSON object with this structure:
        {
            "exam_info": {
                "module_code": "...",
                "module_title": "...",
                "total_marks": ...,
                "duration": "..."
            },
            "questions": [
                {
                    "question_number": "1",
                    "question_text": "...",
                    "marks": 8,
                    "answer": "Complete model answer here...",
                    "rubric": "Marking scheme: 2 marks for..., 3 marks for..., etc."
                }
            ]
        }
        """

        print("[QuestionPaperParser] Calling GPT-4o to parse and generate answers...")

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": dedent(system_prompt)},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": dedent(user_prompt)},
                            *image_contents
                        ]
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.3,  # Lower temperature for more consistent answers
            )

            result = json.loads(completion.choices[0].message.content)

            # Add metadata
            result["_metadata"] = {
                "parsed_at": datetime.now().isoformat(),
                "total_questions": len(result.get("questions", [])),
                "model_used": self.model
            }

            print(f"[QuestionPaperParser] Successfully parsed {len(result.get('questions', []))} questions")

            # Save to JSON file
            print(f"[QuestionPaperParser] Saving to: {output_json_path}")
            with open(output_json_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            print(f"[QuestionPaperParser] ✓ Complete! Output saved to: {output_json_path}")

            return result

        except Exception as e:
            print(f"[QuestionPaperParser] ERROR during LLM call: {e}")
            raise


def main():
    """Main entry point"""

    # Paths
    backend_dir = Path(__file__).parent
    pdf_path = backend_dir / "test_paper.pdf"
    output_path = backend_dir / "test_paper_parsed.json"

    # Check if PDF exists
    if not pdf_path.exists():
        print(f"ERROR: PDF not found at {pdf_path}")
        return

    print("="*80)
    print("Question Paper Parser - Standalone")
    print("="*80)
    print(f"Input PDF: {pdf_path}")
    print(f"Output JSON: {output_path}")
    print("="*80)

    # Parse the question paper
    parser = QuestionPaperParser()
    result = parser.parse_question_paper(str(pdf_path), str(output_path))

    # Print summary
    print("\n" + "="*80)
    print("PARSING COMPLETE - SUMMARY")
    print("="*80)

    exam_info = result.get("exam_info", {})
    print(f"Module: {exam_info.get('module_code', 'N/A')} - {exam_info.get('module_title', 'N/A')}")
    print(f"Total Marks: {exam_info.get('total_marks', 'N/A')}")
    print(f"Questions Extracted: {len(result.get('questions', []))}")

    print("\nQuestions Overview:")
    print("-" * 80)
    for q in result.get("questions", [])[:10]:  # Show first 10
        print(f"Q{q['question_number']}: {q['marks']} marks")
        print(f"  Question: {q['question_text'][:100]}...")
        print(f"  Answer: {q.get('answer', 'N/A')[:80]}...")
        print()

    if len(result.get("questions", [])) > 10:
        print(f"... and {len(result.get('questions', [])) - 10} more questions")

    print("="*80)
    print(f"✓ Full output saved to: {output_path}")
    print("="*80)


if __name__ == "__main__":
    main()
