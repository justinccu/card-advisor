"""Polite page fetching: robots.txt, per-host rate limit, honest User-Agent, browser fallback.

Plain HTTP first; a headless browser only when the page is blocked or is a JavaScript shell.
In the deployed pipeline the browser step becomes AgentCore Browser (ADR 0007).
"""

import hashlib
import json
import re
import time
import urllib.robotparser
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "card-advisor-scout/0.1 (+https://github.com/justinccu/card-advisor)"
MIN_INTERVAL_S = 2.0
# Below this much visible text, the page is almost certainly a JS shell or a block page.
MIN_TEXT_CHARS = 1500
RENDER_SETTLE_MS = 8000  # Amex hydrates its offer block ~5-8s after DOMContentLoaded
_DROP_TAGS = ("script", "style", "noscript", "svg", "iframe", "template")


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    method: str  # "http" | "browser"
    text: str
    content_hash: str
    fetched_at: str
    note: str = ""


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
    """Whether the text carries an annual fee and an offer/earning signal.

    Only decides whether to also try the browser, so a false negative costs time, not accuracy.
    """
    lines = text.splitlines()
    fee = bool(_NO_FEE.search(text)) or any(
        _FEE.search(window) and _MONEY.search(window)
        for window in (" ".join(lines[i : i + FEE_WINDOW_LINES]) for i in range(len(lines)))
    )
    return fee and bool(_OFFER.search(text))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Fetcher:
    def __init__(self, *, browser_fallback: bool = True, sleep=time.sleep, clock=time.monotonic):
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            follow_redirects=True,
            timeout=30,
        )
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last_hit: dict[str, float] = {}
        self._browser_fallback = browser_fallback
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

    def fetch(self, url: str) -> FetchResult:
        if not self.allowed(url):
            raise RobotsDenied(url)
        self._throttle(urlsplit(url).netloc)
        now = datetime.now(UTC).isoformat(timespec="seconds")
        http_result = None
        try:
            resp = self._client.get(url)
            text = html_to_text(resp.text)
            if resp.status_code == 200 and len(text) >= MIN_TEXT_CHARS:
                http_result = FetchResult(
                    url, str(resp.url), 200, "http", text, content_hash(text), now
                )
                if has_key_facts(text):
                    return http_result
            note = f"http {resp.status_code}, {len(text)} chars"
        except httpx.HTTPError as e:
            note = f"http error: {type(e).__name__}"

        if not self._browser_fallback:
            return http_result or FetchResult(url, url, 0, "http", "", "", now, note)
        browser_result = self._fetch_browser(url, now, note + ", key facts missing")
        if has_key_facts(browser_result.text) or http_result is None:
            return browser_result
        # Neither has the key facts: keep the richer text and let extraction/review flag gaps.
        best = max(http_result, browser_result, key=lambda r: len(r.text))
        best.note = "key facts missing in both http and browser"
        return best

    def _fetch_browser(self, url: str, now: str, note: str) -> FetchResult:
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
        # locale, not an extra Accept-Language header: extra headers are attached to the page's
        # cross-origin API calls too, trip CORS preflights, and Amex then never loads its offer.
        page = self._browser.new_page(locale="en-US")
        try:
            # Not "networkidle": issuer pages keep analytics beacons open and never go idle.
            resp = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            try:
                page.wait_for_load_state("load", timeout=15_000)
            except Exception:
                pass  # render whatever arrived; the offer block is usually already hydrated
            page.wait_for_timeout(RENDER_SETTLE_MS)
            text = html_to_text(page.content())
            status = resp.status if resp else 0
            return FetchResult(
                url, page.url, status, "browser", text, content_hash(text), now, note
            )
        finally:
            page.close()


def save(result: FetchResult, card_id: str, cache_dir: Path) -> Path:
    out = cache_dir / "pages" / card_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "page.txt").write_text(result.text)
    meta = asdict(result) | {"chars": len(result.text)}
    del meta["text"]
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return out


def load_cached(card_id: str, cache_dir: Path) -> tuple[dict, str] | None:
    out = cache_dir / "pages" / card_id
    if not (out / "meta.json").exists():
        return None
    return json.loads((out / "meta.json").read_text()), (out / "page.txt").read_text()
