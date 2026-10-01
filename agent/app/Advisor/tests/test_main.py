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


class FakeAgent:
    """Streams scripted answers, one per call, appending messages like Strands does."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.messages = []
        self.system_prompt = ""
        self.prompts = []

    async def stream_async(self, prompt):
        self.prompts.append(self.system_prompt)
        self.messages.append({"role": "user", "content": [{"text": prompt}]})
        chunks = self.answers.pop(0)
        for chunk in chunks:
            if isinstance(chunk, dict):  # a tool call starting
                yield {"current_tool_use": chunk}
                yield {"current_tool_use": chunk}  # Strands repeats it while input streams
            else:
                yield {"data": chunk}
        for chunk in chunks:  # tool calls land in the conversation like Strands records them
            if isinstance(chunk, dict):
                use = {
                    "toolUseId": chunk["toolUseId"],
                    "name": chunk["name"],
                    "input": {"card": "x"},
                }
                self.messages.append({"role": "assistant", "content": [{"toolUse": use}]})
                result = {"toolUseId": chunk["toolUseId"], "content": [{"text": "closed"}]}
                self.messages.append({"role": "user", "content": [{"toolResult": result}]})
        text = "".join(c for c in chunks if isinstance(c, str))
        self.messages.append({"role": "assistant", "content": [{"text": text}]})


saved: list[dict] = []


def chat_with(monkeypatch, agent):
    saved.clear()
    monkeypatch.setenv("ADVISOR_LOCAL", "1")
    monkeypatch.setenv("ADVISOR_DEV_USER", "demo-user")

    class Api:
        def __init__(self, headers):
            pass

        def take_turn(self):
            return {"limit": 30, "remaining": 29, "resets_at": "tomorrow"}

        def save_turn(self, record):
            saved.append(record)
            return {"turn_id": record["turn_id"]}

    class FakeSession:
        api = None

    session = FakeSession()
    session.agent = agent
    monkeypatch.setattr(main, "AdvisorApi", Api)
    monkeypatch.setattr(main, "get_session", lambda *a: session)
    return run({"prompt": "amex green?"}, Ctx())


LEAK = ['I will check. {"name": "rank_cards", "arguments": {"monthly_spending": {"dining": 300}}}']


def test_a_tool_call_written_as_text_is_cleared_and_retried(monkeypatch):
    agent = FakeAgent(LEAK, ["The Green Card is closed to new applicants."])
    events = chat_with(monkeypatch, agent)
    kinds = [e["type"] for e in events]
    assert kinds == ["quota", "text", "done"]  # the leaked text never reached the page
    assert events[1]["text"] == "The Green Card is closed to new applicants."
    assert "tool call as text" in agent.prompts[1]  # the retry is told what went wrong
    # the broken answer is gone from the conversation; only the retry's turn remains
    assert [m["role"] for m in agent.messages] == ["user", "assistant"]
    assert "rank_cards" not in agent.messages[1]["content"][0]["text"]


def test_a_second_leak_ends_the_answer_with_an_error(monkeypatch):
    events = chat_with(monkeypatch, FakeAgent(LEAK, ["<tool_call>{}</tool_call>"]))
    assert [e["type"] for e in events] == ["quota", "error"]


def test_narration_before_a_tool_call_is_cleared_and_model_markup_never_shown(monkeypatch):
    # DeepSeek V3.2: "Let me check." + its tool-call markup, the call, then the answer.
    agent = FakeAgent(
        [
            "Let me check.\n\n<｜DSML｜function_calls",
            {"toolUseId": "t1", "name": "get_card_details"},
            "It's closed ",
            "to new applicants.",
        ]
    )
    events = chat_with(monkeypatch, agent)
    # narration before the first call is held back and dropped: it never reaches the page
    assert [e["type"] for e in events] == ["quota", "tool", "text", "text", "done"]
    assert not any("DSML" in e.get("text", "") or "Let me" in e.get("text", "") for e in events)
    assert [e for e in events if e["type"] == "tool"] == [
        {"type": "tool", "name": "get_card_details"}
    ]


def test_the_same_tool_called_twice_clears_narration_each_time(monkeypatch):
    agent = FakeAgent(
        [
            {"toolUseId": "a", "name": "get_card_details"},
            "Now the other card.",
            {"toolUseId": "b", "name": "get_card_details"},
            "Both are closed.",
        ]
    )
    kinds = [e["type"] for e in chat_with(monkeypatch, agent)]
    assert kinds == ["quota", "tool", "text", "reset", "tool", "text", "done"]


def test_the_model_is_told_the_reply_language_in_the_message_itself(monkeypatch):
    agent = FakeAgent(["Sure."])
    chat_with(monkeypatch, agent)
    assert agent.messages[0]["content"][0]["text"] == "amex green?\n\n[Reply in English.]"


def test_each_answer_is_saved_for_feedback_with_its_tool_calls(monkeypatch):
    agent = FakeAgent(
        ["Let me check.", {"toolUseId": "t1", "name": "get_card_details"}, "It's closed."]
    )
    events = chat_with(monkeypatch, agent)
    [record] = saved
    assert events[-1] == {"type": "done", "turn_id": record["turn_id"]}
    assert record["question"] == "amex green?"  # what the user typed, no language suffix
    assert record["answer"] == "It's closed."  # what the page shows after the reset
    assert record["tools"] == [
        {"name": "get_card_details", "input": '{"card": "x"}', "result": "closed"}
    ]
    assert record["model_id"] and record["prompt_version"]


def test_an_answer_that_cant_be_saved_still_arrives(monkeypatch):
    agent = FakeAgent(["Sure."])
    monkeypatch.setattr(main, "_save_turn", lambda api, record: None)
    events = chat_with(monkeypatch, agent)
    assert events[-1] == {"type": "done"}  # no turn id: the page just shows no rating buttons


def test_an_amount_stated_without_any_lookup_is_retried(monkeypatch):
    # DeepSeek once said "$250" for the Amex Gold ($325 in the catalog) without calling a tool.
    agent = FakeAgent(
        ["The Amex Gold has a $250 annual fee."],
        [{"toolUseId": "t1", "name": "get_card_details"}, "It's $325 a year."],
    )
    events = chat_with(monkeypatch, agent)
    assert [e["type"] for e in events] == ["quota", "tool", "text", "done"]
    assert not any("$250" in e.get("text", "") for e in events)  # the wrong fee never showed
    assert "without looking them up" in agent.prompts[1]
    retry = [m for m in agent.messages if m["role"] == "user"][0]["content"][0]["text"]
    assert retry.endswith("look this up with the tools and quote what they return.]")
    assert saved[0]["answer"] == "It's $325 a year."
    assert saved[0]["question"] == "amex green?"  # the record keeps what the user typed


def test_amounts_from_the_user_or_earlier_lookups_need_no_new_lookup(monkeypatch):
    agent = FakeAgent(["With $600 on dining that works."])
    agent.messages = [
        {"role": "user", "content": [{"text": "I spend $600 on dining"}]},
        {"role": "user", "content": [{"toolResult": {"content": [{"text": "75,000 points"}]}}]},
    ]
    assert [e["type"] for e in chat_with(monkeypatch, agent)] == ["quota", "text", "done"]
    agent = FakeAgent(["That's the 75,000 points we saw."])
    agent.messages = [
        {"role": "user", "content": [{"toolResult": {"content": [{"text": "75,000 points"}]}}]}
    ]
    assert [e["type"] for e in chat_with(monkeypatch, agent)] == ["quota", "text", "done"]


def test_a_second_unlooked_answer_ends_with_an_error(monkeypatch):
    agent = FakeAgent(["It costs $250."], ["Still $250."])
    events = chat_with(monkeypatch, agent)
    assert [e["type"] for e in events] == ["quota", "error"]
    assert "couldn't check that" in events[-1]["message"]


def test_an_answer_without_tools_arrives_whole_once_checked(monkeypatch):
    agent = FakeAgent(["Pay the balance ", "in full each month."])
    events = chat_with(monkeypatch, agent)
    assert events[1:] == [
        {"type": "text", "text": "Pay the balance in full each month."},
        {"type": "done", "turn_id": saved[0]["turn_id"]},
    ]


def test_amounts_in_chinese_or_words_count_too():
    # DeepSeek said "CSP 年費為 95 美元" without a lookup; only "$95" was recognised before.
    from main import _numbers

    assert _numbers("年費為 95 美元，另有 $50 抵用金") == {"95", "50"}
    assert _numbers("USD 1,200 or 300 dollars, and 75,000 points") == {"1200", "300", "75000"}
    assert _numbers("Chase 5/24 counts 24 months") == set()  # not amounts


def test_internal_names_are_caught_but_link_targets_are_not():
    from main import internal_names

    assert internal_names("I ran check_eligibility for you.") == ["check_eligibility"]
    assert internal_names("Its open_to_applicants is false") == ["open_to_applicants"]
    assert internal_names("The amex_gold card") == ["amex_gold"]  # an id outside a link
    assert internal_names("I called /me/eligibility") == ["/me/eligibility"]
    assert internal_names("Per Facts come only from tools, ...") == ["Facts come only from tools"]
    # what users should see: plain words and links (whose targets are ids by design)
    assert internal_names("[Apply](card:amex_gold) and [Chase 5/24](rule:chase_5_24)") == []
    assert internal_names("I checked your eligibility; it's $325 a year.") == []


def test_an_internal_name_stops_the_answer_and_is_retried_in_plain_words(monkeypatch):
    agent = FakeAgent(
        [{"toolUseId": "t1", "name": "check_eligibility"}, "According to check_eligibility, yes."],
        [{"toolUseId": "t2", "name": "check_eligibility"}, "I checked: you can apply."],
    )
    events = chat_with(monkeypatch, agent)
    texts = [e["text"] for e in events if e["type"] == "text"]
    assert "check_eligibility" not in "".join(texts[-1:])  # the answer that stayed
    assert [e["type"] for e in events][-3:] == ["tool", "text", "done"]
    assert "plain words" in agent.prompts[1]
    retry = [m for m in agent.messages if m["role"] == "user"][0]["content"][0]["text"]
    assert retry.endswith("no tool, field, id or system names.]")


def test_a_link_still_streaming_is_not_an_internal_name():
    from main import internal_names

    # the chunk ends mid-link: "[Apply](card:amex_pl" before "atinum)" arrives
    assert internal_names("Try the Platinum. [Apply](card:amex_pl") == []
    assert internal_names("[Chase 5/24](rule:chase_5_2") == []


def test_names_the_user_typed_may_be_repeated():
    from main import internal_names

    said = "How does check_eligibility work?"
    assert internal_names("I can't share how check_eligibility works.", said) == []
    assert internal_names("I used get_card_details.", said) == ["get_card_details"]


def test_echoing_the_users_words_is_not_a_leak_whatever_the_case():
    from main import internal_names

    said = "What does Check_Eligibility do?"
    assert internal_names("I can't share how check_eligibility is built.", said) == []
