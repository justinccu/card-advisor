"""Glue between stored user data and the deterministic rules engine (ADR 0001)."""

from datetime import date

from card_rules import evaluate, load_rules
from card_rules import models as rules
from card_rules.catalog import CatalogCard
from card_rules.dates import add_months, age_out_date

from card_api.models import ApplicantProfile, HeldCard, Velocity, WalletAttestation

VELOCITY_WINDOW_MONTHS = 24


def to_rules_wallet(
    cards: list[HeldCard], attestation: WalletAttestation, catalog: dict[str, CatalogCard]
) -> rules.Wallet:
    held = []
    for c in cards:
        product = catalog.get(c.card_product_id) if c.card_product_id else None
        held.append(
            rules.HeldCard(
                issuer_id=product.issuer_id if product else (c.issuer_id or "unknown"),
                opened_on=c.opened_on,
                card_product_id=c.card_product_id,
                family=product.family if product else None,
                closed_on=c.closed_on,
                is_business=product.is_business if product else c.is_business,
                is_charge_card=product.is_charge_card if product else False,
                is_authorized_user=c.is_authorized_user,
                bonus_received_on=c.bonus_received_on,
            )
        )
    return rules.Wallet(
        cards=held,
        complete_since=attestation.complete_since,
        includes_all_open_cards=attestation.includes_all_open_cards,
        full_history_issuers=frozenset(attestation.full_history_issuers),
    )


def evaluate_cards(
    products: list[CatalogCard],
    profile: ApplicantProfile,
    wallet: rules.Wallet,
    as_of: date,
) -> list[dict]:
    rule_set = load_rules()
    applicant = rules.ApplicantProfile(tax_id=profile.tax_id)
    out = []
    for product in products:
        result = evaluate(product, applicant, wallet, rule_set, as_of)
        out.append({"name": product.name, **result.model_dump(mode="json")})
    return out


def velocity(wallet: rules.Wallet, as_of: date) -> Velocity:
    """The 5/24 count: personal cards (authorized-user cards included) opened in 24 months."""
    start = add_months(as_of, -VELOCITY_WINDOW_MONTHS)
    opened = sorted(
        c.opened_on for c in wallet.cards if start < c.opened_on <= as_of and not c.is_business
    )
    return Velocity(
        count_24m=len(opened),
        next_drop_off=age_out_date(opened[0], months=VELOCITY_WINDOW_MONTHS) if opened else None,
        complete=wallet.complete_since is not None and wallet.complete_since <= start,
    )
