import jwt
import pytest
from advisor.identity import NotSignedIn, caller_from


def token(**claims):
    return "Bearer " + jwt.encode(
        {"token_use": "access", "sub": "user-1", **claims},
        "test-secret-key-that-is-long-enough-32b",
        "HS256",
    )


def test_user_id_is_the_access_tokens_sub_and_the_token_is_forwarded():
    auth = token()
    caller = caller_from({"Authorization": auth})
    assert caller.user_id == "user-1" and caller.headers == {"Authorization": auth}


def test_id_tokens_and_garbage_are_rejected():
    with pytest.raises(NotSignedIn):
        caller_from({"authorization": token(token_use="id")})
    with pytest.raises(NotSignedIn):
        caller_from({"authorization": "Bearer not-a-jwt"})
    with pytest.raises(NotSignedIn):
        caller_from({})


def test_dev_user_needs_both_local_switches(monkeypatch):
    monkeypatch.setenv("ADVISOR_DEV_USER", "demo-user")
    with pytest.raises(NotSignedIn):
        caller_from({})  # ADVISOR_LOCAL not set: the deployed runtime never has it
    monkeypatch.setenv("ADVISOR_LOCAL", "1")
    assert caller_from({}).headers == {"X-Dev-User": "demo-user"}
    # a real token always wins over the dev switch
    assert caller_from({"Authorization": token()}).user_id == "user-1"


def test_local_dev_user_can_come_from_the_demo_site(monkeypatch):
    from advisor.identity import DEV_USER_HEADER

    monkeypatch.setenv("ADVISOR_DEV_USER", "demo-user")
    with pytest.raises(NotSignedIn):
        caller_from({DEV_USER_HEADER: "u-42"})  # never outside local dev
    monkeypatch.setenv("ADVISOR_LOCAL", "1")
    caller = caller_from({DEV_USER_HEADER.lower(): "u-42"})
    assert caller.user_id == "u-42" and caller.headers == {"X-Dev-User": "u-42"}
