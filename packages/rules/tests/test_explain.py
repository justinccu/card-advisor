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


def test_bonus_windows_say_when_they_start():
    # The Advisor once said every Citi window counts from the opening date; the 48 months
    # count from the bonus.
    facts = " ".join(explain(by_id()["citi_48_month_bonus"])["how_it_counts"])
    assert "count from when that bonus was earned, not from when a card was opened" in facts


def test_sapphire_rules_say_may_where_the_terms_do_and_name_the_exceptions():
    rules = by_id()
    names = {
        "chase_sapphire_preferred": "Chase Sapphire Preferred",
        "chase_sapphire_reserve": "Chase Sapphire Reserve",
    }
    other = explain(rules["chase_sapphire_other_open"])
    assert other["how_it_counts"][0].startswith("The welcome offer may not be given")
    assert other["enforcement"].startswith("soft")
    assert explain(rules["chase_sapphire_one_open"])["decides"] == "approval"
    months = explain(rules["chase_24_month_bonus"], names)["how_it_counts"][-1]
    assert months == (
        "Doesn't apply to Chase Sapphire Preferred and Chase Sapphire Reserve, "
        "which have stricter rules of their own."
    )
