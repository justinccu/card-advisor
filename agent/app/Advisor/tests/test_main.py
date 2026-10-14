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


def test_a_full_guest_day_is_a_quota_error_the_site_answers_with_sign_in(monkeypatch):
    from advisor.api import QuotaExceeded

    monkeypatch.setenv("ADVISOR_LOCAL", "1")
    monkeypatch.setenv("ADVISOR_DEV_USER", "guest-abc")

    class Api:
        def __init__(self, headers):
            pass

        def take_turn(self):
            raise QuotaExceeded(429, {"message": "all taken", "code": "guests_full", "guest": True})

    monkeypatch.setattr(main, "AdvisorApi", Api)
    monkeypatch.setattr(
        main, "get_session", lambda *a: (_ for _ in ()).throw(AssertionError("model used"))
    )
    [event] = run({"prompt": "hi"}, Ctx())
    assert event == {"type": "error", "code": "quota", "message": "all taken", "guest": True}


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
        if isinstance(prompt, list):  # messages: the user's, then lookups made before the model
            self.messages.extend(prompt)
        else:
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
                text = chunk.get("result", "closed")  # what the tool returned
                result = {"toolUseId": chunk["toolUseId"], "content": [{"text": text}]}
                self.messages.append({"role": "user", "content": [{"toolResult": result}]})
        text = "".join(c for c in chunks if isinstance(c, str))
        self.messages.append({"role": "assistant", "content": [{"text": text}]})


saved: list[dict] = []
costs: list[float] = []


def chat_with(monkeypatch, agent):
    saved.clear()
    costs.clear()
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

        def record_usage(self, cost):
            costs.append(cost)

    class FakeSession:
        api = None

    session = FakeSession()
    session.agent = agent
    session.timings = main.Timings()
    monkeypatch.setattr(main, "AdvisorApi", Api)
    monkeypatch.setattr(main, "get_session", lambda *a: session)
    return run({"prompt": "amex green?"}, Ctx())


def seen(events):
    """Event kinds the page acts on: all but "writing", which only moves the status line."""
    return [e["type"] for e in events if e["type"] != "writing"]


LEAK = ['I will check. {"name": "rank_cards", "arguments": {"monthly_spending": {"dining": 300}}}']


def test_a_tool_call_written_as_text_is_cleared_and_retried(monkeypatch):
    agent = FakeAgent(LEAK, ["The Green Card is closed to new applicants."])
    events = chat_with(monkeypatch, agent)
    # the leaked text never reached the page; "reset" tells it the answer is being redone
    assert seen(events) == ["quota", "reset", "text", "done"]
    assert [e["text"] for e in events if e["type"] == "text"] == [
        "The Green Card is closed to new applicants."
    ]
    assert "tool call as text" in agent.prompts[1]  # the retry is told what went wrong
    # the broken answer is gone from the conversation; only the retry's turn remains
    assert [m["role"] for m in agent.messages] == ["user", "assistant"]
    assert "rank_cards" not in agent.messages[1]["content"][0]["text"]


def test_a_second_leak_ends_the_answer_with_an_error(monkeypatch):
    events = chat_with(monkeypatch, FakeAgent(LEAK, ["<tool_call>{}</tool_call>"]))
    assert seen(events) == ["quota", "reset", "error"]
    assert len(costs) == 1  # a failed answer still costs, and is counted


def test_each_message_reports_its_cost_with_retries_included(monkeypatch):
    from model.load import MESSAGE_OVERHEAD_USD, message_cost

    class Metrics:
        accumulated_usage = {"inputTokens": 1000, "outputTokens": 100}

    agent = FakeAgent(LEAK, ["The Green Card is closed to new applicants."])
    agent.event_loop_metrics = Metrics()
    original = agent.stream_async

    async def stream(prompt):  # each model call adds 10k in / 500 out
        Metrics.accumulated_usage = {
            "inputTokens": Metrics.accumulated_usage["inputTokens"] + 10_000,
            "outputTokens": Metrics.accumulated_usage["outputTokens"] + 500,
        }
        async for event in original(prompt):
            yield event

    agent.stream_async = stream
    chat_with(monkeypatch, agent)
    assert costs == [message_cost(20_000, 1_000)]
    assert costs[0] == round(20_000 * 0.62e-6 + 1_000 * 1.85e-6 + MESSAGE_OVERHEAD_USD, 6)
    assert message_cost(10**9, 10**9, "some.new-model") == 1.0  # capped; unlisted priced high


