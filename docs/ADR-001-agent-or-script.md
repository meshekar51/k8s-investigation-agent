# ADR-001: Do we need an agent, or is a script enough?

Status: Accepted · Transcript step 1 ("analyse if the agent is actually required")

## Question
On-call engineers spend the first 10-20 minutes of most Kubernetes incidents running the same
kubectl commands and reading describe/events/logs output. Can we automate that triage?

## Option A - a shell/Python script
A script can detect *known* patterns cheaply and deterministically:
`kubectl get pods -A | grep -E 'CrashLoopBackOff|ImagePullBackOff|Pending'` plus a lookup table.

- ✅ zero model cost, zero hallucination risk, trivial to run
- ❌ only answers questions we already wrote an `if` for
- ❌ cannot correlate evidence (events + exit code + logs + node state) into one root cause
- ❌ cannot explain itself or ask for the missing data

## Option B - an LLM agent with read-only tools
- ✅ follows the SRE investigation workflow on any failure shape, including unseen combinations
- ✅ correlates multiple signals and writes the incident report + remediation + verification
- ✅ says "insufficient evidence" instead of guessing (enforced by the prompt + evals)
- ❌ costs tokens per investigation, slower than a script (30-90 s)
- ❌ can be wrong → needs evals, guardrails, observability, read-only identity

## Decision
Build the agent **as a triage assistant only**: read-only, recommends but never executes.
Keep the script mindset where it wins: the eval suite and the smoke test are deterministic code,
and simple known checks (e.g. "is the pod listing empty?") stay in tools, not in the model.

## Re-evaluate when
- monthly Bedrock cost for the agent > the on-call time it saves, or
- eval pass rate stays below 80% after two prompt/tool iterations.
