from datetime import date

import pytest
from card_rules.catalog import CatalogCard, Credit, EarningRate, Offer, Valuation
from card_rules.models import Evaluation, Reason, Status, Verdict
from card_rules.ranking import RankOptions, SpendingProfile, annual_rewards, rank

AS_OF = date(2026, 9, 28)
VALUATIONS = {
    "bank": Valuation(name="Bank points", cents=1.0, basis="cash"),
    "hotel": Valuation(name="Hotel points", cents=0.5, basis="floor", free_night_points=50000),
}


def rate(r, unit="percent_cash_back", spend=("everything_else",), **kw):
    return EarningRate(category=kw.pop("category", "x"), rate=r, unit=unit, spend=list(spend), **kw)


def card(id_, rates, **kw):
    return CatalogCard(
        id=id_,
        issuer_id=kw.pop("issuer_id", "bank"),
        name=id_,
        url="https://x",
        earning_rates=rates,
        **kw,
    )


def verdict(status=Status.ELIGIBLE, reasons=()):
    return Verdict(status=status, reasons=list(reasons))


def ok(*cards, offer=Status.ELIGIBLE):
    return {
        c.id: Evaluation(
            card_product_id=c.id, as_of=AS_OF, application=verdict(), offer=verdict(offer)
        )
        for c in cards
    }


def spend(**monthly):
    return SpendingProfile(monthly_usd=monthly)


# --- rewards --------------------------------------------------------------------------


def test_flat_cash_back_earns_on_all_spend():
    c = card("flat", [rate(2)])
    assert annual_rewards(c, None, {"dining": 100, "everything_else": 400}, set())[0] == 120.0


def test_points_use_the_conservative_valuation():
    c = card("pts", [rate(3, "x_points", ["dining"]), rate(1, "x_points")], currency="bank")
    # 3x at 1¢ on $1,200 dining = $36, 1x at 1¢ on $2,400 other = $24
    assert annual_rewards(c, 1.0, {"dining": 100, "everything_else": 200}, set())[0] == 60.0


def test_a_cap_is_shared_by_a_rates_categories_and_the_rest_earns_base():
    # 6% on groceries + gas up to $6,000 a year combined, then 1%
    c = card(
        "capped",
        [rate(6, spend=["groceries", "gas_ev"], cap_usd=6000, cap_period="calendar_year"), rate(1)],
    )
    rewards, _ = annual_rewards(c, None, {"groceries": 400, "gas_ev": 200}, set())
    # $7,200 eligible: $6,000 at 6% = $360, $1,200 at 1% = $12
    assert rewards == 372.0


def test_conditional_rates_count_only_when_opted_in_and_are_listed_otherwise():
    portal = rate(5, spend=["flights", "hotels"], when="portal", category="Chase Travel")
    brand = rate(4, spend=["flights"], when="brand", brand="delta", category="Delta")
    c = card("travel", [portal, brand, rate(1)], issuer_id="chase")
    monthly = {"flights": 100}
    plain, listed = annual_rewards(c, None, monthly, set())
    assert plain == 12.0 and len(listed) == 2
    assert annual_rewards(c, None, monthly, {"brand:delta"})[0] == 48.0
    assert annual_rewards(c, None, monthly, {"portal:chase"})[0] == 60.0  # best counted rate wins


def test_choice_and_relationship_rates_are_never_counted_in_v1():
    c = card("choice", [rate(3, spend=[], when="choice"), rate(4, when="relationship"), rate(1)])
    assert annual_rewards(c, None, {"dining": 100}, {"choice", "relationship"})[0] == 12.0


# --- offer, credits, fees -------------------------------------------------------------


def offer(**kw):
    return Offer(amount_disclosed=True, min_spend_usd=None, spend_window_months=None, **kw)


