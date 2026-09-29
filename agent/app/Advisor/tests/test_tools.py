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
            return httpx.Response(200, json={"version": "1.5", "cards": [CARD]})
        if path == "/me/chat/turn":
            return httpx.Response(429, json={"detail": {"message": "used up", "remaining": 0}})
        return httpx.Response(404, json={"detail": "nope"})


class S:
    api = None


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
    assert json.loads(t["get_card_details"](card_id="nope"))["error"] == 404
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
