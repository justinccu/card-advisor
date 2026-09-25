"""Grounding check: every extracted value must quote text that is actually on the page."""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from scout.schema import ExtractedCard

_MARKS = str.maketrans({"®": "", "™": "", "℠": "", "‘": "'", "’": "'", "“": '"', "”": '"'})
_DASHES = re.compile(r"[‐-―−]")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_MARKS)
    text = _DASHES.sub("-", text)
    return re.sub(r"\s+", " ", text).strip().lower()


@dataclass
class FieldCheck:
    path: str
    value: Any
    evidence: str | None
    status: str  # "verified" | "unverified" | "missing_evidence" | "empty"


def _check(path: str, value: Any, evidence: str | None, page: str) -> FieldCheck:
    if value is None:
        return FieldCheck(path, None, evidence, "empty")
    if not evidence:
        return FieldCheck(path, value, None, "missing_evidence")
    status = "verified" if normalize(evidence) in page else "unverified"
    return FieldCheck(path, value, evidence, status)


def check_card(card: ExtractedCard, page_text: str) -> list[FieldCheck]:
    page = normalize(page_text)
    checks = [
        _check(name, getattr(card, name).value, getattr(card, name).evidence, page)
        for name in (
            "annual_fee_usd",
            "first_year_annual_fee_usd",
            "foreign_transaction_fee_pct",
            "network",
            "accepts_itin",
        )
    ]
    if card.offer:
        for name in ("amount", "min_spend_usd", "spend_window_months"):
            sourced = getattr(card.offer, name)
            checks.append(_check(f"offer.{name}", sourced.value, sourced.evidence, page))
    for i, rate in enumerate(card.earning_rates):
        label = f"{rate.rate:g} {rate.unit} on {rate.category}"
        checks.append(_check(f"earning_rates[{i}]", label, rate.evidence, page))
    for i, credit in enumerate(card.credits):
        label = f"${credit.amount_usd} / {credit.period}: {credit.description}"
        checks.append(_check(f"credits[{i}]", label, credit.evidence, page))
    return checks
