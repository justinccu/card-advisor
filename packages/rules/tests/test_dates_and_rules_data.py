from datetime import date

import pytest
from card_rules import load_rules
from card_rules.dates import add_months, window_start
from card_rules.models import OfferHistoryRule, VelocityRule

KNOWN_ISSUERS = {
    "chase",
    "amex",
    "citi",
    "capital_one",
    "discover",
    "bofa",
    "wells_fargo",
    "us_bank",
}


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2024, 2, 29), 12, date(2025, 2, 28)),
        (date(2026, 9, 24), -24, date(2024, 9, 24)),
        (date(2026, 1, 15), -1, date(2025, 12, 15)),
    ],
)
def test_add_months_clamps_to_month_end(start, months, expected):
    assert add_months(start, months) == expected


def test_window_start_requires_exactly_one_unit():
    with pytest.raises(ValueError):
        window_start(date(2026, 1, 1))
    with pytest.raises(ValueError):
        window_start(date(2026, 1, 1), months=1, days=1)


def test_every_rule_is_sourced_and_well_formed():
    rules = load_rules()
    assert rules
    for rule in rules:
        assert rule.issuer_id in KNOWN_ISSUERS, rule.id
        assert rule.source_url and rule.verified_on, rule.id
        if isinstance(rule, VelocityRule):
            assert (rule.window_months is None) != (rule.window_days is None), rule.id
        if isinstance(rule, OfferHistoryRule) and rule.target == "family":
            assert rule.family, rule.id
