"""The Advisor on AgentCore Runtime (ADR 0009).

Each request: identify the caller from the verified token, take one message from today's quota
(before any model call), then stream the agent's answer as small JSON events the site renders:

    {"type": "quota", "limit": 30, "remaining": 29, "resets_at": "...", "guest": false}
    {"type": "tool", "name": "rank_cards"}        # a tool started (for a progress hint)
    {"type": "text", "text": "..."}               # answer text, streamed
    {"type": "reset"}                             # discard the answer text so far (a retry follows)
    {"type": "error", "code": "quota" | "auth" | "signin" | "input" | "internal", "message": "..."}
    {"type": "done", "turn_id": "..."}            # turn_id: rate this answer (absent if not saved)
"""

import json
import logging
import os
import re
import time
import uuid
from collections import OrderedDict

from advisor import prefetch
from advisor.api import AdvisorApi, ApiError, QuotaExceeded, catalog_version, rules_version
from advisor.identity import NotSignedIn, caller_from
from advisor.prompt import (
    PROMPT_HEADINGS,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    TRADITIONAL_CHINESE,
    reply_language,
    system_prompt_for,
    typed,
    with_language,
)
from advisor.tools import build_tools
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from memory.session import get_memory_session_manager
from model.load import MODEL_ID, load_model, message_cost
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from timing import Timings


def _local_cors() -> list[Middleware]:
    """The demo site on :3000 calls `agentcore dev` on :8080 directly. Deployed, the AgentCore
    endpoint answers CORS itself, so this is local only."""
    if os.environ.get("ADVISOR_LOCAL") != "1":
        return []
    origins = os.environ.get("ADVISOR_CORS_ORIGINS", "http://localhost:3000").split(",")
    return [
        Middleware(
            CORSMiddleware, allow_origins=origins, allow_methods=["POST"], allow_headers=["*"]
        )
    ]


app = BedrockAgentCoreApp(middleware=_local_cors())
log = app.logger
# Cutting a model stream short (a retry) closes Strands' generator in another async context, and
# OpenTelemetry logs a traceback for each span it can't detach. Harmless: the span just ends
# there. Keep real errors from that logger.
logging.getLogger("opentelemetry.context").setLevel(logging.CRITICAL)

# Qwen sometimes writes a tool call into its reply instead of making it
# ('{"name": "rank_cards", "arguments": {...}} </tool_call>').
LEAKED_TOOL_CALL = re.compile(r'</?tool_call>|\{\s*"name"\s*:\s*"\w+"\s*,\s*"arguments"\s*:')
# DeepSeek's tool-call markup can surface in the text stream even when the call itself works
# ("<｜DSML｜function_calls"); it is never part of an answer.
MODEL_MARKUP = re.compile(r"</?｜DSML｜[A-Za-z_]*>?|<｜[^｜<>\n]{1,40}｜>")
# Names users must never see: tools and fields (snake_case, which also catches card and rule
# ids written outside a link), API paths, and the system prompt's own headings. Deterministic,
# so it doesn't depend on the model following the "no tool names" rule.
# A link target, closed or still streaming ("[Apply](card:amex_pl" before the rest arrives).
_LINK_TARGET = re.compile(r"\]\((?:card|rule):[^)\s]*(?:\)|$)")
_INTERNAL = re.compile(
    r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b|/me/[\w/-]*|/(?:rules|catalog)\b|"
    + "|".join(re.escape(h) for h in PROMPT_HEADINGS)
)


def internal_names(text: str, said: str = "") -> list[str]:
    """Internal names in a reply, except those the user typed (repeating the user's own words
    reveals nothing; how a tool works still mustn't be explained, which the prompt covers)."""
    allowed = {n.lower() for n in _INTERNAL.findall(said.lower())}
    return [n for n in _INTERNAL.findall(_LINK_TARGET.sub("]", text)) if n.lower() not in allowed]


# Spending categories whose ids have an underscore (card_rules.catalog.SpendCategory), as words.
CATEGORY_WORDS = {
    "other_travel": "other travel",
    "gas_ev": "gas & EV charging",
    "online_shopping": "online shopping",
    "everything_else": "everything else",
}
_LINKED = re.compile(r"\((?:card|rule):[^)\s]*\)")
_HTTP_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BARE_URL = re.compile(r"(?:https?://|www\.)[^\s<>()\[\]]+")
_ANY_LINK = re.compile(r"\[([^\]]+)\]\((rule|card):([^)\s]+)\)")
_ID_AS_LABEL = re.compile(r"\[`?([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`?\]\(((?:card|rule):[^)\s]+)\)")
_BARE_ID = re.compile(r"`?\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b`?")


