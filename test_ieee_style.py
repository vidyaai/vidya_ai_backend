#!/usr/bin/env python3
"""
Test script for IEEE-style professional question paper generation.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from utils.pdf_generator import AssignmentPDFGenerator

def create_ieee_style_assignment():
    """Create a professional IEEE-style question paper."""
    return {
        "title": "Mathematics Examination",
        "description": "Answer all questions. Time allowed: 3 hours.",
        "total_points": 100,
        "questions": [
            {
                "question": r"Solve the quadratic equation $x^2 - 5x + 6 = 0$.",
                "type": "short-answer",
                "points": 10,
                "difficulty": "easy"
            },
            {
                "question": r"Evaluate the integral $\int_0^1 x^2 dx$.",
                "type": "short-answer", 
                "points": 15,
                "difficulty": "medium"
            },
            {
                "question": r"Find the limit $\lim_{x \to 0} \frac{\sin(x)}{x}$.",
                "type": "short-answer",
                "points": 15,
                "difficulty": "medium"
            },
            {
                "question": r"What is the derivative of $f(x) = x^3 + 2x^2 - x + 5$?",
                "type": "multiple-choice",
                "points": 10,
                "difficulty": "easy",
                "options": [
                    r"$3x^2 + 4x - 1$",
                    r"$3x^2 + 4x + 1$", 
                    r"$x^4 + 2x^3 - x^2 + 5x$",
                    r"$3x^2 - 4x - 1$"
                ]
            },
            {
                "question": r"""A particle moves according to the equation $s(t) = 3t^2 - 2t + 1$, where $s$ is displacement in meters and $t$ is time in seconds. Find the velocity at $t = 2$ seconds.""",
                "type": "long-answer",
                "points": 20,
                "difficulty": "medium"
            },
            {
                "question": r"""Given the system of equations:
                $$2x + y = 7$$
                $$x - y = 2$$
                Solve for $x$ and $y$.""",
                "type": "long-answer",
                "points": 15,
                "difficulty": "easy"
            },
            {
                "question": r"Prove that $\frac{d}{dx}[\sin(x)] = \cos(x)$ using the definition of derivative.",
                "type": "long-answer",
                "points": 15,
                "difficulty": "hard"
            }
        ]
    }

def main():
    """Generate IEEE-style professional question paper."""
    print("Creating IEEE-style mathematics question paper...")
    
    # Create PDF generator
    generator = AssignmentPDFGenerator()
    
    # Create test assignment
    assignment = create_ieee_style_assignment()
    
    # Generate PDF
    try:
        pdf_content = generator.generate_assignment_pdf(assignment)
        
        # Save to file
        output_file = "ieee_style_question_paper.pdf"
        with open(output_file, 'wb') as f:
            f.write(pdf_content)
        
        print(f"✅ IEEE-style question paper generated: {output_file}")
        print(f"📄 File size: {len(pdf_content):,} bytes")
        
        # Clean up
        generator.cleanup()
        
        print("\n🎯 IEEE Paper Features:")
        print("✓ Times New Roman font throughout")
        print("✓ Equations same size as text")
        print("✓ No answer spaces - clean question format")
        print("✓ Professional layout matching academic papers")
        print("✓ Justified text alignment")
        print("✓ Minimal margins and clean styling")
        
        print(f"\n📖 Open {output_file} to see the professional formatting!")
        
    except Exception as e:
        print(f"❌ Error generating PDF: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()