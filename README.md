# card-advisor (working name)

A US credit card advisor: a static, non-LLM catalog for browsing and comparing cards, and an invite-only conversational agent on Amazon Bedrock AgentCore that recommends cards from a deterministic eligibility engine.

- Domain language: [CONTEXT.md](CONTEXT.md)
- Architecture decisions: [docs/adr/](docs/adr/)

## Layout

| Path | What |
|---|---|
| `packages/rules` | `card_rules`: deterministic Eligibility Verdicts + Catalog Snapshot model (ADR 0001) |
| `packages/scout` | Scout: fetch issuer pages → schema-constrained extraction → human review → versioned snapshot (ADR 0002, 0007) |
| `packages/api` | FastAPI wallet/profile/eligibility API; runs locally or on Lambda via Mangum |
| `web` | Next.js static site (catalog, compare, wallet), Apple-style motion |
| `infra` | AWS CDK (Python) |
| `catalog/seed` | Card list Scout reads; `catalog/us/vMAJOR.MINOR.json` (v1.1, v1.2, ...) are published snapshots |

## Local demo ($0, no AWS)

```bash
make install   # Python workspace, pre-commit hooks, web dependencies
make demo      # API on :8000 + site on :3000; Ctrl-C stops both
```

Open <http://localhost:3000>. Sign in with invite code `DEMO-2026`, or pick "Use demo account" for a
wallet that already holds five cards. The site and API read the newest published snapshot
(`catalog/us/vMAJOR.MINOR.json`); with none published they fall back to the local `scout preview` and show a
banner saying the data is unreviewed.

`make web-aws` runs the site against the deployed API and Cognito instead: real invite-only
sign-up (email code), SRP sign-in, and account deletion. `make e2e-aws` (with it running) drives
that flow in a browser with a throwaway user and removes it afterwards.

CI (GitHub Actions) runs on every push and pull request: pre-commit, pytest, `cdk synth`, the
site build, and the browser e2e against the local demo. On `main`, once all of those pass, it
deploys every stack with short-lived OIDC credentials (no stored AWS keys; the role only trusts
`main`) and smoke-tests the live API. It needs one repository secret, `ALERT_EMAIL`.

`make deploy-infra` deploys the stacks (data, auth, api); `make aws-smoke` then signs up a
throwaway user with a one-off invite, calls the API with its JWT, and deletes both.

`uv run scout release` ships the newest snapshot to the catalog bucket (dry run unless `--live`):
each version is uploaded once, never overwritten, and a `LATEST` pointer moves to it; the API
picks it up within a minute, and every API response names the catalog version it used.

Cards are drawn as simulated faces: each card's own colors (sampled by
`scripts/card_face_colors.py`) with its wordmarks as text, no logos or artwork. In `make demo` only,
a footer toggle switches to the issuers' card art, kept locally in `web/public/card-art` (gitignored:
never pushed or deployed).

`make e2e` (with the demo running) drives a real browser through sign-up, optimistic wallet edits,
rollback on API failure, and the gesture physics.

## Development

```bash
make test      # Python unit, API (in-memory + DynamoDB via moto), and CDK assertion tests
make lint      # pre-commit: gitleaks, ruff, formatting
make synth     # cdk synth
```

`make` reads a gitignored `.env` in the repo root:

```bash
AWS_PROFILE=chenhan9          # your AWS CLI profile
ALERT_EMAIL=you@example.com   # budget / alarm notifications
```

The site reads `CATALOG_PATH` (default: the local preview snapshot) and `NEXT_PUBLIC_API_URL`
(default `http://localhost:8000`) from the environment at build time.

> Not financial advice. This project takes no affiliate or issuer payments.
