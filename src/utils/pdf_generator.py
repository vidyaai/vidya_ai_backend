"""
PDF generation service for assignments with LaTeX-style formatting.
Supports professional equation rendering, images, and research paper layout.
"""

import io
import base64
import re
import tempfile
import os
from typing import Dict, List, Any, Optional
from datetime import datetime
import requests

try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except ImportError as e:
    print(f"WeasyPrint import failed: {e}")
    WEASYPRINT_AVAILABLE = False

try:
    import matplotlib.pyplot as plt
    import matplotlib.mathtext as mathtext
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import matplotlib.patches as patches
    from matplotlib import rcParams
except ImportError:
    print("Matplotlib not installed. Install with: pip install matplotlib")

try:
    import sympy as sp
    from sympy import latex, preview
    # Note: sympy.parsing.latex is optional and may not be available in all versions
    try:
        from sympy.parsing.latex import parse_latex
        SYMPY_LATEX_PARSER = True
    except ImportError:
        SYMPY_LATEX_PARSER = False
    SYMPY_AVAILABLE = True
except ImportError as e:
    print(f"SymPy import failed: {e}")
    SYMPY_AVAILABLE = False
    SYMPY_LATEX_PARSER = False

try:
    from latex2mathml.converter import convert as latex_to_mathml
    LATEX2MATHML_AVAILABLE = True
