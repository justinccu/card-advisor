from datetime import date

import pytest
from card_rules import evaluate, load_rules
from card_rules.dates import add_months
from card_rules.models import (
    ApplicantProfile,
    CardProduct,
    HeldCard,
    Status,
    TaxId,
    Wallet,
)

AS_OF = date(2026, 9, 24)
RULES = load_rules()
SSN = ApplicantProfile(tax_id=TaxId.SSN)

FREEDOM = CardProduct(
    id="chase_freedom_unlimited", issuer_id="chase", name="Chase Freedom Unlimited"
)
CSP = CardProduct(
    id="chase_sapphire_preferred", issuer_id="chase", name="Sapphire Preferred", family="sapphire"
)
AMEX_GOLD = CardProduct(id="amex_gold", issuer_id="amex", name="Amex Gold", is_charge_card=True)
AMEX_BCP = CardProduct(id="amex_bcp", issuer_id="amex", name="Blue Cash Preferred")
VENTURE_X = CardProduct(id="c1_venture_x", issuer_id="capital_one", name="Venture X")
WF_ACTIVE = CardProduct(id="wf_active_cash", issuer_id="wells_fargo", name="Active Cash")


def card(issuer: str, months_ago: int, **kw) -> HeldCard:
    return HeldCard(issuer_id=issuer, opened_on=add_months(AS_OF, -months_ago), **kw)


def complete(*cards: HeldCard, issuers: frozenset[str] = frozenset()) -> Wallet:
    return Wallet(
        cards=list(cards),
        complete_since=add_months(AS_OF, -60),
        includes_all_open_cards=True,
        full_history_issuers=issuers,
    )


def reason(verdict, rule_id):
    return next(r for r in verdict.reasons if r.rule_id == rule_id)


# --- Chase 5/24 -------------------------------------------------------------------


def test_4_of_24_is_eligible():
    wallet = complete(*(card("citi", m) for m in (1, 5, 10, 20)))
    result = evaluate(FREEDOM, SSN, wallet, RULES, AS_OF)
    assert reason(result.application, "chase_5_24").status is Status.ELIGIBLE


def test_5_of_24_is_ineligible_with_retry_date():
    wallet = complete(*(card("citi", m) for m in (1, 5, 10, 20, 23)))
    r = reason(evaluate(FREEDOM, SSN, wallet, RULES, AS_OF).application, "chase_5_24")
    assert r.status is Status.INELIGIBLE
    # Oldest counted card (23 months ago) ages out 24 months after opening.
    assert r.retry_after == add_months(AS_OF, 1)


def test_retry_date_waits_for_enough_cards_to_age_out():
    wallet = complete(*(card("citi", m) for m in (1, 2, 3, 20, 22, 23)))
    r = reason(evaluate(FREEDOM, SSN, wallet, RULES, AS_OF).application, "chase_5_24")
    # 6 counted, limit 5: the two oldest (23 and 22 months ago) must both age out.
    assert r.retry_after == add_months(AS_OF, 2)


def test_card_opened_exactly_24_months_ago_no_longer_counts():
    wallet = complete(*(card("citi", m) for m in (1, 5, 10, 20, 24)))
    assert reason(
        evaluate(FREEDOM, SSN, wallet, RULES, AS_OF).application, "chase_5_24"
    ).status is (Status.ELIGIBLE)


def test_authorized_user_cards_count_but_business_cards_do_not():
    base = [card("citi", m) for m in (1, 5, 10, 20)]
    with_au = complete(*base, card("amex", 2, is_authorized_user=True))
    with_biz = complete(*base, card("amex", 2, is_business=True))
    assert reason(
        evaluate(FREEDOM, SSN, with_au, RULES, AS_OF).application, "chase_5_24"
    ).status is (Status.INELIGIBLE)
    assert reason(
        evaluate(FREEDOM, SSN, with_biz, RULES, AS_OF).application, "chase_5_24"
    ).status is (Status.ELIGIBLE)


def test_incomplete_wallet_under_limit_is_undetermined():
    wallet = Wallet(cards=[card("citi", 3)], includes_all_open_cards=True)
    r = reason(evaluate(FREEDOM, SSN, wallet, RULES, AS_OF).application, "chase_5_24")
    assert r.status is Status.UNDETERMINED


def test_incomplete_wallet_already_over_limit_is_still_ineligible():
    wallet = Wallet(cards=[card("citi", m) for m in (1, 2, 3, 4, 5)])
    r = reason(evaluate(FREEDOM, SSN, wallet, RULES, AS_OF).application, "chase_5_24")
    assert r.status is Status.INELIGIBLE


# --- Sapphire (2026 rules) --------------------------------------------------------


def test_sapphire_offer_blocked_while_another_sapphire_is_open():
    wallet = complete(
        card("chase", 30, card_product_id="chase_sapphire_reserve", family="sapphire")
    )
    result = evaluate(CSP, SSN, wallet, RULES, AS_OF)
    assert result.offer.status is Status.INELIGIBLE
    assert reason(result.offer, "chase_sapphire_open").status is Status.INELIGIBLE


