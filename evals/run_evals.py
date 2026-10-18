"""Run every scenario in evals/scenarios/ against the agent and grade it.

  python -m evals.run_evals                         # all scenarios, gate at 80% pass rate
  python -m evals.run_evals --only oomkilled        # one scenario
  python -m evals.run_evals --threshold 0.9 --junit reports/evals.xml   # CI mode

Each scenario replays RECORDED kubectl output (FixtureBackend), so the cluster is not
needed and every run sees identical evidence: only the agent's reasoning is being tested.
Exit code 1 when the pass rate is below --threshold -> the pipeline stops before deploy.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from langgraph.store.memory import InMemoryStore

from app.agent import build_agent, build_model, investigate
from app.config import load_settings
from app.kube import FixtureBackend
from app.memory import IncidentMemory
from app.tools import make_tools
from evals.scoring import score

SCENARIO_DIR = Path(__file__).parent / "scenarios"


def load_scenarios(directory: Path = SCENARIO_DIR, only: list[str] | None = None) -> list[dict]:
    scenarios = []
    for path in sorted(directory.glob("*.json")):
        sc = json.loads(path.read_text(encoding="utf-8"))
        for key in ("id", "input", "fixtures", "expected"):
            if key not in sc:
                raise ValueError(f"{path.name}: missing '{key}'")
        if only and sc["id"] not in only:
            continue
        scenarios.append(sc)
    return scenarios


def run_one(scenario: dict, model, recursion_limit: int = 40):
    backend = FixtureBackend(scenario["fixtures"])
    memory = IncidentMemory(InMemoryStore())  # empty memory: scenarios must not leak into each other
    agent = build_agent(model, make_tools(backend, memory=memory))
    result = investigate(agent, scenario["input"], recursion_limit=recursion_limit)
    return result, score(scenario, result)


def run_suite(scenarios: list[dict], model, workers: int = 2, recursion_limit: int = 40) -> list[tuple]:
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(run_one, sc, model, recursion_limit) for sc in scenarios]
        return [(sc, *f.result()) for sc, f in zip(scenarios, futures, strict=True)]


def write_junit(rows: list[tuple], path: Path) -> None:
    suite = ET.Element("testsuite", name="agent-evals", tests=str(len(rows)),
                       failures=str(sum(1 for _, _, c in rows if not c.passed)))
    for sc, result, card in rows:
        case = ET.SubElement(suite, "testcase", classname="evals", name=sc["id"], time=str(result.duration_s))
        if not card.passed:
            fail = ET.SubElement(case, "failure", message=f"{card.points}/100")
            fail.text = "\n".join(card.notes) + "\n\nverdict: " + json.dumps(result.footer)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def summarise(rows: list[tuple]) -> dict:
    n = len(rows)
    passed = sum(1 for _, _, c in rows if c.passed)
    return {
        "scenarios": n,
        "passed": passed,
        "pass_rate": round(passed / n, 3) if n else 0.0,
        "avg_points": round(sum(c.points for _, _, c in rows) / n, 1) if n else 0.0,
        "tokens_in": sum(r.input_tokens for _, r, _ in rows),
        "tokens_out": sum(r.output_tokens for _, r, _ in rows),
        "avg_tool_calls": round(sum(len(r.tool_calls) for _, r, _ in rows) / n, 1) if n else 0.0,
    }


def main(argv: list[str] | None = None, model=None) -> int:
    p = argparse.ArgumentParser(description="Agent evaluation suite")
    p.add_argument("--only", nargs="*", help="scenario ids to run")
    p.add_argument("--threshold", type=float, default=0.8, help="minimum pass rate (0-1)")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--out", default="reports/eval-report.json")
    p.add_argument("--junit", default="")
    p.add_argument("--scenarios", default=str(SCENARIO_DIR))
    a = p.parse_args(argv)

    settings = load_settings()
    scenarios = load_scenarios(Path(a.scenarios), a.only)
    if not scenarios:
        print("no scenarios found")
        return 1
    model = model or build_model(settings)

    started = time.time()
    rows = run_suite(scenarios, model, a.workers, settings.recursion_limit)

    print(f"\n{'SCENARIO':34} {'PTS':>4}  {'RESULT':6}  {'CAT':7} NOTES")
    print("-" * 100)
    for sc, result, card in rows:
        cat = (result.footer or {}).get("category", "-")
        status = "PASS" if card.passed else "FAIL"
        print(f"{sc['id']:34} {card.points:>4}  {status:6}  {cat:7} {'; '.join(card.notes)[:60]}")
    summary = summarise(rows)
    summary["threshold"] = a.threshold
    summary["model"] = settings.model_id
    summary["seconds"] = round(time.time() - started, 1)
    gate = summary["pass_rate"] >= a.threshold
    summary["gate"] = "PASSED" if gate else "FAILED"
    print("-" * 100)
    print(json.dumps(summary, indent=2))

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "summary": summary,
        "results": [{"scenario": sc["id"], "score": card.to_dict(), "result": result.to_dict()} for sc, result, card in rows],
    }, indent=2), encoding="utf-8")
    if a.junit:
        write_junit(rows, Path(a.junit))
    return 0 if gate else 1


if __name__ == "__main__":
    sys.exit(main())
