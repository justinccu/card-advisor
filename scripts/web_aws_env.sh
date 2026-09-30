#!/usr/bin/env bash
# Print the env that points the site at the deployed stack (API + Cognito), read from the SSM
# parameters the api stack writes, and at the deployed Advisor runtime (from the agentcore CLI's
# state) once there is one. Used by `make web-aws`: eval "$(scripts/web_aws_env.sh)".
set -euo pipefail
region=us-east-2
get() { aws ssm get-parameter --region "$region" --name "/card-advisor/$1" --query Parameter.Value --output text; }
echo "export NEXT_PUBLIC_API_URL=$(get api-url)"
echo "export NEXT_PUBLIC_COGNITO_USER_POOL_ID=$(get user-pool-id)"
echo "export NEXT_PUBLIC_COGNITO_CLIENT_ID=$(get web-client-id)"
arn=$(python3 -c 'import json,sys
s = json.load(open(sys.argv[1]))
rt = s.get("targets", {}).get("default", {}).get("resources", {}).get("runtimes", {})
print(rt.get("Advisor", {}).get("runtimeArn", ""))' agent/agentcore/.cli/deployed-state.json 2>/dev/null || true)
if [ -n "$arn" ]; then
  encoded=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$arn")
  echo "export NEXT_PUBLIC_ADVISOR_URL=https://bedrock-agentcore.$region.amazonaws.com/runtimes/$encoded/invocations?qualifier=DEFAULT"
fi