def rule_label(facts: dict) -> str:
    """A rule as the page names it: its summary's subject ("Chase 5/24"). No "rule" after it:
    the reply around an id already says "the ... rule" or "... 規則"."""
    summary = facts.get("summary") or ""
    return summary.split(":")[0].strip() if ":" in summary else summary


def plain_names(text: str, rules: dict[str, dict], cards: dict[str, dict]) -> str:
    """Ids a reply writes as plain text, put in words before the leak check: a rule id becomes
    its citation (the page shows it as the rule's label), a card id the card's name, a spending
    category its words, and a URL the card's own link (the page lists only catalog links) or
    "[link removed]", as the page does: asked for "the full https link", DeepSeek wrote the Amex
    Gold's from memory. Each id was a retry of the whole answer (7-10s): DeepSeek copied
    "chase_sapphire_once_per_card" and "other_travel" from tool results into its text. A link to
    an id that doesn't exist keeps only its label, as the page shows it: the model once cited a
    "rule:citi_one_bonus_per_card_48_months" it made up. Other internal names (tools, fields, API
    paths) are still left to the leak check."""

    def word(name: str) -> str | None:
        if name in rules:
            return f"[{rule_label(rules[name])}](rule:{name})"
        if name in cards:
            return cards[name].get("name") or None
        return CATEGORY_WORDS.get(name)

    # An id used as a link's label: keep the link, name it properly.
    def relabel(m: re.Match) -> str:
        name, target = m.group(1), m.group(2)
        label = rule_label(rules[name]) if name in rules else (cards.get(name) or {}).get("name")
        return f"[{label}]({target})" if label else m.group(0)

    by_url = {_bare(c["url"]): c for c in cards.values() if c.get("url")}

    def web_link(m: re.Match) -> str:  # [label](https://...)
        card = by_url.get(_bare(m.group(2)))
        return f"[{m.group(1)}](card:{card['id']})" if card else m.group(1)

    def bare_url(m: re.Match) -> str:
        url = m.group(0).rstrip(".,;:!?'\"")
        card = by_url.get(_bare(url))
        shown = f"[{card['name']}](card:{card['id']})" if card else "[link removed]"
        return shown + m.group(0)[len(url) :]

    text = _BARE_URL.sub(bare_url, _HTTP_LINK.sub(web_link, text))

    def known_or_label(m: re.Match) -> str:
        label, kind, name = m.group(1), m.group(2), m.group(3)
        known = rules if kind == "rule" else cards
        return label if known and name not in known else m.group(0)

    text = _ANY_LINK.sub(known_or_label, text)
    text = _ID_AS_LABEL.sub(relabel, text)
    # Link targets are ids by design: set them aside while the rest is rewritten.
    targets: list[str] = []

    def hide(m: re.Match) -> str:
        targets.append(m.group(0))
        return f"\x00{len(targets) - 1}\x00"

    text = _LINKED.sub(hide, text)
    text = _BARE_ID.sub(lambda m: word(m.group(1)) or m.group(0), text)
    return re.sub("\x00(\\d+)\x00", lambda m: targets[int(m.group(1))], text)


def _bare(url: str) -> str:
    """A URL compared without scheme, www., query, fragment or trailing slash."""
    url = re.sub(r"^(?:https?://)?(?:www\.)?", "", url.lower())
    return re.split(r"[?#]", url)[0].rstrip("/")


def _known_names(session: "Session") -> tuple[dict, dict]:
    """The rules and cards whose ids `plain_names` can put in words (both cached by the API
    client); none when they can't be read, which leaves every id to the leak check."""
    try:
        return session.api.rule_facts(), session.api.cards()
    except Exception:  # noqa: BLE001
        return {}, {}


INTERNAL_HINT = (
    "\nYour previous reply named internal things (tool names, field names, ids, API paths). "
    'Describe what you did in plain words, such as "I checked your eligibility".'
)
RETRY_HINT = (
    "\nYour previous reply wrote a tool call as text. Call tools only through tool use; "
    "never write a tool call in the reply."
)
MAX_PROMPT_CHARS = 2000
MAX_SESSIONS = 200  # agents kept warm per runtime process
WINDOW_MESSAGES = 20  # conversation turns sent to the model (bounds tokens per request)


