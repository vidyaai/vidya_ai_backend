#!/usr/bin/env python3
"""
Command-line tool for generating professional student-friendly PDFs from lecture summaries.
Usage: python generate_pdf.py [markdown_file] [--output output_file] [--all]
"""

import argparse
import sys
import os
from pathlib import Path
import logging

# Add utils to path
sys.path.append(os.path.join(os.path.dirname(__file__), "utils"))

from utils.pdf_generator import generate_pdf_from_markdown_file

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Generate professional student-friendly PDFs from lecture summary markdown files"
    )

    parser.add_argument("input", nargs="?", help="Path to markdown file to convert")

    parser.add_argument("--output", "-o", help="Output PDF file path (optional)")

    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Convert all markdown files in the output directory",
    )

    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory containing markdown files (default: output)",
    )

    args = parser.parse_args()

    if not args.input and not args.all:
        print("Error: Please specify either an input file or use --all flag")
        parser.print_help()
        return 1

    if args.all:
        # Convert all markdown files in the output directory
        output_dir = Path(args.output_dir)
        if not output_dir.exists():
            print(f"Error: Output directory '{output_dir}' does not exist")
            return 1

        markdown_files = list(output_dir.glob("*.md"))
        if not markdown_files:
            print(f"No markdown files found in '{output_dir}'")
            return 0

        print(f"Found {len(markdown_files)} markdown files to convert:")

        success_count = 0
        for md_file in markdown_files:
            try:
                print(f"\nConverting: {md_file.name}")

                # Generate output filename
                pdf_file = md_file.parent / f"{md_file.stem}_ieee.pdf"

                # Generate PDF
                result_path = generate_pdf_from_markdown_file(
                    str(md_file), str(pdf_file)
                )
                print(f"✓ Generated: {Path(result_path).name}")
                success_count += 1

            except Exception as e:
                print(f"✗ Error converting {md_file.name}: {e}")
                logger.error(f"Failed to convert {md_file}: {e}")

        print(
            f"\nConversion complete: {success_count}/{len(markdown_files)} files converted successfully"
        )

    else:
        # Convert single file
        input_file = Path(args.input)

        if not input_file.exists():
            print(f"Error: Input file '{input_file}' does not exist")
            return 1

        if input_file.suffix.lower() != ".md":
            print(f"Warning: Input file does not have .md extension")

        try:
            # Generate output filename if not provided
            if args.output:
                output_file = args.output
            else:
                output_file = str(input_file.parent / f"{input_file.stem}_ieee.pdf")

            print(f"Converting: {input_file}")
            print(f"Output: {output_file}")

            # Generate PDF
            result_path = generate_pdf_from_markdown_file(str(input_file), output_file)
            print(f"✓ Successfully generated PDF: {result_path}")

        except Exception as e:
            print(f"✗ Error: {e}")
            logger.error(f"Failed to convert {input_file}: {e}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
