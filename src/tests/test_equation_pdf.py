#!/usr/bin/env python3
"""
Test script for the improved equation rendering in PDF generation.
This script creates a sample assignment with various mathematical equations
to test the professional LaTeX-style rendering.
"""

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from utils.pdf_generator import AssignmentPDFGenerator


def create_test_assignment():
    """Create a test assignment with various types of mathematical equations."""
    return {
        "title": "Mathematics Test Assignment - Equation Rendering Demo",
        "description": """
        This assignment demonstrates professional equation rendering in PDF documents.
        All equations should appear with research paper quality formatting.

        Please solve the following problems showing all work clearly.
        """,
        "total_points": 100,
        "questions": [
            {
                "question": r"""
                Solve the quadratic equation: $$x^2 + 5x + 6 = 0$$

                Use the quadratic formula: $x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$

                Where $a = 1$, $b = 5$, and $c = 6$.
                """,
                "type": "long-answer",
                "points": 25,
                "difficulty": "medium",
            },
            {
                "question": r"""
                Calculate the definite integral:
                $$\int_0^{\pi} \sin(x) \, dx$$

                Show all steps in your calculation.
                """,
                "type": "long-answer",
                "points": 20,
                "difficulty": "medium",
            },
            {
                "question": r"""
                Find the limit: $\lim_{x \to 0} \frac{\sin(x)}{x}$

                You may use L'Hôpital's rule or the standard limit identity.
                """,
                "type": "short-answer",
                "points": 15,
                "difficulty": "easy",
            },
            {
                "question": r"""
                Given the system of linear equations:
                $$2x + y = 5$$
                $$x + 3y = 7$$

                Find the values of $x$ and $y$.
                """,
                "type": "long-answer",
                "points": 25,
                "difficulty": "hard",
            },
            {
                "question": r"What is the value of $e^{i\pi} + 1$?",
                "type": "multiple-choice",
                "points": 15,
                "difficulty": "easy",
                "options": ["$0$", "$1$", "$-1$", "$i$"],
            },
        ],
    }


def main():
    """Generate and save test PDF."""
    print("Creating test assignment with professional equation rendering...")

    # Create PDF generator
    generator = AssignmentPDFGenerator()

    # Create test assignment
    assignment = create_test_assignment()

    # Generate PDF
    try:
        pdf_content = generator.generate_assignment_pdf(assignment)

        # Save to file
        output_file = "test_equations_output.pdf"
        with open(output_file, "wb") as f:
            f.write(pdf_content)

        print(f"✅ PDF generated successfully: {output_file}")
        print(f"📄 File size: {len(pdf_content)} bytes")

        # Clean up
        generator.cleanup()

        print("\n📋 Test Summary:")
        print("- Display equations ($$...$$) should be centered")
        print("- Inline equations ($...$) should be properly aligned")
        print("- All equations should have professional LaTeX typography")
        print("- Mathematical symbols should be crisp and clear")
        print("- Font styling should match research paper standards")

    except Exception as e:
        print(f"❌ Error generating PDF: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