def test_a_closed_guest_trial_asks_the_guest_to_sign_in(monkeypatch):
    from advisor.api import ApiError

    monkeypatch.setenv("ADVISOR_LOCAL", "1")
    monkeypatch.setenv("ADVISOR_DEV_USER", "guest-abc")

    class Api:
        def __init__(self, headers):
            pass

        def take_turn(self):
            raise ApiError(503, {"message": "The free trial is paused.", "code": "guests_closed"})

    monkeypatch.setattr(main, "AdvisorApi", Api)
    monkeypatch.setattr(
        main, "get_session", lambda *a: (_ for _ in ()).throw(AssertionError("model used"))
    )
    [event] = run({"prompt": "hi"}, Ctx())
    assert event == {"type": "error", "code": "signin", "message": "The free trial is paused."}


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
    # narration is dropped unseen; the answer arrives whole once checked
    assert seen(events) == ["quota", "tool", "text", "done"]
    assert [e["text"] for e in events if e["type"] == "text"] == ["It's closed to new applicants."]
    assert [e["type"] for e in events][:3] == ["quota", "writing", "tool"]  # status line moves
    assert not any("DSML" in e.get("text", "") or "Let me" in e.get("text", "") for e in events)
    assert [e for e in events if e["type"] == "tool"] == [
        {"type": "tool", "name": "get_card_details"}
    ]


def test_narration_between_calls_is_never_shown(monkeypatch):
    # DeepSeek once wrote a whole analysis before ranking cards; shown, then cleared when the
    # next call started, it read as the answer vanishing.
    agent = FakeAgent(
        [
            {"toolUseId": "a", "name": "get_card_details"},
            "Now the other card, which uses check_eligibility.",
            {"toolUseId": "b", "name": "get_card_details"},
            "Both are closed.",
        ]
    )
    events = chat_with(monkeypatch, agent)
    assert seen(events) == ["quota", "tool", "tool", "text", "done"]
    assert [e["text"] for e in events if e["type"] == "text"] == ["Both are closed."]
    assert len(agent.prompts) == 1  # an internal name in narration costs no retry


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
        [
            {"toolUseId": "t1", "name": "get_card_details", "result": "$325 a year"},
            "It's $325 a year.",
        ],
    )
    events = chat_with(monkeypatch, agent)
    assert seen(events) == ["quota", "reset", "tool", "text", "done"]
    assert not any("$250" in e.get("text", "") for e in events)  # the wrong fee never showed
    assert "without looking them up" in agent.prompts[1]
    retry = [m for m in agent.messages if m["role"] == "user"][0]["content"][0]["text"]
    assert "look this up with the tools and quote what they return.]" in retry
    assert retry.endswith("[No lookup gave these amounts: 250.]")
    assert saved[0]["answer"] == "It's $325 a year."
    assert saved[0]["question"] == "amex green?"  # the record keeps what the user typed


def test_amounts_from_the_user_or_earlier_lookups_need_no_new_lookup(monkeypatch):
    agent = FakeAgent(["With $600 on dining that works."])
    agent.messages = [
        {"role": "user", "content": [{"text": "I spend $600 on dining"}]},
        {"role": "user", "content": [{"toolResult": {"content": [{"text": "75,000 points"}]}}]},
    ]
    assert seen(chat_with(monkeypatch, agent)) == ["quota", "text", "done"]
    agent = FakeAgent(["That's the 75,000 points we saw."])
    agent.messages = [
        {"role": "user", "content": [{"toolResult": {"content": [{"text": "75,000 points"}]}}]}
    ]
    assert seen(chat_with(monkeypatch, agent)) == ["quota", "text", "done"]


def test_an_amount_no_lookup_returned_is_retried_once_after_a_lookup(monkeypatch):
    # DeepSeek checked eligibility, then gave the Reserve's old $550 fee ($795 in the catalog).
    agent = FakeAgent(
        [{"toolUseId": "t1", "name": "check_eligibility"}, "Yes. Its fee is $550."],
        [{"toolUseId": "t2", "name": "get_card_details"}, "Yes. Its fee is $795."],
    )
    agent.messages = [
        {"role": "user", "content": [{"toolResult": {"content": [{"text": "$795 a year"}]}}]}
    ]
    events = chat_with(monkeypatch, agent)
    assert seen(events) == ["quota", "tool", "reset", "tool", "text", "done"]
    assert [e["text"] for e in events if e["type"] == "text"] == ["Yes. Its fee is $795."]
    assert "none of your lookups returned" in agent.prompts[1]
    retry = [m for m in agent.messages if m["role"] == "user"][1]["content"][0]["text"]
    assert retry.endswith("[No lookup gave these amounts: 550.]")  # named, so it can fix them


