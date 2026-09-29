"""The Advisor's tools (ADR 0009). All deterministic: they read the user's data and the catalog
through the API and return compact JSON. The model never supplies a card fact, an eligibility
verdict or a ranking; it only picks which tool to call and with what the user said.

Outputs are trimmed to what the model needs to explain (fewer tokens), and never include URLs:
the model links cards as `card:<id>` and the site turns that into the official issuer page.
"""

import json
from typing import Any, Protocol

from strands import tool

from advisor.api import AdvisorApi, ApiError

MAX_CARDS = 10


class Session(Protocol):
    api: AdvisorApi  # replaced on every request with one carrying the caller's current token


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _error(e: ApiError) -> str:
    return _json({"error": e.status, "detail": e.detail})


# --- compaction (pure, unit-tested) ---------------------------------------------------------


def compact_profile(profile: dict) -> dict:
    spending = profile.get("spending") or {}
    missing = [k for k in ("tax_id", "score_band", "income_band") if not profile.get(k)]
    if not any((spending.get("monthly_usd") or {}).values()):
        missing.append("monthly spending")
    if not spending.get("goals"):
        missing.append("goals")
    return {
        "tax_id": profile.get("tax_id"),
        "credit_score_range": profile.get("score_band"),
        "income_range": profile.get("income_band"),
        "credit_history": profile.get("credit_history"),
        "monthly_spending_usd": spending.get("monthly_usd") or {},
        "goals": spending.get("goals") or [],
        "max_annual_fee_usd": spending.get("max_annual_fee_usd"),
        "wants_business_cards": spending.get("wants_business", False),
        "missing": missing,
    }


def compact_wallet(wallet: dict, velocity: dict) -> dict:
    return {
        "cards": [
            {
                "card": c.get("card_product_id") or c.get("name"),
                "opened_on": c.get("opened_on"),
                "closed_on": c.get("closed_on"),
                "authorized_user": c.get("is_authorized_user", False),
            }
            for c in wallet.get("cards", [])
        ],
        "cards_opened_last_24_months": velocity.get("count_24m"),
        "next_drop_off": velocity.get("next_drop_off"),
        "history_complete": velocity.get("complete"),
        "attestation": wallet.get("attestation"),
    }


def offer_text(card: dict | None) -> str | None:
    """ "up to 80,000 miles + $250 statement credit" from a catalog card, or None."""
    offer = (card or {}).get("offer") or {}
    if not offer:
        return None
    unit = offer.get("unit")
    amount = offer.get("amount")
    if unit == "cashback_match":
        text = "cash back matched at the end of the first year"
    elif amount is None:
        text = "amount shown only when applying"
    elif unit in ("usd", "gift_card_usd"):
        text = f"${amount:,}" + (" gift card" if unit == "gift_card_usd" else "")
    elif unit == "free_nights":
        text = f"{amount} free night awards"
    else:
        text = f"{amount:,} {unit}"
    if offer.get("amount_is_up_to") and amount is not None:
        text = "up to " + text
    if offer.get("statement_credit_usd"):
        text += f" + ${offer['statement_credit_usd']:,} statement credit"
    if offer.get("ends_on"):
        text += f" (offer ends {offer['ends_on']})"
    return text


def min_spend_text(card: dict | None) -> str | None:
    offer = (card or {}).get("offer") or {}
    if not offer.get("min_spend_usd"):
        return None
    window = offer.get("spend_window_months")
    return f"${offer['min_spend_usd']:,}" + (f" in {window} months" if window else "")


