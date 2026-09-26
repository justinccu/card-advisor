import httpx
import pytest
from scout import fetch
from scout.fetch import (
    USER_AGENT,
    Fetcher,
    RobotsDenied,
    divergence,
    has_key_facts,
    html_to_text,
    is_variant,
    key_numbers,
)


def test_html_to_text_drops_scripts_but_keeps_footer_fine_print():
    html = """<html><head><style>.x{}</style><script>var offer=1</script></head>
    <body><h1>Card</h1><p>Earn   60,000 points</p>
    <footer>Offer terms apply</footer></body></html>"""
    assert html_to_text(html) == "Card\nEarn 60,000 points\nOffer terms apply"


@pytest.mark.parametrize(
    "text",
    [
        "Annual Fee\nIntro\n$95\nEarn 60,000\nbonus points",  # label and amount split across lines
        "No annual fee\nEarn a $200 online cash rewards bonus offer after you make $1,000",
        "no annual fee\nUnlimited Cashback Match",
    ],
)
def test_key_facts_detected(text):
    assert has_key_facts(text)


@pytest.mark.parametrize(
    "text",
    [
        "Skip to main\nMy Account\nNo Annual Fee Credit Cards",  # nav-only shell: no offer signal
        "Earn 60,000 bonus points after you spend $4,000",  # no fee at all
    ],
)
def test_key_facts_missing(text):
    assert not has_key_facts(text)


def _fetcher(handler, clock=None, render=False):
    return Fetcher(
        render=render,
        sleep=lambda s: sleeps.append(s),
        clock=clock or (lambda: 0),
        transport=httpx.MockTransport(handler),
    )


sleeps: list[float] = []

PAGE = "<p>" + "filler " * 300 + "</p><p>Annual fee $95</p><p>Earn 60,000 bonus points</p>"


def test_robots_disallow_is_respected():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /cards/")
        return httpx.Response(200, text=PAGE)

    f = _fetcher(handler)
    with pytest.raises(RobotsDenied):
        f.fetch("https://bank.example/cards/gold")
    assert f.fetch("https://bank.example/other").method == "http"


def test_robots_server_error_means_disallow_all():
    f = _fetcher(lambda req: httpx.Response(503))
    assert not f.allowed("https://bank.example/cards/gold")


def test_robots_404_means_no_restrictions():
    def handler(req):
        return (
            httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, text=PAGE)
        )

    assert _fetcher(handler).fetch("https://bank.example/cards/gold").status == 200


def test_same_host_requests_are_spaced_out():
    sleeps.clear()
    f = _fetcher(lambda req: httpx.Response(200, text=PAGE), clock=lambda: 100.0)
    f.fetch("https://bank.example/a")  # robots.txt + page: second hit on the host must wait
    assert sleeps and all(s == pytest.approx(fetch.MIN_INTERVAL_S) for s in sleeps)


def test_js_shell_without_render_is_kept_and_flagged():
    shell = "<p>" + "Skip to main My Account " * 100 + "</p>"
    f = _fetcher(lambda req: httpx.Response(200, text=shell))
    result = f.fetch("https://bank.example/a")
    assert result.method == "http" and result.text  # kept for review rather than dropped
    assert "key facts missing" in result.note


# --- divergence (HTML vs rendered) ----------------------------------------------------------

SURPASS_HTML = (
    "Annual Fee\n$0 introductory annual fee for the first year, then $150.\nEarn 130,000 points"
)
SURPASS_RENDERED = "Annual Fee\n$150\nEarn 130,000 points"


def test_hidden_html_offer_is_flagged_as_variant():
    # Hilton Surpass: the HTML ships a "$0 first year" block that visitors never see.
    v = divergence(SURPASS_HTML, SURPASS_RENDERED)
    assert v["hidden_in_render"] == ["$0"]
    assert is_variant(v)


def test_one_sentence_with_two_fees_is_not_a_variant():
    # Both versions say "$0 first year, then $150": two fields, one version.
    assert divergence(SURPASS_HTML, SURPASS_HTML) is None


