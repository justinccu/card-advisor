"""Build the next Catalog Snapshot from approved reviews (ADR 0002, 0003).

Snapshots are immutable: a new version is written only when content actually changed.
"""

import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

from card_rules.catalog import (
    VERSION_PATTERN,
    CatalogCard,
    CatalogSnapshot,
    Credit,
    EarningRate,
    Offer,
    OfferVariant,
    version_key,
)
from card_rules.models import Market, TaxId

from scout.seed import REPO_ROOT, SeedCard

CATALOG_DIR = REPO_ROOT / "catalog" / "us"


def _published_notes(review: dict) -> str:
    """Model-written notes are review aids only. A scraped page can steer them, and the chat agent
    later reads the catalog, so only notes a reviewer explicitly wrote reach the snapshot."""
    if any(e["path"] == "reviewer_notes" for e in review["edits"]):
        return review["final"].get("reviewer_notes", "")
    return ""


def _offer(offer: dict | None) -> Offer | None:
    """Build the catalog Offer, normalizing contradictions seen in model output:

    - a fixed amount quoted from the page is disclosed, whatever amount_disclosed says
      (only a ceiling can sit next to "find out your offer");
    - a cash offer given only as statement_credit_usd is the amount itself, and a
      statement_credit_usd equal to a cash amount is the same money counted twice;
    - an "offer" with no amount, credit or spend requirement is no offer.
    """
    if not offer:
        return None
    amount = offer["amount"]["value"]
    up_to = offer.get("amount_is_up_to", False)
    credit = (offer.get("statement_credit_usd") or {}).get("value")
    min_spend = offer["min_spend_usd"]["value"]
    unit = offer["unit"]
    if unit == "usd" and credit is not None and amount in (None, credit):
        amount, credit = credit, None
    if amount is None and credit is None and min_spend is None and unit != "cashback_match":
        return None
    return Offer(
        amount_disclosed=offer["amount_disclosed"] or (amount is not None and not up_to),
        amount=amount,
        amount_is_up_to=up_to,
        unit=unit,
        min_spend_usd=min_spend,
        spend_window_months=offer["spend_window_months"]["value"],
        statement_credit_usd=credit,
        ends_on=_date_or_none((offer.get("ends_on") or {}).get("value")),
    )


