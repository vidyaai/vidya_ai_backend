"""
PDF generation service for assignments with LaTeX-style formatting.
Supports professional equation rendering, images, and research paper layout.
"""

import io
import base64
import re
import tempfile
import os
from typing import Dict, List, Any
from datetime import datetime
import requests

from controllers.storage import s3_presign_url

try:
    if os.name == "nt":
        # On Windows, add Tesseract-OCR to DLL search path for WeasyPrint dependencies
        os.add_dll_directory(r"C:\Program Files\Tesseract-OCR")
    from weasyprint import HTML, CSS

    WEASYPRINT_AVAILABLE = True
except ImportError as e:
    print(f"WeasyPrint import failed: {e}")
    WEASYPRINT_AVAILABLE = False

try:
    from markdown_katex.extension import tex2html

    MARKDOWN_KATEX_AVAILABLE = True
except ImportError as e:
    print(
        f"markdown-katex import failed: {e}. Install with: pip install markdown-katex"
    )
    MARKDOWN_KATEX_AVAILABLE = False

try:
    import matplotlib.pyplot as plt
    import matplotlib.mathtext as mathtext
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import matplotlib.patches as patches
    from matplotlib import rcParams
except ImportError:
    print("Matplotlib not installed. Install with: pip install matplotlib")

from controllers.config import logger


