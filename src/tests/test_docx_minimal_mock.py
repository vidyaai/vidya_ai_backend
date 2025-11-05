#!/usr/bin/env python3
"""
Minimal DOCX endpoint test - only mock authentication, let everything else run normally
"""

import base64
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

# Add src directory to Python path
src_dir = Path(__file__).parent.parent
sys.path.insert(0, str(src_dir))


def test_docx_endpoint_minimal_mock():
    """Test DOCX endpoint with minimal mocking - only auth"""
    print("Testing DOCX Endpoint with Minimal Mocking (Auth Only)")
    print("=" * 60)

    # Create test_files directory if it doesn't exist
    test_files_dir = Path("E:/VidyAI/Dev/vidya_ai_backend/src/tests/test_files")
    test_files_dir.mkdir(exist_ok=True)

    # Look for DOCX files
    docx_files = list(test_files_dir.glob("*.docx"))

    if not docx_files:
        print(f"❌ No DOCX files found in test_files directory {test_files_dir}")
        return False

    print(f"Found {len(docx_files)} DOCX files to test:")
    for file_path in docx_files:
        print(f"  - {file_path}")

    # Only mock authentication - let everything else run normally
    with patch("utils.firebase_auth.ensure_firebase_initialized") as mock_firebase_init:
        # Setup auth mock
        mock_firebase_init.return_value = None

        # Import and setup app with dependency override
        from main import app
        from utils.firebase_auth import get_current_user

        def mock_get_current_user_override():
            return {"uid": "test_user_123"}

        # Override only the authentication dependency
        app.dependency_overrides[get_current_user] = mock_get_current_user_override

        try:
            # Create test client
            client = TestClient(app)

            passed = 0
            total = 0

            for file_path in docx_files:
                print(f"\n{'='*60}")
                print(f"Testing file: {file_path.name}")
                print(f"{'='*60}")

                try:
                    # Read the DOCX file
                    with open(file_path, "rb") as f:
                        docx_content = f.read()

                    print(f"✓ File loaded: {len(docx_content)} bytes")

                    # Test 1: File upload mode
                    print("\n1. Testing file upload mode...")
                    files = {
                        "file": (
                            file_path.name,
                            docx_content,
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        )
                    }
                    data = {
                        "file_name": file_path.name,
                        "file_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "generation_options": "{}",
                    }

                    response = client.post(
                        "/api/assignments/import-document", files=files, data=data
                    )

                    print(f"Response status: {response.status_code}")

                    if response.status_code == 200:
                        response_data = response.json()
                        print(f"✓ Success! Title: {response_data.get('title')}")
                        print(
                            f"✓ Questions extracted: {len(response_data.get('questions', []))}"
                        )
                        print(f"✓ File info: {response_data.get('file_info', {})}")

                        # Show actual questions if any
                        questions = response_data.get("questions", [])
                        if questions:
                            print(
                                f"✓ Sample question: {questions[0].get('question', '')[:100]}..."
                            )

                        passed += 1
                    else:
                        print(f"❌ Request failed: {response.text}")

                    total += 1

                    # Test 2: Base64 JSON mode
                    print("\n2. Testing base64 JSON mode...")
                    encoded_content = base64.b64encode(docx_content).decode("utf-8")
                    request_data = {
                        "file_content": encoded_content,
                        "file_name": file_path.name,
                        "file_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "generation_options": {},
                    }

                    response = client.post(
                        "/api/assignments/import-document", json=request_data
                    )

                    print(f"Response status: {response.status_code}")

                    if response.status_code == 200:
                        response_data = response.json()
                        print(f"✓ Success! Title: {response_data.get('title')}")
                        print(
                            f"✓ Questions extracted: {len(response_data.get('questions', []))}"
                        )
                        passed += 1
                    else:
                        print(f"❌ Request failed: {response.text}")

                    total += 1

                except Exception as e:
                    print(f"❌ Error processing {file_path.name}: {e}")
                    import traceback

                    traceback.print_exc()
                    total += 2  # Count both tests as failed

            print(f"\n{'='*60}")
            print(f"Test Results: {passed}/{total} tests passed")

            if passed == total:
                print("🎉 All tests passed! DOCX endpoint is working correctly.")
                return True
            else:
                print("⚠️  Some tests failed. Check the issues above.")
                return False

        finally:
            # Clean up dependency overrides
            app.dependency_overrides.clear()


if __name__ == "__main__":
    success = test_docx_endpoint_minimal_mock()
    sys.exit(0 if success else 1)
