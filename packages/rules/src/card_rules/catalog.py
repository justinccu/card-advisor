"""Catalog Snapshot: the immutable, versioned catalog every consumer reads (ADR 0003).

The static site, the web API, and the agent's tools all load this one shape.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from card_rules.models import CardProduct, Market


class Offer(BaseModel):
    amount_disclosed: bool
    amount: int | None
    # "as high as" / "up to": `amount` is a ceiling, not what every applicant gets
    amount_is_up_to: bool = False
    unit: Literal["points", "miles", "usd", "gift_card_usd", "cashback_match", "free_nights"]
    min_spend_usd: int | None
    spend_window_months: int | None
    # Two-part offers: a dollar statement credit earned with the same spend as the bonus
    # (Delta Gold: "Earn a $250 Statement Credit and the bonus miles").
    statement_credit_usd: int | None = None
    # "Offer ends 11/4/2026": an ended offer never headlines a card.
    ends_on: date | None = None


class EarningRate(BaseModel):
    category: str
    rate: float
    unit: Literal["x_points", "x_miles", "percent_cash_back"]
    cap_usd: int | None = None
    cap_period: str | None = None


class Credit(BaseModel):
    description: str
    amount_usd: float | None = None  # None for non-dollar perks; cents allowed ($12.95/month)
    period: str  # one_time | per_use | month | quarter | year | calendar_year | ...
    percent: float | None = None  # "25% back as a statement credit": a rate, not an amount
    valid_from: date | None = None  # limited-time perks
    valid_until: date | None = None
    conditions: str | None = None  # e.g. "after $250 spend", "enrollment required"


class OfferVariant(BaseModel):
    """One offer as seen from one source (the main page, or a public campaign landing page)."""

    source_url: str
    profile: Literal["fresh", "campaign", "http"]
    offer: Offer | None
    fetched_at: datetime | None = None


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
    # Every offer version we saw; `offer` is the one chosen by `offer_basis`.
    offer_variants: list[OfferVariant] = []
    # "max_public_number": the largest publicly shown amount (same unit), NOT the highest expected
    # value. An "up to 100,000" ceiling beats a fixed 90,000 even if typical approvals get less.
    offer_basis: Literal["max_public_number"] = "max_public_number"
    # The issuer shows different content to different visitors (HTML vs rendered, or variants).
    varies_by_visitor: bool = False
    # Numbers the issuer ships only in raw HTML (visitors never see them). Kept as notes for
    # reviewers; they can never become the published offer or any field value.
    quarantine: list[str] = []
    # Fields corrected by a person (catalog/seed/overrides.yaml) -> date verified
    manually_verified: dict[str, date] = {}


VERSION_PATTERN = r"^\d+\.\d+$"


def version_key(version: str) -> tuple[int, int]:
    """Numeric sort key for "MAJOR.MINOR", so 1.10 sorts after 1.9."""
    major, minor = version.split(".")
    return int(major), int(minor)


class CatalogSnapshot(BaseModel):
    # "MAJOR.MINOR" (file catalog/us/vMAJOR.MINOR.json). Each publish bumps MINOR; MAJOR marks a
    # change in how the catalog is produced. The local preview is "0.0".
    version: str = Field(pattern=VERSION_PATTERN)
    market: Market
    generated_at: datetime
    cards: list[CatalogCard]
    # True for a local preview built from unreviewed extractions (ADR 0002): never published,
    # and every consumer must label it as unverified.
    preview: bool = False

    @field_validator("version", mode="before")
    @classmethod
    def _legacy_int_version(cls, v: object) -> object:
        # Snapshots written before MAJOR.MINOR (e.g. an old local preview) used a plain integer.
        return f"{v}.0" if isinstance(v, int) else v

    def card(self, card_id: str) -> CatalogCard:
        return next(c for c in self.cards if c.id == card_id)
