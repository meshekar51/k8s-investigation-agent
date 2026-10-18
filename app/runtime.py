"""Wires settings -> backend + memory + model + agent. Shared by the API server and the CLI."""

from __future__ import annotations

from dataclasses import dataclass

from app.agent import build_agent, build_model
from app.config import Settings
from app.kube import LiveKubectl
from app.memory import IncidentMemory, build_checkpointer, build_store
from app.tools import make_tools


@dataclass
class Runtime:
    settings: Settings
    agent: object
    memory: IncidentMemory


def build_runtime(settings: Settings, backend=None, model=None) -> Runtime:
    backend = backend or LiveKubectl(settings.kubectl_bin, settings.kubectl_timeout, settings.kubectl_context)
    memory = IncidentMemory(build_store(settings))
    tools = make_tools(backend, memory=memory, max_chars=settings.max_output_chars)
    agent = build_agent(model or build_model(settings), tools, checkpointer=build_checkpointer(settings))
    return Runtime(settings=settings, agent=agent, memory=memory)


def remember(runtime: Runtime, question: str, result, requested_by: str) -> None:
    """Write a finished investigation to long-term memory."""
    if result.error or not result.footer:
        return
    f = result.footer
    runtime.memory.remember(
        str(f.get("namespace") or "cluster").lower(),
        {
            "question": question[:300],
            "category": f.get("category"),
            "subtype": f.get("subtype"),
            "root_cause": str(f.get("root_cause", ""))[:500],
            "severity": f.get("severity"),
            "session_id": result.session_id,
            "requested_by": requested_by,
        },
    )
