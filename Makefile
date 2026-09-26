-include .env
export

.PHONY: install test lint synth deploy-infra preview api web demo e2e web-build

install:
	uv sync --all-packages
	uv run pre-commit install
	cd web && npm install

test:
	uv run pytest

lint:
	uv run pre-commit run --all-files

synth:
	cd infra && cdk synth --quiet

deploy-infra:
	cd infra && cdk deploy --all --require-approval broadening

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

e2e:
	uv run python scripts/e2e_smoke.py

web-build:
	cd web && npm run build