def compact_ranking(body: dict, cards: dict[str, dict] | None = None) -> dict:
    """`cards`: catalog entries for the ranked cards, to add the Offer's actual terms."""
    cards = cards or {}
    if body.get("needs"):
        return {"needs": body["needs"], "spending_used": body.get("spending_used")}
    return {
        "catalog_version": body.get("catalog_version"),
        "sorted_by": body.get("sort_by"),
        "what_if": body.get("scenario", False),
        "spending_used": (body.get("spending_used") or {}).get("monthly_usd"),
        "cards": [
            {
                "rank": c.get("rank"),
                "card_id": c["card_id"],
                "name": c["name"],
                "apply_link": f"[Apply](card:{c['card_id']})",
                "first_year_value_usd": c["first_year_value_usd"],
                "ongoing_value_usd": c["ongoing_value_usd"],
                "welcome_offer": offer_text(cards.get(c["card_id"])),
                "welcome_offer_value_usd": c["breakdown"]["offer_usd"],
                "minimum_spend": min_spend_text(cards.get(c["card_id"])),
                "minimum_spend_check": (
                    None
                    if c.get("min_spend_gap_usd") is None
                    else "usual spending covers it"
                    if c["min_spend_gap_usd"] == 0
                    else f"${c['min_spend_gap_usd']:,.0f} more than usual spending in that window"
                ),
                "rewards_usd_per_year": c["breakdown"]["rewards_usd"],
                "annual_fee_usd": c["breakdown"]["annual_fee_usd"],
                "first_year_fee_usd": c["breakdown"]["first_year_fee_usd"],
                "offer_is_up_to": c.get("offer_is_up_to", False),
                "can_apply": c["application_status"],
                "offer_status": c["offer_status"],
                # Why it earns what it does: quote these instead of stating rates.
                "top_earnings": [
                    f"{e['category']}: {e['rate']} on ${e['annual_spend_usd']:,.0f}/yr"
                    f" = ${e['usd']:,.0f}/yr"
                    for e in c.get("earnings", [])[:3]
                ],
                "notes": c.get("notes", [])[:3],
                "not_counted_rates": c.get("conditional_rates", [])[:4],
            }
            for c in body.get("cards", [])
        ],
        "excluded": [
            {"card_id": e["card_id"], "reason": e["reason"], "retry_after": e.get("retry_after")}
            for e in body.get("excluded", [])[:6]
        ],
    }


def compact_eligibility(body: dict) -> list[dict]:
    def reasons(verdict: dict) -> list[str]:
        return [
            r["message"] + (f" (retry after {r['retry_after']})" if r.get("retry_after") else "")
            for r in verdict.get("reasons", [])
            if r["status"] != "Eligible"
        ] + [f"warning: {w['message']}" for w in verdict.get("warnings", [])]

    return [
        {
            "card_id": e["card_product_id"],
            "name": e.get("name"),
            "can_apply": e["application"]["status"],
            "can_apply_because": reasons(e["application"]),
            "offer": e["offer"]["status"],
            "offer_because": reasons(e["offer"]),
        }
        for e in body.get("evaluations", [])
    ]


def compact_card(card: dict) -> dict:
    offer = card.get("offer") or {}
    return {
        "card_id": card["id"],
        "name": card["name"],
        "issuer": card["issuer_id"],
        "annual_fee_usd": card.get("annual_fee_usd"),
        "first_year_fee_usd": card.get("first_year_annual_fee_usd"),
        "foreign_transaction_fee_pct": card.get("foreign_transaction_fee_pct"),
        "offer": {
            k: offer.get(k)
            for k in (
                "amount",
                "unit",
                "amount_is_up_to",
                "min_spend_usd",
                "spend_window_months",
                "statement_credit_usd",
                "ends_on",
            )
        }
        if offer
        else None,
        "earning": [
            f"{r['rate']:g}{'%' if r['unit'] == 'percent_cash_back' else 'x'} on {r['category']}"
            + (
                f" ({r['when']}{':' + r['brand'] if r.get('brand') else ''})"
                if r.get("when")
                else ""
            )
            for r in card.get("earning_rates", [])
        ],
        "credits": [
            {"description": c["description"], "usd": c.get("amount_usd"), "period": c["period"]}
            for c in card.get("credits", [])
        ],
        "tags": card.get("tags", []),
        "open_to_applicants": card.get("availability") == "open",
    }


# --- tools ----------------------------------------------------------------------------------


