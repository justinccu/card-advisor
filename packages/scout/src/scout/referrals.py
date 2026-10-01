"""Referral facts (catalog/seed/referrals.yaml), stamped into the Catalog Snapshot at publish.

A card entry applies to that card; an issuer entry to every open card of the bank (only those
with an "up to" offer when `only_up_to_offers` is set). A card's own entry wins.
"""

import yaml
from card_rules.catalog import CatalogCard, Referral

from scout.annotate import SEED

REFERRALS_PATH = SEED / "referrals.yaml"


class ReferralError(ValueError):
    pass


def stamp(cards: list[CatalogCard], path=REFERRALS_PATH) -> list[CatalogCard]:
    data = yaml.safe_load(path.read_text()) or {}
    by_card = {k: Referral.model_validate(v) for k, v in (data.get("cards") or {}).items()}
    by_issuer = {}
    for issuer, entry in (data.get("issuers") or {}).items():
        entry = dict(entry)
        only_up_to = entry.pop("only_up_to_offers", False)
        by_issuer[issuer] = (Referral.model_validate(entry), only_up_to)
    unknown = sorted(set(by_card) - {c.id for c in cards})
    if unknown:
        raise ReferralError(f"referrals.yaml names cards not in the catalog: {', '.join(unknown)}")

    def referral(card: CatalogCard) -> Referral | None:
        if card.id in by_card:
            return by_card[card.id]
        if card.availability != "open" or card.issuer_id not in by_issuer:
            return None
        found, only_up_to = by_issuer[card.issuer_id]
        if only_up_to and not (card.offer and card.offer.amount_is_up_to):
            return None
        return found

    return [c.model_copy(update={"referral": referral(c)}) for c in cards]
