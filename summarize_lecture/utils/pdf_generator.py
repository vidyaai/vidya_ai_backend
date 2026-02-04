"""
IEEE-style PDF generator for lecture summaries.
Converts markdown summaries to professional academic papers.
"""

import io
import base64
import re
import tempfile
import os
from typing import Dict, List, Any, Optional
from datetime import datetime
import requests
from pathlib import Path
import markdown
import logging

try:
    from weasyprint import HTML, CSS

    WEASYPRINT_AVAILABLE = True
except ImportError:
    print("WeasyPrint not installed. Install with: pip install weasyprint")
    WEASYPRINT_AVAILABLE = False

try:
    import matplotlib.pyplot as plt
    import matplotlib.mathtext as mathtext
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import matplotlib.patches as patches
    from matplotlib import rcParams

    MATPLOTLIB_AVAILABLE = True
except ImportError:
    print("Matplotlib not installed. Install with: pip install matplotlib")
    MATPLOTLIB_AVAILABLE = False

# Configure logging
logger = logging.getLogger(__name__)


class LectureSummaryPDFGenerator:
    """Generates professional single-column PDFs for lecture summaries with student-friendly formatting."""

    def __init__(self):
        if not WEASYPRINT_AVAILABLE:
            raise ImportError(
                "WeasyPrint is required for PDF generation. Install with: pip install weasyprint"
            )

        self.temp_dir = tempfile.mkdtemp()

        # Configure matplotlib for professional rendering if available
        if MATPLOTLIB_AVAILABLE:
            self._configure_matplotlib_for_latex()

    def _configure_matplotlib_for_latex(self):
        """Configure matplotlib with professional LaTeX settings."""
        try:
            rcParams.update(
                {
                    "font.size": 11,
                    "font.family": "serif",
                    "font.serif": ["Times New Roman", "DejaVu Serif"],
                    "text.usetex": False,
                    "mathtext.fontset": "cm",
                    "mathtext.rm": "serif",
                    "mathtext.it": "serif:italic",
                    "mathtext.bf": "serif:bold",
                    "axes.unicode_minus": True,
                    "figure.dpi": 200,
                    "savefig.dpi": 200,
                    "savefig.format": "png",
                    "savefig.bbox": "tight",
                    "savefig.transparent": True,
                }
            )
        except Exception as e:
            logger.warning(f"Could not configure LaTeX settings: {e}")

    def parse_markdown(self, markdown_content: str) -> Dict[str, Any]:
        """
        Parse markdown content and extract structured information.

        Args:
            markdown_content: Raw markdown content

        Returns:
            Dictionary with parsed content structure
        """
        lines = markdown_content.strip().split("\n")

        parsed = {
            "title": "",
            "overview": "",
            "key_concepts": [],
            "detailed_breakdown": [],
            "key_takeaways": [],
            "further_reading": [],
            "content": markdown_content,
        }

        current_section = None
        current_subsection = None
        current_content = []

        for line in lines:
            line = line.strip()

            # Extract title (first # heading)
            if line.startswith("# ") and not parsed["title"]:
                parsed["title"] = line[2:].strip()
                continue

            # Handle sections
            if line.startswith("## "):
                # Save previous section content
                if current_section and current_content:
                    content_text = "\n".join(current_content).strip()
                    if current_section == "overview":
                        parsed["overview"] = content_text
                    elif current_section == "key_concepts":
                        parsed["key_concepts"] = self._parse_section_content(
                            content_text
                        )
                    elif current_section == "detailed_breakdown":
                        parsed["detailed_breakdown"] = self._parse_numbered_list(
                            content_text
                        )
                    elif current_section == "key_takeaways":
                        parsed["key_takeaways"] = self._parse_bullet_list(content_text)
                    elif current_section == "further_reading":
                        parsed["further_reading"] = self._parse_links(content_text)

                # Start new section
                section_title = line[3:].strip().lower()
                if "overview" in section_title:
                    current_section = "overview"
                elif "key concepts" in section_title:
                    current_section = "key_concepts"
                elif "detailed breakdown" in section_title:
                    current_section = "detailed_breakdown"
                elif "key takeaways" in section_title:
                    current_section = "key_takeaways"
                elif "further reading" in section_title:
                    current_section = "further_reading"
                else:
                    current_section = section_title

                current_content = []
                continue

            # Collect content for current section
            if current_section:
                current_content.append(line)

        # Handle last section
        if current_section and current_content:
            content_text = "\n".join(current_content).strip()
            if current_section == "overview":
                parsed["overview"] = content_text
            elif current_section == "key_concepts":
                parsed["key_concepts"] = self._parse_section_content(content_text)
            elif current_section == "detailed_breakdown":
                parsed["detailed_breakdown"] = self._parse_numbered_list(content_text)
            elif current_section == "key_takeaways":
                parsed["key_takeaways"] = self._parse_bullet_list(content_text)
            elif current_section == "further_reading":
                parsed["further_reading"] = self._parse_links(content_text)

        return parsed

    def _parse_section_content(self, content: str) -> List[Dict[str, str]]:
        """Parse key concepts section with subsections."""
        sections = []
        lines = content.split("\n")
        current_subsection = None
        current_points = []

        for line in lines:
            line = line.strip()
            if line.startswith("### "):
                # Save previous subsection
                if current_subsection:
                    sections.append(
                        {
                            "title": current_subsection,
                            "content": "\n".join(current_points),
                        }
                    )

                # Start new subsection
                current_subsection = line[4:].strip()
                current_points = []
            elif line and current_subsection:
                current_points.append(line)

        # Add last subsection
        if current_subsection:
            sections.append(
                {"title": current_subsection, "content": "\n".join(current_points)}
            )

        return sections

    def _parse_numbered_list(self, content: str) -> List[Dict[str, str]]:
        """Parse numbered list sections."""
        items = []
        lines = content.split("\n")
        current_item = None
        current_content = []

        for line in lines:
            line = line.strip()
            # Match numbered items (1., 2., etc.)
            if re.match(r"^\d+\.\s+\*\*.*?\*\*", line):
                # Save previous item
                if current_item:
                    items.append(
                        {"title": current_item, "content": "\n".join(current_content)}
                    )

                # Extract title from bold text
                match = re.search(r"\*\*(.*?)\*\*", line)
                if match:
                    current_item = match.group(1)
                    # Get remaining content after the bold title
                    remaining = line[line.find("**", line.find("**") + 2) + 2 :].strip()
                    current_content = [remaining] if remaining else []
                else:
                    current_item = line
                    current_content = []
            elif line and current_item:
                current_content.append(line)

        # Add last item
        if current_item:
            items.append({"title": current_item, "content": "\n".join(current_content)})

        return items

    def _parse_bullet_list(self, content: str) -> List[str]:
        """Parse bullet point list."""
        items = []
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                items.append(line[2:].strip())
        return items

    def _parse_links(self, content: str) -> List[Dict[str, str]]:
        """Parse links section."""
        links = []
        lines = content.split("\n")

        for i, line in enumerate(lines):
            line = line.strip()
            # Look for markdown links
            link_match = re.search(r"\[([^\]]+)\]\(([^)]+)\)", line)
            if link_match:
                title = link_match.group(1)
                url = link_match.group(2)

                # Look for description in next line
                description = ""
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if not next_line.startswith("-") and not next_line.startswith("["):
                        description = next_line

                links.append({"title": title, "url": url, "description": description})

        return links

    def _latex_to_html(self, latex_text: str) -> str:
        """
        Convert LaTeX mathematical expressions to HTML with Unicode characters and proper formatting.

        Args:
            latex_text: LaTeX mathematical expression

        Returns:
            HTML with Unicode mathematical characters and proper formatting
        """
        html = latex_text

        # Common mathematical symbols
        symbol_map = {
            # Greek letters
            r"\\alpha": "α",
            r"\\beta": "β",
            r"\\gamma": "γ",
            r"\\delta": "δ",
            r"\\Delta": "Δ",
            r"\\epsilon": "ε",
            r"\\varepsilon": "ε",
            r"\\theta": "θ",
            r"\\vartheta": "ϑ",
            r"\\Theta": "Θ",
            r"\\lambda": "λ",
            r"\\Lambda": "Λ",
            r"\\mu": "μ",
            r"\\nu": "ν",
            r"\\xi": "ξ",
            r"\\Xi": "Ξ",
            r"\\pi": "π",
            r"\\Pi": "Π",
            r"\\rho": "ρ",
            r"\\varrho": "ϱ",
            r"\\sigma": "σ",
            r"\\varsigma": "ς",
            r"\\Sigma": "Σ",
            r"\\tau": "τ",
            r"\\upsilon": "υ",
            r"\\Upsilon": "Υ",
            r"\\phi": "φ",
            r"\\varphi": "ϕ",
            r"\\Phi": "Φ",
            r"\\chi": "χ",
            r"\\psi": "ψ",
            r"\\Psi": "Ψ",
            r"\\omega": "ω",
            r"\\Omega": "Ω",
            # Mathematical operators
            r"\\times": "×",
            r"\\cdot": "·",
            r"\\div": "÷",
            r"\\pm": "±",
            r"\\mp": "∓",
            r"\\leq": "≤",
            r"\\geq": "≥",
            r"\\neq": "≠",
            r"\\approx": "≈",
            r"\\equiv": "≡",
            r"\\sim": "∼",
            r"\\simeq": "≃",
            r"\\cong": "≅",
            r"\\propto": "∝",
            r"\\infty": "∞",
            r"\\partial": "∂",
            r"\\nabla": "∇",
            r"\\sum": "∑",
            r"\\prod": "∏",
            r"\\int": "∫",
            r"\\oint": "∮",
            r"\\iint": "∬",
            r"\\iiint": "∭",
            r"\\sqrt": "√",
            r"\\forall": "∀",
            r"\\exists": "∃",
            r"\\nexists": "∄",
            # Set theory
            r"\\in": "∈",
            r"\\notin": "∉",
            r"\\subset": "⊂",
            r"\\supset": "⊃",
            r"\\subseteq": "⊆",
            r"\\supseteq": "⊇",
            r"\\cup": "∪",
            r"\\cap": "∩",
            r"\\emptyset": "∅",
            r"\\varnothing": "∅",
            # Arrows
            r"\\rightarrow": "→",
            r"\\to": "→",
            r"\\leftarrow": "←",
            r"\\gets": "←",
            r"\\leftrightarrow": "↔",
            r"\\Rightarrow": "⇒",
            r"\\Leftarrow": "⇐",
            r"\\Leftrightarrow": "⇔",
            r"\\iff": "⇔",
            r"\\uparrow": "↑",
            r"\\downarrow": "↓",
            r"\\updownarrow": "↕",
            # Other symbols
            r"\\deg": "°",
            r"\\angle": "∠",
            r"\\perp": "⊥",
            r"\\parallel": "∥",
            r"\\hbar": "ℏ",
            r"\\ell": "ℓ",
            r"\\wp": "℘",
            r"\\Re": "ℜ",
            r"\\Im": "ℑ",
            r"\\aleph": "ℵ",
            r"\\beth": "ℶ",
            r"\\gimel": "ℷ",
            r"\\daleth": "ℸ",
        }

        # Replace symbols first
        for latex_symbol, unicode_char in symbol_map.items():
            html = re.sub(latex_symbol + r"(?![a-zA-Z])", unicode_char, html)

        # Handle fractions \frac{numerator}{denominator} with proper styling
        def format_fraction(match):
            numerator = self._latex_to_html(match.group(1))
            denominator = self._latex_to_html(match.group(2))
            return f'<span class="fraction"><span class="numerator">{numerator}</span><span class="denominator">{denominator}</span></span>'

        html = re.sub(
            r"\\frac\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}",
            format_fraction,
            html,
        )

        # Handle superscripts ^{...} or ^char (process before subscripts)
        html = re.sub(
            r"\^{([^}]+)}",
            lambda m: f"<sup>{self._latex_to_html(m.group(1))}</sup>",
            html,
        )
        html = re.sub(r"\^([a-zA-Z0-9+\-*/=<>().])", r"<sup>\1</sup>", html)

        # Handle subscripts _{...} or _char
        html = re.sub(
            r"_{([^}]+)}",
            lambda m: f"<sub>{self._latex_to_html(m.group(1))}</sub>",
            html,
        )
        html = re.sub(r"_([a-zA-Z0-9+\-*/=<>().])", r"<sub>\1</sub>", html)

        # Handle square roots
        html = re.sub(
            r"\\sqrt\{([^}]+)\}",
            lambda m: f'√<span class="sqrt-content">{self._latex_to_html(m.group(1))}</span>',
            html,
        )

        # Handle nth roots
        html = re.sub(
            r"\\sqrt\[([^]]+)\]\{([^}]+)\}",
            lambda m: f'<sup>{m.group(1)}</sup>√<span class="sqrt-content">{self._latex_to_html(m.group(2))}</span>',
            html,
        )

        # Handle limits
        html = re.sub(
            r"\\lim_{([^}]+)}",
            lambda m: f"lim<sub>{self._latex_to_html(m.group(1))}</sub>",
            html,
        )

        # Handle integrals with limits
        html = re.sub(
            r"\\int_\{([^}]+)\}\^\{([^}]+)\}",
            lambda m: f"∫<sub>{self._latex_to_html(m.group(1))}</sub><sup>{self._latex_to_html(m.group(2))}</sup>",
            html,
        )
        html = re.sub(
            r"\\int_([a-zA-Z0-9])\^([a-zA-Z0-9])", r"∫<sub>\1</sub><sup>\2</sup>", html
        )
        html = re.sub(
            r"\\int_{([^}]+)}",
            lambda m: f"∫<sub>{self._latex_to_html(m.group(1))}</sub>",
            html,
        )
        html = re.sub(
            r"\\int\^{([^}]+)}",
            lambda m: f"∫<sup>{self._latex_to_html(m.group(1))}</sup>",
            html,
        )

        # Handle summation with limits
        html = re.sub(
            r"\\sum_{([^}]+)}\^{([^}]+)}",
            lambda m: f"∑<sub>{self._latex_to_html(m.group(1))}</sub><sup>{self._latex_to_html(m.group(2))}</sup>",
            html,
        )
        html = re.sub(
            r"\\sum_{([^}]+)}",
            lambda m: f"∑<sub>{self._latex_to_html(m.group(1))}</sub>",
            html,
        )
        html = re.sub(
            r"\\sum\^{([^}]+)}",
            lambda m: f"∑<sup>{self._latex_to_html(m.group(1))}</sup>",
            html,
        )

        # Handle product with limits
        html = re.sub(
            r"\\prod_{([^}]+)}\^{([^}]+)}",
            lambda m: f"∏<sub>{self._latex_to_html(m.group(1))}</sub><sup>{self._latex_to_html(m.group(2))}</sup>",
            html,
        )

        # Handle text in math mode
        html = re.sub(r"\\text\{([^}]+)\}", r'<span class="math-text">\1</span>', html)
        html = re.sub(
            r"\\mathrm\{([^}]+)\}", r'<span class="math-text">\1</span>', html
        )
        html = re.sub(
            r"\\mathit\{([^}]+)\}", r'<span class="math-italic">\1</span>', html
        )
        html = re.sub(
            r"\\mathbf\{([^}]+)\}", r'<span class="math-bold">\1</span>', html
        )

        # Handle spacing commands
        html = re.sub(r"\\,", " ", html)  # thin space
        html = re.sub(r"\\;", "  ", html)  # medium space
        html = re.sub(r"\\quad", "    ", html)  # quad space
        html = re.sub(r"\\qquad", "        ", html)  # double quad space

        # Handle left and right delimiters
        html = re.sub(r"\\left\(", "(", html)
        html = re.sub(r"\\right\)", ")", html)
        html = re.sub(r"\\left\[", "[", html)
        html = re.sub(r"\\right\]", "]", html)
        html = re.sub(r"\\left\{", "{", html)
        html = re.sub(r"\\right\}", "}", html)
        html = re.sub(r"\\left\|", "|", html)
        html = re.sub(r"\\right\|", "|", html)

        # Clean up remaining backslashes for simple commands
        html = re.sub(r"\\([a-zA-Z]+)", r"\1", html)

        return html

    def process_text_formatting(self, text: str) -> str:
        """
        Process text formatting (bold, italic, code, LaTeX) for HTML.

        Args:
            text: Text with markdown and LaTeX formatting

        Returns:
            HTML formatted text with proper mathematical notation
        """
        if not text:
            return ""

        # First, process LaTeX expressions before markdown conversion
        # Handle display math ($$...$$)
        def process_display_math(match):
            latex_content = match.group(1)
            html_math = self._latex_to_html(latex_content)
            return f'<div class="math-display">{html_math}</div>'

        text = re.sub(r"\$\$([^$]+?)\$\$", process_display_math, text)

        # Handle inline math ($...$)
        def process_inline_math(match):
            latex_content = match.group(1)
            html_math = self._latex_to_html(latex_content)
            return f'<span class="math-inline">{html_math}</span>'

        text = re.sub(r"(?<!\$)\$([^$]+?)\$(?!\$)", process_inline_math, text)

        # Handle LaTeX expressions in parentheses like (equation)
        def process_paren_math(match):
            full_match = match.group(0)
            # Check if it contains LaTeX commands
            if "\\" in full_match and any(
                cmd in full_match for cmd in ["frac", "_", "^", "int", "sum"]
            ):
                latex_content = match.group(1)
                html_math = self._latex_to_html(latex_content)
                return f'<span class="math-inline">({html_math})</span>'
            return full_match

        text = re.sub(r"\(([^)]*\\[^)]*)\)", process_paren_math, text)

        # Convert markdown to HTML
        html = markdown.markdown(text, extensions=["extra", "codehilite"])

        # Additional processing for professional style
        # Make bold text more prominent
        html = re.sub(r"<strong>(.*?)</strong>", r'<span class="bold">\1</span>', html)

        # Style inline code
        html = re.sub(
            r"<code>(.*?)</code>", r'<span class="inline-code">\1</span>', html
        )

        return html

    def generate_ieee_css(self) -> str:
        """Generate student-friendly single-column CSS for academic papers."""
        return """
        @page {
            size: A4;
            margin: 0.75in 0.625in;
            @top-left {
                content: string(paper-title);
                font-size: 9pt;
                color: #666;
                font-weight: normal;
            }
            @top-right {
                content: "Lecture Summary";
                font-size: 9pt;
                color: #666;
            }
            @bottom-center {
                content: counter(page);
                font-size: 9pt;
                color: #666;
            }
        }

        body {
            font-family: "Times New Roman", Times, serif;
            font-size: 11pt;
            line-height: 1.4;
            color: #000;
            margin: 0;
            padding: 0 20pt;
            text-align: justify;
            hyphens: auto;
        }

        /* Title section */
        .paper-header {
            text-align: center;
            margin-bottom: 16pt;
            padding-bottom: 8pt;
            border-bottom: 1pt solid #000;
        }

        .paper-title {
            font-size: 16pt;
            font-weight: bold;
            margin-bottom: 10pt;
            string-set: paper-title content();
            text-transform: uppercase;
            letter-spacing: 0.5pt;
        }

        .paper-meta {
            font-size: 9pt;
            color: #333;
            font-style: italic;
            margin-bottom: 6pt;
        }

        .abstract {
            margin-bottom: 16pt;
            padding: 12pt 20pt;
            background-color: #f8f9fa;
            border-left: 4pt solid #007acc;
            border-radius: 4pt;
        }

        .abstract h3 {
            font-size: 12pt;
            font-weight: bold;
            margin: 0 0 8pt 0;
            text-transform: uppercase;
            letter-spacing: 0.5pt;
        }

        .abstract-text {
            font-size: 11pt;
            line-height: 1.4;
            text-align: justify;
        }

        /* Main content styling */
        h2 {
            font-size: 13pt;
            font-weight: bold;
            margin: 18pt 0 10pt 0;
            text-transform: uppercase;
            letter-spacing: 0.3pt;
            text-align: left;
            color: #2c3e50;
        }

        h3 {
            font-size: 12pt;
            font-weight: bold;
            margin: 14pt 0 6pt 0;
            font-style: italic;
            text-align: left;
            color: #34495e;
        }

        h4 {
            font-size: 11pt;
            font-weight: bold;
            margin: 12pt 0 4pt 0;
            text-align: left;
        }

        p {
            margin: 0 0 8pt 0;
            text-indent: 15pt;
            text-align: justify;
        }

        .no-indent {
            text-indent: 0;
        }

        /* Lists */
        ul, ol {
            margin: 8pt 0;
            padding-left: 24pt;
        }

        li {
            margin-bottom: 5pt;
            text-align: justify;
            line-height: 1.4;
        }

        /* Key concepts section */
        .key-concepts {
            margin: 12pt 0;
        }

        .concept {
            margin-bottom: 12pt;
            padding: 8pt;
            background-color: #fafafa;
            border-radius: 4pt;
            border-left: 3pt solid #3498db;
        }

        .concept-title {
            font-weight: bold;
            font-size: 11pt;
            margin-bottom: 4pt;
            color: #2c3e50;
        }

        .concept-content {
            margin-left: 0pt;
            font-size: 11pt;
            line-height: 1.4;
        }

        /* Detailed breakdown */
        .breakdown-item {
            margin-bottom: 14pt;
            padding: 10pt;
            background-color: #f8f9fa;
            border-radius: 4pt;
            border-left: 3pt solid #27ae60;
        }

        .breakdown-title {
            font-weight: bold;
            font-size: 11pt;
            margin-bottom: 4pt;
            color: #2c3e50;
        }

        .breakdown-content {
            margin-left: 0pt;
            font-size: 11pt;
            line-height: 1.4;
        }

        /* Key takeaways */
        .takeaways {
            background-color: #fff3cd;
            padding: 15pt;
            margin: 16pt 0;
            border: 2pt solid #ffc107;
            border-radius: 6pt;
        }

        .takeaways h3 {
            margin-top: 0;
        }

        .takeaway-list {
            list-style-type: none;
            padding-left: 0;
        }

        .takeaway-list li {
            margin-bottom: 6pt;
            position: relative;
            padding-left: 15pt;
            line-height: 1.5;
        }

        .takeaway-list li:before {
            content: "✓";
            position: absolute;
            left: 0;
            font-weight: bold;
            color: #f39c12;
            font-size: 12pt;
        }

        /* References section */
        .references {
            margin-top: 20pt;
            padding-top: 12pt;
            border-top: 2pt solid #bdc3c7;
        }

        .reference {
            margin-bottom: 10pt;
            font-size: 10pt;
            text-indent: -15pt;
            padding-left: 15pt;
            line-height: 1.3;
        }

        .reference-title {
            font-weight: bold;
        }

        .reference-url {
            color: #0066cc;
            text-decoration: none;
        }

        .reference-description {
            font-style: italic;
            color: #666;
        }

        /* Text formatting */
        .bold, strong {
            font-weight: bold;
        }

        .italic, em {
            font-style: italic;
        }

        .inline-code {
            font-family: "Courier New", monospace;
            font-size: 9pt;
            background-color: #f5f5f5;
            padding: 1pt 2pt;
            border-radius: 2pt;
        }

        /* Mathematical expressions */
        .math-inline {
            font-family: "Times New Roman", serif;
            font-style: italic;
            font-size: 11pt;
            white-space: nowrap;
        }

        .math-display {
            text-align: center;
            font-family: "Times New Roman", serif;
            font-style: italic;
            margin: 12pt 0;
            font-size: 12pt;
            padding: 8pt;
            background-color: #f9f9f9;
            border: 1pt solid #e0e0e0;
            border-radius: 3pt;
        }

        /* Fraction styling */
        .fraction {
            display: inline-block;
            vertical-align: middle;
            text-align: center;
            font-size: 0.9em;
        }

        .numerator {
            display: block;
            border-bottom: 1pt solid #000;
            padding: 0 2pt 1pt 2pt;
            line-height: 1.0;
        }

        .denominator {
            display: block;
            padding: 1pt 2pt 0 2pt;
            line-height: 1.0;
        }

        /* Square root styling */
        .sqrt-content {
            border-top: 1pt solid #000;
            padding-left: 2pt;
            display: inline-block;
        }

        /* Mathematical text styles */
        .math-text {
            font-style: normal;
            font-family: "Times New Roman", serif;
        }

        .math-italic {
            font-style: italic;
            font-family: "Times New Roman", serif;
        }

        .math-bold {
            font-weight: bold;
            font-family: "Times New Roman", serif;
            font-style: normal;
        }

        /* Superscripts and subscripts enhancement */
        sup, sub {
            font-size: 0.75em;
            line-height: 0;
            position: relative;
        }

        sup {
            top: -0.4em;
        }

        sub {
            bottom: -0.2em;
        }

        /* Mathematical operators spacing */
        .math-inline sup + sup,
        .math-inline sub + sub {
            margin-left: 1pt;
        }

        /* Prevent widows and orphans */
        p, li {
            orphans: 2;
            widows: 2;
        }

        h2, h3, h4 {
            page-break-after: avoid;
            orphans: 3;
            widows: 3;
        }

        /* Section styling */
        .section {
            break-inside: avoid;
            margin-bottom: 8pt;
        }

        /* Footer */
        .footer-info {
            margin-top: 30pt;
            padding-top: 10pt;
            border-top: 1pt solid #bdc3c7;
            font-size: 9pt;
            color: #7f8c8d;
            text-align: center;
            font-style: italic;
        }
        """

    def generate_html_content(self, parsed_content: Dict[str, Any]) -> str:
        """
        Generate IEEE-style HTML content from parsed markdown.

        Args:
            parsed_content: Parsed content dictionary

        Returns:
            HTML content string
        """
        title = parsed_content.get("title", "Lecture Summary")
        overview = parsed_content.get("overview", "")
        key_concepts = parsed_content.get("key_concepts", [])
        detailed_breakdown = parsed_content.get("detailed_breakdown", [])
        key_takeaways = parsed_content.get("key_takeaways", [])
        further_reading = parsed_content.get("further_reading", [])

        # Generate metadata
        generation_date = datetime.now().strftime("%B %d, %Y")

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>{title}</title>
        </head>
        <body>
            <div class="paper-header">
                <div class="paper-title">{title}</div>
                <div class="paper-meta">
                    Lecture Summary Document | Generated on {generation_date}
                </div>
            </div>

            {f'''
            <div class="abstract">
                <h3>Abstract</h3>
                <div class="abstract-text">
                    {self.process_text_formatting(overview)}
                </div>
            </div>
            ''' if overview else ''}

            {f'''
            <h2>I. Key Concepts</h2>
            <div class="key-concepts">
                {self._generate_key_concepts_html(key_concepts)}
            </div>
            ''' if key_concepts else ''}

            {f'''
            <h2>II. Detailed Analysis</h2>
            <div class="detailed-breakdown">
                {self._generate_breakdown_html(detailed_breakdown)}
            </div>
            ''' if detailed_breakdown else ''}

            {f'''
            <div class="takeaways">
                <h3>Key Takeaways</h3>
                <ul class="takeaway-list">
                    {self._generate_takeaways_html(key_takeaways)}
                </ul>
            </div>
            ''' if key_takeaways else ''}

            {f'''
            <div class="references">
                <h2>References</h2>
                {self._generate_references_html(further_reading)}
            </div>
            ''' if further_reading else ''}

            <div class="footer-info">
                Generated by Lecture Summary AI System
            </div>
        </body>
        </html>
        """

        return html_content

    def _generate_key_concepts_html(self, concepts: List[Dict[str, str]]) -> str:
        """Generate HTML for key concepts section."""
        html = ""
        for concept in concepts:
            title = concept.get("title", "")
            content = concept.get("content", "")

            html += f"""
            <div class="concept section">
                <div class="concept-title">{title}</div>
                <div class="concept-content">
                    {self.process_text_formatting(content)}
                </div>
            </div>
            """

        return html

    def _generate_breakdown_html(self, breakdown: List[Dict[str, str]]) -> str:
        """Generate HTML for detailed breakdown section."""
        html = ""
        for item in breakdown:
            title = item.get("title", "")
            content = item.get("content", "")

            html += f"""
            <div class="breakdown-item section">
                <div class="breakdown-title">{title}</div>
                <div class="breakdown-content">
                    {self.process_text_formatting(content)}
                </div>
            </div>
            """

        return html

    def _generate_takeaways_html(self, takeaways: List[str]) -> str:
        """Generate HTML for key takeaways."""
        html = ""
        for takeaway in takeaways:
            html += f"<li>{self.process_text_formatting(takeaway)}</li>\n"
        return html

    def _generate_references_html(self, references: List[Dict[str, str]]) -> str:
        """Generate HTML for references section."""
        html = ""
        for i, ref in enumerate(references, 1):
            title = ref.get("title", "")
            url = ref.get("url", "")
            description = ref.get("description", "")

            html += f"""
            <div class="reference">
                [{i}] <span class="reference-title">{title}</span>.
                Available: <a href="{url}" class="reference-url">{url}</a>
                {f'<span class="reference-description">. {description}</span>' if description else ''}
            </div>
            """

        return html

    def generate_pdf_from_markdown(
        self, markdown_file: str, output_file: str = None
    ) -> str:
        """
        Generate IEEE-style PDF from markdown file.

        Args:
            markdown_file: Path to markdown file
            output_file: Optional output PDF path

        Returns:
            Path to generated PDF file
        """
        try:
            # Read markdown content
            with open(markdown_file, "r", encoding="utf-8") as f:
                markdown_content = f.read()

            # Parse markdown content
            parsed_content = self.parse_markdown(markdown_content)

            # Generate HTML content
            html_content = self.generate_html_content(parsed_content)

            # Generate output filename if not provided
            if not output_file:
                input_path = Path(markdown_file)
                output_file = str(input_path.parent / f"{input_path.stem}_ieee.pdf")

            # Generate PDF using WeasyPrint
            html_doc = HTML(string=html_content)
            css_doc = CSS(string=self.generate_ieee_css())

            html_doc.write_pdf(output_file, stylesheets=[css_doc])

            logger.info(f"Generated IEEE-style PDF: {output_file}")
            return output_file

        except Exception as e:
            logger.error(f"Error generating PDF from {markdown_file}: {e}")
            raise

    def generate_pdf_from_content(self, markdown_content: str, output_file: str) -> str:
        """
        Generate IEEE-style PDF from markdown content string.

        Args:
            markdown_content: Markdown content as string
            output_file: Output PDF path

        Returns:
            Path to generated PDF file
        """
        try:
            # Parse markdown content
            parsed_content = self.parse_markdown(markdown_content)

            # Generate HTML content
            html_content = self.generate_html_content(parsed_content)

            # Generate PDF using WeasyPrint
            html_doc = HTML(string=html_content)
            css_doc = CSS(string=self.generate_ieee_css())

            html_doc.write_pdf(output_file, stylesheets=[css_doc])

            logger.info(f"Generated IEEE-style PDF: {output_file}")
            return output_file

        except Exception as e:
            logger.error(f"Error generating PDF: {e}")
            raise

    def cleanup(self):
        """Clean up temporary files."""
        try:
            import shutil

            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception as e:
            logger.warning(f"Error cleaning up temp directory: {e}")


# Convenience functions
def generate_pdf_from_markdown_file(markdown_file: str, output_file: str = None) -> str:
    """
    Convenience function to generate PDF from markdown file.

    Args:
        markdown_file: Path to markdown file
        output_file: Optional output PDF path

    Returns:
        Path to generated PDF file
    """
    generator = LectureSummaryPDFGenerator()
    try:
        return generator.generate_pdf_from_markdown(markdown_file, output_file)
    finally:
        generator.cleanup()


def generate_pdf_from_markdown_content(markdown_content: str, output_file: str) -> str:
    """
    Convenience function to generate PDF from markdown content.

    Args:
        markdown_content: Markdown content as string
        output_file: Output PDF path

    Returns:
        Path to generated PDF file
    """
    generator = LectureSummaryPDFGenerator()
    try:
        return generator.generate_pdf_from_content(markdown_content, output_file)
    finally:
        generator.cleanup()


if __name__ == "__main__":
    # Example usage
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pdf_generator.py <markdown_file> [output_file]")
        sys.exit(1)

    markdown_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        pdf_path = generate_pdf_from_markdown_file(markdown_file, output_file)
        print(f"Successfully generated PDF: {pdf_path}")
    except Exception as e:
        print(f"Error generating PDF: {e}")
        sys.exit(1)
