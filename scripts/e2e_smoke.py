"""Browser smoke test of the local demo: invite sign-up, optimistic wallet add/remove, rollback
when the API fails, sheet drag-to-dismiss vs. spring-back, modal inertness, compare, deck fling,
and the Advisor chat against a scripted agent (link sanitizing, quota, persistence).

Needs the demo running (`make demo`), then: `make e2e`. Uses Playwright's Chromium ($0).
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

# Matches with or without a query string (the site pins ?catalog_version=...).
WALLET_CARDS = re.compile(r".*/me/wallet/cards(\?.*)?$")

BASE = os.environ.get("E2E_BASE", "http://localhost:3000")
API = os.environ.get("E2E_API", "http://localhost:8000")
ADVISOR = "http://localhost:8080/invocations"  # `make agent`; scripted here, never called
DEV_USER_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Dev-User"
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
    # The failing POST is held until the optimistic row has been counted, then answered, so the
    # check doesn't depend on how fast the build reacts.
    held = []
    page.route(
        WALLET_CARDS,
        lambda route: held.append(route) if route.request.method == "POST" else route.continue_(),
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
    page.wait_for_timeout(300)
    mid = rows.count()
    for route in held:
        route.fulfill(status=500, body='{"detail":"boom"}')
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

    # search: a bank by either name, a card by its alias, a typo, and a card we don't list
    page.goto(BASE + "/cards/", wait_until="networkidle")
    box = page.get_by_label("Search cards")
    # Card tiles only: in `next dev` the dev-tools button is also labelled "Open ...".
    tiles = page.locator("main button[aria-label^='Open ']")

    def search(q):
        box.fill(q)
        # Tiles leaving the grid animate out; wait until the grid holds just the results.
        for _ in range(40):
            page.wait_for_timeout(100)
            said = re.search(
                r"(\d+) cards?", page.locator("p[aria-live=polite]").first.inner_text()
            )
            if said and tiles.count() == int(said.group(1)):
                break
        return [tiles.nth(i).get_attribute("aria-label")[5:] for i in range(tiles.count())]

    amex, american_express = search("Amex"), search("American Express")
    check(
        f"'Amex' and 'American Express' both find the Amex cards ({len(amex)})",
        len(amex) == 10 and sorted(amex) == sorted(american_express),
    )
    check("an alias finds its card ('CSP')", search("CSP")[:1] == ["Chase Sapphire Preferred"])
    check("a typo still finds the card ('saphire')", "Chase Sapphire Reserve" in search("saphire"))
    check(
        "'amex gold' puts the Gold first",
        search("amex gold")[:1] == ["American Express Gold Card"],
    )
    search("Bilt")
    check("a card we don't list finds nothing", page.get_by_text("No cards match").is_visible())
    box.fill("")

    # referral facts are stated, never linked (ADR 0004)
    page.goto(BASE + "/cards/discover_it_student_cash_back/", wait_until="networkidle")
    tip = page.get_by_text("we don't provide referral links").first
    check(
        "a card page states what a referral adds, without any referral link",
        tip.is_visible() and page.get_by_text("$100 statement credit").first.is_visible(),
    )
    page.goto(BASE + "/cards/", wait_until="networkidle")

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

    # Spending Profile (ADR 0009): amounts save on blur and survive a reload
    page.goto(BASE + "/profile/", wait_until="networkidle")
    page.wait_for_timeout(800)
    page.get_by_label("Dining per month").fill("450")
    page.get_by_label("Dining per month").press("Enter")
    cash_back = page.get_by_role("button", name="Cash back")
    if cash_back.get_attribute("aria-pressed") != "true":  # a re-run on the same demo API
        cash_back.click()
    page.wait_for_timeout(800)
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1000)
    kept = page.get_by_label("Dining per month").input_value()
    goal = page.get_by_role("button", name="Cash back").get_attribute("aria-pressed")
    check(
        f"spending profile persists (dining {kept!r}, goal {goal})",
        kept == "450" and goal == "true",
    )

    # Editing a held card's open date (typed MM/DD/YYYY), then putting it back so a re-run on
    # the same demo API sees the same wallet.
    page.goto(BASE + "/wallet/", wait_until="networkidle")
    page.wait_for_timeout(1200)
    # by name: the list re-sorts by open date once the date changes
    row = page.get_by_role(
        "button",
        name=page.get_by_role("button", name=re.compile("^Edit ")).first.get_attribute(
            "aria-label"
        ),
        exact=True,
    )
    row.click()
    page.wait_for_timeout(600)
    dialog = page.get_by_role("dialog")
    opened = dialog.get_by_label("Opened", exact=True)
    original = opened.input_value()
    opened.fill("")
    opened.press_sequentially("1/15/2024")  # "1/" pads to "01/"
    check(
        f"typed dates are masked as MM/DD/YYYY ({opened.input_value()!r})",
        opened.input_value() == "01/15/2024",
    )
    dialog.get_by_role("button", name="Save").click()
    page.wait_for_timeout(1500)
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1200)
    check(
        "an edited open date is saved (PATCH passes CORS) and survives a reload",
        "opened Jan 15, 2024" in row.inner_text(),
    )
    row.click()
    page.wait_for_timeout(600)
    opened = page.get_by_role("dialog").get_by_label("Opened", exact=True)
    opened.fill("")
    opened.press_sequentially("02/30/2024")
    opened.press("Tab")
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    page.wait_for_timeout(400)
    check(
        "an impossible date blocks Save with a message",
        page.get_by_role("dialog").get_by_text("Enter a real date").is_visible(),
    )
    # restore through the calendar: month-and-year view, then the day
    month, day, year = (int(x) for x in original.split("/"))
    opened.click()
    page.wait_for_timeout(400)
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="Choose month and year").click()
    shown = int(dialog.get_by_role("button", name="Back to days").inner_text())
    for _ in range(shown - year):
        dialog.get_by_role("button", name="Previous year").click()
    for _ in range(year - shown):
        dialog.get_by_role("button", name="Next year").click()
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    dialog.get_by_role("button", name=months[month - 1], exact=True).click()
    full = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ][month - 1]
    dialog.get_by_role("button", name=f"{full} {day}, {year}", exact=True).click()
    check(
        f"the calendar fills the field ({opened.input_value()!r})", opened.input_value() == original
    )
    dialog.get_by_role("button", name="Save").click()
    page.wait_for_timeout(1200)

    # Advisor chat (ADR 0009), against a scripted agent: no model is called, so CI can run it.
    replies = []

    def fake_agent(route):
        cors = {"Access-Control-Allow-Origin": BASE, "Access-Control-Allow-Headers": "*"}
        if route.request.method == "OPTIONS":
            return route.fulfill(status=204, headers=cors)
        events = replies.pop(0)
        body = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
        route.fulfill(status=200, headers=cors, content_type="text/event-stream", body=body)

    page.route(ADVISOR, fake_agent)
    # The real agent saves each answer through the API; do the same so it can be rated.
    turn_id = f"{int(time.time() * 1000)}-e2e00001"
    saved = urllib.request.Request(
        API + "/me/chat/turns",
        data=json.dumps(
            {
                "turn_id": turn_id,
                "question": "Which card for dining?",
                "answer": "Chase Sapphire Preferred fits best.",
                "model_id": "scripted",
                "prompt_version": "e2e",
            }
        ).encode(),
        headers={"Content-Type": "application/json", "X-Dev-User": "demo-user"},
        method="POST",
    )
    urllib.request.urlopen(saved, timeout=10)
    replies.append(
        [
            {"type": "quota", "limit": 30, "remaining": 27, "resets_at": "2026-09-30T04:00:00Z"},
            {"type": "text", "text": 'Checking. {"name": "rank_cards", "arguments": {}}'},
            {"type": "reset"},
            {"type": "tool", "name": "rank_cards"},
            {"type": "text", "text": "**Chase Sapphire Preferred** fits best. "},
            {"type": "text", "text": "[Apply](card:chase_sapphire_preferred)\n\n"},
            {
                "type": "text",
                "text": "Also see [this](https://evil.example/x) or https://evil.example/y. "
                "[Amex Green](card:amex_green) is closed to new applicants. "
                "Per [Chase 5/24](rule:chase_5_24) you can apply.",
            },
            {"type": "done", "turn_id": turn_id},
        ]
    )
    page.goto(BASE + "/advisor/", wait_until="networkidle")
    page.wait_for_timeout(600)
    check(
        "advisor shows today's quota",
        page.get_by_text(re.compile(r"of 30 left today")).is_visible(),
    )
    page.get_by_label("Message the Advisor").fill("Which card for dining?")
    page.get_by_label("Message the Advisor").press("Enter")
    page.wait_for_timeout(800)
    log = page.get_by_role("log")
    hrefs = [a.get_attribute("href") or "" for a in log.locator("a:not([data-rule])").all()]
    official = [h for h in hrefs if h.startswith("https://")]
    check(
        f"card: links become the official page, nothing else links out ({hrefs})",
        bool(official)
        and all("chase.com" in h for h in official)
        and not any("evil" in h for h in hrefs),
    )
    check("bare URLs are removed from the reply", "evil.example" not in log.inner_text())
    source = log.locator("a[data-rule='chase_5_24']")
    check(
        "a cited rule (rule:ID) shows as its source, with the rule on hover",
        source.count() == 1
        and source.get_attribute("href").startswith("https://")
        and "5/24" in (source.get_attribute("title") or ""),
    )
    check(
        "a reset clears the discarded text (a leaked tool call never stays on screen)",
        '"arguments"' not in log.inner_text() and "Checking." not in log.inner_text(),
    )
    check(
        "the recommended card gets a row linking to its page",
        log.get_by_role("link", name="Chase Sapphire Preferred").get_attribute("href")
        == "/cards/chase_sapphire_preferred/",
    )
    green = log.locator("li", has_text="American Express Green Card")
    check(
        "a card closed to applicants gets no Apply button, and its link stays on our site",
        green.get_by_text("No longer offered").is_visible()
        and green.get_by_role("link", name="Apply").count() == 0
        and log.get_by_role("link", name="Amex Green").get_attribute("href")
        == "/cards/amex_green/",
    )
    check("quota updates from the stream", page.get_by_text("27 of 30 left today").is_visible())

    check(
        "an answer offers 👍 / 👎 and says what rating shares",
        log.get_by_role("button", name="Helpful", exact=True).is_visible()
        and log.get_by_text("Rating shares this exchange").is_visible(),
    )
    log.get_by_role("button", name="Not helpful").click()
    send = log.get_by_role("button", name="Send feedback")
    check("👎 asks what went wrong before sending", send.is_disabled())
    log.get_by_role("button", name="Wrong information").click()
    log.get_by_placeholder("Anything else? (optional)").fill("The fee looks off")
    with page.expect_response(
        lambda r: "/feedback" in r.url and r.request.method == "PUT"
    ) as rated:
        send.click()
    page.wait_for_timeout(300)
    check(
        f"the rating reaches the API ({rated.value.status}) and the answer says thanks",
        rated.value.status == 204 and log.get_by_text("look into it").is_visible(),
    )

    page.reload(wait_until="networkidle")
    page.wait_for_timeout(600)
    check(
        "the conversation survives a reload",
        page.get_by_text("Which card for dining?").is_visible(),
    )
    replies.append(
        [{"type": "error", "code": "quota", "message": "You've used today's 30 Advisor messages."}]
    )
    page.get_by_label("Message the Advisor").fill("One more?")
    page.get_by_label("Message the Advisor").press("Enter")
    page.wait_for_timeout(600)
    check(
        "a quota error is shown in the chat",
        page.get_by_role("alert").filter(has_text="today's 30 Advisor messages").is_visible(),
    )

    page.goto(BASE + "/cards/", wait_until="networkidle")
    page.get_by_role("button", name="Ask the Advisor").click()
    page.wait_for_timeout(600)
    panel = page.get_by_role("dialog")
    check(
        "the floating panel shows the same conversation",
        panel.get_by_text("Which card for dining?").is_visible(),
    )
    panel.get_by_role("button", name="New conversation").click()
    page.wait_for_timeout(300)
    check(
        "New conversation clears it",
        panel.get_by_text("Which card for dining?").count() == 0
        and panel.get_by_role("button", name=re.compile("fits my spending")).is_visible(),
    )
    page.keyboard.press("Escape")
    page.unroute(ADVISOR)

    # The guest trial (ADR 0009, temporary): a visitor who isn't signed in can chat; the first
    # message starts a guest (POST /guest), and the trial ends with a way to sign in.
    guest_ctx = b.new_context(viewport={"width": 1280, "height": 900})
    guest_page = guest_ctx.new_page()
    guest_page.on("pageerror", lambda e: errors.append(str(e)))
    callers = []

    def fake_guest_agent(route):
        cors = {"Access-Control-Allow-Origin": BASE, "Access-Control-Allow-Headers": "*"}
        if route.request.method == "OPTIONS":
            return route.fulfill(status=204, headers=cors)
        callers.append(route.request.headers.get(DEV_USER_HEADER.lower(), ""))
        events = replies.pop(0)
        body = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
        route.fulfill(status=200, headers=cors, content_type="text/event-stream", body=body)

    guest_page.route(ADVISOR, fake_guest_agent)
    guest_page.goto(BASE + "/advisor/", wait_until="networkidle")
    guest_page.wait_for_timeout(600)
    check(
        "signed out, the Advisor offers a free trial",
        guest_page.get_by_text("Try it free: 10 messages").is_visible(),
    )
    replies.append(
        [
            {"type": "quota", "limit": 10, "remaining": 9, "resets_at": None, "guest": True},
            {"type": "tool", "name": "rank_cards"},
            {"type": "text", "text": "**Chase Sapphire Preferred** fits best."},
            {"type": "done"},
        ]
    )
    guest_page.get_by_label("Message the Advisor").fill("Which card for dining?")
    guest_page.get_by_label("Message the Advisor").press("Enter")
    guest_page.wait_for_timeout(800)
    check(
        f"the first message starts a guest and sends as it ({callers})",
        len(callers) == 1 and callers[0].startswith("guest-"),
    )
    check(
        "a guest sees free messages left", guest_page.get_by_text("9 of 10 free left").is_visible()
    )
    replies.append(
        [
            {
                "type": "error",
                "code": "quota",
                "message": "You've used the 10 free messages. Sign in to keep using the Advisor.",
                "guest": True,
            }
        ]
    )
    guest_page.get_by_label("Message the Advisor").fill("One more?")
    guest_page.get_by_label("Message the Advisor").press("Enter")
    guest_page.wait_for_timeout(600)
    alert = guest_page.get_by_role("alert").filter(has_text="10 free messages")
    check(
        "a used-up trial offers sign-in",
        alert.is_visible() and alert.get_by_role("link", name="Sign in").is_visible(),
    )
    guest_ctx.close()

    check("no uncaught page errors", not errors)
    b.close()
print("\n".join(results))
if errors:
    print("page errors:", errors[:3])
sys.exit(0 if all(r.startswith("PASS") for r in results) else 1)
