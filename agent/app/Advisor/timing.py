"""Where one message's time goes, logged once per message: the quota check, everything before the
first model call (Memory reads, prompt setup), each model call, each tool call, and the work after
the answer, every AgentCore Memory call (`watch_aws`), and when each event reached the page.
Names and durations only, never the user's or the model's text."""

import time

from strands.hooks import (
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeModelCallEvent,
    HookProvider,
    HookRegistry,
)


class Timings(HookProvider):
    def __init__(self) -> None:
        self.start()

    def start(self) -> None:
        self.began = time.monotonic()
        self.report = ""  # the last message's summary, once it's done
        self.marks: dict[str, float] = {}  # phase -> seconds it took
        self.first_model: float | None = None  # seconds from start to the first model call
        # (first output, whole call, output tokens) per model call
        self.models: list[tuple[float | None, float, int | None]] = []
        self.tools: list[tuple[str, float]] = []
        self.aws: list[tuple[str, float]] = []  # Memory API calls
        self.sent: list[tuple[str, float]] = []  # event kind -> seconds since the start
        self._model_began: float | None = None
        self._first_output: float | None = None

    def output(self) -> None:
        """The model call under way produced its first text or tool call."""
        if self._model_began is not None and self._first_output is None:
            self._first_output = time.monotonic() - self._model_began

    def event(self, kind: str) -> None:
        """An event went to the page (the first of each kind, and every text, reset and done)."""
        if kind in ("text", "reset", "done", "error") or kind not in {k for k, _ in self.sent}:
            self.sent.append((kind, time.monotonic() - self.began))

    def watch_aws(self, client) -> None:
        """Time every call a boto3 client makes (ListEvents, CreateEvent, RetrieveMemoryRecords),
        including those made in the Memory library's own threads."""

        def before(context, **kw):
            context["timing_began"] = time.monotonic()

        def after(context, model, **kw):
            if "timing_began" in context:
                self.aws.append((model.name, time.monotonic() - context["timing_began"]))

        client.meta.events.register("before-call.*", before)
        client.meta.events.register("after-call.*", after)

    def lap(self, phase: str, since: float) -> None:
        self.marks[phase] = self.marks.get(phase, 0.0) + time.monotonic() - since

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeModelCallEvent, self._before_model)
        registry.add_callback(AfterModelCallEvent, self._after_model)
        registry.add_callback(AfterToolCallEvent, self._after_tool)

    def _before_model(self, event: BeforeModelCallEvent) -> None:
        self._model_began = time.monotonic()
        self._first_output = None
        if self.first_model is None:
            self.first_model = self._model_began - self.began

    def _after_model(self, event: AfterModelCallEvent) -> None:
        if self._model_began is not None:
            written = _output_tokens(event)
            self.models.append((self._first_output, time.monotonic() - self._model_began, written))
            self._model_began = None

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        self.tools.append((event.tool_use.get("name", "?"), event.duration or 0.0))

    def summary(self, retries: int) -> str:
        def s(x: float) -> str:
            return f"{x:.1f}s"

        parts = [f"total={s(time.monotonic() - self.began)}", f"retries={retries}"]
        parts += [f"{phase}={s(took)}" for phase, took in self.marks.items()]
        if self.first_model is not None:
            parts.append(f"before_model={s(self.first_model)}")
        # each model call as first-output/whole/tokens written: waiting, then writing
        parts.append(
            "model=["
            + ", ".join(
                f"{s(first) if first is not None else '?'}/{s(whole)}"
                + (f"/{tokens}tok" if tokens is not None else "")
                for first, whole, tokens in self.models
            )
            + "]"
        )
        parts.append("tools=[" + ", ".join(f"{name} {s(took)}" for name, took in self.tools) + "]")
        parts.append("memory=[" + ", ".join(f"{name} {s(took)}" for name, took in self.aws) + "]")
        parts.append("sent=[" + ", ".join(f"{kind}@{s(at)}" for kind, at in self.sent) + "]")
        return " ".join(parts)


def _output_tokens(event: AfterModelCallEvent) -> int | None:
    """Tokens this model call wrote. Strands attaches the call's usage to its message before
    this hook runs (its running total is updated only after)."""
    response = getattr(event, "stop_response", None)
    message = getattr(response, "message", None) or {}
    return (message.get("metadata") or {}).get("usage", {}).get("outputTokens")
