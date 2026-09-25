"""Build the next Catalog Snapshot from approved reviews (ADR 0002, 0003).

Snapshots are immutable: a new version is written only when content actually changed.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from card_rules.catalog import CatalogCard, CatalogSnapshot, Credit, EarningRate, Offer
from card_rules.models import Market, TaxId

from scout.seed import REPO_ROOT, SeedCard

CATALOG_DIR = REPO_ROOT / "catalog" / "us"


def _card(seed: SeedCard, review: dict | None) -> CatalogCard:
    base = {
        "id": seed.id,
        "issuer_id": seed.issuer_id,
        "name": seed.name,
        "market": Market.US,
        "family": seed.family,
        "is_business": seed.is_business,
        "is_charge_card": seed.is_charge_card,
        "url": seed.url,
        "availability": seed.availability,
        "closed_on": seed.closed_on,
        "tags": seed.tags,
    }
    if review is None:  # closed card kept for Held Card selection only
        return CatalogCard(**base)

    x = review["final"]
    offer = x.get("offer")
    itin = x["accepts_itin"]["value"] is True
    return CatalogCard(
        **base,
        # Only an explicit ITIN statement widens eligibility; silence stays SSN-only (conservative).
        accepted_tax_ids=frozenset({TaxId.SSN, TaxId.ITIN} if itin else {TaxId.SSN}),
        annual_fee_usd=x["annual_fee_usd"]["value"],
        first_year_annual_fee_usd=x["first_year_annual_fee_usd"]["value"],
        foreign_transaction_fee_pct=x["foreign_transaction_fee_pct"]["value"],
        network=x["network"]["value"],
        offer=Offer(
            amount_disclosed=offer["amount_disclosed"],
            amount=offer["amount"]["value"],
            unit=offer["unit"],
            min_spend_usd=offer["min_spend_usd"]["value"],
            spend_window_months=offer["spend_window_months"]["value"],
        )
        if offer
        else None,
        earning_rates=[
            EarningRate(**{k: v for k, v in r.items() if k != "evidence"})
            for r in x["earning_rates"]
        ],
        credits=[Credit(**{k: v for k, v in c.items() if k != "evidence"}) for c in x["credits"]],
        notes=x.get("reviewer_notes", ""),
        verified_at=review["reviewed_at"],
        content_hash=review["content_hash"],
    )


def build(seeds: list[SeedCard], reviews: dict[str, dict]) -> list[CatalogCard]:
    cards = []
    for seed in seeds:
        review = reviews.get(seed.id)
        if review and review["decision"] == "approved":
            cards.append(_card(seed, review))
        elif seed.availability == "closed_to_new_applicants":
            cards.append(_card(seed, None))
    return cards


def _digest(cards: list[CatalogCard]) -> str:
    payload = json.dumps([c.model_dump(mode="json") for c in cards], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def latest(catalog_dir: Path = CATALOG_DIR) -> tuple[int, CatalogSnapshot | None]:
    versions = sorted(int(p.stem[1:]) for p in catalog_dir.glob("v*.json"))
    if not versions:
        return 0, None
    v = versions[-1]
    return v, CatalogSnapshot.model_validate_json((catalog_dir / f"v{v}.json").read_text())


def publish(cards: list[CatalogCard], catalog_dir: Path = CATALOG_DIR) -> Path | None:
    """Write v{N+1}.json if the catalog changed; return its path, or None if unchanged."""
    version, previous = latest(catalog_dir)
    if previous is not None and _digest(previous.cards) == _digest(cards):
        return None
    snapshot = CatalogSnapshot(
        version=version + 1, market=Market.US, generated_at=datetime.now(UTC), cards=cards
    )
    catalog_dir.mkdir(parents=True, exist_ok=True)
    path = catalog_dir / f"v{snapshot.version}.json"
    path.write_text(snapshot.model_dump_json(indent=2))
    return path
