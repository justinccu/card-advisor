"""Bedrock Converse calls with a hard spend cap.

Every call's token usage is priced and appended to a local ledger; a call that could push the
running total past the cap is refused before it is made.
"""

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# USD per 1M tokens (input, output), us-east-2, verified via the AWS Pricing API on 2026-09-24.
PRICES = {
    "moonshotai.kimi-k2.5": (0.60, 3.00),
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00),
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.10, 5.50),
}
DEFAULT_MODEL = "moonshotai.kimi-k2.5"
DEFAULT_BUDGET_USD = 5.0


class BudgetExceeded(Exception):
    pass


def cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES[model_id]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


@dataclass
class Ledger:
    path: Path
    budget_usd: float = float(os.environ.get("SCOUT_BUDGET_USD", DEFAULT_BUDGET_USD))

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line]

    def total_usd(self) -> float:
        return sum(e["cost_usd"] for e in self.entries())

    def guard(self, worst_case_usd: float) -> None:
        spent = self.total_usd()
        if spent + worst_case_usd > self.budget_usd:
            raise BudgetExceeded(
                f"spent ${spent:.4f}; next call could cost up to ${worst_case_usd:.4f}, "
                f"over the ${self.budget_usd:.2f} cap (raise SCOUT_BUDGET_USD to continue)"
            )

    def record(self, *, model_id: str, card_id: str, usage: dict) -> float:
        cost = cost_usd(model_id, usage["inputTokens"], usage["outputTokens"])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "model_id": model_id,
            "card_id": card_id,
            "input_tokens": usage["inputTokens"],
            "output_tokens": usage["outputTokens"],
            "cost_usd": cost,
        }
        with self.path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        return cost


def estimate_input_tokens(text: str) -> int:
    return len(text) // 4
