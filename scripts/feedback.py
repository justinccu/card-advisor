"""Review rated Advisor answers on the deployed stack, as the AWS account owner (ADR 0009).

    make feedback          # every rated answer, 👎 first, newest first
    make feedback DOWN=1   # only 👎

For each one: the question, the answer the user saw, and every tool the Advisor called with
what it returned. That is what tells a data mistake (the tool result is wrong) from a model
mistake (the tool result is right, the answer isn't); the second kind becomes a golden-set case.
Users are shown by a short hash of their id, not their email: reviewing answers needs no names.
"""

import argparse
import hashlib
import sys

import boto3
from botocore.exceptions import LoginRefreshRequired, NoCredentialsError
from card_api.repository import DynamoRepository

PROJECT, REGION = "card-advisor", "us-east-2"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--down", action="store_true", help="only answers rated 👎")
    parser.add_argument("--tools", type=int, default=600, help="characters of each tool result")
    args = parser.parse_args()
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        table = ssm.get_parameter(Name=f"/{PROJECT}/table-name")["Parameter"]["Value"]
        repo = DynamoRepository(table, resource=boto3.resource("dynamodb", region_name=REGION))
        rated = repo.rated_turns()
    except (LoginRefreshRequired, NoCredentialsError):
        sys.exit("AWS session expired or missing: run `aws login --profile chenhan9`, then retry.")

    rated = [r for r in rated if not args.down or r[1].feedback.rating == "down"]
    rated.sort(key=lambda r: r[1].created_at, reverse=True)  # newest first...
    rated.sort(key=lambda r: r[1].feedback.rating != "down")  # ...with 👎 before 👍 (stable)
    ups = sum(1 for _, t in rated if t.feedback.rating == "up")
    print(f"{len(rated)} rated answers: {len(rated) - ups} 👎, {ups} 👍\n")
    for uid, turn in rated:
        fb = turn.feedback
        who = hashlib.sha256(uid.encode()).hexdigest()[:8]
        print("=" * 100)
        print(
            f"{'👎' if fb.rating == 'down' else '👍'} {fb.reason or ''}  {turn.created_at}  "
            f"user {who}  model {turn.model_id}  prompt {turn.prompt_version}  "
            f"catalog {turn.catalog_version or '-'}"
        )
        if fb.comment:
            print(f"comment: {fb.comment}")
        print(f"\nQ: {turn.question}\n\nA: {turn.answer}\n")
        for call in turn.tools:
            print(f"  tool {call.name}({call.input})")
            print(f"    -> {call.result[: args.tools]}")
        print()


if __name__ == "__main__":
    main()