def _date_or_none(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:  # the model wrote something that isn't a date: treat as unknown
        return None


def _credit(c: dict) -> Credit:
    fields = {k: v for k, v in c.items() if k != "evidence"}
    fields["valid_until"] = _date_or_none(fields.get("valid_until"))
    return Credit(**fields)


def choose_offer(
    main: Offer | None, others: list[Offer | None], as_of: date | None = None
) -> Offer | None:
    """The offer to headline: the **largest publicly shown number**, not the best expected value.

    - Only public amounts in the main offer's unit compete (points never beat dollars). A
      ceiling counts as public even when the exact offer is shown only on applying (Amex: "as
      high as 100,000 ... find out your offer"); a hidden amount with no number does not.
    - A ceiling ("as high as 100,000", amount_is_up_to) beats a fixed 90,000 here even though
      many applicants get less; that's why the chosen offer keeps amount_is_up_to and the site
      renders it as "Up to". On a tie, the fixed amount wins.
    - An offer past its `ends_on` never headlines.
    - If nothing is disclosed, the main page's offer stands.
    """
    as_of = as_of or date.today()
    unit = main.unit if main else None
    pool = [
        o
        for o in [main, *others]
        if o
        and (o.amount_disclosed or o.amount_is_up_to)
        and o.amount is not None
        and (unit is None or o.unit == unit)
        and (o.ends_on is None or o.ends_on >= as_of)
    ]
    if not pool:
        return main
    return max(pool, key=lambda o: (o.amount, not o.amount_is_up_to))


def _card(seed: SeedCard, review: dict | None, variants: list[dict] = ()) -> CatalogCard:
    base = {
        "id": seed.id,
        "issuer_id": seed.issuer_id,
        "name": seed.name,
        "market": Market.US,
        "family": seed.family,
        "is_business": seed.is_business,
        "is_charge_card": seed.is_charge_card,
        "url": seed.url,
        "availability": seed.availability,
        "closed_on": seed.closed_on,
        "tags": seed.tags,
    }
    if review is None:  # closed card kept for Held Card selection only
        return CatalogCard(**base)

    x = review["final"]
    main_offer = _offer(x.get("offer"))
    variant_offers = [
        {
            "offer": _offer(v["extracted"].get("offer")),
            "source_url": v["source_url"],
            "profile": v.get("profile", "campaign"),
            "fetched_at": v.get("fetched_at"),
        }
        for v in variants
    ]
    # Varies if the HTML hid fee/offer numbers from visitors, or the pages disagree on the offer.
    distinct = {
        (o.amount, o.unit, o.amount_is_up_to)
        for o in [main_offer, *(v["offer"] for v in variant_offers)]
        if o
    }
    varies = bool((review.get("page_variant") or {}).get("hidden_in_render")) or len(distinct) > 1
    itin = x["accepts_itin"]["value"] is True
    return CatalogCard(
        **base,
        # Only an explicit ITIN statement widens eligibility; silence stays SSN-only (conservative).
        accepted_tax_ids=frozenset({TaxId.SSN, TaxId.ITIN} if itin else {TaxId.SSN}),
        annual_fee_usd=x["annual_fee_usd"]["value"],
        first_year_annual_fee_usd=x["first_year_annual_fee_usd"]["value"],
        foreign_transaction_fee_pct=x["foreign_transaction_fee_pct"]["value"],
        network=x["network"]["value"],
        # Raw-HTML ("http") offers never compete: only rendered pages can supply the offer.
        offer=choose_offer(
            main_offer, [v["offer"] for v in variant_offers if v["profile"] != "http"]
        ),
        offer_variants=[
            OfferVariant(
                source_url=review.get("source_url") or seed.url,
                profile="fresh",
                offer=main_offer,
                fetched_at=review.get("fetched_at"),
            ),
            *(
                OfferVariant(
                    source_url=v["source_url"],
                    profile=v["profile"],
                    offer=v["offer"],
                    fetched_at=v["fetched_at"],
                )
                for v in variant_offers
            ),
        ],
        varies_by_visitor=varies,
        earning_rates=[
            EarningRate(**{k: v for k, v in r.items() if k != "evidence"})
            for r in x["earning_rates"]
        ],
        credits=[_credit(c) for c in x["credits"]],
        notes=_published_notes(review),
        verified_at=review["reviewed_at"],
        content_hash=review["content_hash"],
    )


def build(seeds: list[SeedCard], reviews: dict[str, dict]) -> list[CatalogCard]:
    cards = []
    for seed in seeds:
        review = reviews.get(seed.id)
        if review and review["decision"] == "approved":
            cards.append(_card(seed, review))
        elif seed.availability == "closed_to_new_applicants":
            cards.append(_card(seed, None))
    return cards


def build_preview(
    seeds: list[SeedCard], changes: dict[str, dict], variants: dict[str, list[dict]] | None = None
) -> CatalogSnapshot:
    """A local-only snapshot from unreviewed Proposed Changes, for demos while review is pending.
    Model notes are still dropped; nothing here is marked verified."""
    cards = []
    for seed in seeds:
        change = changes.get(seed.id)
        if change:
            pseudo = {
                "final": change["extracted"],
                "edits": [],
                "reviewed_at": None,
                "content_hash": change["content_hash"],
                "source_url": change.get("source_url"),
                "fetched_at": change.get("fetched_at"),
                "page_variant": change.get("page_variant"),
            }
            cards.append(_card(seed, pseudo, (variants or {}).get(seed.id, [])))
        elif seed.availability == "closed_to_new_applicants":
            cards.append(_card(seed, None))
    return CatalogSnapshot(
        version="0.0", market=Market.US, generated_at=datetime.now(UTC), cards=cards, preview=True
    )


# Fields whose quotes must be found on the page (verbatim or approximately) before a new
# extraction may replace a published card. Perks and earning rates may still carry flags; they are
# listed in the publish notes instead of blocking the update.
CRITICAL_FIELDS = ("annual_fee_usd", "first_year_annual_fee_usd", "offer.")
ACCEPTED_STATUSES = ("verified", "approximate", "empty")


def update_from_run(
    base: list[CatalogCard],
    seeds: list[SeedCard],
    changes: dict[str, dict],
    variants: dict[str, list[dict]] | None = None,
) -> tuple[list[CatalogCard], list[str]]:
    """Replace published cards with re-extracted ones, gated on critical-field evidence.

    A card is replaced only if every fee and offer field's quote is on the rendered page. The new
    card's `verified_at` is its fetch time: the automated quote check, not a person, verified it.
    """
    by_seed = {s.id: s for s in seeds}
    rebuilt = build_preview([by_seed[cid] for cid in changes if cid in by_seed], changes, variants)
    fresh = {c.id: c for c in rebuilt.cards}
    out, notes = [], []
    for card in base:
        change = changes.get(card.id)
        if change is None or card.id not in fresh:
            out.append(card)
            continue
        blocking = [
            c["path"]
            for c in change["checks"]
            if c["path"].startswith(CRITICAL_FIELDS) and c["status"] not in ACCEPTED_STATUSES
        ]
        if blocking:
            notes.append(f"{card.id}: kept published version; unverified critical {blocking}")
            out.append(card)
            continue
        other = [c["path"] for c in change["checks"] if c["status"] not in ACCEPTED_STATUSES]
        fetched = change.get("fetched_at")
        out.append(
            fresh[card.id].model_copy(
                update={"verified_at": datetime.fromisoformat(fetched) if fetched else None}
            )
        )
        notes.append(
            f"{card.id}: updated" + (f" (flagged, non-critical: {other})" if other else "")
        )
    return out, notes


def mark_page_variants(
    cards: list[CatalogCard], page_variants: dict[str, dict | None]
) -> tuple[list[CatalogCard], list[str]]:
    """Carry fetch-time findings into the catalog: a card whose latest fetch saw fee/offer
    numbers in the HTML that the rendered page hides is marked `varies_by_visitor`, and those
    raw-only numbers go to `quarantine`: noted for reviewers, never used as a value. This comes
    from the fetch, not the extraction, so it applies even when republishing old data."""
    out, notes = [], []
    for card in cards:
        hidden = (page_variants.get(card.id) or {}).get("hidden_in_render")
        if hidden:
            q = f"raw HTML only, not shown to visitors: {', '.join(hidden)}"
            card = card.model_copy(
                update={
                    "varies_by_visitor": True,
                    "quarantine": [*(x for x in card.quarantine if x != q), q],
                }
            )
            notes.append(f"{card.id}: varies by visitor; quarantined {hidden}")
        out.append(card)
    return out, notes


def load_verification(verification_dir: Path) -> dict[str, dict]:
    """Per-field verification logs (one JSON per card: final.fields[] with field/verdict/
    checked_at), produced by an independent check of an extraction against issuer pages."""
    out = {}
    for f in sorted(verification_dir.glob("*.json")):
        final = json.loads(f.read_text())["final"]
        out[final["id"]] = final
    return out


_INDEXED = re.compile(r"^(earning_rates|credits)\[(\d+)\]$")


def promote_preview(
    preview: CatalogSnapshot, verification: dict[str, dict]
) -> tuple[list[CatalogCard], list[str]]:
    """Turn a preview's cards into publishable ones using a field verification log.

    Cards without a verification log are left out. Earning rates and credits the log marks
    MISMATCH are dropped (omitting a perk beats publishing a wrong one); NOT_FOUND values are
    kept but reported. Returns the cards and a human-readable list of what changed.
    """
    cards, notes = [], []
    for card in preview.cards:
        if card.availability != "open":
            cards.append(card)
            continue
        log = verification.get(card.id)
        if not log:
            notes.append(f"{card.id}: no verification log, left out")
            continue
        drop: dict[str, set[int]] = {"earning_rates": set(), "credits": set()}
        for fld in log["fields"]:
            m = _INDEXED.match(fld["field"])
            if fld["verdict"] == "MISMATCH" and m:
                drop[m.group(1)].add(int(m.group(2)))
                notes.append(f"{card.id}: dropped {fld['field']} (MISMATCH)")
            elif fld["verdict"] == "MISMATCH":
                notes.append(f"{card.id}: {fld['field']} MISMATCH kept, needs manual fix")
            elif fld["verdict"] == "NOT_FOUND":
                notes.append(f"{card.id}: {fld['field']} not quoted on page (kept)")
        checked = max(f["checked_at"] for f in log["fields"])
        cards.append(
            card.model_copy(
                update={
                    "earning_rates": [
                        r
                        for i, r in enumerate(card.earning_rates)
                        if i not in drop["earning_rates"]
                    ],
                    "credits": [c for i, c in enumerate(card.credits) if i not in drop["credits"]],
                    "verified_at": datetime.fromisoformat(checked),
                }
            )
        )
    return cards, notes


def _digest(cards: list[CatalogCard]) -> str:
    payload = json.dumps([c.model_dump(mode="json") for c in cards], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


FIRST_VERSION = "1.1"


def versions(catalog_dir: Path = CATALOG_DIR) -> list[str]:
    """Published versions, oldest first ("1.1", "1.2", ..., "1.10")."""
    found = [p.stem[1:] for p in catalog_dir.glob("v*.json")]
    return sorted((v for v in found if re.fullmatch(VERSION_PATTERN, v)), key=version_key)


def latest(catalog_dir: Path = CATALOG_DIR) -> tuple[str | None, CatalogSnapshot | None]:
    published = versions(catalog_dir)
    if not published:
        return None, None
    v = published[-1]
    return v, CatalogSnapshot.model_validate_json((catalog_dir / f"v{v}.json").read_text())


def next_version(current: str | None) -> str:
    if current is None:
        return FIRST_VERSION
    major, minor = version_key(current)
    return f"{major}.{minor + 1}"


def publish(cards: list[CatalogCard], catalog_dir: Path = CATALOG_DIR) -> Path | None:
    """Write the next vMAJOR.MINOR.json if the catalog changed; return its path, or None."""
    version, previous = latest(catalog_dir)
    if previous is not None and _digest(previous.cards) == _digest(cards):
        return None
    snapshot = CatalogSnapshot(
        version=next_version(version),
        market=Market.US,
        generated_at=datetime.now(UTC),
        cards=cards,
    )
    catalog_dir.mkdir(parents=True, exist_ok=True)
    path = catalog_dir / f"v{snapshot.version}.json"
    path.write_text(snapshot.model_dump_json(indent=2) + "\n")
    return path
