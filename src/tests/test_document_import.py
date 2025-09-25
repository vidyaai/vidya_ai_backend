#!/usr/bin/env python3
"""
Test script for document import functionality
"""

import base64
import json
from utils.document_processor import DocumentProcessor, AssignmentDocumentParser


def test_text_extraction():
    """Test text extraction from a simple text document"""
    processor = DocumentProcessor()

    # Create a sample text document
    sample_text = """
    Introduction to Control Systems

    Control systems are fundamental to modern engineering and are used in a wide variety of applications.
    A control system is a system that manages, commands, directs, or regulates the behavior of other devices or systems.

    Key Concepts:
    1. Open-loop control systems
    2. Closed-loop (feedback) control systems
    3. Transfer functions
    4. Stability analysis

    Example: Temperature Control System
    Consider a simple temperature control system for a room. The system consists of:
    - Temperature sensor (thermometer)
    - Controller (thermostat)
    - Actuator (heater/air conditioner)
    - Plant (the room)

    The goal is to maintain the room temperature at a desired setpoint.
    """

    # Encode as base64
    encoded_content = base64.b64encode(sample_text.encode("utf-8")).decode("utf-8")

    try:
        extracted_text = processor.extract_text_from_file(
            encoded_content, "control_systems.txt", "text/plain"
        )

        print("✓ Text extraction successful!")
        print(f"Extracted text length: {len(extracted_text)} characters")
        print(f"First 200 characters: {extracted_text[:200]}...")

        return extracted_text

    except Exception as e:
        print(f"✗ Text extraction failed: {e}")
        return None


