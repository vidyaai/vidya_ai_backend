#!/usr/bin/env python3
"""
Test script for programmatic assignment generation without UI

Usage:
    python test_question_gen.py -input input_prompt.txt -subject electrical -level grad -pdf_gen True
    python test_question_gen.py -input input_prompt.txt -subject mechanical -level grad -pdf_gen True -engine ai
    python test_question_gen.py -input input_prompt.txt -subject cs -level grad -pdf_gen True -engine nonai
    python test_question_gen.py -input input_prompt.txt -subject physics -level grad -pdf_gen True -engine ai -model pro
    python test_question_gen.py -input input_prompt.txt -subject chemistry -level undergrad -pdf_gen True
    python test_question_gen.py -input input_prompt.txt -subject computer_eng -level grad -pdf_gen True -engine ai

Subjects: electrical, mechanical, cs, civil, math, physics, chemistry, computer_eng
"""

import sys
import os
import json
import argparse
import shutil
from datetime import datetime
from pathlib import Path

# Load .env file from backend root (override=True to override stale shell vars)
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from utils.assignment_generator import AssignmentGenerator
from utils.pdf_generator import AssignmentPDFGenerator
from controllers.config import logger


def get_next_run_number(base_dir: Path) -> int:
    """Get the next run number by checking existing run folders"""
    existing_runs = [
        d for d in base_dir.iterdir() if d.is_dir() and d.name.startswith("run")
    ]
    if not existing_runs:
        return 1

    run_numbers = []
    for run_dir in existing_runs:
        try:
            num = int(run_dir.name.replace("run", ""))
            run_numbers.append(num)
        except ValueError:
            continue

    return max(run_numbers) + 1 if run_numbers else 1


def save_images_to_folder(questions: list, output_dir: Path):
    """
    Extract and save images from questions to the output folder.
    Returns updated questions with local image paths.
    """
    images_saved = 0

    def process_question(q, parent_num=""):
        nonlocal images_saved

        question_num = (
            f"{parent_num}{q.get('questionNumber', '')}"
            if parent_num
            else str(q.get("questionNumber", ""))
        )

        # Check if question has a diagram
        if q.get("hasDiagram") and q.get("diagram"):
            diagram = q["diagram"]
            s3_url = diagram.get("s3_url")

            if s3_url:
                try:
                    # Download image from S3
                    import requests

                    response = requests.get(s3_url, timeout=10)
                    if response.status_code == 200:
                        # Save image locally
                        image_filename = f"question_{question_num}_diagram.png"
                        image_path = output_dir / image_filename

                        with open(image_path, "wb") as f:
                            f.write(response.content)

                        # Update diagram with local path
                        diagram["local_path"] = str(image_path)
                        images_saved += 1

                        logger.info(
                            f"Saved diagram for question {question_num}: {image_filename}"
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to download image for question {question_num}: {str(e)}"
                    )

        # Process subquestions recursively
        if q.get("subquestions"):
            for subq in q["subquestions"]:
                process_question(subq, f"{question_num}.")

    # Process all questions
    for question in questions:
        process_question(question)

    return images_saved


