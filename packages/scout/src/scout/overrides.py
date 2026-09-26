"""Human-verified corrections that win over any extraction (ADR 0002).

Without this, a value a person corrected would be overwritten by the next model run, e.g. Hilton
Surpass's "$0 first year" (present in the HTML, never shown to visitors) would keep coming back.
Overrides are applied when a catalog file is written, not when snapshots are built, so
cross-model comparison still measures what the models actually extracted.
"""

import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from card_rules.catalog import CatalogCard, Credit, EarningRate, Offer
from pydantic import BaseModel

from scout.seed import REPO_ROOT

OVERRIDES_PATH = REPO_ROOT / "catalog" / "seed" / "overrides.yaml"


# List fields that "add" can append to, and the model each item must satisfy.
_LIST_ITEMS = {"credits": Credit, "earning_rates": EarningRate}


class Override(BaseModel):
    card_id: str
    field: str  # a CatalogCard field, or "offer.<field>"
    # set: replace the field's value. add: append one item to a list field (credits,
    # earning_rates), replacing an existing item with the same description/category. "add" never
    # depends on list positions, which change whenever a card is re-extracted.
    op: Literal["set", "add"] = "set"
    # add only: a regex (case-insensitive) for the extracted item this correction supersedes,
    # when the model words the same perk differently ("food, beverages and Wi-Fi on United").
    match: str | None = None
    value: Any
    reason: str
    verified_by: str
    verified_on: date


def load(path: Path = OVERRIDES_PATH) -> list[Override]:
    if not path.exists():
        return []
    return [Override.model_validate(o) for o in yaml.safe_load(path.read_text()) or []]


def _check(card_id: str, field: str, op: str) -> None:
    if op == "add":
        if field not in _LIST_ITEMS:
            raise ValueError(f"{card_id}: 'add' only applies to {sorted(_LIST_ITEMS)}")
        return
    if field.startswith("offer."):
        ok = field.removeprefix("offer.") in Offer.model_fields
    else:
        ok = field in CatalogCard.model_fields
    if not ok:
        raise ValueError(f"{card_id}: unknown field {field!r}")


def _get(card: CatalogCard, field: str) -> Any:
    if field.startswith("offer."):
        return getattr(card.offer, field.removeprefix("offer."), None) if card.offer else None
    return getattr(card, field)


def _set(card: CatalogCard, field: str, value: Any) -> CatalogCard:
    """Replace a value with full validation (model_copy alone would skip it and let a malformed
    override reach the catalog)."""
    if field.startswith("offer."):
        if card.offer is None:
            raise ValueError(f"{card.id}: cannot override {field}, the card has no offer")
        offer = Offer.model_validate(
            card.offer.model_dump() | {field.removeprefix("offer."): value}
        )
        return card.model_copy(update={"offer": offer})
    validated = CatalogCard.model_validate(card.model_dump() | {field: value})
    return card.model_copy(update={field: getattr(validated, field)})


def _item_key(field: str, item: Any) -> str:
    return item.description if field == "credits" else item.category


def _add(
    card: CatalogCard, field: str, value: Any, match: str | None = None
) -> tuple[CatalogCard, str]:
    item = _LIST_ITEMS[field].model_validate(value)
    key = _item_key(field, item)
    items = list(getattr(card, field))
    existing = [
        i
        for i, x in enumerate(items)
        if _item_key(field, x) == key or (match and re.search(match, _item_key(field, x), re.I))
    ]
    if existing:
        verb = f"replaced {_item_key(field, items[existing[0]])!r} with"
        items[existing[0]] = item
        for i in reversed(existing[1:]):
            del items[i]
    else:
        items.append(item)
        verb = "added"
    return card.model_copy(update={field: items}), f"{verb} {field[:-1]} {key!r}"


def apply(
    cards: list[CatalogCard], overrides: list[Override]
) -> tuple[list[CatalogCard], list[str]]:
    """Apply overrides last (highest precedence). Returns the cards and notes that say, for each
    override, whether it changed an extracted value or now just matches it (maybe stale)."""
    by_id = {c.id: c for c in cards}
    notes = []
    for o in overrides:
        card = by_id.get(o.card_id)
        if card is None:
            notes.append(f"override for {o.card_id}.{o.field}: card not in this catalog")
            continue
        _check(o.card_id, o.field, o.op)
        if o.op == "add":
            card, what = _add(card, o.field, o.value, o.match)
            key = f"{o.field}:{_item_key(o.field, _LIST_ITEMS[o.field].model_validate(o.value))}"
            card = card.model_copy(
                update={"manually_verified": {**card.manually_verified, key: o.verified_on}}
            )
            by_id[o.card_id] = card
            notes.append(f"{o.card_id}: override {what}")
            continue
        before = _get(card, o.field)
        card = _set(card, o.field, o.value)
        card = card.model_copy(
            update={"manually_verified": {**card.manually_verified, o.field: o.verified_on}}
        )
        by_id[o.card_id] = card
        if before == o.value:
            notes.append(f"{o.card_id}.{o.field}: override matches extraction ({o.value!r})")
        else:
            notes.append(f"{o.card_id}.{o.field}: override replaced {before!r} with {o.value!r}")
    return [by_id[c.id] for c in cards], notes