class Session:
    """One user's conversation. `api` is replaced on every request, so tools always call the API
    with the caller's current token."""

    def user_said(self) -> str:
        """What the user typed in this conversation (not tool results), for checking that tool
        arguments such as spending amounts came from the user."""
        return "\n".join(
            typed(block["text"])
            for message in self.agent.messages
            if message.get("role") == "user"
            for block in message.get("content", [])
            if "text" in block
        )

    def __init__(self, session_id: str, user_id: str) -> None:
        self.api: AdvisorApi | None = None
        self.timings = Timings()
        tools = build_tools(self)
        self.tools = {t.tool_name: t for t in tools}  # for lookups made before the model runs
        self.agent = Agent(
            model=load_model(),
            system_prompt=SYSTEM_PROMPT,
            tools=tools,
            session_manager=get_memory_session_manager(session_id, user_id, self.timings),
            conversation_manager=SlidingWindowConversationManager(window_size=WINDOW_MESSAGES),
            callback_handler=None,
            hooks=[self.timings],
        )


_sessions: OrderedDict[tuple[str, str], Session] = OrderedDict()


def get_session(session_id: str, user_id: str) -> Session:
    # Keyed by user too: a session id guessed by another user never reaches this conversation.
    key = (session_id, user_id)
    if key in _sessions:
        _sessions.move_to_end(key)
        return _sessions[key]
    session = _sessions[key] = Session(session_id, user_id)
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return session


def _error(code: str, message: str, **extra) -> dict:
    return {"type": "error", "code": code, "message": message, **extra}


INTERNALS_REFUSAL = (
    "I can't share how the Advisor works inside. I can compare cards for your spending, check "
    "issuer rules like Chase 5/24 against your wallet, or look up a card's fees and offers."
)
# The Advisor's own messages, for a reply in Traditional Chinese (the API's messages stay as sent).
# The model or a service failed (throttling, a timeout), not the answer: the eval re-runs these.
TURN_FAILED = "Something went wrong while answering. Please try again."

ZH_TW = {
    "The Advisor had trouble answering. Please try again.": "Advisor 這次沒能回答，請再試一次。",
    "I couldn't check that against our card data. Please ask again.": (
        "我沒辦法用我們的卡片資料確認這點，請再問一次。"
    ),
    TURN_FAILED: "回答時出了問題，請再試一次。",
    INTERNALS_REFUSAL: (
        "我不能說明 Advisor 內部是怎麼運作的。我可以依你的消費比較卡片、用你的錢包檢查 "
        "Chase 5/24 等申請規則，或查詢卡片的年費和開卡禮。"
    ),
}


def _in_reply_language(message: str, prompt: str) -> str:
    return ZH_TW.get(message, message) if reply_language(prompt) == TRADITIONAL_CHINESE else message


# A question about the Advisor's own workings ("check_eligibility 這個函數是怎麼實作的？").
_ABOUT_INTERNALS = re.compile(
    r"函[數式]|參數|實作|原始碼|系統提示|提示詞|prompt|function|parameter|implement|source code",
    re.IGNORECASE,
)


def asks_about_internals(message: str) -> bool:
    return bool(_INTERNAL.search(message) or _ABOUT_INTERNALS.search(message))


