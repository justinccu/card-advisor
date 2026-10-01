import json

import httpx
from advisor.api import AdvisorApi, QuotaExceeded
from advisor.tools import build_tools, compact_card, compact_profile

CARD = {
    "id": "amex_gold",
    "name": "Amex Gold",
    "issuer_id": "amex",
    "annual_fee_usd": 325,
    "availability": "open",
    "url": "https://issuer.example/gold",
    "offer": {"amount": 100000, "unit": "points", "amount_is_up_to": True, "min_spend_usd": 8000},
    "earning_rates": [
        {"rate": 4, "unit": "x_points", "category": "Restaurants", "when": None},
        {"rate": 2, "unit": "x_points", "category": "Prepaid Hotels", "when": "portal"},
    ],
    "credits": [{"description": "Dining Credit", "amount_usd": 10, "period": "month"}],
}


GREEN = {
    "id": "amex_green",
    "name": "American Express Green Card",
    "issuer_id": "amex",
    "availability": "closed_to_new_applicants",
    "closed_on": "2026-07-23",
    "annual_fee_usd": None,
    "offer": None,
    "earning_rates": [],
    "credits": [],
}
SAPPHIRES = [
    {
        "id": f"chase_sapphire_{tier}",
        "name": f"Chase Sapphire {tier.title()}",
        "issuer_id": "chase",
        "availability": "open",
        "annual_fee_usd": fee,
        "earning_rates": [],
        "credits": [],
    }
    for tier, fee in (("preferred", 95), ("reserve", 795))
]


class FakeApi:
    """Records what the tools send, answers like the real API."""

    def __init__(self):
        self.sent = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        path = request.url.path
        if path == "/me/recommendations":
            return httpx.Response(
                200,
                json={
                    "catalog_version": "1.5",
                    "needs": [],
                    "sort_by": "first_year",
                    "scenario": True,
                    "spending_used": {"monthly_usd": {"dining": 800}},
                    "cards": [
                        {
                            "card_id": "amex_gold",
                            "name": "Amex Gold",
                            "first_year_value_usd": 900.0,
                            "ongoing_value_usd": 100.0,
                            "breakdown": {
                                "offer_usd": 600,
                                "rewards_usd": 384,
                                "annual_fee_usd": 325,
                                "first_year_fee_usd": 325,
                            },
                            "offer_is_up_to": True,
                            "application_status": "Eligible",
                            "offer_status": "Undetermined",
                            "min_spend_gap_usd": 0,
                            "notes": ["a", "b", "c", "d"],
                            "conditional_rates": ["2x on Prepaid Hotels (portal)"],
                            "rank": 1,
                            "earnings": [
                                {
                                    "category": "dining",
                                    "rate": "4x points",
                                    "issuer_category": "Restaurants",
                                    "annual_spend_usd": 9600,
                                    "usd": 384,
                                }
                            ],
                        }
                    ],
                    "excluded": [],
                },
            )
        if path == "/catalog":
            return httpx.Response(200, json={"version": "1.5", "cards": [CARD, GREEN, *SAPPHIRES]})
        if path == "/rules":
            return httpx.Response(
                200,
                json={
                    "rules": [
                        {
                            "rule_id": "chase_5_24",
                            "issuer_id": "chase",
                            "summary": "Chase 5/24",
                            "decides": "approval",
                            "applies_to": "every chase card",
                            "how_it_counts": ["Counts new cards opened from any bank"],
                            "enforcement": "strict: cards are marked Ineligible",
                            "source": "applicants' reported results",
                            "source_url": "https://example.com/rules",
                            "verified_on": "2026-09-24",
                        }
                    ]
                },
            )
        if path == "/me/eligibility":
            return httpx.Response(
                200,
                json={
                    "evaluations": [
                        {
                            "card_product_id": "chase_sapphire_preferred",
                            "name": "Chase Sapphire Preferred",
                            "application": {"status": "Eligible", "reasons": [], "warnings": []},
                            "offer": {
                                "status": "Undetermined",
                                "reasons": [
                                    {
                                        "rule_id": "chase_5_24",
                                        "status": "Eligible",
                                        "message": "under 5/24",
                                    },
                                    {
                                        "rule_id": "chase_5_24",
                                        "status": "Undetermined",
                                        "message": "Chase 5/24: wallet not confirmed complete",
                                        "retry_after": None,
                                    },
                                ],
                                "warnings": [],
                            },
                        }
                    ]
                },
            )
        if path == "/me/chat/turn":
            return httpx.Response(429, json={"detail": {"message": "used up", "remaining": 0}})
        return httpx.Response(404, json={"detail": "nope"})


class S:
    api = None
    said = "I spend about $800 a month on dining."

    def user_said(self):
        return self.said


