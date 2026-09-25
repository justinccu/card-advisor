import json
from dataclasses import asdict

import pytest
from card_rules.catalog import CatalogSnapshot
from card_rules.models import TaxId
from scout import publish, review
from scout.seed import SeedCard
from test_extract import PAGE, run, sourced, tool_input


def change_dict(tmp_path, payload=None) -> dict:
    change, _, _ = run(payload or tool_input(), tmp_path)
    return json.loads(json.dumps(asdict(change)))


def scripted(*answers):
    it = iter(answers)
    return lambda prompt: next(it)


def decide(change, *answers):
    lines: list[str] = []
    result = review.decide(change, PAGE, run="r1", ask=scripted(*answers), say=lines.append)
    return result, "\n".join(lines)


def test_clean_change_approves_without_extra_confirmation(tmp_path):
    result, _ = decide(change_dict(tmp_path), "a")
    assert result.decision == "approved" and result.edits == []
    assert result.final["offer"]["amount"]["value"] == 75000


def test_flagged_field_needs_confirmation_or_edit(tmp_path):
    payload = tool_input()
    payload["offer"]["amount"] = sourced(100000, "Earn 100,000 points")
    change = change_dict(tmp_path, payload)

    result, shown = decide(change, "a", "n", "e", "offer.amount.value", "75000", "a")
    assert "closest line" in shown and "Earn 75,000 points" in shown
    assert result.final["offer"]["amount"]["value"] == 75000
    assert result.edits == [{"path": "offer.amount.value", "old": 100000, "new": 75000}]


def test_bad_edit_path_is_reported_not_crashing(tmp_path):
    result, shown = decide(change_dict(tmp_path), "e", "offer.nope.value", "1", "a")
    assert "no such field" in shown and result.edits == []


def test_edit_can_delete_list_items(tmp_path):
    result, _ = decide(change_dict(tmp_path), "e", "earning_rates[0]", "<del>", "a")
    assert result.final["earning_rates"] == []


def test_reject_records_reason_and_skip_returns_none(tmp_path):
    change = change_dict(tmp_path)
    rejected, _ = decide(change, "r", "page is a login wall")
    assert rejected.decision == "rejected" and rejected.reason == "page is a login wall"
    assert decide(change, "s")[0] is None


def test_accuracy_counts_each_corrected_field_once():
    reviews = {
        "a": {
            "decision": "approved",
            "fields_total": 10,
            "edits": [
                {"path": "offer.amount.value"},
                {"path": "offer.amount.evidence"},
                {"path": "earning_rates[1].rate"},
            ],
        },
        "b": {"decision": "approved", "fields_total": 10, "edits": []},
        "c": {"decision": "rejected", "fields_total": 8, "edits": []},
    }
    stats = review.accuracy(reviews)
    assert stats["fields_edited"] == 2  # offer.amount and earning_rates[1]
    assert stats["accepted_unchanged"] == pytest.approx(18 / 20)
    assert stats["cards_rejected"] == 1


SEEDS = [
    SeedCard(
        id="csp",
        issuer_id="chase",
        name="Sapphire Preferred",
        url="https://x",
        priority="P0",
        family="sapphire",
    ),
    SeedCard(
        id="green",
        issuer_id="amex",
        name="Green",
        url="https://y",
        priority="P1",
        availability="closed_to_new_applicants",
        closed_on="2026-07-23",
    ),
    SeedCard(id="unreviewed", issuer_id="citi", name="Pending", url="https://z", priority="P0"),
]


def approved(tmp_path, payload=None):
    result, _ = decide(change_dict(tmp_path, payload), "a")
    return {"csp": result.__dict__}


def test_publish_includes_approved_and_closed_cards_only(tmp_path):
    cards = publish.build(SEEDS, approved(tmp_path))
    assert [c.id for c in cards] == ["csp", "green"]
    csp = cards[0]
    assert csp.offer.amount == 75000 and csp.annual_fee_usd == 95
    assert csp.accepted_tax_ids == {TaxId.SSN}  # page silent on ITIN -> conservative
    assert cards[1].offer is None and cards[1].availability == "closed_to_new_applicants"


def test_itin_is_accepted_only_when_page_says_so(tmp_path):
    payload = tool_input(accepts_itin=sourced(True, "$95 Annual Fee"))
    card = publish.build(SEEDS[:1], approved(tmp_path, payload))[0]
    assert card.accepted_tax_ids == {TaxId.SSN, TaxId.ITIN}


def test_snapshots_are_versioned_and_not_rewritten_when_unchanged(tmp_path):
    cards = publish.build(SEEDS, approved(tmp_path))
    out = tmp_path / "catalog"
    first = publish.publish(cards, out)
    assert first.name == "v1.json"
    assert publish.publish(cards, out) is None  # identical content -> no new version
    snapshot = CatalogSnapshot.model_validate_json(first.read_text())
    assert snapshot.card("csp").offer.min_spend_usd == 5000

    changed = [cards[0].model_copy(update={"annual_fee_usd": 150}), *cards[1:]]
    assert publish.publish(changed, out).name == "v2.json"
