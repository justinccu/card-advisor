"""Catalog Snapshot: the immutable, versioned catalog every consumer reads (ADR 0003).

The static site, the web API, and the agent's tools all load this one shape.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from card_rules.models import CardProduct, Market


class Offer(BaseModel):
    amount_disclosed: bool
    amount: int | None
    unit: Literal["points", "miles", "usd", "gift_card_usd", "cashback_match", "free_nights"]
    min_spend_usd: int | None
    spend_window_months: int | None


class EarningRate(BaseModel):
    category: str
    rate: float
    unit: Literal["x_points", "x_miles", "percent_cash_back"]
    cap_usd: int | None = None
    cap_period: str | None = None


class Credit(BaseModel):
    description: str
    amount_usd: int
    period: str


class CatalogCard(CardProduct):
    url: str
    availability: Literal["open", "closed_to_new_applicants"] = "open"
    closed_on: date | None = None
    tags: list[str] = []
    # Facts below are None for closed cards kept only so users can list them as Held Cards.
    annual_fee_usd: int | None = None
    first_year_annual_fee_usd: int | None = None
    foreign_transaction_fee_pct: float | None = None
    network: str | None = None
    offer: Offer | None = None
    earning_rates: list[EarningRate] = []
    credits: list[Credit] = []
    notes: str = ""
    verified_at: datetime | None = None
    content_hash: str | None = None


class CatalogSnapshot(BaseModel):
    version: int
    market: Market
    generated_at: datetime
    cards: list[CatalogCard]

    def card(self, card_id: str) -> CatalogCard:
        return next(c for c in self.cards if c.id == card_id)
