#!/usr/bin/env bash
# Installs everything this repo needs on Ubuntu 24.04 (amd64 or arm64). Safe to re-run:
# tools that are already installed are skipped.
#   bash scripts/install-ubuntu-tools.sh
set -euo pipefail

KIND_VERSION="${KIND_VERSION:-v0.33.0}"
KUBECTL_VERSION="${KUBECTL_VERSION:-v1.37.1}"
ARCH="$(dpkg --print-architecture)"          # amd64 | arm64
have() { command -v "$1" >/dev/null 2>&1; }
step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

step "base packages"
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl unzip jq git gnupg lsb-release openssl \
  python3 python3-venv python3-pip

if ! have docker; then
  step "docker"
  sudo apt-get install -y docker.io docker-buildx
  sudo systemctl enable --now docker
  sudo usermod -aG docker "$USER"
  echo "!! You were added to the 'docker' group. Run 'newgrp docker' (or log out/in) before the next step."
fi

if ! have kind; then
  step "kind ${KIND_VERSION}"
  curl -fsSLo /tmp/kind "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-${ARCH}"
  sudo install -m 0755 /tmp/kind /usr/local/bin/kind
fi

if ! have kubectl; then
  step "kubectl ${KUBECTL_VERSION}"
  curl -fsSLo /tmp/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl"
  curl -fsSLo /tmp/kubectl.sha256 "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl.sha256"
  echo "$(cat /tmp/kubectl.sha256)  /tmp/kubectl" | sha256sum -c -
  sudo install -m 0755 /tmp/kubectl /usr/local/bin/kubectl
fi

if ! have helm; then
  step "helm"
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

if ! have aws; then
  step "aws cli v2"
  curl -fsSLo /tmp/awscliv2.zip "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip"
  unzip -q -o /tmp/awscliv2.zip -d /tmp
  sudo /tmp/aws/install --update
fi

if ! have terraform; then
  step "terraform"
  curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor --yes -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
  echo "deb [arch=${ARCH} signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" \
    | sudo tee /etc/apt/sources.list.d/hashicorp.list >/dev/null
  sudo apt-get update -y && sudo apt-get install -y terraform
fi

step "kernel limits for multi-node kind (avoids 'too many open files')"
printf 'fs.inotify.max_user_watches = 524288\nfs.inotify.max_user_instances = 512\n' | sudo tee /etc/sysctl.d/99-kind.conf >/dev/null
sudo sysctl --system >/dev/null

step "versions"
docker --version || true
kind version
kubectl version --client | head -1
helm version --short
aws --version
terraform version | head -1
python3 --version
