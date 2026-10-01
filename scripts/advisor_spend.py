"""The Advisor's running cost on the deployed stack, and whether the guest trial is open
(ADR 0009), as the AWS account owner: `make advisor-spend`.

The total is what the agent reports per message (tokens at list price plus Runtime and Memory),
counted since the guest trial was deployed. It is an estimate for closing the trial, not the
bill: AWS Billing remains the record.
"""

import sys
from datetime import datetime

import boto3
from botocore.exceptions import LoginRefreshRequired, NoCredentialsError
from card_api.app import CHAT_TIMEZONE
from card_api.repository import DynamoRepository
from card_api.settings import settings

PROJECT, REGION = "card-advisor", "us-east-2"


def main() -> None:
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        table = ssm.get_parameter(Name=f"/{PROJECT}/table-name")["Parameter"]["Value"]
        repo = DynamoRepository(table, resource=boto3.resource("dynamodb", region_name=REGION))
        total = repo.spend()
        today = datetime.now(CHAT_TIMEZONE).date().isoformat()
        guest_today = repo.guest_messages(today)
    except (LoginRefreshRequired, NoCredentialsError):
        sys.exit("AWS session expired or missing: run `aws login --profile chenhan9`, then retry.")
    budget = settings.guest_budget_usd
    state = "open" if total < budget else "closed (guests are asked to sign in)"
    print(f"Advisor spend: ${total:.2f} of ${budget:.0f}; guest trial {state}")
    print(f"Guest messages today (US Eastern): {guest_today} of {settings.guest_daily_limit}")


if __name__ == "__main__":
    main()
