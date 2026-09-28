"""Card ranking by estimated dollar value (ADR 0001, 0009).

Pure functions of (Catalog Snapshot cards + valuations, Spending Profile, Eligibility Verdicts,
options): no clock, no I/O, so a Recommendation replays exactly against one snapshot.

    First-year Value = Offer (if earnable) + a year of rewards + confirmed credits − first-year fee
    Ongoing Value    = a year of rewards + confirmed recurring credits − annual fee

Rewards use Conservative Point Valuations. Rates with a condition the profile can't show
(portal, brand, ...) count only when the caller opts in; the rest are listed, never counted.
"""

from typing import Literal

from pydantic import BaseModel, Field

from card_rules.catalog import CatalogCard, EarningRate, SpendCategory, Valuation
from card_rules.models import Evaluation, Status

Goal = Literal["earn_offers", "long_term", "travel", "cash_back", "build_credit"]

# How many times a cap or credit period fits in a year.
PER_YEAR = {
    "month": 12,
    "monthly": 12,
    "quarter": 4,
    "quarterly": 4,
    "semi_annual": 2,
    "year": 1,
    "annual": 1,
    "calendar_year": 1,
    "cardmember_year": 1,
    "four_years": 0.25,
}
STARTER_TAGS = {"starter", "secured", "student"}


class SpendingProfile(BaseModel):
    """Monthly spend per category and what the user wants (ADR 0009). `source` is where the
    numbers came from; ranking treats manual and imported numbers the same."""

    monthly_usd: dict[SpendCategory, float] = {}
    goals: list[Goal] = []
    max_annual_fee_usd: int | None = None
    wants_business: bool = False
    source: Literal["manual", "statements"] = "manual"


class RankOptions(BaseModel):
    """What the user confirmed in conversation: conditional rates that apply to them
    ("portal:chase", "brand:delta") and credits they'd really use ({card_id: [description]})."""

    opted_in: set[str] = set()
    credits: dict[str, list[str]] = {}
    include_business: bool | None = None  # None: follow the Spending Profile
    limit: int = 10


class Breakdown(BaseModel):
    offer_usd: float = 0
    rewards_usd: float = 0
    credits_first_year_usd: float = 0
    credits_ongoing_usd: float = 0
    first_year_fee_usd: float = 0
    annual_fee_usd: float = 0


class RankedCard(BaseModel):
    card_id: str
    name: str
    first_year_value_usd: float
    ongoing_value_usd: float
    breakdown: Breakdown
    offer_counted: bool
    offer_is_up_to: bool = False
    # How far usual spend falls short of the Minimum Spend in its window (0 = on track).
    min_spend_gap_usd: float | None = None
    application_status: Status
    offer_status: Status
    notes: list[str] = []
    # Rates not counted because of a condition, for the Advisor to mention.
    conditional_rates: list[str] = []


class Excluded(BaseModel):
    card_id: str
    name: str
    reason: str
    retry_after: str | None = None


class Ranking(BaseModel):
    sort_by: Literal["first_year", "ongoing"]
    cards: list[RankedCard] = Field(default_factory=list)
    excluded: list[Excluded] = Field(default_factory=list)


def _cents(card: CatalogCard, valuations: dict[str, Valuation]) -> float | None:
    """US cents per point/mile for this card, or None for cash back."""
    if card.currency is None:
        return None
    return valuations[card.currency].cents


def _rate_usd(rate: EarningRate, cents: float | None) -> float:
    """Dollars earned per dollar spent at this rate."""
    if rate.unit == "percent_cash_back":
        return rate.rate / 100
    return rate.rate * (cents if cents is not None else 0) / 100


def _counts(rate: EarningRate, card: CatalogCard, opted_in: set[str]) -> bool:
    if rate.when is None:
        return True
    if rate.when == "portal":
        return f"portal:{card.issuer_id}" in opted_in
    if rate.when == "brand":
        return f"brand:{rate.brand}" in opted_in
    return False  # choice / relationship / business / time_window: not computable in v1


