# /// script
# requires-python = ">=3.12"
# dependencies = ["boto3[crt]", "playwright"]  # run via `make e2e-aws` (the project env)
# ///
"""Browser e2e of the site in Cognito mode against the deployed stack (~$0).

Needs `make web-aws` running. Signs up through the real sign-up form with a one-off invite,
signs in (SRP), adds a card that persists in DynamoDB, checks that an expired session signs the
user out, then deletes the account from the profile page. The throwaway user
(catest+<random>@example.com; example.com accepts no mail) and the invite are removed either way.

    AWS_PROFILE=... uv run scripts/e2e_aws.py
"""

import secrets
import sys
import urllib.error
import urllib.request

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import LoginRefreshRequired, NoCredentialsError
from playwright.sync_api import sync_playwright

BASE, PROJECT, REGION = "http://localhost:3000", "card-advisor", "us-east-2"
ssm = boto3.client("ssm", region_name=REGION)


def param(name: str) -> str:
    try:
        return ssm.get_parameter(Name=f"/{PROJECT}/{name}")["Parameter"]["Value"]
    except (LoginRefreshRequired, NoCredentialsError):
        sys.exit("AWS session expired or missing: run `aws login --profile chenhan9`, then retry.")


def site_mode() -> str | None:
    """'cognito' or 'dev' for the site on :3000, or None if nothing is listening."""
    try:
        with urllib.request.urlopen(BASE + "/signin/", timeout=10) as r:
            html = r.read().decode()
    except (urllib.error.URLError, OSError):
        return None
    return "cognito" if "Welcome back." in html else "dev"


mode = site_mode()
if mode is None:
    sys.exit("Nothing on localhost:3000: start `make web-aws` in another terminal, then retry.")
if mode == "dev":
    sys.exit("localhost:3000 is the local demo (`make demo`); stop it and run `make web-aws`.")

POOL, TABLE = param("user-pool-id"), param("table-name")
idp = boto3.client("cognito-idp", region_name=REGION)
table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)

EMAIL = f"catest+{secrets.token_hex(4)}@example.com"
PASSWORD = "Test-" + secrets.token_urlsafe(12) + "9aA"
CODE = "CA" + "".join(secrets.choice("0123456789ABCDEFGHJKMNPQRSTVWXYZ") for _ in range(12))
results: list[str] = []


def check(name: str, cond: bool) -> None:
    results.append(("PASS" if cond else "FAIL") + "  " + name)


def cognito_user() -> dict | None:
    users = idp.list_users(UserPoolId=POOL, Filter=f'email = "{EMAIL}"')["Users"]
    return users[0] if users else None


def heading(page, text: str):
    return page.get_by_role("heading", name=text)


def fill_account(page, *, invite: str | None) -> None:
    page.get_by_label("Email").fill(EMAIL)
    page.get_by_label("Password").fill(PASSWORD)
    if invite is not None:
        page.get_by_label("Invite code").fill(invite)


table.put_item(Item={"PK": "INVITE", "SK": f"CODE#{CODE}", "remaining": 1})
sub = None
try:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("dialog", lambda d: d.accept())  # "Delete your account?" confirm

        page.goto(BASE + "/signin/", wait_until="networkidle")
        check("sign-in page is the Cognito one", heading(page, "Welcome back.").is_visible())

        # Sign-up: a wrong invite is refused by the pre sign-up trigger, and leaves no account.
        page.get_by_role("radio", name="Create account").click()
        fill_account(page, invite="CA-WRNG-CODE-0000")
        page.get_by_role("button", name="Create account").click()
        alert = page.locator("p[role=alert]")  # not Next's route announcer (also role=alert)
        alert.wait_for(timeout=15000)
        check("wrong invite -> friendly error", "invalid" in alert.inner_text())
        check("wrong invite -> no Cognito account", cognito_user() is None)

        # The real invite, typed the way people type (lowercase, dashes).
        page.get_by_label("Invite code").fill(f"ca-{CODE[2:6]}-{CODE[6:10]}-{CODE[10:]}".lower())
        page.get_by_role("button", name="Create account").click()
        heading(page, "Check your email.").wait_for(timeout=15000)
        user = cognito_user()
        sub = next(a["Value"] for a in user["Attributes"] if a["Name"] == "sub") if user else None
        check("valid invite -> account created, email step shown", sub is not None)

        # The emailed code can't be read here; confirm as an admin would, then sign in.
        idp.admin_confirm_sign_up(UserPoolId=POOL, Username=EMAIL)
        page.goto(BASE + "/signin/", wait_until="networkidle")
        fill_account(page, invite=None)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/wallet/", timeout=15000)
        page.get_by_text("No cards yet").wait_for(timeout=15000)
        check("sign-in (SRP) -> empty wallet from the real API", True)

        # Add a card through the UI; it must persist in DynamoDB.
        page.get_by_role("button", name="Add card").click()
        page.get_by_label("Search cards").last.fill("Sapphire Preferred")
        page.get_by_role("dialog").get_by_role(
            "button", name="Chase Sapphire Preferred"
        ).first.click()
        page.get_by_role("button", name="Add to wallet").click()
        page.wait_for_timeout(2500)
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(2000)
        rows = page.locator("ul li:has(p:text('opened'))").count()
        stored = table.query(
            KeyConditionExpression=Key("PK").eq(f"USER#{sub}") & Key("SK").begins_with("CARD#")
        )["Items"]
        check(
            f"added card survives a reload and is in DynamoDB ({rows} row, {len(stored)} item)",
            rows == 1 and len(stored) == 1,
        )

        # An expired/revoked session: the API answers 401 -> the site signs out.
        page.route("**/me/**", lambda r: r.fulfill(status=401, body='{"message":"Unauthorized"}'))
        page.goto(BASE + "/profile/", wait_until="networkidle")
        page.wait_for_url("**/signin/", timeout=15000)
        check("401 from the API signs the user out", heading(page, "Welcome back.").is_visible())
        page.unroute("**/me/**")

        # Sign in again and delete the account from the profile page.
        fill_account(page, invite=None)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/wallet/", timeout=15000)
        page.goto(BASE + "/profile/", wait_until="networkidle")
        page.get_by_role("button", name="Delete my account").click()
        page.wait_for_url(BASE + "/", timeout=15000)
        page.wait_for_timeout(1500)
        left = table.query(KeyConditionExpression=Key("PK").eq(f"USER#{sub}"))["Items"]
        check("delete account -> Cognito user gone", cognito_user() is None)
        check("delete account -> wallet and profile purged", not left)
        check("no uncaught page errors", not errors)
        browser.close()
finally:
    try:
        idp.admin_delete_user(UserPoolId=POOL, Username=EMAIL)
    except idp.exceptions.UserNotFoundException:
        pass
    table.delete_item(Key={"PK": "INVITE", "SK": f"CODE#{CODE}"})
    if sub:
        table.delete_item(Key={"PK": "INVITE", "SK": f"CODE#{CODE}#USE#{sub}"})
        for item in table.query(KeyConditionExpression=Key("PK").eq(f"USER#{sub}"))["Items"]:
            table.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

print("\n".join(results))
print("cleanup done: test user and invite removed")
sys.exit(0 if results and all(r.startswith("PASS") for r in results) else 1)