@app.entrypoint
async def invoke(payload, context):
    try:
        caller = caller_from(getattr(context, "request_headers", None))
    except NotSignedIn as e:
        yield _error("auth", str(e))
        return

    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        yield _error("input", "Send a message in the 'prompt' field.")
        return
    if len(prompt) > MAX_PROMPT_CHARS:
        yield _error("input", f"Messages are limited to {MAX_PROMPT_CHARS} characters.")
        return

    began = time.monotonic()
    api = AdvisorApi(caller.headers)
    try:
        quota = api.take_turn()  # before the model runs: an exhausted quota costs nothing
    except QuotaExceeded as e:
        detail = e.detail if isinstance(e.detail, dict) else {}
        message = detail.pop("message", "Today's messages are used up.")
        detail.pop(
            "code", None
        )  # why the API refused (e.g. guests_full); the event's code is quota
        yield _error("quota", message, **detail)
        return
    except ApiError as e:
        detail = e.detail if isinstance(e.detail, dict) else {}
        if detail.get("code") == "guests_closed":  # the guest trial's budget is spent
            yield _error("signin", detail.get("message", "Sign in to use the Advisor."))
            return
        log.warning("quota check failed: %s", e)
        yield _error("internal", "The Advisor can't reach your account right now.")
        return
    yield {
        "type": "quota",
        "limit": quota.get("limit"),
        "remaining": quota["remaining"],
        "resets_at": quota["resets_at"],
        "guest": quota.get("guest", False),
    }

    session_id = getattr(context, "session_id", None) or uuid.uuid4().hex
    quota_took = time.monotonic() - began
    set_up = time.monotonic()
    session = get_session(session_id, caller.user_id)
    timings = session.timings
    timings.start()
    timings.began = began
    timings.marks["quota"] = quota_took
    timings.lap("session", set_up)
    session.api = api
    tokens_before = _tokens(session.agent)
    session.agent.system_prompt = system_prompt_for(prompt)  # this message's reply language
    answer = ""  # the checked answer the page shows
    nudge = ""  # a retry's instruction, at the end of the message where DeepSeek heeds it
    looked_ahead = _look_ahead(session, prompt)  # made once; a retry reuses them
    retries = 0
    try:
        for attempt in range(2):
            start = len(session.agent.messages)
            leaked = None  # "tool_call" or "internal": why the stream was cut
            leak_names: list[str] = []
            # Nothing the model writes reaches the page until the answer is checked: tool and
            # writing events keep the page's status line moving meanwhile.
            looked_up = bool(looked_ahead)
            answer = ""
            said = with_language(prompt) + nudge
            request = prefetch.as_messages(said, looked_ahead) if looked_ahead else said
            events = _stream(session, request, prompt)
            async for event in events:
                kind = event["type"]
                if kind == "leak":
                    leaked = event["why"]
                    leak_names = event.get("names", [])
                    break
                if kind == "answer":
                    answer = event["text"]
                    continue
                if kind == "tool":
                    looked_up = True
                timings.event(kind)
                yield event
            await events.aclose()  # stops the model call when it leaked
            checking = time.monotonic()
            unsourced = unsourced_in(answer, session.agent.messages) if answer else set()
            timings.lap("checks", checking)
            problem = leaked or (
                ("unlooked" if not looked_up else "unsourced") if unsourced else None
            )
            if problem is None:
                if answer:
                    timings.event("text")
                    yield {"type": "text", "text": answer}  # the held answer, checked
                break
            # Drop the answer from the conversation and ask once more.
            what, hint, retry_nudge, give_up = PROBLEMS[problem]
            # Names and amounts only (tool and field names, the unsourced figures), never the
            # user's or the model's text.
            flagged = sorted(unsourced) if unsourced else sorted(set(leak_names))
            log.warning("%s (attempt %d) %s", what, attempt + 1, flagged[:5])
            del session.agent.messages[start:]
            if attempt == 1:
                if problem == "internal" and asks_about_internals(prompt):
                    # Asked how the Advisor works and still naming its insides: decline plainly.
                    answer = _in_reply_language(INTERNALS_REFUSAL, prompt)
                    yield {"type": "text", "text": answer}
                    break
                yield _error("internal", _in_reply_language(give_up, prompt))
                return
            retries += 1
            timings.event("reset")
            yield {"type": "reset"}  # the page says it's double-checking; nothing was shown
            session.agent.system_prompt = system_prompt_for(prompt) + hint
            nudge = retry_nudge
            if unsourced:  # name them: "look things up" alone didn't stop a recalled $550 fee
                nudge += f"\n[No lookup gave these amounts: {', '.join(sorted(unsourced))}.]"
            answer = ""
        saving = time.monotonic()
        turn_id = _save_turn(api, turn_record(session.agent.messages[start:], prompt, answer))
        timings.lap("save", saving)
        # Before the cost report: the page finishes the reply as soon as it has the turn id.
        timings.event("done")
        yield {"type": "done", **({"turn_id": turn_id} if turn_id else {})}
    except Exception:
        log.exception("advisor turn failed")
        yield _error("internal", _in_reply_language(TURN_FAILED, prompt))
        return
    finally:
        reporting = time.monotonic()
        _report_cost(api, session.agent, tokens_before)
        timings.lap("usage", reporting)
        session.api = None  # don't keep the caller's token after the reply
        timings.report = timings.summary(retries)
        log.info("timing %s", timings.report)


