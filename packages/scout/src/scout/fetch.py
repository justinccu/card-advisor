"""Polite page fetching with provenance: robots.txt, per-host rate limit, one honest identity.

Every page is fetched twice with the same honest profile:
- over plain HTTP (what a simple crawler gets), and
- rendered in a fresh headless browser (closest to what a first-time visitor sees).

Extraction always uses the rendered text. Fee/offer numbers present in the HTML but missing from
the rendered page are recorded as a *variant*: the issuer ships content that real visitors don't
see (e.g. Hilton Surpass: "$0 first year" in the HTML, only "$150" on screen).

We never disguise the crawler: no spoofed browser User-Agent, no cookie seeding or simulated human
behavior, and a block (403/429/challenge page) is recorded, not retried or worked around.
In the deployed pipeline the browser step becomes AgentCore Browser (ADR 0007).
"""

import hashlib
import json
import re
import time
import urllib.robotparser
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "card-advisor-scout/0.1 (+https://github.com/justinccu/card-advisor)"
# One pinned identity, so pages fetched at different times are comparable.
FETCH_PROFILE = {
    "user_agent": USER_AGENT,
    "locale": "en-US",
    "timezone": "America/Chicago",
    "cookies": "none (fresh browser context per page)",
}
MIN_INTERVAL_S = 2.0
# Below this much visible text, the page is almost certainly a JS shell or a block page.
MIN_TEXT_CHARS = 1500
# Wait for offer text to actually appear instead of a blind sleep. The pattern needs a number next
# to the offer wording: plain "Cash Back" or "Welcome Offer" already sit in nav menus at
# DOMContentLoaded, before the personalized offer block hydrates. Polled from Python by reading
# the DOM: some issuer pages disable eval, which page.wait_for_function relies on.
OFFER_WAIT_MS = 20_000
OFFER_TEXT_PATTERNS = [
    # offer wording before the number, so "every 5,000 miles you redeem" doesn't count;
    # may span a line break (Amex Gold renders "AS HIGH AS" and "100,000" on separate lines)
    # up to 3 words between number and unit: "100,000 Membership Rewards® points"
    r"(earn|as high as|bonus)[\s\S]{0,30}?\d[\d,]{3,}\s+(?:[\w®]+\s+){0,3}?(miles|points)",
    # up to 2 words between: "$200 cash bonus", "$150 Amazon Gift Card", "$250 Statement Credit"
    r"\$\d[\d,]*\s+(?:[\w®]+\s+){0,2}?(statement credit|cash back|bonus|gift card)",
    r"cashback match",
    r"apply and find out your welcome offer",  # hidden amount: still a real offer block
]
_OFFER_TEXT = re.compile("|".join(f"(?:{p})" for p in OFFER_TEXT_PATTERNS), re.I)
OFFER_POLL_MS = 250
# After offer text shows up, keep reading until the page text stops changing for this long:
# issuers ship offer-looking server-rendered text that client-side personalization then replaces
# (Delta Gold: a "$0 first year" block becomes "$150" plus an "As High As 80,000" offer).
STABLE_MS = 1000


def offer_text_present(text: str) -> bool:
    return bool(_OFFER_TEXT.search(text))


BLOCK_STATUSES = {401, 403, 429}
_CHALLENGE = re.compile(
    r"access denied|verify you are (a )?human|are you a robot|captcha|request unsuccessful"
    r"|unusual traffic",
    re.I,
)
_DROP_TAGS = ("script", "style", "noscript", "svg", "iframe", "template")


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    method: str  # "browser" | "http" (render failed or disabled) | "blocked"
    text: str
    content_hash: str
    fetched_at: str
    note: str = ""
    http_hash: str | None = None
    rendered_hash: str | None = None
    # {"hidden_in_render": [...], "render_only": [...]} when fee/offer numbers differ
    variant: dict | None = None
    # Whether offer text appeared in the rendered page within OFFER_WAIT_MS. False means the offer
    # is hidden (or the card has none): the model sees no offer, never raw-HTML numbers.
    offer_text_seen: bool | None = None
    fetch_profile: dict = field(default_factory=lambda: dict(FETCH_PROFILE))

    @property
    def blocked(self) -> bool:
        return self.method == "blocked"


class RobotsDenied(Exception):
    pass


