"""
AI Assignment Generation Service

This module provides AI-powered assignment generation capabilities for the VidyaAI platform.
It integrates with OpenAI's GPT models to generate engineering-focused assignments from various content sources.
"""

import json
import base64
from textwrap import dedent
from typing import Dict, List, Any, Optional
from openai import OpenAI
from controllers.config import logger
from utils.assignment_schemas import get_assignment_parsing_schema
from utils.document_processor import DocumentProcessor


class AssignmentGenerator:
    """AI-powered assignment generation service"""

    def __init__(self):
        """Initialize the assignment generator with OpenAI client"""
        self.client = OpenAI()
        self.model = "gpt-5"

    def generate_assignment(
        self,
        generation_options: Dict[str, Any],
        linked_videos: Optional[List[Dict]] = None,
        uploaded_files: Optional[List[Dict]] = None,
        generation_prompt: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate an assignment using AI based on provided content and options.

        Args:
            generation_options: Configuration for assignment generation
            linked_videos: List of linked video data
            uploaded_files: List of uploaded file data
            generation_prompt: Custom prompt for generation
            title: Assignment title
            description: Assignment description

        Returns:
            Generated assignment data
        """
        try:
            logger.info(
                f"Starting assignment generation with options: {generation_options}"
            )
            logger.info(f"Linked videos: {len(linked_videos or [])}")
            logger.info(f"Uploaded files: {len(uploaded_files or [])}")
            logger.info(f"Generation prompt: {generation_prompt}")

            # Extract content from various sources
            content_sources = self._extract_content_sources(
                linked_videos, uploaded_files, generation_prompt
            )
            logger.info(f"Content sources extracted: {list(content_sources.keys())}")

            # Generate questions based on content and options
            questions = self._generate_questions(content_sources, generation_options)
            logger.info(f"Generated {len(questions)} questions")

            # Create assignment metadata
            assignment_data = {
                "title": title or self._generate_title(generation_options),
                "description": description
                or self._generate_description(generation_options, content_sources),
                "questions": questions,
                "linked_videos": linked_videos or [],
                "uploaded_files": uploaded_files or [],
                "generation_prompt": generation_prompt,
                "generation_options": generation_options,
            }

            logger.info(f"Generated assignment with {len(questions)} questions")
            return assignment_data

        except Exception as e:
            logger.error(f"Error generating assignment: {str(e)}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            raise Exception(f"Error generating assignment: {str(e)}")

    def _extract_content_sources(
        self,
        linked_videos: Optional[List[Dict]],
        uploaded_files: Optional[List[Dict]],
        generation_prompt: Optional[str],
    ) -> Dict[str, Any]:
        """Extract and process content from various sources"""
        content_sources = {
            "video_transcripts": [],
            "document_texts": [],
            "custom_prompt": generation_prompt,
        }

        # Process linked videos
        if linked_videos:
            for video in linked_videos:
                if video.get("transcript_text"):
                    content_sources["video_transcripts"].append(
                        {
                            "title": video.get("title", "Unknown Video"),
                            "transcript": video.get("transcript_text"),
                            "youtube_id": video.get("youtube_id"),
                        }
                    )

        # Process uploaded files
        if uploaded_files:
            for file_data in uploaded_files:
                try:
                    # Extract text from uploaded files
                    doc_processor = DocumentProcessor()
                    content = doc_processor.extract_text_from_file(
                        file_data.get("content"),
                        file_data.get("name"),
                        file_data.get("type"),
                    )
                    content_sources["document_texts"].append(
                        {
                            "name": file_data.get("name", "Unknown File"),
                            "content": content,
                            "type": file_data.get("type", "application/pdf"),
                        }
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to process file {file_data.get('name')}: {str(e)}"
                    )
                    raise Exception(
                        f"Failed to process file {file_data.get('name')}: {str(e)}"
                    )

        return content_sources

    def _generate_questions(
        self, content_sources: Dict[str, Any], generation_options: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate questions using AI based on content and options"""

        # Prepare the content context
        content_context = self._prepare_content_context(content_sources)

        # Create the generation prompt
        prompt = self._create_generation_prompt(content_context, generation_options)

        # Generate questions using OpenAI with structured output
        try:
            # Get the structured output schema with dynamic naming (using document parsing schema)
            response_schema = get_assignment_parsing_schema(
                "assignment_generation_questions"
            )

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": dedent(self._get_system_prompt(generation_options)),
                    },
                    {"role": "user", "content": dedent(prompt).strip()},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "assignment_generation_questions",
                        "schema": response_schema,
                    },
                },
            )

            # Parse the response
            generated_data = json.loads(response.choices[0].message.content)
            questions = generated_data.get("questions", [])

            # Post-process questions to ensure they meet requirements
            questions = self._post_process_questions(questions, generation_options)

            return questions

        except Exception as e:
            logger.error(f"Error generating questions with AI: {str(e)}")
            # Re-raise the exception instead of falling back to mock questions
            raise Exception(f"Failed to generate questions with AI: {str(e)}")

    def _prepare_content_context(self, content_sources: Dict[str, Any]) -> str:
        """Prepare content context for AI generation"""
        context_parts = []

        # Add video transcripts
        if content_sources.get("video_transcripts"):
            context_parts.append("## Video Content:")
            for video in content_sources["video_transcripts"]:
                context_parts.append(f"### {video['title']}")
                context_parts.append(
                    video["transcript"][:2000] + "..."
                    if len(video["transcript"]) > 2000
                    else video["transcript"]
                )

        # Add document content
        if content_sources.get("document_texts"):
            context_parts.append("## Document Content:")
            for doc in content_sources["document_texts"]:
                context_parts.append(f"### {doc['name']}")
                context_parts.append(
                    doc["content"][:2000] + "..."
                    if len(doc["content"]) > 2000
                    else doc["content"]
                )

        # Add custom prompt
        if content_sources.get("custom_prompt"):
            context_parts.append("## Custom Instructions:")
            context_parts.append(content_sources["custom_prompt"])

        return "\n\n".join(context_parts)

    def _create_generation_prompt(
        self, content_context: str, generation_options: Dict[str, Any]
    ) -> str:
        """Create the generation prompt for AI"""

        # Extract key options
        num_questions = generation_options.get("numQuestions", 5)
        engineering_level = generation_options.get("engineeringLevel", "")
        engineering_discipline = generation_options.get("engineeringDiscipline", "")
        question_types = generation_options.get("questionTypes", {})
        difficulty_level = generation_options.get("difficultyLevel", "mixed")
        total_points = generation_options.get("totalPoints", 50)

        # Handle per-question difficulty distribution
        difficulty_distribution = None
        if generation_options.get("perQuestionDifficulty"):
            difficulty_distribution = generation_options.get(
                "difficultyDistribution", {}
            )

        # Create question type requirements
        enabled_types = [k for k, v in question_types.items() if v]

        # Use different prompts based on whether discipline is specified (engineering vs general)
        if engineering_discipline:
            # Engineering-specific prompt
            prompt = f"""
            Generate {num_questions} engineering assignment questions based on the provided content.

            Assignment Requirements:
            - Engineering Level: {engineering_level}
            - Engineering Discipline: {engineering_discipline}
            - Question Types: {', '.join(enabled_types)}
            - Difficulty Level: {difficulty_level}

            Content Context:
            {content_context}

            Please generate questions that:
            1. Are appropriate for {engineering_level}-level {engineering_discipline} engineering students
            2. Test understanding of key concepts from the provided content
            3. Include a mix of question types: {', '.join(enabled_types)}
            4. Have appropriate difficulty levels for the target audience
            5. Include clear, unambiguous questions with proper answer keys
            6. Follow engineering education best practices

            For each question, provide:
            - Clear, well-structured question text
            - Appropriate answer options (for multiple choice) with correctAnswer as index (like "0", "1", "2", "3") of the correct answer in the options array
            - Correct answer with brief explanation (except for multi-part questions which get answers from sub-questions)
            - Rubric or grading guidelines
            - Point value based on difficulty
            - Any necessary code templates or diagrams

            The response will be automatically structured according to the provided JSON schema. Focus on generating high-quality questions that meet the specified requirements.
        """
        else:
            # General (non-engineering) prompt
            level_text = f"{engineering_level}-level " if engineering_level else ""
            prompt = f"""
            Generate {num_questions} assignment questions based on the provided content.

            Assignment Requirements:
            {f"- Academic Level: {engineering_level}" if engineering_level else ""}
            - Question Types: {', '.join(enabled_types)}
            - Difficulty Level: {difficulty_level}

            Content Context:
            {content_context}

            Please generate questions that:
            1. Are appropriate for {level_text}students
            2. Test understanding of key concepts from the provided content
            3. Include a mix of question types: {', '.join(enabled_types)}
            4. Have appropriate difficulty levels for the target audience
            5. Include clear, unambiguous questions with proper answer keys
            6. Follow education best practices

            For each question, provide:
            - Clear, well-structured question text
            - Appropriate answer options (for multiple choice) with correctAnswer as index (like "0", "1", "2", "3") of the correct answer in the options array
            - Correct answer with brief explanation (except for multi-part questions which get answers from sub-questions)
            - Rubric or grading guidelines
            - Point value based on difficulty

            The response will be automatically structured according to the provided JSON schema. Focus on generating high-quality questions that meet the specified requirements.
        """

        # Add difficulty distribution if specified
        if difficulty_distribution:
            prompt += f"\n\nDifficulty Distribution Requirements:\n"
            for difficulty, config in difficulty_distribution.items():
                if config.get("count", 0) > 0:
                    if config.get("pointsEach", 0) > 0:
                        prompt += f"- {config['count']} {difficulty} questions ({config['pointsEach']} points each)\n"
                    else:
                        for varying_point in config.get("varyingPoints", []):
                            prompt += f"- {varying_point['count']} {difficulty} questions ({varying_point['points']} points each)\n"
            prompt += f"\n\nTotal Assignment Points: {total_points}\n"
        else:
            prompt += f"\n\nOverall Difficulty Level: {difficulty_level}\n"
            prompt += f"\n\nTotal Assignment Points: {total_points}\n"
        # logger.info(f"Prompt: {prompt}")
        return prompt

    def _get_system_prompt(self, generation_options: Dict[str, Any]) -> str:
        """Get the system prompt for AI generation"""
        engineering_level = generation_options.get("engineeringLevel", "")
        engineering_discipline = generation_options.get("engineeringDiscipline", "")

        # Use different system prompts based on whether discipline is specified (engineering vs general)
        if engineering_discipline:
            # Engineering-specific system prompt
            return f"""You are an expert engineering educator specializing in {engineering_discipline} engineering education at the {engineering_level} level.

            Your task is to create high-quality assignment questions that:
            1. Test deep understanding of engineering concepts
            2. Require critical thinking and problem-solving skills
            3. Are appropriate for the specified academic level
            4. Follow engineering education best practices
            5. Include clear, unambiguous questions with proper answer keys
            6. Provide educational value beyond simple recall

            Guidelines:
            - Questions should be challenging but fair
            - Include a variety of question types to assess different skills
            - Provide clear, detailed explanations for answers
            - Ensure questions are self-contained and don't require external resources
            - Use proper engineering terminology and notation
            - Include code examples and diagrams when appropriate
            - Follow academic integrity standards

            The response will be automatically structured according to the provided JSON schema. Focus on generating high-quality questions that meet the specified requirements.
        """
        else:
            # General (non-engineering) system prompt
            level_text = (
                f" at the {engineering_level} level" if engineering_level else ""
            )
            return f"""You are an expert educator{level_text}.

            Your task is to create high-quality assignment questions that:
            1. Test deep understanding of the subject matter
            2. Require critical thinking and problem-solving skills
            3. Are appropriate for the specified academic level
            4. Follow education best practices
            5. Include clear, unambiguous questions with proper answer keys
            6. Provide educational value beyond simple recall

            Guidelines:
            - Questions should be challenging but fair
            - Include a variety of question types to assess different skills
            - Provide clear, detailed explanations for answers
            - Ensure questions are self-contained and don't require external resources
            - Use proper terminology and notation appropriate to the subject
            - Follow academic integrity standards

            The response will be automatically structured according to the provided JSON schema. Focus on generating high-quality questions that meet the specified requirements.
        """

    def _post_process_questions(
        self, questions: List[Dict[str, Any]], generation_options: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Post-process generated questions to ensure they meet requirements"""

        # Ensure all questions have required fields
        for i, question in enumerate(questions):
            question["id"] = i + 1
            question.setdefault("type", "multiple-choice")
            question.setdefault("points", 5)
            question.setdefault("difficulty", "medium")
            question.setdefault("explanation", "No explanation provided")

            # Ensure correct answer format
            if question.get("correctAnswer") is None:
                if question.get("type") == "multiple-choice" and question.get(
                    "options"
                ):
                    question["correctAnswer"] = "0"
                elif question.get("type") == "multi-part":
                    question[
                        "correctAnswer"
                    ] = ""  # Multi-part questions don't have their own answers
                else:
                    question["correctAnswer"] = "0"

            # Set default multiple correct values
            question.setdefault("allowMultipleCorrect", False)
            question.setdefault("multipleCorrectAnswers", [])

        return questions

    def _generate_title(self, generation_options: Dict[str, Any]) -> str:
        """Generate assignment title based on options"""
        engineering_level = generation_options.get("engineeringLevel", "")
        engineering_discipline = generation_options.get("engineeringDiscipline", "")

        # Handle empty strings - not an engineering assignment
        if not engineering_discipline:
            if not engineering_level:
                return "AI-Generated Assignment"
            else:
                return f"{engineering_level.title()} Level Assignment"
        else:
            if not engineering_level:
                return f"{engineering_discipline.title()} Assignment"
            else:
                return f"{engineering_level.title()} {engineering_discipline.title()} Assignment"

    def _generate_description(
        self, generation_options: Dict[str, Any], content_sources: Dict[str, Any]
    ) -> str:
        """Generate assignment description"""
        engineering_level = generation_options.get("engineeringLevel", "")
        engineering_discipline = generation_options.get("engineeringDiscipline", "")
        num_questions = generation_options.get("numQuestions", 5)

        # Build description based on available options
        if engineering_level and engineering_discipline:
            description_parts = [
                f"AI-generated {engineering_level}-level {engineering_discipline} assignment",
            ]
        elif engineering_level:
            description_parts = [
                f"AI-generated {engineering_level}-level assignment",
            ]
        elif engineering_discipline:
            description_parts = [
                f"AI-generated {engineering_discipline} assignment",
            ]
        else:
            description_parts = [
                "AI-generated assignment",
            ]

        description_parts.append(
            f"Contains {num_questions} questions covering key concepts"
        )

        if content_sources.get("video_transcripts"):
            description_parts.append(
                f"Based on {len(content_sources['video_transcripts'])} video(s)"
            )

        if content_sources.get("document_texts"):
            description_parts.append(
                f"Includes content from {len(content_sources['document_texts'])} document(s)"
            )

        return ". ".join(description_parts) + "."
