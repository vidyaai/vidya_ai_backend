#!/usr/bin/env python3
"""
Test script for diagram upload endpoints
Usage: python test_diagram_upload.py
"""

import requests
import json
import os
from pathlib import Path

# Configuration
BASE_URL = "http://localhost:8000"  # Update with your server URL
TEST_IMAGE_PATH = "test_diagram.png"  # You'll need to create this file

# Test data
FIREBASE_TOKEN = "your_firebase_token_here"  # Replace with actual token
ASSIGNMENT_ID = "test_assignment_id"  # Replace with actual assignment ID


def create_test_image():
    """Create a simple test image for upload"""
    try:
        from PIL import Image, ImageDraw

        # Create a simple test image
        img = Image.new("RGB", (300, 200), color="white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([50, 50, 250, 150], outline="black", width=2)
        draw.text((100, 100), "Test Diagram", fill="black")
        img.save(TEST_IMAGE_PATH)
        print(f"Created test image: {TEST_IMAGE_PATH}")
        return True
    except ImportError:
        print("PIL not available, creating dummy file")
        with open(TEST_IMAGE_PATH, "wb") as f:
            f.write(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\x12IDATx\x9cc```bPPP\x00\x02\xd2\x00\x00\x00\xffAv\x9f\x00\x00\x00\x00IEND\xaeB`\x82"
            )
        return True
    except Exception as e:
        print(f"Error creating test image: {e}")
        return False


def test_upload_diagram():
    """Test diagram upload endpoint"""
    print("\n=== Testing Diagram Upload ===")

    if not os.path.exists(TEST_IMAGE_PATH):
        if not create_test_image():
            print("Failed to create test image")
            return None

    # Prepare request
    headers = {"Authorization": f"Bearer {FIREBASE_TOKEN}"}

    with open(TEST_IMAGE_PATH, "rb") as f:
        files = {"file": ("test_diagram.png", f, "image/png")}

        # Test without assignment_id
        response = requests.post(
            f"{BASE_URL}/api/assignments/upload-diagram", headers=headers, files=files
        )

    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

    if response.status_code == 200:
        return response.json()["file_id"]
    return None


def test_serve_diagram(file_id):
    """Test diagram serving endpoint"""
    print("\n=== Testing Diagram Serving ===")

    headers = {"Authorization": f"Bearer {FIREBASE_TOKEN}"}

    response = requests.get(
        f"{BASE_URL}/api/assignments/diagrams/{file_id}",
        headers=headers,
        allow_redirects=False,
    )

    print(f"Status Code: {response.status_code}")
    if response.status_code == 302:
        print(f"Redirect URL: {response.headers.get('Location')}")
    else:
        print(f"Response: {response.text}")


def test_delete_diagram(file_id):
    """Test diagram deletion endpoint"""
    print("\n=== Testing Diagram Deletion ===")

    headers = {"Authorization": f"Bearer {FIREBASE_TOKEN}"}

    response = requests.delete(
        f"{BASE_URL}/api/assignments/diagrams/{file_id}", headers=headers
    )

    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")


def main():
    """Run all tests"""
    print("Testing Diagram Upload API Endpoints")
    print("=" * 40)

    # Check if server is running
    try:
        response = requests.get(f"{BASE_URL}/docs")
        if response.status_code != 200:
            print(f"Server not responding at {BASE_URL}")
            return
    except requests.exceptions.ConnectionError:
        print(f"Cannot connect to server at {BASE_URL}")
        print("Make sure the backend server is running")
        return

    # Run tests
    file_id = test_upload_diagram()

    if file_id:
        test_serve_diagram(file_id)
        test_delete_diagram(file_id)
    else:
        print("Upload failed, skipping other tests")

    # Cleanup
    if os.path.exists(TEST_IMAGE_PATH):
        os.remove(TEST_IMAGE_PATH)
        print(f"\nCleaned up test file: {TEST_IMAGE_PATH}")


if __name__ == "__main__":
    main()
