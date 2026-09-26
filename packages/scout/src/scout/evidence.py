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
    # "verified": the quote is on the page verbatim.
    # "approximate": the quote's words appear on the page in order, with a few words the model
    #   elided in between ("AS HIGH AS 100,000 [Membership Rewards] points").
    # "unverified": neither; "missing_evidence": a value without a quote; "empty": no value.
    # "value_not_in_quote": the quote is on the page but doesn't contain the extracted number
    #   (e.g. value 80,000 quoting "Earn 75,000 points").
    status: str


# Numeric fields whose number must appear in the quote itself, not just somewhere on the page.
NUMBER_IN_QUOTE = {
    "annual_fee_usd",
    "first_year_annual_fee_usd",
    "offer.amount",
    "offer.min_spend_usd",
    "offer.statement_credit_usd",
}
# "No annual fee", "No annual credit card fee", "$0 intro annual fee", "waived for the first year".
_NO_FEE = re.compile(r"\bno\b[\w\s-]{0,25}\bfee\b|\$0\b|\bwaived\b")


def _number_in_quote(value: float, quote: str) -> bool:
    text = normalize(quote)
    if value == 0 and _NO_FEE.search(text):
        return True
    numbers = {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}
    return float(value) in numbers


_WORD = re.compile(r"[a-z0-9]+")
MAX_ELIDED_WORDS = 6  # per gap between consecutive quote words


def _approximate(quote: str, page_words: list[str]) -> bool:
    """Whether the quote's words occur in order on the page, each within a few words of the last."""
    words = _WORD.findall(normalize(quote))
    if len(words) < 3:
        return False
    for start in (i for i, w in enumerate(page_words) if w == words[0]):
        pos, ok = start, True
        for w in words[1:]:
            window = page_words[pos + 1 : pos + 2 + MAX_ELIDED_WORDS]
            if w not in window:
                ok = False
                break
            pos = pos + 1 + window.index(w)
        if ok:
            return True
    return False


def _check(
    path: str, value: Any, evidence: str | None, page: str, page_words: list[str] | None = None
) -> FieldCheck:
    if value is None:
        return FieldCheck(path, None, evidence, "empty")
    if not evidence:
        return FieldCheck(path, value, None, "missing_evidence")
    if normalize(evidence) in page:
        status = "verified"
    else:
        words = page_words if page_words is not None else _WORD.findall(page)
        status = "approximate" if _approximate(evidence, words) else "unverified"
    if (
        status != "unverified"
        and path in NUMBER_IN_QUOTE
        and isinstance(value, int | float)
        and not _number_in_quote(value, evidence)
    ):
        status = "value_not_in_quote"
    return FieldCheck(path, value, evidence, status)


def check_card(card: ExtractedCard, page_text: str) -> list[FieldCheck]:
    page = normalize(page_text)
    page_words = _WORD.findall(page)

    checks = [
        _check(name, getattr(card, name).value, getattr(card, name).evidence, page, page_words)
        for name in (
            "annual_fee_usd",
            "first_year_annual_fee_usd",
            "foreign_transaction_fee_pct",
            "network",
            "accepts_itin",
        )
    ]
    if card.offer:
        for name in (
            "amount",
            "min_spend_usd",
            "spend_window_months",
            "statement_credit_usd",
            "ends_on",
        ):
            sourced = getattr(card.offer, name)
            checks.append(
                _check(f"offer.{name}", sourced.value, sourced.evidence, page, page_words)
            )
    for i, rate in enumerate(card.earning_rates):
        label = f"{rate.rate:g} {rate.unit} on {rate.category}"
        checks.append(_check(f"earning_rates[{i}]", label, rate.evidence, page, page_words))
    for i, credit in enumerate(card.credits):
        amount = (
            f"${credit.amount_usd}"
            if credit.amount_usd is not None
            else f"{credit.percent:g}%"
            if credit.percent is not None
            else "perk"
        )
        label = f"{amount} / {credit.period}: {credit.description}"
        checks.append(_check(f"credits[{i}]", label, credit.evidence, page, page_words))
    return checks
