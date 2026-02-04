# Entry point
import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from graph.workflow import run_summarization
from config import OUTPUT_DIR, INPUT_DIR, DEEPGRAM_API_KEY
from transcribe import transcribe_video, ensure_directories

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_transcript(file_path: str) -> str:
    """Load transcript from file"""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Skip metadata header if present
    if content.startswith("# Transcript:"):
        lines = content.split("\n")
        # Find the end of metadata (look for separator line)
        start_idx = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("=" * 50):
                start_idx = i + 2  # Skip separator and empty line
                break
        content = "\n".join(lines[start_idx:])

    return content.strip()


def save_summary(video_id: str, summary: str) -> str:
    """Save summary to markdown file"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{video_id}_{timestamp}_summary.md"
    filepath = os.path.join(OUTPUT_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(summary)

    logger.info(f"Summary saved to: {filepath}")
    return filepath


def get_user_input_choice():
    """Get user's choice for input type"""
    print("\n" + "=" * 60)
    print("CHOOSE INPUT TYPE")
    print("=" * 60)
    print("1. 🎥 Video file (.mp4) - Will transcribe using Deepgram + GPT-4o")
    print("2. 📄 Text transcript file (.txt)")
    print("=" * 60)

    while True:
        choice = input("\nEnter your choice (1 or 2): ").strip()
        if choice in ["1", "2"]:
            return int(choice)
        print("❌ Invalid choice. Please enter 1 or 2.")


def get_video_file():
    """Get video file from user"""
    ensure_directories()

    print(f"\n📁 Looking for .mp4 files in '{INPUT_DIR}' folder...")

    # List video files in input directory
    video_files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith(".mp4")]

    if video_files:
        print(f"\n✅ Found {len(video_files)} video file(s):")
        for i, filename in enumerate(video_files, 1):
            print(f"  {i}. {filename}")

        print(f"  {len(video_files) + 1}. Enter custom path")

        while True:
            choice = input(f"\nSelect video (1-{len(video_files) + 1}): ").strip()

            if choice.isdigit():
                choice_num = int(choice)
                if 1 <= choice_num <= len(video_files):
                    return os.path.join(INPUT_DIR, video_files[choice_num - 1])
                elif choice_num == len(video_files) + 1:
                    break

            print("❌ Invalid choice. Please try again.")

    # Manual path entry
    while True:
        video_path = (
            input("\nEnter full path to .mp4 file: ").strip().strip('"').strip("'")
        )
        if os.path.exists(video_path) and video_path.lower().endswith(".mp4"):
            return video_path
        print("❌ File not found or not an .mp4 file. Please try again.")


def get_transcript_file():
    """Get transcript file from user"""
    print(f"\n📁 Looking for .txt files in current directory...")

    # List transcript files
    transcript_files = [f for f in os.listdir(".") if f.lower().endswith(".txt")]

    if transcript_files:
        print(f"\n✅ Found {len(transcript_files)} text file(s):")
        for i, filename in enumerate(transcript_files, 1):
            print(f"  {i}. {filename}")

        print(f"  {len(transcript_files) + 1}. Enter custom path")

        while True:
            choice = input(
                f"\nSelect transcript (1-{len(transcript_files) + 1}): "
            ).strip()

            if choice.isdigit():
                choice_num = int(choice)
                if 1 <= choice_num <= len(transcript_files):
                    return transcript_files[choice_num - 1]
                elif choice_num == len(transcript_files) + 1:
                    break

            print("❌ Invalid choice. Please try again.")

    # Manual path entry
    while True:
        transcript_path = (
            input("\nEnter path to transcript file: ").strip().strip('"').strip("'")
        )
        if os.path.exists(transcript_path):
            return transcript_path
        print("❌ File not found. Please try again.")


