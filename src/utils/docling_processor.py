"""
Hybrid Document Processor using Docling + Optional GPT-4o Vision

Strategy:
1. Use Docling for fast, reliable text extraction (8x faster than GPT-4o vision)
2. Docling detects all images and their locations
3. Optionally use GPT-4o vision to describe ONLY key images (much cheaper than full PDF)
4. Embed image descriptions back into markdown text

Benefits:
- Fast extraction: 35-41 seconds instead of 56-305 seconds
- Free base extraction: No API costs for text
- Targeted image description: Only describe important diagrams
- Cost savings: ~$0.003 per image vs $0.027 for entire PDF
- More reliable: No refusals, consistent output
"""

import os
import base64
from typing import Dict, List, Any, Optional
from pathlib import Path
from io import BytesIO

from docling.document_converter import DocumentConverter
from docling.datamodel.pipeline_options import PdfPipelineOptions
from openai import OpenAI
from controllers.config import logger


class DoclingProcessor:
    """
    Hybrid document processor using Docling for extraction
    and optional GPT-4o vision for image descriptions
    """

    def __init__(self, enable_image_descriptions: bool = False):
        """
        Initialize processor

        Args:
            enable_image_descriptions: If True, use GPT-4o to describe images
                                      If False, just mark image locations
        """
        self.enable_image_descriptions = enable_image_descriptions
        self.client = OpenAI() if enable_image_descriptions else None

    def extract_text_from_pdf(
        self,
        pdf_bytes: bytes,
        describe_images: bool = None,
        max_images_to_describe: int = 10
    ) -> str:
        """
        Extract text from PDF using Docling with optional image descriptions

        Args:
            pdf_bytes: PDF file bytes
            describe_images: Override instance setting for image descriptions
            max_images_to_describe: Maximum number of images to describe (cost control)

        Returns:
            Extracted markdown text with optional image descriptions
        """
        # Use instance setting if not overridden
        if describe_images is None:
            describe_images = self.enable_image_descriptions

        logger.info(
            f"Extracting PDF with Docling (image descriptions: {describe_images})"
        )

        try:
            # Save bytes to temporary file (docling needs file path)
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(pdf_bytes)
                tmp_path = tmp.name

            # Configure pipeline options
            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_ocr = True
            pipeline_options.do_table_structure = True
            pipeline_options.images_scale = 2.0
            pipeline_options.generate_picture_images = True

            # Convert PDF
            converter = DocumentConverter()
            result = converter.convert(tmp_path)

            # Clean up temp file
            os.unlink(tmp_path)

            # Get document
            doc = result.document

            # Get base markdown
            markdown = doc.export_to_markdown()

            # Log extraction stats
            image_count = markdown.count('<!-- image -->')
            char_count = len(markdown)
            logger.info(
                f"Docling extraction complete: {char_count:,} chars, "
                f"{image_count} images detected"
            )

            # If image descriptions disabled, return as-is
            if not describe_images:
                logger.info("Image descriptions disabled - returning text with image markers")
                return markdown

            # Extract images and get descriptions
            logger.info(
                f"Describing up to {max_images_to_describe} images with GPT-4o..."
            )

            images_with_descriptions = self._describe_images(
                doc, pdf_bytes, max_images=max_images_to_describe
            )

            # Embed descriptions into markdown
            enhanced_markdown = self._embed_image_descriptions(
                markdown, images_with_descriptions
            )

            logger.info(
                f"Enhanced {len(images_with_descriptions)} images with descriptions"
            )

            return enhanced_markdown

        except Exception as e:
            logger.error(f"Docling extraction failed: {str(e)}")
            raise

    def _describe_images(
        self, doc, pdf_bytes: bytes, max_images: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Use GPT-4o vision to describe extracted images

        Args:
            doc: Docling document object
            pdf_bytes: Original PDF bytes (for extracting image regions)
            max_images: Maximum images to describe (cost control)

        Returns:
            List of image descriptions with locations
        """
        if not self.client:
            return []

        # Collect pictures/figures
        pictures = []
        for element, _level in doc.iterate_items():
            if hasattr(element, 'label'):
                if 'picture' in element.label.lower() or 'figure' in element.label.lower():
                    pictures.append(element)

        # Limit to max_images
        pictures = pictures[:max_images]

        logger.info(f"Describing {len(pictures)} images (max: {max_images})")

        descriptions = []

        # Convert PDF to images for extraction
        try:
            from pdf2image import convert_from_bytes
            page_images = convert_from_bytes(pdf_bytes, dpi=200)
        except Exception as e:
            logger.error(f"Could not convert PDF to images: {e}")
            return []

        for i, picture in enumerate(pictures, 1):
            try:
                # Get page number and bounding box
                if not hasattr(picture, 'prov') or not picture.prov:
                    continue

                prov = picture.prov[0]
                page_no = prov.page_no
                bbox = prov.bbox if hasattr(prov, 'bbox') else None

                if not bbox or page_no > len(page_images):
                    continue

                # Get page image (page_no is 1-indexed)
                page_img = page_images[page_no - 1]

                # Crop to bounding box
                # Convert docling bbox (PDF coords) to PIL image coords
                # PDF origin is bottom-left, PIL origin is top-left
                page_height = page_img.height

                # Docling bbox: l (left), t (top), r (right), b (bottom) in PDF coords
                # PIL crop: (left, upper, right, lower) in image coords
                # Convert: y_image = page_height - y_pdf
                left = bbox.l
                upper = page_height - bbox.b  # bottom in PDF = upper in image
                right = bbox.r
                lower = page_height - bbox.t  # top in PDF = lower in image

                # Ensure coordinates are valid
                left = max(0, min(left, page_img.width))
                right = max(0, min(right, page_img.width))
                upper = max(0, min(upper, page_img.height))
                lower = max(0, min(lower, page_img.height))

                # Ensure left < right and upper < lower
                if left >= right or upper >= lower:
                    logger.warning(f"Invalid bbox for image {i}: skipping")
                    continue

                cropped = page_img.crop((left, upper, right, lower))

                # Convert to base64
                buffered = BytesIO()
                cropped.save(buffered, format="PNG")
                img_base64 = base64.b64encode(buffered.getvalue()).decode()

                # Get description from GPT-4o
                description = self._get_image_description(img_base64, page_no)

                descriptions.append({
                    "index": i - 1,  # 0-indexed for replacement
                    "page": page_no,
                    "bbox": bbox,
                    "description": description
                })

                logger.info(
                    f"  Described image {i}/{len(pictures)} "
                    f"(page {page_no}): {description[:60]}..."
                )

            except Exception as e:
                logger.error(f"Failed to describe image {i}: {e}")
                continue

        return descriptions

    def _get_image_description(self, img_base64: str, page_no: int) -> str:
        """
        Get description of a single image using GPT-4o vision

        Args:
            img_base64: Base64 encoded image
            page_no: Page number for context

        Returns:
            Description string
        """
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are analyzing a diagram/figure from a technical lecture. "
                            "Provide a clear, technical description of what the diagram shows. "
                            "Include: type of diagram, main components, labels, key concepts illustrated. "
                            "Keep description concise but informative (2-3 sentences)."
                        )
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Describe this diagram from page {page_no} of a technical lecture:"
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img_base64}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=300,
                temperature=0.1
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            logger.error(f"GPT-4o vision description failed: {e}")
            return "[Image description unavailable]"

    def _embed_image_descriptions(
        self, markdown: str, descriptions: List[Dict[str, Any]]
    ) -> str:
        """
        Replace <!-- image --> markers with descriptions

        Args:
            markdown: Original markdown with <!-- image --> markers
            descriptions: List of image descriptions

        Returns:
            Enhanced markdown with descriptions
        """
        if not descriptions:
            return markdown

        # Replace each <!-- image --> marker with description
        # Note: This replaces in order of appearance
        lines = markdown.split('\n')
        image_index = 0
        result_lines = []

        for line in lines:
            if '<!-- image -->' in line and image_index < len(descriptions):
                desc = descriptions[image_index]
                # Replace marker with description
                enhanced_line = line.replace(
                    '<!-- image -->',
                    f'[DIAGRAM on Page {desc["page"]}: {desc["description"]}]'
                )
                result_lines.append(enhanced_line)
                image_index += 1
            else:
                result_lines.append(line)

        return '\n'.join(result_lines)


# Convenience function for compatibility with existing code
def extract_pdf_with_docling(
    pdf_bytes: bytes,
    describe_images: bool = False,
    max_images: int = 10
) -> str:
    """
    Convenience function to extract PDF with Docling

    Args:
        pdf_bytes: PDF file bytes
        describe_images: Whether to describe images with GPT-4o
        max_images: Max images to describe (cost control)

    Returns:
        Extracted markdown text
    """
    processor = DoclingProcessor(enable_image_descriptions=describe_images)
    return processor.extract_text_from_pdf(
        pdf_bytes,
        describe_images=describe_images,
        max_images_to_describe=max_images
    )