def test_first_year_and_ongoing_values_add_up():
    c = card(
        "csp",
        [rate(1, "x_points")],
        currency="bank",
        annual_fee_usd=95,
        offer=offer(amount=60000, unit="points", statement_credit_usd=50),
        credits=[
            Credit(description="Hotel credit", amount_usd=50, period="calendar_year"),
            Credit(description="Welcome gift", amount_usd=100, period="one_time"),
        ],
    )
    opts = RankOptions(credits={"csp": ["Hotel credit", "Welcome gift"]})
    r = rank([c], VALUATIONS, spend(everything_else=1000), ok(c), opts).cards[0]
    # offer $600 + $50, rewards $120, credits $150 first year / $50 ongoing, fee $95
    assert r.first_year_value_usd == 650 + 120 + 150 - 95
    assert r.ongoing_value_usd == 120 + 50 - 95


def test_credits_count_only_when_confirmed():
    c = card(
        "amex",
        [rate(1)],
        annual_fee_usd=0,
        credits=[Credit(description="Dining", amount_usd=10, period="month")],
    )
    assert rank([c], VALUATIONS, spend(), ok(c)).cards[0].breakdown.credits_ongoing_usd == 0
    confirmed = RankOptions(credits={"amex": ["Dining"]})
    assert (
        rank([c], VALUATIONS, spend(), ok(c), confirmed).cards[0].breakdown.credits_ongoing_usd
        == 120
    )


def test_an_offer_the_user_cant_earn_is_not_counted():
    c = card("gold", [rate(1)], offer=offer(amount=500, unit="usd"))
    r = rank([c], VALUATIONS, spend(), ok(c, offer=Status.INELIGIBLE)).cards[0]
    assert r.breakdown.offer_usd == 0 and not r.offer_counted
    assert any("may not earn" in n for n in r.notes)


def test_offer_units():
    nights = card(
        "boundless",
        [rate(1, "x_points")],
        currency="hotel",
        offer=offer(amount=3, unit="free_nights"),
    )
    match = card("discover", [rate(1)], offer=offer(amount=None, unit="cashback_match"))
    up_to = card("ceiling", [rate(1)], offer=offer(amount=300, unit="usd", amount_is_up_to=True))
    r = {
        x.card_id: x
        for x in rank(
            [nights, match, up_to],
            VALUATIONS,
            spend(everything_else=1000),
            ok(nights, match, up_to),
        ).cards
    }
    assert r["boundless"].breakdown.offer_usd == 3 * 50000 * 0.5 / 100
    assert r["discover"].breakdown.offer_usd == 120.0  # matches the first year's cash back
    assert r["ceiling"].offer_is_up_to and any("up to" in n for n in r["ceiling"].notes)


def test_first_year_fee_waiver_and_min_spend_gap():
    c = card(
        "waived",
        [rate(2)],
        annual_fee_usd=150,
        first_year_annual_fee_usd=0,
        offer=offer(amount=200, unit="usd").model_copy(
            update={"min_spend_usd": 3000, "spend_window_months": 3}
        ),
    )
    r = rank([c], VALUATIONS, spend(everything_else=500), ok(c)).cards[0]
    assert r.breakdown.first_year_fee_usd == 0 and r.breakdown.annual_fee_usd == 150
    assert r.min_spend_gap_usd == 1500  # $3,000 needed, $1,500 usual in 3 months


# --- filtering and order --------------------------------------------------------------


def test_ineligible_applications_are_excluded_with_the_retry_date():
    c = card("csr", [rate(1)])
    blocked = Reason(
        rule_id="chase_5_24",
        status=Status.INELIGIBLE,
        message="5/24",
        confidence="official",
        retry_after=date(2027, 3, 1),
    )
    ev = {
        "csr": Evaluation(
            card_product_id="csr",
            as_of=AS_OF,
            application=verdict(Status.INELIGIBLE, [blocked]),
            offer=verdict(),
        )
    }
    ranking = rank([c], VALUATIONS, spend(), ev)
    assert ranking.cards == [] and ranking.excluded[0].retry_after == "2027-03-01"


