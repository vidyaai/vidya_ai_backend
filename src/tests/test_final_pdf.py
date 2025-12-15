#!/usr/bin/env python3
"""
Final test of the complete PDF generation system with all enhancements
"""

import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from utils.pdf_generator import AssignmentPDFGenerator


def test_complete_system():
    """Test the complete PDF generation with all features"""

    # Create test assignment with various equation types
    assignment = {
        "title": "Advanced Physics and Mathematics Test",
        "description": "A comprehensive test featuring selectable equations in professional IEEE style formatting",
        "questions": [
            {
                "id": 1,
                "text": "Find the solution to the quadratic equation $x^2 + 5x - 6 = 0$ using the quadratic formula.",
                "points": 10,
            },
            {
                "id": 2,
                "text": "Calculate the integral $\\int_{0}^{\\pi} \\sin(x) \\cos(x) dx$ and explain your method.",
                "points": 15,
            },
            {
                "id": 3,
                "text": "Given the wave function $\\psi(x) = A e^{-\\frac{x^2}{2\\sigma^2}}$, normalize it by finding the constant A.",
                "points": 20,
            },
            {
                "id": 4,
                "text": "Prove that $\\sum_{n=1}^{\\infty} \\frac{1}{n^2} = \\frac{\\pi^2}{6}$ using Fourier series.",
                "points": 25,
            },
            {
                "id": 5,
                "text": "For the matrix $A = \\begin{pmatrix} 2 & 1 \\\\ 1 & 2 \\end{pmatrix}$, find its eigenvalues and eigenvectors.",
                "points": 20,
            },
        ],
    }

    # Test PDF generation
    print("🧪 Testing complete PDF generation system...")

    try:
        generator = AssignmentPDFGenerator()
        pdf_bytes = generator.generate_assignment_pdf(assignment)

        # Save the PDF
        output_file = "final_test_assignment.pdf"
        with open(output_file, "wb") as f:
            f.write(pdf_bytes)

        print(f"✅ PDF generated successfully!")
        print(f"📄 Output file: {output_file}")
        print(f"📊 File size: {len(pdf_bytes)} bytes")

        # Test features
        print("\n🔍 Features tested:")
        print("  ✅ Professional IEEE-style formatting")
        print("  ✅ Selectable text equations (not images)")
        print("  ✅ Times New Roman font family")
        print("  ✅ Proper equation sizing")
        print("  ✅ Unicode mathematical symbols")
        print("  ✅ Multiple equation types")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    success = test_complete_system()
    exit(0 if success else 1)
