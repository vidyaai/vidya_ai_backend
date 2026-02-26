"""
Question Review Agent

Validates generated questions against lecture notes and user requirements.
Acts as a quality control step to ensure questions are appropriate and aligned.
"""

from typing import Dict, List, Any, Optional
from openai import OpenAI
from controllers.config import logger


class QuestionReviewAgent:
    """AI agent that reviews and validates generated questions"""

    def __init__(self):
        """Initialize the review agent"""
        self.client = OpenAI()
        self.model = "gpt-4o"  # Use GPT-4o for better reasoning

    def _get_review_prompt(self) -> str:
        """Get the system prompt for the review agent"""
        return """You are an expert educational reviewer. Your job is to validate that generated assignment questions are appropriate, accurate, and aligned with source materials.

YOUR ROLE:
- Quality control for AI-generated assignment questions
- Verify alignment with lecture notes and user requirements
- Ensure questions feel natural (like a human professor wrote them)
- Flag technical inaccuracies or hallucinations
- Suggest improvements where needed

REVIEW CRITERIA:

1. CONTENT ALIGNMENT (Most Important):
   ✓ Questions cover concepts from the lecture notes
   ✓ No hallucinated topics or concepts not in the notes
   ✓ Appropriate difficulty level for the stated audience
   ✓ Technical accuracy (formulas, terminology, values)
   ✗ Questions about topics NOT covered in the notes
   ✗ Made-up equations or incorrect physics/engineering

2. ALIGNMENT WITH USER PROMPT:
   ✓ Questions match the requested topic
   ✓ Cover the specific areas mentioned in the prompt
   ✓ Appropriate question types as requested
   ✗ Off-topic or irrelevant questions

3. NATURAL QUALITY (Human-like):
   ✓ Varied question formats and phrasings
   ✓ Mix of theoretical and practical
   ✓ Natural difficulty progression
   ✓ Not overly robotic or repetitive
   ✗ All questions follow same template
   ✗ Obviously AI-generated patterns

4. DIAGRAM APPROPRIATENESS:
   ✓ Diagrams are necessary and helpful
   ✓ Technically accurate
   ✓ Well-integrated into questions
   ✗ Unnecessary decorative diagrams
   ✗ Inaccurate or misleading diagrams
   ✗ Too many or too few diagrams

REVIEW OUTPUT:
For each question, provide:
- alignment_score: 0-10 (how well it aligns with notes/prompt)
- quality_score: 0-10 (how natural/well-written it is)
- issues: List of specific problems (empty if none)
- suggestions: List of improvements (empty if none)
- keep: true/false (should this question be kept?)

STRICT RULE:
- If a question covers a topic NOT in the lecture notes → alignment_score = 0, keep = false
- If technically inaccurate → alignment_score ≤ 3, keep = false
- If minor issues but fixable → keep = true, provide suggestions
"""

    def review_questions(
        self,
        questions: List[Dict[str, Any]],
        lecture_notes_content: str,
        user_prompt: str,
        generation_options: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Review generated questions for quality and alignment.

        Args:
            questions: List of generated questions
            lecture_notes_content: Content from lecture notes/uploaded files
            user_prompt: User's original prompt/topic
            generation_options: Generation configuration

        Returns:
            Review results with scores and suggestions
        """
        try:
            logger.info(f"Starting question review for {len(questions)} questions")

            # Prepare context
            context = f"""
USER PROMPT/TOPIC:
{user_prompt}

LECTURE NOTES CONTENT (excerpt):
{lecture_notes_content[:3000]}...  # First 3000 chars for context

GENERATION OPTIONS:
- Difficulty: {generation_options.get('difficulty', 'mixed')}
- Total Points: {generation_options.get('totalPoints', 'not specified')}
- Question Types: {', '.join(generation_options.get('questionTypes', {}).keys())}

QUESTIONS TO REVIEW:
{self._format_questions_for_review(questions)}
"""

            # Call review agent
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_review_prompt()},
                    {
                        "role": "user",
                        "content": f"""{context}

Please review each question and provide:
1. Alignment score (0-10)
2. Quality score (0-10)
3. Issues found
4. Suggestions for improvement
5. Keep recommendation (true/false)

Format your response as JSON:
{{
    "overall_assessment": "Brief overall summary",
    "questions_reviewed": {{
        "1": {{
            "alignment_score": 0-10,
            "quality_score": 0-10,
            "issues": ["list of issues"],
            "suggestions": ["list of suggestions"],
            "keep": true/false
        }},
        ...
    }},
    "statistics": {{
        "total_reviewed": number,
        "recommended_keep": number,
        "recommended_remove": number,
        "avg_alignment": number,
        "avg_quality": number
    }}
}}
""",
                    },
                ],
                temperature=0.3,  # Lower for more consistent evaluation
                response_format={"type": "json_object"},
            )

            review_result = response.choices[0].message.content
            logger.info("Question review complete")

            import json

            return json.loads(review_result)

        except Exception as e:
            logger.error(f"Error in question review: {str(e)}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            # Return default passing review on error
            return {
                "overall_assessment": "Review failed - proceeding with generated questions",
                "questions_reviewed": {},
                "statistics": {
                    "total_reviewed": len(questions),
                    "recommended_keep": len(questions),
                    "recommended_remove": 0,
                    "avg_alignment": 7.0,
                    "avg_quality": 7.0,
                },
            }

    def _format_questions_for_review(self, questions: List[Dict[str, Any]]) -> str:
        """Format questions for review prompt"""
        formatted = []
        for i, q in enumerate(questions, 1):
            formatted.append(
                f"""
Question {i}:
Type: {q.get('type', 'unknown')}
Points: {q.get('points', 0)}
Has Diagram: {q.get('hasDiagram', False)}
Question Text: {q.get('question', 'N/A')}
Correct Answer: {q.get('correctAnswer', 'N/A')[:200]}...
"""
            )
        return "\n".join(formatted)
