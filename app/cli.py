"""Run the agent from your terminal against whatever cluster kubectl points at.

  python -m app.cli "Pods in namespace lab are failing. Investigate."
  python -m app.cli --scenario evals/scenarios/oomkilled.json              # replay an eval scenario
  python -m app.cli --session inc-42 "And what about the oom-app pod?"     # follow-up turn

Sessions survive between CLI runs only when POSTGRES_HOST points at a database;
locally (in-memory) use the API server for multi-turn sessions.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.agent import investigate
from app.config import load_settings
from app.kube import FixtureBackend
from app.runtime import build_runtime, remember


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Kubernetes SRE investigation agent")
    p.add_argument("question", nargs="?", help="what to investigate")
    p.add_argument("--session", help="session id to continue a previous conversation")
    p.add_argument("--scenario", help="replay an eval scenario JSON instead of a live cluster")
    p.add_argument("--json", action="store_true", help="print the full result as JSON")
    a = p.parse_args(argv)

    settings = load_settings()
    backend = None
    question = a.question
    if a.scenario:
        with open(a.scenario, encoding="utf-8") as fh:
            sc = json.load(fh)
        backend = FixtureBackend(sc["fixtures"])
        question = question or sc["input"]
    if not question:
        p.error("give a question (or --scenario)")

    rt = build_runtime(settings, backend=backend)
    result = investigate(rt.agent, question, a.session, settings.recursion_limit)
    remember(rt, question, result, "cli")

    if a.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.report or result.error)
        print("\n--- verdict ---")
        print(json.dumps(result.footer, indent=2))
        print(f"session={result.session_id} tools={len(result.tool_calls)} "
              f"tokens_in={result.input_tokens} tokens_out={result.output_tokens} time={result.duration_s}s")
    return 1 if result.error else 0


if __name__ == "__main__":
    sys.exit(main())
