"""Text normalization utilities for AI responses."""

import re
import logging

logger = logging.getLogger(__name__)


def normalize_ai_response(text: str) -> str:
    """
    Normalize AI-generated text for consistent frontend rendering.

    This function ensures that AI responses render correctly in the frontend
    by handling line endings, numbered lists, and excess whitespace.

    Args:
        text: Raw AI-generated text

    Returns:
        Normalized text ready for frontend consumption

    Handles:
        - Line ending normalization (Windows → Unix)
        - Numbered list formatting (joins markers with content)
        - Excess whitespace removal
        - Invisible Unicode character removal
    """
    if not text:
        return text

    # Log original for debugging (can be removed after verification)
    # logger.debug(f"Normalizing text (first 200 chars): {text[:200]}")
    # logger.debug(f"Raw format: {repr(text[:100])}")

    # Step 1: Normalize line endings to Unix style (\n)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Step 2: Remove invisible Unicode characters that cause rendering issues
    text = re.sub(r"[\u200B-\u200D\uFEFF]", "", text)

    # Step 3: Remove excessive blank lines (more than 2 consecutive newlines)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Step 4: Join numbered list markers with their content
    # Pattern: "1." + optional whitespace + newline(s) + optional whitespace + content
    # Uses lookahead (?=\S) to ensure there's actual content after
    text = re.sub(r"(\d+\.)\s*\n+\s*(?=\S)", r"\1 ", text)

    # logger.debug(f"Normalized text (first 200 chars): {text[:200]}")

    return text


def validate_ai_response(text: str) -> dict:
    """
    Validate AI response for common issues.

    Args:
        text: AI-generated text to validate

    Returns:
        Dict with validation results:
        {
            "valid": bool,
            "issues": list of issue descriptions,
            "warnings": list of warning messages
        }
    """
    issues = []
    warnings = []

    if not text or not text.strip():
        issues.append("Response is empty or whitespace only")

    if len(text) > 50000:
        warnings.append("Response is unusually long (>50k chars)")

    # Check for excessive newlines
    consecutive_newlines = re.findall(r"\n{4,}", text)
    if consecutive_newlines:
        warnings.append(
            f"Found {len(consecutive_newlines)} instances of 4+ consecutive newlines"
        )

    # Check for malformed numbered lists
    malformed_lists = re.findall(r"\d+\.\s*\n\s*\n", text)
    if malformed_lists:
        warnings.append(
            f"Found {len(malformed_lists)} malformed numbered lists (will be auto-fixed)"
        )

    return {"valid": len(issues) == 0, "issues": issues, "warnings": warnings}
