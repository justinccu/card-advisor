"""Domain types. Names follow CONTEXT.md; keep them in sync."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class Market(StrEnum):
    US = "US"
    TW = "TW"


class TaxId(StrEnum):
    SSN = "SSN"
    ITIN = "ITIN"
    NONE = "NONE"


class CardProduct(BaseModel):
    id: str
    issuer_id: str
    name: str
    market: Market = Market.US
    family: str | None = None
    is_business: bool = False
    is_charge_card: bool = False
    accepted_tax_ids: frozenset[TaxId] = frozenset({TaxId.SSN})


class HeldCard(BaseModel):
    issuer_id: str
    opened_on: date
    card_product_id: str | None = None  # None when the card isn't in our catalog
    family: str | None = None
    closed_on: date | None = None
    is_business: bool = False
    is_charge_card: bool = False
    is_authorized_user: bool = False
    bonus_received_on: date | None = None

    @property
    def is_open(self) -> bool:
        return self.closed_on is None


class Wallet(BaseModel):
    """A user's Held Cards plus what the user has attested about the list's completeness.

    Rules only trust the absence of a card when the matching attestation covers it;
    otherwise they return Undetermined instead of guessing Eligible.
    """

    cards: list[HeldCard] = Field(default_factory=list)
    complete_since: date | None = None  # every card opened on/after this date is listed
    includes_all_open_cards: bool = False
    full_history_issuers: frozenset[str] = frozenset()


class ApplicantProfile(BaseModel):
    tax_id: TaxId | None = None


# --- Eligibility Rules -------------------------------------------------------

Strength = Literal["strict", "soft"]
Confidence = Literal["official", "community"]
ProductScope = Literal["personal", "business", "all"]


class _RuleBase(BaseModel):
    id: str
    issuer_id: str
    market: Market = Market.US
    description: str
    # strict: violations make the verdict Ineligible. soft: inconsistently enforced,
    # so violations become warnings and never change the verdict.
    strength: Strength = "strict"
    confidence: Confidence
    source_url: HttpUrl
    verified_on: date
    applies_to_products: ProductScope = "personal"
    applies_to_charge_cards: bool = True
    # Cards this rule skips because a stricter rule of their own covers them.
    not_for_products: list[str] = []


class VelocityRule(_RuleBase):
    """Application Rule: fewer than `limit` new cards opened within the window."""

    kind: Literal["velocity"] = "velocity"
    scope: Literal["all_issuers", "same_issuer"]
    limit: int
    window_months: int | None = None
    window_days: int | None = None
    counts_authorized_user: bool = False
    counts_business: bool = False
    counts_charge_cards: bool = True


class MaxOpenRule(_RuleBase):
    """Application Rule: fewer than `limit` open cards with this Issuer."""

    kind: Literal["max_open"] = "max_open"
    limit: int
    counts_business: bool = True
    counts_charge_cards: bool = True


class ProductOpenRule(_RuleBase):
    """Application Rule: the card can't be opened while you already have it open (Chase
    Sapphire: "unavailable to you if you currently have one open"). `family` limits the rule to
    that family's cards."""

    kind: Literal["product_open"] = "product_open"
    family: str | None = None


class FamilyOpenRule(_RuleBase):
    """Offer Rule: no Offer while another card of the same family is open."""

    kind: Literal["family_open"] = "family_open"
    family: str


class OfferHistoryRule(_RuleBase):
    """Offer Rule: no Offer if the user held / earned a bonus within the lookback (None =
    lifetime) on: the product itself (`product`), any card of its family (`family`), or any of
    listed `products` (`products`, e.g. Amex's ladder: no Gold Offer after holding Platinum).
    `for_product` limits the rule to Offers on one Card Product."""

    kind: Literal["offer_history"] = "offer_history"
    target: Literal["product", "family", "products"]
    family: str | None = None
    products: list[str] = []
    for_product: str | None = None
    basis: Literal["held", "bonus"]
    lookback_months: int | None = None

    @model_validator(mode="after")
    def _target_fields(self) -> "OfferHistoryRule":
        if self.target == "products" and not (self.products and self.for_product):
            raise ValueError(f"{self.id}: target 'products' needs `products` and `for_product`")
        if self.target == "family" and not self.family:
            raise ValueError(f"{self.id}: target 'family' needs `family`")
        return self


ApplicationRule = VelocityRule | MaxOpenRule | ProductOpenRule
OfferRule = FamilyOpenRule | OfferHistoryRule
EligibilityRule = Annotated[
    VelocityRule | MaxOpenRule | ProductOpenRule | FamilyOpenRule | OfferHistoryRule,
    Field(discriminator="kind"),
]


# --- Verdicts ----------------------------------------------------------------


class Status(StrEnum):
    ELIGIBLE = "Eligible"
    INELIGIBLE = "Ineligible"
    UNDETERMINED = "Undetermined"


class Reason(BaseModel):
    rule_id: str
    status: Status
    message: str
    confidence: Confidence
    source_url: str | None = None
    retry_after: date | None = None  # earliest date this rule stops blocking


class Verdict(BaseModel):
    status: Status
    reasons: list[Reason] = Field(default_factory=list)
    warnings: list[Reason] = Field(default_factory=list)


class Evaluation(BaseModel):
    """Eligibility Verdicts for one Card Product: can the user be approved (application),
    and would they earn its Offer (offer)."""

    card_product_id: str
    as_of: date
    application: Verdict
    offer: Verdict
