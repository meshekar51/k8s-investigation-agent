"""The agent's hands: READ-ONLY kubectl tools.

Production rules baked in here (not left to the prompt):
  1. Read-only verbs only (get / describe / logs). There is no delete/apply/edit/exec tool.
  2. Secrets can never be read, whatever the model asks for.
  3. Every name is validated (DNS-1123), so the model cannot smuggle flags like
     "--kubeconfig=/etc/x" or shell tricks into a command.
  4. Output is clipped so one noisy log cannot blow the token budget.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from langchain_core.tools import BaseTool, tool

NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$")
CONTAINER_RE = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")

GET_KINDS = {
    "pods", "deployments", "replicasets", "statefulsets", "daemonsets", "jobs", "cronjobs",
    "services", "endpoints", "endpointslices", "ingresses", "networkpolicies",
    "configmaps",  # `get` shows NAME/DATA/AGE only - never the values
    "persistentvolumeclaims", "persistentvolumes", "storageclasses",
    "horizontalpodautoscalers", "namespaces", "nodes",
}
DESCRIBE_KINDS = {
    "deployments", "replicasets", "statefulsets", "daemonsets", "jobs", "services",
    "ingresses", "networkpolicies", "persistentvolumeclaims", "persistentvolumes",
    "horizontalpodautoscalers", "nodes", "pods",
}
CLUSTER_SCOPED = {"nodes", "persistentvolumes", "storageclasses", "namespaces"}
FORBIDDEN_KINDS = {"secret", "secrets", "serviceaccounttokens", "tokenreviews"}
ALIASES = {
    "pod": "pods", "po": "pods", "deploy": "deployments", "deployment": "deployments",
    "rs": "replicasets", "replicaset": "replicasets", "sts": "statefulsets", "statefulset": "statefulsets",
    "ds": "daemonsets", "daemonset": "daemonsets", "job": "jobs", "cronjob": "cronjobs",
    "svc": "services", "service": "services", "ep": "endpoints", "endpoint": "endpoints",
    "endpointslice": "endpointslices", "ing": "ingresses", "ingress": "ingresses",
    "netpol": "networkpolicies", "networkpolicy": "networkpolicies",
    "cm": "configmaps", "configmap": "configmaps", "pvc": "persistentvolumeclaims",
    "persistentvolumeclaim": "persistentvolumeclaims", "pv": "persistentvolumes",
    "persistentvolume": "persistentvolumes", "sc": "storageclasses", "storageclass": "storageclasses",
    "hpa": "horizontalpodautoscalers", "horizontalpodautoscaler": "horizontalpodautoscalers",
    "ns": "namespaces", "namespace": "namespaces", "node": "nodes", "no": "nodes",
}
MAX_LOG_TAIL = 500


class Backend(Protocol):
    def run(self, args: list[str]) -> str: ...


class ToolInputError(ValueError):
    """Raised when the model passes something we refuse to run."""


# ---------------------------------------------------------------- validation
def check_name(value: str, what: str) -> str:
    value = (value or "").strip()
    if not NAME_RE.match(value):
        raise ToolInputError(f"invalid {what} '{value}': must be a lowercase DNS-1123 name")
    return value


def check_namespace(value: str | None) -> str | None:
    """Returns None for 'all namespaces'."""
    v = (value or "").strip().lower()
    if v in ("", "all", "*", "-a", "--all-namespaces"):
        return None
    return check_name(v, "namespace")


def check_kind(kind: str, allowed: set[str]) -> str:
    k = (kind or "").strip().lower()
    k = ALIASES.get(k, k)
    if k in FORBIDDEN_KINDS:
        raise ToolInputError("reading Secrets is not allowed for this agent (governance rule)")
    if k not in allowed:
        raise ToolInputError(f"kind '{kind}' is not allowed. Allowed: {', '.join(sorted(allowed))}")
    return k


def _ns_args(ns: str | None) -> list[str]:
    return ["-A"] if ns is None else ["-n", ns]


# ------------------------------------------------------------ command builders
# Pure functions: easy to unit test, and the capture script reuses them so
# recorded eval fixtures always match what the tools ask for.
def cmd_list_pods(namespace: str | None = "all") -> list[str]:
    return ["get", "pods", *_ns_args(check_namespace(namespace)), "-o", "wide"]


def cmd_events(namespace: str | None = "all") -> list[str]:
    return ["get", "events", *_ns_args(check_namespace(namespace)), "--sort-by=.lastTimestamp"]


def cmd_describe_pod(namespace: str, pod: str) -> list[str]:
    ns = check_namespace(namespace)
    if ns is None:
        raise ToolInputError("describe_pod needs a specific namespace")
    return ["describe", "pod", check_name(pod, "pod"), "-n", ns]


def cmd_logs(namespace: str, pod: str, container: str = "", previous: bool = False, tail: int = 200) -> list[str]:
    ns = check_namespace(namespace)
    if ns is None:
        raise ToolInputError("get_pod_logs needs a specific namespace")
    args = ["logs", check_name(pod, "pod"), "-n", ns]
    if container:
        if not CONTAINER_RE.match(container):
            raise ToolInputError(f"invalid container name '{container}'")
        args += ["-c", container]
    if previous:
        args.append("--previous")
    tail = max(1, min(int(tail or 200), MAX_LOG_TAIL))
    args.append(f"--tail={tail}")
    return args


def cmd_describe_deployment(namespace: str, deployment: str) -> list[str]:
    ns = check_namespace(namespace)
    if ns is None:
        raise ToolInputError("describe_deployment needs a specific namespace")
    return ["describe", "deployment", check_name(deployment, "deployment"), "-n", ns]


def cmd_list_nodes() -> list[str]:
    return ["get", "nodes", "-o", "wide"]


def cmd_describe_node(node: str) -> list[str]:
    return ["describe", "node", check_name(node, "node")]


def cmd_get_resources(kind: str, namespace: str | None = "all", name: str = "") -> list[str]:
    k = check_kind(kind, GET_KINDS)
    args = ["get", k]
    if name:
        args.append(check_name(name, "name"))
    if k not in CLUSTER_SCOPED:
        ns = check_namespace(namespace)
        if ns is None and name:
            raise ToolInputError("a specific name needs a specific namespace")
        args += _ns_args(ns)
    return args + ["-o", "wide"]


def cmd_describe_resource(kind: str, namespace: str, name: str) -> list[str]:
    k = check_kind(kind, DESCRIBE_KINDS)
    args = ["describe", k, check_name(name, "name")]
    if k not in CLUSTER_SCOPED:
        ns = check_namespace(namespace)
        if ns is None:
            raise ToolInputError("describe needs a specific namespace")
        args += ["-n", ns]
    return args


# -------------------------------------------------------------------- helpers
def clip(text: str, limit: int, keep: str = "head") -> str:
    if len(text) <= limit:
        return text
    note = f"\n...[truncated {len(text) - limit} chars]...\n"
    return (text[:limit] + note) if keep == "head" else (note + text[-limit:])


def _safe(backend: Backend, build, limit: int, keep: str = "head") -> str:
    try:
        args = build()
    except ToolInputError as exc:
        return f"REFUSED: {exc}"
    return clip(backend.run(args), limit, keep)


# ---------------------------------------------------------------- tool factory
def make_tools(backend: Backend, memory=None, max_chars: int = 12000) -> list[BaseTool]:
    """Build the LangChain tools bound to one backend (live cluster or eval fixture)."""

    @tool
    def list_pods(namespace: str = "all") -> str:
        """List pods with STATUS, RESTARTS and NODE. Use namespace='all' for every namespace.
        Start most investigations here."""
        return _safe(backend, lambda: cmd_list_pods(namespace), max_chars)

    @tool
    def get_events(namespace: str = "all") -> str:
        """Recent Kubernetes events sorted by time (scheduling failures, probe failures,
        image pull errors, OOM kills, back-offs). Use namespace='all' for the whole cluster."""
        return _safe(backend, lambda: cmd_events(namespace), max_chars, keep="tail")

    @tool
    def describe_pod(namespace: str, pod: str) -> str:
        """Full pod description: container state, last state, exit code, reason, probes,
        resource limits, mounts and the pod's events. Essential for CrashLoopBackOff,
        OOMKilled, ImagePullBackOff, Pending and probe failures."""
        return _safe(backend, lambda: cmd_describe_pod(namespace, pod), max_chars)

    @tool
    def get_pod_logs(namespace: str, pod: str, container: str = "", previous: bool = False, tail: int = 200) -> str:
        """Container logs. Set previous=True to read the logs of the last crashed
        container (needed for CrashLoopBackOff). tail is capped at 500 lines."""
        return _safe(backend, lambda: cmd_logs(namespace, pod, container, previous, tail), max_chars, keep="tail")

    @tool
    def describe_deployment(namespace: str, deployment: str) -> str:
        """Deployment description: replicas, rollout conditions, pod template, image,
        probes, resources and recent rollout events."""
        return _safe(backend, lambda: cmd_describe_deployment(namespace, deployment), max_chars)

    @tool
    def list_nodes() -> str:
        """List nodes with STATUS (Ready/NotReady), roles, version and IPs."""
        return _safe(backend, cmd_list_nodes, max_chars)

    @tool
    def describe_node(node: str) -> str:
        """Node description: conditions (MemoryPressure, DiskPressure, PIDPressure, Ready),
        taints, capacity/allocatable and allocated resources."""
        return _safe(backend, lambda: cmd_describe_node(node), max_chars)

    @tool
    def get_resources(kind: str, namespace: str = "all", name: str = "") -> str:
        """Generic read-only `kubectl get` for: deployments, replicasets, statefulsets,
        daemonsets, jobs, cronjobs, services, endpoints, endpointslices, ingresses,
        networkpolicies, configmaps (names only), pvc, pv, storageclasses, hpa, namespaces, nodes.
        Secrets are never readable."""
        return _safe(backend, lambda: cmd_get_resources(kind, namespace, name), max_chars)

    @tool
    def describe_resource(kind: str, namespace: str, name: str) -> str:
        """Generic read-only `kubectl describe` for services, ingresses, pvc, pv, hpa,
        statefulsets, daemonsets, jobs, networkpolicies, replicasets, deployments, nodes, pods."""
        return _safe(backend, lambda: cmd_describe_resource(kind, namespace, name), max_chars)

    tools: list[BaseTool] = [
        list_pods, get_events, describe_pod, get_pod_logs, describe_deployment,
        list_nodes, describe_node, get_resources, describe_resource,
    ]

    if memory is not None:

        @tool
        def recall_past_incidents(namespace: str) -> str:
            """Long-term memory: the most recent incidents this agent investigated in a
            namespace (or 'cluster'). Use it to spot recurring problems. Past incidents are
            hints, never evidence - always confirm with live data."""
            try:
                ns = check_namespace(namespace) or "cluster"
            except ToolInputError as exc:
                return f"REFUSED: {exc}"
            items = memory.recall(ns)
            return json.dumps(items, indent=2) if items else f"No past incidents recorded for '{ns}'."

        tools.append(recall_past_incidents)

    return tools
