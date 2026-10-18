"""Guards the eval dataset itself: a broken answer key is worse than no answer key."""

import pytest

from app.kube import fixture_key
from evals.run_evals import load_scenarios

SCENARIOS = load_scenarios()
VALID = {"A", "B", "C", "D", "E", "UNKNOWN"}


def test_seed_dataset_size():
    assert len(SCENARIOS) >= 14


@pytest.mark.parametrize("sc", SCENARIOS, ids=lambda s: s["id"])
def test_scenario_is_well_formed(sc):
    exp = sc["expected"]
    cats = exp["category"] if isinstance(exp["category"], list) else [exp["category"]]
    assert set(c.upper() for c in cats) <= VALID, "category must be A-E or UNKNOWN"
    assert exp["root_cause_all"], "answer key needs at least one keyword group"
    assert all(isinstance(g, list) and g for g in exp["root_cause_all"])
    assert len(sc["input"]) > 20
    keys = [fixture_key(k.split()) for k in sc["fixtures"]]
    assert len(keys) == len(set(keys)), "two fixtures normalise to the same command"
    assert any(k.startswith("get pods") for k in keys), "every scenario needs a pod listing"
