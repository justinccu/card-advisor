"""What Scout extracts from one Card Product page. Every fact carries a verbatim quote.

A value with no quote, or a quote not found on the page, is flagged for review (ADR 0002):
that is how we catch the model inventing an Offer.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Free text a scraped page could steer, so it is capped and never published as-is (ADR 0007).
MAX_NOTES_CHARS = 500

# Models differ in how strictly they honor "required": an omitted optional field is read as
# "not stated on the page" (null), which is exactly what an explicit null means.
_EVIDENCE = "short verbatim quote from the page supporting value"


class SourcedInt(BaseModel):
    value: int | None = Field(None, description="null if the page does not state it")
    evidence: str | None = Field(None, description=_EVIDENCE)


class SourcedFloat(BaseModel):
    value: float | None = Field(None, description="null if the page does not state it")
    evidence: str | None = Field(None, description=_EVIDENCE)


class SourcedBool(BaseModel):
    value: bool | None = Field(None, description="null if the page does not state it")
    evidence: str | None = Field(None, description=_EVIDENCE)


class SourcedStr(BaseModel):
    value: str | None = Field(None, description="null if the page does not state it")
    evidence: str | None = Field(None, description=_EVIDENCE)


class ExtractedOffer(BaseModel):
    amount_disclosed: bool = Field(
        description="false when the page hides the amount (e.g. 'apply to find out your offer')"
    )
    amount: SourcedInt = Field(
        default_factory=SourcedInt, description="bonus size in `unit`; null if not disclosed"
    )
    amount_is_up_to: bool = Field(
        False,
        description="true when the page states a ceiling: 'as high as' / 'up to' / 'earn up to'",
    )
    unit: Literal["points", "miles", "usd", "gift_card_usd", "cashback_match", "free_nights"]
    min_spend_usd: SourcedInt = Field(
        default_factory=SourcedInt, description="null if no spend is required"
    )
    spend_window_months: SourcedInt = Field(
        default_factory=SourcedInt, description="convert days to months: 90 days -> 3"
    )
    statement_credit_usd: SourcedInt = Field(
        default_factory=SourcedInt,
        description="two-part offers only: a dollar statement credit earned with the same spend",
    )
    ends_on: SourcedStr = Field(
        default_factory=SourcedStr,
        description="offer end date as YYYY-MM-DD if the page says 'Offer ends ...'",
    )


class EarningRate(BaseModel):
    category: str = Field(description="e.g. 'dining', 'U.S. supermarkets', 'everything else'")
    rate: float = Field(description="3 for 3X points/miles, 3 for 3% cash back")
    unit: Literal["x_points", "x_miles", "percent_cash_back"]
    cap_usd: int | None = Field(None, description="spend cap before the rate drops, else null")
    cap_period: Literal["month", "quarter", "year", "calendar_year"] | None = None
    evidence: str


class Credit(BaseModel):
    description: str
    amount_usd: float | None = Field(
        None, description="dollar value (cents allowed); null for non-dollar or percentage perks"
    )
    period: Literal[
        "one_time",
        "per_use",
        "month",
        "quarter",
        "year",
        "calendar_year",
        "semi_annual",
        "four_years",
    ] = Field(description="per_use: each stay/order/flight; one_time: once per account")
    percent: float | None = Field(None, description="25 for '25% back as a statement credit'")
    valid_until: str | None = Field(None, description="YYYY-MM-DD if the perk is time-limited")
    conditions: str | None = Field(None, description="e.g. 'after $250 spend', 'enrollment'")
    evidence: str


class ExtractedCard(BaseModel):
    annual_fee_usd: SourcedInt = Field(default_factory=SourcedInt)
    first_year_annual_fee_usd: SourcedInt = Field(
        default_factory=SourcedInt,
        description="only if the first year differs from annual_fee_usd, else value null",
    )
    foreign_transaction_fee_pct: SourcedFloat = Field(
        default_factory=SourcedFloat, description="0 if the page says none"
    )
    network: SourcedStr = Field(
        default_factory=SourcedStr, description="Visa, Mastercard, American Express, or Discover"
    )
    offer: ExtractedOffer | None = Field(
        None, description="the welcome/sign-up bonus; null if none"
    )
    earning_rates: list[EarningRate] = []
    credits: list[Credit] = Field([], description="statement credits and similar dollar benefits")
    accepts_itin: SourcedBool = Field(
        default_factory=SourcedBool, description="only if the page mentions ITIN applications"
    )
    reviewer_notes: str = Field(
        "",
        description="conditions a reviewer must know, e.g. 'requires Prime membership'",
        max_length=MAX_NOTES_CHARS,
    )

    @field_validator("reviewer_notes", mode="before")
    @classmethod
    def _truncate_notes(cls, v: object) -> object:
        # Truncate instead of rejecting: a long note must not cost us an otherwise good extraction.
        if isinstance(v, str) and len(v) > MAX_NOTES_CHARS:
            return v[: MAX_NOTES_CHARS - 1] + "…"
        return v


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
