-include .env
export

.PHONY: install test lint synth deploy-infra

install:
	uv sync --all-packages
	uv run pre-commit install

test:
	uv run pytest

lint:
	uv run pre-commit run --all-files

synth:
	cd infra && cdk synth --quiet

deploy-infra:
	cd infra && cdk deploy --all --require-approval broadening
