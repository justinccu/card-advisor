"""One contract, two stores: the in-memory repo must behave like DynamoDB (tested via moto,
no AWS calls)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import boto3
import pytest
from card_api.lambda_handler import presignup_handler
from card_api.models import ApplicantProfile, HeldCardIn, WalletAttestation
from card_api.repository import DynamoRepository, InMemoryRepository
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


def test_profile_and_attestation_default_then_roundtrip(repo):
    assert repo.get_profile("u") == ApplicantProfile()
    repo.put_profile("u", ApplicantProfile(tax_id="ITIN"))
    repo.put_attestation("u", WalletAttestation(complete_since=date(2024, 9, 1)))
    assert repo.get_profile("u").tax_id == "ITIN"
    assert repo.get_attestation("u").complete_since == date(2024, 9, 1)


def test_invite_redemption_is_atomic(repo):
    repo.create_invite("CODE", 2)
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: repo.redeem_invite("CODE"), range(20)))
    assert results.count(True) == 2
    assert repo.redeem_invite("MISSING") is False


def test_quota_stops_at_the_limit_per_day(repo):
    day = date(2026, 9, 25)
    assert [repo.take_quota("u", day, 2) for _ in range(3)] == [True, True, False]
    assert repo.take_quota("u", date(2026, 9, 26), 2) is True  # new day, new counter


def test_delete_user_purges_everything(repo):
    repo.add_card("u", card("a", date(2024, 1, 1)))
    repo.put_profile("u", ApplicantProfile(tax_id="SSN"))
    repo.take_quota("u", date(2026, 9, 25), 5)
    repo.add_card("v", card("a", date(2024, 1, 1)))
    repo.delete_user("u")
    assert repo.list_cards("u") == [] and repo.get_profile("u") == ApplicantProfile()
    assert len(repo.list_cards("v")) == 1  # other users untouched


def test_presignup_trigger_requires_a_live_invite(monkeypatch):
    from card_api import lambda_handler

    r = InMemoryRepository()
    r.create_invite("GOOD", 1)
    monkeypatch.setattr(lambda_handler, "get_repo", lambda: r)
    event = {"request": {"clientMetadata": {"invite_code": "good"}}}
    assert presignup_handler(event, None) is event
    with pytest.raises(Exception, match="invite code"):
        presignup_handler(event, None)  # single use, now spent
    with pytest.raises(Exception, match="invite code"):
        presignup_handler({"request": {}}, None)
