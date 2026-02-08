"""Test script for assignment generator"""
import os
import sys
import json
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

load_dotenv()

from utils.assignment_generator import AssignmentGenerator

def test_cmos_question():
    """Test generating CMOS push-pull question"""
    
    generator = AssignmentGenerator()
    
    generation_options = {
        "numQuestions": 1,
        "engineeringLevel": "undergraduate",
        "engineeringDiscipline": "electronics",
        "questionTypes": {
            "multiple-choice": True,
            "short-answer": False,
            "long-answer": False,
            "true-false": False,
            "multi-part": False
        },
        "difficultyLevel": "medium",
        "totalPoints": 10
    }
    
    generation_prompt = "generate an undergrad level question on cmos push pull to test knowledge on how logic gates are implemented using cmos circuits"
    
    print("=" * 80)
    print("Testing Assignment Generation")
    print("=" * 80)
    print(f"Prompt: {generation_prompt}")
    print(f"Options: {json.dumps(generation_options, indent=2)}")
    print("=" * 80)
    
    try:
        result = generator.generate_assignment(
            generation_options=generation_options,
            linked_videos=None,
            uploaded_files=None,
            generation_prompt=generation_prompt,
            title="Test CMOS Assignment",
            description="Test assignment for CMOS circuits"
        )
        
        print("\n✅ Generation successful!")
        print("\nGenerated Questions:")
        print("-" * 80)
        for i, question in enumerate(result.get("questions", []), 1):
            print(f"\nQuestion {i}:")
            print(f"Type: {question.get('type')}")
            print(f"Text: {question.get('text')}")
            if question.get('options'):
                print(f"Options: {question.get('options')}")
            print(f"Correct Answer: {question.get('correctAnswer')}")
            print(f"Explanation: {question.get('explanation')}")
        
        return result
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    test_cmos_question()