class AssignmentPDFGenerator:
    """Generates professional LaTeX-style PDFs for assignments."""

    def __init__(self):
        self.temp_dir = tempfile.mkdtemp()

        # Configure matplotlib for professional rendering
        self._configure_matplotlib_for_latex()

    def _configure_matplotlib_for_latex(self):
        """Configure matplotlib with professional LaTeX settings."""
        try:
            # Set up LaTeX-like font rendering
            rcParams.update(
                {
                    "font.size": 12,
                    "font.family": "serif",
                    "font.serif": ["DejaVu Serif", "Times New Roman"],
                    "text.usetex": False,  # We'll use mathtext which is more reliable
                    "mathtext.fontset": "cm",  # Computer Modern fonts
                    "mathtext.rm": "serif",
                    "mathtext.it": "serif:italic",
                    "mathtext.bf": "serif:bold",
                    "mathtext.sf": "sans\\-serif",  # Fixed syntax
                    "mathtext.tt": "monospace",
                    "mathtext.cal": "cursive",
                    "axes.unicode_minus": True,  # Use proper minus signs
                    "figure.dpi": 200,  # High DPI for crisp equations
                    "savefig.dpi": 200,
                    "savefig.format": "png",
                    "savefig.bbox": "tight",
                    "savefig.transparent": True,
                }
            )
        except Exception as e:
            logger.warning(f"Could not configure LaTeX settings: {e}")

    def render_latex_equation(
        self, latex_text: str, fontsize: int = 11, is_display: bool = False
    ) -> str:
        """
        Convert LaTeX to selectable HTML text with proper mathematical formatting.

        Args:
            latex_text: LaTeX equation string
            fontsize: Font size for the equation (matches text size)
            is_display: True for display equations (centered), False for inline

        Returns:
            HTML formatted mathematical expression as selectable text
        """
        # logger.info(f"Rendering LaTeX equation: {latex_text} (display={is_display})")
        try:
            # Clean up LaTeX text
            latex_text = latex_text.strip()

            # Remove outer $ signs if present
            if latex_text.startswith("$$") and latex_text.endswith("$$"):
                latex_text = latex_text[2:-2]
                is_display = True
            elif latex_text.startswith("$") and latex_text.endswith("$"):
                latex_text = latex_text[1:-1]

            # Convert LaTeX to HTML using markdown-katex if available
            html_equation = self._latex_to_html(latex_text, is_display=is_display)

            # Return formatted HTML
            if is_display:
                logger.info(f"Rendered display equation: {html_equation}")
                return f'<div class="math-display">{html_equation}</div>'
            else:
                return f'<span class="math-inline">{html_equation}</span>'

        except Exception as e:
            logger.warning(f"LaTeX conversion failed for '{latex_text}': {e}")
            # Fallback to plain text with basic formatting
            return f'<span class="math-fallback">{latex_text}</span>'

    def _enhance_latex_formatting(self, latex_text: str) -> str:
        """
        Enhance LaTeX text with proper mathematical formatting.

        Args:
            latex_text: Raw LaTeX text

        Returns:
            Enhanced LaTeX text with better typography
        """
        # Clean up common LaTeX issues
        enhanced = latex_text

        # Fix common spacing issues around operators (only if not already spaced)
        enhanced = re.sub(r"(?<!\s)\+(?!\s)", " + ", enhanced)
        enhanced = re.sub(r"(?<!\s)-(?!\s)", " - ", enhanced)
        enhanced = re.sub(r"(?<!\s)=(?!\s)", " = ", enhanced)
        enhanced = re.sub(r"(?<!\s)<(?!\s)", " < ", enhanced)
        enhanced = re.sub(r"(?<!\s)>(?!\s)", " > ", enhanced)

        # Ensure proper braces for single character sub/superscripts
        enhanced = re.sub(
            r"([a-zA-Z])_([a-zA-Z0-9])(?![a-zA-Z0-9{])", r"\1_{\2}", enhanced
        )
        enhanced = re.sub(
            r"([a-zA-Z])\^([a-zA-Z0-9])(?![a-zA-Z0-9{])", r"\1^{\2}", enhanced
        )

        return enhanced

    def _replace_ne_with_symbol(self, latex_text: str) -> str:
        """
        Replace \ne with the proper not-equal symbol for better rendering.

        Args:
            latex_text: LaTeX text
        Returns:
            LaTeX text with \ne replaced
        """
        return (
            latex_text.replace(r"\\neq", "\\not=")
            .replace(r"\\ne", "\\not=")
            .replace(r"\neq", "\\not=")
            .replace(r"\ne", "\\not=")
            .strip()
        )

    def _latex_to_html(self, latex_text: str, is_display: bool = False) -> str:
        """
        Convert LaTeX mathematical expressions to HTML.
        Uses markdown-katex if available, otherwise falls back to Unicode conversion.

        Args:
            latex_text: LaTeX mathematical expression

        Returns:
            HTML with rendered mathematics
        """
        # Try markdown-katex first (best quality for WeasyPrint)
        if MARKDOWN_KATEX_AVAILABLE:
            try:
                processed_latex_text = self._replace_ne_with_symbol(latex_text)
                # processed_latex_text = latex_text

                # Configure for WeasyPrint compatibility
                options = {
                    "no_inline_svg": False,
                    "insert_fonts_css": False,
                }
                html = tex2html(processed_latex_text, options)
                return html
            except Exception as e:
                logger.warning(
                    f"markdown-katex conversion failed for '{latex_text}': {e}. Falling back to Unicode."
                )

        # Fallback to Unicode conversion
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
            r"\\theta": "θ",
            r"\\Theta": "Θ",
            r"\\lambda": "λ",
            r"\\Lambda": "Λ",
            r"\\mu": "μ",
            r"\\pi": "π",
            r"\\Pi": "Π",
            r"\\sigma": "σ",
            r"\\Sigma": "Σ",
            r"\\tau": "τ",
            r"\\phi": "φ",
            r"\\Phi": "Φ",
            r"\\chi": "χ",
            r"\\psi": "ψ",
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
            r"\\infty": "∞",
            r"\\partial": "∂",
            r"\\nabla": "∇",
            r"\\sum": "∑",
            r"\\prod": "∏",
            r"\\int": "∫",
            r"\\oint": "∮",
            r"\\sqrt": "√",
            r"\\forall": "∀",
            r"\\exists": "∃",
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
            # Arrows
            r"\\rightarrow": "→",
            r"\\leftarrow": "←",
            r"\\leftrightarrow": "↔",
            r"\\Rightarrow": "⇒",
            r"\\Leftarrow": "⇐",
            r"\\Leftrightarrow": "⇔",
            # Other symbols
            r"\\deg": "°",
            r"\\angle": "∠",
            r"\\perp": "⊥",
            r"\\parallel": "∥",
        }

        # Replace symbols
        for latex_symbol, unicode_char in symbol_map.items():
            html = re.sub(latex_symbol + r"(?![a-zA-Z])", unicode_char, html)

        # Handle fractions \frac{numerator}{denominator}
        html = re.sub(
            r"\\frac\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}",
            lambda m: f'<span class="fraction"><span class="numerator">{self._latex_to_html(m.group(1))}</span><span class="fraction-bar">/</span><span class="denominator">{self._latex_to_html(m.group(2))}</span></span>',
            html,
        )

        # Handle superscripts ^{...} or ^char
        html = re.sub(r"\^{([^}]+)}", r"<sup>\1</sup>", html)
        html = re.sub(r"\^([a-zA-Z0-9])", r"<sup>\1</sup>", html)

        # Handle subscripts _{...} or _char
        html = re.sub(r"_{([^}]+)}", r"<sub>\1</sub>", html)
        html = re.sub(r"_([a-zA-Z0-9])", r"<sub>\1</sub>", html)

        # Handle square roots
        html = re.sub(
            r"\\sqrt\{([^}]+)\}", r'√<span class="sqrt-content">\1</span>', html
        )

        # Handle limits
        html = re.sub(r"\\lim_{([^}]+)}", r"lim<sub>\1</sub>", html)

        # Handle integrals with limits
        html = re.sub(
            r"\\int_\{([^}]+)\}\^\{([^}]+)\}", r"∫<sub>\1</sub><sup>\2</sup>", html
        )
        html = re.sub(
            r"\\int_([a-zA-Z0-9])\^([a-zA-Z0-9])", r"∫<sub>\1</sub><sup>\2</sup>", html
        )

        # Handle summation with limits
        html = re.sub(
            r"\\sum_{([^}]+)}\^{([^}]+)}", r"∑<sub>\1</sub><sup>\2</sup>", html
        )

        # Handle text in math mode
        html = re.sub(r"\\text\{([^}]+)\}", r'<span class="math-text">\1</span>', html)

        # Clean up remaining backslashes for simple commands
        html = re.sub(r"\\([a-zA-Z]+)", r"\1", html)

        return html

    def _simplify_latex_for_mathtext(self, latex_text: str) -> str:
        """
        Simplify LaTeX expressions that matplotlib mathtext cannot handle.

        Args:
            latex_text: Complex LaTeX text

        Returns:
            Simplified LaTeX text compatible with mathtext
        """
        simplified = latex_text

        # Replace unsupported matrix environments with simple notation
        simplified = re.sub(
            r"\\begin\{pmatrix\}([^}]+)\\end\{pmatrix\}", r"[\1]", simplified
        )
        simplified = re.sub(
            r"\\begin\{bmatrix\}([^}]+)\\end\{bmatrix\}", r"[\1]", simplified
        )
        simplified = re.sub(
            r"\\begin\{matrix\}([^}]+)\\end\{matrix\}", r"[\1]", simplified
        )

        # Replace double backslashes with commas in simplified matrices
        simplified = re.sub(r"\\\\", ", ", simplified)

        # Replace some complex symbols with simpler alternatives
        replacements = {
            r"\\vec\{([^}]+)\}": r"\mathbf{\1}",  # Vector notation
            r"\\text\{([^}]+)\}": r"\mathrm{\1}",  # Text in math mode
            r"\\mathrm\{([^}]+)\}": r"\1",  # Remove mathrm if problematic
        }

        for pattern, replacement in replacements.items():
            simplified = re.sub(pattern, replacement, simplified)

        return simplified

    def _render_fallback_equation(self, latex_text: str, fontsize: int = 14) -> str:
        """
        Fallback equation renderer for cases where main renderer fails.

        Args:
            latex_text: LaTeX equation text
            fontsize: Font size

        Returns:
            Base64 encoded simple text image
        """
        try:
            fig, ax = plt.subplots(figsize=(6, 1))

            # Simple text rendering with math font
            ax.text(
                0.5,
                0.5,
                latex_text,
                transform=ax.transAxes,
                fontsize=fontsize,
                ha="center",
                va="center",
                fontfamily="monospace",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="lightgray", alpha=0.3),
            )

            ax.axis("off")
            fig.patch.set_alpha(0)

            buf = io.BytesIO()
            plt.savefig(
                buf, format="png", bbox_inches="tight", transparent=True, dpi=150
            )
            buf.seek(0)

            img_base64 = base64.b64encode(buf.read()).decode("utf-8")
            plt.close(fig)

            return f"data:image/png;base64,{img_base64}"

        except Exception as e:
            logger.error(f"Fallback rendering failed: {e}")
            return ""

    def convert_text_math_to_latex(self, text: str) -> str:
        """
        Convert plain text mathematical notation to LaTeX format.
        Handles subscripts (x_1), superscripts (x^2), scientific notation, and special characters.
        
        Args:
            text: Text with plain subscript/superscript notation
            
        Returns:
            Text with notation converted to LaTeX $...$ format
        """
        if not text:
            return ""
        
        # Handle scientific notation with units: 7.0×10^−4 °C^−1
        # This must come FIRST before we process degree symbols separately
        scientific_with_units_pattern = r'([\d.]+)\s*[×x]\s*10\^([−\-]?\d+)\s*°C\^([−\-]?\d+)'
        
        def replace_scientific_with_units(match):
            coefficient = match.group(1)
            exponent = match.group(2).replace('−', '-')
            unit_exp = match.group(3).replace('−', '-')
            return f'${coefficient}\\times 10^{{{exponent}}}$ °C$^{{{unit_exp}}}$'
        
        text = re.sub(scientific_with_units_pattern, replace_scientific_with_units, text)
        
        # Now handle degree symbols for regular temperature values
        # Use HTML entity instead of LaTeX for better rendering
        text = text.replace('°C', '°C')
        text = text.replace('°', '°')
        
        # Handle regular scientific notation: 7.0×10^−4 or 7.0×10^-4
        scientific_pattern = r'([\d.]+)\s*[×x]\s*10\^([−\-]?\d+)'
        
        def replace_scientific(match):
            coefficient = match.group(1)
            exponent = match.group(2).replace('−', '-')
            return f'${coefficient}\\times 10^{{{exponent}}}$'
        
        text = re.sub(scientific_pattern, replace_scientific, text)
        
        # Pattern to match variable names with subscripts/superscripts
        # Matches patterns like: ρ_o, ρ_w, m^3, V_th, X_L, β_o, p_20, etc.
        math_pattern = r'([A-Za-zΔΔα-ωΑ-Ωβρ]+)([_^])([A-Za-z0-9]+)'
        
        def replace_math(match):
            base = match.group(1)
            operator = match.group(2)
            subscript = match.group(3)
            
            if operator == '_':
                return f'${base}_{{{subscript}}}$'
            else:  # ^
                return f'${base}^{{{subscript}}}$'
        
        # Convert underscore/caret notation to LaTeX
        text = re.sub(math_pattern, replace_math, text)
        
        # Clean up any double spaces or multiple $ signs next to each other
        text = re.sub(r'\$\s*\$', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        
        return text

    def process_question_text(self, text: str) -> str:
        """
        Process question text to render LaTeX equations as professional images.

        Args:
            text: Question text that may contain LaTeX equations

        Returns:
            HTML text with LaTeX equations rendered as high-quality images
        """
        if not text:
            return ""
        
        # First convert plain text math notation to LaTeX
        text = self.convert_text_math_to_latex(text)

        # Handle display equations: $$...$$ and \[...\]
        display_pattern = r"\$\$([^$]+?)\$\$"

        def replace_display_equation(match):
            latex_text = match.group(1)
            html_equation = self.render_latex_equation(
                latex_text, fontsize=11, is_display=True
            )
            return f'<div class="display-equation">{html_equation}</div>'

        processed_text = re.sub(display_pattern, replace_display_equation, text)
        processed_text = re.sub(
            r"\\\[(.+?)\\\]",
            lambda m: f'<div class="display-equation">{self.render_latex_equation(m.group(1), fontsize=11, is_display=True)}</div>',
            processed_text,
            flags=re.DOTALL,
        )

        # Handle inline equations: $...$ and \(...\)
        inline_pattern = r"\$([^$]+?)\$"

        def replace_inline_equation(match):
            latex_text = match.group(1)
            html_equation = self.render_latex_equation(
                latex_text, fontsize=11, is_display=False
            )
            return html_equation

        processed_text = re.sub(inline_pattern, replace_inline_equation, processed_text)
        processed_text = re.sub(
            r"\\\((.+?)\\\)",
            lambda m: self.render_latex_equation(m.group(1), fontsize=11, is_display=False),
            processed_text,
        )

        # Handle equation placeholders like <eq id> format (from your existing system)
        eq_placeholder_pattern = r"<eq\s+([^>]+)>"

        def replace_eq_placeholder(match):
            eq_id = match.group(1)
            # For now, show placeholder - this could be enhanced to look up actual LaTeX
            return f'<span class="equation-placeholder" style="background: #e3f2fd; padding: 2px 6px; border-radius: 3px; font-family: monospace;">[Equation {eq_id}]</span>'

        processed_text = re.sub(
            eq_placeholder_pattern, replace_eq_placeholder, processed_text
        )

        return processed_text

    def process_question_text_with_equations(
        self, text: str, equations: List[Dict[str, Any]] = None
    ) -> str:
        """
        Process question text with equations array (your existing system format).

        Args:
            text: Question text with <eq id> placeholders
            equations: List of equation objects with id, latex, position, type

        Returns:
            HTML text with equations rendered as professional images
        """
        if not text:
            return ""

        # Create equation lookup dictionary
        eq_lookup = {}
        if equations:
            for eq in equations:
                eq_lookup[eq.get("id", "")] = {
                    "latex": eq.get("latex", ""),
                    "display": eq.get("type", "inline") == "display",
                }

        # Then handle <eq id> placeholders with actual LaTeX lookup
        eq_placeholder_pattern = r"<eq\s+([^>]+)>"

        def replace_eq_placeholder_with_latex(match):
            eq_id = match.group(1)
            latex_text = eq_lookup.get(eq_id)["latex"] if eq_lookup.get(eq_id) else ""
            is_display = (
                eq_lookup.get(eq_id)["display"] if eq_lookup.get(eq_id) else False
            )

            logger.info(
                f"Processing equation placeholder: id={eq_id}, latex='{latex_text}', display={is_display}"
            )

            if latex_text:
                # Render the actual LaTeX equation as selectable text
                html_equation = self.render_latex_equation(
                    latex_text, fontsize=11, is_display=is_display
                )
                return html_equation
            else:
                # Fallback to placeholder display
                return f'<span class="equation-placeholder">[Equation {eq_id}]</span>'

        processed_text = re.sub(
            eq_placeholder_pattern, replace_eq_placeholder_with_latex, text
        )

        # Next handle standard LaTeX equations
        processed_text = self.process_question_text(processed_text)

        return processed_text

    def download_image_as_base64(self, image_url: str) -> str:
        """
        Download image from URL and convert to base64 data URI.

        Args:
            image_url: URL of the image to download

        Returns:
            Base64 encoded image data URI
        """
        try:
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()

            # Determine content type
            content_type = response.headers.get("content-type", "image/png")

            # Convert to base64
            img_base64 = base64.b64encode(response.content).decode("utf-8")
            return f"data:{content_type};base64,{img_base64}"

        except Exception as e:
            logger.error(f"Error downloading image from {image_url}: {e}")
            return ""

    def generate_question_html(
        self, question: Dict[str, Any], question_num: int
    ) -> str:
        """
        Generate HTML for a single question.

        Args:
            question: Question data dictionary
            question_num: Question number

        Returns:
            HTML string for the question
        """
        # Use enhanced processing that handles both LaTeX and equation placeholders
        equations = question.get("equations", [])
        if equations:
            question_text = self.process_question_text_with_equations(
                question.get("question", ""), equations
            )
        else:
            question_text = self.process_question_text(question.get("question", ""))

        question_type = question.get("type", "unknown")
        points = question.get("points", 0)
        difficulty = question.get("difficulty", "medium")

        # Difficulty badge colors
        difficulty_colors = {"easy": "#10b981", "medium": "#f59e0b", "hard": "#ef4444"}

        html = f"""
        <div class="question">
            <div class="question-header">
                <h3>Question {question_num}</h3>
                <div class="question-meta">
                    <span class="points">{points} points</span>
                    <span class="difficulty" style="background-color: {difficulty_colors.get(difficulty, '#6b7280')}">
                        {difficulty.title()}
                    </span>
                    <span class="type">{question_type.replace('-', ' ').title()}</span>
                </div>
            </div>

            <div class="question-text">
                {question_text}
            </div>
        """

        # Add code block if present
        # For code-writing questions, use starterCode (student template) instead of
        # code (which may contain the solution). For other types, code is reference code.
        if question_type in ("code-writing", "code_writing"):
            starter_code = question.get("starterCode", "")
            if starter_code:
                html += f"""
            <div class="question-code" style="background: #f3f4f6; padding: 10px; border-radius: 5px; font-family: monospace; white-space: pre-wrap; margin-top: 10px;">{starter_code}</div>
            """
        elif question.get("hasCode") and question.get("code"):
            code_text = question["code"]
            html += f"""
            <div class="question-code" style="background: #f3f4f6; padding: 10px; border-radius: 5px; font-family: monospace; white-space: pre-wrap; margin-top: 10px;">{code_text}</div>
            """

        # Add diagram if present
        if question.get("diagram") and question["diagram"].get("s3_key"):
            diagram_url = s3_presign_url(question["diagram"]["s3_key"])
            diagram_base64 = self.download_image_as_base64(diagram_url)
            if diagram_base64:
                html += f"""
                <div class="question-diagram">
                    <img src="{diagram_base64}" alt="Question diagram" style="max-width: 100%; height: auto;">
                </div>
                """

        # Add options for multiple choice questions
        if question_type == "multiple-choice" and question.get("options"):
            html += '<div class="question-options">'
            for i, option in enumerate(question["options"]):
                # Strip leading letter labels (e.g. "A) ", "A. ", "a) ") to avoid
                # duplication since the PDF adds its own A./B./C./D. prefixes.
                option_clean = re.sub(r"^[A-Za-z][).]\s*", "", option)
                # Process options with equations support too
                if equations:
                    option_text = self.process_question_text_with_equations(
                        option_clean, equations
                    )
                else:
                    option_text = self.process_question_text(option_clean)
                letter = chr(65 + i)  # A, B, C, D...
                html += f'<div class="option"><strong>{letter}.</strong> {option_text}</div>'
            html += "</div>"

        # Handle subquestions for multi-part questions
        if question.get("subquestions"):
            html += '<div class="subquestions">'
            for i, subq in enumerate(question["subquestions"]):
                # Process subquestion text with equations
                subq_equations = subq.get("equations", equations)
                if subq_equations:
                    logger.info(
                        f"Processing subquestion {i+1} {subq.get('question', '')} with equations."
                    )
                    subq_text = self.process_question_text_with_equations(
                        subq.get("question", ""), subq_equations
                    )
                else:
                    subq_text = self.process_question_text(subq.get("question", ""))

                subq_points = subq.get("points", 0)
                subq_type = subq.get("type", "short-answer")

                html += f"""
                <div class="subquestion">
                    <h4>Part {chr(97 + i)}) ({subq_points} points)</h4>
                    <div class="subquestion-text">{subq_text}</div>
                """

                # handle subquestion code block if present
                # For code-writing subquestions, use starterCode instead of code
                if subq_type in ("code-writing", "code_writing"):
                    starter_code = subq.get("starterCode", "")
                    if starter_code:
                        html += f"""
                    <div class="subquestion-code" style="background: #f3f4f6; padding: 10px; border-radius: 5px; font-family: monospace; white-space: pre-wrap; margin-top: 10px;">{starter_code}</div>
                    """
                elif subq.get("hasCode") and subq.get("code"):
                    code_text = subq["code"]
                    html += f"""
                    <div class="subquestion-code" style="background: #f3f4f6; padding: 10px; border-radius: 5px; font-family: monospace; white-space: pre-wrap; margin-top: 10px;">{code_text}</div>
                    """

                # handle subquestion diagram if present
                if subq.get("diagram") and subq["diagram"].get("s3_key"):
                    diagram_url = s3_presign_url(subq["diagram"]["s3_key"])
                    diagram_base64 = self.download_image_as_base64(diagram_url)
                    if diagram_base64:
                        html += f"""
                        <div class="subquestion-diagram">
                            <img src="{diagram_base64}" alt="Subquestion diagram" style="max-width: 100%; height: auto;">
                        </div>
                        """

                # Add options for multiple choice subquestions
                if subq_type == "multiple-choice" and subq.get("options"):
                    html += '<div class="question-options">'
                    for j, option in enumerate(subq["options"]):
                        option_clean = re.sub(r"^[A-Za-z][).]\s*", "", option)
                        if subq_equations:
                            option_text = self.process_question_text_with_equations(
                                option_clean, subq_equations
                            )
                        else:
                            option_text = self.process_question_text(option_clean)
                        letter = chr(65 + j)  # A, B, C, D...
                        html += f'<div class="option"><strong>{letter}.</strong> {option_text}</div>'
                    html += "</div>"

                # Handle sub-subquestions
                if subq.get("subquestions"):
                    html += '<div class="sub-subquestions" style="padding-left: 20px; margin-top: 10px;">'
                    for k, sub_subq in enumerate(subq["subquestions"]):
                        # Process sub-subquestion text with equations
                        sub_subq_equations = sub_subq.get("equations", subq_equations)
                        if sub_subq_equations:
                            sub_subq_text = self.process_question_text_with_equations(
                                sub_subq.get("question", ""), sub_subq_equations
                            )
                        else:
                            sub_subq_text = self.process_question_text(
                                sub_subq.get("question", "")
                            )

                        sub_subq_points = sub_subq.get("points", 0)
                        sub_subq_type = sub_subq.get("type", "short-answer")

                        html += f"""
                        <div class="sub-subquestion" style="margin-bottom: 12px;">
                            <h5 style="margin: 0 0 6px 0; font-size: 10.5pt; color: #666;">
                                Part {chr(97 + i)}.{k + 1}) ({sub_subq_points} points)
                            </h5>
                            <div class="sub-subquestion-text">{sub_subq_text}</div>
                        """

                        # Add options for multiple choice sub-subquestions
                        if sub_subq_type == "multiple-choice" and sub_subq.get(
                            "options"
                        ):
                            html += '<div class="question-options">'
                            for m, option in enumerate(sub_subq["options"]):
                                option_clean = re.sub(r"^[A-Za-z][).]\s*", "", option)
                                if sub_subq_equations:
                                    option_text = (
                                        self.process_question_text_with_equations(
                                            option_clean, sub_subq_equations
                                        )
                                    )
                                else:
                                    option_text = self.process_question_text(option_clean)
                                letter = chr(65 + m)  # A, B, C, D...
                                html += f'<div class="option"><strong>{letter}.</strong> {option_text}</div>'
                            html += "</div>"

                        html += """
                            <div class="answer-space">
                                <div class="answer-lines" style="height: 3em; border-bottom: 1px solid #ccc; margin: 8px 0;"></div>
                            </div>
                        </div>
                        """
                    html += "</div>"  # Close sub-subquestions

                html += "</div>"  # Close subquestion

            html += "</div>"  # Close subquestions

        html += "</div>"  # Close question div
        return html

    def generate_css(self) -> str:
        """Generate CSS for LaTeX-style document formatting."""
        return """
        @page {
            size: A4;
            margin: 1in;
            @top-center {
                content: string(doc-title);
                font-size: 10pt;
                color: #666;
            }
            @bottom-center {
                content: "Page " counter(page) " of " counter(pages);
                font-size: 9pt;
                color: #666;
            }
        }

        body {
            font-family: "Times New Roman", Times, serif;
            font-size: 11pt;
            line-height: 1.3;
            color: #000;
            margin: 0;
            padding: 0;
            text-align: justify;
        }

        /* KaTeX base styles for proper math rendering */
        .katex {
            font-size: 1em;
            text-indent: 0;
            font-family: KaTeX_Main, "Times New Roman", Times, serif;
        }

        .katex-display {
            margin: 0.5em 0;
            text-align: center;
        }

        .katex .mrel {
            font-family: KaTeX_Main, "Times New Roman", Times, serif;
        }

        /* Ensure not-equal and other relation symbols render correctly */
        .katex .mord.vbox .thinbox .rlap {
            display: inline-block;
        }

        .katex .strut {
            display: inline-block;
        }

        .katex-mathml {
            position: absolute;
            clip: rect(1px, 1px, 1px, 1px);
            padding: 0;
            border: 0;
            height: 1px;
            width: 1px;
            overflow: hidden;
        }

        .katex-html {
            display: inline-block;
        }

        .document-header {
            text-align: center;
            margin-bottom: 20px;
            padding-bottom: 10px;
        }

        .document-title {
            font-size: 14pt;
            font-weight: bold;
            margin-bottom: 6px;
            string-set: doc-title content();
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .document-meta {
            font-size: 10pt;
            color: #333;
            margin-bottom: 10px;
        }

        .instructions {
            margin-bottom: 15px;
            font-style: italic;
        }

        .instructions h3 {
            display: none; /* Hide instructions header for cleaner look */
        }

        .question {
            margin-bottom: 15px;
            page-break-inside: avoid;
        }

        .question-header {
            margin-bottom: 8px;
        }

        .question-header h3 {
            margin: 0;
            font-size: 11pt;
            color: #000;
            font-weight: bold;
            display: inline;
        }

        .question-meta {
            display: none; /* Hide meta information for clean paper look */
        }

        .points, .difficulty, .type {
            display: none; /* Hide badges for professional appearance */
        }

        .question-text {
            margin-bottom: 10px;
            line-height: 1.3;
            text-align: justify;
        }

        .question-diagram {
            text-align: center;
            margin: 15px 0;
        }

        .question-options {
            margin: 15px 0;
        }

        .option {
            margin: 8px 0;
            padding-left: 20px;
        }

        .answer-space {
            margin-top: 15px;
        }

        .answer-lines {
            border-bottom: 1px solid #ccc;
            margin: 8px 0;
        }

        .subquestions {
            margin-top: 15px;
            padding-left: 20px;
        }

        .subquestion {
            margin-bottom: 15px;
        }

        .subquestion h4 {
            margin: 0 0 8px 0;
            font-size: 11pt;
            color: #555;
        }

        .footer-info {
            margin-top: 40px;
            border-top: 1px solid #ddd;
            padding-top: 15px;
            font-size: 9pt;
            color: #666;
            text-align: center;
        }

        /* Professional Mathematical Text Styling */
        .display-equation {
            text-align: center;
            margin: 12px 0;
            padding: 0;
        }

        .math-display {
            display: block;
            text-align: center;
            font-family: "Times New Roman", Times, serif;
            font-size: 11pt;
            font-style: italic;
            user-select: text;
            margin: 12px 0;
        }

        .math-inline {
            font-family: "Times New Roman", Times, serif;
            font-size: 11pt;
            font-style: italic;
            user-select: text;
        }

        .math-fallback {
            font-family: "Times New Roman", Times, serif;
            font-size: 11pt;
            font-style: italic;
            user-select: text;
        }

        .equation-placeholder {
            font-family: "Times New Roman", Times, serif;
            font-size: 11pt;
            font-style: italic;
        }

        /* Mathematical formatting elements */
        .fraction {
            display: inline-block;
            text-align: center;
            vertical-align: middle;
        }

        .numerator {
            display: block;
            border-bottom: 1px solid black;
            padding-bottom: 1px;
            margin-bottom: 1px;
        }

        .denominator {
            display: block;
            padding-top: 1px;
        }

        .fraction-bar {
            display: none; /* Hide the slash, use border instead */
        }

        .sqrt-content {
            border-top: 1px solid black;
            padding-left: 2px;
        }

        .math-text {
            font-style: normal;
        }

        /* Superscripts and subscripts */
        sup, sub {
            font-size: 0.8em;
            line-height: 0;
        }

        /* Code blocks for mathematical expressions */
        code {
            font-family: "Times New Roman", Times, serif;
            font-size: 11pt;
            font-style: italic;
        }

        /* IEEE paper styling */
        .question-text {
            text-align: justify;
            line-height: 1.3;
            font-size: 11pt;
        }

        .question-text p {
            margin-bottom: 8px;
        }

        /* Multiple choice options - IEEE style */
        .question-options .option {
            margin: 4px 0;
            padding-left: 15px;
            line-height: 1.3;
        }

        .question-options .option strong {
            margin-right: 6px;
        }

        /* Professional diagram styling */
        .question-diagram img {
            max-width: 100%;
            height: auto;
        }

        /* Remove answer spaces completely */
        .answer-space {
            display: none;
        }

        .answer-lines {
            display: none;
        }
        """

    def generate_assignment_pdf(self, assignment: Dict[str, Any]) -> bytes:
        """
        Generate a professional PDF for an assignment.

        Args:
            assignment: Assignment data dictionary

        Returns:
            PDF content as bytes
        """
        try:
            title = assignment.get("title", "Assignment")
            description = assignment.get("description", "")
            questions = assignment.get("questions", [])
            total_points = assignment.get("total_points", 0)

            # Add KaTeX CSS if using markdown-katex
            katex_css = ""
            if MARKDOWN_KATEX_AVAILABLE:
                try:
                    # KaTeX CSS for proper math rendering
                    katex_css = """
                    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css" integrity="sha384-n8MVd4RsNIU0tAv4ct0nTaAbDJwPJzDEaqSD1odI+WdtXRGWt2kTvGFasHpSy3SV" crossorigin="anonymous">
                    <style>
                    .katex { font-size: 1em; }
                    .katex-display { margin: 0.5em 0; }
                    </style>
                    """
                except:
                    pass

            # Generate HTML content
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>{title}</title>
                {katex_css}
            </head>
            <body>
                <div class="document-header">
                    <div class="document-title">{title}</div>
                    <div class="document-meta">
                        Total Points: {total_points} | Questions: {len(questions)} | Date: {datetime.now().strftime('%B %d, %Y')}
                    </div>
                </div>

                {f'''
                <div class="instructions">
                    <p>{self.process_question_text(description)}</p>
                </div>
                ''' if description else ''}

                <div class="questions">
            """

            # Add each question
            for i, question in enumerate(questions, 1):
                html_content += self.generate_question_html(question, i)

            html_content += """
                </div>

                <div class="footer-info">
                    <p>Generated by Vidya AI Assignment System</p>
                </div>
            </body>
            </html>
            """

            # Generate PDF using WeasyPrint
            html_doc = HTML(string=html_content)
            css_doc = CSS(string=self.generate_css())

            # Fetch KaTeX CSS from CDN for proper math rendering
            stylesheets = [css_doc]
            if MARKDOWN_KATEX_AVAILABLE:
                try:
                    katex_cdn_css = CSS(
                        url="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css"
                    )
                    stylesheets.insert(0, katex_cdn_css)  # Add KaTeX CSS first
                    # stylesheets = [katex_cdn_css]  # Add only KaTeX CSS
                except Exception as e:
                    logger.warning(f"Failed to fetch KaTeX CSS from CDN: {e}")

            pdf_buffer = io.BytesIO()
            html_doc.write_pdf(pdf_buffer, stylesheets=stylesheets)
            pdf_buffer.seek(0)

            return pdf_buffer.getvalue()

        except Exception as e:
            logger.error(f"Error generating assignment PDF: {e}")
            raise

    def cleanup(self):
        """Clean up temporary files."""
        try:
            import shutil

            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except:
            pass
