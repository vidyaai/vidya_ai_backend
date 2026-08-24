"""AWS Bedrock client + Claude model-ID mapping for the Anthropic SDK.

Use ``get_bedrock_client()`` everywhere we used to call ``anthropic.Anthropic(...)``.
The AnthropicBedrock client exposes the exact same ``.messages.create(...)`` API,
so call sites only need to swap the constructor and pass a Bedrock model ID
(via ``resolve_model_id``) instead of the raw Claude model name.

Auth: anthropic>=0.103 reads the long-term Bedrock API key from
``AWS_BEARER_TOKEN_BEDROCK`` and sends it as ``Authorization: Bearer ...``
to the bedrock-runtime endpoint — no SigV4 / IAM credentials required.
"""

from __future__ import annotations

import os
from functools import lru_cache

from anthropic import AnthropicBedrock

# Maps the Claude model name used throughout the codebase to its Bedrock
# US-geo inference-profile ID. Verify each ID against the AWS Bedrock console
# (model card → Programmatic Access → Geo inference ID for US) before promoting.
#
# Note: the original "claude-sonnet-4-20250514" model is no longer offered on
# Bedrock — we map it forward to Sonnet 4.6 (the current mid-tier Claude).
BEDROCK_MODEL_MAP: dict[str, str] = {
    "claude-sonnet-4-20250514": "us.anthropic.claude-sonnet-4-6",
    "claude-opus-4-5": "us.anthropic.claude-opus-4-5-20251101-v1:0",
    "claude-opus-4-6": "us.anthropic.claude-opus-4-6-v1",
    "claude-haiku-4-5-20251001": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
}


@lru_cache(maxsize=1)
def get_bedrock_client() -> AnthropicBedrock:
    """Return a process-wide AnthropicBedrock client.

    Authenticates with the long-term Bedrock API key from the
    ``AWS_BEARER_TOKEN_BEDROCK`` env var (the SDK reads it automatically).
    ``AWS_BEDROCK_REGION`` selects the ``bedrock-runtime.{region}.amazonaws.com``
    endpoint; ``us-east-1`` is the default and matches the US-geo inference
    profiles in ``BEDROCK_MODEL_MAP``.
    """
    return AnthropicBedrock(
        aws_region=os.getenv("AWS_BEDROCK_REGION", "us-east-1"),
    )


def resolve_model_id(model: str) -> str:
    """Translate a Claude model name to its Bedrock inference-profile ID.

    Accepts either a short name (e.g. ``claude-opus-4-5``) or an already-resolved
    Bedrock ID (e.g. ``us.anthropic.claude-opus-4-5-20251101-v1:0``) and passes
    the latter through unchanged.
    """
    if model in BEDROCK_MODEL_MAP:
        return BEDROCK_MODEL_MAP[model]
    if model.startswith(("us.anthropic.", "anthropic.")):
        return model
    raise ValueError(f"Unmapped Claude model for Bedrock: {model}")
