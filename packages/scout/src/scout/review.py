"""Human review of Proposed Changes (ADR 0002). Nothing reaches the catalog without a decision here.

Core functions are pure; the interactive loop only wires them to input()/print() so it can be
tested with scripted answers.
"""

import copy
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scout.evidence import normalize

SYMBOL = {"verified": "✓", "unverified": "⚠", "missing_evidence": "✗", "empty": "·"}
FLAGGED = ("unverified", "missing_evidence")


@dataclass
class Review:
    card_id: str
    run: str
    decision: str  # "approved" | "rejected"
    reviewed_at: str
    content_hash: str
    source_url: str
    model_id: str
    fields_total: int
    edits: list[dict] = field(default_factory=list)
    final: dict | None = None
    reason: str = ""

    def save(self, reviews_dir: Path) -> Path:
        reviews_dir.mkdir(parents=True, exist_ok=True)
        path = reviews_dir / f"{self.card_id}.json"
        path.write_text(json.dumps(self.__dict__, indent=2))
        return path


def load_reviews(reviews_dir: Path) -> dict[str, dict]:
    if not reviews_dir.exists():
        return {}
    return {p.stem: json.loads(p.read_text()) for p in sorted(reviews_dir.glob("*.json"))}


def latest_run(runs_dir: Path) -> Path:
    runs = sorted(p for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.exists() else []
    if not runs:
        raise SystemExit("no extraction runs yet (run `scout extract --live`)")
    return runs[-1]


def closest_line(evidence: str, page_text: str) -> str | None:
    """The page line sharing the most words with a quote the model got wrong, to speed review."""
    want = set(re.findall(r"\w+", normalize(evidence)))
    if not want:
        return None
    best = max(
        page_text.splitlines(),
        key=lambda line: len(want & set(re.findall(r"\w+", normalize(line)))),
        default=None,
    )
    return best if best and want & set(re.findall(r"\w+", normalize(best))) else None


def render(change: dict, page_text: str) -> str:
    x = change["extracted"]
    out = [
        f"{change['card_id']}  ({change['source_url']})",
        f"model {change['model_id']}  cost ${change['cost_usd']:.4f}",
        "",
    ]
    for check in change["checks"]:
        if check["status"] == "empty":
            continue
        out.append(f"  {SYMBOL[check['status']]} {check['path']:28} {check['value']}")
        if check["evidence"]:
            out.append(f'      quote: "{check["evidence"]}"')
        if check["status"] == "unverified":
            hint = closest_line(check["evidence"], page_text)
            out.append(
                f'      not on page; closest line: "{hint}"' if hint else "      not on page"
            )
    empty = [c["path"] for c in change["checks"] if c["status"] == "empty"]
    if empty:
        out.append(f"  · not stated on page: {', '.join(empty)}")
    if x.get("offer") and not x["offer"]["amount_disclosed"]:
        out.append("  ! offer amount is not disclosed publicly")
    if x.get("reviewer_notes"):
        out.append(f"  notes: {x['reviewer_notes']}")
    return "\n".join(out)


_PATH_PART = re.compile(r"([a-z_]+)(?:\[(\d+)\])?")


def _walk(obj: Any, path: str) -> tuple[Any, str | int]:
    """Return (container, key) for a dotted path like 'offer.amount.value' or 'credits[0]'."""
    parts = path.split(".")
    for part in parts[:-1]:
        name, idx = _PATH_PART.fullmatch(part).groups()
        obj = obj[name] if idx is None else obj[name][int(idx)]
    name, idx = _PATH_PART.fullmatch(parts[-1]).groups()
    return (obj, name) if idx is None else (obj[name], int(idx))


def apply_edit(extracted: dict, path: str, raw: str) -> tuple[dict, dict]:
    """Set a value (JSON, or a bare string) at `path`; 'del <path>' semantics via raw == '<del>'."""
    updated = copy.deepcopy(extracted)
    try:
        container, key = _walk(updated, path)
        old = container[key]
    except (AttributeError, KeyError, IndexError, TypeError) as e:
        raise ValueError(f"no such field: {path}") from e
    if raw == "<del>":
        del container[key]
        new = None
    else:
        try:
            new = json.loads(raw)
        except json.JSONDecodeError:
            new = raw
        container[key] = new
    return updated, {"path": path, "old": old, "new": new}


def decide(
    change: dict,
    page_text: str,
    *,
    run: str,
    ask: Callable[[str], str],
    say: Callable[[str], None],
) -> Review | None:
    """Interactive review of one Proposed Change. Returns None when the reviewer skips it."""
    extracted = copy.deepcopy(change["extracted"])
    edits: list[dict] = []
    filled = [c for c in change["checks"] if c["status"] != "empty"]
    flagged = [c["path"] for c in filled if c["status"] in FLAGGED]
    say(render(change, page_text))

    def review(decision: str, **kw) -> Review:
        return Review(
            card_id=change["card_id"],
            run=run,
            decision=decision,
            reviewed_at=datetime.now(UTC).isoformat(timespec="seconds"),
            content_hash=change["content_hash"],
            source_url=change["source_url"],
            model_id=change["model_id"],
            fields_total=len(filled),
            edits=edits,
            **kw,
        )

    while True:
        choice = ask("\n[a]pprove  [e]dit  [r]eject  [s]kip  [q]uit > ").strip().lower()
        if choice == "a":
            unresolved = [p for p in flagged if not any(e["path"].startswith(p) for e in edits)]
            if unresolved:
                ok = ask(
                    f"{len(unresolved)} flagged field(s) unedited: {unresolved}. Approve? [y/N] "
                )
                if ok.strip().lower() != "y":
                    continue
            return review("approved", final=extracted)
        if choice == "e":
            path = ask("field path (e.g. offer.amount.value, earning_rates[1], credits[0]) > ")
            raw = ask("new value as JSON, or <del> to remove > ")
            try:
                extracted, edit = apply_edit(extracted, path.strip(), raw.strip())
            except ValueError as e:
                say(str(e))
                continue
            edits.append(edit)
            say(f"  {edit['path']}: {edit['old']!r} -> {edit['new']!r}")
        elif choice == "r":
            return review("rejected", reason=ask("reason > ").strip())
        elif choice == "s":
            return None
        elif choice == "q":
            raise KeyboardInterrupt


def field_key(path: str) -> str:
    """Map an edit path to the field it corrects: 'offer.amount.value' -> 'offer.amount'."""
    path = re.sub(r"\.(value|evidence)$", "", path)
    m = re.match(r"(earning_rates|credits)\[\d+\]", path)
    return m.group(0) if m else path


def accuracy(reviews: dict[str, dict]) -> dict[str, float | int]:
    """Extraction quality: share of fields approved without a reviewer edit."""
    approved = [r for r in reviews.values() if r["decision"] == "approved"]
    fields = sum(r["fields_total"] for r in approved)
    edited = sum(len({field_key(e["path"]) for e in r["edits"]}) for r in approved)
    return {
        "cards_approved": len(approved),
        "cards_rejected": sum(r["decision"] == "rejected" for r in reviews.values()),
        "fields_reviewed": fields,
        "fields_edited": edited,
        "accepted_unchanged": (fields - edited) / fields if fields else 0.0,
    }
