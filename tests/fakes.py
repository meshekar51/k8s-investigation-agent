"""A scripted stand-in for Claude so tests run offline (no AWS, no tokens)."""

from __future__ import annotations

from collections.abc import Iterator

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage


class ScriptedChatModel(GenericFakeChatModel):
    """Returns the given AIMessages in order; supports tool binding like a real model."""

    def bind_tools(self, tools, **kwargs):  # noqa: ARG002 - same signature as real models
        return self


def scripted(messages: list[AIMessage]) -> ScriptedChatModel:
    it: Iterator[AIMessage] = iter(messages)
    return ScriptedChatModel(messages=it)


def tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


FINAL_OOM = AIMessage(
    content=(
        "INCIDENT SUMMARY\nIssue: oom-app restarts\n\nROOT CAUSE\n"
        "Container exceeded its 64Mi memory limit and was OOMKilled (exit code 137).\n"
        "Confidence: 95%\n"
        '```json\n{"category": "B", "subtype": "OOMKilled", "root_cause": "Container is OOMKilled: '
        'memory use exceeds the 64Mi limit (exit code 137)", "confidence": 95, "severity": "P2", '
        '"namespace": "lab", "insufficient_evidence": false}\n```'
    ),
    usage_metadata={"input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500},
)
