"""
Extract text from PDFs using Docling and save to files
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from utils.docling_processor import DoclingProcessor


def extract_and_save(pdf_path: str, output_path: str):
    """Extract text from PDF and save to file"""
    print(f"\nExtracting: {Path(pdf_path).name}")
    print("-" * 70)

    # Read PDF
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()

    # Extract with docling (no image descriptions for speed)
    processor = DoclingProcessor(enable_image_descriptions=False)
    extracted_text = processor.extract_text_from_pdf(pdf_bytes, describe_images=False)

    # Save to file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(extracted_text)

    # Stats
    char_count = len(extracted_text)
    word_count = len(extracted_text.split())
    line_count = len(extracted_text.split('\n'))
    image_count = extracted_text.count('<!-- image -->')

    print(f"✅ Saved to: {output_path}")
    print(f"   Characters: {char_count:,}")
    print(f"   Words: {word_count:,}")
    print(f"   Lines: {line_count:,}")
    print(f"   Images detected: {image_count}")

    # Show first 1000 characters
    print(f"\nFirst 1000 characters:")
    print("=" * 70)
    print(extracted_text[:1000])
    print("=" * 70)

    return {
        "chars": char_count,
        "words": word_count,
        "lines": line_count,
        "images": image_count
    }


def main():
    """Extract both PDFs"""
    pdfs = [
        (
            "/Users/pingakshyagoswami/Library/Mobile Documents/com~apple~CloudDocs/vidya_ai_backend/question_generation_test/synthesis.pdf",
            "/Users/pingakshyagoswami/Library/Mobile Documents/com~apple~CloudDocs/vidya_ai_backend/docling_extracted_synthesis.md"
        ),
        (
            "/Users/pingakshyagoswami/Downloads/placement.pdf",
            "/Users/pingakshyagoswami/Library/Mobile Documents/com~apple~CloudDocs/vidya_ai_backend/docling_extracted_placement.md"
        )
    ]

    results = []

    for pdf_path, output_path in pdfs:
        try:
            result = extract_and_save(pdf_path, output_path)
            result["pdf"] = Path(pdf_path).name
            result["output"] = output_path
            results.append(result)
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

    # Summary
    print("\n" + "=" * 70)
    print("EXTRACTION SUMMARY")
    print("=" * 70)

    for r in results:
        print(f"\n{r['pdf']}:")
        print(f"  Output file: {r['output']}")
        print(f"  Characters: {r['chars']:,}")
        print(f"  Words: {r['words']:,}")
        print(f"  Lines: {r['lines']:,}")
        print(f"  Images: {r['images']}")


if __name__ == "__main__":
    main()