def posted(fake):
    """The body of the last POST /me/recommendations (later calls may fetch the catalog)."""
    req = [r for r in fake.sent if r.url.path == "/me/recommendations"][-1]
    return json.loads(req.content)


def session_with(fake):
    s = S()
    s.api = AdvisorApi(
        {"X-Dev-User": "u"},
        client=httpx.Client(base_url="http://api", transport=httpx.MockTransport(fake.handler)),
    )
    return s


def tools(session):
    return {t.tool_name: t for t in build_tools(session)}


def test_rank_cards_sends_only_what_the_user_said_as_a_what_if():
    fake = FakeApi()
    t = tools(session_with(fake))
    out = json.loads(
        t["rank_cards"](monthly_spending={"dining": 800}, opted_in=["portal:amex"], limit=50)
    )
    body = posted(fake)
    assert body["scenario"] == {"monthly_usd": {"dining": 800}}
    assert body["opted_in"] == ["portal:amex"] and body["limit"] == 10  # clamped
    assert "include_business" not in body  # unset stays unset (profile decides)
    card = out["cards"][0]
    assert card["offer_is_up_to"] and len(card["notes"]) == 3  # trimmed for the model
    assert card["apply_link"] == "[Apply](card:amex_gold)" and card["rank"] == 1
    assert card["top_earnings"] == ["dining: 4x points on $9,600/yr = $384/yr"]
    assert card["welcome_offer"] == "up to 100,000 points"
    assert (
        card["minimum_spend"] == "$8,000"
        and card["minimum_spend_check"] == "usual spending covers it"
    )
    assert out["what_if"] is True


def test_no_what_if_means_the_saved_profile_is_used():
    fake = FakeApi()
    tools(session_with(fake))["rank_cards"]()
    assert "scenario" not in posted(fake)


def test_card_details_never_include_urls_and_mark_conditions():
    out = compact_card(CARD)
    assert "url" not in json.dumps(out) and "https://" not in json.dumps(out)
    assert out["earning"] == ["4x on Restaurants", "2x on Prepaid Hotels (portal)"]


def test_unknown_card_and_api_errors_come_back_as_data_not_exceptions():
    t = tools(session_with(FakeApi()))
    assert json.loads(t["get_card_details"](card="nope"))["not_in_catalog"] == "nope"
    assert json.loads(t["get_my_profile"]())["error"] == 404


def test_profile_lists_what_ranking_still_needs():
    out = compact_profile({"tax_id": "SSN", "spending": None})
    assert "monthly spending" in out["missing"] and "goals" in out["missing"]
    assert "tax_id" not in out["missing"]


def test_quota_exhaustion_is_its_own_error():
    import pytest

    with pytest.raises(QuotaExceeded):
        session_with(FakeApi()).api.take_turn()


def test_offer_text_reads_like_the_issuer_page():
    from advisor.tools import offer_text

    two_part = {
        "offer": {
            "amount": 80000,
            "unit": "miles",
            "amount_is_up_to": True,
            "statement_credit_usd": 250,
            "ends_on": "2026-11-04",
        }
    }
    assert (
        offer_text(two_part) == "up to 80,000 miles + $250 statement credit (offer ends 2026-11-04)"
    )
    assert offer_text({"offer": {"amount": 3, "unit": "free_nights"}}) == "3 free night awards"
    assert (
        offer_text({"offer": {"amount": None, "unit": "cashback_match"}})
        == "cash back matched at the end of the first year"
    )
    assert offer_text({"offer": None}) is None


def test_tool_output_never_contains_a_null():
    # A null first-year fee was read as "$0 the first year"; absent facts are left out instead.
    t = tools(session_with(FakeApi()))
    details = t["get_card_details"](card="amex_gold")  # CARD has no first-year fee field
    ranking = t["rank_cards"]()
    for raw in (details, ranking, t["get_issuer_rules"](issuer_id="chase")):
        assert "null" not in raw
    assert json.loads(details)["annual_fee"] == (
        "$325 a year, including the first year (no first-year discount)"
    )
    assert json.loads(ranking)["cards"][0]["annual_fee"] == json.loads(details)["annual_fee"]


def test_wallet_cards_say_open_or_closed():
    from advisor.tools import compact_wallet

    out = compact_wallet(
        {
            "cards": [
                {"card_product_id": "a", "closed_on": None},
                {"card_product_id": "b", "closed_on": "2025-01-02"},
            ]
        },
        {},
    )
    assert [c["status"] for c in out["cards"]] == ["open", "closed on 2025-01-02"]


