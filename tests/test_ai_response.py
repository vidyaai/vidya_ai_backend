#!/usr/bin/env python3
from openai import OpenAI
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from utils.system_prompt import SYSTEM_PROMPT_CONVERSATIONAL_INITIAL

client = OpenAI()

# Test prompt
messages = [
    {"role": "system", "content": SYSTEM_PROMPT_CONVERSATIONAL_INITIAL},
    {"role": "user", "content": "Explain the equation F = ma with proper formatting"}
]

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=messages,
    max_tokens=500,
    temperature=0.3
)

print("="*80)
print("AI RESPONSE:")
print("="*80)
print(response.choices[0].message.content)
print("="*80)
print("\nSearching for 'MathML' in response:")
if 'MathML' in response.choices[0].message.content:
    print("❌ FOUND 'MathML' - AI is ignoring instructions!")
else:
    print("✅ No 'MathML' found - AI is following instructions")
