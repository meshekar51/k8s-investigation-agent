"""End-to-end through the real LangGraph loop, with a scripted model instead of Bedrock."""

import json

from langgraph.checkpoint.memory import InMemorySaver

from app.agent import build_agent, investigate
from app.kube import FixtureBackend
from evals import run_evals
from evals.run_evals import load_scenarios, run_one
from tests.fakes import FINAL_OOM, scripted, tool_call

OOM = next(s for s in load_scenarios() if s["id"] == "oomkilled")
POD = "oom-app-7d5b6c9f4c-q7lm2"


def _oom_script():
    return scripted([
        tool_call("list_pods", {"namespace": "lab"}, "c1"),
        tool_call("describe_pod", {"namespace": "lab", "pod": POD}, "c2"),
        tool_call("get_pod_logs", {"namespace": "lab", "pod": POD, "previous": True}, "c3"),
        FINAL_OOM,
    ])


def test_agent_calls_tools_and_returns_verdict():
    backend = FixtureBackend(OOM["fixtures"])
    from app.tools import make_tools

    agent = build_agent(_oom_script(), make_tools(backend))
    result = investigate(agent, OOM["input"])
    assert result.error is None
    assert result.tool_calls == ["list_pods", "describe_pod", "get_pod_logs"]
    assert result.footer["category"] == "B"
    assert result.input_tokens == 1200
    assert "describe pod oom-app-7d5b6c9f4c-q7lm2 -n lab" in backend.calls
    assert "```json" not in result.report  # footer stripped from the human report


def test_eval_runner_scores_a_good_answer_as_pass():
    result, card = run_one(OOM, _oom_script())
    assert card.passed, card.notes
    assert card.points == 100


def test_eval_cli_gate_and_reports(tmp_path):
    out, junit = tmp_path / "r.json", tmp_path / "j.xml"
    rc = run_evals.main(["--only", "oomkilled", "--workers", "1", "--out", str(out), "--junit", str(junit)], model=_oom_script())
    assert rc == 0
    assert json.loads(out.read_text())["summary"]["gate"] == "PASSED"
    assert "testsuite" in junit.read_text()


def test_session_memory_keeps_previous_turns():
    model = scripted([FINAL_OOM, FINAL_OOM])
    agent = build_agent(model, [], checkpointer=InMemorySaver())
    investigate(agent, "first question about lab", session_id="inc-1")
    investigate(agent, "follow-up question", session_id="inc-1")
    state = agent.get_state({"configurable": {"thread_id": "inc-1"}})
    humans = [m.text for m in state.values["messages"] if m.type == "human"]
    assert humans == ["first question about lab", "follow-up question"]