except ImportError as e:
    print(f"latex2mathml import failed: {e}")
    LATEX2MATHML_AVAILABLE = False

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
            rcParams.update({
                'font.size': 12,
                'font.family': 'serif',
                'font.serif': ['DejaVu Serif', 'Times New Roman'],
                'text.usetex': False,  # We'll use mathtext which is more reliable
                'mathtext.fontset': 'cm',  # Computer Modern fonts
                'mathtext.rm': 'serif',
                'mathtext.it': 'serif:italic', 
                'mathtext.bf': 'serif:bold',
                'mathtext.sf': 'sans\\-serif',  # Fixed syntax
                'mathtext.tt': 'monospace',
                'mathtext.cal': 'cursive',
                'axes.unicode_minus': True,  # Use proper minus signs
                'figure.dpi': 200,  # High DPI for crisp equations
                'savefig.dpi': 200,
                'savefig.format': 'png',
                'savefig.bbox': 'tight',
                'savefig.transparent': True
            })
        except Exception as e:
            logger.warning(f"Could not configure LaTeX settings: {e}")
        
    def render_latex_equation(self, latex_text: str, fontsize: int = 11, is_display: bool = False) -> str:
        """
        Convert LaTeX to selectable HTML text with proper mathematical formatting.
        
        Args:
            latex_text: LaTeX equation string
            fontsize: Font size for the equation (matches text size)
            is_display: True for display equations (centered), False for inline
            
        Returns:
            HTML formatted mathematical expression as selectable text
        """
        try:
            # Clean up LaTeX text
            latex_text = latex_text.strip()
            
            # Remove outer $ signs if present
            if latex_text.startswith('$$') and latex_text.endswith('$$'):
                latex_text = latex_text[2:-2]
                is_display = True
            elif latex_text.startswith('$') and latex_text.endswith('$'):
                latex_text = latex_text[1:-1]
            
            # Convert LaTeX to selectable HTML using Unicode and CSS
            html_equation = self._latex_to_html(latex_text)
            
            # Return formatted HTML
            if is_display:
                return f'<span class="math-display">{html_equation}</span>'
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
        enhanced = re.sub(r'(?<!\s)\+(?!\s)', ' + ', enhanced)
        enhanced = re.sub(r'(?<!\s)-(?!\s)', ' - ', enhanced)  
        enhanced = re.sub(r'(?<!\s)=(?!\s)', ' = ', enhanced)
        enhanced = re.sub(r'(?<!\s)<(?!\s)', ' < ', enhanced)
        enhanced = re.sub(r'(?<!\s)>(?!\s)', ' > ', enhanced)
        
        # Ensure proper braces for single character sub/superscripts
        enhanced = re.sub(r'([a-zA-Z])_([a-zA-Z0-9])(?![a-zA-Z0-9{])', r'\1_{\2}', enhanced)
        enhanced = re.sub(r'([a-zA-Z])\^([a-zA-Z0-9])(?![a-zA-Z0-9{])', r'\1^{\2}', enhanced)
        
        return enhanced
    
    def _latex_to_html(self, latex_text: str) -> str:
        """
        Convert LaTeX mathematical expressions to HTML with Unicode characters.
        
        Args:
            latex_text: LaTeX mathematical expression
            
        Returns:
            HTML with Unicode mathematical characters
        """
        html = latex_text
        
        # Common mathematical symbols
        symbol_map = {
            # Greek letters
            r'\\alpha': 'α', r'\\beta': 'β', r'\\gamma': 'γ', r'\\delta': 'δ', r'\\Delta': 'Δ',
            r'\\epsilon': 'ε', r'\\theta': 'θ', r'\\Theta': 'Θ', r'\\lambda': 'λ', r'\\Lambda': 'Λ',
            r'\\mu': 'μ', r'\\pi': 'π', r'\\Pi': 'Π', r'\\sigma': 'σ', r'\\Sigma': 'Σ',
            r'\\tau': 'τ', r'\\phi': 'φ', r'\\Phi': 'Φ', r'\\chi': 'χ', r'\\psi': 'ψ', r'\\omega': 'ω', r'\\Omega': 'Ω',
            
            # Mathematical operators
            r'\\times': '×', r'\\cdot': '·', r'\\div': '÷', r'\\pm': '±', r'\\mp': '∓',
            r'\\leq': '≤', r'\\geq': '≥', r'\\neq': '≠', r'\\approx': '≈', r'\\equiv': '≡',
            r'\\infty': '∞', r'\\partial': '∂', r'\\nabla': '∇', r'\\sum': '∑', r'\\prod': '∏',
            r'\\int': '∫', r'\\oint': '∮', r'\\sqrt': '√', r'\\forall': '∀', r'\\exists': '∃',
            
            # Set theory
            r'\\in': '∈', r'\\notin': '∉', r'\\subset': '⊂', r'\\supset': '⊃', r'\\subseteq': '⊆',
            r'\\supseteq': '⊇', r'\\cup': '∪', r'\\cap': '∩', r'\\emptyset': '∅', 
            
            # Arrows
            r'\\rightarrow': '→', r'\\leftarrow': '←', r'\\leftrightarrow': '↔',
            r'\\Rightarrow': '⇒', r'\\Leftarrow': '⇐', r'\\Leftrightarrow': '⇔',
            
            # Other symbols
            r'\\deg': '°', r'\\angle': '∠', r'\\perp': '⊥', r'\\parallel': '∥',
        }
        
        # Replace symbols
        for latex_symbol, unicode_char in symbol_map.items():
            html = re.sub(latex_symbol + r'(?![a-zA-Z])', unicode_char, html)
        
        # Handle fractions \frac{numerator}{denominator}
        html = re.sub(r'\\frac\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}',
                     lambda m: f'<span class="fraction"><span class="numerator">{self._latex_to_html(m.group(1))}</span><span class="fraction-bar">/</span><span class="denominator">{self._latex_to_html(m.group(2))}</span></span>',
                     html)
        
        # Handle superscripts ^{...} or ^char
        html = re.sub(r'\^{([^}]+)}', r'<sup>\1</sup>', html)
        html = re.sub(r'\^([a-zA-Z0-9])', r'<sup>\1</sup>', html)
        
        # Handle subscripts _{...} or _char
        html = re.sub(r'_{([^}]+)}', r'<sub>\1</sub>', html)
        html = re.sub(r'_([a-zA-Z0-9])', r'<sub>\1</sub>', html)
        
        # Handle square roots
        html = re.sub(r'\\sqrt\{([^}]+)\}', r'√<span class="sqrt-content">\1</span>', html)
        
        # Handle limits
        html = re.sub(r'\\lim_{([^}]+)}', r'lim<sub>\1</sub>', html)
        
        # Handle integrals with limits
        html = re.sub(r'\\int_\{([^}]+)\}\^\{([^}]+)\}', r'∫<sub>\1</sub><sup>\2</sup>', html)
        html = re.sub(r'\\int_([a-zA-Z0-9])\^([a-zA-Z0-9])', r'∫<sub>\1</sub><sup>\2</sup>', html)
        
        # Handle summation with limits
        html = re.sub(r'\\sum_{([^}]+)}\^{([^}]+)}', r'∑<sub>\1</sub><sup>\2</sup>', html)
        
        # Handle text in math mode
        html = re.sub(r'\\text\{([^}]+)\}', r'<span class="math-text">\1</span>', html)
        
        # Clean up remaining backslashes for simple commands
        html = re.sub(r'\\([a-zA-Z]+)', r'\1', html)
        
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
        simplified = re.sub(r'\\begin\{pmatrix\}([^}]+)\\end\{pmatrix\}', 
                           r'[\1]', simplified)
        simplified = re.sub(r'\\begin\{bmatrix\}([^}]+)\\end\{bmatrix\}', 
                           r'[\1]', simplified)
        simplified = re.sub(r'\\begin\{matrix\}([^}]+)\\end\{matrix\}', 
                           r'[\1]', simplified)
        
        # Replace double backslashes with commas in simplified matrices  
        simplified = re.sub(r'\\\\', ', ', simplified)
        
        # Replace some complex symbols with simpler alternatives
        replacements = {
            r'\\vec\{([^}]+)\}': r'\mathbf{\1}',  # Vector notation
            r'\\text\{([^}]+)\}': r'\mathrm{\1}',  # Text in math mode
            r'\\mathrm\{([^}]+)\}': r'\1',  # Remove mathrm if problematic
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
            ax.text(0.5, 0.5, latex_text, 
                   transform=ax.transAxes,
                   fontsize=fontsize,
                   ha='center', 
                   va='center',
                   fontfamily='monospace',
                   bbox=dict(boxstyle='round,pad=0.3', 
                           facecolor='lightgray', 
                           alpha=0.3))
            
            ax.axis('off')
            fig.patch.set_alpha(0)
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight', 
                       transparent=True, dpi=150)
            buf.seek(0)
            
            img_base64 = base64.b64encode(buf.read()).decode('utf-8')
            plt.close(fig)
            
            return f"data:image/png;base64,{img_base64}"
            
        except Exception as e:
            logger.error(f"Fallback rendering failed: {e}")
            return ""
    
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
        
        # First handle display equations ($$equation$$)
        display_pattern = r'\$\$([^$]+?)\$\$'
        
        def replace_display_equation(match):
            latex_text = match.group(1)
            html_equation = self.render_latex_equation(latex_text, fontsize=11, is_display=True)
            return f'<div class="display-equation">{html_equation}</div>'
        
        # Replace display equations first
        processed_text = re.sub(display_pattern, replace_display_equation, text)
        
        # Then handle inline equations ($equation$)
        inline_pattern = r'\$([^$]+?)\$'
        
        def replace_inline_equation(match):
            latex_text = match.group(1)
            html_equation = self.render_latex_equation(latex_text, fontsize=11, is_display=False)
            return html_equation
        
        # Replace inline equations
        processed_text = re.sub(inline_pattern, replace_inline_equation, processed_text)
        
        # Handle equation placeholders like <eq id> format (from your existing system)
        eq_placeholder_pattern = r'<eq\s+([^>]+)>'
        
        def replace_eq_placeholder(match):
            eq_id = match.group(1)
            # For now, show placeholder - this could be enhanced to look up actual LaTeX
            return f'<span class="equation-placeholder" style="background: #e3f2fd; padding: 2px 6px; border-radius: 3px; font-family: monospace;">[Equation {eq_id}]</span>'
        
        processed_text = re.sub(eq_placeholder_pattern, replace_eq_placeholder, processed_text)
        
        return processed_text
    
    def process_question_text_with_equations(self, text: str, equations: List[Dict[str, Any]] = None) -> str:
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
                eq_lookup[eq.get('id', '')] = eq.get('latex', '')
        
        # First handle standard LaTeX equations
        processed_text = self.process_question_text(text)
        
        # Then handle <eq id> placeholders with actual LaTeX lookup
        eq_placeholder_pattern = r'<eq\s+([^>]+)>'
        
        def replace_eq_placeholder_with_latex(match):
            eq_id = match.group(1)
            latex_text = eq_lookup.get(eq_id, '')
            
            if latex_text:
                # Render the actual LaTeX equation as selectable text
                html_equation = self.render_latex_equation(latex_text, fontsize=11, is_display=False)
                return html_equation
            else:
                # Fallback to placeholder display
                return f'<span class="equation-placeholder">[Equation {eq_id}]</span>'
        
        processed_text = re.sub(eq_placeholder_pattern, replace_eq_placeholder_with_latex, processed_text)
        
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
            content_type = response.headers.get('content-type', 'image/png')
            
            # Convert to base64
            img_base64 = base64.b64encode(response.content).decode('utf-8')
            return f"data:{content_type};base64,{img_base64}"
            
        except Exception as e:
            logger.error(f"Error downloading image from {image_url}: {e}")
            return ""
    
    def generate_question_html(self, question: Dict[str, Any], question_num: int) -> str:
        """
        Generate HTML for a single question.
        
        Args:
            question: Question data dictionary
            question_num: Question number
            
        Returns:
            HTML string for the question
        """
        # Use enhanced processing that handles both LaTeX and equation placeholders
        equations = question.get('equations', [])
        if equations:
            question_text = self.process_question_text_with_equations(question.get('question', ''), equations)
        else:
            question_text = self.process_question_text(question.get('question', ''))
            
        question_type = question.get('type', 'unknown')
        points = question.get('points', 0)
        difficulty = question.get('difficulty', 'medium')
        
        # Difficulty badge colors
        difficulty_colors = {
            'easy': '#10b981',
            'medium': '#f59e0b', 
            'hard': '#ef4444'
        }
        
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
        
        # Add diagram if present
        if question.get('diagram') and question['diagram'].get('url'):
            diagram_url = question['diagram']['url']
            diagram_base64 = self.download_image_as_base64(diagram_url)
            if diagram_base64:
                html += f"""
                <div class="question-diagram">
                    <img src="{diagram_base64}" alt="Question diagram" style="max-width: 100%; height: auto;">
                </div>
                """
        
        # Add options for multiple choice questions
        if question_type == 'multiple-choice' and question.get('options'):
            html += '<div class="question-options">'
            for i, option in enumerate(question['options']):
                # Process options with equations support too
                option_text = self.process_question_text(option)
                letter = chr(65 + i)  # A, B, C, D...
                html += f'<div class="option"><strong>{letter}.</strong> {option_text}</div>'
            html += '</div>'
        
        # No answer spaces for professional question paper format
        
        # Handle subquestions for multi-part questions
        if question.get('subquestions'):
            html += '<div class="subquestions">'
            for i, subq in enumerate(question['subquestions']):
                subq_text = self.process_question_text(subq.get('question', ''))
                subq_points = subq.get('points', 0)
                html += f"""
                <div class="subquestion">
                    <h4>Part {chr(97 + i)}) ({subq_points} points)</h4>
                    <div class="subquestion-text">{subq_text}</div>
                    <div class="answer-space">
                        <div class="answer-lines" style="height: 4.5em; border-bottom: 1px solid #ccc; margin: 10px 0;"></div>
                    </div>
                </div>
                """
            html += '</div>'
        
        html += '</div>'  # Close question div
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
            margin: 8px 0;
            padding: 0;
        }
        
        .math-display {
            font-family: "Times New Roman", Times, serif;
            font-size: 11pt;
            font-style: italic;
            user-select: text;
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
            title = assignment.get('title', 'Assignment')
            description = assignment.get('description', '')
            questions = assignment.get('questions', [])
            total_points = assignment.get('total_points', 0)
            
            # Generate HTML content
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>{title}</title>
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
            
            pdf_buffer = io.BytesIO()
            html_doc.write_pdf(pdf_buffer, stylesheets=[css_doc])
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