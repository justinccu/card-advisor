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


def test_a_cards_dates_and_authorized_user_flag_can_be_corrected(client):
    card = add(client, "ann", "citi_double_cash", 5).json()
    url = f"/me/wallet/cards/{card['id']}"
    fixed = client.patch(url, json={"opened_on": "2025-03-14"}, headers=as_user("ann"))
    assert fixed.status_code == 200
    assert fixed.json()["opened_on"] == "2025-03-14" and fixed.json()["id"] == card["id"]
    closed = client.patch(url, json={"closed_on": "2025-09-01"}, headers=as_user("ann")).json()
    assert closed["closed_on"] == "2025-09-01" and closed["opened_on"] == "2025-03-14"
    reopened = client.patch(url, json={"closed_on": None}, headers=as_user("ann")).json()
    assert reopened["closed_on"] is None
    au = client.patch(url, json={"is_authorized_user": True}, headers=as_user("ann")).json()
    assert au["is_authorized_user"] is True
    wallet = client.get("/me/wallet", headers=as_user("ann")).json()["cards"]
    assert len(wallet) == 1 and wallet[0]["opened_on"] == "2025-03-14"


@pytest.mark.parametrize(
    "patch",
    [{"opened_on": "2999-01-01"}, {"closed_on": "2020-01-01"}, {"opened_on": "not-a-date"}],
)
def test_card_corrections_are_validated_like_new_cards(client, patch):
    card = add(client, "ann", "citi_double_cash", 5).json()
    r = client.patch(f"/me/wallet/cards/{card['id']}", json=patch, headers=as_user("ann"))
    assert r.status_code == 422