def main():
    parser = argparse.ArgumentParser(
        description="Generate assignment questions programmatically"
    )
    parser.add_argument(
        "-input", "--input", required=True, help="Path to input prompt file"
    )
    parser.add_argument(
        "-subject",
        "--subject",
        required=True,
        choices=[
            "electrical",
            "mechanical",
            "cs",
            "civil",
            "math",
            "physics",
            "chemistry",
            "computer_eng",
        ],
        help="Subject area: electrical, mechanical, cs, civil, math, physics, chemistry, computer_eng",
    )
    parser.add_argument(
        "-level",
        "--level",
        required=True,
        choices=["undergrad", "grad"],
        help="Education level: undergrad or grad",
    )
    parser.add_argument(
        "-pdf_gen",
        "--pdf_gen",
        type=str,
        choices=["True", "False"],
        default="False",
        help="Generate PDF: True or False",
    )
    parser.add_argument(
        "-engine",
        "--engine",
        type=str,
        choices=["ai", "nonai", "both"],
        default="nonai",
        help="Diagram engine: ai (Gemini image gen), nonai (Claude SVG/code), or both (side-by-side comparison)",
    )
    parser.add_argument(
        "-model",
        "--model",
        type=str,
        choices=["flash", "pro"],
        default="flash",
        help="Gemini model: flash (gemini-2.5-flash-image via Vertex AI) or pro (gemini-3-pro-image-preview via Google AI Studio)",
    )

    args = parser.parse_args()

    # Read input prompt
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ Error: Input file not found: {args.input}")
        return 1

    with open(input_path, "r") as f:
        generation_prompt = f.read().strip()

    if not generation_prompt:
        print("❌ Error: Input prompt is empty")
        return 1

    # Create output directory for this run
    base_dir = Path(__file__).parent
    run_number = get_next_run_number(base_dir)
    output_dir = base_dir / f"run{run_number}"
    output_dir.mkdir(exist_ok=True)

    print(f"\n{'='*60}")
    print(f"ASSIGNMENT GENERATION TEST - RUN {run_number}")
    print(f"{'='*60}")
    print(f"Subject: {args.subject}")
    print(f"Input prompt: {input_path.name}")
    print(f"Level: {args.level}")
    print(f"Engine: {args.engine}")
    print(
        f"Model: {args.model} ({'gemini-3-pro-image-preview via AI Studio' if args.model == 'pro' else 'gemini-2.5-flash-image via Vertex AI'})"
    )
    print(f"PDF generation: {args.pdf_gen}")
    print(f"Output directory: {output_dir}")
    print(f"{'='*60}\n")

    # Configure generation options
    generation_options = {
        "numQuestions": 4,  # Test with 15 questions for robustness
        "totalPoints": 40,  # 150 marks total (~10 marks per question)
        "questionTypes": {
            "mcq": False,
            "short-answer": True,
            "numerical": True,
            "true-false": False,
            "fill-in-blanks": False,
            "diagram-analysis": False,  # Off, but model decides intelligently
        },
        "difficultyLevel": "graduate" if args.level == "grad" else "undergraduate",
        "includeRubric": True,
        "multipartQuestions": True,  # Enable multipart questions
    }

    # Generate unique assignment ID
    assignment_id = f"test_assignment_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    try:
        print("⏳ Generating assignment...")
        print(
            f"   Prompt: {generation_prompt[:100]}..."
            if len(generation_prompt) > 100
            else f"   Prompt: {generation_prompt}"
        )

        # Initialize generator
        generator = AssignmentGenerator()

        # Generate assignment
        assignment_data = generator.generate_assignment(
            generation_options=generation_options,
            linked_videos=None,
            uploaded_files=None,
            generation_prompt=generation_prompt,
            title=f"Test Assignment - Run {run_number}",
            description=f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            assignment_id=assignment_id,
            engine=args.engine,
            subject=args.subject,
            diagram_model=args.model,
        )

        questions = assignment_data.get("questions", [])

        print(f"\n✅ Generated {len(questions)} questions")

        # Count multipart questions
        multipart_count = sum(1 for q in questions if q.get("subquestions"))
        print(f"   Multipart questions: {multipart_count}")

        # Count questions with diagrams
        diagram_count = sum(1 for q in questions if q.get("hasDiagram"))
        print(f"   Questions with diagrams: {diagram_count}")

        # Save images to output folder
        if diagram_count > 0:
            print(f"\n⏳ Downloading and saving diagrams...")
            images_saved = save_images_to_folder(questions, output_dir)
            print(f"✅ Saved {images_saved} diagram images")

        # Prepare assignment data for saving
        output_data = {
            "metadata": {
                "run_number": run_number,
                "timestamp": datetime.now().isoformat(),
                "subject": args.subject,
                "input_prompt": generation_prompt,
                "level": args.level,
                "engine": args.engine,
                "generation_options": generation_options,
                "assignment_id": assignment_id,
            },
            "assignment": {
                "title": assignment_data.get("title"),
                "description": assignment_data.get("description"),
                "total_points": assignment_data.get("total_points"),
                "questions": questions,
            },
            "statistics": {
                "total_questions": len(questions),
                "multipart_questions": multipart_count,
                "questions_with_diagrams": diagram_count,
            },
        }

        # Save JSON
        json_path = output_dir / "assignment.json"
        with open(json_path, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\n✅ Saved JSON: {json_path}")

        # Generate PDF if requested
        if args.pdf_gen == "True":
            print(f"\n⏳ Generating PDF...")
            try:
                pdf_generator = AssignmentPDFGenerator()

                # Prepare assignment data for PDF generation
                pdf_assignment = {
                    "title": assignment_data.get("title"),
                    "description": assignment_data.get("description"),
                    "total_points": assignment_data.get("total_points"),
                    "questions": questions,
                }

                pdf_bytes = pdf_generator.generate_assignment_pdf(pdf_assignment)

                # Save PDF
                pdf_path = output_dir / "assignment.pdf"
                with open(pdf_path, "wb") as f:
                    f.write(pdf_bytes)

                print(f"✅ Generated PDF: {pdf_path}")
                print(f"   Size: {len(pdf_bytes) / 1024:.1f} KB")

            except Exception as e:
                print(f"❌ PDF generation failed: {str(e)}")
                logger.error(f"PDF generation error: {str(e)}", exc_info=True)

        # Save summary
        summary_path = output_dir / "summary.txt"
        with open(summary_path, "w") as f:
            f.write(f"ASSIGNMENT GENERATION SUMMARY - RUN {run_number}\n")
            f.write(f"{'='*60}\n\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Subject: {args.subject}\n")
            f.write(f"Level: {args.level}\n")
            f.write(f"Engine: {args.engine}\n")
            f.write(f"Model: {args.model}\n")
            f.write(f"Assignment ID: {assignment_id}\n\n")
            f.write(f"INPUT PROMPT:\n{'-'*60}\n")
            f.write(f"{generation_prompt}\n\n")
            f.write(f"STATISTICS:\n{'-'*60}\n")
            f.write(f"Total questions: {len(questions)}\n")
            f.write(f"Multipart questions: {multipart_count}\n")
            f.write(f"Questions with diagrams: {diagram_count}\n")
            f.write(f"Total points: {assignment_data.get('total_points', 0)}\n\n")
            f.write(f"FILES GENERATED:\n{'-'*60}\n")
            f.write(f"- assignment.json\n")
            if args.pdf_gen == "True":
                f.write(f"- assignment.pdf\n")
            if diagram_count > 0:
                f.write(f"- {diagram_count} diagram images\n")

        print(f"✅ Saved summary: {summary_path}")

        print(f"\n{'='*60}")
        print(f"✅ GENERATION COMPLETE!")
        print(f"{'='*60}")
        print(f"Output location: {output_dir}")
        print(f"\nGenerated files:")
        print(f"  - assignment.json (questions data)")
        if args.pdf_gen == "True":
            print(f"  - assignment.pdf (formatted assignment)")
        if diagram_count > 0:
            print(f"  - {diagram_count} diagram image(s)")
        print(f"  - summary.txt (generation summary)")
        print(f"\n🎉 Success!\n")

        return 0

    except Exception as e:
        print(f"\n❌ Generation failed: {str(e)}")
        logger.error(f"Assignment generation error: {str(e)}", exc_info=True)

        # Save error log
        error_path = output_dir / "error.log"
        with open(error_path, "w") as f:
            f.write(f"Assignment generation failed\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"Error: {str(e)}\n\n")
            import traceback

            f.write(traceback.format_exc())

        print(f"Error log saved: {error_path}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
