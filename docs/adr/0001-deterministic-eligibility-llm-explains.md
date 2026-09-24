# Recommendations are computed by deterministic code; the LLM only elicits and explains

Eligibility Rules and card scoring live in a shared, unit-tested Python package exposed to the agent as tools; the LLM gathers the Applicant Profile, calls the tools, and explains results with sources. We rejected letting the LLM rank cards directly because financial recommendations must not hallucinate, must be reproducible against a Catalog Snapshot, and need a ground truth for CI eval gates. The same package serves the non-LLM web pages, so there is one source of truth for rules.
