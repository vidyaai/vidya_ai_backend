# Video Lecture Summarization System

A comprehensive system that converts video lectures into well-structured markdown summaries using AI. The system utilizes Deepgram for transcription, GPT-4o for cleanup and summarization, and includes external resource gathering through Google Search.

## Important Note About API Usage

This project uses several APIs but is designed to minimize costs:
- **Deepgram API**: Uses the free tier effectively (up to 40,000 minutes)
- **Google Custom Search**: Uses the free tier (100 queries/day)
- **GPT-4o**: Minimal token usage due to optimized prompts and chunking

## Features

- Video to high-quality transcript conversion using Deepgram
- Intelligent transcript cleanup with GPT-4o
- Multi-agent analysis system:
  - Analyzer Agent: Extracts key topics and concepts
  - Research Agent: Finds relevant external resources
  - Synthesis Agent: Creates comprehensive markdown summaries
- Support for both video (.mp4) and text transcript inputs
- Structured markdown output with citations and external resources
- **Professional PDF generation** with student-friendly single-column formatting
- Interactive command-line interface

## Project Structure

```
summarize_lecture/
├── main.py                 # Main entry point
├── config.py              # Configuration settings
├── transcribe.py          # Video transcription pipeline
├── agents/                # AI agent modules
│   ├── analyzer_agent.py   # Topic extraction
│   ├── research_agent.py   # Resource finding
│   └── synthesis_agent.py  # Summary generation
├── utils/                 # Utility modules
│   ├── audio_extractor.py  # Video to audio
│   ├── deepgram_client.py  # Transcription
│   ├── gpt_cleaner.py      # Transcript cleanup
│   ├── google_search.py    # Web search
│   └── pdf_generator.py    # IEEE-style PDF generation
├── input/                 # Place video files here
├── output/               # Generated summaries
└── temp/                 # Temporary files
```

## Setup Instructions

1. **Clone the repository**
   ```bash
   git clone https://github.com/pingakshya2008utd/summarize_video.git
   cd summarize_video
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install FFmpeg** (required for audio extraction)
   - On macOS: `brew install ffmpeg`
   - On Ubuntu: `sudo apt-get install ffmpeg`
   - On Windows: Download from ffmpeg.org

4. **Configure API keys**
   Create a `.env` file in the root directory:
   ```
   OPENAI_API_KEY=your-openai-key
   DEEPGRAM_API_KEY=your-deepgram-key
   GOOGLE_CSE_API_KEY=your-google-api-key
   GOOGLE_CSE_ID=your-search-engine-id
   ```

## Usage

1. **Input Files**
   - For video input: Place your .mp4 files in the `input/` directory
   - For text input: Have your transcript .txt file ready

2. **Run the System**
   ```bash
   python3 main.py
   ```

3. **Choose Input Type**
   - Select option 1 for video file (.mp4)
   - Select option 2 for text transcript (.txt)

4. **Select Input File**
   - The system will show available files
   - Choose from the list or provide a custom path

5. **Review Output**
   - Find the cleaned transcript in `output/{filename}_cleaned_{timestamp}.txt`
   - Find the summary in `output/{filename}_{timestamp}_summary.md`
   - Optionally generate IEEE-style PDF when prompted

## PDF Generation

The system includes professional IEEE-style PDF generation:

### Automatic Generation
When running the main workflow, you'll be prompted to generate a PDF after the summary is created.

### Manual Generation
```bash
# Convert a single file
python generate_pdf.py output/your_summary.md

# Convert all markdown files
python generate_pdf.py --all
```

### PDF Features
- Single-column format optimized for student reading
- Professional typography with Times New Roman
- Color-coded sections for visual organization
- Enhanced readability with improved spacing
- **Comprehensive LaTeX mathematical notation support**
- Proper rendering of equations, fractions, and scientific symbols
- Academic reference formatting
- Student-friendly layout perfect for study materials

For detailed PDF generation instructions, see [PDF_GENERATION.md](PDF_GENERATION.md).

## Output Format

The system generates multiple outputs:
1. **Cleaned Transcript**: Enhanced with proper formatting and punctuation
2. **Markdown Summary**: Including:
   - Title and overview
   - Key topics and concepts
   - Detailed section breakdowns
   - External resources and citations
   - Metadata and timestamps
3. **Professional PDF** (optional): Student-friendly academic format with:
   - Single-column layout for easy reading
   - Enhanced typography and spacing
   - Color-coded sections
   - **Professional LaTeX mathematical notation rendering**
   - Proper fractions, superscripts, subscripts, and scientific symbols
   - Reference citations

## Requirements

- Python 3.8+
- FFmpeg
- Internet connection for API access
- Sufficient disk space for video processing

## Limitations

- Video files must be in .mp4 format
- Currently supports English language only
- Maximum video file size depends on available RAM
- Google search limited to 100 queries per day on free tier

## Contributing

Contributions are welcome! Please feel free to submit pull requests.

## License

MIT License - See LICENSE file for details# summarize_video
