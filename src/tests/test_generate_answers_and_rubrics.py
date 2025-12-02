#!/usr/bin/env python3
"""
Test for _generate_missing_answers_and_rubrics function in AssignmentDocumentParser.

Uses Q2.json as input data - calls real GPT APIs.
"""
import dotenv

dotenv.load_dotenv()

import json
import sys
from pathlib import Path

# Add src directory to Python path
src_dir = Path(__file__).parent.parent
sys.path.insert(0, str(src_dir))

from PIL import Image
from utils.assignment_document_parser import AssignmentDocumentParser


# Load Q2.json
Q2_JSON_PATH = "src/tests/test_files/Q2.json"


def test_generate_missing_answers_and_rubrics():
    """
    Test _generate_missing_answers_and_rubrics using Q2.json data.
    Calls real GPT APIs to generate answers.
    """
    # Load Q2.json
    with open(Q2_JSON_PATH, "r", encoding="utf-8") as f:
        input_data = json.load(f)

    # mock images
    image_files = [
        "src/tests/test_files/Q2/page_1.png",
        "src/tests/test_files/Q2/page_2.png",
    ]  # list of image file paths corresponding to input_data
    images = [Image.open(img_path) for img_path in image_files]

    # Create parser and call function
    parser = AssignmentDocumentParser(user_id=123)
    result = parser._generate_missing_answers_and_rubrics(input_data, images)
    result = parser._normalize_assignment_data(
        result, "generate_missing_answers_and_rubrics_test"
    )

    # Print results
    print(f"\nTitle: {result['title']}")
    print(f"Total questions: {len(result['questions'])}")

    for q in result["questions"]:
        print(f"\nQ{q['id']}:")
        for sub in q.get("subquestions", []):
            answer = sub.get("correctAnswer", "")[:100]
            rubric = sub.get("rubric", "")[:50]
            equations = sub.get("equations", [])
            if equations:
                print(
                    f"  {sub['id']}: answer={answer}... rubric={rubric}... equations={equations}..."
                )
            else:
                print(f"  {sub['id']}: answer={answer}... rubric={rubric}...")

    return result


if __name__ == "__main__":
    test_generate_missing_answers_and_rubrics()