def test_sapphire_offer_is_once_per_card_even_after_closing():
    held = card("chase", 50, card_product_id=CSP.id, family="sapphire", closed_on=date(2025, 1, 1))
    result = evaluate(CSP, SSN, complete(held, issuers=frozenset({"chase"})), RULES, AS_OF)
    r = reason(result.offer, "chase_sapphire_once_per_card")
    assert r.status is Status.INELIGIBLE
    assert r.retry_after is None  # lifetime rule: never


def test_lifetime_rule_needs_full_history_attestation():
    result = evaluate(CSP, SSN, complete(), RULES, AS_OF)
    assert reason(result.offer, "chase_sapphire_once_per_card").status is Status.UNDETERMINED
    attested = evaluate(CSP, SSN, complete(issuers=frozenset({"chase"})), RULES, AS_OF)
    assert attested.offer.status is Status.ELIGIBLE


# --- Amex -------------------------------------------------------------------------


def test_amex_2_90_counts_only_amex_credit_cards():
    wallet = complete(card("amex", 1), card("amex", 2, is_charge_card=True), card("chase", 1))
    r = reason(evaluate(AMEX_BCP, SSN, wallet, RULES, AS_OF).application, "amex_2_90")
    assert r.status is Status.ELIGIBLE


def test_amex_credit_card_limits_do_not_apply_to_charge_cards():
    five_credit = complete(*(card("amex", 30 + i) for i in range(5)))
    assert (
        evaluate(AMEX_BCP, SSN, five_credit, RULES, AS_OF).application.status is Status.INELIGIBLE
    )
    gold = evaluate(AMEX_GOLD, SSN, five_credit, RULES, AS_OF)
    assert all(r.rule_id != "amex_max_5_credit" for r in gold.application.reasons)


# --- Bonus lookback (Capital One 48 months) ---------------------------------------


def test_bonus_inside_lookback_blocks_until_it_ages_out():
    held = card("capital_one", 30, card_product_id=VENTURE_X.id, bonus_received_on=date(2024, 6, 1))
    r = reason(
        evaluate(VENTURE_X, SSN, complete(held), RULES, AS_OF).offer, "capital_one_48_month_bonus"
    )
    assert r.status is Status.INELIGIBLE
    assert r.retry_after == date(2028, 6, 1)


def test_bonus_outside_lookback_is_eligible():
    held = card("capital_one", 70, card_product_id=VENTURE_X.id, bonus_received_on=date(2021, 3, 1))
    wallet = complete(held, issuers=frozenset({"capital_one"}))
    r = reason(evaluate(VENTURE_X, SSN, wallet, RULES, AS_OF).offer, "capital_one_48_month_bonus")
    assert r.status is Status.ELIGIBLE


def test_undetermined_message_names_the_history_actually_needed():
    # A bonus earned inside the 48-month window could come from a card opened up to
    # 12 months earlier, so the Wallet must be attested back 60 months, not 48.
    wallet = Wallet(complete_since=add_months(AS_OF, -48), includes_all_open_cards=True)
    r = reason(evaluate(VENTURE_X, SSN, wallet, RULES, AS_OF).offer, "capital_one_48_month_bonus")
    assert r.status is Status.UNDETERMINED
    assert add_months(AS_OF, -60).isoformat() in r.message


def test_held_card_with_unknown_bonus_date_is_undetermined():
    held = card("capital_one", 30, card_product_id=VENTURE_X.id)
    r = reason(
        evaluate(VENTURE_X, SSN, complete(held), RULES, AS_OF).offer, "capital_one_48_month_bonus"
    )
    assert r.status is Status.UNDETERMINED


# --- Tax ID -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tax_id", "expected"),
    [
        (TaxId.SSN, Status.ELIGIBLE),
        (TaxId.ITIN, Status.ELIGIBLE),
        (TaxId.NONE, Status.INELIGIBLE),
        (None, Status.UNDETERMINED),
    ],
)
def test_tax_id(tax_id, expected):
    product = FREEDOM.model_copy(update={"accepted_tax_ids": frozenset({TaxId.SSN, TaxId.ITIN})})
    result = evaluate(product, ApplicantProfile(tax_id=tax_id), complete(), RULES, AS_OF)
    assert reason(result.application, "tax_id").status is expected


# --- Combining --------------------------------------------------------------------


def test_soft_rule_violation_warns_without_changing_status():
    wallet = complete(card("wells_fargo", 2))
    result = evaluate(WF_ACTIVE, SSN, wallet, RULES, AS_OF)
    assert result.application.status is Status.ELIGIBLE
    assert [w.rule_id for w in result.application.warnings] == ["wells_fargo_1_6"]


def test_ineligible_outranks_undetermined():
    wallet = Wallet(cards=[card("citi", m) for m in (1, 2, 3, 4, 5)])
    result = evaluate(FREEDOM, ApplicantProfile(), wallet, RULES, AS_OF)
    assert reason(result.application, "tax_id").status is Status.UNDETERMINED
    assert result.application.status is Status.INELIGIBLE


def test_rules_only_apply_to_their_issuer():
    result = evaluate(VENTURE_X, SSN, complete(), RULES, AS_OF)
    assert all(not r.rule_id.startswith("chase") for r in result.application.reasons)


def test_evaluation_is_deterministic():
    wallet = complete(*(card("citi", m) for m in (1, 5, 10)))
    assert evaluate(CSP, SSN, wallet, RULES, AS_OF) == evaluate(CSP, SSN, wallet, RULES, AS_OF)
