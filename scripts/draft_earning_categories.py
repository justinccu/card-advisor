"""Draft the earning-category mapping (ADR 0009) for catalog rates that have none yet.

Issuers name reward categories their own way ("U.S. supermarkets", "Flights booked directly with
airlines"); ranking needs them on one fixed set of spending categories. This proposes a mapping
by keyword for every (card, category text) not yet in catalog/seed/earning_categories.yaml and
appends it with `status: draft`; a person reviews each draft and sets `status: reviewed`.
Reviewed entries are never touched.

    uv run python scripts/draft_earning_categories.py [catalog/us/v1.4.json]
"""

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "catalog" / "seed" / "earning_categories.yaml"

SPEND_CATEGORIES = [
    "dining",
    "groceries",
    "flights",
    "hotels",
    "other_travel",
    "gas_ev",
    "transit",
    "streaming",
    "online_shopping",
    "drugstores",
    "everything_else",
]
TRAVEL = ["flights", "hotels", "other_travel"]

# Rates that apply only under a condition the Spending Profile can't express; ranking counts them
# only when the user says they apply (like credits).
PORTAL = re.compile(
    r"(through|booked on|booked through|purchased through|booked in|on)\s+"
    r"(chase travel|capital one travel|american express travel|amex ?travel(\.com)?|"
    r"cititravel\.com|citi travel( portal)?|travel center)"
    r"|^(chase travel|capital one travel)(\s+purchases)?$",
    re.I,
)
BRANDS = {
    "delta": r"\bdelta\b",
    "united": r"\bunited\b",
    "southwest": r"\bsouthwest\b",
    "american_airlines": r"american airlines",
    "hyatt": r"\bhyatt\b",
    "ihg": r"\bihg\b",
    "marriott": r"\bmarriott\b",
    "costco": r"\bcostco\b",
    "amazon": r"amazon|whole foods",
    "lyft": r"\blyft\b",
    "capital_one_entertainment": r"capital one entertainment",
}
# Co-brand cards whose generic-sounding hotel/airline categories mean the partner's own.
COBRAND = {
    "amex_hilton_honors": "hilton",
    "amex_hilton_surpass": "hilton",
    "chase_world_of_hyatt": "hyatt",
    "chase_ihg_premier": "ihg",
    "chase_marriott_boundless": "marriott",
    "amex_delta_gold": "delta",
    "chase_united_explorer": "united",
    "chase_southwest_plus": "southwest",
    "citi_aadvantage_platinum_select": "american_airlines",
}
CHOICE = re.compile(r"choice|chosen|top \d|top eligible|rotating", re.I)
RELATIONSHIP = re.compile(r"smartly|qualifying balances", re.I)
BUSINESS = re.compile(
    r"business|office supply|shipping|advertising|internet, cable|phone services|\$5k", re.I
)
TIME_WINDOW = re.compile(r"citi nights|friday|saturday", re.I)
BASE = re.compile(
    r"^(all|every|everyday|everything|other|eligible)\b.*(purchase|else|\bpurchases?)?$", re.I
)

KEYWORDS = [
    ("dining", r"restaurant|dining|takeout|delivery"),
    ("groceries", r"grocery|groceries|supermarket|wholesale club"),
    ("flights", r"flight|airline|air travel"),
    ("hotels", r"hotel|resort|vacation rental|vacation home"),
    ("other_travel", r"car rental|rental car|attraction|cruise"),
    ("gas_ev", r"\bgas\b|ev charging"),
    ("transit", r"transit|commut|rideshare"),
    ("streaming", r"streaming"),
    ("online_shopping", r"online retail|online shopping"),
    ("drugstores", r"drugstore"),
]


def propose(card_id: str, text: str) -> dict:
    t = text.strip()
    entry: dict = {"text": t}
    if TIME_WINDOW.search(t):
        return entry | {"spend": ["dining"], "when": "time_window"}
    if RELATIONSHIP.search(t):
        return entry | {"spend": ["everything_else"], "when": "relationship"}
    if CHOICE.search(t):
        return entry | {"spend": [], "when": "choice"}
    spend = [cat for cat, pat in KEYWORDS if re.search(pat, t, re.I)]
    if re.search(r"\btravel\b", t, re.I) and not {"flights", "hotels"} & set(spend):
        spend += [c for c in TRAVEL if c not in spend]
    brand = next((b for b, pat in BRANDS.items() if re.search(pat, t, re.I)), None)
    if (
        brand is None
        and card_id in COBRAND
        and ({"hotels", "flights"} & set(spend) or re.search(r"purchase", t, re.I))
        and not BASE.search(t)
    ):
        brand = COBRAND[card_id]
    if PORTAL.search(t):
        entry["when"] = "portal"
    elif brand:
        entry["when"] = "brand"
        entry["brand"] = brand
    elif BUSINESS.search(t):
        entry["when"] = "business"
    if not spend and BASE.search(t):
        spend = ["everything_else"]
    return entry | {"spend": spend}


def main() -> None:
    catalog = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else max(
            (ROOT / "catalog" / "us").glob("v*.json"),
            key=lambda p: tuple(int(x) for x in p.stem[1:].split(".")),
        )
    )
    snapshot = json.loads(catalog.read_text())
    mapping = yaml.safe_load(MAP_PATH.read_text()) if MAP_PATH.exists() else {}
    cards = mapping.setdefault("cards", {})
    added = 0
    for card in snapshot["cards"]:
        if card["availability"] != "open":
            continue
        known = {e["text"] for e in cards.get(card["id"], [])}
        for rate in card["earning_rates"]:
            text = rate["category"].strip()
            if text in known:
                continue
            cards.setdefault(card["id"], []).append(propose(card["id"], text) | {"status": "draft"})
            known.add(text)
            added += 1
    mapping["spend_categories"] = SPEND_CATEGORIES
    body = yaml.safe_dump(
        {"spend_categories": SPEND_CATEGORIES, "cards": dict(sorted(cards.items()))},
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )
    MAP_PATH.write_text(HEADER + body)
    print(f"{added} draft entries added from {catalog.name}; review them in {MAP_PATH.name}")


HEADER = """\
# Issuer reward categories -> the Spending Profile's categories (ADR 0009).
#
# One entry per (card, category text as extracted). `spend` lists the spending categories the
# rate applies to ([] = none the profile tracks). `when` marks a condition ranking can't verify,
# so the rate counts only if the user says it applies: portal (issuer travel site), brand
# (one merchant or airline/hotel chain), choice (user-chosen or rotating category), relationship
# (needs deposits), business, time_window. Drafts come from scripts/draft_earning_categories.py;
# a person reviews each and sets `status: reviewed`.
"""


if __name__ == "__main__":
    main()
