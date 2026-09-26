"""Create and list invite codes on the deployed stack, as the AWS account owner.

    make invite            # one code, one use
    make invite N=3 USES=2 # three codes, two uses each
    make invites           # every code: uses left, who used it, confirmed or abandoned

Writes go straight to DynamoDB with your AWS credentials (the same records the API's
POST /admin/invites creates), so no signed-in admin session is needed.
"""

import argparse
import sys
from datetime import datetime

import boto3
from botocore.exceptions import LoginRefreshRequired, NoCredentialsError
from card_api import invites
from card_api.repository import DynamoRepository

PROJECT, REGION = "card-advisor", "us-east-2"


def _connect() -> tuple[DynamoRepository, str, object]:
    ssm = boto3.client("ssm", region_name=REGION)
    try:
        param = lambda n: ssm.get_parameter(Name=f"/{PROJECT}/{n}")["Parameter"]["Value"]  # noqa: E731
        table, pool = param("table-name"), param("user-pool-id")
    except (LoginRefreshRequired, NoCredentialsError):
        sys.exit("AWS session expired or missing: run `aws login --profile chenhan9`, then retry.")
    repo = DynamoRepository(table, resource=boto3.resource("dynamodb", region_name=REGION))
    return repo, pool, boto3.client("cognito-idp", region_name=REGION)


def _email(idp, pool: str, sub: str) -> str:
    users = idp.list_users(UserPoolId=pool, Filter=f'sub = "{sub}"', Limit=1)["Users"]
    if not users:
        return "(account deleted)"
    return next((a["Value"] for a in users[0]["Attributes"] if a["Name"] == "email"), sub)


def _when(ts: int | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""


def create(n: int, uses: int) -> None:
    repo, _, _ = _connect()
    codes = [invites.new_code() for _ in range(n)]
    for code in codes:
        repo.create_invite(code, uses)
    print(f"{n} invite code(s), {uses} use(s) each:")
    for code in codes:
        print(f"  {invites.display(code)}")
    print("Sign up at the site -> Create account (make web-aws locally).")


def show() -> None:
    repo, pool, idp = _connect()
    rows = repo.list_invites()
    if not rows:
        print("no invite codes yet (make invite)")
        return
    for inv in rows:
        print(f"{invites.display(inv.code)}  uses left: {inv.remaining}")
        for use in sorted(inv.uses, key=lambda u: u.taken_at):
            status = (
                f"confirmed {_when(use.confirmed_at)}"
                if use.confirmed_at
                else "NOT confirmed (sign-up abandoned?)"
            )
            print(f"    {_email(idp, pool, use.user):32} taken {_when(use.taken_at)}  {status}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="invites")
    sub = parser.add_subparsers(dest="cmd", required=True)
    new = sub.add_parser("create")
    new.add_argument("-n", type=int, default=1)
    new.add_argument("--uses", type=int, default=1)
    sub.add_parser("list")
    args = parser.parse_args()
    if args.cmd == "create":
        if not (1 <= args.n <= 50 and 1 <= args.uses <= 100):
            sys.exit("N must be 1-50 and USES 1-100")
        create(args.n, args.uses)
    else:
        show()


if __name__ == "__main__":
    main()
