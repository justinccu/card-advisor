# Agent plane via agentcore CLI, everything else via CDK, bridged by SSM Parameters

Runtime, Memory, Gateway, Policy, and online evals are declared in `agentcore.json`; Cognito, DynamoDB, S3, CloudFront, APIs, Scout, and ops resources are CDK (Python). Using two IaC tools is deliberate: the CDK AgentCore constructs are alpha and would forfeit the CLI's eval, recommendation, and A/B workflows. CDK writes cross-cutting values (e.g. Cognito discovery URL) to SSM; a single `make deploy` runs CDK first, then `agentcore deploy`.