# Dollar amounts and point counts ("$250", "95 美元", "USD 95", "75,000"): card facts a reply
# may state only when a tool (or the user) supplied them.
_AMOUNT = r"(\d[\d,]*(?:\.\d+)?)"
_FACT_NUMBER = re.compile(
    "|".join(
        [
            rf"\$\s?{_AMOUNT}",  # $95
            rf"(?:usd|us\$)\s?{_AMOUNT}",  # USD 95
            rf"{_AMOUNT}\s?(?:美元|美金|dollars?\b|usd\b)",  # 95 美元, 95 dollars
            r"\b(\d{1,3}(?:,\d{3})+)\b",  # 75,000 (points, miles)
        ]
    ),
    re.IGNORECASE,
)
LOOKUP_HINT = (
    "\nYour previous reply stated card facts (amounts) without looking them up. Call the tools "
    "(get_card_details, rank_cards, check_eligibility) and quote what they return."
)
UNSOURCED_HINT = (
    "\nYour previous reply stated card facts (amounts) that none of your lookups returned. Look "
    "up each card you mention (get_card_details) and quote what it returns."
)

# Why an answer was dropped -> (log text, system-prompt hint, end-of-message nudge, message
# shown if the retry fails too).
PROBLEMS = {
    "tool_call": (
        "tool call written as text",
        RETRY_HINT,
        "\n[Call tools through tool use; never write a tool call in the reply.]",
        "The Advisor had trouble answering. Please try again.",
    ),
    "internal": (
        "internal name in the reply",
        INTERNAL_HINT,
        "\n[Answer in plain words: no tool, field, id or system names.]",
        "The Advisor had trouble answering. Please try again.",
    ),
    "unlooked": (
        "facts stated without a lookup",
        LOOKUP_HINT,
        "\n[Before answering, look this up with the tools and quote what they return.]",
        "I couldn't check that against our card data. Please ask again.",
    ),
    # It looked things up but stated amounts none of them returned (each time so far, a fee it
    # recalled: the Reserve's old $550). Asked once more, naming the amounts; then given up.
    "unsourced": (
        "amounts not from the lookups",
        UNSOURCED_HINT,
        "\n[Look up every card you mention; quote its fees, offers and credits as returned.]",
        "I couldn't check that against our card data. Please ask again.",
    ),
}


def _numbers(text: str) -> set[str]:
    return {
        next(g for g in groups if g).replace(",", "").removesuffix(".00")
        for groups in _FACT_NUMBER.findall(text)
    }


def unsourced_in(answer: str, messages: list[dict]) -> set[str]:
    """Amounts in the answer that no tool result and nothing the user wrote in this conversation
    contains. DeepSeek once answered "The Amex Gold has a $250 annual fee" from memory ($325 in
    the catalog) without calling a tool, and once checked eligibility, then gave the Sapphire
    Reserve's old $550 fee ($795 in the catalog) without looking the card up."""
    sources = []
    for message in messages:
        for block in message.get("content", []):
            if "toolResult" in block:
                sources += [p.get("text", "") for p in block["toolResult"].get("content", [])]
            elif message.get("role") == "user" and "text" in block:
                sources.append(typed(block["text"]))
    return unsourced_amounts(answer, sources)


def unsourced_amounts(answer: str, sources: list[str]) -> set[str]:
    """Amounts in the answer that no source text contains (tool results, the user's words).
    Zero is never a claim worth sourcing ("$0 annual fee" reads "no annual fee" in the data).
    The sum or difference of two sourced amounts the answer states is worked out, not recalled
    ("$795 less the $300 credit is $495")."""
    text = "\n".join(sources)
    known = _numbers(text) | {n.replace(",", "") for n in re.findall(r"\d[\d,]*", text)}
    stated = _numbers(answer)
    sourced = [float(n) for n in stated & known]
    worked_out = {f"{v:g}" for a in sourced for b in sourced for v in (a + b, abs(a - b)) if a != b}
    return {n for n in stated - known - {"0"} if f"{float(n):g}" not in worked_out}


