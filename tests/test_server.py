import dataclasses

import pytest
from fastapi.testclient import TestClient

from app.kube import FixtureBackend
from evals.run_evals import load_scenarios
from tests.fakes import FINAL_OOM, scripted, tool_call

OOM = next(s for s in load_scenarios() if s["id"] == "oomkilled")


@pytest.fixture
def client(monkeypatch):
    from app import server
    from app.runtime import build_runtime as real_build_runtime

    def fake_runtime(settings, backend=None, model=None):
        model = scripted([tool_call("list_pods", {"namespace": "lab"}, "c1"), FINAL_OOM] * 3)
        return real_build_runtime(settings, FixtureBackend(OOM["fixtures"]), model)

    monkeypatch.setattr(server, "build_runtime", fake_runtime)
    monkeypatch.setattr(server, "settings", dataclasses.replace(server.settings, api_token="s3cret"))
    with TestClient(server.app) as c:
        yield c


def test_health_and_ready(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json()["status"] == "ready"


def test_investigate_requires_token(client):
    assert client.post("/investigate", json={"question": "why is lab broken"}).status_code == 401


def test_investigate_returns_verdict_and_metrics(client):
    r = client.post("/investigate", json={"question": "why is oom-app restarting?"},
                    headers={"Authorization": "Bearer s3cret", "X-Requested-By": "chandra"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["footer"]["subtype"] == "OOMKilled"
    assert body["tool_calls"] == ["list_pods"]
    metrics = client.get("/metrics/").text
    assert 'sre_agent_investigations_total{category="B",env="dev",status="ok"}' in metrics
    assert 'sre_agent_tool_calls_total{env="dev",tool="list_pods"}' in metrics


def test_finished_investigation_is_remembered(client):
    from app import server

    client.post("/investigate", json={"question": "why is oom-app restarting?"}, headers={"Authorization": "Bearer s3cret"})
    past = server.STATE["rt"].memory.recall("lab")
    assert past and past[0]["subtype"] == "OOMKilled"
