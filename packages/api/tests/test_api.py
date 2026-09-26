from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from card_api import app as app_module
from card_api import auth
from card_api.app import app, get_repo
from card_api.repository import InMemoryRepository
from card_api.settings import Settings
from card_rules.dates import add_months
from fastapi.testclient import TestClient

TODAY = date.today()


@pytest.fixture
def repo():
    r = InMemoryRepository()
    app.dependency_overrides[get_repo] = lambda: r
    yield r
    app.dependency_overrides.clear()


@pytest.fixture
def client(repo):
    return TestClient(app)


def as_user(uid):
    return {"X-Dev-User": uid}


def add(client, uid, product, months_ago, **kw):
    body = {"card_product_id": product, "opened_on": add_months(TODAY, -months_ago).isoformat()}
    return client.post("/me/wallet/cards", json=body | kw, headers=as_user(uid))


# --- identity ---------------------------------------------------------------------------


def test_requests_without_identity_are_rejected(client):
    assert client.get("/me/wallet").status_code == 401


def test_malformed_dev_user_is_rejected(client):
    assert client.get("/me/wallet", headers=as_user("../../etc")).status_code == 400


def test_dev_header_is_ignored_outside_local(client, monkeypatch):
    monkeypatch.setattr(auth, "settings", Settings(env="aws"))
    assert client.get("/me/wallet", headers=as_user("mallory")).status_code == 401


def test_identity_comes_from_verified_jwt_claims_on_aws(client, monkeypatch):
    monkeypatch.setattr(auth, "settings", Settings(env="aws"))
    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {"claims": {"sub": "user-123", "cognito:groups": "[admin readers]"}}
            }
        }
    }

    class Req:
        scope = {"aws.event": event}

    caller = auth.current_caller(Req(), x_dev_user="someone-else")
    assert caller.uid == "user-123" and caller.is_admin  # the header can't override the JWT


# --- profile & wallet -------------------------------------------------------------------


def test_profile_roundtrip_and_range_only_fields(client):
    body = {"tax_id": "ITIN", "score_band": "670_739", "income_band": "25k_50k"}
    assert client.put("/me/profile", json=body, headers=as_user("ann")).status_code == 200
    assert client.get("/me/profile", headers=as_user("ann")).json()["tax_id"] == "ITIN"
    bad = client.put("/me/profile", json={"score_band": "712"}, headers=as_user("ann"))
    assert bad.status_code == 422  # exact scores are refused by design


def test_wallet_add_list_delete(client):
    card = add(client, "ann", "citi_double_cash", 5).json()
    wallet = client.get("/me/wallet", headers=as_user("ann")).json()
    assert [c["id"] for c in wallet["cards"]] == [card["id"]]
    assert (
        client.delete(f"/me/wallet/cards/{card['id']}", headers=as_user("ann")).status_code == 204
    )
    assert client.get("/me/wallet", headers=as_user("ann")).json()["cards"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"card_product_id": "no_such_card", "opened_on": "2025-01-01"},
        {"opened_on": "2025-01-01"},  # neither catalog id nor issuer+name
        {"card_product_id": "citi_double_cash", "opened_on": "2999-01-01"},
        {
            "card_product_id": "citi_double_cash",
            "opened_on": "2025-05-01",
            "closed_on": "2025-01-01",
        },
    ],
)
def test_invalid_cards_are_rejected(client, body):
    assert client.post("/me/wallet/cards", json=body, headers=as_user("ann")).status_code == 422


def test_off_catalog_cards_count_toward_velocity(client):
    add(client, "ann", None, 2, issuer_id="synchrony", name="Store card")
    assert client.get("/me/velocity", headers=as_user("ann")).json()["count_24m"] == 1


def test_users_cannot_touch_each_others_cards(client):
    card = add(client, "ann", "citi_double_cash", 5).json()
    assert (
        client.delete(f"/me/wallet/cards/{card['id']}", headers=as_user("bob")).status_code == 404
    )
    assert len(client.get("/me/wallet", headers=as_user("ann")).json()["cards"]) == 1
    assert client.get("/me/wallet", headers=as_user("bob")).json()["cards"] == []


