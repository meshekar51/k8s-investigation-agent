import pytest

from app import tools as t
from app.kube import MISSING_FIXTURE, FixtureBackend, fixture_key


def test_list_pods_all_namespaces():
    assert t.cmd_list_pods("all") == ["get", "pods", "-A", "-o", "wide"]
    assert t.cmd_list_pods("lab") == ["get", "pods", "-n", "lab", "-o", "wide"]


def test_logs_previous_and_tail_cap():
    args = t.cmd_logs("lab", "web-1", previous=True, tail=10_000)
    assert "--previous" in args and "--tail=500" in args


@pytest.mark.parametrize("bad", ["--kubeconfig=/etc/x", "a;rm -rf /", "UPPER", "$(id)", "../x", ""])
def test_rejects_injection_in_names(bad):
    with pytest.raises(t.ToolInputError):
        t.cmd_describe_pod("lab", bad)


@pytest.mark.parametrize("kind", ["secret", "secrets", "Secrets"])
def test_secrets_are_never_readable(kind):
    with pytest.raises(t.ToolInputError, match="Secrets"):
        t.cmd_get_resources(kind, "lab")


def test_aliases_and_cluster_scoped_kinds():
    assert t.cmd_get_resources("svc", "shop") == ["get", "services", "-n", "shop", "-o", "wide"]
    assert t.cmd_get_resources("nodes") == ["get", "nodes", "-o", "wide"]
    assert t.cmd_describe_resource("pvc", "db", "data-0") == ["describe", "persistentvolumeclaims", "data-0", "-n", "db"]


def test_tools_refuse_instead_of_crashing():
    tools = {tool.name: tool for tool in t.make_tools(FixtureBackend({}))}
    out = tools["get_resources"].invoke({"kind": "secrets", "namespace": "lab"})
    assert out.startswith("REFUSED")


def test_no_write_tools_exist():
    names = {tool.name for tool in t.make_tools(FixtureBackend({}))}
    for verb in ("delete", "apply", "edit", "patch", "exec", "scale", "rollout", "create"):
        assert not any(verb in n for n in names), f"write-capable tool found: {verb}"


def test_fixture_key_ignores_format_flags():
    assert fixture_key("kubectl logs p -n lab --tail=50".split()) == fixture_key(["logs", "p", "-n", "lab", "--tail=200"])
    assert fixture_key(["get", "pods", "-A", "-o", "wide"]) == "get pods -A"


def test_fixture_backend_replays_and_reports_missing():
    b = FixtureBackend({"kubectl get pods -A -o wide": "POD TABLE"})
    assert b.run(t.cmd_list_pods("all")) == "POD TABLE"
    assert b.run(t.cmd_list_nodes()) == MISSING_FIXTURE


def test_clip_keeps_tail_for_logs():
    out = t.clip("a" * 50 + "END", 10, keep="tail")
    assert out.endswith("END") and "truncated" in out
