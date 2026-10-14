"""Lookups made before the model runs, so its first step can already answer (speculative
execution, as Alexa+ describes it). Measured on 2026-10-13, the first model call was
spent fetching the profile and wallet, and wrote 2.5-4.7s of narration before making that call.

Always: the user's profile and wallet. For cards the message names outright (`search.mentioned`):
their details and the eligibility check. For a request for recommendations that names no card,
once the profile shows spending: the ranking (a recommendation's first step anyway; without
spending the model asks for it first). The results join the conversation as tool calls the
model already made, so it quotes them like its own lookups, the amount check counts them as
sources, and the saved answer records them. A lookup that fails is left out: the model can still
make it."""

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

from advisor import search

ALWAYS = [("get_my_profile", {}), ("get_my_wallet", {})]
RANKING = ("rank_cards", {})

# Asking which card to get, in English or Chinese. A miss costs only the model's own ranking call;
# a false match, one ranking it may not use.
RECOMMEND = re.compile(
    r"\b(?:which|what)\b[^?.!]*\bcards?\b|\bbest\b[^?.!]*\bcards?\b|\bcards?\b[^?.!]*\bbest\b"
    r"|\brecommend|\bsuggest|\bshould i (?:get|apply)"
    r"|推薦|建議|哪張|哪一張|哪種卡|哪一種卡|該辦|要辦哪|選哪|最適合|適合我|適合辦",
    re.IGNORECASE,
)


def wants_ranking(prompt: str, calls: list[tuple[str, dict]]) -> bool:
    """A request for recommendations that names no card (named cards are already looked up)."""
    named = any(name == "get_card_details" for name, _ in calls)
    return not named and bool(RECOMMEND.search(prompt))


def has_spending(done: list[tuple[str, dict, str]]) -> bool:
    """The looked-up profile has monthly spending to rank by."""
    for name, _, result in done:
        if name == "get_my_profile":
            try:
                return any((json.loads(result).get("monthly_spending_usd") or {}).values())
            except (ValueError, AttributeError):
                return False
    return False


def plan(prompt: str, cards: dict[str, dict], issuers: dict) -> list[tuple[str, dict]]:
    named = search.mentioned(prompt, cards, issuers)
    calls = list(ALWAYS)
    calls += [("get_card_details", {"card": c["name"]}) for c in named]
    if named:
        calls.append(("check_eligibility", {"card_ids": [c["id"] for c in named]}))
    return calls


def run(tools: dict, calls: list[tuple[str, dict]]) -> list[tuple[str, dict, str]]:
    """(tool, arguments, result) for each call that worked, run at the same time."""

    def one(call: tuple[str, dict]) -> tuple[str, dict, str] | None:
        name, args = call
        try:
            return name, args, tools[name](**args)
        except Exception:  # noqa: BLE001 - the model can still make this lookup itself
            return None

    with ThreadPoolExecutor(max_workers=len(calls) or 1) as pool:
        return [done for done in pool.map(one, calls) if done is not None]


def as_messages(user_text: str, done: list[tuple[str, dict, str]]) -> list[dict]:
    """The user's message, then the lookups as one step of tool calls and their results."""
    ids = [f"prefetch-{uuid.uuid4().hex[:12]}" for _ in done]
    return [
        {"role": "user", "content": [{"text": user_text}]},
        {
            "role": "assistant",
            "content": [
                {"toolUse": {"toolUseId": i, "name": name, "input": args}}
                for i, (name, args, _) in zip(ids, done, strict=True)
            ],
        },
        {
            "role": "user",
            "content": [
                {"toolResult": {"toolUseId": i, "status": "success", "content": [{"text": result}]}}
                for i, (_, _, result) in zip(ids, done, strict=True)
            ],
        },
    ]
