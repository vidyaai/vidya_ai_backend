import os
from typing import List
from PIL import Image
from controllers.config import logger
from pydantic import BaseModel


class DiagramBBox(BaseModel):
    box_2d: List[float]


def detect_diagram_bbox(page_image: Image.Image, question_text: str) -> List[float]:
    """
    Call Gemini 2.5 Flash to detect a diagram bounding box for the given question on the page.

    Returns normalized [xmin, ymin, xmax, ymax] in 0..1000 coordinate space.
    """
    from google import genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    client = genai.Client(api_key=api_key)

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=DiagramBBox,
    )

    instruction = "Detect the diagram related to the question in the image. If multiple diagrams are present for a question, return the box_2d containing all the diagrams. The box_2d should be [ymin, xmin, ymax, xmax] normalized to 0-1000."

    prompt = f"Question: {question_text}\n{instruction}"

    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[page_image, prompt],
        config=config,
    )

    text = (resp.text or "").strip()

    try:
        bbox_obj: DiagramBBox = resp.parsed
        return bbox_obj.box_2d
    except Exception as e:
        logger.warning(f"Failed to parse Gemini bbox: {e}; raw: {text[:200]}")
        return [0.0, 0.0, 1000.0, 1000.0]