def _annual_cap(rate: EarningRate) -> float | None:
    if rate.cap_usd is None:
        return None
    return rate.cap_usd * PER_YEAR.get(rate.cap_period or "year", 1)


def annual_rewards(
    card: CatalogCard, cents: float | None, monthly: dict[str, float], opted_in: set[str]
) -> tuple[float, list[str]]:
    """A year of rewards in dollars, allocating each category's spend to the best counted rate
    first (respecting caps shared across a rate's categories); what's left earns the base rate."""
    remaining = {c: 12 * max(0.0, v) for c, v in monthly.items() if v}
    conditional: list[str] = []
    counted = []
    base: EarningRate | None = None
    for rate in card.earning_rates:
        if not _counts(rate, card, opted_in):
            label = rate.when + (f":{rate.brand}" if rate.brand else "")
            conditional.append(f"{rate.rate:g}{_unit(rate)} on {rate.category} ({label})")
            continue
        if rate.spend == ["everything_else"]:
            if base is None or _rate_usd(rate, cents) > _rate_usd(base, cents):
                base = rate
            continue
        counted.append(rate)

    total = 0.0
    for rate in sorted(counted, key=lambda r: _rate_usd(r, cents), reverse=True):
        cap = _annual_cap(rate)
        for category in rate.spend:
            if category == "everything_else":
                continue
            take = remaining.get(category, 0.0)
            if cap is not None:
                take = min(take, cap)
                cap -= take
            total += take * _rate_usd(rate, cents)
            remaining[category] = remaining.get(category, 0.0) - take
    if base is not None:
        total += sum(remaining.values()) * _rate_usd(base, cents)
    return round(total, 2), conditional


def _unit(rate: EarningRate) -> str:
    return "%" if rate.unit == "percent_cash_back" else "x"


def _credits(card: CatalogCard, confirmed: list[str]) -> tuple[float, float]:
    """(first-year, ongoing) dollars from the credits the user said they'd use."""
    first = ongoing = 0.0
    for credit in card.credits:
        if credit.description not in confirmed or credit.amount_usd is None:
            continue
        if credit.period == "one_time":
            first += credit.amount_usd
        elif credit.period in PER_YEAR:
            yearly = credit.amount_usd * PER_YEAR[credit.period]
            first += yearly
            ongoing += yearly
    return round(first, 2), round(ongoing, 2)


def _offer_usd(
    card: CatalogCard, cents: float | None, valuations: dict[str, Valuation], first_year: float
) -> tuple[float, list[str]]:
    offer = card.offer
    if offer is None:
        return 0.0, []
    notes = []
    value = 0.0
    if offer.amount is None:
        notes.append("Offer amount isn't public; not counted")
    elif offer.unit in ("usd", "gift_card_usd"):
        value = offer.amount
    elif offer.unit in ("points", "miles"):
        value = offer.amount * (cents or 0) / 100
    elif offer.unit == "free_nights":
        per_night = valuations[card.currency].free_night_points if card.currency else None
        if per_night:
            value = offer.amount * per_night * (cents or 0) / 100
        else:
            notes.append("free-night Offer has no per-night valuation; not counted")
    if offer.unit == "cashback_match":
        value = first_year  # matches all cash back earned in the first year
    value += offer.statement_credit_usd or 0
    if offer.amount_is_up_to and offer.amount is not None:
        notes.append("Offer is an 'up to' ceiling; many applicants get less")
    return round(value, 2), notes


def _missing(evaluation: Evaluation) -> list[str]:
    reasons = evaluation.application.reasons + evaluation.offer.reasons
    return [r.message for r in reasons if r.status is Status.UNDETERMINED]


