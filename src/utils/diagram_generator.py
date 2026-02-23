"""
Diagram Generation Service for AI Assignments

This module provides multi-method diagram generation capabilities:
1. Code-based rendering (matplotlib, schemdraw, networkx)
2. AI image generation (DALL-E 3)
3. SVG markup rendering

Supports diagrams for: data structures, algorithms, circuits, physics diagrams,
mathematical plots, neural networks, and more.
"""

import io
import os
import re
import uuid
import boto3
import asyncio
import subprocess
import tempfile
from typing import Dict, List, Any, Optional, Tuple
from openai import OpenAI
from controllers.config import logger
import requests
from PIL import Image


class DiagramGenerator:
    """Multi-method diagram generation and S3 upload service"""

    def __init__(self):
        """Initialize diagram generator with OpenAI and S3 clients"""
        self.client = OpenAI()
        self.s3_client = boto3.client("s3")
        self.bucket_name = os.environ.get("AWS_S3_BUCKET")

        # Security: Allowed imports for code-based rendering
        self.ALLOWED_IMPORTS = {
            "matplotlib",
            "matplotlib.pyplot",
            "matplotlib.patches",
            "numpy",
            "np",
            "schemdraw",
            "schemdraw.elements",
            "schemdraw.logic",
            "networkx",
            "nx",
            "graphviz",
            "math",
        }

        # Dangerous patterns to strip from code
        self.DANGEROUS_PATTERNS = [
            r"\bos\.",
            r"\bsubprocess\.",
            r"\bopen\(",
            r"\bexec\(",
            r"\beval\(",
            r"\b__import__\(",
            r"\bcompile\(",
            r"\bglobals\(",
            r"\blocals\(",
            r"\bsetattr\(",
            r"\bdelattr\(",
        ]

    def _sanitize_code(self, code: str) -> str:
        """
        Sanitize Python code to remove dangerous patterns.

        Args:
            code: Python code to sanitize

        Returns:
            Sanitized code

        Raises:
            ValueError: If dangerous patterns are detected
        """
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, code):
                raise ValueError(f"Dangerous pattern detected: {pattern}")

        return code

    def _validate_imports(self, code: str) -> bool:
        """
        Validate that code only imports allowed libraries.

        Args:
            code: Python code to validate

        Returns:
            True if all imports are allowed

        Raises:
            ValueError: If disallowed imports are found
        """
        import_pattern = r"^(?:from|import)\s+([\w.]+)"
        for line in code.split("\n"):
            match = re.match(import_pattern, line.strip())
            if match:
                module = match.group(1).split(".")[0]
                if module not in self.ALLOWED_IMPORTS:
                    raise ValueError(f"Disallowed import: {module}")

        return True

    async def render_matplotlib(self, code: str) -> bytes:
        """
        Render diagram using matplotlib code execution.

        Args:
            code: Python code using matplotlib

        Returns:
            PNG image bytes

        Raises:
            Exception: If rendering fails
        """
        try:
            logger.info("Rendering matplotlib diagram...")

            # Sanitize and validate code
            code = self._sanitize_code(code)
            self._validate_imports(code)

            # Create temporary file for output
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
                output_path = tmp_file.name

            # ── Force HD quality: override DPI and enforce minimum figsize ──
            import re

            # 1. Inject minimum figsize + large fonts BEFORE figure creation
            #    This ensures all diagrams are at least 8×5 inches and text is readable
            hd_preamble = (
                "import matplotlib\n"
                "matplotlib.use('Agg')\n"
                "import matplotlib.pyplot as plt\n"
                "# === HD quality overrides ===\n"
                "plt.rcParams.update({\n"
                "    'figure.dpi': 200,\n"
                "    'savefig.dpi': 200,\n"
                "    'font.size': 13,\n"
                "    'axes.titlesize': 15,\n"
                "    'axes.labelsize': 13,\n"
                "    'xtick.labelsize': 11,\n"
                "    'ytick.labelsize': 11,\n"
                "    'legend.fontsize': 11,\n"
                "    'lines.linewidth': 1.8,\n"
                "})\n"
            )
            # Remove duplicate matplotlib imports/backend settings from Claude's code
            code = re.sub(r"import matplotlib\s*\n", "", code)
            code = re.sub(r"matplotlib\.use\(['\"]Agg['\"]\)\s*\n", "", code)
            code = hd_preamble + code

            # 2. Replace savefig filename AND force dpi=200
            #    Match full plt.savefig(...) call and rewrite with our path + dpi=200
            savefig_full_pattern = r"plt\.savefig\([^)]*\)"
            # Use forward slashes so the path is safe inside a Python string literal
            # on all platforms (Windows accepts forward slashes in file paths).
            safe_output_path = output_path.replace("\\", "/")
            hd_savefig = f"plt.savefig('{safe_output_path}', dpi=200, bbox_inches='tight', facecolor='white')"

            if re.search(savefig_full_pattern, code):
                # Replace ALL existing plt.savefig() calls with our HD version
                # Use a lambda replacement to prevent the replacement string from being
                # interpreted as a regex template (e.g. \U, \n backreferences).
                code_with_output = re.sub(
                    savefig_full_pattern, lambda m: hd_savefig, code
                )
            else:
                # Add plt.savefig() if not present
                code_with_output = (
                    code
                    + f"\nplt.savefig('{safe_output_path}', dpi=200, bbox_inches='tight', facecolor='white')"
                )

            # Write code to temporary Python file
            # Always write as UTF-8 and declare encoding so non-ASCII chars (e.g. °, μ, α)
            # in AI-generated code don't cause SyntaxError on Windows (PEP 263).
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as code_file:
                code_file.write("# -*- coding: utf-8 -*-\n" + code_with_output)
                code_path = code_file.name

            try:
                # Execute code in subprocess with timeout and memory limit
                # Use sys.executable to ensure we use the same Python environment
                import sys

                result = subprocess.run(
                    [sys.executable, code_path],
                    capture_output=True,
                    text=True,
                    timeout=30,  # 30 second timeout (complex HD diagrams need more time)
                    env={
                        **os.environ,
                        "MPLBACKEND": "Agg",
                    },  # Use non-interactive backend
                )

                if result.returncode != 0:
                    logger.error(f"Code execution failed: {result.stderr}")
                    raise Exception(f"Matplotlib rendering failed: {result.stderr}")

                # Read generated image
                with open(output_path, "rb") as img_file:
                    image_bytes = img_file.read()

                logger.info("Matplotlib diagram rendered successfully")
                return image_bytes

            finally:
                # Cleanup temporary files
                try:
                    os.unlink(code_path)
                    os.unlink(output_path)
                except:
                    pass

        except subprocess.TimeoutExpired:
            logger.error("Matplotlib rendering timed out")
            raise Exception("Diagram rendering timed out (>10s)")
        except Exception as e:
            logger.error(f"Error rendering matplotlib diagram: {str(e)}")
            raise

    def _sanitize_schemdraw_code(self, code: str) -> str:
        """
        Fix common schemdraw code mistakes before execution.

        Handles:
        - .at(pos, ofst=...) → .at(pos)  (ofst kwarg doesn't exist)
        - anchor + (dx, dy) → Point(anchor) + Point((dx, dy))
        - Missing 'from schemdraw.util import Point' when Point() is used
        """
        import re

        original = code

        # 1. Fix .at(pos, ofst=(...)) → .at(pos)
        #    The 'ofst' kwarg does not exist in schemdraw 0.19
        code = re.sub(r"\.at\(([^,)]+),\s*ofst\s*=\s*\([^)]*\)\)", r".at(\1)", code)

        # 2. Fix anchor + (dx, dy) tuple arithmetic → Point(anchor) + Point((dx, dy))
        #    Matches patterns like: pmos.gate + (-1.5, 0) or nmos.drain + (0, 1.0)
        code = re.sub(
            r"(\w+\.\w+)\s*\+\s*\(([^)]+)\)", r"Point(\1) + Point((\2))", code
        )
        # Also fix anchor - (dx, dy) patterns
        code = re.sub(r"(\w+\.\w+)\s*-\s*\(([^)]+)\)", r"Point(\1) - Point((\2))", code)

        # 3. If we introduced Point() calls, ensure the import exists
        if "Point(" in code and "from schemdraw.util import Point" not in code:
            # Insert after the schemdraw import
            if "import schemdraw" in code:
                code = code.replace(
                    "import schemdraw\n",
                    "import schemdraw\nfrom schemdraw.util import Point\n",
                    1,
                )
                # Also handle: import schemdraw.elements as elm
                if "from schemdraw.util import Point" not in code:
                    code = code.replace(
                        "import schemdraw.elements as elm\n",
                        "import schemdraw.elements as elm\nfrom schemdraw.util import Point\n",
                        1,
                    )
            else:
                code = "from schemdraw.util import Point\n" + code

        if code != original:
            logger.info("Sanitized schemdraw code (fixed common API mistakes)")

        return code

    async def render_schemdraw(self, code: str) -> bytes:
        """
        Render circuit diagram using schemdraw.

        Args:
            code: Python code using schemdraw

        Returns:
            PNG image bytes
        """
        try:
            logger.info("Rendering schemdraw circuit diagram...")

            import re

            # --- Preprocessing: fix common schemdraw issues ---

            # 1. Ensure matplotlib uses non-interactive backend (inject at top of code)
            backend_line = "import matplotlib\nmatplotlib.use('Agg')\n"
            if "matplotlib.use" not in code:
                code = backend_line + code

            # 2. Ensure 'show=False' in Drawing() constructor to prevent interactive display
            #    Replace Drawing() or Drawing(show=True) with Drawing(show=False)
            code = re.sub(
                r"schemdraw\.Drawing\(\)", "schemdraw.Drawing(show=False)", code
            )
            code = re.sub(
                r"schemdraw\.Drawing\(show\s*=\s*True\)",
                "schemdraw.Drawing(show=False)",
                code,
            )
            # Handle 'with schemdraw.Drawing() as d:' pattern
            code = re.sub(r"(with\s+schemdraw\.Drawing\()\)", r"\1show=False)", code)

            # 3. Remove any plt.show() or d.show() calls that cause non-interactive errors
            code = re.sub(
                r"\bplt\.show\(\)", "# plt.show() removed for non-interactive", code
            )

            # 3b. Sanitize common schemdraw code mistakes
            code = self._sanitize_schemdraw_code(code)

            # 4. Handle save path replacement:
            #    Schemdraw code uses d.save('output.png') not plt.savefig()
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
                output_path = tmp_file.name

            # Replace d.save('...') patterns
            dsave_pattern = r"d\.save\(['\"].*?['\"]"
            dsave_replacement = f"d.save('{output_path}'"

            # Also check for drawing.save() pattern
            drawsave_pattern = r"drawing\.save\(['\"].*?['\"]"

            plt_savefig_pattern = r"plt\.savefig\(['\"].*?['\"]"
            plt_replacement = f"plt.savefig('{output_path}'"

            if re.search(dsave_pattern, code):
                code_with_output = re.sub(dsave_pattern, dsave_replacement, code)
            elif re.search(drawsave_pattern, code):
                code_with_output = re.sub(
                    drawsave_pattern, f"drawing.save('{output_path}'", code
                )
            elif re.search(plt_savefig_pattern, code):
                code_with_output = re.sub(plt_savefig_pattern, plt_replacement, code)
            else:
                # No save found - add d.save() at the end
                # Also ensure matplotlib.pyplot is imported for fallback
                if "import matplotlib.pyplot" not in code:
                    code = "import matplotlib.pyplot as plt\n" + code
                code_with_output = (
                    code
                    + f"\nplt.savefig('{output_path}', dpi=200, bbox_inches='tight')"
                )

            # 5. Write code to temporary Python file and execute
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as code_file:
                code_file.write(code_with_output)
                code_path = code_file.name

            try:
                import sys

                result = subprocess.run(
                    [sys.executable, code_path],
                    capture_output=True,
                    text=True,
                    timeout=15,  # Slightly longer timeout for schemdraw
                    env={**os.environ, "MPLBACKEND": "Agg"},
                )

                if result.returncode != 0:
                    logger.error(f"Schemdraw code execution failed: {result.stderr}")
                    raise Exception(f"Schemdraw rendering failed: {result.stderr}")

                # Read generated image
                if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                    raise Exception("Schemdraw rendering produced no output image")

                with open(output_path, "rb") as img_file:
                    image_bytes = img_file.read()

                logger.info("Schemdraw diagram rendered successfully")
                return image_bytes

            finally:
                try:
                    os.unlink(code_path)
                    os.unlink(output_path)
                except:
                    pass

        except Exception as e:
            logger.error(f"Error rendering schemdraw diagram: {str(e)}")
            raise

    async def render_networkx(self, code: str) -> bytes:
        """
        Render graph/tree using networkx + matplotlib.

        Args:
            code: Python code using networkx and matplotlib

        Returns:
            PNG image bytes
        """
        try:
            logger.info("Rendering networkx graph diagram...")

            # NetworkX uses matplotlib for drawing, so same process
            return await self.render_matplotlib(code)

        except Exception as e:
            logger.error(f"Error rendering networkx diagram: {str(e)}")
            raise

    async def render_ai_image(self, prompt: str, model: str = "dall-e-3") -> bytes:
        """
        Generate diagram using AI image generation (DALL-E 3).

        Args:
            prompt: Detailed prompt for image generation
            model: AI model to use (default: dall-e-3)

        Returns:
            PNG image bytes
        """
        try:
            logger.info(f"Generating AI image with {model}...")
            logger.info(f"Prompt: {prompt}")

            # Generate image using DALL-E 3
            response = self.client.images.generate(
                model=model,
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )

            # Download generated image
            image_url = response.data[0].url
            img_response = requests.get(image_url)
            img_response.raise_for_status()

            # Resize if needed (to keep file size reasonable)
            image = Image.open(io.BytesIO(img_response.content))

            # Convert to RGB if necessary
            if image.mode != "RGB":
                image = image.convert("RGB")

            # Resize to max 1200px width while maintaining aspect ratio
            max_width = 1200
            if image.width > max_width:
                ratio = max_width / image.width
                new_height = int(image.height * ratio)
                image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)

            # Save to bytes
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format="PNG", optimize=True)
            image_bytes = img_byte_arr.getvalue()

            logger.info("AI image generated successfully")
            return image_bytes

        except Exception as e:
            logger.error(f"Error generating AI image: {str(e)}")
            raise

    async def render_svg(self, svg_markup: str) -> bytes:
        """
        Render SVG markup to PNG.

        Args:
            svg_markup: SVG XML markup

        Returns:
            PNG image bytes
        """
        try:
            logger.info("Rendering SVG diagram...")

            # Try to import cairosvg
            try:
                import cairosvg
            except ImportError:
                logger.error("cairosvg not installed, cannot render SVG")
                raise Exception("SVG rendering not available (cairosvg not installed)")

            # Convert SVG to PNG
            png_bytes = cairosvg.svg2png(bytestring=svg_markup.encode("utf-8"))

            logger.info("SVG diagram rendered successfully")
            return png_bytes

        except Exception as e:
            logger.error(f"Error rendering SVG diagram: {str(e)}")
            raise

    async def upload_to_s3(
        self, image_bytes: bytes, assignment_id: str, question_index: int
    ) -> Dict[str, Any]:
        """
        Upload diagram image to S3.

        Args:
            image_bytes: PNG image data
            assignment_id: Assignment ID for S3 path
            question_index: Question index for filename

        Returns:
            Dictionary with S3 metadata: {file_id, filename, s3_key, s3_url, content_type, size}
        """
        try:
            logger.info(f"Uploading diagram to S3 for question {question_index}...")

            # Generate unique file ID
            file_id = str(uuid.uuid4())
            filename = f"diagram_q{question_index}.png"
            s3_key = f"assignments/{assignment_id}/diagrams/{file_id}.png"

            # Upload to S3 with retry
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.s3_client.put_object(
                        Bucket=self.bucket_name,
                        Key=s3_key,
                        Body=image_bytes,
                        ContentType="image/png",
                        CacheControl="max-age=31536000",  # 1 year cache
                    )
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    logger.warning(
                        f"S3 upload attempt {attempt + 1} failed, retrying..."
                    )
                    await asyncio.sleep(2**attempt)  # Exponential backoff

            # Generate presigned URL
            s3_url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": s3_key},
                ExpiresIn=31536000,  # 1 year
            )

            logger.info(f"Diagram uploaded successfully to {s3_key}")

            return {
                "file_id": file_id,
                "filename": filename,
                "s3_key": s3_key,
                "s3_url": s3_url,
                "content_type": "image/png",
                "size": len(image_bytes),
            }

        except Exception as e:
            logger.error(f"Error uploading diagram to S3: {str(e)}")
            raise

    async def _render_diagram(
        self, diagram_spec: Dict[str, Any], fallback_chain: bool = True
    ) -> Optional[bytes]:
        """
        Render a single diagram based on its specification.

        Args:
            diagram_spec: Diagram specification with type and rendering data
            fallback_chain: Whether to fall back to other methods on failure

        Returns:
            PNG image bytes or None if all methods fail
        """
        diagram_type = diagram_spec.get("diagram_type", "")

        try:
            # Route to appropriate renderer
            if diagram_type in ["matplotlib", "matplotlib_networkx"]:
                code = diagram_spec.get("code", "")
                if not code:
                    raise ValueError("No code provided for matplotlib diagram")
                return await self.render_matplotlib(code)

            elif diagram_type == "schemdraw":
                code = diagram_spec.get("code", "")
                if not code:
                    raise ValueError("No code provided for schemdraw diagram")
                return await self.render_schemdraw(code)

            elif diagram_type == "networkx":
                code = diagram_spec.get("code", "")
                if not code:
                    raise ValueError("No code provided for networkx diagram")
                return await self.render_networkx(code)

            elif diagram_type == "ai_image":
                prompt = diagram_spec.get("ai_prompt", "")
                if not prompt:
                    raise ValueError("No prompt provided for AI image generation")
                return await self.render_ai_image(prompt)

            elif diagram_type == "svg":
                svg_markup = diagram_spec.get("svg_markup", "")
                if not svg_markup:
                    raise ValueError("No SVG markup provided")
                return await self.render_svg(svg_markup)

            else:
                logger.warning(f"Unknown diagram type: {diagram_type}")
                return None

        except Exception as e:
            logger.error(f"Primary rendering method ({diagram_type}) failed: {str(e)}")

            if not fallback_chain:
                return None

            # Fallback chain: try AI generation if code-based failed
            if diagram_type not in ["ai_image", "svg"]:
                try:
                    logger.info("Falling back to AI image generation...")
                    description = diagram_spec.get("description", "")
                    if description:
                        # Create a detailed prompt from the description
                        ai_prompt = f"Create a clear, educational diagram showing: {description}. Use a clean, technical style suitable for an engineering textbook."
                        return await self.render_ai_image(ai_prompt)
                except Exception as fallback_error:
                    logger.error(
                        f"Fallback AI generation also failed: {str(fallback_error)}"
                    )

            return None

    async def generate_diagrams_batch(
        self, diagram_specs: List[Tuple[int, Dict[str, Any]]], assignment_id: str
    ) -> List[Tuple[int, Optional[Dict[str, Any]]]]:
        """
        Generate multiple diagrams in parallel with concurrency limit.

        Args:
            diagram_specs: List of (question_index, diagram_spec) tuples
            assignment_id: Assignment ID for S3 upload

        Returns:
            List of (question_index, diagram_data) tuples
            diagram_data is None if generation failed
        """
        try:
            logger.info(
                f"Starting batch diagram generation for {len(diagram_specs)} diagrams"
            )

            async def process_diagram(
                question_index: int, spec: Dict[str, Any]
            ) -> Tuple[int, Optional[Dict[str, Any]]]:
                """Process a single diagram: render + upload"""
                try:
                    # Render diagram
                    image_bytes = await self._render_diagram(spec, fallback_chain=True)

                    if image_bytes is None:
                        logger.warning(
                            f"Failed to generate diagram for question {question_index}"
                        )
                        return (question_index, None)

                    # Upload to S3
                    diagram_data = await self.upload_to_s3(
                        image_bytes, assignment_id, question_index
                    )
                    return (question_index, diagram_data)

                except Exception as e:
                    logger.error(
                        f"Error processing diagram for question {question_index}: {str(e)}"
                    )
                    return (question_index, None)

            # Process diagrams in parallel with concurrency limit
            semaphore = asyncio.Semaphore(5)  # Max 5 concurrent renders

            async def bounded_process(
                q_idx: int, spec: Dict[str, Any]
            ) -> Tuple[int, Optional[Dict[str, Any]]]:
                async with semaphore:
                    return await process_diagram(q_idx, spec)

            # Create tasks for all diagrams
            tasks = [bounded_process(idx, spec) for idx, spec in diagram_specs]

            # Wait for all to complete
            results = await asyncio.gather(*tasks, return_exceptions=False)

            # Count successes
            success_count = sum(1 for _, data in results if data is not None)
            logger.info(
                f"Batch diagram generation complete: {success_count}/{len(diagram_specs)} successful"
            )

            return results

        except Exception as e:
            logger.error(f"Error in batch diagram generation: {str(e)}")
            # Return empty results rather than failing entire assignment
            return [(idx, None) for idx, _ in diagram_specs]
