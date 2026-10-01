"""The model is one setting (ADR 0009): DeepSeek V3.2 on Bedrock (billed by AWS, covered by the
account's credits), chosen 2026-09-30. Qwen3 235B before it wrote tool calls as text at times;
Nova 2 Lite before that skipped the tools. The production model is confirmed in S8 by running
the golden set against the candidates."""

import os

from strands.models.bedrock import BedrockModel

MODEL_ID = os.environ.get("ADVISOR_MODEL_ID", "deepseek.v3.2")
REGION = os.environ.get("AWS_REGION", "us-east-2")

# What a message costs, for the running total that closes the guest trial (ADR 0009): Bedrock
# list prices in USD per million input / output tokens, plus Runtime and Memory per message
# (the rest of ADR 0009's ~$0.015-a-message estimate). A model not listed is priced high, so the
# total errs toward closing the trial early.
PRICES_PER_MILLION = {
    "deepseek.v3.2": (0.62, 1.85),
    "qwen.qwen3-235b-a22b-2507-v1:0": (0.22, 0.88),
}
UNLISTED_PRICES = (5.0, 25.0)
MESSAGE_OVERHEAD_USD = 0.006


def message_cost(input_tokens: int, output_tokens: int, model_id: str = MODEL_ID) -> float:
    per_in, per_out = PRICES_PER_MILLION.get(model_id, UNLISTED_PRICES)
    tokens = (input_tokens * per_in + output_tokens * per_out) / 1_000_000
    return min(1.0, round(tokens + MESSAGE_OVERHEAD_USD, 6))  # the API takes at most $1


def load_model() -> BedrockModel:
    """Bedrock model client using the runtime's IAM role (or local AWS credentials in dev)."""
    return BedrockModel(model_id=MODEL_ID, region_name=REGION, temperature=0.2, max_tokens=1200)
