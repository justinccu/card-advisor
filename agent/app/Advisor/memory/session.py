"""AgentCore Memory for the Advisor (ADR 0005, 0009): only user preferences and conversation
summaries persist across conversations. Facts like credit score or tax id always come from the
Applicant Profile, so Memory never becomes a second, drifting copy of them."""

import os
import uuid

from bedrock_agentcore.memory.integrations.strands.config import (
    AgentCoreMemoryConfig,
    RetrievalConfig,
)
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)

MEMORY_ID = os.getenv("MEMORY_ADVISORMEMORY_ID")
REGION = os.getenv("AWS_REGION", "us-east-2")


def get_memory_session_manager(
    session_id: str | None, actor_id: str
) -> AgentCoreMemorySessionManager | None:
    if not MEMORY_ID:  # local dev without deployed memory: conversation state only
        return None
    session_id = session_id or uuid.uuid4().hex
    retrieval = {
        f"/users/{actor_id}/preferences": RetrievalConfig(top_k=3, relevance_score=0.5),
        f"/summaries/{actor_id}": RetrievalConfig(top_k=3, relevance_score=0.5),
    }
    return AgentCoreMemorySessionManager(
        AgentCoreMemoryConfig(
            memory_id=MEMORY_ID,
            session_id=session_id,
            actor_id=actor_id,
            retrieval_config=retrieval,
        ),
        REGION,
    )