def test_delete_me_purges_all_user_data(client):
    add(client, "ann", "citi_double_cash", 5)
    client.put("/me/profile", json={"tax_id": "SSN"}, headers=as_user("ann"))
    assert client.delete("/me", headers=as_user("ann")).status_code == 204
    assert client.get("/me/wallet", headers=as_user("ann")).json()["cards"] == []
    assert client.get("/me/profile", headers=as_user("ann")).json()["tax_id"] is None


# --- eligibility ------------------------------------------------------------------------


def _five_of_24(client, uid):
    for product, months in [
        ("citi_double_cash", 2),
        ("amex_blue_cash_everyday", 6),
        ("c1_venture_x", 10),
        ("discover_it_cash_back", 14),
        ("chase_freedom_unlimited", 20),
    ]:
        add(client, uid, product, months)
    client.put(
        "/me/wallet/attestation",
        json={
            "complete_since": add_months(TODAY, -24).isoformat(),
            "includes_all_open_cards": True,
        },
        headers=as_user(uid),
    )
    client.put("/me/profile", json={"tax_id": "SSN"}, headers=as_user(uid))


def test_eligibility_runs_the_rules_engine(client):
    _five_of_24(client, "ann")
    res = client.get(
        "/me/eligibility", params={"card_id": "chase_sapphire_preferred"}, headers=as_user("ann")
    )
    [verdict] = res.json()
    assert verdict["name"] == "Sapphire Preferred"
    assert verdict["application"]["status"] == "Ineligible"
    reason = next(r for r in verdict["application"]["reasons"] if r["rule_id"] == "chase_5_24")
    assert reason["retry_after"] == add_months(add_months(TODAY, -20), 24).isoformat()


def test_eligibility_defaults_to_open_cards_only(client):
    ids = {
        v["card_product_id"] for v in client.get("/me/eligibility", headers=as_user("ann")).json()
    }
    assert "amex_green" not in ids and "chase_sapphire_preferred" in ids


def test_velocity_reports_count_drop_off_and_completeness(client):
    _five_of_24(client, "ann")
    v = client.get("/me/velocity", headers=as_user("ann")).json()
    assert v["count_24m"] == 5 and v["complete"] is True
    assert v["next_drop_off"] == add_months(add_months(TODAY, -20), 24).isoformat()


# --- invites ----------------------------------------------------------------------------


def test_only_admins_create_invites(client):
    assert client.post("/admin/invites", json={}, headers=as_user("ann")).status_code == 403
    res = client.post("/admin/invites", json={"count": 2, "uses": 3}, headers=as_user("admin-1"))
    assert res.status_code == 201 and len(res.json()["codes"]) == 2


def test_signup_consumes_invite_uses(client, repo):
    repo.create_invite("ONE-USE", 1)
    assert client.post("/dev/signup", json={"invite_code": "one-use"}).status_code == 201
    assert client.post("/dev/signup", json={"invite_code": "ONE-USE"}).status_code == 403
    assert client.post("/dev/signup", json={"invite_code": "NOPE"}).status_code == 403


def test_concurrent_signups_cannot_oversubscribe_an_invite(client, repo):
    repo.create_invite("RACE", 3)
    with ThreadPoolExecutor(16) as pool:
        codes = list(
            pool.map(
                lambda _: client.post("/dev/signup", json={"invite_code": "RACE"}).status_code,
                range(40),
            )
        )
    assert codes.count(201) == 3


def test_demo_seed_has_invite_and_realistic_wallet():
    repo = InMemoryRepository()
    app_module.seed_demo(repo)
    assert repo.redeem_invite(app_module.DEMO_INVITE)
    assert len(repo.list_cards(app_module.DEMO_USER)) == 5