def main():
    """Main execution function"""
    print("=" * 60)
    print("🤖 AI-POWERED VIDEO SUMMARIZATION SYSTEM")
    print("=" * 60)
    print("Features:")
    print("• Video transcription with Deepgram + GPT-4o cleanup")
    print("• AI topic extraction and analysis")
    print("• Intelligent web research for external resources")
    print("• Comprehensive markdown summary generation")
    print("=" * 60)

    try:
        # Get user input choice
        choice = get_user_input_choice()

        if choice == 1:
            # Video input workflow
            if not DEEPGRAM_API_KEY:
                print("\n❌ Error: DEEPGRAM_API_KEY not found in environment variables!")
                print(
                    "Please add your Deepgram API key to the .env file to use video transcription."
                )
                return

            print("\n🎥 VIDEO TRANSCRIPTION MODE")
            video_path = get_video_file()
            video_name = Path(video_path).stem

            print(f"\n📹 Processing video: {video_name}")
            print("🔄 Starting transcription pipeline...")

            # Transcribe video
            transcript_path = transcribe_video(video_path)

            print(f"\n✅ Transcription complete!")
            print(f"📄 Transcript saved to: {transcript_path}")

            # Load the cleaned transcript
            transcript = load_transcript(transcript_path)
            video_id = video_name

        else:
            # Text transcript workflow
            print("\n📄 TEXT TRANSCRIPT MODE")
            transcript_file = get_transcript_file()

            print(f"\n📖 Loading transcript from: {transcript_file}")
            transcript = load_transcript(transcript_file)
            video_id = Path(transcript_file).stem

        print(f"\n📊 Transcript loaded: {len(transcript)} characters")

        # Run summarization workflow
        print(f"\n🚀 Starting AI summarization for: {video_id}")
        print("\n🔄 Workflow Pipeline:")
        print("   1️⃣ Analyzer Agent - Extracting key topics...")
        print("   2️⃣ Research Agent - Finding external resources...")
        print("   3️⃣ Synthesis Agent - Creating markdown summary...")
        print()

        final_state = run_summarization(video_id, transcript)

        # Check for errors
        if final_state["errors"]:
            print("\n⚠️  Warnings:")
            for error in final_state["errors"]:
                print(f"   • {error}")

        # Display results
        print("\n" + "=" * 60)
        print("📊 ANALYSIS RESULTS")
        print("=" * 60)

        print(f"\n🎯 Key Topics Found: {len(final_state['key_topics'])}")
        for i, topic in enumerate(final_state["key_topics"], 1):
            print(f"   {i}. {topic}")

        print(f"\n🔗 External Resources Found: {len(final_state['research_results'])}")
        for i, result in enumerate(final_state["research_results"], 1):
            print(f"   {i}. {result['title'][:60]}...")
            print(f"      🌐 {result['url']}")

        # Save summary
        if final_state["summary_markdown"]:
            filepath = save_summary(video_id, final_state["summary_markdown"])
            print(f"\n✅ Summary saved to: {filepath}")

            # Ask if user wants to generate PDF
            print(f"\n📄 Would you like to generate a professional PDF? (y/n): ", end="")
            pdf_choice = input().strip().lower()

            if pdf_choice in ["y", "yes"]:
                try:
                    print("🔄 Generating student-friendly PDF...")
                    # Import PDF generator
                    from utils.pdf_generator import generate_pdf_from_markdown_file

                    # Generate PDF
                    pdf_path = generate_pdf_from_markdown_file(filepath)
                    print(f"✅ Professional PDF generated: {Path(pdf_path).name}")

                    # Store PDF path for later display
                    globals()["generated_pdf"] = pdf_path

                except ImportError:
                    print("❌ PDF generation not available. Install dependencies with:")
                    print("   pip install weasyprint markdown matplotlib requests")
                except Exception as e:
                    print(f"❌ Error generating PDF: {e}")
                    logger.error(f"PDF generation failed: {e}")

            # Display preview
            print("\n" + "=" * 60)
            print("📖 SUMMARY PREVIEW (First 500 characters)")
            print("=" * 60)
            preview = final_state["summary_markdown"][:500]
            if len(final_state["summary_markdown"]) > 500:
                preview += "..."
            print(preview)
        else:
            print("\n❌ Failed to generate summary")

        print("\n" + "=" * 60)
        print("🎉 PROCESS COMPLETE!")
        print("=" * 60)

        if final_state["summary_markdown"]:
            print(f"\n📁 Your files:")
            if choice == 1:
                print(f"   📄 Transcript: {Path(transcript_path).name}")
            print(f"   📋 Summary: {Path(filepath).name}")
            # Check if PDF was generated
            pdf_path = Path(filepath).parent / f"{Path(filepath).stem}_ieee.pdf"
            if pdf_path.exists():
                print(f"   📃 IEEE PDF: {pdf_path.name}")
            print(f"\n💡 Tips:")
            print(
                f"   • Open the summary file to see the full analysis with external resources"
            )
            if pdf_path.exists():
                print(
                    f"   • The PDF is formatted as a student-friendly academic paper with enhanced readability"
                )
                print(
                    f"   • Use 'python generate_pdf.py --all' to convert all summaries to PDF"
                )

    except KeyboardInterrupt:
        print("\n\n⏹️  Process interrupted by user.")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        logger.error(f"Main execution failed: {str(e)}")


if __name__ == "__main__":
    main()
