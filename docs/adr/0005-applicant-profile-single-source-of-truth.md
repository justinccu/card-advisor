# Applicant Profile lives only in DynamoDB; AgentCore Memory holds soft preferences only

Facts that affect eligibility (SSN/ITIN status, credit history, score and income ranges) are stored solely in DynamoDB and changed by the agent only through an `update_profile` tool after user confirmation. AgentCore Memory's semantic extraction would otherwise create a second, drifting copy of the same facts; Memory is restricted to soft preferences and conversation summaries. Account deletion must purge both stores. Scores and income are stored as ranges; SSN numbers are never stored.
