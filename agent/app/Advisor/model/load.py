"""The model is one setting (ADR 0009). Development uses Amazon Nova 2 Lite (AWS's own model,
covered by the account's credits); DeepSeek V3.1 was first choice but stopped responding on this
account (2026-09-28). The production model is chosen in S8 by running the golden set against the
candidates."""

import os

from strands.models.bedrock import BedrockModel

MODEL_ID = os.environ.get("ADVISOR_MODEL_ID", "us.amazon.nova-2-lite-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-2")


def load_model() -> BedrockModel:
    """Bedrock model client using the runtime's IAM role (or local AWS credentials in dev)."""
    return BedrockModel(model_id=MODEL_ID, region_name=REGION, temperature=0.2, max_tokens=1200)