def test_the_site_may_send_every_method_the_wallet_uses(client):
    # Browsers preflight PATCH and DELETE: a method missing here fails only in the browser.
    for method in ("POST", "PATCH", "DELETE"):
        r = client.options(
            "/me/wallet/cards/x",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert r.status_code == 200, method


def test_users_cannot_edit_each_others_cards(client):
    card = add(client, "ann", "citi_double_cash", 5).json()
    r = client.patch(
        f"/me/wallet/cards/{card['id']}", json={"opened_on": "2025-01-01"}, headers=as_user("bob")
    )
    assert r.status_code == 404


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
    body = res.json()
    assert body["catalog_version"] == "1.1" and res.headers["X-Catalog-Version"] == "1.1"
    [verdict] = body["evaluations"]
    assert verdict["name"] == "Sapphire Preferred"
    assert verdict["application"]["status"] == "Ineligible"
    reason = next(r for r in verdict["application"]["reasons"] if r["rule_id"] == "chase_5_24")
    assert reason["retry_after"] == add_months(add_months(TODAY, -20), 24).isoformat()


def test_eligibility_defaults_to_open_cards_only(client):
    ids = {
        v["card_product_id"]
        for v in client.get("/me/eligibility", headers=as_user("ann")).json()["evaluations"]
    }
    assert "amex_green" not in ids and "chase_sapphire_preferred" in ids


def test_velocity_reports_count_drop_off_and_completeness(client):
    _five_of_24(client, "ann")
    v = client.get("/me/velocity", headers=as_user("ann")).json()
    assert v["count_24m"] == 5 and v["complete"] is True
    assert v["next_drop_off"] == add_months(add_months(TODAY, -20), 24).isoformat()


def test_requests_can_pin_a_catalog_version(client):
    ok = client.get("/me/velocity", params={"catalog_version": "1.1"}, headers=as_user("ann"))
    assert ok.status_code == 200 and ok.headers["X-Catalog-Version"] == "1.1"
    missing = client.get(
        "/me/eligibility", params={"catalog_version": "9.9"}, headers=as_user("ann")
    )
    assert missing.status_code == 404
    bad = client.get("/catalog", params={"catalog_version": "latest"})
    assert bad.status_code == 422


def test_pinned_catalog_is_cached_forever_and_latest_briefly(client):
    pinned = client.get("/catalog", params={"catalog_version": "1.1"})
    assert "immutable" in pinned.headers["Cache-Control"]
    assert client.get("/catalog").headers["Cache-Control"] == "public, max-age=60"


# --- invites ----------------------------------------------------------------------------


def test_only_admins_create_invites(client):
    assert client.post("/admin/invites", json={}, headers=as_user("ann")).status_code == 403
    res = client.post("/admin/invites", json={"count": 2, "uses": 3}, headers=as_user("admin-1"))
    assert res.status_code == 201 and len(res.json()["codes"]) == 2
    assert client.get("/admin/invites", headers=as_user("ann")).status_code == 403
    listed = client.get("/admin/invites", headers=as_user("admin-1")).json()
    assert {i["code"] for i in listed} == set(res.json()["codes"])
    assert all(i["remaining"] == 3 and i["uses"] == [] for i in listed)


def test_invite_codes_are_unguessable_and_typo_tolerant():
    from card_api import invites

    codes = {invites.new_code() for _ in range(2000)}
    assert len(codes) == 2000
    for code in list(codes)[:50]:
        assert code.startswith("CA") and len(code) == 14
        assert set(code[2:]) <= set(invites.ALPHABET) and not set("ILOU") & set(code[2:])
        shown = invites.display(code)  # CA-XXXX-XXXX-XXXX
        assert len(shown) == 17 and invites.normalize(f" {shown.lower()} ") == code
    assert len(invites.ALPHABET) ** invites.SYMBOLS >= 2**60


def test_signup_consumes_invite_uses(client, repo):
    repo.create_invite("ONEUSE", 1)
    first = client.post("/dev/signup", json={"invite_code": "one-use"})
    assert first.status_code == 201
    assert client.post("/dev/signup", json={"invite_code": "ONE-USE"}).status_code == 403
    assert client.post("/dev/signup", json={"invite_code": "NOPE"}).status_code == 403
    [use] = repo.list_invites()[0].uses
    assert use.user == first.json()["user_id"] and use.confirmed_at is not None


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
    from card_api import invites

    repo = InMemoryRepository()
    app_module.seed_demo(repo)
    assert repo.redeem_invite(invites.normalize(app_module.DEMO_INVITE), "someone")
    assert len(repo.list_cards(app_module.DEMO_USER)) == 5


def test_demo_invite_exists_only_in_the_local_in_memory_store(monkeypatch):
    """AWS (DynamoDB) must never get the public demo code."""
    import dataclasses

    from card_api import repository

    created = []
    monkeypatch.setattr(
        app_module, "settings", dataclasses.replace(app_module.settings, table_name="t")
    )
    monkeypatch.setattr(
        repository.DynamoRepository, "__init__", lambda self, name, **kw: created.append(name)
    )
    monkeypatch.setattr(
        repository.DynamoRepository,
        "create_invite",
        lambda *a: pytest.fail("seeded an invite into DynamoDB"),
        raising=False,
    )
    get_repo.cache_clear()
    try:
        assert isinstance(get_repo(), repository.DynamoRepository) and created == ["t"]
    finally:
        get_repo.cache_clear()


def test_settings_import_outside_the_repo_like_on_lambda(tmp_path):
    """On Lambda the package sits at /var/task/card_api/: importing settings must not assume a
    repo checkout around it (this crashed every cold start of the first deploy)."""
    from pathlib import Path

    from card_api.settings import REPO_ROOT, repo_root

    assert repo_root(Path("/var/task/card_api/settings.py")) == Path.cwd()
    assert (REPO_ROOT / "catalog" / "us").is_dir()  # in the repo: still finds the checkout


# --- recommendations (ADR 0009) ---------------------------------------------------------


def test_recommendations_ask_for_spending_first(client):
    body = client.post("/me/recommendations", headers=as_user("ann")).json()
    assert body["needs"] == ["spending"] and body["cards"] == []


def test_recommendations_rank_by_the_spending_profile(client):
    client.put(
        "/me/profile",
        json={
            "tax_id": "SSN",
            "spending": {
                "monthly_usd": {"dining": 500, "everything_else": 500},
                "goals": ["earn_offers"],
            },
        },
        headers=as_user("ann"),
    )
    res = client.post("/me/recommendations", headers=as_user("ann"))
    body = res.json()
    assert (
        res.status_code == 200
        and body["catalog_version"] == "1.1"
        and body["sort_by"] == "first_year"
    )
    top = body["cards"][0]
    # CSP: 75,000 x 1¢ + 3x dining ($180) + 1x other ($60) - $95 fee
    assert top["card_id"] == "chase_sapphire_preferred"
    assert top["first_year_value_usd"] == 750 + 180 + 60 - 95
    # rates the model can't see are never invented: cards without rates earn $0
    assert all(c["card_id"] != "amex_green" for c in body["cards"])  # closed cards never ranked


def test_recommendation_options_are_validated(client):
    res = client.post("/me/recommendations", json={"limit": "many"}, headers=as_user("ann"))
    assert res.status_code == 422


# --- Advisor chat quota (ADR 0009) ------------------------------------------------------


def test_chat_quota_counts_down_and_stops_at_ten(client, monkeypatch):
    from datetime import datetime

    monkeypatch.setattr(
        app_module, "_now", lambda: datetime(2026, 9, 28, 23, 30, tzinfo=app_module.CHAT_TIMEZONE)
    )
    assert client.get("/me/chat/quota", headers=as_user("ann")).json()["remaining"] == 10
    for i in range(10):
        res = client.post("/me/chat/turn", headers=as_user("ann"))
        assert res.status_code == 200 and res.json()["remaining"] == 9 - i
    blocked = client.post("/me/chat/turn", headers=as_user("ann"))
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["resets_at"] == "2026-09-29T00:00:00-04:00"
    # other users are unaffected
    assert client.post("/me/chat/turn", headers=as_user("bob")).json()["remaining"] == 9


def test_chat_quota_resets_at_midnight_us_eastern_not_utc(client, monkeypatch):
    from datetime import datetime

    et = app_module.CHAT_TIMEZONE
    # 11:30 PM ET on the 28th is already the 29th in UTC; it must still count toward the 28th.
    monkeypatch.setattr(app_module, "_now", lambda: datetime(2026, 9, 28, 23, 30, tzinfo=et))
    for _ in range(10):
        client.post("/me/chat/turn", headers=as_user("ann"))
    assert client.post("/me/chat/turn", headers=as_user("ann")).status_code == 429
    monkeypatch.setattr(app_module, "_now", lambda: datetime(2026, 9, 29, 0, 1, tzinfo=et))
    assert client.post("/me/chat/turn", headers=as_user("ann")).json()["remaining"] == 9


def test_recommendations_accept_a_what_if_without_saving_it(client):
    # No saved profile yet: a first chat can still get a ranking from the conversation's numbers.
    what_if = {
        "scenario": {
            "monthly_usd": {"dining": 500, "everything_else": 500},
            "goals": ["earn_offers"],
        }
    }
    body = client.post("/me/recommendations", json=what_if, headers=as_user("ann")).json()
    assert body["scenario"] is True and body["needs"] == []
    assert body["cards"][0]["card_id"] == "chase_sapphire_preferred"
    assert body["spending_used"]["monthly_usd"] == {"dining": 500.0, "everything_else": 500.0}
    # nothing was written to the profile
    assert client.get("/me/profile", headers=as_user("ann")).json()["spending"] is None


def test_rules_are_explained_from_the_rules_data(client):
    rules = client.get("/rules?issuer_id=amex", headers=as_user("ann")).json()["rules"]
    assert rules and {r["issuer_id"] for r in rules} == {"amex"}
    ladder = next(r for r in rules if r["rule_id"] == "amex_ladder_gold")
    assert ladder["decides"] == "welcome offer"
    assert any("ever held any of" in fact for fact in ladder["how_it_counts"])


def test_delete_me_deletes_nothing_when_the_advisor_memory_cant_be_purged(client, monkeypatch):
    from card_api import app as app_module

    class Memory:
        def __init__(self, failed):
            self.failed = failed

        def get_paginator(self, name):
            key = {"list_memory_records": "memoryRecordSummaries"}.get(name, "sessionSummaries")
            items = [{"memoryRecordId": "r1"}] if name == "list_memory_records" else []

            class Pages:
                def paginate(self, **kw):
                    yield {key: items}

            return Pages()

        def batch_delete_memory_records(self, memoryId, records):
            return {"failedRecords": records if self.failed else []}

    client.put("/me/profile", json={"tax_id": "SSN"}, headers=as_user("ann"))
    monkeypatch.setattr(app_module, "settings", type(app_module.settings)(advisor_memory_id="m"))
    monkeypatch.setattr(app_module, "memory_client", lambda: Memory(failed=True))
    assert client.delete("/me", headers=as_user("ann")).status_code == 503
    assert client.get("/me/profile", headers=as_user("ann")).json()["tax_id"] == "SSN"

    monkeypatch.setattr(app_module, "memory_client", lambda: Memory(failed=False))
    assert client.delete("/me", headers=as_user("ann")).status_code == 204
    assert client.get("/me/profile", headers=as_user("ann")).json()["tax_id"] is None
