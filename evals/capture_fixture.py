"""Turn a REAL broken pod into a new eval scenario (how you grow from 14 to 50+ scenarios).

1. Break something in your kind cluster (see lab/), wait until it fails.
2. Capture what kubectl shows:
     python -m evals.capture_fixture --id oom-batch-job --namespace lab --pod oom-app-xxxxx `
        --deployment oom-app --input "Pod oom-app in namespace lab keeps restarting. Investigate."
3. Open evals/scenarios/<id>.json and fill in the "expected" block (the answer key).
4. Run: python -m evals.run_evals --only <id>

The commands recorded are built by the same functions the agent's tools use, so the
replay always matches what the agent asks for.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from app import tools as t
from app.config import load_settings
from app.kube import LiveKubectl, RecordingBackend

OUT_DIR = Path(__file__).parent / "scenarios"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Record kubectl evidence into an eval scenario")
    p.add_argument("--id", required=True, help="scenario id, e.g. oom-batch-job")
    p.add_argument("--input", required=True, help="the question the agent will be asked")
    p.add_argument("--namespace", required=True)
    p.add_argument("--pod", required=True)
    p.add_argument("--deployment", default="")
    p.add_argument("--container", default="")
    p.add_argument("--extra", nargs="*", default=[], help='extra "kind/name" to get+describe, e.g. service/web')
    a = p.parse_args(argv)

    s = load_settings()
    rec = RecordingBackend(LiveKubectl(s.kubectl_bin, s.kubectl_timeout, s.kubectl_context))

    rec.run(t.cmd_list_pods("all"))
    rec.run(t.cmd_list_pods(a.namespace))
    rec.run(t.cmd_events("all"))
    rec.run(t.cmd_events(a.namespace))
    describe = rec.run(t.cmd_describe_pod(a.namespace, a.pod))
    rec.run(t.cmd_logs(a.namespace, a.pod, a.container))
    rec.run(t.cmd_logs(a.namespace, a.pod, a.container, previous=True))
    if a.deployment:
        rec.run(t.cmd_describe_deployment(a.namespace, a.deployment))
    rec.run(t.cmd_list_nodes())
    node = re.search(r"^Node:\s+([^/\s]+)", describe, re.MULTILINE)
    if node and node.group(1) != "<none>":
        rec.run(t.cmd_describe_node(node.group(1)))
    for item in a.extra:
        kind, _, name = item.partition("/")
        rec.run(t.cmd_get_resources(kind, a.namespace, name))
        rec.run(t.cmd_describe_resource(kind, a.namespace, name))

    scenario = {
        "id": a.id,
        "description": "TODO: one line on what is broken",
        "source": "captured from a live cluster",
        "input": a.input,
        "fixtures": rec.recorded,
        "expected": {
            "category": "TODO: A|B|C|D|E|UNKNOWN (or a list of acceptable letters)",
            "root_cause_all": [["TODO keyword", "synonym"], ["TODO second fact"]],
            "must_not_claim": ["TODO wrong cause the agent must NOT conclude"],
            "min_tool_calls": 2,
        },
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{a.id}.json"
    path.write_text(json.dumps(scenario, indent=2), encoding="utf-8")
    print(f"wrote {path} with {len(rec.recorded)} recorded commands - now fill in 'expected'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
