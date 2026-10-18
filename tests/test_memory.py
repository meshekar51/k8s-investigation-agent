"""Memory backends. The Postgres tests run when TEST_POSTGRES_HOST is set
(CI's e2e job and the README's local check do this); otherwise they are skipped."""

import dataclasses
import os
import uuid

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent import build_agent, investigate
from app.config import load_settings
from app.memory import IncidentMemory, build_checkpointer, build_store
from tests.fakes import scripted


def test_no_postgres_means_in_memory(monkeypatch):
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    s = load_settings()
    assert s.postgres_uri is None
    assert isinstance(build_checkpointer(s), InMemorySaver)


def test_postgres_uri_escapes_password(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "sre-agent-db")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss/w:rd")
    assert load_settings().postgres_uri == "postgresql://sreagent:p%40ss%2Fw%3Ard@sre-agent-db:5432/sreagent?sslmode=disable"


PG = os.getenv("TEST_POSTGRES_HOST")


@pytest.mark.skipif(not PG, reason="set TEST_POSTGRES_HOST to run against a real PostgreSQL")
def test_postgres_session_and_incident_memory():
    s = dataclasses.replace(
        load_settings(),
        postgres_host=PG,
        postgres_port=int(os.getenv("TEST_POSTGRES_PORT", "5432")),
        postgres_password=os.getenv("TEST_POSTGRES_PASSWORD"),
    )
    memory = IncidentMemory(build_store(s))
    ns = f"test-{uuid.uuid4().hex[:6]}"
    memory.remember(ns, {"subtype": "OOMKilled"})
    assert memory.recall(ns)[0]["subtype"] == "OOMKilled"

    final = AIMessage(content='done ```json\n{"category": "B", "root_cause": "x"}\n```')
    agent = build_agent(scripted([final, final]), [], checkpointer=build_checkpointer(s))
    sid = f"sess-{uuid.uuid4().hex[:8]}"
    investigate(agent, "first question", session_id=sid)
    investigate(agent, "second question", session_id=sid)
    humans = [m.text for m in agent.get_state({"configurable": {"thread_id": sid}}).values["messages"] if m.type == "human"]
    assert humans == ["first question", "second question"]
