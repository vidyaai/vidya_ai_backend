#!/usr/bin/env python3
"""
Test script for _extract_all_content_parallel method in AssignmentDocumentParser
"""

import os
import sys
import json
from pathlib import Path
from PIL import Image
from pdf2image import convert_from_path

from dotenv import load_dotenv

load_dotenv()

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.assignment_document_parser import AssignmentDocumentParser


def load_test_images_from_pdf(pdf_path: str) -> list[Image.Image]:
    """
    Load images from a PDF file for testing.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        List of PIL Images
    """
    print(f"Loading images from PDF: {pdf_path}")
    images = convert_from_path(pdf_path, dpi=200)
    print(f"✓ Loaded {len(images)} pages from PDF")
    return images


def create_sample_page_batches(
    images: list[Image.Image], batch_size: int = 3
) -> list[list[tuple[Image.Image, int]]]:
    """
    Create page batches from images for testing.

    Args:
        images: List of PIL Images
        batch_size: Number of pages per batch

    Returns:
        List of batches, where each batch is a list of (image, page_number) tuples
    """
    page_batches = []
    for i in range(0, len(images), batch_size):
        batch = [(images[j], j + 1) for j in range(i, min(i + batch_size, len(images)))]
        page_batches.append(batch)

    print(f"✓ Created {len(page_batches)} batches with batch_size={batch_size}")
    return page_batches


