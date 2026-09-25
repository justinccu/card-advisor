"""What Scout extracts from one Card Product page. Every fact carries a verbatim quote.

A value with no quote, or a quote not found on the page, is flagged for review (ADR 0002):
that is how we catch the model inventing an Offer.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class SourcedInt(BaseModel):
    value: int | None = Field(description="null if the page does not state it")
    evidence: str | None = Field(description="short verbatim quote from the page supporting value")


class SourcedFloat(BaseModel):
    value: float | None = Field(description="null if the page does not state it")
    evidence: str | None = Field(description="short verbatim quote from the page supporting value")


class SourcedBool(BaseModel):
    value: bool | None = Field(description="null if the page does not state it")
    evidence: str | None = Field(description="short verbatim quote from the page supporting value")


class SourcedStr(BaseModel):
    value: str | None = Field(description="null if the page does not state it")
    evidence: str | None = Field(description="short verbatim quote from the page supporting value")


class ExtractedOffer(BaseModel):
    amount_disclosed: bool = Field(
        description="false when the page hides the amount (e.g. 'apply to find out your offer')"
    )
    amount: SourcedInt = Field(description="bonus size in `unit`; null if not disclosed")
    unit: Literal["points", "miles", "usd", "gift_card_usd", "cashback_match", "free_nights"]
    min_spend_usd: SourcedInt = Field(description="null if no spend is required")
    spend_window_months: SourcedInt = Field(description="convert days to months: 90 days -> 3")


class EarningRate(BaseModel):
    category: str = Field(description="e.g. 'dining', 'U.S. supermarkets', 'everything else'")
    rate: float = Field(description="3 for 3X points/miles, 3 for 3% cash back")
    unit: Literal["x_points", "x_miles", "percent_cash_back"]
    cap_usd: int | None = Field(description="spend cap before the rate drops, else null")
    cap_period: Literal["month", "quarter", "year", "calendar_year"] | None
    evidence: str


class Credit(BaseModel):
    description: str
    amount_usd: int
    period: Literal["one_time", "month", "year", "calendar_year", "semi_annual", "four_years"]
    evidence: str


class ExtractedCard(BaseModel):
    annual_fee_usd: SourcedInt
    first_year_annual_fee_usd: SourcedInt = Field(
        description="only if the first year differs from annual_fee_usd, else value null"
    )
    foreign_transaction_fee_pct: SourcedFloat = Field(description="0 if the page says none")
    network: SourcedStr = Field(description="Visa, Mastercard, American Express, or Discover")
    offer: ExtractedOffer | None = Field(description="the welcome/sign-up bonus; null if none")
    earning_rates: list[EarningRate]
    credits: list[Credit] = Field(description="statement credits and similar dollar benefits")
    accepts_itin: SourcedBool = Field(description="only if the page mentions ITIN applications")
    reviewer_notes: str = Field(
        description="conditions a reviewer must know, e.g. 'requires Prime membership'"
    )


def tool_input_schema() -> dict[str, Any]:
    """JSON schema with every $ref inlined: not all Bedrock models resolve $defs in tool schemas."""
    schema = ExtractedCard.model_json_schema()
    defs = schema.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return inline(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {k: inline(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [inline(v) for v in node]
        return node

    return inline(schema)
