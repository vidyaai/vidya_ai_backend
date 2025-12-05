#!/usr/bin/env python3
"""
Tests for PDFAnswerProcessor - process_pdf_to_json and extract_diagram_from_pdf functions.
"""
import json
import dotenv

dotenv.load_dotenv()

import os
import sys
import tempfile
from pathlib import Path

# Add src directory to Python path
src_dir = Path(__file__).parent.parent
sys.path.insert(0, str(src_dir))

from utils.pdf_answer_processor import PDFAnswerProcessor


# Test PDF file path
TEST_PDF_PATH = (
    Path(__file__).parent
    / "test_files"
    / "057c3ec997b62a8a87423296fded99c3_test1sol.pdf"
)


def test_process_pdf_to_json():
    """
    Test process_pdf_to_json function with a real PDF file.
    Calls real GPT APIs to extract answers from PDF.
    """
    # Initialize processor
    processor = PDFAnswerProcessor()

    # Process the PDF
    result = processor.process_pdf_to_json(str(TEST_PDF_PATH))

    # Print results
    print(f"\n[Test] Extracted {len(result)} answers from PDF")
    print(f"[Test] Result: {result}")

    # Basic assertions
    assert isinstance(result, dict), "Result should be a dictionary"
    assert len(result) > 0, "Should extract at least one answer"

    # Check structure of answers
    for q_num, answer in result.items():
        print(f"  Q{q_num}: {answer}")
        assert isinstance(q_num, str), "Question number should be string"
        # Answer can be string or dict (with diagram)
        if isinstance(answer, dict):
            assert "text" in answer, "Dict answer should have 'text' field"
            assert "diagram" in answer, "Dict answer should have 'diagram' field"
        else:
            assert isinstance(answer, str), "Answer should be string or dict"

    return result


def test_extract_diagram_from_pdf():
    """
    Test extract_diagram_from_pdf function.
    First processes PDF to get bounding boxes, then extracts diagrams.
    """
    # Initialize processor
    processor = PDFAnswerProcessor()

    # First, process PDF to get answers with diagrams
    answers = processor.process_pdf_to_json(str(TEST_PDF_PATH))

    print(f"All Answers extracted: {json.dumps(answers, indent=2)}...")

    # Find answers that have diagrams
    diagrams_found = []
    for q_num, answer in answers.items():
        if isinstance(answer, dict) and answer.get("diagram"):
            diagrams_found.append((q_num, answer["diagram"]))

    print(f"\n[Test] Found {len(diagrams_found)} diagrams in PDF")

    if diagrams_found:
        # Test extracting the first diagram
        q_num, diagram_info = diagrams_found[0]
        bounding_box = diagram_info.get("bounding_box")
        page_num = diagram_info.get("page_number", None)

        print(
            f"[Test] Extracting diagram for Q{q_num} with bounding box: {bounding_box}"
        )

        # Create temp file for output
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            output_path = tmp.name

        try:
            # Extract diagram
            success = processor.extract_diagram_from_pdf(
                str(TEST_PDF_PATH), bounding_box, page_num, output_path
            )

            print(f"[Test] Extraction success: {success}")

            if success:
                # Verify file was created and has content
                assert os.path.exists(output_path), "Output file should exist"
                assert (
                    os.path.getsize(output_path) > 0
                ), "Output file should have content"
                print(
                    f"[Test] Diagram saved to: {output_path} (size: {os.path.getsize(output_path)} bytes)"
                )

            return success
        finally:
            pass
            # Cleanup
            # if os.path.exists(output_path):
            #     os.unlink(output_path)
    else:
        print("[Test] No diagrams found in PDF - skipping extraction test")
        return True


def test_normalize_question_number():
    """Test the _normalize_question_number static method."""
    processor = PDFAnswerProcessor()

    test_cases = [
        ("1", "1"),
        ("17(a)", "17.1"),
        ("17(b)", "17.2"),
        ("33(a)(i)", "33.1.1"),
        ("33(a)(ii)", "33.1.2"),
        ("29.1", "29.1"),
        ("5(c)(iii)", "5.3.3"),
    ]

    print("\n[Test] Testing question number normalization:")
    for input_val, expected in test_cases:
        result = processor._normalize_question_number(input_val)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{input_val}' -> '{result}' (expected: '{expected}')")
        assert result == expected, f"Expected {expected}, got {result}"

    print("[Test] All normalization tests passed!")


def test_normalize_mcq_answer():
    """Test the _normalize_mcq_answer static method."""
    processor = PDFAnswerProcessor()

    test_cases = [
        ("C", "C"),
        ("B, 0.3 MB", "B"),
        ("A, Applying Galvanometer", "A"),
        ("D", "D"),
        ("a", "A"),
        (
            "Long descriptive answer about photosynthesis",
            "Long descriptive answer about photosynthesis",
        ),
        ("", ""),
    ]

    print("\n[Test] Testing MCQ answer normalization:")
    for input_val, expected in test_cases:
        result = processor._normalize_mcq_answer(input_val)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{input_val}' -> '{result}' (expected: '{expected}')")
        assert result == expected, f"Expected {expected}, got {result}"

    print("[Test] All MCQ normalization tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Testing PDFAnswerProcessor")
    print("=" * 60)

    # # Run helper function tests first (no API calls)
    # test_normalize_question_number()
    # test_normalize_mcq_answer()

    # # Run main tests (requires API calls)
    # print("\n" + "=" * 60)
    # print("Testing process_pdf_to_json (requires OpenAI API)")
    # print("=" * 60)
    # test_process_pdf_to_json()

    print("\n" + "=" * 60)
    print(
        "Testing process_pdf_to_json (requires OpenAI API) and extract_diagram_from_pdf"
    )
    print("=" * 60)
    test_extract_diagram_from_pdf()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
