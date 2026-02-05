# Professional PDF Generation for Lecture Summaries

This document explains how to use the professional PDF generation feature for your lecture summaries.

## Overview

The PDF generator converts your markdown lecture summaries into professional academic papers with:
- Single-column layout optimized for student reading
- Professional typography with Times New Roman font
- Structured sections (Abstract, Key Concepts, Detailed Analysis, etc.)
- Color-coded sections for better visual organization
- Proper mathematical formatting
- Academic references formatting
- Student-friendly formatting with enhanced readability

## Installation

### Dependencies Required

The PDF generation feature requires additional packages:

```bash
# Install using your virtual environment
/path/to/your/venv/bin/python -m pip install weasyprint markdown matplotlib requests
```

Or use the provided installation script:

```bash
python install_pdf_deps.py
```

### System Dependencies (macOS)

WeasyPrint may require additional system libraries. If you encounter issues:

```bash
# Install using Homebrew
brew install cairo pango gdk-pixbuf libffi
```

## Usage

### 1. Automatic PDF Generation (Integrated)

When running the main summarization workflow:

```bash
/path/to/your/venv/bin/python main.py
```

After the summary is generated, you'll be prompted:
```
📄 Would you like to generate a professional PDF? (y/n): y
```

Choose 'y' to automatically generate the student-friendly PDF alongside your markdown summary.

### 2. Manual PDF Generation

#### Convert a Single File

```bash
/path/to/your/venv/bin/python generate_pdf.py path/to/summary.md
```

Example:
```bash
/path/to/your/venv/bin/python generate_pdf.py output/semiconductor_summary.md
```

#### Convert All Files in Output Directory

```bash
/path/to/your/venv/bin/python generate_pdf.py --all
```

This will convert all `.md` files in the `output/` directory to IEEE-style PDFs.

#### Specify Custom Output Location

```bash
/path/to/your/venv/bin/python generate_pdf.py input.md --output custom_name.pdf
```

## Generated PDF Features

### Document Structure

1. **Header Section**
   - Document title (uppercase, centered)
   - Generation metadata (date, document type)

2. **Abstract Section** (if overview is present)
   - Highlighted with border and background
   - Concise summary of the lecture content

3. **Main Content**
   - **I. Key Concepts**: Structured subsections with important topics
   - **II. Detailed Analysis**: Numbered breakdown of main points
   - **Key Takeaways**: Highlighted bullet points with special formatting

4. **References Section**
   - Numbered IEEE-style references
   - Clickable URLs
   - Descriptions for each source

### Typography and Layout

- **Font**: Times New Roman (academic standard)
- **Layout**: Single-column format for enhanced readability
- **Font Sizes**:
  - Body text: 11pt (optimized for reading)
  - Headings: 12-16pt (hierarchical with colors)
  - References: 10pt (improved readability)
- **Line spacing**: 1.4 (student-friendly spacing)
- **Margins**: 0.75" top/bottom, 0.625" left/right with 20pt padding
- **Visual Elements**:
  - Color-coded section borders
  - Background highlighting for key areas
  - Enhanced bullet points with checkmarks

### Mathematical Content

The PDF generator supports comprehensive LaTeX mathematical formatting:

#### Text Formatting
- **Bold text**: `**important terms**` → **important terms**
- **Italic text**: `*emphasis*` → *emphasis*
- **Inline code**: `\`technical_terms\`` → `technical_terms`

#### Mathematical Expressions
- **Inline math**: `$E = mc^2$` → E = mc²
- **Display math**: `$$x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$$` → Centered equation
- **Fractions**: `\frac{numerator}{denominator}` → Proper fraction layout
- **Superscripts/Subscripts**: `x^2`, `H_2O` → x², H₂O
- **Greek letters**: `\alpha`, `\beta`, `\gamma` → α, β, γ
- **Mathematical operators**: `\times`, `\div`, `\pm` → ×, ÷, ±
- **Integrals**: `\int_a^b f(x) dx` → Proper integral notation
- **Summations**: `\sum_{i=1}^n x_i` → Proper summation notation
- **Square roots**: `\sqrt{expression}` → √expression

## File Naming Convention

Generated PDFs follow this naming pattern:
```
[original_filename]_ieee.pdf
```

Examples:
- `semiconductor_summary.md` → `semiconductor_summary_ieee.pdf`
- `quantum_physics_lecture.md` → `quantum_physics_lecture_ieee.pdf`

## Troubleshooting

### Common Issues

1. **"WeasyPrint not installed" Error**
   ```bash
   # Solution: Install WeasyPrint
   /path/to/your/venv/bin/python -m pip install weasyprint
   ```

2. **Font Rendering Issues**
   ```bash
   # Install system fonts (macOS)
   brew install --cask font-times-new-roman
   ```

3. **Import Errors**
   - Ensure you're using the correct virtual environment path
   - Verify all dependencies are installed in the same environment

### Checking Installation

Test if all dependencies are available:

```bash
/path/to/your/venv/bin/python -c "import weasyprint, markdown, matplotlib, requests; print('All dependencies available')"
```

## Integration with Your Workflow

The PDF generation is seamlessly integrated into your existing lecture summarization workflow:

1. **Video Processing** → Transcription → AI Analysis → **Markdown Summary**
2. **PDF Generation** (optional) → **Professional IEEE-style Document**

The generated PDFs are perfect for:
- Academic presentations
- Research documentation
- Sharing with colleagues
- Archival purposes
- Professional reports

## Example Output

Your markdown summaries like:

```markdown
# The Essential Role of Semiconductors in Modern Technology

**Overview**
Semiconductors are integral to various technologies...

## Key Concepts
### What is a Semiconductor?
- A semiconductor is a material...
```

Are transformed into professional IEEE-style academic papers with proper formatting, typography, and structure.

---

For technical support or feature requests, please refer to the main project documentation.