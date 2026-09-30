"""The model is one setting (ADR 0009): DeepSeek V3.2 on Bedrock (billed by AWS, covered by the
account's credits), chosen 2026-09-30. Qwen3 235B before it wrote tool calls as text at times;
Nova 2 Lite before that skipped the tools. The production model is confirmed in S8 by running
the golden set against the candidates."""

import os

from strands.models.bedrock import BedrockModel

MODEL_ID = os.environ.get("ADVISOR_MODEL_ID", "deepseek.v3.2")
REGION = os.environ.get("AWS_REGION", "us-east-2")


def load_model() -> BedrockModel:
    """Bedrock model client using the runtime's IAM role (or local AWS credentials in dev)."""
    return BedrockModel(model_id=MODEL_ID, region_name=REGION, temperature=0.2, max_tokens=1200)
