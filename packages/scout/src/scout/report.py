"""Read-only HTML overview of an extraction run, to skim before `scout review`.

Local file only (catalog/.cache is gitignored): it quotes issuer pages, which we don't publish.
"""

import html
import json
from pathlib import Path

from scout.review import FLAGGED, closest_line

_CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#e3e3e3;--ok:#1a7f37;--warn:#9a6700;--bad:#cf222e;--card:#fafafa}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#9aa4ae;--line:#30363d;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--card:#161b22}}
body{font:14px/1.5 -apple-system,system-ui,sans-serif;background:var(--bg);color:var(--fg);max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:20px}h2{font-size:16px;margin:0}a{color:inherit}
.summary{display:flex;gap:16px;flex-wrap:wrap;margin:12px 0 20px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 14px}
.stat b{font-size:20px;display:block}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}
.head{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:baseline}
.badge{font-weight:600}.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
table{border-collapse:collapse;width:100%;margin-top:8px}
td{border-top:1px solid var(--line);padding:4px 6px;vertical-align:top}
td:first-child{white-space:nowrap;color:var(--muted);width:1%}
.q{color:var(--muted);font-size:12px}.flag{background:rgba(210,153,34,.12)}
.notes{color:var(--muted);font-size:12px;margin-top:8px}
"""


def _row(check: dict, page: str) -> str:
    status = check["status"]
    mark = {
        "verified": "✓",
        "approximate": "≈",
        "unverified": "⚠",
        "missing_evidence": "✗",
        "value_not_in_quote": "≠",
    }[status]
    cls = "ok" if status in ("verified", "approximate") else "warn"
    quote = html.escape(check["evidence"] or "(no quote)")
    extra = ""
    if status == "unverified":
        hint = closest_line(check["evidence"], page)
        if hint:
            extra = f'<div class="q">page says: “{html.escape(hint)}”</div>'
    flag = ' class="flag"' if status in FLAGGED else ""
    return (
        f"<tr{flag}><td><span class='{cls}'>{mark}</span> {html.escape(check['path'])}</td>"
        f"<td>{html.escape(str(check['value']))}<div class='q'>“{quote}”</div>{extra}</td></tr>"
    )


def _card(change: dict, page: str) -> str:
    filled = [c for c in change["checks"] if c["status"] != "empty"]
    flagged = [c for c in filled if c["status"] in FLAGGED]
    ratio = (len(filled) - len(flagged)) / len(filled) if filled else 0
    cls = "ok" if not flagged else ("warn" if ratio >= 0.75 else "bad")
    x = change["extracted"]
    offer = x.get("offer")
    hidden = (
        "<div class='warn'>Offer amount not publicly disclosed</div>"
        if offer and not offer["amount_disclosed"]
        else ""
    )
    if offer and offer.get("amount_is_up_to"):
        hidden += "<div class='warn'>Offer is a ceiling (“as high as / up to”)</div>"
    empty = ", ".join(c["path"] for c in change["checks"] if c["status"] == "empty")
    key = change.get("source_key", "")
    label = key if "/variants/" in key else change["card_id"]
    page_variant = change.get("page_variant") or {}
    if page_variant.get("hidden_in_render"):
        hidden += (
            "<div class='warn'>Page varies by visitor: the HTML contains "
            f"{html.escape(', '.join(page_variant['hidden_in_render']))} that the rendered page "
            "does not show</div>"
        )
    notes = html.escape(x.get("reviewer_notes") or "")
    return f"""
<section class="card" id="{html.escape(label)}">
  <div class="head">
    <h2>{html.escape(label)}{" · campaign page" if "/variants/" in label else ""}</h2>
    <span class="badge {cls}">{ratio:.0%} verified · {len(flagged)} flagged</span>
    <a href="{html.escape(change["source_url"])}" target="_blank" rel="noopener">source page ↗</a>
  </div>
  {hidden}
  <table>{"".join(_row(c, page) for c in filled)}</table>
  {f'<div class="notes">not stated on page: {html.escape(empty)}</div>' if empty else ""}
  {f'<div class="notes">model notes (not published): {notes}</div>' if notes else ""}
</section>"""


def build(run_dir: Path, pages: dict[str, str]) -> str:
    changes = [
        json.loads(p.read_text())
        for p in sorted(run_dir.glob("*.json"))
        if not p.name.endswith(".invalid.json")
    ]
    invalid = sorted(p.name.removesuffix(".invalid.json") for p in run_dir.glob("*.invalid.json"))

    def n_flagged(c: dict) -> int:
        return sum(ch["status"] in FLAGGED for ch in c["checks"])

    changes.sort(key=lambda c: (-n_flagged(c), c["card_id"]))
    clean = sum(n_flagged(c) == 0 for c in changes)
    cost = sum(c["cost_usd"] for c in changes)
    body = "".join(_card(c, pages.get(c["card_id"], "")) for c in changes)
    invalid_html = (
        f"<p class='bad'>Failed schema validation (not reviewable yet): {', '.join(invalid)}</p>"
        if invalid
        else ""
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scout Review Report</title><style>{_CSS}</style></head><body>
<h1>Scout review report · run {html.escape(run_dir.name)}</h1>
<div class="summary">
  <div class="stat"><b>{len(changes)}</b>cards extracted</div>
  <div class="stat"><b class="ok">{clean}</b>fully verified</div>
  <div class="stat"><b class="warn">{len(changes) - clean}</b>with flagged fields</div>
  <div class="stat"><b>${cost:.3f}</b>model cost</div>
</div>
{invalid_html}
<p>Flagged cards come first. ⚠ = quote not found on page (usually paraphrased; check
“page says”), ✗ = value without a quote. Open “source page” to confirm numbers, then approve in
<code>scout review</code>.</p>
{body}
</body></html>"""
