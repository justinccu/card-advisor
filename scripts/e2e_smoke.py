"""Browser smoke test of the local demo: invite sign-up, optimistic wallet add/remove, rollback
when the API fails, sheet drag-to-dismiss vs. spring-back, modal inertness, compare, deck fling.

Needs the demo running (`make demo`), then: `make e2e`. Uses Playwright's Chromium ($0).
"""

import re
import sys
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

# Matches with or without a query string (the site pins ?catalog_version=...).
WALLET_CARDS = re.compile(r".*/me/wallet/cards(\?.*)?$")

BASE = "http://localhost:3000"
results = []

try:
    with urllib.request.urlopen(BASE + "/signin/", timeout=10) as r:
        signin_html = r.read().decode()
except (urllib.error.URLError, OSError):
    sys.exit("Nothing on localhost:3000: start `make demo` in another terminal, then retry.")
if "Welcome back." in signin_html:
    sys.exit("localhost:3000 is the AWS-backed site (`make web-aws`); stop it and run `make demo`.")


def check(name, cond):
    results.append(("PASS" if cond else "FAIL") + "  " + name)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    # invite flow
    page.goto(BASE + "/signin/", wait_until="networkidle")
    page.get_by_label("Invite code").fill("WRONG-CODE")
    page.get_by_role("button", name="Continue").click()
    page.wait_for_timeout(600)
    check("invalid invite shows error", page.get_by_text("invite code is invalid").is_visible())
    page.get_by_label("Invite code").fill("DEMO-2026")
    page.get_by_role("button", name="Continue").click()
    page.wait_for_url("**/wallet/")
    page.wait_for_timeout(1200)
    check("valid invite -> new empty wallet", page.get_by_text("No cards yet").is_visible())

    # demo account
    page.goto(BASE + "/signin/", wait_until="networkidle")
    page.get_by_text("Use demo account").click()
    page.wait_for_url("**/wallet/")
    page.wait_for_timeout(1500)
    rows = page.locator("ul li:has(p:text('opened'))")
    n0 = rows.count()
    check(f"demo wallet has 5 cards (got {n0})", n0 == 5)
    gauge = page.locator("p.headline").first
    check(f"gauge shows 4 (got {gauge.inner_text()!r})", gauge.inner_text().startswith("4"))

    # optimistic add
    page.get_by_role("button", name="Add card").click()
    page.wait_for_timeout(500)
    page.get_by_label("Search cards").last.fill("Sapphire Preferred")
    page.wait_for_timeout(300)
    page.get_by_role("dialog").get_by_role("button", name="Chase Sapphire Preferred").first.click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="Add to wallet").click()
    page.wait_for_timeout(120)  # well before the server round-trip settles the list
    check(f"optimistic add shows row immediately ({rows.count()})", rows.count() == 6)
    page.wait_for_timeout(1500)
    check(
        f"after server confirm gauge updates to 5 (got {gauge.inner_text()!r})",
        gauge.inner_text().startswith("5"),
    )

    # rollback on failure
    page.route(
        WALLET_CARDS,
        lambda route: (
            route.fulfill(status=500, body='{"detail":"boom"}')
            if route.request.method == "POST"
            else route.continue_()
        ),
    )
    page.get_by_role("button", name="Add card").click()
    page.wait_for_timeout(500)
    page.get_by_label("Search cards").last.fill("Venture")
    page.wait_for_timeout(300)
    page.get_by_role("dialog").get_by_role(
        "button", name="Capital One Venture", exact=False
    ).first.click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="Add to wallet").click()
    page.wait_for_timeout(150)
    mid = rows.count()
    page.wait_for_timeout(1500)
    after = rows.count()
    check(
        f"failed add appears optimistically then rolls back ({mid} -> {after})",
        mid == 7 and after == 6,
    )
    check("rollback shows a toast", page.get_by_role("status").filter(has_text="boom").is_visible())
    page.unroute(WALLET_CARDS)

    # remove
    page.get_by_role("button", name="Remove Chase Sapphire Preferred").click()
    page.wait_for_timeout(1500)
    check(
        f"remove -> 5 cards, gauge 4 ({rows.count()}, {gauge.inner_text()!r})",
        rows.count() == 5 and gauge.inner_text().startswith("4"),
    )

    # sheet drag-to-dismiss (pointer drag on the grabber)
    page.goto(BASE + "/cards/", wait_until="networkidle")
    page.wait_for_timeout(400)
    page.get_by_label("Open Chase Sapphire Preferred").click()
    page.wait_for_timeout(800)
    dialog = page.get_by_role("dialog")
    check("sheet opens", dialog.is_visible())
    check("page behind the sheet is inert", page.locator("main").get_attribute("inert") is not None)
    grab = dialog.locator("span.h-\\[5px\\]").bounding_box()
    x, y = grab["x"] + grab["width"] / 2, grab["y"] + 2
    page.mouse.move(x, y)
    page.mouse.down()
    for i in range(1, 11):
        page.mouse.move(x, y + i * 30)
        page.wait_for_timeout(16)
    page.mouse.up()
    page.wait_for_timeout(900)
    check("dragging the sheet down dismisses it", page.get_by_role("dialog").count() == 0)

    # small drag springs back
    page.get_by_label("Open Chase Sapphire Preferred").click()
    page.wait_for_timeout(800)
    grab = page.get_by_role("dialog").locator("span.h-\\[5px\\]").bounding_box()
    x, y = grab["x"] + grab["width"] / 2, grab["y"] + 2
    page.mouse.move(x, y)
    page.mouse.down()
    for i in range(1, 4):
        page.mouse.move(x, y + i * 12)
        page.wait_for_timeout(60)
    page.wait_for_timeout(200)
    page.mouse.up()
    page.wait_for_timeout(900)
    check("a short slow drag springs back instead", page.get_by_role("dialog").count() == 1)
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    check("Escape closes the sheet", page.get_by_role("dialog").count() == 0)

    # compare tray
    for name in ["Chase Sapphire Preferred", "Capital One Venture X"]:
        page.locator(f"div:has(> button[aria-label='Open {name}'])").get_by_role(
            "button", name="Compare"
        ).click()
        page.wait_for_timeout(300)
    check("compare tray shows 2 of 3", page.get_by_text("2 of 3").is_visible())

    # hero deck fling
    page.goto(BASE + "/", wait_until="networkidle")
    page.wait_for_timeout(500)
    before = page.get_by_role("tab", selected=True).get_attribute("aria-label")
    box = page.get_by_role("region", name="Featured cards").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx, cy)
    page.mouse.down()
    for i in range(1, 8):
        page.mouse.move(cx - i * 40, cy)
        page.wait_for_timeout(10)
    page.mouse.up()
    page.wait_for_timeout(900)
    after = page.get_by_role("tab", selected=True).get_attribute("aria-label")
    check(f"flinging the deck moves the selection ({before} -> {after})", before != after)
    check("no uncaught page errors", not errors)
    b.close()
print("\n".join(results))
if errors:
    print("page errors:", errors[:3])
sys.exit(0 if all(r.startswith("PASS") for r in results) else 1)
