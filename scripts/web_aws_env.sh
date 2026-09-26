#!/usr/bin/env bash
# Print the env that points the site at the deployed stack (API + Cognito), read from the SSM
# parameters the api stack writes. Used by `make web-aws`: eval "$(scripts/web_aws_env.sh)".
set -euo pipefail
region=us-east-2
get() { aws ssm get-parameter --region "$region" --name "/card-advisor/$1" --query Parameter.Value --output text; }
echo "export NEXT_PUBLIC_API_URL=$(get api-url)"
echo "export NEXT_PUBLIC_COGNITO_USER_POOL_ID=$(get user-pool-id)"
echo "export NEXT_PUBLIC_COGNITO_CLIENT_ID=$(get web-client-id)"