def test_assignment_extraction():
    """Test AI-powered assignment question extraction"""
    sample_assignment = """
    Digital Signal Processing Assignment

    Instructions: Answer all questions. Show your work for numerical problems.

    Question 1: (5 points)
    What is the Nyquist frequency for a signal sampled at 8 kHz?
    a) 2 kHz
    b) 4 kHz
    c) 8 kHz
    d) 16 kHz

    Answer: b) 4 kHz

    Question 2: (10 points)
    Explain the difference between FIR and IIR digital filters. Include at least three key differences in your answer.

    Rubric:
    - Definition of FIR (3 points)
    - Definition of IIR (3 points)
    - Three key differences (4 points)

    Question 3 (Multi-part): (15 points)
    Digital Filter Design Task
    Part (a): Calculate the normalized cutoff frequency for a low-pass filter with cutoff 1 kHz and sampling rate 8 kHz.
    Part (b): Provide a short Python function using SciPy to design a simple FIR low-pass filter with that cutoff.
    Part (c): What would happen if the cutoff frequency was 5 kHz instead?

    Code (starter):
    ```python
    import numpy as np
    from scipy.signal import firwin

    def design_lowpass(num_taps: int, cutoff_hz: float, fs_hz: float) -> np.ndarray:
        # TODO: implement using firwin
        return firwin(num_taps, ???, fs=fs_hz)
    ```

    Question 4: (8 points)
    The capital of France is ___ and it has a population of approximately ___ million people.

    Question 5: (3 points)
    True or False: Digital filters always have better performance than analog filters.

    Question 6: (12 points)
    Write a Python function to implement a moving average filter. The function should:
    - Take a signal and window size as input
    - Return the filtered signal
    - Handle edge cases properly

    ```python
    def moving_average(signal, window_size):
        # Your implementation here
        pass
    ```

    Answer Key:
    a) Normalized cutoff = 1 kHz / (8 kHz/2) = 0.25
    b) Yes, reasonable as it's well below Nyquist frequency
    c) Would cause aliasing as 5 kHz > 4 kHz (Nyquist frequency)
    4. Paris, 2.1
    5. False
    6. See implementation above

    Total Points: 30
    """

    parser = AssignmentDocumentParser()

    try:
        parsed_assignment = parser.parse_document_to_assignment(
            sample_assignment,
            "dsp_assignment.pdf",
            None,  # No generation options needed for extraction
        )

        print("\n✓ Assignment extraction successful!")
        print(f"Title: {parsed_assignment.get('title')}")
        print(f"Description: {parsed_assignment.get('description')}")
        print(f"Number of questions: {len(parsed_assignment.get('questions', []))}")
        print(f"Total points: {parsed_assignment.get('total_points')}")

        # Display questions
        for i, question in enumerate(parsed_assignment.get("questions", [])):
            print(f"\nQuestion {i+1}:")
            print(f"  Type: {question.get('type')}")
            print(f"  Question: {question.get('question')[:100]}...")
            print(f"  Points: {question.get('points')}")
            print(f"  Has Code: {question.get('hasCode', False)}")
            print(f"  Has Diagram: {question.get('hasDiagram', False)}")
            print(f"  Code Language: {question.get('codeLanguage', 'N/A')}")
            print(f"  Output Type: {question.get('outputType', 'N/A')}")
            print(f"  Rubric Type: {question.get('rubricType', 'N/A')}")
            if question.get("options"):
                print(f"  Options: {len(question.get('options'))} choices")
            if question.get("correctAnswer"):
                print(f"  Answer: {question.get('correctAnswer')[:50]}...")
            if question.get("subquestions"):
                print(f"  Subquestions: {len(question.get('subquestions'))} parts")
                for j, sub in enumerate(question.get("subquestions", [])):
                    print(f"    Part {j+1}: {sub.get('question', '')[:50]}...")
                    print(f"      Type: {sub.get('type')}")
                    print(f"      Has Code: {sub.get('hasCode', False)}")
                    print(f"      Has Diagram: {sub.get('hasDiagram', False)}")

        # Display source info
        source_info = parsed_assignment.get("source_info", {})
        print(f"\nSource Info:")
        print(f"  Questions found: {source_info.get('questions_found', 0)}")
        print(f"  Has answer key: {source_info.get('has_answer_key', False)}")
        print(f"  Has rubrics: {source_info.get('has_rubrics', False)}")
        print(f"  Document type: {source_info.get('document_type', 'unknown')}")

        # Validate frontend schema compliance
        print(f"\nValidating frontend schema compliance...")
        questions = parsed_assignment.get("questions", [])

        # Check that we have the expected question types
        question_types = [q.get("type") for q in questions]
        expected_types = [
            "multiple-choice",
            "short-answer",
            "long-answer",
            "fill-blank",
            "true-false",
            "code-writing",
            "multi-part",
        ]

        for expected_type in expected_types:
            if expected_type in question_types:
                print(f"  ✓ Found {expected_type} question")
            else:
                print(f"  ⚠ Missing {expected_type} question")

        # Check frontend schema fields
        required_fields = [
            "hasCode",
            "hasDiagram",
            "codeLanguage",
            "outputType",
            "rubricType",
            "code",
            "options",
            "correctAnswer",
        ]

        for i, question in enumerate(questions):
            missing_fields = [
                field for field in required_fields if field not in question
            ]
            if missing_fields:
                print(f"  ⚠ Question {i+1} missing fields: {missing_fields}")
            else:
                print(f"  ✓ Question {i+1} has all required fields")

        # Check for multi-part questions
        multi_part_questions = [q for q in questions if q.get("type") == "multi-part"]
        if multi_part_questions:
            print(f"  ✓ Found {len(multi_part_questions)} multi-part question(s)")
        else:
            print(f"  ⚠ No multi-part questions found")

        # Check for code questions
        code_questions = [q for q in questions if q.get("hasCode", False)]
        if code_questions:
            print(f"  ✓ Found {len(code_questions)} question(s) with code")
        else:
            print(f"  ⚠ No questions with code found")

        return parsed_assignment

    except Exception as e:
        print(f"✗ Assignment extraction failed: {e}")
        import traceback

        traceback.print_exc()
        return None


if __name__ == "__main__":
    print("Testing Document Import Functionality")
    print("=" * 50)

    # Test text extraction
    print("\n1. Testing text extraction...")
    extracted_text = test_text_extraction()

    if extracted_text:
        # Test assignment extraction
        print("\n2. Testing assignment extraction...")
        parsed_assignment = test_assignment_extraction()

        if parsed_assignment:
            print("\n✓ All tests passed!")
            print("\nDocument import functionality is working correctly.")
        else:
            print("\n✗ Assignment extraction test failed.")
    else:
        print("\n✗ Text extraction test failed.")

    print("\n" + "=" * 50)
