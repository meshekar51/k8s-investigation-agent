from app.agent import InvestigationResult, parse_footer
from evals.scoring import score

SCENARIO = {
    "id": "oomkilled",
    "expected": {
        "category": ["B"],
        "root_cause_all": [["oom", "out of memory"], ["64mi", "memory limit"]],
        "must_not_claim": ["image pull"],
        "min_tool_calls": 2,
    },
}


def _result(footer, tools=("describe_pod", "get_pod_logs"), report=""):
    return InvestigationResult(session_id="s", report=report, footer=footer, tool_calls=list(tools))


def test_perfect_answer_scores_100():
    card = score(SCENARIO, _result({"category": "B", "subtype": "OOMKilled", "root_cause": "exceeds 64Mi memory limit"}))
    assert card.points == 100 and card.passed


def test_no_evidence_loses_points():
    card = score(SCENARIO, _result({"category": "B", "subtype": "OOMKilled", "root_cause": "64Mi limit"}, tools=()))
    assert card.points == 90 and not card.checks["evidence"]


def test_hallucinated_root_cause_fails_even_with_high_score():
    card = score(SCENARIO, _result({"category": "B", "subtype": "OOMKilled image pull", "root_cause": "64Mi limit"}))
    assert not card.passed and not card.checks["no_false_claim"]


def test_ruling_out_a_cause_in_the_report_is_not_a_false_claim():
    report = "ROOT CAUSE\nOOMKilled at 64Mi limit. Image pull problems were ruled out.\n----------------"
    card = score(SCENARIO, _result({"category": "B", "subtype": "OOMKilled", "root_cause": "64Mi memory limit"}, report=report))
    assert card.passed


def test_unknown_expected_accepts_insufficient_flag():
    sc = {"id": "x", "expected": {"category": "UNKNOWN", "root_cause_all": [["insufficient"]]}}
    card = score(sc, _result({"category": "C", "insufficient_evidence": True, "root_cause": "insufficient evidence"}))
    assert card.checks["category"]


def test_agent_error_scores_zero():
    r = InvestigationResult(session_id="s", report="", footer=None, error="AccessDeniedException")
    assert score(SCENARIO, r).points == 0


def test_parse_footer_takes_last_valid_block():
    text = 'blah ```json\n{"x": 1}\n``` more ```json\n{"category": "c", "root_cause": "r"}\n```'
    assert parse_footer(text) == {"category": "C", "root_cause": "r"}
    assert parse_footer("no footer here") is None
