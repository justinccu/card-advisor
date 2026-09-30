"""Traces and logs carry no conversation text (ADR 0009). The deployed runtime's env vars
(agentcore.json) turn content capture off in both places that record it; this pins that the
installed Strands and ADOT versions still honor them."""

import json
from pathlib import Path

AGENTCORE_JSON = Path(__file__).parents[3] / "agentcore" / "agentcore.json"


def runtime_env() -> dict[str, str]:
    [runtime] = json.loads(AGENTCORE_JSON.read_text())["runtimes"]
    return {v["name"]: v["value"] for v in runtime["envVars"]}


def test_strands_redacts_messages_prompts_and_tool_io(monkeypatch):
    from strands.telemetry.tracer import Tracer

    monkeypatch.setenv(
        "OTEL_SEMCONV_STABILITY_OPT_IN", runtime_env()["OTEL_SEMCONV_STABILITY_OPT_IN"]
    )
    tracer = Tracer()
    for attribute in (
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.system_instructions",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
    ):
        assert tracer._redact(attribute, "Amex Gold, income 50k") == "[REDACTED]"


def test_adot_does_not_capture_model_messages():
    # ADOT sets this to "true" on AgentCore with os.environ.setdefault, so an explicit value wins.
    assert runtime_env()["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "false"
