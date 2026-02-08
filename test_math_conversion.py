"""Test math notation conversion"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.pdf_generator import AssignmentPDFGenerator

def test_conversion():
    generator = AssignmentPDFGenerator()
    
    # Test the exact question 8 text
    question_8 = "Temperature effect. A manometer at 20°C has ρ_o = 850 kg/m^3, ρ_w = 1000 kg/m^3, ρ_Hg = 13600 kg/m^3, with h_o = 0.20 m, h_w = 0.25 m, Δz = 0.04 m. The indicated gauge pressure at 20°C is p_20. The temperature rises to 50°C; assume densities change approximately as ρ(T) ≈ ρ_20[1 − βΔT], with β_o = 7.0×10^−4 °C^−1, β_w = 2.0×10^−4 °C^−1, β_Hg = 1.2×10^−4 °C^−1. If the column heights remain the same, estimate the change in indicated pressure Δp = p_50 − p_20 and the percent change relative to p_20."
    
    other_tests = [
        "Power factor is 0.95 lagging at X_L = 40 Ω",
        "Temperature is 25°C with Δz = 0.04 m",
        "The equation is V_out/V_in = R_f/R_in",
        "Scientific notation: 3.5×10^−6 and 2.1×10^8"
    ]
    
    print("Testing Math Notation Conversion")
    print("=" * 80)
    
    print("\n=== Question 8 Test ===")
    print(f"Input:\n{question_8}\n")
    converted = generator.convert_text_math_to_latex(question_8)
    print(f"Output:\n{converted}\n")
    
    print("\n=== Other Tests ===")
    for i, test in enumerate(other_tests, 1):
        print(f"\nTest {i}:")
        print(f"Input:  {test}")
        converted = generator.convert_text_math_to_latex(test)
        print(f"Output: {converted}")

if __name__ == "__main__":
    test_conversion()
