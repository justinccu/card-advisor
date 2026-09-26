"""Cross-model agreement: where two independent extractions of the same pages agree, the value is
very likely right; where they disagree is where a human's review time is best spent (ADR 0002).

Both sides are compared in catalog shape (CatalogCard). Free-text fields (category and credit
descriptions) are compared by their numbers only, since two models word the same perk differently.
"""

from dataclasses import dataclass

from card_rules.catalog import CatalogCard, CatalogSnapshot

SCALAR_FIELDS = [
    "annual_fee_usd",
    "first_year_annual_fee_usd",
    "foreign_transaction_fee_pct",
    "network",
]
OFFER_FIELDS = ["amount_disclosed", "amount", "unit", "min_spend_usd", "spend_window_months"]


@dataclass
class Diff:
    card_id: str
    field: str
    a: object
    b: object


def _norm(v: object) -> object:
    if isinstance(v, str):
        return v.strip().lower()
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _rates(card: CatalogCard) -> list[tuple]:
    # -1 = "no cap": keeps capped and uncapped rates sortable together
    return sorted(
        (_norm(r.rate), r.unit, r.cap_usd if r.cap_usd is not None else -1)
        for r in card.earning_rates
    )


def _credits(card: CatalogCard) -> list[tuple]:
    return sorted(
        ((c.amount_usd if c.amount_usd is not None else -1), c.period) for c in card.credits
    )


def fields_of(card: CatalogCard) -> dict[str, object]:
    out: dict[str, object] = {f: _norm(getattr(card, f)) for f in SCALAR_FIELDS}
    for f in OFFER_FIELDS:
        out[f"offer.{f}"] = _norm(getattr(card.offer, f)) if card.offer else None
    out["earning_rates"] = _rates(card)
    out["credits"] = _credits(card)
    return out


def compare_cards(a: CatalogCard, b: CatalogCard) -> list[Diff]:
    fa, fb = fields_of(a), fields_of(b)
    return [Diff(a.id, k, fa[k], fb[k]) for k in fa if fa[k] != fb[k]]


@dataclass
class Report:
    compared: int
    fields_total: int
    diffs: list[Diff]
    only_in_a: list[str]
    only_in_b: list[str]

    @property
    def agreement(self) -> float:
        return 1 - len(self.diffs) / self.fields_total if self.fields_total else 0.0


def compare(a: CatalogSnapshot, b: CatalogSnapshot) -> Report:
    ia = {c.id: c for c in a.cards if c.availability == "open"}
    ib = {c.id: c for c in b.cards if c.availability == "open"}
    shared = sorted(ia.keys() & ib.keys())
    diffs = [d for cid in shared for d in compare_cards(ia[cid], ib[cid])]
    per_card = len(SCALAR_FIELDS) + len(OFFER_FIELDS) + 2
    return Report(
        compared=len(shared),
        fields_total=len(shared) * per_card,
        diffs=diffs,
        only_in_a=sorted(ia.keys() - ib.keys()),
        only_in_b=sorted(ib.keys() - ia.keys()),
    )
