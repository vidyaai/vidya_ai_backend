#!/usr/bin/env python3
"""
Test script for selectable text equations instead of images.
"""

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from utils.pdf_generator import AssignmentPDFGenerator


def create_selectable_math_test():
    """Create a test with selectable mathematical text."""
    return {
        "title": "Selectable Mathematics Test",
        "description": "This test demonstrates selectable mathematical expressions that can be copied and edited.",
        "total_points": 100,
        "questions": [
            {
                "question": r"Solve the quadratic equation $x^2 - 5x + 6 = 0$ using the quadratic formula $x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$.",
                "type": "short-answer",
                "points": 20,
                "difficulty": "medium",
            },
            {
                "question": r"Calculate the integral: $$\int_0^\pi \sin(x) dx$$",
                "type": "short-answer",
                "points": 20,
                "difficulty": "medium",
            },
            {
                "question": r"Find the limit $\lim_{x \to 0} \frac{\sin(x)}{x}$ and explain why it equals 1.",
                "type": "long-answer",
                "points": 25,
                "difficulty": "medium",
            },
            {
                "question": r"Given the function $f(x) = x^3 + 2x^2 - 5x + 3$, find $f'(x)$.",
                "type": "multiple-choice",
                "points": 15,
                "difficulty": "easy",
                "options": [
                    r"$3x^2 + 4x - 5$",
                    r"$3x^2 + 4x + 5$",
                    r"$x^4 + 2x^3 - 5x^2 + 3x$",
                    r"$3x^2 - 4x - 5$",
                ],
            },
            {
                "question": r"""Physics problem: A ball is thrown with initial velocity $v_0 = 20 \text{ m/s}$ at angle $\theta = 45°$.

                The position equations are:
                $$x(t) = v_0 \cos(\theta) \cdot t$$
                $$y(t) = v_0 \sin(\theta) \cdot t - \frac{1}{2}gt^2$$

                Where $g = 9.8 \text{ m/s}^2$. Find the maximum height reached.""",
                "type": "long-answer",
                "points": 20,
                "difficulty": "hard",
            },
        ],
    }


def main():
    """Generate test with selectable mathematical text."""
    print("Creating mathematics test with selectable equations...")

    # Create PDF generator
    generator = AssignmentPDFGenerator()

    # Create test assignment
    assignment = create_selectable_math_test()

    # Generate PDF
    try:
        pdf_content = generator.generate_assignment_pdf(assignment)

        # Save to file
        output_file = "selectable_math_test.pdf"
        with open(output_file, "wb") as f:
            f.write(pdf_content)

        print(f"✅ Selectable math test generated: {output_file}")
        print(f"📄 File size: {len(pdf_content):,} bytes")

        # Clean up
        generator.cleanup()

        print("\n🎯 New Features:")
        print("✓ All equations are selectable text (not images)")
        print("✓ Professors can copy and paste equations")
        print("✓ Better accessibility for screen readers")
        print("✓ Smaller file sizes (no embedded images)")
        print("✓ Professional mathematical typography")
        print("✓ Unicode mathematical symbols")
        print("✓ Proper fraction and superscript formatting")

        print(f"\n📖 Open {output_file} and try selecting the mathematical text!")

    except Exception as e:
        print(f"❌ Error generating PDF: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
