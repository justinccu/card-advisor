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

The public site (S5) deploys in the same job, in four steps:
1. Build `web/out` against the live API, Cognito and Advisor runtime.
2. Load every page under CloudFront's security headers (`scripts/check_site_headers.py`). A
   Content-Security-Policy that would block anything fails the job before the site changes.
3. Publish through the `card-advisor-web` stack: a private S3 bucket behind CloudFront with
   origin access control, HTTPS only, and CSP, HSTS and frame-deny headers. Hashed assets are
   cached for a year and HTML is revalidated on each visit.
4. Smoke-test the live URL.

`make site-check` runs steps 1 and 2 locally, and deploys nothing. Issuer card art is never
published. After the first deploy, add the site's URL (the `SiteUrl` output, also in SSM at
`/card-advisor/site-url`) to `cors_origins` in `infra/cdk.json`, so the API accepts calls from it.

`make deploy-infra` deploys the stacks (data, auth, api); `make aws-smoke` then signs up a
throwaway user with a one-off invite, calls the API with its JWT, and deletes both.

`uv run scout release` ships the newest snapshot to the catalog bucket (dry run unless `--live`):
each version is uploaded once, never overwritten, and a `LATEST` pointer moves to it; the API
picks it up within a minute, and every API response names the catalog version it used.

Cards are drawn as simulated faces: each card's own colors (sampled by
`scripts/card_face_colors.py`) with its wordmarks as text, no logos or artwork. In `make demo` only,
a footer toggle switches to the issuers' card art, kept locally in `web/public/card-art` (gitignored:
never pushed or deployed).

`make agent` (in a second terminal, next to `make demo`) runs the Advisor chat agent on :8080
without deploying it. It calls a Bedrock model with your AWS profile (a fraction of a cent per
message), and the site's "Ask the Advisor" button and `/advisor` page talk to it.

Card search (the site's boxes and the Advisor's card lookup) takes a bank by either name ("Amex",
"American Express"), card aliases ("CSP") and typos. Names live in `catalog/seed/issuers.yaml`
and each seed card's `aliases`, and are stamped into the snapshot by `scout publish`.

`make eval` runs the Advisor golden set (`agent/evals/golden.yaml`) against the real model and
gates on leaks, unsourced amounts, uncited rules, language and each case's expectations. It
costs about $0.6 a run. `make agent-deploy` runs it first and won't deploy if it fails.

Each Advisor answer can be rated 👍 / 👎. `make feedback` (`DOWN=1` for 👎 only) lists rated
answers on the deployed stack, with the tools each one called, so a bad answer can be traced to
the data or to the model.

`make e2e` (with the demo running) drives a real browser through sign-up, optimistic wallet edits,
rollback on API failure, the gesture physics, and the Advisor chat against a scripted agent (no
model calls).

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
