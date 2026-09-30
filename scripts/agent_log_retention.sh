#!/usr/bin/env bash
# Keep the Advisor's CloudWatch logs and traces for 7 days, matching AgentCore Memory's
# retention (ADR 0009). AgentCore creates these log groups itself, outside our CDK and the
# agentcore CLI's stack, so `make agent-deploy` runs this after every deploy. Idempotent.
set -euo pipefail
region=us-east-2
days=7
runtime_id=$(python3 -c 'import json
s = json.load(open("agent/agentcore/.cli/deployed-state.json"))
print(s["targets"]["default"]["resources"]["runtimes"]["Advisor"]["runtimeId"])')
for group in "/aws/bedrock-agentcore/runtimes/${runtime_id}-DEFAULT" "aws/spans"; do
  # The runtime's group appears on its first invocation; create it so the policy applies now.
  aws logs create-log-group --region "$region" --log-group-name "$group" 2>/dev/null || true
  aws logs put-retention-policy --region "$region" --log-group-name "$group" \
    --retention-in-days "$days"
  echo "$group: kept $days days"
done