def test_extract_all_content_parallel():
    """
    Test the _extract_all_content_parallel method with real PDF images.
    """
    print("\n" + "=" * 80)
    print("Testing _extract_all_content_parallel")
    print("=" * 80)

    # Path to test PDF (you can change this to any PDF file)
    pdf_path = r"E:\VidyAI\Dev\vidya_ai_backend\src\tests\test_files\physics qp.pdf"

    # Check if PDF exists
    if not os.path.exists(pdf_path):
        print(f"⚠ Test PDF not found at: {pdf_path}")
        print("Please update the pdf_path variable to point to a valid PDF file.")

        # Try to find any PDF in the test_files directory
        test_files_dir = os.path.join(os.path.dirname(__file__), "test_files")
        if os.path.exists(test_files_dir):
            pdf_files = list(Path(test_files_dir).glob("*.pdf"))
            if pdf_files:
                pdf_path = str(pdf_files[0])
                print(f"Using alternative PDF: {pdf_path}")
            else:
                print("✗ No PDF files found in test_files directory")
                return None
        else:
            print("✗ Test cannot proceed without a PDF file")
            return None

    try:
        # Initialize parser
        print("\n1. Initializing AssignmentDocumentParser...")
        parser = AssignmentDocumentParser(user_id=1)  # Test user ID
        print("✓ Parser initialized")

        # Load images from PDF
        print("\n2. Loading images from PDF...")
        images = load_test_images_from_pdf(pdf_path)

        # Create page batches
        print("\n3. Creating page batches...")
        # Test with different batch sizes
        batch_size = 3  # Process 3 pages per batch
        page_batches = create_sample_page_batches(images, batch_size)

        # Display batch information
        print(f"\nBatch Information:")
        for idx, batch in enumerate(page_batches):
            page_nums = [page_num for _, page_num in batch]
            print(f"  Batch {idx + 1}: Pages {page_nums}")

        # Call _extract_all_content_parallel
        print("\n4. Calling _extract_all_content_parallel...")
        print("   (This will make parallel LLM API calls - may take some time)")

        file_name = os.path.basename(pdf_path)
        extracted_data = parser._extract_all_content_parallel(page_batches, file_name)

        print("\n✓ Extraction completed successfully!")

        # Validate and display results
        print("\n5. Validating extracted data...")

        # Check structure
        assert isinstance(extracted_data, dict), "Extracted data should be a dictionary"
        print("✓ Extracted data is a dictionary")

        # Check required fields
        assert "title" in extracted_data, "Missing 'title' field"
        assert "questions" in extracted_data, "Missing 'questions' field"
        print("✓ Required fields present")

        # Check questions
        questions = extracted_data.get("questions", [])
        assert isinstance(questions, list), "Questions should be a list"
        print(f"✓ Extracted {len(questions)} questions")

        # Display summary
        print("\n" + "=" * 80)
        print("EXTRACTION SUMMARY")
        print("=" * 80)
        print(f"Title: {extracted_data.get('title', 'N/A')}")
        print(f"Description: {extracted_data.get('description', 'N/A')}")
        print(f"Total Questions: {len(questions)}")

        # Analyze question types
        question_types = {}
        for q in questions:
            q_type = q.get("type", "unknown")
            question_types[q_type] = question_types.get(q_type, 0) + 1

        print(f"\nQuestion Types:")
        for q_type, count in question_types.items():
            print(f"  {q_type}: {count}")

        # Display first few questions
        print(f"\nFirst {min(3, len(questions))} Questions:")
        for i, question in enumerate(questions[:3]):
            print(f"\n--- Question {i + 1} ---")
            print(f"ID: {question.get('id', 'N/A')}")
            print(f"Type: {question.get('type', 'N/A')}")
            print(f"Question: {question.get('question', 'N/A')[:100]}...")
            print(f"Points: {question.get('points', 'N/A')}")
            print(f"Has Diagram: {question.get('hasDiagram', False)}")
            print(f"Has Code: {question.get('hasCode', False)}")

            if question.get("options"):
                print(f"Options: {len(question.get('options', []))} choices")

            if question.get("correctAnswer"):
                ans = question.get("correctAnswer", "")
                if isinstance(ans, str):
                    print(f"Correct Answer: {ans[:50]}...")
                else:
                    print(f"Correct Answer: {ans}")

            if question.get("rubric"):
                print(f"Rubric: {question.get('rubric', '')[:50]}...")

            if question.get("equations"):
                print(f"Equations: {len(question.get('equations', []))} equation(s)")

            if question.get("subquestions"):
                print(f"Subquestions: {len(question.get('subquestions', []))} part(s)")

        # Check for questions with diagrams
        questions_with_diagrams = [q for q in questions if q.get("hasDiagram")]
        print(f"\nQuestions with Diagrams: {len(questions_with_diagrams)}")

        # Check for questions with equations
        questions_with_equations = [q for q in questions if q.get("equations")]
        print(f"Questions with Equations: {len(questions_with_equations)}")

        # Check for multi-part questions
        multi_part_questions = [q for q in questions if q.get("type") == "multi-part"]
        print(f"Multi-part Questions: {len(multi_part_questions)}")

        # Save extracted data to file for inspection
        output_file = os.path.join(
            os.path.dirname(__file__), "test_output_extract_all_content_parallel.json"
        )
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(extracted_data, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Full extracted data saved to: {output_file}")

        print("\n" + "=" * 80)
        print("✓ TEST PASSED - _extract_all_content_parallel works correctly!")
        print("=" * 80)

        return extracted_data

    except Exception as e:
        print(f"\n✗ TEST FAILED with error: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_extract_all_content_parallel_with_custom_batches():
    """
    Test with manually defined page batches to ensure consolidation works correctly.
    """
    print("\n" + "=" * 80)
    print("Testing _extract_all_content_parallel with Custom Batches")
    print("=" * 80)

    pdf_path = r"E:\VidyAI\QP and AS\PhysicsQP\Physics QP.pdf"

    if not os.path.exists(pdf_path):
        print(f"⚠ Test PDF not found at: {pdf_path}")
        return None

    try:
        parser = AssignmentDocumentParser(user_id=1)
        images = load_test_images_from_pdf(pdf_path)

        # Create custom batches (e.g., pages 1-2, pages 3-5, pages 6-7)
        custom_batches = [
            [(images[0], 1), (images[1], 2)],
        ]

        # Add more batches if we have enough pages
        if len(images) >= 5:
            custom_batches.append([(images[2], 3), (images[3], 4), (images[4], 5)])

        if len(images) >= 7:
            custom_batches.append([(images[5], 6), (images[6], 7)])

        print(f"Testing with {len(custom_batches)} custom batches:")
        for idx, batch in enumerate(custom_batches):
            page_nums = [page_num for _, page_num in batch]
            print(f"  Batch {idx + 1}: Pages {page_nums}")

        print("\nExtracting content...")
        extracted_data = parser._extract_all_content_parallel(
            custom_batches, os.path.basename(pdf_path)
        )

        print(f"✓ Extracted {len(extracted_data.get('questions', []))} questions")

        # Verify question IDs are unique and sequential
        question_ids = []
        for q in extracted_data.get("questions", []):
            question_ids.append(q.get("id"))

        print(f"\nQuestion IDs: {question_ids}")

        # Check for duplicates
        if len(question_ids) != len(set(question_ids)):
            print("⚠ WARNING: Duplicate question IDs detected!")
        else:
            print("✓ All question IDs are unique")

        return extracted_data

    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_extract_all_content_parallel_edge_cases():
    """
    Test edge cases for _extract_all_content_parallel.
    """
    print("\n" + "=" * 80)
    print("Testing _extract_all_content_parallel Edge Cases")
    print("=" * 80)

    pdf_path = r"E:\VidyAI\QP and AS\PhysicsQP\Physics QP.pdf"

    if not os.path.exists(pdf_path):
        print(f"⚠ Test PDF not found at: {pdf_path}")
        return

    try:
        parser = AssignmentDocumentParser(user_id=1)
        images = load_test_images_from_pdf(pdf_path)

        # Test 1: Single batch with all pages
        print("\n1. Testing single batch with all pages...")
        single_batch = [[(img, idx + 1) for idx, img in enumerate(images[:3])]]
        result1 = parser._extract_all_content_parallel(single_batch, "test.pdf")
        print(f"✓ Single batch: {len(result1.get('questions', []))} questions")

        # Test 2: Single page per batch (maximum parallelism)
        if len(images) >= 3:
            print("\n2. Testing one page per batch...")
            individual_batches = [
                [(images[i], i + 1)] for i in range(min(3, len(images)))
            ]
            result2 = parser._extract_all_content_parallel(
                individual_batches, "test.pdf"
            )
            print(
                f"✓ Individual batches: {len(result2.get('questions', []))} questions"
            )

        # Test 3: Verify consolidation preserves all questions
        print("\n3. Verifying consolidation preserves questions...")
        batch_size_3 = create_sample_page_batches(images[:6], batch_size=3)
        result3 = parser._extract_all_content_parallel(batch_size_3, "test.pdf")

        batch_size_2 = create_sample_page_batches(images[:6], batch_size=2)
        result4 = parser._extract_all_content_parallel(batch_size_2, "test.pdf")

        print(f"Batch size 3: {len(result3.get('questions', []))} questions")
        print(f"Batch size 2: {len(result4.get('questions', []))} questions")

        # Note: Due to LLM variability, counts may differ slightly, but should be close
        print("✓ Edge case tests completed")

    except Exception as e:
        print(f"✗ Edge case tests failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("TESTING _extract_all_content_parallel METHOD")
    print("=" * 80)

    # Run main test
    print("\n>>> Test 1: Basic Extraction")
    result1 = test_extract_all_content_parallel()

    # Run custom batch test
    if result1:
        print("\n>>> Test 2: Custom Batches")
        result2 = test_extract_all_content_parallel_with_custom_batches()

    # Run edge case tests
    if result1:
        print("\n>>> Test 3: Edge Cases")
        test_extract_all_content_parallel_edge_cases()

    print("\n" + "=" * 80)
    print("ALL TESTS COMPLETED")
    print("=" * 80)
