#!/usr/bin/env python3
"""
Enhanced question paper parser with LLM-based diagram extraction.
No YOLO required - uses GPT-4o vision for diagram detection and extraction.
"""

import os
import json
import base64
from io import BytesIO
from pathlib import Path
from datetime import datetime
from textwrap import dedent
from typing import List, Dict, Any, Tuple

import dotenv
dotenv.load_dotenv()

from openai import OpenAI
from pdf2image import convert_from_path
from PIL import Image


class LLMDiagramExtractor:
    """Extract diagrams using LLM vision instead of YOLO"""

    def __init__(self):
        self.client = OpenAI()
        self.model = "gpt-4o"

    def _pil_image_to_data_url(self, img: Image.Image) -> str:
        """Convert PIL image to base64 data URL."""
        buffered = BytesIO()
        img.save(buffered, format="JPEG", quality=95)
        encoded = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"

    def detect_diagrams_in_page(self, page_image: Image.Image, page_num: int) -> List[Dict[str, Any]]:
        """
        Use GPT-4o to detect all diagrams/figures in a page and return bounding boxes.

        Returns:
            List of diagram metadata with bounding boxes
        """
        print(f"[LLM Detector] Analyzing page {page_num} for diagrams...")

        system_prompt = """
        You are a diagram detection expert. Analyze the image and identify ALL diagrams,
        figures, charts, graphs, schematics, or illustrations present.

        For each diagram, provide:
        1. A descriptive label
        2. Bounding box coordinates [x_min, y_min, x_max, y_max] in pixels
        3. Brief description of what the diagram shows

        Be precise with bounding boxes - include the entire diagram including labels and captions.
        """

        user_prompt = f"""
        Analyze this page and detect all diagrams, figures, charts, or illustrations.

        Return a JSON array of detected diagrams with this structure:
        {{
            "diagrams": [
                {{
                    "label": "Circuit diagram showing...",
                    "bounding_box": [x_min, y_min, x_max, y_max],
                    "description": "Brief description",
                    "confidence": "high/medium/low"
                }}
            ]
        }}

        Rules:
        - Only include actual diagrams/figures, not text or equations
        - Bounding box should be [left, top, right, bottom] in pixels
        - If no diagrams found, return empty array
        - Order diagrams top-to-bottom on the page
        """

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": dedent(system_prompt)},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": dedent(user_prompt)},
                            {
                                "type": "image_url",
                                "image_url": {"url": self._pil_image_to_data_url(page_image)}
                            }
                        ]
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )

            result = json.loads(completion.choices[0].message.content)
            diagrams = result.get("diagrams", [])

            print(f"[LLM Detector] Found {len(diagrams)} diagrams on page {page_num}")
            return diagrams

        except Exception as e:
            print(f"[LLM Detector] ERROR detecting diagrams: {e}")
            return []

    def extract_diagram_image(
        self,
        page_image: Image.Image,
        bounding_box: List[int],
        output_path: str
    ) -> bool:
        """Extract diagram region from page image using bounding box."""
        try:
            x_min, y_min, x_max, y_max = bounding_box

            # Validate bounds
            width, height = page_image.size
            x_min = max(0, min(x_min, width))
            x_max = max(0, min(x_max, width))
            y_min = max(0, min(y_min, height))
            y_max = max(0, min(y_max, height))

            if x_max <= x_min or y_max <= y_min:
                print(f"[LLM Detector] Invalid bounding box: {bounding_box}")
                return False

            # Crop and save
            cropped = page_image.crop((x_min, y_min, x_max, y_max))
            cropped.save(output_path, "JPEG", quality=95)

            print(f"[LLM Detector] Extracted diagram to {output_path}")
            return True

        except Exception as e:
            print(f"[LLM Detector] ERROR extracting diagram: {e}")
            return False

    def parse_question_paper_with_diagrams(
        self,
        pdf_path: str,
        output_json_path: str,
        diagrams_dir: str = None
    ) -> Dict[str, Any]:
        """
        Parse question paper with LLM-based diagram extraction.

        Args:
            pdf_path: Path to PDF file
            output_json_path: Path to save JSON output
            diagrams_dir: Directory to save extracted diagram images

        Returns:
            Dictionary with questions, answers, rubrics, and diagram metadata
        """
        print(f"[QuestionPaperParser] Starting to parse: {pdf_path}")

        # Setup diagrams directory
        if diagrams_dir:
            diagrams_path = Path(diagrams_dir)
            diagrams_path.mkdir(exist_ok=True, parents=True)
        else:
            diagrams_path = Path(pdf_path).parent / "diagrams"
            diagrams_path.mkdir(exist_ok=True)

        # Convert PDF to images
        print("[QuestionPaperParser] Converting PDF to images...")
        poppler_path = os.getenv("POPPLER_PATH", None)

        try:
            images = convert_from_path(pdf_path, dpi=200, poppler_path=poppler_path)
            print(f"[QuestionPaperParser] Converted {len(images)} pages")
        except Exception as e:
            print(f"[QuestionPaperParser] ERROR: {e}")
            raise

        # Step 1: Detect diagrams on each page
        print("\n[STEP 1] Detecting diagrams on all pages...")
        all_diagrams = {}
        for page_num, page_img in enumerate(images, 1):
            diagrams = self.detect_diagrams_in_page(page_img, page_num)
            if diagrams:
                all_diagrams[page_num] = {
                    "image": page_img,
                    "diagrams": diagrams
                }

        print(f"\n[STEP 1] Total diagrams detected: {sum(len(d['diagrams']) for d in all_diagrams.values())}")

        # Step 2: Extract diagram images
        print("\n[STEP 2] Extracting diagram images...")
        diagram_files = []
        for page_num, page_data in all_diagrams.items():
            for idx, diagram in enumerate(page_data["diagrams"], 1):
                diagram_filename = f"page{page_num}_diagram{idx}.jpg"
                diagram_filepath = diagrams_path / diagram_filename

                success = self.extract_diagram_image(
                    page_data["image"],
                    diagram["bounding_box"],
                    str(diagram_filepath)
                )

                if success:
                    diagram["extracted_file"] = str(diagram_filepath)
                    diagram["page_number"] = page_num
                    diagram_files.append(diagram)

        print(f"[STEP 2] Extracted {len(diagram_files)} diagram images")

        # Step 3: Parse questions with diagram context
        print("\n[STEP 3] Parsing questions with diagram awareness...")

        # Build prompt with all pages
        image_contents = []
        for page_num, page_img in enumerate(images, 1):
            image_contents.append({
                "type": "image_url",
                "image_url": {"url": self._pil_image_to_data_url(page_img)}
            })

        # Create diagram context for the prompt
        diagram_context = ""
        if diagram_files:
            diagram_context = "\n\nDetected diagrams:\n"
            for diag in diagram_files:
                diagram_context += f"- Page {diag['page_number']}: {diag['label']}\n"

        system_prompt = """
        You are an expert educational assessment analyzer.
        Parse question papers and generate model answers with detailed rubrics.
        Pay special attention to questions that reference diagrams or figures.
        """

        user_prompt = f"""
        Parse this question paper and extract ALL questions with answers and rubrics.

        {diagram_context}

        For each question, provide:
        - question_number: identifier (e.g., "1", "2a", "4c")
        - question_text: full question text
        - marks: total marks
        - answer: complete model answer
        - rubric: detailed marking scheme
        - has_diagram: true if question references a diagram/figure
        - diagram_reference: which diagram if applicable

        Return JSON:
        {{
            "exam_info": {{
                "module_code": "...",
                "module_title": "...",
                "total_marks": ...,
                "duration": "..."
            }},
            "questions": [
                {{
                    "question_number": "1",
                    "question_text": "...",
                    "marks": 8,
                    "answer": "...",
                    "rubric": "...",
                    "has_diagram": false,
                    "diagram_reference": null
                }}
            ]
        }}
        """

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
                temperature=0.3,
            )

            result = json.loads(completion.choices[0].message.content)

            # Add diagram metadata
            result["diagrams"] = diagram_files
            result["_metadata"] = {
                "parsed_at": datetime.now().isoformat(),
                "total_questions": len(result.get("questions", [])),
                "total_diagrams": len(diagram_files),
                "diagrams_directory": str(diagrams_path),
                "model_used": self.model,
                "extraction_method": "LLM-based (no YOLO)"
            }

            print(f"[STEP 3] Parsed {len(result.get('questions', []))} questions")

            # Save to JSON
            print(f"\n[QuestionPaperParser] Saving to: {output_json_path}")
            with open(output_json_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            print(f"[QuestionPaperParser] ✓ Complete!")
            print(f"  - Output JSON: {output_json_path}")
            print(f"  - Diagrams: {diagrams_path}")

            return result

        except Exception as e:
            print(f"[QuestionPaperParser] ERROR: {e}")
            raise


def main():
    """Main entry point"""

    # Paths
    backend_dir = Path(__file__).parent
    pdf_path = backend_dir / "test_paper.pdf"
    output_path = backend_dir / "test_paper_with_diagrams.json"
    diagrams_dir = backend_dir / "extracted_diagrams"

    if not pdf_path.exists():
        print(f"ERROR: PDF not found at {pdf_path}")
        return

    print("="*80)
    print("Question Paper Parser with LLM Diagram Extraction")
    print("="*80)
    print(f"Input PDF: {pdf_path}")
    print(f"Output JSON: {output_path}")
    print(f"Diagrams Dir: {diagrams_dir}")
    print("="*80)

    # Parse with diagram extraction
    parser = LLMDiagramExtractor()
    result = parser.parse_question_paper_with_diagrams(
        str(pdf_path),
        str(output_path),
        str(diagrams_dir)
    )

    # Print summary
    print("\n" + "="*80)
    print("PARSING COMPLETE - SUMMARY")
    print("="*80)

    exam_info = result.get("exam_info", {})
    print(f"Module: {exam_info.get('module_code', 'N/A')} - {exam_info.get('module_title', 'N/A')}")
    print(f"Total Marks: {exam_info.get('total_marks', 'N/A')}")
    print(f"Questions: {len(result.get('questions', []))}")
    print(f"Diagrams Extracted: {len(result.get('diagrams', []))}")

    print("\nExtracted Diagrams:")
    print("-" * 80)
    for diag in result.get("diagrams", []):
        print(f"Page {diag['page_number']}: {diag['label']}")
        print(f"  File: {Path(diag['extracted_file']).name}")
        print(f"  Description: {diag.get('description', 'N/A')}")
        print()

    print("="*80)
    print(f"✓ Output saved to: {output_path}")
    print(f"✓ Diagrams saved to: {diagrams_dir}")
    print("="*80)


if __name__ == "__main__":
    main()
