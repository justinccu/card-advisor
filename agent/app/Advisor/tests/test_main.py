import asyncio

import main


class Ctx:
    def __init__(self, headers=None, session_id="s1"):
        self.request_headers = headers or {}
        self.session_id = session_id


def run(payload, ctx):
    async def collect():
        return [e async for e in main.invoke(payload, ctx)]

    return asyncio.run(collect())


def test_no_identity_no_model(monkeypatch):
    monkeypatch.setattr(
        main, "get_session", lambda *a: (_ for _ in ()).throw(AssertionError("model used"))
    )
    assert run({"prompt": "hi"}, Ctx())[0]["code"] == "auth"


def test_exhausted_quota_answers_without_calling_the_model(monkeypatch):
    from advisor.api import QuotaExceeded

    monkeypatch.setenv("ADVISOR_LOCAL", "1")
    monkeypatch.setenv("ADVISOR_DEV_USER", "demo-user")

    class Api:
        def __init__(self, headers):
            pass

        def take_turn(self):
            raise QuotaExceeded(
                429, {"message": "used up", "resets_at": "tomorrow", "remaining": 0}
            )

    monkeypatch.setattr(main, "AdvisorApi", Api)
    monkeypatch.setattr(
        main, "get_session", lambda *a: (_ for _ in ()).throw(AssertionError("model used"))
    )
    [event] = run({"prompt": "hi"}, Ctx())
    assert event == {
        "type": "error",
        "code": "quota",
        "message": "used up",
        "resets_at": "tomorrow",
        "remaining": 0,
    }


def test_bad_input_is_rejected_before_quota(monkeypatch):
    monkeypatch.setenv("ADVISOR_LOCAL", "1")
    monkeypatch.setenv("ADVISOR_DEV_USER", "demo-user")
    monkeypatch.setattr(
        main, "AdvisorApi", lambda *a: (_ for _ in ()).throw(AssertionError("quota used"))
    )
    assert run({"prompt": " "}, Ctx())[0]["code"] == "input"
    assert run({"prompt": "x" * 3000}, Ctx())[0]["code"] == "input"


def test_sessions_are_per_user(monkeypatch):
    monkeypatch.setattr(main, "Session", lambda sid, uid: object())
    main._sessions.clear()
    assert main.get_session("s", "alice") is not main.get_session("s", "mallory")
