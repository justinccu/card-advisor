"""Run the Advisor golden set (agent/evals/golden.yaml) against the real model (S8, ADR 0009).

    make eval                      # every case once (~$0.6 with DeepSeek V3.2)
    make eval RUNS=3               # each case three times, to see how stable answers are
    make eval MODEL=qwen.qwen3-235b-a22b-2507-v1:0
    make eval ONLY=amex-gold-fee,rule-5-24-closed-cards

The agent runs in this process through the same entrypoint the Runtime calls (identity, quota,
guards, streaming), against a fresh local API on :8011. Each case gets its own user, seeded
like the demo account or left empty. A case passes when its expectations hold and every
universal check passes (see golden.yaml). Exits non-zero when a threshold isn't met, so
`make agent-deploy` can refuse to deploy.
"""

import argparse
import asyncio
import contextvars
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import date, datetime
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "agent" / "app" / "Advisor"
GOLDEN = Path(__file__).with_name("golden.yaml")
REPORTS = Path(__file__).with_name("reports")
API_PORT = 8011
API = f"http://localhost:{API_PORT}"

THRESHOLDS = {  # share of answers (or cases) that must pass
    "leaks": 1.0,
    "links": 1.0,
    "sourced": 0.95,
    "citations": 0.95,
    "language": 0.95,
    "expectations": 0.90,
}
# Simplified-only characters: their presence means the reply isn't Traditional Chinese.
SIMPLIFIED = set(
    "们这为说时对发会个点费门现还经过么问题银优礼开积额请资讯务无万让应该与从当买实际帮获计划"
)
HAN = re.compile(r"[一-鿿]")
LINK = re.compile(r"\]\(\s*(card|rule):([a-z0-9_]+)\s*\)")
MARKUP = ("<｜", "</tool_call>", '"arguments"')

DEMO_CARDS = [  # what app.seed_demo gives the demo account
    ("chase_freedom_unlimited", 30),
    ("amex_blue_cash_everyday", 20),
    ("c1_venture_x", 11),
    ("citi_double_cash", 7),
    ("discover_it_cash_back", 3),
]

current_case: contextvars.ContextVar[list] = contextvars.ContextVar("current_case")


def months_ago(n: int) -> str:
    today = date.today()
    y, m = divmod(today.month - 1 - n, 12)
    return date(today.year + y, m + 1, min(today.day, 28)).isoformat()


def seed_user(user: str, case: dict) -> None:
    """demo: the demo account's wallet, profile and confirmed history. fresh: nothing. Either can
    add `cards` ([card_id, months_ago] pairs), a demo `profile`, and `full_history` (issuers
    whose whole history is listed), so a case can hold the card its question is about."""
    kind = case.get("user", "demo")
    cards = (DEMO_CARDS if kind == "demo" else []) + [tuple(c) for c in case.get("cards", [])]
    with httpx.Client(base_url=API, headers={"X-Dev-User": user}, timeout=10) as api:
        for card_id, ago in cards:
            api.post(
                "/me/wallet/cards", json={"card_product_id": card_id, "opened_on": months_ago(ago)}
            ).raise_for_status()
        if kind == "demo" or case.get("profile") == "demo":
            api.put(
                "/me/profile", json={"tax_id": "SSN", "score_band": "740_799"}
            ).raise_for_status()
        if kind == "demo" or "full_history" in case:
            api.put(
                "/me/wallet/attestation",
                json={
                    "complete_since": months_ago(60 if "full_history" in case else 24),
                    "includes_all_open_cards": True,
                    "full_history_issuers": case.get("full_history", []),
                },
            ).raise_for_status()


