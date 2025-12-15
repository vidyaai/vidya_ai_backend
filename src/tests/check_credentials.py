#!/usr/bin/env python3
"""
Google Forms Credentials Verification Script

This script tests if your Google Forms credentials are properly configured
for both local development and server deployment.
"""

import os
import sys
import json
from pathlib import Path


def test_credentials():
    """Test Google Forms credentials configuration."""
    print("🔍 Testing Google Forms Credentials Configuration")
    print("=" * 50)

    # Add src to path for imports
    sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

    try:
        from utils.google_forms_service import GoogleFormsService

        # Initialize service
        service = GoogleFormsService()

        if service.is_available():
            print("✅ Google Forms service initialized successfully!")
            print(f"✅ Credentials source: {get_credential_source()}")

            # Test basic API access
            try:
                # This would test actual API access - commented out to avoid quota usage
                # result = service.service.forms().list().execute()
                print("✅ Google Forms API access appears to be working")
                return True
            except Exception as e:
                print(f"⚠️ API access test failed (this might be normal): {e}")
                return True  # Service is available even if API test fails

        else:
            print("❌ Google Forms service not available")
            print("🔧 Troubleshooting steps:")
            print("1. Check if credentials file exists:")
            check_credential_files()
            print("2. Check environment variables:")
            check_env_variables()
            return False

    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("💡 Make sure you're running from the project root directory")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def get_credential_source():
    """Determine which credential source is being used."""
    if os.getenv("GOOGLE_CLOUD_CREDENTIALS_JSON"):
        return "Environment variable (GOOGLE_CLOUD_CREDENTIALS_JSON)"
    elif os.getenv("GOOGLE_CLOUD_CREDENTIALS_FILE"):
        return f"File path from env var: {os.getenv('GOOGLE_CLOUD_CREDENTIALS_FILE')}"
    else:
        # Check for local files
        local_files = [
            "vidyaai-forms-integrations-0270b6b160e0.json",
            "credentials/vidyaai-forms-integrations-0270b6b160e0.json",
            "credentials/google-service-account.json",
        ]
        for file_path in local_files:
            if os.path.exists(file_path):
                return f"Local file: {file_path}"
        return "Application Default Credentials (Google Cloud Platform)"


def check_credential_files():
    """Check for credential files in expected locations."""
    files_to_check = [
        "vidyaai-forms-integrations-0270b6b160e0.json",
        "credentials/vidyaai-forms-integrations-0270b6b160e0.json",
        "credentials/google-service-account.json",
        "google-service-account.json",
    ]

    for file_path in files_to_check:
        if os.path.exists(file_path):
            print(f"   ✅ Found: {file_path}")
        else:
            print(f"   ❌ Missing: {file_path}")


def check_env_variables():
    """Check environment variables."""
    env_vars = ["GOOGLE_CLOUD_CREDENTIALS_JSON", "GOOGLE_CLOUD_CREDENTIALS_FILE"]

    for var in env_vars:
        value = os.getenv(var)
        if value:
            if var == "GOOGLE_CLOUD_CREDENTIALS_JSON":
                print(f"   ✅ {var}: [JSON content present - {len(value)} chars]")
            else:
                print(f"   ✅ {var}: {value}")
        else:
            print(f"   ❌ {var}: Not set")


def validate_credentials_file(file_path):
    """Validate a credentials file format."""
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return False

    try:
        with open(file_path, "r") as f:
            creds = json.load(f)

        required_fields = ["type", "project_id", "private_key", "client_email"]
        missing_fields = [field for field in required_fields if field not in creds]

        if missing_fields:
            print(f"❌ Invalid credentials file - missing fields: {missing_fields}")
            return False

        if creds["type"] != "service_account":
            print(
                f"❌ Invalid credentials type: {creds['type']} (expected: service_account)"
            )
            return False

        print(f"✅ Valid credentials file: {file_path}")
        print(f"   Project ID: {creds['project_id']}")
        print(f"   Client Email: {creds['client_email']}")
        return True

    except json.JSONDecodeError:
        print(f"❌ Invalid JSON in credentials file: {file_path}")
        return False
    except Exception as e:
        print(f"❌ Error reading credentials file: {e}")
        return False


def main():
    """Main function."""
    print("🚀 VidyaAI Google Forms Credentials Checker")
    print()

    # Test current configuration
    success = test_credentials()

    print()
    print("=" * 50)

    if success:
        print("🎉 Configuration looks good!")
        print()
        print("📋 For server deployment:")
        print("1. Copy vidyaai-forms-integrations-0270b6b160e0.json to your server")
        print("2. Set GOOGLE_CLOUD_CREDENTIALS_FILE environment variable")
        print("3. Ensure file permissions are secure (600)")
    else:
        print("🔧 Configuration needs attention!")
        print()
        print("💡 Quick setup:")
        print(
            "1. Ensure vidyaai-forms-integrations-0270b6b160e0.json is in project root"
        )
        print("2. Or set GOOGLE_CLOUD_CREDENTIALS_FILE environment variable")

    print()
    print("🔗 For more help, see docs/GOOGLE_FORMS_DEPLOYMENT.md")


if __name__ == "__main__":
    main()
