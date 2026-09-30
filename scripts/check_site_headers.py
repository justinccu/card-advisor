"""Load the built site (web/out) under the same headers and URL rules CloudFront uses, and fail
on any Content-Security-Policy violation or page error. Catches a CSP that would break the live
site before it is deployed. Nothing is deployed and no model is called.

    make site-check   # builds web/out against the deployed stack, then runs this
"""

import os
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parents[1] / "infra"))
from stacks.web_stack import CSP  # noqa: E402

OUT = Path(__file__).parents[1] / "web" / "out"
PORT = 3100
PAGES = ["/", "/cards/", "/cards/amex_gold/", "/compare/", "/wallet/", "/signin/", "/advisor/"]
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class Site(SimpleHTTPRequestHandler):
    """web/out with CloudFront's rules: /x/ -> /x/index.html, /x -> 301 /x/, missing -> 404."""

    def do_GET(self):
        path = self.path.split("?")[0]
        name = path.rsplit("/", 1)[-1]
        if path != "/" and not path.endswith("/") and "." not in name:
            self.send_response(301)
            self.send_header("Location", path + "/")
            self.end_headers()
            return
        target = OUT / (path.lstrip("/") + ("index.html" if path.endswith("/") else ""))
        if not target.is_file():
            body = (OUT / "404.html").read_bytes()
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        for key, value in HEADERS.items():
            self.send_header(key, value)
        super().end_headers()

    def log_message(self, *args):
        pass


def main() -> int:
    if not (OUT / "index.html").is_file():
        sys.exit("No web/out: run `make site-check` (it builds the site first).")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), partial(Site, directory=str(OUT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{PORT}"
    violations, errors, results = [], [], []

    with sync_playwright() as p:
        page = p.chromium.launch().new_page()
        page.on(
            "console",
            lambda m: ("Content Security Policy" in m.text or "Refused to" in m.text)
            and violations.append(f"{page.url}: {m.text[:200]}"),
        )
        page.on("pageerror", lambda e: errors.append(f"{page.url}: {e}"))
        for path in PAGES:
            response = page.goto(base + path, wait_until="networkidle")
            ok = response.status == 200 and page.locator("main").count() == 1
            results.append(("PASS" if ok else "FAIL") + f"  {path} renders ({response.status})")
        missing = page.goto(base + "/no-such-page/", wait_until="networkidle")
        results.append(("PASS" if missing.status == 404 else "FAIL") + "  unknown page -> 404")
        page.goto(base + "/cards/")
        page.get_by_role("button", name="Ask the Advisor").click()  # the chat panel opens
        page.wait_for_timeout(500)

        # The CSP must allow the three services the site calls; a blocked request logs a CSP
        # violation (CORS or 4xx answers are fine here: the request left the page).
        probes = {
            "API": (os.environ.get("NEXT_PUBLIC_API_URL", "") + "/health", "GET"),
            "Cognito": ("https://cognito-idp.us-east-2.amazonaws.com/", "POST"),
            "Advisor": (os.environ.get("NEXT_PUBLIC_ADVISOR_URL", ""), "POST"),
        }
        # Control: a host the CSP doesn't list must be refused, or this check proves nothing.
        before = len(violations)
        page.evaluate("() => fetch('https://example.com/').catch(() => null)")
        page.wait_for_timeout(300)
        caught = len(violations) > before
        del violations[before:]
        results.append(("PASS" if caught else "FAIL") + "  an unlisted host is refused (control)")
        for name, (url, method) in probes.items():
            if not url.startswith("https://"):
                results.append(f"SKIP  {name} probe (no URL in the environment)")
                continue
            page.evaluate(
                "([url, method]) => fetch(url, {method}).catch(() => null)", [url, method]
            )
            page.wait_for_timeout(300)
            results.append(f"PASS  {name} request allowed by the CSP")
    server.shutdown()

    if violations:
        results.append("FAIL  CSP violations:\n    " + "\n    ".join(violations[:10]))
    if errors:
        results.append("FAIL  page errors:\n    " + "\n    ".join(errors[:5]))
    print("\n".join(results))
    return 0 if all(not r.startswith("FAIL") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
