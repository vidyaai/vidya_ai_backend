"""
AI Assignment Generation Service

This module provides AI-powered assignment generation capabilities for the VidyaAI platform.
It integrates with OpenAI's GPT models to generate engineering-focused assignments from various content sources.
"""

import json
from textwrap import dedent
from typing import Dict, List, Any, Optional
from openai import OpenAI
from controllers.config import logger
from utils.assignment_schemas import (
    create_dynamic_generation_response,
)
from utils.document_processor import DocumentProcessor


class AssignmentGenerator:
    """AI-powered assignment generation service"""

    def __init__(self):
        """Initialize the assignment generator with OpenAI client"""
        self.client = OpenAI()
        self.model = "gpt-4o"

    def _extract_equations_from_questions(
        self, questions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract equations from generated questions using a separate AI call.

        This method processes all questions in a single batched API call to detect
        mathematical expressions and add equation metadata with proper positioning.

        Args:
            questions: List of generated questions (may contain nested subquestions)

        Returns:
            Modified questions list with equation metadata added
        """
        try:
            logger.info(f"Starting equation extraction for {len(questions)} questions")

            # Serialize questions for equation extraction
            questions_json = json.dumps(questions, indent=2)

            # Create equation extraction prompt
            prompt = dedent(
                f"""
                Analyze the following assignment questions and identify all mathematical equations,
                formulas, and expressions that should be rendered using LaTeX.

                For each equation found:
                1. Extract the LaTeX representation
                2. Determine the position (context: question_text, options, correctAnswer, or rubric)
                3. Calculate the character index where the equation appears
                4. Specify whether it's inline or display type
                5. Replace the equation in the text with a placeholder: {{{{EQ_ID}}}}

                Questions to process:
                {questions_json}

                IMPORTANT:
                - Process ALL question levels (main questions, subquestions at Level 2, nested subquestions at Level 3)
                - Look for equations in: question text, options, correctAnswer, and rubric fields
                - Generate unique equation IDs: q<question_id>_eq<number> (e.g., q1_eq1, q1_eq2)
                - For subquestions: q<main_id>_<sub_id>_eq<number> (e.g., q1_1_eq1)
                - Common equation patterns: fractions, exponents, integrals, derivatives, matrices, Greek letters
                - Inline equations: part of regular text flow
                - Display equations: standalone mathematical expressions

                Each equation object should have this structure:
                {{
                    "id": "q1_eq1",
                    "latex": "E = mc^2",
                    "position": {{
                        "char_index": 25,
                        "context": "question_text"
                    }},
                    "type": "inline"
                }}

                Return a JSON object with a "questions" array containing the modified questions with:
                1. Equation placeholders in text (<eq q1_eq1>, <eq q1_eq2>, etc.)
                2. "equations" array for each question/subquestion containing equation objects

                Return ONLY the JSON object, no additional text.
            """
            ).strip()

            # Make API call for equation extraction using regular completion
            logger.info("Calling GPT-4o for equation extraction...")

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at identifying mathematical equations and converting them to LaTeX format. You always return valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )

            # Parse the JSON response
            response_text = response.choices[0].message.content
            extracted_data = json.loads(response_text)
            questions_with_equations = extracted_data.get("questions", [])

            logger.info(
                f"Equation extraction complete. Processed {len(questions_with_equations)} questions"
            )

            return questions_with_equations

        except Exception as e:
            logger.error(f"Error extracting equations: {str(e)}")
            logger.warning(
                "Continuing without equation extraction, returning original questions"
            )
            # Graceful degradation - return original questions without equations
            return questions

    def _cleanup_diagram_metadata(
        self, questions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Clean up diagram metadata for questions that don't have actual diagrams.

        Removes hasDiagram flags and diagram metadata from questions where the diagram
        agent decided not to generate a diagram (no s3_url present).

        Args:
            questions: List of questions (may contain nested subquestions)

        Returns:
            Questions list with cleaned up diagram metadata
        """

        def cleanup_question(q: Dict[str, Any]) -> Dict[str, Any]:
            """Recursively clean up a question and its subquestions"""
            # Check if question has diagram metadata but no actual S3 URL
            if q.get("hasDiagram") and q.get("diagram"):
                if not q["diagram"].get("s3_url"):
                    # No actual diagram was generated, remove the metadata
                    q["hasDiagram"] = False
                    q["diagram"] = None
                    logger.debug(
                        f"Cleaned up diagram metadata for question {q.get('id')}"
                    )
            elif q.get("hasDiagram") and not q.get("diagram"):
                # hasDiagram is True but no diagram object at all
                q["hasDiagram"] = False
                logger.debug(f"Cleaned up hasDiagram flag for question {q.get('id')}")

            # Recursively clean up subquestions
            if q.get("subquestions"):
                q["subquestions"] = [cleanup_question(sq) for sq in q["subquestions"]]

            return q

        # Clean up all questions
        cleaned_questions = [cleanup_question(q) for q in questions]

        # Count how many were cleaned
        def count_cleaned(qs):
            count = 0
            for q in qs:
                if not q.get("hasDiagram") or (
                    q.get("diagram") and q["diagram"].get("s3_url")
                ):
                    # This is OK
                    pass
                if q.get("subquestions"):
                    count += count_cleaned(q["subquestions"])
            return count

        cleaned_count = len(questions) - sum(
            1
            for q in cleaned_questions
            if q.get("hasDiagram") and q.get("diagram") and q["diagram"].get("s3_url")
        )
        if cleaned_count > 0:
            logger.info(
                f"Cleaned up diagram metadata from {cleaned_count} questions without actual diagrams"
            )

        return cleaned_questions

    def generate_assignment(
        self,
        generation_options: Dict[str, Any],
        linked_videos: Optional[List[Dict]] = None,
        uploaded_files: Optional[List[Dict]] = None,
        generation_prompt: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        assignment_id: Optional[str] = None,
        engine: str = "nonai",
        subject: str = "electrical",
        diagram_model: str = "flash",
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
            assignment_id: Unique assignment ID
            engine: "ai" for Gemini image gen, "nonai" for current flow, "both" for comparison
            subject: Subject domain for diagram routing
            diagram_model: "flash" for gemini-2.5-flash-image, "pro" for gemini-3-pro-image-preview

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

            # Use PageIndex for semantic topic-based chunking (if large documents)
            content_sources_with_topics = self._process_with_pageindex(
                content_sources, generation_options
            )

            # Generate questions based on content and options
            questions = self._generate_questions(content_sources_with_topics, generation_options)
            logger.info(f"Generated {len(questions)} questions")

            # Use multi-agent diagram analysis to generate diagrams
            if assignment_id:
                from utils.diagram_agent import DiagramAnalysisAgent

                has_diagram_analysis = generation_options.get("questionTypes", {}).get(
                    "diagram-analysis", False
                )

                logger.info(
                    f"Starting multi-agent diagram analysis (diagram-analysis: {has_diagram_analysis}, engine: {engine})..."
                )
                agent = DiagramAnalysisAgent(
                    engine=engine, subject=subject, diagram_model=diagram_model
                )
                questions = agent.analyze_and_generate_diagrams(
                    questions=questions,
                    assignment_id=assignment_id,
                    has_diagram_analysis=has_diagram_analysis,
                    generation_prompt=generation_prompt or "",
                )
                logger.info("Multi-agent diagram analysis complete")

                # Clean up diagram metadata for questions without actual diagrams
                questions = self._cleanup_diagram_metadata(questions)
                logger.info("Diagram metadata cleanup complete")
            else:
                logger.warning(
                    "Skipping diagram generation: assignment_id not provided"
                )

            # Review questions for quality and alignment with lecture notes
            if content_sources.get("document_texts") or content_sources.get(
                "video_transcripts"
            ):
                from utils.question_review_agent import QuestionReviewAgent

                logger.info("Starting question review and validation...")
                reviewer = QuestionReviewAgent()

                # Prepare lecture notes content for review
                lecture_content = ""
                if content_sources.get("document_texts"):
                    lecture_content += "\n\n".join(
                        [doc["content"] for doc in content_sources["document_texts"]]
                    )
                if content_sources.get("video_transcripts"):
                    lecture_content += "\n\n".join(
                        [
                            vid["transcript"]
                            for vid in content_sources["video_transcripts"]
                        ]
                    )

                # Review questions
                review_results = reviewer.review_questions(
                    questions=questions,
                    lecture_notes_content=lecture_content[
                        :50000
                    ],  # Send first 5000 chars
                    user_prompt=generation_prompt or "Generate assignment",
                    generation_options=generation_options,
                )

                logger.info(
                    f"Review complete: {review_results.get('overall_assessment', 'No assessment')}"
                )
                logger.info(f"Statistics: {review_results.get('statistics', {})}")

                # Filter and regenerate low-quality questions
                if review_results.get("questions_reviewed"):
                    filtered_questions = []
                    questions_to_regenerate = []

                    for i, question in enumerate(questions, 1):
                        review = review_results["questions_reviewed"].get(str(i), {})

                        if review.get("keep", True):  # Keep by default if no review
                            filtered_questions.append(question)
                        else:
                            questions_to_regenerate.append({
                                "original_question": question,
                                "issues": review.get("issues", []),
                                "alignment_score": review.get("alignment_score", 0)
                            })
                            logger.warning(
                                f"Removing question {i} for regeneration: {review.get('issues', [])}"
                            )

                    # Regenerate removed questions to meet requested count
                    num_removed = len(questions_to_regenerate)
                    if num_removed > 0:
                        logger.info(f"Regenerating {num_removed} questions to maintain requested count...")

                        regenerated = self._regenerate_questions(
                            num_to_regenerate=num_removed,
                            failed_questions=questions_to_regenerate,
                            content_sources=content_sources,
                            generation_options=generation_options
                        )

                        if regenerated:
                            filtered_questions.extend(regenerated)
                            logger.info(f"Successfully regenerated {len(regenerated)} questions. Total questions: {len(filtered_questions)}")
                        else:
                            logger.warning("Regeneration produced no questions. Proceeding with fewer questions than requested.")

                    if len(filtered_questions) != len(questions):
                        logger.info(
                            f"Question count changed: {len(questions)} → {len(filtered_questions)} (removed {num_removed}, regenerated {len(regenerated) if num_removed > 0 else 0})"
                        )
                        questions = filtered_questions
            else:
                logger.info("No lecture notes provided - skipping quality review")

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

    def _regenerate_questions(
        self,
        num_to_regenerate: int,
        failed_questions: List[Dict[str, Any]],
        content_sources: Dict[str, Any],
        generation_options: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Regenerate questions that failed review.
        Uses insights from failed questions to avoid repeating mistakes.
        """
        try:
            logger.info(f"Starting regeneration of {num_to_regenerate} questions...")

            # Build context about what went wrong
            failure_context = "PREVIOUS FAILED QUESTIONS (Learn from these mistakes):\n\n"
            for i, failed in enumerate(failed_questions, 1):
                failure_context += f"Failed Question {i}:\n"
                failure_context += f"  Question: {failed['original_question'].get('question', '')[:200]}\n"
                failure_context += f"  Issues: {', '.join(failed['issues'])}\n"
                failure_context += f"  Alignment Score: {failed['alignment_score']}/10\n\n"

            failure_context += """
REGENERATION INSTRUCTIONS:
1. Study the issues above to understand what went wrong
2. Generate REPLACEMENT questions that avoid these mistakes
3. Ensure questions are STRICTLY based on lecture content ONLY
4. Focus on topics with clear coverage in the lecture material
5. Do NOT repeat the same mistakes listed above
6. Do NOT introduce topics not explicitly covered in the lecture material

Generate high-quality replacement questions that fix the identified issues.
"""

            # Prepare modified generation options
            regen_options = generation_options.copy()
            regen_options["numQuestions"] = num_to_regenerate

            # Prepare content context with failure warnings
            content_context = self._prepare_content_context(content_sources)
            enhanced_context = failure_context + "\n\n" + content_context

            # Create temporary content sources with enhanced context
            regen_content_sources = content_sources.copy()
            if regen_content_sources.get("custom_prompt"):
                regen_content_sources["custom_prompt"] = failure_context + "\n\n" + regen_content_sources["custom_prompt"]
            else:
                regen_content_sources["custom_prompt"] = failure_context

            # Generate replacement questions
            logger.info("Calling question generation with failure context...")
            regenerated = self._generate_questions(
                content_sources=regen_content_sources,
                generation_options=regen_options
            )

            logger.info(f"Regeneration complete: {len(regenerated)} questions created")
            return regenerated

        except Exception as e:
            logger.error(f"Error during question regeneration: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []  # Return empty list on failure

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

    def _process_with_pageindex(
        self,
        content_sources: Dict[str, Any],
        generation_options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process documents with PageIndex for semantic topic-based chunking.

        For large documents (>100k chars), uses PageIndex to:
        1. Extract semantic topic structure
        2. Enable topic-based question generation
        3. Distribute questions proportionally across topics

        Args:
            content_sources: Content from videos/documents/prompts
            generation_options: Generation configuration

        Returns:
            Enhanced content_sources with pageindex_topics if applicable
        """
        from utils.pageindex_processor import PageIndexProcessor

        # Check if we have documents for PageIndex processing
        document_texts = content_sources.get("document_texts", [])
        if not document_texts:
            return content_sources  # No documents to process

        # Calculate total document size for logging
        total_chars = sum(len(doc.get("content", "")) for doc in document_texts)

        # Always use PageIndex for uploaded lecture notes to enable semantic topic-based chunking
        # PageIndex provides semantic boundaries regardless of document size
        if total_chars > 0:
            logger.info(f"Document content detected ({total_chars} chars). Using PageIndex for semantic topic extraction...")

            try:
                pageindex = PageIndexProcessor()
                all_topics = []

                # Process each document with PageIndex
                for doc in document_texts:
                    doc_name = doc.get("name", "document")
                    doc_content = doc.get("content", "")

                    if len(doc_content) > 0:
                        logger.info(f"Processing {doc_name} with PageIndex ({len(doc_content)} chars)...")

                        # Create semantic topic index
                        index_result = pageindex.create_document_index(
                            content=doc_content,
                            doc_name=doc_name
                        )

                        topics = index_result.get("topics", [])
                        logger.info(f"PageIndex identified {len(topics)} semantic topics in {doc_name}")

                        # Tag topics with source document
                        for topic in topics:
                            topic["source_document"] = doc_name

                        all_topics.extend(topics)

                # If we have topics, add them to content_sources
                if all_topics:
                    # Distribute total questions across topics
                    num_questions = generation_options.get("numQuestions", 5)
                    topics_with_questions = pageindex.distribute_questions_across_topics(
                        all_topics,
                        num_questions
                    )

                    # Smart image handling: prepare topics with selective image descriptions
                    try:
                        from utils.smart_image_handler import prepare_topics_for_question_generation

                        # Get the first document's content (assuming single PDF upload)
                        # If multiple PDFs, this would need adjustment
                        first_doc = document_texts[0]
                        doc_content = first_doc.get("content", "")

                        # Prepare topics with smart image handling
                        # Budget: $0.05 per assignment (describes ~15-20 key images)
                        enhanced_topics = prepare_topics_for_question_generation(
                            docling_markdown=doc_content,
                            pageindex_topics=topics_with_questions,
                            budget=0.05  # Configurable budget for image descriptions
                        )

                        content_sources["pageindex_topics"] = enhanced_topics
                        logger.info(
                            f"Enhanced {len(enhanced_topics)} topics with smart image handling. "
                            f"Images allocated: {[(t['name'], t.get('images_allocated', 0)) for t in enhanced_topics]}"
                        )
                    except Exception as e:
                        logger.warning(f"Smart image handler failed: {str(e)}. Using topics without image descriptions.")
                        content_sources["pageindex_topics"] = topics_with_questions

                    logger.info(f"Question distribution: {[(t['name'], t['num_questions']) for t in content_sources['pageindex_topics']]}")

                    # Store original documents as backup
                    content_sources["original_documents"] = document_texts
                else:
                    logger.warning("PageIndex did not extract any topics. Falling back to standard processing.")

            except Exception as e:
                logger.error(f"PageIndex processing failed: {str(e)}. Falling back to standard processing.")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")

        return content_sources

    def _generate_questions_by_topics(
        self,
        content_sources: Dict[str, Any],
        generation_options: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Generate questions topic-by-topic using PageIndex semantic topics.

        For each topic:
        1. Creates focused context from topic content
        2. Generates questions for that topic
        3. Combines all topic questions into final list

        Args:
            content_sources: Content with pageindex_topics
            generation_options: Generation configuration

        Returns:
            List of questions generated from all topics
        """
        topics = content_sources.get("pageindex_topics", [])
        if not topics:
            logger.warning("No PageIndex topics found. Falling back to standard generation.")
            return self._generate_questions(content_sources, generation_options)

        logger.info(f"Generating questions from {len(topics)} semantic topics...")

        all_questions = []

        for i, topic in enumerate(topics, 1):
            topic_name = topic.get("name", f"Topic {i}")
            num_questions = topic.get("num_questions", 1)

            if num_questions <= 0:
                logger.info(f"Skipping {topic_name}: {num_questions} questions allocated")
                continue

            logger.info(f"Generating {num_questions} questions from topic: {topic_name}")

            try:
                # Create focused content sources for this topic
                # Use enhanced_text if available (from smart image handler), otherwise fall back to content
                topic_text = topic.get("enhanced_text", topic.get("content", ""))

                topic_content_sources = {
                    "custom_prompt": content_sources.get("custom_prompt"),
                    "document_texts": [{
                        "name": f"{topic.get('source_document', 'document')} - {topic_name}",
                        "content": topic_text,  # Use enhanced text with image context
                        "topic_info": {
                            "name": topic_name,
                            "pages": f"{topic.get('start_page', '?')}-{topic.get('end_page', '?')}",
                            "description": topic.get("description", ""),
                            "type": topic.get("type", "topic"),
                            "images_in_topic": topic.get("image_count", 0),
                            "images_described": topic.get("images_allocated", 0)
                        }
                    }]
                }

                # Modify generation options for this topic
                topic_gen_options = generation_options.copy()
                topic_gen_options["numQuestions"] = num_questions

                # Generate questions for this topic (standard single-pass)
                # Temporarily remove pageindex_topics to avoid recursion
                temp_content = content_sources.copy()
                if "pageindex_topics" in temp_content:
                    del temp_content["pageindex_topics"]

                # Use standard generation with topic-focused content
                content_context = self._prepare_content_context(topic_content_sources)
                prompt = self._create_generation_prompt(
                    content_context, topic_gen_options, topic_content_sources
                )
                system_prompt = self._get_system_prompt(topic_gen_options)

                # Generate questions for this topic
                question_types = topic_gen_options.get("questionTypes", {})
                enabled_types = [k for k, v in question_types.items() if v]
                response_model = create_dynamic_generation_response(enabled_types or [])

                user_content = [{"type": "input_text", "text": dedent(prompt).strip()}]
                input_data = [{"type": "message", "role": "user", "content": user_content}]

                logger.info(f"Calling AI for topic: {topic_name}...")
                response = self.client.responses.parse(
                    model=self.model,
                    instructions=dedent(system_prompt).strip(),
                    input=input_data,
                    text_format=response_model,
                )

                parsed_response = response.output_parsed
                extracted_data = parsed_response.model_dump()
                topic_questions = extracted_data.get("questions", [])

                logger.info(f"Generated {len(topic_questions)} questions from {topic_name}")

                # Extract equations
                topic_questions = self._extract_equations_from_questions(topic_questions)

                # Sanitize
                topic_questions = self._sanitize_questions(topic_questions)

                # Tag questions with source topic
                for q in topic_questions:
                    q["source_topic"] = topic_name
                    q["source_topic_pages"] = f"{topic.get('start_page', '?')}-{topic.get('end_page', '?')}"

                all_questions.extend(topic_questions)

            except Exception as e:
                logger.error(f"Error generating questions for topic '{topic_name}': {str(e)}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                # Continue with other topics even if one fails

        logger.info(f"Topic-based generation complete: {len(all_questions)} total questions from {len(topics)} topics")

        # Post-process all questions together
        all_questions = self._post_process_questions(all_questions, generation_options)

        return all_questions

    def _generate_questions(
        self, content_sources: Dict[str, Any], generation_options: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate questions using AI based on content and options"""

        # Check if we have PageIndex topics for semantic chunking
        if content_sources.get("pageindex_topics"):
            logger.info("Using PageIndex topic-based question generation")
            return self._generate_questions_by_topics(content_sources, generation_options)

        # Standard single-pass generation for small documents
        # Prepare the content context
        content_context = self._prepare_content_context(content_sources)

        # Create the generation prompt (pass content_sources for checking)
        prompt = self._create_generation_prompt(
            content_context, generation_options, content_sources
        )
        system_prompt = self._get_system_prompt(generation_options)

        # debug: Log the final prompt and system prompt before sending to AI
        logger.info(f"Final system prompt for AI:\n{system_prompt}")
        logger.info(f"Final user prompt for AI:\n{prompt}")

        # Generate questions using OpenAI with structured output
        try:
            # Extract enabled types and get dynamic schema
            question_types = generation_options.get("questionTypes", {})
            enabled_types = [k for k, v in question_types.items() if v]

            # Get the appropriate response model based on enabled types
            response_model = create_dynamic_generation_response(enabled_types or [])
            logger.info(
                f"Using response model: {response_model.__name__} for types: {enabled_types}"
            )

            user_content = [{"type": "input_text", "text": dedent(prompt).strip()}]
            input_data = [{"type": "message", "role": "user", "content": user_content}]

            # Generate questions without equations
            logger.info("Generating questions (without equations)...")
            response = self.client.responses.parse(
                model=self.model,
                instructions=dedent(system_prompt).strip(),
                input=input_data,
                text_format=response_model,
                # reasoning={"effort": "low"},
            )

            parsed_response = response.output_parsed
            extracted_data = parsed_response.model_dump()
            questions = extracted_data.get("questions", [])

            # Debug: Log the raw questions before equation extraction
            logger.info(
                f"Raw questions from AI (without equations): {questions} questions"
            )

            # Extract equations in a separate API call
            logger.info("Extracting equations from generated questions...")
            questions = self._extract_equations_from_questions(questions)

            # Debug: Log questions after equation extraction
            logger.info(f"Questions after equation extraction: {questions} questions")

            # Sanitize questions to remove null bytes and problematic characters
            questions = self._sanitize_questions(questions)
            logger.info(f"Questions sanitized")

            # Post-process questions to ensure they meet requirements
            questions = self._post_process_questions(questions, generation_options)

            # Debug: Log post-processed questions
            logger.info(
                f"Post-processed questions: {len(questions)} questions complete"
            )

            return questions

        except Exception as e:
            logger.error(f"Error generating questions with AI: {str(e)}")
            # Re-raise the exception instead of falling back to mock questions
            raise Exception(f"Failed to generate questions with AI: {str(e)}")

    def _prepare_content_context(self, content_sources: Dict[str, Any]) -> str:
        """Prepare content context with lecture notes as PRIMARY source"""
        context_parts = []

        has_lecture_notes = content_sources.get("document_texts") or content_sources.get("video_transcripts")
        has_custom_prompt = content_sources.get("custom_prompt")

        # STRATEGY: Lecture notes are ALWAYS primary when they exist
        # Custom prompts are ALWAYS secondary (style/focus guidance)

        # PRIORITY 1: Lecture notes/videos are PRIMARY CONTENT SOURCE
        if has_lecture_notes:
            context_parts.append("## PRIMARY LECTURE CONTENT (MAIN SOURCE FOR QUESTIONS):")
            context_parts.append("Generate questions EXCLUSIVELY from the concepts, topics, and material covered in this content.")
            context_parts.append("")

            # Add documents first (highest priority)
            if content_sources.get("document_texts"):
                for doc in content_sources["document_texts"]:
                    context_parts.append(f"### Lecture Notes: {doc['name']}")
                    content = doc["content"][:100000]  # INCREASED from 20000
                    context_parts.append(content)
                    if len(doc["content"]) > 100000:
                        context_parts.append("\n[Document truncated at 100k characters for length - chunking may be needed]")

            # Add video transcripts
            if content_sources.get("video_transcripts"):
                for video in content_sources["video_transcripts"]:
                    context_parts.append(f"### Lecture Video: {video['title']}")
                    transcript = video["transcript"][:100000]  # INCREASED from 20000
                    context_parts.append(transcript)
                    if len(video["transcript"]) > 100000:
                        context_parts.append("\n[Transcript truncated at 100k characters for length - chunking may be needed]")

            # PRIORITY 2: Custom prompt is STYLE GUIDANCE ONLY (when lecture notes exist)
            if has_custom_prompt:
                context_parts.append("")
                context_parts.append("## ADDITIONAL INSTRUCTIONS (Style & Focus Preferences):")
                context_parts.append("Use these to guide HOW to create questions from the lecture content above:")
                context_parts.append(content_sources["custom_prompt"])
                context_parts.append("")
                context_parts.append("IMPORTANT: Do NOT introduce topics not in the lecture material above. These instructions are for style and emphasis only.")

        # FALLBACK: If NO lecture notes, custom prompt becomes primary
        elif has_custom_prompt:
            context_parts.append("## PRIMARY TOPIC INSTRUCTIONS:")
            context_parts.append(content_sources["custom_prompt"])

        return "\n\n".join(context_parts)

    def _get_multipart_instructions(self, enabled_types: List[str]) -> str:
        """Generate instructions for multi-part question handling based on enabled types."""
        has_multipart = "multi-part" in enabled_types
        other_types = [t for t in enabled_types if t != "multi-part"]

        if not has_multipart:
            # No multi-part enabled - generate flat questions only
            return """
                    - ALL questions should be standalone (flat) questions
                    - Do NOT create multi-part questions with subquestions
                    - Each question is independent without nested parts
            """
        elif has_multipart and other_types:
            # Multi-part + other types - natural mix
            return f"""
                    - Generate a NATURAL MIX of standalone questions and multi-part questions
                    - For standalone questions: Use types from {', '.join(other_types)}
                    - For multi-part questions: Include subquestions that can be any type (including nested multi-part at Level 2)
                    - At Level 3 (deepest nesting): subquestions can be any type EXCEPT multi-part
                    - Let the content guide whether to use standalone or multi-part format
                    - For any multi-part question, ensure subquestions and nested subquestions are serially numbered (id) like 1, 2, 3.
            """
        else:
            # ONLY multi-part enabled
            return """
                    - ALL top-level questions MUST be multi-part questions
                    - Each multi-part question must contain subquestions (Level 2)
                    - Level 2 subquestions can be: multiple-choice, short-answer, numerical, true-false, code-writing, diagram-analysis, or nested multi-part
                    - Level 3 subquestions (nested within Level 2 multi-part) can be: multiple-choice, short-answer, numerical, true-false, code-writing, diagram-analysis (NO multi-part at Level 3)
                    - Generate diverse subquestion types to test different skills
                    - For any multi-part question, ensure subquestions and nested subquestions are serially numbered (id) like 1, 2, 3.
            """

    def _create_generation_prompt(
        self,
        content_context: str,
        generation_options: Dict[str, Any],
        content_sources: Dict[str, Any],
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

        # Check if custom prompt exists to determine priority
        has_custom_prompt = content_sources.get("custom_prompt")
        has_video_or_docs = content_sources.get(
            "video_transcripts"
        ) or content_sources.get("document_texts")

        # Use different prompts based on whether discipline is specified (engineering vs general)
        if engineering_discipline:
            # Engineering-specific prompt
            if has_custom_prompt and not has_video_or_docs:
                # Custom prompt only - make it the PRIMARY focus
                prompt = f"""
                    Generate {num_questions} engineering assignment questions STRICTLY based on the topic specified in the PRIMARY TOPIC INSTRUCTIONS below.

                    Assignment Requirements:
                    - Engineering Level: {engineering_level}
                    - Engineering Discipline: {engineering_discipline}
                    - Question Types: {', '.join(enabled_types)}
                    - Difficulty Level: {difficulty_level}
                    - Number of questions: {num_questions}
                    - Total points: {total_points}

                    Content Context:
                    {content_context}

                    CRITICAL INSTRUCTIONS:
                    1. You MUST generate questions ONLY on the specific topic mentioned in the PRIMARY TOPIC INSTRUCTIONS above
                    2. DO NOT generate questions on random topics within {engineering_discipline} engineering
                    3. The questions must be appropriate for {engineering_level}-level students
                    4. Test deep understanding of the SPECIFIC concept/topic requested
                    5. Include a mix of question types: {', '.join(enabled_types)}
                    6. Include clear, unambiguous questions with proper answer keys and rubrics

                    For each question, provide:
                    - Clear, well-structured question text
                    - Appropriate answer options (for multiple choice)
                    - Correct answer and Rubric or grading guidelines
                    - Point value based on difficulty
                    - Any necessary code templates in the code field

                    CODE FIELD GUIDELINES:
                    - if code question
                      -- if outputType is "code", provide a code template with the correct code structure but with key parts left blank for the student to fill in.
                      -- if outputType is "function", provide a function definition template with the correct signature but with the body left blank for the student to implement.
                      -- if outputType is "algorithm", provide a detailed outline of the algorithm steps with key steps left blank for the student to fill in.
                      -- if outputType is "output", provide the code snippet that the student needs to analyze and determine the expected output.
                    - if question includes code (for non-code-writing question types), provide the necessary code snippet in the code field to support the question

                    CORRECTANSWER AND MULTIPLECORRECTANSWERS FIELD GUIDELINES:
                    - correctAnswer is the complete correct answer for the question or subquestion expected from the student. It should be a fully formed answer, not just keywords
                    - for MCQ, provide correctAnswer as index (like "0", "1", "2", "3"). if multiple correct, set allowMultipleCorrect to true and provide multipleCorrectAnswers as array of indices
                    - for code questions, correctAnswer should depend on outputType.
                      -- If outputType is "code", correctAnswer should be the full code.
                      -- If outputType is "function", correctAnswer should be the full function defination.
                      -- If outputType is "algorithm", correctAnswer should be a detailed description of the algorithm steps.
                      -- If outputType is "output", correctAnswer should be the expected output from running the code.

                    MULTI-PART QUESTION GUIDELINES:
                    {self._get_multipart_instructions(enabled_types)}

                    CRITICAL - SUBQUESTION REQUIREMENTS:
                    - EVERY subquestion at ALL levels (Level 2 and Level 3) MUST include:
                      * correctAnswer: The correct answer for that subquestion
                      * rubric: Detailed grading guidelines for that subquestion
                    - Do NOT leave correctAnswer or rubric empty for subquestions
                    - Each subquestion should be independently gradable with its own rubric

                    The response will be automatically structured according to the provided JSON schema. Focus on generating high-quality questions that meet the specified requirements.
                """
            else:
                # Has video/docs or no custom prompt - original behavior
                prompt = f"""
                    Generate {num_questions} engineering assignment questions based on the provided content.

                    Assignment Requirements:
                    - Engineering Level: {engineering_level}
                    - Engineering Discipline: {engineering_discipline}
                    - Question Types: {', '.join(enabled_types)}
                    - Difficulty Level: {difficulty_level}
                    - Number of questions: {num_questions}
                    - Total points: {total_points}

                    Content Context:
                    {content_context}

                    Please generate questions that:
                    1. Are based EXCLUSIVELY on material explicitly covered in the PRIMARY LECTURE CONTENT section above
                    2. DO NOT generate questions on topics not mentioned in the lecture material
                    3. DO NOT generate generic {engineering_discipline} engineering questions unless they match lecture content
                    4. DO NOT introduce concepts, algorithms, formulas, or examples not present in the lecture notes
                    5. Quote or reference specific parts of the lecture material in questions when appropriate
                    6. Are appropriate for {engineering_level}-level {engineering_discipline} engineering students
                    7. Include a mix of question types: {', '.join(enabled_types)}
                    8. Include clear, unambiguous questions with proper answer keys and rubrics

                    CRITICAL: If you cannot find enough material in the PRIMARY LECTURE CONTENT for {num_questions} questions, generate fewer questions rather than hallucinating topics not covered in the material.

                    For each question, provide:
                    - Clear, well-structured question text
                    - Appropriate answer options (for multiple choice)
                    - Correct answer and Rubric or grading guidelines
                    - Point value based on difficulty
                    - Any necessary code templates in the code field

                    CODE FIELD GUIDELINES:
                    - if code question
                      -- if outputType is "code", provide a code template with the correct code structure but with key parts left blank for the student to fill in.
                      -- if outputType is "function", provide a function definition template with the correct signature but with the body left blank for the student to implement.
                      -- if outputType is "algorithm", provide a detailed outline of the algorithm steps with key steps left blank for the student to fill in.
                      -- if outputType is "output", provide the code snippet that the student needs to analyze and determine the expected output.
                    - if question includes code (for non-code-writing question types), provide the necessary code snippet in the code field to support the question

                    CORRECTANSWER AND MULTIPLECORRECTANSWERS FIELD GUIDELINES:
                    - correctAnswer is the complete correct answer for the question or subquestion expected from the student. It should be a fully formed answer, not just keywords
                    - for MCQ, provide correctAnswer as index (like "0", "1", "2", "3"). if multiple correct, set allowMultipleCorrect to true and provide multipleCorrectAnswers as array of indices
                    - for code questions, correctAnswer should depend on outputType.
                      -- If outputType is "code", correctAnswer should be the full code.
                      -- If outputType is "function", correctAnswer should be the full function defination.
                      -- If outputType is "algorithm", correctAnswer should be a detailed description of the algorithm steps.
                      -- If outputType is "output", correctAnswer should be the expected output from running the code.

                    MULTI-PART QUESTION GUIDELINES:
                    {self._get_multipart_instructions(enabled_types)}

                    CRITICAL - SUBQUESTION REQUIREMENTS:
                    - EVERY subquestion at ALL levels (Level 2 and Level 3) MUST include:
                      * correctAnswer: The correct answer for that subquestion
                      * rubric: Detailed grading guidelines for that subquestion
                    - Do NOT leave correctAnswer or rubric empty for subquestions
                    - Each subquestion should be independently gradable with its own rubric

                    The response will be automatically structured according to the provided JSON schema. Focus on generating high-quality questions that meet the specified requirements.
                """
        else:
            # General (non-engineering) prompt
            level_text = f"{engineering_level}-level " if engineering_level else ""
            if has_custom_prompt and not has_video_or_docs:
                # Custom prompt only - make it the PRIMARY focus
                prompt = f"""
                    Generate {num_questions} assignment questions STRICTLY based on the topic specified in the PRIMARY TOPIC INSTRUCTIONS below.

                    Assignment Requirements:
                    {f"- Academic Level: {engineering_level}" if engineering_level else ""}
                    - Question Types: {', '.join(enabled_types)}
                    - Difficulty Level: {difficulty_level}
                    - Number of questions: {num_questions}
                    - Total points: {total_points}

                    Content Context:
                    {content_context}

                    CRITICAL INSTRUCTIONS:
                    1. You MUST generate questions ONLY on the specific topic mentioned in the PRIMARY TOPIC INSTRUCTIONS above
                    2. DO NOT generate questions on random or unrelated topics
                    3. The questions must be appropriate for {level_text}students
                    4. Test deep understanding of the SPECIFIC concept/topic requested
                    5. Include a mix of question types: {', '.join(enabled_types)}
                    6. Include clear, unambiguous questions with proper answer keys
                    7. Follow the user's specific instructions precisely and rubrics

                    For each question, provide:
                    - Clear, well-structured question text
                    - Appropriate answer options (for multiple choice)
                    - Correct answer and Rubric or grading guidelines
                    - Point value based on difficulty
                    - Any necessary code templates in the code field

                    CODE FIELD GUIDELINES:
                    - if code question
                      -- if outputType is "code", provide a code template with the correct code structure but with key parts left blank for the student to fill in.
                      -- if outputType is "function", provide a function definition template with the correct signature but with the body left blank for the student to implement.
                      -- if outputType is "algorithm", provide a detailed outline of the algorithm steps with key steps left blank for the student to fill in.
                      -- if outputType is "output", provide the code snippet that the student needs to analyze and determine the expected output.
                    - if question includes code (for non-code-writing question types), provide the necessary code snippet in the code field to support the question

                    CORRECTANSWER AND MULTIPLECORRECTANSWERS FIELD GUIDELINES:
                    - correctAnswer is the complete correct answer for the question or subquestion expected from the student. It should be a fully formed answer, not just keywords
                    - for MCQ, provide correctAnswer as index (like "0", "1", "2", "3"). if multiple correct, set allowMultipleCorrect to true and provide multipleCorrectAnswers as array of indices
                    - for code questions, correctAnswer should depend on outputType.
                      -- If outputType is "code", correctAnswer should be the full code.
                      -- If outputType is "function", correctAnswer should be the full function defination.
                      -- If outputType is "algorithm", correctAnswer should be a detailed description of the algorithm steps.
                      -- If outputType is "output", correctAnswer should be the expected output from running the code.

                    MULTI-PART QUESTION GUIDELINES:
                    {self._get_multipart_instructions(enabled_types)}

                    CRITICAL - SUBQUESTION REQUIREMENTS:
                    - EVERY subquestion at ALL levels (Level 2 and Level 3) MUST include:
                      * correctAnswer: The correct answer for that subquestion
                      * rubric: Detailed grading guidelines for that subquestion
                    - Do NOT leave correctAnswer or rubric empty for subquestions
                    - Each subquestion should be independently gradable with its own rubric

                    The response will be automatically structured according to the provided JSON schema. Focus on generating high-quality questions that meet the specified requirements.
                """
            else:
                # Has video/docs or no custom prompt - original behavior
                prompt = f"""
                    Generate {num_questions} assignment questions based on the provided content.

                    Assignment Requirements:
                    {f"- Academic Level: {engineering_level}" if engineering_level else ""}
                    - Question Types: {', '.join(enabled_types)}
                    - Difficulty Level: {difficulty_level}
                    - Number of questions: {num_questions}
                    - Total points: {total_points}

                    Content Context:
                    {content_context}

                    Please generate questions that:
                    1. Are based EXCLUSIVELY on material explicitly covered in the PRIMARY LECTURE CONTENT section above
                    2. DO NOT generate questions on topics not mentioned in the lecture material
                    3. DO NOT generate random or generic questions unrelated to the lecture content
                    4. DO NOT introduce concepts, formulas, or examples not present in the lecture notes
                    5. Quote or reference specific parts of the lecture material in questions when appropriate
                    6. Are appropriate for {level_text}students
                    7. Include a mix of question types: {', '.join(enabled_types)}
                    8. Include clear, unambiguous questions with proper answer keys

                    CRITICAL: If you cannot find enough material in the PRIMARY LECTURE CONTENT for {num_questions} questions, generate fewer questions rather than hallucinating topics not covered in the material.

                    For each question, provide:
                    - Clear, well-structured question text
                    - Appropriate answer options (for multiple choice)
                    - Correct answer and Rubric or grading guidelines
                    - Any necessary code templates in the code field

                    CODE FIELD GUIDELINES:
                    - if code question
                      -- if outputType is "code", provide a code template with the correct code structure but with key parts left blank for the student to fill in.
                      -- if outputType is "function", provide a function definition template with the correct signature but with the body left blank for the student to implement.
                      -- if outputType is "algorithm", provide a detailed outline of the algorithm steps with key steps left blank for the student to fill in.
                      -- if outputType is "output", provide the code snippet that the student needs to analyze and determine the expected output.
                    - if question includes code (for non-code-writing question types), provide the necessary code snippet in the code field to support the question

                    CORRECTANSWER AND MULTIPLECORRECTANSWERS FIELD GUIDELINES:
                    - correctAnswer is the complete correct answer for the question or subquestion expected from the student. It should be a fully formed answer, not just keywords
                    - for MCQ, provide correctAnswer as index (like "0", "1", "2", "3"). if multiple correct, set allowMultipleCorrect to true and provide multipleCorrectAnswers as array of indices
                    - for code questions, correctAnswer should depend on outputType.
                      -- If outputType is "code", correctAnswer should be the full code.
                      -- If outputType is "function", correctAnswer should be the full function defination.
                      -- If outputType is "algorithm", correctAnswer should be a detailed description of the algorithm steps.
                      -- If outputType is "output", correctAnswer should be the expected output from running the code.

                    MULTI-PART QUESTION GUIDELINES:
                    {self._get_multipart_instructions(enabled_types)}

                    CRITICAL - SUBQUESTION REQUIREMENTS:
                    - EVERY subquestion at ALL levels (Level 2 and Level 3) MUST include:
                      * correctAnswer: The correct answer for that subquestion
                      * rubric: Detailed grading guidelines for that subquestion
                    - Do NOT leave correctAnswer or rubric empty for subquestions
                    - Each subquestion should be independently gradable with its own rubric

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
            1. STRICTLY follow any PRIMARY TOPIC INSTRUCTIONS provided by the user - this is your TOP priority
            2. Test deep understanding of the SPECIFIC concepts requested
            3. Require critical thinking and problem-solving skills
            4. Are appropriate for the specified academic level
            5. Follow engineering education best practices
            6. Include clear, unambiguous questions with proper answer keys
            7. Provide educational value beyond simple recall

            CRITICAL: If the user provides PRIMARY TOPIC INSTRUCTIONS, you MUST generate questions ONLY on that specific topic. DO NOT deviate to other subjects or generate random questions within the discipline.

            Guidelines:
            - Questions should be challenging but fair
            - Include a variety of question types to assess different skills
            - Provide clear, detailed explanations for answers
            - Ensure questions are self-contained and don't require external resources
            - Use proper engineering terminology and notation
            - Include code examples and diagrams when appropriate
            - Follow academic integrity standards

            SELF-CONTAINED QUESTION RULES (CRITICAL):
            - Every question MUST explicitly state ALL values, parameters, states, and conditions in the question text itself.
            - NEVER write vague references like "as shown in the diagram", "see the figure", "from the circuit above" or "given the values in the table".
            - If a question involves state transitions, truth tables, or specific input/output values, list them ALL explicitly in the question text.
            - Example of WRONG: "Calculate the output for the states shown in the diagram."
            - Example of RIGHT: "Calculate the output Z when Q1=1, Q0=0, I=1 using the formula Z = (Q1 XOR I) AND (Q0 OR I)."
            - Diagrams may be added later by a separate system — the question text must be independently comprehensible without any diagram.
            - For FSM/state machine questions: always include the complete state transition table or explicit transition rules in the question text.
            - For circuit analysis: always specify ALL component values, node labels, and connection topology in the question text.

            MANDATORY FOR MULTI-PART QUESTIONS:
            - EVERY subquestion at ALL nesting levels MUST have:
              * A complete correctAnswer
              * A detailed rubric for grading
            - Never leave subquestion answers or rubrics empty
            - Each subquestion should be independently gradable

            The response will be automatically structured according to the provided JSON schema. Focus on generating high-quality questions that meet the specified requirements.
        """
        else:
            # General (non-engineering) system prompt
            level_text = (
                f" at the {engineering_level} level" if engineering_level else ""
            )
            return f"""You are an expert educator{level_text}.

            Your task is to create high-quality assignment questions that:
            1. STRICTLY follow any PRIMARY TOPIC INSTRUCTIONS provided by the user - this is your TOP priority
            2. Test deep understanding of the SPECIFIC concepts requested
            3. Require critical thinking and problem-solving skills
            4. Are appropriate for the specified academic level
            5. Follow education best practices
            6. Include clear, unambiguous questions with proper answer keys
            7. Provide educational value beyond simple recall

            CRITICAL: If the user provides PRIMARY TOPIC INSTRUCTIONS, you MUST generate questions ONLY on that specific topic. DO NOT deviate to other subjects or generate random unrelated questions.

            Guidelines:
            - Questions should be challenging but fair
            - Include a variety of question types to assess different skills
            - Provide clear, detailed explanations for answers
            - Ensure questions are self-contained and don't require external resources
            - Use proper terminology and notation appropriate to the subject
            - Follow academic integrity standards

            SELF-CONTAINED QUESTION RULES (CRITICAL):
            - Every question MUST explicitly state ALL values, parameters, states, and conditions in the question text itself.
            - NEVER write vague references like "as shown in the diagram", "see the figure", "from the circuit above" or "given the values in the table".
            - If a question involves state transitions, truth tables, or specific input/output values, list them ALL explicitly in the question text.
            - Example of WRONG: "Calculate the output for the states shown in the diagram."
            - Example of RIGHT: "Calculate the output Z when Q1=1, Q0=0, I=1 using the formula Z = (Q1 XOR I) AND (Q0 OR I)."
            - Diagrams may be added later by a separate system — the question text must be independently comprehensible without any diagram.
            - For FSM/state machine questions: always include the complete state transition table or explicit transition rules in the question text.

            MANDATORY FOR MULTI-PART QUESTIONS:
            - EVERY subquestion at ALL nesting levels MUST have:
              * A complete correctAnswer
              * A detailed rubric for grading
            - Never leave subquestion answers or rubrics empty
            - Each subquestion should be independently gradable

            The response will be automatically structured according to the provided JSON schema. Focus on generating high-quality questions that meet the specified requirements.
        """

    def _sanitize_string(self, text: Any) -> str:
        """
        Sanitize string to remove null bytes and other problematic characters.

        Args:
            text: Text to sanitize (can be any type)

        Returns:
            Sanitized string with null bytes removed
        """
        if text is None:
            return ""
        if not isinstance(text, str):
            text = str(text)
        # Remove null bytes and other control characters that PostgreSQL can't handle
        return text.replace("\x00", "").replace("\u0000", "")

    def _sanitize_questions(
        self, questions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Recursively sanitize all text fields in questions to remove null bytes.

        Args:
            questions: List of questions with potential null bytes

        Returns:
            Sanitized questions list
        """
        for question in questions:
            # Sanitize top-level string fields
            if "question" in question:
                question["question"] = self._sanitize_string(question["question"])
            if "text" in question:
                question["text"] = self._sanitize_string(question["text"])
            if "correctAnswer" in question:
                question["correctAnswer"] = self._sanitize_string(
                    question["correctAnswer"]
                )
            if "rubric" in question:
                question["rubric"] = self._sanitize_string(question["rubric"])
            if "code" in question:
                question["code"] = self._sanitize_string(question["code"])
            if "codeLanguage" in question:
                question["codeLanguage"] = self._sanitize_string(
                    question["codeLanguage"]
                )
            if "outputType" in question:
                question["outputType"] = self._sanitize_string(question["outputType"])

            # Sanitize options array
            if "options" in question and isinstance(question["options"], list):
                question["options"] = [
                    self._sanitize_string(opt) for opt in question["options"]
                ]

            # Sanitize multipleCorrectAnswers array
            if "multipleCorrectAnswers" in question and isinstance(
                question["multipleCorrectAnswers"], list
            ):
                question["multipleCorrectAnswers"] = [
                    self._sanitize_string(ans)
                    for ans in question["multipleCorrectAnswers"]
                ]

            # Sanitize equations
            if "equations" in question and isinstance(question["equations"], list):
                for eq in question["equations"]:
                    if isinstance(eq, dict):
                        if "id" in eq:
                            eq["id"] = self._sanitize_string(eq["id"])
                        if "latex" in eq:
                            eq["latex"] = self._sanitize_string(eq["latex"])

            # Recursively sanitize subquestions
            if "subquestions" in question and isinstance(
                question["subquestions"], list
            ):
                question["subquestions"] = self._sanitize_questions(
                    question["subquestions"]
                )

        return questions

    def _post_process_questions(
        self, questions: List[Dict[str, Any]], generation_options: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Post-process generated questions to ensure they meet requirements.

        Fills in default values for fields the frontend expects but that were
        omitted from the lightweight generation schema to keep token usage low.
        """

        for i, question in enumerate(questions):
            question["id"] = i + 1
            question.setdefault("type", "multiple-choice")
            question.setdefault("points", 5)
            question.setdefault("difficulty", "medium")
            question.setdefault("order", i + 1)

            # Normalize "question" <-> "text" for frontend compatibility
            if "question" in question and "text" not in question:
                question["text"] = question["question"]
            elif "text" in question and "question" not in question:
                question["question"] = question["text"]

            # Correct answer defaults
            if question.get("correctAnswer") is None:
                if question.get("type") == "multiple-choice" and question.get(
                    "options"
                ):
                    question["correctAnswer"] = "0"
                elif question.get("type") == "multi-part":
                    question["correctAnswer"] = ""
                else:
                    question["correctAnswer"] = "0"

            if question.get("type") == "true-false" and question.get(
                "correctAnswer"
            ) not in [True, False]:
                if isinstance(question["correctAnswer"], str):
                    if question["correctAnswer"].lower() in ["true", "false"]:
                        question["correctAnswer"] = (
                            question["correctAnswer"].lower() == "true"
                        )
                    if question["correctAnswer"] in ["1", "0"]:
                        question["correctAnswer"] = question["correctAnswer"] == "1"

            # Fields omitted from the lightweight generation schema — set defaults
            question.setdefault("allowMultipleCorrect", False)
            question.setdefault("multipleCorrectAnswers", [])
            question.setdefault("options", [])
            question.setdefault("equations", [])
            question.setdefault("rubric", "")
            question.setdefault("hasCode", False)
            question.setdefault("hasDiagram", False)
            question.setdefault("codeLanguage", "")
            question.setdefault("outputType", "")
            question.setdefault("rubricType", "overall")
            question.setdefault("code", "")
            question.setdefault("diagram", {"s3_url": None, "s3_key": None})
            question.setdefault("optionalParts", False)
            question.setdefault("requiredPartsCount", 0)
            question.setdefault("subquestions", [])

            if not question.get("code"):
                question["hasCode"] = False
            else:
                question["hasCode"] = True
            if not question.get("diagram") or not question["diagram"].get("s3_url"):
                question["hasDiagram"] = False
            else:
                question["hasDiagram"] = True

            # Fill defaults for subquestions too
            for j, sub in enumerate(question.get("subquestions", [])):
                sub.setdefault("id", j + 1)
                sub.setdefault("type", "short-answer")
                sub.setdefault("points", 1)
                sub.setdefault("options", [])
                sub.setdefault("correctAnswer", "")
                sub.setdefault("allowMultipleCorrect", False)
                sub.setdefault("multipleCorrectAnswers", [])
                sub.setdefault("equations", [])
                sub.setdefault("hasCode", False)
                sub.setdefault("hasDiagram", False)
                sub.setdefault("codeLanguage", "")
                sub.setdefault("outputType", "")
                sub.setdefault("rubricType", "overall")
                sub.setdefault("code", "")
                sub.setdefault("diagram", {"s3_url": None, "s3_key": None})
                sub.setdefault("rubric", "")
                sub.setdefault("optionalParts", False)
                sub.setdefault("requiredPartsCount", 0)
                sub.setdefault("subquestions", [])
                # Normalize question/text
                if "question" in sub and "text" not in sub:
                    sub["text"] = sub["question"]
                elif "text" in sub and "question" not in sub:
                    sub["question"] = sub["text"]

                if not sub.get("code"):
                    sub["hasCode"] = False
                else:
                    sub["hasCode"] = True
                if not sub.get("diagram") or not sub["diagram"].get("s3_url"):
                    sub["hasDiagram"] = False
                else:
                    sub["hasDiagram"] = True

                # Fill defaults for Level 3 nested subquestions
                for k, nested_sub in enumerate(sub.get("subquestions", [])):
                    nested_sub.setdefault("id", k + 1)
                    nested_sub.setdefault("type", "short-answer")
                    nested_sub.setdefault("points", 1)
                    nested_sub.setdefault("options", [])
                    nested_sub.setdefault("correctAnswer", "")
                    nested_sub.setdefault("allowMultipleCorrect", False)
                    nested_sub.setdefault("multipleCorrectAnswers", [])
                    nested_sub.setdefault("equations", [])
                    nested_sub.setdefault("hasCode", False)
                    nested_sub.setdefault("hasDiagram", False)
                    nested_sub.setdefault("codeLanguage", "")
                    nested_sub.setdefault("outputType", "")
                    nested_sub.setdefault("rubricType", "overall")
                    nested_sub.setdefault("code", "")
                    nested_sub.setdefault("diagram", {"s3_url": None, "s3_key": None})
                    nested_sub.setdefault("rubric", "")
                    nested_sub.setdefault("optionalParts", False)
                    nested_sub.setdefault("requiredPartsCount", 0)
                    # Normalize question/text
                    if "question" in nested_sub and "text" not in nested_sub:
                        nested_sub["text"] = nested_sub["question"]
                    elif "text" in nested_sub and "question" not in nested_sub:
                        nested_sub["question"] = nested_sub["text"]
                    if not nested_sub.get("code"):
                        nested_sub["hasCode"] = False
                    else:
                        nested_sub["hasCode"] = True
                    if not nested_sub.get("diagram") or not nested_sub["diagram"].get(
                        "s3_url"
                    ):
                        nested_sub["hasDiagram"] = False
                    else:
                        nested_sub["hasDiagram"] = True
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
