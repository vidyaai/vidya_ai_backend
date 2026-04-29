#!/usr/bin/env python3
"""
Test script for Query Rewriter - Tests numbered reference detection and rewriting.

Usage:
    python test_query_rewriter.py
"""

import sys
import os

# Load environment variables from .env file
from dotenv import load_dotenv

load_dotenv()

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from utils.ml_models import OpenAIVisionClient
from controllers.config import logger
import json


def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_test_case(test_num, description):
    """Print test case header."""
    print(f"\n{'─' * 80}")
    print(f"Test {test_num}: {description}")
    print(f"{'─' * 80}")


def test_query_rewriter():
    """Test the query rewriter with numbered references."""

    print_section("QUERY REWRITER TEST SUITE")
    print("\nInitializing OpenAI Vision Client...")

    try:
        client = OpenAIVisionClient()
        print("✅ Client initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize client: {e}")
        return

    # Test Case 1: Numbered list from exam questions
    print_test_case(1, "Reference to numbered exam question")

    conversation_history_1 = [
        {
            "role": "user",
            "content": "give me 10 questions from this lecture to prepare for exams",
        },
        {
            "role": "assistant",
            "content": """Here are 10 questions based on the key points:

1. What is the main purpose of Doug McLean's seminar on aerodynamics?

2. How does McLean relate his personal experiences with air travel?

3. What is the significance of Newton's third law in aerodynamics?

4. What are some misconceptions related to lift that McLean addresses?

5. What role does vorticity play in understanding aerodynamic flows?

6. Why is it important to challenge assumptions when debunking misconceptions?

7. What is the zero CF criterion, and why is it problematic in 3D flows?

8. What does McLean mean by the "region of origin" concept?

9. How does lift impact the motion of the atmosphere at large?

10. What is the economic significance of aviation mentioned?""",
        },
    ]

    test_queries_1 = [
        "explain question 7 in detail",
        "tell me more about point 8",
        "give me details on the 2nd point",
        "elaborate on question 4",
    ]

    for query in test_queries_1:
        print(f"\nUser query: '{query}'")
        result = client.rewrite_query_with_context(query, conversation_history_1)

        print(f"  Has reference: {result.get('has_ambiguous_reference')}")
        print(f"  Resolved term: {result.get('resolved_term')}")
        print(f"  Rewritten: '{result.get('rewritten_query')}'")

        if result.get("has_ambiguous_reference"):
            print("  ✅ PASS - Detected and rewrote reference")
        else:
            print("  ❌ FAIL - Did not detect reference")

    # Test Case 2: Reference to "the above topic"
    print_test_case(2, "Reference to 'the above topic'")

    conversation_history_2 = [
        {
            "role": "user",
            "content": "is wafer level chip packaging discussed in the video?",
        },
        {
            "role": "assistant",
            "content": "Yes, wafer level chip packaging is discussed at 60:31 to 61:26 in the video.",
        },
    ]

    query_2 = "can you give me some external links about the above topic?"
    print(f"\nUser query: '{query_2}'")
    result = client.rewrite_query_with_context(query_2, conversation_history_2)

    print(f"  Has reference: {result.get('has_ambiguous_reference')}")
    print(f"  Resolved term: {result.get('resolved_term')}")
    print(f"  Rewritten: '{result.get('rewritten_query')}'")

    if "wafer level chip packaging" in result.get("rewritten_query", "").lower():
        print("  ✅ PASS - Correctly resolved 'the above topic'")
    else:
        print("  ❌ FAIL - Did not resolve 'the above topic'")

    # Test Case 3: Self-contained query (should NOT rewrite)
    print_test_case(3, "Self-contained query (no reference)")

    conversation_history_3 = [
        {"role": "user", "content": "what is aerodynamics?"},
        {
            "role": "assistant",
            "content": "Aerodynamics is the study of how air flows around objects...",
        },
    ]

    query_3 = "what is drag?"
    print(f"\nUser query: '{query_3}'")
    result = client.rewrite_query_with_context(query_3, conversation_history_3)

    print(f"  Has reference: {result.get('has_ambiguous_reference')}")
    print(f"  Resolved term: {result.get('resolved_term')}")
    print(f"  Rewritten: '{result.get('rewritten_query')}'")

    if not result.get("has_ambiguous_reference"):
        print("  ✅ PASS - Correctly identified as self-contained")
    else:
        print("  ❌ FAIL - Incorrectly detected reference")

    # Test Case 4: Implicit reference ("elaborate more")
    print_test_case(4, "Implicit reference ('elaborate more')")

    conversation_history_4 = [
        {"role": "user", "content": "what is the Bernoulli principle?"},
        {
            "role": "assistant",
            "content": "The Bernoulli principle states that an increase in the speed of a fluid occurs simultaneously with a decrease in pressure...",
        },
    ]

    query_4 = "can you elaborate more on this?"
    print(f"\nUser query: '{query_4}'")
    result = client.rewrite_query_with_context(query_4, conversation_history_4)

    print(f"  Has reference: {result.get('has_ambiguous_reference')}")
    print(f"  Resolved term: {result.get('resolved_term')}")
    print(f"  Rewritten: '{result.get('rewritten_query')}'")

    if result.get("has_ambiguous_reference"):
        print("  ✅ PASS - Detected implicit reference")
    else:
        print("  ❌ FAIL - Did not detect implicit reference")

    # Test Case 5: Empty conversation history
    print_test_case(5, "Empty conversation history")

    query_5 = "explain the concept"
    print(f"\nUser query: '{query_5}'")
    result = client.rewrite_query_with_context(query_5, [])

    print(f"  Has reference: {result.get('has_ambiguous_reference')}")
    print(f"  Rewritten: '{result.get('rewritten_query')}'")

    if result.get("rewritten_query") == query_5:
        print("  ✅ PASS - Returned original query (no history)")
    else:
        print("  ❌ FAIL - Should return original when no history")

    # Test Case 6: Multiple numbered list styles
    print_test_case(6, "Different numbering styles (1), 2:, 3-)")

    conversation_history_6 = [
        {"role": "user", "content": "give me key concepts"},
        {
            "role": "assistant",
            "content": """Key concepts:
1) Turboprops vs turbojets - efficiency comparison
2: Propeller control systems - constant speed mechanisms
3 - Flight instrumentation - six-pack layout""",
        },
    ]

    test_queries_6 = [
        ("tell me about topic 2", "Propeller control"),
        ("explain the first one", "Turboprops"),
        ("what about number 3?", "Flight instrumentation"),
    ]

    for query, expected_term in test_queries_6:
        print(f"\nUser query: '{query}'")
        result = client.rewrite_query_with_context(query, conversation_history_6)

        print(f"  Has reference: {result.get('has_ambiguous_reference')}")
        print(f"  Resolved term: {result.get('resolved_term')}")
        print(f"  Rewritten: '{result.get('rewritten_query')}'")

        if result.get("has_ambiguous_reference"):
            print(f"  ✅ PASS - Detected reference")
        else:
            print(f"  ❌ FAIL - Did not detect reference")

    # Summary
    print_section("TEST SUMMARY")
    print("\n✅ All tests completed!")
    print("\nIf you see:")
    print("  - ✅ PASS: Query rewriter is working correctly")
    print("  - ❌ FAIL: Query rewriter needs debugging")
    print("\nCheck the rewritten queries to verify they extracted the correct topics.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    print("\n" + "🧪" * 40)
    print("  QUERY REWRITER TEST SUITE")
    print("  Testing numbered reference detection and rewriting")
    print("🧪" * 40)

    try:
        test_query_rewriter()
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()
