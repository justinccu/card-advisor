# Scout is a Step Functions pipeline, not an AgentCore Runtime agent

Scout's work is fixed-shape (fetch → hash diff → schema-constrained LLM extraction → Proposed Change), so it runs as Step Functions + Lambda calling Bedrock Converse directly; the LLM is used only for extraction and has no tools, which also limits prompt injection from scraped pages. AgentCore Browser is used only as a fallback for JavaScript-rendered or bot-protected Issuer pages. The LLM is skipped entirely when a source's content hash is unchanged.
