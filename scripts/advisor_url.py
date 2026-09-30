"""Print the deployed Advisor runtime's invocation URL (empty when none is deployed), read from
the agentcore CLI's committed state. Used by `make web-aws` and by CI when building the site."""

import json
import sys
from pathlib import Path
from urllib.parse import quote

REGION = "us-east-2"
STATE = Path(__file__).parents[1] / "agent" / "agentcore" / ".cli" / "deployed-state.json"


def advisor_url() -> str:
    try:
        state = json.loads(STATE.read_text())
        arn = state["targets"]["default"]["resources"]["runtimes"]["Advisor"]["runtimeArn"]
    except (OSError, KeyError, ValueError):
        return ""
    return (
        f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{quote(arn, safe='')}"
        "/invocations?qualifier=DEFAULT"
    )


if __name__ == "__main__":
    sys.stdout.write(advisor_url())
