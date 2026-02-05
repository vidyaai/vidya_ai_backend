#!/usr/bin/env python3
"""
Installation script for PDF generation dependencies.
This script installs the additional packages needed for IEEE-style PDF generation.
"""

import subprocess
import sys
import os


def install_package(package):
    """Install a package using pip."""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        return True
    except subprocess.CalledProcessError:
        return False


def main():
    print("🔧 Installing PDF generation dependencies...")
    print("=" * 50)

    # PDF generation packages
    packages = [
        "weasyprint==61.2",
        "markdown==3.6",
        "matplotlib==3.8.0",
        "requests==2.31.0",
    ]

    success_count = 0

    for package in packages:
        package_name = package.split("==")[0]
        print(f"\n📦 Installing {package_name}...")

        if install_package(package):
            print(f"✅ {package_name} installed successfully")
            success_count += 1
        else:
            print(f"❌ Failed to install {package_name}")

    print("\n" + "=" * 50)

    if success_count == len(packages):
        print("🎉 All PDF generation dependencies installed successfully!")
        print("\n💡 You can now generate IEEE-style PDFs using:")
        print("   • python generate_pdf.py <markdown_file>")
        print("   • python generate_pdf.py --all (for all files in output/)")
        print("   • Run main.py and choose 'y' when prompted for PDF generation")
    else:
        print(f"⚠️  {success_count}/{len(packages)} packages installed successfully")
        print("Some packages failed to install. Please check the error messages above.")

    print("\n📋 Note: WeasyPrint requires system dependencies.")
    print(
        "If installation fails, please refer to: https://doc.courtbouillon.org/weasyprint/stable/first_steps.html"
    )


if __name__ == "__main__":
    main()
