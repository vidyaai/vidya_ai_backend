"""
Google AI Diagram Generator - uses Gemini native image generation (Nano Banana Pro).

Unlike Imagen 3 (a pure diffusion model), Gemini's native image generation
combines deep language understanding with image synthesis, producing accurate
technical/engineering diagrams with proper labels, symbols, and layouts.

Models:
  - gemini-2.5-flash-image  (Nano Banana) - fast, efficient
  - gemini-3-pro-image-preview (Nano Banana Pro) - highest quality, thinking, best text rendering

Capabilities:
  - generate_diagram(): Text-to-image - generate a new diagram from a prompt
  - fix_diagram():      Image-edit  - send back an existing image + correction
                        instructions to fix only text/label/unit errors

Pipeline:
    Description -> Gemini generate_content (with IMAGE modality) -> PNG bytes -> S3 upload
"""

import os
import json
import base64
from typing import Optional, Dict, Any, List
from controllers.config import logger


class GoogleDiagramGenerator:
    """Generate diagrams using Gemini native image generation.

    Supports two models selectable via the `diagram_model` constructor arg:
      - "flash"  → gemini-2.5-flash-image   via Vertex AI (service account auth)
      - "pro"    → gemini-3-pro-image-preview via Google AI Studio (API key auth)
    """

    MODELS = {
        "flash": "gemini-2.5-flash-image",
        "pro": "gemini-3-pro-image-preview",
    }

    def __init__(self, diagram_model: str = "flash"):
        """
        Args:
            diagram_model: "flash" for gemini-2.5-flash-image (Vertex AI),
                           "pro"   for gemini-3-pro-image-preview (Google AI Studio API key)
        """
        self.diagram_model = diagram_model.lower().strip()
        self.MODEL_NAME = self.MODELS.get(self.diagram_model, self.MODELS["flash"])

        self.project_id = None
        self.location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        self._client = None
        self._initialized = False
        self._credentials_path = None

        # Find the service account credentials file (needed for flash/Vertex AI)
        backend_root = os.path.join(os.path.dirname(__file__), "..", "..")
        for f in os.listdir(backend_root):
            if f.startswith("vidyaai-forms-integrations") and f.endswith(".json"):
                self._credentials_path = os.path.join(backend_root, f)
                break

        if self.diagram_model == "flash" and not self._credentials_path:
            logger.warning(
                "No vidyaai-forms-integrations-*.json found — Gemini flash image generation disabled"
            )

    def _ensure_initialized(self):
        """Lazy-initialize the google-genai Client.

        - flash: Vertex AI with service account credentials
        - pro:   Google AI Studio with GEMINI_API_KEY from environment
        """
        if self._initialized:
            return True

        try:
            from google import genai

            if self.diagram_model == "pro":
                # Google AI Studio API key auth — no Vertex AI allowlist needed
                api_key = os.getenv("GEMINI_API_KEY")
                if not api_key:
                    logger.error(
                        "GEMINI_API_KEY not set in environment — pro model disabled"
                    )
                    return False
                self._client = genai.Client(api_key=api_key)
                self._initialized = True
                logger.info(
                    f"Gemini image gen initialized: model={self.MODEL_NAME} (Google AI Studio)"
                )
                return True

            else:
                # flash — Vertex AI with service account
                if not self._credentials_path:
                    logger.error("No Google service account credentials file found")
                    return False

                with open(self._credentials_path, "r") as f:
                    creds_data = json.load(f)
                self.project_id = creds_data.get("project_id")

                from google.oauth2 import service_account

                credentials = service_account.Credentials.from_service_account_file(
                    self._credentials_path,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
                self._client = genai.Client(
                    vertexai=True,
                    project=self.project_id,
                    location=self.location,
                    credentials=credentials,
                )
                self._initialized = True
                logger.info(
                    f"Gemini image gen initialized: project={self.project_id}, "
                    f"location={self.location}, model={self.MODEL_NAME}"
                )
                return True

        except Exception as e:
            logger.error(f"Failed to initialize Gemini image gen: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    async def generate_diagram(
        self,
        description: str,
        subject: str = "electrical",
        question_text: str = "",
        style: str = "textbook",
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a diagram using Gemini native image generation.

        Args:
            description: Description of the diagram to generate
            subject: Subject domain (electrical, mechanical, computer, math, civil)
            question_text: Full question text for additional context
            style: Diagram style (textbook, schematic, etc.)

        Returns:
            Dict with 'image_bytes', 'format', 'model' or None on failure
        """
        if not self._ensure_initialized():
            return None

        try:
            from google.genai import types

            prompt = self._build_prompt(description, subject, question_text, style)

            logger.info(f"Generating Gemini diagram: {description[:100]}...")
            logger.debug(f"Gemini image prompt: {prompt}")

            response = self._client.models.generate_content(
                model=self.MODEL_NAME,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio="4:3",
                    ),
                ),
            )

            # Extract image from response parts
            if response and response.candidates:
                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.mime_type.startswith(
                        "image/"
                    ):
                        image_bytes = part.inline_data.data
                        logger.info(f"Gemini generated image: {len(image_bytes)} bytes")
                        return {
                            "image_bytes": image_bytes,
                            "format": "png",
                            "model": self.MODEL_NAME,
                        }

            logger.warning("Gemini response contained no image parts")
            # Log what we got for debugging
            if response and response.candidates:
                for part in response.candidates[0].content.parts:
                    if part.text:
                        logger.debug(f"Gemini text response: {part.text[:200]}")
            return None

        except Exception as e:
            logger.error(f"Gemini image generation failed: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _build_prompt(
        self,
        description: str,
        subject: str,
        question_text: str,
        style: str,
    ) -> str:
        """Build a detailed prompt for Gemini native image generation."""
        domain_context = {
            "electrical": (
                "professional electrical/electronics engineering diagram. "
                "Use standard IEEE circuit symbols. For logic gates use standard shapes: "
                "D-shaped AND, curved OR, triangle NOT with bubble. "
                "For CMOS circuits show PMOS on top connected to VDD, NMOS on bottom to GND."
            ),
            "mechanical": (
                "professional mechanical engineering technical drawing. "
                "For free body diagrams show all forces as labeled arrows. "
                "Use standard hatching for fixed supports. "
                "For beams show supports (pin, roller, fixed) with standard symbols. "
                "For P-V and T-S diagrams label axes and show process paths with arrows."
            ),
            "computer": (
                "professional computer science diagram. "
                "For graphs and trees use circles for nodes and arrows for edges. "
                "For FSMs use circles for states, arrows with labels for transitions, "
                "double circle for accept states. "
                "Use hierarchical layout for trees with root at top."
            ),
            "math": (
                "professional mathematical figure. "
                "Label axes properly, show grid where helpful, mark key points. "
                "Use proper mathematical notation in labels. "
                "For geometric figures show angles, lengths, and constructions clearly."
            ),
            "civil": (
                "professional civil/structural engineering diagram. "
                "Show supports, loads, and reactions with standard symbols. "
                "Use standard symbols for pin, roller, and fixed supports. "
                "Show dimensions and cross-section details clearly."
            ),
        }

        context = domain_context.get(subject, "professional technical STEM diagram")

        prompt = f"""Generate a {context}

DIAGRAM SPECIFICATION:
{description}

STYLE REQUIREMENTS:
- Clean BLACK AND WHITE line art on pure WHITE background
- Publication-quality, textbook standard
- All labels must be CLEARLY READABLE with proper font size
- Use standard engineering/academic symbols and conventions
- Crisp, well-defined lines with professional spacing
- No decorative elements — purely technical
- Compact layout suitable for a printed assignment page

CRITICAL RULES:
- DO NOT include any computed output values or answers
- For circuit inputs, show only variable names (A, B, C) — NEVER specific values like A=1, B=0
- DO NOT include truth tables or boolean expressions in the diagram
- DO NOT include any text that reveals the solution
- This is for a student exam — the answer must NOT be visible

TEXT & LABEL ACCURACY (EXTREMELY IMPORTANT):
- Every dimension label MUST be spelled out EXACTLY as specified (e.g. "10 mm" not "10m", "1 mm" not "1im")
- Units must be correct and complete — write "mm", "W/m²K", "°C" with proper symbols
- Do NOT abbreviate, truncate, or garble any text labels
- All text must be clearly legible at print size
- Double-check every number and unit before rendering
- If a dimension is "0.5 mm" write exactly "0.5 mm" -- never "0.5m" or ".5mm"

DIMENSION PLACEMENT (CRITICAL):
- Each edge/side of a component must have AT MOST ONE dimension label
- NEVER place two different dimension values on the same edge or side
- Horizontal dimensions (width) go on horizontal edges (top or bottom)
- Vertical dimensions (height/thickness) go on vertical edges (left or right)
- If a component is "W x H" (e.g. 10 mm x 1 mm), the W labels go horizontally and the H labels go vertically — do NOT mix them
- For 3D objects described as "L x W x H", map them clearly to the 2D view so each axis has only one value"""

        # Add question context
        if question_text:
            prompt += f"\n\nQUESTION CONTEXT (for understanding the diagram purpose only):\n{question_text}"

        return prompt

    async def fix_diagram(
        self,
        image_bytes: bytes,
        issues: List[str],
        reason: str,
        original_description: str,
        question_text: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        Fix an existing diagram by sending it back to Gemini with correction instructions.

        Instead of regenerating from scratch, this sends the existing image along
        with specific issues to fix (e.g., wrong labels, units, spelling errors).
        The model preserves the overall layout and structure while correcting text.

        Args:
            image_bytes: The existing diagram PNG bytes to fix
            issues: List of specific issues from the reviewer
            reason: The reviewer's reason for failure
            original_description: The original generation description
            question_text: The question text for context

        Returns:
            Dict with 'image_bytes', 'format', 'model' or None on failure
        """
        if not self._ensure_initialized():
            return None

        try:
            from google.genai import types
            from PIL import Image as PILImage
            import io

            # Build the fix prompt — use issues if available, otherwise use the reason
            if issues:
                issues_text = "\n".join(f"  - {issue}" for issue in issues)
            else:
                issues_text = f"  - {reason}"

            fix_prompt = f"""You MUST output a corrected version of the attached diagram as an IMAGE.

Fix the following issues in this technical engineering diagram.
DO NOT change the overall layout, structure, or composition.
ONLY fix the text, labels, dimensions, and units as specified below.

ISSUES TO FIX:
{issues_text}

REVIEWER'S NOTE: {reason}

ORIGINAL SPECIFICATION (for reference):
{original_description}

CORRECTION INSTRUCTIONS:
- Fix ONLY the specific text/label/unit errors listed above
- Keep the exact same diagram layout, structure, and style
- Ensure all dimension labels are EXACTLY correct (e.g., "10 mm", "0.5 mm", "1 mm")
- Ensure all units are properly formatted (e.g., "W/m2K", "C", "mm")
- All text must be clearly legible
- Maintain clean black and white line art style
- Do NOT add any new elements or change the structure
- Output the corrected diagram as an image"""

            if question_text:
                fix_prompt += f"\n\nQUESTION CONTEXT (for verifying correctness):\n{question_text}"

            # Load the image for sending to the model
            pil_image = PILImage.open(io.BytesIO(image_bytes))

            logger.info(
                f"Sending diagram for fix (preserving layout, correcting labels)..."
            )
            logger.debug(f"Fix issues: {issues_text}")

            response = self._client.models.generate_content(
                model=self.MODEL_NAME,
                contents=[fix_prompt, pil_image],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio="4:3",
                    ),
                ),
            )

            # Extract fixed image from response
            if response and response.candidates:
                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.mime_type.startswith(
                        "image/"
                    ):
                        fixed_bytes = part.inline_data.data
                        logger.info(
                            f"Gemini fixed image: {len(fixed_bytes)} bytes "
                            f"(original: {len(image_bytes)} bytes)"
                        )
                        return {
                            "image_bytes": fixed_bytes,
                            "format": "png",
                            "model": self.MODEL_NAME,
                        }

            logger.warning("Gemini fix response contained no image parts")
            # Log what we got for debugging
            if response and response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        logger.debug(f"Gemini fix text response: {part.text[:300]}")
            return None

        except Exception as e:
            logger.error(f"Gemini diagram fix failed: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

        # Add question context
        if question_text:
            prompt += f"\n\nQUESTION CONTEXT (for understanding the diagram purpose only):\n{question_text}"

        return prompt
