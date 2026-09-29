"""The model is one setting (ADR 0009). Development uses Qwen3 235B on Bedrock (billed by AWS,
covered by the account's credits). Nova 2 Lite, used before it, skipped the tools and answered
issuer-rule questions from memory, wrongly (2026-09-29). The production model is chosen in S8 by
running the golden set against the candidates, including Claude and Gemini through their own
APIs."""

import os

from strands.models.bedrock import BedrockModel

MODEL_ID = os.environ.get("ADVISOR_MODEL_ID", "qwen.qwen3-235b-a22b-2507-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-2")


def load_model() -> BedrockModel:
    """Bedrock model client using the runtime's IAM role (or local AWS credentials in dev)."""
    return BedrockModel(model_id=MODEL_ID, region_name=REGION, temperature=0.2, max_tokens=1200)