def start_api() -> subprocess.Popen:
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "card_api.app:app", "--port", str(API_PORT)],
        cwd=ROOT,
        env={**os.environ, "APP_ENV": "local"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            if httpx.get(f"{API}/health", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.5)
    proc.kill()
    sys.exit(f"the local API didn't start on :{API_PORT}")


def check_aws() -> None:
    """Fail in a second, not one error per case, when the model can't be reached."""
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        boto3.client("sts", region_name="us-east-2").get_caller_identity()
    except (BotoCoreError, ClientError) as e:
        sys.exit(
            f"AWS credentials don't work ({type(e).__name__}): run `aws login --profile "
            "chenhan9`, then retry."
        )


def newest_catalog() -> Path:
    return max(
        (ROOT / "catalog" / "us").glob("v*.json"),
        key=lambda p: [int(x) for x in p.stem[1:].split(".")],
    )


def catalog_ids() -> set[str]:
    return {c["id"] for c in json.loads(newest_catalog().read_text())["cards"]}


# --- one case -----------------------------------------------------------------------------


class Ctx:
    def __init__(self, user: str, session_id: str):
        from advisor.identity import DEV_USER_HEADER

        self.request_headers = {DEV_USER_HEADER: user}
        self.session_id = session_id


async def run_case(main, case: dict, run: int) -> dict:
    user = f"eval-{uuid.uuid4().hex[:12]}"  # the dev sign-in takes short ids only
    seed_user(user, case)
    records: list[dict] = []
    current_case.set(records)
    started = time.monotonic()
    answer, errors = "", []
    for turn in case["turns"]:
        answer, errors = "", []
        async for event in main.invoke({"prompt": turn}, Ctx(user, f"{case['id']}-{run}-{user}")):
            if event["type"] == "text":
                answer += event["text"]
            elif event["type"] == "reset":
                answer = ""
            elif event["type"] == "error":
                errors.append(event.get("message", ""))
    tools = [t["name"] for t in records[-1]["tools"]] if records else []
    return {
        "id": case["id"],
        "category": case["category"],
        "critical": bool(case.get("critical")),
        "run": run,
        "seconds": round(time.monotonic() - started, 1),
        "question": case["turns"][-1],
        "answer": answer,
        "errors": errors,
        "tools": tools,
        "tool_results": [c["result"] for r in records for c in r["tools"]],
        "user_texts": list(case["turns"]),
    }


# --- checks -------------------------------------------------------------------------------


def universal(result: dict, card_ids: set[str], rule_ids: set[str]) -> dict[str, str | None]:
    """check -> None when it passes, else why it failed."""
    from advisor.prompt import reply_language
    from main import internal_names, unsourced_amounts

    a = result["answer"]
    shown = LINK.sub("]", a)
    leaks = internal_names(a, "\n".join(result["user_texts"])) + [m for m in MARKUP if m in a]
    if re.search(r"https?://|www\.", shown):
        leaks.append("a URL")
    links = [i for kind, i in LINK.findall(a) if kind == "card" and i not in card_ids]
    links += [f"rule:{i}" for kind, i in LINK.findall(a) if kind == "rule" and i not in rule_ids]
    unsourced = unsourced_amounts(a, result["tool_results"] + result["user_texts"])
    cited = [i for kind, i in LINK.findall(a) if kind == "rule"]
    uncited = [i for i in cited if not any(i in s for s in result["tool_results"])]
    if reply_language(result["question"]).startswith("Traditional"):
        simplified = sorted(set(a) & SIMPLIFIED)
        language = (
            f"Simplified characters: {''.join(simplified)}"
            if simplified
            else (None if len(HAN.findall(a)) >= 5 else "not in Chinese")
        )
    else:
        language = "Chinese in an English reply" if HAN.search(LINK.sub("", a)) else None
    return {
        "leaks": f"internal names: {leaks}" if leaks else None,
        "links": f"links to cards or rules that don't exist: {links}" if links else None,
        "sourced": f"amounts no tool or user gave: {sorted(unsourced)}" if unsourced else None,
        "citations": f"rules cited but never looked up: {uncited}" if uncited else None,
        "language": language,
    }


def expectations(result: dict, expect: dict) -> list[str]:
    a = result["answer"].lower()
    problems = [f"error: {e}" for e in result["errors"]]
    if not result["answer"].strip() and not result["errors"]:
        problems.append("empty answer")
    for tool in expect.get("tools", []):
        if tool not in result["tools"]:
            problems.append(f"didn't call {tool} (called {result['tools']})")
    for text in expect.get("contains", []):
        if text.lower() not in a:
            problems.append(f"missing {text!r}")
    if expect.get("contains_any") and not any(t.lower() in a for t in expect["contains_any"]):
        problems.append(f"none of {expect['contains_any']}")
    for text in expect.get("not_contains", []):
        if text.lower() in a:
            problems.append(f"says {text!r}")
    if expect.get("asks") and not re.search(r"[?？]", result["answer"]):
        problems.append("doesn't ask the user anything")
    for rule in expect.get("cites", []):
        if f"rule:{rule}" not in a:
            problems.append(f"doesn't cite {rule}")
    if expect.get("card_links") and "](card:" not in a:
        problems.append("no card: link")
    return problems


# --- main ---------------------------------------------------------------------------------


async def run_all(cases: list[dict], runs: int, parallel: int) -> list[dict]:
    sys.path.insert(0, str(AGENT))
    os.chdir(AGENT)
    import main

    def capture(api, record):  # the record the API would store, kept for the checks
        current_case.get().append(record)
        return record["turn_id"]

    main._save_turn = capture
    gate = asyncio.Semaphore(parallel)

    async def one(case, run):
        async with gate:
            try:
                return await run_case(main, case, run)
            except Exception as e:  # a crash fails the case, not the whole run
                return {
                    "id": case["id"],
                    "category": case["category"],
                    "critical": bool(case.get("critical")),
                    "run": run,
                    "seconds": 0,
                    "question": case["turns"][-1],
                    "answer": "",
                    "errors": [f"crashed: {e!r}"],
                    "tools": [],
                    "tool_results": [],
                    "user_texts": list(case["turns"]),
                }

    return await asyncio.gather(*(one(c, r) for c in cases for r in range(runs)))


def main_cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--only", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--parallel", type=int, default=4)
    args = parser.parse_args()

    golden = yaml.safe_load(GOLDEN.read_text())
    cases = golden["cases"]
    newest = newest_catalog().stem[1:]
    if str(golden.get("catalog_version")) != newest:
        print(
            f"note: golden.yaml was written against catalog v{golden.get('catalog_version')}, "
            f"testing v{newest}: review cases that depend on changed data"
        )
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    os.environ.update(ADVISOR_LOCAL="1", ADVISOR_API_URL=API, AWS_REGION="us-east-2")
    os.environ.pop("ADVISOR_DEV_USER", None)
    os.environ.pop("MEMORY_ADVISORMEMORY_ID", None)  # conversations stay in this process
    if args.model:
        os.environ["ADVISOR_MODEL_ID"] = args.model

    check_aws()
    api = start_api()
    try:
        rule_ids = {
            r["rule_id"]
            for r in httpx.get(f"{API}/rules", headers={"X-Dev-User": "eval-rules"}).json()["rules"]
        }
        results = asyncio.run(run_all(cases, args.runs, args.parallel))
    finally:
        api.terminate()

    ids = catalog_ids()
    by_case = {c["id"]: c for c in cases}
    counts = {k: [0, 0] for k in THRESHOLDS}
    failed_critical = []
    for r in results:
        r["checks"] = universal(r, ids, rule_ids)
        r["expectations"] = expectations(r, by_case[r["id"]].get("expect", {}))
        for check, why in r["checks"].items():
            counts[check][0] += why is None
            counts[check][1] += 1
        ok = not r["expectations"]
        counts["expectations"][0] += ok
        counts["expectations"][1] += 1
        # A citation of a real rule the model didn't look up counts toward the citations
        # rate only; a rule that doesn't exist fails the case (under links), like a fake card.
        r["passed"] = ok and all(v is None for k, v in r["checks"].items() if k != "citations")
        if r["critical"] and not r["passed"]:
            failed_critical.append(r["id"])

    for r in sorted(results, key=lambda r: (r["passed"], r["category"], r["id"])):
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"{mark}  {r['category']:15} {r['id']:42} {r['seconds']:5}s  tools={r['tools']}")
        if not r["passed"]:
            for why in [v for v in r["checks"].values() if v] + r["expectations"]:
                print(f"        - {why}")
            print(f"        answer: {r['answer'][:300]!r}")
    print()
    gate_ok = not failed_critical
    for check, (good, total) in counts.items():
        share = good / total if total else 1.0
        ok = share >= THRESHOLDS[check]
        gate_ok &= ok
        print(
            f"{'ok ' if ok else 'LOW'}  {check:13} {good}/{total} = {share:.0%} "
            f"(needs {THRESHOLDS[check]:.0%})"
        )
    if failed_critical:
        print(f"LOW  critical cases failing: {', '.join(sorted(set(failed_critical)))}")
    turns = sum(len(c["turns"]) for c in cases) * args.runs
    print(
        f"\n{len(results)} answers, {turns} messages, about ${turns * 0.015:.2f} "
        f"({os.environ.get('ADVISOR_MODEL_ID') or 'default model'})"
    )

    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(
        json.dumps(
            {
                "model": os.environ.get("ADVISOR_MODEL_ID"),
                "results": results,
                "counts": counts,
                "passed": gate_ok,
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    print(f"report: {out.relative_to(ROOT)}")
    print("EVAL PASSED" if gate_ok else "EVAL FAILED: don't deploy")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    sys.exit(main_cli())
