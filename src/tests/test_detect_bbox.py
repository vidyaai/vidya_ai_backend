import os
import argparse
from typing import List

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test Gemini detect_diagram_bbox on a page image and question text",
    )
    parser.add_argument(
        "--image",
        required=True,
        help="Path to a page image (PNG/JPG)",
    )
    parser.add_argument(
        "--question",
        required=True,
        help="Question text referencing the diagram on the page",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional GEMINI_API_KEY (overrides env if provided)",
    )

    args = parser.parse_args()

    if args.api_key:
        os.environ["GEMINI_API_KEY"] = args.api_key

    try:
        img = Image.open(args.image).convert("RGB")
    except Exception as e:
        raise SystemExit(f"Failed to open image {args.image}: {e}")

    try:
        from controllers.vision_gemini import detect_diagram_bbox

        bbox: List[float] = detect_diagram_bbox(img, args.question)
        print(
            {
                "input_image": args.image,
                "question": args.question,
                "bbox_format": "[ymin, xmin, ymax, xmax] normalized 0..1000",
                "bbox": bbox,
            }
        )
    except Exception as e:
        raise SystemExit(f"Detection failed: {e}")


if __name__ == "__main__":
    main()