def build_tools(session: Session) -> list:
    @tool
    def get_my_profile() -> str:
        """Read the user's saved Applicant Profile: tax ID type, credit score and income ranges,
        monthly spending by category, goals, annual-fee limit, and which of these are missing."""
        try:
            return _json(compact_profile(session.api.profile()))
        except ApiError as e:
            return _error(e)

    @tool
    def get_my_wallet() -> str:
        """Read the cards the user holds (with open/close dates) and how many personal cards they
        opened in the last 24 months (Chase 5/24)."""
        try:
            return _json(compact_wallet(session.api.wallet(), session.api.velocity()))
        except ApiError as e:
            return _error(e)

    @tool
    def rank_cards(
        monthly_spending: dict[str, float] | None = None,
        goals: list[str] | None = None,
        max_annual_fee_usd: int | None = None,
        no_fee_limit: bool = False,
        include_business: bool | None = None,
        opted_in: list[str] | None = None,
        confirmed_credits: dict[str, list[str]] | None = None,
        limit: int = 5,
    ) -> str:
        """Rank open cards by estimated dollar value for this user (deterministic code; never rank
        cards yourself). Uses the saved profile; pass only what the user said in this
        conversation to try it as a what-if (not saved).

        Args:
            monthly_spending: What-if monthly USD by category, overriding only those categories.
                Categories: dining, groceries, flights, hotels, other_travel, gas_ev, transit,
                streaming, online_shopping, drugstores, everything_else. 0 removes one.
            goals: What-if goals: earn_offers, long_term, travel, cash_back, build_credit.
            max_annual_fee_usd: What-if annual-fee ceiling.
            no_fee_limit: True to ignore a saved fee ceiling this time.
            include_business: True to include business cards, False to exclude them.
            opted_in: Conditional rates the user confirmed apply to them, e.g. "portal:chase"
                (books through that issuer's travel site) or "brand:delta" (flies Delta).
            confirmed_credits: Card credits the user said they would really use,
                {card_id: [credit description exactly as get_card_details lists it]}.
            limit: How many cards to return (1-10).
        """
        scenario = {
            k: v
            for k, v in {
                "monthly_usd": monthly_spending,
                "goals": goals,
                "max_annual_fee_usd": max_annual_fee_usd,
            }.items()
            if v is not None
        }
        if no_fee_limit:
            scenario["no_fee_limit"] = True
        options: dict[str, Any] = {
            "opted_in": opted_in or [],
            "credits": confirmed_credits or {},
            "limit": max(1, min(MAX_CARDS, limit)),
        }
        if include_business is not None:
            options["include_business"] = include_business
        if scenario:
            options["scenario"] = scenario
        try:
            body = session.api.recommendations(options)
            ranked = {c["card_id"]: session.api.card(c["card_id"]) for c in body.get("cards", [])}
            return _json(compact_ranking(body, ranked))
        except ApiError as e:
            return _error(e)

    @tool
    def check_eligibility(card_ids: list[str]) -> str:
        """Check whether the user can be approved for specific cards and whether they would earn
        each card's welcome offer, with the reasons (issuer rules such as Chase 5/24).

        Args:
            card_ids: Catalog card ids, e.g. ["chase_sapphire_preferred"] (at most 10).
        """
        try:
            body = session.api.eligibility(card_ids[:MAX_CARDS])
            return _json(compact_eligibility(body))
        except ApiError as e:
            return _error(e)

    @tool
    def get_card_details(card_id: str) -> str:
        """Facts about one card from the catalog: fees, welcome offer, earning rates (with any
        condition such as a travel portal or brand), credits and perks.

        Args:
            card_id: Catalog card id, e.g. "amex_gold".
        """
        try:
            card = session.api.card(card_id)
        except ApiError as e:
            return _error(e)
        if card is None:
            return _json({"error": 404, "detail": f"no card {card_id!r} in the catalog"})
        return _json(compact_card(card))

    return [get_my_profile, get_my_wallet, rank_cards, check_eligibility, get_card_details]