def test_undetermined_cards_stay_ranked_with_what_is_missing():
    c = card("maybe", [rate(1)])
    unsure = Reason(
        rule_id="tax_id",
        status=Status.UNDETERMINED,
        message="Need the tax ID",
        confidence="official",
    )
    ev = {
        "maybe": Evaluation(
            card_product_id="maybe",
            as_of=AS_OF,
            application=verdict(Status.UNDETERMINED, [unsure]),
            offer=verdict(),
        )
    }
    r = rank([c], VALUATIONS, spend(), ev).cards[0]
    assert "Undetermined: Need the tax ID" in r.notes


def test_fee_ceiling_business_and_starter_filters():
    pricey = card("pricey", [rate(3)], annual_fee_usd=695)
    biz = card("ink", [rate(2)], is_business=True)
    starter = card("secured", [rate(1)], tags=["secured"])
    cards = [pricey, biz, starter]
    base = SpendingProfile(monthly_usd={"everything_else": 100}, max_annual_fee_usd=100)
    r = rank(cards, VALUATIONS, base, ok(*cards))
    assert [c.card_id for c in r.cards] == ["secured"] and r.excluded[0].card_id == "pricey"
    with_biz = rank(cards, VALUATIONS, base.model_copy(update={"wants_business": True}), ok(*cards))
    assert "ink" in [c.card_id for c in with_biz.cards]
    starters = rank(
        cards, VALUATIONS, base.model_copy(update={"goals": ["build_credit"]}), ok(*cards)
    )
    assert [c.card_id for c in starters.cards] == ["secured"]


@pytest.mark.parametrize("goal,first", [("earn_offers", "bonus"), ("long_term", "keeper")])
def test_order_follows_the_goal(goal, first):
    bonus = card("bonus", [rate(1)], offer=offer(amount=500, unit="usd"))
    keeper = card("keeper", [rate(3)])
    profile = SpendingProfile(monthly_usd={"everything_else": 500}, goals=[goal])
    r = rank([bonus, keeper], VALUATIONS, profile, ok(bonus, keeper))
    assert r.cards[0].card_id == first
    assert r.sort_by == ("first_year" if goal == "earn_offers" else "ongoing")


def test_a_conversation_scenario_overrides_only_what_it_mentions():
    from card_rules.ranking import SpendingScenario

    saved = SpendingProfile(
        monthly_usd={"dining": 300, "groceries": 400}, goals=["long_term"], max_annual_fee_usd=100
    )
    what_if = SpendingScenario(monthly_usd={"dining": 800, "groceries": 0}, goals=["earn_offers"])
    used = what_if.apply(saved)
    assert used.monthly_usd == {"dining": 800}  # dining replaced, groceries removed by 0
    assert used.goals == ["earn_offers"] and used.max_annual_fee_usd == 100  # fee limit kept
    assert SpendingScenario(no_fee_limit=True).apply(saved).max_annual_fee_usd is None
    assert saved.monthly_usd == {"dining": 300, "groceries": 400}  # the saved profile is untouched
    # works with no saved profile at all (a first chat)
    assert SpendingScenario(monthly_usd={"flights": 200}).apply(None).monthly_usd == {
        "flights": 200
    }


def test_each_card_says_where_its_rewards_come_from_and_its_rank():
    c = card(
        "csp",
        [rate(3, "x_points", ["dining"], category="dining"), rate(1, "x_points", category="other")],
        currency="bank",
    )
    r = rank([c], VALUATIONS, spend(dining=100, everything_else=200), ok(c)).cards[0]
    assert r.rank == 1
    assert [(e.category, e.rate, e.usd) for e in r.earnings] == [
        ("everything_else", "1x points", 24.0),
        ("dining", "3x points", 36.0),
    ][::-1]  # biggest first
    assert sum(e.usd for e in r.earnings) == r.breakdown.rewards_usd
