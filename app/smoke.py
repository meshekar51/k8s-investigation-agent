"""Post-deploy test, run INSIDE the agent pod (so it uses the pod's real identity):

  kubectl -n agent-staging exec deploy/sre-agent -- python -m app.smoke
  kubectl -n agent-staging exec deploy/sre-agent -- python -m app.smoke \
      --question "Pod oom-app in namespace lab keeps restarting. Investigate." --expect-category B

Checks: the API is ready, one real investigation runs end-to-end
(Bedrock + RBAC-limited kubectl + PostgreSQL memory) and returns a verdict.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

BASE = os.getenv("SMOKE_URL", "http://127.0.0.1:8080")


def _call(path: str, body: dict | None = None, timeout: int = 300) -> dict:
    headers = {"Content-Type": "application/json", "X-Requested-By": "smoke-test"}
    if os.getenv("API_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['API_TOKEN']}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="End-to-end check of a deployed agent")
    p.add_argument("--question", help="question to ask (default: health of this pod's namespace)")
    p.add_argument("--expect-category", help="fail unless the verdict category is one of these, e.g. B or A,C")
    a = p.parse_args(argv)

    ns = os.getenv("POD_NAMESPACE", "default")
    question = a.question or f"Smoke test: check the health of the pods in namespace {ns}."
    print("readyz:", _call("/readyz"))
    print("question:", question)
    result = _call("/investigate", {"question": question})
    footer = result.get("footer") or {}
    print("tools used:", result.get("tool_calls"))
    print("verdict:", json.dumps(footer))
    print(f"tokens in/out: {result.get('input_tokens')}/{result.get('output_tokens')}  time: {result.get('duration_s')}s")

    if not result.get("tool_calls"):
        print("FAIL: agent answered without collecting evidence")
        return 1
    if not footer:
        print("FAIL: no machine-readable verdict in the reply")
        return 1
    if a.expect_category:
        wanted = {c.strip().upper() for c in a.expect_category.split(",")}
        if str(footer.get("category", "")).upper() not in wanted:
            print(f"FAIL: expected category {sorted(wanted)}, got {footer.get('category')}")
            print(result.get("report", "")[:3000])
            return 1
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
