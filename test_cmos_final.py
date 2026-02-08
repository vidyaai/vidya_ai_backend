"""Final comprehensive test for CMOS question generation"""
import os
import sys
import json
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

load_dotenv()

from utils.assignment_generator import AssignmentGenerator

def test_various_prompts():
    """Test multiple prompts to ensure specificity"""
    
    generator = AssignmentGenerator()
    
    test_cases = [
        {
            "prompt": "generate an undergrad level question on cmos push pull to test knowledge on how logic gates are implemented using cmos circuits",
            "expected_keywords": ["cmos", "pmos", "nmos", "transistor", "pull", "gate", "logic"],
            "forbidden_keywords": ["power factor", "ice cream", "drowning", "correlation"]
        },
        {
            "prompt": "create a question about binary search tree insertion",
            "expected_keywords": ["binary", "tree", "node", "insert"],
            "forbidden_keywords": ["cmos", "power", "circuit"]
        }
    ]
    
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
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'='*80}")
        print(f"Test Case {i}")
        print(f"{'='*80}")
        print(f"Prompt: {test_case['prompt']}")
        print(f"Expected keywords: {', '.join(test_case['expected_keywords'])}")
        print(f"Forbidden keywords: {', '.join(test_case['forbidden_keywords'])}")
        
        try:
            result = generator.generate_assignment(
                generation_options=generation_options,
                linked_videos=None,
                uploaded_files=None,
                generation_prompt=test_case['prompt'],
                title=f"Test Assignment {i}",
                description=f"Test for: {test_case['prompt'][:50]}"
            )
            
            question = result.get("questions", [])[0]
            question_text = (question.get("question", "") + " " + 
                           question.get("text", "") + " " +
                           str(question.get("options", [])) + " " +
                           question.get("explanation", "")).lower()
            
            # Check for expected keywords
            found_expected = [kw for kw in test_case['expected_keywords'] if kw.lower() in question_text]
            found_forbidden = [kw for kw in test_case['forbidden_keywords'] if kw.lower() in question_text]
            
            print(f"\n✓ Question Generated:")
            print(f"  - Question field: {question.get('question', 'N/A')[:100]}...")
            print(f"  - Text field: {question.get('text', 'N/A')[:100]}...")
            
            if found_expected:
                print(f"\n✅ PASS: Found expected keywords: {', '.join(found_expected)}")
            else:
                print(f"\n⚠️  WARNING: No expected keywords found!")
            
            if found_forbidden:
                print(f"❌ FAIL: Found forbidden keywords: {', '.join(found_forbidden)}")
            else:
                print(f"✅ PASS: No forbidden keywords found")
            
            print(f"\n📝 Full Question:")
            print(f"Type: {question.get('type')}")
            print(f"Question: {question.get('question', 'N/A')}")
            print(f"Text: {question.get('text', 'N/A')}")
            if question.get('options'):
                for j, opt in enumerate(question.get('options', []), 1):
                    print(f"  {j}. {opt}")
            print(f"Correct: {question.get('correctAnswer')}")
            print(f"Explanation: {question.get('explanation', 'N/A')[:200]}...")
            
        except Exception as e:
            print(f"\n❌ Error: {str(e)}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    test_various_prompts()