def turn_record(messages: list[dict], question: str, answer: str) -> dict:
    """This answer as the API stores it for feedback (ADR 0009): the question, the answer the
    page showed, and each tool call with its result, so a bad answer can be traced to the data
    or to the model."""
    calls, results = [], {}
    for message in messages:
        for block in message.get("content", []):
            if "toolUse" in block:
                use = block["toolUse"]
                calls.append(
                    (
                        use.get("toolUseId"),
                        use["name"],
                        json.dumps(use.get("input"), ensure_ascii=False),
                    )
                )
            elif "toolResult" in block:
                result = block["toolResult"]
                results[result.get("toolUseId")] = "".join(
                    part.get("text", "") for part in result.get("content", [])
                )
    return {
        "turn_id": f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}",
        "question": question[:2000],
        "answer": answer[:12000],
        "tools": [
            {"name": name, "input": args[:2000], "result": results.get(use_id, "")[:6000]}
            for use_id, name, args in calls[:20]
        ],
        "model_id": MODEL_ID,
        "prompt_version": PROMPT_VERSION,
        "catalog_version": catalog_version(),
        "rules_version": rules_version(),
    }


def _tokens(agent) -> tuple[int, int]:
    """Input and output tokens this agent has used so far (Strands keeps a running total)."""
    usage = getattr(getattr(agent, "event_loop_metrics", None), "accumulated_usage", None) or {}
    return usage.get("inputTokens", 0), usage.get("outputTokens", 0)


def _report_cost(api: AdvisorApi, agent, before: tuple[int, int]) -> None:
    """What this message cost, retries included, toward the guest trial's budget (ADR 0009).
    Reporting never fails the answer."""
    used_in, used_out = (now - then for now, then in zip(_tokens(agent), before, strict=True))
    try:
        api.record_usage(message_cost(used_in, used_out))
    except Exception:
        log.warning("couldn't report the message's cost", exc_info=True)


def _save_turn(api: AdvisorApi, record: dict) -> str | None:
    """The turn id for feedback, or None: failing to save never fails the answer."""
    try:
        return api.save_turn(record)["turn_id"]
    except Exception:
        log.warning("couldn't save the answer for feedback", exc_info=True)
        return None


def _look_ahead(session: Session, prompt: str) -> list[tuple[str, dict, str]]:
    """The lookups `prefetch` makes before the model runs; none if the catalog can't be read."""
    tools = getattr(session, "tools", None)
    if not tools:
        return []
    began = time.monotonic()
    try:
        calls = prefetch.plan(prompt, session.api.cards(), session.api.issuers())
    except Exception:  # noqa: BLE001 - without the catalog, profile and wallet still help
        calls = list(prefetch.ALWAYS)
    done = prefetch.run(tools, calls)
    # Ranking reads the saved profile: only once it shows spending to rank by.
    if prefetch.wants_ranking(prompt, calls) and prefetch.has_spending(done):
        done += prefetch.run(tools, [prefetch.RANKING])
    session.timings.lap("prefetch", began)
    return done


async def _stream(session: Session, request, prompt: str):
    """The agent's work as site events, holding back everything the model writes until it is
    checked: a "tool" event per call, a "writing" event when the model starts writing after one,
    and last an "answer" event with the text after the final call. Text before a call is narration
    ("Let me check...", once a whole analysis before ranking): shown and then cleared, it read as
    the answer vanishing, so it's dropped unseen. A "leak" event ends the stream when the model
    writes a tool call as text, or when the answer names something internal (a tool, a field, an
    id, an API path); narration naming one costs nothing, since nobody sees it."""
    text = ""
    writing = False  # told the page the model is writing, since the last call
    tool_calls: set[str] = set()
    stream = session.agent.stream_async(request)
    try:
        async for event in stream:
            if isinstance(event, dict) and isinstance(event.get("data"), str):
                session.timings.output()
                text += event["data"]
                if LEAKED_TOOL_CALL.search(text):
                    yield {"type": "leak", "why": "tool_call"}
                    return
                if not writing and MODEL_MARKUP.sub("", text).strip():
                    writing = True
                    yield {"type": "writing"}
            elif isinstance(event, dict) and "current_tool_use" in event:
                use = event["current_tool_use"] or {}
                call = use.get("toolUseId") or use.get("name")
                if call and call not in tool_calls:
                    session.timings.output()
                    tool_calls.add(call)
                    text, writing = "", False
                    yield {"type": "tool", "name": use.get("name")}
        answer = plain_names(MODEL_MARKUP.sub("", text).strip(), *_known_names(session))
        names = internal_names(answer, prompt)
        if names:
            yield {"type": "leak", "why": "internal", "names": names}
            return
        yield {"type": "answer", "text": answer}
    finally:
        await stream.aclose()


if __name__ == "__main__":
    app.run()
