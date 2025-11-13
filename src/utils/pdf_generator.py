"""
PDF generation service for assignments with LaTeX-style formatting.
Supports equations, images, and professional document layout.
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
    from weasyprint.css.targets import PageBox
except ImportError:
    print("WeasyPrint not installed. Install with: pip install weasyprint")

try:
    import matplotlib.pyplot as plt
    import matplotlib.mathtext as mathtext
    from matplotlib.backends.backend_agg import FigureCanvasAgg
except ImportError:
    print("Matplotlib not installed. Install with: pip install matplotlib")

from controllers.config import logger


class AssignmentPDFGenerator:
    """Generates professional LaTeX-style PDFs for assignments."""
    
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp()
        
    def render_latex_equation(self, latex_text: str, fontsize: int = 12) -> str:
        """
        Render LaTeX equation to base64 image using matplotlib.
        
        Args:
            latex_text: LaTeX equation string
            fontsize: Font size for the equation
            
        Returns:
            Base64 encoded image data URI
        """
        try:
            # Clean up LaTeX text
            latex_text = latex_text.strip()
            if not latex_text.startswith('$'):
                latex_text = f'${latex_text}$'
            
            # Create figure for equation
            fig, ax = plt.subplots(figsize=(8, 1))
            ax.text(0.5, 0.5, latex_text, transform=ax.transAxes, 
                   fontsize=fontsize, ha='center', va='center',
                   fontfamily='serif')
            
            # Remove axes and make transparent
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis('off')
            fig.patch.set_alpha(0)
            
            # Save to bytes
            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight', 
                       transparent=True, dpi=150, pad_inches=0.1)
            buf.seek(0)
            
            # Convert to base64
            img_base64 = base64.b64encode(buf.read()).decode('utf-8')
            plt.close(fig)
            
            return f"data:image/png;base64,{img_base64}"
            
        except Exception as e:
            logger.error(f"Error rendering LaTeX equation '{latex_text}': {e}")
            return ""
    
    def process_question_text(self, text: str) -> str:
        """
        Process question text to render LaTeX equations as images.
        
        Args:
            text: Question text that may contain LaTeX
            
        Returns:
            HTML text with LaTeX equations rendered as images
        """
        if not text:
            return ""
        
        # Pattern to match LaTeX equations: $equation$ or $$equation$$
        equation_pattern = r'\$\$([^$]+)\$\$|\$([^$]+)\$'
        
        def replace_equation(match):
            latex_text = match.group(1) or match.group(2)
            img_data = self.render_latex_equation(latex_text)
            if img_data:
                return f'<img src="{img_data}" style="vertical-align: middle; margin: 0 4px;" alt="{latex_text}">'
            else:
                return f'<code>{latex_text}</code>'  # Fallback to code styling
        
        # Replace all LaTeX equations
        processed_text = re.sub(equation_pattern, replace_equation, text)
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
                option_text = self.process_question_text(option)
                letter = chr(65 + i)  # A, B, C, D...
                html += f'<div class="option"><strong>{letter}.</strong> {option_text}</div>'
            html += '</div>'
        
        # Add answer space for other question types
        elif question_type in ['short-answer', 'numerical', 'long-answer']:
            lines = 3 if question_type == 'short-answer' else 8
            html += f"""
            <div class="answer-space">
                <p><strong>Answer:</strong></p>
                <div class="answer-lines" style="height: {lines * 1.5}em; border-bottom: 1px solid #ccc; margin: 10px 0;"></div>
            </div>
            """
        
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
            font-family: "Times New Roman", "Liberation Serif", serif;
            font-size: 11pt;
            line-height: 1.4;
            color: #000;
            margin: 0;
            padding: 0;
        }
        
        .document-header {
            text-align: center;
            margin-bottom: 30px;
            border-bottom: 2px solid #333;
            padding-bottom: 15px;
        }
        
        .document-title {
            font-size: 18pt;
            font-weight: bold;
            margin-bottom: 8px;
            string-set: doc-title content();
        }
        
        .document-meta {
            font-size: 10pt;
            color: #666;
            margin-bottom: 15px;
        }
        
        .instructions {
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            padding: 15px;
            margin-bottom: 25px;
            border-radius: 4px;
        }
        
        .instructions h3 {
            margin-top: 0;
            color: #495057;
        }
        
        .question {
            margin-bottom: 25px;
            page-break-inside: avoid;
        }
        
        .question-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            border-bottom: 1px solid #ddd;
            padding-bottom: 8px;
        }
        
        .question-header h3 {
            margin: 0;
            font-size: 14pt;
            color: #333;
        }
        
        .question-meta {
            display: flex;
            gap: 10px;
            align-items: center;
        }
        
        .points, .difficulty, .type {
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 9pt;
            font-weight: bold;
            color: white;
        }
        
        .points {
            background-color: #007bff;
        }
        
        .type {
            background-color: #6c757d;
        }
        
        .question-text {
            margin-bottom: 15px;
            line-height: 1.5;
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
        
        /* Math equation styling */
        .equation {
            text-align: center;
            margin: 10px 0;
        }
        
        /* Code blocks */
        code {
            font-family: "Courier New", monospace;
            background-color: #f4f4f4;
            padding: 2px 4px;
            border-radius: 2px;
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
                    <h3>Instructions</h3>
                    <p>{self.process_question_text(description)}</p>
                    <p><strong>Important:</strong> Show all work for full credit. Write legibly and organize your answers clearly.</p>
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