def test_fees_and_credits_are_spelled_out():
    from advisor.tools import credit_value, fee_text

    assert fee_text(325, None) == "$325 a year, including the first year (no first-year discount)"
    assert fee_text(325, 325) == fee_text(325, None)
    assert fee_text(95, 0) == "$0 the first year, then $95 a year"
    assert fee_text(0, None) == "no annual fee"
    assert fee_text(None, None) == "not listed in our catalog"
    assert credit_value({"amount_usd": 10, "period": "month"}) == "$10 per month"
    assert credit_value({"amount_usd": None, "percent": 25, "period": "per_use"}) == "25% back"


def test_rules_come_from_the_api_without_urls():
    out = json.loads(tools(session_with(FakeApi()))["get_issuer_rules"](issuer_id="chase"))
    assert out[0]["how_it_counts"] == ["Counts new cards opened from any bank"]
    assert "https://" not in json.dumps(out)


def test_eligibility_findings_carry_how_each_rule_works():
    out = json.loads(
        tools(session_with(FakeApi()))["check_eligibility"](card_ids=["chase_sapphire_preferred"])
    )
    [because] = out[0]["offer_because"]  # the Eligible reason is left out of the reasons...
    # ...but a rule met can still be cited, and says what it is
    assert out[0]["rules_met_for_offer"] == [{"rule": "chase_5_24", "says": "Chase 5/24"}]
    assert because["rule"] == "chase_5_24" and because["status"] == "Undetermined"
    assert because["how_the_rule_works"] == ["Counts new cards opened from any bank"]
    assert "retry_after" not in because  # nulls are dropped
    assert out[0]["can_apply_because"] == []


def test_cards_are_found_by_what_the_user_calls_them():
    t = tools(session_with(FakeApi()))
    assert json.loads(t["get_card_details"](card="Amex Gold"))["card_id"] == "amex_gold"
    assert json.loads(t["get_card_details"](card="sapphire preferred"))["card_id"] == (
        "chase_sapphire_preferred"
    )
    both = json.loads(t["get_card_details"](card="Chase Sapphire card"))
    assert [c["card_id"] for c in both["several_cards_match"]] == [
        "chase_sapphire_preferred",
        "chase_sapphire_reserve",
    ]


def test_a_card_we_dont_cover_is_said_plainly():
    out = json.loads(tools(session_with(FakeApi()))["get_card_details"](card="Bilt Mastercard"))
    assert out["not_in_catalog"] == "Bilt Mastercard"
    assert out["catalog_covers"] == "4 cards from amex, chase"


def test_a_closed_card_says_so_instead_of_listing_empty_fields():
    out = json.loads(tools(session_with(FakeApi()))["get_card_details"](card="amex green"))
    assert set(out) == {"card_id", "name", "issuer", "status"}
    assert out["status"].startswith("closed to new applicants since 2026-07-23")


def test_spending_the_user_never_said_is_refused():
    from advisor.tools import unstated_spending

    said = "I spend $1,200 a year on streaming, 800 on dining and about 1.5k on everything else"
    assert unstated_spending({"streaming": 100, "dining": 800, "everything_else": 1500}, said) == []
    assert unstated_spending({"dining": 300, "flights": 0}, said) == ["dining"]  # 0 removes

    fake = FakeApi()
    session = session_with(fake)
    session.said = "Which card is best for me?"
    out = json.loads(tools(session)["rank_cards"](monthly_spending={"dining": 300}))
    assert out["error"] == "spending_not_from_user" and "dining" in out["detail"]
    assert not [r for r in fake.sent if r.url.path == "/me/recommendations"]  # never ranked


def test_referral_tips_say_how_sure_they_are_and_carry_no_link():
    from advisor.tools import compact_card, referral_tip

    card = CARD | {
        "referral": {
            "text": "Amex referral links more often show the full offer.",
            "confidence": "community",
            "source": "applicants",
            "verified_on": "2026-10-01",
        }
    }
    tip = compact_card(card)["referral_tip"]
    assert tip.startswith("Amex referral links") and "applicants report" in tip
    assert "not counted" in tip and "http" not in tip
    assert referral_tip({"id": "x"}) is None


def test_earning_rates_carry_their_caps():
    from advisor.tools import earning_text

    rate = {"rate": 3, "unit": "percent_cash_back", "category": "U.S. supermarkets",
            "cap_usd": 6000, "cap_period": "calendar_year"}  # fmt: skip
    assert earning_text(rate) == (
        "3% on U.S. supermarkets (up to $6,000 a calendar year, then the base rate)"
    )


def test_an_unconfirmed_wallet_says_5_24_cant_be_determined():
    from advisor.tools import compact_wallet

    empty = compact_wallet({"cards": []}, {"count_24m": 0, "complete": False})
    assert empty["five_24_status"].startswith("can't be determined")
    assert compact_wallet({"cards": []}, {"count_24m": 4, "complete": True})["five_24_status"] == (
        "4 of 5"
    )
