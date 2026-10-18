"""How the agent talks to a cluster.

Analogy: the agent is a doctor, kubectl is the stethoscope.
 - LiveKubectl      -> a real stethoscope on a real patient (your kind / EKS cluster)
 - FixtureBackend   -> a recorded heartbeat played back (used by evals: same input, same output)
 - RecordingBackend -> a real stethoscope that also saves the recording (used to create new evals)

Every backend exposes one method: run(args) -> str.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable

MISSING_FIXTURE = "(no output recorded for this command in the eval scenario)"

# Flags that change formatting only. They are ignored when matching recorded output,
# so `logs x --tail=200` and `logs x --tail=50` replay the same recording.
_FORMAT_ONLY_PREFIXES = ("--tail=", "--sort-by=")


def fixture_key(args: Iterable[str]) -> str:
    """Normalise a kubectl command so recorded and live commands match."""
    tokens = [t for t in args if t]
    if tokens and tokens[0] == "kubectl":
        tokens = tokens[1:]
    out: list[str] = []
    skip_next = False
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if tok == "-o":
            skip_next = True
            continue
        if tok.startswith("-o=") or tok.startswith("--output="):
            continue
        if tok.startswith(_FORMAT_ONLY_PREFIXES):
            continue
        out.append(tok)
    return " ".join(out)


class LiveKubectl:
    """Runs real kubectl. Uses your kubeconfig locally, the ServiceAccount token in-cluster."""

    def __init__(self, binary: str = "kubectl", timeout: int = 30, context: str | None = None):
        self.binary = binary
        self.timeout = timeout
        self.context = context

    def run(self, args: list[str]) -> str:
        cmd = [self.binary, *args]
        if self.context:
            cmd += ["--context", self.context]
        try:
            proc = subprocess.run(  # noqa: S603 - args are validated, no shell
                cmd, capture_output=True, text=True, timeout=self.timeout, check=False
            )
        except FileNotFoundError:
            return f"ERROR: '{self.binary}' not found on PATH."
        except subprocess.TimeoutExpired:
            return f"ERROR: kubectl timed out after {self.timeout}s: {' '.join(args)}"
        out = proc.stdout.strip()
        if proc.returncode != 0:
            err = proc.stderr.strip()
            out = f"{out}\n{err}".strip() or f"ERROR: kubectl exited with code {proc.returncode}"
        return out or "(no output)"


class FixtureBackend:
    """Replays recorded kubectl output from an eval scenario."""

    def __init__(self, fixtures: dict[str, str]):
        self._data = {fixture_key(cmd.split()): out for cmd, out in fixtures.items()}
        self.calls: list[str] = []

    def run(self, args: list[str]) -> str:
        key = fixture_key(args)
        self.calls.append(key)
        return self._data.get(key, MISSING_FIXTURE)


class RecordingBackend:
    """Wraps a live backend and keeps every command + output (to build new eval scenarios)."""

    def __init__(self, inner: LiveKubectl):
        self.inner = inner
        self.recorded: dict[str, str] = {}

    def run(self, args: list[str]) -> str:
        out = self.inner.run(args)
        self.recorded["kubectl " + fixture_key(args)] = out
        return out
