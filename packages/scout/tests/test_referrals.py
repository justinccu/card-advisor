import pytest
from card_rules.catalog import CatalogCard, Offer
from scout import referrals


def card(id_, issuer="amex", up_to=None, open_=True):
    offer = None
    if up_to is not None:
        offer = Offer(
            amount_disclosed=True, amount=1000, unit="points", amount_is_up_to=up_to,
            min_spend_usd=None, spend_window_months=None,
        )  # fmt: skip
    return CatalogCard(
        id=id_, issuer_id=issuer, name=id_, url="https://x", offer=offer,
        availability="open" if open_ else "closed_to_new_applicants",
    )  # fmt: skip


def test_referral_facts_reach_the_right_cards(tmp_path):
    path = tmp_path / "referrals.yaml"
    path.write_text(
        """
cards:
  disc: {text: "+$100", bonus_usd: 100, confidence: owner, source: owner, verified_on: 2026-10-01}
issuers:
  amex: {only_up_to_offers: true, text: "fuller offer", confidence: community,
         source: applicants, verified_on: 2026-10-01}
"""
    )
    out = {
        c.id: c.referral
        for c in referrals.stamp(
            [
                card("disc", issuer="discover"),
                card("gold", up_to=True),
                card("hilton", up_to=False),  # a fixed offer: nothing for a referral to raise
                card("green", up_to=True, open_=False),  # closed to applicants
                card("csp", issuer="chase", up_to=True),
            ],
            path,
        )
    }
    assert out["disc"].bonus_usd == 100 and out["disc"].confidence == "owner"
    assert out["gold"].text == "fuller offer"
    assert out["hilton"] is None and out["green"] is None and out["csp"] is None


def test_a_referral_for_an_unknown_card_is_refused(tmp_path):
    path = tmp_path / "referrals.yaml"
    path.write_text(
        "cards:\n  nope: {text: x, confidence: owner, source: s, verified_on: 2026-10-01}\n"
    )
    with pytest.raises(referrals.ReferralError, match="nope"):
        referrals.stamp([card("gold")], path)


def test_the_seed_file_is_valid():
    from card_rules import catalog  # noqa: F401
    from scout.publish import latest

    _, snapshot = latest()
    stamped = {c.id: c for c in referrals.stamp(snapshot.cards)}
    assert stamped["discover_it_student_cash_back"].referral.bonus_usd == 100
    assert stamped["amex_gold"].referral.confidence == "community"
