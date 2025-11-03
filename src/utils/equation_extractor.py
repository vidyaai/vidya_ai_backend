"""
Utility module for extracting mathematical equations from various document formats
and converting them to LaTeX format for consistent storage and rendering.
"""

import re
import xml.etree.ElementTree as ET
from typing import List, Tuple, Optional
from io import BytesIO
from controllers.config import logger

try:
    from omml2mathml import create_omml2mathml_converter

    OMML_TO_MATHML_AVAILABLE = True
except ImportError:
    OMML_TO_MATHML_AVAILABLE = False
    logger.warning(
        "omml2mathml not available. DOCX equation extraction will be limited."
    )

try:
    from bs4 import BeautifulSoup

    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    logger.warning(
        "beautifulsoup4 not available. HTML equation extraction will be limited."
    )


class EquationExtractor:
    """Extract and convert mathematical equations from various document formats to LaTeX"""

    # LaTeX equation patterns
    LATEX_INLINE_PATTERN = r"\$([^$]+)\$"
    LATEX_DISPLAY_PATTERN = r"\$\$([^$]+)\$\$"
    LATEX_BRACKET_INLINE = r"\\\(([^\)]+)\\\)"
    LATEX_BRACKET_DISPLAY = r"\\\[([^\]]+)\\\]"
    LATEX_ENVIRONMENT_PATTERN = r"\\begin\{(equation|eqnarray|align|multline|gather)\*?\}(.*?)\\end\{(equation|eqnarray|align|multline|gather)\*?\}"

    def __init__(self):
        self.omml_converter = None
        if OMML_TO_MATHML_AVAILABLE:
            try:
                self.omml_converter = create_omml2mathml_converter()
            except Exception as e:
                logger.warning(f"Failed to initialize OMML converter: {e}")

    def extract_from_docx(self, content: bytes) -> List[Tuple[str, str]]:
        """
        Extract OMML equations from DOCX file and convert to LaTeX.

        Args:
            content: Raw DOCX file content (bytes)

        Returns:
            List of tuples (equation_latex, equation_type) where equation_type is 'inline' or 'display'
        """
        equations = []
        if not OMML_TO_MATHML_AVAILABLE or not self.omml_converter:
            logger.warning(
                "OMML to MathML conversion not available. Skipping DOCX equation extraction."
            )
            return equations

        try:
            import zipfile
            from lxml import etree

            # DOCX is a ZIP archive
            zip_file = zipfile.ZipFile(BytesIO(content))

            # Find main document XML
            if "word/document.xml" not in zip_file.namelist():
                return equations

            doc_xml = zip_file.read("word/document.xml")
            root = ET.fromstring(doc_xml)

            # Define namespaces
            namespaces = {
                "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
                "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
            }

            # Find all OMML equations
            omath_elements = root.findall(".//m:oMath", namespaces)

            for omath in omath_elements:
                try:
                    # Convert OMML XML to string
                    omml_str = ET.tostring(omath, encoding="unicode")

                    # Convert OMML to MathML
                    mathml = self.omml_converter.convert(omml_str)

                    # Convert MathML to LaTeX (simplified approach)
                    latex = self._mathml_to_latex(mathml)

                    if latex:
                        # Determine if inline or display based on context
                        equation_type = "inline"  # Default to inline
                        equations.append((latex, equation_type))
                        logger.debug(f"Extracted DOCX equation: {latex[:50]}...")
                except Exception as e:
                    logger.warning(f"Error converting OMML equation: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error extracting equations from DOCX: {e}")

        return equations

    def extract_from_text(self, content: str) -> List[Tuple[str, str]]:
        """
        Detect LaTeX equation patterns in plain text.

        Args:
            content: Text content

        Returns:
            List of tuples (equation_latex, equation_type)
        """
        equations = []

        # Find all LaTeX patterns
        patterns = [
            (self.LATEX_DISPLAY_PATTERN, "display"),
            (self.LATEX_BRACKET_DISPLAY, "display"),
            (self.LATEX_ENVIRONMENT_PATTERN, "display"),
            (self.LATEX_INLINE_PATTERN, "inline"),
            (self.LATEX_BRACKET_INLINE, "inline"),
        ]

        for pattern, eq_type in patterns:
            matches = re.finditer(pattern, content, re.DOTALL)
            for match in matches:
                equation = match.group(1) if match.lastindex >= 1 else match.group(0)
                # Clean up the equation
                equation = equation.strip()
                if equation:
                    equations.append((equation, eq_type))

        return equations

    def extract_from_html(self, content: str) -> List[Tuple[str, str]]:
        """
        Extract MathML or LaTeX equations from HTML.

        Args:
            content: HTML content

        Returns:
            List of tuples (equation_latex, equation_type)
        """
        equations = []

        try:
            if BS4_AVAILABLE:
                soup = BeautifulSoup(content, "html.parser")

                # Extract MathML equations
                math_elements = soup.find_all("math")
                for math_elem in math_elements:
                    mathml_str = str(math_elem)
                    latex = self._mathml_to_latex(mathml_str)
                    if latex:
                        equations.append((latex, "display"))

                # Extract LaTeX from script tags (MathJax/KaTeX)
                script_tags = soup.find_all(
                    "script",
                    type=lambda x: x and ("math" in x.lower() or "latex" in x.lower()),
                )
                for script in script_tags:
                    script_content = script.string or ""
                    # Look for LaTeX patterns in script content
                    text_eqs = self.extract_from_text(script_content)
                    equations.extend(text_eqs)

                # Extract LaTeX from data attributes or comments
                # Look for LaTeX in HTML comments
                comments = soup.find_all(
                    string=lambda text: isinstance(text, str) and "$" in text
                )
                for comment in comments:
                    text_eqs = self.extract_from_text(comment)
                    equations.extend(text_eqs)
            else:
                # Fallback: use regex on raw HTML
                # Look for <math> tags
                math_pattern = r"<math[^>]*>(.*?)</math>"
                matches = re.finditer(math_pattern, content, re.DOTALL)
                for match in matches:
                    mathml_str = match.group(0)
                    latex = self._mathml_to_latex(mathml_str)
                    if latex:
                        equations.append((latex, "display"))

                # Extract LaTeX patterns from HTML text
                text_eqs = self.extract_from_text(content)
                equations.extend(text_eqs)

        except Exception as e:
            logger.error(f"Error extracting equations from HTML: {e}")
            # Fallback to text extraction
            equations.extend(self.extract_from_text(content))

        return equations

    def extract_from_markdown(self, content: str) -> List[Tuple[str, str]]:
        """
        Extract LaTeX equations from Markdown content.

        Args:
            content: Markdown content

        Returns:
            List of tuples (equation_latex, equation_type)
        """
        # Markdown uses same LaTeX patterns as plain text
        return self.extract_from_text(content)

    def normalize_equation(self, equation: str, source_format: str) -> str:
        """
        Normalize equation to LaTeX format.

        Args:
            equation: Equation string in various formats
            source_format: Source format ('omml', 'mathml', 'latex', 'plain')

        Returns:
            Normalized LaTeX equation string
        """
        if source_format == "latex":
            return equation.strip()
        elif source_format == "mathml":
            return self._mathml_to_latex(equation)
        elif source_format == "omml":
            if self.omml_converter:
                try:
                    mathml = self.omml_converter.convert(equation)
                    return self._mathml_to_latex(mathml)
                except Exception as e:
                    logger.warning(f"Error converting OMML to LaTeX: {e}")
            return equation
        else:
            # Plain text - return as-is (might need AI conversion later)
            return equation.strip()

    def _mathml_to_latex(self, mathml: str) -> Optional[str]:
        """
        Convert MathML to LaTeX (simplified implementation).

        Args:
            mathml: MathML string

        Returns:
            LaTeX string or None if conversion fails
        """
        try:
            # This is a simplified conversion - for production, consider using
            # a dedicated library like latex2mathml.converter or similar
            # For now, we'll use a basic pattern-based approach

            if not mathml or not isinstance(mathml, str):
                return None

            # Try to parse MathML and extract basic elements
            # This is a basic implementation - full MathML conversion requires a proper library
            try:
                root = ET.fromstring(mathml)
            except ET.ParseError:
                # Try with namespace
                root = ET.fromstring(
                    mathml.replace(
                        "<math>", '<math xmlns="http://www.w3.org/1998/Math/MathML">'
                    )
                )

            # Basic conversion logic
            latex = self._mathml_element_to_latex(root)
            return latex if latex else None

        except Exception as e:
            logger.debug(f"MathML to LaTeX conversion error: {e}")
            return None

    def _mathml_element_to_latex(self, element: ET.Element) -> str:
        """
        Recursively convert MathML element to LaTeX.

        This is a simplified implementation. For production use, consider
        using a library like latex2mathml.converter or similar.
        """
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag
        text = element.text or ""
        tail = element.tail or ""

        # Basic MathML to LaTeX mappings
        conversions = {
            "math": lambda e: self._mathml_element_to_latex(e[0]) if e else "",
            "mi": lambda e: text,  # Identifier
            "mn": lambda e: text,  # Number
            "mo": lambda e: text,  # Operator
            "mfrac": lambda e: f"\\frac{{{self._mathml_element_to_latex(e[0])}}}{{{self._mathml_element_to_latex(e[1])}}}"
            if len(e) >= 2
            else "",
            "msup": lambda e: f"{{{self._mathml_element_to_latex(e[0])}}}^{{{self._mathml_element_to_latex(e[1])}}}"
            if len(e) >= 2
            else "",
            "msub": lambda e: f"{{{self._mathml_element_to_latex(e[0])}}}_{{{self._mathml_element_to_latex(e[1])}}}"
            if len(e) >= 2
            else "",
            "msubsup": lambda e: f"{{{self._mathml_element_to_latex(e[0])}}}_{{{self._mathml_element_to_latex(e[1])}}}^{{{self._mathml_element_to_latex(e[2])}}}"
            if len(e) >= 3
            else "",
            "mroot": lambda e: f"\\sqrt[{self._mathml_element_to_latex(e[1])}]{{{self._mathml_element_to_latex(e[0])}}}"
            if len(e) >= 2
            else f"\\sqrt{{{self._mathml_element_to_latex(e[0])}}}",
            "msqrt": lambda e: f"\\sqrt{{{self._mathml_element_to_latex(e[0])}}}",
            "mrow": lambda e: "".join(
                [self._mathml_element_to_latex(child) for child in e]
            ),
            "mtable": lambda e: "\\begin{matrix}\n"
            + "\\\\\n".join([self._mathml_element_to_latex(row) for row in e])
            + "\n\\end{matrix}",
            "mtr": lambda e: " & ".join(
                [self._mathml_element_to_latex(cell) for cell in e]
            ),
            "mtd": lambda e: self._mathml_element_to_latex(e[0]) if e else "",
        }

        if tag in conversions:
            return conversions[tag](list(element))
        else:
            # Default: concatenate children
            result = text
            for child in element:
                result += self._mathml_element_to_latex(child)
            result += tail
            return result

    def preserve_equations_in_text(self, text: str, format_type: str = "text") -> str:
        """
        Preserve equations in text by ensuring LaTeX delimiters are present.

        Args:
            text: Text content
            format_type: Format type ('text', 'markdown', 'html')

        Returns:
            Text with preserved equations
        """
        # Extract equations
        equations = []
        if format_type == "html":
            equations = self.extract_from_html(text)
        elif format_type == "markdown":
            equations = self.extract_from_markdown(text)
        else:
            equations = self.extract_from_text(text)

        # If equations are already properly delimited, return as-is
        # Otherwise, ensure they have delimiters
        result = text

        # For now, return text as-is since equations should already be in LaTeX format
        # This method can be enhanced to wrap plain text equations in delimiters if needed
        return result
