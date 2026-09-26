# Scout is a Step Functions pipeline, not an AgentCore Runtime agent

Scout's work is fixed-shape (fetch → hash diff → schema-constrained LLM extraction → Proposed Change), so it runs as Step Functions + Lambda calling Bedrock Converse directly; the LLM is used only for extraction and has no tools, which also limits prompt injection from scraped pages. AgentCore Browser is used only as a fallback for JavaScript-rendered or bot-protected Issuer pages. The LLM is skipped entirely when a source's content hash is unchanged.

## Consequences

- Prompt-level instructions alone don't stop indirect prompt injection (Greshake et al. 2023; Yi et al., KDD 2025), so the defenses are structural: one forced tool and no others, a per-request random fence name with fence-like text stripped from the page (spotlighting, Hines et al. 2024), verbatim-evidence checks, and human review.
- Model-written `reviewer_notes` are review aids only and never reach the Catalog Snapshot unless a reviewer rewrites them, because the chat agent reads the catalog: publishing them would turn a scraped page into a second-order injection into the agent.
