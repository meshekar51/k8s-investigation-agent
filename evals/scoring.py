"""Grading an investigation against a scenario's expected output (transcript step 4).

Analogy: an exam with a marking scheme. Each scenario is a question; the "expected"
block is the teacher's answer key. 100 points per scenario:

  evidence    10  - did it call tools before answering? (rule 2: ALWAYS collect evidence)
  category    30  - right failure class (A..E, or UNKNOWN when evidence is insufficient)
  root cause  40  - every keyword group found in the verdict (one synonym per group is enough)
  no false    20  - none of the "must_not_claim" root causes (hallucination guard)
  claim

A scenario PASSES at >= 70 points AND with no hallucinated claim.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

PASS_MARK = 70


@dataclass
class ScoreCard:
    scenario_id: str
    points: int
    passed: bool
    checks: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _root_cause_section(report: str) -> str:
    m = re.search(r"ROOT CAUSE(.*?)(?:\n-{10,}|REMEDIATION|$)", report or "", re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else ""


def verdict_text(result) -> str:
    """What the agent CLAIMS as root cause: footer + the ROOT CAUSE section of the report."""
    f = result.footer or {}
    parts = [str(f.get("subtype", "")), str(f.get("root_cause", "")), _root_cause_section(result.report)]
    return " ".join(parts).lower()


def score(scenario: dict, result) -> ScoreCard:
    exp = scenario["expected"]
    sid = scenario["id"]
    card = ScoreCard(scenario_id=sid, points=0, passed=False)

    if result.error:
        card.notes.append(f"agent error: {result.error}")
        card.checks = {"evidence": False, "category": False, "root_cause": False, "no_false_claim": False}
        return card

    footer = result.footer or {}
    if not result.footer:
        card.notes.append("no machine-readable footer")
    text = verdict_text(result)

    # 1. evidence first
    min_calls = int(exp.get("min_tool_calls", 1))
    evidence_ok = len(result.tool_calls) >= min_calls
    if not evidence_ok:
        card.notes.append(f"only {len(result.tool_calls)} tool calls (need >= {min_calls})")

    # 2. category
    wanted = exp["category"] if isinstance(exp["category"], list) else [exp["category"]]
    wanted = [w.upper() for w in wanted]
    got = str(footer.get("category", "")).upper()
    if "UNKNOWN" in wanted:
        category_ok = got == "UNKNOWN" or footer.get("insufficient_evidence") is True
    else:
        category_ok = got in wanted
    if not category_ok:
        card.notes.append(f"category {got or '-'} not in {wanted}")

    # 3. root cause keyword groups
    groups = exp.get("root_cause_all", [])
    missed = [g for g in groups if not any(word.lower() in text for word in g)]
    root_ok = not missed
    if missed:
        card.notes.append("missing root-cause keywords: " + " | ".join("/".join(g) for g in missed))

    # 4. hallucination guard - checked on the one-line verdict only, because the report is
    #    SUPPOSED to discuss (and rule out) other causes in its "Possible / Less likely" list.
    claim = f"{footer.get('subtype', '')} {footer.get('root_cause', '')}".lower()
    false_claims = [w for w in exp.get("must_not_claim", []) if w.lower() in claim]
    guard_ok = not false_claims
    if false_claims:
        card.notes.append("claimed wrong root cause: " + ", ".join(false_claims))

    card.points = 10 * evidence_ok + 30 * category_ok + 40 * root_ok + 20 * guard_ok
    card.passed = card.points >= PASS_MARK and guard_ok
    card.checks = {"evidence": evidence_ok, "category": category_ok, "root_cause": root_ok, "no_false_claim": guard_ok}
    return card
