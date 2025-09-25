#!/usr/bin/env python3
"""
Simple test script to verify the assignment generation API is working
"""

import requests
import json

# Test data
test_data = {
    "generation_options": {
        "numQuestions": 3,
        "totalPoints": 15,
        "difficultyLevel": "mixed",
        "engineeringLevel": "undergraduate",
        "engineeringDiscipline": "computer",
        "questionTypes": {
            "multiple-choice": True,
            "short-answer": True,
            "code-writing": True,
        },
    },
    "generation_prompt": "Generate questions about machine learning fundamentals",
    "title": "Test Assignment",
    "description": "A test assignment for debugging",
}


def test_assignment_generation():
    """Test the assignment generation API"""
    print("Testing Assignment Generation API...")
    print("=" * 50)

    try:
        # Make API call (you'll need to replace with your actual backend URL)
        url = "http://localhost:8000/api/assignments/generate"

        # Note: This will fail without proper authentication, but we can see the error
        response = requests.post(url, json=test_data)

        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")

        if response.status_code == 200:
            result = response.json()
            print("✅ API call successful!")
            print(f"Generated assignment: {result.get('title', 'No title')}")
            print(f"Number of questions: {len(result.get('questions', []))}")
        else:
            print("❌ API call failed")
            print(f"Error: {response.text}")

    except requests.exceptions.ConnectionError:
        print("❌ Connection failed - is the backend server running?")
    except Exception as e:
        print(f"❌ Error: {str(e)}")


if __name__ == "__main__":
    test_assignment_generation()