def test_js_loaded_numbers_alone_are_not_a_variant():
    v = divergence("Annual Fee\n$95", "Annual Fee\n$95\nEarn 75,000 bonus points")
    assert v == {"hidden_in_render": [], "render_only": ["75,000 bonus points"]}
    assert not is_variant(v)


def test_key_numbers_only_reads_fee_and_offer_lines():
    text = (
        "Annual Fee\n$95\nFooter: call $1,000,000 prize line\n"
        "Earn 60,000 points after you spend $4,000"
    )
    assert key_numbers(text) == {"$95", "60,000 points", "$4,000"}


# --- dual fetch with a fake renderer --------------------------------------------------------

LONG = "filler " * 300


class FakeRenderFetcher(Fetcher):
    def __init__(self, handler, rendered: tuple[int, str], offer_seen: bool = True):
        super().__init__(
            render=True,
            sleep=lambda s: None,
            clock=lambda: 0,
            transport=httpx.MockTransport(handler),
        )
        self.rendered = rendered
        self.offer_seen = offer_seen
        self.render_calls: list[str] = []

    def _render(self, url):
        self.render_calls.append(url)
        status, text = self.rendered
        return status, url, text, "", self.offer_seen


def _page(body):
    return lambda req: (
        httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, text=body)
    )


def test_extraction_gets_the_rendered_text_and_variant_is_recorded():
    html = (
        f"<p>{LONG}</p><p>Annual Fee</p><p>$0 introductory annual fee, then $150.</p>"
        "<p>Earn 130,000 bonus points</p>"
    )
    rendered = f"{LONG}\nAnnual Fee\n$150\nEarn 130,000 bonus points"
    f = FakeRenderFetcher(_page(html), (200, rendered))
    r = f.fetch("https://bank.example/surpass")
    assert r.method == "browser" and r.text == rendered
    assert r.variant["hidden_in_render"] == ["$0"]
    assert r.http_hash and r.rendered_hash and r.http_hash != r.rendered_hash
    assert r.fetch_profile["user_agent"] == USER_AGENT


def test_render_failure_never_promotes_raw_html():
    # The HTML is perfectly readable, but the model may only ever see rendered text.
    f = FakeRenderFetcher(_page(PAGE), (0, ""))
    r = f.fetch("https://bank.example/a")
    assert r.method == "render_failed" and r.text == "" and "raw HTML not used" in r.note


def test_offer_text_that_never_appears_is_recorded_as_hidden():
    rendered = f"{LONG}\nAnnual Fee\n$95\nApply now"
    f = FakeRenderFetcher(_page(PAGE), (200, rendered), offer_seen=False)
    r = f.fetch("https://bank.example/a")
    assert r.method == "browser" and r.offer_text_seen is False and "hidden" in r.note
    assert r.text == rendered  # what visitors see, not the HTML's "Earn 60,000 bonus points"


def test_block_is_recorded_not_retried_and_nothing_is_fetched_first():
    seen: list[str] = []

    def handler(req):
        seen.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        assert req.headers["user-agent"] == USER_AGENT  # never a disguised browser UA
        return httpx.Response(403, text="Access Denied")

    f = FakeRenderFetcher(handler, (403, "Access Denied"))
    r = f.fetch("https://bank.example/cards/gold")
    assert r.blocked and r.text == ""
    # robots.txt, then the page exactly once: no homepage warm-up, no retry
    assert seen == ["https://bank.example/robots.txt", "https://bank.example/cards/gold"]
    assert f.render_calls == ["https://bank.example/cards/gold"]


def test_challenge_page_counts_as_blocked():
    f = FakeRenderFetcher(_page("<p>short</p>"), (200, "Please verify you are a human"))
    assert f.fetch("https://bank.example/a").blocked