def rank(
    cards: list[CatalogCard],
    valuations: dict[str, Valuation],
    spending: SpendingProfile,
    evaluations: dict[str, Evaluation],
    options: RankOptions | None = None,
) -> Ranking:
    options = options or RankOptions()
    business = (
        spending.wants_business if options.include_business is None else options.include_business
    )
    sort_by = "first_year" if "earn_offers" in spending.goals else "ongoing"
    ranking = Ranking(sort_by=sort_by)
    monthly = dict(spending.monthly_usd)
    monthly_total = sum(monthly.values())

    for card in cards:
        if card.availability != "open":
            continue
        if card.is_business and not business:
            continue
        if "build_credit" in spending.goals and not STARTER_TAGS & set(card.tags):
            continue
        evaluation = evaluations.get(card.id)
        if evaluation is None:
            continue
        if evaluation.application.status is Status.INELIGIBLE:
            blocking = [r for r in evaluation.application.reasons if r.status is Status.INELIGIBLE]
            retry = max((r.retry_after for r in blocking if r.retry_after), default=None)
            ranking.excluded.append(
                Excluded(
                    card_id=card.id,
                    name=card.name,
                    reason="; ".join(r.message for r in blocking),
                    retry_after=retry.isoformat() if retry else None,
                )
            )
            continue
        fee = card.annual_fee_usd or 0
        if spending.max_annual_fee_usd is not None and fee > spending.max_annual_fee_usd:
            ranking.excluded.append(
                Excluded(
                    card_id=card.id,
                    name=card.name,
                    reason=f"${fee} annual fee is over your ${spending.max_annual_fee_usd} limit",
                )
            )
            continue

        cents = _cents(card, valuations)
        rewards, conditional = annual_rewards(card, cents, monthly, options.opted_in)
        credits_first, credits_ongoing = _credits(card, options.credits.get(card.id, []))
        offer_counted = evaluation.offer.status is not Status.INELIGIBLE
        offer_value, notes = _offer_usd(card, cents, valuations, rewards)
        if not offer_counted and card.offer is not None:
            notes = ["You may not earn this card's Offer, so it isn't counted", *notes]
            offer_value = 0.0
        first_fee = (
            card.first_year_annual_fee_usd if card.first_year_annual_fee_usd is not None else fee
        )

        gap = None
        if card.offer and card.offer.min_spend_usd and card.offer.spend_window_months:
            usual = monthly_total * card.offer.spend_window_months
            gap = round(max(0.0, card.offer.min_spend_usd - usual), 2)
            if gap > 0:
                notes.append(
                    f"Minimum Spend ${card.offer.min_spend_usd:,} in "
                    f"{card.offer.spend_window_months} months is ${gap:,.0f} above your usual spend"
                )
        notes += [f"Undetermined: {m}" for m in _missing(evaluation)]

        breakdown = Breakdown(
            offer_usd=offer_value,
            rewards_usd=rewards,
            credits_first_year_usd=credits_first,
            credits_ongoing_usd=credits_ongoing,
            first_year_fee_usd=first_fee,
            annual_fee_usd=fee,
        )
        ranking.cards.append(
            RankedCard(
                card_id=card.id,
                name=card.name,
                first_year_value_usd=round(offer_value + rewards + credits_first - first_fee, 2),
                ongoing_value_usd=round(rewards + credits_ongoing - fee, 2),
                breakdown=breakdown,
                offer_counted=offer_counted and offer_value > 0,
                offer_is_up_to=bool(card.offer and card.offer.amount_is_up_to),
                min_spend_gap_usd=gap,
                application_status=evaluation.application.status,
                offer_status=evaluation.offer.status,
                notes=notes,
                conditional_rates=conditional,
            )
        )

    key = "first_year_value_usd" if sort_by == "first_year" else "ongoing_value_usd"
    ranking.cards.sort(key=lambda c: (getattr(c, key), c.card_id), reverse=True)
    ranking.cards = ranking.cards[: options.limit]
    return ranking
