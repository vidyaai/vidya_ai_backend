"""
Equation extraction service using GPT-4o with character position tracking
"""
import base64
import json
from typing import List, Dict, Any, Optional
from openai import OpenAI
from PIL import Image
from io import BytesIO
from controllers.config import logger


class EquationExtractor:
    """Extract equations from document images with character position metadata"""

    def __init__(self):
        self.client = OpenAI()
        self.model = "gpt-4o"

    def extract_equations_from_question(
        self,
        question_text: str,
        question_image: Optional[Image.Image] = None,
        question_id: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Extract equations from question text with character positions.

        Args:
            question_text: The full question text
            question_image: Optional image if visual parsing is needed
            question_id: Question ID for equation ID generation

        Returns:
            List of equation metadata with character positions
        """

        prompt = f"""
Analyze this question text and extract ALL mathematical equations, formulas, and expressions.

Question text:
{question_text}

For each equation found, provide:
1. LaTeX representation of the equation
2. Character index: Count of characters in the question text BEFORE the equation starts
3. Type: "inline" (within text flow) or "display" (standalone block)
4. Context: "question_text", "options", "explanation", or "subquestion"

IMPORTANT: Character index should be the exact position in the text where the equation begins.
For example, if text is "Calculate x where x + 5 = 10", the equation "x + 5 = 10" starts at character 20.

Return a JSON object with an "equations" array.

Example output format:
{{
    "equations": [
        {{
            "latex": "x + 5 = 10",
            "char_index": 20,
            "type": "inline",
            "context": "question_text"
        }}
    ]
}}
"""

        # Build messages
        messages = [
            {
                "role": "system",
                "content": "You are an expert at identifying and extracting mathematical equations from text. You must accurately count character positions.",
            },
            {"role": "user", "content": [{"type": "text", "text": prompt}]},
        ]

        # Add image if provided (for visual equation detection)
        if question_image:
            buffered = BytesIO()
            question_image.save(buffered, format="PNG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            messages[1]["content"].append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_base64}"},
                }
            )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)
            equations = result.get("equations", [])

            # Add equation IDs and ensure position structure
            for i, eq in enumerate(equations):
                eq["id"] = f"eq_q{question_id}_{i+1}"
                # Ensure position structure
                if "char_index" in eq and "context" in eq:
                    eq["position"] = {
                        "char_index": eq.pop("char_index"),
                        "context": eq.pop("context"),
                    }

            logger.info(
                f"Extracted {len(equations)} equations from question {question_id}"
            )
            return equations

        except Exception as e:
            logger.error(f"Error extracting equations from question {question_id}: {e}")
            return []

    def extract_equations_from_options(
        self, options: List[str], question_id: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Extract equations from multiple choice options.

        Args:
            options: List of option texts
            question_id: Question ID for equation ID generation

        Returns:
            List of equation metadata with option-relative character positions
        """
        all_equations = []

        for option_idx, option_text in enumerate(options):
            prompt = f"""
Extract any mathematical equations from this multiple choice option:

Option: {option_text}

Provide:
1. LaTeX representation
2. Character index within THIS option text
3. Type: "inline" or "display"

Return JSON with "equations" array.
"""

            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Extract equations from option text with accurate character positions.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                )

                result = json.loads(response.choices[0].message.content)
                equations = result.get("equations", [])

                for i, eq in enumerate(equations):
                    eq["id"] = f"eq_q{question_id}_opt{option_idx+1}_{i+1}"
                    eq["position"] = {
                        "char_index": eq.pop("char_index", 0),
                        "context": "options",
                        "option_index": option_idx,
                    }
                    all_equations.append(eq)

            except Exception as e:
                logger.error(
                    f"Error extracting equations from option {option_idx}: {e}"
                )
                continue

        return all_equations
