"""The Advisor on AgentCore Runtime (ADR 0009).

Each request: identify the caller from the verified token, take one message from today's quota
(before any model call), then stream the agent's answer as small JSON events the site renders:

    {"type": "quota", "remaining": 9, "resets_at": "..."}
    {"type": "tool", "name": "rank_cards"}        # a tool started (for a progress hint)
    {"type": "text", "text": "..."}               # answer text, streamed
    {"type": "error", "code": "quota" | "auth" | "input" | "internal", "message": "..."}
    {"type": "done"}
"""

import uuid
from collections import OrderedDict

from advisor.api import AdvisorApi, ApiError, QuotaExceeded
from advisor.identity import NotSignedIn, caller_from
from advisor.prompt import SYSTEM_PROMPT
from advisor.tools import build_tools
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from memory.session import get_memory_session_manager
from model.load import load_model
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager

app = BedrockAgentCoreApp()
log = app.logger

MAX_PROMPT_CHARS = 2000
MAX_SESSIONS = 200  # agents kept warm per runtime process
WINDOW_MESSAGES = 20  # conversation turns sent to the model (bounds tokens per request)


class Session:
    """One user's conversation. `api` is replaced on every request, so tools always call the API
    with the caller's current token."""

    def __init__(self, session_id: str, user_id: str) -> None:
        self.api: AdvisorApi | None = None
        self.agent = Agent(
            model=load_model(),
            system_prompt=SYSTEM_PROMPT,
            tools=build_tools(self),
            session_manager=get_memory_session_manager(session_id, user_id),
            conversation_manager=SlidingWindowConversationManager(window_size=WINDOW_MESSAGES),
            callback_handler=None,
        )


_sessions: OrderedDict[tuple[str, str], Session] = OrderedDict()


def get_session(session_id: str, user_id: str) -> Session:
    # Keyed by user too: a session id guessed by another user never reaches this conversation.
    key = (session_id, user_id)
    if key in _sessions:
        _sessions.move_to_end(key)
        return _sessions[key]
    session = _sessions[key] = Session(session_id, user_id)
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return session


def _error(code: str, message: str, **extra) -> dict:
    return {"type": "error", "code": code, "message": message, **extra}


@app.entrypoint
async def invoke(payload, context):
    try:
        caller = caller_from(getattr(context, "request_headers", None))
    except NotSignedIn as e:
        yield _error("auth", str(e))
        return

    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        yield _error("input", "Send a message in the 'prompt' field.")
        return
    if len(prompt) > MAX_PROMPT_CHARS:
        yield _error("input", f"Messages are limited to {MAX_PROMPT_CHARS} characters.")
        return

    api = AdvisorApi(caller.headers)
    try:
        quota = api.take_turn()  # before the model runs: an exhausted quota costs nothing
    except QuotaExceeded as e:
        detail = e.detail if isinstance(e.detail, dict) else {}
        message = detail.pop("message", "Today's messages are used up.")
        yield _error("quota", message, **detail)
        return
    except ApiError as e:
        log.warning("quota check failed: %s", e)
        yield _error("internal", "The Advisor can't reach your account right now.")
        return
    yield {"type": "quota", "remaining": quota["remaining"], "resets_at": quota["resets_at"]}

    session_id = getattr(context, "session_id", None) or uuid.uuid4().hex
    session = get_session(session_id, caller.user_id)
    session.api = api
    last_tool = None
    try:
        async for event in session.agent.stream_async(prompt):
            if isinstance(event, dict) and isinstance(event.get("data"), str):
                yield {"type": "text", "text": event["data"]}
            elif isinstance(event, dict) and "current_tool_use" in event:
                name = (event["current_tool_use"] or {}).get("name")
                if name and name != last_tool:
                    last_tool = name
                    yield {"type": "tool", "name": name}
    except Exception:
        log.exception("advisor turn failed")
        yield _error("internal", "Something went wrong while answering. Please try again.")
        return
    finally:
        session.api = None  # don't keep the caller's token after the reply
    yield {"type": "done"}


if __name__ == "__main__":
    app.run()