def test_browser_context_uses_the_honest_profile(monkeypatch):
    calls = {}

    class Page:
        url = "https://bank.example/a"

        def goto(self, *a, **k):
            return type("R", (), {"status": 200})()

        def wait_for_timeout(self, ms):
            calls["polls"] = calls.get("polls", 0) + 1

        def content(self):
            return "<p>Annual Fee $95</p><p>Earn 75,000 bonus points</p>"

    class Context:
        def new_page(self):
            return Page()

        def close(self):
            calls["closed"] = True

    class Browser:
        def new_context(self, **kw):
            calls["context"] = kw
            return Context()

    f = Fetcher(render=True)
    f._browser = Browser()
    status, _, text, err, seen = f._render("https://bank.example/a")
    assert status == 200 and not err and seen is True
    # offer text present from the start: only waits for the text to hold steady
    assert calls["polls"] == fetch.STABLE_MS // fetch.OFFER_POLL_MS
    assert calls["context"] == {
        "user_agent": USER_AGENT,
        "locale": "en-US",
        "timezone_id": "America/Chicago",
    }
    assert calls["closed"]  # a fresh context per page: no cookies carry over
    f._browser = None
    f.close()


def test_offer_wait_ignores_nav_links_and_matches_real_offer_text():
    # Nav menus contain "Cash Back" / "Welcome Offer" before the offer block hydrates.
    assert not fetch.offer_text_present("Cash Back Credit Cards\nWelcome Offer & Key Details")
    assert fetch.offer_text_present("As High As 80,000 Bonus Miles")  # Delta Gold
    assert fetch.offer_text_present("Earn a $250 Statement Credit")
    assert fetch.offer_text_present("Apply and find out your welcome offer")
    assert fetch.offer_text_present("AS HIGH AS\n100,000\nMembership Rewards points")  # Amex Gold
    assert fetch.offer_text_present("Earn 75,000 points after you spend $5,000")
    assert fetch.offer_text_present("Earn a one-time $200 cash bonus")  # Capital One Quicksilver
    assert fetch.offer_text_present("Get a $150 Amazon Gift Card instantly")  # Prime Visa
    # Delta Gold's server-rendered benefits text, present before the real offer hydrates
    assert not fetch.offer_text_present("$50 off the cost of your flight for every 5,000 miles")


class _HydratingPage:
    """Server-rendered text first; after `after` polls, personalization swaps in the real offer
    block and the page then stays unchanged."""

    SSR = "<p>Annual Fee</p><p>$0 introductory annual fee, then $150</p><p>Earn 60,000 points</p>"
    HYDRATED = "<p>Annual Fee</p><p>$150</p><p>As High As 80,000 Bonus Miles</p>"

    def __init__(self, after):
        self.after, self.polls = after, 0

    def content(self):
        return self.HYDRATED if self.polls >= self.after else self.SSR

    def wait_for_timeout(self, ms):
        self.polls += 1


def test_poll_waits_for_hydration_not_the_first_offer_looking_text():
    # SSR text already "looks like" an offer; reading it would capture the hidden $0 variant.
    page = _HydratingPage(after=2)
    text, seen = fetch._poll_offer(page, clock=lambda: 0.0)
    assert seen and "80,000 Bonus Miles" in text and "$0 introductory" not in text
    stable = fetch.STABLE_MS // fetch.OFFER_POLL_MS
    assert page.polls == 2 + stable  # returned once the hydrated text held steady


def test_poll_times_out_honestly_without_offer_text():
    class NoOffer(_HydratingPage):
        def content(self):
            return f"<p>Welcome Offer</p><p>poll {self.polls}</p>"  # keeps changing, no offer

    now = [0.0]

    def clock():
        now[0] += 1.0  # each poll "takes" a second
        return now[0]

    page = NoOffer(after=0)
    text, seen = fetch._poll_offer(page, clock=clock)
    assert not seen and "Welcome Offer" in text
    assert page.polls <= fetch.OFFER_WAIT_MS / 1000 + 1


def test_rewards_calculator_defaults_are_not_a_page_variant():
    http = (
        "Earn 75,000 bonus miles\nMonthly card spend $2,200\nYou could earn 52,800 miles per year"
    )
    rendered = (
        "Earn 75,000 bonus miles\nMonthly card spend $420\nYou could earn 10,080 miles per year"
    )
    assert divergence(http, rendered) is None
