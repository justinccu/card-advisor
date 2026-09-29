"""One contract, two stores: the in-memory repo must behave like DynamoDB (tested via moto,
no AWS calls)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import boto3
import pytest
from card_api.models import ApplicantProfile, HeldCardIn, WalletAttestation
from card_api.repository import DynamoRepository, InMemoryRepository
from card_api.triggers import postconfirm_handler, presignup_handler
from moto import mock_aws


@pytest.fixture(params=["memory", "dynamo"])
def repo(request, monkeypatch):
    if request.param == "memory":
        yield InMemoryRepository()
        return
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-2")
        ddb.create_table(
            TableName="t",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield DynamoRepository("t", resource=ddb)


def card(product, opened):
    return HeldCardIn(card_product_id=product, opened_on=opened)


def test_cards_are_listed_in_open_date_order(repo):
    repo.add_card("u", card("b", date(2025, 6, 1)))
    repo.add_card("u", card("a", date(2024, 1, 1)))
    assert [c.card_product_id for c in repo.list_cards("u")] == ["a", "b"]


def test_delete_is_scoped_to_the_owner(repo):
    held = repo.add_card("u", card("a", date(2024, 1, 1)))
    assert repo.delete_card("someone-else", held.id) is False
    assert repo.delete_card("u", held.id) is True
    assert repo.list_cards("u") == []


def test_editing_the_open_date_moves_the_card_and_keeps_its_id(repo):
    held = repo.add_card("u", card("a", date(2024, 1, 1)))
    repo.add_card("u", card("b", date(2025, 1, 1)))
    moved = repo.update_card("u", held.id, card("a", date(2025, 6, 15)))
    assert moved.id == held.id and moved.opened_on == date(2025, 6, 15)
    listed = repo.list_cards("u")
    assert [(c.card_product_id, c.opened_on) for c in listed] == [
        ("b", date(2025, 1, 1)),
        ("a", date(2025, 6, 15)),
    ]  # no copy left under the old date
    assert repo.update_card("v", held.id, card("a", date(2025, 1, 1))) is None  # not v's card


def test_profile_and_attestation_default_then_roundtrip(repo):
    assert repo.get_profile("u") == ApplicantProfile()
    repo.put_profile("u", ApplicantProfile(tax_id="ITIN"))
    repo.put_attestation("u", WalletAttestation(complete_since=date(2024, 9, 1)))
    assert repo.get_profile("u").tax_id == "ITIN"
    assert repo.get_attestation("u").complete_since == date(2024, 9, 1)


def test_invite_redemption_is_atomic(repo):
    repo.create_invite("CODE", 2)
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda i: repo.redeem_invite("CODE", f"user-{i}"), range(20)))
    assert results.count(True) == 2
    assert repo.redeem_invite("MISSING", "someone") is False
    # remaining + recorded uses always equals what the code was created with
    [invite] = repo.list_invites()
    assert invite.remaining == 0 and len(invite.uses) == 2


def test_last_use_race_has_exactly_one_winner(repo):
    repo.create_invite("LAST", 1)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda u: repo.redeem_invite("LAST", u), ["ann", "bob"]))
    assert sorted(results) == [False, True]
    [invite] = repo.list_invites()
    assert [u.user for u in invite.uses] == [["ann", "bob"][results.index(True)]]


def test_failed_redemption_records_nothing(repo):
    repo.create_invite("SPENT", 0)
    assert repo.redeem_invite("SPENT", "ann") is False
    assert repo.list_invites()[0].uses == []


def test_a_retried_sign_up_does_not_take_a_second_use(repo):
    repo.create_invite("TWO", 2)
    assert repo.redeem_invite("TWO", "ann") and repo.redeem_invite("TWO", "ann")
    assert repo.list_invites()[0].remaining == 1


def test_uses_are_confirmed_once_and_listed_per_code(repo):
    repo.create_invite("B-CODE", 1)
    repo.create_invite("A-CODE", 3)
    repo.redeem_invite("A-CODE", "ann")
    repo.redeem_invite("A-CODE", "bob")
    assert repo.confirm_invite_use("ann") is True
    assert repo.confirm_invite_use("ann") is False  # already confirmed
    assert repo.confirm_invite_use("nobody") is False
    a, b = repo.list_invites()
    assert (a.code, a.remaining, b.code, b.remaining) == ("A-CODE", 1, "B-CODE", 1)
    status = {u.user: u.confirmed_at is not None for u in a.uses}
    assert status == {"ann": True, "bob": False}  # bob abandoned sign-up: a burned use


def test_quota_stops_at_the_limit_per_day(repo):
    day = date(2026, 9, 25)
    assert [repo.take_quota("u", day, 2) for _ in range(3)] == [1, 2, None]
    assert repo.quota_used("u", day) == 2
    assert repo.take_quota("u", date(2026, 9, 26), 2) == 1  # new day, new counter
    assert repo.quota_used("u", date(2026, 9, 27)) == 0


def test_delete_user_purges_everything(repo):
    repo.add_card("u", card("a", date(2024, 1, 1)))
    repo.put_profile("u", ApplicantProfile(tax_id="SSN"))
    repo.take_quota("u", date(2026, 9, 25), 5)
    repo.add_card("v", card("a", date(2024, 1, 1)))
    repo.create_invite("CODE", 2)
    repo.redeem_invite("CODE", "u")
    repo.redeem_invite("CODE", "v")
    repo.delete_user("u")
    assert repo.list_cards("u") == [] and repo.get_profile("u") == ApplicantProfile()
    assert len(repo.list_cards("v")) == 1  # other users untouched
    [invite] = repo.list_invites()
    assert [u.user for u in invite.uses] == ["v"] and invite.remaining == 0  # use stays spent


def test_presignup_trigger_requires_a_live_invite(monkeypatch):
    from card_api import triggers

    r = InMemoryRepository()
    r.create_invite("CAGOOD", 1)
    monkeypatch.setattr(triggers, "get_repo", lambda: r)
    event = {"userName": "sub-1", "request": {"clientMetadata": {"invite_code": "ca-good"}}}
    assert presignup_handler(event, None) is event
    with pytest.raises(Exception, match="invite code"):
        presignup_handler({**event, "userName": "sub-2"}, None)  # single use, now spent
    with pytest.raises(Exception, match="invite code"):
        presignup_handler({"userName": "sub-3", "request": {}}, None)
    with pytest.raises(Exception, match="invite code"):
        presignup_handler({"request": {"clientMetadata": {"invite_code": "CAGOOD"}}}, None)

    confirm = {"triggerSource": "PostConfirmation_ConfirmSignUp", "userName": "sub-1"}
    assert postconfirm_handler(confirm, None) is confirm
    assert r.list_invites()[0].uses[0].confirmed_at is not None
    # a password reset also fires post-confirmation; it must not touch invites
    reset = {"triggerSource": "PostConfirmation_ConfirmForgotPassword", "userName": "sub-9"}
    assert postconfirm_handler(reset, None) is reset


def test_triggers_stay_light_for_cognitos_5_second_limit():
    import subprocess
    import sys

    code = (
        "import sys, card_api.triggers; "
        "print('fastapi' in sys.modules, 'card_api.catalog' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["False", "False"]
