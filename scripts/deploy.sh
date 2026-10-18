#!/usr/bin/env bash
# Build the image, load it into kind, deploy ONE environment, prove it works - or roll back.
#
#   bash scripts/deploy.sh staging
#   bash scripts/deploy.sh prod
#   SKIP_BUILD=1 IMAGE_TAG=<tag> bash scripts/deploy.sh prod      # image already built/pulled
#
# Bedrock credentials: if AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (+ AWS_SESSION_TOKEN) are set
# in your shell they are written to Secret sre-agent-aws; otherwise the existing Secret is kept.
set -euo pipefail

ENV="${1:?usage: scripts/deploy.sh <staging|prod>}"
case "$ENV" in staging|prod) ;; *) echo "environment must be staging or prod"; exit 2 ;; esac
NS="agent-${ENV}"
CLUSTER="${KIND_CLUSTER:-agentops-lab}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE_TAG="${IMAGE_TAG:-$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
IMAGE="k8s-sre-agent:${IMAGE_TAG}"
step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

kubectl config use-context "kind-${CLUSTER}" >/dev/null

# ---- governance gate: production must run behind the Bedrock guardrail ---------------
if [[ "$ENV" == "prod" ]] && grep -qE '^\s*- BEDROCK_GUARDRAIL_ID=\s*(#.*)?$' "$ROOT/deploy/app/base/kustomization.yaml"; then
  echo "ERROR: BEDROCK_GUARDRAIL_ID is empty in deploy/app/base/kustomization.yaml."
  echo "       Production requires the guardrail (README step 3). Refusing to deploy prod."
  exit 1
fi

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  step "build ${IMAGE}"
  docker build -t "$IMAGE" "$ROOT"
fi
step "load ${IMAGE} into kind cluster ${CLUSTER}"
kind load docker-image "$IMAGE" --name "$CLUSTER"

step "platform layer: namespaces + read-only RBAC"
kubectl apply -k "$ROOT/deploy/platform"

step "secrets in ${NS}"
RESTART=0
if [[ -n "${AWS_ACCESS_KEY_ID:-}" && -n "${AWS_SECRET_ACCESS_KEY:-}" ]]; then
  args=(--from-literal=AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" --from-literal=AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY")
  [[ -n "${AWS_SESSION_TOKEN:-}" ]] && args+=(--from-literal=AWS_SESSION_TOKEN="$AWS_SESSION_TOKEN")
  kubectl -n "$NS" create secret generic sre-agent-aws "${args[@]}" --dry-run=client -o yaml | kubectl apply -f -
  RESTART=1
elif ! kubectl -n "$NS" get secret sre-agent-aws >/dev/null 2>&1; then
  echo "ERROR: no Bedrock credentials. Export AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY (README step 4)."
  exit 1
fi
create_once() {  # never rotate silently: the database password is fixed at first start
  if ! kubectl -n "$NS" get secret "$1" >/dev/null 2>&1; then
    kubectl -n "$NS" create secret generic "$1" --from-literal="$2=$(openssl rand -hex 24)"
  fi
}
create_once sre-agent-db POSTGRES_PASSWORD
create_once sre-agent-auth API_TOKEN

step "apply deploy/app/overlays/${ENV} with image ${IMAGE}"
kubectl kustomize "$ROOT/deploy/app/overlays/${ENV}" \
  | sed "s|image: k8s-sre-agent:dev|image: ${IMAGE}|" \
  | kubectl apply -f -

step "wait for PostgreSQL"
kubectl -n "$NS" rollout status statefulset/sre-agent-db --timeout=240s

[[ "$RESTART" == "1" ]] && kubectl -n "$NS" rollout restart deploy/sre-agent >/dev/null

rollback() {
  echo "ERROR: $1 - rolling back ${NS}"
  kubectl -n "$NS" get pods -o wide || true
  kubectl -n "$NS" logs deploy/sre-agent --tail=50 || true
  kubectl -n "$NS" rollout undo deploy/sre-agent || echo "(first deploy: nothing to roll back to)"
  exit 1
}

step "wait for the agent rollout"
kubectl -n "$NS" rollout status deploy/sre-agent --timeout=300s || rollback "rollout did not become ready"

step "smoke test inside the pod (Bedrock + RBAC + PostgreSQL)"
kubectl -n "$NS" exec deploy/sre-agent -- python -m app.smoke || rollback "smoke test failed"

step "deployed ${IMAGE} to ${NS}"
echo "API token:  kubectl -n ${NS} get secret sre-agent-auth -o jsonpath='{.data.API_TOKEN}' | base64 -d"