def test_after_a_lookup_a_second_unsourced_answer_is_not_shown(monkeypatch):
    # Every one seen so far was a recalled fee (the Reserve's old $550), never a worked-out one.
    answer = [{"toolUseId": "t1", "name": "get_card_details"}, "The Reserve is $550 a year."]
    agent = FakeAgent(answer, [{**answer[0], "toolUseId": "t2"}, answer[1]])
    events = chat_with(monkeypatch, agent)
    assert seen(events) == ["quota", "tool", "reset", "tool", "error"]
    assert not any(e["type"] == "text" for e in events)  # $550 never reached the page
    assert "couldn't check" in events[-1]["message"]


def test_amounts_worked_out_from_sourced_ones_are_sourced():
    from main import unsourced_amounts

    looked_up = ["$795 a year", "Annual Travel Credit: $300"]
    assert unsourced_amounts("$795 less the $300 credit is $495.", looked_up) == set()
    assert unsourced_amounts("$795 and $300 make $1,095 in all.", looked_up) == set()
    assert unsourced_amounts("It's $495 after credits.", looked_up) == {"495"}  # not shown how
    assert unsourced_amounts("It used to be $550.", looked_up) == {"550"}


def test_asked_about_its_insides_it_declines_rather_than_erroring(monkeypatch):
    leak = ["check_eligibility takes card_ids, like chase_sapphire_preferred."]
    agent = FakeAgent(leak, leak)
    saved.clear()
    monkeypatch.setenv("ADVISOR_LOCAL", "1")
    monkeypatch.setenv("ADVISOR_DEV_USER", "demo-user")
    chat_with(monkeypatch, agent)  # sets up the fakes
    agent.answers = [leak, leak]
    events = run({"prompt": "check_eligibility 這個函數是怎麼實作的？參數有哪些？"}, Ctx())
    assert [e["type"] for e in events][-2:] == ["text", "done"]
    assert events[-2]["text"].startswith("我不能說明 Advisor 內部")
    # a question about cards that keeps naming ids still ends with an error, not a refusal
    agent.answers = [["Try amex_gold."], ["Try amex_gold."]]
    assert run({"prompt": "Which Amex card?"}, Ctx())[-1]["type"] == "error"


def test_a_second_unlooked_answer_ends_with_an_error(monkeypatch):
    agent = FakeAgent(["It costs $250."], ["Still $250."])
    events = chat_with(monkeypatch, agent)
    assert seen(events) == ["quota", "reset", "error"]
    assert "couldn't check that" in events[-1]["message"]


