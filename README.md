# card-advisor (working name)

A US credit card advisor: a static, non-LLM catalog for browsing and comparing cards, and an invite-only conversational agent on Amazon Bedrock AgentCore that recommends cards from a deterministic eligibility engine.

- Domain language: [CONTEXT.md](CONTEXT.md)
- Architecture decisions: [docs/adr/](docs/adr/)

## Development

```bash
make install   # uv workspace + pre-commit hooks (gitleaks, ruff)
make test      # unit + CDK assertion tests
make synth     # cdk synth (copy .env.example to .env first)
```

> Not financial advice. This project takes no affiliate or issuer payments.
