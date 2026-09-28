"""Stamp ranking inputs onto cards at publish time (ADR 0009).

The reviewed seed tables (catalog/seed/earning_categories.yaml, reward_currencies.yaml) are
copied into the Catalog Snapshot, so ranking reads one immutable, versioned file and a
Recommendation can be replayed exactly, even after the tables change.
Publishing refuses to guess: every rate on an open card needs a reviewed mapping, and every
points/miles card needs a currency.
"""

from pathlib import Path

import yaml
from card_rules.catalog import CatalogCard, Valuation

from scout.seed import REPO_ROOT

SEED = REPO_ROOT / "catalog" / "seed"
CATEGORIES_PATH = SEED / "earning_categories.yaml"
CURRENCIES_PATH = SEED / "reward_currencies.yaml"


class AnnotationError(ValueError):
    pass


def _needs_currency(card: CatalogCard) -> bool:
    units = {r.unit for r in card.earning_rates} | ({card.offer.unit} if card.offer else set())
    return bool(units & {"x_points", "x_miles", "points", "miles", "free_nights"})


def annotate(
    cards: list[CatalogCard],
    categories_path: Path = CATEGORIES_PATH,
    currencies_path: Path = CURRENCIES_PATH,
) -> tuple[list[CatalogCard], dict[str, Valuation]]:
    mapping = yaml.safe_load(categories_path.read_text())["cards"]
    table = yaml.safe_load(currencies_path.read_text())
    valuations = {
        key: Valuation.model_validate({k: v for k, v in c.items() if k in Valuation.model_fields})
        for key, c in table["currencies"].items()
        if c.get("status") == "reviewed"
    }
    problems: list[str] = []
    out: list[CatalogCard] = []
    for card in cards:
        if card.availability != "open":
            out.append(card)
            continue
        entries = {e["text"]: e for e in mapping.get(card.id, [])}
        rates = []
        for rate in card.earning_rates:
            e = entries.get(rate.category.strip())
            if e is None or e.get("status") != "reviewed":
                problems.append(f"{card.id}: no reviewed mapping for rate {rate.category!r}")
                rates.append(rate)
                continue
            rates.append(
                rate.model_copy(
                    update={
                        "spend": e.get("spend", []),
                        "when": e.get("when"),
                        "brand": e.get("brand"),
                    }
                )
            )
        currency = table["cards"].get(card.id)
        if _needs_currency(card) and currency not in valuations:
            problems.append(f"{card.id}: earns points/miles but has no reviewed currency")
        out.append(card.model_copy(update={"earning_rates": rates, "currency": currency}))
    if problems:
        raise AnnotationError(
            "cannot publish: \n  "
            + "\n  ".join(problems)
            + "\n(run scripts/draft_earning_categories.py, review, set status: reviewed)"
        )
    return out, valuations
