from card_rules import load_rules
from card_rules.explain import explain


def by_id():
    return {r.id: r for r in load_rules()}


def test_every_rule_can_be_explained():
    for rule in load_rules():
        facts = explain(rule)
        assert facts["how_it_counts"] and facts["summary"] and facts["source_url"]


def test_5_24_says_closed_cards_and_every_bank_count():
    facts = explain(by_id()["chase_5_24"])
    text = " ".join(facts["how_it_counts"])
    assert facts["decides"] == "approval"
    assert "from any bank" in text and "in the last 24 months" in text
    assert "closing it does not remove it" in text
    assert "Authorized-user cards count." in text and "Business cards do not count." in text


def test_amex_ladder_names_the_cards_it_looks_at():
    facts = explain(by_id()["amex_ladder_gold"], {"amex_platinum": "The Platinum Card"})
    text = " ".join(facts["how_it_counts"])
    assert facts["decides"] == "welcome offer"
    assert "The Platinum Card" in text
