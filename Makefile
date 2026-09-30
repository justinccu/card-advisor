-include .env
export

.PHONY: install test lint lambda-bundle synth deploy-infra aws-smoke web-aws e2e-aws invite invites preview api web demo e2e web-build agent agent-deploy

install:
	uv sync --all-packages
	uv run pre-commit install
	cd web && npm install

test:
	uv run pytest

lint:
	uv run pre-commit run --all-files

synth: lambda-bundle
	cd infra && cdk synth --quiet

# Linux arm64 Lambda package for the API and Cognito triggers (no Docker needed)
lambda-bundle:
	./scripts/bundle_lambda.sh

deploy-infra: lambda-bundle
	cd infra && cdk deploy --all --require-approval broadening

# Live end-to-end check of the deployed stack with a throwaway user (~$0; cleans up after itself)
aws-smoke:
	uv run scripts/aws_smoke.py

# --- Local demo ($0: no AWS calls) -----------------------------------------------------------

# Unreviewed catalog for demos while human review is pending (ADR 0002)
preview:
	uv run scout preview

api:
	APP_ENV=local uv run uvicorn card_api.app:app --reload --port 8000

web:
	cd web && npm run dev

# API + site together; Ctrl-C stops both. Open http://localhost:3000 (invite code DEMO-2026)
# NEXT_PUBLIC_CARD_ART=1 enables the footer's Simulated/Real card-face toggle; the Real faces are the
# local, gitignored images in web/public/card-art (never pushed or deployed).
demo:
	@test -d web/node_modules || (cd web && npm install)
	@echo "API  http://localhost:8000/docs\nSite http://localhost:3000   (invite: DEMO-2026, or 'Use demo account')"
	@trap 'kill 0' INT TERM EXIT; \
	APP_ENV=local uv run uvicorn card_api.app:app --port 8000 & \
	(cd web && NEXT_PUBLIC_CARD_ART=1 npm run dev -- --port 3000) & \
	wait

# The Advisor agent on :8080 for `make demo`'s chat (run it in a second terminal). It calls the
# Bedrock model in AWS_PROFILE's account (Nova 2 Lite: a fraction of a cent per message) and the
# local API as the demo's signed-in user; nothing is deployed (--skip-deploy).
agent:
	cd agent && agentcore dev --skip-deploy --logs

# Deploy the Advisor runtime + memory to AWS (billable per use, ADR 0009). Then set the printed
# Memory id as advisor_memory_id in infra/cdk.json so account deletion can purge it.
agent-deploy:
	cd agent && agentcore deploy

# Invite codes on the deployed stack: `make invite` (N=1 USES=1 by default) and `make invites`
N ?= 1
USES ?= 1
invite:
	uv run python scripts/invites.py create -n $(N) --uses $(USES)

invites:
	uv run python scripts/invites.py list

# The site on :3000 against the deployed API and Cognito (real sign-up with an invite code)
web-aws:
	@test -d web/node_modules || (cd web && npm install)
	@env_lines="$$(./scripts/web_aws_env.sh)" && eval "$$env_lines" && \
	echo "Site http://localhost:3000 -> $$NEXT_PUBLIC_API_URL (Cognito $$NEXT_PUBLIC_COGNITO_USER_POOL_ID)" && \
	cd web && npm run dev -- --port 3000

e2e:
	uv run python scripts/e2e_smoke.py

# Browser e2e in Cognito mode against the deployed stack (needs `make web-aws` running; ~$0)
e2e-aws:
	uv run python scripts/e2e_aws.py

web-build:
	cd web && npm run build
