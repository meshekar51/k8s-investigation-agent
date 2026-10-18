#!/usr/bin/env bash
# End-to-end test of a deployed agent against the broken lab workloads.
#   bash scripts/e2e-test.sh staging
# Proves: real investigations reach the right verdict, RBAC is read-only, memory is in PostgreSQL.
set -euo pipefail

ENV="${1:-staging}"
NS="agent-${ENV}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SA="system:serviceaccount:${NS}:sre-agent"
step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
fail() { echo "E2E FAILED: $*"; exit 1; }

step "lab workloads present"
kubectl apply -f "$ROOT/lab/broken-workloads.yaml" >/dev/null

wait_for() {  # wait_for <app label> <jsonpath> <expected value>
  for _ in $(seq 1 60); do
    got="$(kubectl -n lab get pods -l "app=$1" -o jsonpath="$2" 2>/dev/null || true)"
    [[ "$got" == *"$3"* ]] && { echo "$1: $3"; return 0; }
    sleep 5
  done
  fail "$1 never reached $3 (last: ${got:-none})"
}
wait_for oom-app '{.items[0].status.containerStatuses[0].lastState.terminated.reason}' OOMKilled
wait_for config-app '{.items[0].status.containerStatuses[0].state.waiting.reason}' CreateContainerConfigError

step "RBAC: the agent can look but not touch"
check() {  # check <expected yes|no> <kubectl auth can-i args...>
  want="$1"; shift
  got="$(kubectl auth can-i "$@" --as="$SA" 2>/dev/null || true)"
  printf '  %-40s %s\n' "$*" "$got"
  [[ "$got" == "$want" ]] || fail "can-i $* should be $want"
}
check yes list pods -A
check yes get pods/log -n lab
check no  get secrets -n lab
check no  delete pods -n lab
check no  create pods/exec -n lab

step "investigation 1: oom-app (expect category B)"
kubectl -n "$NS" exec deploy/sre-agent -- python -m app.smoke \
  --question "Pod oom-app in namespace lab keeps restarting. Investigate and give the root cause." \
  --expect-category B || fail "oom-app verdict"

step "investigation 2: config-app (expect category A or C)"
kubectl -n "$NS" exec deploy/sre-agent -- python -m app.smoke \
  --question "config-app in namespace lab is stuck and not running. Investigate." \
  --expect-category A,C || fail "config-app verdict"

step "memory: investigations are stored in PostgreSQL"
# shellcheck disable=SC2016  # $POSTGRES_* expand inside the database pod
rows="$(kubectl -n "$NS" exec sre-agent-db-0 -- sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select count(*) from store"')"
echo "  incident memory rows: ${rows}"
[[ "${rows:-0}" -ge 2 ]] || fail "expected >= 2 incident rows in PostgreSQL"
# shellcheck disable=SC2016
sessions="$(kubectl -n "$NS" exec sre-agent-db-0 -- sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select count(distinct thread_id) from checkpoints"')"
echo "  sessions stored: ${sessions}"

step "metrics exposed"
kubectl -n "$NS" exec deploy/sre-agent -- python -c \
  "import urllib.request;t=urllib.request.urlopen('http://127.0.0.1:8080/metrics/').read().decode();print([l for l in t.splitlines() if l.startswith('sre_agent_investigations_total')])"

echo
echo "E2E PASSED for ${NS}"
