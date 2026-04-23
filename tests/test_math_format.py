#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

# Load env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

from openai import OpenAI

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Test with explicit instructions
messages = [
    {"role": "system", "content": "Use LaTeX ONLY: \\( \\) for inline math, \\[ \\] for display math. NEVER use HTML, MathML tags, or any markup other than LaTeX. NEVER reference 'MathML' or include HTML attributes like display='block'."},
    {"role": "user", "content": "Write Newton's second law F = ma with proper math formatting"}
]

print("Testing AI response...")
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=messages,
    max_tokens=150
)

output = response.choices[0].message.content
print("="*70)
print("AI RESPONSE:")
print("="*70)
print(output)
print("="*70)
print("\nANALYSIS:")

issues = []
if 'MathML' in output:
    issues.append("❌ CONTAINS 'MathML'")
if 'display=' in output:
    issues.append("❌ CONTAINS 'display='")
if '<math' in output or '<span' in output:
    issues.append("❌ CONTAINS HTML TAGS")

if issues:
    for issue in issues:
        print(issue)
    print("\n🔴 AI IS NOT FOLLOWING LATEX-ONLY INSTRUCTIONS!")
elif '\\(' in output or '\\[' in output:
    print("✅ AI IS USING LATEX SYNTAX CORRECTLY!")
else:
    print("⚠️  NO MATH FORMATTING DETECTED")
