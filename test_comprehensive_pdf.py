#!/usr/bin/env python3
"""
Comprehensive test for the improved PDF generator with equation placeholders.
Tests both direct LaTeX and the existing <eq id> system.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from utils.pdf_generator import AssignmentPDFGenerator

def create_comprehensive_test_assignment():
    """Create a test assignment with various equation formats."""
    return {
        "title": "Professional Mathematics Assignment",
        "description": r"""
        This assignment demonstrates various mathematical notation formats.
        Solve all problems showing complete work for full credit.
        
        **Important:** Use proper mathematical notation in your solutions.
        """,
        "total_points": 150,
        "questions": [
            {
                "question": r"""
                Solve the quadratic equation: $$x^2 - 4x + 3 = 0$$
                
                Use the quadratic formula: $x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$
                
                Show all steps clearly.
                """,
                "type": "long-answer",
                "points": 25,
                "difficulty": "easy"
            },
            {
                "question": r"""
                Evaluate the integral: $$\int x^2 \sin(x) \, dx$$
                
                Use integration by parts: $\int u \, dv = uv - \int v \, du$
                """,
                "type": "long-answer", 
                "points": 30,
                "difficulty": "hard"
            },
            {
                "question": r"Find $\lim_{x \to 0} \frac{\sin(3x)}{x}$",
                "type": "short-answer",
                "points": 15,
                "difficulty": "medium"
            },
            {
                "question": r"What is the derivative of $f(x) = x^3 \cos(x)$?",
                "type": "multiple-choice",
                "points": 20,
                "difficulty": "medium",
                "options": [
                    r"$3x^2 \cos(x) - x^3 \sin(x)$",
                    r"$3x^2 \cos(x) + x^3 \sin(x)$", 
                    r"$x^2 \cos(x) - 3x^3 \sin(x)$",
                    r"$3x^2 \sin(x) + x^3 \cos(x)$"
                ]
            },
            {
                "question": """
                Consider the physics problem with equation <eq physics1>.
                
                Given initial velocity <eq physics2> and acceleration <eq physics3>,
                find the final velocity using <eq physics4>.
                """,
                "equations": [
                    {"id": "physics1", "latex": "v_f^2 = v_i^2 + 2a\\Delta x", "type": "inline"},
                    {"id": "physics2", "latex": "v_i = 10 \\text{ m/s}", "type": "inline"},
                    {"id": "physics3", "latex": "a = 5 \\text{ m/s}^2", "type": "inline"},
                    {"id": "physics4", "latex": "\\Delta x = 20 \\text{ m}", "type": "inline"}
                ],
                "type": "long-answer",
                "points": 25,
                "difficulty": "medium"
            },
            {
                "question": r"""
                Prove that for any triangle with sides $a$, $b$, $c$:
                
                $$\cos(C) = \frac{a^2 + b^2 - c^2}{2ab}$$
                
                This is known as the Law of Cosines.
                """,
                "type": "long-answer",
                "points": 35,
                "difficulty": "hard"
            }
        ]
    }

def main():
    """Generate comprehensive test PDF."""
    print("Creating comprehensive mathematics assignment PDF...")
    
    # Create PDF generator
    generator = AssignmentPDFGenerator()
    
    # Create test assignment
    assignment = create_comprehensive_test_assignment()
    
    # Generate PDF
    try:
        pdf_content = generator.generate_assignment_pdf(assignment)
        
        # Save to file
        output_file = "comprehensive_math_assignment.pdf"
        with open(output_file, 'wb') as f:
            f.write(pdf_content)
        
        print(f"✅ PDF generated successfully: {output_file}")
        print(f"📄 File size: {len(pdf_content):,} bytes")
        
        # Clean up
        generator.cleanup()
        
        print("\n🎯 Features Demonstrated:")
        print("✓ Professional LaTeX equation rendering")
        print("✓ Display equations (centered)")
        print("✓ Inline equations (in-text)")
        print("✓ Mathematical symbols and operators")
        print("✓ Equation placeholder system (<eq id>)")
        print("✓ Research paper formatting")
        print("✓ Multiple choice with equations")
        print("✓ Professional typography")
        
        print(f"\n📖 Open {output_file} to see the results!")
        
    except Exception as e:
        print(f"❌ Error generating PDF: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()