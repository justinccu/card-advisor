import httpx
import pytest
from scout import fetch
from scout.fetch import Fetcher, RobotsDenied, has_key_facts, html_to_text


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


def _fetcher(handler, clock=None):
    f = Fetcher(
        browser_fallback=False, sleep=lambda s: sleeps.append(s), clock=clock or (lambda: 0)
    )
    f._client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return f


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


def test_js_shell_without_browser_returns_richest_http_text():
    shell = "<p>" + "Skip to main My Account " * 100 + "</p>"
    f = _fetcher(lambda req: httpx.Response(200, text=shell))
    result = f.fetch("https://bank.example/a")
    assert result.method == "http" and result.text  # kept for review rather than dropped
