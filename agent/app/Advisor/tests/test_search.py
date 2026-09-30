"""Card search by what people call a card (advisor.search; the site's lib/search.ts matches)."""

import pytest
from advisor.search import find, matches, words

ISSUERS = {
    "amex": {"name": "American Express", "aliases": ["Amex"]},
    "chase": {"name": "Chase", "aliases": []},
    "citi": {"name": "Citi", "aliases": ["Citibank"]},
}


def card(id_, issuer, name, aliases=()):
    return {"id": id_, "issuer_id": issuer, "name": name, "aliases": list(aliases)}


CARDS = {
    c["id"]: c
    for c in [
        card("amex_gold", "amex", "American Express Gold Card", ["Amex Gold"]),
        card("amex_business_gold", "amex", "American Express Business Gold"),
        card("amex_platinum", "amex", "The Platinum Card", ["Amex Plat"]),
        card("amex_green", "amex", "American Express Green Card"),
        card("chase_sapphire_preferred", "chase", "Chase Sapphire Preferred", ["CSP"]),
        card("chase_sapphire_reserve", "chase", "Chase Sapphire Reserve", ["CSR"]),
        card("citi_secured", "citi", "Citi Secured Mastercard"),
    ]
}


@pytest.mark.parametrize(
    "query,kind,ids",
    [
        ("amex gold", "one", ["amex_gold"]),
        ("American Express Gold Card", "one", ["amex_gold"]),
        ("CSP", "one", ["chase_sapphire_preferred"]),  # an alias
        ("saphire preferred", "one", ["chase_sapphire_preferred"]),  # a typo
        ("amex plat", "one", ["amex_platinum"]),  # a prefix
        ("amex green card for travel", "one", ["amex_green"]),  # an extra word
        ("chase sapphire", "several", ["chase_sapphire_preferred", "chase_sapphire_reserve"]),
        ("bilt gold", "closest", ["amex_gold", "amex_business_gold"]),  # never taken as meant
        ("Bilt Mastercard", "none", []),  # networks don't match cards
        ("amex_gold", "one", ["amex_gold"]),  # an id
    ],
)
def test_cards_are_found_by_what_people_call_them(query, kind, ids):
    found_kind, found = find(query, CARDS, ISSUERS)
    assert (found_kind, [c["id"] for c in found]) == (kind, ids)


@pytest.mark.parametrize("bank", ["Amex", "American Express", "american express", "AMEX"])
def test_a_bank_by_either_name_lists_its_cards(bank):
    kind, found = find(bank, CARDS, ISSUERS)
    assert kind == "several"
    assert {c["id"] for c in found} == {
        "amex_gold",
        "amex_business_gold",
        "amex_platinum",
        "amex_green",
    }


def test_typo_tolerance_grows_with_word_length():
    assert matches("saphire", "sapphire") and matches("platnum", "platinum")
    assert not matches("gld", "gold")  # short words must match exactly or as a prefix
    assert matches("preffered", "preferred")  # two letters off in a long word
    assert words("U.S. Bank Cash+") == ["u", "s", "bank", "cash", "plus"]