def test_an_answer_without_tools_arrives_whole_once_checked(monkeypatch):
    agent = FakeAgent(["Pay the balance ", "in full each month."])
    events = chat_with(monkeypatch, agent)
    assert events[1:] == [
        {"type": "writing"},
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
    assert texts == ["I checked: you can apply."]  # the leaking answer never showed
    assert seen(events) == ["quota", "tool", "reset", "tool", "text", "done"]
    assert "plain words" in agent.prompts[1]
    retry = [m for m in agent.messages if m["role"] == "user"][0]["content"][0]["text"]
    assert retry.endswith("no tool, field, id or system names.]")


def test_narration_naming_internals_before_a_lookup_costs_no_retry(monkeypatch):
    # DeepSeek: "Let me check amex_ladder_gold" before calling a tool. The page never shows it.
    agent = FakeAgent(
        [
            "Let me check amex_ladder_gold.",
            {"toolUseId": "t1", "name": "get_issuer_rules"},
            "Yes, if you've had the Platinum the Gold's offer still depends on the ladder.",
        ]
    )
    events = chat_with(monkeypatch, agent)
    assert seen(events) == ["quota", "tool", "text", "done"]
    assert len(agent.prompts) == 1  # answered on the first try
    assert "amex_ladder_gold" not in "".join(e.get("text", "") for e in events)


def test_an_answer_with_no_lookup_is_checked_whole_before_it_is_shown(monkeypatch):
    agent = FakeAgent(["Ask me about the ", "chase_5_24 rule."], ["Ask me about Chase 5/24."])
    events = chat_with(monkeypatch, agent)
    assert seen(events) == ["quota", "reset", "text", "done"]
    assert [e["text"] for e in events if e["type"] == "text"] == ["Ask me about Chase 5/24."]
    assert len(agent.prompts) == 2


def test_giving_up_speaks_the_reply_language(monkeypatch):
    agent = FakeAgent(LEAK, ["<tool_call>{}</tool_call>"])
    chat_with(monkeypatch, agent)  # an English question gives up in English...
    agent.answers = [LEAK, ["<tool_call>{}</tool_call>"]]
    events = run({"prompt": "推薦哪張卡？"}, Ctx())  # ...a Chinese one in Chinese
    assert events[-1] == {
        "type": "error",
        "code": "internal",
        "message": "Advisor 這次沒能回答，請再試一次。",
    }


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


# --- lookups made before the model runs ------------------------------------------------------


def chat_with_tools(
    monkeypatch, agent, prompt, profile='{"monthly_spending_usd": {"dining": 800}}'
):
    """chat_with, plus tools the prefetch can call (recording each call) and a one-card catalog."""
    calls = []

    def tool(name, result):
        def call(**args):
            calls.append((name, args))
            return result

        return call

    chat_with(monkeypatch, FakeAgent())  # installs the fake API and session
    session = main.get_session("s", "u")
    session.agent = agent
    session.tools = {
        "get_my_profile": tool("get_my_profile", profile),
        "get_my_wallet": tool("get_my_wallet", '{"five_24_status": "2/24"}'),
        "get_card_details": tool("get_card_details", '{"annual_fee": "$95 a year"}'),
        "check_eligibility": tool("check_eligibility", '[{"offer": "Eligible"}]'),
        "rank_cards": tool(
            "rank_cards", '{"ranked": [{"card": "Gold", "first_year_value": "$1,208"}]}'
        ),
    }
    csp = {"id": "chase_sapphire_preferred", "name": "Chase Sapphire Preferred"}

    class WithCatalog(main.AdvisorApi):
        def cards(self):
            return {csp["id"]: {**csp, "issuer_id": "chase", "aliases": ["CSP"]}}

        def issuers(self):
            return {"chase": {"name": "Chase"}}

    monkeypatch.setattr(main, "AdvisorApi", WithCatalog)
    return run({"prompt": prompt}, Ctx()), calls


def test_cards_a_message_names_are_found_conservatively():
    from advisor.search import mentioned

    cards = {
        "csp": {
            "id": "csp",
            "name": "Chase Sapphire Preferred",
            "issuer_id": "chase",
            "aliases": ["CSP"],
        },
        "csr": {
            "id": "csr",
            "name": "Chase Sapphire Reserve",
            "issuer_id": "chase",
            "aliases": ["CSR"],
        },
        "gold": {
            "id": "gold",
            "name": "American Express Gold Card",
            "issuer_id": "amex",
            "aliases": [],
        },
        "vx": {
            "id": "vx",
            "name": "Capital One Venture X",
            "issuer_id": "capital_one",
            "aliases": [],
        },
        "v": {"id": "v", "name": "Capital One Venture", "issuer_id": "capital_one", "aliases": []},
    }
    issuers = {
        "chase": {"name": "Chase"},
        "amex": {"name": "American Express", "aliases": ["Amex"]},
        "capital_one": {"name": "Capital One"},
    }

    def ids(text):
        return [c["id"] for c in mentioned(text, cards, issuers)]

    assert ids("我已經有 Chase Sapphire Preferred，還能申請 Sapphire Reserve 嗎？") == [
        "csp",
        "csr",
    ]
    assert ids("CSP vs CSR") == ["csp", "csr"]
    assert ids("is the amex gold worth it?") == ["gold"]
    assert ids("which gold card?") == []  # one word, no bank: not sure which card
    assert ids("Venture X or not") == ["vx"]  # not also the plain Venture
    assert ids("Which card fits my spending best?") == []


def test_the_profile_and_wallet_are_looked_up_before_the_model_runs(monkeypatch):
    # The model answers at once from them: no call of its own, and the amount it quotes ($800,
    # from the profile) counts as looked up, not as recalled.
    agent = FakeAgent(["With $800 a month on dining, that's 2/24 for Chase."])
    events, calls = chat_with_tools(monkeypatch, agent, "How do I build credit?")
    assert sorted(name for name, _ in calls) == ["get_my_profile", "get_my_wallet"]
    assert [m["role"] for m in agent.messages[:3]] == ["user", "assistant", "user"]
    assert "toolUse" in agent.messages[1]["content"][0]
    assert seen(events) == ["quota", "text", "done"]  # no retry for the $800
    assert {t["name"] for t in saved[0]["tools"]} == {"get_my_profile", "get_my_wallet"}


def test_named_cards_are_looked_up_and_checked_and_a_retry_does_not_fetch_again(monkeypatch):
    agent = FakeAgent(["It costs $550."], ["It costs $95 a year."])
    events, calls = chat_with_tools(monkeypatch, agent, "Is the CSP worth it?")
    names = [name for name, _ in calls]
    assert sorted(names) == [
        "check_eligibility",
        "get_card_details",
        "get_my_profile",
        "get_my_wallet",
    ]
    assert ("check_eligibility", {"card_ids": ["chase_sapphire_preferred"]}) in calls
    assert seen(events) == ["quota", "reset", "text", "done"]  # $550 was no lookup's
    assert len(calls) == 4  # the retry reused the lookups


def test_a_failed_lookup_is_left_to_the_model():
    from advisor import prefetch

    def broken(**args):
        raise TimeoutError

    done = prefetch.run({"get_my_profile": broken, "get_my_wallet": lambda: "{}"}, prefetch.ALWAYS)
    assert [name for name, _, _ in done] == ["get_my_wallet"]


def test_a_request_for_recommendations_is_ranked_before_the_model_runs(monkeypatch):
    agent = FakeAgent(["The Gold: $1,208 in the first year."])
    events, calls = chat_with_tools(monkeypatch, agent, "推薦一張適合我的卡")
    assert [name for name, _ in calls][-1] == "rank_cards"  # after the profile it reads
    assert seen(events) == ["quota", "text", "done"]  # $1,208 came from the ranking


def test_no_ranking_without_spending_or_when_cards_are_named(monkeypatch):
    agent = FakeAgent(["What do you spend each month?"])
    _, calls = chat_with_tools(
        monkeypatch, agent, "Which card is best for me?", profile='{"monthly_spending_usd": {}}'
    )
    assert "rank_cards" not in [name for name, _ in calls]  # the model asks for spending first
    agent = FakeAgent(["The CSP fits."])
    _, calls = chat_with_tools(monkeypatch, agent, "Which is better for me, the CSP?")
    assert "rank_cards" not in [name for name, _ in calls]  # the named card is looked up instead


def test_ids_written_as_text_are_put_in_words_instead_of_costing_a_retry(monkeypatch):
    from main import internal_names, plain_names

    rules = {"chase_sapphire_once_per_card": {"summary": "Chase Sapphire: once per card"}}
    cards = {"amex_gold": {"name": "American Express Gold Card"}}
    out = plain_names("根據 chase_sapphire_once_per_card 規則，other_travel 也算。", rules, cards)
    assert (
        out == "根據 [Chase Sapphire](rule:chase_sapphire_once_per_card) 規則，other travel 也算。"
    )
    assert plain_names("[amex_gold](card:amex_gold), `amex_gold`", rules, cards) == (
        "[American Express Gold Card](card:amex_gold), American Express Gold Card"
    )
    assert plain_names("See [Gold](card:amex_gold).", rules, cards) == "See [Gold](card:amex_gold)."
    # a link to an id that doesn't exist keeps its label only (the model once made one up)
    assert plain_names("Per [Citi's rule](rule:citi_made_up).", rules, cards) == "Per Citi's rule."
    assert plain_names("[A card](card:no_such_card)", rules, cards) == "A card"
    assert plain_names("[A card](card:no_such_card)", {}, {}) == "[A card](card:no_such_card)"
    # what isn't a rule, card or category still goes to the leak check
    assert internal_names(plain_names("I ran check_eligibility.", rules, cards)) == [
        "check_eligibility"
    ]

    # in a reply: the id is named, nothing is retried
    class Api:
        def __init__(self, headers):
            pass

        def take_turn(self):
            return {"limit": 30, "remaining": 29, "resets_at": "tomorrow"}

        def save_turn(self, record):
            return {"turn_id": "t"}

        def record_usage(self, cost):
            pass

        def rule_facts(self):
            return rules

        def cards(self):
            return cards

    class Session:
        api = None
        timings = main.Timings()
        agent = FakeAgent(
            [
                {"toolUseId": "t1", "name": "check_eligibility"},
                "Per chase_sapphire_once_per_card, no.",
            ]
        )

    monkeypatch.setenv("ADVISOR_LOCAL", "1")
    monkeypatch.setenv("ADVISOR_DEV_USER", "demo-user")
    monkeypatch.setattr(main, "AdvisorApi", Api)
    monkeypatch.setattr(main, "get_session", lambda *a: Session)
    events = run({"prompt": "Can I get the Sapphire bonus again?"}, Ctx())
    assert seen(events) == ["quota", "tool", "text", "done"]
    assert len(Session.agent.prompts) == 1  # answered the first time, no retry
    assert "[Chase Sapphire](rule:chase_sapphire_once_per_card)" in events[-2]["text"]
