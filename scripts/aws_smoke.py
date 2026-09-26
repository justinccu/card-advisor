# /// script
# requires-python = ">=3.12"
# dependencies = ["boto3[crt]", "pycognito"]  # crt: reads `aws login` credentials
# ///
"""Live check of the deployed S4 stack (run after `make deploy-infra`; ~$0).

Invite-gated sign-up -> email confirmation -> SRP sign-in (like the site) -> API calls with the
JWT -> admin listing -> account deletion. Uses a throwaway catest@example.com user (example.com
accepts no mail) and a one-off invite code, and removes both, pass or fail.

    AWS_PROFILE=... uv run scripts/aws_smoke.py
"""

import json
import secrets
import sys
import time
import urllib.error
import urllib.request

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import LoginRefreshRequired, NoCredentialsError
from pycognito import Cognito

PROJECT, REGION = "card-advisor", "us-east-2"
ssm = boto3.client("ssm", region_name=REGION)


def param(name: str) -> str:
    try:
        return ssm.get_parameter(Name=f"/{PROJECT}/{name}")["Parameter"]["Value"]
    except (LoginRefreshRequired, NoCredentialsError):
        sys.exit("AWS session expired or missing: run `aws login --profile chenhan9`, then retry.")


POOL, CLIENT, API, TABLE = (
    param(n) for n in ("user-pool-id", "web-client-id", "api-url", "table-name")
)
EMAIL, PASSWORD = "catest@example.com", "Test-" + secrets.token_urlsafe(12) + "9aA"
idp = boto3.client("cognito-idp", region_name=REGION)
table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
code = "CA" + "".join(secrets.choice("0123456789ABCDEFGHJKMNPQRSTVWXYZ") for _ in range(12))
failures = []


def ok(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def call(method, path, token=None, body=None):
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            headers = {k.lower(): v for k, v in r.headers.items()}
            return r.status, headers, json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode()[:200]


def signup(invite):
    try:
        idp.sign_up(
            ClientId=CLIENT,
            Username=EMAIL,
            Password=PASSWORD,
            UserAttributes=[{"Name": "email", "Value": EMAIL}],
            ClientMetadata={"invite_code": invite},
        )
        return "ok"
    except idp.exceptions.UserLambdaValidationException as e:
        return "rejected: " + str(e).split(":")[-1].strip()


latest = call("GET", "/health")[2]["catalog_version"]
print(f"API {API} serving catalog v{latest}")
table.put_item(Item={"PK": "INVITE", "SK": f"CODE#{code}", "remaining": 1})
sub = None
try:
    ok(
        "wrong invite code is rejected by the pre sign-up trigger",
        signup("CA-WRONG-CODE-0000").startswith("rejected"),
    )
    ok(
        "no account left behind by the rejected sign-up",
        not idp.list_users(UserPoolId=POOL, Filter=f'email = "{EMAIL}"')["Users"],
    )
    shown = f"ca-{code[2:6]}-{code[6:10]}-{code[10:]}".lower()  # typed messily
    ok("valid invite (typed lowercase with dashes) signs up", signup(shown) == "ok")
    user = idp.admin_get_user(UserPoolId=POOL, Username=EMAIL)
    sub = next(a["Value"] for a in user["UserAttributes"] if a["Name"] == "sub")
    ok("Cognito username equals sub", user["Username"] == sub)
    inv = table.get_item(Key={"PK": "INVITE", "SK": f"CODE#{code}"})["Item"]
    use = table.get_item(Key={"PK": "INVITE", "SK": f"CODE#{code}#USE#{sub}"}).get("Item")
    ok(
        "one use taken and recorded against the user",
        inv["remaining"] == 0 and use and "confirmed_at" not in use,
    )

    idp.admin_confirm_sign_up(UserPoolId=POOL, Username=EMAIL)
    time.sleep(1)
    use = table.get_item(Key={"PK": "INVITE", "SK": f"CODE#{code}#USE#{sub}"})["Item"]
    ok("post confirmation trigger stamped confirmed_at", "confirmed_at" in use)

    u = Cognito(POOL, CLIENT, username=EMAIL)
    u.authenticate(password=PASSWORD)  # SRP, like the site
    token = u.access_token
    s, h, b = call("GET", "/me/wallet", token)
    ok(f"JWT reaches the app: GET /me/wallet -> {s}", s == 200 and b["cards"] == [])
    s, h, b = call(
        "POST",
        f"/me/wallet/cards?catalog_version={latest}",
        token,
        {"card_product_id": "chase_sapphire_preferred", "opened_on": "2025-06-01"},
    )
    ok(f"add a card -> {s}", s == 201)
    s, h, b = call("GET", "/me/eligibility?card_id=chase_sapphire_reserve", token)
    tagged = b.get("catalog_version") if isinstance(b, dict) else None
    ok(
        f"eligibility tagged with the catalog version -> {s} {tagged}",
        s == 200 and tagged == latest and h.get("x-catalog-version") == latest,
    )
    s, _, _ = call("POST", "/admin/invites", token, {"count": 1})
    ok(f"non-admin cannot mint invites -> {s}", s == 403)
    s, _, _ = call("POST", "/dev/signup", token, {"invite_code": "DEMO-2026"})
    ok(f"local dev sign-up is off on AWS -> {s}", s == 404)
    demo = table.get_item(Key={"PK": "INVITE", "SK": "CODE#DEMO2026"}).get("Item")
    ok("the public demo code does not exist in DynamoDB", demo is None)

    idp.admin_add_user_to_group(UserPoolId=POOL, Username=EMAIL, GroupName="admin")
    u.authenticate(password=PASSWORD)
    s, _, b = call("GET", "/admin/invites", u.access_token)
    mine = [i for i in b if i["code"].replace("-", "") == code] if s == 200 else []
    ok(
        f"admin lists invites with use + confirmation -> {s}",
        mine and mine[0]["uses"][0]["user"] == sub and mine[0]["uses"][0]["confirmed_at"],
    )

    s, _, _ = call("DELETE", "/me", u.access_token)
    left = table.query(KeyConditionExpression=Key("PK").eq(f"USER#{sub}"))["Items"]
    use = table.get_item(Key={"PK": "INVITE", "SK": f"CODE#{code}#USE#{sub}"}).get("Item")
    ok(
        f"DELETE /me purges wallet and invite-use record -> {s}",
        s == 204 and not left and use is None,
    )
finally:
    try:
        idp.admin_delete_user(UserPoolId=POOL, Username=EMAIL)
    except idp.exceptions.UserNotFoundException:
        pass
    table.delete_item(Key={"PK": "INVITE", "SK": f"CODE#{code}"})
    if sub:
        table.delete_item(Key={"PK": "INVITE", "SK": f"CODE#{code}#USE#{sub}"})
    print("cleanup done: test user and invite removed")
sys.exit(1 if failures else 0)