def html_to_text(html: str) -> str:
    """Visible text, one block per line. Keeps header/footer: offer fine print often lives there."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    lines = (re.sub(r"\s+", " ", line).strip() for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)


_NO_FEE = re.compile(r"\bno annual fee\b|\$0 annual fee", re.I)
_FEE = re.compile(r"annual fee", re.I)
_MONEY = re.compile(r"\$\s?\d")
_OFFER = re.compile(
    r"(after|once) you (spend|make)|after spending|in purchases (within|in) the first"
    r"|bonus (points|miles|offer)|[\d,]{5,} (bonus )?(points|miles)|cashback match|gift card",
    re.I,
)
FEE_WINDOW_LINES = 6  # issuer pages split "Annual Fee" and "$95" across separate elements


def has_key_facts(text: str) -> bool:
    """Whether the text carries an annual fee and an offer/earning signal (a sanity check on
    what we hand to extraction; a JS shell or block page fails it)."""
    lines = text.splitlines()
    fee = bool(_NO_FEE.search(text)) or any(
        _FEE.search(window) and _MONEY.search(window)
        for window in (" ".join(lines[i : i + FEE_WINDOW_LINES]) for i in range(len(lines)))
    )
    return fee and bool(_OFFER.search(text))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# --- divergence -----------------------------------------------------------------------------

_KEY_LINE = re.compile(
    r"annual fee|welcome offer|bonus|earn\b|spend|introductory|first year|statement credit", re.I
)
KEY_WINDOW_LINES = 2  # a label line ("Annual Fee") plus the next line, where its value sits
_NUMBER = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?"  # $95, $5,000
    r"|\b\d{1,3}(?:,\d{3})+\s*(?:bonus\s+)?(?:points|miles)\b"  # 75,000 points
    r"|\b\d+(?:\.\d+)?%",  # 3%
    re.I,
)


# Rewards calculators ("Monthly card spend $2,200 ... You could earn 52,800 miles") ship one
# default in the HTML and another once their script runs; those numbers are neither fee nor offer.
_CALCULATOR = re.compile(r"monthly (?:card )?spend(?:ing)?|slide the bar|you could earn", re.I)


def key_numbers(text: str) -> set[str]:
    """Numbers stated on fee/offer lines (and the lines right after them), normalized."""
    lines = text.splitlines()
    found: set[str] = set()
    for i, line in enumerate(lines):
        if _KEY_LINE.search(line):
            window = " ".join(lines[i : i + KEY_WINDOW_LINES])
            if _CALCULATOR.search(window):
                continue
            found |= {re.sub(r"\s+", " ", m.group(0).lower()) for m in _NUMBER.finditer(window)}
    return found


def divergence(http_text: str, rendered_text: str) -> dict | None:
    """Fee/offer numbers that differ between the HTML and the rendered page.

    `hidden_in_render` is the dangerous direction: numbers the issuer ships in the HTML but does
    not show visitors, which an HTTP-only crawler would have extracted as fact. `render_only` is
    reported too but is usually just JavaScript-loaded content.
    """
    if not http_text or not rendered_text:
        return None
    h, r = key_numbers(http_text), key_numbers(rendered_text)
    hidden, render_only = sorted(h - r), sorted(r - h)
    if not hidden and not render_only:
        return None
    return {"hidden_in_render": hidden, "render_only": render_only}


def is_variant(variant: dict | None) -> bool:
    return bool(variant and variant["hidden_in_render"])


# --- fetching -------------------------------------------------------------------------------


class Fetcher:
    def __init__(
        self,
        *,
        render: bool = True,
        sleep=time.sleep,
        clock=time.monotonic,
        transport: httpx.BaseTransport | None = None,  # tests inject a mock
    ):
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            follow_redirects=True,
            timeout=30,
            transport=transport,
        )
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last_hit: dict[str, float] = {}
        self._render_enabled = render
        self._sleep, self._clock = sleep, clock
        self._browser = None

    def close(self) -> None:
        self._client.close()
        if self._browser:
            self._browser.close()
            self._playwright.stop()

    def _throttle(self, host: str) -> None:
        wait = self._last_hit.get(host, -MIN_INTERVAL_S) + MIN_INTERVAL_S - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last_hit[host] = self._clock()

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            self._throttle(parts.netloc)
            try:
                resp = self._client.get(f"{origin}/robots.txt")
                # RFC 9309: 4xx = no restrictions; 5xx or network error = assume disallowed.
                if resp.status_code >= 500:
                    parser.disallow_all = True
                elif resp.status_code >= 400:
                    # Must be explicit: an unparsed RobotFileParser denies everything.
                    parser.allow_all = True
                else:
                    parser.parse(resp.text.splitlines())
            except httpx.HTTPError:
                parser.disallow_all = True
            self._robots[origin] = parser
        return self._robots[origin].can_fetch(USER_AGENT, url)

    def _http(self, url: str) -> tuple[int, str, str, str]:
        """(status, final_url, visible text or "", error note or "")."""
        try:
            resp = self._client.get(url)
        except httpx.HTTPError as e:
            return 0, url, "", f"http error: {type(e).__name__}"
        text = html_to_text(resp.text) if resp.status_code == 200 else ""
        return resp.status_code, str(resp.url), text, ""

    def fetch(self, url: str) -> FetchResult:
        if not self.allowed(url):
            raise RobotsDenied(url)
        host = urlsplit(url).netloc
        now = datetime.now(UTC).isoformat(timespec="seconds")

        self._throttle(host)
        http_status, http_url, http_text, http_err = self._http(url)
        http_blocked = http_status in BLOCK_STATUSES
        http_ok = http_status == 200 and len(http_text) >= MIN_TEXT_CHARS

        r_status, r_url, r_text, r_err, offer_seen = 0, url, "", "", None
        if self._render_enabled:
            self._throttle(host)
            r_status, r_url, r_text, r_err, offer_seen = self._render(url)
        r_blocked = r_status in BLOCK_STATUSES or (
            bool(r_text) and len(r_text) < MIN_TEXT_CHARS and bool(_CHALLENGE.search(r_text))
        )
        r_ok = r_status == 200 and not r_blocked and len(r_text) >= MIN_TEXT_CHARS

        notes = []
        if http_blocked or r_blocked:
            notes.append(f"blocked ({'http ' + str(http_status) if http_blocked else 'render'})")
        notes += [e for e in (http_err, r_err) if e]

        if r_ok:
            method, status, final, text = "browser", r_status, r_url, r_text
            if offer_seen is False:
                notes.append(f"offer text did not appear within {OFFER_WAIT_MS // 1000}s (hidden)")
        elif http_ok and not self._render_enabled:
            # HTTP-only mode exists for tests/debugging; extraction refuses non-rendered pages.
            method, status, final, text = "http", http_status, http_url, http_text
        else:
            # No rendered text: nothing usable. Raw HTML is never promoted to the page text the
            # model reads, and blocks are recorded, never retried or routed around.
            if http_blocked or r_blocked:
                method = "blocked"
            else:
                method = "render_failed"
                notes.append("render failed; raw HTML not used")
            return FetchResult(
                url, url, r_status or http_status, method, "", "", now, "; ".join(notes)
            )

        if not has_key_facts(text):
            notes.append("key facts missing")
        return FetchResult(
            url,
            final,
            status,
            method,
            text,
            content_hash(text),
            now,
            "; ".join(notes),
            http_hash=content_hash(http_text) if http_ok else None,
            rendered_hash=content_hash(r_text) if r_ok else None,
            variant=divergence(http_text, r_text) if http_ok and r_ok else None,
            offer_text_seen=offer_seen if r_ok else None,
        )

    def _wait_for_offer(self, page) -> tuple[str, bool]:
        return _poll_offer(page, self._clock)

    def _render(self, url: str) -> tuple[int, str, str, str, bool | None]:
        """(status, final_url, visible text, error note, offer text seen) from a fresh browser
        context: no cookies, honest UA, pinned locale/timezone; discarded afterwards."""
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
        # locale, not an extra Accept-Language header: extra headers are attached to the page's
        # cross-origin API calls too, trip CORS preflights, and Amex then never loads its offer.
        context = self._browser.new_context(
            user_agent=FETCH_PROFILE["user_agent"],
            locale=FETCH_PROFILE["locale"],
            timezone_id=FETCH_PROFILE["timezone"],
        )
        page = context.new_page()
        try:
            # Not "networkidle": issuer pages keep analytics beacons open and never go idle.
            resp = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            text, seen = self._wait_for_offer(page)
            return (resp.status if resp else 0), page.url, text, "", seen
        except Exception as e:  # no rendered text: the page is recorded as render_failed
            return 0, url, "", f"render error: {type(e).__name__}", None
        finally:
            context.close()


def _poll_offer(page, clock=time.monotonic) -> tuple[str, bool]:
    """Read the page's visible text until offer text is present AND the text has stopped changing
    (hydration finished), or OFFER_WAIT_MS passes. Returns (text, whether offer text was seen).
    A timeout without offer text is reported honestly as not seen; the text returned is always
    what a visitor sees, never raw HTML."""
    deadline = clock() + OFFER_WAIT_MS / 1000
    stable_polls = STABLE_MS // OFFER_POLL_MS
    last, unchanged = None, 0
    while True:
        text = html_to_text(page.content())
        unchanged = unchanged + 1 if text == last else 0
        last = text
        seen = offer_text_present(text)
        if seen and unchanged >= stable_polls:
            return text, True
        if clock() >= deadline:
            return text, seen
        page.wait_for_timeout(OFFER_POLL_MS)


def save(result: FetchResult, key: str, cache_dir: Path) -> Path:
    """Store a fetch under pages/<key>/ (key may be "<card>/variants/<n>")."""
    out = cache_dir / "pages" / key
    out.mkdir(parents=True, exist_ok=True)
    (out / "page.txt").write_text(result.text)
    meta = asdict(result) | {"chars": len(result.text)}
    del meta["text"]
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return out


def load_cached(key: str, cache_dir: Path) -> tuple[dict, str] | None:
    out = cache_dir / "pages" / key
    if not (out / "meta.json").exists():
        return None
    return json.loads((out / "meta.json").read_text()), (out / "page.txt").read_text()
